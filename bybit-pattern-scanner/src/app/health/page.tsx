'use client';

import { useState } from 'react';
import { usePolling } from '@/lib/hooks';
import { Button, Chip, ErrorState, HealthDot, Panel, SectionTitle, Skeleton, formatTime } from '@/components/ui';

interface HealthResponse {
  ok: boolean;
  overall: string;
  version: string;
  ranAt: string;
  checks: {
    bybit?: { reachable: boolean; latencyMs?: number; serverTime?: string; clockDriftMs?: number; status: string; error?: string };
    store?: { kind: string; persistent: boolean; lastScanAt: string | null; heartbeatAgeMs: number | null; status: string; note: string };
    telegram?: { configured: boolean; status: string; note: string };
    adapter?: { requests: number; errors: number; lastLatencyMs: number | null; lastError: string | null };
    safety?: { tradingCapability: string; allowlistedPaths: string[]; exchangeCredentialsPresent: boolean; note: string };
  };
}

interface VerifyCheck {
  name: string;
  passed: boolean;
  detail: string;
  latencyMs?: number;
  sample?: unknown;
}

interface VerifyResponse {
  ok: boolean;
  summary: string;
  serverTime: string | null;
  instrumentCounts: { spot: number; linear: number; total: number };
  btcusdtLastPrice: number;
  checks: VerifyCheck[];
  durationMs: number;
}

export default function HealthPage() {
  const health = usePolling<HealthResponse>('/api/health', 30_000);
  const [verify, setVerify] = useState<VerifyResponse | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [verifyError, setVerifyError] = useState<string | null>(null);

  const runVerify = async () => {
    setVerifying(true);
    setVerifyError(null);
    try {
      const res = await fetch('/api/verify-live', { cache: 'no-store' });
      const body = await res.json();
      setVerify(body);
      if (!body.ok) setVerifyError('One or more live checks failed — see the detail below.');
    } catch (err) {
      setVerifyError((err as Error).message);
    } finally {
      setVerifying(false);
    }
  };

  const checks = health.data?.checks;

  return (
    <div className="space-y-5 pt-2">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-[#f2f5fb]">System Health</h1>
          <p className="mt-1 text-xs text-[#5c6883]">
            Exchange connectivity, data freshness, storage, alerts and the no-trading guarantee
          </p>
        </div>
        <div className="flex items-center gap-2">
          {health.data ? <HealthDot state={health.data.overall} /> : null}
          <Button variant="ghost" onClick={health.refresh}>
            ⟳ Refresh
          </Button>
        </div>
      </div>

      {health.error ? (
        <Panel>
          <ErrorState message={health.error} onRetry={health.refresh} />
        </Panel>
      ) : null}

      {health.loading && !health.data ? (
        <div className="grid gap-4 md:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-44" />
          ))}
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          <Panel className="p-4">
            <SectionTitle title="Bybit REST" />
            {checks?.bybit?.reachable ? (
              <dl className="mono space-y-2 text-xs">
                <div className="flex justify-between">
                  <dt className="text-[#5c6883]">Status</dt>
                  <dd>
                    <HealthDot state={checks.bybit.status} />
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-[#5c6883]">Latency</dt>
                  <dd className="text-[#a8b3cc]">{checks.bybit.latencyMs}ms</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-[#5c6883]">Clock drift</dt>
                  <dd className={(checks.bybit.clockDriftMs ?? 0) < 5000 ? 'text-[#34d399]' : 'text-[#fbbf24]'}>
                    {checks.bybit.clockDriftMs}ms
                  </dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="shrink-0 text-[#5c6883]">Server time</dt>
                  <dd className="truncate text-[#a8b3cc]">{checks.bybit.serverTime}</dd>
                </div>
              </dl>
            ) : (
              <p className="text-xs text-[#fb7185]">
                Unreachable: {checks?.bybit?.error ?? 'unknown error'}
              </p>
            )}
          </Panel>

          <Panel className="p-4">
            <SectionTitle title="Storage" />
            <div className="mb-2 flex items-center gap-2">
              <Chip tone={checks?.store?.persistent ? 'bull' : 'warn'}>
                {checks?.store?.kind === 'supabase' ? 'Supabase' : 'In-memory'}
              </Chip>
            </div>
            <p className="text-[11px] leading-relaxed text-[#a8b3cc]">{checks?.store?.note}</p>
            <dl className="mono mt-3 space-y-2 border-t border-white/[0.06] pt-3 text-xs">
              <div className="flex justify-between gap-2">
                <dt className="text-[#5c6883]">Last scan</dt>
                <dd className="truncate text-[#a8b3cc]">
                  {checks?.store?.lastScanAt ? formatTime(new Date(checks.store.lastScanAt).getTime()) : 'never'}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-[#5c6883]">Heartbeat age</dt>
                <dd className="text-[#a8b3cc]">
                  {checks?.store?.heartbeatAgeMs !== null && checks?.store?.heartbeatAgeMs !== undefined
                    ? `${Math.round(checks.store.heartbeatAgeMs / 1000)}s`
                    : '—'}
                </dd>
              </div>
            </dl>
          </Panel>

          <Panel className="p-4">
            <SectionTitle title="Telegram" />
            <div className="mb-2">
              <Chip tone={checks?.telegram?.configured ? 'bull' : 'warn'}>
                {checks?.telegram?.configured ? 'Configured' : 'Not configured'}
              </Chip>
            </div>
            <p className="text-[11px] leading-relaxed text-[#a8b3cc]">{checks?.telegram?.note}</p>
          </Panel>

          <Panel className="p-4">
            <SectionTitle title="Adapter statistics" subtitle="Since this serverless instance started" />
            <dl className="mono space-y-2 text-xs">
              <div className="flex justify-between">
                <dt className="text-[#5c6883]">Requests</dt>
                <dd className="text-[#a8b3cc]">{checks?.adapter?.requests ?? 0}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-[#5c6883]">Errors</dt>
                <dd className={(checks?.adapter?.errors ?? 0) > 0 ? 'text-[#fbbf24]' : 'text-[#34d399]'}>
                  {checks?.adapter?.errors ?? 0}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-[#5c6883]">Last latency</dt>
                <dd className="text-[#a8b3cc]">{checks?.adapter?.lastLatencyMs ?? '—'}ms</dd>
              </div>
            </dl>
            {checks?.adapter?.lastError ? (
              <p className="mono mt-3 break-words rounded-md bg-[#f43f5e]/10 px-2.5 py-2 text-[10px] text-[#fb7185]">
                {checks.adapter.lastError}
              </p>
            ) : null}
          </Panel>
        </div>
      )}

      {/* Live verification gate */}
      <Panel className="p-4">
        <SectionTitle
          title="Live exchange verification"
          subtitle="The release gate. Proves this deployment is reading the real Bybit V5 API, not fixtures."
          action={
            <Button onClick={runVerify} disabled={verifying}>
              {verifying ? 'Running…' : 'Run live verification'}
            </Button>
          }
        />

        {verifyError ? <p className="mb-3 text-xs text-[#fb7185]">{verifyError}</p> : null}

        {verify ? (
          <>
            <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div className="rounded-lg border border-white/[0.06] p-3">
                <div className="text-[10px] uppercase tracking-wider text-[#5c6883]">Result</div>
                <div className={`mono mt-1 text-sm font-bold ${verify.ok ? 'text-[#34d399]' : 'text-[#fb7185]'}`}>
                  {verify.ok ? 'ALL PASSED' : 'FAILURES'}
                </div>
              </div>
              <div className="rounded-lg border border-white/[0.06] p-3">
                <div className="text-[10px] uppercase tracking-wider text-[#5c6883]">Instruments</div>
                <div className="mono mt-1 text-sm font-bold text-[#67e8f9]">{verify.instrumentCounts.total}</div>
                <div className="mono text-[10px] text-[#5c6883]">
                  {verify.instrumentCounts.linear} perp · {verify.instrumentCounts.spot} spot
                </div>
              </div>
              <div className="rounded-lg border border-white/[0.06] p-3">
                <div className="text-[10px] uppercase tracking-wider text-[#5c6883]">BTCUSDT</div>
                <div className="mono mt-1 text-sm font-bold text-[#f2f5fb]">
                  {verify.btcusdtLastPrice.toLocaleString('en-US', { maximumFractionDigits: 1 })}
                </div>
              </div>
              <div className="rounded-lg border border-white/[0.06] p-3">
                <div className="text-[10px] uppercase tracking-wider text-[#5c6883]">Duration</div>
                <div className="mono mt-1 text-sm font-bold text-[#a8b3cc]">
                  {(verify.durationMs / 1000).toFixed(1)}s
                </div>
              </div>
            </div>

            <ul className="space-y-2">
              {verify.checks.map((c) => (
                <li key={c.name} className="rounded-lg border border-white/[0.06] p-3">
                  <div className="flex items-start justify-between gap-3">
                    <span className="text-xs font-medium text-[#d6dcea]">{c.name}</span>
                    <Chip tone={c.passed ? 'bull' : 'bear'}>{c.passed ? 'PASS' : 'FAIL'}</Chip>
                  </div>
                  <p className="mt-1.5 text-[11px] leading-relaxed text-[#7d8aa8]">{c.detail}</p>
                  {c.latencyMs !== undefined ? (
                    <p className="mono mt-1 text-[10px] text-[#5c6883]">{c.latencyMs}ms</p>
                  ) : null}
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="py-6 text-center text-xs text-[#5c6883]">
            Press <strong className="text-[#a8b3cc]">Run live verification</strong> to check server time, instrument
            pagination, tickers, klines, candle integrity and REST reconciliation against Bybit right now.
          </p>
        )}
      </Panel>

      {/* Safety */}
      <Panel className="border-[#10b981]/25 p-4">
        <SectionTitle title="No-trading guarantee" />
        <p className="text-[11px] leading-relaxed text-[#a8b3cc]">{checks?.safety?.note}</p>
        <dl className="mono mt-3 space-y-2 text-xs">
          <div className="flex justify-between">
            <dt className="text-[#5c6883]">Trading capability</dt>
            <dd className="text-[#34d399]">{checks?.safety?.tradingCapability ?? 'NONE'}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-[#5c6883]">Exchange credentials present</dt>
            <dd className={checks?.safety?.exchangeCredentialsPresent ? 'text-[#fb7185]' : 'text-[#34d399]'}>
              {checks?.safety?.exchangeCredentialsPresent ? 'YES — REMOVE THEM' : 'NO'}
            </dd>
          </div>
        </dl>
        <div className="mt-3 border-t border-white/[0.06] pt-3">
          <h3 className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-[#5c6883]">
            Allowlisted endpoints (the only URLs this app may call)
          </h3>
          <ul className="mono grid gap-1 text-[10px] text-[#7d8aa8] sm:grid-cols-2">
            {(checks?.safety?.allowlistedPaths ?? []).map((p) => (
              <li key={p}>GET {p}</li>
            ))}
          </ul>
        </div>
      </Panel>
    </div>
  );
}
