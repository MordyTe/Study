/**
 * Live contract test against official Bybit V5 endpoints.
 * This is the release gate: it proves the deployment is talking to the real
 * exchange, not fixtures. Surfaced on the System Health page.
 */

import { NextResponse } from 'next/server';
import {
  getInstruments,
  getKlines,
  getServerTime,
  getTicker,
  getTickers,
} from '@/lib/bybit/client';
import { checkCandleIntegrity } from '@/lib/engine/verification';
import { assertNoExchangeCredentials } from '@/lib/bybit/allowlist';

export const dynamic = 'force-dynamic';
export const maxDuration = 30;

interface Check {
  name: string;
  passed: boolean;
  detail: string;
  latencyMs?: number;
  sample?: unknown;
}

export async function GET() {
  const checks: Check[] = [];
  const startedAt = Date.now();

  // 0 — no exchange credentials may exist in this process.
  try {
    assertNoExchangeCredentials();
    checks.push({ name: 'No trading credentials present', passed: true, detail: 'No Bybit API key or secret found in the environment, as required.' });
  } catch (err) {
    checks.push({ name: 'No trading credentials present', passed: false, detail: (err as Error).message });
  }

  // 1 — server time and clock drift.
  let serverTimeMs = 0;
  try {
    const t0 = Date.now();
    const time = await getServerTime();
    serverTimeMs = time.seconds * 1000;
    const drift = Math.abs(Date.now() - serverTimeMs);
    checks.push({
      name: 'Bybit server time',
      passed: drift < 30_000,
      detail: `Clock drift ${drift}ms (tolerance 30000ms).`,
      latencyMs: Date.now() - t0,
      sample: new Date(serverTimeMs).toISOString(),
    });
  } catch (err) {
    checks.push({ name: 'Bybit server time', passed: false, detail: (err as Error).message });
  }

  // 2 — spot instruments.
  let spotCount = 0;
  try {
    const t0 = Date.now();
    const spot = await getInstruments('spot');
    spotCount = spot.length;
    checks.push({
      name: 'Spot instruments (USDT)',
      passed: spot.length > 100,
      detail: `${spot.length} eligible active spot instruments discovered.`,
      latencyMs: Date.now() - t0,
      sample: spot.slice(0, 3).map((i) => i.symbol),
    });
  } catch (err) {
    checks.push({ name: 'Spot instruments (USDT)', passed: false, detail: (err as Error).message });
  }

  // 3 — linear instruments, fully paginated.
  let linearCount = 0;
  let btcFound = false;
  try {
    const t0 = Date.now();
    const linear = await getInstruments('linear');
    linearCount = linear.length;
    btcFound = linear.some((i) => i.symbol === 'BTCUSDT');
    checks.push({
      name: 'Linear perpetuals (USDT-settled, paginated)',
      passed: linear.length > 300 && btcFound,
      detail: `${linear.length} eligible linear perpetuals discovered; BTCUSDT ${btcFound ? 'found' : 'MISSING'}. Pagination must exhaust nextPageCursor — a result under ~300 usually means only one page was read.`,
      latencyMs: Date.now() - t0,
      sample: linear.slice(0, 3).map((i) => i.symbol),
    });
  } catch (err) {
    checks.push({ name: 'Linear perpetuals (USDT-settled, paginated)', passed: false, detail: (err as Error).message });
  }

  // 4 — tickers.
  let btcPrice = 0;
  try {
    const t0 = Date.now();
    const tickers = await getTickers('linear');
    const btc = tickers.find((t) => t.symbol === 'BTCUSDT');
    btcPrice = btc?.lastPrice ?? 0;
    checks.push({
      name: 'Live tickers',
      passed: tickers.length > 100 && btcPrice > 0,
      detail: `${tickers.length} linear tickers returned; BTCUSDT last price ${btcPrice}.`,
      latencyMs: Date.now() - t0,
      sample: { symbol: 'BTCUSDT', lastPrice: btcPrice, turnover24h: btc?.turnover24h },
    });
  } catch (err) {
    checks.push({ name: 'Live tickers', passed: false, detail: (err as Error).message });
  }

  // 5 — historical klines + structural integrity.
  try {
    const t0 = Date.now();
    const series = await getKlines('linear', 'BTCUSDT', '1h', 200);
    const closed = series.candles.slice(0, -1);
    const integrity = checkCandleIntegrity(closed, '1h');
    checks.push({
      name: 'Historical klines + integrity',
      passed: closed.length >= 150 && integrity.valid,
      detail: `${closed.length} closed 1h candles; ${integrity.gaps} gap(s); ${integrity.issues.length} integrity issue(s).`,
      latencyMs: Date.now() - t0,
      sample: closed[closed.length - 1],
    });
  } catch (err) {
    checks.push({ name: 'Historical klines + integrity', passed: false, detail: (err as Error).message });
  }

  // 6 — cross-source reconciliation (kline close vs independent ticker fetch).
  try {
    const t0 = Date.now();
    const [series, ticker] = await Promise.all([
      getKlines('linear', 'BTCUSDT', '15m', 10),
      getTicker('linear', 'BTCUSDT'),
    ]);
    const lastClosed = series.candles[series.candles.length - 2];
    if (lastClosed && ticker) {
      const deltaPct = Math.abs((ticker.lastPrice - lastClosed.close) / lastClosed.close) * 100;
      checks.push({
        name: 'REST reconciliation (kline vs ticker)',
        passed: deltaPct < 3,
        detail: `Latest closed 15m candle ${lastClosed.close} vs ticker ${ticker.lastPrice} → ${deltaPct.toFixed(3)}% divergence.`,
        latencyMs: Date.now() - t0,
      });
    } else {
      checks.push({ name: 'REST reconciliation (kline vs ticker)', passed: false, detail: 'Missing candle or ticker data.' });
    }
  } catch (err) {
    checks.push({ name: 'REST reconciliation (kline vs ticker)', passed: false, detail: (err as Error).message });
  }

  const passed = checks.filter((c) => c.passed).length;
  const allPassed = passed === checks.length;

  return NextResponse.json(
    {
      ok: allPassed,
      summary: `${passed}/${checks.length} live checks passed against ${'https://api.bybit.com'}.`,
      source: 'Bybit V5 Official',
      serverTime: serverTimeMs ? new Date(serverTimeMs).toISOString() : null,
      instrumentCounts: { spot: spotCount, linear: linearCount, total: spotCount + linearCount },
      btcusdtLastPrice: btcPrice,
      checks,
      durationMs: Date.now() - startedAt,
      ranAt: new Date().toISOString(),
    },
    { status: allPassed ? 200 : 503 },
  );
}
