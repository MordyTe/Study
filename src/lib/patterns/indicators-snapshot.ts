/** Builds the shared IndicatorSnapshot once per candle series. */

import type { Candle } from '@/lib/bybit/types';
import {
  adx,
  atr,
  bollinger,
  ema,
  keltner,
  lastDefined,
  macd,
  realizedVolatility,
  rsi,
  zScore,
} from '@/lib/ta/indicators';
import { analyzeStructure, clusterLevels, findPivots } from '@/lib/ta/structure';
import type { IndicatorSnapshot } from './types';

export function buildIndicatorSnapshot(candles: Candle[]): IndicatorSnapshot {
  const closes = candles.map((c) => c.close);
  const highs = candles.map((c) => c.high);
  const lows = candles.map((c) => c.low);
  const volumes = candles.map((c) => c.volume);
  const turnovers = candles.map((c) => c.turnover);

  const atrSeries = atr(candles, 14);
  const atrLast = lastDefined(atrSeries) ?? 0;

  const pivots = findPivots(candles, { window: 3, minProminenceAtr: 0.5, atrPeriod: 14 });
  const levels = clusterLevels(pivots, atrLast, 0.6, candles[candles.length - 1]?.time ?? Date.now());
  const structure = analyzeStructure(candles, pivots);

  return {
    closes,
    highs,
    lows,
    volumes,
    turnovers,
    atr: atrSeries,
    atrLast,
    ema20: ema(closes, 20),
    ema50: ema(closes, 50),
    ema200: ema(closes, 200),
    rsi: rsi(closes, 14),
    macd: macd(closes, 12, 26, 9),
    bollinger: bollinger(closes, 20, 2),
    keltner: keltner(candles, 20, 1.5),
    adx: adx(candles, 14),
    volumeZ: zScore(volumes, 20),
    realizedVol: realizedVolatility(closes, 20),
    pivots,
    levels,
    structure,
  };
}
