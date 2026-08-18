import { Badge, Card, Stat } from '@/components/ui';
import { getLlmProvider } from '@/lib/agents/llm';
import { listAdapterStats } from '@/lib/net/client';
import { MIN_CALIBRATION_SAMPLE, computeCalibration } from '@/lib/paper/calibration';
import { getStore } from '@/lib/store';

export const dynamic = 'force-dynamic';

export default async function HealthPage() {
  const store = await getStore();
  const [scans, candidates, resolutions] = await Promise.all([
    store.listScans(10),
    store.listCandidates(500),
    store.listResolutions(),
  ]);
  const llm = getLlmProvider();
  const adapters = listAdapterStats();
  const calibration = computeCalibration(candidates, resolutions);

  return (
    <main className="space-y-6">
      <Card>
        <h1 className="text-base font-medium">System state</h1>
        <div className="mt-4 grid grid-cols-2 gap-5 sm:grid-cols-3">
          <Stat
            label="Store"
            value={store.kind}
            detail={store.kind === 'memory' ? 'NOT durable — lost on restart' : 'durable'}
          />
          <Stat
            label="Agent provider"
            value={llm.kind}
            detail={
              llm.kind === 'unavailable'
                ? 'every market will abstain'
                : llm.kind === 'replay'
                  ? 'serving recorded fixtures'
                  : 'live'
            }
          />
          <Stat label="Scans recorded" value={String(scans.length)} />
        </div>
        {store.kind === 'memory' ? (
          <p className="mt-5 text-sm leading-relaxed" style={{ color: 'var(--warn)' }}>
            The in-memory store is not persistence. Everything here is lost when the process
            restarts. Configure Supabase to keep results across restarts — which is required before
            any calibration measurement means anything, since calibration needs months of resolved
            outcomes.
          </p>
        ) : null}
      </Card>

      <Card>
        <h2 className="text-sm font-medium">
          Calibration — {calibration.minSampleMet ? 'measurable' : 'insufficient sample'}
        </h2>
        <p className="mt-3 text-sm leading-relaxed" style={{ color: 'var(--muted)' }}>
          {calibration.detail}
        </p>
        <div className="mt-4 grid grid-cols-2 gap-5 sm:grid-cols-4">
          <Stat
            label="Resolved estimates"
            value={String(calibration.n)}
            detail={`minimum ${MIN_CALIBRATION_SAMPLE}`}
          />
          <Stat
            label="Brier — ours"
            value={calibration.brierOurs === null ? '—' : calibration.brierOurs.toFixed(4)}
            detail="lower is better"
          />
          <Stat
            label="Brier — market"
            value={calibration.brierMarket === null ? '—' : calibration.brierMarket.toFixed(4)}
            detail="the bar to clear"
          />
          <Stat
            label="Paper P&L"
            value={`$${calibration.totalPnl.toFixed(2)}`}
            detail={`on $${calibration.totalStaked.toFixed(2)} staked`}
          />
        </div>
        {calibration.buckets.length > 0 ? (
          <div className="mt-5 overflow-x-auto">
            <table className="tabular w-full min-w-sm text-sm">
              <thead>
                <tr style={{ color: 'var(--muted)' }} className="text-left text-xs">
                  <th className="pb-2 pr-4 font-normal">Forecast bucket</th>
                  <th className="pb-2 pr-4 font-normal">Markets</th>
                  <th className="pb-2 pr-4 font-normal">Mean forecast</th>
                  <th className="pb-2 font-normal">Actual frequency</th>
                </tr>
              </thead>
              <tbody>
                {calibration.buckets.map((bucket) => (
                  <tr
                    key={bucket.lo}
                    className="border-t"
                    style={{ borderColor: 'var(--border)' }}
                  >
                    <td className="py-1.5 pr-4">
                      {(bucket.lo * 100).toFixed(0)}–{(bucket.hi * 100).toFixed(0)}%
                    </td>
                    <td className="py-1.5 pr-4">{bucket.count}</td>
                    <td className="py-1.5 pr-4">{(bucket.meanForecast * 100).toFixed(1)}%</td>
                    <td className="py-1.5">{(bucket.frequency * 100).toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        <p className="mt-4 text-sm leading-relaxed">
          Estimates produced so far: <strong>{candidates.length}</strong>. Until the minimum sample
          is met, a displayed probability is a hypothesis wearing the costume of a measurement —
          and the candidates page says so.
        </p>
      </Card>

      <Card>
        <h2 className="text-sm font-medium">Venue adapters</h2>
        {Object.keys(adapters).length === 0 ? (
          <p className="mt-3 text-sm" style={{ color: 'var(--muted)' }}>
            No outbound request has been made yet in this process.
          </p>
        ) : (
          <div className="mt-3 space-y-3 text-sm">
            {Object.entries(adapters).map(([name, stats]) => (
              <div key={name} className="flex flex-wrap justify-between gap-3">
                <span className="font-medium">{name}</span>
                <span className="tabular" style={{ color: 'var(--muted)' }}>
                  {stats.requests} requests · {stats.errors} errors
                  {stats.lastLatencyMs !== null ? ` · ${stats.lastLatencyMs}ms last` : ''}
                  {stats.lastError ? ` · ${stats.lastError}` : ''}
                </span>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card>
        <h2 className="text-sm font-medium">Recent scans</h2>
        {scans.length === 0 ? (
          <p className="mt-3 text-sm" style={{ color: 'var(--muted)' }}>
            No scan has run yet.
          </p>
        ) : (
          <div className="mt-3 space-y-4">
            {scans.map((scan) => (
              <div key={scan.id} className="border-t pt-3" style={{ borderColor: 'var(--border)' }}>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <span className="tabular text-sm">
                    {new Date(scan.startedAt).toISOString().replace('T', ' ').slice(0, 19)}
                  </span>
                  <span className="flex gap-2">
                    <Badge label={`${scan.actionable} actionable`} />
                    <Badge label={`${scan.watch} watch`} />
                    <Badge label={`${scan.abstain} abstain`} />
                  </span>
                </div>
                <p className="tabular mt-1 text-xs" style={{ color: 'var(--muted)' }}>
                  {scan.universeSize} markets seen · {scan.promoted} promoted ·{' '}
                  {scan.finishedAt - scan.startedAt}ms
                </p>
                {scan.errors.length > 0 ? (
                  <ul className="mt-2 space-y-1 text-xs" style={{ color: 'var(--muted)' }}>
                    {scan.errors.slice(0, 6).map((error, i) => (
                      <li key={i}>· {error}</li>
                    ))}
                    {scan.errors.length > 6 ? (
                      <li>· …and {scan.errors.length - 6} more</li>
                    ) : null}
                  </ul>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </Card>
    </main>
  );
}
