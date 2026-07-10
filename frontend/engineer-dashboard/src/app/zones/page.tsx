"use client";
import { useState, useEffect } from 'react';
import { Flame, ShieldAlert, CheckCircle2 } from 'lucide-react';

export default function ZonesPage() { 
  const [zones, setZones] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/v1/graph/project/P-001/zones`)
      .then(res => res.json())
      .then(data => {
        if (data.status === 'success') {
          setZones(data.data);
        }
        setLoading(false);
      })
      .catch(() => {
        // Fallback demo data
        setZones([
          { zone_id: 'A12', name: 'Zone A12', risk_score: 0.85, status: 'critical', active_issues: 3, coordinates: { x: 105, y: 105 } },
          { zone_id: 'B3', name: 'Zone B3', risk_score: 0.45, status: 'amber', active_issues: 1, coordinates: { x: 305, y: 105 } },
          { zone_id: 'C7', name: 'Zone C7', risk_score: 0.12, status: 'green', active_issues: 0, coordinates: { x: 505, y: 105 } }
        ]);
        setLoading(false);
      });
  }, []);

  return (
    <div className="h-full p-8">
      <h1 className="text-3xl font-bold text-white mb-6">High Risk Zones</h1>
      
      {loading ? (
        <div className="flex justify-center py-12"><div className="w-8 h-8 rounded-full border-2 border-t-atw-cyan animate-spin"></div></div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {zones.map((zone) => (
            <div key={zone.zone_id} className={`bg-atw-surface/40 backdrop-blur-md border rounded-xl p-6 shadow-2xl transition-all ${
              zone.status === 'critical' ? 'border-atw-red/50 shadow-[0_0_15px_rgba(239,68,68,0.2)]' : 
              zone.status === 'amber' ? 'border-atw-amber/50' : 'border-white/10'
            }`}>
              <div className="flex justify-between items-start mb-4">
                <h3 className="text-xl font-bold text-white">{zone.name}</h3>
                {zone.status === 'critical' && <Flame className="text-atw-red" size={24} />}
                {zone.status === 'amber' && <ShieldAlert className="text-atw-amber" size={24} />}
                {zone.status === 'green' && <CheckCircle2 className="text-atw-green" size={24} />}
              </div>
              
              <div className="space-y-3">
                <div className="flex justify-between">
                  <span className="text-gray-400">Risk Score</span>
                  <span className={`font-mono font-bold ${
                    zone.status === 'critical' ? 'text-atw-red' : zone.status === 'amber' ? 'text-atw-amber' : 'text-atw-green'
                  }`}>{(zone.risk_score * 100).toFixed(0)}%</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Active Issues</span>
                  <span className="text-white font-bold">{zone.active_issues}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Location Coordinates</span>
                  <span className="text-gray-300 font-mono text-sm">[{zone.coordinates?.x}, {zone.coordinates?.y}]</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  ); 
}