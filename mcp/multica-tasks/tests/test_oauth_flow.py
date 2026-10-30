import json
import re
import unittest
from html import unescape
from urllib.parse import parse_qs, urlsplit

from oauth_support import ANNA, ANNA2, CLAUDE_CALLBACK, FORM, RESOURCE, OAuthCase, cookie, pkce


class Metadata(OAuthCase):
    def test_без_токена_401_с_указанием_на_метаданные_и_без_счёта_неудач(self):
        for _ in range(self.config.auth_fail_limit + 2):
            status, _, resp = self.http('POST', '/mcp', body={})
            self.assertEqual(status, 401)
        self.assertEqual(resp.getheader('WWW-Authenticate'),
                         'Bearer resource_metadata="https://multica.yakutov.com/.well-known/oauth-protected-resource/mcp"')
        status, _, _ = self.http('POST', '/mcp', body={}, headers={'Authorization': 'Bearer wrong'})
        self.assertEqual(status, 401, 'обычный challenge не должен блокировать адрес')

    def test_неверный_токен_считается_перебором(self):
        for _ in range(self.config.auth_fail_limit):
            self.http('POST', '/mcp', body={}, headers={'Authorization': 'Bearer wrong'})
        status, _, _ = self.http('POST', '/mcp', body={}, headers={'Authorization': 'Bearer wrong'})
        self.assertEqual(status, 429)

    def test_protected_resource_и_корневой_вариант(self):
        for path in ('/.well-known/oauth-protected-resource/mcp', '/.well-known/oauth-protected-resource'):
            status, text, _ = self.http('GET', path)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(text), {
                'resource': RESOURCE, 'authorization_servers': ['https://multica.yakutov.com'],
                'scopes_supported': ['multica', 'offline_access'], 'bearer_methods_supported': ['header'],
                'resource_name': 'Multica'})

    def test_authorization_server(self):
        status, text, _ = self.http('GET', '/.well-known/oauth-authorization-server')
        meta = json.loads(text)
        self.assertEqual(status, 200)
        self.assertEqual(meta['issuer'], 'https://multica.yakutov.com')
        self.assertEqual(meta['registration_endpoint'], 'https://multica.yakutov.com/mcp/oauth/register')
        self.assertEqual(meta['code_challenge_methods_supported'], ['S256'])
        self.assertEqual(meta['token_endpoint_auth_methods_supported'], ['none'])
        self.assertEqual(meta['grant_types_supported'], ['authorization_code', 'refresh_token'])
        self.assertEqual(meta['response_types_supported'], ['code'])

    def test_метаданные_только_get_и_с_разрешённым_host(self):
        self.assertEqual(self.http('POST', '/.well-known/oauth-authorization-server', body={})[0], 405)
        self.assertEqual(self.http('GET', '/.well-known/oauth-authorization-server', headers={'Host': 'evil.example'})[0], 403)

    def test_без_oauth_пути_не_существуют(self):
        self.handler = __import__('multica_tasks.http', fromlist=['make_handler']).make_handler(self.config, self.service, self.limiter)
        self.assertEqual(self.http('GET', '/mcp/oauth/authorize')[0], 404)


class Registration(OAuthCase):
    def test_claude_и_loopback_регистрируются(self):
        status, body = self.register([CLAUDE_CALLBACK, 'http://localhost:54321/callback', 'http://127.0.0.1:1/callback'])
        self.assertEqual(status, 201)
        self.assertEqual(body['token_endpoint_auth_method'], 'none')
        self.assertNotIn('client_secret', body)
        self.assertEqual(self.http('GET', '/.well-known/oauth-authorization-server')[0], 200)

    def test_чужие_redirect_uri_отклоняются(self):
        for uri in ('https://evil.example/cb', 'http://evil.example/callback', 'https://claude.ai/other',
                    'http://localhost:1/other', 'http://localhost/callback?x=1', 'https://claude.ai.evil.example/api/mcp/auth_callback',
                    'javascript:alert(1)', 'http://user@localhost:1/callback', 'http://localhost:99999/callback'):
            with self.subTest(uri=uri):
                status, body = self.register([uri])
                self.assertEqual((status, body['error']), (400, 'invalid_redirect_uri'))

    def test_секретный_метод_и_лишние_grant_отклоняются(self):
        for extra in ({'token_endpoint_auth_method': 'client_secret_basic'}, {'grant_types': ['password']},
                      {'response_types': ['token']}, {'client_name': '\x00'}):
            with self.subTest(extra=extra):
                self.assertEqual(self.register(**{'redirect_uris': [CLAUDE_CALLBACK], **extra})[0], 400)

    def test_лимит_регистраций_с_адреса(self):
        statuses = [self.register()[0] for _ in range(22)]
        self.assertEqual(statuses[:20], [201] * 20)
        self.assertEqual(statuses[20], 429)

    def test_чужой_origin_и_не_json(self):
        self.assertEqual(self.http('POST', '/mcp/oauth/register', body={'redirect_uris': [CLAUDE_CALLBACK]},
                                   headers={'Origin': 'https://evil.example'})[0], 403)
        status, _, _ = self.http('POST', '/mcp/oauth/register', raw=b'{', headers={'Content-Type': 'application/json'})
        self.assertEqual(status, 400)


class Authorize(OAuthCase):
    def setUp(self):
        super().setUp()
        self.cid = self.client_id()
        self.verifier, self.challenge = pkce()

    def redirect_error(self, **kw):
        status, _, resp = self.authorize(self.cid, self.challenge, **kw)
        self.assertEqual(status, 302)
        return parse_qs(urlsplit(resp.getheader('Location')).query), resp.getheader('Location')

    def test_неизвестный_клиент_и_чужой_redirect_это_страница_без_перехода(self):
        for kw in ({'client_id': 'nope'}, {'redirect_uri': 'https://evil.example/cb'}):
            with self.subTest(kw=kw):
                cid = kw.get('client_id', self.cid)
                status, text, resp = self.authorize(cid, self.challenge, **{k: v for k, v in kw.items() if k != 'client_id'})
                self.assertEqual(status, 400)
                self.assertIsNone(resp.getheader('Location'))
                self.assertNotIn('evil.example', text.decode())

    def test_pkce_обязателен_и_только_s256(self):
        self.assertEqual(self.redirect_error(code_challenge=None)[0]['error'], ['invalid_request'])
        self.assertEqual(self.redirect_error(code_challenge_method='plain')[0]['error'], ['invalid_request'])
        self.assertEqual(self.redirect_error(code_challenge='short')[0]['error'], ['invalid_request'])
        self.assertEqual(self.redirect_error(code_challenge_method=None)[0]['error'], ['invalid_request'])

    def test_неверный_resource_scope_и_response_type(self):
        self.assertEqual(self.redirect_error(resource='https://evil.example/mcp')[0]['error'], ['invalid_target'])
        self.assertEqual(self.redirect_error(scope='admin')[0]['error'], ['invalid_scope'])
        self.assertEqual(self.redirect_error(response_type='token')[0]['error'], ['unsupported_response_type'])

    def test_ошибка_возвращает_state(self):
        query, _ = self.redirect_error(response_type='token', state='abc')
        self.assertEqual(query['state'], ['abc'])

    def test_повторяющиеся_параметры_отклоняются(self):
        status, _, _ = self.http('GET', f'/mcp/oauth/authorize?client_id={self.cid}&client_id={self.cid}')
        self.assertEqual(status, 400)

    def test_промежуточная_страница_а_не_редирект(self):
        status, text, resp = self.authorize(self.cid, self.challenge)
        self.assertEqual(status, 200)
        self.assertIsNone(resp.getheader('Location'))
        self.assertIn('http-equiv="refresh"', text.decode())
        self.assertIn("frame-ancestors 'none'", resp.getheader('Content-Security-Policy'))


class Consent(OAuthCase):
    def setUp(self):
        super().setUp()
        self.cid = self.client_id()
        self.verifier, self.challenge = pkce()
        self.req = self.request_id(self.cid, self.challenge)

    def test_без_входа_редирект_на_логин_multica_с_непрозрачным_next(self):
        status, _, resp = self.consent_page(self.req, session=None)
        self.assertEqual(status, 302)
        location = resp.getheader('Location')
        self.assertTrue(location.startswith('/login?next=%2Fmcp%2Foauth%2Fcontinue%3Freq%3D' + self.req), location)
        self.assertNotIn(self.challenge, location)
        self.assertNotIn(self.cid, location)

    def test_протухшая_сессия_это_тоже_логин(self):
        self.assertEqual(self.consent_page(self.req, session='SESS-OLD')[0], 302)

    def test_экран_показывает_пользователя_приложение_и_адрес_возврата(self):
        status, html, resp = self.consent_page(self.req)
        text = unescape(html.decode())
        self.assertEqual(status, 200)
        for expected in ('Анна', 'Claude', 'claude.ai', 'все, где вы состоите'):
            self.assertIn(expected, text)
        self.assertIn('value="approve"', text)
        self.assertIn('value="deny"', text)
        self.assertEqual(resp.getheader('Cache-Control'), 'no-store')

    def test_имя_приложения_экранируется(self):
        cid = self.client_id(client_name='<script>alert(1)</script>')
        req = self.request_id(cid, self.challenge)
        _, html, _ = self.consent_page(req)
        self.assertNotIn('<script>alert', html.decode())
        self.assertIn('&lt;script&gt;', html.decode())

    def test_страница_согласия_не_ломает_origin_формы(self):
        # no-referrer заставляет браузер слать в POST формы Origin: null, а он отклоняется
        _, _, resp = self.consent_page(self.req)
        self.assertEqual(resp.getheader('Referrer-Policy'), 'same-origin')

    def test_origin_публичного_адреса_проходит_а_null_и_чужой_нет(self):
        _, html, _ = self.consent_page(self.req)
        csrf = self.csrf_of(html)
        for origin in ('null', 'https://evil.example', 'http://multica.yakutov.com'):
            with self.subTest(origin=origin):
                self.assertEqual(self.decide(self.req, csrf, headers={'Origin': origin})[0], 403)
        self.assertEqual(self.multica.created, [])
        self.assertEqual(self.decide(self.req, csrf, headers={'Origin': 'https://multica.yakutov.com'})[0], 302)

    def test_адрес_возврата_loopback_показывается_с_портом(self):
        cid = self.client_id(['http://localhost:54321/callback'])
        req = self.request_id(cid, self.challenge, redirect_uri='http://localhost:54321/callback')
        _, html, _ = self.consent_page(req)
        self.assertIn('localhost:54321', html.decode())

    def test_согласие_выдаёт_code_и_pat_с_конечным_сроком(self):
        _, html, _ = self.consent_page(self.req)
        status, _, resp = self.decide(self.req, self.csrf_of(html))
        self.assertEqual(status, 302)
        location = resp.getheader('Location')
        self.assertTrue(location.startswith(CLAUDE_CALLBACK + '?'))
        query = parse_qs(urlsplit(location).query)
        self.assertEqual(query['state'], ['st-1'])
        self.assertEqual(len(self.multica.created), 1)
        name, days = self.multica.created[0]
        self.assertEqual(days, 90)
        self.assertIn('Claude MCP', name)

    def test_отказ_не_выпускает_pat(self):
        _, html, _ = self.consent_page(self.req)
        status, _, resp = self.decide(self.req, self.csrf_of(html), decision='deny')
        query = parse_qs(urlsplit(resp.getheader('Location')).query)
        self.assertEqual((status, query['error'], query['state']), (302, ['access_denied'], ['st-1']))
        self.assertNotIn('code', query)
        self.assertEqual(self.multica.created, [])

    def test_csrf_обязателен_и_привязан_к_пользователю_и_запросу(self):
        _, html, _ = self.consent_page(self.req)
        good = self.csrf_of(html)
        other_req = self.request_id(self.cid, self.challenge)
        for csrf, session in (('', 'SESS-ANNA'), ('0' * 64, 'SESS-ANNA'), (good, 'SESS-ANNA2')):
            with self.subTest(csrf=csrf[:6], session=session):
                status, _, _ = self.decide(self.req, csrf, session=session)
                self.assertEqual(status, 403)
        self.assertEqual(self.decide(other_req, good)[0], 403, 'токен от другого запроса')
        self.assertEqual(self.multica.created, [])

    def test_чужой_origin_и_отсутствие_сессии_не_выпускают_pat(self):
        _, html, _ = self.consent_page(self.req)
        csrf = self.csrf_of(html)
        self.assertEqual(self.decide(self.req, csrf, headers={'Origin': 'https://evil.example'})[0], 403)
        self.assertEqual(self.decide(self.req, csrf, session=None)[0], 401)
        self.assertEqual(self.multica.created, [])

    def test_повторная_отправка_не_выпускает_второй_pat(self):
        _, html, _ = self.consent_page(self.req)
        csrf = self.csrf_of(html)
        self.assertEqual(self.decide(self.req, csrf)[0], 302)
        self.assertEqual(self.decide(self.req, csrf)[0], 400)
        self.assertEqual(len(self.multica.created), 1)

    def test_запрос_истекает(self):
        self.clock.advance(11 * 60)
        self.assertEqual(self.consent_page(self.req)[0], 400)

    def test_multica_недоступна_это_503_и_pat_не_создан(self):
        self.multica.down = True
        status, _, resp = self.consent_page(self.req)
        self.assertEqual((status, resp.getheader('Retry-After')), (503, '30'))

    def test_сессия_с_неверным_csrf_multica_pat_не_создаёт(self):
        # у куки-сессии нет читаемой CSRF-cookie: Multica отклонит создание, согласие не должно проходить
        _, html, _ = self.consent_page(self.req)
        status, _, _ = self.decide(self.req, self.csrf_of(html), headers={'Cookie': 'multica_auth=SESS-ANNA'})
        self.assertEqual(status, 401)
        self.assertEqual(self.multica.created, [])


if __name__ == '__main__':
    unittest.main()
