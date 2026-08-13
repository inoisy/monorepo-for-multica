import initSqlJs, { Database, type SqlJsStatic } from "sql.js";
import path from "path";
import { fileURLToPath } from "url";
import { readFileSync, writeFileSync, existsSync, mkdirSync } from "fs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DB_DIR = path.join(__dirname, "../../../data");
const DB_PATH = path.join(DB_DIR, "sprint-sync.db");

// Ensure data directory exists
if (!existsSync(DB_DIR)) {
  mkdirSync(DB_DIR, { recursive: true });
}

let sqlJs: SqlJsStatic | null = null;

async function initSqlJsModule(): Promise<SqlJsStatic> {
  if (!sqlJs) {
    sqlJs = await initSqlJs({
      // Load WebAssembly binary
      // For Node.js environment, sql.js will automatically locate the wasm file
    });
  }
  return sqlJs;
}

export interface SprintTask {
  id: number; // Local primary key
  task_id: string; // Sphere task ID
  title: string;
  description: string;
  status: string;
  stage_id: string;
  priority: string;
  deadline: string | null;
  tag: string | null; // Sprint tag (e.g., "Спринт 49")
  parent_id: string | null;
  group_id: string;
  responsible_id: string;
  time_estimate: string | null; // Seconds
  time_spent: string | null; // Seconds
  sphere_version: string; // Version from Sphere for conflict detection
  local_version: number; // Local version for conflict detection
  created_at: string;
  updated_at: string;
  synced_at: string; // Last sync with Sphere
}

export interface SyncState {
  id: number;
  tag: string; // Sprint tag
  last_pull_at: string | null;
  last_push_at: string | null;
  last_sync_hash: string | null; // Hash of all tasks for change detection
  status: "idle" | "pulling" | "pushing" | "conflict";
}

export interface AuditLog {
  id: number;
  task_id: string; // Sphere task ID
  action: "pull" | "push" | "conflict" | "update_estimate" | "update_status" | "update_stage";
  old_value: string | null; // JSON string of previous state
  new_value: string | null; // JSON string of new state
  sphere_request_id: string | null; // MCP request ID for debugging
  created_at: string;
  error_message: string | null;
}

async function createDatabase(): Promise<Database> {
  const SQL = await initSqlJsModule();

  let db: Database;

  // Load existing database or create new one
  if (existsSync(DB_PATH)) {
    const buffer = readFileSync(DB_PATH);
    db = new SQL.Database(buffer);
  } else {
    db = new SQL.Database();
  }

  // Enable foreign keys
  db.run("PRAGMA foreign_keys = ON");

  // Create sprint_task table
  db.run(`
    CREATE TABLE IF NOT EXISTS sprint_task (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      task_id TEXT NOT NULL UNIQUE,
      title TEXT NOT NULL,
      description TEXT,
      status TEXT NOT NULL,
      stage_id TEXT NOT NULL,
      priority TEXT NOT NULL,
      deadline TEXT,
      tag TEXT,
      parent_id TEXT,
      group_id TEXT NOT NULL,
      responsible_id TEXT NOT NULL,
      time_estimate TEXT,
      time_spent TEXT,
      sphere_version TEXT NOT NULL DEFAULT '',
      local_version INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      updated_at TEXT NOT NULL DEFAULT (datetime('now')),
      synced_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
  `);

  // Create sync_state table
  db.run(`
    CREATE TABLE IF NOT EXISTS sync_state (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      tag TEXT NOT NULL UNIQUE,
      last_pull_at TEXT,
      last_push_at TEXT,
      last_sync_hash TEXT,
      status TEXT NOT NULL DEFAULT 'idle',
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
  `);

  // Create audit_log table
  db.run(`
    CREATE TABLE IF NOT EXISTS audit_log (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      task_id TEXT NOT NULL,
      action TEXT NOT NULL,
      old_value TEXT,
      new_value TEXT,
      sphere_request_id TEXT,
      error_message TEXT,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      FOREIGN KEY (task_id) REFERENCES sprint_task(task_id) ON DELETE CASCADE
    )
  `);

  // Create indexes for better query performance
  db.run(`
    CREATE INDEX IF NOT EXISTS idx_sprint_task_tag ON sprint_task(tag);
    CREATE INDEX IF NOT EXISTS idx_sprint_task_task_id ON sprint_task(task_id);
    CREATE INDEX IF NOT EXISTS idx_audit_log_task_id ON audit_log(task_id);
    CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log(created_at);
  `);

  return db;
}

function saveDatabase(db: Database): void {
  const data = db.export();
  const buffer = Buffer.from(data);
  writeFileSync(DB_PATH, buffer);
}

export async function getDatabase(): Promise<Database> {
  return await createDatabase();
}

export { saveDatabase };