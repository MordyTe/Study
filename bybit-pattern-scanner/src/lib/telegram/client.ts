/**
 * Telegram Bot API adapter — outbound only.
 * https://core.telegram.org/bots/api
 *
 * There is no trade-execution or approval button anywhere in this module.
 * Allowed inline actions: Open Dashboard, Watch, Mute 24h, Useful, Not Useful.
 */

import type { Opportunity } from '@/lib/engine/opportunity';
import type { Settings } from '@/lib/config/settings';

const API_BASE = 'https://api.telegram.org';

export interface TelegramConfig {
  botToken: string;
  chatId: string;
}

export function getTelegramConfig(): TelegramConfig | null {
  const botToken = process.env.TELEGRAM_BOT_TOKEN?.trim();
  const chatId = process.env.TELEGRAM_CHAT_ID?.trim();
  if (!botToken || !chatId) return null;
  return { botToken, chatId };
}

export function isTelegramConfigured(): boolean {
  return getTelegramConfig() !== null;
}

/** MarkdownV2 requires escaping this exact set. Symbol names are untrusted input. */
export function escapeMarkdown(text: string): string {
  return text.replace(/[_*[\]()~`>#+\-=|{}.!\\]/g, (m) => `\\${m}`);
}

function formatPrice(value: number): string {
  if (!Number.isFinite(value)) return 'n/a';
  if (Math.abs(value) >= 1000) return value.toFixed(2);
  if (Math.abs(value) >= 1) return value.toFixed(4);
  return value.toPrecision(6);
}

function formatTime(ts: number, timezone: string): string {
  try {
    return new Intl.DateTimeFormat('en-GB', {
      dateStyle: 'short',
      timeStyle: 'short',
      timeZone: timezone,
    }).format(new Date(ts));
  } catch {
    return new Date(ts).toISOString();
  }
}

/** Builds the MarkdownV2 caption for a confirmed opportunity. */
export function formatOpportunityMessage(
  opp: Opportunity,
  settings: Settings,
  dashboardUrl: string | null,
): string {
  const dir = opp.direction === 'long' ? 'Potential Long' : 'Potential Short';
  const marketLabel = opp.category === 'linear' ? 'Linear Perp' : 'Spot';
  const headline = opp.status === 'CONFIRMED' ? 'CONFIRMED OPPORTUNITY' : `UPDATE: ${opp.status}`;

  const lines: string[] = [];
  lines.push(`*${escapeMarkdown(headline)}*`);
  lines.push(
    `${escapeMarkdown(opp.symbol)} · ${escapeMarkdown(marketLabel)} · ${escapeMarkdown(opp.timeframe)} · ${escapeMarkdown(dir)}`,
  );
  lines.push('');
  lines.push(`Pattern: ${escapeMarkdown(opp.patternDisplayName)}`);
  lines.push(`Setup Quality: ${escapeMarkdown(`${opp.score}/100`)}`);
  lines.push(
    `Data: ${escapeMarkdown(`${opp.verification.source} · ${opp.verification.health}`)}`,
  );
  lines.push('');
  lines.push(
    `Possible entry zone: ${escapeMarkdown(`${formatPrice(opp.entryZone.from)} – ${formatPrice(opp.entryZone.to)}`)}`,
  );
  lines.push(`Scenario invalidation: ${escapeMarkdown(formatPrice(opp.invalidation))}`);
  opp.targets.forEach((t, i) => {
    lines.push(`Possible target ${i + 1}: ${escapeMarkdown(`${formatPrice(t.price)} (${t.method})`)}`);
  });
  lines.push(`Estimated R:R: ${escapeMarkdown(String(opp.rewardToRisk))}`);
  lines.push('');
  lines.push('*Why it qualifies:*');
  for (const r of opp.reasonsFor.slice(0, 4)) lines.push(`• ${escapeMarkdown(r)}`);
  lines.push('');
  lines.push('*Main risks:*');
  for (const r of opp.reasonsAgainst.slice(0, 3)) lines.push(`• ${escapeMarkdown(r)}`);
  lines.push('');
  lines.push(`Detected: ${escapeMarkdown(formatTime(opp.detectedAt, settings.timezone))}`);
  lines.push(
    `Exchange time: ${escapeMarkdown(formatTime(opp.verification.exchangeTimestamp, settings.timezone))}`,
  );
  if (dashboardUrl) lines.push(`Dashboard: ${escapeMarkdown(`${dashboardUrl}/opportunity/${opp.id}`)}`);
  lines.push('');
  lines.push(escapeMarkdown('Analysis only — no trade was placed.'));

  return lines.join('\n');
}

interface InlineButton {
  text: string;
  url?: string;
  callback_data?: string;
}

function buildKeyboard(opp: Opportunity, dashboardUrl: string | null): { inline_keyboard: InlineButton[][] } {
  const row1: InlineButton[] = [];
  if (dashboardUrl) row1.push({ text: '📊 Open Dashboard', url: `${dashboardUrl}/opportunity/${opp.id}` });
  row1.push({ text: '👁 Watch', callback_data: `watch:${opp.id}` });

  const row2: InlineButton[] = [
    { text: '🔕 Mute 24h', callback_data: `mute:${opp.symbol}` },
    { text: '👍 Useful', callback_data: `useful:${opp.id}` },
    { text: '👎 Not Useful', callback_data: `notuseful:${opp.id}` },
  ];

  return { inline_keyboard: [row1, row2] };
}

async function telegramCall<T>(
  config: TelegramConfig,
  method: string,
  payload: Record<string, unknown>,
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15_000);

  try {
    const res = await fetch(`${API_BASE}/bot${config.botToken}/${method}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    const body = (await res.json()) as { ok: boolean; result?: T; description?: string };
    if (!body.ok) throw new Error(body.description ?? `Telegram ${method} failed`);
    return body.result as T;
  } finally {
    clearTimeout(timer);
  }
}

export async function sendOpportunityAlert(
  opp: Opportunity,
  settings: Settings,
  dashboardUrl: string | null,
): Promise<{ sent: boolean; detail: string }> {
  const config = getTelegramConfig();
  if (!config) return { sent: false, detail: 'Telegram is not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing).' };

  const text = formatOpportunityMessage(opp, settings, dashboardUrl);
  try {
    await telegramCall(config, 'sendMessage', {
      chat_id: config.chatId,
      text,
      parse_mode: 'MarkdownV2',
      disable_web_page_preview: true,
      reply_markup: buildKeyboard(opp, dashboardUrl),
    });
    return { sent: true, detail: `Alert delivered for ${opp.symbol} ${opp.timeframe}.` };
  } catch (err) {
    return { sent: false, detail: `Telegram send failed: ${(err as Error).message}` };
  }
}

export async function sendTestMessage(): Promise<{ sent: boolean; detail: string }> {
  const config = getTelegramConfig();
  if (!config) {
    return {
      sent: false,
      detail: 'Telegram is not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in your environment.',
    };
  }
  try {
    await telegramCall(config, 'sendMessage', {
      chat_id: config.chatId,
      text: [
        '*Bybit Pattern Scanner*',
        '',
        escapeMarkdown('Telegram connection verified. You will receive confirmed opportunity alerts here.'),
        '',
        escapeMarkdown('Analysis only — this system cannot execute trades.'),
      ].join('\n'),
      parse_mode: 'MarkdownV2',
    });
    return { sent: true, detail: 'Test message delivered.' };
  } catch (err) {
    return { sent: false, detail: `Telegram test failed: ${(err as Error).message}` };
  }
}

/** Lifecycle updates (invalidated, target reached, expired). */
export async function sendLifecycleUpdate(
  opp: Opportunity,
  settings: Settings,
  dashboardUrl: string | null,
): Promise<{ sent: boolean; detail: string }> {
  const config = getTelegramConfig();
  if (!config) return { sent: false, detail: 'Telegram not configured.' };

  const emoji =
    opp.status === 'INVALIDATED' ? '❌' : opp.status.startsWith('TARGET') ? '🎯' : opp.status === 'EXPIRED' ? '⌛' : 'ℹ️';

  const text = [
    `*${escapeMarkdown(`${emoji} ${opp.status.replace(/_/g, ' ')}`)}*`,
    `${escapeMarkdown(opp.symbol)} · ${escapeMarkdown(opp.category)} · ${escapeMarkdown(opp.timeframe)}`,
    '',
    escapeMarkdown(`Pattern: ${opp.patternDisplayName}`),
    escapeMarkdown(`Last price: ${formatPrice(opp.lastPrice)}`),
    escapeMarkdown(`MFE ${opp.maxFavorableExcursionPct}% · MAE ${opp.maxAdverseExcursionPct}%`),
    '',
    escapeMarkdown('This is a tracked analytical scenario. No position was ever opened by this system.'),
  ].join('\n');

  try {
    await telegramCall(config, 'sendMessage', {
      chat_id: config.chatId,
      text,
      parse_mode: 'MarkdownV2',
      disable_web_page_preview: true,
      reply_markup: buildKeyboard(opp, dashboardUrl),
    });
    return { sent: true, detail: `Lifecycle update sent (${opp.status}).` };
  } catch (err) {
    return { sent: false, detail: `Telegram lifecycle update failed: ${(err as Error).message}` };
  }
}
