"use client";

import React, { useState } from 'react';
import { GlassCard } from '../ui/GlassCard';
import { StatusBadge } from '../ui/StatusBadge';
import { LiveIndicator } from '../ui/LiveIndicator';
import { useZones, getRiskLevel, Zone } from '@/hooks/useZones';

// Positions are a lookup keyed by zone_code, not real site-plan coordinates
// — the Zone schema has no spatial data yet (would need a BIM/site-plan
// integration to place zones by their actual geometry). Unknown zone codes
// fall back to DEFAULT_POSITION rather than being dropped from the map.
const ZONE_POSITIONS: Record<string, { x: number; y: number }> = {
  A12: { x: 27, y: 27 },
  D4: { x: 72, y: 27 },
  C7: { x: 22, y: 72 },
  B3: { x: 67, y: 72 },
};
const DEFAULT_POSITION = { x: 50, y: 50 };

const DEMO_ZONES: Zone[] = [
  { id: "z-1", zone_code: "A12", name: "Zone A12", current_activity: "Rebar installation in progress", risk_level: "critical", risk_score: 85, active_worker_count: 14, open_issue_count: 3, last_scored_at: "" },
  { id: "z-4", zone_code: "D4", name: "Zone D4", current_activity: "Formwork assembly", risk_level: "elevated", risk_score: 61, active_worker_count: 9, open_issue_count: 2, last_scored_at: "" },
  { id: "z-3", zone_code: "C7", name: "Zone C7", current_activity: "Fire suppression inspection passed", risk_level: "normal", risk_score: 12, active_worker_count: 22, open_issue_count: 0, last_scored_at: "" },
  { id: "z-2", zone_code: "B3", name: "Zone B3", current_activity: "MEP rough-in complete", risk_level: "elevated", risk_score: 45, active_worker_count: 8, open_issue_count: 1, last_scored_at: "" },
];

export function LiveSiteMap() {
  const { zones: liveZones, connectionStatus } = useZones("default-project");
  const zones = liveZones.length > 0 ? liveZones : DEMO_ZONES;
  const [activeZone, setActiveZone] = useState<Zone | null>(null);

  // Helper to determine style based on risk score (0-100), matching the
  // same 3-tier risk model as useZones.getRiskLevel everywhere else in
  // the app instead of a 4th ad hoc "HIGH" tier this component used to
  // invent on its own.
  const getZoneStyle = (score: number) => {
    const level = getRiskLevel(score);
    if (level === 'critical') return { fill: 'rgba(255,59,59,0.18)', stroke: 'rgba(255,59,59,0.6)', pulse: true, badge: 'CRITICAL' };
    if (level === 'elevated') return { fill: 'rgba(255,179,0,0.12)', stroke: 'rgba(255,179,0,0.4)', pulse: false, badge: 'WARNING' };
    return { fill: 'rgba(0,200,81,0.12)', stroke: 'rgba(0,200,81,0.4)', pulse: false, badge: 'PASS' };
  };

  return (
    <GlassCard className="h-full flex flex-col min-h-[400px]">
      <div className="p-4 border-b border-[var(--border-subtle)] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold tracking-wide text-[var(--text-primary)] uppercase">Live Site Map</h2>
          <LiveIndicator isLive={connectionStatus === 'live'} />
        </div>
        <div className="flex gap-3 text-xs text-[var(--text-muted)]">
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-[var(--fail)]" /> Critical</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-[var(--amber)]" /> Warning</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-[var(--pass)]" /> Clear</span>
        </div>
      </div>
      
      <div className="flex-1 relative bg-[#061020] overflow-hidden site-map-container" style={{
        backgroundImage: 'linear-gradient(rgba(0,212,255,0.025) 1px, transparent 1px), linear-gradient(90deg, rgba(0,212,255,0.025) 1px, transparent 1px)',
        backgroundSize: '24px 24px'
      }}>
        <svg width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 pointer-events-none">
          {/* Building outlines */}
          <rect x="5" y="5" width="90" height="90" fill="rgba(0,212,255,0.02)" stroke="#00D4FF" strokeWidth="1.5" rx="4" />
          
          {/* Internal walls */}
          <line x1="5" y1="50" x2="95" y2="50" stroke="#00D4FF" strokeWidth="0.5" />
          <line x1="50" y1="5" x2="50" y2="50" stroke="#00D4FF" strokeWidth="0.5" />
          <line x1="40" y1="50" x2="40" y2="95" stroke="#00D4FF" strokeWidth="0.5" />
          
          {/* Column grid dots at 20px intervals approx */}
          {[20, 40, 60, 80].map((cx) => (
            [20, 40, 60, 80].map((cy) => (
              <circle key={`${cx}-${cy}`} cx={cx} cy={cy} r="0.5" fill="rgba(0,212,255,0.15)" />
            ))
          ))}
          
          {/* Compass rose (N Arrow) top right */}
          <g transform="translate(85, 10)">
            <path d="M0 -3 L-2 3 L0 2 L2 3 Z" fill="#00D4FF" />
            <text x="0" y="5" fill="#00D4FF" fontSize="3" textAnchor="middle" fontFamily="var(--font-mono)">N</text>
          </g>
          
          {/* Scale bar bottom left */}
          <g transform="translate(10, 90)">
            <line x1="0" y1="0" x2="20" y2="0" stroke="rgba(255,255,255,0.4)" strokeWidth="0.2" />
            <line x1="0" y1="-1" x2="0" y2="1" stroke="rgba(255,255,255,0.4)" strokeWidth="0.2" />
            <line x1="10" y1="-1" x2="10" y2="1" stroke="rgba(255,255,255,0.4)" strokeWidth="0.2" />
            <line x1="20" y1="-1" x2="20" y2="1" stroke="rgba(255,255,255,0.4)" strokeWidth="0.2" />
            <text x="0" y="3" fill="rgba(255,255,255,0.4)" fontSize="2" textAnchor="middle" fontFamily="var(--font-mono)">0</text>
            <text x="10" y="3" fill="rgba(255,255,255,0.4)" fontSize="2" textAnchor="middle" fontFamily="var(--font-mono)">10</text>
            <text x="20" y="3" fill="rgba(255,255,255,0.4)" fontSize="2" textAnchor="middle" fontFamily="var(--font-mono)">20m</text>
          </g>

          {/* Zones Backgrounds (Filled Polygons/Rects for the 4 quadrants) */}
          {/* Top Left (A12) */}
          <rect x="5" y="5" width="45" height="45" fill="rgba(255,59,59,0.12)" rx="4" />
          <text x="7" y="10" fill="var(--text-muted)" fontSize="3" fontFamily="var(--font-mono)">ZONE A12</text>
          
          {/* Top Right (D4) */}
          <rect x="50" y="5" width="45" height="45" fill="rgba(255,107,0,0.10)" rx="4" />
          <text x="52" y="10" fill="var(--text-muted)" fontSize="3" fontFamily="var(--font-mono)">ZONE D4</text>

          {/* Bottom Left (C7) */}
          <rect x="5" y="50" width="35" height="45" fill="rgba(0,200,81,0.08)" rx="4" />
          <text x="7" y="55" fill="var(--text-muted)" fontSize="3" fontFamily="var(--font-mono)">ZONE C7</text>

          {/* Bottom Right (B3) */}
          <rect x="40" y="50" width="55" height="45" fill="rgba(255,179,0,0.08)" rx="4" />
          <text x="42" y="55" fill="var(--text-muted)" fontSize="3" fontFamily="var(--font-mono)">ZONE B3</text>
        </svg>

        {/* Floating active markers for zones */}
        {zones.map((zone: Zone) => {
          const style = getZoneStyle(zone.risk_score);
          const isSelected = activeZone?.id === zone.id;
          const pos = ZONE_POSITIONS[zone.zone_code] || DEFAULT_POSITION;

          // Custom class for A12 critical pulse
          const isCriticalA12 = zone.zone_code === 'A12';

          return (
            <div
              key={zone.id}
              className={`absolute flex items-center justify-center cursor-pointer transition-all duration-300 pointer-events-auto
                ${style.pulse ? 'animate-pulse' : ''} ${isSelected ? 'scale-110 z-20' : 'hover:scale-105 z-10'}`}
              style={{
                left: `${pos.x}%`,
                top: `${pos.y}%`,
                width: isCriticalA12 ? '45%' : '8%', // For A12 we want to highlight the whole room if selected, but for now just place a marker
                height: isCriticalA12 ? '45%' : '8%',
                transform: isCriticalA12 ? 'translate(-38.8%, -38.8%)' : 'translate(-50%, -50%)', // Centered on A12
                border: isCriticalA12 ? `2px dashed rgba(255,59,59,0.8)` : `1px solid ${style.stroke}`,
                backgroundColor: isCriticalA12 ? 'transparent' : style.fill,
                borderRadius: isCriticalA12 ? '4px' : '50%',
                animation: isCriticalA12 ? 'dashOffset 1s linear infinite' : 'none'
              }}
              onClick={() => setActiveZone(zone)}
            >
              {/* Only show pin dot for non-A12 for cleaner look, A12 gets the dashed border */}
              {!isCriticalA12 && (
                 <span className="text-[8px] font-bold text-white tracking-widest bg-black/40 px-1 py-0.5 rounded backdrop-blur-sm" style={{ fontFamily: 'var(--font-mono)' }}>
                   {zone.zone_code}
                 </span>
              )}
              {/* Active Observation blip when this zone has open issues */}
              {zone.open_issue_count > 0 && !isCriticalA12 && (
                <div className="absolute w-2 h-2 rounded-full bg-[var(--cyan)] shadow-[0_0_8px_var(--cyan)] animate-ping" />
              )}
            </div>
          );
        })}
      </div>

      {/* Zone Detail Drawer Overlay */}
      {activeZone && (
        <div className="absolute top-0 right-0 w-[280px] h-full bg-[var(--bg-elevated)]/95 backdrop-blur-md border-l border-[var(--border-subtle)] p-5 animate-fade-in z-30 flex flex-col">
          <div className="flex justify-between items-start mb-4">
            <div>
              <div className="flex items-center gap-2 mb-1">
                <h3 className="text-xl font-bold font-mono text-[var(--text-primary)]">{activeZone.name}</h3>
                <StatusBadge status={getZoneStyle(activeZone.risk_score).badge} />
              </div>
              <p className="text-xs text-[var(--text-secondary)]">{activeZone.current_activity}</p>
            </div>
            <button onClick={() => setActiveZone(null)} className="text-[var(--text-muted)] hover:text-white">✕</button>
          </div>
          
          <div className="space-y-4">
            <div className="bg-[var(--bg-surface)] p-3 rounded-lg border border-[var(--border-subtle)]">
              <span className="text-[10px] uppercase text-[var(--text-muted)] tracking-wider">Risk Score</span>
              <div className="text-2xl font-bold font-mono mt-1" style={{ color: getZoneStyle(activeZone.risk_score).stroke }}>
                {activeZone.risk_score.toFixed(1)}%
              </div>
            </div>
            <div className="bg-[var(--bg-surface)] p-3 rounded-lg border border-[var(--border-subtle)]">
              <span className="text-[10px] uppercase text-[var(--text-muted)] tracking-wider">Active Issues</span>
              <div className="text-xl font-bold mt-1 text-[var(--text-primary)]">
                {activeZone.open_issue_count} detected
              </div>
            </div>
            <button className="w-full py-2.5 bg-[var(--cyan-dim)] text-[var(--cyan)] border border-[var(--cyan)]/30 rounded-lg text-xs font-bold tracking-widest hover:bg-[var(--cyan)]/20 transition-colors">
              VIEW FULL DETAILS
            </button>
          </div>
        </div>
      )}
    </GlassCard>
  );
}
