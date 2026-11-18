---
title: שורת הפקודה
description: כל פקודה של bbox, הפקודה של הלשכה, לפי נושא.
---

## תקציר

```bash
./bbox <פקודה> [ארגומנטים]
./bbox <אפליקציה> <פועל> [ארגומנטים]
./bbox help
```

על Windows: `bbox.cmd` במקום `./bbox`. בלי פקודה, `bbox` מראה את העזרה.

הדגל `--force` מתקבל בכל פקודה, ומדלג על שאלת האישור.

## מחזור החיים

| פקודה | מה היא עושה |
|---|---|
| `bbox run [svc...]` | מעלה את הלשכה, או רק את השירותים שנכתבו. |
| `bbox stop` | מוריד את הלשכה. הקונטיינרים יורדים, הנתונים נשמרים. |
| `bbox reset [--force]` | **מוחק את כל הנתונים.** שואל לפני כן. |
| `bbox status` | תמונת מצב: קונטיינרים, אוטומציות והרשאות. |
| `bbox context [app] [--json]` | מה הלשכה, או אפליקציה אחת, היא ועושה עכשיו: התדריך, הפקודות והמצב של כל אפליקציה, נקראים בזמן אמת. |
| `bbox computers map [--json]` | כל רשת הלשכות כמו שהיא עכשיו: כל לשכה, המחשב שלה, הקישור אליה ומה רץ בה. נקרא בזמן אמת, לא מקובץ במאגר. |
| `bbox verify [dependencies]` | בדיקת מוכנות. יוצא עם קוד שאינו אפס כשמשהו שבור. |
| `bbox logs [svc] [-f]` | יומנים של כל השירותים או של אחד. `-f` ממשיך לעקוב. |
| `bbox update <app…>` | פורס אפליקציה שנבנתה מחדש, מחכה שתהיה תקינה, וחוזר אחורה אם לא. |
| `bbox follow [--dry-run\|heal\|status\|install]` | הלשכה מעדכנת את עצמה מהענף שב-`DGO_FOLLOW`. |
| `bbox agent <verb>` | הסוכן של הלשכה מהמסוף. `bbox agent --help` מראה הכול. |
| `bbox remote [office [alias [path]]]` | האפליקציות של לשכה מקושרת. |
| `bbox via <office> <bbox args…>` | מריץ פקודת `bbox` על לשכה מקושרת. |
| `bbox dialable [-Check\|-Undo]` | האם לשכה אחרת יכולה להתקשר ללשכה הזו. |
| `bbox secrets check` | מפתחות ב-`.env` שריקים או שעדיין יש בהם ערך מתבנית. שמות בלבד. |
| `bbox secrets plan [KEY…]` | איך מחליפים כל מפתח כזה, ומי קורא אותו. לא כותב דבר. |
| `bbox rename-address [--dry-run] <old-domain> <new-domain>` | הלשכה עברה לדומיין אחר: הכתובות של האנשים עוברות איתה. |

## העברה למחשב אחר

| פקודה | מה היא עושה |
|---|---|
| `bbox export [--mode full\|config] [--quiesce] [--out DIR]` | שומר את כל מה שאין בתיקייה: מסדי נתונים, אוטומציות, מסמכים, משתמשים. ברירת המחדל: `exports/`. |
| `bbox import [DIR]` | משחזר ארכיון לתוך התיקייה הזו. |

## המחשב

| פקודה | מה היא עושה |
|---|---|
| `bbox apparmor [status\|validate\|verify\|install\|uninstall]` | בודק את AppArmor של המחשב. `install` דורש `sudo`. |
| `bbox host-power [status\|install\|uninstall]` | מחשב נייד שמריץ לשכה: לא נרדם, לא מתחמם. `install` דורש `sudo`. |
| `bbox baseline` | בדיקה מאפס: מוחק, בונה, מעלה ובודק. |
| `bbox ui-map` | מצלם את כל המסכים לתמונה אחת. |
| `bbox flow-qa [suite…]` | מריץ כל תהליך ובודק את התוצאה. |
| `bbox seed` | ממלא נתוני הדגמה, כדי שכל מסך יראה תוכן. |

## אוטומציות (n8n)

| פקודה | מה היא עושה |
|---|---|
| `bbox n8n pull <app> [wfId ...]` | מהמערכת החיה לקוד. |
| `bbox n8n push <app> <wfId ...>` | מהקוד למערכת החיה. |
| `bbox n8n status` | מה השתנה, מה פורסם, אילו הרשאות. |
| `bbox n8n test <app> <wfId>` | מפעיל ומחזיר תוצאה. |
| `bbox n8n verify` | בודק את ההרשאות ומחזיר קישורים לחיבור מחדש. |

`bbox help` מראה את כל הפקודות של n8n.

## אפליקציות וקטלוג

| פקודה | מה היא עושה |
|---|---|
| `bbox apps list\|validate` | התוכנית של הלשכה; בדיקת ההצהרות. |
| `bbox apps enable\|disable <app>…` | מדליק או מכבה. הנתונים נשמרים תמיד. |
| `bbox catalog keygen` | יוצר מפתח חתימה ללשכה. |
| `bbox catalog build` | בונה קטלוג חתום מ-`apps/`. |
| `bbox catalog verify [ref]` | בודק את החתימה ואת כל רשומה. |
| `bbox catalog list [ref]` | הרשומות בקטלוג. |
| `bbox catalog show <id>` | מה האפליקציה תעשה, לפני ההתקנה. |
| `bbox catalog trust <key-id> <hex>` | סומך על מפתח של מפרסם. |
| `bbox app install <ref>` | מתקין לפי מזהה, כתובת או תיקייה. `--dry-run` רק מראה. |

## התקנה

| פקודה | מה היא עושה |
|---|---|
| `bbox install debian` | `git` ו-Docker על Debian או Ubuntu. |
| `bbox install windows` | הכנת WSL. מריצים דרך `bbox.cmd`, לא דרך Docker Desktop. |
| `bbox install macos` | המנוע של הלשכה על Mac, בלי הרשאות מנהל. |
| `bbox engine <verb>` | macOS בלבד: `start`, `stop`, `status`, `shell`, `socket`, `doctor`, `destroy`. |

## הפעלה ראשונה

| פקודה | מה היא עושה |
|---|---|
| `bbox onboarding` | בודק דרישות, מעלה, מחכה שהכול תקין, ובודק. בלשכה בלי n8n (וכך לשכה חדשה) הוא מחכה לה כארבע דקות ונגמר ב-«n8n REST not ready yet»: שם בודקים עם `bbox status` ו-`bbox verify`. |
| `bbox onboarding --auth-state` | רק בודק הרשאות ומחזיר קישורים לחיבור מחדש. |

## הפעלים של כל אפליקציה

```bash
./bbox <app> <verb>
```

לכל אפליקציה שיש לה תיקיית `hooks/` יש פעלים משלה. `bbox help` מראה אותם, נבנים מהקבצים עצמם. לחלק מהאפליקציות יש שם קצר ב-`app.json`.

## דוגמאות

```bash
./bbox status
./bbox logs -f
./bbox apps enable drive
./bbox drive find חשבונית
```

## ראו גם

- [האפליקציות](/he/apps)
- [לסוכנים](/he/for-agents)
