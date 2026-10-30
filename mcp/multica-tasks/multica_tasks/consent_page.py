"""HTML экранов OAuth: согласие, ошибка, промежуточная страница. Все значения пользователя и клиента экранируются."""
from html import escape

STYLE = '''
:root{color-scheme:light dark;--bg:#f6f7f9;--card:#fff;--text:#16181d;--muted:#5b6270;--line:#d9dde4;--accent:#2457d6;--accent-text:#fff;--danger:#8f1d1d}
@media (prefers-color-scheme:dark){:root{--bg:#101216;--card:#1a1d24;--text:#eceef2;--muted:#a0a7b4;--line:#2f343e;--accent:#6b97ff;--accent-text:#0b1020;--danger:#ff9a9a}}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:16px;background:var(--bg);color:var(--text);font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{width:100%;max-width:440px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:24px}
h1{margin:0 0 12px;font-size:1.25rem;line-height:1.3}
p{margin:0 0 12px}
.muted{color:var(--muted);font-size:.9rem}
dl{margin:0 0 16px;display:grid;grid-template-columns:auto 1fr;gap:6px 12px}
dt{color:var(--muted)}dd{margin:0;overflow-wrap:anywhere}
.actions{display:flex;gap:12px}
button{flex:1;height:44px;padding:0 16px;border-radius:8px;border:1px solid var(--line);background:transparent;color:var(--text);font:inherit;cursor:pointer}
button.primary{background:var(--accent);border-color:var(--accent);color:var(--accent-text);font-weight:600}
.error{color:var(--danger)}
'''


def _page(title, body):
    return ('<!doctype html><html lang="ru"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="robots" content="noindex"><title>{escape(title)}</title><style>{STYLE}</style></head>'
            f'<body><main>{body}</main></body></html>')


def consent(user_name, client_name, return_host, req_id, csrf):
    return _page('Подключение к Multica', f'''
<h1>Разрешить доступ к Multica?</h1>
<dl>
<dt>Вы</dt><dd>{escape(user_name)}</dd>
<dt>Приложение</dt><dd>{escape(client_name)}</dd>
<dt>Вернётся на</dt><dd>{escape(return_host or '')}</dd>
<dt>Воркспейсы</dt><dd>все, где вы состоите, включая появившиеся позже</dd>
<dt>Действия</dt><dd>задачи, проекты и просмотр данных Multica от вашего имени — по списку команд сервиса</dd>
</dl>
<p class="muted">Для доступа будет выпущен отдельный токен на 90 дней; отозвать его можно в настройках токенов Multica.</p>
<form method="post" action="/mcp/oauth/consent">
<input type="hidden" name="req" value="{escape(req_id)}"><input type="hidden" name="csrf" value="{escape(csrf)}">
<div class="actions"><button type="submit" name="decision" value="deny">Отказать</button>
<button type="submit" name="decision" value="approve" class="primary">Разрешить</button></div>
</form>''')


def error(message):
    return _page('Подключение к Multica', f'<h1 class="error">Не удалось подключить</h1><p>{escape(message)}</p>'
                 '<p class="muted">Закройте это окно и повторите подключение в приложении.</p>')


def continue_page(url):
    """Переход с нашей же страницы: cookie сессии Multica (SameSite=Strict) не уходят в запросе, начатом с чужого сайта."""
    return ('<!doctype html><html lang="ru"><head><meta charset="utf-8">'
            f'<meta http-equiv="refresh" content="0;url={escape(url)}"><meta name="robots" content="noindex">'
            f'<title>Multica</title></head><body><p><a href="{escape(url)}">Продолжить</a></p></body></html>')
