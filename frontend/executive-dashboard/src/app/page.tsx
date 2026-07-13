"use client";

import { useEffect, useState } from 'react';
import { Activity, ShieldCheck, TrendingUp, DollarSign } from 'lucide-react';
import { SystemHealthPanel } from '@/components/SystemHealthPanel';
import { AgentActivityFeed } from '@/components/AgentActivityFeed';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer
} from 'recharts';

const FALLBACK_TRENDS = [
  { month: 'Feb 2026', cost_avoided: 15000, incidents: 4 },
  { month: 'Mar 2026', cost_avoided: 18000, incidents: 5 },
  { month: 'Apr 2026', cost_avoided: 12000, incidents: 3 },
  { month: 'May 2026', cost_avoided: 24000, incidents: 6 },
  { month: 'Jun 2026', cost_avoided: 22000, incidents: 5 },
  { month: 'Jul 2026', cost_avoided: 28000, incidents: 7 },
];

export default function ExecutiveDashboard() {
  const [trends, setTrends] = useState<Record<string, unknown>[]>(FALLBACK_TRENDS);
  const [stats, setStats] = useState({
    total_cost_avoided_usd: 187000,
    rework_prevented_count: 12
  });

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [statsRes, trendsRes] = await Promise.all([
          fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/v1/learning/stats`),
          fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/v1/learning/trends`)
        ]);
        
        if (statsRes.ok) {
          const sData = await statsRes.json();
          if (sData && typeof sData.total_cost_avoided_usd !== 'undefined') {
            setStats(sData);
          }
        }
        
        if (trendsRes.ok) {
          const tData = await trendsRes.json();
          if (tData && tData.status === 'success' && tData.data && tData.data.length > 0) {
            setTrends(tData.data);
          }
        }
      } catch (e) {
        console.warn("Failed to fetch dashboard data, using fallback");
      }
    };
    
    fetchData();
  }, []);

  return (
    <div className="flex-1 flex flex-col min-h-screen bg-atw-bg text-white">
      {/* Top Header */}
      <header className="h-16 border-b border-atw-border bg-atw-surface/50 backdrop-blur-md flex items-center justify-between px-6 sticky top-0 z-10">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded bg-atw-purple/20 flex items-center justify-center border border-atw-purple/50">
            <ShieldCheck className="text-atw-purple" size={18} />
          </div>
          <div>
            <h1 className="text-lg font-semibold tracking-wide">FIELDPILOT AI <span className="text-white/50 text-sm font-normal">| EXECUTIVE VIEW</span></h1>
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <div className="flex-1 p-6 overflow-y-auto">
        
        {/* KPI Row */}
        <div className="grid grid-cols-3 gap-4 mb-6">
          <div className="bg-atw-surface/60 backdrop-blur-md border border-white/10 rounded-xl p-5 flex items-center gap-4 animate-fade-in shadow-lg">
            <div className="p-3 rounded-lg bg-black/40 border border-white/5">
              <DollarSign className="text-atw-green" size={28} />
            </div>
            <div>
              <p className="text-sm font-medium text-white/50 tracking-wider uppercase">Total Cost Avoided</p>
              <p className="text-3xl font-bold text-white tracking-tight">${stats.total_cost_avoided_usd.toLocaleString()}</p>
            </div>
          </div>
          
          <div className="bg-atw-surface/60 backdrop-blur-md border border-white/10 rounded-xl p-5 flex items-center gap-4 animate-fade-in shadow-lg" style={{ animationDelay: '150ms' }}>
            <div className="p-3 rounded-lg bg-black/40 border border-white/5">
              <TrendingUp className="text-atw-purple" size={28} />
            </div>
            <div>
              <p className="text-sm font-medium text-white/50 tracking-wider uppercase">Rework Prevented</p>
              <p className="text-3xl font-bold text-white tracking-tight">{stats.rework_prevented_count} <span className="text-sm font-normal text-white/40">Events</span></p>
            </div>
          </div>
          
          <div className="bg-atw-surface/60 backdrop-blur-md border border-white/10 rounded-xl p-5 flex items-center gap-4 animate-fade-in shadow-lg" style={{ animationDelay: '300ms' }}>
            <div className="p-3 rounded-lg bg-black/40 border border-white/5">
              <Activity className="text-atw-cyan" size={28} />
            </div>
            <div>
              <p className="text-sm font-medium text-white/50 tracking-wider uppercase">System Status</p>
              <p className="text-3xl font-bold text-atw-cyan tracking-tight">OPERATIONAL</p>
            </div>
          </div>
        </div>

        {/* Dashboard Grid */}
        <div className="grid grid-cols-12 gap-6 h-[500px]">
          
          {/* Main Chart */}
          <div className="col-span-8 h-full bg-atw-surface/60 backdrop-blur-md border border-white/10 rounded-xl p-5 shadow-2xl flex flex-col relative overflow-hidden">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-semibold tracking-wide text-white/90 uppercase text-sm flex items-center gap-2">
                <TrendingUp size={16} className="text-atw-green" />
                Monthly Cost Avoidance (USD)
              </h2>
            </div>
            
            <div className="flex-1 w-full relative z-10">
              {trends.length > 0 && (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={trends} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                    <defs>
                      <linearGradient id="colorCost" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#00E676" stopOpacity={0.4}/>
                        <stop offset="95%" stopColor="#00E676" stopOpacity={0}/>
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
                    <XAxis 
                      dataKey="month" 
                      stroke="rgba(255,255,255,0.3)" 
                      fontSize={12} 
                      tickLine={false}
                      axisLine={false}
                      dy={10}
                    />
                    <YAxis 
                      stroke="rgba(255,255,255,0.3)" 
                      fontSize={12} 
                      tickLine={false}
                      axisLine={false}
                      tickFormatter={(value) => `$${value/1000}k`}
                      dx={-10}
                    />
                    <Tooltip 
                      contentStyle={{ backgroundColor: 'rgba(10, 22, 40, 0.9)', borderColor: 'rgba(255,255,255,0.1)', borderRadius: '8px' }}
                      itemStyle={{ color: '#00E676' }}
                    />
                    <Area 
                      type="monotone" 
                      dataKey="cost_avoided" 
                      stroke="#00E676" 
                      strokeWidth={3}
                      fillOpacity={1} 
                      fill="url(#colorCost)" 
                      animationDuration={2000}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>

          {/* Side Panels */}
          <div className="col-span-4 flex flex-col gap-6 h-full">
            <div className="flex-1 min-h-0">
              <SystemHealthPanel />
            </div>
            <div className="flex-1 min-h-0">
              <AgentActivityFeed />
            </div>
          </div>
          
        </div>
      </div>
    </div>
  );
}
