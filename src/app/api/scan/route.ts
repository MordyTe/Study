/**
 * Scan endpoint — the engine's heartbeat.
 * Triggered by Vercel Cron (see vercel.json) and by the "Scan now" button.
 */

import { NextResponse } from 'next/server';
import { runScan } from '@/lib/engine/scanner';
import { getStore } from '@/lib/store';
import { sendOpportunityAlert } from '@/lib/telegram/client';
import { assertNoExchangeCredentials } from '@/lib/bybit/allowlist';

export const dynamic = 'force-dynamic';
export const maxDuration = 60;

function dashboardUrl(): string | null {
  const explicit = process.env.NEXT_PUBLIC_APP_URL;
  if (explicit) return explicit.replace(/\/$/, '');
  const vercel = process.env.VERCEL_PROJECT_PRODUCTION_URL ?? process.env.VERCEL_URL;
  return vercel ? `https://${vercel}` : null;
}

function authorized(request: Request): boolean {
  const secret = process.env.CRON_SECRET;
  if (!secret) return true; // No secret configured — open (documented in SECURITY.md).
  const header = request.headers.get('authorization');
  return header === `Bearer ${secret}`;
}

export async function GET(request: Request) {
  return handle(request);
}

export async function POST(request: Request) {
  return handle(request);
}

async function handle(request: Request) {
  const startedAt = Date.now();

  try {
    assertNoExchangeCredentials();
  } catch (err) {
    return NextResponse.json({ ok: false, error: (err as Error).message }, { status: 500 });
  }

  if (!authorized(request)) {
    return NextResponse.json({ ok: false, error: 'Unauthorized' }, { status: 401 });
  }

  try {
    const store = await getStore();
    const settings = await store.getSettings();
    const url = new URL(request.url);
    const symbol = url.searchParams.get('symbol') ?? undefined;
    const limit = url.searchParams.get('limit');

    const outcome = await runScan({
      settings,
      store,
      onlySymbol: symbol,
      maxCandidates: limit ? Number(limit) : undefined,
      timeBudgetMs: 45_000,
      onAlert: async (opp) => {
        const key = `${opp.fingerprint}|CONFIRMED`;
        if (await store.hasDelivery(key)) return;
        const result = await sendOpportunityAlert(opp, settings, dashboardUrl());
        await store.recordDelivery({
          id: `del_${Date.now()}_${opp.id}`,
          opportunityId: opp.id,
          idempotencyKey: key,
          channel: 'telegram',
          status: result.sent ? 'sent' : 'failed',
          detail: result.detail,
          at: Date.now(),
        });
      },
    });

    return NextResponse.json({
      ok: true,
      scan: outcome.record,
      opportunities: outcome.opportunities.length,
      confirmed: outcome.record.confirmed,
      forming: outcome.record.forming,
      tier1Ranked: outcome.tier1.length,
      storeKind: store.kind,
      durationMs: Date.now() - startedAt,
    });
  } catch (err) {
    return NextResponse.json(
      { ok: false, error: (err as Error).message, durationMs: Date.now() - startedAt },
      { status: 500 },
    );
  }
}
