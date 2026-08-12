import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { b24AddComment, b24UpdateComment, b24DeleteComment, b24LogTime, b24GetTimeEntries, b24GetTaskTimeTotals, b24DeleteTimeEntry, b24UpdateEstimate, b24UpdateStatus, b24UpdateStage, type B24ElapsedRaw } from "./api/b24-client.js";
import { fetchMyTasksViaApi, fetchTasksBatch } from "./api/task-fetcher-api.js";
import { formatSeconds } from "./utils/format.js";
import { ok, err, isApiConfigured, type McpResult } from "./mcp/utils.js";
import { parseTaskSpecs, MAX_BATCH_TASKS } from "./mcp/batch-args.js";
import { formatTask, formatTaskBrief, formatTaskDetail } from "./mcp/formatters.js";
import { stageNameToIds, allStageNames, groupIdToName, initStages, initGroups } from "./config.js";

const MCP_WRITE_ENABLED = process.env.MCP_WRITE_ENABLED === "true";

function assertWriteEnabled(): void {
  if (!MCP_WRITE_ENABLED) {
    throw new Error("Write operations are disabled by default. Set MCP_WRITE_ENABLED=true to allow.");
  }
}

function buildGetMyTasksTool() {
  const names = allStageNames;
  return {
    name: "get_my_tasks",
    description: "Get my current tasks from Sphere (Bitrix24). Returns compact list by default — use get_task for full single-task detail.",
    inputSchema: {
      type: "object",
      properties: {
        include_body: { type: "boolean", description: "Include task descriptions (default: false)" },
        include_comments: { type: "boolean", description: "Include comments (default: false)" },
        all_stages: { type: "boolean", description: "Include all stages. Default: only open + in-progress." },
        stage_names: names.length > 0
          ? {
            type: "array",
            items: { type: "string", enum: names },
            description: `Filter by stage name. Valid: ${names.join(", ")}.`,
          }
          : { type: "array", items: { type: "string" }, description: "Filter by stage name." },
        tag: { type: "string", description: "Filter by tag (e.g. 'спринт 49'). Exact match." },
      },
    },
  };
}

// Static base tools
const STATIC_BASE_TOOLS = [
  {
    name: "get_task",
    description: "Get a single Sphere task by ID with full detail (description, comments).",
    inputSchema: {
      type: "object",
      properties: {
        task_id: { type: "string", description: "Sphere task ID" },
        with_context: { type: "boolean", description: "Include parent story + sibling tasks (default: false)" },
      },
      required: ["task_id"],
    },
  },
  {
    name: "get_tasks_batch",
    description: "Get several Sphere tasks at once — one Bitrix24 batch instead of N get_task calls. Prefer this over repeated get_task whenever you need 2+ known task IDs. For 'my current tasks' use get_my_tasks instead.",
    inputSchema: {
      type: "object",
      properties: {
        tasks: {
          type: "array",
          description: "Task IDs. Plain string uses the shared settings below; an object overrides them for that task only.",
          minItems: 1,
          maxItems: MAX_BATCH_TASKS,
          items: {
            anyOf: [
              { type: "string", description: "Sphere task ID" },
              {
                type: "object",
                properties: {
                  task_id: { type: "string", description: "Sphere task ID" },
                  with_context: { type: "boolean", description: "Override shared with_context for this task" },
                },
                required: ["task_id"],
              },
            ],
          },
        },
        with_context: {
          type: "boolean",
          description: "Shared default for every task: include parent story + sibling tasks (default: false). Per-task value wins.",
        },
      },
      required: ["tasks"],
    },
  },
  {
    name: "fetch_sphere_static",
    description: "Fetch a file from Sphere URL. Images returned inline; DOCX/XLSX/PDF — text extracted. Optional crop/resize for images.",
    inputSchema: {
      type: "object",
      properties: {
        url: { type: "string", description: "Sphere file URL" },
        crop: {
          type: "object",
          description: "Crop image (pixels)",
          properties: {
            x: { type: "integer" }, y: { type: "integer" },
            width: { type: "integer" }, height: { type: "integer" },
          },
          required: ["x", "y", "width", "height"],
        },
        resize: {
          type: "object",
          description: "Resize image",
          properties: {
            width: { type: "integer" }, height: { type: "integer" },
          },
        },
      },
      required: ["url"],
    },
  },
  {
    name: "get_time",
    description: "Get all time entries on a Sphere task.",
    inputSchema: {
      type: "object",
      properties: {
        task_id: { type: "string", description: "Task ID" },
      },
      required: ["task_id"],
    },
  },
];

// Write tools — only when MCP_WRITE_ENABLED=true
const WRITE_TOOLS = [
  {
    name: "add_comment",
    description: "Add a comment to a Sphere task. Requires MCP_WRITE_ENABLED=true.",
    inputSchema: {
      type: "object",
      properties: {
        task_id: { type: "string", description: "Task ID" },
        message: { type: "string", description: "Comment text (BBCode supported)" },
      },
      required: ["task_id", "message"],
    },
  },
  {
    name: "edit_comment",
    description: "Edit an existing comment. Requires MCP_WRITE_ENABLED=true. Only author can edit.",
    inputSchema: {
      type: "object",
      properties: {
        task_id: { type: "string", description: "Task ID" },
        comment_id: { type: "string", description: "Comment ID" },
        message: { type: "string", description: "New comment text" },
      },
      required: ["task_id", "comment_id", "message"],
    },
  },
  {
    name: "delete_comment",
    description: "Delete a comment. Requires MCP_WRITE_ENABLED=true. Only author can delete.",
    inputSchema: {
      type: "object",
      properties: {
        task_id: { type: "string", description: "Task ID" },
        comment_id: { type: "string", description: "Comment ID" },
      },
      required: ["task_id", "comment_id"],
    },
  },
  {
    name: "log_time",
    description: "Log time on a task. Requires MCP_WRITE_ENABLED=true.",
    inputSchema: {
      type: "object",
      properties: {
        task_id: { type: "string", description: "Task ID" },
        seconds: { type: "number", description: "Time in seconds" },
        comment: { type: "string", description: "Optional comment" },
      },
      required: ["task_id", "seconds"],
    },
  },
  {
    name: "delete_time",
    description: "Delete a time entry. Requires MCP_WRITE_ENABLED=true.",
    inputSchema: {
      type: "object",
      properties: {
        task_id: { type: "string", description: "Task ID" },
        entry_id: { type: "string", description: "Time entry ID" },
      },
      required: ["task_id", "entry_id"],
    },
  },
  {
    name: "update_estimate",
    description: "Update task time estimate in seconds. Requires MCP_WRITE_ENABLED=true.",
    inputSchema: {
      type: "object",
      properties: {
        task_id: { type: "string", description: "Task ID" },
        estimate_seconds: { type: "number", description: "Time estimate in seconds" },
      },
      required: ["task_id", "estimate_seconds"],
    },
  },
  {
    name: "update_status",
    description: "Update task status (e.g., '2', '3', '4', '5', '6', '7'). Requires MCP_WRITE_ENABLED=true.",
    inputSchema: {
      type: "object",
      properties: {
        task_id: { type: "string", description: "Task ID" },
        status: { type: "string", description: "Status code" },
      },
      required: ["task_id", "status"],
    },
  },
  {
    name: "update_stage",
    description: "Update task stage ID. Requires MCP_WRITE_ENABLED=true.",
    inputSchema: {
      type: "object",
      properties: {
        task_id: { type: "string", description: "Task ID" },
        stage_id: { type: "string", description: "Stage ID" },
      },
      required: ["task_id", "stage_id"],
    },
  },
];

function buildAllTools() {
  return [buildGetMyTasksTool(), ...STATIC_BASE_TOOLS, ...(MCP_WRITE_ENABLED ? WRITE_TOOLS : [])];
}

const server = new Server(
  { name: "sphere-integration", version: "2.0.0" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, () => ({
  tools: buildAllTools(),
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  if (name === "get_my_tasks") return handleGetMyTasks(args);
  if (name === "get_task") return handleGetTask(args);
  if (name === "get_tasks_batch") return handleGetTasksBatch(args);
  if (name === "fetch_sphere_static") return handleFetchStatic(args);
  if (name === "get_time") return handleGetTime(args);

  // Write tools — guarded individually
  if (name === "add_comment") return handleAddComment(args);
  if (name === "edit_comment") return handleEditComment(args);
  if (name === "delete_comment") return handleDeleteComment(args);
  if (name === "log_time") return handleLogTime(args);
  if (name === "delete_time") return handleDeleteTime(args);
  if (name === "update_estimate") return handleUpdateEstimate(args);
  if (name === "update_status") return handleUpdateStatus(args);
  if (name === "update_stage") return handleUpdateStage(args);

  return err(`Unknown tool: ${name}`);
});

async function handleGetMyTasks(args: Record<string, unknown> | undefined): Promise<McpResult> {
  const includeBody = (args?.include_body as boolean) ?? false;
  const includeComments = (args?.include_comments as boolean) ?? false;
  const allStages = args?.all_stages as boolean;
  const stageNames = args?.stage_names as string[] | undefined;
  const tag = args?.tag as string | undefined;

  if (!isApiConfigured()) {
    return err("B24_WEBHOOK_URL not configured in .env");
  }

  // Convert stage names to IDs
  let stages: number[] | undefined;
  if (allStages) {
    stages = [];
  } else if (stageNames && stageNames.length > 0) {
    const allIds = new Set<number>();
    for (const name of stageNames) {
      const ids = stageNameToIds[name];
      if (ids) ids.forEach((id) => allIds.add(id));
    }
    stages = [...allIds];
  }
  // else: default open stages applied inside fetchMyTasksViaApi (from initStages())

  try {
    const results = await fetchMyTasksViaApi({
      withContext: true,
      withSiblings: false,
      stages,
      tag,
    });

    const formatted = results.map((r) => {
      const groupName = groupIdToName.get(r.task.groupId);
      return formatTaskBrief(r, { includeBody, includeComments, groupName });
    });
    return ok(`${results.length} tasks\n\n${formatted.join("\n\n")}`);
  } catch (err_: unknown) {
    return err(`API fetch failed: ${(err_ as Error).message}`);
  }
}

async function handleGetTask(args: Record<string, unknown> | undefined): Promise<McpResult> {
  const taskId = args?.task_id as string;
  const withContext = (args?.with_context as boolean) ?? false;

  return fetchTaskLiveApi(taskId, withContext);
}

async function handleGetTasksBatch(args: Record<string, unknown> | undefined): Promise<McpResult> {
  if (!isApiConfigured()) return err("B24_WEBHOOK_URL not configured in .env");

  const parsed = parseTaskSpecs(args);
  if ("error" in parsed) return err(parsed.error);
  const { specs } = parsed;

  try {
    const ctxMap = await fetchTasksBatch(specs);

    const missing: string[] = [];
    const sections = specs.map((spec) => {
      const ctx = ctxMap.get(spec.taskId);
      if (!ctx) {
        missing.push(spec.taskId);
        return `## TASK [${spec.taskId}]\n> Not found or fetch failed`;
      }
      return spec.withContext
        ? formatTask(ctx, true, true, groupIdToName.get(ctx.task.groupId))
        : formatTaskDetail(ctx.task, "Live fetch (API, batch)");
    });

    const header = missing.length > 0
      ? `${specs.length - missing.length}/${specs.length} tasks (missing: ${missing.join(", ")})`
      : `${specs.length} tasks`;
    return ok(`${header}\n\n${sections.join("\n\n=====\n\n")}`);
  } catch (err_: unknown) {
    return err(`API fetch failed: ${(err_ as Error).message}`);
  }
}

async function handleFetchStatic(args: Record<string, unknown> | undefined): Promise<McpResult> {
  const url = args?.url as string | undefined;
  if (!url) return err("'url' is required");

  const cropArg = args?.crop as { x: number; y: number; width: number; height: number } | undefined;
  const resizeArg = args?.resize as { width?: number; height?: number } | undefined;

  let response: Response;
  try {
    response = await fetch(url);
  } catch (e) {
    return err(`Fetch failed: ${(e as Error).message}`);
  }
  if (!response.ok) return err(`HTTP ${response.status} fetching ${url}`);

  const contentType = response.headers.get("content-type") ?? "";
  const urlLower = url.toLowerCase();
  const buffer = Buffer.from(await response.arrayBuffer());

  // Images
  const isImage = contentType.startsWith("image/") || /\.(png|jpe?g|gif|webp|bmp)(\?|#|$)/i.test(urlLower);
  if (isImage) {
    let outBuffer: Buffer = buffer as Buffer;
    let mimeType = contentType.startsWith("image/") ? contentType.split(";")[0] : "image/png";
    if (cropArg || resizeArg?.width || resizeArg?.height) {
      const { default: sharp } = await import("sharp");
      let img = sharp(buffer);
      if (cropArg) img = img.extract({ left: cropArg.x, top: cropArg.y, width: cropArg.width, height: cropArg.height });
      if (resizeArg?.width || resizeArg?.height) img = img.resize(resizeArg?.width, resizeArg?.height, { fit: "inside" });
      outBuffer = await img.png().toBuffer();
      mimeType = "image/png";
    }
    return { content: [{ type: "image", data: outBuffer.toString("base64"), mimeType }] };
  }

  // DOCX
  if (contentType.includes("wordprocessingml") || urlLower.includes(".docx")) {
    const { default: mammoth } = await import("mammoth");
    const result = await mammoth.extractRawText({ buffer });
    return ok(result.value.slice(0, 20000));
  }

  // XLSX
  if (contentType.includes("spreadsheetml") || urlLower.includes(".xlsx") || urlLower.includes(".xls")) {
    const { read, utils } = await import("xlsx");
    const wb = read(buffer);
    const lines: string[] = [];
    for (const name of wb.SheetNames) {
      lines.push(`## ${name}`);
      lines.push(utils.sheet_to_csv(wb.Sheets[name]));
    }
    return ok(lines.join("\n").slice(0, 20000));
  }

  // PDF
  if (contentType.includes("pdf") || urlLower.includes(".pdf")) {
    const { PDFParse } = await import("pdf-parse");
    const parser = new PDFParse({}) as unknown as { load: (b: unknown) => Promise<void>; getText: () => Promise<{ text: string }> };
    await parser.load(buffer);
    const result = await parser.getText();
    return ok(result.text.slice(0, 20000));
  }

  // Fallback: plain text
  return ok(buffer.toString("utf8").slice(0, 10000));
}

async function handleGetTime(args: Record<string, unknown> | undefined): Promise<McpResult> {
  const taskId = args?.task_id as string;
  if (!taskId) return err("'task_id' is required");

  // Detailed elapsed-item list. On the current Bitrix instance
  // task.elapseditem.getlist fails with server-side ERROR_CORE
  // "Object property 'count' not found" (a tasks-module bug), so we wrap
  // it in try and always fall through to the aggregate totals below,
  // which come straight from the task (tasks.task.get) and are reliable.
  let entries: B24ElapsedRaw[] = [];
  let detailError = "";
  try {
    entries = await b24GetTimeEntries(taskId);
  } catch (e) {
    detailError = (e as Error).message ?? String(e);
  }

  let totals: { timeEstimate: string | null; timeSpentInLogs: string | null } | null = null;
  try {
    totals = await b24GetTaskTimeTotals(taskId);
  } catch {
    /* aggregate unavailable — show what we have */
  }

  const lines: string[] = [`Time for task ${taskId}:`];

  if (totals) {
    const plan = totals.timeEstimate ? formatSeconds(parseInt(String(totals.timeEstimate), 10)) : "—";
    const spent = totals.timeSpentInLogs ? formatSeconds(parseInt(String(totals.timeSpentInLogs), 10)) : "—";
    lines.push(`Plan (estimate): ${plan}`);
    lines.push(`Spent (logged):  ${spent}`);
  }

  if (entries.length > 0) {
    let totalSeconds = 0;
    lines.push("", `Detailed entries (${entries.length}):`);
    for (const e of entries) {
      const secs = parseInt(e.SECONDS, 10);
      totalSeconds += secs;
      lines.push(`[${e.ID}] ${e.CREATED_DATE} — ${formatSeconds(secs)} by user ${e.USER_ID}${e.COMMENT_TEXT ? `: ${e.COMMENT_TEXT}` : ""}`);
    }
    lines.push(`Total: ${formatSeconds(totalSeconds)}`);
  } else if (detailError) {
    lines.push("", `Detailed entries unavailable: ${detailError}`);
    lines.push(`(Bitrix task.elapseditem.getlist is broken on this instance — ERROR_CORE "Object property 'count' not found".)`);
  } else {
    lines.push("", "No detailed time entries.");
  }

  return ok(lines.join("\n"));
}

async function handleAddComment(args: Record<string, unknown> | undefined): Promise<McpResult> {
  assertWriteEnabled();
  const taskId = args?.task_id as string;
  const message = args?.message as string;
  if (!taskId || !message) return err("Both 'task_id' and 'message' are required");
  try {
    const commentId = await b24AddComment(taskId, message);
    return ok(`Comment added to task ${taskId} (ID: ${commentId})`);
  } catch (err_: unknown) {
    return err(`Failed to add comment: ${(err_ as Error).message}`);
  }
}

async function handleEditComment(args: Record<string, unknown> | undefined): Promise<McpResult> {
  assertWriteEnabled();
  const taskId = args?.task_id as string;
  const commentId = args?.comment_id as string;
  const message = args?.message as string;
  if (!taskId || !commentId || !message) return err("'task_id', 'comment_id', and 'message' are required");
  try {
    await b24UpdateComment(taskId, commentId, message);
    return ok(`Comment ${commentId} updated`);
  } catch (err_: unknown) {
    return err(`Failed to edit comment: ${(err_ as Error).message}`);
  }
}

async function handleDeleteComment(args: Record<string, unknown> | undefined): Promise<McpResult> {
  assertWriteEnabled();
  const taskId = args?.task_id as string;
  const commentId = args?.comment_id as string;
  if (!taskId || !commentId) return err("Both 'task_id' and 'comment_id' are required");
  try {
    await b24DeleteComment(taskId, commentId);
    return ok(`Comment ${commentId} deleted`);
  } catch (err_: unknown) {
    return err(`Failed to delete comment: ${(err_ as Error).message}`);
  }
}

async function handleLogTime(args: Record<string, unknown> | undefined): Promise<McpResult> {
  assertWriteEnabled();
  const taskId = args?.task_id as string;
  const seconds = args?.seconds as number;
  const comment = args?.comment as string | undefined;
  if (!taskId || !seconds) return err("Both 'task_id' and 'seconds' are required");
  try {
    const entryId = await b24LogTime(taskId, seconds, comment);
    return ok(`Logged ${formatSeconds(seconds)} (${seconds}s) to task ${taskId} (ID: ${entryId})`);
  } catch (err_: unknown) {
    return err(`Failed to log time: ${(err_ as Error).message}`);
  }
}

async function handleDeleteTime(args: Record<string, unknown> | undefined): Promise<McpResult> {
  assertWriteEnabled();
  const taskId = args?.task_id as string;
  const entryId = args?.entry_id as string;
  if (!taskId || !entryId) return err("Both 'task_id' and 'entry_id' are required");
  try {
    await b24DeleteTimeEntry(taskId, entryId);
    return ok(`Time entry ${entryId} deleted`);
  } catch (err_: unknown) {
    return err(`Failed to delete time entry: ${(err_ as Error).message}`);
  }
}

async function handleUpdateEstimate(args: Record<string, unknown> | undefined): Promise<McpResult> {
  assertWriteEnabled();
  const taskId = args?.task_id as string;
  const estimateSeconds = args?.estimate_seconds as number;
  if (!taskId || !estimateSeconds) return err("Both 'task_id' and 'estimate_seconds' are required");
  try {
    await b24UpdateEstimate(taskId, estimateSeconds);
    return ok(`Task ${taskId} estimate updated to ${formatSeconds(estimateSeconds)} (${estimateSeconds}s)`);
  } catch (err_: unknown) {
    return err(`Failed to update estimate: ${(err_ as Error).message}`);
  }
}

async function handleUpdateStatus(args: Record<string, unknown> | undefined): Promise<McpResult> {
  assertWriteEnabled();
  const taskId = args?.task_id as string;
  const status = args?.status as string;
  if (!taskId || !status) return err("Both 'task_id' and 'status' are required");
  try {
    await b24UpdateStatus(taskId, status);
    return ok(`Task ${taskId} status updated to ${status}`);
  } catch (err_: unknown) {
    return err(`Failed to update status: ${(err_ as Error).message}`);
  }
}

async function handleUpdateStage(args: Record<string, unknown> | undefined): Promise<McpResult> {
  assertWriteEnabled();
  const taskId = args?.task_id as string;
  const stageId = args?.stage_id as string;
  if (!taskId || !stageId) return err("Both 'task_id' and 'stage_id' are required");
  try {
    await b24UpdateStage(taskId, stageId);
    return ok(`Task ${taskId} stage updated to ${stageId}`);
  } catch (err_: unknown) {
    return err(`Failed to update stage: ${(err_ as Error).message}`);
  }
}

async function fetchTaskLiveApi(taskId: string, withContext = false): Promise<McpResult> {
  try {
    const ctxMap = await fetchTasksBatch([{ taskId, withContext }]);
    const ctx = ctxMap.get(taskId);
    if (!ctx) return err(`Task ${taskId} not found`);

    if (!withContext) return ok(formatTaskDetail(ctx.task, "Live fetch (API)"));

    const groupName = groupIdToName.get(ctx.task.groupId);
    return ok(formatTask(ctx, true, true, groupName));
  } catch (err_: unknown) {
    return err(`API fetch failed: ${(err_ as Error).message}`);
  }
}

if (isApiConfigured()) {
  await initGroups();
  await initStages();
}

const transport = new StdioServerTransport();
await server.connect(transport);
