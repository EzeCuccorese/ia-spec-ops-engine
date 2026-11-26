import { useEffect, useState } from "react";
import { Play, RefreshCw, ShieldAlert } from "lucide-react";
import { ApiError, api } from "../api";
import type { PendingDispatch, TaskDetail } from "../types";
import { MarkdownView } from "./MarkdownView";

interface DebatePanelProps {
  task: TaskDetail;
  onRefresh: () => void;
}

function parseModels(raw: string): Record<string, string> | undefined {
  const models: Record<string, string> = {};
  for (const part of raw.split(",")) {
    const [k, v] = part.split("=").map((s) => s.trim());
    if (k && v) models[k] = v;
  }
  return Object.keys(models).length > 0 ? models : undefined;
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
  const [confirming, setConfirming] = useState(false);

  useEffect(() => setDid(rd.dispatch_id), [rd.dispatch_id]);

  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: 8, padding: "0.6rem", display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.83rem" }}>
        <span>Round #{String(rd.n).padStart(3, "0")} · {rd.role} ({rd.agent}/{rd.model || "default"})</span>
        <span className={`pill ${rd.launched ? "pill-emerald" : "pill-amber"}`}>{rd.launched ? "launched" : "reserved"}</span>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
        {!rd.launched && !confirming && (
          <button type="button" className="btn btn-primary" disabled={busy} onClick={() => setConfirming(true)}>
            <Play size={13} /> Launch Orca Worker
          </button>
        )}
        {!rd.launched && confirming && (
          <>
            <button type="button" className="btn btn-primary" disabled={busy} onClick={() => { setConfirming(false); onRun(() => api.launchRound(taskId, rd.n)); }}>
              Confirm Launch
            </button>
            <button type="button" className="btn" disabled={busy} onClick={() => setConfirming(false)}>Cancel</button>
          </>
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

function OpenDebateBox({
  busy,
  onOpen,
}: {
  busy: boolean;
  onOpen: (body: { topic: string; agents: string[]; web: boolean; models?: Record<string, string> }) => void;
}) {
  const [topic, setTopic] = useState("");
  const [agents, setAgents] = useState<string[]>(["claude", "codex"]);
  const [web, setWeb] = useState(false);
  const [modelsText, setModelsText] = useState("");
  const toggle = (a: string) => setAgents((p) => (p.includes(a) ? p.filter((x) => x !== a) : [...p, a]));

  return (
    <div className="card list-stack">
      <div style={{ fontSize: "0.82rem", color: "var(--text-muted)" }}>Open a blind multi-provider debate on this task:</div>
      <textarea className="textarea" rows={4} placeholder="Debate topic in Markdown..." value={topic} onChange={(e) => setTopic(e.target.value)} />
      <input className="input" placeholder="Models (optional, e.g. claude=sonnet, codex=gpt-6.2-sol)" value={modelsText} onChange={(e) => setModelsText(e.target.value)} />
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
        {["claude", "codex", "antigravity"].map((a) => (
          <label key={a} style={{ display: "inline-flex", gap: 4, fontSize: "0.82rem" }}>
            <input type="checkbox" checked={agents.includes(a)} onChange={() => toggle(a)} /> {a}
          </label>
        ))}
        <label style={{ display: "inline-flex", gap: 4, fontSize: "0.82rem" }}>
          <input type="checkbox" checked={web} onChange={(e) => setWeb(e.target.checked)} /> web research
        </label>
        <button
          type="button"
          className="btn btn-primary"
          disabled={busy || !topic.trim() || agents.length < 2}
          onClick={() => onOpen({ topic, agents, web, models: parseModels(modelsText) })}
        >
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
        <OpenDebateBox busy={busy} onOpen={(body) => void runAction(() => api.openDebate(task.id, body))} />
      ) : (
        <div className="card list-stack">
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "space-between" }}>
            <span className="pill pill-violet">Debate active ({task.debate.seats.length} seats)</span>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              <button type="button" className="btn" disabled={busy} onClick={() => void runAction(() => api.crossDebate(task.id))}>
                <RefreshCw size={13} /> Cross-Exam
              </button>
              <button type="button" className="btn" disabled={busy} onClick={() => void runAction(() => api.closeDebate(task.id, true))}>
                Close Partial
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
