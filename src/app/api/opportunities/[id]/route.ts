import { NextResponse } from 'next/server';
import { getStore } from '@/lib/store';
import { getKlines } from '@/lib/bybit/client';

export const dynamic = 'force-dynamic';

export async function GET(_request: Request, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;

  try {
    const store = await getStore();
    const opportunity = await store.getOpportunity(id);
    if (!opportunity) {
      return NextResponse.json({ ok: false, error: 'Opportunity not found' }, { status: 404 });
    }

    // Fetch the chart window that backs this opportunity's overlays.
    let candles: Awaited<ReturnType<typeof getKlines>>['candles'] = [];
    try {
      const series = await getKlines(opportunity.category, opportunity.symbol, opportunity.timeframe, 200);
      candles = series.candles;
    } catch {
      // Chart data is a nice-to-have; the evidence bundle stands on its own.
    }

    return NextResponse.json({ ok: true, opportunity, candles, source: 'Bybit V5 Official' });
  } catch (err) {
    return NextResponse.json({ ok: false, error: (err as Error).message }, { status: 500 });
  }
}
