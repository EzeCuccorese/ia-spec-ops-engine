import { useCallback, useEffect, useState } from "react";
import { BrainCircuit, Cpu, LayoutDashboard, ListTodo, Search } from "lucide-react";
import { api } from "./api";
import { CommandSearchModal } from "./components/CommandSearchModal";
import type { BrainGraph, BrainNote, HealthResponse, TaskDetail, TaskSummary, WorkersResponse } from "./types";
import { BrainView } from "./views/BrainView";
import { OverviewView } from "./views/OverviewView";
import { TaskflowView } from "./views/TaskflowView";
import { WorkersView } from "./views/WorkersView";

type Tab = "overview" | "taskflow" | "brain" | "workers";

function TopNavBar({ tab, health, onTab, onSearch }: { tab: Tab; health: HealthResponse | null; onTab: (t: Tab) => void; onSearch: () => void }) {
  const tabs: [Tab, string, typeof LayoutDashboard][] = [
    ["overview", "Overview", LayoutDashboard],
    ["taskflow", "Taskflow", ListTodo],
    ["brain", "Second Brain", BrainCircuit],
    ["workers", "Orca Workers", Cpu],
  ];
  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-dot" />
        <span>ai-governance</span>
        {health && <span className="pill" style={{ fontSize: "0.7rem" }}>v{health.version}</span>}
      </div>
      <nav className="nav-tabs">
        {tabs.map(([id, label, Icon]) => (
          <button key={id} type="button" className={`nav-tab ${tab === id ? "active" : ""}`} onClick={() => onTab(id)}>
            <Icon size={15} /> {label}
          </button>
        ))}
      </nav>
      <div className="topbar-actions">
        <button type="button" className="btn" onClick={onSearch}><Search size={14} /> Search <span style={{ color: "var(--text-muted)" }}>⌘K</span></button>
      </div>
    </header>
  );
}

export function App() {
  const [tab, setTab] = useState<Tab>("overview");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [selectedTask, setSelectedTask] = useState<TaskDetail | null>(null);
  const [notes, setNotes] = useState<BrainNote[]>([]);
  const [scopes, setScopes] = useState<string[]>(["personal"]);
  const [kinds, setKinds] = useState<string[]>(["gotcha", "reference", "decision", "howto", "archive"]);
  const [selectedNote, setSelectedNote] = useState<{ note: BrainNote; backlinks: { ref: string; title: string; kind: string }[] } | null>(null);
  const [graph, setGraph] = useState<BrainGraph | null>(null);
  const [workers, setWorkers] = useState<WorkersResponse | null>(null);
  const [scopeFilter, setScopeFilter] = useState("");
  const [kindFilter, setKindFilter] = useState("");
  const [includeHubs, setIncludeHubs] = useState(true);
  const [searchOpen, setSearchOpen] = useState(false);

  const loadAll = useCallback(async () => {
    const [h, t, n, g, w] = await Promise.all([
      api.health().catch(() => null),
      api.listTasks(true).catch(() => ({ tasks: [] })),
      api.listNotes({ scope: scopeFilter, kind: kindFilter }).catch(() => null),
      api.getGraph({ scope: scopeFilter, kind: kindFilter, hubs: includeHubs }).catch(() => null),
      api.workers().catch(() => null),
    ]);
    if (h) setHealth(h);
    setTasks(t.tasks);
    if (n) { setNotes(n.notes); setScopes(n.scopes); setKinds(n.kinds); }
    if (g) setGraph(g);
    if (w) setWorkers(w);
  }, [scopeFilter, kindFilter, includeHubs]);

  useEffect(() => { void loadAll(); }, [loadAll]);
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

  return (
    <div className="app-shell">
      <TopNavBar tab={tab} health={health} onTab={setTab} onSearch={() => setSearchOpen(true)} />
      <main className="main-content">
        {tab === "overview" && <OverviewView tasks={tasks} notes={notes} graph={graph} workers={workers} onNavigate={setTab} onSelectTask={(id) => void selectTask(id)} />}
        {tab === "taskflow" && <TaskflowView tasks={tasks} selectedTask={selectedTask} onSelectTask={(id) => void selectTask(id)} onRefresh={() => void loadAll()} onArchived={(ref) => { openNoteRef(ref); void loadAll(); }} />}
        {tab === "brain" && (
          <BrainView
            graph={graph} notes={notes} scopes={scopes} kinds={kinds} selectedNote={selectedNote}
            scopeFilter={scopeFilter} kindFilter={kindFilter} includeHubs={includeHubs}
            onChangeFilter={(nx) => { if (nx.scope !== undefined) setScopeFilter(nx.scope); if (nx.kind !== undefined) setKindFilter(nx.kind); if (nx.hubs !== undefined) setIncludeHubs(nx.hubs); }}
            onSelectNote={(sc, sl) => void selectNote(sc, sl)} onSelectTask={(id) => void selectTask(id)}
            onClearNote={() => setSelectedNote(null)} onRefresh={() => void loadAll()}
          />
        )}
        {tab === "workers" && <WorkersView workers={workers} onRefresh={() => void loadAll()} />}
      </main>
      {searchOpen && <CommandSearchModal onClose={() => setSearchOpen(false)} onSelectTask={(id) => void selectTask(id)} onSelectNote={openNoteRef} />}
    </div>
  );
}
