/**
 * Tier 1: rank the whole universe by NEGLECT.
 *
 * A pure function with no I/O, run over every market returned by one cheap
 * Gamma call. It is the cost control for the entire system: the agent stage
 * costs real money per market, so what gets promoted here decides the bill.
 *
 * The ranking deliberately does NOT favour the markets a person would find
 * interesting. Headline releases — CPI, nonfarm payrolls — are the most
 * efficiently priced things on the venue, and a small account has no edge
 * there. What is scored highly is the opposite: a market with a checkable
 * scheduled source that has low volume, a wide spread, and a price that has not
 * moved recently. That is where nobody is looking, which is the only place
 * attention beats speed.
 *
 * Every contributing factor also pushes a human-readable string into `reasons`,
 * so a ranking can be explained rather than merely trusted.
 */

import type { Market } from '@/lib/polymarket/types';
import type { Settings } from '@/lib/store';

/**
 * Terms that indicate a scheduled, publicly checkable resolution source. This is
 * the domain the system is built for; markets without any of these are skipped
 * because no agent in the network knows how to resolve them.
 */
export const SCHEDULED_SOURCE_TERMS = [
  'cpi',
  'inflation',
  'core pce',
  'pce',
  'unemployment',
  'jobless',
  'payroll',
  'nonfarm',
  'jobs report',
  'gdp',
  'fed',
  'fomc',
  'interest rate',
  'rate cut',
  'rate hike',
  'basis points',
  'retail sales',
  'ppi',
  'producer price',
  'consumer confidence',
  'housing starts',
  'temperature',
  'rainfall',
  'snowfall',
  'hurricane',
  'ecb',
  'boe',
  'boj',
] as const;

export interface RankedMarket {
  market: Market;
  /** 0..1. Higher means more likely to be both mispriced and unwatched. */
  neglect: number;
  reasons: string[];
  daysToResolution: number | null;
  /** Best available YES price from the venue's own summary. */
  impliedPrice: number | null;
}

export interface Tier1Result {
  promoted: RankedMarket[];
  /** Markets that passed the hard filters but ranked below the cut. */
  considered: number;
  /** Markets rejected by a hard filter, with counts by reason. */
  rejected: Record<string, number>;
}

function matchedSourceTerms(market: Market): string[] {
  const haystack = `${market.question} ${market.description}`.toLowerCase();
  return SCHEDULED_SOURCE_TERMS.filter((term) => haystack.includes(term));
}

function daysToResolution(market: Market, now: number): number | null {
  if (!market.endDateIso) return null;
  const end = Date.parse(market.endDateIso);
  if (!Number.isFinite(end)) return null;
  return (end - now) / 86_400_000;
}

function impliedYesPrice(market: Market): number | null {
  const price = market.outcomePrices[0];
  return typeof price === 'number' && Number.isFinite(price) && price > 0 && price < 1
    ? price
    : null;
}

/**
 * Score one market. Exported so the ranking can be unit-tested directly rather
 * than only through the scan.
 */
export function scoreNeglect(
  market: Market,
  now: number,
  settings: Settings,
): RankedMarket | { rejected: string } {
  if (market.closed || !market.active) return { rejected: 'closed-or-inactive' };

  const terms = matchedSourceTerms(market);
  if (terms.length === 0) return { rejected: 'no-scheduled-source' };

  if (market.volumeNum < settings.minVolumeUsd) return { rejected: 'below-volume-floor' };

  const days = daysToResolution(market, now);
  if (days === null) return { rejected: 'no-resolution-date' };
  if (days < settings.minDaysToResolution) return { rejected: 'resolves-too-soon' };
  if (days > settings.maxDaysToResolution) return { rejected: 'resolves-too-late' };

  const price = impliedYesPrice(market);
  if (price === null) return { rejected: 'no-usable-price' };

  const reasons: string[] = [];

  // Neglect rises as volume falls, on a log scale — the difference between $600
  // and $6,000 matters far more than between $600k and $6M.
  const volumeScore = 1 - Math.min(1, Math.log10(Math.max(market.volumeNum, 1)) / 6);
  reasons.push(
    `Volume $${Math.round(market.volumeNum).toLocaleString()} — ` +
      `${volumeScore > 0.6 ? 'thin enough that few are watching' : 'well-trafficked'}.`,
  );

  // Thin liquidity relative to volume suggests nobody is quoting it seriously.
  const liquidityRatio =
    market.volumeNum > 0 ? Math.min(1, market.liquidityNum / market.volumeNum) : 0;
  const liquidityScore = 1 - liquidityRatio;
  if (liquidityScore > 0.5) reasons.push('Resting liquidity is small relative to traded volume.');

  // Prices at the extremes are usually extreme for a good reason, and the fee
  // schedule is cheapest there, so they are not where the errors live.
  const centrality = 1 - Math.abs(price - 0.5) * 2;
  reasons.push(`Implied ${(price * 100).toFixed(1)}% — ${centrality > 0.5 ? 'genuinely uncertain' : 'near a tail'}.`);

  // A comfortable horizon: long enough that a forecast has content, short
  // enough that the residual distribution is still informative.
  const horizonScore = days >= 5 && days <= 60 ? 1 : days < 5 ? days / 5 : Math.max(0, 1 - (days - 60) / 60);
  reasons.push(`Resolves in ${days.toFixed(1)} days.`);

  // More matched terms means the resolution source is more clearly identifiable.
  const sourceScore = Math.min(1, terms.length / 3);
  reasons.push(`Scheduled-source signals: ${terms.slice(0, 4).join(', ')}.`);

  const neglect =
    volumeScore * 0.35 +
    liquidityScore * 0.15 +
    centrality * 0.2 +
    horizonScore * 0.15 +
    sourceScore * 0.15;

  return { market, neglect, reasons, daysToResolution: days, impliedPrice: price };
}

export function rankTier1(markets: Market[], now: number, settings: Settings): Tier1Result {
  const ranked: RankedMarket[] = [];
  const rejected: Record<string, number> = {};

  for (const market of markets) {
    const result = scoreNeglect(market, now, settings);
    if ('rejected' in result) {
      rejected[result.rejected] = (rejected[result.rejected] ?? 0) + 1;
      continue;
    }
    ranked.push(result);
  }

  ranked.sort((a, b) => b.neglect - a.neglect || a.market.conditionId.localeCompare(b.market.conditionId));

  return {
    promoted: ranked.slice(0, settings.tier2Candidates),
    considered: ranked.length,
    rejected,
  };
}
