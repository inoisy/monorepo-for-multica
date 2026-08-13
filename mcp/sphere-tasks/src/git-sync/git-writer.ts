import { execSync } from "child_process";
import { writeFileSync, mkdirSync, existsSync, readFileSync } from "fs";
import { join } from "path";
import { logger } from "../utils/logger.js";

export class GitWriter {
  constructor(private readonly repoPath: string) {
    if (!existsSync(repoPath)) {
      throw new Error(`TASKS_REPO_PATH not found: ${repoPath}`);
    }
  }

  private exec(cmd: string): string {
    return execSync(cmd, { cwd: this.repoPath, encoding: "utf8" });
  }

  private hasStagedChanges(): boolean {
    return this.exec("git status --porcelain").trim().length > 0;
  }

  writeTask(slug: string, files: Record<string, string>, commitMsg: string): boolean {
    const taskDir = join(this.repoPath, "tasks", slug);
    mkdirSync(taskDir, { recursive: true });

    for (const [filename, content] of Object.entries(files)) {
      writeFileSync(join(taskDir, filename), content, "utf8");
    }

    this.exec(`git add tasks/${slug}`);

    if (!this.hasStagedChanges()) {
      logger.info(`git-sync: no changes for ${slug}`);
      return false;
    }

    this.exec(`git commit -m ${JSON.stringify(commitMsg)}`);

    try {
      this.exec("git push");
    } catch {
      // push fails if no remote — ok for local-only setup
      logger.warn("git-sync: push skipped (no remote configured)");
    }

    logger.success(`git-sync: committed ${slug}`);
    return true;
  }

  updateMeta(syncedIds: string[]): void {
    const metaDir = join(this.repoPath, "_meta");
    mkdirSync(metaDir, { recursive: true });

    const timestamp = new Date().toISOString();
    const meta = { lastSync: timestamp, syncedTasks: syncedIds };

    writeFileSync(join(metaDir, "last-sync.json"), JSON.stringify(meta, null, 2) + "\n", "utf8");

    const logPath = join(metaDir, "SYNC-LOG.md");
    const existing = existsSync(logPath) ? readFileSync(logPath, "utf8") : "# Sync Log\n";
    const entry = `- ${timestamp}: ${syncedIds.length} task(s) — ${syncedIds.join(", ")}\n`;
    writeFileSync(logPath, existing + entry, "utf8");

    this.exec("git add _meta/");
    if (this.hasStagedChanges()) {
      this.exec(`git commit -m ${JSON.stringify(`sync: meta [${timestamp}]`)}`);
      try {
        this.exec("git push");
      } catch {
        logger.warn("git-sync: meta push skipped (no remote)");
      }
    }
  }
}
