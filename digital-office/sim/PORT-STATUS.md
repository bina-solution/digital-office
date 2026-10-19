# Port status — sim → live, app by app

`PORT-PLAN.md` says what to do and in what order. This says **where it actually is**, what was proved
and how, and every place the live platform and the simulation deliberately disagree.

Order of work (as requested): console → my-docs → drive → mail → INDOX → chat → infrastructure apps.

Panels are the `ui-map.py` indices. Regenerate the sim side with
`python3 digital-office/sim/ui-map.py --profile desktop`; capture the live side against the container
IP (no credentials needed — traefik's forward-auth is a separate concern with its own gate, G20).

---

## 1 · Console — **done**

| Entry | What | Proof |
|---|---|---|
| A1 | one palette, type stack, space/radius/elevation ramps, status roles | panels 00/02 match on colour |
| A2 | last four glyph-icons (`☰ ✕ ↗ ✓`) become stroke icons; hardcoded status hexes point at tokens | no pictographic glyph left in the console |
| C1 | brand → הלשכה הדיגיטלית, logo `ל`, build footer from `/api/version` | panel 00 |
| C16 | shell owns the viewport (`height:100dvh`) | phone profile, no scroll behind the URL bar |
| C3/C15 | one switcher, in the top bar; `#acctBar` and `.has-bar` deleted | chip present at 3 profiles × 2 services, menu opens, no `#acctBar` in the DOM |
| C4 | connection-health panel | a card per connection (mail 2, drive 1) |
| B4/B7 | chip sheds detail at 1100/760px; 44px targets on `pointer:coarse` | chip 43×44 phone, 93px desktop |
| B6 | theming as a CSS-variable cascade + switcher, propagated into the embedded app | shell and app report the SAME computed background in all four themes |
| C14.1 | layered Escape; `aria-expanded` tracks the menu | — |

**Defects found and fixed while doing it** (all silent, none reported by any existing check):

1. **mail `/readyz` never sent `ready`.** §2 says the answer carries it; mail's failure paths set it,
   but the success path forwarded the adapter's probe payload verbatim and no adapter includes it. So
   a healthy mailbox answered `200 {mode,status,user}` and the console — keying on the documented
   field — fell through to "error" and painted a working service with a red שגיאה chip. Now derived
   from the status code, which is already the contract's truth (the compose healthcheck keys on it).
2. **Two different dark palettes** for the same tokens (`#0f1613/#243b32` in bina-ui and the app
   copies, `#0d1411/#233830` in the sim), so one app in OS-dark and the same app in chosen-dark were
   two different products. Now one set, enforced by **G21**.
3. **The console had no dark palette at all** while bina-ui had carried one for a long time — on a
   dark-mode machine the apps went dark and the shell around them stayed white.
4. **Drive and mailview carried `:root[data-theme="midnight"]` component rules with no token block**
   to adjust against: they were ported expecting tokens that only ever existed in the sim's runtime
   overlay. Caught by asserting shell and app backgrounds match, before believing the feature worked.
5. **The account menu crushed three facts into one 290px row** — a Gmail account rendered as `..m`
   beside `(...)`. Stacked.
6. **The console's "service didn't answer" message fired when the service HAD answered**, just
   off-contract. It sent the reader to look at a restarting container instead of a version mismatch.

### Deliberate divergence — panel 01 (אפליקציות)

The sim shows a console-native apps grid: a hero and two rows of cards. **The live platform is ahead
of the simulation here**, not behind it. That native view (`renderApps`) was deleted; `#/m/apps` now
embeds the **app-management** app, which owns launching *and* lifecycle — enable, disable, install,
uninstall — with tabs (האפליקציות שלי / חנות האפליקציות / שירותי ליבה), per-app version, layer and
running counts.

Regressing live to match the sim would delete working functionality to satisfy a picture, so it is
**not** being done. The rule "where they disagree, the simulation is right" is about *look*, and
app-management already uses the shell's tokens, card shapes and accent. Recorded here so the panel
diff is a known answer rather than an open question.

### Registry differences (not console code)

* Sim nav shows **צ׳אט**; live shows **בוט וואצאפ**. The sim describes it as multi-provider chat
  (WhatsApp / Telegram / local) — that is entry **B3**, and it lands with the Chat item.
* Sim shows **אימות מערכת** (feature-validation); live has no such module.
* `hello-bina` appears in neither. `platform.state.yaml` has it `enabled: false` — an install must not
  start a demo nobody asked for — so live converging to that is correct.

---

## 2 · My-docs — not started

C7 (faithful document renderer), C5 (file-type icons). Panels 03–04.

## 3 · Drive — **ported; the simulation now embeds the live frontend**

`sim/apps/localdrive` was transferred wholesale; the backend has `view=recent|starred|shared`,
`POST api/star`, `GET api/storage` and the `opened` column. The live app then went past the fork (a
phone's row menu in place of hover buttons, a storage meter that reads what the service sends,
profiles), so the fork was retired (2026-10-09): `build.mjs` embeds `apps/drive/static/` itself,
behind a mock that answers the live service's shapes. The drive flows (`flow-qa.py drive`, 27 at
each size) and the layout / windows / scroll suites therefore run on the code that is served.
**Outstanding:** `flow-qa.py --url … drive` against a live office with a drive of test data (the
flows write: star, rename, trash, a new folder), and the 14 drive panels (05–18) compared at three
profiles.
Known deliberate mismatch: **"משותף איתי" is empty on a local backend** — there is no sharing model to
populate it, and inventing one would make the simulation lie about what the platform can do.

## 4 · Mail — **ported; the simulation now embeds the live frontend**

`sim/apps/mailview` was transferred; the backend has `view=`, `POST api/mark`, `GET api/thread/<id>`.
The live app then went past the fork (the tag rules editor, the mailbox's settings — addresses, the
private-mail checklist, the guided connect — and the office's shared side menu, which is a drawer
on a phone), so the fork was retired (2026-10-09): `build.mjs` embeds `apps/mail/mailview/static/`
itself, behind a mock that answers the live service's shapes and its refusals. The mail flows
(`flow-qa.py mail`, 44 at each size) and the layout / windows / scroll suites therefore run on the
code that is served — the layout suite on the mail's settings screens too (its rule 12) — and the
map gained five panels for the screens the fork never had (42–46).
**Outstanding:** `flow-qa.py --url … mail` against a live office with a mailbox of test data (the
flows write: star, archive, a label, a sent message, a rule, an address), the mail panels
(`18.png`–`26.png`, `42.png`–`46.png`) compared at three profiles, and **C13**'s windowing and
decade-aware dates on a real mailbox (the bug is invisible on small data). C13's whole-mailbox
counts were NOT ported and are not owed: the mail service reports none, so the live menu shows
none and the mock answers none. At the tablet profile (and in any frame 600–839px wide) the
office's side menu is a rail; until 2026-10-09 a rail showed neither the rows folded behind
«הצג עוד» nor the search, and no suite ran at that width. The shared component reaches everything
in a rail now, and the layout suite's rule 13 goes to 834px itself to hold it there.
Known deliberate mismatches: a page framed from a file has no address to change, so where the live
app re-reads itself from its address (after switching the active account) the simulation lands on
the inbox; and the simulation's account switcher in the console's top bar is still the sim's own
overlay (`overlay/switcher.js`), beside the mail's own «חיבור חשבון».

## 5 · INDOX — not started

C8 (instances), C9/C10 (one sync surface + operator board). 37-file React fork. Read
`INDOX-SYNC-PORT.md`, not just the changelog entry. Includes B1 (bundle RevoGrid, or the documents
panel hangs on "טוען נתונים…"). Panels 28–36.

## 6 · Chat — not started

B3 (multi-provider client), B5 (charset-first — the Hebrew mojibake fix). Panel 43. Carries the
צ׳אט / בוט וואצאפ naming question above.

## 7 · Infrastructure apps — not started

any-concurrency, notifications, machine, app-management, connections. Panels 37–42. These already use
the design system; the work is the theme-token block (G21 lists the files that must carry it — extend
it as each app adopts one), the icon pass, and the responsive rules.

---

## How each item is proved

```bash
# the two maps, panel N against panel N
python3 digital-office/sim/ui-map.py --profile desktop
./bbox ui-map --profile desktop

# every flow driven to its end, against the LIVE platform
python3 digital-office/sim/flow-qa.py --url https://your-host
python3 digital-office/sim/flow-qa.py --url https://your-host --mobile

# the theme copies have not drifted
python3 scripts/refactor/theme-token-lint.py
```

A port is done when the live panel and the sim panel are the same picture **and** the flow suite is
green against the URL — not when the code looks right.
