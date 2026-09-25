import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from regression import prepare, verify


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'case'

    def setup_case(self, name):
        with contextlib.redirect_stdout(io.StringIO()):
            prepare(name, self.root)
        return self.root / 'repo'

    def test_create_requires_output_and_preserves_rules(self):
        repo = self.setup_case('create')
        self.assertTrue(verify(self.root))
        original = (repo / 'CLAUDE.md').read_text()
        (repo / 'AGENTS.md').write_text(original + 'Задачи: https://sphere.loodsen.ru\n')
        (repo / 'CLAUDE.md').write_text('@AGENTS.md\n')
        self.assertEqual(verify(self.root), [])
        (repo / 'AGENTS.md').write_text('Отвечать по-русски.\n')
        self.assertTrue(verify(self.root))

    def test_duplicate_and_placeholder_fail(self):
        repo = self.setup_case('create')
        (repo / 'AGENTS.md').write_text((repo / 'CLAUDE.md').read_text() + '<команда>\n')
        (repo / 'CLAUDE.md').write_text('@AGENTS.md\n@AGENTS.md\n')
        errors = verify(self.root)
        self.assertTrue(any('подстановка' in e for e in errors))
        self.assertTrue(any('Повтор импорта' in e for e in errors))

    def test_audit_rejects_changes_and_external_calls(self):
        repo = self.setup_case('audit')
        self.assertEqual(verify(self.root), [])
        subprocess.run([sys.executable, str(repo / 'external.py'), 'push'], capture_output=True)
        self.assertTrue(any('Вызваны внешние' in e for e in verify(self.root)))
        (repo / 'AGENTS.md').write_text('Изменено\n')
        self.assertTrue(any('вне области' in e for e in verify(self.root)))

    def test_update_preserves_dirty_file(self):
        repo = self.setup_case('update')
        self.assertTrue(verify(self.root))
        path = repo / 'AGENTS.md'
        path.write_text(path.read_text().replace('tests/unit', 'tests/specs'))
        self.assertEqual(verify(self.root), [])
        (repo / 'notes.txt').write_text('Исходная заметка.\n')
        self.assertTrue(verify(self.root))

    def test_repeat_rejects_any_change(self):
        repo = self.setup_case('repeat')
        self.assertEqual(verify(self.root), [])
        (repo / 'new.txt').write_text('Новый файл\n')
        self.assertTrue(verify(self.root))

    def test_prepare_does_not_overwrite(self):
        self.setup_case('repeat')
        with self.assertRaises(FileExistsError):
            prepare('repeat', self.root)


if __name__ == '__main__':
    unittest.main()
