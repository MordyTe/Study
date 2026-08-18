/**
 * Calibration and the paper ledger — the module that answers the only question
 * this project exists to ask:
 *
 *   Do the system's probabilities beat the market's, out-of-sample, by enough
 *   to survive fees and spread at small size?
 *
 * The design has one organizing principle: the market's own price is scored by
 * exactly the same rule as the system's estimate. The Brier score of
 * `fairProbability` means nothing in isolation; it means everything next to the
 * Brier score of `marketPrice` over the same markets. If ours is not lower,
 * there is no edge, whatever the paper P&L happens to show over a small sample.
 *
 * Everything here is a pure function of stored candidates and resolutions, so
 * the report is reproducible from the store alone.
 */

import type { Candidate } from '@/lib/engine/assess';

export interface ResolutionRecord {
  marketId: string;
  resolvedYes: boolean;
  resolvedAt: number;
}

/**
 * Below this many resolved estimates, no headline Brier comparison should be
 * believed — the sampling error on a Brier difference is larger than any edge
 * this system could plausibly have. The numbers are still computed and shown,
 * labelled as insufficient.
 */
export const MIN_CALIBRATION_SAMPLE = 50;

export interface ReliabilityBucket {
  lo: number;
  hi: number;
  count: number;
  /** Mean of the system's forecasts in this bucket. */
  meanForecast: number;
  /** Fraction of those markets that actually resolved YES. */
  frequency: number;
}

export interface PaperFill {
  marketId: string;
  question: string;
  notional: number;
  shares: number;
  avgPrice: number;
  feesPaid: number;
  resolvedYes: boolean;
  /** Dollars: payout − cost − fees. */
  pnl: number;
}

export interface CalibrationReport {
  /** Resolved markets with a system estimate — the scoring sample. */
  n: number;
  brierOurs: number | null;
  brierMarket: number | null;
  /** ours − market. Negative means the system is better calibrated. */
  brierEdge: number | null;
  buckets: ReliabilityBucket[];
  fills: PaperFill[];
  totalPnl: number;
  totalStaked: number;
  minSampleMet: boolean;
  detail: string;
}

/**
 * One scored pair per market: the LATEST estimate made before resolution.
 * Re-estimates of the same market supersede rather than double-count — scoring
 * every intermediate estimate would let one market dominate the sample.
 */
function latestPerMarket(candidates: Candidate[]): Map<string, Candidate> {
  const byMarket = new Map<string, Candidate>();
  for (const c of candidates) {
    if (c.fairProbability === null) continue;
    const existing = byMarket.get(c.marketId);
    if (!existing || c.decisionAt > existing.decisionAt) byMarket.set(c.marketId, c);
  }
  return byMarket;
}

function brier(pairs: Array<{ p: number; y: number }>): number | null {
  if (pairs.length === 0) return null;
  return pairs.reduce((acc, { p, y }) => acc + (p - y) ** 2, 0) / pairs.length;
}

/** The simulated fill for one ACTIONABLE candidate, taken from its own curve. */
function paperFill(candidate: Candidate, resolvedYes: boolean): PaperFill | null {
  const sizing = candidate.sizing;
  if (candidate.status !== 'ACTIONABLE' || !sizing || sizing.notional <= 0) return null;

  // The curve was walked against the real book at decision time; the point at
  // (or just past) the recommended notional is the fill we would have taken.
  const point =
    candidate.curve.find((c) => c.notional >= sizing.notional - 1e-9) ??
    candidate.curve[candidate.curve.length - 1];
  if (!point || !(point.fill.shares > 0)) return null;

  const payout = resolvedYes ? point.fill.shares : 0;
  return {
    marketId: candidate.marketId,
    question: candidate.question,
    notional: point.fill.notional,
    shares: point.fill.shares,
    avgPrice: point.fill.avgPrice,
    feesPaid: point.feesPaid,
    resolvedYes,
    pnl: payout - point.fill.notional - point.feesPaid,
  };
}

export function computeCalibration(
  candidates: Candidate[],
  resolutions: ResolutionRecord[],
): CalibrationReport {
  const resolutionByMarket = new Map(resolutions.map((r) => [r.marketId, r]));
  const scored: Array<{ candidate: Candidate; resolvedYes: boolean }> = [];

  for (const candidate of latestPerMarket(candidates).values()) {
    const resolution = resolutionByMarket.get(candidate.marketId);
    if (!resolution) continue;
    // No-lookahead at the ledger level too: an estimate made after the market
    // resolved is not a forecast and must not be scored as one.
    if (candidate.decisionAt >= resolution.resolvedAt) continue;
    scored.push({ candidate, resolvedYes: resolution.resolvedYes });
  }

  const oursPairs = scored.map(({ candidate, resolvedYes }) => ({
    p: candidate.fairProbability!,
    y: resolvedYes ? 1 : 0,
  }));
  const marketPairs = scored
    .filter(({ candidate }) => candidate.marketPrice !== null)
    .map(({ candidate, resolvedYes }) => ({
      p: candidate.marketPrice!,
      y: resolvedYes ? 1 : 0,
    }));

  const brierOurs = brier(oursPairs);
  const brierMarket = brier(marketPairs);

  const buckets: ReliabilityBucket[] = [];
  for (let b = 0; b < 10; b++) {
    const lo = b / 10;
    const hi = (b + 1) / 10;
    const inBucket = scored.filter(({ candidate }) => {
      const p = candidate.fairProbability!;
      return p >= lo && (b === 9 ? p <= hi : p < hi);
    });
    if (inBucket.length === 0) continue;
    buckets.push({
      lo,
      hi,
      count: inBucket.length,
      meanForecast:
        inBucket.reduce((acc, { candidate }) => acc + candidate.fairProbability!, 0) /
        inBucket.length,
      frequency: inBucket.filter(({ resolvedYes }) => resolvedYes).length / inBucket.length,
    });
  }

  const fills = scored
    .map(({ candidate, resolvedYes }) => paperFill(candidate, resolvedYes))
    .filter((f): f is PaperFill => f !== null);

  const totalPnl = fills.reduce((acc, f) => acc + f.pnl, 0);
  const totalStaked = fills.reduce((acc, f) => acc + f.notional + f.feesPaid, 0);
  const minSampleMet = scored.length >= MIN_CALIBRATION_SAMPLE;

  const detail = !minSampleMet
    ? `${scored.length} resolved estimate(s) against a minimum of ${MIN_CALIBRATION_SAMPLE}. ` +
      'Nothing below should be treated as evidence yet.'
    : brierOurs !== null && brierMarket !== null
      ? brierOurs < brierMarket
        ? `The system's Brier (${brierOurs.toFixed(4)}) beats the market's (${brierMarket.toFixed(4)}) over ${scored.length} markets.`
        : `The market's Brier (${brierMarket.toFixed(4)}) beats the system's (${brierOurs.toFixed(4)}) over ${scored.length} markets — no edge demonstrated.`
      : 'Insufficient priced markets for a comparison.';

  return {
    n: scored.length,
    brierOurs,
    brierMarket,
    brierEdge: brierOurs !== null && brierMarket !== null ? brierOurs - brierMarket : null,
    buckets,
    fills,
    totalPnl,
    totalStaked,
    minSampleMet,
    detail,
  };
}
