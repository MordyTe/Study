/**
 * Classical reversal detectors: double top/bottom and head & shoulders.
 * Both confirm only on a neckline CLOSE, never on a touch.
 */

import type { Candle } from '@/lib/bybit/types';
import type { Pivot } from '@/lib/ta/structure';
import type {
  IndicatorSnapshot,
  MarketContext,
  PatternCandidate,
  PatternDetector,
} from '../types';
import { roundToTick } from '../types';

const DOUBLE_PARAMS = {
  peakToleranceAtr: 0.8,
  minSeparationBars: 5,
  maxSeparationBars: 60,
  invalidationBufferAtr: 0.5,
};

export const doubleTopBottomDetector: PatternDetector = {
  name: 'double_top_bottom',
  version: '1.0.0',
  displayName: 'Double Top / Double Bottom',
  description:
    'Two comparable pivots within an ATR-aware tolerance separated by a configurable bar distance, with a neckline drawn at the intervening extreme. Confirmed only on a neckline close.',
  minCandles: 80,

  detect(candles: Candle[], ind: IndicatorSnapshot, ctx: MarketContext): PatternCandidate[] {
    const out: PatternCandidate[] = [];
    const n = candles.length;
    const last = candles[n - 1];
    const atrValue = ind.atrLast;
    if (n < this.minCandles || !last || atrValue <= 0) return out;

    const tolerance = atrValue * DOUBLE_PARAMS.peakToleranceAtr;

    const build = (kind: 'high' | 'low'): PatternCandidate | null => {
      const pivots = ind.pivots.filter((p) => p.kind === kind).slice(-6);
      if (pivots.length < 2) return null;

      // Scan recent pivot pairs for two comparable extremes.
      for (let i = pivots.length - 1; i >= 1; i--) {
        const second = pivots[i]!;
        const first = pivots[i - 1]!;
        const separation = second.index - first.index;
        if (separation < DOUBLE_PARAMS.minSeparationBars || separation > DOUBLE_PARAMS.maxSeparationBars) continue;
        if (Math.abs(second.price - first.price) > tolerance) continue;

        // Neckline = the extreme between the two pivots.
        const between = candles.slice(first.index, second.index + 1);
        if (between.length < 3) continue;
        const neckline =
          kind === 'high' ? Math.min(...between.map((c) => c.low)) : Math.max(...between.map((c) => c.high));

        const isShort = kind === 'high';
        // Confirmation: last closed candle closed through the neckline.
        const confirmed = isShort ? last.close < neckline : last.close > neckline;
        if (!confirmed) continue;

        // Reject stale patterns: the break must be recent.
        if (n - 1 - second.index > 25) continue;

        const patternHeight = Math.abs(second.price - neckline);
        if (patternHeight < atrValue * 0.8) continue;

        const buffer = atrValue * DOUBLE_PARAMS.invalidationBufferAtr;
        const invalidation = roundToTick(
          isShort ? Math.max(first.price, second.price) + buffer : Math.min(first.price, second.price) - buffer,
          ctx.tickSize,
        );

        const symmetry = 1 - Math.abs(second.price - first.price) / (tolerance || 1);
        const geometryQuality = Math.max(0, Math.min(1, symmetry * 0.6 + Math.min(1, patternHeight / (atrValue * 3)) * 0.4));

        return {
          detectorName: doubleTopBottomDetector.name,
          detectorVersion: doubleTopBottomDetector.version,
          displayName: isShort ? 'Double Top' : 'Double Bottom',
          direction: isShort ? 'short' : 'long',
          geometryQuality,
          confirmationIndex: n - 1,
          confirmationTime: last.time,
          entryZone: {
            from: roundToTick(Math.min(neckline, last.close), ctx.tickSize),
            to: roundToTick(Math.max(neckline, last.close), ctx.tickSize),
          },
          invalidation,
          targets: [
            {
              price: roundToTick(
                isShort ? neckline - patternHeight * 0.6 : neckline + patternHeight * 0.6,
                ctx.tickSize,
              ),
              method: 'Measured move (60% of pattern height)',
            },
            {
              price: roundToTick(
                isShort ? neckline - patternHeight : neckline + patternHeight,
                ctx.tickSize,
              ),
              method: 'Measured move (100% of pattern height)',
            },
          ],
          overlays: [
            { type: 'horizontal_line', price: neckline, label: 'Neckline', color: isShort ? 'bear' : 'bull' },
            { type: 'marker', time: first.time, price: first.price, label: kind === 'high' ? 'Top 1' : 'Bottom 1', color: 'neutral' },
            { type: 'marker', time: second.time, price: second.price, label: kind === 'high' ? 'Top 2' : 'Bottom 2', color: 'neutral' },
            { type: 'invalidation_line', price: invalidation, label: 'Pattern failure' },
          ],
          reasonsFor: [
            `Two ${kind === 'high' ? 'tops' : 'bottoms'} within ${(Math.abs(second.price - first.price) / atrValue).toFixed(2)} ATR of each other — the level rejected price twice.`,
            `Neckline at ${neckline.toFixed(6)} broken by candle close, confirming the reversal.`,
            `Pattern height is ${(patternHeight / atrValue).toFixed(1)} ATR, giving the measured move meaningful room.`,
          ],
          reasonsAgainst: [
            'Double tops/bottoms fail frequently when the broader trend is strongly against the reversal.',
            'The measured-move target assumes symmetry that the market does not guarantee.',
          ],
          parameters: { ...DOUBLE_PARAMS },
          evidence: {
            pivot1Time: first.time,
            pivot1Price: first.price,
            pivot2Time: second.time,
            pivot2Price: second.price,
            neckline,
            patternHeight,
            separationBars: separation,
          },
        };
      }
      return null;
    };

    const top = build('high');
    if (top) out.push(top);
    const bottom = build('low');
    if (bottom) out.push(bottom);

    return out;
  },
};

const HS_PARAMS = {
  shoulderSymmetryTolerance: 0.35,
  minHeadProminenceAtr: 0.8,
  invalidationBufferAtr: 0.5,
  maxBarsSinceRightShoulder: 30,
};

export const headShouldersDetector: PatternDetector = {
  name: 'head_shoulders',
  version: '1.0.0',
  displayName: 'Head & Shoulders',
  description:
    'Three-pivot reversal with a prominent head, symmetric shoulders within tolerance, and a fitted neckline. Confirmed only on a neckline close.',
  minCandles: 100,

  detect(candles: Candle[], ind: IndicatorSnapshot, ctx: MarketContext): PatternCandidate[] {
    const out: PatternCandidate[] = [];
    const n = candles.length;
    const last = candles[n - 1];
    const atrValue = ind.atrLast;
    if (n < this.minCandles || !last || atrValue <= 0) return out;

    const build = (inverse: boolean): PatternCandidate | null => {
      const kind: 'high' | 'low' = inverse ? 'low' : 'high';
      const extremes = ind.pivots.filter((p) => p.kind === kind).slice(-5);
      const opposite = ind.pivots.filter((p) => p.kind === (inverse ? 'high' : 'low'));
      if (extremes.length < 3) return null;

      // Take the last three same-kind pivots as L / H / R.
      const [ls, head, rs] = extremes.slice(-3) as [Pivot, Pivot, Pivot];
      if (n - 1 - rs.index > HS_PARAMS.maxBarsSinceRightShoulder) return null;

      // Head must be the extreme of the three.
      const headIsExtreme = inverse
        ? head.price < ls.price && head.price < rs.price
        : head.price > ls.price && head.price > rs.price;
      if (!headIsExtreme) return null;

      const headProminence = inverse
        ? (Math.min(ls.price, rs.price) - head.price) / atrValue
        : (head.price - Math.max(ls.price, rs.price)) / atrValue;
      if (headProminence < HS_PARAMS.minHeadProminenceAtr) return null;

      // Shoulders should be roughly level.
      const shoulderDiff = Math.abs(ls.price - rs.price);
      const shoulderRef = Math.abs(head.price - (ls.price + rs.price) / 2) || atrValue;
      const asymmetry = shoulderDiff / shoulderRef;
      if (asymmetry > HS_PARAMS.shoulderSymmetryTolerance * 3) return null;

      // Neckline from the two opposing pivots between the shoulders.
      const troughs = opposite.filter((p) => p.index > ls.index && p.index < rs.index);
      if (troughs.length < 1) return null;
      const neckPoints = troughs.slice(-2);
      const neckline =
        neckPoints.reduce((a, p) => a + p.price, 0) / neckPoints.length;

      const confirmed = inverse ? last.close > neckline : last.close < neckline;
      if (!confirmed) return null;

      const patternHeight = Math.abs(head.price - neckline);
      const buffer = atrValue * HS_PARAMS.invalidationBufferAtr;
      const invalidation = roundToTick(
        inverse ? Math.min(ls.price, rs.price) - buffer : Math.max(ls.price, rs.price) + buffer,
        ctx.tickSize,
      );

      const geometryQuality = Math.max(
        0,
        Math.min(
          1,
          (1 - Math.min(1, asymmetry)) * 0.45 + Math.min(1, headProminence / 2.5) * 0.35 + 0.2,
        ),
      );

      return {
        detectorName: headShouldersDetector.name,
        detectorVersion: headShouldersDetector.version,
        displayName: inverse ? 'Inverse Head & Shoulders' : 'Head & Shoulders',
        direction: inverse ? 'long' : 'short',
        geometryQuality,
        confirmationIndex: n - 1,
        confirmationTime: last.time,
        entryZone: {
          from: roundToTick(Math.min(neckline, last.close), ctx.tickSize),
          to: roundToTick(Math.max(neckline, last.close), ctx.tickSize),
        },
        invalidation,
        targets: [
          {
            price: roundToTick(
              inverse ? neckline + patternHeight * 0.6 : neckline - patternHeight * 0.6,
              ctx.tickSize,
            ),
            method: 'Measured move (60% of head-to-neckline)',
          },
          {
            price: roundToTick(
              inverse ? neckline + patternHeight : neckline - patternHeight,
              ctx.tickSize,
            ),
            method: 'Measured move (100% of head-to-neckline)',
          },
        ],
        overlays: [
          { type: 'horizontal_line', price: neckline, label: 'Neckline', color: inverse ? 'bull' : 'bear' },
          { type: 'marker', time: ls.time, price: ls.price, label: 'Left shoulder', color: 'neutral' },
          { type: 'marker', time: head.time, price: head.price, label: 'Head', color: 'warn' },
          { type: 'marker', time: rs.time, price: rs.price, label: 'Right shoulder', color: 'neutral' },
          { type: 'invalidation_line', price: invalidation, label: 'Shoulder failure' },
        ],
        reasonsFor: [
          `Head stands ${headProminence.toFixed(2)} ATR beyond both shoulders — a genuine failed extension.`,
          `Shoulder asymmetry is ${(asymmetry * 100).toFixed(0)}%, within the configured tolerance.`,
          `Neckline at ${neckline.toFixed(6)} broken by close, completing the pattern.`,
        ],
        reasonsAgainst: [
          'Head & shoulders is frequently mis-identified; the pattern requires the broader context to agree.',
          'A fast reclaim of the neckline usually means the break was a liquidity grab.',
        ],
        parameters: { ...HS_PARAMS },
        evidence: {
          leftShoulder: { time: ls.time, price: ls.price },
          head: { time: head.time, price: head.price },
          rightShoulder: { time: rs.time, price: rs.price },
          neckline,
          patternHeight,
          headProminenceAtr: headProminence,
          shoulderAsymmetry: asymmetry,
        },
      };
    };

    const normal = build(false);
    if (normal) out.push(normal);
    const inverse = build(true);
    if (inverse) out.push(inverse);

    return out;
  },
};
