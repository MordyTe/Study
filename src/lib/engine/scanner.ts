/**
 * The scan engine — tiered market analysis over the full Bybit USDT universe.
 *
 * Tier 1  Cheap full-universe pass: one tickers call per category ranks every
 *         eligible instrument by liquidity, volatility and momentum energy.
 * Tier 2  The top N candidates get real candle history, the full indicator
 *         snapshot, every pattern detector, and REST reconciliation.
 * Tier 3  Confirmed opportunities are persisted, scored, tracked, and alerted.
 *
 * Determinism: given the same candles and settings, the same opportunities are
 * produced. Nothing here depends on wall-clock beyond staleness checks.
 */

import {
  getInstruments,
  getKlines,
  getOpenInterest,
  getServerTime,
  getTickers,
} from '@/lib/bybit/client';
import {
  TIMEFRAME_MS,
  type Instrument,
  type MarketCategory,
  type Ticker,
  type Timeframe,
} from '@/lib/bybit/types';
import { buildIndicatorSnapshot } from '@/lib/patterns/indicators-snapshot';
import { DETECTORS, runAllDetectors } from '@/lib/patterns/registry';
import type { MarketContext, PatternCandidate } from '@/lib/patterns/types';
import { isQuietHour, type Settings } from '@/lib/config/settings';
import { scoreCandidate } from './scoring';
import {
  buildFingerprint,
  computeExpiry,
  evaluateLifecycle,
  fingerprintToId,
  type Opportunity,
} from './opportunity';
import { buildVerificationRecord, isVerifiedForConfirmation } from './verification';
import type { ScanRecord, Store } from '@/lib/store';

export interface Tier1Candidate {
  instrument: Instrument;
  ticker: Ticker;
  /** Composite ranking energy — higher means more worth a full analysis pass. */
  energy: number;
  reasons: string[];
}

/** Instrument-level universe cache; instruments change slowly. */
interface UniverseCache {
  instruments: Instrument[];
  fetchedAt: number;
}
const UNIVERSE_TTL_MS = 60 * 60_000;
const universeCacheKey = '__bybit_universe_cache__';
type GlobalWithUniverse = typeof globalThis & { [universeCacheKey]?: Map<MarketCategory, UniverseCache> };

function universeCache(): Map<MarketCategory, UniverseCache> {
  const g = globalThis as GlobalWithUniverse;
  if (!g[universeCacheKey]) g[universeCacheKey] = new Map();
  return g[universeCacheKey]!;
}

export async function getUniverse(category: MarketCategory, force = false): Promise<Instrument[]> {
  const cache = universeCache();
  const hit = cache.get(category);
  if (!force && hit && Date.now() - hit.fetchedAt < UNIVERSE_TTL_MS) return hit.instruments;

  const instruments = await getInstruments(category);
  cache.set(category, { instruments, fetchedAt: Date.now() });
  return instruments;
}

/**
 * Tier 1 — rank the entire eligible universe using only ticker data.
 * One REST call per category covers hundreds of instruments.
 */
export function rankTier1(
  instruments: Instrument[],
  tickers: Ticker[],
  settings: Settings,
): Tier1Candidate[] {
  const byId = new Map(instruments.map((i) => [i.id, i]));
  const out: Tier1Candidate[] = [];
  const now = Date.now();

  for (const ticker of tickers) {
    const instrument = byId.get(ticker.id);
    if (!instrument || !instrument.active) continue;
    if (settings.mutedSymbols.includes(instrument.symbol)) continue;
    if (ticker.turnover24h < settings.minTurnover24h) continue;
    if (ticker.spreadBps !== null && ticker.spreadBps > settings.maxSpreadBps) continue;

    if (instrument.launchTime) {
      const ageDays = (now - instrument.launchTime) / 86_400_000;
      if (ageDays < settings.minInstrumentAgeDays) continue;
    }

    const reasons: string[] = [];

    // Liquidity: log-scaled so a $2B pair does not drown out a healthy $20M pair.
    const liquidity = Math.min(1, Math.log10(Math.max(1, ticker.turnover24h) / 1_000_000) / 3);

    // Daily range as a proxy for realized volatility.
    const range =
      ticker.lastPrice > 0 ? (ticker.highPrice24h - ticker.lowPrice24h) / ticker.lastPrice : 0;
    const volatility = Math.min(1, range / 0.12);
    if (range > 0.06) reasons.push(`24h range ${(range * 100).toFixed(1)}%`);

    // Directional displacement — where in the daily range price is sitting.
    const dayRange = ticker.highPrice24h - ticker.lowPrice24h;
    const position = dayRange > 0 ? (ticker.lastPrice - ticker.lowPrice24h) / dayRange : 0.5;
    // Energy is highest at range extremes (breakout / rejection territory).
    const extremity = Math.abs(position - 0.5) * 2;
    if (extremity > 0.7) {
      reasons.push(position > 0.5 ? 'trading near 24h high' : 'trading near 24h low');
    }

    const momentum = Math.min(1, Math.abs(ticker.price24hPcnt) / 0.15);
    if (Math.abs(ticker.price24hPcnt) > 0.05) {
      reasons.push(`${(ticker.price24hPcnt * 100).toFixed(1)}% 24h move`);
    }

    // Crowded funding on perps is genuine squeeze information.
    let fundingEnergy = 0;
    if (ticker.fundingRate !== null && Math.abs(ticker.fundingRate) > 0.0003) {
      fundingEnergy = Math.min(1, Math.abs(ticker.fundingRate) / 0.001);
      reasons.push(`funding ${(ticker.fundingRate * 100).toFixed(4)}%`);
    }

    const energy =
      liquidity * 0.3 + volatility * 0.25 + extremity * 0.2 + momentum * 0.15 + fundingEnergy * 0.1;

    out.push({ instrument, ticker, energy: Number(energy.toFixed(4)), reasons });
  }

  return out.sort((a, b) => b.energy - a.energy);
}

/** Higher-timeframe directional bias used as a scoring input. */
async function fetchHigherTimeframeBias(
  category: MarketCategory,
  symbol: string,
  contextTimeframe: Timeframe,
): Promise<'uptrend' | 'downtrend' | 'range' | null> {
  try {
    const series = await getKlines(category, symbol, contextTimeframe, 200);
    const closed = series.candles.slice(0, -1);
    if (closed.length < 60) return null;
    return buildIndicatorSnapshot(closed).structure.state;
  } catch {
    return null;
  }
}

export interface AnalyzeResult {
  candidates: PatternCandidate[];
  opportunities: Opportunity[];
  errors: string[];
}

/**
 * Tier 2/3 — full analysis of a single instrument/timeframe.
 * Only CLOSED candles are used, which is what makes CONFIRMED trustworthy.
 */
export async function analyzeInstrument(
  candidate: Tier1Candidate,
  timeframe: Timeframe,
  settings: Settings,
  serverTimeMs: number,
  higherTimeframeBias: 'uptrend' | 'downtrend' | 'range' | null,
): Promise<AnalyzeResult> {
  const errors: string[] = [];
  const { instrument, ticker } = candidate;

  const startedAt = Date.now();
  const series = await getKlines(instrument.category, instrument.symbol, timeframe, 300);
  const restLatencyMs = Date.now() - startedAt;

  // Drop the still-open candle. Detection runs on closed data only.
  const closed = series.candles.slice(0, -1);
  const minRequired = Math.max(...DETECTORS.map((d) => d.minCandles));
  if (closed.length < Math.min(minRequired, 100)) {
    return { candidates: [], opportunities: [], errors: [`${instrument.id} ${timeframe}: only ${closed.length} closed candles`] };
  }

  const closedSeries = { ...series, candles: closed, includesOpen: false };
  const verification = buildVerificationRecord({
    series: closedSeries,
    ticker,
    serverTimeMs,
    restLatencyMs,
    settings,
  });

  const indicators = buildIndicatorSnapshot(closed);

  // Open-interest trend adds derivatives context on perps.
  let openInterestChangePct: number | null = null;
  if (instrument.category === 'linear') {
    try {
      const oi = await getOpenInterest(instrument.symbol, '1h', 24);
      if (oi.length >= 2) {
        const first = oi[0]!.openInterest;
        const last = oi[oi.length - 1]!.openInterest;
        if (first > 0) openInterestChangePct = ((last - first) / first) * 100;
      }
    } catch {
      // Derivatives extras are optional — never fail the scan over them.
    }
  }

  const context: MarketContext = {
    instrumentId: instrument.id,
    category: instrument.category,
    symbol: instrument.symbol,
    timeframe,
    tickSize: instrument.tickSize,
    turnover24h: ticker.turnover24h,
    spreadBps: ticker.spreadBps,
    fundingRate: ticker.fundingRate,
    openInterestChangePct,
    higherTimeframeBias,
    launchTime: instrument.launchTime,
  };

  // runAllDetectors applies the shared target-normalization layer, so live
  // scanning and backtesting can never diverge in scenario arithmetic.
  const allCandidates: PatternCandidate[] = runAllDetectors(
    closed,
    indicators,
    context,
    settings.mutedDetectors,
  );

  const verified = isVerifiedForConfirmation(verification, settings);
  const now = Date.now();
  const opportunities: Opportunity[] = [];

  for (const c of allCandidates) {
    const score = scoreCandidate(c, indicators, context, settings, {
      verified: verification.health === 'HEALTHY',
      ageMs: verification.dataAgeMs,
      reconciled: verification.reconciliationPassed,
    });

    if (score.total < settings.watchThreshold) continue;

    const fingerprint = buildFingerprint({
      category: instrument.category,
      symbol: instrument.symbol,
      timeframe,
      detectorName: c.detectorName,
      detectorVersion: c.detectorVersion,
      direction: c.direction,
      confirmationTime: c.confirmationTime,
    });

    // CONFIRMED requires: score gate + R:R gate + verified closed data.
    const meetsConfirmed =
      score.total >= settings.confirmedThreshold &&
      score.rewardToRisk >= settings.minRewardToRisk &&
      verified;

    opportunities.push({
      id: fingerprintToId(fingerprint),
      fingerprint,
      instrumentId: instrument.id,
      category: instrument.category,
      symbol: instrument.symbol,
      timeframe,
      detectorName: c.detectorName,
      detectorVersion: c.detectorVersion,
      patternDisplayName: c.displayName,
      direction: c.direction,
      status: meetsConfirmed ? 'CONFIRMED' : 'FORMING',
      score: score.total,
      scoreComponents: score.components,
      scorePenalties: score.penalties,
      rewardToRisk: score.rewardToRisk,
      lastPrice: ticker.lastPrice,
      entryZone: c.entryZone,
      invalidation: c.invalidation,
      targets: c.targets.map((t) => ({ ...t, reached: false })),
      overlays: c.overlays,
      reasonsFor: c.reasonsFor,
      reasonsAgainst: c.reasonsAgainst,
      parameters: c.parameters,
      evidence: { ...c.evidence, openInterestChangePct, tier1Energy: candidate.energy },
      verification,
      detectedAt: now,
      confirmationTime: c.confirmationTime,
      updatedAt: now,
      expiresAt: computeExpiry(c.confirmationTime, TIMEFRAME_MS[timeframe]),
      entryZoneTouched: false,
      maxFavorableExcursionPct: 0,
      maxAdverseExcursionPct: 0,
      alertSent: false,
      events: [
        {
          at: now,
          type: meetsConfirmed ? 'CONFIRMED' : 'FORMING',
          detail: meetsConfirmed
            ? `Confirmed at score ${score.total} with R:R ${score.rewardToRisk} on verified closed candles.`
            : `Watch-level setup at score ${score.total}. ${verified ? '' : 'Data verification incomplete. '}Not alert-eligible.`,
        },
      ],
    });
  }

  return { candidates: allCandidates, opportunities, errors };
}

export interface ScanOptions {
  settings: Settings;
  store: Store;
  /** Cap on Tier-2 instruments this run — protects the serverless time budget. */
  maxCandidates?: number;
  /** Restrict to one symbol (used by the on-demand analyze endpoint). */
  onlySymbol?: string;
  onlyCategory?: MarketCategory;
  /** Wall-clock budget; the scan stops promoting new candidates when exceeded. */
  timeBudgetMs?: number;
  onAlert?: (opp: Opportunity) => Promise<void>;
}

export interface ScanOutcome {
  record: ScanRecord;
  opportunities: Opportunity[];
  tier1: Tier1Candidate[];
}

/** Full scan cycle: Tier 1 → Tier 2 → persist → lifecycle → alerts. */
export async function runScan(options: ScanOptions): Promise<ScanOutcome> {
  const { settings, store } = options;
  const startedAt = Date.now();
  const timeBudgetMs = options.timeBudgetMs ?? 45_000;
  const errors: string[] = [];

  const serverTime = await getServerTime();
  const serverTimeMs = serverTime.seconds * 1000;

  // ── Tier 1 ──────────────────────────────────────────────────────────────
  const categories = (options.onlyCategory ? [options.onlyCategory] : settings.markets) as MarketCategory[];
  let tier1: Tier1Candidate[] = [];

  for (const category of categories) {
    try {
      const [instruments, tickers] = await Promise.all([getUniverse(category), getTickers(category)]);
      tier1.push(...rankTier1(instruments, tickers, settings));
    } catch (err) {
      errors.push(`Tier 1 ${category}: ${(err as Error).message}`);
    }
  }
  tier1.sort((a, b) => b.energy - a.energy);

  if (options.onlySymbol) {
    tier1 = tier1.filter((c) => c.instrument.symbol === options.onlySymbol);
  }

  const instrumentsScanned = tier1.length;
  const maxCandidates = options.maxCandidates ?? settings.tier2Candidates;
  const promoted = tier1.slice(0, maxCandidates);

  // ── Tier 2 ──────────────────────────────────────────────────────────────
  const produced: Opportunity[] = [];
  let candidatesEvaluated = 0;

  // Higher-timeframe bias is fetched once per symbol and shared across timeframes.
  const biasCache = new Map<string, 'uptrend' | 'downtrend' | 'range' | null>();

  for (const candidate of promoted) {
    if (Date.now() - startedAt > timeBudgetMs) {
      errors.push(`Time budget reached after ${produced.length} results; remaining candidates deferred to the next scan.`);
      break;
    }

    const biasKey = candidate.instrument.id;
    if (!biasCache.has(biasKey)) {
      biasCache.set(
        biasKey,
        await fetchHigherTimeframeBias(
          candidate.instrument.category,
          candidate.instrument.symbol,
          settings.contextTimeframe,
        ),
      );
    }
    const bias = biasCache.get(biasKey) ?? null;

    for (const timeframe of settings.timeframes) {
      if (Date.now() - startedAt > timeBudgetMs) break;
      try {
        const result = await analyzeInstrument(candidate, timeframe, settings, serverTimeMs, bias);
        candidatesEvaluated += result.candidates.length;
        produced.push(...result.opportunities);
        errors.push(...result.errors);
      } catch (err) {
        errors.push(`${candidate.instrument.id} ${timeframe}: ${(err as Error).message}`);
      }
    }
  }

  // ── Tier 3 — de-duplicate, persist, alert ───────────────────────────────
  const now = Date.now();
  const cooldownMs = settings.cooldownMinutes * 60_000;
  const quiet = isQuietHour(settings, new Date(now));
  let alertsSent = 0;

  const ranked = produced.sort((a, b) => b.score - a.score).slice(0, settings.maxSignalsPerScan);

  for (const opp of ranked) {
    const existing = await store.findByFingerprint(opp.fingerprint);

    if (existing) {
      // Same geometry seen again — update in place rather than duplicating.
      const advanced = evaluateLifecycle({ ...existing, score: opp.score, scoreComponents: opp.scoreComponents }, opp.lastPrice, now);
      await store.upsertOpportunity(advanced);
      continue;
    }

    // Cooldown: suppress a fresh signal for the same symbol+detector+timeframe.
    const recent = await store.listOpportunities(200);
    const inCooldown = recent.some(
      (r) =>
        r.symbol === opp.symbol &&
        r.timeframe === opp.timeframe &&
        r.detectorName === opp.detectorName &&
        r.direction === opp.direction &&
        now - r.detectedAt < cooldownMs,
    );
    if (inCooldown) continue;

    await store.upsertOpportunity(opp);

    const alertEligible =
      opp.status === 'CONFIRMED' &&
      settings.telegramEnabled &&
      (!quiet || settings.criticalBypassQuietHours === false ? !quiet : false);

    if (opp.status === 'CONFIRMED' && settings.telegramEnabled && !quiet && options.onAlert) {
      try {
        await options.onAlert(opp);
        alertsSent += 1;
        await store.upsertOpportunity({ ...opp, alertSent: true });
      } catch (err) {
        errors.push(`Alert for ${opp.id}: ${(err as Error).message}`);
      }
    } else if (opp.status === 'CONFIRMED' && quiet) {
      errors.push(`Quiet hours active — ${opp.symbol} ${opp.timeframe} recorded without an alert.`);
    }
    void alertEligible;
  }

  // ── Lifecycle sweep over previously tracked opportunities ───────────────
  const tracked = await store.listOpportunities(150);
  const priceBySymbol = new Map(tier1.map((c) => [c.instrument.id, c.ticker.lastPrice]));
  for (const opp of tracked) {
    if (['INVALIDATED', 'EXPIRED', 'CLOSED_TRACKING'].includes(opp.status)) continue;
    const price = priceBySymbol.get(opp.instrumentId);
    if (price === undefined) continue;
    const advanced = evaluateLifecycle(opp, price, now);
    if (advanced.status !== opp.status || advanced.updatedAt !== opp.updatedAt) {
      await store.upsertOpportunity(advanced);
    }
  }

  const finishedAt = Date.now();
  const record: ScanRecord = {
    id: `scan_${startedAt}`,
    startedAt,
    finishedAt,
    instrumentsScanned,
    candidatesEvaluated,
    confirmed: ranked.filter((o) => o.status === 'CONFIRMED').length,
    forming: ranked.filter((o) => o.status === 'FORMING').length,
    alertsSent,
    durationMs: finishedAt - startedAt,
    errors: errors.slice(0, 25),
  };

  await store.recordScan(record);

  return { record, opportunities: ranked, tier1 };
}
