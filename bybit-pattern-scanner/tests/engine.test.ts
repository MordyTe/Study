import { describe, expect, it } from 'vitest';
import { buildIndicatorSnapshot } from '@/lib/patterns/indicators-snapshot';
import { scoreCandidate } from '@/lib/engine/scoring';
import {
  buildFingerprint,
  computeExpiry,
  evaluateLifecycle,
  fingerprintToId,
  type Opportunity,
} from '@/lib/engine/opportunity';
import { checkCandleIntegrity, reconcile, isVerifiedForConfirmation, buildVerificationRecord } from '@/lib/engine/verification';
import { rankTier1 } from '@/lib/engine/scanner';
import { DEFAULT_SETTINGS, isQuietHour, mergeSettings, settingsSchema } from '@/lib/config/settings';
import { MemoryStore } from '@/lib/store';
import { escapeMarkdown, formatOpportunityMessage } from '@/lib/telegram/client';
import type { Candle, Instrument, Ticker } from '@/lib/bybit/types';
import type { MarketContext, PatternCandidate } from '@/lib/patterns/types';
import { makeCandle, uptrendSeries } from './fixtures';

const ctx: MarketContext = {
  instrumentId: 'linear:TESTUSDT',
  category: 'linear',
  symbol: 'TESTUSDT',
  timeframe: '1h',
  tickSize: 0.01,
  turnover24h: 50_000_000,
  spreadBps: 3,
  fundingRate: 0.0001,
  openInterestChangePct: 2,
  higherTimeframeBias: 'uptrend',
  launchTime: null,
};

function candidate(overrides: Partial<PatternCandidate> = {}): PatternCandidate {
  return {
    detectorName: 'test_detector',
    detectorVersion: '1.0.0',
    displayName: 'Test Pattern',
    direction: 'long',
    geometryQuality: 0.8,
    confirmationIndex: 219,
    confirmationTime: Date.now() - 60_000,
    entryZone: { from: 100, to: 101 },
    invalidation: 96,
    targets: [
      { price: 110, method: 'Measured move' },
      { price: 120, method: 'ATR extension' },
    ],
    overlays: [{ type: 'horizontal_line', price: 100, label: 'Level', color: 'bull' }],
    reasonsFor: ['Test reason for'],
    reasonsAgainst: ['Test reason against'],
    parameters: { testParam: 1 },
    evidence: {},
    ...overrides,
  };
}

describe('scoring', () => {
  const candles = uptrendSeries(220);
  const ind = buildIndicatorSnapshot(candles);

  it('produces a total inside 0..100 with all seven components', () => {
    const result = scoreCandidate(candidate(), ind, ctx, DEFAULT_SETTINGS, {
      verified: true,
      ageMs: 1000,
      reconciled: true,
    });

    expect(result.total).toBeGreaterThanOrEqual(0);
    expect(result.total).toBeLessThanOrEqual(100);
    expect(result.components).toHaveLength(7);

    const maxSum = result.components.reduce((a, c) => a + c.max, 0);
    expect(maxSum).toBe(100);

    for (const c of result.components) {
      expect(c.value).toBeGreaterThanOrEqual(0);
      expect(c.value).toBeLessThanOrEqual(c.max);
      expect(c.detail.length).toBeGreaterThan(10);
    }
  });

  it('scores a higher-timeframe-aligned setup above a conflicting one', () => {
    const aligned = scoreCandidate(candidate(), ind, { ...ctx, higherTimeframeBias: 'uptrend' }, DEFAULT_SETTINGS, {
      verified: true,
      ageMs: 0,
      reconciled: true,
    });
    const conflicting = scoreCandidate(candidate(), ind, { ...ctx, higherTimeframeBias: 'downtrend' }, DEFAULT_SETTINGS, {
      verified: true,
      ageMs: 0,
      reconciled: true,
    });
    expect(aligned.total).toBeGreaterThan(conflicting.total);
  });

  it('penalises thin turnover', () => {
    const thin = scoreCandidate(candidate(), ind, { ...ctx, turnover24h: 100_000 }, DEFAULT_SETTINGS, {
      verified: true,
      ageMs: 0,
      reconciled: true,
    });
    expect(thin.penalties.some((p) => p.key === 'thin_turnover')).toBe(true);
  });

  it('penalises poor reward-to-risk', () => {
    const poor = scoreCandidate(
      candidate({ targets: [{ price: 102, method: 'tiny' }] }),
      ind,
      ctx,
      DEFAULT_SETTINGS,
      { verified: true, ageMs: 0, reconciled: true },
    );
    expect(poor.penalties.some((p) => p.key === 'poor_asymmetry')).toBe(true);
  });

  it('awards fewer data-quality points when verification is incomplete', () => {
    const good = scoreCandidate(candidate(), ind, ctx, DEFAULT_SETTINGS, { verified: true, ageMs: 0, reconciled: true });
    const bad = scoreCandidate(candidate(), ind, ctx, DEFAULT_SETTINGS, {
      verified: false,
      ageMs: 999_999_999,
      reconciled: false,
    });
    const goodData = good.components.find((c) => c.key === 'dataQuality')!.value;
    const badData = bad.components.find((c) => c.key === 'dataQuality')!.value;
    expect(goodData).toBeGreaterThan(badData);
    expect(badData).toBe(0);
  });
});

describe('fingerprinting and de-duplication', () => {
  const base = {
    category: 'linear' as const,
    symbol: 'BTCUSDT',
    timeframe: '1h' as const,
    detectorName: 'breakout_retest',
    detectorVersion: '1.0.0',
    direction: 'long' as const,
    confirmationTime: 1_700_000_000_000,
  };

  it('is stable for identical geometry', () => {
    expect(buildFingerprint(base)).toBe(buildFingerprint({ ...base }));
    expect(fingerprintToId(buildFingerprint(base))).toBe(fingerprintToId(buildFingerprint(base)));
  });

  it('differs across market category for the same symbol', () => {
    expect(buildFingerprint(base)).not.toBe(buildFingerprint({ ...base, category: 'spot' }));
  });

  it('differs across direction, timeframe, detector version and confirmation bar', () => {
    expect(buildFingerprint(base)).not.toBe(buildFingerprint({ ...base, direction: 'short' }));
    expect(buildFingerprint(base)).not.toBe(buildFingerprint({ ...base, timeframe: '4h' }));
    expect(buildFingerprint(base)).not.toBe(buildFingerprint({ ...base, detectorVersion: '1.1.0' }));
    expect(buildFingerprint(base)).not.toBe(buildFingerprint({ ...base, confirmationTime: 1_700_000_003_600 }));
  });

  it('produces short, url-safe ids', () => {
    const id = fingerprintToId(buildFingerprint(base));
    expect(id).toMatch(/^[a-z0-9]+$/);
    expect(id.length).toBeLessThanOrEqual(12);
  });
});

describe('opportunity lifecycle', () => {
  function opportunity(overrides: Partial<Opportunity> = {}): Opportunity {
    const fingerprint = buildFingerprint({
      category: 'linear',
      symbol: 'BTCUSDT',
      timeframe: '1h',
      detectorName: 'test',
      detectorVersion: '1.0.0',
      direction: 'long',
      confirmationTime: 1000,
    });
    return {
      id: fingerprintToId(fingerprint),
      fingerprint,
      instrumentId: 'linear:BTCUSDT',
      category: 'linear',
      symbol: 'BTCUSDT',
      timeframe: '1h',
      detectorName: 'test',
      detectorVersion: '1.0.0',
      patternDisplayName: 'Test',
      direction: 'long',
      status: 'CONFIRMED',
      score: 80,
      scoreComponents: [],
      scorePenalties: [],
      rewardToRisk: 3,
      lastPrice: 100,
      entryZone: { from: 99, to: 101 },
      invalidation: 95,
      targets: [
        { price: 110, method: 'T1', reached: false },
        { price: 120, method: 'T2', reached: false },
      ],
      overlays: [],
      reasonsFor: [],
      reasonsAgainst: [],
      parameters: {},
      evidence: {},
      verification: {
        id: 'dvr_test',
        source: 'Bybit V5 Official',
        exchangeTimestamp: Date.now(),
        localTimestamp: Date.now(),
        clockDriftMs: 10,
        dataAgeMs: 1000,
        restLatencyMs: 50,
        reconciliationPassed: true,
        reconciliationDeltaPct: 0.01,
        candleGapsDetected: 0,
        health: 'HEALTHY',
        notes: [],
      },
      detectedAt: Date.now(),
      confirmationTime: 1000,
      updatedAt: Date.now(),
      expiresAt: Date.now() + 86_400_000,
      entryZoneTouched: false,
      maxFavorableExcursionPct: 0,
      maxAdverseExcursionPct: 0,
      alertSent: false,
      events: [],
      ...overrides,
    };
  }

  it('marks the entry zone as touched when price enters it', () => {
    const advanced = evaluateLifecycle(opportunity(), 100);
    expect(advanced.entryZoneTouched).toBe(true);
    expect(advanced.events.some((e) => e.type === 'ENTRY_ZONE_TOUCHED')).toBe(true);
  });

  it('invalidates when price breaches the stop level', () => {
    const advanced = evaluateLifecycle(opportunity(), 94);
    expect(advanced.status).toBe('INVALIDATED');
  });

  it('records target 1 then target 2', () => {
    const t1 = evaluateLifecycle(opportunity(), 111);
    expect(t1.status).toBe('TARGET_1_REACHED');
    expect(t1.targets[0]!.reached).toBe(true);

    const t2 = evaluateLifecycle(t1, 121);
    expect(t2.targets[1]!.reached).toBe(true);
    expect(t2.status).toBe('CLOSED_TRACKING');
  });

  it('expires when the window elapses without resolution', () => {
    const advanced = evaluateLifecycle(opportunity({ expiresAt: Date.now() - 1000 }), 100);
    expect(advanced.status).toBe('EXPIRED');
  });

  it('is terminal — a resolved opportunity is never reopened', () => {
    const invalidated = evaluateLifecycle(opportunity(), 90);
    expect(invalidated.status).toBe('INVALIDATED');
    const again = evaluateLifecycle(invalidated, 150);
    expect(again.status).toBe('INVALIDATED');
    expect(again).toBe(invalidated); // untouched
  });

  it('tracks maximum favorable and adverse excursion', () => {
    let opp = evaluateLifecycle(opportunity(), 105);
    opp = evaluateLifecycle(opp, 97);
    expect(opp.maxFavorableExcursionPct).toBeGreaterThan(0);
    expect(opp.maxAdverseExcursionPct).toBeGreaterThan(0);
  });

  it('computes expiry from the confirmation bar', () => {
    expect(computeExpiry(1000, 3_600_000)).toBe(1000 + 3_600_000 * 24);
  });
});

describe('candle integrity and reconciliation', () => {
  it('accepts a well-formed aligned series', () => {
    const result = checkCandleIntegrity(uptrendSeries(50), '1h');
    expect(result.valid).toBe(true);
    expect(result.gaps).toBe(0);
  });

  it('detects OHLC ordering violations', () => {
    const bad = [makeCandle(0, 100, 90, 110, 105)]; // high < low
    expect(checkCandleIntegrity(bad, '1h').valid).toBe(false);
  });

  it('detects gaps in the series', () => {
    const candles = uptrendSeries(20);
    const withGap = [...candles.slice(0, 10), ...candles.slice(13)];
    expect(checkCandleIntegrity(withGap, '1h').gaps).toBeGreaterThan(0);
  });

  it('rejects an empty series', () => {
    expect(checkCandleIntegrity([], '1h').valid).toBe(false);
  });

  it('passes reconciliation when the ticker is close to the last close', () => {
    const candles = uptrendSeries(30);
    const last = candles[candles.length - 1]!;
    const series = {
      instrumentId: 'linear:TESTUSDT',
      category: 'linear' as const,
      symbol: 'TESTUSDT',
      timeframe: '1h' as const,
      candles,
      includesOpen: false,
      fetchedAt: Date.now(),
    };
    const ticker = { lastPrice: last.close * 1.0005 } as Ticker;
    expect(reconcile(series, ticker, 0.5).passed).toBe(true);
  });

  it('fails reconciliation on a large divergence', () => {
    const candles = uptrendSeries(30);
    const last = candles[candles.length - 1]!;
    const series = {
      instrumentId: 'linear:TESTUSDT',
      category: 'linear' as const,
      symbol: 'TESTUSDT',
      timeframe: '1h' as const,
      candles,
      includesOpen: false,
      fetchedAt: Date.now(),
    };
    const ticker = { lastPrice: last.close * 1.5 } as Ticker;
    expect(reconcile(series, ticker, 0.5).passed).toBe(false);
  });

  it('withholds confirmation when the verification record is not fully healthy', () => {
    const base = {
      id: 'dvr',
      source: 'Bybit V5 Official' as const,
      exchangeTimestamp: Date.now(),
      localTimestamp: Date.now(),
      clockDriftMs: 10,
      dataAgeMs: 1000,
      restLatencyMs: 40,
      reconciliationPassed: true,
      reconciliationDeltaPct: 0.01,
      candleGapsDetected: 0,
      health: 'HEALTHY' as const,
      notes: [],
    };
    expect(isVerifiedForConfirmation(base, DEFAULT_SETTINGS)).toBe(true);
    expect(isVerifiedForConfirmation({ ...base, health: 'DEGRADED' }, DEFAULT_SETTINGS)).toBe(false);
    expect(isVerifiedForConfirmation({ ...base, reconciliationPassed: false }, DEFAULT_SETTINGS)).toBe(false);
    expect(isVerifiedForConfirmation({ ...base, candleGapsDetected: 2 }, DEFAULT_SETTINGS)).toBe(false);
    expect(isVerifiedForConfirmation({ ...base, clockDriftMs: 999_999 }, DEFAULT_SETTINGS)).toBe(false);
  });

  it('builds a complete verification record', () => {
    const candles = uptrendSeries(40);
    const record = buildVerificationRecord({
      series: {
        instrumentId: 'linear:TESTUSDT',
        category: 'linear',
        symbol: 'TESTUSDT',
        timeframe: '1h',
        candles,
        includesOpen: false,
        fetchedAt: Date.now(),
      },
      ticker: { lastPrice: candles[candles.length - 1]!.close } as Ticker,
      serverTimeMs: Date.now(),
      restLatencyMs: 42,
      settings: DEFAULT_SETTINGS,
    });
    expect(record.source).toBe('Bybit V5 Official');
    expect(record.id).toContain('dvr_');
    expect(['HEALTHY', 'DEGRADED', 'STALE']).toContain(record.health);
  });
});

describe('tier 1 ranking', () => {
  const instrument = (symbol: string, category: 'spot' | 'linear' = 'linear'): Instrument => ({
    id: `${category}:${symbol}`,
    category,
    symbol,
    baseCoin: symbol.replace('USDT', ''),
    quoteCoin: 'USDT',
    status: 'Trading',
    contractType: category === 'linear' ? 'LinearPerpetual' : null,
    settleCoin: category === 'linear' ? 'USDT' : null,
    launchTime: Date.now() - 365 * 86_400_000,
    tickSize: 0.01,
    qtyStep: 0.001,
    active: true,
  });

  const ticker = (symbol: string, overrides: Partial<Ticker> = {}): Ticker => ({
    id: `linear:${symbol}`,
    category: 'linear',
    symbol,
    lastPrice: 100,
    prevPrice24h: 98,
    price24hPcnt: 0.02,
    highPrice24h: 105,
    lowPrice24h: 95,
    turnover24h: 50_000_000,
    volume24h: 500_000,
    bid1Price: 99.99,
    ask1Price: 100.01,
    markPrice: 100,
    indexPrice: 100,
    openInterest: 1_000_000,
    fundingRate: 0.0001,
    nextFundingTime: Date.now() + 3_600_000,
    spreadBps: 2,
    ...overrides,
  });

  it('excludes instruments below the turnover floor', () => {
    const ranked = rankTier1(
      [instrument('LOWUSDT'), instrument('HIGHUSDT')],
      [ticker('LOWUSDT', { id: 'linear:LOWUSDT', turnover24h: 1000 }), ticker('HIGHUSDT', { id: 'linear:HIGHUSDT' })],
      DEFAULT_SETTINGS,
    );
    expect(ranked.map((r) => r.instrument.symbol)).toEqual(['HIGHUSDT']);
  });

  it('excludes instruments with an excessive spread', () => {
    const ranked = rankTier1(
      [instrument('WIDEUSDT')],
      [ticker('WIDEUSDT', { id: 'linear:WIDEUSDT', spreadBps: 500 })],
      DEFAULT_SETTINGS,
    );
    expect(ranked).toHaveLength(0);
  });

  it('excludes muted symbols', () => {
    const ranked = rankTier1(
      [instrument('MUTEDUSDT')],
      [ticker('MUTEDUSDT', { id: 'linear:MUTEDUSDT' })],
      { ...DEFAULT_SETTINGS, mutedSymbols: ['MUTEDUSDT'] },
    );
    expect(ranked).toHaveLength(0);
  });

  it('excludes instruments that are too newly listed', () => {
    const fresh = { ...instrument('NEWUSDT'), launchTime: Date.now() - 86_400_000 };
    const ranked = rankTier1([fresh], [ticker('NEWUSDT', { id: 'linear:NEWUSDT' })], DEFAULT_SETTINGS);
    expect(ranked).toHaveLength(0);
  });

  it('ranks a volatile instrument at a range extreme above a quiet one', () => {
    const ranked = rankTier1(
      [instrument('CALMUSDT'), instrument('HOTUSDT')],
      [
        ticker('CALMUSDT', { id: 'linear:CALMUSDT', highPrice24h: 100.5, lowPrice24h: 99.5, price24hPcnt: 0.001, lastPrice: 100 }),
        ticker('HOTUSDT', { id: 'linear:HOTUSDT', highPrice24h: 120, lowPrice24h: 100, lastPrice: 119.5, price24hPcnt: 0.18 }),
      ],
      DEFAULT_SETTINGS,
    );
    expect(ranked[0]!.instrument.symbol).toBe('HOTUSDT');
    expect(ranked[0]!.reasons.length).toBeGreaterThan(0);
  });

  it('is sorted by descending energy', () => {
    const ranked = rankTier1(
      [instrument('AUSDT'), instrument('BUSDT'), instrument('CUSDT')],
      [
        ticker('AUSDT', { id: 'linear:AUSDT', turnover24h: 10_000_000 }),
        ticker('BUSDT', { id: 'linear:BUSDT', turnover24h: 900_000_000 }),
        ticker('CUSDT', { id: 'linear:CUSDT', turnover24h: 100_000_000 }),
      ],
      DEFAULT_SETTINGS,
    );
    for (let i = 1; i < ranked.length; i++) {
      expect(ranked[i - 1]!.energy).toBeGreaterThanOrEqual(ranked[i]!.energy);
    }
  });
});

describe('settings', () => {
  it('validates the defaults against the schema', () => {
    expect(settingsSchema.safeParse(DEFAULT_SETTINGS).success).toBe(true);
  });

  it('has 5m disabled by default to control noise', () => {
    expect(DEFAULT_SETTINGS.timeframes).not.toContain('5m');
  });

  it('merges partial input over the defaults and ignores garbage', () => {
    expect(mergeSettings({ confirmedThreshold: 90 }).confirmedThreshold).toBe(90);
    expect(mergeSettings({ confirmedThreshold: 90 }).watchThreshold).toBe(DEFAULT_SETTINGS.watchThreshold);
    expect(mergeSettings(null)).toEqual(DEFAULT_SETTINGS);
    expect(mergeSettings('nonsense')).toEqual(DEFAULT_SETTINGS);
  });

  it('caps the hypothetical risk planner at 2 percent', () => {
    expect(settingsSchema.safeParse({ ...DEFAULT_SETTINGS, plannerRiskPct: 5 }).success).toBe(false);
  });

  it('evaluates quiet hours across a midnight-spanning window', () => {
    const settings = {
      ...DEFAULT_SETTINGS,
      quietHoursEnabled: true,
      quietHoursStart: 23,
      quietHoursEnd: 6,
      quietHoursTimezone: 'UTC',
    };
    expect(isQuietHour(settings, new Date('2026-01-01T23:30:00Z'))).toBe(true);
    expect(isQuietHour(settings, new Date('2026-01-01T03:00:00Z'))).toBe(true);
    expect(isQuietHour(settings, new Date('2026-01-01T12:00:00Z'))).toBe(false);
    expect(isQuietHour({ ...settings, quietHoursEnabled: false }, new Date('2026-01-01T23:30:00Z'))).toBe(false);
  });
});

describe('memory store', () => {
  it('round-trips settings, opportunities, scans and deliveries', async () => {
    const store = new MemoryStore();

    await store.saveSettings({ ...DEFAULT_SETTINGS, confirmedThreshold: 88 });
    expect((await store.getSettings()).confirmedThreshold).toBe(88);

    const fingerprint = 'bybit|linear|BTCUSDT|1h|test|1.0.0|long|1000';
    const opp = { id: 'abc123', fingerprint, detectedAt: Date.now() } as Opportunity;
    await store.upsertOpportunity(opp);

    expect((await store.getOpportunity('abc123'))?.id).toBe('abc123');
    expect((await store.findByFingerprint(fingerprint))?.id).toBe('abc123');
    expect((await store.listOpportunities()).length).toBeGreaterThan(0);

    await store.recordScan({
      id: 'scan_1',
      startedAt: 1,
      finishedAt: 2,
      instrumentsScanned: 10,
      candidatesEvaluated: 5,
      confirmed: 1,
      forming: 2,
      alertsSent: 1,
      errors: [],
      durationMs: 1,
    });
    expect((await store.lastScan())?.id).toBe('scan_1');

    await store.recordDelivery({
      id: 'del_1',
      opportunityId: 'abc123',
      idempotencyKey: 'key_1',
      channel: 'telegram',
      status: 'sent',
      detail: 'ok',
      at: Date.now(),
    });
    expect(await store.hasDelivery('key_1')).toBe(true);
    expect(await store.hasDelivery('key_missing')).toBe(false);
  });
});

describe('telegram formatting', () => {
  it('escapes every MarkdownV2 reserved character', () => {
    const escaped = escapeMarkdown('BTC_USDT *test* [link](x) 1.5-2!');
    for (const ch of ['_', '*', '[', ']', '(', ')', '.', '-', '!']) {
      expect(escaped).toContain(`\\${ch}`);
    }
  });

  it('never advertises a trade action in the message body', () => {
    const opp = {
      symbol: 'BTCUSDT',
      category: 'linear',
      timeframe: '1h',
      direction: 'long',
      status: 'CONFIRMED',
      patternDisplayName: 'Breakout + Retest',
      score: 84,
      rewardToRisk: 3,
      entryZone: { from: 100, to: 101 },
      invalidation: 95,
      targets: [{ price: 110, method: 'Measured move', reached: false }],
      reasonsFor: ['Reason one'],
      reasonsAgainst: ['Risk one'],
      detectedAt: Date.now(),
      verification: { source: 'Bybit V5 Official', health: 'HEALTHY', exchangeTimestamp: Date.now() },
      id: 'abc',
    } as unknown as Opportunity;

    const message = formatOpportunityMessage(opp, DEFAULT_SETTINGS, 'https://example.com');
    expect(message).toContain('Analysis only');
    expect(message.toLowerCase()).not.toMatch(/\bbuy now\b|\bplace order\b|\bexecute trade\b/);
    expect(message).toContain('Possible entry zone');
    expect(message).toContain('Scenario invalidation');
  });
});
