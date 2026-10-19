import copy
import unittest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import control_state as control  # noqa: E402


class AccountCards(unittest.TestCase):
    def setUp(self):
        self.subs = [
            {'id': 'main', 'provider': 'claude', 'quota_row': 'shared', 'reserve': 10,
             'windows': ['5h'], 'caps': {'5h': 80}, 'credential': 'main-path'},
            {'id': 'max', 'provider': 'claude', 'quota_row': 'shared', 'reserve': 10,
             'windows': ['5h', 'week'], 'caps': {'5h': 90, 'week': 95}, 'credential': 'max-path'},
            {'id': 'other', 'provider': 'codex', 'quota_row': 'shared', 'reserve': 0,
             'windows': ['week'], 'caps': {'week': 70}},
            {'id': 'standalone', 'provider': 'claude', 'windows': [], 'caps': {}, 'reserve': 0},
        ]

    def test_groups_shared_keys_by_provider_and_row_in_table_order(self):
        groups = control.accounts(self.subs)
        self.assertEqual([[s['id'] for s in group] for group in groups],
                         [['main', 'max'], ['other'], ['standalone']])

    def test_card_combines_windows_and_preserves_per_key_subscription_data(self):
        before = copy.deepcopy(self.subs)
        card = control.account_card(self.subs[:2])
        self.assertEqual(card['id'], 'main')
        self.assertEqual(card['keys'], ['main', 'max'])
        self.assertEqual(card['windows'], ['5h', 'week'])
        self.assertEqual(card['caps'], {'5h': 80, 'week': 95})
        self.assertEqual(card['effective'], {'5h': 80, 'week': 90})
        self.assertEqual(card['credential'], 'main-path · max-path')
        self.assertEqual(self.subs, before)

    def test_single_account_retains_its_subscription(self):
        card = control.account_card([self.subs[-1]])
        self.assertEqual(card, {**self.subs[-1], 'keys': ['standalone'], 'effective': {}})


if __name__ == '__main__':
    unittest.main()
