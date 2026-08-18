/**
 * Calibration and the paper ledger — golden tests with hand-computed values.
 *
 * These are the numbers the whole project's verdict will rest on, so every
 * expected value here was worked by hand before the assertion was written.
 */

import { describe, expect, it } from 'vitest';

import {
  MIN_CALIBRATION_SAMPLE,
  computeCalibration,
  type ResolutionRecord,
} from '@/lib/paper/calibration';
import type { Candidate } from '@/lib/engine/assess';

const T0 = Date.UTC(2026, 7, 1);

/** A minimal candidate with exactly the fields calibration reads. */
function candidate(overrides: Partial<Candidate>): Candidate {
  return {
    id: 'id',
    fingerprint: 'fp',
    marketId: 'm1',
    question: 'q',
    decisionAt: T0,
    status: 'WATCH',
    fairProbability: 0.6,
    marketPrice: 0.5,
    grossEdge: 0.1,
    feeHurdle: 0.0125,
    sizing: null,
    curve: [],
    residuals: null,
    verification: {
      health: 'HEALTHY',
      estimateAgeMs: 0,
      independentSources: 1,
      bookDepthUsd: 100,
      bookAgeMs: 0,
      specConfidence: 0.9,
      unresolvedAmbiguities: [],
      checks: [],
    },
    reasoning: [],
    abstentionReasons: [],
    assumptions: [],
    ...overrides,
  };
}

function resolution(marketId: string, resolvedYes: boolean, resolvedAt = T0 + 86_400_000): ResolutionRecord {
  return { marketId, resolvedYes, resolvedAt };
}

describe('computeCalibration', () => {
  it('computes the hand-worked Brier scores for ours and the market', () => {
    // Market A: we said 0.8, price 0.6, resolved YES → ours (0.2)²=0.04, market (0.4)²=0.16
    // Market B: we said 0.3, price 0.4, resolved NO  → ours (0.3)²=0.09, market (0.4)²=0.16
    // Brier ours = 0.065; market = 0.16; edge = −0.095.
    const report = computeCalibration(
      [
        candidate({ id: 'a', marketId: 'A', fairProbability: 0.8, marketPrice: 0.6 }),
        candidate({ id: 'b', marketId: 'B', fairProbability: 0.3, marketPrice: 0.4 }),
      ],
      [resolution('A', true), resolution('B', false)],
    );
    expect(report.n).toBe(2);
    expect(report.brierOurs).toBeCloseTo(0.065, 10);
    expect(report.brierMarket).toBeCloseTo(0.16, 10);
    expect(report.brierEdge).toBeCloseTo(-0.095, 10);
  });

  it('scores only the latest estimate per market — no double counting', () => {
    const report = computeCalibration(
      [
        candidate({ id: 'old', marketId: 'A', fairProbability: 0.9, decisionAt: T0 - 1000 }),
        candidate({ id: 'new', marketId: 'A', fairProbability: 0.6, decisionAt: T0 }),
      ],
      [resolution('A', true)],
    );
    expect(report.n).toBe(1);
    // Only the 0.6 estimate counts: (0.4)² = 0.16.
    expect(report.brierOurs).toBeCloseTo(0.16, 10);
  });

  it('refuses to score an estimate made at or after resolution — ledger no-lookahead', () => {
    const report = computeCalibration(
      [candidate({ marketId: 'A', decisionAt: T0 + 86_400_000 })],
      [resolution('A', true, T0 + 86_400_000)],
    );
    expect(report.n).toBe(0);
    expect(report.brierOurs).toBeNull();
  });

  it('ignores unresolved markets and abstained candidates', () => {
    const report = computeCalibration(
      [
        candidate({ marketId: 'A' }),
        candidate({ id: 'x', marketId: 'B', fairProbability: null, status: 'ABSTAIN' }),
      ],
      [resolution('A', true)],
    );
    expect(report.n).toBe(1);
  });

  it('builds a reliability bucket with mean forecast and realized frequency', () => {
    // Three estimates in the 60–70% bucket; two resolve YES → frequency 2/3.
    const report = computeCalibration(
      [
        candidate({ id: '1', marketId: 'A', fairProbability: 0.62 }),
        candidate({ id: '2', marketId: 'B', fairProbability: 0.65 }),
        candidate({ id: '3', marketId: 'C', fairProbability: 0.68 }),
      ],
      [resolution('A', true), resolution('B', true), resolution('C', false)],
    );
    const bucket = report.buckets.find((b) => b.lo === 0.6);
    expect(bucket).toBeDefined();
    expect(bucket!.count).toBe(3);
    expect(bucket!.meanForecast).toBeCloseTo(0.65, 10);
    expect(bucket!.frequency).toBeCloseTo(2 / 3, 10);
  });

  describe('paper ledger', () => {
    const actionable = candidate({
      marketId: 'A',
      status: 'ACTIONABLE',
      fairProbability: 0.7,
      sizing: {
        notional: 20,
        kellyFractionRaw: 0.4,
        kellyFractionApplied: 0.1,
        maxProfitable: 50,
        limitedBy: 'kelly',
        detail: '',
      },
      curve: [
        {
          notional: 20,
          fill: { shares: 40, avgPrice: 0.5, notional: 20, levelsConsumed: 1, exhausted: false },
          expectedValue: 7.5,
          expectedReturn: 0.375,
          feesPaid: 0.5,
        },
      ],
    });

    it('computes P&L on a win: payout − cost − fees', () => {
      // 40 shares pay $40; cost $20; fees $0.50 → +$19.50.
      const report = computeCalibration([actionable], [resolution('A', true)]);
      expect(report.fills).toHaveLength(1);
      expect(report.fills[0]!.pnl).toBeCloseTo(19.5, 10);
      expect(report.totalPnl).toBeCloseTo(19.5, 10);
      expect(report.totalStaked).toBeCloseTo(20.5, 10);
    });

    it('computes P&L on a loss: the full stake plus fees', () => {
      const report = computeCalibration([actionable], [resolution('A', false)]);
      expect(report.fills[0]!.pnl).toBeCloseTo(-20.5, 10);
    });

    it('takes no paper position from WATCH or ABSTAIN candidates', () => {
      const report = computeCalibration(
        [candidate({ marketId: 'A', status: 'WATCH' })],
        [resolution('A', true)],
      );
      expect(report.fills).toHaveLength(0);
      expect(report.totalPnl).toBe(0);
    });
  });

  it('labels the sample insufficient below the minimum, while still computing', () => {
    const report = computeCalibration(
      [candidate({ marketId: 'A' })],
      [resolution('A', true)],
    );
    expect(report.minSampleMet).toBe(false);
    expect(report.brierOurs).not.toBeNull();
    expect(report.detail).toContain(String(MIN_CALIBRATION_SAMPLE));
  });

  it('declares the sample sufficient at the threshold', () => {
    const candidates = Array.from({ length: MIN_CALIBRATION_SAMPLE }, (_, i) =>
      candidate({ id: `c${i}`, marketId: `M${i}`, fairProbability: 0.6 }),
    );
    const resolutions = candidates.map((c) => resolution(c.marketId, true));
    const report = computeCalibration(candidates, resolutions);
    expect(report.n).toBe(MIN_CALIBRATION_SAMPLE);
    expect(report.minSampleMet).toBe(true);
  });

  it('handles the empty store without inventing numbers', () => {
    const report = computeCalibration([], []);
    expect(report.n).toBe(0);
    expect(report.brierOurs).toBeNull();
    expect(report.brierMarket).toBeNull();
    expect(report.brierEdge).toBeNull();
    expect(report.buckets).toEqual([]);
    expect(report.totalPnl).toBe(0);
  });
});
