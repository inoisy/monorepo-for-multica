# Сверка действующего кода перед выкладкой

Снимок проверен 18.10.2026. Не заменяйте исходники целиком установленным сторожем: он ещё не содержит
независимую полосу провайдеров, атомарное слияние состояния и защиту/полный лог приёмки из основной ветки.

| Файл | Действующий SHA256 | Дельта относительно основной ветки |
|---|---|---|
| `/usr/local/bin/multica-conveyor` | `210632daabab43ddf1c1f6dbf020b39962f35de89a523d8e21381052b5f2d5aa` | INFRA-классификация, интервал, счётчик и лимит повторов |
| `/usr/local/bin/control_state.py`, `/opt/multica-control/control_state.py` | `616dfa8392676c77d33175cf6c36d9c12b47be067ed46135e8bb51fbc3b63fd9` | `accounts`, `account_card`, нейтральный пример в docstring |

Предыдущий `control_state.py` в `/var/backups/multica-control/20261018-account-cards/` имеет SHA256
`5736e0eddbc7f6fdeb6cbf72a572a18bf096029fa4a1d6449702a89d3f65e851`, совпадающий с baseline harness и основной
веткой до переноса. Обе действующие копии изменены в 09:04:04 UTC; пульт перезапущен в 09:04:05 UTC.
Дельта появилась при обновлении карточек аккаунтов вне harness. Конкретный инициатор из этих данных не установлен.
Действующий `control_panel.py` вызывает новые функции в выдаче подписок и изменении лимитов аккаунта;
выкладка старого модуля сломала бы эти операции. Исходник общего модуля теперь побайтно совпадает с действующим.

INFRA-функции и сигнатуры перенесены из действующего файла. Интеграция сохраняет общий lock с провайдерами,
перечитывает задачу/раны перед повтором и не пишет сырой текст ошибки в журнал. В отличие от прежней интеграции,
queued/running повтор сохраняет число последовательных падений: иначе каждый новый ран обнулял бы лимит.
Схема состояния совместима: `_infra_retry` содержит прежние `at`, `n`, `gave_up`.

# Проверки перед передачей QA

Из корня репозитория:

```sh
python3 -I -m unittest discover -s services/multica-conveyor/tests -q
python3 -I -m unittest discover -s services/harness-control/tests -q
python3 -I services/harness-control/checks/multica-conveyor/contract_smoke.py services/multica-conveyor
python3 -I services/harness-control/checks/multica-conveyor/state_compat.py services/multica-conveyor
python3 -I services/harness-control/checks/multica-conveyor/subs_pick_smoke.py services/multica-conveyor
bash services/harness-control/bootstrap/install.sh --check
```

Тесты не запускают реальные LLM. Новых зависимостей, переменных окружения, HTTP-эндпоинтов и миграций нет.
Регрессии: `test_infra_retry.py`, `test_account_cards.py`, `test_parity.py`. Проверка bootstrap сравнивает состояние
до/после `--check` и работает также на машине с уже установленным harness.

# Живая проверка QA

1. После review и слияния PR зафиксировать полный SHA из `main`. Повторно сверить действующие хэши и изменения
   после снимка выше. При новой дельте остановить deploy и сохранить её в исходниках через review.
2. `harness-control inspect multica-conveyor`: проверить policy, health, текущую версию и drift. Исходный дрейф
   общего модуля разобран выше; новые несовпадения требуют отдельного разбора.
3. `harness-control validate multica-conveyor <sha40> --key <sha40>:main` → дождаться `validated` через `op`.
   Проверить полный лог, `result.commit`, `reachable=true`, `policy_version`, тесты и capabilities.
   Validate из ветки до merge не даёт разрешения на deploy: его `reachable=false` не меняется задним числом.
4. `harness-control deploy multica-conveyor --validation <operation_id> --digest <result.digest>`.
   Digest брать из проверки. Сохранить оба operation_id, результат health и `log`.
5. Дождаться `done`: следующий плановый тик epics и providers, свежие status-файлы без ошибок, HTTP пульта,
   импорт общего модуля и subs-pick. `multica-provider.timer` должен включиться по capabilities без ручного
   `systemctl enable`. `inspect` должен показать commit/digest кандидата и чистый drift.
6. При провале health проверить штатный автооткат (`rolled_back`, `rollback_health`) или выполнить
   `harness-control rollback multica-conveyor` и дождаться health. Baseline содержит старый общий модуль:
   он безопасен для старого сторожа, но несовместим с новыми карточками текущего пульта; не считать его
   полноценным восстановлением пульта без отдельной проверки карточек. Не выполнять ручную замену root-файлов.
7. Canary validate/deploy/rollback/auto-rollback уже подтверждены; повторять их только при изменении этого пути.
   Расписание канарейки выключено (см. README, «Harness-canary: ручная проверка»): для deploy-проверки таймер включает оператор.

Для проверки исправленного адаптера без замены root-кода запускать `services/harness-control/bin/harness-control`
и `services/harness-control/bin/harness-control-mcp` из проверенного SHA. Они вызывают тот же установленный
`harness-priv`, с прежними правами. Проверить `harness_op` успешной операции: `error:null`, `isError:false`, CLI
выходит с 0; для неизвестной операции — заполненная ошибка, `isError:true`, CLI выходит с 1. JSON должен совпадать.
Протокол initialize/tools/list/tools/call проверяется по stdio.

Это проверка кандидата адаптера. Установленный `/usr/local/bin/harness-control-mcp` продолжает использовать
root-owned пакет до его обновления. В текущей политике разрешены только `multica-conveyor` и `harness-canary`;
самообновление harness отсутствует. Не расширять политику, не подменять canary и не выдавать себе root ради обновления.
Не объявлять установленный MCP исправленным по результату проверки адаптера из исходников.

# Остаток реестра

Первый путь конвейера/провайдеров не означает готовность всей обвязки. После его QA и review остаются отдельные
адаптеры: stand и сборки; пульт/mconv и реестр подписок; runtime-обёртки и квоты; guard'ы и старые фоновые таймеры;
MCP/навыки/конфигурация агентов; агрегированные логи/health и проверяемый backup/restore. Daemon/backend платформы
остаются только в инвентаризации до проверки drain, сохранения активной работы и отдельной политики.
