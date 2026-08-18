import { NextResponse } from 'next/server';
import { getStore } from '@/lib/store';

export const dynamic = 'force-dynamic';

export async function GET(request: Request): Promise<NextResponse> {
  const url = new URL(request.url);
  const limit = Math.min(200, Math.max(1, Number(url.searchParams.get('limit') ?? 50) || 50));
  const status = url.searchParams.get('status');

  const store = await getStore();
  const all = await store.listCandidates(limit);
  const candidates = status ? all.filter((c) => c.status === status.toUpperCase()) : all;

  return NextResponse.json({
    ok: true,
    storeKind: store.kind,
    durable: store.kind !== 'memory',
    count: candidates.length,
    candidates,
  });
}
