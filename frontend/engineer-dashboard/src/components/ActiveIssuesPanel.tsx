"use client";

import { useEffect, useState } from 'react';
import { AlertTriangle, Clock, Camera, FileText } from 'lucide-react';

export function ActiveIssuesPanel({ lastEvent }: { lastEvent?: any }) {
  const [issues, setIssues] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchIssues = async () => {
    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/v1/compliance/issues`);
      const data = await response.json();
      setIssues(data);
    } catch (e) {
      console.error("Failed to fetch issues", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchIssues();
    const interval = setInterval(fetchIssues, 10000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (lastEvent && lastEvent.type === 'COMPLIANCE_FAIL') {
      const newIssue = {
        id: `ws-${Date.now()}`,
        zone_id: lastEvent.zone_id,
        asset_type: lastEvent.asset_id,
        severity: lastEvent.severity,
        deviation_pct: lastEvent.deviation_pct,
        created_at: new Date().toISOString()
      };
      setIssues(prev => [newIssue, ...prev].slice(0, 20));
    }
  }, [lastEvent]);

  return (
    <div className="h-full flex flex-col relative animate-fade-in" style={{ animationDelay: '200ms', animationFillMode: 'both' }}>
      <div className="p-4 border-b border-white/5 bg-gradient-to-r from-atw-red/20 to-transparent flex items-center justify-between">
        <div className="flex items-center gap-2">
          <AlertTriangle className="text-atw-red" size={20} />
          <h2 className="font-semibold tracking-wide text-white/90 uppercase text-sm">Active Issues</h2>
        </div>
        <span className="bg-atw-red/20 text-atw-red text-xs px-2.5 py-1 rounded-full border border-atw-red/30 tracking-wider">
          {issues.length} DETECTED
        </span>
      </div>
      
      <div className="p-5 flex-1 overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center h-32">
            <div className="w-6 h-6 border-2 border-atw-red border-t-transparent rounded-full animate-spin"></div>
          </div>
        ) : issues.length === 0 ? (
          <div className="text-white/40 text-sm text-center py-10">No active issues detected.</div>
        ) : (
          <div className="space-y-4">
            {issues.map(issue => (
              <div key={issue.id} className="bg-black/40 backdrop-blur-md rounded-lg p-4 border border-atw-red/30 group hover:border-atw-red/60 hover:shadow-[0_0_15px_rgba(255,59,59,0.3)] transition-all duration-300 relative overflow-hidden">
                <div className="absolute top-0 left-0 w-1 h-full bg-atw-red animate-pulse-slow"></div>
                
                <div className="flex items-start justify-between mb-3 ml-2">
                  <div className="flex items-center gap-2 text-white/90">
                    <span className="font-bold bg-atw-red text-white text-[10px] px-1.5 py-0.5 rounded tracking-widest">{issue.severity}</span>
                    <span className="font-semibold text-sm">Zone {issue.zone_id} — {issue.asset_type}</span>
                  </div>
                  <div className="flex items-center text-white/40 text-xs">
                    <Clock size={12} className="mr-1" />
                    {new Date(issue.created_at).toLocaleTimeString()}
                  </div>
                </div>
                
                <div className="ml-2 mb-3 bg-atw-red/10 border border-atw-red/20 p-2.5 rounded text-sm text-atw-red/90 leading-relaxed">
                  Deviation of {issue.deviation_pct ? Number(issue.deviation_pct).toFixed(1) : '?'}% detected. Measured: {issue.measured_value}, Expected: {issue.spec_value}. Immediate correction required.
                </div>
                
                <div className="ml-2 flex items-center gap-4 text-xs text-white/50 mb-4">
                  <span className="flex items-center"><span className="text-white/30 mr-1">Worker:</span> {issue.worker_id || "System"}</span>
                  <span className="flex items-center gap-1 cursor-pointer hover:text-atw-cyan transition-colors"><Camera size={14} /> View Photo</span>
                  <span className="flex items-center gap-1 cursor-pointer hover:text-atw-cyan transition-colors"><FileText size={14} /> Report</span>
                </div>
                
                <div className="ml-2 flex gap-3">
                  <button className="flex-1 bg-atw-red/20 hover:bg-atw-red/40 text-atw-red border border-atw-red/30 text-xs py-2 rounded transition-colors uppercase tracking-wider font-semibold">
                    Escalate
                  </button>
                  <button className="flex-1 bg-atw-cyan hover:bg-atw-cyan/80 text-black text-xs py-2 rounded transition-colors uppercase tracking-wider font-semibold">
                    Resolve
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
