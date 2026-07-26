'use client';

import { useState } from 'react';
import Link from 'next/link';
import { usePolling } from '@/lib/hooks';
import type { Opportunity } from '@/lib/engine/opportunity';
import { OpportunityCard } from '@/components/opportunity-card';
import {
  Button,
  Chip,
  DataSourceBadge,
  EmptyState,
  ErrorState,
  Kpi,
  Panel,
  SectionTitle,
  Skeleton,
  formatCompact,
  formatPct,
  formatPrice,
  formatTime,
} from '@/components/ui';

interface MarketRow {
  id: string;
  category: 'spot' | 'linear';
  symbol: string;
  lastPrice: number;
  change24hPct: number;
  turnover24h: number;
  spreadBps: number | null;
  fundingRate: number | null;
  energy: number;
  reasons: string[];
}

interface OverviewResponse {
  ok: boolean;
  fetchedAt: number;
  instrumentCounts: { spot: number; linear: number; total: number };
  eligibleAfterFilters: number;
  rows: MarketRow[];
  opportunities: { confirmed: number; forming: number; total: number };
  lastScan: {
    id: string;
    finishedAt: number;
    instrumentsScanned: number;
    confirmed: number;
    forming: number;
    durationMs: number;
    alertsSent: number;
  } | null;
  storeKind: string;
  settings: { markets: string[]; timeframes: string[]; confirmedThreshold: number };
}

export default function CommandCenter() {
  const market = usePolling<OverviewResponse>('/api/market?view=overview', 30_000);
  const opps = usePolling<{ items: Opportunity[]; count: number }>('/api/opportunities?limit=12', 30_000);
  const [scanning, setScanning] = useState(false);
  const [scanMessage, setScanMessage] = useState<string | null>(null);

  const runScan = async () => {
    setScanning(true);
    setScanMessage('Scanning the live Bybit universe — this can take up to a minute…');
    try {
      const res = await fetch('/api/scan', { method: 'POST' });
      const body = await res.json();
      setScanMessage(
        body.ok
          ? `Scan complete: ${body.scan.instrumentsScanned} instruments ranked, ${body.confirmed} confirmed, ${body.forming} forming, in ${(body.scan.durationMs / 1000).toFixed(1)}s.`
          : `Scan failed: ${body.error}`,
      );
      market.refresh();
      opps.refresh();
    } catch (err) {
      setScanMessage(`Scan failed: ${(err as Error).message}`);
    } finally {
      setScanning(false);
    }
  };

  const data = market.data;
  const active = (opps.data?.items ?? []).filter(
    (o) => !['INVALIDATED', 'EXPIRED', 'CLOSED_TRACKING'].includes(o.status),
  );
  const confirmed = active.filter((o) => o.status === 'CONFIRMED');
  const forming = active.filter((o) => o.status === 'FORMING');

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4 pt-2">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-[#f2f5fb]">Command Center</h1>
          <p className="mt-1 text-xs text-[#5c6883]">
            Live analysis across the full Bybit USDT universe · spot and linear perpetuals
          </p>
        </div>
        <div className="flex items-center gap-3">
          <DataSourceBadge fetchedAt={data?.fetchedAt} />
          <Button onClick={runScan} disabled={scanning}>
            {scanning ? 'Scanning…' : '⟳ Scan now'}
          </Button>
        </div>
      </div>

      {scanMessage ? (
        <Panel className="px-4 py-3">
          <p className="text-xs text-[#a8b3cc]">{scanMessage}</p>
        </Panel>
      ) : null}

      {market.error ? <Panel><ErrorState message={market.error} onRetry={market.refresh} /></Panel> : null}

      {/* KPI row */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {market.loading && !data ? (
          Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-[104px]" />)
        ) : (
          <>
            <Kpi
              label="Active instruments"
              value={data?.instrumentCounts.total ?? '—'}
              hint={`${data?.instrumentCounts.linear ?? 0} perps · ${data?.instrumentCounts.spot ?? 0} spot`}
              tone="accent"
            />
            <Kpi
              label="Passing filters"
              value={data?.eligibleAfterFilters ?? '—'}
              hint="After liquidity, spread and age gates"
            />
            <Kpi
              label="Confirmed now"
              value={confirmed.length}
              hint={`Score ≥ ${data?.settings.confirmedThreshold ?? 75} on verified closed candles`}
              tone={confirmed.length > 0 ? 'bull' : 'default'}
            />
            <Kpi
              label="Forming"
              value={forming.length}
              hint="Watch-level setups, not alert-eligible"
              tone={forming.length > 0 ? 'warn' : 'default'}
            />
            <Kpi
              label="Last scan"
              value={data?.lastScan ? `${(data.lastScan.durationMs / 1000).toFixed(1)}s` : '—'}
              hint={data?.lastScan ? formatTime(data.lastScan.finishedAt) : 'No scan recorded yet'}
            />
            <Kpi
              label="Alerts sent"
              value={data?.lastScan?.alertsSent ?? 0}
              hint="Telegram deliveries in the last scan"
            />
          </>
        )}
      </div>

      {/* Opportunity deck */}
      <section>
        <SectionTitle
          title="Opportunity deck"
          subtitle="Confirmed and forming setups, ranked by setup quality"
          action={
            <Link href="/opportunities" className="text-xs font-medium text-[#67e8f9] hover:underline">
              View all →
            </Link>
          }
        />
        {opps.loading && !opps.data ? (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-[248px]" />
            ))}
          </div>
        ) : active.length === 0 ? (
          <Panel>
            <EmptyState
              title="No active setups right now"
              detail="The engine only promotes a setup when pattern geometry, confirmation quality, liquidity and data verification all clear their gates. An empty deck is a valid, honest result — not a failure. Run a scan to evaluate the current market."
              action={
                <Button onClick={runScan} disabled={scanning}>
                  {scanning ? 'Scanning…' : 'Run a scan'}
                </Button>
              }
            />
          </Panel>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {[...confirmed, ...forming].slice(0, 9).map((opp) => (
              <OpportunityCard key={opp.id} opp={opp} />
            ))}
          </div>
        )}
      </section>

      {/* Live market energy */}
      <section>
        <SectionTitle
          title="Live market energy"
          subtitle="Tier-1 ranking across the eligible universe — liquidity, volatility, range position and funding"
          action={
            <Link href="/scanner" className="text-xs font-medium text-[#67e8f9] hover:underline">
              Open scanner →
            </Link>
          }
        />
        <Panel className="overflow-hidden">
          {market.loading && !data ? (
            <div className="space-y-2 p-4">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-9" />
              ))}
            </div>
          ) : !data?.rows.length ? (
            <EmptyState
              title="No instruments passed the current filters"
              detail="Lower the minimum 24h turnover or widen the maximum spread in Settings to include more of the market."
            />
          ) : (
            <div className="scroll-x">
              <table className="w-full min-w-[760px] text-left text-xs">
                <thead>
                  <tr className="border-b border-white/[0.06] text-[10px] uppercase tracking-wider text-[#5c6883]">
                    <th className="px-4 py-2.5 font-medium">Instrument</th>
                    <th className="px-4 py-2.5 font-medium">Market</th>
                    <th className="px-4 py-2.5 text-right font-medium">Price</th>
                    <th className="px-4 py-2.5 text-right font-medium">24h</th>
                    <th className="px-4 py-2.5 text-right font-medium">Turnover</th>
                    <th className="px-4 py-2.5 text-right font-medium">Spread</th>
                    <th className="px-4 py-2.5 font-medium">Signal energy</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.slice(0, 14).map((row) => (
                    <tr key={row.id} className="border-b border-white/[0.03] transition-colors hover:bg-white/[0.02]">
                      <td className="px-4 py-2.5">
                        <Link
                          href={`/asset/${row.category}/${row.symbol}`}
                          className="mono font-semibold text-[#f2f5fb] hover:text-[#67e8f9]"
                        >
                          {row.symbol}
                        </Link>
                      </td>
                      <td className="px-4 py-2.5">
                        <Chip tone={row.category === 'linear' ? 'info' : 'muted'}>
                          {row.category === 'linear' ? 'PERP' : 'SPOT'}
                        </Chip>
                      </td>
                      <td className="mono px-4 py-2.5 text-right text-[#d6dcea]">{formatPrice(row.lastPrice)}</td>
                      <td
                        className="mono px-4 py-2.5 text-right"
                        style={{ color: row.change24hPct >= 0 ? '#34d399' : '#fb7185' }}
                      >
                        {formatPct(row.change24hPct)}
                      </td>
                      <td className="mono px-4 py-2.5 text-right text-[#a8b3cc]">
                        ${formatCompact(row.turnover24h)}
                      </td>
                      <td className="mono px-4 py-2.5 text-right text-[#7d8aa8]">
                        {row.spreadBps === null ? '—' : `${row.spreadBps.toFixed(1)}bp`}
                      </td>
                      <td className="px-4 py-2.5">
                        <div className="flex items-center gap-2">
                          <div className="h-1.5 w-16 shrink-0 overflow-hidden rounded-full bg-white/[0.07]">
                            <div
                              className="h-full rounded-full bg-gradient-to-r from-[#22d3ee] to-[#8b5cf6]"
                              style={{ width: `${Math.min(100, row.energy * 100)}%` }}
                            />
                          </div>
                          <span className="truncate text-[10px] text-[#5c6883]">
                            {row.reasons[0] ?? 'baseline'}
                          </span>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </section>

      {data?.storeKind === 'memory' ? (
        <Panel className="border-[#f59e0b]/25 px-4 py-3">
          <p className="text-xs leading-relaxed text-[#fbbf24]">
            <strong>In-memory storage active.</strong> Live market data and analysis are fully functional, but
            opportunity history resets when the serverless instance recycles. Add Supabase credentials in{' '}
            <Link href="/settings" className="underline">
              Settings
            </Link>{' '}
            for durable history.
          </p>
        </Panel>
      ) : null}
    </div>
  );
}
