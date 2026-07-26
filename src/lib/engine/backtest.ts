/**
 * Backtester — evaluates SIGNALS, not executed user trades.
 *
 * Reuses the exact production detector and scoring code. There is deliberately
 * no separate "easy" backtest implementation, because a second implementation
 * would silently drift from live behaviour and make results meaningless.
 *
 * No-lookahead guarantee: at each step the detectors see only candles[0..i],
 * and the decision time is the CLOSE of candle i. Outcome resolution then walks
 * forward from i+1 only.
 */

import { getKlines } from '@/lib/bybit/client';
import { TIMEFRAME_MS, type Candle, type MarketCategory, type Timeframe } from '@/lib/bybit/types';
import { buildIndicatorSnapshot } from '@/lib/patterns/indicators-snapshot';
import { DETECTORS, runDetector } from '@/lib/patterns/registry';
import type { MarketContext } from '@/lib/patterns/types';
import { scoreCandidate } from './scoring';
import type { Settings } from '@/lib/config/settings';

export interface BacktestParams {
  category: MarketCategory;
  symbol: string;
  timeframe: Timeframe;
  /** Number of closed candles to evaluate. */
  bars: number;
  settings: Settings;
  /** Round-trip cost applied to the outcome, in basis points. */
  costBps?: number;
  detectorFilter?: string[];
}

export type Outcome = 'target1' | 'target2' | 'invalidated' | 'expired' | 'open';

export interface BacktestSignal {
  index: number;
  time: number;
  detectorName: string;
  displayName: string;
  direction: 'long' | 'short';
  score: number;
  rewardToRisk: number;
  entry: number;
  invalidation: number;
  target1: number;
  target2: number | null;
  outcome: Outcome;
  barsToOutcome: number | null;
  /** Net return in percent after costs, from the entry reference price. */
  returnPct: number;
  maxFavorablePct: number;
  maxAdversePct: number;
}

export interface BacktestSummary {
  symbol: string;
  category: MarketCategory;
  timeframe: Timeframe;
  barsEvaluated: number;
  from: number;
  to: number;
  totalSignals: number;
  resolved: number;
  wins: number;
  losses: number;
  hitRate: number;
  avgReturnPct: number;
  expectancyPct: number;
  profitFactor: number | null;
  maxDrawdownPct: number;
  avgBarsToOutcome: number | null;
  equityCurve: { time: number; equity: number }[];
  byDetector: {
    detector: string;
    signals: number;
    hitRate: number;
    avgReturnPct: number;
  }[];
  byScoreBucket: { bucket: string; signals: number; hitRate: number; avgReturnPct: number }[];
  costBps: number;
  detectorVersions: Record<string, string>;
  assumptions: string[];
  reproducibilityId: string;
}

export interface BacktestResult {
  summary: BacktestSummary;
  signals: BacktestSignal[];
}

/**
 * Resolves a signal by walking forward. When a single candle contains both the
 * invalidation and the target, the conservative policy applies: invalidation
 * first. Lower-timeframe resolution would be required to do better, and
 * assuming the favourable order would inflate every result.
 */
function resolveOutcome(
  candles: Candle[],
  fromIndex: number,
  direction: 'long' | 'short',
  entry: number,
  invalidation: number,
  target1: number,
  target2: number | null,
  maxBars: number,
): { outcome: Outcome; barsToOutcome: number | null; exitPrice: number; mfe: number; mae: number } {
  const isLong = direction === 'long';
  let mfe = 0;
  let mae = 0;

  for (let i = fromIndex + 1; i < Math.min(candles.length, fromIndex + 1 + maxBars); i++) {
    const c = candles[i]!;
    const bars = i - fromIndex;

    const favorable = isLong ? ((c.high - entry) / entry) * 100 : ((entry - c.low) / entry) * 100;
    const adverse = isLong ? ((entry - c.low) / entry) * 100 : ((c.high - entry) / entry) * 100;
    mfe = Math.max(mfe, favorable);
    mae = Math.max(mae, adverse);

    const hitInvalidation = isLong ? c.low <= invalidation : c.high >= invalidation;
    const hitTarget1 = isLong ? c.high >= target1 : c.low <= target1;
    const hitTarget2 = target2 !== null && (isLong ? c.high >= target2 : c.low <= target2);

    // Conservative ambiguity policy.
    if (hitInvalidation && (hitTarget1 || hitTarget2)) {
      return { outcome: 'invalidated', barsToOutcome: bars, exitPrice: invalidation, mfe, mae };
    }
    if (hitInvalidation) {
      return { outcome: 'invalidated', barsToOutcome: bars, exitPrice: invalidation, mfe, mae };
    }
    if (hitTarget2 && target2 !== null) {
      return { outcome: 'target2', barsToOutcome: bars, exitPrice: target2, mfe, mae };
    }
    if (hitTarget1) {
      return { outcome: 'target1', barsToOutcome: bars, exitPrice: target1, mfe, mae };
    }
  }

  const lastIdx = Math.min(candles.length - 1, fromIndex + maxBars);
  const lastCandle = candles[lastIdx];
  const stillOpen = lastIdx >= candles.length - 1;

  return {
    outcome: stillOpen ? 'open' : 'expired',
    barsToOutcome: stillOpen ? null : lastIdx - fromIndex,
    exitPrice: lastCandle?.close ?? entry,
    mfe,
    mae,
  };
}

const MAX_HOLD_BARS = 24;

export async function runBacktest(params: BacktestParams): Promise<BacktestResult> {
  const { category, symbol, timeframe, settings } = params;
  const costBps = params.costBps ?? 12; // ~6 bps per side: taker fee + slippage.
  const requested = Math.max(120, Math.min(900, params.bars));

  const series = await getKlines(category, symbol, timeframe, Math.min(1000, requested + 250));
  const candles = series.candles.slice(0, -1); // closed candles only

  if (candles.length < 200) {
    throw new Error(`Not enough history for ${symbol} ${timeframe}: got ${candles.length} closed candles.`);
  }

  const detectors = params.detectorFilter?.length
    ? DETECTORS.filter((d) => params.detectorFilter!.includes(d.name))
    : DETECTORS;

  const warmup = 150;
  const startIndex = Math.max(warmup, candles.length - requested);
  const signals: BacktestSignal[] = [];

  for (let i = startIndex; i < candles.length - 1; i++) {
    // ── NO LOOKAHEAD: the window ends at i, the decision bar. ──
    const window = candles.slice(0, i + 1);
    const ind = buildIndicatorSnapshot(window);

    const ctx: MarketContext = {
      instrumentId: `${category}:${symbol}`,
      category,
      symbol,
      timeframe,
      tickSize: 0.0001,
      // Historical turnover/spread are not reconstructable per-bar, so the
      // liquidity component is held neutral rather than fabricated.
      turnover24h: settings.minTurnover24h,
      spreadBps: null,
      fundingRate: null,
      openInterestChangePct: null,
      higherTimeframeBias: null,
      launchTime: null,
    };

    for (const detector of detectors) {
      // Same normalization path as the live scanner — never a separate engine.
      const found = runDetector(detector, window, ind, ctx);

      for (const c of found) {
        const score = scoreCandidate(c, ind, ctx, settings, {
          verified: true,
          ageMs: 0,
          reconciled: true,
        });
        if (score.total < settings.confirmedThreshold) continue;
        if (score.rewardToRisk < settings.minRewardToRisk) continue;

        const entry = c.direction === 'long' ? c.entryZone.to : c.entryZone.from;
        const target1 = c.targets[0]?.price ?? entry;
        const target2 = c.targets[1]?.price ?? null;

        const res = resolveOutcome(
          candles,
          i,
          c.direction,
          entry,
          c.invalidation,
          target1,
          target2,
          MAX_HOLD_BARS,
        );

        const gross =
          c.direction === 'long'
            ? ((res.exitPrice - entry) / entry) * 100
            : ((entry - res.exitPrice) / entry) * 100;
        const net = gross - costBps / 100;

        signals.push({
          index: i,
          time: candles[i]!.time,
          detectorName: c.detectorName,
          displayName: c.displayName,
          direction: c.direction,
          score: score.total,
          rewardToRisk: score.rewardToRisk,
          entry,
          invalidation: c.invalidation,
          target1,
          target2,
          outcome: res.outcome,
          barsToOutcome: res.barsToOutcome,
          returnPct: Number(net.toFixed(4)),
          maxFavorablePct: Number(res.mfe.toFixed(3)),
          maxAdversePct: Number(res.mae.toFixed(3)),
        });
      }
    }
  }

  // ── Summary statistics ──────────────────────────────────────────────────
  const resolvedSignals = signals.filter((s) => s.outcome !== 'open');
  const wins = resolvedSignals.filter((s) => s.returnPct > 0);
  const losses = resolvedSignals.filter((s) => s.returnPct <= 0);

  const grossProfit = wins.reduce((a, s) => a + s.returnPct, 0);
  const grossLoss = Math.abs(losses.reduce((a, s) => a + s.returnPct, 0));

  let equity = 100;
  let peak = 100;
  let maxDrawdown = 0;
  const equityCurve: { time: number; equity: number }[] = [];
  for (const s of [...resolvedSignals].sort((a, b) => a.time - b.time)) {
    equity *= 1 + s.returnPct / 100;
    peak = Math.max(peak, equity);
    maxDrawdown = Math.max(maxDrawdown, ((peak - equity) / peak) * 100);
    equityCurve.push({ time: s.time, equity: Number(equity.toFixed(3)) });
  }

  const byDetectorMap = new Map<string, BacktestSignal[]>();
  for (const s of resolvedSignals) {
    const arr = byDetectorMap.get(s.detectorName) ?? [];
    arr.push(s);
    byDetectorMap.set(s.detectorName, arr);
  }

  const buckets: { bucket: string; min: number; max: number }[] = [
    { bucket: '75–80', min: 75, max: 80 },
    { bucket: '80–85', min: 80, max: 85 },
    { bucket: '85–90', min: 85, max: 90 },
    { bucket: '90+', min: 90, max: 1000 },
  ];

  const avg = (arr: BacktestSignal[]) =>
    arr.length ? arr.reduce((a, s) => a + s.returnPct, 0) / arr.length : 0;
  const hitRateOf = (arr: BacktestSignal[]) =>
    arr.length ? (arr.filter((s) => s.returnPct > 0).length / arr.length) * 100 : 0;

  const barsResolved = resolvedSignals.filter((s) => s.barsToOutcome !== null);

  const summary: BacktestSummary = {
    symbol,
    category,
    timeframe,
    barsEvaluated: candles.length - startIndex,
    from: candles[startIndex]?.time ?? 0,
    to: candles[candles.length - 1]?.time ?? 0,
    totalSignals: signals.length,
    resolved: resolvedSignals.length,
    wins: wins.length,
    losses: losses.length,
    hitRate: Number(hitRateOf(resolvedSignals).toFixed(2)),
    avgReturnPct: Number(avg(resolvedSignals).toFixed(4)),
    expectancyPct: Number(avg(resolvedSignals).toFixed(4)),
    profitFactor: grossLoss > 0 ? Number((grossProfit / grossLoss).toFixed(3)) : null,
    maxDrawdownPct: Number(maxDrawdown.toFixed(3)),
    avgBarsToOutcome: barsResolved.length
      ? Number((barsResolved.reduce((a, s) => a + (s.barsToOutcome ?? 0), 0) / barsResolved.length).toFixed(2))
      : null,
    equityCurve,
    byDetector: [...byDetectorMap.entries()]
      .map(([detector, arr]) => ({
        detector,
        signals: arr.length,
        hitRate: Number(hitRateOf(arr).toFixed(2)),
        avgReturnPct: Number(avg(arr).toFixed(4)),
      }))
      .sort((a, b) => b.signals - a.signals),
    byScoreBucket: buckets.map((b) => {
      const arr = resolvedSignals.filter((s) => s.score >= b.min && s.score < b.max);
      return {
        bucket: b.bucket,
        signals: arr.length,
        hitRate: Number(hitRateOf(arr).toFixed(2)),
        avgReturnPct: Number(avg(arr).toFixed(4)),
      };
    }),
    costBps,
    detectorVersions: Object.fromEntries(detectors.map((d) => [d.name, d.version])),
    assumptions: [
      `Entry is assumed filled at the confirming candle's close (${'no intrabar fill modelling'}).`,
      `Round-trip cost of ${costBps} bps applied to every signal (taker fee + slippage estimate).`,
      `Maximum hold of ${MAX_HOLD_BARS} bars; unresolved signals are marked expired at that point.`,
      'When a single candle contains both the invalidation and a target, the invalidation is assumed first (conservative policy).',
      'Historical liquidity and spread are not reconstructable per bar, so those score components are held neutral.',
      'These are simulated signal outcomes, not executed trades. Real results would differ.',
    ],
    reproducibilityId: `bt_${category}_${symbol}_${timeframe}_${candles[startIndex]?.time ?? 0}_${candles[candles.length - 1]?.time ?? 0}_${settings.confirmedThreshold}_${settings.minRewardToRisk}_${costBps}`,
  };

  return { summary, signals: signals.slice(-500) };
}

export { TIMEFRAME_MS };
