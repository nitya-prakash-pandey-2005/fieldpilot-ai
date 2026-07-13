"use client";
import React from 'react';

export function StatusBadge({ status }: { status: 'PASS' | 'FAIL' | 'CRITICAL' | 'WARNING' | string }) {
  let colorClass = 'bg-[var(--pass-dim)] text-[var(--pass)] border-[var(--pass)]';
  
  if (status === 'FAIL') colorClass = 'bg-[var(--fail-dim)] text-[var(--fail)] border-[var(--fail)]';
  if (status === 'CRITICAL') colorClass = 'bg-[var(--fail)] text-white border-[var(--fail)] animate-pulse-slow';
  if (status === 'WARNING') colorClass = 'bg-[var(--warning-dim)] text-[var(--warning)] border-[var(--warning)]';

  return (
    <span className={`px-2 py-1 text-[10px] font-bold tracking-widest uppercase rounded border border-opacity-30 ${colorClass}`} style={{ fontFamily: 'var(--font-display)' }}>
      {status}
    </span>
  );
}
