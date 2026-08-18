/**
 * Normalized venue shapes. Nothing downstream of this file ever sees a raw
 * vendor payload: Gamma returns numbers as strings and arrays as JSON-encoded
 * strings, and CLOB does not guarantee book ordering. Normalizing at the edge
 * means a vendor change is a one-file change.
 */

export interface BookLevel {
  /** Dollars per share, in [0, 1]. */
  price: number;
  /** Shares available at this level. */
  size: number;
}

export interface OrderBook {
  tokenId: string;
  /** Sorted best (highest) first. */
  bids: BookLevel[];
  /** Sorted best (lowest) first. */
  asks: BookLevel[];
  fetchedAt: number;
}

export interface Market {
  conditionId: string;
  slug: string;
  /** The headline question as displayed. */
  question: string;
  /** Free text carrying the resolution criteria. The parser agent's input. */
  description: string;
  outcomes: string[];
  /** ERC-1155 token ids, index-aligned with `outcomes`. */
  clobTokenIds: string[];
  /** Last traded / midpoint price per outcome, index-aligned with `outcomes`. */
  outcomePrices: number[];
  negRisk: boolean;
  active: boolean;
  closed: boolean;
  /** ISO 8601, or null when the venue did not supply one. */
  endDateIso: string | null;
  volumeNum: number;
  liquidityNum: number;
  minimumTickSize: number;
  category: string | null;
}

export interface EventGroup {
  id: string;
  slug: string;
  title: string;
  description: string;
  tags: string[];
  /**
   * Multi-outcome events are commonly modelled as several *separate binary
   * markets* grouped under one event, not as one categorical market. Any
   * cross-outcome reasoning must therefore happen at this level.
   */
  markets: Market[];
}

// ---------------------------------------------------------------------------
// Coercion helpers. Vendor payloads are untrusted and loosely typed.
// ---------------------------------------------------------------------------

export function asNumber(value: unknown, fallback: number): number {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string') {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return fallback;
}

export function asString(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback;
}

export function asBoolean(value: unknown, fallback = false): boolean {
  if (typeof value === 'boolean') return value;
  if (typeof value === 'string') {
    if (value === 'true') return true;
    if (value === 'false') return false;
  }
  return fallback;
}

/**
 * Gamma encodes `outcomes`, `clobTokenIds` and `outcomePrices` as JSON strings
 * rather than arrays. Accept either, and never throw — a market we cannot parse
 * is a market we skip, not a scan we abort.
 */
export function asArray(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  if (typeof value === 'string') {
    try {
      const parsed: unknown = JSON.parse(value);
      if (Array.isArray(parsed)) return parsed;
    } catch {
      return [];
    }
  }
  return [];
}

export function normalizeMarket(raw: Record<string, unknown>): Market | null {
  const conditionId = asString(raw['conditionId'] ?? raw['condition_id']);
  if (!conditionId) return null;

  const outcomes = asArray(raw['outcomes']).map((o) => asString(o));
  const clobTokenIds = asArray(raw['clobTokenIds'] ?? raw['clob_token_ids']).map((t) =>
    asString(t),
  );
  const outcomePrices = asArray(raw['outcomePrices'] ?? raw['outcome_prices']).map((p) =>
    asNumber(p, Number.NaN),
  );

  return {
    conditionId,
    slug: asString(raw['slug']),
    question: asString(raw['question']),
    description: asString(raw['description']),
    outcomes,
    clobTokenIds,
    outcomePrices,
    negRisk: asBoolean(raw['negRisk'] ?? raw['neg_risk']),
    active: asBoolean(raw['active'], true),
    closed: asBoolean(raw['closed']),
    endDateIso: typeof raw['endDate'] === 'string' ? raw['endDate'] : null,
    volumeNum: asNumber(raw['volumeNum'] ?? raw['volume'], 0),
    liquidityNum: asNumber(raw['liquidityNum'] ?? raw['liquidity'], 0),
    minimumTickSize: asNumber(raw['minimum_tick_size'] ?? raw['minimumTickSize'], 0.01),
    category: typeof raw['category'] === 'string' ? raw['category'] : null,
  };
}

export function normalizeEvent(raw: Record<string, unknown>): EventGroup | null {
  const id = asString(raw['id']);
  if (!id) return null;

  const markets = asArray(raw['markets'])
    .map((m) => (typeof m === 'object' && m !== null ? normalizeMarket(m as Record<string, unknown>) : null))
    .filter((m): m is Market => m !== null);

  const tags = asArray(raw['tags'])
    .map((t) =>
      typeof t === 'object' && t !== null
        ? asString((t as Record<string, unknown>)['label'] ?? (t as Record<string, unknown>)['slug'])
        : asString(t),
    )
    .filter((t) => t.length > 0);

  return {
    id,
    slug: asString(raw['slug']),
    title: asString(raw['title']),
    description: asString(raw['description']),
    tags,
    markets,
  };
}

function normalizeLevels(raw: unknown): BookLevel[] {
  return asArray(raw)
    .map((entry) => {
      if (typeof entry !== 'object' || entry === null) return null;
      const rec = entry as Record<string, unknown>;
      const price = asNumber(rec['price'], Number.NaN);
      const size = asNumber(rec['size'], Number.NaN);
      if (!Number.isFinite(price) || !Number.isFinite(size) || size <= 0) return null;
      return { price, size };
    })
    .filter((l): l is BookLevel => l !== null);
}

/**
 * The venue does not guarantee level ordering, and a depth walk that assumes
 * the wrong order silently reports a better fill than reality. Sort explicitly.
 */
export function normalizeOrderBook(
  tokenId: string,
  raw: Record<string, unknown>,
  fetchedAt: number,
): OrderBook {
  const bids = normalizeLevels(raw['bids']).sort((a, b) => b.price - a.price);
  const asks = normalizeLevels(raw['asks']).sort((a, b) => a.price - b.price);
  return { tokenId, bids, asks, fetchedAt };
}
