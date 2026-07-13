"use client";

import React from 'react';
import { KPIBar } from '@/components/dashboard/KPIBar';
import { LiveSiteMap } from '@/components/dashboard/LiveSiteMap';
import { ActiveIssuesPanel } from '@/components/dashboard/ActiveIssuesPanel';
import { PredictedRFIPanel } from '@/components/dashboard/PredictedRFIPanel';

export default function Home() {
  const [obsIndex, setObsIndex] = React.useState(0);
  
  React.useEffect(() => {
    // Cycle the observation every 10 seconds for demo purposes
    const interval = setInterval(() => {
      setObsIndex(prev => prev === 0 ? 1 : 0);
    }, 10000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="flex flex-col h-full gap-4 relative animate-fade-in">
      <KPIBar />
      
      {/* LAST AI OBSERVATION BANNER */}
      <div className="w-full h-[40px] bg-[var(--bg-surface)]/80 backdrop-blur-md border border-[var(--border-accent)] rounded-lg flex items-center px-4 shadow-lg overflow-hidden relative">
        <div className="absolute left-0 top-0 bottom-0 w-1 bg-[var(--cyan)] shadow-[0_0_8px_var(--cyan)] animate-pulse" />
        
        {obsIndex === 0 ? (
          <p className="text-[11px] font-mono text-[var(--text-primary)] w-full truncate flex items-center gap-2">
            <span className="text-[14px]">🥽</span> 
            <span className="font-bold text-[var(--cyan)] tracking-wider">ZONE A12</span> 
            <span className="text-[var(--text-muted)] mx-1">·</span>
            Rebar spacing deviation detected 
            <span className="text-[var(--text-muted)] mx-1">·</span>
            <span className="text-[var(--fail)] font-bold">+30mm above spec</span> 
            <span className="text-[var(--text-muted)] mx-1">·</span>
            Worker: Ali Hassan
            <span className="text-[var(--text-muted)] mx-1">·</span>
            Agent 7 retrieved 3 relevant specs
            <span className="text-[var(--text-muted)] mx-1">·</span>
            WhatsApp dispatched to Engineer Chen
            <span className="text-[var(--text-muted)] mx-1">·</span>
            <span className="text-[var(--text-muted)]">2 minutes ago</span>
          </p>
        ) : (
          <p className="text-[11px] font-mono text-[var(--pass)] w-full truncate flex items-center gap-2">
             <span className="w-2 h-2 rounded-full bg-[var(--pass)] animate-pulse shadow-[0_0_8px_var(--pass)]" />
             All zones nominal — Glasses feed monitoring 4 workers
          </p>
        )}
      </div>
      
      <div className="grid grid-cols-1 lg:grid-cols-3 xl:grid-cols-4 gap-4 flex-1 min-h-[500px]">
        {/* Main Map Area */}
        <div className="lg:col-span-2 xl:col-span-2 flex flex-col xl:border-r border-[var(--border-subtle)] xl:pr-4">
          <LiveSiteMap />
        </div>
        
        {/* Right Sidebar Columns */}
        <div className="flex flex-col gap-4 xl:col-span-1 xl:border-r border-[var(--border-subtle)] xl:pr-4">
          <div className="flex-1 min-h-[250px]">
            <ActiveIssuesPanel />
          </div>
        </div>
        
        <div className="flex flex-col gap-4 xl:col-span-1">
          <div className="flex-1 min-h-[250px]">
            <PredictedRFIPanel />
          </div>
        </div>
      </div>
    </div>
  );
}
