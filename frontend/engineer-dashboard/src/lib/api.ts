/**
 * Where the FieldPilot API lives, resolved at runtime.
 *
 * Every call site used to inline `process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000"`.
 * That fallback is correct only when the dashboard is opened ON the machine
 * running the backend. Open the same page from a phone at
 * http://192.168.1.42:3000 and the browser is the phone, so `127.0.0.1` means
 * the phone itself — the page renders but every panel fails to load, which
 * looks like a broken app rather than a misconfigured URL.
 *
 * Resolution order:
 *   1. NEXT_PUBLIC_API_URL          explicit override, always wins
 *   2. the page's own hostname      whoever served the dashboard also serves
 *                                   the API, on API_PORT
 *   3. 127.0.0.1                    server-side rendering only
 *
 * Rule 2 makes laptop and phone both work with no configuration: the host the
 * dashboard was fetched from is by definition reachable from the device that
 * fetched it.
 */

const API_PORT = process.env.NEXT_PUBLIC_API_PORT ?? "8000";

function stripTrailingSlash(url: string): string {
  return url.replace(/\/+$/, "");
}

export function apiBase(): string {
  const explicit = process.env.NEXT_PUBLIC_API_URL;
  if (explicit) return stripTrailingSlash(explicit);

  if (typeof window !== "undefined" && window.location?.hostname) {
    const { protocol, hostname } = window.location;

    // Rule 2b — an HTTPS page must use the same-origin proxy.
    //
    // The worker device is a phone, and a phone will not grant camera or
    // microphone access on a plain http:// origin, so the page is served over
    // HTTPS through a tunnel. From that page, a call to http://<host>:8000 is
    // mixed content and the browser refuses it before any request is made; and
    // the tunnel only forwards 443, so port 8000 is not reachable under that
    // hostname anyway. Returning "" routes through the /api/:path* rewrite in
    // next.config.mjs, which reaches the backend server-side.
    if (protocol === "https:") return "";

    return `${protocol}//${hostname}:${API_PORT}`;
  }

  // SSR / build time. Client components re-resolve on mount, so this value
  // never reaches a real browser request.
  return `http://127.0.0.1:${API_PORT}`;
}

export function wsBase(): string {
  const explicit = process.env.NEXT_PUBLIC_WS_URL;
  if (explicit) return stripTrailingSlash(explicit);

  const base = apiBase();
  // apiBase() returns "" on an HTTPS page (same-origin proxy). A WebSocket URL
  // cannot be relative, so build an absolute one from the page.
  //
  // Note: Next's rewrites do not proxy WebSocket upgrades, so the /ws/* feeds
  // (digital twin, glasses stream) do not survive a tunnel. The worker device
  // does not use them — it polls over fetch — but a dashboard opened through
  // the tunnel will lose its live WS panels. Point NEXT_PUBLIC_WS_URL at a
  // directly reachable host if you need them.
  if (!base && typeof window !== "undefined") {
    const { protocol, host } = window.location;
    return `${protocol === "https:" ? "wss:" : "ws:"}//${host}`;
  }
  return base.replace(/^http/, "ws");
}

/** Convenience: `apiUrl("/api/v1/health")` -> fully qualified URL. */
export function apiUrl(path: string): string {
  return `${apiBase()}${path.startsWith("/") ? path : `/${path}`}`;
}

/**
 * Kept as a named export because most existing call sites interpolate a bare
 * string (`${API}/api/v1/...`). Note this is evaluated at MODULE LOAD time —
 * for components that may render server-side first, prefer calling apiBase()
 * inside the effect so it resolves in the browser.
 */
export const API_BASE = apiBase();
