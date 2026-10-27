# hebrew_text

Pure-Python utilities for Hebrew text that AI agents get wrong: normalize spelling marks and quotes, parse a Hebrew date into its parts, and compute gematria.

## Install

```bash
pip install mcp          # the only non-stdlib dependency (server only)
python server.py         # MCP server over stdio
```

Tests need only pytest (no `mcp`, no network):

```bash
python -m pytest -q product/tools/hebrew_text/tests
```

## Tools

| Tool | Parameters | Returns |
|------|------------|---------|
| `normalize` | `text: str` | `{"ok": true, "text": str}` |
| `parse_hebrew_date` | `text: str` | `{"ok": true, "day": int, "month": str, "month_index": int, "month_en": str, "year": int\|null, "leap_year": bool\|null}` |
| `gematria` | `text: str` | `{"ok": true, "value": int, "letters": int, "ignored": [str]}` |

**normalize** removes niqqud and cantillation marks (U+0591–U+05C7, except the maqaf ־), removes directional marks (U+200E, U+200F, U+202A–U+202E, U+2066–U+2069), converts Hebrew geresh ׳ / gershayim ״ and curly quotes ‘ ’ “ ” to ASCII `'` and `"`, and collapses runs of spaces/tabs to one space (newlines are kept; the result is trimmed).

**parse_hebrew_date** finds the first `day month [year]` sequence: day as a Hebrew numeral (`כ״ג`, `כ"ג`, `כג`) or digits (1–30); month with or without the ב/ל preposition, including `אדר א׳`/`אדר ב׳` (also `אדר ראשון`/`אדר שני`) and common spellings (`חשון`, `מרחשוון`, `כסליו`, `סיון`, `איר`, `מנחם־אב`); year as a Hebrew numeral with or without gershayim (`תשפ״ו`, `תשפו`, `ה׳תשפ״ו`, `התשפ״ו`) or digits. A year without thousands gets +5000. `month_index` is Tishrei-first and stable: תשרי 1, חשוון 2, כסלו 3, טבת 4, שבט 5, אדר / אדר א׳ 6, ניסן 7, אייר 8, סיוון 9, תמוז 10, אב 11, אלול 12, אדר ב׳ 13. `leap_year` is computed from the year (19-year cycle) and is `null` when the year is absent.

**gematria** uses standard values (א=1 … י=10, כ=20 … ק=100, ר=200, ש=300, ת=400); final letters (ך ם ן ף ץ) equal their regular forms. Whitespace, points, geresh/gershayim and bidi marks are skipped silently; any other non-Hebrew character is skipped and reported once in `ignored`, in order of first appearance.

Errors are never raised; they are returned as `{"ok": false, "error": <code>, "message": <text>}`:

| `error` | When |
|---------|------|
| `invalid_input` | `text` is `None` or not a string |
| `input_too_large` | more than 100,000 characters (`limit` field included) |
| `invalid_date` | `parse_hebrew_date` only: no date found, day not 1–30 (e.g. `ל״ב בתשרי`), or day 30 in a 29-day month |
| `internal_error` | unexpected failure (should not happen; please report) |

An empty string returns `ok: true` with an empty result (`"text": ""`, `"value": 0`, or all date fields `null`).

## Example

Call:

```json
{"tool": "parse_hebrew_date", "arguments": {"text": "כ״ג בתשרי תשפ״ו"}}
```

Result:

```json
{"ok": true, "day": 23, "month": "תשרי", "month_index": 1, "month_en": "Tishrei", "year": 5786, "leap_year": false}
```

More: `normalize("שָׁלוֹם “עוֹלָם”")` → `{"ok": true, "text": "שלום \"עולם\""}`; `gematria("תשפ״ו")` → `{"ok": true, "value": 786, "letters": 4, "ignored": []}`.

## Limits, assumptions and sources

* Input limit: 100,000 characters per call. Pure Python, stdlib only, no network.
* **Conversion to a Gregorian date is not supported** (out of scope for this version).
* Assumptions made where the spec was open:
  * The maqaf ־ (U+05BE) is kept by `normalize`: it is a hyphen, not a mark, and removing it would merge words.
  * Low/reversed curly quotes ‚ ‛ „ ‟ and the bidi isolates U+2066–U+2069 / U+061C are treated like their spec'd siblings.
  * `parse_hebrew_date` is lenient about surrounding text (weekday, commas) and strict about the numerals: a day must be a canonical numeral 1–30 (ט״ו/ט״ז accepted), a year must be a well-formed numeral (hundreds, tens, units) so ordinary words are not mistaken for years. Month lengths are checked only for months that always have 29 days (טבת, אייר, תמוז, אלול, אדר ב׳; plain אדר in a non-leap year). Plain `אדר` in a leap year keeps index 6 and is not reinterpreted. Adar I/II are not validated against the year.
  * `year` is `null` (not an error) when the text has no year.
  * Output month names are canonical modern spellings (`חשוון`, `סיוון`, `אדר ב׳` with a Hebrew geresh); `month_en` gives the English name.
  * `gematria` is mispar hechrechi only (no mispar gadol / katan).
* Sources: Unicode Hebrew block (U+0590–U+05FF) and General Punctuation block definitions; standard gematria table; Hebrew calendar leap-year rule `(7·year + 1) mod 19 < 7`.

---

# hebrew_text (עברית)

פונקציות פייתון טהורות לטקסט עברי שסוכני AI נכשלים בו: נרמול ניקוד ומרכאות, פירוק תאריך עברי לרכיביו, וחישוב גימטריה.

## התקנה

```bash
pip install mcp          # התלות היחידה מחוץ לספריית התקן (לשרת בלבד)
python server.py         # שרת MCP על stdio
```

הטסטים דורשים רק pytest (לא `mcp`, בלי רשת):

```bash
python -m pytest -q product/tools/hebrew_text/tests
```

## כלים

| כלי | פרמטרים | פלט |
|-----|---------|-----|
| `normalize` | `text: str` | `{"ok": true, "text": str}` |
| `parse_hebrew_date` | `text: str` | `{"ok": true, "day": int, "month": str, "month_index": int, "month_en": str, "year": int\|null, "leap_year": bool\|null}` |
| `gematria` | `text: str` | `{"ok": true, "value": int, "letters": int, "ignored": [str]}` |

**normalize** מסיר ניקוד וטעמים (U+0591–U+05C7, למעט המקף ־), מסיר סימני כיווניות (U+200E, U+200F, U+202A–U+202E, U+2066–U+2069), מאחד גרש ׳ / גרשיים ״ ומרכאות מסולסלות ‘ ’ “ ” למרכאות ASCII `'` ו‑`"`, ומכווץ רצפי רווחים/טאבים לרווח אחד (שורות חדשות נשמרות; התוצאה נחתכת בקצוות).

**parse_hebrew_date** מוצא את הרצף הראשון `יום חודש [שנה]`: יום כספרה עברית (`כ״ג`, `כ"ג`, `כג`) או כספרות (1–30); חודש עם או בלי ב'/ל' היחס, כולל `אדר א׳`/`אדר ב׳` (גם `אדר ראשון`/`אדר שני`) וכתיבים נפוצים (`חשון`, `מרחשוון`, `כסליו`, `סיון`, `איר`, `מנחם־אב`); שנה כספרה עברית עם או בלי גרשיים (`תשפ״ו`, `תשפו`, `ה׳תשפ״ו`, `התשפ״ו`) או כספרות. שנה ללא אלפים מקבלת +5000. `month_index` מתחיל בתשרי ויציב: תשרי 1, חשוון 2, כסלו 3, טבת 4, שבט 5, אדר / אדר א׳ 6, ניסן 7, אייר 8, סיוון 9, תמוז 10, אב 11, אלול 12, אדר ב׳ 13. `leap_year` מחושב מהשנה (מחזור 19 שנים) והוא `null` כשאין שנה.

**gematria** לפי המספר ההכרחי (א=1 … י=10, כ=20 … ק=100, ר=200, ש=300, ת=400); אותיות סופיות (ך ם ן ף ץ) שוות לרגילות. רווחים, ניקוד, גרש/גרשיים וסימני כיווניות נדלגים בשקט; כל תו אחר שאינו עברי נדלג ומדווח פעם אחת ב‑`ignored`, לפי סדר ההופעה.

שגיאות לא נזרקות כ‑exception אלא מוחזרות כ‑`{"ok": false, "error": <קוד>, "message": <טקסט>}`:

| `error` | מתי |
|---------|-----|
| `invalid_input` | `text` הוא `None` או לא מחרוזת |
| `input_too_large` | מעל 100,000 תווים (כולל שדה `limit`) |
| `invalid_date` | ב‑`parse_hebrew_date` בלבד: לא נמצא תאריך, יום לא בטווח 1–30 (למשל `ל״ב בתשרי`), או יום 30 בחודש של 29 ימים |
| `internal_error` | תקלה בלתי צפויה (לא אמור לקרות; נא לדווח) |

מחרוזת ריקה מחזירה `ok: true` עם תוצאה ריקה (`"text": ""`, `"value": 0`, או כל שדות התאריך `null`).

## דוגמה

קריאה:

```json
{"tool": "parse_hebrew_date", "arguments": {"text": "כ״ג בתשרי תשפ״ו"}}
```

פלט:

```json
{"ok": true, "day": 23, "month": "תשרי", "month_index": 1, "month_en": "Tishrei", "year": 5786, "leap_year": false}
```

עוד: `normalize("שָׁלוֹם “עוֹלָם”")` ← `{"ok": true, "text": "שלום \"עולם\""}`; `gematria("תשפ״ו")` ← `{"ok": true, "value": 786, "letters": 4, "ignored": []}`.

## מגבלות, הנחות ומקורות

* מגבלת קלט: 100,000 תווים לקריאה. פייתון טהור, ספריית התקן בלבד, בלי רשת.
* **המרה לתאריך לועזי אינה נתמכת** (מחוץ להיקף של גרסה זו).
* הנחות שנעשו היכן שהמפרט היה פתוח:
  * המקף ־ (U+05BE) נשמר ב‑`normalize`: הוא מקף ולא סימן ניקוד, והסרתו הייתה מדביקה מילים.
  * מרכאות תחתונות/הפוכות ‚ ‛ „ ‟ וסימני הבידוד U+2066–U+2069 / U+061C מטופלים כמו אחיהם שבמפרט.
  * `parse_hebrew_date` סלחני לטקסט מסביב (יום בשבוע, פסיקים) ומחמיר בספרות: יום חייב להיות ספרה קנונית 1–30 (ט״ו/ט״ז מתקבלים), שנה חייבת להיות ספרה תקינה (מאות, עשרות, יחידות) כדי שמילים רגילות לא ייחשבו לשנה. אורכי חודשים נבדקים רק לחודשים שתמיד בני 29 ימים (טבת, אייר, תמוז, אלול, אדר ב׳; אדר רגיל בשנה פשוטה). `אדר` רגיל בשנה מעוברת נשאר באינדקס 6 ואינו מפורש מחדש. אדר א׳/ב׳ אינם מאומתים מול השנה.
  * `year` הוא `null` (לא שגיאה) כשאין שנה בטקסט.
  * שמות החודשים בפלט בכתיב מלא קנוני (`חשוון`, `סיוון`, `אדר ב׳` עם גרש עברי); `month_en` נותן את השם באנגלית.
  * `gematria` לפי המספר ההכרחי בלבד (לא מספר גדול / קטן).
* מקורות: הגדרות בלוק העברית ביוניקוד (U+0590–U+05FF) ובלוק הפיסוק הכללי; טבלת הגימטריה הסטנדרטית; כלל השנה המעוברת `(7·year + 1) mod 19 < 7`.
