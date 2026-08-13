import { describe, it, expect } from "vitest";
import { parseTaskSpecs, MAX_BATCH_TASKS } from "./batch-args.js";

function specs(result: ReturnType<typeof parseTaskSpecs>) {
  if ("error" in result) throw new Error(`unexpected error: ${result.error}`);
  return result.specs;
}

describe("parseTaskSpecs", () => {
  it("accepts a plain array of ID strings", () => {
    expect(specs(parseTaskSpecs({ tasks: ["1", "2"] }))).toEqual([
      { taskId: "1", withContext: false },
      { taskId: "2", withContext: false },
    ]);
  });

  it("accepts the task_ids alias", () => {
    expect(specs(parseTaskSpecs({ task_ids: ["7"] }))).toEqual([{ taskId: "7", withContext: false }]);
  });

  it("coerces numeric IDs to strings", () => {
    expect(specs(parseTaskSpecs({ tasks: [123, { task_id: 456 }] }))).toEqual([
      { taskId: "123", withContext: false },
      { taskId: "456", withContext: false },
    ]);
  });

  it("applies shared options to every plain ID", () => {
    expect(specs(parseTaskSpecs({ tasks: ["1", "2"], with_context: true }))).toEqual([
      { taskId: "1", withContext: true },
      { taskId: "2", withContext: true },
    ]);
  });

  it("lets a per-task value override the shared default", () => {
    expect(specs(parseTaskSpecs({
      tasks: ["1", { task_id: "2", with_context: false }],
      with_context: true,
    }))).toEqual([
      { taskId: "1", withContext: true },
      { taskId: "2", withContext: false },
    ]);
  });

  it("mixes per-task settings without a shared default", () => {
    expect(specs(parseTaskSpecs({
      tasks: [{ task_id: "1", with_context: true }, "2"],
    }))).toEqual([
      { taskId: "1", withContext: true },
      { taskId: "2", withContext: false },
    ]);
  });

  it("merges duplicate IDs, keeping with_context if any entry asked for it", () => {
    expect(specs(parseTaskSpecs({
      tasks: ["1", { task_id: "1", with_context: true }, "2"],
    }))).toEqual([
      { taskId: "1", withContext: true },
      { taskId: "2", withContext: false },
    ]);
  });

  it("trims whitespace around IDs", () => {
    expect(specs(parseTaskSpecs({ tasks: [" 42 "] }))).toEqual([{ taskId: "42", withContext: false }]);
  });

  it("rejects a missing tasks array", () => {
    expect(parseTaskSpecs({})).toMatchObject({ error: expect.stringContaining("'tasks' is required") });
    expect(parseTaskSpecs(undefined)).toMatchObject({ error: expect.stringContaining("'tasks' is required") });
  });

  it("rejects an empty tasks array", () => {
    expect(parseTaskSpecs({ tasks: [] })).toMatchObject({ error: "'tasks' must not be empty" });
  });

  it("rejects more than MAX_BATCH_TASKS", () => {
    const tasks = Array.from({ length: MAX_BATCH_TASKS + 1 }, (_, i) => String(i));
    expect(parseTaskSpecs({ tasks })).toMatchObject({ error: expect.stringContaining("Too many tasks") });
  });

  it("rejects an entry without task_id", () => {
    expect(parseTaskSpecs({ tasks: [{ with_context: true }] }))
      .toMatchObject({ error: "tasks[0]: 'task_id' is required" });
  });

  it("rejects an empty task ID", () => {
    expect(parseTaskSpecs({ tasks: ["  "] })).toMatchObject({ error: "tasks[0]: empty task ID" });
  });

  it("rejects a non-boolean with_context", () => {
    expect(parseTaskSpecs({ tasks: [{ task_id: "1", with_context: "yes" }] }))
      .toMatchObject({ error: "tasks[0]: 'with_context' must be a boolean" });
    expect(parseTaskSpecs({ tasks: ["1"], with_context: "yes" }))
      .toMatchObject({ error: "arguments: 'with_context' must be a boolean" });
  });

  it("rejects an unusable entry type", () => {
    expect(parseTaskSpecs({ tasks: [null] }))
      .toMatchObject({ error: expect.stringContaining("tasks[0]: expected a task ID") });
  });
});
