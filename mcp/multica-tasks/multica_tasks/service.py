"""Владелец поведения: дедуп ранов, «зависшие», воркспейсы из allowlist, проекции, аудит.

HTTP-слой и JSON-RPC ничего из этого не решают, они зовут Service.call_tool.
"""
import datetime as dt
import logging
import re
import threading
import time
from collections import defaultdict
from dataclasses import dataclass

from . import projection, tools
from .audit import text_digest
from .errors import ApiError, ForbiddenCall, ToolError

log = logging.getLogger('multica_tasks')

# Раны, которые считаются «есть работа»: нового рана поверх не ставим.
ACTIVE_RUN = frozenset({'queued', 'dispatched', 'running', 'waiting_local_directory', 'deferred'})
STALE_STATUSES = ('todo', 'in_progress')
STATUS_KEY = re.compile(r'[a-z0-9_-]{1,40}')
UUID_RE = re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}')
ISSUE_REF = re.compile(rf'[A-Za-z][A-Za-z0-9]{{0,15}}-\d{{1,9}}|{UUID_RE.pattern}')
NOTE_PREFIX = '/note'
STALE_SCAN_LIMIT = 1000
PAGE = 100


@dataclass
class CallContext:
    """Что инструмент сообщает аудиту: чем занимался."""
    client_ip: str = ''
    workspace: str = ''
    issue: str = ''
    task_id: str = ''


def _parse_time(value):
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def _starts_with_note(text):
    parts = text.split(None, 1)
    return bool(parts) and parts[0].lower() == NOTE_PREFIX


class Service:
    def __init__(self, api, workspaces, audit, clock=time.time):
        self.api, self.allowed, self.audit, self.clock = api, tuple(workspaces), audit, clock
        self._workspaces = None
        self._meta = threading.Lock()
        self._issue_locks = defaultdict(threading.Lock)

    # --- вход ---------------------------------------------------------------------------------

    def call_tool(self, name, arguments, client_ip=''):
        """(is_error, payload). Ошибка API или аргументов — isError, а не исключение транспорта."""
        ctx = CallContext(client_ip=client_ip)
        spec = tools.TOOLS.get(name)
        if spec is None:
            return True, ToolError('unknown_tool', f'нет инструмента {name}').to_dict()
        args = arguments
        try:
            args = tools.validate(name, arguments)
            payload, is_error = getattr(self, name)(ctx, **args), False
        except ToolError as e:
            payload, is_error = e.to_dict(), True
        except ApiError as e:
            payload, is_error = ToolError(f'api_{e.status}' if e.status else 'api_unavailable', e.message).to_dict(), True
        except ForbiddenCall as e:
            log.error('вызов вне белого списка: %s', e)
            payload, is_error = ToolError('internal', 'операция запрещена политикой сервера').to_dict(), True
        except Exception:  # один плохой вызов не должен ронять сервер; текст исключения наружу не идёт
            log.exception('инструмент %s упал', name)
            payload, is_error = ToolError('internal', 'внутренняя ошибка сервера').to_dict(), True
        if spec['write']:
            self._audit(name, ctx, args, payload, is_error)
        return is_error, payload

    def _audit(self, name, ctx, args, payload, is_error):
        shown = dict(args) if isinstance(args, dict) else {'arguments': repr(args)[:200]}
        if isinstance(shown.get('text'), str):
            shown['text'] = text_digest(shown['text'])
        if is_error:
            result = {'ok': False, **payload['error']}
        else:
            result = {'ok': True, **{k: v for k, v in payload.items() if k in ('result', 'status', 'comment_id', 'woke', 'wake')}}
        try:
            self.audit.write(tool=name, workspace=ctx.workspace, issue=ctx.issue, task_id=ctx.task_id,
                             args=shown, result=result, client_ip=ctx.client_ip)
        except OSError:
            log.exception('не удалось записать аудит')

    # --- воркспейсы и сущности ----------------------------------------------------------------------

    def _allowed_workspaces(self):
        with self._meta:
            if self._workspaces is None:
                everything = self.api.get('/api/workspaces')
                wanted = {w.lower() for w in self.allowed}
                self._workspaces = [w for w in everything
                                    if {str(w.get('id', '')).lower(), str(w.get('slug', '')).lower()} & wanted]
            return self._workspaces

    def _workspace(self, ctx, ref=None):
        known = self._allowed_workspaces()
        if ref is None:
            if len(known) != 1:
                raise ToolError('invalid_argument', 'workspace: укажите воркспейс (' + ', '.join(w['slug'] for w in known) + ')')
            found = known[0]
        else:
            key = ref.strip().lower()
            found = next((w for w in known if key in (str(w['id']).lower(), str(w['slug']).lower(), str(w.get('name', '')).lower())), None)
            if found is None:
                raise ToolError('forbidden_workspace', f'воркспейс {ref!r} не разрешён этому коннектору')
        ctx.workspace = found['slug']
        return found['id']

    def _issue(self, ctx, ws_id, ref):
        if not ISSUE_REF.fullmatch(ref):
            raise ToolError('invalid_argument', 'issue: ключ вида TST-272 или UUID')
        issue = self.api.get(f'/api/issues/{ref}', ws_id)
        if issue.get('workspace_id') != ws_id:
            raise ToolError('not_found', f'задача {ref} не найдена в этом воркспейсе')
        ctx.issue = issue.get('identifier') or issue['id']
        return issue

    def _issue_lock(self, issue_id):
        with self._meta:
            return self._issue_locks[issue_id]

    def _principals(self, ws_id):
        """(агенты, сквады) воркспейса без архивных."""
        agents = [a for a in self.api.get('/api/agents', ws_id, workspace_id=ws_id) if not a.get('archived_at')]
        squads = [s for s in self.api.get('/api/squads', ws_id) if not s.get('archived_at')]
        return agents, squads

    @staticmethod
    def _match(items, ref):
        key = ref.strip().lower()
        if UUID_RE.fullmatch(key):
            return [i for i in items if str(i['id']).lower() == key]
        return [i for i in items if str(i.get('name', '')).lower() == key]

    def _resolve_agent(self, ws_id, ref):
        found = self._match(self._principals(ws_id)[0], ref)
        if len(found) != 1:
            raise ToolError('not_found' if not found else 'invalid_argument',
                            f'агент {ref!r} ' + ('не найден' if not found else 'неоднозначен, укажите UUID'))
        return found[0]

    def _resolve_assignee(self, ws_id, ref):
        agents, squads = self._principals(ws_id)
        found = [('agent', a) for a in self._match(agents, ref)] + [('squad', s) for s in self._match(squads, ref)]
        if len(found) != 1:
            raise ToolError('not_found' if not found else 'invalid_argument',
                            f'исполнитель {ref!r} ' + ('не найден среди агентов и сквадов' if not found else 'неоднозначен, укажите UUID'))
        return found[0][0], found[0][1]['id']

    def _executor(self, ws_id, issue):
        """Агент, который отработает ран: сам исполнитель или лидер сквада."""
        kind, ident = issue.get('assignee_type'), issue.get('assignee_id')
        if kind == 'agent' and ident:
            return ident
        if kind == 'squad' and ident:
            squad = next((s for s in self.api.get('/api/squads', ws_id) if s['id'] == ident), None)
            return squad.get('leader_id') if squad else None
        return None

    def _runs(self, ws_id, issue_id):
        return self.api.get(f'/api/issues/{issue_id}/task-runs', ws_id)

    def _active_run(self, ws_id, issue_id, agent_id):
        return next((t for t in self._runs(ws_id, issue_id)
                     if t.get('agent_id') == agent_id and t.get('status') in ACTIVE_RUN), None)

    def _active_by_issue(self, ws_id):
        snapshot = self.api.get('/api/agent-task-snapshot', ws_id)
        return [t for t in snapshot if t.get('status') in ACTIVE_RUN]

    # --- чтение ------------------------------------------------------------------------------------

    def list_workspaces(self, ctx):
        return {'workspaces': [projection.workspace(w) for w in self._allowed_workspaces()]}

    def list_agents(self, ctx, workspace=None):
        ws_id = self._workspace(ctx, workspace)
        agents, _ = self._principals(ws_id)
        active = {}
        for t in self._active_by_issue(ws_id):
            active.setdefault(t.get('agent_id'), []).append(
                {'task_id': t.get('id'), 'issue_id': t.get('issue_id'),
                 'issue_identifier': t.get('issue_identifier'), 'status': t.get('status')})
        return {'agents': [projection.agent(a, active.get(a['id'], [])) for a in agents]}

    def list_issues(self, ctx, workspace=None, status=None, assignee=None, stale_minutes=None, limit=50, offset=0):
        ws_id = self._workspace(ctx, workspace)
        if status is not None and not STATUS_KEY.fullmatch(status):
            raise ToolError('invalid_argument', 'status: ключ статуса, например in_progress')
        assignee_id = self._resolve_agent(ws_id, assignee)['id'] if assignee else None
        agents, squads = self._principals(ws_id)
        names = {p['id']: p.get('name') for p in (*agents, *squads)}
        if stale_minutes is not None:
            issues, page = self._stale(ws_id, status, assignee_id, stale_minutes)[offset:offset + limit], {}
        else:
            data = self.api.get('/api/issues', ws_id, workspace_id=ws_id, status=status, assignee_id=assignee_id,
                                limit=limit, offset=offset)
            issues, page = data.get('issues') or [], {'total': data.get('total'), 'has_more': data.get('has_more')}
        out = []
        for i in issues:
            row = projection.issue(i)
            row['assignee_name'] = names.get(i.get('assignee_id'))
            out.append(row)
        return {'issues': out, 'count': len(out), 'offset': offset, 'limit': limit, **page}

    def _stale(self, ws_id, status, assignee_id, minutes):
        statuses = STALE_STATUSES if status is None else ((status,) if status in STALE_STATUSES else ())
        busy = {t.get('issue_id') for t in self._active_by_issue(ws_id)}
        border = self.clock() - minutes * 60
        found = []
        for st in statuses:
            scanned = 0
            while scanned < STALE_SCAN_LIMIT:
                data = self.api.get('/api/issues', ws_id, workspace_id=ws_id, status=st, assignee_id=assignee_id,
                                    limit=PAGE, offset=scanned)
                batch = data.get('issues') or []
                for i in batch:
                    when = _parse_time(i.get('last_activity_at') or i.get('updated_at'))
                    if (i.get('assignee_type') in ('agent', 'squad') and i['id'] not in busy
                            and when is not None and when.timestamp() < border):
                        found.append(i)
                scanned += len(batch)
                if not data.get('has_more') or not batch:
                    break
        found.sort(key=lambda i: i.get('last_activity_at') or i.get('updated_at') or '')
        return found

    def get_issue(self, ctx, issue, workspace=None, comments=10):
        ws_id = self._workspace(ctx, workspace)
        data = self._issue(ctx, ws_id, issue)
        issue_id = data['id']
        recent = []
        if comments:
            all_comments = self.api.get(f'/api/issues/{issue_id}/comments', ws_id)
            all_comments = all_comments.get('comments', []) if isinstance(all_comments, dict) else all_comments
            recent = sorted(all_comments, key=lambda c: c.get('created_at') or '')[-comments:]
        return {'issue': projection.issue(data, with_description=True),
                'comments': [projection.comment(c) for c in recent],
                'runs': [projection.run(t) for t in self._runs(ws_id, issue_id)]}

    def list_agent_tasks(self, ctx, agent, workspace=None, limit=20):
        ws_id = self._workspace(ctx, workspace)
        found = self._resolve_agent(ws_id, agent)
        tasks = self.api.get(f'/api/agents/{found["id"]}/tasks', ws_id, limit=limit)
        return {'agent': {'id': found['id'], 'name': found.get('name')},
                'tasks': [projection.run(t) for t in tasks[:limit]]}

    # --- запись ------------------------------------------------------------------------------------

    def _wake(self, ws_id, issue):
        """Ровно один ран исполнителю. Вызывать под замком задачи."""
        agent_id = self._executor(ws_id, issue)
        if not agent_id:
            raise ToolError('no_agent_assignee', 'у задачи нет исполнителя-агента или сквада с лидером')
        active = self._active_run(ws_id, issue['id'], agent_id)
        if active:
            return {'result': 'already_active', 'task_id': active['id'], 'agent_id': agent_id, 'status': active.get('status')}
        task = self.api.post(f'/api/issues/{issue["id"]}/rerun', ws_id)
        return {'result': 'queued', 'task_id': task.get('id'), 'agent_id': agent_id}

    def wake_issue(self, ctx, issue, workspace=None):
        ws_id = self._workspace(ctx, workspace)
        ref = self._issue(ctx, ws_id, issue)
        with self._issue_lock(ref['id']):
            result = self._wake(ws_id, self.api.get(f'/api/issues/{ref["id"]}', ws_id))
        ctx.task_id = result.get('task_id') or ''
        return result

    def update_issue(self, ctx, issue, workspace=None, status=None, assignee=None, wake=None):
        if status is None and assignee is None:
            raise ToolError('invalid_argument', 'нужен status или assignee')
        if status is not None and not STATUS_KEY.fullmatch(status):
            raise ToolError('invalid_argument', 'status: ключ статуса, например in_progress')
        ws_id = self._workspace(ctx, workspace)
        ref = self._issue(ctx, ws_id, issue)
        # suppress_run всегда: ран ставит только _wake, иначе смена исполнителя + комментарий дают два рана
        body = {'suppress_run': True}
        if status is not None:
            body['status'] = status
        if assignee is not None:
            if assignee.strip().lower() in ('none', 'unassigned'):
                body.update(assignee_type=None, assignee_id=None)
            else:
                body['assignee_type'], body['assignee_id'] = self._resolve_assignee(ws_id, assignee)
        if wake is None:
            wake = assignee is not None
        with self._issue_lock(ref['id']):
            updated = self.api.put(f'/api/issues/{ref["id"]}', ws_id, body)
            result = {'issue': projection.issue(updated if updated.get('id') else {**ref, **body}), 'wake': None}
            if wake:
                try:
                    result['wake'] = self._wake(ws_id, self.api.get(f'/api/issues/{ref["id"]}', ws_id))
                    ctx.task_id = result['wake'].get('task_id') or ''
                except (ToolError, ApiError) as e:
                    code = e.code if isinstance(e, ToolError) else f'api_{e.status}'
                    result['wake'] = {'result': 'failed', 'code': code, 'message': e.message}
        return result

    def comment_issue(self, ctx, issue, text, workspace=None, wake=False):
        if not text.strip():
            raise ToolError('invalid_argument', 'text: пустой комментарий')
        if wake and _starts_with_note(text):
            raise ToolError('invalid_argument', 'wake=true несовместим с префиксом /note: такой комментарий рана не создаёт')
        ws_id = self._workspace(ctx, workspace)
        ref = self._issue(ctx, ws_id, issue)
        content = text if wake or _starts_with_note(text) else f'{NOTE_PREFIX} {text}'
        with self._issue_lock(ref['id']):
            before = {t['id'] for t in self._runs(ws_id, ref['id'])} if wake else set()
            created = self.api.post(f'/api/issues/{ref["id"]}/comments', ws_id, {'content': content})
            woke = [{'agent_id': t.get('agent_id'), 'task_id': t['id'], 'status': t.get('status')}
                    for t in self._runs(ws_id, ref['id']) if t['id'] not in before] if wake else []
        if woke:
            ctx.task_id = woke[0]['task_id']
        return {'comment_id': created.get('id'), 'posted_as_note': not wake, 'woke': woke}

    def cancel_task(self, ctx, task_id, workspace=None):
        if not UUID_RE.fullmatch(task_id):
            raise ToolError('invalid_argument', 'task_id: UUID рана')
        ws_id = self._workspace(ctx, workspace)
        ctx.task_id = task_id
        cancelled = self.api.post(f'/api/tasks/{task_id}/cancel', ws_id)
        return {'task_id': task_id, 'status': cancelled.get('status')}
