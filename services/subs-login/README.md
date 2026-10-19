# subs-login — вход в подписки из интерфейса

Этап 5 ТЗ моделей (раздел 10): владелец workspace перелогинивает аккаунт подписки со страницы «Подписки» без ssh.

- Codex — `codex login --device-auth` во временном `CODEX_HOME`; страница показывает ссылку и код, после входа
  `auth.json` учётки подменяется атомарно (права 600).
- Claude — вставка токена из `claude setup-token`; ключ API — вставка нового ключа (для провайдеров с проверкой квоты
  ключ сначала проверяется).
- Статус входа (`logged_in`, `revoked`, `never`, `check_failed`, `unchecked`) видят все участники workspace; входить
  может только owner. Роль и сессию помощник проверяет по API multica той же cookie, что пришла в запросе.
- Брошенный, отменённый или неудачный вход рабочий файл не трогает; незавершённый убивается через `login_timeout`
  (15 минут). Один вход на аккаунт одновременно — второй запрос получает то же окно.
- Журнал `~/.local/state/subs-login/journal.jsonl`: кто, когда, какой аккаунт, результат. Значения токенов и ключей
  не пишутся ни в журнал, ни в ответы.

Аккаунты и пути учёток берутся из выгрузки таблиц «Подписок» (`subscriptions.json` пульта: строки с `auth` из
`codex_auth`, `claude_oauth`, `api_key` и заполненным `credential`), а не из запроса.

## Установка (root)

```sh
install -m 0755 services/subs-login/subs-login /usr/local/bin/subs-login
install -m 0644 services/subs-login/systemd/subs-login.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now subs-login.service
```

Конфиг `/etc/subs-login.json` необязателен (ключи — в docstring скрипта). Помощник слушает только `127.0.0.1:8101` (8099 занят `takes-site`, 8100 — `multica-pages`);
наружу — через Caddy того же сайта, что Multica, чтобы cookie сессии доходила:

```caddy
handle_path /subs-login/* {
	reverse_proxy 127.0.0.1:8101
}
```

## API

| Запрос | Кто | Что |
| --- | --- | --- |
| `GET /api/accounts?ws=<slug>` | участник | аккаунты, статус входа, идущий вход, `can_login` |
| `GET /api/login?ws=<slug>&account=<id>` | участник | состояние входа: `waiting`, `done`, `failed`, `cancelled`, `expired` |
| `POST /api/login?ws=<slug>` `{"account", "action": "start"}` | owner | device-auth Codex; ответ — ссылка и код |
| `POST /api/login?ws=<slug>` `{"account", "action": "cancel"}` | owner | отменить вход |
| `POST /api/login?ws=<slug>` `{"account", "action": "secret", "value"}` | owner | токен Claude или ключ API |

POST требует заголовок `X-Subs-Login-Request: 1` (защита от отправки формы с чужого сайта).

## Проверка

`python3 -m unittest discover -s services/subs-login/tests` — поддельный `codex`: успешный вход подменяет файл;
отмена, таймаут, неверный код — файл байт в байт прежний; не owner — 403; второй вход — то же окно; в журнале и
ответах нет значений. Настоящие `codex login --device-auth` и `claude setup-token` проверяются только на сервере.
