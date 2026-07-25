/** Opportunity model, fingerprinting, and lifecycle evaluation. */

import type { MarketCategory, Timeframe } from '@/lib/bybit/types';
import type { Direction, Overlay, PatternStatus } from '@/lib/patterns/types';
import type { ScoreComponent, ScorePenalty } from './scoring';

export interface DataVerificationRecord {
  id: string;
  source: 'Bybit V5 Official';
  /** Bybit server time at verification. */
  exchangeTimestamp: number;
  /** Local clock at receipt. */
  localTimestamp: number;
  clockDriftMs: number;
  dataAgeMs: number;
  restLatencyMs: number;
  /** Latest closed candle close vs the live ticker last price. */
  reconciliationPassed: boolean;
  reconciliationDeltaPct: number | null;
  candleGapsDetected: number;
  health: 'HEALTHY' | 'DEGRADED' | 'STALE' | 'DISCONNECTED' | 'RECOVERING';
  notes: string[];
}

export interface Opportunity {
  id: string;
  /** Stable identity across scans. Used for de-duplication. */
  fingerprint: string;

  instrumentId: string;
  category: MarketCategory;
  symbol: string;
  timeframe: Timeframe;

  detectorName: string;
  detectorVersion: string;
  patternDisplayName: string;
  direction: Direction;
  status: PatternStatus;

  score: number;
  scoreComponents: ScoreComponent[];
  scorePenalties: ScorePenalty[];
  rewardToRisk: number;

  lastPrice: number;
  entryZone: { from: number; to: number };
  invalidation: number;
  targets: { price: number; method: string; reached: boolean }[];

  overlays: Overlay[];
  reasonsFor: string[];
  reasonsAgainst: string[];
  parameters: Record<string, number | string | boolean>;
  evidence: Record<string, unknown>;

  verification: DataVerificationRecord;

  detectedAt: number;
  confirmationTime: number;
  updatedAt: number;
  expiresAt: number;

  /** Lifecycle flags tracked after confirmation. */
  entryZoneTouched: boolean;
  maxFavorableExcursionPct: number;
  maxAdverseExcursionPct: number;

  alertSent: boolean;
  events: OpportunityEvent[];
}

export interface OpportunityEvent {
  at: number;
  type: PatternStatus | 'ENTRY_ZONE_TOUCHED' | 'SCORE_UPDATED' | 'DATA_DEGRADED';
  detail: string;
}

/**
 * Stable fingerprint. Anchors are quantized to the timeframe so a redetection of
 * the same geometry on the next scan collapses onto the same identity.
 */
export function buildFingerprint(input: {
  category: MarketCategory;
  symbol: string;
  timeframe: Timeframe;
  detectorName: string;
  detectorVersion: string;
  direction: Direction;
  confirmationTime: number;
}): string {
  return [
    'bybit',
    input.category,
    input.symbol,
    input.timeframe,
    input.detectorName,
    input.detectorVersion,
    input.direction,
    String(input.confirmationTime),
  ].join('|');
}

/** Short, human-friendly id derived from the fingerprint (stable, no crypto dep). */
export function fingerprintToId(fingerprint: string): string {
  let h1 = 0x811c9dc5;
  let h2 = 0x01000193;
  for (let i = 0; i < fingerprint.length; i++) {
    const c = fingerprint.charCodeAt(i);
    h1 = Math.imul(h1 ^ c, 0x01000193) >>> 0;
    h2 = Math.imul(h2 + c, 0x85ebca6b) >>> 0;
  }
  return (h1.toString(36) + h2.toString(36)).slice(0, 12);
}

/**
 * Advances an opportunity's lifecycle against a fresh price observation.
 * Pure: returns a new object, never mutates.
 */
export function evaluateLifecycle(
  opp: Opportunity,
  currentPrice: number,
  now: number = Date.now(),
): Opportunity {
  if (
    opp.status === 'INVALIDATED' ||
    opp.status === 'EXPIRED' ||
    opp.status === 'CLOSED_TRACKING'
  ) {
    return opp;
  }

  const events: OpportunityEvent[] = [];
  let status: PatternStatus = opp.status;
  const targets = opp.targets.map((t) => ({ ...t }));

  const isLong = opp.direction === 'long';
  const entryMid = (opp.entryZone.from + opp.entryZone.to) / 2;

  // Excursions, measured from the entry-zone midpoint.
  const movePct = entryMid > 0 ? ((currentPrice - entryMid) / entryMid) * 100 : 0;
  const favorable = isLong ? movePct : -movePct;
  const adverse = isLong ? -movePct : movePct;

  const maxFavorableExcursionPct = Math.max(opp.maxFavorableExcursionPct, favorable);
  const maxAdverseExcursionPct = Math.max(opp.maxAdverseExcursionPct, adverse);

  // Entry-zone touch.
  let entryZoneTouched = opp.entryZoneTouched;
  if (!entryZoneTouched && currentPrice >= opp.entryZone.from && currentPrice <= opp.entryZone.to) {
    entryZoneTouched = true;
    events.push({ at: now, type: 'ENTRY_ZONE_TOUCHED', detail: `Price ${currentPrice} entered the scenario zone.` });
  }

  // Invalidation takes precedence over targets.
  const invalidated = isLong ? currentPrice <= opp.invalidation : currentPrice >= opp.invalidation;
  if (invalidated) {
    status = 'INVALIDATED';
    events.push({
      at: now,
      type: 'INVALIDATED',
      detail: `Price ${currentPrice} breached the invalidation level ${opp.invalidation}.`,
    });
  } else {
    for (let i = 0; i < targets.length; i++) {
      const t = targets[i]!;
      if (t.reached) continue;
      const hit = isLong ? currentPrice >= t.price : currentPrice <= t.price;
      if (hit) {
        t.reached = true;
        const type: PatternStatus = i === 0 ? 'TARGET_1_REACHED' : 'TARGET_2_REACHED';
        status = type;
        events.push({ at: now, type, detail: `Price reached target ${i + 1} at ${t.price}.` });
      }
    }

    if (status !== 'TARGET_2_REACHED' && now > opp.expiresAt) {
      status = 'EXPIRED';
      events.push({ at: now, type: 'EXPIRED', detail: 'Scenario expired before resolving.' });
    }
  }

  // Both targets hit ends active tracking.
  if (targets.length > 0 && targets.every((t) => t.reached)) status = 'CLOSED_TRACKING';

  return {
    ...opp,
    status,
    targets,
    lastPrice: currentPrice,
    entryZoneTouched,
    maxFavorableExcursionPct: Number(maxFavorableExcursionPct.toFixed(3)),
    maxAdverseExcursionPct: Number(maxAdverseExcursionPct.toFixed(3)),
    updatedAt: now,
    events: [...opp.events, ...events],
  };
}

/** How long a scenario stays actionable, by timeframe. */
export const EXPIRY_BARS = 24;

export function computeExpiry(confirmationTime: number, timeframeMs: number): number {
  return confirmationTime + timeframeMs * EXPIRY_BARS;
}
