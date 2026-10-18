"""Песочница validate: transient-юнит systemd без сети, без доступа к данным harness и домашним каталогам.

Набор свойств фиксирован здесь и не приходит ни из запроса, ни из кандидата; политика задаёт только лимиты.
"""
import contextlib
import itertools
import re
import time
import uuid

from .store import file_lock

WORK = '/work'
CHECKS = '/checks'
HIDDEN = ['/var/lib/harness-control', '/etc/harness-control', '/etc/sudoers.d', '/etc/sudoers', '/root', '/var/backups',
          '-/run/dbus', '-/run/docker.sock', '-/var/run/docker.sock']
TMP_SIZE = '512M'
FIXED_PROPERTIES = [
    'DynamicUser=yes', 'PrivateNetwork=yes', 'ProtectSystem=strict', 'ProtectHome=yes',
    # /tmp в памяти: ограничен размером и входит в MemoryMax, на диск хоста кандидат не пишет
    f'TemporaryFileSystem=/tmp:mode=1777,size={TMP_SIZE}',
    'PrivateDevices=yes', 'NoNewPrivileges=yes', 'ProtectKernelTunables=yes', 'ProtectKernelModules=yes',
    'ProtectControlGroups=yes', 'RestrictSUIDSGID=yes', 'LockPersonality=yes', 'CapabilityBoundingSet=',
    'RestrictNamespaces=yes', 'RestrictAddressFamilies=AF_UNIX', 'RestrictRealtime=yes', 'ProtectClock=yes',
    'ProtectHostname=yes', 'ProtectProc=invisible', 'ProcSubset=pid', 'PrivateIPC=yes',
    'SystemCallArchitectures=native', 'SystemCallFilter=@system-service', 'LimitFSIZE=1G',
]
ENV = {'HOME': '/tmp', 'TMPDIR': '/tmp', 'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1', 'CI': '1'}
RESULT = re.compile(r'Finished with result:\s*(\S+)')
TERMINATED = re.compile(r'terminated with:\s*code=(\w+),\s*status=([^\s,/]+)(?:/(\S+))?')
SIGNALS = {'KILL', 'TERM', 'SEGV', 'ABRT', 'BUS', 'INT', 'HUP', 'PIPE', 'FPE', 'ILL', 'QUIT'}


def substitute(argv):
    return [a.replace('{work}', WORK).replace('{checks}', CHECKS) for a in argv]


def build_argv(systemd_run, limits, work_dir, checks_dir, argv, unit=None, extra_env=None, extra_properties=()):
    """Полный argv `systemd-run …`. work_dir и checks_dir монтируются только на чтение."""
    unit = unit or f'harness-validate-{uuid.uuid4().hex[:12]}'
    out = [systemd_run, f'--unit={unit}', '--wait', '--collect', '--pipe']
    props = [*FIXED_PROPERTIES,
             f'MemoryMax={limits["memory_max"]}', 'MemorySwapMax=0', f'TasksMax={limits["tasks_max"]}',
             f'RuntimeMaxSec={limits["runtime_max_sec"]}', f'WorkingDirectory={WORK}',
             f'BindReadOnlyPaths={work_dir}:{WORK}', f'BindReadOnlyPaths={checks_dir}:{CHECKS}',
             *[f'InaccessiblePaths={p}' for p in HIDDEN], *extra_properties]
    for p in props:
        out += ['-p', p]
    env = {**ENV, 'PATH': limits['path'], **(extra_env or {})}
    for k, v in sorted(env.items()):
        out.append(f'--setenv={k}={v}')
    return [*out, '--', *substitute(argv)]


def parse_outcome(returncode, stderr):
    """Первичная причина: exit code, сигнал, таймаут или oom-kill — как их видит systemd."""
    result = (RESULT.search(stderr) or [None, None])[1]
    m = TERMINATED.search(stderr)
    code_kind, status, sig = (m.group(1), m.group(2), m.group(3)) if m else (None, None, None)
    killed = code_kind == 'killed'
    signal = (status if not status.isdigit() else (sig or status)) if killed else None
    return {
        'ok': returncode == 0 and result in (None, 'success'),
        'exit_code': None if killed else (int(status) if status and status.isdigit() else returncode),
        'signal': signal,
        'timeout': result == 'timeout' or returncode == 124,
        'oom_kill': result == 'oom-kill',
        'result': result,
    }


def run(system, limits, work_dir, checks_dir, argv, timeout, extra_env=None):
    """Запуск в песочнице. Возвращает (outcome, вывод)."""
    full = build_argv(system.exe('systemd-run'), limits, work_dir, checks_dir, argv, extra_env=extra_env)
    r = system.run(full, timeout=timeout + 60)
    return parse_outcome(r.returncode, r.stderr), (r.stdout or '') + ('\n' + r.stderr if r.stderr else '')


@contextlib.contextmanager
def slot(paths, limit, timeout=3600, poll=0.5):
    """Глобальный лимит параллельных validate: limit flock-слотов; ждём свободный до timeout."""
    deadline = time.monotonic() + timeout
    while True:
        for i in range(limit):
            with contextlib.ExitStack() as stack:
                got = stack.enter_context(file_lock(paths.locks / f'validate-{i}.lock', blocking=False))
                if got:
                    yield i
                    return
        if time.monotonic() >= deadline:
            yield None
            return
        time.sleep(poll)
