"""Маскирование настроенных секретов в данных до обрезки полей и JSON-кодирования."""
import re


class Redactor:
    def __init__(self, secrets=()):
        # Длинный секрет может содержать короткий: заменяем целое за один проход.
        secrets = sorted({s for s in secrets if s}, key=len, reverse=True)
        self._pattern = re.compile('|'.join(re.escape(s) for s in secrets)) if secrets else None

    def __call__(self, value):
        if isinstance(value, str):
            return self._pattern.sub('[redacted]', value) if self._pattern else value
        if isinstance(value, dict):
            return {self(k): self(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self(v) for v in value]
        return value
