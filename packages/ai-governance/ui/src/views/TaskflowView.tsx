import { useState } from "react";
import { LayoutGrid, List, Plus } from "lucide-react";
import { ApiError, api } from "../api";
import { TaskDetailDrawer } from "../components/TaskDetailDrawer";
import type { TaskDetail, TaskStatus, TaskSummary } from "../types";

export type TaskBucket = "active" | "blocked" | "paused" | "closed";

const BUCKETS: { key: TaskBucket; label: string }[] = [
  { key: "active", label: "Active" },
  { key: "blocked", label: "Blocked" },
  { key: "paused", label: "Paused" },
  { key: "closed", label: "Closed" },
];

const FILTERS = ["all", "blocked", "debate", "active", "paused", "closed"] as const;
const STATUS_OPTIONS: TaskStatus[] = ["active", "paused", "closed"];

export function taskBucket(t: TaskSummary): TaskBucket {
  if (t.status === "closed") return "closed";
  if (Object.keys(t.blocked || {}).length > 0) return "blocked";
  if (t.status === "paused") return "paused";
  return "active";
}

function matchesFilter(t: TaskSummary, filter: string, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (q) {
    const hay = `${t.id} ${t.title} ${t.summary}`.toLowerCase();
    if (!hay.includes(q)) return false;
  }
  if (filter === "all") return true;
  if (filter === "debate") return t.has_debate;
  return taskBucket(t) === filter;
}

interface TaskflowViewProps {
  tasks: TaskSummary[];
  selectedTask: TaskDetail | null;
  onSelectTask: (id: string) => void;
  onRefresh: () => void;
  onArchived?: (ref: string) => void;
}

function NewTaskForm({ onCreated, onCancel }: { onCreated: (id: string) => void; onCancel: () => void }) {
  const [id, setId] = useState("");
  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState("");
  const [error, setError] = useState("");

  async function submit() {
    setError("");
    try {
      const res = await api.createTask({ id: id.trim(), title: title.trim(), summary: summary.trim() });
      onCreated(res.task.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create task");
    }
  }

  return (
    <div className="card list-stack">
      {error && <div className="alert-error">{error}</div>}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: 8 }}>
        <input className="input" placeholder="Task ID (e.g. TASK-101)" value={id} onChange={(e) => setId(e.target.value)} />
        <input className="input" placeholder="Title" value={title} onChange={(e) => setTitle(e.target.value)} />
      </div>
      <input className="input" placeholder="Summary (optional)" value={summary} onChange={(e) => setSummary(e.target.value)} />
      <div style={{ display: "flex", gap: 8 }}>
        <button type="button" className="btn btn-primary" disabled={!id.trim() || !title.trim()} onClick={() => void submit()}>Create Task</button>
        <button type="button" className="btn" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

function TaskCard({
  task,
  selected,
  onSelect,
  onStatusChange,
}: {
  task: TaskSummary;
  selected: boolean;
  onSelect: (id: string) => void;
  onStatusChange: (id: string, status: TaskStatus) => void;
}) {
  const bucket = taskBucket(task);
  return (
    <div
      role="button"
      tabIndex={0}
      className={`item-card ${selected ? "selected" : ""}`}
      onClick={() => onSelect(task.id)}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onSelect(task.id); }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.75rem" }}>
        <span style={{ color: "var(--cyan)", fontWeight: 600 }}>{task.id}</span>
        <span className={`pill pill-${bucket === "blocked" ? "amber" : task.status}`}>{bucket}</span>
      </div>
      <div style={{ fontWeight: 600, marginTop: 4 }}>{task.title}</div>
      <div style={{ display: "flex", gap: 8, marginTop: 6, fontSize: "0.75rem", color: "var(--text-muted)", flexWrap: "wrap" }}>
        <span>{task.done_steps}/{task.total_steps} steps</span>
        {task.has_debate && <span className="pill pill-violet">debate</span>}
        {task.pending_rounds > 0 && <span className="pill pill-amber">{task.pending_rounds} pending</span>}
      </div>
      <div style={{ display: "flex", gap: 4, marginTop: 8 }}>
        {STATUS_OPTIONS.map((st) => (
          <button
            key={st}
            type="button"
            className={`btn ${task.status === st ? "btn-primary" : ""}`}
            style={{ padding: "0.15rem 0.45rem", fontSize: "0.7rem", textTransform: "capitalize" }}
            onClick={(e) => { e.stopPropagation(); onStatusChange(task.id, st); }}
          >
            {st}
          </button>
        ))}
      </div>
    </div>
  );
}

function BoardView({
  tasks,
  selectedId,
  onSelect,
  onStatusChange,
}: {
  tasks: TaskSummary[];
  selectedId?: string;
  onSelect: (id: string) => void;
  onStatusChange: (id: string, status: TaskStatus) => void;
}) {
  return (
    <div className="kanban-grid">
      {BUCKETS.map(({ key, label }) => {
        const colTasks = tasks.filter((t) => taskBucket(t) === key);
        return (
          <div key={key} className="list-stack" style={{ gap: 8 }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.8rem", fontWeight: 600 }}>
              <span>{label}</span>
              <span className="pill">{colTasks.length}</span>
            </div>
            {colTasks.map((t) => (
              <TaskCard key={t.id} task={t} selected={selectedId === t.id} onSelect={onSelect} onStatusChange={onStatusChange} />
            ))}
          </div>
        );
      })}
    </div>
  );
}

function TaskToolbar({
  viewMode,
  filter,
  query,
  onViewMode,
  onFilter,
  onQuery,
  onToggleNew,
}: {
  viewMode: "board" | "list";
  filter: string;
  query: string;
  onViewMode: (m: "board" | "list") => void;
  onFilter: (f: string) => void;
  onQuery: (q: string) => void;
  onToggleNew: () => void;
}) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
        {FILTERS.map((st) => (
          <button key={st} type="button" className={`btn ${filter === st ? "btn-primary" : ""}`} onClick={() => onFilter(st)}>{st}</button>
        ))}
        <input className="input" style={{ width: 200 }} placeholder="Search id, title, summary..." value={query} onChange={(e) => onQuery(e.target.value)} />
      </div>
      <div style={{ display: "flex", gap: 6 }}>
        <button type="button" className={`btn ${viewMode === "board" ? "btn-primary" : ""}`} onClick={() => onViewMode("board")}>
          <LayoutGrid size={14} /> Board
        </button>
        <button type="button" className={`btn ${viewMode === "list" ? "btn-primary" : ""}`} onClick={() => onViewMode("list")}>
          <List size={14} /> List
        </button>
        <button type="button" className="btn btn-primary" onClick={onToggleNew}><Plus size={14} /> New Task</button>
      </div>
    </div>
  );
}

export function TaskflowView({ tasks, selectedTask, onSelectTask, onRefresh, onArchived }: TaskflowViewProps) {
  const [viewMode, setViewMode] = useState<"board" | "list">("board");
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(false);

  const visible = tasks.filter((t) => matchesFilter(t, filter, query));

  async function handleStatusChange(id: string, status: TaskStatus) {
    await api.patchTask(id, { status });
    onRefresh();
  }

  return (
    <div className="list-stack" style={{ gap: "0.85rem" }}>
      <TaskToolbar
        viewMode={viewMode}
        filter={filter}
        query={query}
        onViewMode={setViewMode}
        onFilter={setFilter}
        onQuery={setQuery}
        onToggleNew={() => setCreating((v) => !v)}
      />
      {creating && <NewTaskForm onCreated={(newId) => { setCreating(false); onRefresh(); onSelectTask(newId); }} onCancel={() => setCreating(false)} />}
      <div className="split-layout">
        {viewMode === "board" ? (
          <BoardView tasks={visible} selectedId={selectedTask?.id} onSelect={onSelectTask} onStatusChange={(id, st) => void handleStatusChange(id, st)} />
        ) : (
          <div className="list-stack">
            {visible.map((t) => (
              <TaskCard key={t.id} task={t} selected={selectedTask?.id === t.id} onSelect={onSelectTask} onStatusChange={(id, st) => void handleStatusChange(id, st)} />
            ))}
          </div>
        )}
        <div>
          {selectedTask ? (
            <TaskDetailDrawer key={selectedTask.id} task={selectedTask} onRefresh={() => { onRefresh(); onSelectTask(selectedTask.id); }} onArchived={onArchived} onSelectTask={onSelectTask} />
          ) : (
            <div className="card" style={{ color: "var(--text-muted)", fontSize: "0.86rem" }}>Select a task to inspect its notebook, steps, decisions, and debates.</div>
          )}
        </div>
      </div>
    </div>
  );
}
