import { Card } from '@/components/ui';
import { listAgentMeta } from '@/lib/agents/registry';
import { FEE_COEFFICIENTS } from '@/lib/estimate/fees';
import { MIN_RESIDUALS } from '@/lib/estimate/residuals';
import { MODEL_RISK_FLOOR } from '@/lib/estimate/threshold';

export const dynamic = 'force-dynamic';

export default function MethodPage() {
  const agents = listAgentMeta();

  return (
    <main className="space-y-6">
      <Card>
        <h1 className="text-base font-medium">What this system does, and what it does not</h1>
        <div className="mt-3 space-y-3 text-sm leading-relaxed" style={{ color: 'var(--muted)' }}>
          <p>
            It watches prediction markets whose outcome is decided by a{' '}
            <strong style={{ color: 'var(--text)' }}>scheduled public data release</strong> — an
            inflation print, a jobs report, a rate decision, a temperature reading. For each one it
            estimates the probability of the stated threshold, compares that to the market price,
            and records the result so its own calibration can be measured later.
          </p>
          <p>
            It holds no credentials and has no order path. A test walks the entire source tree on
            every commit to prove that, and it is not a formality — it is the property that makes
            the rest of this safe to run unattended.
          </p>
        </div>
      </Card>

      <Card>
        <h2 className="text-sm font-medium">The line that makes this defensible</h2>
        <p className="mt-3 text-sm leading-relaxed">
          The agents never produce a probability. Their job is to{' '}
          <strong>locate and parse sources</strong>. The probability is arithmetic over a
          distribution of historical forecast error.
        </p>
        <ol className="mt-4 space-y-2 text-sm leading-relaxed" style={{ color: 'var(--muted)' }}>
          <li>
            <strong style={{ color: 'var(--text)' }}>1.</strong> Agents extract the resolution rule
            and gather a point estimate from public nowcasts.
          </li>
          <li>
            <strong style={{ color: 'var(--text)' }}>2.</strong> A deterministic module builds the
            empirical distribution of how wrong that kind of estimate has been at a comparable
            horizon, using a kernel-smoothed CDF rather than a fitted normal — economic surprises
            have fat tails, and a Gaussian understates exactly the outcomes that decide a threshold.
          </li>
          <li>
            <strong style={{ color: 'var(--text)' }}>3.</strong> The threshold is converted from the{' '}
            <em>published, rounded</em> figure to the underlying value. Whether &ldquo;above
            3.0%&rdquo; resolves on ≥ 3.0 or ≥ 3.05 is half a reporting step, and at these prices
            that is the whole edge.
          </li>
        </ol>
      </Card>

      <Card>
        <h2 className="text-sm font-medium">Where it refuses to answer</h2>
        <ul className="mt-3 space-y-2 text-sm leading-relaxed" style={{ color: 'var(--muted)' }}>
          <li>• The resolution criteria carry any unresolved ambiguity.</li>
          <li>
            • Fewer than {MIN_RESIDUALS} comparable historical forecast errors exist — below that the
            tail behaviour is unstable, and an unstable tail is what produces a confident wrong
            answer on exactly the markets that look most mispriced.
          </li>
          <li>• No point estimate was gathered, or the one found is stale.</li>
          <li>• The book is too thin to take the position at any meaningful size.</li>
          <li>
            • No probability is ever reported outside{' '}
            <span className="tabular">
              [{MODEL_RISK_FLOOR}, {1 - MODEL_RISK_FLOOR}]
            </span>
            . The chance that the whole model is wrong — misparsed criteria, wrong series, a
            methodology change — exceeds anything more extreme.
          </li>
        </ul>
        <p className="mt-4 text-sm leading-relaxed">
          A high abstention rate is correct behaviour, not a failure.
        </p>
      </Card>

      <Card>
        <h2 className="text-sm font-medium">Fees are why most apparent edge is not edge</h2>
        <p className="mt-3 text-sm leading-relaxed" style={{ color: 'var(--muted)' }}>
          The venue charges takers <code>shares × coefficient × p × (1 − p)</code>. That term peaks
          at p = 0.50, so the fee is largest exactly where prediction markets are busiest. Every
          number on this site is net of it, and every candidate reports the size at which its edge
          stops existing.
        </p>
        <div className="mt-4 overflow-x-auto">
          <table className="tabular w-full min-w-sm text-sm">
            <thead>
              <tr style={{ color: 'var(--muted)' }} className="text-left text-xs">
                <th className="pb-2 pr-6 font-normal">Category</th>
                <th className="pb-2 pr-6 font-normal">Coefficient</th>
                <th className="pb-2 font-normal">Fee per share at p = 0.50</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(FEE_COEFFICIENTS).map(([category, coefficient]) => (
                <tr key={category} className="border-t" style={{ borderColor: 'var(--border)' }}>
                  <td className="py-1.5 pr-6">{category}</td>
                  <td className="py-1.5 pr-6">{coefficient.toFixed(2)}</td>
                  <td className="py-1.5">{(coefficient * 0.25 * 100).toFixed(2)}¢</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card>
        <h2 className="text-sm font-medium">The agent network</h2>
        <ul className="mt-3 space-y-3 text-sm">
          {agents.map((agent) => (
            <li key={agent.name}>
              <div className="font-medium">
                {agent.displayName}{' '}
                <span className="tabular text-xs" style={{ color: 'var(--muted)' }}>
                  {agent.name}@{agent.version}
                </span>
              </div>
              <div className="mt-0.5 leading-relaxed" style={{ color: 'var(--muted)' }}>
                {agent.description}
              </div>
            </li>
          ))}
        </ul>
      </Card>
    </main>
  );
}
