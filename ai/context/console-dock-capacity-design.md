# The dock's capacity — why 40 tiles do not fit, and how to make it always fit

**Status:** SHIPPED 2026-10-05 — the recommendation (§5 (b), specified in §6) is implemented and
measured, and the five questions in §8 were decided as the defaults §8 lists. This file stays the
specification: read it before changing the dock's geometry. Bug:
`issues/console-desktop-dock-overflows-its-pill-and-hides-17-apps.yaml` (resolved).
**What shipped, in one line:** `platform-base/console/static/dock-budget.js` (the pure budget) spent by
`desktop.js`'s `buildDock()` — tiles that fit, one «עוד» door in the last slot, everything else in the
grouped launcher panel with a filter; measured by `scripts/ui-coverage/dock-fit.py` at 1294/1440/1920
(0 tiles outside the pill, 0 off screen, panel 43/43) and gated by `scripts/refactor/dock-fit-lint.py`
in WARN mode for one release.
**Scope:** the console's desktop-mode dock (`platform-base/console/static/desktop.js` `buildDock()`,
`.dk-dock` / `.dk-ic` in `desktop.css`). The classic rail, the phone bar and the palette are outside
it — except where they are the answer.

**The one sentence:** the dock is a flat, uncapped row whose width is a function of how many apps and
linked machines the office has, so it can only ever be correct by accident; the cure is to make its
geometry a function of the **viewport** alone and let the app set live inside it (visible slots + one
overflow door), which is the decision this platform already made for the rail and never applied here.

---

## 1. Measured today (2026-10-05, live console, headless Chromium)

Reproduction (read-only): `ui-capture:latest` on `traefik-network`, `http://console:8000/`, force
`window.BinaDesktop.enable()`, then read `.dk-dock` / `.dk-ic` rects. Scripts, raw JSON and PNG
strips: `ci-artifacts/dock-overflow/` (also `tmp/dock-probe/`).

| viewport (CSS px) | tiles | pill box | content | inside pill | outside pill | fully off-screen | unreachable by pointer |
|---|---|---|---|---|---|---|---|
| 1294×810 (13" retina, the owner's) | 40 | 1254 | 2189 | 23 | 17 | **16** | **17** |
| 1440×900 (repo profile `desktop`) | 40 | 1400 | 2189 | 25 | 15 | **13** | **14** |
| 1920×1080 | 40 | 1880 | 2189 | 34 | 6 | **5** | **5** |
| 2560×1440 | 40 | 2187 | 2190 | 40 | 0 | 0 | 0 |

* `overflow-x` is `visible` at every width and `scrollWidth (2189) > clientWidth` — the content is
  there and cannot be scrolled to (`scrollable: false`). The only scrolling dock is
  `.dk.compact .dk-dock{overflow-x:auto}` (`desktop.css:290`), reachable only below
  `CFG.MIN_WIDTH = 1024` (`desktop.js:29`), i.e. never at a width where the desktop mode is even on.
* Unreachable at 1294×810, in dock order: `computers.vps1`, `connections`, `dgo-extend`,
  `connections.hp-laptop`, `dgo-extend.hp-laptop`, `connections.vps1`, `dgo-extend.vps1`, `install`,
  `settings` (הגדרות מסוף), `git-accounts`, `hello-bina.vps1`, `hello-bina`, `browser42` (דפדפן
  הלשכה), `console-home.hp-laptop`, `console-home.vps1`, `native:memory` (זיכרון) — and
  «כל החלונות», the Exposé tile, which is appended last and is therefore always the first casualty.
  At 1920×1080: `browser42`, both linked-office «המרכז» tiles, `native:memory`, «כל החלונות».
* In desktop mode `#app` is `display:none` (`desktop.css:13`; measured `railHidden: true`) — the dock
  *is* the launcher here. The survivor is search: Ctrl-K opened 38 `.pal-item` rows
  (`app.js:467-512`). So the tail is reachable by typing a name, and unreachable by looking.

## 2. The mechanism, exactly

Three defects in the same eight lines, and they compound:

1. **`max-width` caps the box, not the content** — `desktop.css:56-58`:
   `.dk-dock{display:flex;gap:8px;padding:8px 10px;max-width:calc(100vw - 40px)}`. No `overflow`
   (⇒ `visible`), no `flex-wrap` (⇒ `nowrap`). The flex container is capped at `100vw - 40`; its
   content keeps its intrinsic width and is painted outside it.
2. **Nothing shrinks, and that is deliberate** — `desktop.css:60-62`: `.dk-ic{width:46px;
   height:46px;flex:none}` (`flex:0 0 auto`). The container's min-content width is therefore its
   full preferred width. *Today's tiles are not distorted*: all 40 measure 46×46. The distortion
   risk belongs to the naive fix — drop `flex:none` or add `min-width:0` and the width falls below
   46 while the height stays 46: non-square tiles with a 24px glyph in them.
3. **The clip is the viewport, and RTL decides the side** — `desktop.css:19-20`:
   `.dk{position:fixed;inset:0;overflow:hidden;direction:rtl}`. Flex main-start is the right edge in
   RTL, so the excess (935px at 1294) runs off to the LEFT, past the pill's left border, and is cut
   dead at `x=0`. Nothing can scroll it back.
4. **The builder never measures** — `desktop.js:1137-1172`: `modules().forEach(...)` + `.sep` +
   natives + one all-windows tile. `updateDock()` (`:1174-1178`) only toggles a `run` class;
   `refresh()` (`:1464`) rebuilds the same unbounded row.

Two smaller defects live in the same block and deserve the same pass:

* **Tooltips are clipped at the row's ends** — `.dk-ic .tip{position:absolute;bottom:58px;
  left:50%;transform:translateX(-50%)}` (`desktop.css:76`) is centred on its tile with no
  viewport clamp, so the tip of the outermost tile hangs outside the screen.
* **The row is visually asymmetric when it overflows**: centred, overflowing only at main-end, so
  the right side keeps a 31px margin while the left has none — the "not uniform" half of the report.

## 3. Why it grows without limit

Width is closed-form: **W(N) = 54·(N + K + 1) + 27 px** — 46px tile + 8px gap, one 5px separator,
20px padding, 2px border; K = natives (1 today: `desktop-memory.js:888`). With K=1, **W = 54N + 135**.
The cap is `100vw - 40`, so the dock fits only while **N ≤ floor((v − 175) / 54)**:

| viewport | 1294 | 1440 | 1512 | 1728 | 1920 | 2560 |
|---|---|---|---|---|---|---|
| max tiles that fit | 22 | 25 | 26 | 28 | 34 | 46 |
| needed today (38 modules → 40 tiles) | −935px | −789px | −717px | −525px | −309px | +330px |

N only grows, in two independent directions:

* **New apps**: every enabled app that declares `routing[].module` compiles into
  `.generated/registry/console.modules.yaml` and adds 54px.
* **Linked offices**: an app that runs on this machine AND on a linked office is **one tile per
  machine** — `<alias>` and `<alias>.<office>`, each with the `is-remote` corner mark
  (`desktop.css:68-73`, `ai/context/dgo-remote-apps.md:105`). Today: 35 compiled tiles = **9 local +
  26 remote** (`16 × .vps1`, `10 × .hp-laptop`); `/api/modules` = 38 = 35 + 2 console-own views
  (`install`, `settings`) + 1 peer-only `hello-bina`. Two thirds of the dock is the *same apps on
  other machines*.

Nothing in the system can see the problem: `bbox ui-map` never captures desktop mode (no `dk-on`
under `scripts/`), the sim — the spec the live UI is ported toward — has no dock at all, and
`platform-navigation-design.md:776-778` already records that gap; `platform-base/console/test_app.py`
asserts nothing about the desktop; gate G9 skips `/static/`; G27's target list does not include
`desktop.css`. So the dock crossed its cap around its 21st tile and no gate, test or design surface
was ever going to say so.

## 4. The platform already decided this — for the rail

`ai/context/platform-navigation-design.md` is a binding navigation spec with an overflow law keyed to
the number of destinations (`:205-215`, restated `:520-534`):

* ~16 → groups + labels + one scroll container; "the ⌘K palette is the fast path";
* 20–24 → a **filter field inside the nav** (never a modal), group state remembered;
* 40 → filter mandatory, groups collapsed except the one holding the active app;
* 80 → "the rail stops being the whole IA: **pinned (≤6) + recent (≤5) + the open group + «כל
  האפליקציות» launcher** (grid page with search). Keep the top ~12 visible; **make the tail
  searchable, never scroll-only**."

Its own gate for the launcher work — "P6 — Only when the estate grows past ~24 destinations.
Pinning/favourites, recents, and the «כל האפליקציות» launcher. **Not before**" (`:780-786`) — is
**satisfied today: 38 destinations**. And its invariants (`:637-644`) state the property the dock
breaks: *"The rail's occupied width is a function of viewport + state only; no content can widen
it"* and *"Nav height never exceeds the viewport, and the scroll lives in exactly one container"*.
The dock's occupied width is **exactly its content**, and the height of the row is fine while 40% of
it is off-screen.

The decision recorded for the *rail* is therefore the design license for the *dock*, and the reusable
parts already exist:

| need | already in the repo |
|---|---|
| cap a list and reveal the rest ("Priority+") | `platform-base/bina-ui/bina-nav.js:254-272` (`showMore: N` → `.bnv-rest` + `.bnv-more`), CSS `bina-nav.css:289-296` |
| the full app set as a grouped grid, registry-driven | `renderHome()` `app.js:351-383` + `.home-grid{repeat(auto-fill,minmax(84px,1fr))}` `style.css:885` |
| an all-apps screen that reads the same registry | `apps/app-management` (`app-management/static/app.js:196-200`) |
| search over every module | `openPalette()` `app.js:467-512` (already reachable from the top bar `desktop.js:1014` and from inside a window `:1212-1216`) |
| cap a bar and push the tail into "עוד" | phone bottom nav `app.js:514-545` |
| fit N things into a viewport by measuring | expose's column search `desktop.js:818-827` |

## 5. The options, with the criterion that decides them

The owner's requirement is "always good, stable, uniform, no glitches". Read literally, that is one
testable property, and it is the only criterion worth ranking by:

> **Does the dock's geometry depend on the number of apps?** If yes, it is a future glitch — every
> install, every linked office, every zoom level and every screen is a new chance to break.

| # | Option | Geometry depends on N? | Cost | Verdict |
|---|---|---|---|---|
| a | **Scale tiles to fit** (keep the row, shrink) | partially (size shrinks as N grows) | tiny | **No.** 46px is already at Apple's 44px floor / Material's 48dp; the floor is reached at ~25 tiles on a 1294 viewport, i.e. immediately. Distorts the visual rhythm; turns a fit problem into a legibility problem. |
| b | **Slot budget + one overflow tile** ("עוד") → launcher grid | **no** — slots are `f(viewport)` | medium (one pure function + one CSS block) | **Recommended.** Nothing can ever paint outside the pill; the dock's shape is identical at 12 apps and at 80; installing an app never moves an existing tile. Windows 11's chevron and GNOME's App Grid are this. |
| c | **Grouped clusters + separators** (ראשי / עסק / תשתית / הגדרות) | yes, still one-dimensional | medium | Good *inside* the launcher and as a secondary cue in the dock; not sufficient alone. Cannot cap. |
| d | **Pinned (≤6) + recent (≤5) + the rest** | no | medium + product decisions | The rail spec's P6 answer. Excellent perceived stability; needs a persistence model and a rule for what leaves the dock. Natural pairing with (b): the pinned set occupies slots, everything else lives behind «עוד». |
| e | **Pages / paging dots** | no | medium | Very stable, but adds a navigation depth and RTL scroll-mapping care to a surface that currently has none. Only worth it if the owner wants the dock to *be* the launcher. |
| f | **Search-first** (palette as the primary door) | no | already exists | Already true: Ctrl-K finds all 38. But a dock that asks you to remember a name is not a launcher — keep it as the accelerator, not the answer. |
| g | **Two rows / a shelf that grows upward** | **yes** (height ∝ N) | tiny | **No.** The pill's shape changes with every install, it fights the bottom edge, and the app's own UI gets less room. |
| h | **Make the row a horizontal scroller** (macOS/ChromeOS shelf) | no (bounded box) | tiny (CSS only) | *Viable fallback*: `overflow-x:auto` + hidden scrollbar + edge fade; safe by construction and needs no JS. But it hides apps behind a drag gesture with no visible count — against "never looks wrong" and against the rail spec's own "searchable, never scroll-only". Use it *inside* the overflow panel, not on the dock. |

**Recommendation: (b), with (d) as the follow-up the rail spec already scheduled, and (c) as the
shape of the overflow panel.** Rationale in one line: it is the only option where the dock's geometry
is a function of the viewport alone, and it is the option the platform's own navigation spec already
picked for the sibling surface.

## 6. The recommended design

### 6.1 The contract (what "like nature" means, testably)

1. The dock's **outer box** is a function of the viewport only. `content ≤ box` at every width, every
   zoom, every N — so nothing can ever paint outside the pill, and no tile can ever be clipped.
2. **Tile size is constant** (46×46, ≥44px target, never scaled by count). Scale is a function of
   proximity (hover), never of how many apps exist.
3. **Installing an app never moves an existing tile.** With slots free it appends; with slots full it
   appears behind «עוד». No reflow, no layout shift, no "everything jumped" moment.
4. **One overflow door, always in the same place** (last child = leftmost in RTL), always visible
   when `N > slots`, and it says how many are behind it.
5. The tail stays **grouped and searchable** in the overflow panel (the existing `m.group` order and
   the palette's filter), never "scroll-only".
6. The **`is-remote` mark and the offline state** appear on every tile wherever it is drawn
   (`dgo-remote-apps.md:105`), including tiles rendered inside the overflow panel.
7. Nothing depends on **hover alone**; every tile keeps an `aria-label` (today `remoteTip(m)`) and a
   keyboard path (Ctrl-K, Alt+\`, and expose on `E`).
8. **No second scroller** on the screen (`digital-office/sim/flow-qa.py:424-457`), and no
   page-level horizontal scroll (`flow-qa.py:531-537` — the repo's own rule: "horizontal scroll on a
   whole page is never a design decision").

### 6.2 The slot budget — one pure function, measured once

Mirror `platform-navigation-design.md` §3.14's code shape (a pure decision function + one CSS block
keyed on a state attribute + no magic numbers):

```js
// pure, unit-testable in node — no DOM, no globals
resolveDock({ available, count, tile: 46, gap: 8, pad: 20, sep: 5 })
  → { slots, showMore }      // slots = clamp(floor((available - pad - sep) / (tile + gap)), 3, count + 1)
                             // showMore = count > slots
```

* Called on mount, on `refresh()` (registry change) and from a **`ResizeObserver` on the dock's
  container** — never on a timer, never per frame. Zoom is a resize, so it is covered for free.
* The overflow tile occupies the **last** slot, so `slots - 1` app tiles are shown when `showMore`.
* Sizes/gaps/padding become custom properties on `.dk` (`--dock-tile`, `--dock-gap`, `--dock-pad`) —
  the design's own rule: "a number that exists in two places is a future inconsistency".
* CSS then needs exactly one new declaration: `.dk-dock{overflow:hidden}` (belt and braces — the
  budget already makes overflow impossible, and the clip turns any future bug into a visible edge
  instead of icons on the wallpaper).
* Degenerate cases are specified, not discovered: `count = 0` → the dock renders natives +
  «כל החלונות» only; viewport too narrow for 3 slots → the dock keeps its 3 slots and lets the
  compact mode take over below `MIN_WIDTH` as today.

**Resulting dock at each width today (40 tiles, 38 apps):**

| viewport | available | slots | rendered | «עוד» |
|---|---|---|---|---|
| 1294 | 1254 | 22 | 21 apps + «עוד» | opens the panel with the other 18 |
| 1440 | 1400 | 25 | 24 + «עוד» | 15 |
| 1920 | 1880 | 34 | 33 + «עוד» | 6 |
| 2560 | 2520 | 46 | 40, no «עוד» | — (nothing is hidden, and nothing looks different) |

The last row matters: on a big screen the dock degrades *into today's good behaviour* with no special
case, and on the owner's screen it becomes a stable 22-slot shelf.

### 6.3 The overflow door's content (reuse, do not invent)

The panel behind «עוד» is the **existing** grouped launcher: the same registry, the same `m.group`
ordering, the same `.htile` grid as `renderHome()` (`app.js:351-383`, `style.css:885`) and the same
search field pattern as BinaNav's in-nav filter (`bina-nav.js:277-293`). It opens as a window/popover
in desktop mode (the desktop already has window chrome and the memory tool's panel pattern), with the
first `~12` tiles uncapped and the rest behind BinaNav's Priority+ control if the estate keeps
growing. Nothing about it is new — which is exactly why it will not drift.

### 6.4 Pinning, recents, and the tile-per-machine question

* **Pinning (≤6) + recents (≤5)** is the rail spec's P6, trigger now met. In the dock it means: the
  slots show pinned + recents + the overflow door, and pinning **adds a block, never re-sorts** the
  existing order (`platform-navigation-design.md:527-528`).
* **One tile per (app × machine)** is a *product* decision this document deliberately does not take.
  It is the single largest lever on N — with three machines, 26 of 40 tiles are linked-office copies
  — and two shapes are defensible: (i) status quo, honest but 3× the width; (ii) one tile per app,
  with its linked-office twins one level in (a long-press/context menu, or in the overflow panel),
  keeping the `is-remote` mark on the parent tile when any twin is offline. Option (ii) alone takes
  the dock from 40 tiles to ~14 and would let the whole estate fit on the owner's screen without any
  overflow door at all. Both are compatible with §6.2; the owner should pick, because the dock's tile
  set is a statement about what "an app" is.

### 6.5 What must NOT be done

* Do **not** let `.dk-ic` shrink (`flex-shrink`, `min-width:0`) — non-square tiles below the 44px
  floor, the exact "glitch" class the owner named.
* Do **not** wrap to a second row — the pill's height would become a function of N.
* Do **not** solve it by widening `max-width` or by assuming "the office will not grow".
* Do **not** make the dock the horizontal scroller (option h) as the primary answer: apps behind a
  drag are apps nobody finds, and the rail spec says so in writing.
* Do **not** lose the `is-remote` / offline mark on tiles that move into the overflow panel.
* Do **not** ship it without the measurement in §7 — this bug exists because nothing measured.

## 7. How to prove it (and what to wire so it cannot come back)

The honest proof is the probe used for this report, at the profile widths, with desktop mode forced
on. Essential recipe:

```python
ctx = browser.new_context(viewport={"width": 1294, "height": 810})
page.goto("http://console:8000/", wait_until="domcontentloaded")
page.wait_for_function("!!window.BinaDesktop"); page.evaluate("window.BinaDesktop.enable()")
page.wait_for_selector(".dk-dock .dk-ic")
m = page.evaluate("""() => { const d = document.querySelector('.dk-dock');
  const r = d.getBoundingClientRect(); const ic = [...d.querySelectorAll('.dk-ic')];
  return { w: r.width, content: d.scrollWidth, tiles: ic.length,
           outside: ic.filter(e => { const b = e.getBoundingClientRect();
             return b.x < r.x - .5 || b.right > r.right + .5; }).length,
           offScreen: ic.filter(e => e.getBoundingClientRect().right <= 0).length }; }""")
assert m["content"] <= m["width"] + 1 and m["outside"] == 0 == m["offScreen"]
```

* **Add it as a gate** (`scripts/refactor/run-gates.py`) at 1294/1440/1512/1920/2560 from
  `scripts/ui-coverage/view-profiles.yaml`. Today the change surface is unguarded: G27's `TARGETS`
  exclude `desktop.css`, G9 skips `/static/`, and `console/test_app.py` has no desktop assertion.
* **Close the capture gap**: `scripts/ui-coverage/capture.py` never sets the `do-desktop`
  localStorage flag (`desktop.js:24`), so `./bbox ui-map` cannot show this surface. Either capture one
  desktop-mode panel per profile or record in the nav spec + `PORT-PLAN.md` why it stays uncaptured —
  the same gap the nav spec already flags at `:776-778`.
* **Regression**: `python3 scripts/refactor/run-gates.py --all` (never trust `$?` under WSL) and
  `./bbox ui-map --profile desktop` to prove the classic shell is untouched; the offline
  `digital-office/sim/flow-qa.py console|layout` sweep for JS errors (the sim has no dock, so it
  cannot cover this — do not mistake it for coverage).

## 8. Decisions this document needs from the owner

1. **Tile model**: keep one tile per (app × machine) (40 tiles today), or one tile per app with its
   linked-office twins one level in (~14 tiles)? — *the largest single lever on the problem.*
2. **The overflow door**: a grouped launcher grid + search (this recommendation), or pinned(≤6) +
   recents(≤5) as the rail spec's P6 describes (which then needs a rule for what leaves the dock)?
3. **Slot budget floor**: is 3 slots (plus «עוד») the minimum before the dock is useless, or should a
   narrow desktop simply hide the dock and lean on the palette?
4. **The dock's height/dimension tokens**: accept the `--dock-*` custom properties (nav spec §3.14
   rule 2 — "no magic numbers"), or keep the literals in `desktop.css`?
5. **The gate**: block CI on the dock measurement from day one, or warn-first for one release
   (`AGENTS.md`'s staged-rollout rule for a tightened contract)?

## Sources (external)

* macOS Dock: user-set tile size and magnification, never two rows — <https://support.apple.com/guide/mac-help/mchlp1119/26/mac/26>, <https://www.heise.de/en/news/Icons-in-macOS-26-Fighting-the-Squircle-Prison-11075561.html>
* ChromeOS shelf's explicit scrollable-overflow mode — <https://chromium.googlesource.com/chromium/src/+/12802e63cae3af35930570920af94d978f5d6bbe/ash/shelf/shelf_view.cc>
* GNOME 40+ dash: fixed-size row, the App Grid absorbs the estate — <https://gitlab.gnome.org/Teams/Design/initiatives/-/work_items/78>
* Windows 11 taskbar overflow chevron; the removal of Windows 10 icon resizing — <https://onewebcare.com/windows/windows-11-taskbar-overflow/>
* KDE Plasma filed the same bug: items do not shrink, the panel overflows — <https://bugs.kde.org/show_bug.cgi?id=473420>
* iOS Home Screen pages + App Library; Android drawer/folders — <https://setapp.com/how-to/app-library-iphone>, <https://developer.android.google.cn/design/ui/mobile/guides/layout-and-content/layout-and-nav-patterns>
* Hit-target floors: Apple HIG 44pt — <https://developer.apple.com/design/human-interface-guidelines/buttons>; Material 48dp — <https://support.google.com/accessibility/android/answer/7101858>
* The CSS mechanics behind this bug: `flex-shrink` cannot create space — <https://developer.mozilla.org/en-US/docs/Web/CSS/flex-shrink>, and `overflow:visible` is not a scroll container — <https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/overflow>; measuring layout on resize — <https://developer.mozilla.org/en-US/docs/Web/API/ResizeObserver>
