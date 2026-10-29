import unittest

from support import PKG  # noqa: F401  (путь к пакету)
from multica_tasks import policy
from multica_tasks.errors import InvalidParams

ALLOWED = (
    ['issue', 'list', '--status', 'dev'], ['issue', 'get', 'TST-1'], ['issue', 'search', 'x'], ['issue', 'children', 'TST-1'],
    ['issue', 'pull-requests', 'TST-1'], ['issue', 'timeline', 'TST-1'], ['issue', 'runs', 'TST-1', '--full-id'],
    ['issue', 'run-messages', 'r'], ['issue', 'usage', 'TST-1'], ['issue', 'comment', 'list', 'TST-1'],
    ['issue', 'subscriber', 'list', 'TST-1'], ['issue', 'label', 'list', 'TST-1'], ['issue', 'metadata', 'list', 'TST-1'],
    ['issue', 'metadata', 'get', 'TST-1', 'k'], ['issue', 'property', 'list', 'TST-1'], ['issue', 'wakeup', 'list', 'TST-1'],
    ['issue', 'wakeup', 'get', 'TST-1', 'w'], ['issue', 'wakeup', 'runs', 'TST-1', 'w'], ['issue', 'wakeup', 'events'],
    ['issue', 'create', '--title', 'x', '--description-stdin'], ['issue', 'update', 'TST-1', '--title', 'y'],
    ['issue', 'assign', 'TST-1', '--unassign'], ['issue', 'status', 'TST-1', 'done'], ['issue', 'reorder', 'TST-1'],
    ['issue', 'rerun-task', 'r'], ['issue', 'cancel-task', 'x'], ['issue', 'steer', 'TST-1', '--content-stdin'],
    ['issue', 'model-profile', 'TST-1'], ['issue', 'stages', 'TST-1'],
    ['issue', 'comment', 'add', 'TST-1', '--content-stdin'], ['issue', 'comment', 'update', 'c', '--content', 'x'],
    ['issue', 'comment', 'resolve', 'c'], ['issue', 'comment', 'unresolve', 'c'], ['issue', 'subscriber', 'add', 'TST-1'],
    ['issue', 'subscriber', 'remove', 'TST-1'], ['issue', 'label', 'add', 'TST-1', 'l'], ['issue', 'label', 'remove', 'TST-1', 'l'],
    ['issue', 'metadata', 'set', 'TST-1', 'k', 'v'], ['issue', 'property', 'set', 'TST-1', 'p', 'v'],
    ['issue', 'property', 'unset', 'TST-1', 'p'], ['issue', 'wakeup', 'create', 'TST-1'], ['issue', 'wakeup', 'update', 'TST-1', 'w'],
    ['issue', 'wakeup', 'disable', 'TST-1', 'w'], ['issue', 'wakeup', 'trigger', 'TST-1', 'w'], ['issue', 'wakeup', 'checkin', 'TST-1'],
    ['project', 'list'], ['project', 'get', 'p'], ['agent', 'list'], ['agent', 'get', 'a'], ['agent', 'models', 'a'],
    ['agent', 'tasks', 'a'], ['squad', 'list'], ['squad', 'get', 's'], ['squad', 'member', 'list', 's'], ['profile', 'list'],
    ['workflow', 'list'], ['label', 'list'], ['property', 'list'], ['skill', 'list'], ['skill', 'get', 's'],
    ['runtime', 'unavailable'], ['subscription', 'list'], ['workspace', 'list'], ['version'],
)
# Группы и команды из «Границы» задачи: ни одна не должна запускаться
DENIED = (
    ['agent', 'create'], ['agent', 'update', 'a'], ['agent', 'delete', 'a'], ['agent', 'mcp', 'list'], ['agent', 'skills', 'list'],
    ['skill', 'create'], ['skill', 'update', 's'], ['skill', 'delete', 's'], ['autopilot', 'list'], ['pool', 'list'],
    ['subscription', 'create'], ['subscription', 'delete', 'x'], ['runtime', 'list'], ['daemon', 'start'], ['daemon', 'status'],
    ['auth', 'status'], ['login'], ['setup'], ['config', 'show'], ['update'], ['user', 'get'], ['attachment', 'download', 'x'],
    ['repo', 'checkout', 'x'], ['property', 'create'], ['property', 'delete', 'x'], ['label', 'create'], ['label', 'delete', 'x'],
    ['workspace', 'get'], ['workspace', 'delete', 'x'], ['chat', 'list'], ['project', 'create'], ['project', 'delete', 'p'],
    ['squad', 'create'], ['squad', 'member', 'add'], ['profile', 'create'], ['workflow', 'create'], ['issue2', 'get'],
    ['agent'], ['runtime', 'unavailable', 'recheck'], ['agent', 'models', 'a', 'set'], ['agent', 'models', 'a', 'profile', 'x'],
    ['agent', 'models', 'a', 'tools'], ['agent', 'models', 'a', 'reset'], [''], ['--server-url', 'http://x', 'issue', 'list'],
    ['--profile', 'x', 'issue', 'list'], ['issue', '--server-url', 'http://evil', 'list'], ['version2'], ['ISSUE', 'get'],
    # удаление и неизвестные подкоманды issue: таблица явная, новое в CLI само не открывается
    ['issue', 'comment', 'delete', 'c'], ['issue', 'metadata', 'delete', 'TST-1', 'k'], ['issue', 'wakeup', 'delete', 'TST-1', 'w'],
    ['issue', 'delete', 'TST-1'], ['issue', 'future-subcommand'], ['issue'], ['issue', 'comment'],
    # флаг перед подкомандой: cobra всё равно нашла бы `issue comment delete`
    ['issue', '--output', 'json', 'comment', 'delete', 'c'], ['issue', '--output=json', 'comment', 'delete', 'c'],
)
WRITES = (
    ['issue', 'create', '--title', 'x'], ['issue', 'update', 'K', '--title', 'y'], ['issue', 'assign', 'K', '--to', 'a'],
    ['issue', 'status', 'K', 'done'], ['issue', 'comment', 'add', 'K', '--content', 'x'], ['issue', 'steer', 'K'],
    ['issue', 'wakeup', 'create', 'K'], ['issue', 'cancel-task', 'r'], ['issue', 'model-profile', 'K', 'x'],
)
FORBIDDEN_FLAGS = (
    ['issue', 'create', '--description-file', 'x'], ['issue', 'create', '--description-file=/etc/passwd'],
    ['issue', 'comment', 'add', 'K', '--content-file', 'x'], ['issue', 'steer', 'K', '--content-file', 'x'],
    ['issue', 'update', 'K', '--allow-external-file'], ['issue', 'wakeup', 'create', 'K', '--instruction-file', 'x'],
    ['issue', 'create', '--attachment', 'x'], ['issue', 'create', '--attachment-id', 'x'], ['issue', 'update', 'K', '--attach=x'],
    ['issue', 'list', '--server-url', 'http://evil'], ['issue', 'list', '--server-url=http://evil'],
    ['issue', 'list', '--workspace-id', 'x'], ['issue', 'list', '--profile', 'x'], ['issue', 'list', '--debug'],
    ['skill', 'get', 's', '--with-content'], ['skill', 'get', 's', '--with-content=true'],
)


class Allowlist(unittest.TestCase):
    def test_каждая_строка_allowlist_проходит(self):
        for argv in ALLOWED:
            with self.subTest(argv=argv):
                self.assertIsInstance(policy.check(argv), tuple)

    def test_таблица_целиком_покрыта_примерами(self):
        covered = {policy.check(a) for a in ALLOWED}
        self.assertEqual(covered, set(policy.COMMANDS))

    def test_запрещённые_группы_и_команды_отказ_32602(self):
        for argv in DENIED:
            with self.subTest(argv=argv), self.assertRaises(InvalidParams) as ctx:
                policy.check(argv)
            self.assertTrue(ctx.exception.message.startswith('только по ssh'))
            self.assertTrue(ctx.exception.denied)

    def test_запрещённые_флаги_отказ_даже_у_разрешённых_команд(self):
        for argv in FORBIDDEN_FLAGS:
            with self.subTest(argv=argv), self.assertRaises(InvalidParams):
                policy.check(argv)

    def test_справка_на_командах_и_группах(self):
        for argv in (['--help'], ['-h'], ['issue', '--help'], ['agent', '--help'], ['squad', 'member', '--help'], ['issue', 'comment', '--help'],
                     ['issue', 'create', '--help'], ['project', 'list', '-h'], ['workspace', '--help']):
            with self.subTest(argv=argv):
                policy.check(argv)
        for argv in (['agent', 'update', '--help'], ['daemon', '--help'], ['--help', 'agent', 'update'],
                     ['--help', '--server-url', 'x'], ['auth', '-h']):
            with self.subTest(argv=argv), self.assertRaises(InvalidParams):
                policy.check(argv)

    def test_пустой_argv_отказ(self):
        with self.assertRaises(InvalidParams):
            policy.check([])

    def test_запрещённые_группы_из_границы_не_входят_в_таблицу(self):
        groups = {p[0] for p in policy.COMMANDS}
        for banned in ('autopilot', 'pool', 'daemon', 'auth', 'login', 'setup', 'config', 'update', 'user', 'attachment', 'repo', 'chat'):
            self.assertNotIn(banned, groups)
        for group, sub in (('agent', 'create'), ('agent', 'update'), ('agent', 'delete'), ('agent', 'mcp'), ('agent', 'skills'),
                           ('skill', 'create'), ('skill', 'delete'), ('property', 'create'), ('label', 'create'), ('runtime', 'list')):
            self.assertNotIn((group, sub), policy.COMMANDS)
        self.assertEqual({p for p in policy.COMMANDS if p[0] == 'subscription'}, {('subscription', 'list')})
        self.assertEqual({p for p in policy.COMMANDS if p[0] == 'workspace'}, {('workspace', 'list')})
        self.assertFalse([p for p in policy.COMMANDS if 'delete' in p])

    def test_ключ_только_для_чтения_не_пишет_но_читает_и_видит_справку(self):
        for argv in WRITES:
            with self.subTest(argv=argv), self.assertRaises(InvalidParams) as ctx:
                policy.check(argv, read_only=True)
            self.assertIn('только для чтения', ctx.exception.message)
        for argv in (['issue', 'list'], ['issue', 'get', 'K'], ['issue', 'create', '--help'], ['agent', 'models', 'a']):
            with self.subTest(argv=argv):
                policy.check(argv, read_only=True)
        with self.assertRaises(InvalidParams):  # `--title --help` — не справка, команда пишет
            policy.check(['issue', 'create', '--title', '--help'], read_only=True)

    def test_флаг_output_добавляется_только_там_где_нужен(self):
        self.assertTrue(policy.wants_output_flag(['issue', 'list']))
        self.assertFalse(policy.wants_output_flag(['issue', 'list', '--help']))
        self.assertFalse(policy.wants_output_flag(['version']))
        self.assertFalse(policy.wants_output_flag(['issue', 'list', '--output', 'table']))
        self.assertFalse(policy.wants_output_flag(['issue', 'list', '--output=table']))
        self.assertFalse(policy.wants_output_flag(['issue', 'create', '-h']))

    def test_help_как_значение_флага_не_справка(self):
        # `--title --help`: pflag берёт --help значением, команда выполняется — воркспейс обязателен
        self.assertFalse(policy.is_help(['issue', 'create', '--title', '--help']))
        self.assertTrue(policy.needs_workspace(('issue', 'create'), ['issue', 'create', '--title', '--help']))
        self.assertTrue(policy.wants_output_flag(['issue', 'create', '--title', '--help']))
        self.assertTrue(policy.is_help(['issue', 'get', 'TST-1', '--help']))
        self.assertFalse(policy.needs_workspace(('issue', 'create'), ['issue', 'create', '-h']))


if __name__ == '__main__':
    unittest.main()
