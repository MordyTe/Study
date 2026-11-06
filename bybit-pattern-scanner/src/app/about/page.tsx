import { Panel, SectionTitle } from '@/components/ui';

export const metadata = { title: 'About & Methodology · Bybit Pattern Scanner' };

const SOURCES = [
  ['Integration guide', 'https://bybit-exchange.github.io/docs/v5/guide'],
  ['Instruments', 'https://bybit-exchange.github.io/docs/v5/market/instrument'],
  ['Server time', 'https://bybit-exchange.github.io/docs/v5/market/time'],
  ['Tickers', 'https://bybit-exchange.github.io/docs/v5/market/tickers'],
  ['Historical klines', 'https://bybit-exchange.github.io/docs/v5/market/kline'],
  ['Open interest', 'https://bybit-exchange.github.io/docs/v5/market/open-interest'],
  ['Funding history', 'https://bybit-exchange.github.io/docs/v5/market/history-fund-rate'],
  ['Rate limits', 'https://bybit-exchange.github.io/docs/v5/rate-limit'],
];

export default function AboutPage() {
  return (
    <div className="space-y-5 pt-2">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-[#f2f5fb]">About & Methodology</h1>
        <p className="mt-1 text-xs text-[#5c6883]">What this system does, what it deliberately does not do, and why</p>
      </div>

      <Panel className="border-[#10b981]/25 p-5">
        <h2 className="text-sm font-semibold text-[#34d399]">Analysis only — this system cannot execute trades</h2>
        <p className="mt-2 text-xs leading-relaxed text-[#a8b3cc]">
          This is a hard architectural boundary, not a setting. The codebase contains no order-creation, amendment,
          cancellation, position-management, leverage, transfer, or withdrawal code. No Bybit API key is required or
          accepted — a startup guard fails the boot if one is present. Every outbound exchange request is checked
          against an explicit allowlist of public GET market-data endpoints before a socket is opened, and a test in
          the suite fails the build if a forbidden path ever appears in the source.
        </p>
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel className="p-5">
          <SectionTitle title="What it does" />
          <ul className="space-y-2.5 text-xs leading-relaxed text-[#a8b3cc]">
            <li>• Discovers every eligible active USDT instrument on Bybit spot and linear perpetuals.</li>
            <li>• Ranks the full universe by liquidity, volatility, range position and funding pressure.</li>
            <li>• Runs twelve deterministic pattern detectors on closed candles across multiple timeframes.</li>
            <li>• Verifies the underlying data against Bybit before any setup is labelled confirmed.</li>
            <li>• Scores each setup 0–100 with a fully attributable component breakdown.</li>
            <li>• Tracks each scenario forward: entry-zone touch, invalidation, targets, expiry.</li>
            <li>• Sends Telegram notifications for confirmed setups and lifecycle changes.</li>
          </ul>
        </Panel>

        <Panel className="p-5">
          <SectionTitle title="What it does not do" />
          <ul className="space-y-2.5 text-xs leading-relaxed text-[#a8b3cc]">
            <li>• It does not place, approve, modify, or close any trade — ever.</li>
            <li>• It does not connect to your exchange account or hold your credentials.</li>
            <li>• It does not predict prices or claim any win rate, accuracy, or profitability.</li>
            <li>• It does not give financial advice.</li>
            <li>• It does not display a probability, because no calibrated probability model has been validated.</li>
          </ul>
        </Panel>
      </div>

      <Panel className="p-5">
        <SectionTitle title="Setup Quality is not a win probability" />
        <p className="text-xs leading-relaxed text-[#a8b3cc]">
          The 0–100 score measures how well-formed and well-supported a setup is against explicit criteria: pattern
          geometry and fit (25), confirmation quality (20), structure and regime alignment (15), volume and momentum
          (15), multi-timeframe alignment (10), liquidity and spread (10), and data verification (5). Penalties are
          then subtracted for poor asymmetry, thin turnover, wide spread, very new listings, incomplete history, a
          blocking level in the path, crowded funding, and staleness.
        </p>
        <p className="mt-3 text-xs leading-relaxed text-[#a8b3cc]">
          A high score means the setup is textbook-clean, not that it will work. Converting a quality score into a
          probability requires a separately validated calibration model built on a large sample of resolved outcomes,
          evaluated out-of-sample with a reported Brier score and reliability curve. Until that exists, presenting a
          percentage would be dishonest — so this system does not.
        </p>
      </Panel>

      <Panel className="p-5">
        <SectionTitle title="Official data sources" subtitle="Bybit V5 public market API is the sole exchange source of truth" />
        <ul className="grid gap-1.5 text-[11px] sm:grid-cols-2">
          {SOURCES.map(([label, url]) => (
            <li key={url}>
              <a
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[#67e8f9] hover:underline"
              >
                {label} ↗
              </a>
            </li>
          ))}
        </ul>
      </Panel>

      <Panel className="border-[#f59e0b]/20 p-5">
        <SectionTitle title="Risk disclosure" />
        <p className="text-xs leading-relaxed text-[#fbbf24]">
          Cryptocurrency trading involves substantial risk of loss and is not suitable for everyone. Leveraged
          perpetual futures can lose more than the initial margin. Nothing in this application is financial advice, a
          recommendation, or a solicitation. Backtest figures are simulated signal outcomes, not executed trades, and
          past behaviour does not predict future results. You alone are responsible for every decision you make with
          your own capital.
        </p>
      </Panel>
    </div>
  );
}
