/**
 * Depth-aware sizing: the difference between an edge that exists and an edge
 * you can actually take.
 *
 * A 4¢ mispricing on the top of a book holding $6 of size is not a 4% edge, and
 * reporting it as one is the single most common way a paper strategy looks
 * profitable and a real one does not. Every candidate this system produces
 * carries a size curve: net expected value as a function of notional, walked
 * across real book levels and charged real fees.
 *
 * Pure functions throughout — the book is an input, the clock is not consulted.
 */

import { feePerShare, type FeeModel } from './fees';
import type { BookLevel } from '@/lib/polymarket/types';

export interface Fill {
  shares: number;
  /** Volume-weighted average price actually paid. */
  avgPrice: number;
  /** Total dollars spent on shares, excluding fees. */
  notional: number;
  /** How many book levels were consumed. */
  levelsConsumed: number;
  /** True when the book ran out before the requested size was filled. */
  exhausted: boolean;
}

/**
 * Walk the ask side buying up to `targetNotional` dollars.
 *
 * Levels must be sorted best-first, which `normalizeOrderBook` guarantees.
 */
export function walkAsks(asks: BookLevel[], targetNotional: number): Fill {
  let remaining = targetNotional;
  let shares = 0;
  let spent = 0;
  let levelsConsumed = 0;

  for (const level of asks) {
    if (remaining <= 0) break;
    const levelNotional = level.price * level.size;
    const take = Math.min(levelNotional, remaining);
    if (take <= 0) continue;
    shares += take / level.price;
    spent += take;
    remaining -= take;
    levelsConsumed += 1;
  }

  return {
    shares,
    avgPrice: shares > 0 ? spent / shares : Number.NaN,
    notional: spent,
    levelsConsumed,
    exhausted: remaining > 1e-9,
  };
}

/** Total dollars of liquidity resting on one side of the book. */
export function sideDepthUsd(levels: BookLevel[]): number {
  return levels.reduce((acc, l) => acc + l.price * l.size, 0);
}

export interface EdgeAtSize {
  notional: number;
  fill: Fill;
  /** Dollars of expected profit after fees. */
  expectedValue: number;
  /** Expected profit as a fraction of notional deployed. */
  expectedReturn: number;
  feesPaid: number;
}

/**
 * Expected value of buying `notional` dollars of a YES token believed to be
 * worth `fairProbability`.
 *
 * Each share pays $1 with probability `fairProbability` and $0 otherwise, so
 * per share the expectation is `fair − avgPrice − fee(avgPrice)`.
 */
export function edgeAtSize(
  asks: BookLevel[],
  fairProbability: number,
  notional: number,
  feeModel: FeeModel,
): EdgeAtSize {
  const fill = walkAsks(asks, notional);
  if (!(fill.shares > 0) || !Number.isFinite(fill.avgPrice)) {
    return {
      notional,
      fill,
      expectedValue: 0,
      expectedReturn: 0,
      feesPaid: 0,
    };
  }

  const feePer = feePerShare(fill.avgPrice, feeModel);
  const feesPaid = feePer * fill.shares;
  const expectedValue = fill.shares * (fairProbability - fill.avgPrice - feePer);

  return {
    notional: fill.notional,
    fill,
    expectedValue,
    expectedReturn: fill.notional > 0 ? expectedValue / fill.notional : 0,
    feesPaid,
  };
}

/**
 * The size curve: expected value sampled across increasing notionals.
 *
 * Monotonically non-increasing in expected *return* by construction — each
 * additional dollar buys at a price at least as bad as the last. The curve is
 * what the UI shows instead of a single headline number.
 */
export function sizeCurve(
  asks: BookLevel[],
  fairProbability: number,
  feeModel: FeeModel,
  maxNotional: number,
  steps = 12,
): EdgeAtSize[] {
  const out: EdgeAtSize[] = [];
  for (let i = 1; i <= steps; i++) {
    const notional = (maxNotional * i) / steps;
    out.push(edgeAtSize(asks, fairProbability, notional, feeModel));
  }
  return out;
}

/**
 * The largest notional at which the position still has positive expected value
 * after fees, capped by `maxNotional` and by the book's actual depth.
 *
 * Bisection over a monotone function; 40 iterations resolves to well under a
 * cent on any capital size this project contemplates.
 */
export function maxProfitableNotional(
  asks: BookLevel[],
  fairProbability: number,
  feeModel: FeeModel,
  maxNotional: number,
): number {
  const ceiling = Math.min(maxNotional, sideDepthUsd(asks));
  if (ceiling <= 0) return 0;
  if (edgeAtSize(asks, fairProbability, ceiling, feeModel).expectedValue > 0) return ceiling;
  if (edgeAtSize(asks, fairProbability, ceiling / 1000, feeModel).expectedValue <= 0) return 0;

  let low = 0;
  let high = ceiling;
  for (let i = 0; i < 40; i++) {
    const mid = (low + high) / 2;
    if (edgeAtSize(asks, fairProbability, mid, feeModel).expectedValue > 0) low = mid;
    else high = mid;
  }
  return low;
}

/**
 * Kelly fraction for a binary contract bought at `price` with fair probability
 * `fair`.
 *
 *   staking `price` per share to win `1 − price`  ⇒  b = (1 − price)/price
 *   f* = (p·b − q)/b  =  (p − price)/(1 − price)
 *
 * Returns 0 when the bet is not favourable. Full Kelly is far too aggressive
 * for probabilities this uncertain, so callers apply a fractional multiplier.
 */
export function kellyFraction(fair: number, price: number): number {
  if (!(price > 0) || !(price < 1)) return 0;
  const f = (fair - price) / (1 - price);
  return f > 0 ? f : 0;
}

export interface SizingRecommendation {
  /** Recommended notional in dollars, after every cap. */
  notional: number;
  kellyFractionRaw: number;
  kellyFractionApplied: number;
  maxProfitable: number;
  /** The binding constraint, named for the UI. */
  limitedBy: 'kelly' | 'depth' | 'bankroll-cap' | 'no-edge';
  detail: string;
}

export interface SizingLimits {
  bankrollUsd: number;
  /** Fraction of full Kelly to actually use. Quarter Kelly by default. */
  kellyMultiplier: number;
  /** Hard cap on any single position as a fraction of bankroll. */
  maxPositionFraction: number;
}

export const DEFAULT_SIZING_LIMITS: SizingLimits = {
  bankrollUsd: 1000,
  kellyMultiplier: 0.25,
  maxPositionFraction: 0.05,
};

export function recommendSize(
  asks: BookLevel[],
  fairProbability: number,
  feeModel: FeeModel,
  limits: SizingLimits = DEFAULT_SIZING_LIMITS,
): SizingRecommendation {
  const best = asks[0];
  if (!best) {
    return {
      notional: 0,
      kellyFractionRaw: 0,
      kellyFractionApplied: 0,
      maxProfitable: 0,
      limitedBy: 'no-edge',
      detail: 'No resting asks — nothing to buy at any size.',
    };
  }

  const raw = kellyFraction(fairProbability, best.price);
  const applied = raw * limits.kellyMultiplier;
  const kellyNotional = applied * limits.bankrollUsd;
  const hardCap = limits.maxPositionFraction * limits.bankrollUsd;
  const profitable = maxProfitableNotional(asks, fairProbability, feeModel, hardCap);

  if (raw <= 0 || profitable <= 0) {
    return {
      notional: 0,
      kellyFractionRaw: raw,
      kellyFractionApplied: applied,
      maxProfitable: profitable,
      limitedBy: 'no-edge',
      detail:
        `No positive edge after fees at the best ask of ${best.price}. ` +
        `Fair estimate ${fairProbability.toFixed(4)}.`,
    };
  }

  const candidates: Array<{ value: number; label: SizingRecommendation['limitedBy'] }> = [
    { value: kellyNotional, label: 'kelly' },
    { value: profitable, label: 'depth' },
    { value: hardCap, label: 'bankroll-cap' },
  ];
  candidates.sort((a, b) => a.value - b.value);
  const binding = candidates[0]!;

  return {
    notional: binding.value,
    kellyFractionRaw: raw,
    kellyFractionApplied: applied,
    maxProfitable: profitable,
    limitedBy: binding.label,
    detail:
      `Kelly suggests $${kellyNotional.toFixed(2)} (${(applied * 100).toFixed(2)}% of bankroll at ` +
      `${limits.kellyMultiplier}× Kelly); the book supports $${profitable.toFixed(2)} profitably; ` +
      `the per-position cap is $${hardCap.toFixed(2)}. Binding constraint: ${binding.label}.`,
  };
}
