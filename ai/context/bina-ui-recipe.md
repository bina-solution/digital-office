# מתכון ה-UI של בינה — למה DeepSeek Harness יציב בכל גודל, ומה מפריד בינו לבין אפליקציות הלשכה

**תאריך:** 2026-09-27 · **סוג:** מחקר read-only (לא שונה קובץ באפליקציה) · **מקורות:** הקליפה של בינה
שנמסרת בפועל (`/opt/bina/harness/profile/node_modules/…`) מול ה-checkout של הלשכה.

---

## תקציר

1. **בינה לא "מסתדרת" בכל גודל — היא מחשבת אותו.** רוחב שלוש העמודות נגזר בפונקציה אחת,
   `computeColumns(viewport, sidebar, rightbar)`, שמייצרת פיקסלים מתוך רוחב הפריים בפועל, מהדקת
   כל עמודה לטווח, ומוותרת על העמודה הפחות חשובה לפני שהמרכז יורד מתחת למינימום. אין ולו
   `@media (max-width:1024px)` אחד שמחליט זאת.
2. **הרוחב נמדד על הפריים עצמו, לא על החלון.** `ResizeObserver` על אלמנט ה-frame
   (`dsh-client-ui-layout/lib/client.js:208-232`) — ולכן בינה מתנהגת נכון גם כשהיא מוטמעת ב-iframe,
   גם בחלון של הקונסול, גם במסך מלא, וגם כשהחלון מוקטן.
3. **94% מההסתגלות נעשית בלי נקודות שבירה.** בכל 320,633 הבתים של ה-CSS של בינה (קליפה + 107
   גיליונות של תוספים) יש **9** `@media` מבוססי-רוחב בלבד ו-**10** `@container`. כל השאר זורם:
   `min-width:0` ×238, `overflow:hidden` ×209, `nowrap` ×159, `ellipsis` ×103.
4. **שכבת טוקנים אמיתית:** 73 טוקני פלטה סטטיים → **91 טוקנים סמנטיים** (`--dsw-alias-*`) עם ערך
   נפרד ל-light ול-dark, ועוד ~185 טוקני טיפוגרפיה ו-9 elevation. לאף רכיב אין צבע משלו.
5. **הגופן הוא ציר נפרד.** המשתמש בוחר 12–17px, והבחירה מזיזה לא רק טקסט אלא גם גבהי שורה
   וגבהי אייקונים דרך `--dsh-content-font-delta` — טקסט גדל, הכרום לא מתפרק.
6. **מנגד, בלשכה:** 24 אפליקציות, ~430KB CSS (201KB בקבצים + 229KB בתוך `<style>` מוטבע),
   **14 ערכי רוחב שונים** ב-31 שאילתות מבוססות-רוחב (אין מערכת), `@container`: 3 — כולם באפליקציה
   אחת, 16 טוקנים משותפים בלבד (ושני ערכי `--radius-sm` סותרים בין הקונסול לערכה), ו-`min-width:0`
   שמופיע ב-**0** פעמים בחמש מהן. הפריסות הן מספרים קבועים (`#app{grid-template-columns:252px 1fr}`).
7. **הפער אינו "אין לנו design system" — הוא שהמערכת קיימת ונעצרת בשער.** המנגנון לחלוק טוקנים
   בין אפליקציות **כבר בנוי ומתועד** (`platform-base/bina-ui/theme-tokens.css`, שער G27,
   `theme-token-lint.py --fix`), והחוק של בינה — "המעטפת מחזיקה את ה-viewport, כל מה שמתחת מקבל את
   הגובה שנתנו לו" — **כבר כתוב אצלנו** ב-`scripts/ops/lint_viewport_units.py`. שניהם פשוט חלים על
   אפליקציה אחת או שתיים.
8. **ההמלצה:** לא להעתיק את הארכיטקטורה של בינה (React + 37 תוספים + CSS לכל תוסף) — להעתיק את
   **המכניקה** שלה: ~45 טוקנים סמנטיים, פותר עמודות קטן ב-JS, ספריית "מסגרת" מועתקת ומגודרת,
   והרחבת השערים הקיימים. שישה שלבים, כולם הפיכים, הראשון מהם הוא שינוי רשימה אחת.

---

## 1. שיטה — מה נמדד ואיך

| מה | איך |
|---|---|
| הקליפה של בינה | הפלטה והטיפוגרפיה חולצו מ-`@deepseek-ai/dsh-client-ui-theme/lib/client.js` (מחרוזות ה-CSS המוזרקות); הלוגיקה מ-`@deepseek-ai/dsh-client-ui-layout/lib/client.js` ו-`lib/types/client/columns.d.ts` |
| כל ה-CSS של בינה | 107 גיליונות ייחודיים שחולצו מ-`const css = "…"` בכל חבילות `dsh-client-ui-*` (266,111 בתים) + `dsh-web-frontend/dist/assets/index-*.css` (54,522 בתים) |
| התאמות ל-RTL וללשכה | `/opt/bina/plugins/{locale-he,brand-bina,office-context,office-workspace}` — קוד המקור של התוספים של הלשכה |
| אפליקציות הלשכה | סריקה סטטית של `apps/*` ו-`platform-base/*`: קבצי CSS, בלוקי `<style>` מוטבעים, media queries, ספירת מאפיינים, מאזני גלישה |
| אימות | 5 חוקרי-משנה במקביל, כל אחד עם הוראה לאמת כל טענה בנתיב:שורה; הממצאים צוטטו כאן עם הראיה שלהם |

**מה לא נמדד:** לא הורצה מדידה בדפדפן חי (אין Playwright בזמן המחקר). כל מספר כאן הוא סטטי
מהמקור. כל מקום שבו מסקנה נגזרת ולא נמדדת — מסומן **(נגזר)**.

---

## 2. שנים-עשר המנגנונים שהופכים את בינה ליציבה בכל גודל

### 2.1 מסגרת אחת שאינה נגללת — הגולל הוא תמיד פאנל פנימי

```css
/* index-*.css — ה-reset הגלובלי היחיד בכל האפליקציה (2 כללים) */
html,body,#root{height:100%;margin:0}
button,input,select,textarea{font-family:inherit}

/* AppFrame.module.css (dsh-client-ui-layout/lib/client.js:71) */
.pI_x6G_frame{background:var(--dsw-alias-bg-base);height:100%;grid-template-rows:100%;
  display:grid;position:relative;overflow:hidden;
  transition:grid-template-columns var(--ds-transition-duration-slow) var(--ds-ease-in-out)}
.pI_x6G_sidebarCol{min-width:0;overflow:hidden}
.pI_x6G_centerCol{flex-direction:column;min-width:0;display:flex;overflow:hidden}
.pI_x6G_rightbarCol{min-width:0;position:relative;overflow:visible}
```

העמוד אינו יכול להיגלל אופקית **מבנית**: `html/body/#root` בגובה מלא, המסגרת `overflow:hidden`,
וכל אחת משלוש העמודות `min-width:0` + `overflow:hidden`. מה שנגלל הוא רק מה שהוכרז כגולל.
זו הסיבה המרכזית לכך שבינה "לא נשברת": אין בה מצב שבו הדף רחב מהחלון.

**בלשכה:** `apps/mail/mailview/static/index.html:111` — `#app{grid-template-columns:252px 1fr;
height:100vh}` עם `body{overflow:hidden}` (`:68`) — המסגרת קיימת אבל העמודות **אינן** `min-width:0`
באופן שיטתי, ובמקביל יש **ארבעה** גוללים על אותו מסך (`.sidescroll:148`, `.tablewrap:188`,
`.rp-scroll:269`, `.org-grid:518`).

---

### 2.2 פותר עמודות — פיקסלים מחושבים, לא נקודות שבירה

```js
// dsh-client-ui-layout/lib/client.js:36-44
const s = sidebar === 0 ? 56 : clampWidth(sidebar, 264, 420);
const available = viewport - s - 400;                       // 400 = מרכז מוגן
const r = rightbar === 0 || available < 300 ? 0
        : Math.min(available, clampWidth(rightbar, 300, viewport * 0.7));
return { sidebar: s, center: Math.max(0, viewport - s - r), rightbar: r };
```

החוזה המלא (‎`columns.d.ts`): `CENTER_MIN=400`, `SIDEBAR_MIN=264`, `SIDEBAR_MAX=420`,
`SIDEBAR_DEFAULT=280`, `SIDEBAR_COLLAPSED=56`, `SIDEBAR_AUTO_COLLAPSE=1024`, `RIGHTBAR_MIN=300`,
`RIGHTBAR_MAX_RATIO=0.7`, `RIGHTBAR_DEFAULT_RATIO=0.45`.

המשמעות: הסרגל הצדדי **לעולם לא מוותר**, הלוח הימני מצטמצם ואז **מאבד את המקום שלו לגמרי**
(`available < 300` → `r=0`), ורק אז המרכז יורד מתחת ל-400. כלומר יש **סדר עדיפויות מוצהר**, ולא
שלושה כללי CSS שמתנגשים.

הרוחב נמדד על הפריים:
```js
// client.js:214-226
const measure = () => { const w = el.getBoundingClientRect().width; if (w>0) actions.setViewportWidth(w); };
measure();
const observer = new ResizeObserver(() => { raf ??= requestAnimationFrame(()=>{ raf=null; measure(); }); });
observer.observe(el);
```
`ResizeObserver` **על אלמנט המסגרת** (לא `window.resize`), עם `requestAnimationFrame` שחוסם
סערות — כלומר בינה יודעת את רוחבה האמיתי גם בתוך iframe, גם כשהחלון נגרר, וגם כשהמסגרת מצטמצמת
בגלל פאנל שנפתח לידה.

**בלשכה:** `matchMedia`/`innerWidth`/`ResizeObserver` = **0** ב-`apps/mail/mailview/static/` כולה;
ב-5 האפליקציות החדשות (computers/sites/domains/telegram-tv/git) = **0 בקוד חי**. ההחלטה היחידה
שמתקבלת היא הצהרתית: `domains/static/index.html:109` `@media (max-width:900px){.layout{grid-template-columns:1fr}}`.

---

### 2.3 "צר" הוא מצב, לא תצוגה שנייה

```js
const narrow = viewport < SIDEBAR_AUTO_COLLAPSE;              // 1024
const sidebarCollapsed = narrow ? !layoutInfo.narrowExpanded : layoutInfo.sidebar === 0;
// צר + פתוח ⇒ הסרגל מצויר כ-overlay ואינו צורך מסלול ברשת:
const normal = computeColumns(viewport, !layoutInfo.rightbarShown && narrow ? 0 : sidebarPreference, …);
```
ובחנות (`client.js:369-374`): מעבר את סף ה-1024 **מאפס** את `narrowExpanded`, כדי שמצב שהיה פתוח
בטלפון לא יגרור לוח פתוח בדסקטופ.

המסילה עצמה היא **אותו DOM**, לא רכיב אחר (`dsh-client-ui-sidebar/SidebarRoot.module.css`):
```css
.hHd-Xa_root.collapsed{padding:18px 10px 6px}
.hHd-Xa_collapsed .hHd-Xa_panelRow{width:36px;height:36px;justify-content:center;padding:0}
.hHd-Xa_collapsed .hHd-Xa_newSessionLabel{max-width:0}   /* התווית מצטמצמת, לא נעלמת */
```
תווית שנעלמת היא פחות נגישה מתווית שנמחצת ל-0 — וכך גם אין שני מסלולי קוד לתחזק.

**בלשכה:** הקונסול **כן** עושה את זה (`console/static/style.css:391-397` — מסילה של 62px בטווח
641–1024, `:400-419` — מתחת ל-640 מסתתר הסרגל ומופיע `.bottomnav` בגובה 60px).
האפליקציות שבתוכן לא: ל-mail אין מגירה, `.side` נשאר 252px, וב-390px ה-iframe נשאר עם **114px**
לשורת המייל (נגזר: 390 − 252 − 2×12 ריפוד).

---

### 2.4 שכבת טוקנים דו-שלבית — 73 → 91, ולא צבע אחד ברכיב

```
--dsw-static-*   (73)  הפלטה: neutral-00…1000, neutral-bluish-*, deepseek-*, blue-*, red-*, green-*, amber-*
--dsw-alias-*    (91)  סמנטי: bg-base/layer-1/2/3, bg-overlay, bg-mask-1/2/3, label-primary/secondary/
                       tertiary/caption/dimmed, border-l1..l4, brand-primary, link, state-*-primary/
                       secondary/tertiary, interactive-bg-hover/active, scrollbar-*, markdown-*, …
--dsw-specific-* (11)  bubble, menu, sidebar-fill, sidebar-nav-item-*, input-major, toast, tooltip
```

**כל** טוקן סמנטי מוגדר פעמיים — `body{…}` ו-`body[data-ds-dark-theme]{…}` — כך שהחלפת מצב היא
`body.toggleAttribute("data-ds-dark-theme")` אחד (`dsh-client-ui-theme/lib/client.js`, `bootThemeScript`).
אין JS שנוגע בצבע, ואין רכיב שמכיר hex.

נגזרות נעשות ב-CSS, לא בטוקנים חדשים: `color-mix(in srgb, var(--dsw-alias-state-success-primary) 10%, transparent)`
×30 — למשל התגיות ב-`Tag.module.css` (tone=success/warning/danger/info).

**בלשכה:** 16 טוקנים משותפים (`platform-base/bina-ui/theme-tokens.css`) שחלים על 10 משטחים מתוך 24;
`apps/indox/app/webapp/src/index.css` **אינו** ב-`TARGETS` של G27 (רק ב-`FONT_TARGETS`) ולכן אין לו
dark כלל — הוא נשאר לבן בתוך קונסול כהה. `apps/telegram-tv/static/style.css` גם אינו ב-`TARGETS`.
`connection`/`machine`/`any-concurrency`/`app-management`/`notifications` — אף אחד מהם לא נושא את
הבלוק. `app-management` משתמש ב-**15%** תיקנון צבעים (72 מתוך 85 hex קשיחים ב-`:12-20`).

וחמור מכך — **יש שתי מערכות טוקנים מתחרות ולא חופפות**: ל-`console/static/style.css` יש **48**
טוקנים (`--elev-1..4`, `--space-1..8`, `--dur-*`, `--ok/--warn/--danger/--info`) ול-`bina-ui.css`
**28** (`--radius`, `--mono`), והן **סותרות**: `--radius-sm` הוא **8px** בקונסול (`style.css:15`)
ו-**9px** ב-`bina-ui.css:20`. G27 אינו תופס זאת, כי הוא משווה **רק את האזור המסומן** בין העותקים
(`theme-token-lint.py:110-124`) ולא את שאר הקובץ.

ובאג dark אמיתי, מאותה סיבה בדיוק: `bina-ui.css:49` **מגדיר** `--ok-soft/--warn-soft/--danger-soft/
--info-soft` — **ואף רכיב לא קורא אותם** (0 שימושים). במקומם כתובים צבעים קשיחים:
`.pill.warn{background:#fdf1dc}` (`:92`), `.pill.bad{#fdecea}` (`:93`), `.pill.unset{#eef1f4}` (`:95`),
`.callout.warn{#fffaf0}` (`:103`). התוצאה ב-OS-dark: **כל הגלולות והבאנרים של כל אפליקציה שמשתמשת
ב-bina-ui נשארים בהירים**. זה בדיוק הכשל ש-G27 נכתב למנוע — והוא לא רואה אותו, כי הגלולה לא
משתמשת בטוקן.

---

### 2.5 הגופן הוא ציר — טקסט גדל, כרום לא מתפרק

```css
body{--dsh-content-font-delta:calc(var(--dsh-content-font-size,14px) - 14px);
     --dsh-content-font-size-secondary:min(calc(var(--dsh-content-font-size,14px) - 1px),
                                           max(13px, calc(var(--dsh-content-font-size,14px) - 2px)));
     --dsw-font-markdown-h1:700 calc(21px + var(--dsh-content-font-delta)) / calc(30px + var(--dsh-content-font-delta)) …}
```
ובכל רכיב גבהים נגזרים מהציר, לא מקובעים:
```css
.turnStatus{height:calc(26px + var(--dsh-content-font-delta,0px))}
.leading{width:calc(16px + var(--dsh-content-font-delta,0px)); height:calc(16px + var(--dsh-content-font-delta,0px))}
```
הבחירה עצמה נשמרת בשרת (‎`settings` namespace‎ `ui-theme`, `fontSize` 12–17, ברירת מחדל 14) ומוזרקת
לעמוד ב-`<script>` inline **לפני** שהמודולים נטענים — ולכן אין הבהוב של פונט לא נכון.

**בלשכה:** אין סקאלה. `mail` משתמש ב-16 גדלים ייחודיים, `indox` ב-17, `telegram-tv` ב-52 הצהרות
`font-size` — כולל חצאי-פיקסל (10.5/11.5/12.5/13.5) ובסיס שונה בין אפליקציות (14px מול 15px).
אין `rem` ואין `clamp()` באף אחת מהן (חוץ מ-telegram-tv, שיש לה 3).

---

### 2.6 משמעת אנטי-גלישה — המספרים הם ההסבר

| מאפיין | בינה (320KB CSS) | mail | indox | 5 החדשות |
|---|---|---|---|---|
| `min-width:0` | **238** | 28 | 32 | **5** (כולם ב-telegram-tv) |
| `overflow:hidden` | 209 | 22 | 45 | 23 |
| `white-space:nowrap` | 159 | 26 | 44 | 16 |
| `text-overflow:ellipsis` | **103** | 17 | 21 | **3** |

ההבדל אינו סגנוני. `min-width:0` הוא מה שמאפשר לילד flex/grid להתכווץ **מתחת ל-min-content שלו**;
בלעדיו, ילד עם טקסט ארוך (שם קובץ, נושא מייל, כתובת URL) דוחף את המכל, המכל דוחף את השורה, והשורה
דוחפת את הדף — וזה בדיוק "נשבר בגודל הזה".
ההחלפה הנפוצה בלשכה היא `flex-wrap:wrap` — שמסדר מחדש במקום לכווץ, ולכן היא "עובדת" אבל מייצרת
שורות גבוהות ומכוערות. בינה ממעטת ב-wrap ומרבה ב-`nowrap` + `ellipsis`.

---

### 2.7 תשע נקודות שבירה לכל האפליקציה, ועשרה קונטיינר-קווריז

```
@deepseek-ai/dsh-web-frontend  (54KB, כל הקליפה)   → 3 @media, כולם prefers-reduced-motion
107 גיליונות של תוספים        (266KB)             → 43 @media:
     24 prefers-reduced-motion · 5 pointer:coarse · 3 prefers-reduced-motion:no-preference
     2 hover · 9 מבוססי-רוחב: 480, 560×4, 680, 720×2, 760
   + 10 @container: 271 · 360 · 375 · 460 · 479 · 583 · 620 · 687 · 900 · container בשם
```

הקונטיינר-קווריז הם התשובה לשאלה "הרכיב הזה צר — לא החלון":
```css
/* Deliverables.module.css — רשת הקבצים שנמסרו */
.root{container-type:inline-size}
.presented{grid-template-columns:repeat(2,minmax(0,1fr))}
@container (width<=620px){.presented{grid-template-columns:minmax(0,1fr)}}
@container (width<=687px){.file:nth-of-type(6){display:none} .more[data-shown="6"]{display:inline}}
@container (width<=583px){…:nth-of-type(5)…} @container (width<=479px){…} @container (width<=375px){…}
```
וכותרת טבלה שמצטמצמת לפי **רוחב הטבלה שלה**:
```css
@container Y0dWHa_trajectory-table (width<=620px){ .eventColumn{width:50px} .event{padding-left:28px!important} }
```
ובשלושה מקרים ירדו לרזולוציה של **271px** — כלומר מישהו בדק גם בתוך חלון מרובע.

**בלשכה:** ל-`indox` יש 3 קונטיינר-קווריז (`index.css:396,790,825`) עם `container-type:inline-size`
ו-fallback של `@supports not (container-type)` — הדפוס הנכון, וזה מה שמציל אותו ב-834px.
לכל שאר 23 האפליקציות: **0**.

---

### 2.8 לכל רכיב יש חוזה גודל מקסימלי/מינימלי מפורש

```css
/* טבלת markdown — לא דוחפת את הדף, אף פעם */
._tableScroll{max-width:100%;overflow-x:auto;overscroll-behavior-x:contain}
._tableScroll th,._tableScroll td{max-width:320px;max-width:min(30vw,320px);min-width:100px}
._tableScroll.md-table-wide{overflow-x:hidden;padding-bottom:var(--dsh-scrollbar-width,8px)}
._tableScroll.md-table-wide:hover{overflow-x:scroll;padding-bottom:0}   /* פס גלילה שמתגלה ב-hover */

/* תפריט — לא יוצא מהמסך */
._list{min-width:218px;max-width:360px;position:absolute;top:calc(100% + 4px)}
._scrollable{max-height:calc(100vh - 24px)}

/* מודאל — לא רחב מהפריים */
._confirmation{width:min(440px,100%);max-height:calc(100vh - 48px);overflow:hidden}
@supports (height:100dvh){._confirmation{max-height:calc(100dvh - 48px)}}

/* Selector של מודל — רחב בדיוק כמו שיש מקום */
.trigger{max-width:min(360px,45cqw)}
.menu{min-width:min(240px,100vw - 32px);max-width:min(420px,100vw - 32px);max-height:min(360px,100vh - 96px)}
```

זה אותו רעיון שלוש פעמים: **הרכיב מצהיר את גבולותיו, ולא מקווה שהמכל יספיק**. 191 שימושים
ב-`calc(` ו-18 ב-`min(`/`max(` הם בדיוק זה.

**בלשכה:** הדוגמה הטובה היא `indox` (`DataGrid.tsx:1173` — `template` נבנה מסכום רוחבי עמודות,
`:1562` `style={{minWidth}}`, ו-`.dg-scroll{overflow:auto}`) — הטבלה נגללת בתוך המכל. הדוגמה
הרעה: `sites/static/app.js:256,266,334,397,401` — **חמש טבלאות, אף אחת לא עטופה ב-`overflow`**.

---

### 2.9 `pointer:coarse` ו-`prefers-reduced-motion` הם ברירת מחדל, לא תוספת

בינה: 5×`@media (pointer:coarse)` (למשל `Deliverables`: `min-height:44px` לכפתור המפוצל),
31×`prefers-reduced-motion`, 2×`@media (hover:hover)` כדי לא להראות אפקט-ריחוף במגע,
ו-`corner-shape:superellipse(1.5)` בתוך `@supports` (שיפור פרוגרסיבי).

**בלשכה:** `pointer:coarse` מופיע ב-3 מקומות בלבד — `console/static/style.css:437` (44px),
`mailview/index.html:146,707`. ב-5 האפליקציות החדשות: **0**. הבקרות שם 24–37px
(`sites:93` `.step` ≈24px, `computers:87` `.btn.sm` ≈28px, `telegram-tv:81` `.icon-btn` 36px).
`prefers-reduced-motion` קיים בקונסול ובחלק מהאפליקציות, אבל לא כמדיניות.

---

### 2.10 RTL: מנוע LTR + שכבת תיקון מתועדת (השיעור החשוב ביותר ללשכה)

בינה עצמה **אינה דו-כיוונית**: `dist/index.html` הוא `<html lang="en">` בלי `dir`, וה-CSS של הפריסה
פיזי (`border-right`, `margin-left:-4px`, `left:`). העברית נעשית בתוסף נפרד —
`/opt/bina/plugins/locale-he/lib/client.js` — שמזריק גיליון אחד (`RTL_CSS`, id=`bina-rtl-css`) ומגדיר
`document.documentElement.dir="rtl"`.

הגיליון הזה הוא **חמישה כללים, כל אחד עם הסבר כתוב**:

```css
/* 1. קוד/פקודה/נתיב: תמיד LTR מבודד ("/root/one/" הוצג כ-"root/one/") */
html[dir="rtl"] code, pre, kbd, samp { direction:ltr; unicode-bidi:isolate; text-align:left }

/* 2. קישור לפי הטקסט שלו: URL משמאל, תווית עברית מימין */
html[dir="rtl"] a[href] { unicode-bidi:plaintext }

/* 3. כל בלוק מיושר לקצה ה-start — בעברית וגם באנגלית (החלטת בעלים 2026-09-17) */
html[dir="rtl"] p, li, h1..h6, blockquote, dd, dt { unicode-bidi:plaintext; text-align:right }

/* 4. הודעת המשתמש מוצמדת ל-start, לא ל-end */
html[dir="rtl"] [class*="_userRow"], [class*="_userStack"] { align-items:flex-start }

/* 5. שורת הפקדים של התיבה: margin-left:auto פיזי של המנוע שובר את RTL —
      המקבילה הלוגית (margin-inline-start:auto) מחזירה את כפתור השליחה לקצה */
html[dir="rtl"] [class*="_trailing"] { margin-left:0; margin-right:auto }
```
בנוסף: משטחים מפתחים (trajectory, terminal, diff, code block) **נשארים LTR בכוונה**, וטקסט רץ
בתוכם חוזר ל-`text-align:left`.

המסקנה המעשית: בינה לא "תומכת RTL" — היא **מתקנת** מנוע LTR בשכבה מבודדת, מתועדת, בת חמישה כללים.
המחיר: כל שינוי upstream שיבטל `_userRow`/`_trailing` ישבור את הכלל בשקט. היתרון: אין פורק.

**בלשכה — כאן אנחנו טובים מבינה:** כל האפליקציות הן `dir="rtl"` ב-`<html>` ובעלות **0** מאפיינים
פיזיים של מרווח ב-`indox`/`mail`/`computers`/`sites`/`domains`/`telegram-tv`, עם 8–26 מאפיינים לוגיים
כל אחת. `telegram-tv` אף מכבדת RTL ב-JS (`app.js:632` — `frac=(rect.right-e.clientX)/rect.width`,
"RTL: the bar is filled from the right"; `app.js:532` כותב `insetInlineStart`).
מה שכן חסר: **אין לנו שכבת בידוד דו-כיוונית אחידה**. `mail` עוטף 68 `<bdi>` ידנית; `indox` סומך על
-`direction:ltr;unicode-bidi:isolate` ב-10 כללים (אופט-אין שנשכח בכל className חדש); לאחרות אין.
נוסחה: שלושת כללי ה-RTL הראשונים של בינה (קוד LTR, קישור לפי תוכן, `.ltr`/`.num` גנרי) הם מה שחסר.

---

### 2.11 ארכיטקטורה: 37 תוספים, 107 גיליונות, 47 סלוטים — ואין CSS גלובלי

```js
// כל תוסף: CSS משלו, מוזרק עם זהות משלו
const tagId = "@deepseek-ai/dsh-client-ui-layout/AppFrame.module.css";
if (document.querySelector(`style[data-plugin-css="${tagId}"]`) === null) {
  const tag = document.createElement("style");
  tag.dataset.plugin = "@deepseek-ai/dsh-client-ui-layout"; tag.dataset.pluginCss = tagId;
  tag.textContent = css; document.head.appendChild(tag);
}
```
הקליפה מרנדרת **רק** את הסלוט `root`; הפריסה מצהירה על ארבעה סלוטים (`sidebar` single, `main`
keyed, `rightbar` single, `shell.overlay` list) ו-47 שמות סלוטים בסך הכול
(`conversation.composer`, `settings.general.item`, `sidebar.footer.action`, …).
המחלקות מהושות (`._7KE1Ra_trigger`), כלומר אין namespace גלובלי שאפשר לשבור בטעות.

המחיר של המודל הזה: **320KB CSS, מתוכם חלק לא מבוטל כפילות בין תוספים**. היתרון: תוסף אחד לא יכול
להרוס תוסף אחר, והוספת יכולת לא נוגעת בקליפה. זו הסיבה שבינה "עמידה" גם כשהיא גדלה.

**בלשכה:** כל אפליקציה היא מסמך נפרד עם גיליון מונוליטי מוטבע. `apps/git/static/index.html:11-104`
ו-`apps/sites/static/index.html:11-104` **זהים בייט-בייט** (אומת ב-`diff`), וכך גם domains. חמש
משש אפליקציות ה-base מגדירות **אותו `:root` בדיוק**.

---

### 2.12 בלי הבהוב, ובלי "מסך לבן בזמן טעינה"

```js
// dsh-client-ui-theme/lib/index.js — מוזרק כ-<script> inline לפני שהמודולים נטענים
document.documentElement.style.colorScheme = dark ? 'dark' : 'light'
document.body.toggleAttribute('data-ds-dark-theme', dark)
document.body.style.setProperty('--dsh-content-font-size', '14px')
```
מסך הטעינה עצמו (`.boot`) משתמש **בטוקנים עם נפילה לאחור**:
`background:var(--dsw-alias-bg-base, var(--dsh-boot-bg))` — כלומר גם לפני שה-CSS של התוספים נטען,
הצבע נכון ולא מופיע בזק לבן→שחור.

---

## 3. מה יש ללשכה היום — המדידה

### 3.1 מצרפי

| מדד | בינה | הלשכה |
|---|---|---|
| משטחים חזיתיים | 1 אפליקציה, 37 תוספים | 24 אפליקציות/שירותים |
| CSS | 320,633 B ב-108 גיליונות | ~430KB: 201KB בקבצי `.css` + **229KB בתוך `<style>` מוטבע** |
| טוקנים סמנטיים | **91** (+73 פלטה, +185 טיפוגרפיה) | **16** בכלל; **48** בקונסול מול **28** ב-bina-ui, בשתי קבוצות שלא חופפות |
| `@media` (הכל) | 46 | 63 — מהם **31 מבוססי-רוחב** |
| ערכי רוחב מובחנים | 480 · 560 · 680 · 720 · 760 | **14**: 520, 640, 641, 680, 700, 720, 760, 800, 820, 900, 1024, 1100, 1120, 1121 |
| `@container` | 10 | 3 (כולם ב-indox) |
| `min-width:0` | 238 | **121** בכל הלשכה — ומתוכם 90 בשלוש אפליקציות (indox 32, drive 30, mail 28) |
| `text-overflow:ellipsis` | 103 | **82** בכל הלשכה |
| קוד viewport ב-JS | פותר עמודות מלא + ResizeObserver על הפריים | `matchMedia`: **0**; `ResizeObserver`: 2 (indox לגובה, bina-table לרוחב עמודות) |
| `pointer:coarse` | 5 | **3 שורות** (console:437-441, 7 מחלקות) + mail |
| בקרת גודל טקסט למשתמש | ציר 12–17px שמזיז גם גבהים ואייקונים | **אין** |
| שער שמגן | — | G27 (10 משטחים מתוך 24) |

### 3.2 לפי אפליקציה (מדידות החוקרים; ראיות בקיצור)

| אפליקציה | CSS | `@media` רוחב | `@container` | `min-width:0` | dark | הבשלה |
|---|---|---|---|---|---|---|
| `console` | 55KB (style 31.9 + desktop 23.6) | 640 / 760 / 1024(+641) / 1100 | **0** | 12 | ✔ | **הטובה** — מסילה 62px, bottom-nav 60px, `pointer:coarse`; אבל `bina-ui.css` רוחב-עיוור (0 MQ) |
| `indox` | 79KB | 640×2 / 760 / 520 | **3** | 32 | ✗ | **הטובה** — "גולל אחד", טבלה שנגללת, 100dvh |
| `mail` | 49KB inline | 640 / 760 / 820 | 0 | 28 | ✔ | בינונית — rail קבוע 252px שלא מתקפל |
| `drive` | 42KB inline | 1120 / 820 / 700 / 640 | 0 | **30** | ✔ | **הטובה** — `minmax(0,248px)`, 17 overflow:hidden, 11 ellipsis, `pointer:coarse`, מגירה off-canvas ב-640 |
| `telegram-tv` | 26KB | 900 (24 הצהרות) | 0 | **5** | ✔ | **הטובה מבין החדשות** — `clamp()`, aspect-ratio, RTL ב-JS |
| `domains` | 19KB | 900 / 700 / 640 | 0 | 0 | ✔ | בינונית+ — הסולם היחיד; 7 מ-9 טבלאות לא עטופות |
| `my-docs` | 18KB | 720 (no-op) | 0 | **0** | ✔ | **נמוכה** — רשתות `1fr 260px` קבועות; נשבר ב-390px ב-2 מקומות |
| `app-management` | 16KB | **0** | 0 | 1 | ✗ | **הגרועה** — 15% תיקנון צבעים |
| `apitools` | 14KB | 2 | 0 | — | ✗ | — |
| `connections` | 12KB | 680 | 0 | 5 | ✗ | בינונית — טבלה→כרטיסים; חסר `<meta viewport>` ו-`<html>` |
| `sites` | 11KB | **0** | 0 | 0 | ✔ | **הגרועה מבין החדשות** — גרף שנחתך בשקט, 5 טבלאות לא עטופות |
| `data-management` | 11KB | **0** | 0 | **0** | חלקי | **לא נשבר באף רוחב** — זרימה טהורה (הוכחה נגדית, ראו 3.4) |
| `computers` | 10+13KB | 760 / 900 | 0 | 0 | ✔ | טוב — טבלה→כרטיסים עם `data-th`; 51KB נכסים מתים |
| `notifications` | 10KB | 640 | 0 | 1 | ✗ | בינונית-נמוכה — פלטת dark סוטה (`#0f1613` מול `#0d1411`) |
| `machine` | 9KB | 900 | 0 | **0** | ✗ | בינונית-גבוהה — `min-width:960px` מול ~338px |
| `any-concurrency` | 8KB | **0** | 0 | 0 | ✗ | **הגרועה** — `RAIL=232` קשיח ⇒ 82px לציור ב-390px |
| `git` | 7KB | **0** | 0 | 0 | ✔ | עמיד **בהיעדר תוכן רחב**, לא בתכנון |
| `chat` | 0 (ב-JS) | — | — | — | — | — |

### 3.3 שלוש עובדות מבניות שמסבירות את רוב התסמינים

1. **רוחב ה-iframe אינו רוחב החלון.** פרופיל mobile=390 ⇒ iframe 390; tablet=834 ⇒ iframe **772**
   (מסילת 62px); desktop=1440 ⇒ iframe **1202** (`console/static/style.css:114,391-405`).
   כלומר `@media (max-width:820px)` ב-mail **כן** נורה בטאבלט, אבל `@media (max-width:900px)`
   ב-domains/sites/telegram-tv **לא** — כלומר נקודת השבירה שלהם גבוהה מהרוחב האמיתי שקיבלו.
2. **הקונסול מסקל במקום לפרוס מחדש.** `console/static/desktop.js:196` —
   `e.style.transform="scale("+s+")"` עד `S_MIN:0.16`, ורק מתחת ל-`READ_Z:0.8` (`:34`) נקרא
   `reflow()` (`:223-236`) שמצר את ה-iframe. כלומר חלון מוקטן מצויר ב-85% **בלי שהאפליקציה תראה
   viewport צר** — ה-media queries שלה לא נורו, והטקסט פשוט קטן. שום אפליקציה לא מזהה זאת
   (`visualViewport`/`ResizeObserver` = 0).
3. **השער קיים, הכיסוי חסר.** `theme-token-lint.py:41` — `TARGETS` מכסה 10 משטחים;
   `FONT_TARGETS:59` מכסה 5. חמש משש אפליקציות ה-base, `indox`, `telegram-tv` ו-`apitools`
   מחוץ לבלוק הטוקנים. התוצאה הנצפית: dark בקונסול מול אפליקציה לבנה בתוכו.

### 3.4 הוכחה נגדית: `data-management` לא נשבר **בלי** נקודות שבירה

`platform-base/data-management` הוא המקרה המעניין ביותר בכל הלשכה:

* **0** `@media` מבוססי-רוחב · **0** `min-width:0` · **0** `text-overflow:ellipsis` · **0**
  `pointer:coarse`
* ובכל זאת — לפי בדיקת החוקר — הוא **היחיד שלא נשבר באף רוחב**, כי הוא בנוי נכון מבנית:
  זרימה טהורה (`grid-template-columns:repeat(auto-fit,minmax(158px,1fr))` ב-`:95`), ומכל שמגן על
  עצמו סביב כל טבלה (`<div style="overflow-x:auto">` ב-`:269` — כל עשר הטבלאות).

ומנגד, `drive` מגיע לאותה תוצאה עם **6** נקודות שבירה ו-30 `min-width:0`; ו-`my-docs` נכשל כי הוא
**בין השניים**: לא זרימה טהורה (`grid-template-columns:1.1fr 2fr` ב-`:83`, `repeat(4,1fr)` ב-`:90`,
`1fr 260px` ב-`:214`) וגם לא מכל שמגן על עצמו (`.tablewrap{overflow:hidden}` ב-`:108`).

**המסקנה שזה מכריח:** היעד אינו "להוסיף נקודות שבירה" אלא **שהפריסה תיגזר מהמקום, וכל מכל יגדיר
את גבולותיו**. מספר נקודות השבירה הוא תסמין, לא התרופה.

### 3.5 פער המדידה — המערכת שמודדת לא מודדת את מה שנשלח

זו התגלית שסביר שתופיע שוב בכל תיקון עתידי:

| מה | הממצא |
|---|---|
| `flow-qa.py` (הבדיקה הרספונסיבית היחידה: `:535` no page h-scroll, `:537` spills, `:539` double v-scroll; `--mobile` מריץ ב-390×844) | **אינה ב-CI** — `grep flow-qa .github/workflows/*.yml` → **0**. היא מופיעה רק כהוראה ידנית ב-`CLAUDE.md`, ורצה על **הסים** |
| G4 (`ui-pixel-diff`) | כל **75** צילומי הייחוס הם **2880×1800 (דסקטופ בלבד)**; אין רפרנס ב-390px או 834px. והשער **report-only** (`ui-map.yml:160` — `UI_MAP_GATE` ברירת מחדל 0) |
| צילום mobile | היה **שבור בשקט עד 2026-08-06**: `run_capture.sh:113-120` מתעד ש-`view-profiles.yaml` לא הועתק, ולכן `_load_profile()` נפל תמיד ל-`desktop` — "a `--profile mobile` run captured every view at the desktop 1440x900 viewport … with no error". כל נתון mobile מלפני התאריך הזה הוא דסקטופ בשם מטעה |
| `build.mjs:26` מול `:30` | מטמיע את `my-docs` **האמיתי** אבל **fork** של drive (`digital-office/sim/apps/localdrive`, 45,420B מול 49,315B) — כלומר `layout/drive` בודק קוד אחר ממה שמוגש |
| התיקון ל-`my-docs` | כבר כתוב — `digital-office/sim/overlay/responsive.js:144-156` מנמק בשמו את השבירה ("its nav stays one wide row and the .kpi-strip is a fixed 4-col grid") ומתקן אותה. הוא נטען **רק לסים** (`build.mjs:49,253`), בעוד הלאב עצמו נשבר ב-390px |
| לינט CSS | **לא קיים.** `compile-lint.py` (G12) בודק `.py` בלבד; אין stylelint; ו-`charset-first-lint.py` כתוב אך **אינו מחווט** (`run-gates.py:271` מכניס אותו ל-`NOT_A_GATE`) |
| `live-ui-map.py` | המסלול היחיד שרץ על הלאב — **לא מחווט לשום דבר** (`bbox ui-map` → `ui-map.sh:87` → `run_capture.sh`/`capture.py`) |
| `data-management` | אין לו שער UI כלשהו: לא ב-`console_embed`, אין states, אין pairs, אין code-coverage |
| `my-docs` | אינו מצולם חי (`run_capture.sh:53`) אך עדיין מזווג ב-`pixel-diff.yaml:85-86` ונספר ב-`code_coverage` |
| `pixel-diff.yaml:82-93` | מוסט בפאנל אחד מול `sim/ui-map.py:253-256` |
| `console/test_app.py` | 4 טסטים — **אינם רצים ב-CI** (רק 3 הרצות pytest ב-`ci-verify.yml:493,500,524`, ואף אחת אינה הזו) |

במלים אחרות: **יש סים שמדד, יש כלי צילום שמדד, ואין מסלול שמחבר ביניהם ל-24 המשטחים שנשלחים.**

### 3.6 עשרת השבירות הקונקרטיות (מדורג לפי חומרה)

| # | אפליקציה | מה נשבר | הראיה |
|---|---|---|---|
| 1 | `my-docs` | גלישת עמוד ~192px ב-390px: nav בשורה אחת (5 פריטים ≈468px, `nowrap`, בלי `flex-wrap`) + `.kpi-strip{repeat(4,1fr)}` | `style.css:58-59,90,93`; התיקון קיים ב-`sim/overlay/responsive.js:150-156` בלבד |
| 2 | `any-concurrency` | `RAIL=232` קשיח ⇒ בציור נשארים **82px** ב-iframe של 390px, ו-`body{overflow:hidden}` הופך חריגה לחיתוך שקט | `static/index.html:264,278,32` |
| 3 | `sites` | גרף שעות (עד 168 עמודות × 4px = 672px) בתוך `overflow:hidden` של 298px ⇒ ~74 שעות נראות, השאר נעלם בלי סימן. 5 טבלאות, אף אחת לא עטופה | `index.html:141-142`; `app.js:256,266,334,397,401` |
| 4 | `mail` | rail קבוע 252px ⇒ **114px** לתוכן ב-390px; 4 גוללים במקביל; iframe של גוף המייל נעול ל-`min-height:240px` בלי autosize | `index.html:111,148,188,269,279`; `app.js:944-946` |
| 5 | `indox` | ה-tabstrip נחתך באמצע (≈490px של טאבים ב-390px, בלי `overflow` — "בדיקות" ו"חילוץ מסמכים" לא נגישים) | `App.tsx:433` + `index.css:225,36` |
| 6 | `computers` | `style="grid-template-columns:1fr 1fr 2fr"` inline גובר על ה-breakpoint ⇒ מודאל "הרצת פקודה" נשאר 3 עמודות ב-322px | `index.html:259` מול `:121` |
| 7 | `domains` | 7 מ-9 טבלאות בלי עטיפת `overflow`, וטבלת ה-diff במגירה בלי כרטוס בטלפון | `app.js:237,319,323,812`; `.diff` ב-`index.html:217-218` |
| 8 | `telegram-tv` | `.chat-row{auto 1fr auto}` בלי `min-width:0` על האמצעית, בתוך `.app{overflow-x:hidden}` — חיתוך במקום גלילה | `style.css:304,310,343` |
| 9 | `machine` | `.table{min-width:960px}` מול ~338px שמיש; `min-width:0`=0 | `index.html:86` |
| 10 | `computers`/`machine`/`my-docs` | ~51KB נכסים מתים: `vendor/bina-table.{js,css}` נטענים אך **אינם בשימוש** (0 מחלקות `bt-`) | `computers/index.html:10`; ‏`app.js` ללא `bt-` |

### 3.7 הקונסול — המעטפת הטובה, ומה שנשאר בה

הקונסול הוא המשטח הבשל ביותר בפלטפורמה, ובכל זאת:

* **ערכת העיצוב עצמה רוחב-עיוורת.** `bina-ui.css` ו-`bina-table.css`: **0** media queries מבוססי-רוחב
  ו-**0** `pointer:coarse`. כפתור bina-ui הוא **29px** (`bina-ui.css:107-108`), `.bt-pgbtn` **26px**
  (`bina-table.css:137-139`), `.bt-act` **26px**. כל אפליקציה שמשתמשת בערכה מקבלת בקרות של 26–29px
  על מסך מגע.
* **`.table{width:100%}` ב-`bina-ui.css:126-127` בלי שום עוטף `overflow-x`** — טבלה עם עמודות רבות
  לא יכולה להיות צרה מה-min-content שלה ותדחוף את העמוד. הפתרון **קיים ב-spec ולא הועבר למקור**:
  `digital-office/sim/overlay/responsive.js` (‏`table{display:block;max-width:100%;overflow-x:auto}`
  ≤820px).
* **ניווט הטלפון מקודד קשיח ארבעה מזהי layer 3:** `app.js:299` — `["drive","mail","chat","incoming"]`.
  חמש האפליקציות הפעילות האחרות (computers/sites/domains/telegram-tv/git) נגישות בטלפון **רק**
  דרך כפתור "עוד" שפותח את לוח הפקודות. `chat` מבוטל, כלומר בפועל 3 אריחים מתוך 9.
* **`.bizform{grid-template-columns:1fr 1fr}` (`style.css:329`) לא מכוסה** ב-`@media (max-width:640px)`
  (שם מטופל רק `.cw-grid`) ⇒ ~153px לשדה בטלפון.
* **4 שימושים חיים ב-`vh`** שנשארו למרות שהקובץ עצמו כותב ב-`:112` "`100dvh`, not `100vh`":
  `.hlist{max-height:52vh}` (`:222`), `.modal.wide{max-height:88vh}` (`:266`), `.pal-ov{padding-top:12vh}`
  (`:376`), `.pal-list{max-height:52vh}` (`:379`). רק `#app` תוקן (`:114`).
* **אין `env(safe-area-inset-*)` בכל הפלטפורמה** (0 מופעים), וה-`viewport` meta בלי
  `viewport-fit=cover` (`index.html:5`) — הסרגל התחתון יושב מתחת ל-home-indicator באייפון.
* **הקונסול לא מגדיר `line-height`** (`style.css:109`) בזמן ש-`bina-ui.css:54` מגדיר `1.5` —
  המעטפת וה-iframe שבתוכה רצים בשני גבהי שורה על אותו מסך.
* **אין בקרת גודל טקסט למשתמש:** `app.js` — 0 מופעי `fontSize`; מסך ההגדרות היחיד
  (`desktop.js:1390-1412`) מציע רקע, תפריט, מסילות, היסטוריה ומספר חלונות — **לא גודל טקסט**. זה
  בדיוק ההפך מהציר של בינה (§2.5).
* **באג RTL מוחשי:** `desktop.css:202-204` — `.dk-col.two-up .view{left:0; border-inline-end:1px …}`
  מערבב פיזי עם לוגי; ב-RTL הקו המפריד נופל על הקצה החיצוני במקום בין שני הפנלים. באותו קובץ
  (`:173-174`) `side-l`/`side-r` מפורשים דווקא **פיזית** — שתי סמנטיקות לאותו שם.
  (`desktop.css` מכיל 25 מתוך 31 המאפיינים הפיזיים בקונסול.)

---

## 4. הפער — מנגנון מול מנגנון

| # | מנגנון של בינה | מה יש לנו | ההשפעה בפועל | מאמץ לסגור |
|---|---|---|---|---|
| 1 | מסגרת `overflow:hidden` + עמודות `min-width:0` | קיים בקונסול, חסר באפליקציות | דף שנגלל אופקית / תוכן שנמחץ ל-114px | **בינוני** |
| 2 | `computeColumns` + `ResizeObserver` | `matchMedia`=0 בכל האפליקציות | הסרגל לא מתקפל אף פעם; הרוחב לא מגיב לחלון המקונן | **בינוני** |
| 3 | "צר" = overlay + rail | מסילה+bottom-nav בקונסול בלבד | אפליקציה ב-390px חסרת ניווט | **בינוני** |
| 4 | 91 טוקנים סמנטיים | 16 משותפים; 48 מול 28 בשתי קבוצות סותרות | dark לא עובד; גלולות נשארות בהירות; שני ערכי `--radius-sm` | **נמוך** (יש כלי) |
| 5 | ציר גופן | אין סקאלה ואין בקרה למשתמש | 16–52 גדלים אד-הוק; טקסט לא גדל עם ההגדרה | **נמוך** |
| 6 | משמעת אנטי-גלישה | 121 מול 238 (`min-width:0`) — ומתוכם 90 בשלוש אפליקציות בלבד | "נשבר בגודל" — התסמין שהבעלים רואה | **גבוה** (רוחבי) |
| 7 | 9 שבירות + 10 קונטיינר | 14 ערכי רוחב, 3 קונטיינר | התאמה לפי החלון ולא לפי המקום | **נמוך** |
| 8 | חוזה גודל לכל רכיב | טבלאות/תפריטים בלי `max`/`min`; `.table{width:100%}` בערכה בלי עוטף | 5 טבלאות לא עטופות ב-sites, 7 מ-9 ב-domains | **בינוני** |
| 9 | `pointer:coarse` כברירת מחדל | 3 שורות; 0 בערכת העיצוב | 26–37px באצבע | **נמוך** |
| 10 | שכבת RTL מבודדת | אין; bidi אד-הוק; 25 `left/right` פיזיים ב-`desktop.css` | 0 מאפיינים פיזיים (טוב), אבל בידוד לא אחיד ובאג קו-מפריד | **נמוך** |
| 11 | CSS מבודד לכל יחידה | גיליון מונוליטי לכל אפליקציה | 229KB בתוך HTML; שניים זהים בייט-בייט | **גבוה** (לא מומלץ) |
| 12 | boot בלי הבהוב | חלקי | הבהוב dark→light בטעינה | **נמוך** |
| 13 | מדידה מובנית (הפריסה נמדדת בכל שינוי) | הכלי קיים (CDP + flow-qa + פרופילים) ואינו מחווט ל-CI | אין דרך לדעת מה שבור בלי להסתכל | **נמוך** |

---

## 5. מה שכבר נכון בלשכה ואסור לזרוק

1. **G27 + `theme-tokens.css`** — המנגנון לחלוק טוקנים בין אפליקציות עצמאיות **קיים, מתועד
   ומיושם** (`--fix` מפיץ, השער נכשל על דריפט). זה בדיוק ה"מכנה המשותף" של בינה, בגרסה שמתאימה
   לארכיטקטורה שלנו (כל אפליקציה ניתנת להתקנה בנפרד ⇒ אין `<link>` משותף).
2. **`lint_viewport_units.py`** — החוק של בינה כתוב אצלנו מילה במילה: *"המעטפת מחזיקה את ה-viewport;
   כל מה שמתחת מקבל את הגובה שנתנו לו"*. הוא חל על indox בלבד.
3. **`view-profiles.yaml` + `capture.py` + `pixel-diff.py` + `flow-qa.py`** — תשתית צילום ותקינות
   אמיתית, כולל **`CSS.startRuleUsageTracking`** דרך CDP (`capture.py:371`) — כלומר יש דפדפן אמיתי
   שאפשר למדוד בו גלישה. חסר רק השער.
4. **`indox`** — קונטיינר-קווריז עם fallback, "גולל אחד בלבד", `100dvh`, טבלה שנגללת בתוך מכל,
   `container-type:inline-size` ו-`@supports not (container-type)`. זה המודל ליישום.
5. **`telegram-tv`** — היחידה שמתעדת **מדידה** ולא הערכה (`style.css:340-342`: "העמוד היה 66px רחב
   מהמסך של טלפון, והאשמים היו חיפוש של 210px וצ'יפ שסירב להתכווץ"), עם `clamp()`, `aspect-ratio`,
   RTL נכון ב-JS, ובדיקת ניגודיות (3.4:1 → 4.9:1).
6. **`bina-table`** — עטיפת טבלה משותפת (RevoGrid) עם אסטרטגיית RTL מתועדת ("מנוע LTR, טקסט RTL")
   ו"כרטיס סגור: toolbar + grid + footer בפאנל אחד". 4 אפליקציות טוענות אותה — **אבל לפחות
   ב-`computers` היא נטענת ואינה בשימוש** (0 מחלקות `bt-` ב-`app.js`; ~51KB נכסים מתים), ואין שער
   שמסנכרן את ארבעת העותקים זה עם זה.
7. **הקונסול עצמו** — מסילה 62px בטווח 641–1024, bottom-nav בגובה 60px מתחת ל-640 עם
   `.embed{inset:0 0 60px 0}`, `pointer:coarse` ל-44px — ההתנהגות הרספונסיבית הנכונה כבר קיימת
   בשכבת המעטפת.
8. **`themeIntoFrame()`** (`console/static/app.js:249-251`) — הקונסול **כבר** מזריק `data-theme`
   למסמך של האפליקציה המוטמעת (same-origin). כלומר כל מה שצריך כדי ש-dark יעבוד הוא שהאפליקציה
   תחזיק את הבלוק — לא שינוי בקונסול.

---

## 6. מה **לא** להעתיק

| לא להעתיק | למה |
|---|---|
| React + 37 תוספים + CSS-in-JS פר-תוסף | rewrite של כל ה-frontend; הרווח (בידוד) לא שווה את המחיר בלשכה |
| 380 טוקנים | 91 סמנטיים מכסים את הצרכים; 45 מספיקים לנו (נספח א') |
| יישור פיזי (`left:`, `border-right`) | אנחנו **חזקים יותר** מבינה כאן — כמעט כל האפליקציות כבר לוגיות; את 25 ה-`left/right` שנשארו ב-`desktop.css` צריך לתקן, לא לאמץ |
| `computeColumns` עם 400px מרכז מוגן | הערכים של deepsuite; אצלנו המספרים צריכים להיגזר מהפריסות שלנו |
| גיליון גלובלי מקושר | שובר את "כל אפליקציה ניתנת להתקנה בנפרד" — העותק + G27 הוא הפתרון הנכון |
| ב-JS: `window.resize` | בינה משתמשת ב-`ResizeObserver` על הפריים — זה מה שמתאים לנו (iframe!) |

---

## 7. תוכנית מעבר — שישה שלבים

### שלב 0 — למדוד לפני שנוגעים (חצי יום)
**מה:**
1. בדיקת גלישה ב-`scripts/ui-coverage/capture.py` שמריצה `Runtime.evaluate` ומדווחת לכל אפליקציה ×
   פרופיל: `documentElement.scrollWidth > clientWidth`, ומניין אלמנטים עם `scrollWidth > clientWidth+1`.
2. **לחווט את `digital-office/sim/flow-qa.py` ל-CI** — הוא כבר בודק בדיוק את ארבעת המדדים הנכונים
   (`hOverflow<=2` ב-`:534`, `spills` ב-`:536`, double v-scroll ב-`:538`) ויש לו `--mobile` ל-390×844
   (`:556-558`). אפס אזכורים שלו ב-`.github/workflows/*.yml`.
3. **רפרנס pixel-diff ב-390px** — כל 75 צילומי הייחוס הם 2880×1800 דסקטופ בלבד.
**למה:** בלי זה אין דרך להוכיח שיפור, וכל "תיקון" הוא דעה.
**אימות:** הפלטה על 24 אפליקציות × 3 פרופילים; היום אי אפשר לדעת מה שבור בלי להסתכל.

### שלב 1 — להרחיב את רשימת ה-TARGETS של G27 (שעה)
**מה:** להוסיף ל-`scripts/refactor/theme-token-lint.py:41` את `machine`, `notifications`,
`any-concurrency`, `connections`, `app-management`, `indox`, `telegram-tv`, `apitools`
ול-`FONT_TARGETS` את השלוש שלא שם; ואז `python3 scripts/refactor/theme-token-lint.py --fix`.
בנוסף — להוסיף ל-G27 בדיקה שכל טוקן **שמוגדר** גם **בשימוש** (הגלולות של `bina-ui.css:92-104`
כותבות hex קשיח בעוד `--warn-soft` מוגדר ב-`:49` עם 0 שימושים).
**למה:** זה מוסיף dark + מקצה ~50% מהכפילות ב-CSS של שש אפליקציות, בעלות של רשימה אחת.
**אימות:** `theme-token-lint.py` ירוק; קונסול במצב dark ⇒ כל האפליקציות כהות.
**אזהרה:** `--fix` ידרוס פלטות dark ידניות (למשל `notifications` `#0f1613`) — וזו התוצאה הרצויה.

### שלב 2 — לאחד את שתי מערכות הטוקנים ל-~45 (יום)
**מה:** להרחיב את `platform-base/bina-ui/theme-tokens.css` (נספח א') ולהפיץ ב-`--fix`; **ולאחד**
את 48 הטוקנים של `console/static/style.css` עם 28 של `bina-ui.css` לקבוצה אחת — כולל הכרעה בין
`--radius-sm:8px` (`style.css:15`) ל-`9px` (`bina-ui.css:20`).
**למה:** בלעדיו אין מה שיספוג את הצבעים הידניים — 123 hex ב-mail, 103 ב-indox, 71 ב-drive,
41 ב-data-management, 30 ב-`bina-ui.css`.
**אימות:** ספירת hex בכללים לפני/אחרי; כל אפליקציה יורדת לאפס-כמעט.

### שלב 3 — ספריית מסגרת + פותר עמודות משותף (2–3 ימים)
**מה:** `platform-base/bina-ui/bina-layout.js` + בלוק CSS מסומן `@bina-layout:start/end`,
מועתק לכל אפליקציה כמו הטוקנים ומגודר באותו רעיון:
```js
BinaLayout.frame(rootEl, { sidebar:[264,420], collapse:1024, rail:56, centerMin:400, rightbar:[300,0.7] })
BinaLayout.solve({ width, sidebar, rightbar })   // → {sidebar, center, rightbar}
// מזריק --app-w, ומדליק data-narrow / data-rail על <html> של האפליקציה
```
עם בלוק CSS שמגדיר: `#app{display:grid;grid-template-columns:var(--col-side) minmax(0,1fr) var(--col-right);
height:100dvh;overflow:hidden}`, `min-width:0` על כל עמודה, גולל יחיד, ומסילה/overlay במצב צר.
**למה:** זה המנגנון שסוגר פערים 1–3 ו-7 בבת אחת, והוא ~120 שורות.
**אימות:** `./bbox ui-map --profile mobile` — אפס גלישה, וכל אפליקציה נגישה ב-390px.

### שלב 4 — תיקוני פריסה נקודתיים, מהגרוע לטוב (3–4 ימים)
לפי סדר: `any-concurrency` (82px לציור) → `sites` (גרף שנחתך, 5 טבלאות) → `mail` (rail 252px)
→ `my-docs` (nav + kpi-strip) → `app-management` (אפס MQ, 72 hex) → `machine` (`min-width:960px`)
→ `domains` (4 טבלאות) → `bina-ui.css` (`.table` בלי עוטף).
לכל אחד: בלוק שבירה יחיד, `data-th` לכרטוס טבלאות (הדפוס מ-`computers:145`), ו-`overflow-x:auto`
על המכל.
**אימות:** הבדיקה משלב 0 על הפרופיל mobile, לפני/אחרי.

### שלב 5 — מגע, מיקוד, טיפוגרפיה ובקרת גופן (יום-יומיים)
* `pointer:coarse` ל-44px **בכל** האפליקציות **וגם ב-`bina-ui.css`/`bina-table.css`** (שם: 0 מופעים,
  וכפתור 26–29px). היום יש 3 שורות כאלה בכל הפלטפורמה (`console/static/style.css:437-441`),
  והן מכסות 7 מחלקות בלבד.
* `:focus-visible` גלובלי אחד לכל אפליקציה (ל-indox אין); `--focus` שאינו `--accent-soft` —
  כיום טבעת מיקוד בניגודיות ~1.05:1, כלומר בלתי נראית.
* **סקאלת טיפוגרפיה:** לאחד 16 הגדלים של הקונסול (10…22, בחצאי פיקסל) ו-16 של mail לשש דרגות,
  ולהוסיף את **ציר הגופן של בינה** (`--content-font-size` + `--content-font-delta`) לבקרת ההגדרות.
  הקונסול גם לא מגדיר `line-height` בזמן ש-bina-ui מגדיר `1.5`.
* `env(safe-area-inset-bottom)` ל-`.bottomnav` + `viewport-fit=cover` ב-`index.html:5`.
* החלפת 4 שימושי ה-`vh` שנשארו בקונסול ל-`dvh`; `<meta viewport>` ל-`connections`.
* **ניווט הטלפון לא יקודד קשיח** `["drive","mail","chat","incoming"]` (`app.js:299`) — לגזור אותו
  מ-`.generated/registry/console.modules.yaml` (אותו מקור שהאריחים נבנים ממנו).

### שלב 6 — הפיכת ה-lint של ה-viewport לגלובלי (חצי יום)
`scripts/ops/lint_viewport_units.py` — מהרחבת ה-scope שלו מחדר המסמכים של indox לכל 24 המשטחים,
עם רשימת allowlist ל-`.app-shell` בכל אפליקציה.

### שלב 7 (אופציונלי, אחרי שהשערים ירוקים) — לסגור את פער המדידה
לחווט את `live-ui-map.py` ל-`bbox ui-map` במקום `run_capture.sh`; לתקן את ההיסט ב-
`pixel-diff.yaml:82-93`; להסיר את `my-docs` מזיווגי pixel-diff ו-code-coverage כל עוד הוא מושבת;
ולהוסיף את `platform-base/console/test_app.py` ואת `sim-live-parity.py --all` ל-CI.

---

## 8. השערים שצריך להוסיף (וכל אחד מהם הוא תנאי לסיום)

| שער | מה בודק | מבוסס על |
|---|---|---|
| `overflow-probe` | לכל אפליקציה × פרופיל: אין גלישה אופקית של המסגרת; מניין אלמנטים גולשים | `capture.py` (CDP קיים) |
| G27 מורחב | כל משטח נושא את בלוק הטוקנים ומתעדכן מ-`--fix`; **וטוקן מוגדר = טוקן בשימוש** | `theme-token-lint.py` |
| G27 רוחבי | גם `desktop.css`, `bina-table.css`, ו-5 ה-frontends של layer 2 | `theme-token-lint.py` |
| `flow-qa` ב-CI | 4 מדדי הפריסה (`hOverflow`, `spills`, double-scroll, תוכן) × 3 פרופילים | `digital-office/sim/flow-qa.py` |
| G4 עם רפרנס נייד | צילומי ייחוס ב-390px ו-834px, לא רק 2880×1800 | `ui-pixel-diff.py` |
| `layout-contract-lint` | כל אפליקציה עם `module.embed` טוענת `bina-layout` ומצהירה נקודת שבירה | חדש (בסגנון `theme-token-lint`) |
| `viewport-units` גלובלי | אין `100vh` מחוץ ל-`.app-shell` | `lint_viewport_units.py` |
| `touch-targets` | אין כפתור < 44px תחת `pointer:coarse` | חדש (סריקת CSS) |
| `bidi-lint` | אין `text-align:left\|right` בלי `direction:ltr` מלווה; אין `left:`/`right:` בלי הצדקה | חדש (סריקת CSS) |
| `css-lint` | תחביר CSS בכלל (היום G12 בודק `.py` בלבד) + חיווט `charset-first-lint.py` | חדש / `run-gates.py:271` |

---

## 9. נספחים

### נספח א' — מיפוי הטוקנים המוצע (16 → ~45)

לשמור על השמות הקיימים (אף אפליקציה לא נשברת) ולהוסיף:

```
צבע:   --surface-3 · --ink-2 --ink-3 --ink-dim · --line-2 --line-solid · --accent-ink
       --ok --warn --danger --info (מוצקים) + --ok-ink --warn-ink --danger-ink --info-ink
       --scrim (מסכת overlay) · --focus (טבעת מיקוד)
משטח:  --elev-1 --elev-2 --elev-3 --elev-stroke   (בינה: elevation-{panel,prominent,soft,stroke})
גופן:  --font (קיים) · --font-mono
       --font-caption --font-body --font-strong --font-title --font-display  (shorthand מלא:
       weight size/line-height family — כמו --dsw-font-base-16)
       --content-font-size --content-font-delta   (ציר ההגדלה של המשתמש)
תנועה: --ease --dur-fast --dur --dur-slow        (בינה: .1s/.2s/.3s + cubic-bezier(.4,0,.2,1))
גלילה: --scrollbar-thumb --scrollbar-thumb-hover --scrollbar-width
```

### נספח ב' — נקודות השבירה

| | בינה | הלשכה (מומלץ לאחד) |
|---|---|---|
| מסך | 480 · 560 · 680 · 720 · 760 | 520 · 640 · 820 · 1024 |
| קונטיינר | 271 · 360 · 375 · 460 · 479 · 583 · 620 · 687 · 900 | לפי רכיב (טבלה, כרטיס, גרף) |
| ציר | 9 שבירות ב-320KB | **14 ערכי רוחב** ב-31 שאילתות: 520, 640, 641, 680, 700, 720, 760, 800, 820, 900, 1024, 1100, 1120, 1121 |
| מה שמשלם על זה | פותר ב-JS + `min-width:0`×238 + 10 קונטיינר | `flex-wrap:wrap` (מסדר מחדש במקום לכווץ) |

### נספח ג' — הפקודות שמאפשרות לשחזר את המדידה

```bash
# כל ה-CSS שמוזרק על ידי תוספי בינה (107 גיליונות) — לחילוץ מחדש:
python3 - <<'PY'
import re,glob,json
for f in glob.glob("/opt/bina/harness/profile/node_modules/.pnpm/@deepseek-ai+dsh-client-ui-*/node_modules/@deepseek-ai/*/lib/client.js"):
    s=open(f).read()
    for m in re.finditer(r'const css(?:\$\d+)? = ("(?:[^"\\]|\\.)*");', s):
        print(json.loads(m.group(1)))
PY

# הטוקנים של בינה (פלטה + סמנטי, light + dark):
#   dsh-client-ui-theme/lib/client.js  →  design_platform_css_default / gradient_shadow_text_css_default
# הפריסה:
#   dsh-client-ui-layout/lib/client.js:36-44 (computeColumns), :208-232 (ResizeObserver), :338-395 (store)

# בלשכה — ספירת media queries ומדדי גלישה:
python3 -c "
import re,glob
for f in glob.glob('/workspace/office/{apps,platform-base}/*{,/*}/{static,app/webapp/src}/*.css',recursive=True):
    s=open(f).read(); print(f, len(s), len(re.findall(r'@media',s)))"
```

---

### נספח ד' — השורה התחתונה

בינה לא "יפה בכל מצב" בגלל עיצוב טוב. היא יציבה מפני שארבעה חוקים נאכפים בכל שכבת קוד:

1. **הדף לא נגלל; פאנל נגלל.** (מסגרת `overflow:hidden`, `height:100%`, גולל אחד לכל אזור)
2. **רוחב נמדד ומחושב, לא מנוחש.** (`ResizeObserver` על הפריים + `computeColumns` עם טווחים וסדר עדיפויות)
3. **אף אלמנט אינו מניח שיש לו מקום.** (`min-width:0` ×238, `max-width:min(…,100vw-…)`, `nowrap`+`ellipsis`)
4. **צבע וגודל באים מהמערכת, לא מהרכיב.** (91 טוקנים סמנטיים × light/dark + ציר גופן)

הלשכה כבר אימצה את החוק הרביעי (G27) ואת הראשון (`lint_viewport_units.py`) — כל אחד על משטח אחד.
המהלך הגדול אינו לכתוב מחדש, אלא **להרחיב את מה שקיים** ולהשלים את החסר: פותר הרוחב.
