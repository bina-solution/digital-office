---
type: article
slug: n8n
lang: he
title: "n8n לעסק ישראלי: מה מקבלים, כמה זה עולה ומה לא עובד בעברית"
seo_title: "n8n בעברית: אוטומציה לעסק, רישיון ומחיר (2026)"
meta_description: "מה זה n8n, מה הרישיון מתיר ואוסר, כמה זה עולה בשקלים בענן ובשרת, איך מחברים וואטסאפ וחשבוניות, ומתי Zapier עדיף. נכון לאוקטובר 2026."
summary: "n8n היא פלטפורמת אוטומציה שאפשר להריץ על שרת משלכם: חינם לשימוש עסקי פנימי תחת רישיון fair-code, ומ-20 אירו לחודש בענן. היא חזקה בתהליכים ארוכים וב-AI, אבל הממשק באנגלית בלבד, השרת והעדכונים עליכם, והרישיון אינו קוד פתוח. כשאין מי שמתחזק, Zapier או Make עדיפים."
category: automation
tags: [ n8n, אוטומציה, workflow, self-hosting, fair-code, סוכני AI, וואטסאפ, חשבוניות ישראל, Zapier, Make ]
keywords: { primary: "n8n", secondary: [ "אוטומציה לעסקים", "n8n בעברית", "n8n מול Zapier", "n8n רישיון", "n8n מחיר" ] }
plane: DGO-692
author: צוות בינה סולושנס
publisher: בינה סולושנס
published: 2026-10-19
updated: 2026-10-19
words: 2344
reading_minutes: 12
project:
  name: n8n
  website: https://n8n.io
  repo: https://github.com/n8n-io/n8n
  license: "Sustainable Use License 1.0 (fair-code); קבצים עם ee בשמם תחת n8n Enterprise License"
  stars: "208,030 (2026-10-19)"
  latest_release: "n8n@2.43.8 (2026-10-19)"
  replaces: [ Zapier, Make ]
  dgo_status: live
faq:
  - q: "האם n8n בחינם?"
    a: "ב-self-hosting כן: מהדורת Community חינמית לשימוש עסקי פנימי ובלי תקרת הרצות, ומשלמים רק על השרת, בערך 27 עד 47 ₪ לחודש ב-VPS כמו Hostinger KVM 2. בענן המחיר מתחיל ב-20 אירו לחודש בחיוב שנתי (כ-70 ₪) ל-2,500 הרצות. נכון ל-19.10.2026."
  - q: "האם n8n היא קוד פתוח?"
    a: "לא לפי הגדרת OSI. הרישיון, Sustainable Use License, הוא fair-code: מותר להריץ ולשנות לשימוש עסקי פנימי, אסור לארח אותה כשירות שבו לקוחות בונים תהליכים, וקבצים עם ee בשמם דורשים רישיון Enterprise."
  - q: "האם n8n תומכת בעברית?"
    a: "הממשק באנגלית בלבד (בקוד של העורך יש קובץ תרגום אחד, en.json), ובתיעוד אין אזכור לתמיכה ב-RTL. בנתונים לא נמצא דיווח על כשל כללי, אך יש באגים בקצוות, למשל נושא מייל עברי בצומת Gmail. בדקו נושא עברי ושם קובץ עברי כבר בתהליך הראשון."
  - q: "מה ההבדל בין n8n ל-Zapier?"
    a: "n8n סופרת הרצה שלמה של תהליך ו-Zapier סופרת כל פעולה מוצלחת כמשימה, ולכן תהליך ארוך זול יותר ב-n8n. ל-Zapier קטלוג גדול יותר (מעל 9,000 אפליקציות) ואין שרת לתחזק; n8n דורשת יותר ידע טכני."
  - q: "כמה זיכרון ושרת צריך כדי להריץ n8n?"
    a: "מדריך ה-Docker Compose הרשמי דורש 4GB ו-2 vCPU לפחות, בגלל ה-sandbox של n8n Assistant; מדריך Hetzner שלו מסתפק בשרת הקטן CPX11 לרוב השימושים. במדידה של Hostinger על שרת של 2 vCPU ו-8GB צרכה n8n כ-860MB בסרק, וההמלצה שם היא 4GB לפחות ל-10 עד 20 תהליכים."
  - q: "אפשר לחבר n8n לוואטסאפ?"
    a: "כן, דרך צומת WhatsApp Business Cloud מול ה-API הרשמי של Meta, שמחייב לפי הודעה מאז 1.7.2025. תנאי השימוש של וואטסאפ אוסרים הודעות אוטומטיות והמוניות באפליקציה הרגילה."
  - q: "האם n8n מבקשת מספר הקצאה מרשות המסים?"
    a: "לא. את הבקשה שולחת תוכנת הנהלת חשבונות שחוברה לרשות, או שמגישים אותה ידנית ביישום של הרשות. n8n יכולה לתזמר סביב זה: לבדוק חשבוניות נכנסות מעל 5,000 ₪ לפני מע״מ ולבקש מהספק מספר חסר."
  - q: "איך מגבים n8n?"
    a: "פקודות ה-CLI מייצאות רק workflows ו-credentials. גיבוי מלא כולל את תיקיית .n8n, את מסד הנתונים ואת מפתח ההצפנה, ובלי המפתח אי אפשר לפענח את האישורים."
sources:
  - { title: "n8n: Plans and Pricing", url: "https://n8n.io/pricing/", accessed: 2026-10-19 }
  - { title: "GitHub: n8n-io/n8n (repository, API)", url: "https://github.com/n8n-io/n8n", accessed: 2026-10-19 }
  - { title: "GitHub: n8n releases", url: "https://github.com/n8n-io/n8n/releases", accessed: 2026-10-19 }
  - { title: "n8n: Integrations", url: "https://n8n.io/integrations/", accessed: 2026-10-19 }
  - { title: "Zapier: Pricing", url: "https://zapier.com/pricing", accessed: 2026-10-19 }
  - { title: "Zapier Help: How is task usage measured in Zapier", url: "https://help.zapier.com/hc/en-us/articles/8496196837261-How-is-task-usage-measured-in-Zapier", accessed: 2026-10-19 }
  - { title: "GitHub: n8n LICENSE.md (Sustainable Use License 1.0)", url: "https://github.com/n8n-io/n8n/blob/master/LICENSE.md", accessed: 2026-10-19 }
  - { title: "n8n Docs: Community license", url: "https://docs.n8n.io/n8n-community-license", accessed: 2026-10-19 }
  - { title: "n8n Docs: License FAQ", url: "https://docs.n8n.io/n8n-community-license/community-license/license-faq", accessed: 2026-10-19 }
  - { title: "n8n Docs: Compare editions", url: "https://docs.n8n.io/deploy/host-n8n/community-edition-features", accessed: 2026-10-19 }
  - { title: "n8n Docs: Choose how to use n8n", url: "https://docs.n8n.io/choose-how-to-use-n8n", accessed: 2026-10-19 }
  - { title: "n8n Docs: Full documentation export (llms-full.txt)", url: "https://docs.n8n.io/llms-full.txt", accessed: 2026-10-19 }
  - { title: "Bank of Israel: representative exchange rates (public API)", url: "https://boi.org.il/PublicApi/GetExchangeRates?asXml=false", accessed: 2026-10-19 }
  - { title: "Hostinger: VPS hosting", url: "https://www.hostinger.com/vps-hosting", accessed: 2026-10-19 }
  - { title: "Hostinger: n8n benchmark", url: "https://www.hostinger.com/tutorials/n8n-benchmark", accessed: 2026-10-19 }
  - { title: "n8n Docs: Deploy to Hetzner", url: "https://docs.n8n.io/deploy/host-n8n/install-options/use-a-cloud-provider/deploy-to-hetzner", accessed: 2026-10-19 }
  - { title: "n8n Docs: Install using Docker Compose", url: "https://docs.n8n.io/deploy/host-n8n/install-options/install-using-docker-compose", accessed: 2026-10-19 }
  - { title: "n8n Docs: Update n8n", url: "https://docs.n8n.io/deploy/host-n8n/keep-n8n-running/update-n8n", accessed: 2026-10-19 }
  - { title: "n8n Docs: Executions environment variables (pruning defaults)", url: "https://docs.n8n.io/deploy/host-n8n/configure-n8n/basic-configuration/use-environment-variables/executions", accessed: 2026-10-19 }
  - { title: "n8n template 4452: Automated PDF invoice processing and approval flow", url: "https://n8n.io/workflows/4452", accessed: 2026-10-19 }
  - { title: "n8n Docs: Extract From File node", url: "https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.extractfromfile/", accessed: 2026-10-19 }
  - { title: "רשות המסים: הוראת ביצוע מס ערך מוסף, הקצאת מספרי חשבוניות (7.12.2025)", url: "https://www.gov.il/BlobFolder/policy/inst-071225-1/he/vat_inst-071225-1.pdf", accessed: 2026-10-19 }
  - { title: "מורנינג (חשבונית ירוקה): הדרישות החדשות בתוקף מ-1.6.26", url: "https://www.greeninvoice.co.il/israel-invoice/", accessed: 2026-10-19 }
  - { title: "מורנינג (חשבונית ירוקה): מודל חשבוניות ישראל, מדריך 2026", url: "https://www.greeninvoice.co.il/magazine/israel-invoice/", accessed: 2026-10-19 }
  - { title: "מורנינג: הרשאה לשירותי הדיגיטל של רשות המסים", url: "https://www.greeninvoice.co.il/help-center/app-tax-auth/", accessed: 2026-10-19 }
  - { title: "Morning developers", url: "https://developers.morning.co/", accessed: 2026-10-19 }
  - { title: "npm: n8n-nodes-icount", url: "https://www.npmjs.com/package/n8n-nodes-icount", accessed: 2026-10-19 }
  - { title: "npm: @bines/n8n-nodes-fireberry", url: "https://www.npmjs.com/package/@bines/n8n-nodes-fireberry", accessed: 2026-10-19 }
  - { title: "npm: n8n-nodes-priority-gateway", url: "https://www.npmjs.com/package/n8n-nodes-priority-gateway", accessed: 2026-10-19 }
  - { title: "n8n Docs: WhatsApp Business Cloud credentials", url: "https://docs.n8n.io/integrations/builtin/credentials/whatsapp/", accessed: 2026-10-19 }
  - { title: "Meta for Developers: WhatsApp Business Platform pricing", url: "https://developers.facebook.com/docs/whatsapp/pricing/", accessed: 2026-10-19 }
  - { title: "WhatsApp: Terms of Service", url: "https://www.whatsapp.com/legal/terms-of-service", accessed: 2026-10-19 }
  - { title: "n8n Docs: Google OAuth for self-hosted n8n", url: "https://docs.n8n.io/integrations/builtin/credentials/google/oauth-single-service/", accessed: 2026-10-19 }
  - { title: "Google Identity: OAuth 2.0, refresh token expiration", url: "https://developers.google.com/identity/protocols/oauth2", accessed: 2026-10-19 }
  - { title: "n8n Docs: monday.com node", url: "https://docs.n8n.io/integrations/builtin/app-nodes/n8n-nodes-base.mondaycom/", accessed: 2026-10-19 }
  - { title: "ארתור מלצר: 5 אוטומציות n8n שכל עסק קטן צריך (פברואר 2026)", url: "https://arthurmeltser.co.il/blog/n8n-automations-for-business/", accessed: 2026-10-19 }
  - { title: "n8n Docs: AI Agent node", url: "https://docs.n8n.io/integrations/builtin/cluster-nodes/root-nodes/n8n-nodes-langchain.agent/", accessed: 2026-10-19 }
  - { title: "n8n Docs: MCP Client Tool node", url: "https://docs.n8n.io/integrations/builtin/cluster-nodes/sub-nodes/n8n-nodes-langchain.toolmcp/", accessed: 2026-10-19 }
  - { title: "n8n Docs: Human-in-the-loop for tools", url: "https://docs.n8n.io/build/integrate-ai/ai-examples/human-in-the-loop-for-tools", accessed: 2026-10-19 }
  - { title: "GitHub: n8n i18n locales folder", url: "https://github.com/n8n-io/n8n/tree/master/packages/frontend/@n8n/i18n/src/locales", accessed: 2026-10-19 }
  - { title: "n8n Docs: Timezone and localization variables", url: "https://docs.n8n.io/deploy/host-n8n/configure-n8n/basic-configuration/use-environment-variables/timezone-and-localization", accessed: 2026-10-19 }
  - { title: "GitHub n8n issue 12569: shortcuts with non-English keyboard layout", url: "https://github.com/n8n-io/n8n/issues/12569", accessed: 2026-10-19 }
  - { title: "GitHub n8n issue 16218: non-English characters in downloaded workflow names", url: "https://github.com/n8n-io/n8n/issues/16218", accessed: 2026-10-19 }
  - { title: "GitHub n8n issue 17514: Gmail node subject encoding", url: "https://github.com/n8n-io/n8n/issues/17514", accessed: 2026-10-19 }
  - { title: "n8n Docs: Performance benchmarking", url: "https://docs.n8n.io/hosting/scaling/performance-benchmarking", accessed: 2026-10-19 }
  - { title: "n8n Docs: Queue mode", url: "https://docs.n8n.io/hosting/scaling/queue-mode/", accessed: 2026-10-19 }
  - { title: "n8n Docs: Binary data", url: "https://docs.n8n.io/hosting/scaling/binary-data/", accessed: 2026-10-19 }
  - { title: "n8n Docs: Back up and restore", url: "https://docs.n8n.io/deploy/host-n8n/keep-n8n-running/backup-and-restore", accessed: 2026-10-19 }
  - { title: "GitHub Advisory Database: n8n (npm)", url: "https://api.github.com/advisories?ecosystem=npm&affects=n8n", accessed: 2026-10-19 }
  - { title: "GitHub Advisory GHSA-v4pr-fm98-w9pg (CVE-2026-21858)", url: "https://github.com/advisories/GHSA-v4pr-fm98-w9pg", accessed: 2026-10-19 }
  - { title: "n8n Docs: Securing n8n", url: "https://docs.n8n.io/hosting/securing/overview/", accessed: 2026-10-19 }
  - { title: "n8n Docs: Schedule Trigger node", url: "https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.scheduletrigger/", accessed: 2026-10-19 }
  - { title: "n8n Docs: Error Trigger node", url: "https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.errortrigger/", accessed: 2026-10-19 }
  - { title: "FahimAI: n8n, 7 things to know before you start (2026)", url: "https://fahimai.com/n8n", accessed: 2026-10-19 }
  - { title: "Jet Admin: Make pricing (checked 2026-09-26)", url: "https://www.jetadmin.io/blog/make-pricing/", accessed: 2026-10-19 }
  - { title: "Make Help: Credits", url: "https://help.make.com/credits", accessed: 2026-10-19 }
  - { title: "GitHub: activepieces/activepieces (repository, LICENSE)", url: "https://github.com/activepieces/activepieces", accessed: 2026-10-19 }
  - { title: "Node-RED: About (OpenJS Foundation)", url: "https://nodered.org/about/", accessed: 2026-10-19 }
  - { title: "GitHub: windmill-labs/windmill (repository, LICENSE)", url: "https://github.com/windmill-labs/windmill", accessed: 2026-10-19 }
related: [ "dgo://comparison/n8n-vs-zapier", "dgo://article/indox-documents-automation", "dgo://tutorial/install-dgo-with-claude", "dgo://project/activepieces", "dgo://project/windmill", "dgo://directory/israeli-business-software" ]
---

# n8n לעסק ישראלי: מה מקבלים, כמה זה עולה ומה לא עובד בעברית

n8n היא פלטפורמת אוטומציה: בונים על קנבס תהליך (workflow) שמחבר בין Gmail, Google Sheets, וואטסאפ, CRM ותוכנת חשבוניות, ומוסיפים קוד כשצריך. היא מתאימה לעסק, לפרילנסר או לצוות שיש בו מי שיטפל בשרת, ופחות למי שרוצה להתקין ולשכוח. נכון ל-19.10.2026 אפשר להריץ אותה בחינם על שרת משלכם (self-hosting) לשימוש עסקי פנימי, תחת רישיון fair-code שאינו קוד פתוח; בענן היא מתחילה ב-20 אירו לחודש בחיוב שנתי (כ-70 ₪); הממשק באנגלית בלבד; וגרסת תיקון יוצאת כמעט בכל יום עבודה.

השורה התחתונה: בתהליכים ארוכים, או כשרוצים סוכן AI שנוגע בנתוני העסק, n8n יוצאת זולה יותר מ-Zapier, כי היא סופרת הרצה שלמה ולא כל צעד. כשאין מי שיעדכן שרת פעם בחודש, Zapier ו-Make עדיפים.

## מה זה n8n, ומה היא מחליפה?

n8n מחליפה את Zapier ואת Make: אותו «כש-X קורה, עשו Y», עם תנאים, לולאות, קוד JavaScript ו-Python וקריאה לכל API דרך צומת (node) HTTP. המאגר ב-[GitHub](https://github.com/n8n-io/n8n), שנוצר ב-2019, עומד ב-19.10.2026 על 208,030 כוכבים, והגרסה היציבה היא [n8n@2.43.8](https://github.com/n8n-io/n8n/releases). [דף האינטגרציות](https://n8n.io/integrations/) מונה 2,367 אינטגרציות, ול-Zapier יש [מעל 9,000 אפליקציות](https://zapier.com/pricing). הספירות אינן זהות, אבל הקטלוג של Zapier גדול בהרבה, וזה חשוב אם המערכת שלכם נישתית.

[[screenshot: n8n בלשכה: קנבס עם תהליך חשבונית נכנסת, מטריגר מייל ועד התראה | alt: קנבס n8n עם צמתים מחוברים בחצים, מטריגר מייל דרך חילוץ PDF ועד התראה בוואטסאפ]]

## האם n8n בקוד פתוח? הרישיון ומלכודותיו

n8n היא fair-code, כלומר קוד גלוי עם הגבלות על שימוש מסחרי, ו[התיעוד שלה](https://docs.n8n.io/n8n-community-license) אומר במפורש שהיא אינה קוד פתוח לפי הגדרת OSI. [הרישיון](https://github.com/n8n-io/n8n/blob/master/LICENSE.md), Sustainable Use License 1.0, מתיר להריץ ולשנות את הקוד לצרכים העסקיים הפנימיים שלכם, בכל גודל חברה, או לשימוש אישי. הפצה מותרת רק בחינם ולא למטרות מסחריות.

לפי [שאלות הרישיון](https://docs.n8n.io/n8n-community-license/community-license/license-faq) של n8n:

- **מותר:** לבנות אוטומציות ללקוחות על המופע שלכם ולגבות על בנייה, תחזוקה והדרכה, כל עוד הלקוחות לא יוצרים או עורכים תהליכים; להתקין n8n על שרת הלקוח בתשלום, בלי לארח אותה בעצמכם; להפעיל אותה כמנוע אחורי במוצר שהמשתמשים רק מפעילים.
- **אסור:** לארח n8n כשירות שבו לקוחות בונים תהליכים, גם דרך ממשק מותאם, API, MCP או סוכן AI שפועל בשמם; לעשות white-label או fork למוצר אוטומציה מתחרה; להשתמש בפיצ׳רים שדורשים מפתח רישיון בלי רישיון Enterprise.
- **אפור:** מוצר בתשלום שמטמיע n8n אצל הלקוח. ה-FAQ מבקש לאשר את הארכיטקטורה מראש ב-person33@example.com.

:::warning
קבצים עם `.ee.` בשמם אינם תחת הרישיון הרגיל, וענפים שאינם master אינם מורשים כלל. הפרה מבטלת את הרישיון אוטומטית; אם מפסיקים תוך 30 יום מההודעה הוא חוזר, פעם אחת בלבד. ב-Community תהליך נראה רק ליוצר שלו ולבעלים של המופע, ושיתוף, פרויקטים, SSO ו-Git דורשים [Business או Enterprise](https://docs.n8n.io/deploy/host-n8n/community-edition-features). מפתח Business מדווח לשרת הרישיון מדי יום, וטלמטריה פעילה כברירת מחדל.
:::

[[image: טבלת המהדורות בתיעוד של n8n | alt: טבלה שמסמנת אילו פיצ׳רים זמינים בכל מהדורה של n8n | source: project-site]]

## כמה זה עולה באמת: ענן או שרת משלכם?

המחירון של n8n בענן הוא באירו. בשער היציג של בנק ישראל מ-19.10.2026 (3.11 ₪ לדולר, 3.4919 ₪ לאירו) הוא נראה כך, לפי [דף המחירים](https://n8n.io/pricing/):

| תוכנית | הרצות בחודש | חיוב שנתי, לחודש | חיוב חודשי |
|---|---|---|---|
| Starter | 2,500 | €20 ≈ ₪70 ≈ $22 | €24 ≈ ₪84 |
| Pro | 10,000 | €50 ≈ ₪175 ≈ $56 | €60 ≈ ₪210 |
| Business (self-hosting בלבד) | 40,000 | €667 ≈ ₪2,329 ≈ $749 | €800 ≈ ₪2,794 |

כל התוכניות כוללות משתמשים ו-workflows בלי הגבלה, ויש [ניסיון חינם של 14 יום](https://docs.n8n.io/choose-how-to-use-n8n). ההבדל המרכזי מ-Zapier הוא יחידת הספירה: n8n סופרת הרצה שלמה בכל מספר צעדים, ו-Zapier סופרת [כל פעולה שהצליחה](https://help.zapier.com/hc/en-us/articles/8496196837261-How-is-task-usage-measured-in-Zapier) (טריגר, Filter ו-Formatter בחינם). תהליך חשבונית של טריגר וחמש פעולות הוא הרצה אחת ב-n8n וחמש משימות ב-Zapier. 600 חשבוניות בחודש הן 600 הרצות, שנכנסות ב-Starter (כ-70 ₪), מול 3,000 משימות, שדורשות ב-Zapier Professional את שכבת 5,000 המשימות: 89$ לחודש בחיוב שנתי (כ-277 ₪, מחירון 19.10.2026).

והצד השני: תהליך מתוזמן שרץ כל חמש דקות שורף [8,600 עד 8,900 הרצות בחודש](https://n8n.io/pricing/), יותר מפי שלושה מחבילת Starter, גם כשאין מה לעבד; ב-Zapier בדיקת טריגר ריקה לא נספרת.

ל-Starter יש תקרה של חמש הרצות במקביל ושל חמש דקות להרצה, ו-Business אינה זמינה כרגע בענן: היא self-hosting בלבד, עם 50% הנחה לחברות מתחת ל-20 עובדים. נתוני הענן יושבים בפרנקפורט.

ב-self-hosting מהדורת Community חינמית ובלי תקרת הרצות; משלמים על השרת. [Hostinger KVM 2](https://www.hostinger.com/vps-hosting) עם 2 vCPU ו-8GB עולה 8.79$ לחודש במבצע ו-14.99$ בחידוש (מחירון 19.10.2026), כ-27 עד 47 ₪. המחיר האמיתי הוא הזמן: n8n עצמה [כותבת](https://docs.n8n.io/deploy/host-n8n/install-options/use-a-cloud-provider/deploy-to-hetzner) ש-self-hosting מיועד למומחים, כי טעות עלולה להביא לאובדן נתונים ולפרצות, ו[ממליצה לעדכן](https://docs.n8n.io/deploy/host-n8n/keep-n8n-running/update-n8n) לפחות פעם בחודש.

## איך מטפלים בחשבוניות ובמסמכים נכנסים?

הזרימה הנפוצה בעסק ישראלי: PDF מגיע למייל או לתיקיית Drive, נקרא, ושורה נכנסת לגיליון או לתוכנת הנהלת החשבונות. [תבנית ציבורית של n8n](https://n8n.io/workflows/4452) עושה את זה כך: Gmail, Drive או טופס, חילוץ טקסט מה-PDF, מודל שפה שמוציא ספק, סכום ותאריך, מייל אישור או דחייה, ורישום ב-Google Sheets.

הצומת [Extract From File](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.extractfromfile/) קורא PDF, ודף התיעוד שלו לא מזכיר OCR (זיהוי טקסט מתמונה), כך שסריקות דורשות שירות נפרד. את איכות ה-OCR העברי אי אפשר לשפוט ממאמר: הריצו עשר חשבוניות אמיתיות לפני שבונים. היסטוריית ההרצות [נמחקת כברירת מחדל אחרי 14 יום](https://docs.n8n.io/deploy/host-n8n/configure-n8n/basic-configuration/use-environment-variables/executions), ולכן הארכיון הוא הגיליון או Drive ולא n8n.

כשהמסמכים מגיעים בכמויות, יש להם אפליקציה ייעודית ב«הלשכה הדיגיטלית (DGO)»: [INDOX](dgo://article/indox-documents-automation), עם סנכרון, חילוץ, תיוק והצגה.

[[diagram: זרימת חשבונית נכנסת: מייל, חילוץ שדות, בדיקת סכום ומספר הקצאה, ואז בקשה לספק או שורה בגיליון | alt: תרשים זרימה של חשבונית נכנסת עם צומת החלטה על מספר הקצאה]]

## מספר הקצאה של רשות המסים: מה n8n יכולה ומה לא?

לפי [הוראת הביצוע של רשות המסים מ-7.12.2025](https://www.gov.il/BlobFolder/policy/inst-071225-1/he/vat_inst-071225-1.pdf), חשבונית מס מעל 5,000 ₪ לפני מע״מ (מ-1.6.2026; מ-1.1.2026 הסף היה 10,000) צריכה מספר הקצאה בן תשע ספרות, בארבעה תנאים: הסכום מעל הסף, יש בחשבונית מע״מ, הלקוח עוסק מורשה, והוא דרש מספר. בלי המספר הלקוח לא מנכה מס תשומות. עוסק פטור מנפיק קבלות בלבד, ולכן [מחוץ לדרישה](https://www.greeninvoice.co.il/magazine/israel-invoice/).

הבקשה מוגשת דרך תוכנת הנהלת חשבונות שחוברה לרשות, או ביישום האינטרנטי של הרשות, חשבונית אחר חשבונית. n8n היא כלי תזמור ולא תוכנת חשבוניות, ולכן אינה מבקשת מספרים בעצמה. [מורנינג](https://www.greeninvoice.co.il/israel-invoice/), למשל, מבקשת אותם אוטומטית אחרי שמחברים אותה לרשות, וההרשאה [תקפה שלושה חודשים](https://www.greeninvoice.co.il/help-center/app-tax-auth/) ודורשת חידוש. מה שכן שווה לבנות סביב זה:

- **חשבוניות נכנסות:** אם אחרי החילוץ הסכום לפני מע״מ מעל הסף ואין מספר בן תשע ספרות, שולחים לספק בקשה אוטומטית ומסמנים בגיליון «ממתין למספר הקצאה». ההוראה מתארת גם לקונה שירותי אימות מספר וקליטת נתוני חשבונית אל הנהלת החשבונות; בדקו מה התוכנה שלכם כבר עושה עם זה לפני שבונים בדיקה משלכם.
- **חשבוניות יוצאות:** במורנינג יש [API עם webhooks](https://developers.morning.co/) (קריאה אליכם בכל מסמך חדש); ל-iCount יש חבילת קהילה, [n8n-nodes-icount](https://www.npmjs.com/package/n8n-nodes-icount), ברישיון MIT ובידי מתחזק יחיד, והגרסה האחרונה שלה מאוקטובר 2025. כך אפשר לשלוח ללקוח את החשבונית בוואטסאפ ברגע שהונפקה.

## איך מחברים וואטסאפ, Google Sheets ו-CRM?

**וואטסאפ.** הצומת [WhatsApp Business Cloud](https://docs.n8n.io/integrations/builtin/credentials/whatsapp/) שולח הודעות ותבניות ומעלה ומוריד מדיה, והטריגר מקבל הודעות נכנסות. צריך חשבון מפתח ב-Meta, Business portfolio ואפליקציה במצב Live עם כתובות של מדיניות פרטיות ותנאי שימוש.

Meta [מחייבת לפי הודעה מאז 1.7.2025](https://developers.facebook.com/docs/whatsapp/pricing/), והתעריף תלוי בקידומת המדינה של הנמען. [תנאי השימוש של וואטסאפ](https://www.whatsapp.com/legal/terms-of-service) אוסרים הודעות המוניות ואוטומטיות ושימוש לא אישי בשירות אלא באישורה, ולכן הודעות אוטומטיות ממספר רגיל עוברות עליהם.

**Google Sheets.** ב-self-hosting אין OAuth מנוהל, ולכן פותחים [פרויקט משלכם ב-Google Cloud](https://docs.n8n.io/integrations/builtin/credentials/google/oauth-single-service/). אפליקציה שנשארה במצב Testing מקבלת [אסימונים שפגים אחרי שבעה ימים](https://developers.google.com/identity/protocols/oauth2), ואז צריך לחבר מחדש.

**CRM.** יש [צומת monday.com](https://docs.n8n.io/integrations/builtin/app-nodes/n8n-nodes-base.mondaycom/) ללוחות, עמודות וקבוצות, ובדף האינטגרציות גם HubSpot ו-Pipedrive. ב-npm יש חבילות קהילה ל-[Fireberry](https://www.npmjs.com/package/@bines/n8n-nodes-fireberry) (לשעבר Powerlink) ול-[Priority](https://www.npmjs.com/package/n8n-nodes-priority-gateway); ל-Cardcom, ל-Tranzila, ל-PayPlus ולרווחית לא נמצאו בחיפוש מ-19.10.2026, ושם מחברים דרך HTTP Request. מה שסוכנויות ישראליות [בונות בפועל](https://arthurmeltser.co.il/blog/n8n-automations-for-business/): ליד מטופס באתר לגיליון ולוואטסאפ של בעל העסק, תזכורות תשלום ב-7, 14 ו-30 יום, תזכורות לפגישות ובקשות לביקורת בגוגל.

## מה אפשר לעשות עם סוכני AI ב-n8n?

צומת [AI Agent](https://docs.n8n.io/integrations/builtin/cluster-nodes/root-nodes/n8n-nodes-langchain.agent/) מחבר מודל שפה ולפחות כלי אחד, והמודל בוחר בעצמו איזה כלי להפעיל. מגרסה 1.82.0 כל הצמתים האלה עובדים כ-Tools Agent, וגרסה 1 של הצומת תוסר ב-n8n 3.0. כלי יכול להיות תהליך אחר, שאילתת Postgres או שרת MCP חיצוני (פרוטוקול שמחבר סוכנים לכלים) דרך [MCP Client Tool](https://docs.n8n.io/integrations/builtin/cluster-nodes/sub-nodes/n8n-nodes-langchain.toolmcp/); ה-MCP Server Trigger עושה את ההפך וחושף את התהליכים שלכם לסוכנים אחרים. יש גם צומת Ollama למודל מקומי, ואפשר [לדרוש אישור אנושי](https://docs.n8n.io/build/integrate-ai/ai-examples/human-in-the-loop-for-tools) לפני שהסוכן מפעיל כלי מסוים.

איכות העברית היא של המודל ולא של n8n: מדדו על מסמכים שלכם. סוכן שקורא מייל נכנס וגם שולח הודעות חשוף להוראות שמוסתרות במסמך, ולכן מגבילים את הכלים ומשאירים אדם בלולאה בכל פעולה שכותבת או שולחת.

## מה לא עובד טוב בעברית?

הממשק באנגלית בלבד: בתיקיית התרגומים של העורך ב-[GitHub](https://github.com/n8n-io/n8n/tree/master/packages/frontend/@n8n/i18n/src/locales) יש קובץ תרגום אחד, `en.json`, ו-[`N8N_DEFAULT_LOCALE`](https://docs.n8n.io/deploy/host-n8n/configure-n8n/basic-configuration/use-environment-variables/timezone-and-localization) מחזיר לאנגלית כל מחרוזת שלא תורגמה. RTL (כתיבה מימין לשמאל) לא מוזכר בתיעוד: חיפוש בייצוא המלא שלו לא מצא RTL, Hebrew או Arabic, וגם ב-GitHub לא נמצאה בקשה ייעודית ל-RTL בעורך. יישור הטקסט העברי בתוך העורך לא נבדק לצורך המאמר, ולכן לא מתואר כאן.

בנתונים לא נמצא דיווח על כשל כללי בעברית, אבל יש באגים בקצוות:

- בינואר 2025 קיצורי Ctrl+C ו-Ctrl+Z [לא עבדו](https://github.com/n8n-io/n8n/issues/12569) כשפריסת המקלדת עברית; תוקן ב-17.1.2025.
- עד גרסה 1.100.0 [שם קובץ](https://github.com/n8n-io/n8n/issues/16218) עם אותיות לא-לטיניות הוחלף בקווים תחתונים בהורדת workflow.
- נושא מייל עברי שנלקח מ-expression בצומת Gmail [יצא משובש](https://github.com/n8n-io/n8n/issues/17514) (גרסה 1.102.4, יולי 2025). הדיווח נסגר אוטומטית בנובמבר 2025 בלי תיקון מאושר, ולכן בודקים נושא עברי כבר בתהליך הראשון.

[[screenshot: עורך n8n עם הערת Sticky ושמות צמתים בעברית, כדי לראות את היישור בפועל | alt: קנבס n8n עם טקסט עברי בהערה ובשמות צמתים]]

## איזה שרת צריך, ומתי עוברים ל-queue mode?

המינימום הרשמי תלוי במה שמריצים. מדריך ה-[Docker Compose](https://docs.n8n.io/deploy/host-n8n/install-options/install-using-docker-compose) דורש 4GB ו-2 vCPU לפחות, בגלל ה-sandbox של n8n Assistant (הרצת קוד שנוצר ב-AI); מדריך ההתקנה על Hetzner אומר שבלעדיו [שרת קטן מסוג CPX11 מספיק לרוב השימושים](https://docs.n8n.io/deploy/host-n8n/install-options/use-a-cloud-provider/deploy-to-hetzner).

[Hostinger מדדה](https://www.hostinger.com/tutorials/n8n-benchmark) n8n על KVM 2 (2 vCPU, 8GB): כ-860MB בסרק, והמליצה על 4GB לפחות ל-10 עד 20 תהליכים. n8n עצמה מציינת [עד 220 הרצות בשנייה](https://docs.n8n.io/hosting/scaling/performance-benchmarking) במופע אחד על 4GB, בתהליך של שני צמתים בלבד. אצלנו מכונה כזו, KVM 2 בפריז, מריצה לשכה שלמה ואת האתרים הציבוריים של החברה.

[Queue mode](https://docs.n8n.io/hosting/scaling/queue-mode/) (מצב תור) מפצל את העבודה: מופע ראשי מקבל טריגרים ו-webhooks, Redis מחזיק את התור, ו-workers (תהליכי הרצה נפרדים) מריצים מול Postgres. כל worker מריץ 10 הרצות במקביל כברירת מחדל, וכל המופעים חייבים אותו מפתח הצפנה.

ברירת המחדל שומרת קבצים בזיכרון, וקבצים גדולים [עלולים להפיל את התהליך](https://docs.n8n.io/hosting/scaling/binary-data/); במופע יחיד מעבירים לדיסק עם `N8N_DEFAULT_BINARY_DATA_MODE=filesystem`. במצב תור אין תמיכה באחסון קבצים בדיסק ועוברים ל-database; אחסון חיצוני ב-S3 הוא פיצ׳ר בתשלום. לפי [תיעוד המהדורות](https://docs.n8n.io/deploy/host-n8n/community-edition-features) queue mode כלול גם ב-Community, ו-multi-main (זמינות גבוהה) בתשלום. Hostinger מצאה ש-queue mode מכפיל בערך את הזיכרון בסרק.

[[diagram: ארכיטקטורת queue mode: מופע ראשי, Redis כתור, כמה workers ומסד Postgres | alt: תרשים של מופע ראשי שמעביר הרצות דרך Redis ל-workers שכותבים ל-Postgres]]

## איך מגבים, מעדכנים ושומרים על האבטחה?

[פקודות ה-CLI](https://docs.n8n.io/deploy/host-n8n/keep-n8n-running/backup-and-restore) מייצאות רק workflows ו-credentials (אישורים). חסרים משתמשים ותפקידים, היסטוריית הרצות, משתנים והגדרות המופע, כולל מפתח ההצפנה. גיבוי מלא כולל את תיקיית `.n8n`, שבה קובץ ה-config עם המפתח, את מסד Postgres ואחסון חיצוני. האישורים נשמרים מוצפנים במפתח הזה, ולכן גיבוי בלעדיו לא ישחזר אותם.

```text
docker exec -u node -it n8n n8n export:workflow --backup --output=backups/latest/workflows/
docker exec -u node -it n8n n8n export:credentials --backup --output=backups/latest/credentials/
```

בלשכה: [[fact: האם הגיבוי המלא של «ניהול נתונים» כולל את מפתח ההצפנה ואת מסד הנתונים של n8n]].

n8n משחררת [גרסת מינור כמעט בכל שבוע וגרסאות תיקון כמעט בכל יום עבודה](https://github.com/n8n-io/n8n/releases). ב[מאגר ה-advisories של GitHub](https://api.github.com/advisories?ecosystem=npm&affects=n8n) רשומות לה 157 הודעות אבטחה שפורסמו ב-2026 עד 19 באוקטובר, 21 מהן ברמה critical. אחת מהן, [Ni8mare](https://github.com/advisories/GHSA-v4pr-fm98-w9pg) (ציון 10.0, ינואר 2026), איפשרה גישה לא מאומתת לקבצים דרך webhook ותוקנה ב-1.121.0.

לכן לא חושפים את העורך לאינטרנט בלי שכבת כניסה, ומעדכנים לפי לוח קבוע. ועוד שני מתגים [מהתיעוד](https://docs.n8n.io/hosting/securing/overview/): `N8N_PUBLIC_API_DISABLED=true` מכבה את ה-API הציבורי, ו-`NODES_EXCLUDE` חוסם צמתים (ברירת המחדל כבר חוסמת את Execute Command).

## מה עושים ב-30 הדקות הראשונות?

1. **חשבון ראשון.** צרו את חשבון ה-owner. בהתקנה חדשה אפשר לבקש [מפתח רישיון חינם](https://docs.n8n.io/deploy/host-n8n/community-edition-features) (Registered Community) שמוסיף תיקיות ו-debug in editor.
2. **שעון.** ברירת המחדל ב-[self-hosting היא America/New_York](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.scheduletrigger/), ובענן GMT. הגדירו `GENERIC_TIMEZONE` ו-`TZ` ל-`Asia/Jerusalem`.
3. **מפתח הצפנה.** הגדירו `N8N_ENCRYPTION_KEY` בעצמכם ושמרו עותק מחוץ לשרת.
4. **תהליך ראשון.** Gmail Trigger, אחריו Extract From File ואז Google Sheets. ב-Schedule Trigger במרווח Weeks בוחרים ימים: ראשון עד חמישי.
5. **התראת כשל.** תהליך נפרד עם [Error Trigger](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.errortrigger/) שמזהיר אתכם, ובהגדרות כל תהליך Error workflow. הוא נדלק רק בכשל של הרצה אוטומטית.
6. **פרסום וגיבוי.** פרסמו (Publish) את התהליך, כי Schedule Trigger לא רץ בלי פרסום, והריצו את הגיבוי הראשון.

:::tip
בלי `GENERIC_TIMEZONE` «כל בוקר ב-8:00» ירוץ בשעון ניו יורק, כלומר ב-15:00 אצלכם.
:::

[[video: youtube | סרטון Quickstart רשמי של ערוץ n8n: בניית workflow ראשון, או חיפוש בערוץ הרשמי youtube.com/c/n8n-io | url: ]]

## מתי Zapier או Make עדיין עדיפים?

- **האפליקציה שאתם צריכים נמצאת רק שם.** הקטלוג של Zapier גדול בהרבה, וב-n8n תצטרכו אז קריאה ידנית ל-API דרך HTTP Request.
- **הנפח נמוך.** 150 חשבוניות בחודש הן 750 משימות: [19.99$ לחודש בחיוב שנתי](https://zapier.com/pricing) ב-Zapier Professional נכון ל-19.10.2026 (כ-62 ₪; Zapier מציגה גם מחירון בשקלים), פחות מ-Starter של n8n (70 ₪). החבילה החינמית כוללת 100 משימות.
- **אין מי שיתחזק שרת.** ב-Zapier וב-Make העדכונים ותיקוני האבטחה הם עניין של הספק; ב-self-hosting הם עליכם, כל חודש.
- **העובדים בונים בעצמם.** [סקירה שעודכנה בפברואר 2026](https://fahimai.com/n8n) מתארת עקומת למידה תלולה מ-Zapier, בערך שבוע עד שמרגישים בנוח. ובמהדורת Community אין שיתוף תהליכים בין עובדים.
- **Make.** Core מתחיל ב-[9$ לחודש בחיוב שנתי](https://www.jetadmin.io/blog/make-pricing/) (כ-28 ₪) ל-10,000 [קרדיטים](https://help.make.com/credits), לפי בדיקה של Jet Admin מ-26.9.2026, והחבילה החינמית נותנת 1,000.

ההשוואה המלאה: [n8n מול Zapier](dgo://comparison/n8n-vs-zapier).

## מהן החלופות: Activepieces, Node-RED ו-Windmill?

- [Activepieces](dgo://project/activepieces): רישיון MIT חוץ מתיקיות ee, שדורשות [תנאי מנוי](https://github.com/activepieces/activepieces); 25,118 כוכבים; מתמקדת בסוכני AI וב-MCP.
- [Node-RED](dgo://project/node-red): Apache-2.0 תחת [OpenJS Foundation](https://nodered.org/about/); 23,762 כוכבים; נולדה ב-IBM ב-2013 ורצה אפילו על Raspberry Pi. מתאימה לאירועים ול-IoT יותר מאשר לתהליכים עסקיים רחבים.
- [Windmill](dgo://project/windmill): AGPLv3 עם קוד קנייני בצד; 18,223 כוכבים; פלטפורמה למפתחים. [גרסת ה-Community](https://github.com/windmill-labs/windmill) אוסרת למכור, לארח כשירות, לשנות או לעטוף בלי הסכם.

הנתונים נכון ל-19.10.2026.

## n8n בתוך הלשכה הדיגיטלית

:::dgo
n8n היא אחת מ-18 אפליקציות של פרויקטים חיצוניים שרצות היום בתוך DGO, ושם היא מנוע האוטומציה של הלשכה. מתקינים אותה ממסך «ניהול אפליקציות» והיא נפתחת בחלון משלה בקונסול; הגיבוי והשחזור נעשים ב«ניהול נתונים». אפליקציה שרצה בלשכה אחת נפתחת כאריח בקונסול של לשכה מקושרת: אצלנו [Plane](dgo://article/plane) רץ על מחשב ה-HP ונפתח מהקונסול של ה-MacBook. [[fact: האם n8n בלשכה עוברת דרך הכניסה האחת של authentik או שנשארת לה התחברות משלה]] ההסתייגות: הרישיון של n8n אינו קוד פתוח, והתוכנית היא להוציא אותה מהליבה ולהציע אותה כתוספת אופציונלית. DGO חינמית, ובינה סולושנס מפתחת אותה.
:::

להתקנה ראשונה: [התקנת DGO עם Claude](dgo://tutorial/install-dgo-with-claude). ועוד תוכנות ישראליות: [המפתח לתוכנות עסקיות בישראל](dgo://directory/israeli-business-software).
