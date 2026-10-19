# המרכז — screen reproduction contract

You reproduce ONE OR MORE screens of an RTL Hebrew business platform as **1:1 HTML** from provided screenshots.
Each screen is a self-contained block:

```html
<section class="screen" data-screen="SCREEN_ID"> ... full viewport markup ... </section>
```

Output ONLY the `<section>...</section>` blocks (no <html>, <head>, <style>, no markdown fences). All CSS classes below already exist globally — reuse them. You MAY add small inline `style="..."` for screen-specific tweaks or a screen-scoped `<style>` INSIDE the section using a unique prefix class. Never redefine the global classes.

Viewport is 1440×900, `dir="rtl"`, font Heebo. Match Hebrew text, numbers, colors, and layout to the screenshot as closely as possible.

## Palette (CSS vars, already defined)
--green:#0e9f6e  --green-d:#0b7a58  --green-dd:#085d40  --sidebar:#0f2a22
--hero1:#0e5e49 --hero2:#0b7b5d  --bg:#f4f6f5 --card:#fff --line:#e6eae8
--muted:#6b7c76 --amber-bg:#fdf1dc --amber-ink:#b45309 --blue:#2563eb --red:#dc2626 --purple:#7c53c9 --gold:#c07f16

## המרכז shell (use for INTERNAL app screens: dashboard/mydocs/indox/mail/notifications/connections)
Paste this shell; set the active nav item by adding class `on`; put the page title in `.hm-title`; put page body inside `.hm-body`.

```html
<section class="screen" data-screen="SCREEN_ID">
<div class="viewport">
  <aside class="hm-side">
    <div class="hm-brand"><div class="logo">מ</div><div class="bt"><b>המרכז</b><span>מערכת ניהול העסק</span></div></div>
    <nav class="hm-nav">
      <div class="hm-sec">ראשי</div>
      <a data-nav="dashboard"><span>לוח בקרה</span><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg></a>
      <div class="hm-sec">עסק</div>
      <a data-nav="mydocs-dash"><span>מסמכים שלי</span><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg></a>
      <a data-nav="drive-root"><span>דרייב</span><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 7a2 2 0 0 1 2-2h4l2 3h8a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg></a>
      <a data-nav="mail-inbox"><span>מייל</span><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/></svg></a>
      <a data-nav="indox-root"><span>מסמכים נכנסים</span><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5 5h14l3 7v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-6z"/></svg></a>
      <a data-nav="wadmin-dashboard"><span>בוט ווצאפ</span><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 11.5a8.38 8.38 0 0 1-8.5 8.5 8.5 8.5 0 0 1-3.8-.9L3 21l1.9-5.7a8.5 8.5 0 1 1 16.1-3.8z"/></svg></a>
      <div class="hm-sec">תשתית</div>
      <a data-nav="kabil"><span>כל‑מקביל</span><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg></a>
      <a data-nav="notifications"><span>התראות</span><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/></svg></a>
      <a data-nav="machine"><span>מכונה</span><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="6" rx="1"/><rect x="2" y="9" width="20" height="6" rx="1"/><rect x="2" y="15" width="20" height="6" rx="1"/></svg></a>
      <a data-nav="apps"><span>אפליקציות</span><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg></a>
      <a data-nav="feature-validation"><span>אימות מערכת</span><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/></svg></a>
      <div class="hm-sec">הגדרות</div>
      <a data-nav="connections-auth"><span>חיבורים ומפתחות</span><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="8" cy="15" r="4"/><path d="m10.85 12.15 8.15-8.15 2 2-2 2 2 2-3 3-2-2-2 2"/></svg></a>
      <a data-nav="console-install"><span>מסך התקנה</span><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-2.82 1.17V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 8 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 8.6a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09A1.65 1.65 0 0 0 15 4.6a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9z"/></svg></a>
    </nav>
    <div class="hm-foot"><small>מחובר/ת</small><b>authentik Default Admin</b></div>
  </aside>
  <main class="hm-main">
    <div class="hm-top">
      <div class="grp"><div class="hm-title">PAGE TITLE</div><button class="hm-burger">☰</button></div>
      <div class="grp"><div class="hm-search"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m21 21-4-4"/></svg><span>חיפוש</span><span class="kbd">Ctrl K</span></div></div>
      <div class="grp left"><span style="color:var(--muted);font-size:13px">SUBTITLE TEXT</span><div class="pill-amber">⚙ 7 שלבי התקנה</div></div>
    </div>
    <div class="hm-scroll"><div class="hm-body">
      <!-- PAGE BODY HERE -->
    </div></div>
  </main>
</div>
</section>
```

Notes:
- `.hm-top` order visually: right = title+burger, center = search, left = subtitle + amber install pill.
- SUBTITLE differs per app (e.g. dashboard: "", mydocs: "ניהול מסמכים עסקיים", indox: "עיבוד מסמכים אוטומטי (INDOX)", mail: "תיבת דואר עסקית", connections: "ניהול מפתחות גישה וחיבורים", notifications: "מרכז התראות").
- For apps with a secondary tab bar (mydocs, indox), put a `.biz-bar` with `.biz-tabs` as the FIRST child inside `.hm-scroll` (before `.hm-body`). mydocs tabs: לוח בקרה / מסמכים / לקוחות / פריטים / הגדרות עסק, plus a `+ מסמך חדש` primary button on the far right of the bar. indox tabs (dark underline style, akadmin): לוח בקרה / מסמכים / סנכרון / הגדרות / בדיקות / חילוץ מסמכים, with `akadmin` label at the right.

## Components (classes)
- Hero banner: `<div class="hero"><h2>..</h2><p>..</p></div>`
- Stat row: `<div class="stat-row" style="grid-template-columns:repeat(5,1fr)"> <div class="stat acc-g"><div class="n">295</div><div class="l">הודעות דואר</div></div> ...</div>` (variants: acc-g/acc-a/acc-b top bar; number color .n.g/.a/.b/.r; feature card `.stat.stat-big`)
- Card: `.card` with `h3` title.
- App tiles grid: `.tiles` > `.tile` (`.ti` icon slot, `<b>`, `<span>`). External tile add class `ext` and `↗` before name.
- Buttons: `.btn`, `.btn-primary`, `.btn-danger`, `.btn-ghost`, `.btn-sm`.
- Segmented filter pills: `.segs` > `.seg` (active `.seg.on`), count `<span class="c">9</span>`.
- Tables: `.tbl-wrap` > `table.tbl` with `th`/`td` (right aligned). Status `.badge .badge-gray/green/blue/amber/red`. Search field `.searchbox`.
- Horizontal bar chart rows: `.bar-line` > `.lab` + `.bar-track`>`.bar-fill` (set width%, color via inline style) + `.bar-num`.
- Live pill: `<span class="live"><span class="dt"></span>חי</span>`.
- Two-col grid: `.g2`.

## EXTERNAL tool screens (authentik, portainer, n8n, supabase, redis, glitchtip, browser42, machine, wadmin, console)
These are NOT המרכז apps — they have their OWN full-screen chrome. Reproduce them self-contained inside `<section class="screen" data-screen="ID"><div style="height:100vh;overflow:auto;...">…</div></section>` using their real colors from the screenshot. Use your own scoped inline styles. Match faithfully.

Return only the `<section>` block(s).
