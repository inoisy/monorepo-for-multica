"""Вырезание секретов из логов проверок и ответов. Лог хранится только после редакции.

Вход — вывод кандидата, то есть недоверенный: шаблоны линейные (старт только на границе «слова», длины ограничены),
а длина строки и всего текста обрезается до редакции.
"""
import re

REDACTED = '[скрыто]'
MAX_LINE = 4096
MAX_TEXT = 2 << 20
_NOT_WORD = r'(?<![\w.-])'
_NAME = r'[\w.-]{0,64}?(?:token|secret|passw(?:or)?d|passwd|api[_-]?key|credential|private[_-]?key|authorization)[\w.-]{0,64}'
_PATTERNS = [
    (re.compile(r'(?i)(?<![\w])(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,256}'), r'\1 ' + REDACTED),
    (re.compile(r'(?i)' + _NOT_WORD + r'(' + _NAME + r')(\s{0,8}[=:]\s{0,8})("[^"\n]{0,512}"|\'[^\'\n]{0,512}\'|[^\s"\']{1,512})'), r'\1\2' + REDACTED),
    (re.compile(r'(?<=://)[^/\s:@]{1,128}:[^/\s@]{1,256}(?=@)'), REDACTED),
    (re.compile(r'\b(?:gh[pousr]_|github_pat_|glpat-|sk-|xox[abp]-|npm_|AKIA)[A-Za-z0-9_-]{10,256}'), REDACTED),
    (re.compile(r'\beyJ[A-Za-z0-9_-]{8,2048}\.[A-Za-z0-9_-]{8,2048}\.[A-Za-z0-9_-]{4,2048}'), REDACTED),
]
_KEY_BLOCK = re.compile(r'-----BEGIN [A-Z ]{0,32}PRIVATE KEY-----.{0,8192}?(?:-----END [A-Z ]{0,32}PRIVATE KEY-----|\Z)', re.S)


def clip(text, limit=MAX_TEXT):
    """Обрезка по размеру: хвост важнее начала только для строк, поэтому режем строки, а не весь текст."""
    if len(text) > limit:
        text = text[:limit] + '\n[вывод обрезан]'
    return '\n'.join(l if len(l) <= MAX_LINE else l[:MAX_LINE] + ' [строка обрезана]' for l in text.split('\n'))


def redact(text, literals=()):
    """literals — значения, которые вырезаются дословно (например, из окружения проверки)."""
    text = clip(text)
    for value in literals:
        if value and len(value) >= 6:
            text = text.replace(value, REDACTED)
    text = _KEY_BLOCK.sub(REDACTED, text)
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text
