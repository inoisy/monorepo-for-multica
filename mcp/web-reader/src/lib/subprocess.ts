import { spawn, ChildProcess } from 'child_process';
import { writeFileSync, unlinkSync, mkdirSync, readdirSync, statSync } from 'fs';
import { join } from 'path';
import { debug } from './utils.js';

const activeProcesses = new Set<ChildProcess>();

export function registerProcess(proc: ChildProcess): void {
  activeProcesses.add(proc);
  proc.on('exit', () => activeProcesses.delete(proc));
  proc.on('error', () => activeProcesses.delete(proc));
}

export function killAllSubprocesses(): void {
  activeProcesses.forEach(proc => {
    try { proc.kill('SIGKILL'); } catch {}
  });
  activeProcesses.clear();
}

/** Scratch dir for generated renderer scripts, next to the built package. */
export function tempDir(): string {
  const dir = join(__dirname, '..', '..', '.tmp');
  try { mkdirSync(dir, { recursive: true }); } catch {}
  return dir;
}

/**
 * Deletes renderer scripts left behind by crashed runs. Called once at startup
 * so `.tmp` cannot grow without bound.
 */
export function cleanTempDir(maxAgeMs = 60 * 60 * 1000): void {
  const dir = tempDir();
  const cutoff = Date.now() - maxAgeMs;
  try {
    for (const name of readdirSync(dir)) {
      const path = join(dir, name);
      try {
        if (statSync(path).mtimeMs < cutoff) unlinkSync(path);
      } catch {}
    }
  } catch {}
}

export interface RunScriptOptions {
  /** Interpreter binary, e.g. `node` or a python path. */
  command: string;
  /** Extra args placed before the script path. */
  args?: string[];
  /** Script source written to a temp file and executed. */
  script: string;
  /** File extension for the temp script (`.mjs`, `.py`). */
  extension: string;
  /** Hard wall-clock budget. The process is killed when it elapses. */
  timeoutMs: number;
  /** Prefix used in error messages and debug logs. */
  label: string;
}

/**
 * Runs a generated script in a child process and parses the single JSON object
 * it writes to stdout. The child is always killed and its temp file removed,
 * including on timeout — a renderer must never leak a browser process.
 */
export async function runScript<T>(opts: RunScriptOptions): Promise<T> {
  const { command, args = [], script, extension, timeoutMs, label } = opts;
  const scriptPath = join(tempDir(), `${label}-${Date.now()}-${process.pid}${extension}`);
  writeFileSync(scriptPath, script, 'utf8');

  const cleanup = () => { try { unlinkSync(scriptPath); } catch {} };

  return new Promise<T>((resolve, reject) => {
    let proc: ChildProcess;
    try {
      proc = spawn(command, [...args, scriptPath], { stdio: ['ignore', 'pipe', 'pipe'], shell: false });
    } catch (err) {
      cleanup();
      return reject(new Error(`${label}: failed to spawn ${command} (${(err as Error).message})`));
    }

    registerProcess(proc);

    let stdout = '';
    let stderr = '';
    let timedOut = false;
    let settled = false;

    proc.stdout?.on('data', c => { stdout += c.toString(); });
    proc.stderr?.on('data', c => {
      const s = c.toString();
      stderr += s;
      debug(`[${label}] ${s.trimEnd()}`);
    });

    const timer = setTimeout(() => {
      timedOut = true;
      try { proc.kill('SIGKILL'); } catch {}
    }, timeoutMs);

    // A killed browser can leave the child alive long enough that `close` never
    // fires; settle on `exit` too and guard against a double resolve.
    const finish = (fn: () => void) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      cleanup();
      fn();
    };

    proc.on('error', err => {
      finish(() => {
        if ((err as NodeJS.ErrnoException).code === 'ENOENT') {
          return reject(new Error(`${label}: interpreter not found: ${command}`));
        }
        reject(new Error(`${label}: subprocess error (${err.message})`));
      });
    });

    proc.on('close', code => {
      finish(() => {
        debug(`[${label}] exit code=${code} timedOut=${timedOut} stdout=${stdout.length}b`);

        if (timedOut) {
          return reject(new Error(`${label}: timed out after ${timeoutMs}ms`));
        }
        if (code === 2) {
          return reject(new Error(`${label}: missing dependency${stderr ? ` — ${stderr.trim().slice(0, 300)}` : ''}`));
        }

        const trimmed = stdout.trim();
        if (!trimmed) {
          return reject(new Error(
            `${label}: no output (exit ${code})${stderr ? ` — ${stderr.trim().slice(0, 300)}` : ''}`,
          ));
        }

        // Browser libs sometimes print banners to stdout; the JSON payload is
        // the last line, so fall back to that when a full parse fails.
        let parsed: (T & { error?: string }) | undefined;
        for (const candidate of [trimmed, trimmed.slice(trimmed.lastIndexOf('\n') + 1)]) {
          try { parsed = JSON.parse(candidate); break; } catch {}
        }
        if (!parsed) {
          return reject(new Error(`${label}: unparseable output (${trimmed.slice(0, 200)})`));
        }
        if (parsed.error) return reject(new Error(`${label}: ${parsed.error}`));
        resolve(parsed);
      });
    });
  });
}
