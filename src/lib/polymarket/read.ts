/**
 * The ONLY module in this codebase that opens a connection to Polymarket.
 *
 * Every function here routes through `fetchJson`, which calls this module's own
 * allowlist assertion as its first statement. Adding a new venue call means
 * adding a path to `allowlist.ts` in a diff a reviewer can read in ten seconds.
 *
 * Read-only by construction: no credential is ever attached to a request, and
 * `assertNoVenueCredentials` refuses to let the process run if one is present.
 */

import { fetchJson, getAdapterStats, type AdapterStats } from '@/lib/net/client';
import { assertClobPath, assertGammaPath, assertNoVenueCredentials } from './allowlist';
import {
  normalizeEvent,
  normalizeMarket,
  normalizeOrderBook,
  type EventGroup,
  type Market,
  type OrderBook,
} from './types';

export const GAMMA_BASE = 'https://gamma-api.polymarket.com';
export const CLOB_BASE = 'https://clob.polymarket.com';

const GAMMA = 'gamma';
const CLOB = 'clob';

/**
 * Called at the top of every entry point that can reach the network. Mirrors
 * the previous project's boot-time credential check: the presence of a key is
 * itself the thing being refused, not merely its use.
 */
export function assertReadOnlyEnvironment(env: NodeJS.ProcessEnv = process.env): void {
  assertNoVenueCredentials(env as Record<string, string | undefined>);
}

export interface ListEventsOptions {
  limit?: number;
  offset?: number;
  /** Gamma's sort key, e.g. `volume_24hr`, `liquidity`, `end_date`. */
  order?: string;
  ascending?: boolean;
  tagId?: number;
  fetchImpl?: typeof fetch;
}

/**
 * One page of open events, each carrying its constituent markets.
 *
 * Tier 1 of the scan walks this endpoint and nothing else: it is the single
 * cheap call that covers the whole universe, which is what makes the expensive
 * per-market agent work affordable.
 */
export async function listEvents(options: ListEventsOptions = {}): Promise<EventGroup[]> {
  const raw = await fetchJson<unknown>({
    adapter: GAMMA,
    baseUrl: GAMMA_BASE,
    path: '/events',
    assertPath: assertGammaPath,
    query: {
      active: true,
      closed: false,
      archived: false,
      limit: options.limit ?? 100,
      offset: options.offset ?? 0,
      order: options.order ?? 'volume_24hr',
      ascending: options.ascending ?? false,
      tag_id: options.tagId,
    },
    fetchImpl: options.fetchImpl,
  });

  // Gamma has returned both a bare array and a `{data: [...]}` envelope across
  // versions. Accept either rather than breaking on a shape change.
  const rows = Array.isArray(raw)
    ? raw
    : Array.isArray((raw as { data?: unknown })?.data)
      ? ((raw as { data: unknown[] }).data)
      : [];

  return rows
    .map((row) =>
      typeof row === 'object' && row !== null
        ? normalizeEvent(row as Record<string, unknown>)
        : null,
    )
    .filter((e): e is EventGroup => e !== null);
}

/**
 * Walk `listEvents` to completion, bounded. The bound is not decoration: an
 * unbounded walk against a paginated endpoint is how a scan turns into an
 * accidental denial-of-service against a host that rate-limits without headers.
 */
export async function listAllEvents(
  maxPages = 20,
  pageSize = 100,
  fetchImpl?: typeof fetch,
): Promise<{ events: EventGroup[]; pagesFetched: number; truncated: boolean }> {
  const events: EventGroup[] = [];
  let pagesFetched = 0;

  for (let page = 0; page < maxPages; page++) {
    const batch = await listEvents({ limit: pageSize, offset: page * pageSize, fetchImpl });
    pagesFetched += 1;
    events.push(...batch);
    if (batch.length < pageSize) {
      return { events, pagesFetched, truncated: false };
    }
  }
  // Truncation is reported, never silent.
  return { events, pagesFetched, truncated: true };
}

export async function getMarketBySlug(
  slug: string,
  fetchImpl?: typeof fetch,
): Promise<Market | null> {
  const raw = await fetchJson<unknown>({
    adapter: GAMMA,
    baseUrl: GAMMA_BASE,
    path: '/markets',
    assertPath: assertGammaPath,
    query: { slug },
    fetchImpl,
  });
  const rows = Array.isArray(raw) ? raw : [];
  const first = rows[0];
  return typeof first === 'object' && first !== null
    ? normalizeMarket(first as Record<string, unknown>)
    : null;
}

/** Full order book for one outcome token. Tier 2 — one call per candidate. */
export async function getOrderBook(
  tokenId: string,
  fetchImpl?: typeof fetch,
): Promise<OrderBook> {
  const raw = await fetchJson<Record<string, unknown>>({
    adapter: CLOB,
    baseUrl: CLOB_BASE,
    path: '/book',
    assertPath: assertClobPath,
    query: { token_id: tokenId },
    fetchImpl,
  });
  return normalizeOrderBook(tokenId, raw, Date.now());
}

/**
 * The venue's current taker fee rate. Queried, never hardcoded: the schedule
 * changed several times during 2026 and a stale constant silently turns a
 * losing edge into a reported winner.
 */
export async function getFeeRateBps(fetchImpl?: typeof fetch): Promise<number | null> {
  try {
    const raw = await fetchJson<Record<string, unknown>>({
      adapter: CLOB,
      baseUrl: CLOB_BASE,
      path: '/fee-rate',
      assertPath: assertClobPath,
      fetchImpl,
    });
    const value = raw['fee_rate_bps'] ?? raw['feeRateBps'] ?? raw['baseFeeRateBps'];
    const parsed = typeof value === 'string' ? Number(value) : value;
    return typeof parsed === 'number' && Number.isFinite(parsed) ? parsed : null;
  } catch {
    // A missing fee rate must not be treated as a zero fee. The caller falls
    // back to the conservative configured default and records that it did.
    return null;
  }
}

/** Venue clock, used for the drift component of the verification record. */
export async function getServerTimeMs(fetchImpl?: typeof fetch): Promise<number | null> {
  try {
    const raw = await fetchJson<unknown>({
      adapter: CLOB,
      baseUrl: CLOB_BASE,
      path: '/time',
      assertPath: assertClobPath,
      fetchImpl,
    });
    const seconds = typeof raw === 'number' ? raw : Number(raw);
    return Number.isFinite(seconds) ? seconds * 1000 : null;
  } catch {
    return null;
  }
}

export function venueStats(): { gamma: AdapterStats; clob: AdapterStats } {
  return { gamma: getAdapterStats(GAMMA), clob: getAdapterStats(CLOB) };
}
