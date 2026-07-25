import { NextResponse } from 'next/server';
import { getStore } from '@/lib/store';
import { isTelegramConfigured } from '@/lib/telegram/client';

export const dynamic = 'force-dynamic';

export async function GET() {
  try {
    const store = await getStore();
    const [deliveries, scans] = await Promise.all([store.listDeliveries(50), store.listScans(20)]);
    return NextResponse.json({
      ok: true,
      telegramConfigured: isTelegramConfigured(),
      deliveries,
      scans,
      storeKind: store.kind,
    });
  } catch (err) {
    return NextResponse.json({ ok: false, error: (err as Error).message }, { status: 500 });
  }
}
