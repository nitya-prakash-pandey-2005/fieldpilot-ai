"use client";
import { Flame, ShieldAlert, Activity, HardHat } from 'lucide-react';
import { mockZones } from '@/data/mockData';

export default function ZonesPage() { 
  return (
    <div className="h-full p-8 flex flex-col min-h-0 bg-atw-bg">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold text-white tracking-tight flex items-center gap-3">
            <Flame className="text-orange-500" size={32} />
            High Risk Zones
          </h1>
          <p className="text-white/50 mt-2">Aggregated risk scoring based on active issues, historical RFIs, and real-time activity.</p>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto min-h-0">
        <div className="flex flex-col gap-6 pb-10">
          {mockZones.sort((a, b) => b.risk_score - a.risk_score).map((zone) => (
            <div key={zone.id} className="bg-[#12121A] border border-white/10 rounded-xl p-6 shadow-2xl relative overflow-hidden group hover:border-white/20 transition-colors">
              <div className={`absolute top-0 left-0 w-1 h-full ${
                zone.status === 'RED' ? 'bg-atw-red' : 
                zone.status === 'AMBER' ? 'bg-atw-amber' : 'bg-atw-green'
              }`}></div>
              
              <div className="flex flex-col md:flex-row gap-8 items-start md:items-center justify-between">
                
                {/* Info Block */}
                <div className="flex-1">
                  <div className="flex items-center gap-3 mb-2">
                    <span className={`text-xs font-bold px-2 py-0.5 rounded uppercase tracking-widest ${
                      zone.status === 'RED' ? 'bg-atw-red/20 text-atw-red border border-atw-red/30' : 
                      zone.status === 'AMBER' ? 'bg-atw-amber/20 text-atw-amber border border-atw-amber/30' : 
                      'bg-atw-green/20 text-atw-green border border-atw-green/30'
                    }`}>
                      {zone.status === 'RED' ? 'CRITICAL RISK' : zone.status === 'AMBER' ? 'ELEVATED RISK' : 'NORMAL'}
                    </span>
                    <span className="text-white/40 text-sm font-mono tracking-wider">ZONE {zone.id}</span>
                  </div>
                  <h3 className="text-white text-2xl font-bold mb-2">{zone.name}</h3>
                  <div className="flex items-center gap-6 text-sm text-white/60">
                    <span className="flex items-center gap-2"><Activity size={16} className="text-atw-cyan" /> {zone.recent_activity}</span>
                    <span className="flex items-center gap-2"><HardHat size={16} className="text-atw-amber" /> {zone.active_workers} Active Workers</span>
                    <span className="flex items-center gap-2"><ShieldAlert size={16} className={zone.active_issues > 0 ? "text-atw-red" : "text-white/40"} /> {zone.active_issues} Open Issues</span>
                  </div>
                </div>

                {/* Risk Score Block */}
                <div className="w-full md:w-64 bg-black/40 border border-white/5 rounded-lg p-4 flex flex-col items-center justify-center">
                  <span className="text-[10px] uppercase tracking-widest text-white/40 font-bold mb-1">Risk Score</span>
                  <div className="flex items-end gap-1 mb-3">
                    <span className={`text-4xl font-black tracking-tighter ${
                      zone.risk_score > 0.7 ? 'text-atw-red' : 
                      zone.risk_score > 0.3 ? 'text-atw-amber' : 'text-atw-green'
                    }`}>
                      {Math.round(zone.risk_score * 100)}
                    </span>
                    <span className="text-white/30 text-lg mb-1 font-bold">/ 100</span>
                  </div>
                  <div className="w-full bg-white/10 h-2 rounded-full overflow-hidden">
                    <div 
                      className={`h-full rounded-full transition-all duration-1000 ${
                        zone.risk_score > 0.7 ? 'bg-atw-red shadow-[0_0_10px_rgba(255,59,59,0.8)]' : 
                        zone.risk_score > 0.3 ? 'bg-atw-amber shadow-[0_0_10px_rgba(255,179,0,0.8)]' : 
                        'bg-atw-green shadow-[0_0_10px_rgba(0,200,81,0.8)]'
                      }`} 
                      style={{ width: `${zone.risk_score * 100}%` }}
                    ></div>
                  </div>
                </div>

              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  ); 
}