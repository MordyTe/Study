/**
 * Horizontal level detectors:
 *  - breakout_retest: close beyond a clustered level, then a retest + rejection.
 *  - level_rejection: wick rejection from a high-quality level.
 *
 * Both treat a wick-only penetration as NOT a breakout — a body close is required.
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

const BREAKOUT_PARAMS = {
  minLevelTouches: 2,
  minLevelStrength: 0.35,
  breakoutLookback: 12,
  retestToleranceAtr: 0.5,
  invalidationBufferAtr: 0.7,
  minVolumeZ: 0.3,
};

export const breakoutRetestDetector: PatternDetector = {
  name: 'breakout_retest',
  version: '1.0.0',
  displayName: 'Breakout + Retest',
  description:
    'Price closes decisively beyond a horizontal level built from repeated swing touches, then returns to retest it and is rejected. Wick-only penetration is explicitly rejected.',
  minCandles: 80,

  detect(candles: Candle[], ind: IndicatorSnapshot, ctx: MarketContext): PatternCandidate[] {
    const out: PatternCandidate[] = [];
    const n = candles.length;
    const last = candles[n - 1];
    const atrValue = ind.atrLast;
    if (n < this.minCandles || !last || atrValue <= 0) return out;

    const candidateLevels = ind.levels.filter(
      (l) => l.touches >= BREAKOUT_PARAMS.minLevelTouches && l.strength >= BREAKOUT_PARAMS.minLevelStrength,
    );

    for (const level of candidateLevels.slice(0, 6)) {
      const lookback = candles.slice(-BREAKOUT_PARAMS.breakoutLookback);

      // Find the breakout bar: first close beyond the level within the lookback.
      let breakoutIdx = -1;
      let isLong = false;
      for (let i = 0; i < lookback.length; i++) {
        const c = lookback[i]!;
        const globalIdx = n - lookback.length + i;
        if (globalIdx < 1) continue;
        const prev = candles[globalIdx - 1]!;
        if (prev.close <= level.price && c.close > level.price) {
          breakoutIdx = globalIdx;
          isLong = true;
        } else if (prev.close >= level.price && c.close < level.price) {
          breakoutIdx = globalIdx;
          isLong = false;
        }
      }
      if (breakoutIdx === -1 || breakoutIdx >= n - 1) continue;

      const breakoutCandle = candles[breakoutIdx]!;
      const breakoutStrength = Math.abs(breakoutCandle.close - level.price) / atrValue;
      if (breakoutStrength < 0.15) continue; // marginal close — not decisive

      // Retest: after the break, price came back within tolerance of the level.
      const after = candles.slice(breakoutIdx + 1);
      const tolerance = atrValue * BREAKOUT_PARAMS.retestToleranceAtr;
      const retestBar = after.find((c) =>
        isLong ? c.low <= level.price + tolerance : c.high >= level.price - tolerance,
      );
      if (!retestBar) continue;

      // Rejection: the last closed candle closed back in the breakout direction.
      const heldLevel = isLong ? last.close > level.price : last.close < level.price;
      if (!heldLevel) continue;

      const volZ = ind.volumeZ[breakoutIdx] ?? 0;
      const buffer = atrValue * BREAKOUT_PARAMS.invalidationBufferAtr;
      const invalidation = roundToTick(isLong ? level.price - buffer : level.price + buffer, ctx.tickSize);

      // Measured move: prior swing range projected from the level.
      const rangeWindow = candles.slice(Math.max(0, breakoutIdx - 40), breakoutIdx);
      const rangeHigh = Math.max(...rangeWindow.map((c) => c.high));
      const rangeLow = Math.min(...rangeWindow.map((c) => c.low));
      const measuredMove = Math.max(atrValue, rangeHigh - rangeLow);

      const entryFrom = roundToTick(Math.min(level.price, last.close), ctx.tickSize);
      const entryTo = roundToTick(Math.max(level.price, last.close), ctx.tickSize);

      const geometryQuality = Math.min(
        1,
        level.strength * 0.5 + Math.min(1, breakoutStrength) * 0.3 + Math.min(1, Math.max(0, volZ) / 2) * 0.2,
      );

      out.push({
        detectorName: this.name,
        detectorVersion: this.version,
        displayName: `Breakout + Retest (${isLong ? 'bullish' : 'bearish'})`,
        direction: isLong ? 'long' : 'short',
        geometryQuality,
        confirmationIndex: n - 1,
        confirmationTime: last.time,
        entryZone: { from: entryFrom, to: entryTo },
        invalidation,
        targets: [
          {
            price: roundToTick(
              isLong ? level.price + measuredMove * 0.6 : level.price - measuredMove * 0.6,
              ctx.tickSize,
            ),
            method: 'Measured move (60% of prior range)',
          },
          {
            price: roundToTick(
              isLong ? level.price + measuredMove : level.price - measuredMove,
              ctx.tickSize,
            ),
            method: 'Measured move (100% of prior range)',
          },
        ],
        overlays: [
          {
            type: 'horizontal_line',
            price: level.price,
            label: `Level (${level.touches} touches)`,
            color: isLong ? 'bull' : 'bear',
          },
          { type: 'invalidation_line', price: invalidation, label: 'Level reclaim = invalid' },
          {
            type: 'marker',
            time: breakoutCandle.time,
            price: breakoutCandle.close,
            label: 'Breakout close',
            color: isLong ? 'bull' : 'bear',
          },
          {
            type: 'marker',
            time: retestBar.time,
            price: isLong ? retestBar.low : retestBar.high,
            label: 'Retest',
            color: 'neutral',
          },
        ],
        reasonsFor: [
          `Level at ${level.price.toFixed(6)} was tested ${level.touches} times before breaking (strength ${(level.strength * 100).toFixed(0)}%).`,
          `Breakout confirmed by candle close ${breakoutStrength.toFixed(2)} ATR beyond the level — not a wick.`,
          'Price returned to retest the level and held it, which is the higher-probability entry versus chasing the initial break.',
          volZ > BREAKOUT_PARAMS.minVolumeZ
            ? `Breakout volume was ${volZ.toFixed(1)} standard deviations above its 20-bar average.`
            : 'Breakout occurred on unremarkable volume.',
        ],
        reasonsAgainst: [
          'Failed breakouts are common; a close back through the level invalidates the scenario immediately.',
          volZ <= BREAKOUT_PARAMS.minVolumeZ ? 'Weak participation reduces conviction in the break.' : 'Volume participation was adequate.',
        ],
        parameters: { ...BREAKOUT_PARAMS },
        evidence: {
          levelPrice: level.price,
          levelTouches: level.touches,
          levelStrength: level.strength,
          breakoutTime: breakoutCandle.time,
          retestTime: retestBar.time,
          breakoutStrengthAtr: breakoutStrength,
          volumeZ: volZ,
          measuredMove,
        },
      });

      if (out.length >= 2) break;
    }

    return out;
  },
};

const REJECTION_PARAMS = {
  minLevelStrength: 0.45,
  proximityAtr: 0.5,
  minWickRatio: 0.5,
  invalidationBufferAtr: 0.5,
};

export const levelRejectionDetector: PatternDetector = {
  name: 'level_rejection',
  version: '1.0.0',
  displayName: 'Support / Resistance Rejection',
  description:
    'Price probes a high-quality horizontal level and is rejected with a dominant wick, closing back inside the range. Requires level quality from multiple touches.',
  minCandles: 80,

  detect(candles: Candle[], ind: IndicatorSnapshot, ctx: MarketContext): PatternCandidate[] {
    const out: PatternCandidate[] = [];
    const n = candles.length;
    const last = candles[n - 1];
    const atrValue = ind.atrLast;
    if (n < this.minCandles || !last || atrValue <= 0) return out;

    const range = last.high - last.low;
    if (range <= 0) return out;

    const body = Math.abs(last.close - last.open);
    const upperWick = last.high - Math.max(last.close, last.open);
    const lowerWick = Math.min(last.close, last.open) - last.low;
    const clv = closeLocationValue(last);

    for (const level of ind.levels.filter((l) => l.strength >= REJECTION_PARAMS.minLevelStrength).slice(0, 5)) {
      const proximity = atrValue * REJECTION_PARAMS.proximityAtr;

      // Bullish rejection from support: lower wick dominates, close in upper half.
      const touchedSupport = last.low <= level.price + proximity && last.close > level.price;
      const bullWick = lowerWick / range >= REJECTION_PARAMS.minWickRatio && clv > 0.2;

      // Bearish rejection from resistance: upper wick dominates, close in lower half.
      const touchedResistance = last.high >= level.price - proximity && last.close < level.price;
      const bearWick = upperWick / range >= REJECTION_PARAMS.minWickRatio && clv < -0.2;

      const isLong = touchedSupport && bullWick;
      const isShort = touchedResistance && bearWick;
      if (!isLong && !isShort) continue;

      const buffer = atrValue * REJECTION_PARAMS.invalidationBufferAtr;
      const invalidation = roundToTick(
        isLong ? Math.min(last.low, level.price) - buffer : Math.max(last.high, level.price) + buffer,
        ctx.tickSize,
      );

      // Target the next opposing level, falling back to an ATR extension.
      const opposing = ind.levels
        .filter((l) => (isLong ? l.price > last.close : l.price < last.close))
        .sort((a, b) => (isLong ? a.price - b.price : b.price - a.price))[0];

      const t1 = opposing
        ? opposing.price
        : isLong
          ? last.close + atrValue * 1.8
          : last.close - atrValue * 1.8;

      const wickRatio = isLong ? lowerWick / range : upperWick / range;
      const geometryQuality = Math.min(1, level.strength * 0.55 + wickRatio * 0.45);

      out.push({
        detectorName: this.name,
        detectorVersion: this.version,
        displayName: `${isLong ? 'Support' : 'Resistance'} Rejection`,
        direction: isLong ? 'long' : 'short',
        geometryQuality,
        confirmationIndex: n - 1,
        confirmationTime: last.time,
        entryZone: {
          from: roundToTick(Math.min(last.close, level.price), ctx.tickSize),
          to: roundToTick(Math.max(last.close, level.price), ctx.tickSize),
        },
        invalidation,
        targets: [
          { price: roundToTick(t1, ctx.tickSize), method: opposing ? 'Next opposing level' : 'ATR extension (1.8x)' },
          {
            price: roundToTick(isLong ? last.close + atrValue * 3 : last.close - atrValue * 3, ctx.tickSize),
            method: 'ATR extension (3.0x)',
          },
        ],
        overlays: [
          {
            type: 'horizontal_line',
            price: level.price,
            label: `${isLong ? 'Support' : 'Resistance'} (${level.touches} touches)`,
            color: isLong ? 'bull' : 'bear',
          },
          { type: 'invalidation_line', price: invalidation, label: 'Level failure' },
          {
            type: 'marker',
            time: last.time,
            price: isLong ? last.low : last.high,
            label: 'Rejection wick',
            color: isLong ? 'bull' : 'bear',
          },
        ],
        reasonsFor: [
          `Level has ${level.touches} historical touches with ${(level.strength * 100).toFixed(0)}% quality.`,
          `Rejection wick is ${(wickRatio * 100).toFixed(0)}% of the candle range — sellers/buyers were absorbed.`,
          `Close location value ${clv.toFixed(2)} confirms the close finished on the rejecting side.`,
        ],
        reasonsAgainst: [
          'A single rejection candle is weak evidence without follow-through on the next bar.',
          'Levels that have been tested many times tend to weaken and eventually break.',
        ],
        parameters: { ...REJECTION_PARAMS },
        evidence: {
          levelPrice: level.price,
          levelTouches: level.touches,
          wickRatio,
          closeLocationValue: clv,
          bodyRatio: body / range,
        },
      });

      break; // one rejection signal per series is enough
    }

    return out;
  },
};
