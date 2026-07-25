'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

export interface FetchState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  refresh: () => void;
  lastUpdated: number | null;
}

/**
 * Polling fetch hook with abort-on-unmount and refresh-in-place (no flash of
 * loading state on interval refreshes).
 */
export function usePolling<T>(url: string | null, intervalMs = 30_000): FetchState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);
  const [nonce, setNonce] = useState(0);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const refresh = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    if (!url) {
      setLoading(false);
      return;
    }

    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | null = null;

    const load = async (isFirst: boolean) => {
      if (isFirst) setLoading(true);
      try {
        const res = await fetch(url, { cache: 'no-store', signal: controller.signal });
        const body = await res.json();
        if (!mounted.current) return;

        if (!res.ok || body?.ok === false) {
          setError(body?.error ?? `Request failed with status ${res.status}`);
        } else {
          setData(body as T);
          setError(null);
          setLastUpdated(Date.now());
        }
      } catch (err) {
        if ((err as Error).name === 'AbortError') return;
        if (mounted.current) setError((err as Error).message);
      } finally {
        if (mounted.current) setLoading(false);
      }
    };

    void load(true);

    if (intervalMs > 0) {
      const tick = () => {
        void load(false);
        timer = setTimeout(tick, intervalMs);
      };
      timer = setTimeout(tick, intervalMs);
    }

    return () => {
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [url, intervalMs, nonce]);

  return { data, error, loading, refresh, lastUpdated };
}
