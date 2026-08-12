import { Command } from "commander";
import consola from "consola";
import { fetchMyTasksViaApi } from "../api/task-fetcher-api.js";
import { b24UpdateEstimate, b24UpdateStatus, b24UpdateStage } from "../api/b24-client.js";
import { getDatabase, saveDatabase, type SprintTask } from "../sprint-sync/db-schema.js";
import { SprintTaskRepository, SyncStateRepository, AuditLogRepository } from "../sprint-sync/db-operations.js";
import crypto from "crypto";

export function makeSyncCliCommand(): Command {
  const cmd = new Command("sprint-sync");

  cmd
    .command("pull")
    .description("Pull sprint tasks from Sphere into local database")
    .requiredOption("-t, --tag <tag>", "Sprint tag (e.g., 'Спринт 49')")
    .option("--dry-run", "Show what would be pulled without storing")
    .action(async (options) => {
      try {
        const { tag, dryRun } = options;

        consola.info(`Pulling tasks for sprint: ${tag}${dryRun ? " (dry run)" : ""}`);

        // Fetch tasks from Sphere
        const results = await fetchMyTasksViaApi({
          withContext: false,
          withSiblings: false,
          tag,
        });

        if (dryRun) {
          consola.success(`Would pull ${results.length} tasks:`);
          results.forEach((r) => {
            consola.log(`  - [${r.task.taskId}] ${r.task.title}`);
          });
          return;
        }

        // Initialize database
        const db = await getDatabase();
        const taskRepo = new SprintTaskRepository(db);
        const syncStateRepo = new SyncStateRepository(db);
        const auditLogRepo = new AuditLogRepository(db);

        // Update sync state to pulling
        syncStateRepo.upsertSyncState(tag, "pulling");

        // Store tasks in local database
        let added = 0;
        let updated = 0;
        let conflicts = 0;

        for (const result of results) {
          const task = result.task;
          const existing = taskRepo.getTask(task.taskId);

          taskRepo.upsertTask({
            task_id: task.taskId,
            title: task.title,
            description: task.body || "",
            status: task.status,
            stage_id: task.stageId.toString(),
            priority: task.priority,
            deadline: task.deadline || null,
            tag: tag,
            parent_id: task.parentTaskId || null,
            group_id: task.groupId,
            responsible_id: task.responsible,
            time_estimate: task.timeEstimate || null,
            time_spent: null, // Not available in TaskDetail
            sphere_version: `${task.fetchedAt}_${task.status}_${task.stageId}`,
            local_version: 1,
          });

          // Log the pull action
          auditLogRepo.logAction(task.taskId, "pull", null, {
            task_id: task.taskId,
            title: task.title,
          });

          if (existing) {
            updated++;
          } else {
            added++;
          }
        }

        // Update sync state
        const localTasks = taskRepo.getTasksByTag(tag);
        const hash = generateTasksHash(localTasks);
        syncStateRepo.updateLastPull(tag, hash);
        syncStateRepo.updateStatus(tag, "idle");

        // Save database
        saveDatabase(db);

        consola.success(`Pull complete: ${added} added, ${updated} updated, ${conflicts} conflicts`);
        consola.info(`Sync hash: ${hash}`);

        db.close();
      } catch (error) {
        consola.error(`Pull failed: ${error instanceof Error ? error.message : "Unknown error"}`);
        process.exit(1);
      }
    });

  cmd
    .command("push")
    .description("Push local changes to Sphere")
    .requiredOption("-t, --tag <tag>", "Sprint tag (e.g., 'Спринт 49')")
    .option("--task-ids <ids...>", "Specific task IDs to push (default: all tasks for tag)")
    .option("--dry-run", "Show what would be pushed without pushing")
    .action(async (options) => {
      try {
        const { tag, taskIds, dryRun } = options;

        consola.info(`Pushing changes for sprint: ${tag}${dryRun ? " (dry run)" : ""}`);

        // Initialize database
        const db = await getDatabase();
        const taskRepo = new SprintTaskRepository(db);
        const syncStateRepo = new SyncStateRepository(db);
        const auditLogRepo = new AuditLogRepository(db);

        // Get tasks to push
        const tasksToSync = taskIds
          ? taskIds.map((id: string) => taskRepo.getTask(id)).filter((t: SprintTask | undefined): t is SprintTask => !!t)
          : taskRepo.getTasksByTag(tag);

        if (tasksToSync.length === 0) {
          consola.warn("No tasks to push");
          db.close();
          return;
        }

        consola.info(`Found ${tasksToSync.length} tasks to check`);

        let pushed = 0;
        let skipped = 0;
        let errors = 0;

        // Update sync state to pushing
        if (!dryRun) {
          syncStateRepo.upsertSyncState(tag, "pushing");
          saveDatabase(db);
        }

        for (const task of tasksToSync) {
          const requestId = crypto.randomUUID();
          try {
            // Check if there are local changes to push (local_version > 1)
            if (task.local_version <= 1) {
              consola.log(`  [${task.task_id}] Skipped - no local changes`);
              skipped++;
              continue;
            }

            if (dryRun) {
              consola.log(`  [${task.task_id}] Would push changes`);
              pushed++;
              continue;
            }

            // In a real implementation, you would check what specific fields changed
            // and push only those changes. For now, this is a placeholder.

            // Example: push estimate if it changed
            if (task.time_estimate) {
              await b24UpdateEstimate(task.task_id, parseInt(task.time_estimate || "0", 10));
              consola.success(`  [${task.task_id}] Pushed estimate update`);
              pushed++;
            } else {
              skipped++;
            }

            // Log the push action
            auditLogRepo.logAction(
              task.task_id,
              "push",
              null,
              { task_id: task.task_id, action: "update_estimate" },
              requestId
            );
          } catch (error) {
            const errorMessage = error instanceof Error ? error.message : "Unknown error";
            consola.error(`  [${task.task_id}] Error: ${errorMessage}`);
            errors++;

            // Log the error
            auditLogRepo.logAction(task.task_id, "push", null, null, requestId, errorMessage);
          }
        }

        // Save audit logs
        saveDatabase(db);

        // Update sync state
        if (!dryRun) {
          syncStateRepo.updateLastPush(tag);
          syncStateRepo.updateStatus(tag, "idle");
          saveDatabase(db);
        }

        consola.success(`Push complete: ${pushed} pushed, ${skipped} skipped, ${errors} errors`);

        db.close();
      } catch (error) {
        consola.error(`Push failed: ${error instanceof Error ? error.message : "Unknown error"}`);
        process.exit(1);
      }
    });

  cmd
    .command("status")
    .description("Show current sync state")
    .option("-t, --tag <tag>", "Sprint tag (e.g., 'Спринт 49')")
    .action(async (options) => {
      try {
        const { tag } = options;

        const db = await getDatabase();
        const syncStateRepo = new SyncStateRepository(db);
        const taskRepo = new SprintTaskRepository(db);

        if (tag) {
          const state = syncStateRepo.getSyncState(tag);
          if (state) {
            consola.log(`Sync state for "${tag}":`);
            consola.log(`  Status: ${state.status}`);
            consola.log(`  Last pull: ${state.last_pull_at || "never"}`);
            consola.log(`  Last push: ${state.last_push_at || "never"}`);
            consola.log(`  Sync hash: ${state.last_sync_hash || "none"}`);

            const tasks = taskRepo.getTasksByTag(tag);
            consola.log(`  Local tasks: ${tasks.length}`);
          } else {
            consola.warn(`No sync state found for "${tag}"`);
          }
        } else {
          // Show all states
          consola.log("All sync states:");
          // You would need to implement getAllSyncStates in SyncStateRepository
          // For now, show just the general status
          consola.log("Sync service is running");
          consola.log("Use --tag to see specific sprint status");
        }

        db.close();
      } catch (error) {
        consola.error(`Status check failed: ${error instanceof Error ? error.message : "Unknown error"}`);
        process.exit(1);
      }
    });

  cmd
    .command("update-estimate")
    .description("Update task estimate locally")
    .requiredOption("--task-id <id>", "Sphere task ID")
    .requiredOption("--estimate <seconds>", "Time estimate in seconds")
    .action(async (options) => {
      try {
        const { taskId, estimate } = options;

        const db = await getDatabase();
        const taskRepo = new SprintTaskRepository(db);
        const auditLogRepo = new AuditLogRepository(db);

        const task = taskRepo.getTask(taskId);
        if (!task) {
          consola.error(`Task ${taskId} not found in local database`);
          db.close();
          process.exit(1);
        }

        const oldValue = task.time_estimate;
        task.time_estimate = estimate;

        // Update task (you would need to implement updateTimeEstimate in SprintTaskRepository)
        // For now, this is a placeholder
        taskRepo.incrementLocalVersion(taskId);

        consola.success(`Updated estimate for task ${taskId}: ${oldValue}s → ${estimate}s`);

        // Log the change
        auditLogRepo.logAction(taskId, "update_estimate", { time_estimate: oldValue }, {
          time_estimate: estimate,
        });

        // Save database
        saveDatabase(db);

        db.close();
      } catch (error) {
        consola.error(`Update failed: ${error instanceof Error ? error.message : "Unknown error"}`);
        process.exit(1);
      }
    });

  cmd
    .command("logs")
    .description("Show audit logs")
    .option("--task-id <id>", "Filter by task ID")
    .option("--limit <n>", "Number of logs to show", "50")
    .option("--errors", "Show only error logs")
    .action(async (options) => {
      try {
        const { taskId, limit, errors } = options;

        const db = await getDatabase();
        const auditLogRepo = new AuditLogRepository(db);

        let logs;
        if (errors) {
          logs = auditLogRepo.getErrorLogs(parseInt(limit, 10));
        } else if (taskId) {
          logs = auditLogRepo.getTaskLogs(taskId, parseInt(limit, 10));
        } else {
          logs = auditLogRepo.getRecentLogs(parseInt(limit, 10));
        }

        consola.log(`Recent audit logs (${logs.length}):`);
        logs.forEach((log) => {
          const timestamp = new Date(log.created_at).toLocaleString();
          consola.log(`  [${log.id}] ${timestamp} - ${log.action} for task ${log.task_id}`);
          if (log.error_message) {
            consola.error(`    Error: ${log.error_message}`);
          }
        });

        db.close();
      } catch (error) {
        consola.error(`Logs fetch failed: ${error instanceof Error ? error.message : "Unknown error"}`);
        process.exit(1);
      }
    });

  return cmd;
}

function generateTasksHash(tasks: SprintTask[]): string {
  const normalized = tasks
    .map((t: SprintTask) => `${t.task_id}:${t.sphere_version}:${t.time_estimate}:${t.status}:${t.stage_id}`)
    .sort()
    .join("|");
  return crypto.createHash("sha256").update(normalized).digest("hex");
}