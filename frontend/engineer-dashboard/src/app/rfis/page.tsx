"use client";
import React, { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { BrainCircuit, Info, Search, FileText, ArrowRight, Eye, Sparkles, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { mockRFIs } from '@/data/mockData';
import { useZones } from '@/hooks/useZones';
import { LiveIndicator } from '@/components/ui/LiveIndicator';
import { DraftRFIModal } from '@/components/dashboard/DraftRFIModal';

import { apiBase } from '@/lib/api';
const API = apiBase();

// Real predictions come from POST /api/v1/rfi/predict (agents/predictive_rfi/
// predictor.py — real Neo4j historical-RFI query + LLM prediction), called
// once per active zone. Previously this page rendered mockRFIs directly
// with no backend call at all, and the home page's PredictedRFIPanel called
// a DIFFERENT stub endpoint (/api/v1/planning/predictions) that always
// returns the same single hardcoded prediction.
async function fetchRealPredictions(zones: { zone_code: string; current_activity: string }[]) {
  const results = await Promise.allSettled(
    zones.map(z =>
      fetch(`${API}/api/v1/rfi/predict`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: 'default-project',
          zone_id: z.zone_code,
          current_activity: {
            work_type: z.current_activity || 'general construction',
            drawing_refs: [],
            scheduled_completion: new Date(Date.now() + 14 * 86400_000).toISOString().slice(0, 10),
          },
        }),
      }).then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
    )
  );

  const rfis: any[] = [];
  for (const r of results) {
    if (r.status === 'fulfilled') {
      const predicted = r.value?.prediction?.predicted_rfis || [];
      const zoneId = r.value.prediction.zone_id;
      for (const [idx, p] of predicted.entries()) {
        rfis.push({
          id: p.prediction_id || `pred-${zoneId}-${idx}`,
          // Zone + array index makes this collision-proof for the React key
          // even if two zones' predictions land on the same prediction_id
          // (e.g. both fall back to the same mock, or the LLM hallucinates
          // the same id for different zones).
          key: `${zoneId}-${p.prediction_id || idx}-${rfis.length}`,
          zone_id: zoneId,
          rfi_category: p.rfi_category,
          probability: p.probability,
          basis: p.basis,
          recommended_pre_action: p.recommended_pre_action,
          drawing_sections_to_clarify: p.drawing_sections_to_clarify || [],
        });
      }
    }
  }
  return rfis;
}

export default function RFIsPage() {
  const router = useRouter();
  const { zones } = useZones('default-project');
  const [selectedRFI, setSelectedRFI] = useState<any>(null);
  const [rfis, setRfis] = useState<any[]>(mockRFIs);
  const [isLive, setIsLive] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [search, setSearch] = useState('');

  const refresh = useCallback(async () => {
    if (zones.length === 0) return;
    setIsRefreshing(true);
    try {
      const real = await fetchRealPredictions(zones.map(z => ({ zone_code: z.zone_code, current_activity: z.current_activity })));
      if (real.length > 0) {
        setRfis(real);
        setIsLive(true);
        toast.success(`${real.length} prediction(s) refreshed from Agent 6`);
      } else {
        toast.error('No predictions returned — showing demo data');
      }
    } catch (err) {
      toast.error('Prediction request failed — showing demo data');
    } finally {
      setIsRefreshing(false);
    }
  }, [zones]);

  useEffect(() => { refresh(); }, [refresh]);

  const filteredRfis = rfis.filter(r =>
    !search || r.rfi_category.toLowerCase().includes(search.toLowerCase()) || r.zone_id.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="h-full p-8 flex flex-col min-h-0 bg-[var(--bg-base)]">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold text-[var(--text-primary)] tracking-tight flex items-center gap-3">
            <BrainCircuit className="text-[var(--purple)]" size={32} />
            Predicted RFIs
            <LiveIndicator isLive={isLive} />
          </h1>
          <p className="text-[var(--text-secondary)] mt-2">AI-driven predictive issue generation based on historical patterns and current site trajectory.</p>
        </div>

        <div className="flex gap-4 items-center">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-[var(--text-muted)]" size={16} />
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search predictions..."
              className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-lg pl-10 pr-4 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--purple)]/50 transition-colors"
            />
          </div>
          <button
            disabled={isRefreshing}
            className="bg-[var(--purple-dim)] hover:opacity-90 text-[var(--purple)] border border-[var(--purple)]/30 px-4 py-2 rounded-lg font-semibold flex items-center gap-2 transition-all cursor-pointer disabled:opacity-50"
            onClick={refresh}
          >
            {isRefreshing ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
            {isRefreshing ? 'Analyzing…' : 'Refresh Analysis'}
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto min-h-0">
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6 pb-10">
          {filteredRfis.map((rfi) => (
            <div key={rfi.key || rfi.id} className="bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-xl flex flex-col shadow-2xl relative overflow-hidden group hover:border-[var(--purple)]/40 transition-colors">
              <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-[var(--purple)] via-[var(--cyan)] to-transparent opacity-70"></div>

              <div className="p-6 border-b border-[var(--border-subtle)] flex justify-between items-start">
                <div>
                  <div className="flex items-center gap-3 mb-2">
                    <span className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-[var(--text-secondary)] px-2 py-0.5 rounded text-xs font-mono font-bold tracking-wider">
                      ZONE {rfi.zone_id}
                    </span>
                    <span className="text-sm font-semibold text-[var(--purple)] bg-[var(--purple-dim)] px-2 py-0.5 rounded uppercase tracking-wider border border-[var(--purple)]/20">
                      {rfi.rfi_category.replace(/_/g, ' ')}
                    </span>
                  </div>
                  <h3 className="text-[var(--text-primary)] text-xl font-bold mt-3">High Probability: {rfi.rfi_category.replace(/_/g, ' ')}</h3>
                </div>
                <div className="flex flex-col items-end">
                  <div className="text-3xl font-bold font-mono text-[var(--text-primary)] tracking-tighter">
                    {Math.round(rfi.probability * 100)}<span className="text-[var(--purple)] text-xl">%</span>
                  </div>
                  <span className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] font-bold">Probability</span>
                </div>
              </div>

              <div className="p-6 flex-1 flex flex-col gap-6">
                <div>
                  <h4 className="text-xs uppercase tracking-widest text-[var(--text-muted)] mb-2 font-bold flex items-center gap-2">
                    <Info size={14} className="text-[var(--cyan)]" /> Basis of Prediction
                  </h4>
                  <p className="text-[var(--text-secondary)] text-sm leading-relaxed bg-[var(--bg-elevated)] p-4 rounded-lg border border-[var(--border-subtle)]">
                    {rfi.basis}
                  </p>
                </div>

                <div>
                  <h4 className="text-xs uppercase tracking-widest text-[var(--text-muted)] mb-2 font-bold flex items-center gap-2">
                    <BrainCircuit size={14} className="text-[var(--purple)]" /> Recommended Action
                  </h4>
                  <div className="bg-[var(--purple-dim)] border border-[var(--purple)]/20 rounded-lg p-4 text-[var(--purple)] text-sm leading-relaxed relative overflow-hidden">
                    <div className="absolute top-0 right-0 w-24 h-24 bg-[var(--purple)]/20 blur-2xl rounded-full"></div>
                    {rfi.recommended_pre_action}
                  </div>
                </div>

                <div>
                  <h4 className="text-xs uppercase tracking-widest text-[var(--text-muted)] mb-2 font-bold">Related Documents</h4>
                  <div className="flex gap-2 flex-wrap">
                    {rfi.drawing_sections_to_clarify.map((doc: string, i: number) => (
                      <span key={i} className="text-xs bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-[var(--text-secondary)] px-3 py-1.5 rounded-full flex items-center gap-2">
                        <FileText size={12} /> {doc}
                      </span>
                    ))}
                  </div>
                </div>
              </div>

              <div className="p-4 border-t border-[var(--border-subtle)] bg-[var(--bg-elevated)] flex gap-4">
                <button
                  onClick={() => router.push(`/memory?q=${encodeURIComponent(rfi.rfi_category.replace(/_/g, ' '))}`)}
                  className="flex-1 bg-[var(--bg-surface)] hover:bg-[var(--bg-hover)] text-[var(--text-primary)] font-semibold py-3 rounded-lg transition-colors border border-[var(--border-subtle)] flex items-center justify-center gap-2 cursor-pointer text-sm"
                >
                  <Eye size={16} /> View Similar Historical RFIs
                </button>
                <button
                  onClick={() => setSelectedRFI(rfi)}
                  className="flex-1 bg-[var(--purple)] hover:opacity-90 text-white font-semibold py-3 rounded-lg transition-colors flex items-center justify-center gap-2 cursor-pointer text-sm shadow-[0_0_15px_rgba(123,97,255,0.3)]"
                >
                  Draft Clarification <ArrowRight size={16} />
                </button>
              </div>
            </div>
          ))}

          {filteredRfis.length === 0 && (
            <div className="col-span-full py-20 text-center text-[var(--text-muted)]">
              No predictions match your search.
            </div>
          )}
        </div>
      </div>

      <DraftRFIModal
        isOpen={selectedRFI !== null}
        onClose={() => setSelectedRFI(null)}
        rfiId={selectedRFI?.id}
        title={selectedRFI?.rfi_category}
        zone={selectedRFI?.zone_id}
      />
    </div>
  );
}
