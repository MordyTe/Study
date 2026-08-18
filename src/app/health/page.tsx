import { Badge, Card, Stat } from '@/components/ui';
import { getLlmProvider } from '@/lib/agents/llm';
import { listAdapterStats } from '@/lib/net/client';
import { getStore } from '@/lib/store';

export const dynamic = 'force-dynamic';

export default async function HealthPage() {
  const store = await getStore();
  const [scans, candidates] = await Promise.all([store.listScans(10), store.listCandidates(500)]);
  const llm = getLlmProvider();
  const adapters = listAdapterStats();

  const resolved = 0; // Populated once markets this system estimated have settled.

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
        <h2 className="text-sm font-medium">Calibration</h2>
        <p className="mt-3 text-sm leading-relaxed" style={{ color: 'var(--muted)' }}>
          No probability from this system should be trusted until all five of these hold. Until
          then the numbers on the candidates page are a hypothesis, not a measurement.
        </p>
        <ul className="mt-4 space-y-2 text-sm">
          {[
            [`Resolved outcomes recorded`, `${resolved} — need hundreds`],
            ['Calibration model fitted', 'not yet'],
            ['Out-of-sample time-split evaluation', 'not yet'],
            ['Brier score and reliability curve reported', 'not yet'],
            ['Minimum sample size stated', 'yes — nothing is shown below it'],
          ].map(([label, state]) => (
            <li key={label} className="flex justify-between gap-4">
              <span>{label}</span>
              <span className="tabular text-right" style={{ color: 'var(--muted)' }}>
                {state}
              </span>
            </li>
          ))}
        </ul>
        <p className="mt-4 text-sm leading-relaxed">
          Estimates produced so far: <strong>{candidates.length}</strong>. A probability displayed
          before these preconditions are met would be a fabricated number wearing the costume of a
          measurement.
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
