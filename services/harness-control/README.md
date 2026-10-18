# harness-control

Единая точка эксплуатации обвязки агентов: **inspect → validate → deploy → health → rollback** для компонентов из
политики, которую задаёт оператор. Агент не получает общий root: оператор один раз ставит фиксированный привилегированный
вход, дальше агент сам проверяет, выкатывает и откатывает разрешённые версии.

Первый этап: сторож конвейера вместе с полосой провайдеров (`multica-conveyor`) и тестовый `harness-canary`.
Не входят: daemon и backend платформы (`multica-agents`, `multica-*` — всегда `forbidden_component`), самообновление
harness-control, stand, пульт, guard'ы, MCP и навыки, бэкапы — они идут следующими стадиями.

## Устройство

```
агент ── harness-control (CLI) ─┐
агент ── harness-control-mcp ───┴─ sudo -n /usr/local/sbin/harness-priv <глагол> … --json
                                          │  root, разбор аргументов по таблице глаголов (commands.py)
                                          ▼
                                   harness_control.core.Harness   ← единственный владелец поведения
                                          │  операция пишется в ops.db и уходит в transient-юнит
                                          ▼
                                   systemd-run --unit=harness-op-<id> … runner <id>
```

- CLI и MCP — тонкие адаптеры: оба зовут `client.call` и печатают тот же JSON. Таблица глаголов (`commands.py`) — один
  источник для разбора аргументов, argv MCP и схем инструментов.
- Операция живёт в своём юните и не зависит ни от рана агента, ни от обрыва MCP: `op <id>` и `log <id>` работают после.
- Python 3.12, только stdlib. Тесты: `python3 -I -m unittest discover -s services/harness-control/tests -q`.

## Глаголы

| глагол | аргументы | ответ |
|---|---|---|
| `inspect [component]` | — | версия (digest, commit, когда и кем), дрейф (фактические хэши против записанных), юниты, последняя операция и причина, разрешённые операции, зависимости, health. Без секретов |
| `validate <component> <sha40>` | `--key`, `--reason` | `{operation_id, status: "queued"}` |
| `deploy <component> --validation <op> --digest sha256:<64>` | `--key`, `--reason` | `{operation_id, status}` |
| `rollback <component> [--to baseline\|<digest>]` | `--reason` | `{operation_id, status}` |
| `op <id>` / `log <id> [--tail N]` / `ops [component]` | — | состояние и полный лог операции |

Статусы: `queued → running → validated | failed`; для deploy `staged → switching → health → done | rolled_back | degraded`;
`interrupted` — прервана и доведена `recover`.

Ошибки: `{error, reason, missing}`, где `missing` называет недостающую роль или действие оператора; у отказа проверки
добавляется `primary_reason` (`check`, `exit_code`, `signal`, `timeout`, `oom_kill`, `result`). Коды:
`unknown_component`, `forbidden_component`, `verb_not_allowed`, `validation_not_found`, `validation_failed`,
`digest_mismatch`, `artifact_tampered`, `policy_changed`, `ref_not_allowed`, `busy`, `locked_degraded`,
`unsafe_target`, `tests_decreased`, `not_installed`; служебные: `bad_request`, `idempotency_conflict`,
`operation_not_found`, `release_not_found`, `internal`.

Идемпотентность: ключ `(глагол, компонент, key)`. Повтор запроса с тем же `--key` возвращает ту же операцию и не
запускает вторую; тот же ключ с другим запросом — `idempotency_conflict`. Ключ по умолчанию: sha для validate,
`validation:digest` для deploy. Неудавшаяся (`failed`) или прерванная (`interrupted`) операция ключ освобождает.

## Модель полномочий

- **Root-вход** `harness-priv` (sudoers `NOPASSWD`, только пользователю `agents`, только перечисленные глаголы;
  административные `adopt-baseline`, `recover`, `run-op` агенту недоступны ни по sudoers, ни в коде).
- **Аргументы** проверяются регулярками; свободный текст — только `reason` (до 500 символов), он сохраняется и никогда не
  исполняется. Всё, что запускается, — списки аргументов, shell не используется.
- **Политика** `/etc/harness-control/policy.d/<компонент>.json` (root 0644) и каталог доверенных проверок
  `/usr/local/lib/harness-control/checks/<компонент>/` вне кандидата. `policy_version` = sha256(политика + checks +
  версия harness). Правка в кандидате ни на что не влияет; поменять политику может только оператор переустановкой пакета.
- **Validate**: root берёт коммит из публичного репо в своё зеркало (без ключей агента), `git archive <sha>:<путь>`
  даёт канонический tar, его sha256 — digest артефакта (`artifacts/<digest>.tar`, 0400). Проверки идут в transient-юните
  `systemd-run` с фиксированным набором свойств: `DynamicUser`, `PrivateNetwork`, `ProtectSystem=strict`,
  `ProtectHome`, `InaccessiblePaths` на данные harness и sudoers, `MemoryMax`, `TasksMax`, `RuntimeMaxSec`; кандидат и
  checks примонтированы только на чтение, окружение пустое, `PATH` из политики. Глобальный лимит параллельных
  validate — `max_parallel_validate` в `/etc/harness-control/harness.json` (по умолчанию 1).
- **Обязательные проверки сторожа**: контракт `--capabilities`, совместимость `state.json`/`controls.json`, smoke
  `subs-pick` на `control_state.py` кандидата (его импортирует старт каждого рана claude/codex-reserve), затем собственные
  тесты кандидата. Число тестов не меньше, чем у последней проверенной версии и порога `min` политики
  (`tests_decreased`).
- **Deploy** проверяет: компонент в политике, validate успешен, digest и `policy_version` совпадают, хэш tar
  пересчитан, коммит достижим из `origin/main` (если не отключено оператором), компонент не в `degraded`. Всё это
  повторяется под flock компонента перед записью. Затем: распаковка в `releases/<компонент>/<digest>/`; таймеры
  останавливаются, идущий тик → `busy` (тик не прерывается); для каждой цели `dst.tmp-<op>` + fsync + rename через dirfd с
  `O_NOFOLLOW`, родители — владелец root, без записи другим, иначе `unsafe_target`, ничего не изменив; перезапуск юнитов
  из политики (только если изменились их файлы); таймеры включаются по `capabilities` артефакта — например,
  `multica-provider.timer` включается, если сторож объявил полосу `providers`, и выключается при откате на baseline.
- **Health** ждёт следующий плановый проход таймера и сам тик не запускает: юнит запущен после активации и закончил с
  `Result=success`; `tick` в статус-файле новее активации и `errors` пуст; пульт отвечает; вспомогательные проверки
  проходят. Окно — `health.timeout` политики (сторож: 600 с; тик с приёмкой может идти до часа — на такой тик окно не
  рассчитано, deploy в это время отклоняется как `busy`).
- **Откат**: при провале health — ровно один автооткат на предыдущий релиз (`rolled_back`). Если после него health
  тоже не прошёл — `degraded`: компонент заблокирован (`locked_degraded`), повторов нет, выход — явный `rollback`.
  `rollback` без `--to` возвращает последний проверенный релиз, кроме текущего; для `degraded` компонента — повторно
  применяет текущий. `--to baseline` возвращает файлы, найденные на сервере при установке harness.
- **Восстановление**: перед первой заменой на диск пишется журнал `switch.json` с копиями прежних файлов.
  `harness-control-recover.service` при загрузке (и `harness-priv recover`) возвращает прерванные операции к
  полному прежнему набору файлов, перезапускает юниты и ставит `interrupted` с записью в журнале операции. Работающий
  runner `recover` не трогает.
- **Аудит**: `audit.jsonl` и syslog (`harness-control`): `SUDO_USER`, `MULTICA_AGENT_NAME`, `MULTICA_TASK_ID`
  (sudoers `env_keep`), reason, глагол, digest, итог. Атрибуция внутри uid `agents` декларативная — так же, как у
  stand: env может подменить любой процесс agents.
- **Инвариант**: цели политики никогда не исполняются от root. Сторож и `control_state.py` работают от `agents`, canary — от
  `DynamicUser`; поэтому выкладка не повышает привилегии. Не добавляйте в политику цели, которые запускает root.

## Условие безопасности

`validate` выполняет код кандидата в песочнице, но не доказывает его честность: кандидат пишет и сами тесты, и их вывод.
Реальный барьер выкладки — `require_ref`: коммит должен быть достижим из `origin/main`. Поэтому **ветка `main` монорепо
должна быть защищена от прямой записи ключом агентов** (PR и слияние человеком), иначе агент с доступом к `main` может
выложить любой код в разрешённые цели. Привилегии выкладка при этом не повышает: цели исполняются от `agents` или
`DynamicUser`, никогда от root. Для `harness-canary` `require_ref` отключён намеренно (нужны сбойные версии вне `main`),
поэтому его юнит ограничен (`PrivateNetwork`, пустой `CapabilityBoundingSet`, лимиты).

Порог числа тестов поднимают только коммиты из `require_ref`: счётчик печатает сам кандидат.

## Политика

Строгая схема (неизвестные ключи отвергаются), см. `policy.d/*.json`, `harness_control/policy.py`. Ключи: `source`
(`repo`, `path`, `require_ref`), `targets[{src,dst,mode}]`, `timers`, `busy_units`, `restart_units[{unit,when_changed}]`,
`required_units`, `lanes`, `baseline_capabilities`, `capabilities`, `validate{checks,tests}`, `sandbox`, `health`,
`dependencies`. Новый компонент: политика + каталог `checks/<имя>/` + (если нужен baseline) установка вручную; затем
пакет собирается и ставится оператором заново.

## Установка (оператор, root)

```sh
bash services/harness-control/bootstrap/build-release.sh <коммит>      # tar + SHA256SUMS в ./dist
tar -xzf dist/harness-control-<версия>-<коммит>.tar.gz
bash harness-control-<версия>-<коммит>/bootstrap/install.sh --check    # план и SHA256, без root, ничего не меняет
sudo bash harness-control-<версия>-<коммит>/bootstrap/install.sh       # установка; обновление — с --upgrade
```

Установщик записывает текущие файлы сторожа как релиз `baseline` (`source: installed`), сам сторож не меняет,
`multica-provider.timer` ставит выключенным, sudoers — последним (после `visudo -c`).

После установки: `harness-control inspect` от `agents` (сторож в baseline, дрейфа нет); canary: validate → deploy →
health → rollback (версия `…-fail` в `canary/VERSION` проверяет автооткат); регистрация MCP: `multica workspace mcp add
harness-control` (нужен admin workspace) и `multica agent mcp add` для нужных агентов.

Откат установки: `sudo /usr/local/lib/harness-control/uninstall.sh [--restore-baseline]` — первым удаляется sudoers,
состояние и политика уходят в `/var/backups/harness-control-<время>`.

## Эксплуатация

- Что смотреть при сбое: `harness-control op <id>` и `log <id>` (полный лог без секретов, первичная причина),
  `journalctl -u harness-op-<id>`, `journalctl -t harness-control`, `/var/lib/harness-control/audit.jsonl`.
- `busy` — идёт тик сторожа или другая операция компонента; повторить позже.
- `degraded` — зайти на хост, разобраться, выполнить `harness-control rollback <компонент> [--to baseline]`.
- Артефакты (`artifacts/`, до 8 МБ каждый) и зеркало репо растут: очистки пока нет, смотреть `du -sh /var/lib/harness-control`.
- Требуются для systemd ≥ 247 (`systemctl show --timestamp=unix`).
- Не покрыто тестами из-за отсутствия root: реальный `systemd-run` (разбор вывода `--wait` опирается на формат systemd 255),
  реальные `sudo`/`visudo`-доступ агента и права файлов на хосте. Это проверяется оператором после установки.
