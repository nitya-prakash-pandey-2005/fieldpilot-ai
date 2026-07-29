"use client";

import React from 'react';
import { GlassCard } from '../ui/GlassCard';
import { useAPIData } from '@/hooks/useAPIData';
import { ComplianceCard, ComplianceIssue } from '../ui/ComplianceCard';
import { useAuth } from '@/context/AuthContext';

// Shape matches the real GET /api/v1/compliance/issues response (see
// ComplianceCard.tsx) — previously this demo data (and the live-fetch
// code path) used a different shape (description/timestamp/zone/worker/
// measured/spec/deviation) the backend never actually served, which only
// stayed invisible because the endpoint had no real rows before Agent 5's
// FAIL path was wired to persist ComplianceEvent (see agents/compliance/
// validator.py).
const DEMO_ISSUES: ComplianceIssue[] = [
  { id: "OBS-049", zone_code: "A12", asset_id: "rebar_grid_C4", severity: "CRITICAL", measured_value: 190, spec_value: 150, deviation_pct: 26.7, confidence: 0.93, worker_id: "Ali Hassan", status: "open", created_at: new Date(Date.now() - 2 * 60 * 1000).toISOString() },
  { id: "OBS-048", zone_code: "D4", asset_id: "generator_bay", severity: "MEDIUM", measured_value: null, spec_value: null, deviation_pct: null, confidence: null, worker_id: "Sarah Chen", status: "open", created_at: new Date(Date.now() - 12 * 60 * 1000).toISOString() },
  { id: "OBS-047", zone_code: "A12", asset_id: "harness_check", severity: "HIGH", measured_value: null, spec_value: null, deviation_pct: null, confidence: null, worker_id: "Mark Davis", status: "open", created_at: new Date(Date.now() - 45 * 60 * 1000).toISOString() },
  { id: "OBS-046", zone_code: "B3", asset_id: "egress_route", severity: "MEDIUM", measured_value: null, spec_value: null, deviation_pct: null, confidence: null, worker_id: "Tom Wilson", status: "open", created_at: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString() },
];

export function ActiveIssuesPanel() {
  const { data: initialIssues } = useAPIData('/api/v1/compliance/issues', DEMO_ISSUES);
  const [issues, setIssues] = React.useState<ComplianceIssue[]>([]);
  const { user } = useAuth();

  React.useEffect(() => {
    if (initialIssues) {
      setIssues(initialIssues);
    }
  }, [initialIssues]);

  const handleReject = async (issue: ComplianceIssue) => {
    // Optimistic UI update
    setIssues(prev => prev.filter(i => i.id !== issue.id));

    // Reject operates on the linked FieldIssue, not the ComplianceEvent's
    // own id — ComplianceCard only shows the button when field_issue_id is
    // present. Previously this called a bare relative URL
    // (`/api/v1/issues/${id}/reject`, no API base) against the ComplianceEvent's
    // id, which would 404 against the Next.js server itself rather than
    // reaching the FastAPI backend at all.
    const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
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
        {issues.map((issue) => (
          <ComplianceCard key={issue.id} issue={issue} onReject={handleReject} />
        ))}
      </div>
    </GlassCard>
  );
}
