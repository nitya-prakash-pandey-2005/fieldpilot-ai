"use client";
import { useState, useMemo } from 'react';
import { Flame, ShieldAlert, Activity, HardHat, Bell, CheckCircle2, Clock } from 'lucide-react';
import { useZones, getRiskLevel } from '@/hooks/useZones';
import { format, formatDistanceToNow } from 'date-fns';

export const RISK_COLORS = {
  critical: {
    score:       '#e53935',
    badge_bg:    '#1a0505',
    badge_text:  '#e53935',
    badge_border:'#4a1010',
    card_border: '#e53935',
    bar:         '#e53935',
    glow:        'rgba(229,57,53,0.08)'
  },
  elevated: {
    score:       '#f59e0b',
    badge_bg:    '#1a1200',
    badge_text:  '#f59e0b',
    badge_border:'#4a3200',
    card_border: '#f59e0b',
    bar:         '#f59e0b',
    glow:        'rgba(245,158,11,0.06)'
  },
  normal: {
    score:       '#22c55e',
    badge_bg:    '#051a0a',
    badge_text:  '#22c55e',
    badge_border:'#0f4a20',
    card_border: '#22c55e',
    bar:         '#22c55e',
    glow:        'transparent'
  }
};

export default function ZonesPage() {
  const { zones, summary, lastUpdated, loading, error, connectionStatus } = useZones("default-project");
  const [filter, setFilter] = useState<'all' | 'critical' | 'elevated' | 'normal'>('all');
  const [alertLoadingId, setAlertLoadingId] = useState<string | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [selectedZoneIdForIssues, setSelectedZoneIdForIssues] = useState<string | null>(null);
  const [zoneIssues, setZoneIssues] = useState<any[]>([]);
  const [issuesLoading, setIssuesLoading] = useState(false);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3000);
  };

  const openIssuesPanel = async (zoneId: string) => {
    setSelectedZoneIdForIssues(zoneId);
    setIssuesLoading(true);
    try {
      const BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';
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
      const BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';
      const res = await fetch(`${BASE}/api/v1/zones/${zoneId}/alerts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ triggered_by_user_id: 'current-user-123' })
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

  const atRiskCount = zones.filter(z => getRiskLevel(z.risk_score) !== 'normal').length;

  return (
    <div className="h-full p-8 flex flex-col min-h-0 bg-atw-bg relative">
      {/* Toast Notification */}
      {toastMessage && (
        <div className="absolute top-4 left-1/2 -translate-x-1/2 bg-black border border-[var(--border-subtle)] text-white px-4 py-2 rounded-lg text-sm z-50 shadow-lg animate-in fade-in slide-in-from-top-2 flex items-center gap-2">
          <CheckCircle2 size={16} className="text-atw-green" />
          {toastMessage}
        </div>
      )}

      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold text-white tracking-tight flex items-center gap-3">
            <Flame className="text-orange-500" size={32} />
            High Risk Zones
          </h1>
          <p className="text-white/50 mt-2">Aggregated risk scoring based on active issues, historical RFIs, and real-time activity.</p>
        </div>
        
        <div className="flex flex-col items-end gap-3">
          <div className="flex items-center gap-2 text-xs font-mono">
            {lastUpdated && (
              <span className="text-white/40">Last sync: {format(lastUpdated, 'h:mm:ss aa')}</span>
            )}
            <span style={{
              color: connectionStatus === 'live' ? '#00e5c0' : 
                     connectionStatus === 'offline' ? '#e53935' : '#f59e0b',
              border: `1px solid currentColor`,
              borderRadius: 4,
              padding: '2px 8px',
              fontSize: 11,
              fontWeight: 500
            }}>
              {connectionStatus === 'live' ? '● LIVE' : 
               connectionStatus === 'offline' ? '● OFFLINE' : '● DEMO MODE'}
            </span>
          </div>
          
          <div className="flex items-center gap-2 bg-[#12121A] border border-white/10 rounded p-1">
            {['all', 'critical', 'elevated', 'normal'].map(level => (
              <button
                key={level}
                onClick={() => setFilter(level as any)}
                style={{
                  background: filter === level ? '#1a2a1a' : 'transparent',
                  border: `0.5px solid ${filter === level ? '#00e5c0' : '#2a2a2a'}`,
                  color: filter === level ? '#00e5c0' : '#666',
                  borderRadius: 6,
                  padding: '4px 12px',
                  fontSize: 12,
                  cursor: 'pointer'
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
          <div className="bg-[#12121A] border border-white/10 rounded-xl p-4 flex items-center gap-4">
            <div className="bg-atw-red/10 p-3 rounded-lg"><Flame size={24} className="text-atw-red" /></div>
            <div>
              <div className="text-white/40 text-xs uppercase tracking-widest font-bold">Critical Zones</div>
              <div className="text-2xl font-black text-white">{summary.critical_count}</div>
            </div>
          </div>
          <div className="bg-[#12121A] border border-white/10 rounded-xl p-4 flex items-center gap-4">
            <div className="bg-atw-cyan/10 p-3 rounded-lg"><HardHat size={24} className="text-atw-cyan" /></div>
            <div>
              <div className="text-white/40 text-xs uppercase tracking-widest font-bold">Active Workers</div>
              <div className="text-2xl font-black text-white">{summary.total_workers}</div>
            </div>
          </div>
          <div className="bg-[#12121A] border border-white/10 rounded-xl p-4 flex items-center gap-4">
            <div className="bg-atw-amber/10 p-3 rounded-lg"><ShieldAlert size={24} className="text-atw-amber" /></div>
            <div>
              <div className="text-white/40 text-xs uppercase tracking-widest font-bold">Open Issues</div>
              <div className="text-2xl font-black text-white">{summary.total_open_issues}</div>
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
              <div key={i} style={{
                background: '#161616', border: '0.5px solid #222',
                borderLeft: '3px solid #2a2a2a', borderRadius: 10,
                padding: '16px 20px', marginBottom: 10,
                display: 'flex', alignItems: 'center', gap: 16
              }}>
                <div style={{ flex: 1 }}>
                  <div style={{ background: 'linear-gradient(90deg, #1a1a1a 25%, #222 50%, #1a1a1a 75%)', backgroundSize: '800px 100%', animation: 'shimmer 1.5s infinite', height: 16, width: 120, borderRadius: 4, marginBottom: 10 }} />
                  <div style={{ background: 'linear-gradient(90deg, #1a1a1a 25%, #222 50%, #1a1a1a 75%)', backgroundSize: '800px 100%', animation: 'shimmer 1.5s infinite', height: 20, width: 240, borderRadius: 4, marginBottom: 10 }} />
                  <div style={{ background: 'linear-gradient(90deg, #1a1a1a 25%, #222 50%, #1a1a1a 75%)', backgroundSize: '800px 100%', animation: 'shimmer 1.5s infinite', height: 12, width: 200, borderRadius: 4 }} />
                </div>
                <div style={{ background: 'linear-gradient(90deg, #1a1a1a 25%, #222 50%, #1a1a1a 75%)', backgroundSize: '800px 100%', animation: 'shimmer 1.5s infinite', height: 40, width: 80, borderRadius: 4 }} />
              </div>
            ))}
          </div>
        </div>
      ) : error ? (
        <div className="bg-atw-red/10 border border-atw-red/30 text-atw-red p-4 rounded-xl">
          {error}
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto min-h-0">
          <div className="flex flex-col gap-6 pb-10">
            {connectionStatus === 'offline' && (
              <div style={{
                background: '#1a0a0a',
                border: '0.5px solid #4a1010',
                borderRadius: 6,
                padding: '8px 14px',
                fontSize: 12,
                color: '#e53935',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                marginBottom: 12
              }}>
                <span>⚠ Live updates paused — reconnecting...</span>
                <button
                  onClick={() => window.location.reload()}
                  style={{ background: 'none', border: 'none',
                           color: '#e53935', cursor: 'pointer',
                           textDecoration: 'underline', fontSize: 12 }}
                >
                  Retry now
                </button>
              </div>
            )}

            {filteredZones.length === 0 && (
              <div style={{
                textAlign: 'center',
                padding: '48px 0',
                color: '#444'
              }}>
                <div style={{ fontSize: 32, marginBottom: 12 }}>✓</div>
                <div style={{ fontSize: 15, color: '#666', marginBottom: 4 }}>
                  No {filter === 'all' ? '' : filter} zones
                </div>
                <div style={{ fontSize: 12, color: '#444' }}>
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
                <div key={zone.id} style={{
                  background: '#161616',
                  border: `0.5px solid #262626`,
                  borderLeft: `3px solid ${colors.card_border}`,
                  borderRadius: 10,
                  padding: '16px 20px',
                  backgroundColor: `color-mix(in srgb, #161616 95%, ${colors.card_border})`,
                  transition: 'border-color 0.3s ease'
                }} className="shadow-2xl relative overflow-hidden group hover:border-white/20">
                  <div className="flex flex-col md:flex-row gap-8 items-start md:items-center justify-between pl-3">
                    
                    {/* Info Block */}
                    <div className="flex-1">
                      <div className="flex items-center gap-3 mb-2">
                        <span style={{
                          background: colors.badge_bg,
                          color: colors.badge_text,
                          border: `0.5px solid ${colors.badge_border}`,
                          borderRadius: 4,
                          padding: '2px 7px',
                          fontSize: 10,
                          fontWeight: 500,
                          letterSpacing: '0.5px'
                        }}>
                          {riskLvl.toUpperCase()} RISK
                        </span>
                        <span className="text-white/40 text-xs font-mono tracking-wider">ZONE {zone.zone_code}</span>
                        
                        {zone.last_scored_at && (
                          <span className="text-white/30 text-xs font-mono flex items-center gap-1">
                            <Clock size={12} />
                            {formatDistanceToNow(new Date(zone.last_scored_at), { addSuffix: true })}
                          </span>
                        )}
                      </div>
                      <h3 className="text-white text-xl font-bold mb-3">{zone.name}</h3>
                      
                      <div className="flex items-center gap-6 text-xs text-white/60 mb-4">
                        <span className="flex items-center gap-2"><Activity size={14} className="text-atw-cyan" /> {zone.current_activity}</span>
                        <span className="flex items-center gap-2"><HardHat size={14} className="text-atw-amber" /> {zone.active_worker_count} Active Workers</span>
                        <span className="flex items-center gap-2"><ShieldAlert size={14} className={zone.open_issue_count > 0 ? "text-atw-red" : "text-white/40"} /> {zone.open_issue_count} Open Issues</span>
                      </div>

                      <div className="zone-actions flex gap-3" onClick={e => e.stopPropagation()}>
                        {riskLvl === 'critical' && (
                          <button 
                            className="btn-alert"
                            disabled={alertLoadingId === zone.id}
                            onClick={() => handleAlertTeam(zone.id)}
                            style={{
                              background: '#1a0808',
                              border: '0.5px solid #5a1212',
                              color: '#e53935',
                              borderRadius: '6px',
                              padding: '5px 12px',
                              fontSize: '12px',
                              cursor: 'pointer',
                              transition: 'background 0.15s'
                            }}
                          >
                            <Bell size={12} className="inline mr-1" />
                            {alertLoadingId === zone.id ? "Alerting..." : "Alert team"}
                          </button>
                        )}
                        
                        {zone.open_issue_count > 0 && (
                          <button 
                            className="btn-secondary"
                            onClick={() => openIssuesPanel(zone.id)}
                            style={{
                              background: '#1a1a1a',
                              border: '0.5px solid #2a2a2a',
                              color: '#aaa',
                              borderRadius: '6px',
                              padding: '5px 12px',
                              fontSize: '12px',
                              cursor: 'pointer'
                            }}
                          >
                            View issues ({zone.open_issue_count})
                          </button>
                        )}
                        
                        <button 
                          className="btn-ghost"
                          onClick={() => {}}
                          style={{
                            background: 'transparent',
                            border: '0.5px solid transparent',
                            color: '#aaa',
                            borderRadius: '6px',
                            padding: '5px 12px',
                            fontSize: '12px',
                            cursor: 'pointer'
                          }}
                        >
                          Details
                        </button>
                      </div>
                    </div>

                    {/* Risk Score Block */}
                    <div className="w-full md:w-64 bg-black/40 border border-white/5 rounded-lg p-4 flex flex-col items-center justify-center shrink-0">
                      <span className="text-[10px] uppercase tracking-widest text-white/40 font-bold mb-1">Risk Score</span>
                      <div className="flex items-end gap-1 mb-3">
                        <span style={{ color: colors.score }} className="text-4xl font-black tracking-tighter transition-colors duration-500">
                          {zone.risk_score}
                        </span>
                        <span className="text-white/30 text-lg mb-1 font-bold">/ 100</span>
                      </div>
                      
                      <div style={{ position: 'relative', width: '100%' }}>
                        <div style={{
                          width: '100%',
                          height: '4px',
                          background: '#222',
                          borderRadius: '2px',
                          overflow: 'hidden'
                        }}>
                          <div style={{
                            height: '100%',
                            width: `${zone.risk_score}%`,
                            background: colors.bar,
                            borderRadius: '2px',
                            transition: 'width 0.8s ease, background 0.4s ease'
                          }} />
                        </div>
                        <div style={{
                          position: 'absolute',
                          left: '70%',
                          top: 0,
                          width: '1px',
                          height: '4px',
                          background: '#e53935',
                          opacity: 0.4
                        }} title="Critical threshold" />
                      </div>
                    </div>

                  </div>
                </div>
              );
            })}
            {filteredZones.length === 0 && (
              <div className="text-center text-white/40 py-12">
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
          <div className="fixed top-0 right-0 h-full w-[400px] bg-[#12121A] border-l border-white/10 shadow-2xl z-50 flex flex-col animate-in slide-in-from-right">
            <div className="p-6 border-b border-white/10 flex justify-between items-center bg-[#161616]">
              <h2 className="text-xl font-bold text-white flex items-center gap-2">
                <ShieldAlert className="text-atw-amber" />
                Zone Issues
              </h2>
              <button 
                onClick={() => setSelectedZoneIdForIssues(null)}
                className="text-white/50 hover:text-white"
              >
                ✕
              </button>
            </div>
            
            <div className="flex-1 overflow-y-auto p-6 flex flex-col gap-4">
              {issuesLoading ? (
                <div className="text-white/50 text-center py-10">Loading issues...</div>
              ) : zoneIssues.length === 0 ? (
                <div className="text-white/50 text-center py-10">No open issues found.</div>
              ) : (
                zoneIssues.map((issue) => (
                  <div key={issue.id} className="bg-black/40 border border-white/5 p-4 rounded-lg">
                    <div className="flex justify-between items-start mb-2">
                      <span className="text-xs font-mono font-semibold text-white/80">{issue.id}</span>
                      <span className={`text-[10px] font-bold px-2 py-0.5 rounded uppercase tracking-widest ${
                        issue.severity === 'CRITICAL' ? 'bg-atw-red/20 text-atw-red border border-atw-red/30' : 
                        issue.severity === 'HIGH' ? 'bg-orange-500/20 text-orange-500 border border-orange-500/30' : 
                        'bg-atw-amber/20 text-atw-amber border border-atw-amber/30'
                      }`}>
                        {issue.severity}
                      </span>
                    </div>
                    <h4 className="text-white font-semibold text-sm mb-1">{issue.title}</h4>
                    <p className="text-white/50 text-xs mb-3">{issue.description}</p>
                    <div className="flex justify-between text-[10px] text-white/30">
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

    </div>
  ); 
}