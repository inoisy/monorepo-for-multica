import { logger } from "../utils/logger.js";
import type { TaskDetail, TaskWithContext } from "../types.js";

export function taskRolePrefix(task: TaskDetail): string {
  if (task.title.startsWith("[FE]")) return "FE";
  if (task.title.startsWith("[BE]")) return "BE";
  if (task.title.startsWith("[QA]")) return "QA";
  return "??";
}

export function getArg(args: string[], name: string): string | undefined {
  const idx = args.indexOf(name);
  return idx >= 0 && args[idx + 1] ? args[idx + 1] : undefined;
}

export function printSummary(results: TaskWithContext[], failed?: string[]): void {
  logger.log("");
  logger.log("=== SUMMARY ===");
  logger.log(`Total tasks:     ${results.length}`);
  logger.log(`With parent:     ${results.filter((r) => r.parentStory).length}`);
  logger.log(`With backend:    ${results.filter((r) => r.relatedTasks.length > 0).length}`);
  if (failed && failed.length > 0) {
    logger.log(`Failed:          ${failed.length}`);
  }
  logger.log("");
  for (const r of results) {
    const prefix = taskRolePrefix(r.task);
    const stage = r.task.stageTitle || r.task.status;
    logger.log(`  [${prefix}] #${r.task.taskId} ${r.task.title.substring(0, 70)}`);
    logger.log(`        Stage: ${stage} | Comments: ${r.task.comments.length}`);
    if (r.parentStory) {
      logger.log(`        Story: #${r.parentStory.taskId} ${r.parentStory.title.substring(0, 60)}`);
    }
    if (r.relatedTasks.length > 0) {
      logger.log(`        Backend: ${r.relatedTasks.map((t) => `#${t.taskId}`).join(", ")}`);
    }
  }
}

export function printHelp(): void {
  logger.log(`
sphere-tasks v2.0 — API-only task fetcher for Sphere (Bitrix24)

Commands:
  fetch-my-tasks-api  Fetch my tasks via Bitrix24 REST API
    --with-siblings     Fetch backend sibling tasks
    --no-context        Skip fetching parent story context
    --responsible <s>   Filter by responsible name
    --all-stages        Include all stages (default: only open + in-progress)
    --stage <ids>       Comma-separated stage IDs override
  webhook             Start HTTP server for Bitrix24 outgoing webhooks (port 3100)

MCP server:
  node dist/mcp-server.js   (stdio transport, started by agent)

Environment:
  B24_WEBHOOK_URL    Bitrix24 REST webhook URL (required)
  B24_USER_ID        Bitrix24 user ID (auto-extracted from B24_WEBHOOK_URL)
  B24_RESPONSIBLE    Filter by responsible name
  SPHERE_BASE_URL    Base URL (default: https://sphere.loodsen.ru)
  MCP_WRITE_ENABLED  Enable write operations (default: false)
`);
}