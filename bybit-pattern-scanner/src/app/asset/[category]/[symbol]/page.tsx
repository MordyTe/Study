'use client';

import { use, useState } from 'react';
import Link from 'next/link';
import { usePolling } from '@/lib/hooks';
import type { Candle, Ticker, Timeframe } from '@/lib/bybit/types';
import type { Opportunity } from '@/lib/engine/opportunity';
import { PriceChart } from '@/components/price-chart';
import {
  Chip,
  ErrorState,
  Kpi,
  Panel,
  SectionTitle,
  Skeleton,
  StatusChip,
  formatCompact,
  formatPct,
  formatPrice,
} from '@/components/ui';

const TFS: Timeframe[] = ['15m', '1h', '4h', '1d'];

interface AssetResponse {
  ok: boolean;
  ticker: Ticker | null;
  structures: { timeframe: Timeframe; structure: string | null; rsi: number | null; atrPct: number | null }[];
  opportunities: Opportunity[];
}

interface KlineResponse {
  ok: boolean;
  candles: Candle[];
  levels: { price: number; touches: number; kind: string; strength: number }[];
  structure: string | null;
}

export default function AssetPage({ params }: { params: Promise<{ category: string; symbol: string }> }) {
  const { category, symbol } = use(params);
  const [timeframe, setTimeframe] = useState<Timeframe>('1h');

  const asset = usePolling<AssetResponse>(`/api/market?view=asset&category=${category}&symbol=${symbol}`, 20_000);
  const klines = usePolling<KlineResponse>(
    `/api/market?view=klines&category=${category}&symbol=${symbol}&timeframe=${timeframe}`,
    30_000,
  );

  const ticker = asset.data?.ticker;

  return (
    <div className="space-y-5 pt-2">
      <Link href="/scanner" className="inline-block text-xs text-[#67e8f9] hover:underline">
        ← Back to scanner
      </Link>

      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="mono text-2xl font-bold text-[#f2f5fb]">{symbol}</h1>
            <Chip tone={category === 'linear' ? 'info' : 'muted'}>
              {category === 'linear' ? 'LINEAR PERP' : 'SPOT'}
            </Chip>
          </div>
          <p className="mt-1 text-xs text-[#5c6883]">Live data from the Bybit V5 public market API</p>
        </div>
        <div className="flex items-center gap-1" role="group" aria-label="Select timeframe">
          {TFS.map((tf) => (
            <button
              key={tf}
              type="button"
              onClick={() => setTimeframe(tf)}
              aria-pressed={timeframe === tf}
              className={`rounded-lg border px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wider transition-colors ${
                timeframe === tf
                  ? 'border-[#22d3ee]/40 bg-[#22d3ee]/12 text-[#67e8f9]'
                  : 'border-white/10 text-[#7d8aa8] hover:text-[#d6dcea]'
              }`}
            >
              {tf}
            </button>
          ))}
        </div>
      </div>

      {asset.error ? (
        <Panel>
          <ErrorState message={asset.error} onRetry={asset.refresh} />
        </Panel>
      ) : null}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {asset.loading && !ticker ? (
          Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-[104px]" />)
        ) : (
          <>
            <Kpi label="Last price" value={formatPrice(ticker?.lastPrice)} tone="accent" />
            <Kpi
              label="24h change"
              value={formatPct((ticker?.price24hPcnt ?? 0) * 100)}
              tone={(ticker?.price24hPcnt ?? 0) >= 0 ? 'bull' : 'bear'}
            />
            <Kpi label="24h turnover" value={`$${formatCompact(ticker?.turnover24h)}`} />
            <Kpi
              label="Spread"
              value={ticker?.spreadBps === null || ticker?.spreadBps === undefined ? '—' : `${ticker.spreadBps.toFixed(1)}bp`}
            />
            <Kpi
              label="Funding"
              value={ticker?.fundingRate === null || ticker?.fundingRate === undefined ? '—' : `${(ticker.fundingRate * 100).toFixed(4)}%`}
              tone={(ticker?.fundingRate ?? 0) > 0 ? 'bear' : 'bull'}
              hint={category === 'linear' ? 'Positive = longs pay shorts' : 'Spot markets have no funding'}
            />
            <Kpi
              label="Open interest"
              value={ticker?.openInterest ? formatCompact(ticker.openInterest) : '—'}
              hint={category === 'linear' ? 'Contracts outstanding' : 'Perps only'}
            />
          </>
        )}
      </div>

      <Panel className="p-4">
        <SectionTitle
          title={`${timeframe} price action`}
          subtitle={
            klines.data?.structure
              ? `Detected market structure on this timeframe: ${klines.data.structure}`
              : 'Structure requires at least 60 closed candles'
          }
        />
        {klines.loading && !klines.data ? (
          <Skeleton className="h-[420px]" />
        ) : (
          <PriceChart
            candles={klines.data?.candles ?? []}
            overlays={(klines.data?.levels ?? []).map((l) => ({
              type: 'horizontal_line' as const,
              price: l.price,
              label: `${l.kind === 'high' ? 'Resistance' : 'Support'} (${l.touches})`,
              color: l.kind === 'high' ? ('bear' as const) : ('bull' as const),
            }))}
            height={420}
            ariaSummary={`${symbol} ${timeframe} candlestick chart with ${klines.data?.candles.length ?? 0} candles and ${klines.data?.levels.length ?? 0} detected support and resistance levels.`}
          />
        )}
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel className="p-4">
          <SectionTitle title="Multi-timeframe structure" subtitle="Top-down context read across timeframes" />
          <div className="scroll-x">
            <table className="w-full min-w-[380px] text-left text-xs">
              <thead>
                <tr className="border-b border-white/[0.06] text-[10px] uppercase tracking-wider text-[#5c6883]">
                  <th className="py-2 font-medium">Timeframe</th>
                  <th className="py-2 font-medium">Structure</th>
                  <th className="py-2 text-right font-medium">RSI(14)</th>
                  <th className="py-2 text-right font-medium">ATR %</th>
                </tr>
              </thead>
              <tbody>
                {(asset.data?.structures ?? []).map((s) => (
                  <tr key={s.timeframe} className="border-b border-white/[0.03]">
                    <td className="mono py-2.5 font-semibold text-[#d6dcea]">{s.timeframe}</td>
                    <td className="py-2.5">
                      {s.structure ? (
                        <Chip tone={s.structure === 'uptrend' ? 'bull' : s.structure === 'downtrend' ? 'bear' : 'muted'}>
                          {s.structure}
                        </Chip>
                      ) : (
                        <span className="text-[#5c6883]">insufficient history</span>
                      )}
                    </td>
                    <td className="mono py-2.5 text-right text-[#a8b3cc]">
                      {s.rsi === null ? '—' : s.rsi.toFixed(1)}
                    </td>
                    <td className="mono py-2.5 text-right text-[#a8b3cc]">
                      {s.atrPct === null ? '—' : `${s.atrPct.toFixed(2)}%`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>

        <Panel className="p-4">
          <SectionTitle title="Detected setups on this instrument" />
          {(asset.data?.opportunities ?? []).length === 0 ? (
            <p className="py-8 text-center text-xs text-[#5c6883]">
              No setups recorded for {symbol} yet. Setups appear here after a scan promotes one past the watch
              threshold.
            </p>
          ) : (
            <ul className="space-y-2">
              {(asset.data?.opportunities ?? []).slice(0, 8).map((o) => (
                <li key={o.id}>
                  <Link
                    href={`/opportunity/${o.id}`}
                    className="flex items-center justify-between gap-3 rounded-lg border border-white/[0.06] px-3 py-2.5 transition-colors hover:border-[#22d3ee]/30 hover:bg-white/[0.02]"
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-xs text-[#d6dcea]">{o.patternDisplayName}</span>
                      <span className="mono block text-[10px] text-[#5c6883]">
                        {o.timeframe} · {o.direction} · R:R {o.rewardToRisk}
                      </span>
                    </span>
                    <span className="flex shrink-0 items-center gap-2">
                      <StatusChip status={o.status} />
                      <span className="mono text-sm font-bold text-[#67e8f9]">{o.score}</span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  );
}
