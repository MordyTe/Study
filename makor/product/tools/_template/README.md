# _template

A one-sentence description of what the tool does. (This is the layout every Makor tool copies — see `TEMPLATE_GUIDE.md`.)

## Install

```bash
pip install mcp          # the only non-stdlib dependency
python server.py         # MCP server over stdio
```

Tests need only pytest (no `mcp`):

```bash
python -m pytest -q product/tools/_template/tests
```

## Tools

| Tool | Parameters | Returns |
|------|------------|---------|
| `count_words` | `text: str` | `{"ok": true, "words": int, "characters": int}` |

Errors are never raised; they are returned as `{"ok": false, "error": <code>, "message": <text>}`:

| `error` | When |
|---------|------|
| `invalid_input` | `text` is `None` or not a string |
| `input_too_large` | more than 100,000 characters (`limit` field included) |
| `internal_error` | unexpected failure (should not happen; please report) |

## Example

Call:

```json
{"tool": "count_words", "arguments": {"text": "hello world"}}
```

Result:

```json
{"ok": true, "words": 2, "characters": 11}
```

## Limits and sources

* Input limit: 100,000 characters per call.
* Pure Python, stdlib only, no network access.
* Sources: none (no external data).

---

# _template (עברית)

משפט אחד שמתאר מה הכלי עושה. (זו התבנית שכל כלי של מקור מעתיק — ראו `TEMPLATE_GUIDE.md`.)

## התקנה

```bash
pip install mcp          # התלות היחידה מחוץ לספריית התקן
python server.py         # שרת MCP על stdio
```

הטסטים דורשים רק pytest (לא `mcp`):

```bash
python -m pytest -q product/tools/_template/tests
```

## כלים

| כלי | פרמטרים | פלט |
|-----|---------|-----|
| `count_words` | `text: str` | `{"ok": true, "words": int, "characters": int}` |

שגיאות לא נזרקות כ‑exception אלא מוחזרות כ‑`{"ok": false, "error": <קוד>, "message": <טקסט>}`:

| `error` | מתי |
|---------|-----|
| `invalid_input` | `text` הוא `None` או לא מחרוזת |
| `input_too_large` | מעל 100,000 תווים (כולל שדה `limit`) |
| `internal_error` | תקלה בלתי צפויה (לא אמור לקרות; נא לדווח) |

## דוגמה

קריאה:

```json
{"tool": "count_words", "arguments": {"text": "hello world"}}
```

פלט:

```json
{"ok": true, "words": 2, "characters": 11}
```

## מגבלות ומקורות

* מגבלת קלט: 100,000 תווים לקריאה.
* פייתון טהור, ספריית התקן בלבד, בלי גישה לרשת.
* מקורות: אין (אין נתונים חיצוניים).
