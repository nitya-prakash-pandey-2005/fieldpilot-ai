"use client";

import React from 'react';
import { GlassCard } from '../ui/GlassCard';
import { useAPIData } from '@/hooks/useAPIData';

const DEMO_RFIS = [
  { id: "RFI-PRED-102", title: "Clash between HVAC duct and sprinkler main in Corridor B", confidence: 0.94, impact: "High", action: "Review Model", zone: "Zone B3" },
  { id: "RFI-PRED-103", title: "Missing dimensions for embed plates on Grid Line 4", confidence: 0.72, impact: "Medium", action: "Draft RFI", zone: "Zone D4" },
  { id: "RFI-PRED-104", title: "Inconsistent fire rating specs for Door 120", confidence: 0.55, impact: "Low", action: "Check Spec", zone: "Zone A12" },
];

export function PredictedRFIPanel() {
  const { data: rfis } = useAPIData('/api/v1/planning/predictions', DEMO_RFIS);
  
  // Real-time timestamp mockup
  const [updateTime, setUpdateTime] = React.useState(0);
  React.useEffect(() => {
    const timer = setInterval(() => setUpdateTime(prev => prev + 5), 5000);
    return () => clearInterval(timer);
  }, []);

  return (
    <GlassCard className="h-full flex flex-col" accentColor="var(--purple)">
      <div className="p-4 border-b border-[var(--border-subtle)] flex items-center justify-between">
        <h2 className="text-sm font-semibold tracking-wide text-[var(--text-primary)] uppercase">AI Predicted RFIs</h2>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-[var(--text-muted)] font-mono">· Updated {updateTime === 0 ? '5m ago' : `${5 * 60 + updateTime}s ago`}</span>
          <span className="text-[10px] font-bold bg-[var(--purple-dim)] text-[var(--purple)] px-2 py-1 rounded-full border border-[var(--purple)]/30">AGENT 7 ACTIVE</span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-2">
        {rfis.map((rfi: any) => {
          // Circular progress config
          const pct = Math.round(rfi.confidence * 100);
          const circumference = 2 * Math.PI * 14;
          const strokeDashoffset = circumference - (pct / 100) * circumference;
          const circleColor = pct > 80 ? 'var(--pass)' : pct >= 60 ? 'var(--amber)' : 'var(--text-muted)';
          
          return (
          <div key={rfi.id} className="p-3 border-b border-[var(--border-subtle)] last:border-0 hover:bg-[var(--bg-hover)] transition-colors rounded-lg mb-1 relative overflow-hidden group">
            <div className="flex items-start justify-between mb-2">
              <div className="flex flex-col">
                <span className="text-xs font-mono font-semibold text-[var(--purple)]">{rfi.id}</span>
                <span className="text-[10px] text-[var(--text-muted)] mt-1">predicted for: next 7 days</span>
              </div>
              
              {/* Confidence Circle */}
              <div className="relative w-8 h-8 flex items-center justify-center shrink-0">
                <svg className="w-8 h-8 transform -rotate-90">
                  <circle cx="16" cy="16" r="14" fill="none" stroke="rgba(255,255,255,0.1)" strokeWidth="2" />
                  <circle cx="16" cy="16" r="14" fill="none" stroke={circleColor} strokeWidth="2"
                    strokeDasharray={circumference}
                    strokeDashoffset={strokeDashoffset}
                    className="transition-all duration-1000"
                  />
                </svg>
                <span className="absolute text-[10px] font-bold text-[var(--text-primary)]">{pct}%</span>
              </div>
            </div>
            
            <p className="text-sm text-[var(--text-primary)] mb-3">{rfi.title}</p>
            
            <div className="flex items-center justify-between mb-3">
               <div className="flex items-center gap-1.5 text-xs text-[var(--text-muted)]">
                 <span className="text-[var(--cyan)]">📍</span> {rfi.zone}
               </div>
            </div>
            
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-bold px-2 py-0.5 rounded tracking-wider" style={{
                backgroundColor: rfi.impact === 'High' ? 'rgba(255,107,0,0.2)' : rfi.impact === 'Medium' ? 'rgba(0,152,255,0.2)' : 'rgba(128,128,160,0.2)',
                color: rfi.impact === 'High' ? '#FF6B00' : rfi.impact === 'Medium' ? '#0098FF' : '#8080A0'
              }}>
                {rfi.impact.toUpperCase()} IMPACT
              </span>
              <button className="text-[10px] font-bold bg-[var(--bg-elevated)] border border-[var(--border-subtle)] px-2 py-1 rounded hover:bg-[var(--purple-dim)] hover:border-[var(--purple)] hover:text-[var(--purple)] transition-colors uppercase w-24 text-center">
                {rfi.action}
              </button>
            </div>
          </div>
        )})}
      </div>
    </GlassCard>
  );
}
