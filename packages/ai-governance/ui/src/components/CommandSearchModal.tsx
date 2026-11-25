import { useEffect, useState } from "react";
import { Search, X } from "lucide-react";
import { api } from "../api";
import type { SearchHit } from "../types";

interface CommandSearchModalProps {
  onClose: () => void;
  onSelectTask: (id: string) => void;
  onSelectNote: (ref: string) => void;
}

export function CommandSearchModal({
  onClose,
  onSelectTask,
  onSelectNote,
}: CommandSearchModalProps) {
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);

  useEffect(() => {
    const trimmed = query.trim();
    if (!trimmed) {
      setHits([]);
      return;
    }
    const timer = setTimeout(() => {
      void api.searchAll(trimmed).then((res) => setHits(res.hits)).catch(() => setHits([]));
    }, 150);
    return () => clearTimeout(timer);
  }, [query]);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel list-stack" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <Search size={16} color="#38bdf8" />
          <input
            autoFocus
            className="input"
            placeholder="Search Second Brain notes, Taskflow tasks, and rules..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button type="button" className="btn" onClick={onClose}>
            <X size={14} />
          </button>
        </div>
        <div className="list-stack" style={{ maxHeight: 360, overflowY: "auto" }}>
          {hits.map((hit, idx) => (
            <button
              key={`${hit.source}-${hit.ref}-${idx}`}
              type="button"
              className="item-card"
              onClick={() => {
                if (hit.source === "taskflow") onSelectTask(hit.ref);
                else if (hit.source === "brain") onSelectNote(hit.ref);
                onClose();
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.75rem" }}>
                <span className="pill pill-cyan">{hit.source}</span>
                <span style={{ color: "var(--text-muted)" }}>{hit.ref}</span>
              </div>
              <div style={{ fontWeight: 600, marginTop: 4 }}>{hit.title}</div>
              {hit.snippet && (
                <div style={{ fontSize: "0.78rem", color: "var(--text-muted)", marginTop: 2 }}>
                  {hit.snippet}
                </div>
              )}
            </button>
          ))}
          {query.trim() && hits.length === 0 && (
            <div style={{ fontSize: "0.84rem", color: "var(--text-muted)", padding: "0.5rem" }}>
              No matches found.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
