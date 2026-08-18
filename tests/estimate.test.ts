/**
 * Golden tests for the deterministic core.
 *
 * Every expected value here was computed by hand. If the arithmetic in these
 * modules is wrong, nothing built on top of it can be right, so this file runs
 * before any agent exists and is the first thing to check when a result looks
 * surprising.
 */

import { describe, expect, it } from 'vitest';

import {
  MIN_RESIDUALS,
  buildResidualDistribution,
  quantile,
  residualCdf,
  standardNormalCdf,
  type ForecastObservation,
} from '@/lib/estimate/residuals';
import {
  MODEL_RISK_FLOOR,
  effectiveThreshold,
  thresholdProbability,
  type ThresholdSpec,
} from '@/lib/estimate/threshold';
import {
  DEFAULT_FEE_COEFFICIENT,
  FEE_COEFFICIENTS,
  breakEvenEdgePerShare,
  feePerShare,
  resolveFeeModel,
} from '@/lib/estimate/fees';
import {
  DEFAULT_SIZING_LIMITS,
  edgeAtSize,
  kellyFraction,
  maxProfitableNotional,
  recommendSize,
  sideDepthUsd,
  sizeCurve,
  walkAsks,
} from '@/lib/estimate/sizing';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

/**
 * `count` observations whose residuals are symmetric about zero and span
 * ±`spread`. Deterministic — no RNG, so the suite is reproducible.
 */
function symmetricObservations(count: number, spread: number, horizonDays = 5): ForecastObservation[] {
  const out: ForecastObservation[] = [];
  for (let i = 0; i < count; i++) {
    // Maps i onto [-1, 1] symmetrically.
    const t = count === 1 ? 0 : (2 * i) / (count - 1) - 1;
    out.push({
      seriesId: 'TEST',
      releaseDate: `2026-01-${String((i % 28) + 1).padStart(2, '0')}`,
      forecast: 0,
      actual: t * spread,
      horizonDays,
      source: 'test-source',
    });
  }
  return out;
}

const dist24 = buildResidualDistribution(symmetricObservations(24, 0.5), {
  targetHorizonDays: 5,
})!;

// ---------------------------------------------------------------------------
// Residual distributions
// ---------------------------------------------------------------------------

describe('buildResidualDistribution', () => {
  it('refuses a sample below the minimum rather than guessing', () => {
    const observations = symmetricObservations(MIN_RESIDUALS - 1, 0.5);
    expect(buildResidualDistribution(observations, { targetHorizonDays: 5 })).toBeNull();
  });

  it('accepts a sample at exactly the minimum', () => {
    const observations = symmetricObservations(MIN_RESIDUALS, 0.5);
    expect(buildResidualDistribution(observations, { targetHorizonDays: 5 })).not.toBeNull();
  });

  it('filters to observations at a comparable horizon', () => {
    const near = symmetricObservations(20, 0.5, 5);
    const far = symmetricObservations(20, 5.0, 90);
    const dist = buildResidualDistribution([...near, ...far], {
      targetHorizonDays: 5,
      horizonToleranceDays: 7,
    });
    expect(dist).not.toBeNull();
    expect(dist!.n).toBe(20);
    // The far-horizon observations had a 10x wider spread; if they had leaked
    // in, sd would be far larger.
    expect(dist!.sd).toBeLessThan(1);
    expect(dist!.horizonRange).toEqual({ minDays: 5, maxDays: 5 });
  });

  it('returns null when nothing is at a comparable horizon', () => {
    const far = symmetricObservations(40, 0.5, 90);
    expect(
      buildResidualDistribution(far, { targetHorizonDays: 5, horizonToleranceDays: 7 }),
    ).toBeNull();
  });

  it('does not bias-correct a small sample, and does correct a large one', () => {
    const small = buildResidualDistribution(symmetricObservations(20, 0.5), {
      targetHorizonDays: 5,
    })!;
    expect(small.biasCorrected).toBe(false);

    const large = buildResidualDistribution(symmetricObservations(30, 0.5), {
      targetHorizonDays: 5,
    })!;
    expect(large.biasCorrected).toBe(true);
  });

  it('measures a systematic lean as bias', () => {
    // Every actual overshoots its forecast by exactly 0.2.
    const observations = symmetricObservations(30, 0.5).map((o) => ({
      ...o,
      actual: o.actual + 0.2,
    }));
    const dist = buildResidualDistribution(observations, { targetHorizonDays: 5 })!;
    expect(dist.bias).toBeCloseTo(0.2, 6);
    // After correction the residuals are centred again.
    expect(quantile(dist.residuals, 0.5)).toBeCloseTo(0, 6);
  });

  it('survives a degenerate sample where every residual is identical', () => {
    const observations = symmetricObservations(20, 0).map((o) => ({ ...o, actual: 0 }));
    const dist = buildResidualDistribution(observations, { targetHorizonDays: 5 })!;
    expect(dist.bandwidth).toBeGreaterThan(0);
    expect(Number.isFinite(residualCdf(dist, 0))).toBe(true);
  });
});

describe('residualCdf', () => {
  it('is 0.5 at the centre of a symmetric distribution', () => {
    expect(residualCdf(dist24, 0)).toBeCloseTo(0.5, 6);
  });

  it('is monotonically increasing', () => {
    let previous = -Infinity;
    for (let x = -2; x <= 2; x += 0.1) {
      const value = residualCdf(dist24, x);
      expect(value).toBeGreaterThanOrEqual(previous);
      previous = value;
    }
  });

  it('stays strictly interior across the range the kernel meaningfully covers', () => {
    // Residuals span ±0.5 with a bandwidth near 0.14, so ±1.0 is several
    // bandwidths beyond the observed data and still has real kernel mass.
    for (const x of [-1.0, -0.6, 0, 0.6, 1.0]) {
      const value = residualCdf(dist24, x);
      expect(value).toBeGreaterThan(0);
      expect(value).toBeLessThan(1);
    }
  });

  it('is permitted to underflow to 0 absurdly far out — that is the kernel, not the answer', () => {
    // Documenting the real numerical behaviour rather than pretending otherwise.
    // The guarantee that no *reported* probability is 0 or 1 lives one layer up,
    // in thresholdProbability's model-risk floor, which is where it belongs:
    // it is a claim about model misspecification, not about arithmetic.
    expect(residualCdf(dist24, -1000)).toBe(0);
    expect(residualCdf(dist24, 1000)).toBe(1);
  });
});

describe('standardNormalCdf', () => {
  it('matches known values of the standard normal', () => {
    expect(standardNormalCdf(0)).toBeCloseTo(0.5, 6);
    expect(standardNormalCdf(1)).toBeCloseTo(0.8413447, 5);
    expect(standardNormalCdf(-1)).toBeCloseTo(0.1586553, 5);
    expect(standardNormalCdf(1.96)).toBeCloseTo(0.9750021, 5);
  });
});

describe('quantile', () => {
  it('interpolates between order statistics', () => {
    const sorted = [0, 1, 2, 3, 4];
    expect(quantile(sorted, 0)).toBe(0);
    expect(quantile(sorted, 0.5)).toBe(2);
    expect(quantile(sorted, 1)).toBe(4);
    expect(quantile(sorted, 0.25)).toBe(1);
    expect(quantile(sorted, 0.125)).toBeCloseTo(0.5, 10);
  });
});

// ---------------------------------------------------------------------------
// The rounding conversion — the highest-value arithmetic in the system
// ---------------------------------------------------------------------------

describe('effectiveThreshold', () => {
  const oneDp = { decimals: 1, mode: 'half-up' as const };

  it('converts "reported >= 3.0" to an underlying cutoff of 2.95', () => {
    const result = effectiveThreshold({ threshold: 3.0, comparator: 'gte', rounding: oneDp });
    expect(result.value).toBeCloseTo(2.95, 10);
    expect(result.isUpperTail).toBe(true);
  });

  it('converts "reported > 3.0" to an underlying cutoff of 3.05', () => {
    const result = effectiveThreshold({ threshold: 3.0, comparator: 'gt', rounding: oneDp });
    expect(result.value).toBeCloseTo(3.05, 10);
    expect(result.isUpperTail).toBe(true);
  });

  it('converts "reported <= 3.0" to underlying < 3.05', () => {
    const result = effectiveThreshold({ threshold: 3.0, comparator: 'lte', rounding: oneDp });
    expect(result.value).toBeCloseTo(3.05, 10);
    expect(result.isUpperTail).toBe(false);
  });

  it('converts "reported < 3.0" to underlying < 2.95', () => {
    const result = effectiveThreshold({ threshold: 3.0, comparator: 'lt', rounding: oneDp });
    expect(result.value).toBeCloseTo(2.95, 10);
    expect(result.isUpperTail).toBe(false);
  });

  it('scales the half-step with the reported precision', () => {
    const twoDp = { decimals: 2, mode: 'half-up' as const };
    const result = effectiveThreshold({ threshold: 3.0, comparator: 'gte', rounding: twoDp });
    expect(result.value).toBeCloseTo(2.995, 10);
  });

  it('applies the threshold literally and says so when rounding is unknown', () => {
    const result = effectiveThreshold({ threshold: 3.0, comparator: 'gte', rounding: null });
    expect(result.value).toBe(3.0);
    expect(result.detail).toContain('unknown');
  });

  it('separates gte from gt by exactly one reporting step', () => {
    const gte = effectiveThreshold({ threshold: 3.0, comparator: 'gte', rounding: oneDp });
    const gt = effectiveThreshold({ threshold: 3.0, comparator: 'gt', rounding: oneDp });
    expect(gt.value - gte.value).toBeCloseTo(0.1, 10);
  });
});

describe('thresholdProbability', () => {
  const oneDp = { decimals: 1, mode: 'half-up' as const };

  it('is 0.5 when the point estimate sits exactly on the effective cutoff', () => {
    const spec: ThresholdSpec = { threshold: 3.0, comparator: 'gte', rounding: oneDp };
    const result = thresholdProbability(2.95, spec, dist24);
    expect(result.probability).toBeCloseTo(0.5, 6);
    expect(result.effectiveCutoff).toBeCloseTo(2.95, 10);
  });

  it('rises as the point estimate moves above the cutoff', () => {
    const spec: ThresholdSpec = { threshold: 3.0, comparator: 'gte', rounding: oneDp };
    const low = thresholdProbability(2.8, spec, dist24).probability;
    const mid = thresholdProbability(2.95, spec, dist24).probability;
    const high = thresholdProbability(3.2, spec, dist24).probability;
    expect(low).toBeLessThan(mid);
    expect(mid).toBeLessThan(high);
  });

  it('gives lower-tail comparators the complementary probability', () => {
    const gte: ThresholdSpec = { threshold: 3.0, comparator: 'gte', rounding: oneDp };
    const lt: ThresholdSpec = { threshold: 3.0, comparator: 'lt', rounding: oneDp };
    // Both convert to the same 2.95 cutoff, on opposite sides.
    const up = thresholdProbability(3.0, gte, dist24).probability;
    const down = thresholdProbability(3.0, lt, dist24).probability;
    expect(up + down).toBeCloseTo(1, 6);
  });

  it('produces a materially different answer for gte vs gt — the fine-print edge', () => {
    const gte: ThresholdSpec = { threshold: 3.0, comparator: 'gte', rounding: oneDp };
    const gt: ThresholdSpec = { threshold: 3.0, comparator: 'gt', rounding: oneDp };
    const a = thresholdProbability(3.0, gte, dist24).probability;
    const b = thresholdProbability(3.0, gt, dist24).probability;
    expect(a).toBeGreaterThan(b);
    // With sd ≈ 0.3 the 0.1 shift is worth well over a percentage point.
    expect(a - b).toBeGreaterThan(0.01);
  });

  it('never reports certainty, however distant the threshold', () => {
    const far: ThresholdSpec = { threshold: 500, comparator: 'gte', rounding: oneDp };
    const impossible = thresholdProbability(0, far, dist24);
    expect(impossible.probability).toBe(MODEL_RISK_FLOOR);

    const near: ThresholdSpec = { threshold: -500, comparator: 'gte', rounding: oneDp };
    const certain = thresholdProbability(0, near, dist24);
    expect(certain.probability).toBe(1 - MODEL_RISK_FLOOR);
  });

  it('says out loud when it clamped to the model-risk floor', () => {
    const far: ThresholdSpec = { threshold: 500, comparator: 'gte', rounding: oneDp };
    const result = thresholdProbability(0, far, dist24);
    expect(result.reasoning.join(' ')).toContain('model-risk floor');
  });

  it('leaves ordinary probabilities untouched by the floor', () => {
    const spec: ThresholdSpec = { threshold: 3.0, comparator: 'gte', rounding: oneDp };
    const result = thresholdProbability(2.95, spec, dist24);
    expect(result.probability).toBeGreaterThan(MODEL_RISK_FLOOR);
    expect(result.probability).toBeLessThan(1 - MODEL_RISK_FLOOR);
    expect(result.reasoning.join(' ')).not.toContain('model-risk floor');
  });

  it('explains itself', () => {
    const spec: ThresholdSpec = { threshold: 3.0, comparator: 'gte', rounding: oneDp };
    const result = thresholdProbability(2.95, spec, dist24);
    expect(result.reasoning.length).toBeGreaterThanOrEqual(4);
    expect(result.reasoning.join(' ')).toContain('n=24');
  });
});

// ---------------------------------------------------------------------------
// Fees
// ---------------------------------------------------------------------------

describe('fee model', () => {
  it('peaks at p = 0.5 and vanishes at the extremes', () => {
    const model = resolveFeeModel('politics', null);
    expect(feePerShare(0.5, model)).toBeCloseTo(0.01, 10);
    expect(feePerShare(0.9, model)).toBeCloseTo(0.04 * 0.09, 10);
    expect(feePerShare(0.99, model)).toBeLessThan(feePerShare(0.9, model));
    expect(feePerShare(0, model)).toBe(0);
    expect(feePerShare(1, model)).toBe(0);
  });

  it('reproduces the published per-100-share caps at p = 0.5', () => {
    // cap_per_100 = 100 × coefficient × 0.25 = 25 × coefficient
    expect(100 * feePerShare(0.5, resolveFeeModel('politics', null))).toBeCloseTo(1.0, 10);
    expect(100 * feePerShare(0.5, resolveFeeModel('sports', null))).toBeCloseTo(1.25, 10);
    expect(100 * feePerShare(0.5, resolveFeeModel('crypto', null))).toBeCloseTo(1.75, 10);
  });

  it('charges nothing in the fee-free category', () => {
    const model = resolveFeeModel('geopolitics', null);
    expect(FEE_COEFFICIENTS.geopolitics).toBe(0);
    expect(feePerShare(0.5, model)).toBe(0);
  });

  it('prefers the live venue coefficient over the fallback table', () => {
    const model = resolveFeeModel('politics', 0.09);
    expect(model.coefficient).toBe(0.09);
    expect(model.fromVenue).toBe(true);
  });

  it('falls back conservatively when the category is unknown', () => {
    const model = resolveFeeModel(null, null);
    expect(model.coefficient).toBe(DEFAULT_FEE_COEFFICIENT);
    expect(model.fromVenue).toBe(false);
    // Never silently cheaper than the cheap tier.
    expect(model.coefficient).toBeGreaterThanOrEqual(FEE_COEFFICIENTS.politics);
  });

  it('reports the break-even hurdle a gross edge must clear', () => {
    const model = resolveFeeModel('crypto', null);
    expect(breakEvenEdgePerShare(0.5, model)).toBeCloseTo(0.0175, 10);
  });
});

// ---------------------------------------------------------------------------
// Depth and sizing
// ---------------------------------------------------------------------------

describe('walkAsks', () => {
  const asks = [
    { price: 0.4, size: 100 }, // $40 of depth
    { price: 0.45, size: 100 }, // $45 of depth
    { price: 0.5, size: 100 }, // $50 of depth
  ];

  it('fills entirely at the best level when size permits', () => {
    const fill = walkAsks(asks, 20);
    expect(fill.shares).toBeCloseTo(50, 10);
    expect(fill.avgPrice).toBeCloseTo(0.4, 10);
    expect(fill.levelsConsumed).toBe(1);
    expect(fill.exhausted).toBe(false);
  });

  it('walks into the second level and reports the true average price', () => {
    // $40 buys 100 shares at 0.40; the remaining $20 buys 44.444 at 0.45.
    const fill = walkAsks(asks, 60);
    expect(fill.shares).toBeCloseTo(144.4444444, 6);
    expect(fill.avgPrice).toBeCloseTo(0.4153846, 6);
    expect(fill.levelsConsumed).toBe(2);
    expect(fill.exhausted).toBe(false);
  });

  it('reports exhaustion rather than inventing liquidity', () => {
    const fill = walkAsks(asks, 1000);
    expect(fill.exhausted).toBe(true);
    expect(fill.notional).toBeCloseTo(135, 10);
  });

  it('degrades the average price monotonically with size', () => {
    let previous = 0;
    for (const notional of [10, 20, 40, 60, 100, 135]) {
      const { avgPrice } = walkAsks(asks, notional);
      expect(avgPrice).toBeGreaterThanOrEqual(previous - 1e-12);
      previous = avgPrice;
    }
  });

  it('returns an empty fill against an empty book', () => {
    const fill = walkAsks([], 100);
    expect(fill.shares).toBe(0);
    expect(fill.exhausted).toBe(true);
  });

  it('sums side depth in dollars', () => {
    expect(sideDepthUsd(asks)).toBeCloseTo(135, 10);
  });
});

describe('edgeAtSize', () => {
  const model = resolveFeeModel('politics', null);

  it('computes expected value net of fees', () => {
    // 50 shares at 0.40, fair 0.50. Fee at p=0.4 is 0.04 × 0.4 × 0.6 = 0.0096.
    // EV per share = 0.50 − 0.40 − 0.0096 = 0.0904; × 50 = 4.52.
    const result = edgeAtSize([{ price: 0.4, size: 100 }], 0.5, 20, model);
    expect(result.fill.shares).toBeCloseTo(50, 10);
    expect(result.expectedValue).toBeCloseTo(4.52, 6);
    expect(result.feesPaid).toBeCloseTo(0.48, 6);
    expect(result.expectedReturn).toBeCloseTo(0.226, 6);
  });

  it('turns negative once the fee exceeds the gross edge', () => {
    // Gross edge of half a cent at p=0.5 against a one-cent fee.
    const result = edgeAtSize([{ price: 0.5, size: 1000 }], 0.505, 100, model);
    expect(result.expectedValue).toBeLessThan(0);
  });

  it('handles an empty book without producing a phantom edge', () => {
    const result = edgeAtSize([], 0.9, 100, model);
    expect(result.expectedValue).toBe(0);
    expect(result.expectedReturn).toBe(0);
  });
});

describe('sizeCurve', () => {
  const model = resolveFeeModel('politics', null);
  const asks = [
    { price: 0.4, size: 100 },
    { price: 0.5, size: 100 },
    { price: 0.6, size: 100 },
  ];

  it('is non-increasing in expected return — the honesty property', () => {
    const curve = sizeCurve(asks, 0.7, model, 100, 10);
    for (let i = 1; i < curve.length; i++) {
      expect(curve[i]!.expectedReturn).toBeLessThanOrEqual(curve[i - 1]!.expectedReturn + 1e-12);
    }
  });
});

describe('maxProfitableNotional', () => {
  const model = resolveFeeModel('politics', null);

  it('is bounded by the depth actually resting on the book', () => {
    const asks = [{ price: 0.4, size: 100 }];
    const max = maxProfitableNotional(asks, 0.99, model, 10_000);
    expect(max).toBeCloseTo(40, 6);
  });

  it('stops where the walked AVERAGE price kills the edge, not where the level price does', () => {
    // The distinction this test exists to pin down: what matters is the average
    // price paid across the whole fill, not the price of the level you are
    // currently eating. Buying at 0.60 against a fair value of 0.50 is a losing
    // trade in isolation, yet it remains worth doing while the cheap shares
    // underneath still drag the average below break-even.
    //
    // Book: 100 @ 0.40 ($40), 100 @ 0.50 ($50), 100 @ 0.60 ($60). Fair = 0.50.
    //   at $90  → 200 sh, avg 0.4500, fee 0.04·0.45·0.55 = 0.00990 → EV/sh +0.0401
    //   at $150 → 300 sh, avg 0.5000, fee 0.04·0.25       = 0.01000 → EV/sh −0.0100
    // so the boundary lies between them, well past the second level.
    const asks = [
      { price: 0.4, size: 100 },
      { price: 0.5, size: 100 },
      { price: 0.6, size: 100 },
    ];
    const max = maxProfitableNotional(asks, 0.5, model, 10_000);
    expect(max).toBeGreaterThan(90);
    expect(max).toBeLessThan(sideDepthUsd(asks));

    // And the boundary really is the boundary.
    expect(edgeAtSize(asks, 0.5, max * 0.99, model).expectedValue).toBeGreaterThan(0);
    expect(edgeAtSize(asks, 0.5, max * 1.05, model).expectedValue).toBeLessThan(0);
  });

  it('returns zero when there is no edge at any size', () => {
    const asks = [{ price: 0.6, size: 100 }];
    expect(maxProfitableNotional(asks, 0.5, model, 10_000)).toBe(0);
  });
});

describe('kellyFraction', () => {
  it('matches the closed form (p − c)/(1 − c)', () => {
    expect(kellyFraction(0.6, 0.5)).toBeCloseTo(0.2, 10);
    expect(kellyFraction(0.9, 0.5)).toBeCloseTo(0.8, 10);
    expect(kellyFraction(0.55, 0.5)).toBeCloseTo(0.1, 10);
  });

  it('is zero on an unfavourable or fair bet', () => {
    expect(kellyFraction(0.5, 0.5)).toBe(0);
    expect(kellyFraction(0.4, 0.5)).toBe(0);
  });

  it('refuses degenerate prices instead of dividing by zero', () => {
    expect(kellyFraction(0.9, 0)).toBe(0);
    expect(kellyFraction(0.9, 1)).toBe(0);
  });
});

describe('recommendSize', () => {
  const model = resolveFeeModel('politics', null);

  it('names the binding constraint', () => {
    // Deep book, modest edge: Kelly should bind before depth or the hard cap.
    const asks = [{ price: 0.5, size: 100_000 }];
    const result = recommendSize(asks, 0.55, model, DEFAULT_SIZING_LIMITS);
    expect(result.kellyFractionRaw).toBeCloseTo(0.1, 10);
    expect(result.kellyFractionApplied).toBeCloseTo(0.025, 10);
    expect(result.limitedBy).toBe('kelly');
    expect(result.notional).toBeCloseTo(25, 6);
  });

  it('is limited by depth on a thin book — the case that matters most', () => {
    // A huge edge, but only $4 of it exists.
    const asks = [{ price: 0.2, size: 20 }];
    const result = recommendSize(asks, 0.9, model, DEFAULT_SIZING_LIMITS);
    expect(result.limitedBy).toBe('depth');
    expect(result.notional).toBeCloseTo(4, 6);
  });

  it('recommends nothing when the edge does not survive fees', () => {
    const asks = [{ price: 0.5, size: 1000 }];
    const result = recommendSize(asks, 0.505, model, DEFAULT_SIZING_LIMITS);
    expect(result.notional).toBe(0);
    expect(result.limitedBy).toBe('no-edge');
  });

  it('recommends nothing against an empty book', () => {
    const result = recommendSize([], 0.9, model, DEFAULT_SIZING_LIMITS);
    expect(result.notional).toBe(0);
    expect(result.limitedBy).toBe('no-edge');
  });

  it('never exceeds the per-position bankroll cap', () => {
    const asks = [{ price: 0.05, size: 1_000_000 }];
    const result = recommendSize(asks, 0.95, model, DEFAULT_SIZING_LIMITS);
    const cap = DEFAULT_SIZING_LIMITS.maxPositionFraction * DEFAULT_SIZING_LIMITS.bankrollUsd;
    expect(result.notional).toBeLessThanOrEqual(cap + 1e-9);
  });
});
