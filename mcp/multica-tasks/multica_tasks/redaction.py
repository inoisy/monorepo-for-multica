"""Маскирование секретов в данных до обрезки полей и JSON-кодирования.

Один Redactor делят аудит, раннер и сервис: секреты, выданные во время работы (PAT и токены OAuth),
добавляются через add() и сразу попадают во все три.
"""
import re
import threading


class Redactor:
    def __init__(self, secrets=()):
        self._lock = threading.Lock()
        self._secrets = set()
        self._pattern = None
        self.longest = 0
        self.add(*secrets)

    def add(self, *secrets):
        with self._lock:
            fresh = {s for s in secrets if s and s not in self._secrets}
            if not fresh:
                return
            self._secrets |= fresh
            self.longest = max(self.longest, *(len(s) for s in fresh))
            # Длинный секрет может содержать короткий: заменяем целое за один проход.
            ordered = sorted(self._secrets, key=len, reverse=True)
            self._pattern = re.compile('|'.join(re.escape(s) for s in ordered))

    def __call__(self, value):
        if isinstance(value, str):
            pattern = self._pattern
            return pattern.sub('[redacted]', value) if pattern else value
        if isinstance(value, dict):
            return {self(k): self(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self(v) for v in value]
        return value
