import http from "http";
import { URL } from "url";
import { initStages, env } from "./config.js";
import { logger } from "./utils/logger.js";
import { fetchFullTaskDetail, fetchMyTasksViaApi } from "./api/task-fetcher-api.js";
import { SyncEngine } from "./git-sync/sync-engine.js";

const PORT = parseInt(process.env.WEBHOOK_PORT || "3100", 10);

type B24Event = {
  event: string;
  data: {
    FIELDS?: {
      ID?: string;
      TASK_ID?: string;
      COMMENT_ID?: string;
      BEFORE?: Record<string, string>;
      AFTER?: Record<string, string>;
    };
    [key: string]: unknown;
  };
  [key: string]: unknown;
};

function parseBody(buf: Buffer): Record<string, unknown> {
  const text = buf.toString("utf8");
  try {
    return JSON.parse(text);
  } catch {
    const params = new URLSearchParams(text);
    const obj: Record<string, unknown> = {};
    params.forEach((v, k) => (obj[k] = k.endsWith("[]") ? [...(obj[k] as string[] || []), v] : v));
    return obj;
  }
}

function getSyncEngine(): SyncEngine | null {
  if (!env.tasksRepoPath) return null;
  return new SyncEngine(env.tasksRepoPath);
}

async function handleTaskUpdate(taskId: string): Promise<void> {
  logger.info(`Webhook: refreshing task ${taskId}...`);
  try {
    const detail = await fetchFullTaskDetail(taskId);
    logger.success(`Webhook: task ${taskId} refreshed (stage: ${detail.stageTitle})`);
    getSyncEngine()?.syncTask(taskId).catch((err) =>
      logger.error(`git-sync: task ${taskId} failed — ${(err as Error).message}`)
    );
  } catch (err) {
    logger.error(`Webhook: failed to refresh task ${taskId}: ${(err as Error).message}`);
  }
}

async function handleFullRefresh(): Promise<void> {
  logger.info("Webhook: full refresh triggered...");
  try {
    const results = await fetchMyTasksViaApi({ withContext: false, withSiblings: false });
    logger.success(`Webhook: full refresh done (${results.length} tasks)`);
    getSyncEngine()?.syncAll().catch((err) =>
      logger.error(`git-sync: full refresh failed — ${(err as Error).message}`)
    );
  } catch (err) {
    logger.error(`Webhook: full refresh failed: ${(err as Error).message}`);
  }
}

async function handleRequest(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
  const url = new URL(req.url ?? "/", `http://localhost:${PORT}`);
  const path = url.pathname;

  if (req.method === "GET" && path === "/health") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ status: "ok", uptime: process.uptime() }));
    return;
  }

  if (req.method === "POST" && path === "/webhook/b24") {
    if (env.webhookSecret) {
      const token = req.headers["x-bitrix-token"] ?? url.searchParams.get("auth[application_token]");
      if (token !== env.webhookSecret) {
        res.writeHead(401, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ error: "unauthorized" }));
        return;
      }
    }
    const chunks: Buffer[] = [];
    for await (const chunk of req) chunks.push(chunk as Buffer);
    const body = parseBody(Buffer.concat(chunks));

    const event = body.event as string || body["auth[application_token]"] as string ? "event" : "unknown";
    const fields = (body.data as B24Event["data"])?.FIELDS ?? body;
    const taskId = (fields.ID || fields.TASK_ID || url.searchParams.get("task_id")) as string | undefined;

    logger.info(`Webhook received: event=${event}, taskId=${taskId || "n/a"}`);

    if (taskId) {
      await handleTaskUpdate(String(taskId));
    }

    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ received: true, event, taskId: taskId || null }));
    return;
  }

  if (req.method === "POST" && path === "/webhook/refresh") {
    const taskId = url.searchParams.get("task_id");
    if (taskId) {
      await handleTaskUpdate(taskId);
    } else {
      await handleFullRefresh();
    }
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ refreshed: true, taskId: taskId || "all" }));
    return;
  }

  res.writeHead(404, { "Content-Type": "application/json" });
  res.end(JSON.stringify({ error: "not found" }));
}

await initStages();

const server = http.createServer(handleRequest);

server.listen(PORT, () => {
  logger.log(`\n  🪝 Sphere webhook server running on http://localhost:${PORT}`);
  logger.log(`\n  Endpoints:`);
  logger.log(`    GET  /health                  — health check`);
  logger.log(`    POST /webhook/b24             — Bitrix24 outgoing webhook`);
  logger.log(`    POST /webhook/refresh         — refresh cache (all or ?task_id=N)`);
  logger.log(`    POST /webhook/sync-multica    — removed (sync-multica.ts does not exist)`);
  logger.log(`\n  Usage with ngrok:`);
  logger.log(`    ngrok http ${PORT}`);
  logger.log(`    Then configure B24 webhook: https://<ngrok-id>.ngrok.io/webhook/b24\n`);
});
