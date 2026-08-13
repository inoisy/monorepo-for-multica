import { describe, it, expect, vi, beforeEach } from "vitest";
import type { B24TaskRaw, B24CommentRaw } from "./b24-client.js";

vi.mock("../config.js", () => ({
  env: { baseUrl: "https://sphere.loodsen.ru", userId: "1", webhookUrl: "https://sphere.loodsen.ru/rest/1/auth/" },
  openStageIds: [],
  stageIdToName: new Map<string, string>(),
}));

const b24BatchTasksWithComments = vi.fn();
const b24BatchListByParent = vi.fn();
const b24BatchFetchTags = vi.fn();

vi.mock("./b24-client.js", () => ({
  b24FetchTasks: vi.fn(),
  b24FetchTaskWithComments: vi.fn(),
  b24BatchTasksWithComments: (...args: unknown[]) => b24BatchTasksWithComments(...args),
  b24BatchListByParent: (...args: unknown[]) => b24BatchListByParent(...args),
  b24BatchFetchTags: (...args: unknown[]) => b24BatchFetchTags(...args),
  b24Call: vi.fn(),
  buildDiskAttachUrl: vi.fn(),
}));

const { fetchTasksBatch } = await import("./task-fetcher-api.js");

function raw(id: string, parentId = "", title = `Task ${id}`): B24TaskRaw {
  return {
    id,
    title,
    description: "",
    status: "2",
    stageId: "10",
    priority: "1",
    deadline: "",
    parentId,
    groupId: "5",
    responsible: { id: "1", name: "Dev" },
    responsibleId: "1",
    creator: { id: "1", name: "Dev" },
    timeEstimate: null,
    timeSpentInLogs: null,
  };
}

/** Mocks the task batch endpoint with the given raw tasks, keyed by id. */
function mockTasks(...tasks: B24TaskRaw[]) {
  const byId = new Map(tasks.map((t) => [t.id, { task: t, comments: [] as B24CommentRaw[] }]));
  b24BatchTasksWithComments.mockImplementation(async (ids: string[]) =>
    new Map(ids.filter((id) => byId.has(id)).map((id) => [id, byId.get(id)!]))
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  b24BatchListByParent.mockResolvedValue(new Map());
  b24BatchFetchTags.mockResolvedValue(new Map());
});

describe("fetchTasksBatch", () => {
  it("fetches N tasks in a single batch call when no context is requested", async () => {
    mockTasks(raw("1"), raw("2"), raw("3"));

    const result = await fetchTasksBatch([
      { taskId: "1" }, { taskId: "2" }, { taskId: "3" },
    ]);

    expect(b24BatchTasksWithComments).toHaveBeenCalledTimes(1);
    expect(b24BatchTasksWithComments).toHaveBeenCalledWith(["1", "2", "3"]);
    expect(b24BatchListByParent).not.toHaveBeenCalled();
    expect([...result.keys()]).toEqual(["1", "2", "3"]);
    expect(result.get("1")!.parentStory).toBeNull();
    expect(result.get("1")!.relatedTasks).toEqual([]);
  });

  it("omits tasks missing from the batch response", async () => {
    mockTasks(raw("1"));

    const result = await fetchTasksBatch([{ taskId: "1" }, { taskId: "404" }]);

    expect(result.has("1")).toBe(true);
    expect(result.has("404")).toBe(false);
  });

  it("dedupes repeated IDs into one fetch", async () => {
    mockTasks(raw("1"));

    await fetchTasksBatch([{ taskId: "1" }, { taskId: "1" }]);

    expect(b24BatchTasksWithComments).toHaveBeenCalledWith(["1"]);
  });

  it("fetches a shared parent story once for tasks that share it", async () => {
    mockTasks(raw("1", "100"), raw("2", "100"), raw("100", "", "Story"));

    const result = await fetchTasksBatch([
      { taskId: "1", withContext: true },
      { taskId: "2", withContext: true },
    ]);

    const parentCalls = b24BatchTasksWithComments.mock.calls.filter(
      (call) => (call[0] as string[]).includes("100")
    );
    expect(parentCalls).toHaveLength(1);
    expect(parentCalls[0][0]).toEqual(["100"]);

    expect(result.get("1")!.parentStory!.taskId).toBe("100");
    expect(result.get("2")!.parentStory!.taskId).toBe("100");
    expect(result.get("1")!.task.parentTaskTitle).toBe("Story");
  });

  it("skips context work for tasks that did not ask for it", async () => {
    mockTasks(raw("1", "100"), raw("2", "200"), raw("100", "", "Story"));

    const result = await fetchTasksBatch([
      { taskId: "1", withContext: true },
      { taskId: "2", withContext: false },
    ]);

    expect(b24BatchListByParent).toHaveBeenCalledWith(["100"]);
    expect(result.get("1")!.parentStory!.taskId).toBe("100");
    expect(result.get("2")!.parentStory).toBeNull();
  });

  it("attaches siblings and excludes the task itself", async () => {
    mockTasks(raw("1", "100"), raw("100", "", "Story"), raw("9", "100", "Sibling"));
    b24BatchListByParent.mockResolvedValue(new Map([["100", [raw("1", "100"), raw("9", "100")]]]));

    const result = await fetchTasksBatch([{ taskId: "1", withContext: true }]);

    const ctx = result.get("1")!;
    expect(ctx.relatedTasks.map((t) => t.taskId)).toEqual(["9"]);
    expect(ctx.task.siblingTasks).toEqual([{ id: "9", title: "Sibling" }]);
  });

  it("reuses an already-fetched task instead of refetching it as a sibling", async () => {
    mockTasks(raw("1", "100"), raw("2", "100"), raw("100", "", "Story"));
    b24BatchListByParent.mockResolvedValue(new Map([["100", [raw("1", "100"), raw("2", "100")]]]));

    const result = await fetchTasksBatch([
      { taskId: "1", withContext: true },
      { taskId: "2", withContext: true },
    ]);

    // calls: main [1,2], parents [100] — no third call for siblings, both already fetched
    expect(b24BatchTasksWithComments).toHaveBeenCalledTimes(2);
    expect(result.get("1")!.relatedTasks.map((t) => t.taskId)).toEqual(["2"]);
    expect(result.get("2")!.relatedTasks.map((t) => t.taskId)).toEqual(["1"]);
  });

  it("does not refetch a parent that was also requested as a task", async () => {
    mockTasks(raw("1", "100"), raw("100", "", "Story"));

    const result = await fetchTasksBatch([
      { taskId: "1", withContext: true },
      { taskId: "100" },
    ]);

    expect(b24BatchTasksWithComments).toHaveBeenCalledTimes(1);
    expect(b24BatchTasksWithComments).toHaveBeenCalledWith(["1", "100"]);
    expect(result.get("1")!.parentStory!.taskId).toBe("100");
    expect(result.has("100")).toBe(true);
  });

  it("applies tags to main tasks, parents and siblings in one batch", async () => {
    mockTasks(raw("1", "100"), raw("100", "", "Story"), raw("9", "100", "Sibling"));
    b24BatchListByParent.mockResolvedValue(new Map([["100", [raw("1", "100"), raw("9", "100")]]]));
    b24BatchFetchTags.mockResolvedValue(new Map([
      ["1", ["спринт 49"]],
      ["100", ["story"]],
      ["9", ["be"]],
    ]));

    const result = await fetchTasksBatch([{ taskId: "1", withContext: true }]);

    expect(b24BatchFetchTags).toHaveBeenCalledTimes(1);
    expect(b24BatchFetchTags.mock.calls[0][0].sort()).toEqual(["1", "100", "9"]);
    expect(result.get("1")!.task.tags).toEqual(["спринт 49"]);
    expect(result.get("1")!.parentStory!.tags).toEqual(["story"]);
    expect(result.get("1")!.relatedTasks[0].tags).toEqual(["be"]);
  });

  it("returns an empty map for no specs without hitting the API", async () => {
    const result = await fetchTasksBatch([]);

    expect(result.size).toBe(0);
    expect(b24BatchTasksWithComments).not.toHaveBeenCalled();
  });
});
