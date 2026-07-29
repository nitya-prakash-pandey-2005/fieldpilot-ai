"use client";

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useZones, getRiskLevel } from '@/hooks/useZones';
import { useAuth, ROLE_LABELS, Role } from '@/context/AuthContext';

const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuth();
  const [healthData, setHealthData] = useState<{ id: string; status: string }[]>([]);
  const { zones } = useZones("default-project");
  const [activeIssuesCount, setActiveIssuesCount] = useState<number | null>(null);

  const atRiskCount = zones.filter(z => getRiskLevel(z.risk_score) !== 'normal').length;

  useEffect(() => {
    // Initial fetch of issues summary for the badge
    fetch(`${API}/api/v1/projects/default-project/issues`)
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

  // roles: who this nav item is relevant to. Backend routes enforce the
  // real security boundary (see api/auth.py's require_role) — this is
  // just keeping each role's sidebar focused on their actual job.
  const navItems: { icon: string; label: string; href: string; badge: string | number | null; roles: Role[] }[] = [
    { icon: "🏗", label: "Command Center", href: "/", badge: null, roles: ["worker", "engineer", "pm", "admin", "executive"] },
    { icon: "📈", label: "Executive Summary", href: "/executive", badge: null, roles: ["pm", "admin", "executive"] },
    { icon: "🥽", label: "Glasses Feed", href: "/glasses", badge: "LIVE", roles: ["worker", "engineer", "pm", "admin"] },
    { icon: "🗺", label: "Site Zones", href: "/zones", badge: atRiskCount, roles: ["engineer", "pm", "admin", "executive"] },
    { icon: "⚠️", label: "Active Issues", href: "/issues", badge: activeIssuesCount, roles: ["engineer", "pm", "admin", "executive"] },
    { icon: "🔮", label: "RFI Predictions", href: "/rfis", badge: "AI", roles: ["engineer", "pm", "admin", "executive"] },
    { icon: "📐", label: "Drawings", href: "/drawings", badge: null, roles: ["engineer", "admin"] },
    { icon: "💬", label: "Project Memory", href: "/memory", badge: null, roles: ["worker", "engineer", "pm", "admin", "executive"] },
    { icon: "🔔", label: "Notifications", href: "/notifications", badge: null, roles: ["engineer", "pm", "admin", "executive"] },
    { icon: "🕸", label: "Knowledge Graph", href: "/graph", badge: null, roles: ["engineer", "admin"] },
    { icon: "🏛", label: "Digital Twin", href: "/twin", badge: null, roles: ["pm", "admin", "executive"] },
  ];

  const visibleNavItems = user ? navItems.filter(item => item.roles.includes(user.role)) : navItems;

  useEffect(() => {
    fetch(`${API}/api/v1/health/agents`)
      .then(res => res.ok ? res.json() : Promise.reject())
      .then(data => {
        const agents = data.agents || {};
        setHealthData(Object.entries(agents).map(([id, status]) => ({ id, status: status as string })));
      })
      .catch(() => {
        // Backend unreachable — show unknown rather than falsely "operational"
        setHealthData([]);
      });
  }, []);

  const operationalCount = healthData.filter(a => a.status === 'operational').length;

  return (
    <aside className="w-[220px] h-full flex flex-col bg-[var(--bg-elevated)] border-r border-[var(--border-subtle)] shrink-0 transition-all duration-300 relative overflow-hidden">
      {/* Subtle blueprint grid bg for sidebar */}
      <div className="absolute inset-0 blueprint-grid opacity-50 pointer-events-none" />

      {/* User badge */}
      {user && (
        <div className="p-3 border-b border-[var(--border-subtle)] relative z-10">
          <div className="flex items-center gap-2.5 px-2 py-2 rounded-lg bg-[var(--bg-surface)] border border-[var(--border-subtle)]">
            <div className="w-8 h-8 rounded-full bg-[var(--cyan-dim)] border border-[var(--cyan)]/30 flex items-center justify-center text-[var(--cyan)] font-bold text-sm shrink-0">
              {user.name.charAt(0)}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs font-semibold text-[var(--text-primary)] truncate">{user.name}</p>
              <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide truncate">{ROLE_LABELS[user.role]}</p>
            </div>
            <button
              onClick={() => { logout(); router.push('/login'); }}
              title="Log out"
              className="text-[var(--text-muted)] hover:text-[var(--fail)] transition-colors text-sm shrink-0"
            >
              ⏻
            </button>
          </div>
        </div>
      )}

      <div className="flex-1 py-6 px-3 flex flex-col gap-1 overflow-y-auto relative z-10">
        <div className="mb-4 px-3 text-xs font-semibold text-[var(--text-muted)] tracking-widest uppercase">
          Menu
        </div>

        {visibleNavItems.map((item) => {
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

      {/* AGENT HEALTH MINI GRID — real status from GET /api/v1/health/agents */}
      <div className="p-4 border-t border-[var(--border-subtle)] bg-[var(--bg-surface)] relative z-10">
        <div className="text-[10px] font-bold text-[var(--pass)] tracking-widest uppercase mb-3 flex items-center justify-between">
          <span>{healthData.length > 0 ? `${operationalCount}/${healthData.length} OPERATIONAL` : 'CHECKING…'}</span>
          <span className={`w-1.5 h-1.5 rounded-full animate-pulse ${
            healthData.length === 0 ? 'bg-[var(--text-muted)]' :
            operationalCount === healthData.length ? 'bg-[var(--pass)] shadow-[0_0_8px_var(--pass)]' : 'bg-[var(--amber)] shadow-[0_0_8px_var(--amber)]'
          }`}></span>
        </div>

        <div className="grid grid-cols-5 gap-2 mb-2">
          {healthData.map((agent) => {
            const isOp = agent.status === 'operational';
            return (
            <div
              key={agent.id}
              title={`${agent.id}: ${agent.status.toUpperCase()}`}
              className="flex items-center gap-1 cursor-help opacity-80 hover:opacity-100 transition-opacity"
            >
              <div className={`w-2 h-2 rounded-full ${isOp ? 'bg-[var(--pass)] shadow-[0_0_5px_var(--pass-dim)]' : 'bg-[var(--fail)]'}`} />
              <span className="text-[9px] font-mono text-[var(--text-secondary)] truncate">{agent.id.slice(0, 4)}</span>
            </div>
            );
          })}
        </div>
      </div>
    </aside>
  );
}
