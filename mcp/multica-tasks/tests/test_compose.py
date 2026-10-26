"""Боевой compose-аддон: Docker принимает только то, что видно после разбора YAML."""
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

ADDON = Path(__file__).resolve().parents[1] / 'deploy' / 'compose.production.yaml'


@unittest.skipIf(yaml is None, 'нужен PyYAML')
class ProductionComposeTest(unittest.TestCase):
    def service(self):
        return yaml.safe_load(ADDON.read_text())['services']['multica-tasks-mcp']

    def test_tmpfs_is_single_mount_with_options(self):
        # В flow-списке запятая — разделитель элементов: опции монтирования не должны стать «путями».
        tmpfs = self.service()['tmpfs']
        self.assertEqual(tmpfs, ['/tmp:rw,noexec,nosuid,size=16m'])

    def test_every_tmpfs_entry_starts_with_absolute_path(self):
        for entry in self.service()['tmpfs']:
            self.assertTrue(entry.startswith('/'), entry)


if __name__ == '__main__':
    unittest.main()
