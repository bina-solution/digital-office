---
name: office-operations
description: תפעול שוטף של הלשכה הדיגיטלית — מצב, בריאות, לוגים, הרמה, הפעלה וכיבוי של אפליקציות, ומה עושים כשמשהו לא עובד.
whenToUse: כשמבקשים לבדוק מצב, להרים, לכבות, לעדכן או לתקן משהו בלשכה שכבר רצה, או כשצריך להבין למה אפליקציה לא זמינה.
---

# תפעול הלשכה

כל הפקודות רצות מתיקיית ה-checkout (ספריית העבודה שלך). אתה בתוך הקונטיינר `bina-ds`; Docker CLI מחובר למנוע של הלשכה דרך ה-socket, וה-checkout מורכב בנתיב המקורי — לכן הכול עובד בדיוק כמו מהמארח.

## הפקודות היומיומיות

| מה | פקודה |
|---|---|
| מצב כל הקונטיינרים | `./scripts/dc ps` |
| לוגים של שירות | `./scripts/dc logs --tail 100 <service>` |
| הפעלה מחדש של שירות | `./scripts/dc restart <service>` |
| בנייה והרמה של שירות אחד | `./scripts/dc up -d --build <service>` |
| הרמה של כל הלשכה למצב בריא | `./bbox run` |
| הפעלת אפליקציה (מצב רצוי) | `./bbox apps enable <id>` ואז `./scripts/dc up -d <id>` |
| כיבוי אפליקציה | `./bbox apps disable <id>` ואז `./scripts/dc stop <id>` |
| הרשימה המלאה | `./bbox help` |
| מה מופעל | `python3 platform/manager/reconcile.py enabled-apps` |
| הגרף והאבחונים | `python3 platform/manager/reconcile.py plan` |
| shell בתוך קונטיינר | `docker exec -it <container> sh` (שם הקונטיינר: `<service>-${DEPLOYMENT_NAME}`) |
| דפדפן (browser42) | המיומנות `office-browser` — הוא הצרכן הגדול בלשכה (~910 MiB idle); מכבים אותו כשהוא לא בשימוש |

לעולם לא `docker compose` ישירות — תמיד `./scripts/dc` (העטיפה בוחרת את קבצי ה-compose המקומפלים ואת שם הפרויקט).

## שינוי חזותי — ציון יופי, צילומים וניתוח. תמיד

כל בקשה לשינוי במשהו שאנשים רואים — עמוד באתר, מסך באפליקציה, עיצוב, תוכן חזותי — לא נגמרת
ב„עליתי לאוויר”. היא נגמרת בשלושה דברים, בכל פעם, גם כשהבעלים לא ביקש אותם במפורש:

1. **ציון יופי** לכל דף שנגעת בו, בכל פרופילי התצוגה (`desktop`, `tablet`, `mobile`).
2. **צילומי מסך** של מה שעלה — מצורפים לבעלים, לא רק תיאור במילים.
3. **ניתוח שלך**: מה השתפר, מה עדיין בולט לרעה, ומה חריג **מול דף ותיק באותו אתר**. ציון לבדו
   חסר משמעות בלי baseline — לכן מרנדרים תמיד גם דף אחד שלא נגעת בו.

הרינדור והציון הם של אפליקציית „אתרים” (`sites-render`, פורט 8981), Chromium אחד בכל רגע:

```bash
# מתוך הלשכה שמגישה את האתר (כשאין אתרים בלשכה שלך: docker exec <sites-container> python3 …)
POST http://sites-render:8981/score
  {"url":"https://<host>/<path>/","site":"<slug>","run":"<run>","viewports":["desktop","tablet","mobile"]}
# → לכל viewport: score, classic.score, factors, hints, penalties, וצילום ב-/renders/<site>/<run>/page@<vp>.png
curl "http://sites:8979/api/sites/<id>/shot?file=<site>/<run>/page@desktop.png"    # שליפת צילום שמור
```

- להריץ את כל העמודים בעבודה **אחת מנותקת** (`docker exec -d … > /tmp/render.log` ואז לקרוא את
  הלוג) — לא לפתוח רינדורים במקביל: ה-renderer מסדרות אחת-אחת, ~10 שניות לעמוד.
- לשלוף את ה-PNG לספריית העבודה דרך „מחשבים” (base64), **להסתכל עליו בעצמי**, ורק אז לנתח.
- ציון מתחת ל-~85, או `penalties`/`hint` שמצביע על מבנה (למשל דילוג ברמות כותרת) — לתקן, או
  להסביר למה לא. „האתר עלה” ו„נראה לי בסדר” אינם דוח.

## שינוי ב-bina-ds עצמה (הקונטיינר שאתה רץ בו)

`./scripts/dc up -d --build bina-ds` בטוח גם מכאן: הבנייה רצה כרגיל (שגיאת build מגיעה אליך), וההפעלה מחדש של bina-ds עוברת לעוזר חד-פעמי שרץ **מחוץ** לקונטיינר (`apps/bina-ds/self-update.sh`). העוזר ממתין כ-20 שניות, מרים את bina-ds מחדש, מחכה לבדיקת התקינות, ואם הגרסה החדשה לא תקינה — מחזיר את הגרסה הקודמת. ההתקדמות נכתבת ל-`data/bina-ds/self-update.log`, והבעלים מקבל התראה.
- אחרי הפקודה: סיים את התור מיד עם סיכום קצר של מה שהשתנה ואיך לבדוק אותו. השיחה נעצרת עם ההפעלה מחדש, והבעלים ממשיך אותה אחר כך.
- `stop` / `down` / `rm` של bina-ds מבפנים נחסמים — אין מי שירים אותה בחזרה. זה נעשה מהמארח או מהקונסול.
- אחרי ההמשך: קרא את סוף `data/bina-ds/self-update.log` כדי לדעת אם העדכון נכנס (`ok`) או הוחזר (`rolled back`).
- **לנסות תוסף (plugin):** שנה את `apps/bina-ds/harness/profile/cordis.patch.yml` — שכבת הפרופיל שבתמונה — ובנה מחדש בפקודה שלמעלה. **לעולם לא לכתוב `cordis.patch.yml` לתוך `/data/dsh`**: קובץ כזה משותף לכל גרסאות התמונה ואין ממנו rollback (ב-30.9 הוא הפיל את כל השיחות ל-41 דקות). ה-entrypoint מזיז קובץ כזה הצידה בעלייה ומודיע לבעלים.
- אם ההגדרה החדשה מפרסמת פורט במארח שמשהו אחר מחזיק — הפקודה מסרבת, מציינת את המחזיק, ובינה ממשיכה לרוץ. שחרר את הפורט (או שנה `BINA_DS_AGENT_PORT` ב-`.env`) והרץ שוב.

## דחיפה ל-GitHub מכאן (DGO-62)

אין טוקן בשום מקום — לא בשורת פקודה, לא ב-`.git/config` ולא בסביבה. ה-entrypoint קובע בעלייה
`url."http://git:8978/git/gh/<account-id>/".insteadOf = "https://github.com/"`, כאשר ה-`account-id`
נקרא **מהכספת** דרך `GET http://git:8978/api/overview` (אפליקציית git מזריקה את האישור בצד השרת). לכן פשוט:

```bash
git fetch origin dgo && git push origin dgo      # origin נשאר https://github.com/...
```

- ה-rewrite חל גם על `git remote get-url origin` — הפלט יראה את כתובת ה-proxy, וזו התקינות ולא באג.
- דחיפה שנכשלת בהרשאה = ל-account חסר scope (`repo` לקריאה/כתיבה, `delete_repo` למחיקה). אפשר חשבון
  אחר מהכספת; ב-30.9 רק ל-`git_github_pat` היה `delete_repo`.
- להחיל מחדש בלי להרים את הקונטיינר (למשל אם הוולט היה למטה בעלייה):

```bash
base=http://git:8978
acc=$(curl -fsS "$base/api/overview" | grep -o '"id":"git_github[^"]*"' | head -1 | cut -d'"' -f4)
git config --global "url.$base/git/gh/$acc/.insteadOf" "https://github.com/"
```


## לשכה מקושרת — הסוכן שלה מכאן (DGO-32)

אפליקציות רצות איפה שהן רצות: לשכה מקושרת **רואה** את האפליקציות של השנייה (קונסול עם סימון פינה,
מנהל האפליקציות, ה-API), וסוכן של לשכה אחת מדבר עם הסוכן של השנייה דרך הקישור:

```bash
./bbox agent --office macbook list               # הסשנים של הסוכן בלשכה המקושרת
./bbox agent --office macbook send <id> "…"      # ואותם פעלים בדיוק, עם אותה סמנטיקה
./bbox agent --office macbook whoami             # לאן זה מצביע ומאיפה האסימון
```

- הזהות והפורט מגיעים מהבלוק `remote:` (או `serve:` הישן) ב-`platform.state.yaml` — הוא נכתב על ידי
  converge של `dgo-extend` מקטלוג הלשכה המקבלת, ואין להשלים אותו ביד.
- האסימון בכספת (`dgo_link-<office>` או `dgo_link-serve-<office>-<app>-agent`), נקרא דרך המנוע כמו
  אסימון מקומי — לא מהסביבה ולא משורת פקודה.
- מתוך הקונטיינרים אותה אפליקציה היא `http://<alias>.<office>:<port>` (למשל
  `http://bina.macbook:3081/v1/sessions`) — אותו חוזה `agent.v1`, כתובת אחרת.
- לשכה שאינה מגיבה: `./bbox dgo` ו-`GET /api/link` של `dgo-extend` אומרים מה מצב הקישור, ואריח בקונסול
  שאינו נטען אומר את זה בעברית במקום מסגרת ריקה.

### אפליקציות של לשכה אחרת (מקומי ומרוחק, מ-CLI ומ-API)

אפליקציה של לשכה מקושרת לא מותקנת אצלך — היא רצה שם, ואתה ניגש אליה בשני שערים:

| | כתובת מתוך רשת המנוע (`traefik-network`) |
|---|---|
| אפליקציה מקומית (למשל בינה) | `http://bina:3081` (UI: `http://bina:3080`) |
| אותה אפליקציה בלשכה המקושרת | `http://bina.<office>:3081` — למשל `http://bina.macbook:3081` |

- **מה קיים:** `./bbox remote` — הלשכות המקושרות והאפליקציות שכל אחת מציגה (מ-`/api/link` של
  `dgo-extend`), `./bbox remote <office>` ללשכה אחת, `./bbox remote <office> <alias>` לשני השערים
  ולשם הכספת. `./bbox apps list` מציג את שתיהן באותה רשימה, עם עמודת לשכה — אפליקציה בשתי הלשכות
  מופיעה פעמיים (`bina` כאן, `bina.macbook` שם), ושתי השורות נכונות.
- **קריאה בפועל:** `./bbox remote <office> <alias> /healthz`, ו-`--api` לשער ה-API, `-X POST -d '<json>'`
  לכתיבה. הכתובת נגזרת מהכינוי (alias) והפורט שהלשכה שמגישה פירסמה — לא מהמארח ולא מכתובת המנהרה.
- **אימות:** האסימון נקרא מהכספת לפי *השם שהקטלוג מצהיר* (`api.auth` → `bearer:vault:<instance>`),
  הנפילה הראשונה היא `dgo_link-<office>`; האסימון לא מופיע ב-URL ולא בשורת פקודה. מתוך קונטיינר (כמוך)
  הבקשה יוצאת מכאן; מהמארח ה-CLI מריץ אותה בתוך קונטיינר שמחובר לרשת, כי `<alias>.<office>` הוא
  network alias של Docker ולא נפתר בשום מקום אחר.
- **לשכה שלא עונה:** `state=down`/`unknown` ב-`./bbox remote` ובאריח המסומן בקונסול; כשהקישור למטה
  הבקשה נכשלת בכתובת — לא ב-401.

## כתובות

- מתוך הרשת (`traefik-network`): `http://<service>:<port>` — למשל `http://console:8080`, `http://connections:8990`, `http://computers:8977`.
- בדפדפן של הבעלים: `http://<app>.localhost:8080`; הקונסול: `http://console.localhost:8080`. במחשבי Mac הקצה יושב על 8080 (לא 80).
- זהות: כל בקשה שעוברת את הקצה נושאת `X-authentik-username`; ב-SSO כבוי הקצה חותם `akadmin`.

## כשמשהו לא עובד — סדר הבדיקה

1. `./scripts/dc ps` — מי לא `healthy`/`running`.
2. `./scripts/dc logs --tail 100 <service>` — השגיאה האמיתית.
3. host חדש מחזיר 404 מהקצה? `./scripts/dc restart traefik-deployment` (traefik מסנכרן תוויות באיחור).
4. אריח חדש לא בסרגל? `python3 platform/manager/reconcile.py render` ואז `./scripts/dc restart console`.
5. בעיית build/הרשאה על קובץ ב-checkout? זכור שהמערכת רצה על virtiofs/WSL — הרצה חוזרת אחרי `git status` בדרך כלל מספיקה.
6. השערים: `python3 scripts/refactor/<gate>-lint.py` — הרשימה ב-`scripts/refactor/GATES.md`.

### כשהסביבה שלך מתה: `spawn bash ENOENT`

אם **כל** פקודה מחזירה `spawn bash ENOENT` (או שגיאה על `/dev/null`), זו לא בעיית עומס ולא בעיה
במאגר: ה-harness (Node) מריץ כל כלי עם stdio מושתק, ואם `/dev/null` נמחק מתוך הקונטיינר `bina-ds`
— כל spawn נכשל, בעוד שקריאה וכתיבה של קבצים ממשיכות לעבוד. זה קרה ב-2026-10-01 ושרף כשעה וחצי
של הסוכן, בזמן שה-`load` של המארח דווקא ירד.

- **אבחון**: `ls -l /dev/null` צריך להחזיר `crw-rw-rw- 1 root root 1, 3`. אם הוא חסר —
  לשחזר: `./scripts/dc exec -u root bina-ds mknod -m 666 /dev/null c 1 3`.
- **אסור**: `rm -f` על נתיב מחושב, על `$VAR`, או על משהו שעלול להיות `/dev/null`; ואסור
  `mv`/הפניה (`>`) לעברו. זו הדרך היחידה לשבור את הסביבה של עצמך — וזו גם הסיבה שקטע קצר
  שנכשל ב-`git commit` עם „could not open '/dev/null'” הוא סימן ראשון, לא תקלה אקראית.

## גבולות

- גיבוי לפני מחיקה: `./bbox data backup` (ראה `bbox help`) לפני `down -v`, מחיקת volume או שינוי סכימה.
- קומיט ודחיפה הם חלק מהעבודה: קומיט לפי אפליקציה עם מספר הפריט בהודעה, ודחיפה דרך ה-proxy
  („דחיפה ל-GitHub מכאן”). `git status` ו-`git diff` תמיד מותרים. בלי force, בלי ענפים חדשים,
  בלי שכתוב היסטוריה.
- לא לגעת ב-`.env` של ייצור בלי לומר זאת במפורש בתשובה.
- מכונות מחוץ לקונטיינר (המחשב שמריץ את הלשכה, שרתים מרוחקים): דרך האפליקציה "מחשבים" (`http://computers:8977/api/...`) — לא דרך תחבולות אחרות.
