/**
 * Data verification layer. No opportunity is labelled CONFIRMED without a
 * DataVerificationRecord proving the underlying candles agree with Bybit.
 */

import type { Candle, CandleSeries, Ticker, Timeframe } from '@/lib/bybit/types';
import { TIMEFRAME_MS } from '@/lib/bybit/types';
import type { Settings } from '@/lib/config/settings';
import type { DataVerificationRecord } from './opportunity';

export interface CandleIntegrityResult {
  valid: boolean;
  gaps: number;
  issues: string[];
}

/**
 * Structural integrity of a candle series:
 * boundary alignment, monotonic unique timestamps, OHLC sanity, gap count.
 */
export function checkCandleIntegrity(candles: Candle[], timeframe: Timeframe): CandleIntegrityResult {
  const issues: string[] = [];
  const step = TIMEFRAME_MS[timeframe];
  let gaps = 0;

  if (candles.length === 0) {
    return { valid: false, gaps: 0, issues: ['Empty candle series.'] };
  }

  for (let i = 0; i < candles.length; i++) {
    const c = candles[i]!;

    if (c.open <= 0 || c.high <= 0 || c.low <= 0 || c.close <= 0) {
      issues.push(`Non-positive price at index ${i} (t=${c.time}).`);
    }
    if (c.low > c.open || c.low > c.close || c.high < c.open || c.high < c.close || c.high < c.low) {
      issues.push(`OHLC ordering violated at index ${i} (t=${c.time}).`);
    }
    if (c.volume < 0 || c.turnover < 0) {
      issues.push(`Negative volume/turnover at index ${i} (t=${c.time}).`);
    }
    // Daily candles align to UTC midnight; intraday aligns to the interval.
    if (timeframe !== '1d' && c.time % step !== 0) {
      issues.push(`Timestamp ${c.time} is not aligned to the ${timeframe} boundary.`);
    }

    if (i > 0) {
      const prev = candles[i - 1]!;
      if (c.time <= prev.time) {
        issues.push(`Non-monotonic timestamp at index ${i} (${prev.time} → ${c.time}).`);
      } else {
        const delta = c.time - prev.time;
        if (delta > step) gaps += Math.round(delta / step) - 1;
      }
    }
  }

  return { valid: issues.length === 0, gaps, issues };
}

/** Reconciles the newest closed candle against an independently fetched ticker. */
export function reconcile(
  series: CandleSeries,
  ticker: Ticker | null,
  tolerancePct: number,
): { passed: boolean; deltaPct: number | null; note: string } {
  const lastClosed = series.candles[series.candles.length - 1];
  if (!lastClosed) return { passed: false, deltaPct: null, note: 'No closed candle available to reconcile.' };
  if (!ticker || ticker.lastPrice <= 0) {
    return { passed: false, deltaPct: null, note: 'No ticker snapshot available for reconciliation.' };
  }

  const deltaPct = Math.abs((ticker.lastPrice - lastClosed.close) / lastClosed.close) * 100;
  // Price legitimately moves inside the open candle, so allow the tolerance to
  // scale with the candle's own realized range.
  const candleRangePct = ((lastClosed.high - lastClosed.low) / lastClosed.close) * 100;
  const effectiveTolerance = Math.max(tolerancePct, candleRangePct * 1.5);
  const passed = deltaPct <= effectiveTolerance;

  return {
    passed,
    deltaPct: Number(deltaPct.toFixed(4)),
    note: passed
      ? `Ticker last price is within ${deltaPct.toFixed(3)}% of the latest closed candle (tolerance ${effectiveTolerance.toFixed(3)}%).`
      : `Ticker/candle divergence of ${deltaPct.toFixed(3)}% exceeds tolerance ${effectiveTolerance.toFixed(3)}%.`,
  };
}

export function buildVerificationRecord(input: {
  series: CandleSeries;
  ticker: Ticker | null;
  serverTimeMs: number;
  restLatencyMs: number;
  settings: Settings;
}): DataVerificationRecord {
  const { series, ticker, serverTimeMs, restLatencyMs, settings } = input;
  const localTimestamp = Date.now();
  const clockDriftMs = Math.abs(localTimestamp - serverTimeMs);

  const integrity = checkCandleIntegrity(series.candles, series.timeframe);
  const recon = reconcile(series, ticker, settings.reconciliationTolerancePct);

  const lastCandle = series.candles[series.candles.length - 1];
  const step = TIMEFRAME_MS[series.timeframe];
  // Age from when the newest candle should have closed.
  const dataAgeMs = lastCandle ? Math.max(0, localTimestamp - (lastCandle.time + step)) : Number.MAX_SAFE_INTEGER;

  const notes: string[] = [recon.note, ...integrity.issues.slice(0, 3)];

  let health: DataVerificationRecord['health'] = 'HEALTHY';
  if (dataAgeMs > settings.maxDataAgeMs * 3) health = 'STALE';
  else if (!recon.passed || integrity.gaps > 0 || clockDriftMs > settings.maxClockDriftMs) health = 'DEGRADED';
  else if (!integrity.valid) health = 'DEGRADED';

  if (integrity.gaps > 0) notes.push(`${integrity.gaps} candle gap(s) detected in the fetched window.`);
  if (clockDriftMs > settings.maxClockDriftMs) {
    notes.push(`Clock drift of ${clockDriftMs}ms exceeds the ${settings.maxClockDriftMs}ms tolerance.`);
  }

  return {
    id: `dvr_${series.instrumentId.replace(':', '_')}_${series.timeframe}_${lastCandle?.time ?? 0}`,
    source: 'Bybit V5 Official',
    exchangeTimestamp: serverTimeMs,
    localTimestamp,
    clockDriftMs,
    dataAgeMs,
    restLatencyMs,
    reconciliationPassed: recon.passed,
    reconciliationDeltaPct: recon.deltaPct,
    candleGapsDetected: integrity.gaps,
    health,
    notes,
  };
}

/** A CONFIRMED opportunity requires a fully healthy verification record. */
export function isVerifiedForConfirmation(record: DataVerificationRecord, settings: Settings): boolean {
  return (
    record.health === 'HEALTHY' &&
    record.reconciliationPassed &&
    record.candleGapsDetected === 0 &&
    record.clockDriftMs <= settings.maxClockDriftMs &&
    record.dataAgeMs <= settings.maxDataAgeMs
  );
}
