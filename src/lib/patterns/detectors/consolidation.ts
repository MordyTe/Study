/**
 * Consolidation / continuation geometry:
 *  - triangle: ascending, descending, symmetrical (converging trendlines)
 *  - wedge: rising / falling (converging, same-direction slopes)
 *  - flag: impulse pole + controlled counter-trend channel
 */

import type { Candle } from '@/lib/bybit/types';
import { fitTrendLine, trendLineValueAt, type TrendLine } from '@/lib/ta/structure';
import type {
  IndicatorSnapshot,
  MarketContext,
  PatternCandidate,
  PatternDetector,
} from '../types';
import { roundToTick } from '../types';

const TRI_PARAMS = {
  minTouchesPerSide: 2,
  minFit: 0.55,
  minConvergencePct: 25,
  invalidationBufferAtr: 0.5,
  lookback: 60,
};

/** Shared trendline extraction for the last `lookback` bars. */
function buildBoundaries(
  ind: IndicatorSnapshot,
  n: number,
  lookback: number,
): { upper: TrendLine | null; lower: TrendLine | null } {
  const from = Math.max(0, n - lookback);
  const highs = ind.pivots
    .filter((p) => p.kind === 'high' && p.index >= from)
    .map((p) => ({ index: p.index, time: p.time, price: p.price }));
  const lows = ind.pivots
    .filter((p) => p.kind === 'low' && p.index >= from)
    .map((p) => ({ index: p.index, time: p.time, price: p.price }));

  return {
    upper: highs.length >= TRI_PARAMS.minTouchesPerSide ? fitTrendLine(highs.slice(-4)) : null,
    lower: lows.length >= TRI_PARAMS.minTouchesPerSide ? fitTrendLine(lows.slice(-4)) : null,
  };
}

/** How much the two boundaries converge across the pattern, as a percentage. */
function convergencePct(upper: TrendLine, lower: TrendLine, startIdx: number, endIdx: number): number {
  const widthStart = trendLineValueAt(upper, startIdx) - trendLineValueAt(lower, startIdx);
  const widthEnd = trendLineValueAt(upper, endIdx) - trendLineValueAt(lower, endIdx);
  if (widthStart <= 0) return 0;
  return ((widthStart - widthEnd) / widthStart) * 100;
}

export const triangleDetector: PatternDetector = {
  name: 'triangle',
  version: '1.0.0',
  displayName: 'Triangle (Ascending / Descending / Symmetrical)',
  description:
    'Fits upper and lower trendlines through recent swing pivots, requires a minimum touch count and genuine convergence, then confirms on a close beyond a boundary before the apex.',
  minCandles: 80,

  detect(candles: Candle[], ind: IndicatorSnapshot, ctx: MarketContext): PatternCandidate[] {
    const out: PatternCandidate[] = [];
    const n = candles.length;
    const last = candles[n - 1];
    const atrValue = ind.atrLast;
    if (n < this.minCandles || !last || atrValue <= 0) return out;

    const { upper, lower } = buildBoundaries(ind, n, TRI_PARAMS.lookback);
    if (!upper || !lower) return out;
    if (upper.fit < TRI_PARAMS.minFit || lower.fit < TRI_PARAMS.minFit) return out;

    const startIdx = Math.min(upper.startIndex, lower.startIndex);
    const endIdx = n - 1;
    const conv = convergencePct(upper, lower, startIdx, endIdx);
    if (conv < TRI_PARAMS.minConvergencePct) return out;

    const upperNow = trendLineValueAt(upper, endIdx);
    const lowerNow = trendLineValueAt(lower, endIdx);
    if (!Number.isFinite(upperNow) || !Number.isFinite(lowerNow) || upperNow <= lowerNow) return out;

    // Breakout must be a close beyond a boundary.
    const brokeUp = last.close > upperNow;
    const brokeDown = last.close < lowerNow;
    if (!brokeUp && !brokeDown) return out;

    // Sanity: don't fire past the apex.
    const slopeDiff = upper.slope - lower.slope;
    const apexIdx = slopeDiff !== 0 ? (lower.intercept - upper.intercept) / slopeDiff : Infinity;
    if (Number.isFinite(apexIdx) && apexIdx < endIdx) return out;

    // Classify by boundary slopes, normalized to price.
    const priceRef = last.close || 1;
    const upSlopePct = (upper.slope / priceRef) * 100;
    const lowSlopePct = (lower.slope / priceRef) * 100;
    const flat = 0.02;

    let variant: 'ascending' | 'descending' | 'symmetrical';
    if (Math.abs(upSlopePct) < flat && lowSlopePct > flat) variant = 'ascending';
    else if (Math.abs(lowSlopePct) < flat && upSlopePct < -flat) variant = 'descending';
    else variant = 'symmetrical';

    const isLong = brokeUp;
    const height = trendLineValueAt(upper, startIdx) - trendLineValueAt(lower, startIdx);
    const boundary = isLong ? upperNow : lowerNow;
    const buffer = atrValue * TRI_PARAMS.invalidationBufferAtr;
    const invalidation = roundToTick(
      isLong ? Math.min(lowerNow, last.low) - buffer : Math.max(upperNow, last.high) + buffer,
      ctx.tickSize,
    );

    const touches = upper.points.length + lower.points.length;
    const geometryQuality = Math.min(
      1,
      ((upper.fit + lower.fit) / 2) * 0.5 + Math.min(1, conv / 60) * 0.25 + Math.min(1, touches / 8) * 0.25,
    );

    out.push({
      detectorName: this.name,
      detectorVersion: this.version,
      displayName: `${variant[0]!.toUpperCase()}${variant.slice(1)} Triangle Breakout`,
      direction: isLong ? 'long' : 'short',
      geometryQuality,
      confirmationIndex: endIdx,
      confirmationTime: last.time,
      entryZone: {
        from: roundToTick(Math.min(boundary, last.close), ctx.tickSize),
        to: roundToTick(Math.max(boundary, last.close), ctx.tickSize),
      },
      invalidation,
      targets: [
        {
          price: roundToTick(isLong ? boundary + height * 0.6 : boundary - height * 0.6, ctx.tickSize),
          method: 'Measured move (60% of triangle height)',
        },
        {
          price: roundToTick(isLong ? boundary + height : boundary - height, ctx.tickSize),
          method: 'Measured move (100% of triangle height)',
        },
      ],
      overlays: [
        {
          type: 'trend_line',
          from: { time: candles[upper.startIndex]?.time ?? last.time, price: trendLineValueAt(upper, upper.startIndex) },
          to: { time: last.time, price: upperNow },
          label: 'Upper boundary',
          color: 'bear',
        },
        {
          type: 'trend_line',
          from: { time: candles[lower.startIndex]?.time ?? last.time, price: trendLineValueAt(lower, lower.startIndex) },
          to: { time: last.time, price: lowerNow },
          label: 'Lower boundary',
          color: 'bull',
        },
        { type: 'invalidation_line', price: invalidation, label: 'Back inside triangle' },
      ],
      reasonsFor: [
        `${variant} triangle with ${touches} boundary touches and R² fits of ${upper.fit.toFixed(2)} / ${lower.fit.toFixed(2)}.`,
        `Boundaries converged ${conv.toFixed(0)}% across the pattern — genuine compression, not a random channel.`,
        `Breakout confirmed by close ${isLong ? 'above' : 'below'} the ${isLong ? 'upper' : 'lower'} boundary.`,
      ],
      reasonsAgainst: [
        'Triangle breakouts are prone to false starts; the first close beyond a boundary often reverses.',
        'Trendline fitting is sensitive to which pivots are selected — treat boundaries as zones, not exact lines.',
      ],
      parameters: { ...TRI_PARAMS, variant },
      evidence: {
        variant,
        upperFit: upper.fit,
        lowerFit: lower.fit,
        upperSlopePct: upSlopePct,
        lowerSlopePct: lowSlopePct,
        convergencePct: conv,
        touches,
        triangleHeight: height,
      },
    });

    return out;
  },
};

const WEDGE_PARAMS = {
  minFit: 0.55,
  minConvergencePct: 20,
  minSlopeAlignmentPct: 0.03,
  invalidationBufferAtr: 0.5,
  lookback: 60,
};

export const wedgeDetector: PatternDetector = {
  name: 'wedge',
  version: '1.0.0',
  displayName: 'Rising / Falling Wedge',
  description:
    'Converging boundaries that slope in the SAME direction. A rising wedge is bearish, a falling wedge is bullish. Confirmed on a close beyond the boundary.',
  minCandles: 80,

  detect(candles: Candle[], ind: IndicatorSnapshot, ctx: MarketContext): PatternCandidate[] {
    const out: PatternCandidate[] = [];
    const n = candles.length;
    const last = candles[n - 1];
    const atrValue = ind.atrLast;
    if (n < this.minCandles || !last || atrValue <= 0) return out;

    const { upper, lower } = buildBoundaries(ind, n, WEDGE_PARAMS.lookback);
    if (!upper || !lower) return out;
    if (upper.fit < WEDGE_PARAMS.minFit || lower.fit < WEDGE_PARAMS.minFit) return out;

    const priceRef = last.close || 1;
    const upSlopePct = (upper.slope / priceRef) * 100;
    const lowSlopePct = (lower.slope / priceRef) * 100;

    // Wedge requires both boundaries sloping the same way.
    const rising = upSlopePct > WEDGE_PARAMS.minSlopeAlignmentPct && lowSlopePct > WEDGE_PARAMS.minSlopeAlignmentPct;
    const falling = upSlopePct < -WEDGE_PARAMS.minSlopeAlignmentPct && lowSlopePct < -WEDGE_PARAMS.minSlopeAlignmentPct;
    if (!rising && !falling) return out;

    const startIdx = Math.min(upper.startIndex, lower.startIndex);
    const endIdx = n - 1;
    const conv = convergencePct(upper, lower, startIdx, endIdx);
    if (conv < WEDGE_PARAMS.minConvergencePct) return out;

    const upperNow = trendLineValueAt(upper, endIdx);
    const lowerNow = trendLineValueAt(lower, endIdx);

    // Rising wedge breaks down; falling wedge breaks up.
    const isLong = falling;
    const brokenOut = isLong ? last.close > upperNow : last.close < lowerNow;
    if (!brokenOut) return out;

    const height = trendLineValueAt(upper, startIdx) - trendLineValueAt(lower, startIdx);
    const buffer = atrValue * WEDGE_PARAMS.invalidationBufferAtr;
    const invalidation = roundToTick(
      isLong ? Math.min(lowerNow, last.low) - buffer : Math.max(upperNow, last.high) + buffer,
      ctx.tickSize,
    );
    const boundary = isLong ? upperNow : lowerNow;

    const geometryQuality = Math.min(
      1,
      ((upper.fit + lower.fit) / 2) * 0.5 + Math.min(1, conv / 50) * 0.3 + 0.2,
    );

    out.push({
      detectorName: this.name,
      detectorVersion: this.version,
      displayName: rising ? 'Rising Wedge (bearish)' : 'Falling Wedge (bullish)',
      direction: isLong ? 'long' : 'short',
      geometryQuality,
      confirmationIndex: endIdx,
      confirmationTime: last.time,
      entryZone: {
        from: roundToTick(Math.min(boundary, last.close), ctx.tickSize),
        to: roundToTick(Math.max(boundary, last.close), ctx.tickSize),
      },
      invalidation,
      targets: [
        {
          price: roundToTick(isLong ? boundary + height * 0.6 : boundary - height * 0.6, ctx.tickSize),
          method: 'Measured move (60% of wedge height)',
        },
        {
          price: roundToTick(isLong ? boundary + height : boundary - height, ctx.tickSize),
          method: 'Measured move (100% of wedge height)',
        },
      ],
      overlays: [
        {
          type: 'trend_line',
          from: { time: candles[upper.startIndex]?.time ?? last.time, price: trendLineValueAt(upper, upper.startIndex) },
          to: { time: last.time, price: upperNow },
          label: 'Wedge upper',
          color: 'warn',
        },
        {
          type: 'trend_line',
          from: { time: candles[lower.startIndex]?.time ?? last.time, price: trendLineValueAt(lower, lower.startIndex) },
          to: { time: last.time, price: lowerNow },
          label: 'Wedge lower',
          color: 'warn',
        },
        { type: 'invalidation_line', price: invalidation, label: 'Wedge reclaim' },
      ],
      reasonsFor: [
        `${rising ? 'Rising' : 'Falling'} wedge: both boundaries slope ${rising ? 'up' : 'down'} while converging ${conv.toFixed(0)}%.`,
        'Converging same-direction boundaries indicate momentum exhaustion in the direction of the slope.',
        `Breakout confirmed by candle close beyond the ${isLong ? 'upper' : 'lower'} boundary.`,
      ],
      reasonsAgainst: [
        'Wedges are the most subjective classical pattern; boundary selection materially changes the read.',
        'A wedge inside a strong opposing trend often continues rather than reverses.',
      ],
      parameters: { ...WEDGE_PARAMS, variant: rising ? 'rising' : 'falling' },
      evidence: {
        variant: rising ? 'rising' : 'falling',
        upperFit: upper.fit,
        lowerFit: lower.fit,
        upperSlopePct: upSlopePct,
        lowerSlopePct: lowSlopePct,
        convergencePct: conv,
        wedgeHeight: height,
      },
    });

    return out;
  },
};

const FLAG_PARAMS = {
  poleLookback: 20,
  minPoleAtr: 2.5,
  channelBars: 12,
  maxRetracePct: 62,
  minRetracePct: 15,
  invalidationBufferAtr: 0.4,
};

export const flagDetector: PatternDetector = {
  name: 'flag_channel',
  version: '1.0.0',
  displayName: 'Bull / Bear Flag',
  description:
    'A strong impulse pole followed by a controlled counter-trend channel. Retracements deeper than the configured maximum are rejected as trend failure, not consolidation.',
  minCandles: 60,

  detect(candles: Candle[], ind: IndicatorSnapshot, ctx: MarketContext): PatternCandidate[] {
    const out: PatternCandidate[] = [];
    const n = candles.length;
    const last = candles[n - 1];
    const atrValue = ind.atrLast;
    if (n < this.minCandles || !last || atrValue <= 0) return out;

    const channelStart = n - FLAG_PARAMS.channelBars;
    const poleStart = Math.max(0, channelStart - FLAG_PARAMS.poleLookback);
    if (channelStart <= poleStart) return out;

    const pole = candles.slice(poleStart, channelStart);
    const channel = candles.slice(channelStart);
    if (pole.length < 5 || channel.length < 4) return out;

    const poleLow = Math.min(...pole.map((c) => c.low));
    const poleHigh = Math.max(...pole.map((c) => c.high));
    const poleRange = poleHigh - poleLow;
    if (poleRange < atrValue * FLAG_PARAMS.minPoleAtr) return out;

    const poleFirst = pole[0]!;
    const poleLast = pole[pole.length - 1]!;
    const isBull = poleLast.close > poleFirst.open;

    // Retracement of the pole inside the channel.
    const channelExtreme = isBull
      ? Math.min(...channel.map((c) => c.low))
      : Math.max(...channel.map((c) => c.high));
    const retrace = isBull
      ? ((poleHigh - channelExtreme) / poleRange) * 100
      : ((channelExtreme - poleLow) / poleRange) * 100;

    if (retrace > FLAG_PARAMS.maxRetracePct || retrace < FLAG_PARAMS.minRetracePct) return out;

    // Continuation trigger: close beyond the channel's opposing extreme.
    const channelHigh = Math.max(...channel.slice(0, -1).map((c) => c.high));
    const channelLow = Math.min(...channel.slice(0, -1).map((c) => c.low));
    const triggered = isBull ? last.close > channelHigh : last.close < channelLow;
    if (!triggered) return out;

    const buffer = atrValue * FLAG_PARAMS.invalidationBufferAtr;
    const invalidation = roundToTick(
      isBull ? channelExtreme - buffer : channelExtreme + buffer,
      ctx.tickSize,
    );
    const breakoutLevel = isBull ? channelHigh : channelLow;

    const geometryQuality = Math.min(
      1,
      Math.min(1, poleRange / (atrValue * 5)) * 0.45 +
        (1 - Math.abs(retrace - 38) / 60) * 0.35 +
        0.2,
    );

    out.push({
      detectorName: this.name,
      detectorVersion: this.version,
      displayName: isBull ? 'Bull Flag' : 'Bear Flag',
      direction: isBull ? 'long' : 'short',
      geometryQuality: Math.max(0, geometryQuality),
      confirmationIndex: n - 1,
      confirmationTime: last.time,
      entryZone: {
        from: roundToTick(Math.min(breakoutLevel, last.close), ctx.tickSize),
        to: roundToTick(Math.max(breakoutLevel, last.close), ctx.tickSize),
      },
      invalidation,
      targets: [
        {
          price: roundToTick(
            isBull ? breakoutLevel + poleRange * 0.6 : breakoutLevel - poleRange * 0.6,
            ctx.tickSize,
          ),
          method: 'Pole projection (60%)',
        },
        {
          price: roundToTick(
            isBull ? breakoutLevel + poleRange : breakoutLevel - poleRange,
            ctx.tickSize,
          ),
          method: 'Pole projection (100%)',
        },
      ],
      overlays: [
        {
          type: 'trend_line',
          from: { time: poleFirst.time, price: isBull ? poleLow : poleHigh },
          to: { time: poleLast.time, price: isBull ? poleHigh : poleLow },
          label: 'Impulse pole',
          color: isBull ? 'bull' : 'bear',
        },
        {
          type: 'price_zone',
          from: Math.min(channelLow, channelHigh),
          to: Math.max(channelLow, channelHigh),
          label: 'Flag channel',
          color: 'neutral',
        },
        { type: 'invalidation_line', price: invalidation, label: 'Flag failure' },
      ],
      reasonsFor: [
        `Impulse pole spans ${(poleRange / atrValue).toFixed(1)} ATR — a genuine directional thrust, not drift.`,
        `Retracement of ${retrace.toFixed(0)}% stayed within the healthy consolidation band.`,
        'Close beyond the flag channel confirms the continuation trigger.',
      ],
      reasonsAgainst: [
        'Flags fail when the impulse was itself the end of a move rather than the start.',
        'The pole-projection target assumes the second leg matches the first, which is not guaranteed.',
      ],
      parameters: { ...FLAG_PARAMS },
      evidence: {
        poleStartTime: poleFirst.time,
        poleEndTime: poleLast.time,
        poleRange,
        poleAtrMultiple: poleRange / atrValue,
        retracePct: retrace,
        channelHigh,
        channelLow,
      },
    });

    return out;
  },
};
