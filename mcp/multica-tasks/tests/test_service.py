import json
import os
import stat
import unittest

from support import ILYA_KEY, ILYA_PAT, KEY, OTHER_WS, PAT, WS, McpCase
from multica_tasks.errors import InvalidParams


class Clients(McpCase):
    def test_два_клиента_идут_каждый_со_своим_токеном(self):
        self.ok(['issue', 'get', 'TST-1'])
        self.ok(['issue', 'get', 'TST-1'], client='Илья', workspace='stt')
        calls = [c for c in self.cli.calls if c['argv'][:2] == ['issue', 'get']]
        self.assertEqual([c['env']['MULTICA_TOKEN'] for c in calls], [PAT, ILYA_PAT])

    def test_через_http_ключ_клиента_выбирает_его_токен(self):
        self.start_http()
        self.tool(['issue', 'get', 'TST-1'], key=KEY)
        self.tool(['issue', 'get', 'TST-1'], key=ILYA_KEY, workspace='stt')
        tokens = [c['env']['MULTICA_TOKEN'] for c in self.cli.calls if c['argv'][:2] == ['issue', 'get']]
        self.assertEqual(tokens, [PAT, ILYA_PAT])
        self.assertEqual([l['client'] for l in self.audit_lines()], ['Claude (MCP)', 'Илья'])

    def test_окружение_процесса_минимально_и_cwd_пустой(self):
        self.ok(['issue', 'get', 'TST-1'], stdin='текст')
        call = next(c for c in self.cli.calls if c['argv'][:2] == ['issue', 'get'])
        # LC_* и __CF_USER_TEXT_ENCODING добавляет сама ОС (macOS), это не часть контракта
        self.assertEqual(set(call['env']) - {'LC_CTYPE', 'LANG', 'LC_ALL', '__CF_USER_TEXT_ENCODING'},
                         {'MULTICA_TOKEN', 'MULTICA_SERVER_URL', 'MULTICA_WORKSPACE_ID', 'HOME', 'PATH'})
        self.assertEqual(call['env']['MULTICA_SERVER_URL'], 'http://127.0.0.1:8080')
        self.assertEqual(call['env']['MULTICA_WORKSPACE_ID'], WS)
        self.assertEqual(call['env']['HOME'], call['cwd'])
        self.assertEqual(call['listing'], [])
        self.assertEqual(call['stdin'], 'текст')
        self.assertFalse(os.path.exists(call['cwd']), 'временный каталог убран после вызова')

    def test_воркспейс_обязателен_если_разрешено_больше_одного(self):
        with self.assertRaises(InvalidParams) as ctx:
            self.call(['issue', 'list'], client='Илья')
        self.assertIn('workspace', ctx.exception.message)
        self.ok(['issue', 'list'], client='Илья', workspace='Мульты')
        last = self.cli.calls[-1]
        self.assertEqual(last['env']['MULTICA_WORKSPACE_ID'], OTHER_WS)

    def test_чужой_воркспейс_не_запускает_процесс(self):
        for ref in ('hidden', 'Скрытый', 'aaaaaaaa-0000-4000-8000-000000000003', 'nope'):
            with self.subTest(ref=ref), self.assertRaises(InvalidParams):
                self.call(['issue', 'list'], workspace=ref)
        self.assertFalse([c for c in self.cli.calls if c['argv'][:2] == ['issue', 'list']])

    def test_воркспейс_по_uuid_из_разрешённых_без_запроса_списка(self):
        from multica_tasks.config import Client
        client = Client('X', 'x' * 40, 'mul_x', (WS,))
        self.service.call_tool('multica', {'args': ['issue', 'list']}, '', client)
        self.assertEqual([c['argv'][:2] for c in self.cli.calls], [['issue', 'list']])
        self.assertEqual(self.cli.calls[0]['env']['MULTICA_WORKSPACE_ID'], WS)

    def test_ключ_только_для_чтения_читает_но_не_пишет(self):
        from multica_tasks.config import Client
        reader = Client('Читатель', 'r' * 40, 'mul_reader', (WS,), read_only=True)
        self.service.call_tool('multica', {'args': ['issue', 'list']}, '', reader)
        with self.assertRaises(InvalidParams):
            self.service.call_tool('multica', {'args': ['issue', 'comment', 'add', 'TST-1', '--content', 'x']}, '', reader)
        self.assertEqual([c['argv'][:2] for c in self.cli.calls], [['issue', 'list']])
        self.assertIn('только для чтения', self.audit_lines()[-1]['denied'])

    def test_список_воркспейсов_берётся_один_раз_на_клиента(self):
        self.ok(['issue', 'list'])
        self.ok(['issue', 'list'])
        self.assertEqual(len([c for c in self.cli.calls if c['argv'][:2] == ['workspace', 'list']]), 1)

    def test_справка_версия_и_список_воркспейсов_не_требуют_воркспейса(self):
        for args in (['version'], ['--help'], ['workspace', 'list'], ['issue', 'create', '--help']):
            with self.subTest(args=args):
                self.ok(args, client='Илья')
        self.assertTrue(all('MULTICA_WORKSPACE_ID' not in c['env'] for c in self.cli.calls))

    def test_сбой_списка_воркспейсов_это_ошибка_инструмента(self):
        self.cli.behavior['workspaces'] = 'не json'
        self.cli.save()
        is_error, payload = self.call(['issue', 'list'])
        self.assertTrue(is_error)
        self.assertEqual(payload['error']['code'], 'workspace_lookup_failed')


class Execution(McpCase):
    def test_спецсимволы_доходят_до_argv_как_есть(self):
        args = ['issue', 'comment', 'add', 'TST-1', '--content', '; touch pwned #', '$(id)', '`id`', 'a | b', '> out', '*']
        payload = self.ok(args)
        call = self.cli.calls[-1]
        self.assertEqual(call['argv'][:len(args)], args)
        self.assertEqual(json.loads(payload['stdout'])['argv'][:len(args)], args)
        self.assertEqual(call['listing'], [])

    def test_output_json_добавляется_к_issue_list_и_не_к_справке(self):
        self.ok(['issue', 'list'])
        self.assertEqual(self.cli.calls[-1]['argv'], ['issue', 'list', '--output', 'json'])
        self.ok(['issue', 'list', '--help'])
        self.assertEqual(self.cli.calls[-1]['argv'], ['issue', 'list', '--help'])
        self.ok(['version'])
        self.assertEqual(self.cli.calls[-1]['argv'], ['version'])
        self.ok(['issue', 'list', '--output', 'table'])
        self.assertEqual(self.cli.calls[-1]['argv'], ['issue', 'list', '--output', 'table'])

    def test_подкоманда_без_флага_output_повторяется_без_него(self):
        self.cli.rule(['issue', 'metadata'], reject_output=True, stdout='ok')
        payload = self.ok(['issue', 'metadata', 'get', 'TST-1'])
        self.assertEqual(payload['stdout'], 'ok')
        argvs = [c['argv'] for c in self.cli.calls if c['argv'][:2] == ['issue', 'metadata']]
        self.assertEqual(argvs, [['issue', 'metadata', 'get', 'TST-1', '--output', 'json'], ['issue', 'metadata', 'get', 'TST-1']])

    def test_ненулевой_код_это_iserror_с_выводом(self):
        self.cli.rule(['issue', 'get'], exit=1, stderr='Error: issue not found')
        is_error, payload = self.call(['issue', 'get', 'TST-404'])
        self.assertTrue(is_error)
        self.assertEqual((payload['exit_code'], payload['stderr']), (1, 'Error: issue not found'))

    def test_успех_не_ошибка_и_ответ_полный(self):
        self.cli.rule(['issue', 'get'], stdout='{"id": 1}')
        payload = self.ok(['issue', 'get', 'TST-1'])
        self.assertEqual(payload, {'exit_code': 0, 'stdout': '{"id": 1}', 'stderr': '', 'truncated': False, 'timeout': False})


class Timeout(McpCase):
    run_overrides = {'run_timeout': 0.5}

    def test_таймаут_убивает_процесс(self):
        self.cli.rule(['issue', 'runs'], sleep=30)
        is_error, payload = self.call(['issue', 'runs', 'TST-1'])
        self.assertTrue(is_error)
        self.assertEqual((payload['exit_code'], payload['timeout']), (None, True))


class Truncation(McpCase):
    run_overrides = {'max_output': 200}

    def setUp(self):
        super().setUp()
        self.cli.behavior['workspaces'] = [{'id': WS, 'slug': 'stt'}]  # список воркспейсов тоже режется потолком
        self.cli.save()

    def test_длинный_вывод_обрезается_с_пометкой(self):
        self.cli.rule(['issue', 'get'], stdout='x' * 5000)
        payload = self.ok(['issue', 'get', 'TST-1'])
        self.assertTrue(payload['truncated'])
        self.assertTrue(payload['stdout'].startswith('x' * 200))
        self.assertIn('обрезано', payload['stdout'])
        self.assertLess(len(payload['stdout']), 300)

    def test_секреты_каждого_клиента_маскируются_на_границе_обрезки(self):
        for secret in (PAT, KEY, ILYA_PAT, ILYA_KEY):
            for pad in (200 - 10, 200 - len(secret) // 2, 200 - 1, 200):
                with self.subTest(secret=secret[:12], pad=pad):
                    self.cli.behavior['rules'] = []
                    self.cli.rule(['issue', 'get'], stdout='x' * pad + secret + 'y' * 300, stderr=secret * 2)
                    self.cli.save()
                    payload = self.ok(['issue', 'get', 'TST-1'])
                    for text in (payload['stdout'], payload['stderr']):
                        self.assertNotIn(secret[:12], text)
                        self.assertNotIn(secret[-12:], text)

    def test_токен_клиента_из_вывода_процесса_не_утекает(self):
        self.cli.rule(['issue', 'get'], stdout='token={TOKEN}', stderr='{TOKEN}')
        for name, secret in (('Claude (MCP)', PAT), ('Илья', ILYA_PAT)):
            payload = self.ok(['issue', 'get', 'TST-1'], client=name, workspace='stt')
            self.assertEqual(payload['stdout'], 'token=[redacted]')
            self.assertEqual(payload['stderr'], '[redacted]')


class Denied(McpCase):
    def test_отказ_не_запускает_процесс_и_пишется_в_аудит(self):
        with self.assertRaises(InvalidParams) as ctx:
            self.call(['agent', 'update', 'a', '--instructions', 'x'])
        self.assertIn('только по ssh', ctx.exception.message)
        self.assertEqual(self.cli.calls, [])
        (line,) = self.audit_lines()
        self.assertEqual((line['client'], line['argv'][:2], line['exit_code']), ('Claude (MCP)', ['agent', 'update'], None))
        self.assertTrue(line['denied'])

    def test_аргументы_неверной_формы_это_32602(self):
        for arguments in ({}, {'args': 'issue get'}, {'args': []}, {'args': ['issue', 1]}, {'args': [['issue']]}, {'args': ['a\x00b']},
                          {'args': ['issue'], 'stdin': 5}, {'args': ['issue'], 'extra': 1}, {'args': ['issue'], 'workspace': ''},
                          {'args': ['issue', 'x' * 20000]}, {'args': ['issue'], 'stdin': 'x' * (256 * 1024 + 1)}, [], 'x', None):
            with self.subTest(arguments=str(arguments)[:40]), self.assertRaises(InvalidParams):
                self.service.call_tool('multica', arguments, '', self.client())
        self.assertEqual(self.cli.calls, [])

    def test_неизвестный_инструмент_32602(self):
        for name in ('get_issue', 'create_issue', 'x'):
            with self.subTest(name=name), self.assertRaises(InvalidParams):
                self.service.call_tool(name, {}, '', self.client())


class Audit(McpCase):
    def test_запись_содержит_клиента_argv_код_длины_и_длительность(self):
        self.cli.rule(['issue', 'comment'], stdout='готово')
        self.ok(['issue', 'comment', 'add', 'TST-1', '--content-stdin'], stdin='Привет, ' + PAT)
        (line,) = self.audit_lines()
        self.assertEqual(line['client'], 'Claude (MCP)')
        self.assertEqual(line['argv'], ['issue', 'comment', 'add', 'TST-1', '--content-stdin'])
        self.assertEqual((line['exit_code'], line['stdout_length'], line['client_ip']), (0, len('готово'.encode()), '203.0.113.9'))
        self.assertIn('duration', line)
        self.assertIsNone(line['denied'])
        self.assertEqual(line['stdin']['length'], len('Привет, ' + PAT))
        self.assertEqual(len(line['stdin']['sha256']), 64)
        self.assertEqual(line['stdin']['head'], 'Привет, [redacted]')

    def test_превью_stdin_до_200_символов_и_без_секрета_на_границе(self):
        self.ok(['issue', 'comment', 'add', 'TST-1', '--content-stdin'], stdin='x' * 190 + ILYA_PAT)
        (line,) = self.audit_lines()
        self.assertEqual(len(line['stdin']['head']), 200)
        self.assertNotIn(ILYA_PAT[:10], json.dumps(line))

    def test_ключи_и_pat_всех_клиентов_в_аудит_не_попадают(self):
        self.ok(['issue', 'get', 'TST-1', '--title', KEY + ILYA_KEY + PAT + ILYA_PAT])
        text = (self.state / 'audit.jsonl').read_text()
        for secret in (KEY, ILYA_KEY, PAT, ILYA_PAT):
            self.assertNotIn(secret, text)

    def test_нулевой_код_и_ошибка_различимы_в_аудите(self):
        self.cli.rule(['issue', 'get'], exit=3)
        self.call(['issue', 'get', 'X'])
        self.assertEqual(self.audit_lines()[0]['exit_code'], 3)

    def test_права_файла_0600(self):
        self.ok(['version'])
        self.assertEqual(stat.S_IMODE((self.state / 'audit.jsonl').stat().st_mode), 0o600)

    def test_существующий_аудит_дописывается(self):
        self.ok(['version'])
        from multica_tasks.audit import AuditLog
        AuditLog(self.state / 'audit.jsonl').write(tool='x')
        self.assertEqual(len(self.audit_lines()), 2)


if __name__ == '__main__':
    unittest.main()
