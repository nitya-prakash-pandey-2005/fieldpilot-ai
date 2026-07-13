"use client";

import React, { useState } from 'react';
import { GlassCard } from '../ui/GlassCard';
import { Calculator, DollarSign, Clock, ShieldAlert, Hammer } from 'lucide-react';

const baseMetrics = {
  rfisPerWorkerPerMonth: 0.023,
  costPerRFI: 4000,
  hoursPerRFI: 7.2,
  reworkCostPct: 0.12
};

export function ROICalculator() {
  const [workers, setWorkers] = useState(200);
  const [months, setMonths] = useState(18);

  const calculate = (w: number, m: number) => {
    const rfis = Math.round(w * m * baseMetrics.rfisPerWorkerPerMonth);
    const cost = Math.round(w * m * baseMetrics.rfisPerWorkerPerMonth * baseMetrics.costPerRFI);
    const hours = Math.round(w * m * baseMetrics.rfisPerWorkerPerMonth * baseMetrics.hoursPerRFI);
    const rework = Math.round(w * m * 0.0067); // roughly deriving 24 from 200*18
    return { rfis, cost, hours, rework };
  };

  const results = calculate(workers, months);

  return (
    <GlassCard className="p-6 my-6 border border-[var(--cyan)]/30 shadow-[0_0_30px_rgba(0,212,255,0.05)] shrink-0">
      <div className="flex items-center gap-4 mb-8">
        <div className="flex items-center justify-center p-2.5 bg-[var(--cyan)]/10 rounded-lg border border-[var(--cyan)]/30 shrink-0">
          <Calculator className="text-[var(--cyan)]" size={24} />
        </div>
        <div className="flex flex-col justify-center gap-0.5">
          <h2 className="text-xl font-bold tracking-wide text-[var(--text-primary)] uppercase leading-none">CALCULATE YOUR PROJECT SAVINGS</h2>
          <p className="text-xs text-[var(--text-muted)] font-mono leading-none">HOW MUCH WOULD FIELDPILOT AI SAVE YOUR PROJECT?</p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        {/* Sliders Area */}
        <div className="flex flex-col gap-6 p-6 bg-[var(--bg-elevated)] rounded-xl border border-[var(--border-subtle)]">
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <label className="text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wide">Project Size (Workers)</label>
              <span className="font-mono font-bold text-[var(--cyan)] text-lg">{workers}</span>
            </div>
            <input 
              type="range" 
              min="50" max="500" step="10" 
              value={workers} 
              onChange={(e) => setWorkers(parseInt(e.target.value))}
              className="w-full accent-[var(--cyan)] cursor-pointer h-2 bg-[var(--border-subtle)] rounded-lg appearance-none"
            />
            <div className="flex justify-between text-[10px] text-[var(--text-muted)] mt-1">
              <span>50</span>
              <span>500</span>
            </div>
          </div>

          <div className="flex flex-col gap-2 mt-4">
            <div className="flex items-center justify-between">
              <label className="text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wide">Project Duration (Months)</label>
              <span className="font-mono font-bold text-[var(--cyan)] text-lg">{months}</span>
            </div>
            <input 
              type="range" 
              min="6" max="36" step="3" 
              value={months} 
              onChange={(e) => setMonths(parseInt(e.target.value))}
              className="w-full accent-[var(--cyan)] cursor-pointer h-2 bg-[var(--border-subtle)] rounded-lg appearance-none"
            />
            <div className="flex justify-between text-[10px] text-[var(--text-muted)] mt-1">
              <span>6mo</span>
              <span>36mo</span>
            </div>
          </div>
        </div>

        {/* Results Area */}
        <div className="flex flex-col">
          <h3 className="text-[10px] font-bold text-[var(--text-muted)] tracking-widest uppercase mb-4">ESTIMATED SAVINGS</h3>
          
          <div className="grid grid-cols-2 gap-4">
            <div className="flex items-center gap-3 bg-[var(--bg-surface)] p-4 rounded-lg border border-[var(--border-subtle)] hover:border-[var(--cyan)]/50 transition-colors">
              <ShieldAlert className="text-[var(--cyan)] opacity-70" size={20} />
              <div className="flex flex-col">
                <span className="text-2xl font-bold font-mono text-[var(--text-primary)]">~{results.rfis}</span>
                <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">RFIs Avoided</span>
              </div>
            </div>
            
            <div className="flex items-center gap-3 bg-[var(--bg-surface)] p-4 rounded-lg border border-[var(--border-subtle)] hover:border-[var(--pass)]/50 transition-colors">
              <DollarSign className="text-[var(--pass)] opacity-70" size={20} />
              <div className="flex flex-col">
                <span className="text-2xl font-bold font-mono text-[var(--pass)]">~${results.cost.toLocaleString()}</span>
                <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">Cost Saved</span>
              </div>
            </div>

            <div className="flex items-center gap-3 bg-[var(--bg-surface)] p-4 rounded-lg border border-[var(--border-subtle)] hover:border-[var(--amber)]/50 transition-colors">
              <Clock className="text-[var(--amber)] opacity-70" size={20} />
              <div className="flex flex-col">
                <span className="text-2xl font-bold font-mono text-[var(--text-primary)]">~{results.hours.toLocaleString()}h</span>
                <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">Hours Saved</span>
              </div>
            </div>

            <div className="flex items-center gap-3 bg-[var(--bg-surface)] p-4 rounded-lg border border-[var(--border-subtle)] hover:border-[var(--purple)]/50 transition-colors">
              <Hammer className="text-[var(--purple)] opacity-70" size={20} />
              <div className="flex flex-col">
                <span className="text-2xl font-bold font-mono text-[var(--text-primary)]">~{results.rework}</span>
                <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">Rework Prevented</span>
              </div>
            </div>
          </div>
          
          <div className="mt-6 p-4 bg-[var(--pass-dim)] rounded-lg border border-[var(--pass)]/30 flex items-center justify-between">
            <span className="text-sm font-bold text-[var(--pass)] tracking-wide">ROI Ratio: 12:1</span>
            <span className="text-xs text-[var(--pass)] opacity-80 font-mono">"For every $1 invested, save $12 in rework costs"</span>
          </div>
        </div>
      </div>
    </GlassCard>
  );
}
