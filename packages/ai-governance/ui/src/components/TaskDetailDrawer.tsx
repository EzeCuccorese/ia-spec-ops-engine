import { useEffect, useState } from "react";
import { Archive, CheckSquare, ExternalLink, Plus, ShieldAlert, Square } from "lucide-react";
import { ApiError, api } from "../api";
import type { TaskDetail } from "../types";
import { DebatePanel } from "./DebatePanel";

interface TaskDetailDrawerProps {
  task: TaskDetail;
  onRefresh: () => void;
  onArchived?: (ref: string) => void;
  onSelectTask?: (id: string) => void;
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

function FactsSection({ task, onMutate }: { task: TaskDetail; onMutate: (fn: () => Promise<unknown>) => void }) {
  const [newFact, setNewFact] = useState("");
  return (
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
  );
}

function DecisionsSection({ task, onMutate }: { task: TaskDetail; onMutate: (fn: () => Promise<unknown>) => void }) {
  const [decText, setDecText] = useState("");
  const [decWhy, setDecWhy] = useState("");
  return (
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
  );
}

function BlockedSection({ task, onMutate }: { task: TaskDetail; onMutate: (fn: () => Promise<unknown>) => void }) {
  const [editing, setEditing] = useState(false);
  const [owner, setOwner] = useState("");
  const [needs, setNeeds] = useState("");
  const entries = Object.entries(task.blocked || {});
  if (entries.length > 0) {
    return (
      <div className="alert-error" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
        <div style={{ fontSize: "0.8rem" }}>
          <ShieldAlert size={14} style={{ verticalAlign: "middle", marginRight: 4 }} />
          <strong>Blocked:</strong> {entries.map(([k, v]) => `${k}: ${String(v)}`).join(" · ")}
        </div>
        <button type="button" className="btn" onClick={() => onMutate(() => api.patchTask(task.id, { blocked: {} }))}>Unblock</button>
      </div>
    );
  }
  if (!editing) {
    return (
      <div>
        <button type="button" className="btn" onClick={() => setEditing(true)}>Mark Blocked</button>
      </div>
    );
  }
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
      <input className="input" style={{ flex: 1, minWidth: 120 }} placeholder="Owner..." value={owner} onChange={(e) => setOwner(e.target.value)} />
      <input className="input" style={{ flex: 2, minWidth: 160 }} placeholder="Needs..." value={needs} onChange={(e) => setNeeds(e.target.value)} />
      <button type="button" className="btn btn-danger" disabled={!owner.trim() && !needs.trim()} onClick={() => onMutate(async () => { await api.patchTask(task.id, { blocked: { owner: owner.trim(), needs: needs.trim() } }); setEditing(false); setOwner(""); setNeeds(""); })}>Save Block</button>
      <button type="button" className="btn" onClick={() => setEditing(false)}>Cancel</button>
    </div>
  );
}

function ReposSection({ repos }: { repos: TaskDetail["repos"] }) {
  if (repos.length === 0) return null;
  return (
    <div>
      <div style={{ fontSize: "0.8rem", fontWeight: 600, marginBottom: 4 }}>Bound Repos ({repos.length})</div>
      <div className="list-stack" style={{ gap: 4 }}>
        {repos.map((r, i) => (
          <div key={i} style={{ fontSize: "0.78rem", color: "var(--text-muted)", display: "flex", gap: 8, flexWrap: "wrap" }}>
            {r.path && <span style={{ color: "var(--text)" }}>{r.path}</span>}
            {r.branch && <span className="pill">{r.branch}</span>}
            {r.pr && <span className="pill pill-cyan">{r.pr}</span>}
          </div>
        ))}
      </div>
    </div>
  );
}

function LinksSection({ task, onMutate }: { task: TaskDetail; onMutate: (fn: () => Promise<unknown>) => void }) {
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");
  return (
    <div>
      <div style={{ fontSize: "0.8rem", fontWeight: 600, marginBottom: 4 }}>Links ({task.links.length})</div>
      {task.links.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 6 }}>
          {task.links.map((l, i) => (
            <a key={i} href={l.url} target="_blank" rel="noreferrer" className="pill" style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
              <ExternalLink size={12} /> {l.title || l.url}
            </a>
          ))}
        </div>
      )}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        <input className="input" style={{ flex: 1, minWidth: 120 }} placeholder="Link title..." value={title} onChange={(e) => setTitle(e.target.value)} />
        <input className="input" style={{ flex: 2, minWidth: 160 }} placeholder="https://..." value={url} onChange={(e) => setUrl(e.target.value)} />
        <button type="button" className="btn" disabled={!title.trim() || !url.trim()} onClick={() => onMutate(async () => { await api.addLink(task.id, title.trim(), url.trim()); setTitle(""); setUrl(""); })}>Add Link</button>
      </div>
    </div>
  );
}

function SubtasksSection({ subtasks, onSelectTask }: { subtasks: string[]; onSelectTask?: (id: string) => void }) {
  if (subtasks.length === 0) return null;
  return (
    <div>
      <div style={{ fontSize: "0.8rem", fontWeight: 600, marginBottom: 4 }}>Subtasks ({subtasks.length})</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {subtasks.map((subId) => (
          <button key={subId} type="button" className="btn" onClick={() => onSelectTask?.(subId)}>{subId}</button>
        ))}
      </div>
    </div>
  );
}

function ActivityLogSection({ logLines }: { logLines: string[] }) {
  if (logLines.length === 0) return null;
  const recent = logLines.slice(-30);
  return (
    <div>
      <div style={{ fontSize: "0.8rem", fontWeight: 600, marginBottom: 4 }}>Activity Log ({recent.length})</div>
      <div className="log-timeline">
        {recent.map((line, i) => <div key={i} style={{ fontSize: "0.75rem" }}>{line}</div>)}
      </div>
    </div>
  );
}

function findJiraUrl(links: TaskDetail["links"]): string {
  const hit = links.find(
    (l) => l.url.includes("/browse/") || l.title.toLowerCase().startsWith("jira")
  );
  return hit?.url ?? "";
}

function DrawerHeader(props: {
  task: TaskDetail;
  titleDraft: string;
  onTitleDraft: (v: string) => void;
  onMutate: (fn: () => Promise<unknown>) => void;
  onArchived?: (ref: string) => void;
}) {
  const { task, titleDraft, onTitleDraft, onMutate, onArchived } = props;
  const jiraUrl = findJiraUrl(task.links);
  return (
    <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
      <div style={{ flex: 1, minWidth: 200 }}>
        <div style={{ fontSize: "0.75rem", color: "var(--cyan)", fontWeight: 600 }}>{task.id}</div>
        <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
          <input className="input" aria-label="Title" value={titleDraft} onChange={(e) => onTitleDraft(e.target.value)} />
          <button type="button" className="btn" onClick={() => onMutate(() => api.patchTask(task.id, { title: titleDraft }))}>Save</button>
        </div>
      </div>
      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
        {jiraUrl && (
          <a href={jiraUrl} target="_blank" rel="noreferrer" className="btn btn-primary" style={{ textDecoration: "none" }}>
            <ExternalLink size={14} /> Open in Jira
          </a>
        )}
        <select className="select" style={{ width: "auto" }} value={task.status} onChange={(e) => onMutate(() => api.patchTask(task.id, { status: e.target.value }))}>
          <option value="active">active</option>
          <option value="paused">paused</option>
          <option value="closed">closed</option>
        </select>
        <button type="button" className="btn" onClick={() => onMutate(async () => { const res = await api.archiveTask(task.id); onArchived?.(res.ref); })}>
          <Archive size={14} /> Archive to Brain
        </button>
      </div>
    </div>
  );
}

export function TaskDetailDrawer({ task, onRefresh, onArchived, onSelectTask }: TaskDetailDrawerProps) {
  const [titleDraft, setTitleDraft] = useState(task.title);
  const [phaseDraft, setPhaseDraft] = useState(task.phase);
  const [summaryDraft, setSummaryDraft] = useState(task.summary);
  const [error, setError] = useState("");

  useEffect(() => {
    setTitleDraft(task.title);
    setPhaseDraft(task.phase);
    setSummaryDraft(task.summary);
  }, [task.id, task.title, task.phase, task.summary]);

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
      <DrawerHeader task={task} titleDraft={titleDraft} onTitleDraft={setTitleDraft} onMutate={(fn) => void mutate(fn)} onArchived={onArchived} />
      {error && <div className="alert-error">{error}</div>}
      <BlockedSection task={task} onMutate={(fn) => void mutate(fn)} />
      <div className="form-grid-2">
        <div style={{ display: "flex", gap: 6 }}>
          <input className="input" aria-label="Phase" placeholder="Phase..." value={phaseDraft} onChange={(e) => setPhaseDraft(e.target.value)} />
          <button type="button" className="btn" onClick={() => void mutate(() => api.patchTask(task.id, { phase: phaseDraft }))}>Save</button>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <input className="input" aria-label="Summary" placeholder="Summary..." value={summaryDraft} onChange={(e) => setSummaryDraft(e.target.value)} />
          <button type="button" className="btn" onClick={() => void mutate(() => api.patchTask(task.id, { summary: summaryDraft }))}>Save</button>
        </div>
      </div>
      <StepsSection task={task} onMutate={(fn) => void mutate(fn)} />
      <div className="form-grid-2">
        <FactsSection task={task} onMutate={(fn) => void mutate(fn)} />
        <DecisionsSection task={task} onMutate={(fn) => void mutate(fn)} />
      </div>
      <ReposSection repos={task.repos} />
      <LinksSection task={task} onMutate={(fn) => void mutate(fn)} />
      <SubtasksSection subtasks={task.subtasks} onSelectTask={onSelectTask} />
      <ActivityLogSection logLines={task.log_lines} />
      <DebatePanel task={task} onRefresh={onRefresh} />
    </div>
  );
}
