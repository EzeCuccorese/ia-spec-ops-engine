import { useState } from "react";
import { Archive, CheckSquare, Plus, Square } from "lucide-react";
import { ApiError, api } from "../api";
import type { TaskDetail } from "../types";
import { DebatePanel } from "./DebatePanel";

interface TaskDetailDrawerProps {
  task: TaskDetail;
  onRefresh: () => void;
  onArchived?: (ref: string) => void;
}

function StepsSection({ task, onMutate }: { task: TaskDetail; onMutate: (fn: () => Promise<unknown>) => void }) {
  const [newStep, setNewStep] = useState("");
  return (
    <div>
      <div style={{ fontSize: "0.8rem", fontWeight: 600, marginBottom: 6 }}>
        Steps ({task.steps.filter((s) => s.done).length}/{task.steps.length})
      </div>
      <div className="list-stack" style={{ gap: 4 }}>
        {task.steps.map((step, i) => (
          <button key={i} type="button" className="item-card" style={{ padding: "0.45rem 0.65rem", display: "flex", gap: 8, alignItems: "center" }} onClick={() => onMutate(() => api.toggleStep(task.id, i, !step.done))}>
            {step.done ? <CheckSquare size={15} color="#34d399" /> : <Square size={15} />}
            <span style={{ textDecoration: step.done ? "line-through" : "none" }}>{step.text}</span>
          </button>
        ))}
      </div>
      <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
        <input className="input" placeholder="Add step..." value={newStep} onChange={(e) => setNewStep(e.target.value)} />
        <button type="button" className="btn btn-primary" disabled={!newStep.trim()} onClick={() => onMutate(async () => { await api.addStep(task.id, newStep.trim()); setNewStep(""); })}>
          <Plus size={14} /> Add
        </button>
      </div>
    </div>
  );
}

function FactsAndDecisions({ task, onMutate }: { task: TaskDetail; onMutate: (fn: () => Promise<unknown>) => void }) {
  const [newFact, setNewFact] = useState("");
  const [decText, setDecText] = useState("");
  const [decWhy, setDecWhy] = useState("");
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
      <div>
        <div style={{ fontSize: "0.8rem", fontWeight: 600, marginBottom: 4 }}>Facts ({task.facts.length})</div>
        <ul style={{ margin: 0, paddingLeft: "1.1rem", fontSize: "0.81rem" }}>
          {task.facts.map((f, i) => <li key={i}>{f.text}</li>)}
        </ul>
        <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
          <input className="input" placeholder="Record fact..." value={newFact} onChange={(e) => setNewFact(e.target.value)} />
          <button type="button" className="btn" disabled={!newFact.trim()} onClick={() => onMutate(async () => { await api.addFact(task.id, newFact.trim()); setNewFact(""); })}>Add</button>
        </div>
      </div>
      <div>
        <div style={{ fontSize: "0.8rem", fontWeight: 600, marginBottom: 4 }}>Decisions ({task.decisions.length})</div>
        <ul style={{ margin: 0, paddingLeft: "1.1rem", fontSize: "0.81rem" }}>
          {task.decisions.map((d, i) => <li key={i}><strong>{d.text}</strong> — <span style={{ color: "var(--text-muted)" }}>{d.why}</span></li>)}
        </ul>
        <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 6 }}>
          <input className="input" placeholder="Decision..." value={decText} onChange={(e) => setDecText(e.target.value)} />
          <div style={{ display: "flex", gap: 6 }}>
            <input className="input" placeholder="Why..." value={decWhy} onChange={(e) => setDecWhy(e.target.value)} />
            <button type="button" className="btn" disabled={!decText.trim() || !decWhy.trim()} onClick={() => onMutate(async () => { await api.addDecision(task.id, decText.trim(), decWhy.trim()); setDecText(""); setDecWhy(""); })}>Add</button>
          </div>
        </div>
      </div>
    </div>
  );
}

export function TaskDetailDrawer({ task, onRefresh, onArchived }: TaskDetailDrawerProps) {
  const [summaryDraft, setSummaryDraft] = useState(task.summary);
  const [error, setError] = useState("");

  async function mutate(fn: () => Promise<unknown>) {
    setError("");
    try {
      await fn();
      onRefresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Update failed");
    }
  }

  return (
    <div className="card list-stack">
      <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <div>
          <div style={{ fontSize: "0.75rem", color: "var(--cyan)", fontWeight: 600 }}>{task.id}</div>
          <h2 style={{ margin: "0.15rem 0 0", fontSize: "1.15rem" }}>{task.title}</h2>
        </div>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <select className="select" style={{ width: "auto" }} value={task.status} onChange={(e) => void mutate(() => api.patchTask(task.id, { status: e.target.value }))}>
            <option value="active">active</option>
            <option value="paused">paused</option>
            <option value="closed">closed</option>
          </select>
          <button type="button" className="btn" onClick={() => void mutate(async () => { const res = await api.archiveTask(task.id); onArchived?.(res.ref); })}>
            <Archive size={14} /> Archive to Brain
          </button>
        </div>
      </div>
      {error && <div className="alert-error">{error}</div>}
      <div style={{ display: "flex", gap: 6 }}>
        <input className="input" placeholder="Summary..." value={summaryDraft} onChange={(e) => setSummaryDraft(e.target.value)} />
        <button type="button" className="btn" onClick={() => void mutate(() => api.patchTask(task.id, { summary: summaryDraft }))}>Save</button>
      </div>
      <StepsSection task={task} onMutate={(fn) => void mutate(fn)} />
      <FactsAndDecisions task={task} onMutate={(fn) => void mutate(fn)} />
      <DebatePanel task={task} onRefresh={onRefresh} />
    </div>
  );
}
