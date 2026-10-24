"""Ошибки инструментов: код + текст, без секретов. Всё, что не ToolError, наружу текстом не уходит."""


class ToolError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self):
        return {'error': {'code': self.code, 'message': self.message}}


class ApiError(Exception):
    """Ответ Multica API с ошибкой или сбой связи. status=0 — не достучались."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


class ForbiddenCall(Exception):
    """Вызов вне белого списка (метод, шаблон пути): ошибка программиста, а не пользователя."""
