'use client';

import { useState } from 'react';
import { usePolling } from '@/lib/hooks';
import { Button, Chip, ErrorState, Panel, SectionTitle, Skeleton, formatTime } from '@/components/ui';

interface Delivery {
  id: string;
  opportunityId: string;
  channel: string;
  status: 'sent' | 'failed' | 'skipped';
  detail: string;
  at: number;
}

interface AlertsResponse {
  ok: boolean;
  telegramConfigured: boolean;
  deliveries: Delivery[];
  scans: {
    id: string;
    finishedAt: number;
    confirmed: number;
    forming: number;
    alertsSent: number;
    durationMs: number;
    instrumentsScanned: number;
    errors: string[];
  }[];
}

export default function AlertsPage() {
  const { data, error, loading, refresh } = usePolling<AlertsResponse>('/api/alerts', 30_000);
  const [testMsg, setTestMsg] = useState<string | null>(null);

  const test = async () => {
    setTestMsg('Sending…');
    try {
      const res = await fetch('/api/telegram/test', { method: 'POST' });
      const body = await res.json();
      setTestMsg(body.ok ? '✓ Delivered — check Telegram.' : `✕ ${body.error ?? body.detail}`);
      refresh();
    } catch (err) {
      setTestMsg(`✕ ${(err as Error).message}`);
    }
  };

  return (
    <div className="space-y-5 pt-2">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-[#f2f5fb]">Alert Center</h1>
          <p className="mt-1 text-xs text-[#5c6883]">Telegram delivery state, history and scan activity</p>
        </div>
        <div className="flex items-center gap-3">
          <Button variant="ghost" onClick={test}>
            Send test message
          </Button>
          <Button variant="ghost" onClick={refresh}>
            ⟳ Refresh
          </Button>
        </div>
      </div>

      {testMsg ? (
        <Panel className="px-4 py-3">
          <p className="text-xs text-[#a8b3cc]">{testMsg}</p>
        </Panel>
      ) : null}

      {error ? (
        <Panel>
          <ErrorState message={error} onRetry={refresh} />
        </Panel>
      ) : null}

      <Panel className="p-4">
        <SectionTitle title="Telegram destination" />
        <div className="flex items-center gap-3">
          <Chip tone={data?.telegramConfigured ? 'bull' : 'warn'}>
            {data?.telegramConfigured ? 'Connected' : 'Not configured'}
          </Chip>
          <span className="text-[11px] text-[#7d8aa8]">
            {data?.telegramConfigured
              ? 'Confirmed opportunities are delivered to your configured chat.'
              : 'Add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in Vercel → Settings → Environment Variables, then redeploy.'}
          </span>
        </div>
      </Panel>

      <Panel className="overflow-hidden">
        <div className="p-4 pb-0">
          <SectionTitle title="Delivery history" subtitle="Every send attempt, with its idempotency outcome" />
        </div>
        {loading && !data ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-10" />
            ))}
          </div>
        ) : (data?.deliveries ?? []).length === 0 ? (
          <p className="px-4 pb-6 pt-2 text-center text-xs text-[#5c6883]">
            No deliveries yet. Alerts are sent when a scan produces a CONFIRMED opportunity and Telegram is configured.
          </p>
        ) : (
          <div className="scroll-x">
            <table className="w-full min-w-[620px] text-left text-xs">
              <thead>
                <tr className="border-b border-white/[0.06] text-[10px] uppercase tracking-wider text-[#5c6883]">
                  <th className="px-4 py-2.5 font-medium">Time</th>
                  <th className="px-4 py-2.5 font-medium">Opportunity</th>
                  <th className="px-4 py-2.5 font-medium">Status</th>
                  <th className="px-4 py-2.5 font-medium">Detail</th>
                </tr>
              </thead>
              <tbody>
                {(data?.deliveries ?? []).map((d) => (
                  <tr key={d.id} className="border-b border-white/[0.03]">
                    <td className="mono px-4 py-2.5 text-[#7d8aa8]">{formatTime(d.at)}</td>
                    <td className="mono px-4 py-2.5 text-[#d6dcea]">{d.opportunityId}</td>
                    <td className="px-4 py-2.5">
                      <Chip tone={d.status === 'sent' ? 'bull' : d.status === 'failed' ? 'bear' : 'muted'}>
                        {d.status}
                      </Chip>
                    </td>
                    <td className="px-4 py-2.5 text-[11px] text-[#7d8aa8]">{d.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel className="overflow-hidden">
        <div className="p-4 pb-0">
          <SectionTitle title="Scan history" subtitle="Engine heartbeat — proof the scanner is actually running" />
        </div>
        {(data?.scans ?? []).length === 0 ? (
          <p className="px-4 pb-6 pt-2 text-center text-xs text-[#5c6883]">
            No scans recorded yet. Run one from the Command Center, or wait for the scheduled cron cycle.
          </p>
        ) : (
          <div className="scroll-x">
            <table className="w-full min-w-[680px] text-left text-xs">
              <thead>
                <tr className="border-b border-white/[0.06] text-[10px] uppercase tracking-wider text-[#5c6883]">
                  <th className="px-4 py-2.5 font-medium">Finished</th>
                  <th className="px-4 py-2.5 text-right font-medium">Instruments</th>
                  <th className="px-4 py-2.5 text-right font-medium">Confirmed</th>
                  <th className="px-4 py-2.5 text-right font-medium">Forming</th>
                  <th className="px-4 py-2.5 text-right font-medium">Alerts</th>
                  <th className="px-4 py-2.5 text-right font-medium">Duration</th>
                  <th className="px-4 py-2.5 text-right font-medium">Issues</th>
                </tr>
              </thead>
              <tbody>
                {(data?.scans ?? []).map((s) => (
                  <tr key={s.id} className="border-b border-white/[0.03]">
                    <td className="mono px-4 py-2.5 text-[#7d8aa8]">{formatTime(s.finishedAt)}</td>
                    <td className="mono px-4 py-2.5 text-right text-[#a8b3cc]">{s.instrumentsScanned}</td>
                    <td className="mono px-4 py-2.5 text-right text-[#34d399]">{s.confirmed}</td>
                    <td className="mono px-4 py-2.5 text-right text-[#fbbf24]">{s.forming}</td>
                    <td className="mono px-4 py-2.5 text-right text-[#67e8f9]">{s.alertsSent}</td>
                    <td className="mono px-4 py-2.5 text-right text-[#a8b3cc]">
                      {(s.durationMs / 1000).toFixed(1)}s
                    </td>
                    <td className="mono px-4 py-2.5 text-right text-[#5c6883]">{s.errors.length}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
