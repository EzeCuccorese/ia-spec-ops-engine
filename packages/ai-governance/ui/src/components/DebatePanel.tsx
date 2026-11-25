import { useState } from "react";
import { Play, RefreshCw, ShieldAlert } from "lucide-react";
import { ApiError, api } from "../api";
import type { PendingDispatch, TaskDetail } from "../types";
import { MarkdownView } from "./MarkdownView";

interface DebatePanelProps {
  task: TaskDetail;
  onRefresh: () => void;
}

function PendingRoundRow({
  taskId,
  rd,
  busy,
  onRun,
}: {
  taskId: string;
  rd: PendingDispatch;
  busy: boolean;
  onRun: (fn: () => Promise<unknown>) => void;
}) {
  const [did, setDid] = useState(rd.dispatch_id);
  const [reason, setReason] = useState("");
  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: 8, padding: "0.6rem", display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.83rem" }}>
        <span>Round #{String(rd.n).padStart(3, "0")} · {rd.role} ({rd.agent}/{rd.model || "default"})</span>
        <span className={`pill ${rd.launched ? "pill-emerald" : "pill-amber"}`}>{rd.launched ? "launched" : "reserved"}</span>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
        {!rd.launched && (
          <button type="button" className="btn btn-primary" disabled={busy} onClick={() => { if (window.confirm(`Launch Orca worker for round #${rd.n}?`)) onRun(() => api.launchRound(taskId, rd.n)); }}>
            <Play size={13} /> Launch Orca Worker
          </button>
        )}
        <input className="input" style={{ maxWidth: 200 }} placeholder="Dispatch ID" value={did} onChange={(e) => setDid(e.target.value)} />
        <button type="button" className="btn" disabled={busy || !did.trim()} onClick={() => onRun(() => api.collectRound(taskId, rd.n, did.trim()))}>Collect</button>
        <input className="input" style={{ maxWidth: 170 }} placeholder="Abort reason" value={reason} onChange={(e) => setReason(e.target.value)} />
        <button type="button" className="btn btn-danger" disabled={busy || !reason.trim()} onClick={() => onRun(() => api.abortRound(taskId, rd.n, reason.trim(), did.trim()))}>
          <ShieldAlert size={13} /> Abort
        </button>
      </div>
    </div>
  );
}

function OpenDebateBox({ busy, onOpen }: { busy: boolean; onOpen: (topic: string, agents: string[]) => void }) {
  const [topic, setTopic] = useState("");
  const [agents, setAgents] = useState<string[]>(["claude", "codex"]);
  const toggle = (a: string) => setAgents((p) => (p.includes(a) ? p.filter((x) => x !== a) : [...p, a]));
  return (
    <div className="card list-stack">
      <div style={{ fontSize: "0.82rem", color: "var(--text-muted)" }}>Open a blind multi-provider debate on this task:</div>
      <textarea className="textarea" rows={4} placeholder="Debate topic in Markdown..." value={topic} onChange={(e) => setTopic(e.target.value)} />
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
        {["claude", "codex", "antigravity"].map((a) => (
          <label key={a} style={{ display: "inline-flex", gap: 4, fontSize: "0.82rem" }}>
            <input type="checkbox" checked={agents.includes(a)} onChange={() => toggle(a)} /> {a}
          </label>
        ))}
        <button type="button" className="btn btn-primary" disabled={busy || !topic.trim() || agents.length < 2} onClick={() => onOpen(topic, agents)}>
          Open Debate
        </button>
      </div>
    </div>
  );
}

export function DebatePanel({ task, onRefresh }: DebatePanelProps) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function runAction(fn: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await fn();
      onRefresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Operation failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="list-stack" style={{ marginTop: "0.75rem" }}>
      <h3 style={{ margin: 0, fontSize: "0.95rem" }}>Multi-Provider Debate & Orca Rounds</h3>
      {error && <div className="alert-error">{error}</div>}
      {!task.debate.active ? (
        <OpenDebateBox busy={busy} onOpen={(topic, agents) => void runAction(() => api.openDebate(task.id, { topic, agents }))} />
      ) : (
        <div className="card list-stack">
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "space-between" }}>
            <span className="pill pill-violet">Debate active ({task.debate.seats.length} seats)</span>
            <div style={{ display: "flex", gap: 6 }}>
              <button type="button" className="btn" disabled={busy} onClick={() => void runAction(() => api.crossDebate(task.id))}>
                <RefreshCw size={13} /> Cross-Exam
              </button>
              <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void runAction(() => api.closeDebate(task.id, false))}>
                Close & Synthesize
              </button>
            </div>
          </div>
          {task.debate.seats.map((seat, idx) => (
            <div key={idx} style={{ display: "flex", justifyContent: "space-between", fontSize: "0.82rem", padding: "0.35rem 0.5rem", background: "rgba(7,11,20,0.5)", borderRadius: 6 }}>
              <span><strong>{String(seat.focus ?? "")}</strong> ({String(seat.agent ?? "")})</span>
              <span className="pill">{String(seat.overall ?? seat.status ?? "pending")}</span>
            </div>
          ))}
        </div>
      )}
      {task.pending_dispatches.length > 0 && (
        <div className="card list-stack">
          <div style={{ fontSize: "0.82rem", fontWeight: 600 }}>Reserved Orca Rounds</div>
          {task.pending_dispatches.map((rd) => (
            <PendingRoundRow key={rd.n} taskId={task.id} rd={rd} busy={busy} onRun={(fn) => void runAction(fn)} />
          ))}
        </div>
      )}
      {task.debate.synthesis && (
        <div className="card">
          <div style={{ fontSize: "0.78rem", color: "var(--text-muted)", marginBottom: 4 }}>synthesis.md</div>
          <MarkdownView text={task.debate.synthesis} />
        </div>
      )}
    </div>
  );
}
