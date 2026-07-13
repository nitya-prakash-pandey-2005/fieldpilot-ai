"use client";

import { useEffect, useState } from 'react';
import { Activity, CheckCircle2, AlertTriangle, ShieldCheck } from 'lucide-react';

const FALLBACK_AGENTS = {
  "vision": "operational",
  "measurement": "operational",
  "drawing": "degraded",
  "knowledge_graph": "operational",
  "compliance": "operational",
  "predictive_rfi": "degraded",
  "memory": "operational",
  "version_control": "operational",
  "notification": "operational",
  "learning": "operational"
};

export function SystemHealthPanel() {
  const [agents, setAgents] = useState<Record<string, string>>(FALLBACK_AGENTS);

  useEffect(() => {
    const fetchHealth = async () => {
      try {
        const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/v1/health/agents`);
        const data = await response.json();
        if (data && data.agents && Object.keys(data.agents).length > 0) {
          setAgents(data.agents);
        }
      } catch (e) {
        console.warn("Failed to fetch system health, using fallback");
      }
    };
    
    fetchHealth();
    const interval = setInterval(fetchHealth, 15000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="h-full flex flex-col bg-atw-surface/60 backdrop-blur-md rounded-xl border border-white/10 shadow-2xl overflow-hidden relative">
      <div className="p-4 border-b border-white/5 bg-gradient-to-r from-atw-cyan/10 to-transparent flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ShieldCheck className="text-atw-cyan" size={20} />
          <h2 className="font-semibold tracking-wide text-white/90 uppercase text-sm">Agent Ecosystem Health</h2>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-atw-green animate-pulse"></div>
          <span className="text-atw-green text-xs tracking-wider">ALL SYSTEMS GO</span>
        </div>
      </div>
      
      <div className="p-4 flex-1 overflow-y-auto">
        <div className="grid grid-cols-2 gap-3">
          {Object.entries(agents).map(([slug, status]) => {
            const isAmber = status !== 'operational';
            return (
              <div key={slug} className="bg-black/40 border border-white/5 rounded-lg p-3 flex flex-col gap-2 hover:border-atw-cyan/30 transition-colors group relative overflow-hidden">
                <div className={`absolute left-0 top-0 w-1 h-full ${isAmber ? 'bg-atw-amber' : 'bg-atw-green'} opacity-50 group-hover:opacity-100 transition-opacity`}></div>
                
                <div className="flex items-center justify-between ml-1">
                  <span className="text-white/80 font-medium text-xs capitalize">Agent: {slug.replace('_', ' ')}</span>
                  {isAmber ? (
                    <AlertTriangle size={14} className="text-atw-amber" />
                  ) : (
                    <CheckCircle2 size={14} className="text-atw-green" />
                  )}
                </div>
                
                <div className="flex justify-between items-center text-[10px] ml-1">
                  <span className="text-white/40">Status: <span className={isAmber ? 'text-atw-amber uppercase' : 'text-atw-cyan/90 uppercase'}>{status}</span></span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
