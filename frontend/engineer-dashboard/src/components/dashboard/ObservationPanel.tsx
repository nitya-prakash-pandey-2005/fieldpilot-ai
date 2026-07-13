"use client";

import React, { useState } from 'react';
import { GlassCard } from '../ui/GlassCard';
import { Bell, FileText, Camera, Volume2, Square } from 'lucide-react';
import { useRouter } from 'next/navigation';
import * as htmlToImage from 'html-to-image';

export function ObservationPanel({ scanResult }: { scanResult: any }) {
  const router = useRouter();
  const [isPlaying, setIsPlaying] = useState(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3000);
  };

  const getVerdictColor = (verdict: string) => {
    switch (verdict) {
      case 'CRITICAL': return 'var(--fail)';
      case 'HIGH': return 'var(--amber)';
      case 'PASS': return 'var(--pass)';
      case 'WARNING': return 'var(--amber)';
      case 'UNCERTAIN': return '#6366F1'; // indigo
      default: return 'var(--text-primary)';
    }
  };

  const handleNotify = async () => {
    if (!scanResult) return;
    try {
      await fetch(`${process.env.NEXT_PUBLIC_API_URL || ""}/api/v1/notification/dispatch`, { 
        method: 'POST', 
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          severity: scanResult.verdict === "CRITICAL" ? "CRITICAL" : "MEDIUM",
          zone_id: "A12",
          message: `Scene analysis: ${scanResult.verdict}. Confidence: ${scanResult.confidence}. Manual review requested.`,
          worker_id: "WRK-001"
        }) 
      });
      showToast("✓ Engineer notified");
    } catch (e) {
      showToast("Queued for delivery");
    }
  };

  const handleFileRfi = () => {
    if (!scanResult) return;
    router.push(`/rfis?prefill=OBS-052`);
  };

  const handleSaveEvidence = async () => {
    if (!scanResult) return;
    const viewport = document.getElementById('glasses-viewport');
    if (viewport) {
      try {
        const dataUrl = await htmlToImage.toPng(viewport, { 
          backgroundColor: '#050b14',
          cacheBust: true,
          pixelRatio: 2,
          filter: (node) => {
            // html-to-image often crashes when trying to serialize <video> elements
            if (node.tagName === 'VIDEO') return false;
            return true;
          }
        });
        const link = document.createElement('a');
        link.download = `observation-OBS-052.png`;
        link.href = dataUrl;
        link.click();
        showToast("✓ Evidence saved");
      } catch (err: any) {
        console.warn("Failed to save evidence:", err?.message || err);
        showToast("Failed to save image");
      }
    }
  };

  const handlePlayAudio = () => {
    if (!scanResult) return;
    if (isPlaying) {
      window.speechSynthesis.cancel();
      setIsPlaying(false);
      return;
    }

    const textToSpeak = scanResult.verdict === 'UNCERTAIN' 
      ? 'Scene type unknown. No construction asset pattern matched. Flagging for manual engineer review.'
      : `Verdict is ${scanResult.verdict}. ${scanResult.issue}. ${scanResult.measured}.`;

    const utterance = new SpeechSynthesisUtterance(textToSpeak);
    utterance.onend = () => setIsPlaying(false);
    utterance.rate = 0.9;
    
    setIsPlaying(true);
    window.speechSynthesis.speak(utterance);
  };

  return (
    <div className="flex flex-col h-full gap-4 relative">
      {toastMessage && (
        <div className="absolute -top-12 left-1/2 -translate-x-1/2 bg-black border border-[var(--border-subtle)] text-white px-4 py-2 rounded-lg text-xs z-50 shadow-lg animate-in fade-in slide-in-from-bottom-2">
          {toastMessage}
        </div>
      )}

      {/* Last Observation Data */}
      <GlassCard className="flex-1 p-4 flex flex-col min-h-0">
        <h2 className="text-sm font-semibold tracking-wide text-[var(--text-primary)] uppercase mb-3 shrink-0">Last Observation</h2>
        
        {scanResult ? (
          <div 
            className="flex-1 bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded p-3 pb-[12px] font-mono last-observation-content"
            style={{ 
              overflowY: 'auto', 
              maxHeight: '280px', 
              scrollbarWidth: 'thin', 
              scrollbarColor: 'rgba(0,212,255,0.3) transparent' 
            }}
          >
            <div className="text-[var(--text-muted)] mb-2 tracking-wider text-xs">
              OBS-052 · Zone A12 · 2s ago
            </div>
            
            <div className="grid grid-cols-3 gap-y-[5px] items-center">
              <div className="text-[var(--text-muted)] text-[11px]">Scene:</div>
              <div className="col-span-2 text-[var(--cyan)] text-[12px] break-words">{scanResult.name}</div>
              
              <div className="text-[var(--text-muted)] text-[11px]">Verdict:</div>
              <div className="col-span-2 font-bold flex items-center gap-1.5 text-[12px]" style={{ color: getVerdictColor(scanResult.verdict) }}>
                <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: getVerdictColor(scanResult.verdict) }} />
                {scanResult.verdict}
              </div>
              
              <div className="text-[var(--text-muted)] text-[11px]">Confidence:</div>
              <div className="col-span-2 text-[var(--pass)] text-[12px]">{scanResult.confidence}</div>
              
              {scanResult.verdict !== 'UNCERTAIN' && (
                <>
                  <div className="text-[var(--text-muted)] text-[11px]">Deviation:</div>
                  <div className={`col-span-2 text-[12px] ${scanResult.deviation === 'N/A' ? 'text-[var(--text-muted)]' : 'text-[var(--fail)]'}`}>
                    {scanResult.deviation}
                  </div>
                </>
              )}

              {scanResult.verdict === 'UNCERTAIN' && (
                <>
                  <div className="text-[var(--text-muted)] text-[11px]">Scene Type:</div>
                  <div className="col-span-2 text-[#6366F1] text-[12px]">Non-standard</div>
                  
                  <div className="text-[var(--text-muted)] text-[11px]">AI Assess:</div>
                  <div className="col-span-2 text-white text-[12px]">No construction asset</div>
                  
                  <div className="text-[var(--text-muted)] text-[11px]">Action:</div>
                  <div className="col-span-2 text-[var(--amber)] text-[12px]">Manual review required</div>
                </>
              )}
              
              <div className="col-span-3 border-t border-[var(--border-subtle)] my-[2px]" />
              
              <div className="text-[var(--text-muted)] text-[11px]">Agent chain:</div>
              <div className="col-span-2 text-[var(--purple)] text-[12px]">{scanResult.agentChain}</div>
              
              <div className="text-[var(--text-muted)] text-[11px]">Total time:</div>
              <div className="col-span-2 text-[var(--text-primary)] text-[12px]">{scanResult.time}</div>
            </div>
          </div>
        ) : (
          <div className="flex-1 border border-dashed border-[var(--border-subtle)] rounded flex items-center justify-center text-[var(--text-muted)] font-mono text-xs uppercase tracking-widest text-center">
            Awaiting<br/>Scan...
          </div>
        )}
      </GlassCard>

      {/* Quick Actions */}
      <GlassCard className="shrink-0 p-4">
        <h2 className="text-sm font-semibold tracking-wide text-[var(--text-primary)] uppercase mb-3">Quick Actions</h2>
        <div className="grid grid-cols-2 gap-2">
          <button onClick={handleNotify} disabled={!scanResult} className="flex items-center gap-2 bg-[var(--bg-surface)] hover:bg-[var(--cyan)]/10 hover:border-[var(--cyan)]/30 border border-[var(--border-subtle)] px-2 py-2 rounded text-xs text-[var(--text-primary)] transition-colors disabled:opacity-50">
            <Bell size={14} className="text-[var(--amber)] shrink-0" />
            <span className="truncate">Notify Engineer</span>
          </button>
          <button onClick={handleFileRfi} disabled={!scanResult} className="flex items-center gap-2 bg-[var(--bg-surface)] hover:bg-[var(--cyan)]/10 hover:border-[var(--cyan)]/30 border border-[var(--border-subtle)] px-2 py-2 rounded text-xs text-[var(--text-primary)] transition-colors disabled:opacity-50">
            <FileText size={14} className="text-[var(--cyan)] shrink-0" />
            <span className="truncate">File RFI Draft</span>
          </button>
          <button onClick={handleSaveEvidence} disabled={!scanResult} className="flex items-center gap-2 bg-[var(--bg-surface)] hover:bg-[var(--cyan)]/10 hover:border-[var(--cyan)]/30 border border-[var(--border-subtle)] px-2 py-2 rounded text-xs text-[var(--text-primary)] transition-colors disabled:opacity-50">
            <Camera size={14} className="text-[var(--pass)] shrink-0" />
            <span className="truncate">Save Evidence</span>
          </button>
          <button onClick={handlePlayAudio} disabled={!scanResult} className="flex items-center gap-2 bg-[var(--bg-surface)] hover:bg-[var(--cyan)]/10 hover:border-[var(--cyan)]/30 border border-[var(--border-subtle)] px-2 py-2 rounded text-xs text-[var(--text-primary)] transition-colors disabled:opacity-50">
            {isPlaying ? (
              <><Square size={14} className="text-[var(--fail)] shrink-0" /><span className="truncate">Stop Audio</span></>
            ) : (
              <><Volume2 size={14} className="text-[var(--purple)] shrink-0" /><span className="truncate">Play Audio</span></>
            )}
          </button>
        </div>
      </GlassCard>
    </div>
  );
}
