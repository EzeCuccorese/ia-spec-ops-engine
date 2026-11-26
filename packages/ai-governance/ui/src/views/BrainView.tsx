import { useMemo, useState } from "react";
import { List, Network, Plus, X } from "lucide-react";
import { NeuralGraph } from "../components/NeuralGraph";
import { NoteDrawer } from "../components/NoteDrawer";
import type { BrainFilters, BrainGraph, BrainNote, NoteBacklink } from "../types";

interface BrainViewProps {
  graph: BrainGraph | null;
  notes: BrainNote[];
  allNotes: BrainNote[];
  scopes: string[];
  kinds: string[];
  repos: string[];
  tags: string[];
  selectedNote: { note: BrainNote; backlinks: NoteBacklink[] } | null;
  filters: BrainFilters;
  onChangeFilter: (next: Partial<BrainFilters>) => void;
  onSelectNote: (scope: string, slug: string) => void;
  onSelectTask: (taskId: string) => void;
  onClearNote: () => void;
  onRefresh: () => void;
}

function hasActiveFilters(filters: BrainFilters): boolean {
  return Boolean(
    filters.scope || filters.kind || filters.repo || filters.tag || filters.staleOnly || filters.orphansOnly
  );
}

function FilterSelects(props: {
  scopes: string[];
  kinds: string[];
  repos: string[];
  tags: string[];
  filters: BrainFilters;
  onChangeFilter: (next: Partial<BrainFilters>) => void;
}) {
  const { filters, onChangeFilter } = props;
  return (
    <>
      <select className="select" style={{ width: "auto" }} value={filters.scope} onChange={(e) => onChangeFilter({ scope: e.target.value })}>
        <option value="">All scopes</option>
        {props.scopes.map((s) => <option key={s} value={s}>{s}</option>)}
      </select>
      <select className="select" style={{ width: "auto" }} value={filters.kind} onChange={(e) => onChangeFilter({ kind: e.target.value })}>
        <option value="">All kinds</option>
        {props.kinds.map((k) => <option key={k} value={k}>{k}</option>)}
      </select>
      <select className="select" style={{ width: "auto" }} value={filters.repo} onChange={(e) => onChangeFilter({ repo: e.target.value })}>
        <option value="">All repos</option>
        {props.repos.map((r) => <option key={r} value={r}>{r}</option>)}
      </select>
      <select className="select" style={{ width: "auto" }} value={filters.tag} onChange={(e) => onChangeFilter({ tag: e.target.value })}>
        <option value="">All tags</option>
        {props.tags.map((t) => <option key={t} value={t}>#{t}</option>)}
      </select>
    </>
  );
}

function FilterToggles(props: {
  mode: "graph" | "list";
  filters: BrainFilters;
  onChangeFilter: (next: Partial<BrainFilters>) => void;
}) {
  const { filters, onChangeFilter } = props;
  return (
    <>
      <label style={{ display: "inline-flex", gap: 5, fontSize: "0.82rem", alignItems: "center" }}>
        <input type="checkbox" checked={filters.staleOnly} onChange={(e) => onChangeFilter({ staleOnly: e.target.checked })} />
        Stale only
      </label>
      <label style={{ display: "inline-flex", gap: 5, fontSize: "0.82rem", alignItems: "center" }}>
        <input type="checkbox" checked={filters.orphansOnly} onChange={(e) => onChangeFilter({ orphansOnly: e.target.checked })} />
        Orphans only
      </label>
      {props.mode === "graph" && (
        <label style={{ display: "inline-flex", gap: 5, fontSize: "0.82rem", alignItems: "center" }}>
          <input type="checkbox" checked={filters.hubs} onChange={(e) => onChangeFilter({ hubs: e.target.checked })} />
          Hubs
        </label>
      )}
      {hasActiveFilters(filters) && (
        <button
          type="button"
          className="btn"
          onClick={() => onChangeFilter({ scope: "", kind: "", repo: "", tag: "", staleOnly: false, orphansOnly: false })}
        >
          <X size={13} /> Clear
        </button>
      )}
    </>
  );
}

function BrainToolbar(props: {
  mode: "graph" | "list";
  noteCount: number;
  scopes: string[];
  kinds: string[];
  repos: string[];
  tags: string[];
  filters: BrainFilters;
  onMode: (m: "graph" | "list") => void;
  onChangeFilter: (next: Partial<BrainFilters>) => void;
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
        <FilterSelects
          scopes={props.scopes} kinds={props.kinds} repos={props.repos} tags={props.tags}
          filters={props.filters} onChangeFilter={props.onChangeFilter}
        />
        <FilterToggles mode={props.mode} filters={props.filters} onChangeFilter={props.onChangeFilter} />
      </div>
      <button type="button" className="btn btn-primary" onClick={props.onNewNote}><Plus size={14} /> New Note</button>
    </div>
  );
}

function NotesList(props: {
  notes: BrainNote[];
  orphanRefs: Set<string>;
  selectedRef?: string;
  onSelect: (sc: string, sl: string) => void;
}) {
  return (
    <div className="list-stack">
      {props.notes.map((n) => (
        <button key={n.ref} type="button" className={`item-card ${props.selectedRef === n.ref ? "selected" : ""}`} onClick={() => props.onSelect(n.scope, n.slug)}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.75rem", gap: 6 }}>
            <span style={{ color: "var(--text-muted)" }}>{n.ref}</span>
            <span style={{ color: "var(--text-muted)" }}>{n.updated.slice(0, 10)}</span>
          </div>
          <div style={{ fontWeight: 600, marginTop: 4 }}>{n.title}</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 6 }}>
            <span className="pill pill-cyan">{n.kind}</span>
            {n.stale && <span className="pill pill-amber">stale</span>}
            {props.orphanRefs.has(n.ref) && <span className="pill pill-rose">orphan</span>}
            {n.tags.map((t) => <span key={t} className="pill">#{t}</span>)}
            {n.repos.map((r) => <span key={r} className="pill pill-emerald">{r}</span>)}
          </div>
        </button>
      ))}
    </div>
  );
}

function BrainCanvasArea(props: {
  mode: "graph" | "list";
  graph: BrainGraph | null;
  notes: BrainNote[];
  orphanRefs: Set<string>;
  selectedNote: BrainViewProps["selectedNote"];
  onPickNote: (sc: string, sl: string) => void;
  onSelectTask: (id: string) => void;
  onSelectHub: (kind: "tag" | "repo", value: string) => void;
  onNewNote: () => void;
}) {
  if (props.mode === "graph" && props.graph) {
    return (
      <NeuralGraph
        graph={props.graph}
        selectedNodeId={props.selectedNote ? `note:${props.selectedNote.note.ref}` : undefined}
        onSelectNote={props.onPickNote}
        onSelectTask={props.onSelectTask}
        onSelectHub={props.onSelectHub}
        onNewNote={props.onNewNote}
      />
    );
  }
  return (
    <NotesList
      notes={props.notes}
      orphanRefs={props.orphanRefs}
      selectedRef={props.selectedNote?.note.ref}
      onSelect={props.onPickNote}
    />
  );
}

function resolveNoteByRef(ref: string, notes: BrainNote[]): BrainNote | undefined {
  if (ref.includes("/")) {
    const [sc, sl] = ref.split("/", 2);
    return notes.find((n) => n.scope === sc && n.slug === sl);
  }
  const lower = ref.toLowerCase();
  return notes.find((n) => n.slug === ref || n.title.toLowerCase() === lower);
}

function useOrphanRefs(graph: BrainGraph | null): Set<string> {
  return useMemo(() => {
    const set = new Set<string>();
    for (const n of graph?.nodes ?? []) {
      if (n.type === "note" && n.orphan && n.ref) set.add(n.ref);
    }
    return set;
  }, [graph]);
}

export function BrainView(props: BrainViewProps) {
  const [mode, setMode] = useState<"graph" | "list">("graph");
  const [creating, setCreating] = useState(false);
  const [initialTitle, setInitialTitle] = useState("");
  const orphanRefs = useOrphanRefs(props.graph);
  const visibleNotes = useMemo(
    () => (props.filters.orphansOnly ? props.notes.filter((n) => orphanRefs.has(n.ref)) : props.notes),
    [props.filters.orphansOnly, props.notes, orphanRefs]
  );

  const openNewNote = (title = "") => { props.onClearNote(); setInitialTitle(title); setCreating(true); };
  const closeDrawer = () => { setCreating(false); setInitialTitle(""); props.onClearNote(); };
  const openByRef = (ref: string) => {
    const found = resolveNoteByRef(ref, props.allNotes);
    if (found) { setCreating(false); props.onSelectNote(found.scope, found.slug); return; }
    openNewNote(ref.includes("/") ? ref.split("/", 2)[1] : ref);
  };

  return (
    <div className="list-stack" style={{ gap: "0.85rem" }}>
      <BrainToolbar
        mode={mode} noteCount={visibleNotes.length} scopes={props.scopes} kinds={props.kinds}
        repos={props.repos} tags={props.tags} filters={props.filters}
        onMode={setMode} onChangeFilter={props.onChangeFilter} onNewNote={() => openNewNote("")}
      />
      <div className={props.selectedNote || creating ? "split-layout" : ""}>
        <BrainCanvasArea
          mode={mode} graph={props.graph} notes={visibleNotes} orphanRefs={orphanRefs}
          selectedNote={props.selectedNote} onSelectTask={props.onSelectTask} onNewNote={() => openNewNote("")}
          onPickNote={(sc, sl) => { setCreating(false); props.onSelectNote(sc, sl); }}
          onSelectHub={(kind, value) => props.onChangeFilter(kind === "tag" ? { tag: value } : { repo: value })}
        />
        {(props.selectedNote || creating) && (
          <NoteDrawer
            note={creating ? null : props.selectedNote?.note ?? null}
            backlinks={creating ? [] : props.selectedNote?.backlinks ?? []}
            kinds={props.kinds} scopes={props.scopes} allNotes={props.allNotes}
            isNew={creating} initialTitle={initialTitle} onClose={closeDrawer} onNavigateRef={openByRef}
            onSaved={(saved) => { closeDrawer(); props.onRefresh(); props.onSelectNote(saved.scope, saved.slug); }}
          />
        )}
      </div>
    </div>
  );
}
