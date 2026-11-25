import { BrainCircuit, CheckCircle2, Cpu, ListTodo } from "lucide-react";
import type { BrainGraph, BrainNote, TaskSummary, WorkersResponse } from "../types";

interface OverviewViewProps {
  tasks: TaskSummary[];
  notes: BrainNote[];
  graph: BrainGraph | null;
  workers: WorkersResponse | null;
  onNavigate: (tab: "taskflow" | "brain" | "workers") => void;
  onSelectTask: (id: string) => void;
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

export function OverviewView({ tasks, notes, graph, workers, onNavigate, onSelectTask }: OverviewViewProps) {
  const activeCount = tasks.filter((t) => t.status === "active").length;
  const staleCount = notes.filter((n) => n.stale).length;
  const runningCount = workers?.workers.filter((w) => w.running).length ?? 0;

  return (
    <div className="list-stack" style={{ gap: "1rem" }}>
      <div className="grid-stats">
        <StatCard label="Active Tasks" value={activeCount} sub={`${tasks.length} total tracked`} color="var(--cyan)" />
        <StatCard label="Second Brain Notes" value={notes.length} sub={`${graph?.stats.links ?? 0} synaptic links · ${staleCount} stale`} color="var(--violet)" />
        <StatCard label="Live Orca Workers" value={runningCount} sub={workers?.available ? `${workers.workers.length} reported` : "Orca offline"} color="var(--emerald)" />
      </div>
      <div className="split-layout">
        <div className="card list-stack">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ display: "inline-flex", gap: 6, alignItems: "center", fontWeight: 600 }}><ListTodo size={16} color="#38bdf8" /> Recent Tasks</span>
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
          {tasks.length === 0 && <div style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>No tasks yet.</div>}
        </div>
        <div className="card list-stack">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ display: "inline-flex", gap: 6, alignItems: "center", fontWeight: 600 }}><BrainCircuit size={16} color="#a78bfa" /> Neural Knowledge & Workers</span>
            <div style={{ display: "flex", gap: 6 }}>
              <button type="button" className="btn btn-primary" onClick={() => onNavigate("brain")}>Neural Graph</button>
              <button type="button" className="btn" onClick={() => onNavigate("workers")}><Cpu size={14} /> Workers</button>
            </div>
          </div>
          <div style={{ fontSize: "0.84rem", color: "var(--text-muted)", lineHeight: 1.55 }}>
            Explore Second Brain notes as an interactive force-directed neural network, edit Markdown notes with secret-content protection, and orchestrate Taskflow debates & Orca workers.
          </div>
        </div>
      </div>
    </div>
  );
}
