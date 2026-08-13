import { env } from "../config.js";

// Глобальный keep-alive agent с короткими таймаутами.
// Bitrix24 за reverse-proxy (172.24.66.83) прибивает idle-соединения
// через ~30-60 сек. undici по умолчанию использует 30-сек таймаут и
// пытается писать в разорванный сокет, что приводит к зависанию fetch
// на 60+ сек и последующему 502 от Hermes MCP runtime.
// undici встроен в Node >= 18 — но в проекте нет @types/undici,
// поэтому загружаем динамически и работаем через any-каст.

// eslint-disable-next-line @typescript-eslint/no-var-requires
const undiciModule: any = (() => {
  try {
    // @ts-ignore — undici встроен в Node 18+
    return require("undici");
  } catch {
    return null;
  }
})();

if (undiciModule?.Agent && undiciModule?.setGlobalDispatcher) {
  const agent = new undiciModule.Agent({
    keepAliveTimeout: 10_000,
    keepAliveMaxTimeout: 30_000,
    connections: 10,
    connect: { timeout: 10_000 },
    // bodyTimeout / headersTimeout НЕ ставим — fetch() под капотом
    // использует undici, и слишком жёсткие таймауты ломают стриминг.
  });
  undiciModule.setGlobalDispatcher(agent);
} else {
  console.error("[b24-client] undici unavailable, keep-alive tuning skipped");
}

const REQUEST_TIMEOUT_MS = 25_000;

export interface B24TaskRaw {
  id: string;
  title: string;
  description: string;
  status: string;
  stageId: string;
  priority: string;
  deadline: string;
  tag?: string[];
  parentId: string;        // tasks.task.list/get uses parentId, not parentTaskId
  groupId: string;
  responsible: { id: string; name: string; link?: string; workPosition?: string };
  responsibleId: string;
  creator: { id: string; name: string };
  timeEstimate: string | null;
  timeSpentInLogs: string | null;
  [key: string]: unknown;
}

export interface B24AttachmentRaw {
  ATTACHMENT_ID: string;
  NAME: string;
  SIZE: string;
  FILE_ID: string;
  DOWNLOAD_URL: string;
  VIEW_URL: string;
}

export interface B24CommentRaw {
  ID: string;
  AUTHOR_ID: string;
  AUTHOR_NAME: string;
  POST_MESSAGE: string;
  POST_DATE: string;
  ATTACHED_OBJECTS?: Record<string, B24AttachmentRaw>;
}

export interface B24ElapsedRaw {
  ID: string;
  TASKID: string;
  USER_ID: string;
  SECONDS: string;
  COMMENT_TEXT: string;
  CREATED_DATE: string;
}

function buildBody(obj: Record<string, unknown>): string {
  const parts: string[] = [];
  function encode(value: unknown, key: string): void {
    if (Array.isArray(value)) {
      value.forEach((item, i) => encode(item, `${key}[${i}]`));
    } else if (value !== null && typeof value === "object") {
      for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
        encode(v, `${key}[${k}]`);
      }
    } else if (value !== null && value !== undefined) {
      parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`);
    }
  }
  for (const [key, value] of Object.entries(obj)) {
    encode(value, key);
  }
  return parts.join("&");
}

export async function b24Call<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
  const webhookUrl = env.webhookUrl;
  if (!webhookUrl) throw new Error("B24_WEBHOOK_URL not set in .env");

  const url = `${webhookUrl.replace(/\/$/, "")}/${method}.json`;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: buildBody(params),
      signal: controller.signal,
    });

    if (!response.ok) {
      const text = await response.text();
      throw new Error(`B24 HTTP ${response.status}: ${text.slice(0, 200)}`);
    }

    const data = await response.json() as { result: T; error?: string; error_description?: string };
    if (data.error) throw new Error(`B24 API: ${data.error} — ${data.error_description ?? ""}`);
    return data.result;
  } catch (e: any) {
    if (e?.name === "AbortError") {
      throw new Error(`B24 timeout after ${REQUEST_TIMEOUT_MS}ms: ${method}`);
    }
    throw e;
  } finally {
    clearTimeout(timeout);
  }
}

export async function b24FetchTasks(params: Record<string, unknown> = {}): Promise<B24TaskRaw[]> {
  const all: B24TaskRaw[] = [];
  let start = 0;
  while (true) {
    const result = await b24Call<{ tasks: B24TaskRaw[]; next?: number }>("tasks.task.list", {
      ...params,
      start,
    });
    const page = result.tasks ?? [];
    all.push(...page);
    if (!result.next || page.length === 0) break;
    start = result.next;
  }
  return all;
}

export async function b24AddComment(taskId: string, message: string): Promise<string> {
  return b24Call<string>("task.commentitem.add", {
    TASKID: taskId,
    FIELDS: { POST_MESSAGE: message },
  });
}

export async function b24UpdateComment(taskId: string, commentId: string, message: string): Promise<string> {
  return b24Call<string>("task.commentitem.update", {
    TASKID: taskId,
    ITEMID: commentId,
    FIELDS: { POST_MESSAGE: message },
  });
}

export async function b24DeleteComment(taskId: string, commentId: string): Promise<string> {
  return b24Call<string>("task.commentitem.delete", {
    TASKID: taskId,
    ITEMID: commentId,
  });
}

export async function b24LogTime(taskId: string, seconds: number, comment?: string): Promise<string> {
  const fields: Record<string, unknown> = { SECONDS: seconds };
  if (comment) fields["COMMENT_TEXT"] = comment;
  return b24Call<string>("task.elapseditem.add", {
    TASKID: taskId,
    FIELDS: fields,
  });
}

export async function b24GetTimeEntries(taskId: string): Promise<B24ElapsedRaw[]> {
  const result = await b24Call<B24ElapsedRaw[]>("task.elapseditem.getlist", {
    TASKID: taskId,
    ORDER: { ID: "ASC" },
  });
  return Array.isArray(result) ? result : [];
}

export interface B24TaskTimeTotals {
  timeEstimate: string | null;   // plan, seconds
  timeSpentInLogs: string | null; // spent, seconds
}

// Aggregate time totals straight from the task object.
// Reliable source: task.elapseditem.getlist is broken server-side on the
// current Bitrix instance (ERROR_CORE "Object property 'count' not found"),
// but tasks.task.get always returns timeEstimate / timeSpentInLogs.
export async function b24GetTaskTimeTotals(taskId: string): Promise<B24TaskTimeTotals> {
  const result = await b24Call<{ task: B24TaskRaw }>("tasks.task.get", { taskId });
  const task = result.task;
  return {
    timeEstimate: task.timeEstimate ?? null,
    timeSpentInLogs: task.timeSpentInLogs ?? null,
  };
}

export async function b24DeleteTimeEntry(taskId: string, entryId: string): Promise<string> {
  return b24Call<string>("task.elapseditem.delete", {
    TASKID: taskId,
    ITEMID: entryId,
  });
}

export interface B24Stage {
  ID: string;
  TITLE: string;
  SORT: string;
  COLOR: string;
  SYSTEM_TYPE: string | null;
  ENTITY_ID: string;
  ENTITY_TYPE: string;
}

export async function b24GetStages(entityId: number): Promise<Map<string, B24Stage>> {
  const result = await b24Call<Record<string, B24Stage>>("task.stages.get", { entityId });
  return new Map(Object.entries(result));
}

export async function b24GetGroup(groupId: number): Promise<{ NAME: string } | null> {
  try {
    return await b24Call<{ NAME: string }>("sonet_group.get", { groupId });
  } catch {
    return null;
  }
}

export async function b24Batch<T extends Record<string, unknown>>(
  commands: Record<string, string>,
  halt = 0
): Promise<{ result: T; result_error: Record<string, string> }> {
  const webhookUrl = env.webhookUrl;
  if (!webhookUrl) throw new Error("B24_WEBHOOK_URL not set in .env");

  const url = `${webhookUrl.replace(/\/$/, "")}/batch.json`;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: buildBody({ halt, cmd: commands }),
      signal: controller.signal,
    });

    if (!response.ok) {
      const text = await response.text();
      throw new Error(`B24 HTTP ${response.status}: ${text.slice(0, 200)}`);
    }

    const data = await response.json() as {
      result: { result: T; result_error: Record<string, string> };
      error?: string;
      error_description?: string;
    };
    if (data.error) throw new Error(`B24 API: ${data.error} — ${data.error_description ?? ""}`);
    return data.result;
  } catch (e: any) {
    if (e?.name === "AbortError") {
      throw new Error(`B24 batch timeout after ${REQUEST_TIMEOUT_MS}ms`);
    }
    throw e;
  } finally {
    clearTimeout(timeout);
  }
}

const B24_BATCH_LIMIT = 50;

export async function b24BatchListByParent(
  parentIds: string[]
): Promise<Map<string, B24TaskRaw[]>> {
  const results = new Map<string, B24TaskRaw[]>();
  if (parentIds.length === 0) return results;

  for (let i = 0; i < parentIds.length; i += B24_BATCH_LIMIT) {
    const chunk = parentIds.slice(i, i + B24_BATCH_LIMIT);
    const commands: Record<string, string> = {};
    for (const id of chunk) {
      commands[`list_${id}`] = `tasks.task.list?filter[PARENT_ID]=${id}&select[0]=*&select[1]=UF_*`;
    }
    const batch = await b24Batch<Record<string, unknown>>(commands);
    for (const id of chunk) {
      const r = batch.result[`list_${id}`] as { tasks?: B24TaskRaw[] } | undefined;
      results.set(id, r?.tasks ?? []);
    }
  }
  return results;
}

export async function b24BatchFetchTags(taskIds: string[]): Promise<Map<string, string[]>> {
  const results = new Map<string, string[]>();
  if (taskIds.length === 0) return results;

  for (let i = 0; i < taskIds.length; i += B24_BATCH_LIMIT) {
    const chunk = taskIds.slice(i, i + B24_BATCH_LIMIT);
    const commands: Record<string, string> = {};
    for (const id of chunk) {
      commands[`tags_${id}`] = `task.item.getdata?TASKID=${id}`;
    }
    const batch = await b24Batch<Record<string, unknown>>(commands);
    for (const id of chunk) {
      const raw = batch.result[`tags_${id}`] as { TAGS?: string[] } | undefined;
      results.set(id, Array.isArray(raw?.TAGS) ? raw!.TAGS : []);
    }
  }
  return results;
}

export async function b24BatchTasksWithComments(
  taskIds: string[]
): Promise<Map<string, { task: B24TaskRaw; comments: B24CommentRaw[] }>> {
  const results = new Map<string, { task: B24TaskRaw; comments: B24CommentRaw[] }>();
  if (taskIds.length === 0) return results;

  const CHUNK = Math.floor(B24_BATCH_LIMIT / 2); // 25 tasks × 2 cmds = 50
  for (let i = 0; i < taskIds.length; i += CHUNK) {
    const chunk = taskIds.slice(i, i + CHUNK);
    const commands: Record<string, string> = {};
    for (const id of chunk) {
      commands[`task_${id}`] = `tasks.task.get?taskId=${id}&select[0]=*&select[1]=UF_*`;
      commands[`comments_${id}`] = `task.commentitem.getlist?TASKID=${id}&ORDER[ID]=ASC`;
    }

    const batch = await b24Batch<Record<string, unknown>>(commands);

    for (const id of chunk) {
      const taskResult = batch.result[`task_${id}`] as { task: B24TaskRaw } | undefined;
      const commentsResult = batch.result[`comments_${id}`];
      if (taskResult?.task) {
        results.set(id, {
          task: taskResult.task,
          comments: Array.isArray(commentsResult) ? (commentsResult as B24CommentRaw[]) : [],
        });
      }
    }
  }

  return results;
}

export async function b24FetchTaskWithComments(taskId: string): Promise<{
  task: B24TaskRaw;
  comments: B24CommentRaw[];
}> {
  type BatchShape = { task: { task: B24TaskRaw }; comments: B24CommentRaw[] };
  const batch = await b24Batch<BatchShape>({
    task: `tasks.task.get?taskId=${taskId}&select[0]=*&select[1]=UF_*`,
    comments: `task.commentitem.getlist?TASKID=${taskId}&ORDER[ID]=ASC`,
  });

  if (batch.result_error?.task) {
    throw new Error(`B24 batch error for task ${taskId}: ${batch.result_error.task}`);
  }

  const taskResult = batch.result.task as { task: B24TaskRaw };
  const commentsResult = batch.result.comments;
  return {
    task: taskResult.task,
    comments: Array.isArray(commentsResult) ? (commentsResult as B24CommentRaw[]) : [],
  };
}

export async function b24UpdateEstimate(taskId: string, estimateSeconds: number): Promise<string> {
  return b24Call<string>("tasks.task.update", {
    taskId,
    fields: {
      TIME_ESTIMATE: estimateSeconds.toString(),
    },
  });
}

export async function b24UpdateStatus(taskId: string, status: string): Promise<string> {
  return b24Call<string>("tasks.task.update", {
    taskId,
    fields: {
      STATUS: status,
    },
  });
}

export async function b24UpdateStage(taskId: string, stageId: string): Promise<string> {
  return b24Call<string>("tasks.task.update", {
    taskId,
    fields: {
      STAGE_ID: stageId,
    },
  });
}

export function buildDiskAttachUrl(attachedId: string, action: "show" | "download"): string {
  const m = env.webhookUrl?.replace(/\/$/, "").match(/\/rest\/(\d+)\/([^/]+)/);
  const auth = m ? `auth%5Baplogin%5D=${m[1]}&auth%5Bap%5D=${m[2]}` : "";
  return `${env.baseUrl}/bitrix/tools/disk/uf.php?attachedId=${attachedId}&${auth}&action=${action}&ncc=1`;
}

