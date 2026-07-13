"use client";

import React, { useState, useEffect, useRef } from 'react';
import { GlassCard } from '../ui/GlassCard';

interface Props {
  scanStatus: 'IDLE' | 'LOADING' | 'RESULT';
  scanResult: any;
}

const MESSAGE_SEQUENCES: Record<string, any[]> = {
  rebar: [
    { type: 'agent', text: 'Initializing VLM pipeline...' },
    { type: 'vision', text: 'YOLOv11 frame captured · confidence 0.97' },
    { type: 'vision', text: 'Asset detected: rebar grid · Zone A12' },
    { type: 'agent', text: 'Calibrating via ArUco marker...' },
    { type: 'agent', text: 'Spacing measured: 152mm' },
    { type: 'agent', text: 'Querying spec for Zone A12 rebar...' },
    { type: 'memory', text: 'Spec retrieved: 102mm ±5mm · ACI 318-19' },
    { type: 'agent', text: 'Deviation: +50mm (+49.0%) · CRITICAL' },
    { type: 'worker', text: 'Is this rebar spacing correct?' },
    { type: 'agent', text: 'No. Spacing is 152mm. Spec requires 102mm. Stop work and await engineer instruction.' },
    { type: 'system', text: 'OBSERVATION FILED: OBS-050' },
    { type: 'system', text: 'WhatsApp → Engineer Chen ✓' },
    { type: 'system', text: 'Slack #site-alerts ✓' },
    { type: 'system', text: 'Neo4j graph updated · Zone A12 risk: 0.91' }
  ],
  ppe: [
    { type: 'agent', text: 'Initializing VLM pipeline...' },
    { type: 'vision', text: 'YOLOv11 frame captured · confidence 0.94' },
    { type: 'vision', text: 'Asset detected: worker · Zone D4' },
    { type: 'agent', text: 'Running PPE compliance check...' },
    { type: 'vision', text: 'Hard hat: NOT DETECTED' },
    { type: 'agent', text: 'Safety violation confirmed: HIGH severity' },
    { type: 'worker', text: 'Can I proceed to the next zone?' },
    { type: 'agent', text: 'Safety alert. Worker detected without head protection. Please put on hard hat before continuing.' },
    { type: 'system', text: 'OBSERVATION FILED: OBS-051' }
  ],
  compliant: [
    { type: 'agent', text: 'Initializing VLM pipeline...' },
    { type: 'vision', text: 'YOLOv11 frame captured · confidence 0.99' },
    { type: 'vision', text: 'Asset detected: concrete formwork' },
    { type: 'agent', text: 'Measuring clearance...' },
    { type: 'agent', text: 'Clearance: 52mm' },
    { type: 'memory', text: 'Spec retrieved: Minimum 50mm' },
    { type: 'agent', text: 'Deviation: +4% · PASS' },
    { type: 'agent', text: 'Installation compliant. Clearance within specification. Continue work.' }
  ],
  drawing: [
    { type: 'agent', text: 'Initializing VLM pipeline...' },
    { type: 'vision', text: 'YOLOv11 frame captured · confidence 0.95' },
    { type: 'vision', text: 'Asset detected: architectural drawing' },
    { type: 'agent', text: 'Extracting title block text...' },
    { type: 'vision', text: 'OCR: "Rev B"' },
    { type: 'memory', text: 'Checking latest version for sheet A-102...' },
    { type: 'memory', text: 'Latest version in Procore: Rev C' },
    { type: 'agent', text: 'Version Mismatch: Outdated by 1 rev · WARNING' },
    { type: 'worker', text: 'What revision is this drawing?' },
    { type: 'agent', text: 'You are using Rev B. The latest drawing is Rev C. Please pull the latest version.' }
  ],
  custom: [
    { type: 'agent', text: 'Initializing custom analysis pipeline...' },
    { type: 'vision', text: 'YOLOv11 frame captured · confidence 0.45' },
    { type: 'agent', text: 'Scene type: Unknown / Non-standard' },
    { type: 'agent', text: 'No construction asset pattern matched' },
    { type: 'memory', text: 'Querying general safety protocols...' },
    { type: 'agent', text: 'Low confidence — escalating to engineer' },
    { type: 'system', text: 'OBSERVATION FILED: OBS-052 (UNCERTAIN)' },
    { type: 'agent', text: 'Escalating to manual review queue' },
    { type: 'system', text: 'Engineer notification sent' },
    { type: 'agent', text: 'Tip: For best results, point at rebar, conduit, formwork, or structural elements' },
    { type: 'memory', text: '3 similar unidentified scenes in project history' },
    { type: 'system', text: 'Session logged · OBS-052 saved to project memory' }
  ]
};

export function TranscriptPanel({ scanStatus, scanResult }: Props) {
  const [logs, setLogs] = useState<any[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Initial dummy state
  useEffect(() => {
    if (scanStatus === 'IDLE' && logs.length === 0) {
      setLogs([
        { id: 1, type: 'system', text: 'System ready. Awaiting scan...', time: new Date().toLocaleTimeString() }
      ]);
    }
  }, []);

  // Trigger animation sequence when LOADING begins
  useEffect(() => {
    if (scanStatus === 'LOADING') {
      setLogs([]); // Clear logs
    }
  }, [scanStatus]);

  // Handle sequence playing based on RESULT
  useEffect(() => {
    if (scanStatus === 'RESULT' && scanResult) {
      // If we already started playing, continue. If not, start now.
      const seqId = (scanResult.name === 'Custom Image Analysis' || scanResult.name === 'Custom Scene Analysis') ? 'custom' : (scanResult.id || 'rebar');
      const sequence = MESSAGE_SEQUENCES[seqId] || MESSAGE_SEQUENCES['rebar'];
      
      let i = 0;
      setLogs([]);
      
      const interval = setInterval(() => {
        if (i < sequence.length) {
          const msg = sequence[i];
          setLogs(prev => [...prev, {
            id: Date.now() + i,
            type: msg.type,
            text: msg.text,
            time: new Date().toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
          }]);
          i++;
        } else {
          clearInterval(interval);
        }
      }, 400);
      
      return () => clearInterval(interval);
    }
  }, [scanStatus, scanResult]);

  // Auto-scroll to bottom
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  const getColorClasses = (type: string) => {
    switch (type) {
      case 'agent': return 'bg-transparent text-[var(--cyan)]';
      case 'worker': return 'bg-[var(--cyan)]/20 border border-[var(--cyan)]/30 text-[var(--cyan)] rounded-tr-none';
      case 'system': return 'bg-[var(--fail-dim)] border border-[var(--fail)]/30 text-[var(--fail)] font-bold';
      case 'vision': return 'bg-transparent text-[var(--purple)]';
      case 'memory': return 'bg-transparent text-[#4da6ff]';
      default: return 'bg-[var(--bg-surface)] text-[var(--text-primary)]';
    }
  };

  return (
    <GlassCard className="h-full flex flex-col relative overflow-hidden">
      <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-transparent via-[var(--cyan)] to-transparent opacity-20" />
      
      <div className="p-3 border-b border-[var(--border-subtle)] flex items-center justify-between bg-black/20">
        <h2 className="text-[11px] font-bold tracking-widest text-[var(--text-primary)] uppercase flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-[var(--cyan)] animate-pulse" />
          Live Transcript
        </h2>
        <span className="text-[10px] font-mono text-[var(--text-muted)]">TERMINAL_V2</span>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 flex flex-col gap-1.5 font-mono text-xs bg-black/40 scroll-smooth">
        {logs.map((log) => (
          <div key={log.id} className={`flex flex-col gap-0.5 animate-in fade-in slide-in-from-bottom-2 duration-300 ${
            log.type === 'worker' ? 'items-end' : 'items-start'
          }`}>
            <span className="text-[9px] text-[var(--text-muted)] tracking-wider">
              {log.time} <span className="opacity-50">|</span> {log.type.toUpperCase()}
            </span>
            <div className={`px-2.5 py-1 rounded-[4px] max-w-[90%] leading-relaxed ${getColorClasses(log.type)}`}>
              {log.type === 'agent' && <span className="text-[var(--cyan)] mr-2 opacity-70">&gt;</span>}
              {log.type === 'vision' && <span className="text-[var(--purple)] mr-2 opacity-70">[YOLO]</span>}
              {log.type === 'memory' && <span className="text-[#4da6ff] mr-2 opacity-70">[RAG]</span>}
              {log.text}
            </div>
          </div>
        ))}
      </div>
    </GlassCard>
  );
}
