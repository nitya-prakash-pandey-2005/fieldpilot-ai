"use client";

import React, { useEffect, useState } from 'react';
import { GlassCard } from '../ui/GlassCard';
import { LiveIndicator } from '../ui/LiveIndicator';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, BarChart, Bar, Legend, ReferenceLine, Label } from 'recharts';

// Fallback demo data, shown only until GET /api/v1/learning/trends returns
// real rows (see fetchTrends below) — previously this was permanently
// hardcoded and the real endpoint was never called at all.
const DEMO_RISK_DATA = [
  { name: 'Mon', risk: 85, avg: 45 },
  { name: 'Tue', risk: 78, avg: 45 },
  { name: 'Wed', risk: 65, avg: 45 },
  { name: 'Thu', risk: 52, avg: 45 },
  { name: 'Fri', risk: 41, avg: 45 },
  { name: 'Sat', risk: 35, avg: 45 },
  { name: 'Sun', risk: 28, avg: 45 },
];

const DEMO_INCIDENT_DATA = [
  { name: 'Week 1', prevented: 14, occurred: 2 },
  { name: 'Week 2', prevented: 20, occurred: 1 },
  { name: 'Week 3', prevented: 25, occurred: 0 },
  { name: 'Week 4', prevented: 18, occurred: 2 },
];

const CustomBarTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    const incidents = payload.find((p: any) => p.dataKey === 'incidents')?.value || 0;
    return (
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] p-3 rounded-lg shadow-xl">
        <p className="font-bold text-[var(--text-primary)] mb-2">{label}</p>
        <p className="text-[12px] text-[var(--text-secondary)]">
          <span className="text-[var(--cyan)] font-bold">{incidents}</span> incidents resolved
        </p>
      </div>
    );
  }
  return null;
};

export function ExecutiveCharts() {
  const [costData, setCostData] = useState<{ name: string; cost: number }[]>(DEMO_RISK_DATA.map(d => ({ name: d.name, cost: 0 })));
  const [incidentData, setIncidentData] = useState<{ name: string; incidents: number }[]>(
    DEMO_INCIDENT_DATA.map(d => ({ name: d.name, incidents: d.prevented }))
  );
  const [isLive, setIsLive] = useState(false);

  useEffect(() => {
    const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
    fetch(`${API}/api/v1/learning/trends`)
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(json => {
        const rows = json?.data || [];
        if (rows.length > 0) {
          setCostData(rows.map((r: any) => ({ name: r.date.slice(5), cost: r.cost_avoided })));
          setIncidentData(rows.map((r: any) => ({ name: r.date.slice(5), incidents: r.incidents })));
          setIsLive(true);
        }
        // If there's no real data yet (fresh install, nothing resolved
        // today), keep showing the illustrative demo series above rather
        // than an empty chart.
      })
      .catch(() => setIsLive(false));
  }, []);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 w-full">
      <GlassCard className="p-6 h-[400px] flex flex-col relative">
        <div className="mb-6 flex items-center gap-2">
          <h3 className="text-sm font-semibold tracking-wide text-[var(--text-primary)] uppercase">Cost Avoided Through AI Intervention</h3>
          <LiveIndicator isLive={isLive} />
        </div>
        <p className="text-[10px] text-[var(--text-muted)] font-mono -mt-4 mb-2">Daily cost avoided (USD), from resolved incidents</p>
        <div className="flex-1 w-full min-h-0">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={costData} margin={{ top: 20, right: 30, left: -20, bottom: 0 }}>
              <defs>
                <linearGradient id="riskGradient" x1="0" y1="0" x2="1" y2="0">
                  <stop offset="0%" stopColor="#00C851" stopOpacity={0.8}/>
                  <stop offset="100%" stopColor="#00D4FF" stopOpacity={0.8}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" vertical={false} />
              <XAxis dataKey="name" stroke="var(--text-muted)" fontSize={12} tickLine={false} axisLine={false} />
              <YAxis stroke="var(--text-muted)" fontSize={12} tickLine={false} axisLine={false} />
              <Tooltip
                contentStyle={{ backgroundColor: 'var(--bg-elevated)', border: '1px solid var(--border-subtle)', borderRadius: '8px' }}
                itemStyle={{ color: 'var(--text-primary)' }}
                formatter={(v: any) => [`$${Number(v).toLocaleString()}`, 'Cost avoided']}
              />
              <Area type="monotone" dataKey="cost" stroke="url(#riskGradient)" fillOpacity={0.3} fill="url(#riskGradient)" strokeWidth={3} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </GlassCard>

      <GlassCard className="p-6 h-[400px] flex flex-col relative">
        <div className="mb-6 flex items-center gap-2">
          <h3 className="text-sm font-semibold tracking-wide text-[var(--text-primary)] uppercase">Incidents Resolved Per Day</h3>
          <LiveIndicator isLive={isLive} />
        </div>
        <div className="flex-1 w-full min-h-0">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={incidentData} margin={{ top: 10, right: 30, left: 0, bottom: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" vertical={false} />
              <XAxis dataKey="name" stroke="var(--text-muted)" fontSize={12} tickLine={false} axisLine={false} />
              <YAxis stroke="var(--text-muted)" fontSize={12} tickLine={false} axisLine={false} label={{ value: 'Incidents', angle: -90, position: 'insideLeft', fill: 'var(--text-muted)', fontSize: 12, dy: 30 }} />
              <Tooltip cursor={{ fill: 'var(--bg-hover)' }} content={<CustomBarTooltip />} />
              <Legend iconType="circle" wrapperStyle={{ fontSize: '12px', paddingTop: '10px' }} />
              <Bar dataKey="incidents" name="Resolved by AI + Engineer" fill="var(--cyan)" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </GlassCard>
    </div>
  );
}
