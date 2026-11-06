/**
 * BybitPublicMarketDataAdapter — the ONLY place in this codebase that talks to
 * Bybit. GET-only, allowlisted paths, no authentication, no credentials.
 *
 * Official docs baseline (see docs/VENDOR_BASELINE.md):
 *   https://bybit-exchange.github.io/docs/v5/guide
 */

import {
  ALLOWED_PATHS,
  BYBIT_REST_BASE,
  assertAllowedPath,
  type AllowedPath,
} from './allowlist';
import {
  BybitApiError,
  TIMEFRAME_TO_INTERVAL,
  type BybitEnvelope,
  type BybitInstrumentRaw,
  type Candle,
  type CandleSeries,
  type FundingPoint,
  type Instrument,
  type MarketCategory,
  type OpenInterestPoint,
  type RateLimitSnapshot,
  type Ticker,
  type Timeframe,
} from './types';

const DEFAULT_TIMEOUT_MS = 12_000;
const MAX_RETRIES = 2;

/** retCodes that are permanent client errors — never retried. */
const NON_RETRYABLE_CODES = new Set([10001, 10002, 10003, 10004, 10005, 110001, 181001]);

function toNum(v: unknown, fallback = 0): number {
  if (v === null || v === undefined || v === '') return fallback;
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function toNumOrNull(v: unknown): number | null {
  if (v === null || v === undefined || v === '') return null;
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

export interface RequestMeta {
  path: string;
  latencyMs: number;
  correlationId: string;
  rateLimit: RateLimitSnapshot;
  serverTime: number;
}

export interface AdapterStats {
  requests: number;
  errors: number;
  lastLatencyMs: number | null;
  lastRateLimit: RateLimitSnapshot | null;
  lastError: string | null;
  lastSuccessAt: number | null;
}

let stats: AdapterStats = {
  requests: 0,
  errors: 0,
  lastLatencyMs: null,
  lastRateLimit: null,
  lastError: null,
  lastSuccessAt: null,
};

export function getAdapterStats(): AdapterStats {
  return { ...stats };
}

export function resetAdapterStats(): void {
  stats = {
    requests: 0,
    errors: 0,
    lastLatencyMs: null,
    lastRateLimit: null,
    lastError: null,
    lastSuccessAt: null,
  };
}

function correlationId(): string {
  return Math.random().toString(36).slice(2, 10);
}

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/**
 * Core request primitive. Enforces the allowlist, applies timeouts, retries only
 * safe reads, and parses the Bybit envelope rather than trusting HTTP status.
 */
export async function bybitGet<T>(
  path: AllowedPath | string,
  params: Record<string, string | number | undefined> = {},
): Promise<{ data: T; meta: RequestMeta }> {
  assertAllowedPath(path);

  const search = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') search.set(k, String(v));
  }
  const qs = search.toString();
  const url = `${BYBIT_REST_BASE}${path}${qs ? `?${qs}` : ''}`;
  const cid = correlationId();

  let lastError: Error | null = null;

  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    const startedAt = Date.now();
    stats.requests += 1;

    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), DEFAULT_TIMEOUT_MS);

      const res = await fetch(url, {
        method: 'GET',
        headers: { accept: 'application/json', 'user-agent': 'bybit-pattern-scanner/1.0 (analysis-only)' },
        signal: controller.signal,
        cache: 'no-store',
      }).finally(() => clearTimeout(timer));

      const latencyMs = Date.now() - startedAt;

      const rateLimit: RateLimitSnapshot = {
        limit: toNumOrNull(res.headers.get('x-bapi-limit')),
        status: toNumOrNull(res.headers.get('x-bapi-limit-status')),
        resetTimestamp: toNumOrNull(res.headers.get('x-bapi-limit-reset-timestamp')),
      };
      stats.lastRateLimit = rateLimit;
      stats.lastLatencyMs = latencyMs;

      if (res.status === 429 || res.status >= 500) {
        throw new BybitApiError(path, res.status, `HTTP ${res.status}`, true);
      }

      const body = (await res.json()) as BybitEnvelope<T>;

      if (body.retCode !== 0) {
        const retryable = !NON_RETRYABLE_CODES.has(body.retCode) && body.retCode >= 10006;
        throw new BybitApiError(path, body.retCode, body.retMsg ?? 'unknown', retryable);
      }

      stats.lastSuccessAt = Date.now();
      return {
        data: body.result,
        meta: { path, latencyMs, correlationId: cid, rateLimit, serverTime: body.time },
      };
    } catch (err) {
      lastError = err instanceof Error ? err : new Error(String(err));
      stats.errors += 1;
      stats.lastError = lastError.message;

      const retryable =
        lastError instanceof BybitApiError
          ? lastError.retryable
          : lastError.name === 'AbortError' || lastError.name === 'TypeError';

      if (!retryable || attempt === MAX_RETRIES) break;
      // Exponential backoff with jitter.
      await sleep(250 * 2 ** attempt + Math.random() * 200);
    }
  }

  throw lastError ?? new Error(`Bybit request failed: ${path}`);
}

// ── Endpoints ─────────────────────────────────────────────────────────────

export async function getServerTime(): Promise<{ seconds: number; nano: string; latencyMs: number }> {
  const { data, meta } = await bybitGet<{ timeSecond: string; timeNano: string }>('/v5/market/time');
  return { seconds: toNum(data.timeSecond), nano: data.timeNano, latencyMs: meta.latencyMs };
}

/** Instrument-level exclusions. Stock tokens are not crypto pairs. */
function isExcludedSpot(raw: BybitInstrumentRaw): boolean {
  const s = raw.symbol.toUpperCase();
  if (s.includes('XSTOCK')) return true;
  // Leveraged tokens (3L/3S/2L/2S) behave nothing like their underlying.
  if (/\d[LS]USDT$/.test(s)) return true;
  return false;
}

function normalizeInstrument(raw: BybitInstrumentRaw, category: MarketCategory): Instrument {
  return {
    id: `${category}:${raw.symbol}`,
    category,
    symbol: raw.symbol,
    baseCoin: raw.baseCoin,
    quoteCoin: raw.quoteCoin,
    status: raw.status,
    contractType: raw.contractType ?? null,
    settleCoin: raw.settleCoin ?? null,
    launchTime: raw.launchTime ? toNum(raw.launchTime) : null,
    tickSize: toNum(raw.priceFilter?.tickSize, 0.01),
    qtyStep: toNum(raw.lotSizeFilter?.qtyStep ?? raw.lotSizeFilter?.basePrecision, 0.001),
    active: raw.status === 'Trading',
  };
}

/**
 * Fetches every eligible instrument for a category, following nextPageCursor to
 * exhaustion. Linear routinely exceeds 500 instruments — never assume one page.
 */
export async function getInstruments(category: MarketCategory): Promise<Instrument[]> {
  const out: Instrument[] = [];
  let cursor: string | undefined;
  let pages = 0;

  do {
    const { data } = await bybitGet<{ list: BybitInstrumentRaw[]; nextPageCursor?: string }>(
      '/v5/market/instruments-info',
      { category, limit: 1000, cursor },
    );

    for (const raw of data.list ?? []) {
      if (raw.status !== 'Trading') continue;
      if (raw.quoteCoin !== 'USDT') continue;

      if (category === 'spot') {
        if (isExcludedSpot(raw)) continue;
      } else {
        if (raw.settleCoin !== 'USDT') continue;
        if (raw.contractType !== 'LinearPerpetual') continue;
        // Pre-listing instruments have no tradable history.
        if (raw.launchTime && toNum(raw.launchTime) > Date.now()) continue;
      }

      out.push(normalizeInstrument(raw, category));
    }

    cursor = data.nextPageCursor && data.nextPageCursor !== '' ? data.nextPageCursor : undefined;
    pages += 1;
  } while (cursor && pages < 20);

  return out;
}

interface TickerRaw {
  symbol: string;
  lastPrice: string;
  prevPrice24h?: string;
  price24hPcnt?: string;
  highPrice24h?: string;
  lowPrice24h?: string;
  turnover24h?: string;
  volume24h?: string;
  bid1Price?: string;
  ask1Price?: string;
  markPrice?: string;
  indexPrice?: string;
  openInterest?: string;
  fundingRate?: string;
  nextFundingTime?: string;
}

function normalizeTicker(raw: TickerRaw, category: MarketCategory): Ticker {
  const bid = toNumOrNull(raw.bid1Price);
  const ask = toNumOrNull(raw.ask1Price);
  const mid = bid !== null && ask !== null && bid > 0 ? (bid + ask) / 2 : null;
  const spreadBps = mid !== null && ask !== null && bid !== null && mid > 0 ? ((ask - bid) / mid) * 10_000 : null;

  return {
    id: `${category}:${raw.symbol}`,
    category,
    symbol: raw.symbol,
    lastPrice: toNum(raw.lastPrice),
    prevPrice24h: toNum(raw.prevPrice24h),
    price24hPcnt: toNum(raw.price24hPcnt),
    highPrice24h: toNum(raw.highPrice24h),
    lowPrice24h: toNum(raw.lowPrice24h),
    turnover24h: toNum(raw.turnover24h),
    volume24h: toNum(raw.volume24h),
    bid1Price: bid,
    ask1Price: ask,
    markPrice: toNumOrNull(raw.markPrice),
    indexPrice: toNumOrNull(raw.indexPrice),
    openInterest: toNumOrNull(raw.openInterest),
    fundingRate: toNumOrNull(raw.fundingRate),
    nextFundingTime: toNumOrNull(raw.nextFundingTime),
    spreadBps,
  };
}

/** One call returns the whole category — the backbone of Tier-1 scanning. */
export async function getTickers(category: MarketCategory): Promise<Ticker[]> {
  const { data } = await bybitGet<{ list: TickerRaw[] }>('/v5/market/tickers', { category });
  return (data.list ?? []).map((t) => normalizeTicker(t, category));
}

export async function getTicker(category: MarketCategory, symbol: string): Promise<Ticker | null> {
  const { data } = await bybitGet<{ list: TickerRaw[] }>('/v5/market/tickers', { category, symbol });
  const first = data.list?.[0];
  return first ? normalizeTicker(first, category) : null;
}

/**
 * Bybit kline rows are [start, open, high, low, close, volume, turnover],
 * returned newest-first. We reverse to ascending and drop the still-open candle
 * unless explicitly requested.
 */
export async function getKlines(
  category: MarketCategory,
  symbol: string,
  timeframe: Timeframe,
  limit = 200,
  opts: { includeOpen?: boolean; end?: number; start?: number } = {},
): Promise<CandleSeries> {
  const interval = TIMEFRAME_TO_INTERVAL[timeframe];
  const { data } = await bybitGet<{ list: string[][] }>('/v5/market/kline', {
    category,
    symbol,
    interval,
    limit: Math.min(1000, Math.max(1, limit)),
    start: opts.start,
    end: opts.end,
  });

  const rows = data.list ?? [];
  const candles: Candle[] = rows
    .map((r) => ({
      time: toNum(r[0]),
      open: toNum(r[1]),
      high: toNum(r[2]),
      low: toNum(r[3]),
      close: toNum(r[4]),
      volume: toNum(r[5]),
      turnover: toNum(r[6]),
    }))
    .filter((c) => c.time > 0 && c.open > 0 && c.high > 0 && c.low > 0 && c.close > 0)
    .sort((a, b) => a.time - b.time);

  return {
    instrumentId: `${category}:${symbol}`,
    category,
    symbol,
    timeframe,
    candles,
    includesOpen: opts.includeOpen ?? true,
    fetchedAt: Date.now(),
  };
}

export async function getOpenInterest(
  symbol: string,
  intervalTime: '5min' | '15min' | '30min' | '1h' | '4h' | '1d' = '1h',
  limit = 50,
): Promise<OpenInterestPoint[]> {
  const { data } = await bybitGet<{ list: { openInterest: string; timestamp: string }[] }>(
    '/v5/market/open-interest',
    { category: 'linear', symbol, intervalTime, limit },
  );
  return (data.list ?? [])
    .map((p) => ({ timestamp: toNum(p.timestamp), openInterest: toNum(p.openInterest) }))
    .sort((a, b) => a.timestamp - b.timestamp);
}

export async function getFundingHistory(symbol: string, limit = 50): Promise<FundingPoint[]> {
  const { data } = await bybitGet<{ list: { fundingRate: string; fundingRateTimestamp: string }[] }>(
    '/v5/market/funding/history',
    { category: 'linear', symbol, limit },
  );
  return (data.list ?? [])
    .map((p) => ({ timestamp: toNum(p.fundingRateTimestamp), fundingRate: toNum(p.fundingRate) }))
    .sort((a, b) => a.timestamp - b.timestamp);
}

export async function getOrderbook(
  category: MarketCategory,
  symbol: string,
  depth = 50,
): Promise<{ bids: [number, number][]; asks: [number, number][]; timestamp: number }> {
  const { data } = await bybitGet<{ b: string[][]; a: string[][]; ts: number }>('/v5/market/orderbook', {
    category,
    symbol,
    limit: depth,
  });
  const conv = (rows: string[][] = []): [number, number][] =>
    rows.map((r) => [toNum(r[0]), toNum(r[1])] as [number, number]);
  return { bids: conv(data.b), asks: conv(data.a), timestamp: data.ts };
}

export { ALLOWED_PATHS };
