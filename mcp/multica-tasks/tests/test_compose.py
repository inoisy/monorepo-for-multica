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

    def test_tmpfs_is_one_mount_per_path_with_options(self):
        # В flow-списке запятая — разделитель элементов: опции монтирования не должны стать «путями».
        tmpfs = self.service()['tmpfs']
        self.assertEqual(tmpfs, ['/tmp:rw,noexec,nosuid,size=16m', '/run/multica-cli:rw,noexec,nosuid,size=16m,mode=1777'])

    def test_run_dir_is_the_tmpfs_and_service_stays_read_only(self):
        service = self.service()
        self.assertEqual(service['environment']['MULTICA_MCP_RUN_DIR'], '/run/multica-cli')
        self.assertIs(service['read_only'], True)
        self.assertEqual(service['cap_drop'], ['ALL'])

    def test_dockerfile_pins_backend_image_by_commit(self):
        import re
        dockerfile = (ADDON.parents[1] / 'Dockerfile').read_text()
        self.assertRegex(dockerfile, r'(?m)^ARG MULTICA_BACKEND_IMAGE=ghcr\.io/inoisy/multica-backend:[0-9a-f]{40}$')
        self.assertIn('COPY --from=multica-cli /app/multica /usr/local/bin/multica', dockerfile)
        self.assertIsNone(re.search(r'(?m)^FROM .*:latest', dockerfile))
        # Каталог запусков задаёт compose вместе с tmpfs: со старым compose без tmpfs cwd создаётся в /tmp
        self.assertNotIn('MULTICA_MCP_RUN_DIR', dockerfile)

    def test_every_tmpfs_entry_starts_with_absolute_path(self):
        for entry in self.service()['tmpfs']:
            self.assertTrue(entry.startswith('/'), entry)


if __name__ == '__main__':
    unittest.main()
