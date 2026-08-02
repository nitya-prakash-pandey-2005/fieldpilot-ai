"use client";
import { useState, useEffect, useCallback, useMemo } from 'react';
import { Network, Database, Map, AlertTriangle, Users, RefreshCw, Search, Info, Wrench, Box } from 'lucide-react';
import { LiveIndicator } from '@/components/ui/LiveIndicator';
import { GlassCard } from '@/components/ui/GlassCard';
import { GraphCanvas, GraphNode } from '@/components/graph/GraphCanvas';
import { SEVERITY } from '@/theme/severityColors';

import { apiBase } from '@/lib/api';
const API = apiBase();
const POLL_INTERVAL_MS = 20_000;

// Real payload from GET /api/v1/graph/full (api/routes/knowledge_graph.py)
// — Postgres Project/Zone/Issue nodes (always populated) merged with the
// real Neo4j Incident/Engineer subgraph that agents/learning/ingestor.py
// writes whenever POST /api/v1/learning/resolve fires. Previously this page
// was a one-level-at-a-time click-through with no legend, no search, and no
// visual sense of the graph shape at all.
interface GraphEdgeRow { source: string; target: string; type: string; }
interface GraphMeta {
  neo4j_available: boolean;
  zone_count: number;
  issue_count: number;
  incident_count: number;
  asset_count?: number;
}

const TYPE_META: Record<string, { icon: typeof Database; label: string; color: string }> = {
  project: { icon: Database, label: 'Project', color: 'var(--cyan)' },
  zone: { icon: Map, label: 'Zone', color: 'var(--text-secondary)' },
  issue: { icon: AlertTriangle, label: 'Issue', color: 'var(--fail)' },
  incident: { icon: Wrench, label: 'Resolved Incident', color: 'var(--purple)' },
  asset: { icon: Box, label: 'Inspected Asset', color: 'var(--pass)' },
  engineer: { icon: Users, label: 'Engineer', color: 'var(--text-muted)' },
};

const TYPE_ORDER = ['all', 'project', 'zone', 'issue', 'incident', 'asset', 'engineer'] as const;

function riskColor(level?: string) {
  if (level === 'critical') return 'var(--fail)';
  if (level === 'elevated') return 'var(--amber)';
  return 'var(--pass)';
}

function inspectionColor(result?: string) {
  if (result === 'FAIL') return 'var(--fail)';
  if (result === 'UNCERTAIN') return 'var(--amber)';
  if (result === 'PASS') return 'var(--pass)';
  return 'var(--text-muted)';
}

function colorForNode(node: GraphNode): string {
  switch (node.type) {
    case 'project': return 'var(--cyan)';
    case 'zone': return riskColor(node.risk_level);
    case 'issue': return SEVERITY[node.severity as keyof typeof SEVERITY]?.badge_text || 'var(--fail)';
    case 'incident': return node.resolved ? 'var(--pass)' : 'var(--amber)';
    case 'asset': return inspectionColor(node.latest_inspection_result);
    case 'engineer': return 'var(--purple)';
    default: return 'var(--text-muted)';
  }
}

export default function GraphPage() {
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdgeRow[]>([]);
  const [meta, setMeta] = useState<GraphMeta | null>(null);
  const [isLive, setIsLive] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState<(typeof TYPE_ORDER)[number]>('all');

  const load = useCallback(async (showSpinner: boolean) => {
    if (showSpinner) setIsRefreshing(true);
    try {
      const res = await fetch(`${API}/api/v1/graph/full?project_id=default-project`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (data?.data) {
        setNodes(data.data.nodes || []);
        setEdges(data.data.edges || []);
        setMeta(data.data.meta || null);
        setIsLive(true);
      }
    } catch {
      setIsLive(false);
    } finally {
      if (showSpinner) setIsRefreshing(false);
    }
  }, []);

  useEffect(() => {
    load(false);
    const interval = setInterval(() => load(false), POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [load]);

  const highlightIds = useMemo(() => {
    if (!search && typeFilter === 'all') return null;
    const set = new Set<string>();
    nodes.forEach(n => {
      const matchesType = typeFilter === 'all' || n.type === typeFilter;
      const matchesSearch = !search
        || n.label.toLowerCase().includes(search.toLowerCase())
        || (n.zone_code || '').toLowerCase().includes(search.toLowerCase());
      if (matchesType && matchesSearch) set.add(n.id);
    });
    return set;
  }, [nodes, search, typeFilter]);

  const typeCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    nodes.forEach(n => { counts[n.type] = (counts[n.type] || 0) + 1; });
    return counts;
  }, [nodes]);

  return (
    <div className="h-full p-8 flex flex-col min-h-0 bg-[var(--bg-base)]">
      <div className="flex items-center justify-between mb-6 flex-wrap gap-4">
        <div>
          <h1 className="text-3xl font-bold text-[var(--text-primary)] tracking-tight flex items-center gap-3">
            <Network className="text-[var(--pass)]" size={32} />
            Knowledge Graph
            <LiveIndicator isLive={isLive} />
          </h1>
          <p className="text-[var(--text-secondary)] mt-2">
            Real Project → Zone → Issue graph from Postgres, merged with the real resolved-incident graph Agent 10 writes to Neo4j.
          </p>
        </div>
        <button
          disabled={isRefreshing}
          className="bg-[var(--bg-elevated)] hover:bg-[var(--bg-hover)] text-[var(--text-secondary)] border border-[var(--border-subtle)] px-4 py-2 rounded-lg font-semibold flex items-center gap-2 transition-all cursor-pointer disabled:opacity-50"
          onClick={() => load(true)}
        >
          <RefreshCw size={16} className={isRefreshing ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
        <GlassCard className="p-4" accentColor="var(--cyan)">
          <div className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] font-bold mb-1">Zones</div>
          <div className="text-2xl font-bold font-mono text-[var(--text-primary)]">{meta?.zone_count ?? '—'}</div>
        </GlassCard>
        <GlassCard className="p-4" accentColor="var(--fail)">
          <div className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] font-bold mb-1">Tracked Issues</div>
          <div className="text-2xl font-bold font-mono text-[var(--text-primary)]">{meta?.issue_count ?? '—'}</div>
        </GlassCard>
        <GlassCard className="p-4" accentColor="var(--pass)">
          <div className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] font-bold mb-1">Inspected Assets</div>
          <div className="text-2xl font-bold font-mono text-[var(--text-primary)]">{meta?.asset_count ?? '—'}</div>
        </GlassCard>
        <GlassCard className="p-4" accentColor="var(--purple)">
          <div className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] font-bold mb-1">Resolved Incidents</div>
          <div className="text-2xl font-bold font-mono text-[var(--text-primary)]">{meta?.incident_count ?? '—'}</div>
        </GlassCard>
        <GlassCard className="p-4" accentColor={meta?.neo4j_available ? 'var(--pass)' : 'var(--text-muted)'}>
          <div className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] font-bold mb-1">Neo4j Graph Store</div>
          <div className="text-sm font-bold" style={{ color: meta?.neo4j_available ? 'var(--pass)' : 'var(--text-muted)' }}>
            {meta ? (meta.neo4j_available ? 'Connected' : 'Unavailable') : '—'}
          </div>
        </GlassCard>
      </div>

      <div className="flex-1 grid grid-cols-1 xl:grid-cols-[1fr_320px] gap-6 min-h-0">
        <div className="flex flex-col min-h-0 gap-3">
          <div className="flex items-center gap-3 flex-wrap">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-[var(--text-muted)]" size={16} />
              <input
                type="text"
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="Search nodes…"
                className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-lg pl-10 pr-4 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--cyan)]/50 transition-colors w-64"
              />
            </div>
            <div className="flex gap-1.5 flex-wrap">
              {TYPE_ORDER.map(t => (
                <button
                  key={t}
                  onClick={() => setTypeFilter(t)}
                  className={`text-xs font-bold uppercase tracking-wider px-3 py-1.5 rounded-full border transition-colors cursor-pointer ${
                    typeFilter === t
                      ? 'bg-[var(--cyan-dim)] border-[var(--cyan)]/40 text-[var(--cyan)]'
                      : 'bg-[var(--bg-elevated)] border-[var(--border-subtle)] text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
                  }`}
                >
                  {t === 'all' ? `All (${nodes.length})` : `${TYPE_META[t]?.label || t} (${typeCounts[t] || 0})`}
                </button>
              ))}
            </div>
          </div>

          <div className="flex-1 bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-xl relative shadow-2xl overflow-hidden min-h-0">
            <div className="absolute inset-0 opacity-[0.03] bg-[linear-gradient(rgba(255,255,255,1)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,1)_1px,transparent_1px)] bg-[size:40px_40px] pointer-events-none" />
            {nodes.length > 0 ? (
              <GraphCanvas
                nodes={nodes}
                edges={edges}
                onSelect={setSelected}
                selectedId={selected?.id || null}
                highlightIds={highlightIds}
                colorFor={colorForNode}
              />
            ) : (
              <div className="w-full h-full flex items-center justify-center text-[var(--text-muted)] text-sm">
                {isLive ? 'No graph data yet.' : 'Loading graph…'}
              </div>
            )}

            <div className="absolute bottom-4 left-4 bg-[var(--bg-elevated)]/90 backdrop-blur border border-[var(--border-subtle)] rounded-lg p-3 flex flex-col gap-1.5 text-[11px] pointer-events-none">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: 'var(--cyan)' }} />
                <span className="text-[var(--text-secondary)]">Project</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: 'var(--pass)' }} />
                <span className="text-[var(--text-secondary)]">Zone (normal) / Incident (resolved)</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: 'var(--amber)' }} />
                <span className="text-[var(--text-secondary)]">Zone (elevated) / Incident (open)</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: 'var(--fail)' }} />
                <span className="text-[var(--text-secondary)]">Zone (critical) / Issue / Asset (last inspection FAIL)</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: 'var(--purple)' }} />
                <span className="text-[var(--text-secondary)]">Engineer</span>
              </div>
              <div className="text-[var(--text-muted)] italic mt-1 border-t border-[var(--border-subtle)] pt-1.5">
                Drag nodes · scroll to zoom · drag background to pan
              </div>
            </div>

            {meta && !meta.neo4j_available && (
              <div className="absolute top-4 right-4 bg-[var(--amber-dim)] border border-[var(--amber)]/30 text-[var(--amber)] text-[11px] font-semibold px-3 py-1.5 rounded-lg flex items-center gap-2 max-w-xs text-right">
                <Info size={12} className="shrink-0" /> Neo4j unreachable — showing Postgres zone/issue data only
              </div>
            )}
            {meta && meta.neo4j_available && meta.incident_count === 0 && (
              <div className="absolute top-4 right-4 bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-[var(--text-muted)] text-[11px] font-semibold px-3 py-1.5 rounded-lg flex items-center gap-2 max-w-xs text-right">
                <Info size={12} className="shrink-0" /> No resolved incidents graphed yet — resolve one via the Learning Agent to see it appear here
              </div>
            )}
          </div>
        </div>

        <div className="overflow-y-auto min-h-0">
          <GlassCard className="p-5 h-full">
            <h3 className="text-xs font-bold uppercase tracking-widest text-[var(--text-primary)] mb-4 flex items-center gap-2">
              <Info size={14} className="text-[var(--text-muted)]" /> Node Details
            </h3>
            {!selected ? (
              <p className="text-sm text-[var(--text-muted)] italic">Click a node in the graph to inspect its real properties.</p>
            ) : (
              <div className="space-y-3">
                <div className="flex items-center gap-2 mb-2">
                  <span className="w-3 h-3 rounded-full shrink-0" style={{ backgroundColor: colorForNode(selected) }} />
                  <span className="text-[10px] uppercase tracking-widest font-bold" style={{ color: colorForNode(selected) }}>
                    {TYPE_META[selected.type]?.label || selected.type}
                  </span>
                </div>
                <h4 className="text-lg font-bold text-[var(--text-primary)] break-words">{selected.label}</h4>
                <div className="flex flex-col gap-2">
                  {Object.entries(selected)
                    .filter(([k]) => !['id', 'type', 'label'].includes(k))
                    .map(([k, v]) => (
                      <div key={k} className="bg-[var(--bg-elevated)] rounded-lg p-2.5">
                        <span className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] block mb-0.5">{k.replace(/_/g, ' ')}</span>
                        <span className="text-[var(--text-primary)] text-sm break-words">{v === null || v === undefined || v === '' ? '—' : String(v)}</span>
                      </div>
                    ))}
                </div>
              </div>
            )}
          </GlassCard>
        </div>
      </div>
    </div>
  );
}
