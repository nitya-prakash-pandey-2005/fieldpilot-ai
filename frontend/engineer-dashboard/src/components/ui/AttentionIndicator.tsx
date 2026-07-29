"use client";
import React from 'react';

// Mirrors agents/vision/attention_tracker.py's three states exactly.
export type AttentionState = 'PASSIVE' | 'ACKNOWLEDGED' | 'ESCALATED';

const STYLES: Record<AttentionState, { color: string; dim: string; label: string; pulse: boolean }> = {
  PASSIVE:      { color: 'var(--text-muted)', dim: 'var(--bg-hover)',  label: 'PASSIVE',      pulse: false },
  ACKNOWLEDGED: { color: 'var(--pass)',       dim: 'var(--pass-dim)',  label: 'ACKNOWLEDGED', pulse: false },
  ESCALATED:    { color: 'var(--fail)',       dim: 'var(--fail-dim)',  label: 'ESCALATED',    pulse: true  },
};

/**
 * Shows a worker's Day-4 attention state (PASSIVE -> ACKNOWLEDGED ->
 * ESCALATED) — whether they've held an acknowledging gaze on an active
 * hazard, or ignored it long enough to escalate. See
 * agents/vision/attention_tracker.py for the dwell/timeout thresholds.
 */
export function AttentionIndicator({ state }: { state: AttentionState | string | undefined }) {
  const style = STYLES[(state as AttentionState) in STYLES ? (state as AttentionState) : 'PASSIVE'];
  return (
    <div
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border ${style.pulse ? 'animate-pulse' : ''}`}
      style={{ backgroundColor: style.dim, borderColor: `${style.color}4d` }}
      title="Attention state: worker's gaze relative to an active hazard"
    >
      <div className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: style.color }} />
      <span
        className="text-[9px] font-bold tracking-wider"
        style={{ color: style.color, fontFamily: 'var(--font-mono)' }}
      >
        {style.label}
      </span>
    </div>
  );
}
