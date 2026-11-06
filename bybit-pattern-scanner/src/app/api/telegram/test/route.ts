import { NextResponse } from 'next/server';
import { isTelegramConfigured, sendTestMessage } from '@/lib/telegram/client';

export const dynamic = 'force-dynamic';

export async function POST() {
  if (!isTelegramConfigured()) {
    return NextResponse.json(
      {
        ok: false,
        error:
          'Telegram is not configured. Add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in Vercel → Settings → Environment Variables, then redeploy.',
      },
      { status: 400 },
    );
  }

  const result = await sendTestMessage();
  return NextResponse.json({ ok: result.sent, detail: result.detail }, { status: result.sent ? 200 : 502 });
}
