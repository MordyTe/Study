/**
 * Market structure trend detector.
 * Fires on a Break of Structure (continuation) or Change of Character (reversal
 * warning) confirmed by a candle CLOSE beyond the relevant swing.
 */

import type { Candle } from '@/lib/bybit/types';
import type {
  IndicatorSnapshot,
  MarketContext,
  PatternCandidate,
  PatternDetector,
} from '../types';
import { roundToTick } from '../types';

const PARAMS = {
  atrBufferMult: 0.6,
  minAdx: 18,
  target1Atr: 1.5,
  target2Atr: 3.0,
};

export const structureTrendDetector: PatternDetector = {
  name: 'structure_trend',
  version: '1.0.0',
  displayName: 'Market Structure Break',
  description:
    'Detects Break of Structure (trend continuation) and Change of Character (early reversal) using ATR-adaptive swing pivots. Requires a close beyond the swing, not a wick.',
  minCandles: 60,

  detect(candles: Candle[], ind: IndicatorSnapshot, ctx: MarketContext): PatternCandidate[] {
    const out: PatternCandidate[] = [];
    const n = candles.length;
    if (n < this.minCandles) return out;

    const last = candles[n - 1];
    const atrValue = ind.atrLast;
    if (!last || atrValue <= 0) return out;

    const { structure } = ind;
    const adxNow = ind.adx[n - 1] ?? 0;

    // ── Break of Structure: continuation in the established direction ──
    if (structure.breakOfStructure && (adxNow ?? 0) >= PARAMS.minAdx) {
      const isLong = structure.state === 'uptrend';
      const brokenPivot = isLong ? structure.lastHigh : structure.lastLow;
      const anchor = isLong ? structure.lastLow : structure.lastHigh;
      if (brokenPivot && anchor) {
        const buffer = atrValue * PARAMS.atrBufferMult;
        const entryFrom = roundToTick(brokenPivot.price, ctx.tickSize);
        const entryTo = roundToTick(last.close, ctx.tickSize);
        const invalidation = roundToTick(
          isLong ? anchor.price - buffer : anchor.price + buffer,
          ctx.tickSize,
        );

        const fitQuality = Math.min(1, structure.confidence * 0.7 + Math.min(1, (adxNow ?? 0) / 40) * 0.3);

        out.push({
          detectorName: this.name,
          detectorVersion: this.version,
          displayName: `Break of Structure (${isLong ? 'bullish' : 'bearish'})`,
          direction: isLong ? 'long' : 'short',
          geometryQuality: fitQuality,
          confirmationIndex: n - 1,
          confirmationTime: last.time,
          entryZone: {
            from: Math.min(entryFrom, entryTo),
            to: Math.max(entryFrom, entryTo),
          },
          invalidation,
          targets: [
            {
              price: roundToTick(
                isLong ? last.close + atrValue * PARAMS.target1Atr : last.close - atrValue * PARAMS.target1Atr,
                ctx.tickSize,
              ),
              method: `ATR extension (${PARAMS.target1Atr}x ATR14)`,
            },
            {
              price: roundToTick(
                isLong ? last.close + atrValue * PARAMS.target2Atr : last.close - atrValue * PARAMS.target2Atr,
                ctx.tickSize,
              ),
              method: `ATR extension (${PARAMS.target2Atr}x ATR14)`,
            },
          ],
          overlays: [
            {
              type: 'horizontal_line',
              price: brokenPivot.price,
              label: 'Broken swing',
              color: isLong ? 'bull' : 'bear',
            },
            { type: 'invalidation_line', price: invalidation, label: 'Structure invalidation' },
            {
              type: 'marker',
              time: last.time,
              price: last.close,
              label: 'BOS close',
              color: isLong ? 'bull' : 'bear',
            },
          ],
          reasonsFor: [
            `Structure is ${structure.state} with a confirmed break of the prior swing ${isLong ? 'high' : 'low'}.`,
            `Break confirmed by candle close (${last.close}), not a wick.`,
            `ADX ${(adxNow ?? 0).toFixed(1)} indicates a directional (non-choppy) regime.`,
          ],
          reasonsAgainst: [
            'Break-of-structure entries chase momentum; a deep retrace can hit invalidation before continuation.',
            ctx.higherTimeframeBias && ctx.higherTimeframeBias !== structure.state
              ? `Higher timeframe bias is ${ctx.higherTimeframeBias}, which conflicts with this setup.`
              : 'No higher-timeframe conflict detected.',
          ],
          parameters: { ...PARAMS },
          evidence: {
            structureState: structure.state,
            brokenPivotTime: brokenPivot.time,
            brokenPivotPrice: brokenPivot.price,
            anchorPivotTime: anchor.time,
            anchorPivotPrice: anchor.price,
            adx: adxNow,
          },
        });
      }
    }

    // ── Change of Character: early reversal signal ──
    if (structure.changeOfCharacter) {
      const isLong = structure.state === 'downtrend'; // downtrend broken upward
      const brokenPivot = isLong ? structure.lastHigh : structure.lastLow;
      if (brokenPivot) {
        const buffer = atrValue * PARAMS.atrBufferMult;
        const recentExtreme = isLong
          ? Math.min(...candles.slice(-10).map((c) => c.low))
          : Math.max(...candles.slice(-10).map((c) => c.high));
        const invalidation = roundToTick(
          isLong ? recentExtreme - buffer : recentExtreme + buffer,
          ctx.tickSize,
        );

        out.push({
          detectorName: this.name,
          detectorVersion: this.version,
          displayName: `Change of Character (${isLong ? 'bullish' : 'bearish'})`,
          direction: isLong ? 'long' : 'short',
          geometryQuality: Math.min(0.75, structure.confidence),
          confirmationIndex: n - 1,
          confirmationTime: last.time,
          entryZone: {
            from: roundToTick(Math.min(brokenPivot.price, last.close), ctx.tickSize),
            to: roundToTick(Math.max(brokenPivot.price, last.close), ctx.tickSize),
          },
          invalidation,
          targets: [
            {
              price: roundToTick(
                isLong ? last.close + atrValue * 2 : last.close - atrValue * 2,
                ctx.tickSize,
              ),
              method: 'ATR extension (2.0x ATR14)',
            },
            {
              price: roundToTick(
                isLong ? last.close + atrValue * 3.5 : last.close - atrValue * 3.5,
                ctx.tickSize,
              ),
              method: 'ATR extension (3.5x ATR14)',
            },
          ],
          overlays: [
            {
              type: 'horizontal_line',
              price: brokenPivot.price,
              label: 'CHoCH level',
              color: isLong ? 'bull' : 'bear',
            },
            { type: 'invalidation_line', price: invalidation, label: 'Reversal invalidation' },
          ],
          reasonsFor: [
            `First counter-trend structural break against the prevailing ${structure.state}.`,
            'Close beyond the opposing swing suggests the trend is losing control.',
          ],
          reasonsAgainst: [
            'Change of Character is an early signal; the prior trend frequently resumes.',
            'Best treated as a warning to reduce trend exposure rather than a standalone reversal entry.',
          ],
          parameters: { ...PARAMS, mode: 'choch' },
          evidence: {
            structureState: structure.state,
            brokenPivotTime: brokenPivot.time,
            brokenPivotPrice: brokenPivot.price,
          },
        });
      }
    }

    return out;
  },
};
