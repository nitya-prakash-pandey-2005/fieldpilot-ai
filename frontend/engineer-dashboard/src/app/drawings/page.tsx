"use client";
import { useState, useRef, useEffect, useCallback } from 'react';
import { FileBox, Upload, Search, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { mockDrawings } from '@/data/mockData';
import { LiveIndicator } from '@/components/ui/LiveIndicator';

import { apiBase } from '@/lib/api';
const API = apiBase();

// Real list from GET /api/v1/drawing/list — grouped from actual Qdrant
// chunk payloads written by /parse (agents/drawing/indexer.py), merged
// with real Neo4j Drawing node metadata where the filename matches a
// known drawing number. mockDrawings is only the pre-fetch placeholder
// now, the same pattern rfis/page.tsx uses — previously this table
// rendered mockDrawings unconditionally with no backend call at all.
interface RealDrawing {
  id: string;
  number: string;
  discipline: string;
  latest_revision: string | null;
  latest_date: string | null;
  approved_by: string | null;
  indexed_chunks: number;
  source_file: string;
}

export default function DrawingsPage() {
  const [search, setSearch] = useState('');
  const [uploading, setUploading] = useState(false);
  const [drawings, setDrawings] = useState<RealDrawing[] | typeof mockDrawings>(mockDrawings);
  const [isLive, setIsLive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/v1/drawing/list`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      const rows: RealDrawing[] = json?.data || [];
      if (rows.length > 0) {
        setDrawings(rows);
        setIsLive(true);
      }
      // If nothing's been indexed yet in a fresh project, keep showing the
      // illustrative mock rows rather than an empty table.
    } catch {
      setIsLive(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const filteredDrawings = drawings.filter((d: any) =>
    !search || d.number.toLowerCase().includes(search.toLowerCase()) || d.discipline.toLowerCase().includes(search.toLowerCase())
  );

  const handleUploadClick = () => fileInputRef.current?.click();

  const handleFileSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('is_tabular', 'false');
      const res = await fetch(`${API}/api/v1/drawing/parse`, { method: 'POST', body: formData });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      toast.success(`${file.name}: ${data.indexed_chunks} chunks indexed into project memory`);
      await refresh();
    } catch (err) {
      toast.error('Upload failed — could not reach the drawing parser');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  return (
    <div className="h-full p-8 flex flex-col min-h-0 bg-[var(--bg-base)]">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold text-[var(--text-primary)] tracking-tight flex items-center gap-3">
            <FileBox className="text-[var(--cyan)]" size={32} />
            Drawing Versions
            <LiveIndicator isLive={isLive} />
          </h1>
          <p className="text-[var(--text-secondary)] mt-2">Agent 3 indexes uploaded drawings for RAG retrieval; Agent 8 resolves revisions against real Neo4j drawing records.</p>
        </div>

        <div className="flex gap-4 items-center">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-[var(--text-muted)]" size={16} />
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search drawings..."
              className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-lg pl-10 pr-4 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--cyan)]/50 transition-colors"
            />
          </div>
          <input ref={fileInputRef} type="file" accept=".pdf,.docx,.txt" className="hidden" onChange={handleFileSelected} />
          <button
            disabled={uploading}
            className="bg-[var(--cyan)] hover:opacity-90 text-black px-4 py-2 rounded-lg font-semibold flex items-center gap-2 transition-all cursor-pointer shadow-lg disabled:opacity-50"
            onClick={handleUploadClick}
          >
            {uploading ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />}
            {uploading ? 'Parsing…' : 'Upload New Revision'}
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto min-h-0">
        <div className="bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-xl overflow-hidden shadow-2xl">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-[var(--bg-elevated)] border-b border-[var(--border-subtle)]">
                <th className="p-4 text-xs font-bold text-[var(--text-muted)] uppercase tracking-widest">Drawing No.</th>
                <th className="p-4 text-xs font-bold text-[var(--text-muted)] uppercase tracking-widest">Discipline</th>
                <th className="p-4 text-xs font-bold text-[var(--text-muted)] uppercase tracking-widest">Latest Approved</th>
                <th className="p-4 text-xs font-bold text-[var(--text-muted)] uppercase tracking-widest">Approved By</th>
                <th className="p-4 text-xs font-bold text-[var(--text-muted)] uppercase tracking-widest">RAG Index Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border-subtle)]">
              {filteredDrawings.map((dwg: any) => (
                <tr key={dwg.id} className="hover:bg-[var(--bg-hover)] transition-colors group">
                  <td className="p-4">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded bg-[var(--cyan-dim)] border border-[var(--cyan)]/20 flex items-center justify-center">
                        <FileBox size={14} className="text-[var(--cyan)]" />
                      </div>
                      <span className="font-bold text-[var(--text-primary)] tracking-wider">{dwg.number}</span>
                    </div>
                  </td>
                  <td className="p-4 text-sm text-[var(--text-secondary)]">{dwg.discipline}</td>
                  <td className="p-4">
                    <div className="flex flex-col">
                      <span className="font-mono text-[var(--pass)] font-bold text-lg">{dwg.latest_revision || '—'}</span>
                      <span className="text-xs text-[var(--text-muted)]">{dwg.latest_date || 'Not matched to a graph record'}</span>
                    </div>
                  </td>
                  <td className="p-4 text-sm text-[var(--text-secondary)]">{dwg.approved_by || '—'}</td>
                  <td className="p-4">
                    {dwg.indexed_chunks !== undefined ? (
                      <span className="text-[10px] font-bold tracking-widest uppercase text-[var(--pass)] opacity-80">
                        ✓ {dwg.indexed_chunks} chunks indexed
                      </span>
                    ) : (
                      <span className="text-[10px] font-bold tracking-widest uppercase text-[var(--text-muted)]">Demo data</span>
                    )}
                  </td>
                </tr>
              ))}
              {filteredDrawings.length === 0 && (
                <tr>
                  <td colSpan={5} className="p-8 text-center text-[var(--text-muted)]">No drawings match your search.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
