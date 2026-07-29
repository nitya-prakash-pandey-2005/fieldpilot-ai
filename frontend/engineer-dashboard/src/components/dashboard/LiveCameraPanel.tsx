"use client";

import React, { useEffect, useRef, useState, useCallback } from "react";
import { AttentionIndicator } from "../ui/AttentionIndicator";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
interface HazardSummary {
  risk_level: "normal" | "elevated" | "high" | "critical";
  hazard_score: number;
  worker_count: number;
  fall_events: string[];
  ppe_violations: number;
  active_alerts: string[];
}

interface ComplianceWorker {
  worker_id: string;
  hardhat: boolean;
  vest: boolean;
  gloves: boolean;
  glasses: boolean;
  boots: boolean;
  ppe_score: number;
  fall_detected: boolean;
  risk_level: string;
  hazard_score: number;
  attention_state?: string;
}

interface LiveFramePayload {
  type: string;
  frame: string;          // base64 JPEG
  hazard: HazardSummary;
  detections: {
    compliance: ComplianceWorker[];
    fall_events: string[];
  };
}

interface Props {
  workerId?: string;
  zoneId?: string;
  apiBase?: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
const RISK_COLORS: Record<string, string> = {
  critical: "#FF2D2D",
  high    : "#FF6B00",
  elevated: "#FFB800",
  normal  : "#00E676",
};

const PPE_ICONS: { key: keyof ComplianceWorker; label: string; emoji: string }[] = [
  { key: "hardhat", label: "Hard Hat",  emoji: "🪖" },
  { key: "vest",    label: "Vest",      emoji: "🦺" },
  { key: "gloves",  label: "Gloves",    emoji: "🧤" },
  { key: "glasses", label: "Glasses",   emoji: "🥽" },
  { key: "boots",   label: "Boots",     emoji: "👢" },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export function LiveCameraPanel({
  workerId = "WRK-001",
  zoneId   = "A12",
  apiBase  = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
}: Props) {
  const canvasRef   = useRef<HTMLCanvasElement>(null);
  const wsRef       = useRef<WebSocket | null>(null);
  const frameQueueRef = useRef<string[]>([]);
  const rafRef      = useRef<number>(0);
  const imgRef      = useRef<HTMLImageElement | null>(null);

  const [connected,    setConnected]    = useState(false);
  const [fps,          setFps]          = useState(0);
  const [latencyMs,    setLatencyMs]    = useState(0);
  const [framesRecv,   setFramesRecv]   = useState(0);
  const [hazard,       setHazard]       = useState<HazardSummary | null>(null);
  const [compliance,   setCompliance]   = useState<ComplianceWorker[]>([]);
  const [alerts,       setAlerts]       = useState<string[]>([]);
  const [sourceLabel,  setSourceLabel]  = useState("CONNECTING…");
  const [isPipelineUp, setIsPipelineUp] = useState(false);

  // FPS tracking
  const fpsCountRef  = useRef(0);
  const fpsTimerRef  = useRef(Date.now());

  // ── Canvas draw loop ────────────────────────────────────────────────────
  const drawLoop = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    if (frameQueueRef.current.length > 0) {
      const b64 = frameQueueRef.current.shift()!;
      const img = imgRef.current ?? (imgRef.current = new Image());
      img.onload = () => {
        canvas.width  = img.width  || canvas.clientWidth;
        canvas.height = img.height || canvas.clientHeight;
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      };
      img.src = `data:image/jpeg;base64,${b64}`;
    } else if (!connected) {
      // Draw waiting placeholder
      ctx.fillStyle = "#0A0F1E";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = "rgba(0,200,200,0.15)";
      ctx.font = "14px monospace";
      ctx.fillText("Waiting for live stream…", canvas.width / 2 - 90, canvas.height / 2);
    }

    rafRef.current = requestAnimationFrame(drawLoop);
  }, [connected]);

  // ── WebSocket connection ────────────────────────────────────────────────
  useEffect(() => {
    const wsUrl = apiBase
      .replace("http://", "ws://")
      .replace("https://", "wss://")
      + `/ws/live/${workerId}`;

    let retryTimer: ReturnType<typeof setTimeout>;

    const connect = () => {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        setSourceLabel("LIVE STREAM");
        console.log("[LiveCam] WS connected:", wsUrl);
      };

      ws.onmessage = (evt) => {
        const sendTime = Date.now();
        let data: LiveFramePayload;
        try {
          data = JSON.parse(evt.data);
        } catch {
          return;
        }

        if (data.type !== "live_frame") return;

        // Enqueue frame (cap to 3 to avoid lag)
        if (frameQueueRef.current.length < 3) {
          frameQueueRef.current.push(data.frame);
        }

        // Update stats
        fpsCountRef.current++;
        const now = Date.now();
        const elapsed = now - fpsTimerRef.current;
        if (elapsed >= 1000) {
          setFps(Math.round((fpsCountRef.current * 1000) / elapsed));
          fpsCountRef.current  = 0;
          fpsTimerRef.current  = now;
        }
        setLatencyMs(now - sendTime);
        setFramesRecv(f => f + 1);
        setIsPipelineUp(true);

        if (data.hazard) {
          setHazard(data.hazard);
        }
        if (data.detections?.compliance) {
          setCompliance(data.detections.compliance);
        }
        if (data.hazard?.active_alerts?.length) {
          setAlerts(prev => [
            ...data.hazard.active_alerts,
            ...prev,
          ].slice(0, 20));
        }
      };

      ws.onclose = () => {
        setConnected(false);
        setSourceLabel("RECONNECTING…");
        retryTimer = setTimeout(connect, 2000);
      };

      ws.onerror = () => {
        ws.close();
      };
    };

    connect();
    rafRef.current = requestAnimationFrame(drawLoop);

    // Poll /api/v1/live/status for pipeline health
    const statusPoll = setInterval(async () => {
      try {
        const r = await fetch(`${apiBase}/api/v1/live/status`);
        const s = await r.json();
        setIsPipelineUp(s.pipeline_active && s.active_workers > 0);
      } catch {
        setIsPipelineUp(false);
      }
    }, 3000);

    return () => {
      clearTimeout(retryTimer);
      clearInterval(statusPoll);
      cancelAnimationFrame(rafRef.current);
      wsRef.current?.close();
    };
  }, [workerId, apiBase, drawLoop]);

  // ── Risk colour ─────────────────────────────────────────────────────────
  const riskColor = RISK_COLORS[hazard?.risk_level ?? "normal"] ?? "#00E676";

  return (
    <div className="flex flex-col h-full gap-3">

      {/* ── Top status bar ── */}
      <div
        className="flex items-center justify-between px-4 py-2 rounded-xl border text-xs font-mono"
        style={{
          background: "rgba(10,15,30,0.85)",
          backdropFilter: "blur(12px)",
          borderColor: connected ? riskColor + "55" : "#ffffff22",
          boxShadow: connected ? `0 0 18px ${riskColor}22` : "none",
          transition: "all 0.4s ease",
        }}
      >
        <div className="flex items-center gap-3">
          {/* Live indicator dot */}
          <div className="relative flex items-center gap-1.5">
            <span
              className="w-2 h-2 rounded-full"
              style={{
                background: connected ? riskColor : "#555",
                boxShadow: connected ? `0 0 8px ${riskColor}` : "none",
                animation: connected ? "pulse 1.5s ease-in-out infinite" : "none",
              }}
            />
            <span style={{ color: connected ? riskColor : "#888" }}>
              {sourceLabel}
            </span>
          </div>
          <span className="text-[var(--text-muted)]">Worker: <b className="text-white">{workerId}</b></span>
          <span className="text-[var(--text-muted)]">Zone: <b className="text-white">{zoneId}</b></span>
        </div>

        <div className="flex items-center gap-4">
          <Stat label="FPS"     value={fps}          unit=""   color={fps >= 20 ? "#00E676" : "#FFB800"} />
          <Stat label="Latency" value={latencyMs}    unit="ms" color={latencyMs < 100 ? "#00E676" : "#FF6B00"} />
          <Stat label="Frames"  value={framesRecv}   unit=""   color="#00BFFF" />
          {hazard && (
            <Stat
              label="Risk Score"
              value={hazard.hazard_score}
              unit="/100"
              color={riskColor}
            />
          )}
        </div>
      </div>

      {/* ── Main layout: video + sidebar ── */}
      <div className="flex gap-3 flex-1 min-h-0">

        {/* ── Video canvas ── */}
        <div
          className="relative flex-1 rounded-xl overflow-hidden"
          style={{
            background: "#030810",
            border: `1px solid ${connected ? riskColor + "44" : "#ffffff15"}`,
            boxShadow: connected ? `0 0 40px ${riskColor}18, inset 0 0 60px rgba(0,0,0,0.4)` : "none",
          }}
        >
          <canvas
            ref={canvasRef}
            className="w-full h-full object-contain"
            style={{ display: "block", minHeight: 300 }}
          />

          {/* Offline overlay */}
          {!isPipelineUp && (
            <div
              className="absolute inset-0 flex flex-col items-center justify-center gap-4"
              style={{ background: "rgba(3,8,16,0.88)", backdropFilter: "blur(4px)" }}
            >
              <div className="text-4xl">🎥</div>
              <div className="text-center">
                <p className="text-white font-bold text-lg mb-1">Pipeline Offline</p>
                <p className="text-sm" style={{ color: "#7090B0" }}>
                  Start the live camera pipeline to see the feed
                </p>
                <div className="mt-3 px-4 py-2 rounded-lg text-xs font-mono"
                     style={{ background: "#0A1828", color: "#00BFFF", border: "1px solid #00BFFF33" }}>
                  python scripts/live_camera_pipeline.py
                </div>
                <div className="mt-2 px-4 py-2 rounded-lg text-xs font-mono"
                     style={{ background: "#0A1828", color: "#00BFFF", border: "1px solid #00BFFF33" }}>
                  python scripts/live_camera_pipeline.py --source phone --phone-ip YOUR_IP
                </div>
              </div>
            </div>
          )}

          {/* AR corner brackets */}
          <div className="absolute inset-0 pointer-events-none">
            {[
              "top-3 left-3 border-t-2 border-l-2",
              "top-3 right-3 border-t-2 border-r-2",
              "bottom-3 left-3 border-b-2 border-l-2",
              "bottom-3 right-3 border-b-2 border-r-2",
            ].map((cls, i) => (
              <div
                key={i}
                className={`absolute w-6 h-6 rounded-sm ${cls}`}
                style={{ borderColor: riskColor + "88", transition: "border-color 0.5s" }}
              />
            ))}
          </div>

          {/* Fall alert flash */}
          {hazard && hazard.fall_events.length > 0 && (
            <div
              className="absolute top-4 left-1/2 -translate-x-1/2 px-5 py-2 rounded-full text-sm font-bold"
              style={{
                background: "rgba(255,30,30,0.9)",
                color: "white",
                animation: "pulse 0.6s ease-in-out infinite",
                boxShadow: "0 0 24px #FF2D2D",
              }}
            >
              ⚠ FALL DETECTED — {hazard.fall_events.length} WORKER(S)
            </div>
          )}
        </div>

        {/* ── Sidebar ── */}
        <div className="flex flex-col gap-3 w-64 shrink-0 overflow-y-auto">

          {/* Hazard score card */}
          {hazard ? (
            <div
              className="rounded-xl p-4"
              style={{
                background: "rgba(10,15,30,0.85)",
                backdropFilter: "blur(12px)",
                border: `1px solid ${riskColor}44`,
                boxShadow: `0 0 20px ${riskColor}18`,
              }}
            >
              <p className="text-xs text-[var(--text-muted)] uppercase tracking-widest mb-2">
                Zone Risk
              </p>
              <div className="flex items-end gap-2 mb-1">
                <span className="text-4xl font-black" style={{ color: riskColor, fontVariantNumeric: "tabular-nums" }}>
                  {hazard.hazard_score}
                </span>
                <span className="text-lg text-[var(--text-muted)] mb-1">/100</span>
              </div>
              <div
                className="inline-block px-2 py-0.5 rounded text-xs font-bold uppercase tracking-wider mb-3"
                style={{ background: riskColor + "25", color: riskColor }}
              >
                {hazard.risk_level}
              </div>
              <div className="grid grid-cols-3 gap-2 text-center text-xs">
                <MiniStat label="Workers" value={hazard.worker_count} />
                <MiniStat label="Falls"   value={hazard.fall_events.length} danger={hazard.fall_events.length > 0} />
                <MiniStat label="PPE ⚠"  value={hazard.ppe_violations}     danger={hazard.ppe_violations > 0} />
              </div>
            </div>
          ) : (
            <SkeletonCard />
          )}

          {/* PPE compliance per worker */}
          {compliance.length > 0 && (
            <div
              className="rounded-xl p-3"
              style={{
                background: "rgba(10,15,30,0.85)",
                backdropFilter: "blur(12px)",
                border: "1px solid rgba(255,255,255,0.08)",
              }}
            >
              <p className="text-xs text-[var(--text-muted)] uppercase tracking-widest mb-2">
                PPE Status
              </p>
              <div className="flex flex-col gap-2 max-h-48 overflow-y-auto pr-1">
                {compliance.map((w, i) => (
                  <WorkerPpeRow key={i} worker={w} />
                ))}
              </div>
            </div>
          )}

          {/* Live alerts log */}
          <div
            className="rounded-xl p-3 flex-1 min-h-0"
            style={{
              background: "rgba(10,15,30,0.85)",
              backdropFilter: "blur(12px)",
              border: "1px solid rgba(255,255,255,0.08)",
            }}
          >
            <p className="text-xs text-[var(--text-muted)] uppercase tracking-widest mb-2">
              Event Log
            </p>
            {alerts.length === 0 ? (
              <p className="text-xs text-[var(--text-muted)] italic">No alerts yet</p>
            ) : (
              <div className="flex flex-col gap-1.5 max-h-60 overflow-y-auto pr-1">
                {alerts.map((a, i) => (
                  <div
                    key={i}
                    className="text-xs px-2 py-1.5 rounded"
                    style={{
                      background: "rgba(255,60,60,0.1)",
                      border: "1px solid rgba(255,60,60,0.25)",
                      color: "#FFB0B0",
                    }}
                  >
                    {a}
                  </div>
                ))}
              </div>
            )}
          </div>

        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function Stat({ label, value, unit, color }: { label: string; value: number; unit: string; color: string }) {
  return (
    <div className="flex flex-col items-end">
      <span className="text-[10px] text-[var(--text-muted)] uppercase">{label}</span>
      <span className="font-bold tabular-nums" style={{ color }}>
        {value}{unit}
      </span>
    </div>
  );
}

function MiniStat({ label, value, danger = false }: { label: string; value: number; danger?: boolean }) {
  return (
    <div className="flex flex-col items-center">
      <span
        className="text-base font-black tabular-nums"
        style={{ color: danger && value > 0 ? "#FF4444" : "rgba(255,255,255,0.9)" }}
      >
        {value}
      </span>
      <span className="text-[10px] text-[var(--text-muted)]">{label}</span>
    </div>
  );
}

function WorkerPpeRow({ worker }: { worker: ComplianceWorker }) {
  const riskCol = RISK_COLORS[worker.risk_level] ?? "#00E676";
  return (
    <div
      className="rounded-lg px-2 py-1.5"
      style={{
        background: "rgba(255,255,255,0.03)",
        border: `1px solid ${riskCol}33`,
      }}
    >
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-mono text-white">{worker.worker_id}</span>
        {worker.fall_detected && (
          <span className="text-[10px] font-bold text-red-400 animate-pulse">FALL</span>
        )}
      </div>
      <div className="mb-1">
        <AttentionIndicator state={worker.attention_state} />
      </div>
      <div className="flex gap-1 flex-wrap">
        {PPE_ICONS.map(({ key, emoji }) => {
          const ok = worker[key] as boolean;
          return (
            <span
              key={key}
              title={key}
              className="text-sm"
              style={{ filter: ok ? "none" : "grayscale(1) opacity(0.35)" }}
            >
              {emoji}
            </span>
          );
        })}
        <span className="ml-auto text-[10px] tabular-nums" style={{ color: riskCol }}>
          {Math.round((worker.ppe_score ?? 0) * 100)}%
        </span>
      </div>
    </div>
  );
}

function SkeletonCard() {
  return (
    <div
      className="rounded-xl p-4 animate-pulse"
      style={{ background: "rgba(10,15,30,0.85)", border: "1px solid rgba(255,255,255,0.06)" }}
    >
      <div className="h-3 w-20 rounded mb-3" style={{ background: "rgba(255,255,255,0.06)" }} />
      <div className="h-10 w-16 rounded mb-2" style={{ background: "rgba(255,255,255,0.06)" }} />
      <div className="h-3 w-28 rounded" style={{ background: "rgba(255,255,255,0.06)" }} />
    </div>
  );
}
