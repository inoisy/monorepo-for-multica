import json
import os
import sqlite3
import stat
import unittest
from urllib.parse import urlencode

from oauth_support import ANNA, CLAUDE_CALLBACK, FORM, RESOURCE, OAuthCase, pkce
from multica_tasks.oauth_service import ACCESS_TTL, CODE_TTL
from support import WS


class CodeExchange(OAuthCase):
    def test_успешный_обмен(self):
        _, body = self.connect()
        self.assertEqual((body['token_type'], body['expires_in'], body['scope']), ('Bearer', ACCESS_TTL, 'multica'))
        self.assertTrue(body['access_token'] and body['refresh_token'])

    def test_без_verifier_и_с_неверным_нет_токенов(self):
        for verifier in ('', 'x' * 43, pkce()[0]):
            with self.subTest(verifier=verifier[:5]):
                cid, _, code = self.approved_code()
                status, body = self.exchange(cid, verifier, code)
                self.assertEqual((status, body['error']), (400, 'invalid_grant' if verifier else 'invalid_request'))
                self.assertNotIn('access_token', body)

    def test_неверный_verifier_сжигает_code(self):
        cid, verifier, code = self.approved_code()
        self.exchange(cid, pkce()[0], code)
        status, body = self.exchange(cid, verifier, code)
        self.assertEqual((status, body['error']), (400, 'invalid_grant'))

    def test_повторный_code_отзывает_выданное_по_нему(self):
        cid, verifier, code = self.approved_code()
        _, first = self.exchange(cid, verifier, code)
        self.assertEqual(self.issue_get(first['access_token'])[0], 200)
        status, body = self.exchange(cid, verifier, code)
        self.assertEqual((status, body['error']), (400, 'invalid_grant'))
        self.assertEqual(self.issue_get(first['access_token'])[0], 401)
        self.assertEqual(self.token(grant_type='refresh_token', client_id=cid, refresh_token=first['refresh_token'])[0], 400)

    def test_просроченный_code(self):
        cid, verifier, code = self.approved_code()
        self.clock.advance(CODE_TTL + 1)
        self.assertEqual(self.exchange(cid, verifier, code)[1]['error'], 'invalid_grant')

    def test_чужой_client_id(self):
        _, verifier, code = self.approved_code()
        other = self.client_id()
        self.assertEqual(self.exchange(other, verifier, code)[1]['error'], 'invalid_grant')

    def test_неизвестный_client_id(self):
        _, verifier, code = self.approved_code()
        self.assertEqual(self.exchange('nope', verifier, code)[0], 401)

    def test_другой_redirect_uri_и_resource(self):
        cases = ({'redirect_uri': 'https://claude.com/api/mcp/auth_callback', 'resource': RESOURCE},
                 {'redirect_uri': CLAUDE_CALLBACK, 'resource': 'https://evil.example/mcp'})
        for form in cases:
            with self.subTest(form=form):
                cid, verifier, code = self.approved_code()
                status, body = self.token(grant_type='authorization_code', client_id=cid, code=code, code_verifier=verifier, **form)
                self.assertEqual((status, body['error']), (400, 'invalid_grant'))

    def test_loopback_порт_привязан_к_запросу(self):
        cid = self.client_id(['http://localhost:1111/callback'])
        _, verifier, code = self.approved_code(cid, redirect_uri='http://localhost:2222/callback')
        wrong = self.token(grant_type='authorization_code', client_id=cid, code=code, code_verifier=verifier,
                           redirect_uri='http://localhost:1111/callback')
        self.assertEqual(wrong[1]['error'], 'invalid_grant')
        _, verifier, code = self.approved_code(cid, redirect_uri='http://localhost:2222/callback')
        ok = self.token(grant_type='authorization_code', client_id=cid, code=code, code_verifier=verifier,
                        redirect_uri='http://localhost:2222/callback')
        self.assertEqual(ok[0], 200)

    def test_форма_и_content_type(self):
        status, text, _ = self.http('POST', '/mcp/oauth/token', raw=b'{}', headers={'Content-Type': 'application/json'})
        self.assertEqual((status, json.loads(text)['error']), (400, 'invalid_request'))
        status, text, _ = self.http('POST', '/mcp/oauth/token', raw=b'a=1&a=2', headers={'Content-Type': FORM})
        self.assertEqual(status, 400)
        self.assertEqual(self.http('GET', '/mcp/oauth/token')[0], 405)

    def test_ответ_без_кэша(self):
        _, _, resp = self.http('POST', '/mcp/oauth/token', raw=b'grant_type=x', headers={'Content-Type': FORM})
        self.assertEqual(resp.getheader('Cache-Control'), 'no-store')

    def test_неудачные_обмены_ограничиваются_по_адресу(self):
        statuses = [self.token(grant_type='authorization_code', client_id='x')[0] for _ in range(22)]
        self.assertEqual(statuses[-1], 429)


class Refresh(OAuthCase):
    def refresh(self, cid, token, **extra):
        return self.token(grant_type='refresh_token', client_id=cid, refresh_token=token, **extra)

    def test_ротация_выдаёт_новую_пару_и_гасит_старый_refresh(self):
        cid, first = self.connect()
        status, second = self.refresh(cid, first['refresh_token'])
        self.assertEqual(status, 200)
        self.assertNotEqual(second['refresh_token'], first['refresh_token'])
        self.assertEqual(self.issue_get(second['access_token'])[0], 200)
        self.assertEqual(self.issue_get(first['access_token'])[0], 401, 'старый access заменён')

    def test_повтор_старого_refresh_блокирует_всё_семейство(self):
        cid, first = self.connect()
        _, second = self.refresh(cid, first['refresh_token'])
        status, body = self.refresh(cid, first['refresh_token'])
        self.assertEqual((status, body['error']), (400, 'invalid_grant'))
        self.assertEqual(self.issue_get(second['access_token'])[0], 401)
        self.assertEqual(self.refresh(cid, second['refresh_token'])[0], 400)

    def test_refresh_чужого_клиента_и_resource(self):
        cid, first = self.connect()
        self.assertEqual(self.refresh(self.client_id(), first['refresh_token'])[1]['error'], 'invalid_grant')
        self.assertEqual(self.refresh(cid, first['refresh_token'], resource='https://evil.example/mcp')[1]['error'], 'invalid_target')
        self.assertEqual(self.refresh(cid, first['refresh_token'])[0], 200, 'отказы выше не сожгли токен')

    def test_refresh_не_продлевает_срок_grant(self):
        cid, token = self.connect()
        self.clock.advance(60 * 24 * 3600)
        _, token = self.refresh(cid, token['refresh_token'])
        self.clock.advance(60 * 24 * 3600)  # 120 суток от входа: grant (89) закончился, даже если refresh обновляли
        self.assertEqual(self.refresh(cid, token['refresh_token'])[1]['error'], 'invalid_grant')
        self.assertEqual(self.issue_get(token['access_token'])[0], 401)

    def test_refresh_после_отзыва_pat_в_multica(self):
        cid, token = self.connect()
        self.multica.revoke_all()
        status, body = self.refresh(cid, token['refresh_token'])
        self.assertEqual((status, body['error']), (400, 'invalid_grant'))

    def test_refresh_при_недоступной_multica_не_отзывает(self):
        cid, token = self.connect()
        self.multica.down = True
        status, body = self.refresh(cid, token['refresh_token'])
        self.assertEqual((status, body['error']), (503, 'temporarily_unavailable'))
        self.multica.down = False
        self.assertEqual(self.refresh(cid, token['refresh_token'])[0], 200, 'недоступность не сожгла refresh и grant')

    def test_параллельные_refresh_дают_один_успех(self):
        import threading
        cid, token = self.connect()
        results = []
        barrier = threading.Barrier(4)

        def attempt():
            barrier.wait()
            results.append(self.service_refresh(cid, token['refresh_token']))
        threads = [threading.Thread(target=attempt) for _ in range(4)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(results.count('ok'), 1, results)

    def service_refresh(self, cid, refresh_token):
        from multica_tasks.oauth_service import OAuthError
        try:
            self.oauth.token({'grant_type': 'refresh_token', 'client_id': cid, 'refresh_token': refresh_token})
            return 'ok'
        except OAuthError:
            return 'denied'


class AccessAndRevocation(OAuthCase):
    def test_вызов_идёт_от_pat_пользователя_и_аудит_называет_его(self):
        _, token = self.connect()
        status, body = self.issue_get(token['access_token'])
        self.assertEqual(status, 200)
        self.assertFalse(body['result']['isError'], body)
        call = next(c for c in self.cli.calls if c['argv'][:2] == ['issue', 'get'])
        pat = next(iter(self.multica.pats))
        self.assertEqual(call['env']['MULTICA_TOKEN'], pat)
        self.assertEqual(call['env']['MULTICA_WORKSPACE_ID'], WS)
        entry = self.audit_lines()[-1]
        self.assertEqual((entry['client'], entry['user_id'], entry['auth']), ('Анна', ANNA.id, 'oauth'))
        self.assertNotIn(pat, json.dumps(entry))
        self.assertNotIn(token['access_token'], (self.state / 'audit.jsonl').read_text())

    def test_pat_из_вывода_cli_маскируется(self):
        _, token = self.connect()
        self.cli.rule(['issue', 'get'], stdout='ответ с {{TOKEN}} внутри')
        _, body = self.issue_get(token['access_token'])
        text = body['result']['content'][0]['text']
        self.assertNotIn(next(iter(self.multica.pats)), text)
        self.assertIn('[redacted]', text)

    def test_отозванный_в_multica_pat_закрывает_все_методы_сразу(self):
        _, token = self.connect()
        self.assertEqual(self.mcp('tools/list', token['access_token'])[0], 200)
        self.multica.revoke_all()
        for method in ('tools/list', 'initialize', 'ping'):
            with self.subTest(method=method):
                self.assertEqual(self.mcp(method, token['access_token'])[0], 401)
        self.assertEqual(len([c for c in self.cli.calls if c['argv'][:2] == ['issue', 'get']]), 0)

    def test_положительного_кэша_нет_каждый_запрос_проверяет_pat(self):
        _, token = self.connect()
        before = self.multica.me_pat_calls
        for _ in range(3):
            self.mcp('tools/list', token['access_token'])
        self.assertEqual(self.multica.me_pat_calls - before, 3)

    def test_недоступная_multica_503_и_доступ_возвращается_без_нового_входа(self):
        _, token = self.connect()
        self.multica.down = True
        status, _, resp = self.http('POST', '/mcp', body={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'},
                                    headers={'Authorization': 'Bearer ' + token['access_token']})
        self.assertEqual((status, resp.getheader('Retry-After')), (503, '30'))
        self.multica.down = False
        self.assertEqual(self.mcp('tools/list', token['access_token'])[0], 200)

    def test_истёкший_access(self):
        _, token = self.connect()
        self.clock.advance(ACCESS_TTL + 1)
        self.assertEqual(self.mcp('tools/list', token['access_token'])[0], 401)

    def test_чужой_неизвестный_и_refresh_вместо_access(self):
        _, token = self.connect()
        for bad in ('x' * 40, token['refresh_token']):
            self.assertEqual(self.mcp('tools/list', bad)[0], 401)

    def test_отзыв_через_endpoint(self):
        cid, token = self.connect()
        other = self.client_id()
        self.http('POST', '/mcp/oauth/revoke', raw=urlencode({'token': token['access_token'], 'client_id': other}).encode(),
                  headers={'Content-Type': FORM})
        self.assertEqual(self.mcp('tools/list', token['access_token'])[0], 200, 'чужой клиент не отзывает')
        status, _, _ = self.http('POST', '/mcp/oauth/revoke', raw=urlencode({'token': token['refresh_token'], 'client_id': cid}).encode(),
                                 headers={'Content-Type': FORM})
        self.assertEqual(status, 200)
        self.assertEqual(self.mcp('tools/list', token['access_token'])[0], 401)
        self.assertEqual(self.token(grant_type='refresh_token', client_id=cid, refresh_token=token['refresh_token'])[0], 400)
        status, _, _ = self.http('POST', '/mcp/oauth/revoke', raw=b'token=unknown&client_id=' + cid.encode(), headers={'Content-Type': FORM})
        self.assertEqual(status, 200)

    def test_два_человека_с_одним_именем_не_смешиваются(self):
        _, anna = self.connect('SESS-ANNA')
        _, twin = self.connect('SESS-ANNA2')
        self.issue_get(anna['access_token'])
        self.issue_get(twin['access_token'])
        calls = [c for c in self.cli.calls if c['argv'][:2] == ['issue', 'get']]
        pats = {c['env']['MULTICA_TOKEN'] for c in calls}
        self.assertEqual(len(pats), 2)
        self.assertEqual([l['user_id'] for l in self.audit_lines()][-2:], ['user-anna', 'user-anna-2'])
        self.assertEqual(len([c for c in self.cli.calls if c['argv'][:2] == ['workspace', 'list']]), 2, 'кэш членства на каждого свой')

    def test_ключевые_клиенты_и_oauth_сосуществуют(self):
        from multica_tasks.config import Client
        key_client = Client('Claude (MCP)', 'k' * 40, 'mul_static_pat', ('stt',), read_only=True)
        object.__setattr__(self.config, 'clients', (key_client,))
        self.handler = __import__('multica_tasks.http', fromlist=['make_handler']).make_handler(
            self.config, self.service, self.limiter, self.oauth_http)
        self.assertEqual(self.rpc('tools/list', key='k' * 40)[0], 200)
        _, token = self.connect()
        self.assertEqual(self.issue_get(token['access_token'])[0], 200)

    def test_oauth_соблюдает_перечень_команд(self):
        _, token = self.connect()
        status, body = self.rpc('tools/call', {'name': 'multica', 'arguments': {'args': ['daemon', 'start']}}, key=token['access_token'])
        self.assertEqual(body['error']['code'], -32602)


class Storage(OAuthCase):
    def test_состояние_переживает_рестарт(self):
        cid, token = self.connect()
        self.store.close()
        self.build_oauth()
        self.assertEqual(self.mcp('tools/list', token['access_token'])[0], 200)
        self.assertEqual(self.token(grant_type='refresh_token', client_id=cid, refresh_token=token['refresh_token'])[0], 200)
        self.assertIsNotNone(self.store.get_client(cid), 'DCR-регистрация сохранилась')

    def test_секреты_в_базе_только_хешами_и_шифртекстом(self):
        cid, verifier, code = self.approved_code()
        _, token = self.exchange(cid, verifier, code)
        pat = next(iter(self.multica.pats))
        raw = (self.state / 'oauth.sqlite').read_bytes()
        for secret in (code, token['access_token'], token['refresh_token'], pat, verifier):
            self.assertNotIn(secret.encode(), raw)
        self.assertEqual(stat.S_IMODE(os.stat(self.state / 'oauth.sqlite').st_mode), 0o600)
        self.assertNotIn(b'SESS-ANNA', raw, 'cookie сессии не сохраняется')

    def test_другой_ключ_не_расшифровывает_pat(self):
        from cryptography.fernet import Fernet
        _, token = self.connect()
        self.key = Fernet.generate_key()
        self.store.close()
        self.build_oauth()
        self.assertEqual(self.mcp('tools/list', token['access_token'])[0], 401)

    def test_все_логи_и_ошибки_без_секретов(self):
        import logging
        with self.assertLogs(level=logging.DEBUG) as logs:
            logging.getLogger('multica_tasks').info('start')
            cid, verifier, code = self.approved_code()
            _, token = self.exchange(cid, verifier, code)
            self.issue_get(token['access_token'])
        joined = '\n'.join(logs.output)
        pat = next(iter(self.multica.pats))
        for secret in (code, token['access_token'], token['refresh_token'], pat):
            self.assertNotIn(secret, joined)

    def test_просроченное_удаляется(self):
        self.connect()
        self.clock.advance(100 * 24 * 3600)
        self.oauth.purge()
        db = sqlite3.connect(self.state / 'oauth.sqlite')
        self.addCleanup(db.close)
        self.assertEqual([db.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in ('grants', 'tokens', 'codes', 'pending')], [0, 0, 0, 0])


if __name__ == '__main__':
    unittest.main()
