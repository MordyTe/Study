/**
 * The series nowcast: fetches the resolving series once and produces both
 * halves of the statistical input — the point estimate for the next release,
 * and the historical residual record that says how wrong such estimates run.
 *
 * One agent rather than two ("nowcast-collector" + "history-builder") because
 * both derive from the same fetch, and a second identical request per market
 * per scan would be pure waste against a rate-limited host.
 *
 * No model is involved. The estimate is the persistence baseline — see
 * `estimate/persistence.ts` for why that humility is deliberate — and the
 * residuals are reconstructed exactly, because a persistence forecast's history
 * is just the series shifted by one release.
 */

import { catalogByFredId } from '@/lib/sources/catalog';
import { getSeriesObservations, isFredConfigured } from '@/lib/sources/fred';
import {
  latestPersistenceEstimate,
  persistenceObservations,
  toMetricSeries,
} from '@/lib/estimate/persistence';
import type { Agent, AgentContext, EvidenceBundle } from './types';

export const seriesNowcast: Agent = {
  name: 'series-nowcast',
  version: '1.0.0',
  displayName: 'Series nowcast',
  description:
    'Fetches the resolving series from FRED and produces a persistence point estimate ' +
    'plus the exact historical residual record of that estimator.',

  async run(
    bundle: EvidenceBundle,
    context: AgentContext,
  ): Promise<Partial<EvidenceBundle> | null> {
    const spec = bundle.spec;
    if (!spec?.seriesHint) {
      return { notes: ['series-nowcast: no series identified; nothing to fetch.'] };
    }

    const entry = catalogByFredId(spec.seriesHint);
    if (!entry) {
      // A model-proposed series outside the catalog: fetchable in principle,
      // but the transform and cycle would be guesses. Abstain instead.
      return {
        notes: [
          `series-nowcast: ${spec.seriesHint} is not in the catalog, so its transform and ` +
            'release cycle are unknown; abstaining rather than guessing.',
        ],
      };
    }

    if (!isFredConfigured()) {
      return {
        notes: [
          'series-nowcast: FRED_API_KEY is not configured; no estimate can be produced. ' +
            'A key is free at fred.stlouisfed.org.',
        ],
      };
    }

    let points;
    try {
      points = await getSeriesObservations(entry.fredId, { fetchImpl: context.fetchImpl });
    } catch (err) {
      return { notes: [`series-nowcast: FRED fetch failed — ${(err as Error).message}`] };
    }

    const metric = toMetricSeries(points, entry.transform);
    const estimate = latestPersistenceEstimate(metric);
    if (!estimate || metric.length < 14) {
      return {
        notes: [
          `series-nowcast: ${entry.fredId} returned too little history to be usable ` +
            `(${metric.length} derived points).`,
        ],
      };
    }

    return {
      pointEstimate: {
        value: estimate.value,
        sourceName: `fred:${entry.fredId}`,
        sourceUrl: `https://fred.stlouisfed.org/series/${entry.fredId}`,
        // The value was public before this scan began; the data vintage that
        // actually dates it is disclosed in `method`.
        observedAt: context.decisionAt,
        horizonDays: entry.cycleDays,
        method:
          `persistence (random-walk) nowcast: the latest published ${entry.label} ` +
          `(vintage ${estimate.vintageDate}) is the forecast for the next release.`,
      },
      observations: persistenceObservations(metric, entry.fredId, entry.cycleDays),
      claims: [
        {
          statement: `Latest published ${entry.label}: ${estimate.value.toFixed(entry.decimals + 1)} (vintage ${estimate.vintageDate}).`,
          value: estimate.value,
          unit: entry.transform === 'mom-diff' ? 'thousands' : 'percent',
          sourceName: `fred:${entry.fredId}`,
          sourceUrl: `https://fred.stlouisfed.org/series/${entry.fredId}`,
          observedAt: context.decisionAt,
          fetchedAt: context.decisionAt,
        },
      ],
      notes: [
        `series-nowcast: ${metric.length} derived observations from ${entry.fredId}; ` +
          `estimate ${estimate.value.toFixed(3)} at a ${entry.cycleDays}-day native horizon.`,
      ],
    };
  },
};
