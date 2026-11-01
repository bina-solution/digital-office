# Extracting the essence of Astryx (Meta's 8-year design system) into our simulation

**Source:** [Astryx](https://astryx.atmeta.com/) — Meta open-sourced (June 2026, MIT) the design system it
matured internally for **8 years across 13,000+ apps**. Built on **React + StyleX** (Meta's compile-time
atomic-CSS engine), **150+ accessible components**, **agent-ready** (CLI + MCP server), **10 themes** via a
CSS-variable cascade. Sources: [launch post](https://astryx.atmeta.com/blog/introducing-astryx) ·
[GitHub facebook/astryx](https://github.com/facebook/astryx) ·
[MarkTechPost overview](https://www.marktechpost.com/2026/07/21/meta-open-sources-astryx-an-agent-ready-react-design-system-with-150-accessible-components-seven-themes-and-a-cli/).

**Reality for us:** we can't *adopt* Astryx — our sim is vanilla HTML/CSS/JS bundling real app frontends,
not React/StyleX. So we extract the **essence** (principles, token architecture, component coverage,
accessibility defaults, theming, agent-readiness) and re-implement it in our own tokens/overlays. This
doc is the full essence list + a phased plan. Everything here is sim-only and desktop-safe.

---

## Part A — The essence (what 8 years actually taught them)

### A1. Six design principles (the philosophy)
1. **Guidance over enforcement** — components *enable* capability, they don't lock you into one API.
2. **Strong, documented conventions** — consistent naming, props, composition; conventions are the value.
3. **One system for humans and AI** — a single API + docs + CLI (+ MCP) serves people and agents alike.
4. **Earned by measurement** — conventions are tested against real usage, not asserted.
5. **Start anywhere, change anything** — compose at any level; `swizzle` can eject a component's source.
6. **System controls behavior/a11y/quality; themes control looks** — a hard separation of concerns.

> **Our takeaways:** (a) keep a single canonical token layer everything reads from; (b) separate
> *behavior/accessibility* (stable) from *appearance* (themeable); (c) name things consistently so both we
> and future agents can reason about them; (d) prove quality by the ui-map + QA harness, not by assertion.

### A2. Architecture: **system ≠ theme**
- The **system** owns structure, behavior, accessibility, and quality.
- A **theme** is *only* a set of **CSS custom-property overrides**. Change the variables → every component
  restyles. No component markup changes. This is exactly portable to vanilla CSS.

### A3. Token architecture (the CSS-variable cascade)
Astryx tokens are grouped as **color · typography · radius · spacing · motion · elevation**, exposed as CSS
variables and overridden per theme. The important idea is **semantic roles**, not raw values:
- **Color roles** (not hex-by-name): `surface`, `on-surface/ink`, `muted`, `line/border`, `accent`,
  `accent-hover`, `accent-soft`, `on-accent`, plus status roles `success/warning/danger/info`.
- **Typography scale**: a font stack + a modular size ramp (e.g. `xs…3xl`) + weights + line-heights.
- **Radius scale**: `sm/md/lg/pill`.
- **Spacing scale**: a single step ramp (4px base) used for all gaps/padding.
- **Elevation**: a shadow ramp (`xs/sm/md/lg`) — depth as a token, not ad-hoc box-shadows.
- **Motion**: duration + easing tokens (`fast/base/slow`, standard/entrance/exit easings).

> **Our state:** `sim/overlay/tokens.js` already injects a canonical `:root` palette + font stack. It's a
> partial version of exactly this. Gap: we lack a **spacing/type/radius/elevation/motion ramp** and
> **status roles** as first-class tokens, and we have no **theme switch**.

### A4. Theming — 10 named themes via variable cascade
`default, neutral, daily, butter, chocolate, matcha, stone, gothic, brutalist, y2k` + dark mode. Each is a
`:root[data-theme=…]` (or class) block overriding the same variables. A "theme provider" just sets the
attribute. **Directly portable**: our `tokens.js` can define 2–3 themes as `[data-theme]` blocks and the
console can offer a switcher (we already handle light/dark).

### A5. The full component inventory (150+) — grouped
This is the coverage checklist. **✅ = we already have an equivalent in the sim; ◑ = partial; ⬜ = missing.**

| Group | Astryx components | Our coverage |
|---|---|---|
| **Actions** | Button, Button Group, Dropdown Menu, Icon Button, Link, More Menu, Segmented Control, Toggle Button (+Group), Toolbar | ✅ buttons/links/icon-btn; ✅ segmented control (chat tabs); ◑ dropdown/more-menu (switcher) |
| **Chat** | Chat Composer, Chat Layout, Chat Message, Message Metadata, System Message, Tool Calls | ✅ we built a full chat (composer/layout/message/metadata/system note) — B3/B4 |
| **Containers** | Card, Carousel, Clickable Card, Collapsible, Selectable Card | ✅ cards; ◑ collapsible (mail label groups); ⬜ carousel, selectable card |
| **Content** | Avatar, Avatar Group, Blockquote, Citation, Code, Code Block, Empty State, Heading, Icon, Kbd, Markdown, Text, Thumbnail, Timestamp, Token | ✅ avatar, empty state, heading, icon, kbd, text, timestamp; ◑ thumbnail (drive); ⬜ avatar-group, blockquote, citation, code-block, markdown |
| **Data input** | Calendar, Checkbox, Date/DateRange/DateTime/Time Input, Field, File Input, Multi Selector, Number Input, Power Search, Radio List, Selector, Slider, Switch, Text Area, Text Input, Tokenizer, Typeahead | ✅ text input/area, file input, field, search; ◑ command-palette=Power Search; ⬜ calendar/date, slider, switch, multi-selector, tokenizer, typeahead |
| **Feedback** | Badge, Banner, Progress Bar, Skeleton, Spinner, Status Dot | ✅ badge, banner, progress, spinner, status-dot; ◑ skeleton (grid loader); |
| **Layout** | App Shell, Aspect Ratio, Divider, Form Layout, Grid, Layout, Resize Handle, Section | ✅ app shell (console), grid, divider, section, form layout; ⬜ aspect-ratio, resize-handle |
| **Navigation** | Breadcrumbs, Outline, Pagination, Side Nav, Tab List, Top Nav (+Mega Menu/Featured/Menu) | ✅ side nav, top nav, tab list, pagination, breadcrumbs (drive); ⬜ mega-menu, outline |
| **Overlay** | Command Palette, Dialog, Hover Card, Lightbox, Overlay, Popover, Toast, Tooltip | ✅ command palette (Ctrl-K), dialog/overlay, toast, popover (switcher), tooltip; ⬜ hover-card, lightbox |
| **Table & list** | List, Metadata List, Overflow List, Table, Tree List | ✅ table (RevoGrid/BinaTable), list, tree list (drive); ◑ metadata list; ⬜ overflow-list |
| **Utility** | Visually Hidden | ⬜ (needed for a11y) |

> **Insight:** the two categories we're *strongest* on are exactly where we invested — **Chat** and
> **App Shell/Nav**. The gaps are **form controls** (switch, slider, date, typeahead), a few **overlays**
> (hover-card, lightbox), and **a11y utilities** (visually-hidden). This is our build backlog.

### A6. Accessibility defaults (baked in, not bolted on)
Every component ships **accessible defaults**: keyboard operability, focus management, ARIA roles/labels,
visible focus, and contrast. The lesson: a11y is a *system* responsibility, not per-screen.
> **Our gap:** we have inconsistent focus rings, few ARIA roles, no `visually-hidden`, and unaudited
> contrast/keyboard paths. This is the single highest-leverage quality investment.

### A7. Composition & agent-readiness
- **Compose at any level** (not a closed top-level API) + **swizzle/eject** for full ownership.
- **Agent-first**: one API, docs, CLI, MCP — so an AI can scaffold/verify UIs from the same source of truth.
> **Our takeaway:** keep our overlays/mocks small and composable; keep this doc + the ui-map + QA harness
> as the machine-readable "source of truth" an agent (me) uses to build and verify.

### A8. **Aesthetic essence** — the visual taste of an 8-year, 13,000-app system
This is the part you can't get from tokens alone — the *judgment* about how it should look and feel.
Distilled from the docs, example UIs, and hands-on reviews
([Evangeline Ng's test](https://evangelineng.substack.com/p/i-tested-metas-agent-ready-design),
[MakerStack review](https://makerstack.co/reviews/astryx-review/),
[Stork.AI vs shadcn](https://www.stork.ai/blog/metas-new-framework-targets-shadcn)):

1. **"Clean design, everyday durability."** Calm, professional, unflashy. It should look boring-in-a-good-way
   and survive daily use — not win a dribbble award. Restraint is the aesthetic.
2. **Medium density — the balance.** Reviewers specifically call it *medium density*: **not cramped
   data-tables, not excessive emptiness.** This is the exact axis we've been getting wrong in both
   directions (console hub too sparse; mail rows too dense). Target the middle everywhere.
3. **Generous whitespace on a consistent rhythm.** Breathing room around cards/sections, methodically
   spaced off ONE scale — never ad-hoc margins. Whitespace *is* the hierarchy.
4. **Depth by restraint, not drop-shadows.** Prefer **soft borders + a single subtle 1px shadow + color
   separation** over heavy elevation. Pick ONE elevation ramp and never mix shadow styles. (A review
   flagged an *unwanted* shadow on a segmented control as a defect — stray/inconsistent shadows read as
   low quality.)
5. **Color discipline — one accent, applied *everywhere it belongs*.** Neutral surfaces + a single brand
   accent that reaches **every** keyed element: buttons, links, active nav, **progress bars, status
   labels, badges, secondary controls.** The sharpest lesson from the reviews: a brand is *"perfect
   everywhere the system lets you reach, and wrong everywhere it doesn't."* → **No orphan-colored
   elements.** Audit every screen for anything rendering in a stray default color.
6. **Typographic hierarchy through weight, not size alone.** Strong weight contrast between headings and
   body; concise, scannable copy; one type ramp. Big-bold numbers for KPIs, quiet labels.
7. **Motion is functional, never decorative.** Transitions for state/feedback (hover, focus, enter/exit,
   optimistic sends, typing) — nothing that merely wiggles. Short durations; standard easings.
8. **Coherence is the thing users love.** What makes a multi-app platform feel "loved" is that every
   surface shares the *same* radius, spacing, icon set, empty-state voice, and interaction states — the
   super-app feeling is **consistency**, not novelty per app.

> **Concrete aesthetic quality-bar we can enforce in the ui-map QA** (pass/fail per screen):
> - [ ] no element in a stray/default color (accent + status roles reach everything)
> - [ ] one radius scale, one shadow ramp — no mixed/stray shadows
> - [ ] density is medium: rows/cards neither cramped nor floating in emptiness
> - [ ] all gaps/paddings land on the spacing scale (no 13px/17px one-offs)
> - [ ] clear heading↔body weight contrast; numbers bold, labels quiet
> - [ ] every state present & consistent: hover/focus-visible/active/disabled/loading/empty/error
> - [ ] motion only where it communicates state

### A9. **Patterns layer** — the real unit of reuse (biggest insight for us)
Astryx's third layer isn't components, it's **battle-tested whole-workflow patterns**: **table pages,
detail layouts, form wizards, navigation, data-entry flows, checkout, dashboard/analytics, chat/assistant,
empty states.** Eight years taught them that teams don't reason in buttons — they reason in *workflows*,
so the durable value is composed patterns with the density/rhythm/states already right.
> **This is exactly what our sim is** — 10 whole apps, not a component gallery. So our highest-leverage
> move is to codify our own **pattern set** (list/table page · detail drawer · wizard/onboarding · chat ·
> dashboard · empty/error state) with the A8 quality-bar baked in, then make every app conform to it.

### A10. **UX essence** — how it *behaves*, not just how it looks
The interaction insights an 8-year, 13,000-app system encodes (from the principles, the component set —
Empty State, Skeleton, Toast, Banner, Command Palette, Field, Typeahead, Form Layout — and the reviews):

1. **Every state is designed — never a dead-end.** Loading → **Skeleton** (not a bare spinner), Empty →
   **Empty State with a next action**, Error → recovery affordance, Success → confirmation. First-class
   `Empty State` + `Skeleton` components mean this is a *system rule*: every view answers "what now?".
2. **Guidance over enforcement, applied to flows.** Forgiving, low-friction paths; sensible defaults;
   prefer **undo (Toast) over blocking confirm-dialogs**; let people recover rather than gate them.
3. **Immediate feedback / optimistic UI.** On mobile "even short pauses feel long," so act instantly and
   reconcile: optimistic sends, typing indicators, progress bars, status dots. The user is never left
   guessing whether something worked.
4. **One consistent interaction model everywhere.** The same click/gesture/shortcut does the same thing
   in every app — inconsistent gestures across screens are a top UX defect. Coherence again.
5. **Keyboard-first for power, touch-first for reach.** **Command Palette (Ctrl-K)** + full keyboard
   operability for pros; **thumb-zone bottom nav + 44–48px targets** for phones. Both, not either.
6. **Progressive disclosure.** Start with visible controls; reveal advanced options/gestures as the user
   demonstrates competence — don't dump everything at once, don't hide everything behind a gesture.
7. **Low-friction data entry.** Typeahead, multi-selector, tokenizer, date pickers, and inline `Field`
   validation reduce the cost of input — the system does the work, not the user.
8. **Orientation at all times.** Breadcrumbs, active nav states, outline, timestamps, metadata lists —
   you always know *where you are* and *what you're looking at*.
9. **Non-blocking feedback.** Toasts/banners/status over modal alerts; the flow keeps moving.
10. **Accessibility is UX.** Focus management (trap in dialogs, restore on close), visible focus, ARIA,
    keyboard paths — inclusive interaction is a system guarantee, not a screen-by-screen afterthought.

> **UX quality-bar we can enforce per flow (pass/fail):**
> - [ ] loading shows a **skeleton** shaped like the content, not a bare spinner
> - [ ] empty states name a **next action**; error states offer **recovery** (retry/reconnect/back)
> - [ ] destructive actions offer **undo** (toast) rather than only a confirm dialog
> - [ ] every action gives **immediate feedback** (optimistic + toast/status)
> - [ ] the **same gesture/shortcut** behaves identically across all apps
> - [ ] overlays **trap focus**, **Esc closes**, focus **restores** to the trigger on close
> - [ ] you can tell **where you are** (active nav/breadcrumb/title) on every screen
> - [ ] forms validate **inline**, with forgiving inputs (typeahead/pickers) and clear errors

> **Our UX audit (quick):** ✅ strong on optimistic chat, typing, toasts, command palette, empty/error
> states (we just added chat error→reconnect), bottom-nav thumb reach. ◑ inconsistent focus-trap/Esc in
> our custom overlays; ⬜ we use blocking `confirm()` for deletes (should be undo-toasts); ⬜ no skeletons
> for most loads (bare spinners); ⬜ inline form validation is thin.

---

## Part B — The extraction plan (phased, mapped to our vanilla sim)

Each phase is sim-only, behind existing overlays, and desktop-safe. Ordered by leverage.

**Phase 0 — Aesthetic (A8) + UX (A10) quality-bar pass + pattern set (A9)** — the "make it look & feel loved" work
- Encode the A8 (look) **and** A10 (behavior) checklists as QA gates and run them over the whole ui-map
  (desktop + mobile) plus the key flows.
- Fix aesthetics: **orphan-colored elements** (route status/progress/badges through accent+status roles),
  **stray/mixed shadows** (one elevation ramp), **density outliers** (tune the sparse console hub / cramped
  rows to medium), **off-scale paddings**.
- Fix UX: replace blocking `confirm()` deletes with **undo-toasts**; add **skeletons** shaped like content
  for loads; make custom overlays **trap focus + Esc-close + restore focus**; add **inline form validation**;
  ensure the same shortcut/gesture behaves the same everywhere.
- Codify our **pattern set** (list-page · detail-drawer · wizard · chat · dashboard · empty/error) with both
  bars baked in, and make every app conform. Acceptance: each screen/flow passes A8 **and** A10; the ui-map
  reads as one coherent, self-explaining system.

**Phase 1 — Elevate the token layer to an Astryx-style cascade** (`sim/overlay/tokens.js`)
- Add first-class **spacing, type, radius, elevation, motion** ramps + **status roles** as CSS variables.
- Refactor nothing visually — just expose the ramps so future work reads tokens, not magic numbers.
- Acceptance: ui-map pixel-identical (tokens resolve to today's values); new vars available.

**Phase 2 — Theming (system ≠ theme)** 
- Define 2–3 themes as `:root[data-theme=…]` override blocks (start: `default`, `neutral`, `midnight`).
- Add a theme switcher in the console (reuse the light/dark plumbing); persist choice.
- Acceptance: switching restyles every app via variables only; no markup changes; default == today.

**Phase 3 — Accessibility pass (system responsibility)**
- Global focus-visible ring token; add `visually-hidden`; ARIA roles on nav/dialog/list/tabs; label icon
  buttons; verify keyboard paths (Esc closes overlays, arrow-keys in lists) and AA contrast.
- Acceptance: automated axe-style check in the QA harness returns 0 criticals per app.

**Phase 4 — Fill the highest-value component gaps** (as sim components/overlays)
- Form controls: **Switch, Slider, Date input, Typeahead, Multi-selector** (used by real business flows).
- Overlays: **Hover-card, Lightbox** (drive/mail previews).
- Utility: **Visually-hidden**, **Skeleton** unification.
- Acceptance: each new pattern demoed in the app that needs it + added to the ui-map.

**Phase 5 — Conventions & agent source-of-truth ("earned by measurement")**
- One naming convention doc for our overlay classes/tokens; keep this file + `ALIGNMENT-CHANGELOG.md` +
  the mobile/desktop ui-map + QA harness as the canonical, machine-readable record.
- Acceptance: an agent can regenerate the ui-map and diff against baseline to catch regressions.

**Port note (to the live platform):** every phase maps cleanly to real source later — the token cascade and
themes become each app's stylesheet `:root`; the a11y defaults and new components fold into the shared
`development/design/bina-ui.css`. Nothing here requires React or StyleX.

---

## Part D — A8 + A10 completion matrix (the "don't miss anything" plan)

Goal: satisfy **every** A8 (aesthetic) and A10 (UX) checklist item across every surface. Key enabler: our
overlays inject **CSS *and* JS at runtime into every app** — that is sim-only (no real source edited) yet
can reach the real apps' behavior/appearance. So far more is achievable than "port-only". Column key:
**S**=done · **~**=partial · **·**=todo · **PORT**=needs real source (can't do even via overlay).

### A8 — aesthetic bar
| # | Item | Mechanism (sim/overlay) | Status |
|---|---|---|---|
| A8.1 | No orphan/stray colors — accent+status reach every element | per-app CSS audit from the ui-map → override stray hexes to token roles | · |
| A8.2 | One radius scale | global CSS: normalize outlier radii to `--radius-*` (guarded) | · |
| A8.3 | One shadow/elevation ramp — no stray shadows | global CSS: map ad-hoc `box-shadow` to `--elev-*`; kill stray ones | · |
| A8.4 | Medium density (not sparse, not cramped) | targeted CSS: tighten sparse console-hub desktop; loosen cramped rows | · |
| A8.5 | Gaps/paddings on the spacing scale | audit + snap outliers to `--space-*` where safe | ~ |
| A8.6 | Heading↔body weight contrast; numbers bold | mostly holds; spot-fix | ~ |
| A8.7 | Every state present: hover/**focus**/active/disabled/loading/empty/error | focus ✅ (tokens); add missing hover/disabled affordances via CSS | ~ |
| A8.8 | Motion only functional | holds (reduced-motion guard ✅) | S |

### A10 — UX bar
| # | Item | Mechanism (sim/overlay) | Status |
|---|---|---|---|
| A10.1 | Loading = **skeleton** shaped like content, not bare spinner | overlay: replace spinners with skeleton blocks (mock knows load points) | · |
| A10.2 | Empty → next action; Error → recovery | chat ✅; add to drive/docs/mail empty+error via overlay | ~ |
| A10.3 | Destructive → **undo-toast** not blocking confirm | native `confirm()` is synchronous → can't wrap async; **PORT** (or intercept specific delete buttons in overlay w/ styled dialog) | PORT/~ |
| A10.4 | Every action → immediate feedback | holds in our surfaces; verify per app | ~ |
| A10.5 | Same shortcut/gesture everywhere | Ctrl-K palette ✅; **global Esc closes any overlay** across apps | · |
| A10.6 | Overlays trap focus + Esc + restore | our overlays ✅; **global Esc for real-app overlays** | ~ |
| A10.7 | You always know where you are (active nav/title/breadcrumb) | holds (active nav + titles) | S |
| A10.8 | Inline form validation, forgiving inputs | our forms ~; real-app forms **PORT** | ~/PORT |

### Execution order (this batch → next)
1. **Global Esc-closes-overlay** across every app (A10.5/A10.6) — one overlay handler.
2. **Skeletons** for the data grids/loaders (A10.1) — overlay CSS+hook.
3. **Aesthetic pass from the ui-map**: orphan colors, stray shadows, density (A8.1/A8.3/A8.4) — per-app CSS.
4. **Empty/error affordances** for drive/docs/mail (A10.2).
5. Document the true PORT residue (A10.3 undo, A10.8 real-app inline validation) — not fakeable in-sim.

> "100%" therefore means: **100% of what the sim/overlay layer can reach**, with the two genuinely
> source-bound items (async-undo on native confirm, deep inline validation inside real app forms)
> explicitly listed as port-only — not silently skipped.

## Part C — What to do next
Start **Phase 1 + 2** together (token ramp + a `neutral`/`midnight` theme + switcher): highest visible
payoff, zero risk to desktop (pure variable additions), and it unlocks everything else. Then the
**Phase 3 accessibility pass** is the biggest quality jump. Phase 4 fills the component backlog by need.
