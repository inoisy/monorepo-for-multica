"""Маршрут задачи ведёт сторож: агент пишет `verdict`, сторож упоминает следующего, возвращает или зовёт лидера."""
import unittest

from test_conveyor import c

ROUTE = 'dev:Бэкенд,dev:Фронтенд,qa:Тестировщик,review:Техдиректор,close:Тимлид'
AGENTS = {'Бэкенд': 'b', 'Фронтенд': 'f', 'Тестировщик': 'q', 'Техдиректор': 't', 'Тимлид': 'l'}


def move(**meta):
    return c.route_move({'route': ROUTE, **meta})


class RouteMove(unittest.TestCase):
    def test_прошло_зовёт_следующего_даже_на_том_же_шаге(self):
        self.assertEqual(move(step='dev', verdict='pass')[0::2], ('Фронтенд', {'step': 'dev', 'pos': 1}))
        self.assertEqual(move(step='dev', pos='1', verdict='pass')[0::2], ('Тестировщик', {'step': 'qa', 'pos': 2}))

    def test_шаг_переписанный_лидером_главнее_старого_pos(self):
        self.assertEqual(move(step='dev', pos='3', verdict='pass')[0::2], ('Фронтенд', {'step': 'dev', 'pos': 1}))

    def test_последний_шаг_ставит_in_review_и_зовёт_лидера(self):
        who, _, keys, status = move(step='review', verdict='pass')
        self.assertEqual((who, keys, status), ('Тимлид', {'step': 'close', 'pos': 4}, 'in_review'))

    def test_не_прошло_возвращает_ближайшему_dev_с_кругом(self):
        who, _, keys, status = move(step='qa', verdict='fail')
        self.assertEqual((who, keys, status), ('Фронтенд', {'step': 'dev', 'pos': 1, 'round': 1}, None))

    def test_третий_круг_и_блокер_к_лидеру(self):
        self.assertEqual(move(step='review', verdict='fail', round='2')[0::2], ('Тимлид', {'round': 3}))
        self.assertEqual(move(step='qa', verdict='blocked')[0::2], ('Тимлид', {}))

    def test_не_прошло_без_dev_и_неизвестный_шаг_к_лидеру(self):
        self.assertEqual(move(step='dev', verdict='fail')[0::2], ('Тимлид', {}))
        self.assertEqual(move(step='intake', verdict='pass')[0::2], ('Тимлид', {}))


class FakeWatch:
    dry = False

    def __init__(self): self.events = []
    def permit(self, settings=None): pass
    def log(self, kind, text): self.events.append((kind, text))


class Advance(unittest.TestCase):
    def setUp(self):
        self.writes, self.bodies, self.fail_comment = [], [], False
        self.issues = {'pass': [{'identifier': 'EP-2', 'status': 'qa', 'metadata': {
            'route': ROUTE, 'step': 'qa', 'verdict': 'pass', 'branch': 't-1-x', 'commit': 'a' * 40}}]}

    def m(self, *args, write=False):
        if args[:2] == ('issue', 'list'):
            return {'issues': self.issues.get(args[-3].split('=')[1], [])}
        if args[:2] == ('agent', 'list'):
            return {'agents': [{'name': n, 'id': i} for n, i in AGENTS.items()]}
        if args[:3] == ('issue', 'comment', 'add'):
            if self.fail_comment:
                raise RuntimeError('CLI недоступен')
            self.bodies.append(open(args[args.index('--content-file') + 1]).read())
        self.writes.append(args)
        return {}

    def run_routes(self):
        w = FakeWatch()
        orig = c.Multica
        c.Multica = lambda ws, dry, guard=None: self.m
        try:
            c.run_routes(w, {'ws'})
        finally:
            c.Multica = orig
        return w

    def test_упоминание_раньше_метаданных_и_снятия_итога(self):
        self.run_routes()
        self.assertIn('mention://agent/t', self.bodies[0])
        self.assertIn('`t-1-x`', self.bodies[0])
        self.assertEqual([a[:3] for a in self.writes], [('issue', 'comment', 'add'), ('issue', 'metadata', 'set'),
                                                        ('issue', 'metadata', 'set'), ('issue', 'metadata', 'delete')])
        self.assertEqual(self.writes[-1], ('issue', 'metadata', 'delete', 'EP-2', '--key', 'verdict'))

    def test_недоставленное_упоминание_оставляет_итог_до_следующего_тика(self):
        self.fail_comment = True
        w = self.run_routes()
        self.assertEqual(self.writes, [])
        self.assertEqual(w.events[0][0], 'error')

    def test_закрытая_задача_только_снимает_итог(self):
        self.issues['pass'][0]['status'] = 'done'
        self.run_routes()
        self.assertEqual(self.writes, [('issue', 'metadata', 'delete', 'EP-2', '--key', 'verdict')])

    def test_последний_шаг_меняет_статус(self):
        self.issues['pass'][0]['metadata'].update(step='review')
        self.run_routes()
        self.assertIn(('issue', 'update', 'EP-2', '--status', 'in_review'), self.writes)
        self.assertIn('mention://agent/l', self.bodies[0])


if __name__ == '__main__':
    unittest.main()
