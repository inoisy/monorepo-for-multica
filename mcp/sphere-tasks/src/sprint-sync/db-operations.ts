import type { Database } from "sql.js";
import type { SprintTask, SyncState, AuditLog } from "./db-schema.js";

export class SprintTaskRepository {
  constructor(private db: Database) {}

  // Upsert a sprint task
  upsertTask(task: Omit<SprintTask, "id" | "created_at" | "updated_at" | "synced_at">): void {
    const existing = this.db.exec(`SELECT * FROM sprint_task WHERE task_id = '${task.task_id}'`);

    if (existing.length > 0 && existing[0].values.length > 0) {
      // Update existing task
      this.db.run(`
        UPDATE sprint_task
        SET title = ?,
            description = ?,
            status = ?,
            stage_id = ?,
            priority = ?,
            deadline = ?,
            tag = ?,
            parent_id = ?,
            group_id = ?,
            responsible_id = ?,
            time_estimate = ?,
            time_spent = ?,
            sphere_version = ?,
            synced_at = datetime('now')
        WHERE task_id = ?
      `, [
        task.title,
        task.description,
        task.status,
        task.stage_id,
        task.priority,
        task.deadline,
        task.tag,
        task.parent_id,
        task.group_id,
        task.responsible_id,
        task.time_estimate,
        task.time_spent,
        task.sphere_version,
        task.task_id
      ]);
    } else {
      // Insert new task
      this.db.run(`
        INSERT INTO sprint_task (
          task_id, title, description, status, stage_id, priority,
          deadline, tag, parent_id, group_id, responsible_id,
          time_estimate, time_spent, sphere_version, local_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
      `, [
        task.task_id,
        task.title,
        task.description,
        task.status,
        task.stage_id,
        task.priority,
        task.deadline,
        task.tag,
        task.parent_id,
        task.group_id,
        task.responsible_id,
        task.time_estimate,
        task.time_spent,
        task.sphere_version
      ]);
    }
  }

  // Get task by Sphere task ID
  getTask(taskId: string): SprintTask | undefined {
    const results = this.db.exec(`SELECT * FROM sprint_task WHERE task_id = '${taskId}'`);
    if (results.length === 0 || results[0].values.length === 0) {
      return undefined;
    }

    return this.mapRowToTask(results[0].values[0] as any[]);
  }

  // Get all tasks for a specific tag
  getTasksByTag(tag: string): SprintTask[] {
    const results = this.db.exec(`SELECT * FROM sprint_task WHERE tag = '${tag}' ORDER BY created_at`);
    if (results.length === 0) {
      return [];
    }

    return results[0].values.map((row) => this.mapRowToTask(row as any[]));
  }

  // Get all tasks (with optional tag filter)
  getAllTasks(tag?: string): SprintTask[] {
    if (tag) {
      return this.getTasksByTag(tag);
    }
    const results = this.db.exec(`SELECT * FROM sprint_task ORDER BY created_at`);
    if (results.length === 0) {
      return [];
    }

    return results[0].values.map((row) => this.mapRowToTask(row as any[]));
  }

  // Update local version after local changes
  incrementLocalVersion(taskId: string): void {
    this.db.run(`UPDATE sprint_task SET local_version = local_version + 1 WHERE task_id = '${taskId}'`);
  }

  // Helper method to map database row to SprintTask interface
  private mapRowToTask(row: any[]): SprintTask {
    const [id, task_id, title, description, status, stage_id, priority, deadline, tag, parent_id, group_id, responsible_id, time_estimate, time_spent, sphere_version, local_version, created_at, updated_at, synced_at] = row;

    return {
      id: id as number,
      task_id: task_id as string,
      title: title as string,
      description: description as string,
      status: status as string,
      stage_id: stage_id as string,
      priority: priority as string,
      deadline: deadline as string | null,
      tag: tag as string | null,
      parent_id: parent_id as string | null,
      group_id: group_id as string,
      responsible_id: responsible_id as string,
      time_estimate: time_estimate as string | null,
      time_spent: time_spent as string | null,
      sphere_version: sphere_version as string,
      local_version: local_version as number,
      created_at: created_at as string,
      updated_at: updated_at as string,
      synced_at: synced_at as string,
    };
  }
}

export class SyncStateRepository {
  constructor(private db: Database) {}

  // Get sync state for a tag
  getSyncState(tag: string): SyncState | undefined {
    const results = this.db.exec(`SELECT * FROM sync_state WHERE tag = '${tag}'`);
    if (results.length === 0 || results[0].values.length === 0) {
      return undefined;
    }

    return this.mapRowToSyncState(results[0].values[0] as any[]);
  }

  // Create or update sync state
  upsertSyncState(tag: string, status: SyncState["status"] = "idle"): void {
    const existing = this.getSyncState(tag);
    if (existing) {
      this.db.run(`
        UPDATE sync_state
        SET status = ?, updated_at = datetime('now')
        WHERE tag = ?
      `, [status, tag]);
    } else {
      this.db.run(`
        INSERT INTO sync_state (tag, status)
        VALUES (?, ?)
      `, [tag, status]);
    }
  }

  // Update last pull time
  updateLastPull(tag: string, hash?: string): void {
    this.db.run(`
      UPDATE sync_state
      SET last_pull_at = datetime('now'),
          last_sync_hash = ?,
          updated_at = datetime('now')
      WHERE tag = ?
    `, [hash || null, tag]);
  }

  // Update last push time
  updateLastPush(tag: string): void {
    this.db.run(`
      UPDATE sync_state
      SET last_push_at = datetime('now'),
          updated_at = datetime('now')
      WHERE tag = ?
    `, [tag]);
  }

  // Update status
  updateStatus(tag: string, status: SyncState["status"]): void {
    this.db.run(`UPDATE sync_state SET status = ?, updated_at = datetime('now') WHERE tag = ?`, [status, tag]);
  }

  // Helper method to map database row to SyncState interface
  private mapRowToSyncState(row: any[]): SyncState {
    const [id, tag, last_pull_at, last_push_at, last_sync_hash, status] = row;

    return {
      id: id as number,
      tag: tag as string,
      last_pull_at: last_pull_at as string | null,
      last_push_at: last_push_at as string | null,
      last_sync_hash: last_sync_hash as string | null,
      status: status as SyncState["status"],
    };
  }
}

export class AuditLogRepository {
  constructor(private db: Database) {}

  // Log an action
  logAction(
    taskId: string,
    action: AuditLog["action"],
    oldValue: Record<string, unknown> | null = null,
    newValue: Record<string, unknown> | null = null,
    sphereRequestId: string | null = null,
    errorMessage: string | null = null
  ): void {
    this.db.run(`
      INSERT INTO audit_log (task_id, action, old_value, new_value, sphere_request_id, error_message)
      VALUES (?, ?, ?, ?, ?, ?)
    `, [
      taskId,
      action,
      oldValue ? JSON.stringify(oldValue) : null,
      newValue ? JSON.stringify(newValue) : null,
      sphereRequestId,
      errorMessage
    ]);
  }

  // Get audit logs for a task
  getTaskLogs(taskId: string, limit = 100): AuditLog[] {
    const results = this.db.exec(`SELECT * FROM audit_log WHERE task_id = '${taskId}' ORDER BY created_at DESC LIMIT ${limit}`);
    if (results.length === 0) {
      return [];
    }

    return results[0].values.map((row) => this.mapRowToAuditLog(row as any[]));
  }

  // Get recent audit logs (all tasks)
  getRecentLogs(limit = 100): AuditLog[] {
    const results = this.db.exec(`SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ${limit}`);
    if (results.length === 0) {
      return [];
    }

    return results[0].values.map((row) => this.mapRowToAuditLog(row as any[]));
  }

  // Get audit logs with errors
  getErrorLogs(limit = 100): AuditLog[] {
    const results = this.db.exec(`SELECT * FROM audit_log WHERE error_message IS NOT NULL ORDER BY created_at DESC LIMIT ${limit}`);
    if (results.length === 0) {
      return [];
    }

    return results[0].values.map((row) => this.mapRowToAuditLog(row as any[]));
  }

  // Helper method to map database row to AuditLog interface
  private mapRowToAuditLog(row: any[]): AuditLog {
    const [id, task_id, action, old_value, new_value, sphere_request_id, created_at, error_message] = row;

    return {
      id: id as number,
      task_id: task_id as string,
      action: action as AuditLog["action"],
      old_value: old_value as string | null,
      new_value: new_value as string | null,
      sphere_request_id: sphere_request_id as string | null,
      created_at: created_at as string,
      error_message: error_message as string | null,
    };
  }
}