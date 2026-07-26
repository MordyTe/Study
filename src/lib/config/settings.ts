/**
 * Runtime settings. Everything an operator can tune lives here and is editable
 * from the Settings page without a redeploy — that is why the app ships usable
 * with zero environment configuration.
 */

import { z } from 'zod';
import { TIMEFRAMES, type MarketCategory, type Timeframe } from '@/lib/bybit/types';

export const settingsSchema = z.object({
  /** Which Bybit market categories are scanned. */
  markets: z.array(z.enum(['spot', 'linear'])).min(1),
  /** Timeframes that produce alertable signals. */
  timeframes: z.array(z.enum(TIMEFRAMES)).min(1),
  /** Higher timeframe used purely as directional context. */
  contextTimeframe: z.enum(TIMEFRAMES),

  /** Liquidity and hygiene filters. */
  minTurnover24h: z.number().min(0),
  maxSpreadBps: z.number().min(0),
  minInstrumentAgeDays: z.number().min(0),

  /** Score gates. */
  watchThreshold: z.number().min(0).max(100),
  confirmedThreshold: z.number().min(0).max(100),
  minRewardToRisk: z.number().min(0.1).max(20),

  /** Noise control. */
  cooldownMinutes: z.number().min(0),
  maxSignalsPerScan: z.number().min(1).max(200),
  mutedSymbols: z.array(z.string()),
  mutedDetectors: z.array(z.string()),

  /** How many instruments Tier-1 promotes into full analysis per scan. */
  tier2Candidates: z.number().min(1).max(400),

  /** Alerts. */
  telegramEnabled: z.boolean(),
  quietHoursEnabled: z.boolean(),
  quietHoursStart: z.number().min(0).max(23),
  quietHoursEnd: z.number().min(0).max(23),
  quietHoursTimezone: z.string(),
  /** Invalidation alerts may bypass quiet hours. */
  criticalBypassQuietHours: z.boolean(),

  /** Display. */
  timezone: z.string(),

  /** Hypothetical risk planner — educational only, never connected to an exchange. */
  plannerAccountSize: z.number().min(0),
  plannerRiskPct: z.number().min(0.1).max(2),
  plannerLeverage: z.number().min(1).max(25),

  /** Data verification tolerances. */
  maxClockDriftMs: z.number().min(0),
  maxDataAgeMs: z.number().min(0),
  reconciliationTolerancePct: z.number().min(0),
});

export type Settings = z.infer<typeof settingsSchema>;

export const DEFAULT_SETTINGS: Settings = {
  markets: ['linear', 'spot'],
  // 5m is intentionally OFF by default — it is the noisiest timeframe.
  timeframes: ['15m', '1h', '4h', '1d'],
  contextTimeframe: '4h',

  minTurnover24h: 5_000_000,
  maxSpreadBps: 15,
  minInstrumentAgeDays: 7,

  watchThreshold: 65,
  confirmedThreshold: 75,
  minRewardToRisk: 2.0,

  cooldownMinutes: 120,
  maxSignalsPerScan: 40,
  mutedSymbols: [],
  mutedDetectors: [],

  tier2Candidates: 60,

  telegramEnabled: true,
  quietHoursEnabled: false,
  quietHoursStart: 1,
  quietHoursEnd: 7,
  quietHoursTimezone: 'Asia/Jerusalem',
  criticalBypassQuietHours: true,

  timezone: 'Asia/Jerusalem',

  plannerAccountSize: 10_000,
  plannerRiskPct: 1,
  plannerLeverage: 5,

  maxClockDriftMs: 5_000,
  maxDataAgeMs: 10 * 60_000,
  reconciliationTolerancePct: 0.5,
};

export function mergeSettings(partial: unknown): Settings {
  const parsed = settingsSchema.partial().safeParse(partial ?? {});
  if (!parsed.success) return DEFAULT_SETTINGS;
  return { ...DEFAULT_SETTINGS, ...parsed.data };
}

export function isMarketEnabled(settings: Settings, category: MarketCategory): boolean {
  return settings.markets.includes(category);
}

export function isTimeframeEnabled(settings: Settings, tf: Timeframe): boolean {
  return settings.timeframes.includes(tf);
}

/** True when the current wall-clock hour falls inside the configured quiet window. */
export function isQuietHour(settings: Settings, now: Date = new Date()): boolean {
  if (!settings.quietHoursEnabled) return false;
  let hour: number;
  try {
    hour = Number(
      new Intl.DateTimeFormat('en-US', {
        hour: 'numeric',
        hour12: false,
        timeZone: settings.quietHoursTimezone,
      }).format(now),
    );
  } catch {
    hour = now.getUTCHours();
  }
  const { quietHoursStart: start, quietHoursEnd: end } = settings;
  return start <= end ? hour >= start && hour < end : hour >= start || hour < end;
}
