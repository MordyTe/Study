/**
 * The venue's taker fee model.
 *
 * Polymarket introduced taker fees in 2026, priced as
 *
 *     fee = shares × coefficient × p × (1 − p)
 *
 * The `p(1 − p)` term peaks at 0.25 when p = 0.50 and vanishes at the extremes,
 * so a fee-blind edge calculation is wrong by the largest amount at exactly the
 * prices where prediction markets are most active. Makers pay nothing and earn
 * a rebate, which is why any strategy that survives contact with this schedule
 * tends to migrate toward resting orders — a materially harder system, and a
 * deliberate non-goal for v1.
 *
 * Every constant here is an ASSUMPTION with a stated provenance, not a fact.
 * The live coefficient is queried from the venue at scan time; these values are
 * the conservative fallback used when that query fails, and any result computed
 * from a fallback says so.
 */

export type FeeCategory =
  | 'politics'
  | 'finance'
  | 'tech'
  | 'sports'
  | 'economics'
  | 'culture'
  | 'weather'
  | 'crypto'
  | 'geopolitics'
  | 'other';

/**
 * Coefficients derived from the published per-100-share caps, which are quoted
 * at p = 0.50 where p(1−p) = 0.25:
 *
 *     coefficient = cap_per_share / 0.25 = (cap_per_100 / 100) / 0.25
 *
 * e.g. a $1.00/100-share cap ⇒ $0.01/share at p=0.5 ⇒ coefficient 0.04.
 */
export const FEE_COEFFICIENTS: Record<FeeCategory, number> = {
  politics: 0.04,
  finance: 0.04,
  tech: 0.04,
  sports: 0.05,
  economics: 0.05,
  culture: 0.05,
  weather: 0.05,
  other: 0.05,
  crypto: 0.07,
  geopolitics: 0.0,
};

/**
 * Used when the category cannot be determined. The most expensive non-crypto
 * tier, because assuming the cheap tier turns a losing edge into a reported
 * winner, and this system's whole purpose is to not do that.
 */
export const DEFAULT_FEE_COEFFICIENT = 0.05;

export interface FeeModel {
  coefficient: number;
  category: FeeCategory | null;
  /** True when the coefficient came from the venue rather than the fallback table. */
  fromVenue: boolean;
  detail: string;
}

export function resolveFeeModel(
  category: FeeCategory | null,
  venueCoefficient: number | null,
): FeeModel {
  if (venueCoefficient !== null && Number.isFinite(venueCoefficient)) {
    return {
      coefficient: venueCoefficient,
      category,
      fromVenue: true,
      detail: `Fee coefficient ${venueCoefficient} queried live from the venue.`,
    };
  }
  if (category && category in FEE_COEFFICIENTS) {
    const coefficient = FEE_COEFFICIENTS[category];
    return {
      coefficient,
      category,
      fromVenue: false,
      detail:
        `Venue fee query unavailable; using the published ${category} coefficient ` +
        `${coefficient} as a fallback. Treat the resulting edge as an estimate.`,
    };
  }
  return {
    coefficient: DEFAULT_FEE_COEFFICIENT,
    category: null,
    fromVenue: false,
    detail:
      `Category undetermined and venue fee query unavailable; using the conservative ` +
      `default coefficient ${DEFAULT_FEE_COEFFICIENT}.`,
  };
}

/** Taker fee in dollars for one share filled at price `p`. */
export function feePerShare(price: number, model: FeeModel): number {
  const p = Math.min(1, Math.max(0, price));
  return model.coefficient * p * (1 - p);
}

/** Taker fee in dollars for `shares` filled at an average price of `p`. */
export function totalFee(shares: number, avgPrice: number, model: FeeModel): number {
  return shares * feePerShare(avgPrice, model);
}

/**
 * The gross edge a position must clear before it breaks even, expressed in
 * dollars per share. Reported alongside every candidate so a 3¢ apparent edge
 * against a 2.5¢ hurdle is never displayed as "3¢ of edge".
 */
export function breakEvenEdgePerShare(price: number, model: FeeModel): number {
  return feePerShare(price, model);
}
