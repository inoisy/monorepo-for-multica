export interface Task {
  taskId: string;
  title: string;
  stage: string;
  responsible: string;
  priority: string;
  deadline: string;
  tags: string[];
  timer: string;
  timeEstimate: string;
  detailUrl: string;
  groupId: string;
}

export interface Comment {
  author: string;
  text: string;
  date: string;
  images: BodyImage[];
}

export interface BodyImage {
  /** Remote URL, e.g. Sphere disk URL with attachedId */
  src: string;
  /** Original filename */
  alt: string;
}

export interface TaskDetail extends Task {
  status: string;
  sidebarFields: Record<string, string>;
  body: string;
  bodyImages: BodyImage[];
  comments: Comment[];
  stageId: number;
  stageTitle: string;
  parentTaskId: string;
  parentTaskTitle: string;
  siblingTasks: { id: string; title: string }[];
  fetchedAt: string;
}

export interface TaskWithContext {
  task: TaskDetail;
  parentStory: TaskDetail | null;
  relatedTasks: TaskDetail[];
}
