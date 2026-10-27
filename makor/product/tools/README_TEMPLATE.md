<!--
README_TEMPLATE.md — the bilingual README every Makor tool uses.
How to use: copy to product/tools/<tool_name>/README.md, replace every {{placeholder}}, delete these comments.
Keep the section order. English first, Hebrew mirror below — every section exists in both languages.
Code, parameter names, JSON keys and error codes stay in English in both halves.
No superlatives. No performance or accuracy claims without a measurement (what, when, where). Every number needs a date and a source.
Spec: product/research/day0-naming.md (part C).

תבנית README דו‑לשונית לכל כלי. איך משתמשים: מעתיקים ל‑product/tools/<tool_name>/README.md, מחליפים כל {{placeholder}}, מוחקים את ההערות.
לא משנים את סדר הסעיפים. אנגלית קודם, עברית מתחת — כל סעיף קיים בשתי השפות. קוד, פרמטרים, מפתחות JSON וקודי שגיאה נשארים באנגלית.
בלי סופרלטיבים. בלי הבטחות ביצועים/דיוק בלי מדידה. כל מספר עם תאריך ומקור.
-->

# {{tool_name}}

{{One sentence, under 120 characters: what the tool does, for whom. No adjectives. Example: "Search datasets and query records on data.gov.il, Israel's CKAN open-data portal."}}

Status: {{alpha | beta | stable}} · Version: {{0.1.0}} · License: {{license}} · Runs as: MCP server (stdio)

## What it does

{{2–5 sentences. What goes in, what comes out, what it does not do. State the main non-goal explicitly, e.g. "Does not convert Hebrew dates to Gregorian dates."}}

- {{Capability 1 — one line, checkable against a test in tests/}}
- {{Capability 2}}
- {{Capability 3}}

## Install / Run

Requirements: Python {{3.11+}}, the `mcp` package. No other dependencies. {{If the tool uses the network, say so here in one line: "Needs outbound HTTPS to {{host}}."}}

```bash
python -m pip install mcp
python product/tools/{{tool_name}}/server.py      # starts the MCP server on stdio
```

MCP client configuration (Claude Desktop, Cursor, or any stdio MCP client):

```json
{
  "mcpServers": {
    "{{tool_name}}": {
      "command": "python",
      "args": ["/absolute/path/to/product/tools/{{tool_name}}/server.py"]
    }
  }
}
```

Run the tests (no network is used):

```bash
python -m pytest -q product/tools/{{tool_name}}/tests
```

## Tools & parameters

| Tool | Parameter | Type | Required | Default | Description |
|------|-----------|------|----------|---------|-------------|
| `{{tool_a}}` | `{{param}}` | `str` | yes | — | {{what it is; limits, e.g. "max 100,000 characters"}} |
| `{{tool_b}}` | `{{param}}` | `str` | yes | — | {{...}} |
| `{{tool_b}}` | `{{limit}}` | `int` | no | `{{10}}` | {{range, e.g. "1–100; values above 100 are clamped"}} |

Every tool returns a JSON object. Success: `{"ok": true, ...}`. Failure: `{"ok": false, "error": "<code>", "detail": "<optional text>"}`. No tool raises an exception to the caller.

## Example call

```json
{
  "tool": "{{tool_a}}",
  "arguments": {
    "{{param}}": "{{example input — use a real value, e.g. Hebrew text or a real dataset id}}"
  }
}
```

Equivalent direct call from Python (same function the server wraps):

```python
from product.tools.{{tool_name}}.core import {{tool_a}}
print({{tool_a}}("{{example input}}"))
```

## Example output

```json
{{Paste the actual output of the call above, unedited. If it comes from a live source, state the capture date in a comment line below the block.}}
```

{{Captured: YYYY-MM-DD, {{live API | offline computation}}.}}

## Limits & data sources

- Input size limit: {{e.g. 100,000 characters per call → error `input_too_large`}}.
- Timeout: {{e.g. 10 seconds per HTTP request → error `source_unavailable`}} / {{"not applicable — no network"}}.
- Rate limits: {{what the source documents, with URL; or "none documented — not measured"}}.
- Not supported: {{explicit list, e.g. "Hebrew → Gregorian date conversion"}}.
- Data source: {{name}} — {{URL}}. Terms of use: {{URL}}. License of the data: {{exact license name + URL}}.
- robots.txt of {{host}}, read on {{YYYY-MM-DD}} at {{URL/robots.txt}}, relevant lines quoted:

  ```
  {{User-agent: *}}
  {{Disallow: ...}}
  ```

  {{One line: what this tool accesses (public API endpoints only) and why it is within these rules.}}
- Test fixtures (`tests/fixtures/*.json`) are real responses captured once from the source API. Tests never touch the network.

| Fixture file | Captured from (URL) | Captured on |
|--------------|---------------------|-------------|
| `{{fixture_1.json}}` | `{{full request URL}}` | {{YYYY-MM-DD}} |
| `{{fixture_2.json}}` | `{{full request URL}}` | {{YYYY-MM-DD}} |

## Errors

| Code | When | What to do |
|------|------|------------|
| `invalid_input` | Argument is `None`, wrong type, or empty where a value is required | Check the argument type and value |
| `input_too_large` | Input exceeds the documented size limit | Split the input |
| `source_unavailable` | Timeout, connection error, or HTTP 5xx from the data source | Retry later; the source is down or slow |
| `bad_response` | Source returned something that is not valid JSON / expected structure | Report with the request URL; the source may have changed |
| `{{tool_specific_code}}` | {{when}} | {{what to do}} |

## Changelog

- {{0.1.0}} ({{YYYY-MM-DD}}) — {{first version: list the tools}}.

---

# {{tool_name}}

{{משפט אחד, עד 120 תווים: מה הכלי עושה ולמי. בלי שמות תואר. דוגמה: "חיפוש מאגרים ושליפת רשומות מ‑data.gov.il, פורטל הנתונים הפתוחים של ממשלת ישראל (CKAN)."}}

סטטוס: {{alpha | beta | stable}} · גרסה: {{0.1.0}} · רישיון: {{license}} · רץ כ: שרת MCP (stdio)

## מה הכלי עושה

{{2–5 משפטים. מה נכנס, מה יוצא, מה הכלי לא עושה. לכתוב במפורש את ה"לא" המרכזי, למשל: "לא ממיר תאריך עברי לתאריך לועזי."}}

- {{יכולת 1 — שורה אחת, עם טסט תואם ב‑tests/}}
- {{יכולת 2}}
- {{יכולת 3}}

## התקנה / הרצה

דרישות: Python {{3.11+}} וחבילת `mcp`. אין תלויות נוספות. {{אם הכלי משתמש ברשת — שורה אחת: "דורש HTTPS יוצא אל {{host}}."}}

```bash
python -m pip install mcp
python product/tools/{{tool_name}}/server.py      # מפעיל את שרת ה‑MCP על stdio
```

הגדרת לקוח MCP (Claude Desktop, Cursor, או כל לקוח stdio):

```json
{
  "mcpServers": {
    "{{tool_name}}": {
      "command": "python",
      "args": ["/absolute/path/to/product/tools/{{tool_name}}/server.py"]
    }
  }
}
```

הרצת הטסטים (בלי רשת):

```bash
python -m pytest -q product/tools/{{tool_name}}/tests
```

## כלים ופרמטרים

| כלי | פרמטר | טיפוס | חובה | ברירת מחדל | תיאור |
|-----|-------|-------|------|------------|-------|
| `{{tool_a}}` | `{{param}}` | `str` | כן | — | {{מה זה; מגבלות, למשל "עד 100,000 תווים"}} |
| `{{tool_b}}` | `{{param}}` | `str` | כן | — | {{...}} |
| `{{tool_b}}` | `{{limit}}` | `int` | לא | `{{10}}` | {{טווח, למשל "1–100; מעל 100 נחתך ל‑100"}} |

כל כלי מחזיר אובייקט JSON. הצלחה: `{"ok": true, ...}`. כשל: `{"ok": false, "error": "<code>", "detail": "<טקסט אופציונלי>"}`. אף כלי לא זורק exception למי שקורא לו.

## דוגמת קריאה

```json
{
  "tool": "{{tool_a}}",
  "arguments": {
    "{{param}}": "{{קלט לדוגמה — ערך אמיתי, למשל טקסט עברי או מזהה מאגר קיים}}"
  }
}
```

קריאה ישירה מ‑Python (אותה פונקציה שהשרת עוטף):

```python
from product.tools.{{tool_name}}.core import {{tool_a}}
print({{tool_a}}("{{קלט לדוגמה}}"))
```

## דוגמת פלט

```json
{{הפלט האמיתי של הקריאה שלמעלה, ללא עריכה. אם הגיע ממקור חי — תאריך הלכידה בשורה מתחת.}}
```

{{נלכד: YYYY-MM-DD, {{API חי | חישוב מקומי}}.}}

## מגבלות ומקורות נתונים

- מגבלת גודל קלט: {{למשל 100,000 תווים לקריאה → שגיאה `input_too_large`}}.
- Timeout: {{למשל 10 שניות לבקשת HTTP → שגיאה `source_unavailable`}} / {{"לא רלוונטי — אין רשת"}}.
- מגבלות קצב: {{מה שהמקור מתעד, עם URL; או "לא מתועד — לא נמדד"}}.
- לא נתמך: {{רשימה מפורשת, למשל "המרת תאריך עברי ללועזי"}}.
- מקור הנתונים: {{שם}} — {{URL}}. תנאי שימוש: {{URL}}. רישיון הנתונים: {{שם מדויק + URL}}.
- robots.txt של {{host}}, נקרא בתאריך {{YYYY-MM-DD}} מ‑{{URL/robots.txt}}, השורות הרלוונטיות:

  ```
  {{User-agent: *}}
  {{Disallow: ...}}
  ```

  {{שורה אחת: למה הכלי פונה (רק נקודות קצה ציבוריות של ה‑API) ולמה זה בתוך הכללים.}}
- קבצי ה‑fixture (`tests/fixtures/*.json`) הם תשובות אמיתיות שנלכדו פעם אחת מה‑API של המקור. הטסטים לא נוגעים ברשת.

| קובץ fixture | נלכד מ‑(URL) | תאריך לכידה |
|--------------|--------------|-------------|
| `{{fixture_1.json}}` | `{{URL מלא של הבקשה}}` | {{YYYY-MM-DD}} |
| `{{fixture_2.json}}` | `{{URL מלא של הבקשה}}` | {{YYYY-MM-DD}} |

## שגיאות

| קוד | מתי | מה לעשות |
|-----|-----|----------|
| `invalid_input` | הארגומנט הוא `None`, מטיפוס שגוי, או ריק כשנדרש ערך | לבדוק טיפוס וערך |
| `input_too_large` | הקלט חורג ממגבלת הגודל המתועדת | לפצל את הקלט |
| `source_unavailable` | timeout, שגיאת חיבור או HTTP 5xx מהמקור | לנסות שוב מאוחר יותר; המקור לא זמין או איטי |
| `bad_response` | המקור החזיר משהו שאינו JSON תקין / מבנה צפוי | לדווח עם ה‑URL של הבקשה; ייתכן שהמקור השתנה |
| `{{tool_specific_code}}` | {{מתי}} | {{מה לעשות}} |

## יומן שינויים

- {{0.1.0}} ({{YYYY-MM-DD}}) — {{גרסה ראשונה: רשימת הכלים}}.
