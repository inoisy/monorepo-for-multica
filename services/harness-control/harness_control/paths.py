"""Пути harness-control. HARNESS_ROOT переносит всё под каталог — только для тестов и только не от root."""
import os
from pathlib import Path

AGENT_USER_DEFAULT = 'agents'


class Paths:
    def __init__(self, root='/'):
        self.root = Path(root)

    @classmethod
    def from_env(cls):
        # От root переменная окружения не принимается: sudo её и так сбрасывает, это второй рубеж.
        override = os.environ.get('HARNESS_ROOT')
        return cls(override if override and os.geteuid() != 0 else '/')

    def host(self, absolute):
        """Системный абсолютный путь → путь на диске (под HARNESS_ROOT в тестах)."""
        absolute = str(absolute)
        if not absolute.startswith('/'):
            raise ValueError(f'нужен абсолютный путь: {absolute}')
        return self.root / absolute.lstrip('/')

    @property
    def state(self): return self.host('/var/lib/harness-control')
    @property
    def etc(self): return self.host('/etc/harness-control')
    @property
    def policy_dir(self): return self.etc / 'policy.d'
    @property
    def lib(self): return self.host('/usr/local/lib/harness-control')
    @property
    def checks(self): return self.lib / 'checks'
    @property
    def db(self): return self.state / 'ops.db'
    @property
    def ops(self): return self.state / 'ops'
    @property
    def artifacts(self): return self.state / 'artifacts'
    @property
    def releases(self): return self.state / 'releases'
    @property
    def mirror(self): return self.state / 'mirror'
    @property
    def work(self): return self.host('/run/harness-control/work')
    @property
    def locks(self): return self.state / 'locks'
    @property
    def audit(self): return self.state / 'audit.jsonl'

    def op_dir(self, op_id): return self.ops / op_id
