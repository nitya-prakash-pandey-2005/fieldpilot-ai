"use client";

import React from 'react';
import { formatDistanceToNow } from 'date-fns';
import { StatusBadge } from './StatusBadge';
import { SEVERITY } from '@/theme/severityColors';

// Matches api/models/compliance.py's ComplianceEvent + the response shape
// from GET /api/v1/compliance/issues (api/routes/compliance.py) — the
// output of ComplianceEngine.validate() (agents/compliance/validator.py)
// once persisted. Previously ActiveIssuesPanel.tsx fetched this same
// endpoint but rendered fields (description/timestamp/zone/worker/
// measured/spec/deviation) the backend never actually returned.
export interface ComplianceIssue {
  id: string;
  zone_code: string | null;
  asset_id: string | null;
  field_issue_id?: string | null;
  severity: string; // CRITICAL | HIGH | MEDIUM | LOW
  measured_value: number | null;
  spec_value: number | null;
  deviation_pct: number | null;
  confidence: number | null;
  worker_id: string | null;
  status: string;
  created_at: string;
}

function confidenceColor(c: number) {
  if (c >= 0.9) return 'var(--pass)';
  if (c >= 0.75) return 'var(--amber)';
  return 'var(--fail)';
}

export function ComplianceCard({
  issue,
  onReject,
}: {
  issue: ComplianceIssue;
  // Reject operates on the linked FieldIssue (POST /api/v1/issues/{id}/reject
  // sets FieldIssue.is_hard_negative for the training flywheel) — a
  // ComplianceEvent without a field_issue_id can't be rejected, so the
  // button only renders when one is present.
  onReject?: (issue: ComplianceIssue) => void;
}) {
  const sevKey = (issue.severity || 'low').toLowerCase() as keyof typeof SEVERITY;
  const sev = SEVERITY[sevKey] ?? SEVERITY.low;
  const isCritical = sevKey === 'critical';

  let timeAgo = '';
  try {
    timeAgo = formatDistanceToNow(new Date(issue.created_at), { addSuffix: true });
  } catch {
    timeAgo = '';
  }

  return (
    <div
      className={`p-3 border-b border-[var(--border-subtle)] last:border-0 hover:bg-[var(--bg-hover)] transition-colors cursor-pointer rounded-lg mb-1 relative
        ${isCritical ? 'border-l-[3px] shadow-sm' : ''}`}
      style={{
        animation: isCritical ? 'criticalPulse 1.5s ease-in-out infinite' : 'none',
        borderLeftColor: isCritical ? sev.card_border : 'transparent',
      }}
    >
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2">
          <StatusBadge status={(issue.severity || 'LOW').toUpperCase()} />
          <span className="text-xs font-mono font-semibold text-[var(--text-primary)]">
            {issue.asset_id || issue.id.slice(0, 8)}
          </span>
        </div>
        {timeAgo && <span className="text-[10px] text-[var(--text-muted)] font-mono">{timeAgo}</span>}
      </div>

      {issue.measured_value != null && issue.spec_value != null && (
        <div className="mb-2">
          <span className="inline-flex items-center text-[10px] bg-black/40 border border-white/10 px-2 py-1 rounded font-mono text-[var(--text-secondary)]">
            {issue.measured_value} / spec {issue.spec_value}
            {issue.deviation_pct != null && (
              <span className="font-bold ml-2" style={{ color: sev.deviation }}>
                ({issue.deviation_pct > 0 ? '+' : ''}{issue.deviation_pct.toFixed(1)}%)
              </span>
            )}
          </span>
        </div>
      )}

      {issue.confidence != null && (
        <div className="flex items-center gap-2 mb-2" title="Model's own certainty in this measurement">
          <span className="text-[9px] uppercase tracking-widest text-[var(--text-muted)] font-bold shrink-0">Confidence</span>
          <div className="flex-1 h-1 rounded-full bg-black/40 overflow-hidden max-w-[80px]">
            <div
              className="h-full rounded-full"
              style={{ width: `${Math.round(issue.confidence * 100)}%`, backgroundColor: confidenceColor(issue.confidence) }}
            />
          </div>
          <span className="text-[10px] font-mono font-bold" style={{ color: confidenceColor(issue.confidence) }}>
            {Math.round(issue.confidence * 100)}%
          </span>
        </div>
      )}

      <div className="flex items-center justify-between mt-3">
        <div className="flex flex-col gap-1 text-[10px]">
          {issue.zone_code && (
            <div className="flex items-center gap-1.5 text-[var(--text-muted)]">
              <span className="text-[var(--cyan)]">📍</span> Zone {issue.zone_code}
            </div>
          )}
          {issue.worker_id && (
            <div className="flex items-center gap-1.5 text-[var(--text-muted)] opacity-70">
              <span>👷</span> {issue.worker_id}
            </div>
          )}
        </div>
        {onReject && issue.field_issue_id && (
          <div className="flex items-center gap-2">
            <button
              onClick={() => onReject(issue)}
              className="text-[10px] font-bold text-[var(--fail)] tracking-wider hover:bg-[var(--fail-dim)] border border-[var(--fail)]/30 hover:border-[var(--fail)] transition-all uppercase px-2 py-1 rounded"
              title="Mark as false positive for AI training (Data Flywheel)"
            >
              Reject ✕
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
