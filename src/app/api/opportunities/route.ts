import { NextResponse } from 'next/server';
import { getStore } from '@/lib/store';

export const dynamic = 'force-dynamic';

export async function GET(request: Request) {
  const url = new URL(request.url);
  const status = url.searchParams.get('status');
  const category = url.searchParams.get('category');
  const detector = url.searchParams.get('detector');
  const minScore = Number(url.searchParams.get('minScore') ?? '0');
  const limit = Number(url.searchParams.get('limit') ?? '100');

  try {
    const store = await getStore();
    let items = await store.listOpportunities(300);

    if (status) items = items.filter((o) => o.status === status);
    if (category) items = items.filter((o) => o.category === category);
    if (detector) items = items.filter((o) => o.detectorName === detector);
    if (Number.isFinite(minScore) && minScore > 0) items = items.filter((o) => o.score >= minScore);

    return NextResponse.json({
      ok: true,
      count: items.length,
      storeKind: store.kind,
      items: items.slice(0, Math.min(300, Math.max(1, limit))),
    });
  } catch (err) {
    return NextResponse.json({ ok: false, error: (err as Error).message }, { status: 500 });
  }
}
