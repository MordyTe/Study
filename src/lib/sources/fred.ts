/**
 * FRED (Federal Reserve Bank of St. Louis) — the single economic data source
 * for v1.
 *
 * Chosen deliberately: FRED mirrors the BLS and BEA series this system cares
 * about behind one stable, keyed JSON API, which means one host on the network
 * allowlist and one boundary module instead of four. The same boundary
 * discipline as the venue adapter applies: a positive path allowlist, and every
 * request routed through `fetchJson`, which calls the assertion before the URL
 * is even built.
 *
 * A key is free (fred.stlouisfed.org → "API key"). Without one this module
 * reports itself unconfigured and every dependent agent abstains — the honest
 * degradation, not a crash.
 */

import { fetchJson } from '@/lib/net/client';

export const FRED_BASE = 'https://api.stlouisfed.org';

export class ForbiddenFredPathError extends Error {
  constructor(path: string) {
    super(`Refused to request "${path}": not in the FRED read allowlist.`);
    this.name = 'ForbiddenFredPathError';
  }
}

export const FRED_ALLOWED_PATHS = ['/fred/series/observations', '/fred/series'] as const;
export type FredPath = (typeof FRED_ALLOWED_PATHS)[number];

export function assertFredPath(path: string): asserts path is FredPath {
  if (!(FRED_ALLOWED_PATHS as readonly string[]).includes(path)) {
    throw new ForbiddenFredPathError(path);
  }
}

export function isFredConfigured(
  env: Record<string, string | undefined> = process.env,
): boolean {
  const key = env['FRED_API_KEY'];
  return typeof key === 'string' && key.trim().length > 0;
}

export interface SeriesPoint {
  /** ISO date, e.g. "2026-06-01" — the period the value describes. */
  date: string;
  value: number;
}

/**
 * Observations for one series, ascending by date. Missing values (FRED encodes
 * them as ".") are dropped rather than treated as zero.
 */
export async function getSeriesObservations(
  seriesId: string,
  options: {
    observationStart?: string;
    fetchImpl?: typeof fetch;
    env?: Record<string, string | undefined>;
  } = {},
): Promise<SeriesPoint[]> {
  const env = options.env ?? process.env;
  const apiKey = env['FRED_API_KEY'];
  if (!apiKey) throw new Error('FRED_API_KEY is not configured.');

  const raw = await fetchJson<{ observations?: Array<{ date?: string; value?: string }> }>({
    adapter: 'fred',
    baseUrl: FRED_BASE,
    path: '/fred/series/observations',
    assertPath: assertFredPath,
    query: {
      series_id: seriesId,
      api_key: apiKey,
      file_type: 'json',
      observation_start: options.observationStart ?? '2000-01-01',
    },
    fetchImpl: options.fetchImpl,
  });

  return (raw.observations ?? [])
    .map((o) => {
      if (typeof o.date !== 'string' || typeof o.value !== 'string' || o.value === '.') return null;
      const value = Number(o.value);
      return Number.isFinite(value) ? { date: o.date, value } : null;
    })
    .filter((p): p is SeriesPoint => p !== null);
}
