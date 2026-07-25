import { NextResponse } from 'next/server';
import { runBacktest } from '@/lib/engine/backtest';
import { getStore } from '@/lib/store';
import { TIMEFRAMES, type MarketCategory, type Timeframe } from '@/lib/bybit/types';

export const dynamic = 'force-dynamic';
export const maxDuration = 60;

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as {
      category?: string;
      symbol?: string;
      timeframe?: string;
      bars?: number;
      costBps?: number;
      detectors?: string[];
    };

    const category = (body.category === 'spot' ? 'spot' : 'linear') as MarketCategory;
    const symbol = (body.symbol ?? 'BTCUSDT').toUpperCase().trim();
    const timeframe = ((TIMEFRAMES as readonly string[]).includes(body.timeframe ?? '')
      ? body.timeframe
      : '1h') as Timeframe;

    if (!/^[A-Z0-9]{3,20}$/.test(symbol)) {
      return NextResponse.json({ ok: false, error: 'Invalid symbol.' }, { status: 400 });
    }

    const store = await getStore();
    const settings = await store.getSettings();

    const result = await runBacktest({
      category,
      symbol,
      timeframe,
      bars: Math.max(120, Math.min(700, Number(body.bars ?? 400))),
      settings,
      costBps: Math.max(0, Math.min(100, Number(body.costBps ?? 12))),
      detectorFilter: body.detectors,
    });

    return NextResponse.json({ ok: true, ...result, source: 'Bybit V5 Official' });
  } catch (err) {
    return NextResponse.json({ ok: false, error: (err as Error).message }, { status: 500 });
  }
}
