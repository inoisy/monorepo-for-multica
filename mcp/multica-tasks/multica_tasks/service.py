"""Владелец поведения: проверка команды по allowlist, воркспейс клиента, запуск CLI от его токена, аудит.

HTTP-слой и JSON-RPC ничего из этого не решают, они зовут Service.call_tool.
"""
import json
import logging
import re
import threading

from . import policy, tools
from .audit import text_digest
from .errors import InvalidParams, ToolError

log = logging.getLogger('multica_tasks')

UUID_RE = re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}')
AUDIT_ARG_CHARS = 500


class Service:
    def __init__(self, runner, audit):
        self.runner, self.audit = runner, audit
        self.redact = audit.redact
        self._workspaces = {}  # имя клиента → [{id, slug, name}] из `workspace list`
        self._meta = threading.Lock()

    def call_tool(self, name, arguments, client_ip='', client=None):
        """(is_error, payload). Нарушение allowlist или формы аргументов — InvalidParams (-32602)."""
        if name not in tools.TOOLS:
            raise InvalidParams(f'нет инструмента {name}')
        args, stdin, workspace = tools.validate(arguments)
        entry = {'client': client.name, 'client_ip': client_ip, 'argv': [a[:AUDIT_ARG_CHARS] for a in args]}
        try:
            prefix = policy.check(args)
        except InvalidParams as e:
            self._audit(entry | {'denied': e.denied, 'exit_code': None})
            raise
        try:
            workspace_id = self._workspace_id(client, workspace) if policy.needs_workspace(prefix, args) else ''
        except InvalidParams as e:
            self._audit(entry | {'denied': e.message, 'exit_code': None})
            raise
        except ToolError as e:
            self._audit(entry | {'denied': None, 'exit_code': None, 'error': e.message})
            return True, e.to_dict()
        argv = args + ['--output', 'json'] if policy.wants_output_flag(args) else args
        result = self.runner.run(client.token, argv, stdin, workspace_id)
        entry |= {'denied': None, 'exit_code': result.exit_code, 'timeout': result.timeout,
                  'duration': result.duration, 'stdin_length': result.stdin_length, 'stdout_length': result.stdout_length}
        if stdin:
            entry['stdin'] = text_digest(stdin, self.audit.redact)
        self._audit(entry)
        return result.exit_code != 0, result.to_dict()

    def _audit(self, entry):
        try:
            self.audit.write(tool='multica', **entry)
        except OSError:
            log.exception('не удалось записать аудит')

    # --- воркспейс клиента ---------------------------------------------------------------------

    def _workspace_id(self, client, ref):
        wanted = [w for w in client.workspaces]
        if ref is None:
            if len(wanted) != 1:
                raise InvalidParams('workspace: укажите воркспейс (' + ', '.join(wanted) + ')')
            ref = wanted[0]
        key = ref.lower()
        if UUID_RE.fullmatch(ref) and key in (w.lower() for w in wanted):
            return ref
        for known in self._known(client):
            if key in (str(known.get('id', '')).lower(), str(known.get('slug', '')).lower(), str(known.get('name', '')).lower()):
                return str(known['id'])
        raise InvalidParams(f'workspace: {ref!r} не разрешён этому ключу (' + ', '.join(wanted) + ')')

    def _known(self, client):
        """Воркспейсы из allowlist клиента: id и slug берём из `workspace list` его же токеном."""
        with self._meta:
            if client.name not in self._workspaces:
                wanted = {w.lower() for w in client.workspaces}
                result = self.runner.run(client.token, ['workspace', 'list', '--output', 'json'])
                if result.exit_code != 0:
                    raise ToolError('workspace_lookup_failed', 'не удалось получить список воркспейсов: ' + result.stderr.strip()[:300])
                try:
                    rows = json.loads(result.stdout)
                except ValueError:
                    raise ToolError('workspace_lookup_failed', 'список воркспейсов: ответ не JSON') from None
                rows = rows.get('workspaces') if isinstance(rows, dict) else rows
                if not isinstance(rows, list):
                    raise ToolError('workspace_lookup_failed', 'список воркспейсов: неожиданный формат ответа')
                self._workspaces[client.name] = [
                    w for w in rows if isinstance(w, dict)
                    and wanted & {str(w.get('id', '')).lower(), str(w.get('slug', '')).lower()}]
            return self._workspaces[client.name]
