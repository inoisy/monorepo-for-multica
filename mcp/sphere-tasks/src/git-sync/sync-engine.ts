import { fetchFullTaskDetail, fetchMyTasksViaApi } from "../api/task-fetcher-api.js";
import { logger } from "../utils/logger.js";
import { GitWriter } from "./git-writer.js";
import { formatIndexMd, formatCommentsMd, taskSlug } from "./task-formatter.js";

export class SyncEngine {
  private writer: GitWriter;

  constructor(repoPath: string) {
    this.writer = new GitWriter(repoPath);
  }

  async syncTask(taskId: string): Promise<boolean> {
    logger.info(`sync-engine: fetching task #${taskId}...`);
    const detail = await fetchFullTaskDetail(taskId);
    const slug = taskSlug(detail);
    const timestamp = new Date().toISOString();

    const changed = this.writer.writeTask(
      slug,
      {
        "index.md": formatIndexMd(detail),
        "comments.md": formatCommentsMd(detail),
      },
      `sync: task #${taskId} "${detail.stageTitle}" [${timestamp}]`,
    );

    if (changed) {
      this.writer.updateMeta([taskId]);
    }

    return changed;
  }

  async syncAll(): Promise<string[]> {
    logger.info("sync-engine: fetching all my tasks...");
    const results = await fetchMyTasksViaApi({ withContext: false, withSiblings: false });

    const changed: string[] = [];
    const failed: string[] = [];

    for (const { task } of results) {
      try {
        const slug = taskSlug(task);
        const timestamp = new Date().toISOString();
        const wasChanged = this.writer.writeTask(
          slug,
          {
            "index.md": formatIndexMd(task),
            "comments.md": formatCommentsMd(task),
          },
          `sync: task #${task.taskId} "${task.stageTitle}" [${timestamp}]`,
        );
        if (wasChanged) changed.push(task.taskId);
      } catch (err) {
        logger.error(`sync-engine: task #${task.taskId} failed — ${(err as Error).message}`);
        failed.push(task.taskId);
      }
    }

    if (changed.length > 0) {
      this.writer.updateMeta(changed);
    }

    logger.success(`sync-engine: done. changed=${changed.length} failed=${failed.length}`);
    return changed;
  }
}
