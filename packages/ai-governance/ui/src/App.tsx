import { useCallback, useEffect, useRef, useState } from "react";
import { BrainCircuit, Cpu, LayoutDashboard, ListTodo, Search } from "lucide-react";
import { api } from "./api";
import { CommandSearchModal } from "./components/CommandSearchModal";
import type {
  BrainFilters,
  BrainGraph,
  BrainNote,
  HealthResponse,
  TaskDetail,
  TaskSummary,
  WorkersResponse,
} from "./types";
import { BrainView } from "./views/BrainView";
import { OverviewView } from "./views/OverviewView";
import { TaskflowView } from "./views/TaskflowView";
import { WorkersView } from "./views/WorkersView";

type Tab = "overview" | "taskflow" | "brain" | "workers";
type SelectedNoteState = { note: BrainNote; backlinks: { ref: string; title: string; kind: string }[] } | null;

const DEFAULT_FILTERS: BrainFilters = {
  scope: "",
  kind: "",
  repo: "",
  tag: "",
  staleOnly: false,
  orphansOnly: false,
  hubs: true,
};

function getShortcutLabel(): string {
  if (typeof navigator === "undefined") return "Ctrl+K";
  return /Mac|iPhone|iPad/i.test(navigator.platform || navigator.userAgent) ? "⌘K" : "Ctrl+K";
}

function TopNavBar({
  tab,
  health,
  live,
  onTab,
  onSearch,
}: {
  tab: Tab;
  health: HealthResponse | null;
  live: boolean;
  onTab: (t: Tab) => void;
  onSearch: () => void;
}) {
  const tabs: [Tab, string, typeof LayoutDashboard][] = [
    ["overview", "Overview", LayoutDashboard],
    ["taskflow", "Sessions", ListTodo],
    ["brain", "Second Brain", BrainCircuit],
    ["workers", "Orca Workers", Cpu],
  ];
  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-dot" />
        <span>ai-governance</span>
        {health && <span className="pill" style={{ fontSize: "0.7rem" }}>v{health.version}</span>}
        <span className="live-pill" title={live ? "Connected to live updates" : "Live updates offline"}>
          <span className={`live-dot ${live ? "" : "offline"}`} />
          {live ? "Live" : "Offline"}
        </span>
      </div>
      <nav className="nav-tabs">
        {tabs.map(([id, label, Icon]) => (
          <button key={id} type="button" className={`nav-tab ${tab === id ? "active" : ""}`} onClick={() => onTab(id)}>
            <Icon size={15} /> {label}
          </button>
        ))}
      </nav>
      <div className="topbar-actions">
        <button type="button" className="btn" onClick={onSearch}>
          <Search size={14} /> Search <span style={{ color: "var(--text-muted)" }}>{getShortcutLabel()}</span>
        </button>
      </div>
    </header>
  );
}

function useGovernanceStore(filters: BrainFilters) {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [notes, setNotes] = useState<BrainNote[]>([]);
  const [allNotes, setAllNotes] = useState<BrainNote[]>([]);
  const [scopes, setScopes] = useState<string[]>(["personal"]);
  const [kinds, setKinds] = useState<string[]>(["gotcha", "reference", "decision", "howto", "archive"]);
  const [repos, setRepos] = useState<string[]>([]);
  const [tags, setTags] = useState<string[]>([]);
  const [graph, setGraph] = useState<BrainGraph | null>(null);
  const [workers, setWorkers] = useState<WorkersResponse | null>(null);

  const loadAll = useCallback(async () => {
    const hasFilter = Boolean(filters.scope || filters.kind || filters.repo || filters.tag);
    const [h, t, n, allN, g, w] = await Promise.all([
      api.health().catch(() => null),
      api.listTasks(true).catch(() => ({ tasks: [] })),
      api.listNotes({ scope: filters.scope, kind: filters.kind, repo: filters.repo, tag: filters.tag }).catch(() => null),
      hasFilter ? api.listNotes({}).catch(() => null) : Promise.resolve(null),
      api.getGraph({ scope: filters.scope, kind: filters.kind, repo: filters.repo, tag: filters.tag, hubs: filters.hubs }).catch(() => null),
      api.workers().catch(() => null),
    ]);
    if (h) setHealth(h);
    setTasks(t.tasks);
    if (n) { setNotes(n.notes); setScopes(n.scopes); setKinds(n.kinds); setRepos(n.repos); setTags(n.tags); }
    if (allN) setAllNotes(allN.notes);
    else if (n) setAllNotes(n.notes);
    if (g) setGraph(g);
    if (w) setWorkers(w);
  }, [filters.scope, filters.kind, filters.repo, filters.tag, filters.hubs]);

  useEffect(() => { void loadAll(); }, [loadAll]);
  return { health, tasks, notes, allNotes, scopes, kinds, repos, tags, graph, workers, loadAll };
}

function useLiveSync(params: {
  loadAll: () => Promise<void>;
  selectedTask: TaskDetail | null;
  selectedNote: SelectedNoteState;
  setSelectedTask: (t: TaskDetail) => void;
  setSelectedNote: (n: SelectedNoteState) => void;
}): boolean {
  const { loadAll, selectedTask, selectedNote, setSelectedTask, setSelectedNote } = params;
  const [live, setLive] = useState(false);
  const loadRef = useRef(loadAll);
  const taskIdRef = useRef<string | null>(null);
  const noteRef = useRef<{ scope: string; slug: string } | null>(null);
  loadRef.current = loadAll;
  taskIdRef.current = selectedTask?.id ?? null;
  noteRef.current = selectedNote ? { scope: selectedNote.note.scope, slug: selectedNote.note.slug } : null;

  useEffect(() => {
    return api.subscribeEvents((changed) => {
      void loadRef.current();
      if (changed.includes("taskflow") && taskIdRef.current) {
        void api.getTask(taskIdRef.current).then((r) => setSelectedTask(r.task)).catch(() => null);
      }
      if (changed.includes("brain") && noteRef.current) {
        const { scope, slug } = noteRef.current;
        void api.getNote(scope, slug).then((r) => setSelectedNote(r)).catch(() => null);
      }
    }, setLive);
  }, [setSelectedTask, setSelectedNote]);

  return live;
}

export function App() {
  const [tab, setTab] = useState<Tab>("overview");
  const [filters, setFilters] = useState<BrainFilters>(DEFAULT_FILTERS);
  const [selectedTask, setSelectedTask] = useState<TaskDetail | null>(null);
  const [selectedNote, setSelectedNote] = useState<SelectedNoteState>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const store = useGovernanceStore(filters);
  const live = useLiveSync({ loadAll: store.loadAll, selectedTask, selectedNote, setSelectedTask, setSelectedNote });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setSearchOpen((v) => !v); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const selectTask = async (id: string) => { setTab("taskflow"); const r = await api.getTask(id).catch(() => null); if (r) setSelectedTask(r.task); };
  const selectNote = async (sc: string, sl: string) => { setTab("brain"); const r = await api.getNote(sc, sl).catch(() => null); if (r) setSelectedNote(r); };
  const openNoteRef = (ref: string) => { const [sc, sl] = ref.split("/", 2); if (sc && sl) void selectNote(sc, sl); };
  const changeFilter = (next: Partial<BrainFilters>) => setFilters((prev) => ({ ...prev, ...next }));

  return (
    <div className="app-shell">
      <TopNavBar tab={tab} health={store.health} live={live} onTab={setTab} onSearch={() => setSearchOpen(true)} />
      <main className="main-content">
        {tab === "overview" && <OverviewView tasks={store.tasks} notes={store.notes} graph={store.graph} workers={store.workers} onNavigate={setTab} onSelectTask={(id) => void selectTask(id)} onSelectNote={(sc, sl) => void selectNote(sc, sl)} />}
        {tab === "taskflow" && <TaskflowView tasks={store.tasks} selectedTask={selectedTask} onSelectTask={(id) => void selectTask(id)} onRefresh={() => void store.loadAll()} onArchived={(ref) => { openNoteRef(ref); void store.loadAll(); }} />}
        {tab === "brain" && <BrainView graph={store.graph} notes={store.notes} allNotes={store.allNotes} scopes={store.scopes} kinds={store.kinds} repos={store.repos} tags={store.tags} selectedNote={selectedNote} filters={filters} onChangeFilter={changeFilter} onSelectNote={(sc, sl) => void selectNote(sc, sl)} onSelectTask={(id) => void selectTask(id)} onClearNote={() => setSelectedNote(null)} onRefresh={() => void store.loadAll()} />}
        {tab === "workers" && <WorkersView workers={store.workers} onRefresh={() => void store.loadAll()} />}
      </main>
      {searchOpen && <CommandSearchModal onClose={() => setSearchOpen(false)} onSelectTask={(id) => void selectTask(id)} onSelectNote={openNoteRef} />}
    </div>
  );
}
