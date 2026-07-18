# ☁️ פריסה לענן — Vercel + Supabase

המערכת עובדת בשני מצבים מאותו קוד: **מקומי** (WebSocket חי, ראה README) ו-**ענן** (serverless, tick כל דקה). המדריך הזה מקים את מצב הענן.

## מה כבר מוכן
- ✅ טבלאות ה-Supabase (`ta_signals`, `ta_signal_events`, `ta_engine_state`, `ta_settings`, `ta_llm_calls`) כבר קיימות בפרויקט שלך (`vcpcwovifmjzvxazelip`), נעולות ב-RLS — גישה רק דרך service key.
- ✅ `vercel.json` מכוון ל-region **fra1** (פרנקפורט) — חובה, כי Bybit חוסם IP אמריקאי.

## שלב 1 — פריסה ל-Vercel

1. היכנס ל-[vercel.com](https://vercel.com) → **Add New → Project** → ייבא את הריפו `MordyTe/Study` (בחר את ה-branch `claude/eth-usdt-trading-agent-at1bwd` או עשה merge קודם).
2. Framework Preset: **Other**. אל תגדיר Build Command (אין build — פייתון טהור).
3. לפני Deploy, הוסף **Environment Variables**:

| משתנה | ערך | מאיפה |
|--------|-----|-------|
| `SUPABASE_URL` | `https://vcpcwovifmjzvxazelip.supabase.co` | קבוע |
| `SUPABASE_SERVICE_KEY` | service_role key | Supabase → Project Settings → API keys → `service_role` (⚠️ הסודי, לא ה-anon) |
| `TELEGRAM_BOT_TOKEN` | הטוקן מ-@BotFather | טלגרם |
| `TELEGRAM_CHAT_ID` | ה-ID שלך מ-@userinfobot | טלגרם |
| `GEMINI_API_KEY` | מפתח ה-Gemini שלך | aistudio.google.com |
| `CRON_SECRET` | מחרוזת אקראית ארוכה (למשל `openssl rand -hex 24`) | אתה ממציא |
| `TELEGRAM_WEBHOOK_SECRET` | עוד מחרוזת אקראית | אתה ממציא |

4. **Deploy**. בסיום תקבל כתובת: `https://<project>.vercel.app`.
5. בדיקה: פתח `https://<project>.vercel.app` — הדשבורד אמור לעלות עם גרף חי (מ-Bybit REST). ה-badge יציג `cloud · polling`.

## ✅ צ'קליסט הפעלה (אחרי שהאתר עולה)

סדר הפעולות הנכון, הכל מהנייד:

1. **`/api/health`** — ודא: `boot_ok:true`, `region` שמתחיל ב-`fra`, `bybit.ok:true`, `supabase.ok:true`.
   אם `bybit.ok:false` ו-region אמריקאי → Vercel → Settings → Functions → Function Region → **Frankfurt** → Redeploy.
2. **Backoffice** (`/settings`) → הדבק את ה-`CRON_SECRET` בשדה ולחץ Save (נשמר רק בדפדפן שלך).
3. לחץ **🔗 Connect Telegram webhook** — מחבר את הבוט אוטומטית (בלי curl).
4. לחץ **▶️ Run tick now** — ה-tick הראשון ירוץ, ותקבל בטלגרם הודעת "🚀 Agent online".
5. הגדר את ה-**cron הדקתי** (סעיף למטה) — ומעכשיו המערכת חיה לבד.

## שלב 2 — ה-tick הדקתי (Hobby plan)

Vercel Hobby מגביל cron מובנה לפעם ביום, אז נשתמש בפינגר חיצוני חינמי:

1. הירשם ל-[cron-job.org](https://cron-job.org) (חינם).
2. צור Job חדש:
   - **URL**: `https://<project>.vercel.app/api/tick?secret=<CRON_SECRET>`
   - **Schedule**: every 1 minute
   - **Timeout**: 60 seconds
3. שמור. בתוך דקה-שתיים תראה בלוגים של Vercel קריאות tick, וב-`/api/state` יופיע `feed_ok: true`.

בדיקה ידנית: `curl "https://<project>.vercel.app/api/tick?secret=<CRON_SECRET>"` — אמור להחזיר JSON עם `"ok": true`.

> 💡 אם תשדרג ל-Vercel Pro: מחק את הפינגר, והוסף ל-`vercel.json`:
> ```json
> "crons": [{ "path": "/api/tick", "schedule": "* * * * *" }]
> ```
> (Vercel שולח אוטומטית `Authorization: Bearer <CRON_SECRET>`.)

## שלב 3 — חיבור הטלגרם (webhook)

הרץ פעם אחת (החלף את הערכים):

```bash
curl "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook?url=https://<project>.vercel.app/api/telegram&secret_token=<TELEGRAM_WEBHOOK_SECRET>"
```

עכשיו שלח `/status` לבוט — אמורה לחזור תשובה עם מצב השוק.

## שלב 4 — Backoffice בענן

`https://<project>.vercel.app/settings`:
- **API Keys** — מציג אילו משתני סביבה מוגדרים (עריכה דרך Vercel בלבד — serverless לא יכול לכתוב קבצים).
- **Runtime Settings** — סף קונפלואנס, אחוז סיכון, מצב וטו של Gemini ועוד — נשמרים ב-Supabase ונטענים **בטיק הבא, בלי redeploy**.

## מה שונה מהמצב המקומי (בכנות)

| יכולת | מקומי | ענן (Vercel) |
|--------|-------|---------------|
| עדכון נתונים | WebSocket חי (שניות) | tick כל דקה |
| CVD מזרם עסקאות | ✅ | ❌ (אין stream ב-serverless) |
| זרם חיסולים חי | ✅ | ❌ (funding/OI/LS עדיין פעילים דרך REST) |
| איתותי intraday | ✅ | ✅ מלא |
| איתותי scalp | ✅ | ✅ עם עיכוב עד דקה מהסגירה |
| Telegram | polling | webhook (יציב יותר) |
| Backtest | ✅ מקומי | רץ מקומית (לא בענן) |

עבור אינטרדיי — אין הבדל מעשי. עבור סקאלפינג 1m-5m — עיכוב של עד דקה הוא משמעותי; אם הסקאלפינג חשוב לך ברצינות, שקול בעתיד VPS קטן ($5/חודש) שמריץ את המצב המקומי המלא. הקוד תומך בשניהם ללא שינוי.

## אבטחה
- `/api/tick` מוגן ב-`CRON_SECRET`; ה-webhook מוגן ב-secret token של טלגרם; הבוט מגיב רק ל-chat ID שלך.
- טבלאות ה-DB נעולות ב-RLS — ה-anon key של Supabase לא רואה כלום.
- הדשבורד עצמו ציבורי לקריאה (מציג איתותים). אם תרצה להסתיר אותו לגמרי — אפשר להוסיף Vercel Password Protection (Pro) או להגיד לי ואוסיף Basic Auth.
