import type { TaskBatchSpec } from "../api/task-fetcher-api.js";

export const MAX_BATCH_TASKS = 100;

export type ParseSpecsResult = { specs: TaskBatchSpec[] } | { error: string };

/** Per-task options, mirroring get_task's arguments. Add new get_task options here. */
function parseOptions(
  source: Record<string, unknown>,
  defaults: TaskBatchSpec,
  where: string
): TaskBatchSpec | { error: string } {
  const spec: TaskBatchSpec = { ...defaults };

  if (source.with_context !== undefined) {
    if (typeof source.with_context !== "boolean") {
      return { error: `${where}: 'with_context' must be a boolean` };
    }
    spec.withContext = source.with_context;
  }

  return spec;
}

/**
 * Normalize get_tasks_batch arguments into task specs.
 *
 * Accepts `tasks` (or the `task_ids` alias) as an array of either plain IDs or
 * `{ task_id, ...options }` objects. Top-level options are shared defaults; a per-task
 * value overrides them. Duplicate IDs are merged — an id requested with context keeps it.
 */
export function parseTaskSpecs(args: Record<string, unknown> | undefined): ParseSpecsResult {
  const raw = args?.tasks ?? args?.task_ids;

  if (!Array.isArray(raw)) {
    return { error: "'tasks' is required: an array of task IDs or { task_id, with_context } objects" };
  }
  if (raw.length === 0) return { error: "'tasks' must not be empty" };
  if (raw.length > MAX_BATCH_TASKS) {
    return { error: `Too many tasks: ${raw.length} (max ${MAX_BATCH_TASKS})` };
  }

  const shared = parseOptions(args ?? {}, { taskId: "", withContext: false }, "arguments");
  if ("error" in shared) return shared;

  const specs: TaskBatchSpec[] = [];
  const byId = new Map<string, TaskBatchSpec>();

  for (let i = 0; i < raw.length; i++) {
    const item = raw[i];
    const where = `tasks[${i}]`;
    let taskId: string;
    let spec: TaskBatchSpec;

    if (typeof item === "string" || typeof item === "number") {
      taskId = String(item).trim();
      spec = { ...shared, taskId };
    } else if (item !== null && typeof item === "object") {
      const obj = item as Record<string, unknown>;
      const id = obj.task_id ?? obj.taskId;
      if (typeof id !== "string" && typeof id !== "number") {
        return { error: `${where}: 'task_id' is required` };
      }
      taskId = String(id).trim();
      const parsed = parseOptions(obj, { ...shared, taskId }, where);
      if ("error" in parsed) return parsed;
      spec = parsed;
    } else {
      return { error: `${where}: expected a task ID or { task_id, with_context } object` };
    }

    if (!taskId) return { error: `${where}: empty task ID` };

    const existing = byId.get(taskId);
    if (existing) {
      existing.withContext = existing.withContext || spec.withContext;
      continue;
    }
    byId.set(taskId, spec);
    specs.push(spec);
  }

  return { specs };
}
