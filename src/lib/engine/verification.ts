/**
 * The verification gate.
 *
 * Ported from the previous project, where it was the single highest-value
 * component: a pattern on a stale feed both scored lower AND could not be
 * promoted. The same logic applies here with more force, because this system's
 * output is a probability, and a probability computed from stale or
 * unreconciled evidence is not a weaker claim — it is a false one.
 *
 * Health is a hard veto on `ACTIONABLE`, not merely a scoring input.
 */

import type { EvidenceBundle } from '@/lib/agents/types';
import type { OrderBook } from '@/lib/polymarket/types';

export type Health = 'HEALTHY' | 'DEGRADED' | 'STALE' | 'INSUFFICIENT';

export interface VerificationRecord {
  health: Health;
  /** Age of the point estimate at decision time, ms. Null when there is none. */
  estimateAgeMs: number | null;
  /** Number of independent sources backing the evidence. */
  independentSources: number;
  /** Dollars resting on the side we would buy. */
  bookDepthUsd: number;
  /** Age of the order book snapshot, ms. */
  bookAgeMs: number | null;
  /** The parser's own confidence in its reading of the criteria. */
  specConfidence: number | null;
  /** Ambiguities the parser could not resolve. Non-empty forbids promotion. */
  unresolvedAmbiguities: string[];
  checks: Array<{ name: string; passed: boolean; detail: string }>;
}

export interface VerificationLimits {
  /** Beyond this, a point estimate is stale for a scheduled release. */
  maxEstimateAgeMs: number;
  maxBookAgeMs: number;
  minBookDepthUsd: number;
  minSpecConfidence: number;
  minIndependentSources: number;
}

export const DEFAULT_VERIFICATION_LIMITS: VerificationLimits = {
  // Two days: nowcasts for scheduled releases update on a daily-ish cadence,
  // and anything older has usually been superseded by new component data.
  maxEstimateAgeMs: 48 * 60 * 60 * 1000,
  maxBookAgeMs: 5 * 60 * 1000,
  minBookDepthUsd: 25,
  minSpecConfidence: 0.8,
  minIndependentSources: 1,
};

export function buildVerificationRecord(
  bundle: EvidenceBundle,
  book: OrderBook | null,
  limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
): VerificationRecord {
  const estimateAgeMs = bundle.pointEstimate
    ? bundle.decisionAt - bundle.pointEstimate.observedAt
    : null;

  const sources = new Set(bundle.claims.map((c) => c.sourceName));
  if (bundle.pointEstimate) sources.add(bundle.pointEstimate.sourceName);
  const independentSources = sources.size;

  const bookDepthUsd = book ? book.asks.reduce((a, l) => a + l.price * l.size, 0) : 0;
  const bookAgeMs = book ? bundle.decisionAt - book.fetchedAt : null;

  const specConfidence = bundle.spec?.confidence ?? null;
  const unresolvedAmbiguities = bundle.spec?.unresolvedAmbiguities ?? [];

  const checks: VerificationRecord['checks'] = [
    {
      name: 'resolution-spec',
      passed: bundle.spec !== null,
      detail: bundle.spec
        ? `Parsed as ${bundle.spec.metric} ${bundle.spec.comparator} ${bundle.spec.threshold}.`
        : 'No machine-readable resolution spec was produced.',
    },
    {
      name: 'spec-confidence',
      passed: specConfidence !== null && specConfidence >= limits.minSpecConfidence,
      detail:
        specConfidence === null
          ? 'No spec, so no confidence to assess.'
          : `Parser confidence ${specConfidence.toFixed(2)} against a floor of ${limits.minSpecConfidence}.`,
    },
    {
      name: 'no-unresolved-ambiguity',
      passed: unresolvedAmbiguities.length === 0,
      detail:
        unresolvedAmbiguities.length === 0
          ? 'The criteria were read without residual ambiguity.'
          : `Unresolved: ${unresolvedAmbiguities.join('; ')}`,
    },
    {
      name: 'point-estimate-present',
      passed: bundle.pointEstimate !== null,
      detail: bundle.pointEstimate
        ? `Estimate ${bundle.pointEstimate.value} from ${bundle.pointEstimate.sourceName}.`
        : 'No point estimate was gathered.',
    },
    {
      name: 'estimate-freshness',
      passed: estimateAgeMs !== null && estimateAgeMs <= limits.maxEstimateAgeMs,
      detail:
        estimateAgeMs === null
          ? 'No estimate to age.'
          : `Estimate is ${(estimateAgeMs / 3_600_000).toFixed(1)}h old; limit is ` +
            `${(limits.maxEstimateAgeMs / 3_600_000).toFixed(0)}h.`,
    },
    {
      name: 'independent-sources',
      passed: independentSources >= limits.minIndependentSources,
      detail: `${independentSources} independent source(s); minimum is ${limits.minIndependentSources}.`,
    },
    {
      name: 'book-depth',
      passed: bookDepthUsd >= limits.minBookDepthUsd,
      detail: `$${bookDepthUsd.toFixed(2)} resting on the ask side; minimum is $${limits.minBookDepthUsd}.`,
    },
    {
      name: 'book-freshness',
      passed: bookAgeMs !== null && bookAgeMs <= limits.maxBookAgeMs,
      detail:
        bookAgeMs === null
          ? 'No order book snapshot.'
          : `Book snapshot is ${(bookAgeMs / 1000).toFixed(0)}s old; limit is ` +
            `${(limits.maxBookAgeMs / 1000).toFixed(0)}s.`,
    },
  ];

  return {
    health: deriveHealth(checks, estimateAgeMs, limits),
    estimateAgeMs,
    independentSources,
    bookDepthUsd,
    bookAgeMs,
    specConfidence,
    unresolvedAmbiguities,
    checks,
  };
}

function deriveHealth(
  checks: VerificationRecord['checks'],
  estimateAgeMs: number | null,
  limits: VerificationLimits,
): Health {
  const failed = checks.filter((c) => !c.passed).map((c) => c.name);
  if (failed.length === 0) return 'HEALTHY';

  // Missing structural prerequisites is a different condition from having them
  // and finding them old, and the UI should not conflate the two.
  const structural = ['resolution-spec', 'point-estimate-present', 'book-depth'];
  if (failed.some((f) => structural.includes(f))) return 'INSUFFICIENT';

  if (estimateAgeMs !== null && estimateAgeMs > limits.maxEstimateAgeMs) return 'STALE';
  if (failed.includes('book-freshness')) return 'STALE';

  return 'DEGRADED';
}

/**
 * The hard gate. Nothing may be promoted to ACTIONABLE without this, regardless
 * of how attractive the arithmetic looks.
 */
export function isVerified(record: VerificationRecord): boolean {
  return record.health === 'HEALTHY';
}
