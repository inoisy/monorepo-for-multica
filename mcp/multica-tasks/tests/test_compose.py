"""Боевой compose-аддон: Docker принимает только то, что видно после разбора YAML."""
import re
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

    def test_oauth_key_is_mounted_read_only_outside_state_dir(self):
        service = self.service()
        key = service['environment']['MULTICA_MCP_OAUTH_KEY_FILE']
        self.assertIn(f'{key}:{key}:ro', service['volumes'])
        self.assertFalse(key.startswith('/state'))
        self.assertEqual(service['environment']['MULTICA_MCP_PUBLIC_URL'], 'https://multica.yakutov.com')

    def test_operator_script_embeds_the_same_compose_and_caddy_block(self):
        # Скрипт оператора пишет compose и блок Caddy сам: расхождение с файлами репозитория запрещено.
        import re
        script = (ADDON.parent / 'enable-oauth.sh').read_text()
        compose = re.search(r"mcp_yml\(\) \{.*?cat <<YML\n(.*?)\nYML\n", script, re.S).group(1)
        compose = compose.replace('\\${', '${').replace('$1', '    user: X')
        expected = ADDON.read_text()
        expected = re.sub(r'(?m)^    user: .*$', '    user: X', expected)
        self.assertEqual(compose, expected.rstrip('\n'))
        block = re.search(r"caddy_block\(\) \{\n  cat <<'CADDY'\n(.*?)\nCADDY\n", script, re.S).group(1)
        fragment = (ADDON.parent / 'Caddyfile.fragment').read_text()
        fragment = '\n'.join(l for l in fragment.splitlines() if not l.startswith('#')).strip('\n')
        self.assertEqual(block, fragment)

    def test_caddy_routes_only_exact_oauth_paths(self):
        fragment = (ADDON.parent / 'Caddyfile.fragment').read_text()
        matcher = re.search(r'@mcp path (.*)', fragment).group(1).split()
        self.assertEqual(matcher, ['/mcp', '/mcp/oauth/*', '/.well-known/oauth-protected-resource',
                                   '/.well-known/oauth-protected-resource/mcp', '/.well-known/oauth-authorization-server'])

    def test_every_tmpfs_entry_starts_with_absolute_path(self):
        for entry in self.service()['tmpfs']:
            self.assertTrue(entry.startswith('/'), entry)


if __name__ == '__main__':
    unittest.main()
