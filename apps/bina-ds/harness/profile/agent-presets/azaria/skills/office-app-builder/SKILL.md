---
name: office-app-builder
description: איך בונים או משנים אפליקציה של הלשכה הדיגיטלית — איפה המסמכים, מה הדוגמאות, ומה סדר ההרמה והאימות.
whenToUse: כשמבקשים ממך לפתח, לשנות או לתקן אפליקציה של הלשכה (apps/<id>/).
---

# בניית אפליקציה ללשכה

## קרא קודם (בסדר הזה)

1. `ai/context/build-your-first-app.md` — האנטומיה המלאה: app.json, compose, routing/module, SSO, חיבורים, נתונים, השערים.
2. `platform/schema/app.schema.json` — כל שדה מותר ב-app.json; `module.group` הוא רק `ראשי` / `עסק` / `תשתית` / `הגדרות`.
3. דוגמאות: `apps/hello-bina/` (המינימום), `platform-base/machine/` (FastAPI + UI בעברית עם ערכת bina-ui), `apps/drive/app.py` + `apps/drive/connections_client.py` (ניהול מופעים לפי `ai/context/platform-service-contract.md`).
4. אייקונים לאריח: המפה `ICONS` ב-`platform-base/console/static/app.js`.

## כללים שנכשלים בשקט אם שוכחים

- `title` ו-`summary` הם `{he, en}`; שם התיקייה = `id`; host / module.id / alias ייחודיים.
- ב-UI רק כתובות יחסיות (הקונסול מגיש ב-`/a/<alias>/` ומזריק `<base href>`).
- healthcheck רק עם בינארי שקיים באימג' (python, לא curl).
- ערכת העיצוב מקובצת בתוך `static/` של האפליקציה; אחרי העתקה `python3 scripts/refactor/theme-token-lint.py --fix`.
- `data.volumes` תואם ל-compose; `resources` קטן (128M–384M).
- מספרים, IP, נתיבים ופקודות בטקסט עברי: `direction:ltr; unicode-bidi:isolate`.

## סדר ההרמה

```bash
python3 platform/manager/reconcile.py validate
./bbox apps enable <id>
./scripts/dc up -d --build <id>
./scripts/dc ps <id>; ./scripts/dc logs --tail 50 <id>
./scripts/dc restart traefik-deployment   # host חדש מחזיר 404 עד הסנכרון
./scripts/dc restart console              # האריח החדש בסרגל
```

## לפני "סיימתי"

`python3 scripts/refactor/<gate>-lint.py` עבור: layering (--strict), healthcheck, image-pin, data-volumes, engine-bypass, theme-token, capability-use (--strict), memory-budget. הרשימה והרציונל: `scripts/refactor/GATES.md`. ואז בדיקה אמיתית בדפדפן: `http://console.localhost:8080` → הסרגל → האפליקציה.

**שינוי חזותי** (מסך, עיצוב, תוכן שאנשים רואים) נגמר גם בציון יופי, בצילומי מסך ובניתוח שלך — ראו
`office-operations` § „שינוי חזותי”. זה חלק מההגדרה של „סיימתי”, לא תוספת.
