"use client";

import React, { useState } from 'react';
import { GlassCard } from '../ui/GlassCard';
import { useAPIData } from '@/hooks/useAPIData';
import { DraftRFIModal } from './DraftRFIModal';

// No DEMO_RFIS fallback. GET /api/v1/planning/predictions is real (Agent 6's
// calibrated risk model plus an LLM-written rationale), so inventing three
// plausible predictions when it fails would put fabricated engineering advice
// — "clash between HVAC duct and sprinkler main" — on the landing page,
// indistinguishable from the model's actual output.

// Matches the real GET /api/v1/planning/predictions payload, verified against
// a live response: { id, title, confidence, impact, action, zone }.
type PredictedRFI = {
  id: string;
  title?: string;
  confidence?: number;
  impact?: string;
  action?: string;
  zone?: string;
};

export function PredictedRFIPanel() {
  const { data, error } = useAPIData<PredictedRFI[]>('/api/v1/planning/predictions');
  const rfis: PredictedRFI[] = Array.isArray(data) ? data : [];
  const [selectedRFI, setSelectedRFI] = useState<any>(null);
  
  // Real-time timestamp mockup
  const [updateTime, setUpdateTime] = React.useState(0);
  React.useEffect(() => {
    const timer = setInterval(() => setUpdateTime(prev => prev + 5), 5000);
    return () => clearInterval(timer);
  }, []);

  return (
    <>
    <GlassCard className="h-full flex flex-col" accentColor="var(--purple)">
      <div className="p-4 border-b border-[var(--border-subtle)] flex items-center justify-between">
        <h2 className="text-sm font-semibold tracking-wide text-[var(--text-primary)] uppercase">AI Predicted RFIs</h2>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-[var(--text-muted)] font-mono">· Updated {updateTime === 0 ? '5m ago' : `${5 * 60 + updateTime}s ago`}</span>
          <span className="text-[10px] font-bold bg-[var(--purple-dim)] text-[var(--purple)] px-2 py-1 rounded-full border border-[var(--purple)]/30">AGENT 7 ACTIVE</span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-2">
        {rfis.length === 0 && (
          <div className="h-full flex flex-col items-center justify-center text-center px-6 gap-1.5 py-8">
            <p className="text-[13px] text-[var(--text-secondary)]">
              {error ? 'Cannot load predictions' : 'No predicted RFIs'}
            </p>
            <p className="text-[11px] text-[var(--text-muted)] max-w-[290px] leading-relaxed">
              {error
                ? 'The predictive RFI agent is unreachable.'
                : 'Agent 6 scores each zone from live issue history. Predictions appear once a zone accumulates enough signal.'}
            </p>
          </div>
        )}
        {rfis.map((rfi) => {
          // Circular progress config
          const pct = Math.round((rfi.confidence ?? 0) * 100);
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
                {(rfi.impact ?? 'unknown').toUpperCase()} IMPACT
              </span>
              <button 
                onClick={() => setSelectedRFI(rfi)}
                className="text-[10px] font-bold bg-[var(--bg-elevated)] border border-[var(--border-subtle)] px-2 py-1 rounded hover:bg-[var(--purple-dim)] hover:border-[var(--purple)] hover:text-[var(--purple)] transition-colors uppercase w-24 text-center">
                {rfi.action ?? 'Draft RFI'}
              </button>
            </div>
          </div>
        )})}
      </div>
    </GlassCard>
    
    <DraftRFIModal 
      isOpen={selectedRFI !== null}
      onClose={() => setSelectedRFI(null)}
      rfiId={selectedRFI?.id}
      title={selectedRFI?.title}
      zone={selectedRFI?.zone}
    />
    </>
  );
}
