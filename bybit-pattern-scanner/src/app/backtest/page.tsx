'use client';

import { useState } from 'react';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { TIMEFRAMES, type Timeframe } from '@/lib/bybit/types';
import type { BacktestResult } from '@/lib/engine/backtest';
import { Button, Chip, Kpi, Panel, SectionTitle } from '@/components/ui';

const inputClass =
  'mono w-full rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-[#f2f5fb] focus:border-[#22d3ee]/50 focus:outline-none';

export default function BacktestPage() {
  const [symbol, setSymbol] = useState('BTCUSDT');
  const [category, setCategory] = useState<'linear' | 'spot'>('linear');
  const [timeframe, setTimeframe] = useState<Timeframe>('1h');
  const [bars, setBars] = useState(400);
  const [costBps, setCostBps] = useState(12);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch('/api/backtest', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ symbol: symbol.toUpperCase(), category, timeframe, bars, costBps }),
      });
      const body = await res.json();
      if (!body.ok) setError(body.error ?? 'Backtest failed.');
      else setResult({ summary: body.summary, signals: body.signals });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setRunning(false);
    }
  };

  const s = result?.summary;

  return (
    <div className="space-y-5 pt-2">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-[#f2f5fb]">Backtest Lab</h1>
        <p className="mt-1 text-xs text-[#5c6883]">
          Replays the exact production detectors over official Bybit history — no separate simplified engine
        </p>
      </div>

      <Panel className="border-[#f59e0b]/20 p-4">
        <p className="text-[11px] leading-relaxed text-[#fbbf24]">
          <strong>Simulated results.</strong> These are modelled signal outcomes, not executed trades. Real
          execution involves fills, slippage, funding and human behaviour that no simulation captures. Past
          behaviour does not predict future results.
        </p>
      </Panel>

      <Panel className="p-4">
        <SectionTitle title="Configuration" />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          <label className="block">
            <span className="mb-2 block text-xs font-medium text-[#d6dcea]">Symbol</span>
            <input value={symbol} onChange={(e) => setSymbol(e.target.value)} className={inputClass} />
          </label>
          <label className="block">
            <span className="mb-2 block text-xs font-medium text-[#d6dcea]">Market</span>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value as 'linear' | 'spot')}
              className={inputClass}
            >
              <option value="linear" className="bg-[#0f1420]">
                Linear perp
              </option>
              <option value="spot" className="bg-[#0f1420]">
                Spot
              </option>
            </select>
          </label>
          <label className="block">
            <span className="mb-2 block text-xs font-medium text-[#d6dcea]">Timeframe</span>
            <select
              value={timeframe}
              onChange={(e) => setTimeframe(e.target.value as Timeframe)}
              className={inputClass}
            >
              {TIMEFRAMES.map((tf) => (
                <option key={tf} value={tf} className="bg-[#0f1420]">
                  {tf}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="mb-2 block text-xs font-medium text-[#d6dcea]">Bars</span>
            <input
              type="number"
              min={120}
              max={700}
              value={bars}
              onChange={(e) => setBars(Number(e.target.value))}
              className={inputClass}
            />
          </label>
          <label className="block">
            <span className="mb-2 block text-xs font-medium text-[#d6dcea]">Round-trip cost (bps)</span>
            <input
              type="number"
              min={0}
              max={100}
              value={costBps}
              onChange={(e) => setCostBps(Number(e.target.value))}
              className={inputClass}
            />
          </label>
        </div>
        <div className="mt-4 flex items-center gap-3">
          <Button onClick={run} disabled={running}>
            {running ? 'Running backtest…' : '▶ Run backtest'}
          </Button>
          {error ? <span className="text-[11px] text-[#fb7185]">{error}</span> : null}
        </div>
      </Panel>

      {s ? (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            <Kpi label="Signals" value={s.totalSignals} hint={`${s.resolved} resolved`} />
            <Kpi
              label="Hit rate"
              value={`${s.hitRate}%`}
              tone={s.hitRate >= 50 ? 'bull' : 'bear'}
              hint={s.resolved < 20 ? '⚠ small sample' : `${s.wins}W / ${s.losses}L`}
            />
            <Kpi
              label="Expectancy"
              value={`${s.expectancyPct.toFixed(3)}%`}
              tone={s.expectancyPct > 0 ? 'bull' : 'bear'}
              hint="Average net return per signal"
            />
            <Kpi
              label="Profit factor"
              value={s.profitFactor ?? '—'}
              tone={(s.profitFactor ?? 0) > 1 ? 'bull' : 'bear'}
            />
            <Kpi label="Max drawdown" value={`${s.maxDrawdownPct}%`} tone="warn" />
            <Kpi label="Avg bars to outcome" value={s.avgBarsToOutcome ?? '—'} />
          </div>

          {s.resolved < 20 ? (
            <Panel className="border-[#f59e0b]/25 px-4 py-3">
              <p className="text-[11px] text-[#fbbf24]">
                Only {s.resolved} resolved signals. That is far too small a sample to conclude anything. Increase the
                bar count, test more symbols, or lower the confirmed threshold to gather more data before drawing
                conclusions.
              </p>
            </Panel>
          ) : null}

          <div className="grid gap-4 lg:grid-cols-2">
            <Panel className="p-4">
              <SectionTitle title="Scenario equity curve" subtitle="Compounded from a base of 100, after costs" />
              {s.equityCurve.length > 1 ? (
                <ResponsiveContainer width="100%" height={240}>
                  <AreaChart data={s.equityCurve}>
                    <defs>
                      <linearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#22d3ee" stopOpacity={0.35} />
                        <stop offset="100%" stopColor="#22d3ee" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid stroke="rgba(148,163,184,0.08)" />
                    <XAxis
                      dataKey="time"
                      tickFormatter={(t) => new Date(t).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })}
                      stroke="#5c6883"
                      fontSize={10}
                    />
                    <YAxis stroke="#5c6883" fontSize={10} domain={['auto', 'auto']} />
                    <Tooltip
                      contentStyle={{
                        background: '#0f1420',
                        border: '1px solid rgba(148,163,184,0.2)',
                        borderRadius: 8,
                        fontSize: 11,
                      }}
                      labelFormatter={(t) => new Date(Number(t)).toLocaleString('en-GB')}
                    />
                    <Area type="monotone" dataKey="equity" stroke="#22d3ee" fill="url(#eq)" strokeWidth={2} />
                  </AreaChart>
                </ResponsiveContainer>
              ) : (
                <p className="py-16 text-center text-xs text-[#5c6883]">Not enough resolved signals to plot a curve.</p>
              )}
            </Panel>

            <Panel className="p-4">
              <SectionTitle title="Outcome by score bucket" subtitle="Does a higher quality score actually correlate with better outcomes?" />
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={s.byScoreBucket}>
                  <CartesianGrid stroke="rgba(148,163,184,0.08)" />
                  <XAxis dataKey="bucket" stroke="#5c6883" fontSize={10} />
                  <YAxis stroke="#5c6883" fontSize={10} />
                  <Tooltip
                    contentStyle={{
                      background: '#0f1420',
                      border: '1px solid rgba(148,163,184,0.2)',
                      borderRadius: 8,
                      fontSize: 11,
                    }}
                  />
                  <Bar dataKey="hitRate" fill="#8b5cf6" name="Hit rate %" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </Panel>
          </div>

          <Panel className="p-4">
            <SectionTitle title="Performance by detector" />
            <div className="scroll-x">
              <table className="w-full min-w-[520px] text-left text-xs">
                <thead>
                  <tr className="border-b border-white/[0.06] text-[10px] uppercase tracking-wider text-[#5c6883]">
                    <th className="py-2 font-medium">Detector</th>
                    <th className="py-2 text-right font-medium">Signals</th>
                    <th className="py-2 text-right font-medium">Hit rate</th>
                    <th className="py-2 text-right font-medium">Avg return</th>
                  </tr>
                </thead>
                <tbody>
                  {s.byDetector.map((d) => (
                    <tr key={d.detector} className="border-b border-white/[0.03]">
                      <td className="mono py-2.5 text-[#d6dcea]">{d.detector}</td>
                      <td className="mono py-2.5 text-right text-[#a8b3cc]">{d.signals}</td>
                      <td
                        className="mono py-2.5 text-right"
                        style={{ color: d.hitRate >= 50 ? '#34d399' : '#fb7185' }}
                      >
                        {d.signals >= 5 ? `${d.hitRate}%` : <span className="text-[#5c6883]">n/a</span>}
                      </td>
                      <td
                        className="mono py-2.5 text-right"
                        style={{ color: d.avgReturnPct >= 0 ? '#34d399' : '#fb7185' }}
                      >
                        {d.avgReturnPct.toFixed(3)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          <Panel className="p-4">
            <SectionTitle title="Assumptions & reproducibility" />
            <ul className="space-y-2">
              {s.assumptions.map((a, i) => (
                <li key={i} className="flex gap-2 text-[11px] leading-relaxed text-[#a8b3cc]">
                  <span className="shrink-0 text-[#5c6883]" aria-hidden>
                    ·
                  </span>
                  <span>{a}</span>
                </li>
              ))}
            </ul>
            <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-white/[0.06] pt-3">
              <Chip tone="info">Bybit V5 Official</Chip>
              <Chip tone="muted">
                {new Date(s.from).toLocaleDateString('en-GB')} → {new Date(s.to).toLocaleDateString('en-GB')}
              </Chip>
              <Chip tone="muted">{s.barsEvaluated} bars</Chip>
            </div>
            <p className="mono mt-3 break-all text-[10px] text-[#5c6883]">
              Reproducibility ID: {s.reproducibilityId}
            </p>
            <p className="mono mt-1 text-[10px] text-[#5c6883]">
              Detector versions: {Object.entries(s.detectorVersions).map(([k, v]) => `${k}@${v}`).join(', ')}
            </p>
          </Panel>
        </>
      ) : null}
    </div>
  );
}
