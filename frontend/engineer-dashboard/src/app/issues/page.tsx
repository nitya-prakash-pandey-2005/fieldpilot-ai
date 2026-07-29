"use client";
import { useState } from 'react';
import { AlertTriangle, Clock, FileText, CheckCircle, ArrowUpRight, Loader2, Download } from 'lucide-react';
import { toast } from 'sonner';
import { useFieldIssues, FieldIssue } from '@/hooks/useFieldIssues';
import { useAuth } from '@/context/AuthContext';
import { SEVERITY } from '@/theme/severityColors';
import IssueDetailPanel from '@/components/issues/IssueDetailPanel';
import { format } from 'date-fns';

function issueTime(dateStr: string): string {
  const d = new Date(dateStr);
  const age = Date.now() - d.getTime();
  if (age < 60_000) return 'just now';
  if (age < 3600_000) return `${Math.floor(age/60000)}m ago`;
  return format(d, 'h:mm aa');
}

export default function IssuesPage() {
  const { issues, setIssues, summary, isLoading, error, newIssueId, resolveIssue, escalateIssue } = useFieldIssues('default-project');
  const { user } = useAuth();
  const [activeFilter, setActiveFilter] = useState('ALL');
  const [selectedIssueId, setSelectedIssueId] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  const [resolveMode, setResolveMode] = useState<string | null>(null);
  const [resolutionNote, setResolutionNote] = useState('');
  const [resolving, setResolving] = useState(false);

  const [escalateMode, setEscalateMode] = useState<string | null>(null);
  const [escalateRole, setEscalateRole] = useState('site_manager');
  const [escalationNote, setEscalationNote] = useState('');
  const [escalating, setEscalating] = useState(false);

  // Filter issues
  const filteredIssues = issues.filter(i =>
    i.status === 'open' && (activeFilter === 'ALL' || i.severity.toLowerCase() === activeFilter.toLowerCase())
  );

  // Enforce sort order
  const SEVERITY_ORDER: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
  const sortedIssues = [...filteredIssues].sort((a, b) => {
    const s = SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity];
    if (s !== 0) return s;
    return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
  });

  const handleExport = async () => {
    setExporting(true);
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000"}/api/v1/projects/default-project/issues/export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ severity_filter: activeFilter, format: 'pdf' })
      });
      if (!res.ok) throw new Error('Export failed');
      const data = await res.json();
      window.open(data.download_url, '_blank');
      toast.success('Report downloaded');
    } catch (err) {
      toast.error('Failed to generate report');
    } finally {
      setExporting(false);
    }
  };

  // Actions are attributed to the logged-in user (was hardcoded 'current_user'
  // regardless of who was actually signed in).
  const onResolveConfirm = async (issueId: string) => {
    setResolving(true);
    const success = await resolveIssue(issueId, resolutionNote, user?.id || user?.email);
    if (success) {
      setResolveMode(null);
      setResolutionNote('');
    }
    setResolving(false);
  };

  const onEscalateConfirm = async (issueId: string) => {
    setEscalating(true);
    const success = await escalateIssue(issueId, escalateRole, escalationNote, user?.id || user?.email);
    if (success) {
      setEscalateMode(null);
      setEscalationNote('');
    }
    setEscalating(false);
  };

  if (error) {
    return (
      <div className="h-full flex items-center justify-center text-[var(--fail)] bg-[var(--bg-base)]">
        <div className="text-center">
          <AlertTriangle size={48} className="mx-auto mb-4 opacity-50" />
          <h2 className="text-xl font-bold">Connection Error</h2>
          <p className="text-[var(--text-muted)] mt-2">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full p-8 flex flex-col min-h-0 bg-[var(--bg-base)] relative">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-3xl font-bold text-[var(--text-primary)] tracking-tight flex items-center gap-3">
            <AlertTriangle className="text-[var(--fail)]" size={32} />
            Active Field Issues
          </h1>
          <p className="text-[var(--text-secondary)] mt-2">Real-time deviations detected by Vision & Measurement Agents.</p>
        </div>

        <div className="flex gap-4">
          <div className="bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-lg p-1 flex">
            {['ALL', 'CRITICAL', 'HIGH', 'MEDIUM'].map(f => (
              <button
                key={f}
                onClick={() => setActiveFilter(f)}
                className={`px-4 py-2 rounded-md text-sm font-semibold transition-all ${
                  activeFilter === f
                    ? 'bg-[var(--bg-hover)] text-[var(--text-primary)] shadow-lg'
                    : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
                }`}
              >
                {f}
              </button>
            ))}
          </div>
          <button
            onClick={handleExport}
            disabled={exporting}
            className="bg-[var(--bg-elevated)] hover:bg-[var(--bg-hover)] text-[var(--text-primary)] border border-[var(--border-subtle)] px-4 py-2 rounded-lg font-semibold flex items-center gap-2 transition-all cursor-pointer disabled:opacity-50"
          >
            {exporting
              ? <><Loader2 size={16} className="animate-spin" /> Generating PDF...</>
              : <><Download size={16} /> Export report</>
            }
          </button>
        </div>
      </div>

      {/* Summary Strip */}
      {summary && (
        <div className="flex gap-4 mb-4 text-[13px] text-[var(--text-muted)]">
          <span>
            <span className="text-[var(--text-primary)] font-medium">{summary.open}</span> open issues
          </span>
          <span className="text-[var(--border-subtle)]">|</span>
          <span><span className="text-[var(--fail)]">{summary.by_severity.critical}</span> critical</span>
          <span><span className="text-[var(--amber)]">{summary.by_severity.high}</span> high</span>
          <span><span className="text-[var(--warning)]">{summary.by_severity.medium}</span> medium</span>
          <span className="ml-auto text-[var(--text-muted)] text-xs">
            Sorted by severity · detected by Vision Agent
          </span>
        </div>
      )}

      <div className="flex-1 overflow-y-auto min-h-0">
        {isLoading ? (
          <div className="flex items-center justify-center h-40">
            <Loader2 size={32} className="animate-spin text-[var(--text-muted)]" />
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6 pb-10">
            {sortedIssues.map((issue) => {
              const sev = SEVERITY[issue.severity as keyof typeof SEVERITY] || SEVERITY.medium;
              const isNew = issue.id === newIssueId;

              // Measurement Color Logic
              let measuredColor = 'var(--pass)'; // within tolerance
              if (issue.measured_value && issue.expected_value) {
                 const mVal = parseFloat(issue.measured_value.replace(/[^0-9.-]+/g,""));
                 const eVal = parseFloat(issue.expected_value.replace(/[^0-9.-]+/g,""));
                 if (!isNaN(mVal) && !isNaN(eVal) && mVal > eVal) {
                    measuredColor = sev.deviation;
                 } else if (issue.deviation_pct && issue.deviation_pct > 0) {
                    measuredColor = sev.deviation;
                 }
              }

              return (
                <div
                  key={issue.id}
                  className="relative rounded-xl p-6 bg-[var(--bg-surface)] border border-[var(--border-subtle)]"
                  style={{
                    borderLeft: isNew ? '3px solid var(--cyan)' : `3px solid ${sev.card_border}`,
                    transition: 'border-left-color 1.5s ease',
                  }}
                >
                  <div
                    onClick={() => setSelectedIssueId(issue.id)}
                    className="cursor-pointer"
                  >
                    <div className="flex justify-between items-start mb-4">
                      <div>
                        <span
                          className="text-[10px] font-bold uppercase tracking-wider px-2.5 py-1 rounded-full"
                          style={{ background: sev.badge_bg, color: sev.badge_text, border: `1px solid ${sev.badge_border}` }}
                        >
                          {issue.severity}
                        </span>
                        <h3 className="text-[var(--text-primary)] text-lg font-semibold mt-3">{issue.issue_type}</h3>
                        <div className="text-[var(--text-muted)] text-sm">Zone {issue.zone_code}</div>
                      </div>
                      <div className="flex items-center text-xs text-[var(--text-muted)]">
                        <Clock size={12} className="mr-1" />
                        <span>{issueTime(issue.created_at)}</span>
                      </div>
                    </div>

                    <div className="bg-[var(--bg-elevated)] rounded-md px-3 py-2.5 text-[13px] text-[var(--text-secondary)] leading-relaxed my-2.5">
                      {issue.description}
                    </div>

                    <div className="grid grid-cols-4 border-t border-[var(--border-subtle)] mt-2.5 pt-2.5 mb-4">
                      {[
                        { label: 'DEVIATION', value: issue.deviation_pct ? `${issue.deviation_pct}%` : '-', color: 'var(--fail)' },
                        { label: 'MEASURED', value: issue.measured_value || '-', color: measuredColor },
                        { label: 'EXPECTED', value: issue.expected_value || '-', color: 'var(--pass)' },
                        { label: 'WORKER', value: issue.worker_id || '-', color: 'var(--cyan)', clickable: true }
                      ].map(col => (
                        <div key={col.label}>
                          <div className="text-[10px] text-[var(--text-muted)] tracking-wide mb-0.5">{col.label}</div>
                          <div className="text-[13px] font-medium" style={{ color: col.color }}>
                            {col.clickable && issue.worker_id ? (
                               <a
                                href={`/workers/${issue.worker_id}`}
                                onClick={(e) => e.stopPropagation()}
                                className="hover:underline"
                                style={{ color: 'var(--cyan)' }}
                              >
                                {col.value}
                              </a>
                            ) : (
                              col.value
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Actions */}
                  {!resolveMode && !escalateMode && (
                    <div className="flex gap-3 mt-4">
                      <button
                        onClick={(e) => { e.stopPropagation(); setResolveMode(issue.id); }}
                        className="flex-1 py-2.5 rounded-lg transition-colors flex items-center justify-center gap-2 cursor-pointer font-semibold bg-[var(--pass-dim)] border border-[var(--pass)]/30 text-[var(--pass)]"
                      >
                        <CheckCircle size={16} /> Resolve
                      </button>
                      <button
                        onClick={(e) => { e.stopPropagation(); setEscalateMode(issue.id); }}
                        className="flex-1 bg-transparent hover:bg-[var(--bg-hover)] text-[var(--text-primary)] font-semibold py-2.5 rounded-lg transition-colors border border-[var(--border-subtle)] flex items-center justify-center gap-2 cursor-pointer"
                      >
                        <ArrowUpRight size={16} /> Escalate
                      </button>
                    </div>
                  )}

                  {/* Inline Resolve Modal */}
                  {resolveMode === issue.id && (
                    <div className="mt-3 p-3 bg-[var(--pass-dim)] border border-[var(--pass)]/30 rounded-lg">
                      <textarea
                        placeholder="Describe how this was resolved (required)..."
                        value={resolutionNote}
                        onChange={e => setResolutionNote(e.target.value)}
                        className="w-full min-h-[60px] bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-md text-[var(--text-primary)] text-xs p-2 resize-y"
                      />
                      <div className="flex gap-2 mt-2">
                        <button
                          disabled={resolutionNote.length < 10 || resolving}
                          onClick={() => onResolveConfirm(issue.id)}
                          className="rounded-md px-3.5 py-1.5 text-xs border border-[var(--pass)]/50 text-[var(--pass)]"
                          style={{
                            background: resolutionNote.length >= 10 ? 'var(--pass-dim)' : 'var(--bg-elevated)',
                            opacity: resolutionNote.length >= 10 ? 1 : 0.5
                          }}
                        >
                          {resolving ? 'Resolving...' : 'Confirm resolve'}
                        </button>
                        <button
                          onClick={() => { setResolveMode(null); setResolutionNote(''); }}
                          className="rounded-md px-3.5 py-1.5 text-xs border border-[var(--border-subtle)] text-[var(--text-muted)]"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Inline Escalate Modal */}
                  {escalateMode === issue.id && (
                    <div className="mt-3 p-3 bg-[var(--amber-dim)] border border-[var(--amber)]/30 rounded-lg">
                      <div className="text-xs text-[var(--text-muted)] mb-2">Escalate to:</div>
                      <select
                        value={escalateRole}
                        onChange={(e) => setEscalateRole(e.target.value)}
                        className="w-full bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-[var(--text-primary)] rounded-md px-2 py-1.5 text-xs"
                      >
                        <option value="site_manager">Site Manager</option>
                        <option value="safety_officer">Safety Officer</option>
                        <option value="project_director">Project Director</option>
                      </select>
                      <textarea
                        placeholder="Escalation note (optional)..."
                        value={escalationNote}
                        onChange={(e) => setEscalationNote(e.target.value)}
                        className="w-full mt-2 min-h-[50px] bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-md text-[var(--text-primary)] text-xs p-2 resize-y"
                      />
                      <div className="flex gap-2 mt-2">
                        <button
                          onClick={() => onEscalateConfirm(issue.id)}
                          disabled={escalating}
                          className="rounded-md px-3.5 py-1.5 text-xs border border-[var(--amber)]/60 text-[var(--amber)] bg-[var(--amber-dim)] disabled:opacity-50"
                        >
                          {escalating ? 'Escalating...' : 'Confirm escalate'}
                        </button>
                        <button
                          onClick={() => { setEscalateMode(null); setEscalationNote(''); }}
                          className="rounded-md px-3.5 py-1.5 text-xs border border-[var(--border-subtle)] text-[var(--text-muted)]"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}

                </div>
              );
            })}

            {sortedIssues.length === 0 && !isLoading && (
              <div className="col-span-full py-20 text-center text-[var(--text-muted)]">
                No issues match the selected filter.
              </div>
            )}
          </div>
        )}
      </div>

      <IssueDetailPanel
        issue={issues.find(i => i.id === selectedIssueId) || null}
        isOpen={!!selectedIssueId}
        onClose={() => setSelectedIssueId(null)}
        onResolve={(id, note) => resolveIssue(id, note, user?.id || user?.email)}
        onEscalate={(id, role, note) => escalateIssue(id, role, note, user?.id || user?.email)}
      />
    </div>
  );
}
