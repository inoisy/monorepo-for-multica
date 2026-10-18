"""Health после выкладки: ждём следующий плановый проход таймера, лишний тик не запускаем.

Принудительный запуск сторожа сам выполняет переключения моделей и повторы, поэтому проверка пассивная:
юнит запущен после активации и закончил с Result=success, статус-файл свежее активации и без ошибок,
пульт отвечает, вспомогательные проверки проходят.
"""
import datetime as dt
import json
import time
import urllib.error
import urllib.request

from . import safefile
from .redact import redact

PASS, FAIL, PENDING = 'pass', 'fail', 'pending'
ACTIVE_STATES = {'active', 'activating', 'deactivating', 'reloading'}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def http_status(url, timeout=5):
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(url, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, OSError, ValueError):
        return None


def parse_tick(text):
    """tick сторожа — UTC «2026-10-18 06:34:01»; принимается и ISO с поясом."""
    value = dt.datetime.fromisoformat(text.replace('Z', '+00:00'))
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.timestamp()


class Health:
    def __init__(self, paths, system, sandbox_check, clock=time.time, sleep=time.sleep, http=http_status):
        # sandbox_check(argv) → (ok, detail): вспомогательные команды идут в песочнице, не от root
        self.paths, self.system, self.sandbox_check = paths, system, sandbox_check
        self.clock, self.sleep, self.http = clock, sleep, http

    def wait(self, policy, lanes, since, timeout=None):
        spec = policy.health
        timeout = spec['timeout'] if timeout is None else timeout
        deadline = self.clock() + timeout
        started = self.clock()
        while True:
            checks = self.evaluate(policy, lanes, since)
            states = {c['state'] for c in checks}
            if FAIL in states:
                return self._result(False, checks, started)
            if states <= {PASS}:
                return self._result(True, checks, started)
            if self.clock() >= deadline:
                for c in checks:
                    if c['state'] == PENDING:
                        c.update(state=FAIL, detail=f'не дождались за {timeout} с: {c["detail"]}')
                return self._result(False, checks, started)
            self.sleep(spec['poll'])

    def _result(self, ok, checks, started):
        return {'ok': ok, 'waited': round(self.clock() - started, 1),
                'checks': [{'name': c['name'], 'ok': c['state'] == PASS, 'detail': c['detail']} for c in checks]}

    def evaluate(self, policy, lanes, since):
        spec = policy.health
        active = lambda item: item.get('lane') is None or item['lane'] in lanes
        out = []
        for u in filter(active, spec['units']):
            out += self._unit(u, since)
        for s in filter(active, spec['status_files']):
            out.append(self._status_file(s, since))
        for h in spec['http']:
            out.append(self._http(h))
        for c in spec['commands']:
            ok, detail = self.sandbox_check(c['argv'])
            out.append({'name': c['name'], 'state': PASS if ok else FAIL, 'detail': detail})
        return out

    def _unit(self, item, since):
        out = []
        if item.get('timer'):
            props = self.system.unit_props(item['timer'], ['ActiveState'])
            ok = props['ActiveState'] == 'active'
            out.append({'name': f'таймер {item["timer"]}', 'state': PASS if ok else FAIL,
                        'detail': f'ActiveState={props["ActiveState"]}'})
        unit = item['unit']
        props = self.system.unit_props(unit, ['ActiveState', 'Result', 'ExecMainStartTimestamp', 'ExecMainStatus'])
        started = props.get('ExecMainStartTimestamp')
        if started is None or started <= int(since):
            state, detail = PENDING, 'ждём следующий плановый запуск'
        elif props['ActiveState'] in ACTIVE_STATES:
            state, detail = PENDING, 'запуск после активации идёт'
        elif props['Result'] == 'success':
            state, detail = PASS, 'запуск после активации завершился успешно'
        else:
            state, detail = FAIL, f'Result={props["Result"]}, код {props.get("ExecMainStatus")}'
        out.append({'name': f'запуск {unit}', 'state': state, 'detail': detail})
        return out

    def _status_file(self, item, since):
        name = f'статус {item["path"].rsplit("/", 1)[-1]}'
        try:
            return self._read_status(item, since, name)
        except Exception as e:  # файл принадлежит агенту: любой неожиданный формат — отказ проверки, а не сбой harness
            return {'name': name, 'state': PENDING, 'detail': f'статус не разобран: {type(e).__name__}'}

    def _read_status(self, item, since, name):
        try:
            data = json.loads(safefile.read_text(self.paths.host(item['path'])))
            tick = parse_tick(data[item['tick_key']])
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
            return {'name': name, 'state': PENDING, 'detail': f'статус не прочитан: {type(e).__name__}'}
        if tick <= int(since):
            return {'name': name, 'state': PENDING, 'detail': 'tick старше активации'}
        errors = data.get(item.get('errors_key') or 'errors') or []
        if errors:
            first = str(errors[0] if isinstance(errors, list) else errors).strip().splitlines()
            return {'name': name, 'state': FAIL, 'detail': redact(first[0] if first else 'errors не пуст')[:300]}
        kinds = set(item.get('bad_event_kinds') or [])
        events = data.get(item.get('events_key') or 'events') or []
        for ev in events if isinstance(events, list) else []:
            try:
                stamp = parse_tick(ev['t'])
            except (KeyError, ValueError, TypeError, AttributeError):
                continue
            if isinstance(ev, dict) and ev.get('kind') in kinds and stamp > int(since):
                return {'name': name, 'state': FAIL, 'detail': redact(str(ev.get('text', ''))[:300])}
        return {'name': name, 'state': PASS, 'detail': 'tick свежий, ошибок нет'}

    def _http(self, item):
        code = self.http(item['url'])
        if code is None:
            return {'name': f'HTTP {item["url"]}', 'state': PENDING, 'detail': 'нет ответа'}
        ok = code in item['expect']
        return {'name': f'HTTP {item["url"]}', 'state': PASS if ok else FAIL, 'detail': f'код {code}'}
