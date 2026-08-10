"use client";

import React from 'react';
import { KPIBar } from '@/components/dashboard/KPIBar';
import { LiveSiteMap } from '@/components/dashboard/LiveSiteMap';
import { ActiveIssuesPanel } from '@/components/dashboard/ActiveIssuesPanel';
import { PredictedRFIPanel } from '@/components/dashboard/PredictedRFIPanel';
import { useAPIData } from '@/hooks/useAPIData';

/**
 * Last-observation banner, driven by the real interaction log.
 *
 * This used to be two hardcoded strings that alternated every ten seconds —
 * "Rebar spacing deviation detected · +30mm above spec · Worker: Ali Hassan ·
 * WhatsApp dispatched to Engineer Chen · 2 minutes ago", and an "All zones
 * nominal" line. Neither corresponded to anything that had happened. It sat at
 * the top of the command centre looking exactly like a live event feed, naming
 * people who do not exist and an alert that was never sent.
 *
 * It now reads the newest row from /api/v1/interactions, which every agent run
 * writes to (Agent 9 records one per orchestrated frame). With no activity yet
 * it says so, which is a true statement about a site nobody has scanned.
 */
function LastObservationBanner() {
  // useAPIData unwraps `{ data: ... }`, and this endpoint returns
  // `{ status, count, data: [...] }` — so what arrives here is the array itself.
  const { data, error } = useAPIData<any[]>('/api/v1/interactions?limit=5');
  const rows = Array.isArray(data) ? data : [];
  const latest = rows[0];

  const verdictColor = (v?: string) =>
    v === 'FAIL' ? 'var(--fail)' : v === 'UNCERTAIN' ? 'var(--amber)'
    : v === 'PASS' ? 'var(--pass)' : 'var(--text-muted)';

  const ago = (ts?: string) => {
    if (!ts) return '';
    const secs = Math.max(0, (Date.now() - new Date(ts).getTime()) / 1000);
    if (secs < 60) return `${Math.round(secs)}s ago`;
    if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
    if (secs < 86400) return `${Math.round(secs / 3600)}h ago`;
    return `${Math.round(secs / 86400)}d ago`;
  };

  return (
    <div className="w-full min-h-[40px] bg-[var(--bg-surface)]/80 backdrop-blur-md border border-[var(--border-accent)] rounded-lg flex items-center px-4 shadow-lg overflow-hidden relative">
      <div className="absolute left-0 top-0 bottom-0 w-1 bg-[var(--cyan)] shadow-[0_0_8px_var(--cyan)] animate-pulse motion-reduce:animate-none" />

      {error ? (
        <p className="text-[11px] font-mono text-[var(--amber)] w-full truncate">
          Activity feed unavailable — {error}
        </p>
      ) : !latest ? (
        <p className="text-[11px] font-mono text-[var(--text-muted)] w-full truncate flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-[var(--text-muted)]" />
          No agent activity recorded yet. Run a scan from Agent Flow or Glasses Mode.
        </p>
      ) : (
        <p className="text-[11px] font-mono text-[var(--text-primary)] w-full truncate flex items-center gap-2">
          <span className="text-[14px]">🥽</span>
          <span className="font-bold text-[var(--cyan)] tracking-wider">
            ZONE {latest.zone_code || '—'}
          </span>
          <span className="text-[var(--text-muted)] mx-1">·</span>
          {latest.kind?.replace(/_/g, ' ') || 'observation'}
          {latest.verdict && (
            <>
              <span className="text-[var(--text-muted)] mx-1">·</span>
              <span className="font-bold" style={{ color: verdictColor(latest.verdict) }}>
                {latest.verdict}
              </span>
            </>
          )}
          {latest.worker_id && (
            <>
              <span className="text-[var(--text-muted)] mx-1">·</span>
              Worker: {latest.worker_id}
            </>
          )}
          {latest.agent_chain && (
            <>
              <span className="text-[var(--text-muted)] mx-1">·</span>
              <span className="text-[var(--text-secondary)]">{latest.agent_chain}</span>
            </>
          )}
          <span className="text-[var(--text-muted)] mx-1">·</span>
          <span className="text-[var(--text-muted)]">{ago(latest.created_at)}</span>
        </p>
      )}
    </div>
  );
}

export default function Home() {

  return (
    <div className="flex flex-col h-full gap-4 relative animate-fade-in">
      <KPIBar />
      
      {/* LAST AI OBSERVATION — real, from the interaction log */}
      <LastObservationBanner />

      <div className="grid grid-cols-1 lg:grid-cols-3 xl:grid-cols-4 gap-4 flex-1 min-h-[500px]">
        {/* Main Map Area */}
        <div className="lg:col-span-2 xl:col-span-2 flex flex-col xl:border-r border-[var(--border-subtle)] xl:pr-4">
          <LiveSiteMap />
        </div>
        
        {/* Right Sidebar Columns */}
        <div className="flex flex-col gap-4 xl:col-span-1 xl:border-r border-[var(--border-subtle)] xl:pr-4">
          <div className="flex-1 min-h-[250px]">
            <ActiveIssuesPanel />
          </div>
        </div>
        
        <div className="flex flex-col gap-4 xl:col-span-1">
          <div className="flex-1 min-h-[250px]">
            <PredictedRFIPanel />
          </div>
        </div>
      </div>
    </div>
  );
}
