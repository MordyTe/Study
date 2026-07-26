import type { Metadata, Viewport } from 'next';
import './globals.css';
import { Nav } from '@/components/nav';

export const metadata: Metadata = {
  title: 'Bybit Pattern Scanner',
  description:
    'Analysis-only market pattern scanner for Bybit spot and USDT perpetuals. Live official V5 market data. Cannot execute trades.',
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  themeColor: '#05070d',
  width: 'device-width',
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">
        <div className="app-backdrop" aria-hidden />
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-[#0f1420] focus:px-4 focus:py-2 focus:text-sm focus:text-[#67e8f9]"
        >
          Skip to main content
        </a>
        <Nav />
        <main id="main" className="mx-auto w-full max-w-[1600px] px-4 pb-16 pt-4 sm:px-6 lg:px-8">
          {children}
        </main>
        <footer className="mx-auto w-full max-w-[1600px] px-4 pb-10 text-center sm:px-6 lg:px-8">
          <p className="text-[11px] leading-relaxed text-[#5c6883]">
            Analysis only — this system cannot execute trades. Data source: Bybit V5 public market API.
            Nothing here is financial advice, and no accuracy or profitability is guaranteed.
          </p>
        </footer>
      </body>
    </html>
  );
}
