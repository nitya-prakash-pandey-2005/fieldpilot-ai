"use client";

import React, { useState, useEffect } from 'react';
import { GlassCard } from '@/components/ui/GlassCard';
import { StatusBadge } from '@/components/ui/StatusBadge';
import { LiveIndicator } from '@/components/ui/LiveIndicator';
import { GlassesFeedPanel } from '@/components/dashboard/GlassesFeedPanel';
import { TranscriptPanel } from '@/components/dashboard/TranscriptPanel';
import { ObservationPanel } from '@/components/dashboard/ObservationPanel';

export const SCENARIOS = [
  {
    id: 'rebar',
    name: "Rebar Spacing Violation",
    shortName: "🔴 Rebar Fail",
    image: "/demo/rebar.jpg",
    verdict: "CRITICAL",
    issue: "Rebar Spacing",
    measured: "152mm (6 inch)",
    required: "102mm (4 inch)", 
    deviation: "+49%",
    confidence: "97%",
    agentChain: "V1→C5→N9→L10",
    time: "2.3s"
  },
  {
    id: 'ppe',
    name: "Missing PPE",
    shortName: "🟠 Missing PPE",
    image: "/demo/ppe.jpg",
    verdict: "HIGH",
    issue: "Safety Violation",
    measured: "No hard hat detected",
    required: "Hard hat mandatory",
    deviation: "N/A",
    confidence: "94%",
    agentChain: "V1→S2→N9",
    time: "1.8s"
  },
  {
    id: 'compliant',
    name: "Compliant Installation",
    shortName: "🟢 Compliant",
    image: "/demo/compliant.jpg",
    verdict: "PASS",
    issue: "Concrete Formwork",
    measured: "Clearance: 52mm",
    required: "Minimum 50mm",
    deviation: "+4%",
    confidence: "99%",
    agentChain: "V1→C2",
    time: "1.2s"
  },
  {
    id: 'drawing',
    name: "Outdated Drawing",
    shortName: "📋 Drawing",
    image: "/demo/drawing.jpg",
    verdict: "WARNING",
    issue: "Version Mismatch",
    measured: "Rev B",
    required: "Rev C (Latest)",
    deviation: "Outdated by 1 rev",
    confidence: "95%",
    agentChain: "V1→D4→L10",
    time: "2.1s"
  }
];

export default function GlassesPage() {
  const [fps, setFps] = useState("30.0");
  const [latency, setLatency] = useState("12");
  const [gpu, setGpu] = useState("67");

  const [activeScenarioId, setActiveScenarioId] = useState(SCENARIOS[0].id);
  const [scanStatus, setScanStatus] = useState<'IDLE' | 'LOADING' | 'RESULT'>('IDLE');
  const [scanResult, setScanResult] = useState<any>(null);
  const [customImage, setCustomImage] = useState<string | null>(null);

  const [currentZone, setCurrentZone] = useState('A12');
  const [currentLanguage, setCurrentLanguage] = useState('EN 🇺🇸');
  const [currentWorker, setCurrentWorker] = useState('WRK-001');

  useEffect(() => {
    const timer = setInterval(() => {
      setFps((28 + Math.random() * 4).toFixed(1));
      setLatency(Math.round(10 + Math.random() * 6).toString());
      setGpu(Math.round(60 + Math.random() * 15).toString());
    }, 2000);
    return () => clearInterval(timer);
  }, []);

  const handleScan = async (imageToScan: string, isCustom = false) => {
    setScanStatus('LOADING');
    setScanResult(null);
    
    try {
      await new Promise(resolve => setTimeout(resolve, 2000));
      
      let result;
      if (isCustom) {
        result = {
          name: "Custom Image Analysis",
          image: imageToScan,
          verdict: "UNCERTAIN",
          issue: "Unknown Scene",
          measured: "Manual review required",
          required: "N/A",
          deviation: "N/A",
          confidence: "45%",
          agentChain: "V1",
          time: "3.5s"
        };
      } else {
        result = SCENARIOS.find(s => s.id === activeScenarioId);
      }
      
      setScanResult(result);
      setScanStatus('RESULT');
      
    } catch (e) {
      console.error(e);
      setScanStatus('IDLE');
    }
  };

  const handleReset = () => {
    setScanStatus('IDLE');
    setScanResult(null);
    setCustomImage(null);
    const nextIndex = (SCENARIOS.findIndex(s => s.id === activeScenarioId) + 1) % SCENARIOS.length;
    setActiveScenarioId(SCENARIOS[nextIndex].id);
  };

  const [showToast, setShowToast] = useState(true);
  
  useEffect(() => {
    const timer = setTimeout(() => setShowToast(false), 5000);
    return () => clearTimeout(timer);
  }, []);

  return (
    <div className="flex flex-col min-h-full gap-4 relative animate-fade-in pb-8">
      
      {/* 7. Top-Right Toast Notification (Mock) */}
      {showToast && (
        <div className="fixed top-[60px] right-[20px] z-[9999] min-w-[280px] flex items-center justify-between gap-2 bg-[rgba(255,59,59,0.15)] border border-[rgba(255,59,59,0.4)] rounded-lg px-3.5 py-2.5 backdrop-blur-md shadow-lg animate-in slide-in-from-right-4 fade-in duration-500" style={{ animationDelay: '1s', animationFillMode: 'both' }}>
          <div className="flex items-center gap-2">
            <span className="text-sm">🔴</span>
            <span className="text-white text-xs font-medium tracking-wide">1 New Issue · Zone A12</span>
          </div>
          <div className="flex items-center gap-3">
            <button className="text-[var(--text-muted)] hover:text-white text-[11px] font-bold transition-colors">View →</button>
            <button className="text-[var(--text-muted)] hover:text-white text-xs" onClick={() => setShowToast(false)}>✕</button>
          </div>
        </div>
      )}

      <div className="flex items-center justify-between bg-[var(--bg-surface)]/75 backdrop-blur-[20px] rounded-xl border border-[var(--border-subtle)] p-4 shrink-0">
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-bold tracking-tight text-[var(--text-primary)] font-display uppercase">Meta Glasses Stream</h1>
            <LiveIndicator isLive={true} />
          </div>
          <div className="flex items-center gap-3">
            <select 
              value={currentZone} 
              onChange={e => setCurrentZone(e.target.value)}
              className="bg-black/40 border border-[var(--border-subtle)] text-[var(--text-secondary)] text-xs rounded px-2 py-1 outline-none focus:border-[var(--cyan)]"
            >
              <option value="A12">Zone A12</option>
              <option value="B3">Zone B3</option>
              <option value="C7">Zone C7</option>
              <option value="D4">Zone D4</option>
            </select>
            
            <select 
              value={currentLanguage} 
              onChange={e => setCurrentLanguage(e.target.value)}
              className="bg-black/40 border border-[var(--border-subtle)] text-[var(--text-secondary)] text-xs rounded px-2 py-1 outline-none focus:border-[var(--cyan)]"
            >
              <option value="EN 🇺🇸">EN 🇺🇸</option>
              <option value="HI 🇮🇳">हिंदी 🇮🇳</option>
              <option value="AR 🇦🇪">العربية 🇦🇪</option>
              <option value="TA 🇮🇳">தமிழ் 🇮🇳</option>
              <option value="TE 🇮🇳">తెలుగు 🇮🇳</option>
            </select>

            <select 
              value={currentWorker} 
              onChange={e => setCurrentWorker(e.target.value)}
              className="bg-black/40 border border-[var(--border-subtle)] text-[var(--text-secondary)] text-xs rounded px-2 py-1 outline-none focus:border-[var(--cyan)]"
            >
              <option value="WRK-001">WRK-001</option>
              <option value="WRK-002">WRK-002</option>
              <option value="WRK-003">WRK-003</option>
            </select>
          </div>
        </div>

        <div className="flex items-center gap-4 text-xs font-mono">
          <div className="flex flex-col items-end">
            <span className="text-[var(--text-muted)]">Worker ID</span>
            <span className="text-[var(--cyan)] font-bold">{currentWorker} (Nitya Pandey)</span>
          </div>
          <div className="flex flex-col items-end">
            <span className="text-[var(--text-muted)]">Latency</span>
            <span className="text-[var(--pass)] font-bold transition-all duration-300">{latency}ms</span>
          </div>
          <div className="flex flex-col items-end">
            <span className="text-[var(--text-muted)]">FPS</span>
            <span className="text-[var(--pass)] font-bold transition-all duration-300">{fps}</span>
          </div>
          <div className="flex flex-col items-end">
            <span className="text-[var(--text-muted)]">GPU</span>
            <span className="text-[var(--amber)] font-bold transition-all duration-300">{gpu}%</span>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 xl:grid-cols-4 gap-4 flex-1">
        
        {/* Main Feed */}
        <div className="lg:col-span-2 xl:col-span-3 flex flex-col h-[80vh]">
          <GlassesFeedPanel 
            scenarios={SCENARIOS}
            activeScenarioId={activeScenarioId}
            setActiveScenarioId={setActiveScenarioId}
            scanStatus={scanStatus}
            scanResult={scanResult}
            customImage={customImage}
            setCustomImage={setCustomImage}
            onScan={handleScan}
            onReset={handleReset}
          />
        </div>
        
        {/* Real-time transcript & logs */}
        <div className="flex flex-col gap-4 xl:col-span-1 h-[80vh]">
          <div className="h-[45%] shrink-0">
            <TranscriptPanel scanStatus={scanStatus} scanResult={scanResult} />
          </div>
          <div className="h-[55%] flex flex-col">
            <ObservationPanel scanResult={scanResult} />
          </div>
        </div>
        
      </div>
    </div>
  );
}
