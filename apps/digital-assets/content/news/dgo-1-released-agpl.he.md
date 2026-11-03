---
type: news
slug: dgo-1-released-agpl
lang: he
title: "DGO שוחררה בקוד פתוח ברישיון AGPL v3: מה מותר, מה חובה ומה נשאר בחוץ"
seo_title: "DGO ברישיון AGPL v3: קוד פתוח, מה מותר ומה חובה"
meta_description: "הלשכה הדיגיטלית (DGO) שוחררה ב-19.10.2026 ברישיון AGPL v3: מה מותר, מה דורש סעיף 13 ולמה n8n נשארת מחוץ לרישיון. נכון לאוקטובר 2026."
summary: "הלשכה הדיגיטלית (DGO) של בינה סולושנס שוחררה ב-19.10.2026 כקוד פתוח ברישיון GNU AGPL v3 לכל המאגר. מותר להשתמש בה, ללמוד אותה, לשנות אותה ולמכור שירותים מעליה; מי ששינה את הקוד ואחרים משתמשים בגרסה שלו דרך רשת חייב להציע להם את קוד המקור שלה (סעיף 13). האפליקציות החיצוניות שרצות בלשכה, ובהן n8n, נשארות תחת הרישיונות שלהן, ו-n8n אינה קוד פתוח."
category: licensing
tags: [ DGO, AGPL, קוד פתוח, רישיון, copyleft, סעיף 13, n8n, GitHub, בינה סולושנס, self-hosting ]
keywords: { primary: "DGO AGPL", secondary: [ "הלשכה הדיגיטלית קוד פתוח", "רישיון AGPL מה מותר", "AGPL סעיף 13", "n8n לא קוד פתוח" ] }
plane: DGO-662
author: צוות בינה סולושנס
publisher: בינה סולושנס
published: 2026-10-19
updated: 2026-10-19
words: 0
reading_minutes: 0
faq:
  - q: "מה זה רישיון AGPL, ובמה הוא שונה מ-GPL?"
    a: "AGPL v3 היא GPL v3 עם דרישה נוספת אחת: מי ששינה את התוכנה ומשרת בה אחרים דרך רשת חייב להציע להם את קוד המקור של הגרסה שלו (סעיף 13). ב-GPL הרגיל חובת השיתוף חלה רק על מי שמפיץ עותקים, ולכן שרת שמריץ גרסה ששונתה לא היה חייב דבר. ה-OSI אישר את AGPL ב-3 במרץ 2008."
  - q: "האם אפשר להשתמש ב-DGO בעסק בלי לשלם ובלי לפרסם את הקוד שלי?"
    a: "כן. הרצה של DGO כמו שהיא בעסק שלכם אינה כרוכה בתשלום ואינה מחייבת לפרסם דבר: הרשאת ההרצה בלתי מוגבלת (סעיף 2). חובת ההצעה של קוד המקור חלה רק על מי ששינה את התוכנה ואחרים משתמשים בגרסה שלו דרך רשת."
  - q: "האם מותר למכור שירותי התקנה ותמיכה על DGO?"
    a: "כן. הרישיון מתיר לגבות כל מחיר על עותק ועל תמיכה (סעיף 4), ואוסר לגבות דמי רישיון על הזכויות עצמן (סעיף 10). מי שמארח לשכות ללקוחות בודק בנפרד את הרישיון של האפליקציות שבתוכן, ובהן n8n."
  - q: "מה בדיוק דורש סעיף 13 של AGPL?"
    a: "מי ששינה את התוכנה צריך להציע בבולטות לכל המשתמשים שמתקשרים איתה דרך רשת הזדמנות לקבל את קוד המקור של הגרסה שלו, משרת ברשת, בחינם ובדרך הורדה מקובלת. הרצה של גרסה שלא שונתה אינה מפעילה את הסעיף. הקונסול של DGO עדיין לא מציג למשתמשיו קישור כזה."
  - q: "האם כל מה שרץ בתוך DGO הוא קוד פתוח?"
    a: "לא. AGPL חלה על המאגר של DGO. אפליקציות חיצוניות שהלשכה מריצה נשארות תחת הרישיון שלהן, ו-n8n תחת Sustainable Use License, שאינו קוד פתוח. התוכנית היא להוציא את n8n מהליבה ולהציע אותה כתוסף אופציונלי."
  - q: "איפה מורידים את הקוד של DGO ואיך מריצים אותו?"
    a: "במאגר github.com/bina-solution/digital-office. מריצים ./bbox run (ב-Windows bbox.cmd run) על Docker 28.x ובלי Docker Desktop. הבנייה הראשונה לוקחת 10 עד 15 דקות על מחשב קטן."
  - q: "כמה עולה להריץ את DGO?"
    a: "DGO עצמה חינמית. משלמים על המחשב, על VPS אם רוצים, ועל API של מודל AI אם בוחרים. VPS מסוג Hostinger KVM 2 עולה 8.79$ לחודש במבצע ו-14.99$ בחידוש, כ-27 עד 47 ₪ בשער היציג של 3.11 ש״ח לדולר ב-19.10.2026."
sources:
  - { title: "GitHub: bina-solution/digital-office (המאגר הציבורי של DGO)", url: "https://github.com/bina-solution/digital-office", accessed: 2026-10-19 }
  - { title: "GitHub: digital-office, קובץ LICENSE", url: "https://github.com/bina-solution/digital-office/blob/main/LICENSE", accessed: 2026-10-19 }
  - { title: "GitHub: digital-office, קובץ NOTICE.md", url: "https://github.com/bina-solution/digital-office/blob/main/NOTICE.md", accessed: 2026-10-19 }
  - { title: "GitHub: digital-office, קומיט השחרור ea3961b (19.10.2026)", url: "https://github.com/bina-solution/digital-office/commit/ea3961bb54f41a0c897ecb06332bac9498cf96a5", accessed: 2026-10-19 }
  - { title: "GNU: GNU Affero General Public License, version 3", url: "https://www.gnu.org/licenses/agpl-3.0.html", accessed: 2026-10-19 }
  - { title: "GNU: Why the Affero GPL", url: "https://www.gnu.org/licenses/why-affero-gpl.html", accessed: 2026-10-19 }
  - { title: "SPDX License List (עמודת OSI Approved)", url: "https://spdx.org/licenses/", accessed: 2026-10-19 }
  - { title: "Open Source Initiative: GNU Affero General Public License version 3", url: "https://opensource.org/license/agpl-v3", accessed: 2026-10-19 }
  - { title: "FOSSA: OSS license compliance expert Heather Meeker on the AGPL (2022-01-25)", url: "https://fossa.com/blog/oss-license-compliance-expert-heather-meeker-agpl/", accessed: 2026-10-19 }
  - { title: "Kyle E. Mitchell: Reading AGPL, a guided introduction for first-timers (2021-01-24)", url: "https://writing.kemitchell.com/2021/01/24/Reading-AGPL", accessed: 2026-10-19 }
  - { title: "n8n Docs: Community license", url: "https://docs.n8n.io/n8n-community-license/", accessed: 2026-10-19 }
  - { title: "n8n Docs: License FAQ", url: "https://docs.n8n.io/n8n-community-license/community-license/license-faq", accessed: 2026-10-19 }
  - { title: "Google Open Source: AGPL Policy", url: "https://opensource.google/documentation/reference/using/agpl-policy", accessed: 2026-10-19 }
  - { title: "Redis: Redis is now available under the AGPLv3 open source license (2025-05-01)", url: "https://redis.io/blog/agplv3/", accessed: 2026-10-19 }
  - { title: "Elastic: Elasticsearch is open source again (2024-08-29)", url: "https://www.elastic.co/blog/elasticsearch-is-open-source-again", accessed: 2026-10-19 }
  - { title: "GitHub: makeplane/plane (AGPL v3)", url: "https://github.com/makeplane/plane", accessed: 2026-10-19 }
  - { title: "GitHub: nextcloud/server (AGPL v3)", url: "https://github.com/nextcloud/server", accessed: 2026-10-19 }
  - { title: "GitHub: grafana/grafana (AGPL v3)", url: "https://github.com/grafana/grafana", accessed: 2026-10-19 }
  - { title: "Hostinger: VPS hosting (KVM 2)", url: "https://www.hostinger.com/vps-hosting", accessed: 2026-10-19 }
  - { title: "Bank of Israel: exchange rates (public API)", url: "https://boi.org.il/PublicApi/GetExchangeRates?asXml=false", accessed: 2026-10-19 }
  - { title: "הלשכה הדיגיטלית: עמוד הרישיון באתר המוצר", url: "https://digital-office.co.il/license.html", accessed: 2026-10-19 }
related: [ "dgo://article/open-source-licenses", "dgo://tutorial/install-dgo-with-claude", "dgo://tutorial/install-dgo-manually", "dgo://article/n8n", "dgo://article/plane", "dgo://glossary/terms-part-1" ]
---

# DGO שוחררה בקוד פתוח ברישיון AGPL v3: מה מותר, מה חובה ומה נשאר בחוץ

הלשכה הדיגיטלית (DGO) של בינה סולושנס שוחררה ב-19 באוקטובר 2026 כקוד פתוח, ברישיון [GNU AGPL v3](https://www.gnu.org/licenses/agpl-3.0.html) לכל [המאגר ב-GitHub](https://github.com/bina-solution/digital-office). מותר להשתמש בה, להריץ, ללמוד, לשנות ולמכור שירותים מעליה, בלי תשלום ובלי לבקש רשות. חובה חריגה אחת: מי ששינה את הקוד ואחרים משתמשים בגרסה שלו דרך רשת חייב להציע להם את קוד המקור שלה (סעיף 13).

מי שמריץ את DGO כמו שהיא בעסק של עצמו לא חייב כלום. מי שמתקין אותה ללקוחות צריך את הטבלה שלמטה. הסתייגות אחת: האפליקציות החיצוניות שרצות בלשכה, ובהן n8n, נשארות תחת הרישיונות שלהן, ו-n8n אינה קוד פתוח.

## מה שוחרר ב-19 באוקטובר?

קובץ [LICENSE](https://github.com/bina-solution/digital-office/blob/main/LICENSE) הוא הנוסח המלא של AGPL v3, זהה לנוסח ב-gnu.org. לפי [NOTICE](https://github.com/bina-solution/digital-office/blob/main/NOTICE.md), זכויות היוצרים של בינה סולושנס משנת 2023, והרישיון הוא גרסה 3 או כל גרסה מאוחרת יותר, לבחירתכם. ה-OSI, הארגון שמגדיר קוד פתוח, [אישר את AGPL](https://opensource.org/license/agpl-v3) ב-3 במרץ 2008: זה קוד פתוח לפי ההגדרה הרשמית, לא fair-code.

מה שפורסם הוא [צילום של ענף הפיתוח](https://github.com/bina-solution/digital-office/commit/ea3961bb54f41a0c897ecb06332bac9498cf96a5) מ-12 באוקטובר, בלי ההיסטוריה שלו: ארבעה קומיטים (commits, שמירות בהיסטוריית הגרסאות) ביום השחרור. נתוני לקוחות וסריקות מסמכים לא נכללו.

[[image: דף המאגר ב-GitHub | alt: דף המאגר של DGO ב-GitHub עם תג הרישיון AGPL-3.0 | source: project-site]]

## מה מותר ומה חובה לפי AGPL?

AGPL היא GPL עם תוספת אחת לשרתים: [קרן התוכנה החופשית (FSF)](https://www.gnu.org/licenses/why-affero-gpl.html) מסבירה שהיא נועדה למנוע מצב שבו מפתח משנה תוכנה ומריץ אותה אצלו בלי להפיץ עותק. סעיף 13 חל רק כששני תנאים מתקיימים יחד: שיניתם את התוכנה, ואחרים משתמשים בה דרך רשת. כך קוראים אותו [Heather Meeker](https://fossa.com/blog/oss-license-compliance-expert-heather-meeker-agpl/), מומחית לרישוי, ו-[Kyle E. Mitchell](https://writing.kemitchell.com/2021/01/24/Reading-AGPL). לפי Meeker שינוי הוא בדרך כלל שינוי קוד ולא הגדרות, ובמאמר מ-2022 היא מציינת שאין פסיקה בנושא.

|מה אתם עושים|מה [הרישיון](https://www.gnu.org/licenses/agpl-3.0.html) דורש|
|---|---|
|מריצים את DGO כמו שהיא בעסק שלכם|כלום. ההרצה בלתי מוגבלת והזכות בלתי הפיכה כל עוד עומדים בתנאים (סעיף 2)|
|מתקינים ללקוחות וגובים על התקנה ותמיכה|מותר, בכל מחיר (סעיף 4). דמי רישיון על הזכויות עצמן אסורים (סעיף 10)|
|משנים את הקוד, ואחרים משתמשים בגרסה שלכם דרך הרשת|להציע להם בחינם את קוד המקור של הגרסה שלכם, בדרך הורדה מקובלת (סעיף 13)|
|מפיצים עותק ששונה, או משלבים אותו במוצר|כל היצירה תחת AGPL, עם הערה מה שיניתם ומתי; מוצר סגור לא יכול להכיל אותה (סעיף 5)|

דוגמה: איש IT שמתקין לשכה לרואה חשבון ומחייב על ההתקנה והתמיכה פועל לפי הרישיון. אם שינה את הקונסול ומארח את הגרסה שלו לכמה לקוחות, כל אחד מהם זכאי לקוד שלה. לשילוב במוצר סגור: [[fact: האם בינה סולושנס מציעה רישיון מסחרי נפרד, ובאילו תנאים]].

:::warning
זה סיכום ולא ייעוץ משפטי; הנוסח המחייב הוא קובץ LICENSE. שילוב קוד של DGO באפליקציה שלכם, או אירוח לשכה ששיניתם ללקוחות: כאן כדאי שעורך דין יקרא את סעיפים 5 ו-13.
:::

## מה AGPL לא מכסה בלשכה?

AGPL חלה על המאגר. האפליקציות החיצוניות שהלשכה מריצה (n8n, authentik, Traefik, PostgreSQL, Redis, Plane ועוד) נמשכות כאימג׳ים, ולפי NOTICE כל אחת בשימוש לפי הרישיון שלה. גם הרכיבים שהועתקו למאגר (MIT, SIL OFL, Apache 2.0) שומרים את הרישיון שלהם.

n8n היא החריג: היא תחת Sustainable Use License, ו[התיעוד שלה](https://docs.n8n.io/n8n-community-license/) מסביר למה היא אינה קוד פתוח. לפי [שאלות הרישיון](https://docs.n8n.io/n8n-community-license/community-license/license-faq) מותר להשתמש בה לצורכי העסק ולבנות ללקוחות אוטומציות שהם לא עורכים, ואסור לארח אותה כשירות שבו לקוחות בונים תהליכים. התוכנית היא להוציא את n8n מהליבה ולהציע אותה כתוסף אופציונלי; פרטים ב[מאמר על n8n](dgo://article/n8n).

[[diagram: שלוש שכבות רישיון: המאגר תחת AGPL, רכיבים מועתקים תחת MIT, OFL ו-Apache, אימג׳ים חיצוניים כל אחד תחת הרישיון שלו | alt: תרשים של שלוש שכבות רישיון בלשכה]]

## מה עוד לא סגור?

- **אין קישור למקור בקונסול.** הקונסול עדיין לא מציג למשתמשים קישור לקוד המקור של הגרסה שרצה; הפתרון הנפוץ, לפי Meeker, הוא קישור להורדה בתוך הממשק.
- **אין עדיין ענן מנוהל.** את הלשכה מריצים אתם, על מחשב או על VPS.
- **הפרויקט צעיר.** כוכב אחד ב-GitHub ביום השחרור לא מוכיח דבר; בדקו אותו לפני שבונים עליו עסק.

## למה AGPL לא מוזרה, ומתי היא בעיה?

AGPL נפוצה בתשתיות: [Plane](https://github.com/makeplane/plane), [Nextcloud](https://github.com/nextcloud/server) ו-[Grafana](https://github.com/grafana/grafana) משתמשות בה. [Elastic](https://www.elastic.co/blog/elasticsearch-is-open-source-again) הודיעה באוגוסט 2024 שתוסיף אותה, ו-[Redis](https://redis.io/blog/agplv3/) הוסיפה אותה במאי 2025; שתיהן אחרי שעברו לרישיונות ש-[OSI לא מאשר](https://spdx.org/licenses/). מנגד, [גוגל אוסרת](https://opensource.google/documentation/reference/using/agpl-policy) קוד AGPL בתוך החברה, כי המגבלות על תוכנה שמשרתת ברשת קשות לה מאוד לציות. אם הלקוחות שלכם ארגונים כאלה, שאלו את המחלקה המשפטית שלהם לפני שמציעים להם לשכה.

## מה עושים עכשיו?

ההרצה היא פקודה אחת, `./bbox run` (ב-Windows `bbox.cmd run`), על Docker 28.x ובלי Docker Desktop; הבנייה הראשונה לוקחת 10 עד 15 דקות על מחשב קטן.

```bash
git clone https://github.com/bina-solution/digital-office
cd digital-office
./bbox run
```

DGO חינמית, ומשלמים על המחשב. לשכה שלמה רצה אצלנו על VPS מסוג Hostinger KVM 2 (2 vCPU, 8 GB), ש[עולה 8.79$ לחודש במבצע ו-14.99$ בחידוש](https://www.hostinger.com/vps-hosting): כ-27 עד 47 ₪ ב-19.10.2026, בשער [בנק ישראל](https://boi.org.il/PublicApi/GetExchangeRates?asXml=false) 3.11.

ההתקנה צעד אחר צעד: [עם Claude Code](dgo://tutorial/install-dgo-with-claude) או [ידנית](dgo://tutorial/install-dgo-manually). השוואה מלאה בין AGPL, GPL, MIT ו-fair-code: [רישיונות קוד פתוח בעברית](dgo://article/open-source-licenses). בינה סולושנס מפתחת את DGO; ההסבר שלה על הרישיון: [באתר המוצר](https://digital-office.co.il/license.html).
