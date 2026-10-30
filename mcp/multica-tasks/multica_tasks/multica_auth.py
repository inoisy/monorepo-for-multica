"""Клиент API Multica для OAuth: кто вошёл (по сессии или PAT) и выпуск PAT от имени вошедшего.

Адрес берётся только из конфигурации. Сессия пользователя живёт в пределах одного вызова: ни cookie, ни CSRF-значение
не сохраняются и не логируются. Редиректы не выполняются: ответ на нестандартный адрес — отказ, а не переход.
"""
import json
import urllib.error
import urllib.request
from dataclasses import dataclass

SESSION_COOKIE = 'multica_auth'
CSRF_COOKIES = ('multica_csrf_session', 'multica_csrf')  # какое из двух принимает сервер, зависит от версии сессии
MAX_RESPONSE = 64 * 1024


class MulticaAuthError(Exception):
    """unauthenticated — Multica отказал (нет сессии, PAT отозван или истёк); unavailable — ответа нет или он не разобран."""

    def __init__(self, kind, message=''):
        super().__init__(message or kind)
        self.kind = kind


@dataclass(frozen=True)
class User:
    id: str
    name: str


@dataclass(frozen=True)
class IssuedPat:
    id: str
    token: str


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def session_from_cookie_header(header):
    """(значение сессионной cookie, значение для X-CSRF-Token) из заголовка Cookie браузера; пустые строки, если нет.

    Разбор по парам «имя=значение» через «;», как у Go net/http в Multica: SimpleCookie молча обрывает разбор на чужой
    cookie с пробелом или кавычкой, и вошедший пользователь выглядел бы невошедшим. Повтор имени — берём первое.
    """
    jar = {}
    for part in (header or '').split(';'):
        name, sep, value = part.strip().partition('=')
        value = value.strip()
        if len(value) > 1 and value[0] == value[-1] == '"':
            value = value[1:-1]
        if sep and name and name not in jar:
            jar[name] = value
    session = jar.get(SESSION_COOKIE, '')
    csrf = next((jar[n] for n in CSRF_COOKIES if jar.get(n)), '')
    return session, csrf


class MulticaApi:
    def __init__(self, base_url, timeout=8.0):
        self.base_url, self.timeout = base_url.rstrip('/'), timeout
        self._opener = urllib.request.build_opener(_NoRedirect)

    def me_by_session(self, session):
        if not session:
            raise MulticaAuthError('unauthenticated', 'нет сессии')
        return self._user(self._request('GET', '/api/me', {'Cookie': f'{SESSION_COOKIE}={session}'}))

    def me_by_pat(self, pat):
        return self._user(self._request('GET', '/api/me', {'Authorization': f'Bearer {pat}'}))

    def create_pat(self, session, csrf, name, days):
        if not session:
            raise MulticaAuthError('unauthenticated', 'нет сессии')
        body = json.dumps({'name': name, 'expires_in_days': days}).encode()
        data = self._request('POST', '/api/tokens', {'Cookie': f'{SESSION_COOKIE}={session}', 'X-CSRF-Token': csrf,
                                                     'Content-Type': 'application/json'}, body)
        token, pat_id = data.get('token'), data.get('id')
        if not (isinstance(token, str) and token and isinstance(pat_id, str) and pat_id):
            raise MulticaAuthError('unavailable', 'ответ создания токена не разобран')
        return IssuedPat(pat_id, token)

    @staticmethod
    def _user(data):
        user_id, name = data.get('id'), data.get('name')
        if not (isinstance(user_id, str) and user_id):
            raise MulticaAuthError('unavailable', 'ответ /api/me без id')
        return User(user_id, name.strip() if isinstance(name, str) and name.strip() else user_id)

    def _request(self, method, path, headers, body=None):
        request = urllib.request.Request(self.base_url + path, data=body, method=method, headers=headers)
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE + 1)
        except urllib.error.HTTPError as e:
            e.close()
            if e.code in (401, 403):
                raise MulticaAuthError('unauthenticated', f'Multica ответил {e.code}') from None
            raise MulticaAuthError('unavailable', f'Multica ответил {e.code}') from None
        except (OSError, ValueError):
            raise MulticaAuthError('unavailable', 'Multica недоступна') from None
        if len(raw) > MAX_RESPONSE:
            raise MulticaAuthError('unavailable', 'ответ Multica слишком большой')
        try:
            data = json.loads(raw)
        except ValueError:
            raise MulticaAuthError('unavailable', 'ответ Multica не JSON') from None
        if not isinstance(data, dict):
            raise MulticaAuthError('unavailable', 'неожиданный формат ответа Multica')
        return data
