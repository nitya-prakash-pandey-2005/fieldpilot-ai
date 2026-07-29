"use client";

import React, { useState, useEffect } from 'react';
import { Bell, Menu } from 'lucide-react';
import { ThemeToggle } from './ThemeToggle';

import { useConnectionStatus } from '../../hooks/useConnectionStatus';
import { useAuth, ROLE_LABELS } from '@/context/AuthContext';

const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export function Header() {
  const { status } = useConnectionStatus();
  const { user } = useAuth();
  const [notifCount, setNotifCount] = useState<number | null>(null);

  useEffect(() => {
    fetch(`${API}/api/v1/notification/active`)
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(data => setNotifCount((data.data || []).length))
      .catch(() => setNotifCount(null));
  }, []);

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

      {/* CENTER — single active project (multi-project switching isn't
          implemented server-side yet; every route defaults to
          "default-project", so this no longer pretends to switch between
          projects that don't exist) */}
      <div className="hidden md:flex items-center gap-2 px-4 py-2 rounded-lg border border-[var(--border-muted)]">
        <span className="w-1.5 h-1.5 rounded-full bg-[var(--cyan)]" />
        <span className="text-sm font-medium text-[var(--text-primary)]">Downtown Tower Phase 2</span>
      </div>

      {/* RIGHT */}
      <div className="flex items-center gap-4">

        {/* Language — single-language (English) for now; no i18n exists yet */}
        <div className="hidden sm:flex items-center text-xs font-medium text-[var(--text-muted)]">
          <span>EN</span>
        </div>

        {/* WebSocket Status */}
        <div className="flex items-center gap-1.5">
          <span
            className={`w-[7px] h-[7px] rounded-full ${status === 'live' ? 'animate-pulse' : ''}`}
            style={{ background: status === 'live' ? 'var(--pass)' : status === 'offline' ? 'var(--fail)' : 'var(--amber)' }}
          />
          <span
            className="text-[11px] font-medium tracking-wide border rounded px-1.5 py-0.5"
            style={{ color: status === 'live' ? 'var(--pass)' : status === 'offline' ? 'var(--fail)' : 'var(--amber)', borderColor: 'currentColor' }}
          >
            {status === 'live' ? 'LIVE' :
             status === 'offline' ? 'OFFLINE' : 'DEMO MODE'}
          </span>
        </div>

        {/* Notifications — real count from GET /api/v1/notification/active */}
        <a href="/notifications" className="relative text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors">
          <Bell size={18} />
          {notifCount !== null && notifCount > 0 && (
            <div className="absolute -top-1 -right-1 min-w-[14px] h-3.5 px-0.5 rounded-full bg-[var(--fail)] flex items-center justify-center border-2 border-[var(--bg-surface)]">
              <span className="text-[8px] font-bold text-white">{notifCount > 9 ? '9+' : notifCount}</span>
            </div>
          )}
        </a>

        <ThemeToggle />

        {/* Avatar — real logged-in user (was hardcoded "SC" regardless of who was logged in) */}
        {user && (
          <div
            className="w-8 h-8 rounded-full bg-[var(--cyan-dim)] border border-[var(--border-accent)] flex items-center justify-center cursor-pointer"
            title={`${user.name} — ${ROLE_LABELS[user.role]}`}
          >
            <span className="text-xs font-bold text-[var(--cyan)]">{user.name.split(' ').map(n => n[0]).join('').slice(0, 2)}</span>
          </div>
        )}

      </div>
    </header>
  );
}
