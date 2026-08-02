"use client";

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { GlassCard } from '@/components/ui/GlassCard';
import { SEVERITY } from '@/theme/severityColors';
import { apiBase } from '@/lib/api';
import {
  AlertTriangle, ArrowLeft, Clock, HardHat, Mic, Ruler, ScanLine, Activity,
} from 'lucide-react';

/**
 * Worker detail.
 *
 * The Issues table has always linked each worker ID to /workers/<id>, but this
 * route did not exist — every one of those links 404'd. Built rather than
 * removed, because "who is this worker and what has the system seen them do"
 * is exactly the question an engineer asks after reading an issue.
 *
 * There is no worker directory in the backend to read a profile from, so
 * nothing here is invented: identity is limited to the ID the issue carries,
 * and everything else is derived from two real endpoints —
 *   GET /api/v1/projects/{id}/issues      (filtered to this worker)
 *   GET /api/v1/interactions?worker_id=…  (their audit trail)
 * If a worker has no recorded activity the page says so instead of filling in
 * plausible-looking history.
 */

type Issue = {
  id: string;
  zone_code?: string | null;
  issue_type?: string | null;
  severity?: string | null;
  status?: string | null;
  description?: string | null;
  measured_value?: string | null;
  expected_value?: string | null;
  deviation_pct?: number | null;
  worker_id?: string | null;
  created_at?: string | null;
};

type Interaction = {
  id: string;
  kind: string;
  query: string | null;
  result: string | null;
  verdict: string | null;
  severity: string | null;
  confidence: number | null;
  zone_code: string | null;
  agent_chain: string | null;
  latency_ms: number | null;
  created_at: string | null;
};

// Typed with the props actually passed below. React.ElementType is too loose —
// TS narrows its props to `never`, so `size`/`className` fail to type-check.
type IconComponent = React.ComponentType<{ size?: number; className?: string }>;

const KIND_ICON: Record<string, IconComponent> = {
  scan: ScanLine,
  voice: Mic,
  measurement: Ruler,
  drawing_check: HardHat,
  compliance: AlertTriangle,
};

function sev(s?: string | null) {
  const key = (s ?? 'low').toLowerCase() as keyof typeof SEVERITY;
  return SEVERITY[key] ?? SEVERITY.low;
}

function relativeTime(iso?: string | null): string {
  if (!iso) return '—';
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return '—';
  const mins = Math.floor((Date.now() - t) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const h = Math.floor(mins / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return d === 1 ? 'yesterday' : `${d}d ago`;
}

function StatTile({ label, value, hint, accent }: {
  label: string; value: string | number; hint?: string; accent?: string;
}) {
  return (
    <GlassCard className="p-4" accentColor={accent}>
      <p className="text-[10px] uppercase tracking-wider text-[var(--text-muted)] mb-1">{label}</p>
      <p className="text-2xl font-semibold text-[var(--text-primary)] tabular-nums leading-tight">{value}</p>
      {hint && <p className="text-[10px] text-[var(--text-muted)] mt-1">{hint}</p>}
    </GlassCard>
  );
}

export default function WorkerDetailPage() {
  const params = useParams<{ workerId: string }>();
  const router = useRouter();
  const workerId = decodeURIComponent(String(params?.workerId ?? ''));

  const [issues, setIssues] = useState<Issue[]>([]);
  const [interactions, setInteractions] = useState<Interaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const API = apiBase();
    try {
      const [issuesRes, interRes] = await Promise.all([
        fetch(`${API}/api/v1/projects/default-project/issues`),
        fetch(`${API}/api/v1/interactions?worker_id=${encodeURIComponent(workerId)}&limit=100`),
      ]);
      if (!issuesRes.ok) throw new Error(`issues HTTP ${issuesRes.status}`);

      const issuesJson = await issuesRes.json();
      const all: Issue[] = issuesJson?.issues ?? [];
      setIssues(all.filter(i => i.worker_id === workerId));

      // The interactions feed degrades rather than erroring, so an unavailable
      // store must not blank the issues half of this page.
      if (interRes.ok) {
        const interJson = await interRes.json();
        setInteractions(interJson?.data ?? []);
      } else {
        setInteractions([]);
      }
      setError(null);
    } catch (e: any) {
      setError(`Couldn't load worker data from ${API} — ${e?.message ?? 'unknown error'}`);
    } finally {
      setLoading(false);
    }
  }, [workerId]);

  useEffect(() => {
    load();
    const t = setInterval(load, 20_000);
    return () => clearInterval(t);
  }, [load]);

  const stats = useMemo(() => {
    const open = issues.filter(i => (i.status ?? 'open') === 'open');
    const critical = open.filter(i => ['critical', 'high'].includes((i.severity ?? '').toLowerCase()));
    const zones = Array.from(new Set(
      [...issues.map(i => i.zone_code), ...interactions.map(i => i.zone_code)].filter(Boolean)
    )) as string[];
    const times = [...issues.map(i => i.created_at), ...interactions.map(i => i.created_at)]
      .filter(Boolean)
      .map(t => new Date(t as string).getTime())
      .filter(n => !Number.isNaN(n));
    return {
      open: open.length,
      critical: critical.length,
      interactions: interactions.length,
      zones,
      lastSeen: times.length ? new Date(Math.max(...times)).toISOString() : null,
    };
  }, [issues, interactions]);

  const hasNothing = !loading && issues.length === 0 && interactions.length === 0 && !error;

  return (
    <div className="p-6 md:p-8 space-y-6 max-w-[1400px] mx-auto">
      <div className="flex items-center gap-3">
        <button
          onClick={() => router.back()}
          className="p-2 rounded-lg border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-colors"
          aria-label="Go back"
        >
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 flex-wrap">
            <h1 className="text-2xl font-semibold text-[var(--text-primary)]">{workerId || 'Unknown worker'}</h1>
            {stats.zones.map(z => (
              <span key={z} className="px-2 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider
                                       bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-[var(--text-secondary)]">
                Zone {z}
              </span>
            ))}
          </div>
          <p className="text-[11px] text-[var(--text-muted)] mt-1">
            Field worker · everything below is recorded activity, refreshed every 20s
          </p>
        </div>
      </div>

      {error && (
        <GlassCard className="p-4" accentColor={SEVERITY.critical.card_border}>
          <p className="text-[13px] text-[var(--text-primary)]">{error}</p>
        </GlassCard>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatTile label="Open issues" value={stats.open}
                  accent={stats.open ? SEVERITY.high.card_border : undefined} />
        <StatTile label="Critical / high" value={stats.critical}
                  accent={stats.critical ? SEVERITY.critical.card_border : undefined}
                  hint={stats.critical ? 'needs engineer action' : 'none outstanding'} />
        <StatTile label="AI interactions" value={stats.interactions}
                  hint="scans, questions, measurements" />
        <StatTile label="Last activity" value={relativeTime(stats.lastSeen)}
                  hint={stats.lastSeen ? new Date(stats.lastSeen).toLocaleString() : 'no record'} />
      </div>

      {hasNothing && (
        <GlassCard className="p-8 text-center">
          <p className="text-[15px] text-[var(--text-secondary)] mb-1">
            No recorded activity for {workerId}
          </p>
          <p className="text-[12px] text-[var(--text-muted)] max-w-[460px] mx-auto leading-relaxed">
            This worker has no issues raised against them and no AI interactions logged.
            There is no separate worker directory in the system, so this page shows only
            what has actually been observed — nothing is filled in for presentation.
          </p>
        </GlassCard>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <GlassCard className="p-6">
          <div className="flex items-center gap-2 mb-4">
            <AlertTriangle size={14} className="text-[var(--text-secondary)]" />
            <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--text-primary)]">
              Issues raised
            </h2>
            <span className="text-[11px] text-[var(--text-muted)]">({issues.length})</span>
          </div>

          {loading ? (
            <p className="text-[12px] text-[var(--text-muted)]">Loading…</p>
          ) : issues.length === 0 ? (
            <p className="text-[12px] text-[var(--text-muted)]">No issues attributed to this worker.</p>
          ) : (
            <div className="space-y-3 max-h-[520px] overflow-y-auto pr-1">
              {issues.map(issue => {
                const s = sev(issue.severity);
                return (
                  <div key={issue.id}
                       className="p-3 rounded-lg border"
                       style={{ borderColor: s.card_border, background: s.card_tint }}>
                    <div className="flex items-center justify-between gap-2 mb-1.5">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider"
                              style={{ background: s.badge_bg, color: s.badge_text, border: `1px solid ${s.badge_border}` }}>
                          {issue.severity ?? 'low'}
                        </span>
                        <span className="text-[13px] font-medium text-[var(--text-primary)] truncate">
                          {issue.issue_type ?? 'Issue'}
                        </span>
                        {issue.zone_code && (
                          <span className="text-[10px] font-mono text-[var(--text-muted)]">
                            {issue.zone_code}
                          </span>
                        )}
                      </div>
                      <span className="text-[10px] text-[var(--text-muted)] shrink-0">
                        {relativeTime(issue.created_at)}
                      </span>
                    </div>
                    <p className="text-[12px] text-[var(--text-secondary)] leading-relaxed">
                      {issue.description}
                    </p>
                    {(issue.measured_value || issue.expected_value) && (
                      <div className="flex items-center gap-3 mt-2 text-[11px] font-mono">
                        {issue.measured_value && (
                          <span style={{ color: s.deviation }}>measured {issue.measured_value}</span>
                        )}
                        {issue.expected_value && (
                          <span className="text-[var(--text-muted)]">spec {issue.expected_value}</span>
                        )}
                        {issue.deviation_pct != null && (
                          <span style={{ color: s.deviation }}>{Number(issue.deviation_pct).toFixed(1)}% dev</span>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </GlassCard>

        <GlassCard className="p-6">
          <div className="flex items-center gap-2 mb-4">
            <Activity size={14} className="text-[var(--text-secondary)]" />
            <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--text-primary)]">
              AI interaction history
            </h2>
            <span className="text-[11px] text-[var(--text-muted)]">({interactions.length})</span>
          </div>

          {loading ? (
            <p className="text-[12px] text-[var(--text-muted)]">Loading…</p>
          ) : interactions.length === 0 ? (
            <p className="text-[12px] text-[var(--text-muted)]">
              Nothing logged yet. Scans, voice questions and measurements this worker
              makes appear here with the agent chain that handled them.
            </p>
          ) : (
            <div className="space-y-2.5 max-h-[520px] overflow-y-auto pr-1">
              {interactions.map(it => {
                const Icon = KIND_ICON[it.kind] ?? Activity;
                const v = (it.verdict ?? '').toUpperCase();
                const vColor = v === 'FAIL' ? SEVERITY.critical.badge_text
                  : v === 'PASS' ? SEVERITY.low.badge_text
                  : v === 'UNCERTAIN' ? SEVERITY.medium.badge_text
                  : 'var(--text-muted)';
                return (
                  <div key={it.id} className="flex gap-3 p-3 rounded-lg bg-[var(--bg-elevated)]/50 border border-[var(--border-subtle)]">
                    <Icon size={14} className="mt-0.5 shrink-0 text-[var(--text-muted)]" />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="text-[9px] uppercase tracking-wider text-[var(--text-muted)] font-mono">
                            {it.kind}
                          </span>
                          {v && (
                            <span className="text-[9px] font-bold tracking-wider" style={{ color: vColor }}>
                              {v}
                            </span>
                          )}
                        </div>
                        <span className="flex items-center gap-1 text-[10px] text-[var(--text-muted)] shrink-0">
                          <Clock size={10} />{relativeTime(it.created_at)}
                        </span>
                      </div>
                      <p className="text-[12.5px] text-[var(--text-primary)] mt-0.5 leading-snug">
                        {it.query ?? '—'}
                      </p>
                      {it.result && (
                        <p className="text-[11.5px] text-[var(--text-secondary)] mt-1 leading-relaxed">
                          {it.result}
                        </p>
                      )}
                      {(it.agent_chain || it.latency_ms != null || it.confidence != null) && (
                        <p className="text-[9.5px] font-mono text-[var(--text-muted)] mt-1.5">
                          {it.agent_chain}
                          {it.confidence != null && `  ·  conf ${(it.confidence * 100).toFixed(0)}%`}
                          {it.latency_ms != null && `  ·  ${Math.round(it.latency_ms)}ms`}
                        </p>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </GlassCard>
      </div>
    </div>
  );
}
