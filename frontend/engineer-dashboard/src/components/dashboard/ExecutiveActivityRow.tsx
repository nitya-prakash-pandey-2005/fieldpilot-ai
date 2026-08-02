"use client";

import React, { useEffect, useState } from 'react';
import { GlassCard } from '../ui/GlassCard';
import { LiveIndicator } from '../ui/LiveIndicator';
import { Download } from 'lucide-react';

import { apiBase } from '@/lib/api';
const API = apiBase();

// Real per-agent operational status from GET /api/v1/health/agents
// (actually tests Postgres/Neo4j/Qdrant/Groq connectivity — see
// api/routes/health.py). Previously this whole panel showed 10 permanently
// hardcoded "activity volume" numbers with a comment admitting they were
// never fetched from anywhere.
const AGENT_LABELS: Record<string, string> = {
  vision: "Agent 1 · Vision",
  measurement: "Agent 2 · Measurement",
  drawing: "Agent 3 · Drawing",
  knowledge_graph: "Agent 4 · Knowledge Graph",
  compliance: "Agent 5 · Compliance",
  predictive_rfi: "Agent 6 · Predictive RFI",
  memory: "Agent 7 · Memory",
  version_control: "Agent 8 · Version Control",
  notification: "Agent 9 · Notification",
  learning: "Agent 10 · Learning",
};

const DEMO_INCIDENTS = [
  { issue: "Rebar Spacing", zone: "A12", deviation: "190mm -> 150mm", resolved_by: "E-Chen", time_hours: 2.5, cost_saved_usd: 12000 },
  { issue: "HVAC Duct Clash", zone: "B3", deviation: "overlap", resolved_by: "T-Wilson", time_hours: 4.1, cost_saved_usd: 45000 },
];

export function ExecutiveActivityRow() {
  const [agentStatus, setAgentStatus] = useState<Record<string, string>>({});
  const [incidents, setIncidents] = useState(DEMO_INCIDENTS);
  const [isLive, setIsLive] = useState(false);

  useEffect(() => {
    fetch(`${API}/api/v1/health/agents`)
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(data => setAgentStatus(data.agents || {}))
      .catch(() => setAgentStatus({}));

    fetch(`${API}/api/v1/learning/recent-incidents?limit=10`)
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(data => {
        if (data.data?.length > 0) {
          setIncidents(data.data);
          setIsLive(true);
        }
      })
      .catch(() => setIsLive(false));
  }, []);

  const handleExport = async () => {
    try {
      const res = await fetch(`${API}/api/v1/learning/export-dataset`);
      if (!res.ok) throw new Error();
      const text = await res.text();
      const blob = new Blob([text], { type: 'application/jsonl' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `fieldpilot-training-dataset-${new Date().toISOString().slice(0, 10)}.jsonl`;
      link.click();
      URL.revokeObjectURL(url);
    } catch {
      // Real endpoint unreachable — no fake download
    }
  };

  const agentEntries = Object.entries(agentStatus);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 w-full mt-6">

      {/* AGENT STATUS */}
      <GlassCard className="p-6 flex flex-col h-[400px]">
        <div className="flex items-center gap-2 mb-4">
          <h3 className="text-sm font-semibold tracking-wide text-[var(--text-primary)] uppercase">Agent Status</h3>
          <LiveIndicator isLive={agentEntries.length > 0} />
        </div>
        <p className="text-[10px] text-[var(--text-muted)] font-mono mb-4 border-b border-[var(--border-subtle)] pb-2">Live connectivity to each agent's backing service</p>

        <div className="flex-1 overflow-y-auto pr-2 space-y-2">
          {agentEntries.length === 0 && (
            <div className="text-xs text-[var(--text-muted)] italic">Checking agent status…</div>
          )}
          {agentEntries.map(([key, status]) => (
            <div key={key} className="flex items-center justify-between text-sm px-3 py-2 rounded-lg bg-[var(--bg-elevated)]">
              <span className="text-[var(--text-secondary)] text-xs">{AGENT_LABELS[key] || key}</span>
              <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full ${
                status === 'operational' ? 'bg-[var(--pass-dim)] text-[var(--pass)]' : 'bg-[var(--fail-dim)] text-[var(--fail)]'
              }`}>
                {status}
              </span>
            </div>
          ))}
        </div>
      </GlassCard>

      {/* RECENT RESOLVED INCIDENTS */}
      <GlassCard className="p-6 flex flex-col h-[400px]">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold tracking-wide text-[var(--text-primary)] uppercase">Recent Resolved Incidents</h3>
            <LiveIndicator isLive={isLive} />
          </div>
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
                <th className="py-3 px-2 font-normal">Resolved By</th>
                <th className="py-3 px-2 font-normal text-right">Time</th>
                <th className="py-3 px-2 font-normal text-right">Cost Saved</th>
              </tr>
            </thead>
            <tbody className="text-[var(--text-secondary)]">
              {incidents.map((inc: any, i: number) => (
                <tr key={i} className="border-b border-[var(--border-subtle)] hover:bg-[var(--bg-hover)] transition-colors cursor-default">
                  <td className="py-3 px-2 font-medium text-[var(--text-primary)]">{inc.issue}</td>
                  <td className="py-3 px-2"><span className="bg-[var(--bg-elevated)] px-1.5 py-0.5 rounded font-mono text-[var(--cyan)] border border-[var(--cyan)]/20">{inc.zone}</span></td>
                  <td className="py-3 px-2 opacity-80">{inc.resolved_by}</td>
                  <td className="py-3 px-2 text-right font-mono">{inc.time_hours}h</td>
                  <td className="py-3 px-2 text-right font-mono text-[var(--pass)] font-bold">${Number(inc.cost_saved_usd).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassCard>

    </div>
  );
}
