import { NextResponse } from 'next/server';
import { getAdapterStats, getServerTime } from '@/lib/bybit/client';
import { getStore, isSupabaseConfigured } from '@/lib/store';
import { isTelegramConfigured } from '@/lib/telegram/client';
import { ALLOWED_PATHS } from '@/lib/bybit/allowlist';

export const dynamic = 'force-dynamic';

export async function GET() {
  const checks: Record<string, unknown> = {};
  let overall: 'HEALTHY' | 'DEGRADED' | 'DISCONNECTED' = 'HEALTHY';

  // Bybit REST reachability + clock drift.
  try {
    const t0 = Date.now();
    const time = await getServerTime();
    const drift = Math.abs(Date.now() - time.seconds * 1000);
    checks.bybit = {
      reachable: true,
      latencyMs: Date.now() - t0,
      serverTime: new Date(time.seconds * 1000).toISOString(),
      clockDriftMs: drift,
      status: drift < 5000 ? 'HEALTHY' : 'DEGRADED',
    };
    if (drift >= 5000) overall = 'DEGRADED';
  } catch (err) {
    checks.bybit = { reachable: false, error: (err as Error).message, status: 'DISCONNECTED' };
    overall = 'DISCONNECTED';
  }

  // Store.
  try {
    const store = await getStore();
    const lastScan = await store.lastScan();
    const heartbeatAgeMs = lastScan ? Date.now() - lastScan.finishedAt : null;
    checks.store = {
      kind: store.kind,
      persistent: store.kind === 'supabase',
      supabaseConfigured: isSupabaseConfigured(),
      lastScanAt: lastScan ? new Date(lastScan.finishedAt).toISOString() : null,
      heartbeatAgeMs,
      status: store.kind === 'supabase' ? 'HEALTHY' : 'DEGRADED',
      note:
        store.kind === 'memory'
          ? 'Running on the in-memory store. Live market data is fully functional; opportunity history resets when the serverless instance recycles. Add Supabase credentials for durable history.'
          : 'Persistent Supabase storage active.',
    };
    if (store.kind === 'memory' && overall === 'HEALTHY') overall = 'DEGRADED';
  } catch (err) {
    checks.store = { error: (err as Error).message, status: 'DISCONNECTED' };
    overall = 'DEGRADED';
  }

  checks.telegram = {
    configured: isTelegramConfigured(),
    status: isTelegramConfigured() ? 'HEALTHY' : 'DEGRADED',
    note: isTelegramConfigured()
      ? 'Bot token and chat id present.'
      : 'Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to receive alerts.',
  };

  checks.adapter = getAdapterStats();

  checks.safety = {
    tradingCapability: 'NONE',
    allowlistedPaths: ALLOWED_PATHS,
    exchangeCredentialsPresent: Boolean(process.env.BYBIT_API_KEY || process.env.BYBIT_API_SECRET),
    note: 'Analysis only — this system has no order-entry code path and cannot execute trades.',
  };

  return NextResponse.json({
    ok: overall !== 'DISCONNECTED',
    overall,
    checks,
    version: '1.0.0',
    ranAt: new Date().toISOString(),
  });
}
