"use client";
import {
  Bell, AlertTriangle, AlertCircle, Info, CheckCircle2, XCircle,
  MessageCircle, Mail, Smartphone, Hash, Monitor, RefreshCw,
  Search, ChevronDown, ChevronUp, FlaskConical,
} from 'lucide-react';
import { toast } from 'sonner';
import { useState, useEffect, useMemo, useCallback } from 'react';
import { formatDistanceToNow, format } from 'date-fns';
import { LiveIndicator } from '@/components/ui/LiveIndicator';
import { GlassCard } from '@/components/ui/GlassCard';

const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
const POLL_INTERVAL_MS = 20_000;

// Shape matches GET /api/v1/notification/active (api/routes/notification.py
// — real audit-log rows from agents/notification/router.py's dispatch
// calls). dispatch_results carries the real per-channel outcome (success,
// delivered_at, error, whether a mock provider stood in for a missing
// credential) written by NotificationRouter._log_to_db — previously fetched
// but never rendered, so failed/simulated channels were indistinguishable
// from delivered ones in the UI.
interface DispatchResult {
  channel: string;
  success: boolean;
  delivered_at: string | null;
  error: string | null;
  mock_used: boolean;
}

interface NotificationRow {
  id: string;
  notification_id: string;
  incident_id: string | null;
  severity: string;
  zone_id: string | null;
  asset_id: string | null;
  channels_attempted: string[];
  channels_delivered: string[];
  dispatch_results: DispatchResult[];
  mock_channels: string[];
  created_at: string;
}

const DEMO_NOTIFICATIONS: NotificationRow[] = [
  {
    id: 'n1', notification_id: 'n1', incident_id: 'asset-rebar-42', severity: 'CRITICAL',
    zone_id: 'A12', asset_id: 'asset-rebar-42',
    channels_attempted: ['whatsapp', 'slack', 'email', 'sms'],
    channels_delivered: ['whatsapp', 'slack', 'email', 'sms'],
    dispatch_results: [
      { channel: 'whatsapp', success: true, delivered_at: new Date(Date.now() - 2 * 60 * 1000).toISOString(), error: null, mock_used: true },
      { channel: 'slack', success: true, delivered_at: new Date(Date.now() - 2 * 60 * 1000).toISOString(), error: null, mock_used: true },
      { channel: 'email', success: true, delivered_at: new Date(Date.now() - 2 * 60 * 1000).toISOString(), error: null, mock_used: true },
      { channel: 'sms', success: true, delivered_at: new Date(Date.now() - 2 * 60 * 1000).toISOString(), error: null, mock_used: true },
    ],
    mock_channels: ['whatsapp', 'slack', 'email', 'sms'],
    created_at: new Date(Date.now() - 2 * 60 * 1000).toISOString(),
  },
  {
    id: 'n2', notification_id: 'n2', incident_id: 'drawing-S101', severity: 'HIGH',
    zone_id: 'B3', asset_id: 'drawing-S101',
    channels_attempted: ['whatsapp', 'slack', 'email'],
    channels_delivered: ['whatsapp', 'email'],
    dispatch_results: [
      { channel: 'whatsapp', success: true, delivered_at: new Date(Date.now() - 8 * 60 * 1000).toISOString(), error: null, mock_used: true },
      { channel: 'slack', success: false, delivered_at: null, error: 'SLACK_WEBHOOK_URL is missing', mock_used: false },
      { channel: 'email', success: true, delivered_at: new Date(Date.now() - 8 * 60 * 1000).toISOString(), error: null, mock_used: true },
    ],
    mock_channels: ['whatsapp', 'email'],
    created_at: new Date(Date.now() - 8 * 60 * 1000).toISOString(),
  },
];

const SEVERITY_CONFIG: Record<string, { color: string; dim: string; icon: typeof AlertTriangle; label: string }> = {
  CRITICAL: { color: 'var(--fail)', dim: 'var(--fail-dim)', icon: AlertTriangle, label: 'Critical' },
  HIGH: { color: 'var(--amber)', dim: 'var(--amber-dim)', icon: AlertCircle, label: 'High' },
  MEDIUM: { color: 'var(--cyan)', dim: 'var(--cyan-dim)', icon: Info, label: 'Medium' },
  LOW: { color: 'var(--text-muted)', dim: 'var(--bg-elevated)', icon: Info, label: 'Low' },
};

const CHANNEL_CONFIG: Record<string, { icon: typeof Mail; label: string }> = {
  whatsapp: { icon: MessageCircle, label: 'WhatsApp' },
  slack: { icon: Hash, label: 'Slack' },
  email: { icon: Mail, label: 'Email' },
  sms: { icon: Smartphone, label: 'SMS' },
  in_app: { icon: Monitor, label: 'In-App' },
};

const CHANNEL_ORDER = ['whatsapp', 'slack', 'email', 'sms', 'in_app'];

// Mirrors NotificationRouter.severity_matrix in agents/notification/router.py
// — real routing behavior, not a mockup of it. If that matrix changes, this
// falls out of sync with the actual code (there's no shared source of truth
// between Python and TS here), but it's what the router genuinely does today.
const SEVERITY_MATRIX: Record<string, string[]> = {
  CRITICAL: ['whatsapp', 'slack', 'email', 'sms'],
  HIGH: ['whatsapp', 'slack', 'email'],
  MEDIUM: ['whatsapp', 'in_app'],
  LOW: ['in_app'],
};

function severityConfig(sev: string) {
  return SEVERITY_CONFIG[sev] || SEVERITY_CONFIG.LOW;
}

export default function NotificationsPage() {
  const [notifications, setNotifications] = useState<NotificationRow[]>(DEMO_NOTIFICATIONS);
  const [acknowledged, setAcknowledged] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [isLive, setIsLive] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [severityFilter, setSeverityFilter] = useState('ALL');
  const [search, setSearch] = useState('');

  const load = useCallback(async (showSpinner: boolean) => {
    if (showSpinner) setIsRefreshing(true);
    try {
      const res = await fetch(`${API}/api/v1/notification/active`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (data.data) {
        setNotifications(data.data);
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

  const stats = useMemo(() => {
    const bySeverity: Record<string, number> = { CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0 };
    let attempted = 0, delivered = 0, simulated = 0;
    for (const n of notifications) {
      bySeverity[n.severity] = (bySeverity[n.severity] || 0) + 1;
      attempted += n.channels_attempted?.length || 0;
      delivered += n.channels_delivered?.length || 0;
      if (n.mock_channels?.length > 0) simulated += 1;
    }
    const deliveryRate = attempted > 0 ? Math.round((delivered / attempted) * 100) : 0;
    return { total: notifications.length, bySeverity, deliveryRate, simulated };
  }, [notifications]);

  const channelStats = useMemo(() => {
    const stats: Record<string, { attempted: number; delivered: number; mocked: number }> = {};
    for (const n of notifications) {
      const delivered = new Set(n.channels_delivered || []);
      const mocked = new Set(n.mock_channels || []);
      for (const ch of n.channels_attempted || []) {
        if (!stats[ch]) stats[ch] = { attempted: 0, delivered: 0, mocked: 0 };
        stats[ch].attempted += 1;
        if (delivered.has(ch)) stats[ch].delivered += 1;
        if (mocked.has(ch)) stats[ch].mocked += 1;
      }
    }
    return stats;
  }, [notifications]);

  const filtered = notifications.filter(n => {
    if (severityFilter !== 'ALL' && n.severity !== severityFilter) return false;
    if (search) {
      const haystack = `${n.zone_id || ''} ${n.asset_id || ''} ${n.incident_id || ''} ${n.notification_id || ''}`.toLowerCase();
      if (!haystack.includes(search.toLowerCase())) return false;
    }
    return true;
  });

  const markAllRead = () => {
    setAcknowledged(new Set(notifications.map(n => n.id)));
    toast.success("All notifications acknowledged.");
  };

  const toggleExpanded = (id: string) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  return (
    <div className="h-full p-8 flex flex-col min-h-0 bg-[var(--bg-base)]">
      <div className="flex items-center justify-between mb-6 flex-wrap gap-4">
        <div>
          <h1 className="text-3xl font-bold text-[var(--text-primary)] tracking-tight flex items-center gap-3">
            <Bell className="text-[var(--text-secondary)]" size={32} />
            Notifications
            <LiveIndicator isLive={isLive} />
          </h1>
          <p className="text-[var(--text-secondary)] mt-2">Agent 9 routing layer for alerts, incidents, and tasks — real dispatch audit log across WhatsApp, Slack, Email, and SMS.</p>
        </div>

        <div className="flex gap-3">
          <button
            disabled={isRefreshing}
            className="bg-[var(--bg-elevated)] hover:bg-[var(--bg-hover)] text-[var(--text-secondary)] border border-[var(--border-subtle)] px-4 py-2 rounded-lg font-semibold flex items-center gap-2 transition-all cursor-pointer disabled:opacity-50"
            onClick={() => load(true)}
          >
            <RefreshCw size={16} className={isRefreshing ? 'animate-spin' : ''} /> Refresh
          </button>
          <button
            className="bg-[var(--bg-elevated)] hover:bg-[var(--bg-hover)] text-[var(--text-secondary)] border border-[var(--border-subtle)] px-4 py-2 rounded-lg font-semibold flex items-center gap-2 transition-all cursor-pointer"
            onClick={markAllRead}
          >
            <CheckCircle2 size={16} /> Mark All Read
          </button>
        </div>
      </div>

      {/* Summary stats */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
        <GlassCard className="p-4">
          <div className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] font-bold mb-1">Total (last 20)</div>
          <div className="text-2xl font-bold font-mono text-[var(--text-primary)]">{stats.total}</div>
        </GlassCard>
        {(['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] as const).map(sev => {
          const cfg = severityConfig(sev);
          return (
            <GlassCard key={sev} className="p-4" accentColor={cfg.color}>
              <div className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] font-bold mb-1">{cfg.label}</div>
              <div className="text-2xl font-bold font-mono" style={{ color: cfg.color }}>{stats.bySeverity[sev] || 0}</div>
            </GlassCard>
          );
        })}
      </div>

      <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-[var(--text-muted)]" size={16} />
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search by zone, asset, incident…"
              className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-lg pl-10 pr-4 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--cyan)]/50 transition-colors w-72"
            />
          </div>
          <div className="flex gap-1.5">
            {(['ALL', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] as const).map(sev => (
              <button
                key={sev}
                onClick={() => setSeverityFilter(sev)}
                className={`text-xs font-bold uppercase tracking-wider px-3 py-1.5 rounded-full border transition-colors cursor-pointer ${
                  severityFilter === sev
                    ? 'bg-[var(--cyan-dim)] border-[var(--cyan)]/40 text-[var(--cyan)]'
                    : 'bg-[var(--bg-elevated)] border-[var(--border-subtle)] text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
                }`}
              >
                {sev === 'ALL' ? 'All' : severityConfig(sev).label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-4 text-xs text-[var(--text-muted)]">
          <span>Delivery rate: <span className="font-mono font-bold text-[var(--pass)]">{stats.deliveryRate}%</span></span>
          {stats.simulated > 0 && (
            <span className="flex items-center gap-1.5">
              <FlaskConical size={12} /> {stats.simulated} simulated (no Slack/Twilio credentials configured)
            </span>
          )}
        </div>
      </div>

      <div className="flex-1 grid grid-cols-1 xl:grid-cols-[1fr_320px] gap-6 min-h-0">
      <div className="overflow-y-auto min-h-0">
        <div className="flex flex-col gap-3 pb-10">
          {filtered.map((notif) => {
            const isRead = acknowledged.has(notif.id);
            const isOpen = expanded.has(notif.id);
            const cfg = severityConfig(notif.severity);
            const Icon = cfg.icon;
            const attempted = notif.channels_attempted || [];
            const delivered = new Set(notif.channels_delivered || []);
            const mocked = new Set(notif.mock_channels || []);
            const resultsByChannel = new Map((notif.dispatch_results || []).map(r => [r.channel, r]));

            return (
              <div
                key={notif.id}
                className={`rounded-xl border transition-all ${
                  isRead ? 'bg-[var(--bg-elevated)] border-[var(--border-subtle)] opacity-70' : 'bg-[var(--bg-surface)] border-[var(--border-subtle)] shadow-lg'
                }`}
              >
                <div className="p-5 flex gap-4">
                  <div className="mt-1">
                    <div className="w-10 h-10 rounded-full flex items-center justify-center border" style={{ backgroundColor: cfg.dim, borderColor: `${cfg.color}4D` }}>
                      <Icon size={18} style={{ color: cfg.color }} />
                    </div>
                  </div>

                  <div className="flex-1 min-w-0">
                    <div className="flex justify-between items-start mb-1 gap-3">
                      <h3 className={`font-semibold text-lg ${isRead ? 'text-[var(--text-muted)]' : 'text-[var(--text-primary)]'}`}>
                        {cfg.label} — Zone {notif.zone_id || 'n/a'}
                      </h3>
                      <span
                        className="text-xs text-[var(--text-muted)] whitespace-nowrap shrink-0"
                        title={(() => { try { return format(new Date(notif.created_at), 'PPpp'); } catch { return ''; } })()}
                      >
                        {(() => { try { return formatDistanceToNow(new Date(notif.created_at), { addSuffix: true }); } catch { return ''; } })()}
                      </span>
                    </div>

                    <p className={`text-sm ${isRead ? 'text-[var(--text-muted)]' : 'text-[var(--text-secondary)]'}`}>
                      Asset <span className="font-mono">{notif.asset_id || 'n/a'}</span>
                      {notif.incident_id && notif.incident_id !== notif.asset_id && (
                        <> · Incident <span className="font-mono">{notif.incident_id}</span></>
                      )}
                    </p>

                    {/* Per-channel delivery breakdown */}
                    <div className="flex flex-wrap gap-2 mt-3">
                      {attempted.map(ch => {
                        const chCfg = CHANNEL_CONFIG[ch] || { icon: Bell, label: ch };
                        const ChIcon = chCfg.icon;
                        const ok = delivered.has(ch);
                        const isMock = mocked.has(ch);
                        return (
                          <span
                            key={ch}
                            className={`flex items-center gap-1.5 text-[11px] font-semibold px-2.5 py-1 rounded-full border ${
                              ok
                                ? 'bg-[var(--pass-dim)] text-[var(--pass)] border-[var(--pass)]/25'
                                : 'bg-[var(--fail-dim)] text-[var(--fail)] border-[var(--fail)]/25'
                            }`}
                          >
                            <ChIcon size={11} />
                            {chCfg.label}
                            {ok ? <CheckCircle2 size={11} /> : <XCircle size={11} />}
                            {isMock && <span className="opacity-70 italic">(sim)</span>}
                          </span>
                        );
                      })}
                      {attempted.length === 0 && (
                        <span className="text-xs text-[var(--text-muted)] italic">No channels attempted.</span>
                      )}
                    </div>

                    {/* Expandable per-channel detail */}
                    {attempted.length > 0 && (
                      <button
                        onClick={() => toggleExpanded(notif.id)}
                        className="mt-3 flex items-center gap-1 text-[11px] font-semibold text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-colors cursor-pointer"
                      >
                        {isOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                        {isOpen ? 'Hide dispatch details' : 'Show dispatch details'}
                      </button>
                    )}
                    {isOpen && (
                      <div className="mt-2 border border-[var(--border-subtle)] rounded-lg divide-y divide-[var(--border-subtle)] overflow-hidden">
                        {attempted.map(ch => {
                          const r = resultsByChannel.get(ch);
                          const chCfg = CHANNEL_CONFIG[ch] || { icon: Bell, label: ch };
                          const ChIcon = chCfg.icon;
                          return (
                            <div key={ch} className="flex items-center justify-between px-3 py-2 text-xs bg-[var(--bg-elevated)]">
                              <span className="flex items-center gap-2 text-[var(--text-secondary)] font-semibold">
                                <ChIcon size={12} /> {chCfg.label}
                              </span>
                              {r?.success ? (
                                <span className="text-[var(--pass)] font-mono">
                                  delivered {r.delivered_at ? (() => { try { return formatDistanceToNow(new Date(r.delivered_at!), { addSuffix: true }); } catch { return ''; } })() : ''}
                                  {r.mock_used && ' · simulated'}
                                </span>
                              ) : (
                                <span className="text-[var(--fail)] font-mono truncate max-w-[240px]" title={r?.error || 'unknown error'}>
                                  failed{r?.error ? `: ${r.error}` : ''}
                                </span>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}

                    {!isRead && (
                      <div className="mt-4 flex gap-3">
                        <button
                          onClick={() => {
                            setAcknowledged(prev => new Set(prev).add(notif.id));
                            toast.success('Acknowledged.');
                          }}
                          className="bg-[var(--bg-elevated)] hover:bg-[var(--bg-hover)] text-[var(--text-primary)] text-xs font-semibold px-4 py-2 rounded-lg transition-colors cursor-pointer border border-[var(--border-subtle)]"
                        >
                          Acknowledge
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            );
          })}

          {filtered.length === 0 && notifications.length > 0 && (
            <div className="text-center text-[var(--text-muted)] py-20">No notifications match your filters.</div>
          )}
          {notifications.length === 0 && (
            <div className="text-center text-[var(--text-muted)] py-20">No notifications yet.</div>
          )}
        </div>
      </div>

      {/* Sidebar: channel health + routing matrix, both derived from real data/logic */}
      <div className="overflow-y-auto min-h-0 flex flex-col gap-6 pb-10">
        <GlassCard className="p-5" accentColor="var(--cyan)">
          <h3 className="text-xs font-bold uppercase tracking-widest text-[var(--text-primary)] mb-4">Channel Health</h3>
          <div className="flex flex-col gap-3">
            {CHANNEL_ORDER.filter(ch => channelStats[ch]).map(ch => {
              const s = channelStats[ch];
              const chCfg = CHANNEL_CONFIG[ch];
              const ChIcon = chCfg.icon;
              const rate = s.attempted > 0 ? Math.round((s.delivered / s.attempted) * 100) : 0;
              return (
                <div key={ch}>
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="flex items-center gap-2 text-xs font-semibold text-[var(--text-secondary)]">
                      <ChIcon size={13} /> {chCfg.label}
                    </span>
                    <span className="text-xs font-mono text-[var(--text-muted)]">
                      {s.delivered}/{s.attempted}
                      {s.mocked > 0 && <span className="italic"> ({s.mocked} sim)</span>}
                    </span>
                  </div>
                  <div className="h-1.5 rounded-full bg-[var(--bg-elevated)] overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all"
                      style={{ width: `${rate}%`, backgroundColor: rate >= 90 ? 'var(--pass)' : rate >= 50 ? 'var(--amber)' : 'var(--fail)' }}
                    />
                  </div>
                </div>
              );
            })}
            {Object.keys(channelStats).length === 0 && (
              <p className="text-xs text-[var(--text-muted)] italic">No dispatch activity yet.</p>
            )}
          </div>
        </GlassCard>

        <GlassCard className="p-5" accentColor="var(--purple)">
          <h3 className="text-xs font-bold uppercase tracking-widest text-[var(--text-primary)] mb-1">Severity Routing Matrix</h3>
          <p className="text-[11px] text-[var(--text-muted)] mb-4">Which channels Agent 9 dispatches to per severity level.</p>
          <div className="flex flex-col gap-3">
            {(['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] as const).map(sev => {
              const cfg = severityConfig(sev);
              return (
                <div key={sev} className="flex items-start justify-between gap-3">
                  <span className="text-[11px] font-bold uppercase tracking-wider px-2 py-0.5 rounded shrink-0" style={{ backgroundColor: cfg.dim, color: cfg.color }}>
                    {cfg.label}
                  </span>
                  <div className="flex flex-wrap gap-1.5 justify-end">
                    {SEVERITY_MATRIX[sev].map(ch => {
                      const chCfg = CHANNEL_CONFIG[ch];
                      const ChIcon = chCfg.icon;
                      return (
                        <span key={ch} className="flex items-center gap-1 text-[10px] font-semibold px-1.5 py-0.5 rounded bg-[var(--bg-elevated)] text-[var(--text-secondary)] border border-[var(--border-subtle)]">
                          <ChIcon size={10} /> {chCfg.label}
                        </span>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        </GlassCard>
      </div>
      </div>
    </div>
  );
}
