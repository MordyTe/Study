/** Shared contract every pattern detector implements. */

import type { Candle, MarketCategory, Timeframe } from '@/lib/bybit/types';
import type { Level, MarketStructure, Pivot } from '@/lib/ta/structure';
import type { Series } from '@/lib/ta/indicators';

export type Direction = 'long' | 'short';

export type PatternStatus =
  | 'FORMING'
  | 'CONFIRMED'
  | 'INVALIDATED'
  | 'EXPIRED'
  | 'TARGET_1_REACHED'
  | 'TARGET_2_REACHED'
  | 'CLOSED_TRACKING';

/** Chart overlay primitives. The web chart and the Telegram image both render these. */
export type Overlay =
  | { type: 'horizontal_line'; price: number; label: string; color: 'neutral' | 'bull' | 'bear' | 'warn' }
  | { type: 'trend_line'; from: { time: number; price: number }; to: { time: number; price: number }; label: string; color: 'neutral' | 'bull' | 'bear' | 'warn' }
  | { type: 'price_zone'; from: number; to: number; label: string; color: 'neutral' | 'bull' | 'bear' | 'warn' }
  | { type: 'marker'; time: number; price: number; label: string; color: 'neutral' | 'bull' | 'bear' | 'warn' }
  | { type: 'target_line'; price: number; label: string }
  | { type: 'invalidation_line'; price: number; label: string };

/** Precomputed indicator snapshot handed to every detector — computed once per series. */
export interface IndicatorSnapshot {
  closes: number[];
  highs: number[];
  lows: number[];
  volumes: number[];
  turnovers: number[];
  atr: Series;
  atrLast: number;
  ema20: Series;
  ema50: Series;
  ema200: Series;
  rsi: Series;
  macd: { macd: Series; signal: Series; histogram: Series };
  bollinger: { upper: Series; middle: Series; lower: Series; bandwidth: Series };
  keltner: { upper: Series; middle: Series; lower: Series };
  adx: Series;
  volumeZ: Series;
  realizedVol: Series;
  pivots: Pivot[];
  levels: Level[];
  structure: MarketStructure;
}

/** Market-wide context that is not derivable from the candle series alone. */
export interface MarketContext {
  instrumentId: string;
  category: MarketCategory;
  symbol: string;
  timeframe: Timeframe;
  tickSize: number;
  turnover24h: number;
  spreadBps: number | null;
  fundingRate: number | null;
  openInterestChangePct: number | null;
  /** Structure state of the next higher timeframe, when available. */
  higherTimeframeBias: 'uptrend' | 'downtrend' | 'range' | null;
  launchTime: number | null;
}

export interface PatternCandidate {
  detectorName: string;
  detectorVersion: string;
  displayName: string;
  direction: Direction;
  /** Detector's own conviction, 0..1. Feeds the geometry component of the score. */
  geometryQuality: number;
  /** Index of the candle that confirmed the pattern (last closed candle). */
  confirmationIndex: number;
  confirmationTime: number;
  /** Analytical scenario values — never orders. */
  entryZone: { from: number; to: number };
  invalidation: number;
  targets: { price: number; method: string }[];
  overlays: Overlay[];
  reasonsFor: string[];
  reasonsAgainst: string[];
  /** Detector parameters, persisted so historical results stay reproducible. */
  parameters: Record<string, number | string | boolean>;
  /** Free-form geometric evidence (pivot times/prices, fit quality, etc). */
  evidence: Record<string, unknown>;
}

export interface PatternDetector {
  name: string;
  version: string;
  displayName: string;
  description: string;
  /** Minimum closed candles required before the detector may run. */
  minCandles: number;
  detect(candles: Candle[], indicators: IndicatorSnapshot, context: MarketContext): PatternCandidate[];
}

/** Rounds a scenario price to the instrument's tick size — no fake precision. */
export function roundToTick(price: number, tickSize: number): number {
  if (!Number.isFinite(price) || tickSize <= 0) return price;
  const decimals = Math.max(0, Math.min(12, Math.ceil(-Math.log10(tickSize))));
  return Number((Math.round(price / tickSize) * tickSize).toFixed(decimals));
}

/** Reward-to-risk of a scenario, using the far edge of the entry zone. */
export function rewardToRisk(
  direction: Direction,
  entry: number,
  invalidation: number,
  target: number,
): number {
  const risk = Math.abs(entry - invalidation);
  if (risk <= 0) return 0;
  const reward = direction === 'long' ? target - entry : entry - target;
  return reward / risk;
}

/** The entry price a scenario is measured from: the far edge of the zone. */
export function entryReference(direction: Direction, zone: { from: number; to: number }): number {
  return direction === 'long' ? zone.to : zone.from;
}

/** Minimum R multiples a published scenario must offer. */
const MIN_R_TARGET_1 = 1.5;
const MIN_R_TARGET_2 = 3.0;

/**
 * Finalizes scenario targets.
 *
 * Geometric targets (measured moves, ATR extensions, next levels) carry real
 * information, but on their own they routinely produce nonsense: a structural
 * stop placed at the last swing can sit far below the entry, leaving a "target"
 * only 0.2R away — or, when price has already run past the measured move, a
 * target BEHIND the entry and a negative reward-to-risk.
 *
 * This helper enforces what a disciplined trader would require:
 *   1. Every target lies strictly beyond the entry in the trade's direction.
 *   2. Target 1 is at least 1.5R and target 2 at least 3R from the entry.
 *   3. A geometric target further out than the R floor is kept, and its method
 *      is preserved, because it is the more meaningful level.
 *
 * Returns targets sorted nearest-first.
 */
export function finalizeTargets(
  direction: Direction,
  entryZone: { from: number; to: number },
  invalidation: number,
  geometricTargets: { price: number; method: string }[],
  tickSize: number,
): { price: number; method: string }[] {
  const entry = entryReference(direction, entryZone);
  const risk = Math.abs(entry - invalidation);
  if (risk <= 0) return [];

  const isLong = direction === 'long';
  const project = (r: number) => (isLong ? entry + risk * r : entry - risk * r);

  // Keep only geometric targets that are genuinely ahead of the entry.
  const ahead = geometricTargets
    .filter((t) => Number.isFinite(t.price) && (isLong ? t.price > entry : t.price < entry))
    .sort((a, b) => (isLong ? a.price - b.price : b.price - a.price));

  // Tick rounding must never pull a projected target back below its R floor,
  // so floors round AWAY from the entry. A floor that rounds down is not a floor.
  const roundOutward = (price: number) => {
    if (tickSize <= 0 || !Number.isFinite(price)) return price;
    const decimals = Math.max(0, Math.min(12, Math.ceil(-Math.log10(tickSize))));
    const steps = isLong ? Math.ceil(price / tickSize) : Math.floor(price / tickSize);
    return Number((steps * tickSize).toFixed(decimals));
  };

  const floors = [
    { r: MIN_R_TARGET_1, price: project(MIN_R_TARGET_1) },
    { r: MIN_R_TARGET_2, price: project(MIN_R_TARGET_2) },
  ];

  const out: { price: number; method: string }[] = [];

  for (let i = 0; i < floors.length; i++) {
    const floor = floors[i]!;
    const geometric = ahead[i];

    // Prefer the geometric level when it already clears the R floor.
    const useGeometric =
      geometric !== undefined && (isLong ? geometric.price >= floor.price : geometric.price <= floor.price);

    if (useGeometric) {
      out.push({ price: roundToTick(geometric.price, tickSize), method: geometric.method });
    } else {
      const note = geometric
        ? `${geometric.method}, extended to the ${floor.r}R floor`
        : `${floor.r}R projection from the invalidation level`;
      out.push({ price: roundOutward(floor.price), method: note });
    }
  }

  // Guarantee strict ordering after tick rounding.
  const first = out[0]!;
  const second = out[1]!;
  if (isLong ? second.price <= first.price : second.price >= first.price) {
    second.price = roundOutward(project(MIN_R_TARGET_2));
  }

  return out;
}
