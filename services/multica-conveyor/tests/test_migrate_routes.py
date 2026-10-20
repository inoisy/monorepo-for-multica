"""Перевод задач с маршрутом сторожа на серверный маршрут: что включается, что чистится, что в отчёт."""
import importlib.machinery, importlib.util, unittest
from pathlib import Path

path = str(Path(__file__).resolve().parent.parent / 'migrate-routes')
spec = importlib.util.spec_from_loader('migrate_routes', importlib.machinery.SourceFileLoader('migrate_routes', path))
mr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mr)

ROUTE = 'dev:Бэкенд,qa:Тестировщик,review:Техдиректор,close:Тимлид'


def issue(key, status='in_progress', **meta):
    return {'identifier': key, 'status': status, 'metadata': meta}


class Fake:
    def __init__(self, root, children, conveyors=(), refuse=()):
        self.root, self.children, self.conveyors, self.refuse = root, children, set(conveyors), set(refuse)
        self.calls = []

    def __call__(self, *a):
        self.calls.append(a)
        if a[:2] == ('issue', 'get'):
            return {'issue': self.root}
        if a[:2] == ('issue', 'children'):
            return {'stages': [{'stage': 1, 'issues': self.children}], 'unstaged': []}
        if a[:3] == ('issue', 'conveyor', 'get'):
            if a[3] in self.conveyors:
                return {'status': 'active'}
            raise RuntimeError('multica issue conveyor get: no route on this issue')
        if a[:3] == ('issue', 'conveyor', 'enable') and a[3] in self.refuse:
            raise RuntimeError('multica issue conveyor: an active run already holds the issue')
        return {}

    def writes(self):
        return [a for a in self.calls if a[:3] in (('issue', 'conveyor', 'enable'), ('issue', 'metadata', 'delete'))]


class Migrate(unittest.TestCase):
    def setUp(self):
        self.root = issue('STT-239', 'in_progress')  # эпик без маршрута — не трогается
        self.children = [
            issue('STT-240', route=ROUTE, step='qa', pos='1', round='1', branch='t-1', commit='a' * 40),
            issue('STT-241', 'in_review', route=ROUTE, step='close', pos='3'),
            issue('STT-242', route=ROUTE, step='dev', verdict='pass'),
            issue('STT-243', 'done', route=ROUTE, step='close'),
            issue('STT-244', route=ROUTE, step='review'),
            issue('STT-245', route=ROUTE, step='dev'),
        ]
        self.out = []

    def run_it(self, apply, **kw):
        m = Fake(self.root, self.children, **kw)
        return m, mr.migrate(m, ['STT-239'], apply=apply, out=self.out.append)

    def test_сухой_прогон_ничего_не_пишет(self):
        m, report = self.run_it(False)
        self.assertEqual(m.writes(), [])
        self.assertIn(f'STT-240: enable --route {ROUTE} --from-step qa', self.out)
        self.assertEqual([k for k, _ in report], ['STT-241', 'STT-242'])

    def test_включение_с_текущего_шага_и_чистка_metadata(self):
        m, report = self.run_it(True, conveyors={'STT-244'}, refuse={'STT-245'})
        w = m.writes()
        self.assertIn(('issue', 'conveyor', 'enable', 'STT-240', '--route', ROUTE, '--from-step', 'qa'), w)
        self.assertEqual([a[5] for a in w if a[:4] == ('issue', 'metadata', 'delete', 'STT-240')], ['route', 'pos', 'round'])
        # branch и commit остаются — по ним сторож принимает задачу
        self.assertFalse(any(a[5] in ('branch', 'commit') for a in w if a[:3] == ('issue', 'metadata', 'delete')))
        # закрытая — только чистка; уже включённая на сервере — без повторного enable
        self.assertNotIn('STT-243', [a[3] for a in w if a[2] == 'enable'])
        self.assertIn(('issue', 'metadata', 'delete', 'STT-243', '--key', 'route'), w)
        self.assertNotIn('STT-244', [a[3] for a in w if a[2] == 'enable'])
        self.assertIn(('issue', 'metadata', 'delete', 'STT-244', '--key', 'route'), w)
        self.assertFalse([a for a in w if a[:3] == ('issue', 'metadata', 'delete') and a[5] == 'step'])
        # пройденная, сданная без передачи и отклонённая сервером — в отчёт, metadata не трогается
        self.assertEqual(sorted(k for k, _ in report), ['STT-241', 'STT-242', 'STT-245'])
        for key in ('STT-241', 'STT-242', 'STT-245'):
            self.assertFalse([a for a in w if a[:3] == ('issue', 'metadata', 'delete') and a[3] == key])
        self.assertFalse([a for a in m.calls if 'STT-239' in a and a[:3] != ('issue', 'get', 'STT-239')
                          and a[:2] != ('issue', 'children')])


if __name__ == '__main__':
    unittest.main()
