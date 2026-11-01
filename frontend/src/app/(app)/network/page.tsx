"use client";

import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type EdgeMouseHandler,
  type Node,
  type NodeMouseHandler,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { ArrowUpRight } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Empty, ErrorNote, Field, Loading, Tag } from "@/components/ui";
import { useApi } from "@/lib/api";
import type { GraphEdgeView, GraphNodeView } from "@/lib/types";

interface GraphData {
  nodes: GraphNodeView[];
  edges: GraphEdgeView[];
  investigations: { id: string; ref: string; name: string }[];
}

const KINDS_ALL = ["source", "test", "evidence", "hypothesis", "finding", "assumption", "claim", "investigation", "remediation"];

const KINDS: { key: string; label: string; singular: string; column: number }[] = [
  { key: "source", label: "Data sources", singular: "Data source", column: 0 },
  { key: "test", label: "Tests", singular: "Test", column: 1 },
  { key: "evidence", label: "Evidence", singular: "Evidence", column: 2 },
  { key: "hypothesis", label: "Hypotheses", singular: "Hypothesis", column: 3 },
  { key: "finding", label: "Findings", singular: "Finding", column: 3 },
  { key: "assumption", label: "Assumptions", singular: "Assumption", column: 3 },
  { key: "claim", label: "Claims", singular: "Claim", column: 4 },
  { key: "investigation", label: "Investigations", singular: "Investigation", column: 4 },
  { key: "remediation", label: "Remediation actions", singular: "Remediation action", column: 4 },
];

/** Focused views. Showing every node at once stops being readable, so nothing starts that way. */
const VIEWS: { key: string; label: string; kinds: string[] }[] = [
  { key: "explanations", label: "Explanations", kinds: ["source", "evidence", "hypothesis", "claim"] },
  { key: "tests", label: "Tests", kinds: ["test", "evidence", "hypothesis", "claim"] },
  { key: "findings", label: "Findings", kinds: ["evidence", "finding", "remediation", "claim"] },
  { key: "assumptions", label: "Assumptions", kinds: ["evidence", "assumption", "remediation", "claim"] },
  { key: "everything", label: "Everything", kinds: KINDS_ALL },
];

const RELATIONS: Record<string, { label: string; color: string; dash?: string }> = {
  supports: { label: "Supports", color: "#55B987" },
  contradicts: { label: "Contradicts", color: "#D46B6B" },
  derived_from: { label: "Derived from", color: "#3F3F3F" },
  depends_on: { label: "Depends on", color: "#6B6B6B", dash: "4 4" },
  challenges: { label: "Challenges", color: "#D6A85B", dash: "6 3" },
  resolves: { label: "Resolves", color: "#FFFFFF", dash: "2 3" },
  distinguishes: { label: "Distinguishes", color: "#A3A3A3", dash: "1 3" },
};

const HANDLE = "!size-1 !min-h-0 !min-w-0 !border-0 !bg-transparent";
const NODE_WIDTH = 216;
const COLUMN_GAP = 300;
const ROW_GAP = 76;

function nodeStateTone(node: GraphNodeView) {
  const state = node.data.compatibility ?? node.data.severity ?? node.data.status ?? node.data.assessment ?? node.data.verification;
  if (state === "incompatible" || state === "violated" || state === "CONTRADICTED" || state === "failed" || state === "critical") return "border-l-bad";
  if (state === "corroborated" || state === "unverified" || state === "UNDERDETERMINED" || state === "PARTIALLY IDENTIFIED" || state === "high") return "border-l-warn";
  if (state === "held" || state === "SUPPORTED" || state === "verified" || state === "completed") return "border-l-ok";
  return "border-l-line";
}

function GraphCard({ data, selected }: NodeProps<Node<{ node: GraphNodeView; dim: boolean }>>) {
  const { node, dim } = data;
  const label = KINDS.find((k) => k.key === node.kind)?.singular ?? node.kind;
  return (
    <div
      style={{ width: NODE_WIDTH }}
      className={`rounded-md border border-l-2 bg-surface px-2.5 py-2 transition-opacity duration-200 ${nodeStateTone(node)} ${selected ? "!border-fg" : "border-line"} ${dim ? "opacity-20" : ""}`}
    >
      <Handle id="l" type="target" position={Position.Left} className={HANDLE} />
      <Handle id="t" type="target" position={Position.Top} className={HANDLE} />
      <p className="mono text-[9.5px] uppercase tracking-[0.08em] text-mute">{label}</p>
      <p className="mt-0.5 line-clamp-2 text-[11.5px] leading-[1.3] text-fg">{node.label}</p>
      <Handle id="r" type="source" position={Position.Right} className={HANDLE} />
      <Handle id="b" type="source" position={Position.Bottom} className={HANDLE} />
    </div>
  );
}

const nodeTypes = { card: GraphCard };

/** Every line flows left to right. The arrowhead keeps the relation's true direction when that reverses it. */
function route(edge: GraphEdgeView, positions: Map<string, { x: number; y: number }>) {
  const from = positions.get(edge.source)!;
  const to = positions.get(edge.target)!;
  if (from.x === to.x) {
    const downward = from.y < to.y;
    return {
      source: downward ? edge.source : edge.target,
      target: downward ? edge.target : edge.source,
      sourceHandle: "b",
      targetHandle: "t",
      reversed: !downward,
    };
  }
  const forward = from.x < to.x;
  return {
    source: forward ? edge.source : edge.target,
    target: forward ? edge.target : edge.source,
    sourceHandle: "r",
    targetHandle: "l",
    reversed: !forward,
  };
}

/** Layered layout: columns by node type, then rows ordered by neighbours to cut edge crossings. */
function layout(nodes: GraphNodeView[], edges: GraphEdgeView[]) {
  // Only columns with something in them take up width, so a focused view stays large enough to read.
  const used = [...new Set(nodes.map((n) => KINDS.find((k) => k.key === n.kind)?.column ?? 0))].sort((a, b) => a - b);
  const columnOf = (kind: string) => used.indexOf(KINDS.find((k) => k.key === kind)?.column ?? 0);
  const groupOrder = ["source", "test", "evidence", "hypothesis", "finding", "assumption", "investigation", "claim", "remediation"];
  const neighbours = new Map<string, string[]>();
  for (const edge of edges) {
    neighbours.set(edge.source, [...(neighbours.get(edge.source) ?? []), edge.target]);
    neighbours.set(edge.target, [...(neighbours.get(edge.target) ?? []), edge.source]);
  }
  const columns = new Map<number, GraphNodeView[]>();
  for (const node of [...nodes].sort((a, b) => groupOrder.indexOf(a.kind) - groupOrder.indexOf(b.kind))) {
    const column = columnOf(node.kind);
    columns.set(column, [...(columns.get(column) ?? []), node]);
  }
  const rank = new Map<string, number>();
  const settle = () => columns.forEach((list) => list.forEach((node, index) => rank.set(node.id, index - list.length / 2)));
  settle();
  for (let pass = 0; pass < 6; pass += 1) {
    columns.forEach((list, column) => {
      const score = (node: GraphNodeView) => {
        const linked = (neighbours.get(node.id) ?? []).map((id) => rank.get(id) ?? 0);
        return linked.length ? linked.reduce((a, b) => a + b, 0) / linked.length : 0;
      };
      columns.set(
        column,
        [...list].sort((a, b) => {
          // Hypotheses stay above assumptions, and remediations below the claim, so each band stays legible.
          const band = groupOrder.indexOf(a.kind) - groupOrder.indexOf(b.kind);
          return band || score(a) - score(b);
        }),
      );
    });
    settle();
  }
  const positions = new Map<string, { x: number; y: number }>();
  columns.forEach((list, column) => {
    list.forEach((node, index) => {
      positions.set(node.id, { x: column * COLUMN_GAP, y: (index - (list.length - 1) / 2) * ROW_GAP });
    });
  });
  return positions;
}

export default function NetworkPage() {
  const [investigationId, setInvestigationId] = useState<string | null>(null);
  const path = investigationId === null ? null : `/network${investigationId ? `?investigation_id=${investigationId}` : ""}`;
  const { data: index } = useApi<GraphData>("/network?investigation_id=none");
  const { data, error, loading, reload } = useApi<GraphData>(path);
  const [view, setView] = useState("explanations");
  const [hidden, setHidden] = useState(new Set<string>());
  const [selected, setSelected] = useState<{ node?: GraphNodeView; edge?: GraphEdgeView } | null>(null);
  const [focus, setFocus] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  useEffect(() => {
    if (!index || investigationId !== null) return;
    const linked = window.location.hash.slice(1);
    const known = index.investigations.some((i) => i.id === linked);
    setInvestigationId(known ? linked : (index.investigations[0]?.id ?? ""));
  }, [index, investigationId]);

  function chooseView(key: string) {
    setView(key);
    setHidden(new Set());
    setSelected(null);
    setFocus(null);
  }

  const shownKinds = useMemo(() => new Set((VIEWS.find((v) => v.key === view) ?? VIEWS[0]).kinds.filter((k) => !hidden.has(k))), [view, hidden]);

  const flow = useMemo(() => {
    if (!data) return { nodes: [] as Node[], edges: [] as Edge[] };
    let visible = focus ? data.nodes : data.nodes.filter((n) => shownKinds.has(n.kind));
    if (focus) {
      // Two steps out from one node, regardless of the view. Hubs link to nearly everything, so
      // the walk stops at them, or every focus would widen back into the whole graph.
      const kindOf = new Map(data.nodes.map((n) => [n.id, n.kind]));
      const hub = (id: string) => id !== focus && ["claim", "investigation", "source"].includes(kindOf.get(id) ?? "");
      const reach = new Set([focus]);
      let frontier = new Set([focus]);
      for (let step = 0; step < 2; step += 1) {
        const next = new Set<string>();
        for (const edge of data.edges) {
          for (const [from, to] of [[edge.source, edge.target], [edge.target, edge.source]]) {
            if (frontier.has(from) && !reach.has(to)) {
              reach.add(to);
              if (!hub(to)) next.add(to);
            }
          }
        }
        frontier = next;
      }
      visible = visible.filter((n) => reach.has(n.id));
    }
    const ids = new Set(visible.map((n) => n.id));
    const links = data.edges.filter((e) => ids.has(e.source) && ids.has(e.target));
    const positions = layout(visible, links);
    const focusId = selected?.node?.id;
    const related = new Set<string>();
    if (focusId) {
      related.add(focusId);
      for (const edge of links) {
        if (edge.source === focusId) related.add(edge.target);
        if (edge.target === focusId) related.add(edge.source);
      }
    }
    const nodes: Node[] = visible.map((node) => ({
      id: node.id,
      type: "card",
      position: positions.get(node.id)!,
      data: { node, dim: Boolean(focusId) && !related.has(node.id) },
      selected: focusId === node.id,
    }));
    const edges: Edge[] = links.map((edge) => {
      const relation = RELATIONS[edge.relation] ?? RELATIONS.derived_from;
      const active = !focusId || edge.source === focusId || edge.target === focusId;
      const path = route(edge, positions);
      const marker = { type: MarkerType.ArrowClosed, color: relation.color, width: 12, height: 12 };
      return {
        id: edge.id,
        source: path.source,
        target: path.target,
        sourceHandle: path.sourceHandle,
        targetHandle: path.targetHandle,
        type: "default",
        data: { edge },
        style: { stroke: relation.color, strokeWidth: selected?.edge?.id === edge.id ? 2 : 1, strokeDasharray: relation.dash, opacity: active ? 1 : 0.08 },
        ...(path.reversed ? { markerStart: marker } : { markerEnd: marker }),
        interactionWidth: 14,
      };
    });
    return { nodes, edges };
  }, [data, shownKinds, selected, focus]);

  const matches = useMemo(() => {
    const term = search.trim().toLowerCase();
    return term && data ? data.nodes.filter((n) => n.label.toLowerCase().includes(term)).slice(0, 8) : [];
  }, [data, search]);

  const onNodeClick: NodeMouseHandler = (_, node) => setSelected({ node: (node.data as { node: GraphNodeView }).node });
  const onEdgeClick: EdgeMouseHandler = (_, edge) => setSelected({ edge: (edge.data as { edge: GraphEdgeView }).edge });

  const nodeById = useMemo(() => new Map(data?.nodes.map((n) => [n.id, n]) ?? []), [data]);
  const selectedEdges = selected?.node ? data?.edges.filter((e) => e.source === selected.node!.id || e.target === selected.node!.id) ?? [] : [];
  const linkedInvestigation = selected?.node?.investigation_id;

  return (
    <main className="flex h-[calc(100dvh-29px)] flex-col max-lg:h-[calc(100dvh-74px)]">
      <header className="flex flex-wrap items-center justify-between gap-4 border-b border-line px-6 py-3.5">
        <div>
          <h1 className="text-[20px] font-light tracking-[-0.015em]">Evidence Network</h1>
          <p className="text-[13px] text-dim">How claims, evidence, tests, findings and fixes depend on each other.</p>
        </div>
        <select
          aria-label="Investigation"
          className="field !w-auto max-w-80"
          value={investigationId ?? ""}
          onChange={(event) => {
            setSelected(null);
            setFocus(null);
            setInvestigationId(event.target.value);
          }}
        >
          <option value="">All investigations</option>
          {index?.investigations.map((i) => <option key={i.id} value={i.id}>{i.ref} {i.name}</option>)}
        </select>
      </header>
      <div className="flex flex-wrap items-center gap-1.5 border-b border-line px-6 py-2">
        <span className="label mr-1">View</span>
        {VIEWS.map(({ key, label }) => (
          <button
            key={key}
            type="button"
            aria-pressed={view === key && !focus}
            onClick={() => chooseView(key)}
            className={`rounded-sm px-2 py-0.5 text-xs transition-colors ${view === key && !focus ? "bg-raised text-fg" : "text-dim hover:text-fg"}`}
          >
            {label}
          </button>
        ))}
        <span aria-hidden className="mx-1.5 h-3.5 w-px bg-line" />
        <span className="label mr-1">Show</span>
        {KINDS.filter((k) => (VIEWS.find((v) => v.key === view) ?? VIEWS[0]).kinds.includes(k.key)).map(({ key, label }) => {
          const on = !hidden.has(key);
          return (
            <button
              key={key}
              type="button"
              aria-pressed={on}
              onClick={() => {
                const next = new Set(hidden);
                if (on) next.add(key);
                else next.delete(key);
                setHidden(next);
              }}
              className={`rounded-sm border px-2 py-0.5 text-xs transition-colors ${on ? "border-line text-fg" : "border-transparent text-mute line-through"}`}
            >
              {label}
            </button>
          );
        })}
      </div>
      <div className="flex min-h-0 flex-1">
        <div className="relative min-w-0 flex-1 bg-base">
          {error && <div className="p-6"><ErrorNote message={error} onRetry={reload} /></div>}
          {loading && !data && <div className="p-6"><Loading rows={3} /></div>}
          {data && data.nodes.length === 0 && <div className="p-6"><Empty title="Nothing to show">Run an investigation to populate the network.</Empty></div>}
          {data && data.nodes.length > 0 && (
            <ReactFlow
              key={`${investigationId}-${view}-${[...hidden].join()}-${focus}`}
              nodes={flow.nodes}
              edges={flow.edges}
              nodeTypes={nodeTypes}
              onNodeClick={onNodeClick}
              onEdgeClick={onEdgeClick}
              onPaneClick={() => setSelected(null)}
              nodesDraggable
              nodesConnectable={false}
              fitView
              fitViewOptions={{ padding: 0.06, maxZoom: 1 }}
              minZoom={0.15}
              maxZoom={1.6}
              proOptions={{ hideAttribution: true }}
              colorMode="dark"
              style={{ background: "transparent" }}
            >
              <Background variant={BackgroundVariant.Dots} gap={28} size={1} color="#1d1d1d" />
              <Controls showInteractive={false} position="bottom-left" />
            </ReactFlow>
          )}
          <ul aria-label="Relationship key" className="pointer-events-none absolute bottom-3 left-14 flex flex-wrap gap-x-3.5 gap-y-1 rounded-md border border-line bg-surface/95 px-3 py-1.5 text-[11px] text-dim">
            {Object.values(RELATIONS).map((relation) => (
              <li key={relation.label} className="flex items-center gap-1.5">
                <svg width="18" height="4" aria-hidden><line x1="0" y1="2" x2="18" y2="2" stroke={relation.color} strokeWidth="1.5" strokeDasharray={relation.dash} /></svg>
                {relation.label}
              </li>
            ))}
          </ul>
        </div>
        <aside aria-label="Selection details" className="w-[310px] shrink-0 overflow-y-auto border-l border-line p-5 max-md:hidden">
          <input aria-label="Search the network" className="field mb-2" placeholder="Search the network" value={search} onChange={(event) => setSearch(event.target.value)} />
          {matches.length > 0 && (
            <ul className="mb-4 divide-y divide-line/60 border-b border-line">
              {matches.map((node) => (
                <li key={node.id}>
                  <button
                    type="button"
                    onClick={() => {
                      setSelected({ node });
                      setFocus(node.id);
                      setSearch("");
                    }}
                    className="w-full py-1.5 text-left text-[13px] text-dim transition-colors hover:text-fg"
                  >
                    <span className="mono block text-[10.5px] uppercase text-mute">{KINDS.find((k) => k.key === node.kind)?.singular}</span>
                    <span className="line-clamp-2">{node.label}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {focus && (
            <button type="button" onClick={() => setFocus(null)} className="mb-4 text-xs text-dim underline decoration-line underline-offset-4 hover:text-fg">Clear focus</button>
          )}
          {!selected && (
            <>
              <p className="label mb-2 mt-3">Inspector</p>
              <p className="text-sm text-dim">Select a node or relationship to see why it&apos;s there. Scroll to zoom, drag to pan.</p>
              {data && (
                <dl className="mt-6 grid grid-cols-2 gap-4">
                  <Field label="Nodes"><span className="mono">{flow.nodes.length}</span></Field>
                  <Field label="Relationships"><span className="mono">{flow.edges.length}</span></Field>
                </dl>
              )}
            </>
          )}
          {selected?.node && (
            <div className="rise">
              <p className="label mb-1">{KINDS.find((k) => k.key === selected.node!.kind)?.singular}</p>
              <p className="text-[15px] leading-snug">{selected.node.label}</p>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {Object.entries(selected.node.data).filter(([key]) => ["compatibility", "status", "assessment", "reliability", "verification", "origin", "severity"].includes(key)).map(([key, value]) => (
                  <Tag key={key}>{`${key}: ${value}`}</Tag>
                ))}
              </div>
              {!focus && (
                <button type="button" onClick={() => setFocus(selected.node!.id)} className="mt-3 block text-[13px] text-dim underline decoration-line underline-offset-4 hover:text-fg">Focus on this</button>
              )}
              {linkedInvestigation && (
                <Link href={`/investigations/${linkedInvestigation}`} className="mt-4 inline-flex items-center gap-1 text-[13px] text-dim underline decoration-line underline-offset-4 hover:text-fg">
                  Open {selected.node.data.investigation_ref} <ArrowUpRight size={13} aria-hidden />
                </Link>
              )}
              <h2 className="label mb-2 mt-6">Relationships ({selectedEdges.length})</h2>
              <ul className="space-y-2.5">
                {selectedEdges.map((edge) => {
                  const outgoing = edge.source === selected.node!.id;
                  const other = nodeById.get(outgoing ? edge.target : edge.source);
                  return (
                    <li key={edge.id}>
                      <button type="button" onClick={() => setSelected({ edge })} className="w-full text-left text-[13px] text-dim transition-colors hover:text-fg">
                        <span className="mono text-[11px] text-mute">{outgoing ? "" : "← "}{RELATIONS[edge.relation]?.label}{outgoing ? " →" : ""}</span>
                        <span className="line-clamp-2 block">{other?.label}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
          {selected?.edge && (
            <div className="rise">
              <p className="label mb-1">Relationship</p>
              <p className="text-[15px]">{RELATIONS[selected.edge.relation]?.label}</p>
              <dl className="mt-4 space-y-3">
                <Field label="From">{nodeById.get(selected.edge.source)?.label}</Field>
                <Field label="To">{nodeById.get(selected.edge.target)?.label}</Field>
                {selected.edge.explanation && <Field label="Why">{selected.edge.explanation}</Field>}
              </dl>
            </div>
          )}
        </aside>
      </div>
    </main>
  );
}
