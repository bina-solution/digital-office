---
type: tutorial
slug: install-dgo-with-claude
lang: he
title: "להתקין את הלשכה הדיגיטלית (DGO) עם Claude Code: מה אומרים לו ואיך הוא צריך לפעול"
seo_title: "התקנת DGO עם Claude Code: הנחיה, בדיקות ותקלות"
meta_description: "מדריך להתקנת הלשכה הדיגיטלית (DGO) עם Claude Code ב-Mac, ב-Windows וב-Linux: ההנחיה להדבקה, מה לראות בכל שלב ופתרון לתקלות הנפוצות."
summary: "מתקינים את DGO עם Claude Code בהנחיה אחת: משכפלים את המאגר, פותחים בו את Claude Code ומאשרים את הפקודות שהוא מציג. המדריך נותן את ההנחיה להדבקה, את מה שאמור להופיע בכל שלב ב-Mac, ב-Windows וב-Linux, ואת הפתרון לתקלות הנפוצות. DGO חינמית, אבל Claude Code דורש מנוי בתשלום."
category: install
tags: [התקנה, claude-code, סוכני AI, docker, wsl, macos, windows, linux, self-hosting, bbox]
keywords: { primary: "התקנת DGO עם Claude Code", secondary: [ "להתקין הלשכה הדיגיטלית", "Claude Code התקנה", "bbox run", "DGO Windows WSL", "Docker 29 Traefik 404" ] }
plane: DGO-749
author: צוות בינה סולושנס
publisher: בינה סולושנס
published: 2026-10-19
updated: 2026-10-19
words: 2163
reading_minutes: 11
faq:
  - q: "האם אפשר להתקין את DGO עם Claude Code בלי לשלם?"
    a: "DGO עצמה בחינם. Claude Code דורש מנוי Pro, Max, Team או Enterprise, או חשבון Console לפי שימוש; החשבון החינמי של Claude לא כולל אותו. נכון לאוקטובר 2026 Pro עולה 20 דולר לחודש, או 17 דולר בתשלום שנתי של 200 דולר, לפני מס."
  - q: "כמה זמן לוקחת ההתקנה של DGO?"
    a: "ההרצה הראשונה בונה את האימג׳ים וגוזלת כ-10 עד 15 דקות על מחשב קטן. הרצות מאוחרות יותר נשענות על מטמון."
  - q: "באיזו מערכת הפעלה אפשר להתקין?"
    a: "ב-Mac עם ./bbox run מתוך שכפול תחת תיקיית הבית, ב-Windows עם bbox.cmd run דרך WSL, וב-Linux או ב-VPS ישירות על Docker 28.x. בכל המקרים בלי Docker Desktop."
  - q: "באיזה מצב הרשאות מריצים את Claude Code להתקנה?"
    a: "בגרסה 2.1.283 ומעלה סשן חדש בטרמינל מתחיל ברוב המקרים במצב auto, שבו מודל שני מחליט על רוב האישורים. מי שרוצה לאשר בעצמו כל פקודה שמשנה משהו לוחץ Shift+Tab פעם אחת ועובר ל-Manual. מצב bypassPermissions מיועד לפי Anthropic למכולות ולמכונות וירטואליות מבודדות בלבד."
  - q: "למה Docker 29 לא עובד עם DGO?"
    a: "Docker 29.0.0 העלה את גרסת ה-API המינימלית ל-1.44 ו-29.3.0 הורידה אותה ל-1.40, אבל Traefik 3.3, נתב הקצה של DGO, מדבר API 1.24. התוצאה שקטה: Traefik עולה ולא מוצא נתיבים, וכל כתובת מחזירה 404. DGO רצה על Docker 28.x."
  - q: "האם Claude Code עובד בעברית?"
    a: "אפשר לכתוב לו בעברית, אבל בטרמינל יש דיווחים על עברית שמוצגת בסדר שגוי, בעיקר בשורות שמערבות עברית ואנגלית. לכן ההנחיה במדריך כתובה באנגלית."
  - q: "מה עושים כשפקודה מבקשת סיסמת sudo?"
    a: "משתמשים מדווחים שאי אפשר להקליד סיסמת sudo בתוך Claude Code. מריצים את הפקודה בעצמכם בחלון טרמינל נפרד וחוזרים ל-Claude עם התוצאה."
  - q: "האם Claude Code רואה את הסיסמאות שבקובץ .env?"
    a: "הוא קורא כל קובץ בתיקיית העבודה בלי לשאול, והתוכן נשלח ל-Anthropic כחלק מהשיחה. לכן ההנחיה אומרת לקרוא מ-.env רק את השורות הדרושות ולא להדפיס סיסמאות."
sources:
  - { title: "Claude Code docs: Advanced setup", url: "https://code.claude.com/docs/en/setup", accessed: 2026-10-19 }
  - { title: "Claude Code docs: Quickstart", url: "https://code.claude.com/docs/en/quickstart", accessed: 2026-10-19 }
  - { title: "Claude Code docs: How Claude remembers your project", url: "https://code.claude.com/docs/en/memory", accessed: 2026-10-19 }
  - { title: "Claude Code docs: Choose a permission mode", url: "https://code.claude.com/docs/en/permission-modes", accessed: 2026-10-19 }
  - { title: "Claude Code docs: Tools reference", url: "https://code.claude.com/docs/en/tools-reference", accessed: 2026-10-19 }
  - { title: "Claude Code docs: Manage costs effectively", url: "https://code.claude.com/docs/en/costs", accessed: 2026-10-19 }
  - { title: "Claude Code docs: Best practices", url: "https://code.claude.com/docs/en/best-practices", accessed: 2026-10-19 }
  - { title: "Claude Code docs: Troubleshooting", url: "https://code.claude.com/docs/en/troubleshooting", accessed: 2026-10-19 }
  - { title: "Claude Code docs: Data usage", url: "https://code.claude.com/docs/en/data-usage", accessed: 2026-10-19 }
  - { title: "Claude pricing", url: "https://claude.com/pricing", accessed: 2026-10-19 }
  - { title: "Anthropic: Supported Regions Policy", url: "https://www.anthropic.com/supported-countries", accessed: 2026-10-19 }
  - { title: "Bank of Israel: exchange rates (public API)", url: "https://boi.org.il/PublicApi/GetExchangeRates?asXml=false", accessed: 2026-10-19 }
  - { title: "Microsoft Learn: Install WSL", url: "https://learn.microsoft.com/en-us/windows/wsl/install", accessed: 2026-10-19 }
  - { title: "Docker Engine 29 release notes", url: "https://docs.docker.com/engine/release-notes/29/", accessed: 2026-10-19 }
  - { title: "Docker Engine 28 release notes", url: "https://docs.docker.com/engine/release-notes/28/", accessed: 2026-10-19 }
  - { title: "GitHub anthropics/claude-code issue 48938: Hebrew and English mixed text order", url: "https://github.com/anthropics/claude-code/issues/48938", accessed: 2026-10-19 }
  - { title: "GitHub anthropics/claude-code issue 33713: RTL fix reverses clipboard text", url: "https://github.com/anthropics/claude-code/issues/33713", accessed: 2026-10-19 }
  - { title: "GitHub anthropics/claude-code issue 76296: sudo password input", url: "https://github.com/anthropics/claude-code/issues/76296", accessed: 2026-10-19 }
  - { title: "WebKit Bugzilla 160504: Localhost subdomains don't work", url: "https://bugs.webkit.org/show_bug.cgi?id=160504", accessed: 2026-10-19 }
  - { title: "Pro Git: Installing Git", url: "https://git-scm.com/book/en/v2/Getting-Started-Installing-Git", accessed: 2026-10-19 }
related: [ "dgo://tutorial/install-dgo-manually", "dgo://article/the-triangle", "dgo://tutorial/dgo-on-a-small-vps", "dgo://tutorial/install-dgo-with-gemini", "dgo://article/traefik", "dgo://article/hardware-for-an-office" ]
---

# להתקין את הלשכה הדיגיטלית (DGO) עם Claude Code: מה אומרים לו ואיך הוא צריך לפעול

מתקינים את הלשכה הדיגיטלית (DGO) עם Claude Code בארבע פעולות: מתקינים את Claude Code, משכפלים את המאגר, מדביקים הנחיה אחת ומאשרים את הפקודות שהוא מציג. ההנחיה מורה לו לבדוק את המכונה, להריץ את הפקודה היחידה של DGO (`./bbox run`, ב-Windows `bbox.cmd run`) ולהוכיח שהמשרד עלה בפלט אמיתי. המדריך מיועד לבעל עסק או לאיש IT שמעדיף שסוכן יקרא את מסמכי ההתקנה, אבל לא מוכן לוותר על האישור לכל פקודה.

השורה התחתונה: ההתקנה מתאימה לסוכן, כי המאגר עצמו נכתב לסוכנים. יש בו CLAUDE.md, AGENTS.md ופקודה אחת. אבל Claude לא מחליף אתכם בשלושה מקומות: סיסמת sudo, התקנת WSL ב-Windows, והמתנה של 10 עד 15 דקות לבנייה הראשונה.

DGO עצמה עולה אפס. Claude Code דורש חשבון בתשלום: נכון לאוקטובר 2026 מנוי Pro עולה [20 דולר לחודש, או 17 דולר בתשלום שנתי של 200 דולר](https://claude.com/pricing). לפי [השער היציג](https://boi.org.il/PublicApi/GetExchangeRates?asXml=false) של 3.11 ש״ח מ-19.10.2026 אלה כ-62 וכ-53 ש״ח לחודש, לפני מס. החשבון החינמי לא כולל Claude Code, וישראל מופיעה ב[רשימת המדינות הנתמכות](https://www.anthropic.com/supported-countries) של Anthropic.

[[diagram: זרימת ההתקנה: אתם, Claude Code, bbox, מנוע DGO (Lima ב-Mac, WSL ב-Windows, Docker ישיר ב-Linux) והקונסול בדפדפן | alt: תרשים זרימה מ-Claude Code דרך bbox אל מנוע DGO ואל הקונסול]]

## מה צריך לפני שמתחילים?

Claude Code [מותקן בפקודה אחת](https://code.claude.com/docs/en/setup) לפי מערכת ההפעלה. ההתקנה לא מציגה התקדמות, אז אחריה פותחים חלון טרמינל חדש ומריצים `claude --version`. ב-Windows לא צריך הרשאות מנהל.

```text
macOS, Linux, WSL:  curl -fsSL https://claude.ai/install.sh | bash
Windows PowerShell: irm https://claude.ai/install.ps1 | iex
Windows CMD:        curl -fsSL https://claude.ai/install.cmd -o install.cmd && install.cmd && del install.cmd
```

[[video: youtube | סרטון רשמי של Anthropic על התקנה והפעלה ראשונה של Claude Code, מערוץ מאומת | url: ]]

הדרישות של Claude Code: macOS 13 ומעלה, Windows 10 גרסה 1809 ומעלה, Ubuntu 20.04 או Debian 10 ומעלה, ו-4 GB זיכרון לפחות. ב-Mac חדש הפקודה `git` הראשונה מפעילה התקנה של כלי שורת הפקודה של Xcode ([Pro Git](https://git-scm.com/book/en/v2/Getting-Started-Installing-Git)): ממתינים לה.

### Mac

אין צורך ב-Docker Desktop, ב-Homebrew או בהרשאות מנהל. `./bbox run` יוצרת מכונת Linux קטנה משלה (Lima על הווירטואליזציה של Apple, עם Docker CE 28.5.2) תחת `~/.bbox/macos` ומעמידה בתוכה את תיקיית הבית, ולכן השכפול חייב לשבת תחתיה. הממשק נפתח בכתובת `http://<app>.localhost:8080`, כי תהליך בלי הרשאות לא יכול לפתוח את פורט 80 ב-macOS. אימג׳ים שנבנו רק ל-amd64 דורשים Rosetta, שמתקינים בנפרד מול Apple: `softwareupdate --install-rosetta`.

### Windows עם WSL

ארבעה חלקים: WSL 2 עם Ubuntu, שכפול על C: (עם [Git for Windows](https://git-scm.com/download/win)), `bbox.cmd` מ-CMD או מ-PowerShell, ו-Claude Code ב-Windows עצמו ולא בתוך WSL. את WSL מתקינים ב-PowerShell שנפתח כמנהל, עם `wsl --install -d Ubuntu` והפעלה מחדש ([Microsoft](https://learn.microsoft.com/en-us/windows/wsl/install): Windows 10 גרסה 2004 ומעלה או Windows 11). את Claude מריצים מחוץ ל-WSL כי הקוד יושב על C:, ו-Anthropic מזהירה שחיפוש על `/mnt/c` מתוך WSL [איטי ומחזיר פחות תוצאות](https://code.claude.com/docs/en/troubleshooting).

`bbox.cmd` מעבירה כל שורה להפצה `Ubuntu`, ושם רץ Docker של DGO עצמה; Docker Desktop, מותקן או לא, לא בשימוש. במכונה חדשה מריצים קודם `bbox.cmd install windows`: היא מכינה את WSL ומתקינה git ו-Docker בתוך ההפצה.

### Linux או VPS

Debian או Ubuntu עם Docker 28.x. Docker 29 אינו נתמך: Traefik 3.3, נתב הקצה (edge router) של DGO, עולה ולא מוצא נתיבים. `./bbox install debian` מתקינה git ו-Docker, ואחריה `./bbox run`. היא משתמשת ב-sudo, ומשתמשים [מדווחים](https://github.com/anthropics/claude-code/issues/76296) שאי אפשר להקליד סיסמת sudo בתוך Claude Code, אז מריצים אותה בעצמכם בחלון נפרד.

### החומרה, בכנות

המינימום הרשמי: [[fact: מינימום זיכרון, מעבד ודיסק רשמי ל-DGO]]. מה שנמדד אצלנו: משרד מלא, יחד עם האתרים הציבוריים של החברה, רץ על VPS של Hostinger מסוג KVM 2 (2 vCPU, 8 GB זיכרון, 100 GB דיסק, Debian 12, פריז). משרד ה-MacBook רץ בתוך מכונה וירטואלית (VM) של 4 מעבדים ו-5 GiB, וב-Mac עם 8 GB זיכרון זה מה ש-DGO מקצה לה. Claude Code דורש 4 GB לפחות, אז ב-Mac כזה סוגרים אפליקציות כבדות לפני הבנייה. לבחירת חומרה: [איזה מחשב לקנות](dgo://article/hardware-for-an-office).

## איך משיגים את הקוד ומפעילים את Claude Code?

```bash
git clone https://github.com/bina-solution/digital-office
cd digital-office
claude
```

בהפעלה הראשונה Claude Code מבקש להתחבר דרך הדפדפן, ואז מציג שורת פתיחה עם הגרסה, המודל והתיקייה ([Quickstart](https://code.claude.com/docs/en/quickstart)).

שתי בדיקות לפני ההנחיה. הראשונה: `/memory` מראה אילו קבצי הוראות נטענו. תראו שם את CLAUDE.md של המאגר ולא את AGENTS.md. כש-CLAUDE.md קיים, [Claude Code טוען רק אותו](https://code.claude.com/docs/en/memory), ו-CLAUDE.md של DGO מפנה ל-AGENTS.md בקישור רגיל ולא ב-`@AGENTS.md`; לכן ההנחיה מבקשת לקרוא אותו במפורש.

השנייה: שורת הסטטוס. בגרסה 2.1.283 ומעלה סשן חדש בטרמינל [מתחיל ברוב המקרים במצב auto](https://code.claude.com/docs/en/permission-modes), שבו מודל שני מחליט על רוב האישורים. `Shift+Tab` פעם אחת מעביר ל-Manual: קריאת קבצים עוברת בלי שאלה, וכל פקודה שמשנה משהו מחכה לכם. מצב `bypassPermissions` מיועד לפי Anthropic למכולות ולמכונות וירטואליות מבודדות בלבד, והמכונה הווירטואלית של DGO מבודדת את המשרד, לא את Claude.

[[screenshot: Claude Code בתיקיית המאגר: שורת הפתיחה, /memory עם CLAUDE.md ושורת סטטוס במצב manual | alt: טרמינל עם Claude Code, קבצי ההוראות שנטענו ושורת סטטוס במצב ידני]]

## מה כותבים ל-Claude Code?

ההנחיה באנגלית, בכוונה: שני דיווחים ב-GitHub ([48938](https://github.com/anthropics/claude-code/issues/48938), [33713](https://github.com/anthropics/claude-code/issues/33713)) מתארים עברית שמוצגת בסדר שגוי בטרמינל של Claude Code: שורות מעורבות עם אנגלית וטקסט שמועתק הפוך. שניהם נסגרו אוטומטית כ״לא מתוכננים״, בלי תגובה של מתחזק. הדביקו את הבלוק כמו שהוא.

```text
Install DGO (Digital Office) from the repo in the current folder.
Reply in English, keep messages short, and show real command output, not summaries.

1. Read CLAUDE.md and AGENTS.md in full first. Claude Code does not load AGENTS.md on its own when CLAUDE.md exists, so open it yourself. Follow both. AGENTS.md calls this production: when in doubt, stop and ask me.
2. Survey first, change nothing. Report my OS and CPU, RAM, free disk, and the exact Docker version or WSL status. If Docker is 29.x, stop and tell me.
3. The only way to run DGO is the command in CLAUDE.md: ./bbox run (Windows: bbox.cmd run from CMD or PowerShell, never ./bbox from Git Bash). Never call docker compose directly, edit .generated/, or use Docker Desktop. Run no git command that changes anything.
4. For missing prerequisites use only the installers in bbox help (./bbox install debian, bbox.cmd install windows).
5. No .env: a Mac generates one. Elsewhere do not invent secrets or copy .env.ex as is; read .env.ex and scripts/ci-env.sh, tell me what you propose, and wait.
6. Before any command that writes, deletes, installs, restarts or needs sudo, tell me in one or two lines what it does and what could break, then wait for my OK. If a command needs a password, give it to me to run myself. Never run bbox reset or use --force without an explicit yes.
7. The first run builds images, 10 to 15 minutes on a small machine. Run it in the background, check its output about once a minute, and report one line each time.
8. If something fails, show the real error and the cause. Never retry blindly or work around a failure silently.
9. Done means proven: show ./bbox status, then curl -sI the console (http://console.localhost, on a Mac http://console.localhost:8080) and show the status line (404 means no routing, even if status is green), then give me the address to open. Read only the .env lines you need, never print passwords, and tell me where they are.
```

## איך Claude אמור להתנהג בזמן ההתקנה?

ארבע התנהגויות, וכל אחת נשענת על מסמך ולא על ניחוש:

1. **קורא לפני שהוא משנה, ומראה ראיות.** סקר של המכונה בלי שינויים, ובסוף אימות מול פלט אמיתי. את האימות AGENTS.md דורש במפורש, ו-[Anthropic ממליצה](https://code.claude.com/docs/en/best-practices) על שניהם: קודם לחקור ורק אז לבצע, ולבקש ראיה ולא הצהרה.
2. **מסביר לפני שהוא מבצע.** AGENTS.md דורש שורה או שתיים על כל פקודה מסוכנת (`rm`, `sudo`, `kill`, `--force`, כל כתיבה או מחיקה): מה היא עושה ומה עלול להישבר. `./bbox stop` מוריד קונטיינרים ושומר נתונים; `./bbox reset` מוחק הכול ושואל אישור.
3. **עוצר בשתי מלכודות שקטות:** Docker 29, ו-Docker Desktop שיכול לתפוס בשקט את הכתובת הרגילה של Docker. אף אחת מהן לא זורקת שגיאה: כל הכתובות מחזירות 404 והקונטיינרים בריאים.
4. **לא מאלתר סביב הכניסה היחידה.** `docker compose` ישיר מסתיים בהצלחה בלי להרים שום שירות, כי ה-compose בשורש מכיל רק את הרשת והשירותים מקומפלים ל-`.generated/` (AGENTS.md, שער G7). הצעה לעקוף דרכו, או דרך Docker Desktop, היא סימן לעצור.

ושני גבולות. CLAUDE.md ו-AGENTS.md הם [הקשר ולא אכיפה](https://code.claude.com/docs/en/memory), אז האישור שלכם הוא השער האמיתי. ואת מה שפקודות Bash עשו אי אפשר לבטל ב-`/rewind` ([Anthropic](https://code.claude.com/docs/en/best-practices)): אימג׳ים, קונטיינרים ונפחי נתונים נשארים.

:::warning
Claude Code שולח ל-Anthropic את השיחה כולה בכל בקשה, כולל כל קובץ שקרא וכל פלט של פקודה ([עלויות](https://code.claude.com/docs/en/costs), [נתונים](https://code.claude.com/docs/en/data-usage)). ב-Pro וב-Max הנתונים נשמרים 5 שנים אם ההגדרה לשיפור מודלים פעילה, ו-30 יום אם כבויה; ב-Team, ב-Enterprise וב-API 30 יום וללא אימון. ב-`.env` יושבים סודות, ולכן ההנחיה אוסרת להדפיס סיסמאות: תמלילי השיחה נשמרים אצלכם גם בטקסט גלוי תחת `~/.claude/projects/`.
:::

## מה רואים בכל שלב?

1. **סקר, בלי שינויים.** Claude קורא את שני הקבצים ומדווח: מערכת, מעבד, זיכרון, דיסק פנוי וגרסת Docker או WSL, ותוכנית. אין אף פקודת כתיבה. עצירה על Docker 29.x היא התנהגות נכונה ולא תקלה.
2. **הכנת המכונה, רק אם חסר משהו.** ב-Mac אין שלב כזה: `./bbox run` יוצרת את המנוע בעצמה. ב-Windows רצה `bbox.cmd install windows`, ולפעמים היא מבקשת `wsl --shutdown` (ראו בסוף). ב-Linux רצה `./bbox install debian`, ו-`docker version` בסופה מראה שרת 28.x.
3. **קובץ `.env`.** ב-Mac `./bbox run` מייצר אחד מקומי כשאין, עם כתובות `<app>.localhost:8080`. ב-Windows וב-Linux CLAUDE.md קובע שהקובץ באחריותכם: [[fact: הדרך הנתמכת ליצור .env ראשון ב-Windows וב-Linux]].
4. **ההרצה.** הבנייה הראשונה נמשכת כ-10 עד 15 דקות על מחשב קטן, והבאות נשענות על מטמון. Claude אמור להריץ אותה ברקע. אם הריץ בחזית, אחרי שתי דקות Claude Code מעביר אותה לרקע ([Anthropic](https://code.claude.com/docs/en/tools-reference)) ומציג `Command did not complete within its 120s timeout and was moved to the background`; זה תקין, ו-`/tasks` מציג אותה. כל בדיקה של Claude שולחת שוב את כל השיחה, ולכן דקה בין בדיקות ולא שנייה. זמן מדוד: [[fact: זמן ההרצה הראשונה שנמדד ב-vps1 וב-MacBook]].
5. **בדיקה.** `./bbox status` מסכם כמה קונטיינרים פועלים וכמה healthy, ומסמן `DOWN` כל אחד שנפל. אחריו Claude מציג את שורת הסטטוס של כתובת הקונסול: 200 או הפניה (3xx) למסך הכניסה עוברים, 404 אומר שאין ניתוב, ו-5xx אומר שהשירות עצמו לא ענה. אזהרה שלא כל השירותים healthy בזמן שהוקצב אינה סוף הדרך: מחכים כמה דקות ובודקים שוב.

[[screenshot: הפלט של ./bbox status בסוף הרצה מוצלחת, עם הזמן שנמדד | alt: טרמינל שמציג סיכום קונטיינרים תקינים אחרי ./bbox status]]

## איך נראה הקונסול בפעם הראשונה?

פותחים ב-Chrome או ב-Firefox את `http://console.localhost` (ב-Mac: `http://console.localhost:8080`). ב-Safari שלפני macOS 26 הכתובת לא תיפתח: בבאג [WebKit 160504](https://bugs.webkit.org/show_bug.cgi?id=160504) מדווח ש-`*.localhost` עובד ב-macOS 26.0 ונכשל ב-15.7. הכניסה: [[fact: הכניסה הראשונה למשרד חדש: שם משתמש ומקום הסיסמה]].

מה רואים: שולחן עבודה בעברית מימין לשמאל, שבו כל אפליקציה נפתחת בחלון משלה, והוא עובד גם בטלפון ובטאבלט. ארבעה מסכים לפתוח עכשיו: «ניהול אפליקציות» (מה מותקן, מופעל ומושבת), «מכונה» (קונטיינרים, אחסון, מעבד וזיכרון), «חיבורים ומפתחות» ו«ניהול נתונים».

[[screenshot: הקונסול «המרכז» בכניסה הראשונה, בעברית וב-RTL, עם חלון «ניהול אפליקציות» פתוח | alt: שולחן עבודה בעברית עם חלון ניהול אפליקציות פתוח]]

:::dgo
אחרי ההתקנה יש לכם משרד: קונסול בעברית וב-RTL, כניסה אחת (authentik) לכל האפליקציות, ומסך «ניהול אפליקציות» להתקנה, הפעלה והסרה. סיסמאות ומפתחות יושבים במקום אחד, «חיבורים ומפתחות»; גיבוי ושחזור מלאים ב«ניהול נתונים»; ושירות שמדווח על עצמו כלא תקין מופעל מחדש לבד. עזריה, סוכן המשרד, חיה באפליקציה «בינה» בתוך המשרד, ו-Claude Code הוא הכלי שמקים אותו מבחוץ. DGO פותחה בידי בינה סולושנס ושוחררה ב-19.10.2026 ברישיון AGPL v3. כל מה שכתוב כאן פעיל היום.
:::

## מה משתבש, ואיך מתקנים?

- **כל כתובת מחזירה 404 וה-status ירוק.** Docker 29 הוא הכשל הכי מנומס שיש: שום שגיאה, הכול ירוק, ורק כל הכתובות מחזירות 404. Docker 29.0.0 העלה ב-10.11.2025 את גרסת ה-API המינימלית ל-1.44, ו-29.3.0 הורידה אותה ב-5.3.2026 ל-1.40 ([Docker](https://docs.docker.com/engine/release-notes/29/)), אבל הלקוח של Traefik 3.3 מדבר API 1.24, אז הנתב עולה ולא מוצא נתיבים ([Traefik ב-DGO](dgo://article/traefik)). `docker info | grep "Server Version"` צריך להחזיר 28.x. ב-Mac וב-Windows מנוע הפרויקט מוצמד ל-28, והמלכודת היא Linux שבו Docker הותקן בלי הצמדה. מחיר ההצמדה: 28.5.2 היא [האחרונה בקו 28](https://docs.docker.com/engine/release-notes/28/) (5.11.2025), ו-Docker כבר ב-29.9.1 (14.10.2026). ב-Mac גם `.env` ידני עם כתובות בלי `:8080` נותן 404 תחת סטטוס ירוק.
- **הבנייה נראית תקועה.** על מחשב קטן 10 עד 15 דקות בלי הרבה פלט הן הרגיל. Claude קורא את קובץ הפלט של הפקודה כל דקה; שגיאה אמיתית תופיע שם, והוא אמור להציג אותה כלשונה.
- **`bbox.cmd` לא מוצא את ההפצה Ubuntu.** `wsl -l -v` צריך להציג הפצה בשם `Ubuntu` בגרסה 2. אם היא חסרה: `wsl --install -d Ubuntu` כמנהל, והפעלה מחדש.
- **`Wsl/Service/0x8007274c` באמצע בנייה.** זו חריגת זמן בשיחה עם המכונה הווירטואלית ולא כשל בתוכה: מתייחסים אליה כ״לא ידוע, מנסים שוב״. ה-VM מוגבל בזיכרון ב-`.wslconfig` ולא מחזיר אותו ל-Windows; `wsl --shutdown` משחרר אותו מיד, אבל עוצר כל הפצה, אז רק בנקודת ביניים.
- **פורטים.** ה-edge של DGO מאזין ל-80 ול-443, ותהליך אחר שמחזיק אותם חוסם אותו. ב-Mac השער יושב על 8080 ו-8443; `./bbox engine forwards` מדפיס את השרשרת ומצביע על החוליה הפתוחה.

## מה עושים אחרי שזה עובד?

ארבעה כיוונים:

- [התקנה ידנית](dgo://tutorial/install-dgo-manually): אותם שלבים בלי סוכן, כשרוצים להבין מה Claude עשה.
- [המשולש](dgo://article/the-triangle): משרד שני מתחבר לראשון, ואפליקציה שרצה באחד נפתחת כאריח בקונסול של האחר. אצלנו ה-MacBook, מחשב HP ו-VPS מקושרים כך, עם גבול כן: משרד על לפטופ לא זמין כשהלפטופ ישן.
- [DGO על VPS קטן](dgo://tutorial/dgo-on-a-small-vps): משרד על שרת בכתובת אמיתית.
- [התקנה עם Gemini](dgo://tutorial/install-dgo-with-gemini): אותה התקנה עם סוכן אחר.
