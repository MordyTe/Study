/**
 * The source locator: metric prose → canonical series identity.
 *
 * Deterministic-first. The curated catalog is consulted before any model,
 * because series identity is where a plausible wrong answer costs the most,
 * and the known cases deserve to be pinned as reviewable code. The LLM is only
 * a fallback for metrics the catalog does not know, and anything it proposes
 * is marked as unverified and held to a confidence floor.
 *
 * A second, quieter job happens here: when the resolution parser could not
 * determine the publishing precision but the catalog knows it, the rounding
 * convention is filled in — with a note, never silently.
 */

import { z } from 'zod';
import { findCatalogEntry } from '@/lib/sources/catalog';
import type { Agent, AgentContext, EvidenceBundle } from './types';

export const LocatorFallbackSchema = z.object({
  /** Null when no confident identification exists. */
  fredSeriesId: z.string().nullable(),
  transform: z.enum(['yoy-pct', 'mom-diff', 'level']).nullable(),
  decimals: z.number().int().min(0).max(4).nullable(),
  confidence: z.number().min(0).max(1),
  rationale: z.string(),
});

const SYSTEM = `You identify the canonical FRED series that resolves a prediction-market question about a scheduled economic data release.

Rules:
- Name a series only if you are confident it is the one the resolution criteria describe. Seasonally adjusted vs not, core vs headline, and index vs rate are DIFFERENT series; a near-miss is worse than no answer.
- transform describes how the market's headline number derives from the raw series: 'yoy-pct' (percent change vs a year earlier), 'mom-diff' (first difference), or 'level' (the series is the number).
- decimals is the precision the publishing agency uses for the headline figure.
- If you cannot identify the series confidently, return null for fredSeriesId and say why in rationale. Do not guess.`;

export const sourceLocator: Agent = {
  name: 'source-locator',
  version: '1.0.0',
  displayName: 'Source locator',
  description:
    'Maps the parsed metric onto a canonical FRED series via a curated catalog, ' +
    'falling back to model identification only for metrics the catalog does not know.',

  async run(
    bundle: EvidenceBundle,
    context: AgentContext,
  ): Promise<Partial<EvidenceBundle> | null> {
    const spec = bundle.spec;
    if (!spec) {
      return { notes: ['source-locator: no resolution spec to locate a series for.'] };
    }

    const entry = findCatalogEntry(`${spec.metric} ${context.market.question}`);
    if (entry) {
      const rounding =
        spec.rounding ?? ({ decimals: entry.decimals, mode: 'half-up' } as const);
      const filledRounding = spec.rounding === null;
      return {
        spec: { ...spec, seriesHint: entry.fredId, rounding },
        notes: [
          `source-locator: catalog matched "${entry.label}" → FRED ${entry.fredId} ` +
            `(${entry.transform}, ${entry.decimals} dp, ${entry.agency}).` +
            (filledRounding
              ? ' Publishing precision was missing from the parse and filled from the catalog.'
              : ''),
        ],
      };
    }

    // Catalog miss — ask the model, and treat the answer as unverified.
    const result = await context.llm.extract({
      cacheKey: `source-locator:v1:${context.market.conditionId}`,
      system: SYSTEM,
      effort: 'high',
      schema: LocatorFallbackSchema,
      user: [
        `METRIC: ${spec.metric}`,
        `AGENCY: ${spec.agency}`,
        `QUESTION: ${context.market.question}`,
        `CRITERIA: ${context.market.description || '(none)'}`,
      ].join('\n'),
    });

    if (!result.data || !result.data.fredSeriesId || result.data.confidence < 0.8) {
      return {
        spec: {
          ...spec,
          unresolvedAmbiguities: [
            ...spec.unresolvedAmbiguities,
            `source-locator: no confident series identification (${
              result.data?.rationale ?? result.detail
            }).`,
          ],
        },
        notes: ['source-locator: could not identify the resolving series; market will abstain.'],
      };
    }

    return {
      spec: { ...spec, seriesHint: result.data.fredSeriesId },
      notes: [
        `source-locator: MODEL-identified FRED ${result.data.fredSeriesId} ` +
          `(confidence ${result.data.confidence.toFixed(2)}, unverified by the catalog): ` +
          result.data.rationale,
      ],
    };
  },
};
