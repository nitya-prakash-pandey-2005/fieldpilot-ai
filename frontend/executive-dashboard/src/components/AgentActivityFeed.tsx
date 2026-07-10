"use client";

import { useEffect, useState } from 'react';
import { RadioReceiver, Info, AlertOctagon, Sparkles } from 'lucide-react';

export function AgentActivityFeed() {
  const [activities, setActivities] = useState([
    { id: 1, agent: "Agent 5 (Compliance)", action: "Identified CRITICAL rebar spacing deviation in Zone A12", time: "Just now", type: "alert" },
    { id: 2, agent: "Agent 10 (Learning)", action: "Added incident to Memory Graph. Total cost avoided updated.", time: "2m ago", type: "success" },
    { id: 3, agent: "Agent 9 (Notification)", action: "Dispatched automated WhatsApp alert to Site Superintendent.", time: "3m ago", type: "info" },
    { id: 4, agent: "Agent 2 (Depth)", action: "Processed LiDAR point cloud for Zone B3. No anomalies.", time: "14m ago", type: "info" },
    { id: 5, agent: "Agent 4 (Knowledge Graph)", action: "Updated 14 relationship vectors in Zone C7.", time: "22m ago", type: "info" }
  ]);

  // Simulate incoming activity for demo purposes
  useEffect(() => {
    const timer = setInterval(() => {
      setActivities(prev => {
        const newAct = {
          id: Date.now(),
          agent: "Agent 6 (Predictive RFI)",
          action: "Scanned structural junctions. 0 high-risk nodes detected.",
          time: "Just now",
          type: "info"
        };
        return [newAct, ...prev].slice(0, 8);
      });
    }, 45000);
    return () => clearInterval(timer);
  }, []);

  const getIcon = (type: string) => {
    switch (type) {
      case 'alert': return <AlertOctagon size={14} className="text-atw-red" />;
      case 'success': return <Sparkles size={14} className="text-atw-green" />;
      case 'info': default: return <Info size={14} className="text-atw-cyan" />;
    }
  };

  return (
    <div className="h-full flex flex-col bg-atw-surface/60 backdrop-blur-md rounded-xl border border-white/10 shadow-2xl overflow-hidden relative">
      <div className="p-4 border-b border-white/5 bg-gradient-to-r from-atw-purple/10 to-transparent flex items-center gap-2">
        <RadioReceiver className="text-atw-purple" size={20} />
        <h2 className="font-semibold tracking-wide text-white/90 uppercase text-sm">Agent Activity Feed</h2>
      </div>
      
      <div className="p-4 flex-1 overflow-y-auto space-y-4">
        {activities.map((act) => (
          <div key={act.id} className="flex gap-3 animate-fade-in group">
            <div className="mt-0.5">
              <div className="w-6 h-6 rounded bg-black/40 border border-white/10 flex items-center justify-center">
                {getIcon(act.type)}
              </div>
            </div>
            <div>
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xs font-semibold text-white/80">{act.agent}</span>
                <span className="text-[10px] text-white/40">{act.time}</span>
              </div>
              <p className="text-xs text-white/60 leading-relaxed group-hover:text-white/80 transition-colors">
                {act.action}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
