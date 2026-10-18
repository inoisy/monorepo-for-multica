import io
import json
import os
import re
import subprocess
import unittest
from unittest import mock

from support import ACTOR, PKG, HarnessCase
from harness_control import cli, client, mcp, priv
from harness_control.commands import COMMANDS, parse


def normalize(text, *roots):
    for root in roots:
        text = text.replace(str(root), '<root>')
    text = re.sub(r'\d{13}-[0-9a-f]{8}', '<op>', text)
    return re.sub(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ', '<t>', text)


class World:
    """Один изолированный корень + способ дёргать harness-priv так, как это делает sudo (внутри процесса)."""

    def __init__(self, case):
        self.case = case

    def invoke(self, verb, tokens):
        out = io.StringIO()
        env = {'SUDO_USER': 'agents', 'MULTICA_AGENT_NAME': 'Бэкенд', 'MULTICA_TASK_ID': 'TASK-264'}
        with mock.patch.dict(os.environ, {'HARNESS_ROOT': str(self.case.root)}):
            priv.main([verb, *tokens, '--json'], env=env, out=out, system=self.case.system, spawn=self.case.pending.append)
        return json.loads(out.getvalue())

    def cli(self, argv):
        out = io.StringIO()
        code = cli.main(argv, call=self.invoke, out=out)
        return code, out.getvalue().strip()

    def mcp(self, verb, args):
        isError, text = mcp.call_tool(f'harness_{verb}', args, call=self.invoke)
        return isError, text.strip()


class Parity(HarnessCase):
    def setUp(self):
        super().setUp()
        self.other = HarnessCase('setUp')
        self.other.setUp()
        self.addCleanup(self.other.doCleanups)
        self.a, self.b = World(self), World(self.other)

    def norm(self, text):
        return normalize(text, self.root, self.other.root)

    def both(self, argv, args=None):
        verb = argv[0]
        code, cli_text = self.a.cli(argv)
        try:
            args = args if args is not None else parse(verb, argv[1:])
        except Exception:
            self.fail(f'сценарий {argv} не разбирается')
        is_error, mcp_text = self.b.mcp(verb, args)
        self.assertEqual(self.norm(cli_text), self.norm(mcp_text), f'CLI и MCP разошлись на {argv}')
        self.assertEqual(code in (1, 2), is_error)
        return json.loads(cli_text), json.loads(mcp_text)

    def test_одинаковые_сценарии_дают_одинаковый_json(self):
        scenarios = [
            ['inspect'], ['inspect', 'harness-canary'], ['inspect', 'nosuch'], ['ops'], ['ops', 'harness-canary'],
            ['validate', 'harness-canary', '0' * 40, '--reason', 'паритет'],
            ['validate', 'multica-agents', '0' * 40],
            ['deploy', 'harness-canary', '--validation', '0000000000000-deadbeef', '--digest', 'sha256:' + '0' * 64],
            ['rollback', 'harness-canary'],
            ['rollback', 'harness-canary', '--to', 'baseline'],
        ]
        for argv in scenarios:
            with self.subTest(argv=argv):
                a, b = self.both(argv)
                self.assertEqual(self.norm(json.dumps(a, sort_keys=True)), self.norm(json.dumps(b, sort_keys=True)))

    def test_op_и_log_после_validate(self):
        a, b = self.both(['validate', 'harness-canary', '0' * 40, '--key', 'p1'])
        op_a, op_b = a['operation_id'], b['operation_id']
        code, cli_text = self.a.cli(['op', op_a])
        is_error, mcp_text = self.b.mcp('op', {'id': op_b})
        self.assertEqual(self.norm(cli_text), self.norm(mcp_text))
        self.assertIsNone(json.loads(cli_text)['error'])
        self.assertEqual((code, is_error), (0, False))
        code, cli_text = self.a.cli(['log', op_a, '--tail', '5'])
        is_error, mcp_text = self.b.mcp('log', {'id': op_b, 'tail': 5})
        self.assertEqual(self.norm(cli_text), self.norm(mcp_text))

    def test_op_несуществующей_операции_ошибка_в_обоих_адаптерах(self):
        a, _ = self.both(['op', '0000000000000-deadbeef'])
        self.assertEqual(a['error'], 'operation_not_found')

    def test_ошибки_разбора_одинаковы(self):
        code, cli_text = self.a.cli(['validate', 'harness-canary', 'XYZ'])
        is_error, mcp_text = self.b.mcp('validate', {'component': 'harness-canary', 'sha': 'XYZ'})
        self.assertEqual((code, is_error), (2, True))
        self.assertEqual(cli_text, mcp_text)
        self.assertEqual(json.loads(cli_text)['error'], 'bad_request')

    def test_административные_и_неизвестные_глаголы_отказ_одинаков(self):
        for verb in ('adopt-baseline', 'recover', 'run-op', 'rm'):
            with self.subTest(verb=verb):
                code, cli_text = self.a.cli([verb, 'harness-canary'])
                is_error, mcp_text = self.b.mcp(verb, {'component': 'harness-canary'})
                self.assertEqual((code, is_error), (2, True))
                self.assertEqual(cli_text, mcp_text)
                self.assertEqual(json.loads(cli_text)['error'], 'verb_not_allowed')

    def test_таблица_глаголов_покрыта_инструментами_mcp(self):
        self.assertEqual([t['name'] for t in mcp.TOOLS], [f'harness_{v}' for v in COMMANDS])
        for tool in mcp.TOOLS:
            self.assertEqual(tool['inputSchema']['additionalProperties'], False)


class McpProtocol(unittest.TestCase):
    def test_ответ_с_error_null_и_фактической_ошибкой(self):
        for error in (None, 'operation_not_found'):
            with self.subTest(error=error):
                payload = {'error': error, 'status': 'done' if error is None else 'failed'}
                call = lambda verb, tokens: payload
                out = io.StringIO()
                code = cli.main(['op', '0000000000000-deadbeef'], call=call, out=out)
                mcp_out = io.StringIO()
                mcp.handle({'id': 1, 'method': 'tools/call', 'params': {
                    'name': 'harness_op', 'arguments': {'id': '0000000000000-deadbeef'}}}, mcp_out, call=call)
                result = json.loads(mcp_out.getvalue())['result']
                self.assertEqual(json.loads(out.getvalue()), json.loads(result['content'][0]['text']))
                self.assertEqual((code, result['isError']), (1, True) if error else (0, False))

    def run_lines(self, *messages):
        out = io.StringIO()
        mcp.main(io.StringIO('\n'.join(m if isinstance(m, str) else json.dumps(m) for m in messages) + '\n'), out,
                 call=lambda verb, tokens: {'verb': verb, 'tokens': tokens})
        return [json.loads(l) for l in out.getvalue().splitlines()]

    def test_handshake_список_и_вызов(self):
        replies = self.run_lines(
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18'}},
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'harness_validate', 'arguments': {'component': 'harness-canary', 'sha': 'a' * 40, 'reason': 'x'}}},
            {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {'name': 'harness_nope', 'arguments': {}}},
            {'jsonrpc': '2.0', 'id': 5, 'method': 'nope'}, 'не json')
        self.assertEqual(replies[0]['result']['serverInfo']['name'], 'harness-control')
        self.assertEqual(len(replies[1]['result']['tools']), 7)
        body = json.loads(replies[2]['result']['content'][0]['text'])
        self.assertEqual(body, {'verb': 'validate', 'tokens': ['harness-canary', 'a' * 40, '--reason', 'x']})
        self.assertTrue(replies[3]['result']['isError'])
        self.assertEqual(replies[4]['error']['code'], -32601)
        self.assertEqual(replies[5]['error']['code'], -32700)


class PrivEntryPoint(HarnessCase):
    def test_код_выхода_op_зависит_от_ошибки_а_не_наличия_ключа(self):
        for error in (None, {'error': 'internal', 'reason': 'failed'}):
            with self.subTest(error=error), mock.patch.object(priv, 'Harness') as harness:
                harness.return_value.handle.return_value = {'error': error}
                out = io.StringIO()
                code = priv.main(['op', '0000000000000-deadbeef'], out=out)
                self.assertEqual(json.loads(out.getvalue()), {'error': error})
                self.assertEqual(code, 1 if error else 0)

    def _run(self, *argv, **env):
        return subprocess.run([str(PKG / 'bin' / 'harness-priv'), *argv], capture_output=True, text=True, timeout=60,
                              env={'HARNESS_ROOT': str(self.root), 'PATH': '/usr/bin:/bin', **env})

    def test_процесс_отдаёт_json_и_код_выхода(self):
        r = self._run('inspect', 'nosuch', '--json')
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(json.loads(r.stdout)['error'], 'unknown_component')

    def test_агент_через_sudo_не_получает_административные_глаголы(self):
        r = self._run('adopt-baseline', 'harness-canary', SUDO_USER='agents')
        self.assertEqual(json.loads(r.stdout)['error'], 'verb_not_allowed')

    def test_окружение_не_подменяет_корень_у_root(self):
        # от root HARNESS_ROOT игнорируется: проверяем правило, а не запускаем root
        from harness_control.paths import Paths
        with mock.patch('os.geteuid', return_value=0), mock.patch.dict(os.environ, {'HARNESS_ROOT': '/tmp/evil'}):
            self.assertEqual(str(Paths.from_env().root), '/')


if __name__ == '__main__':
    unittest.main()
