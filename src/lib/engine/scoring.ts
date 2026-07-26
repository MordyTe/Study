/**
 * Explainable Setup Quality Score, 0–100.
 *
 * THIS IS NOT A WIN PROBABILITY. It measures how well-formed and well-supported
 * a setup is against the configured criteria. Probability would require a
 * separately validated calibration model on resolved outcomes — see
 * docs/SCORING_MODEL.md.
 *
 * Component maxima (sum = 100):
 *   geometry 25 | confirmation 20 | regime 15 | volumeMomentum 15
 *   multiTimeframe 10 | liquidity 10 | dataQuality 5
 */

import type { IndicatorSnapshot, MarketContext, PatternCandidate } from '@/lib/patterns/types';
import { rewardToRisk } from '@/lib/patterns/types';
import type { Settings } from '@/lib/config/settings';

export interface ScoreComponent {
  key: string;
  label: string;
  value: number;
  max: number;
  detail: string;
}

export interface ScorePenalty {
  key: string;
  label: string;
  value: number;
  detail: string;
}

export interface ScoreResult {
  total: number;
  components: ScoreComponent[];
  penalties: ScorePenalty[];
  rewardToRisk: number;
}

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

export function scoreCandidate(
  candidate: PatternCandidate,
  ind: IndicatorSnapshot,
  ctx: MarketContext,
  settings: Settings,
  dataQuality: { verified: boolean; ageMs: number; reconciled: boolean },
): ScoreResult {
  const components: ScoreComponent[] = [];
  const penalties: ScorePenalty[] = [];

  const n = ind.closes.length;
  const lastClose = ind.closes[n - 1] ?? 0;
  const atrValue = ind.atrLast;

  // ── 1. Pattern geometry and fit (25) ──────────────────────────────────
  const geometry = clamp(candidate.geometryQuality, 0, 1) * 25;
  components.push({
    key: 'geometry',
    label: 'Pattern geometry & fit',
    value: Number(geometry.toFixed(1)),
    max: 25,
    detail: `Detector conviction ${(candidate.geometryQuality * 100).toFixed(0)}% from ${candidate.detectorName}@${candidate.detectorVersion}.`,
  });

  // ── 2. Confirmation quality (20) ──────────────────────────────────────
  // Rewards a decisive confirming candle: real body, closing in the direction.
  const confIdx = candidate.confirmationIndex;
  const cHigh = ind.highs[confIdx] ?? 0;
  const cLow = ind.lows[confIdx] ?? 0;
  const cClose = ind.closes[confIdx] ?? 0;
  const cRange = cHigh - cLow;
  const closePosition =
    cRange > 0 ? (candidate.direction === 'long' ? (cClose - cLow) / cRange : (cHigh - cClose) / cRange) : 0.5;
  const rangeStrength = atrValue > 0 ? clamp(cRange / atrValue, 0, 1.5) / 1.5 : 0;
  const confirmation = (closePosition * 0.6 + rangeStrength * 0.4) * 20;
  components.push({
    key: 'confirmation',
    label: 'Confirmation quality',
    value: Number(confirmation.toFixed(1)),
    max: 20,
    detail: `Confirming candle closed ${(closePosition * 100).toFixed(0)}% toward the ${candidate.direction === 'long' ? 'high' : 'low'} with a ${(cRange / (atrValue || 1)).toFixed(2)} ATR range.`,
  });

  // ── 3. Market structure / regime alignment (15) ───────────────────────
  const adxNow = ind.adx[n - 1] ?? 0;
  const structureAligned =
    (candidate.direction === 'long' && ind.structure.state === 'uptrend') ||
    (candidate.direction === 'short' && ind.structure.state === 'downtrend');
  const structureOpposed =
    (candidate.direction === 'long' && ind.structure.state === 'downtrend') ||
    (candidate.direction === 'short' && ind.structure.state === 'uptrend');

  let regime = structureAligned ? 11 : structureOpposed ? 3 : 7;
  regime += clamp((adxNow ?? 0) / 40, 0, 1) * 4;
  components.push({
    key: 'regime',
    label: 'Structure / regime alignment',
    value: Number(regime.toFixed(1)),
    max: 15,
    detail: `Local structure is ${ind.structure.state} (ADX ${(adxNow ?? 0).toFixed(1)}); setup is ${structureAligned ? 'aligned' : structureOpposed ? 'counter-trend' : 'neutral'}.`,
  });

  // ── 4. Volume and momentum confirmation (15) ──────────────────────────
  const volZ = ind.volumeZ[confIdx] ?? 0;
  const rsiNow = ind.rsi[n - 1] ?? 50;
  const macdHist = ind.macd.histogram[n - 1] ?? 0;
  const momentumAgrees =
    (candidate.direction === 'long' && (macdHist ?? 0) > 0) ||
    (candidate.direction === 'short' && (macdHist ?? 0) < 0);
  const volumeScore = clamp((volZ ?? 0) / 2.5, 0, 1) * 9;
  const momentumScore = momentumAgrees ? 6 : 2;
  const volumeMomentum = volumeScore + momentumScore;
  components.push({
    key: 'volumeMomentum',
    label: 'Volume & momentum',
    value: Number(volumeMomentum.toFixed(1)),
    max: 15,
    detail: `Confirming-bar volume ${(volZ ?? 0).toFixed(1)}σ; MACD histogram ${momentumAgrees ? 'agrees with' : 'opposes'} the direction (RSI ${(rsiNow ?? 50).toFixed(0)}).`,
  });

  // ── 5. Multi-timeframe alignment (10) ─────────────────────────────────
  let multiTimeframe = 5;
  let mtfDetail = 'No higher-timeframe context available.';
  if (ctx.higherTimeframeBias) {
    const htfAligned =
      (candidate.direction === 'long' && ctx.higherTimeframeBias === 'uptrend') ||
      (candidate.direction === 'short' && ctx.higherTimeframeBias === 'downtrend');
    const htfOpposed =
      (candidate.direction === 'long' && ctx.higherTimeframeBias === 'downtrend') ||
      (candidate.direction === 'short' && ctx.higherTimeframeBias === 'uptrend');
    multiTimeframe = htfAligned ? 10 : htfOpposed ? 1 : 5;
    mtfDetail = `Higher timeframe bias is ${ctx.higherTimeframeBias} — ${htfAligned ? 'aligned' : htfOpposed ? 'conflicting' : 'neutral'}.`;
  }
  components.push({
    key: 'multiTimeframe',
    label: 'Multi-timeframe alignment',
    value: multiTimeframe,
    max: 10,
    detail: mtfDetail,
  });

  // ── 6. Liquidity and spread (10) ──────────────────────────────────────
  const turnoverScore = clamp(Math.log10(Math.max(1, ctx.turnover24h) / 1_000_000) / 2, 0, 1) * 6;
  const spreadScore =
    ctx.spreadBps === null ? 2.5 : clamp(1 - ctx.spreadBps / (settings.maxSpreadBps || 15), 0, 1) * 4;
  const liquidity = turnoverScore + spreadScore;
  components.push({
    key: 'liquidity',
    label: 'Liquidity & spread',
    value: Number(liquidity.toFixed(1)),
    max: 10,
    detail: `24h turnover $${(ctx.turnover24h / 1_000_000).toFixed(1)}M; spread ${ctx.spreadBps === null ? 'unknown' : `${ctx.spreadBps.toFixed(1)} bps`}.`,
  });

  // ── 7. Data verification quality (5) ──────────────────────────────────
  let dataScore = 0;
  if (dataQuality.verified) dataScore += 2;
  if (dataQuality.reconciled) dataScore += 2;
  if (dataQuality.ageMs <= settings.maxDataAgeMs) dataScore += 1;
  components.push({
    key: 'dataQuality',
    label: 'Data verification',
    value: dataScore,
    max: 5,
    detail: `${dataQuality.verified ? 'Verified' : 'Unverified'} against Bybit V5; REST/series reconciliation ${dataQuality.reconciled ? 'passed' : 'not confirmed'}; data age ${(dataQuality.ageMs / 1000).toFixed(0)}s.`,
  });

  // ── Penalties ─────────────────────────────────────────────────────────
  const bestTarget = candidate.targets[0]?.price ?? lastClose;
  const entryRef = candidate.direction === 'long' ? candidate.entryZone.to : candidate.entryZone.from;
  const rr = rewardToRisk(candidate.direction, entryRef, candidate.invalidation, bestTarget);

  if (rr < settings.minRewardToRisk) {
    const deficit = clamp((settings.minRewardToRisk - rr) * 6, 0, 18);
    penalties.push({
      key: 'poor_asymmetry',
      label: 'Poor reward-to-risk',
      value: -Number(deficit.toFixed(1)),
      detail: `Estimated R:R of ${rr.toFixed(2)} is below the configured minimum of ${settings.minRewardToRisk}.`,
    });
  }

  if (ctx.turnover24h < settings.minTurnover24h) {
    penalties.push({
      key: 'thin_turnover',
      label: 'Thin turnover',
      value: -12,
      detail: `24h turnover of $${(ctx.turnover24h / 1_000_000).toFixed(2)}M is below the $${(settings.minTurnover24h / 1_000_000).toFixed(1)}M floor.`,
    });
  }

  if (ctx.spreadBps !== null && ctx.spreadBps > settings.maxSpreadBps) {
    penalties.push({
      key: 'wide_spread',
      label: 'Excessive spread',
      value: -8,
      detail: `Spread of ${ctx.spreadBps.toFixed(1)} bps exceeds the ${settings.maxSpreadBps} bps limit.`,
    });
  }

  if (ctx.launchTime) {
    const ageDays = (Date.now() - ctx.launchTime) / 86_400_000;
    if (ageDays < settings.minInstrumentAgeDays) {
      penalties.push({
        key: 'new_instrument',
        label: 'Very new instrument',
        value: -10,
        detail: `Listed ${ageDays.toFixed(1)} days ago; price history is too short for reliable levels.`,
      });
    }
  }

  if (n < 150) {
    penalties.push({
      key: 'incomplete_history',
      label: 'Incomplete history',
      value: -5,
      detail: `Only ${n} candles available; longer-horizon structure cannot be assessed.`,
    });
  }

  // Nearby opposing level between entry and first target blocks the path.
  const opposing = ind.levels.find((l) => {
    const between =
      candidate.direction === 'long' ? l.price > entryRef && l.price < bestTarget : l.price < entryRef && l.price > bestTarget;
    return between && l.strength >= 0.5;
  });
  if (opposing) {
    penalties.push({
      key: 'blocking_level',
      label: 'Opposing level in the path',
      value: -6,
      detail: `A level at ${opposing.price.toFixed(6)} with ${opposing.touches} touches sits between the entry and the first target.`,
    });
  }

  // Extreme funding on perpetuals signals crowded positioning.
  if (ctx.fundingRate !== null && Math.abs(ctx.fundingRate) > 0.0005) {
    const crowded =
      (candidate.direction === 'long' && ctx.fundingRate > 0) ||
      (candidate.direction === 'short' && ctx.fundingRate < 0);
    if (crowded) {
      penalties.push({
        key: 'extreme_funding',
        label: 'Crowded funding',
        value: -5,
        detail: `Funding rate ${(ctx.fundingRate * 100).toFixed(4)}% means the side you would join is already paying to hold — squeeze risk.`,
      });
    }
  }

  const ageMinutes = (Date.now() - candidate.confirmationTime) / 60_000;
  if (ageMinutes > 240) {
    penalties.push({
      key: 'stale_setup',
      label: 'Stale setup',
      value: -Number(clamp((ageMinutes - 240) / 60, 0, 10).toFixed(1)),
      detail: `Confirmed ${(ageMinutes / 60).toFixed(1)} hours ago; the entry zone may no longer be relevant.`,
    });
  }

  const rawTotal =
    components.reduce((a, c) => a + c.value, 0) + penalties.reduce((a, p) => a + p.value, 0);

  return {
    total: Number(clamp(rawTotal, 0, 100).toFixed(1)),
    components,
    penalties,
    rewardToRisk: Number(rr.toFixed(2)),
  };
}
