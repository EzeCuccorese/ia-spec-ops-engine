import { useEffect, useState } from "react";
import { Edit3, Eye, Pencil, Save, X } from "lucide-react";
import { ApiError, api } from "../api";
import type { BrainNote, NoteBacklink } from "../types";
import { MarkdownView } from "./MarkdownView";

interface NoteDrawerProps {
  note: BrainNote | null;
  backlinks: NoteBacklink[];
  kinds: string[];
  scopes: string[];
  allNotes?: BrainNote[];
  isNew?: boolean;
  initialTitle?: string;
  onClose: () => void;
  onSaved: (note: BrainNote) => void;
  onNavigateRef: (ref: string) => void;
}

function splitCsv(raw: string): string[] {
  return raw.split(",").map((s) => s.trim()).filter(Boolean);
}

function initForm(note: BrainNote | null, kinds: string[], scopes: string[], initialTitle?: string) {
  return {
    title: note?.title ?? initialTitle ?? "",
    kind: note?.kind ?? kinds[0] ?? "gotcha",
    scope: note?.scope ?? scopes[0] ?? "personal",
    tagsRaw: note?.tags.join(", ") ?? "",
    reposRaw: note?.repos.join(", ") ?? "",
    body: note?.body ?? "",
  };
}

function BodyEditorToolbar(props: {
  preview: boolean;
  allNotes: BrainNote[];
  onTogglePreview: (p: boolean) => void;
  onInsertLink: (ref: string) => void;
}) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
      <div style={{ display: "flex", gap: 6 }}>
        <button type="button" className={`btn ${!props.preview ? "btn-primary" : ""}`} onClick={() => props.onTogglePreview(false)}>
          <Pencil size={13} /> Write
        </button>
        <button type="button" className={`btn ${props.preview ? "btn-primary" : ""}`} onClick={() => props.onTogglePreview(true)}>
          <Eye size={13} /> Preview
        </button>
      </div>
      <select
        className="select"
        style={{ width: "auto" }}
        value=""
        onChange={(e) => { if (e.target.value) props.onInsertLink(e.target.value); }}
      >
        <option value="">Insert [[link]]...</option>
        {props.allNotes.map((n) => (
          <option key={n.ref} value={n.ref}>{n.title} ({n.ref})</option>
        ))}
      </select>
    </div>
  );
}

function NoteFormFields(props: {
  title: string;
  kind: string;
  scope: string;
  tagsRaw: string;
  reposRaw: string;
  kinds: string[];
  isNew: boolean;
  onTitle: (v: string) => void;
  onKind: (v: string) => void;
  onScope: (v: string) => void;
  onTags: (v: string) => void;
  onRepos: (v: string) => void;
}) {
  return (
    <>
      <input className="input" placeholder="Title" value={props.title} onChange={(e) => props.onTitle(e.target.value)} />
      <div className="form-grid-2">
        <select className="select" value={props.kind} onChange={(e) => props.onKind(e.target.value)}>
          {props.kinds.map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
        <input className="input" disabled={!props.isNew} value={props.scope} onChange={(e) => props.onScope(e.target.value)} />
      </div>
      <div className="form-grid-2">
        <input className="input" placeholder="Tags (comma separated)" value={props.tagsRaw} onChange={(e) => props.onTags(e.target.value)} />
        <input className="input" placeholder="Repos (comma separated)" value={props.reposRaw} onChange={(e) => props.onRepos(e.target.value)} />
      </div>
    </>
  );
}

async function saveNoteRequest(params: {
  note: BrainNote | null;
  isNew: boolean;
  scope: string;
  payload: { title: string; body: string; kind: string; tags: string[]; repos: string[]; source: string };
}): Promise<BrainNote> {
  const res = params.isNew
    ? await api.createNote({ ...params.payload, scope: params.scope })
    : await api.updateNote(params.note!.scope, params.note!.slug, params.payload);
  return res.note;
}

function NoteForm(props: {
  note: BrainNote | null;
  kinds: string[];
  scopes: string[];
  allNotes: BrainNote[];
  isNew: boolean;
  initialTitle?: string;
  onCancel: () => void;
  onSaved: (note: BrainNote) => void;
  onError: (msg: string) => void;
}) {
  const initial = initForm(props.note, props.kinds, props.scopes, props.initialTitle);
  const [title, setTitle] = useState(initial.title);
  const [kind, setKind] = useState(initial.kind);
  const [scope, setScope] = useState(initial.scope);
  const [tagsRaw, setTagsRaw] = useState(initial.tagsRaw);
  const [reposRaw, setReposRaw] = useState(initial.reposRaw);
  const [body, setBody] = useState(initial.body);
  const [preview, setPreview] = useState(false);
  const [saving, setSaving] = useState(false);

  async function submit() {
    setSaving(true);
    props.onError("");
    const payload = { title, body, kind, tags: splitCsv(tagsRaw), repos: splitCsv(reposRaw), source: props.note?.source ?? "" };
    try {
      props.onSaved(await saveNoteRequest({ note: props.note, isNew: props.isNew, scope, payload }));
    } catch (err) {
      props.onError(err instanceof ApiError ? err.message : "Failed to save note");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="list-stack">
      <NoteFormFields
        title={title} kind={kind} scope={scope} tagsRaw={tagsRaw} reposRaw={reposRaw}
        kinds={props.kinds} isNew={props.isNew}
        onTitle={setTitle} onKind={setKind} onScope={setScope} onTags={setTagsRaw} onRepos={setReposRaw}
      />
      <BodyEditorToolbar
        preview={preview} allNotes={props.allNotes} onTogglePreview={setPreview}
        onInsertLink={(ref) => setBody((prev) => `${prev} [[${ref}]]`)}
      />
      {preview ? (
        <div style={{ border: "1px solid var(--border)", borderRadius: 8, padding: "0.65rem", minHeight: 160 }}>
          <MarkdownView text={body || "_Nothing to preview._"} />
        </div>
      ) : (
        <textarea className="textarea" rows={10} placeholder="Markdown body..." value={body} onChange={(e) => setBody(e.target.value)} />
      )}
      <div style={{ display: "flex", gap: 8 }}>
        <button type="button" className="btn btn-primary" disabled={saving} onClick={() => void submit()}>
          <Save size={14} /> {saving ? "Saving..." : "Save Note"}
        </button>
        {!props.isNew && <button type="button" className="btn" onClick={props.onCancel}>Cancel</button>}
      </div>
    </div>
  );
}

function NoteReader({ note, backlinks, onNavigateRef }: { note: BrainNote; backlinks: NoteBacklink[]; onNavigateRef: (ref: string) => void }) {
  return (
    <>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        <span className="pill pill-cyan">{note.kind}</span>
        {note.stale && <span className="pill pill-amber">stale</span>}
        {note.tags.map((t) => <span key={t} className="pill">#{t}</span>)}
        {note.repos.map((r) => <span key={r} className="pill pill-emerald">{r}</span>)}
      </div>
      <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", display: "flex", gap: 12, flexWrap: "wrap" }}>
        <span>Updated: {note.updated}</span>
        {note.source && <span>Source: {note.source}</span>}
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

export function NoteDrawer({
  note, backlinks, kinds, scopes, allNotes = [], isNew = false, initialTitle, onClose, onSaved, onNavigateRef,
}: NoteDrawerProps) {
  const [editing, setEditing] = useState(isNew);
  const [error, setError] = useState("");
  useEffect(() => {
    setEditing(isNew);
    setError("");
  }, [note, isNew, initialTitle]);

  const formKey = `${note?.ref ?? "new"}-${isNew ? initialTitle ?? "" : ""}`;

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
        <NoteForm
          key={formKey} note={note} kinds={kinds} scopes={scopes} allNotes={allNotes}
          isNew={isNew} initialTitle={initialTitle}
          onCancel={() => setEditing(false)}
          onSaved={(saved) => { setEditing(false); onSaved(saved); }}
          onError={setError}
        />
      ) : (
        note && <NoteReader note={note} backlinks={backlinks} onNavigateRef={onNavigateRef} />
      )}
    </div>
  );
}
