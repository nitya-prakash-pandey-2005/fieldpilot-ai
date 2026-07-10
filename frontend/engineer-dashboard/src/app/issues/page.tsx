"use client";
import { useState } from 'react';
import { AlertTriangle, Clock, Camera, FileText, CheckCircle, ArrowUpRight, Search, Filter } from 'lucide-react';
import { toast } from 'sonner';
import { mockIssues } from '@/data/mockData';

export default function IssuesPage() { 
  const [issues, setIssues] = useState(mockIssues);
  const [filter, setFilter] = useState('ALL'); // ALL, CRITICAL, HIGH, MEDIUM

  const filteredIssues = issues.filter(i => filter === 'ALL' || i.severity === filter);

  return (
    <div className="h-full p-8 flex flex-col min-h-0 bg-atw-bg">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold text-white tracking-tight flex items-center gap-3">
            <AlertTriangle className="text-atw-red" size={32} />
            Active Field Issues
          </h1>
          <p className="text-white/50 mt-2">Real-time deviations detected by Vision & Measurement Agents.</p>
        </div>
        
        <div className="flex gap-4">
          <div className="bg-black/20 border border-white/10 rounded-lg p-1 flex">
            {['ALL', 'CRITICAL', 'HIGH', 'MEDIUM'].map(f => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`px-4 py-2 rounded-md text-sm font-semibold transition-all ${
                  filter === f 
                    ? 'bg-white/10 text-white shadow-lg' 
                    : 'text-white/40 hover:text-white/80'
                }`}
              >
                {f}
              </button>
            ))}
          </div>
          <button 
            className="bg-atw-cyan/20 hover:bg-atw-cyan/30 text-atw-cyan border border-atw-cyan/30 px-4 py-2 rounded-lg font-semibold flex items-center gap-2 transition-all cursor-pointer"
            onClick={() => toast('Exporting report as PDF...', { icon: <FileText size={16} /> })}
          >
            Export Report
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto min-h-0">
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6 pb-10">
          {filteredIssues.map((issue) => (
            <div key={issue.id} className="bg-[#12121A] border border-white/10 rounded-xl p-6 shadow-2xl relative overflow-hidden group hover:border-atw-red/40 transition-colors">
              <div className={`absolute top-0 left-0 w-full h-1 ${
                issue.severity === 'CRITICAL' ? 'bg-atw-red animate-pulse' : 
                issue.severity === 'HIGH' ? 'bg-orange-500' : 'bg-yellow-500'
              }`}></div>
              
              <div className="flex justify-between items-start mb-4">
                <div>
                  <span className={`text-xs font-bold px-2.5 py-1 rounded-full uppercase tracking-wider ${
                    issue.severity === 'CRITICAL' ? 'bg-atw-red/20 text-atw-red border border-atw-red/30' : 
                    issue.severity === 'HIGH' ? 'bg-orange-500/20 text-orange-500 border border-orange-500/30' : 
                    'bg-yellow-500/20 text-yellow-500 border border-yellow-500/30'
                  }`}>
                    {issue.severity}
                  </span>
                  <h3 className="text-white text-lg font-semibold mt-3">Zone {issue.zone_id} • {issue.asset_type}</h3>
                </div>
                <div className="text-white/40 flex items-center text-xs bg-black/40 px-2 py-1 rounded">
                  <Clock size={12} className="mr-1" />
                  {new Date(issue.created_at).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}
                </div>
              </div>

              <div className="bg-black/30 border border-white/5 rounded-lg p-4 mb-5 text-white/80 text-sm leading-relaxed">
                {issue.description}
              </div>

              <div className="flex items-center justify-between text-xs text-white/50 mb-6 bg-white/5 p-3 rounded-lg">
                <div className="flex flex-col gap-1">
                  <span className="uppercase tracking-wider text-[10px] text-white/30">Deviation</span>
                  <span className="text-white font-mono">{issue.deviation_pct.toFixed(1)}%</span>
                </div>
                <div className="flex flex-col gap-1">
                  <span className="uppercase tracking-wider text-[10px] text-white/30">Measured</span>
                  <span className="text-white font-mono">{issue.measured_value}</span>
                </div>
                <div className="flex flex-col gap-1">
                  <span className="uppercase tracking-wider text-[10px] text-white/30">Expected</span>
                  <span className="text-white font-mono">{issue.spec_value}</span>
                </div>
                <div className="flex flex-col gap-1">
                  <span className="uppercase tracking-wider text-[10px] text-white/30">Worker</span>
                  <span className="text-white font-mono">{issue.worker_id}</span>
                </div>
              </div>

              <div className="flex gap-3">
                <button 
                  onClick={() => toast.success(`Issue in Zone ${issue.zone_id} marked as resolved.`)}
                  className="flex-1 bg-atw-cyan hover:bg-atw-cyan/90 text-black font-semibold py-2.5 rounded-lg transition-colors flex items-center justify-center gap-2 cursor-pointer"
                >
                  <CheckCircle size={16} /> Resolve
                </button>
                <button 
                  onClick={() => toast.error(`Issue escalated to PM. Ticket created.`)}
                  className="flex-1 bg-white/5 hover:bg-white/10 text-white font-semibold py-2.5 rounded-lg transition-colors border border-white/10 flex items-center justify-center gap-2 cursor-pointer"
                >
                  <ArrowUpRight size={16} /> Escalate
                </button>
              </div>
            </div>
          ))}
          {filteredIssues.length === 0 && (
            <div className="col-span-full py-20 text-center text-white/40">
              No issues match the selected filter.
            </div>
          )}
        </div>
      </div>
    </div>
  ); 
}