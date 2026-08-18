/**
 * Threshold probability: the conversion from "what will the number be" to
 * "will the market resolve YES".
 *
 * The single highest-value piece of arithmetic in the system lives here, and it
 * is not the probability — it is `effectiveThreshold`. Agencies publish rounded
 * figures. BLS reports CPI year-over-year to one decimal. A market asking
 * "above 3.0%" therefore does NOT ask whether the underlying value exceeds 3.0;
 * it asks about the *rounded* value, and the two differ by half a reporting
 * step. Getting that wrong shifts the probability by several points in exactly
 * the thin markets that look most mispriced — a confidently wrong answer, which
 * is the worst failure mode this system has.
 *
 * Everything here is a pure function of its inputs. No clock, no I/O, no model.
 */

import {
  residualCdf,
  type ResidualDistribution,
} from './residuals';

export type Comparator = 'gte' | 'gt' | 'lte' | 'lt';

/**
 * No probability is ever reported outside [MODEL_RISK_FLOOR, 1 − MODEL_RISK_FLOOR].
 *
 * This is not numerical hygiene, it is an honest statement about what the model
 * knows. The kernel CDF is a statement about *forecast error given the model is
 * correct*. It says nothing about the probability that the model itself is
 * wrong: that the resolution criteria were misparsed, that the wrong series was
 * matched, that a methodology change broke the historical residuals, or that a
 * regime shift makes the whole sample unrepresentative. Those failure modes are
 * collectively far more likely than one in ten thousand.
 *
 * A system that reports 0.00% is claiming certainty it has not earned, and it
 * is precisely on the markets furthest from the historical range — the ones
 * that look most mispriced — that it would do so. 0.5% is a deliberately
 * conservative estimate of "the chance everything above this line is wrong".
 */
export const MODEL_RISK_FLOOR = 0.005;

function applyModelRiskFloor(p: number): number {
  if (!Number.isFinite(p)) return 0.5;
  return Math.min(1 - MODEL_RISK_FLOOR, Math.max(MODEL_RISK_FLOOR, p));
}

export interface RoundingConvention {
  /** Decimal places the agency publishes, e.g. 1 for "3.0%". */
  decimals: number;
  /** Standard half-up rounding is the near-universal agency convention. */
  mode: 'half-up';
}

export interface ThresholdSpec {
  /** The number quoted in the market's resolution criteria. */
  threshold: number;
  comparator: Comparator;
  /**
   * How the deciding agency publishes the figure. Null means the resolution
   * criteria did not make it determinable — the threshold is then applied to
   * the underlying value directly and the result is flagged as lower confidence.
   */
  rounding: RoundingConvention | null;
}

export interface EffectiveThreshold {
  /** The cutoff to apply to the *underlying* (unrounded) value. */
  value: number;
  /** True when the event is `underlying ≥ value`, false when `underlying < value`. */
  isUpperTail: boolean;
  /** Plain-English account of the conversion, surfaced in the UI. */
  detail: string;
}

/**
 * Convert a threshold stated against a rounded published figure into the
 * equivalent threshold against the underlying value.
 *
 * With half-up rounding to `d` decimals and step `s = 10^-d`:
 *   reported ≥ X  ⟺  underlying ≥ X − s/2
 *   reported > X   ⟺  reported ≥ X + s  ⟺  underlying ≥ X + s/2
 *   reported ≤ X   ⟺  underlying < X + s/2
 *   reported < X   ⟺  reported ≤ X − s  ⟺  underlying < X − s/2
 */
export function effectiveThreshold(spec: ThresholdSpec): EffectiveThreshold {
  const { threshold, comparator, rounding } = spec;

  if (!rounding) {
    const isUpperTail = comparator === 'gte' || comparator === 'gt';
    return {
      value: threshold,
      isUpperTail,
      detail:
        `Rounding convention unknown; applied ${threshold} to the underlying value directly. ` +
        'This is a source of error worth resolving before trusting the number.',
    };
  }

  const step = Math.pow(10, -rounding.decimals);
  const half = step / 2;

  switch (comparator) {
    case 'gte':
      return {
        value: threshold - half,
        isUpperTail: true,
        detail:
          `Reported ≥ ${threshold} at ${rounding.decimals} dp rounds up from ${threshold - half}, ` +
          `so the underlying cutoff is ${threshold - half}.`,
      };
    case 'gt':
      return {
        value: threshold + half,
        isUpperTail: true,
        detail:
          `Reported > ${threshold} at ${rounding.decimals} dp means reported ≥ ${threshold + step}, ` +
          `so the underlying cutoff is ${threshold + half}.`,
      };
    case 'lte':
      return {
        value: threshold + half,
        isUpperTail: false,
        detail:
          `Reported ≤ ${threshold} at ${rounding.decimals} dp holds while the underlying is below ` +
          `${threshold + half}.`,
      };
    case 'lt':
      return {
        value: threshold - half,
        isUpperTail: false,
        detail:
          `Reported < ${threshold} at ${rounding.decimals} dp means reported ≤ ${threshold - step}, ` +
          `so the underlying must be below ${threshold - half}.`,
      };
  }
}

export interface ThresholdProbability {
  /** P(market resolves YES), strictly interior to (0, 1). */
  probability: number;
  /** The underlying-value cutoff actually used. */
  effectiveCutoff: number;
  /** Distance from the point estimate to the cutoff, in residual standard deviations. */
  standardizedDistance: number;
  /** Ordered explanation of how the number was reached. */
  reasoning: string[];
}

/**
 * P(resolution) for a threshold market.
 *
 * `pointEstimate` is the best available forecast of the underlying value.
 * `dist` describes how wrong forecasts of this kind have historically been at a
 * comparable horizon. The event is expressed on the underlying value, so:
 *
 *   actual = pointEstimate + residual
 *   P(actual ≥ cutoff) = P(residual ≥ cutoff − pointEstimate)
 */
export function thresholdProbability(
  pointEstimate: number,
  spec: ThresholdSpec,
  dist: ResidualDistribution,
): ThresholdProbability {
  const effective = effectiveThreshold(spec);
  const gap = effective.value - pointEstimate;

  // P(residual ≤ gap) — the probability the outcome lands below the cutoff.
  const below = residualCdf(dist, gap);
  const raw = effective.isUpperTail ? 1 - below : below;
  const probability = applyModelRiskFloor(raw);
  const flooredBy = probability !== raw;

  const standardizedDistance = dist.sd > 0 ? gap / dist.sd : 0;

  const reasoning = [
    effective.detail,
    `Point estimate ${pointEstimate} vs underlying cutoff ${round(effective.value, 6)} ` +
      `— a gap of ${round(gap, 6)}.`,
    `Residual distribution: n=${dist.n} from ${dist.source}, sd=${round(dist.sd, 4)}, ` +
      `IQR=${round(dist.iqr, 4)}, horizon ${dist.horizonRange.minDays}–${dist.horizonRange.maxDays}d` +
      (dist.biasCorrected
        ? `, bias of ${round(dist.bias, 4)} removed (n ≥ 24).`
        : `, bias of ${round(dist.bias, 4)} observed but NOT removed (sample too small).`),
    `That gap is ${round(standardizedDistance, 2)} residual standard deviations from the estimate.`,
    `P(${effective.isUpperTail ? 'underlying ≥' : 'underlying <'} ${round(effective.value, 6)}) = ` +
      `${round(probability, 4)}.`,
  ];

  if (flooredBy) {
    reasoning.push(
      `The threshold lies far outside the historical residual range, so the kernel returned ` +
        `${round(raw, 6)}. Clamped to the ${MODEL_RISK_FLOOR} model-risk floor: the chance that the ` +
        `resolution spec, series match, or residual sample is simply wrong exceeds that number.`,
    );
  }

  return {
    probability,
    effectiveCutoff: effective.value,
    standardizedDistance,
    reasoning,
  };
}

function round(value: number, places: number): number {
  const factor = Math.pow(10, places);
  return Math.round(value * factor) / factor;
}
