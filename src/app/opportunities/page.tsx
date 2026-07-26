'use client';

import { useMemo, useState } from 'react';
import { usePolling } from '@/lib/hooks';
import type { Opportunity } from '@/lib/engine/opportunity';
import { OpportunityCard } from '@/components/opportunity-card';
import { Button, EmptyState, ErrorState, Panel, Skeleton } from '@/components/ui';

const STATUSES = ['ALL', 'CONFIRMED', 'FORMING', 'TARGET_1_REACHED', 'INVALIDATED', 'EXPIRED'] as const;

export default function OpportunitiesPage() {
  const { data, error, loading, refresh } = usePolling<{ items: Opportunity[]; count: number }>(
    '/api/opportunities?limit=200',
    30_000,
  );
  const [status, setStatus] = useState<(typeof STATUSES)[number]>('ALL');
  const [minScore, setMinScore] = useState(0);

  const items = useMemo(() => {
    let list = data?.items ?? [];
    if (status !== 'ALL') list = list.filter((o) => o.status === status);
    if (minScore > 0) list = list.filter((o) => o.score >= minScore);
    return list.sort((a, b) => b.score - a.score);
  }, [data, status, minScore]);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-4 pt-2">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-[#f2f5fb]">Opportunities</h1>
          <p className="mt-1 text-xs text-[#5c6883]">
            Every detected setup with its full evidence bundle and lifecycle state
          </p>
        </div>
        <Button variant="ghost" onClick={refresh}>
          ⟳ Refresh
        </Button>
      </div>

      <Panel className="flex flex-wrap items-center gap-3 p-3">
        <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Filter by status">
          {STATUSES.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setStatus(s)}
              aria-pressed={status === s}
              className={`rounded-lg border px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider transition-colors ${
                status === s
                  ? 'border-[#22d3ee]/40 bg-[#22d3ee]/12 text-[#67e8f9]'
                  : 'border-white/10 text-[#7d8aa8] hover:text-[#d6dcea]'
              }`}
            >
              {s.replace(/_/g, ' ')}
            </button>
          ))}
        </div>
        <label className="ml-auto flex items-center gap-2 text-[11px] text-[#7d8aa8]">
          Min score
          <input
            type="range"
            min={0}
            max={100}
            step={5}
            value={minScore}
            onChange={(e) => setMinScore(Number(e.target.value))}
            className="w-28 accent-[#22d3ee]"
          />
          <span className="mono w-6 text-[#d6dcea]">{minScore}</span>
        </label>
      </Panel>

      {error ? (
        <Panel>
          <ErrorState message={error} onRetry={refresh} />
        </Panel>
      ) : null}

      {loading && !data ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-[248px]" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <Panel>
          <EmptyState
            title="No opportunities match these filters"
            detail="Opportunities appear after a scan promotes a setup past the watch threshold. Run a scan from the Command Center, or relax the filters above."
          />
        </Panel>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {items.map((opp) => (
            <OpportunityCard key={opp.id} opp={opp} />
          ))}
        </div>
      )}
    </div>
  );
}
