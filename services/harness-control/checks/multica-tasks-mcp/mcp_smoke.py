"""Доверенная проверка multica-tasks-mcp: контракт, который кандидат не вправе менять вместе со своими тестами.

Аргумент — каталог кандидата (mcp/multica-tasks). Проверяется то, что делает публичный сервер безопасным:
ровно один инструмент `multica`, allowlist без запрещённых групп и подкоманд записи, нет shell и DELETE,
ключ сравнивается через hmac.compare_digest, бинарь запускается изолированным интерпретатором.
"""
import importlib
import re
import sys
from pathlib import Path

work = Path(sys.argv[1])
sys.path.insert(0, str(work))

BANNED_GROUPS = {'autopilot', 'pool', 'daemon', 'auth', 'login', 'setup', 'config', 'update', 'user', 'attachment', 'repo', 'chat'}
BANNED_PAIRS = {('agent', 'create'), ('agent', 'update'), ('agent', 'delete'), ('agent', 'mcp'), ('agent', 'skills'),
                ('skill', 'create'), ('skill', 'update'), ('skill', 'delete'), ('property', 'create'), ('property', 'update'),
                ('property', 'delete'), ('label', 'create'), ('label', 'update'), ('label', 'delete'), ('runtime', 'list')}
# Остальное разрешённое — чтение; единственная группа с записью — issue (без delete)
ALLOWED_GROUPS = {'issue', 'project', 'agent', 'squad', 'profile', 'workflow', 'label', 'property', 'skill', 'runtime',
                  'subscription', 'workspace', 'version'}

tools = importlib.import_module('multica_tasks.tools')
policy = importlib.import_module('multica_tasks.policy')
assert set(tools.TOOLS) == {'multica'}, f'набор инструментов изменился: {sorted(tools.TOOLS)}'
assert [t['name'] for t in tools.public_list()] == ['multica'], 'tools/list расходится с TOOLS'

for prefix in policy.ALLOW:
    assert prefix[0] in ALLOWED_GROUPS, f'allowlist открывает группу {prefix[0]}'
    assert prefix[0] not in BANNED_GROUPS, f'allowlist открывает группу {prefix[0]}'
    assert prefix not in BANNED_PAIRS, f'allowlist открывает {" ".join(prefix)}'
    assert not any(w in ('delete', 'rm', 'remove', 'create', 'update') for w in prefix if prefix[0] != 'issue'), \
        f'allowlist открывает запись: {" ".join(prefix)}'
assert ('issue',) in policy.ALLOW and not any(w == 'delete' for p in policy.ALLOW for w in p), 'issue delete в allowlist'
assert {p for p in policy.ALLOW if p[0] == 'workspace'} == {('workspace', 'list')}, 'workspace: только list'
assert {p for p in policy.ALLOW if p[0] == 'subscription'} == {('subscription', 'list')}, 'subscription: только list'

sources = {f.name: f.read_text() for f in (work / 'multica_tasks').glob('*.py')}
for name, text in sources.items():
    assert not re.search(r'shell\s*=\s*True|os\.system|os\.popen|\bcommands\.getoutput', text), f'{name}: запуск через shell'
    assert not re.search(r'''['"]DELETE['"]''', text), f'{name}: метод DELETE в коде'
assert 'subprocess.Popen([' in sources['runner.py'], 'runner.py: argv списком без shell'
assert 'hmac.compare_digest' in sources['http.py'], 'ключ должен сравниваться через hmac.compare_digest'
first = (work / 'bin' / 'multica-tasks-mcp').read_text().splitlines()[0]
assert first == '#!/usr/bin/python3 -I', f'бинарь должен запускаться изолированным интерпретатором: {first}'
print('mcp-smoke: ok')
