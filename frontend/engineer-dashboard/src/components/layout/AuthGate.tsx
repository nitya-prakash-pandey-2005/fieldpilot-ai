"use client";

import React, { useEffect } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { useAuth } from '@/context/AuthContext';
import { Sidebar } from './Sidebar';
import { Header } from './Header';

/**
 * Gates the whole dashboard shell behind login. /login itself renders
 * bare (no sidebar/header). Every other route redirects to /login if
 * there's no valid session — previously there was no auth of any kind
 * anywhere in the app.
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const isLoginPage = pathname === '/login';
  // The worker device is a phone held one-handed in gloves. The desktop shell —
  // fixed sidebar, header, notification bell — costs most of a phone screen and
  // navigates nowhere a worker needs to go, so /worker renders bare like /login.
  const isBarePage = isLoginPage || pathname === '/worker';

  useEffect(() => {
    if (!isLoading && !user && !isLoginPage) {
      router.push('/login');
    }
  }, [isLoading, user, isLoginPage, router]);

  // /login is the only page that renders before authentication. /worker is
  // still gated — it reaches a real site's camera and voice loop — it just
  // renders without the desktop shell once the worker is signed in. Returning
  // it here unconditionally would flash the full worker UI for a moment before
  // the redirect landed.
  if (isLoginPage) {
    return <>{children}</>;
  }

  if (isLoading) {
    return (
      <div className="min-h-screen w-full flex items-center justify-center bg-[var(--bg-base)]">
        <div className="w-6 h-6 rounded-full border-2 border-[var(--cyan)] border-t-transparent animate-spin" />
      </div>
    );
  }

  if (!user) {
    // Redirect is in flight (useEffect above) — render nothing to avoid a
    // flash of the protected shell.
    return null;
  }

  if (isBarePage) {
    return <>{children}</>;
  }

  return (
    <div className="flex w-full min-h-screen h-screen overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col min-h-0 h-full overflow-hidden bg-[var(--bg-base)] relative">
        <Header />
        <main className="flex-1 overflow-y-auto p-4 md:p-6 lg:p-8 relative z-10">
          {children}
        </main>
      </div>
    </div>
  );
}
