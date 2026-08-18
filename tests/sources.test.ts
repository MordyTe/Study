/**
 * Data-source layer: the FRED boundary, the series catalog, and the
 * persistence transforms the statistical engine feeds on.
 */

import { describe, expect, it } from 'vitest';

import {
  FRED_ALLOWED_PATHS,
  ForbiddenFredPathError,
  assertFredPath,
  getSeriesObservations,
  isFredConfigured,
} from '@/lib/sources/fred';
import { CATALOG, catalogByFredId, findCatalogEntry } from '@/lib/sources/catalog';
import {
  latestPersistenceEstimate,
  persistenceObservations,
  toMetricSeries,
} from '@/lib/estimate/persistence';
import { buildResidualDistribution } from '@/lib/estimate/residuals';

// ---------------------------------------------------------------------------
// FRED boundary
// ---------------------------------------------------------------------------

describe('FRED boundary', () => {
  it('allows only the documented read paths', () => {
    for (const p of FRED_ALLOWED_PATHS) expect(() => assertFredPath(p)).not.toThrow();
    expect(() => assertFredPath('/fred/series/updates')).toThrow(ForbiddenFredPathError);
    expect(() => assertFredPath('/anything')).toThrow(ForbiddenFredPathError);
  });

  it('reports itself unconfigured without a key, and never treats blank as one', () => {
    expect(isFredConfigured({})).toBe(false);
    expect(isFredConfigured({ FRED_API_KEY: '  ' })).toBe(false);
    expect(isFredConfigured({ FRED_API_KEY: 'abc' })).toBe(true);
  });

  it('parses observations, dropping FRED\'s "." missing markers', async () => {
    const fetchImpl = (async () =>
      new Response(
        JSON.stringify({
          observations: [
            { date: '2026-01-01', value: '100.0' },
            { date: '2026-02-01', value: '.' },
            { date: '2026-03-01', value: '101.5' },
            { date: '2026-04-01', value: 'garbage' },
          ],
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      )) as unknown as typeof fetch;

    const points = await getSeriesObservations('TEST', {
      fetchImpl,
      env: { FRED_API_KEY: 'k' },
    });
    expect(points).toEqual([
      { date: '2026-01-01', value: 100.0 },
      { date: '2026-03-01', value: 101.5 },
    ]);
  });

  it('refuses to fetch without a configured key', async () => {
    await expect(
      getSeriesObservations('TEST', { env: {} }),
    ).rejects.toThrow('FRED_API_KEY');
  });
});

// ---------------------------------------------------------------------------
// Catalog
// ---------------------------------------------------------------------------

describe('series catalog', () => {
  it('has unique keys and FRED ids', () => {
    expect(new Set(CATALOG.map((e) => e.key)).size).toBe(CATALOG.length);
    expect(new Set(CATALOG.map((e) => e.fredId)).size).toBe(CATALOG.length);
  });

  it('matches core CPI before headline CPI — order is the guard', () => {
    expect(findCatalogEntry('Core CPI year-over-year for September')?.key).toBe('core-cpi-yoy');
    expect(findCatalogEntry('CPI year-over-year, all items')?.key).toBe('cpi-yoy');
  });

  it('maps the common release families', () => {
    expect(findCatalogEntry('unemployment rate above 4.5%')?.fredId).toBe('UNRATE');
    expect(findCatalogEntry('nonfarm payrolls beat 200k')?.fredId).toBe('PAYEMS');
    expect(findCatalogEntry('Will the FOMC cut the target rate?')?.fredId).toBe('DFEDTARU');
    expect(findCatalogEntry('US GDP growth above 2%')?.fredId).toBe('A191RL1Q225SBEA');
  });

  it('returns null for metrics it does not know, rather than a near-miss', () => {
    expect(findCatalogEntry('Best Picture at the Academy Awards')).toBeNull();
    expect(findCatalogEntry('Ethereum price above $5000')).toBeNull();
  });

  it('looks up by FRED id', () => {
    expect(catalogByFredId('CPIAUCNS')?.key).toBe('cpi-yoy');
    expect(catalogByFredId('NOPE')).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Persistence transforms
// ---------------------------------------------------------------------------

/** A monthly index rising 0.25% per month — ~3.04% year-over-year, exactly. */
function steadyIndex(months: number): Array<{ date: string; value: number }> {
  const out = [];
  for (let i = 0; i < months; i++) {
    const year = 2020 + Math.floor(i / 12);
    const month = (i % 12) + 1;
    out.push({
      date: `${year}-${String(month).padStart(2, '0')}-01`,
      value: 100 * Math.pow(1.0025, i),
    });
  }
  return out;
}

describe('persistence transforms', () => {
  it('computes year-over-year percent change against the observation 12 back', () => {
    const metric = toMetricSeries(steadyIndex(30), 'yoy-pct');
    expect(metric).toHaveLength(18);
    // (1.0025^12 − 1) × 100 = 3.0416…%
    for (const point of metric) expect(point.value).toBeCloseTo(3.0416, 3);
  });

  it('computes first differences for mom-diff', () => {
    const metric = toMetricSeries(
      [
        { date: '2026-01-01', value: 157000 },
        { date: '2026-02-01', value: 157150 },
        { date: '2026-03-01', value: 157100 },
      ],
      'mom-diff',
    );
    expect(metric).toEqual([
      { date: '2026-02-01', value: 150 },
      { date: '2026-03-01', value: -50 },
    ]);
  });

  it('passes level series through untouched', () => {
    const raw = [{ date: '2026-01-01', value: 4.1 }];
    expect(toMetricSeries(raw, 'level')).toEqual(raw);
  });

  it('builds (forecast, actual) pairs where each forecast is the prior release', () => {
    const metric = [
      { date: '2026-01-01', value: 3.0 },
      { date: '2026-02-01', value: 3.2 },
      { date: '2026-03-01', value: 3.1 },
    ];
    const obs = persistenceObservations(metric, 'TEST', 30);
    expect(obs).toEqual([
      {
        seriesId: 'TEST',
        releaseDate: '2026-02-01',
        forecast: 3.0,
        actual: 3.2,
        horizonDays: 30,
        source: 'fred-persistence',
      },
      {
        seriesId: 'TEST',
        releaseDate: '2026-03-01',
        forecast: 3.2,
        actual: 3.1,
        horizonDays: 30,
        source: 'fred-persistence',
      },
    ]);
  });

  it('produces residuals the estimator accepts end-to-end', () => {
    // A noisy-but-deterministic YoY series: enough structure for a real
    // distribution, no RNG so the test is reproducible.
    const metric = Array.from({ length: 40 }, (_, i) => ({
      date: `20${20 + Math.floor(i / 12)}-${String((i % 12) + 1).padStart(2, '0')}-01`,
      value: 3 + Math.sin(i * 1.7) * 0.3,
    }));
    const obs = persistenceObservations(metric, 'TEST', 30);
    const dist = buildResidualDistribution(obs, { targetHorizonDays: 30 });
    expect(dist).not.toBeNull();
    expect(dist!.n).toBe(39);
    expect(dist!.sd).toBeGreaterThan(0);
  });

  it('reports the latest value as the estimate, with its vintage', () => {
    const metric = [
      { date: '2026-05-01', value: 2.9 },
      { date: '2026-06-01', value: 3.1 },
    ];
    expect(latestPersistenceEstimate(metric)).toEqual({ value: 3.1, vintageDate: '2026-06-01' });
    expect(latestPersistenceEstimate([])).toBeNull();
  });
});
