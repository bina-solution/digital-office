# המרכז — Platform Navigation & Layout Design

Research-backed navigation and layout spec for **המרכז** (the console): a unified Hebrew
RTL business platform (Bina design system) that hosts many apps in one shell — dashboard,
פנקס (documents/invoicing), דרייב, מייל, מסמכים נכנסים (INDOX), בוט ווצאפ, כל מקביל,
התראות, מכונה, אימות, חיבורים, install.

**Status:** design reference for the next implementation pass. No app code changed by this doc.
**Author pass:** 2026-07-13, branch `release-v2-lockin`.
**Revision:** **v2 — 2026-09-25.** §1g/§1h added (sizing/targets/motion by the numbers, and the
10/20/40/80-item strategy); §2 rewritten as a **measured** baseline of the live console; §3.1, §3.4
and §3.7 re-bound to the shipped CSS and re-decided; §3.8–§3.12 added (overflow, the embed-aware
auto-collapse state machine, the keyboard/AT contract, motion, failure-mode invariants); §4 replaced
by a phased plan with acceptance tests; §5 lists what this doc deliberately does **not** decide
alone. **v1's section numbers are preserved on purpose** — `ai/context/archive/indox-pre-2026-09/
indox-experience-design.md` cites §1f, §3.2, §3.5 and §3.6 by number, and §3.2/§3.3/§3.5/§3.6 are
carried over unchanged. The raw, link-per-claim evidence behind the v2 numbers is
[`sidebar-research.md`](sidebar-research.md).
**TL;DR recommendation (opinionated, one pattern):** evolve the current fixed 238px dark rail into a
**collapsible dark icon rail** (VS Code / Slack model): full-width labels on the dashboard and
launcher, auto-collapsed to a 60px icon-only rail whenever an app is embedded, plus a
**⌘K / Ctrl+K command palette** as the cross-app accelerator. Embedded apps **never** render a
second vertical rail — their own nav is always a **horizontal contextual tab-strip** (section-apps)
or a **light in-content side-panel** (tool-apps). Mobile (<640px) collapses the rail into a
**bottom tab bar** for the top 4–5 destinations + a "more" sheet. This keeps exactly one dark
navigation surface on screen at all times and fixes the remaining cramped-phone gap.

---

## 1. Research — 2024–2026 best practices

### 1a. Primary vs secondary navigation for a shell hosting many apps

The dominant pattern across modern multi-app workspaces (VS Code, Slack, Linear, Notion, Discord)
is the **app-shell**: a fixed vertical column on the leading edge + a flexible main column, with the
whole app living in that grid ([DEV — Linear sidebar clone](https://dev.to/dev48v/i-cloned-linears-sidebar-in-50-lines-of-html-one-file-zero-npm-40ej)).
For a shell that hosts *many distinct apps* (our case), the strongest variant is the **two-tier VS
Code / Slack model**: a narrow **icon rail** (primary — switches between apps/workspaces) plus a
**contextual panel** that belongs to the currently-selected app. This gives each app room for its own
navigation without competing with the shell.

Key guidance:

- A **navigation rail** is a narrow vertical sidebar of icon+label items; exposed by default (no
  hamburger), it lowers interaction cost but adds some cognitive load, so it should carry only
  primary destinations ([UXPin — Mobile Navigation 2026](https://www.uxpin.com/studio/blog/mobile-navigation-examples/),
  [Material — Navigation patterns](https://m1.material.io/patterns/navigation.html)).
- **Consistency across the suite is worth more than any single clever layout.** Reported: user
  satisfaction rises when interface elements are consistent across a product family, and users
  prefer uniform layouts across apps in the same suite ([DeveloperUX — Multi-platform internal tools](https://developerux.com/2026/05/18/improving-multi-platform-navigation-internal-tools/)).
- Professional/dense software (IDEs, design tools, admin consoles) favors **persistent** navigation
  over hidden/hamburger nav to reduce cognitive load and speed repeat actions
  ([Navbar Gallery — Sidebar examples 2026](https://www.navbar.gallery/blog/best-side-bar-navigation-menu-design-examples)).
- A **command palette (⌘/Ctrl+K)** is the recognized accelerator layer for object/page navigation in
  action-heavy enterprise products — keyboard-first, groups results into buckets (commands / pages /
  recent), teaches its own shortcuts. GitHub removed its palette in July 2025 and reversed within
  five days after power users objected — a caution that once added it becomes load-bearing, and that
  **discoverability** (a visible ⌘K chip) matters ([Mobbin — Command Palette](https://mobbin.com/glossary/command-palette),
  [UX Patterns for Developers — Command Palette](https://uxpatterns.dev/patterns/advanced/command-palette),
  [buildmvpfast — Cmd+K guide](https://www.buildmvpfast.com/blog/how-to-add-cmd-k-command-palette-saas-2026)).

**Verdict:** icon rail (primary) + contextual per-app nav (secondary) + command palette (accelerator).
Top-nav-only doesn't scale to ~12 apps; hamburger-only hides the estate and is wrong for a daily-driver
admin tool.

### 1b. "Double navigation" done right — when two levels are justified

Two nav levels are legitimate **only when they sit at different levels of the hierarchy and read as
different levels** — e.g. Slack's workspace rail (which workspace) + channel sidebar (what inside it),
or VS Code's activity bar (which tool) + side panel (what inside the tool). The failure mode — the
one we already hit — is **two peers**: two vertical rails of similar weight, so the user can't tell
which owns navigation. Linear's 2024–25 redesign is instructive: they explicitly worked to *"increase
the hierarchy and density of navigation elements"* and aligned labels/icons/buttons vertically and
horizontally in the sidebar and tabs to **reduce visual noise**
([Linear — How we redesigned the UI, part II](https://linear.app/now/how-we-redesigned-the-linear-ui)).
Slack's Sept-2025 redesign similarly consolidated tabs and replaced ambiguous icons with plain-language
labels to remove "visual excess" ([Slack — new design overview](https://slack.com/help/articles/16764236868755-An-overview-of-Slacks-new-design)).

**Rules that make two levels legible:** (1) different **visual weight** — primary is dark/elevated,
secondary is light/in-content; (2) different **orientation** where possible — vertical primary,
horizontal secondary tabs; (3) different **granularity** — primary = which app, secondary = which
view inside it; (4) never two dark vertical rails side by side.

### 1c. Responsive strategy desktop → tablet → mobile

- Most sites do best with **3–5 primary breakpoints**; a common set is S 480 / M 768 / L 1024 /
  XL 1366. **1024px is the typical point where a sidebar is introduced**; below it, complex nav
  collapses ([BrowserStack — Breakpoints 2025](https://www.browserstack.com/guide/responsive-design-breakpoints),
  [Framer — Responsive breakpoints 2026](https://www.framer.com/blog/responsive-breakpoints/)).
- The adaptive nav progression is well established: **bottom tab bar on phone → navigation rail on
  tablet → full sidebar on desktop**, i.e. the same destinations re-projected per width
  ([UXPin — Mobile Navigation 2026](https://www.uxpin.com/studio/blog/mobile-navigation-examples/)).
- **Bottom navigation** puts primary options in the thumb zone and is recommended by both Material
  and Apple HIG for primary mobile nav; it suits 3–5 top destinations
  ([Material — Navigation patterns](https://m1.material.io/patterns/navigation.html)).
- Touch targets: **44×44pt (Apple) / 48×48dp (Material)** minimum ([UXPin](https://www.uxpin.com/studio/blog/mobile-navigation-examples/)).

### 1d. Dense data-table UX

- **Sticky header** keeps column context on scroll — but a header that jitters/detaches mid-scroll is
  worse than none; test on real content ([Pencil & Paper — Enterprise data tables](https://www.pencilandpaper.io/articles/ux-pattern-analysis-enterprise-data-tables)).
- **Density:** offer a compact density mode with sane type sizes rather than shrinking the font to
  cram rows ([Pencil & Paper](https://www.pencilandpaper.io/articles/ux-pattern-analysis-enterprise-data-tables)).
- **Bulk actions:** a **floating contextual toolbar** appears when rows are selected (above the
  selection or pinned to the bottom); works well responsively and cuts cursor travel
  ([Pencil & Paper](https://www.pencilandpaper.io/articles/ux-pattern-analysis-enterprise-data-tables),
  [UX Design World — Table actions](https://uxdworld.com/best-practices-for-providing-actions-in-data-tables/)).
- **Filters must show active state** — a filtered table that looks unfiltered makes people misread
  the data ([Pencil & Paper](https://www.pencilandpaper.io/articles/ux-pattern-analysis-enterprise-data-tables)).
- **Pagination vs infinite scroll:** for SaaS dashboards/data tables, **pagination (or Load-More
  hybrid)** is recommended — better performance, predictable state across filters/sorts; infinite
  scroll is for discovery/browsing feeds, not records you act on
  ([Onething — Pagination vs Infinite Scroll](https://www.onething.design/post/pagination-vs-infinite-scroll-which-is-better),
  [Medium — Pagination vs Infinite for SaaS tables](https://medium.com/@artof.anj/pagination-vs-infinite-scrolling-the-ultimate-showdown-for-saas-table-design-febfac537781)).

### 1e. Settings-page patterns

- **Horizontal tabs** at the top of a settings area to switch between sub-views is the common,
  recommended pattern; group related settings so important items are easy to find; use
  expandable/"read more" sections so users go deeper only when ready
  ([Onething — Navigation patterns](https://www.onething.design/post/top-website-navigation-design-patterns),
  [bricxlabs — Settings page UI examples](https://bricxlabs.com/blogs/settings-page-ui-examples)).
- **Search** is a fast path for users who already know the setting they want ([UXPin](https://www.uxpin.com/studio/blog/mobile-navigation-examples/)).
- **Save affordances:** designs should allow easy reversal/undo so users don't lose context — pair
  with clear affordances (buttons that read as clickable, hover/focus feedback)
  ([Gapsy — UX patterns](https://gapsystudio.com/blog/ux-design-patterns/)).

### 1f. RTL-specific navigation

- RTL is **not just a mirror of LTR** — UI elements, icons, navigation, and hierarchy all flow
  right→left, and every directional assumption needs reconsideration
  ([SimpleLocalize — RTL guide](https://simplelocalize.io/blog/posts/rtl-design-guide-developers/)).
- Sidebars/menus sit on the **right**; the cleanest implementation is DOM order + `direction:rtl`
  letting natural flow place the rail, rather than hard-coded left/right
  ([SimpleLocalize](https://simplelocalize.io/blog/posts/rtl-design-guide-developers/)).
- Use **CSS logical properties** (`margin-inline-start`, `inset-inline-start`, `text-align:start`) so
  one stylesheet serves both directions ([SimpleLocalize](https://simplelocalize.io/blog/posts/rtl-design-guide-developers/),
  [Mozilla — RTL guidelines](https://firefox-source-docs.mozilla.org/code-quality/coding-style/rtl_guidelines.html)).
- **Mirror only directional icons** (arrows, progress, back/forward, time); do **not** mirror logos,
  decorative or non-directional glyphs. Numbers, code, and phone numbers stay LTR inside RTL text
  ([SimpleLocalize](https://simplelocalize.io/blog/posts/rtl-design-guide-developers/),
  [GitHub — rtl-guidelines](https://github.com/ItielMaN/rtl-guidelines)).
- Catch regressions with **RTL/LTR screenshot diffing** and a native-speaker review pass
  ([placeholdertext — RTL testing guide](https://placeholdertext.org/blog/the-complete-guide-to-rtl-right-to-left-layout-testing-arabic-hebrew-more/)).

Our stack already does most of this right: `dir="rtl"` on `<html>`, logical properties in the Bina
CSS (`inset-inline-start`, `margin-inline-start`, `text-align:start`), and LTR-isolated numerics
(`.num{direction:ltr;unicode-bidi:isolate}`).

### 1g. Sizing, targets and motion — the numbers (2026 pass)

Every figure below is sourced; anything marked **(judgement)** is a decision, not a finding. Full
link-per-claim evidence: [`sidebar-research.md`](sidebar-research.md).

**Width**

| Source | Expanded | Collapsed |
|---|---|---|
| Material 3 standard navigation drawer | **360dp** ([spec](https://m3.material.io/components/navigation-drawer/specs)) | — |
| M3 extended rail (expressive spec) | **256dp**; spec range **220–360dp**, default 360dp | **80dp**, 96dp in expressive |
| Common product/Tailwind convention | **224px (`w-56`)** … **240px** classic fixed nav | 64–72px |
| Notion | ships **narrower than users want** — a third-party extension exists purely to widen it | — |

**Item metrics (M3, sourced):** container/destination height 64dp (56dp for a rail destination);
leading inset 16dp; active indicator **56×32dp** pill, corner-full; icon **24dp**; label **12sp**
collapsed / **14sp** expanded, active weight 700; state layer confined to the pill — hover 8%,
focus 10%, pressed 10% — while **the click target stays the whole row**.

**Denser desktop-product values (sourced as code, the Tailwind nav reference):** row ≈**36px**,
icon **20px**, gap 12px, radius 8px, label 14px. Our shipped rail is already in that family
(13.5px label, 19px icon, 33px row) — the v2 spec stays dense rather than adopting M3's airy 64dp.

**Active treatment:** treat contrast as a budget spent on content, not chrome. Linear's Mar-2026
refresh dimmed the **whole** nav, shrank icons, muted inactive text and reduced/softened separators
(["structure felt, not seen"](https://linear.app/now/behind-the-latest-design-refresh)). So: filled
8–10% tinted pill + weight, not a saturated accent block everywhere, and exactly one hairline at the
chrome↔content boundary.

**Targets (WCAG 2.2):** [2.5.8 Target Size (Minimum), AA](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html)
requires **24×24 CSS px**, or passes via a 24px-diameter spacing circle; the worked examples are
menu items of **24px height passing and 18px failing**, and 20×20 with 4px spacing passing. The
requirement is **zoom-independent** — "it fits at 100%" is not a defence. AAA 2.5.5 (44×44) is the
bar to aim at for the primary destinations.

**Motion:** M3's rail crossfades between collapsed and expanded in **200ms** — that is the anchor
number, not a style preference. Alongside it: tint transitions 80–120ms, tooltip in 300–500ms and
out **0ms**, and `prefers-reduced-motion: reduce` → **0ms** with the state still changing.

**Two hard-won implementation rules that belong with the numbers:**
1. **Animating the rail's width relayouts the iframe every frame** — the single biggest jank source
   in this shell. Animate the sidebar's own width with the content column pinned
   (`flex:1 1 auto; min-width:0`) and `contain: layout paint` on the rail; if profiling still shows
   jank, degrade to an **overlay** rail (translate over content, zero relayout), which is also what
   GitLab does at narrow widths.
2. **`scrollbar-gutter: stable`** on the nav scroller, or a scrollbar appearing at 20 destinations
   shifts every label by ~8px — the classic "it looked fine until we added apps" bug.

### 1h. Many items — 10 / 20 / 40 / 80

Anchors: NN/g's position is that **more than 7–9 top-level items is fine if you plan for it**, and
that vertical navigation is the pattern that absorbs a broad hierarchy
([NN/g vertical nav](https://www.nngroup.com/articles/vertical-nav/)) — but that **hiding** nav
measurably cost task success on desktop specifically
([NN/g on the hamburger](https://www.nngroup.com/articles/hamburger-menu-icon-recognizability/)).
M3's expanded layer **scrolls** when it overflows; Fluent 2 states that a Nav "might not show all
available items", i.e. overflow is expected and must be designed.

| Destinations | What the navigator must do |
|---|---|
| **≤10** | Flat list, no filter, no scroll expected (10×36px = 360px). |
| **~16 (today)** | Groups with labels; **sticky brand above the scroller, one hairline per group in the rail**, and a scroll affordance (fade + `scrollbar-gutter`). No filter yet; the ⌘K palette is the fast path. |
| **20–24** | **Scroll is now real** (20×35px ≈ 700px vs ≈780px usable on a 1440×900). Add a **filter field at the top of the nav** (filters in place, `Esc` clears — never a modal), and remember per-group open/closed state. |
| **40** | Filter mandatory; groups **collapsed by default except the one holding the active app**; section headers sticky inside the scroller; the scroll lives in exactly one container. |
| **80** | The rail stops being the whole IA: pinned (≤6) + recent (≤5) + the open group + **«כל האפליקציות» launcher** (grid page with search). Keep the top ~12 visible; make the tail searchable, never scroll-only. Virtualization only pays above ~150 rows and answers DOM cost, not findability. |

**Also sourced, and easy to get wrong:** an item's **position must stay stable** (Pajamas: naming and
positioning consistent across contexts) — so never re-sort a group by usage; pinning is a user
preference persisted like any other (GitLab stores it in a cookie), and the **expanded and collapsed
states must be the same destination set at two levels of detail** — product nav in one state and
section sub-nav in the other "breaks the user's mental model".

---

## 2. Assessment — where המרכז stands today (measured 2026-09-25)

Measured, not remembered: the inventory comes from the running console's own `/api/modules`; the
layout from headless-Chromium renders of the live container at six widths (1728/1440/1180/1024/820/
390); the code claims from `platform-base/console/static/{index.html,app.js,style.css}` — read,
then re-verified by grep. Line numbers are as of 2026-09-25 and will drift; the symbol names will
not.

### 2.1 What the navigator actually holds

- **16 destinations in 4 groups.** `עסק` 7 (מסכים, דרייב, מייל, גיט, אתרים, דומיינים, דפדפן הלשכה),
  `ראשי` 1 (בינה ודעת), `תשתית` 6, `הגדרות` 2 (חיבורים ומפתחות, מסך התקנה). 15 tiles are compiled
  from `.generated/registry/console.modules.yaml`; 1 (`install`) is the console's own view
  (`modules.yaml`). The merge and sort live in `app.py` (`sorted(tiles + own, key=order)`).
- Longest label **`חיבורים ומפתחות` (15 chars)**; longest group label `הגדרות`. At the shipped
  `13.5px/600` that label needs ≈120px of run; icon box 20px + gap 9px + padding 22px leaves the
  238px rail ≈30px of slack. A 17-character label already ellipsizes.
- Vertical budget at 16 destinations: rows ≈16×35px = 560px, group labels ≈4×24px = 96px, brand
  ≈48px, user box ≈40px, build stamp ≈30px → **≈774px**. On a 900px window it fits by ~120px; **at
  20 destinations the rail is a scrolling nav**, and at 24 it scrolls on a 1080p window too.
- The nav **already scrolls** (`style.css:117` `.side{overflow-y:auto}`) with no affordance of its
  own — no sticky brand, no fade, no scrollbar gutter, and the scrollbar only appears if the OS
  shows overlay scrollbars.
- **Duplicate `order` values** in the compiled registry (`concurrency`/`domains` both `6`;
  `apps`/`computers`/`data-management` all `9`): intra-group position falls through to YAML emission
  order, so a reconcile can silently reorder the navigator.

### 2.2 What renders at each width (live renders, 2026-09-25)

Reproduce (no Playwright, no stack login — the container answers directly):

```bash
docker exec browser42-browser-local sh -lc \
  "chromium --headless=new --no-sandbox --disable-gpu --hide-scrollbars \
   --window-size=1024,900 --virtual-time-budget=5000 \
   --screenshot=/tmp/nav-1024.png http://console:8000/"
```

| Viewport | Shipped behaviour | What the render shows |
|---|---|---|
| 1728 / 1440 | rail expanded 238px | 16 rows + 4 group labels fit; brand subtitle wraps to **two lines** with the live business name; nav bottom has ~120px of slack |
| 1180 | rail expanded 238px | same, content column 942px |
| 1024 / 820 | **icon rail 62px**, auto (CSS only) | icon column; group labels and the brand name gone; **the `digital-office dev` build stamp wraps to three lines** in the 62px column; `#railToggle` is `display:none`, so the user cannot re-expand |
| 390 | rail **hidden**, bottom bar 60px | 4 tabs + «עוד»; «עוד» opens the ⌘K palette; the top bar has no hamburger (also `display:none`) |

### 2.3 Already right (keep, and do not relitigate)

- App-shell grid + **one** persistent dark rail on the **leading edge** (right under `dir="rtl"`,
  `style.css:114`), with RTL hygiene: logical properties, `.num{direction:ltr;unicode-bidi:isolate}`.
- The **anti-double-nav** outcome of v1 (one dark rail, lighter/horizontal secondary inside apps).
- Grouping with small group labels, accent-filled active row, `aria-label` + `aria-expanded` on the
  rail toggle, a visible-on-focus skip link, `prefers-reduced-motion` handling, and the ⌘K palette
  with a visible `Ctrl K` chip in the search button.
- A phone projection exists at all (bottom bar + palette) instead of a squeezed desktop rail.

### 2.4 Defects — proven from the code, ordered by what they cost

| # | Defect | Where | Why it matters |
|---|---|---|---|
| D1 | **The group vocabulary is a hard-coded literal, and the filter is an exact match**: `const GROUPS = ["ראשי","עסק","תשתית","הגדרות"]` + `MODULES.filter(m => m.group === g)` | `app.js:104`, `app.js:195` | A tile whose `group` is a typo, a new group, or English **never renders and never errors** — silent loss in the primary navigator. It also makes the layer-2 shell author the layer-3 grouping vocabulary, the exact inversion `modules.yaml`'s own header forbids. |
| D2 | **The phone bar's destinations are a literal app-id list**: `["drive","mail","chat","incoming"]` | `app.js:296` | `chat` ships disabled (`platform.state.yaml`), so the phone's whole navigator is 3 tabs + «עוד»; the rail's own first tile (the agent) is unreachable except through the palette. Nothing derives this from the registry. |
| D3 | **No `aria-current` anywhere in the console** (grep: 0 hits in `static/`) | `app.js:311` (`setActive` toggles a class) | A screen-reader user cannot tell which destination is current — WCAG-adjacent, and cheap to fix. |
| D4 | **Rail items are not keyboard reachable**: `<a>` with **no `href`** and only `onclick` | `app.js:200-202` | The primary navigator is mouse/touch-only; Tab skips it entirely. Keyboard users get the skip link and the palette — that is the whole navigation. |
| D5 | **Collapsed labels are `title`-only** | `app.js:201` | Not an accessible name, not shown on focus, unreliable on touch. The spec says the label stays in the DOM in both states. |
| D6 | **The toggle vanishes exactly where the rail is auto-collapsed** (`display:none` at 641–1024px and ≤640px) | `style.css:391`, `:397` | The state is both unobservable and unchangeable in the tablet band; v1 asked for "expandable on tap (overlay)". |
| D7 | **No transition on the rail**, and `applyRail()` runs after the modules fetch | `style.css:363` (no `transition`), `app.js:158-159` | A returning collapsed user sees 238px → 62px **snap** after first paint on every load. |
| D8 | **Collapsed groups become an undifferentiated icon column** — `.grouplbl` is hidden and nothing replaces it | `style.css:366` | v1 explicitly wanted thin dividers between icon clusters; today 16 icons read as one list. |
| D9 | **Two `margin-top:auto` siblings** (`.side .user`, `.side .build`) | `style.css:150`, `:440` | The free space is split between them, so the build stamp is not pinned where the C1 comment claims. |
| D10 | **Brand identity disappears when collapsed** (`.brand>div` hides both the name and `#brandSub`) | `style.css:366` | The one place that names the deployment becomes an anonymous «ל». |
| D11 | **Bottom-bar labels have no truncation rule** (no `ellipsis`, no width guard) | `style.css:408` | `חיבורים ומפתחות` inside a 5-way `space-around` row at 320px wraps into a 60px-tall item. |
| D12 | **Four unlabelled `<nav>` landmarks** (one per group, created bare) | `app.js:198` | A screen-reader landmark list shows four "navigation" regions with no names. |
| D13 | **`buildBottomNav()` runs twice per boot and `outerHTML`-replaces its container** | `app.js:151`, `:162`, `:293` | Any focus inside the bar is silently dropped; also re-created on every `platform:modules-changed`. |
| D14 | **A slow or failed `/api/modules` renders a rail-shaped void** — `#nav` ships empty, no `noscript`, no empty state | `index.html:21`, `app.js:149` | No-JS/failed-fetch users see chrome with nothing in it; there is no designed zero state. |

### 2.5 Specification drift (v1 said it, the code never did)

- v1 asked for **240px / 60px** (§3.1, §3.7); the shell ships **238px / 62px**. Both numbers were
  never reconciled, and `console-release-signoff.md` records 238px as a known limitation.
- v1's headline behaviour — **"auto-engages whenever an app is embedded"** — **does not exist in
  the code**. Collapse today is either a manual toggle or a CSS media query; `.embedwrap` appears
  nowhere near a collapse rule. This is the single largest gap between intent and product, and it is
  the behaviour the owner asks for by name.
- v1 put the toggle **at the rail foot**; it ships in the top bar (`index.html:30`). The top-bar
  placement is better (it stays reachable when the rail is hidden on phone) — v2 keeps the code's
  choice and says so rather than reverting to prose that nobody implemented.
- v1's `--bp-mobile/tablet/wide` tokens were never added to the Bina token set; the shell hard-codes
  `1024`/`640` in media queries and nothing else in the platform can read them.


---

## 3. Recommendation — unified navigation + layout spec

RTL-first, Bina-consistent, actionable. Pick-one decisions are stated; alternatives are not relitigated.

### 3.1 Primary navigation — the rail: states, geometry, anatomy

**One dark rail, on the leading edge (right, under `dir="rtl"`).** It stays the *only* dark
navigation surface on screen (`--side` / `--side-ink`). It is the primary destination switcher only —
never overloaded with per-app views (those are §3.2).

**Two states, two widths — and nothing else changes between them:**

| | Expanded | Collapsed (icon rail) |
|---|---|---|
| Width | **256px** | **72px** |
| Row height | **36px** | **44px** |
| Icon box / icon | 20px / 19px | 20px / 21px |
| Label | 13.5px/600, one line, ellipsis | **stays in the DOM**, visually hidden (`sr-only`-style), revealed as a tooltip |
| Group label | visible (11px/700, letter-spacing) | hidden — replaced by a **1px hairline divider** between groups |
| Item inset | 12px | 0 (icon centred) |

Rationale for 256/72 rather than v1's 240/60 or the live 238/62: the longest real label needs
≈190px of row, the iframe must not lose more than ~19% of a 1366px screen, and 72px gives a 48px hit
area plus a 12px inset on each side — comfortably past the 24×24 floor with room for the touch band.
The rail's width is a function of **viewport and state only** — no label, no group, no business name
may ever widen it.

**Anatomy of an item (all three states must be reachable by mouse, touch and keyboard):**

- The **whole row** is the target (`<a href="#/m/<id>">` — a real link, so it is in the tab order and
  the palette and the rail navigate identically). Hover/focus tint is confined to the row's pill.
- **Active** = tinted pill (8–10% accent over `--side`) + **600 weight** + full-opacity icon +
  `aria-current="page"`. Hover = same tint, no radius change, no size change. Focus-visible = the
  shared 2px accent ring, which must remain visible against the tinted active pill.
- **Collapsed tooltips** are real elements (`role="tooltip"`, `aria-describedby`), shown on **hover
  and focus**, opening toward the content (inline-end), delay-in 300–500ms, delay-out 0ms. Never a
  `title`-only tooltip (D5), and never the only accessible name.
- **Group dividers in the rail**: 1px `--side-line`, 8px block margin, no label. This is what keeps
  four clusters readable as four clusters at 72px (D8).

**Groups come from the registry, never from the shell.** `GROUPS` as a literal array is a defect, not
a design (D1): the shell renders whatever groups the compiled tiles declare, in a declared **order**,
with **unknown groups appended at the end** and an empty group omitted entirely. A tile can be lost
by a typo today and reordering is currently decided by YAML emission order (see §2.1) — so the group
order belongs in the registry too, and the gate in §4 enforces that the shell no longer authors it.

**Brand block (top, sticky above the scroller):** logo mark + name + the business line from
`applyBrand()`. One row, `min-height:56px`, name and sub-line ellipsized with a tooltip; in the rail
the mark alone stays, and it must never push the collapse control off-row. The collapse toggle lives
in the **top bar** (where it ships today — it stays reachable when the rail is hidden on phone), is a
real `<button aria-expanded aria-controls="nav">`, and is never `display:none` in a band where the
rail can exist (D6).

**Footer block (user + build stamp):** exactly one flex spacer, above the footer, with the nav
scroller taking `flex:1; min-height:0`. Two `margin-top:auto` siblings split the free space (D9).
Footer = account, appearance, build stamp — low-stakes and re-findable only; per Apple's own warning,
never the *only* path to a business action.

**Zero state:** if the registry returns nothing, the nav renders a designed Hebrew empty state
(«אין אפליקציות זמינות לחשבון זה» + a refresh affordance) inside the nav area — never an empty
column with a scrollbar (D14).

### 3.2 How embedded apps present their own nav (the anti-double-nav contract)

Codify the existing convention as a hard rule. **Embedded apps MUST NOT render their own dark
vertical rail.** They pick exactly one secondary pattern by app type:

- **Section-apps** (multi-view apps: פנקס, INDOX, אימות) → a **horizontal contextual tab-strip** at
  the top of the content area. Light surface (`--surface`), `--line` bottom border, active tab marked
  by a 2px accent underline + `--ink` text (inactive `--muted`). This is orientation-orthogonal to
  the vertical rail, so hierarchy reads instantly. (Matches the settled "horizontal tabs for
  section-apps" convention.)
- **Tool-apps** (browse/detail apps: דרייב, מייל) → a **light in-content side-panel** (folder tree /
  mailbox list) on the leading edge *inside* the content area — `--surface-2` background, `--line`
  divider, never the dark `--side` color. It is visually a content panel, not a nav rail.
- **Single-view apps** (מכונה, התראות, כל מקביל) → **no secondary nav**; just a page `.app-header`.
- **Standalone fallback:** an app run *outside* the console (its own origin) may still show its own
  dark `.topbar` (as incoming-documents does today). The rule is scoped to the **embedded** context —
  detect it (e.g. `window.self !== window.top`, or a `?embedded=1` / `X-Embedded` signal) and hide the
  app's dark chrome, downgrading to the light tab-strip.

**Net effect:** exactly one dark surface (the shell rail) + one light secondary surface, always at
different weight and usually different orientation. Double-nav cannot recur by construction.

### 3.3 Command palette — ⌘K / Ctrl+K

- Global listener in the shell; opens a centered modal (reuse `.modal` tokens, `width:min(560px,92vw)`).
- **Buckets:** *מעבר לאפליקציה* (apps), *פעולות* (verbs: new document, run sync, add key…),
  *אחרונים* (recent). Type-to-filter, ↑/↓ to move, Enter to run, Esc to close. RTL: results
  right-aligned, shortcut hints LTR-isolated on the leading edge.
- **Discoverability:** a small `⌘K` chip in the topbar (the GitHub lesson). Mention once in install/
  onboarding.
- Ships *after* the rail + responsive work (it's an accelerator, not the backbone) but is part of the
  target spec.

### 3.4 Responsive breakpoints (specific px + behavior)

Four bands, **one destination set re-projected** — never a different navigation at a different width.
The bands are evaluated on **CSS pixels after zoom** (`matchMedia` does this for free): a 1440px Mac
at 150% zoom is 960 CSS px and must get the tablet band, and at 200% zoom (≈720 CSS px) the rail must
be able to leave the layout entirely (WCAG 1.4.10 Reflow).

| Token | Range | Rail | Secondary nav | Notes |
|---|---|---|---|---|
| `--bp-mobile` | **< 640px** | **Hidden.** Primary nav = **bottom tab bar, ≤5 destinations** + «עוד» → the ⌘K palette; a hamburger in the top bar opens the same drawer. | Section-app tabs become a scrollable chip row; tool-app panels become full-screen list→detail. | Touch targets ≥44×44. Single column, `padding:14px`. |
| `--bp-tablet` | **640–1199px** | **Permanent icon rail, 72px**, no scrim (visible nav beats hidden nav on desktop-class widths); expandable **as an overlay on demand** — hover the rail edge or press the toggle — never by pushing content. | As desktop. | The toggle is **visible** in this band (D6). The stored pin for this band is honoured. |
| `--bp-desktop` | **1200–1439px** | **Expanded 256px on the console's own views; auto-collapses to 72px the moment an app is embedded** (§3.9); the user can pin either state. | As §3.2. | 1200 is where M3's expressive rail and GitLab's drawer both change behaviour; below it a 256px rail costs 20–40% of the content column. |
| `--bp-wide` | **≥ 1440px** | Expanded 256px, **sticky-pinned when an app is embedded only if the user pinned it**; content `max-width` guard on text-heavy views (tables stay full-bleed). | — | Prevents over-long line lengths; the rail may stay expanded here because 256px is 18% of the viewport. |

**Persistence and precedence** (the part everyone gets wrong): store the user's choice **per band**
(`nav.pin.desktop`, `nav.pin.tablet`) plus the mobile drawer state (`nav.drawerOpen`), and resolve in
this order:

> **explicit user pin at this band → the band's own default → (nothing else)**

A stored pin never overrides a band in which the rail physically cannot fit (GitLab's rule: the
preference "does not change within" the narrow band). The embed-aware collapse (§3.9) is a **band
default**, so an explicit pin beats it — a user who expands the rail while inside an app keeps it
expanded until they say otherwise.

Old v1 text kept for the record: the rail is **not** shrunk-and-kept on phone — it is re-projected
into a bottom bar (≤5) + a drawer for the full estate, and secondary tab-strips become horizontal
chip rows. Bottom bar spec: fixed to the bottom, `--side` background to echo the rail identity,
icon+label tabs, active = accent **plus** `aria-current`.

**The bottom bar's five destinations must be derived, not typed.** Today they are a literal id list
(D2) which silently degraded to 3 tabs when `chat` was disabled. v2 requires the projection to come
from the compiled registry — either "the first ≤4 destinations by `order` within `ראשי`+`עסק`" or, the
better declarative fix, a manifest field (`routing[].module.mobile: true`) that an app declares about
itself and `reconcile` compiles. The 5th slot is always «עוד».

### 3.5 Table-view conventions

Build on the existing `.table`. Standardize:

- **Sticky header:** `position:sticky; top:0` on `thead th`, with the existing `--surface-2`
  background (must stay opaque so rows don't bleed through). Test on real scroll.
- **Density:** two modes — **comfortable** (current `padding:11px 13px`) and **compact**
  (`padding:6px 10px`, same font size, not smaller). A density toggle in the table toolbar; remember
  per-app.
- **Toolbar** (reuse `.toolbar`): search box on the leading edge, active-**filter chips** (dismissible
  pills using `.pill`) so filtered state is always visible, density toggle + column menu on the
  trailing edge.
- **Selection + bulk actions:** checkbox leading column; when ≥1 row selected, show a **floating
  action bar** pinned to the bottom of the table area (`--surface`, `--shadow-lg`, accent primary
  action) with the selected count. Hide when selection clears.
- **Pagination:** a **footer with page controls + row-count + page-size selector** (25/50/100). Use
  pagination, not infinite scroll, for record tables; a "טען עוד" (Load more) hybrid is acceptable
  for append-style logs (e.g. Kafka tail). Keep sort/filter state stable across pages.
- **RTL:** `text-align:start` (already set) so text columns align to the right; **numeric/currency/ID
  columns** wrap values in `.num` (LTR-isolated) but keep the column itself start-aligned; mirror only
  directional cell icons.
- **Empty / loading / error:** every table ships all three states (reuse `.spin`, `.callout`).

### 3.6 Settings-view convention

- **Layout:** a **left (leading) light sub-nav of sections** for settings with many groups (mirrors
  3.2 tool-app panel), OR a **horizontal tab-strip** when ≤ ~5 sections (mirrors 3.2 section-app).
  Prefer the tab-strip for small settings areas, the section list for large ones (e.g. חיבורים keys).
- **Search** across settings when the surface is large (install/connections catalog qualifies — the
  35-connection catalog already collapses behind "מתקדם"; add a filter box).
- **Save affordance:** prefer **explicit Save/Cancel** for consequential forms (a sticky footer action
  bar), with clear dirty-state and an undo/reset path; use inline auto-save only for low-stakes
  toggles (reuse the `.switch` component), showing a subtle saved confirmation. Never silently discard.
- Group with `.group-label`; put destructive actions in a distinct "אזור מסוכן" block using `.callout.bad`.

### 3.7 Spacing, alignment & tokens

Add these to the Bina token set (they generalize what's already in the CSS):

```
/* rail */
--rail-w-expanded: 256px;   --rail-w-collapsed: 72px;
--rail-row-expanded: 36px;  --rail-row-collapsed: 44px;
--rail-item-inset: 12px;    --rail-radius: 8px;
--dur-rail: 200ms;          --ease-rail: cubic-bezier(.2,0,0,1);
/* breakpoints */
--bp-mobile: 640px; --bp-tablet: 1200px; --bp-wide: 1440px;
/* spacing scale (already implied — codify) */
--space-1: 4px; --space-2: 8px; --space-3: 12px; --space-4: 16px; --space-6: 22px; --space-8: 32px;
/* content rhythm */
--content-pad: 22px;  --content-pad-mobile: 14px;  --content-max: 1080px;
```

The rail tokens must live where the shell can read them (`platform-base/console/static/style.css`'s
generated token block is the copy; `platform-base/bina-ui/theme-tokens.css` is the source that gate
G27 keeps byte-identical), and the breakpoint tokens are documentation of values that CSS media
queries must still spell literally — a media query cannot read a custom property. Nothing else in the
platform may hard-code 256/72 again.

Alignment rules (the Linear discipline — align labels/icons/buttons on shared axes):
- One vertical baseline for rail items: icon box `20px` fixed width, label starts at a consistent
  inline offset (already `gap:9px`).
- Content gutters equal on both inline sides; use logical padding only.
- Card grids use `minmax` auto-fill (already the pattern) so density scales with width.
- Consistent radii: containers `--radius:16px`, controls `--radius-sm:9px`, pills `999px`.
- Consistent elevation: `--shadow` for resting cards/panels, `--shadow-lg` only for overlays
  (modals, drawers, floating bulk bar).

### 3.8 Overflow — what happens as apps are added (binding, per §1h)

- **16 (today):** groups + hairline dividers in the rail; **sticky brand above the scroller**; a
  soft bottom fade as the scroll affordance; `scrollbar-gutter:stable`. The nav scroller is the
  **only** scroll container in the shell.
- **20–24:** a **filter field** appears as the first row of the nav (below the brand, above the
  groups): `type="search"`, labelled, filters the visible items in place, `Esc` clears, `↑/↓+Enter`
  move into and through the results, and it is **never** a modal. Empty result = «אין תוצאה» inside
  the nav.
- **40+:** groups are collapsible, **collapsed by default except the group holding the active app**;
  per-group open/closed state is remembered per user; headers stay sticky inside the scroller.
- **80+:** pinned (≤6) + recent (≤5) + the open group + the «כל האפליקציות» launcher; the long tail is
  **searchable, not scrolled**.
- Pinning/favourites, when it lands, is a persisted user preference that **adds** a block at the top
  and never re-sorts the existing groups (spatial memory is the whole value of a sidebar).

### 3.9 Auto-collapse — the embed-aware state machine (the headline behaviour)

This is v1's promise that the code never implemented (§2.5) and the behaviour the owner asks for by
name: *the rail gets out of the way when you are working inside an app, and comes back when you are
not.*

```
band    = f(viewport)                      // CSS + matchMedia: mobile | tablet | desktop | wide
default = mobile      → hidden (bottom bar + drawer)
          tablet      → rail (72px, permanent)
          desktop/wide→ embed ? rail : expanded        // ← the embed-aware default
effective = pin[band] ?? default            // an explicit pin always wins, per band
```

- **`embed` is a property of the current view**, not of the app in the abstract: any view rendered
  into `#embedwrap` (every compiled module tile — the agent included) counts as *working inside an
  app*; views rendered into `#content` (install, connections, business identity, empty state) count
  as the console's own and keep the expanded rail — they are forms, and a form is not a workspace.
- **Re-evaluated on view transitions and on band changes only.** Never on scroll, never on a timer,
  never on the embedded app's *internal* navigation (`bina:route` postMessage): the rail must not
  breathe while the user moves around inside one app.
- **The toggle** (top bar, always visible in every band where the rail exists) sets `pin[band]` to the
  opposite of the effective state and persists it. **⌘/Ctrl + `\`** does the same, and the toggle's
  tooltip states both.
- **Edge-hover reveal** (rail state only): a 8px hot zone on the rail's content-side edge reveals the
  rail as an **overlay that does not push the app** (GitLab's model), closing 300ms after the pointer
  leaves. A hover reveal never writes a pin, never steals focus, and never opens over a modal.
- **Hard invariants:** a collapse/expand must not reload the iframe, must not change the current
  destination, must not lose the app's scroll position, and must not move a mouse target out from
  under the cursor unless the user clicked it. On phone the rail is *re-projected*, never squeezed.
- **First paint:** a returning user must not see the rail snap after the modules fetch (D7). Read the
  stored pin in a **blocking inline script in `<head>`** and set the state class on `<html>` before
  the first paint; the embed-aware default is then applied **with the transition enabled** (200ms),
  which is the one place an animated width change is correct and intended.

### 3.10 Keyboard, focus and screen-reader contract

- **One labelled landmark:** `<nav id="nav" aria-label="ניווט ראשי">` containing one `<ul>` per group,
  each `aria-labelledby` its own heading element. Four bare `<nav>` elements (D12) become one nav with
  four named lists, so a landmark list is readable.
- **Items are links with an `href`** (`<a href="#/m/<id>">`) — that alone puts the navigator in the tab
  order (D4), gives it a status-bar URL on hover, and lets ⌘-click / open-in-new-tab work. No
  `tabindex`, no roving tabindex needed for a vertical list of links.
- **Exactly one `aria-current="page"`**, set by the same code path that sets the active class (D3) and
  present in every projection: expanded, rail (72px) and bottom bar.
- **The label is always in the DOM**; collapsed it is visually hidden, not removed (D5), and every
  icon-only item still has its accessible name from its own text.
- **Toggle** = `<button aria-expanded aria-controls="nav">`; focus stays on it across expand/collapse;
  if focus was inside the list when it collapses, focus moves **to the toggle** (never lost).
- **Mobile drawer is modal** (scrim): focus enters it on open, is trapped while open, `Esc` closes and
  returns focus to the toggle, and the rest of the shell is `inert`. The **tablet edge-hover overlay is
  not modal** — no scrim, no trap, dismiss on `Esc`/pointer-leave.
- **Targets:** ≥44×44 on coarse pointers, ≥24×24 with ≥4px separation at every zoom and band. The
  whole row is the target; the tint is confined to the pill.
- **`forced-colors`:** the active state must survive with the tint flattened — weight + `aria-current`
  carry it, and `:focus-visible` gets an explicit outline.

### 3.11 Motion and polish (binding values)

- Rail expand/collapse **200ms `cubic-bezier(.2,0,0,1)`** (M3's own crossfade number); tint 80–120ms;
  tooltip in 300–500ms, out 0ms; **`prefers-reduced-motion` → 0ms** with the state still changing.
- Labels **fade** (out over the first 60% of a collapse, in at 40% of an expand) and never wrap or
  reflow: `white-space:nowrap; overflow:hidden; text-overflow:ellipsis` with a fixed label box.
- Animate the rail's own width only; the content column is pinned (`flex:1 1 auto; min-width:0`) and
  the rail carries `contain: layout paint`; `scrollbar-gutter: stable`; if the iframe still janks,
  degrade to the **overlay/transform** rail.
- **Zero animation on first paint**, and no layout shift when the scrollbar appears or a tooltip opens.
- Premium details that actually read as premium: a 4/8px rhythm end to end (no 5px, no 13px), one
  20px icon box (never mixing 16/18/20/24 sizes), a single hairline at the chrome↔content boundary at
  ~8% opacity rather than a full-strength line, no separators inside a group, one radius per role,
  and state that persists across reloads with no flash.

### 3.12 RTL rules (binding)

- **Logical properties only** on the shell: `inset-inline-start`, `margin-inline`, `padding-inline`,
  `border-inline-end`, `text-align:start`. Zero physical `left`/`right` (the gate in §4 checks it).
- **Scrollbar side:** with `dir="rtl"` a scroller puts its bar on the inline-**end** edge — for a
  right-hand rail that is the side facing the iframe, which reads as a bug. Wrap the nav scroller in
  `direction:ltr` and put `direction:rtl` back on its children so the bar sits at the window edge.
  This is the single most common RTL sidebar defect and it is invisible in a screenshot review.
- **Mirror only directional glyphs** (collapse/expand chevrons, back/forward); a printer, a document
  and a folder are universal and never flip. If the toggle is drawn as a chevron it points **away from
  the content** when collapsing.
- **Mixed runs:** business names, file names, numbers and code inside Hebrew labels get `dir="ltr"` +
  `unicode-bidi:isolate` (the shipped `.num` rule is the pattern). The build stamp's
  `direction:ltr; text-align:left` inside the rail stays — it is a Latin token, not a layout decision.
- **Across the iframe boundary:** `dir` does not inherit into an embedded app's document. The shell
  sets it on the frame's document when it is same-origin (as the theme code already does) and passes it
  in the embed signal; apps must not assume LTR.

### 3.13 Failure modes and the "never looks bad" invariants

| Failure | Required behaviour |
|---|---|
| Long label (Hebrew has no short-form convention) | One line, ellipsis, full text in a tooltip on hover **and** focus; never below 13px; never two lines in the rail (it breaks the 36px rhythm). |
| Long business name in the brand block | Mark always visible; name ellipsized with a tooltip; in the 72px rail the mark only; the collapse control never pushed off-row. |
| A group with one item | Keep the header (positional consistency), unless it is the *only* group and there is literally one item. |
| An empty group (nothing permitted for this account) | Omit the group entirely — never an empty header, never «0 items». |
| Zero destinations from the registry | Designed empty state inside the nav + refresh; never an empty column or a bare scrollbar track (D14). |
| 24 destinations | Filter field + remembered group collapse (§3.8). |
| 1024px, or 1440px at 150% zoom | Band is evaluated in CSS px after zoom → tablet band → 72px rail. |
| 200% zoom (≈720 CSS px) | The rail must be able to leave the layout entirely (drawer/bottom bar); do **not** shrink targets to fit (2.5.8 is zoom-independent). |
| `forced-colors` / high contrast | Tint + weight + `aria-current`; explicit focus outline; never colour alone. |
| `prefers-reduced-motion` | 0ms transitions; state still changes and is still announced via `aria-expanded`. |
| `/api/modules` fails or is slow | Rail renders brand + a skeleton/empty state, never a dead column; the console keeps its own views reachable. |
| Iframe wider than its track | `min-width:0` on the content column; the rail/overlay is never pushed by the iframe's intrinsic width. |

**Invariants — a change that breaks any of these is a regression, whatever it looks like:**
1. The rail's occupied width is a function of viewport + state only; no content can widen it.
2. Nav height never exceeds the viewport, and the scroll lives in exactly one container.
3. Every target is ≥24×24 CSS px with ≥4px separation at every zoom and band.
4. Every destination's name exists in the DOM in every state, collapsed included.
5. There is exactly one visible active destination, at every band and in every projection.
6. Collapse/expand never reloads the iframe, never changes the destination, never loses scroll.
7. Nothing depends on hover alone — hover is always an enhancement of focus and touch.

### 3.14 Code shape — "minimal and clean like pure gold" (binding on every phase)

The navigator is the most-read code in the shell and the place every future app is measured against,
so its shape is part of the specification, not a matter of taste. Eight rules, each verifiable:

**1. One home per behaviour.** The rail's state is decided **once**, expressed **once**, and read by
CSS — never restated per element, per breakpoint, or per file. Concretely: a single
`<html data-rail="expanded|rail" data-band="mobile|tablet|desktop|wide">` written by one state
function; the collapsed look lives in **one** CSS block keyed on those attributes. Today the same
state has two homes and three of its five declarations are duplicated verbatim (`style.css:363-367`
for the JS class and `:386-390` for the media query), which is exactly how the two drift.

**2. No magic numbers.** Every rail dimension is a token (`--rail-w-expanded`, `--rail-row-*`,
`--dur-rail`, …). The strings `238px`/`62px` must not appear in the shell stylesheet at all — not
once, not "just for the media query". A number that exists in two places is a future inconsistency.

**3. Data in, structure out.** One function turns the compiled registry into the projections the
shell renders (`{ rail, bottomBar }`), and **both projections come from the same call** — so "the
same destination set at two levels of detail" (§1h) is structural rather than aspirational. No
literal id lists, no group vocabulary in the shell, no per-projection filtering logic of its own.
Consumes: `modules[]` from `/api/modules`. Produces: two plain arrays. Renders: nothing (the caller
does).

**4. The decision is a pure function.** `resolveRail(band, isEmbedded, pin) → "expanded" | "rail" |
"hidden"`. No DOM, no storage, no globals inside it — so it is unit-testable in `node` with four
assertions instead of a browser, and the state machine of §3.9 can be proven rather than eyeballed.

**5. Budgets — measured, not felt.** A phase that exceeds one of these is a phase that has not
finished:

| Budget | Limit | Verified by |
|---|---|---|
| Nav JS (state + builder + projections, comments excluded) | **≤120 lines** | `wc -l` on the marked region, or the gate |
| Rail CSS (all states and bands, comments excluded) | **≤70 lines** | same |
| Event listeners for the whole navigator | **1** delegated listener | grep `addEventListener` in the nav region |
| New dependencies / frameworks / build steps | **0** | `git diff package.json` empty |
| `!important`, inline `style=` writes from JS, duplicated declaration bodies (≥3 declarations) | **0** | the gate (N6) |
| `@media` blocks touching the rail | **1 per band** | same |

**6. Comments record decisions, not code.** This repo's house style is long *why* comments and it is
not what "minimal" targets; a comment whose content can be re-derived by reading the next line is
noise, and one that records why the width is 256, which incident produced a rule, or which breakpoint
was chosen over what — is load-bearing and stays. Also: **no commented-out code**, ever.

**7. Delete as part of the change.** Every phase must leave the tree **smaller or equal**, and say in
one line what it deleted. Deleting the second home of the state (§1), the literal lists (D1/D2), the
`title`-only tooltips (D5), the double `margin-top:auto` (D9) and the dead branch that guarded them
is the work — not cleanup for later.

**8. No abstraction before the third use.** There is one sidebar. Build no "navigation framework", no
config object with eleven optional keys, no generic component layer for a single consumer. The gate
script obeys the same rule: ≤150 lines, no imports beyond the stdlib, self-testing on the pre-fix
tree.

---

## 4. Implementation plan — phases with acceptance

Sequenced so each phase is shippable and provable on its own, and so the **contract becomes
mechanical before the contract is tightened** (`AGENTS.md` rule 8: enumerate the callers
mechanically, prove the enumerator finds the pre-fix defect, then land the guard). **Every phase is
judged on code shape as well as behaviour** (§3.14): one home per behaviour, no literals, budgets
respected, and a one-line "what this deleted" in the commit message.

### P0 — Make the contract a gate (do this first, on the current code)

New gate `scripts/refactor/navigation-contract-lint.py`, registered in `scripts/refactor/GATES.md`,
`run-gates.py` and the CI lane. Five statically checkable rules:

| Rule | Fails on today's code because |
|---|---|
| **N1** no literal destination-id list in the console shell | `app.js`'s `["drive","mail","chat","incoming"]` (D2) |
| **N2** the nav must set `aria-current` and the CSS must style `[aria-current]` | zero occurrences today (D3) |
| **N3** no physical `left`/`right`/`margin-left`/`padding-right` in the shell stylesheet — logical properties only | the shell must be RTL-correct by construction (§3.12) |
| **N4** the nav scroller declares `overflow-y:auto` **and** `scrollbar-gutter:stable`, and no second nav scroller exists | `scrollbar-gutter` is absent today |
| **N5** the group vocabulary is not a literal array in the shell; groups come from `/api/modules` | `const GROUPS = [...]` (D1) |
| **N6** no duplicated declaration body (≥3 declarations) in the shell stylesheet, and no `!important` in the rail region | the collapsed state is written twice — `style.css:363-367` and `:386-390` — with three declarations duplicated verbatim (§3.14 rule 1) |
| **N7** no raw rail dimension in the stylesheet: `238px`/`62px`/`60px` must be token references | `style.css:114`, `:363`, `:386` hard-code them (§3.14 rule 2) |

**Acceptance:** the gate reports 6–7 findings on the pre-fix tree (recorded in the commit message),
0 after P1–P4, and it self-tests that its scan set actually contains `platform-base/console/static/`.
The gate itself is ≤150 lines, stdlib-only, and obeys §3.14 — a guard that duplicates its own logic
across two files is the defect it exists to catch.

### P1 — Rail geometry, structure and the accessibility foundation

Tokens (§3.7), 256/72 states with 36/44 rows, sticky brand above a single nav scroller, one spacer
before the footer, hairline dividers between groups in the rail, real `<a href>` items with
`aria-current="page"`, one labelled `<nav>` with per-group labelled `<ul>`s, the toggle visible in
every band where the rail exists, `contain:layout paint` + `grid-template-columns` transition +
`scrollbar-gutter`, and the no-flash first paint via a blocking head script.
**Files:** `platform-base/console/static/{index.html,app.js,style.css}` (+ the token copy kept
byte-identical from `platform-base/bina-ui/theme-tokens.css`, gate G27).
**Acceptance:** six headless renders (1728/1440/1180/1024/820/390) with the measured rail width in
each; a keyboard-only walkthrough that reaches every destination with Tab+Enter and never loses
focus; a landmark list showing one nav + four named lists; exactly one `aria-current`; N2–N7 green.
**Shape (§3.14):** the state is written once (`data-rail`/`data-band` on `<html>`) and the two
duplicated blocks (`style.css:363-367` + `:386-390`) are gone; `238px`/`62px` no longer appear as
literals; nav JS and rail CSS inside budget; the diff's "deleted" line names the second home of the
state, the dead `title`-only plumbing and the duplicate `.tb-acct` declaration.

### P2 — The embed-aware auto-collapse (§3.9)

**Acceptance:** from a console view the rail is expanded in the desktop band; clicking an app tile
collapses it to 72px within ~200ms; pinning expanded inside an app keeps it expanded across app
switches and across a reload; a reload never shows a snap (render at t≈0 and t≈1s must match); the
iframe is **not** reloaded by a collapse (frame `src` unchanged in the network log) and the app keeps
its scroll position; inner app navigation (`bina:route`) never changes the rail.

### P3 — Overflow behaviour (§3.8)

Sticky brand, bottom fade, the in-nav filter field once the navigator exceeds ~18 destinations,
per-group collapse memory past ~24.
**Acceptance:** at 16 destinations no filter is rendered; with 20 the field appears, filters in place
and `Esc` clears; with 40 only the active group is open on arrival; the 72px rail scrolls with group
dividers and no label shift when the scrollbar appears.

### P4 — The mobile projection, derived

Bottom bar built from the registry (not a literal), 4 derived destinations + «עוד», labels that
ellipsize at 320px, the drawer exposed as a modal (scrim, focus trap, `Esc` → focus back on the
toggle), and — the declarative option — a `routing[].module.mobile: true` field compiled by
`reconcile` so an app declares its own phone presence.
**Acceptance:** with `chat` disabled the bar still shows four real destinations; with an app's
`mobile` flag flipped the bar changes on the next reconcile; axe/landmark + focus-trap walkthrough on
the drawer.

### P5 — Motion, polish, parity

Tooltips on hover **and** focus (real elements), `forced-colors` treatment, the premium details of
§3.11, mirror the same behaviour in the dev-only sim (`digital-office/sim/overlay/*`) and add the
matching `PORT-PLAN.md` item — the sim is the spec the live UI is ported toward, and today it has no
rail item at all — then regenerate `./bbox ui-map` for the record.
**Acceptance:** `prefers-reduced-motion` render shows no transition; forced-colors render keeps the
active state visible; `pixel-diff`/parity checks do not regress.

### P6 — Only when the estate grows past ~24 destinations

Pinning/favourites (persisted, additive), recents, and the «כל האפליקציות» launcher. Not before:
building them at 16 destinations adds a surface that has to be maintained and understood for no
findability gain.

**Explicit answers to v1's flagged questions, restated for v2:**
- **Does the double-nav fix evolve into a collapsible icon rail?** Yes — and v2 adds the missing half:
  the collapse is **automatic when an app is embedded** (P2), not only a manual toggle.
- **How should mobile work?** Re-projected, not squeezed: ≤5 derived destinations in a bottom bar +
  a modal drawer for the estate + horizontal chip rows inside apps.
- **What is the one number to hold?** 256 expanded / 72 rail — and the rail's width is never a
  function of its contents.

---

## 5. What this document does NOT decide alone

These need the owner's call; each is a one-line answer that unblocks the phases above.

1. **Width:** 256px expanded (my pick, §3.1) vs keeping today's 238px vs going wider (264–280px).
   On the owner's ~1366px viewport, 256px is 18.7% of the screen.
2. **Auto-collapse default on embed** (§3.9): collapse to the icon rail (matches v1 and the owner's
   stated wish) vs stay expanded until toggled.
3. **Bottom-bar destinations:** derived from `order` (works today, no schema change) vs a declared
   `module.mobile: true` manifest field (cleaner, needs `app.schema.json` + `reconcile` work).
4. **The 20-destination filter field:** add it now (it will appear the moment two apps are installed)
   or wait until the estate crosses 18.
5. **The gate's teeth:** should N1–N7 be a CI-blocking gate from day one, or warn-first for one
   release (`AGENTS.md`'s staged-rollout rule applies to tightened contracts)?

---

## 6. The app's URL is the route — the shell reflects it (adopted, shipped 2026-10-12)

The owner, after the first app was wired by hand: *«תחשוב שזה בעיה שחוזרת על עצמה בכל הכלים
ואפלקציות קוד פתוח שכולם משתמשים בקישור בשביל הניווט צריך למצוא דרך אחידה סטנדארטית ומינימלית
ויציבה ואיכותית שקונסול ידע לשקף את זה»*. He is right, and the first cut (`platform-base/bina-ui/
bina-route.js` — a stamped block per app, a `bina:route` postMessage, a `?r=` query) is the wrong
layer: it makes every app carry an office protocol to say something the browser already knows. He
then ruled out the second cut's machinery as well — *«אסור שזה תלוי בסריקות וקוד מורכב חייב פשוט
לנתב את כל מה שהקישור בפנימי של אפלקציות בברירת מחדל כדי שהנתיב תמיד יהיה הנתיב המלא שניתן לשתף
ומוביל לאותה נקודת מסך»* — and what is SHIPPED is smaller than either.

**THE RULE, AND THE WHOLE MECHANISM (shipped 2026-10-12).** A screen is the app's own URL and
nothing translates it: the console's tail and the frame's URL are the same string under the app's
mount — `#/m/drive/folder/5` ⇄ `/a/drive/folder/5`, no encoding, no protocol, no code in any app.
The one thing that cannot be a rule is TIME — the app moves inside its frame without telling anybody
— so the shell subscribes to the frame's own **`navigate` event** (the Navigation API; same origin,
every embedded app is proxied under `/a/<alias>/`) and writes its own address with `replaceState`.
Ten lines in one file (`watchFrameRoute`, `platform-base/console/static/app.js`), plus a
`hashchange`/`popstate` fallback for engines without the Navigation API and a re-subscribe on the
frame's `load`. **No polling, no message protocol, nothing the app has to do.** Measured AFTER the
deploy (`ci-artifacts/route-contract/navigate-probe.py`): `#/m/drive/trash` renders the app's own
trash screen; a click inside the app's own rail put `#/m/drive/p/home` — the app's route, verbatim —
into the console's address; a full load inside the frame kept working.

**THE FIRST CUT'S OWN MEASUREMENTS, kept because they are why the rule is safe** (the second cut was
proposed against them; the third cut — this one — stands on the same facts):

**THE RULE.** A screen is the app's own URL. The console's tail IS that URL, verbatim —
`#/m/<module><path>[?query][#fragment]` — and the shell reflects whatever the frame's own URL says.
No transport, no encoding, no cooperation from the app.

**WHY IT IS SAFE — five measurements against the live console, 2026-10-12** (`ci-artifacts/
route-contract/bridge-probe.py`):

| # | What was asked | Measured |
|---|---|---|
| A | Can the shell read the frame's own URL? | Yes — the app is proxied under the console's origin (`/a/<alias>/`), so `frame.contentWindow.location` is readable today (the shell already reads it in `showEmbed`) |
| B | Can the shell WATCH it, with nothing from the app? | Yes — this engine has the **Navigation API** in the frame (`frame.contentWindow.navigation`), and wrapping the child's `history.pushState/replaceState` plus listening to `hashchange`/`popstate` on the child also works. Measured: the shell saw `pushState -> /a/drive/trash` when the app's own rail was clicked, with the app knowing nothing about the shell |
| C | Does a PATH tail open the right screen with no protocol at all? | Yes — `#/m/drive/trash` renders the trash screen (screenshot `bridge-path-tail.png`); the app's own router read `/trash` from its own URL, no block, no `?r=`. `drive:8975/trash` answers 200 at the app's origin, `my-docs` and `incoming` answer any path |
| D | And a hash-routed app? | Yes — a fragment inside the frame (`/a/domains/#/a/1/d/x/records`) survives and is visible to the shell, and **never reaches the server at all**, so a hash-routed app needs no server change and no fallback |
| E | The `?r=` link also works | Yes — it is simply unnecessary |

The correction of record from the same session: the earlier "12 of 15 apps have no SPA fallback"
was measured with an INVALID route (`/some/deep/route`); apps that route by path answer their real
routes (drive 200 on `/trash`), and apps that route by hash never need one.

**WHAT CHANGES, AND WHERE.**

- **The shell** (`platform-base/console/static/app.js`) — one watcher: on module open, attach to the
  frame (Navigation API first, else wrap `history` + `hashchange`/`popstate`, re-attached on the
  frame's `load`); on any change mirror the frame's route into the console's hash with
  `replaceState`. The tail regex grows `#` so a fragment can ride along
  (`#/m/<id>[/path][?query][#fragment]`), and `joinEmbed` already rebuilds the frame URL verbatim.
  ~40 lines, one file, for every app — including third-party open-source apps proxied under
  `/a/<alias>/`, which take part without a line of their own.
- **The apps** — nothing. An app is linkable because it uses its own URL, which is what every tool
  already does. What remains per app is PRODUCT work, in the app's own idiom: a screen whose state
  is not in its URL yet (`my-docs` drawer, `computers` selection, `domains`/`sites` already have
  hash routes) gets a route — that is a screen improvement, not platform wiring.
- **The platform** — nothing new. No proxy fallback is needed for the measured apps (path routers
  answer their routes; hash routers need no server support). If a future app routes by path yet 404s
  it, the fallback belongs in ONE place — the console's `app_proxy` (history-API fallback, the
  industry-standard pattern) — and not in fifteen servers.

**THE CLEANUP — DONE, 2026-10-12 (the first cut, removed the same night it was built).**

1. `platform-base/bina-ui/bina-route.js` — the block, deleted; with it its `BLOCKS` row in
   `theme-token-lint.py` (G27, replaced by a note saying why there is no block) and drive's copy
   (`BinaRoute.mount` + the three `BinaRoute.report()` calls), which left `apps/drive/static/app.js`
   byte-identical to what it was before the block. Drive's own router — `MOUNT`, `parseUrl`,
   `applyUrl` — was always the whole implementation; the console now reads it.
2. The `?r=` form — out of the shell's watcher, out of the docs, out of the gate, and out of the
   measurement tools.
5. `routing[].module.route{mode,why}` — never needed after all: removed from `app.schema.json` and
   from `apps/bina-ds/app.json` before it was ever published (both files are back to their committed
   content). Nothing is required of an app, so there is no exception to declare.

**WHAT REMAINS.**
3. The `bina:route` postMessage — the shell no longer needs to be told. Keep the listener for one
   cycle as a compatibility bridge (carriers today: `mailview`, `incoming`), and make the gate count
   the carriers so the removal is provable rather than hopeful; delete the listener and the two
   reports when the count is zero.
4. `apps/bina-ds/plugins/session-link` — shrinks to what is genuinely the app's own business: the
   harness's vendor client has no routing of its own, so the plugin keeps the open conversation in
   the harness's OWN URL (`/?s=<id>`, which the watcher now reflects). Its `report()`/postMessage
   half goes.
6. Gate **G83** carries the product half: every screen the UI map declares
   (`scripts/ui-coverage/inventory.py` derives a route per view) opens at `#/m/<module><route>` —
   measured per app in a browser, and the `frame_src` workaround in `rewrite_for_console` stops being
   a workaround and becomes the ordinary link. The seven apps whose screens are not in their URL at
   all are the gate's list.
7. The rewritten app-author contract in `build-your-first-app.md` § "the address is the state":
   "your route is your URL; the console mirrors it — you write nothing for the shell".

**LIMITS, NAMED.** A frame the browser isolates from the shell — an app on its own host, another
office's app through the door, a `sandbox` without `allow-same-origin` — cannot be read, and there
the console's URL names the app (and the office), never the screen inside it. That is the origin
boundary doing its job, not a gap to close. An app that navigates by full page load is re-attached on
`load`. An app whose state is not in its URL has nothing to mirror: that is the app's work, above.

**MIGRATION — WHERE IT STANDS (2026-10-12, the same night).** DONE: the shell watcher + the identity
tail, verified against drive BOTH with the block present and after deleting it
(`navigate-probe.py`, `drive-trash/`, `drive-reopen/`); the block, its G27 row and drive's wiring
deleted; `module.route` removed before it was published; the app-author contract and gate G83
rewritten to the new rule; the console and drive deployed. NEXT, in this order: (1) the seven apps
whose screens are not in their URL — `my-docs`, `any-concurrency`, `alerts`, `machine`, `computers`,
`connections`, `dgo-extend` (G83 is the list, each one a route per screen in the app's own idiom);
(2) the two `bina:route` carriers converted and the listener deleted, with the gate counting the
carriers until then; (3) `session-link` shrunk to the plugin's own business; (4) G83's runtime half —
every view the inventory declares opens at `#/m/<module><route>`.

---

## Sources

**v2 additions 2026-09-25** (per-claim links for every number in §1g/§1h live in
[`sidebar-research.md`](sidebar-research.md), which also records which figures are sourced and which
are judgement):

- [Material 3 — navigation drawer specs](https://m3.material.io/components/navigation-drawer/specs) ·
  [navigation rail specs and sizes](https://pub.dev/documentation/material_design/latest/material_design/M3NavigationSizes/railWidth-constant.html)
- [Apple HIG — Sidebars](https://developer.apple.com/design/human-interface-guidelines/sidebars)
  (leading edge; "no more than two levels"; "avoid hiding the sidebar by default")
- [GitLab Pajamas — navigation sidebar](https://design-gitlab-com-gitlab-org-gitlab-services-f6beaf2fb7fd4cad76.gitlab.io/patterns/navigation-sidebar/)
  (≥1200px visible, ≤1199px overlay + scrim, pinned items persisted, preference never overrides the band)
- [Fluent 2 — Nav](https://fluent2.microsoft.design/components/web/react/core/nav/usage) (one level
  of nesting; overflow is expected)
- [NN/g — Vertical navigation](https://www.nngroup.com/articles/vertical-nav/) ·
  [NN/g — hamburger recognizability and the cost of hidden nav](https://www.nngroup.com/articles/hamburger-menu-icon-recognizability/)
- [W3C — Understanding 2.5.8 Target Size (Minimum)](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html) ·
  [WCAG 2.2 quick reference](https://www.w3.org/WAI/WCAG22/quickref/)
- [Linear — behind the latest design refresh](https://linear.app/now/behind-the-latest-design-refresh)
  (the nav recedes; borders "felt, not seen")

**v1 sources (2026-07-13, kept):**
- [DEV — I cloned Linear's sidebar (app-shell pattern)](https://dev.to/dev48v/i-cloned-linears-sidebar-in-50-lines-of-html-one-file-zero-npm-40ej)
- [Linear — How we redesigned the UI (part II)](https://linear.app/now/how-we-redesigned-the-linear-ui)
- [Slack — An overview of Slack's new design (Sept 2025)](https://slack.com/help/articles/16764236868755-An-overview-of-Slacks-new-design)
- [UXPin — Mobile Navigation Design: 8 Types (2026)](https://www.uxpin.com/studio/blog/mobile-navigation-examples/)
- [Material Design — Navigation patterns](https://m1.material.io/patterns/navigation.html)
- [Navbar Gallery — Best sidebar menu design examples 2026](https://www.navbar.gallery/blog/best-side-bar-navigation-menu-design-examples)
- [DeveloperUX — Multi-platform navigation for internal tools](https://developerux.com/2026/05/18/improving-multi-platform-navigation-internal-tools/)
- [Mobbin — Command Palette UI design](https://mobbin.com/glossary/command-palette)
- [UX Patterns for Developers — Command Palette](https://uxpatterns.dev/patterns/advanced/command-palette)
- [buildmvpfast — How to add a Cmd+K command palette to your SaaS (2026)](https://www.buildmvpfast.com/blog/how-to-add-cmd-k-command-palette-saas-2026)
- [BrowserStack — Responsive design breakpoints 2025](https://www.browserstack.com/guide/responsive-design-breakpoints)
- [Framer — Responsive breakpoints: 2026 guide](https://www.framer.com/blog/responsive-breakpoints/)
- [Pencil & Paper — Enterprise data tables UX patterns](https://www.pencilandpaper.io/articles/ux-pattern-analysis-enterprise-data-tables)
- [UX Design World — Best practices for actions in data tables](https://uxdworld.com/best-practices-for-providing-actions-in-data-tables/)
- [Onething — Pagination vs Infinite Scroll](https://www.onething.design/post/pagination-vs-infinite-scroll-which-is-better)
- [Medium — Pagination vs Infinite Scrolling for SaaS table design](https://medium.com/@artof.anj/pagination-vs-infinite-scrolling-the-ultimate-showdown-for-saas-table-design-febfac537781)
- [bricxlabs — Settings page UI examples](https://bricxlabs.com/blogs/settings-page-ui-examples)
- [Onething — Top website navigation design patterns](https://www.onething.design/post/top-website-navigation-design-patterns)
- [Gapsy — UX design patterns](https://gapsystudio.com/blog/ux-design-patterns/)
- [SimpleLocalize — RTL design guide for developers](https://simplelocalize.io/blog/posts/rtl-design-guide-developers/)
- [Mozilla — RTL guidelines](https://firefox-source-docs.mozilla.org/code-quality/coding-style/rtl_guidelines.html)
- [ItielMaN — rtl-guidelines (GitHub)](https://github.com/ItielMaN/rtl-guidelines)
- [placeholdertext — Complete guide to RTL layout testing](https://placeholdertext.org/blog/the-complete-guide-to-rtl-right-to-left-layout-testing-arabic-hebrew-more/)
