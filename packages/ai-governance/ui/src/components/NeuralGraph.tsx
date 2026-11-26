import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D, { type ForceGraphMethods } from "react-force-graph-2d";
import { Maximize2, Pause, Play, Plus, Sparkles, ZoomIn, ZoomOut } from "lucide-react";
import type { BrainGraph, GraphLink, GraphNode } from "../types";

const KIND_COLORS: Record<string, string> = {
  gotcha: "#fb7185",
  decision: "#a78bfa",
  reference: "#38bdf8",
  howto: "#34d399",
  archive: "#fbbf24",
  task: "#818cf8",
  tag: "#64748b",
  repo: "#2dd4bf",
};

interface NeuralGraphProps {
  graph: BrainGraph;
  selectedNodeId?: string;
  onSelectNote: (scope: string, slug: string) => void;
  onSelectTask: (taskId: string) => void;
  onSelectHub?: (kind: "tag" | "repo", value: string) => void;
  onNewNote?: () => void;
}

function linkEndpointId(endpoint: string | GraphNode): string {
  return typeof endpoint === "string" ? endpoint : endpoint.id;
}

function buildAdjacency(links: GraphLink[]): Map<string, string[]> {
  const adj = new Map<string, string[]>();
  for (const link of links) {
    const s = linkEndpointId(link.source);
    const t = linkEndpointId(link.target);
    adj.set(s, [...(adj.get(s) ?? []), t]);
    adj.set(t, [...(adj.get(t) ?? []), s]);
  }
  return adj;
}

function countSubgraphStats(nodes: GraphNode[], linkCount: number): BrainGraph["stats"] {
  const counts = { notes: 0, tasks: 0, tags: 0, repos: 0, links: linkCount, orphans: 0 };
  for (const n of nodes) {
    if (n.type === "note") counts.notes += 1;
    else if (n.type === "task") counts.tasks += 1;
    else if (n.type === "tag") counts.tags += 1;
    else if (n.type === "repo") counts.repos += 1;
    if (n.orphan) counts.orphans += 1;
  }
  return counts;
}

function expandFrontier(frontier: string[], adj: Map<string, string[]>, visited: Set<string>): string[] {
  const next: string[] = [];
  for (const id of frontier) {
    for (const nb of adj.get(id) ?? []) {
      if (visited.has(nb)) continue;
      visited.add(nb);
      next.push(nb);
    }
  }
  return next;
}

export function filterEgoSubgraph(graph: BrainGraph, centerId: string, hops: 1 | 2): BrainGraph {
  if (!graph.nodes.some((n) => n.id === centerId)) return graph;
  const adj = buildAdjacency(graph.links);
  const visited = new Set<string>([centerId]);
  let frontier = [centerId];

  for (let step = 0; step < hops; step += 1) {
    frontier = expandFrontier(frontier, adj, visited);
  }

  const nodes = graph.nodes.filter((n) => visited.has(n.id));
  const links = graph.links.filter(
    (l) => visited.has(linkEndpointId(l.source)) && visited.has(linkEndpointId(l.target))
  );
  return { nodes, links, stats: countSubgraphStats(nodes, links.length) };
}

function nodeRadius(node: GraphNode): number {
  if (node.type === "note") return Math.min(12, 4.5 + Math.sqrt(node.degree || 1) * 1.4);
  return node.type === "task" ? 6.5 : 4;
}

function drawLabel(ctx: CanvasRenderingContext2D, node: GraphNode, r: number, scale: number): void {
  const fontSize = Math.max(9, 11 / scale);
  const text = node.label.slice(0, 32);
  ctx.font = `600 ${fontSize}px Inter, system-ui, sans-serif`;
  const padX = 4 / scale;
  const padY = 2 / scale;
  const w = ctx.measureText(text).width + padX * 2;
  const h = fontSize + padY * 2;
  const x = (node.x ?? 0) - w / 2;
  const y = (node.y ?? 0) + r + 3 / scale;

  ctx.fillStyle = "rgba(15, 23, 42, 0.85)";
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, 3 / scale);
  ctx.fill();
  ctx.fillStyle = "#e2e8f0";
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  ctx.fillText(text, node.x ?? 0, y + padY);
}

function drawMarkerRings(ctx: CanvasRenderingContext2D, node: GraphNode, r: number, scale: number): void {
  const x = node.x ?? 0;
  const y = node.y ?? 0;
  if (node.stale) {
    ctx.setLineDash([3 / scale, 2 / scale]);
    ctx.strokeStyle = "#fbbf24";
    ctx.lineWidth = 1.6 / scale;
    ctx.beginPath();
    ctx.arc(x, y, r + 3 / scale, 0, Math.PI * 2);
    ctx.stroke();
  }
  if (node.orphan) {
    ctx.setLineDash([1.5 / scale, 2.5 / scale]);
    ctx.strokeStyle = "#fb7185";
    ctx.lineWidth = 1.6 / scale;
    ctx.beginPath();
    ctx.arc(x, y, r + 5.5 / scale, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.setLineDash([]);
}

function renderNeuronNode(params: {
  node: GraphNode;
  ctx: CanvasRenderingContext2D;
  scale: number;
  activeId: string | null;
  neighbors: Set<string>;
}): void {
  const { node, ctx, scale, activeId, neighbors } = params;
  const x = node.x ?? 0;
  const y = node.y ?? 0;
  const highlighted = !activeId || neighbors.has(node.id);
  const color = KIND_COLORS[node.kind] ?? "#38bdf8";
  const r = nodeRadius(node);

  ctx.save();
  ctx.globalAlpha = highlighted ? 1 : 0.18;
  const glow = ctx.createRadialGradient(x, y, r * 0.2, x, y, r * 2.5);
  glow.addColorStop(0, color);
  glow.addColorStop(1, "rgba(7, 11, 20, 0)");
  ctx.fillStyle = glow;
  ctx.beginPath();
  ctx.arc(x, y, r * 2.5, 0, Math.PI * 2);
  ctx.fill();

  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.fill();
  if (node.id === activeId) {
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 1.8 / scale;
    ctx.stroke();
  }
  drawMarkerRings(ctx, node, r, scale);
  if (scale > 1.35 || (highlighted && activeId !== null)) drawLabel(ctx, node, r, scale);
  ctx.restore();
}

function useContainerDims(wrapRef: React.RefObject<HTMLDivElement>) {
  const [dims, setDims] = useState({ width: 800, height: 600 });
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const update = () => setDims({ width: el.clientWidth || 800, height: el.clientHeight || 600 });
    update();
    const obs = new ResizeObserver(update);
    obs.observe(el);
    return () => obs.disconnect();
  }, [wrapRef]);
  return dims;
}

function useNeighbors(activeId: string | null, links: GraphLink[]): Set<string> {
  return useMemo(() => {
    const set = new Set<string>();
    if (!activeId) return set;
    set.add(activeId);
    for (const link of links) {
      const s = linkEndpointId(link.source);
      const t = linkEndpointId(link.target);
      if (s === activeId) set.add(t);
      if (t === activeId) set.add(s);
    }
    return set;
  }, [activeId, links]);
}

function GraphLegend() {
  return (
    <div className="graph-legend">
      {Object.entries(KIND_COLORS).map(([kind, color]) => (
        <span key={kind} style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
          <span style={{ width: 8, height: 8, borderRadius: 99, background: color }} />
          {kind}
        </span>
      ))}
    </div>
  );
}

function GraphControls(props: {
  hasSelection: boolean;
  egoHops: 0 | 1 | 2;
  frozen: boolean;
  onSetHops: (h: 0 | 1 | 2) => void;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onFit: () => void;
  onToggleFreeze: () => void;
}) {
  return (
    <div className="graph-controls">
      {props.hasSelection && (
        <>
          {([0, 1, 2] as const).map((h) => (
            <button
              key={h}
              type="button"
              className={`btn ${props.egoHops === h ? "btn-primary" : ""}`}
              onClick={() => props.onSetHops(h)}
            >
              {h === 0 ? "Global" : `${h}-hop`}
            </button>
          ))}
        </>
      )}
      <button type="button" className="btn" onClick={props.onZoomIn} title="Zoom in">
        <ZoomIn size={14} /> Zoom +
      </button>
      <button type="button" className="btn" onClick={props.onZoomOut} title="Zoom out">
        <ZoomOut size={14} /> Zoom -
      </button>
      <button type="button" className="btn" onClick={props.onFit} title="Fit graph">
        <Maximize2 size={14} /> Fit
      </button>
      <button type="button" className="btn" onClick={props.onToggleFreeze}>
        {props.frozen ? <Play size={14} /> : <Pause size={14} />}
        {props.frozen ? "Resume" : "Freeze"}
      </button>
    </div>
  );
}

function HoverChip({ node }: { node: GraphNode }) {
  return (
    <div className="graph-hover-chip">
      <strong>{node.label}</strong>
      <span className="pill pill-cyan">{node.kind}</span>
      {node.stale && <span className="pill pill-amber">stale</span>}
      {node.orphan && <span className="pill pill-rose">orphan</span>}
    </div>
  );
}

function EmptyGraph({ onNewNote }: { onNewNote?: () => void }) {
  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", color: "var(--text-muted)", gap: "0.65rem" }}>
      <Sparkles size={26} color="#38bdf8" />
      <div>No Second Brain notes match the current filter yet.</div>
      {onNewNote && (
        <button type="button" className="btn btn-primary" onClick={onNewNote}>
          <Plus size={14} /> Create Note
        </button>
      )}
    </div>
  );
}

function useAutoCenter(
  fgRef: React.RefObject<ForceGraphMethods | undefined>,
  selectedNodeId: string | undefined,
  nodes: GraphNode[]
) {
  useEffect(() => {
    if (!selectedNodeId || !fgRef.current) return;
    const node = nodes.find((n) => n.id === selectedNodeId);
    if (node && typeof node.x === "number" && typeof node.y === "number") {
      fgRef.current.centerAt(node.x, node.y, 400);
      if ((fgRef.current.zoom() ?? 1) < 1.6) fgRef.current.zoom(1.8, 400);
    }
  }, [fgRef, selectedNodeId, nodes]);
}

function dispatchNodeClick(
  node: GraphNode,
  handlers: Pick<NeuralGraphProps, "onSelectNote" | "onSelectTask" | "onSelectHub">
) {
  if (node.type === "note" && node.scope && node.slug) handlers.onSelectNote(node.scope, node.slug);
  else if (node.type === "task" && node.task_id) handlers.onSelectTask(node.task_id);
  else if (node.type === "tag" || node.type === "repo") {
    handlers.onSelectHub?.(node.type, node.type === "tag" ? node.label.replace(/^#/, "") : node.label);
  }
}

function GraphCanvas(props: {
  fgRef: React.MutableRefObject<ForceGraphMethods | undefined>;
  dims: { width: number; height: number };
  graph: BrainGraph;
  frozen: boolean;
  activeId: string | null;
  drawNode: (n: object, ctx: CanvasRenderingContext2D, scale: number) => void;
  onHover: (id: string | null) => void;
  onClick: (node: GraphNode) => void;
}) {
  const isConnected = (l: object) => {
    if (!props.activeId) return false;
    const link = l as GraphLink;
    return linkEndpointId(link.source) === props.activeId || linkEndpointId(link.target) === props.activeId;
  };
  return (
    <ForceGraph2D
      ref={props.fgRef} width={props.dims.width} height={props.dims.height} graphData={props.graph}
      backgroundColor="rgba(0,0,0,0)" cooldownTicks={props.frozen ? 0 : undefined} nodeCanvasObject={props.drawNode}
      linkColor={(l) => (!props.activeId ? "rgba(148, 163, 184, 0.22)" : isConnected(l) ? "rgba(56, 189, 248, 0.72)" : "rgba(148, 163, 184, 0.06)")}
      linkWidth={(l) => ((l as GraphLink).kind === "reference" ? 2 : 1)}
      linkDirectionalParticles={(l) => (isConnected(l) ? 3 : 0)}
      linkDirectionalParticleWidth={2.4} linkDirectionalParticleColor={() => "#38bdf8"}
      onNodeHover={(n) => props.onHover(n ? (n as GraphNode).id : null)}
      onNodeClick={(n) => props.onClick(n as GraphNode)}
    />
  );
}

export function NeuralGraph({ graph, selectedNodeId, onSelectNote, onSelectTask, onSelectHub, onNewNote }: NeuralGraphProps) {
  const fgRef = useRef<ForceGraphMethods>();
  const wrapRef = useRef<HTMLDivElement>(null);
  const dims = useContainerDims(wrapRef);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [egoHops, setEgoHops] = useState<0 | 1 | 2>(0);
  const [frozen, setFrozen] = useState(false);

  const displayedGraph = useMemo(
    () => (selectedNodeId && egoHops !== 0 ? filterEgoSubgraph(graph, selectedNodeId, egoHops) : graph),
    [graph, selectedNodeId, egoHops]
  );
  const activeId = hoveredId ?? selectedNodeId ?? null;
  const neighbors = useNeighbors(activeId, displayedGraph.links);
  const hoveredNode = hoveredId ? displayedGraph.nodes.find((n) => n.id === hoveredId) ?? null : null;
  useAutoCenter(fgRef, selectedNodeId, displayedGraph.nodes);

  const drawNode = useCallback(
    (n: object, ctx: CanvasRenderingContext2D, scale: number) =>
      renderNeuronNode({ node: n as GraphNode, ctx, scale, activeId, neighbors }),
    [activeId, neighbors]
  );
  const zoomBy = (factor: number) => fgRef.current?.zoom(Math.max(0.2, (fgRef.current?.zoom() ?? 1) * factor), 250);
  const toggleFreeze = () => {
    setFrozen((prev) => { if (prev) fgRef.current?.d3ReheatSimulation(); return !prev; });
  };

  return (
    <div ref={wrapRef} className="graph-container">
      <GraphControls
        hasSelection={Boolean(selectedNodeId)} egoHops={egoHops} frozen={frozen}
        onSetHops={setEgoHops} onZoomIn={() => zoomBy(1.35)} onZoomOut={() => zoomBy(1 / 1.35)}
        onFit={() => fgRef.current?.zoomToFit(350, 48)} onToggleFreeze={toggleFreeze}
      />
      {hoveredNode && <HoverChip node={hoveredNode} />}
      {displayedGraph.nodes.length === 0 ? <EmptyGraph onNewNote={onNewNote} /> : (
        <GraphCanvas
          fgRef={fgRef} dims={dims} graph={displayedGraph} frozen={frozen} activeId={activeId}
          drawNode={drawNode} onHover={setHoveredId}
          onClick={(node) => dispatchNodeClick(node, { onSelectNote, onSelectTask, onSelectHub })}
        />
      )}
      <GraphLegend />
    </div>
  );
}
