# יום 0 — שמות, מועמדי דומיין ותבנית README

כותבת: ליאור (agt-wr1). תאריך: 2026-10-27. משימה: task-e15ab3.
מסמך זה הוא קריאה בלבד: לא נרשם שום דומיין, לא נפתח שום חשבון. כל החלטה על שם או דומיין — ורכישתו — היא של הבעלים דרך `state/inbox.json`.

## שיטה ומגבלות הבדיקה (לקרוא לפני הטבלה)
- ניסיתי בדיקת RDAP ציבורית (קריאה בלבד) מול רשמי ה‑TLD: `rdap.verisign.com` (.com), `rdap.nic.google` (.dev/.app), `rdap.identitydigital.services` (.io/.tools), `rdap.nic.ai` (.ai), וגם whois על פורט 43 מול `whois.verisign-grs.com`. כל הבקשות נחסמו בסביבת הסוכן (proxy מחזיר 403 / DNS לא נפתר). לכן **כל הסטטוסים בטבלה הם "לא ידוע"** — לא מצאתי דרך לקבוע "פנוי" או "תפוס" כעובדה.
- מה שכן נבדק: חיפוש אינטרנט אחר כל דומיין כמחרוזת מדויקת. אף תוצאה לא הצביעה על אתר פעיל באף אחד מהמועמדים. זה אינדיקטור חלש בלבד: דומיין יכול להיות רשום (parking, הפניה, מייל) בלי אתר מאונדקס.
- איך הבעלים בודק בדקה, בלי להירשם: https://lookup.icann.org/ (RDAP רשמי, לכל ה‑TLDs הגלובליים). לדומייני .il: שירות ה‑whois של איגוד האינטרנט הישראלי (isoc.org.il). לרשום את התאריך ליד כל תוצאה.

## חלק א — שם המותג
- **מועמד מוביל: מקור / Makor.** נשאר לפי החלטת ישיבת הייסוד (`state/decisions.json`, יום 0) עד שתהיה בדיקת דומיין.
- כתיב באנגלית: **Makor** — התעתיק הנפוץ (ראו Makor Rishon, Makor Group, Makor Chaim). זו הצורה שמפתח יקליד. **Maqor** הוא תעתיק אקדמי (ק = q) — נכון מדעית, אף אחד לא מחפש אותו. **Mekor** הוא הצורה הסמוכה ("מְקוֹר") ומתערבב בגוגל עם "Mekorot" (חברת המים) — להימנע. המלצה: `makor`, אותיות קטנות בכל handle (GitHub, PyPI, Smithery, Apify).
- התנגשויות שם קיימות (נבדק בחיפוש, 2026-10-27): עיתון "מקור ראשון" (makorrishon.co.il, https://en.wikipedia.org/wiki/Makor_Rishon); Makor Group / Makor Capital, ברוקראז' (makor-capital.com); Makor Chaim, מוסד חינוכי (makorchaim.org); MAKOR Energy Solutions (https://www.solarplaza.com/organization/10011/makor-energy-solutions/); חבילת TeX בשם `makor` לסידור עברית ב‑CTAN. המשמעות: המילה "makor" לבדה צפופה בחיפוש, ולכן ב‑handles ובמארקטפלייסים מומלץ תמיד צירוף — `makor-data` או `makor-tools` — ולא `makor` לבד.
- לא נעשתה בדיקת סימן מסחר. אם הבעלים רוצה — מאגר סימני המסחר של רשות הפטנטים (gov.il/ilpo) פתוח לחיפוש. אין בכך צורך לפני הדולר הראשון.
- חלופות אם כל דומייני makor ייפלו (לא נבדקו): `makordata` כמותג בפני עצמו ("Makor Data"), `makorlabs`. לא מוצע שם חדש לגמרי — זה מחליף החלטה שכבר התקבלה ולא פותר את בעיית הדומיין.

## חלק א — טבלת מועמדי דומיין
| # | דומיין | סטטוס (RDAP/whois) | תאריך בדיקה | מה כן ידוע / הערה |
|---|--------|---------------------|-------------|--------------------|
| 1 | makor.tools | לא ידוע — RDAP חסום | 2026-10-27 | חיפוש: אין אתר מאונדקס. TLD תיאורי למוצר ("כלים"). מופיע כבר ב‑OWNER_SETUP.md. |
| 2 | makordata.com | לא ידוע — RDAP חסום | 2026-10-27 | חיפוש: אין אתר מאונדקס. בלי מקף — קל להגיד בקול ולהקליד. |
| 3 | makor-data.com | לא ידוע — RDAP חסום | 2026-10-27 | חיפוש: אין אתר מאונדקס. גיבוי ל‑#2. מופיע ב‑OWNER_SETUP.md. |
| 4 | makor.dev | לא ידוע — RDAP חסום | 2026-10-27 | חיפוש: אין אתר מאונדקס. .dev מחייב HTTPS (HSTS preload) — לא בעיה לנו. |
| 5 | makor-data.io | לא ידוע — RDAP חסום | 2026-10-27 | חיפוש: אין אתר מאונדקס. .io נפוץ אצל כלי מפתחים; יקר יותר מ‑.com בדרך כלל (לא נבדק מחיר). |
| 6 | makordata.io | לא ידוע — RDAP חסום | 2026-10-27 | חיפוש: אין אתר מאונדקס. וריאציה של #5 בלי מקף. |
| 7 | getmakor.com | לא ידוע — RDAP חסום | 2026-10-27 | חיפוש: אין אתר מאונדקס. תחילית "get" מתאימה למוצר להורדה, פחות לחברת נתונים. |
| 8 | makor.io | לא ידוע — RDAP חסום | 2026-10-27 | חיפוש: אין אתר מאונדקס. קצר; סיכוי גבוה שתפוס (הסקה מאורך השם, לא עובדה). |
| 9 | makor.com | לא ידוע — RDAP חסום | 2026-10-27 | חיפוש: אין אתר מאונדקס. מילה של 5 אותיות ב‑.com — ההנחה בישיבה הייתה "כמעט בטוח תפוס"; לא אומת. |
| 10 | makor.co.il | לא ידוע — whois isoc.org.il לא נבדק (חסום) | 2026-10-27 | מתאים לקהל ישראלי בלבד; המארקטפלייסים גלובליים. גיבוי בלבד. |

לא נכלל: makor.ai — TLD יקר ולא תיאורי לנתונים; לבדוק רק אם הבעלים רוצה אותו במפורש.

## חלק א — המלצה (2 מובילים)
1. **makor.tools** — אומר מה אנחנו מוכרים (כלים), לא מתחרה בחיפוש עם העיתון והברוקראז', ומתיישב עם ה‑handle `makor-tools`.
2. **makordata.com** — .com מוכר לכל מפתח, "data" מתאר את הבידול (נתונים ישראליים). אם תפוס: makor-data.com.
**ההחלטה והרכישה הן של הבעלים בלבד, דרך `state/inbox.json`.** הסוכנים לא נרשמים, לא קונים ולא "שומרים" דומיין. הבעלים בודק ב‑lookup.icann.org, רושם תאריך, ומחליט.

## חלק ב — מוסכמת שמות לכלים
- **שפה:** אנגלית בלבד. מפתח בברלין או בבנגלור מחפש "hebrew text mcp", לא "מקור" (החלטת ישיבה, agt-mkt).
- **צורה:** `snake_case`, אותיות קטנות, 2–3 מילים, שם עצם תיאורי. שם התיקייה `product/tools/<name>` = שם שרת ה‑MCP = ה‑slug במארקטפלייס (כשהמארקטפלייס לא מקבל קו תחתון: `hebrew-text`).
- **בלי:** סופרלטיבים (`best_`, `pro`, `ultimate`, `smart`), בלי `mcp`/`server` בשם (זו הקטגוריה, לא השם), בלי שם החברה בשם הכלי.
- **תחיליות קבועות:** `il_` לכלים על מקור נתונים ישראלי (`il_open_data`, בעתיד `il_nadlan`, `il_knesset`), `hebrew_` לכלי שפה (`hebrew_text`). כלי גלובלי — בלי תחילית.
- **שמות פונקציות (MCP tools):** `verb_noun` ב‑snake_case: `search_datasets`, `get_dataset`, `search_records`, `parse_hebrew_date`. חריג מקובל: שם עצם יחיד כשהפעולה ברורה (`normalize`, `gematria`).
- **דוגמאות:** טוב — `hebrew_text`, `il_open_data`, `il_exchange_rates`, `gtfs_stops`. רע — `HebrewTextPro`, `best_israel_data`, `makor_hebrew_mcp_server`, `superfast_ckan`.

### hebrew_text
- שם תצוגה: **Hebrew Text**
- תיאור EN (≤120 תווים): `Normalize Hebrew text (strip nikud, unify quotes), parse Hebrew dates, compute gematria. Pure Python, no network.`
- תיאור HE: `נרמול טקסט עברי (הסרת ניקוד, איחוד גרשיים ומרכאות), פירוק תאריך עברי וחישוב גימטריה. פייתון טהור, בלי רשת.`
- 5 מילות חיפוש: `hebrew text normalization`, `remove nikud`, `hebrew date parser`, `gematria calculator`, `hebrew unicode mcp`
- התנגשויות שנמצאו (2026-10-27): שרתי MCP קיימים לעברית הם קורפוסים תורניים (Sefaria, Otzaria, textual-criticism) — לא נרמול יוניקוד. לא נמצא שרת בשם `hebrew_text` או `hebrew-text` בחיפוש; לא נבדק ב‑PyPI ישירות (חסום). מקורות: https://glama.ai/mcp/servers/NoveltyDreams/textual-criticism-mcp , https://mcp.so/servers/sefaria-mcp-server

### il_open_data
- שם תצוגה: **Israel Open Data (data.gov.il)**
- תיאור EN (≤120 תווים): `Search datasets and query records on data.gov.il, Israel's CKAN open-data portal. stdlib only, offline tests.`
- תיאור HE: `חיפוש מאגרים ושליפת רשומות מ‑data.gov.il, פורטל הנתונים הפתוחים של ממשלת ישראל (CKAN). stdlib בלבד, טסטים בלי רשת.`
- 5 מילות חיפוש: `data.gov.il api`, `israel open data`, `ckan mcp`, `israel government datasets`, `datastore_search israel`
- התנגשויות שנמצאו (2026-10-27): קיימים לפחות שני שרתי MCP ל‑data.gov.il — `DavidOsherProceed/data-gov-il-mcp` (Node.js) ו‑`aviveldan/datagov-mcp` (Python/FastMCP, כולל package_search/package_show/datastore_search). מקורות: https://glama.ai/mcp/servers/@DavidOsherProceed/data-gov-il-mcp , https://glama.ai/mcp/servers/@aviveldan/datagov-mcp . המשמעות ל‑README שלנו: לא לכתוב "הראשון" או "היחיד". לכתוב רק הבדלים שניתן לבדוק בקוד: תלויות (stdlib + mcp), טסטים בלי רשת על fixtures אמיתיים, שגיאות כאובייקט `{ok:false}`, מגבלת קלט מתועדת.

## חלק ג — תבנית README וטון דיבור
- התבנית: `product/tools/README_TEMPLATE.md`. סדר קבוע: שם ושורת תיאור → What it does → Install / Run → Tools & parameters (טבלה) → Example call → Example output → Limits & data sources (כולל שורות robots.txt מצוטטות עם תאריך, ו‑URL + תאריך לכידה של כל fixture) → Errors → Changelog. אחר כך מראה עברי מלא של כל הסעיפים, באותו סדר. אנגלית קודם כי המארקטפלייסים באנגלית.
- העברית היא מראה, לא תקציר: כל סעיף שקיים באנגלית קיים בעברית. קוד, שמות פרמטרים, מפתחות JSON וקודי שגיאה נשארים באנגלית בשני החלקים.
- **טון:** כותבים כמו מפתח שמסביר למפתח. משפט ראשון = מה הכלי עושה. בלי "the best", "powerful", "seamless", "AI‑powered", "blazing fast", "100%", "guaranteed", "enterprise‑grade". בעברית: בלי "המוביל", "המתקדם ביותר", "מושלם".
- **כל טענה ניתנת לבדיקה:** מספר מגיע עם תאריך ומקור (URL או פקודה). "עובד offline" מותר רק אם הטסטים מוכיחים שאין קריאת רשת. "תומך ב‑X" מותר רק אם יש טסט ל‑X.
- **בלי הבטחות ביצועים או דיוק:** לא "מהיר", לא "מדויק". אם נמדד — לכתוב את המדידה, את התאריך ואת הסביבה. אם לא נמדד — לא לכתוב.
- **מה לא נתמך — כותבים במפורש.** למשל ב‑hebrew_text: המרה לתאריך לועזי לא נתמכת. סעיף Limits אינו אופציונלי.
- **מילון מונחים קבוע EN→HE:** dataset = מאגר נתונים; resource = משאב; record = רשומה; tool = כלי; parameter = פרמטר; limit = מגבלה; error code = קוד שגיאה; fixture = fixture (לא מתרגמים); MCP server = שרת MCP.
- **מה בודקים לפני qa --pass:** כל סעיף קיים בשתי השפות; דוגמת הקריאה רצה כפי שהיא ומחזירה את הפלט המודפס; טבלת הכלים תואמת לחתימות ב‑core.py; שורות robots.txt מצוטטות עם תאריך; כל fixture עם URL ותאריך.
