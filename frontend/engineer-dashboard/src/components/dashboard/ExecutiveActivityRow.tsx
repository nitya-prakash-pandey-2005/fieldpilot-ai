"use client";

import React, { useEffect, useState } from 'react';
import { GlassCard } from '../ui/GlassCard';
import { Download } from 'lucide-react';

const DEMO_AGENTS = [
  { name: "Agent 1 Vision", count: 234, label: "frames analyzed", color: "var(--cyan)" },
  { name: "Agent 2 Measurement", count: 189, label: "measurements taken", color: "var(--purple)" },
  { name: "Agent 3 Drawing", count: 12, label: "drawings parsed", color: "var(--amber)" },
  { name: "Agent 4 Graph", count: 847, label: "queries executed", color: "var(--pass)" },
  { name: "Agent 5 Compliance", count: 312, label: "validations run", color: "var(--fail)" },
  { name: "Agent 6 Predictive", count: 8, label: "RFIs predicted", color: "var(--cyan)" },
  { name: "Agent 7 Memory", count: 67, label: "questions answered", color: "var(--purple)" },
  { name: "Agent 8 Version", count: 23, label: "drawings scanned", color: "var(--amber)" },
  { name: "Agent 9 Notification", count: 41, label: "alerts dispatched", color: "var(--pass)" },
  { name: "Agent 10 Learning", count: 47, label: "incidents learned", color: "var(--cyan)" },
];

const DEMO_INCIDENTS = [
  { issue: "Rebar spacing", zone: "Zone A12", deviation: "+30mm", resolvedBy: "E-Chen", time: "2.5h", saved: "$12,000" },
  { issue: "HVAC duct clash", zone: "Zone B3", deviation: "Overlap", resolvedBy: "T-Wilson", time: "4.1h", saved: "$45,000" },
  { issue: "Fire rating spec", zone: "Zone D4", deviation: "Missing", resolvedBy: "S-Davis", time: "1.2h", saved: "$8,500" },
  { issue: "Embed plate missing", zone: "Zone C7", deviation: "Absent", resolvedBy: "E-Chen", time: "0.8h", saved: "$3,200" },
  { issue: "Water pooling", zone: "Zone A12", deviation: "+45mm", resolvedBy: "M-Hassan", time: "5.5h", saved: "$18,000" }
];

export function ExecutiveActivityRow() {
  const [agents, setAgents] = useState(DEMO_AGENTS);
  const [incidents, setIncidents] = useState(DEMO_INCIDENTS);

  // In a real app we'd fetch from /api/v1/health/agents and /api/v1/learning/stats here
  
  const handleExport = () => {
    // Mock export download
    alert("Downloading JSONL dataset from /api/v1/learning/export-dataset");
  };

  const maxAgentCount = Math.max(...agents.map(a => a.count));

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 w-full mt-6">
      
      {/* AGENT ACTIVITY BREAKDOWN */}
      <GlassCard className="p-6 flex flex-col h-[400px]">
        <h3 className="text-sm font-semibold tracking-wide text-[var(--text-primary)] uppercase mb-4">AGENT ACTIVITY BREAKDOWN</h3>
        <p className="text-[10px] text-[var(--text-muted)] font-mono mb-4 border-b border-[var(--border-subtle)] pb-2">Activity volume per agent this week</p>
        
        <div className="flex-1 overflow-y-auto pr-2 space-y-3">
          {agents.map((agent, i) => (
            <div key={i} className="flex flex-col gap-1 text-sm">
              <div className="flex justify-between items-center text-[11px] font-mono">
                <span className="text-[var(--text-secondary)]">{agent.name}</span>
                <span className="text-[var(--text-muted)]">{agent.count} {agent.label}</span>
              </div>
              <div className="w-full h-1.5 bg-[var(--bg-elevated)] rounded-full overflow-hidden">
                <div 
                  className="h-full rounded-full transition-all duration-1000"
                  style={{ width: `${(agent.count / maxAgentCount) * 100}%`, backgroundColor: agent.color }}
                />
              </div>
            </div>
          ))}
        </div>
      </GlassCard>

      {/* RECENT RESOLVED INCIDENTS */}
      <GlassCard className="p-6 flex flex-col h-[400px]">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold tracking-wide text-[var(--text-primary)] uppercase">RECENT RESOLVED INCIDENTS</h3>
          <button 
            onClick={handleExport}
            className="flex items-center gap-1.5 text-[10px] font-bold bg-[var(--bg-elevated)] border border-[var(--border-subtle)] px-3 py-1.5 rounded hover:bg-[var(--cyan-dim)] hover:border-[var(--cyan)] hover:text-[var(--cyan)] transition-colors uppercase"
          >
            <Download size={12} />
            Export Report
          </button>
        </div>
        
        <div className="flex-1 overflow-y-auto w-full">
          <table className="w-full text-left border-collapse text-[11px]">
            <thead>
              <tr className="border-b border-[var(--border-subtle)] text-[var(--text-muted)] font-mono uppercase tracking-wider">
                <th className="py-3 px-2 font-normal">Issue</th>
                <th className="py-3 px-2 font-normal">Zone</th>
                <th className="py-3 px-2 font-normal">Deviation</th>
                <th className="py-3 px-2 font-normal">Resolved By</th>
                <th className="py-3 px-2 font-normal text-right">Time</th>
                <th className="py-3 px-2 font-normal text-right">Cost Saved</th>
              </tr>
            </thead>
            <tbody className="text-[var(--text-secondary)]">
              {incidents.map((inc, i) => (
                <tr key={i} className="border-b border-[var(--border-subtle)] hover:bg-[var(--bg-hover)] transition-colors cursor-default">
                  <td className="py-3 px-2 font-medium text-[var(--text-primary)]">{inc.issue}</td>
                  <td className="py-3 px-2"><span className="bg-black/30 px-1.5 py-0.5 rounded font-mono text-[var(--cyan)] border border-[var(--cyan)]/20">{inc.zone}</span></td>
                  <td className="py-3 px-2 font-mono text-[var(--fail)] font-semibold">{inc.deviation}</td>
                  <td className="py-3 px-2 opacity-80">{inc.resolvedBy}</td>
                  <td className="py-3 px-2 text-right font-mono">{inc.time}</td>
                  <td className="py-3 px-2 text-right font-mono text-[var(--pass)] font-bold">{inc.saved}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        
        <div className="mt-4 pt-3 border-t border-[var(--border-subtle)] flex items-center justify-center">
          <span className="text-[10px] font-mono text-[var(--cyan)] tracking-wider">
            47 total incidents learned · 141 JSONL pairs ready
          </span>
        </div>
      </GlassCard>

    </div>
  );
}
