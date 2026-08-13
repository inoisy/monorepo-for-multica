import { initStages, env } from "../config.js";
import { logger } from "../utils/logger.js";
import { SyncEngine } from "../git-sync/sync-engine.js";

export async function runSync(taskId?: string): Promise<void> {
  if (!env.tasksRepoPath) {
    logger.error("TASKS_REPO_PATH not set. Add it to .env");
    process.exit(1);
  }

  await initStages();
  const engine = new SyncEngine(env.tasksRepoPath);

  if (taskId) {
    logger.info(`Syncing task #${taskId}...`);
    const changed = await engine.syncTask(taskId);
    logger.success(changed ? `Task #${taskId} synced.` : `Task #${taskId} — no changes.`);
  } else {
    logger.info("Full sync — all my tasks...");
    const changed = await engine.syncAll();
    logger.success(`Full sync done. ${changed.length} task(s) updated.`);
  }
}
