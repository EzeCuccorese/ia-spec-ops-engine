import { useEffect, useState, type KeyboardEvent } from "react";
import { ArrowLeft, Search, X } from "lucide-react";
import { api } from "../api";
import type { SearchHit } from "../types";

interface CommandSearchModalProps {
  onClose: () => void;
  onSelectTask: (id: string) => void;
  onSelectNote: (ref: string) => void;
}

function RulePreviewCard({ hit, onBack }: { hit: SearchHit; onBack: () => void }) {
  return (
    <div className="card list-stack" style={{ gap: "0.6rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
        <button type="button" className="btn" onClick={onBack}>
          <ArrowLeft size={14} /> Back
        </button>
        <div style={{ display: "flex", gap: 6, alignItems: "center", fontSize: "0.75rem" }}>
          <span className="pill pill-violet">{hit.source}</span>
          <span style={{ color: "var(--text-muted)" }}>{hit.ref}</span>
        </div>
      </div>
      <div style={{ fontWeight: 700, fontSize: "0.96rem" }}>{hit.title}</div>
      {(hit.scope || hit.kind) && (
        <div style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
          {[hit.scope, hit.kind].filter(Boolean).join(" · ")}
        </div>
      )}
      <div style={{ fontSize: "0.84rem", lineHeight: 1.55, whiteSpace: "pre-wrap", color: "var(--text)" }}>
        {hit.snippet || "No preview snippet available."}
      </div>
    </div>
  );
}

function SearchHitButton({
  hit,
  selected,
  onSelect,
}: {
  hit: SearchHit;
  selected: boolean;
  onSelect: (hit: SearchHit) => void;
}) {
  return (
    <button
      type="button"
      className={`item-card ${selected ? "selected" : ""}`}
      onClick={() => onSelect(hit)}
    >
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.75rem" }}>
        <span className="pill pill-cyan">{hit.source}</span>
        <span style={{ color: "var(--text-muted)" }}>{hit.ref}</span>
      </div>
      <div style={{ fontWeight: 600, marginTop: 4 }}>{hit.title}</div>
      {hit.snippet && (
        <div style={{ fontSize: "0.78rem", color: "var(--text-muted)", marginTop: 2 }}>{hit.snippet}</div>
      )}
    </button>
  );
}

export function CommandSearchModal({ onClose, onSelectTask, onSelectNote }: CommandSearchModalProps) {
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [activeIndex, setActiveIndex] = useState(0);
  const [previewRule, setPreviewRule] = useState<SearchHit | null>(null);

  useEffect(() => {
    setPreviewRule(null);
    const trimmed = query.trim();
    if (!trimmed) {
      setHits([]);
      setActiveIndex(0);
      return;
    }
    const timer = setTimeout(() => {
      void api.searchAll(trimmed).then((res) => {
        setHits(res.hits);
        setActiveIndex(0);
      }).catch(() => setHits([]));
    }, 150);
    return () => clearTimeout(timer);
  }, [query]);

  const activateHit = (hit: SearchHit) => {
    if (hit.source === "taskflow") { onSelectTask(hit.ref); onClose(); return; }
    if (hit.source === "brain") { onSelectNote(hit.ref); onClose(); return; }
    if (hit.source === "rules") { setPreviewRule(hit); return; }
    onClose();
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") { e.preventDefault(); onClose(); return; }
    if (hits.length === 0) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setActiveIndex((i) => (i + 1) % hits.length); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActiveIndex((i) => (i - 1 + hits.length) % hits.length); }
    else if (e.key === "Enter" && hits[activeIndex]) { e.preventDefault(); activateHit(hits[activeIndex]); }
  };

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
            onKeyDown={handleKeyDown}
          />
          <button type="button" className="btn" onClick={onClose}><X size={14} /></button>
        </div>
        {previewRule ? (
          <RulePreviewCard hit={previewRule} onBack={() => setPreviewRule(null)} />
        ) : (
          <div className="list-stack" style={{ maxHeight: 360, overflowY: "auto" }}>
            {hits.map((hit, idx) => (
              <SearchHitButton key={`${hit.source}-${hit.ref}-${idx}`} hit={hit} selected={idx === activeIndex} onSelect={activateHit} />
            ))}
            {query.trim() && hits.length === 0 && (
              <div style={{ fontSize: "0.84rem", color: "var(--text-muted)", padding: "0.5rem" }}>No matches found.</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
