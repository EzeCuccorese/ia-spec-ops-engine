import type {
  BrainGraph,
  BrainNote,
  HealthResponse,
  SearchHit,
  TaskDetail,
  TaskSummary,
  WorkersResponse,
} from "./types";

export class ApiError extends Error {
  status: number;
  code?: string;
  constructor(status: number, message: string, code?: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export function getSessionToken(): string {
  const meta = document.querySelector<HTMLMetaElement>('meta[name="ai-gov-token"]');
  return meta?.content ?? "";
}

function buildHeaders(init: RequestInit, method: string): Headers {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
    const token = getSessionToken();
    if (token) headers.set("X-UI-Token", token);
  }
  return headers;
}

function toApiError(status: number, data: Record<string, unknown>): ApiError {
  const detail = data?.detail as string | { message?: string; code?: string } | undefined;
  const msg =
    typeof detail === "string"
      ? detail
      : (detail?.message ?? `Request failed (${status})`);
  const code = typeof detail === "object" ? detail?.code : undefined;
  return new ApiError(status, msg, code);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const resp = await fetch(path, { ...init, headers: buildHeaders(init, method) });
  const text = await resp.text();
  const data = text ? JSON.parse(text) : {};
  if (!resp.ok) {
    throw toApiError(resp.status, data as Record<string, unknown>);
  }
  return data as T;
}

export const api = {
  health: () => request<HealthResponse>("/api/health"),
  workers: () => request<WorkersResponse>("/api/orca/workers"),

  listTasks: (includeClosed = true) =>
    request<{ tasks: TaskSummary[] }>(`/api/tasks?include_closed=${includeClosed}`),
  getTask: (id: string) => request<{ task: TaskDetail }>(`/api/tasks/${encodeURIComponent(id)}`),
  createTask: (body: { id: string; title: string; summary?: string; workflow?: string; parent?: string }) =>
    request<{ task: TaskDetail }>("/api/tasks", { method: "POST", body: JSON.stringify(body) }),
  patchTask: (id: string, body: { title?: string; summary?: string; status?: string; phase?: string }) =>
    request<{ task: TaskDetail }>(`/api/tasks/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  addStep: (id: string, text: string) =>
    request<{ task: TaskDetail }>(`/api/tasks/${encodeURIComponent(id)}/steps`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  toggleStep: (id: string, index: number, done: boolean) =>
    request<{ task: TaskDetail }>(`/api/tasks/${encodeURIComponent(id)}/steps/${index}`, {
      method: "PATCH",
      body: JSON.stringify({ done }),
    }),
  addFact: (id: string, text: string) =>
    request<{ task: TaskDetail }>(`/api/tasks/${encodeURIComponent(id)}/facts`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  addDecision: (id: string, text: string, why: string) =>
    request<{ task: TaskDetail }>(`/api/tasks/${encodeURIComponent(id)}/decisions`, {
      method: "POST",
      body: JSON.stringify({ text, why }),
    }),
  addLink: (id: string, title: string, url: string) =>
    request<{ task: TaskDetail }>(`/api/tasks/${encodeURIComponent(id)}/links`, {
      method: "POST",
      body: JSON.stringify({ title, url }),
    }),
  archiveTask: (id: string, scope?: string) =>
    request<{ ref: string; created: boolean; updated: boolean }>(
      `/api/tasks/${encodeURIComponent(id)}/archive`,
      { method: "POST", body: JSON.stringify({ scope: scope || null }) }
    ),

  openDebate: (id: string, body: { topic: string; agents: string[]; models?: Record<string, string>; web?: boolean }) =>
    request<{ debate_id: number; rounds: Record<string, unknown>[] }>(
      `/api/tasks/${encodeURIComponent(id)}/debates/open`,
      { method: "POST", body: JSON.stringify(body) }
    ),
  crossDebate: (id: string) =>
    request<{ debate_id: number; warnings: string[] }>(
      `/api/tasks/${encodeURIComponent(id)}/debates/cross`,
      { method: "POST", body: "{}" }
    ),
  closeDebate: (id: string, partial = false) =>
    request<{ synthesis_path: string; synthesis: string }>(
      `/api/tasks/${encodeURIComponent(id)}/debates/close`,
      { method: "POST", body: JSON.stringify({ partial }) }
    ),
  launchRound: (id: string, n: number) =>
    request<{ round: number; dispatch_id: string }>(
      `/api/tasks/${encodeURIComponent(id)}/rounds/${n}/launch`,
      { method: "POST", body: "{}" }
    ),
  collectRound: (id: string, n: number, dispatch_id: string) =>
    request<{ record: Record<string, unknown> }>(
      `/api/tasks/${encodeURIComponent(id)}/rounds/${n}/collect`,
      { method: "POST", body: JSON.stringify({ dispatch_id }) }
    ),
  abortRound: (id: string, n: number, reason: string, dispatch_id?: string) =>
    request<{ record: Record<string, unknown> }>(
      `/api/tasks/${encodeURIComponent(id)}/rounds/${n}/abort`,
      { method: "POST", body: JSON.stringify({ reason, dispatch_id: dispatch_id || null }) }
    ),

  listNotes: (params: { scope?: string; kind?: string; repo?: string } = {}) => {
    const qs = new URLSearchParams();
    if (params.scope) qs.set("scope", params.scope);
    if (params.kind) qs.set("kind", params.kind);
    if (params.repo) qs.set("repo", params.repo);
    return request<{
      notes: BrainNote[];
      scopes: string[];
      kinds: string[];
      repos: string[];
      tags: string[];
    }>(`/api/brain/notes?${qs.toString()}`);
  },
  getNote: (scope: string, slug: string) =>
    request<{ note: BrainNote; backlinks: { ref: string; title: string; kind: string }[] }>(
      `/api/brain/notes/${encodeURIComponent(scope)}/${encodeURIComponent(slug)}`
    ),
  createNote: (body: {
    title: string;
    body: string;
    kind: string;
    scope: string;
    tags: string[];
    repos: string[];
    source?: string;
  }) => request<{ note: BrainNote }>("/api/brain/notes", { method: "POST", body: JSON.stringify(body) }),
  updateNote: (
    scope: string,
    slug: string,
    body: { title: string; body: string; kind: string; tags: string[]; repos: string[]; source?: string }
  ) =>
    request<{ note: BrainNote }>(
      `/api/brain/notes/${encodeURIComponent(scope)}/${encodeURIComponent(slug)}`,
      { method: "PUT", body: JSON.stringify(body) }
    ),
  searchAll: (q: string) =>
    request<{ hits: SearchHit[] }>(`/api/brain/search?q=${encodeURIComponent(q)}`),
  getGraph: (params: { scope?: string; kind?: string; hubs?: boolean } = {}) => {
    const qs = new URLSearchParams();
    if (params.scope) qs.set("scope", params.scope);
    if (params.kind) qs.set("kind", params.kind);
    qs.set("hubs", String(params.hubs ?? true));
    return request<BrainGraph>(`/api/brain/graph?${qs.toString()}`);
  },
};
