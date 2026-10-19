"""Ядро control_state, на которое опираются subs-pick (старт каждого рана claude/codex-reserve) и пульт."""
import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import control_state as control  # noqa: E402

NOW = dt.datetime(2026, 10, 19, 12, tzinfo=dt.timezone.utc)


class Store(unittest.TestCase):
    def test_пишет_только_изменения_и_атомарно(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state' / 'controls.json'
            with control.Store(path).locked() as s:
                self.assertEqual(s, {})
            self.assertFalse(path.exists(), 'неизменённое состояние не пишется')
            with control.Store(path).locked() as s:
                s['chains'] = {'a': {'tier': 'strong'}}
            self.assertEqual(json.loads(path.read_text()), {'chains': {'a': {'tier': 'strong'}}})
            self.assertEqual([p.name for p in path.parent.iterdir() if p.name.startswith('.controls-')], [])


class Windows(unittest.TestCase):
    def test_окно_упирается_в_свой_лимит_или_в_сто(self):
        self.assertTrue(control.window_blocked({'used': 80, 'cap': 80}))
        self.assertFalse(control.window_blocked({'used': 79, 'cap': 80}))
        self.assertTrue(control.window_blocked({'used': 100}))
        self.assertFalse(control.window_blocked({'used': None}))

    def test_итоговый_лимит_меньшее_из_лимита_и_резерва(self):
        self.assertEqual(control.effective_caps({'5h': 90, 'week': 100}, 15, ['5h', 'week']), {'5h': 85, 'week': 85})
        self.assertEqual(control.effective_caps({}, 0, ['5h']), {})

    def test_сброс_по_мск_через_новый_год(self):
        self.assertEqual(control.parse_reset('19.10 18:30', NOW), dt.datetime(2026, 10, 19, 15, 30, tzinfo=dt.timezone.utc))
        new_year = control.parse_reset('02.01 09:00', dt.datetime(2026, 12, 31, 12, tzinfo=dt.timezone.utc))
        self.assertEqual(new_year.year, 2027)
        self.assertIsNone(control.parse_reset('мусор', NOW))

    def test_доступность_runtime_по_строкам_дашборда(self):
        control.RUNTIME_ROWS['codex'] = ['main', 'spare']
        self.addCleanup(control.RUNTIME_ROWS.pop, 'codex')
        busy = {'name': 'main', 'windows': [{'used': 100, 'reset': '19.10 18:30'}]}
        free = {'name': 'spare', 'windows': [{'used': 10}]}
        self.assertTrue(control.available('codex', [busy, free]))
        self.assertFalse(control.available('codex', [busy, {**free, 'windows': [{'used': 100, 'reset': '19.10 20:00'}]}]))
        self.assertIsNone(control.available('unknown', [busy]))
        self.assertEqual(control.reset_at('codex', [busy, {**free, 'windows': [{'used': 100, 'reset': '19.10 20:00'}]}], NOW),
                         dt.datetime(2026, 10, 19, 15, 30, tzinfo=dt.timezone.utc))


class BlockedTools(unittest.TestCase):
    def test_запреты_переводятся_между_семействами(self):
        claude = ['--disallowedTools', 'mcp__github__delete_repo', 'mcp__github__merge_pull_request']
        tools = control.blocked_tools(claude)
        self.assertEqual(tools, [('github', 'delete_repo'), ('github', 'merge_pull_request')])
        codex = control.render_blocked(tools, 'codex')
        self.assertEqual(codex, ['-c', 'mcp_servers.github.disabled_tools=["delete_repo","merge_pull_request"]'])
        self.assertEqual(control.blocked_tools(codex), tools)
        self.assertEqual(control.derive_args('codex', [('claude', claude)]), codex)
        self.assertEqual(control.derive_args('claude', [('claude', claude)]), claude)


if __name__ == '__main__':
    unittest.main()
