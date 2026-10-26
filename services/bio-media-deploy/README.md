# bio-media-api: штатная выкладка CLI

Код — `inoisy/bio-za-minutu`, рабочая копия `/home/agents/bio-course`.
`bio-git-sync.service` уже синхронизирует её с `origin/main`.
Брокер — CLI, вызываемый через существующее разрешение sudo, а не HTTP-сервер.
Его health: `bio-media-api --check` (наличие root-ключа, без платных запросов)
и `broker_guard.py` (ограничения API, моделей, путей, стоимости).

Выбран путь `bio-git-sync` → одобренный root-снимок → `bio-media-deploy.service`.
Ключ `/etc/openrouter/key`, каталог моделей и правила sudo не меняются.
Сервис не исполняет код из изменяемой агентами рабочей копии. Оператор на воротах
merge фиксирует конкретную ревизию и ставит снимок в root-каталог; повторные
запуски юнита идемпотентны. Таймер, автоматически запускающий новый код от root,
не добавляется. Следующий релиз проходит те же команды оператора.

Команды ниже выполняются **только на воротах merge**, после слияния PR и проверки
выбранного коммита. `$REPO` — root-доверенная копия monorepo-for-multica на
одобренном коммите. Сначала выполнить тесты из синхронизированной копии от agents:

```sh
cd /home/agents/bio-course
git fetch origin main
BIO_SHA=$(git rev-parse origin/main)
git diff --exit-code "$BIO_SHA" -- bio-media-api test_broker.py video-models.json
python3 -IB -m unittest discover -s . -p test_broker.py -v
python3 -I /usr/local/lib/harness-control/checks/bio-media-api/broker_guard.py bio-media-api
```

Сохранить `BIO_SHA` в отчёте и сверить его перед установкой. Оператор root:

```sh
# BIO_SHA — полный SHA из проверки выше, не HEAD другой рабочей копии.
install -d -o root -g root -m 0755 /usr/local/lib/bio-media-deploy /var/lib/bio-media-deploy
install -o root -g root -m 0755 "$REPO/services/bio-media-deploy/install.sh" /usr/local/lib/bio-media-deploy/install.sh
# Сохранить уже установленную доверенную проверку до снятия старого пакета.
install -o root -g root -m 0644 /usr/local/lib/harness-control/checks/bio-media-api/broker_guard.py /usr/local/lib/bio-media-deploy/broker_guard.py
# git — от agents: root не исполняет git в рабочей копии агентов (safe.directory, их .git/config).
runuser -u agents -- git -C /home/agents/bio-course show "$BIO_SHA:bio-media-api" > /var/lib/bio-media-deploy/candidate
chown root:root /var/lib/bio-media-deploy/candidate
chmod 0644 /var/lib/bio-media-deploy/candidate
printf '%s\n' "$BIO_SHA" > /var/lib/bio-media-deploy/source-sha
install -o root -g root -m 0644 "$REPO/services/bio-media-deploy/bio-media-deploy.service" /etc/systemd/system/bio-media-deploy.service
systemctl daemon-reload
systemctl start bio-media-deploy.service
journalctl -u bio-media-deploy.service -n 30 --no-pager
/usr/local/bin/bio-media-api --check
python3 -I /usr/local/lib/bio-media-deploy/broker_guard.py /usr/local/bin/bio-media-api
```

Ожидается `Broker installed; health ok; no paid requests` либо
`Already installed; health ok`. Тесты — 12, `broker-guard: ок`. Ключ не выводится.
Сбой установленного `--check` возвращает прежний файл и завершает юнит ошибкой.
Сбой guard останавливает установку до замены файла.

Ручной откат, если при предыдущем запуске был установлен новый файл:

```sh
install -o root -g root -m 0755 /var/lib/bio-media-deploy/previous /usr/local/bin/bio-media-api.new
mv -f /usr/local/bin/bio-media-api.new /usr/local/bin/bio-media-api
/usr/local/bin/bio-media-api --check
python3 -I /usr/local/lib/bio-media-deploy/broker_guard.py /usr/local/bin/bio-media-api
```

При первом идемпотентном запуске `previous` может отсутствовать: код не менялся.
Пока replacement-health не прошёл, старый механизм не снимать.
