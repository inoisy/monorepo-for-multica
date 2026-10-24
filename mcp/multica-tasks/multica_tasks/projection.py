"""Проекции ответов API: наружу идёт только перечисленное. Новое поле в API не попадёт в ответ само.

Это граница утечек: у агентов в API есть instructions, custom_env, mcp_config, а у задач — вложения и ссылки на файлы.
"""
ISSUE = ('id', 'identifier', 'title', 'status', 'status_name', 'priority', 'assignee_type', 'assignee_id',
         'creator_type', 'creator_id', 'project_id', 'parent_issue_id', 'stage', 'due_date',
         'created_at', 'updated_at', 'last_activity_at')
COMMENT = ('id', 'parent_id', 'type', 'author_type', 'author_id', 'created_at', 'updated_at')
RUN = ('id', 'issue_id', 'issue_identifier', 'agent_id', 'status', 'kind', 'attempt', 'max_attempts',
       'created_at', 'dispatched_at', 'started_at', 'completed_at', 'failure_reason')
AGENT = ('id', 'name', 'status', 'visibility', 'max_concurrent_tasks', 'archived_at', 'updated_at')
SQUAD = ('id', 'name', 'leader_id')
WORKSPACE = ('id', 'name', 'slug')

DESCRIPTION_LIMIT = 20000
COMMENT_LIMIT = 8000
ERROR_LIMIT = 500
AGENT_DESCRIPTION_LIMIT = 300


def _pick(source, fields):
    return {k: source.get(k) for k in fields if k in source}


def _clip(value, limit):
    return value if not isinstance(value, str) or len(value) <= limit else value[:limit] + '…'


def workspace(w):
    return _pick(w, WORKSPACE)


def issue(i, with_description=False):
    out = _pick(i, ISSUE)
    if with_description:
        out['description'] = _clip(i.get('description') or '', DESCRIPTION_LIMIT)
    return out


def comment(c):
    out = _pick(c, COMMENT)
    out['content'] = _clip(c.get('content') or '', COMMENT_LIMIT)
    return out


def run(t):
    out = _pick(t, RUN)
    if t.get('error'):
        out['error'] = _clip(str(t['error']), ERROR_LIMIT)
    return out


def agent(a, active_tasks):
    out = _pick(a, AGENT)
    out['description'] = _clip(a.get('description') or '', AGENT_DESCRIPTION_LIMIT)
    out['active_tasks'] = active_tasks
    return out


def squad(s):
    return _pick(s, SQUAD)
