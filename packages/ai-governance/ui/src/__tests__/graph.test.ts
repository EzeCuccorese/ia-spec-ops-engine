import { describe, expect, it } from "vitest";
import { filterEgoSubgraph } from "../components/NeuralGraph";
import type { BrainGraph, GraphNode } from "../types";

function makeNode(id: string, type: GraphNode["type"] = "note", orphan = false): GraphNode {
  return { id, type, kind: type === "note" ? "reference" : type, label: id, degree: 1, orphan };
}

function buildSampleGraph(): BrainGraph {
  const n1 = makeNode("note:a");
  const n2 = makeNode("note:b");
  const t1 = makeNode("task:t1", "task");
  const tag1 = makeNode("tag:x", "tag");
  const far = makeNode("note:far", "note", true);
  return {
    nodes: [n1, n2, t1, tag1, far],
    links: [
      { source: "note:a", target: "note:b", kind: "reference", weight: 1 },
      { source: "note:b", target: "task:t1", kind: "task", weight: 1 },
      { source: "task:t1", target: "tag:x", kind: "tag", weight: 1 },
      { source: "tag:x", target: "note:far", kind: "tag", weight: 1 },
    ],
    stats: { notes: 3, tasks: 1, tags: 1, repos: 0, links: 4, orphans: 1 },
  };
}

describe("filterEgoSubgraph", () => {
  it("returns 1-hop neighbors and connecting edges", () => {
    const graph = buildSampleGraph();
    const sub = filterEgoSubgraph(graph, "note:a", 1);

    expect(sub.nodes.map((n) => n.id)).toEqual(["note:a", "note:b"]);
    expect(sub.links).toHaveLength(1);
    expect(sub.stats).toEqual({ notes: 2, tasks: 0, tags: 0, repos: 0, links: 1, orphans: 0 });
  });

  it("returns 2-hop neighbors and updates stats", () => {
    const graph = buildSampleGraph();
    const sub = filterEgoSubgraph(graph, "note:a", 2);

    expect(sub.nodes.map((n) => n.id)).toEqual(["note:a", "note:b", "task:t1"]);
    expect(sub.links).toHaveLength(2);
    expect(sub.stats).toEqual({ notes: 2, tasks: 1, tags: 0, repos: 0, links: 2, orphans: 0 });
  });

  it("returns graph unchanged when centerId is missing", () => {
    const graph = buildSampleGraph();
    const sub = filterEgoSubgraph(graph, "note:missing", 1);

    expect(sub).toBe(graph);
  });

  it("handles GraphNode object endpoints in links", () => {
    const graph = buildSampleGraph();
    graph.links = [
      { source: graph.nodes[0], target: graph.nodes[1], kind: "reference", weight: 1 },
      { source: graph.nodes[1], target: graph.nodes[2], kind: "task", weight: 1 },
    ];
    const sub = filterEgoSubgraph(graph, "note:a", 1);

    expect(sub.nodes.map((n) => n.id)).toEqual(["note:a", "note:b"]);
    expect(sub.links).toHaveLength(1);
  });
});
