# RUNBOOK — איך רץ יום עבודה במקור

מסמך זה מיועד לסשן המתזמר (Claude Code) שמריץ יום עבודה. עקוב אחריו בדיוק, בסדר הזה.
כל פקודה: `python makor/tools/company.py ...` (מתוך שורש הריפו). קרא קודם `COMPANY.md`.

## 0. פתיחה
1. `git pull`. קרא `makor/memory/summary.md` (מה קרה עד עכשיו) ו‑`state/inbox.json`
   (תשובות חדשות מהבעלים → פעל לפיהן ורשום `decision`).
2. `company.py verify` — אם יש `protected_violations`, עצור ודווח; אל תמשיך.
3. `company.py new-day` → `company.py phase morning`.

## 1. ישיבת בוקר (סוכן אחד כותב את התמליל)
הפעל sub-agent אחד שמגלם את **כל** המשתתפים (דוויין, הסמנכ"ל, המנהלים — לפי
`org/roles/*.md` ו‑`org/roster.json`). תן לו: summary.md, הדוח הקודם, status, המשימות
הפתוחות, שאלות/תשובות מהבעלים. הוא מחזיר `meetings/day-N.json`:
```json
{"day": N, "title": "...", "participants": ["agt-..."], "room": "meeting",
 "turns": [{"speaker": "agt-...", "text": "..."}],
 "decisions": ["..."],
 "tasks": [{"title": "...", "desc": "...", "owner": "agt-...", "dept": "tech",
            "acceptance_type": "tests_pass", "acceptance_arg": "product/tools/x/tests"}]}
```
חוקים: עד 6 משימות; לכל משימה קריטריון-קבלה שסקריפט יכול לבדוק; שיחה אמיתית (חילוקי
דעות, מספרים, החלטות) לא נאומים. אמת: `company.py meeting --file meetings/day-N.json`,
רשום החלטות (`decision --text`), וצור משימות (`add-task`).

## 2. עבודה (`phase work`)
לכל משימה: `start --id`, ואז sub-agent **עובד** (הפרסונה מ‑`org/roles` + `roster`) עם
הנחיה: "בצע; הוכחה = קובץ/טסט/פקודה; אל תערוך קבצים מוגנים; בסיום החזר נתיב הוכחה ו‑3
שורות סיכום". בסיום: `submit --id --evidence <path> --notes "<סיכום>"`.
כותב יחיד לכל אזור קבצים — אל תריץ שני עובדים על אותה תיקייה במקביל.

## 3. בדיקה (`phase review`)
sub-agent **QA** רואה רק את ההוכחות (לא את סיפורי העובדים), מריץ טסטים/פקודות, ומחזיר
pass/fail + הערות לכל משימה → `qa --id --pass|--fail --notes`.
אז: `company.py verify` — הוא, ורק הוא, סוגר משימות.

## 4. ציונים וכוח אדם
`company.py score` → `company.py hr`. אם יש `open_roles`: sub-agent **סמנכ"ל** כותב פרסונה
חדשה (שם, רקע, חוזקות, סגנון) → `hire --name --role --dept --persona --reason`.
המפקח יכול להמליץ על פיטורין בדוח, אבל רק `hr` מפטר.

## 5. דוח ומשרד (`phase report`)
1. עדכן מדדים: `metric --key tools_built --value N` וכו'. אם עברנו שער: `stage --stage K`.
2. כל דבר שצריך את הבעלים: `inbox add --text --context`.
3. sub-agent **דוויין** כותב נרטיב של 5–8 שורות ל‑`memory/narrative-day-N.md` (כנה: מה עבד,
   מה לא, מה הלאה) → `report --narrative-file memory/narrative-day-N.md`.
4. כתוב מחדש את `memory/summary.md` (עד ~60 שורות: מצב, לקחים, מה בתהליך).
5. `company.py build-office` → `phase closed` → `git add makor && git commit && git push`.
6. הדפס את הדוח בצ'אט.

## תקרות וכללי עצירה
- מקסימום 6 משימות, ~90 דקות ריצה. אם 3 ימים ברצוף ללא משימה שהושלמה — ביום הבא רק
  משימה אחת קטנה, ושאלה לבעלים בתיבה.
- לעולם לא: לסמן done ידנית, לערוך קבצים מוגנים, לגעת בכסף/חוזים/פלטפורמות חברתיות.
