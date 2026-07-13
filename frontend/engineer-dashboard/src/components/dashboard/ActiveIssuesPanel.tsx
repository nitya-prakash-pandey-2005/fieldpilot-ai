"use client";

import React from 'react';
import { GlassCard } from '../ui/GlassCard';
import { useAPIData } from '@/hooks/useAPIData';
import { StatusBadge } from '../ui/StatusBadge';

const DEMO_ISSUES = [
  { id: "OBS-049", severity: "critical", description: "Unsecured rebar caps on Column C4", zone: "Zone A12", timestamp: "Just now", measured: "190", spec: "150", deviation: "+40", worker: "Ali Hassan" },
  { id: "OBS-048", severity: "warning", description: "Water pooling near generator", zone: "Zone D4", timestamp: "12 mins ago", worker: "Sarah Chen" },
  { id: "OBS-047", severity: "high", description: "Missing fall protection harness", zone: "Zone A12", timestamp: "45 mins ago", worker: "Mark Davis" },
  { id: "OBS-046", severity: "medium", description: "Material blocking egress route", zone: "Zone B3", timestamp: "2 hours ago", worker: "Tom Wilson" },
];

export function ActiveIssuesPanel() {
  const { data: issues } = useAPIData('/api/v1/compliance/issues', DEMO_ISSUES);
  
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
        {issues.map((issue: any) => {
          const isCritical = issue.id === "OBS-049";
          return (
          <div key={issue.id} className={`p-3 border-b border-[var(--border-subtle)] last:border-0 hover:bg-[var(--bg-hover)] transition-colors cursor-pointer rounded-lg mb-1 relative
            ${isCritical ? 'border-l-[3px] shadow-sm' : ''}
          `}
          style={{ animation: isCritical ? 'criticalPulse 1.5s ease-in-out infinite' : 'none', borderLeftColor: isCritical ? 'var(--fail)' : 'transparent' }}
          >
            <div className="flex items-start justify-between mb-2">
              <div className="flex items-center gap-2">
                <StatusBadge status={issue.severity.toUpperCase()} />
                <span className="text-xs font-mono font-semibold text-[var(--text-primary)]">{issue.id}</span>
              </div>
              <span className="text-[10px] text-[var(--text-muted)] font-mono">{issue.timestamp}</span>
            </div>
            
            <p className="text-sm text-[var(--text-secondary)] mb-2">{issue.description}</p>
            
            {issue.measured && (
              <div className="mb-2">
                <span className="inline-flex items-center text-[10px] bg-black/40 border border-white/10 px-2 py-1 rounded font-mono text-[var(--text-secondary)]">
                  {issue.measured}mm / spec {issue.spec}mm 
                  <span className="text-[var(--fail)] font-bold ml-2">({issue.deviation}mm)</span>
                </span>
              </div>
            )}
            
            <div className="flex items-center justify-between mt-3">
              <div className="flex flex-col gap-1 text-[10px]">
                <div className="flex items-center gap-1.5 text-[var(--text-muted)]">
                  <span className="text-[var(--cyan)]">📍</span> {issue.zone}
                </div>
                <div className="flex items-center gap-1.5 text-[var(--text-muted)] opacity-70">
                  <span>👷</span> {issue.worker}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button className="text-[10px] font-bold text-[var(--amber)] tracking-wider hover:bg-[var(--amber-dim)] border border-transparent hover:border-[var(--amber)]/30 transition-all uppercase px-2 py-1 rounded">
                  Escalate
                </button>
                <button className="text-[10px] font-bold text-[var(--cyan)] tracking-wider hover:bg-[var(--cyan-dim)] border border-[var(--cyan)]/30 hover:border-[var(--cyan)] transition-all uppercase px-2 py-1 rounded">
                  Resolve ↗
                </button>
              </div>
            </div>
          </div>
        )})}
      </div>
    </GlassCard>
  );
}
