"use client";

import React, { useCallback, useEffect, useState } from 'react';
import { apiBase } from '@/lib/api';
import { useAuth } from '@/context/AuthContext';

/**
 * RFI draft review dialog (Agent 6).
 *
 * This used to render a hardcoded paragraph — the same text about HVAC
 * ductwork, 6ft lanyards and beam W12x26 no matter which issue was clicked —
 * and its "Send to Procore" button only closed the dialog. Both were claims the
 * system could not back: the draft was unrelated to the detected deviation, and
 * nothing was ever sent anywhere.
 *
 * Now: POST /api/v1/rfi/draft generates the draft from the real deviation and
 * cites specification passages retrieved from the project index. Citations are
 * shown so the engineer can check them, and when retrieval returns nothing the
 * dialog says the governing clause is unconfirmed rather than inventing one.
 * Approval records the RFI in the audit trail and reports honestly that no ERP
 * integration exists.
 */

interface DraftRFIModalProps {
  isOpen: boolean;
  onClose: () => void;
  rfiId: string;
  title: string;
  zone: string;
  /** When the draft originates from a stored FieldIssue, pass its id so the
   *  backend drafts from recorded values rather than the display strings. */
  issueId?: string;
  severity?: string;
  measuredValue?: string | null;
  expectedValue?: string | null;
  deviationPct?: number | null;
}

type Citation = { source: string; excerpt: string };

type Draft = {
  draft_id: string;
  subject: string;
  location: string;
  impact: string;
  body: string;
  citations: Citation[];
  grounded: boolean;
  generator: string;
  warnings: string[];
};

export function DraftRFIModal({
  isOpen, onClose, rfiId, title, zone,
  issueId, severity, measuredValue, expectedValue, deviationPct,
}: DraftRFIModalProps) {
  const { user } = useAuth();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [body, setBody] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitState, setSubmitState] = useState<'idle' | 'sending' | 'done'>('idle');
  const [submitNote, setSubmitNote] = useState<string | null>(null);

  // Zone labels arrive as "Zone A12" from the predictions feed but the backend
  // keys on the bare code.
  const zoneCode = (zone || '').replace(/^zone\s+/i, '').trim();

  const generate = useCallback(async () => {
    setLoading(true);
    setError(null);
    setDraft(null);
    setSubmitState('idle');
    setSubmitNote(null);
    try {
      const res = await fetch(`${apiBase()}/api/v1/rfi/draft`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          issue_id: issueId ?? null,
          zone_id: zoneCode || null,
          title,
          severity: severity ?? null,
          measured_value: measuredValue ?? null,
          expected_value: expectedValue ?? null,
          deviation_pct: deviationPct ?? null,
        }),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json?.detail ?? `HTTP ${res.status}`);
      setDraft(json);
      setBody(json.body ?? '');
    } catch (e: any) {
      setError(e?.message ?? 'Could not generate the draft');
    } finally {
      setLoading(false);
    }
  }, [issueId, zoneCode, title, severity, measuredValue, expectedValue, deviationPct]);

  useEffect(() => { if (isOpen) generate(); }, [isOpen, generate]);

  const approve = async () => {
    if (!draft) return;
    setSubmitState('sending');
    try {
      const res = await fetch(`${apiBase()}/api/v1/rfi/draft/submit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          draft_id: draft.draft_id,
          subject: draft.subject,
          body,
          zone_id: zoneCode || null,
          issue_id: issueId ?? null,
          approved_by: user?.email ?? user?.id ?? null,
        }),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json?.detail ?? `HTTP ${res.status}`);
      setSubmitState('done');
      setSubmitNote(json?.external_delivery?.reason ?? 'Recorded in the audit trail.');
    } catch (e: any) {
      setSubmitState('idle');
      setError(e?.message ?? 'Could not record the RFI');
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
      <div className="bg-[var(--bg-surface)] border border-[var(--border-accent)] rounded-xl w-full max-w-2xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
        <div className="p-4 border-b border-[var(--border-subtle)] flex items-center justify-between bg-black/20 shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            <span className="text-[10px] font-bold bg-[var(--purple-dim)] text-[var(--purple)] px-2 py-0.5 rounded border border-[var(--purple)]/30 uppercase tracking-wider shrink-0">
              Agent 6: RFI Drafter
            </span>
            <h2 className="text-sm font-semibold text-[var(--text-primary)] truncate">
              {draft?.draft_id ?? rfiId}
            </h2>
          </div>
          <button onClick={onClose} className="text-[var(--text-muted)] hover:text-white transition-colors shrink-0">✕</button>
        </div>

        <div className="p-6 flex flex-col gap-4 overflow-y-auto min-h-0">
          {loading && (
            <p className="text-sm text-[var(--text-muted)]">
              Drafting from the recorded deviation and retrieving the governing specification…
            </p>
          )}

          {error && (
            <div className="p-3 rounded border border-[var(--fail)] bg-[var(--fail-dim)]">
              <p className="text-[13px] text-[var(--text-primary)]">{error}</p>
              <button onClick={generate} className="mt-2 text-[11px] font-bold text-[var(--purple)] hover:underline">
                Retry
              </button>
            </div>
          )}

          {draft && (
            <>
              <div>
                <label className="block text-[10px] text-[var(--text-muted)] uppercase tracking-wider mb-1">Subject</label>
                <div className="text-sm text-[var(--text-primary)] font-medium p-2 bg-black/20 rounded border border-[var(--border-subtle)]">
                  {draft.subject}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-[10px] text-[var(--text-muted)] uppercase tracking-wider mb-1">Location</label>
                  <div className="text-sm text-[var(--text-secondary)] p-2 bg-black/20 rounded border border-[var(--border-subtle)]">
                    {draft.location}
                  </div>
                </div>
                <div>
                  <label className="block text-[10px] text-[var(--text-muted)] uppercase tracking-wider mb-1">Impact</label>
                  <div className="text-sm text-[var(--text-primary)] font-bold p-2 bg-black/20 rounded border border-[var(--border-subtle)]">
                    {draft.impact}
                  </div>
                </div>
              </div>

              <div>
                <label className="block text-[10px] text-[var(--text-muted)] uppercase tracking-wider mb-1">
                  Question / deviation — editable before you approve
                </label>
                <textarea
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  rows={12}
                  className="w-full text-[13px] text-[var(--text-secondary)] p-3 bg-black/20 rounded border border-[var(--border-subtle)] font-mono leading-relaxed resize-y focus:outline-none focus:border-[var(--purple)]"
                />
              </div>

              <div>
                <label className="block text-[10px] text-[var(--text-muted)] uppercase tracking-wider mb-1.5">
                  Specification basis {draft.grounded ? `(${draft.citations.length} retrieved)` : ''}
                </label>
                {draft.citations.length === 0 ? (
                  <p className="text-[12px] text-[var(--amber)] p-2.5 bg-black/20 rounded border border-[var(--amber)]/40">
                    No specification passage matched this item, so this draft cites none.
                    Confirm the governing clause before issuing.
                  </p>
                ) : (
                  <div className="flex flex-col gap-2">
                    {draft.citations.map((c, i) => (
                      <div key={i} className="p-2.5 bg-black/20 rounded border border-[var(--border-subtle)]">
                        <p className="text-[10px] font-mono text-[var(--cyan)] mb-1">{c.source}</p>
                        <p className="text-[11.5px] text-[var(--text-muted)] leading-relaxed">{c.excerpt}</p>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {draft.warnings.length > 0 && (
                <ul className="text-[11px] text-[var(--amber)] list-disc pl-4 space-y-0.5">
                  {draft.warnings.map((w, i) => <li key={i}>{w}</li>)}
                </ul>
              )}

              <p className="text-[10px] font-mono text-[var(--text-muted)]">
                generated by {draft.generator}
              </p>

              {submitState === 'done' && submitNote && (
                <div className="p-3 rounded border border-[var(--pass)] bg-[var(--pass-dim)]">
                  <p className="text-[12px] font-semibold text-[var(--text-primary)] mb-1">
                    RFI {draft.draft_id} recorded
                  </p>
                  <p className="text-[11px] text-[var(--text-secondary)] leading-relaxed">{submitNote}</p>
                </div>
              )}
            </>
          )}
        </div>

        <div className="p-4 border-t border-[var(--border-subtle)] bg-black/20 flex items-center justify-end gap-3 shrink-0">
          <button onClick={onClose} className="px-4 py-2 text-xs font-semibold text-[var(--text-muted)] hover:text-white transition-colors">
            {submitState === 'done' ? 'Close' : 'Cancel'}
          </button>
          <button
            onClick={approve}
            disabled={!draft || submitState !== 'idle'}
            className="px-4 py-2 text-xs font-bold text-black bg-[var(--purple)] hover:bg-[var(--purple-hover)] transition-colors rounded disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {submitState === 'sending' ? 'Recording…' : submitState === 'done' ? 'Recorded' : 'Approve & record'}
          </button>
        </div>
      </div>
    </div>
  );
}
