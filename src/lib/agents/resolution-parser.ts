/**
 * The resolution parser — the highest-leverage agent in the network.
 *
 * Most mispricing in thin scheduled-data markets is not analytical. It is that
 * nobody read the criteria carefully: whether "above 3%" means `> 3.0` or
 * `≥ 3.0`, which of several similarly-named series actually resolves it, and to
 * how many decimals the agency publishes. Half a reporting step is worth several
 * percentage points of probability, which at these prices is the entire edge.
 *
 * This agent extracts that structure and — just as importantly — reports what it
 * could NOT determine. A populated `unresolvedAmbiguities` suppresses the market
 * downstream. Abstention is the correct output for criteria that are genuinely
 * unclear; a confident misreading is the worst thing this system can produce.
 */

import { ResolutionSpecSchema, type Agent, type AgentContext, type EvidenceBundle } from './types';

const SYSTEM = `You extract the machine-readable resolution rule from a prediction-market question about a scheduled data release.

You are NOT forecasting. You are NOT estimating any probability. You read the criteria and report exactly what would have to happen for the market to resolve YES.

Rules that matter most, in order:

1. COMPARATOR. Distinguish these precisely, because they differ by a full reporting step:
   - "above X", "more than X", "exceeds X", "higher than X"  -> gt
   - "at least X", "X or more", "X or higher", "reaches X"    -> gte
   - "below X", "less than X", "under X"                      -> lt
   - "at most X", "X or less", "no more than X"               -> lte
   If the wording genuinely does not settle it, pick your best reading AND record the alternative in unresolvedAmbiguities.

2. ROUNDING. Agencies publish to a fixed precision, and the market resolves on the PUBLISHED figure, not the underlying value. Report the decimals the deciding agency actually publishes for this specific series:
   - US CPI year-over-year and month-over-month: 1 decimal
   - US nonfarm payrolls: thousands, 0 decimals
   - US unemployment rate: 1 decimal
   - Fed target range: 2 decimals (0.25 increments)
   - Daily temperature in F: 0 decimals
   If the criteria state a different precision, that overrides the convention.
   If you cannot determine the precision, set rounding to null and say so in unresolvedAmbiguities. Do not guess.

3. SERIES IDENTITY. Name the exact series, not the family. "CPI" is not enough: is it all-items or core, seasonally adjusted or not, year-over-year or month-over-month, and which index base? If several plausible series fit, that is an ambiguity, not a coin flip.

4. RELEASE TIME. Give the scheduled publication instant in ISO 8601 with a timezone offset if the criteria state or clearly imply it. Otherwise null.

5. CONFIDENCE. Your own probability that you read the criteria correctly. This is about YOUR reading, not about the outcome. Be harsh: 0.95+ only when the criteria are explicit about metric, comparator, and precision.

Never invent a threshold that is not stated. If the question has no numeric threshold, or is not about a scheduled data release at all, set confidence to 0 and explain in unresolvedAmbiguities.`;

export const resolutionParser: Agent = {
  name: 'resolution-parser',
  version: '1.0.0',
  displayName: 'Resolution parser',
  description:
    'Converts a market question and its resolution criteria into a machine-readable ' +
    'threshold specification, including the comparator and the publishing precision.',

  async run(
    _bundle: EvidenceBundle,
    context: AgentContext,
  ): Promise<Partial<EvidenceBundle> | null> {
    const { market } = context;

    const result = await context.llm.extract({
      cacheKey: `resolution-parser:v1:${market.conditionId}`,
      system: SYSTEM,
      effort: 'high',
      schema: ResolutionSpecSchema,
      user: [
        `QUESTION: ${market.question}`,
        '',
        `RESOLUTION CRITERIA:`,
        market.description || '(none supplied)',
        '',
        `MARKET CLOSES: ${market.endDateIso ?? 'unspecified'}`,
        `VENUE CATEGORY: ${market.category ?? 'unspecified'}`,
      ].join('\n'),
    });

    if (!result.data) {
      return {
        notes: [`resolution-parser abstained: ${result.detail}`],
      };
    }

    return {
      spec: result.data,
      notes: [
        `resolution-parser: ${result.data.metric} ${result.data.comparator} ${result.data.threshold}` +
          ` (confidence ${result.data.confidence.toFixed(2)}` +
          (result.data.rounding ? `, ${result.data.rounding.decimals} dp` : ', precision unknown') +
          ')' +
          (result.data.unresolvedAmbiguities.length > 0
            ? ` — ${result.data.unresolvedAmbiguities.length} unresolved ambiguity(ies)`
            : ''),
      ],
    };
  },
};
