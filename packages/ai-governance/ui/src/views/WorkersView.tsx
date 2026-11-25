import { RefreshCw } from "lucide-react";
import type { WorkersResponse } from "../types";

interface WorkersViewProps {
  workers: WorkersResponse | null;
  onRefresh: () => void;
}

export function WorkersView({ workers, onRefresh }: WorkersViewProps) {
  return (
    <div className="card list-stack">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <h2 style={{ margin: 0, fontSize: "1.05rem" }}>Orca Live Workers</h2>
          <div style={{ fontSize: "0.78rem", color: "var(--text-muted)" }}>
            Read-only status from <code>orca worker-list</code>
          </div>
        </div>
        <button type="button" className="btn" onClick={onRefresh}>
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      {workers && !workers.available && (
        <div className="alert-error">{workers.reason || "Orca CLI is unavailable"}</div>
      )}

      {workers?.workers.length === 0 ? (
        <div style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>
          No active or recent Orca workers found.
        </div>
      ) : (
        <div className="list-stack">
          {workers?.workers.map((w) => (
            <div
              key={w.dispatch_id}
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: "0.6rem 0.75rem",
                border: "1px solid var(--border)",
                borderRadius: 8,
                fontSize: "0.84rem",
              }}
            >
              <div>
                <strong>{w.dispatch_id}</strong> ·{" "}
                <span style={{ color: "var(--text-muted)" }}>{w.agent || "unknown agent"}</span>
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                <span className={`pill ${w.running ? "pill-emerald" : ""}`}>{w.state}</span>
                <span className="pill">{w.liveness}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
