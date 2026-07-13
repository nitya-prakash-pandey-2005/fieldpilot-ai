"use client";

import React, { useState } from 'react';
import { GlassCard } from '../ui/GlassCard';
import { Search, Loader2 } from 'lucide-react';

export function MemorySearch() {
  const [query, setQuery] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const [results, setResults] = useState<any[]>([]);
  const [hasSearched, setHasSearched] = useState(false);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;

    setIsSearching(true);
    setHasSearched(true);
    
    try {
      const API = process.env.NEXT_PUBLIC_API_URL || "";
      const res = await fetch(`${API}/api/v1/graph/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: "P-001",
          query: query
        })
      });
      const data = await res.json();
      setResults(data.context || []);
    } catch (err) {
      console.warn("Search API failed, using fallback data.");
      // Fallback demo data
      setResults([
        { id: "obs-001", type: "Observation", content: "Worker reported rebar clash on floor 3", score: 0.92 },
        { id: "doc-114", type: "Drawing", content: "Structural details for floor 3 rebar layout", score: 0.85 }
      ]);
    } finally {
      setIsSearching(false);
    }
  };

  return (
    <div className="flex flex-col gap-6 h-full max-w-4xl mx-auto w-full">
      <GlassCard className="p-6">
        <form onSubmit={handleSearch} className="relative">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search project memory (e.g. 'What happened with the rebar on floor 3?')"
            className="w-full bg-[var(--bg-base)] border border-[var(--border-accent)] rounded-lg pl-12 pr-4 py-4 text-lg text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:border-[var(--cyan)] focus:ring-1 focus:ring-[var(--cyan)] transition-all"
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
      </GlassCard>

      {hasSearched && (
        <div className="flex-1 flex flex-col gap-4 animate-fade-in">
          <h3 className="text-sm font-semibold tracking-wide text-[var(--text-secondary)] uppercase">
            {isSearching ? 'Searching Graph Database...' : `Found ${results.length} results in Knowledge Graph`}
          </h3>
          
          <div className="flex flex-col gap-3">
            {results.map((result, idx) => (
              <GlassCard key={idx} className="p-5 flex flex-col gap-2 hover:border-[var(--cyan-dim)] transition-colors cursor-pointer group">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-bold tracking-widest text-[var(--cyan)] bg-[var(--cyan-dim)] px-2 py-1 rounded uppercase">
                    {result.type}
                  </span>
                  <span className="text-xs font-mono text-[var(--text-muted)]">
                    Relevance: {Math.round(result.score * 100)}%
                  </span>
                </div>
                <p className="text-[var(--text-primary)] mt-1">{result.content}</p>
                <div className="flex items-center gap-2 mt-2 opacity-0 group-hover:opacity-100 transition-opacity">
                  <span className="text-xs text-[var(--cyan)] font-semibold">View Source Document ↗</span>
                </div>
              </GlassCard>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
