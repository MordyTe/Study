'use client';

import { useMemo, useState } from 'react';
import Link from 'next/link';
import { usePolling } from '@/lib/hooks';
import {
  Button,
  Chip,
  DataSourceBadge,
  EmptyState,
  ErrorState,
  Panel,
  Skeleton,
  formatCompact,
  formatPct,
  formatPrice,
} from '@/components/ui';

interface Row {
  id: string;
  category: 'spot' | 'linear';
  symbol: string;
  baseCoin: string;
  lastPrice: number;
  change24hPct: number;
  turnover24h: number;
  high24h: number;
  low24h: number;
  spreadBps: number | null;
  fundingRate: number | null;
  openInterest: number | null;
  energy: number;
  reasons: string[];
}

interface Response {
  ok: boolean;
  fetchedAt: number;
  rows: Row[];
  instrumentCounts: { spot: number; linear: number; total: number };
  eligibleAfterFilters: number;
}

type SortKey = 'energy' | 'turnover24h' | 'change24hPct' | 'symbol' | 'spreadBps';

export default function ScannerPage() {
  const { data, error, loading, refresh, lastUpdated } = usePolling<Response>(
    '/api/market?view=scanner',
    30_000,
  );
  const [query, setQuery] = useState('');
  const [marketFilter, setMarketFilter] = useState<'all' | 'spot' | 'linear'>('all');
  const [sortKey, setSortKey] = useState<SortKey>('energy');
  const [sortDesc, setSortDesc] = useState(true);
  const [visible, setVisible] = useState(60);

  const rows = useMemo(() => {
    let list = data?.rows ?? [];
    if (marketFilter !== 'all') list = list.filter((r) => r.category === marketFilter);
    if (query.trim()) {
      const q = query.trim().toUpperCase();
      list = list.filter((r) => r.symbol.includes(q) || r.baseCoin.includes(q));
    }
    const sorted = [...list].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (typeof av === 'string' && typeof bv === 'string') {
        return sortDesc ? bv.localeCompare(av) : av.localeCompare(bv);
      }
      const an = typeof av === 'number' ? av : -Infinity;
      const bn = typeof bv === 'number' ? bv : -Infinity;
      return sortDesc ? bn - an : an - bn;
    });
    return sorted;
  }, [data, query, marketFilter, sortKey, sortDesc]);

  const toggleSort = (key: SortKey) => {
    if (key === sortKey) setSortDesc((v) => !v);
    else {
      setSortKey(key);
      setSortDesc(true);
    }
  };

  const header = (label: string, key: SortKey, align: 'left' | 'right' = 'left') => (
    <th className={`px-3 py-2.5 font-medium ${align === 'right' ? 'text-right' : 'text-left'}`}>
      <button
        type="button"
        onClick={() => toggleSort(key)}
        className="inline-flex items-center gap-1 hover:text-[#d6dcea]"
        aria-label={`Sort by ${label}`}
      >
        {label}
        {sortKey === key ? <span aria-hidden>{sortDesc ? '▼' : '▲'}</span> : null}
      </button>
    </th>
  );

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-4 pt-2">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-[#f2f5fb]">Live Scanner</h1>
          <p className="mt-1 text-xs text-[#5c6883]">
            {data
              ? `${data.eligibleAfterFilters} of ${data.instrumentCounts.total} instruments pass the current filters`
              : 'Loading the eligible Bybit universe…'}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <DataSourceBadge fetchedAt={lastUpdated ?? undefined} />
          <Button variant="ghost" onClick={refresh}>
            ⟳ Refresh
          </Button>
        </div>
      </div>

      <Panel className="flex flex-wrap items-center gap-3 p-3">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search symbol…"
          aria-label="Search by symbol"
          className="mono min-w-[160px] flex-1 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-[#f2f5fb] placeholder:text-[#5c6883] focus:border-[#22d3ee]/50 focus:outline-none"
        />
        <div className="flex items-center gap-1" role="group" aria-label="Filter by market">
          {(['all', 'linear', 'spot'] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMarketFilter(m)}
              aria-pressed={marketFilter === m}
              className={`rounded-lg border px-3 py-2 text-[11px] font-semibold uppercase tracking-wider transition-colors ${
                marketFilter === m
                  ? 'border-[#22d3ee]/40 bg-[#22d3ee]/12 text-[#67e8f9]'
                  : 'border-white/10 text-[#7d8aa8] hover:text-[#d6dcea]'
              }`}
            >
              {m === 'all' ? 'All' : m === 'linear' ? 'Perps' : 'Spot'}
            </button>
          ))}
        </div>
        <span className="mono text-[11px] text-[#5c6883]">{rows.length} rows</span>
      </Panel>

      {error ? (
        <Panel>
          <ErrorState message={error} onRetry={refresh} />
        </Panel>
      ) : null}

      <Panel className="overflow-hidden">
        {loading && !data ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 14 }).map((_, i) => (
              <Skeleton key={i} className="h-9" />
            ))}
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            title="No instruments match"
            detail="Try clearing the search, switching the market filter, or relaxing the liquidity and spread gates in Settings."
          />
        ) : (
          <>
            <div className="scroll-x">
              <table className="w-full min-w-[900px] text-left text-xs">
                <thead>
                  <tr className="border-b border-white/[0.06] text-[10px] uppercase tracking-wider text-[#5c6883]">
                    {header('Symbol', 'symbol')}
                    <th className="px-3 py-2.5 font-medium">Market</th>
                    <th className="px-3 py-2.5 text-right font-medium">Price</th>
                    {header('24h %', 'change24hPct', 'right')}
                    {header('Turnover', 'turnover24h', 'right')}
                    <th className="px-3 py-2.5 text-right font-medium">24h range</th>
                    {header('Spread', 'spreadBps', 'right')}
                    <th className="px-3 py-2.5 text-right font-medium">Funding</th>
                    {header('Energy', 'energy')}
                  </tr>
                </thead>
                <tbody>
                  {rows.slice(0, visible).map((row) => {
                    const rangePos =
                      row.high24h > row.low24h
                        ? ((row.lastPrice - row.low24h) / (row.high24h - row.low24h)) * 100
                        : 50;
                    return (
                      <tr key={row.id} className="border-b border-white/[0.03] hover:bg-white/[0.02]">
                        <td className="px-3 py-2.5">
                          <Link
                            href={`/asset/${row.category}/${row.symbol}`}
                            className="mono font-semibold text-[#f2f5fb] hover:text-[#67e8f9]"
                          >
                            {row.symbol}
                          </Link>
                        </td>
                        <td className="px-3 py-2.5">
                          <Chip tone={row.category === 'linear' ? 'info' : 'muted'}>
                            {row.category === 'linear' ? 'PERP' : 'SPOT'}
                          </Chip>
                        </td>
                        <td className="mono px-3 py-2.5 text-right text-[#d6dcea]">{formatPrice(row.lastPrice)}</td>
                        <td
                          className="mono px-3 py-2.5 text-right"
                          style={{ color: row.change24hPct >= 0 ? '#34d399' : '#fb7185' }}
                        >
                          {formatPct(row.change24hPct)}
                        </td>
                        <td className="mono px-3 py-2.5 text-right text-[#a8b3cc]">
                          ${formatCompact(row.turnover24h)}
                        </td>
                        <td className="px-3 py-2.5">
                          <div className="ml-auto flex w-24 items-center gap-1.5">
                            <div className="relative h-1.5 flex-1 overflow-hidden rounded-full bg-white/[0.07]">
                              <div
                                className="absolute top-0 h-full w-1 rounded-full bg-[#22d3ee]"
                                style={{ left: `${Math.max(0, Math.min(96, rangePos))}%` }}
                              />
                            </div>
                            <span className="mono w-8 text-right text-[10px] text-[#5c6883]">
                              {rangePos.toFixed(0)}%
                            </span>
                          </div>
                        </td>
                        <td className="mono px-3 py-2.5 text-right text-[#7d8aa8]">
                          {row.spreadBps === null ? '—' : `${row.spreadBps.toFixed(1)}`}
                        </td>
                        <td
                          className="mono px-3 py-2.5 text-right"
                          style={{
                            color:
                              row.fundingRate === null
                                ? '#5c6883'
                                : row.fundingRate > 0
                                  ? '#fb7185'
                                  : '#34d399',
                          }}
                        >
                          {row.fundingRate === null ? '—' : `${(row.fundingRate * 100).toFixed(4)}%`}
                        </td>
                        <td className="px-3 py-2.5">
                          <div className="flex items-center gap-2">
                            <div className="h-1.5 w-14 shrink-0 overflow-hidden rounded-full bg-white/[0.07]">
                              <div
                                className="h-full rounded-full bg-gradient-to-r from-[#22d3ee] to-[#8b5cf6]"
                                style={{ width: `${Math.min(100, row.energy * 100)}%` }}
                              />
                            </div>
                            <span className="mono text-[10px] text-[#5c6883]">
                              {(row.energy * 100).toFixed(0)}
                            </span>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {visible < rows.length ? (
              <div className="border-t border-white/[0.06] p-3 text-center">
                <Button variant="ghost" onClick={() => setVisible((v) => v + 60)}>
                  Show more ({rows.length - visible} remaining)
                </Button>
              </div>
            ) : null}
          </>
        )}
      </Panel>
    </div>
  );
}
