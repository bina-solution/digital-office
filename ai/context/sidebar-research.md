# Raw research appendix — primary sidebar / navigation rail (2026-09-25)

This is the EVIDENCE behind `platform-navigation-design.md` (v2) §1g/§1h: every figure carries a
link, and anything not sourced is explicitly marked **(judgement)**. The spec is the decisions;
this file is the readings. Numbers here are not binding on their own — where the spec disagrees
with a recommendation below, the spec wins.

Collected in one pass on 2026-09-25 for this deployment (Hebrew RTL console, ~16–40 destinations,
desktop-first). Two caveats recorded by the author: `m3.material.io` and `vercel.com/changelog`
return JS-rendered empty bodies, so the M3 figures come from the published size constants plus a
Material-3-conformant component's spec doc; and no NN/g article measuring "focus mode" collapse
was found in the time box, so §5 there is Apple/GitLab-sourced plus judgement.

---

# Primary sidebar / navigation rail — numbers-first reference (RTL, Hebrew, iframe console, desktop-first)

Scope: one web console embedding ~20 business apps in an iframe. Targets: Mac 1440–1728px (primary), tablet 1024px, phone 390px.
Convention: every sourced number carries a link. Unsourced numbers are marked **(judgement)**.

---

## 1. Width, sizing, active treatment

**Expanded width**

| Source | Value |
|---|---|
| Material 3 nav drawer (standard) | **360dp** ([M3NavigationSizes.drawerWidth](https://pub.dev/documentation/material_design/latest/material_design/M3NavigationSizes/drawerWidth-constant.html), spec [M3 navigation drawer](https://m3.material.io/components/navigation-drawer/specs)) |
| M3 extended rail / expressive rail expanded | **256dp** ([M3NavigationSizes.extendedRailWidth](https://pub.dev/documentation/material_design/latest/material_design/M3NavigationSizes/extendedRailWidth-constant.html)); **220–360dp, default 360dp** ([M3 nav-rail skill doc](https://cdn.jsdelivr.net/china/npm/@universal-material/web@3.9.4/skills/navigation-rail/SKILL.md)) |
| Common product/Tailwind convention | **224px (`w-56`)** ([tailwind nav reference](https://github.com/pproenca/dot-skills/blob/master/skills/.experimental/tailwind-responsive-ui/references/nav-tab-bar-mobile.md)); **240px** is the classic fixed left-nav offset ([example impl.](https://repositori.usu.ac.id/bitstream/handle/123456789/107162/M.Abel%20Adyatma_Perancangan%20Website%20Coffee%20Shop%20%E2%80%98My%20Coffee%E2%80%99%20sebagai%20Media%20Promosi%20Digital%20Berbasis%20Web_compressed.pdf?sequence=2&isAllowed=y)) |
| Notion ships a **narrower-than-users-want** sidebar; a third-party extension exists purely to widen it | ([notion-wide-sidebar](https://github.com/manuelmeurer/notion-wide-sidebar)) |

**Recommendation for this console:** expanded **280px** at ≥1280px viewport, **264px** at 1024–1279px, hard floor **240px** **(judgement)**. Rationale: 20+ Hebrew app names + a group label need ≥200px of text run; M3 allows up to 360dp but 360px is 25% of a 1440px screen and the iframe already eats chrome.

**Collapsed rail / icon-only**

- M3 collapsed rail: **80dp**, with a **96dp** default in the expressive spec ([pub.dev M3NavigationSizes.railWidth](https://pub.dev/documentation/material_design/latest/material_design/M3NavigationSizes/railWidth-constant.html), [rail skill doc](https://cdn.jsdelivr.net/china/npm/@universal-material/web@3.9.4/skills/navigation-rail/SKILL.md)).
- **Recommendation: 72px** rail (64px min) **(judgement)** — 80px is generous when the rail sits next to an iframe; 72px still gives a 48px hit area + 12px inset each side.

**Item metrics (M3, sourced)**

- Item container / destination height: **64dp** default; **56dp** for rail destination (indicator + label); gap **4dp** collapsed, **0dp** expanded ([rail skill doc](https://cdn.jsdelivr.net/china/npm/@universal-material/web@3.9.4/skills/navigation-rail/SKILL.md), [M3NavigationSizes.railDestinationHeight](https://pub.dev/documentation/material_design/latest/material_design/M3NavigationSizes/railDestinationHeight-constant.html)).
- Leading inset of the pill: **16dp**; active indicator pill **56×32dp** (collapsed) / content-sized 56dp-height pill (expanded), corner **full** ([rail skill doc](https://cdn.jsdelivr.net/china/npm/@universal-material/web@3.9.4/skills/navigation-rail/SKILL.md), [indicatorWidth 56dp](https://pub.dev/documentation/material_design/latest/material_design/M3NavigationSizes/indicatorWidth-constant.html), [indicatorHeight 32dp](https://pub.dev/documentation/material_design/latest/material_design/M3NavigationSizes/indicatorHeight-constant.html)).
- Icon: **24dp** ([rail skill doc](https://cdn.jsdelivr.net/china/npm/@universal-material/web@3.9.4/skills/navigation-rail/SKILL.md)).
- Label: **12sp** collapsed / **14sp** expanded; active weight **700** ([rail skill doc](https://cdn.jsdelivr.net/china/npm/@universal-material/web@3.9.4/skills/navigation-rail/SKILL.md)).
- State layer: hover **8%**, focus **10%**, pressed **10%**, confined to the pill ([rail skill doc](https://cdn.jsdelivr.net/china/npm/@universal-material/web@3.9.4/skills/navigation-rail/SKILL.md)).

**Denser desktop-product values (Tailwind reference implementation, sourced as code)**

- Item: `gap-3 px-3 py-2 text-sm rounded-lg` with 20px icon (`h-5 w-5`) → **row height ≈36px, icon 20px, gap 12px, radius 8px, label 14px** ([ref](https://github.com/pproenca/dot-skills/blob/master/skills/.experimental/tailwind-responsive-ui/references/nav-tab-bar-mobile.md)).
- **Recommendation (judgement): row height 36px, item padding 8px 10px, icon 20px, icon↔label gap 10px, radius 8px, label 14px/500, line-height 20px, 2px vertical gap between items, 4px inside a group, 16px between groups, 12px horizontal item inset.** This is deliberately between M3 (too airy for a console) and the compact Linear refresh.

**Active-item treatment**

- Linear's refresh made the **whole nav a few notches dimmer** so it "recedes" once the user has arrived, and specifically reduced icon size, muted inactive text, and added vertical padding — i.e. contrast is spent on **content**, not chrome ([Linear, Mar 2026](https://linear.app/now/behind-the-latest-design-refresh)).
- Linear also treats **borders as structure "felt not seen"**: rounder edges, lower-contrast separators, fewer of them ([same](https://linear.app/now/behind-the-latest-design-refresh)).
- **Recommendation (judgement): active = filled 8–10% tinted pill (radius 8px) + text 600 weight + icon at full opacity; inactive label at 60–70% opacity, icon 55–65%; no colored left/right bar except when the app has its own accent color; one 1px hairline (or 0px + 4% surface tint) as the sidebar↔content boundary.** Hover = same tint, no radius change, no size change.

---

## 2. Structure

- **Two levels maximum.** Apple HIG: "In general, show no more than two levels of hierarchy in a sidebar"; deeper hierarchies belong in a split view / content list ([Apple HIG Sidebars](https://developer.apple.com/design/human-interface-guidelines/sidebars), mirror [here](https://github.com/Prisma-Labs-Dev/apple-skills/blob/main/skills/hig/sidebars.md)). GitLab Pajamas: top-level + sub-level, "There is not a third level of depth" ([Pajamas](https://design-gitlab-com-gitlab-org-gitlab-services-f6beaf2fb7fd4cad76.gitlab.io/patterns/navigation-sidebar/)). Fluent 2 Nav: "only supports one level of nesting"; use Tree for deeper ([Fluent 2 Nav](https://fluent2.microsoft.design/components/web/react/core/nav/usage)).
- **Group/section labels:** expanded state shows `<headline>` section headers in title-small / on-surface-variant; headlines **never** appear in the collapsed rail ([rail skill doc](https://cdn.jsdelivr.net/china/npm/@universal-material/web@3.9.4/skills/navigation-rail/SKILL.md)). Apple: use "succinct, descriptive labels" for each group ([HIG](https://github.com/Prisma-Labs-Dev/apple-skills/blob/main/skills/hig/sidebars.md)).
- **Order:** NN/g — keyword-front-load, keep it left-aligned, keep it visible; vertical nav's core benefit is accommodating many **specific** top-level categories so users don't have to dig ([NN/g vertical nav](https://www.nngroup.com/articles/vertical-nav/)). Pajamas: top-level naming and **positioning must stay consistent** across contexts ([Pajamas](https://design-gitlab-com-gitlab-org-gitlab-services-f6beaf2fb7fd4cad76.gitlab.io/patterns/navigation-sidebar/)). **Recommendation (judgement): order = (1) pinned/favourites block, (2) one "ראשי" group with the 5–7 most-used apps, (3) topical business groups, (4) footer utility block. Never re-sort by usage automatically — that destroys spatial memory.**
- **Pinning/favourites:** GitLab: "Pinned items uniquely persist, allowing users to surface important links across groups and projects"; user preference persisted in a **cookie** ([Pajamas](https://design-gitlab-com-gitlab-org-gitlab-services-f6beaf2fb7fd4cad76.gitlab.io/patterns/navigation-sidebar/)). Apple: "When possible, let people customize the contents of a sidebar" — people should decide which areas matter and in what order ([HIG](https://github.com/Prisma-Labs-Dev/apple-skills/blob/main/skills/hig/sidebars.md)).
- **Separators:** M3 expanded items have **0dp** gap → grouping is carried by headlines, not rules; Linear deliberately reduced separators ([rail doc](https://cdn.jsdelivr.net/china/npm/@universal-material/web@3.9.4/skills/navigation-rail/SKILL.md), [Linear](https://linear.app/now/behind-the-latest-design-refresh)). **Judgement: no separators inside a group; at most one hairline above the footer block, and only if the footer block is not already visually detached by 8px+ extra space.**
- **Footer items:** settings/help/account pinned at the bottom of the rail, sized intrinsically and leading-aligned with 16dp inset when expanded, centered when collapsed ([rail skill doc](https://cdn.jsdelivr.net/china/npm/@universal-material/web@3.9.4/skills/navigation-rail/SKILL.md)). **Counter-source:** Apple warns "Avoid putting critical information or actions at the bottom of a sidebar" because window bottom edges get hidden/off-screen ([HIG](https://github.com/Prisma-Labs-Dev/apple-skills/blob/main/skills/hig/sidebars.md)). **Judgement: footer gets only low-stakes, re-findable items (settings, help, account, sign-out), never the only path to a business app.**
- **Header/brand block:** M3 rail reserves **44dp top space** and **20dp vertical-trailing space**; top slot carries the menu button / brand mark, aligned centered when collapsed and leading-aligned with 16dp inset when expanded ([rail skill doc](https://cdn.jsdelivr.net/china/npm/@universal-material/web@3.9.4/skills/navigation-rail/SKILL.md)). **Judgement: brand block = logo mark + name, single line, `text-overflow: ellipsis`, `title`/tooltip with the full name, min-height 56px, collapse button in the same row.**
- **One navigation, two detail levels:** the collapsed and expanded lists must be the **same destination set** at two levels of detail — not product-nav in one state and section sub-nav in the other; that "breaks the user's mental model" ([rail skill doc](https://cdn.jsdelivr.net/china/npm/@universal-material/web@3.9.4/skills/navigation-rail/SKILL.md)).

---

## 3. Many items (10 / 20 / 40 / 80)

Sourced anchors:
- NN/g: more than 7–9 top-tier items in global nav is **acceptable** as long as you plan for it, and vertical nav is exactly the pattern that absorbs a broad hierarchy ([NN/g vertical nav](https://www.nngroup.com/articles/vertical-nav/)).
- M3: the expanded layer **scrolls** when it overflows the rail height; the collapsed layer also scrolls past **~5 items** ([rail skill doc](https://cdn.jsdelivr.net/china/npm/@universal-material/web@3.9.4/skills/navigation-rail/SKILL.md)).
- Fluent 2: Nav "might not show all available items" — overflow is expected and must be designed, not accidental ([Fluent 2 Nav](https://fluent2.microsoft.design/components/web/react/core/nav/usage)).
- Discoverability cost of hiding nav is measurable: hidden nav reduced engagement, dropped task success, raised time-on-task and lowered satisfaction, on **both** mobile and desktop, "exacerbated for desktop" ([NN/g hamburger](https://www.nngroup.com/articles/hamburger-menu-icon-recognizability/)).
- Virtualization is a rendering technique, not a navigation answer — it removes DOM cost, not scroll-hunting (general [virtualization/windowing](https://github.com/sujeet-pro/sujeet.pro/blob/main/content/articles/virtualization-and-windowing/README.md)).

Concrete rules of thumb **(judgement unless noted):**
- **10 items:** flat list, no grouping, no search, no scroll expected at 36px rows (10×36 = 360px, fits any window ≥600px tall).
- **20 items:** group into 3–4 sections with labels; 20×36 = 720px → **scrolls on a 1440×900 Mac** (usable sidebar height ≈ 900 − 56 header ≈ 780px). So at 20 items a **scrollbar is already real** → group first, then add a **filter input** at the top of the sidebar (a "jump to" box that filters in place, never a modal).
- **40 items:** mandatory filter + collapsed-by-default groups; default-open only the group containing the active app; sections remember open/closed state; scroll container **never** nests inside another scroll container.
- **80 items:** sidebar must stop being the whole IA. Show: pinned (≤6) + "recent" (≤5) + open group + **"כל האפליקציות" (All apps) launcher** as a grid page/modal with search. Point 3 of NN/g's own benefits list argues for vertical nav up to broad IAs ([NN/g](https://www.nngroup.com/articles/vertical-nav/)), but 80 persistent rows of scroll is a findability tax, and hidden-behind-one-click nav measurably costs success rate ([NN/g](https://www.nngroup.com/articles/hamburger-menu-icon-recognizability/)) — so keep the top ~12 visible and make the long tail searchable, not scrolled.
- **Virtualization:** only worth it above ~150 DOM rows; at ≤80 rows render everything and rely on grouping **(judgement)**.
- **How premium products avoid a scrollbar-looking nav:** they cap the persistent list (pinned + recents + a few groups), move the long tail into a launcher/search, and scroll only inside a group container with the scrollbar styled to near-invisible (macOS overlay scrollbars) **(judgement, supported by the Fluent 2 "might not show all available items" + NN/g hidden-nav cost sources above)**.
- **Sticky section headers** inside the scroll container: yes; sticky **brand block** above the scroll container: yes; sticky footer: yes; a sticky group header that overlaps the footer: never **(judgement)**.

---

## 4. Responsive behaviour

Sourced breakpoints:
- M3 expressive rail: **<840px rail hidden → use a nav bar; 840–1199px permanent 96dp collapsed rail; ≥1200px permanently expanded 220–360dp**, with `toggle-drawer` collapsing it back to 96dp ([rail skill doc](https://cdn.jsdelivr.net/china/npm/@universal-material/web@3.9.4/skills/navigation-rail/SKILL.md)).
- GitLab Pajamas: **≥1200px visible by default** (user may hide); **≤1199px hidden by default**, revealed by the sidebar icon as an **overlay with a semi-transparent scrim over the page**; the user's cookie preference does **not** change across that breakpoint ([Pajamas](https://design-gitlab-com-gitlab-org-gitlab-services-f6beaf2fb7fd4cad76.gitlab.io/patterns/navigation-sidebar/)).
- Apple: on iPadOS a **sidebarAdaptable** tab view shows either a sidebar or a tab bar, includes a button to switch between them, and adapts automatically to rotation/window resize; "consider using a tab bar first" ([HIG](https://github.com/Prisma-Labs-Dev/apple-skills/blob/main/skills/hig/sidebars.md)).
- Bottom bar destination count: **4–5 main options max** before touch-target size degrades ([NN/g mobile nav primer](https://www.nngroup.com/articles/mobile-navigation-patterns/)); 3–5 primary sections is the practical band ([tailwind nav ref](https://github.com/pproenca/dot-skills/blob/master/skills/.experimental/tailwind-responsive-ui/references/nav-tab-bar-mobile.md)).
- Bottom placement wins on reachability: on 6" + phones the top of the display is the hardest-to-reach zone; keep primary nav in the bottom half ([tailwind nav ref](https://github.com/pproenca/dot-skills/blob/master/skills/.experimental/tailwind-responsive-ui/references/nav-tab-bar-mobile.md)).

**Prescription for this console (judgement, aligned to the sources above):**

| Viewport | Behaviour | Sidebar width | Control |
|---|---|---|---|
| ≥1440px | expanded, always visible | 280px | pin button |
| 1280–1439px | expanded by default, user-collapsible | 264px | pin button |
| 1024–1279px | **auto icon rail**, no scrim, hover-expand | 72px | toggle button, hover-pin |
| 768–1023px | overlay drawer + scrim, closed by default | 280px overlay | hamburger in top bar |
| <768px | bottom tab bar (max **5**: בית, חיפוש, אפליקציות, התראות, חשבון) + "עוד" drawer for the rest | tab bar | tab bar + drawer |

- **Remembering the choice:** persist in a **cookie or localStorage** exactly as GitLab does, and — critically — **do not let the user's stored preference override a breakpoint where the sidebar cannot fit**; GitLab explicitly says the preference "does not change within" the narrow breakpoint ([Pajamas](https://design-gitlab-com-gitlab-org-gitlab-services-f6beaf2fb7fd4cad76.gitlab.io/patterns/navigation-sidebar/)). Precedence **(judgement): explicit user toggle at this breakpoint > layout default for this breakpoint > stored global preference.** Store two independent booleans: `sidebar.mode` (`expanded`/`rail`) and `sidebar.drawerOpen` (mobile only).
- **Auto-collapse on window resize:** Apple recommends automatically hiding/revealing a sidebar when its container window resizes ([HIG](https://github.com/Prisma-Labs-Dev/apple-skills/blob/main/skills/hig/sidebars.md)).
- **Never hide nav by default where it fits:** NN/g's whole position is that visible navigation is the gold standard, and hidden navigation cost success rate on **desktop specifically** ([NN/g hamburger](https://www.nngroup.com/articles/hamburger-menu-icon-recognizability/), [NN/g vertical nav](https://www.nngroup.com/articles/vertical-nav/)).
- **Persist across the iframe boundary:** the sidebar lives in the shell, not in each app, so its state must not reset when the iframe `src` changes **(judgement)**.

---

## 5. Auto-collapse while working (focus mode)

Evidence:
- Apple: "People sometimes want to hide the sidebar to create more room for content details or to reduce distraction… **Avoid hiding the sidebar by default** to ensure that it remains discoverable" ([HIG](https://developer.apple.com/design/human-interface-guidelines/sidebars)).
- GitLab: users hide it "to give focus to the body of the page and minimize distractions" at ≥1200px; while hidden, **hovering the left edge or the sidebar button reveals it as an overlay that can lock in place or be used without disrupting page content** — and it is shown regardless of preference "when the user needs the navigation sidebar to complete a task" ([Pajamas](https://design-gitlab-com-gitlab-org-gitlab-services-f6beaf2fb7fd4cad76.gitlab.io/patterns/navigation-sidebar/)).
- NN/g: when you do hide navigation, you must "think seriously about supporting navigation in other ways" (cross-links, breadcrumbs, hub) ([NN/g mobile nav](https://www.nngroup.com/articles/mobile-navigation-patterns/)).
- Linear frames nav as chrome that should **recede** once the user has arrived, but it recedes by dimming, not by disappearing ([Linear](https://linear.app/now/behind-the-latest-design-refresh)).

**Rules (judgement unless cited):**
- **Never auto-collapse on a timer or on scroll.** Collapse only (a) by explicit user action, (b) on a breakpoint where it cannot fit, (c) via an explicit per-app "focus mode" the user opts into.
- Keep discoverability with three affordances together: **pin button** (always visible), **edge-hover reveal** (a 6–8px hot zone at the sidebar edge, revealed as an overlay, exactly GitLab's model), and **keyboard shortcut** (`Cmd/Ctrl+\` — judgement; document it in a tooltip on the pin button).
- Hover-expand must **not** push content (overlay), and must not steal focus; it closes on mouse-out after ~300ms delay so a diagonal mouse path to a nav item doesn't close it **(judgement)**.
- The active app must remain identifiable while collapsed: highlight the rail icon of the active destination, and put the app name in the shell's top bar **(judgement)**.
- Focus mode must be **per-session, not persisted** by default; make persistence an explicit setting **(judgement)** — otherwise a user who once toggled it can't find their nav.

---

## 6. Accessibility (WCAG 2.2)

Sourced criteria:
- **2.5.8 Target Size (Minimum), AA:** targets at least **24×24 CSS pixels**, or an undersized target passes if a **24 CSS-pixel-diameter circle** centered on its bounding box intersects neither another target nor another undersized target's circle (spacing exception) ([W3C Understanding 2.5.8](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html)). Worked example: menu items of **24 CSS px height pass**, **18 px height fail**; 20×20 with **4px** spacing passes ([same](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html)). 2.5.5 Target Size (Enhanced) is the stricter AAA bar worth aiming at for important links ([same](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html)).
- **2.4.11 Focus Not Obscured (Minimum)** and 2.4.13 Focus Appearance exist as new WCAG 2.2 criteria ([WCAG 2.2 reference list](https://www.w3.org/WAI/WCAG22/quickref/)) — practical implication: a focused nav item must not be hidden behind a sticky header/footer, and the focus ring must be visible against the tinted active pill **(judgement on implementation; criterion itself is sourced from the WCAG 2.2 quickref index)**.
- **1.4.10 Reflow / 1.4.4 Resize** still apply at zoom; the target-size requirement is explicitly **independent of zoom** — you cannot claim zoom creates the spacing ([2.5.8](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html)).
- **2.4.1 Bypass Blocks** and **1.3.1/4.1.2** are standard WCAG 2.x obligations relevant to a persistent nav region ([WCAG 2.2 index](https://www.w3.org/WAI/WCAG22/quickref/)).

**Prescription (judgement, applying the above):**
- Rail items: **min hit area 44×36px**, icon 20px, and the **entire row** is the click target (state layer only inside the pill — M3 does exactly this: "Click target remains the entire item, ripples confined to the pill", [rail doc](https://cdn.jsdelivr.net/china/npm/@universal-material/web@3.9.4/skills/navigation-rail/SKILL.md)). This comfortably clears 24×24.
- Collapsed rail: **48×48px** minimum per icon **(judgement)**; M3's 56×32 indicator inside a 64dp item is the reference ([rail doc](https://cdn.jsdelivr.net/china/npm/@universal-material/web@3.9.4/skills/navigation-rail/SKILL.md)).
- **Landmarks & current page:** one `<nav aria-label="ניווט ראשי">` per nav region (a second one for the footer group is fine with its own label); the active destination carries `aria-current="page"` (or `="true"` for a non-page toggle) — this is the ARIA/WCAG-standard signal for "you are here" **(judgement grounded in WCAG/ARIA practice; the 2.2 criteria index is [here](https://www.w3.org/WAI/WCAG22/quickref/))**.
- **Icon-only rails and screen readers:** every icon-only link needs an **accessible name** that does not depend on the tooltip; the tooltip must be a real element (`role="tooltip"` + `aria-describedby`/`aria-labelledby`), shown on both **hover and focus**, not a `title`-only attribute (title is not reliably exposed and cannot be triggered by keyboard) **(judgement; M3 keeps the item's label in the DOM in both variants — [rail doc](https://cdn.jsdelivr.net/china/npm/@universal-material/web@3.9.4/skills/navigation-rail/SKILL.md))**.
- **Collapsible rail keyboard model (judgement):** collapse/expand is a `<button aria-expanded aria-controls="sidebar-nav">`, not a link; the rail is a list of links (Tab through them, no roving tabindex needed for a vertical `<ul>` of links); the toggle is reachable first in DOM order within the shell header; Escape closes an overlay drawer and **returns focus to the toggle**; on expand, focus stays on the toggle (never jumps into the list); on collapse while focus is inside the list, move focus to the toggle and do not lose it.
- **Announce state changes:** expanding/collapsing a region that is not a dialog should be conveyed by `aria-expanded` on the toggle (plus `aria-hidden`/`inert` removal on the container). Do **not** rely on a live region for something the toggle already announces **(judgement)**.
- **Reduced motion / high contrast:** honour `prefers-reduced-motion` (see §8) and never encode the active item with color alone — pair the tint with weight and/or an icon fill so it survives `forced-colors` **(judgement)**.
- **Bypass:** the shell needs a visible-on-focus "דלג לתוכן" link that jumps past the sidebar to the iframe/main content **(judgement, in service of 2.4.1)**.

---

## 7. RTL (Hebrew, sidebar on the right)

Facts worth pinning:
- Apple defines a sidebar as appearing on the **leading side** of a view ([HIG](https://developer.apple.com/design/human-interface-guidelines/sidebars)) — so in Hebrew the "left sidebar" pattern is the **right** sidebar. All M3/Apple/Fluent guidance about *the* sidebar applies to the leading edge, which is `right` under `dir="rtl"`.
- RTL web layout, including mirrored scrollbars and icon direction, is a known, documented engineering concern for web apps ([Logto: Supporting RTL language layout](https://blog.logto.io/rtl-language-support)).
- Fluent 2's Nav is a leading-edge, one-level list, minimizable ([Fluent 2 Nav](https://fluent2.microsoft.design/components/web/react/core/nav/usage)).

**Rules (judgement, applying the leading-edge definition above):**
- Put the sidebar on the **right** and use **logical properties everywhere**: `inset-inline-start`, `margin-inline-start`, `padding-inline`, `border-inline-end`, `text-align: start`. Zero physical `left/right` in the shell CSS.
- **Icons:** keep app icons unmirrored (universal pictograms such as a printer or a document do not flip); **mirror only directional glyphs** — the collapse chevron, "back/forward", "expand" arrows. Under RTL, the collapse chevron on the right sidebar points **right** to collapse toward the edge and **left** to expand inward — i.e. it points *away from content*, exactly mirroring LTR.
- **Scrollbar side:** with `dir="rtl"` on the scroll container, the scrollbar sits on the **inline-end** edge, i.e. the **left** side of the right-hand sidebar — visually adjacent to the content, not the window edge. If that reads wrong (it often does next to an iframe border), force the scroller to `direction: ltr` with `direction: rtl` on its children so the bar sits on the window side **(judgement — this is the most common RTL sidebar bug)**.
- **Text alignment:** right-aligned (`text-align: start`) for labels and group headings; numbers, file names, dates, and code stay LTR-isolated with `dir="ltr"` + `unicode-bidi: isolate` so a trailing digit doesn't reorder. Hebrew labels containing a trailing latin token or a number need `bdi`/`isolate` to avoid the classic reorder glitch **(judgement)**.
- **Keyboard:** arrow-key navigation is direction-agnostic; but any "next/previous" affordance in the shell must be mirrored, and `Home`/`End` semantics stay the same **(judgement)**.
- **Tooltips/overlays** must open toward the content (inline-end), not off-screen.
- **Mixed content:** the console embeds third-party iframes that may be LTR-only; set `dir` on the shell and pass a `dir` hint into the iframe, and don't rely on `direction` inheritance across the iframe boundary **(judgement)**.
- **Numbers:** the report itself uses Latin digits; keep Latin digits in the product UI unless the owner wants Arabic-Indic ones, and be consistent **(judgement)**.

---

## 8. Motion and polish

Sourced:
- M3 expressive rail **crossfades between the rail and expanded layers in 200ms** ([rail skill doc](https://cdn.jsdelivr.net/china/npm/@universal-material/web@3.9.4/skills/navigation-rail/SKILL.md)).
- M3 state-layer opacities: hover 8%, focus 10%, pressed 10% ([same](https://cdn.jsdelivr.net/china/npm/@universal-material/web@3.9.4/skills/navigation-rail/SKILL.md)).
- GitLab's hidden sidebar reveals as an overlay "without disrupting the page content" ([Pajamas](https://design-gitlab-com-gitlab-org-gitlab-services-f6beaf2fb7fd4cad76.gitlab.io/patterns/navigation-sidebar/)) — i.e. hover-expand must not reflow the app.
- Multi-tooling references for `prefers-reduced-motion` handling in automated UI testing ([example](https://github.com/feder-cr/invisible_playwright/blob/main/docs/prefers-reduced-motion-os-setting-tells.md)) and CSS transition tuning for sidebar expand/collapse ([example](https://www.php.cn/faq/1548749.html)) — both are secondary/no-authority; treated as corroboration only.

**Prescription (judgement unless cited):**
- **Duration/easing:** expand/collapse **180–220ms**, `cubic-bezier(0.2, 0, 0, 1)` (M3 standard emphasized-decelerate family) for both directions; content fade **120–150ms**; hover/active tint **80–120ms linear**; tooltip delay-in **300–500ms**, delay-out **0ms**. Never animate the rail and the iframe content with different durations **(judgement; 200ms crossfade anchor is M3's)**.
- **What to animate:** animate the sidebar's **width** only if the layout is a flex row where the content genuinely resizes — but the *expensive* option is animating the content, not the sidebar. Prefer: sidebar `width` (transform+clip if perf-critical), labels **fade/translate** rather than reflow. In a flex container, animating `width` forces relayout of the iframe every frame → on a 1440px Mac with an embedded app this is the #1 jank source. **Rule: animate the sidebar's `width`, but freeze the content column with `flex: 1 1 auto; min-width: 0` and mark the sidebar `contain: layout paint` so the relayout stays inside it.** If profiling shows jank, fall back to an **overlay** rail (sidebar slides over content via `transform: translateX()`, zero content relayout) — GitLab already uses the overlay model at narrow widths ([Pajamas](https://design-gitlab-com-gitlab-org-gitlab-services-f6beaf2fb7fd4cad76.gitlab.io/patterns/navigation-sidebar/)) **(judgement)**.
- **Prevent text reflow jank:** give labels `white-space: nowrap; overflow: hidden; text-overflow: ellipsis` and a fixed-width label box; during collapse, do **not** let a label wrap to two lines and back — fade it out over the first 60% of the animation, then set `visibility: hidden`/`display: none` at the end; reverse on expand (show at 40%). Wrap the whole thing in a single `transition` with `@starting-style`-free, class-driven state to avoid first-paint flicker **(judgement)**.
- **No layout shift:** reserve the rail width with `width` transitions only on the sidebar, never on a parent grid track without `grid-template-columns` transition support; avoid `margin-left` animation on the content; set a fixed height on the brand block so collapsing doesn't shift the icon stack; add `scrollbar-gutter: stable` on the nav scroller so a scrollbar appearing/disappearing doesn't shift labels 8px **(judgement)**.
- **`prefers-reduced-motion: reduce` → duration 0ms**, state still changes, no crossfade, no slide **(judgement, standard practice)**.
- **Premium details that actually read as premium (judgement):** 4/8px spacing rhythm everywhere (no 5px, no 13px); 1px hairline borders at ~8% opacity rather than a full-strength gray; active pill radius 8px consistently applied to hover too; icons optically aligned to a single 20px box (never mix 16/18/20/24); a subtle 1px inner top highlight or none at all; **state persistence on reload with zero flash** (read the cookie in a blocking inline script in `<head>`); collapsing never moves the mouse-target under the cursor unless the user clicked it; tooltips that appear exactly at the icon's vertical center; and the nav never animating on first paint.

---

## 9. Failure modes to design against

| Failure | Required behaviour (judgement unless cited) |
|---|---|
| **Long labels** (Hebrew app names are long; Hebrew has no short-form convention) | Single line, `ellipsis`, full text in tooltip on hover **and** focus; never shrink font below 13px; never wrap to 2 lines in the rail (it breaks the 36px rhythm). Keep the label box ≥110px at 264px sidebar. |
| **1-item group** | Suppress the group header when a group has exactly 1 item and there is only 1 group; otherwise render the header anyway (consistency beats cleverness) — Pajamas requires top-level naming/positioning consistency even with a single sub-level item ([Pajamas](https://design-gitlab-com-gitlab-org-gitlab-services-f6beaf2fb7fd4cad76.gitlab.io/patterns/navigation-sidebar/)). |
| **Empty group** (0 permitted apps after RBAC filtering) | Never render an empty header or a "0 items" state. Hide the group entirely; if *all* groups are empty, show the empty-state block (see 0 modules). |
| **Very long business name in the brand block** | Logo mark always visible; name ellipsized with `title`+tooltip; in the 72px rail show the mark only; never allow the name to push the collapse button off-row. |
| **0 modules** | A designed empty state inside the nav area: short Hebrew line ("אין אפליקציות מורשות לחשבון זה") + a secondary action (contact admin / refresh). Never an empty white column, never a bare scrollbar track. |
| **40 modules** | Group + default-open only the active group + filter field (see §3). Cap rendered group height, scroll inside the group. |
| **Narrow / zoomed viewport (1024px, or a 1440px Mac at 150% zoom ≈ 960 CSS px)** | The breakpoint must be evaluated on **CSS px after zoom**, which `matchMedia` does automatically. At 1024 CSS px → rail; at <768 CSS px → drawer + tab bar (§4). |
| **200% zoom (720 CSS px on a 1440px screen)** | 1.4.10 Reflow expects content at 320 CSS px without two-dimensional scrolling; a fixed sidebar is the classic violator. The sidebar **must** be allowed to leave the layout (drawer/overlay) below the tablet breakpoint. Target size is zoom-independent — do not shrink targets to make it fit ([2.5.8](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html)). |
| **High-contrast / `forced-colors`** | Use `border`+`background` from system colors (`CanvasText`, `Canvas`, `Highlight`, `HighlightText`); never rely on a 4% tint to mark the active item (forced-colors will flatten it to nothing) — pair it with weight and `aria-current`. Set an explicit `outline` for `:focus-visible`. |
| **`prefers-reduced-motion`** | 0ms transitions; no crossfade; state still changes and is still announced via `aria-expanded`. |
| **No-JS / first paint** | The sidebar must render server-side in its correct width with the correct active item; the persisted collapse state is applied by a **blocking inline `<head>` script** (or a class on `<html>` from the server) — never by a post-hydration effect, or the user sees the sidebar jump on every navigation. Without JS at all, default to **expanded** (visible nav is the gold standard — [NN/g](https://www.nngroup.com/articles/vertical-nav/)). |
| **Iframe content taller/wider than expected** | `min-width: 0` on the content flex child, `iframe { width: 100%; height: 100% }`, and the nav overlay **must not** be pushed by an iframe's intrinsic width. |
| **Keyboard-only + collapsed rail** | Every icon reachable and named; toggle first in tab order within the shell; Escape closes the drawer and restores focus to the toggle. |

**"Never looks bad" invariants**
1. The sidebar's occupied width is a function of viewport only — never of content (no label can widen it).
2. Total nav height never exceeds the viewport; the scroll lives in exactly one container.
3. Every item is ≥24×24 CSS px with ≥4px separation at every zoom and breakpoint ([2.5.8](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html)).
4. Every item has a name that exists in the DOM in every state (collapsed included) — M3 keeps labels in both variants ([rail doc](https://cdn.jsdelivr.net/china/npm/@universal-material/web@3.9.4/skills/navigation-rail/SKILL.md)).
5. There is always exactly one visible active destination, at every breakpoint, including the 72px rail and the bottom tab bar.
6. Collapse never changes the currently open app, never reloads the iframe, and never loses scroll position.
7. No state depends on hover alone; hover is always an enhancement of something also reachable by focus and by touch.

---

## The 12 rules I would hold a reviewer to

1. **Leading edge, logical properties only.** In Hebrew the sidebar is on the **right**, defined by `inset-inline-start`; zero physical `left`/`right` in shell CSS (Apple defines sidebars as leading-side — [HIG](https://developer.apple.com/design/human-interface-guidelines/sidebars)).
2. **Width is 240–280px expanded, 72px collapsed, and content can never change it.** M3 allows 220–360dp ([rail doc](https://cdn.jsdelivr.net/china/npm/@universal-material/web@3.9.4/skills/navigation-rail/SKILL.md)); you pick 280 and you hold it.
3. **Two levels maximum, ever.** Top-level + one sub-level; a third level is a Tree or a split view, not the sidebar ([HIG](https://github.com/Prisma-Labs-Dev/apple-skills/blob/main/skills/hig/sidebars.md), [Pajamas](https://design-gitlab-com-gitlab-org-gitlab-services-f6beaf2fb7fd4cad76.gitlab.io/patterns/navigation-sidebar/), [Fluent 2](https://fluent2.microsoft.design/components/web/react/core/nav/usage)).
4. **Every target is ≥24×24 CSS px with ≥4px separation, at 200% zoom, on every breakpoint.** Zoom is not an excuse ([W3C 2.5.8](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html)).
5. **Labels exist in the DOM in the collapsed rail too**, and every icon has an accessible name — never an icon-only button whose only name is a `title` attribute ([rail doc](https://cdn.jsdelivr.net/china/npm/@universal-material/web@3.9.4/skills/navigation-rail/SKILL.md)).
6. **Exactly one `aria-current="page"`, visible at every breakpoint** — including the rail and the bottom bar.
7. **`aria-expanded` on a real button controls the rail; focus never gets lost on collapse/expand; Escape closes the overlay drawer and restores focus to the toggle.**
8. **Expanded and collapsed are the same destination set at two detail levels** — never product nav in one state and section sub-nav in the other ([rail doc](https://cdn.jsdelivr.net/china/npm/@universal-material/web@3.9.4/skills/navigation-rail/SKILL.md)).
9. **≥1200px: visible by default. ≤1199px: overlay + scrim, closed by default, with the user's stored preference not overriding the breakpoint's fit rule** (GitLab's exact model — [Pajamas](https://design-gitlab-com-gitlab-org-gitlab-services-f6beaf2fb7fd4cad76.gitlab.io/patterns/navigation-sidebar/)).
10. **Never auto-collapse on scroll or a timer.** Collapse on user action, on a breakpoint that can't fit, or on an explicit focus mode; and keep the three discoverability affordances (pin button, edge-hover overlay, keyboard shortcut) ([HIG](https://github.com/Prisma-Labs-Dev/apple-skills/blob/main/skills/hig/sidebars.md), [Pajamas](https://design-gitlab-com-gitlab-org-gitlab-services-f6beaf2fb7fd4cad76.gitlab.io/patterns/navigation-sidebar/)).
11. **Expansion/collapse is 180–220ms with a decelerate curve, labels fade rather than reflow, `scrollbar-gutter: stable`, and `prefers-reduced-motion` sets it to 0ms** (200ms crossfade is M3's own number — [rail doc](https://cdn.jsdelivr.net/china/npm/@universal-material/web@3.9.4/skills/navigation-rail/SKILL.md)).
12. **Below 768px, primary nav is a bottom bar of at most 5 destinations, and the rest live behind an explicit "עוד" affordance** ([NN/g: 4–5 max](https://www.nngroup.com/articles/mobile-navigation-patterns/), [reachability](https://github.com/pproenca/dot-skills/blob/master/skills/.experimental/tailwind-responsive-ui/references/nav-tab-bar-mobile.md)).
