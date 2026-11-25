import { useEffect, useState } from "react";
import { Edit3, Save, X } from "lucide-react";
import { ApiError, api } from "../api";
import type { BrainNote } from "../types";
import { MarkdownView } from "./MarkdownView";

interface NoteDrawerProps {
  note: BrainNote | null;
  backlinks: { ref: string; title: string; kind: string }[];
  kinds: string[];
  scopes: string[];
  isNew?: boolean;
  onClose: () => void;
  onSaved: (note: BrainNote) => void;
  onNavigateRef: (ref: string) => void;
}

function splitCsv(raw: string): string[] {
  return raw.split(",").map((s) => s.trim()).filter(Boolean);
}

function initForm(note: BrainNote | null, kinds: string[], scopes: string[]) {
  return {
    title: note?.title ?? "",
    kind: note?.kind ?? kinds[0] ?? "gotcha",
    scope: note?.scope ?? scopes[0] ?? "personal",
    tagsRaw: note?.tags.join(", ") ?? "",
    reposRaw: note?.repos.join(", ") ?? "",
    body: note?.body ?? "",
  };
}

function NoteForm(props: {
  note: BrainNote | null;
  kinds: string[];
  scopes: string[];
  isNew: boolean;
  onCancel: () => void;
  onSaved: (note: BrainNote) => void;
  onError: (msg: string) => void;
}) {
  const initial = initForm(props.note, props.kinds, props.scopes);
  const [title, setTitle] = useState(initial.title);
  const [kind, setKind] = useState(initial.kind);
  const [scope, setScope] = useState(initial.scope);
  const [tagsRaw, setTagsRaw] = useState(initial.tagsRaw);
  const [reposRaw, setReposRaw] = useState(initial.reposRaw);
  const [body, setBody] = useState(initial.body);
  const [saving, setSaving] = useState(false);

  async function submit() {
    setSaving(true);
    props.onError("");
    const payload = { title, body, kind, tags: splitCsv(tagsRaw), repos: splitCsv(reposRaw), source: props.note?.source ?? "" };
    try {
      const res = props.isNew
        ? await api.createNote({ ...payload, scope })
        : await api.updateNote(props.note!.scope, props.note!.slug, payload);
      props.onSaved(res.note);
    } catch (err) {
      props.onError(err instanceof ApiError ? err.message : "Failed to save note");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="list-stack">
      <input className="input" placeholder="Title" value={title} onChange={(e) => setTitle(e.target.value)} />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        <select className="select" value={kind} onChange={(e) => setKind(e.target.value)}>
          {props.kinds.map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
        <input className="input" disabled={!props.isNew} value={scope} onChange={(e) => setScope(e.target.value)} />
      </div>
      <input className="input" placeholder="Tags (comma separated)" value={tagsRaw} onChange={(e) => setTagsRaw(e.target.value)} />
      <input className="input" placeholder="Repos (comma separated)" value={reposRaw} onChange={(e) => setReposRaw(e.target.value)} />
      <textarea className="textarea" rows={10} placeholder="Markdown body..." value={body} onChange={(e) => setBody(e.target.value)} />
      <div style={{ display: "flex", gap: 8 }}>
        <button type="button" className="btn btn-primary" disabled={saving} onClick={() => void submit()}>
          <Save size={14} /> {saving ? "Saving..." : "Save Note"}
        </button>
        {!props.isNew && <button type="button" className="btn" onClick={props.onCancel}>Cancel</button>}
      </div>
    </div>
  );
}

function NoteReader({ note, backlinks, onNavigateRef }: { note: BrainNote; backlinks: { ref: string; title: string; kind: string }[]; onNavigateRef: (ref: string) => void }) {
  return (
    <>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        <span className="pill pill-cyan">{note.kind}</span>
        {note.tags.map((t) => <span key={t} className="pill">#{t}</span>)}
        {note.repos.map((r) => <span key={r} className="pill pill-emerald">{r}</span>)}
      </div>
      <MarkdownView text={note.body} onWikilinkClick={onNavigateRef} />
      {backlinks.length > 0 && (
        <div style={{ borderTop: "1px solid var(--border)", paddingTop: "0.65rem" }}>
          <div style={{ fontSize: "0.76rem", color: "var(--text-muted)", marginBottom: 6 }}>Backlinks ({backlinks.length})</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {backlinks.map((b) => (
              <button key={b.ref} type="button" className="wikilink-btn" onClick={() => onNavigateRef(b.ref)}>{b.title}</button>
            ))}
          </div>
        </div>
      )}
    </>
  );
}

export function NoteDrawer({ note, backlinks, kinds, scopes, isNew = false, onClose, onSaved, onNavigateRef }: NoteDrawerProps) {
  const [editing, setEditing] = useState(isNew);
  const [error, setError] = useState("");
  useEffect(() => {
    setEditing(isNew);
    setError("");
  }, [note, isNew]);

  return (
    <div className="card" style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
        <div>
          <div style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>{isNew ? "New Brain Note" : note?.ref}</div>
          {!editing && <h2 style={{ margin: "0.15rem 0 0", fontSize: "1.1rem" }}>{note?.title}</h2>}
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          {!isNew && !editing && <button type="button" className="btn" onClick={() => setEditing(true)}><Edit3 size={14} /> Edit</button>}
          <button type="button" className="btn" onClick={onClose}><X size={14} /></button>
        </div>
      </div>
      {error && <div className="alert-error">{error}</div>}
      {editing ? (
        <NoteForm note={note} kinds={kinds} scopes={scopes} isNew={isNew} onCancel={() => setEditing(false)} onSaved={(saved) => { setEditing(false); onSaved(saved); }} onError={setError} />
      ) : (
        note && <NoteReader note={note} backlinks={backlinks} onNavigateRef={onNavigateRef} />
      )}
    </div>
  );
}
