"use client";

import React, { useEffect, useState } from 'react';
import { ShieldCheck, Crosshair, Clock, Users } from 'lucide-react';
import { useRouter } from 'next/navigation';

export function ExecutiveKPIBar() {
  const router = useRouter();
  const [data, setData] = useState({
    riskIndex: 28,
    accuracy: 94.3,
    resolveTime: 2.3,
    workersAssisted: 34
  });
  const [isLive, setIsLive] = useState(false);

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || ""}/api/v1/learning/stats`);
        if (res.ok) {
          const stats = await res.json();
          setData(prev => ({
            ...prev,
            resolveTime: stats.avg_resolution_time_hours || prev.resolveTime,
            workersAssisted: stats.total_incidents_learned || prev.workersAssisted
          }));
          setIsLive(true);
        } else {
          setIsLive(false);
        }
      } catch (e) {
        setIsLive(false);
      }
    };
    fetchStats();
  }, []);

  const kpis = [
    {
      label: "PROJECT RISK INDEX",
      value: data.riskIndex,
      suffix: " (Low Risk)",
      color: "var(--pass)",
      icon: <ShieldCheck size={28} className="text-[var(--pass)]" />,
      trend: "↓ from 85 this week",
      subtext: "Risk reduced 67% through AI intervention",
      route: "/zones"
    },
    {
      label: "AI ACCURACY RATE",
      value: data.accuracy,
      suffix: "%",
      color: "var(--cyan)",
      icon: <Crosshair size={28} className="text-[var(--cyan)]" />,
      trend: "+2.1% vs last week",
      subtext: "Predictions confirmed correct",
      route: "/rfis"
    },
    {
      label: "MEAN TIME TO RESOLVE",
      value: data.resolveTime,
      suffix: "h",
      color: "var(--purple)",
      icon: <Clock size={28} className="text-[var(--purple)]" />,
      trend: "↓ from 8.2h industry avg",
      subtext: "4x faster than manual process",
      route: "/issues"
    },
    {
      label: "WORKERS ASSISTED",
      value: data.workersAssisted,
      suffix: " workers",
      color: "var(--amber)",
      icon: <Users size={28} className="text-[var(--amber)]" />,
      trend: "67 queries answered",
      subtext: "In 4 languages this week",
      route: "/memory"
    }
  ];

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4 mb-6">
      {kpis.map((kpi, idx) => {
        const progressPct = Math.min(100, Math.max(20, (kpi.value.toString().length * 15) + (idx * 10)));
        return (
          <div 
            key={idx} 
            onClick={() => router.push(kpi.route)}
            className="group cursor-pointer bg-gradient-to-b from-[var(--bg-surface-lighter)] to-[var(--bg-surface)] backdrop-blur-[20px] rounded-xl border border-[var(--border-subtle)] relative overflow-hidden shadow-lg p-5 flex flex-col justify-between animate-fade-in hover:shadow-2xl transition-all duration-300 hover:border-white/20 hover:-translate-y-1"
            style={{ animationDelay: `${idx * 150}ms` }}
          >
            {/* Live Indicator */}
            <div className="absolute top-3 right-3 flex items-center gap-1 opacity-70">
              <div className={`w-1.5 h-1.5 rounded-full animate-pulse ${isLive ? 'bg-[var(--cyan)] shadow-[0_0_8px_var(--cyan)]' : 'bg-[var(--amber)] shadow-[0_0_8px_var(--amber)]'}`} />
              <span className="text-[8px] font-mono tracking-widest text-[var(--text-muted)]">{isLive ? 'LIVE' : 'DEMO'}</span>
            </div>

            <div className="flex items-start justify-between mb-4">
              <span className="text-sm font-semibold text-[var(--text-secondary)] uppercase tracking-wider">{kpi.label}</span>
              <span className="mr-6">{kpi.icon}</span>
            </div>
            
            <div className="flex items-baseline gap-1 mt-1 mb-2">
              <span className="text-[44px] leading-none font-bold tracking-tight text-[var(--text-primary)]" style={{ fontFamily: 'var(--font-display)', color: kpi.color }}>
                {kpi.value.toLocaleString()}{kpi.suffix}
              </span>
            </div>

            <div className="mt-2 flex flex-col gap-1 mb-3 relative">
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-[var(--text-primary)] font-semibold">{kpi.trend}</span>
              </div>
              <span className="text-xs text-[var(--text-muted)]">{kpi.subtext}</span>
              
              {/* View Details Hover Reveal */}
              <span className="absolute bottom-0 right-0 text-[10px] font-bold text-[var(--text-primary)] opacity-0 group-hover:opacity-100 transition-opacity uppercase tracking-wider bg-[var(--bg-elevated)] px-2 py-1 rounded border border-[var(--border-accent)] shadow-lg">
                View Details ↗
              </span>
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
