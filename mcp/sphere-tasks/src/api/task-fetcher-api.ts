import { env, openStageIds, stageIdToName } from "../config.js";
import { logger } from "../utils/logger.js";
import { stripBBCode, formatSeconds } from "../utils/format.js";
import type { Task, TaskDetail, TaskWithContext, Comment, BodyImage } from "../types.js";
import {
  b24FetchTasks,
  b24FetchTaskWithComments,
  b24BatchTasksWithComments,
  b24BatchListByParent,
  b24BatchFetchTags,
  b24Call,
  buildDiskAttachUrl,
  type B24TaskRaw,
  type B24CommentRaw,
  type B24AttachmentRaw,
} from "./b24-client.js";

const PRIORITY_MAP: Record<string, string> = { "0": "Низкий", "1": "Средний", "2": "Высокий" };
const STATUS_MAP: Record<string, string> = {
  "1": "Новая",
  "2": "Ждёт выполнения",
  "3": "Выполняется",
  "4": "Якобы выполнена",
  "5": "Завершена",
  "6": "Отложена",
};

function extractGroupId(raw: B24TaskRaw): string {
  const g = raw.group as { id?: unknown } | undefined;
  return String(raw.groupId ?? g?.id ?? "");
}

function responsibleName(raw: B24TaskRaw): string {
  const r = raw.responsible;
  if (!r) return "";
  return r.name ?? "";
}

function mapB24ToTask(raw: B24TaskRaw): Task {
  return {
    taskId: String(raw.id),
    title: String(raw.title ?? ""),
    stage: String(raw.stageId ?? ""),
    responsible: responsibleName(raw),
    priority: PRIORITY_MAP[String(raw.priority ?? "1")] ?? String(raw.priority ?? ""),
    deadline: String(raw.deadline ?? ""),
    tags: Array.isArray(raw.tag) ? raw.tag : [],   // tags unavailable via REST API — will be []
    timer: raw.timeSpentInLogs ? formatSeconds(parseInt(String(raw.timeSpentInLogs), 10)) : "",
    timeEstimate: raw.timeEstimate ? formatSeconds(parseInt(String(raw.timeEstimate), 10)) : "",
    detailUrl: `${env.baseUrl}/company/personal/user/${env.userId}/tasks/task/view/${String(raw.id)}/?IFRAME=Y&IFRAME_TYPE=SIDE_SLIDER`,
    groupId: extractGroupId(raw),
  };
}

const IMAGE_EXT = /\.(png|jpe?g|gif|webp|bmp|svg)$/i;

function attachmentToBodyImage(att: B24AttachmentRaw): BodyImage {
  const isImage = IMAGE_EXT.test(att.NAME);
  return {
    src: `${env.baseUrl}${isImage ? att.VIEW_URL : att.DOWNLOAD_URL}`,
    alt: att.NAME,
  };
}

export async function fetchBodyImages(raw: B24TaskRaw): Promise<BodyImage[]> {
  const ids = raw.ufTaskWebdavFiles;
  if (!Array.isArray(ids) || ids.length === 0) return [];

  const settled = await Promise.all(ids.map(async (id) => {
    const attachedId = String(id);
    try {
      const downloadUrl = buildDiskAttachUrl(attachedId, "download");
      const res = await fetch(downloadUrl, { headers: { Range: "bytes=0-0" } });
      if (!res.ok && res.status !== 206) {
        await res.body?.cancel();
        return null;
      }
      await res.body?.cancel();

      const cd = res.headers.get("content-disposition") ?? "";
      const star = cd.match(/filename\*=utf-8''([^;]+)/i)?.[1];
      const plain = cd.match(/filename="([^"]+)"/i)?.[1];
      const name = star ? decodeURIComponent(star) : (plain ?? `attachment-${attachedId}`);

      const isImage = IMAGE_EXT.test(name);
      return { src: buildDiskAttachUrl(attachedId, isImage ? "show" : "download"), alt: name };
    } catch {
      return null;
    }
  }));
  return settled.filter((r): r is BodyImage => r !== null);
}

export function mapCommentsToTyped(rawComments: B24CommentRaw[]): Comment[] {
  return rawComments.map((c) => {
    const images = c.ATTACHED_OBJECTS
      ? Object.values(c.ATTACHED_OBJECTS).map(attachmentToBodyImage)
      : [];
    return {
      author: c.AUTHOR_NAME || String(c.AUTHOR_ID),
      text: stripBBCode(c.POST_MESSAGE ?? ""),
      date: c.POST_DATE ?? "",
      images,
    };
  });
}

export function mapB24ToTaskDetail(raw: B24TaskRaw, comments: Comment[], bodyImages: BodyImage[] = [], stageMap: Map<string, string> = new Map()): TaskDetail {
  const base = mapB24ToTask(raw);
  const stageId = parseInt(String(raw.stageId ?? "0"), 10);
  const stageTitle = stageMap.get(String(stageId)) ?? String(raw.stageId ?? "");
  const parentTaskId = String(raw.parentId ?? "");
  const priority = PRIORITY_MAP[String(raw.priority ?? "1")] ?? String(raw.priority ?? "");

  const sidebarFields: Record<string, string> = {
    "Стадия": stageTitle,
    "Приоритет": priority,
    "Дедлайн": String(raw.deadline ?? ""),
    "Группа": extractGroupId(raw),
    "Оценка": base.timeEstimate,
    "Затрачено": base.timer,
  };

  return {
    ...base,
    status: STATUS_MAP[String(raw.status ?? "1")] ?? String(raw.status ?? ""),
    sidebarFields,
    body: stripBBCode(String(raw.description ?? "")),
    bodyImages,
    comments,
    stageId,
    stageTitle,
    parentTaskId,
    parentTaskTitle: "",
    siblingTasks: [],
    fetchedAt: new Date().toISOString(),
  };
}

export async function fetchFullTaskDetail(taskId: string): Promise<TaskDetail> {
  const [{ task: rawDetail, comments: rawComments }, tagsRaw] = await Promise.all([
    b24FetchTaskWithComments(taskId),
    b24Call<{ TAGS?: string[] }>("task.item.getdata", { TASKID: taskId }).catch(() => ({})),
  ]);
  const bodyImages = await fetchBodyImages(rawDetail);
  const detail = mapB24ToTaskDetail(rawDetail, mapCommentsToTyped(rawComments), bodyImages, stageIdToName);
  detail.tags = Array.isArray((tagsRaw as { TAGS?: string[] }).TAGS) ? (tagsRaw as { TAGS: string[] }).TAGS : detail.tags;
  return detail;
}

export async function fetchSiblingTasks(parentTaskId: string): Promise<TaskDetail[]> {
  if (!parentTaskId) return [];
  const rawSiblings = await b24FetchTasks({
    filter: { PARENT_ID: parentTaskId },
    select: ["*", "UF_*"],
  });
  if (rawSiblings.length === 0) return [];

  const sibIds = rawSiblings.map(r => String(r.id));
  const dataMap = await b24BatchTasksWithComments(sibIds);

  const results = await Promise.all(sibIds.map(async (id) => {
    const data = dataMap.get(id);
    if (!data) return null;
    const bodyImages = await fetchBodyImages(data.task);
    return mapB24ToTaskDetail(data.task, mapCommentsToTyped(data.comments), bodyImages, stageIdToName);
  }));
  return results.filter((r): r is TaskDetail => r !== null);
}

export function populateSiblingIds(detail: TaskDetail, allSiblings: TaskDetail[]): void {
  detail.siblingTasks = allSiblings
    .filter((s) => s.taskId !== detail.taskId)
    .map((s) => ({ id: s.taskId, title: s.title }));
}

export interface TaskBatchSpec {
  taskId: string;
  /** Include parent story + sibling tasks — same meaning as get_task's with_context */
  withContext?: boolean;
}

/** Batch-fetch details + comments + bodyImages for N task IDs. ceil(N/25) HTTP calls. */
async function fetchDetailsBatch(taskIds: string[]): Promise<Map<string, TaskDetail>> {
  const out = new Map<string, TaskDetail>();
  if (taskIds.length === 0) return out;

  const dataMap = await b24BatchTasksWithComments(taskIds);
  await Promise.all(taskIds.map(async (id) => {
    const data = dataMap.get(id);
    if (!data) { logger.warn(`  Task ${id} missing from batch`); return; }
    try {
      const bodyImages = await fetchBodyImages(data.task);
      out.set(id, mapB24ToTaskDetail(data.task, mapCommentsToTyped(data.comments), bodyImages, stageIdToName));
    } catch (err) {
      logger.error(`  Task ${id} bodyImages failed: ${(err as Error).message}`);
    }
  }));
  return out;
}

/** Tags aren't exposed by tasks.task.list/get — batch them via the old-style API and apply in place. */
async function applyTagsBatch(details: Map<string, TaskDetail>): Promise<void> {
  const ids = [...details.keys()];
  if (ids.length === 0) return;
  const tagsMap = await b24BatchFetchTags(ids);
  for (const [id, detail] of details) {
    const tags = tagsMap.get(id);
    if (tags && tags.length > 0) detail.tags = tags;
  }
}

/**
 * Fetch many tasks in one pipeline instead of N per-task round trips.
 *
 * Parents and siblings are deduped across specs — tasks sharing a parent story fetch it once,
 * and a sibling that is itself a requested task is reused rather than refetched.
 * HTTP for ≤25 tasks: 2 without context, ~5 with context.
 *
 * Returns a Map keyed by taskId. Tasks that couldn't be fetched are absent from the map.
 */
export async function fetchTasksBatch(specs: TaskBatchSpec[]): Promise<Map<string, TaskWithContext>> {
  const results = new Map<string, TaskWithContext>();
  if (specs.length === 0) return results;

  // Dedupe by id — if any spec for an id asked for context, it wins
  const wantContext = new Map<string, boolean>();
  for (const spec of specs) {
    wantContext.set(spec.taskId, (wantContext.get(spec.taskId) ?? false) || !!spec.withContext);
  }
  const taskIds = [...wantContext.keys()];

  logger.info(`Batch fetching ${taskIds.length} task(s) (${Math.ceil(taskIds.length / 25)} batch call(s))...`);
  const details = await fetchDetailsBatch(taskIds);

  // All details we touch — main tasks, parents, siblings. Used for the single tags pass.
  const allDetails = new Map(details);
  const lookup = (id: string): TaskDetail | undefined => allDetails.get(id);

  const parentIds = [...new Set(
    taskIds
      .filter((id) => wantContext.get(id) && details.has(id))
      .map((id) => details.get(id)!.parentTaskId)
      .filter(Boolean)
  )];

  const sibIdsByParent = new Map<string, string[]>();

  if (parentIds.length > 0) {
    logger.info(`Batch fetching ${parentIds.length} parent stor(ies) + siblings...`);

    const [fetchedParents, parentListsMap] = await Promise.all([
      fetchDetailsBatch(parentIds.filter((id) => !allDetails.has(id))),
      b24BatchListByParent(parentIds),
    ]);
    for (const [id, detail] of fetchedParents) allDetails.set(id, detail);

    const missingSibIds = new Set<string>();
    for (const parentId of parentIds) {
      const ids = (parentListsMap.get(parentId) ?? []).map((s) => String(s.id));
      sibIdsByParent.set(parentId, ids);
      for (const id of ids) if (!allDetails.has(id)) missingSibIds.add(id);
    }

    const sibDetails = await fetchDetailsBatch([...missingSibIds]);
    for (const [id, detail] of sibDetails) allDetails.set(id, detail);
  }

  await applyTagsBatch(allDetails);

  for (const taskId of taskIds) {
    const task = details.get(taskId);
    if (!task) continue;

    const ctx: TaskWithContext = { task, parentStory: null, relatedTasks: [] };

    if (wantContext.get(taskId) && task.parentTaskId) {
      const parent = lookup(task.parentTaskId);
      if (parent) {
        parent.parentTaskTitle = parent.title;
        ctx.parentStory = parent;
        task.parentTaskTitle = parent.title;
      }
      const siblings = (sibIdsByParent.get(task.parentTaskId) ?? [])
        .map(lookup)
        .filter((s): s is TaskDetail => !!s);
      populateSiblingIds(task, siblings);
      ctx.relatedTasks = siblings.filter((s) => s.taskId !== taskId);
    }

    results.set(taskId, ctx);
  }

  return results;
}

interface FetchMyTasksApiOptions {
  withContext?: boolean;
  withSiblings?: boolean;
  stages?: number[];
  tag?: string;
}

export async function fetchMyTasksViaApi(options: FetchMyTasksApiOptions = {}): Promise<TaskWithContext[]> {
  const {
    withContext = true,
    withSiblings = false,
    stages,
    tag,
  } = options;

  const userId = env.userId;

  logger.info("Fetching task list via Bitrix24 API...");

  // Build filter: stage + responsible by user ID
  const apiFilter: Record<string, unknown> = {};
  if (stages && stages.length > 0) {
    apiFilter["STAGE_ID"] = stages;
  } else if (stages?.length === 0) {
    // empty array = no stage filter (all stages)
  } else {
    apiFilter["STAGE_ID"] = openStageIds;
  }
  if (userId) apiFilter["RESPONSIBLE_ID"] = userId;
  if (tag) apiFilter["TAG"] = tag;

  const rawTasks = await b24FetchTasks({
    filter: apiFilter,
    select: ["*", "UF_*"],
    order: { CREATED_DATE: "DESC" },
  });
  logger.info(`${rawTasks.length} tasks in open stages for user ${userId}`);

  const tasks: Task[] = rawTasks.map(mapB24ToTask);

  if (tasks.length === 0) return [];

  // Fetch full details + comments — batch all tasks in ceil(N/25) HTTP calls
  const taskIds = tasks.map(t => t.taskId);
  logger.info(`Fetching task details + comments (${taskIds.length} tasks, ${Math.ceil(taskIds.length / 25)} batch call(s))...`);

  const dataMap = await b24BatchTasksWithComments(taskIds);

  const failed: string[] = [];
  const myTasksSettled = await Promise.all(tasks.map(async (task) => {
    const data = dataMap.get(task.taskId);
    if (!data) { failed.push(task.taskId); return null; }
    try {
      const bodyImages = await fetchBodyImages(data.task);
      const detail = mapB24ToTaskDetail(data.task, mapCommentsToTyped(data.comments), bodyImages, stageIdToName);
      logger.success(`  Task ${task.taskId}: ${detail.comments.length} comments, ${detail.bodyImages.length} attachments`);
      return detail;
    } catch (err) {
      logger.error(`  Task ${task.taskId} bodyImages failed: ${(err as Error).message}`);
      failed.push(task.taskId);
      return null;
    }
  }));
  const myTasks = myTasksSettled.filter((d): d is TaskDetail => d !== null);

  if (failed.length > 0) logger.warn(`Failed to fetch: ${failed.join(", ")}`);

  // Fetch tags via old-style API (REST API doesn't expose tags)
  if (myTasks.length > 0) {
    logger.info("Fetching tags via task.item.getdata...");
    const tagsMap = await b24BatchFetchTags(myTasks.map(t => t.taskId));
    for (const task of myTasks) {
      const tags = tagsMap.get(task.taskId);
      if (tags && tags.length > 0) task.tags = tags;
    }
  }

  const results: TaskWithContext[] = myTasks.map((task) => ({ task, parentStory: null, relatedTasks: [] }));

  if (!withContext || myTasks.length === 0) return results;

  // Fetch parent stories
  logger.log("");
  logger.info("=== Fetching context (parent stories + sibling tasks) ===");

  const parentIdSet = new Set(myTasks.map(t => t.parentTaskId).filter(Boolean));
  const uniqueParentIds = Array.from(parentIdSet);

  const parentDetails = new Map<string, TaskDetail>();
  if (uniqueParentIds.length > 0) {
    logger.info(`Fetching ${uniqueParentIds.length} parent stor(ies) in batch...`);
    const parentDataMap = await b24BatchTasksWithComments(uniqueParentIds);

    await Promise.all(uniqueParentIds.map(async (parentId) => {
      const data = parentDataMap.get(parentId);
      if (!data) { logger.error(`  Parent ${parentId} missing from batch`); return; }
      try {
        const bodyImages = await fetchBodyImages(data.task);
        const detail = mapB24ToTaskDetail(data.task, mapCommentsToTyped(data.comments), bodyImages, stageIdToName);
        detail.parentTaskTitle = detail.title;
        parentDetails.set(parentId, detail);
        logger.success(`  Parent ${parentId}: ${detail.title.substring(0, 60)}`);
      } catch (err) {
        logger.error(`  Parent ${parentId} failed: ${(err as Error).message}`);
      }
    }));
  }

  for (const result of results) {
    if (result.task.parentTaskId && parentDetails.has(result.task.parentTaskId)) {
      const parent = parentDetails.get(result.task.parentTaskId)!;
      result.parentStory = parent;
      result.task.parentTaskTitle = parent.title;
    }
  }

  // Sibling tasks — batch all parent lookups + all sibling details
  if (withSiblings) {
    const siblingParentIds = Array.from(new Set(myTasks.map(t => t.parentTaskId).filter(Boolean)));
    if (siblingParentIds.length > 0) {
      logger.info(`Fetching siblings for ${siblingParentIds.length} parent(s) in batch...`);

      const parentListsMap = await b24BatchListByParent(siblingParentIds);
      const allSibIds: string[] = [];
      const sibByParent = new Map<string, string[]>();

      for (const parentId of siblingParentIds) {
        const rawSiblings = parentListsMap.get(parentId) ?? [];
        const ids = rawSiblings.map(s => String(s.id));
        sibByParent.set(parentId, ids);
        allSibIds.push(...ids);
      }

      const sibDataMap = await b24BatchTasksWithComments(allSibIds);
      const sibDetailMap = new Map<string, TaskDetail>();

      await Promise.all(allSibIds.map(async (id) => {
        const data = sibDataMap.get(id);
        if (!data) return;
        try {
          const bodyImages = await fetchBodyImages(data.task);
          sibDetailMap.set(id, mapB24ToTaskDetail(data.task, mapCommentsToTyped(data.comments), bodyImages, stageIdToName));
        } catch { /* skip */ }
      }));

      for (const result of results) {
        if (!result.task.parentTaskId) continue;
        const ids = sibByParent.get(result.task.parentTaskId) ?? [];
        result.relatedTasks = ids
          .map(id => sibDetailMap.get(id))
          .filter((s): s is TaskDetail => !!s && s.taskId !== result.task.taskId);
      }

      logger.success(`  ${allSibIds.length} sibling(s) across ${siblingParentIds.length} parent(s)`);
    }
  }

  return results;
}
