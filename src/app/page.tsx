import Link from 'next/link';
import { Badge, Card, Empty, Stat } from '@/components/ui';
import { getStore } from '@/lib/store';

export const dynamic = 'force-dynamic';

function pct(value: number | null): string {
  return value === null ? '—' : `${(value * 100).toFixed(1)}%`;
}

export default async function CandidatesPage() {
  const store = await getStore();
  const [candidates, lastScan] = await Promise.all([store.listCandidates(50), store.lastScan()]);

  const actionable = candidates.filter((c) => c.status === 'ACTIONABLE');
  const watch = candidates.filter((c) => c.status === 'WATCH');
  const abstain = candidates.filter((c) => c.status === 'ABSTAIN');
  const abstentionRate = candidates.length > 0 ? abstain.length / candidates.length : null;

  return (
    <main className="space-y-6">
      <Card>
        <div className="grid grid-cols-2 gap-5 sm:grid-cols-4">
          <Stat label="Actionable" value={String(actionable.length)} detail="passed every gate" />
          <Stat label="Watch" value={String(watch.length)} detail="edge, but a gate failed" />
          <Stat label="Abstained" value={String(abstain.length)} detail="no number produced" />
          <Stat
            label="Abstention rate"
            value={abstentionRate === null ? '—' : pct(abstentionRate)}
            detail="high is correct"
          />
        </div>
        {lastScan ? (
          <p className="mt-5 text-xs" style={{ color: 'var(--muted)' }}>
            Last scan saw {lastScan.universeSize} markets, promoted {lastScan.promoted}, and stored
            results in the <strong>{lastScan.storeKind}</strong> store using the{' '}
            <strong>{lastScan.llmProviderKind}</strong> agent provider.
            {lastScan.errors.length > 0 ? ` ${lastScan.errors.length} note(s) recorded.` : ''}
          </p>
        ) : null}
      </Card>

      {candidates.length === 0 ? (
        <Empty
          title="No scan has run yet"
          body={
            <>
              <p>
                Trigger one with <code>POST /api/scan</code>, or run <code>npm run scan</code>{' '}
                locally.
              </p>
              <p className="mt-3">
                A scan needs outbound access to <code>gamma-api.polymarket.com</code> and{' '}
                <code>clob.polymarket.com</code> for market data, and an{' '}
                <code>ANTHROPIC_API_KEY</code> for the agent tier. Without the agent tier every
                market abstains, which is the honest result rather than a crash.
              </p>
            </>
          }
        />
      ) : (
        <div className="space-y-3">
          {candidates.map((candidate) => (
            <Link key={candidate.id} href={`/candidate/${candidate.id}`} className="block">
              <Card className="transition-opacity hover:opacity-80">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <h2 className="max-w-xl text-sm font-medium leading-snug">
                    {candidate.question}
                  </h2>
                  <Badge label={candidate.status} />
                </div>
                <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
                  <Stat label="Our estimate" value={pct(candidate.fairProbability)} />
                  <Stat label="Market ask" value={pct(candidate.marketPrice)} />
                  <Stat
                    label="Gross edge"
                    value={
                      candidate.grossEdge === null
                        ? '—'
                        : `${(candidate.grossEdge * 100).toFixed(2)}¢`
                    }
                    detail={
                      candidate.feeHurdle === null
                        ? undefined
                        : `fee ${(candidate.feeHurdle * 100).toFixed(2)}¢`
                    }
                  />
                  <Stat
                    label="Size"
                    value={
                      candidate.sizing ? `$${candidate.sizing.notional.toFixed(2)}` : '—'
                    }
                    detail={candidate.sizing?.limitedBy}
                  />
                </div>
                {candidate.abstentionReasons.length > 0 ? (
                  <p className="mt-4 text-xs leading-relaxed" style={{ color: 'var(--muted)' }}>
                    {candidate.abstentionReasons[0]}
                  </p>
                ) : null}
              </Card>
            </Link>
          ))}
        </div>
      )}
    </main>
  );
}
