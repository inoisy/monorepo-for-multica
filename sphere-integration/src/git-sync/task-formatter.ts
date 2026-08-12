import type { TaskDetail } from "../types.js";

const TRANSLIT: Record<string, string> = {
  а: "a", б: "b", в: "v", г: "g", д: "d", е: "e", ё: "yo", ж: "zh",
  з: "z", и: "i", й: "y", к: "k", л: "l", м: "m", н: "n", о: "o",
  п: "p", р: "r", с: "s", т: "t", у: "u", ф: "f", х: "kh", ц: "ts",
  ч: "ch", ш: "sh", щ: "sch", ъ: "", ы: "y", ь: "", э: "e", ю: "yu", я: "ya",
};

function slugify(str: string): string {
  return str
    .toLowerCase()
    .split("")
    .map((c) => TRANSLIT[c] ?? c)
    .join("")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 50);
}

export function taskSlug(task: TaskDetail): string {
  return `${task.taskId}-${slugify(task.title)}`;
}

function yaml(value: string): string {
  return `"${value.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
}

export function formatIndexMd(task: TaskDetail): string {
  const lines: string[] = [
    "---",
    `id: ${task.taskId}`,
    `title: ${yaml(task.title)}`,
    `status: ${yaml(task.status)}`,
    `stage: ${task.stageId}`,
    `stageTitle: ${yaml(task.stageTitle)}`,
    `responsible: ${yaml(task.responsible)}`,
    `priority: ${yaml(task.priority)}`,
    `deadline: ${yaml(task.deadline)}`,
    `tags: [${task.tags.map((t) => yaml(t)).join(", ")}]`,
    `timer: ${yaml(task.timer)}`,
    `parentTaskId: ${yaml(task.parentTaskId)}`,
    `parentTaskTitle: ${yaml(task.parentTaskTitle)}`,
    `groupId: ${yaml(task.groupId)}`,
    `detailUrl: ${yaml(task.detailUrl)}`,
    `fetchedAt: ${yaml(task.fetchedAt)}`,
    "---",
    "",
    `# ${task.title} (#${task.taskId})`,
    "",
    "## Описание",
    "",
    task.body?.trim() || "_Нет описания_",
  ];

  if (task.bodyImages.length > 0) {
    lines.push("", "## Вложения", "");
    for (const img of task.bodyImages) {
      lines.push(`- [${img.alt}](${img.src})`);
    }
  }

  if (task.siblingTasks.length > 0) {
    lines.push("", "## Связанные задачи", "");
    for (const s of task.siblingTasks) {
      lines.push(`- [#${s.id}] ${s.title}`);
    }
  }

  const extraFields = Object.entries(task.sidebarFields).filter(([, v]) => v);
  if (extraFields.length > 0) {
    lines.push("", "## Дополнительные поля", "");
    for (const [key, value] of extraFields) {
      lines.push(`- **${key}:** ${value}`);
    }
  }

  return lines.join("\n") + "\n";
}

export function formatCommentsMd(task: TaskDetail): string {
  if (task.comments.length === 0) {
    return "# Комментарии\n\n_Нет комментариев_\n";
  }

  const lines: string[] = ["# Комментарии", ""];
  for (const comment of task.comments) {
    lines.push(`## [${comment.date}] ${comment.author}`, "");
    lines.push(comment.text?.trim() || "_пусто_");
    if (comment.images.length > 0) {
      lines.push("", "**Вложения:**");
      for (const img of comment.images) {
        lines.push(`- [${img.alt}](${img.src})`);
      }
    }
    lines.push("", "---", "");
  }
  return lines.join("\n");
}
