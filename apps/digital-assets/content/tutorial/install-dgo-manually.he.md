---
type: tutorial
slug: install-dgo-manually
lang: he
title: "להתקין את הלשכה הדיגיטלית (DGO) בלי סוכן: Mac, Windows ו-Linux צעד אחר צעד"
seo_title: "התקנת DGO ידנית: Mac, Windows ו-Linux צעד אחר צעד"
meta_description: "איך מתקינים את הלשכה הדיגיטלית (DGO) בלי סוכן ב-Mac, ב-Windows וב-Linux: הפקודות, מה רואים בכל שלב, ופתרון ל-Docker 29 ול-Ubuntu 26.04."
summary: "מתקינים את DGO ידנית בשלושה צעדים: משכפלים את המאגר, מכינים את המכונה ומריצים bbox run. ב-Mac אין הכנה, ב-Windows צריך WSL עם Ubuntu 24.04 בשם Ubuntu, וב-Linux צריך Docker 28.x ולא 29. ההרצה הראשונה לוקחת כ-10 עד 15 דקות על מחשב קטן, ו-Ubuntu 26.04 נתקעת כי ל-Docker אין בה גרסה 28."
category: install
tags: [ התקנה, bbox, docker, wsl, macos, windows, linux, ubuntu, lima, self-hosting ]
keywords: { primary: "התקנת DGO ידנית", secondary: [ "להתקין את הלשכה הדיגיטלית", "bbox run", "DGO Windows WSL", "DGO Mac", "Docker 28 Ubuntu 26.04" ] }
plane: DGO-761
author: צוות בינה סולושנס
publisher: בינה סולושנס
published: 2026-10-19
updated: 2026-10-19
words: 0
reading_minutes: 0
faq:
  - q: "כמה זמן לוקחת ההתקנה הידנית של DGO?"
    a: "ההרצה הראשונה בונה את האימג׳ים ולוקחת כ-10 עד 15 דקות על מחשב קטן. ב-Mac נוספות כמה דקות להקמת המנוע, וב-Windows הכנת WSL והפעלה מחדש. הרצות מאוחרות יותר נשענות על מטמון."
  - q: "האם צריך Docker Desktop כדי להתקין את DGO?"
    a: "לא. DGO מביאה מנוע Docker משלה: מכונת Lima ב-Mac, Docker בתוך WSL ב-Windows ו-Docker 28.x ישירות ב-Linux. היא אינה משתמשת ב-Docker Desktop גם כשהוא מותקן."
  - q: "אפשר להתקין את DGO ב-Windows בלי WSL?"
    a: "לפי תיעוד המאגר אין דרך אחרת. bbox.cmd מעביר כל פקודה להפצה בשם Ubuntu ב-WSL, ושם רץ Docker של DGO. הרצה מ-Git Bash נעצרת בשגיאה."
  - q: "למה ההתקנה נתקעת על Ubuntu 26.04?"
    a: "debian-install.sh מצמיד את Docker 28.5.2, וב-apt של Docker ל-Ubuntu 26.04 פורסמו נכון ל-19.10.2026 רק גרסאות 29.3.1 עד 29.9.1. הפקודה wsl --install -d Ubuntu מתקינה היום Ubuntu 26.04, ולכן ב-Windows מתקינים Ubuntu-24.04 בשם Ubuntu. ב-VPS בוחרים Debian 12 או 13, או Ubuntu 22.04 או 24.04."
  - q: "למה כל הכתובות מחזירות 404 כשהכול ירוק?"
    a: "הסיבה הרגילה היא Docker 29: ה-Traefik 3.3 של DGO מדבר API 1.24, ו-Docker 29 דורש לפחות 1.44 (ומ-29.3.0 לפחות 1.40), ולכן Traefik עולה בלי למצוא נתיבים. בודקים עם docker info ומצפים ל-28.x. ב-Mac סיבה נוספת היא קובץ .env ידני עם כתובות בלי :8080."
  - q: "באיזה דפדפן פותחים את הקונסול?"
    a: "ב-Chrome או ב-Firefox. Safari שלפני macOS 26 לא פותח כתובות *.localhost: באג WebKit 160504 מדווח שזה עובד ב-macOS 26.0 ונכשל ב-15.7."
  - q: "איפה הסיסמה של הכניסה הראשונה?"
    a: "בקובץ .env, תחת AUTHENTIK_BOOTSTRAP_PASSWORD. תבנית ה-.env קובעת את המשתמש akadmin ומציינת שהפרטים האלה משמשים רק בהפעלה הראשונה של authentik."
  - q: "האם bbox.cmd משנה משהו ב-Windows מעבר לתיקייה?"
    a: "כן. bbox.cmd run רושמת ב-Task Scheduler משימות בשם Platform-OS שמחזיקות את ההפצה פעילה ובודקות בריאות, ויכולה לבקש אישור מנהל לכלל בחומת האש. מסירים אותן עם platform-keepalive.ps1 ‏-Uninstall."
sources:
  - { title: "GitHub: bina-solution/digital-office (המאגר הפומבי, AGPL-3.0)", url: "https://github.com/bina-solution/digital-office", accessed: 2026-10-19 }
  - { title: "GitHub digital-office: README.md", url: "https://github.com/bina-solution/digital-office/blob/main/README.md", accessed: 2026-10-19 }
  - { title: "GitHub digital-office: CLAUDE.md", url: "https://github.com/bina-solution/digital-office/blob/main/CLAUDE.md", accessed: 2026-10-19 }
  - { title: "GitHub digital-office: debian-install.sh", url: "https://github.com/bina-solution/digital-office/blob/main/debian-install.sh", accessed: 2026-10-19 }
  - { title: "GitHub digital-office: bbox.cmd", url: "https://github.com/bina-solution/digital-office/blob/main/bbox.cmd", accessed: 2026-10-19 }
  - { title: "GitHub digital-office: scripts/install-windows", url: "https://github.com/bina-solution/digital-office/blob/main/scripts/install-windows", accessed: 2026-10-19 }
  - { title: "GitHub digital-office: packaging/macos/engine.sh", url: "https://github.com/bina-solution/digital-office/blob/main/packaging/macos/engine.sh", accessed: 2026-10-19 }
  - { title: "GitHub digital-office: scripts/ci-env.sh", url: "https://github.com/bina-solution/digital-office/blob/main/scripts/ci-env.sh", accessed: 2026-10-19 }
  - { title: "GitHub digital-office: .env.ex", url: "https://github.com/bina-solution/digital-office/blob/main/.env.ex", accessed: 2026-10-19 }
  - { title: "GitHub digital-office: platform-base/traefik/docker-compose.yml", url: "https://github.com/bina-solution/digital-office/blob/main/platform-base/traefik/docker-compose.yml", accessed: 2026-10-19 }
  - { title: "GitHub digital-office: scripts/windows/platform-keepalive.ps1", url: "https://github.com/bina-solution/digital-office/blob/main/scripts/windows/platform-keepalive.ps1", accessed: 2026-10-19 }
  - { title: "GitHub digital-office: platform/profiles/perf-profiles.yml", url: "https://github.com/bina-solution/digital-office/blob/main/platform/profiles/perf-profiles.yml", accessed: 2026-10-19 }
  - { title: "GitHub digital-office: platform/manager/reconcile.py", url: "https://github.com/bina-solution/digital-office/blob/main/platform/manager/reconcile.py", accessed: 2026-10-19 }
  - { title: "GitHub digital-office: ai/context/running-on-wsl.md", url: "https://github.com/bina-solution/digital-office/blob/main/ai/context/running-on-wsl.md", accessed: 2026-10-19 }
  - { title: "Microsoft Learn: Install WSL", url: "https://learn.microsoft.com/en-us/windows/wsl/install", accessed: 2026-10-19 }
  - { title: "Microsoft Learn: Basic commands for WSL", url: "https://learn.microsoft.com/en-us/windows/wsl/basic-commands", accessed: 2026-10-19 }
  - { title: "Microsoft Learn: Troubleshooting WSL", url: "https://learn.microsoft.com/en-us/windows/wsl/troubleshooting", accessed: 2026-10-19 }
  - { title: "Microsoft Learn: Advanced settings configuration in WSL", url: "https://learn.microsoft.com/en-us/windows/wsl/wsl-config", accessed: 2026-10-19 }
  - { title: "GitHub microsoft/WSL: distributions/DistributionInfo.json", url: "https://raw.githubusercontent.com/microsoft/WSL/master/distributions/DistributionInfo.json", accessed: 2026-10-19 }
  - { title: "GitHub microsoft/WSL: Resources.resw (wsl.exe help text)", url: "https://github.com/microsoft/WSL/blob/master/localization/strings/en-US/Resources.resw", accessed: 2026-10-19 }
  - { title: "Ubuntu on WSL docs: Manage and configure instances", url: "https://ubuntu.com/wsl/docs/latest/howto/manage-and-configure/", accessed: 2026-10-19 }
  - { title: "GitHub microsoft/WSL issue 11975: Wsl/Service/0x8007274c", url: "https://github.com/microsoft/WSL/issues/11975", accessed: 2026-10-19 }
  - { title: "Docker Docs: Install Docker Engine on Debian", url: "https://docs.docker.com/engine/install/debian/", accessed: 2026-10-19 }
  - { title: "Docker apt repository: Ubuntu 26.04 (resolute) packages", url: "https://download.docker.com/linux/ubuntu/dists/resolute/pool/stable/amd64/", accessed: 2026-10-19 }
  - { title: "Docker apt repository: Ubuntu 24.04 (noble) packages", url: "https://download.docker.com/linux/ubuntu/dists/noble/pool/stable/amd64/", accessed: 2026-10-19 }
  - { title: "Docker apt repository: Ubuntu 22.04 (jammy) packages", url: "https://download.docker.com/linux/ubuntu/dists/jammy/pool/stable/amd64/", accessed: 2026-10-19 }
  - { title: "Docker apt repository: Debian 13 (trixie) packages", url: "https://download.docker.com/linux/debian/dists/trixie/pool/stable/amd64/", accessed: 2026-10-19 }
  - { title: "Docker apt repository: Debian 12 (bookworm) packages", url: "https://download.docker.com/linux/debian/dists/bookworm/pool/stable/amd64/", accessed: 2026-10-19 }
  - { title: "Docker Engine 29 release notes", url: "https://docs.docker.com/engine/release-notes/29/", accessed: 2026-10-19 }
  - { title: "Docker Engine 28 release notes", url: "https://docs.docker.com/engine/release-notes/28/", accessed: 2026-10-19 }
  - { title: "Traefik v3.6.1 release notes", url: "https://github.com/traefik/traefik/releases/tag/v3.6.1", accessed: 2026-10-19 }
  - { title: "Pro Git: Installing Git", url: "https://git-scm.com/book/en/v2/Getting-Started-Installing-Git", accessed: 2026-10-19 }
  - { title: "Git for Windows: install (winget)", url: "https://git-scm.com/install/windows", accessed: 2026-10-19 }
  - { title: "Lima docs: Virtualization.framework (vz)", url: "https://lima-vm.io/docs/config/vmtype/vz/", accessed: 2026-10-19 }
  - { title: "WebKit Bugzilla 160504: Localhost subdomains don't work", url: "https://bugs.webkit.org/show_bug.cgi?id=160504", accessed: 2026-10-19 }
  - { title: "Apple Support: Using Intel-based apps on a Mac with Apple silicon (Rosetta)", url: "https://support.apple.com/en-us/102527", accessed: 2026-10-19 }
  - { title: "PowerShell docs: about_Command_Precedence", url: "https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_command_precedence", accessed: 2026-10-19 }
  - { title: "Hostinger: VPS hosting", url: "https://www.hostinger.com/vps-hosting", accessed: 2026-10-19 }
  - { title: "Bank of Israel: representative exchange rates (public API)", url: "https://boi.org.il/PublicApi/GetExchangeRates?asXml=false", accessed: 2026-10-19 }
related: [ "dgo://tutorial/install-dgo-with-claude", "dgo://tutorial/dgo-on-a-small-vps", "dgo://article/hardware-for-an-office", "dgo://article/traefik", "dgo://tutorial/installing-apps-in-dgo", "dgo://article/the-triangle" ]
---

# להתקין את הלשכה הדיגיטלית (DGO) בלי סוכן: Mac, Windows ו-Linux צעד אחר צעד

מתקינים את הלשכה הדיגיטלית (DGO) ידנית בשלושה צעדים: משכפלים את המאגר, מכינים את המכונה ומריצים `./bbox run` (ב-Windows: `.\bbox.cmd run`). ב-Mac אין הכנה, כי DGO בונה לעצמה מכונת לינוקס קטנה. ב-Windows צריך WSL עם הפצה בשם `Ubuntu`, וב-Linux צריך Docker 28.x. ההרצה הראשונה בונה אימג׳ים (images) ולוקחת כ-10 עד 15 דקות על מחשב קטן.

המדריך מיועד לבעל עסק או לאיש IT שרוצה לראות כל פקודה בעצמו. מי שמעדיף שסוכן יקרא את מסמכי ההתקנה: [התקנה עם Claude Code](dgo://tutorial/install-dgo-with-claude).

השורה התחתונה: הפקודה האחת היא החלק הקל. מה שמפיל התקנות הוא שלושה פרטים. Docker 29 נכשל בשקט. ל-Ubuntu 26.04, ברירת המחדל של WSL ב-19.10.2026, אין חבילת Docker 28. וקובץ `.env` נוצר לבד רק ב-Mac. DGO חינמית ([AGPL v3](https://github.com/bina-solution/digital-office)), ובמאגר אין עדיין release או תגית, אז המדריך נכתב מול `main` ב-commit `7f2d9ce`.

[[diagram: שלושה מסלולים לאותה פקודה: Mac (מכונת Lima), Windows (WSL עם Docker) ו-Linux (Docker ישירות) מובילים אל bbox run ואל הקונסול בדפדפן | alt: תרשים של שלושה מסלולי התקנה שמתכנסים ל-bbox run ולקונסול]]

## מה צריך לפני שמתחילים?

| | Mac | Windows | Linux או VPS |
|---|---|---|---|
| מערכת | macOS 13 ומעלה | Windows 10 גרסה 2004 ומעלה, או Windows 11 | Debian 12 או 13, Ubuntu 22.04 או 24.04 |
| להכין מראש | git | WSL, הפצה בשם `Ubuntu`, Git for Windows | git, python3-yaml |
| איפה רץ Docker | מכונת Lima משלה | בתוך WSL | ישירות במכונה, גרסה 28.x |
| פקודת ההרצה | `./bbox run` | `.\bbox.cmd run` | `./bbox run` |
| הקונסול | `http://console.localhost:8080` | `http://console.localhost` | `http://console.localhost` |

בטבלה רק הפצות ש-apt של Docker מפרסם להן את 28.5.2, הגרסה ש-DGO מצמידה: [Debian 12](https://download.docker.com/linux/debian/dists/bookworm/pool/stable/amd64/), [Debian 13](https://download.docker.com/linux/debian/dists/trixie/pool/stable/amd64/), [Ubuntu 22.04](https://download.docker.com/linux/ubuntu/dists/jammy/pool/stable/amd64/) ו-[Ubuntu 24.04](https://download.docker.com/linux/ubuntu/dists/noble/pool/stable/amd64/). ל-[Ubuntu 26.04](https://download.docker.com/linux/ubuntu/dists/resolute/pool/stable/amd64/) פורסמו רק 29.3.1 עד 29.9.1, ולכן [debian-install.sh](https://github.com/bina-solution/digital-office/blob/main/debian-install.sh) נעצר שם. אצלנו vps1 רץ על Debian 12.

**חומרה.** הפרופיל הנמוך ביותר בקוד, `ci-small`, [דורש מארח Docker](https://github.com/bina-solution/digital-office/blob/main/platform/profiles/perf-profiles.yml) עם 5 GB זיכרון. ב-Windows המארח הוא המכונה הווירטואלית של WSL, ו[ברירת המחדל שלה](https://learn.microsoft.com/en-us/windows/wsl/wsl-config) היא 50% מזיכרון המחשב: ב-8 GB היא מקבלת 4. מגדילים ב-`%UserProfile%\.wslconfig` (`memory=5GB` תחת `[wsl2]`) ומריצים `wsl --shutdown`. מה שנמדד אצלנו: לשכה מלאה, יחד עם האתרים הציבוריים של החברה, רצה על Hostinger KVM 2 (2 vCPU, 8 GB זיכרון, 100 GB דיסק, Debian 12, פריז), ולשכת ה-MacBook רצה בתוך מכונה וירטואלית של 4 מעבדים ו-5 GiB. המינימום הרשמי של זיכרון, מעבד ודיסק: [[fact: official minimum RAM, CPU and free disk for DGO]]. [איזה מחשב לקנות](dgo://article/hardware-for-an-office).

**עלות.** DGO חינמית. משלמים על החומרה, ואם רוצים שרת קטן: KVM 2 [מוצג ב-19.10.2026](https://www.hostinger.com/vps-hosting) ב-8.79 דולר לחודש במבצע וב-14.99 בחידוש, כ-27 עד 47 ₪ לפי [שער יציג](https://boi.org.il/PublicApi/GetExchangeRates?asXml=false) של 3.11 ₪ לדולר.

## מאיפה משכפלים את המאגר?

```bash
git clone https://github.com/bina-solution/digital-office
cd digital-office
```

אל תעתיקו את ה-clone מה-[README](https://github.com/bina-solution/digital-office/blob/main/README.md) של המאגר: הוא מצביע על `bina-solution/digital-office`, כתובת שמחזירה 404 ב-19.10.2026.

## מה עם קובץ `.env`?

ב-Mac אין מה לעשות: כשאין `.env`, `./bbox run` מייצרת אחד בעצמה, עם סיסמאות אקראיות וכתובות `*.localhost:8080`. ב-Linux וב-Windows היא לא מייצרת, וסקריפט ההתקנה רק מעתיק את התבנית `.env.ex` כשהקובץ חסר. [התבנית הפומבית](https://github.com/bina-solution/digital-office/blob/main/.env.ex) מכילה עשרות שדות מסומנים `CHANGE_ME` (סיסמאות, מפתחות וטוקנים), וה-README אומר לערוך אותם בעצמכם.

את הקובץ ב-Mac כותב [scripts/ci-env.sh](https://github.com/bina-solution/digital-office/blob/main/scripts/ci-env.sh): סודות אקראיים וכתובות `*.localhost` ב-http. הוא מסרב לדרוס `.env` קיים, ולכן מריצים אותו לפני `install`, כדי שהתבנית לא תועתק:

```bash
bash scripts/ci-env.sh                                              # Linux
wsl -d Ubuntu -u root --cd /mnt/c/dgo -- bash scripts/ci-env.sh   # Windows, אחרי שלב 1 שם
```

הסוף: שורה שמתחילה ב-`CI .env generated`. [[fact: supported way to create the first .env for local Windows and Linux]]

## איך מתקינים ב-Mac?

Mac דורש macOS 13 ומעלה, כי [Lima על Virtualization.framework](https://lima-vm.io/docs/config/vmtype/vz/) של אפל לא רץ על גרסה ישנה יותר. DGO עצמה לא צריכה Docker Desktop, Homebrew או הרשאות מנהל.

1. **git.** מריצים `git --version`. ב-Mac חדש זה מפעיל [התקנה של כלי שורת הפקודה של Xcode](https://git-scm.com/book/en/v2/Getting-Started-Installing-Git): ממתינים לה.
2. **שכפול** לתיקייה תחת תיקיית הבית. [המנוע](https://github.com/bina-solution/digital-office/blob/main/packaging/macos/engine.sh) מצמיד את תיקיית הבית כולה, ולכן גם שם תיקייה בעברית או עם רווח לא מפריע.
3. **הרצה:** `./bbox run`

בהרצה הראשונה bbox מורידה את Lima, מקימה מכונת Ubuntu 24.04 עם Docker 28.5.2 תחת `~/.bbox/macos` ורק אז בונה את האימג׳ים. תראו `[bbox engine] creating the engine: Ubuntu 24.04 + Docker 28.5.2` עם גודל המכונה, שורה על Rosetta, ואחריה `no .env — generating a local one for the macOS engine`. הסוף: `[bbox] up. check health with: bbox status`.

[[screenshot: Terminal ב-Mac בהרצה הראשונה של ./bbox run, מהשורה creating the engine ועד up. check health | alt: טרמינל של Mac שמציג את הקמת המנוע והשורה האחרונה של bbox run]]

הקצה יושב על פורט 8080, כי תהליך בלי הרשאות לא יכול לפתוח את פורט 80 ב-macOS. את הקונסול פותחים ב-Chrome או ב-Firefox: Safari שלפני macOS 26 לא פותח כתובות `*.localhost` ([WebKit 160504](https://bugs.webkit.org/show_bug.cgi?id=160504): ב-15.7 הוא נכשל וב-26.0 עובד). Rosetta אופציונלי: בלעדיו ירוצו רק אימג׳ים שיש להם גרסת arm64, ו-`softwareupdate --install-rosetta` ([Apple](https://support.apple.com/en-us/102527)) מוסיף אותו. `./bbox engine status` ו-`./bbox engine stop` מנהלים את המכונה, ו-`./bbox engine doctor` מדפיס גרסאות וגדלים.

Mac שנרדם מקפיא את המכונה, ולשכה על לפטופ אינה זמינה כשהוא ישן או כבוי, בעוד הלשכות האחרות ממשיכות לעבוד. המנוע מפעיל לצדו סוכן שמונע שינה לפי מדיניות שנקבעת בקונסול, בהגדרות מסוף.

## איך מתקינים ב-Windows?

ב-Windows יש דרך אחת: [bbox.cmd](https://github.com/bina-solution/digital-office/blob/main/bbox.cmd) מעביר כל פקודה להפצת WSL בשם `Ubuntu`, ושם רץ Docker של DGO. Docker Desktop, מותקן או לא, [לא בשימוש](https://github.com/bina-solution/digital-office/blob/main/ai/context/running-on-wsl.md), והרצה מ-Git Bash נעצרת בשגיאה. ב-PowerShell כותבים `.\` לפני השם, כי [PowerShell לא מריץ קבצים מהתיקייה הנוכחית](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_command_precedence) בלי נתיב.

**1. WSL והפצה.** [Microsoft](https://learn.microsoft.com/en-us/windows/wsl/install) דורשת Windows 10 גרסה 2004 ומעלה או Windows 11. ב-PowerShell שנפתח כמנהל מתקינים רק את WSL, מפעילים מחדש, ואז מתקינים את ההפצה:

```powershell
wsl --install --no-distribution
wsl --install -d Ubuntu-24.04 --name Ubuntu
wsl -l -v
```

למה לא `wsl --install -d Ubuntu`? [הרשימה הרשמית של WSL](https://raw.githubusercontent.com/microsoft/WSL/master/distributions/DistributionInfo.json) מגדירה היום את `Ubuntu` כ-Ubuntu 26.04.1, ול-26.04 אין חבילת Docker 28. הדגל [`--name`](https://github.com/microsoft/WSL/blob/master/localization/strings/en-US/Resources.resw) ([דוגמה אצל Ubuntu](https://ubuntu.com/wsl/docs/latest/howto/manage-and-configure/)) נותן להפצה 24.04 את השם ש-`bbox.cmd` מחפש. תתבקשו ליצור משתמש וסיסמה בלינוקס, ו-`wsl -l -v` צריך להציג `Ubuntu` עם VERSION 2. הפצה קיימת בשם `Ubuntu` אפשר להחליף ב-`wsl --unregister Ubuntu`, אבל [הפקודה מוחקת כל נתון בה](https://learn.microsoft.com/en-us/windows/wsl/basic-commands).

[[screenshot: PowerShell עם הפלט של wsl -l -v: הפצה בשם Ubuntu, מצב Running, גרסה 2 | alt: פלט של wsl -l -v שמציג הפצת Ubuntu בגרסת WSL 2]]

**2. git ושכפול.**

```powershell
winget install --id Git.Git -e --source winget
git clone https://github.com/bina-solution/digital-office C:\dgo
cd C:\dgo
```

החבילה ב-winget [אינה מתוחזקת](https://git-scm.com/install/windows) בידי פרויקט Git for Windows. עדיף נתיב קצר ובאותיות לטיניות כמו `C:\dgo`: תיקיית משתמש בשם עברי שכיחה בישראל, והנתיב עובר דרך `wslpath` ודרך Docker.

**3. תלות ו-`.env`.** `wsl -d Ubuntu -- python3 -c "import yaml"` אמור לא להדפיס כלום; אם הודפס `ModuleNotFoundError`, מתקינים `python3-yaml`, כי [reconcile.py](https://github.com/bina-solution/digital-office/blob/main/platform/manager/reconcile.py) מסתיים בלעדיו ב-`PyYAML required`. אחר כך יוצרים `.env` כמו למעלה.

**4. הכנת המכונה.** `.\bbox.cmd install windows` [מוסיפה](https://github.com/bina-solution/digital-office/blob/main/scripts/install-windows) ל-`/etc/wsl.conf` מצב mount עם metadata, שבלעדיו הרשאות הקבצים על C: לא עובדות, ומתקינה בתוך Ubuntu את git ואת Docker 28.5.2. אם הודפס שהקובץ שונה, מריצים `wsl --shutdown` מ-Windows ושוב את הפקודה. הסוף: `Windows host ready.`

**5. הרצה.** `.\bbox.cmd run`

הפקודה גם [רושמת ב-Task Scheduler](https://github.com/bina-solution/digital-office/blob/main/scripts/windows/platform-keepalive.ps1) שלוש משימות `Platform-OS-*` שמחזיקות את ההפצה פעילה אחרי אתחול ובודקות בריאות כל חמש דקות, ועלולה להציג בקשת אישור מנהל לכלל בחומת האש. מסירים אותן עם `powershell -ExecutionPolicy Bypass -File scripts\windows\platform-keepalive.ps1 -Uninstall`.

## איך מתקינים ב-Linux או ב-VPS?

מכונה עם ההפצות שבטבלה ומשתמש עם sudo:

```bash
sudo apt-get update && sudo apt-get install -y git python3-yaml
git clone https://github.com/bina-solution/digital-office
cd digital-office
bash scripts/ci-env.sh      # אם בחרתם בו, ראו למעלה
./bbox install debian
```

הסקריפט מתקין את git ואת Docker 28.5.2 מ-apt של Docker, מצמיד אותו ב-`apt-mark hold` כדי ש-`apt upgrade` לא יקפיץ אותו ל-29, מוסיף אתכם לקבוצת `docker`, ויוצר את הרשת ואת `.env` אם חסרים. מתנתקים ומתחברים מחדש כדי שהקבוצה תיכנס לתוקף, ובודקים:

```bash
docker version --format '{{.Server.Version}}'
```

התשובה צריכה להיות `28.5.2`. אז `./bbox run`. ההרצה הראשונה מלמדת את שירות Docker להאזין גם ל-`/run/bbox-docker.sock`, ולשם כך צריך root או sudo בלי סיסמה; בלעדיהם תודפס שורה `cannot provision … (needs root or passwordless sudo)` וההרצה תמשיך עם ה-daemon שעונה.

:::warning
Traefik [מפרסם](https://github.com/bina-solution/digital-office/blob/main/platform-base/traefik/docker-compose.yml) את פורטים 5432 ו-6379 לצד 80 ו-443. [Docker מזהיר](https://docs.docker.com/engine/install/debian/) שפורטים שהוא מפרסם עוקפים את ufw ואת firewalld, ולכן ב-VPS עם כתובת ציבורית חוסמים אותם בחומת האש של הספק, אלא אם אתם צריכים אותם מרחוק.
:::

שעון: ב-`.env` השורה `# TZ=Asia/Jerusalem` מוערת, וברירת המחדל היא שעון המכונה. אם הוא לא שעון ישראל, מסירים את ההערה. כתובת אמיתית עם HTTPS: [DGO על VPS קטן](dgo://tutorial/dgo-on-a-small-vps).

## איך יודעים שההתקנה הצליחה?

```bash
./bbox status
curl -sI -H 'Host: console.localhost' http://127.0.0.1 | head -1
```

`status` (ב-Windows: `.\bbox.cmd status`) מדפיס `containers: N up / M (K healthy; one-shot init containers exit 0)` ומסמן `DOWN` כל קונטיינר שנפל. ה-`curl` בודק ניתוב ולא רק צבע; ב-Mac הכתובת `http://127.0.0.1:8080` והכותרת `Host: console.localhost:8080`, וב-Windows פשוט פותחים את הכתובת בדפדפן. 200 או 302 (הפניה למסך הכניסה) עוברים. 404 אומר שאין ניתוב, גם כשכל הקונטיינרים ירוקים.

[[screenshot: הפלט של ./bbox status בסוף הרצה מוצלחת, עם שורת containers | alt: טרמינל שמציג את שורת הסיכום של bbox status ללא קונטיינרים במצב DOWN]]

הכניסה הראשונה עוברת דרך authentik. [תבנית ה-`.env`](https://github.com/bina-solution/digital-office/blob/main/.env.ex) קובעת את המשתמש `akadmin` ואת הסיסמה `AUTHENTIK_BOOTSTRAP_PASSWORD`, ומציינת שהם משמשים רק בהפעלה הראשונה. את שניהם מוצאים כך (ב-PowerShell: `Select-String '^AUTHENTIK_BOOTSTRAP_(USER|PASSWORD)=' .env`), ואל תצלמו את המסך:

```bash
grep -E '^AUTHENTIK_BOOTSTRAP_(USER|PASSWORD)=' .env
```

[[fact: first sign-in on a fresh install: whether the console asks for the authentik akadmin user and the AUTHENTIK_BOOTSTRAP_PASSWORD from .env, and what the screen shows after it]]

[[screenshot: הקונסול «המרכז» בכניסה הראשונה, בעברית וב-RTL, עם חלון «ניהול אפליקציות» פתוח | alt: שולחן עבודה בעברית עם חלון ניהול אפליקציות פתוח]]

:::dgo
אחרי ההתקנה יש לכם לשכה אחת: קונסול בעברית מימין לשמאל שבו כל אפליקציה נפתחת בחלון משלה, כניסה אחת (authentik) לכולן, ומסך «ניהול אפליקציות» להתקנה, הפעלה והסרה. סיסמאות ומפתחות יושבים ב«חיבורים ומפתחות», גיבוי ושחזור מלאים ב«ניהול נתונים», ושירות שמדווח על עצמו כלא תקין מופעל מחדש לבד («ריפוי עצמי»). לשכה על מחשב נוסף מתחברת אל הראשונה, ואפליקציה שרצה באחת נפתחת כאריח בקונסול של האחרת; הגבול הכן הוא שלשכה על לפטופ לא זמינה כשהוא ישן. DGO חינמית ברישיון AGPL v3, ובינה סולושנס מפתחת אותה. כל מה שכתוב כאן פעיל היום.
:::

[[video: youtube | סרטון רשמי של Microsoft על התקנת WSL והפעלה ראשונה של הפצת Ubuntu, מערוץ מאומת של Microsoft | url: ]]

## מה משתבש, ואיך מתקנים?

- **404 בכל כתובת, וכל הקונטיינרים ירוקים.** הלוח אומר שהכול בסדר, הדפדפן חולק עליו. הסיבה הרגילה היא Docker 29: [29.0.0](https://docs.docker.com/engine/release-notes/29/) העלתה ב-10.11.2025 את גרסת ה-API המינימלית ל-1.44 ו-29.3.0 הורידה אותה ב-5.3.2026 ל-1.40, וה-Traefik 3.3 של DGO ([על Traefik](dgo://article/traefik)) מדבר API 1.24, ולכן עולה בלי נתיבים. Traefik [תיקן את זה ב-3.6.1](https://github.com/traefik/traefik/releases/tag/v3.6.1), ו-DGO עדיין על 3.3. `docker info` צריך להדפיס Server Version של 28.x, ו-[28.5.2](https://docs.docker.com/engine/release-notes/28/) היא האחרונה בקו 28. ב-Mac גורם נוסף: `.env` ידני עם כתובות בלי `:8080`.
- **`docker compose up -d` הסתיים בהצלחה ולא הרים כלום.** ה-`compose.yml` בשורש מצהיר רק על הרשת, והשירותים מקומפלים ל-`.generated/` ([README](https://github.com/bina-solution/digital-office/blob/main/README.md)). מריצים רק `./bbox run`.
- **`could not resolve this directory inside the WSL distro 'Ubuntu'`.** אין הפצה בשם `Ubuntu`. `wsl -l -v` מראה מה קיים.
- **`debian-install.sh` נעצר בשלב Docker, אחרי `apt-get update`.** בודקים `lsb_release -rs`: אם יצא 26.04, אין שם Docker 28. ב-WSL מחליפים להפצת 24.04, וב-VPS בוחרים תבנית אחרת.
- **`running under Git-Bash`.** מריצים מ-CMD או מ-PowerShell: Git Bash רואה רק את Docker Desktop.
- **`0x80370102` בהתקנת WSL.** [לפי Microsoft](https://learn.microsoft.com/en-us/windows/wsl/troubleshooting) מפעילים את Virtual Machine Platform ומוודאים שהווירטואליזציה פעילה ב-BIOS.
- **`Wsl/Service/0x8007274c` באמצע בנייה.** זו [חריגת זמן](https://github.com/microsoft/WSL/issues/11975) מול המכונה הווירטואלית ולא כשל בתוכה, ובדרך כלל מנסים שוב. `wsl --shutdown` מחזיר ל-Windows את הזיכרון, אבל עוצר כל הפצה, אז רק בנקודת ביניים.
- **`PyYAML required`.** חסרה `python3-yaml`: `sudo apt-get install -y python3-yaml`.
- **`permission denied` מול הסוקט של Docker.** המשתמש עדיין לא בקבוצת `docker`: מתנתקים ומתחברים מחדש.
- **פורט תפוס.** תהליך אחר על 80, 443, 5432 או 6379, כמו nginx או PostgreSQL מקומי, מונע מ-Traefik לעלות, ו-80 נופל איתו. את שני האחרונים מזיזים ב-`.env` עם `TRAEFIK_POSTGRES_HOST_PORT` ו-`TRAEFIK_REDIS_HOST_PORT`.
- **`not all services healthy within …`.** ההמתנה נגמרה לפני שהכול עלה, וזה שכיח בבנייה הראשונה על מחשב קטן. מחכים כמה דקות, בודקים `./bbox status`, ומריצים שוב `./bbox run`. `./bbox logs <שירות>` מראה למה שירות לא עולה.

## מה עושים אחרי שזה עובד?

- **לעצור ולהמשיך:** `./bbox stop` מוריד את הקונטיינרים ושומר את הנתונים, ו-`./bbox run` מחזירה אותם. `./bbox reset` מוחקת את כל הנתונים ושואלת אישור. ב-Mac `./bbox engine stop` עוצרת גם את המכונה.
- **לגבות:** גיבוי ושחזור מלאים נמצאים ב«ניהול נתונים».
- **להוסיף אפליקציות:** [להתקין, להפעיל ולכבות אפליקציות](dgo://tutorial/installing-apps-in-dgo).
- **לחבר לשכה שנייה:** [המשולש](dgo://article/the-triangle) מסביר איך אפליקציה מלשכה אחת נפתחת בקונסול של אחרת.
- **להבין את הרישיון:** [AGPL v3, GPL, MIT ו-fair-code](dgo://article/open-source-licenses).
