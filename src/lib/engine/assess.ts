/**
 * The assessment: EvidenceBundle -> Candidate.
 *
 * A pure function. No clock, no network, no model. Given the same bundle and
 * book it returns byte-identical output, which is what lets the backtest reuse
 * this exact code path and what makes the determinism test meaningful.
 *
 * The structure is deliberately gate-first. Every reason to abstain is checked
 * and collected BEFORE any probability is computed, because the failure mode
 * this system most needs to avoid is a confident number resting on evidence
 * that never justified one.
 */

import {
  buildResidualDistribution,
  type ResidualDistribution,
} from '@/lib/estimate/residuals';
import { thresholdProbability, type ThresholdSpec } from '@/lib/estimate/threshold';
import { resolveFeeModel, type FeeCategory, type FeeModel } from '@/lib/estimate/fees';
import {
  DEFAULT_SIZING_LIMITS,
  recommendSize,
  sizeCurve,
  type EdgeAtSize,
  type SizingLimits,
  type SizingRecommendation,
} from '@/lib/estimate/sizing';
import type { EvidenceBundle } from '@/lib/agents/types';
import type { OrderBook } from '@/lib/polymarket/types';
import {
  DEFAULT_VERIFICATION_LIMITS,
  buildVerificationRecord,
  isVerified,
  type VerificationLimits,
  type VerificationRecord,
} from './verification';

export type CandidateStatus = 'ABSTAIN' | 'WATCH' | 'ACTIONABLE';

export interface Candidate {
  id: string;
  fingerprint: string;
  marketId: string;
  question: string;
  decisionAt: number;
  status: CandidateStatus;
  /** The system's probability that the market resolves YES. Null when abstaining. */
  fairProbability: number | null;
  /** Best ask on the YES token — what it would cost to take. */
  marketPrice: number | null;
  /** fair − price, before fees. Null when abstaining. */
  grossEdge: number | null;
  /** Dollars per share the fee schedule takes at this price. */
  feeHurdle: number | null;
  sizing: SizingRecommendation | null;
  curve: EdgeAtSize[];
  residuals: Pick<ResidualDistribution, 'n' | 'sd' | 'iqr' | 'bias' | 'biasCorrected'> | null;
  verification: VerificationRecord;
  /** How the number was reached, in order. Empty when abstaining. */
  reasoning: string[];
  /** Why no number was produced. Empty when not abstaining. */
  abstentionReasons: string[];
  /** Every modelling assumption baked into this result, shipped with it. */
  assumptions: string[];
}

export interface AssessOptions {
  feeCategory: FeeCategory | null;
  venueFeeCoefficient: number | null;
  sizingLimits?: SizingLimits;
  verificationLimits?: VerificationLimits;
  /** Minimum expected return on notional before a candidate is ACTIONABLE. */
  minExpectedReturn?: number;
  /** Horizon tolerance when matching historical residuals, in days. */
  horizonToleranceDays?: number;
}

export const DEFAULT_MIN_EXPECTED_RETURN = 0.03;

/**
 * A readable, greppable identity. The agent versions are inside it on purpose:
 * retuning a prompt creates new identities rather than silently mutating the
 * history of the old ones.
 */
export function buildFingerprint(input: {
  marketId: string;
  agentVersions: string;
  threshold: number;
  comparator: string;
}): string {
  return [
    'polymarket',
    input.marketId,
    input.agentVersions,
    input.comparator,
    String(input.threshold),
  ].join('|');
}

export function fingerprintToId(fingerprint: string): string {
  let hash = 0x811c9dc5;
  for (let i = 0; i < fingerprint.length; i++) {
    hash ^= fingerprint.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash.toString(36).padStart(7, '0').slice(0, 12);
}

function daysBetween(fromMs: number, toIso: string | null): number | null {
  if (!toIso) return null;
  const to = Date.parse(toIso);
  if (!Number.isFinite(to)) return null;
  return (to - fromMs) / 86_400_000;
}

export function assess(
  bundle: EvidenceBundle,
  book: OrderBook | null,
  question: string,
  options: AssessOptions,
): Candidate {
  const sizingLimits = options.sizingLimits ?? DEFAULT_SIZING_LIMITS;
  const minExpectedReturn = options.minExpectedReturn ?? DEFAULT_MIN_EXPECTED_RETURN;
  const feeModel: FeeModel = resolveFeeModel(options.feeCategory, options.venueFeeCoefficient);
  const verification = buildVerificationRecord(bundle, book, options.verificationLimits);

  const agentVersions = bundle.agentsRun.map((a) => `${a.name}@${a.version}`).join(',');
  const spec = bundle.spec;

  const fingerprint = buildFingerprint({
    marketId: bundle.marketId,
    agentVersions,
    threshold: spec?.threshold ?? Number.NaN,
    comparator: spec?.comparator ?? 'none',
  });

  const assumptions = [
    feeModel.detail,
    `Sizing: ${sizingLimits.kellyMultiplier}x Kelly on a $${sizingLimits.bankrollUsd} bankroll, ` +
      `capped at ${(sizingLimits.maxPositionFraction * 100).toFixed(0)}% per position.`,
    `Fills are simulated by walking real book depth and paying the taker fee. Maker rebates, ` +
      `queue position, and price movement between decision and fill are NOT modelled.`,
    `Probabilities come from a kernel-smoothed empirical distribution of historical forecast ` +
      `error, floored at the model-risk bound. They are not calibrated until the reliability ` +
      `curve says so.`,
  ];

  const base = {
    id: fingerprintToId(fingerprint),
    fingerprint,
    marketId: bundle.marketId,
    question,
    decisionAt: bundle.decisionAt,
    curve: [] as EdgeAtSize[],
    verification,
    assumptions,
  };

  // -- Gates. Collected in full rather than short-circuiting, so the UI can
  //    show everything that is wrong at once instead of one thing at a time.
  const abstentionReasons: string[] = [];

  if (!spec) abstentionReasons.push('No machine-readable resolution spec could be extracted.');
  if (spec && spec.unresolvedAmbiguities.length > 0) {
    abstentionReasons.push(
      `The resolution criteria carry unresolved ambiguity: ${spec.unresolvedAmbiguities.join('; ')}`,
    );
  }
  if (!bundle.pointEstimate) abstentionReasons.push('No point estimate was gathered.');

  const horizonDays =
    bundle.pointEstimate?.horizonDays ??
    daysBetween(bundle.decisionAt, spec?.releaseAtIso ?? null) ??
    null;

  let dist: ResidualDistribution | null = null;
  if (horizonDays === null) {
    abstentionReasons.push('The horizon to the release could not be determined.');
  } else {
    dist = buildResidualDistribution(bundle.observations, {
      targetHorizonDays: horizonDays,
      horizonToleranceDays: options.horizonToleranceDays ?? 7,
    });
    if (!dist) {
      abstentionReasons.push(
        'Too few comparable historical forecast errors to build a residual distribution.',
      );
    }
  }

  if (!book || book.asks.length === 0) {
    abstentionReasons.push('No resting asks — the position could not be taken at any size.');
  }

  if (abstentionReasons.length > 0 || !spec || !bundle.pointEstimate || !dist || !book) {
    return {
      ...base,
      status: 'ABSTAIN',
      fairProbability: null,
      marketPrice: null,
      grossEdge: null,
      feeHurdle: null,
      sizing: null,
      residuals: null,
      reasoning: [],
      abstentionReasons,
    };
  }

  // -- Everything below this line has passed the gates.
  const thresholdSpec: ThresholdSpec = {
    threshold: spec.threshold,
    comparator: spec.comparator,
    rounding: spec.rounding,
  };

  const estimate = thresholdProbability(bundle.pointEstimate.value, thresholdSpec, dist);
  const fair = estimate.probability;
  const bestAsk = book.asks[0]!.price;
  const grossEdge = fair - bestAsk;

  const sizing = recommendSize(book.asks, fair, feeModel, sizingLimits);
  const curve = sizeCurve(book.asks, fair, feeModel, Math.max(sizing.notional, 1), 12);
  const atRecommended = curve.find((c) => c.notional >= sizing.notional) ?? curve[curve.length - 1];
  const expectedReturn = atRecommended?.expectedReturn ?? 0;

  const meetsReturn = expectedReturn >= minExpectedReturn;
  const status: CandidateStatus =
    sizing.notional > 0 && meetsReturn && isVerified(verification) ? 'ACTIONABLE' : 'WATCH';

  const reasoning = [
    ...estimate.reasoning,
    `Best ask ${bestAsk.toFixed(4)}; gross edge ${(grossEdge * 100).toFixed(2)}¢ per share.`,
    `Fee hurdle at that price: ${(feeModel.coefficient * bestAsk * (1 - bestAsk) * 100).toFixed(2)}¢ per share.`,
    sizing.detail,
    `Expected return on the recommended size: ${(expectedReturn * 100).toFixed(2)}% ` +
      `against a floor of ${(minExpectedReturn * 100).toFixed(0)}%.`,
    status === 'ACTIONABLE'
      ? 'All gates passed.'
      : `Held at WATCH: ${
          !isVerified(verification)
            ? `verification is ${verification.health}`
            : sizing.notional <= 0
              ? 'no profitable size exists'
              : 'expected return is below the floor'
        }.`,
  ];

  return {
    ...base,
    status,
    fairProbability: fair,
    marketPrice: bestAsk,
    grossEdge,
    feeHurdle: feeModel.coefficient * bestAsk * (1 - bestAsk),
    sizing,
    curve,
    residuals: {
      n: dist.n,
      sd: dist.sd,
      iqr: dist.iqr,
      bias: dist.bias,
      biasCorrected: dist.biasCorrected,
    },
    reasoning,
    abstentionReasons: [],
  };
}
