/**
 * SECURITY BOUNDARY — the venue read allowlist.
 *
 * This project is research-only. It estimates probabilities and records them so
 * that its calibration can be measured against resolved outcomes. It has no
 * order path, holds no credentials, and must not acquire either by accident.
 *
 * Enforcement is three-layered, mirroring the previous project's Bybit guard:
 *
 *   1. A NEGATIVE fragment list, checked first, so a path that merely *contains*
 *      a trading route is rejected even if it would otherwise look allowed.
 *      This is what catches traversal such as `/book/../order`.
 *   2. A POSITIVE allowlist per host. An undocumented path is refused even when
 *      it looks harmless — the set of things we reach is enumerated, not filtered.
 *   3. A CREDENTIAL BAN. The mere presence of a signing key or API secret in the
 *      environment is treated as an attempt to add execution capability, and the
 *      process refuses to proceed.
 *
 * `tests/no-execution-guard.test.ts` asserts all three at runtime AND statically
 * scans the whole of `src/` to prove no module routed around them. That test
 * must never be weakened or skipped.
 *
 * This file is the single permitted exception to the static scan: a blocklist
 * has to be able to name what it blocks.
 */

export class ForbiddenEndpointError extends Error {
  constructor(path: string, reason: string) {
    super(`Refused to request "${path}": ${reason}`);
    this.name = 'ForbiddenEndpointError';
  }
}

export class VenueCredentialError extends Error {
  constructor(names: string[]) {
    super(
      `Refusing to start: venue credentials present in the environment (${names.join(', ')}). ` +
        'This project is research-only and must not be able to sign or submit an order. ' +
        'Remove these variables, or build the risk-limit guard first.',
    );
    this.name = 'VenueCredentialError';
  }
}

/**
 * Substrings that disqualify a path outright, checked against the lowercased
 * path before the positive allowlist. Anything touching order entry, order
 * history, authentication, credential derivation, the private websocket, or an
 * on-chain position mutation belongs here.
 */
export const FORBIDDEN_FRAGMENTS = [
  '/order',
  '/cancel',
  '/auth/',
  '/private',
  '/ws/user',
  '/v1/heartbeats',
  '/data/trades',
  'derive-api-key',
  'builder-api-key',
  'readonly-api-key',
  'withdraw',
  'splitposition',
  'mergepositions',
  'redeempositions',
  'signtypeddata',
  'eth_sendtransaction',
  'poly_signature',
  'poly_passphrase',
] as const;

/**
 * Gamma — market and event metadata. Public, no authentication.
 * https://gamma-api.polymarket.com
 */
export const GAMMA_ALLOWED_PATHS = [
  '/events',
  '/markets',
  '/tags',
  '/sports',
] as const;

/**
 * CLOB — read-only market data. Public, no authentication.
 * Every path here was taken from Polymarket's own `endpoints.py`; the write and
 * account families from that same file are deliberately absent.
 * https://clob.polymarket.com
 */
export const CLOB_ALLOWED_PATHS = [
  '/ok',
  '/time',
  '/version',
  '/book',
  '/books',
  '/midpoint',
  '/midpoints',
  '/price',
  '/prices',
  '/spread',
  '/spreads',
  '/last-trade-price',
  '/last-trades-prices',
  '/tick-size',
  '/neg-risk',
  '/fee-rate',
  '/prices-history',
  '/markets',
  '/simplified-markets',
  '/sampling-markets',
] as const;

export type GammaPath = (typeof GAMMA_ALLOWED_PATHS)[number];
export type ClobPath = (typeof CLOB_ALLOWED_PATHS)[number];

function assertNoForbiddenFragment(path: string): void {
  const lower = path.toLowerCase();
  for (const fragment of FORBIDDEN_FRAGMENTS) {
    if (lower.includes(fragment)) {
      throw new ForbiddenEndpointError(path, `matches forbidden fragment "${fragment}"`);
    }
  }
}

/**
 * The `asserts` signature is deliberate: calling this narrows the argument's
 * type, so downstream code cannot treat the guard as optional decoration.
 */
export function assertGammaPath(path: string): asserts path is GammaPath {
  assertNoForbiddenFragment(path);
  if (!(GAMMA_ALLOWED_PATHS as readonly string[]).includes(path)) {
    throw new ForbiddenEndpointError(path, 'not in the Gamma public read allowlist');
  }
}

export function assertClobPath(path: string): asserts path is ClobPath {
  assertNoForbiddenFragment(path);
  if (!(CLOB_ALLOWED_PATHS as readonly string[]).includes(path)) {
    throw new ForbiddenEndpointError(path, 'not in the CLOB public read allowlist');
  }
}

/**
 * Environment variables whose presence would mean this process can sign or
 * submit something. An empty string is not a credential and does not trip this.
 */
export const BANNED_CREDENTIAL_ENV_VARS = [
  'PRIVATE_KEY',
  'WALLET_PRIVATE_KEY',
  'POLYMARKET_PRIVATE_KEY',
  'POLYMARKET_API_KEY',
  'POLYMARKET_SECRET',
  'POLYMARKET_PASSPHRASE',
  'POLY_API_KEY',
  'POLY_API_SECRET',
  'POLY_PASSPHRASE',
  'MNEMONIC',
  'SEED_PHRASE',
] as const;

export function assertNoVenueCredentials(env: Record<string, string | undefined>): void {
  const present = BANNED_CREDENTIAL_ENV_VARS.filter((name) => {
    const value = env[name];
    return typeof value === 'string' && value.trim().length > 0;
  });
  if (present.length > 0) throw new VenueCredentialError([...present]);
}
