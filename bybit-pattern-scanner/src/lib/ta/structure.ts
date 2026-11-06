/**
 * Market structure primitives: ATR-adaptive swing pivots, horizontal level
 * clustering, and trendline fitting. Shared by every pattern detector so all
 * detectors reason about the same geometry.
 */

import type { Candle } from '@/lib/bybit/types';
import { atr } from './indicators';

export type PivotKind = 'high' | 'low';

export interface Pivot {
  index: number;
  time: number;
  price: number;
  kind: PivotKind;
  /** How far the pivot stands out from its neighbourhood, in ATR units. */
  prominenceAtr: number;
}

export interface PivotOptions {
  /** Bars required on each side for confirmation. */
  window?: number;
  /** Minimum prominence in ATR units to reject noise. */
  minProminenceAtr?: number;
  atrPeriod?: number;
}

/**
 * Detects swing highs/lows using a symmetric window plus an ATR-relative
 * prominence filter. Only bars with `window` confirmed bars to the right are
 * returned, so the output contains no lookahead when used at the last index.
 *
 * Prominence is measured as the depth of the swing — how far the pivot stands
 * above (or below) the deepest retracement inside its window — NOT as the gap
 * to the single nearest neighbour. In a smooth trend a genuine swing high
 * exceeds its immediate neighbour by a rounding error, so a nearest-neighbour
 * measure rejects almost every real pivot.
 */
export function findPivots(candles: Candle[], opts: PivotOptions = {}): Pivot[] {
  const window = opts.window ?? 3;
  const minProminence = opts.minProminenceAtr ?? 0.5;
  const atrSeries = atr(candles, opts.atrPeriod ?? 14);
  const pivots: Pivot[] = [];

  for (let i = window; i < candles.length - window; i++) {
    const c = candles[i]!;
    const a = atrSeries[i] ?? null;
    if (a === null || a <= 0) continue;

    let isHigh = true;
    let isLow = true;
    let windowLow = Infinity;
    let windowHigh = -Infinity;

    for (let j = i - window; j <= i + window; j++) {
      const n = candles[j]!;
      if (j !== i) {
        // Ties resolve to the earlier bar so a flat top yields one pivot, not many.
        if (n.high >= c.high) isHigh = false;
        if (n.low <= c.low) isLow = false;
      }
      windowLow = Math.min(windowLow, n.low);
      windowHigh = Math.max(windowHigh, n.high);
    }

    if (isHigh) {
      // Swing depth: distance from this high down to the window's deepest low.
      const prominence = (c.high - windowLow) / a;
      if (prominence >= minProminence) {
        pivots.push({ index: i, time: c.time, price: c.high, kind: 'high', prominenceAtr: prominence });
      }
    } else if (isLow) {
      const prominence = (windowHigh - c.low) / a;
      if (prominence >= minProminence) {
        pivots.push({ index: i, time: c.time, price: c.low, kind: 'low', prominenceAtr: prominence });
      }
    }
  }

  return pivots;
}

export interface Level {
  price: number;
  /** Number of pivots that formed this level. */
  touches: number;
  kind: PivotKind;
  firstTime: number;
  lastTime: number;
  /** Quality 0..1 combining touch count, recency, and tightness. */
  strength: number;
}

/**
 * Clusters pivots into horizontal support/resistance levels using an
 * ATR-relative tolerance, so a $2 wiggle on BTC and on a micro-cap are treated
 * with the same statistical meaning.
 */
export function clusterLevels(
  pivots: Pivot[],
  atrValue: number,
  toleranceAtr = 0.6,
  now = Date.now(),
): Level[] {
  if (pivots.length === 0 || atrValue <= 0) return [];
  const tolerance = atrValue * toleranceAtr;
  const sorted = [...pivots].sort((a, b) => a.price - b.price);

  const groups: Pivot[][] = [];
  let current: Pivot[] = [sorted[0]!];

  for (let i = 1; i < sorted.length; i++) {
    const p = sorted[i]!;
    const ref = current[current.length - 1]!;
    if (Math.abs(p.price - ref.price) <= tolerance) current.push(p);
    else {
      groups.push(current);
      current = [p];
    }
  }
  groups.push(current);

  const levels: Level[] = groups
    .filter((g) => g.length >= 2)
    .map((g) => {
      const price = g.reduce((a, p) => a + p.price, 0) / g.length;
      const times = g.map((p) => p.time);
      const firstTime = Math.min(...times);
      const lastTime = Math.max(...times);
      const highs = g.filter((p) => p.kind === 'high').length;
      const kind: PivotKind = highs >= g.length / 2 ? 'high' : 'low';

      const spread = Math.max(...g.map((p) => p.price)) - Math.min(...g.map((p) => p.price));
      const tightness = tolerance > 0 ? Math.max(0, 1 - spread / tolerance) : 0;
      const touchScore = Math.min(1, (g.length - 1) / 3);
      const ageDays = (now - lastTime) / 86_400_000;
      const recency = Math.max(0, 1 - ageDays / 60);

      return {
        price,
        touches: g.length,
        kind,
        firstTime,
        lastTime,
        strength: Math.max(0, Math.min(1, touchScore * 0.5 + tightness * 0.2 + recency * 0.3)),
      };
    })
    .sort((a, b) => b.strength - a.strength);

  return levels;
}

export interface TrendLine {
  /** price = slope * index + intercept */
  slope: number;
  intercept: number;
  /** R² of the fit, 0..1. */
  fit: number;
  points: { index: number; time: number; price: number }[];
  startIndex: number;
  endIndex: number;
}

/** Least-squares line through pivot points, with R² so weak fits can be rejected. */
export function fitTrendLine(points: { index: number; time: number; price: number }[]): TrendLine | null {
  if (points.length < 2) return null;
  const n = points.length;
  const meanX = points.reduce((a, p) => a + p.index, 0) / n;
  const meanY = points.reduce((a, p) => a + p.price, 0) / n;

  let num = 0;
  let den = 0;
  for (const p of points) {
    num += (p.index - meanX) * (p.price - meanY);
    den += (p.index - meanX) ** 2;
  }
  if (den === 0) return null;

  const slope = num / den;
  const intercept = meanY - slope * meanX;

  let ssTot = 0;
  let ssRes = 0;
  for (const p of points) {
    const predicted = slope * p.index + intercept;
    ssRes += (p.price - predicted) ** 2;
    ssTot += (p.price - meanY) ** 2;
  }
  const fit = ssTot === 0 ? 1 : Math.max(0, 1 - ssRes / ssTot);

  return {
    slope,
    intercept,
    fit,
    points,
    startIndex: Math.min(...points.map((p) => p.index)),
    endIndex: Math.max(...points.map((p) => p.index)),
  };
}

export function trendLineValueAt(line: TrendLine, index: number): number {
  return line.slope * index + line.intercept;
}

export type StructureState = 'uptrend' | 'downtrend' | 'range';

export interface MarketStructure {
  state: StructureState;
  /** Break of structure: price took out the prior swing in the trend direction. */
  breakOfStructure: boolean;
  /** Change of character: first counter-trend structural break. */
  changeOfCharacter: boolean;
  lastHigh: Pivot | null;
  lastLow: Pivot | null;
  priorHigh: Pivot | null;
  priorLow: Pivot | null;
  /** 0..1 confidence in the classification. */
  confidence: number;
}

/**
 * Classifies structure from the last four alternating pivots (HH/HL vs LH/LL)
 * and flags BOS/CHoCH against the most recent closed candle.
 */
export function analyzeStructure(candles: Candle[], pivots: Pivot[]): MarketStructure {
  const highs = pivots.filter((p) => p.kind === 'high').slice(-3);
  const lows = pivots.filter((p) => p.kind === 'low').slice(-3);

  const lastHigh = highs[highs.length - 1] ?? null;
  const priorHigh = highs[highs.length - 2] ?? null;
  const lastLow = lows[lows.length - 1] ?? null;
  const priorLow = lows[lows.length - 2] ?? null;

  let state: StructureState = 'range';
  let confidence = 0.3;

  if (lastHigh && priorHigh && lastLow && priorLow) {
    const higherHighs = lastHigh.price > priorHigh.price;
    const higherLows = lastLow.price > priorLow.price;
    const lowerHighs = lastHigh.price < priorHigh.price;
    const lowerLows = lastLow.price < priorLow.price;

    if (higherHighs && higherLows) {
      state = 'uptrend';
      confidence = 0.85;
    } else if (lowerHighs && lowerLows) {
      state = 'downtrend';
      confidence = 0.85;
    } else if (higherHighs || higherLows) {
      state = 'range';
      confidence = 0.5;
    }
  }

  const last = candles[candles.length - 1];
  let breakOfStructure = false;
  let changeOfCharacter = false;

  if (last) {
    if (state === 'uptrend' && lastHigh && last.close > lastHigh.price) breakOfStructure = true;
    if (state === 'downtrend' && lastLow && last.close < lastLow.price) breakOfStructure = true;
    if (state === 'uptrend' && lastLow && last.close < lastLow.price) changeOfCharacter = true;
    if (state === 'downtrend' && lastHigh && last.close > lastHigh.price) changeOfCharacter = true;
  }

  return { state, breakOfStructure, changeOfCharacter, lastHigh, lastLow, priorHigh, priorLow, confidence };
}
