"use client";

import React from 'react';
import { useAPIData } from '@/hooks/useAPIData';
import { useCountUp } from '@/hooks/useCountUp';

// There is deliberately no DEMO_KPI fallback.
//
// This component used to carry one, holding the pitch deck's illustrative
// figures (23 RFIs avoided, 340 hours saved). The API did not return those two
// fields at all, so every page load quietly substituted deck numbers — and they
// rendered identically to the two tiles that were genuinely measured. A viewer
// had no way to tell which was which, which is precisely the fabricated-metrics
// problem Follow.md §8.3 warns about.
//
// Now: the backend computes all four from resolved incidents, and anything it
// cannot compute renders as "—". An empty tile is honest; a borrowed one is not.

export function KPIBar() {
  const { data: stats, isLive, error } = useAPIData('/api/v1/learning/stats');

  const trend = stats?.trend;

  // One real period-over-period comparison, shown only where it exists. The
  // previous "+23% vs last month" strings were hardcoded on every tile and
  // claimed a trend nobody had measured.
  const costTrend = trend?.cost_pct_change;
  const incidentTrend = trend?.incidents_pct_change;

  const fmtTrend = (pct: number | null | undefined): string =>
    pct === null || pct === undefined
      ? `no prior ${trend?.window_days ?? 30}-day period to compare`
      : `${pct >= 0 ? '+' : ''}${pct}% vs previous ${trend?.window_days ?? 30} days`;

  const kpis = [
    {
      label: "RFIs Avoided",
      value: useCountUp(stats?.rfis_avoided ?? 0),
      available: stats?.rfis_avoided !== undefined,
      prefix: "",
      suffix: "",
      icon: "🔮",
      trend: fmtTrend(incidentTrend),
      note: stats?.definitions?.rfis_avoided,
      color: "var(--purple)"
    },
    {
      label: "Cost Saved",
      value: useCountUp(stats?.total_cost_avoided_usd ?? 0),
      available: stats?.total_cost_avoided_usd !== undefined,
      prefix: "$",
      suffix: "",
      icon: "💰",
      trend: fmtTrend(costTrend),
      note: stats?.definitions?.total_cost_avoided_usd,
      color: "var(--pass)"
    },
    {
      label: "Hours Saved",
      value: useCountUp(stats?.time_saved_hours ?? 0),
      available: stats?.time_saved_hours !== undefined,
      prefix: "",
      suffix: "h",
      icon: "⏱",
      trend: stats?.assumptions?.baseline_rfi_cycle_hours
        ? `derived · ${stats.assumptions.baseline_rfi_cycle_hours}h baseline RFI cycle`
        : fmtTrend(incidentTrend),
      note: stats?.definitions?.time_saved_hours,
      color: "var(--cyan)"
    },
    {
      label: "Rework Prevented",
      value: useCountUp(stats?.rework_prevented_count ?? 0),
      available: stats?.rework_prevented_count !== undefined,
      prefix: "",
      suffix: " events",
      icon: "🛡",
      trend: fmtTrend(incidentTrend),
      note: stats?.definitions?.rework_prevented_count,
      color: "var(--amber)"
    }
  ];

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4 mb-6">
      {/* No progress bar under these tiles any more. It was width-derived from
          the number of digits in the value — a bar that moved when a figure
          crossed 999 and encoded nothing at all. */}
      {kpis.map((kpi, idx) => {
        const dir = kpi.trend.startsWith('+') ? 'up'
                  : kpi.trend.startsWith('-') ? 'down' : 'flat';
        const dirStyle = dir === 'up'
          ? { bg: 'var(--pass-dim)', fg: 'var(--pass)', glyph: '↗' }
          : dir === 'down'
          ? { bg: 'var(--fail-dim)', fg: 'var(--fail)', glyph: '↘' }
          : { bg: 'var(--bg-elevated)', fg: 'var(--text-muted)', glyph: '·' };

        return (
        <div
          key={idx}
          className="bg-gradient-to-b from-[var(--bg-surface-lighter)] to-[var(--bg-surface)] backdrop-blur-[20px] rounded-xl border border-[var(--border-subtle)] relative overflow-hidden shadow-lg p-5 flex flex-col justify-between animate-fade-in"
          style={{ animationDelay: `${idx * 150}ms` }}
          title={kpi.note || undefined}
        >
          <div className="flex items-start justify-between mb-4">
            <span className="text-sm font-semibold text-[var(--text-secondary)] uppercase tracking-wider">{kpi.label}</span>
            <span className="text-2xl">{kpi.icon}</span>
          </div>

          <div className="flex items-baseline gap-1 mt-1 mb-2">
            {kpi.available ? (
              <span className="text-[44px] leading-none font-bold tracking-tight" style={{ fontFamily: 'var(--font-display)', color: kpi.color }}>
                {kpi.prefix}{kpi.value.toLocaleString()}{kpi.suffix}
              </span>
            ) : (
              <span className="text-[44px] leading-none font-bold tracking-tight text-[var(--text-muted)]"
                    style={{ fontFamily: 'var(--font-display)' }}
                    title={error ? `Metrics unavailable: ${error}` : 'Not yet computed'}>
                —
              </span>
            )}
          </div>

          <div className="mt-2 flex items-center gap-1.5 mb-2">
            <span className="text-[10px] px-1.5 py-0.5 rounded font-bold"
                  style={{ background: dirStyle.bg, color: dirStyle.fg }}>
              {dirStyle.glyph}
            </span>
            <span className="text-xs text-[var(--text-muted)]">
              {kpi.available ? kpi.trend : (error ? 'backend unreachable' : 'no data recorded yet')}
            </span>
          </div>
        </div>
        );
      })}
    </div>
  );
}
