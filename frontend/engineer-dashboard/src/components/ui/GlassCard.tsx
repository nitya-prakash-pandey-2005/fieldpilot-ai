"use client";
import React from 'react';

export function GlassCard({ children, className = '', accentColor = '' }: { children: React.ReactNode, className?: string, accentColor?: string }) {
  return (
    <div 
      className={`bg-[var(--bg-surface)]/75 backdrop-blur-[20px] rounded-xl border border-[var(--border-subtle)] relative overflow-hidden shadow-lg ${className}`}
    >
      {accentColor && (
        <div 
          className="absolute top-0 left-0 w-full h-[2px]" 
          style={{ backgroundColor: accentColor, boxShadow: `0 0 8px ${accentColor}` }} 
        />
      )}
      {children}
    </div>
  );
}
