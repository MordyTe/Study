import Link from 'next/link';
import { notFound } from 'next/navigation';
import { Badge, Card, ReasonList, Stat } from '@/components/ui';
import { getStore } from '@/lib/store';

export const dynamic = 'force-dynamic';

function pct(value: number | null): string {
  return value === null ? '—' : `${(value * 100).toFixed(2)}%`;
}

export default async function CandidatePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const store = await getStore();
  const candidate = await store.getCandidate(id);
  if (!candidate) notFound();

  return (
    <main className="space-y-6">
      <Link href="/" className="text-sm" style={{ color: 'var(--muted)' }}>
        ← All candidates
      </Link>

      <Card>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <h1 className="max-w-2xl text-base font-medium leading-snug">{candidate.question}</h1>
          <Badge label={candidate.status} />
        </div>
        <div className="mt-5 grid grid-cols-2 gap-5 sm:grid-cols-4">
          <Stat label="Our estimate" value={pct(candidate.fairProbability)} />
          <Stat label="Market ask" value={pct(candidate.marketPrice)} />
          <Stat
            label="Gross edge"
            value={
              candidate.grossEdge === null ? '—' : `${(candidate.grossEdge * 100).toFixed(2)}¢`
            }
          />
          <Stat
            label="Fee hurdle"
            value={candidate.feeHurdle === null ? '—' : `${(candidate.feeHurdle * 100).toFixed(2)}¢`}
            detail="per share"
          />
        </div>
      </Card>

      {candidate.abstentionReasons.length > 0 ? (
        <Card>
          <ReasonList title="Why this abstained" items={candidate.abstentionReasons} />
        </Card>
      ) : null}

      {candidate.reasoning.length > 0 ? (
        <Card>
          <ReasonList title="How the number was reached" items={candidate.reasoning} />
        </Card>
      ) : null}

      {candidate.curve.length > 0 ? (
        <Card>
          <h3 className="text-xs uppercase tracking-wide" style={{ color: 'var(--muted)' }}>
            Size curve — where the edge actually stops
          </h3>
          <div className="mt-3 overflow-x-auto">
            <table className="tabular w-full min-w-md text-sm">
              <thead>
                <tr style={{ color: 'var(--muted)' }} className="text-left text-xs">
                  <th className="pb-2 pr-4 font-normal">Notional</th>
                  <th className="pb-2 pr-4 font-normal">Shares</th>
                  <th className="pb-2 pr-4 font-normal">Avg price</th>
                  <th className="pb-2 pr-4 font-normal">Fees</th>
                  <th className="pb-2 pr-4 font-normal">Expected value</th>
                  <th className="pb-2 font-normal">Return</th>
                </tr>
              </thead>
              <tbody>
                {candidate.curve.map((point, i) => (
                  <tr key={i} className="border-t" style={{ borderColor: 'var(--border)' }}>
                    <td className="py-1.5 pr-4">${point.notional.toFixed(2)}</td>
                    <td className="py-1.5 pr-4">{point.fill.shares.toFixed(1)}</td>
                    <td className="py-1.5 pr-4">{point.fill.avgPrice.toFixed(4)}</td>
                    <td className="py-1.5 pr-4">${point.feesPaid.toFixed(3)}</td>
                    <td
                      className="py-1.5 pr-4"
                      style={{ color: point.expectedValue >= 0 ? 'var(--ok)' : 'var(--warn)' }}
                    >
                      ${point.expectedValue.toFixed(3)}
                    </td>
                    <td className="py-1.5">{(point.expectedReturn * 100).toFixed(2)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : null}

      <Card>
        <h3 className="text-xs uppercase tracking-wide" style={{ color: 'var(--muted)' }}>
          Verification — {candidate.verification.health}
        </h3>
        <ul className="mt-3 space-y-2 text-sm">
          {candidate.verification.checks.map((check) => (
            <li key={check.name} className="flex gap-3">
              <span style={{ color: check.passed ? 'var(--ok)' : 'var(--warn)' }}>
                {check.passed ? '✓' : '✕'}
              </span>
              <span>
                <span className="font-medium">{check.name}</span>
                <span style={{ color: 'var(--muted)' }}> — {check.detail}</span>
              </span>
            </li>
          ))}
        </ul>
      </Card>

      {candidate.residuals ? (
        <Card>
          <h3 className="text-xs uppercase tracking-wide" style={{ color: 'var(--muted)' }}>
            Residual distribution
          </h3>
          <div className="mt-3 grid grid-cols-2 gap-5 sm:grid-cols-4">
            <Stat label="Sample" value={String(candidate.residuals.n)} detail="past releases" />
            <Stat label="Std dev" value={candidate.residuals.sd.toFixed(4)} />
            <Stat label="IQR" value={candidate.residuals.iqr.toFixed(4)} />
            <Stat
              label="Bias"
              value={candidate.residuals.bias.toFixed(4)}
              detail={candidate.residuals.biasCorrected ? 'removed' : 'observed, not removed'}
            />
          </div>
        </Card>
      ) : null}

      <Card>
        <ReasonList title="Assumptions shipped with this result" items={candidate.assumptions} />
        <p className="mt-4 text-xs" style={{ color: 'var(--muted)' }}>
          Fingerprint <code>{candidate.fingerprint}</code>
        </p>
      </Card>
    </main>
  );
}
