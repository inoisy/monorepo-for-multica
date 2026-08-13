import express from "express";
import { getDatabase, saveDatabase, type SprintTask } from "./db-schema.js";
import { SprintTaskRepository, SyncStateRepository, AuditLogRepository } from "./db-operations.js";
import { fetchMyTasksViaApi } from "../api/task-fetcher-api.js";
import { b24UpdateEstimate, b24UpdateStatus, b24UpdateStage } from "../api/b24-client.js";
import crypto from "crypto";

const app = express();
app.use(express.json());

let db: Awaited<ReturnType<typeof getDatabase>> | null = null;
let taskRepo: SprintTaskRepository | null = null;
let syncStateRepo: SyncStateRepository | null = null;
let auditLogRepo: AuditLogRepository | null = null;

// Initialize database connection
async function initDatabase(): Promise<void> {
  if (!db) {
    db = await getDatabase();
    taskRepo = new SprintTaskRepository(db);
    syncStateRepo = new SyncStateRepository(db);
    auditLogRepo = new AuditLogRepository(db);
  }
}

// Generate a hash from array of tasks for change detection
function generateTasksHash(tasks: SprintTask[]): string {
  const normalized = tasks
    .map((t) => `${t.task_id}:${t.sphere_version}:${t.time_estimate}:${t.status}:${t.stage_id}`)
    .sort()
    .join("|");
  return crypto.createHash("sha256").update(normalized).digest("hex");
}

// GET /api/sprint/snapshot - Get current local snapshot
app.get("/api/sprint/snapshot", async (req, res) => {
  try {
    await initDatabase();
    const tag = req.query.tag as string | undefined;
    const tasks = taskRepo!.getAllTasks(tag);

    res.json({
      success: true,
      data: {
        tasks,
        count: tasks.length,
        tag: tag || "all",
        generated_at: new Date().toISOString(),
      },
    });
  } catch (error) {
    console.error("Error fetching snapshot:", error);
    res.status(500).json({
      success: false,
      error: error instanceof Error ? error.message : "Unknown error",
    });
  }
});

// POST /api/sprint/sync/pull - Pull tasks from Sphere
app.post("/api/sprint/sync/pull", async (req, res) => {
  const tag = req.body.tag as string;
  if (!tag) {
    return res.status(400).json({
      success: false,
      error: "tag is required in request body",
    });
  }

  try {
    await initDatabase();

    // Update sync state to pulling
    syncStateRepo!.upsertSyncState(tag, "pulling");

    // Fetch tasks from Sphere
    const results = await fetchMyTasksViaApi({
      withContext: false,
      withSiblings: false,
      tag,
    });

    // Store tasks in local database
    for (const result of results) {
      const task = result.task;
      taskRepo!.upsertTask({
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
        sphere_version: `${task.fetchedAt}_${task.status}_${task.stageId}`, // Version from Sphere
        local_version: 1,
      });

      // Log the pull action
      auditLogRepo!.logAction(task.taskId, "pull", null, { task_id: task.taskId, title: task.title });
    }

    // Save database to disk
    saveDatabase(db!);

    // Update sync state
    const localTasks = taskRepo!.getTasksByTag(tag);
    const hash = generateTasksHash(localTasks);
    syncStateRepo!.updateLastPull(tag, hash);
    syncStateRepo!.updateStatus(tag, "idle");

    // Save again after sync state update
    saveDatabase(db!);

    res.json({
      success: true,
      data: {
        pulled: results.length,
        tag: tag,
        tasks: localTasks,
        sync_hash: hash,
        pulled_at: new Date().toISOString(),
      },
    });
  } catch (error) {
    console.error("Error pulling from Sphere:", error);
    if (syncStateRepo) {
      syncStateRepo.updateStatus(tag, "idle");
      saveDatabase(db!);
    }

    res.status(500).json({
      success: false,
      error: error instanceof Error ? error.message : "Unknown error",
      tag: tag,
    });
  }
});

// POST /api/sprint/sync/push - Push changes to Sphere
app.post("/api/sprint/sync/push", async (req, res) => {
  const tag = req.body.tag as string;
  const taskIds = req.body.task_ids as string[] | undefined;

  if (!tag) {
    return res.status(400).json({
      success: false,
      error: "tag is required in request body",
    });
  }

  try {
    await initDatabase();

    // Update sync state to pushing
    syncStateRepo!.upsertSyncState(tag, "pushing");
    saveDatabase(db!);

    // Get tasks to push
    const tasksToSync = taskIds
      ? taskIds.map((id) => taskRepo!.getTask(id)).filter((t): t is SprintTask => !!t)
      : taskRepo!.getTasksByTag(tag);

    if (tasksToSync.length === 0) {
      syncStateRepo!.updateStatus(tag, "idle");
      saveDatabase(db!);
      return res.json({
        success: true,
        data: {
          pushed: 0,
          tag: tag,
          message: "No tasks to push",
          pushed_at: new Date().toISOString(),
        },
      });
    }

    const results: Array<{ task_id: string; success: boolean; action: string; error?: string }> = [];

    // Push each task to Sphere
    for (const task of tasksToSync) {
      const requestId = crypto.randomUUID();
      try {
        // Check if there are local changes to push (local_version > 1)
        if (task.local_version <= 1) {
          results.push({
            task_id: task.task_id,
            success: true,
            action: "skipped",
            error: "No local changes",
          });
          continue;
        }

        // Here we would normally compare with Sphere version to detect conflicts
        // For now, we'll push estimates, status, and stage if they've changed

        let actionPerformed = "none";

        // Example: push estimate change (you would need to track what changed)
        // This is a simplified version - in production you'd track specific fields
        if (task.time_estimate) {
          await b24UpdateEstimate(task.task_id, parseInt(task.time_estimate || "0", 10));
          actionPerformed = "update_estimate";
        }

        // Log the push action
        auditLogRepo!.logAction(
          task.task_id,
          "push",
          null,
          { task_id: task.task_id, action: actionPerformed },
          requestId
        );

        results.push({
          task_id: task.task_id,
          success: true,
          action: actionPerformed,
        });
      } catch (error) {
        const errorMessage = error instanceof Error ? error.message : "Unknown error";
        console.error(`Error pushing task ${task.task_id}:`, error);

        // Log the error
        auditLogRepo!.logAction(
          task.task_id,
          "push",
          null,
          null,
          requestId,
          errorMessage
        );

        results.push({
          task_id: task.task_id,
          success: false,
          action: "error",
          error: errorMessage,
        });
      }
    }

    // Save audit logs
    saveDatabase(db!);

    // Update sync state
    syncStateRepo!.updateLastPush(tag);
    syncStateRepo!.updateStatus(tag, "idle");
    saveDatabase(db!);

    const successCount = results.filter((r) => r.success).length;
    const errorCount = results.filter((r) => !r.success).length;

    res.json({
      success: true,
      data: {
        pushed: successCount,
        errors: errorCount,
        tag: tag,
        results: results,
        pushed_at: new Date().toISOString(),
      },
    });
  } catch (error) {
    console.error("Error pushing to Sphere:", error);
    if (syncStateRepo) {
      syncStateRepo!.updateStatus(tag, "idle");
      saveDatabase(db!);
    }

    res.status(500).json({
      success: false,
      error: error instanceof Error ? error.message : "Unknown error",
      tag: tag,
    });
  }
});

// GET /api/sync/state - Get current sync state
app.get("/api/sync/state", async (req, res) => {
  try {
    await initDatabase();
    const tag = req.query.tag as string | undefined;
    const state = tag ? syncStateRepo!.getSyncState(tag) : undefined;

    res.json({
      success: true,
      data: {
        state: state || null,
        tag: tag || "not specified",
      },
    });
  } catch (error) {
    console.error("Error fetching sync state:", error);
    res.status(500).json({
      success: false,
      error: error instanceof Error ? error.message : "Unknown error",
    });
  }
});

// GET /api/audit/logs - Get audit logs
app.get("/api/audit/logs", async (req, res) => {
  try {
    await initDatabase();
    const taskId = req.query.task_id as string | undefined;
    const limit = parseInt((req.query.limit as string) || "100", 10);

    const logs = taskId ? auditLogRepo!.getTaskLogs(taskId, limit) : auditLogRepo!.getRecentLogs(limit);

    res.json({
      success: true,
      data: {
        logs,
        count: logs.length,
        task_filter: taskId || "all",
      },
    });
  } catch (error) {
    console.error("Error fetching audit logs:", error);
    res.status(500).json({
      success: false,
      error: error instanceof Error ? error.message : "Unknown error",
    });
  }
});

// Health check endpoint
app.get("/health", (req, res) => {
  res.json({
    status: "ok",
    service: "sprint-sync",
    timestamp: new Date().toISOString(),
  });
});

export function startServer(port = 3000): void {
  app.listen(port, () => {
    console.log(`Sprint sync API server running on port ${port}`);
    console.log(`Endpoints:`);
    console.log(`  GET  /api/sprint/snapshot      - Get local task snapshot`);
    console.log(`  POST /api/sprint/sync/pull     - Pull tasks from Sphere`);
    console.log(`  POST /api/sprint/sync/push     - Push changes to Sphere`);
    console.log(`  GET  /api/sync/state          - Get sync state`);
    console.log(`  GET  /api/audit/logs          - Get audit logs`);
    console.log(`  GET  /health                   - Health check`);
  });
}

export { app };