"use client";

import React, { useState, useEffect } from 'react';
import { ExecutiveKPIBar } from '@/components/dashboard/ExecutiveKPIBar';
import { ExecutiveCharts } from '@/components/dashboard/ExecutiveCharts';
import { ROICalculator } from '@/components/dashboard/ROICalculator';
import { ExecutiveActivityRow } from '@/components/dashboard/ExecutiveActivityRow';
import { RefreshCw } from 'lucide-react';

export default function ExecutivePage() {
  const [timestamp, setTimestamp] = useState("");
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [justUpdated, setJustUpdated] = useState(false);

  useEffect(() => {
    setTimestamp(new Date().toLocaleTimeString());
    const timer = setInterval(() => {
      handleRefresh();
    }, 60000);
    return () => clearInterval(timer);
  }, []);

  const handleRefresh = () => {
    setIsRefreshing(true);
    // Real app would fetch data here
    setTimeout(() => {
      setTimestamp(new Date().toLocaleTimeString());
      setIsRefreshing(false);
      setJustUpdated(true);
      setTimeout(() => setJustUpdated(false), 3000);
    }, 600); // fake network delay
  };

  return (
    <div className="flex flex-col gap-2 relative animate-fade-in w-full pb-8">
      <div className="mb-4 flex justify-between items-start shrink-0">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-[var(--text-primary)] font-display uppercase">Executive Summary</h1>
          <p className="text-[var(--text-secondary)] mt-1 mb-1">High-level overview of FieldPilot AI ROI and risk mitigation.</p>
          {timestamp && (
            <p className="text-[10px] text-[var(--text-muted)] font-mono">
              {justUpdated ? <span className="text-[var(--cyan)]">Live — updated just now</span> : `Data as of: ${timestamp} · Auto-refreshes every 60s`}
            </p>
          )}
        </div>
        <button 
          onClick={handleRefresh}
          className="flex items-center gap-1.5 text-xs font-semibold bg-[var(--bg-elevated)] border border-[var(--border-subtle)] px-3 py-1.5 rounded hover:bg-[var(--bg-hover)] transition-colors text-[var(--text-primary)]"
        >
          <RefreshCw size={14} className={isRefreshing ? "animate-spin text-[var(--cyan)]" : ""} />
          Refresh
        </button>
      </div>

      <ExecutiveKPIBar key={timestamp} />
      
      <ExecutiveCharts key={`charts-${timestamp}`} />

      <ROICalculator />

      <ExecutiveActivityRow key={`activity-${timestamp}`} />
    </div>
  );
}
