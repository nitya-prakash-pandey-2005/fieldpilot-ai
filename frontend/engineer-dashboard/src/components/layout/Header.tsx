"use client";

import React, { useState, useEffect } from 'react';
import { Bell, Menu, ChevronDown, User } from 'lucide-react';
import { ThemeToggle } from './ThemeToggle';

import { useConnectionStatus } from '../../hooks/useConnectionStatus';

export function Header() {
  const { status } = useConnectionStatus();

  return (
    <header className="h-12 w-full border-b border-[var(--border-subtle)] bg-[var(--bg-surface)]/80 backdrop-blur-md flex items-center justify-between px-4 z-50 sticky top-0 shrink-0">
      
      {/* LEFT */}
      <div className="flex items-center gap-3">
        <button className="lg:hidden text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
          <Menu size={20} />
        </button>
        <div className="flex items-baseline gap-1">
          <h1 className="text-[var(--text-primary)] font-bold tracking-tight text-lg" style={{ fontFamily: 'var(--font-display)' }}>
            FIELDPILOT AI
          </h1>
          <div className="w-1.5 h-1.5 rounded-full bg-[var(--cyan)]" />
        </div>
      </div>

      {/* CENTER */}
      <div className="relative group hidden md:flex">
        <div className="flex items-center gap-2 cursor-pointer px-4 py-2 rounded-lg border border-[var(--border-muted)] hover:bg-[var(--bg-elevated)] transition-colors">
          <span className="text-sm font-medium text-[var(--text-primary)]">Downtown Tower Phase 2</span>
          <ChevronDown size={14} className="text-[var(--text-muted)] group-hover:text-white transition-colors" />
        </div>
        
        {/* Dropdown Menu */}
        <div className="absolute top-full left-0 mt-2 w-56 bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-lg shadow-xl opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200 z-50">
          <div className="p-1">
            <div className="px-3 py-2 text-xs font-semibold text-[var(--text-muted)] tracking-wider uppercase">Active Projects</div>
            <button className="w-full text-left px-3 py-2 text-sm text-[var(--text-primary)] bg-[var(--cyan-dim)] rounded-md flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--cyan)]" /> Downtown Tower Phase 2
            </button>
            <button className="w-full text-left px-3 py-2 text-sm text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-white transition-colors rounded-md flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--text-muted)]" /> Marina Bay Extension
            </button>
            <button className="w-full text-left px-3 py-2 text-sm text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-white transition-colors rounded-md flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--text-muted)]" /> Terminal 3 Upgrade
            </button>
          </div>
        </div>
      </div>

      {/* RIGHT */}
      <div className="flex items-center gap-4">
        
        {/* Language */}
        <div className="hidden sm:flex items-center gap-1 cursor-pointer text-xs font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
          <span>EN</span>
          <ChevronDown size={12} />
        </div>

        {/* WebSocket Status */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{
            width: 7, height: 7, borderRadius: '50%',
            background: status === 'live' ? '#00e5c0' :
                        status === 'offline' ? '#e53935' : '#f59e0b',
            animation: status === 'live' ? 'pulse 1.5s infinite' : 'none'
          }} />
          <span style={{
            fontSize: 11, fontWeight: 500, letterSpacing: '0.5px',
            color: status === 'live' ? '#00e5c0' :
                   status === 'offline' ? '#e53935' : '#f59e0b',
            border: '1px solid currentColor',
            borderRadius: 4,
            padding: '1px 7px'
          }}>
            {status === 'live' ? 'LIVE' :
             status === 'offline' ? 'OFFLINE' : 'DEMO MODE'}
          </span>
        </div>

        {/* Notifications */}
        <button className="relative text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors">
          <Bell size={18} />
          <div className="absolute -top-1 -right-1 w-3.5 h-3.5 rounded-full bg-[var(--fail)] flex items-center justify-center border-2 border-[var(--bg-surface)]">
            <span className="text-[8px] font-bold text-white">3</span>
          </div>
        </button>

        <ThemeToggle />

        {/* Avatar */}
        <div className="w-8 h-8 rounded-full bg-[var(--cyan-dim)] border border-[var(--border-accent)] flex items-center justify-center cursor-pointer">
          <span className="text-xs font-bold text-[var(--cyan)]">SC</span>
        </div>
        
      </div>
    </header>
  );
}
