/**
 * Empirical forecast-error distributions.
 *
 * This is the statistical basis of the whole system. An agent supplies a point
 * estimate for a scheduled release; this module supplies the distribution of
 * how wrong that kind of estimate has historically been. The probability the
 * system reports is arithmetic over the two. No language model is involved
 * below this line, and none ever emits a percentage.
 *
 * Design choices worth stating, because each one is a place a naive
 * implementation produces confidently wrong numbers:
 *
 *  - **Kernel-smoothed empirical CDF**, not a fitted normal. Economic surprises
 *    have fat tails and occasional skew; a Gaussian understates exactly the
 *    outcomes that decide a threshold market. The kernel keeps the observed
 *    tail shape while still returning a smooth, strictly-interior probability.
 *  - **Never returns exactly 0 or 1.** A raw empirical CDF does, on small
 *    samples, at precisely the thresholds furthest from the mean — which is
 *    where a mispricing would look most attractive.
 *  - **Bias correction is gated on sample size.** Correcting a systematic lean
 *    is right with 30 observations and is overfitting with 8.
 *  - **Horizon matters.** A nowcast 1 day before a release is not the same
 *    estimator as one 30 days before. Residuals are filtered to a comparable
 *    horizon or the distribution is refused.
 */

/** One historical (forecast, actual) pair for a given series and horizon. */
export interface ForecastObservation {
  /** Identifier of the series being forecast, e.g. a FRED series id. */
  seriesId: string;
  /** ISO date of the release this observation refers to. */
  releaseDate: string;
  /** What the source predicted. */
  forecast: number;
  /** What the agency actually published. */
  actual: number;
  /** Days between the forecast being made and the release. */
  horizonDays: number;
  /** Where the forecast came from, e.g. `clevelandfed-nowcast`. */
  source: string;
}

export interface ResidualDistribution {
  seriesId: string;
  source: string;
  /** Number of residuals backing this distribution. */
  n: number;
  /** Sorted ascending. Residual = actual − forecast. */
  residuals: number[];
  /** Median residual. Positive means the source historically under-predicts. */
  bias: number;
  /** Sample standard deviation of residuals. */
  sd: number;
  /** Interquartile range, used for the bandwidth and reported for context. */
  iqr: number;
  /** Kernel bandwidth actually used. */
  bandwidth: number;
  /** Horizon window these residuals were drawn from, in days. */
  horizonRange: { minDays: number; maxDays: number };
  /** True when `bias` was subtracted from residuals before use. */
  biasCorrected: boolean;
}

/**
 * Below this many residuals the distribution is refused outright and the caller
 * abstains. Chosen because the kernel bandwidth and the tail behaviour are both
 * unstable on smaller samples, and an unstable tail is what produces a
 * confident wrong answer on exactly the markets that look most mispriced.
 */
export const MIN_RESIDUALS = 12;

/** Bias is only removed once there is enough data for the lean to be real. */
export const MIN_RESIDUALS_FOR_BIAS_CORRECTION = 24;

export function quantile(sorted: number[], p: number): number {
  if (sorted.length === 0) return Number.NaN;
  if (sorted.length === 1) return sorted[0]!;
  const clamped = Math.min(1, Math.max(0, p));
  const index = clamped * (sorted.length - 1);
  const lower = Math.floor(index);
  const upper = Math.ceil(index);
  if (lower === upper) return sorted[lower]!;
  const weight = index - lower;
  return sorted[lower]! * (1 - weight) + sorted[upper]! * weight;
}

function standardDeviation(values: number[]): number {
  if (values.length < 2) return 0;
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  const variance =
    values.reduce((acc, v) => acc + (v - mean) ** 2, 0) / (values.length - 1);
  return Math.sqrt(variance);
}

/**
 * Abramowitz & Stegun 7.1.26 — max absolute error 1.5e-7, which is several
 * orders of magnitude finer than the uncertainty in the inputs.
 */
function erf(x: number): number {
  const sign = x < 0 ? -1 : 1;
  const absX = Math.abs(x);
  const t = 1 / (1 + 0.3275911 * absX);
  const y =
    1 -
    ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t +
      0.254829592) *
      t *
      Math.exp(-absX * absX);
  return sign * y;
}

export function standardNormalCdf(z: number): number {
  return 0.5 * (1 + erf(z / Math.SQRT2));
}

/**
 * Silverman's rule of thumb, using the robust min(sd, IQR/1.34) scale so a
 * single outlier does not inflate the bandwidth and flatten the whole curve.
 */
function silvermanBandwidth(values: number[], sd: number, iqr: number): number {
  const n = values.length;
  const robustScale = iqr > 0 ? Math.min(sd, iqr / 1.34) : sd;
  const h = 0.9 * robustScale * Math.pow(n, -1 / 5);
  // A degenerate sample (every residual identical) would give h = 0 and a step
  // function. Floor it at something small but non-zero relative to the data.
  if (h > 0) return h;
  const spread = Math.abs(values[values.length - 1]! - values[0]!);
  return spread > 0 ? spread / 10 : 1e-6;
}

export interface BuildResidualOptions {
  /** Only use observations within this many days of the target horizon. */
  horizonToleranceDays?: number;
  /** Target horizon. Observations are filtered to within tolerance of it. */
  targetHorizonDays: number;
  /** Override the automatic bias-correction decision. */
  forceBiasCorrection?: boolean;
}

/**
 * Build a residual distribution, or return null when there is not enough
 * comparable history. Returning null is a first-class outcome: the caller
 * abstains, and a high abstention rate is correct behaviour, not a failure.
 */
export function buildResidualDistribution(
  observations: ForecastObservation[],
  options: BuildResidualOptions,
): ResidualDistribution | null {
  const tolerance = options.horizonToleranceDays ?? 7;
  const target = options.targetHorizonDays;

  const comparable = observations.filter(
    (o) =>
      Number.isFinite(o.forecast) &&
      Number.isFinite(o.actual) &&
      Math.abs(o.horizonDays - target) <= tolerance,
  );

  if (comparable.length < MIN_RESIDUALS) return null;

  const raw = comparable.map((o) => o.actual - o.forecast).sort((a, b) => a - b);
  const bias = quantile(raw, 0.5);

  const shouldCorrect =
    options.forceBiasCorrection ??
    comparable.length >= MIN_RESIDUALS_FOR_BIAS_CORRECTION;

  const residuals = shouldCorrect ? raw.map((r) => r - bias).sort((a, b) => a - b) : raw;

  const sd = standardDeviation(residuals);
  const iqr = quantile(residuals, 0.75) - quantile(residuals, 0.25);
  const horizons = comparable.map((o) => o.horizonDays);

  return {
    seriesId: comparable[0]!.seriesId,
    source: comparable[0]!.source,
    n: residuals.length,
    residuals,
    bias,
    sd,
    iqr,
    bandwidth: silvermanBandwidth(residuals, sd, iqr),
    horizonRange: { minDays: Math.min(...horizons), maxDays: Math.max(...horizons) },
    biasCorrected: shouldCorrect,
  };
}

/**
 * P(residual ≤ x) under the kernel-smoothed empirical distribution.
 *
 * Strictly interior to (0, 1) for any finite x, by construction: every kernel
 * contributes a positive, sub-unit amount everywhere.
 */
export function residualCdf(dist: ResidualDistribution, x: number): number {
  let sum = 0;
  for (const r of dist.residuals) {
    sum += standardNormalCdf((x - r) / dist.bandwidth);
  }
  return sum / dist.n;
}

/** P(residual > x). */
export function residualSurvival(dist: ResidualDistribution, x: number): number {
  return 1 - residualCdf(dist, x);
}
