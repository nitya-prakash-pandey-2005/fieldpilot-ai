"use client";

/**
 * Agent Flow — the 10-agent graph, executing.
 *
 * Follow.md section 8.4 asks for "a live-updating version of the diagram: light
 * up each of the 10 agent nodes as they actually fire during a real request, so
 * judges can watch the pipeline execute rather than read about it."
 *
 * Three decisions worth stating, because all three are load-bearing:
 *
 * 1. THE DIAGRAM IS NOT DRAWN HERE. Nodes and edges come from
 *    GET /api/v1/orchestrator/graph, which the backend builds from the same
 *    structures it compiles the LangGraph from. A hand-drawn diagram would be a
 *    picture of the architecture we intended; this is a picture of the one that
 *    runs, and it cannot drift.
 *
 * 2. THE WIRES ARE MEASURED, NOT SCALED. An earlier version drew edges in an
 *    SVG with viewBox="0 0 100 100" and preserveAspectRatio="none", so the
 *    coordinate system stretched with the container. That keeps lines attached
 *    to boxes but distorts every stroke and makes arrowheads impossible, which
 *    is why the graph read as a faint grey smudge. The canvas is measured with
 *    a ResizeObserver and the overlay is drawn in real pixels — so strokes hold
 *    their weight, corners are properly rounded, and edges can carry direction.
 *
 * 3. IT HAS TO BE USEFUL BEFORE YOU RUN ANYTHING. The API sends a one-line
 *    description of every agent's job and the page used to throw it away,
 *    leaving ten identical boxes reading "WAITING". Idle nodes now show what
 *    that agent does, so the page is a readable architecture reference when
 *    nothing is running and a live trace when something is.
 *
 * Node status is whatever the backend reported: ok / skipped / error. "Skipped"
 * is a first-class state with its reason attached, not a hidden one — an agent
 * that did not run is information, and dropping it would let a viewer assume
 * all ten fire on every frame.
 */

import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { GlassCard } from '@/components/ui/GlassCard';
import { apiBase } from '@/lib/api';
import {
  Activity, AlertTriangle, Camera, CheckCircle2, ChevronRight, CircleDashed,
  Cloud, Cpu, Play, Radio, SkipForward, Upload, Volume2, XCircle,
} from 'lucide-react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type NodeStatus = 'idle' | 'running' | 'ok' | 'skipped' | 'error';

interface GraphNode { id: string; n: number; label: string; lane: string; desc: string; }
interface GraphEdge { source: string; target: string; kind: 'always' | 'conditional'; }
interface Topology { nodes: GraphNode[]; edges: GraphEdge[]; lanes: { id: string; label: string }[]; }

interface TraceRow {
  node: string; agent: number; label: string; lane: string;
  status: 'ok' | 'skipped' | 'error';
  at_ms: number; duration_ms: number;
  backend: string | null; summary: string; error: string | null;
}

interface NodeRuntime {
  status: NodeStatus;
  at_ms?: number;
  duration_ms?: number;
  backend?: string | null;
  summary?: string;
}

// ---------------------------------------------------------------------------
// Layout
// ---------------------------------------------------------------------------
//
// Percentages of the canvas. Kept as fractions rather than pixels so the graph
// reflows with the window; converted to pixels once the canvas is measured.

const POS: Record<string, { x: number; y: number }> = {
  agent5_voice:        { x: 8,  y: 50 },
  agent1_vision:       { x: 22, y: 50 },
  agent2_measurement:  { x: 35, y: 20 },   // ─┐ the parallel pair: these two run
  agent4_hazard:       { x: 35, y: 80 },   // ─┘ concurrently, then rejoin
  agent3_compliance:   { x: 50, y: 50 },
  agent7_knowledge:    { x: 65, y: 20 },
  agent6_rfi:          { x: 80, y: 20 },
  agent8_notification: { x: 72, y: 62 },
  agent9_memory:       { x: 86, y: 62 },
  agent10_learning:    { x: 86, y: 87 },
};

const CANVAS_MIN_W = 1120;
const CANVAS_H = 470;
const CARD_W = 148;

// Column headings. These describe what the stage does, not "01 / 02 / 03" —
// the order is already obvious from left-to-right; the phase is not.
const STAGES: { x: number; label: string }[] = [
  { x: 13, label: 'Capture' },
  { x: 35, label: 'Analyse' },
  { x: 50, label: 'Decide' },
  { x: 72, label: 'Act & remember' },
];

// Contrast strategy: the canvas is a RECESSED board (--bg-base) and the nodes
// are RAISED cards (--bg-surface) sitting on it. That inversion is what makes
// the graph legible in both themes — an earlier version filled the cards with
// --bg-elevated, which is #F8F9FE in the light theme and therefore invisible
// against the white card the graph sits inside.
//
// Idle borders are mixed from --text-muted rather than --border-muted for the
// same reason: --border-muted is rgba(0,0,0,0.10) in light and rgba(255,…,0.10)
// in dark, both of which vanish at this size.
const IDLE_LINE = 'color-mix(in srgb, var(--text-muted) 45%, transparent)';
const CARD_LIFT = '0 1px 3px rgba(0,0,0,0.10), 0 1px 2px rgba(0,0,0,0.06)';

const STATUS_STYLE: Record<NodeStatus, {
  border: string; text: string; glow: string; fill: string; Icon: any; word: string;
}> = {
  idle: {
    border: IDLE_LINE, text: 'var(--text-muted)', glow: CARD_LIFT,
    fill: 'var(--bg-surface)', Icon: CircleDashed, word: 'idle',
  },
  running: {
    border: 'var(--cyan)', text: 'var(--cyan)',
    glow: '0 0 0 1px var(--cyan), 0 0 26px rgba(0,212,255,0.45)',
    fill: 'color-mix(in srgb, var(--cyan) 14%, var(--bg-surface))',
    Icon: Activity, word: 'running',
  },
  ok: {
    border: 'var(--pass)', text: 'var(--pass)',
    glow: `${CARD_LIFT}, 0 0 16px rgba(0,230,118,0.22)`,
    fill: 'color-mix(in srgb, var(--pass) 11%, var(--bg-surface))',
    Icon: CheckCircle2, word: 'fired',
  },
  skipped: {
    border: 'var(--amber)', text: 'var(--amber)', glow: CARD_LIFT,
    fill: 'color-mix(in srgb, var(--amber) 10%, var(--bg-surface))',
    Icon: SkipForward, word: 'skipped',
  },
  error: {
    border: 'var(--fail)', text: 'var(--fail)',
    glow: `${CARD_LIFT}, 0 0 18px rgba(229,57,53,0.3)`,
    fill: 'color-mix(in srgb, var(--fail) 12%, var(--bg-surface))',
    Icon: XCircle, word: 'failed',
  },
};

// node id -> key in the run response. Agent 10 is the odd one: the graph writes
// it to `learning`, the API surfaces it as `prediction`.
const RESULT_KEY: Record<string, string> = {
  agent1_vision: 'vision', agent2_measurement: 'measurement',
  agent3_compliance: 'compliance', agent4_hazard: 'hazard',
  agent5_voice: 'voice', agent6_rfi: 'rfi', agent7_knowledge: 'knowledge',
  agent8_notification: 'notification', agent9_memory: 'memory',
  agent10_learning: 'prediction',
};

// ---------------------------------------------------------------------------

export default function ArchitecturePage() {
  const API = apiBase();

  const [topology, setTopology] = useState<Topology | null>(null);
  const [runtime, setRuntime] = useState<Record<string, NodeRuntime>>({});
  const [trace, setTrace] = useState<TraceRow[]>([]);
  const [firedNodes, setFiredNodes] = useState<Set<string>>(new Set());
  const [mode, setMode] = useState<'cloud' | 'edge'>('cloud');
  const [backends, setBackends] = useState<any>(null);
  const [running, setRunning] = useState(false);
  const [lastRun, setLastRun] = useState<any>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [spoken, setSpoken] = useState<{ text: string; audio: string | null; backend: string | null } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [streamLive, setStreamLive] = useState(false);
  const [cameraOn, setCameraOn] = useState(false);

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  // -- canvas measurement --------------------------------------------------

  const canvasRef = useRef<HTMLDivElement | null>(null);
  const [box, setBox] = useState({ w: CANVAS_MIN_W, h: CANVAS_H });

  useLayoutEffect(() => {
    const el = canvasRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setBox({ w: Math.max(width, CANVAS_MIN_W), h: Math.max(height, 240) });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const px = useCallback(
    (id: string) => {
      const p = POS[id];
      return p ? { x: (p.x / 100) * box.w, y: (p.y / 100) * box.h } : null;
    },
    [box],
  );

  // -- topology + backend status ------------------------------------------

  useEffect(() => {
    fetch(`${API}/api/v1/orchestrator/graph`)
      .then(r => r.json()).then(setTopology)
      .catch(() => setError('Could not load the graph topology. Is the API running on port 8000?'));
    fetch(`${API}/api/v1/orchestrator/status`)
      .then(r => r.json()).then(setBackends).catch(() => {});
  }, [API]);

  // -- live event stream ---------------------------------------------------

  useEffect(() => {
    const es = new EventSource(`${API}/api/v1/orchestrator/stream`);
    es.onopen = () => setStreamLive(true);
    es.onerror = () => setStreamLive(false);
    es.onmessage = (e) => {
      let ev: any;
      try { ev = JSON.parse(e.data); } catch { return; }

      if (ev.type === 'run_start') {
        setRuntime({}); setTrace([]); setFiredNodes(new Set());
        setLastRun(null); setSpoken(null); setSelected(null);
      } else if (ev.type === 'node_start') {
        setRuntime(prev => ({ ...prev, [ev.node]: { status: 'running', at_ms: ev.at_ms } }));
      } else if (ev.type === 'node_end') {
        setRuntime(prev => ({
          ...prev,
          [ev.node]: {
            status: ev.status, at_ms: ev.at_ms, duration_ms: ev.duration_ms,
            backend: ev.backend, summary: ev.summary,
          },
        }));
        setTrace(prev => [...prev, ev as TraceRow]);
        // Only edges leaving a node that produced something light up. A skipped
        // node's wires stay dark, which is how the conditional routing becomes
        // visible: you can see which way the run actually went.
        if (ev.status === 'ok') {
          setFiredNodes(prev => new Set(prev).add(ev.node));
        }
      }
    };
    return () => es.close();
  }, [API]);

  // -- camera --------------------------------------------------------------

  const startCamera = useCallback(async () => {
    try {
      const s = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 } },
        audio: false,
      });
      streamRef.current = s;
      if (videoRef.current) { videoRef.current.srcObject = s; await videoRef.current.play(); }
      setCameraOn(true);
      setError(null);
    } catch (e: any) {
      setError(`Camera unavailable: ${e?.message ?? e}. Upload an image instead.`);
    }
  }, []);

  useEffect(() => () => { streamRef.current?.getTracks().forEach(t => t.stop()); }, []);

  const grabFrame = (): string | null => {
    const v = videoRef.current;
    if (!v || !v.videoWidth) return null;
    const c = document.createElement('canvas');
    c.width = v.videoWidth; c.height = v.videoHeight;
    c.getContext('2d')!.drawImage(v, 0, 0);
    return c.toDataURL('image/jpeg', 0.85).split(',')[1];
  };

  // -- run -----------------------------------------------------------------

  const runPipeline = useCallback(async (frame_b64: string) => {
    setRunning(true); setError(null);
    try {
      const res = await fetch(`${API}/api/v1/orchestrator/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ frame_b64, mode, zone_id: 'A12', worker_id: 'W-001' }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail ?? `Run failed (${res.status})`);
      }
      const out = await res.json();
      setLastRun(out);
      const n = out.notification ?? {};
      setSpoken({ text: n.spoken_text ?? '', audio: n.audio_base64 ?? null, backend: n.tts_backend ?? null });
      if (n.audio_base64 && audioRef.current) {
        audioRef.current.src = `data:audio/wav;base64,${n.audio_base64}`;
        audioRef.current.play().catch(() => {/* autoplay blocked — control is visible */});
      }
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      setRunning(false);
    }
  }, [API, mode]);

  const onCapture = () => {
    const frame = grabFrame();
    if (!frame) { setError('No camera frame yet. Start the camera first, or upload an image.'); return; }
    runPipeline(frame);
  };

  const onUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    const reader = new FileReader();
    reader.onload = () => runPipeline(String(reader.result).split(',')[1]);
    reader.readAsDataURL(f);
  };

  // -- derived -------------------------------------------------------------

  const nodeState = (id: string): NodeRuntime => runtime[id] ?? { status: 'idle' };
  const totalSpan = useMemo(
    () => (trace.length ? Math.max(...trace.map(t => t.at_ms + t.duration_ms), 1) : 1),
    [trace],
  );

  const modeInfo = backends?.modes?.[mode];
  const edgeUnavailable = mode === 'edge' && modeInfo?.vision?.available === false;
  const selectedNode = topology?.nodes.find(n => n.id === selected) ?? null;
  const selectedPayload = selectedNode && lastRun ? lastRun[RESULT_KEY[selectedNode.id]] : null;

  return (
    <div className="flex flex-col gap-4 pb-10">

      {/* ── Header + controls in one band ──────────────────────── */}
      <GlassCard className="p-4">
        <div className="flex flex-wrap items-start justify-between gap-4 mb-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-[10px] font-semibold tracking-[0.18em] uppercase"
                 style={{ color: streamLive ? 'var(--pass)' : 'var(--text-muted)' }}>
              <Radio size={11} />
              {streamLive ? 'Event stream connected' : 'Event stream offline'}
            </div>
            <h1 className="text-xl font-semibold text-[var(--text-primary)] mt-0.5">Agent Flow</h1>
            <p className="text-xs text-[var(--text-secondary)] mt-1 max-w-2xl">
              Ten agents, one frame. Each node lights up when it actually runs — the diagram is
              generated from the graph the backend executes, not drawn by hand.
            </p>
          </div>

          {lastRun && (
            <div className="flex items-center gap-5">
              <Stat label="Agents fired" value={`${lastRun.agents_fired}/${lastRun.agents_total}`} />
              <Stat label="Errors" value={String(lastRun.agents_errored)}
                    tone={lastRun.agents_errored ? 'var(--fail)' : 'var(--pass)'} />
              <Stat label="Wall clock" value={`${(lastRun.duration_ms / 1000).toFixed(1)}s`} />
              <Stat label="Run" value={lastRun.run_id.replace('run-', '')} mono />
            </div>
          )}
        </div>

        <div className="flex flex-wrap items-end gap-4 pt-3 border-t border-[var(--border-subtle)]">
          <div className="flex flex-col gap-1.5">
            <span className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-muted)]">Reasoning mode</span>
            <div className="flex rounded-lg overflow-hidden border border-[var(--border-subtle)]">
              <ModeButton active={mode === 'cloud'} onClick={() => setMode('cloud')} Icon={Cloud} label="Cloud" />
              <ModeButton active={mode === 'edge'} onClick={() => setMode('edge')} Icon={Cpu} label="Offline / Edge" />
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <span className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-muted)]">Frame source</span>
            <div className="flex items-center gap-2">
              {!cameraOn ? (
                <Btn onClick={startCamera} Icon={Camera}>Start camera</Btn>
              ) : (
                <Btn onClick={onCapture} disabled={running} primary Icon={Play}>Capture &amp; run</Btn>
              )}
              <Btn onClick={() => fileRef.current?.click()} disabled={running} Icon={Upload}>Upload image</Btn>
              <input ref={fileRef} type="file" accept="image/*" onChange={onUpload} className="hidden" />
            </div>
          </div>

          {modeInfo && (
            <div className="flex flex-wrap gap-x-7 gap-y-2 ml-auto">
              <BackendChip title="Detector" info={modeInfo.vision} />
              <BackendChip title="Depth" info={modeInfo.depth} />
              <BackendChip title="Speech out" info={modeInfo.tts} />
            </div>
          )}

          <video ref={videoRef} muted playsInline
                 className={`rounded-lg border border-[var(--border-subtle)] bg-black ${cameraOn ? 'w-36 h-[76px] object-cover' : 'hidden'}`} />
        </div>

        {running && (
          <div className="mt-3 flex items-center gap-2 text-xs text-[var(--cyan)]">
            <span className="w-2 h-2 rounded-full bg-[var(--cyan)] animate-pulse motion-reduce:animate-none" />
            Running the pipeline — nodes light up as each agent finishes.
          </div>
        )}
        {edgeUnavailable && (
          <p className="mt-3 text-xs text-[var(--amber)] flex items-start gap-2">
            <AlertTriangle size={13} className="mt-0.5 shrink-0" />
            Edge mode has no detector loaded, so Agent 1 will report why and stop rather than guess.
            The rest of the graph still runs.
          </p>
        )}
        {error && (
          <p className="mt-3 text-xs text-[var(--fail)] flex items-start gap-2">
            <AlertTriangle size={13} className="mt-0.5 shrink-0" />{error}
          </p>
        )}
      </GlassCard>

      {/* ── The graph ──────────────────────────────────────────── */}
      <GlassCard className="p-0 overflow-hidden">
        <div className="px-5 py-2.5 border-b border-[var(--border-subtle)] flex items-center justify-between flex-wrap gap-2">
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">Execution graph</h2>
          <div className="flex items-center gap-4 text-[11px] text-[var(--text-muted)]">
            <LegendDot color="var(--cyan)" label="running" />
            <LegendDot color="var(--pass)" label="fired" />
            <LegendDot color="var(--amber)" label="skipped" />
            <LegendDot color="var(--fail)" label="failed" />
            <span className="flex items-center gap-1.5">
              <svg width="22" height="6" aria-hidden>
                <line x1="0" y1="3" x2="22" y2="3" stroke="var(--text-muted)" strokeWidth="1.5" strokeDasharray="4 3" />
              </svg>
              conditional
            </span>
          </div>
        </div>

        <div className="overflow-x-auto">
          <div ref={canvasRef}
               className="relative bg-[var(--bg-base)]"
               style={{ minWidth: CANVAS_MIN_W, height: CANVAS_H }}>

            {/* stage headings */}
            {STAGES.map(s => (
              <div key={s.label}
                   className="absolute top-2 -translate-x-1/2 text-[10px] uppercase tracking-[0.18em] text-[var(--text-muted)] pointer-events-none"
                   style={{ left: `${s.x}%` }}>
                {s.label}
              </div>
            ))}

            {/* wires — drawn in real pixels so strokes and arrowheads hold */}
            <svg className="absolute inset-0 pointer-events-none" width={box.w} height={box.h} aria-hidden>
              <defs>
                {['idle', 'fired', 'live'].map(k => (
                  <marker key={k} id={`arrow-${k}`} viewBox="0 0 10 10" refX="9" refY="5"
                          markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                    <path d="M 0 0 L 10 5 L 0 10 z"
                          fill={k === 'live' ? 'var(--cyan)' : k === 'fired' ? 'var(--pass)' : IDLE_LINE} />
                  </marker>
                ))}
              </defs>
              {topology?.edges
                .filter(e => POS[e.source] && POS[e.target])
                .map((e, i) => {
                  const a = px(e.source)!, b = px(e.target)!;
                  const targetState = nodeState(e.target).status;
                  const live = firedNodes.has(e.source) && targetState === 'running';
                  const fired = firedNodes.has(e.source) &&
                                ['ok', 'skipped', 'error'].includes(targetState);
                  const kind = live ? 'live' : fired ? 'fired' : 'idle';
                  const stroke = live ? 'var(--cyan)' : fired ? 'var(--pass)' : IDLE_LINE;

                  // Orthogonal route with rounded corners: with ten nodes on
                  // four rows, straight diagonals cross into unreadable noise.
                  const midX = (a.x + b.x) / 2;
                  const r = Math.min(14, Math.abs(b.y - a.y) / 2);
                  const dir = b.y > a.y ? 1 : -1;
                  const d = Math.abs(b.y - a.y) < 2
                    ? `M ${a.x} ${a.y} L ${b.x} ${b.y}`
                    : `M ${a.x} ${a.y} L ${midX - r} ${a.y}`
                      + ` Q ${midX} ${a.y} ${midX} ${a.y + r * dir}`
                      + ` L ${midX} ${b.y - r * dir}`
                      + ` Q ${midX} ${b.y} ${midX + r} ${b.y}`
                      + ` L ${b.x} ${b.y}`;

                  return (
                    <path key={i} d={d} fill="none"
                          stroke={stroke}
                          strokeWidth={live ? 2.5 : fired ? 2 : 1.5}
                          strokeDasharray={e.kind === 'conditional' ? '5 4' : undefined}
                          markerEnd={`url(#arrow-${kind})`}
                          opacity={live ? 1 : fired ? 0.9 : 0.75}
                          className={live ? 'animate-pulse motion-reduce:animate-none' : ''} />
                  );
                })}
            </svg>

            {/* nodes */}
            {topology?.nodes.map(n => {
              const p = POS[n.id];
              if (!p) return null;
              const st = nodeState(n.id);
              const s = STATUS_STYLE[st.status];
              const Icon = s.Icon;
              const isSel = selected === n.id;

              return (
                <button
                  key={n.id}
                  onClick={() => setSelected(isSel ? null : n.id)}
                  aria-pressed={isSel}
                  className="absolute -translate-x-1/2 -translate-y-1/2 text-left rounded-xl transition-all duration-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--cyan)]"
                  style={{ left: `${p.x}%`, top: `${p.y}%`, width: CARD_W }}
                >
                  <div className="rounded-xl border px-3 py-2.5 backdrop-blur"
                       style={{
                         borderColor: isSel ? 'var(--cyan)' : s.border,
                         background: s.fill,
                         boxShadow: isSel ? '0 0 0 2px var(--cyan)' : s.glow,
                       }}>
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[10px] font-mono tracking-wider text-[var(--text-muted)]">
                        {String(n.n).padStart(2, '0')}
                      </span>
                      <Icon size={13} style={{ color: s.text }}
                            className={st.status === 'running' ? 'animate-spin motion-reduce:animate-none' : ''} />
                    </div>

                    <div className="text-[12.5px] font-semibold leading-tight mt-0.5 text-[var(--text-primary)]">
                      {n.label}
                    </div>

                    <div className="text-[9.5px] uppercase tracking-wider mt-1 flex items-center gap-1.5"
                         style={{ color: s.text }}>
                      {s.word}
                      {st.duration_ms != null && (
                        <span className="text-[var(--text-muted)] font-mono normal-case tracking-normal tabular-nums">
                          {st.duration_ms}ms
                        </span>
                      )}
                    </div>

                    {/* Idle shows the agent's job; a run replaces it with what
                        that agent actually reported. */}
                    <div className="text-[10px] leading-snug mt-1 line-clamp-2"
                         style={{ color: st.summary ? 'var(--text-secondary)' : 'var(--text-muted)' }}
                         title={st.summary || n.desc}>
                      {st.summary || n.desc}
                    </div>
                  </div>
                </button>
              );
            })}

            {!topology && (
              <div className="absolute inset-0 grid place-items-center text-sm text-[var(--text-muted)]">
                Loading graph…
              </div>
            )}
          </div>
        </div>

        <div className="px-5 py-2 border-t border-[var(--border-subtle)] text-[11px] text-[var(--text-muted)]">
          {selected ? 'Click the node again to close its detail.' : 'Click any agent to inspect what it returned.'}
        </div>
      </GlassCard>

      {/* ── Selected agent detail ──────────────────────────────── */}
      {selectedNode && (
        <GlassCard className="p-4" accentColor="var(--cyan)">
          <div className="flex items-start justify-between gap-4 mb-3">
            <div>
              <div className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-muted)]">
                Agent {String(selectedNode.n).padStart(2, '0')} · {selectedNode.lane}
              </div>
              <h3 className="text-base font-semibold text-[var(--text-primary)]">{selectedNode.label}</h3>
              <p className="text-xs text-[var(--text-secondary)] mt-0.5">{selectedNode.desc}</p>
            </div>
            <button onClick={() => setSelected(null)}
                    className="text-xs text-[var(--text-muted)] hover:text-[var(--text-primary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--cyan)]">
              Close
            </button>
          </div>

          {!selectedPayload ? (
            <p className="text-xs text-[var(--text-muted)]">
              No output yet — run a frame to see what this agent returns.
            </p>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <Field label="Status" value={selectedPayload.status} />
              <Field label="Backend that served it" value={selectedPayload.backend ?? '—'} />
              <Field label="Duration" value={selectedPayload.duration_ms != null ? `${selectedPayload.duration_ms} ms` : '—'} />
              <div className="md:col-span-3">
                <Field label="Reported" value={selectedPayload.summary || selectedPayload.reason || '—'} />
              </div>
              <details className="md:col-span-3">
                <summary className="text-[11px] text-[var(--text-muted)] cursor-pointer hover:text-[var(--text-primary)]">
                  Full payload
                </summary>
                <pre className="mt-2 text-[10.5px] leading-relaxed text-[var(--text-secondary)] bg-[var(--bg-base)] rounded-lg p-3 overflow-x-auto max-h-72">
{JSON.stringify(selectedPayload, (k, v) =>
  // Frames and audio are hundreds of KB of base64 — useless to read and they
  // freeze the panel. Everything else is shown verbatim.
  (typeof v === 'string' && v.length > 300 && /^[A-Za-z0-9+/=]+$/.test(v.slice(0, 80)))
    ? `<${Math.round(v.length / 1024)} KB base64 omitted>` : v, 2)}
                </pre>
              </details>
            </div>
          )}
        </GlassCard>
      )}

      {/* ── Spoken response ────────────────────────────────────── */}
      {spoken && (
        <GlassCard className="p-4" accentColor="var(--pass)">
          <div className="flex items-start gap-3">
            <Volume2 size={17} className="text-[var(--pass)] mt-0.5 shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-muted)]">
                What the worker hears
                {spoken.backend && <span className="ml-2 normal-case tracking-normal">· {spoken.backend}</span>}
              </div>
              <p className="text-sm text-[var(--text-primary)] mt-1">{spoken.text}</p>
              {!spoken.audio && (
                <p className="text-xs text-[var(--amber)] mt-1">
                  Not spoken — no speech backend was available for this run.
                </p>
              )}
            </div>
            <audio ref={audioRef} controls className="h-8 max-w-[240px]" />
          </div>
        </GlassCard>
      )}

      {/* ── Timeline ───────────────────────────────────────────── */}
      <GlassCard className="p-0 overflow-hidden">
        <div className="px-5 py-3 border-b border-[var(--border-subtle)]">
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">Execution timeline</h2>
          <p className="text-xs text-[var(--text-muted)] mt-0.5">
            One shared axis, real durations. Bars that overlap ran at the same time — Measurement
            and Hazard are the parallel pair, and you can see them overlap rather than take the
            diagram's word for it.
          </p>
        </div>

        {trace.length === 0 ? (
          <div className="px-5 py-8 text-center text-sm text-[var(--text-muted)]">
            Capture or upload a frame to watch the graph execute.
          </div>
        ) : (
          <div className="divide-y divide-[var(--border-subtle)]">
            {[...trace].sort((a, b) => a.at_ms - b.at_ms).map((t, i) => {
              const s = STATUS_STYLE[t.status];
              const left = (t.at_ms / totalSpan) * 100;
              const width = Math.max((t.duration_ms / totalSpan) * 100, 0.7);
              return (
                <button key={`${t.node}-${i}`}
                        onClick={() => setSelected(t.node)}
                        className="w-full text-left px-5 py-2.5 grid grid-cols-[200px_1fr_84px] gap-4 items-center hover:bg-[var(--bg-hover)]/40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--cyan)]">
                  <div className="min-w-0 flex items-center gap-2">
                    <ChevronRight size={12} className="text-[var(--text-muted)] shrink-0" />
                    <div className="min-w-0">
                      <div className="text-[12px] font-medium text-[var(--text-primary)] truncate">
                        <span className="font-mono text-[var(--text-muted)] mr-1.5">{String(t.agent).padStart(2, '0')}</span>
                        {t.label}
                      </div>
                      <div className="text-[10px] uppercase tracking-wider" style={{ color: s.text }}>
                        {s.word}
                      </div>
                    </div>
                  </div>

                  <div className="min-w-0">
                    <div className="relative h-2 rounded-full bg-[var(--bg-base)] overflow-hidden">
                      <div className="absolute h-full rounded-full"
                           style={{ left: `${left}%`, width: `${width}%`, backgroundColor: s.border, opacity: 0.9 }} />
                    </div>
                    <div className="text-[11px] text-[var(--text-secondary)] mt-1 truncate" title={t.summary}>
                      {t.summary || '—'}
                      {t.backend && <span className="text-[var(--text-muted)]"> · {t.backend}</span>}
                    </div>
                  </div>

                  <div className="text-right font-mono text-[12px] text-[var(--text-primary)] tabular-nums">
                    {t.duration_ms}<span className="text-[var(--text-muted)]">ms</span>
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </GlassCard>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Small pieces
// ---------------------------------------------------------------------------

function Stat({ label, value, tone, mono }: { label: string; value: string; tone?: string; mono?: boolean }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-muted)]">{label}</div>
      <div className={`text-base font-semibold tabular-nums ${mono ? 'font-mono text-sm' : ''}`}
           style={{ color: tone ?? 'var(--text-primary)' }}>
        {value}
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-muted)]">{label}</div>
      <div className="text-xs text-[var(--text-primary)] mt-0.5 break-words">{value}</div>
    </div>
  );
}

function Btn({ children, onClick, disabled, primary, Icon }: {
  children: React.ReactNode; onClick: () => void; disabled?: boolean; primary?: boolean; Icon: any;
}) {
  return (
    <button onClick={onClick} disabled={disabled}
            className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm border transition-colors disabled:opacity-40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--cyan)] ${
              primary
                ? 'bg-[var(--cyan)]/15 border-[var(--cyan)]/50 text-[var(--cyan)] hover:bg-[var(--cyan)]/25'
                : 'bg-[var(--bg-elevated)] border-[var(--border-subtle)] text-[var(--text-primary)] hover:border-[var(--cyan)]'
            }`}>
      <Icon size={15} /> {children}
    </button>
  );
}

function ModeButton({ active, onClick, Icon, label }: { active: boolean; onClick: () => void; Icon: any; label: string }) {
  return (
    <button onClick={onClick} aria-pressed={active}
            className={`flex items-center gap-2 px-3.5 py-2 text-sm transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--cyan)] ${
              active ? 'bg-[var(--cyan)]/15 text-[var(--cyan)]' : 'bg-[var(--bg-elevated)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
            }`}>
      <Icon size={14} /> {label}
    </button>
  );
}

function BackendChip({ title, info }: { title: string; info: any }) {
  if (!info) return null;
  const ok = info.available;
  return (
    <div className="min-w-0">
      <div className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-muted)]">{title}</div>
      <div className="flex items-center gap-1.5 mt-0.5">
        <span className="w-1.5 h-1.5 rounded-full shrink-0"
              style={{ backgroundColor: ok ? 'var(--pass)' : 'var(--amber)' }} />
        <span className="text-xs text-[var(--text-primary)] truncate">{info.backend}</span>
        {info.license && (
          <span className="text-[10px] text-[var(--text-muted)] border border-[var(--border-subtle)] rounded px-1 py-px shrink-0">
            {info.license}
          </span>
        )}
      </div>
      {!ok && info.reason && (
        <div className="text-[10px] text-[var(--amber)] mt-0.5 max-w-[260px] leading-snug">{info.reason}</div>
      )}
    </div>
  );
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="w-2 h-2 rounded-full" style={{ backgroundColor: color }} />
      {label}
    </span>
  );
}
