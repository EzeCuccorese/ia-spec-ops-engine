import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D, { type ForceGraphMethods } from "react-force-graph-2d";
import { Maximize2, Sparkles } from "lucide-react";
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
}

function linkEndpointId(endpoint: string | GraphNode): string {
  return typeof endpoint === "string" ? endpoint : endpoint.id;
}

function nodeRadius(node: GraphNode): number {
  if (node.type === "note") return Math.min(12, 4.5 + Math.sqrt(node.degree || 1) * 1.4);
  return node.type === "task" ? 6.5 : 4;
}

function drawLabel(ctx: CanvasRenderingContext2D, node: GraphNode, r: number, scale: number): void {
  const fontSize = Math.max(9, 11 / scale);
  ctx.font = `600 ${fontSize}px Inter, system-ui, sans-serif`;
  ctx.fillStyle = "#e2e8f0";
  ctx.textAlign = "center";
  ctx.fillText(node.label.slice(0, 32), node.x ?? 0, (node.y ?? 0) + r + fontSize + 2 / scale);
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

function EmptyGraph() {
  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", color: "var(--text-muted)", gap: "0.5rem" }}>
      <Sparkles size={26} color="#38bdf8" />
      <div>No Second Brain notes match the current filter yet.</div>
    </div>
  );
}

export function NeuralGraph({ graph, selectedNodeId, onSelectNote, onSelectTask }: NeuralGraphProps) {
  const fgRef = useRef<ForceGraphMethods>();
  const wrapRef = useRef<HTMLDivElement>(null);
  const dims = useContainerDims(wrapRef);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const activeId = hoveredId ?? selectedNodeId ?? null;
  const neighbors = useNeighbors(activeId, graph.links);

  const drawNode = useCallback(
    (n: object, ctx: CanvasRenderingContext2D, scale: number) =>
      renderNeuronNode({ node: n as GraphNode, ctx, scale, activeId, neighbors }),
    [activeId, neighbors]
  );

  const isConnected = (l: object) => {
    if (!activeId) return false;
    const link = l as GraphLink;
    return linkEndpointId(link.source) === activeId || linkEndpointId(link.target) === activeId;
  };

  return (
    <div ref={wrapRef} className="graph-container">
      <div style={{ position: "absolute", top: 10, right: 10, zIndex: 10 }}>
        <button type="button" className="btn" onClick={() => fgRef.current?.zoomToFit(350, 48)}>
          <Maximize2 size={14} /> Fit
        </button>
      </div>
      {graph.nodes.length === 0 ? <EmptyGraph /> : (
        <ForceGraph2D
          ref={fgRef} width={dims.width} height={dims.height} graphData={graph} backgroundColor="rgba(0,0,0,0)"
          nodeCanvasObject={drawNode}
          linkColor={(l) => (!activeId ? "rgba(148, 163, 184, 0.22)" : isConnected(l) ? "rgba(56, 189, 248, 0.72)" : "rgba(148, 163, 184, 0.06)")}
          linkWidth={(l) => ((l as GraphLink).kind === "reference" ? 2 : 1)}
          linkDirectionalParticles={(l) => (isConnected(l) ? 3 : 0)}
          linkDirectionalParticleWidth={2.4} linkDirectionalParticleColor={() => "#38bdf8"}
          onNodeHover={(n) => setHoveredId(n ? (n as GraphNode).id : null)}
          onNodeClick={(n) => {
            const node = n as GraphNode;
            if (node.type === "note" && node.scope && node.slug) onSelectNote(node.scope, node.slug);
            else if (node.type === "task" && node.task_id) onSelectTask(node.task_id);
          }}
        />
      )}
      <GraphLegend />
    </div>
  );
}
