/**
 * Scan orchestration.
 *
 * Three tiers with strictly different cost profiles, carried over from the
 * previous project because the shape fits even better here: Tier 1 is one cheap
 * call covering the whole universe, Tier 2 is the expensive per-market agent
 * fan-out, Tier 3 is deterministic arithmetic and persistence.
 *
 * Two disciplines are load-bearing and must not be relaxed:
 *
 *   - **The wall-clock budget records what it deferred.** Truncation is a fact
 *     that goes into the scan record, never a silent shortening of the work.
 *   - **Per-market failure is captured, not propagated.** One market that fails
 *     to parse, or one agent that times out, must not cost the whole scan.
 */

import { emptyBundle, type AgentContext } from '@/lib/agents/types';
import { getLlmProvider } from '@/lib/agents/llm';
import { runAllAgents } from '@/lib/agents/registry';
import { assess, type Candidate } from '@/lib/engine/assess';
import { rankTier1, type RankedMarket } from '@/lib/engine/rank';
import type { FeeCategory } from '@/lib/estimate/fees';
import {
  assertReadOnlyEnvironment,
  getFeeRateBps,
  getOrderBook,
  listAllEvents,
} from '@/lib/polymarket/read';
import type { Market } from '@/lib/polymarket/types';
import { getStore, type ScanRecord, type Settings } from '@/lib/store';

/**
 * Map the venue's own category label onto a fee tier. Unknown categories fall
 * through to null, which `resolveFeeModel` treats as the expensive default —
 * being wrong in the conservative direction.
 */
export function mapFeeCategory(market: Market): FeeCategory | null {
  const raw = (market.category ?? '').toLowerCase();
  const text = `${raw} ${market.question}`.toLowerCase();

  if (/geopolit|war|ceasefire|treaty|sanction/.test(text)) return 'geopolitics';
  if (/crypto|bitcoin|ethereum|solana|token/.test(text)) return 'crypto';
  if (/cpi|inflation|gdp|unemploy|payroll|jobless|fed|fomc|rate|ppi|retail sales/.test(text))
    return 'economics';
  if (/weather|temperature|rainfall|snow|hurricane/.test(text)) return 'weather';
  if (/politic|election|senate|congress|president/.test(text)) return 'politics';
  if (/sport|nba|nfl|mlb|soccer|olympic/.test(text)) return 'sports';
  if (/stock|equity|s&p|nasdaq|earnings/.test(text)) return 'finance';
  return null;
}

export interface ScanOptions {
  now?: number;
  settings?: Settings;
  fetchImpl?: typeof fetch;
  /** Bounds the Gamma walk. */
  maxPages?: number;
  /** Injected in tests so the pipeline can run without a venue. */
  universeOverride?: Market[];
}

export interface ScanResult {
  record: ScanRecord;
  candidates: Candidate[];
}

export async function runScan(options: ScanOptions = {}): Promise<ScanResult> {
  // Boot-time refusal: the presence of a signing key is itself the thing being
  // rejected, before any network call is made.
  assertReadOnlyEnvironment();

  const startedAt = options.now ?? Date.now();
  const store = await getStore();
  const settings = options.settings ?? (await store.getSettings());
  const llm = getLlmProvider();
  const errors: string[] = [];

  // -- Tier 1 ---------------------------------------------------------------
  let markets: Market[] = options.universeOverride ?? [];
  if (!options.universeOverride) {
    try {
      const { events, truncated, pagesFetched } = await listAllEvents(
        options.maxPages ?? 8,
        100,
        options.fetchImpl,
      );
      markets = events.flatMap((e) => e.markets);
      if (truncated) {
        errors.push(
          `Universe walk stopped at the ${pagesFetched}-page bound; markets beyond it were not seen.`,
        );
      }
    } catch (err) {
      errors.push(`Tier 1 failed: ${(err as Error).message}`);
    }
  }

  const tier1 = rankTier1(markets, startedAt, settings);
  for (const [reason, count] of Object.entries(tier1.rejected)) {
    errors.push(`Tier 1 filtered ${count} market(s): ${reason}.`);
  }

  // One fee query per scan rather than one per market.
  const feeRateBps = options.universeOverride ? null : await getFeeRateBps(options.fetchImpl);
  const venueCoefficient = feeRateBps === null ? null : feeRateBps / 10_000;

  // -- Tier 2 + 3 -----------------------------------------------------------
  const candidates: Candidate[] = [];

  for (const ranked of tier1.promoted) {
    if (Date.now() - startedAt > settings.scanTimeBudgetMs) {
      errors.push(
        `Time budget reached after ${candidates.length} market(s); ` +
          `${tier1.promoted.length - candidates.length} deferred to the next scan.`,
      );
      break;
    }
    try {
      const candidate = await analyseMarket(ranked, {
        decisionAt: startedAt,
        llm,
        settings,
        venueCoefficient,
        fetchImpl: options.fetchImpl,
        skipBook: Boolean(options.universeOverride),
      });
      candidates.push(candidate);
      await store.upsertCandidate(candidate);
    } catch (err) {
      errors.push(`${ranked.market.conditionId}: ${(err as Error).message}`);
    }
  }

  const record: ScanRecord = {
    id: `scan_${startedAt.toString(36)}`,
    startedAt,
    finishedAt: Date.now(),
    universeSize: markets.length,
    promoted: tier1.promoted.length,
    actionable: candidates.filter((c) => c.status === 'ACTIONABLE').length,
    watch: candidates.filter((c) => c.status === 'WATCH').length,
    abstain: candidates.filter((c) => c.status === 'ABSTAIN').length,
    errors,
    storeKind: store.kind,
    llmProviderKind: llm.kind,
  };

  await store.recordScan(record);
  return { record, candidates };
}

interface AnalyseOptions {
  decisionAt: number;
  llm: ReturnType<typeof getLlmProvider>;
  settings: Settings;
  venueCoefficient: number | null;
  fetchImpl?: typeof fetch;
  skipBook?: boolean;
}

async function analyseMarket(
  ranked: RankedMarket,
  options: AnalyseOptions,
): Promise<Candidate> {
  const { market } = ranked;

  const context: AgentContext = {
    market: {
      conditionId: market.conditionId,
      question: market.question,
      description: market.description,
      endDateIso: market.endDateIso,
      category: market.category,
    },
    decisionAt: options.decisionAt,
    llm: options.llm,
    fetchImpl: options.fetchImpl,
  };

  const bundle = await runAllAgents(
    emptyBundle(market.conditionId, options.decisionAt),
    context,
  );

  // The YES token is index 0 by venue convention. A market that does not supply
  // one cannot be priced, and assess() will abstain on the missing book.
  const yesTokenId = market.clobTokenIds[0];
  let book = null;
  if (!options.skipBook && yesTokenId) {
    try {
      book = await getOrderBook(yesTokenId, options.fetchImpl);
    } catch {
      // A missing book is an abstention reason, not a scan failure.
      book = null;
    }
  }

  return assess(bundle, book, market.question, {
    feeCategory: mapFeeCategory(market),
    venueFeeCoefficient: options.venueCoefficient,
    sizingLimits: {
      bankrollUsd: options.settings.bankrollUsd,
      kellyMultiplier: options.settings.kellyMultiplier,
      maxPositionFraction: options.settings.maxPositionFraction,
    },
    minExpectedReturn: options.settings.minExpectedReturn,
  });
}
