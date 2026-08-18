/**
 * The context scanner: the regime-break safety valve.
 *
 * A residual distribution assumes the future resembles the sample. The one way
 * that assumption fails badly for scheduled data is a structural break the
 * history cannot see — a methodology change, a government shutdown delaying the
 * release, a reference-period switch, an extraordinary event dominating the
 * print. This agent asks one narrow question: is there a KNOWN reason the
 * historical error distribution should not be trusted for this specific market?
 *
 * Its power is deliberately one-directional. A high-confidence break forces the
 * market to abstain; nothing it says can ever make a candidate MORE attractive.
 * A safety valve that can add confidence is not a safety valve.
 */

import { z } from 'zod';
import type { Agent, AgentContext, EvidenceBundle } from './types';

export const ContextRiskSchema = z.object({
  riskLevel: z.enum(['low', 'elevated', 'high']),
  reasons: z.array(z.string()),
  /** Confidence in the assessment itself, 0..1. */
  confidence: z.number().min(0).max(1),
});

const SYSTEM = `You assess one narrow question about a prediction market on a scheduled data release: is there a KNOWN, CONCRETE reason the historical forecast-error distribution for this metric should not be trusted right now?

Qualifying reasons are structural: a methodology or base-period change by the publishing agency, a delayed or rescheduled release, a government shutdown, a strike or disaster large enough to dominate this specific print, a redefinition of the series.

NOT qualifying: ordinary economic uncertainty, "inflation might surprise", elections, market volatility, or anything that is just the normal variance the residual distribution already measures.

- 'high' means: a concrete structural reason exists and you can name it. This forces the system to abstain, so use it only when you would defend the specific claim.
- 'elevated' means: something specific warrants a human look, but does not invalidate the history.
- 'low' is the correct answer most of the time.
- Never invent events. If you know of nothing concrete, say 'low' with an empty reasons list.`;

export const contextScanner: Agent = {
  name: 'context-scanner',
  version: '1.0.0',
  displayName: 'Context scanner',
  description:
    'Flags known structural breaks — methodology changes, delayed releases, dominating ' +
    'events — that would invalidate the historical residual distribution. Can only ever ' +
    'force abstention, never add confidence.',

  async run(
    bundle: EvidenceBundle,
    context: AgentContext,
  ): Promise<Partial<EvidenceBundle> | null> {
    const spec = bundle.spec;
    if (!spec) {
      return { notes: ['context-scanner: no resolution spec; nothing to assess.'] };
    }

    const result = await context.llm.extract({
      cacheKey: `context-scanner:v1:${context.market.conditionId}`,
      system: SYSTEM,
      effort: 'medium',
      schema: ContextRiskSchema,
      user: [
        `METRIC: ${spec.metric} (${spec.agency})`,
        `QUESTION: ${context.market.question}`,
        `RELEASE: ${spec.releaseAtIso ?? 'unspecified'}`,
        '',
        'Evidence gathered so far:',
        ...(bundle.claims.length > 0
          ? bundle.claims.map((c) => `- ${c.statement} [${c.sourceName}]`)
          : ['(none)']),
      ].join('\n'),
    });

    if (!result.data) {
      // No assessment is a missing safety check, not a green light — but it is
      // also not a reason to block by itself. Record it and move on.
      return { notes: [`context-scanner: no assessment produced (${result.detail}).`] };
    }

    const { riskLevel, reasons, confidence } = result.data;

    if (riskLevel === 'high' && confidence >= 0.6) {
      return {
        spec: {
          ...spec,
          unresolvedAmbiguities: [
            ...spec.unresolvedAmbiguities,
            `context-scanner: structural break risk — ${reasons[0] ?? 'unspecified'}`,
          ],
        },
        notes: [
          `context-scanner: HIGH structural risk (confidence ${confidence.toFixed(2)}); ` +
            'forcing abstention.',
        ],
      };
    }

    return {
      notes: [
        `context-scanner: risk ${riskLevel}` +
          (reasons.length > 0 ? ` — ${reasons.join('; ')}` : '') +
          ` (confidence ${confidence.toFixed(2)}).`,
      ],
    };
  },
};
