"use client";
import { useState, useMemo, useEffect, useCallback } from 'react';
import dynamic from 'next/dynamic';
import { ScanLine, Users, AlertTriangle, ShieldAlert } from 'lucide-react';
import { useZones, getRiskLevel } from '@/hooks/useZones';
import { LiveIndicator } from '@/components/ui/LiveIndicator';
import { StatusBadge } from '@/components/ui/StatusBadge';
import type { TwinIssue } from '@/components/ThreeSiteViewer';

// react-three-fiber's Canvas needs the browser (WebGL) — load client-side only.
const ThreeSiteViewer = dynamic(() => import('@/components/ThreeSiteViewer'), { ssr: false });

const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
const ISSUES_POLL_MS = 15_000;

// Same zone_code -> position lookup convention as LiveSiteMap.tsx, just in
// ThreeSiteViewer's pixel-space (800x600) instead of percentages — the
// Zone schema still has no real spatial/BIM coordinates (see
// system_prompt.md Section 7's IFC/BIM integration, not yet built). No real
// building geometry file (glTF/IFC) exists anywhere in this repo, so the
// scene below is a stylized construction-site representation driven by
// real zone/issue/worker-count data — not a literal scan of the real site.
const ZONE_LAYOUT: Record<string, { x: number; y: number; w: number; h: number }> = {
  A12: { x: 50, y: 50, w: 340, h: 340 },
  D4: { x: 460, y: 50, w: 300, h: 340 },
  C7: { x: 50, y: 430, w: 300, h: 300 },
  B3: { x: 400, y: 430, w: 360, h: 300 },
};
const DEFAULT_LAYOUT = { x: 350, y: 250, w: 220, h: 220 };

const RISK_TO_STATUS: Record<string, 'GREEN' | 'AMBER' | 'RED'> = {
  critical: 'RED',
  elevated: 'AMBER',
  normal: 'GREEN',
};

const SEVERITY_TEXT_COLOR: Record<string, string> = {
  critical: 'var(--fail)',
  high: 'var(--amber)',
  medium: 'var(--cyan)',
  low: 'var(--pass)',
};

export default function TwinPage() {
  const { zones, summary, connectionStatus } = useZones("default-project");
  const [selectedZoneId, setSelectedZoneId] = useState<string | null>(null);
  const [highlightIssueId, setHighlightIssueId] = useState<string | null>(null);
  const [issues, setIssues] = useState<TwinIssue[]>([]);
  const [issuesByZoneCode, setIssuesByZoneCode] = useState<Record<string, TwinIssue[]>>({});
  const [now, setNow] = useState<Date | null>(null);

  const loadIssues = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/v1/projects/default-project/issues`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const active = (data.issues || []).filter((i: any) => i.status !== 'resolved' && i.status !== 'dismissed');
      const grouped: Record<string, TwinIssue[]> = {};
      const flat: TwinIssue[] = [];
      for (const i of active) {
        const twinIssue: TwinIssue = {
          id: i.id,
          severity: i.severity,
          status: i.status,
          label: (i.issue_type || 'Issue').replace(/_/g, ' '),
          worker_id: i.worker_id,
        };
        flat.push(twinIssue);
        (grouped[i.zone_code] ||= []).push(twinIssue);
      }
      setIssues(flat);
      setIssuesByZoneCode(grouped);
    } catch {
      // Leave whatever was last successfully loaded — no fabricated fallback.
    }
  }, []);

  useEffect(() => {
    loadIssues();
    const interval = setInterval(loadIssues, ISSUES_POLL_MS);
    return () => clearInterval(interval);
  }, [loadIssues]);

  // Live HUD clock — client-only to avoid an SSR/client timestamp mismatch.
  useEffect(() => {
    setNow(new Date());
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const threeZones = useMemo(() => zones.map(z => {
    const layout = ZONE_LAYOUT[z.zone_code] || DEFAULT_LAYOUT;
    return {
      id: z.zone_code,
      name: z.name,
      status: RISK_TO_STATUS[getRiskLevel(z.risk_score)],
      workerCount: z.active_worker_count,
      issues: issuesByZoneCode[z.zone_code] || [],
      ...layout,
    };
  }), [zones, issuesByZoneCode]);

  const selectedZone = zones.find(z => z.zone_code === selectedZoneId) || null;
  const selectedZoneIssues = selectedZoneId ? (issuesByZoneCode[selectedZoneId] || []) : [];
  const highlightedIssue = issues.find(i => i.id === highlightIssueId) || null;

  const handleSelectIssue = (issue: TwinIssue) => {
    setHighlightIssueId(issue.id);
  };

  return (
    <div className="h-full p-8 flex flex-col">
      <div className="flex items-center gap-3 mb-6">
        <h1 className="text-3xl font-bold text-[var(--text-primary)]">Digital Twin</h1>
        <LiveIndicator isLive={connectionStatus === 'live'} />
      </div>
      <p className="text-[var(--text-secondary)] -mt-4 mb-4 text-sm">
        Live 3D site model — stylized construction-site rendering driven entirely by real zone risk, open issues, and worker headcounts (no BIM/architectural file is imported here). Click a zone or hazard beacon for details, drag to orbit.
      </p>

      <div className="flex-1 relative rounded-xl overflow-hidden border border-[var(--border-subtle)] min-h-[400px]">
        {zones.length === 0 ? (
          <div className="w-full h-full flex items-center justify-center text-[var(--text-muted)] bg-[var(--bg-surface)]">
            Loading site model…
          </div>
        ) : (
          <ThreeSiteViewer
            zones={threeZones}
            selectedZoneId={selectedZoneId}
            onSelectZone={(id) => { setSelectedZoneId(id); if (!id) setHighlightIssueId(null); }}
            onSelectIssue={handleSelectIssue}
          />
        )}

        {/* Jarvis-style HUD overlay — decorative frame over real live data */}
        <div className="absolute inset-4 pointer-events-none">
          <div className="absolute top-0 left-0 w-8 h-8 border-t-2 border-l-2 border-[var(--cyan)]/70" />
          <div className="absolute top-0 right-0 w-8 h-8 border-t-2 border-r-2 border-[var(--cyan)]/70" />
          <div className="absolute bottom-0 left-0 w-8 h-8 border-b-2 border-l-2 border-[var(--cyan)]/70" />
          <div className="absolute bottom-0 right-0 w-8 h-8 border-b-2 border-r-2 border-[var(--cyan)]/70" />
        </div>

        <div className="absolute top-4 left-4 flex items-center gap-2 text-[10px] font-mono uppercase tracking-widest text-[var(--cyan)]">
          <ScanLine size={12} className="animate-pulse" />
          Site Scan Active
          <span className="text-[var(--text-muted)] normal-case tracking-normal">{now ? now.toLocaleTimeString() : ''}</span>
        </div>

        {summary && (
          <div className="absolute top-4 right-4 flex flex-col items-end gap-1 text-[10px] font-mono uppercase tracking-widest">
            <span className="flex items-center gap-1.5 text-[var(--text-secondary)]">
              <Users size={11} /> {summary.total_workers} Active Workers
            </span>
            <span className="flex items-center gap-1.5 text-[var(--fail)]">
              <AlertTriangle size={11} /> {summary.total_open_issues} Open Issues
            </span>
            <span className="flex items-center gap-1.5 text-[var(--amber)]">
              <ShieldAlert size={11} /> {summary.critical_count} Critical Zones
            </span>
          </div>
        )}

        {/* Zone detail overlay */}
        {selectedZone && (
          <div className="absolute bottom-4 right-4 w-80 max-h-[70%] flex flex-col bg-[var(--bg-surface)]/95 backdrop-blur-md border border-[var(--border-subtle)] rounded-xl p-4 z-10 shadow-2xl">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-lg font-bold text-[var(--text-primary)] font-mono">Zone {selectedZone.zone_code}</h3>
              <StatusBadge status={getRiskLevel(selectedZone.risk_score).toUpperCase()} />
            </div>
            <p className="text-xs text-[var(--text-secondary)] mb-3">{selectedZone.current_activity}</p>
            <div className="grid grid-cols-3 gap-2 text-center mb-3">
              <div className="bg-[var(--bg-elevated)] rounded-lg p-2">
                <div className="text-lg font-bold text-[var(--text-primary)]">{selectedZone.risk_score}</div>
                <div className="text-[9px] text-[var(--text-muted)] uppercase tracking-wide">Risk</div>
              </div>
              <div className="bg-[var(--bg-elevated)] rounded-lg p-2">
                <div className="text-lg font-bold text-[var(--text-primary)]">{selectedZone.active_worker_count}</div>
                <div className="text-[9px] text-[var(--text-muted)] uppercase tracking-wide">Workers</div>
              </div>
              <div className="bg-[var(--bg-elevated)] rounded-lg p-2">
                <div className="text-lg font-bold text-[var(--text-primary)]">{selectedZoneIssues.length}</div>
                <div className="text-[9px] text-[var(--text-muted)] uppercase tracking-wide">Issues</div>
              </div>
            </div>

            {selectedZoneIssues.length > 0 && (
              <div className="flex-1 overflow-y-auto flex flex-col gap-1.5 border-t border-[var(--border-subtle)] pt-2">
                {selectedZoneIssues.map(issue => (
                  <div
                    key={issue.id}
                    className="text-xs px-2.5 py-1.5 rounded-lg border flex items-center justify-between gap-2"
                    style={{
                      backgroundColor: issue.id === highlightIssueId ? `${SEVERITY_TEXT_COLOR[issue.severity]}22` : 'var(--bg-elevated)',
                      borderColor: issue.id === highlightIssueId ? SEVERITY_TEXT_COLOR[issue.severity] : 'var(--border-subtle)',
                    }}
                  >
                    <span className="text-[var(--text-secondary)] capitalize truncate">{issue.label}</span>
                    <span className="font-bold uppercase text-[10px] shrink-0" style={{ color: SEVERITY_TEXT_COLOR[issue.severity] }}>
                      {issue.severity}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
