#!/usr/bin/env python3
"""ui-map.py — generate a full UI map FROM the simulation (platform-sim.html), fully offline.

Walks every console nav destination (and key sub-views), screenshots each at a given VIEW PROFILE,
labels it, and composes a montage. No running services, no network — the whole platform's surface
captured from the single self-contained file.

View profiles (mobile / tablet / desktop) are NOT defined here: they live in
scripts/ui-coverage/view-profiles.yaml, shared with the docker-stack CI capture, so a viewport is
declared once and the two maps can never disagree.

Usage:
    python3 digital-office/sim/ui-map.py                 # the default profile (desktop)
    python3 digital-office/sim/ui-map.py --profile mobile
    python3 digital-office/sim/ui-map.py --all           # every profile in the file

Out: digital-office/sim/ui-map/<profile>/ui-map.png (+ per-panel PNGs). Slice into upload-safe
     strips with scripts/ui-coverage/split-map.py --src <that path>
"""
import argparse, os, pathlib, sys, time
from playwright.sync_api import sync_playwright
from PIL import Image, ImageDraw, ImageFont

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
SIM = HERE.parent / 'platform-sim.html'
OUT = HERE / 'ui-map'
OUT.mkdir(exist_ok=True)
PROFILES_YAML = REPO / 'scripts' / 'ui-coverage' / 'view-profiles.yaml'
# The ONE rule of "this screen has said what it has to say", shared with the live map the same way
# the viewports are: a panel is photographed when it is drawn, and how long that took is printed.
sys.path.insert(0, str(REPO / 'scripts' / 'ui-coverage'))
import drawn  # noqa: E402

LATE = []      # (profile, panel number, label, what was said, drawn at all?): over the budget, or never drawn
def _chrome():
    """Resolve a Chromium, or None to let Playwright use the one it manages.

    Was a bare literal pinning a machine-specific path and a Playwright build number no
    requirements file names; a fresh clone died at launch. Same resolution order as
    data/ui-map/ui-capture.py and digital-office/sim/flow-qa.py.
    """
    import os
    return os.getenv("UI_CHROME_BIN") or next(
        (str(g) for g in sorted(pathlib.Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome"))), None)


CHROME = _chrome()


def load_profiles():
    """Read the shared profile table. Falls back to a built-in desktop profile so the generator
    still runs if it is ever invoked outside the repo layout."""
    try:
        import yaml
        doc = yaml.safe_load(PROFILES_YAML.read_text(encoding='utf-8'))
        return doc['profiles'], doc.get('default', 'desktop')
    except Exception as e:
        print(f"! could not read {PROFILES_YAML} ({e}); falling back to built-in desktop profile")
        return ({'desktop': {'label': 'Desktop · 1440×900', 'width': 1440, 'height': 900,
                             'dsf': 1, 'is_mobile': False, 'has_touch': False, 'cols': 2}},
                'desktop')

# (label, module-hash, optional action). action(page, frame_locator) runs before the shot — it takes
# the PAGE too because some surfaces (the top-bar instance switcher) live in the console shell, not
# inside the app iframe.
def open_first_row(pg, fl):
    # mailview/my-docs rows: skip date-group separator rows (no time) — click the first row that
    # actually carries a message/doc (heuristic: its text contains a HH:MM time or a currency/₪).
    import re
    for sel in ['.gm-row[data-id]', 'table tbody tr', '.msg', '.row', '.card', 'li[role=option]', '.doc', '.item']:
        try:
            rows = fl.locator(sel)
            n = min(rows.count(), 12)
            for i in range(n):
                r = rows.nth(i)
                if not r.is_visible():
                    continue
                t = (r.inner_text() or '')
                if re.search(r'\d{1,2}:\d{2}', t) or '₪' in t or len(t) > 40:
                    # the message row's own name/subject opens it; a bare row click only selects
                    tgt = r.locator('.gm-sub, .name-open')
                    (tgt.first if tgt.count() else r).click(timeout=1200)
                    return
            # fallback: first visible element for this selector
            if rows.count() and rows.first.is_visible():
                rows.first.click(timeout=1200); return
        except Exception: pass

# ── INDOX actions — the instance surfaces added in v0.23.0 ───────────────────────────────────────
def indox_tab(name):
    """Open one of INDOX's own nav tabs (מסמכים / הגדרות / סנכרון)."""
    def go(pg, fl):
        fl.locator(".tabstrip .tab", has_text=name).first.click()
        pg.wait_for_timeout(1800)
    return go


def _open_switcher(pg):
    chip = pg.locator(".dosw-top .dosw-btn")
    if not chip.count():
        return False
    chip.first.click(); pg.wait_for_timeout(700)
    return True


def indox_switcher(pg, fl):
    """The instance switcher open, listing every INDOX instance."""
    _open_switcher(pg)


def indox_details(pg, fl):
    """"פרטי המופע" — where the deleted repo-detail screen's information now lives."""
    if _open_switcher(pg):
        pg.locator(".dosw-menu .dosw-health").first.click(); pg.wait_for_timeout(1200)


def indox_sync_items(pg, fl):
    """The items drawer — where stuck items get moved between states."""
    fl.locator(".tabstrip .tab", has_text="סנכרון").first.click(); pg.wait_for_timeout(2000)
    fl.locator(".statelegend .li-btn").first.click(); pg.wait_for_timeout(1400)


def indox_sync_editor(pg, fl):
    """The pipe editor parked on step 2 — browsing the chosen connection's real labels/folders."""
    fl.locator(".tabstrip .tab", has_text="סנכרון").first.click(); pg.wait_for_timeout(2000)
    fl.locator("button", has_text="מקור סנכרון חדש").first.click(); pg.wait_for_timeout(1100)   # (its plus is an icon)
    fl.locator(".drawer-body input[type=radio]").first.check(); pg.wait_for_timeout(400)
    fl.locator(".drawer-foot button", has_text="המשך").click(); pg.wait_for_timeout(1400)


def indox_new_instance(pg, fl):
    """The new-instance flow, parked on step 3 — choosing which connection/folders to sync."""
    if not _open_switcher(pg):
        return
    pg.locator(".dosw-menu .dosw-add").first.click(); pg.wait_for_timeout(900)
    fl.locator("#ni-label").fill("חברה חדשה")
    fl.locator(".dosw-mod [data-go]").click(); pg.wait_for_timeout(700)   # → step 2
    fl.locator(".dosw-mod [data-go]").click(); pg.wait_for_timeout(900)   # → step 3


# ── Drive / Mail component surfaces ──────────────────────────────────────────────────────────────
# The drive and the mail client each carry ~20 distinct surfaces that a single "open the app" shot
# can never show (grid vs list, the details pane, a filter menu, the full-screen preview, the share
# dialog, the undo snackbar, a selection toolbar). Each helper below parks the app on exactly one
# of them so the map is a component inventory, not a screenshot of a landing page.
def open_side(pg, fl):
    """On a phone both apps put their rail behind a drawer, exactly as the real products do. A panel
    that clicks a rail entry has to open that drawer first.

    NB: `is_visible()` is NOT the test — an element inside a translated-off-screen drawer still has
    a box and still reports visible, so the click lands on whatever covers it and times out. The
    only reliable signal is the drawer's own open state."""
    # דרייב ships its own drawer: #sideToggle flips `.side.open`. מייל's menu is the office's side menu
    # (BinaNav): #navToggle, and `is-open` on the menu itself.
    for toggle, opened in (('#sideToggle', 'aside.side.open'), ('#navToggle', '#sideNav.is-open')):
        try:
            tog = fl.locator(toggle)
            if tog.count() and tog.first.is_visible():
                if fl.locator(opened).count() == 0:
                    tog.first.click(timeout=2500); pg.wait_for_timeout(450)
                return
        except Exception:
            pass


def rail_click(pg, fl, sel):
    """Click a rail entry, opening the drawer first when the viewport put the rail behind one."""
    open_side(pg, fl)
    fl.locator(sel).first.click(timeout=8000)


def _click(fl, sel, wait=500, pg=None):
    fl.locator(sel).first.click(timeout=3000)
    if pg: pg.wait_for_timeout(wait)


def drive_place(place, then=None):
    def go(pg, fl):
        rail_click(pg, fl, f'[data-place="{place}"]'); pg.wait_for_timeout(900)
        if then: then(pg, fl)
    return go


def drive_grid(pg, fl):
    rail_click(pg, fl, '[data-place="mydrive"]'); pg.wait_for_timeout(800)
    fl.locator('#btnGrid').click(); pg.wait_for_timeout(700)


def drive_details(pg, fl):
    rail_click(pg, fl, '[data-place="mydrive"]'); pg.wait_for_timeout(800)
    # Select FIRST, then open the pane. Below 1120px the pane is a fixed overlay, so opening it
    # first puts it between the pointer and the row the panel is supposed to be describing.
    # (A row is selected by its icon: a press on its name opens the file, and on a phone the name
    # is most of the row.)
    fl.locator('tr[data-id] .ficon').first.click(); pg.wait_for_timeout(400)
    if not fl.locator('#details:not(.hidden)').count():
        fl.locator('#btnInfo').click(); pg.wait_for_timeout(500)


def drive_filter(pg, fl):
    rail_click(pg, fl, '[data-place="recent"]'); pg.wait_for_timeout(800)
    fl.locator('[data-chip="type"]').click(); pg.wait_for_timeout(500)


def drive_preview(pg, fl):
    rail_click(pg, fl, '[data-place="recent"]'); pg.wait_for_timeout(900)
    fl.locator('tr[data-id] .name-open').first.click(); pg.wait_for_timeout(900)


def drive_share(pg, fl):
    rail_click(pg, fl, '[data-place="recent"]'); pg.wait_for_timeout(900)
    row = fl.locator('tr[data-id]').first
    row.hover(); pg.wait_for_timeout(200)
    b = row.locator('button[data-act="share"]')
    if b.count() and b.first.is_visible():           # a hover and room for the row's own buttons
        b.first.click()
    else:                                            # a finger, a narrow list: the row's «⋮» menu
        row.locator('[data-more]').click(timeout=6000); pg.wait_for_timeout(300)
        fl.locator('#ctx [data-c="share"]').click(timeout=6000)
    pg.wait_for_timeout(800)


def drive_context(pg, fl):
    rail_click(pg, fl, '[data-place="recent"]'); pg.wait_for_timeout(900)
    fl.locator('tr[data-id]').first.click(button='right'); pg.wait_for_timeout(600)


def drive_bulk(pg, fl):
    rail_click(pg, fl, '[data-place="recent"]'); pg.wait_for_timeout(900)
    rows = fl.locator('tr[data-id] .ficon')
    rows.nth(0).click(); pg.wait_for_timeout(200)
    rows.nth(3).click(modifiers=['Shift']); pg.wait_for_timeout(600)


def mail_view(view):
    """A view of the mail's side menu (the office's component: rows carry `data-bnv-id`). The less used
    ones are folded behind its «הצג עוד»."""
    def go(pg, fl):
        if view in ('important', 'all', 'spam', 'trash'):
            rail_click(pg, fl, '#sideNav .bnv-more'); pg.wait_for_timeout(400)
        rail_click(pg, fl, f'#sideNav [data-bnv-id="{view}"]'); pg.wait_for_timeout(1100)
    return go


def mail_selmenu(pg, fl):
    fl.locator('#gmAllCaret').click(); pg.wait_for_timeout(500)


# (the predicate is «מסומנים בכוכב»: read and unread are offered only where the mailbox can report them,
#  and this one — Gmail's — cannot)
def mail_bulk(pg, fl):
    fl.locator('#gmAllCaret').click(); pg.wait_for_timeout(300)
    fl.locator('[data-sel="starred"]').click(); pg.wait_for_timeout(700)


def mail_undo(pg, fl):
    fl.locator('#gmAllCaret').click(); pg.wait_for_timeout(300)
    fl.locator('[data-sel="starred"]').click(); pg.wait_for_timeout(400)
    fl.locator('[data-bulk="archive"]').click(); pg.wait_for_timeout(700)


def mail_compose(pg, fl):
    rail_click(pg, fl, '#sideNav .bnv-primary'); pg.wait_for_timeout(700)


def mail_gear(to, section=None):
    """A screen behind the mail's «הגדרות»: `organizer` (the tag rules) or `settings` (the mailbox's own,
    one of its three sections)."""
    def go(pg, fl):
        rail_click(pg, fl, '#sideNav [data-bnv-id="settings"]'); pg.wait_for_timeout(400)
        fl.locator(f'#gearMenu [data-go="{to}"]').click(timeout=6000); pg.wait_for_timeout(1500)
        if section:
            fl.locator(f'#setTabs [data-sec="{section}"]').click(timeout=6000); pg.wait_for_timeout(1500)
    return go


PANELS = [
    ("אפליקציות (console · apps grid)",           "#/m/apps",        None),
    ("מסמכים שלי · רשימה (my-docs)",              "#/m/my-docs",     None),
    ("מסמכים שלי · תצוגת מסמך (my-docs · doc)",   "#/m/my-docs",     open_first_row),
    # ── דרייב · every component surface ──
    ("דרייב · בית (drive · home)",                 "#/m/drive",       None),
    ("דרייב · הדרייב שלי (my drive · list)",       "#/m/drive",       drive_place("mydrive")),
    ("דרייב · תיקייה + נתיב (folder + crumbs)",    "#/m/drive",       drive_place("mydrive", lambda pg, fl: (fl.locator('[data-folder]').first.click(timeout=6000), pg.wait_for_timeout(900)))),
    ("דרייב · תצוגת רשת (grid)",                   "#/m/drive",       drive_grid),
    ("דרייב · חלונית פרטים (details pane)",         "#/m/drive",       drive_details),
    ("דרייב · מסנני צ׳יפים (filter chips)",         "#/m/drive",       drive_filter),
    ("דרייב · אחרונים (recent)",                    "#/m/drive",       drive_place("recent")),
    ("דרייב · מסומן בכוכב (starred)",               "#/m/drive",       drive_place("starred")),
    ("דרייב · משותף איתי (shared with me)",         "#/m/drive",       drive_place("shared")),
    ("דרייב · אשפה (trash)",                        "#/m/drive",       drive_place("trash")),
    ("דרייב · בחירה מרובה + סרגל (bulk bar)",       "#/m/drive",       drive_bulk),
    ("דרייב · תפריט הקשר (context menu)",           "#/m/drive",       drive_context),
    ("דרייב · דיאלוג שיתוף (share dialog)",         "#/m/drive",       drive_share),
    ("דרייב · תצוגת מסמך מלאה (full preview)",      "#/m/drive",       drive_preview),
    # ── מייל · every component surface ──
    ("מייל · דואר נכנס (mailview inbox)",          "#/m/mail",        None),
    ("מייל · הודעה (mailview · message)",         "#/m/mail",        open_first_row),
    ("מייל · תפריט בחירה (select-all menu)",       "#/m/mail",        mail_selmenu),
    ("מייל · סרגל פעולות על נבחרים (bulk)",        "#/m/mail",        mail_bulk),
    ("מייל · סרגל ביטול פעולה (undo snackbar)",     "#/m/mail",        mail_undo),
    ("מייל · מסומן בכוכב (starred)",                "#/m/mail",        mail_view("starred")),
    ("מייל · נשלח (sent)",                          "#/m/mail",        mail_view("sent")),
    ("מייל · דורש טיפול (attention)",               "#/m/mail",        mail_view("attention")),
    ("מייל · כל הדואר (all mail · more)",           "#/m/mail",        mail_view("all")),
    ("INDOX · לוח בקרה (incoming · default)",     "#/m/incoming",    None),
    ("INDOX · מסמכים · הטבלה (one click)",        "#/m/incoming",    indox_tab("מסמכים")),
    ("INDOX · מחליף מופעים (instances)",          "#/m/incoming",    indox_switcher),
    ("INDOX · פרטי המופע (instance details)",     "#/m/incoming",    indox_details),
    ("INDOX · מופע חדש · רישומי סנכרון",          "#/m/incoming",    indox_new_instance),
    ("INDOX · הגדרות המופע (per-instance)",       "#/m/incoming",    indox_tab("הגדרות")),
    ("INDOX · סנכרון · מקורות + מצב חי",           "#/m/incoming",    indox_tab("סנכרון")),
    ("INDOX · סנכרון · פריטים והעברת מצב",         "#/m/incoming",    indox_sync_items),
    ("INDOX · סנכרון · עריכת מקור (תוויות)",       "#/m/incoming",    indox_sync_editor),
    ("כל מקביל · ציר זמן (any-concurrency)",      "#/m/concurrency", None),
    ("התראות (notifications)",                    "#/m/alerts",      None),
    ("מכונה (machine)",                           "#/m/machine",     None),
    ("אימות מערכת (feature-validation)",           "#/m/validation",  None),
    ("חיבורים ומפתחות (connections)",             "#/m/connections", None),
    ("צ׳אט · שיחות (chat)",                       "#/m/chat",         None),
    # ── מייל · the screens the live app has and its fork never did. LAST in the list, so that no panel
    #    before them changes its number (the committed maps and every comparison are written to those). ──
    ("מייל · כתיבה (compose)",                      "#/m/mail",        mail_compose),
    ("מייל · חוקי תיוג (tag rules)",                "#/m/mail",        mail_gear("organizer")),
    ("מייל · הגדרות תיבה · כתובות (mailboxes)",     "#/m/mail",        mail_gear("settings", "mailboxes")),
    ("מייל · הגדרות תיבה · דואר פרטי (setup)",      "#/m/mail",        mail_gear("settings", "setup")),
    ("מייל · הגדרות תיבה · חיבור חשבון (connect)",  "#/m/mail",        mail_gear("settings", "connect")),
]

def capture(name, prof, outdir):
    """Screenshot every panel at one view profile. Each panel gets a fresh context so an action on
    one surface (an open modal, a switched instance) can never leak into the next shot."""
    url = 'file://' + str(SIM)
    shots = []
    vp = {'width': prof['width'], 'height': prof['height']}
    with sync_playwright() as p:
        # executable_path=None is not the same as omitting it, so only pass it when resolved.
        b = p.chromium.launch(**({'executable_path': CHROME} if CHROME else {}))
        for i, (label, mod, action) in enumerate(PANELS):
            ctx = b.new_context(viewport=vp,
                                device_scale_factor=prof.get('dsf', 1),
                                is_mobile=prof.get('is_mobile', False),
                                has_touch=prof.get('has_touch', False))
            pg = ctx.new_page()
            pg.goto(url, wait_until='load'); pg.wait_for_timeout(400)
            t0 = time.monotonic()
            pg.evaluate(f"location.hash='{mod}'")
            # asked from the moment the tile opens; the 2600 ms are the shell's own animation, as before
            took = drawn.wait(pg.evaluate, pg.wait_for_timeout, since=t0, at_least_ms=2600)
            if action:
                try:
                    action(pg, pg.frame_locator('#frame'))
                except Exception as e:
                    print(f"  · {name}/{label}: action skipped ({type(e).__name__})")
                pg.wait_for_timeout(1200)
                shown = drawn.wait(pg.evaluate, pg.wait_for_timeout)     # …and what the action opened is drawn too
                took = took if shown['drawn'] else shown
            fn = outdir / f"{i:02d}.png"
            pg.screenshot(path=str(fn))
            if took['slow']:
                LATE.append((name, i, label, drawn.said(took), took['drawn']))
            shots.append((label, fn)); print(f"  captured [{name}] {label} · {drawn.said(took)}")
            ctx.close()
        b.close()
    return shots

def font(sz):
    for pth in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
        if os.path.exists(pth):
            try: return ImageFont.truetype(pth, sz)
            except Exception: pass
    return ImageFont.load_default()

def compose(shots, prof, outdir):
    """Tile the shots into one montage. Cells are laid out at CSS-pixel size regardless of the
    profile's deviceScaleFactor, so a retina phone shot is downscaled rather than dwarfing the grid
    — three profiles then read at comparable scale."""
    BAR, PAD, BG = 46, 16, (233, 238, 236)
    TITLE = 64
    # Label size follows the cell: a 390px phone cell cannot carry the same 22px caption a 1440px
    # desktop cell can, and an overflowing caption reads as a broken map.
    cellw_px = int(prof['width'])
    f = font(22 if cellw_px >= 1000 else 17 if cellw_px >= 700 else 14)
    ft = font(30)
    cols = int(prof.get('cols', 2))
    cellw, cellh = prof['width'], prof['height'] + BAR
    rows = (len(shots) + cols - 1) // cols
    W = cols * cellw + (cols + 1) * PAD
    H = TITLE + rows * cellh + (rows + 1) * PAD
    canvas = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(canvas)
    d.rectangle([0, 0, W, TITLE], fill=(9, 26, 21))
    d.text((PAD + 4, 18), f"digital-office · UI map · {prof.get('label', '')}"
                          f"   —   {len(shots)} panels", font=ft, fill=(220, 239, 231))
    for idx, (label, fn) in enumerate(shots):
        r, c = divmod(idx, cols)
        x = PAD + c * (cellw + PAD)
        y = TITLE + PAD + r * (cellh + PAD)
        d.rectangle([x, y, x + cellw, y + BAR], fill=(15, 42, 34))
        cap = f"{idx+1:02d} · {label}"
        while d.textlength(cap, font=f) > cellw - 24 and len(cap) > 8:   # ellipsize, never overflow
            cap = cap[:-2] + '…'
        d.text((x + 14, y + (BAR - (f.size if hasattr(f, 'size') else 16)) // 2 - 1),
               cap, font=f, fill=(220, 239, 231))
        try:
            im = Image.open(fn).convert('RGB')
            if im.size != (cellw, prof['height']):          # retina capture → back to CSS pixels
                im = im.resize((cellw, prof['height']), Image.LANCZOS)
            canvas.paste(im, (x, y + BAR))
        except Exception as e:
            d.text((x + 14, y + BAR + 20), f"[missing: {e}]", font=f, fill=(200, 60, 60))
    out = outdir / 'ui-map.png'
    canvas.save(out)
    print(f"ui-map [{prof.get('label')}] -> {out}  ({W}x{H}, {len(shots)} panels)\n")
    return out


def run(name, prof, recompose=False):
    outdir = OUT / name
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"\n=== profile: {name} ({prof['width']}x{prof['height']} @{prof.get('dsf',1)}x) ===")
    if recompose:
        # Re-tile the panels already on disk. Lets the montage (labels, columns, scaling) be tuned
        # without paying for a full re-capture — the slow part by far.
        shots = [(lbl, outdir / f"{i:02d}.png") for i, (lbl, _, _) in enumerate(PANELS)
                 if (outdir / f"{i:02d}.png").exists()]
        if not shots:
            print(f"  ! no panels in {outdir} — capture first"); return None
        print(f"  recomposing {len(shots)} existing panels")
        return compose(shots, prof, outdir)
    return compose(capture(name, prof, outdir), prof, outdir)


if __name__ == '__main__':
    PROFILES, DEFAULT = load_profiles()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--profile', choices=sorted(PROFILES), help='one view profile')
    ap.add_argument('--all', action='store_true', help='every profile in view-profiles.yaml')
    ap.add_argument('--list', action='store_true', help='list the tracked profiles and exit')
    ap.add_argument('--recompose', action='store_true',
                    help='re-tile panels already on disk (tune the montage without re-capturing)')
    a = ap.parse_args()

    if a.list:
        for n, pr in PROFILES.items():
            print(f"{n:9s} {pr['width']:>5}x{pr['height']:<5} @{pr.get('dsf',1)}x  {pr.get('label','')}")
        sys.exit(0)

    names = sorted(PROFILES) if a.all else [a.profile or DEFAULT]
    outs = [o for o in (run(n, PROFILES[n], a.recompose) for n in names) if o]
    print("done:")
    for o in outs:
        print(" ", o)
    if LATE:
        # Named, both kinds. A panel that NEVER finished is a picture of placeholders: the run is red.
        # One that was only slow is said and is not: here the time is this machine's load as much as
        # the screen's own — on a running office (the live map) the same word is a failure.
        print(f"\n! {len(LATE)} panel(s) took longer than a screen may ({drawn.BUDGET_MS / 1000:g}s) to say what they "
              f"have to say, or never did:")
        for prof, i, label, word, _ in LATE:
            print(f"    [{prof}] {i:02d}  {label[:50]:<52} {word}")
        if not all(done for *_, done in LATE):
            sys.exit(1)
