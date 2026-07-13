"use client";

import React, { useEffect, useState } from 'react';
import { GlassCard } from '../ui/GlassCard';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, BarChart, Bar, Legend, ReferenceLine, Label } from 'recharts';

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
    const prevented = payload.find((p: any) => p.dataKey === 'prevented')?.value || 0;
    const occurred = payload.find((p: any) => p.dataKey === 'occurred')?.value || 0;
    return (
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] p-3 rounded-lg shadow-xl">
        <p className="font-bold text-[var(--text-primary)] mb-2">{label}</p>
        <p className="text-[12px] text-[var(--text-secondary)]">
          <span className="text-[var(--cyan)] font-bold">{prevented}</span> prevented by AI
        </p>
        <p className="text-[12px] text-[var(--text-secondary)]">
          <span className="text-[var(--fail)] font-bold">{occurred}</span> occurred
        </p>
      </div>
    );
  }
  return null;
};

export function ExecutiveCharts() {
  const [riskData, setRiskData] = useState(DEMO_RISK_DATA);

  // In real app, fetch /api/v1/learning/trends here
  // Fallback to DEMO_RISK_DATA if failed.

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 w-full">
      <GlassCard className="p-6 h-[400px] flex flex-col relative">
        <div className="mb-6">
          <h3 className="text-sm font-semibold tracking-wide text-[var(--text-primary)] uppercase">RISK REDUCTION THROUGH AI INTERVENTION</h3>
          <p className="text-[10px] text-[var(--text-muted)] font-mono mt-1">Daily site risk index score (lower is better)</p>
        </div>
        <div className="flex-1 w-full min-h-0">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={riskData} margin={{ top: 20, right: 30, left: -20, bottom: 0 }}>
              <defs>
                <linearGradient id="riskGradient" x1="0" y1="0" x2="1" y2="0">
                  <stop offset="0%" stopColor="#FF3B3B" stopOpacity={0.8}/>
                  <stop offset="100%" stopColor="#00C851" stopOpacity={0.8}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" vertical={false} />
              <XAxis dataKey="name" stroke="var(--text-muted)" fontSize={12} tickLine={false} axisLine={false} />
              <YAxis stroke="var(--text-muted)" fontSize={12} tickLine={false} axisLine={false} />
              <Tooltip 
                contentStyle={{ backgroundColor: 'var(--bg-elevated)', border: '1px solid var(--border-subtle)', borderRadius: '8px' }}
                itemStyle={{ color: 'var(--text-primary)' }}
              />
              
              <ReferenceLine y={30} stroke="rgba(255,255,255,0.3)" strokeDasharray="4 2">
                 <Label value="Safe Zone" position="insideTopLeft" fill="rgba(255,255,255,0.5)" fontSize={10} />
              </ReferenceLine>

              {/* Annotation at Wed */}
              <ReferenceLine x="Wed" stroke="var(--cyan)" strokeDasharray="3 3" opacity={0.5}>
                <Label value="🚩 AI predictions activated" position="top" fill="var(--cyan)" fontSize={10} offset={10} />
              </ReferenceLine>

              <Area type="monotone" dataKey="risk" stroke="url(#riskGradient)" fillOpacity={0.3} fill="url(#riskGradient)" strokeWidth={3} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </GlassCard>

      <GlassCard className="p-6 h-[400px] flex flex-col relative">
        <h3 className="text-sm font-semibold tracking-wide text-[var(--text-primary)] uppercase mb-6">AI Interventions vs Occurrences</h3>
        <div className="flex-1 w-full min-h-0">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={DEMO_INCIDENT_DATA} margin={{ top: 10, right: 30, left: 0, bottom: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" vertical={false} />
              <XAxis dataKey="name" stroke="var(--text-muted)" fontSize={12} tickLine={false} axisLine={false} />
              <YAxis stroke="var(--text-muted)" fontSize={12} tickLine={false} axisLine={false} label={{ value: 'Issues Count', angle: -90, position: 'insideLeft', fill: 'var(--text-muted)', fontSize: 12, dy: 30 }} />
              <Tooltip cursor={{ fill: 'var(--bg-hover)' }} content={<CustomBarTooltip />} />
              <Legend iconType="circle" wrapperStyle={{ fontSize: '12px', paddingTop: '10px' }} />
              <Bar dataKey="prevented" name="AI Prevented" fill="var(--cyan)" radius={[4, 4, 0, 0]} />
              <Bar dataKey="occurred" name="Actual Incidents" fill="var(--fail)" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        
        {/* Summary text below legend */}
        <div className="absolute bottom-2 left-0 right-0 text-center">
          <span className="text-[10px] font-mono text-[var(--cyan)] tracking-wider">
            91.3% intervention rate · AI caught 10 in 11 issues before escalation
          </span>
        </div>
      </GlassCard>
    </div>
  );
}
