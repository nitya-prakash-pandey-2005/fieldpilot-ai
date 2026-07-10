import React, { useEffect, useState } from 'react';
import { mockZones } from '@/data/mockData';
import { Activity, ShieldAlert, X } from 'lucide-react';

interface ZoneState {
  id: string;
  status: 'GREEN' | 'AMBER' | 'RED';
  x: number;
  y: number;
  w: number;
  h: number;
}

export default function LiveSiteMap({ lastEvent }: { lastEvent?: any }) {
  const [zones, setZones] = useState<ZoneState[]>([
    { id: 'A12', status: mockZones.find(z => z.id === 'A12')?.status as any || 'RED', x: 105, y: 105, w: 190, h: 190 },
    { id: 'B3', status: mockZones.find(z => z.id === 'B3')?.status as any || 'AMBER', x: 305, y: 105, w: 190, h: 190 },
    { id: 'C7', status: mockZones.find(z => z.id === 'C7')?.status as any || 'GREEN', x: 505, y: 105, w: 190, h: 390 }
  ]);
  const [activeDots, setActiveDots] = useState<any[]>([]);
  const [selectedZoneId, setSelectedZoneId] = useState<string | null>(null);

  const selectedZoneData = mockZones.find(z => z.id === selectedZoneId);

  // Use mock data immediately, no need to fetch for this demo
  /*
  useEffect(() => { ... }, []);
  */

  useEffect(() => {
    if (!lastEvent) return;
    
    // 1. Update Zone Status
    setZones(prev => prev.map(z => {
      if (z.id === lastEvent.zone_id) {
        let newStatus = z.status;
        if (lastEvent.compliance_status === 'CRITICAL') newStatus = 'RED';
        else if (lastEvent.compliance_status === 'FAIL') newStatus = 'AMBER';
        return { ...z, status: newStatus as any };
      }
      return z;
    }));
    
    // 2. Add Pulsing Dot
    const targetZone = zones.find(z => z.id === lastEvent.zone_id);
    if (targetZone) {
      const newDot = {
        id: Date.now(),
        // Random coordinate within the zone
        x: targetZone.x + Math.random() * (targetZone.w - 20) + 10,
        y: targetZone.y + Math.random() * (targetZone.h - 20) + 10,
        color: lastEvent.compliance_status === 'CRITICAL' ? '#FF3B3B' : '#FFB300'
      };
      
      setActiveDots(prev => [...prev, newDot]);
      
      // Remove dot after 5 seconds to simulate issue resolution or transient event
      setTimeout(() => {
        setActiveDots(prev => prev.filter(d => d.id !== newDot.id));
      }, 5000);
    }
  }, [lastEvent]);


  const getZoneColor = (status: string) => {
    switch (status) {
      case 'RED': return { fill: 'rgba(255, 59, 59, 0.2)', stroke: '#FF3B3B', glow: 'drop-shadow(0 0 10px rgba(255,59,59,0.8))' };
      case 'AMBER': return { fill: 'rgba(255, 179, 0, 0.2)', stroke: '#FFB300', glow: 'none' };
      case 'GREEN': default: return { fill: 'rgba(0, 212, 255, 0.05)', stroke: 'transparent', glow: 'none' };
    }
  };

  return (
    <div className="absolute inset-0 rounded-xl border border-white/10 bg-[#0A1628]/80 backdrop-blur-md overflow-hidden p-4 shadow-2xl">
      <h2 className="text-sm font-semibold tracking-wide text-white/80 absolute top-4 left-4 z-10 flex items-center gap-2 uppercase">
        Live Digital Twin
      </h2>
      
      {/* Blueprint SVG */}
      <svg 
        viewBox="0 0 800 600" 
        className="w-full h-full object-contain opacity-90"
        xmlns="http://www.w3.org/2000/svg"
      >
        {/* Grid Pattern */}
        <defs>
          <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
            <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#1E3A5F" strokeWidth="1" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#grid)" />

        {/* Structural Walls */}
        <path d="M 100 100 L 700 100 L 700 500 L 100 500 Z" fill="none" stroke="#00D4FF" strokeWidth="3" opacity="0.7" />
        <path d="M 300 100 L 300 300 L 100 300" fill="none" stroke="#00D4FF" strokeWidth="3" opacity="0.7" />
        <path d="M 500 100 L 500 500" fill="none" stroke="#00D4FF" strokeWidth="3" opacity="0.7" />
        <path d="M 300 300 L 500 300" fill="none" stroke="#00D4FF" strokeWidth="3" opacity="0.7" />

        {/* Zones */}
        {zones.map(z => {
          const colors = getZoneColor(z.status);
          const isSelected = selectedZoneId === z.id;
          return (
            <g 
              key={z.id} 
              className="cursor-pointer transition-all duration-500 hover:opacity-100 group" 
              style={{ filter: colors.glow }}
              onClick={() => setSelectedZoneId(z.id)}
            >
              <rect 
                x={z.x} y={z.y} width={z.w} height={z.h} 
                fill={isSelected ? colors.fill.replace('0.2', '0.4').replace('0.05', '0.15') : colors.fill} 
                stroke={isSelected ? '#FFFFFF' : colors.stroke} 
                strokeWidth={isSelected || z.status !== 'GREEN' ? 3 : 0}
                className="transition-all duration-300"
              />
              <text 
                x={z.x + 45} y={z.y + 95} 
                fill="#FFFFFF" opacity={z.status !== 'GREEN' ? "1" : "0.5"} 
                fontSize="24" fontFamily="monospace" fontWeight="bold"
                className="transition-all duration-500"
              >
                ZONE {z.id}
              </text>
            </g>
          );
        })}

        {/* Active Event Dots */}
        {activeDots.map(dot => (
          <g key={dot.id} style={{ animation: 'pulse 1.5s cubic-bezier(0.4, 0, 0.6, 1) infinite' }}>
            <circle cx={dot.x} cy={dot.y} r="8" fill={dot.color} opacity="0.4" />
            <circle cx={dot.x} cy={dot.y} r="4" fill={dot.color} />
          </g>
        ))}
      </svg>

      {/* Selected Zone Detail Panel */}
      {selectedZoneData && (
        <div className="absolute top-4 right-4 w-72 bg-black/80 backdrop-blur-xl border border-white/20 rounded-xl p-5 shadow-2xl z-20 animate-fade-in">
          <div className="flex justify-between items-start mb-4">
            <div>
              <span className={`text-[10px] uppercase tracking-widest font-bold px-2 py-0.5 rounded border mb-2 inline-block ${
                selectedZoneData.status === 'RED' ? 'bg-atw-red/20 text-atw-red border-atw-red/30' : 
                selectedZoneData.status === 'AMBER' ? 'bg-atw-amber/20 text-atw-amber border-atw-amber/30' : 
                'bg-atw-green/20 text-atw-green border-atw-green/30'
              }`}>
                {selectedZoneData.status === 'RED' ? 'CRITICAL RISK' : selectedZoneData.status === 'AMBER' ? 'ELEVATED RISK' : 'NORMAL'}
              </span>
              <h3 className="text-white font-bold text-lg leading-tight">{selectedZoneData.name}</h3>
            </div>
            <button 
              onClick={() => setSelectedZoneId(null)}
              className="text-white/50 hover:text-white transition-colors p-1"
            >
              <X size={16} />
            </button>
          </div>

          <div className="space-y-3">
            <div className="flex items-center justify-between bg-white/5 p-3 rounded-lg border border-white/5">
              <span className="text-white/50 text-xs flex items-center gap-2"><ShieldAlert size={14} /> Active Issues</span>
              <span className="text-white font-bold">{selectedZoneData.active_issues}</span>
            </div>
            <div className="flex items-center justify-between bg-white/5 p-3 rounded-lg border border-white/5">
              <span className="text-white/50 text-xs flex items-center gap-2"><Activity size={14} /> Risk Score</span>
              <span className="text-white font-bold">{Math.round(selectedZoneData.risk_score * 100)}/100</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
