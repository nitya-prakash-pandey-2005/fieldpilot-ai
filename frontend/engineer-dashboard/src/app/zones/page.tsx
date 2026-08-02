"use client";
import { useState, useMemo } from 'react';
import { Flame, ShieldAlert, Activity, HardHat, Bell, CheckCircle2, Clock } from 'lucide-react';
import { useZones, getRiskLevel } from '@/hooks/useZones';
import { useAuth } from '@/context/AuthContext';
import { format, formatDistanceToNow } from 'date-fns';

import { apiBase } from '@/lib/api';
// Derived from the same CSS var tokens used across the rest of the app
// (globals.css's @theme block) instead of raw hex, so this page no longer
// breaks under the light theme toggle (Header.tsx's ThemeToggle) the way
// hardcoded "#e53935 on text-white" combinations would.
export const RISK_COLORS = {
  critical: {
    score:       'var(--fail)',
    badge_bg:    'var(--fail-dim)',
    badge_text:  'var(--fail)',
    badge_border:'color-mix(in srgb, var(--fail) 40%, transparent)',
    card_border: 'var(--fail)',
    bar:         'var(--fail)',
  },
  elevated: {
    score:       'var(--amber)',
    badge_bg:    'var(--amber-dim)',
    badge_text:  'var(--amber)',
    badge_border:'color-mix(in srgb, var(--amber) 40%, transparent)',
    card_border: 'var(--amber)',
    bar:         'var(--amber)',
  },
  normal: {
    score:       'var(--pass)',
    badge_bg:    'var(--pass-dim)',
    badge_text:  'var(--pass)',
    badge_border:'color-mix(in srgb, var(--pass) 40%, transparent)',
    card_border: 'var(--pass)',
    bar:         'var(--pass)',
  }
};

export default function ZonesPage() {
  const { zones, summary, lastUpdated, loading, error, connectionStatus } = useZones("default-project");
  const { user } = useAuth();
  const [filter, setFilter] = useState<'all' | 'critical' | 'elevated' | 'normal'>('all');
  const [alertLoadingId, setAlertLoadingId] = useState<string | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [selectedZoneIdForIssues, setSelectedZoneIdForIssues] = useState<string | null>(null);
  const [zoneIssues, setZoneIssues] = useState<any[]>([]);
  const [issuesLoading, setIssuesLoading] = useState(false);
  const [detailZoneId, setDetailZoneId] = useState<string | null>(null);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3000);
  };

  const openIssuesPanel = async (zoneId: string) => {
    setSelectedZoneIdForIssues(zoneId);
    setIssuesLoading(true);
    try {
      const BASE = apiBase();
      const res = await fetch(`${BASE}/api/v1/zones/${zoneId}/issues`);
      const data = await res.json();
      setZoneIssues(data.issues || []);
    } catch (err) {
      console.error(err);
      setZoneIssues([]);
    } finally {
      setIssuesLoading(false);
    }
  };

  const handleAlertTeam = async (zoneId: string) => {
    setAlertLoadingId(zoneId);
    try {
      const BASE = apiBase();
      const res = await fetch(`${BASE}/api/v1/zones/${zoneId}/alerts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // Attributed to the logged-in user (was hardcoded 'current-user-123').
        body: JSON.stringify({ triggered_by_user_id: user?.id || user?.email || 'unknown' })
      });
      const data = await res.json();
      showToast(`Team alerted — ${data.notified_count} notified`);
    } catch (err) {
      showToast("Failed to alert team");
    } finally {
      setAlertLoadingId(null);
    }
  };

  const filteredZones = useMemo(() => {
    if (filter === 'all') return zones;
    return zones.filter(zone => getRiskLevel(zone.risk_score) === filter);
  }, [zones, filter]);

  const detailZone = zones.find(z => z.id === detailZoneId) || null;

  return (
    <div className="h-full p-8 flex flex-col min-h-0 bg-[var(--bg-base)] relative">
      {/* Toast Notification */}
      {toastMessage && (
        <div className="absolute top-4 left-1/2 -translate-x-1/2 bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-[var(--text-primary)] px-4 py-2 rounded-lg text-sm z-50 shadow-lg animate-in fade-in slide-in-from-top-2 flex items-center gap-2">
          <CheckCircle2 size={16} className="text-[var(--pass)]" />
          {toastMessage}
        </div>
      )}

      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold text-[var(--text-primary)] tracking-tight flex items-center gap-3">
            <Flame className="text-[var(--amber)]" size={32} />
            High Risk Zones
          </h1>
          <p className="text-[var(--text-secondary)] mt-2">Aggregated risk scoring based on active issues, historical RFIs, and real-time activity.</p>
        </div>

        <div className="flex flex-col items-end gap-3">
          <div className="flex items-center gap-2 text-xs font-mono">
            {lastUpdated && (
              <span className="text-[var(--text-muted)]">Last sync: {format(lastUpdated, 'h:mm:ss aa')}</span>
            )}
            <span
              className="border rounded px-2 py-0.5 text-[11px] font-medium"
              style={{
                color: connectionStatus === 'live' ? 'var(--pass)' : connectionStatus === 'offline' ? 'var(--fail)' : 'var(--amber)',
                borderColor: 'currentColor',
              }}
            >
              {connectionStatus === 'live' ? '● LIVE' :
               connectionStatus === 'offline' ? '● OFFLINE' : '● DEMO MODE'}
            </span>
          </div>

          <div className="flex items-center gap-2 bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded p-1">
            {['all', 'critical', 'elevated', 'normal'].map(level => (
              <button
                key={level}
                onClick={() => setFilter(level as any)}
                className="rounded-md px-3 py-1 text-xs transition-colors"
                style={{
                  background: filter === level ? 'var(--cyan-dim)' : 'transparent',
                  border: `1px solid ${filter === level ? 'var(--cyan)' : 'var(--border-subtle)'}`,
                  color: filter === level ? 'var(--cyan)' : 'var(--text-muted)',
                }}
              >
                {level === 'all' ? 'All zones' :
                 level.charAt(0).toUpperCase() + level.slice(1)}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Summary Row */}
      {summary && (
        <div className="grid grid-cols-3 gap-4 mb-8">
          <div className="bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-xl p-4 flex items-center gap-4">
            <div className="bg-[var(--fail-dim)] p-3 rounded-lg"><Flame size={24} className="text-[var(--fail)]" /></div>
            <div>
              <div className="text-[var(--text-muted)] text-xs uppercase tracking-widest font-bold">Critical Zones</div>
              <div className="text-2xl font-black text-[var(--text-primary)]">{summary.critical_count}</div>
            </div>
          </div>
          <div className="bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-xl p-4 flex items-center gap-4">
            <div className="bg-[var(--cyan-dim)] p-3 rounded-lg"><HardHat size={24} className="text-[var(--cyan)]" /></div>
            <div>
              <div className="text-[var(--text-muted)] text-xs uppercase tracking-widest font-bold">Active Workers</div>
              <div className="text-2xl font-black text-[var(--text-primary)]">{summary.total_workers}</div>
            </div>
          </div>
          <div className="bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-xl p-4 flex items-center gap-4">
            <div className="bg-[var(--amber-dim)] p-3 rounded-lg"><ShieldAlert size={24} className="text-[var(--amber)]" /></div>
            <div>
              <div className="text-[var(--text-muted)] text-xs uppercase tracking-widest font-bold">Open Issues</div>
              <div className="text-2xl font-black text-[var(--text-primary)]">{summary.total_open_issues}</div>
            </div>
          </div>
        </div>
      )}

      {loading && zones.length === 0 ? (
        <div className="flex-1 overflow-y-auto min-h-0">
          <div className="flex flex-col gap-6 pb-10">
            <style>{`
              @keyframes shimmer {
                0% { background-position: -400px 0 }
                100% { background-position: 400px 0 }
              }
            `}</style>
            {[1, 2, 3].map(i => (
              <div key={i} className="bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-[10px] px-5 py-4 mb-2.5 flex items-center gap-4" style={{ borderLeft: '3px solid var(--border-muted)' }}>
                <div style={{ flex: 1 }}>
                  <div style={{ background: 'linear-gradient(90deg, var(--bg-elevated) 25%, var(--bg-hover) 50%, var(--bg-elevated) 75%)', backgroundSize: '800px 100%', animation: 'shimmer 1.5s infinite', height: 16, width: 120, borderRadius: 4, marginBottom: 10 }} />
                  <div style={{ background: 'linear-gradient(90deg, var(--bg-elevated) 25%, var(--bg-hover) 50%, var(--bg-elevated) 75%)', backgroundSize: '800px 100%', animation: 'shimmer 1.5s infinite', height: 20, width: 240, borderRadius: 4, marginBottom: 10 }} />
                  <div style={{ background: 'linear-gradient(90deg, var(--bg-elevated) 25%, var(--bg-hover) 50%, var(--bg-elevated) 75%)', backgroundSize: '800px 100%', animation: 'shimmer 1.5s infinite', height: 12, width: 200, borderRadius: 4 }} />
                </div>
                <div style={{ background: 'linear-gradient(90deg, var(--bg-elevated) 25%, var(--bg-hover) 50%, var(--bg-elevated) 75%)', backgroundSize: '800px 100%', animation: 'shimmer 1.5s infinite', height: 40, width: 80, borderRadius: 4 }} />
              </div>
            ))}
          </div>
        </div>
      ) : error ? (
        <div className="bg-[var(--fail-dim)] border border-[var(--fail)]/30 text-[var(--fail)] p-4 rounded-xl">
          {error}
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto min-h-0">
          <div className="flex flex-col gap-6 pb-10">
            {connectionStatus === 'offline' && (
              <div className="bg-[var(--fail-dim)] border border-[var(--fail)]/30 rounded-md px-3.5 py-2 text-xs text-[var(--fail)] flex items-center justify-between mb-3">
                <span>⚠ Live updates paused — reconnecting...</span>
                <button
                  onClick={() => window.location.reload()}
                  className="bg-transparent border-none text-[var(--fail)] cursor-pointer underline text-xs"
                >
                  Retry now
                </button>
              </div>
            )}

            {filteredZones.length === 0 && (
              <div className="text-center py-12 text-[var(--text-muted)]">
                <div className="text-3xl mb-3">✓</div>
                <div className="text-[15px] text-[var(--text-secondary)] mb-1">
                  No {filter === 'all' ? '' : filter} zones
                </div>
                <div className="text-xs text-[var(--text-muted)]">
                  {filter === 'critical'
                    ? 'No critical risk zones right now'
                    : filter === 'elevated'
                    ? 'No elevated risk zones detected'
                    : 'All zones are operating normally'}
                </div>
              </div>
            )}

            {filteredZones.map((zone) => {
              const riskLvl = getRiskLevel(zone.risk_score);
              const colors = RISK_COLORS[riskLvl];

              return (
                <div
                  key={zone.id}
                  className="shadow-2xl relative overflow-hidden group rounded-[10px] px-5 py-4 bg-[var(--bg-surface)] border border-[var(--border-subtle)] hover:border-[var(--border-accent)] transition-colors"
                  style={{ borderLeft: `3px solid ${colors.card_border}` }}
                >
                  <div className="flex flex-col md:flex-row gap-8 items-start md:items-center justify-between pl-3">

                    {/* Info Block */}
                    <div className="flex-1">
                      <div className="flex items-center gap-3 mb-2">
                        <span
                          className="rounded px-1.5 py-0.5 text-[10px] font-medium tracking-wide"
                          style={{ background: colors.badge_bg, color: colors.badge_text, border: `1px solid ${colors.badge_border}` }}
                        >
                          {riskLvl.toUpperCase()} RISK
                        </span>
                        <span className="text-[var(--text-muted)] text-xs font-mono tracking-wider">ZONE {zone.zone_code}</span>

                        {zone.last_scored_at && (
                          <span className="text-[var(--text-muted)] text-xs font-mono flex items-center gap-1 opacity-80">
                            <Clock size={12} />
                            {formatDistanceToNow(new Date(zone.last_scored_at), { addSuffix: true })}
                          </span>
                        )}
                      </div>
                      <h3 className="text-[var(--text-primary)] text-xl font-bold mb-3">{zone.name}</h3>

                      <div className="flex items-center gap-6 text-xs text-[var(--text-secondary)] mb-4">
                        <span className="flex items-center gap-2"><Activity size={14} className="text-[var(--cyan)]" /> {zone.current_activity}</span>
                        <span className="flex items-center gap-2"><HardHat size={14} className="text-[var(--amber)]" /> {zone.active_worker_count} Active Workers</span>
                        <span className="flex items-center gap-2"><ShieldAlert size={14} className={zone.open_issue_count > 0 ? "text-[var(--fail)]" : "text-[var(--text-muted)]"} /> {zone.open_issue_count} Open Issues</span>
                      </div>

                      <div className="zone-actions flex gap-3" onClick={e => e.stopPropagation()}>
                        {riskLvl === 'critical' && (
                          <button
                            disabled={alertLoadingId === zone.id}
                            onClick={() => handleAlertTeam(zone.id)}
                            className="rounded-md px-3 py-1.5 text-xs bg-[var(--fail-dim)] border border-[var(--fail)]/40 text-[var(--fail)] transition-colors"
                          >
                            <Bell size={12} className="inline mr-1" />
                            {alertLoadingId === zone.id ? "Alerting..." : "Alert team"}
                          </button>
                        )}

                        {zone.open_issue_count > 0 && (
                          <button
                            onClick={() => openIssuesPanel(zone.id)}
                            className="rounded-md px-3 py-1.5 text-xs bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-[var(--text-secondary)]"
                          >
                            View issues ({zone.open_issue_count})
                          </button>
                        )}

                        <button
                          onClick={() => setDetailZoneId(zone.id)}
                          className="rounded-md px-3 py-1.5 text-xs bg-transparent border border-transparent hover:border-[var(--border-subtle)] text-[var(--text-secondary)] transition-colors"
                        >
                          Details
                        </button>
                      </div>
                    </div>

                    {/* Risk Score Block */}
                    <div className="w-full md:w-64 bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-lg p-4 flex flex-col items-center justify-center shrink-0">
                      <span className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] font-bold mb-1">Risk Score</span>
                      <div className="flex items-end gap-1 mb-3">
                        <span style={{ color: colors.score }} className="text-4xl font-black tracking-tighter transition-colors duration-500">
                          {zone.risk_score}
                        </span>
                        <span className="text-[var(--text-muted)] text-lg mb-1 font-bold">/ 100</span>
                      </div>

                      <div className="relative w-full">
                        <div className="w-full h-1 rounded bg-[var(--border-subtle)] overflow-hidden">
                          <div
                            className="h-full rounded transition-all duration-700"
                            style={{ width: `${zone.risk_score}%`, background: colors.bar }}
                          />
                        </div>
                        <div
                          className="absolute top-0 w-px h-1 opacity-40"
                          style={{ left: '70%', background: 'var(--fail)' }}
                          title="Critical threshold"
                        />
                      </div>
                    </div>

                  </div>
                </div>
              );
            })}
            {filteredZones.length === 0 && (
              <div className="text-center text-[var(--text-muted)] py-12">
                No zones match the current filter.
              </div>
            )}
          </div>
        </div>
      )}

      {/* Slide-over Issues Panel */}
      {selectedZoneIdForIssues && (
        <>
          <div
            className="fixed inset-0 bg-black/50 z-40"
            onClick={() => setSelectedZoneIdForIssues(null)}
          />
          <div className="fixed top-0 right-0 h-full w-[400px] bg-[var(--bg-surface)] border-l border-[var(--border-subtle)] shadow-2xl z-50 flex flex-col animate-in slide-in-from-right">
            <div className="p-6 border-b border-[var(--border-subtle)] flex justify-between items-center bg-[var(--bg-elevated)]">
              <h2 className="text-xl font-bold text-[var(--text-primary)] flex items-center gap-2">
                <ShieldAlert className="text-[var(--amber)]" />
                Zone Issues
              </h2>
              <button
                onClick={() => setSelectedZoneIdForIssues(null)}
                className="text-[var(--text-muted)] hover:text-[var(--text-primary)]"
              >
                ✕
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-6 flex flex-col gap-4">
              {issuesLoading ? (
                <div className="text-[var(--text-muted)] text-center py-10">Loading issues...</div>
              ) : zoneIssues.length === 0 ? (
                <div className="text-[var(--text-muted)] text-center py-10">No open issues found.</div>
              ) : (
                zoneIssues.map((issue) => (
                  <div key={issue.id} className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] p-4 rounded-lg">
                    <div className="flex justify-between items-start mb-2">
                      <span className="text-xs font-mono font-semibold text-[var(--text-secondary)]">{issue.id}</span>
                      <span className={`text-[10px] font-bold px-2 py-0.5 rounded uppercase tracking-widest border ${
                        issue.severity === 'CRITICAL' ? 'bg-[var(--fail-dim)] text-[var(--fail)] border-[var(--fail)]/30' :
                        issue.severity === 'HIGH' ? 'bg-[var(--amber-dim)] text-[var(--amber)] border-[var(--amber)]/30' :
                        'bg-[var(--warning-dim)] text-[var(--warning)] border-[var(--warning)]/30'
                      }`}>
                        {issue.severity}
                      </span>
                    </div>
                    <h4 className="text-[var(--text-primary)] font-semibold text-sm mb-1">{issue.title}</h4>
                    <p className="text-[var(--text-secondary)] text-xs mb-3">{issue.description}</p>
                    <div className="flex justify-between text-[10px] text-[var(--text-muted)]">
                      <span>Assigned to: {issue.assigned_to}</span>
                      <span>{formatDistanceToNow(new Date(issue.created_at), { addSuffix: true })}</span>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </>
      )}

      {/* Zone Details Panel */}
      {detailZone && (
        <>
          <div
            className="fixed inset-0 bg-black/50 z-40"
            onClick={() => setDetailZoneId(null)}
          />
          <div className="fixed top-0 right-0 h-full w-[400px] bg-[var(--bg-surface)] border-l border-[var(--border-subtle)] shadow-2xl z-50 flex flex-col animate-in slide-in-from-right">
            <div className="p-6 border-b border-[var(--border-subtle)] flex justify-between items-center bg-[var(--bg-elevated)]">
              <h2 className="text-xl font-bold text-[var(--text-primary)]">Zone {detailZone.zone_code}</h2>
              <button onClick={() => setDetailZoneId(null)} className="text-[var(--text-muted)] hover:text-[var(--text-primary)]">✕</button>
            </div>
            <div className="flex-1 overflow-y-auto p-6 flex flex-col gap-4 text-sm">
              <div>
                <div className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] mb-1">Name</div>
                <div className="text-[var(--text-primary)] font-semibold">{detailZone.name}</div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] mb-1">Current Activity</div>
                <div className="text-[var(--text-secondary)]">{detailZone.current_activity}</div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="bg-[var(--bg-elevated)] rounded-lg p-3 border border-[var(--border-subtle)]">
                  <div className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] mb-1">Risk Score</div>
                  <div className="text-xl font-bold" style={{ color: RISK_COLORS[getRiskLevel(detailZone.risk_score)].score }}>{detailZone.risk_score}/100</div>
                </div>
                <div className="bg-[var(--bg-elevated)] rounded-lg p-3 border border-[var(--border-subtle)]">
                  <div className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] mb-1">Workers</div>
                  <div className="text-xl font-bold text-[var(--text-primary)]">{detailZone.active_worker_count}</div>
                </div>
                <div className="bg-[var(--bg-elevated)] rounded-lg p-3 border border-[var(--border-subtle)]">
                  <div className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] mb-1">Open Issues</div>
                  <div className="text-xl font-bold text-[var(--text-primary)]">{detailZone.open_issue_count}</div>
                </div>
                <div className="bg-[var(--bg-elevated)] rounded-lg p-3 border border-[var(--border-subtle)]">
                  <div className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] mb-1">Last Scored</div>
                  <div className="text-xs text-[var(--text-secondary)] mt-1.5">{detailZone.last_scored_at ? formatDistanceToNow(new Date(detailZone.last_scored_at), { addSuffix: true }) : 'n/a'}</div>
                </div>
              </div>
              {detailZone.open_issue_count > 0 && (
                <button
                  onClick={() => { setDetailZoneId(null); openIssuesPanel(detailZone.id); }}
                  className="mt-2 rounded-lg px-3 py-2 text-xs bg-[var(--cyan-dim)] border border-[var(--cyan)]/30 text-[var(--cyan)]"
                >
                  View {detailZone.open_issue_count} open issue{detailZone.open_issue_count > 1 ? 's' : ''}
                </button>
              )}
            </div>
          </div>
        </>
      )}

    </div>
  );
}
