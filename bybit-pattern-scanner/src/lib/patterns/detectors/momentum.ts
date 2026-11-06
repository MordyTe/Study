/**
 * Volatility, momentum, volume, and candlestick-context detectors.
 * No detector here fires on a candlestick name alone — location and context are
 * always required.
 */

import type { Candle } from '@/lib/bybit/types';
import { closeLocationValue } from '@/lib/ta/indicators';
import type {
  IndicatorSnapshot,
  MarketContext,
  PatternCandidate,
  PatternDetector,
} from '../types';
import { roundToTick } from '../types';

const SQUEEZE_PARAMS = {
  squeezeLookback: 30,
  minSqueezeBars: 4,
  expansionAtrMult: 0.9,
  invalidationBufferAtr: 0.5,
};

export const squeezeDetector: PatternDetector = {
  name: 'volatility_squeeze',
  version: '1.0.0',
  displayName: 'Volatility Squeeze Expansion',
  description:
    'Bollinger Bands contract inside the Keltner Channels (volatility compression), then price expands with a directional close. Compression alone is not a signal.',
  minCandles: 80,

  detect(candles: Candle[], ind: IndicatorSnapshot, ctx: MarketContext): PatternCandidate[] {
    const out: PatternCandidate[] = [];
    const n = candles.length;
    const last = candles[n - 1];
    const atrValue = ind.atrLast;
    if (n < this.minCandles || !last || atrValue <= 0) return out;

    // Count consecutive squeeze bars ending at the previous bar.
    let squeezeBars = 0;
    for (let i = n - 2; i >= Math.max(0, n - SQUEEZE_PARAMS.squeezeLookback); i--) {
      const bbU = ind.bollinger.upper[i];
      const bbL = ind.bollinger.lower[i];
      const kcU = ind.keltner.upper[i];
      const kcL = ind.keltner.lower[i];
      if (bbU == null || bbL == null || kcU == null || kcL == null) break;
      const inSqueeze = bbU < kcU && bbL > kcL;
      if (inSqueeze) squeezeBars += 1;
      else break;
    }
    if (squeezeBars < SQUEEZE_PARAMS.minSqueezeBars) return out;

    // Expansion: the confirming candle's range must exceed the ATR threshold and
    // close decisively outside the prior Bollinger band.
    const bbUpperPrev = ind.bollinger.upper[n - 2];
    const bbLowerPrev = ind.bollinger.lower[n - 2];
    if (bbUpperPrev == null || bbLowerPrev == null) return out;

    const barRange = last.high - last.low;
    if (barRange < atrValue * SQUEEZE_PARAMS.expansionAtrMult) return out;

    const brokeUp = last.close > bbUpperPrev;
    const brokeDown = last.close < bbLowerPrev;
    if (!brokeUp && !brokeDown) return out;

    const isLong = brokeUp;
    const buffer = atrValue * SQUEEZE_PARAMS.invalidationBufferAtr;
    const mid = ind.bollinger.middle[n - 1] ?? last.close;
    const invalidation = roundToTick(isLong ? mid - buffer : mid + buffer, ctx.tickSize);
    const volZ = ind.volumeZ[n - 1] ?? 0;

    const geometryQuality = Math.min(
      1,
      Math.min(1, squeezeBars / 10) * 0.45 + Math.min(1, barRange / (atrValue * 2)) * 0.35 + 0.2,
    );

    out.push({
      detectorName: this.name,
      detectorVersion: this.version,
      displayName: `Squeeze Expansion (${isLong ? 'bullish' : 'bearish'})`,
      direction: isLong ? 'long' : 'short',
      geometryQuality,
      confirmationIndex: n - 1,
      confirmationTime: last.time,
      entryZone: {
        from: roundToTick(Math.min(last.close, isLong ? bbUpperPrev : bbLowerPrev), ctx.tickSize),
        to: roundToTick(Math.max(last.close, isLong ? bbUpperPrev : bbLowerPrev), ctx.tickSize),
      },
      invalidation,
      targets: [
        {
          price: roundToTick(isLong ? last.close + atrValue * 1.6 : last.close - atrValue * 1.6, ctx.tickSize),
          method: 'ATR expansion target (1.6x)',
        },
        {
          price: roundToTick(isLong ? last.close + atrValue * 3 : last.close - atrValue * 3, ctx.tickSize),
          method: 'ATR expansion target (3.0x)',
        },
      ],
      overlays: [
        { type: 'horizontal_line', price: isLong ? bbUpperPrev : bbLowerPrev, label: 'Squeeze band', color: isLong ? 'bull' : 'bear' },
        { type: 'horizontal_line', price: mid, label: 'BB midline', color: 'neutral' },
        { type: 'invalidation_line', price: invalidation, label: 'Back inside range' },
      ],
      reasonsFor: [
        `${squeezeBars} consecutive bars of volatility compression (Bollinger inside Keltner) built stored energy.`,
        `Expansion candle range is ${(barRange / atrValue).toFixed(2)} ATR — a genuine volatility release.`,
        volZ > 0.5 ? `Volume ${volZ.toFixed(1)} SD above average supports the expansion.` : 'Volume was unremarkable on the expansion bar.',
      ],
      reasonsAgainst: [
        'Squeeze releases can whipsaw: the first directional break sometimes reverses hard.',
        'Compression indicates energy but never direction — the directional read comes only from the expansion bar.',
      ],
      parameters: { ...SQUEEZE_PARAMS },
      evidence: { squeezeBars, barRangeAtr: barRange / atrValue, volumeZ: volZ, bbMid: mid },
    });

    return out;
  },
};

const DIV_PARAMS = {
  lookbackPivots: 4,
  minPivotSeparation: 4,
  minRsiGap: 3,
  invalidationBufferAtr: 0.6,
};

export const divergenceDetector: PatternDetector = {
  name: 'momentum_divergence',
  version: '1.0.0',
  displayName: 'RSI Momentum Divergence',
  description:
    'Regular bullish/bearish divergence: price makes a new extreme while RSI does not. Indicator pivots are matched to price pivots with no lookahead.',
  minCandles: 80,

  detect(candles: Candle[], ind: IndicatorSnapshot, ctx: MarketContext): PatternCandidate[] {
    const out: PatternCandidate[] = [];
    const n = candles.length;
    const last = candles[n - 1];
    const atrValue = ind.atrLast;
    if (n < this.minCandles || !last || atrValue <= 0) return out;

    const build = (bullish: boolean): PatternCandidate | null => {
      const kind: 'high' | 'low' = bullish ? 'low' : 'high';
      const pivots = ind.pivots.filter((p) => p.kind === kind).slice(-DIV_PARAMS.lookbackPivots);
      if (pivots.length < 2) return null;

      const second = pivots[pivots.length - 1]!;
      const first = pivots[pivots.length - 2]!;
      if (second.index - first.index < DIV_PARAMS.minPivotSeparation) return null;
      if (n - 1 - second.index > 12) return null; // divergence must be current

      const rsi1 = ind.rsi[first.index];
      const rsi2 = ind.rsi[second.index];
      if (rsi1 == null || rsi2 == null) return null;

      const priceMadeExtreme = bullish ? second.price < first.price : second.price > first.price;
      const rsiFailed = bullish ? rsi2 > rsi1 + DIV_PARAMS.minRsiGap : rsi2 < rsi1 - DIV_PARAMS.minRsiGap;
      if (!priceMadeExtreme || !rsiFailed) return null;

      // Trigger: last close moved back through the divergent pivot's direction.
      const triggered = bullish ? last.close > second.price : last.close < second.price;
      if (!triggered) return null;

      const buffer = atrValue * DIV_PARAMS.invalidationBufferAtr;
      const invalidation = roundToTick(
        bullish ? second.price - buffer : second.price + buffer,
        ctx.tickSize,
      );

      const rsiGap = Math.abs(rsi2 - rsi1);
      const geometryQuality = Math.min(1, Math.min(1, rsiGap / 15) * 0.6 + 0.4 * second.prominenceAtr);

      return {
        detectorName: divergenceDetector.name,
        detectorVersion: divergenceDetector.version,
        displayName: `${bullish ? 'Bullish' : 'Bearish'} RSI Divergence`,
        direction: bullish ? 'long' : 'short',
        geometryQuality: Math.max(0.2, Math.min(1, geometryQuality)),
        confirmationIndex: n - 1,
        confirmationTime: last.time,
        entryZone: {
          from: roundToTick(Math.min(last.close, second.price), ctx.tickSize),
          to: roundToTick(Math.max(last.close, second.price), ctx.tickSize),
        },
        invalidation,
        targets: [
          {
            price: roundToTick(bullish ? first.price : first.price, ctx.tickSize),
            method: 'Prior divergent pivot',
          },
          {
            price: roundToTick(
              bullish ? last.close + atrValue * 2.5 : last.close - atrValue * 2.5,
              ctx.tickSize,
            ),
            method: 'ATR extension (2.5x)',
          },
        ],
        overlays: [
          {
            type: 'trend_line',
            from: { time: first.time, price: first.price },
            to: { time: second.time, price: second.price },
            label: 'Price divergence',
            color: bullish ? 'bull' : 'bear',
          },
          { type: 'invalidation_line', price: invalidation, label: 'Divergence failure' },
          { type: 'marker', time: second.time, price: second.price, label: `RSI ${rsi2.toFixed(1)}`, color: 'warn' },
        ],
        reasonsFor: [
          `Price made a ${bullish ? 'lower low' : 'higher high'} while RSI made a ${bullish ? 'higher low' : 'lower high'} (${rsi1.toFixed(1)} → ${rsi2.toFixed(1)}).`,
          'Momentum is no longer confirming price — the move is running out of participation.',
          `Price has already reclaimed the divergent pivot at ${second.price.toFixed(6)}, providing a trigger.`,
        ],
        reasonsAgainst: [
          'Divergence can persist for many bars in a strong trend before (or without) resolving.',
          'Counter-trend by nature: this fights the prevailing direction.',
        ],
        parameters: { ...DIV_PARAMS },
        evidence: {
          pivot1: { time: first.time, price: first.price, rsi: rsi1 },
          pivot2: { time: second.time, price: second.price, rsi: rsi2 },
          rsiGap,
        },
      };
    };

    const bull = build(true);
    if (bull) out.push(bull);
    const bear = build(false);
    if (bear) out.push(bear);

    return out;
  },
};

const VOLUME_PARAMS = {
  minVolumeZ: 2.0,
  minRangeAtr: 1.2,
  minClv: 0.4,
  minTurnover24h: 2_000_000,
  invalidationBufferAtr: 0.4,
};

export const volumeBreakoutDetector: PatternDetector = {
  name: 'volume_breakout',
  version: '1.0.0',
  displayName: 'Volume Expansion Breakout',
  description:
    'A range-expansion candle on statistically abnormal volume closing near its extreme. Requires baseline liquidity so thin-book spikes are excluded.',
  minCandles: 60,

  detect(candles: Candle[], ind: IndicatorSnapshot, ctx: MarketContext): PatternCandidate[] {
    const out: PatternCandidate[] = [];
    const n = candles.length;
    const last = candles[n - 1];
    const atrValue = ind.atrLast;
    if (n < this.minCandles || !last || atrValue <= 0) return out;
    if (ctx.turnover24h < VOLUME_PARAMS.minTurnover24h) return out;

    const volZ = ind.volumeZ[n - 1];
    if (volZ == null || volZ < VOLUME_PARAMS.minVolumeZ) return out;

    const barRange = last.high - last.low;
    if (barRange < atrValue * VOLUME_PARAMS.minRangeAtr) return out;

    const clv = closeLocationValue(last);
    if (Math.abs(clv) < VOLUME_PARAMS.minClv) return out;

    const isLong = clv > 0;
    // The candle must also clear the recent range, not just be large.
    const priorWindow = candles.slice(Math.max(0, n - 21), n - 1);
    const priorHigh = Math.max(...priorWindow.map((c) => c.high));
    const priorLow = Math.min(...priorWindow.map((c) => c.low));
    const clearedRange = isLong ? last.close > priorHigh : last.close < priorLow;
    if (!clearedRange) return out;

    const buffer = atrValue * VOLUME_PARAMS.invalidationBufferAtr;
    const invalidation = roundToTick(
      isLong ? Math.min(last.low, priorHigh) - buffer : Math.max(last.high, priorLow) + buffer,
      ctx.tickSize,
    );

    const geometryQuality = Math.min(
      1,
      Math.min(1, volZ / 4) * 0.4 + Math.min(1, barRange / (atrValue * 2.5)) * 0.3 + Math.abs(clv) * 0.3,
    );

    out.push({
      detectorName: this.name,
      detectorVersion: this.version,
      displayName: `Volume Breakout (${isLong ? 'bullish' : 'bearish'})`,
      direction: isLong ? 'long' : 'short',
      geometryQuality,
      confirmationIndex: n - 1,
      confirmationTime: last.time,
      entryZone: {
        from: roundToTick(Math.min(last.close, isLong ? priorHigh : priorLow), ctx.tickSize),
        to: roundToTick(Math.max(last.close, isLong ? priorHigh : priorLow), ctx.tickSize),
      },
      invalidation,
      targets: [
        {
          price: roundToTick(isLong ? last.close + atrValue * 1.5 : last.close - atrValue * 1.5, ctx.tickSize),
          method: 'ATR extension (1.5x)',
        },
        {
          price: roundToTick(isLong ? last.close + atrValue * 3 : last.close - atrValue * 3, ctx.tickSize),
          method: 'ATR extension (3.0x)',
        },
      ],
      overlays: [
        { type: 'horizontal_line', price: isLong ? priorHigh : priorLow, label: '20-bar range edge', color: isLong ? 'bull' : 'bear' },
        { type: 'invalidation_line', price: invalidation, label: 'Breakout failure' },
        { type: 'marker', time: last.time, price: last.close, label: `Vol ${volZ.toFixed(1)}σ`, color: isLong ? 'bull' : 'bear' },
      ],
      reasonsFor: [
        `Volume is ${volZ.toFixed(1)} standard deviations above its 20-bar mean — real participation, not drift.`,
        `Candle range of ${(barRange / atrValue).toFixed(2)} ATR cleared the 20-bar ${isLong ? 'high' : 'low'}.`,
        `Close location value ${clv.toFixed(2)} shows the candle closed near its ${isLong ? 'high' : 'low'}.`,
      ],
      reasonsAgainst: [
        'Volume spikes often mark exhaustion rather than initiation, especially after an extended move.',
        'Entry here is at the top/bottom of an expanded candle — the invalidation distance is wide.',
      ],
      parameters: { ...VOLUME_PARAMS },
      evidence: { volumeZ: volZ, barRangeAtr: barRange / atrValue, closeLocationValue: clv, priorHigh, priorLow },
    });

    return out;
  },
};

const CANDLE_PARAMS = {
  minBodyRatio: 0.55,
  proximityAtr: 0.8,
  invalidationBufferAtr: 0.4,
};

export const candlestickContextDetector: PatternDetector = {
  name: 'candlestick_context',
  version: '1.0.0',
  displayName: 'Contextual Candlestick Reversal',
  description:
    'Engulfing and pin-bar reversals that only fire AT a meaningful level and AGAINST a stretched move. A candlestick name alone never produces a signal.',
  minCandles: 60,

  detect(candles: Candle[], ind: IndicatorSnapshot, ctx: MarketContext): PatternCandidate[] {
    const out: PatternCandidate[] = [];
    const n = candles.length;
    const last = candles[n - 1];
    const prev = candles[n - 2];
    const atrValue = ind.atrLast;
    if (n < this.minCandles || !last || !prev || atrValue <= 0) return out;

    const range = last.high - last.low;
    if (range <= 0) return out;

    const body = Math.abs(last.close - last.open);
    const bullBody = last.close > last.open;
    const prevBody = Math.abs(prev.close - prev.open);

    // Engulfing: body fully covers the prior body and is decisively larger.
    const engulfing =
      body > prevBody * 1.1 &&
      body / range >= CANDLE_PARAMS.minBodyRatio &&
      ((bullBody && last.close > prev.open && last.open < prev.close && prev.close < prev.open) ||
        (!bullBody && last.close < prev.open && last.open > prev.close && prev.close > prev.open));

    // Pin bar: long rejection wick, small body.
    const upperWick = last.high - Math.max(last.close, last.open);
    const lowerWick = Math.min(last.close, last.open) - last.low;
    const bullPin = lowerWick / range >= 0.6 && body / range <= 0.3;
    const bearPin = upperWick / range >= 0.6 && body / range <= 0.3;

    if (!engulfing && !bullPin && !bearPin) return out;

    const isLong = engulfing ? bullBody : bullPin;
    const patternName = engulfing ? (bullBody ? 'Bullish Engulfing' : 'Bearish Engulfing') : isLong ? 'Bullish Pin Bar' : 'Bearish Pin Bar';

    // CONTEXT GATE 1 — the candle must occur at a real level.
    const nearLevel = ind.levels.find(
      (l) =>
        Math.abs((isLong ? last.low : last.high) - l.price) <= atrValue * CANDLE_PARAMS.proximityAtr &&
        l.strength >= 0.3,
    );
    if (!nearLevel) return out;

    // CONTEXT GATE 2 — the move into the level must be stretched (RSI extreme).
    const rsiNow = ind.rsi[n - 1];
    if (rsiNow == null) return out;
    const stretched = isLong ? rsiNow < 42 : rsiNow > 58;
    if (!stretched) return out;

    const buffer = atrValue * CANDLE_PARAMS.invalidationBufferAtr;
    const invalidation = roundToTick(
      isLong ? last.low - buffer : last.high + buffer,
      ctx.tickSize,
    );

    const geometryQuality = Math.min(
      1,
      (body / range) * 0.3 + nearLevel.strength * 0.4 + (engulfing ? 0.3 : 0.2),
    );

    out.push({
      detectorName: this.name,
      detectorVersion: this.version,
      displayName: patternName,
      direction: isLong ? 'long' : 'short',
      geometryQuality,
      confirmationIndex: n - 1,
      confirmationTime: last.time,
      entryZone: {
        from: roundToTick(Math.min(last.close, nearLevel.price), ctx.tickSize),
        to: roundToTick(Math.max(last.close, nearLevel.price), ctx.tickSize),
      },
      invalidation,
      targets: [
        {
          price: roundToTick(isLong ? last.close + atrValue * 1.5 : last.close - atrValue * 1.5, ctx.tickSize),
          method: 'ATR extension (1.5x)',
        },
        {
          price: roundToTick(isLong ? last.close + atrValue * 2.5 : last.close - atrValue * 2.5, ctx.tickSize),
          method: 'ATR extension (2.5x)',
        },
      ],
      overlays: [
        { type: 'horizontal_line', price: nearLevel.price, label: 'Reaction level', color: isLong ? 'bull' : 'bear' },
        { type: 'marker', time: last.time, price: isLong ? last.low : last.high, label: patternName, color: isLong ? 'bull' : 'bear' },
        { type: 'invalidation_line', price: invalidation, label: 'Candle low/high broken' },
      ],
      reasonsFor: [
        `${patternName} formed directly at a level with ${nearLevel.touches} historical touches.`,
        `RSI at ${rsiNow.toFixed(1)} shows the move into the level was stretched.`,
        'Location and context gates passed — this is not a standalone candlestick call.',
      ],
      reasonsAgainst: [
        'Single-candle reversals are the weakest evidence class and need immediate follow-through.',
        'Tight invalidation means normal noise can stop the scenario out.',
      ],
      parameters: { ...CANDLE_PARAMS, patternName },
      evidence: {
        patternName,
        bodyRatio: body / range,
        upperWickRatio: upperWick / range,
        lowerWickRatio: lowerWick / range,
        levelPrice: nearLevel.price,
        levelTouches: nearLevel.touches,
        rsi: rsiNow,
      },
    });

    return out;
  },
};
