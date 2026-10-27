# QA_CHECKLIST — צ'קליסט בדיקה לכל כלי (מקור)

מסמך זה הוא הרשימה שכל כלי (MCP server / Apify actor) חייב לעבור **לפני** שה‑QA מסמנת `qa --pass`.
כותבת: תמר (agt-qa). הכלל: בודקים רק לפי הוכחה — מריצים בעצמנו, מנסים לשבור, ומתעדים בדיוק מה הרצנו ומה ראינו.
"זה עובד אצלי" אינו הוכחה. פריט אחד שנכשל = `--fail` עם הערה ספציפית (קלט, פקודה, פלט שהתקבל, פלט צפוי).

## 0. הכנה: הפקודות שה‑QA מריצה

כל הפקודות רצות מתוך `/home/user/Study/makor` עם `/home/user/Study/.venv/bin/python` (אותו interpreter שבו `verify` מריץ טסטים).
`<tool>` = שם תיקיית הכלי, למשל `product/tools/<tool>`.

```bash
cd /home/user/Study/makor
PY=/home/user/Study/.venv/bin/python

# 1) מבנה
ls product/tools/<tool>/server.py product/tools/<tool>/core.py product/tools/<tool>/README.md product/tools/<tool>/tests/

# 2) טסטים (אותה פקודה שה‑verify מריץ) — חייב לצאת 0
$PY -m pytest -q product/tools/<tool>/tests ; echo "exit=$?"

# 3) טסטים ללא רשת — ההוכחה שאין תלות באינטרנט (אחת מהשתיים)
unshare -rn $PY -m pytest -q product/tools/<tool>/tests ; echo "exit=$?"          # namespace בלי רשת
env HTTP_PROXY=http://127.0.0.1:9 HTTPS_PROXY=http://127.0.0.1:9 NO_PROXY= $PY -m pytest -q product/tools/<tool>/tests ; echo "exit=$?"

# 4) זמן ריצה (מתחת ל‑30 שניות)
time $PY -m pytest -q product/tools/<tool>/tests

# 5) דטרמיניזם — שתי ריצות, אותה תוצאה
$PY -m pytest -q -p no:randomly product/tools/<tool>/tests && $PY -m pytest -q product/tools/<tool>/tests

# 6) סודות
grep -rniE "api[_-]?key|secret|token|password|Bearer " product/tools/<tool> --include=*.py --include=*.json --include=*.md ; echo "grep exit=$? (1 = clean)"

# 7) server.py מייבא core ואין בו לוגיקה
grep -nE "^(from|import) .*core" product/tools/<tool>/server.py && wc -l product/tools/<tool>/server.py
```

כשמנסים קלט ידני, משתמשים ב‑`core` ישירות (לא דרך MCP), למשל:
`$PY -c "import sys; sys.path.insert(0,'product/tools/<tool>'); import core; print(core.<func>(''))"`

## 1. מבנה הכלי (structure)

- [ ] קיימים `server.py`, `core.py`, `tests/` (עם לפחות קובץ `test_*.py` אחד), `README.md` בתיקיית הכלי. **בדיקה:** פקודה 1 למעלה. **צפוי:** ארבעת הנתיבים קיימים, `ls` יוצא 0.
- [ ] `server.py` מייבא מ‑`core` ומגדיר רק את ממשק ה‑MCP (tool definitions, קריאה ל‑core, החזרת התוצאה). **בדיקה:** פקודה 7; קריאת הקובץ. **צפוי:** אין parsing/HTTP/חישוב ב‑server.py; כל הלוגיקה ב‑core.py.
- [ ] `core.py` ניתן לייבוא ללא תופעות לוואי (בלי קריאת רשת ב‑import, בלי כתיבה לדיסק). **בדיקה:** `unshare -rn $PY -c "import sys; sys.path.insert(0,'product/tools/<tool>'); import core"`. **צפוי:** exit 0, אין פלט.
- [ ] רשימת תלויות מינימלית (`requirements.txt` או סעיף ב‑README): רק מה שבאמת מיובא. **בדיקה:** `grep -hE "^(import|from) " product/tools/<tool>/*.py | sort -u` מול הרשימה. **צפוי:** אין תלות מיותרת, אין תלות חסרה.
- [ ] אין סודות בקוד: מפתחות API, tokens, סיסמאות, כתובות מייל פרטיות. **בדיקה:** פקודה 6. **צפוי:** `grep exit=1` (אין התאמות), או התאמות שהן רק שמות משתני סביבה (`os.environ.get(...)`) בלי ערך.

## 2. קלט (input edge cases)

לכל פריט: קוראים לפונקציה הראשית ב‑core עם הקלט. **הצפוי המשותף:** מחזירה dict `{"ok": false, "error": "<הודעה קריאה>", ...}` — לא exception, לא traceback, לא `None`, לא מחרוזת ריקה.

- [ ] מחרוזת ריקה `""`. **בדיקה:** `core.<func>("")`. **צפוי:** `{"ok": false, "error": "empty input"}` (או נוסח דומה) — ללא קריאת רשת.
- [ ] `None`. **בדיקה:** `core.<func>(None)`. **צפוי:** `ok: false` עם error מפורש, לא `TypeError`.
- [ ] טיפוס שגוי: `123`, `[]`, `{}`, `b"bytes"`. **בדיקה:** ארבע קריאות. **צפוי:** `ok: false`, error מציין את הטיפוס הצפוי (`"expected str"`).
- [ ] רווחים בלבד `"   "`, וגם `"\t\n"`. **בדיקה:** `core.<func>("   ")`. **צפוי:** מתנהג כמו מחרוזת ריקה — `ok: false`.
- [ ] קלט גדול: מעל 100,000 תווים (וגם 1 MB). **בדיקה:** `core.<func>("א" * 200_000)`. **צפוי:** `ok: false, error: "input too long (max N chars)"` — חוזר תוך פחות משנייה, בלי קריאת רשת, בלי MemoryError.
- [ ] מגבלת הגודל מתועדת ב‑README ותואמת לקוד. **בדיקה:** `grep -n "max" README.md` מול הקבוע ב‑core. **צפוי:** אותו מספר בשני המקומות.
- [ ] מספרים בקלט: `0`, שלילי, `"007"`, מספר עם פסיקים `"1,234"`, ספרות מלאות (`"١٢٣"`), float במקום int. **בדיקה:** קריאה עם כל ערך. **צפוי:** או תוצאה תקינה או `ok: false` — אף פעם לא ValueError.
- [ ] תאריכים (אם הכלי מקבל תאריך): `2026-02-30`, `31/12/2026` לעומת `2026-12-31`, שנה מעוברת עברית — אדר א' / אדר ב' (למשל 5784 ו‑5787), `29 בפברואר` בשנה לא מעוברת, timezone חסר. **בדיקה:** קריאה עם כל ערך. **צפוי:** תאריך לא חוקי → `ok: false`; אדר ב' לא מתמוטט ולא מתורגם בשקט לאדר א'.

## 3. עברית ויוניקוד (Hebrew / Unicode)

- [ ] ניקוד וטעמים (U+0591–U+05C7): `"שָׁלוֹם"`, `"בְּרֵאשִׁ֖ית"`. **בדיקה:** קריאה עם המילה המנוקדת ושוב בלי ניקוד. **צפוי:** אותה תוצאה (הכלי מנרמל ב‑NFC/מסיר ניקוד לפי הצורך), או `ok: false` מתועד — לא תוצאה שונה בשקט.
- [ ] גרש וגרשיים עבריים לעומת ASCII: `׳` (U+05F3) מול `'`, `״` (U+05F4) מול `"`. **בדיקה:** `"צה״ל"`, `"צה\"ל"`, `"ג׳ינס"`, `"ג'ינס"`. **צפוי:** שתי הצורות מניבות אותה תוצאה.
- [ ] אותיות סופיות: `"ךםןףץ"` באמצע מילה ובסופה. **בדיקה:** `"ירושלים"`, `"כסף"`. **צפוי:** לא מתנרמל בטעות (`ם`→`מ`) ואין שגיאה.
- [ ] עברית מעורבת באנגלית ובמספרים: `"MCP שרת 3 גרסה"`, `"iPhone 15 מחיר"`. **בדיקה:** קריאה. **צפוי:** המילים נשמרות בסדר הלוגי הנכון בפלט ה‑JSON; מספרים נשארים ASCII.
- [ ] סימני כיווניות: U+200E (LRM), U+200F (RLM), U+202A–U+202E (LRE/RLE/PDF/LRO/RLO), וגם U+2066–U+2069. **בדיקה:** `core.<func>("‏שלום‎")`, `core.<func>("‫שלום‬")`. **צפוי:** זהה לקלט `"שלום"`; הסימנים לא מופיעים בפלט ולא במפתחות של ה‑JSON.
- [ ] בייטים ב‑cp1255 / windows-1255 במקום UTF-8. **בדיקה:** `core.<func>("שלום".encode("cp1255"))` וגם מקור (mock) שמחזיר גוף ב‑windows-1255 עם header מתאים. **צפוי:** קלט bytes → `ok: false, error: "expected str"`; תגובת מקור ב‑cp1255 → מפוענחת נכון (`"שלום"`, לא `"ùìåí"` ולא `UnicodeDecodeError`).
- [ ] קידוד עברית ב‑URL: פרמטר עברי נשלח כ‑percent-encoding של UTF-8. **בדיקה:** ב‑mock של fetch, ללכוד את ה‑URL שנבנה עבור `"תל אביב"`. **צפוי:** `%D7%AA%D7%9C%20%D7%90%D7%91%D7%99%D7%91` (או `+` לרווח), לא עברית גולמית ולא `%E3`-משהו של cp1255.
- [ ] הפלט תמיד UTF-8 תקין ו‑JSON תקין: `json.dumps(result, ensure_ascii=False)` לא נכשל; אין `�` (replacement char) בפלט. **בדיקה:** `json.loads(json.dumps(r, ensure_ascii=False))`. **צפוי:** round-trip זהה.

## 4. מקור חיצוני (source failures)

כולם נבדקים עם mock של `fetch`/`requests`/`httpx` — בלי רשת אמיתית. **הצפוי המשותף:** `{"ok": false, "error": "...", "source": "<url>"}`, בלי traceback ב‑stderr, בלי exception למי שקורא.

- [ ] האתר לא עונה (ConnectionError / DNS failure). **בדיקה:** mock שמעלה `ConnectionError`. **צפוי:** `ok: false, error` מכיל `"unreachable"`/`"connection"`.
- [ ] Timeout. **בדיקה:** mock שמעלה `TimeoutError`; וגם לוודא ש‑`timeout=` מועבר במפורש לקריאת הרשת (grep ב‑core). **צפוי:** `ok: false, error: "timeout after Ns"`; יש timeout ≤ 30s בקוד.
- [ ] HTTP 5xx (500, 502, 503). **בדיקה:** mock עם `status_code=500`. **צפוי:** `ok: false, error` כולל את קוד הסטטוס.
- [ ] HTTP 404 ו‑403/429. **בדיקה:** mock עם 404. **צפוי:** `ok: false`, error מבדיל בין "לא נמצא" ל"נחסם/rate limit".
- [ ] JSON שבור / HTML במקום JSON. **בדיקה:** mock שמחזיר `"<html>Error</html>"` או `'{"a":'`. **צפוי:** `ok: false, error: "invalid JSON from source"` — לא `JSONDecodeError`.
- [ ] אפס תוצאות. **בדיקה:** mock שמחזיר `{"result": {"records": []}}`. **צפוי:** `{"ok": true, "results": [], "count": 0}` — תוצאה ריקה היא הצלחה, לא שגיאה.
- [ ] שינוי מבנה התשובה (schema change): מפתח חסר, מפתח ששמו השתנה, רשימה במקום dict. **בדיקה:** mock עם `{"result": {}}` ועם `{"records": [...]}` ברמה העליונה. **צפוי:** `ok: false, error: "unexpected response schema (missing key X)"` — לא `KeyError`.
- [ ] תגובה ענקית מהמקור (למשל 50 MB). **בדיקה:** mock עם גוף של `"x" * 50_000_000`. **צפוי:** נחתך או נדחה עם `ok: false` תוך זמן סביר; אין MemoryError.

## 5. טסטים (tests)

- [ ] `python -m pytest -q product/tools/<tool>/tests` יוצא 0. **בדיקה:** פקודה 2. **צפוי:** שורה אחרונה `N passed`, `exit=0`, אפס `skipped`/`xfail` לא מוסברים.
- [ ] הטסטים רצים ללא רשת — fetch מוחלף ב‑mock/monkeypatch. **בדיקה:** פקודה 3 (unshare או proxy מת). **צפוי:** אותו `N passed`, exit 0. אם נכשל ללא רשת → `--fail` מיידי ("test depends on live network").
- [ ] אין קריאה חיה ב‑tests: `grep -rnE "requests\.(get|post)|httpx\.|urlopen" product/tools/<tool>/tests` מחזיר רק שורות של mock/patch. **צפוי:** אין קריאה חיה.
- [ ] דטרמיניסטיים: שתי ריצות רצופות = אותה תוצאה; אין תלות ב‑`datetime.now()`, ב‑random או בסדר של set/dict ללא sort. **בדיקה:** פקודה 5 + `grep -n "now()\|random" core.py`. **צפוי:** זהה פעמיים; זמן נוכחי מוזרק כפרמטר או נקבע ב‑test.
- [ ] fixtures אמיתיים: קובץ ב‑`tests/fixtures/` שנשמר מהמקור האמיתי, עם הערת מקור — URL מלא ותאריך הורדה (`# source: https://... fetched 2026-10-27`). **בדיקה:** `ls tests/fixtures; head -3 tests/fixtures/*`. **צפוי:** לפחות fixture אחד תקין ואחד "שבור" (לשגיאות).
- [ ] זמן ריצה כולל מתחת ל‑30 שניות. **בדיקה:** פקודה 4. **צפוי:** `real` < 30s.
- [ ] יש טסט לכל פריט בסעיפים 2–4 (קלט ריק, None, גדול, ניקוד, גרש, כיווניות, cp1255, timeout, 500, 404, JSON שבור, אפס תוצאות, schema). **בדיקה:** `grep -c "def test_" tests/*.py` וקריאת שמות הטסטים. **צפוי:** כל מקרה קצה מכוסה בשם טסט מזהה.
- [ ] הפלט של כל קריאה מוצלחת הוא dict עם `ok: true` ומבנה קבוע שמתועד ב‑README; שגיאות הן `ok: false` + `error` (str). **בדיקה:** `assert set(r) >= {"ok"}` בטסטים. **צפוי:** אין פונקציה שמחזירה לפעמים list ולפעמים dict.

## 6. תאימות ומסמכים (compliance & docs)

- [ ] `robots.txt` של המקור מתועד ב‑README: הכתובת, תאריך הבדיקה, והשורות הרלוונטיות (Allow/Disallow/Crawl-delay) או ציון שהמקור הוא API רשמי. **בדיקה:** `grep -n -i "robots" README.md`. **צפוי:** סעיף קיים; הנתיבים שהכלי קורא אינם ב‑Disallow.
- [ ] תנאי השימוש / רישיון המקור מתועדים (למשל רישיון data.gov.il) וקצב קריאות (rate limit / Crawl-delay) מכובד בקוד. **בדיקה:** `grep -n -i "license\|terms\|רישיון\|rate" README.md core.py`. **צפוי:** מצוין בשני המקומות; אין לולאת קריאות ללא sleep/limit.
- [ ] README דו‑לשוני: סעיף באנגלית וסעיף בעברית, שניהם עם אותה דוגמת קריאה ואותו פלט. **בדיקה:** קריאה; `grep -c "```" README.md`. **צפוי:** לפחות דוגמת קוד אחת לכל שפה.
- [ ] דוגמת הקריאה ב‑README רצה כפי שהיא ומחזירה את הפלט המודפס (בתוך mock או על fixture). **בדיקה:** העתקה והדבקה של הדוגמה ל‑`$PY -c "..."`. **צפוי:** פלט זהה (עד לשדות שמסומנים כדינמיים).
- [ ] README מתעד: שם הכלי ב‑MCP, פרמטרים וטיפוסיהם, מגבלת גודל קלט, פורמט שגיאה (`{ok:false, error}`), תלויות, איך מריצים טסטים. **בדיקה:** קריאה. **צפוי:** כל ששת הסעיפים קיימים.
- [ ] אין במסמכים או בקוד הבטחות משפטיות, מחירים, או טענת "מדויק" ללא מקור (כלל הברזל של COMPANY.md). **בדיקה:** `grep -n -iE "guarantee|מובטח|\\$[0-9]|price|מחיר" README.md`. **צפוי:** אין התאמות (או התאמות שאינן התחייבות).

## 7. איך ה‑QA מדווחת

- [ ] כל פריט למעלה סומן `[x]` עם הפקודה/הקלט שהורץ והפלט שנצפה — נשמר בהערות ה‑QA (או בקובץ `product/tools/<tool>/QA_NOTES.md` שהעובד לא עורך).
- [ ] **pass** — רק כאשר **כל** הפריטים עברו, כולל הריצה ללא רשת:
  `/home/user/Study/.venv/bin/python tools/company.py qa --id <task-id> --pass --by agt-qa --notes "pytest -q <path>: N passed in Xs (exit 0, also under unshare -rn); checked: empty/None/200k chars, niqqud/geresh/bidi/cp1255, timeout/500/404/bad JSON/schema; robots.txt documented; README he+en example runs"`
- [ ] **fail** — בפריט הראשון שנכשל; ההערה חייבת לכלול קלט מדויק, פקודה, פלט שהתקבל ופלט צפוי, כדי שהעובד יוכל לשחזר:
  `/home/user/Study/.venv/bin/python tools/company.py qa --id <task-id> --fail --by agt-qa --notes "core.search(None) raised TypeError (expected {ok:false,error}); test_timeout fails under unshare -rn (live call to data.gov.il); robots.txt not in README"`
- [ ] ה‑QA לא מתקנת קוד — מחזירה לעובד. ה‑QA לא סוגרת משימה — רק `tools/company.py verify` סוגר, אחרי `qa --pass`.
- [ ] אחרי `verify`: אם כלי שעבר נשבר מאוחר יותר, זה נרשם כ‑KPI שלילי של ה‑QA — ולכן אין קיצורי דרך: בלי ריצה ללא רשת אין pass.
