"use client";

import React, { useRef, useState, useEffect } from 'react';
import { GlassCard } from '../ui/GlassCard';
import { Upload, RefreshCw, Play, Loader2, Glasses as GlassesIcon, Camera as CameraIcon, Upload as UploadIcon } from 'lucide-react';

interface Props {
  scenarios: any[];
  activeScenarioId: string;
  setActiveScenarioId: (id: string) => void;
  scanStatus: 'IDLE' | 'LOADING' | 'RESULT';
  scanResult: any;
  customImage: string | null;
  setCustomImage: (img: string | null) => void;
  onScan: (img: string, isCustom?: boolean) => void;
  onReset: () => void;
  setScanResult?: (result: any) => void;
  setScanStatus?: (status: 'IDLE' | 'LOADING' | 'RESULT') => void;
}

export function GlassesFeedPanel({
  scenarios,
  activeScenarioId,
  setActiveScenarioId,
  scanStatus,
  scanResult,
  customImage,
  setCustomImage,
  onScan,
  onReset,
  setScanResult,
  setScanStatus
}: Props) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  
  const [source, setSource] = useState<'upload' | 'webcam' | 'glasses'>('glasses');
  const [glassesConnected, setGlassesConnected] = useState(false);
  const [webcamActive, setWebcamActive] = useState(false);
  const [webcamError, setWebcamError] = useState<string | null>(null);
  const [webcamIntervalId, setWebcamIntervalId] = useState<NodeJS.Timeout | null>(null);
  const [wsConnection, setWsConnection] = useState<WebSocket | null>(null);

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      const reader = new FileReader();
      reader.onload = (event) => {
        const dataUrl = event.target?.result as string;
        setCustomImage(dataUrl);
        onScan(dataUrl, true);
      };
      reader.readAsDataURL(file);
    }
  };

  const startWebcam = async () => {
    setWebcamError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { width: 1280, height: 720 }});
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        setWebcamActive(true);
        
        const captureInterval = setInterval(async () => {
          if (!videoRef.current) return;
          const canvas = document.createElement('canvas');
          canvas.width = 640;
          canvas.height = 360;
          const ctx = canvas.getContext('2d');
          if (ctx) {
            ctx.drawImage(videoRef.current, 0, 0, 640, 360);
            const base64 = canvas.toDataURL('image/jpeg', 0.8);
            setCustomImage(base64);
            
            const mockResult = scenarios[Math.floor(Math.random() * scenarios.length)];
            setScanResult?.(mockResult);
            setScanStatus?.('RESULT');
          }
        }, 2000);
        
        setWebcamIntervalId(captureInterval);
      }
    } catch (err: any) {
      console.warn("Error accessing webcam:", err);
      setWebcamError(err.message || "Camera permission denied or device not found.");
      setSource('upload');
      alert("Camera access denied. Please allow camera permissions in your browser to use the Webcam feature.");
    }
  };

  const stopWebcam = () => {
    if (webcamIntervalId) clearInterval(webcamIntervalId);
    if (videoRef.current && videoRef.current.srcObject) {
      const stream = videoRef.current.srcObject as MediaStream;
      stream.getTracks().forEach(track => track.stop());
      videoRef.current.srcObject = null;
    }
    setWebcamActive(false);
    setWebcamIntervalId(null);
  };

  const connectGlasses = () => {
    const ws = new WebSocket(`ws://127.0.0.1:8000/ws/glasses/WRK-001`);
    ws.onopen = () => setGlassesConnected(true);
    ws.onclose = () => setGlassesConnected(false);
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'analysis_result') {
        setCustomImage(`data:image/jpeg;base64,${data.frame}`);
        setScanResult?.(data.result);
        setScanStatus?.('RESULT');
      }
    };
    setWsConnection(ws);
  };

  const disconnectGlasses = () => {
    if (wsConnection) {
      wsConnection.close();
      setWsConnection(null);
    }
    setGlassesConnected(false);
  };

  useEffect(() => {
    return () => {
      stopWebcam();
      disconnectGlasses();
    };
  }, []);

  useEffect(() => {
    stopWebcam();
    disconnectGlasses();
    onReset();
    
    if (source === 'webcam') {
      startWebcam();
    } else if (source === 'glasses') {
      connectGlasses();
    }
  }, [source]);

  const currentScenario = scenarios.find(s => s.id === activeScenarioId);
  
  const getVerdictColor = (verdict: string) => {
    switch (verdict) {
      case 'CRITICAL': return 'var(--fail)';
      case 'HIGH': return 'var(--amber)';
      case 'PASS': return 'var(--pass)';
      case 'WARNING': return 'var(--amber)';
      case 'UNCERTAIN': return '#6366F1';
      default: return 'var(--cyan)';
    }
  };

  const getVerdictBg = (verdict: string) => {
    switch (verdict) {
      case 'CRITICAL': return 'rgba(255,59,59,0.90)';
      case 'HIGH': return 'rgba(255,107,0,0.88)';
      case 'PASS': return 'rgba(0,200,81,0.85)';
      case 'WARNING': return 'rgba(255,107,0,0.88)';
      case 'UNCERTAIN': return 'rgba(99,102,241,0.85)';
      default: return 'rgba(255,179,0,0.85)';
    }
  };

  return (
    <div className="h-full flex flex-col relative bg-transparent p-0">
      
      {/* 3 & 4. Header / Toggle Row Outside Viewport */}
      <div className="flex items-center justify-between mb-4 pointer-events-auto">
        
        <div className="flex bg-black/40 rounded-md overflow-hidden border border-[var(--border-subtle)] backdrop-blur">
          <button 
            className={`px-4 py-2 text-xs font-medium flex items-center gap-2 transition-all border-r border-[var(--border-subtle)] ${source === 'glasses' ? 'bg-[var(--cyan)]/15 text-[var(--cyan)]' : 'text-[var(--text-secondary)] hover:bg-white/5'}`}
            onClick={() => setSource('glasses')}
          >
            <GlassesIcon size={14} />
            Meta Glasses
          </button>
          <button
            className={`px-4 py-2 text-xs font-medium flex items-center gap-2 transition-all border-r border-[var(--border-subtle)] ${source === 'webcam' ? 'bg-[var(--cyan)]/15 text-[var(--cyan)]' : 'text-[var(--text-secondary)] hover:bg-white/5'}`}
            onClick={() => setSource('webcam')}
          >
            <CameraIcon size={14} />
            Webcam
          </button>
          <button
            className={`px-4 py-2 text-xs font-medium flex items-center gap-2 transition-all ${source === 'upload' ? 'bg-[var(--cyan)]/15 text-[var(--cyan)]' : 'text-[var(--text-secondary)] hover:bg-white/5'}`}
            onClick={() => { setSource('upload'); fileInputRef.current?.click(); }}
          >
            <UploadIcon size={14} />
            Upload Image
          </button>
        </div>

        <div className="flex items-center gap-2">
          <input type="file" accept="image/*" ref={fileInputRef} onChange={handleFileUpload} className="hidden" />
          
          <button 
            onClick={() => scanStatus === 'RESULT' ? onReset() : onScan(currentScenario.image, false)}
            disabled={scanStatus === 'LOADING'}
            className={`flex items-center gap-2 px-6 py-2 rounded text-xs font-bold tracking-widest transition-all ${
              scanStatus === 'LOADING' 
                ? 'bg-[var(--amber-dim)] text-[var(--amber)] border border-[var(--amber)]'
                : scanStatus === 'RESULT'
                  ? 'bg-[var(--pass-dim)] text-[var(--pass)] border border-[var(--pass)]'
                  : 'bg-[var(--cyan)] text-black shadow-[0_0_15px_var(--cyan)] hover:bg-[var(--cyan-glow)]'
            }`}
          >
            {scanStatus === 'LOADING' ? (
              <><Loader2 size={14} className="animate-spin" /> ANALYZING...</>
            ) : scanStatus === 'RESULT' ? (
              <><RefreshCw size={14} /> SCAN AGAIN</>
            ) : (
              <><Play size={14} fill="currentColor" /> SIMULATE SCAN</>
            )}
          </button>
        </div>
      </div>

      {/* 1. Viewport Height Fix */}
      <div id="glasses-viewport" className="flex-1 w-full relative flex items-center justify-center overflow-hidden bg-[#050b14] border border-[var(--border-muted)] rounded-lg min-h-[460px]">
        <div className="absolute inset-0 pointer-events-none z-0"
             style={{ backgroundImage: 'linear-gradient(rgba(0, 212, 255, 0.025) 1px, transparent 1px), linear-gradient(90deg, rgba(0, 212, 255, 0.025) 1px, transparent 1px)', backgroundSize: '24px 24px' }} />
        
        {/* 2. Idle State */}
        {(!source || (source === 'glasses' && !glassesConnected) || (source === 'webcam' && !webcamActive) || (source === 'upload' && !customImage && scanStatus === 'IDLE')) && (
          <div className="text-center absolute inset-0 flex flex-col items-center justify-center z-10">
            <GlassesIcon size={48} className="text-[var(--cyan)]/40 mb-4" />
            <p className="font-mono text-[13px] text-[var(--text-muted)] mb-1">AWAITING FEED</p>
            <p className="text-[11px] text-[var(--text-muted)] opacity-70 mb-6">Select a source above to begin</p>
            <p className="text-[var(--text-muted)] text-[10px] mb-4">── or ──</p>
            <button 
              onClick={() => onScan(currentScenario.image, false)}
              className="flex items-center gap-2 bg-transparent text-[var(--cyan)] border border-[var(--cyan)]/50 px-6 py-2.5 rounded font-bold text-xs tracking-widest hover:bg-[var(--cyan)]/10 transition-all"
            >
              <Play size={14} fill="currentColor" /> SIMULATE SCAN
            </button>
          </div>
        )}

        <div className="w-full h-full relative flex items-center justify-center border border-white/5 z-10">
          <video ref={videoRef} autoPlay playsInline muted className={`absolute inset-0 w-full h-full object-contain object-center block z-10 ${source === 'webcam' ? 'block' : 'hidden'}`} />

          {source !== 'webcam' && (customImage ? (
             <img src={customImage} alt="Custom Frame" className={`absolute inset-0 w-full h-full object-contain object-center block transition-opacity duration-500 z-10 ${scanStatus === 'RESULT' ? 'opacity-100' : 'opacity-30 grayscale'}`} />
          ) : (scanStatus === 'RESULT' || scanStatus === 'LOADING') ? (
            <img src={currentScenario.image} alt="Simulation Frame" className={`absolute inset-0 w-full h-full object-contain object-center block transition-opacity duration-500 z-10 ${scanStatus === 'RESULT' ? 'opacity-100 animate-in fade-in' : 'opacity-30 grayscale'}`} />
          ) : null)}

          <div className="absolute inset-5 pointer-events-none z-20" style={{ filter: 'drop-shadow(0 0 4px #00D4FF)' }}>
            <div className="absolute top-0 left-0 w-[24px] h-[24px] border-t-2 border-l-2 border-[#00D4FF]" />
            <div className="absolute top-0 right-0 w-[24px] h-[24px] border-t-2 border-r-2 border-[#00D4FF]" />
            <div className="absolute bottom-0 left-0 w-[24px] h-[24px] border-b-2 border-l-2 border-[#00D4FF]" />
            <div className="absolute bottom-0 right-0 w-[24px] h-[24px] border-b-2 border-r-2 border-[#00D4FF]" />
          </div>
          
          {(scanStatus === 'LOADING' || (source === 'glasses' && !glassesConnected) || (source === 'webcam' && !webcamActive)) && source === 'upload' && (
            <div className="absolute inset-0 pointer-events-none z-30 overflow-hidden">
              <div className="w-full h-2 bg-gradient-to-r from-transparent via-[var(--cyan)] to-transparent opacity-80 animate-scan-line shadow-[0_0_20px_var(--cyan)]" />
            </div>
          )}
          
          {(source === 'webcam' || (source === 'glasses' && glassesConnected)) && (
            <div className="absolute inset-0 pointer-events-none z-30 overflow-hidden">
              <div className="w-full h-2 bg-gradient-to-r from-transparent via-[var(--cyan)] to-transparent opacity-40 animate-scan-line shadow-[0_0_10px_var(--cyan)]" />
            </div>
          )}

          {scanStatus === 'RESULT' && scanResult && (
            <div className="absolute inset-0 pointer-events-none z-30 animate-in fade-in duration-300 flex items-center justify-center">
              {!customImage && scanResult.verdict === 'CRITICAL' && (
                <div className="absolute w-[60%] h-[50%] border-2 border-dashed border-[var(--cyan)] bg-[var(--cyan)]/10 flex items-end p-2">
                  <span className="bg-[var(--cyan)] text-black text-xs font-bold px-2 py-1 font-mono">
                    {scanResult.measured} ↔
                  </span>
                </div>
              )}
            </div>
          )}
        </div>
        {/* 8. Webcam REC badge */}
        {source === 'webcam' && webcamActive && (
          <div className="absolute top-4 left-4 z-40 bg-black/60 backdrop-blur rounded px-2 py-1 border border-red-500/50 flex items-center gap-2">
            <span className="text-red-500 text-[10px] animate-pulse">●</span>
            <span className="text-white text-[10px] font-bold tracking-widest">REC</span>
          </div>
        )}

        {/* Glasses REC Badge */}
        {source === 'glasses' && glassesConnected && (
          <div className="absolute top-4 left-4 z-40 bg-black/60 backdrop-blur rounded px-2 py-1 border border-[#00C851]/50 flex items-center gap-2">
            <span className="text-[#00C851] text-[10px] animate-pulse">●</span>
            <span className="text-white text-[10px] font-bold tracking-widest">LIVE</span>
          </div>
        )}

        {scanStatus === 'RESULT' && scanResult && (
          <div className="absolute top-0 left-0 right-0 h-[40px] flex items-center px-6 z-40" 
               style={{ background: getVerdictBg(scanResult.verdict) }}>
            <p className="font-mono text-[13px] text-white font-bold tracking-widest shadow-black drop-shadow-md">
              {scanResult.verdict === 'UNCERTAIN' ? (
                <>⚡ UNCERTAIN — Manual Review Required</>
              ) : (
                <>● {scanResult.verdict}  |  ZONE A12  |  {scanResult.issue.toUpperCase()}</>
              )}
            </p>
          </div>
        )}

        {scanStatus === 'RESULT' && scanResult && scanResult.verdict !== 'UNCERTAIN' && (
          <div className="absolute bottom-6 left-6 bg-black/85 border border-[var(--cyan)]/40 rounded-lg p-3 w-[280px] shadow-lg backdrop-blur pointer-events-auto z-40">
            <h3 className="text-[12px] font-bold text-[var(--amber)] uppercase tracking-wide mb-2 flex items-center gap-2">
              ⚠ {scanResult.issue}
            </h3>
            <div className="grid grid-cols-2 gap-y-1 font-mono text-[11px]">
              <span className="text-white">Measured:</span>
              <span className="text-[var(--cyan)] text-right">{scanResult.measured}</span>
              
              <span className="text-white">Required:</span>
              <span className="text-white text-right">{scanResult.required}</span>
              
              <span className="text-white">Deviation:</span>
              <span className="text-right font-bold" style={{ color: getVerdictColor(scanResult.verdict) }}>
                {scanResult.deviation}
              </span>
            </div>
            <div className="mt-2 pt-2 border-t border-white/20 text-[10px] text-white/70 flex justify-between">
              <span>Confidence: {scanResult.confidence}</span>
              <span>VLM Active</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
