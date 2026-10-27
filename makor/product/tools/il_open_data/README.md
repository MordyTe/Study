# il_open_data — search Israel's open-data portal (data.gov.il) from an AI agent

A small, dependency-free MCP tool that queries the public **CKAN action API** of
[data.gov.il](https://data.gov.il) — Israel's national open-data portal. Three
read-only functions, Hebrew-safe, offline-testable.

```
product/tools/il_open_data/
├── core.py               pure functions (no MCP, no globals mutated at runtime)
├── server.py             thin MCP wrapper; `mcp` import is guarded/optional
├── capture_fixtures.py   one-shot script to (re)capture live API responses
├── tests/                pytest, 100% offline (fetch_json is mocked)
│   ├── conftest.py       blocks urllib.request.urlopen for every test
│   └── fixtures/         CKAN-shaped JSON bodies served by the mock
└── README.md
```

## Functions

| Function | CKAN action | Returns |
|---|---|---|
| `search_datasets(query, limit=10)` | `package_search` | `{"ok": true, "count": N, "results": [{"id", "title", "organization", "resources": [{"format", "url", "id"}]}]}` |
| `get_dataset(dataset_id)` | `package_show` | `{"ok": true, "dataset": {"id", "name", "title", "notes", "organization", "license_title", "metadata_modified", "tags", "resources": [{"id", "name", "format", "url", "last_modified", "datastore_active"}]}}` |
| `search_records(resource_id, query="", limit=20)` | `datastore_search` | `{"ok": true, "count": total, "fields": [{"id", "type"}], "records": [...]}` |

`count` is the server-side total; `results`/`records` hold at most `limit`
items. Zero hits is **not** an error: `{"ok": true, "count": 0, "results": []}`.

### Example

```python
import core

core.search_datasets("תחבורה", limit=2)
# -> GET https://data.gov.il/api/3/action/package_search?q=%D7%AA%D7%97%D7%91%D7%95%D7%A8%D7%94&rows=2
# {'ok': True, 'count': 137, 'results': [{'id': '8a21fc79-...', 'title': 'לוחות זמנים של התחבורה הציבורית (GTFS)',
#   'organization': 'משרד התחבורה והבטיחות בדרכים', 'resources': [{'id': 'c1a2b3c4-...', 'format': 'ZIP', 'url': 'https://gtfs.mot.gov.il/...'}, ...]}, ...]}

core.get_dataset("mechirmnm")["dataset"]["resources"][0]["id"]
# -> 'b7cf8f14-64a2-4b33-8d4b-edb286fdbd37'

core.search_records("b7cf8f14-64a2-4b33-8d4b-edb286fdbd37", query="לחם", limit=3)
# -> {'ok': True, 'count': 23, 'fields': [...], 'records': [{'_id': 1, 'שם המוצר': 'לחם אחיד פרוס', ...}, ...]}
```

Run as an MCP server (needs `pip install mcp`): `python server.py`.
Without `mcp` installed, `server.py` still imports (for tests) and `main()`
returns exit code 1 with a message.

## Errors — always a dict, never an exception

| `error` | When |
|---|---|
| `invalid_input` | empty/whitespace/non-string `query`, `dataset_id` or `resource_id`; `limit` not an int in `1..1000`; text over the size limit; CKAN `Validation Error` |
| `source_unavailable` | timeout (10 s), DNS/connection failure, HTTP 5xx, HTTP 429 |
| `bad_response` | body is not valid JSON/UTF-8, not a JSON object, `success != true` without a recognised type, missing/malformed `result`, other HTTP 4xx, any unexpected exception |
| `not_found` | HTTP 404 or CKAN `Not Found Error` (unknown dataset / resource id) |

`detail` (≤ 500 chars) carries the reason for humans/logs. 

**Input limits:** `query` ≤ 500 chars; `dataset_id`/`resource_id` ≤ 200 chars;
`limit` 1–1000 (CKAN's own server-side cap).

## Transport

* `urllib` only (stdlib). Timeout **10 s**. `User-Agent: makor-il-open-data/0.1`.
* One function performs every request: `core.fetch_json(url)`. Tests replace it
  with `monkeypatch.setattr(core, "fetch_json", fake)`.
* Hebrew / non-ASCII is percent-encoded with `urllib.parse.quote` (`%D7%AA...`);
  the URL on the wire is pure ASCII. Spaces become `%20`.
* GET only. The tool never writes, never authenticates, never follows links to
  download resource files; it hands the `url` back to the caller.

## data.gov.il terms, robots.txt and what this tool does

**Status on 2026-10-27:** this tool was built in a sandbox whose egress proxy
denies `data.gov.il` (HTTP 403 on CONNECT), so `https://data.gov.il/robots.txt`
and the portal's terms-of-use page **could not be read**. We do not quote
content we have not seen. Facts stated here are limited to how the tool behaves.

What is *known* independent of robots.txt:

* `https://data.gov.il/api/3/action/…` is the documented, public, unauthenticated
  **CKAN action API** — the portal's intended machine interface, not an HTML page
  scraped against its will. `robots.txt` governs crawlers; this tool is a
  user-initiated API client that issues one targeted request per call and does
  not crawl, enumerate or mirror the site.
* Each dataset carries its own licence in `license_title` (open licences on this
  portal). The tool surfaces that field so the caller can honour it; it does not
  redistribute dataset contents itself.
* Load is bounded: 10 s timeout, `limit ≤ 1000`, no retries, no background
  polling, identifying User-Agent.

**Manual check to perform once network is available** (owner or any agent):

1. `curl -A makor-il-open-data/0.1 https://data.gov.il/robots.txt` — record the
   date and paste the `Disallow` lines here. If `/api/` is listed, note that
   CKAN's default robots.txt disallows `/api/` for *search-engine crawlers*;
   confirm with the portal's terms page that programmatic API use is permitted
   (it is the API's stated purpose) and link that page here.
2. Read the portal's תנאי שימוש (terms of use) page and summarise, with a link,
   any attribution requirement or rate guidance.
3. Run `python product/tools/il_open_data/capture_fixtures.py` to replace the
   fixtures with live captures (see below) and update the provenance table.

Until that check is recorded, treat this tool as **build-and-test only** (no
publishing) — consistent with COMPANY.md's "do not publish before owner setup".

## Fixture provenance (tests/fixtures/)

The spec asks for fixtures captured once from the live API with URL and date.
Because the API was unreachable from the build environment on 2026-10-27, the
fixtures are **schema-shaped samples written by hand in the exact CKAN 2.x
response format** (`{"help", "success", "result"}`, `package_search` /
`package_show` / `datastore_search` payload layouts including `_links`,
`records_format`, `total`, `datastore_active`, …). Hebrew titles, ids and
values are illustrative, not real records. This is stated in the table so no
reader mistakes them for live data.

| File | Intended URL (used by `capture_fixtures.py`) | Status |
|---|---|---|
| `package_search_transport.json` | `…/package_search?q=%D7%AA%D7%97%D7%91%D7%95%D7%A8%D7%94&rows=2` | sample, 2026-10-27 — NOT a live capture |
| `package_search_empty.json` | `…/package_search?q=zzqx_no_such_dataset_7781&rows=2` | sample, 2026-10-27 — NOT a live capture |
| `package_show.json` | `…/package_show?id=mechirmnm` | sample, 2026-10-27 — NOT a live capture |
| `package_show_not_found.json` | `…/package_show?id=<unknown>` (CKAN 404 body) | sample, 2026-10-27 — NOT a live capture |
| `datastore_search.json` | `…/datastore_search?resource_id=b7cf8f14-…&limit=2` | sample, 2026-10-27 — NOT a live capture |
| `datastore_search_empty.json` | `…/datastore_search?resource_id=b7cf8f14-…&q=zzqx…&limit=2` | sample, 2026-10-27 — NOT a live capture |
| `broken.json` | n/a — deliberately truncated body for the bad-JSON test | synthetic by design |

To upgrade to genuine captures: `python product/tools/il_open_data/capture_fixtures.py`
(one request per fixture, plus `robots.txt`), then replace "sample" with
"captured <date>" above. Tests assert on ids/titles present in the current
fixtures, so expect to adjust a handful of literal assertions after recapture.

## Tests

```
cd makor
python -m pytest -q product/tools/il_open_data/tests      # 41 passed
```

No test touches the network: `conftest.py` replaces `urllib.request.urlopen`
with a function that raises for the whole session, and every happy-path test
swaps `core.fetch_json` for a fixture-backed fake. Required cases covered:
Hebrew query percent-encoded in the URL; empty query; timeout; connection
refused; HTTP 500/502/503/429; HTTP 404; broken JSON; zero results; `limit`
honoured on the wire and in the result (and defaults 10/20); real `fetch_json`
never called when mocked; an unmocked call is blocked by the guard and still
returns a structured error; `server.py` imports and works without `mcp`.

## Assumptions

* `datastore_search` with an empty `query` is valid and returns the first rows,
  so `q` is omitted from the URL in that case.
* `organization` is flattened to the organisation's display title (falls back
  to its slug; `null` when absent).
* HTTP 429 is treated as `source_unavailable` (back off and retry later).
* `limit` above 1000 is rejected rather than silently clamped, so callers learn
  the cap.

---

# il_open_data — חיפוש בפורטל המידע הפתוח data.gov.il מתוך סוכן AI

כלי MCP קטן, ללא תלויות, שפונה ל‑**CKAN action API** הציבורי של
[data.gov.il](https://data.gov.il). שלוש פונקציות קריאה בלבד, תומך בעברית,
ונבדק במלואו בלי רשת.

## פונקציות

| פונקציה | פעולת CKAN | מחזירה |
|---|---|---|
| `search_datasets(query, limit=10)` | `package_search` | `{"ok": true, "count": N, "results": [{"id", "title", "organization", "resources": [{"format", "url", "id"}]}]}` |
| `get_dataset(dataset_id)` | `package_show` | `{"ok": true, "dataset": {...}}` כולל `license_title`, `tags`, ו‑`resources` עם `datastore_active` |
| `search_records(resource_id, query="", limit=20)` | `datastore_search` | `{"ok": true, "count": total, "fields": [...], "records": [...]}` |

`count` הוא הסך הכולל בשרת; `results`/`records` מחזיקים לכל היותר `limit`
פריטים. אפס תוצאות הוא **לא** שגיאה: `{"ok": true, "count": 0, "results": []}`.

### דוגמה

```python
import core
core.search_datasets("תחבורה", limit=2)
# GET https://data.gov.il/api/3/action/package_search?q=%D7%AA%D7%97%D7%91%D7%95%D7%A8%D7%94&rows=2
core.search_records("b7cf8f14-64a2-4b33-8d4b-edb286fdbd37", query="לחם", limit=3)
```

הרצה כשרת MCP (דורש `pip install mcp`): `python server.py`. בלי החבילה,
`server.py` עדיין נטען (לצורך הטסטים) ו‑`main()` מחזיר קוד יציאה 1 עם הודעה.

## שגיאות — תמיד מילון, לעולם לא exception

| `error` | מתי |
|---|---|
| `invalid_input` | `query` / `dataset_id` / `resource_id` ריקים או לא מחרוזת; `limit` לא שלם בתחום 1..1000; טקסט מעל מגבלת הגודל; `Validation Error` של CKAN |
| `source_unavailable` | timeout (10 שניות), כשל DNS/חיבור, HTTP 5xx, HTTP 429 |
| `bad_response` | גוף שאינו JSON/UTF‑8 תקין, לא אובייקט JSON, `success != true` ללא סוג מוכר, `result` חסר/פגום, 4xx אחר, כל exception לא צפוי |
| `not_found` | HTTP 404 או `Not Found Error` של CKAN (מזהה לא קיים) |

**מגבלות קלט:** `query` עד 500 תווים; `dataset_id`/`resource_id` עד 200 תווים;
`limit` בין 1 ל‑1000 (התקרה של CKAN עצמו).

## תעבורה

* `urllib` בלבד (ספריית התקן). Timeout **10 שניות**. `User-Agent: makor-il-open-data/0.1`.
* כל בקשת HTTP עוברת דרך פונקציה אחת: `core.fetch_json(url)`. בטסטים מחליפים אותה
  ב‑`monkeypatch.setattr(core, "fetch_json", fake)`.
* עברית מקודדת ב‑URL עם `urllib.parse.quote` (`%D7%AA...`); ה‑URL על הקו הוא ASCII בלבד.
* GET בלבד; הכלי לא כותב, לא מתחבר עם הרשאות ולא מוריד קובצי משאבים — הוא מחזיר את ה‑`url` לקורא.

## תנאי השימוש, robots.txt ומה הכלי עושה

**מצב ב‑27.10.2026:** הכלי נבנה בסביבה שבה ה‑proxy חוסם את `data.gov.il`
(403 על CONNECT), ולכן **לא ניתן היה לקרוא** את `https://data.gov.il/robots.txt`
ואת עמוד תנאי השימוש. אנחנו לא מצטטים תוכן שלא ראינו; מה שכתוב כאן מוגבל
להתנהגות הכלי עצמו.

מה ידוע ללא תלות ב‑robots.txt:

* `https://data.gov.il/api/3/action/…` הוא ה‑CKAN action API הציבורי והמתועד —
  ממשק המכונה המיועד של הפורטל, לא עמוד HTML שמגרדים. `robots.txt` מכוון
  לזחלנים; הכלי הזה הוא לקוח API שפועל ביוזמת משתמש, בקשה ממוקדת אחת לכל
  קריאה, בלי זחילה, מיפוי או שכפול של האתר.
* לכל מאגר רישיון משלו בשדה `license_title`; הכלי מציג אותו כדי שהקורא יכבד
  אותו, ואינו מפיץ את תוכן המאגרים בעצמו.
* העומס חסום: timeout 10 שניות, `limit ≤ 1000`, בלי retries, בלי polling, עם User‑Agent מזהה.

**בדיקה ידנית לביצוע פעם אחת כשיש רשת** (הבעלים או כל סוכן):

1. `curl -A makor-il-open-data/0.1 https://data.gov.il/robots.txt` — לתעד תאריך
   ולהדביק כאן את שורות ה‑`Disallow`. אם `/api/` מופיע — ברירת המחדל של CKAN
   חוסמת `/api/` *למנועי חיפוש*; לאמת מול עמוד תנאי השימוש ששימוש תוכנתי
   ב‑API מותר (זו מטרתו המוצהרת) ולקשר לעמוד כאן.
2. לקרוא את עמוד תנאי השימוש ולסכם, עם קישור, דרישות ייחוס או קצב.
3. להריץ `python product/tools/il_open_data/capture_fixtures.py` כדי להחליף את
   ה‑fixtures בלכידות אמיתיות ולעדכן את טבלת המקור.

עד שהבדיקה מתועדת, הכלי במצב **בנייה ובדיקה בלבד** (ללא פרסום) — בהתאם
ל‑COMPANY.md: "לא מפרסמים לפני שהבעלים פותח חשבונות".

## מקור ה‑fixtures (tests/fixtures/)

המפרט דורש fixtures שנלכדו פעם אחת מה‑API האמיתי עם URL ותאריך. מכיוון שה‑API
לא היה נגיש מסביבת הבנייה ב‑27.10.2026, הקבצים הם **דוגמאות שנכתבו ידנית
במבנה המדויק של תשובת CKAN 2.x** (`{"help", "success", "result"}` וכל שדות
`package_search` / `package_show` / `datastore_search`). הכותרות, המזהים
והערכים בעברית הם להדגמה ואינם רשומות אמיתיות. זה מצוין בטבלה כדי שאף קורא
לא יחשוב שמדובר בנתונים חיים.

| קובץ | URL מיועד (משמש את `capture_fixtures.py`) | מצב |
|---|---|---|
| `package_search_transport.json` | `…/package_search?q=%D7%AA%D7%97%D7%91%D7%95%D7%A8%D7%94&rows=2` | דוגמה, 27.10.2026 — לא לכידה חיה |
| `package_search_empty.json` | `…/package_search?q=zzqx_no_such_dataset_7781&rows=2` | דוגמה, 27.10.2026 — לא לכידה חיה |
| `package_show.json` | `…/package_show?id=mechirmnm` | דוגמה, 27.10.2026 — לא לכידה חיה |
| `package_show_not_found.json` | `…/package_show?id=<לא קיים>` (גוף 404 של CKAN) | דוגמה, 27.10.2026 — לא לכידה חיה |
| `datastore_search.json` | `…/datastore_search?resource_id=b7cf8f14-…&limit=2` | דוגמה, 27.10.2026 — לא לכידה חיה |
| `datastore_search_empty.json` | `…/datastore_search?resource_id=b7cf8f14-…&q=zzqx…&limit=2` | דוגמה, 27.10.2026 — לא לכידה חיה |
| `broken.json` | — גוף קטום בכוונה לטסט JSON שבור | סינתטי במכוון |

לשדרוג ללכידות אמיתיות: `python product/tools/il_open_data/capture_fixtures.py`
(בקשה אחת לכל fixture, ועוד `robots.txt`), ואז להחליף "דוגמה" ב"נלכד <תאריך>".
הטסטים בודקים מזהים/כותרות מה‑fixtures הנוכחיים, ולכן יידרש עדכון של כמה
assertions מילוליים לאחר הלכידה.

## טסטים

```
cd makor
python -m pytest -q product/tools/il_open_data/tests      # 41 passed
```

אף טסט לא נוגע ברשת: `conftest.py` מחליף את `urllib.request.urlopen` בפונקציה
שזורקת שגיאה לכל אורך הריצה, וכל טסט של מסלול תקין מחליף את `core.fetch_json`
ב‑fake שמגיש fixture. המקרים הנדרשים מכוסים: עברית מקודדת נכון ב‑URL; query ריק;
timeout; חיבור נדחה; HTTP 500/502/503/429; HTTP 404; JSON שבור; אפס תוצאות;
`limit` מכובד על הקו ובתוצאה (וברירות מחדל 10/20); `fetch_json` האמיתי לא נקרא
כשיש mock; קריאה ללא mock נחסמת על ידי המגן ועדיין מחזירה שגיאה מובנית;
`server.py` נטען ועובד בלי `mcp`.

## הנחות

* `datastore_search` עם `query` ריק הוא תקין ומחזיר את השורות הראשונות; במקרה זה `q` מושמט מה‑URL.
* `organization` מושטח לכותרת התצוגה של הארגון (נפילה ל‑slug; `null` כשאין).
* HTTP 429 מטופל כ‑`source_unavailable` (להמתין ולנסות שוב).
* `limit` מעל 1000 נדחה ולא נחתך בשקט, כדי שהקורא ילמד על התקרה.
