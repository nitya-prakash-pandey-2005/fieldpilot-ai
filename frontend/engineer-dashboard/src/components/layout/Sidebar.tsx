"use client";

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useZones, getRiskLevel } from '@/hooks/useZones';

export function Sidebar() {
  const pathname = usePathname();
  const [healthData, setHealthData] = useState<any[]>([]);
  const { zones } = useZones("default-project");
  const [activeIssuesCount, setActiveIssuesCount] = useState<number | null>(null);

  const atRiskCount = zones.filter(z => getRiskLevel(z.risk_score) !== 'normal').length;

  useEffect(() => {
    // Initial fetch of issues summary for the badge
    fetch('/api/v1/projects/default-project/issues')
      .then(res => res.json())
      .then(data => setActiveIssuesCount(data.summary.open))
      .catch(() => setActiveIssuesCount(null));

    // Listen to updates from the issues page/hooks
    const handleIssuesUpdate = (e: any) => {
      if (e.detail !== undefined) setActiveIssuesCount(e.detail);
    };
    import('@/hooks/useFieldIssues').then(({ issuesEventTarget }) => {
      issuesEventTarget.addEventListener('issues-updated', handleIssuesUpdate as EventListener);
    });

    return () => {
      import('@/hooks/useFieldIssues').then(({ issuesEventTarget }) => {
        issuesEventTarget.removeEventListener('issues-updated', handleIssuesUpdate as EventListener);
      });
    };
  }, []);

  const navItems = [
    { icon: "🏗", label: "Command Center", href: "/", badge: null },
    { icon: "📈", label: "Executive Summary", href: "/executive", badge: null },
    { icon: "🥽", label: "Glasses Feed", href: "/glasses", badge: "LIVE" },
    { icon: "🗺", label: "Site Zones", href: "/zones", badge: atRiskCount },
    { icon: "⚠️", label: "Active Issues", href: "/issues", badge: activeIssuesCount },
    { icon: "🔮", label: "RFI Predictions", href: "/rfis", badge: "AI" },
    { icon: "📐", label: "Drawings", href: "/drawings", badge: null },
    { icon: "💬", label: "Project Memory", href: "/memory", badge: null },
    { icon: "🔔", label: "Notifications", href: "/notifications", badge: null },
    { icon: "🕸", label: "Knowledge Graph", href: "/graph", badge: null },
  ];

  const agentIds = Array.from({length: 10}, (_, i) => i + 1);

  useEffect(() => {
    // In a real app, fetch from GET /api/v1/health/agents
    // Fallback for now to all operational
    setHealthData(agentIds.map(id => ({ id, status: 'operational' })));
  }, []);

  return (
    <aside className="w-[220px] h-full flex flex-col bg-[var(--bg-elevated)] border-r border-[var(--border-subtle)] shrink-0 transition-all duration-300 relative overflow-hidden">
      {/* Subtle blueprint grid bg for sidebar */}
      <div className="absolute inset-0 blueprint-grid opacity-50 pointer-events-none" />
      
      <div className="flex-1 py-6 px-3 flex flex-col gap-1 overflow-y-auto relative z-10">
        <div className="mb-4 px-3 text-xs font-semibold text-[var(--text-muted)] tracking-widest uppercase">
          Menu
        </div>
        
        {navItems.map((item) => {
          const isActive = pathname === item.href || (item.href !== '/' && pathname?.startsWith(item.href));
          return (
            <Link 
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all duration-200 border-l-2
                ${isActive 
                  ? 'bg-[var(--cyan-dim)] border-[var(--cyan)] text-[var(--cyan)]' 
                  : 'border-transparent text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]'
                }`}
            >
              <span className="text-lg">{item.icon}</span>
              <span className="text-sm font-medium flex-1">{item.label}</span>
              
              {item.badge && (
                <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                  typeof item.badge === 'number' 
                    ? 'bg-[var(--fail-dim)] text-[var(--fail)] border border-[var(--fail)]/30' 
                    : 'bg-[var(--cyan-dim)] text-[var(--cyan)] border border-[var(--cyan)]/30'
                }`}>
                  {item.badge}
                </span>
              )}
            </Link>
          );
        })}
      </div>

      {/* AGENT HEALTH MINI GRID */}
      <div className="p-4 border-t border-[var(--border-subtle)] bg-[var(--bg-surface)] relative z-10">
        <div className="text-[10px] font-bold text-[var(--pass)] tracking-widest uppercase mb-3 flex items-center justify-between">
          <span>10/10 OPERATIONAL</span>
          <span className="w-1.5 h-1.5 rounded-full bg-[var(--pass)] shadow-[0_0_8px_var(--pass)] animate-pulse"></span>
        </div>
        
        <div className="grid grid-cols-5 gap-2 mb-2">
          {healthData.map((agent, index) => {
            const labels = ["V1", "M2", "D3", "G4", "C5", "R6", "P7", "VC8", "N9", "L10"];
            const label = labels[index] || `A${index+1}`;
            const isOp = agent.status === 'operational';
            return (
            <div 
              key={agent.id}
              title={`Agent ${label}: ${agent.status.toUpperCase()}`}
              className="flex items-center gap-1 cursor-help opacity-80 hover:opacity-100 transition-opacity"
            >
              <div className={`w-2 h-2 rounded-full ${isOp ? 'bg-[var(--pass)] shadow-[0_0_5px_var(--pass-dim)]' : 'bg-[var(--fail)]'}`} />
              <span className="text-[9px] font-mono text-[var(--text-secondary)]">{label}</span>
            </div>
            );
          })}
        </div>
      </div>
    </aside>
  );
}
