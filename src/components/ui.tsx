import { clsx } from 'clsx';
import type { ReactNode } from 'react';

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={clsx('rounded-lg border p-5', className)}
      style={{ borderColor: 'var(--border)', background: 'var(--surface)' }}
    >
      {children}
    </div>
  );
}

const STATUS_COLOR: Record<string, string> = {
  ACTIONABLE: 'var(--ok)',
  WATCH: 'var(--warn)',
  ABSTAIN: 'var(--off)',
  HEALTHY: 'var(--ok)',
  DEGRADED: 'var(--warn)',
  STALE: 'var(--warn)',
  INSUFFICIENT: 'var(--off)',
};

export function Badge({ label }: { label: string }) {
  const color = STATUS_COLOR[label] ?? 'var(--muted)';
  return (
    <span
      className="inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium tracking-wide"
      style={{ color, borderColor: color }}
    >
      {label}
    </span>
  );
}

export function Stat({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail?: string;
}) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide" style={{ color: 'var(--muted)' }}>
        {label}
      </div>
      <div className="tabular mt-1 text-xl font-semibold">{value}</div>
      {detail ? (
        <div className="mt-0.5 text-xs" style={{ color: 'var(--muted)' }}>
          {detail}
        </div>
      ) : null}
    </div>
  );
}

export function Empty({ title, body }: { title: string; body: ReactNode }) {
  return (
    <Card>
      <h2 className="font-medium">{title}</h2>
      <div className="mt-2 text-sm leading-relaxed" style={{ color: 'var(--muted)' }}>
        {body}
      </div>
    </Card>
  );
}

export function ReasonList({ items, title }: { items: string[]; title: string }) {
  if (items.length === 0) return null;
  return (
    <div>
      <h3 className="text-xs uppercase tracking-wide" style={{ color: 'var(--muted)' }}>
        {title}
      </h3>
      <ul className="mt-2 space-y-1.5 text-sm leading-relaxed">
        {items.map((item, i) => (
          <li key={i} className="flex gap-2">
            <span style={{ color: 'var(--muted)' }}>{i + 1}.</span>
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
