/**
 * Target-normalization layer.
 *
 * This exists because raw geometric targets routinely produce untradeable
 * arithmetic: a structural stop far from the entry leaves a "target" a fraction
 * of an R away, and price that has already run past a measured move produces a
 * target BEHIND the entry and a negative reward-to-risk. Both were observed in
 * the real engine before this layer was added.
 */

import { describe, expect, it } from 'vitest';
import { entryReference, finalizeTargets, rewardToRisk } from '@/lib/patterns/types';
import { buildIndicatorSnapshot } from '@/lib/patterns/indicators-snapshot';
import { DETECTORS, runDetector } from '@/lib/patterns/registry';
import type { MarketContext } from '@/lib/patterns/types';
import { doubleBottomSeries, downtrendSeries, noiseSeries, rangeSeries, uptrendSeries } from './fixtures';

const TICK = 0.01;

describe('finalizeTargets', () => {
  it('keeps a geometric target that already clears the R floor', () => {
    // long: entry 100, stop 95 → risk 5. A 130 target is 6R, well past the floor.
    const targets = finalizeTargets('long', { from: 99, to: 100 }, 95, [
      { price: 130, method: 'Measured move' },
      { price: 160, method: 'Extension' },
    ], TICK);

    expect(targets[0]!.price).toBe(130);
    expect(targets[0]!.method).toBe('Measured move');
    expect(targets[1]!.price).toBe(160);
  });

  it('lifts a target that sits below the minimum R multiple', () => {
    // entry 100, stop 90 → risk 10. A target at 101 is only 0.1R.
    const targets = finalizeTargets('long', { from: 99, to: 100 }, 90, [
      { price: 101, method: 'ATR extension' },
    ], TICK);

    const rr = rewardToRisk('long', 100, 90, targets[0]!.price);
    expect(rr).toBeGreaterThanOrEqual(1.5);
    expect(targets[0]!.method).toContain('1.5R');
  });

  it('discards a target that sits behind the entry and projects a real one', () => {
    // Price already ran past the measured move: target 98 is BELOW a long entry.
    const targets = finalizeTargets('long', { from: 99, to: 100 }, 95, [
      { price: 98, method: 'Measured move' },
    ], TICK);

    expect(targets.length).toBe(2);
    for (const t of targets) {
      expect(t.price).toBeGreaterThan(100);
      expect(rewardToRisk('long', 100, 95, t.price)).toBeGreaterThan(0);
    }
  });

  it('handles short scenarios symmetrically', () => {
    // short: entry 100, stop 105 → risk 5.
    const targets = finalizeTargets('short', { from: 100, to: 101 }, 105, [
      { price: 102, method: 'Too close' },
    ], TICK);

    for (const t of targets) {
      expect(t.price).toBeLessThan(100);
      expect(rewardToRisk('short', 100, 105, t.price)).toBeGreaterThanOrEqual(1.5);
    }
  });

  it('returns no targets when there is no risk distance', () => {
    expect(finalizeTargets('long', { from: 100, to: 100 }, 100, [{ price: 110, method: 'x' }], TICK)).toEqual([]);
  });

  it('always orders targets strictly, nearest first', () => {
    const long = finalizeTargets('long', { from: 99, to: 100 }, 95, [{ price: 101, method: 'a' }], TICK);
    expect(long[1]!.price).toBeGreaterThan(long[0]!.price);

    const short = finalizeTargets('short', { from: 100, to: 101 }, 106, [{ price: 100.5, method: 'a' }], TICK);
    expect(short[1]!.price).toBeLessThan(short[0]!.price);
  });

  it('rounds every target to the instrument tick size', () => {
    const targets = finalizeTargets('long', { from: 99, to: 100 }, 90, [], 0.5);
    for (const t of targets) {
      expect(Math.round(t.price / 0.5) * 0.5).toBeCloseTo(t.price, 8);
    }
  });
});

describe('entryReference', () => {
  it('uses the far edge of the zone so the scenario is measured conservatively', () => {
    expect(entryReference('long', { from: 99, to: 101 })).toBe(101);
    expect(entryReference('short', { from: 99, to: 101 })).toBe(99);
  });
});

describe('every produced candidate has tradeable arithmetic', () => {
  const context: MarketContext = {
    instrumentId: 'linear:TESTUSDT',
    category: 'linear',
    symbol: 'TESTUSDT',
    timeframe: '1h',
    tickSize: TICK,
    turnover24h: 250_000_000,
    spreadBps: 2,
    fundingRate: 0.00005,
    openInterestChangePct: 3,
    higherTimeframeBias: null,
    launchTime: null,
  };

  const fixtures = [
    ['uptrend', uptrendSeries(260, 100, 0.55, 1234)],
    ['downtrend', downtrendSeries(260, 400, 88)],
    ['range', rangeSeries(260)],
    ['noise', noiseSeries(260)],
    ['doubleBottom', doubleBottomSeries()],
  ] as const;

  for (const [name, candles] of fixtures) {
    it(`never emits a non-positive reward-to-risk on the ${name} fixture`, () => {
      const ind = buildIndicatorSnapshot(candles);

      for (const detector of DETECTORS) {
        for (const c of runDetector(detector, candles, ind, context)) {
          const entry = entryReference(c.direction, c.entryZone);

          for (const t of c.targets) {
            const rr = rewardToRisk(c.direction, entry, c.invalidation, t.price);
            expect(
              rr,
              `${detector.name} produced R:R ${rr} (entry ${entry}, stop ${c.invalidation}, target ${t.price})`,
            ).toBeGreaterThan(0);
          }

          // Target 1 must clear the published minimum floor.
          const firstTarget = c.targets[0];
          expect(firstTarget).toBeDefined();
          expect(rewardToRisk(c.direction, entry, c.invalidation, firstTarget!.price)).toBeGreaterThanOrEqual(1.5);
        }
      }
    });
  }
});
