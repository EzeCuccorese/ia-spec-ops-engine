import { useState } from "react";
import { Plus } from "lucide-react";
import { ApiError, api } from "../api";
import { TaskDetailDrawer } from "../components/TaskDetailDrawer";
import type { TaskDetail, TaskSummary } from "../types";

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

export function TaskflowView({ tasks, selectedTask, onSelectTask, onRefresh, onArchived }: TaskflowViewProps) {
  const [filter, setFilter] = useState("all");
  const [creating, setCreating] = useState(false);
  const visible = filter === "all" ? tasks : tasks.filter((t) => t.status === filter);

  return (
    <div className="list-stack" style={{ gap: "0.85rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <div style={{ display: "flex", gap: 6 }}>
          {["all", "active", "paused", "closed"].map((st) => (
            <button key={st} type="button" className={`btn ${filter === st ? "btn-primary" : ""}`} onClick={() => setFilter(st)}>{st}</button>
          ))}
        </div>
        <button type="button" className="btn btn-primary" onClick={() => setCreating((v) => !v)}><Plus size={14} /> New Task</button>
      </div>
      {creating && <NewTaskForm onCreated={(newId) => { setCreating(false); onRefresh(); onSelectTask(newId); }} onCancel={() => setCreating(false)} />}
      <div className="split-layout">
        <div className="list-stack">
          {visible.map((t) => (
            <button key={t.id} type="button" className={`item-card ${selectedTask?.id === t.id ? "selected" : ""}`} onClick={() => onSelectTask(t.id)}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.75rem" }}>
                <span style={{ color: "var(--cyan)", fontWeight: 600 }}>{t.id}</span>
                <span className={`pill pill-${t.status}`}>{t.status}</span>
              </div>
              <div style={{ fontWeight: 600, marginTop: 4 }}>{t.title}</div>
              <div style={{ display: "flex", gap: 8, marginTop: 6, fontSize: "0.75rem", color: "var(--text-muted)" }}>
                <span>{t.done_steps}/{t.total_steps} steps</span>
                {t.has_debate && <span className="pill pill-violet">debate</span>}
                {t.pending_rounds > 0 && <span className="pill pill-amber">{t.pending_rounds} pending</span>}
              </div>
            </button>
          ))}
        </div>
        <div>
          {selectedTask ? (
            <TaskDetailDrawer task={selectedTask} onRefresh={() => { onRefresh(); onSelectTask(selectedTask.id); }} onArchived={onArchived} />
          ) : (
            <div className="card" style={{ color: "var(--text-muted)", fontSize: "0.86rem" }}>Select a task to inspect its notebook, steps, decisions, and debates.</div>
          )}
        </div>
      </div>
    </div>
  );
}
