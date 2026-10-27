# מחקר שוק יום 0 — מה נמכר ב‑Apify Store ובמארקטפלייסים של MCP

**מחבר:** דניאל (agt-res1), מחקר. **תאריך גישה לכל המקורות:** 2026-10-27 (אלא אם צוין אחרת).
**שיטה:** חיפוש אינטרנט בלבד (WebSearch). גישה ישירה לדפים (WebFetch/curl) נחסמה בסביבה (DNS/proxy 403), לכן כל ציטוט מבוסס על קטעי תוצאות חיפוש ולא על קריאת הדף המלא. לא בוצע גירוד, לא בוצעה הרשמה.
**סימון:** [מאומת] = מופיע במקור ראשוני (דוקומנטציה/הודעה רשמית/דף מוצר) שנראה בתוצאות החיפוש. [הסקה] = פרשנות שלי או מקור צד‑שלישי בלבד. **אין בקובץ המלצות מחיר — תמחור הוא החלטת בעלים.**

## 1. טבלת מארקטפלייסים

| מארקטפלייס | מודל תמחור לקונה | חלק המפתח | נתוני שימוש ציבוריים? | URL | סטטוס |
|---|---|---|---|---|---|
| Apify Store | Pay‑per‑event (PPE, כולל "pay per result" כאירוע סינתטי של פריט dataset); חינם; השכרה חודשית **בוטלה** (אין פרסום חדש מ‑1.4, הפסקה מלאה 1.10.2026) | 80% מהכנסות האירועים; רק משתמשים בתוכנית בתשלום נספרים (`profit = 0.8*revenue − platform costs`) | כן: בכל דף Actor מוצגים total users, monthly users, runs, success rate | https://apify.com/store ; https://docs.apify.com/actors/monetize/pay-per-event ; https://docs.apify.com/actors/publishing/monetize/rental | [מאומת] (docs.apify.com, 2026-10-27) |
| Smithery | רישום חינמי; שרתים בתשלום לפי קריאה/מושב/מנוי; שכבת Marketplace עם "revenue share" לא מפורט | לא פורסם במקורות שנמצאו | חלקי: יש Registry API עם `totalCount`, ללא נתוני שימוש לכל שרת בתוצאות | https://smithery.ai ; https://smithery.ai/docs/use/registry | [הסקה] (ספירות צד‑ג' סותרות: 3,000+ / 4,700+ / 7,000+; aitoolsatlas.ai, everydev.ai, pub.towardsai.net) |
| MCPize | מנוי / לפי שימוש / חד‑פעמי, המפתח קובע מחיר; אחסון מנוהל (Cloud Run) | 80% לפי פרופיל ו‑FAQ של המפרסם; מקורות מ‑2026 מצטטים 85% — לא הוכרע | חלקי: "950+ שרתים, 450+ מפתחים" (עצמי) | https://mcpize.com | [הסקה] (godberrystudios.com, productcool.com, atlas.verdantix.com — כולם צד‑ג') |
| Glama | מדריך/אינדקס, לא מארקטפלייס תשלום | לא רלוונטי | כן: דף הבית מציג 82,574 servers / 16,184 connectors / 666,723 tools | https://glama.ai/mcp/servers | [הסקה] (ספירת דף הבית מצוטטת ע"י צד‑ג'; ספירה מיולי 2026: 50,845) |
| PulseMCP | מדריך; רישומים חדשים **מושהים** מ‑7.10.2026 בזמן שינוי ingestion | לא רלוונטי | כן: ~21,730 שרתים (אוקטובר 2026); 22,311 (16.7.2026); 20,115 (יולי 2026) — ספירות סותרות | https://www.pulsemcp.com/servers | [הסקה] (saascity.io, capitalandcompute.net) |
| Official MCP Registry (modelcontextprotocol) | מדריך רשמי; ללא תשלום | לא רלוונטי | 30,375 שרתים ייחודיים ב‑10.9.2026 | https://registry.modelcontextprotocol.io | [הסקה] (dev.to/amareswer "MCP registry by the numbers") |
| הפצה משנית של Apify | Actor מפורסם מופץ אוטומטית כ‑MCP ול‑Make/n8n | אותם 80% | — | https://apify.com/mcp/developers | [מאומת] (apify.com, 2026-10-27) |

**מסקנה 1 [הסקה]:** מתוך כל הרשימה, רק Apify (ובדרגה פחותה MCPize) סולק כסף למפתח עם נתונים ציבוריים. Smithery/Glama/PulseMCP הם ערוצי גילוי, לא ערוצי הכנסה.

## 2. 10 קטגוריות מובילות — Apify Store (אינדיקטור מספרי)

מקור: "The Scraping Report" (ניוזלטר Substack, מדגם ~10,000 actors, שבוע 23/2026, 7.6.2026, https://liaichi.substack.com/p/the-scraping-report-4e3). [הסקה] — צד‑ג', עמודות הטבלה נחלצו מטקסט לא מסודר, המספרים מקורבים.

| # | קטגוריה | actors במדגם | סה"כ משתמשים | משתמשים/actor (רוויה) |
|---|---|---|---|---|
| 1 | Videos | ~322 | ~3.2M | ~9,900 |
| 2 | Social Media | ~175 | ~2.26M | ~12,900 |
| 3 | SEO Tools | ~293 | ~1.69M | ~5,800 |
| 4 | Lead Generation | ~172 | ~1.3M | ~7,600 |
| 5 | Travel | — | גבוה (לא נחלץ) | — |
| 6 | E‑commerce | — | — | — |
| 7 | AI / MCP | ~448 | ~320K | ~710 |
| 8 | Developer Tools | ~626 | ~293K | ~470 |
| 9 | Jobs | — | — | — |
| 10 | Real Estate / Other | — | — | — |

**Actors בודדים לפי משתמשים [הסקה, use-apify.com/docs/best-apify-actors, "re‑verified 2026‑05‑26"]:** Google Maps Scraper 426K, Instagram Scraper 277K, TikTok Scraper 185K, Instagram Profile 139K, Google SERP 130K.
**שיעור actors חינמיים:** 5.7% (שבוע 23) לעומת 7.9% (שבוע 19) — "monetization‑first" [הסקה, אותו מקור].
**גודל החנות:** 26,929 actors (אפריל 2026, vantaige.io); 21,000+ (ראשית 2026, רישום khadinakbar); 30,000+ (use-apify.com) — סותר, לא רשמי [הסקה].

### קטגוריות ב‑MCP directories (ללא מספרים אמינים לכל קטגוריה)
Glama/awesome‑mcp: 20+ קטגוריות (Databases, Communication, Security, Developer Tools, Finance, Productivity, Data) [הסקה, mcp.so]. מדריכי "best of 2026" חוזרים על GitHub MCP, Context7, Postgres, Brave/Perplexity Search, Figma, Linear [הסקה, capitalandcompute.net, codewords.ai]. **לא נמצא** דירוג לפי שימוש אמיתי לכל שרת ב‑PulseMCP/Smithery — פער מידע.

## 3. 10 דוגמאות לכלים קטנים (לא סקרייפרים של רשתות חברתיות)

| # | כלי | מחיר שנראה | אינדיקטור שימוש | URL | תג |
|---|---|---|---|---|---|
| 1 | URL→PDF (rainminer/test-actor) | $1.49 / 1,000 PDFs (PPE) | 2 total users, 1 monthly | https://apify.com/rainminer/test-actor | [מאומת] |
| 2 | Currency Converter (pintostudio) | בתשלום (סכום לא נראה) | 620 runs, 3 active users | https://digitalbiztalk.com/tools/apify-actors/pintostudio/currency-converter | [הסקה] (צד‑ג') |
| 3 | Apify Store Scraper (jupri) | $0.10 / request | 148 total users, 1 monthly | https://apify.com/jupri/apify-store | [מאומת] |
| 4 | Smithery MCP Scraper (maximedupre) | $0.90 / 1,000 servers | לא נראה | https://apify.com/maximedupre/smithery-mcp | [מאומת] |
| 5 | Google Maps Reviews (solidcode) | $0.25 / 1,000 results | לא נראה | https://apify.com/solidcode/google-maps-reviews-scraper | [מאומת] |
| 6 | Deep Website Content Crawler (6sigmag) | $8.88 / 1,000 results | 494 monthly users | https://beta-securitybyobscurity.apify.com/6sigmag/deep-website-content-crawler/pricing | [הסקה] (דומיין beta) |
| 7 | Israel Companies Registrar Scraper (parseforge) | $7.50 / 1,000 results | 6–7 total users, 4 monthly | https://apify.com/parseforge/israel-companies-registrar-scraper | [מאומת] |
| 8 | Israel Sold Property Prices – GovMap (swerve/nadlan-deals) | $5–$10 / 1,000 (שני צילומים סותרים) | 16–21 total users, 6–7 monthly | https://apify.com/swerve/nadlan-deals | [מאומת] |
| 9 | Yad2 Scraper – Israel Classifieds API (dami_studio) | $1.20 / 1,000 listings + $0.001 start | לא נראה | https://apify.com/dami_studio/yad2-scraper | [מאומת] |
| 10 | Israel Business Directory (nickslam/israeliyp) | $0.50–$2.00 / 1,000 (שכבות) | 2 total users, 1 monthly | https://apify.com/nickslam/israeliyp-scraper | [מאומת] |

**תוספת — דוגמאות MCP‑as‑Actor:** Pandoc Universal MCP (whitewalk), B2B Lead Finder MCP (sueno31) — תבנית Apify מציגה דוגמת אירועים של $0.05 לקריאת tool ו‑$0.10 ל‑startup [מאומת, https://apify.com/templates/python-mcp-server].
**תצפית [הסקה]:** טווח מחירים נפוץ לכלי נתונים קטן: $0.25–$10 ל‑1,000 תוצאות; הכלים הישראליים הקיימים נמצאים בקצה הגבוה ($5–$10) עם משתמשים בודדים — שוק דק, לא מוכח.

## 4. פסקת מספרים

- **$563,000 בספטמבר 2025:** הודעה לעיתונות של Apify מ‑3.11.2025 — "distributed more than $563,000 to community developers ... in September 2025, six times the previous year's amount"; מצטבר "more than $4 million" מאז פתיחת Store. [מאומת] https://www.einnews.com/pr_news/863598206/apify-bets-1m-on-independent-developers-building-ai-s-missing-tools ; https://apify.com/challenge (2026-10-27). אין אימות עצמאי [הסקה].
- **מספר מפתחים:** לא פורסם מספר כולל של מפתחים מקבלי תשלום. ה‑$1M Challenge (נוב' 2025–ינו' 2026): 704 מפתחים, 3,329 Actors, 1,086 עמדו בתנאי הסף. [מאומת] https://apify.com/challenge
- **דף MCP למפתחים של Apify מצטט "$500k+ monthly payout" וציטוט מפתח "~$2,000/month"** — שיווקי [הסקה] https://apify.com/mcp/developers
- **חלק המפתח 80%:** docs.apify.com — PPE: "developer keeps 80% of event revenue"; השכרה (בוטלה): 80% מדמי השכירות. [מאומת] https://docs.apify.com/actors/monetize/pay-per-event
- **85%:** לא נמצא אצל Apify. 85% מופיע רק ל‑MCPize (מקורות 2026, לעומת 80% במקורות מוקדמים) [הסקה] https://godberrystudios.com/posts/how-to-monetize-mcp-servers-2026/
- **מקבל‑הכנסה עליון (2023):** $4,000+ MRR למפתח העצמאי המוביל — נתון ישן [הסקה] https://blog.apify.com/programmer-passive-income-web-scraping/
- **הקשר:** Apify מתכוונת לסיים compute‑time pricing באוקטובר 2026 [הסקה, automationatlas.io]; רק PPE זכאי ל‑"agentic payments" לפי בקשה [מאומת, docs.apify.com/actors/monetize].

## 5. רווי מול חסר

- **רווי [הסקה]:** Social Media, Google Maps (6+ actors מתחרים ב‑$1–$6/1,000), SERP, E‑commerce, LinkedIn/Leads. 12,900 משתמשים ל‑actor בסושיאל מול ~470 ב‑Dev Tools — אבל שם גם הביקוש ברובו למותגים גדולים.
- **חסר [הסקה]:** נתוני ממשל/רשומות ציבוריות — מפתחים בודדים מתארים זאת כנישה "underserved" (פרופילי slate_spool, oobr, malonestar ב‑Apify Store), עם קטלוגים קטנים ו‑30 משתמשים לכל פרופיל. כלים ישראליים: 3–21 משתמשים לכלי — ביקוש לא מוכח, אך כמעט ללא תחרות.
- **פער מידע:** אין נתוני שימוש לכל שרת ב‑MCP directories; לא ניתן למדוד ביקוש ל‑MCP מחוץ ל‑Apify.

## 6. המלצה: 5 כלים מועמדים ראשונים למקור (מדורגים)

| דירוג | כלי | למי | מתחרה קיים | איך נמדוד ביקוש |
|---|---|---|---|---|
| 1 | **רשם החברות IL — lookup/enrichment MCP+Actor** (מבוסס data.gov.il CKAN) | סוכני KYC/CRM, פינטק, עו"ד | parseforge ($7.50/1k, 7 users), foxlabs, bovi — כולם זעירים | users/monthly users בדף ה‑Actor; קריאות tool ב‑MCP; השוואה ל‑7 המשתמשים של המתחרה אחרי 30 יום |
| 2 | **שערי חליפין יציגים של בנק ישראל (SDMX) — MCP** | סוכני חשבונאות/חשבוניות/מס | מעטפות מסחריות (allratestoday, oanor) בתשלום; אין Actor | runs/day; יחס free→paid; חיפושים ב‑Store על "ILS"/"shekel" |
| 3 | **מכרזים ממשלתיים (מנהל הרכש ב‑data.gov.il + רמ"י)** | סוכני פיתוח עסקי, ספקים | remy-mcp (רמ"י בלבד, קוד פתוח), lentic_clockss (5 מקורות, בתשלום) | monthly users; מספר שאילתות סינון; פידבק ב‑Issues |
| 4 | **למ"ס סדרות (CPI/מדדים) — MCP** | סוכני פיננסים, חוזים צמודי מדד | israel-statistics-mcp (קוד פתוח, לא ממונטז) | קריאות tool; דירוג ב‑Glama/Smithery; השוואה לכוכבי GitHub של המתחרה |
| 5 | **Knesset OData — חוקים/ח"כים/הצבעות** | עיתונות, לובינג, אקדמיה | knesset-mcp (קוד פתוח), מראות HF | runs; שאילתות על חוקים אחרונים; לא צפוי תשלום גבוה — מועמד ל"חינם לגילוי" |

**5 נוספים (שורה אחת "למה" כל אחד) — להשלמת 10:**
6. GTFS ישראל (קווים/תחנות/לוחות זמנים) — קובץ רשמי יומי, Open Bus Stride מוכיח ביקוש מפתחים [הסקה].
7. OpenBudget/BudgetKey proxy — כבר קיים MCP קהילתי (קוד פתוח); הערך הוא אריזה בתשלום + אמינות [הסקה].
8. GovMap/nadlan deals — ביקוש הכי מוכח בין הכלים הישראליים (21 users) אך תנאי השימוש לא מאומתים — **בכפוף לממצאי day0-il-sources.md** [הסקה].
9. Hebrew text utilities (ניקוד/נורמליזציה/גימטריה/תאריך עברי) — אפס תחרות ב‑Store, ללא תלות במקור חיצוני [הסקה].
10. Tel Aviv Open Data (ArcGIS/CKAN) — רישיון ייחוס מפורש, API; נישה עירונית קטנה [הסקה].

**הסתייגות:** כל נתוני השימוש של כלים ישראליים הם חד‑ספרתיים/דו‑ספרתיים — אין הוכחה לביקוש, יש הוכחה להיעדר תחרות. יש למדוד 30 יום לפני השקעה בכלי שני.

## מקורות (נראו 2026-10-27)
- https://docs.apify.com/actors/monetize/pay-per-event · https://docs.apify.com/actors/publishing/monetize/rental · https://docs.apify.com/actors/monetize.md
- https://apify.com/challenge · https://www.einnews.com/pr_news/863598206/... · https://apify.com/mcp/developers · https://apify.com/templates/python-mcp-server
- https://liaichi.substack.com/p/the-scraping-report-4e3 · https://use-apify.com/docs/best-apify-actors · https://vantaige.io/ai-tool/apify
- https://smithery.ai/docs/use/registry · https://pub.towardsai.net/8-best-mcp-marketplaces-to-discover-mcp-servers-fb6cb082efcb · https://godberrystudios.com/posts/how-to-monetize-mcp-servers-2026/ · https://atlas.verdantix.com/vendors/mcpize
- https://claudemarket.ai/blog/best-mcp-server-directories · https://saascity.io/mcp-server-directories · https://capitalandcompute.net/blog/best-mcp-servers/ · https://dev.to/amareswer/the-mcp-registry-by-the-numbers-38nc
- דפי Actors: apify.com/rainminer/test-actor, jupri/apify-store, maximedupre/smithery-mcp, solidcode/google-maps-reviews-scraper, parseforge/israel-companies-registrar-scraper, swerve/nadlan-deals, swerve/nadlan-gov-deals, dami_studio/yad2-scraper, nickslam/israeliyp-scraper, foxlabs/israel-company-data, bovi/israel-companies-registrar, lentic_clockss/israel-data-search
