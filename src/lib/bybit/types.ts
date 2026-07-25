/** Typed models for the Bybit V5 public market-data surface. */

export type MarketCategory = 'spot' | 'linear';

/** Bybit interval identifiers exactly as documented. */
export type BybitInterval = '5' | '15' | '30' | '60' | '120' | '240' | 'D';

export const TIMEFRAMES = ['5m', '15m', '30m', '1h', '2h', '4h', '1d'] as const;
export type Timeframe = (typeof TIMEFRAMES)[number];

export const TIMEFRAME_TO_INTERVAL: Record<Timeframe, BybitInterval> = {
  '5m': '5',
  '15m': '15',
  '30m': '30',
  '1h': '60',
  '2h': '120',
  '4h': '240',
  '1d': 'D',
};

export const TIMEFRAME_MS: Record<Timeframe, number> = {
  '5m': 5 * 60_000,
  '15m': 15 * 60_000,
  '30m': 30 * 60_000,
  '1h': 60 * 60_000,
  '2h': 120 * 60_000,
  '4h': 240 * 60_000,
  '1d': 24 * 60 * 60_000,
};

/** Envelope returned by every Bybit V5 endpoint. */
export interface BybitEnvelope<T> {
  retCode: number;
  retMsg: string;
  result: T;
  retExtInfo?: Record<string, unknown>;
  time: number;
}

export interface BybitInstrumentRaw {
  symbol: string;
  baseCoin: string;
  quoteCoin: string;
  status: string;
  contractType?: string;
  settleCoin?: string;
  launchTime?: string;
  innovation?: string;
  marginTrading?: string;
  lotSizeFilter?: {
    basePrecision?: string;
    quotePrecision?: string;
    minOrderQty?: string;
    qtyStep?: string;
    minNotionalValue?: string;
  };
  priceFilter?: { tickSize?: string; minPrice?: string; maxPrice?: string };
}

/** Normalized instrument identity used everywhere in the app. */
export interface Instrument {
  /** Stable composite identity, e.g. "linear:BTCUSDT". Spot and linear are distinct. */
  id: string;
  category: MarketCategory;
  symbol: string;
  baseCoin: string;
  quoteCoin: string;
  status: string;
  contractType: string | null;
  settleCoin: string | null;
  launchTime: number | null;
  tickSize: number;
  qtyStep: number;
  active: boolean;
}

export interface Ticker {
  id: string;
  category: MarketCategory;
  symbol: string;
  lastPrice: number;
  prevPrice24h: number;
  price24hPcnt: number;
  highPrice24h: number;
  lowPrice24h: number;
  turnover24h: number;
  volume24h: number;
  bid1Price: number | null;
  ask1Price: number | null;
  /** Linear only. */
  markPrice: number | null;
  indexPrice: number | null;
  openInterest: number | null;
  fundingRate: number | null;
  nextFundingTime: number | null;
  /** Spread in basis points, derived from bid/ask when available. */
  spreadBps: number | null;
}

export interface Candle {
  /** Candle open time, epoch ms (UTC). */
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  turnover: number;
}

export interface CandleSeries {
  instrumentId: string;
  category: MarketCategory;
  symbol: string;
  timeframe: Timeframe;
  /** Ascending by time. Only closed candles unless `includesOpen` is true. */
  candles: Candle[];
  includesOpen: boolean;
  fetchedAt: number;
}

export interface OpenInterestPoint {
  timestamp: number;
  openInterest: number;
}

export interface FundingPoint {
  timestamp: number;
  fundingRate: number;
}

export interface RateLimitSnapshot {
  limit: number | null;
  status: number | null;
  resetTimestamp: number | null;
}

export class BybitApiError extends Error {
  readonly retCode: number;
  readonly path: string;
  readonly retryable: boolean;

  constructor(path: string, retCode: number, retMsg: string, retryable: boolean) {
    super(`Bybit ${path} failed (retCode=${retCode}): ${retMsg}`);
    this.name = 'BybitApiError';
    this.retCode = retCode;
    this.path = path;
    this.retryable = retryable;
  }
}
