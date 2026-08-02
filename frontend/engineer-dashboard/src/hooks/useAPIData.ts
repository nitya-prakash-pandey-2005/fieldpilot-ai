import { useCallback, useEffect, useState } from 'react';

import { apiBase } from '@/lib/api';

/**
 * Fetch a backend endpoint, with an optional fallback while it loads.
 *
 * Returns `error` as well as `isLive`: callers previously had no way to tell
 * "the request failed" from "the request succeeded and returned nothing", so
 * an unreachable backend and a genuinely empty result rendered identically —
 * usually as a blank panel with no explanation.
 *
 * Note the unwrapping rule: responses shaped `{ data: ... }` yield the inner
 * `data`; anything else is returned as-is. Both shapes exist in this API
 * (`/learning/trends` wraps, `/projects/{id}/issues` does not).
 */
export function useAPIData<T = any>(
  endpoint: string,
  fallback?: T,
  options: RequestInit = {},
) {
  const [data, setData] = useState<T | undefined>(fallback);
  const [loading, setLoading] = useState(true);
  const [isLive, setIsLive] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // options is typically an inline object literal, so it is a new reference on
  // every render — including it in the effect deps would refetch forever.
  const optionsKey = JSON.stringify(options ?? {});

  const refetch = useCallback(async () => {
    const API = apiBase();
    try {
      const res = await fetch(`${API}${endpoint}`, options);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body = await res.json();
      setData(body?.data !== undefined ? body.data : body);
      setIsLive(true);
      setError(null);
    } catch (e: any) {
      setIsLive(false);
      setError(e?.message ?? 'request failed');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [endpoint, optionsKey]);

  useEffect(() => {
    let cancelled = false;
    (async () => { if (!cancelled) await refetch(); })();
    return () => { cancelled = true; };
  }, [refetch]);

  return { data, loading, isLive, error, refetch };
}
