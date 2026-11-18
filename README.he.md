<div dir="rtl">

# הלשכה הדיגיטלית · DGO — the digital office

**הלשכה הדיגיטלית (DGO) מבית בינה סולושנס: לשכה עסקית שלמה על מחשב משלכם — דואר, מסמכים והאוטומציות שלהם,
פגישות, פרויקטים, קבצים, צ׳אט וסוכן AI. קוד פתוח, מותקן אצלכם, בעברית מהיסוד. [digital-office.co.il](https://digital-office.co.il)**

‏[English](README.md) · [לתרום](CONTRIBUTING.he.md) · [אבטחה](.github/SECURITY.md) · AGPL-3.0

הלשכה הדיגיטלית מריצה את הלשכה של עסק קטן על מחשב אחד משלו — שרת, מחשב נייד או Mac. כל אפליקציה היא קונטיינר,
כל המערכת נבנית מהצהרות, ופקודה אחת מרימה אותה. המידע של הלשכה נשאר על המחשב הזה; סוכן ה-AI מדבר עם ספק המודל
שאת המפתח שלו נתתם לו. המסכים בעברית ומימין לשמאל, ויש גם אנגלית מובנית (`./bbox lang en`).

**מצב:** גרסה 0.3 — מוקדמת, ובשימוש יומיומי אצל העסקים שבונים אותה ואצל הלקוחות הראשונים. היא משתנה מהר.
(אין קשר לשירות הממשלתי שנקרא באותו שם.)

## מה מקבלים

| | |
|---|---|
| **מסך ראשי אחד** | הקונסולה: כל אפליקציות הלשכה מאחורי כניסה אחת, במחשב ובטלפון |
| **דואר** | הדואר של הלשכה, עם תוויות וכללים |
| **מסמכים נכנסים** | חשבוניות וקבלות שנקראות ב-OCR, ממוינות ומתויקות באוטומציות |
| **אוטומציות** | תהליכי n8n, שנשמרים במאגר כקוד |
| **פגישות** | פגישות וידאו (Jitsi) עם הקלטות ותמלול |
| **פרויקטים** | לוח פרויקטים (Plane) עם משימות ומודולים |
| **קבצים** | כונן משותף, ולצידו Google Drive |
| **צ׳אט** | הצ׳אט של הלשכה, עם WhatsApp ו-Telegram דרך החיבורים שלה |
| **סוכן AI** | סוכן שעובד בתוך הלשכה, עם הכלים שלה — ודפדפן שהוא יודע להפעיל |
| **לשכות מקושרות** | לשכות מתחברות זו לזו בקישור מוצפן ומשאילות זו לזו אפליקציות, בלי לפתוח אותן לאינטרנט |

**[קטלוג האפליקציות](apps/README.md)** מפרט את כל האפליקציות של הגרסה הזו, כל אחת מתוך המניפסט שלה; בתיקייה של כל אפליקציה כתוב מה היא
(`app.json`) ואיך מפעילים אותה (`AGENT.md`).

## התקנה

**בפקודה אחת** (Debian/Ubuntu ו-macOS; ב-Windows הפקודה מסבירה את ההכנה ב-WSL):

```bash
curl -fsSL https://digital-office.co.il/install.sh | bash
```

**מתוך עותק של המאגר**, בשרת Debian או Ubuntu:

```bash
git clone https://github.com/bina-solution/digital-office
cd digital-office
./debian-install.sh       # Docker and its compose plugin, and a .env from .env.ex
./bbox run                # compile the office, then bring it up
```

לפני `bbox run`, הגדירו ב-`.env` את הדומיין, את שם העסק ואת שאר הערכים. אם סקריפט ההתקנה הוסיף אתכם לקבוצת `docker`,
התנתקו והתחברו מחדש קודם.

**בלי דומיין — מחשב נייד, או מבט ראשון:** בלי `.env`, והלשכה יוצרת לעצמה אחד מקומי:

```bash
DGO_LOCAL=1 ./debian-install.sh   # no .env
./bbox run                        # a local office, every app at <name>.localhost
```

מחשב שכבר הריץ לשכה ואיבד את ה-`.env` שלו לא מקבל חדש: סודות חדשים לא היו פותחים את המידע שכבר נמצא שם.

- ב-**macOS:** משכפלים ומריצים `./bbox run` — הפקודה מקימה מנוע משלה וכותבת `.env` מקומי; הלשכה בכתובת
  `http://console.localhost:8080` ([packaging/macos.md](packaging/macos.md)).
- ב-**Windows:** פעם אחת לכל מחשב, מ-PowerShell כמנהל מערכת: `wsl --install -d Ubuntu`, הפעלה מחדש, ופתיחה של Ubuntu
  פעם אחת. אחר כך משכפלים לתיקייה בכונן `C:`, ומתוכה מריצים `bbox.cmd install windows` (ייתכן שיבקש `wsl --shutdown`
  אחד והרצה שנייה), ואז `bbox.cmd run` ([ai/context/running-on-wsl.md](ai/context/running-on-wsl.md)).
- עם **Claude Code:** `/plugin marketplace add bina-solution/digital-office`, ואחריו
  `/plugin install digital-office@digital-office`, והסוכן מתקין את הלשכה בשבילכם.

**מה המחשב צריך:** לשכה של כ-60 קונטיינרים, עם אתרים ציבוריים והקלטות פגישות, רצה על 2 מעבדים ו-8GB זיכרון עם swap,
ותופסת כ-44GB דיסק לאימג׳ים של Docker ולמידע. גם Mac עם Apple Silicon ו-8GB מריץ לשכה מקומית. פחות אפליקציות צריכות
פחות ([ai/context/running-the-stack.md](ai/context/running-the-stack.md)).

## השעה הראשונה

1. **הופכים למנהלים.** ההרצה הראשונה של `./bbox run` מדפיסה שורה אחת,
   `[forward-auth] first run: open <sign-in address>/setup?code=…`. פתחו אותה לפני כל אחד אחר: בוחרים שם וסיסמה של
   12 תווים לפחות, ונהיים המנהלים הראשונים של הלשכה. הקישור מפסיק לעבוד ברגע שיש מנהל.
2. **פותחים את הקונסולה** — `http://console.localhost` (ב-Mac עם `:8080`), או כתובת הקונסולה של הדומיין שלכם
   (`CONSOLE_BASE_URL` ב-`.env`).
3. **נותנים לסוכן מודל.** ב«חיבורים ומפתחות» מוסיפים מפתח של ספק המודל שבחרתם; הסוכן משתמש בו.
4. **מדליקים מה שצריך:** `./bbox apps enable <app>`, או במסך מנהל האפליקציות.

ביום-יום: `./bbox status` מראה מה רץ; `./bbox stop` מוריד את הלשכה ושומר את המידע; `git pull` ואחריו `./bbox run`
מביאים גרסה חדשה; `./bbox export` ו-`./bbox import` מעבירים את כל הלשכה למחשב אחר.

## איך זה בנוי

- **הצהרות, לא סקריפטים.** כל אפליקציה היא תיקייה: המניפסט שלה (`apps/<app>/app.json`), וכשהיא מריצה שירות — קובץ
  ה-compose שלה. המהדר (`platform/manager/reconcile.py`) קורא אותם יחד עם הבחירות של הלשכה (`platform.state.yaml`)
  ובונה את מה שרץ לתוך `.generated/`; הפקודה `bbox` מיישרת את Docker לפיו.
- **ליבה שכל לשכה מקבלת** (`platform-base/`): הקונסולה, הכניסה (authentik), השער (Traefik), מסדי הנתונים Postgres
  ו-Redis, מנהל האפליקציות, כספת ההרשאות, ההתראות והאבטחה.
- **אפליקציות שהלשכה בוחרת** (`apps/`): לכל אחת מסך, API ו-CLI משלה (`./bbox <app> …`), לפי תקן אחד
  ([ai/context/app-cli-api-standard.md](ai/context/app-cli-api-standard.md)).
- **מראה אחד.** כל המסכים בנויים ממערכת עיצוב אחת — פלטה אחת, מימין לשמאל קודם.
- **שואלים את הלשכה, לא מסמך.** הפקודה `./bbox context [app]` אומרת מה הלשכה וכל אפליקציה הן ועושות עכשיו;
  הפקודה `./bbox computers map` מציירת את כל רשת הלשכות המקושרות, בזמן אמת.

לא מריצים `docker compose` ישירות: השירותים נבנים לתוך `.generated/`, ולכן `docker compose up` לבד לא מרים כלום.
משתמשים ב-`./bbox`, או ב-`./scripts/dc` ל-compose עצמו. הפקודה `./bbox help` מפרטת כל פקודה.

## לתרום

מתחילים ב-[CONTRIBUTING.he.md](CONTRIBUTING.he.md) וב-[AGENTS.md](AGENTS.md) — קובץ הכניסה הקצר לאנשים ולסוכני קוד.
המדריך [ai/context/build-your-first-app.md](ai/context/build-your-first-app.md) מראה איך כותבים אפליקציה,
והתיקייה `scripts/refactor/` מחזיקה את השערים שכל שינוי עובר. על בעיית אבטחה מדווחים בפרטיות:
[.github/SECURITY.md](.github/SECURITY.md).

רישיון: GNU AGPL v3 — ראו [LICENSE](LICENSE) ו-[NOTICE.md](NOTICE.md).

</div>
