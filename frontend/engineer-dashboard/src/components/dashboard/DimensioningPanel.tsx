"use client";

/**
 * Agent 2 — metric object dimensioning (measurecv: RT-DETR → SAM 2 → Metric3D).
 *
 * Two things this panel refuses to hide, because hiding either turns a
 * measurement into a guess that looks like a measurement:
 *
 *   1. The calibration source. An uncalibrated frame carries ~15% scale error.
 *      That is the difference between "the duct is 400mm" and "the duct is
 *      somewhere between 340 and 460mm", and it is invisible in the number
 *      itself, so it gets its own badge at the top.
 *   2. The error bar. Every dimension renders its 95% interval as an actual
 *      bar, not a tooltip. A reader should not have to hover to discover that
 *      the tolerance they care about sits inside the uncertainty.
 */

import React, { useCallback, useRef, useState } from "react";
import { GlassCard } from "../ui/GlassCard";
import { apiBase } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types — mirror agents/measurement/measurecv_backend.py's payload
// ---------------------------------------------------------------------------
interface Quantity {
  value_mm: number;
  sigma_mm: number;
  relative_error: number;
  interval_95_mm: [number, number];
  confidence: number;
  method: string | null;
}

interface VolumeQuantity {
  value: number;
  sigma: number;
  relative_error: number;
  confidence: number;
  method: string | null;
  caveat: string;
}

interface MeasuredObject {
  label: string;
  score: number;
  track_id: number | null;
  bbox_px: [number, number, number, number];
  dimensions_mm: { length: Quantity | null; width: Quantity | null; height: Quantity | null } | null;
  volume_litres: VolumeQuantity | null;
  distance_mm: Quantity | null;
  confidence: number;
  point_count: number;
  mask_area_px: number;
  warnings: string[];
}

interface DimensioningResult {
  status: "success" | "no_measurement" | "unavailable" | "error";
  objects: MeasuredObject[];
  object_count?: number;
  calibration_source?: string;
  scale_accuracy?: string;
  ground_plane_found?: boolean;
  warnings?: string[];
  timings_ms?: Record<string, number>;
  processing_time_ms?: number;
  message?: string;
  remedy?: string;
}

// ---------------------------------------------------------------------------
// Calibration provenance — the headline caveat
// ---------------------------------------------------------------------------
const CALIBRATION_STYLE: Record<string, { color: string; label: string }> = {
  calibrated: { color: "var(--pass)", label: "CALIBRATED · 1–2%" },
  exif: { color: "var(--amber)", label: "EXIF · ~5%" },
  provided: { color: "var(--amber)", label: "CALLER-SUPPLIED" },
  assumed_fov: { color: "var(--fail)", label: "UNCALIBRATED · ~15%" },
};

function confidenceColor(c: number): string {
  if (c >= 0.75) return "var(--pass)";
  if (c >= 0.5) return "var(--amber)";
  return "var(--fail)";
}

// ---------------------------------------------------------------------------
// One dimension, drawn with its uncertainty
// ---------------------------------------------------------------------------
function DimensionRow({ name, q, scaleMax }: { name: string; q: Quantity | null; scaleMax: number }) {
  if (!q) {
    return (
      <div className="flex items-center gap-3 text-[11px] text-[var(--text-secondary)]">
        <span className="w-14 uppercase tracking-wider">{name}</span>
        <span className="italic">not reconstructable</span>
      </div>
    );
  }

  const [lo, hi] = q.interval_95_mm;
  // Bar geometry is in percent of a shared axis, so length/width/height stay
  // visually comparable within an object instead of each rescaling to itself.
  const pct = (v: number) => `${Math.max(0, Math.min(100, (v / scaleMax) * 100))}%`;

  return (
    <div className="flex items-center gap-3">
      <span className="w-14 text-[11px] uppercase tracking-wider text-[var(--text-secondary)]">
        {name}
      </span>

      <span className="w-32 font-mono text-[13px] text-[var(--text-primary)] tabular-nums">
        {q.value_mm.toFixed(0)}
        <span className="text-[var(--text-secondary)]"> ± {q.sigma_mm.toFixed(0)} mm</span>
      </span>

      <div className="relative h-[6px] flex-1 rounded-full bg-[var(--bg-elevated)]">
        {/* 95% interval */}
        <div
          className="absolute top-0 h-full rounded-full opacity-40"
          style={{ left: pct(lo), width: pct(hi - lo), backgroundColor: confidenceColor(q.confidence) }}
        />
        {/* point estimate */}
        <div
          className="absolute top-[-3px] h-[12px] w-[2px] rounded"
          style={{ left: pct(q.value_mm), backgroundColor: confidenceColor(q.confidence) }}
        />
      </div>

      <span className="w-24 text-right font-mono text-[10px] text-[var(--text-secondary)] tabular-nums">
        ±{(q.relative_error * 100).toFixed(1)}%
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
function ObjectCard({ obj }: { obj: MeasuredObject }) {
  const d = obj.dimensions_mm;
  const values = [d?.length?.interval_95_mm[1], d?.width?.interval_95_mm[1], d?.height?.interval_95_mm[1]]
    .filter((v): v is number => typeof v === "number");
  const scaleMax = values.length ? Math.max(...values) * 1.05 : 1;

  return (
    <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-semibold uppercase tracking-wider text-[var(--text-primary)]">
            {obj.label}
          </span>
          {obj.track_id !== null && (
            <span className="rounded bg-[var(--bg-elevated)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--text-secondary)]">
              #{obj.track_id}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] uppercase tracking-widest text-[var(--text-secondary)]">
            confidence
          </span>
          <span
            className="font-mono text-[13px] font-bold tabular-nums"
            style={{ color: confidenceColor(obj.confidence) }}
          >
            {(obj.confidence * 100).toFixed(0)}%
          </span>
        </div>
      </div>

      <div className="space-y-2">
        <DimensionRow name="Length" q={d?.length ?? null} scaleMax={scaleMax} />
        <DimensionRow name="Width" q={d?.width ?? null} scaleMax={scaleMax} />
        <DimensionRow name="Height" q={d?.height ?? null} scaleMax={scaleMax} />
      </div>

      <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 border-t border-[var(--border-subtle)] pt-3 font-mono text-[11px] text-[var(--text-secondary)]">
        {obj.distance_mm && (
          <span>
            standoff{" "}
            <span className="text-[var(--text-primary)]">
              {(obj.distance_mm.value_mm / 1000).toFixed(2)} m
            </span>
          </span>
        )}
        {obj.volume_litres && (
          <span title={obj.volume_litres.caveat}>
            volume{" "}
            <span className="text-[var(--text-primary)]">
              {obj.volume_litres.value.toFixed(1)} L
            </span>
            <span className="text-[var(--amber)]"> ⓘ</span>
          </span>
        )}
        <span>
          points <span className="text-[var(--text-primary)]">{obj.point_count}</span>
        </span>
        {d?.length?.method && <span>method {d.length.method}</span>}
      </div>

      {obj.warnings.length > 0 && (
        <ul className="mt-3 space-y-1">
          {obj.warnings.map((w, i) => (
            <li key={i} className="flex gap-2 text-[11px] leading-snug text-[var(--amber)]">
              <span aria-hidden>⚠</span>
              <span>{w}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
export function DimensioningPanel({ className = "" }: { className?: string }) {
  const [result, setResult] = useState<DimensioningResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const measure = useCallback(async (file: File) => {
    setBusy(true);
    setError(null);
    setResult(null);
    setPreview(URL.createObjectURL(file));

    try {
      const body = new FormData();
      body.append("file", file);
      body.append("max_objects", "8");

      const res = await fetch(`${apiBase()}/api/v1/measurement/objects`, {
        method: "POST",
        body,
      });
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(`HTTP ${res.status}: ${detail.slice(0, 200)}`);
      }
      setResult((await res.json()) as DimensioningResult);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, []);

  const calib = result?.calibration_source
    ? CALIBRATION_STYLE[result.calibration_source] ?? {
        color: "var(--text-secondary)",
        label: result.calibration_source.toUpperCase(),
      }
    : null;

  return (
    <GlassCard className={`p-5 ${className}`} accentColor="var(--cyan)">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h3
            className="text-sm font-bold uppercase tracking-widest text-[var(--text-primary)]"
            style={{ fontFamily: "var(--font-display)" }}
          >
            Metric Dimensioning
          </h3>
          <p className="mt-1 text-[11px] text-[var(--text-secondary)]">
            Agent 2 · RT-DETR → SAM 2 → Metric3D · every value carries a 95% interval
          </p>
        </div>

        <div className="flex shrink-0 gap-2">
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            capture="environment"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void measure(f);
            }}
          />
          <button
            onClick={() => fileRef.current?.click()}
            disabled={busy}
            className="rounded border border-[var(--border-accent)] bg-[var(--bg-elevated)] px-3 py-1.5 text-[11px] font-bold uppercase tracking-widest text-[var(--text-primary)] transition hover:bg-[var(--bg-hover)] disabled:opacity-40"
          >
            {busy ? "Measuring…" : "Capture / Upload"}
          </button>
        </div>
      </div>

      {busy && (
        <div className="rounded border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4 text-[12px] text-[var(--text-secondary)]">
          Running detection, segmentation and metric depth. On CPU this takes roughly
          20–30 s per frame — the models run at their trained resolution rather than a
          downscaled one, because shrinking the depth input silently costs up to 45%
          accuracy.
        </div>
      )}

      {error && (
        <div className="rounded border border-[var(--fail)] bg-[var(--fail-dim)] p-3 text-[12px] text-[var(--fail)]">
          {error}
        </div>
      )}

      {result && !busy && (
        <>
          <div className="mb-4 flex flex-wrap items-center gap-3">
            {calib && (
              <span
                className="rounded border px-2 py-1 text-[10px] font-bold uppercase tracking-widest"
                style={{ color: calib.color, borderColor: calib.color, backgroundColor: "transparent" }}
                title={result.scale_accuracy}
              >
                {calib.label}
              </span>
            )}
            <span className="text-[11px] text-[var(--text-secondary)]">
              {result.object_count ?? 0} object(s) ·{" "}
              {result.ground_plane_found ? "support plane found" : "no support plane — free PCA box"}
              {result.processing_time_ms != null && ` · ${(result.processing_time_ms / 1000).toFixed(1)}s`}
            </span>
          </div>

          {result.scale_accuracy && result.calibration_source === "assumed_fov" && (
            <p className="mb-4 rounded border border-[var(--amber)] bg-[var(--amber-dim)] p-3 text-[11px] leading-snug text-[var(--amber)]">
              No camera calibration is in effect, so absolute scale rests on an assumed
              60° field of view. Treat these as indicative. Calibrating the camera, or
              putting a credit card or A4 sheet in frame, takes this to 1–2%.
            </p>
          )}

          {preview && (
            <img
              src={preview}
              alt="measured frame"
              className="mb-4 max-h-56 w-full rounded border border-[var(--border-subtle)] object-contain"
            />
          )}

          {result.status === "success" ? (
            <div className="space-y-3">
              {result.objects.map((o, i) => (
                <ObjectCard key={`${o.label}-${i}`} obj={o} />
              ))}
            </div>
          ) : (
            <div className="rounded border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4">
              <p className="text-[12px] font-semibold uppercase tracking-wider text-[var(--amber)]">
                {result.status.replace(/_/g, " ")}
              </p>
              <p className="mt-2 text-[12px] leading-snug text-[var(--text-secondary)]">
                {result.message}
              </p>
              {result.remedy && (
                <p className="mt-2 text-[11px] leading-snug text-[var(--text-secondary)]">
                  <span className="font-semibold text-[var(--text-primary)]">Remedy: </span>
                  {result.remedy}
                </p>
              )}
            </div>
          )}
        </>
      )}

      {!result && !busy && !error && (
        <p className="text-[12px] leading-snug text-[var(--text-secondary)]">
          Capture a frame to measure objects in it. The detector recognises the 80 COCO
          classes; construction-specific assets such as rebar mats and formwork need a
          fine-tuned detector and are reported as unmeasurable rather than guessed at.
        </p>
      )}
    </GlassCard>
  );
}
