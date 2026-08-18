/**
 * The agent layer.
 *
 * This is the only part of the system where a language model runs, and its job
 * is deliberately narrow: **locate and parse sources**. It reads resolution
 * criteria, matches a metric to a canonical series, extracts published numbers
 * from unstructured releases, and flags regime breaks. It never emits a
 * probability. Every number that reaches a decision does so through the
 * deterministic estimator in `src/lib/estimate`.
 *
 * That line is what makes the system testable. Agents are non-deterministic, so
 * their responses are recorded and replayed in tests; everything below them is
 * a pure function of the resulting `EvidenceBundle`.
 */

import { z } from 'zod';

// ---------------------------------------------------------------------------
// Evidence
// ---------------------------------------------------------------------------

/**
 * One factual assertion with provenance. Every claim must be traceable to a
 * source and a time, because "no evidence item may be timestamped after the
 * decision" is the no-lookahead invariant the backtest depends on.
 */
export const ClaimSchema = z.object({
  statement: z.string().min(1),
  /** The numeric content, when the claim has one. */
  value: z.number().nullable(),
  unit: z.string().nullable(),
  sourceName: z.string().min(1),
  sourceUrl: z.string(),
  /** When the source published this. Epoch ms. */
  observedAt: z.number().int().nonnegative(),
});
export type Claim = z.infer<typeof ClaimSchema> & { fetchedAt: number };

export const RoundingSchema = z.object({
  decimals: z.number().int().min(0).max(6),
  mode: z.literal('half-up'),
});

/**
 * The structured form of a market's resolution criteria.
 *
 * Extracting this correctly is the highest-leverage operation in the system: a
 * misread comparator or a missed rounding convention produces a confidently
 * wrong probability, which is strictly worse than no probability at all.
 */
export const ResolutionSpecSchema = z.object({
  /** Human name of the quantity, e.g. "CPI year-over-year, all items". */
  metric: z.string().min(1),
  /** Publishing body, e.g. "BLS". */
  agency: z.string().min(1),
  /** Best guess at a canonical series identifier, if determinable. */
  seriesHint: z.string().nullable(),
  /** Scheduled publication time, ISO 8601, if stated or derivable. */
  releaseAtIso: z.string().nullable(),
  threshold: z.number(),
  comparator: z.enum(['gte', 'gt', 'lte', 'lt']),
  /** Null when the criteria do not determine the reporting precision. */
  rounding: RoundingSchema.nullable(),
  /** The agent's own confidence that it read the criteria correctly, 0..1. */
  confidence: z.number().min(0).max(1),
  /** Anything the agent could not pin down. Non-empty entries suppress trading. */
  unresolvedAmbiguities: z.array(z.string()),
});
export type ResolutionSpec = z.infer<typeof ResolutionSpecSchema>;

/** A point estimate of the underlying value, with its provenance. */
export const PointEstimateSchema = z.object({
  value: z.number(),
  sourceName: z.string().min(1),
  sourceUrl: z.string(),
  observedAt: z.number().int().nonnegative(),
  /** Days between this estimate and the scheduled release. */
  horizonDays: z.number(),
  method: z.string(),
});
export type PointEstimate = z.infer<typeof PointEstimateSchema>;

export interface AgentRun {
  name: string;
  version: string;
  ok: boolean;
  durationMs: number;
  detail: string;
}

/**
 * Everything the deterministic layer is allowed to see. Assembled by the agent
 * network, then frozen: the estimator is a pure function of this object.
 */
export interface EvidenceBundle {
  marketId: string;
  /**
   * The moment the decision is being made. Nothing observed after this may
   * influence it — enforced by `runAgent`, and the reason a backtest over this
   * bundle means anything.
   */
  decisionAt: number;
  spec: ResolutionSpec | null;
  pointEstimate: PointEstimate | null;
  claims: Claim[];
  /** Historical (forecast, actual) pairs for the residual distribution. */
  observations: import('@/lib/estimate/residuals').ForecastObservation[];
  notes: string[];
  agentsRun: AgentRun[];
}

export function emptyBundle(marketId: string, decisionAt: number): EvidenceBundle {
  return {
    marketId,
    decisionAt,
    spec: null,
    pointEstimate: null,
    claims: [],
    observations: [],
    notes: [],
    agentsRun: [],
  };
}

// ---------------------------------------------------------------------------
// The agent contract
// ---------------------------------------------------------------------------

export interface AgentContext {
  /** The market being analysed. */
  market: {
    conditionId: string;
    question: string;
    description: string;
    endDateIso: string | null;
    category: string | null;
  };
  decisionAt: number;
  llm: LlmProvider;
  fetchImpl?: typeof fetch;
}

/**
 * An agent enriches the bundle. It receives what previous agents produced, so
 * ordering in the registry is meaningful and fixed.
 */
export interface Agent {
  name: string;
  /** Semver. Bumped whenever the prompt or logic changes, and part of the fingerprint. */
  version: string;
  displayName: string;
  description: string;
  /** Returns a patch to merge, or null to contribute nothing. */
  run(bundle: EvidenceBundle, context: AgentContext): Promise<Partial<EvidenceBundle> | null>;
}

// ---------------------------------------------------------------------------
// LLM provider abstraction
// ---------------------------------------------------------------------------

/**
 * Every agent call is a schema-constrained extraction, never free-form
 * generation. The model is given a Zod schema and the API validates against it,
 * so a malformed response is impossible rather than merely unlikely — and an
 * agent that cannot fill the schema abstains instead of improvising.
 */
export interface ExtractRequest<T> {
  /**
   * Stable key identifying this call. Used for the response cache and, in
   * tests, to look up the recorded fixture that makes the suite deterministic.
   */
  cacheKey: string;
  system: string;
  user: string;
  schema: z.ZodType<T>;
  maxTokens?: number;
  /** Reasoning depth. `high` for extraction accuracy, `low` for bulk triage. */
  effort?: 'low' | 'medium' | 'high';
}

export interface ExtractResult<T> {
  /** Null when the model declined, the schema did not validate, or the call failed. */
  data: T | null;
  /** True when served from a recorded fixture rather than a live call. */
  replayed: boolean;
  detail: string;
}

export interface LlmProvider {
  readonly kind: 'anthropic' | 'replay' | 'unavailable';
  extract<T>(request: ExtractRequest<T>): Promise<ExtractResult<T>>;
}
