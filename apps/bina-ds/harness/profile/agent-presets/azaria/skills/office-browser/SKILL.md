---
name: office-browser
description: הדפדפן של הלשכה (browser42) — איך מפעילים, כמה זה עולה, הלולאה היחידה של ה-task, ואיך מפרסמים או שולחים הודעה בפייסבוק.
whenToUse: כשצריך דפדפן אמיתי עם סשנים מחוברים — אוטומציה של אתר, QA ויזואלי, צילום מסך של דף, פרסום פוסט או שליחת הודעה בפייסבוק, או כל משימה שדורשת JavaScript/התחברות ולא רק HTTP.
---

# הדפדפן של הלשכה (browser42)

Chromium **אחד**, headed, שיתופי, עם פרופיל מתמיד אחד: הסוכן נוהג בו, והבעלים רואה אותו ב-
`http://browser42.localhost:8080/view/`. אין להרים דפדפן שני ואין לגעת ב-CDP ישירות.
המסמך הקנוני ללולאת העבודה: `ai/context/browser42-cli.md`. קבוצות וסלאגים: `ai/context/browser42-groups.md`.
מתכון פייסבוק (מאומת): `ai/context/setup-facebook-login.md`.

## לקרוא עמוד שלם בלי לגלול (החלון קטן — כ-780x395)

```bash
./bbox b42 task read <slug> [max-chars]        # כל הטקסט של העמוד, בקריאה אחת
./bbox b42 task screenshot <slug> <name> full  # כל העמוד כתמונה אחת, לא רק החלון
```

`read` מהלך על מיכל הגלילה של העמוד עצמו, קורא בכל צעד ומחבר את הצעדים לפי חפיפה (לא לפי שוויון
שורות — זה היה מוחק שורה חוקית שחזרה). זה מה שמחליף גלילה ידנית כדי "להבין את ההקשר": נמדד
2026-10-09 על שיחת סשן בגובה 30,461px — 500,000 תווים ב-49 צעדים, בקריאה אחת. **אל תגלול ביד
כדי לאסוף הקשר** — קרא; ואם צריך גם לראות, `screenshot … full`.

## חידת אנוש (captcha) — המסלול היחיד

ב-2026-10-09 הדפדפן נתקל ב-Claude (claude.ai) בחידת Cloudflare Turnstile בתוך iframe חוצה-מקור.
`inspect` לא רואה אותה בכלל — ה-frame אינו העמוד. המסלול:

```bash
./bbox b42 task captcha <slug> detect           # סוג, ההוראה, יעדים עם קואורדינטות, צילום, ופסיפסים בודדים
./bbox b42 task captcha <slug> click <index>    # יעד אחד או כמה: 0,4,7
./bbox b42 task captcha <slug> click '@x:y'     # קליק לפי פיקסל בעמוד — כשה-DOM לא מגלה את הווידג'ט
```

- `detect` מחזיר `instruction`, `options[{index,x,y,size,role,label,tile}]`, `frames`, `scanned`,
  `token`, ו-`screenshot`. כל אריח-תמונה נשמר כתמונה נפרדת (`tile`) — קוראים אותן ומחליטים.
- **אם `present:false` והצילום מראה ווידג'ט** — זה קורה: ל-Cloudflare יש חידות ששוכנות ב-shadow root
  סגור ואף קריאת DOM לא מגלה (נמדד ב-2026-10-09 בשני אתרים חיים). קרא את הפיקסל של התיבה מהצילום
  (הצילום הוא viewport ב-CSS px — בדיוק היחידות של `page.mouse`) ולחץ `click '@x:y'`.
- אחרי כל קליק מגיע `changed`: `solved` (יצא טוקן) / `advanced` (סבב חדש) / `same` (לא זז).
- **אחרי 3 ניסיונות הכלי מסרב בשם** (`captcha_attempts_exhausted`) ומעביר לבעלים ב-/view. אל תלחץ
  מעבר לזה, ואל תשתמש בשירות פתרון חיצוני — טוקן שנכרה במקום אחר לא שייך לדפדפן הזה, ותמונות העמוד
  הן של הבעלים. הרקע המלא: `ai/context/captcha.md`.

## משאבים — מה זה עולה, ואיך מורידים

הדפדפן הוא **הצרכן הגדול היחיד בלשכה**: 6 קונטיינרים, ~0.7–0.9 GiB RAM, ו-6–12% מליבה אחת
במנוחה (כל שאר הקונטיינרים <1.5% CPU). זה מה שהבעלים הרגיש כ"הלשכה והמחשב נתקעו" (2026-09-22,
host עם 4 ליבות ו-4.9 GiB). המנופים, מהחזק לחלש:

| מנוף | איפה | מה זה נותן |
|---|---|---|
| לא להשאיר אותו דלוק | `./bbox apps disable browser42` + `./scripts/dc stop …` | מוריד את כל ~0.7–0.9 GiB |
| תקרת CPU | `BROWSER42_CPUS` ב-`.env` (כיום **2** מתוך 4 ליבות) | הדפדפן לא יכול לחנוק את שאר הלשכה |
| גודל שולחן העבודה | `BROWSER42_SCREEN_WIDTH/HEIGHT` ב-`.env` (כיום **1280x800**) | כל פיקסל מרונדר בתוכנה ומקודד ל-VNC; 1280x800 = 44% מהפיקסלים של 1080p |
| `scripts/ops/quiet-mode.sh` | `quiet browser42` | התנוחה המתועדת של הפלטפורמה תחת לחץ זיכרון |

```bash
# הפעלה
./bbox apps enable browser42 && python3 platform/manager/reconcile.py render
./scripts/dc up -d browser42-browser browser42-mcp browser42-caddy \
                   browser42-reaper browser42-task-runner browser42-task-watchdog
./scripts/dc restart console          # בלעדיו האריח מחזיר {"app":"browser42","error":"unknown_app"}

# כיבוי (הנתונים נשמרים ב-volume cloakprofile)
./bbox apps disable browser42
./scripts/dc stop browser42-browser browser42-mcp browser42-caddy \
                  browser42-reaper browser42-task-runner browser42-task-watchdog
```

`platform.state.yaml` נכתב רק דרך `./bbox apps enable|disable`. **אין** להוריד את תקרת הזיכרון
(1536M) — ה-high-water המדוד עם עץ Chromium חי הוא 788MiB, ו-1.5G הוא ~1.95x ממנו.

## הלולאה היחידה

כל עבודה בדפדפן עוברת דרך `./bbox b42 task ...` (לא Playwright, לא CDP, לא curl, לא סקריפטים):

```bash
# מסלול מהיר — קריאה/איסוף מדף אחד: goto→settle→extract→screenshot→verify→finish בפקודה אחת
./bbox b42 task goal <slug> <direct-https-url> <topic>

# מסלול צעד-אחר-צעד (משימה אינטראקטיבית: מילוי טופס, לחיצה, פרסום)
./bbox b42 task start <slug> <direct-https-url> '{"minimum_extractions":0,"minimum_records":0}'
./bbox b42 task inspect <slug> "<טקסט שמופיע על המסך>"
./bbox b42 task click   <slug> <handle>
./bbox b42 task fill    <slug> <handle> "<טקסט>"
./bbox b42 task press   <slug> <handle> Enter
./bbox b42 task screenshot <slug> <name>
./bbox b42 task verify  <slug>
./bbox b42 task finish  <slug>          # רק finish מחזיר תוצאה מדווחת
```

- **slug קבוע ומקורי** (kebab-case), זהה בכל פקודה. אין לאמץ סלאג של משימה אחרת.
- **handle** מגיע רק מ-`inspect` האחרון (`b42h:...`). אין להמציא selector או URL.
- תמיד להעביר fragment של טקסט ל-`inspect` — בלעדיו זה איטי, והתשובה נחתכת ל-40 פקדים (ולכן פקד
  בתוך דיאלוג לא יופיע בלי סינון).
- הראיות נכתבות ל-`data/browser42/tasks/<slug>/` (מסך + `result.json`).
- **קצב**: ה-watchdog מסמן משימה `stalled` אחרי 5 דקות בלי פעילות. משימה אינטראקטיבית רצה ברצף אחד,
  לא בפערים של דקות בין צעד לצעד.
- סגירה בסוף: `./bbox b42 close <slug>`, ו-`./bbox b42 groups` לראות מה פתוח.

## פייסבוק

הפרופיל הוא חשבון הבעלים. **לפני כל עבודה — לוודא שהסשן חי**: `start` על `https://www.facebook.com`
ואז `inspect "mind"`; אם מופיע טופס התחברות, הסשן מת (ראה Gotchas) ובקש מהבעלים להתחבר דרך `/view`.

- **פרסום פוסט** (מאומת 2026-09-22): `start` → `inspect "mind"` → `click` על הכפתור
  `What's on your mind, <name>?` → `inspect "mind"` → **textbox** → `fill` בטקסט →
  `screenshot before-post` → `inspect "Post"` → `click` על `button` בשם `Post` (או `פרסום`) →
  `screenshot after-post` → `verify` → `finish`. ראיה מלאה: `data/browser42/tasks/fb-post-1755/`.
- **עריכת פוסט שפורסם** (מאומת 2026-09-22): בציר הזמן של הבעלים (`facebook.com/<vanity>`) —
  `inspect "Actions for this post by <שם>"` → `click` → `inspect "Edit post"` → `click` על ה-menuitem →
  `inspect "mind"` → `fill` (**מחליף את כל התוכן**) → `screenshot before-save` → `click` על `Save` →
  `screenshot after-save`. פייסבוק שומרת את הפוסט והתאריך המקוריים (זו עריכה, לא פרסום מחדש), וכרטיס
  התצוגה המקדימה שורד. ראיה: `data/browser42/tasks/fb-edit-1807/`. מחוץ לציר הזמן הפוסט עלול להיות
  מתחת לקפל, ו-`inspect` רואה רק מה שנראה.
- **שליחת DM**: `scripts/fb-send.py` (נוגע רק בתיבת `Write to <name>`, לעולם לא בתיבת תגובה פומבית).
  Gotcha: מודאל Messenger "Enter your PIN" — לסגור עם "Don't restore messages".
- קישור בטקסט הופך אוטומטית לכרטיס תצוגה מקדימה — לבדוק אותו בצילום `before-post` לפני הפרסום.

## Gotchas שהוכיחו את עצמן

- **אל תעשה restart/stop/up לקונטיינר הדפדפן כשהסשן חשוב.** ב-2026-09-22 התחלה קרה (CDP לא ענה ~60ש'
  → autoheal הפעיל מחדש) גרמה ל-cloakserve למחוק את `/profile/__default__` — כל ה-cookies כולל
  ההתחברות לפייסבוק אבדו, ואין שחזור בלי `state dump`. התחלה חמה היא ~10–18ש' ותקינה; המסוכן הוא הקור.
- **אחרי כל התחברות — לגבות מיד**: `./bbox b42 state dump` (דורש `BROWSER42_STATE_PASSPHRASE` ב-`.env`;
  שחזור: `./bbox b42 state load`). הסקריפט **עוצר את הקונטיינר** לצילום עקבי — גם הגיבוי עצמו הוא רגע
  רגיש, ועדיף לעשות אותו כשאין משימה באוויר.
- **קובץ שמוטמן (bind mount) עלול להתקע בגרסה קטועה ב-macOS/Lima (virtiofs).** אחרי עריכה של
  `apps/browser42/group-manager.py` הקונטיינר המשיך להריץ גרסה בת 1287 שורות (במקום 1324) והחזיר
  `SyntaxError`/`runner_protocol_error`. הפתרון: `./scripts/dc restart <הקונטיינר שקורא את הקובץ>`
  (`browser42-task-runner` מריץ את group-manager.py לכל בקשה; `browser42-browser` מריץ אותו רק עבור
  `bbox b42 close|groups|session`). בדיקה: `docker exec <ctr> md5sum /group-manager.py` מול המארח.
- **עורך contenteditable** (תיבת הפוסט של פייסבוק) הוא `div[contenteditable][role=textbox]` בלי
  `aria-label` — הרמז היחיד שלו הוא `aria-placeholder`. עד 2026-09-22 `inspect` אסף אותו ואז זרק אותו
  (שם ריק), כלומר אי אפשר היה למלא אותו. תוקן ב-`group-manager.py`: השם נלקח גם מ-`aria-placeholder`/
  `data-placeholder`, ו-`locate` נופל ל-`[role=…][aria-placeholder=…]` כששם נגיש ריק.
- **הפרופיל מוגן (2.0.0)**: צילום חי ב-`data/browser42/profile-snapshot/`, שחזור אוטומטי באתחול
  ובזמן ריצה (watcher כל 20ש'), וצילום טוב לא נדרס לעולם ע"י פרופיל מחוק. אם בכל זאת נמחק — הקונטיינר
  מופעל מחדש לבד וההתחברות חוזרת מהצילום; אין צורך בהתחברות מחדש. גיבוי נוסף: `bbox b42 state dump`.
- **חלון אחד תמיד**: באתחול נסגרים חלונות Chromium מיותרים (הם נשארים מלולאת ה-retry של ההפעלה).
  אין לפתוח חלון שני — זה משותף לסוכן ולבעלים.
- התחלה קרה אחרי ימים של חוסר-פעילות איטית ודופקת (Chrome נופל ומוקם כמה פעמים עד ש-CDP מתייצב);
  אין להתחיל משימה בזמן הזה.
- **תחת עומס (3 דפים כבדים במקביל) הדפדפן מבקש 2.5–3.6 ליבות ו-1.45 GiB.** עם התקרה של 2 ליבות
  נמדדו ריסון ב-23.5% מהתקופות, `sustained CDP outage` שהפעיל את הקונטיינר מחדש, ומשימה שנכשלה;
  עם 4 ליבות הכול עבר אבל ההשהיה של שאר הלשכה הוכפלה. המדידה המלאה, ההמלצות והמחירים:
  `ai/context/browser42-resource-and-load-report-2026-09-22.md`.
- host חדש מחזיר 404 מהקצה עד `./scripts/dc restart traefik-deployment`; אריח חסר או
  `{"error":"unknown_app"}` בקונסול — `render` ואז `./scripts/dc restart console`.
- `presentation compact mode was not applied` בלוג הוא רעש לא מזיק.

## מסמכים

| נושא | קובץ |
|---|---|
| לולאת ה-task, סכמת התוצאה, קודי שגיאה | `ai/context/browser42-cli.md` |
| groups, session slug, reaper/gc | `ai/context/browser42-groups.md` |
| פייסבוק — פרופיל, פרסום, DM, מודאלי E2EE | `ai/context/setup-facebook-login.md` |
| כיבוי אפליקציות לא-קריטיות תחת לחץ זיכרון | `scripts/ops/quiet-mode.sh` |
