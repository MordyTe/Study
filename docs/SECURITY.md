# Security

## The no-trading boundary

This application cannot place, amend, cancel, approve, or close a trade. That is enforced at four independent layers, each of which would have to be defeated separately.

### Layer 1 — Nothing to call

There is no order-entry code, no trading adapter, no execution service, and no broker client anywhere in the repository. `src/lib/bybit/client.ts` is the only module that opens a connection to an exchange, and it exposes exactly ten GET functions.

### Layer 2 — Runtime allowlist

`src/lib/bybit/allowlist.ts` defines `ALLOWED_PATHS`. Every request passes through `assertAllowedPath()` before a socket opens. The check runs in two stages: a forbidden-fragment scan (`/v5/order`, `/v5/position`, `/v5/account`, `/v5/asset`, `/v5/trade`, `/private`, …) and then an exact-membership test against the allowlist. An unknown path is rejected even if it looks harmless, so a typo or a future refactor cannot silently widen the surface.

```
GET /v5/market/time                  GET /v5/market/orderbook
GET /v5/market/instruments-info      GET /v5/market/open-interest
GET /v5/market/tickers               GET /v5/market/funding/history
GET /v5/market/kline                 GET /v5/market/recent-trade
GET /v5/market/mark-price-kline      GET /v5/market/index-price-kline
```

### Layer 3 — Credential refusal

`assertNoExchangeCredentials()` runs on the scan path and in the live verification. If `BYBIT_API_KEY`, `BYBIT_API_SECRET`, `BYBIT_SECRET`, or `BYBIT_PRIVATE_KEY` is present and non-empty, it **throws**. Their mere presence signals an attempt to add execution capability, so the system refuses to proceed rather than running alongside them.

`.env.example` documents that these variables are intentionally unsupported.

### Layer 4 — Static build gate

`tests/no-trading-guard.test.ts` walks every file under `src/` and fails if it finds:

- any forbidden Bybit trading path (the allowlist module itself is the sole exemption, since it must name the fragments to block them)
- a private or trade WebSocket URL (`stream.bybit.com/v5/private`, `/v5/trade`)
- a module named like an execution adapter (`order-executor`, `trade-executor`, `place-order`, `broker-client`, …)
- a trade-action UI control (`Place Order`, `Execute Trade`, `Approve Trade`, `Open Position`, `Close Position`), matched with word boundaries so legitimate strings like "Open Dashboard" and "closed candle" do not produce false positives

This test must never be weakened, skipped, or deleted. If a future change makes it fail, the change is wrong, not the test.

### Adding execution later

It would require a separate repository and an approved architecture decision. No placeholder, feature flag, or stub exists for it here — deliberately, because a stub is where a boundary starts to erode.

## Threat model

| Threat | Mitigation |
|---|---|
| **Accidental introduction of trading code** | Four-layer guard above; the static test fails CI. |
| **Secret leakage** | No exchange credentials exist. Telegram token and Supabase service-role key are server-side only and never sent to the browser. `.gitignore` excludes every `.env` variant except the example. Health and settings endpoints report booleans (`configured: true/false`), never values. |
| **SSRF** | The Bybit base URL is a hard-coded constant and paths are allowlisted; no user input can construct an outbound URL. Telegram calls use a fixed base plus the server-side token. |
| **Stale or spoofed upstream data** | Every confirmed opportunity carries a `DataVerificationRecord`: clock drift, data age, candle-integrity check, gap count, and a REST reconciliation of the newest closed candle against an independently fetched ticker. Any failure blocks confirmation and is surfaced in the UI. |
| **Duplicate or replayed alerts** | Opportunities are keyed by a stable fingerprint (exchange, market, symbol, timeframe, detector, version, direction, confirmation bar). Deliveries carry an idempotency key checked before every send, with a unique index in Postgres. |
| **Unauthenticated scan triggering** | Set `CRON_SECRET`; `/api/scan` then requires `Authorization: Bearer <secret>`, which Vercel Cron supplies automatically. Without it the endpoint is open — documented, and surfaced as "not configured" on the Settings page. |
| **Unauthorized settings changes** | Set `ADMIN_PASSWORD` to require it on every settings write. Settings are validated with a Zod schema; the risk-planner percentage is hard-capped at 2% in both the schema and the UI. |
| **Database privilege misuse** | The server writes with the service-role key. Row Level Security is enabled on every table. Anonymous clients get read-only access to analysis output; `alert_deliveries` has no public select policy at all. |
| **Cross-user data exposure** | The schema stores no personal data, no credentials, and no account identifiers — only market analysis. |
| **Malicious content in symbol names** | All Telegram output passes through `escapeMarkdown()`, which escapes the full MarkdownV2 reserved set. React escapes UI output by default. |
| **Supply chain** | Dependencies are pinned in `package-lock.json`. The runtime dependency set is deliberately small: Next, React, Zod, Supabase client, lightweight-charts, recharts. See *Dependency advisories* below for the current audit position. |

## HTTP headers

`next.config.ts` sets `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, and a restrictive `Permissions-Policy`. `robots` metadata marks the app `noindex, nofollow` — it is a private operator tool, not a public site.

## Reporting

If you find a way to make this application place a trade, that is a critical bug. Open an issue immediately with the reproduction, and treat any deployment as compromised until it is fixed.

## Dependency advisories

Current position as of 2026-07-25, from `npm audit --omit=dev`.

### Resolved

| Package | Advisory | Action taken |
|---|---|---|
| `next` | CVE-2025-66478 | Upgraded 15.5.4 → **15.5.22**, the patched release on the 15.x line. |
| `sharp` | libvips CVE-2026-33327 / 33328 / 35590 / 35591 | Pinned to `^0.35.3` via an npm `overrides` entry, because Next depends on an older range transitively. |

### Open, with no upstream fix available

| Package | Advisory | Assessment |
|---|---|---|
| `postcss` | XSS via unescaped `</style>` in stringify output; arbitrary file read and path traversal via attacker-controlled `sourceMappingURL` in CSS comments | **8.5.23 is the latest published version** — no patched release exists yet. It reaches this project only as a transitive build-time dependency of Next.js. |

**Why the `postcss` advisories do not translate into risk here.** All three require attacker-controlled CSS to be processed. This application compiles exactly one stylesheet, `src/app/globals.css`, which is authored in-repo and fixed at build time. No CSS is uploaded, fetched, user-supplied, or generated from external input at any point, and PostCSS never runs at request time — only during `next build`. There is no path by which a third party can introduce CSS into the pipeline.

`npm audit fix --force` proposes downgrading to `next@9.3.3` to clear these. That is npm's naive resolver reaching for any version whose lockfile lacks the advisory; it would discard six major versions of Next.js, break the entire application, and reintroduce years of genuinely exploitable issues. It must not be run.

Upgrading to Next 16.2.12 was tested and resolves none of these — the same transitive versions are pulled — so it offers no security benefit to weigh against a major-version migration.

**Re-check when** a patched `postcss` is published; the override block in `package.json` is where any pin belongs.
