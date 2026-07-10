"use client";

import { PredictedRFIPanel } from '@/components/PredictedRFIPanel';
import { ActiveIssuesPanel } from '@/components/ActiveIssuesPanel';
import LiveSiteMap from '@/components/LiveSiteMap';
import KPIBar from '@/components/KPIBar';
import VoiceSearchBar from '@/components/VoiceSearchBar';
import { ThemeToggle } from '@/components/ThemeToggle';
import { Activity } from 'lucide-react';
import { useRealtimeUpdates } from '@/hooks/useWebSocket';

export default function Dashboard() {
  const { connected, lastEvent } = useRealtimeUpdates('P-001');

  return (
    <div className="flex-1 flex flex-col min-h-screen bg-atw-bg text-white">
      {/* Top Header */}
      <header className="h-16 border-b border-atw-border bg-atw-surface/50 backdrop-blur-md flex items-center justify-between px-6 sticky top-0 z-10">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded bg-atw-cyan/20 flex items-center justify-center border border-atw-cyan/50">
            <Activity className="text-atw-cyan" size={18} />
          </div>
          <div>
            <h1 className="text-lg font-semibold tracking-wide">ASK THE WALL <span className="text-white/50 text-sm font-normal">| COMMAND CENTER</span></h1>
          </div>
        </div>
        
        <div className="flex-1 flex justify-center">
          <VoiceSearchBar />
        </div>
        
        <div className="flex gap-4 items-center">
          <ThemeToggle />
          <div className={`border px-3 py-1.5 rounded-lg flex items-center gap-2 transition-colors duration-300 ${connected ? 'bg-atw-green/10 border-atw-green/20' : 'bg-atw-amber/10 border-atw-amber/20'}`}>
            <div className={`w-2 h-2 rounded-full ${connected ? 'bg-atw-green animate-pulse' : 'bg-atw-amber'}`}></div>
            <span className={`text-sm font-medium tracking-wide ${connected ? 'text-atw-green' : 'text-atw-amber'}`}>
              {connected ? 'System is live' : 'Reconnecting...'}
            </span>
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <div className="flex-1 p-6 overflow-y-auto">
        
        {/* KPI Row (Phase 1 wiring) */}
        <div className="mb-6">
          <KPIBar />
        </div>

        {/* Dashboard Grid */}
        <div className="grid grid-cols-12 gap-6 h-[650px]">
          
          {/* Live Site Map */}
          <div className="col-span-7 h-full flex flex-col">
            <LiveSiteMap lastEvent={lastEvent} />
          </div>

          {/* Side Panels */}
          <div className="col-span-5 flex flex-col gap-6 h-full">
            <div className="flex-1 min-h-0 bg-atw-surface/40 backdrop-blur-md border border-white/10 rounded-xl overflow-hidden shadow-2xl">
              <ActiveIssuesPanel lastEvent={lastEvent} />
            </div>
            <div className="flex-1 min-h-0 bg-atw-surface/40 backdrop-blur-md border border-white/10 rounded-xl overflow-hidden shadow-2xl">
              <PredictedRFIPanel />
            </div>
          </div>
          
        </div>
      </div>
    </div>
  );
}
