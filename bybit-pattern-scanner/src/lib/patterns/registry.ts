/** Central detector registry. Everything that scans reads from this list. */

import type { Candle } from '@/lib/bybit/types';
import type { IndicatorSnapshot, MarketContext, PatternCandidate, PatternDetector } from './types';
import { finalizeTargets } from './types';
import { structureTrendDetector } from './detectors/structure-trend';
import { breakoutRetestDetector, levelRejectionDetector } from './detectors/breakout';
import { doubleTopBottomDetector, headShouldersDetector } from './detectors/reversal';
import { flagDetector, triangleDetector, wedgeDetector } from './detectors/consolidation';
import {
  candlestickContextDetector,
  divergenceDetector,
  squeezeDetector,
  volumeBreakoutDetector,
} from './detectors/momentum';

export const DETECTORS: PatternDetector[] = [
  structureTrendDetector,
  breakoutRetestDetector,
  levelRejectionDetector,
  doubleTopBottomDetector,
  headShouldersDetector,
  triangleDetector,
  wedgeDetector,
  flagDetector,
  squeezeDetector,
  divergenceDetector,
  volumeBreakoutDetector,
  candlestickContextDetector,
];

export const DETECTOR_BY_NAME = new Map(DETECTORS.map((d) => [d.name, d]));

export function getDetector(name: string): PatternDetector | undefined {
  return DETECTOR_BY_NAME.get(name);
}

export function listDetectorMeta() {
  return DETECTORS.map((d) => ({
    name: d.name,
    version: d.version,
    displayName: d.displayName,
    description: d.description,
    minCandles: d.minCandles,
  }));
}

/**
 * Runs one detector and normalizes its scenario targets.
 *
 * Target normalization lives HERE rather than inside each detector so it cannot
 * be forgotten by a future detector. Detectors describe geometry; this layer
 * enforces that the published scenario is tradeable arithmetic — every target
 * strictly ahead of the entry and at a sane R multiple. See finalizeTargets.
 *
 * Every consumer (live scanner, backtester, tests) must go through this
 * function so live and historical behaviour can never diverge.
 */
export function runDetector(
  detector: PatternDetector,
  candles: Candle[],
  indicators: IndicatorSnapshot,
  context: MarketContext,
): PatternCandidate[] {
  if (candles.length < detector.minCandles) return [];

  let raw: PatternCandidate[];
  try {
    raw = detector.detect(candles, indicators, context);
  } catch {
    return [];
  }

  const out: PatternCandidate[] = [];
  for (const candidate of raw) {
    const targets = finalizeTargets(
      candidate.direction,
      candidate.entryZone,
      candidate.invalidation,
      candidate.targets,
      context.tickSize,
    );
    // A scenario with no reachable target is not a scenario. Drop it.
    if (targets.length === 0) continue;

    // Keep the overlay set consistent with the finalized targets.
    const overlays = [
      ...candidate.overlays.filter((o) => o.type !== 'target_line'),
      ...targets.map((t, i) => ({ type: 'target_line' as const, price: t.price, label: `T${i + 1}` })),
    ];

    out.push({ ...candidate, targets, overlays });
  }
  return out;
}

/** Runs every enabled detector over a series. */
export function runAllDetectors(
  candles: Candle[],
  indicators: IndicatorSnapshot,
  context: MarketContext,
  mutedDetectors: string[] = [],
): PatternCandidate[] {
  const out: PatternCandidate[] = [];
  for (const detector of DETECTORS) {
    if (mutedDetectors.includes(detector.name)) continue;
    out.push(...runDetector(detector, candles, indicators, context));
  }
  return out;
}
