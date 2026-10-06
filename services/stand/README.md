# stand

Стенды и артефакты для агентов multica на сервере агентов.

- **Стенд** — ветка репозитория на `https://<имя>.stand.yakutov.com`
  (виды `node`, `static`, `docker`, `compose`). Живёт 48 ч или до закрытия задачи.
- **Артефакт** — статическая страница без сборки и контейнера (аналог artifacts
  в Claude): `.html`, `.md`, `.mmd`, `.svg`, `.jsx`/`.tsx` или каталог с `index.html`.
  Адрес `https://art-<имя>-<суффикс>.stand.yakutov.com`, живёт `--ttl` дней (90).

## Состав

| файл | на сервере | что делает |
|---|---|---|
| `stand` | `/usr/local/bin/stand` | CLI: `up`/`down`/`list`/`status`/`exec`, `art publish`/`list`/`rm`. Агенты зовут через `sudo` |
| `stand-mcp` | `/usr/local/bin/stand-mcp` | MCP-сервер `stand` для агентов — обёртка над `sudo stand` |
| `stand-router.py` | `/opt/stand/stand-router.py` | `forward_auth` для Caddy: имя хоста → порт стенда или сервис артефактов |
| `static-server.mjs` | `/opt/stand/static-server.mjs` | раздаёт статику стендов и артефактов (`--hosts` — режим артефактов) |
| `artifact-shells/*.html` | `/opt/stand/artifact-shells/` | оболочки, в которые `stand art publish` заворачивает markdown / mermaid / svg / jsx |
| `systemd/*` | `/etc/systemd/system/` | `stand-router` (:8093), `stand-artifacts` (:8094), таймеры `stand-gc` и `stand-follow` |
| `SKILL.md` | скилл multica `stand` | инструкция агентам |

## Что не здесь

Ограничения агентов и конфиг сервера в репо не лежат и правятся только
владельцем сервера:

- `/etc/sudoers.d/stand` — что агентам можно через `sudo`;
- `/etc/stand/repos.conf` — какие репозитории можно ставить на стенды;
- `/opt/stand/compose-gen.py` — белый список ключей compose;
- `/etc/stand/*.env`, `/etc/stand/secrets/` — окружение и секреты стендов;
- Caddyfile.

## Выкатка

Из этого каталога сервер не обновляется. Правка — PR сюда; после ревью
владелец сервера ставит файлы руками:

```sh
install -o root -g root -m 755 stand stand-mcp /usr/local/bin/
install -o root -g root -m 644 stand-router.py static-server.mjs /opt/stand/
install -o root -g root -m 644 artifact-shells/*.html /opt/stand/artifact-shells/
systemctl restart stand-router stand-artifacts
```

Проверка до выкатки: `bash -n stand`, `python3 -m py_compile stand-router.py stand-mcp`,
`node --check static-server.mjs`.
