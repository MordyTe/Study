import { NextResponse } from 'next/server';
import { getLlmProvider } from '@/lib/agents/llm';
import { listAgentMeta } from '@/lib/agents/registry';
import { listAdapterStats } from '@/lib/net/client';
import { assertNoVenueCredentials } from '@/lib/polymarket/allowlist';
import { getStore } from '@/lib/store';

export const dynamic = 'force-dynamic';

export async function GET(): Promise<NextResponse> {
  const store = await getStore();
  const llm = getLlmProvider();
  const lastScan = await store.lastScan();

  let credentialsClean = true;
  let credentialDetail = 'No venue credentials present, as required.';
  try {
    assertNoVenueCredentials(process.env as Record<string, string | undefined>);
  } catch (err) {
    credentialsClean = false;
    credentialDetail = (err as Error).message;
  }

  return NextResponse.json({
    ok: credentialsClean,
    mode: 'research-only',
    canPlaceOrders: false,
    store: {
      kind: store.kind,
      durable: store.kind !== 'memory',
      note:
        store.kind === 'memory'
          ? 'In-memory store. Not durable — results are lost on restart.'
          : 'Durable store.',
    },
    agents: {
      provider: llm.kind,
      registered: listAgentMeta(),
    },
    credentials: { clean: credentialsClean, detail: credentialDetail },
    adapters: listAdapterStats(),
    lastScan,
  });
}
