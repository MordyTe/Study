'use client';

import { use } from 'react';
import Link from 'next/link';
import { usePolling } from '@/lib/hooks';
import type { Opportunity } from '@/lib/engine/opportunity';
import type { Candle } from '@/lib/bybit/types';
import { PriceChart } from '@/components/price-chart';
import {
  Chip,
  ErrorState,
  HealthDot,
  Panel,
  ScoreRing,
  SectionTitle,
  Skeleton,
  StatusChip,
  formatPrice,
  formatTime,
} from '@/components/ui';

interface Response {
  ok: boolean;
  opportunity: Opportunity;
  candles: Candle[];
}

export default function OpportunityDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data, error, loading, refresh } = usePolling<Response>(`/api/opportunities/${id}`, 30_000);

  if (loading && !data) {
    return (
      <div className="space-y-4 pt-2">
        <Skeleton className="h-24" />
        <Skeleton className="h-[420px]" />
      </div>
    );
  }

  if (error || !data?.opportunity) {
    return (
      <Panel className="mt-4">
        <ErrorState message={error ?? 'Opportunity not found.'} onRetry={refresh} />
      </Panel>
    );
  }

  const opp = data.opportunity;
  const isLong = opp.direction === 'long';

  return (
    <div className="space-y-5 pt-2">
      <Link href="/opportunities" className="inline-block text-xs text-[#67e8f9] hover:underline">
        ← Back to opportunities
      </Link>

      {/* Header */}
      <Panel className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="mono text-2xl font-bold text-[#f2f5fb]">{opp.symbol}</h1>
              <Chip tone={opp.category === 'linear' ? 'info' : 'muted'}>
                {opp.category === 'linear' ? 'LINEAR PERP' : 'SPOT'}
              </Chip>
              <Chip tone="muted">{opp.timeframe}</Chip>
              <Chip tone={isLong ? 'bull' : 'bear'}>{isLong ? '▲ Potential long' : '▼ Potential short'}</Chip>
              <StatusChip status={opp.status} />
            </div>
            <p className="mt-2 text-sm text-[#a8b3cc]">{opp.patternDisplayName}</p>
            <p className="mono mt-1 text-[11px] text-[#5c6883]">
              {opp.detectorName}@{opp.detectorVersion} · detected {formatTime(opp.detectedAt)}
            </p>
          </div>
          <div className="flex items-center gap-4">
            <div className="text-right">
              <div className="text-[10px] uppercase tracking-wider text-[#5c6883]">Setup quality</div>
              <div className="mono mt-1 text-xs text-[#7d8aa8]">not a win probability</div>
            </div>
            <ScoreRing score={opp.score} size={72} />
          </div>
        </div>
      </Panel>

      <div className="grid gap-4 lg:grid-cols-[1.65fr_1fr]">
        <div className="space-y-4">
          {/* Chart */}
          <Panel className="p-4">
            <SectionTitle
              title="Price action & pattern overlays"
              subtitle={`${opp.timeframe} candles from Bybit V5 · overlays render from the stored evidence bundle`}
            />
            <PriceChart
              candles={data.candles}
              overlays={[
                ...opp.overlays,
                { type: 'price_zone', from: opp.entryZone.from, to: opp.entryZone.to, label: 'Entry scenario', color: isLong ? 'bull' : 'bear' },
                ...opp.targets.map((t, i) => ({ type: 'target_line' as const, price: t.price, label: `T${i + 1}` })),
              ]}
              height={440}
              ariaSummary={`${opp.symbol} ${opp.timeframe} chart showing a ${opp.patternDisplayName} with entry zone ${formatPrice(opp.entryZone.from)} to ${formatPrice(opp.entryZone.to)}, invalidation at ${formatPrice(opp.invalidation)}.`}
            />
          </Panel>

          {/* Reasons */}
          <div className="grid gap-4 sm:grid-cols-2">
            <Panel className="p-4">
              <SectionTitle title="Why it qualifies" />
              <ul className="space-y-2.5">
                {opp.reasonsFor.map((r, i) => (
                  <li key={i} className="flex gap-2 text-xs leading-relaxed text-[#a8b3cc]">
                    <span className="mt-0.5 shrink-0 text-[#34d399]" aria-hidden>
                      ✓
                    </span>
                    <span>{r}</span>
                  </li>
                ))}
              </ul>
            </Panel>
            <Panel className="p-4">
              <SectionTitle title="Main risks" />
              <ul className="space-y-2.5">
                {opp.reasonsAgainst.map((r, i) => (
                  <li key={i} className="flex gap-2 text-xs leading-relaxed text-[#a8b3cc]">
                    <span className="mt-0.5 shrink-0 text-[#fbbf24]" aria-hidden>
                      !
                    </span>
                    <span>{r}</span>
                  </li>
                ))}
              </ul>
            </Panel>
          </div>

          {/* Score breakdown */}
          <Panel className="p-4">
            <SectionTitle
              title="Setup quality breakdown"
              subtitle="Every point is attributable. This measures how well-formed the setup is — not how likely it is to profit."
            />
            <div className="space-y-3">
              {opp.scoreComponents.map((c) => (
                <div key={c.key}>
                  <div className="flex items-baseline justify-between gap-3 text-xs">
                    <span className="text-[#d6dcea]">{c.label}</span>
                    <span className="mono shrink-0 text-[#67e8f9]">
                      {c.value} / {c.max}
                    </span>
                  </div>
                  <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-white/[0.07]">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-[#22d3ee] to-[#8b5cf6]"
                      style={{ width: `${Math.max(0, Math.min(100, (c.value / c.max) * 100))}%` }}
                    />
                  </div>
                  <p className="mt-1.5 text-[11px] leading-relaxed text-[#5c6883]">{c.detail}</p>
                </div>
              ))}

              {opp.scorePenalties.length > 0 ? (
                <div className="mt-4 border-t border-white/[0.06] pt-3">
                  <h3 className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-[#fb7185]">
                    Penalties applied
                  </h3>
                  {opp.scorePenalties.map((p) => (
                    <div key={p.key} className="mb-2">
                      <div className="flex items-baseline justify-between gap-3 text-xs">
                        <span className="text-[#d6dcea]">{p.label}</span>
                        <span className="mono shrink-0 text-[#fb7185]">{p.value}</span>
                      </div>
                      <p className="mt-0.5 text-[11px] leading-relaxed text-[#5c6883]">{p.detail}</p>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          </Panel>
        </div>

        {/* Sidebar */}
        <div className="space-y-4">
          <Panel className="p-4">
            <SectionTitle title="Scenario levels" subtitle="Analytical values — never orders" />
            <dl className="mono space-y-3 text-xs">
              <div className="flex items-baseline justify-between gap-2">
                <dt className="text-[#5c6883]">Last price</dt>
                <dd className="text-[#f2f5fb]">{formatPrice(opp.lastPrice)}</dd>
              </div>
              <div className="flex items-baseline justify-between gap-2">
                <dt className="text-[#5c6883]">Entry zone</dt>
                <dd className="text-[#d6dcea]">
                  {formatPrice(opp.entryZone.from)} – {formatPrice(opp.entryZone.to)}
                </dd>
              </div>
              <div className="flex items-baseline justify-between gap-2">
                <dt className="text-[#5c6883]">Invalidation</dt>
                <dd className="text-[#fb7185]">{formatPrice(opp.invalidation)}</dd>
              </div>
              {opp.targets.map((t, i) => (
                <div key={i}>
                  <div className="flex items-baseline justify-between gap-2">
                    <dt className="text-[#5c6883]">Target {i + 1}</dt>
                    <dd className={t.reached ? 'text-[#34d399]' : 'text-[#d6dcea]'}>
                      {formatPrice(t.price)} {t.reached ? '✓' : ''}
                    </dd>
                  </div>
                  <p className="mt-0.5 text-right text-[10px] text-[#5c6883]">{t.method}</p>
                </div>
              ))}
              <div className="flex items-baseline justify-between gap-2 border-t border-white/[0.06] pt-3">
                <dt className="text-[#5c6883]">Est. reward:risk</dt>
                <dd className={opp.rewardToRisk >= 2 ? 'text-[#34d399]' : 'text-[#fbbf24]'}>
                  {opp.rewardToRisk}
                </dd>
              </div>
            </dl>
            <p className="mt-4 border-t border-white/[0.06] pt-3 text-[10px] leading-relaxed text-[#5c6883]">
              These are analytical scenario values produced by pattern geometry. This system does not place,
              approve, or manage any order.
            </p>
          </Panel>

          <Panel className="p-4">
            <SectionTitle title="Data verification" />
            <div className="mb-3">
              <HealthDot state={opp.verification.health} />
            </div>
            <dl className="mono space-y-2 text-[11px]">
              <div className="flex justify-between gap-2">
                <dt className="text-[#5c6883]">Source</dt>
                <dd className="text-[#d6dcea]">{opp.verification.source}</dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt className="text-[#5c6883]">Exchange time</dt>
                <dd className="text-[#a8b3cc]">{formatTime(opp.verification.exchangeTimestamp)}</dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt className="text-[#5c6883]">Clock drift</dt>
                <dd className="text-[#a8b3cc]">{opp.verification.clockDriftMs}ms</dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt className="text-[#5c6883]">Data age</dt>
                <dd className="text-[#a8b3cc]">{(opp.verification.dataAgeMs / 1000).toFixed(0)}s</dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt className="text-[#5c6883]">REST latency</dt>
                <dd className="text-[#a8b3cc]">{opp.verification.restLatencyMs}ms</dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt className="text-[#5c6883]">Reconciliation</dt>
                <dd className={opp.verification.reconciliationPassed ? 'text-[#34d399]' : 'text-[#fb7185]'}>
                  {opp.verification.reconciliationPassed ? 'PASSED' : 'FAILED'}
                  {opp.verification.reconciliationDeltaPct !== null
                    ? ` (${opp.verification.reconciliationDeltaPct}%)`
                    : ''}
                </dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt className="text-[#5c6883]">Candle gaps</dt>
                <dd className={opp.verification.candleGapsDetected === 0 ? 'text-[#34d399]' : 'text-[#fbbf24]'}>
                  {opp.verification.candleGapsDetected}
                </dd>
              </div>
              <div className="flex justify-between gap-2 border-t border-white/[0.06] pt-2">
                <dt className="text-[#5c6883]">Record ID</dt>
                <dd className="truncate text-[10px] text-[#5c6883]">{opp.verification.id}</dd>
              </div>
            </dl>
          </Panel>

          <Panel className="p-4">
            <SectionTitle title="Lifecycle" />
            <ol className="space-y-3">
              {opp.events.map((e, i) => (
                <li key={i} className="flex gap-3 text-[11px]">
                  <span className="mono shrink-0 text-[#5c6883]">{formatTime(e.at).slice(-8)}</span>
                  <span className="min-w-0">
                    <span className="block font-semibold text-[#d6dcea]">{e.type.replace(/_/g, ' ')}</span>
                    <span className="block leading-relaxed text-[#5c6883]">{e.detail}</span>
                  </span>
                </li>
              ))}
            </ol>
            <dl className="mono mt-4 space-y-2 border-t border-white/[0.06] pt-3 text-[11px]">
              <div className="flex justify-between">
                <dt className="text-[#5c6883]">Entry zone touched</dt>
                <dd className="text-[#a8b3cc]">{opp.entryZoneTouched ? 'Yes' : 'Not yet'}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-[#5c6883]">Max favorable</dt>
                <dd className="text-[#34d399]">{opp.maxFavorableExcursionPct}%</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-[#5c6883]">Max adverse</dt>
                <dd className="text-[#fb7185]">{opp.maxAdverseExcursionPct}%</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-[#5c6883]">Expires</dt>
                <dd className="text-[#a8b3cc]">{formatTime(opp.expiresAt)}</dd>
              </div>
            </dl>
          </Panel>

          <Panel className="p-4">
            <SectionTitle title="Detector parameters" subtitle="Persisted so this result stays reproducible" />
            <dl className="mono space-y-1.5 text-[11px]">
              {Object.entries(opp.parameters).map(([k, v]) => (
                <div key={k} className="flex justify-between gap-2">
                  <dt className="truncate text-[#5c6883]">{k}</dt>
                  <dd className="shrink-0 text-[#a8b3cc]">{String(v)}</dd>
                </div>
              ))}
            </dl>
          </Panel>

          <a
            href={`https://www.bybit.com/trade/usdt/${opp.symbol}`}
            target="_blank"
            rel="noopener noreferrer"
            className="block rounded-lg border border-white/10 bg-white/[0.03] px-4 py-3 text-center text-xs text-[#a8b3cc] transition-colors hover:bg-white/[0.06] hover:text-[#f2f5fb]"
          >
            Open {opp.symbol} on Bybit ↗
            <span className="mt-1 block text-[10px] text-[#5c6883]">
              External link only — this app performs no action on your account
            </span>
          </a>
        </div>
      </div>
    </div>
  );
}
