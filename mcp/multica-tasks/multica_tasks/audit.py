"""Аудит записей: JSONL в $STATE_DIRECTORY/audit.jsonl (0600). Ключ MCP и PAT вырезаются из строки целиком."""
import hashlib
import json
import os
import threading
import time

HEAD_CHARS = 200


def text_digest(text):
    return {'sha256': hashlib.sha256(text.encode()).hexdigest(), 'head': text[:HEAD_CHARS], 'length': len(text)}


class AuditLog:
    def __init__(self, path, secrets=(), clock=time.time):
        self.path, self._secrets, self._clock = path, tuple(s for s in secrets if s), clock
        self._lock = threading.Lock()
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)

    def write(self, **fields):
        entry = {'time': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(self._clock())), **fields}
        line = json.dumps(entry, ensure_ascii=False, sort_keys=True)
        for secret in self._secrets:
            line = line.replace(secret, '[redacted]')
        with self._lock:
            fd = os.open(self.path, os.O_WRONLY | os.O_APPEND)
            try:
                os.write(fd, (line + '\n').encode())
                os.fsync(fd)
            finally:
                os.close(fd)
