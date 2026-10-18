"""Общий lock пульта и конвейера; квоты не старше 15 минут."""
import contextlib
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import tempfile

ACTIVE = {'queued', 'running', 'dispatched', 'pending', 'preparing'}
DEFAULT_STATE = Path.home() / '.local/state/multica-control/controls.json'


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')


class Store:
    def __init__(self, path=None):
        self.path = Path(path or os.environ.get('MULTICA_CONTROL_STATE', DEFAULT_STATE))

    @contextlib.contextmanager
    def locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.path.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                state = json.loads(self.path.read_text()) if self.path.exists() else {}
                before = json.dumps(state, sort_keys=True)
                yield state
                if json.dumps(state, sort_keys=True) != before:
                    fd, name = tempfile.mkstemp(dir=self.path.parent, prefix='.controls-')
                    try:
                        with os.fdopen(fd, 'w') as out:
                            json.dump(state, out, ensure_ascii=False, indent=2)
                            out.flush()
                            os.fsync(out.fileno())
                        os.replace(name, self.path)
                    finally:
                        if os.path.exists(name): os.unlink(name)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


def quota_rows(cfg):
    """Строки дашборда квот не старше 15 минут; у окон — наш лимит из реестра подписок (`cap`)."""
    try:
        data = json.loads(Path(cfg['usage_json']).read_text())
        updated = dt.datetime.fromisoformat(data['updated'].replace('Z', '+00:00'))
        age = (dt.datetime.now(dt.timezone.utc) - updated).total_seconds()
        tbl = current_tables(cfg)
        RUNTIME_ROWS.clear()
        RUNTIME_ROWS.update(runtime_rows(tbl))
        return apply_caps(data.get('rows', []), row_caps(cfg), tbl['windows']) if 0 <= age <= 900 else []
    except (OSError, ValueError, KeyError, TypeError):
        return []


# Подписки — три таблицы: `items` (подписки), `runtimes` (какие подписки за runtime и порядок трат),
# `windows` (окна квот и как их узнать в дашборде). Начальные строки — `subscriptions` конфига,
# правки со страницы «Подписки» — `sub_tables` в controls.json, лимиты и резерв — `subscriptions` там же.
# Пульт и сторож выгружают итог в `subscriptions.file` (и копию `.last`): его читают обёртки, `ai`,
# `subs-pick` и сами пульт со сторожем. В коде нет ни подписок, ни runtime, ни окон.
DEFAULT_SUBS_FILE = Path.home() / '.local/state/multica-control/subscriptions.json'
TABLE_KEYS = {'items': 'id', 'runtimes': 'name', 'windows': 'key'}
ORDERS = ('first', 'balanced')


def tables(cfg, settings):
    """Таблицы из конфига, поверх — правки со страницы: строка целиком или None (удалена)."""
    seed = cfg.get('subscriptions', {})
    edits = settings.get('sub_tables', {})
    out = {}
    for table, key in TABLE_KEYS.items():
        rows = {r[key]: dict(r) for r in seed.get(table, []) if r.get(key)}
        for name, row in (edits.get(table) or {}).items():
            if row is None:
                rows.pop(name, None)
            else:
                rows[name] = {**row, key: name}
        out[table] = list(rows.values())
    return out


def read_subs_file(cfg):
    """Выгрузка пульта; нет или битая — последняя удачная копия `.last`; нет и её — None."""
    path = subs_file(cfg)
    for candidate in (path, last_copy(path)):
        try:
            return json.loads(candidate.read_text())
        except (OSError, ValueError):
            continue
    return None


def current_tables(cfg):
    """Таблицы, по которым сейчас работают обёртки: из выгрузки, без неё — из конфига."""
    data = read_subs_file(cfg) or {}
    tbl = data.get('tables')
    return tbl if isinstance(tbl, dict) and all(k in tbl for k in TABLE_KEYS) else tables(cfg, {})


def window_names(tbl):
    return {w['key']: w.get('title') or w['key'] for w in tbl['windows']}


def window_key(label, windows):
    """Ключ окна по подписи дашборда — по `match` таблицы окон (начало подписи, без регистра).
    Денежные окна («доп. расход», OpenRouter) в таблицу не входят — None: резерв к ним не относится."""
    text = (label or '').strip().lower()
    for w in windows:
        if any(text.startswith(m.strip().lower()) for m in w.get('match') or [] if m.strip()):
            return w['key']
    return None


def runtime_rows(tbl):
    """Строки дашборда квот по имени runtime — через его подписки."""
    rows = {i['id']: i.get('quota_row') for i in tbl['items']}
    return {r['name']: [rows[s] for s in r.get('subscriptions') or [] if rows.get(s)] for r in tbl['runtimes']}


# Как обёртка получает учётку подписки — механизм, а не данные: какие подписки чем пользуются, решает таблица.
AUTHS = ('none', 'claude_login', 'claude_oauth', 'codex_auth', 'api_key')


def usage_by_subscription(tbl, rows):
    """Окна дашборда по каждой подписке: загрузка, наш лимит, сброс; без строки дашборда — пусто."""
    out = {}
    for item in tbl['items']:
        row = next((r for r in rows if item.get('quota_row') and row_key(r.get('name', ''), [item['quota_row']])), {})
        out[item['id']] = {
            'usage': [{'key': window_key(w.get('label'), tbl['windows']), 'label': w.get('label'), 'used': w.get('used'),
                       'cap': w.get('cap'), 'reset': w.get('reset'), 'blocked': window_blocked(w)}
                      for w in row.get('windows') or []],
            'error': row.get('error')}
    return out


def subscription_available(usage):
    """True — все окна ниже нашего лимита; False — хоть одно упёрлось; None — данных нет."""
    used = [w for w in usage.get('usage', []) if isinstance(w.get('used'), (int, float))]
    if any(w['blocked'] for w in used): return False
    return True if used and not usage.get('error') else None


def runtime_subscriptions(tbl):
    """Подписки по имени runtime в порядке трат."""
    return {r['name']: list(r.get('subscriptions') or []) for r in tbl['runtimes']}


def subs_file(cfg):
    return Path(cfg.get('subscriptions', {}).get('file') or os.environ.get('MULTICA_SUBSCRIPTIONS') or DEFAULT_SUBS_FILE)


def last_copy(path):
    return path.with_name(path.stem + '.last' + path.suffix)


def effective_caps(caps, reserve, windows):
    """Итоговый лимит окна: меньшее из лимита окна и 100 − резерв (решение 16.10.2026)."""
    out = {}
    for key in windows:
        cap = min(caps.get(key, 100), 100 - (reserve or 0))
        if cap < 100:
            out[key] = cap
    return out


def subscriptions(cfg, settings):
    """Реестр подписок с правками и итоговыми лимитами окон."""
    saved = settings.get('subscriptions', {})
    out = []
    for item in tables(cfg, settings)['items']:
        mine = saved.get(item['id'], {})
        windows = item.get('windows') or list((item.get('caps') or {}).keys())
        caps = {**(item.get('caps') or {}), **(mine.get('caps') or {})}
        reserve = mine.get('reserve', item.get('reserve', 0))
        out.append({**item, 'windows': windows, 'caps': {k: caps.get(k, 100) for k in windows}, 'reserve': reserve,
                    'effective': effective_caps(caps, reserve, windows),
                    'changed_at': mine.get('at'), 'changed_by': mine.get('by')})
    return out


def export_subscriptions(cfg, settings):
    """Атомарно выгружает итоговые лимиты для обёрток; пишет файл, только если он изменился."""
    subs = subscriptions(cfg, settings)
    tbl = tables(cfg, settings)
    data = {'subscriptions': {s['id']: {'caps': s['effective'], 'reserve': s['reserve'], 'quota_row': s.get('quota_row')}
                              for s in subs}, 'rows': caps_by_row(subs), 'tables': tbl,
            'probe': cfg.get('subscriptions', {}).get('probe', {})}
    path = subs_file(cfg)
    try:
        old = json.loads(path.read_text())
        if {k: old.get(k) for k in data} == data:
            return path
    except (OSError, ValueError, AttributeError):
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps({'updated': now(), **data}, ensure_ascii=False, indent=1)
    for target in (path, last_copy(path)):
        fd, name = tempfile.mkstemp(dir=path.parent, prefix='.subscriptions-')
        try:
            with os.fdopen(fd, 'w') as out:
                out.write(text)
            os.chmod(name, 0o644)
            os.replace(name, target)
        finally:
            if os.path.exists(name): os.unlink(name)
    return path


def accounts(subs):
    """Подписки, сгруппированные по аккаунту: у ключей одного аккаунта (claude-main и claude-max) общая строка
    дашборда — загрузка и лимиты у них одни. Без строки дашборда подписка — сама себе аккаунт. Порядок — по таблице."""
    groups = {}
    for sub in subs:
        groups.setdefault((sub.get('provider'), sub.get('quota_row')) if sub.get('quota_row') else sub['id'], []).append(sub)
    return list(groups.values())


def account_card(group):
    """Одна карточка на аккаунт: первая подписка — главная (её id, название, резерв), окна и runtime — общие."""
    main = group[0]
    windows = list(dict.fromkeys(w for s in group for w in s['windows']))
    caps = {k: next(s['caps'][k] for s in group if k in s['caps']) for k in windows}
    card = {**main, 'windows': windows, 'caps': caps, 'effective': effective_caps(caps, main['reserve'], windows),
            'keys': [s['id'] for s in group]}
    if len(group) > 1:
        card['credential'] = ' · '.join(s['credential'] for s in group if s.get('credential'))
    return card


def caps_by_row(subs):
    """Строка дашборда может стоять за несколькими подписками (claude-main и claude-max) — берём меньший лимит."""
    rows = {}
    for sub in subs:
        if sub.get('quota_row'):
            mine = rows.setdefault(sub['quota_row'], {})
            for key, cap in sub['effective'].items():
                mine[key] = min(cap, mine.get(key, 100))
    return rows


def row_caps(cfg):
    """Лимиты окон по строкам дашборда: из выгруженного файла (или `.last`), без него — из реестра конфига."""
    rows = (read_subs_file(cfg) or {}).get('rows')
    return rows if isinstance(rows, dict) else caps_by_row(subscriptions(cfg, {}))


def row_key(name, keys):
    """Строка реестра для строки дашборда: точное имя или имя с тарифом в скобках («Claude · Евгений (Max 5x)»)."""
    if name in keys:
        return name
    return next((k for k in keys if name.startswith(k + ' (')), None)


def apply_caps(rows, caps, windows):
    """Окнам из таблицы окон — наш лимит из реестра; остальные окна сохраняют `cap` дашборда."""
    out = []
    for row in rows:
        mine = caps.get(row_key(row.get('name', ''), caps))
        if mine is None:
            out.append(row)
            continue
        capped = []
        for w in row.get('windows') or []:
            key = window_key(w.get('label'), windows)
            if key:
                w = {k: v for k, v in w.items() if k != 'cap'}
                if key in mine:
                    w['cap'] = mine[key]
            capped.append(w)
        out.append({**row, 'windows': capped})
    return out


MSK = dt.timezone(dt.timedelta(hours=3))


# Имя runtime → строки дашборда его подписок; обновляется из таблиц при каждом чтении квот.
RUNTIME_ROWS = {}


def accounts_for(runtime, rows):
    """Строки дашборда квот подписок runtime (таблица runtime); None — runtime в таблице нет, данных нет."""
    names = RUNTIME_ROWS.get(runtime)
    if not names:
        return None
    return [r for r in rows if row_key(r.get('name', ''), names)]


def window_blocked(w):
    return isinstance(w.get('used'), (int, float)) and w['used'] >= (w.get('cap') if w.get('cap') is not None else 100)


def parse_reset(text, now):
    """«16.10 22:49» по МСК без года → UTC; через Новый год — следующий год."""
    try:
        t = dt.datetime.strptime(f'{text} {now.year}', '%d.%m %H:%M %Y').replace(tzinfo=MSK)
    except (TypeError, ValueError):
        return None
    if t < now - dt.timedelta(days=180):
        t = t.replace(year=now.year + 1)
    return t.astimezone(dt.timezone.utc)


def reset_at(runtime, rows, now):
    """Когда у runtime освободится хоть одна подписка: у каждой — самое позднее из упёршихся окон, берём раннюю."""
    accounts = accounts_for(runtime, rows)
    times = []
    for row in accounts or []:
        blocked = [parse_reset(w.get('reset'), now) for w in row.get('windows') or [] if window_blocked(w)]
        if not blocked:
            return now
        if all(blocked):
            times.append(max(blocked))
    return min(times) if times else None


def available(runtime, rows):
    """True/False/None: неизвестные данные не запрещают профиль."""
    accounts = accounts_for(runtime, rows)
    if not accounts: return None
    statuses = []
    for row in accounts:
        windows = row.get('windows') or []
        used = [w for w in windows if isinstance(w.get('used'), (int, float))]
        blocked = any(window_blocked(w) for w in used)
        statuses.append(False if blocked else (None if row.get('error') or not used else True))
    if True in statuses: return True
    return None if None in statuses else False


def availability(cfg, names=None):
    names = all_runtime_names(cfg) if names is None else names
    rows = quota_rows(cfg)
    return {rid: available(name, rows) for rid, name in names.items()}


def workspaces(cfg):
    """Workspace с фоллбеками: `providers.workspaces`, без него — один `providers.workspace`."""
    pv = cfg.get('providers', {})
    return pv.get('workspaces') or [{'id': pv.get('workspace'), 'slug': pv.get('workspace_slug', 'stt'),
                                     'kinds': {}, 'runtime_names': pv.get('runtime_names', {})}]


def all_runtime_names(cfg):
    names = dict(cfg.get('providers', {}).get('runtime_names', {}))
    for ws in workspaces(cfg):
        names.update(ws.get('runtime_names', {}))
    return names


def resolve(profiles, ws):
    """Профили шаблона по видам (`kind`: claude, codex, glm…) → runtime этого workspace; вида нет — пропуск."""
    out = []
    for p in profiles:
        rid = p.get('runtime_id') or ws.get('kinds', {}).get(p.get('kind'))
        if rid:
            out.append({'runtime_id': rid, 'model': p.get('model') or '', 'thinking_level': p.get('thinking_level') or ''})
    return out


def kind_of(runtime_id, ws):
    return next((k for k, rid in ws.get('kinds', {}).items() if rid == runtime_id), None)


def agent_chains(cfg, settings):
    """Цепочки из конфига; поверх — сохранённые на экране агента в Multica (`chains` в controls.json).
    Пустая сохранённая цепочка выключает фоллбек и для агента из конфига. У каждой — `workspace`."""
    home = cfg.get('providers', {}).get('workspace')
    out = {aid: {**a, 'workspace': a.get('workspace', home)} for aid, a in cfg.get('providers', {}).get('agents', {}).items()}
    for aid, saved in settings.get('chains', {}).items():
        if saved.get('chain'):
            out[aid] = {'name': saved.get('name') or out.get(aid, {}).get('name') or aid[:8], 'chain': saved['chain'],
                        'workspace': saved.get('workspace') or out.get(aid, {}).get('workspace') or home,
                        'pending_apply': bool(saved.get('pending_apply'))}
        else:
            out.pop(aid, None)
    return out


def runtime_names(cfg, settings):
    """Имена runtime для квот: из конфига всех workspace, для новых — запомненные при сохранении цепочки."""
    names = all_runtime_names(cfg)
    for saved in settings.get('chains', {}).values():
        for p in saved.get('chain') or []:
            if p.get('runtime_name'):
                names.setdefault(p['runtime_id'], p['runtime_name'])
    return names


def family(provider):
    """Синтаксис custom_args: codex — `-c mcp_servers…`, claude-обёртки — `--disallowedTools`."""
    return 'codex' if provider == 'codex' else 'claude' if provider == 'claude' else provider or ''


def blocked_tools(args):
    """Закрытые MCP-инструменты из custom_args любого семейства: [(сервер, инструмент)]."""
    out, i = [], 0
    while i < len(args):
        if args[i] == '--disallowedTools':
            i += 1
            while i < len(args) and not args[i].startswith('-'):
                parts = args[i].split('__')
                if len(parts) == 3 and parts[0] == 'mcp':
                    out.append((parts[1], parts[2]))
                i += 1
            continue
        if args[i] == '-c' and i + 1 < len(args):
            key, _, value = args[i + 1].partition('=')
            parts = key.split('.')
            if len(parts) == 3 and parts[0] == 'mcp_servers' and parts[2] == 'disabled_tools':
                try:
                    out += [(parts[1], t) for t in json.loads(value) if isinstance(t, str)]
                except ValueError:
                    pass
            i += 2
            continue
        i += 1
    return out


def render_blocked(tools, fam):
    if not tools:
        return []
    if fam == 'codex':
        servers = {}
        for server, tool in tools:
            servers.setdefault(server, []).append(tool)
        args = []
        for server, names in servers.items():
            args += ['-c', f'mcp_servers.{server}.disabled_tools=' + json.dumps(names, ensure_ascii=False, separators=(',', ':'))]
        return args
    if fam == 'claude':
        return ['--disallowedTools'] + [f'mcp__{s}__{t}' for s, t in tools]
    return []


def derive_args(fam, known):
    """custom_args нового профиля: копия профиля того же семейства, иначе перевод запретов из любого профиля.
    known — [(семейство, custom_args)] в порядке приоритета."""
    same = next((args for f, args in known if f == fam), None)
    if same is not None:
        return list(same)
    source = next((args for _, args in known if blocked_tools(args)), [])
    return render_blocked(blocked_tools(source), fam)


def next_profile(statuses, start):
    return next((i for i in range(start, len(statuses)) if statuses[i] is not False), None)


def profile_fields(profile):
    return {key: profile.get(key, [] if key == 'custom_args' else '')
            for key in ('runtime_id', 'model', 'thinking_level', 'custom_args')}


def targets(cfg, settings):
    """Настроенные эпики сохраняют свой репозиторий; пульт меняет только включение, паузу и снятие."""
    saved = settings.get('targets', {})
    out = []
    configured = set()
    for epic in cfg.get('epics', []):
        key = epic['key']
        configured.add(key)
        mine = saved.get(key, {})
        if mine.get('removed'):
            continue
        out.append({**mine, **epic, 'kind': epic.get('kind', 'epic'),
                    'enabled': mine.get('enabled', True), 'paused': mine.get('paused', False)})
    for key, target in saved.items():
        if key not in configured and not target.get('removed'):
            out.append({'paused': False, **target, 'key': key})
    return out


def grade(profile, cfg):
    """Сила профиля 1…5 по `providers.grades`: модель, иначе runtime (у GLM и MiniMax модель пустая),
    плюс поправка за уровень рассуждения. 0 — не оценена: ни в один уровень не проходит."""
    g = cfg.get('providers', {}).get('grades', {})
    base = g.get('models', {}).get(profile.get('model') or '') or g.get('runtimes', {}).get(profile.get('runtime_id'), 0)
    if not base:
        return 0
    return max(1, min(5, base + g.get('level_bonus', {}).get(profile.get('thinking_level') or '', 0)))


def grade_names(cfg):
    return cfg.get('providers', {}).get('grades', {}).get('names', {})


def tiers(cfg, settings):
    """Профили агентов (уровни силы): встроенные из конфига и созданные на экране агента (`tiers` в controls.json)."""
    out = [{**t, 'builtin': True} for t in cfg.get('providers', {}).get('tiers', [])]
    taken = {t['id'] for t in out}
    out += [{**t, 'id': tid, 'builtin': False} for tid, t in settings.get('tiers', {}).items() if tid not in taken]
    return out


def below_floor(chain, floor, cfg):
    """Номера профилей слабее порога уровня."""
    return [i for i, p in enumerate(chain) if grade(p, cfg) < floor]
