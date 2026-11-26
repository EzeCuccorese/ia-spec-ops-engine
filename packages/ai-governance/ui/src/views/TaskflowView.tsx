import { useState } from "react";
import { ExternalLink, Link2, Plus, Search } from "lucide-react";
import { ApiError, api } from "../api";
import { TaskDetailDrawer } from "../components/TaskDetailDrawer";
import type { JiraIssuePreview, TaskDetail, TaskSummary } from "../types";

export type TaskBucket = "active" | "blocked" | "paused" | "closed";

const FILTERS = ["all", "active", "blocked", "debate", "closed"] as const;

export function taskBucket(t: TaskSummary): TaskBucket {
  if (t.status === "closed") return "closed";
  if (Object.keys(t.blocked || {}).length > 0) return "blocked";
  if (t.status === "paused") return "paused";
  return "active";
}

function matchesFilter(t: TaskSummary, filter: string, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (q && !`${t.id} ${t.title} ${t.summary}`.toLowerCase().includes(q)) return false;
  if (filter === "all") return true;
  if (filter === "debate") return t.has_debate;
  return taskBucket(t) === filter;
}

function findJiraLink(links?: { title: string; url: string }[]): string {
  const hit = (links ?? []).find(
    (l) => l.url.includes("/browse/") || l.title.toLowerCase().startsWith("jira")
  );
  return hit?.url ?? "";
}

interface TaskflowViewProps {
  tasks: TaskSummary[];
  selectedTask: TaskDetail | null;
  onSelectTask: (id: string) => void;
  onRefresh: () => void;
  onArchived?: (ref: string) => void;
}

function JiraFetchRow(props: {
  jiraRef: string;
  fetching: boolean;
  preview: JiraIssuePreview | null;
  onJiraRef: (v: string) => void;
  onFetch: () => void;
}) {
  return (
    <>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <input
          className="input"
          style={{ flex: 1, minWidth: 220 }}
          placeholder="Jira key or URL (e.g. PROJ-123 or https://.../browse/PROJ-123)"
          value={props.jiraRef}
          onChange={(e) => props.onJiraRef(e.target.value)}
        />
        <button
          type="button"
          className="btn"
          disabled={props.fetching || !props.jiraRef.trim()}
          onClick={props.onFetch}
        >
          <Link2 size={14} /> {props.fetching ? "Fetching..." : "Fetch from Jira"}
        </button>
      </div>
      {props.preview && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", fontSize: "0.76rem", alignItems: "center" }}>
          <span className="pill pill-cyan">{props.preview.key}</span>
          {props.preview.status && <span className="pill">{props.preview.status}</span>}
          {props.preview.issue_type && <span className="pill">{props.preview.issue_type}</span>}
          {props.preview.parent && <span className="pill">parent: {props.preview.parent}</span>}
        </div>
      )}
    </>
  );
}

function NewSessionForm({ onCreated, onCancel }: { onCreated: (id: string) => void; onCancel: () => void }) {
  const [jiraRef, setJiraRef] = useState("");
  const [preview, setPreview] = useState<JiraIssuePreview | null>(null);
  const [fetching, setFetching] = useState(false);
  const [id, setId] = useState("");
  const [title, setTitle] = useState("");
  const [parent, setParent] = useState("");
  const [jiraUrl, setJiraUrl] = useState("");
  const [summary, setSummary] = useState("");
  const [error, setError] = useState("");

  async function fetchJira() {
    setError("");
    setFetching(true);
    try {
      const issue = await api.lookupJira(jiraRef.trim());
      setPreview(issue);
      setId(issue.key);
      if (issue.title) setTitle(issue.title);
      if (issue.parent) setParent(issue.parent);
      if (issue.url) setJiraUrl(issue.url);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to fetch Jira issue");
    } finally {
      setFetching(false);
    }
  }

  async function submit() {
    setError("");
    try {
      const res = await api.createTask({
        id: id.trim(),
        title: title.trim(),
        summary: summary.trim(),
        parent: parent.trim(),
        jira_url: jiraUrl.trim(),
      });
      onCreated(res.task.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create session");
    }
  }

  return (
    <div className="card list-stack">
      <div style={{ fontSize: "0.82rem", fontWeight: 600 }}>Start Agent Session (Link Jira Ticket or Manual)</div>
      {error && <div className="alert-error">{error}</div>}
      <JiraFetchRow jiraRef={jiraRef} fetching={fetching} preview={preview} onJiraRef={setJiraRef} onFetch={() => void fetchJira()} />
      <div className="form-grid-2">
        <input className="input" placeholder="Session ID / Jira Key (e.g. PROJ-123)" value={id} onChange={(e) => setId(e.target.value)} />
        <input className="input" placeholder="Title" value={title} onChange={(e) => setTitle(e.target.value)} />
      </div>
      <div className="form-grid-2">
        <input className="input" placeholder="Jira URL (optional)" value={jiraUrl} onChange={(e) => setJiraUrl(e.target.value)} />
        <input className="input" placeholder="Working notes / summary (optional)" value={summary} onChange={(e) => setSummary(e.target.value)} />
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <button type="button" className="btn btn-primary" disabled={!id.trim() || !title.trim()} onClick={() => void submit()}>
          Start Session
        </button>
        <button type="button" className="btn" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

function SessionCard({ task, selected, onSelect }: { task: TaskSummary; selected: boolean; onSelect: (id: string) => void }) {
  const bucket = taskBucket(task);
  const jiraUrl = findJiraLink(task.links);
  return (
    <button type="button" className={`item-card ${selected ? "selected" : ""}`} onClick={() => onSelect(task.id)}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.75rem", alignItems: "center" }}>
        <span style={{ color: "var(--cyan)", fontWeight: 600, display: "inline-flex", gap: 6, alignItems: "center" }}>
          {task.id}
          {jiraUrl && <ExternalLink size={11} color="#38bdf8" />}
        </span>
        <span className={`pill pill-${bucket === "blocked" ? "rose" : task.status}`}>{bucket}</span>
      </div>
      <div style={{ fontWeight: 600, marginTop: 4 }}>{task.title}</div>
      <div style={{ display: "flex", gap: 8, marginTop: 6, fontSize: "0.75rem", color: "var(--text-muted)", flexWrap: "wrap" }}>
        {task.repos.length > 0 && <span>{task.repos.length} repo(s)</span>}
        <span>{task.done_steps}/{task.total_steps} steps</span>
        {task.has_debate && <span className="pill pill-violet">debate</span>}
        {task.pending_rounds > 0 && <span className="pill pill-amber">{task.pending_rounds} pending</span>}
      </div>
    </button>
  );
}

function SessionToolbar(props: {
  filter: string;
  query: string;
  onFilter: (f: string) => void;
  onQuery: (q: string) => void;
  onToggleNew: () => void;
}) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
        {FILTERS.map((st) => (
          <button key={st} type="button" className={`btn ${props.filter === st ? "btn-primary" : ""}`} onClick={() => props.onFilter(st)}>
            {st}
          </button>
        ))}
        <div style={{ position: "relative", display: "inline-flex", alignItems: "center" }}>
          <Search size={13} color="#94a3b8" style={{ position: "absolute", left: 8, pointerEvents: "none" }} />
          <input className="input" style={{ width: 210, paddingLeft: 26 }} placeholder="Filter sessions..." value={props.query} onChange={(e) => props.onQuery(e.target.value)} />
        </div>
      </div>
      <button type="button" className="btn btn-primary" onClick={props.onToggleNew}>
        <Plus size={14} /> Link Jira / New Session
      </button>
    </div>
  );
}

export function TaskflowView({ tasks, selectedTask, onSelectTask, onRefresh, onArchived }: TaskflowViewProps) {
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(false);
  const visible = tasks.filter((t) => matchesFilter(t, filter, query));

  return (
    <div className="list-stack" style={{ gap: "0.85rem" }}>
      <SessionToolbar filter={filter} query={query} onFilter={setFilter} onQuery={setQuery} onToggleNew={() => setCreating((v) => !v)} />
      {creating && <NewSessionForm onCreated={(newId) => { setCreating(false); onRefresh(); onSelectTask(newId); }} onCancel={() => setCreating(false)} />}
      <div className="split-layout">
        <div className="list-stack">
          {visible.map((t) => (
            <SessionCard key={t.id} task={t} selected={selectedTask?.id === t.id} onSelect={onSelectTask} />
          ))}
          {visible.length === 0 && (
            <div className="card" style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
              No sessions match the current filter. Link a Jira ticket or start a session above.
            </div>
          )}
        </div>
        <div>
          {selectedTask ? (
            <TaskDetailDrawer key={selectedTask.id} task={selectedTask} onRefresh={() => { onRefresh(); onSelectTask(selectedTask.id); }} onArchived={onArchived} onSelectTask={onSelectTask} />
          ) : (
            <div className="card" style={{ color: "var(--text-muted)", fontSize: "0.86rem" }}>
              Select a session to inspect bound repos, technical facts, decisions, debates, and Jira links.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
