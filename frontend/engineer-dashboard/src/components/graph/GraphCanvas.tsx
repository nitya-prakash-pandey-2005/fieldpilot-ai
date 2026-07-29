"use client";
import { useEffect, useRef, useState, useCallback } from 'react';

export interface GraphNode {
  id: string;
  type: string;
  label: string;
  [key: string]: any;
}

export interface GraphEdge {
  source: string;
  target: string;
  type: string;
}

interface SimNode extends GraphNode {
  x: number;
  y: number;
  vx: number;
  vy: number;
}

const TYPE_RADIUS: Record<string, number> = {
  project: 28,
  zone: 20,
  issue: 13,
  incident: 13,
  engineer: 11,
};

const EDGE_LENGTH: Record<string, number> = {
  HAS_ZONE: 170,
  HAS_ISSUE: 100,
  OCCURRED_IN: 100,
  RESOLVED_BY: 75,
};

const SIM_ITERATIONS = 260;

// Custom force-directed layout (repulsion + spring edges + centering) —
// deliberately hand-rolled instead of pulling in d3-force/react-force-graph
// since the graphs here are small (a few dozen nodes) and this keeps the
// bundle free of a new heavy dependency for what's a fairly simple physics
// loop. Positions live in a ref (mutated every animation frame) so re-runs
// don't fight React's render cycle; `tick` just forces a redraw.
export function GraphCanvas({
  nodes,
  edges,
  onSelect,
  selectedId,
  highlightIds,
  colorFor,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  onSelect: (node: GraphNode | null) => void;
  selectedId: string | null;
  highlightIds: Set<string> | null;
  colorFor: (node: GraphNode) => string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const simNodesRef = useRef<Map<string, SimNode>>(new Map());
  const [, setTick] = useState(0);
  const [transform, setTransform] = useState({ x: 0, y: 0, k: 1 });
  const dragRef = useRef<{ id: string | null; panning: boolean; lastX: number; lastY: number; moved: boolean }>({
    id: null, panning: false, lastX: 0, lastY: 0, moved: false,
  });
  const rafRef = useRef<number | null>(null);
  const [dims, setDims] = useState({ w: 900, h: 600 });

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(entries => {
      const { width, height } = entries[0].contentRect;
      if (width > 0 && height > 0) setDims({ w: width, h: height });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const runSimulation = useCallback((w: number, h: number) => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    let iterations = 0;

    const step = () => {
      const simNodes = simNodesRef.current;
      const arr = Array.from(simNodes.values());

      for (let i = 0; i < arr.length; i++) {
        for (let j = i + 1; j < arr.length; j++) {
          const a = arr[i], b = arr[j];
          const dx = b.x - a.x, dy = b.y - a.y;
          let distSq = dx * dx + dy * dy;
          if (distSq < 1) distSq = 1;
          const dist = Math.sqrt(distSq);
          const force = 2600 / distSq;
          const fx = (dx / dist) * force, fy = (dy / dist) * force;
          if (dragRef.current.id !== a.id) { a.vx -= fx; a.vy -= fy; }
          if (dragRef.current.id !== b.id) { b.vx += fx; b.vy += fy; }
        }
      }

      edges.forEach(e => {
        const a = simNodes.get(e.source), b = simNodes.get(e.target);
        if (!a || !b) return;
        const target = EDGE_LENGTH[e.type] || 100;
        const dx = b.x - a.x, dy = b.y - a.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const force = (dist - target) * 0.02;
        const fx = (dx / dist) * force, fy = (dy / dist) * force;
        if (dragRef.current.id !== a.id) { a.vx += fx; a.vy += fy; }
        if (dragRef.current.id !== b.id) { b.vx -= fx; b.vy -= fy; }
      });

      arr.forEach(n => {
        if (dragRef.current.id === n.id) return;
        n.vx += (w / 2 - n.x) * 0.0015;
        n.vy += (h / 2 - n.y) * 0.0015;
        n.vx *= 0.82; n.vy *= 0.82;
        n.x += n.vx; n.y += n.vy;
        n.x = Math.max(30, Math.min(w - 30, n.x));
        n.y = Math.max(30, Math.min(h - 30, n.y));
      });

      iterations++;
      setTick(t => t + 1);
      if (iterations < SIM_ITERATIONS) {
        rafRef.current = requestAnimationFrame(step);
      }
    };
    rafRef.current = requestAnimationFrame(step);
  }, [edges]);

  useEffect(() => {
    const existing = simNodesRef.current;
    const next = new Map<string, SimNode>();
    const w = dims.w || 900, h = dims.h || 600;
    nodes.forEach((n, i) => {
      const prev = existing.get(n.id);
      if (prev) {
        next.set(n.id, { ...prev, ...n });
      } else {
        const angle = (i / Math.max(nodes.length, 1)) * Math.PI * 2;
        const r = Math.min(w, h) * 0.32;
        next.set(n.id, {
          ...n,
          x: w / 2 + Math.cos(angle) * r + (Math.random() - 0.5) * 20,
          y: h / 2 + Math.sin(angle) * r + (Math.random() - 0.5) * 20,
          vx: 0, vy: 0,
        });
      }
    });
    simNodesRef.current = next;
    setTick(t => t + 1);
    runSimulation(w, h);
    // Re-init only when the actual node id set (or canvas size) changes, not on every
    // parent re-render — node property updates (e.g. a poll refresh) still flow through
    // via the `prev` merge above without resetting positions/restarting the sim.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes.map(n => n.id).join('|'), dims.w, dims.h, runSimulation]);

  useEffect(() => () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); }, []);

  const handleNodePointerDown = (e: React.PointerEvent, id: string) => {
    e.stopPropagation();
    dragRef.current.id = id;
    dragRef.current.moved = false;
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
  };

  const handlePointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    if (dragRef.current.id) {
      const rect = e.currentTarget.getBoundingClientRect();
      const x = (e.clientX - rect.left - transform.x) / transform.k;
      const y = (e.clientY - rect.top - transform.y) / transform.k;
      const n = simNodesRef.current.get(dragRef.current.id);
      if (n) {
        n.x = x; n.y = y; n.vx = 0; n.vy = 0;
        dragRef.current.moved = true;
        setTick(t => t + 1);
      }
    } else if (dragRef.current.panning) {
      const dx = e.clientX - dragRef.current.lastX;
      const dy = e.clientY - dragRef.current.lastY;
      dragRef.current.lastX = e.clientX;
      dragRef.current.lastY = e.clientY;
      setTransform(tr => ({ ...tr, x: tr.x + dx, y: tr.y + dy }));
    }
  };

  const handlePointerUp = () => {
    dragRef.current.id = null;
    dragRef.current.panning = false;
  };

  const handleBackgroundPointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    dragRef.current.panning = true;
    dragRef.current.lastX = e.clientX;
    dragRef.current.lastY = e.clientY;
    onSelect(null);
  };

  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const delta = -e.deltaY * 0.0012;
    setTransform(tr => ({ ...tr, k: Math.min(2.5, Math.max(0.35, tr.k + delta * tr.k)) }));
  };

  const simNodes = simNodesRef.current;

  return (
    <div ref={containerRef} className="w-full h-full relative overflow-hidden cursor-grab active:cursor-grabbing">
      <svg
        width="100%"
        height="100%"
        onPointerDown={handleBackgroundPointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerLeave={handlePointerUp}
        onWheel={handleWheel}
      >
        <g transform={`translate(${transform.x},${transform.y}) scale(${transform.k})`}>
          {edges.map((e, i) => {
            const a = simNodes.get(e.source), b = simNodes.get(e.target);
            if (!a || !b) return null;
            const dim = highlightIds && !highlightIds.has(a.id) && !highlightIds.has(b.id);
            return (
              <line
                key={i}
                x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                stroke="var(--border-muted)"
                strokeWidth={1.5}
                opacity={dim ? 0.06 : 0.5}
              />
            );
          })}
          {Array.from(simNodes.values()).map(n => {
            const r = TYPE_RADIUS[n.type] || 12;
            const dim = highlightIds ? !highlightIds.has(n.id) : false;
            const isSelected = selectedId === n.id;
            const color = colorFor(n);
            return (
              <g
                key={n.id}
                transform={`translate(${n.x},${n.y})`}
                onPointerDown={(e) => handleNodePointerDown(e, n.id)}
                onClick={(e) => {
                  e.stopPropagation();
                  if (!dragRef.current.moved) onSelect(n);
                }}
                style={{ cursor: 'pointer', opacity: dim ? 0.15 : 1, transition: 'opacity 0.2s' }}
              >
                <circle r={r} fill={color} fillOpacity={0.16} stroke={color} strokeWidth={isSelected ? 3 : 1.5} />
                <circle r={Math.max(r * 0.4, 4)} fill={color} />
                <text
                  y={r + 14}
                  textAnchor="middle"
                  fontSize={10}
                  fontWeight={600}
                  fill="var(--text-secondary)"
                  style={{ pointerEvents: 'none', userSelect: 'none' }}
                >
                  {n.label.length > 20 ? `${n.label.slice(0, 19)}…` : n.label}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
}
