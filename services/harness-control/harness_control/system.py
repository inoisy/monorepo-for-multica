"""Единственное место, где harness-control запускает внешние программы: systemctl, systemd-run, git.

Абсолютные пути у root; под HARNESS_ROOT (тесты) имена ищутся в PATH, где лежат подмены.
Аргументы всегда списком, shell не используется.
"""
import re
import subprocess
import threading

from .errors import HarnessError

BINARIES = {'systemctl': '/usr/bin/systemctl', 'systemd-run': '/usr/bin/systemd-run', 'git': '/usr/bin/git'}
GIT_ENV = {'GIT_TERMINAL_PROMPT': '0', 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
           'HOME': '/nonexistent', 'LC_ALL': 'C', 'PATH': '/usr/bin:/bin'}


MAX_OUTPUT = 8 << 20


def _drain(stream, chunks):
    kept = 0
    for block in iter(lambda: stream.read(1 << 16), b''):
        if kept < MAX_OUTPUT:
            chunks.append(block[:MAX_OUTPUT - kept])
            kept += len(block)


class _suppress_broken_pipe:
    def __enter__(self): return self
    def __exit__(self, kind, value, tb): return kind is not None and issubclass(kind, BrokenPipeError)


class System:
    def __init__(self, paths, bare=None):
        # bare: имена вместо абсолютных путей (тесты ставят подмены в PATH)
        self.bare = (paths.root != paths.root.parent) if bare is None else bare

    def exe(self, name):
        return name if self.bare else BINARIES[name]

    def run(self, argv, timeout=60, env=None, input=None, cwd=None, binary=False):
        """CompletedProcess без исключения при ненулевом коде; таймаут → rc=124.

        Вывод читается потоком и обрезается до MAX_OUTPUT: процесс продолжает писать в пустоту, а память root не растёт."""
        try:
            proc = subprocess.Popen(argv, stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, env=env, cwd=cwd)
        except FileNotFoundError as e:
            return subprocess.CompletedProcess(argv, 127, b'' if binary else '', str(e))
        out, err = [], []
        readers = [threading.Thread(target=_drain, args=(proc.stdout, out), daemon=True),
                   threading.Thread(target=_drain, args=(proc.stderr, err), daemon=True)]
        for t in readers:
            t.start()
        if input is not None:
            with _suppress_broken_pipe():
                proc.stdin.write(input.encode())
                proc.stdin.close()
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            code = 124
        for t in readers:
            t.join(5)
        for stream in (proc.stdout, proc.stderr):
            stream.close()
        stdout, stderr = b''.join(out), b''.join(err)
        if code == 124:
            stderr += b'\ntimeout'
        if binary:
            return subprocess.CompletedProcess(argv, code, stdout, stderr)
        return subprocess.CompletedProcess(argv, code, stdout.decode(errors='replace'), stderr.decode(errors='replace'))

    # ---- systemd -------------------------------------------------------------------------
    def systemctl(self, *args, timeout=120):
        return self.run([self.exe('systemctl'), *args], timeout=timeout)

    def unit_exists(self, unit):
        r = self.systemctl('show', unit, '-p', 'LoadState', '--value')
        return r.returncode == 0 and r.stdout.strip() not in ('', 'not-found')

    def unit_props(self, unit, props):
        """Свойства юнита; метки времени — unix-секунды (None, если не было)."""
        r = self.systemctl('show', unit, '--timestamp=unix', *[f'-p{p}' for p in props])
        if r.returncode:
            raise HarnessError('internal', f'systemctl show {unit}: {r.stderr.strip()[:200]}')
        out = {}
        for line in r.stdout.splitlines():
            key, _, value = line.partition('=')
            out[key] = value
        for key, value in list(out.items()):
            if 'Timestamp' in key or 'USec' in key:
                m = re.match(r'^@(\d+)', value)
                out[key] = int(m.group(1)) if m else None
        return out

    def is_busy(self, unit):
        return self.unit_props(unit, ['ActiveState'])['ActiveState'] in ('active', 'activating', 'deactivating', 'reloading')

    def start(self, unit): return self._checked('start', unit)
    def stop(self, unit): return self._checked('stop', unit)
    def restart(self, unit): return self._checked('restart', unit)
    def enable_now(self, unit): return self._checked('enable', '--now', unit)
    def disable_now(self, unit): return self._checked('disable', '--now', unit)

    def _checked(self, *args):
        r = self.systemctl(*args)
        if r.returncode:
            raise HarnessError('internal', f'systemctl {" ".join(args)}: {(r.stderr or r.stdout).strip()[:300]}')
        return r

    def spawn_runner(self, op_id, runner_path):
        """Операция живёт в своём transient-юните и не зависит ни от рана агента, ни от обрыва MCP."""
        argv = [self.exe('systemd-run'), f'--unit=harness-op-{op_id}', '--collect', '--quiet',
                '-p', 'RuntimeMaxSec=7200', '-p', 'KillMode=control-group', '-p', 'MemoryMax=2G', '-p', 'TasksMax=256',
                # упавший или убитый runner: прерванные операции доводятся сразу, а не при следующей загрузке
                '-p', 'ExecStopPost=/usr/local/sbin/harness-priv recover',
                '--description', f'harness-control {op_id}',
                '/usr/bin/python3', '-I', runner_path, op_id]
        r = self.run(argv, timeout=60)
        if r.returncode:
            raise HarnessError('internal', f'не удалось запустить runner: {(r.stderr or r.stdout).strip()[:300]}')

    # ---- git -----------------------------------------------------------------------------
    def git(self, git_dir, *args, protocol='https', timeout=300, binary=False):
        env = {**GIT_ENV, 'GIT_ALLOW_PROTOCOL': protocol}
        if self.bare:
            env['PATH'] = '/usr/bin:/bin'
        return self.run([self.exe('git'), '--git-dir', str(git_dir), *args], timeout=timeout, env=env, binary=binary)
