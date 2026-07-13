"use client";

import React from 'react';
import { useAPIData } from '@/hooks/useAPIData';
import { useCountUp } from '@/hooks/useCountUp';

const DEMO_KPI = {
  total_incidents_learned: 47,
  total_cost_avoided_usd: 187000,
  rework_prevented_count: 12,
  avg_resolution_time_hours: 2.3,
  rfis_avoided: 23,
  time_saved_hours: 340,
  safety_alerts_fired: 8,
  workers_assisted: 34
};

export function KPIBar() {
  const { data: stats, isLive } = useAPIData('/api/v1/learning/stats', DEMO_KPI);

  const kpis = [
    { 
      label: "RFIs Avoided",
      value: useCountUp(stats?.rfis_avoided ?? DEMO_KPI.rfis_avoided),
      prefix: "",
      suffix: "",
      icon: "🔮",
      trend: "+23% vs last month",
      color: "var(--purple)"
    },
    {
      label: "Cost Saved",
      value: useCountUp(stats?.total_cost_avoided_usd ?? DEMO_KPI.total_cost_avoided_usd),
      prefix: "$",
      suffix: "",
      icon: "💰",
      trend: "+31% vs last month",
      color: "var(--pass)"
    },
    {
      label: "Hours Saved",
      value: useCountUp(stats?.time_saved_hours ?? DEMO_KPI.time_saved_hours),
      prefix: "",
      suffix: "h",
      icon: "⏱",
      trend: "+28% vs last month",
      color: "var(--cyan)"
    },
    {
      label: "Rework Prevented",
      value: useCountUp(stats?.rework_prevented_count ?? DEMO_KPI.rework_prevented_count),
      prefix: "",
      suffix: " events",
      icon: "🛡",
      trend: "+15% vs last month",
      color: "var(--amber)"
    }
  ];

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4 mb-6">
      {kpis.map((kpi, idx) => {
        // Calculate a dummy progress based on value length or trend just for visual
        const progressPct = Math.min(100, Math.max(20, (kpi.value.toString().length * 15) + (idx * 10)));
        return (
        <div 
          key={idx} 
          className="bg-gradient-to-b from-[var(--bg-surface-lighter)] to-[var(--bg-surface)] backdrop-blur-[20px] rounded-xl border border-[var(--border-subtle)] relative overflow-hidden shadow-lg p-5 flex flex-col justify-between animate-fade-in"
          style={{ animationDelay: `${idx * 150}ms` }}
        >
          <div className="flex items-start justify-between mb-4">
            <span className="text-sm font-semibold text-[var(--text-secondary)] uppercase tracking-wider">{kpi.label}</span>
            <span className="text-2xl">{kpi.icon}</span>
          </div>
          
          <div className="flex items-baseline gap-1 mt-1 mb-2">
            <span className="text-[44px] leading-none font-bold tracking-tight text-[var(--text-primary)]" style={{ fontFamily: 'var(--font-display)', color: kpi.color }}>
              {kpi.prefix}{kpi.value.toLocaleString()}{kpi.suffix}
            </span>
          </div>

          <div className="mt-2 flex items-center gap-1.5 mb-2">
            <span className="text-[10px] bg-[var(--pass-dim)] text-[var(--pass)] px-1.5 py-0.5 rounded font-bold">↗</span>
            <span className="text-xs text-[var(--text-muted)]">{kpi.trend}</span>
          </div>
          
          {/* Bottom Progress Bar */}
          <div className="absolute bottom-0 left-0 w-full h-[4px] bg-[var(--bg-elevated)]">
             <div className="h-full transition-all duration-1000" style={{ width: `${progressPct}%`, backgroundColor: kpi.color }} />
          </div>
        </div>
        );
      })}
    </div>
  );
}
