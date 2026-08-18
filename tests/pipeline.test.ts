/**
 * End-to-end pipeline and agent-contract tests.
 *
 * The contract block loops over the PRODUCTION agent registry, so any agent
 * added later is covered the moment it is registered — there is no registration
 * step in this file and nothing to remember.
 */

import { describe, expect, it } from 'vitest';

import { emptyBundle, type AgentContext, type EvidenceBundle } from '@/lib/agents/types';
import { AGENTS, runAgent, runAllAgents } from '@/lib/agents/registry';
import { assess } from '@/lib/engine/assess';
import { rankTier1, scoreNeglect } from '@/lib/engine/rank';
import { mapFeeCategory } from '@/lib/engine/scanner';
import { DEFAULT_SETTINGS } from '@/lib/store';
import {
  SilentLlmProvider,
  StubLlmProvider,
  T0,
  market,
  observations,
  orderBook,
  spec,
} from './fixtures';

const HEALTHY_ASKS = [
  { price: 0.45, size: 400 },
  { price: 0.48, size: 400 },
  { price: 0.52, size: 400 },
];

function context(llm: AgentContext['llm'], decisionAt = T0): AgentContext {
  const m = market();
  return {
    market: {
      conditionId: m.conditionId,
      question: m.question,
      description: m.description,
      endDateIso: m.endDateIso,
      category: m.category,
    },
    decisionAt,
    llm,
  };
}

/** A bundle as the agent network would have left it, plus gathered evidence. */
async function fullBundle(overrides: Partial<EvidenceBundle> = {}): Promise<EvidenceBundle> {
  const llm = new StubLlmProvider({ 'resolution-parser': spec() });
  const bundle = await runAllAgents(emptyBundle('0xtest-condition', T0), context(llm));
  return {
    ...bundle,
    pointEstimate: {
      value: 3.05,
      sourceName: 'clevelandfed-nowcast',
      sourceUrl: 'https://www.clevelandfed.org/indicators-and-data/inflation-nowcasting',
      observedAt: T0 - 3_600_000,
      horizonDays: 20,
      method: 'published nowcast',
    },
    observations: observations(),
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tier 1
// ---------------------------------------------------------------------------

describe('Tier 1 neglect ranking', () => {
  it('rejects markets with no scheduled resolution source', () => {
    const result = scoreNeglect(
      market({ question: 'Who will win Best Picture?', description: 'Academy Awards.' }),
      T0,
      DEFAULT_SETTINGS,
    );
    expect(result).toEqual({ rejected: 'no-scheduled-source' });
  });

  it('rejects closed and inactive markets', () => {
    expect(scoreNeglect(market({ closed: true }), T0, DEFAULT_SETTINGS)).toEqual({
      rejected: 'closed-or-inactive',
    });
    expect(scoreNeglect(market({ active: false }), T0, DEFAULT_SETTINGS)).toEqual({
      rejected: 'closed-or-inactive',
    });
  });

  it('rejects markets below the volume floor', () => {
    expect(scoreNeglect(market({ volumeNum: 10 }), T0, DEFAULT_SETTINGS)).toEqual({
      rejected: 'below-volume-floor',
    });
  });

  it('rejects markets outside the horizon window', () => {
    const soon = market({ endDateIso: new Date(T0 + 3_600_000).toISOString() });
    expect(scoreNeglect(soon, T0, DEFAULT_SETTINGS)).toEqual({ rejected: 'resolves-too-soon' });

    const late = market({ endDateIso: new Date(T0 + 400 * 86_400_000).toISOString() });
    expect(scoreNeglect(late, T0, DEFAULT_SETTINGS)).toEqual({ rejected: 'resolves-too-late' });
  });

  it('scores a thin market above a heavily-traded one — the core premise', () => {
    // This is the whole thesis in one assertion: attention beats speed, so the
    // ranking must prefer the market nobody is watching.
    const thin = scoreNeglect(market({ volumeNum: 2_000 }), T0, DEFAULT_SETTINGS);
    const busy = scoreNeglect(market({ volumeNum: 5_000_000 }), T0, DEFAULT_SETTINGS);
    expect('neglect' in thin && 'neglect' in busy).toBe(true);
    if ('neglect' in thin && 'neglect' in busy) {
      expect(thin.neglect).toBeGreaterThan(busy.neglect);
    }
  });

  it('scores a genuinely uncertain price above a near-certain one', () => {
    const uncertain = scoreNeglect(market({ outcomePrices: [0.5, 0.5] }), T0, DEFAULT_SETTINGS);
    const settled = scoreNeglect(market({ outcomePrices: [0.97, 0.03] }), T0, DEFAULT_SETTINGS);
    if ('neglect' in uncertain && 'neglect' in settled) {
      expect(uncertain.neglect).toBeGreaterThan(settled.neglect);
    }
  });

  it('explains every ranking it produces', () => {
    const result = scoreNeglect(market(), T0, DEFAULT_SETTINGS);
    expect('reasons' in result && result.reasons.length).toBeGreaterThanOrEqual(4);
  });

  it('caps promotion at the configured candidate budget and counts rejections', () => {
    const markets = [
      ...Array.from({ length: 40 }, (_, i) =>
        market({ conditionId: `0x${i}`, volumeNum: 1_000 + i }),
      ),
      market({ conditionId: '0xnope', question: 'Best Picture?', description: 'Oscars.' }),
    ];
    const result = rankTier1(markets, T0, { ...DEFAULT_SETTINGS, tier2Candidates: 10 });
    expect(result.promoted).toHaveLength(10);
    expect(result.considered).toBe(40);
    expect(result.rejected['no-scheduled-source']).toBe(1);
  });

  it('ranks deterministically, including ties', () => {
    const markets = Array.from({ length: 20 }, (_, i) => market({ conditionId: `0x${i}` }));
    const a = rankTier1(markets, T0, DEFAULT_SETTINGS).promoted.map((r) => r.market.conditionId);
    const b = rankTier1([...markets].reverse(), T0, DEFAULT_SETTINGS).promoted.map(
      (r) => r.market.conditionId,
    );
    expect(b).toEqual(a);
  });
});

describe('fee category mapping', () => {
  it('routes economic releases to the economics tier', () => {
    expect(mapFeeCategory(market())).toBe('economics');
  });

  it('falls through to null rather than guessing a cheap tier', () => {
    expect(
      mapFeeCategory(market({ category: 'Miscellanea', question: 'Something else entirely' })),
    ).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Agent contract — applies to every registered agent automatically
// ---------------------------------------------------------------------------

describe('agent registry contract', () => {
  it('registers at least one agent', () => {
    expect(AGENTS.length).toBeGreaterThan(0);
  });

  it('gives every agent a unique name and a semver version', () => {
    const names = AGENTS.map((a) => a.name);
    expect(new Set(names).size).toBe(names.length);
    for (const agent of AGENTS) {
      expect(agent.version, `${agent.name} version`).toMatch(/^\d+\.\d+\.\d+$/);
      expect(agent.description.length, `${agent.name} description`).toBeGreaterThan(20);
    }
  });

  for (const agent of AGENTS) {
    it(`${agent.name}: abstains rather than throwing when the provider is unavailable`, async () => {
      const bundle = await runAgent(
        agent,
        emptyBundle('m', T0),
        context(new SilentLlmProvider()),
      );
      const run = bundle.agentsRun.find((r) => r.name === agent.name);
      expect(run?.ok).toBe(true);
      expect(bundle.spec).toBeNull();
    });

    it(`${agent.name}: records its own name and version on every run`, async () => {
      const bundle = await runAgent(
        agent,
        emptyBundle('m', T0),
        context(new SilentLlmProvider()),
      );
      const run = bundle.agentsRun.find((r) => r.name === agent.name);
      expect(run).toBeDefined();
      expect(run!.version).toBe(agent.version);
      expect(run!.durationMs).toBeGreaterThanOrEqual(0);
    });

    it(`${agent.name}: survives a provider that throws`, async () => {
      const exploding = {
        kind: 'anthropic' as const,
        extract: async () => {
          throw new Error('provider exploded');
        },
      };
      const bundle = await runAgent(agent, emptyBundle('m', T0), context(exploding));
      // The run is recorded as failed; the pipeline continues.
      expect(bundle.agentsRun.find((r) => r.name === agent.name)?.ok).toBe(false);
    });
  }
});

describe('runAgent middleware', () => {
  it('drops claims observed after the decision time', async () => {
    const lookaheadAgent = {
      name: 'lookahead-test',
      version: '1.0.0',
      displayName: 'Lookahead test',
      description: 'Test agent that returns one past and one future claim.',
      async run() {
        return {
          claims: [
            {
              statement: 'past',
              value: 1,
              unit: null,
              sourceName: 's',
              sourceUrl: 'u',
              observedAt: T0 - 1000,
              fetchedAt: T0,
            },
            {
              statement: 'future',
              value: 2,
              unit: null,
              sourceName: 's',
              sourceUrl: 'u',
              observedAt: T0 + 1000,
              fetchedAt: T0,
            },
          ],
        };
      },
    };

    const bundle = await runAgent(
      lookaheadAgent,
      emptyBundle('m', T0),
      context(new SilentLlmProvider()),
    );
    expect(bundle.claims.map((c) => c.statement)).toEqual(['past']);
    // And it says so, rather than dropping silently.
    expect(bundle.notes.join(' ')).toContain('no-lookahead');
  });

  it('rejects a point estimate observed after the decision time', async () => {
    const futureAgent = {
      name: 'future-estimate',
      version: '1.0.0',
      displayName: 'Future estimate',
      description: 'Test agent returning an estimate from after the decision instant.',
      async run() {
        return {
          pointEstimate: {
            value: 3.5,
            sourceName: 's',
            sourceUrl: 'u',
            observedAt: T0 + 86_400_000,
            horizonDays: 20,
            method: 'test',
          },
        };
      },
    };
    const bundle = await runAgent(
      futureAgent,
      emptyBundle('m', T0),
      context(new SilentLlmProvider()),
    );
    expect(bundle.pointEstimate).toBeNull();
    expect(bundle.notes.join(' ')).toContain('after the decision time');
  });

  it('times out an agent that hangs instead of holding the scan', async () => {
    const hanging = {
      name: 'hanging',
      version: '1.0.0',
      displayName: 'Hanging',
      description: 'Test agent that never resolves, to prove the timeout works.',
      run: () => new Promise<null>(() => {}),
    };
    const bundle = await runAgent(
      hanging,
      emptyBundle('m', T0),
      context(new SilentLlmProvider()),
      50,
    );
    const run = bundle.agentsRun.find((r) => r.name === 'hanging');
    expect(run?.ok).toBe(false);
    expect(run?.detail).toContain('exceeded');
  });
});

// ---------------------------------------------------------------------------
// Assessment
// ---------------------------------------------------------------------------

const ASSESS_OPTIONS = {
  feeCategory: 'economics' as const,
  venueFeeCoefficient: null,
};

describe('assess', () => {
  it('produces an estimate when every gate passes', async () => {
    const bundle = await fullBundle();
    const candidate = assess(bundle, orderBook(HEALTHY_ASKS), market().question, ASSESS_OPTIONS);

    expect(candidate.abstentionReasons).toEqual([]);
    expect(candidate.fairProbability).not.toBeNull();
    expect(candidate.fairProbability!).toBeGreaterThan(0);
    expect(candidate.fairProbability!).toBeLessThan(1);
    expect(candidate.verification.health).toBe('HEALTHY');
    expect(['ACTIONABLE', 'WATCH']).toContain(candidate.status);
  });

  it('applies the rounding conversion end to end', async () => {
    // "above 3.0" at 1 dp means the underlying must clear 3.05, not 3.0. With a
    // point estimate of exactly 3.05 the answer must be very close to a coin flip.
    const bundle = await fullBundle();
    const candidate = assess(bundle, orderBook(HEALTHY_ASKS), market().question, ASSESS_OPTIONS);
    expect(candidate.fairProbability!).toBeCloseTo(0.5, 2);
    expect(candidate.reasoning.join(' ')).toContain('3.05');
  });

  it('is deterministic — identical inputs give byte-identical output', async () => {
    const bundle = await fullBundle();
    const book = orderBook(HEALTHY_ASKS);
    const a = assess(bundle, book, market().question, ASSESS_OPTIONS);
    const b = assess(bundle, book, market().question, ASSESS_OPTIONS);
    expect(JSON.stringify(b)).toBe(JSON.stringify(a));
  });

  it('puts the agent versions in the fingerprint so retuning creates a new identity', async () => {
    const bundle = await fullBundle();
    const candidate = assess(bundle, orderBook(HEALTHY_ASKS), market().question, ASSESS_OPTIONS);
    expect(candidate.fingerprint).toContain('resolution-parser@1.0.0');

    const retuned = assess(
      { ...bundle, agentsRun: [{ ...bundle.agentsRun[0]!, version: '2.0.0' }] },
      orderBook(HEALTHY_ASKS),
      market().question,
      ASSESS_OPTIONS,
    );
    expect(retuned.fingerprint).not.toBe(candidate.fingerprint);
    expect(retuned.id).not.toBe(candidate.id);
  });

  describe('abstention', () => {
    it('abstains with no resolution spec', () => {
      const candidate = assess(
        emptyBundle('m', T0),
        orderBook(HEALTHY_ASKS),
        'q',
        ASSESS_OPTIONS,
      );
      expect(candidate.status).toBe('ABSTAIN');
      expect(candidate.fairProbability).toBeNull();
      expect(candidate.abstentionReasons.join(' ')).toContain('resolution spec');
    });

    it('abstains when the criteria carry unresolved ambiguity', async () => {
      const bundle = await fullBundle();
      const ambiguous = {
        ...bundle,
        spec: spec({ unresolvedAmbiguities: ['Could be core or headline CPI.'] }),
      };
      const candidate = assess(ambiguous, orderBook(HEALTHY_ASKS), 'q', ASSESS_OPTIONS);
      expect(candidate.status).toBe('ABSTAIN');
      expect(candidate.abstentionReasons.join(' ')).toContain('core or headline');
    });

    it('abstains when history is too thin for a residual distribution', async () => {
      const bundle = await fullBundle({ observations: observations(5) });
      const candidate = assess(bundle, orderBook(HEALTHY_ASKS), 'q', ASSESS_OPTIONS);
      expect(candidate.status).toBe('ABSTAIN');
      expect(candidate.abstentionReasons.join(' ')).toContain('Too few comparable historical');
    });

    it('abstains with no order book', async () => {
      const bundle = await fullBundle();
      const candidate = assess(bundle, null, 'q', ASSESS_OPTIONS);
      expect(candidate.status).toBe('ABSTAIN');
      expect(candidate.abstentionReasons.join(' ')).toContain('No resting asks');
    });

    it('collects every failing gate at once rather than the first', async () => {
      const bundle = await fullBundle({
        spec: spec({ unresolvedAmbiguities: ['ambiguous'] }),
        observations: observations(3),
      });
      const candidate = assess(bundle, null, 'q', ASSESS_OPTIONS);
      expect(candidate.abstentionReasons.length).toBeGreaterThanOrEqual(3);
    });

    it('always ships its assumptions, even when abstaining', () => {
      const candidate = assess(emptyBundle('m', T0), null, 'q', ASSESS_OPTIONS);
      expect(candidate.assumptions.length).toBeGreaterThanOrEqual(4);
      expect(candidate.assumptions.join(' ')).toContain('Maker rebates');
    });
  });

  describe('verification as a hard gate', () => {
    it('holds at WATCH when the book is stale, however good the arithmetic', async () => {
      const bundle = await fullBundle();
      // A book from an hour ago against a five-minute freshness limit.
      const stale = orderBook(HEALTHY_ASKS, T0 - 3_600_000);
      const candidate = assess(bundle, stale, 'q', ASSESS_OPTIONS);
      expect(candidate.verification.health).not.toBe('HEALTHY');
      expect(candidate.status).not.toBe('ACTIONABLE');
      expect(candidate.reasoning.join(' ')).toContain('Held at WATCH');
    });

    it('holds at WATCH when the parser is not confident enough', async () => {
      const bundle = await fullBundle({ spec: spec({ confidence: 0.5 }) });
      const candidate = assess(bundle, orderBook(HEALTHY_ASKS), 'q', ASSESS_OPTIONS);
      expect(candidate.status).not.toBe('ACTIONABLE');
    });
  });

  describe('depth honesty', () => {
    it('reports the size at which a large edge actually stops', async () => {
      // A big edge that exists for only $2 must not be sold as a big edge.
      const bundle = await fullBundle();
      const thin = orderBook([{ price: 0.1, size: 20 }]);
      const candidate = assess(bundle, thin, 'q', ASSESS_OPTIONS);
      expect(candidate.grossEdge!).toBeGreaterThan(0.3);
      expect(candidate.sizing!.notional).toBeLessThanOrEqual(2);
      expect(candidate.sizing!.limitedBy).toBe('depth');
    });

    it('produces a non-increasing return curve', async () => {
      const bundle = await fullBundle();
      const candidate = assess(bundle, orderBook(HEALTHY_ASKS), 'q', ASSESS_OPTIONS);
      for (let i = 1; i < candidate.curve.length; i++) {
        expect(candidate.curve[i]!.expectedReturn).toBeLessThanOrEqual(
          candidate.curve[i - 1]!.expectedReturn + 1e-12,
        );
      }
    });

    it('never recommends a size when the fee eats the edge', async () => {
      const bundle = await fullBundle();
      // Fair is ~0.5; asking 0.499 leaves half a cent against a ~1.25c hurdle.
      const candidate = assess(bundle, orderBook([{ price: 0.499, size: 5000 }]), 'q', ASSESS_OPTIONS);
      expect(candidate.sizing!.notional).toBe(0);
      expect(candidate.status).toBe('WATCH');
    });
  });
});
