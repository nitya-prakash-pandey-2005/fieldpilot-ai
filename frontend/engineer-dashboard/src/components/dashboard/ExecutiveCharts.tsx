"use client";

import React, { useEffect, useState } from 'react';
import { GlassCard } from '../ui/GlassCard';
import { LiveIndicator } from '../ui/LiveIndicator';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, BarChart, Bar, Legend, ReferenceLine, Label } from 'recharts';

import { apiBase } from '@/lib/api';
// No illustrative fallback series lives here any more.
//
// This component used to render a plausible seven-day cost curve and a
// four-week incident chart whenever the backend had nothing to show. Those
// numbers were invented, but on screen they were indistinguishable from
// measured ones — a chart that says "$47,000 avoided on Thursday" reads as
// fact whatever a small LIVE badge next to it says. When the underlying data
// is empty the honest thing to draw is nothing, plus an explanation of what
// would fill it.

type EmptyStateProps = { title: string; hint: string; error?: string | null };

function ChartEmptyState({ title, hint, error }: EmptyStateProps) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center text-center px-6 gap-2">
      <div className="w-10 h-10 rounded-full border border-dashed border-[var(--border-subtle)] flex items-center justify-center text-[var(--text-muted)] text-lg">
        {error ? '!' : '—'}
      </div>
      <p className="text-[13px] font-medium text-[var(--text-secondary)]">
        {error ? 'Cannot load this metric' : title}
      </p>
      <p className="text-[11px] text-[var(--text-muted)] max-w-[280px] leading-relaxed">
        {error ?? hint}
      </p>
    </div>
  );
}

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
  const [costData, setCostData] = useState<{ name: string; cost: number }[]>([]);
  const [incidentData, setIncidentData] = useState<{ name: string; incidents: number }[]>([]);
  const [isLive, setIsLive] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const API = apiBase();
    let cancelled = false;

    const load = async () => {
      try {
        const res = await fetch(`${API}/api/v1/learning/trends`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = await res.json();
        if (cancelled) return;
        const rows = json?.data ?? [];
        setCostData(rows.map((r: any) => ({ name: String(r.date).slice(5), cost: r.cost_avoided })));
        setIncidentData(rows.map((r: any) => ({ name: String(r.date).slice(5), incidents: r.incidents })));
        setIsLive(rows.length > 0);
        setError(null);
      } catch (e: any) {
        if (!cancelled) {
          setIsLive(false);
          setError(`Backend unreachable at ${API}`);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    load();
    // Executive metrics move as engineers resolve issues during a walkthrough;
    // refreshing keeps the panel honest without a manual reload.
    const timer = setInterval(load, 30_000);
    return () => { cancelled = true; clearInterval(timer); };
  }, []);

  const EMPTY_HINT =
    'Populated from resolved incidents. Resolve an issue on the Issues page ' +
    '(or POST /api/v1/learning/resolve) and it appears here within 30s.';

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 w-full">
      <GlassCard className="p-6 h-[400px] flex flex-col relative">
        <div className="mb-6 flex items-center gap-2">
          <h3 className="text-sm font-semibold tracking-wide text-[var(--text-primary)] uppercase">Cost Avoided Through AI Intervention</h3>
          <LiveIndicator isLive={isLive} />
        </div>
        <p className="text-[10px] text-[var(--text-muted)] font-mono -mt-4 mb-2">Daily cost avoided (USD), from resolved incidents</p>
        {!loading && costData.length === 0 ? (
          <ChartEmptyState
            title="No resolved incidents yet"
            hint={EMPTY_HINT}
            error={error}
          />
        ) : (
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
        )}
      </GlassCard>

      <GlassCard className="p-6 h-[400px] flex flex-col relative">
        <div className="mb-6 flex items-center gap-2">
          <h3 className="text-sm font-semibold tracking-wide text-[var(--text-primary)] uppercase">Incidents Resolved Per Day</h3>
          <LiveIndicator isLive={isLive} />
        </div>
        {!loading && incidentData.length === 0 ? (
          <ChartEmptyState
            title="No incidents resolved yet"
            hint={EMPTY_HINT}
            error={error}
          />
        ) : (
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
        )}
      </GlassCard>
    </div>
  );
}
