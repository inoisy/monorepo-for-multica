import type { TaskDetail, TaskWithContext, BodyImage, Comment } from "../types.js";

function formatAttachment(img: BodyImage): string {
  return `- [${img.alt}](${img.src})`;
}

function formatComments(comments: Comment[]): string[] {
  const lines: string[] = [];
  for (const c of comments) {
    lines.push(`- **${c.author}** (${c.date}): ${c.text}`);
    if (c.images?.length) {
      lines.push(...c.images.map(formatAttachment));
    }
  }
  return lines;
}

function metaLine(t: TaskDetail, groupName?: string): string {
  const parts = [`Stage: ${t.stageTitle}`, `Responsible: ${t.responsible}`];
  if (groupName) parts.push(`Group: ${groupName}`);
  if (t.tags.length > 0) parts.push(`Sprint: ${t.tags.join(", ")}`);
  if (t.deadline) parts.push(`Deadline: ${t.deadline}`);
  if (t.timeEstimate || t.timer) parts.push(`Estimate: ${t.timeEstimate || "—"} / Spent: ${t.timer || "—"}`);
  return parts.join(" | ");
}

// Compact single-task block used inside full detail view
function formatFullBlock(t: TaskDetail, includeComments: boolean, groupName?: string): string[] {
  const lines: string[] = [];
  lines.push(metaLine(t, groupName));
  lines.push(`URL: ${t.detailUrl}`);
  if (t.body) lines.push(`\nDescription:\n${t.body}`);
  if (t.bodyImages?.length > 0) {
    lines.push(`\nAttachments:`);
    lines.push(...t.bodyImages.map(formatAttachment));
  }
  if (includeComments && t.comments.length > 0) {
    lines.push(`\nComments (${t.comments.length}):`);
    lines.push(...formatComments(t.comments));
  }
  return lines;
}

export interface ListFormatOptions {
  includeBody?: boolean;
  includeComments?: boolean;
  groupName?: string;
}

// List format -- compact by default, configurable
export function formatTaskBrief(r: TaskWithContext, opts: ListFormatOptions = {}): string {
  const t = r.task;
  const lines: string[] = [];
  lines.push(`[${t.taskId}] ${t.title}`);
  lines.push(metaLine(t, opts.groupName));
  lines.push(`URL: ${t.detailUrl}`);
  if (r.parentStory) lines.push(`Parent: [${r.parentStory.taskId}] ${r.parentStory.title}`);
  if (opts.includeBody && t.body) lines.push(`\nDescription:\n${t.body}`);
  if (opts.includeBody && t.bodyImages?.length > 0) {
    lines.push(`Attachments:`);
    lines.push(...t.bodyImages.map(formatAttachment));
  }
  if (opts.includeComments && t.comments.length > 0) {
    lines.push(`\nComments (${t.comments.length}):`);
    lines.push(...formatComments(t.comments));
  }
  return lines.join("\n");
}

// Full format for single-task view with parent story + siblings
export function formatTask(r: TaskWithContext, includeComments: boolean, _includeBody: boolean, groupName?: string): string {
  const sections: string[] = [];

  // Main task
  sections.push([
    `## TASK [${r.task.taskId}] ${r.task.title}`,
    ...formatFullBlock(r.task, includeComments, groupName),
  ].join("\n"));

  // Parent story
  if (r.parentStory) {
    const s = r.parentStory;
    sections.push([
      `## PARENT STORY [${s.taskId}] ${s.title}`,
      ...formatFullBlock(s, includeComments),
    ].join("\n"));
  }

  // Siblings
  if (r.relatedTasks.length > 0) {
    const sibLines: string[] = [`## SIBLING TASKS (${r.relatedTasks.length})`];
    for (const sib of r.relatedTasks) {
      sibLines.push(`\n### [${sib.taskId}] ${sib.title}`);
      sibLines.push(metaLine(sib));
      sibLines.push(`URL: ${sib.detailUrl}`);
      if (sib.body) sibLines.push(`\nDescription:\n${sib.body}`);
      if (sib.bodyImages?.length > 0) {
        sibLines.push(`\nAttachments:`);
        sibLines.push(...sib.bodyImages.map(formatAttachment));
      }
      if (includeComments && sib.comments.length > 0) {
        sibLines.push(`\nComments (${sib.comments.length}):`);
        sibLines.push(...formatComments(sib.comments));
      }
    }
    sections.push(sibLines.join("\n"));
  }

  return sections.join("\n\n---\n\n");
}

// Single task without context (get_task without with_context)
export function formatTaskDetail(t: TaskDetail, label: string): string {
  const lines: string[] = [];
  lines.push(`## TASK [${t.taskId}] ${t.title}`);
  lines.push(`> ${label}`);
  lines.push(metaLine(t));
  lines.push(`URL: ${t.detailUrl}`);
  if (t.body) lines.push(`\nDescription:\n${t.body}`);
  if (t.bodyImages?.length > 0) {
    lines.push(`\nAttachments:`);
    lines.push(...t.bodyImages.map(formatAttachment));
  }
  if (t.comments.length > 0) {
    lines.push(`\nComments (${t.comments.length}):`);
    lines.push(...formatComments(t.comments));
  }
  return lines.join("\n");
}
