import { NextResponse } from 'next/server';
import { getStore } from '@/lib/store';
import { DEFAULT_SETTINGS, mergeSettings, settingsSchema } from '@/lib/config/settings';
import { isTelegramConfigured } from '@/lib/telegram/client';
import { isSupabaseConfigured } from '@/lib/store';

export const dynamic = 'force-dynamic';

export async function GET() {
  try {
    const store = await getStore();
    const settings = await store.getSettings();
    return NextResponse.json({
      ok: true,
      settings,
      defaults: DEFAULT_SETTINGS,
      integrations: {
        storeKind: store.kind,
        supabaseConfigured: isSupabaseConfigured(),
        telegramConfigured: isTelegramConfigured(),
        cronSecretSet: Boolean(process.env.CRON_SECRET),
        adminPasswordSet: Boolean(process.env.ADMIN_PASSWORD),
        aiExplanationsEnabled: process.env.AI_EXPLANATIONS_ENABLED === 'true',
        appUrl: process.env.NEXT_PUBLIC_APP_URL ?? process.env.VERCEL_URL ?? null,
      },
    });
  } catch (err) {
    return NextResponse.json({ ok: false, error: (err as Error).message }, { status: 500 });
  }
}

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as { settings?: unknown; password?: string };

    // Optional write protection.
    const required = process.env.ADMIN_PASSWORD;
    if (required && body.password !== required) {
      return NextResponse.json({ ok: false, error: 'Invalid admin password.' }, { status: 401 });
    }

    const merged = mergeSettings(body.settings);
    const parsed = settingsSchema.safeParse(merged);
    if (!parsed.success) {
      return NextResponse.json(
        { ok: false, error: 'Invalid settings', issues: parsed.error.issues.slice(0, 8) },
        { status: 400 },
      );
    }

    // Guard against a nonsensical gate ordering.
    if (parsed.data.confirmedThreshold < parsed.data.watchThreshold) {
      return NextResponse.json(
        { ok: false, error: 'Confirmed threshold must be greater than or equal to the watch threshold.' },
        { status: 400 },
      );
    }

    const store = await getStore();
    await store.saveSettings(parsed.data);
    return NextResponse.json({ ok: true, settings: parsed.data, storeKind: store.kind });
  } catch (err) {
    return NextResponse.json({ ok: false, error: (err as Error).message }, { status: 500 });
  }
}
