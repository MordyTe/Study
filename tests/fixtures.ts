/**
 * Deterministic fixtures. No RNG, no clock — every value here is a function of
 * its arguments, which is what makes the determinism assertions meaningful.
 */

import type { ExtractRequest, ExtractResult, LlmProvider, ResolutionSpec } from '@/lib/agents/types';
import type { ForecastObservation } from '@/lib/estimate/residuals';
import type { BookLevel, Market, OrderBook } from '@/lib/polymarket/types';

/** A fixed instant, so nothing in the suite depends on when it runs. */
export const T0 = Date.UTC(2026, 7, 1, 12, 0, 0);

export function market(overrides: Partial<Market> = {}): Market {
  return {
    conditionId: '0xtest-condition',
    slug: 'cpi-above-3-september',
    question: 'Will US CPI year-over-year be above 3.0% in the September release?',
    description:
      'This market resolves YES if the year-over-year change in the Consumer Price Index for ' +
      'All Urban Consumers, as published by the Bureau of Labor Statistics, is above 3.0%.',
    outcomes: ['Yes', 'No'],
    clobTokenIds: ['token-yes', 'token-no'],
    outcomePrices: [0.45, 0.55],
    negRisk: false,
    active: true,
    closed: false,
    endDateIso: new Date(T0 + 20 * 86_400_000).toISOString(),
    volumeNum: 4_000,
    liquidityNum: 800,
    minimumTickSize: 0.01,
    category: 'Economics',
    ...overrides,
  };
}

export function orderBook(asks: BookLevel[], fetchedAt = T0): OrderBook {
  return {
    tokenId: 'token-yes',
    bids: asks.map((a) => ({ price: Math.max(0.001, a.price - 0.02), size: a.size })),
    asks,
    fetchedAt,
  };
}

export function spec(overrides: Partial<ResolutionSpec> = {}): ResolutionSpec {
  return {
    metric: 'CPI year-over-year, all items, NSA',
    agency: 'BLS',
    seriesHint: 'CUUR0000SA0',
    releaseAtIso: new Date(T0 + 20 * 86_400_000).toISOString(),
    threshold: 3.0,
    comparator: 'gt',
    rounding: { decimals: 1, mode: 'half-up' },
    confidence: 0.95,
    unresolvedAmbiguities: [],
    ...overrides,
  };
}

/**
 * `count` historical (forecast, actual) pairs whose residuals are symmetric
 * about zero and span ±`spread`.
 */
export function observations(
  count = 30,
  spread = 0.25,
  horizonDays = 20,
): ForecastObservation[] {
  const out: ForecastObservation[] = [];
  for (let i = 0; i < count; i++) {
    const t = count === 1 ? 0 : (2 * i) / (count - 1) - 1;
    out.push({
      seriesId: 'CUUR0000SA0',
      releaseDate: `2024-${String((i % 12) + 1).padStart(2, '0')}-15`,
      forecast: 2.9,
      actual: 2.9 + t * spread,
      horizonDays,
      source: 'clevelandfed-nowcast',
    });
  }
  return out;
}

/**
 * An LLM provider that returns whatever it is handed, without a network call.
 * Deliberately validates against the caller's schema so a stub that has drifted
 * from the real contract fails the test rather than passing it.
 */
export class StubLlmProvider implements LlmProvider {
  readonly kind = 'replay' as const;
  readonly calls: string[] = [];

  constructor(private readonly responses: Record<string, unknown>) {}

  async extract<T>(request: ExtractRequest<T>): Promise<ExtractResult<T>> {
    this.calls.push(request.cacheKey);
    // Match on the agent prefix so a cache key carrying a market id still hits.
    const key = Object.keys(this.responses).find((k) => request.cacheKey.startsWith(k));
    if (key === undefined) {
      return { data: null, replayed: true, detail: `Stub has no response for ${request.cacheKey}.` };
    }
    const parsed = request.schema.safeParse(this.responses[key]);
    if (!parsed.success) {
      return {
        data: null,
        replayed: true,
        detail: `Stub response failed the agent's own schema: ${parsed.error.message}`,
      };
    }
    return { data: parsed.data, replayed: true, detail: 'stub' };
  }
}

/** A provider that always abstains, mirroring an unconfigured deployment. */
export class SilentLlmProvider implements LlmProvider {
  readonly kind = 'unavailable' as const;
  async extract<T>(): Promise<ExtractResult<T>> {
    return { data: null, replayed: false, detail: 'no provider configured' };
  }
}
