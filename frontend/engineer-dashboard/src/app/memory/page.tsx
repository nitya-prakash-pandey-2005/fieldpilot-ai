"use client";

import React, { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { MemorySearch } from '@/components/dashboard/MemorySearch';

function MemoryPageInner() {
  const searchParams = useSearchParams();
  const initialQuery = searchParams.get('q') || '';

  return (
    <div className="flex flex-col h-full relative animate-fade-in max-w-7xl mx-auto w-full pt-8">
      <div className="mb-8 text-center">
        <h1 className="text-3xl font-bold tracking-tight text-[var(--text-primary)] font-display uppercase mb-2">Project Memory</h1>
        <p className="text-[var(--text-secondary)] max-w-2xl mx-auto">
          Semantic search over indexed drawings, specs, and resolved incidents — grounded in real retrieved passages, with AI-synthesized answers when an LLM is configured.
        </p>
      </div>

      <MemorySearch initialQuery={initialQuery} />
    </div>
  );
}

export default function MemoryPage() {
  return (
    <Suspense fallback={null}>
      <MemoryPageInner />
    </Suspense>
  );
}
