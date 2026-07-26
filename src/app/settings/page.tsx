'use client';

import { useEffect, useState } from 'react';
import { usePolling } from '@/lib/hooks';
import type { Settings } from '@/lib/config/settings';
import { TIMEFRAMES } from '@/lib/bybit/types';
import { Button, Chip, ErrorState, Panel, SectionTitle, Skeleton } from '@/components/ui';

interface SettingsResponse {
  ok: boolean;
  settings: Settings;
  defaults: Settings;
  integrations: {
    storeKind: string;
    supabaseConfigured: boolean;
    telegramConfigured: boolean;
    cronSecretSet: boolean;
    adminPasswordSet: boolean;
    aiExplanationsEnabled: boolean;
    appUrl: string | null;
  };
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="block text-xs font-medium text-[#d6dcea]">{label}</span>
      {hint ? <span className="mt-0.5 block text-[11px] leading-relaxed text-[#5c6883]">{hint}</span> : null}
      <div className="mt-2">{children}</div>
    </label>
  );
}

const inputClass =
  'mono w-full rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-[#f2f5fb] focus:border-[#22d3ee]/50 focus:outline-none';

function IntegrationRow({
  name,
  ok,
  detail,
  instructions,
}: {
  name: string;
  ok: boolean;
  detail: string;
  instructions?: string;
}) {
  return (
    <div className="border-b border-white/[0.05] py-3 last:border-0">
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs font-medium text-[#d6dcea]">{name}</span>
        <Chip tone={ok ? 'bull' : 'warn'}>{ok ? 'Connected' : 'Not configured'}</Chip>
      </div>
      <p className="mt-1.5 text-[11px] leading-relaxed text-[#7d8aa8]">{detail}</p>
      {!ok && instructions ? (
        <p className="mono mt-1.5 rounded-md bg-white/[0.03] px-2.5 py-2 text-[10px] leading-relaxed text-[#5c6883]">
          {instructions}
        </p>
      ) : null}
    </div>
  );
}

export default function SettingsPage() {
  const { data, error, loading, refresh } = usePolling<SettingsResponse>('/api/settings', 0);
  const [draft, setDraft] = useState<Settings | null>(null);
  const [password, setPassword] = useState('');
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [telegramMsg, setTelegramMsg] = useState<string | null>(null);

  useEffect(() => {
    if (data?.settings && !draft) setDraft(data.settings);
  }, [data, draft]);

  const update = <K extends keyof Settings>(key: K, value: Settings[K]) => {
    setDraft((d) => (d ? { ...d, [key]: value } : d));
  };

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    setMessage(null);
    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ settings: draft, password }),
      });
      const body = await res.json();
      setMessage(body.ok ? 'Settings saved. They take effect on the next scan.' : `Save failed: ${body.error}`);
      if (body.ok) refresh();
    } catch (err) {
      setMessage(`Save failed: ${(err as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  const testTelegram = async () => {
    setTelegramMsg('Sending…');
    try {
      const res = await fetch('/api/telegram/test', { method: 'POST' });
      const body = await res.json();
      setTelegramMsg(body.ok ? '✓ Test message delivered — check Telegram.' : `✕ ${body.error ?? body.detail}`);
    } catch (err) {
      setTelegramMsg(`✕ ${(err as Error).message}`);
    }
  };

  if (loading && !data) {
    return (
      <div className="space-y-4 pt-2">
        <Skeleton className="h-32" />
        <Skeleton className="h-96" />
      </div>
    );
  }

  if (error || !draft) {
    return (
      <Panel className="mt-4">
        <ErrorState message={error ?? 'Settings unavailable.'} onRetry={refresh} />
      </Panel>
    );
  }

  const integrations = data?.integrations;

  return (
    <div className="space-y-5 pt-2">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-[#f2f5fb]">Settings</h1>
        <p className="mt-1 text-xs text-[#5c6883]">
          Everything the engine uses is tunable here without a redeploy
        </p>
      </div>

      <Panel className="border-[#10b981]/25 p-4">
        <div className="flex items-start gap-3">
          <span className="text-lg text-[#34d399]" aria-hidden>
            ⛨
          </span>
          <div>
            <h2 className="text-sm font-semibold text-[#34d399]">Analysis only — this system cannot execute trades</h2>
            <p className="mt-1.5 text-[11px] leading-relaxed text-[#a8b3cc]">
              There is no order-entry code in this application, no Bybit API key is required or accepted, and every
              outbound exchange request is validated against a public market-data allowlist before a socket opens.
              Enabling execution would require a separate repository and an approved architecture decision.
            </p>
          </div>
        </div>
      </Panel>

      {/* Integrations */}
      <Panel className="p-4">
        <SectionTitle
          title="Integrations"
          subtitle="The app runs on live Bybit data with zero configuration. These unlock persistence and alerts."
        />
        <IntegrationRow
          name="Bybit V5 public market data"
          ok
          detail="No credentials required. The scanner reads public instruments, tickers, klines, open interest and funding directly from api.bybit.com."
        />
        <IntegrationRow
          name="Supabase (durable storage)"
          ok={Boolean(integrations?.supabaseConfigured)}
          detail={
            integrations?.storeKind === 'supabase'
              ? 'Connected. Opportunity history, scan runs and alert deliveries persist across deploys.'
              : 'Using the in-memory store. Everything works, but opportunity history resets when the serverless instance recycles.'
          }
          instructions="1) Create a project at supabase.com. 2) Run supabase/migrations/0001_init.sql in the SQL Editor. 3) In Vercel → Settings → Environment Variables add NEXT_PUBLIC_SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY. 4) Redeploy."
        />
        <IntegrationRow
          name="Telegram alerts"
          ok={Boolean(integrations?.telegramConfigured)}
          detail={
            integrations?.telegramConfigured
              ? 'Bot token and chat id detected. Confirmed opportunities are delivered to your chat.'
              : 'Not configured. Confirmed opportunities are still recorded and shown in the dashboard.'
          }
          instructions="1) Message @BotFather on Telegram and send /newbot to get a token. 2) Message @userinfobot to get your numeric chat id. 3) Add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in Vercel → Settings → Environment Variables. 4) Redeploy, then press Send test message."
        />
        <IntegrationRow
          name="Cron secret"
          ok={Boolean(integrations?.cronSecretSet)}
          detail={
            integrations?.cronSecretSet
              ? 'The /api/scan endpoint requires a bearer token. Vercel Cron supplies it automatically.'
              : 'The scan endpoint is currently open. Set CRON_SECRET to require authorization.'
          }
          instructions="Add CRON_SECRET with any random string in Vercel → Settings → Environment Variables."
        />
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button onClick={testTelegram} variant="ghost">
            Send test message
          </Button>
          {telegramMsg ? <span className="text-[11px] text-[#a8b3cc]">{telegramMsg}</span> : null}
        </div>
      </Panel>

      {/* Markets & timeframes */}
      <Panel className="p-4">
        <SectionTitle title="Markets & timeframes" subtitle="What the scanner covers on every cycle" />
        <div className="grid gap-5 md:grid-cols-2">
          <Field label="Markets" hint="Spot and linear are distinct market identities even for the same symbol.">
            <div className="flex gap-2">
              {(['linear', 'spot'] as const).map((m) => {
                const on = draft.markets.includes(m);
                return (
                  <button
                    key={m}
                    type="button"
                    onClick={() =>
                      update(
                        'markets',
                        on ? draft.markets.filter((x) => x !== m) : [...draft.markets, m],
                      )
                    }
                    aria-pressed={on}
                    className={`rounded-lg border px-3 py-2 text-[11px] font-semibold uppercase tracking-wider ${
                      on ? 'border-[#22d3ee]/40 bg-[#22d3ee]/12 text-[#67e8f9]' : 'border-white/10 text-[#7d8aa8]'
                    }`}
                  >
                    {m === 'linear' ? 'Linear perps' : 'Spot'}
                  </button>
                );
              })}
            </div>
          </Field>

          <Field
            label="Signal timeframes"
            hint="5m is off by default — it is the noisiest timeframe and produces the most false signals."
          >
            <div className="flex flex-wrap gap-1.5">
              {TIMEFRAMES.map((tf) => {
                const on = draft.timeframes.includes(tf);
                return (
                  <button
                    key={tf}
                    type="button"
                    onClick={() =>
                      update('timeframes', on ? draft.timeframes.filter((x) => x !== tf) : [...draft.timeframes, tf])
                    }
                    aria-pressed={on}
                    className={`rounded-lg border px-2.5 py-1.5 text-[11px] font-semibold ${
                      on ? 'border-[#22d3ee]/40 bg-[#22d3ee]/12 text-[#67e8f9]' : 'border-white/10 text-[#7d8aa8]'
                    }`}
                  >
                    {tf}
                  </button>
                );
              })}
            </div>
          </Field>

          <Field label="Context timeframe" hint="Higher timeframe used only as directional bias in scoring.">
            <select
              value={draft.contextTimeframe}
              onChange={(e) => update('contextTimeframe', e.target.value as Settings['contextTimeframe'])}
              className={inputClass}
            >
              {TIMEFRAMES.map((tf) => (
                <option key={tf} value={tf} className="bg-[#0f1420]">
                  {tf}
                </option>
              ))}
            </select>
          </Field>

          <Field
            label="Tier-2 candidates per scan"
            hint="How many top-ranked instruments get full pattern analysis. Higher = more coverage, longer scans."
          >
            <input
              type="number"
              min={1}
              max={400}
              value={draft.tier2Candidates}
              onChange={(e) => update('tier2Candidates', Number(e.target.value))}
              className={inputClass}
            />
          </Field>
        </div>
      </Panel>

      {/* Quality gates */}
      <Panel className="p-4">
        <SectionTitle title="Quality gates" subtitle="Thresholds a setup must clear before it becomes an alert" />
        <div className="grid gap-5 md:grid-cols-3">
          <Field label="Watch threshold" hint="Score at which a setup is recorded as FORMING.">
            <input
              type="number"
              min={0}
              max={100}
              value={draft.watchThreshold}
              onChange={(e) => update('watchThreshold', Number(e.target.value))}
              className={inputClass}
            />
          </Field>
          <Field label="Confirmed threshold" hint="Score required for CONFIRMED status and a Telegram alert.">
            <input
              type="number"
              min={0}
              max={100}
              value={draft.confirmedThreshold}
              onChange={(e) => update('confirmedThreshold', Number(e.target.value))}
              className={inputClass}
            />
          </Field>
          <Field label="Minimum reward:risk" hint="Setups below this asymmetry never confirm.">
            <input
              type="number"
              step={0.1}
              min={0.1}
              value={draft.minRewardToRisk}
              onChange={(e) => update('minRewardToRisk', Number(e.target.value))}
              className={inputClass}
            />
          </Field>
          <Field label="Min 24h turnover (USD)" hint="Liquidity floor. Thin books produce unreliable levels.">
            <input
              type="number"
              min={0}
              step={100000}
              value={draft.minTurnover24h}
              onChange={(e) => update('minTurnover24h', Number(e.target.value))}
              className={inputClass}
            />
          </Field>
          <Field label="Max spread (bps)" hint="Wide spreads make scenario prices unrealistic.">
            <input
              type="number"
              min={0}
              value={draft.maxSpreadBps}
              onChange={(e) => update('maxSpreadBps', Number(e.target.value))}
              className={inputClass}
            />
          </Field>
          <Field label="Min instrument age (days)" hint="New listings lack the history needed for reliable levels.">
            <input
              type="number"
              min={0}
              value={draft.minInstrumentAgeDays}
              onChange={(e) => update('minInstrumentAgeDays', Number(e.target.value))}
              className={inputClass}
            />
          </Field>
        </div>
      </Panel>

      {/* Alerts */}
      <Panel className="p-4">
        <SectionTitle title="Alerts & noise control" />
        <div className="grid gap-5 md:grid-cols-3">
          <Field label="Cooldown (minutes)" hint="Suppresses repeat signals for the same symbol, pattern and timeframe.">
            <input
              type="number"
              min={0}
              value={draft.cooldownMinutes}
              onChange={(e) => update('cooldownMinutes', Number(e.target.value))}
              className={inputClass}
            />
          </Field>
          <Field label="Max signals per scan" hint="Hard cap so one volatile session cannot flood you.">
            <input
              type="number"
              min={1}
              max={200}
              value={draft.maxSignalsPerScan}
              onChange={(e) => update('maxSignalsPerScan', Number(e.target.value))}
              className={inputClass}
            />
          </Field>
          <Field label="Muted symbols" hint="Comma separated, e.g. DOGEUSDT, SHIBUSDT">
            <input
              type="text"
              value={draft.mutedSymbols.join(', ')}
              onChange={(e) =>
                update(
                  'mutedSymbols',
                  e.target.value
                    .split(',')
                    .map((s) => s.trim().toUpperCase())
                    .filter(Boolean),
                )
              }
              className={inputClass}
            />
          </Field>
          <Field label="Telegram alerts">
            <button
              type="button"
              onClick={() => update('telegramEnabled', !draft.telegramEnabled)}
              aria-pressed={draft.telegramEnabled}
              className={`rounded-lg border px-3 py-2 text-[11px] font-semibold uppercase tracking-wider ${
                draft.telegramEnabled
                  ? 'border-[#10b981]/40 bg-[#10b981]/12 text-[#34d399]'
                  : 'border-white/10 text-[#7d8aa8]'
              }`}
            >
              {draft.telegramEnabled ? 'Enabled' : 'Disabled'}
            </button>
          </Field>
          <Field label="Quiet hours" hint={`Local to ${draft.quietHoursTimezone}`}>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => update('quietHoursEnabled', !draft.quietHoursEnabled)}
                aria-pressed={draft.quietHoursEnabled}
                className={`rounded-lg border px-3 py-2 text-[11px] font-semibold ${
                  draft.quietHoursEnabled
                    ? 'border-[#f59e0b]/40 bg-[#f59e0b]/12 text-[#fbbf24]'
                    : 'border-white/10 text-[#7d8aa8]'
                }`}
              >
                {draft.quietHoursEnabled ? 'On' : 'Off'}
              </button>
              <input
                type="number"
                min={0}
                max={23}
                value={draft.quietHoursStart}
                onChange={(e) => update('quietHoursStart', Number(e.target.value))}
                className={`${inputClass} w-16`}
                aria-label="Quiet hours start"
              />
              <span className="text-xs text-[#5c6883]">to</span>
              <input
                type="number"
                min={0}
                max={23}
                value={draft.quietHoursEnd}
                onChange={(e) => update('quietHoursEnd', Number(e.target.value))}
                className={`${inputClass} w-16`}
                aria-label="Quiet hours end"
              />
            </div>
          </Field>
          <Field label="Display timezone">
            <input
              type="text"
              value={draft.timezone}
              onChange={(e) => update('timezone', e.target.value)}
              className={inputClass}
            />
          </Field>
        </div>
      </Panel>

      {/* Risk planner */}
      <Panel className="p-4">
        <SectionTitle
          title="Hypothetical risk planner"
          subtitle="Educational calculator only. Never connected to your Bybit account and never used to size a real order."
        />
        <div className="grid gap-5 md:grid-cols-3">
          <Field label="Account size (USD)">
            <input
              type="number"
              min={0}
              value={draft.plannerAccountSize}
              onChange={(e) => update('plannerAccountSize', Number(e.target.value))}
              className={inputClass}
            />
          </Field>
          <Field label="Risk per setup (%)" hint="Hard maximum of 2% by design.">
            <input
              type="number"
              step={0.1}
              min={0.1}
              max={2}
              value={draft.plannerRiskPct}
              onChange={(e) => update('plannerRiskPct', Math.min(2, Number(e.target.value)))}
              className={inputClass}
            />
          </Field>
          <Field label="Illustrative leverage" hint="Used only to visualize margin. Not an instruction.">
            <input
              type="number"
              min={1}
              max={25}
              value={draft.plannerLeverage}
              onChange={(e) => update('plannerLeverage', Number(e.target.value))}
              className={inputClass}
            />
          </Field>
        </div>
        <p className="mono mt-4 rounded-lg bg-white/[0.03] px-3 py-2.5 text-[11px] text-[#a8b3cc]">
          Risk budget per setup: ${((draft.plannerAccountSize * draft.plannerRiskPct) / 100).toFixed(2)}
        </p>
      </Panel>

      {/* Save */}
      <Panel className="flex flex-wrap items-center gap-3 p-4">
        {integrations?.adminPasswordSet ? (
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Admin password"
            aria-label="Admin password"
            className={`${inputClass} max-w-[200px]`}
          />
        ) : null}
        <Button onClick={save} disabled={saving}>
          {saving ? 'Saving…' : 'Save settings'}
        </Button>
        <Button variant="ghost" onClick={() => data?.defaults && setDraft(data.defaults)}>
          Reset to defaults
        </Button>
        {message ? <span className="text-[11px] text-[#a8b3cc]">{message}</span> : null}
      </Panel>
    </div>
  );
}
