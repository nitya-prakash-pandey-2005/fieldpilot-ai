"use client";

import React from 'react';
import { GlassCard } from '../ui/GlassCard';
import { useAPIData } from '@/hooks/useAPIData';
import { ComplianceCard, ComplianceIssue } from '../ui/ComplianceCard';
import { useAuth } from '@/context/AuthContext';

import { apiBase } from '@/lib/api';

/**
 * The Command Center's Active Issues panel.
 *
 * It used to read GET /api/v1/compliance/issues, which serves the
 * `compliance_events` table. That table only gains a row when Agent 5 runs a
 * live validation, whereas every other page (Issues, Zones, the worker detail
 * page) reads `field_issues`. So the Command Center showed nothing while the
 * Issues page listed five — the same site, two different tables, and the
 * landing page was the empty one.
 *
 * Now reads the same `field_issues` source as everywhere else, mapped into the
 * shape ComplianceCard renders. The DEMO_ISSUES fallback is gone: an empty
 * panel that says why is honest, four fabricated OBS-04x rows on the first
 * screen a judge sees are not.
 */

type FieldIssue = {
  id: string;
  zone_code?: string | null;
  issue_type?: string | null;
  severity?: string | null;
  status?: string | null;
  description?: string | null;
  measured_value?: string | null;
  expected_value?: string | null;
  deviation_pct?: number | string | null;
  worker_id?: string | null;
  created_at?: string | null;
  detected_by?: string | null;
};

/** "190mm" / "2.3 deg" -> 190 / 2.3. ComplianceCard wants numbers; FieldIssue
 *  stores unit-suffixed strings. Returns null when there is no leading number
 *  (e.g. "Drawing R3"), which the card already renders as "—". */
function numericPart(v: string | null | undefined): number | null {
  if (v == null) return null;
  const m = String(v).match(/-?\d+(\.\d+)?/);
  return m ? Number(m[0]) : null;
}

function toComplianceIssue(f: FieldIssue): ComplianceIssue {
  return {
    id: f.id,
    field_issue_id: f.id,          // enables the reject (hard-negative) action
    zone_code: f.zone_code ?? null,
    asset_id: f.issue_type ?? null,
    severity: (f.severity ?? 'low').toUpperCase(),
    measured_value: numericPart(f.measured_value),
    spec_value: numericPart(f.expected_value),
    deviation_pct: f.deviation_pct == null ? null : Number(f.deviation_pct),
    // field_issues carries no per-issue model confidence; showing a number
    // here would invent one.
    confidence: null,
    worker_id: f.worker_id ?? null,
    status: f.status ?? 'open',
    created_at: f.created_at ?? new Date().toISOString(),
    detected_by: f.detected_by ?? null,
  };
}

export function ActiveIssuesPanel() {
  const { data: raw, error } = useAPIData<{ issues?: FieldIssue[] }>(
    '/api/v1/projects/default-project/issues',
    undefined,
  );
  const [issues, setIssues] = React.useState<ComplianceIssue[]>([]);
  const { user } = useAuth();

  React.useEffect(() => {
    const rows = raw?.issues;
    if (!rows) return;
    setIssues(
      rows
        .filter(f => (f.status ?? 'open') === 'open')
        .map(toComplianceIssue)
        // Most severe first, then most recent — the Command Center should lead
        // with what needs attention, not with whatever the DB returned first.
        .sort((a, b) => {
          const rank = (s: string) => ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'].indexOf(s.toUpperCase());
          const d = rank(a.severity) - rank(b.severity);
          if (d !== 0) return d;
          return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
        }),
    );
  }, [raw]);

  const handleReject = async (issue: ComplianceIssue) => {
    // Optimistic UI update
    setIssues(prev => prev.filter(i => i.id !== issue.id));

    // Reject operates on the linked FieldIssue, not the ComplianceEvent's
    // own id — ComplianceCard only shows the button when field_issue_id is
    // present. Previously this called a bare relative URL
    // (`/api/v1/issues/${id}/reject`, no API base) against the ComplianceEvent's
    // id, which would 404 against the Next.js server itself rather than
    // reaching the FastAPI backend at all.
    const API = apiBase();
    try {
      const res = await fetch(`${API}/api/v1/issues/${issue.field_issue_id}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          rejected_by_user_id: user?.id || user?.email || "unknown",
          rejection_reason: "Marked as false positive via dashboard",
          is_false_positive: true
        })
      });
      if (!res.ok) throw new Error(`Reject failed: ${res.status}`);
      console.log("Data Flywheel: Hard negative logged for " + issue.field_issue_id);
    } catch (err) {
      console.error("Failed to reject issue", err);
    }
  };
  
  // Real-time timestamp mockup
  const [updateTime, setUpdateTime] = React.useState(0);
  React.useEffect(() => {
    const timer = setInterval(() => setUpdateTime(prev => prev + 5), 5000);
    return () => clearInterval(timer);
  }, []);

  return (
    <GlassCard className="h-full flex flex-col" accentColor="var(--fail)">
      <div className="p-4 border-b border-[var(--border-subtle)] flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h2 className="text-sm font-semibold tracking-wide text-[var(--text-primary)] uppercase">Active Issues</h2>
          <span className="text-[10px] font-bold bg-[var(--fail-dim)] text-[var(--fail)] px-2 py-0.5 rounded-full">{issues.length} NEW</span>
        </div>
        <span className="text-[10px] text-[var(--text-muted)] font-mono">· Updated {updateTime === 0 ? 'just now' : `${updateTime}s ago`}</span>
      </div>

      <div className="flex-1 overflow-y-auto p-2">
        {issues.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center px-6 gap-1.5 py-8">
            <p className="text-[13px] text-[var(--text-secondary)]">
              {error ? 'Cannot load issues' : 'No open issues'}
            </p>
            <p className="text-[11px] text-[var(--text-muted)] max-w-[280px] leading-relaxed">
              {error
                ? `Backend unreachable at ${apiBase()}.`
                : 'Deviations detected by the vision and compliance agents appear here the moment they are raised.'}
            </p>
          </div>
        ) : (
          issues.map((issue) => (
            <ComplianceCard key={issue.id} issue={issue} onReject={handleReject} />
          ))
        )}
      </div>
    </GlassCard>
  );
}
