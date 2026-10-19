"""stand-seed: свежая база стенда получает справочники один раз, без настоящего стенда."""
import importlib.machinery
import importlib.util
import io
import json
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
loader = importlib.machinery.SourceFileLoader('stand_seed', str(HERE / 'stand-seed'))
spec = importlib.util.spec_from_loader('stand_seed', loader)
seed = importlib.util.module_from_spec(spec)
loader.exec_module(seed)


class Resp(io.BytesIO):
    def __init__(self, status, body, cookies=()):
        super().__init__(json.dumps(body).encode())
        self.status = status
        self.headers = type('H', (), {'get_all': lambda _s, _k: list(cookies)})()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeStand:
    def __init__(self, items):
        self.items, self.calls, self.logged_in = items, [], False

    def __call__(self, req, timeout):
        path = req.full_url.split('example.test', 1)[1]
        self.calls.append((req.get_method(), path))
        if path == '/auth/test/login':
            self.logged_in = True
            return Resp(200, {'csrfToken': 'c'}, ['resource_session=s1; Path=/'])
        if not self.logged_in:
            raise seed.urllib.error.HTTPError(req.full_url, 401, 'auth', {}, None)
        if path == '/api/v1/sync/status':
            return Resp(200, {'items': self.items})
        return Resp(202, {})


CFG = {'stands': [{'name': 'rp', 'url': 'https://rp.example.test', 'operator_principal': 'op', 'sources': ['sphere', 'hr']}]}


class StandSeed(unittest.TestCase):
    def test_пустая_база_получает_справочники(self):
        fake, state, out = FakeStand([]), {}, []
        self.assertEqual(seed.run(CFG, state, opener=fake, say=out.append), 0)
        self.assertIn(('POST', '/api/v1/sync/sphere'), fake.calls)
        self.assertIn(('POST', '/api/v1/sync/hr'), fake.calls)
        self.assertEqual(state['rp']['cookie'], 's1')

    def test_загруженная_или_идущая_загрузка_не_трогается(self):
        for items in ([{'lastSuccessAt': '2026-10-19T10:00:00Z'}], [{'lastSuccessAt': None, 'lastRun': {'status': 'running'}}]):
            fake = FakeStand(items)
            self.assertEqual(seed.run(CFG, {}, opener=fake, say=lambda _m: None), 0)
            self.assertFalse([c for c in fake.calls if c[0] == 'POST' and 'sync/' in c[1]])

    def test_dry_run_не_загружает(self):
        fake = FakeStand([])
        seed.run(CFG, {}, dry=True, opener=fake, say=lambda _m: None)
        self.assertFalse([c for c in fake.calls if 'sync/sphere' in c[1]])


if __name__ == '__main__':
    unittest.main()
