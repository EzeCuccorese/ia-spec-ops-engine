export type TaskStatus = "active" | "paused" | "closed";

export interface TaskSummary {
  id: string;
  title: string;
  status: TaskStatus;
  summary: string;
  parent: string;
  workflow: string;
  phase: string;
  blocked: Record<string, unknown>;
  subtasks: string[];
  done_steps: number;
  total_steps: number;
  repos: { path?: string; branch?: string; pr?: string }[];
  links?: { title: string; url: string }[];
  has_debate: boolean;
  pending_rounds: number;
  created_at: string;
  updated_at: string;
}

export interface PendingDispatch {
  n: number;
  role: string;
  focus: string;
  agent: string;
  model: string;
  launched: boolean;
  dispatch_id: string;
}

export interface TaskDetail {
  id: string;
  title: string;
  status: TaskStatus;
  summary: string;
  parent: string;
  workflow: string;
  phase: string;
  blocked: Record<string, unknown>;
  subtasks: string[];
  steps: { text: string; done: boolean }[];
  facts: { text: string; at: string }[];
  decisions: { text: string; why: string; at: string }[];
  links: { title: string; url: string }[];
  repos: { path?: string; branch?: string; pr?: string }[];
  rounds: Record<string, unknown>[];
  created_at: string;
  updated_at: string;
  log_lines: string[];
  pending_dispatches: PendingDispatch[];
  debate: {
    active: boolean;
    state: Record<string, unknown> | null;
    seats: Record<string, unknown>[];
    synthesis: string;
  };
}

export interface BrainNote {
  ref: string;
  slug: string;
  title: string;
  kind: string;
  scope: string;
  tags: string[];
  repos: string[];
  source: string;
  created: string;
  updated: string;
  path: string;
  body: string;
  stale?: boolean;
}

export interface GraphNode {
  id: string;
  type: "note" | "task" | "tag" | "repo";
  kind: string;
  label: string;
  ref?: string;
  slug?: string;
  scope?: string;
  task_id?: string;
  status?: string;
  tags?: string[];
  repos?: string[];
  updated?: string;
  stale?: boolean;
  orphan?: boolean;
  degree: number;
  x?: number;
  y?: number;
}

export interface NoteBacklink {
  ref: string;
  title: string;
  kind: string;
}

export interface BrainFilters {
  scope: string;
  kind: string;
  repo: string;
  tag: string;
  staleOnly: boolean;
  orphansOnly: boolean;
  hubs: boolean;
}

export interface GraphLink {
  source: string | GraphNode;
  target: string | GraphNode;
  kind: string;
  weight: number;
}

export interface BrainGraph {
  nodes: GraphNode[];
  links: GraphLink[];
  stats: {
    notes: number;
    tasks: number;
    tags: number;
    repos: number;
    links: number;
    orphans?: number;
  };
}

export interface SearchHit {
  source: string;
  ref: string;
  title: string;
  kind: string;
  scope: string;
  snippet: string;
  score: number;
}

export interface OrcaWorker {
  dispatch_id: string;
  state: string;
  liveness: string;
  agent: string;
  running: boolean;
}

export interface WorkersResponse {
  available: boolean;
  reason: string;
  workers: OrcaWorker[];
}

export interface HealthResponse {
  status: string;
  version: string;
  host: string;
  port: number;
}

export interface JiraIssuePreview {
  key: string;
  title: string;
  status: string;
  issue_type: string;
  priority: string;
  parent: string;
  url: string;
}
