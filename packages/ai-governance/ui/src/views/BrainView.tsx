import { useState } from "react";
import { List, Network, Plus } from "lucide-react";
import { NeuralGraph } from "../components/NeuralGraph";
import { NoteDrawer } from "../components/NoteDrawer";
import type { BrainGraph, BrainNote } from "../types";

interface BrainViewProps {
  graph: BrainGraph | null;
  notes: BrainNote[];
  scopes: string[];
  kinds: string[];
  selectedNote: { note: BrainNote; backlinks: { ref: string; title: string; kind: string }[] } | null;
  scopeFilter: string;
  kindFilter: string;
  includeHubs: boolean;
  onChangeFilter: (next: { scope?: string; kind?: string; hubs?: boolean }) => void;
  onSelectNote: (scope: string, slug: string) => void;
  onSelectTask: (taskId: string) => void;
  onClearNote: () => void;
  onRefresh: () => void;
}

function BrainToolbar(props: {
  mode: "graph" | "list";
  noteCount: number;
  scopes: string[];
  kinds: string[];
  scopeFilter: string;
  kindFilter: string;
  includeHubs: boolean;
  onMode: (m: "graph" | "list") => void;
  onChangeFilter: (next: { scope?: string; kind?: string; hubs?: boolean }) => void;
  onNewNote: () => void;
}) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
        <button type="button" className={`btn ${props.mode === "graph" ? "btn-primary" : ""}`} onClick={() => props.onMode("graph")}>
          <Network size={14} /> Neural Graph
        </button>
        <button type="button" className={`btn ${props.mode === "list" ? "btn-primary" : ""}`} onClick={() => props.onMode("list")}>
          <List size={14} /> Notes ({props.noteCount})
        </button>
        <select className="select" style={{ width: "auto" }} value={props.scopeFilter} onChange={(e) => props.onChangeFilter({ scope: e.target.value })}>
          <option value="">All scopes</option>
          {props.scopes.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select className="select" style={{ width: "auto" }} value={props.kindFilter} onChange={(e) => props.onChangeFilter({ kind: e.target.value })}>
          <option value="">All kinds</option>
          {props.kinds.map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
        {props.mode === "graph" && (
          <label style={{ display: "inline-flex", gap: 5, fontSize: "0.82rem", alignItems: "center" }}>
            <input type="checkbox" checked={props.includeHubs} onChange={(e) => props.onChangeFilter({ hubs: e.target.checked })} />
            Show Tag/Repo hubs
          </label>
        )}
      </div>
      <button type="button" className="btn btn-primary" onClick={props.onNewNote}><Plus size={14} /> New Note</button>
    </div>
  );
}

function NotesList({ notes, selectedRef, onSelect }: { notes: BrainNote[]; selectedRef?: string; onSelect: (sc: string, sl: string) => void }) {
  return (
    <div className="list-stack">
      {notes.map((n) => (
        <button key={n.ref} type="button" className={`item-card ${selectedRef === n.ref ? "selected" : ""}`} onClick={() => onSelect(n.scope, n.slug)}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.75rem" }}>
            <span style={{ color: "var(--text-muted)" }}>{n.ref}</span>
            <span className="pill pill-cyan">{n.kind}</span>
          </div>
          <div style={{ fontWeight: 600, marginTop: 4 }}>{n.title}</div>
        </button>
      ))}
    </div>
  );
}

function BrainCanvasArea(props: {
  mode: "graph" | "list";
  graph: BrainGraph | null;
  notes: BrainNote[];
  selectedNote: BrainViewProps["selectedNote"];
  onPickNote: (sc: string, sl: string) => void;
  onSelectTask: (id: string) => void;
}) {
  if (props.mode === "graph" && props.graph) {
    return (
      <NeuralGraph
        graph={props.graph}
        selectedNodeId={props.selectedNote ? `note:${props.selectedNote.note.ref}` : undefined}
        onSelectNote={props.onPickNote}
        onSelectTask={props.onSelectTask}
      />
    );
  }
  return <NotesList notes={props.notes} selectedRef={props.selectedNote?.note.ref} onSelect={props.onPickNote} />;
}

export function BrainView(props: BrainViewProps) {
  const [mode, setMode] = useState<"graph" | "list">("graph");
  const [creating, setCreating] = useState(false);

  const openByRef = (ref: string) => {
    if (ref.includes("/")) {
      const [sc, sl] = ref.split("/", 2);
      props.onSelectNote(sc, sl);
      return;
    }
    const found = props.notes.find((n) => n.slug === ref);
    if (found) props.onSelectNote(found.scope, found.slug);
  };

  return (
    <div className="list-stack" style={{ gap: "0.85rem" }}>
      <BrainToolbar
        mode={mode} noteCount={props.notes.length} scopes={props.scopes} kinds={props.kinds}
        scopeFilter={props.scopeFilter} kindFilter={props.kindFilter} includeHubs={props.includeHubs}
        onMode={setMode} onChangeFilter={props.onChangeFilter}
        onNewNote={() => { props.onClearNote(); setCreating(true); }}
      />
      <div className={props.selectedNote || creating ? "split-layout" : ""}>
        <BrainCanvasArea
          mode={mode} graph={props.graph} notes={props.notes} selectedNote={props.selectedNote}
          onPickNote={(sc, sl) => { setCreating(false); props.onSelectNote(sc, sl); }}
          onSelectTask={props.onSelectTask}
        />
        {(props.selectedNote || creating) && (
          <NoteDrawer
            note={creating ? null : props.selectedNote?.note ?? null}
            backlinks={creating ? [] : props.selectedNote?.backlinks ?? []}
            kinds={props.kinds} scopes={props.scopes} isNew={creating}
            onClose={() => { setCreating(false); props.onClearNote(); }}
            onSaved={(saved) => { setCreating(false); props.onRefresh(); props.onSelectNote(saved.scope, saved.slug); }}
            onNavigateRef={openByRef}
          />
        )}
      </div>
    </div>
  );
}
