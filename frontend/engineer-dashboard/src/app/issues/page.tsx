"use client";
import { useState } from 'react';
import { AlertTriangle, Clock, FileText, CheckCircle, ArrowUpRight, Loader2, Download } from 'lucide-react';
import { toast } from 'sonner';
import { useFieldIssues, FieldIssue } from '@/hooks/useFieldIssues';
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
      const res = await fetch(`/api/v1/projects/default-project/issues/export`, {
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

  const onResolveConfirm = async (issueId: string) => {
    setResolving(true);
    const success = await resolveIssue(issueId, resolutionNote);
    if (success) {
      setResolveMode(null);
      setResolutionNote('');
    }
    setResolving(false);
  };

  const onEscalateConfirm = async (issueId: string) => {
    setEscalating(true);
    const success = await escalateIssue(issueId, escalateRole, escalationNote);
    if (success) {
      setEscalateMode(null);
      setEscalationNote('');
    }
    setEscalating(false);
  };

  if (error) {
    return (
      <div className="h-full flex items-center justify-center text-[#ff4444] bg-[#0a0a0a]">
        <div className="text-center">
          <AlertTriangle size={48} className="mx-auto mb-4 opacity-50" />
          <h2 className="text-xl font-bold">Connection Error</h2>
          <p className="text-white/50 mt-2">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full p-8 flex flex-col min-h-0 bg-[#0a0a0a] relative">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-3xl font-bold text-white tracking-tight flex items-center gap-3">
            <AlertTriangle className="text-[#ff4444]" size={32} />
            Active Field Issues
          </h1>
          <p className="text-white/50 mt-2">Real-time deviations detected by Vision & Measurement Agents.</p>
        </div>
        
        <div className="flex gap-4">
          <div className="bg-black/20 border border-white/10 rounded-lg p-1 flex">
            {['ALL', 'CRITICAL', 'HIGH', 'MEDIUM'].map(f => (
              <button
                key={f}
                onClick={() => setActiveFilter(f)}
                className={`px-4 py-2 rounded-md text-sm font-semibold transition-all ${
                  activeFilter === f 
                    ? 'bg-white/10 text-white shadow-lg' 
                    : 'text-white/40 hover:text-white/80'
                }`}
              >
                {f}
              </button>
            ))}
          </div>
          <button 
            onClick={handleExport} 
            disabled={exporting}
            className="bg-[#111] hover:bg-[#222] text-white border border-white/20 px-4 py-2 rounded-lg font-semibold flex items-center gap-2 transition-all cursor-pointer disabled:opacity-50"
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
        <div style={{
          display: 'flex', gap: 16, marginBottom: 16,
          fontSize: 13, color: '#888'
        }}>
          <span>
            <span style={{ color: '#eee', fontWeight: 500 }}>
              {summary.open}
            </span> open issues
          </span>
          <span style={{ color: '#444' }}>|</span>
          <span>
            <span style={{ color: '#e53935' }}>{summary.by_severity.critical}</span>
            {' '}critical
          </span>
          <span>
            <span style={{ color: '#f97316' }}>{summary.by_severity.high}</span>
            {' '}high
          </span>
          <span>
            <span style={{ color: '#eab308' }}>{summary.by_severity.medium}</span>
            {' '}medium
          </span>
          <span style={{ marginLeft: 'auto', color: '#444', fontSize: 12 }}>
            Sorted by severity · detected by Vision Agent
          </span>
        </div>
      )}

      <div className="flex-1 overflow-y-auto min-h-0">
        {isLoading ? (
          <div className="flex items-center justify-center h-40">
            <Loader2 size={32} className="animate-spin text-white/20" />
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6 pb-10">
            {sortedIssues.map((issue) => {
              const sev = SEVERITY[issue.severity as keyof typeof SEVERITY] || SEVERITY.medium;
              const isNew = issue.id === newIssueId;
              
              // Measurement Color Logic
              let measuredColor = '#22c55e'; // Green if within tolerance
              if (issue.measured_value && issue.expected_value) {
                 const mVal = parseFloat(issue.measured_value.replace(/[^0-9.-]+/g,""));
                 const eVal = parseFloat(issue.expected_value.replace(/[^0-9.-]+/g,""));
                 if (!isNaN(mVal) && !isNaN(eVal) && mVal > eVal) {
                    measuredColor = sev.deviation;
                 } else if (issue.deviation_pct && issue.deviation_pct > 0) {
                    // Fallback for deviation > 0
                    measuredColor = sev.deviation;
                 }
              }

              return (
                <div 
                  key={issue.id}
                  style={{
                    background: '#12121A',
                    borderRadius: 12,
                    padding: 24,
                    position: 'relative',
                    border: `1px solid ${sev.card_tint !== 'transparent' ? sev.card_tint : 'rgba(255,255,255,0.1)'}`,
                    borderLeft: isNew
                      ? '3px solid #00e5c0'
                      : `3px solid ${sev.card_border}`,
                    transition: 'border-left-color 1.5s ease',
                    cursor: 'default'
                  }}
                >
                  <div 
                    onClick={() => setSelectedIssueId(issue.id)}
                    className="cursor-pointer"
                  >
                    <div className="flex justify-between items-start mb-4">
                      <div>
                        <span style={{
                          background: sev.badge_bg,
                          color: sev.badge_text,
                          border: `1px solid ${sev.badge_border}`,
                          fontSize: 10,
                          fontWeight: 'bold',
                          padding: '4px 10px',
                          borderRadius: 999,
                          textTransform: 'uppercase',
                          letterSpacing: 1
                        }}>
                          {issue.severity}
                        </span>
                        <h3 className="text-white text-lg font-semibold mt-3">{issue.issue_type}</h3>
                        <div className="text-white/40 text-sm">Zone {issue.zone_code}</div>
                      </div>
                      <div className="flex items-center text-xs" style={{ color: '#555' }}>
                        <Clock size={12} className="mr-1" />
                        <span>{issueTime(issue.created_at)}</span>
                      </div>
                    </div>

                    <div style={{
                      background: 'rgba(255,255,255,0.03)',
                      borderRadius: 6,
                      padding: '10px 12px',
                      fontSize: 13,
                      color: '#bbb',
                      lineHeight: 1.6,
                      margin: '10px 0'
                    }}>
                      {issue.description}
                    </div>

                    <div style={{
                      display: 'grid',
                      gridTemplateColumns: 'repeat(4, 1fr)',
                      gap: 0,
                      borderTop: '0.5px solid #1e1e1e',
                      marginTop: 10,
                      paddingTop: 10,
                      marginBottom: 16
                    }}>
                      {[
                        { label: 'DEVIATION', value: issue.deviation_pct ? `${issue.deviation_pct}%` : '-',
                          color: '#e53935' },
                        { label: 'MEASURED', value: issue.measured_value || '-',
                          color: measuredColor },
                        { label: 'EXPECTED', value: issue.expected_value || '-',
                          color: '#22c55e' },
                        { label: 'WORKER', value: issue.worker_id || '-',
                          color: '#378add', clickable: true }
                      ].map(col => (
                        <div key={col.label} style={{ padding: '0 0 0 0' }}>
                          <div style={{ fontSize: 10, color: '#444',
                                        letterSpacing: '0.5px', marginBottom: 3 }}>
                            {col.label}
                          </div>
                          <div style={{ fontSize: 13, fontWeight: 500, color: col.color }}>
                            {col.clickable && issue.worker_id ? (
                               <a 
                                href={`/workers/${issue.worker_id}`}
                                onClick={(e) => e.stopPropagation()}
                                style={{
                                  color: '#378add', cursor: 'pointer', fontSize: 13,
                                  fontWeight: 500, textDecoration: 'none'
                                }}
                                onMouseEnter={e => e.currentTarget.style.textDecoration = 'underline'}
                                onMouseLeave={e => e.currentTarget.style.textDecoration = 'none'}
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
                        className="flex-1 py-2.5 rounded-lg transition-colors flex items-center justify-center gap-2 cursor-pointer font-semibold"
                        style={{
                          background: '#0d2a0d',
                          border: '0.5px solid #1a5a1a',
                          color: '#22c55e'
                        }}
                      >
                        <CheckCircle size={16} /> Resolve
                      </button>
                      <button 
                        onClick={(e) => { e.stopPropagation(); setEscalateMode(issue.id); }}
                        className="flex-1 bg-transparent hover:bg-white/5 text-white font-semibold py-2.5 rounded-lg transition-colors border border-[#2a2a2a] flex items-center justify-center gap-2 cursor-pointer"
                      >
                        <ArrowUpRight size={16} /> Escalate
                      </button>
                    </div>
                  )}

                  {/* Inline Resolve Modal */}
                  {resolveMode === issue.id && (
                    <div style={{
                      marginTop: 12, padding: 12,
                      background: '#0d1a0d',
                      border: '0.5px solid #1a4a1a',
                      borderRadius: 8
                    }}>
                      <textarea
                        placeholder="Describe how this was resolved (required)..."
                        value={resolutionNote}
                        onChange={e => setResolutionNote(e.target.value)}
                        style={{
                          width: '100%', minHeight: 60,
                          background: '#111', border: '0.5px solid #222',
                          borderRadius: 6, color: '#eee', fontSize: 12,
                          padding: 8, resize: 'vertical'
                        }}
                      />
                      <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                        <button
                          disabled={resolutionNote.length < 10 || resolving}
                          onClick={() => onResolveConfirm(issue.id)}
                          style={{
                            background: resolutionNote.length >= 10 ? '#0d3d0d' : '#111',
                            border: '0.5px solid #1a5a1a',
                            color: '#22c55e', borderRadius: 6,
                            padding: '5px 14px', fontSize: 12, cursor: 'pointer',
                            opacity: resolutionNote.length >= 10 ? 1 : 0.5
                          }}
                        >
                          {resolving ? 'Resolving...' : 'Confirm resolve'}
                        </button>
                        <button
                          onClick={() => { setResolveMode(null); setResolutionNote(''); }}
                          style={{
                            background: 'transparent',
                            border: '0.5px solid #2a2a2a',
                            color: '#666', borderRadius: 6,
                            padding: '5px 14px', fontSize: 12, cursor: 'pointer'
                          }}
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Inline Escalate Modal */}
                  {escalateMode === issue.id && (
                    <div style={{
                      marginTop: 12, padding: 12,
                      background: '#1a0e00',
                      border: '0.5px solid #4a2a00',
                      borderRadius: 8
                    }}>
                      <div style={{ fontSize: 12, color: '#888', marginBottom: 8 }}>
                        Escalate to:
                      </div>
                      <select 
                        value={escalateRole}
                        onChange={(e) => setEscalateRole(e.target.value)}
                        style={{
                        width: '100%', background: '#111',
                        border: '0.5px solid #333', color: '#eee',
                        borderRadius: 6, padding: '6px 8px', fontSize: 12
                      }}>
                        <option value="site_manager">Site Manager</option>
                        <option value="safety_officer">Safety Officer</option>
                        <option value="project_director">Project Director</option>
                      </select>
                      <textarea
                        placeholder="Escalation note (optional)..."
                        value={escalationNote}
                        onChange={(e) => setEscalationNote(e.target.value)}
                        style={{ width: '100%', marginTop: 8, minHeight: 50,
                                 background: '#111', border: '0.5px solid #222',
                                 borderRadius: 6, color: '#eee',
                                 fontSize: 12, padding: 8, resize: 'vertical' }}
                      />
                      <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                        <button 
                          onClick={() => onEscalateConfirm(issue.id)}
                          disabled={escalating}
                          style={{
                            background: '#1a0e00', border: '0.5px solid #f97316',
                            color: '#f97316', borderRadius: 6,
                            padding: '5px 14px', fontSize: 12, cursor: 'pointer',
                            opacity: escalating ? 0.5 : 1
                          }}>
                          {escalating ? 'Escalating...' : 'Confirm escalate'}
                        </button>
                        <button onClick={() => { setEscalateMode(null); setEscalationNote(''); }}
                          style={{
                            background: 'transparent', border: '0.5px solid #2a2a2a',
                            color: '#666', borderRadius: 6,
                            padding: '5px 14px', fontSize: 12, cursor: 'pointer'
                          }}>
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}

                </div>
              );
            })}
            
            {sortedIssues.length === 0 && !isLoading && (
              <div className="col-span-full py-20 text-center text-white/40">
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
        onResolve={resolveIssue}
        onEscalate={escalateIssue}
      />
    </div>
  ); 
}