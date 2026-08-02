"use client";

import React, { useState, useEffect, useCallback } from 'react';
import { GlassCard } from '../ui/GlassCard';
import { Search, Loader2, Database, Sparkles, AlertTriangle, FileText, BookOpen } from 'lucide-react';
import { useAuth } from '@/context/AuthContext';
import { useZones } from '@/hooks/useZones';

import { apiBase } from '@/lib/api';
const API = apiBase();

const EXAMPLE_QUERIES = [
  'At what height must fall protection be provided?',
  'What PPE is required near rebar work?',
  'Summarize guardrail system requirements',
];

interface Evidence {
  source_type?: string;
  source_id?: string;
  excerpt: string;
  date?: string | null;
  approved_by?: string | null;
  document_url?: string | null;
  page?: number | null;
}

interface MemoryStats {
  collection: string;
  indexed_passages: number;
  llm_configured: boolean;
}

function confidenceColor(c: number) {
  if (c >= 0.7) return 'var(--pass)';
  if (c >= 0.4) return 'var(--amber)';
  return 'var(--fail)';
}

export function MemorySearch({ initialQuery = '' }: { initialQuery?: string }) {
  const { user } = useAuth();
  const { zones } = useZones('default-project');
  const [query, setQuery] = useState(initialQuery);
  const [zoneFilter, setZoneFilter] = useState('all');
  const [isSearching, setIsSearching] = useState(false);
  const [answer, setAnswer] = useState<string | null>(null);
  const [confidence, setConfidence] = useState<number | null>(null);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [caution, setCaution] = useState<string | null>(null);
  const [relatedDrawing, setRelatedDrawing] = useState<string | null>(null);
  const [hasSearched, setHasSearched] = useState(false);
  const [history, setHistory] = useState<string[]>([]);
  const [stats, setStats] = useState<MemoryStats | null>(null);

  useEffect(() => {
    fetch(`${API}/api/v1/memory/stats?project_id=default-project`)
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(data => setStats(data.data || null))
      .catch(() => setStats(null));
  }, []);

  const runSearch = useCallback(async (q: string) => {
    if (!q.trim()) return;
    setIsSearching(true);
    setHasSearched(true);

    try {
      // Real Project Memory Q&A (agents/memory/retriever.py — Qdrant
      // semantic search + LLM synthesis over the same bge-small-en-v1.5
      // embedding model as drawing ingestion). When no LLM is configured,
      // the backend now returns the real retrieved passages with `answer:
      // null` instead of a synthesized narrative — rendered distinctly below.
      const res = await fetch(`${API}/api/v1/memory/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: q,
          project_id: 'default-project',
          zone_id: zoneFilter,
          worker_id: user?.id || 'anonymous',
        }),
      });
      const data = await res.json();
      setAnswer(data.answer ?? null);
      setConfidence(typeof data.confidence === 'number' ? data.confidence : null);
      setEvidence(data.evidence || []);
      setCaution(data.caution ?? null);
      setRelatedDrawing(data.related_drawing ?? null);
      setHistory(prev => [q, ...prev.filter(h => h !== q)].slice(0, 6));
    } catch (err) {
      console.warn('Memory search failed:', err);
      setAnswer(null);
      setConfidence(null);
      setEvidence([]);
      setCaution('Could not reach the project memory service.');
      setRelatedDrawing(null);
    } finally {
      setIsSearching(false);
    }
  }, [zoneFilter, user?.id]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    runSearch(query);
  };

  // Auto-run once if an initial query was passed in (e.g. from the RFIs
  // page's "View Similar Historical RFIs" link).
  useEffect(() => {
    if (initialQuery) runSearch(initialQuery);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex flex-col gap-6 h-full max-w-4xl mx-auto w-full">
      <GlassCard className="p-6">
        <form onSubmit={handleSearch} className="relative">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search project memory (e.g. 'What happened with the rebar on floor 3?')"
            className="w-full bg-[var(--bg-base)] border border-[var(--border-accent)] rounded-lg pl-12 pr-28 py-4 text-lg text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:border-[var(--cyan)] focus:ring-1 focus:ring-[var(--cyan)] transition-all"
          />
          <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" size={24} />
          <button
            type="submit"
            disabled={isSearching}
            className="absolute right-2 top-1/2 -translate-y-1/2 bg-[var(--cyan)] text-[var(--bg-base)] px-4 py-2 rounded-md font-bold text-sm tracking-wide hover:bg-[var(--cyan-glow)] transition-colors disabled:opacity-50"
          >
            {isSearching ? <Loader2 className="animate-spin" size={20} /> : 'SEARCH'}
          </button>
        </form>

        <div className="flex items-center justify-between mt-4 flex-wrap gap-3">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs text-[var(--text-muted)]">Scope:</span>
            <select
              value={zoneFilter}
              onChange={(e) => setZoneFilter(e.target.value)}
              className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-md px-2 py-1 text-xs text-[var(--text-secondary)] focus:outline-none focus:border-[var(--cyan)]/50"
            >
              <option value="all">All Zones</option>
              {zones.map(z => <option key={z.zone_code} value={z.zone_code}>Zone {z.zone_code}</option>)}
            </select>
          </div>

          {stats && (
            <div className="flex items-center gap-3 text-[11px] font-mono text-[var(--text-muted)]">
              <span className="flex items-center gap-1.5">
                <Database size={12} /> {stats.indexed_passages} passages indexed
              </span>
              <span className={`flex items-center gap-1.5 ${stats.llm_configured ? 'text-[var(--pass)]' : 'text-[var(--amber)]'}`}>
                <Sparkles size={12} /> {stats.llm_configured ? 'AI synthesis enabled' : 'Raw retrieval only'}
              </span>
            </div>
          )}
        </div>

        {!hasSearched && (
          <div className="flex flex-wrap gap-2 mt-4">
            {EXAMPLE_QUERIES.map(q => (
              <button
                key={q}
                onClick={() => { setQuery(q); runSearch(q); }}
                className="text-xs bg-[var(--bg-elevated)] hover:bg-[var(--bg-hover)] border border-[var(--border-subtle)] text-[var(--text-secondary)] px-3 py-1.5 rounded-full transition-colors cursor-pointer"
              >
                {q}
              </button>
            ))}
          </div>
        )}

        {history.length > 1 && (
          <div className="flex flex-wrap gap-2 mt-3 border-t border-[var(--border-subtle)] pt-3">
            <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest self-center">Recent:</span>
            {history.slice(1).map(h => (
              <button
                key={h}
                onClick={() => { setQuery(h); runSearch(h); }}
                className="text-[11px] text-[var(--text-muted)] hover:text-[var(--cyan)] underline decoration-dotted cursor-pointer"
              >
                {h}
              </button>
            ))}
          </div>
        )}
      </GlassCard>

      {hasSearched && (
        <div className="flex-1 flex flex-col gap-4 animate-fade-in overflow-y-auto min-h-0 pb-6">
          {isSearching ? (
            <h3 className="text-sm font-semibold tracking-wide text-[var(--text-secondary)] uppercase">Searching project memory…</h3>
          ) : (
            <>
              {caution && (
                <div className="flex items-start gap-2 bg-[var(--amber-dim)] border border-[var(--amber)]/30 text-[var(--amber)] text-sm px-4 py-3 rounded-lg">
                  <AlertTriangle size={16} className="shrink-0 mt-0.5" />
                  <span>{caution}</span>
                </div>
              )}

              {answer ? (
                <GlassCard className="p-5" accentColor="var(--cyan)">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-[10px] font-bold tracking-widest text-[var(--cyan)] uppercase flex items-center gap-1.5">
                      <Sparkles size={12} /> AI Answer
                    </span>
                    {confidence !== null && (
                      <span className="text-xs font-mono text-[var(--text-muted)]">{Math.round(confidence * 100)}% confidence</span>
                    )}
                  </div>
                  <p className="text-[var(--text-primary)] text-base leading-relaxed">{answer}</p>
                  {confidence !== null && (
                    <div className="h-1 rounded-full bg-[var(--bg-elevated)] overflow-hidden mt-3">
                      <div className="h-full rounded-full transition-all" style={{ width: `${Math.round(confidence * 100)}%`, backgroundColor: confidenceColor(confidence) }} />
                    </div>
                  )}
                  {relatedDrawing && (
                    <div className="mt-3 flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
                      <FileText size={12} className="text-[var(--cyan)]" /> Related drawing: <span className="font-mono">{relatedDrawing}</span>
                    </div>
                  )}
                </GlassCard>
              ) : evidence.length > 0 ? (
                <GlassCard className="p-5" accentColor="var(--amber)">
                  <span className="text-[10px] font-bold tracking-widest text-[var(--amber)] uppercase flex items-center gap-1.5">
                    <BookOpen size={12} /> Raw Matches — No AI Synthesis
                  </span>
                  <p className="text-[var(--text-secondary)] text-sm mt-2">
                    These are the real passages project memory found for this query, shown as-is (no LLM available to summarize them into an answer).
                  </p>
                </GlassCard>
              ) : (
                <div className="text-center text-[var(--text-muted)] py-10">
                  {stats && stats.indexed_passages === 0
                    ? 'No documents have been indexed into project memory yet — upload a drawing or spec via the Drawings page first.'
                    : 'No matching passages found — try rephrasing your question.'}
                </div>
              )}

              {evidence.length > 0 && (
                <>
                  <h3 className="text-sm font-semibold tracking-wide text-[var(--text-secondary)] uppercase">
                    {evidence.length} supporting source{evidence.length > 1 ? 's' : ''}
                  </h3>
                  <div className="flex flex-col gap-3">
                    {evidence.map((ev, idx) => (
                      <GlassCard key={idx} className="p-5 flex flex-col gap-2 hover:border-[var(--cyan-dim)] transition-colors">
                        <div className="flex items-center justify-between flex-wrap gap-2">
                          <span className="text-[10px] font-bold tracking-widest text-[var(--cyan)] bg-[var(--cyan-dim)] px-2 py-1 rounded uppercase">
                            {ev.source_type || 'source'}
                          </span>
                          <div className="flex items-center gap-2">
                            {ev.source_id && <span className="text-xs font-mono text-[var(--text-muted)]">{ev.source_id}</span>}
                            {ev.date && <span className="text-xs font-mono text-[var(--text-muted)]">· {ev.date}</span>}
                          </div>
                        </div>
                        <p className="text-[var(--text-primary)] mt-1 text-sm leading-relaxed">{ev.excerpt}</p>
                        {ev.approved_by && (
                          <span className="text-xs text-[var(--text-muted)]">Approved by {ev.approved_by}</span>
                        )}
                      </GlassCard>
                    ))}
                  </div>
                </>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
