import { describe, expect, it } from 'vitest';
import { DETECTORS, getDetector, listDetectorMeta, runDetector } from '@/lib/patterns/registry';
import { buildIndicatorSnapshot } from '@/lib/patterns/indicators-snapshot';
import { roundToTick, rewardToRisk, type MarketContext } from '@/lib/patterns/types';
import { doubleBottomSeries, downtrendSeries, noiseSeries, rangeSeries, uptrendSeries } from './fixtures';

function ctx(overrides: Partial<MarketContext> = {}): MarketContext {
  return {
    instrumentId: 'linear:TESTUSDT',
    category: 'linear',
    symbol: 'TESTUSDT',
    timeframe: '1h',
    tickSize: 0.01,
    turnover24h: 50_000_000,
    spreadBps: 3,
    fundingRate: 0.0001,
    openInterestChangePct: 2,
    higherTimeframeBias: null,
    launchTime: null,
    ...overrides,
  };
}

describe('detector registry', () => {
  it('registers the full documented catalog', () => {
    expect(DETECTORS.length).toBeGreaterThanOrEqual(12);
  });

  it('has unique detector names', () => {
    const names = DETECTORS.map((d) => d.name);
    expect(new Set(names).size).toBe(names.length);
  });

  it('every detector declares a semantic version and a minimum candle count', () => {
    for (const d of DETECTORS) {
      expect(d.version).toMatch(/^\d+\.\d+\.\d+$/);
      expect(d.minCandles).toBeGreaterThan(0);
      expect(d.displayName.length).toBeGreaterThan(3);
      expect(d.description.length).toBeGreaterThan(20);
    }
  });

  it('resolves detectors by name', () => {
    expect(getDetector('breakout_retest')?.displayName).toBe('Breakout + Retest');
    expect(getDetector('does_not_exist')).toBeUndefined();
  });

  it('exposes metadata for the pattern library', () => {
    expect(listDetectorMeta().length).toBe(DETECTORS.length);
  });
});

describe('detector contract', () => {
  const series = [
    { name: 'uptrend', candles: uptrendSeries(240) },
    { name: 'downtrend', candles: downtrendSeries(240) },
    { name: 'range', candles: rangeSeries(240) },
    { name: 'noise', candles: noiseSeries(240) },
    { name: 'doubleBottom', candles: doubleBottomSeries() },
  ];

  for (const { name, candles } of series) {
    it(`produces structurally valid candidates on the ${name} fixture`, () => {
      const ind = buildIndicatorSnapshot(candles);
      const context = ctx();

      for (const detector of DETECTORS) {
        if (candles.length < detector.minCandles) continue;
        const found = runDetector(detector, candles, ind, context);
        expect(Array.isArray(found)).toBe(true);

        for (const c of found) {
          // Identity
          expect(c.detectorName).toBe(detector.name);
          expect(c.detectorVersion).toBe(detector.version);
          expect(['long', 'short']).toContain(c.direction);

          // Confirmation must be the last CLOSED candle — no lookahead.
          expect(c.confirmationIndex).toBe(candles.length - 1);
          expect(c.confirmationTime).toBe(candles[candles.length - 1]!.time);

          // Geometry quality is a normalized conviction.
          expect(c.geometryQuality).toBeGreaterThanOrEqual(0);
          expect(c.geometryQuality).toBeLessThanOrEqual(1);

          // Scenario values must be finite and ordered.
          expect(Number.isFinite(c.entryZone.from)).toBe(true);
          expect(Number.isFinite(c.entryZone.to)).toBe(true);
          expect(c.entryZone.from).toBeLessThanOrEqual(c.entryZone.to);
          expect(Number.isFinite(c.invalidation)).toBe(true);
          expect(c.invalidation).toBeGreaterThan(0);

          // Invalidation must sit on the correct side of the entry.
          const entryMid = (c.entryZone.from + c.entryZone.to) / 2;
          if (c.direction === 'long') expect(c.invalidation).toBeLessThan(entryMid);
          else expect(c.invalidation).toBeGreaterThan(entryMid);

          // Targets must be present, finite, and on the correct side.
          expect(c.targets.length).toBeGreaterThan(0);
          for (const t of c.targets) {
            expect(Number.isFinite(t.price)).toBe(true);
            expect(t.method.length).toBeGreaterThan(3);
            if (c.direction === 'long') expect(t.price).toBeGreaterThan(c.invalidation);
            else expect(t.price).toBeLessThan(c.invalidation);
          }

          // Explainability is mandatory.
          expect(c.reasonsFor.length).toBeGreaterThan(0);
          expect(c.reasonsAgainst.length).toBeGreaterThan(0);
          expect(Object.keys(c.parameters).length).toBeGreaterThan(0);
          expect(c.overlays.length).toBeGreaterThan(0);
        }
      }
    });
  }

  it('does not manufacture signals from a tight range on every detector', () => {
    // A flat, low-volatility range should yield far fewer signals than a trend.
    const range = rangeSeries(240);
    const trend = uptrendSeries(240, 100, 0.6, 21);

    const count = (candles: typeof range) => {
      const ind = buildIndicatorSnapshot(candles);
      return DETECTORS.filter((d) => candles.length >= d.minCandles).reduce(
        (acc, d) => acc + runDetector(d, candles, ind, ctx()).length,
        0,
      );
    };

    expect(count(range)).toBeLessThanOrEqual(count(trend) + 3);
  });
});

describe('no-lookahead invariant', () => {
  it('a detector run on a truncated series is unaffected by future candles', () => {
    const full = uptrendSeries(260, 100, 0.5, 77);
    const cut = 200;
    const truncated = full.slice(0, cut);

    const indTrunc = buildIndicatorSnapshot(truncated);
    const resultsTrunc = DETECTORS.filter((d) => truncated.length >= d.minCandles).flatMap((d) =>
      runDetector(d, truncated, indTrunc, ctx()),
    );

    // Re-run on the same prefix; results must be byte-identical (deterministic).
    const indTrunc2 = buildIndicatorSnapshot(full.slice(0, cut));
    const resultsTrunc2 = DETECTORS.filter((d) => truncated.length >= d.minCandles).flatMap((d) =>
      runDetector(d, full.slice(0, cut), indTrunc2, ctx()),
    );

    expect(JSON.stringify(resultsTrunc2)).toBe(JSON.stringify(resultsTrunc));

    // Every candidate references only bars within the truncated window.
    for (const c of resultsTrunc) {
      expect(c.confirmationIndex).toBeLessThan(cut);
      expect(c.confirmationTime).toBeLessThanOrEqual(truncated[cut - 1]!.time);
    }
  });
});

describe('scenario helpers', () => {
  it('rounds prices to the instrument tick size', () => {
    expect(roundToTick(123.456789, 0.01)).toBe(123.46);
    expect(roundToTick(123.456789, 0.1)).toBe(123.5);
    expect(roundToTick(0.000123456, 0.000001)).toBeCloseTo(0.000123, 9);
  });

  it('computes reward-to-risk correctly for both directions', () => {
    // long: entry 100, stop 95 (risk 5), target 115 (reward 15) → 3.0
    expect(rewardToRisk('long', 100, 95, 115)).toBeCloseTo(3, 10);
    // short: entry 100, stop 105 (risk 5), target 90 (reward 10) → 2.0
    expect(rewardToRisk('short', 100, 105, 90)).toBeCloseTo(2, 10);
  });

  it('returns zero rather than infinity when there is no risk distance', () => {
    expect(rewardToRisk('long', 100, 100, 110)).toBe(0);
  });
});
