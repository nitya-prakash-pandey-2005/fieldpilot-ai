"use client";

import React, { useEffect, useState } from 'react';
import { DollarSign, HardHat, FileText, Activity } from 'lucide-react';

const useCountUp = (target: number, duration = 1500) => {
  const [current, setCurrent] = useState(0);
  
  useEffect(() => {
    if (target === 0) return;
    
    const startTime = Date.now();
    const timer = setInterval(() => {
      const elapsed = Date.now() - startTime;
      const progress = Math.min(elapsed / duration, 1);
      // easeOutExpo
      const eased = progress === 1 ? 1 : 1 - Math.pow(2, -10 * progress);
      setCurrent(Math.floor(eased * target));
      if (progress === 1) clearInterval(timer);
    }, 16);
    
    return () => clearInterval(timer);
  }, [target, duration]);
  
  return current;
};

export default function KPIBar() {
  const [stats, setStats] = useState({
    total_cost_avoided_usd: 0,
    rework_prevented_count: 0,
    total_incidents: 0
  });

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const res = await fetch('http://localhost:8000/api/v1/learning/stats');
        const data = await res.json();
        setStats(data);
      } catch (e) {
        console.error("Failed to fetch stats", e);
        // Fallback for demo if backend is not running
        setStats({
          total_cost_avoided_usd: 187000,
          rework_prevented_count: 12,
          total_incidents: 47
        });
      }
    };
    fetchStats();
  }, []);

  const costAnim = useCountUp(stats.total_cost_avoided_usd);
  const reworkAnim = useCountUp(stats.rework_prevented_count);
  const incidentsAnim = useCountUp(stats.total_incidents);

  const kpis = [
    { label: 'Cost Avoided', value: `$${costAnim.toLocaleString()}`, icon: DollarSign, color: 'text-atw-green', delay: '0ms' },
    { label: 'Rework Prevented', value: `${reworkAnim} events`, icon: HardHat, color: 'text-atw-cyan', delay: '150ms' },
    { label: 'Incidents Learned', value: `${incidentsAnim} total`, icon: Activity, color: 'text-atw-purple', delay: '300ms' },
    { label: 'Active Zones', value: '12', icon: FileText, color: 'text-atw-amber', delay: '450ms' },
  ];

  return (
    <div className="grid grid-cols-4 gap-4">
      {kpis.map((kpi, i) => (
        <div 
          key={i} 
          className="bg-atw-surface/60 backdrop-blur-md border border-white/10 rounded-xl p-5 flex items-center gap-4 animate-fade-in shadow-lg"
          style={{ animationDelay: kpi.delay, animationFillMode: 'backwards' }}
        >
          <div className={`p-3 rounded-lg bg-black/40 border border-white/5`}>
            <kpi.icon className={kpi.color} size={28} />
          </div>
          <div>
            <p className="text-sm font-medium text-white/50 tracking-wider uppercase">{kpi.label}</p>
            <p className="text-2xl font-bold text-white tracking-tight">{kpi.value}</p>
          </div>
        </div>
      ))}
    </div>
  );
}
