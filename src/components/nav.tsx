'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
import { clsx } from 'clsx';

const LINKS = [
  { href: '/', label: 'Command Center' },
  { href: '/scanner', label: 'Live Scanner' },
  { href: '/opportunities', label: 'Opportunities' },
  { href: '/patterns', label: 'Patterns' },
  { href: '/backtest', label: 'Backtest' },
  { href: '/alerts', label: 'Alerts' },
  { href: '/health', label: 'Health' },
  { href: '/settings', label: 'Settings' },
  { href: '/about', label: 'About' },
];

export function Nav() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [scanner, setScanner] = useState<'online' | 'offline' | 'checking'>('checking');

  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        const res = await fetch('/api/health', { cache: 'no-store' });
        const body = await res.json();
        if (!cancelled) setScanner(body?.overall === 'DISCONNECTED' ? 'offline' : 'online');
      } catch {
        if (!cancelled) setScanner('offline');
      }
    };
    void check();
    const timer = setInterval(check, 60_000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  useEffect(() => setOpen(false), [pathname]);

  return (
    <header className="sticky top-0 z-40 border-b border-white/[0.06] bg-[#05070d]/85 backdrop-blur-xl">
      <div className="mx-auto flex w-full max-w-[1600px] items-center gap-4 px-4 py-3 sm:px-6 lg:px-8">
        <Link href="/" className="flex shrink-0 items-center gap-2.5">
          <span
            aria-hidden
            className="grid h-8 w-8 place-items-center rounded-lg border border-[#22d3ee]/30 bg-[#22d3ee]/10 text-sm text-[#67e8f9]"
          >
            ◈
          </span>
          <span className="hidden text-sm font-semibold tracking-tight text-[#f2f5fb] sm:block">
            Bybit Pattern Scanner
          </span>
        </Link>

        <nav className="hidden flex-1 items-center gap-0.5 lg:flex" aria-label="Primary">
          {LINKS.map((link) => {
            const active = pathname === link.href || (link.href !== '/' && pathname.startsWith(link.href));
            return (
              <Link
                key={link.href}
                href={link.href}
                aria-current={active ? 'page' : undefined}
                className={clsx(
                  'rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors',
                  active ? 'bg-white/[0.07] text-[#f2f5fb]' : 'text-[#7d8aa8] hover:bg-white/[0.04] hover:text-[#d6dcea]',
                )}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>

        <div className="ml-auto flex items-center gap-3">
          <span
            className="hidden items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.1em] sm:inline-flex"
            title="Analysis only — this system cannot execute trades."
          >
            <span aria-hidden className="text-[#34d399]">
              ⛨
            </span>
            <span className="text-[#7d8aa8]">Analysis only</span>
          </span>

          <span className="inline-flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.1em]">
            <span
              aria-hidden
              className={clsx(
                scanner === 'online' && 'pulse-dot text-[#34d399]',
                scanner === 'offline' && 'text-[#fb7185]',
                scanner === 'checking' && 'text-[#7d8aa8]',
              )}
            >
              ●
            </span>
            <span
              className={clsx(
                scanner === 'online' && 'text-[#34d399]',
                scanner === 'offline' && 'text-[#fb7185]',
                scanner === 'checking' && 'text-[#7d8aa8]',
              )}
            >
              {scanner === 'online' ? 'Live' : scanner === 'offline' ? 'Offline' : '…'}
            </span>
          </span>

          <button
            type="button"
            className="rounded-lg border border-white/10 px-2.5 py-1.5 text-xs text-[#a8b3cc] lg:hidden"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            aria-label="Toggle navigation menu"
          >
            {open ? '✕' : '☰'}
          </button>
        </div>
      </div>

      {open ? (
        <nav className="border-t border-white/[0.06] px-4 pb-3 lg:hidden" aria-label="Mobile">
          <div className="grid grid-cols-2 gap-1 pt-2 sm:grid-cols-3">
            {LINKS.map((link) => {
              const active = pathname === link.href || (link.href !== '/' && pathname.startsWith(link.href));
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  className={clsx(
                    'rounded-lg px-3 py-2.5 text-xs font-medium',
                    active ? 'bg-white/[0.07] text-[#f2f5fb]' : 'text-[#7d8aa8]',
                  )}
                >
                  {link.label}
                </Link>
              );
            })}
          </div>
        </nav>
      ) : null}
    </header>
  );
}
