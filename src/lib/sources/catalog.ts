/**
 * The series catalog: the curated map from a metric, as a market describes it,
 * to the canonical series that resolves it.
 *
 * Deliberately a hand-written table rather than an LLM lookup. Series identity
 * is exactly the place where a plausible-sounding wrong answer is most
 * expensive — matching "CPI" to the seasonally-adjusted index when the market
 * resolves on the NSA one shifts the answer by real percentage points — so the
 * known cases are pinned here and reviewed as code. The LLM is only a fallback
 * for metrics the table does not know, and its answer arrives marked as such.
 *
 * `match` patterns are ordered most-specific-first: "core CPI" must win before
 * plain "CPI" gets a chance.
 */

export type Transform = 'yoy-pct' | 'mom-diff' | 'level';

export interface CatalogEntry {
  key: string;
  label: string;
  agency: string;
  /** FRED series id. */
  fredId: string;
  /** How the published headline number derives from the raw series. */
  transform: Transform;
  /** Decimals the agency publishes for the headline figure. */
  decimals: number;
  /** Days in one release cycle — the persistence model's native horizon. */
  cycleDays: number;
  match: RegExp;
}

export const CATALOG: CatalogEntry[] = [
  {
    key: 'core-cpi-yoy',
    label: 'Core CPI year-over-year (ex food & energy)',
    agency: 'BLS',
    fredId: 'CPILFESL',
    transform: 'yoy-pct',
    decimals: 1,
    cycleDays: 30,
    match: /core\s+(cpi|inflation)|cpi\s+core|ex[- ]food/i,
  },
  {
    key: 'cpi-yoy',
    label: 'CPI year-over-year, all items',
    agency: 'BLS',
    fredId: 'CPIAUCNS',
    transform: 'yoy-pct',
    decimals: 1,
    cycleDays: 30,
    match: /\bcpi\b|consumer price|headline inflation|inflation rate/i,
  },
  {
    key: 'pce-yoy',
    label: 'PCE price index year-over-year',
    agency: 'BEA',
    fredId: 'PCEPI',
    transform: 'yoy-pct',
    decimals: 1,
    cycleDays: 30,
    match: /\bpce\b|personal consumption/i,
  },
  {
    key: 'unemployment-rate',
    label: 'Unemployment rate',
    agency: 'BLS',
    fredId: 'UNRATE',
    transform: 'level',
    decimals: 1,
    cycleDays: 30,
    match: /unemployment rate|jobless rate/i,
  },
  {
    key: 'nonfarm-payrolls',
    label: 'Nonfarm payrolls, monthly change (thousands)',
    agency: 'BLS',
    fredId: 'PAYEMS',
    transform: 'mom-diff',
    decimals: 0,
    cycleDays: 30,
    match: /nonfarm|payroll|jobs report/i,
  },
  {
    key: 'fed-funds-upper',
    label: 'Federal funds target range, upper bound',
    agency: 'Federal Reserve',
    fredId: 'DFEDTARU',
    transform: 'level',
    decimals: 2,
    cycleDays: 45,
    match: /fed(eral)?\s+funds|fomc|rate\s+(cut|hike|decision)|target\s+rate/i,
  },
  {
    key: 'real-gdp-growth',
    label: 'Real GDP growth, quarterly SAAR',
    agency: 'BEA',
    fredId: 'A191RL1Q225SBEA',
    transform: 'level',
    decimals: 1,
    cycleDays: 90,
    match: /\bgdp\b/i,
  },
];

export function findCatalogEntry(text: string): CatalogEntry | null {
  for (const entry of CATALOG) {
    if (entry.match.test(text)) return entry;
  }
  return null;
}

export function catalogByFredId(fredId: string): CatalogEntry | null {
  return CATALOG.find((e) => e.fredId === fredId) ?? null;
}
