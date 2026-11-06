/**
 * HARD SECURITY BOUNDARY — public market-data path allowlist.
 *
 * This application is analysis-only. It must never be able to place, amend,
 * cancel, or manage an order or position on any exchange.
 *
 * Every outbound Bybit request is validated against ALLOWED_PATHS at runtime.
 * Anything not on this list throws before a socket is opened. There is no
 * override, no environment flag, and no trading adapter anywhere in the tree.
 *
 * See docs/SECURITY.md and tests/no-trading-guard.test.ts.
 */

export const BYBIT_REST_BASE = 'https://api.bybit.com';

/** Documented Bybit V5 public market-data endpoints. GET only. No auth. */
export const ALLOWED_PATHS = [
  '/v5/market/time',
  '/v5/market/instruments-info',
  '/v5/market/tickers',
  '/v5/market/kline',
  '/v5/market/mark-price-kline',
  '/v5/market/index-price-kline',
  '/v5/market/orderbook',
  '/v5/market/open-interest',
  '/v5/market/funding/history',
  '/v5/market/recent-trade',
] as const;

export type AllowedPath = (typeof ALLOWED_PATHS)[number];

/**
 * Substrings that must never appear in an outbound URL. These cover Bybit's
 * order-entry, position-management, account, and asset-transfer surfaces.
 */
export const FORBIDDEN_FRAGMENTS = [
  '/v5/order',
  '/v5/position',
  '/v5/account',
  '/v5/asset',
  '/v5/user',
  '/v5/spot-margin',
  '/v5/lending',
  '/v5/broker',
  '/v5/trade',
  '/private',
  'order/create',
  'order/amend',
  'order/cancel',
  'order/realtime',
  'position/set-leverage',
  'asset/transfer',
  'asset/withdraw',
] as const;

export class ForbiddenEndpointError extends Error {
  constructor(url: string, reason: string) {
    super(`[NO-TRADING GUARD] Blocked outbound request to "${url}": ${reason}`);
    this.name = 'ForbiddenEndpointError';
  }
}

/**
 * Validates a Bybit path. Throws ForbiddenEndpointError when the path is not an
 * explicitly allowed public market-data endpoint.
 */
export function assertAllowedPath(path: string): asserts path is AllowedPath {
  const lower = path.toLowerCase();

  for (const fragment of FORBIDDEN_FRAGMENTS) {
    if (lower.includes(fragment)) {
      throw new ForbiddenEndpointError(path, `matches forbidden fragment "${fragment}"`);
    }
  }

  if (!(ALLOWED_PATHS as readonly string[]).includes(path)) {
    throw new ForbiddenEndpointError(path, 'not in the public market-data allowlist');
  }
}

/**
 * Startup guard. Bybit credentials must not exist in this process — their mere
 * presence signals an attempt to add execution capability.
 */
export function assertNoExchangeCredentials(env: NodeJS.ProcessEnv = process.env): void {
  const banned = ['BYBIT_API_KEY', 'BYBIT_API_SECRET', 'BYBIT_SECRET', 'BYBIT_PRIVATE_KEY'];
  const present = banned.filter((k) => {
    const v = env[k];
    return typeof v === 'string' && v.trim().length > 0;
  });
  if (present.length > 0) {
    throw new Error(
      `[NO-TRADING GUARD] Exchange credentials detected (${present.join(', ')}). ` +
        'This application is analysis-only and must never hold trading credentials. ' +
        'Remove these variables from the environment.',
    );
  }
}
