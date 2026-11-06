/**
 * Deterministic technical indicators. Every function is pure, index-aligned with
 * the input series, and free of lookahead: value[i] uses only candles 0..i.
 *
 * Arrays return `null` for indices where the indicator has insufficient history.
 */

import type { Candle } from '@/lib/bybit/types';

export type Series = (number | null)[];

export function sma(values: number[], period: number): Series {
  const out: Series = new Array(values.length).fill(null);
  if (period <= 0) return out;
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i]!;
    if (i >= period) sum -= values[i - period]!;
    if (i >= period - 1) out[i] = sum / period;
  }
  return out;
}

export function ema(values: number[], period: number): Series {
  const out: Series = new Array(values.length).fill(null);
  if (period <= 0 || values.length < period) return out;
  const k = 2 / (period + 1);
  let seed = 0;
  for (let i = 0; i < period; i++) seed += values[i]!;
  let prev = seed / period;
  out[period - 1] = prev;
  for (let i = period; i < values.length; i++) {
    prev = values[i]! * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}

/** Wilder's smoothing — used by ATR and RSI. */
function wilder(values: number[], period: number): Series {
  const out: Series = new Array(values.length).fill(null);
  if (values.length < period) return out;
  let sum = 0;
  for (let i = 0; i < period; i++) sum += values[i]!;
  let prev = sum / period;
  out[period - 1] = prev;
  for (let i = period; i < values.length; i++) {
    prev = (prev * (period - 1) + values[i]!) / period;
    out[i] = prev;
  }
  return out;
}

export function trueRange(candles: Candle[]): number[] {
  const out: number[] = new Array(candles.length).fill(0);
  for (let i = 0; i < candles.length; i++) {
    const c = candles[i]!;
    if (i === 0) {
      out[i] = c.high - c.low;
      continue;
    }
    const prevClose = candles[i - 1]!.close;
    out[i] = Math.max(c.high - c.low, Math.abs(c.high - prevClose), Math.abs(c.low - prevClose));
  }
  return out;
}

export function atr(candles: Candle[], period = 14): Series {
  return wilder(trueRange(candles), period);
}

export function rsi(values: number[], period = 14): Series {
  const out: Series = new Array(values.length).fill(null);
  if (values.length <= period) return out;

  const gains: number[] = [0];
  const losses: number[] = [0];
  for (let i = 1; i < values.length; i++) {
    const diff = values[i]! - values[i - 1]!;
    gains.push(Math.max(0, diff));
    losses.push(Math.max(0, -diff));
  }

  let avgGain = 0;
  let avgLoss = 0;
  for (let i = 1; i <= period; i++) {
    avgGain += gains[i]!;
    avgLoss += losses[i]!;
  }
  avgGain /= period;
  avgLoss /= period;
  out[period] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);

  for (let i = period + 1; i < values.length; i++) {
    avgGain = (avgGain * (period - 1) + gains[i]!) / period;
    avgLoss = (avgLoss * (period - 1) + losses[i]!) / period;
    out[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  }
  return out;
}

export interface MacdResult {
  macd: Series;
  signal: Series;
  histogram: Series;
}

export function macd(values: number[], fast = 12, slow = 26, signalPeriod = 9): MacdResult {
  const emaFast = ema(values, fast);
  const emaSlow = ema(values, slow);
  const macdLine: Series = values.map((_, i) => {
    const f = emaFast[i];
    const s = emaSlow[i];
    return f !== null && f !== undefined && s !== null && s !== undefined ? f - s : null;
  });

  const firstIdx = macdLine.findIndex((v) => v !== null);
  const dense = firstIdx === -1 ? [] : (macdLine.slice(firstIdx) as number[]);
  const signalDense = ema(dense, signalPeriod);

  const signal: Series = new Array(values.length).fill(null);
  if (firstIdx !== -1) {
    for (let i = 0; i < signalDense.length; i++) signal[firstIdx + i] = signalDense[i] ?? null;
  }

  const histogram: Series = values.map((_, i) => {
    const m = macdLine[i];
    const s = signal[i];
    return m !== null && m !== undefined && s !== null && s !== undefined ? m - s : null;
  });

  return { macd: macdLine, signal, histogram };
}

export function stddev(values: number[], period: number): Series {
  const out: Series = new Array(values.length).fill(null);
  const means = sma(values, period);
  for (let i = period - 1; i < values.length; i++) {
    const mean = means[i];
    if (mean === null || mean === undefined) continue;
    let acc = 0;
    for (let j = i - period + 1; j <= i; j++) acc += (values[j]! - mean) ** 2;
    out[i] = Math.sqrt(acc / period);
  }
  return out;
}

export interface BollingerResult {
  upper: Series;
  middle: Series;
  lower: Series;
  bandwidth: Series;
}

export function bollinger(values: number[], period = 20, mult = 2): BollingerResult {
  const middle = sma(values, period);
  const sd = stddev(values, period);
  const upper: Series = new Array(values.length).fill(null);
  const lower: Series = new Array(values.length).fill(null);
  const bandwidth: Series = new Array(values.length).fill(null);

  for (let i = 0; i < values.length; i++) {
    const m = middle[i];
    const s = sd[i];
    if (m === null || m === undefined || s === null || s === undefined) continue;
    upper[i] = m + mult * s;
    lower[i] = m - mult * s;
    bandwidth[i] = m !== 0 ? ((upper[i]! - lower[i]!) / m) * 100 : null;
  }
  return { upper, middle, lower, bandwidth };
}

export interface KeltnerResult {
  upper: Series;
  middle: Series;
  lower: Series;
}

export function keltner(candles: Candle[], period = 20, mult = 1.5): KeltnerResult {
  const closes = candles.map((c) => c.close);
  const middle = ema(closes, period);
  const atrValues = atr(candles, period);
  const upper: Series = new Array(candles.length).fill(null);
  const lower: Series = new Array(candles.length).fill(null);

  for (let i = 0; i < candles.length; i++) {
    const m = middle[i];
    const a = atrValues[i];
    if (m === null || m === undefined || a === null || a === undefined) continue;
    upper[i] = m + mult * a;
    lower[i] = m - mult * a;
  }
  return { upper, middle, lower };
}

/** Wilder's ADX — trend-strength gauge used for regime classification. */
export function adx(candles: Candle[], period = 14): Series {
  const n = candles.length;
  const out: Series = new Array(n).fill(null);
  if (n < period * 2) return out;

  const plusDM: number[] = new Array(n).fill(0);
  const minusDM: number[] = new Array(n).fill(0);
  for (let i = 1; i < n; i++) {
    const up = candles[i]!.high - candles[i - 1]!.high;
    const down = candles[i - 1]!.low - candles[i]!.low;
    plusDM[i] = up > down && up > 0 ? up : 0;
    minusDM[i] = down > up && down > 0 ? down : 0;
  }

  const tr = trueRange(candles);
  const smTr = wilder(tr, period);
  const smPlus = wilder(plusDM, period);
  const smMinus = wilder(minusDM, period);

  const dx: number[] = new Array(n).fill(0);
  for (let i = 0; i < n; i++) {
    const t = smTr[i];
    const p = smPlus[i];
    const m = smMinus[i];
    if (!t || t === 0 || p === null || p === undefined || m === null || m === undefined) continue;
    const pdi = (p / t) * 100;
    const mdi = (m / t) * 100;
    const sum = pdi + mdi;
    dx[i] = sum === 0 ? 0 : (Math.abs(pdi - mdi) / sum) * 100;
  }

  const smoothed = wilder(dx.slice(period), period);
  for (let i = 0; i < smoothed.length; i++) out[period + i] = smoothed[i] ?? null;
  return out;
}

/** Rolling z-score. Measures how unusual the latest value is versus its window. */
export function zScore(values: number[], period: number): Series {
  const out: Series = new Array(values.length).fill(null);
  const means = sma(values, period);
  const sds = stddev(values, period);
  for (let i = 0; i < values.length; i++) {
    const m = means[i];
    const s = sds[i];
    if (m === null || m === undefined || s === null || s === undefined || s === 0) continue;
    out[i] = (values[i]! - m) / s;
  }
  return out;
}

/** Annualization-free realized volatility (stdev of log returns, in %). */
export function realizedVolatility(closes: number[], period = 20): Series {
  const returns: number[] = [0];
  for (let i = 1; i < closes.length; i++) {
    const prev = closes[i - 1]!;
    returns.push(prev > 0 ? Math.log(closes[i]! / prev) : 0);
  }
  const sd = stddev(returns, period);
  return sd.map((v) => (v === null || v === undefined ? null : v * 100));
}

/** Close Location Value: where the close sits inside the candle range (-1..1). */
export function closeLocationValue(c: Candle): number {
  const range = c.high - c.low;
  if (range <= 0) return 0;
  return ((c.close - c.low) - (c.high - c.close)) / range;
}

/** Least-squares slope of the last `period` values, normalized by price. */
export function linearSlope(values: number[], period: number): number | null {
  const n = values.length;
  if (n < period || period < 2) return null;
  const slice = values.slice(n - period);
  const meanX = (period - 1) / 2;
  const meanY = slice.reduce((a, b) => a + b, 0) / period;
  let num = 0;
  let den = 0;
  for (let i = 0; i < period; i++) {
    num += (i - meanX) * (slice[i]! - meanY);
    den += (i - meanX) ** 2;
  }
  if (den === 0) return null;
  const slope = num / den;
  return meanY !== 0 ? (slope / meanY) * 100 : slope;
}

export function lastDefined(series: Series): number | null {
  for (let i = series.length - 1; i >= 0; i--) {
    const v = series[i];
    if (v !== null && v !== undefined && Number.isFinite(v)) return v;
  }
  return null;
}

export function valueAt(series: Series, index: number): number | null {
  const v = series[index];
  return v === undefined || v === null || !Number.isFinite(v) ? null : v;
}
