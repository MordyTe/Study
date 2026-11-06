'use client';

import { clsx } from 'clsx';
import type { ReactNode } from 'react';

export function Panel({
  children,
  className,
  hover = false,
}: {
  children: ReactNode;
  className?: string;
  hover?: boolean;
}) {
  return <div className={clsx('panel', hover && 'panel-hover', className)}>{children}</div>;
}

export function SectionTitle({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h2 className="text-sm font-semibold uppercase tracking-[0.14em] text-[#a8b3cc]">{title}</h2>
        {subtitle ? <p className="mt-1 text-xs text-[#5c6883]">{subtitle}</p> : null}
      </div>
      {action}
    </div>
  );
}

export type ChipTone = 'bull' | 'bear' | 'warn' | 'info' | 'muted';

export function Chip({ tone = 'muted', children }: { tone?: ChipTone; children: ReactNode }) {
  return <span className={clsx('chip', `chip-${tone}`)}>{children}</span>;
}

export function StatusChip({ status }: { status: string }) {
  const tone: ChipTone =
    status === 'CONFIRMED'
      ? 'bull'
      : status === 'INVALIDATED'
        ? 'bear'
        : status === 'FORMING'
          ? 'warn'
          : status.startsWith('TARGET')
            ? 'info'
            : 'muted';
  return <Chip tone={tone}>{status.replace(/_/g, ' ')}</Chip>;
}

/** Health indicator that never relies on colour alone. */
export function HealthDot({ state }: { state: string }) {
  const map: Record<string, { color: string; label: string; symbol: string }> = {
    HEALTHY: { color: '#10b981', label: 'Healthy', symbol: '●' },
    DEGRADED: { color: '#f59e0b', label: 'Degraded', symbol: '◐' },
    STALE: { color: '#f59e0b', label: 'Stale', symbol: '◑' },
    DISCONNECTED: { color: '#f43f5e', label: 'Disconnected', symbol: '✕' },
    RECOVERING: { color: '#22d3ee', label: 'Recovering', symbol: '↻' },
  };
  const item = map[state] ?? map.DEGRADED!;
  return (
    <span className="inline-flex items-center gap-2 text-xs font-medium" style={{ color: item.color }}>
      <span aria-hidden className={state === 'HEALTHY' ? 'pulse-dot' : ''}>
        {item.symbol}
      </span>
      <span>{item.label}</span>
    </span>
  );
}

export function Kpi({
  label,
  value,
  hint,
  tone = 'default',
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  tone?: 'default' | 'bull' | 'bear' | 'warn' | 'accent';
}) {
  const colors: Record<string, string> = {
    default: '#f2f5fb',
    bull: '#34d399',
    bear: '#fb7185',
    warn: '#fbbf24',
    accent: '#67e8f9',
  };
  return (
    <Panel className="p-4">
      <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[#5c6883]">{label}</div>
      <div className="mono mt-2 text-2xl font-semibold leading-none" style={{ color: colors[tone] }}>
        {value}
      </div>
      {hint ? <div className="mt-2 text-[11px] leading-relaxed text-[#5c6883]">{hint}</div> : null}
    </Panel>
  );
}

export function ScoreRing({ score, size = 56 }: { score: number; size?: number }) {
  const clamped = Math.max(0, Math.min(100, score));
  const radius = (size - 6) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - clamped / 100);
  const color = clamped >= 85 ? '#10b981' : clamped >= 75 ? '#22d3ee' : clamped >= 65 ? '#f59e0b' : '#7d8aa8';

  return (
    <div
      className="relative shrink-0"
      style={{ width: size, height: size }}
      role="img"
      aria-label={`Setup quality score ${clamped} out of 100`}
    >
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="rgba(148,163,184,0.16)" strokeWidth={4} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={4}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">
        <span className="mono text-sm font-bold" style={{ color }}>
          {Math.round(clamped)}
        </span>
      </div>
    </div>
  );
}

export function Button({
  children,
  onClick,
  variant = 'primary',
  disabled,
  type = 'button',
  className,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: 'primary' | 'ghost' | 'danger';
  disabled?: boolean;
  type?: 'button' | 'submit';
  className?: string;
}) {
  const styles: Record<string, string> = {
    primary:
      'bg-[#22d3ee]/12 text-[#67e8f9] border-[#22d3ee]/35 hover:bg-[#22d3ee]/20 hover:border-[#22d3ee]/60',
    ghost: 'bg-white/[0.03] text-[#a8b3cc] border-white/10 hover:bg-white/[0.07] hover:text-[#f2f5fb]',
    danger: 'bg-[#f43f5e]/12 text-[#fb7185] border-[#f43f5e]/35 hover:bg-[#f43f5e]/20',
  };
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={clsx(
        'inline-flex items-center justify-center gap-2 rounded-lg border px-3.5 py-2 text-xs font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-45',
        styles[variant],
        className,
      )}
    >
      {children}
    </button>
  );
}

export function EmptyState({ title, detail, action }: { title: string; detail: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <div className="mb-3 text-2xl opacity-40" aria-hidden>
        ◎
      </div>
      <h3 className="text-sm font-semibold text-[#d6dcea]">{title}</h3>
      <p className="mt-2 max-w-md text-xs leading-relaxed text-[#5c6883]">{detail}</p>
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
      <div className="mb-3 text-2xl text-[#fb7185]" aria-hidden>
        ⚠
      </div>
      <h3 className="text-sm font-semibold text-[#fb7185]">Could not load live data</h3>
      <p className="mono mt-2 max-w-lg break-words text-[11px] leading-relaxed text-[#7d8aa8]">{message}</p>
      {onRetry ? (
        <div className="mt-4">
          <Button onClick={onRetry}>Retry</Button>
        </div>
      ) : null}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx('skeleton', className)} aria-hidden />;
}

export function DataSourceBadge({ fetchedAt, source = 'Bybit V5 Official' }: { fetchedAt?: number; source?: string }) {
  const age = fetchedAt ? Math.max(0, Math.round((Date.now() - fetchedAt) / 1000)) : null;
  return (
    <span className="inline-flex items-center gap-2 text-[10px] text-[#5c6883]">
      <span className="text-[#34d399]" aria-hidden>
        ●
      </span>
      <span className="uppercase tracking-[0.12em]">{source}</span>
      {age !== null ? <span className="mono">· {age}s ago</span> : null}
    </span>
  );
}

export function formatPrice(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  const abs = Math.abs(value);
  if (abs >= 10_000) return value.toLocaleString('en-US', { maximumFractionDigits: 1 });
  if (abs >= 100) return value.toFixed(2);
  if (abs >= 1) return value.toFixed(4);
  if (abs >= 0.0001) return value.toFixed(6);
  return value.toExponential(3);
}

export function formatCompact(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  if (Math.abs(value) >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(2)}B`;
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (Math.abs(value) >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return value.toFixed(0);
}

export function formatPct(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return `${value > 0 ? '+' : ''}${value.toFixed(digits)}%`;
}

export function formatTime(ts: number | null | undefined, timeZone = 'Asia/Jerusalem'): string {
  if (!ts) return '—';
  try {
    return new Intl.DateTimeFormat('en-GB', {
      dateStyle: 'short',
      timeStyle: 'medium',
      timeZone,
    }).format(new Date(ts));
  } catch {
    return new Date(ts).toISOString();
  }
}
