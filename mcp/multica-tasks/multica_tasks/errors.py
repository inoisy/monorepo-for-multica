"""Ошибки сервера: InvalidParams уходит JSON-RPC -32602, ToolError — результатом инструмента с isError."""


class InvalidParams(Exception):
    """Аргументы или команда не прошли проверку: процесс не запускался."""

    def __init__(self, message, denied=None):
        super().__init__(message)
        self.message = message
        self.denied = denied  # причина отказа allowlist для аудита; None — ошибка формы аргументов


class ToolError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self):
        return {'error': {'code': self.code, 'message': self.message}}
