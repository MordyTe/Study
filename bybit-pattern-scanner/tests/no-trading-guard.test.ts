/**
 * SECURITY GATE — this test must never be weakened or skipped.
 *
 * It proves, mechanically, that the codebase has no path to trade execution.
 */

import { describe, expect, it } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import {
  ALLOWED_PATHS,
  FORBIDDEN_FRAGMENTS,
  ForbiddenEndpointError,
  assertAllowedPath,
  assertNoExchangeCredentials,
} from '@/lib/bybit/allowlist';

const SRC = path.resolve(__dirname, '../src');

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = path.join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...walk(full));
    else if (/\.(ts|tsx|js|jsx|json)$/.test(entry)) out.push(full);
  }
  return out;
}

describe('no-trading guard: runtime allowlist', () => {
  it('accepts every documented public market-data path', () => {
    for (const p of ALLOWED_PATHS) {
      expect(() => assertAllowedPath(p)).not.toThrow();
    }
  });

  it('rejects order-entry paths', () => {
    const forbidden = [
      '/v5/order/create',
      '/v5/order/amend',
      '/v5/order/cancel',
      '/v5/order/realtime',
      '/v5/position/set-leverage',
      '/v5/position/list',
      '/v5/account/wallet-balance',
      '/v5/asset/transfer/inter-transfer',
      '/v5/asset/withdraw/create',
      '/v5/user/create-sub-member',
    ];
    for (const p of forbidden) {
      expect(() => assertAllowedPath(p)).toThrow(ForbiddenEndpointError);
    }
  });

  it('rejects any undocumented path even when it looks harmless', () => {
    expect(() => assertAllowedPath('/v5/market/does-not-exist')).toThrow(ForbiddenEndpointError);
    expect(() => assertAllowedPath('/v5/market/kline/../order/create')).toThrow(ForbiddenEndpointError);
  });

  it('refuses to boot when exchange credentials are present', () => {
    expect(() => assertNoExchangeCredentials({ BYBIT_API_KEY: 'abc' } as unknown as NodeJS.ProcessEnv)).toThrow(/analysis-only/i);
    expect(() => assertNoExchangeCredentials({ BYBIT_API_SECRET: 'xyz' } as unknown as NodeJS.ProcessEnv)).toThrow();
    expect(() => assertNoExchangeCredentials({} as unknown as NodeJS.ProcessEnv)).not.toThrow();
    // Empty strings are not credentials.
    expect(() => assertNoExchangeCredentials({ BYBIT_API_KEY: '' } as unknown as NodeJS.ProcessEnv)).not.toThrow();
  });
});

describe('no-trading guard: static source scan', () => {
  const files = walk(SRC);

  it('finds source files to scan', () => {
    expect(files.length).toBeGreaterThan(20);
  });

  it('contains no forbidden Bybit trading endpoint anywhere in src/', () => {
    const offenders: string[] = [];

    for (const file of files) {
      // The allowlist module itself must name the forbidden fragments to block them.
      if (file.endsWith(path.join('bybit', 'allowlist.ts'))) continue;

      const content = readFileSync(file, 'utf8').toLowerCase();
      for (const fragment of FORBIDDEN_FRAGMENTS) {
        if (content.includes(fragment)) {
          offenders.push(`${path.relative(SRC, file)} → "${fragment}"`);
        }
      }
    }

    expect(offenders, `Forbidden trading endpoints found:\n${offenders.join('\n')}`).toEqual([]);
  });

  it('never opens a private Bybit WebSocket', () => {
    const offenders: string[] = [];
    for (const file of files) {
      const content = readFileSync(file, 'utf8').toLowerCase();
      if (content.includes('stream.bybit.com/v5/private') || content.includes('stream.bybit.com/v5/trade')) {
        offenders.push(path.relative(SRC, file));
      }
    }
    expect(offenders).toEqual([]);
  });

  it('has no trading/execution adapter module', () => {
    const suspicious = files.filter((f) =>
      /(order-?executor|trade-?executor|execution-?adapter|place-?order|broker-?client)/i.test(path.basename(f)),
    );
    expect(suspicious).toEqual([]);
  });

  it('exposes no trade-action UI controls', () => {
    const offenders: string[] = [];
    // Word-boundary matches so "Open Dashboard" and "closed candle" do not trip.
    const patterns = [
      /\bplace\s+order\b/i,
      /\bexecute\s+trade\b/i,
      /\bapprove\s+trade\b/i,
      /\bopen\s+position\b/i,
      /\bclose\s+position\b/i,
    ];
    for (const file of files.filter((f) => f.endsWith('.tsx'))) {
      const content = readFileSync(file, 'utf8');
      for (const re of patterns) {
        if (re.test(content)) offenders.push(`${path.relative(SRC, file)} → ${re}`);
      }
    }
    expect(offenders, `Trade-action UI found:\n${offenders.join('\n')}`).toEqual([]);
  });
});
