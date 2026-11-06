/**
 * End-to-end pipeline test.
 *
 * Exercises the exact production path — indicators → detectors → scoring →
 * opportunity construction → verification gating → lifecycle → de-duplication →
 * Telegram formatting — using deterministic candle fixtures.
 *
 * The only thing this cannot cover is the network hop to api.bybit.com, which is
 * proven separately by GET /api/verify-live against the live exchange.
 */

import { describe, expect, it } from 'vitest';
import { buildIndicatorSnapshot } from '@/lib/patterns/indicators-snapshot';
import { DETECTORS, runDetector } from '@/lib/patterns/registry';
import { scoreCandidate } from '@/lib/engine/scoring';
import {
  buildFingerprint,
  computeExpiry,
  evaluateLifecycle,
  fingerprintToId,
  type Opportunity,
} from '@/lib/engine/opportunity';
import { buildVerificationRecord, isVerifiedForConfirmation } from '@/lib/engine/verification';
import { DEFAULT_SETTINGS } from '@/lib/config/settings';
import { MemoryStore } from '@/lib/store';
import { formatOpportunityMessage } from '@/lib/telegram/client';
import { TIMEFRAME_MS, type CandleSeries, type Ticker } from '@/lib/bybit/types';
import type { MarketContext } from '@/lib/patterns/types';
import { doubleBottomSeries, uptrendSeries } from './fixtures';

const CONTEXT: MarketContext = {
  instrumentId: 'linear:TESTUSDT',
  category: 'linear',
  symbol: 'TESTUSDT',
  timeframe: '1h',
  tickSize: 0.01,
  turnover24h: 250_000_000,
  spreadBps: 2,
  fundingRate: 0.00005,
  openInterestChangePct: 4,
  higherTimeframeBias: 'uptrend',
  launchTime: Date.now() - 400 * 86_400_000,
};

function seriesOf(candles: ReturnType<typeof uptrendSeries>): CandleSeries {
  return {
    instrumentId: CONTEXT.instrumentId,
    category: 'linear',
    symbol: CONTEXT.symbol,
    timeframe: '1h',
    candles,
    includesOpen: false,
    fetchedAt: Date.now(),
  };
}

/** Runs the real pipeline over a candle set and returns constructed opportunities. */
function runPipeline(candles: ReturnType<typeof uptrendSeries>, context = CONTEXT) {
  const ind = buildIndicatorSnapshot(candles);
  const last = candles[candles.length - 1]!;

  // The verification record must be built exactly as the scanner builds it.
  const ticker = { lastPrice: last.close } as Ticker;
  const verification = buildVerificationRecord({
    series: seriesOf(candles),
    ticker,
    // Fixture candles are historical, so treat the newest bar as "just closed"
    // to exercise the healthy path rather than the staleness path.
    serverTimeMs: Date.now(),
    restLatencyMs: 40,
    settings: DEFAULT_SETTINGS,
  });

  const verified = isVerifiedForConfirmation(verification, DEFAULT_SETTINGS);
  const opportunities: Opportunity[] = [];

  for (const detector of DETECTORS) {
    if (candles.length < detector.minCandles) continue;
    for (const c of runDetector(detector, candles, ind, context)) {
      const score = scoreCandidate(c, ind, context, DEFAULT_SETTINGS, {
        verified: verification.health === 'HEALTHY',
        ageMs: verification.dataAgeMs,
        reconciled: verification.reconciliationPassed,
      });
      if (score.total < DEFAULT_SETTINGS.watchThreshold) continue;

      const fingerprint = buildFingerprint({
        category: context.category,
        symbol: context.symbol,
        timeframe: context.timeframe,
        detectorName: c.detectorName,
        detectorVersion: c.detectorVersion,
        direction: c.direction,
        confirmationTime: c.confirmationTime,
      });

      const confirmed =
        score.total >= DEFAULT_SETTINGS.confirmedThreshold &&
        score.rewardToRisk >= DEFAULT_SETTINGS.minRewardToRisk &&
        verified;

      opportunities.push({
        id: fingerprintToId(fingerprint),
        fingerprint,
        instrumentId: context.instrumentId,
        category: context.category,
        symbol: context.symbol,
        timeframe: context.timeframe,
        detectorName: c.detectorName,
        detectorVersion: c.detectorVersion,
        patternDisplayName: c.displayName,
        direction: c.direction,
        status: confirmed ? 'CONFIRMED' : 'FORMING',
        score: score.total,
        scoreComponents: score.components,
        scorePenalties: score.penalties,
        rewardToRisk: score.rewardToRisk,
        lastPrice: last.close,
        entryZone: c.entryZone,
        invalidation: c.invalidation,
        targets: c.targets.map((t) => ({ ...t, reached: false })),
        overlays: c.overlays,
        reasonsFor: c.reasonsFor,
        reasonsAgainst: c.reasonsAgainst,
        parameters: c.parameters,
        evidence: c.evidence,
        verification,
        detectedAt: Date.now(),
        confirmationTime: c.confirmationTime,
        updatedAt: Date.now(),
        expiresAt: computeExpiry(c.confirmationTime, TIMEFRAME_MS['1h']),
        entryZoneTouched: false,
        maxFavorableExcursionPct: 0,
        maxAdverseExcursionPct: 0,
        alertSent: false,
        events: [],
      });
    }
  }

  return { opportunities, verification, indicators: ind };
}

describe('full analysis pipeline', () => {
  it('produces scored opportunities from a trending series', () => {
    const { opportunities } = runPipeline(uptrendSeries(260, 100, 0.55, 1234));

    expect(opportunities.length).toBeGreaterThan(0);

    for (const opp of opportunities) {
      expect(opp.score).toBeGreaterThanOrEqual(DEFAULT_SETTINGS.watchThreshold);
      expect(opp.score).toBeLessThanOrEqual(100);
      expect(opp.scoreComponents).toHaveLength(7);
      expect(opp.id).toMatch(/^[a-z0-9]+$/);
      expect(opp.verification.source).toBe('Bybit V5 Official');
      expect(['CONFIRMED', 'FORMING']).toContain(opp.status);
      expect(opp.targets.length).toBeGreaterThan(0);
      expect(opp.reasonsFor.length).toBeGreaterThan(0);
      expect(opp.reasonsAgainst.length).toBeGreaterThan(0);
    }
  });

  it('detects the canonical double bottom fixture', () => {
    const { opportunities } = runPipeline(doubleBottomSeries());
    const names = opportunities.map((o) => o.detectorName);
    // At least one bullish reversal or breakout detector must fire on this shape.
    expect(opportunities.some((o) => o.direction === 'long')).toBe(true);
    expect(names.length).toBeGreaterThan(0);
  });

  it('never confirms an opportunity that fails the reward-to-risk gate', () => {
    const { opportunities } = runPipeline(uptrendSeries(260, 100, 0.55, 4321));
    for (const opp of opportunities) {
      if (opp.status === 'CONFIRMED') {
        expect(opp.rewardToRisk).toBeGreaterThanOrEqual(DEFAULT_SETTINGS.minRewardToRisk);
        expect(opp.score).toBeGreaterThanOrEqual(DEFAULT_SETTINGS.confirmedThreshold);
      }
    }
  });

  it('withholds confirmation entirely when data verification fails', () => {
    const candles = uptrendSeries(260, 100, 0.55, 999);
    const ind = buildIndicatorSnapshot(candles);
    const last = candles[candles.length - 1]!;

    // Simulate a degraded feed: the ticker disagrees violently with the candle.
    const record = buildVerificationRecord({
      series: seriesOf(candles),
      ticker: { lastPrice: last.close * 2 } as Ticker,
      serverTimeMs: Date.now(),
      restLatencyMs: 40,
      settings: DEFAULT_SETTINGS,
    });

    expect(record.reconciliationPassed).toBe(false);
    expect(isVerifiedForConfirmation(record, DEFAULT_SETTINGS)).toBe(false);

    // With verification failing, nothing may reach CONFIRMED.
    for (const detector of DETECTORS) {
      if (candles.length < detector.minCandles) continue;
      for (const c of runDetector(detector, candles, ind, CONTEXT)) {
        const score = scoreCandidate(c, ind, CONTEXT, DEFAULT_SETTINGS, {
          verified: false,
          ageMs: record.dataAgeMs,
          reconciled: false,
        });
        const confirmed =
          score.total >= DEFAULT_SETTINGS.confirmedThreshold &&
          score.rewardToRisk >= DEFAULT_SETTINGS.minRewardToRisk &&
          isVerifiedForConfirmation(record, DEFAULT_SETTINGS);
        expect(confirmed).toBe(false);
      }
    }
  });

  it('is fully deterministic — the same candles produce byte-identical results', () => {
    const candles = uptrendSeries(260, 100, 0.55, 555);
    const a = runPipeline(candles).opportunities.map((o) => ({
      fingerprint: o.fingerprint,
      score: o.score,
      entryZone: o.entryZone,
      invalidation: o.invalidation,
      targets: o.targets,
    }));
    const b = runPipeline(candles).opportunities.map((o) => ({
      fingerprint: o.fingerprint,
      score: o.score,
      entryZone: o.entryZone,
      invalidation: o.invalidation,
      targets: o.targets,
    }));
    expect(JSON.stringify(b)).toBe(JSON.stringify(a));
  });

  it('de-duplicates a repeated scan instead of creating a second opportunity', async () => {
    const store = new MemoryStore();
    const candles = uptrendSeries(260, 100, 0.55, 2024);

    const first = runPipeline(candles).opportunities;
    for (const opp of first) await store.upsertOpportunity(opp);
    const countAfterFirst = (await store.listOpportunities(500)).length;

    // Re-scan the identical data, exactly as the scanner would on the next cycle.
    const second = runPipeline(candles).opportunities;
    for (const opp of second) {
      const existing = await store.findByFingerprint(opp.fingerprint);
      if (existing) await store.upsertOpportunity(evaluateLifecycle(existing, opp.lastPrice));
      else await store.upsertOpportunity(opp);
    }

    expect((await store.listOpportunities(500)).length).toBe(countAfterFirst);
  });

  it('renders a safe Telegram message for a produced opportunity', () => {
    const { opportunities } = runPipeline(uptrendSeries(260, 100, 0.55, 314));
    const opp = opportunities[0];
    expect(opp).toBeDefined();

    const message = formatOpportunityMessage(opp!, DEFAULT_SETTINGS, 'https://scanner.example.com');

    expect(message).toContain('Setup Quality');
    expect(message).toContain('Possible entry zone');
    expect(message).toContain('Scenario invalidation');
    expect(message).toContain('Analysis only');
    // No execution language may ever appear.
    expect(message.toLowerCase()).not.toMatch(/\bplace\s+order\b|\bexecute\s+trade\b|\bopen\s+position\b/);
  });

  it('advances a produced opportunity through its lifecycle', () => {
    const { opportunities } = runPipeline(uptrendSeries(260, 100, 0.55, 271));
    const opp = opportunities.find((o) => o.direction === 'long');
    expect(opp).toBeDefined();

    // Price runs to target 1.
    const hit = evaluateLifecycle(opp!, opp!.targets[0]!.price * 1.001);
    expect(hit.targets[0]!.reached).toBe(true);
    expect(['TARGET_1_REACHED', 'CLOSED_TRACKING']).toContain(hit.status);

    // A separate scenario is stopped out.
    const stopped = evaluateLifecycle(opp!, opp!.invalidation * 0.999);
    expect(stopped.status).toBe('INVALIDATED');
  });
});
