"""Доверенная проверка multica-tasks-mcp: контракт, который кандидат не вправе менять вместе со своими тестами.

Аргумент — каталог кандидата (mcp/multica-tasks). Проверяется то, что делает публичный сервер безопасным:
ровно девять инструментов без удаления, белый список запросов без DELETE и админских путей, ключ сравнивается
через hmac.compare_digest, бинарь запускается изолированным интерпретатором.
"""
import importlib
import re
import sys
from pathlib import Path

work = Path(sys.argv[1])
sys.path.insert(0, str(work))

EXPECTED = {'list_workspaces', 'list_agents', 'list_issues', 'get_issue', 'list_agent_tasks',
            'comment_issue', 'update_issue', 'wake_issue', 'cancel_task'}
FORBIDDEN_PATH = re.compile(r'tokens|mcp-servers|skills|/env|/instructions|/members|/workspaces/[^/]+')

tools = importlib.import_module('multica_tasks.tools')
api = importlib.import_module('multica_tasks.api')
assert set(tools.TOOLS) == EXPECTED, f'набор инструментов изменился: {sorted(set(tools.TOOLS) ^ EXPECTED)}'
assert [t['name'] for t in tools.public_list()] == list(tools.TOOLS), 'tools/list расходится с TOOLS'

methods = {m for m, _ in api.ALLOWED}
assert methods <= {'GET', 'PUT', 'POST'}, f'в белом списке лишние методы: {sorted(methods - {"GET", "PUT", "POST"})}'
for method, pattern in api.ALLOWED:
    assert not FORBIDDEN_PATH.search(pattern.pattern), f'белый список открывает {method} {pattern.pattern}'
    if method == 'PUT':
        assert pattern.pattern.startswith('/api/issues/'), f'PUT разрешён вне задач: {pattern.pattern}'

transport = (work / 'multica_tasks' / 'http.py').read_text()
assert 'hmac.compare_digest' in transport, 'ключ должен сравниваться через hmac.compare_digest'
first = (work / 'bin' / 'multica-tasks-mcp').read_text().splitlines()[0]
assert first == '#!/usr/bin/python3 -I', f'бинарь должен запускаться изолированным интерпретатором: {first}'
print('mcp-smoke: ok')
