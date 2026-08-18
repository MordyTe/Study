import type { Metadata } from 'next';
import Link from 'next/link';
import './globals.css';

export const metadata: Metadata = {
  title: 'Scheduled-Data Edge',
  description:
    'Research-only agent network that estimates probabilities for scheduled-data prediction markets from public sources and historical forecast error.',
};

const NAV = [
  { href: '/', label: 'Candidates' },
  { href: '/method', label: 'Method' },
  { href: '/health', label: 'Health' },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="mx-auto max-w-5xl px-5 py-8">
          <header className="mb-8 border-b pb-5" style={{ borderColor: 'var(--border)' }}>
            <div className="flex flex-wrap items-baseline justify-between gap-3">
              <Link href="/" className="text-lg font-semibold tracking-tight">
                Scheduled-Data Edge
              </Link>
              <nav className="flex gap-5 text-sm">
                {NAV.map((item) => (
                  <Link
                    key={item.href}
                    href={item.href}
                    className="transition-opacity hover:opacity-70"
                    style={{ color: 'var(--muted)' }}
                  >
                    {item.label}
                  </Link>
                ))}
              </nav>
            </div>
            <p className="mt-2 text-sm" style={{ color: 'var(--muted)' }}>
              Research only. Estimates probabilities and measures its own calibration.{' '}
              <strong style={{ color: 'var(--text)' }}>It cannot place an order.</strong>
            </p>
          </header>
          {children}
          <footer
            className="mt-12 border-t pt-5 text-xs"
            style={{ borderColor: 'var(--border)', color: 'var(--muted)' }}
          >
            Nothing here is financial advice. Probabilities are uncalibrated until the reliability
            curve on the Health page says otherwise.
          </footer>
        </div>
      </body>
    </html>
  );
}
