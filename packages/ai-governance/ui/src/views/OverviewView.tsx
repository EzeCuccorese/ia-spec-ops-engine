import type { ReactNode } from "react";
import { AlertTriangle, BrainCircuit, CheckCircle2, Clock, Cpu, ListTodo } from "lucide-react";
import type { BrainGraph, BrainNote, GraphNode, TaskSummary, WorkersResponse } from "../types";

interface OverviewViewProps {
  tasks: TaskSummary[];
  notes: BrainNote[];
  graph: BrainGraph | null;
  workers: WorkersResponse | null;
  onNavigate: (tab: "taskflow" | "brain" | "workers") => void;
  onSelectTask: (id: string) => void;
  onSelectNote: (scope: string, slug: string) => void;
}

function StatCard({ label, value, sub, color }: { label: string; value: number; sub: string; color: string }) {
  return (
    <div className="card">
      <div className="stat-label">{label}</div>
      <div className="stat-value" style={{ color }}>{value}</div>
      <div style={{ fontSize: "0.78rem", color: "var(--text-muted)", marginTop: 4 }}>{sub}</div>
    </div>
  );
}

function RecentTasksCard({
  tasks,
  onNavigate,
  onSelectTask,
}: {
  tasks: TaskSummary[];
  onNavigate: (tab: "taskflow" | "brain" | "workers") => void;
  onSelectTask: (id: string) => void;
}) {
  return (
    <div className="card list-stack">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ display: "inline-flex", gap: 6, alignItems: "center", fontWeight: 600 }}>
          <ListTodo size={16} color="#38bdf8" /> Recent Tasks
        </span>
        <button type="button" className="btn" onClick={() => onNavigate("taskflow")}>Open Board</button>
      </div>
      {tasks.slice(0, 6).map((t) => (
        <button key={t.id} type="button" className="item-card" onClick={() => onSelectTask(t.id)}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.76rem" }}>
            <span style={{ color: "var(--cyan)", fontWeight: 600 }}>{t.id}</span>
            <span className={`pill pill-${t.status}`}>{t.status}</span>
          </div>
          <div style={{ fontWeight: 600, marginTop: 3 }}>{t.title}</div>
          <div style={{ fontSize: "0.76rem", color: "var(--text-muted)", marginTop: 3 }}>
            <CheckCircle2 size={12} style={{ verticalAlign: "middle" }} /> {t.done_steps}/{t.total_steps} steps
          </div>
        </button>
      ))}
      {tasks.length === 0 && (
        <div style={{ fontSize: "0.84rem", color: "var(--text-muted)" }}>
          No tasks yet. Run <code>ai-governance taskflow new TASK-1 --title "..."</code>
        </div>
      )}
    </div>
  );
}

function TriageSection({ title, icon, children }: { title: string; icon: ReactNode; children: ReactNode }) {
  return (
    <div className="triage-group">
      <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: "0.8rem", fontWeight: 600 }}>
        {icon}
        <span>{title}</span>
      </div>
      {children}
    </div>
  );
}

function TaskTriageButton({ task, badge, pillClass, onSelect }: {
  task: TaskSummary;
  badge: string;
  pillClass: string;
  onSelect: (id: string) => void;
}) {
  return (
    <button type="button" className="item-card" onClick={() => onSelect(task.id)}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.75rem" }}>
        <span style={{ color: "var(--cyan)", fontWeight: 600 }}>{task.id}</span>
        <span className={`pill ${pillClass}`}>{badge}</span>
      </div>
      <div style={{ fontWeight: 600, marginTop: 2 }}>{task.title}</div>
    </button>
  );
}

function BrainHealthGroup({
  staleNotes,
  orphanNodes,
  onSelectNote,
}: {
  staleNotes: BrainNote[];
  orphanNodes: GraphNode[];
  onSelectNote: (scope: string, slug: string) => void;
}) {
  return (
    <TriageSection title="Brain Health" icon={<BrainCircuit size={14} color="#a78bfa" />}>
      {staleNotes.slice(0, 4).map((n) => (
        <button key={`stale-${n.ref}`} type="button" className="item-card" onClick={() => onSelectNote(n.scope, n.slug)}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.75rem" }}>
            <span style={{ color: "var(--text-muted)" }}>{n.ref}</span>
            <span className="pill pill-amber">stale</span>
          </div>
          <div style={{ fontWeight: 600, marginTop: 2 }}>{n.title}</div>
        </button>
      ))}
      {orphanNodes.slice(0, 4).map((n) => (
        <button key={`orphan-${n.id}`} type="button" className="item-card" onClick={() => onSelectNote(n.scope!, n.slug!)}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.75rem" }}>
            <span style={{ color: "var(--text-muted)" }}>{n.ref ?? `${n.scope}/${n.slug}`}</span>
            <span className="pill pill-violet">orphan</span>
          </div>
          <div style={{ fontWeight: 600, marginTop: 2 }}>{n.label}</div>
        </button>
      ))}
    </TriageSection>
  );
}

function TriageHeader({ onNavigate }: { onNavigate: (tab: "taskflow" | "brain" | "workers") => void }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
      <span style={{ display: "inline-flex", gap: 6, alignItems: "center", fontWeight: 600 }}>
        <AlertTriangle size={16} color="#fbbf24" /> Needs Attention (Triage)
      </span>
      <div style={{ display: "flex", gap: 6 }}>
        <button type="button" className="btn btn-primary" onClick={() => onNavigate("brain")}>Neural Graph</button>
        <button type="button" className="btn" onClick={() => onNavigate("workers")}><Cpu size={14} /> Workers</button>
      </div>
    </div>
  );
}

function TriagePanel(props: {
  tasks: TaskSummary[];
  notes: BrainNote[];
  graph: BrainGraph | null;
  onNavigate: (tab: "taskflow" | "brain" | "workers") => void;
  onSelectTask: (id: string) => void;
  onSelectNote: (scope: string, slug: string) => void;
}) {
  const blocked = props.tasks.filter((t) => Object.keys(t.blocked || {}).length > 0);
  const pending = props.tasks.filter((t) => t.pending_rounds > 0);
  const staleNotes = props.notes.filter((n) => n.stale);
  const orphanNodes = (props.graph?.nodes ?? []).filter((n) => Boolean(n.orphan && n.scope && n.slug));
  const emptyTriage = blocked.length === 0 && pending.length === 0 && staleNotes.length === 0 && orphanNodes.length === 0;

  return (
    <div className="card list-stack">
      <TriageHeader onNavigate={props.onNavigate} />
      {blocked.length > 0 && (
        <TriageSection title="Blocked Tasks" icon={<AlertTriangle size={14} color="#fb7185" />}>
          {blocked.map((t) => (
            <TaskTriageButton key={t.id} task={t} badge="blocked" pillClass="pill-rose" onSelect={props.onSelectTask} />
          ))}
        </TriageSection>
      )}
      {pending.length > 0 && (
        <TriageSection title="Pending Debate Rounds" icon={<Clock size={14} color="#fbbf24" />}>
          {pending.map((t) => (
            <TaskTriageButton key={t.id} task={t} badge={`${t.pending_rounds} pending`} pillClass="pill-amber" onSelect={props.onSelectTask} />
          ))}
        </TriageSection>
      )}
      {(staleNotes.length > 0 || orphanNodes.length > 0) && (
        <BrainHealthGroup staleNotes={staleNotes} orphanNodes={orphanNodes} onSelectNote={props.onSelectNote} />
      )}
      {emptyTriage && (
        <div className="triage-group" style={{ fontSize: "0.83rem", color: "var(--text-muted)", lineHeight: 1.55 }}>
          <div>All clear — no blocked tasks, pending debate rounds, or stale/orphan notes.</div>
          <div>
            Quick CLI: <code>ai-governance taskflow new &lt;id&gt; --title "..."</code> · <code>ai-governance brain add --title "..."</code>
          </div>
        </div>
      )}
    </div>
  );
}

export function OverviewView(props: OverviewViewProps) {
  const activeCount = props.tasks.filter((t) => t.status === "active").length;
  const staleCount = props.notes.filter((n) => n.stale).length;
  const runningCount = props.workers?.workers.filter((w) => w.running).length ?? 0;

  return (
    <div className="list-stack" style={{ gap: "1rem" }}>
      <div className="grid-stats">
        <StatCard label="Active Tasks" value={activeCount} sub={`${props.tasks.length} total tracked`} color="var(--cyan)" />
        <StatCard label="Second Brain Notes" value={props.notes.length} sub={`${props.graph?.stats.links ?? 0} synaptic links · ${staleCount} stale`} color="var(--violet)" />
        <StatCard label="Live Orca Workers" value={runningCount} sub={props.workers?.available ? `${props.workers.workers.length} reported` : "Orca offline"} color="var(--emerald)" />
      </div>
      <div className="split-layout">
        <RecentTasksCard tasks={props.tasks} onNavigate={props.onNavigate} onSelectTask={props.onSelectTask} />
        <TriagePanel
          tasks={props.tasks}
          notes={props.notes}
          graph={props.graph}
          onNavigate={props.onNavigate}
          onSelectTask={props.onSelectTask}
          onSelectNote={props.onSelectNote}
        />
      </div>
    </div>
  );
}
