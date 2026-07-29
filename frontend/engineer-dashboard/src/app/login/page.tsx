"use client";

import React, { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/context/AuthContext';

const DEMO_ACCOUNTS = [
  { role: 'Worker', email: 'worker@fieldpilot.demo' },
  { role: 'Site Engineer', email: 'engineer@fieldpilot.demo' },
  { role: 'Project Manager', email: 'pm@fieldpilot.demo' },
  { role: 'Admin', email: 'admin@fieldpilot.demo' },
  { role: 'Executive', email: 'executive@fieldpilot.demo' },
];

export default function LoginPage() {
  const { login } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    const result = await login(email, password);
    setSubmitting(false);
    if (result.ok) {
      router.push('/');
    } else {
      setError(result.error || 'Login failed');
    }
  };

  return (
    <div className="min-h-screen w-full flex items-center justify-center bg-[var(--bg-base)] blueprint-grid">
      <div className="w-full max-w-md p-8 bg-[var(--bg-surface)]/90 backdrop-blur-[20px] rounded-2xl border border-[var(--border-subtle)] shadow-2xl">
        <div className="flex items-center gap-3 mb-2">
          <span className="text-3xl">🏗</span>
          <h1 className="text-xl font-bold tracking-tight text-[var(--text-primary)] font-display uppercase">FieldPilot AI</h1>
        </div>
        <p className="text-sm text-[var(--text-secondary)] mb-6">Sign in to the site command center</p>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div>
            <label className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wide">Email</label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full px-3 py-2.5 rounded-lg bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-[var(--text-primary)] focus:outline-none focus:border-[var(--cyan)] transition-colors"
              placeholder="you@fieldpilot.demo"
            />
          </div>
          <div>
            <label className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wide">Password</label>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full px-3 py-2.5 rounded-lg bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-[var(--text-primary)] focus:outline-none focus:border-[var(--cyan)] transition-colors"
              placeholder="••••••••"
            />
          </div>

          {error && (
            <div className="text-xs text-[var(--fail)] bg-[var(--fail-dim)] border border-[var(--fail)]/30 rounded-lg px-3 py-2">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="mt-2 w-full py-2.5 bg-[var(--cyan)] text-black font-bold tracking-wide rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50"
          >
            {submitting ? 'Signing in…' : 'Sign In'}
          </button>
        </form>

        <div className="mt-6 pt-6 border-t border-[var(--border-subtle)]">
          <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest mb-2">Demo accounts (password: fieldpilot123)</p>
          <div className="flex flex-col gap-1.5">
            {DEMO_ACCOUNTS.map((acc) => (
              <button
                key={acc.email}
                type="button"
                onClick={() => { setEmail(acc.email); setPassword('fieldpilot123'); }}
                className="text-left text-xs px-2.5 py-1.5 rounded-md bg-[var(--bg-elevated)] hover:bg-[var(--bg-hover)] border border-[var(--border-subtle)] transition-colors text-[var(--text-secondary)]"
              >
                <span className="font-semibold text-[var(--cyan)]">{acc.role}</span> — {acc.email}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
