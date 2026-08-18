/**
 * The persistence baseline: forecast_next = value_now.
 *
 * This is v1's statistical engine, and choosing it is a deliberate act of
 * humility. A random-walk nowcast of a persistent series like CPI year-over-year
 * is a famously hard baseline to beat, it is computable from a single public
 * series with zero judgement, and — the property that matters most here — its
 * historical error distribution is *fully reconstructible*: for every past
 * release we know exactly what the persistence forecast was, because it was
 * simply the previous release. No archived forecast vintages required, no
 * survivorship, no look-ahead.
 *
 * The residuals it yields are therefore honest by construction. When a real
 * external nowcast (Cleveland Fed, consensus surveys) is wired in later, it
 * must clear this baseline's Brier score out-of-sample to earn its place —
 * which is exactly the discipline the rest of the system is built around.
 *
 * Everything here is a pure function of the series.
 */

import type { ForecastObservation } from './residuals';
import type { SeriesPoint } from '@/lib/sources/fred';
import type { Transform } from '@/lib/sources/catalog';

/**
 * Derive the published headline metric from the raw series.
 *
 *   yoy-pct  — percent change vs 12 observations earlier (monthly series)
 *   mom-diff — first difference (e.g. payrolls change in thousands)
 *   level    — the series is already the headline number
 */
export function toMetricSeries(points: SeriesPoint[], transform: Transform): SeriesPoint[] {
  switch (transform) {
    case 'level':
      return points.slice();
    case 'mom-diff': {
      const out: SeriesPoint[] = [];
      for (let i = 1; i < points.length; i++) {
        out.push({ date: points[i]!.date, value: points[i]!.value - points[i - 1]!.value });
      }
      return out;
    }
    case 'yoy-pct': {
      const out: SeriesPoint[] = [];
      for (let i = 12; i < points.length; i++) {
        const base = points[i - 12]!.value;
        if (base === 0) continue;
        out.push({
          date: points[i]!.date,
          value: ((points[i]!.value - base) / Math.abs(base)) * 100,
        });
      }
      return out;
    }
  }
}

/**
 * Historical (forecast, actual) pairs under the persistence model: each
 * release's forecast is simply the release before it. The horizon is the
 * release cycle — the model's native lead time — which is what the residual
 * distribution is matched on downstream.
 */
export function persistenceObservations(
  metricSeries: SeriesPoint[],
  seriesId: string,
  cycleDays: number,
): ForecastObservation[] {
  const out: ForecastObservation[] = [];
  for (let i = 1; i < metricSeries.length; i++) {
    out.push({
      seriesId,
      releaseDate: metricSeries[i]!.date,
      forecast: metricSeries[i - 1]!.value,
      actual: metricSeries[i]!.value,
      horizonDays: cycleDays,
      source: 'fred-persistence',
    });
  }
  return out;
}

/** The persistence point estimate for the next release: the latest value. */
export function latestPersistenceEstimate(
  metricSeries: SeriesPoint[],
): { value: number; vintageDate: string } | null {
  const last = metricSeries[metricSeries.length - 1];
  return last ? { value: last.value, vintageDate: last.date } : null;
}
