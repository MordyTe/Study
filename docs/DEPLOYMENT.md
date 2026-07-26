# Deployment

## Prerequisites

A GitHub account and a Vercel account. Nothing else. No exchange keys, no database, no server.

## Step 1 — Deploy to Vercel

1. Open **[vercel.com/new](https://vercel.com/new)**.
2. Choose **Import Git Repository** and select this repo.
3. Vercel auto-detects Next.js. **Do not change any build setting.**
4. Skip environment variables for now — the app runs live without them.
5. Press **Deploy**.

The build takes about a minute. Vercel then gives you a URL like `https://bybit-pattern-scanner.vercel.app`.

## Step 2 — Verify it is genuinely live

Open the deployment and go to **System Health → Run live verification**, or `GET /api/verify-live`.

A healthy result looks like this:

```json
{
  "ok": true,
  "summary": "7/7 live checks passed against https://api.bybit.com",
  "instrumentCounts": { "spot": 600, "linear": 550, "total": 1150 },
  "btcusdtLastPrice": 104213.5,
  "checks": [ … ]
}
```

Numbers vary with the market — what matters is that `ok` is `true`, `linear` exceeds ~300 (proving pagination exhausted `nextPageCursor` rather than stopping at the first page), and `btcusdtLastPrice` is a real current price.

If it returns `503`, read the failing check's `detail` field. It names the exact problem.

## Step 3 — Scanning cadence

`vercel.json` ships:

```json
{ "crons": [{ "path": "/api/scan", "schedule": "0 6 * * *" }] }
```

### Why daily, and not every 15 minutes

**The Vercel Hobby plan only permits daily cron granularity.** A schedule such as `*/15 * * * *` does not merely get downgraded — Vercel **rejects the entire deployment** with a cron-limit error before the build starts, so nothing deploys at all. The shipped schedule is therefore Hobby-safe by default.

### Getting frequent scans

| Option | Cadence | Cost | Setup |
|---|---|---|---|
| **Scan now** | On demand | Free | Command Center → **Scan now**. Runs a full scan immediately. |
| **External cron** | Any | Free | See below. Recommended on Hobby. |
| **Vercel Pro** | Any | Paid | Set `"schedule": "*/15 * * * *"` in `vercel.json`, commit, redeploy. |

**External cron setup** (free, works on Hobby):

1. Create a job at [cron-job.org](https://cron-job.org) (or UptimeRobot, or any scheduler).
2. URL: `https://<your-app>.vercel.app/api/scan`
3. Method: `GET`
4. Interval: every 15 minutes
5. If you set `CRON_SECRET`, add a request header: `Authorization: Bearer <your secret>`

The endpoint is idempotent — a scan that overlaps a previous one simply re-evaluates current market state; de-duplication by fingerprint prevents duplicate opportunities or repeated alerts.

Do not wait for any schedule to verify the system works — press **Scan now**. **Alerts → Scan history** then shows the run with instruments ranked, candidates evaluated, and setups confirmed.

## Step 4 — Optional integrations

Add these under **Vercel → Settings → Environment Variables**, then **redeploy** (environment changes do not apply to an existing deployment).

### Supabase — durable history

Without it the app uses an in-memory store: fully functional, but opportunity history resets whenever the serverless instance recycles.

1. Create a project at [supabase.com](https://supabase.com).
2. Open **SQL Editor**, paste the contents of `supabase/migrations/0001_init.sql`, and run it.
3. In **Project Settings → API**, copy the **Project URL** and the **`service_role`** key.
4. Add:
   - `NEXT_PUBLIC_SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY`
5. Redeploy.

**Health → Storage** should then read `Supabase` instead of `In-memory`. If the migration has not been run, the app detects the missing tables and falls back to memory rather than erroring — check the Health page if you expected persistence.

> The `service_role` key bypasses Row Level Security. It is used server-side only and is never exposed to the browser. Do not put it in a `NEXT_PUBLIC_*` variable.

### Telegram — alerts

1. Message [@BotFather](https://t.me/BotFather), send `/newbot`, follow the prompts, copy the token.
2. Message [@userinfobot](https://t.me/userinfobot) to get your numeric chat id.
3. Add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
4. Redeploy, then press **Send test message** on the Settings or Alerts page.

You must have started a conversation with your bot at least once, or Telegram rejects the first message.

### CRON_SECRET — protect the scan endpoint

Set any random string. `/api/scan` then requires `Authorization: Bearer <secret>`, which Vercel Cron sends automatically. Without it the endpoint is publicly callable — harmless (it only reads public data and writes to your own store) but wasteful.

### ADMIN_PASSWORD — protect settings writes

When set, the Settings page requires it before saving.

## Environment variable reference

| Variable | Required | Purpose |
|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | No | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | No | Server-side database writes |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | No | Used only if the service-role key is absent |
| `TELEGRAM_BOT_TOKEN` | No | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | No | Destination chat id |
| `CRON_SECRET` | No | Bearer token required by `/api/scan` |
| `ADMIN_PASSWORD` | No | Password for saving settings |
| `NEXT_PUBLIC_APP_URL` | No | Overrides the dashboard link in Telegram messages |
| `AI_EXPLANATIONS_ENABLED` | No | Reserved for the optional narrative layer; `false` by default |
| `BYBIT_API_KEY` / `BYBIT_API_SECRET` | **Never** | **Not supported.** Their presence makes the app refuse to run. |

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Health shows Bybit `DISCONNECTED` | Your deployment cannot reach `api.bybit.com`. Vercel's network can. Some corporate networks and restricted sandboxes block it — check from the deployment, not from your laptop. |
| Verification reports fewer than ~300 linear instruments | Pagination stopped early. Confirm `getInstruments` is following `nextPageCursor` to exhaustion. |
| Scanner table is empty | Every instrument was filtered out. Lower **Min 24h turnover** or raise **Max spread** in Settings. |
| Opportunity deck stays empty | Expected and honest. `CONFIRMED` requires score ≥ 75, R:R ≥ 2.0, and a fully healthy verification record. Lower the thresholds in Settings to see more, understanding that quality drops. |
| Opportunities disappear after a while | The in-memory store recycled with the serverless instance. Add Supabase. |
| Telegram test fails | Token or chat id wrong, or you never messaged the bot first. The error detail from the Telegram API is shown verbatim. |
| Scan times out | Lower **Tier-2 candidates per scan** in Settings. The scan self-limits at 45 seconds and reports how many candidates it deferred. |
| Deployment rejected with a cron limit error | The schedule in `vercel.json` is finer than daily and the account is on Hobby. Use `0 6 * * *` (shipped default) and drive frequent scans with an external cron, or upgrade to Pro. |
| Settings changes do nothing | They apply on the **next scan**. Press **Scan now**. |

## Local development

```bash
npm install
npm run dev        # http://localhost:3000
npm run check      # typecheck + 104 tests
npm run build      # production build
```

No `.env` file is needed. Copy `.env.example` to `.env.local` only when adding integrations.
