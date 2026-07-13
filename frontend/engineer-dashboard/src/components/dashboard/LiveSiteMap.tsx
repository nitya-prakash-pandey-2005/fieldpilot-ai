"use client";

import React, { useState, useEffect } from 'react';
import { GlassCard } from '../ui/GlassCard';
import { useAPIData } from '@/hooks/useAPIData';
import { StatusBadge } from '../ui/StatusBadge';

const DEMO_ZONES = [
  { id: "A12", name: "Zone A12", risk_score: 0.87, status: "critical", active_issues: 3, coordinates: { x: 45, y: 30 }, description: "Rebar installation in progress" },
  { id: "B3", name: "Zone B3", risk_score: 0.34, status: "medium", active_issues: 1, coordinates: { x: 70, y: 55 }, description: "MEP rough-in complete" },
  { id: "C7", name: "Zone C7", risk_score: 0.12, status: "low", active_issues: 0, coordinates: { x: 25, y: 75 }, description: "Fire suppression inspection passed" },
  { id: "D4", name: "Zone D4", risk_score: 0.61, status: "high", active_issues: 2, coordinates: { x: 60, y: 20 }, description: "Formwork assembly" }
];

export function LiveSiteMap() {
  const { data: zones } = useAPIData('/api/v1/graph/project/P-001/zones', DEMO_ZONES);
  const [activeZone, setActiveZone] = useState<any>(null);

  // Helper to determine style based on risk score
  const getZoneStyle = (score: number) => {
    if (score >= 0.8) return { fill: 'rgba(255,59,59,0.18)', stroke: 'rgba(255,59,59,0.6)', pulse: true, badge: 'CRITICAL' };
    if (score >= 0.6) return { fill: 'rgba(255,140,0,0.15)', stroke: 'rgba(255,140,0,0.5)', pulse: false, badge: 'HIGH' };
    if (score >= 0.3) return { fill: 'rgba(255,179,0,0.12)', stroke: 'rgba(255,179,0,0.4)', pulse: false, badge: 'WARNING' };
    return { fill: 'rgba(0,200,81,0.12)', stroke: 'rgba(0,200,81,0.4)', pulse: false, badge: 'PASS' };
  };

  return (
    <GlassCard className="h-full flex flex-col min-h-[400px]">
      <div className="p-4 border-b border-[var(--border-subtle)] flex items-center justify-between">
        <h2 className="text-sm font-semibold tracking-wide text-[var(--text-primary)] uppercase">Live Site Map</h2>
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
        {zones.map((zone: any) => {
          const style = getZoneStyle(zone.risk_score);
          const isSelected = activeZone?.id === zone.id;
          
          // Custom class for A12 critical pulse
          const isCriticalA12 = zone.id === 'A12';
          
          return (
            <div 
              key={zone.id}
              className={`absolute flex items-center justify-center cursor-pointer transition-all duration-300 pointer-events-auto
                ${style.pulse ? 'animate-pulse' : ''} ${isSelected ? 'scale-110 z-20' : 'hover:scale-105 z-10'}`}
              style={{
                left: `${zone.coordinates.x}%`,
                top: `${zone.coordinates.y}%`,
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
                   {zone.id}
                 </span>
              )}
              {/* Active Observation blip mock */}
              {(zone.id === 'D4' || zone.id === 'C7') && !isCriticalA12 && (
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
              <p className="text-xs text-[var(--text-secondary)]">{activeZone.description}</p>
            </div>
            <button onClick={() => setActiveZone(null)} className="text-[var(--text-muted)] hover:text-white">✕</button>
          </div>
          
          <div className="space-y-4">
            <div className="bg-[var(--bg-surface)] p-3 rounded-lg border border-[var(--border-subtle)]">
              <span className="text-[10px] uppercase text-[var(--text-muted)] tracking-wider">Risk Score</span>
              <div className="text-2xl font-bold font-mono mt-1" style={{ color: getZoneStyle(activeZone.risk_score).stroke }}>
                {(activeZone.risk_score * 100).toFixed(1)}%
              </div>
            </div>
            <div className="bg-[var(--bg-surface)] p-3 rounded-lg border border-[var(--border-subtle)]">
              <span className="text-[10px] uppercase text-[var(--text-muted)] tracking-wider">Active Issues</span>
              <div className="text-xl font-bold mt-1 text-[var(--text-primary)]">
                {activeZone.active_issues} detected
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
