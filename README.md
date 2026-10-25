# studio-transcribe — מערכת תמלול אולפן בדיוק גבוה (עברית + אנגלית)

תמלול מדויק, מתויג-דובר, לאולפן שידור שמזין את ערוצי המיקרופון (לכל מיק ערוץ נפרד)
מ‑**Behringer X32** דרך **Dante** אל node תמלול ייעודי. מנוע ברירת המחדל הוא ה‑fine-tune
הישראלי הפתוח **ivrit.ai** ל‑Whisper, שמריץ **מקומית** (פרטי, ללא עלות לפי דקה) ומגיע
ל‑~5% WER על עברית נקייה.

> אפיון המוצר המלא נמצא ב‑[`docs/SPEC.md`](docs/SPEC.md).

## למה זה מדויק (עקרונות)

1. **ערוץ לכל מיקרופון** → כל ערוץ = דובר אחד, בלי diarization ובלי חפיפת-דוברים. המנוף
   הגדול ביותר, ומגיע "בחינם" מה‑X32.
2. **מודל עברי ייעודי** — `ivrit-ai/whisper-large-v3-turbo` (לא Whisper רגיל). ~35–45% פחות
   שגיאות בעברית.
3. **Silero VAD** — אנטי-הזיה #1 (Whisper ממציא טקסט על שקט/מוזיקה).
4. **הגדרות אנטי-לופ** — `condition_on_previous_text=False` + ספי compression/logprob.
5. **מילון (glossary)** להטיית שמות ומונחי אנגלית.
6. **תיקון-LLM מבוקר** — רק על מקטעים בביטחון נמוך, בלי לנסח מחדש (הגנה מ‑over-correction).

## ארכיטקטורה (תקציר)

```
X32 ──(X-DANTE / X-USB, 48kHz, clock-locked)── Dante ──► node תמלול ייעודי
  → לכידת ASIO (32ch)  → 16kHz mono/ערוץ  → VAD
  → שכבה מדויקת: ivrit.ai large-v3-turbo + מיזוג + תיקון-LLM → ארכיון + ייצוא
  → שכבה חיה (בהמשך): streaming → כתוביות ל‑OBS/vMix
```

מכיוון שכל הערוצים מגיעים מ‑stream יחיד נעול-clock, הם סינכרוניים ברמת ה‑sample — מה שהופך
את מיזוג ציר-הזמן בין הדוברים למדויק לחלוטין.

## מבנה הפרויקט

```
studio_transcribe/        חבילת הפייתון
  models.py               מבני נתונים (Word/Segment/ChannelResult)
  normalize_he.py         נרמול עברית (ניקוד/bidi/גרשיים) לתצוגה ול‑WER
  eval_wer.py             מדידת WER/CER (ללא תלויות)
  merge.py                מיזוג ערוצים → ציר זמן מתויג-דובר
  export.py               ייצוא SRT/VTT/TXT/DOCX
  glossary.py             טעינת מילון + בניית initial_prompt
  config.py               קונפיגורציה (dict/YAML)
  store.py                אחסון SQLite + חיפוש full-text (FTS5/LIKE)
  audio_io.py             קריאת אודיו + resample ל‑16kHz mono
  vad.py                  Silero VAD (לשכבה החיה / pre-gating)
  llm_correction.py       תיקון-LLM מבוקר (low-confidence בלבד)
  pipeline.py             הצינור ה-offline המלא
  cli.py                  ממשק שורת פקודה (transcribe/search/live/eval)
  engines/                מנועי ASR (faster-whisper מקומי, cloud scaffold)
  live/                   כתוביות חיות: capture_stream, soniox_client,
                          vad_gate, captions, sinks (OBS/vMix/file), runner
  server/                 מסך תפעול: FastAPI (app/service/auth) + SPA ב‑static/
capture/capture_asio.py   שלב 0: לכידת ערוצי X32 דרך ASIO ל‑WAV נפרד
config/                   דוגמאות קונפיג + מילון
tests/                    טסטים ל‑core הדטרמיניסטי (40 טסטים)
docs/SPEC.md              אפיון המוצר המלא
```

ה‑**core** (נרמול, WER, מיזוג, ייצוא, glossary, config) הוא pure-stdlib ונבדק במלואו; שכבת
ה‑ML/אודיו טוענת את התלויות הכבדות (faster-whisper, torch, soundfile) באופן עצל.

## התקנה (על node התמלול)

```bash
python -m venv .venv && source .venv/bin/activate   # ב‑Windows: .venv\Scripts\activate
pip install -r requirements.txt
# אופציונלי: pip install -r requirements-cloud.txt   # fallback ענן
```

מודל ivrit.ai יורד אוטומטית מ‑HuggingFace בריצה הראשונה. לזמן-אמת מקומי דרוש GPU של NVIDIA
(מומלץ ≥12GB VRAM; 24GB נוח לכמה ערוצים במקביל).

## מסך תפעול (UI)

```bash
pip install -r requirements.txt
studio-transcribe serve -c config/config.yaml          # ואז פתחו http://localhost:8000
```

מסך דפדפן להדלקה/כיבוי כתוביות חיות, הרצת תמלול, חיפוש בארכיון, והגדרות (ערוצים↔דוברים,
יעד כתוביות OBS/vMix, מילון). לגישה מרשת: `host: 0.0.0.0` + `STUDIO_TRANSCRIBE_PASSWORD`.
**המדריך המלא: [`docs/USAGE.md`](docs/USAGE.md).**

## שימוש בשורת פקודה

**שלב 0 — לכידת אודיו מה‑X32 (על החומרה):**

```bash
python capture/capture_asio.py list                      # לראות device‑ים/ASIO
python capture/capture_asio.py record --device ASIO \
    --channels 1 2 3 4 --seconds 60 --out-dir rec        # WAV נפרד לכל ערוץ
```

**שלב 1 — תמלול מדויק + ייצוא:**

```bash
# תיקיית ערוצים (ch01.wav, ch02.wav, ...) או קובץ רב-ערוצי יחיד
studio-transcribe transcribe rec/ -c config/config.yaml -o out -f txt srt docx
# או בלי התקנה:
python -m studio_transcribe transcribe rec/ -c config/config.yaml -f txt srt
```

**שלב 2 — אחסון וחיפוש:**

```bash
# שמירה ל‑DB תוך כדי תמלול
studio-transcribe transcribe rec/ -c config/config.yaml --db studio.db --session-name "פרק 1"
# חיפוש full-text (עברית/אנגלית), עם סינון דובר אופציונלי
studio-transcribe search "Dante" --db studio.db
studio-transcribe search "ברוכים הבאים" --db studio.db --speaker "מנחה"
```

**שלב 3 — כתוביות חיות (Soniox → OBS/vMix):**

```bash
export STUDIO_TRANSCRIBE_CLOUD_KEY=...      # מפתח Soniox
studio-transcribe live -c config/config.yaml --db studio.db
# מזרים את ערוצי ה‑X32 ל‑Soniox ודוחף כתוביות ל‑OBS/vMix לפי סקשן live בקונפיג
```

**מדידת דיוק (WER/CER) מול תמלול-אמת:**

```bash
studio-transcribe eval reference.txt hypothesis.txt
# WER: 4.90%  (S=12 D=3 I=4 N=388)
# CER: 1.82%
```

## מדידת דיוק — איך "מבטיחים" מדויק

הדיוק נמדד על האודיו שלכם, לא מוצהר:
1. להקליט 2–3 תוכניות אמיתיות (פודקאסט + שידור עם ערבוב עברית-אנגלית).
2. לתמלל ידנית דגימות כ‑ground truth.
3. להריץ `studio-transcribe eval` — הנרמול תואם את ה‑leaderboard של ivrit.ai (ניקוד/bidi/גרשיים),
   כך שהמספר בר-השוואה.
4. לכוון gate/VAD/glossary/תיקון-LLM, ולמדוד שוב.

## פיתוח

```bash
pip install pytest && python -m pytest        # 40 טסטים ל‑core
```

## מפת דרכים (מתוך האפיון)

- [x] שלב 0: לכידת ערוצי X32 דרך ASIO
- [x] שלב 1: צינור תמלול מדויק (offline) + ייצוא + מדידת WER
- [x] שלב 2: אחסון SQLite (FTS5) + חיפוש full-text
- [x] שלב 3: כתוביות חיות → Soniox (ענן) → OBS (obs-websocket) / vMix (API) / קובץ
- [x] שלב 4: מסך תפעול (FastAPI + UI) — הדלקה/כיבוי, תמלול, חיפוש, הגדרות, גישת LAN+סיסמה
- [ ] שלב 5: הקשחה נוספת, ניטור מתקדם, מתג hybrid אוטומטי בעומס

## רישיון

MIT (קוד הפרויקט). מודל ivrit.ai: Apache-2.0. יש לוודא רישוי כל תלות שמותקנת.
