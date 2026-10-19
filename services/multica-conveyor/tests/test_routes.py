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

    def test_последний_шаг_меняет_статус_без_комментария(self):
        # Лидер уже проснулся от отчёта исполнителя (делегирование Multica), приёмку делает сторож:
        # комментарий владельца CLI разбудил бы лидера второй раз (STT-301, 19.10.2026).
        self.issues['pass'][0]['metadata'].update(step='review')
        w = self.run_routes()
        self.assertEqual(self.bodies, [])
        self.assertIn(('issue', 'update', 'EP-2', '--status', 'in_review'), self.writes)
        self.assertIn(('issue', 'metadata', 'set', 'EP-2', '--key', 'step', '--value', 'close'), self.writes)
        self.assertEqual(self.writes[-1], ('issue', 'metadata', 'delete', 'EP-2', '--key', 'verdict'))
        self.assertIn('шаг close', w.events[0][1])


class RouteFailures(unittest.TestCase):
    """Окончательное падение рана в задаче с `route` — лидеру, если его не подхватят сторож и Multica."""

    def setUp(self):
        self.now = c.now_utc().replace(microsecond=0)
        self.entry = {'failures_since': self.at(-60)}
        self.writes, self.bodies, self.fail_comment = [], [], False
        self.issue = {'identifier': 'EP-2', 'status': 'dev', 'metadata': {'route': ROUTE, 'step': 'dev'}}

    def at(self, minutes):
        return (self.now + c.dt.timedelta(minutes=minutes)).isoformat()

    def run_(self, rid='r1', minutes=-10, **extra):
        return {'id': rid, 'issue_id': 'i', 'status': 'failed', 'error': 'Tool crashed', 'failure_reason': 'agent_error.unknown',
                'created_at': self.at(minutes - 30), 'completed_at': self.at(minutes), **extra}

    def m(self, *args, write=False):
        if args[:2] == ('issue', 'get'):
            return self.issue
        if args[:3] == ('issue', 'comment', 'add'):
            if self.fail_comment:
                raise RuntimeError('CLI недоступен')
            self.bodies.append(open(args[args.index('--content-file') + 1]).read())
        self.writes.append(args)
        return {}

    def report(self, runs, name='Фронтенд'):
        w = FakeWatch()
        c.report_route_failures(self.m, w, {'name': name}, self.entry, runs, self.now, lambda: AGENTS)
        return w

    def test_падение_сообщается_лидеру_один_раз(self):
        self.report([self.run_()])
        self.report([self.run_()])
        self.assertEqual(len(self.bodies), 1)
        self.assertIn('mention://agent/l', self.bodies[0])
        self.assertIn('Tool crashed', self.bodies[0])

    def test_не_сообщается_то_что_подхватят_другие(self):
        self.report([self.run_('quota', error='You’ve hit your session limit'),
                     self.run_('infra', failure_reason='runtime_recovery', error=''),
                     self.run_('delegated', attribution={'delegated_from_task_id': 'src'}),
                     self.run_('fresh', minutes=-1),
                     self.run_('old', minutes=-90)])
        self.assertEqual(self.bodies, [])

    def test_повторённый_закрытый_и_без_маршрута_не_сообщаются(self):
        self.report([self.run_('r1'), {'id': 'r2', 'issue_id': 'i', 'status': 'running', 'created_at': self.at(-5)}])
        self.issue['status'] = 'done'
        self.report([self.run_('r3')])
        self.issue.update(status='dev', metadata={})
        self.report([self.run_('r4')])
        self.assertEqual(self.bodies, [])

    def test_ран_самого_лидера_не_сообщается(self):
        self.report([self.run_()], name='Тимлид')
        self.assertEqual(self.bodies, [])

    def test_недоставленное_сообщение_повторяется(self):
        self.fail_comment = True
        with self.assertRaises(RuntimeError):
            self.report([self.run_()])
        self.fail_comment = False
        self.report([self.run_()])
        self.assertEqual(len(self.bodies), 1)


if __name__ == '__main__':
    unittest.main()
