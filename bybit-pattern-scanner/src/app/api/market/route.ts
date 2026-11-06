/**
 * Live market data for the UI.
 *   ?view=overview   → KPI counts + top-ranked Tier-1 candidates
 *   ?view=scanner    → the full ranked instrument table
 *   ?view=klines&category=&symbol=&timeframe=  → candles + overlays for charts
 *   ?view=asset&category=&symbol=              → ticker + multi-timeframe read
 */

import { NextResponse } from 'next/server';
import { getKlines, getTicker, getTickers, getAdapterStats } from '@/lib/bybit/client';
import { getUniverse, rankTier1 } from '@/lib/engine/scanner';
import { buildIndicatorSnapshot } from '@/lib/patterns/indicators-snapshot';
import { getStore } from '@/lib/store';
import { TIMEFRAMES, type MarketCategory, type Timeframe } from '@/lib/bybit/types';
import { lastDefined } from '@/lib/ta/indicators';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

function isCategory(v: string | null): v is MarketCategory {
  return v === 'spot' || v === 'linear';
}

function isTimeframe(v: string | null): v is Timeframe {
  return typeof v === 'string' && (TIMEFRAMES as readonly string[]).includes(v);
}

export async function GET(request: Request) {
  const url = new URL(request.url);
  const view = url.searchParams.get('view') ?? 'overview';

  try {
    const store = await getStore();
    const settings = await store.getSettings();

    if (view === 'klines') {
      const category = url.searchParams.get('category');
      const symbol = url.searchParams.get('symbol');
      const timeframe = url.searchParams.get('timeframe') ?? '1h';
      if (!isCategory(category) || !symbol || !isTimeframe(timeframe)) {
        return NextResponse.json({ ok: false, error: 'category, symbol and timeframe are required' }, { status: 400 });
      }
      const series = await getKlines(category, symbol, timeframe, 300);
      const closed = series.candles.slice(0, -1);
      const ind = closed.length > 60 ? buildIndicatorSnapshot(closed) : null;

      return NextResponse.json({
        ok: true,
        symbol,
        category,
        timeframe,
        candles: series.candles,
        levels: ind ? ind.levels.slice(0, 6) : [],
        structure: ind?.structure.state ?? null,
        source: 'Bybit V5 Official',
        fetchedAt: series.fetchedAt,
      });
    }

    if (view === 'asset') {
      const category = url.searchParams.get('category');
      const symbol = url.searchParams.get('symbol');
      if (!isCategory(category) || !symbol) {
        return NextResponse.json({ ok: false, error: 'category and symbol are required' }, { status: 400 });
      }

      const ticker = await getTicker(category, symbol);
      const timeframes: Timeframe[] = ['15m', '1h', '4h', '1d'];
      const structures = await Promise.all(
        timeframes.map(async (tf) => {
          try {
            const series = await getKlines(category, symbol, tf, 200);
            const closed = series.candles.slice(0, -1);
            if (closed.length < 60) return { timeframe: tf, structure: null, rsi: null, atrPct: null };
            const ind = buildIndicatorSnapshot(closed);
            const price = closed[closed.length - 1]?.close ?? 0;
            return {
              timeframe: tf,
              structure: ind.structure.state,
              rsi: lastDefined(ind.rsi),
              atrPct: price > 0 ? (ind.atrLast / price) * 100 : null,
            };
          } catch {
            return { timeframe: tf, structure: null, rsi: null, atrPct: null };
          }
        }),
      );

      const opportunities = (await store.listOpportunities(200)).filter(
        (o) => o.symbol === symbol && o.category === category,
      );

      return NextResponse.json({
        ok: true,
        ticker,
        structures,
        opportunities: opportunities.slice(0, 20),
        source: 'Bybit V5 Official',
      });
    }

    // overview / scanner both need the ranked universe.
    const categories = settings.markets;
    const rows: ReturnType<typeof rankTier1> = [];
    let spotCount = 0;
    let linearCount = 0;

    for (const category of categories) {
      const [instruments, tickers] = await Promise.all([getUniverse(category), getTickers(category)]);
      if (category === 'spot') spotCount = instruments.length;
      else linearCount = instruments.length;
      rows.push(...rankTier1(instruments, tickers, settings));
    }
    rows.sort((a, b) => b.energy - a.energy);

    const lastScan = await store.lastScan();
    const opportunities = await store.listOpportunities(200);
    const active = opportunities.filter(
      (o) => !['INVALIDATED', 'EXPIRED', 'CLOSED_TRACKING'].includes(o.status),
    );

    const payload = rows.map((r) => ({
      id: r.instrument.id,
      category: r.instrument.category,
      symbol: r.instrument.symbol,
      baseCoin: r.instrument.baseCoin,
      lastPrice: r.ticker.lastPrice,
      change24hPct: r.ticker.price24hPcnt * 100,
      turnover24h: r.ticker.turnover24h,
      high24h: r.ticker.highPrice24h,
      low24h: r.ticker.lowPrice24h,
      spreadBps: r.ticker.spreadBps,
      fundingRate: r.ticker.fundingRate,
      openInterest: r.ticker.openInterest,
      energy: r.energy,
      reasons: r.reasons,
    }));

    return NextResponse.json({
      ok: true,
      source: 'Bybit V5 Official',
      fetchedAt: Date.now(),
      instrumentCounts: { spot: spotCount, linear: linearCount, total: spotCount + linearCount },
      eligibleAfterFilters: rows.length,
      rows: view === 'scanner' ? payload : payload.slice(0, 24),
      opportunities: {
        confirmed: active.filter((o) => o.status === 'CONFIRMED').length,
        forming: active.filter((o) => o.status === 'FORMING').length,
        total: opportunities.length,
      },
      lastScan,
      adapter: getAdapterStats(),
      storeKind: store.kind,
      settings: {
        markets: settings.markets,
        timeframes: settings.timeframes,
        minTurnover24h: settings.minTurnover24h,
        confirmedThreshold: settings.confirmedThreshold,
      },
    });
  } catch (err) {
    return NextResponse.json({ ok: false, error: (err as Error).message }, { status: 502 });
  }
}
