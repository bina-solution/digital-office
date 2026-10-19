# לשכה מרוחקת, אפלקציית רשת, ופיצול האתרים — תוכנית עבודה

**מצב:** תוכנית, **rev 2** (2026-09-29). rev 1 נכתבה 2026-09-25. אין כאן שאלות פתוחות — כל נקודה
שלא נאמרה בידי הבעלים הוכרעה כאן במפורש, עם הנימוק. מה שבאמת דורש הכרעה של הבעלים מרוכז ב־§16.

**מה השתנה ב־rev 2 (אחרי ביקורת ארכיטקטורה):**

| # | התיקון | איפה |
|---|---|---|
| 1 | **אישור הצימוד עבר לשליטת השער.** השער מנפיק את אסימון ההרשמה מאחורי ה־SSO שלו; לשכה מקומית כבר לא מנפיקה לעצמה הרשאה. אפס משטחים לא־מאומתים. | §5, §10 |
| 2 | **בוטל ראוטר ה־catch-all מסוג `HostRegexp`.** במקומו ראוטר `Host()` מדויק לכל צומת, שנכתב ל־file provider, עם priority מפורש ורשימת שמות שמורים נאכפת מכנית. | §3.4 |
| 3 | **הנחות ה־DNS/TLS תוקנו מול בדיקה חיה**: ה־NS הם `sitesdepot.com` (Plesk/InterVision) ולא Cloudflare; ל־`staging.digital-office.co.il` **אין רשומת A**; וה־wildcard של `*.staging` עונה בכל עומק. | §3.3, נספח ב |
| 4 | **בעל אחד לניתוב.** טבלת המסלולים היא האמת; קבצי traefik הם **רינדור** שלה, נכתבים באותה טרנזקציה ובאופן אטומי. | §3.2 |
| 5 | **הוכרע איפה הזהות של הצי** — והיא כבר חיה בפועל על `auth.staging.digital-office.co.il`; authentik מקומי בצומת הוא נפילה בלבד. | §3.5, §16 |
| 6 | **`module.passthrough` עם `mount: root` הוסר** — הוא דורש SSO ומתחבר ל־host של הקונסול, לא לקצה הציבורי. | §4.1 |
| 7 | **תוקנה הטענה על אפליקציות נתיב־שורש**: Plane מנותב לפי hostname ואינו נכנס ל־prefix; הוא מגיע ב־host משלו. | §7.2 |
| 8 | **מיפוי הדרישות לפאזות תוקן** (R7 דורש P4), וה־URL הקנוני הוא `<edge-host>/<node>/…` כברירת מחדל. | §1.1, §7.1 |
| 9 | פורט 8981 (תפוס ע"י `sites-render`) → **8984** ל־`network`, ו־**8987** ל־`site-runtime` (8985 תפוס ע"י `digital-assets`, 8986 ע"י `social-list`); ספירות הממצאים הותאמו לגוף; המסמך הישן מסומן כמוחלף חלקית; נוספו עובדות Lima; ומבחן הקבלה של P2 עבר למסלול האמיתי מק↔VPS. | §4.1, §8.1, §14, נספח א |
| 10 | **ההתקנה של לשכה על מכונה שייכת לאפלקציית `offices` הקיימת** (capability `offices.v1`) — ולכן `remote.py` נמחק מהתוכנית: `network` צורך `offices.create` + `offices.converge` ומוסיף רק אסימון הרשמה, peer, מנהרה ומסלולים. גם "הרכב התקנה" הוא רשימת ה־`apps:` שבהצהרת `offices` — בעל אחד. | §4, §6, §13 |

**מה שהמסמך הזה מחליף:** `NETWORK-APP-AND-NATIVE-SCALING-PLAN.md` (2026-08-11) **מוחלף חלקית** —
החלקים שהוחלפו מסומנים בכותרתו. הניתוח שלו על התעבורה (שבע תקלות מדודות שהכריעו WireGuard על פני
`ssh -R`: 1,334 סבבי ssh ב־10 דקות, split-brain של 6 שעות, worker שצרך אפס משימות בזמן ש־Docker
דיווח `healthy`) **נשאר תקף ואינו מועתק לכאן**. מסמך הביקורת באנגלית:
`digital-office-network-architecture.md`.

---

## 0. שבע הכרעות שכל השאר נגזר מהן

| # | ההכרעה | הנימוק בשורה |
|---|---|---|
| **D1** | **אין מוצר שני בשם `digital-office-server`.** הלשכה עצמה היא המתקין, והשרת המרוחק הוא לשכה מלאה בהרכב אחר. | "פליטה של התקנה" היא בעלים שני לאותו מעמד. התקנה, עדכון, אימות והתקנת אפליקציות כבר קיימים כ־`bbox` + `app-management` + `catalog`, **וההתקנה של לשכה על מכונה היא כבר אפלקציית `offices`** (§6). הכלל: *להצהיר, לא לרשום*. |
| **D2** | **תעבורה: WireGuard בבעלות אפלקציית `network`, עם agent לכל צומת.** | הוכרע ב־2026-08-11 אחרי שבע תקלות. אין סשנים, אין מפּות פורטים, אין "רגל חצי־בנויה". |
| **D3** | **ראוטר `Host()` מדויק לכל צומת, נכתב ל־file provider — ולא catch-all.** אפלקציית `network` היא ה־gateway ה־L7, וטרפיק מעביר אליו. | `HostRegexp` ללא priority היה גובר על `console.staging` ו־`auth.staging` החיים, ו־ACME לא מנפיק תעודה לכלל regexp. ראוטר מדויק = אין גניבת host ואין בעיית תעודה. |
| **D4** | **הכתובת הציבורית דו־מפלסית: `/<node>/` היא דלת ואינדקס, ו־`<node>.<edge-host>` היא ההר עצמו.** | אפליקציה עם נתיבים מוחלטים מהשורש (Plane, n8n) לא עובדת מתחת ל־prefix — זה הבאג הפתוח #8168 וזו הסיבה ש־Plane הוא `embed: false`. |
| **D5** | **הזהות של הצי יושבת ב־edge הציבורי, וכל צומת אחר נופל לזהות המקומית שלו כשה־edge לא זמין.** בפועל זה כבר המצב: `auth.staging.digital-office.co.il` חי ועונה. | המקבוק נסגר בערב; VPS לא. תעבורת אתרים מחוץ ל־SSO לחלוטין. |
| **D6** | **`sites` מתפצל ל־`site-runtime` (מגיש) ול־`sites` (מנהל).** ההגשה לא תלויה במנהל. | מה שהבעלים ביקש, ומה שמאפשר ללשכה אחת לנהל אתרים בכמה מכונות דרך הרשת במקום דרך SSH. |
| **D7** | **הצימוד מאושר בידי השער, מאחורי ה־SSO שלו.** השער מנפיק אסימון הרשמה חד־פעמי; לשכה מקומית לא מנפיקה לעצמה הרשאה. | אחרת כל מי שמריץ לשכה יכול להצטרף לשער ולקבל שם תחת הדומיין. ראו §5. |

---

## 1. הדרישות, והמיפוי לפאזות

| # | הדרישה | הפירוק ההנדסי | פאזה שסוגרת |
|---|---|---|---|
| **R1** | "אם יש שרת מרוחק מחובר במחשבים ויש דומיין שמפנה אליו — זה מתקין שם נתב" | התקנת לשכה בהרכב `network-edge` על הצומת בעל הדומיין | P3 (+P2 למנהרה) |
| **R2** | "`domain/digital-office/connect` שפותח מצלמה ומאפשר לסרוק את הברקוד שמופיע באפליקציה בלשכה" | מסך הצטרפות, מצלמה, `BarcodeDetector`→jsQR, ואסימון שנוצר **מאחורי SSO של השער** | **P1** |
| **R3** | "לקבל חיבור מלא לכתובת `domain/digital-office/macbook1`" | הצומת מאחורי NAT נפתח בכתובת ציבורית בזמן שהוא פתוח | P1+P2 |
| **R4** | "לקוחות יריצו את הלשכה על המחשב האישי שלהם ויחזיקו גם שרת בשביל האתרים" | דייר = לשכת־לקוח + צומת־שרת תחת gateway אחד | P3+P6 |
| **R5** | "פרוייקט שנותן לנו שליטה והתקנת אפליקציות" | `app-management` של הצומת המרוחק, נגיש דרך המנהור. אין מתקין חדש. | P3 (נוחות מלאה ב־P4) |
| **R6** | "להפריד בין אתרים (מגיש) לניהול אתרים (מנהל)" | `site-runtime` + `sites`, הגשה שאינה תלויה במנהל | P5 |
| **R7** | "הלשכה המקומית תקבל גישה ללשכה המרוחקת… וזה יופיע ב־`console.localhost:8080/vps1`" | מודולים פדרטיביים ב־rail: אריחי הצומת המרוחק במקומי | **P4** — לא P1+P2 |
| **R8** | "`staging.digital-office.co.il/macbook1` ינתב אותי ללשכה שרצה כאן במקבוק" | שם הצומת בכתובת; ראו §7.1 ואת מגבלת ה־apex ב־§16 | P1+P2 |

### 1.1 מה כל פאזה סוגרת

```
P1 (זהות + אסימון + מסך הצטרפות) ─┐
P2 (מישור נתונים + gateway)      ├─► R2, R3, R8
P3 (התקנת צומת מרחוק)            ───  R1, R4 (חלקי), R5 (בסיסי)
P4 (פדרציה בקונסול)              ───  R7, ו־R5 בנוחות מלאה
P5 (פיצול האתרים)                ───  R6
P6 (ריבוי דיירים)                ───  R4 בסקייל
```

**R7 אינו נסגר ב־P1+P2.** אריחים של צומת מרוחק בתוך הקונסול המקומי דורשים את `modules.d` ואת
ה־proxy ה־same-origin — כלומר את P4. rev 1 טען אחרת, וזו טעות שתוקנה כאן.

---

## 2. אוצר מילים

| מונח | מה זה | איפה הוא חי |
|---|---|---|
| **צומת (node)** | לשכה אחת על מכונה אחת. | זהות: ULID + Ed25519 (חתימה) + מפתח WireGuard, נשמרים ב־volume של אפלקציית `network`. |
| **edge** | הצומת שמחזיק דומיין ציבורי, TLS ואת מסך ההצטרפות. | `network` + `traefik` באותו צומת. **חייב Linux** (נספח א). |
| **edge host** | שם DNS שמתאר את ה־edge, וכל שם צומת יושב מתחתיו. בפועל `console.staging.digital-office.co.il` (§3.3). | `.env`: `NETWORK_EDGE_HOST`. |
| **דייר (tenant)** | לקוח: צומת־לשכה אחד או יותר + צומת־שרת אחד או יותר. | רשומה אצל ה־gateway. |
| **קישור (link)** | המנהרה בין שני צמתים. | ממשק `dow0` בשני הצדדים + רשומת peer אצל ה־gateway. |
| **אסימון הרשמה (enrollment token)** | הרשאת הצטרפות חד־פעמית ש**השער** מנפיק מאחורי ה־SSO, ומוצגת כ־QR. | נשמר אצל השער (`network_state`), נצרך פעם אחת. |
| **שירות מפורסם** | יחידת HTTP/WS שצומת מציע (הקונסול שלו, אפליקציה, אתר). | קטלוג הצומת, נדחף ל־gateway בחתימה. |
| **מסלול (route)** | "מה מוביל למה": התאמה → יעד + מדיניות (auth, strip, priority). | טבלת המסלולים של ה־gateway (בעל יחיד). |
| **host שמור** | שם DNS שהפלטפורמה מחזיקה ואסור לצומת לתפוס: `console.*`, `auth.*`, כל host שנקמפל, וה־edge host עצמו. | נגזר מכנית מ־`.generated/routing.override.yml` + `.env`. |
| **הרכב (profile)** | אילו אפליקציות מותקנות: `office` / `site-host` / `network-edge`. | ה־`apps:` בהצהרת אפלקציית `offices` — בעל אחד (§6). |

---

## 3. ארכיטקטורה

### 3.1 הצורה הכללית

```
        ┌────────────────────── EDGE / GATEWAY (Linux, IP ציבורי, edge host) ─────────────────────┐
 דפדפן ─┤ traefik ──► network:8984 ──┬─► קונסול ואפליקציות מקומיות (traefik-network)              │
        │   · ראוטר Host() מדויק לכל צומת (נכתב ל־file provider)                                 │
        │   · /digital-office/…  (הצטרפות + אינדקס הצי, מאחורי SSO)                               │
        │   · לוח מסלולים · קטלוג · אסימוני הרשמה                                                 │
        │ authentik (זהות הצי) · connections (מישור האישורים)                                     │
        └───────────────┬──────────────────────────────────────────────────┬──────────────────────┘
                        │ dow0 · WireGuard · keepalive 25s                 │ dow0
              ┌─────────┴──────────┐                            ┌──────────┴───────────┐
              ▼                    ▼                            ▼                      │
   צומת לשכה (מאחורי NAT, מק)      …                  צומת אתרים (VPS של דייר, IP ציבורי)
   traefik · console · bina · site-runtime           traefik (edge משלו + תעודה) · site-runtime · nginx
                        ▲                                          ▲
                        │ נפילה: computers.exec (SSH)              │ overlay: apply / start / logs
                        └──────────── sites (מנהל) ───────────────┘
   תעבורת אתרים (Class B): הדפדפן ──► ה־edge של צומת האתרים (לא דרך ה־gateway)
```

ארבעה מישורים, בעלים אחד לכל אחד:

| מישור | בעלים | מה הוא נותן |
|---|---|---|
| תעבורה | אפלקציית `network` (`dow0`) | קישוריות. אין סשנים ואין מפּות פורטים. |
| בקרה | אפלקציית `network` + מישור האישורים | הצטרפות, ביטול, קטלוג, מצב קישורים. |
| ניתוב | אפלקציית `network` — **בעל יחיד** | מה מוביל למה, בזמן ריצה (§3.2). |
| זהות | authentik של ה־edge, עם נפילה לזהות המקומית | משתמש אחד לצי (§3.5). |

### 3.2 בעל אחד לניתוב (התיקון של ממצא 4)

rev 1 החזיק שני בעלים לאותה עובדה: ראוטר catch-all שנקמפל ב־`reconcile` **וגם** טבלת מסלולים חיה
אצל ה־gateway. שני בעלים = שני מקומות שיכולים לסתור זה את זה, וזו בדיוק המחלה שהפלטפורמה הזו נלחמת
בה בכל מקום אחר.

**הכלל עכשיו:**

```
טבלת המסלולים (SQLite ב־network_state)   ← האמת. בעל יחיד: אפלקציית network.
        │  רינדור פונקציונלי, באותה טרנזקציה, אטומי (temp + rename), עם ולידציה לפני כתיבה
        ▼
network_dynamic/*.yml  (file provider של traefik; volume שנקרא ע"י traefik בלבד)
```

- **המקמפל לא מייצר שום מסלול פדרטיבי.** `reconcile` ממשיך לייצר את הראוטר הפרטי של האפליקציה
  עצמה (`network.localhost` / `NETWORK_BASE_URL`) ואת אריח הקונסול — כמו כל אפליקציה.
- קבצי traefik אינם "בעלים שני": הם **פלט מרונדר**, בדיוק כמו `.generated/` שהוא רינדור של
  `app.json`. הבדיקה שמאכפת זאת: רינדור חוזר של אותה טבלה חייב להיות **זהה בית־לבית**, ואין נתיב
  קוד שכותב ראוטר בלי לכתוב קודם לטבלה.
- **מכשול בטיחות:** כל רינדור נבדק לפני כתיבה (סכימה + רשימת ה־hosts השמורים + פתירות DNS), נשמרת
  Generation קודמת לחזרה אחורה, וקובץ לא־תקין לא נכתב כלל — כלומר traefik ממשיך להחזיק את המצב
  התקין האחרון במקום לאבד את כל הראוטרים.

### 3.3 TLS, DNS וראיות (התיקון של ממצא 3)

**הנחת rev 1** ("wildcard certificate ב־DNS-01 דרך Cloudflare") **הייתה שגויה.** מה שנמדד ב־
2026-09-29 (DoH + `getent` + `curl`; הפלט המלא בנספח ב):

| הטענה ב־rev 1 | מה שנמדד |
|---|---|
| "שרתי השמות ב־Cloudflare" | **לא.** `NS digital-office.co.il` → `ns1.sitesdepot.com`, `ns2.sitesdepot.com`; SOA: `ns1.sitesdepot.com admin.intervision.co.il` (Plesk של InterVision). DNS-01 ב־Cloudflare **אינו זמין** בלי להעביר את הדלגציה. |
| "wildcard ברמה אחת" | `*.staging.digital-office.co.il` קיים, ו**עונה בכל עומק** אצל שרת השמות הזה: `macbook1.staging…`, `plane.macbook1.staging…`, ואפילו `a.b.c.d.e.staging…` — כולם `31.97.196.82`. לעומת זאת `x.digital-office.co.il` → NXDOMAIN, כלומר `*.digital-office.co.il` **לא** קיים, וכלל "wildcard של תווית אחת" שבהערות `.env` נשאר נכון ל־`*.<slug>`. |
| "הדומיין `staging.digital-office.co.il` הוא נקודת הכניסה" | **אין לו רשומת A.** `staging.digital-office.co.il` → תשובה ריקה (NODATA); `curl https://staging…` → `000`. נקודת כניסה חייבת להיות שם שפותר. |
| — | ה־edge החי על `31.97.196.82` **כבר** מגיש `console.staging.digital-office.co.il` (302 → `auth.staging…/application/o/authorize/`) ו־`auth.staging.digital-office.co.il` (302 → זרימת authentik). `edge.staging…` ו־`macbook1.staging…` מחזירים **404 של traefik** (אין ראוטר). |
| — | `31.97.196.82` **כבר בצי המחשבים**: `computer_ssh-b154fa0c` ("שרת פיתוח בינה סלושנס"). |

**ההכרעה שנובעת מזה:**

1. **תעודה לכל host בדיוק, באתגר HTTP-01 רגיל** — לא wildcard, לא DNS-01. כל `<node>.<edge-host>`
   פותר ל־edge ממילא (ה־wildcard), ולכן `myresolver` מנפיק תעודה בלי לגעת ב־DNS.
2. **`NETWORK_EDGE_HOST` חייב להיות שם שפותר.** ברירת המחדל: `console.staging.digital-office.co.il`
   — הצומת החי, היחיד שכבר יש לו תעודה וראוטר. ה־URL המילולי שביקש הבעלים
   (`staging.digital-office.co.il/macbook1`) דורש **רשומת A אחת** ל־`staging` בפאנל Plesk, פעולה של
   הבעלים — ומסמך זה לא מניח אותה. ראו §16 החלטה 3.
3. **בדיקת פתירות בזמן פרסום מסלול.** לפני שהשער מפרסם ראוטר ל־host H, הוא פותר את H ומסרב לפרסם
   אם H לא מצביע לכתובת ה־edge. זה תופס מכנית גם את ה־apex חסר הרשומה, גם דומיין של לקוח בלי
   wildcard, וגם שגיאת הקלדה — במקום תעודה שלא תונפק בשקט.
4. **תעודת wildcard נשארת החלטה פתוחה** (§16 החלטה 2): היא נדרשת רק בסקייל (מכסת Let's Encrypt —
   50 תעודות/שבוע לדומיין), והיא דורשת או העברת דלגציה ל־Cloudflare, או מפתח API ל־Plesk **והוספת
   ה־IP שלנו לרשימת ההיתר** (הפאנל הזה מסרב לפי IP: `403 Access to API is disabled for <ip>` —
   מתועד ב־`apps/domains/AGENT.md`).

### 3.4 ראוטרים: מדויק, עם priority, ורשימת שמות שמורים (התיקון של ממצא 2)

ה־catch-all של rev 1 (`HostRegexp('^[a-z0-9-]+\.<edge-domain>$')`) היה שתי תקלות בבת אחת:

- **הוא היה גובר על ראוטרים חיים.** ב־Traefik v3 אורך הכלל קובע את ה־priority כברירת מחדל, ו־regexp
  ארוך מנצח `Host()` קצר — כלומר `console.staging` ו־`auth.staging` (הקונסול והזהות החיים על
  `31.97.196.82`) היו נבלעים לתוך ה־gateway. זו לא השערה: הם באמת רצים שם, עם ראוטרים משלהם.
- **ACME לא מנפיק תעודה לכלל regexp.** traefik מנפיק ל־`Host()` מדויקים; catch-all מקבל את תעודת
  ברירת המחדל של הקצה — כלומר "עובד" בדפדפן עם אזהרה, וזה בדיוק סוג הכשל שמדווח כהצלחה.

**המנגנון שנבחר:**

```
לכל שירות מפורסם של צומת — ראוטר אחד בקובץ של אותו צומת:
  rule      = Host(`macbook1.<edge-host>`)            # מדויק, אין regexp
  priority  = 10..90                                  # נמוך מ־100 (הקונסול) ומהשמורים
  service   = network:8984                            # ה־gateway מפנה משם ל־dow0
  tls       = true + certresolver=myresolver          # HTTP-01 על ה־host המדויק
```

ומונעים תפיסה של שם של מישהו אחר:

- **רשימת hosts שמורים** נגזרת מכנית מ־`.generated/routing.override.yml` (25 כללי `Host(...)`, עם
  הצבות מ־`.env`) + `AUTH_EXTERNAL_URL` + ה־edge host עצמו. אפלקציית `network` **מסרבת** לרנדר ראוטר
  לשם כזה, עם השם והבעלים שלו בהודעת הסירוב.
- אין צורך בשדה חדש בסכימה. rev 1 הציע `routing[].extra_rules` במקמפל — **ההצעה בוטלה**: כל מה
  שתלוי בקיום צמתים נכתב ל־file provider, ולכן לא נדרש שינוי במקמפל כלל.
- ראוטר שנכשל ב־traefik (למשל rule שגוי) לא מפיל את הקצה: traefik מתעלם מהקובץ הפגום וממשיך עם
  הקונפיג הקודם, ואפלקציית `network` מדווחת על כך במסך.

### 3.5 זהות: איפה היא חיה (התיקון של ממצא 5)

rev 1 סתר את עצמו: התוכנית שמה את authentik הראשי על המקבוק, ומסמך הארכיטקטורה העביר אותו ל־gateway
בלי לומר זאת. **הוכרע מחדש מכמה עובדות:**

- הזהות של הצי חיה **ב־edge**: `auth.staging.digital-office.co.il` כבר חי ועונה, והוא זה שמגן על
  `console.staging…` (302 ל־`application/o/authorize/`). כלומר המצב הזה כבר קיים — rev 1 רק לא הכיר בו.
- המקבוק נסגר בערב; ה־VPS לא. זהות שהמאסטר שלה על מכונה שנסגרת היא זהות שנופלת כל לילה.
- לכן: **מישור זהות אחד — של ה־edge.** authentik מקומי בכל צומת נשאר קיים, אבל תפקידו **נפילה
  בלבד**: כשהקצה לא זמין, המנהל ממשיך להיכנס ללשכה המקומית שלו.

**מאיפה מגיע המשתמש שב־JWT** (הפער שהיה ב־§4.3 של מסמך הארכיטקטורה): מה־authentik של הקצה. המסלול:

1. הדפדפן מקבל session מול `auth.staging…` (כפי שקורה היום).
2. בקונסול המקומי, מסלול פדרטיבי (`/a/<peer>/…`) נאכף ע"י **ה־outpost של הקצה** דרך ה־overlay: traefik
   המקומי משתמש ב־middleware‏ `authentik-fleet@file` שכתובתו `http://<edge-overlay>:9000/...`, ולא
   ב־`authentik@file` המקומי.
3. ה־gateway מנפיק מכאן JWT קצר־טווח, חתום במפתח הצומת שלו, עם `aud`=הצומת ו־`scope`.
4. הצומת המרוחק מאמת מול המפתח הציבורי של העמית ממישור האישורים, ומסרב ל־`X-Authentik-*` מכל מקור
   שאינו ה־overlay **וגם** בלי JWT תקף.
5. תעבורת אתרים (Class B) לא נושאת שום כותרת זהות.

**הקובץ שחסר ב־rev 1 ונוסף לרשימת השינויים ב־§13:**
`platform-base/traefik/config/authentik-forwardauth.yaml` — נוסף לו middleware שני, `authentik-fleet`,
שכתובתו מגיעה מ־env (`BBOX_FLEET_AUTH_URL`). הוא לא נוקב בשם אפליקציה, ולכן G9 (layering) נשאר ירוק.

---

## 4. אפלקציית `network` — מיפוי לפלטפורמה

```
apps/network/
  app.json            manifest — היחיד שהמקמפל קורא
  AGENT.md            ה־brief שנטען לכל סשן סוכן
  app.py              ה־API
  gateway.py          טבלת מסלולים → proxy
  routes.py           רינדור הטבלה לקבצי traefik (בעל יחיד, אטומי, עם Generation)
  tunnel.py           בעלות על dow0 (kernel / wireguard-go)
  catalog.py          קטלוג שירותים + מודולים פדרטיביים
  enroll.py           אסימוני הרשמה (השער מנפיק) + אימות הצטרפות
  # התקנה/שדרוג/תיקון של לשכה על מכונה — של אפלקציית `offices` (offices.v1). אין כאן מתקין שני.
  store.py            SQLite ב־/data
  static/enroll/      מסך ההצטרפות — מצלמה + QR, בלי CDN ובלי תלות חוץ
  Dockerfile · docker-compose.yml
```

### 4.1 הצהרות ב־`app.json` (התיקונים של ממצאים 1 ו־6)

| שדה | הצהרה | הערה |
|---|---|---|
| `capabilities` | `network` / `network.v1` על **`http://network:8984`** | **8981 תפוס ע"י `sites-render`** (מתועד ב־`apps/sites/docker-compose.yml`); rev 1 הקצה אותו בטעות. |
| `use` | **`offices` (requires, after)** — מי שמתקין ומתקן לשכה על מכונה; `computers` (requires, after), `secrets` (requires, after), `identity` (requires, after), `domains` (wants), `notify` (wants), `ui-kit` (wants) | |
| `connections` | אין סודות סטטיים; במקומם `contributes.connection_providers` עם פרוטוקול חדש `digital_office_node` | §4.2 |
| `data.volumes` | `network_state` (`on_uninstall: keep`) | הזהות היא מה שמחזיק את הצומת בצי |
| `contributes.volumes` | `{ traefik: ["network_dynamic:/etc/traefik/dynamic"] }` | traefik כבר מחזיק `--providers.file.directory=/etc/traefik` וקורא רקורסיבית; הכתיבה היא ל־volume **שלנו** |
| `routing` | `host: network`, `auth: sso`, `module: {embed: true, alias: network}` | **אין `passthrough` ואין `mount: root`.** ראו למטה. |

**למה הוסר `module.passthrough` עם `mount: root`** (ממצא 6): המנגנון דורש `auth: sso`
(`reconcile.py:794` מסרב אחרת) **ומתחבר ל־host של הקונסול** — לא לקצה הציבורי. שני תנאים שהופכים
אותו לבלתי־מתאים למסך הצטרפות: (א) אם הוא SSO — הוא לא יכול לשמש להצטרפות ראשונה של צומת שאינו
מחובר; (ב) אם הוא לא SSO — המקמפל מסרב. בנוסף, הצומת החשוף צריך לחיות על `NETWORK_EDGE_HOST`, לא על
host הקונסול. לכן: **כל ראוטר ציבורי של האפליקציה נכתב ל־file provider** (בעל יחיד, §3.2), והמקמפל
מטפל רק באריח.

### 4.2 כל צומת = instance במישור האישורים

```
protocol: digital_office_node
secret:   { node_name, tenant, signing_pubkey, wg_pubkey, overlay_ip, edge_endpoint,
            scope: ["console","apps","sites"], enrolled_at, enrollment_token_id }
```

המפתח **הפרטי** של הצומת המרוחק לא נמצא כאן — רק החצי הציבורי. אותו דפוס של `computer_ssh`.

---

## 5. ההצטרפות (התיקון של ממצא 1)

### 5.1 מה היה שבור ב־rev 1

rev 1 נתן ללשכה המקומית להנפיק ולחתום לעצמה את כרטיס ההצטרפות, ואת `/connect` ואת "האישור" השאיר
לא־מאומתים. המשמעות בפועל: **כל מי שמריץ לשכה יכול היה להצטרף לשער, לקבוע לעצמו שם, ולקבל
`<name>.digital-office.co.il`** — בלי שום הרשאה בצד השער. זה גם נוגד את מודל ההרשאות של הפלטפורמה,
שבו כל פעולה בעלת השלכה על הצי עוברת דרך מישור האישורים.

**ההכרעה (D7): ההרשאה נוצרת בצד השער, מאחורי ה־SSO שלו.** הלשכה המקומית מוכיחה שהבעלים שלח אותה;
היא לא מחליטה שהיא מורשית.

### 5.2 הזרימה הקנונית — השער מנפיק, הצומת סורק

```
[שער · דפדפן של הבעלים, אחרי SSO על auth.staging…]
  1. authorize  https://<edge-host>/digital-office/nodes/new   (auth: sso)
                בחירה: דייר, שם צומת, scope  →  השער מנפיק enrollment_token
                {id, node_name, tenant, scope, expires 15 דק', single-use}
  2. display    השער מציג QR + קוד בן 8 תווים

[צומת הלשכה · מסך "רשת > הצטרף לשער"]
  3. scan       המצלמה של הצומת קוראת את ה־QR של השער (או הקלדת הקוד)
  4. keygen     הצומת מייצר מקומית זוג Ed25519 + זוג WireGuard
  5. post       POST /api/enroll {token, node_name, signing_pub, wg_pub, endpoint}
                ← האסימון הוא ההרשאה; אין כאן שום בקשה אנונימית שימושית
  6. verify     השער מאמת: חתימה, תפוגה, חד־פעמיות, גבול הדייר, ורשימת ה־hosts השמורים
  7. assign     מקצה 10.79.<gateway_slot>.<n>; רושם instance במישור האישורים
  8. respond    באותה תשובה: {edge_pubkey, endpoint, assigned_ip, scope, overlay_cidr, mtu}
                ← אין polling ואין צורך בנגישות נכנסת אל הצומת
  9. up         הצומת מכוונן peer, מרים dow0, keepalive=25
 10. active     handshake ראשון → השער מפרסם ראוטרים + רשומת modules
                (ואם אין handshake תוך 60 שנ' → degraded, והמסך אומר בדיוק מה לא קרה)
```

ההיפוך משיג שלושה דברים בבת אחת: ההרשאה נקבעת אצל מי שמחזיק בשם הציבורי; **אפס משטחים לא־מאומתים**
(נקודת הקצה היחידה בלי SSO היא ה־POST של ההרשמה, וחסרת תועלת בלי אסימון); ואין צורך ב־polling —
התשובה חוזרת על הבקשה של הצומת עצמו.

### 5.3 הווריאנט שהבעלים תיאר — נשמר, עם אישור מאומת

הכיוון המקורי (הלשכה מציגה QR, `/digital-office/connect` פותח מצלמה) **נשמר כאפשרות שנייה**, כי הוא
נוח: הלשכה מציגה אסימון קצר־מועד ומי שסורק הוא הטלפון. אבל שם **האישור** — הרגע שבו נוצר ה־instance —
דורש session של בעל הבית בשער: `POST /api/pair/approve` מפנה ל־SSO של השער, ובשבילו זה קליק אחד (הוא
כבר מחובר). סריקה לבדה **לעולם** לא רושמת צומת.

**מה שנשאר לא־מאומת בשני הווריאנטים:** מסך סטטי בלבד — קורא QR ומציג "ממתין לאישור". אין בו קריאת
קטלוג, אין בו ניהול, ואין בו מידע על צמתים אחרים.

### 5.4 מצבים ואבטחה

`pending → claimed → approved → active | degraded | offline | revoked | expired`

| מצב | מה המשתמש רואה | מה זה אומר |
|---|---|---|
| `active` | "מחובר" + rtt ו־rx/tx | handshake טרי **וגם** קטלוג השירותים נקרא |
| `degraded` | "מחובר אבל לא מגיב" | handshake טרי, הקטלוג לא נענה → לא מנתבים לשם |
| `offline` | "הלשכה הזו סגורה כרגע" (עמוד, לא 502) | אין handshake מ־3× keepalive |
| `revoked` | "החיבור בוטל" + מונה בתים קפוא | הרשומה הוסרה בשני הצדדים |

- אסימון: חד־פעמי, 15 דק', `consumed_at` נרשם, וצריכה שנייה נדחית **ונרשמת כאזהרה**.
- `scope` הוא default-deny.
- הגבלת קצב לכל IP ולכל אסימון; אימות חתימה בזמן קבוע; הודעת "אסימון לא מוכר" והודעת "אסימון שפג"
  זהות, כדי שלא יהיה oracle.
- השער מסרב לאסימון של דייר אחר.

---

## 6. התקנה ואימות של צומת מרוחק

### 6.1 הרכבים

| הרכב | מה מותקן | למי | טביעת רגל |
|---|---|---|---|
| `office` | ברירת המחדל הנוכחית | המחשב האישי | ~5 GiB |
| `network-edge` | traefik · network · authentik · connections · console · app-management | ה־VPS שמוביל את הדומיין | ~1.2 GiB |
| `site-host` | traefik · **site-runtime** · network · app-management | VPS של לקוח | ~0.4 GiB |

**המנגנון — והוא כבר קיים:** רשימת האפליקציות של צומת היא **`apps:` בהצהרת `offices`**, וההתקנה עצמה
היא `offices.converge`. אין כאן מנגנון הרכבים שני ואין `remote.py`: `network` מצהיר `use: offices`,
קורא `create` (הצהרה) ו־`converge` (התקנה/שדרוג/תיקון — אותה פעולה), ומוסיף רק את מה ש־`offices` לא
עושה: אסימון הרשמה, peer, `dow0`, מסלולים ורשומות `modules`. ההצהרה נכתבת פעם אחת ל־
`platform.state.yaml` של הצומת (הדפוס של `indox.bootstrap_seed`), ומכאן והלאה `platform.state.yaml`
הוא הבעלים היחיד.

### 6.2 הזרימה ושלוש המלכודות

```
# ההתקנה עצמה — offices (הבעל), לא network
POST http://offices:8983/api/offices                     {"id":"vps1","machine":"...","domain":"...",
                                                          "path":"/root/deployment-hacohen",
                                                          "source":{"repo":"...","ref":"<commit>"},
                                                          "apps":["traefik","network","site-runtime",
                                                                  "app-management"]}
POST http://offices:8983/api/offices/vps1/converge       # התקנה = שדרוג = תיקון, אותה פעולה
```

1. **preflight** בצעדי `converge`: `dns` (‏`console.<domain>` ו־`auth.<domain>` מצביעים למכונה), docker
   **28.5.2** (29 עולה, מדווח healthy, ומגלה אפס ראוטרים), פורטים 80/443, מקום, RAM. **סירוב קורה
   כאן**, לפני שינוי.
2. **code** — `git clone/fetch` + `checkout --detach <commit>`; הטוקן עובר כ־`http.extraHeader`
   חד־פעמי ולא נכתב ל־`.git/config`. ה־commit חייב להיות **דחוף** — `home.pushed` אומר אם הוא.
3. **engine · env · state · run** — Docker מוצמד (28.5.2); `.env` חדש נוצר מ־`scripts/ci-env.sh`,
   ו־`.env` קיים **רק מורחב** (הסודות שלו לא מתחדשים; `.env` שדומיין שלו שונה מההצהרה נדחה);
   `set-state` לכל אפליקציה; ואז `./bbox run` מנותק על המכונה, ששורד ניתוק SSH.
4. **הצטרפות** — אחרי שהצומת converged, השער מנפיק אסימון (§5.2) והצומת צורך אותו דרך
   `computers.exec`; כאן אין צורך במצלמה. הצטרפות שלא הושלמה לא משאירה צומת חצי־רשום: הרשומה נוצרת
   רק אחרי handshake. **ההתקנה וההצטרפות נפרדות בכוונה** — אפשר להתקין בלי להצטרף, ולהצטרף בלי
   להתקין מחדש.
5. **אימות** — צ'קליסט עם ראיות: קונטיינרים, `/healthz`, ה־commit שרץ מול ה־ref, תוקף תעודה,
   התאמת DNS, מקום פנוי — **ויכולת, לא תהליך**.

**מלכודת 1 — `exec` נגמר אחרי 600 שניות** (`apps/computers`: `MAX_TIMEOUT = 600`) ובנייה ראשונה
אורכת 10–15 דקות ⇒ ההתקנה חייבת להיות job מנותק
(`nohup ./bbox run >/var/log/dobox-install.log 2>&1 &`) עם polling. הדפוס כבר קיים:
`apps/domains/webengine.py` (`submit(client=…)` = טוקן אידמפוטנטיות, שורה = חוזה ה־API, SSE להתקדמות).
**מלכודת 2 — התקנה כפולה** ⇒ ה־API הוא `ensure`: מזהה התקנה קיימת לפי `.generated/` + ref ומדווח
"כבר מותקן" עם ה־commit שרץ.
**מלכודת 3 — לדווח "מותקן" בלי ראיה** ⇒ כל תשובה נושאת exit code, stderr ותוצאות בדיקה.

---

## 7. הכתובות

### 7.1 הטבלה (התיקונים של ממצאים 7 ו־8)

| כתובת | מה זה | מימוש |
|---|---|---|
| `https://<edge-host>/digital-office/nodes/new` | הנפקת אסימון הרשמה — **מאחורי SSO** | file provider, `auth: sso` |
| `https://<edge-host>/digital-office/connect` | סורק QR (מסך סטטי, הווריאנט של §5.3) | file provider, סטטי |
| `https://<edge-host>/digital-office/` | אינדקס הצי | file provider, `auth: sso` |
| `https://<edge-host>/<node>/…` | הקונסול של הצומת (דלת + prefix) | ראוטר `Host()` + gateway; דורש `subpath` |
| `https://<node>.<edge-host>/` | **ההר הרציני** — נתיב שורש, אפס rewriting | ראוטר `Host()` מדויק + HTTP-01 |
| `https://<node>.<edge-host>/a/<alias>/` | אפליקציה שהצהירה `subpath: true` | אותו ראוטר |
| `https://plane.<node>.<edge-host>/` | אפליקציית נתיב־שורש (Plane) — **host משלה** | ראוטר `Host()` מדויק (§7.2) |
| `http://console.localhost:8080/vps1/` | הצומת המרוחק בקונסול המקומי (302 → `/a/vps1/`) | **P4** |
| `http://console.localhost:8080/a/network/` | מסך הרשת | אריח רגיל |

**הצורה הקנונית:** `<edge-host>/<node>/…` — כלומר **בדיוק מה שהבעלים ביקש**, כשה־`NETWORK_PUBLIC_PREFIX`
ריק (`""`) ו־`NETWORK_URL_SHAPE=node` (ברירת המחדל לצומת עם דייר אחד). rev 1 החליף בשקט ל־
`/digital-office/<tenant>/<node>/`; זה מצב **אופציונלי** (`NETWORK_URL_SHAPE=tenant-node`) שנדרש רק
כששער אחד משרת כמה דיירים. ה־URL המילולי `staging.digital-office.co.il/macbook1` דורש גם את רשומת
ה־A החסרה (§3.3) — ראו §16 החלטה 3.

### 7.2 למה דו־מפלסי, ואיפה Plane (התיקון של ממצא 7)

rev 1 טען ש"`<node>.<edge-domain>/a/<alias>/` מגיע לכל אפליקציה, כולל Plane". **זו טענה שגויה:**
`apps/project-pln/app.json` מנותב לפי **hostname** (`"host": "plane"`, נתיבי שורש, `auth: "none"`,
`embed: false`), כלומר Plane **לא** נכנס ל־prefix של הקונסול, וכל ניסיון להציג אותו ב־`/a/<alias>/`
נכשל — זה בדיוק הכשל המתועד ב־`AGENTS.md` ("Do not try `/a/plane/`; upstream bug #8168"). הטענה
השגויה השנייה שנבעה ממנה: "wildcard של תווית אחת" — נכון ל־`*.<slug>` ולא לתת־העץ של `staging`
(§3.3).

**הכלל המתוקן, לפי הצהרה:**

| סוג אפליקציה | איך מגיעים אליה בצומת |
|---|---|
| `subpath: true` (הקונסול שלנו, `bina`, `sites`, `drive`, `mail`) | גם ב־`<node>.<edge-host>/a/<alias>/`, וגם בדלת ה־prefix |
| נתיב־שורש (`project-pln`, `n8n`, `supabase`) | **host משלה**: `plane.<node>.<edge-host>` — ומתאים ל־`auth: none`/`embed: false` שכבר מוצהרים בה |
| כל השאר | כפתור "נפתח בכתובת משלו" במקום מסך שבור |

`plane.macbook1.staging.digital-office.co.il` **פותר היום** (נמדד, §3.3) — ולכן host שכזה ניתן לפרסום
עם תעודה ב־HTTP-01. אבל זו התנהגות של שרת השמות **הזה**, ואין להכליל אותה לדומיין של לקוח. לכן בדיקת
הפתירות של §3.3 היא חלק מהפרסום עצמו: אם ה־host לא פותר ל־edge — לא מפרסמים ראוטר.

### 7.3 `/vps1` בתוך הקונסול המקומי — P4

1. **אריחים ב־rail (הדרך הטובה).** הקונסול מושך מ־`network` את הקטלוג הפדרטיבי ומצייר את אריחי
   הצומת בקבוצה בשם הצומת. לחיצה = `/a/<peer>-<alias>/` באותו origin דרך ה־gateway, בלי התחברות שנייה.
   **כאן מתאחדים "ניהול האתרים" המקומי ו"אתרים" של הצומת המרוחק**: שני אריחים, שני צמתים, rail אחד.
2. **`/<peer>/` = הקונסול המלא של הצומת, ממוסגר** (302 ל־`/a/<peer>/`). דורש prefix בקונסול (ממצא F-03
   במסמך הביקורת) ולכן דורש את ה־enumerator לפני שהוא נוגע בקוד.
3. **קישור יוצא** ל־`<node>.<edge-host>/` כפתרון אחרון.

**מרחב שמות:** נתיבי צמתים חיים תחת `/a/<peer>/`; `/<peer>/` בראש הקונסול הוא **הפניה בלבד**,
נבדקת מכנית מול `reserved_paths` ונרשמת ב־`.generated/`.

---

## 8. פיצול `sites` — מגיש ומנהל

### 8.1 מה זז לאן

| רכיב ב־`apps/sites` היום | אחרי הפיצול | למה |
|---|---|---|
| `runtime.py` (render + deploy + start/stop/reload) | **`apps/site-runtime`** (פורט **8987**) | זה מה שנוגע במכונה; חייב לרוץ **על** המכונה |
| `checks/` + `render_server.py` | נשאר ב־`sites` | סריקה כבדה היא פעולת ניהול |
| `scheduler.py` | בשניהם: ה־runtime אוסף, המנהל מציג | הגשה ממשיכה כשהמנהל למטה |
| `store.py` + UI + API | **`sites`** (המנהל), כותרת "ניהול אתרים" | ניהול |
| `machines.py` | בשניהם; המנהל מעדיף overlay, ה־runtime תמיד מקומי | §8.3 |

### 8.2 החוזה

```
site-runtime · capability site-runtime, interface site-runtime.v1, endpoint http://site-runtime:8987
required_ops: apply, start, stop, reload, logs, probe, listLocal
```

- `apply` מקבל **את הקבצים המרונדרים**, לא "בקשה": הזכות להחליט מה נכתב נשארת במנהל, הזכות להריץ
  נשארת במגיש.
- ה־runtime לא מחזיק רשימת אתרים של הכלל, מפרסם `/healthz` **ו־`/readyz`**, ומדווח מה הוא מריץ.
- **לפני המעבר — ספירת קוראים מכנית** (AGENTS.md §8): לתעד כמה קבצים נסרקו ולא רק כמה ממצאים נמצאו,
  להוכיח שהשער מייצר ממצאים על הקוד **לפני** השינוי ואפס אחריו, ואז להעביר. אין לסמוך על `grep`.

### 8.3 מה זה פותח

היום `apps/sites/machines.py` עובד דרך `computers` ב־SSH: כדי לנהל אתר בשרת צריך להפקיד מפתח SSH.
**לקוח לא יעשה את זה.** אחרי הפיצול מכונה עם `site-runtime` ו־`network` נדרשת בהצטרפות (QR), והמנהל
מדבר עם ה־runtime דרך ה־overlay:

```
office (sites, מנהל) ──overlay──► vps1 · site-runtime ──► site-2 (nginx)
        └── נפילה: computers.exec (SSH) למכונה שאין עליה runtime ──┘
```

**ואף אתר לא נופל במעבר:** `sites` כבר תומך ב־`source: adopted` — אתר שהתחיל מחוץ לנו נסרק ומנוטר
וההתקנה שלו לא נגעת. לכן הנתיב לשני האתרים הקיימים: הצטרפות־צומת → adopted → (כשרוצים) "העבר לדפוס
הקבוע". אפס downtime, ואף שלב לא מחייב את הבא.

---

## 9. מודל נתונים (`network_state`)

```
Tenant       id, name, edge_host, parent_domain, created_at
Node         id, tenant_id, name, role: office|server|edge,
             signing_pub, wg_pub, overlay_ip, endpoint, version, commit,
             scope[], state, last_handshake_at, rtt_ms, created_at
Service      id, node_id, name, kind: http|tcp, port, ws, subpath, health_path, last_seen_at
Route        id, tenant_id, node_id|null, match{host, path_prefix},
             target{service, strip_prefix, rewrite_host}, auth: sso|peer|none,
             priority, enabled, source: user|derived, updated_by, updated_at
Token        id, tenant_id, node_name, scope[], issued_by, issued_at, expires_at,
             consumed_at, state
ReservedHost host, owner, source: compiled|env|edge, updated_at
InstallJob   id, machine_id, profile, ref, state, log_tail, evidence{}, started_at, ended_at
```

שלוש הערות שהן החלטות:

- **`Route.target` הוא שירות, לא כתובת.** כתובת ה־overlay מוקצית מחדש; מסלול שמחזיק IP נשבר בשקט.
- **אין טבלת מפתחות.** כל סוד בצי במישור האישורים; כאן רק חצאים ציבוריים.
- **`ReservedHost` הוא טבלה ולא רשימה בקוד** — היא נבנית מחדש בכל קומפילציה מקבצי הניתוב המרונדרים,
  כדי ש"אסור לתפוס את `console.staging`" לא יהיה ידע שאף אחד לא מעדכן.

---

## 10. API

```
# מאחורי SSO של השער
POST /digital-office/nodes/new                   → enrollment_token + qr_svg + short_code
GET  /api/nodes | /api/nodes/<id> | /api/links
GET  /api/routes | POST /api/routes | DELETE /api/routes/<id>
GET  /api/catalog
POST /api/nodes/install {machine_id, profile, ref, domain}   → job
GET  /api/nodes/install/<job>                    → state, log_tail, evidence
POST /api/nodes/<id>/verify                      → צ'קליסט עם ראיות
POST /api/nodes/<id>/revoke                      → עצירת תעבורה + הוכחה

# חסר תועלת בלי אסימון (היחיד שאינו דורש session)
POST /api/enroll          {token, node_name, signing_pub, wg_pub, endpoint}
                          → {edge_pubkey, endpoint, assigned_ip, scope, overlay_cidr, mtu}

# אופס קנוניים (platform-service.v1)
POST /listNodes /getNode /createEnrollment /enroll /revokeNode
POST /listRoutes /writeRoute /deleteRoute /installNode /verifyNode /listLinks /catalog
```

---

## 11. כשלים — הטבלה שהתוכנית נשפטת לפיה

| # | המצב | מה קורה | מה מונע אותו |
|---|---|---|---|
| F1 | שני הצדדים מאחורי NAT | WireGuard ישיר לא יעלה | **דרישת סף**: לצי חייב להיות edge עם IP ציבורי (זה ה־VPS) |
| F2 | UDP חסום | המנהרה לא עולה | TCP fallback מסומן ב־UI כ**מושפל**, לא כשקוף |
| F3 | MTU / black hole | קטן עובד, העלאה נתקעת | `MTU 1420` + בדיקת payload בהצטרפות, MTU נשמר לכל peer |
| F4 | ה־edge סגור | אתרי הלקוח ממשיכים; הלשכה המרוחקת נשארת בזהות המקומית | אתרים מחוץ ל־SSO; ה־runtime לא תלוי במנהל |
| F5 | צומת נעלם בלי FIN | אין סשן חצי־פתוח לתקוע | Keepalive 25 שנ' וסף 3× |
| F6 | שני צמתים טוענים לאותו host | נדחה בזמן כתיבת המסלול, עם שני השמות | ולידציה ב־`writeRoute` + `ReservedHost` |
| F7 | אסימון שדלף | תפוגה 15 דק' + חד־פעמי; צריכה שנייה נרשמת כאזהרה | `Token` + `consumed_at` |
| F8 | שעון לא מסונכרן | תפוגות מתנהגות אקראית | NTP + skew מדוד לכל peer |
| F9 | כמסת תעודות | הנפקה נכשלת כשמצטרף צומת | HTTP-01 לכל host מדויק; wildcard ב־DNS-01 כשמחליטים (§16) |
| F10 | התקנה שנקטעת | `.generated/` חלקי | API אידמפוטנטי + verify לכל שלב בנפרד |
| F11 | דיסק מלא ב־VPS | כשל שנראה כמו באג רשת | preflight + ניטור ב־verify |
| F12 | Docker 29 | traefik עולה, healthy, אפס ראוטרים | preflight נועל 28.x ומסרב |
| F13 | host שלא פותר (למשל ה־apex `staging`) | תעודה לא תונפק בשקט, והמשתמש מקבל שגיאת TLS | **בדיקת פתירות לפני פרסום ראוטר** (§3.3) |
| F14 | ראוטר שגוי שנכתב ל־file provider | עלול להפיל ניתוב בקצה | ולידציה לפני כתיבה + Generation אחורה + traefik מתעלם מקובץ פגום |

---

## 12. ריבוי לקוחות

```
Tenant: shlomo      office: macbook1   server: vps1        → console.staging.digital-office.co.il
Tenant: customer-a  office: a-laptop   server: a-vps       → a.digital-office.co.il
Tenant: customer-b  office: (אין)      server: shared-vps  → b.digital-office.co.il
```

1. **בידוד שמות** — כל צומת מנוסח בשם הדייר שלו; אותה ולידציית התנגשות של `validate`.
2. **ה־edge לא מחזיק מפתחות של לקוחות** — רק חצאים ציבוריים; הסודות במישור האישורים של הצומת.
3. **שני מודלים**: VPS לכל לקוח (`site-host`, ~0.4 GiB, בידוד מלא) — ברירת מחדל; אחסון משותף על
   ה־VPS שלי (כל אתר פרויקט compose נפרד, מה ש־`sites` כבר עושה) — למי שלא רוצה שרת. שיתוף מלא של
   לשכה אחת בין לקוחות **אינו** מוצע.

---

## 13. מה משתנה בקוד הזה

| קובץ/תיקייה | שינוי | סוג |
|---|---|---|
| `apps/network/` | חדש: app.json · AGENT.md · app.py · gateway.py · routes.py · tunnel.py · catalog.py · enroll.py · store.py · static/enroll/ · Dockerfile · docker-compose.yml (**אין `remote.py`** — ההתקנה של `offices`) | חדש |
| `apps/site-runtime/` | חדש: app.json · AGENT.md · app.py · runtime.py (מועבר) · compose | חדש + העברה |
| `apps/sites/` | מסיר את שכבת ההרצה, שומר store/UI/checks, מוסיף קריאה ל־`site-runtime`, כותרת "ניהול אתרים" | שינוי |
| `platform-base/traefik/config/authentik-forwardauth.yaml` | **נוסף middleware שני**, `authentik-fleet`, שכתובתו מ־env (`BBOX_FLEET_AUTH_URL`) — זהות הצי למסלולים פדרטיביים. **היה חסר ב־rev 1** | שינוי (platform-base, בלי שם אפליקציה ⇒ G9 ירוק) |
| `platform-base/traefik/docker-compose.yml` | volume ל־`/etc/traefik/dynamic` (מוצהר ע"י `network` דרך `contributes.volumes`) | שינוי קטן |
| `platform-base/console/` | תמיכת prefix עצמית (`X-Forwarded-Prefix`) + מקור מודולים שני מ־`modules.d/` | שינוי |
| `platform/manager/reconcile.py` | **אין שינוי מנגנון.** rev 1 הציע `routing[].extra_rules` — ההצעה בוטלה (§3.4) | — |
| `apps/offices/` (**קיים**) | הבעלים של התקנה/שדרוג/תיקון של לשכה על מכונה. `network` צורך אותו (`use: offices`), ורשימת האפליקציות של צומת היא ה־`apps:` בהצהרה | אין שינוי — שימוש |
| `.env.ex` | `NETWORK_EDGE_HOST`, `NETWORK_TENANT`, `NETWORK_PUBLIC_PREFIX`, `NETWORK_URL_SHAPE`, `NETWORK_OVERLAY_CIDR`, `BBOX_FLEET_AUTH_URL` | קונפיג |
| `scripts/refactor/` | שער חדש: (א) כל host ציבורי מוצהר בצומת אחד; (ב) רשימת ה־hosts השמורים נגזרת מכנית; (ג) רינדור המסלולים אידמפוטנטי | שער |

**שערים בסוף כל פאזה:** `ownership-lint` (G5) · `layering-lint` (G9) · `compose-invocation-lint` (G7) ·
`healthcheck-lint` (G18) · `image-pin-lint` (G15) · `memory-budget-lint` (G30) · `fresh-machine-check.sh`.

---

## 14. פאזות — ומה מוכיח כל אחת

| פאזה | מה נבנה | איך מוכיחים | גודל |
|---|---|---|---|
| **P0 — הקפאת חוזים** | מסמכים אלה + נעילת D1–D7 | סקירה; אין קוד | S |
| **P1 — זהות, אסימון, מסך הצטרפות** | אפלקציית `network` + אסימוני הרשמה + מצלמה + instance במישור האישורים | אסימון שנוצר מאחורי SSO; אסימון שנצרך פעמיים נדחה; בקשה בלי אסימון נדחית; אסימון מדייר אחר נדחה | M |
| **P2 — מישור נתונים** | `dow0` (kernel + userspace), gateway, ראוטרים מדויקים, בדיקת פתירות | **על המסלול האמיתי: המקבוק ↔ `31.97.196.82`.** ראיות: handshake, rtt, GET פדרטיבי של קונסול המקבוק מהשרת, בדיקת payload של 10 MB אחרי כיוון MTU, וסבב עם UDP חסום שמוכיח את ה־fallback. הסים המקומי הוא בדיקת קדם מהירה בלבד, **לא** הקבלה | L |
| **P3 — הצטרפות של צומת מרוחק** | `use: offices`; מסך שמפעיל `create` + `converge`, ואז אסימון ההרשמה; verify עם ראיות | הצהרה + converge על VPS נקי → לשכה עולה (`home.pushed` אמת); converge שני מדווח "כבר מותקן"; preflight מסרב ל־Docker 29; אחריו הצומת `active` | M |
| **P4 — פדרציה בקונסול** | `modules.d`, אריחי צומת ב־rail, `/a/<peer>/`, `/vps1`, JWT | לחיצה על אריח מרוחק נפתחת בלי התחברות שנייה, כולל WS; revoke מסיר את האריחים | L |
| **P5 — פיצול האתרים** | `site-runtime`, המנהל דרך ה־overlay, מעבר adopted | שני האתרים ממשיכים לשרת לאורך כל המעבר; כיבוי המאסטר לא מפסיק הגשה | M |
| **P6 — ריבוי דיירים** | דיירים, ניפוק שמות, החלטת התעודות מ־§16 | דייר שני מצטרף בכתובת משלו בלי לגעת בראשון | M |

**R2/R3/R8 נסגרים ב־P1+P2. R1 ו־R5 ב־P3. R7 ב־P4. R6 ב־P5. R4 ב־P3+P6.**

---

## 15. מה במפורש לא עושים

- לא כותבים מתקין חדש — `bbox` + `app-management` + `catalog` הם המתקין.
- לא מנתבים subnet גולמי לתוך netns של traefik — ה־gateway מפנה.
- לא ממציאים מישור הרשאות שני. זהות = authentik; סודות = connections.
- לא מנסים להציג אפליקציית נתיב־שורש בתוך prefix — נותנים לה host.
- לא שומרים IP של צומת בתוך מסלול.
- לא מפדרים את n8n כתהליך אחד על שני צמתים (מזהים מתפצלים — מסמך 2026-08-11).
- **לא משתמשים ב־`HostRegexp` catch-all** ולא נוגעים ב־`extra_rules` של המקמפל.

---

## 16. החלטות פתוחות לבעלים (מה שלא הוכרע כאן, ולמה)

אלה שש ההכרעות שאינן שלי. לכל אחת: האפשרויות, הראיה הקיימת, ומה היא חוסמת.

| # | ההכרעה | האפשרויות | הראיה / המלצה | מה היא חוסמת |
|---|---|---|---|---|
| **1** | **איפה הזהות של הצי** | (א) ב־edge — `auth.staging.digital-office.co.il`; (ב) על המקבוק | (א) **כבר המצב בפועל**: `console.staging…` מפנה אליו ב־302. המקבוק נסגר בערב ⇒ (א) מומלץ | כלום — ההמלצה משמרת את המצב הקיים |
| **2** | **DNS ותעודות** | (א) HTTP-01 לכל host (עובד היום); (ב) wildcard ב־DNS-01 — דורש העברת דלגציה ל־Cloudflare **או** מפתח API ל־Plesk + הוספת ה־IP שלנו לרשימת ההיתר | ה־NS הם `sitesdepot.com`; ה־API של Plesk מסרב לפי IP (`403 Access to API is disabled for <ip>`). (א) מספיק עד ~50 צמתים/שבוע; (ב) נדרש בסקייל | P6 (ריבוי דיירים גדול) בלבד |
| **3** | **ה־URL הקנוני** | (א) `<edge-host>/<node>/…` (מה שביקשת); (ב) `staging.digital-office.co.il/<node>/…` — דורש **רשומת A אחת** ל־`staging` בפאנל Plesk; (ג) `/digital-office/<tenant>/<node>/…` לריבוי דיירים | ל־`staging` אין רשומת A ⇒ (א) עובד מיד עם `NETWORK_EDGE_HOST=console.staging…`; (ב) הוא קליק אחד אצלך | P1 (קביעת `NETWORK_EDGE_HOST`) |
| **4** | **מודל אישור הצימוד** | (א) השער מנפיק אסימון מאחורי SSO, הצומת סורק (ברירת המחדל כאן); (ב) הצומת מציג, השער סורק, והאישור דורש SSO | (א) אפס משטחים לא־מאומתים; (ב) נוח יותר בטלפון אבל מוסיף סריקה+התחברות | P1 (מימוש הזרימה) |
| **5** | **איזה VPS הוא הקצה** | (א) `31.97.196.82` — כבר בצי כ־`computer_ssh-b154fa0c`, כבר מריץ `console.staging` + `auth.staging`; (ב) מכונה חדשה | (א) מומלץ: ה־wildcard, הקונסול והזהות כבר שם | P2 (היעד של מסלול הקבלה) |
| **6** | **WireGuard עצמי מול Headscale** | (א) עצמי (התוכנית); (ב) Headscale — NAT traversal ו־DERP בחינם, אבל מישור בקרה שני | (א) מומלץ ל־P1–P3 (שני צמתים, אחד מהם ציבורי); (ב) אם יתגלה צומת כפול־NAT בלי קצה — וניתן להחליף **מתחת לאותה אפליקציה** | P6 (טופולוגיות בלי קצה ציבורי) |

**לא החלטה פתוחה, כי היא כבר הוכרעה:** "הרכב התקנה" (אילו אפליקציות בצומת) הוא ה־`apps:` בהצהרת
`offices`, וההתקנה/השדרוג/התיקון עצמם הם `offices.converge` (§6, §13).

---

## נספח א — עובדות ריצה ב־macOS (שהיו חסרות ב־rev 1)

- הלשכה על מק רצה בתוך **Lima/vz guest** (`~/.bbox/macos`, Docker CE **28.5.2** נעוץ), עם ה־checkout
  מורכב באותו נתיב — כלומר **הכל רץ בלינוקס אמיתי**, לא ב־Docker Desktop (`packaging/macos.md`).
- **המשמעות ל־WireGuard:** המודול זמין בקרנל של ה־guest, ולכן המנהרה עובדת בגרסת הקרנל. הקונטיינר
  של אפלקציית `network` צריך `cap_add: [NET_ADMIN]` ו־`devices: ["/dev/net/tun"]`; כשהמודול חסר —
  נפילה ל־`wireguard-go` במרחב המשתמש, **ומדווחת ב־UI** (איטי פי 3–5, ואסור שזה יהיה שקוף).
- **הקצה על מק לא יכול להיות קצה ציבורי:** הקצה על מק מאזין ב־`http://<app>.localhost:8080` (macOS
  מסרב ל־:80 לתהליך לא־מיוחס), ו־ACME HTTP-01 דורש :80. לכן **צומת שמשמש edge ציבורי חייב להיות
  Linux** — ומתיישב עם §16 החלטה 5.
- בדיקת `NET_ADMIN` ו־`/dev/net/tun` היא **תנאי קדם שמדווח**, לא נפילה שקטה: אם הם חסרים, האפליקציה
  עולה במצב "אין מנהרה" עם הסבר, ולא מחזירה "מחובר" כשאין חיבור.

## נספח ב — הראיות שנמדדו (2026-09-29)

```
NS digital-office.co.il            → ns1.sitesdepot.com, ns2.sitesdepot.com
                                     SOA: ns1.sitesdepot.com admin.intervision.co.il (serial 2026091701)
A  staging.digital-office.co.il    → תשובה ריקה (NODATA, Status 0)     ← אין רשומה
A  *.staging.digital-office.co.il  → 31.97.196.82
A  macbook1.staging...             → 31.97.196.82
A  plane.macbook1.staging...       → 31.97.196.82
A  a.b.c.d.e.staging...            → 31.97.196.82                        ← עונה בכל עומק
A  x.digital-office.co.il          → NXDOMAIN (Status 3)                 ← אין wildcard על ה־apex
A  digital-office.co.il            → 31.97.196.82

curl -k https://console.staging.digital-office.co.il/  → 302 → auth.staging.../application/o/authorize/
                                                          (client_id + redirect_uri=/outpost.goauthentik.io/callback)
curl -k https://auth.staging.digital-office.co.il/     → 302 → /flows/-/default/authentication/?next=/
curl -k https://edge.staging.digital-office.co.il/     → 404 (traefik, אין ראוטר)
curl -k https://macbook1.staging.digital-office.co.il/ → 404 (traefik, אין ראוטר)
curl    https://staging.digital-office.co.il/          → 000 (לא פותר; TLS לא מתחיל)

GET http://computers:8977/api/computers → computer_local-local (172.18.0.1) ·
                                          computer_ssh-b154fa0c ("שרת פיתוח בינה סלושנס", 31.97.196.82)
Host( ב־.generated/routing.override.yml  → 25 שמות מנוקמפלים (המקור לרשימת ה־hosts השמורים)
```
