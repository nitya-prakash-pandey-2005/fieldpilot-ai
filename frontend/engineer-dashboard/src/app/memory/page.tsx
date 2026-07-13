"use client";

import React from 'react';
import { MemorySearch } from '@/components/dashboard/MemorySearch';

export default function MemoryPage() {
  return (
    <div className="flex flex-col h-full relative animate-fade-in max-w-7xl mx-auto w-full pt-8">
      <div className="mb-8 text-center">
        <h1 className="text-3xl font-bold tracking-tight text-[var(--text-primary)] font-display uppercase mb-2">Project Memory</h1>
        <p className="text-[var(--text-secondary)] max-w-2xl mx-auto">
          Query the AI Knowledge Graph to retrieve past decisions, RFI resolutions, and visual observations across the entire project history.
        </p>
      </div>

      <MemorySearch />
    </div>
  );
}
