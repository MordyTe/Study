/**
 * SECURITY GATE — this test must never be weakened or skipped.
 *
 * It proves, mechanically, that this codebase has no path to trade execution.
 * The project is research-only: it estimates probabilities and records them so
 * their calibration can be measured. It holds no credentials and signs nothing.
 *
 * The test has two halves, and the second is the one that actually matters.
 * Half A proves the guard functions work. Half B walks the entire `src/` tree
 * and proves nobody routed AROUND them — which is the property you care about,
 * and the one a unit test alone can never establish.
 *
 * When execution is eventually justified by measured results, this file is not
 * deleted. It is inverted into a risk-limit guard with the same two-half
 * structure: bounded notional, per-market and per-cluster caps, a daily-loss
 * kill switch, a minimum-edge-after-fees floor, and a TRADING_ENABLED flag that
 * defaults off.
 */

import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';

import {
  CLOB_ALLOWED_PATHS,
  FORBIDDEN_FRAGMENTS,
  ForbiddenEndpointError,
  GAMMA_ALLOWED_PATHS,
  VenueCredentialError,
  assertClobPath,
  assertGammaPath,
  assertNoVenueCredentials,
} from '@/lib/polymarket/allowlist';

const SRC = path.resolve(__dirname, '../src');

/** The allowlist module must be able to name what it blocks. */
const ALLOWLIST_MODULE = path.join('polymarket', 'allowlist.ts');

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = path.join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...walk(full));
    else if (/\.(ts|tsx|js|jsx|json)$/.test(entry)) out.push(full);
  }
  return out;
}

const SOURCE_FILES = walk(SRC);

// ===========================================================================
// Half A — the guard functions themselves
// ===========================================================================

describe('no-execution guard: runtime allowlist', () => {
  it('accepts every documented public read path', () => {
    // The positive half. Without it, someone could "fix" a failure by blocking
    // everything, and the suite would go green on a broken application.
    for (const p of GAMMA_ALLOWED_PATHS) {
      expect(() => assertGammaPath(p), `Gamma path ${p}`).not.toThrow();
    }
    for (const p of CLOB_ALLOWED_PATHS) {
      expect(() => assertClobPath(p), `CLOB path ${p}`).not.toThrow();
    }
  });

  it('rejects order-entry and order-management paths', () => {
    const forbidden = [
      '/order',
      '/orders',
      '/cancel-all',
      '/cancel-market-orders',
      '/data/orders',
      '/order-scoring',
    ];
    for (const p of forbidden) {
      expect(() => assertClobPath(p), `expected ${p} to be refused`).toThrow(
        ForbiddenEndpointError,
      );
    }
  });

  it('rejects credential and authentication paths', () => {
    const forbidden = [
      '/auth/api-key',
      '/auth/api-keys',
      '/auth/derive-api-key',
      '/auth/readonly-api-key',
      '/auth/builder-api-key',
    ];
    for (const p of forbidden) {
      expect(() => assertClobPath(p), `expected ${p} to be refused`).toThrow(
        ForbiddenEndpointError,
      );
    }
  });

  it('rejects the private websocket and the dead-man heartbeat', () => {
    expect(() => assertClobPath('/ws/user')).toThrow(ForbiddenEndpointError);
    expect(() => assertClobPath('/private')).toThrow(ForbiddenEndpointError);
    expect(() => assertClobPath('/v1/heartbeats')).toThrow(ForbiddenEndpointError);
  });

  it('rejects any undocumented path even when it looks harmless', () => {
    expect(() => assertClobPath('/does-not-exist')).toThrow(ForbiddenEndpointError);
    expect(() => assertGammaPath('/markets/extra')).toThrow(ForbiddenEndpointError);
  });

  it('rejects path traversal that would reach a forbidden route', () => {
    // The fragment check runs BEFORE the allowlist check precisely for this.
    expect(() => assertClobPath('/book/../order')).toThrow(ForbiddenEndpointError);
    expect(() => assertClobPath('/price/../../auth/api-key')).toThrow(ForbiddenEndpointError);
  });

  it('keeps the two hosts separate', () => {
    // A Gamma path is not automatically a CLOB path and vice versa; the
    // allowlists are per-host on purpose.
    expect(() => assertGammaPath('/book')).toThrow(ForbiddenEndpointError);
    expect(() => assertClobPath('/events')).toThrow(ForbiddenEndpointError);
  });

  it('refuses to run when venue credentials are present', () => {
    expect(() => assertNoVenueCredentials({ PRIVATE_KEY: '0xabc' })).toThrow(VenueCredentialError);
    expect(() => assertNoVenueCredentials({ POLY_API_SECRET: 'secret' })).toThrow(
      VenueCredentialError,
    );
    expect(() => assertNoVenueCredentials({ MNEMONIC: 'word word word' })).toThrow(
      VenueCredentialError,
    );
  });

  it('does not trip on an empty or whitespace credential', () => {
    // An empty string is not a credential. Treating it as one would make the
    // guard annoying enough that someone eventually disables it.
    expect(() => assertNoVenueCredentials({})).not.toThrow();
    expect(() => assertNoVenueCredentials({ PRIVATE_KEY: '' })).not.toThrow();
    expect(() => assertNoVenueCredentials({ PRIVATE_KEY: '   ' })).not.toThrow();
    expect(() => assertNoVenueCredentials({ NODE_ENV: 'production' })).not.toThrow();
  });

  it('names every offending variable so the error is actionable', () => {
    try {
      assertNoVenueCredentials({ PRIVATE_KEY: 'a', POLY_API_SECRET: 'b' });
      expect.unreachable('should have thrown');
    } catch (err) {
      expect((err as Error).message).toContain('PRIVATE_KEY');
      expect((err as Error).message).toContain('POLY_API_SECRET');
    }
  });
});

// ===========================================================================
// Half B — the static scan. Proof that nobody routed around Half A.
// ===========================================================================

describe('no-execution guard: static source scan', () => {
  it('finds source files to scan at all', () => {
    // A guard that silently scans nothing passes forever.
    expect(SOURCE_FILES.length).toBeGreaterThan(10);
  });

  it('contains no forbidden venue endpoint anywhere in src/', () => {
    const offenders: string[] = [];
    for (const file of SOURCE_FILES) {
      if (file.endsWith(ALLOWLIST_MODULE)) continue;
      const content = readFileSync(file, 'utf8').toLowerCase();
      for (const fragment of FORBIDDEN_FRAGMENTS) {
        if (content.includes(fragment)) {
          offenders.push(`${path.relative(SRC, file)} → "${fragment}"`);
        }
      }
    }
    expect(offenders, `Forbidden endpoints found:\n${offenders.join('\n')}`).toEqual([]);
  });

  it('imports no transaction-signing or wallet library', () => {
    // Without one of these, an order cannot be signed even if a route existed.
    const signingLibraries = [
      '@polymarket/clob-client',
      '@polymarket/client',
      'ethers',
      'viem',
      'web3',
      'eth-account',
      '@ethersproject',
    ];
    const offenders: string[] = [];
    for (const file of SOURCE_FILES) {
      if (file.endsWith(ALLOWLIST_MODULE)) continue;
      const content = readFileSync(file, 'utf8');
      for (const lib of signingLibraries) {
        if (content.includes(`from '${lib}`) || content.includes(`from "${lib}`)) {
          offenders.push(`${path.relative(SRC, file)} → ${lib}`);
        }
      }
    }
    expect(offenders, `Signing libraries imported:\n${offenders.join('\n')}`).toEqual([]);
  });

  it('has no execution adapter module', () => {
    const suspicious = SOURCE_FILES.filter((f) =>
      /(order-?executor|trade-?executor|execution-?adapter|place-?order|broker-?client|signer)/i.test(
        path.basename(f),
      ),
    );
    expect(suspicious.map((f) => path.relative(SRC, f))).toEqual([]);
  });

  it('contains no private-key or mnemonic shaped literal', () => {
    const offenders: string[] = [];
    for (const file of SOURCE_FILES) {
      const content = readFileSync(file, 'utf8');
      // A 64-hex-character run is a secp256k1 private key.
      if (/0x[a-fA-F0-9]{64}\b/.test(content)) {
        offenders.push(`${path.relative(SRC, file)} → 64-hex literal`);
      }
    }
    expect(offenders, `Key-shaped literals found:\n${offenders.join('\n')}`).toEqual([]);
  });

  it('routes every outbound request through an allowlist assertion', () => {
    // fetchJson cannot be called without an assertPath callback — that is
    // enforced by its type. This check proves nothing calls fetch directly and
    // bypasses it.
    const offenders: string[] = [];
    for (const file of SOURCE_FILES) {
      // The net client is the one module allowed to invoke fetch.
      if (file.endsWith(path.join('net', 'client.ts'))) continue;
      const content = readFileSync(file, 'utf8');
      // `fetchImpl` is the injected-for-tests parameter and is fine; a bare
      // `fetch(` call site is not.
      const bareFetch = /(?<![A-Za-z.])fetch\s*\(/.test(content);
      if (bareFetch) offenders.push(path.relative(SRC, file));
    }
    expect(offenders, `Direct fetch calls outside the net client:\n${offenders.join('\n')}`).toEqual(
      [],
    );
  });

  it('exposes no trade-action control in the UI', () => {
    const patterns = [
      /\bplace\s+order\b/i,
      /\bexecute\s+trade\b/i,
      /\bsubmit\s+order\b/i,
      /\bbuy\s+now\b/i,
      /\bconnect\s+wallet\b/i,
    ];
    const offenders: string[] = [];
    for (const file of SOURCE_FILES.filter((f) => f.endsWith('.tsx'))) {
      const content = readFileSync(file, 'utf8');
      for (const pattern of patterns) {
        if (pattern.test(content)) {
          offenders.push(`${path.relative(SRC, file)} → ${pattern}`);
        }
      }
    }
    expect(offenders, `Trade controls found in UI:\n${offenders.join('\n')}`).toEqual([]);
  });
});
