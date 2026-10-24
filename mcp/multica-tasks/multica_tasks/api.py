"""REST-клиент Multica. Ходит только по белому списку пар (метод, шаблон пути); PAT — из конфигурации, в ошибки не попадает."""
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from .errors import ApiError, ForbiddenCall

UUID = r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
# Ключ задачи в пути принимает и UUID, и «TST-272»: сервер разбирает оба.
ISSUE = rf'(?:{UUID}|[A-Za-z][A-Za-z0-9]{{0,15}}-\d{{1,9}})'

ALLOWED = tuple((method, re.compile(pattern)) for method, pattern in (
    ('GET', r'/api/workspaces'),
    ('GET', r'/api/agents'),
    ('GET', r'/api/squads'),
    ('GET', r'/api/agent-task-snapshot'),
    ('GET', r'/api/issues'),
    ('GET', rf'/api/issues/{ISSUE}'),
    ('GET', rf'/api/issues/{ISSUE}/comments'),
    ('GET', rf'/api/issues/{ISSUE}/task-runs'),
    ('GET', rf'/api/agents/{UUID}/tasks'),
    ('PUT', rf'/api/issues/{ISSUE}'),
    ('POST', rf'/api/issues/{ISSUE}/comments'),
    ('POST', rf'/api/issues/{ISSUE}/rerun'),
    ('POST', rf'/api/tasks/{UUID}/cancel'),
))
MAX_RESPONSE = 8 * 1024 * 1024
MAX_ERROR_TEXT = 300


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Редирект с токеном в заголовке — утечка PAT на чужой адрес."""

    def redirect_request(self, *a, **k):
        return None


def is_allowed(method, path):
    return any(m == method and p.fullmatch(path) for m, p in ALLOWED)


class Api:
    def __init__(self, base_url, pat, timeout=20.0, secrets=(), opener=None):
        self.base_url, self.timeout = base_url.rstrip('/'), timeout
        self._pat = pat
        self._secrets = tuple(s for s in (pat, *secrets) if s)
        self._opener = opener or urllib.request.build_opener(_NoRedirect)

    def _scrub(self, text):
        for secret in self._secrets:
            text = text.replace(secret, '[redacted]')
        return text

    def request(self, method, path, workspace_id=None, query=None, body=None):
        if not is_allowed(method, path):
            raise ForbiddenCall(f'{method} {path} вне белого списка')
        url = self.base_url + path
        if query:
            url += '?' + urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
        headers = {'Authorization': f'Bearer {self._pat}', 'Accept': 'application/json', 'User-Agent': 'multica-tasks-mcp'}
        if workspace_id:
            headers['X-Workspace-ID'] = workspace_id
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode()
            headers['Content-Type'] = 'application/json'
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                raw = resp.read(MAX_RESPONSE + 1)
        except urllib.error.HTTPError as e:
            raise ApiError(e.code, self._error_text(e.read(4096))) from None
        except (urllib.error.URLError, OSError) as e:
            raise ApiError(0, self._scrub(f'Multica API недоступен: {getattr(e, "reason", e)}')) from None
        if len(raw) > MAX_RESPONSE:
            raise ApiError(0, 'ответ Multica API слишком большой')
        if not raw.strip():
            return {}
        try:
            return json.loads(raw)
        except ValueError:
            raise ApiError(0, 'Multica API вернул не JSON') from None

    def _error_text(self, raw):
        text = raw.decode('utf-8', 'replace')
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                text = str(parsed.get('error') or parsed.get('message') or text)
        except ValueError:
            pass
        return self._scrub(text.strip())[:MAX_ERROR_TEXT]

    def get(self, path, ws=None, **query):
        return self.request('GET', path, ws, query)

    def put(self, path, ws, body):
        return self.request('PUT', path, ws, body=body)

    def post(self, path, ws, body=None):
        return self.request('POST', path, ws, body={} if body is None else body)
