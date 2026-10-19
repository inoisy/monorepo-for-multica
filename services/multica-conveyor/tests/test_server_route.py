"""Маршрут ведёт Multica: сторож только читает `multica issue conveyor get` перед вливанием."""
import re
import unittest
from pathlib import Path

from test_conveyor import c

SOURCE = Path(c.__file__).read_text()


def conveyor(steps='dev,qa,review,close', at='close', status='completed', accepted=''):
    route = [{'idx': i, 'step': step, 'agent_id': f'agent-{i}'} for i, step in enumerate(steps.split(','))]
    return {'status': status, 'step': at, 'current_idx': next(n['idx'] for n in route if n['step'] == at),
            'route': route, 'accepted_commit': accepted}


class NoRouteMachinery(unittest.TestCase):
    def test_ведение_маршрута_убрано(self):
        for name in ('run_routes', 'advance_route', 'route_move', 'report_route_failures', 'parse_route'):
            with self.subTest(name=name):
                self.assertFalse(hasattr(c, name))
                self.assertNotRegex(SOURCE, rf'\b{name}\b')
        self.assertNotIn('отчёт выше', SOURCE)
        self.assertNotRegex(SOURCE, r"meta(?:data)?\.get\('(?:route|step|verdict)'\)")

    def test_возможности_без_полосы_маршрутов(self):
        features = c.CAPABILITIES['features']
        self.assertIn('server-route-gate', features)
        for gone in ('routes', 'route-failures', 'route-gate'):
            self.assertNotIn(gone, features)


class RouteGate(unittest.TestCase):
    issue = {'metadata': {'branch': 't-1-x', 'commit': 'a' * 40}}

    def test_завершён_на_close_с_review_вливается(self):
        self.assertIsNone(c.route_gate(self.issue, conveyor()))
        self.assertIsNone(c.route_gate(self.issue, conveyor('dev,review,close')))
        self.assertIsNone(c.route_gate(self.issue, conveyor(accepted='a' * 12)))

    def test_причины_отказа(self):
        cases = {
            'нет маршрута': None,
            'маршрут выключен': conveyor(status='disabled'),
            'нет шага review': conveyor('dev,qa,close'),
            'шаг `review`': conveyor(at='review', status='active'),
            'шаг `dev`': conveyor(at='dev', status='awaiting_coordinator'),
            'шаг `close` (paused)': conveyor(status='paused'),
            'принял коммит bbbbbbbbbbbb': conveyor(accepted='b' * 40),
        }
        for expected, cv in cases.items():
            with self.subTest(expected=expected):
                why = c.route_gate(self.issue, cv)
                self.assertIsNotNone(why)
                if expected != 'маршрут выключен':
                    self.assertIn(expected, why)

    def test_metadata_route_не_читается(self):
        issue = {'metadata': {'commit': 'a' * 40, 'route': 'dev:Бэкенд,review:Техдиректор,close:Тимлид', 'step': 'close'}}
        self.assertIsNotNone(c.route_gate(issue, None))
        self.assertIsNone(c.route_gate({'metadata': {'commit': 'a' * 40, 'step': 'dev'}}, conveyor()))

    def test_лидер_нужен_только_когда_маршрута_не_дождаться(self):
        self.assertTrue(c.route_problem(None))
        self.assertTrue(c.route_problem(conveyor(status='disabled')))
        self.assertTrue(c.route_problem(conveyor('dev,close')))
        for status in ('active', 'paused', 'awaiting_coordinator', 'waiting_provider'):
            with self.subTest(status=status):
                self.assertFalse(c.route_problem(conveyor(at='dev', status=status)))


class ConveyorOf(unittest.TestCase):
    def test_нет_маршрута_это_none_а_сбой_cli_поднимается(self):
        def missing(*a, **k):
            raise RuntimeError('multica issue conveyor get: no route on this issue')

        def broken(*a, **k):
            raise RuntimeError('multica issue conveyor get: connection refused')

        self.assertIsNone(c.conveyor_of(missing, {'identifier': 'EP-2'}))
        with self.assertRaises(RuntimeError):
            c.conveyor_of(broken, {'identifier': 'EP-2'})
        calls = []
        self.assertEqual(c.conveyor_of(lambda *a, **k: calls.append(a) or conveyor(), {'identifier': 'EP-2'}), conveyor())
        self.assertEqual(calls, [('issue', 'conveyor', 'get', 'EP-2')])


if __name__ == '__main__':
    unittest.main()
