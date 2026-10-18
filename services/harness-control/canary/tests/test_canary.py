import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

import importlib.util

SPEC = importlib.util.spec_from_file_location('canary', Path(__file__).resolve().parent.parent / 'canary.py')
canary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(canary)


class Canary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_статус_пишется_с_версией_и_тиком(self):
        (self.dir / 'VERSION').write_text('7\n')
        now = dt.datetime(2026, 10, 18, 6, 0, 5, tzinfo=dt.timezone.utc)
        self.assertEqual(canary.run(self.dir, self.dir / 'state', now), 0)
        status = json.loads((self.dir / 'state' / 'status.json').read_text())
        self.assertEqual(status, {'tick': '2026-10-18 06:00:05', 'version': '7', 'errors': []})

    def test_сбойная_версия_завершается_с_ошибкой(self):
        (self.dir / 'VERSION').write_text('2-fail\n')
        self.assertEqual(canary.run(self.dir, self.dir / 'state'), 1)
        self.assertTrue(json.loads((self.dir / 'state' / 'status.json').read_text())['errors'])


if __name__ == '__main__':
    unittest.main()
