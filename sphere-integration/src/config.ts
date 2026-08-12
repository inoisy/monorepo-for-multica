import { config } from "dotenv";
config();

import { b24GetStages, b24GetGroup } from "./api/b24-client.js";

function parseIntList(raw: string | undefined): number[] {
  if (!raw) return [];
  return raw.split(",").map(s => parseInt(s.trim(), 10)).filter(n => !isNaN(n));
}

const _webhookUrl = process.env.B24_WEBHOOK_URL ?? "";
// Extract user ID from webhook URL: /rest/<USER_ID>/<TOKEN>/
const _autoUserId = _webhookUrl.match(/\/rest\/(\d+)\//)?.[1] ?? "";

export const env = {
  baseUrl: process.env.SPHERE_BASE_URL ?? "https://sphere.loodsen.ru",
  webhookUrl: _webhookUrl,
  userId: process.env.B24_USER_ID || _autoUserId,
  groupIds: parseIntList(process.env.B24_GROUP_IDS),
  tasksRepoPath: process.env.TASKS_REPO_PATH ?? "",
  webhookSecret: process.env.WEBHOOK_SECRET ?? "",
};

export async function checkNetwork(): Promise<void> {
  const url = env.baseUrl;
  try {
    await fetch(url, { method: "HEAD", signal: AbortSignal.timeout(5000) });
  } catch {
    throw new Error(`Network unreachable: ${url}`);
  }
}

const _openStageIdsFallback = parseIntList(process.env.B24_OPEN_STAGE_IDS);

// SYSTEM_TYPE "NEW" = open, "WORK" = in-progress (rarely set in group stages — most use null)
const OPEN_SYSTEM_TYPES = new Set(["NEW", "WORK"]);
// Title patterns for custom stages that B24 marks as null SYSTEM_TYPE
const _openTitlePatterns = (process.env.B24_OPEN_STAGE_TITLES ?? "В работе")
  .split(",").map(s => s.trim().toLowerCase()).filter(Boolean);

// Live bindings — updated by initStages() at startup. Fallback to env until then.
export let openStageIds: number[] = _openStageIdsFallback;
export let stageNameToIds: Record<string, number[]> = {};
export let allStageNames: string[] = [];
export let stageIdToName: Map<string, string> = new Map();
export const groupIdToName: Map<string, string> = new Map();

export async function initGroups(): Promise<void> {
  const groupIds = env.groupIds;
  if (groupIds.length === 0) return;
  try {
    const results = await Promise.all(groupIds.map((id) => b24GetGroup(id)));
    for (let i = 0; i < groupIds.length; i++) {
      const name = results[i]?.NAME;
      if (name) groupIdToName.set(String(groupIds[i]), name);
    }
  } catch (err) {
    console.warn("Failed to init group names from API:", err);
  }
}

export async function initStages(): Promise<void> {
  const groupIds = env.groupIds;
  if (groupIds.length === 0) {
    console.warn("B24_GROUP_IDS not set — cannot fetch group stages. Set B24_GROUP_IDS=<id1>,<id2>.");
    return;
  }
  try {
    const allMaps = await Promise.all(groupIds.map((id) => b24GetStages(id)));
    const nameToIds: Record<string, number[]> = {};
    const idToName = new Map<string, string>();
    const found: number[] = [];
    for (const stagesMap of allMaps) {
      for (const [id, stage] of stagesMap.entries()) {
        const numId = parseInt(id, 10);
        if (isNaN(numId)) continue;
        const title = stage.TITLE;
        if (!nameToIds[title]) nameToIds[title] = [];
        nameToIds[title].push(numId);
        idToName.set(id, title);
        const isOpenByType = stage.SYSTEM_TYPE != null && OPEN_SYSTEM_TYPES.has(stage.SYSTEM_TYPE);
        const isOpenByTitle = _openTitlePatterns.some((p) => title.toLowerCase().includes(p));
        if (isOpenByType || isOpenByTitle) {
          found.push(numId);
        }
      }
    }
    stageNameToIds = nameToIds;
    stageIdToName = idToName;
    allStageNames = Object.keys(nameToIds);
    openStageIds = found.length > 0 ? found : _openStageIdsFallback;
  } catch (err) {
    console.warn("Failed to init stages from API, using fallback:", err);
  }
}
