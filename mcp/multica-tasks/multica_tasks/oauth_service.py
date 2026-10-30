"""Владелец входа через OAuth: регистрация клиентов, согласие, code + PKCE, refresh, проверка и отзыв.

Сервер авторизации и resource server — один процесс. Личность проверяет Multica по сессии браузера; после явного
согласия выпускается отдельный PAT пользователя. Клиенту Claude уходят только токены этого сервиса, PAT и сессия — нет.
HTTP-слой маршрутизирует запросы сюда и сам ничего не решает.
"""
import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import stat
import time
import unicodedata
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from cryptography.fernet import Fernet, InvalidToken

from .config import ALL_WORKSPACES, Client, ConfigError
from .multica_auth import MulticaAuthError, session_from_cookie_header

log = logging.getLogger('multica_tasks.oauth')

SCOPE = 'multica'
SCOPES = ('multica', 'offline_access')
CODE_TTL = 120
ACCESS_TTL = 15 * 60
PENDING_TTL = 10 * 60
GRANT_TTL = 89 * 24 * 3600  # меньше срока PAT (90 дней): refresh не переживёт выпущенный PAT
PAT_DAYS = 90
MAX_CLIENTS = 2000
MAX_REDIRECT_URIS = 5
HOSTED_CALLBACKS = ('https://claude.ai/api/mcp/auth_callback', 'https://claude.com/api/mcp/auth_callback')
LOOPBACK_HOSTS = ('localhost', '127.0.0.1')
LOOPBACK_PATH = '/callback'
CHALLENGE_RE = re.compile(r'[A-Za-z0-9_-]{43}')
VERIFIER_RE = re.compile(r'[A-Za-z0-9._~-]{43,128}')
REQUEST_ID_RE = re.compile(r'[A-Za-z0-9_-]{22,64}')
MAX_STATE = 512


class OAuthError(Exception):
    """error — код OAuth (RFC 6749 §5.2), status — HTTP-код ответа token/register endpoint."""

    def __init__(self, error, description='', status=400):
        super().__init__(description or error)
        self.error, self.description, self.status = error, description, status


class Unavailable(Exception):
    """Multica не ответила: доступ закрыт временной ошибкой, grant не трогаем."""


class PageError(Exception):
    """Ошибка до проверки redirect_uri: пользователю показываем страницу, по redirect_uri не возвращаем."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _new_secret():
    return secrets.token_urlsafe(32)


def _loopback(uri):
    parts = urlsplit(uri)
    return parts.scheme == 'http' and parts.hostname in LOOPBACK_HOSTS and parts.path == LOOPBACK_PATH


def valid_redirect_uri(uri):
    if uri in HOSTED_CALLBACKS:
        return True
    try:
        parts = urlsplit(uri)
        parts.port  # noqa: B018 — проверка корректности порта
    except ValueError:
        return False
    return _loopback(uri) and not parts.query and not parts.fragment and not parts.username and not parts.password


def redirect_matches(registered, requested):
    """Облачные адреса — точное совпадение; loopback — без учёта порта (RFC 8252 §7.3), хост и путь те же."""
    if requested in registered:
        return True
    if not _loopback(requested):
        return False
    wanted = urlsplit(requested)
    for uri in registered:
        if _loopback(uri):
            known = urlsplit(uri)
            if known.hostname == wanted.hostname and known.path == wanted.path and not wanted.query and not wanted.fragment:
                return True
    return False


def _with_params(uri, params):
    parts = urlsplit(uri)
    query = parse_qsl(parts.query, keep_blank_values=True) + [(k, v) for k, v in params.items() if v is not None]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ''))


def _printable(text, limit):
    cleaned = ''.join(c for c in unicodedata.normalize('NFC', text) if c.isprintable()).strip()
    return cleaned[:limit]


def load_key(path):
    try:
        mode = path.stat().st_mode
        raw = path.read_bytes().strip()
    except OSError as e:
        raise ConfigError(f'MULTICA_MCP_OAUTH_KEY_FILE: файл недоступен ({e.strerror})') from None
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise ConfigError('MULTICA_MCP_OAUTH_KEY_FILE: файл должен быть доступен только владельцу (0600)')
    try:
        Fernet(raw)
    except ValueError:
        raise ConfigError('MULTICA_MCP_OAUTH_KEY_FILE: ожидается ключ Fernet (32 байта в url-safe base64)') from None
    return raw


class OAuthService:
    def __init__(self, config, store, api, key, redactor, clock=time.time):
        self.config, self.store, self.api, self.redactor, self.clock = config, store, api, redactor, clock
        self._fernet = Fernet(key)
        self._csrf_key = hashlib.sha256(b'consent-csrf\0' + key).digest()
        self.issuer = config.public_url
        self.resource = config.public_url + '/mcp'

    # --- метаданные -------------------------------------------------------------------------------

    def protected_resource_metadata(self):
        return {'resource': self.resource, 'authorization_servers': [self.issuer], 'scopes_supported': list(SCOPES),
                'bearer_methods_supported': ['header'], 'resource_name': 'Multica'}

    def authorization_server_metadata(self):
        base = self.issuer + '/mcp/oauth'
        return {'issuer': self.issuer, 'authorization_endpoint': base + '/authorize', 'token_endpoint': base + '/token',
                'registration_endpoint': base + '/register', 'revocation_endpoint': base + '/revoke',
                'response_types_supported': ['code'], 'grant_types_supported': ['authorization_code', 'refresh_token'],
                'code_challenge_methods_supported': ['S256'], 'token_endpoint_auth_methods_supported': ['none'],
                'scopes_supported': list(SCOPES)}

    @property
    def challenge_header(self):
        return f'Bearer resource_metadata="{self.issuer}/.well-known/oauth-protected-resource/mcp"'

    # --- регистрация клиента (DCR) ----------------------------------------------------------------

    def register(self, meta):
        if not isinstance(meta, dict):
            raise OAuthError('invalid_client_metadata', 'нужен JSON-объект')
        uris = meta.get('redirect_uris')
        if (not isinstance(uris, list) or not uris or len(uris) > MAX_REDIRECT_URIS
                or not all(isinstance(u, str) and valid_redirect_uri(u) for u in uris)):
            raise OAuthError('invalid_redirect_uri', 'redirect_uris: разрешены только callback Claude и loopback http://localhost|127.0.0.1/callback')
        if meta.get('token_endpoint_auth_method', 'none') != 'none':
            raise OAuthError('invalid_client_metadata', 'token_endpoint_auth_method: только none (public client)')
        grants = meta.get('grant_types', ['authorization_code'])
        if (not isinstance(grants, list) or not grants
                or not set(grants) <= {'authorization_code', 'refresh_token'} or not all(isinstance(g, str) for g in grants)):
            raise OAuthError('invalid_client_metadata', 'grant_types: authorization_code и refresh_token')
        if meta.get('response_types', ['code']) != ['code']:
            raise OAuthError('invalid_client_metadata', 'response_types: только code')
        name = meta.get('client_name', 'MCP-клиент')
        if not isinstance(name, str) or not _printable(name, 100):
            raise OAuthError('invalid_client_metadata', 'client_name: непустая строка')
        name = _printable(name, 100)
        if self.store.count_clients() >= MAX_CLIENTS:
            raise OAuthError('invalid_client_metadata', 'слишком много зарегистрированных клиентов', 503)
        client_id = secrets.token_urlsafe(24)
        self.store.add_client(client_id, name, uris, self.clock())
        return {'client_id': client_id, 'client_name': name, 'redirect_uris': uris, 'grant_types': ['authorization_code', 'refresh_token'],
                'response_types': ['code'], 'token_endpoint_auth_method': 'none', 'scope': ' '.join(SCOPES)}

    # --- запрос авторизации -----------------------------------------------------------------------

    def begin_authorize(self, params):
        """Идентификатор сохранённого запроса. PageError — redirect_uri недоверенный; OAuthError.redirect — вернуть клиенту."""
        client = self.store.get_client(params.get('client_id', ''))
        redirect_uri = params.get('redirect_uri', '')
        if not client:
            raise PageError('Неизвестное приложение. Добавьте коннектор заново.')
        if not redirect_matches(client['redirect_uris'], redirect_uri):
            raise PageError('Адрес возврата не зарегистрирован для этого приложения.')
        state = params.get('state')
        if state is not None and len(state) > MAX_STATE:
            raise PageError('Слишком длинный state.')

        def fail(error, description):
            exc = OAuthError(error, description)
            exc.redirect = _with_params(redirect_uri, {'error': error, 'error_description': description, 'state': state})
            return exc

        if params.get('response_type') != 'code':
            raise fail('unsupported_response_type', 'нужен response_type=code')
        challenge = params.get('code_challenge', '')
        if params.get('code_challenge_method') != 'S256' or not CHALLENGE_RE.fullmatch(challenge):
            raise fail('invalid_request', 'нужен PKCE: code_challenge_method=S256 и code_challenge')
        if params.get('resource', self.resource) != self.resource:
            raise fail('invalid_target', 'resource не совпадает с ' + self.resource)
        scope = params.get('scope', '').split()
        if not set(scope) <= set(SCOPES):
            raise fail('invalid_scope', 'неизвестный scope')
        req_id = secrets.token_urlsafe(24)
        self.store.put_pending(req_id, client['client_id'], redirect_uri, state, challenge, self.resource,
                               SCOPE, self.clock() + PENDING_TTL)
        return req_id

    def pending_view(self, req_id):
        """Данные для экрана согласия или None, если запрос истёк/неизвестен."""
        if not REQUEST_ID_RE.fullmatch(req_id or ''):
            return None
        pending = self.store.get_pending(req_id, self.clock())
        if not pending:
            return None
        client = self.store.get_client(pending['client_id'])
        return {'client_name': client['name'], 'return_host': urlsplit(pending['redirect_uri']).hostname}

    def whoami(self, cookie_header):
        """Пользователь Multica по сессии браузера или None, если не вошёл. Unavailable — Multica не ответила."""
        session, _ = session_from_cookie_header(cookie_header)
        try:
            return self.api.me_by_session(session)
        except MulticaAuthError as e:
            if e.kind == 'unauthenticated':
                return None
            raise Unavailable() from None

    def csrf_token(self, req_id, user_id):
        return hmac.new(self._csrf_key, f'{req_id}\0{user_id}'.encode(), hashlib.sha256).hexdigest()

    def decide(self, cookie_header, req_id, csrf, approve):
        """Адрес возврата клиенту. Без входа — OAuthError('login_required'), с неверным CSRF — 'invalid_csrf'."""
        user = self.whoami(cookie_header)
        if user is None:
            raise OAuthError('login_required', 'нужен вход в Multica', 401)
        if not hmac.compare_digest(self.csrf_token(req_id or '', user.id), csrf or ''):
            raise OAuthError('invalid_csrf', 'форма согласия устарела, начните подключение заново', 403)
        pending = self.store.take_pending(req_id, self.clock())
        if not pending:
            raise OAuthError('expired_request', 'запрос подключения истёк, начните заново', 400)
        redirect_uri, state = pending['redirect_uri'], pending['state']
        if not approve:
            return _with_params(redirect_uri, {'error': 'access_denied', 'state': state})
        client = self.store.get_client(pending['client_id'])
        session, csrf_cookie = session_from_cookie_header(cookie_header)
        stamp = time.strftime('%Y-%m-%d', time.gmtime(self.clock()))
        try:
            pat = self.api.create_pat(session, csrf_cookie, f'Claude MCP: {client["name"][:40]} ({stamp})', PAT_DAYS)
        except MulticaAuthError as e:
            if e.kind == 'unauthenticated':
                raise OAuthError('login_required', 'сессия Multica истекла', 401) from None
            raise Unavailable() from None
        self.redactor.add(pat.token)
        now = self.clock()
        grant = {'id': secrets.token_urlsafe(16), 'client_id': client['client_id'], 'user_id': user.id, 'user_name': user.name,
                 'pat_id': pat.id, 'pat_cipher': self._fernet.encrypt(pat.token.encode()), 'scope': pending['scope'],
                 'created': now, 'expires': now + GRANT_TTL}
        code = _new_secret()
        self.store.create_grant_with_code(grant, _hash(code), {
            'client_id': client['client_id'], 'redirect_uri': redirect_uri, 'challenge': pending['challenge'],
            'resource': pending['resource'], 'expires': now + CODE_TTL})
        log.info('grant выдан', extra={'ctx': {'user_id': user.id, 'client': client['name']}})
        return _with_params(redirect_uri, {'code': code, 'state': state})

    # --- token endpoint ---------------------------------------------------------------------------

    def token(self, form):
        client = self.store.get_client(form.get('client_id', ''))
        if not client:
            raise OAuthError('invalid_client', 'неизвестный client_id', 401)
        grant_type = form.get('grant_type')
        if grant_type == 'authorization_code':
            return self._exchange_code(client, form)
        if grant_type == 'refresh_token':
            return self._refresh(client, form)
        raise OAuthError('unsupported_grant_type', 'поддерживаются authorization_code и refresh_token')

    def _exchange_code(self, client, form):
        code, verifier = form.get('code', ''), form.get('code_verifier', '')
        if not code or not VERIFIER_RE.fullmatch(verifier):
            raise OAuthError('invalid_request', 'нужны code и code_verifier')
        row, reused = self.store.redeem_code(_hash(code))
        if row is None:
            raise OAuthError('invalid_grant', 'code неизвестен')
        if reused:
            self.store.revoke_grant(row['grant_id'])  # повтор code — признак кражи: всё выданное по нему блокируем
            raise OAuthError('invalid_grant', 'code уже использован')
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        problems = (row['expires'] <= self.clock(), row['client_id'] != client['client_id'],
                    form.get('redirect_uri') != row['redirect_uri'],
                    not hmac.compare_digest(challenge.encode(), row['challenge'].encode()),
                    form.get('resource', row['resource']) != row['resource'])
        if any(problems):
            self.store.revoke_grant(row['grant_id'])
            raise OAuthError('invalid_grant', 'code не подходит: просрочен или не совпал клиент, redirect_uri, verifier или resource')
        grant = self.store.get_grant(row['grant_id'])
        self._check_grant(grant)
        return self._issue(grant)

    def _refresh(self, client, form):
        old = form.get('refresh_token', '')
        row = self.store.get_token(_hash(old)) if old else None
        if not row or row['kind'] != 'refresh':
            raise OAuthError('invalid_grant', 'refresh_token неизвестен')
        grant = self.store.get_grant(row['grant_id'])
        if grant is None or grant['client_id'] != client['client_id']:
            raise OAuthError('invalid_grant', 'refresh_token выдан другому клиенту')
        if form.get('resource', self.resource) != self.resource:
            raise OAuthError('invalid_target', 'resource не совпадает')
        if row['used']:
            self.store.revoke_grant(grant['id'])  # повторное использование: семейство токенов блокируется целиком
            raise OAuthError('invalid_grant', 'refresh_token уже использован')
        if row['expires'] <= self.clock():
            raise OAuthError('invalid_grant', 'refresh_token истёк')
        self._check_grant(grant)
        self._live(grant)  # отозванный в Multica PAT не даёт обновить токены
        return self._issue(grant, rotate=_hash(old))

    def _check_grant(self, grant):
        if grant is None or grant['revoked'] or grant['expires'] <= self.clock():
            raise OAuthError('invalid_grant', 'доступ отозван или истёк')

    def _issue(self, grant, rotate=None):
        now = self.clock()
        access, refresh = _new_secret(), _new_secret()
        access_hash, refresh_hash = _hash(access), _hash(refresh)
        if rotate:
            if not self.store.rotate_refresh(rotate, grant['id'], access_hash, now + ACCESS_TTL, refresh_hash, grant['expires']):
                self.store.revoke_grant(grant['id'])
                raise OAuthError('invalid_grant', 'refresh_token уже использован')
        else:
            self.store.put_tokens(grant['id'], access_hash, now + ACCESS_TTL, refresh_hash, grant['expires'])
        return {'access_token': access, 'token_type': 'Bearer', 'expires_in': ACCESS_TTL, 'refresh_token': refresh,
                'scope': SCOPE}

    def revoke(self, form):
        """Идемпотентно: чужой или неизвестный токен молча игнорируется. PAT в Multica не удаляется."""
        token = form.get('token', '')
        row = self.store.get_token(_hash(token)) if token else None
        if row:
            grant = self.store.get_grant(row['grant_id'])
            if grant and grant['client_id'] == form.get('client_id'):
                self.store.revoke_grant(grant['id'])

    # --- проверка токена на /mcp ------------------------------------------------------------------

    def authenticate(self, token):
        """Client для запроса к /mcp или None, если токен не наш/просрочен/отозван. Unavailable — Multica не ответила."""
        row = self.store.get_token(_hash(token)) if token else None
        if not row or row['kind'] != 'access' or row['expires'] <= self.clock():
            return None
        grant = self.store.get_grant(row['grant_id'])
        if grant is None or grant['revoked'] or grant['expires'] <= self.clock():
            return None
        try:
            pat, user = self._live(grant)
        except OAuthError:
            return None
        return Client(user.name, '', pat, (ALL_WORKSPACES,), False, ident=grant['user_id'], source='oauth')

    def _live(self, grant):
        """(PAT, пользователь): PAT расшифрован и действует в Multica прямо сейчас — положительного кэша нет."""
        try:
            pat = self._fernet.decrypt(grant['pat_cipher']).decode()
        except InvalidToken:
            raise OAuthError('invalid_grant', 'PAT не расшифровывается: ключ сервиса сменён') from None
        self.redactor.add(pat)
        try:
            user = self.api.me_by_pat(pat)
        except MulticaAuthError as e:
            if e.kind == 'unauthenticated':
                self.store.revoke_grant(grant['id'])
                raise OAuthError('invalid_grant', 'PAT отозван или истёк в Multica') from None
            raise Unavailable() from None
        if user.id != grant['user_id']:
            self.store.revoke_grant(grant['id'])
            raise OAuthError('invalid_grant', 'PAT принадлежит другому пользователю')
        return pat, user

    def purge(self):
        self.store.purge(self.clock())
