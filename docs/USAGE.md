# מדריך שימוש — מערכת תמלול האולפן

מדריך מלא: התקנה, הרצה, גישה, ותפעול יומיומי של מסך הפרודקשן.

---

## 0. התחלה מהירה (3 דקות) — בדיקת מיקרופון

הדרך הכי מהירה לראות שהתמלול עובד, לפני כל חיבור ל‑X32/Dante:

```bash
# התקנה (ראו §1 לפירוט)
python -m venv .venv && .venv\Scripts\activate      # Windows
pip install -r requirements.txt

# הרצה
studio-transcribe serve -c config/config.yaml
```

1. פתחו בדפדפן **http://localhost:8000**.
2. אתם כבר בטאב **"בדיקת מיקרופון"**.
3. לחצו **🎤 התחלת בדיקה**, חכו ל"מוכן — דברו" (בפעם הראשונה המודל יורד — דקה בערך),
   ודברו למיקרופון של המחשב.
4. הטקסט יופיע על המסך. זהו — התמלול עובד.

> הבדיקה משתמשת במיקרופון הדיפולטי של המחשב ובמנוע המקומי (ivrit.ai) — בלי הגדרות,
> בלי מפתחות, בלי חיבורים. רק אחרי שזה עובד, עוברים לחיבור ה‑X32 (§4 ואילך).

---

## 1. התקנה (פעם אחת, על ה‑node)

ה‑node הוא המחשב שמקבל את האודיו (מומלץ מחשב ייעודי, לא מחשב השידור העמוס).

```bash
# 1. להוריד את הקוד
git clone <repo-url> studio-transcribe && cd studio-transcribe

# 2. סביבת פייתון (Python 3.10+)
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

# 3. התקנת תלויות
pip install -r requirements.txt

# 4. הגדרות ראשוניות
copy config\config.example.yaml config\config.yaml      # Windows
# cp config/config.example.yaml config/config.yaml      # Linux/Mac
copy config\glossary.example.txt config\glossary.txt
```

מודל ה‑ivrit.ai (לתמלול המדויק) יורד אוטומטית בפעם הראשונה. לכתוביות החיות דרוש מפתח
**Soniox** (ראו §4).

---

## 2. הרצת המערכת

```bash
studio-transcribe serve -c config/config.yaml
# או בלי התקנה כחבילה:
python -m studio_transcribe serve -c config/config.yaml
```

תראו בטרמינל: `operator UI on http://127.0.0.1:8000`.

**עצירה:** `Ctrl-C` בטרמינל.

---

## 3. גישה למסך התפעול

### מהמחשב עצמו
פתחו דפדפן: **http://localhost:8000**

### ממחשבים אחרים באולפן (LAN)
1. בקובץ `config/config.yaml`, בסקשן `server`, שנו `host: 0.0.0.0`.
2. הגדירו סיסמה (מומלץ מאוד ברשת) — משתנה סביבה:
   ```bash
   set STUDIO_TRANSCRIBE_PASSWORD=הסיסמה-שלכם      # Windows
   # export STUDIO_TRANSCRIBE_PASSWORD=...          # Linux/Mac
   ```
3. הריצו `serve` שוב.
4. ממחשב אחר: **http://<כתובת-ה-node>:8000** (לדוגמה `http://192.168.1.50:8000`),
   הזינו את הסיסמה במסך הכניסה.

> אם לא מוגדרת סיסמה — הגישה פתוחה (מתאים רק ל‑localhost). לרשת — תמיד הגדירו סיסמה.
> ודאו שה‑firewall של Windows מתיר את הפורט 8000.

---

## 4. מסך התפעול — סיור

### טאב "בדיקת מיקרופון"
בדיקה מהירה מהמיקרופון של המחשב (ראו §0). כפתור התחלה/עצירה אחד, המנוע המקומי, בלי הגדרות.

### טאב "חי" (כתוביות חיות)
- כפתור גדול **הדלקת / כיבוי כתוביות חיות**.
- אינדיקטור סטטוס למעלה (פעיל/לא פעיל).
- תצוגת הכתוביות בזמן אמת + הערוצים הפעילים כרגע.

**הכנה לכתוביות חיות (Soniox):**
1. השיגו מפתח API מ‑Soniox והגדירו אותו כמשתנה סביבה לפני הרצת `serve`:
   ```bash
   set STUDIO_TRANSCRIBE_CLOUD_KEY=<soniox-api-key>
   ```
2. בטאב **הגדרות** בחרו את יעד הכתוביות (sink): `obs` / `vmix` / `file`.
3. לחצו **הדלקה** — הכתוביות יזרמו ל‑OBS/vMix וגם יוצגו במסך.

### טאב "תמלול" (מדויק, מקומי — אחרי השידור)
1. הכניסו נתיב לקובץ רב-ערוצי או לתיקיית ערוצים (על ה‑node), למשל `rec/` או
   `C:\recordings\show1.wav`.
2. סמנו פורמטים (TXT/SRT/VTT/DOCX) ולחצו **הרץ תמלול**.
3. בסיום — קישורי הורדה לתוצרים. אם מוגדר DB, התמלול נשמר גם לארכיון.

### טאב "ארכיון" (חיפוש)
- חיפוש full-text בכל מה שתומלל אי-פעם, עם סינון לפי דובר.
- רשימת ההקלטות השמורות.

### טאב "הגדרות"
- **ערוצים ↔ דוברים:** מיפוי מספר ערוץ X32 לשם דובר (ערוץ 1 → "מנחה" וכו').
- **מנוע / device / DB.**
- **יעד כתוביות:** הגדרות OBS (source/host/port), vMix (url/input/field), או קובץ.
- **מילון (glossary):** שמות ומונחי אנגלית לשיפור הדיוק.
- **שמור הגדרות** — נכתב ל‑`config.yaml`.

---

## 5. חיבור הכתוביות ל‑OBS / vMix

### OBS
1. ב‑OBS: Tools → WebSocket Server Settings → הפעילו, רשמו port (4455) וסיסמה.
2. הוסיפו מקור **Text (GDI+)** בשם `captions`.
3. בהגדרות המערכת: sink=`obs`, source=`captions`, host/port/password של OBS.

### vMix
1. ב‑vMix: Settings → Web Controller → הפעילו (port 8088).
2. הוסיפו Title עם שדה טקסט (למשל `Headline.Text`).
3. בהגדרות המערכת: sink=`vmix`, url=`http://127.0.0.1:8088/api/`, input=שם/מספר ה‑Title,
   field=`Headline.Text`.

### חלופה פשוטה (קובץ)
sink=`file`, path=`captions.txt`. ב‑OBS הוסיפו Text עם "Read from file" → `captions.txt`,
או ב‑vMix Data Source שקורא את הקובץ.

---

## 6. הפעלה אוטומטית ב‑Windows (autostart)

### אפשרות A — Task Scheduler
1. Task Scheduler → Create Task.
2. Trigger: At startup.
3. Action: Program = `C:\path\.venv\Scripts\python.exe`,
   Arguments = `-m studio_transcribe serve -c C:\path\config\config.yaml`,
   Start in = `C:\path`.
4. הגדירו את משתני הסביבה (`STUDIO_TRANSCRIBE_PASSWORD`, `STUDIO_TRANSCRIBE_CLOUD_KEY`)
   כמשתני סביבה מערכתיים כדי שיהיו זמינים.

### אפשרות B — NSSM (שירות Windows אמיתי)
```bash
nssm install StudioTranscribe "C:\path\.venv\Scripts\python.exe" "-m studio_transcribe serve -c C:\path\config\config.yaml"
nssm set StudioTranscribe AppDirectory C:\path
nssm set StudioTranscribe AppEnvironmentExtra STUDIO_TRANSCRIBE_PASSWORD=... STUDIO_TRANSCRIBE_CLOUD_KEY=...
nssm start StudioTranscribe
```

---

## 7. מדידת דיוק (מומלץ לפני פרודקשן)

```bash
# תמלול הקלטה קיימת, ואז השוואה מול תמלול-אמת ידני
studio-transcribe eval reference.txt hypothesis.txt
# WER: 4.90%  (S=.. D=.. I=.. N=..)
```
הנרמול תואם את ה‑leaderboard של ivrit.ai, כך שהמספר בר-השוואה.

---

## 8. פתרון תקלות

| תופעה | בדיקה |
|---|---|
| המסך לא נפתח ממחשב אחר | `host: 0.0.0.0`? firewall פתוח לפורט? כתובת IP נכונה? |
| "Soniox live needs an API key" | הגדרתם `STUDIO_TRANSCRIBE_CLOUD_KEY` לפני `serve`? |
| כתוביות לא מגיעות ל‑OBS | ה‑WebSocket של OBS פעיל? שם ה‑source תואם? (אזהרת יעד תוצג במסך) |
| אין device אודיו ברשימה | הותקן `sounddevice`? ה‑DVS/X-USB מופיע כ‑ASIO? |
| תמלול איטי מאוד | רץ על CPU? ודאו GPU של NVIDIA + `device: cuda`. |

הלוג של השרת מודפס בטרמינל (או בלוג של השירות).
