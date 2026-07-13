"use client";
import React from 'react';

export function LiveIndicator({ isLive = true }: { isLive?: boolean }) {
  if (!isLive) return null;
  return (
    <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-[var(--fail-dim)] border border-[var(--fail)]/30">
      <div className="w-1.5 h-1.5 rounded-full bg-[var(--fail)] animate-pulse" />
      <span className="text-[9px] font-bold tracking-wider text-[var(--fail)]" style={{ fontFamily: 'var(--font-mono)' }}>
        LIVE
      </span>
    </div>
  );
}
