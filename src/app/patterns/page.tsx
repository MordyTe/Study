'use client';

import { usePolling } from '@/lib/hooks';
import { Chip, ErrorState, Panel, SectionTitle, Skeleton } from '@/components/ui';

interface Detector {
  name: string;
  version: string;
  displayName: string;
  description: string;
  minCandles: number;
  enabled: boolean;
  signalsProduced: number;
  resolved: number;
  hitRate: number | null;
  avgScore: number | null;
}

export default function PatternsPage() {
  const { data, error, loading, refresh } = usePolling<{ detectors: Detector[]; sampleSizeNote: string }>(
    '/api/patterns',
    60_000,
  );

  return (
    <div className="space-y-5 pt-2">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-[#f2f5fb]">Pattern Library</h1>
        <p className="mt-1 text-xs text-[#5c6883]">
          Every detector in plain language, with its version, requirements and observed behaviour
        </p>
      </div>

      <Panel className="border-[#f59e0b]/20 p-4">
        <p className="text-[11px] leading-relaxed text-[#fbbf24]">
          <strong>On performance numbers:</strong> {data?.sampleSizeNote ?? 'Hit rate is withheld until enough signals have resolved.'}{' '}
          A hit rate over a small sample says almost nothing about future results. Setup Quality is a measure of how
          well-formed a setup is — it is deliberately not presented as a win probability.
        </p>
      </Panel>

      {error ? (
        <Panel>
          <ErrorState message={error} onRetry={refresh} />
        </Panel>
      ) : null}

      {loading && !data ? (
        <div className="grid gap-3 md:grid-cols-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-40" />
          ))}
        </div>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {(data?.detectors ?? []).map((d) => (
            <Panel key={d.name} className="p-4" hover>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h2 className="text-sm font-semibold text-[#f2f5fb]">{d.displayName}</h2>
                  <p className="mono mt-0.5 text-[10px] text-[#5c6883]">
                    {d.name}@{d.version} · needs {d.minCandles} closed candles
                  </p>
                </div>
                <Chip tone={d.enabled ? 'bull' : 'muted'}>{d.enabled ? 'Enabled' : 'Muted'}</Chip>
              </div>

              <p className="mt-3 text-[11px] leading-relaxed text-[#a8b3cc]">{d.description}</p>

              <dl className="mono mt-4 grid grid-cols-3 gap-2 border-t border-white/[0.06] pt-3 text-[11px]">
                <div>
                  <dt className="text-[9px] uppercase tracking-wider text-[#5c6883]">Signals</dt>
                  <dd className="mt-0.5 text-[#d6dcea]">{d.signalsProduced}</dd>
                </div>
                <div>
                  <dt className="text-[9px] uppercase tracking-wider text-[#5c6883]">Resolved</dt>
                  <dd className="mt-0.5 text-[#d6dcea]">{d.resolved}</dd>
                </div>
                <div>
                  <dt className="text-[9px] uppercase tracking-wider text-[#5c6883]">Hit rate</dt>
                  <dd className="mt-0.5 text-[#67e8f9]">
                    {d.hitRate === null ? <span className="text-[#5c6883]">n/a</span> : `${d.hitRate}%`}
                  </dd>
                </div>
              </dl>
            </Panel>
          ))}
        </div>
      )}
    </div>
  );
}
