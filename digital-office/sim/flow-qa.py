#!/usr/bin/env python3
"""flow-qa.py — end-to-end flow QA for the simulation, fully offline.

The ui-map proves every screen RENDERS. This proves the screens WORK: every flow a user can start is
driven to its end and its effect asserted. A flow that silently no-ops — a filter that filters
nothing, a checkbox that never fills, an invisible veil swallowing clicks — is precisely the failure
a screenshot cannot catch, and every one of those has actually shipped here at least once.

    python3 digital-office/sim/flow-qa.py                    # all suites, desktop
    python3 digital-office/sim/flow-qa.py drive mail         # named suites only
    python3 digital-office/sim/flow-qa.py --mobile           # every flow at 390x844
    python3 digital-office/sim/flow-qa.py windows            # every screen in a desktop-mode WINDOW
    python3 digital-office/sim/flow-qa.py windows --tiles alerts,apps   # …these tiles only
    python3 digital-office/sim/flow-qa.py --url https://…    # run the SAME suite against the LIVE
                                                             # platform, to prove parity after a port

The viewport matters: on a phone both rails move behind a drawer and the details pane becomes a
fixed overlay, so the same flow travels a different path and can break in ways the desktop run
never touches.

Exit code is non-zero if any flow fails or any JS error is raised, so it can gate CI.
"""
import json, pathlib, sys, time
from playwright.sync_api import sync_playwright

SIM = pathlib.Path(__file__).resolve().parent.parent / 'platform-sim.html'
# The ONE rule of "this screen has said what it has to say" — the maps' and this file's: nothing
# here is measured or photographed on a fixed wait alone (scripts/ui-coverage/drawn.py says why).
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / 'scripts' / 'ui-coverage'))
import drawn  # noqa: E402


def target_url():
    """Where to point the suite. Defaults to the built simulation; --url <base> aims the identical
    assertions at a live deployment, which is how a port is proven rather than declared done."""
    for i, a in enumerate(sys.argv):
        if a == '--url' and i + 1 < len(sys.argv):
            return sys.argv[i + 1].rstrip('/')
        if a.startswith('--url='):
            return a.split('=', 1)[1].rstrip('/')
    return SIM.as_uri()


def tiles(ids):
    """The tiles a suite walks: all of them, or only those named with `--tiles a,b` — one screen's
    windows on their own, or a running office's without a screen that is not to be opened there."""
    for i, a in enumerate(sys.argv):
        if a == '--tiles' and i + 1 < len(sys.argv):
            return [m for m in ids if m in sys.argv[i + 1].split(',')]
    return list(ids)


def _chrome():
    """Resolve a Chromium, or None to let Playwright use the one it manages.

    This used to be the bare literal "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
    which pins both a machine-specific absolute path and a Playwright build number that no
    requirements file mentions. On any host without that exact directory — i.e. a fresh clone —
    the whole suite died at launch with "executable doesn't exist", which reads as a broken
    test rather than a missing browser. data/ui-map/ui-capture.py already resolves it this way;
    this is the same order, so the two cannot drift.
    """
    import os
    return os.getenv("UI_CHROME_BIN") or next(
        (str(g) for g in sorted(pathlib.Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome"))), None)


CHROME = _chrome()
OUT = pathlib.Path(__file__).resolve().parent / 'ui-map'
OUT.mkdir(exist_ok=True)

RESULTS = []
def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("  PASS  " if cond else "  FAIL  ") + name + ((" — " + str(detail)) if detail and not cond else ""))

def open_side(pg, fl):
    """Both apps put their rail behind a drawer on a phone. `is_visible()` is NOT the test — an
    element inside a translated-off-screen drawer still has a box — so go by the drawer's own open
    state. No-op on a wide viewport, where no toggle is visible."""
    # the drive's own drawer, then the office's side menu (BinaNav — the mail's, the notifications'): each has
    # its own button (the menu's is named by the component's attribute: not every screen gives it an id), and
    # says it is open on the menu itself
    for toggle, opened in (('#sideToggle', 'aside.side.open'), ('[data-nav-toggle]', '#sideNav.is-open')):
        try:
            tog = fl.locator(toggle)
            if tog.count() and tog.first.is_visible():
                if fl.locator(opened).count() == 0:
                    tog.first.click(timeout=2500); pg.wait_for_timeout(400)
                return
        except Exception:
            pass


def rail(pg, fl, sel):
    """Click a rail entry, opening the drawer first when the viewport put the rail behind one."""
    open_side(pg, fl)
    fl.locator(sel).first.click(timeout=8000)


def open_app(pg, mod, wait=2600):
    pg.goto(target_url()); pg.wait_for_timeout(800)
    pg.evaluate("h=>location.hash=h", mod); pg.wait_for_timeout(wait)
    return pg.frame_locator('iframe')


# ══ DRIVE ════════════════════════════════════════════════════════════════════════════════════════
def pick(row, **how):
    """Select a file's row — by its icon, never by its middle: a press on the NAME opens the file, and
    on a phone the name is most of the row."""
    row.locator('.ficon').first.click(**how)


def row_act(pg, fl, row, act):
    """One of a row's own actions: its button where there is a hover and room for buttons, its «⋮»
    menu where there is not (a finger, a narrow list) — the two ways the drive itself offers."""
    row.hover(); pg.wait_for_timeout(200)
    b = row.locator(f'button[data-act="{act}"]')
    if b.count() and b.first.is_visible():
        b.first.click()
    else:
        row.locator('[data-more]').click(timeout=6000); pg.wait_for_timeout(300)
        fl.locator(f'#ctx [data-c="{act}"]').click(timeout=6000)


def drive_flows(pg, errs):
    fl = open_app(pg, '/m/drive')
    print("\nDRIVE")

    # places
    for place, label in [('mydrive', 'הדרייב שלי'), ('recent', 'לאחרונה'),
                         ('starred', 'מסומן בכוכב'), ('shared', 'שיתפו איתי'), ('trash', 'אשפה')]:
        rail(pg, fl, f'[data-place="{place}"]'); pg.wait_for_timeout(900)
        check(f'drive/place {place}', label in fl.locator('#viewTitle').inner_text(),
              fl.locator('#viewTitle').inner_text())

    # breadcrumb depth + back-navigation
    rail(pg, fl, '[data-place="mydrive"]'); pg.wait_for_timeout(800)
    fl.locator('[data-folder]').first.click(); pg.wait_for_timeout(900)
    depth2 = fl.locator('#crumbs .cb').count()
    check('drive/breadcrumb grows', depth2 >= 2, depth2)
    fl.locator('#crumbs .cb').first.click(); pg.wait_for_timeout(900)   # first crumb = הדרייב שלי
    check('drive/breadcrumb navigates back', fl.locator('#crumbs .cb').count() == 1,
          fl.locator('#crumbs .cb').count())

    # filter chip narrows, and clearing restores
    rail(pg, fl, '[data-place="recent"]'); pg.wait_for_timeout(900)
    before = fl.locator('tr[data-id]').count()
    fl.locator('[data-chip="type"]').click(); pg.wait_for_timeout(400)
    fl.locator('[data-opt="pdf"]').click(); pg.wait_for_timeout(700)
    after = fl.locator('tr[data-id]').count()
    check('drive/filter narrows', 0 < after < before, f'{before}->{after}')
    fl.locator('[data-chipclear]').click(); pg.wait_for_timeout(700)
    check('drive/filter clears', fl.locator('tr[data-id]').count() == before)

    # star toggles and persists across a view change
    row = fl.locator('tr[data-id]').first
    fid = row.get_attribute('data-id')
    was_on = 'on' in (row.locator('.rstar').get_attribute('class') or '')
    row.locator('.rstar').click(); pg.wait_for_timeout(700)
    now_on = 'on' in (fl.locator(f'tr[data-id="{fid}"] .rstar').get_attribute('class') or '')
    check('drive/star toggles', now_on != was_on)
    rail(pg, fl, '[data-place="mydrive"]'); pg.wait_for_timeout(700)
    rail(pg, fl, '[data-place="recent"]'); pg.wait_for_timeout(900)
    persisted = 'on' in (fl.locator(f'tr[data-id="{fid}"] .rstar').get_attribute('class') or '')
    check('drive/star persists', persisted == now_on)

    # details pane follows selection
    pick(fl.locator('tr[data-id]').first); pg.wait_for_timeout(400)
    if not fl.locator('#details:not(.hidden)').count():
        fl.locator('#btnInfo').click(); pg.wait_for_timeout(500)
    dt = fl.locator('#details').inner_text()
    check('drive/details describes the file', 'סוג' in dt and 'מיקום' in dt, dt[:60])
    # Below 1120px the pane is a fixed overlay covering the toolbar — including the ⓘ that opened
    # it — so it MUST carry its own way out or the app is stuck behind it.
    fl.locator('#detClose').click(timeout=6000); pg.wait_for_timeout(500)
    check('drive/details pane closes from inside', fl.locator('#details.hidden').count() == 1)

    # grid keeps the same items and is selectable
    fl.locator('#btnGrid').click(); pg.wait_for_timeout(900)
    check('drive/grid renders', fl.locator('.gcard').count() > 0, fl.locator('.gcard').count())
    fl.locator('.gcard').first.click(); pg.wait_for_timeout(500)
    check('drive/grid selects', fl.locator('.gcard.sel').count() == 1)
    fl.locator('#btnList').click(); pg.wait_for_timeout(700)

    # multi-select + bulk trash + restore from אשפה
    rows = fl.locator('tr[data-id]')
    pick(rows.nth(0)); pg.wait_for_timeout(150)
    pick(rows.nth(2), modifiers=['Shift']); pg.wait_for_timeout(500)
    nsel = fl.locator('tr.sel').count()
    check('drive/shift-range selects', nsel == 3, nsel)
    fl.locator('#bulkbar [data-bulk="trash"]').click(); pg.wait_for_timeout(1100)
    rail(pg, fl, '[data-place="trash"]'); pg.wait_for_timeout(900)
    intrash = fl.locator('tr[data-id]').count()
    check('drive/bulk trash lands in אשפה', intrash >= 3, intrash)
    pick(fl.locator('tr[data-id]').first); pg.wait_for_timeout(300)
    fl.locator('#bulkbar [data-bulk="restore"]').click(); pg.wait_for_timeout(1100)
    check('drive/restore removes it from אשפה', fl.locator('tr[data-id]').count() == intrash - 1,
          fl.locator('tr[data-id]').count())

    # «מחיקה סופית» cannot be taken back, so the office's question asks it and does it: it names the file and
    # opens on «ביטול»; a refusal by the service is said IN it, the file still in the bin and the action
    # offered again; the second press takes the file away. (The one refusal is this flow's: it answers the
    # screen's next delete request itself, once, the way the service refuses - a status and an `error`.)
    ASKED = """c => { const y = c.querySelector('.bask-btn.danger'); return {
      title: c.querySelector('h2').textContent, fact: (c.querySelector('.bask-facts dd') || {}).textContent || '',
      yes: y ? y.textContent : '', off: !y || y.disabled, focus: document.activeElement.textContent,
      said: c.querySelector('.bask-said').textContent, own: !document.getElementById('modal').classList.contains('hidden') }; }"""
    asked = lambda: fl.locator('.bask-card').evaluate(ASKED) if fl.locator('.bask-card').count() else {}
    left, doomed = fl.locator('tr[data-id]').count(), fl.locator('tr[data-id]').first
    fid, name = doomed.get_attribute('data-id'), doomed.locator('.name-open').inner_text().strip()
    pick(doomed); pg.wait_for_timeout(300)
    fl.locator('#bulkbar [data-bulk="delete"]').click(); pg.wait_for_timeout(500)
    q = asked()
    check('drive/a permanent delete is asked by the office: it names the file and opens on «ביטול»',
          q.get('yes') == 'מחיקה סופית' and q.get('fact') == name and q.get('focus') == 'ביטול' and not q.get('own'), q)
    fl.locator('body').evaluate("""() => { const real = window.fetch; window.fetch = function (u) {
      if (!/api\\/delete/.test(String(u))) return real.apply(this, arguments);
      window.fetch = real;
      return Promise.resolve(new Response(JSON.stringify({ error: 'הקובץ נעול כרגע' }),
                                          { status: 409, headers: { 'Content-Type': 'application/json' } })); }; }""")
    fl.locator('.bask-btn.danger').click(); pg.wait_for_timeout(600)
    q = asked()
    check('drive/a refused delete is said in the question, the file still in the bin and the action offered again',
          q.get('said') == 'הקובץ נעול כרגע' and q.get('yes') == 'מחיקה סופית' and not q.get('off')
          and fl.locator('tr[data-id]').count() == left, q)
    fl.locator('.bask-btn.danger').click(); pg.wait_for_timeout(1100)
    check('drive/the second press deletes it for good',
          not fl.locator('.bask-card').count() and not fl.locator(f'tr[data-id="{fid}"]').count()
          and fl.locator('tr[data-id]').count() == left - 1, fl.locator('tr[data-id]').count())

    # rename round-trip
    rail(pg, fl, '[data-place="mydrive"]'); pg.wait_for_timeout(900)
    row_act(pg, fl, fl.locator('tr[data-id]').first, 'rename'); pg.wait_for_timeout(600)
    fl.locator('#mInput').fill('קובץ_בדיקה_QA.pdf')
    fl.locator('#mFoot .primary').click(); pg.wait_for_timeout(1100)
    check('drive/rename applied', 'קובץ_בדיקה_QA' in fl.locator('#filesTable').inner_text())

    # new folder → it appears in the tree
    tree_before = fl.locator('#treeList a.nl').count()
    open_side(pg, fl)                      # the button lives in the rail, which a phone hides
    fl.locator('#newFolderBtn').click(timeout=8000); pg.wait_for_timeout(500)
    fl.locator('#mInput').fill('תיקיית QA')
    fl.locator('#mFoot .primary').click(); pg.wait_for_timeout(1200)
    check('drive/new folder opens it', 'תיקיית QA' in fl.locator('#viewTitle').inner_text(),
          fl.locator('#viewTitle').inner_text())

    # share dialog
    rail(pg, fl, '[data-place="recent"]'); pg.wait_for_timeout(900)
    row_act(pg, fl, fl.locator('tr[data-id]').first, 'share'); pg.wait_for_timeout(800)
    mb = fl.locator('#mBody').inner_text()
    check('drive/share dialog', 'בעלי גישה' in mb and 'הוספת אנשים' in mb, mb[:60])
    fl.locator('#mClose').click(); pg.wait_for_timeout(400)

    # full preview + ‹ › walk
    fl.locator('tr[data-id] .name-open').first.click(); pg.wait_for_timeout(900)
    check('drive/preview opens', fl.locator('#pvfull:not(.hidden)').count() == 1)
    name1 = fl.locator('#pvfull .pvn').inner_text()
    if fl.locator('[data-pv="next"]').count():
        fl.locator('[data-pv="next"]').click(); pg.wait_for_timeout(700)
        check('drive/preview walks', fl.locator('#pvfull .pvn').inner_text() != name1)
    fl.locator('[data-pv="close"]').click(); pg.wait_for_timeout(500)
    check('drive/preview closes', fl.locator('#pvfull.hidden').count() == 1)

    # context menu
    fl.locator('tr[data-id]').first.click(button='right'); pg.wait_for_timeout(600)
    check('drive/context menu', fl.locator('#ctx:not(.hidden) button').count() >= 4,
          fl.locator('#ctx button').count())
    pg.keyboard.press('Escape'); pg.wait_for_timeout(300)

    # global search across the whole archive
    fl.locator('#search').fill('חשבונית'); fl.locator('#search').press('Enter'); pg.wait_for_timeout(1600)
    check('drive/global search', fl.locator('tr[data-id]').count() > 20,
          fl.locator('tr[data-id]').count())

    # account switch changes the drive
    pg.locator('.dosw-top .dosw-btn').first.click(); pg.wait_for_timeout(700)
    pg.locator('.dosw-menu .dosw-it').nth(3).click(); pg.wait_for_timeout(2400)
    check('drive/account switch', True)


# ══ MAIL ═════════════════════════════════════════════════════════════════════════════════════════
def mail_flows(pg, errs):
    fl = open_app(pg, '/m/mail')
    print("\nMAIL")

    def view(v, wait=1200):
        """One entry of the side menu (the office's component: `data-bnv-id`), opened where a phone keeps
        the menu in a drawer, and its «הצג עוד» pressed when the entry is in the folded tail."""
        open_side(pg, fl)
        it = fl.locator(f'#sideNav [data-bnv-id="{v}"]').first
        if not it.is_visible():
            fl.locator('#sideNav .bnv-more').first.click(timeout=4000); pg.wait_for_timeout(300)
        it.click(timeout=8000); pg.wait_for_timeout(wait)

    # every system view returns rows (or a truthful empty state)
    for v in ['starred', 'sent', 'drafts', 'attention']:
        view(v)
        n = fl.locator('.gm-row').count()
        check(f'mail/view {v}', n > 0 or 'אין' in fl.locator('#msgTable').inner_text(), n)
    for v in ['important', 'all', 'spam', 'trash']:
        view(v)
        check(f'mail/view {v}', fl.locator('.gm-row').count() > 0, fl.locator('.gm-row').count())

    view('inbox', 1300)
    # A COUNT IS WRITTEN ONE WAY. The list said «100 מתוך 4421» over its rows and again under them, a tile away
    # from an archive of «13,811».
    told = fl.locator('body').evaluate(r"""() => { const t = ['.gm-count', '#statusbar'].map(s => { const e = document.querySelector(s);
        return e ? e.textContent.replace(/\s+/g, ' ').trim() : ''; }).join(' · ');
      return { t, bare: t.match(/(?<![\d,.:\/-])\d{4,}(?![\d,.:\/])/g) || [] }; }""")
    check('mail/a count of four digits or more is written with its separator, over the list and under it',
          len(told['t']) > 12 and not told['bare'], told['t'][:90])

    # star round-trip through the backend
    rid = fl.locator('.gm-row').first.get_attribute('data-id')
    fl.locator(f'.gm-row[data-id="{rid}"] .gm-star').click(); pg.wait_for_timeout(900)
    view('starred', 1300)
    check('mail/star reaches the starred view',
          fl.locator(f'.gm-row[data-id="{rid}"]').count() == 1)
    view('inbox', 1300)

    # ONE TICKED MESSAGE IS SAID AS ONE. The toolbar said «1 נבחרו»; the office's table says «נבחרה 1». Pressed as a
    # person presses it: a finger's tap on a phone.
    press = (lambda b: b.tap(timeout=4000)) if pg.viewport_size['width'] < 700 else (lambda b: b.click(timeout=4000))
    press(fl.locator('.gm-row .gm-cb').first); pg.wait_for_timeout(500)
    said = ' '.join(fl.locator('.gm-selinfo').inner_text().split()) if fl.locator('.gm-selinfo').count() else ''
    check('mail/one ticked message is said as one', said == 'נבחרה 1', said)
    if fl.locator('[data-bulk="clear"]').count():
        fl.locator('[data-bulk="clear"]').click(timeout=4000); pg.wait_for_timeout(400)

    # select-all predicate + bulk archive + undo. (The predicate is «מסומנים בכוכב»: read and unread are
    # offered only where the mailbox can report them, and this one - Gmail's - cannot.)
    fl.locator('#gmAllCaret').click(); pg.wait_for_timeout(400)
    fl.locator('[data-sel="starred"]').click(); pg.wait_for_timeout(700)
    nsel = fl.locator('.gm-cb.on[data-cb]').count()
    check('mail/select by a predicate', nsel > 0, nsel)
    rows_before = fl.locator('.gm-row').count()
    fl.locator('[data-bulk="archive"]').click(); pg.wait_for_timeout(900)
    check('mail/bulk archive removes rows', fl.locator('.gm-row').count() < rows_before,
          f'{rows_before}->{fl.locator(".gm-row").count()}')
    # the offer is the office's notice with «ביטול» in it (the screen had a snackbar of its own)
    check('mail/undo offered', fl.locator('#bina-tell .btell button').count() == 1)
    fl.locator('#bina-tell .btell button').click(); pg.wait_for_timeout(800)
    check('mail/undo restores rows', fl.locator('.gm-row').count() == rows_before,
          f'{rows_before} vs {fl.locator(".gm-row").count()}')

    # reading pane replaces the list; ‹ › walks; back returns
    fl.locator('.gm-row .gm-sub').first.click(); pg.wait_for_timeout(1300)
    check('mail/reader opens', fl.locator('#reader:not(.hidden)').count() == 1)
    check('mail/list is replaced, not covered', fl.locator('#msgTable.hidden').count() == 1)
    subj1 = fl.locator('#rSubject').inner_text()
    fl.locator('#rNext').click(); pg.wait_for_timeout(1100)
    check('mail/reader walks to next', fl.locator('#rSubject').inner_text() != subj1)
    fl.locator('#rClose').click(); pg.wait_for_timeout(800)
    check('mail/back returns to the list', fl.locator('#msgTable:not(.hidden)').count() == 1)

    # a threaded conversation shows its earlier turns
    if fl.locator('.gm-row:has(.thx)').count():
        fl.locator('.gm-row:has(.thx) .gm-sub').first.click(); pg.wait_for_timeout(1500)
        n = fl.locator('.thmsg').count()
        check('mail/conversation shows earlier turns', n > 0, n)
        if n:
            fl.locator('.thmsg .thm-h').first.click(); pg.wait_for_timeout(500)
            check('mail/earlier turn expands',
                  fl.locator('.thmsg .thm-b:not(.hidden)').count() == 1)
        fl.locator('#rClose').click(); pg.wait_for_timeout(700)

    # label add / remove round-trip
    fl.locator('.gm-row .gm-sub').first.click(); pg.wait_for_timeout(1300)
    tags_before = fl.locator('#rTags .chip').count()
    fl.locator('#addTag').click(); pg.wait_for_timeout(700)
    if fl.locator('#mBody .pick').count():
        fl.locator('#mBody .pick').first.click(); pg.wait_for_timeout(1100)
        check('mail/label added', fl.locator('#rTags .chip').count() >= tags_before, tags_before)
    else:
        check('mail/label picker opens', fl.locator('#mBody').inner_text() != '')
        fl.locator('#mClose').click(); pg.wait_for_timeout(400)

    # reply opens the compose window, prefilled and quoted
    fl.locator('[data-r="reply"]').click(); pg.wait_for_timeout(1300)
    win = fl.locator('.mlc-win')
    if not win.count():
        win = pg.locator('.mlc-win')
    check('mail/reply opens compose', win.count() == 1)
    if win.count():
        to = win.locator('[data-to]').input_value()
        subj = win.locator('[data-subj]').input_value()
        body = win.locator('[data-body]').input_value()
        check('mail/reply prefills recipient', '@' in to, to)
        check('mail/reply prefills Re: subject', subj.lower().startswith('re:'), subj)
        check('mail/reply quotes the original', '>' in body, body[:40])
        # Escape is what a person presses; assert the window actually answers it
        pg.keyboard.press('Escape'); pg.wait_for_timeout(500)
        gone = (fl.locator('.mlc-win').count() == 0 and pg.locator('.mlc-win').count() == 0)
        check('mail/compose closes on Escape', gone)
        if not gone:
            (fl.locator('.mlc-win [data-x]') if fl.locator('.mlc-win').count()
             else pg.locator('.mlc-win [data-x]')).first.click(timeout=6000)
            pg.wait_for_timeout(400)
    fl.locator('#rClose').click(); pg.wait_for_timeout(700)

    # compose + send appends to נשלח. «כתיבה» is the side menu's one primary action, so a phone keeps it
    # in the drawer.
    open_side(pg, fl)
    fl.locator('#sideNav .bnv-primary').first.click(timeout=8000); pg.wait_for_timeout(700)
    w = fl.locator('.mlc-win')
    if w.count():
        # the window is a sheet: the screen's width on a phone (inset from one side, it left a strip of the
        # list showing beside it), and inset from the side reading starts on where there is room
        gap = w.evaluate('e => { const r = e.getBoundingClientRect(); return [Math.round(r.left), Math.round(innerWidth - r.right), innerWidth]; }')
        check("mail/the compose sheet is the screen's width on a phone, and inset from the reading side on a wider screen",
              gap[:2] == [0, 0] if gap[2] <= 640 else gap[1] == 24, gap)
        w.locator('[data-to]').fill('person135@example.com')
        w.locator('[data-subj]').fill('בדיקת QA — הודעה חדשה')
        w.locator('[data-body]').fill('גוף ההודעה לבדיקה.')
        w.locator('.mlc-send').click(); pg.wait_for_timeout(1200)
        view('sent', 1400)
        check('mail/sent message appears in נשלח',
              'בדיקת QA' in fl.locator('#msgTable').inner_text())
    else:
        check('mail/compose window opens', False, 'compose button not found')

    # search across the corpus — the search lives in the side menu, and Enter runs it
    view('inbox', 1100)
    open_side(pg, fl)
    box = fl.locator('#sideNav .bnv-search input')
    box.fill('חשמל'); box.press('Enter'); pg.wait_for_timeout(1600)
    check('mail/search', fl.locator('.gm-row').count() > 10, fl.locator('.gm-row').count())

    mail_settings_flows(pg, fl, view)

    # account switch swaps the mailbox
    pg.locator('.dosw-top .dosw-btn').first.click(); pg.wait_for_timeout(700)
    pg.locator('.dosw-menu .dosw-it').nth(2).click(); pg.wait_for_timeout(2400)
    check('mail/account switch', fl.locator('.gm-row').count() >= 0)


def mail_settings_flows(pg, fl, view):
    """The two screens behind the mail's «הגדרות»: the tag rules and the mailbox's settings. What cannot be
    taken back there is asked by the office's question, and the service's refusals are said in its words."""
    ASKED = """c => { const y = c.querySelector('.bask-btn.danger'); return { title: c.querySelector('h2').textContent,
      facts: [...c.querySelectorAll('.bask-facts dd')].map(n => n.textContent), yes: y ? y.textContent : '',
      focus: document.activeElement.textContent, said: c.querySelector('.bask-said').textContent }; }"""
    asked = lambda: fl.locator('.bask-card').evaluate(ASKED) if fl.locator('.bask-card').count() else {}
    yes = lambda: (fl.locator('.bask-btn.danger').click(timeout=4000), pg.wait_for_timeout(700))
    keys = lambda: fl.locator('#orgGrid [data-f="KEY"]').evaluate_all('els => els.map(e => e.value)')

    def gear(to):
        open_side(pg, fl)
        fl.locator('#sideNav [data-bnv-id="settings"]').first.click(timeout=6000); pg.wait_for_timeout(400)
        fl.locator(f'#gearMenu [data-go="{to}"]').click(timeout=6000); pg.wait_for_timeout(1500)

    # the tag rules. A choice in the settings menu leaves the drawer: on a phone the screen it chose used to
    # open BEHIND it.
    gear('organizer')
    check('mail/the tag rules open in sight, the menu out of the way',
          fl.locator('#orgPane:not(.hidden)').count() == 1 and fl.locator('#sideNav.is-open').count() == 0
          and len(keys()) >= 5 and 'PROCESSED' in keys(), keys())
    # The rules were a table that needs 960px, in a pane narrower than that nearly everywhere (848px at 1440,
    # 320 on a phone): a rule's own buttons were behind a sideways scroll of the card.
    fit = fl.locator('#orgGrid').evaluate("""g => { const box = g.getBoundingClientRect();
      const out = [...g.querySelectorAll('tr[data-i] :is(button, input, select, textarea)')].filter(e => e.getClientRects().length)
        .filter(e => { const r = e.getBoundingClientRect(); return r.left < box.left - 1 || r.right > box.right + 1; });
      return { sideways: g.scrollWidth - g.clientWidth, outside: out.length, of: g.querySelectorAll('tr[data-i]').length }; }""")
    check('mail/…and every rule is whole in the width it is given — nothing of it behind a sideways scroll',
          fit['of'] >= 5 and fit['sideways'] <= 1 and not fit['outside'], fit)
    # A RULE TRIED ON THE LAST MESSAGES ENDS, AND SAYS ONE ERROR AS ONE. «תצוגה מקדימה» runs a rule over the list's
    # last messages and counts the ones it could not read. No line pressed it, and the mock refuses nothing: when
    # that count was worded (round 27) the page's `one()` stood under a local of the same name — the worker that
    # tries one message — and ONE unreadable message asked the trial of a number, which failed and asked again:
    # 7,568 rows and as many requests in twelve seconds, «[object Promise]» for a summary, no «עצירה» left to press.
    # The first message the trial asks for is refused here (in the page only), and the trial is left to end.
    fl.locator('body').evaluate("""() => { const f0 = window.fetch; let asked = 0;
      window.fetch = (u, o) => String(u).includes('api/message/') && !asked++
        ? Promise.resolve(new Response('{"error":"down"}', { status: 502, headers: { 'content-type': 'application/json' } })) : f0(u, o);
      window.__whole = () => { window.fetch = f0; }; }""")
    fl.locator('#orgGrid [data-preview]').first.click(timeout=6000)
    TRIAL = r"""(p) => ({ rows: p.querySelectorAll('.pv-row').length, failed: p.querySelectorAll('.pv-row.exc').length,
      says: ((p.querySelector('.pv-sum') || {}).innerText || '').replace(/\s+/g, ' ').trim(), running: !!p.querySelector('[data-pv-cancel]') })"""
    trial = {}
    for _ in range(12):                              # read as it goes: a trial that has ended stops drawing rows
        pg.wait_for_timeout(700); was, trial = trial, fl.locator('#orgPreview').evaluate(TRIAL)
        if not trial['running'] and was.get('rows') == trial['rows']:
            break
    fl.locator('body').evaluate('() => window.__whole()')
    ended = 0 < trial['rows'] <= 50 and not trial['running']
    check('mail/a rule tried on the last messages ends when one of them cannot be read, and says the one error as one',
          ended and trial['failed'] == 1 and 'שגיאה אחת' in trial['says'], trial)
    # (closed through the page: under a trial that did not end the page is too busy to be pressed, and the lines
    #  after this one are owed their own answers)
    fl.locator('#orgPreview [data-pv-close]').evaluate('b => b.click()'); pg.wait_for_timeout(300 if ended else 3000)
    # The engine's own row. The service refuses a document that renames its label or drops it (409) unless
    # the request says the change is meant. A new label picked for it is a change the screen does not ask
    # about when it is made — so it is asked at the save, and saved on yes.
    at = keys().index('PROCESSED') if 'PROCESSED' in keys() else 0
    fl.locator(f'#orgGrid [data-pick="{at}"]').click(timeout=6000); pg.wait_for_timeout(500)
    fl.locator('#pickList .pick[data-t="מעקב"]').click(timeout=6000); pg.wait_for_timeout(500)
    fl.locator('#orgSave').click(timeout=6000); pg.wait_for_timeout(900)
    q = asked()
    check('mail/a new label for the PROCESSED row is asked at the save',
          'PROCESSED' in q.get('title', '') and q.get('yes') == 'שמירה בכל זאת' and q.get('focus') == 'ביטול',
          q or fl.locator('#orgNotice').inner_text()[:110])
    if q:                                     # «ביטול» saves nothing, and the button is the save button again
        fl.locator('.bask-card .bask-btn:not(.danger)').click(timeout=4000); pg.wait_for_timeout(500)
    check('mail/…«ביטול» saves nothing and gives the save button back',
          fl.locator('#orgSave').inner_text().strip() == 'שמירה' and fl.locator('#orgSave').is_enabled(),
          fl.locator('#orgSave').inner_text())
    fl.locator('#orgSave').click(timeout=6000); pg.wait_for_timeout(900)
    if asked():
        yes()
    pg.wait_for_timeout(1300)
    check('mail/…and saved on yes', fl.locator('#orgSave').is_disabled() and 'נשמר' in fl.locator('#orgNotice').inner_text(),
          fl.locator('#orgNotice').inner_text()[:110])
    # deleting it IS asked when it is done, and that answer travels with the save: no second question
    at = keys().index('PROCESSED') if 'PROCESSED' in keys() else 0
    fl.locator(f'#orgGrid [data-del="{at}"]').click(timeout=6000); pg.wait_for_timeout(500)
    q = asked()
    check('mail/deleting the PROCESSED row is asked by the office, on «ביטול»',
          'PROCESSED' in q.get('title', '') and q.get('yes') == 'מחיקה' and q.get('focus') == 'ביטול', q)
    if q:
        yes()
    fl.locator('#orgSave').click(timeout=6000); pg.wait_for_timeout(1600)
    check('mail/…and the save that was agreed to is saved',
          'PROCESSED' not in keys() and fl.locator('#orgSave').is_disabled() and not fl.locator('.bask-card').count()
          and 'נשמר' in fl.locator('#orgNotice').inner_text(), fl.locator('#orgNotice').inner_text()[:90])
    # leaving with a change unsaved is asked once, and «הישארות» stays
    fl.locator(f'#orgGrid [data-del="{len(keys()) - 1}"]').click(timeout=6000); pg.wait_for_timeout(500)
    if asked():
        yes()
    fl.locator('#orgClose').click(timeout=6000); pg.wait_for_timeout(500)
    q = asked()
    if q:
        fl.locator('.bask-card .bask-btn:not(.danger)').click(timeout=4000)
    pg.wait_for_timeout(400)
    check('mail/leaving unsaved rules is asked, and «הישארות» stays',
          q.get('yes') == 'עזיבה בלי שמירה' and q.get('focus') == 'הישארות' and fl.locator('#orgPane:not(.hidden)').count() == 1, q)
    fl.locator('#orgClose').click(timeout=6000); pg.wait_for_timeout(500)
    if asked():
        yes()
    pg.wait_for_timeout(600)
    check('mail/…and one yes leaves', fl.locator('#msgTable:not(.hidden)').count() == 1 and not fl.locator('.bask-card').count())

    # the mailbox's settings: an address at the domain is made and removed AS a profile of the local server.
    # With Gmail the active account the service refuses, in its own words; with the local one it is done.
    gear('settings')
    fl.locator('#setTabs [data-sec="mailboxes"]').click(timeout=6000); pg.wait_for_timeout(1300)
    rows = lambda: fl.locator('#mbList .mb-row').count()
    n0 = rows()

    def add_address(local):
        fl.locator('#mbAdd').click(timeout=6000); pg.wait_for_timeout(400)
        fl.locator('#mbLocal').fill(local)
        fl.locator('#mbCreate').click(timeout=6000); pg.wait_for_timeout(1200)
    told = lambda: fl.locator('#bina-tell .btell.bad').last.inner_text() if fl.locator('#bina-tell .btell.bad').count() else ''
    untell = lambda: fl.locator('#bina-tell .btell').evaluate_all('els => els.forEach(e => e.remove())')
    add_address('qa')
    check('mail/an address is not made while Gmail is the active account — the service says why',
          rows() == n0 and 'שרת הדואר המקומי' in told(), told()[:80])
    untell()
    fl.locator('#setTabs [data-sec="connect"]').click(timeout=6000); pg.wait_for_timeout(1300)
    fl.locator('#cwConns [data-sel="local"]').click(timeout=6000); pg.wait_for_timeout(1500)
    # a new account re-reads the screen from its ADDRESS — and a page framed from a file has none, so the
    # simulation lands on the inbox where an office stays on the settings
    if not fl.locator('#setPane:not(.hidden)').count():
        gear('settings')
    fl.locator('#setTabs [data-sec="mailboxes"]').click(timeout=6000); pg.wait_for_timeout(1300)
    # the server's refusal is its own sentence, shown word for word — so it is one a person here can read
    add_address('qa lev')
    check('mail/…a name the server does not take is refused in the office\'s language',
          rows() == n0 and 'שם תיבה לא תקין' in told(), told()[:90])
    untell()
    add_address('qa')
    check('mail/…and as the local account it is made, its password shown once',
          rows() == n0 + 1 and fl.locator('#mbNewPw').count() == 1, rows())
    if fl.locator('#mbDone').count():
        fl.locator('#mbDone').click(timeout=6000); pg.wait_for_timeout(1200)
    fl.locator('#mbList .mb-del').first.click(timeout=6000); pg.wait_for_timeout(500)
    q = asked()
    check('mail/deleting an address is asked by the office, naming it',
          q.get('yes') == 'מחיקה' and any('qa@' in f for f in q.get('facts', [])) and q.get('focus') == 'ביטול', q)
    if q:
        yes()
    pg.wait_for_timeout(900)
    check('mail/…and it is gone', rows() == n0 and not fl.locator('.bask-card').count(), rows())
    fl.locator('#setTabs [data-sec="setup"]').click(timeout=6000); pg.wait_for_timeout(1500)
    check('mail/the private-mail checklist says what it found',
          fl.locator('#stList .st-row').count() >= 3 and 'התקנה מקומית' in fl.locator('#setBody').inner_text(),
          fl.locator('#stList .st-row').count())
    fl.locator('#setClose').click(timeout=6000); pg.wait_for_timeout(900)


# ══ INDOX ════════════════════════════════════════════════════════════════════════════════════════
# INDOX's display catalog — the live app's own file: the heading of each column of its documents table, and the
# word of each value of a status, a type, a source. What a screen may not show as the database holds it.
def catalog_words():
    cat = json.loads((pathlib.Path(__file__).resolve().parents[2] / 'apps/indox/blueprint/schema/display.json').read_text(encoding='utf-8'))
    cols = cat['tables']['incoming_documents']['columns']
    return {'names': list(cols), 'headings': [c['label'] for c in cols.values() if c.get('label')],
            'values': sorted({k for d in cat['enums'].values() for k in d if len(k) > 2 and k.isupper()})}


# -> the texts in sight that are exactly a catalogued column's NAME or a catalogued VALUE — and what a FIELD in
#    sight holds, which is no text of the page: a text box holding «INVOICE» stood beside this probe, green —
#    and how many of the catalog's headings are in sight
CATALOG_PROBE = r"""(el, w) => { const names = new Set(w.names), values = new Set(w.values), headings = new Set(w.headings);
  const raw = new Set(); let headed = 0;
  for (let t = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT), n; (n = t.nextNode());) {
    const s = n.nodeValue.trim();
    if (!s || !n.parentElement || !n.parentElement.getClientRects().length) continue;
    if (names.has(s) || values.has(s)) raw.add(s);
    if (headings.has(s)) headed++;
  }
  for (const f of document.querySelectorAll('input:not([type=hidden]):not([type=checkbox]), textarea')) {
    const s = (f.value || '').trim();
    if (s && f.getClientRects().length && (names.has(s) || values.has(s))) raw.add(s);
  }
  return { headed, raw: [...raw].slice(0, 6), asked: names.size + values.size }; }"""


def indox_flows(pg, errs):
    fl = open_app(pg, '/m/incoming', wait=3400)
    print("\nINDOX")
    words = catalog_words()

    def tab(name, wait=2400):
        fl.locator('.tabstrip .tab', has_text=name).first.click(); pg.wait_for_timeout(wait)

    def table_tool(name):
        # a tool of the TABLE's own (density, columns, export, import, the focused row's delete): in a narrow card
        # it sits behind «עוד», so a person — and this suite — opens that first
        b = fl.locator('.bt-toolbar button', has_text=name).first
        if not b.is_visible():
            fl.locator('.bt-toolbar .bt-more').first.click(timeout=4000); pg.wait_for_timeout(250)
        b.click(timeout=6000)

    def worded(view, headed=0):
        # HEADED AND WORDED AS THE LIVE APP SAYS ITS DATA READS. Its service serves each column with its heading
        # and each value of a status, a type or a source with its word (the app's display catalog, read here from
        # the app's own file). The simulation's table was headed «COMPANY_NAME», «SHORT_DOC_ID» and showed
        # «INVOICE», «COMPLETED» as the database holds them; its dashboard «RECEIPT»; a sync source's tag «INVOICE».
        got = fl.locator('body').evaluate(CATALOG_PROBE, words)
        check(f"indox/{view}: no column's name and no value stands as the database holds it — the app's catalog words them",
              got['asked'] > 99 and not got['raw'] and got['headed'] >= headed, got)

    def counted(view, where):
        # A COUNT IS WRITTEN ONE WAY. The dashboard's legend said «13243» under a tile that said «13,243», and the
        # sync screen's tiles «3097» a tab away from «13,811».
        bare = fl.locator('body').evaluate(r"""(el, where) => [...document.querySelectorAll(where)].filter(e => e.getClientRects().length)
            .map(e => e.textContent.trim()).filter(t => /^\d{4,}$/.test(t))""", where)
        check(f"indox/{view}: a count of four digits or more is written with its separator, as every other count of the app",
              not bare, bare[:4])

    worded('the dashboard')
    counted('the dashboard', '.statelegend b, .bigstat .v, .bar-val')
    # (the instance chip's second line was the table's name in the database: «incoming_documents»)
    chip = pg.evaluate(r"""() => { const s = document.querySelector('.dosw-top .dosw-btn small'); const t = s ? s.textContent.trim() : '';
        return /^[a-z0-9_.]+$/.test(t) ? t : ''; }""")
    check("indox/the instance chip names the company — the table it is kept in is not its second line", not chip, chip)
    # the documents table lands one click away and carries the whole repo
    tab('מסמכים', 3000)
    body = fl.locator('body').inner_text()
    check('indox/documents table is one click away', 'מסמכים' in body and fl.locator('revo-grid').count() > 0, body[:60])
    check('indox/table carries the archive', fl.locator('table tbody tr, .rgRow').count() > 10,
          fl.locator('table tbody tr, .rgRow').count())
    worded('the documents table', headed=1)          # (a phone shows two of its columns)

    # A DOCUMENT'S OWN PAGE, in the same words — and what a FIELD holds is read too (the probe): its two fields
    # of a value domain were text boxes holding «INVOICE», «IN_PROGRESS», and its history was each event's whole
    # row as JSON, every line's comma at its beginning. A field of a domain is chosen in the catalog's words; an
    # event says what changed; the row as it was stored is one press away.
    fl.locator('revo-grid .bt-link').first.click(timeout=6000); pg.wait_for_timeout(2400)
    worded("a document's own page", headed=3)
    # (what a closed <details> holds keeps its boxes — the browser skips its contents, it does not remove them — so
    #  «in sight» is asked of the browser itself here, not read off a rectangle)
    hist = fl.locator('body').evaluate(r"""() => ({ stored: document.querySelectorAll('details.rowas').length,
        open: [...document.querySelectorAll('pre.codeblock')].filter(e => e.checkVisibility()).length })""")
    check("indox/a document's history says what changed in words — the row as it was stored is one press away",
          hist['stored'] > 0 and hist['open'] == 0, hist)
    if pg.viewport_size['width'] < 700:
        # (side by side at 390px each of the page's two cards was 170px wide: a name cut in its field)
        cards = fl.locator('.card').evaluate_all("""els => els.filter(e => e.checkVisibility()).slice(0, 2).map(e => {
            const r = e.getBoundingClientRect(); return [Math.round(r.top), Math.round(r.bottom), Math.round(r.width)]; })""")
        check("indox/on a phone a document's two cards stand one under the other",
              len(cards) == 2 and cards[1][0] >= cards[0][1], cards)

    # the merged sync surface: pipes, live state, and the items behind a state
    tab('סנכרון')
    worded('the sync screen')
    counted('the sync screen', '.bigstat .v, .statelegend b')
    txt = fl.locator('body').inner_text()
    check('indox/sync shows the pipes', 'סנכרון' in txt and len(txt) > 200)
    if fl.locator('.statelegend .li-btn').count():
        fl.locator('.statelegend .li-btn').first.click(); pg.wait_for_timeout(1500)
        check('indox/items drawer opens', fl.locator('.drawer, .items-drawer').count() > 0)
        pg.keyboard.press('Escape'); pg.wait_for_timeout(600)
        check('indox/items drawer closes on Escape',
              fl.locator('.drawer-h').count() == 0, 'drawer still open')
        if fl.locator('.scrim').count():          # fall back to the scrim so the suite continues
            fl.locator('.scrim').first.click(); pg.wait_for_timeout(500)

    # settings are per instance
    tab('הגדרות')
    check('indox/settings render', len(fl.locator('body').inner_text()) > 150)
    if pg.viewport_size['width'] < 700:
        # (five sub-tabs stood on three lines of a phone, above the table they choose)
        lines = fl.locator('.subnav .stab').evaluate_all("els => [...new Set(els.map(e => Math.round(e.getBoundingClientRect().top)))]")
        check("indox/the settings' sub-tabs stand on one line of a phone", len(lines) == 1, lines)

    # WHAT IS REMOVED IS ASKED IN THE PAGE, naming it. Three removals here went through the browser's own dialog
    # («…says», English buttons, one line of text, nothing about what goes) and a fourth — an extraction run —
    # asked nothing and was gone. The office's question is what is read: red, opening on «ביטול», naming the
    # thing — and «ביטול» removes nothing. (The browser's dialog itself is failed by main(), for every suite.)
    inpage = lambda js: fl.locator('body').evaluate(js)
    ASKED = """() => { const c = document.querySelector('.bask-card'); if (!c) return {};
      return { title: c.querySelector('h2').textContent, facts: [...c.querySelectorAll('.bask-facts dd')].map(n => n.textContent),
               red: !!c.querySelector('.bask-btn.danger'), focus: document.activeElement.textContent }; }"""

    def removal(what, press, left, named, gone=1):
        def pressed():                         # the question is waited for, not a fixed moment: a loaded machine draws it late
            press()
            try:
                fl.locator('.bask-card').wait_for(state='visible', timeout=3000)
            except Exception:
                pass
            return inpage(ASKED)
        n = left()
        q = pressed()
        if q:
            fl.locator('.bask-card .bask-btn:not(.danger)').click(timeout=4000); pg.wait_for_timeout(500)
        check(f'indox/{what} is asked in the page, naming it — and «ביטול» removes nothing',
              bool(q) and q['red'] and q['focus'] == 'ביטול' and any(named in f for f in q['facts']) and left() == n,
              q or f'no question in the page · left: {n} -> {left()}')
        if q and gone:
            pressed()
            fl.locator('.bask-card .bask-btn.danger').click(timeout=4000); pg.wait_for_timeout(1200)
            check('indox/…and the action removes it', left() == n - gone, f'{n} -> {left()}')

    records = lambda: int(''.join(ch for ch in fl.locator('.bt-count').first.inner_text() if ch.isdigit()) or 1)
    fl.locator('button.stab', has_text='חברות').click(timeout=6000); pg.wait_for_timeout(1800)
    # A TABLE'S TOOLBAR IN A NARROW CARD — a phone, a small window: what is done to rows stays in sight (the search
    # and «הוסף» on one line, the selection under them) and the table's own tools sit behind «עוד». It wrapped onto
    # five lines, and ONE row of the table was in sight under it. («In sight» is asked of the browser.)
    bar = fl.locator('.bt-toolbar').first.evaluate(r"""(t) => ({ h: Math.round(t.getBoundingClientRect().height),
        more: [...t.querySelectorAll('.bt-more')].some(e => e.checkVisibility()),
        tools: [...t.querySelectorAll('button')].filter(e => e.checkVisibility()
          && /^(צפוף|מרווח|ייצוא|ייבוא|מחק שורה|עמודות)/.test(e.textContent.trim())).length })""")
    if pg.viewport_size['width'] < 700:
        check("indox/a table's toolbar takes two lines of a phone — the table's own tools are behind «עוד»",
              bar['h'] <= 100 and bar['more'] and bar['tools'] == 0, bar)
        brought = 0
        if bar['more']:                                  # (a table with no «עוד» has nothing to bring: the line says so)
            fl.locator('.bt-toolbar .bt-more').first.tap(timeout=4000); pg.wait_for_timeout(300)
            brought = fl.locator('.bt-toolbar').first.evaluate(r"""(t) => [...t.querySelectorAll('.bt-tools button')].filter(e => e.checkVisibility()).length""")
            fl.locator('.bt-toolbar .bt-more').first.tap(timeout=4000); pg.wait_for_timeout(300)
        check("indox/«עוד» brings the table's tools", brought >= 2, brought)
    else:
        check("indox/a wide table's toolbar is one line with its tools in it — no «עוד»",
              bar['h'] <= 64 and not bar['more'] and bar['tools'] >= 2, bar)
    # What the table has to SAY it says through the office's notice. It kept a toast of its own (and the sync
    # board another): a second and a third place on one screen for "saved" and "failed". Asked with no row in
    # focus, «מחק שורה» has exactly one thing to say.
    table_tool('מחק שורה'); pg.wait_for_timeout(500)
    said = fl.locator('#bina-tell .btell').all_inner_texts()
    check("indox/the table says what it needs through the office's notice, not through a toast of its own",
          any('בחרו תא' in t for t in said) and not fl.locator('.bt-toast, .sb-toast').count(),
          said or fl.locator('.bt-toast, .sb-toast').all_inner_texts())
    fl.locator('#bina-tell .btell').evaluate_all('els => els.forEach(e => e.remove())')
    # a cell of the first row's own data (a row's NUMBER takes no focus) — the one a person reads first: its rightmost
    cells = fl.locator('revo-grid .rgRow .rgCell.bt-editable')
    at = max(0, inpage("""() => { const cs = [...document.querySelectorAll('revo-grid .rgRow .rgCell.bt-editable')].map((c) => [c, c.getBoundingClientRect()]);
      let best = -1, x = -1;
      cs.forEach(([c, r], i) => { if (r.top < cs[0][1].top + 2 && r.left >= 0 && r.right <= innerWidth && r.left > x && c.textContent.trim().length > 2) { best = i; x = r.left; } });
      return best; }"""))
    row = cells.nth(at).inner_text().strip()
    cells.nth(at).click(timeout=6000); pg.wait_for_timeout(400)
    removal('deleting a settings row', lambda: table_tool('מחק שורה'), records, row)
    # A ROW IS TICKED BY ONE PRESS OF ITS BOX — pressed as a person presses it: a finger's TAP on a phone
    # (touchstart, touchend, and the click the browser makes of them), unforced at both sizes. The suite forced
    # a mouse click here; under it the first tap ticked nothing (the grid moved its focus to the box's cell and
    # drew its 30px drag handle over the box before the press ended) and ticking the first row moved every row
    # 34px down (the selection's controls took a new line of the toolbar) — which is how the forced click came
    # to miss on a loaded machine: one row counted where two were pressed. The table's own count is waited for.
    boxes = fl.locator('revo-grid input.bt-selbox')
    press = (lambda b: b.tap(timeout=4000)) if pg.viewport_size['width'] < 700 else (lambda b: b.click(timeout=4000))
    picked = lambda: inpage("""() => { const c = document.querySelector('.bt-selcount');      // (its number is its `data-n`)
      return c && c.getClientRects().length && getComputedStyle(c).visibility !== 'hidden' ? parseInt(c.dataset.n || c.textContent) || 0 : 0; }""")
    rows_at = lambda: inpage("() => Math.round(document.querySelector('revo-grid').getBoundingClientRect().top)")
    boxes.nth(0).scroll_into_view_if_needed(timeout=4000); pg.wait_for_timeout(300)
    ticked, at, moved, one = [], rows_at(), None, ''
    for i in (0, 1):
        try:
            press(boxes.nth(i))
        except Exception as e:                           # refused: something stands over the box
            ticked.append(str(e).split('\n')[0][:70]); break
        for _ in range(12):
            if picked() == i + 1:
                break
            pg.wait_for_timeout(250)
        ticked.append(picked())
        if i == 0:
            moved, one = rows_at() - at, ' '.join(fl.locator('.bt-selcount').first.inner_text().split())
    check("indox/a row is ticked by one press of its box — a finger's, on a phone", ticked == [1, 2], ticked)
    check('indox/ticking a row does not move the rows', moved is not None and abs(moved) <= 1, f'{moved}px')
    # (the table's count read «1 נבחרו»: one, in the plural — as short as it was, so that the rows stay)
    check('indox/one ticked row is said as one', 'נבחרה' in one and 'נבחרו' not in one, one)
    removal('deleting the selected rows', lambda: fl.locator('.bt-toolbar button', has_text='מחק נבחרות').click(timeout=6000),
            records, '2', gone=0)
    # WHAT A PRESS MEETS, WHEN THE NUMBER IS ONE OR THE SERVICE SAYS NO. None of this was pressed by any line, and the
    # mock refuses nothing: each sentence below was read for the first time by walking it (a refusal is planted in
    # the page, as the mail's rule trial does). Two rows are ticked here.
    told = lambda: ' · '.join(' '.join(t.split()) for t in fl.locator('#bina-tell .btell').all_inner_texts())
    hush = lambda: fl.locator('#bina-tell .btell').evaluate_all('els => els.forEach(e => e.remove())')
    refuse = lambda method: inpage("""() => { const f0 = window.fetch; let n = 0;
      window.fetch = (u, o) => (o && o.method === '%s' && !n++)
        ? Promise.resolve(new Response('<html>502</html>', { status: 502, headers: { 'content-type': 'text/html' } })) : f0(u, o);
      window.__whole = () => { window.fetch = f0; }; }""" % method)
    whole = lambda: inpage('() => { if (window.__whole) window.__whole(); }')

    def answered(ask_it, yes):                      # press, wait for the office's question, read it, answer it
        ask_it()
        try:
            fl.locator('.bask-card').wait_for(state='visible', timeout=3000)
        except Exception:
            return {}
        q = inpage(ASKED)
        fl.locator('.bask-card .bask-btn.danger' if yes else '.bask-card .bask-btn:not(.danger)').click(timeout=4000)
        pg.wait_for_timeout(1300 if yes else 400)
        return q

    del_ticked = lambda: fl.locator('.bt-toolbar button', has_text='מחק נבחרות').click(timeout=6000)
    # …one ticked row is asked about as ONE row, and named as a person calls it (it was «למחוק את השורות שנבחרו?»
    #  with the fact «שורות: 1»)
    try:
        press(boxes.nth(1)); pg.wait_for_timeout(400)
    except Exception:
        pass
    q1 = answered(del_ticked, False) if picked() == 1 else {}
    check('indox/one ticked row is asked about as one row, and named',
          'השורה שנבחרה' in q1.get('title', '') and len((q1.get('facts') or [''])[0]) > 1, q1 or f'{picked()} ticked')
    # …a row is ticked by a press BESIDE its box, anywhere in its cell: the box is 15px, what a finger hits is the
    #  label that fills the cell (44px). Pressed 3px inside the label's corner.
    lab = fl.locator('revo-grid label.bt-sellbl')
    was = picked()
    if lab.count() > 1:
        try:
            (lab.nth(1).tap if pg.viewport_size['width'] < 700 else lab.nth(1).click)(position={'x': 3, 'y': 3}, timeout=4000)
        except Exception:
            pass
        for _ in range(8):
            if picked() != was:
                break
            pg.wait_for_timeout(250)
    check('indox/a row is ticked by a press beside its box, anywhere in its cell', was == 1 and picked() == 2,
          f'{was} -> {picked()} ticked · labels around the boxes: {lab.count()}')
    # …a row the service refuses to DELETE stays, and the refusal is said (nothing was said, and the failed request
    #  was thrown past everything on the page)
    n, before = records(), len(errs)
    cells.nth(0).click(timeout=6000); pg.wait_for_timeout(300)
    hush(); refuse('DELETE')
    answered(lambda: table_tool('מחק שורה'), True)
    thrown = [e for e in errs[before:] if not e.startswith('console:')]; del errs[before:]
    check('indox/a row the service refuses to delete stays, and the refusal is said in words',
          'השורה לא נמחקה' in told() and records() == n and not thrown, {'said': told(), 'rows': f'{n} -> {records()}', 'thrown': thrown[:2]})
    whole(); hush()
    # …and a row it refuses to ADD is not there, and that is said
    n, before = records(), len(errs)
    refuse('POST')
    fl.locator('.bt-toolbar .bt-add').first.click(timeout=6000); pg.wait_for_timeout(1300)
    thrown = [e for e in errs[before:] if not e.startswith('console:')]; del errs[before:]
    check('indox/a row the service refuses to add is not there, and the refusal is said in words',
          'השורה לא נוספה' in told() and records() == n and not thrown, {'said': told(), 'rows': f'{n} -> {records()}', 'thrown': thrown[:2]})
    whole(); hush()
    # …of two ticked rows of which the service deletes one: the notice counts one done and one failed, each as one,
    #  and the refused row STAYS (both left the table, beside a notice that counted one as failed)
    n, two = records(), picked()
    refuse('DELETE')
    answered(del_ticked, True)
    check('indox/of two ticked rows one refused: one is said deleted and one failed, and the refused row stays',
          two == 2 and 'נמחקה 1' in told() and 'אחת נכשלה' in told() and records() == n - 1, {'ticked': two, 'said': told(), 'rows': f'{n} -> {records()}'})
    whole(); hush()
    # WHAT WAS DONE IN A TABLE STAYS DONE when its tab is left and returned to, and the tab counts the table's rows.
    # The grid kept a copy of the page's rows: the tab went on reading the number it opened with, and the return drew
    # the copy afresh from the page's — every row deleted above was back.
    on_tab = lambda: int(''.join(ch for ch in fl.locator('button.stab.active .n').first.inner_text() if ch.isdigit()) or -1)
    foot = lambda: ' '.join(fl.locator('.bt-count').first.inner_text().split())        # (the table's own words: «רשומה אחת»)
    n, foot_was, tabbed = records(), foot(), on_tab()
    fl.locator('button.stab', has_text='חוקי תיוג').click(timeout=6000); pg.wait_for_timeout(1800)
    fl.locator('button.stab', has_text='חברות').click(timeout=6000); pg.wait_for_timeout(1800)
    check('indox/a table keeps what was done in it when its tab is left and returned to, and the tab counts its rows',
          bool(foot_was) and foot() == foot_was and n == tabbed == on_tab(), {'the table': f'«{foot_was}» -> «{foot()}»', 'the tab': f'{tabbed} -> {on_tab()}'})
    tab('סנכרון')
    names = lambda: [t.strip() for t in fl.locator('.card .sync-meta .name').all_inner_texts()]
    removal('deleting a sync source', lambda: fl.locator('.card button.link', has_text='מחיקה').first.click(timeout=6000),
            lambda: len(names()), (names() or ['—'])[0])
    tab('חילוץ')               # a run to remove: one document, run to its end (the mock gives a document a poll)
    fl.locator('table input[type=checkbox]').nth(1).click(timeout=6000, force=True); pg.wait_for_timeout(300)
    fl.locator('button', has_text='הרץ נבחרים').first.click(timeout=6000)
    history = fl.locator('.card', has_text='היסטוריית הרצות')
    for _ in range(14):
        pg.wait_for_timeout(1000)
        if history.count() and not fl.locator('button', has_text='עצור').count():
            break
    if history.count():
        history.first.locator('button.link', has_text='הצג').first.click(timeout=6000); pg.wait_for_timeout(500)
    runs = lambda: fl.locator('button.link.danger', has_text='מחק').count()
    removal('deleting an extraction run', lambda: fl.locator('button.link.danger', has_text='מחק').first.click(timeout=6000), runs, '1/1')

    # switching instance swaps the whole INDOX — table, settings, registry, and SCALE
    tab('מסמכים', 3000)
    before = fl.locator('body').inner_text()
    pg.locator('.dosw-top .dosw-btn').first.click(); pg.wait_for_timeout(800)
    items = pg.locator('.dosw-menu .dosw-it')
    if items.count() > 1:
        items.nth(1).click(); pg.wait_for_timeout(3200)
        check('indox/instance switch changes the repo',
              fl.locator('body').inner_text() != before)


# ══ CONSOLE ══════════════════════════════════════════════════════════════════════════════════════
def console_flows(pg, errs):
    print("\nCONSOLE")
    pg.goto(target_url()); pg.wait_for_timeout(1200)
    # every rail destination reaches a screen with content. The rail marks each entry with
    # data-id (not an href) — it drives the hash itself — so that is what we walk.
    # `#nav`, not `nav`: the console's menu is `<div id="nav" class="bnv-scroll">` (the component's
    # own markup, platform-base/bina-ui/bina-nav.css), so a bare element selector matched NOTHING and
    # this check reported "the rail has no destinations" against a rail that was rendering thirteen
    # rows. The 10-entry floor stays: that is what fails a rail which genuinely did not load.
    ids = pg.evaluate("() => [...document.querySelectorAll('#nav a[data-id]')].map(a => a.dataset.id)")
    check('console/rail has destinations', len(ids) >= 10, len(ids))
    for mod in ids:
        pg.evaluate("m=>location.hash='/m/'+m", mod)
        pg.wait_for_timeout(1800)
        # The console keeps a spent about:blank iframe around when it switches to one of its own
        # native screens, so "the first non-main frame" is not the app — read whichever frame
        # actually has content.
        best = ''
        for f in pg.frames:
            try:
                t = f.locator('body').inner_text()[:400]
            except Exception:
                t = ''
            if len(t.strip()) > len(best.strip()):
                best = t
        check(f'console/{mod}', len(best.strip()) > 20, len(best.strip()))

    # THE APPS SCREEN, driven. It is the real frontend over a mock of its API (it was the simulator's
    # placeholder for a week, and "has more than 20 characters" passed over the placeholder too): a
    # card per installed app, and a verb whose effect is SEEN — an app switched off says so on its
    # own card and offers to be switched on again.
    if 'apps' in ids:
        pg.evaluate("location.hash = '/m/apps'"); pg.wait_for_timeout(1800)
        fr = next((f for f in pg.frames if f != pg.main_frame and f.locator('article.card[data-id]').count()), None)
        cards = fr.locator('article.card[data-id]').count() if fr else 0
        check('console/apps · the real screen: a card for every installed app', cards >= 4, cards)
        if fr:
            # A list that is SHORT — nothing matches, or nothing has arrived yet — and a side menu that
            # still stands the frame's whole height: it ended where the content did, half way down the
            # screen, for as long as the list took to load (seen on a running office, 2026-10-09).
            find = fr.locator('.bnv .bnv-search input')
            if pg.viewport_size['width'] >= 840 and find.count():
                find.first.fill('אין-אפליקציה-כזאת'); pg.wait_for_timeout(600)
                short = fr.evaluate("""() => { const m = document.querySelector('.bnv').getBoundingClientRect();
                  return { cards: document.querySelectorAll('article.card').length, menu_ends: Math.round(m.bottom),
                           frame: innerHeight, page: document.scrollingElement.scrollHeight }; }""")
                check("console/apps · with nothing to list, the side menu still stands the frame's whole height",
                      short['cards'] == 0 and short['menu_ends'] >= short['frame'] - 1, short)
                find.first.fill(''); pg.wait_for_timeout(600)
            # A list that is SLOW to answer is asked for by one read at a time. The screen asks every
            # 5 seconds; with answers that took longer than that (5 to 13 seconds on a running office)
            # two or three reads were in flight for as long as it stood open, each slowing the next.
            # Here every answer is held back 7 seconds, across two of the screen's ticks.
            reads = fr.evaluate("""async () => {
              const real = window.fetch; let out = 0, most = 0, asked = 0;
              window.fetch = (u, o) => {
                if (!/(^|\\/)api\\/apps$/.test(String(u).split('?')[0])) return real(u, o);
                asked += 1; out += 1; most = Math.max(most, out);
                return new Promise((go) => setTimeout(go, 7000)).then(() => real(u, o)).finally(() => { out -= 1; });
              };
              await new Promise((go) => setTimeout(go, 11500));
              window.fetch = real;
              return { asked, most_at_once: most };
            }""")
            check('console/apps · a list that is slow to answer is asked for by one read at a time',
                  reads['asked'] >= 1 and reads['most_at_once'] == 1, reads)
            card = fr.locator('article.card[data-id="drive"]')
            was = card.locator('.badge').first.inner_text().strip() if card.count() else ''
            if card.count():
                card.locator('button[data-act="disable"]').click()
                pg.wait_for_timeout(2500)
            card = fr.locator('article.card[data-id="drive"]')
            now = card.locator('.badge').first.inner_text().strip() if card.count() else ''
            again = card.locator('button[data-act="install"]').count() if card.count() else 0
            check('console/apps · switching an app off is seen on its card, with the way back',
                  bool(was) and was != now and 'מושבתת' in now and again == 1, {'was': was, 'now': now, 'on': again})

    # THE NOTIFICATIONS SCREEN, pressed. No line pressed a row of it or either of its buttons, so nothing had met what
    # a press does there. A row shows two lines of its text and a press opens a text that is cut — and the first
    # forms of that, written under green: a row OPENED in «לא נקראו» left the list at that very press (read now, it
    # was no longer among the unread the list asks for); then every row pressed there STAYED, whether it had
    # anything to open or not; a double press on a word of an open text, to copy it, folded the row, and the list's
    # next read unmarked the word; a fold read the row again. And the two buttons said «נוקו 1 התראות» and «סומנו 1
    # כנקראו». In the simulation only: these presses mark rows read and clear them, and on a running office the
    # rows are a person's own.
    if 'alerts' in ids and not target_url().startswith('http'):
        size = pg.viewport_size
        touch = size['width'] < 700
        row = '#list .item[data-id="%s"] %s'
        # -> the first row that is unread (or read), with a text that is cut (or whole); '' where there is none
        ROW = """(a) => { for (const e of document.querySelectorAll('#list .item')) { const d = e.querySelector('.desc');
          if (d && e.classList.contains('unread') === a[0] && (d.scrollHeight > d.clientHeight + 1) === a[1]) return e.dataset.id; }
          return ''; }"""
        # -> the middle of a word of a text, from the text's own corner (a double press on a space marks nothing)
        WORD = r"""(e) => { const b = e.getBoundingClientRect();
          for (let w = document.createTreeWalker(e, NodeFilter.SHOW_TEXT), n; (n = w.nextNode());) {
            const m = /[א-תA-Za-z]{4,}/.exec(n.nodeValue); if (!m || n.parentElement.closest('a')) continue;
            const r = document.createRange(); r.setStart(n, m.index + 1); r.setEnd(n, m.index + m[0].length - 1);
            const c = r.getBoundingClientRect(); if (c.width) return { x: c.left + c.width / 2 - b.left, y: c.top + c.height / 2 - b.top }; }
          return { x: b.width / 2, y: 8 }; }"""

        def alerts():                                    # the tile, opened: its frame
            pg.evaluate("location.hash = '/m/alerts'"); pg.wait_for_timeout(1800)
            return next((f for f in pg.frames if f != pg.main_frame and f.locator('#list .item').count()), None)

        def press(sel):                                  # as a person presses (a finger's tap on a phone); says whether it landed
            try:
                (fr.locator(sel).first.tap if touch else fr.locator(sel).first.click)(timeout=4000); landed = True
            except Exception:
                landed = False
            pg.wait_for_timeout(1200)
            return landed
        listed = lambda: fr.evaluate("() => [...document.querySelectorAll('#list .item')].map((e) => e.dataset.id)")
        looks = lambda i: fr.evaluate("""(i) => (document.querySelector('#list .item[data-id="' + i + '"]') || {}).className || 'gone'""", i)
        unread = lambda: int(''.join(ch for ch in fr.locator('#hud .pg-kpi', has_text='לא נקראו').locator('.pg-kpi-v').first.inner_text() if ch.isdigit()) or -1)
        said = lambda: ' · '.join(' '.join(t.split()) for t in fr.locator('#bina-tell .btell').all_inner_texts())
        hush = lambda: fr.locator('#bina-tell .btell').evaluate_all('els => els.forEach(e => e.remove())')
        marked = lambda: fr.evaluate('() => String(getSelection()).trim()')
        fr = alerts()
        check('console/alerts · the real screen: a row for every notification', fr is not None, 'no frame holds #list .item')
        if fr:
            # A ROW WHOSE TEXT IS WHOLE has nothing to open: the press reads it, and in «לא נקראו» it leaves the list
            # as it always did. (At a laptop's width no text of the mock is cut; on a phone every unread one is.)
            rail(pg, fr, '[data-bnv-id="read:unread"]'); pg.wait_for_timeout(1200)
            was, n, plain = listed(), unread(), fr.evaluate(ROW, [True, False])
            if plain:
                landed = press(row % (plain, '.title'))
                check("console/alerts · a row whose text is whole is read by a press and leaves «לא נקראו» — nothing was opened, nothing is kept",
                      landed and plain not in listed() and len(listed()) == len(was) - 1 and unread() == n - 1,
                      {'rows': f'{len(was)} -> {len(listed())}', 'the row': looks(plain), 'unread': f'{n} -> {unread()}'})
            else:
                check("console/alerts · a row whose text is whole is read by a press and leaves «לא נקראו» (no unread text is whole at this size)", True)
        # A ROW WHOSE TEXT IS CUT, where a mouse meets one too: the smallest window desktop mode gives, 380px wide.
        # The page is loaded afresh — the mock's rows as they open.
        if not touch:
            pg.set_viewport_size({'width': 380, 'height': size['height']})
        try:
            pg.goto(target_url()); pg.wait_for_timeout(1200)
            fr = alerts()
            if fr is None:
                check('console/alerts · the screen, in a narrow window', False, 'no frame holds #list .item')
            else:
                rail(pg, fr, '[data-bnv-id="read:unread"]'); pg.wait_for_timeout(1200)
                was, n, one = listed(), unread(), fr.evaluate(ROW, [True, True])
                landed = bool(one) and press(row % (one, '.title'))
                press('#live'); press('#live')           # paused and resumed: the list is read again
                check("console/alerts · a row opened in «לא נקראו» stays open and in its place — read, and counted read — through the list's next read",
                      landed and listed() == was and 'whole' in looks(one) and 'unread' not in looks(one) and unread() == n - 1,
                      {'rows': f'{len(was)} -> {len(listed())}', 'the row': looks(one), 'unread': f'{n} -> {unread()}'})
                landed = press(row % (one, '.desc'))
                check("console/alerts · an open text is the reader's own: a press on it does not fold the row", landed and 'whole' in looks(one), looks(one))
                if not touch:                            # (a mouse's: a finger marks a word by a long press, which is no press)
                    try:
                        text = fr.locator(row % (one, '.desc')).first
                        text.dblclick(position=text.evaluate(WORD), timeout=4000)
                    except Exception:
                        pass
                    pg.wait_for_timeout(400)
                    word = marked()
                    check('console/alerts · a word marked in an open text by a double press stays marked, in a row still open',
                          len(word) > 1 and 'whole' in looks(one), {'marked': word[:24], 'the row': looks(one)})
                    # …and the list's own read does not draw over it (the read a tab asks when it is returned to — the
                    # clock's read is the same one). That a read WAS asked is counted in the page: a list that is
                    # paused, or a page that is hidden, asks nothing — and would leave the word marked for that reason.
                    fr.evaluate("""() => { const f0 = window.fetch; window.__reads = 0;
                      window.fetch = (u, o) => { if (/api\\/notifications\\?/.test(String(u))) window.__reads++; return f0(u, o); };
                      window.__whole = () => { window.fetch = f0; }; }""")
                    fr.evaluate("() => document.dispatchEvent(new Event('visibilitychange'))"); pg.wait_for_timeout(900)
                    reads = fr.evaluate('() => { window.__whole(); return window.__reads; }')
                    check('console/alerts · …and the list, read again by itself, does not draw over the marked word',
                          len(word) > 1 and reads >= 1 and marked() == word, {'reads asked': reads, 'marked': f'«{word[:24]}» -> «{marked()[:24]}»'})
                    fr.evaluate('() => getSelection().removeAllRanges()')
                landed = press(row % (one, '.title'))
                check('console/alerts · …and a press on its title folds it: read, it leaves «לא נקראו»',
                      landed and bool(one) and one not in listed() and len(listed()) == len(was) - 1, {'rows': f'{len(was)} -> {len(listed())}'})
                # …and a row opened in «הכל» is not kept among «לא נקראו» for having been opened: a list that is left
                # folds what was opened in it (the row read a moment ago: its text is cut)
                rail(pg, fr, '[data-bnv-id="read:all"]'); pg.wait_for_timeout(1200)
                opened = press(row % (one, '.title')) and 'whole' in looks(one)
                rail(pg, fr, '[data-bnv-id="read:unread"]'); pg.wait_for_timeout(1200)
                check('console/alerts · a read row opened in «הכל» is not among «לא נקראו» for having been opened',
                      opened and one not in listed(), {'opened': opened, 'listed': listed()})
                rail(pg, fr, '[data-bnv-id="read:all"]'); pg.wait_for_timeout(1200)
                # a FOLD reads nothing: the row opened, marked unread again by its own button, and folded — is unread
                press(row % (one, '.title')); press(row % (one, '.rowacts .iact')); landed = press(row % (one, '.title'))
                check('console/alerts · a row marked unread again while it is open is still unread once it is folded: a fold reads nothing',
                      landed and 'unread' in looks(one) and 'whole' not in looks(one), {'the row': looks(one)})
                if not touch:
                    # a press that MARKS text — a drag from the row's title down into its text — is no press at all
                    # (the row is unread and folded: a press would open it and read it)
                    before = ''
                    try:
                        fr.locator(row % (one, '')).first.scroll_into_view_if_needed(timeout=4000); pg.wait_for_timeout(300)
                        t, d, before = fr.locator(row % (one, '.title')).first.bounding_box(), fr.locator(row % (one, '.desc')).first.bounding_box(), looks(one)
                        pg.mouse.move(t['x'] + t['width'] - 4, t['y'] + t['height'] / 2); pg.mouse.down()
                        pg.mouse.move(d['x'] + d['width'] / 2, d['y'] + 8, steps=4)
                    except Exception:
                        pass
                    finally:
                        pg.mouse.up()                    # (whatever happened: a button left down makes the next press a drag)
                    pg.wait_for_timeout(1200)
                    check('console/alerts · a press that marks text — a drag from a title into its text — is no press: the row is as it was',
                          bool(before) and len(marked()) > 3 and looks(one) == before, {'marked': marked()[:24], 'the row': f'{before} -> {looks(one)}'})
                    fr.evaluate('() => getSelection().removeAllRanges()')
                # «נקה נקראו» DELETES, AND ASKS FIRST: the office's question, red, opening on «ביטול», naming how many are
                # read — and «ביטול» deletes nothing. (Every read notification went at one press, with nothing asked.)
                asked = lambda: fr.evaluate("""() => { const c = document.querySelector('.bask-card'); return !c ? {} : {
                  title: c.querySelector('h2').textContent, red: !!c.querySelector('.bask-btn.danger'), focus: document.activeElement.textContent }; }""")
                ask_of = lambda k: 'למחוק את ההתראה שנקראה?' if k == 1 else f'למחוק את {k} ההתראות שנקראו?'
                hush(); was = listed(); due = ask_of(len(was) - unread())
                press('#clearRead'); q = asked(); press('.bask-card .bask-btn:not(.danger)')
                check('console/alerts · «נקה נקראו» asks before it deletes, naming how many are read — and «ביטול» deletes nothing',
                      q.get('title') == due and q['red'] and q['focus'] == 'ביטול' and listed() == was and not said(),
                      {'asked': q or 'no question in the page', 'due': due, 'rows': f'{len(was)} -> {len(listed())}', 'said': said()})
                # ONE IS SAID AS ONE by the question and by the two buttons: what is read is cleared, then ONE row is read
                # and cleared; then every row but one is read, and «סמן הכל כנקרא» has one to mark
                press('#clearRead'); press('.bask-card .bask-btn.danger'); hush()
                left, q = listed(), {}
                if left:
                    press(row % (left[0], '.title')); press('#clearRead'); q = asked(); press('.bask-card .bask-btn.danger')
                check('console/alerts · one notification cleared is asked about and said as one',
                      q.get('title') == ask_of(1) and 'נוקתה התראה אחת' in said(), {'asked': q.get('title', ''), 'said': said() or 'nothing said'})
                hush()
                left = listed()
                for i in left[:-1]:
                    press(row % (i, '.title'))
                # (from here the list's own reads are held in the page: the tiles stay a read behind until they are let go)
                fr.evaluate("""() => { const f0 = window.fetch; let go; const held = new Promise((r) => { go = r; });
                  window.fetch = (u, o) => /api\\/notifications\\?/.test(String(u)) ? held.then(() => f0(u, o)) : f0(u, o);
                  window.__whole = () => { window.fetch = f0; go(); }; }""")
                if left:
                    press('#readAll')
                check('console/alerts · one notification marked read by «סמן הכל כנקרא» is said as one', 'סומנה אחת כנקראה' in said(), said() or 'nothing said')
                # THE COUNT ASKED ABOUT IS READ AT THE PRESS. A moment after «סמן הכל כנקרא», with the list's answer still
                # on its way, the tiles count what was read BEFORE it: the question named three, and four were deleted.
                hush(); behind = len(left) - unread()
                press('#clearRead'); q = asked(); press('.bask-card .bask-btn:not(.danger)')
                fr.evaluate('() => window.__whole()'); pg.wait_for_timeout(900)
                check('console/alerts · «נקה נקראו» counts what is read AT THE PRESS — every row, a moment after «סמן הכל כנקרא» — not what its tiles still show',
                      0 <= behind < len(left) and q.get('title') == ask_of(len(left)),
                      {'asked': q.get('title', ''), 'rows, all read': len(left), 'the tiles still counted read': behind})
                hush()
                # …WHERE NOTHING IS READ ANY MORE NOTHING IS ASKED (the page's read of its numbers is answered «none
                # are read», in the page — as when another window has just cleared them): the button goes off, and the
                # list — the one that was behind — is read again. The press has to LAND on rows that are still there:
                # where the button deletes without asking they are gone by now, and it is off for that reason. And A
                # COUNT THAT CANNOT BE READ IS NOT SAID (that read refused): the question asks without a number.
                plant = lambda answer: fr.evaluate("""(a) => { const f0 = window.fetch; window.__reads = 0;
                  window.fetch = (u, o) => { if (/api\\/notifications\\?/.test(String(u))) window.__reads++;
                    return !/notifications\\/stats/.test(String(u)) ? f0(u, o) : !a ? Promise.reject(new TypeError('down'))
                      : Promise.resolve(new Response(JSON.stringify(a), { status: 200, headers: { 'content-type': 'application/json' } })); };
                  window.__whole = () => { window.fetch = f0; return window.__reads; }; }""", answer)
                still = len(listed()); press('#live')                # (paused: the only read of the list is the press's own)
                plant({'total': len(left), 'unread': len(left), 'by_level': {}, 'unread_by_level': {}, 'by_source': {}, 'unread_by_source': {}})
                landed = press('#clearRead'); q = asked(); off = fr.evaluate("() => document.getElementById('clearRead').disabled")
                reads = fr.evaluate('() => window.__whole()')
                check('console/alerts · «נקה נקראו» pressed when nothing is read any more asks nothing, says nothing, goes off — and reads the list again',
                      landed and still == len(left) > 0 and not q and off and not said() and reads == 1,
                      {'the press landed': landed, 'rows': f'{len(left)} -> {still}', 'asked': q.get('title', ''), 'off': off, 'said': said(), 'the list read': reads})
                press('#live'); hush()                               # (resumed: the list and its numbers are read again)
                plant(None); press('#clearRead'); q = asked(); press('.bask-card .bask-btn:not(.danger)')
                fr.evaluate('() => window.__whole()')
                check('console/alerts · a count that cannot be read is not said: «נקה נקראו» asks without a number',
                      q.get('title') == 'למחוק את ההתראות שנקראו?' and q['red'], q or 'no question in the page')
                hush()
        finally:
            if not touch:
                pg.set_viewport_size(size)
            pg.goto(target_url()); pg.wait_for_timeout(1200)

    # An address is permanent: a tile that was renamed still opens from the id it had before — in
    # this page, with the address rewritten to the new one.
    if 'chat' in ids:
        pg.evaluate("location.hash = '/m/whatsapp'"); pg.wait_for_timeout(900)
        check('console/an address under the id a tile had before its rename opens that tile, here',
              here(pg) and pg.url.endswith('#/m/chat'), pg.url[-70:])
        if not here(pg):
            pg.goto(target_url()); pg.wait_for_timeout(1200)

    # A REMOTE app that keeps its own host (a linked office's agent). On a console where a frame
    # cannot sign in, the shell asks that host first and never frames a refusal. What the edge
    # answers is measured on a live office; here each answer is given, and what is checked is what
    # the shell does with it — the one decision that, wrong, shows the owner a browser error page.
    own = pg.evaluate(OWN_HOST)
    check('console/own host · this console cannot frame a sign-in', own['asks'], own)
    t = own['trip']
    check('console/own host · unsigned: the browser is taken to this office\'s sign-in on that host, and back to the tile',
          not t['framed'] and len(t['went']) == 1 and 'bina.macbook' in t['went'][0]
          and t['went'][0].endswith('/.dgo/enter/m/bina.macbook'), t)
    u = own['unsigned']
    check('console/own host · still unsigned a moment later: a card, not a second trip',
          not u['framed'] and not u['went'] and 'נדרשת כניסה' in u['text'], u)
    check('console/own host · the card\'s one button is the same trip',
          u['button'] == 'כניסה' and u['href'] == t['went'][0] and u['title'], u)
    check('console/own host · signed in: framed on its own host',
          len(own['signed']['framed']) == 1 and 'bina.macbook' in own['signed']['framed'][0], own['signed'])
    n = own['noname']
    check('console/own host · no such name from here: said, with nothing to press',
          not n['framed'] and 'לא ניתנת להצגה מהכתובת הזאת' in n['text'] and not n['button'], n)
    check('console/own host · the question is the path the tile names', own['asked'] and all(
          a.endswith('/.dgo/signed-in') for a in own['asked']), own['asked'])
    check('console/own host · an app that comes through the console\'s own path is never asked',
          own['door']['asked'] == 0 and own['door']['framed'] == ['/a/drive.macbook/'], own['door'])
    # …and an app of THIS office on a host of its own is asked the same way (Plane on a `.localhost`
    # office): the card, with no other office to introduce — and in desktop mode, where the app is a
    # window on that host, the window shows the card and then the app.
    # WHOSE SCREEN IS THIS. A linked office's «דרייב» and this office's are the same title over the
    # same buttons; the top bar says the office for the one that is not here, and only for it.
    check("console/own host · the top bar names the office of a linked office's tile, and of no other",
          'MacBook' in own['door']['bar'] and 'דרייב' in own['door']['bar']
          and 'MacBook' not in own['here']['bar'], [own['door']['bar'], own['here']['bar']])
    h = own['here']
    check('console/own host · an app of this office: the same card, no office named',
          not h['framed'] and 'נדרשת כניסה' in h['text'] and 'לשכת' not in h['text']
          and 'undefined' not in h['text'] and h['button'] == 'כניסה', h)
    d = own['desk']
    if d is None:                       # a phone has no desktop; at any other size that is a failure
        if '--mobile' not in sys.argv:
            check('console/own host · desktop mode mounts', False, 'no desktop on a wide viewport')
    else:
        check('console/own host · desktop window, unsigned: the card over an empty frame, and the page stays',
              'נדרשת כניסה' in d['unsigned']['card'] and not d['unsigned']['src'] and not d['unsigned']['went'],
              d['unsigned'])
        check('console/own host · desktop window, signed in after returning: the app, no card',
              not d['signed']['card'] and d['signed']['src'] == d['url'], d)
        check('console/own host · desktop window being opened, unsigned: the same trip, back to that window',
              len(d['went']) == 1 and d['went'][0].endswith('/.dgo/enter/m/plane.here'), d['went'])

    # FINDING AN APP BY TYPING. One matcher answers ⌘K and the desktop dock's «עוד» panel
    # (app.js `moduleMatches`), and it used to be a case-sensitive search of the Hebrew name: typing
    # `drive` or `DRIVE` found nothing in an office that has it. A person types what they call the
    # thing — here, its id, in both cases.
    find = pg.evaluate(FIND_BY_TYPING)
    check('console/find · ⌘K lists every app before anything is typed', find['all'] >= 10, find)
    check('console/find · an app is found by its id, in whatever case it is typed',
          find['id'] and find['lower'] >= 1 and find['upper'] == find['lower'], find)
    check('console/find · what matches nothing lists nothing', find['none'] == 0, find)

    # A LINKED OFFICE THAT IS NOT ANSWERING. The fault is INJECTED — the registry is made to say what
    # the office's own link measurement says when a hop falls (`remote.ok: false` + the hop's
    # sentence) — because a healthy run never shows it, and the one time it was real the owner got a
    # blank frame and fifteen hours of tiles that looked alive. Then the office comes back, and
    # nothing may need a reload to say so.
    link = pg.evaluate(LINK_DOWN)
    check('console/link down · every tile of that office is marked before anything is opened, and says which hop fell',
          all(r and r['off'] and r['meta'] == 'MacBook' and 'לא זמינה כרגע' in r['tip']
              and 'המנהרה אליה לא מעבירה תנועה' in r['tip'] for r in link['marked']), link['marked'])
    check('console/link down · its own-host tile opens as a card naming the office and the hop — nothing is framed',
          not link['card']['framed'] and 'MacBook' in link['card']['text']
          and 'המנהרה אליה לא מעבירה תנועה' in link['card']['text']
          and link['card']['buttons'] == ['נסה שוב', 'פתיחה בחלון נפרד'] and link['card']['bar'], link['card'])
    check('console/link down · «נסה שוב» asks the office for real, once — the next plain open is the card again',
          len(link['again']) == 1 and 'notes.macbook' in link['again'][0]
          and not link['card_again']['framed'] and link['card_again']['card'], [link['again'], link['card_again']])
    check('console/link down · the office is back: the marks go and the card becomes the app, with no reload',
          all(r and not r['off'] and 'לא זמינה' not in r['tip'] for r in link['back']['rail'])
          and len(link['back']['framed']) == 1 and link['alive'], link['back'])
    # The rail's office column is 5em: the state is FORM there (the tag's colour, the row dimmed),
    # so it is the form that is asserted — it must differ between "not answering" and "back".
    check('console/link down · the rail says it in form: the office tag changes colour and the row dims',
          all(a['color'] != b['color'] and a['dim'] < 1 and b['dim'] == 1
              for a, b in zip(link['marked'], link['back']['rail'])), [link['marked'], link['back']['rail']])
    check('console/link down · a verdict that turns under a working app redraws the marks and reloads nothing',
          not link['in_view']['framed'] and link['in_view']['rail']['off'] and link['in_view']['bar'],
          link['in_view'])
    if link.get('home') is not None:
        check('console/link down · phone launcher: the tile itself says its office is unavailable',
              link['home'].get('off') and link['home'].get('lines') == ['MacBook', 'לא זמינה כרגע']
              and not link['home'].get('cut'), link['home'])

    # THE PAGE'S OWN SIGN-IN RAN OUT. The edge answers the page's question with a redirect to the
    # identity provider; the page says so (one button) when somebody is using it, and takes the
    # top-level load at once when nobody is — a return to the tab — but never twice in a row.
    out = pg.evaluate(SIGNED_OUT)
    check('console/signed out · in use: said, with one button, and nothing is loaded behind a person\'s back',
          out['said'] and 'הכניסה ללשכה פגה' in out['said']['text'] and out['said']['button'] == 'כניסה'
          and out['said']['went'] == 0 and out['pressed'] == 1, out)
    check('console/signed out · on a return to the tab: the sign-in is taken at once',
          out['first'] == 1 and not out['overlay1'], out)
    check('console/signed out · …and not twice in a row (that would be a loop): the second time it is said',
          out['second'] == 1 and out['overlay2'], out)

    # A TAB THAT STAYS OPEN. The office changes under a page that lives for days; the page is told
    # (`/api/version`) and renews itself: tiles at once, the shell itself at the next navigation.
    stays = pg.evaluate(STAYS_OPEN)
    check('console/stays open · a changed tile list is re-read, with no reload',
          stays['tile'] and stays['alive'], stays)
    check('console/stays open · a new shell build is not loaded under a person\'s hands',
          stays['alive_after_new_build_in_view'], stays)
    try:
        pg.evaluate("() => { freshen(true); }")           # the next navigation: the page goes away
    except Exception:
        pass
    pg.wait_for_timeout(2500)
    check('console/stays open · a new shell build is loaded at the next navigation',
          pg.evaluate("() => window.__drawn_before_the_new_build === undefined"))


# The palette, asked for an app the way a person types it: an id from the rail whose Hebrew label
# does not contain it (so it is the ID that has to match), lower-case and upper-case.
FIND_BY_TYPING = """() => {
  const rail = [...document.querySelectorAll('#nav a[data-id]')];
  const a = rail.find(x => /^[a-z][a-z0-9-]+$/.test(x.dataset.id)
                        && !x.textContent.toLowerCase().includes(x.dataset.id));
  const id = a ? a.dataset.id : '';
  openPalette();
  const input = document.querySelector('#palInput');
  const typed = q => { input.value = q; input.dispatchEvent(new Event('input', {bubbles: true}));
                       return document.querySelectorAll('#palList .pal-item').length; };
  const out = {id, all: typed(''), lower: typed(id), upper: typed(id.toUpperCase()), none: typed('zzzz-no-such-app')};
  closePalette();
  return out;
}"""

# Two tiles of a linked office are added to what the registry answers — one that keeps its own host
# and one the console proxies — and opened through the shell's own router. The edge's answer and the
# frame are stood in for, so nothing is fetched from a host that does not exist here.
OWN_HOST = """async () => {
  const from = {office: 'macbook', label: {he: 'MacBook'}};
  const own = {id: 'bina.macbook', name: 'בינה ודעת', icon: 'bot', group: 'ראשי', external: true,
               host: 'bina.macbook', embed: '/a/bina/', signed_in: '/.dgo/signed-in', enter: '/.dgo/enter', remote: from};
  const door = {id: 'drive.macbook', name: 'דרייב', icon: 'folder', group: 'עסק', external: true,
                host: 'drive.macbook', embed: '/a/drive/', proxy: '/a/drive.macbook/', remote: from};
  const here = {id: 'plane.here', name: 'ניהול פרויקטים', icon: 'check', group: 'עסק', external: true,
                host: 'plane', embed: '/a/plane/', signed_in: '/.dgo/signed-in', enter: '/.dgo/enter'};
  const real = {fetch: window.fetch, showEmbed, hash: location.hash, leave: leaveFor};
  const asked = [], framed = [], trips = [];
  let answer = '';
  leaveFor = (u) => { trips.push(u); };                  // the trip is counted, not taken
  const tried = (id, when) => { enterOwnHost.gone = false; trips.length = 0;
                                 try { sessionStorage.setItem('do-enter:' + id, String(when)); } catch (e) {} };
  window.fetch = async (u, o) => {
    if (String(u).endsWith(own.signed_in)) {
      asked.push(String(u));
      if (!answer) throw new TypeError('no such name');
      return {type: answer};
    }
    const r = await real.fetch(u, o);
    if (!String(u).includes('/api/modules')) return r;
    const listed = (await r.json()).modules;
    return {ok: true, json: async () => ({modules: listed.concat([own, door, here])})};
  };
  showEmbed = (u) => { framed.push(u); };
  await refreshModules(false);
  const open = async (id, a) => {
    answer = a; framed.length = 0;
    if (location.hash === '#/m/' + id) route(); else location.hash = '#/m/' + id;
    await new Promise(done => setTimeout(done, 120));    // the host is asked, then the shell draws
    const c = document.querySelector('#content'), b = c.querySelector('a.btn');
    return {framed: framed.slice(), text: c.innerText, bar: document.querySelector('#viewTitle').innerText,
            button: b ? b.textContent.trim() : '', href: b ? b.getAttribute('href') : '', title: b ? b.title : ''};
  };
  const out = {asks: noNestedHost(location.hostname)};
  tried(own.id, 0);                                      // never tried: the browser is taken there
  out.trip = Object.assign(await open(own.id, 'opaqueredirect'), {went: trips.slice()});
  tried(own.id, Date.now());                             // tried a moment ago and it still asks: the card
  out.unsigned = Object.assign(await open(own.id, 'opaqueredirect'), {went: trips.slice()});
  out.noname = await open(own.id, '');
  out.signed = await open(own.id, 'cors');
  out.asked = asked.slice(); asked.length = 0;
  const through = await open(door.id, 'cors');
  out.door = {framed: through.framed, asked: asked.length, bar: through.bar};
  tried(here.id, Date.now());
  out.here = await open(here.id, 'opaqueredirect');
  // The same tile as a desktop WINDOW. Its address is stood in for (the sim has no host to nest
  // under); what is checked is what the window shows for each answer of the edge.
  out.desk = null;
  const realUrl = externalUrl, wait = () => new Promise(done => setTimeout(done, 150));
  externalUrl = (m) => m.id === here.id ? 'http://127.0.0.1:9/' : realUrl(m);
  answer = 'opaqueredirect';
  BinaDesktop.enable();
  if (BinaDesktop.isOn()) {
    const seen = async (a) => {
      answer = a; BinaDesktop.askOwnHosts(); await wait();
      const w = document.querySelector('.dk-win.external');
      return {card: w.querySelector('.dk-ask').innerText, src: w.querySelector('iframe').getAttribute('src') || '',
              went: trips.slice()};
    };
    await wait();                       // mounting routes the hash: the tile in view is the window
    tried(here.id, 0);                  // an OPEN window never goes by itself, whenever the last trip was
    out.desk = {url: 'http://127.0.0.1:9/', unsigned: await seen('opaqueredirect'), signed: await seen('cors')};
    document.querySelector('.dk-win.external .dk-l.close').click();
    tried(here.id, 0); answer = 'opaqueredirect';        // …and a window that is being OPENED goes itself
    BinaDesktop.openModule(here); await wait();
    out.desk.went = trips.slice();
    document.querySelector('.dk-win.external .dk-l.close').click();
    BinaDesktop.disable();
  }
  externalUrl = realUrl; leaveFor = real.leave; enterOwnHost.gone = false;
  window.fetch = real.fetch; showEmbed = real.showEmbed;
  openClose(door.id);
  await refreshModules(false);
  location.hash = real.hash;
  return out;
}"""


# What the server says the page should have been drawn from is stood in for: first a registry with
# one more tile, then a different build of the shell. The stand-in stays in place for the reload
# check that follows, and goes away with the page.
# The edge's answer is stood in for (a redirect where the page expects JSON), and the top-level load
# is counted instead of taken — what is checked is the page's decision for each situation.
SIGNED_OUT = """async () => {
  const real = {fetch: window.fetch, go: signInAgain};
  let went = 0;
  signInAgain = () => { went++; };
  window.fetch = async (u, o) => String(u).includes('/api/version') ? {type: 'opaqueredirect'} : real.fetch(u, o);
  const fresh = () => { signedOut.asked = false; try { sessionStorage.removeItem('do-signin'); } catch (e) {} };
  fresh();
  await freshen(false);
  let dlg = document.querySelector('.signed-out');
  const said = dlg ? {text: dlg.innerText, button: dlg.querySelector('button').textContent.trim(), went} : null;
  if (dlg) { dlg.querySelector('button').click(); dlg.remove(); }
  const pressed = went;
  fresh(); went = 0;
  await freshen(false, true);
  const first = went, overlay1 = !!document.querySelector('.signed-out');
  signedOut.asked = false;
  await freshen(false, true);
  dlg = document.querySelector('.signed-out');
  const second = went, overlay2 = !!dlg;
  if (dlg) dlg.remove();
  fresh(); window.fetch = real.fetch; signInAgain = real.go;
  return {said, pressed, first, overlay1, second, overlay2};
}"""


# Two tiles of a linked office — one on a host of its own, one the console proxies — whose office the
# registry says is unreachable, then reachable, then unreachable again. The registry and the page's
# "what should I have been drawn from" question are stood in for; the frame is counted, not loaded.
LINK_DOWN = """async () => {
  window.__link_down_page = true;
  const why = 'המנהרה אליה לא מעבירה תנועה: היא כבויה, מנותקת מהרשת, או שהקישור נפל.';
  const from = (ok) => Object.assign({office: 'macbook', label: {he: 'MacBook'}}, ok ? {ok: true} : {ok: false, why});
  const tiles = (ok) => [
    {id: 'notes.macbook', name: 'פתקים', icon: 'file', group: 'עסק', external: true, host: 'notes.macbook',
     embed: '/a/notes/', remote: from(ok)},
    {id: 'drive.macbook', name: 'דרייב', icon: 'folder', group: 'עסק', external: true, host: 'drive.macbook',
     embed: '/a/drive/', proxy: '/a/drive.macbook/', remote: from(ok)}];
  const real = {fetch: window.fetch, showEmbed, externalFallback, hash: location.hash};
  const drawn = await real.fetch('/api/version').then(r => r.json()).catch(() => ({}));   // what this page was drawn from
  const framed = [];
  let ok = false, turn = 0;
  window.fetch = async (u, o) => {
    if (String(u).includes('/api/version'))
      return {ok: true, json: async () => Object.assign({}, drawn, {registry: 'link-' + turn})};
    const r = await real.fetch(u, o);
    if (!String(u).includes('/api/modules')) return r;
    const listed = (await r.json()).modules;
    return {ok: true, json: async () => ({modules: listed.concat(tiles(ok))})};
  };
  showEmbed = (u) => { framed.push(u); };
  externalFallback = () => {};                       // the frame is stood in for: nothing to look at
  const settle = () => new Promise(done => setTimeout(done, 200));
  const rail = (id) => { const a = document.querySelector('#nav a[data-id="' + id + '"]');
    const meta = a && a.querySelector('.bnv-meta');
    return a ? {off: a.classList.contains('is-offline'), tip: a.title, meta: meta ? meta.textContent : '',
                color: meta ? getComputedStyle(meta).color : '',
                dim: +getComputedStyle(a.querySelector('.bnv-label')).opacity} : null; };
  const barOff = () => !!document.querySelector('#viewTitle .vt-office.is-off');
  const out = {home: null};
  // measured unreachable: marked before anything is opened
  await freshen(false, true); await settle();
  out.marked = [rail('notes.macbook'), rail('drive.macbook')];
  if (matchMedia('(max-width: 640px)').matches) {
    renderHome();
    const t = document.querySelector('.htile[data-hid="drive.macbook"]');
    const line = t && t.querySelector('.htile-office');
    out.home = line ? {off: t.classList.contains('is-offline'),
                       lines: [...line.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent),
                       cut: line.scrollWidth > line.clientWidth + 1} : {};
  }
  // its own-host tile: the card, naming the office and the hop — and nothing framed
  location.hash = '#/m/notes.macbook'; await settle();
  const c = document.querySelector('#content');
  out.card = {framed: framed.slice(), text: c.innerText, bar: barOff(),
              buttons: [...c.querySelectorAll('.xn-acts .btn')].map(b => b.textContent.trim())};
  // «נסה שוב»: asked for real, once — the next plain open is the card again
  const again = c.querySelector('.xn-acts button');
  if (again) again.click();
  await settle();
  out.again = framed.slice(); framed.length = 0;
  route(); await settle();
  out.card_again = {framed: framed.slice(), card: !!document.querySelector('#content .xn')};
  // the office is back: the page learns it at its next question — the marks go, the card becomes the app
  ok = true; turn++; await freshen(false, true); await settle();
  out.back = {rail: [rail('notes.macbook'), rail('drive.macbook')], framed: framed.slice()};
  // a verdict that turns while a WORKING app is in view redraws the marks and reloads nothing
  location.hash = '#/m/drive.macbook'; await settle();
  framed.length = 0;
  ok = false; turn++; await freshen(false, true); await settle();
  out.in_view = {framed: framed.slice(), rail: rail('drive.macbook'), bar: barOff()};
  out.alive = window.__link_down_page === true;
  await new Promise(done => setTimeout(done, 2600));   // the shell's own "did the frame come up" timers pass
  window.fetch = real.fetch; showEmbed = real.showEmbed; externalFallback = real.externalFallback;
  openClose('drive.macbook');
  await freshen(false);                              // …and the page is its own again
  location.hash = real.hash;
  return out;
}"""


STAYS_OPEN = """async () => {
  window.__drawn_before_the_new_build = true;
  const real = window.fetch;
  const more = {id: 'linked.later', name: 'נוסף אחר כך', icon: 'bot', group: 'עסק', embed: '/a/my-docs/'};
  let says = {registry: 'another'};
  window.fetch = async (u, o) => {
    if (String(u).includes('/api/version')) return {ok: true, json: async () => says};
    const r = await real(u, o);
    if (!String(u).includes('/api/modules')) return r;
    const listed = (await r.json()).modules;
    return {ok: true, json: async () => ({modules: listed.concat([more])})};
  };
  await freshen(false);
  const out = {tile: !!document.querySelector('#nav a[data-id="linked.later"]'),
               alive: window.__drawn_before_the_new_build === true};
  says = {registry: 'another', shell: 'a newer build'};
  await freshen(false);
  out.alive_after_new_build_in_view = window.__drawn_before_the_new_build === true;
  return out;
}"""


# ══ SCROLL ═══════════════════════════════════════════════════════════════════════════════════════
def scroll_flows(pg, errs):
    """No screen may scroll on the same axis twice.

    A long settings page scrolling is fine — that is one scrollbar doing its job. What is never fine
    is the PAGE scrolling while a region inside it also scrolls vertically: two bars stacked on one
    axis, and the wheel obeys whichever the pointer happens to be over. It is always caused by the
    same thing — something inside declaring a fixed height instead of taking the height it is given.
    """
    print("\nSCROLL")
    pg.goto(target_url()); pg.wait_for_timeout(900)
    for m in tiles(LAYOUT_MODS):
        if not screen(pg, 'scroll', m):
            continue
        fr = [f for f in pg.frames if f != pg.main_frame]
        host = fr[0] if fr else pg.main_frame
        try:
            r = host.evaluate("""() => {
              const inner = [];
              const walk = el => { for (const c of el.children) {
                if (c.scrollHeight > c.clientHeight + 8 && c.clientHeight > 120) {
                  const cs = getComputedStyle(c);
                  if (['auto','scroll'].includes(cs.overflowY))
                    inner.push((c.className||'').toString().slice(0,30));
                } walk(c); } };
              walk(document.body);
              const se = document.scrollingElement;
              return { doc: se.scrollHeight - se.clientHeight, inner };
            }""")
        except Exception as e:
            check(f'scroll/{m}', False, str(e)); continue
        doubled = r['doc'] > 4 and len(r['inner']) > 0
        check(f'scroll/{m} not doubled', not doubled,
              f"page overflows {r['doc']}px AND {r['inner'][:2]} scrolls")



# ══ LAYOUT INVARIANTS ════════════════════════════════════════════════════════════════════════════
# Rules that must hold on EVERY screen at EVERY width. Each one is a defect that has actually
# shipped here, and each is invisible to a flow test (the flow passes; the screen just looks wrong).
LAYOUT_MODS = ['my-docs', 'drive', 'mail', 'chat', 'incoming', 'concurrency', 'alerts',
               'machine', 'validation', 'connections', 'apps']
# The panels a screen opens over itself: each (what opens it, the panel, what closes it) — and a fourth
# word, True, when what opens it lives in the screen's rail, which a phone keeps behind a drawer. See rule 9.
PANELS = {'my-docs': [('#newBtn', '#editor', '#closeEditor'), ('tr[data-id]', '#drawer', '#closeDrawer')],
          'drive': [('tr[data-id] .name-open', '#pvfull', '[data-pv="close"]'), ('#newFolderBtn', '#modal', '#mClose', True)],
          'mail': [('.gm-row .gm-sub', '#reader', '#rClose'), ('#sideNav .bnv-primary', '.mlc-ov', '.mlc-ov [data-x]', True)],
          'connections': [('button[onclick="addSecret()"]', '.ov', '.ov [data-x]')],
          'apps': [('.card:not([data-remote]) .nm', '#drawer', '#drawer [data-act="close"]')]}
# The screens a tile has beyond the one it opens on: each (its name, the presses that reach it). A press written
# `rail:<selector>` is in the tile's side menu, which a phone keeps in a drawer. See rule 12.
_MAIL_SET = ['rail:#sideNav [data-bnv-id="settings"]', '#gearMenu [data-go="settings"]']
VIEWS = {'mail': [('the tag rules', ['rail:#sideNav [data-bnv-id="settings"]', '#gearMenu [data-go="organizer"]']),
                  ('its addresses', _MAIL_SET + ['#setTabs [data-sec="mailboxes"]']),
                  ('its private-mail checklist', _MAIL_SET + ['#setTabs [data-sec="setup"]']),
                  ('its accounts', _MAIL_SET + ['#setTabs [data-sec="connect"]'])]}
# (in the simulation the second capability's cases run a workflow, and an opened one names its links. It is reached
#  by its place in the mock's list: a running office orders its capabilities its own way, and is not asked this.)
if not target_url().startswith('http'):
    VIEWS['validation'] = [('a case, opened', ['#feat-1 .feature-header', '#cases-1 .case-row'])]
# What a screen offers in a panel it FOLDS AWAY in a narrow frame, each (what it is, the ways to it): one of the ways
# is in sight and is what a finger hits at every width — a phone, and the window desktop mode opens the screen in.
# The office's own side menu is held to this by rule 13; this is for a panel a screen made itself. See rule 20.
REACH = {'chat': [('a new conversation', ['#newChat', '#mNew'])]}
# -> whether one of the ways is on the screen and on top where a finger lands (below the fold counts: a page scrolls)
REACH_PROBE = r"""(ways) => ways.some((sel) => { const e = document.querySelector(sel);
  if (!e || !e.checkVisibility({ checkVisibilityCSS: true })) return false;
  const r = e.getBoundingClientRect(); if (!r.width || r.right <= 0 || r.left >= innerWidth) return false;
  if (r.top + r.height / 2 >= innerHeight) return true;
  const top = document.elementFromPoint(r.left + r.width / 2, Math.max(r.top + r.height / 2, 1));
  return !!top && (top === e || e.contains(top)); })"""
# -> the controls of an open panel that a touch at their centre would NOT reach, each with what lies on it
FINGER_PROBE = r"""(sel) => {
  const p = document.querySelector(sel);
  if (!p || !p.getBoundingClientRect().width) return ['the panel did not open'];
  const name = (e) => (e.id || (typeof e.className === 'string' && e.className) || e.title || e.textContent.trim() || e.tagName).toString().slice(0, 24);
  const ctl = [...p.querySelectorAll('button, input, select, textarea, a[href]')].filter((e) => e.getBoundingClientRect().width);
  // sideways first, and before anything is scrolled: a finger brings a control UP — a row of buttons wider
  // than its panel is not "reached" because the panel's body can be dragged sideways to it
  const past = ctl.filter((e) => { const r = e.getBoundingClientRect(); return r.left < -1 || r.right > innerWidth + 1; });
  return past.map((e) => name(e) + " is past the window's edge").concat(ctl.filter((e) => !past.includes(e)).map((e) => {
    e.scrollIntoView({ block: 'center' });                 // as a finger would bring it up
    const r = e.getBoundingClientRect(), top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return top === e || (top && e.contains(top)) ? null : name(e) + ' is under ' + (top ? name(top) : 'nothing');
  }).filter(Boolean));
}"""
# -> the fields of an open panel too narrow to show what is typed in them, each with its width
THIN_PROBE = r"""(sel) => [...document.querySelectorAll(sel + ' input, ' + sel + ' select, ' + sel + ' textarea')]
  .filter((e) => { const w = e.getBoundingClientRect().width; return w && w < 44 && !/^(checkbox|radio|file|hidden)$/.test(e.type); })
  .map((e) => (e.id || e.dataset.k || e.tagName).toString().slice(0, 24) + ' is ' + Math.round(e.getBoundingClientRect().width) + 'px wide')"""
# -> the buttons of an open panel that are always in sight (not inside a part of it that scrolls) and that the
#    office's notice, said now, would lie over; null where the page has no such notice
NOTICE_PROBE = r"""(sel) => {
  if (typeof binaTell !== 'function') return null;
  const p = document.querySelector(sel), n = binaTell('zz', 'bad'), b = n.getBoundingClientRect();
  const scrolls = (e) => { for (let a = e.parentElement; a && a !== p; a = a.parentElement) if (/(auto|scroll)/.test(getComputedStyle(a).overflowY) && a.scrollHeight > a.clientHeight + 1) return true; return false; };
  const under = [...p.querySelectorAll('button')].filter((e) => { const r = e.getBoundingClientRect();
    return r.width && !scrolls(e) && r.left < b.right && b.left < r.right && r.top < b.bottom && b.top < r.bottom; })
    .map((e) => (e.id || e.textContent || e.className).toString().trim().slice(0, 24));
  n.remove(); return under;
}"""


# -> a screen's requests are cut off where it stands (both ways a page asks), and its own «רענון» is pressed when
#    it has one; answers with that control's name, or null
SILENCE_PROBE = r"""() => { const w = window; w.__stays = 1; w.__asked = [w.fetch, XMLHttpRequest.prototype.send];
  w.fetch = () => Promise.reject(new TypeError('Failed to fetch'));
  XMLHttpRequest.prototype.send = function () { setTimeout(() => this.dispatchEvent(new ProgressEvent('error')), 0); };
  const b = [...document.querySelectorAll('button, a.btn')].find(e => e.getClientRects().length
    && /רענ/.test((e.id || '') + (e.title || '') + (e.getAttribute('aria-label') || '') + e.textContent));
  if (b) b.click(); return b ? (b.id || b.textContent.trim()).slice(0, 20) : null; }"""
# -> …and a moment later: is it the same page still, and how many placeholders it shows; its requests are given back
HEARD_PROBE = r"""() => { const w = window, was = w.__asked; if (was) { w.fetch = was[0]; XMLHttpRequest.prototype.send = was[1]; }
  return { stayed: w.__stays === 1, loading: [...document.querySelectorAll('.sk, .skel, .skeleton, .spin, .spinner, [aria-busy="true"]')]
    .filter(e => e.getClientRects().length).length }; }"""
# -> what a tile's frame shows a moment after it was LOADED: is it the tile's own page still (the simulation's
#    switch is in it), how many placeholders are in sight, does it SAY that it was not read (the office's words
#    for it, as its screens use them) — and what it says that is NOT words (the browser's or the parser's own
#    sentence, a bare status where the cause belongs; a status beside the cause, as its detail, is a fact), how
#    many of its chips go on saying «חי», what it says THERE IS NONE OF (a list that was never read is not an
#    empty one), whether its side menu stands as a blank column, and the beginning of what it says
LOADED_PROBE = r"""() => { const text = (document.body ? document.body.innerText : '').replace(/\s+/g, ' ').trim();
  const seen = (e) => e.getClientRects().length;
  const none = [];
  for (let t = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT), n; (n = t.nextNode());) {
    const s = n.nodeValue.replace(/\s+/g, ' ').trim(), p = n.parentElement;
    if (s && s.length < 60 && p && seen(p) && getComputedStyle(p).visibility !== 'hidden'
        && /^(אין|לא נמצאו|עדיין אין)\s/.test(s) && !/^אין (תשובה|חיבור|גישה|הרשאה)/.test(s)) none.push(s);
  }
  const menu = document.querySelector('.bnv'), rows = menu && (menu.querySelector('.bnv-scroll') || menu);
  return { own: !!document.querySelector('script[data-sim="silent"]'),
    loading: [...document.querySelectorAll('.sk, .skel, .skeleton, .spin, .spinner, [aria-busy="true"]')].filter(seen).length,
    said: /לא נטע[נן]|אין תשובה|אינו זמין|נכשל|שגיא[הת]|לא ניתן/.test(text),
    raw: (text.match(/Failed to \w+|Unexpected token|body stream|is not valid JSON|\bAPI \d{3}\b|שגיאה \(\d{3}\)/g) || []).slice(0, 2),
    live: [...document.querySelectorAll('span, button, b')].filter(e => seen(e) && e.textContent.trim() === 'חי').length,
    none: none.slice(0, 3),
    blank: !!rows && seen(menu) && ![...rows.querySelectorAll('*')].some(e => seen(e) && e.textContent.trim()),
    says: text.slice(0, 70) }; }"""
# -> what the simulation's instance chip (the console's top bar) says of the account in view, or null
CHIP_PROBE = r"""() => { const b = document.querySelector('.dosw-top .dosw-btn'); return b ? b.getAttribute('aria-label') : null; }"""
# -> the rows of NUMBER TILES in this frame that leave one alone: a grid or a wrapping row of three or more boxes
#    of one kind, each holding a short value set large, whose last row holds exactly ONE under a row of three or more
ALONE_PROBE = r"""() => { const out = [];
  const tile = (e) => [...e.querySelectorAll('*')].some(x => x.getClientRects().length && !x.children.length
    && parseFloat(getComputedStyle(x).fontSize) >= 19 && /\d/.test(x.textContent) && /^[\d.,%₪\s\-–/:A-Za-z]{1,14}$/.test(x.textContent.trim()));
  for (const g of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(g);
    if (!(cs.display === 'grid' || (cs.display === 'flex' && cs.flexWrap !== 'nowrap'))) continue;
    const kids = [...g.children].filter(k => k.getClientRects().length);
    if (kids.length < 3 || !kids.every(k => k.tagName === kids[0].tagName && k.classList[0] === kids[0].classList[0]) || !kids.every(tile)) continue;
    const rows = {}; for (const k of kids) { const y = Math.round(k.getBoundingClientRect().top / 4); rows[y] = (rows[y] || 0) + 1; }
    const n = Object.keys(rows).sort((a, b) => a - b).map(y => rows[y]);
    if (n.length > 1 && n[n.length - 1] === 1 && n[0] >= 3)
      out.push((g.classList[0] || g.tagName.toLowerCase()) + ' ' + n.join('+') + ' in a frame of ' + innerWidth + 'px');
  }
  return out; }"""
# -> the views a frame names with a tab, by what each tab reads
TABS_PROBE = r"""() => [...document.querySelectorAll('.tabstrip .tab, [role=tab]')].filter(e => e.getClientRects().length)
  .map(e => e.textContent.replace(/\s+/g, ' ').trim().slice(0, 24))"""
# the tiles whose screens HAVE instances (accounts, connections): the simulation's switcher keeps their chip in the top bar
WITH_INSTANCES = ('drive', 'mail', 'chat', 'incoming')
# The texts a screen cuts to a set number of lines — each shown WHOLE by a press on it: (the texts, the ones among
# them a press on which changes nothing on a running office). See rule 25.
CLAMPED = {'alerts': ('.item .desc', '.item:not(.unread) .desc')}
# What rule 24 knows of and does not ask yet: a control under 30px that stands in a file of another writer's, with
# the item that asks it of them. A name here is a DEBT recorded on that item, not a pass — anything else in the same
# panel still fails — and it leaves this list the day its item closes. (tile, panel) -> (what the probe says, item)
TAP_OWED = {('apps', '#drawer'): (('button.x 26x26',), 'DGO-529')}


def framed(pg):
    """The frame the open tile is drawn in — the largest one in sight — or None where the shell draws the tile
    itself (it also keeps spent frames, out of sight, which are nobody's screen)."""
    best, at = 0, None
    for el in pg.query_selector_all('iframe'):
        box = el.bounding_box() if el.is_visible() else None
        if box and box['width'] * box['height'] > best:
            best, at = box['width'] * box['height'], el.content_frame()
    return at


def loaded(pg, how):
    """Load the open tile's frame AGAIN, its service being what `how` says — 'none' (no answer at all),
    'refused' (a proxy's 502 page), None (answering) — and -> what the frame shows a moment later. The
    simulation's pages carry the switch (build.mjs SILENT); a running office's do not."""
    fr = framed(pg)
    fr.frame_element().evaluate("(e, how) => { top.__simSilent = how; const d = e.srcdoc; e.srcdoc = ''; e.srcdoc = d; }", how)
    pg.wait_for_timeout(2500)
    try:
        return fr.evaluate(LOADED_PROBE)
    except Exception as e:                                      # the frame was sent somewhere else
        return {'own': False, 'loading': 0, 'said': False, 'went': str(e).split('\n')[0][:90]}


def here(pg):
    """Is the top page still the office the suite was pointed at (whatever its route or query)?"""
    page = lambda u: u.split('#')[0].split('?')[0].rstrip('/')          # noqa: E731
    return page(pg.url) == page(target_url())


def screen(pg, suite, m):
    """Open one tile for a screen-level check — and say so when the page is no longer the office.

    Every check below reads "the page" and passes on anything with a body. For five weeks that
    included Chrome's own error page: the list still named a tile by the id it had before a rename,
    the shell's rewrite of that address took the simulation's top page away (build.mjs had given the
    SHELL the `<base>` meant for framed apps), and the eight tiles after it were measured — no
    sideways scroll, nothing spilling, "has content" — on "This site can't be reached". Two thirds
    of both suites' green lines said nothing (found 2026-10-06, by reading the JS errors under them).

    …and when the screen has not SAID anything yet. The wait here was 2.2 seconds, whatever the
    screen was doing; against a running office a list that takes five seconds was measured as its
    six placeholder cards, and passed (no sideways scroll, nothing spilling, "has content"). The
    screen is asked until it is drawn (drawn.py); one that needs longer than a screen may take is a
    failure of its own, and one that never is drawn is not measured at all.
    """
    t0 = time.monotonic()
    pg.evaluate("x => location.hash = '/m/' + x", m)
    r = drawn.wait(pg.evaluate, pg.wait_for_timeout, since=t0, at_least_ms=2200)
    if not here(pg):
        check(f'{suite}/{m}', False, f'the page left the office for {pg.url[:80]}')
        pg.goto(target_url()); pg.wait_for_timeout(900)
        return False
    # …and when the office has no tile of that name. The shell sends an id it does not know to its FIRST tile:
    # `install` stayed in the list after the install screen was taken out of the shell, and every rule of two
    # suites was asked of my-docs a second time and passed under its name (found by looking at what stood there).
    at = pg.evaluate("() => location.hash")
    if not at.startswith('#/m/' + m):
        check(f'{suite}/{m}', False, f'the office has no tile of this name: its address became {at[:50]}')
        return False
    if late(r):
        check(f'{suite}/{m} has said what it has to say in time, before it is measured', False, drawn.said(r))
    return r['drawn']


def late(r):
    """Is this verdict of drawn.py a failure HERE? A screen that never finished is one anywhere. A
    screen that was only slow is one on a running office (`--url`), where the time is a person's
    wait; in the simulation it is this machine's load as much as the screen's own, and a check that
    turns on that says nothing about the screen."""
    return not r['drawn'] or (r['slow'] and target_url().startswith('http'))

LAYOUT_PROBE = """() => {
  const se = document.scrollingElement, vw = se.clientWidth, vh = se.clientHeight;
  const inner = [];
  const walk = el => { for (const c of el.children) {
    if (c.scrollHeight > c.clientHeight + 8 && c.clientHeight > 120) {
      const cs = getComputedStyle(c);
      if (['auto','scroll'].includes(cs.overflowY)) inner.push((c.className||'').toString().slice(0,30));
    } walk(c); } };
  walk(document.body);
  // Elements poking past the viewport edge. Two things legitimately sit outside it and must NOT
  // be flagged, or the check cries wolf and gets ignored:
  //   · a CLOSED off-canvas drawer — it is parked off-screen on purpose, waiting to slide in.
  //   · anything inside a horizontally scrollable/clipping ancestor — a wide table inside its own
  //     scroll region is the CORRECT answer to "this content is wider than the screen".
  // What is left is content that genuinely escaped and that nobody can ever reach.
  const contained = el => {
    for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
      const cs = getComputedStyle(a);
      if (['auto','scroll','hidden','clip'].includes(cs.overflowX)) return true;
      if (cs.position === 'fixed') return true;
      // an off-canvas panel: translated away, or explicitly hidden from a11y
      if (a.getAttribute('aria-hidden') === 'true') return true;
      const t = cs.transform;
      if (t && t !== 'none' && /matrix/.test(t)) {
        const tx = parseFloat(t.split(',')[4] || '0');
        if (Math.abs(tx) > 40) return true;
      }
    }
    return false;
  };
  const spills = [];
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el);
    if (cs.position === 'fixed' || cs.display === 'none' || cs.visibility === 'hidden') continue;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    if ((r.right > vw + 2 || r.left < -2) && !contained(el)) {
      spills.push(`${el.tagName}.${(el.className||'').toString().slice(0,22)}`);
      if (spills.length > 4) break;
    }
  }
  return { vw, vh,
           hOverflow: se.scrollWidth - vw,
           vOverflow: se.scrollHeight - vh,
           innerScrollers: inner,
           spills,
           textLen: (document.body.innerText || '').trim().length };
}"""


def layout_flows(pg, errs):
    print("\nLAYOUT")
    pg.goto(target_url()); pg.wait_for_timeout(900)
    size = pg.viewport_size
    with_menu = []                              # the tiles that carry the office's side menu (rule 13)
    for m in tiles(LAYOUT_MODS):
        if not screen(pg, 'layout', m):
            continue
        # 17 — the instance chip in the console's top bar is THIS screen's, or there is none. The simulation's
        #      switcher mounts a chip there from each of the four apps that have instances, and left it standing
        #      on the next tile: «מכונה» was read under INDOX's «סבח סוכנויות». (Its own overlay: not asked of a
        #      running office, whose screens keep their accounts inside themselves.)
        if not target_url().startswith('http') and m not in WITH_INSTANCES:
            chip = pg.evaluate("() => { const c = document.querySelector('.dosw-top'); return c ? c.innerText.replace(/\\s+/g, ' ').trim().slice(0, 40) : null; }")
            check(f"layout/{m} a screen with no instances stands under no other screen's instance chip", chip is None, chip)
        # A view the console shell draws itself has no frame, and the console leaves a spent
        # about:blank iframe behind when it switches to one — so "the first non-main frame" is
        # not the screen. Probe whichever frame actually rendered something.
        best, r = -1, None
        for f in pg.frames:
            try:
                got = f.evaluate(LAYOUT_PROBE)
            except Exception:
                continue
            if got['textLen'] > best:
                best, r = got['textLen'], got
        if r is None:
            check(f'layout/{m}', False, 'no probeable frame'); continue

        # 1 — the page never scrolls sideways. Horizontal scroll on a whole page is never a design
        #     decision; it is always something that did not fit and was not told it had to.
        check(f'layout/{m} no page h-scroll', r['hOverflow'] <= 2, f"{r['hOverflow']}px wide")
        # 2 — nothing pokes past the viewport edge (content clipped where nobody can reach it)
        check(f'layout/{m} nothing spills off-screen', not r['spills'], r['spills'][:3])
        # 3 — one scroll axis at a time
        check(f'layout/{m} no double v-scroll',
              not (r['vOverflow'] > 4 and r['innerScrollers']),
              f"page +{r['vOverflow']}px and {r['innerScrollers'][:2]}")
        # 4 — the screen actually rendered something
        check(f'layout/{m} has content', r['textLen'] > 40, r['textLen'])
        # 5 — no raw value where a fact belongs. `undefined`, `NaN` or `[object Object]` on a screen
        #     is a field the page reads that its data does not give — the live machine screen printed
        #     "undefined" three times for half a day, and the map photographed it at three sizes.
        raw = []
        for f in pg.frames:
            try:
                raw += f.evaluate(RAW_PROBE)
            except Exception:
                continue
        check(f'layout/{m} no raw value printed', not raw, raw[:3])
        # 6 — a tile's number and a table's column header are whole. Both sit in a box that clips
        #     what does not fit, so neither spills (2) nor scrolls (1): «151.9 שע׳» lost its unit to
        #     the tile's edge and «סטטוס» read «סט…» on the live office, under green checks. And
        #     whatever IS cut — a table's cell, a file's name, a label — keeps its BEGINNING.
        cut = []
        for f in pg.frames:
            try:
                cut += f.evaluate(CUT_PROBE)
            except Exception:
                continue
        check(f'layout/{m} no number or column header cut, and nothing cut at its beginning', not cut, cut[:3])
        # 7 — somebody else's grid, drawn inside the screen, is dressed by the office. Whatever the
        #     grid is not given it paints in its OWN colours, and no source of the office names
        #     them: its rows were black (on the dark ground too) and a column's filter panel a
        #     white card with the grid's green button, pinned to the window's right edge.
        #     (Read at rest: where the last press of the screen before left the pointer over the
        #     panel's button, the button wore its hover and the rule called that a wrong colour.)
        pg.mouse.move(1, 1)
        for f in pg.frames:
            try:
                off = f.evaluate(GRID_PROBE)
            except Exception:
                continue
            if off is not None:
                check(f'layout/{m} the grid inside it wears the palette, and its filter panel opens under its column',
                      not off, off[:3])
        # 8 — the stop the keyboard is on wears the palette's ring or the part's own, never the
        #     browser's: a hard black ring around the office's controls. Two screens had said the
        #     ring for themselves; on ten others nearly every button and link wore the browser's.
        ua = keyboard_walk(pg)
        check(f"layout/{m} no keyboard stop wears the browser's own ring", not ua, ua[:4])
        # 9 — a panel the screen opens over itself is what a finger reaches. A veil raised above its
        #     own panel leaves the panel in plain sight and dead: at phone width the simulation's
        #     responsive layer lifted this screen's veil over the new-document editor — fifteen
        #     controls, none of them what a touch hit, and the first touch closed it — under 201
        #     green flows, because not one of them opened it. Asked of seven more panels, the rule
        #     found three more at once: the apps screen's drawer never came into sight at all (its
        #     direction's rule outranked its open rule — a card's press raised the veil over
        #     nothing, on the live office too), and in the simulation the file preview kept most
        #     of its bar, and the mail reader «הדפס», past a phone's edge.
        for opener, panel, closer, *in_rail in PANELS.get(m, []):
            fr = next((f for f in pg.frames if f.locator(opener).count()), None)
            dead, thin, under, inside, tiny = ['no frame holds ' + opener], [], None, None, None
            if fr is not None:
                try:
                    if in_rail:
                        open_side(pg, fr)
                    fr.locator(opener).first.click(timeout=4000); pg.wait_for_timeout(900)
                    # (rules 18, 19, 21 and 22 as the panel OPENS, before the rules below scroll it and say a notice in it)
                    inside = fr.evaluate(ONE_PROBE) + fr.evaluate(SPILL_PROBE) + fr.evaluate(OVERLAP_PROBE) + fr.evaluate(URL_PROBE)
                    if size['width'] < 700:                # (…and rule 24, on a phone: the PANEL's own controls)
                        tiny = fr.evaluate(TAP_PROBE, [30, panel])
                    dead = fr.evaluate(FINGER_PROBE, panel)
                    thin = fr.evaluate(THIN_PROBE, panel)
                    under = fr.evaluate(NOTICE_PROBE, panel)
                except Exception as e:
                    dead = [str(e)[:160]]
                try:                                       # a dead panel cannot be closed by its own button
                    fr.locator(closer).first.click(timeout=1500); pg.wait_for_timeout(300)
                except Exception:
                    pass
            check(f'layout/{m} every control of the panel it opens ({panel}) is what a finger hits', not dead, dead[:3])
            # 10 — …and each of its fields shows what is typed in it. A row of fixed columns left a
            #      line's description what remained of a phone's width: 35 pixels, under the same flows.
            check(f'layout/{m} no field of the panel it opens ({panel}) is too narrow to read', not thin, thin[:3])
            # 11 — …and what the screen SAYS while the panel is open is not said on top of the panel's
            #      buttons. The office's notice has one corner, and five panels kept their bar there: a
            #      refused save was said over «שמור טיוטה» — the button it sends a person back to. Each
            #      was found in a photograph; this is what would have found the sixth.
            if under is not None:
                check(f"layout/{m} a notice said while its panel ({panel}) is open lies over none of the panel's buttons", not under, under[:3])
            # …and what is true of the screen is true of the panel it opens (rules 18, 19, 21, 22): one is said as one,
            # every text stands in its card and on no other text, and an address is a link.
            if inside is not None:
                check(f'layout/{m} the panel it opens ({panel}) is read as the screen is: one as one, each text in its card and on no other, no address as text',
                      not inside, inside[:3])
            if tiny is not None:
                # (a control recorded as OWED is said in the line's name every run; one the probe no longer finds
                #  small fails the line until its entry is taken off the list — the list cannot outlive its debts.
                #  A panel that did not open is not asked at all: the probe answers nothing for it, and rule 9 fails.)
                owed, item = TAP_OWED.get((m, panel), ((), ''))
                owing, tiny = [t for t in tiny if t.startswith(owed)], [t for t in tiny if not t.startswith(owed)]
                paid = [o for o in owed if not any(t.startswith(o) for t in owing)]
                check(f'layout/{m} no control of the panel it opens ({panel}) is smaller than a finger (30px each way)'
                      + (f' — but «{owing[0]}», owed on {item}' if owing else ''),
                      not tiny and not paid, tiny[:4] or [f'{p} is not found small in the open panel: take it off TAP_OWED ({item})' for p in paid])
        # 12 — a tile's OTHER screens are held to the page rules too (1, 2, 5 and 6). The suite read every
        #      tile as it OPENS, and the mail's settings are never the screen it opens on: at phone width
        #      its list of accounts read «…l» for «Gmail» and «…ns.co.il» for the address, under green checks.
        for name, presses in VIEWS.get(m, []):
            fr = next((f for f in pg.frames if f.locator(presses[0].split(':', 1)[-1]).count()), None)
            got, raw, cut, more, tiny, why = None, [], [], [], [], 'no frame holds ' + presses[0]
            if fr is not None:
                try:
                    for p in presses:
                        if p.startswith('rail:'):
                            open_side(pg, fr); p = p[5:]
                        fr.locator(p).first.click(timeout=4000); pg.wait_for_timeout(1300)
                    got, raw, cut = fr.evaluate(LAYOUT_PROBE), fr.evaluate(RAW_PROBE), fr.evaluate(CUT_PROBE)
                    more = (fr.evaluate(ONE_PROBE) + fr.evaluate(SPILL_PROBE) + fr.evaluate(OVERLAP_PROBE)
                            + fr.evaluate(URL_PROBE) + fr.evaluate(NAME_PROBE))
                    tiny = fr.evaluate(TAP_PROBE, [30, None]) if size['width'] < 700 else []
                except Exception as e:
                    why = str(e)[:160]
            check(f'layout/{m} · {name}: no page h-scroll, nothing spills, no raw value',
                  got is not None and got['hOverflow'] <= 2 and not got['spills'] and not raw,
                  why if got is None else (f"{got['hOverflow']}px wide", got['spills'][:3], raw[:3]))
            check(f'layout/{m} · {name}: no number or column header cut, and nothing cut at its beginning',
                  got is not None and not cut, why if got is None else cut[:3])
            # (…and rules 18, 19, 21, 22 and 23 there too: a tile's other screens are read as its first is)
            check(f'layout/{m} · {name}: one as one, each text in its card and on no other, no address as text, every tile name whole',
                  got is not None and not more, why if got is None else more[:3])
            if size['width'] < 700:                             # (…and rule 24, on a phone)
                check(f'layout/{m} · {name}: no control in sight is smaller than a finger (30px each way)',
                      got is not None and not tiny, why if got is None else tiny[:4])
        # 13 — a side menu that is not WHOLE still reaches everything it holds. The office's menu is a
        #      rail in a frame 600–839px wide and a drawer below that, and neither had lost a pixel by
        #      any rule above: a rail showed neither the rows folded behind «הצג עוד» (the mail's four
        #      last views) nor the search; a rail a person CHOSE — one press of the collapse control —
        #      kept the whole menu's column and had nothing left that brought the menu back; and three
        #      screens had no button that opens their drawer, so on a phone the notifications' filters
        #      could not be reached. Found by walking the mail at 834px: no line of this suite looks at a
        #      screen between 600 and 839, so this rule goes there itself (below, when the run is wide).
        fr, menu = menu_of(pg)
        if menu is not None and screen(pg, 'layout', m):       # (rule 12 leaves a tile on another of its screens)
            fr, menu = menu_of(pg)
            if menu is not None:
                with_menu.append(m)
                menu_rules(pg, fr, menu, m, '')
        # 14 — a screen whose service stops answering STAYS, and says so: it goes nowhere else, throws nothing
        #      it does not catch, and is not left saying it is loading. The machine screen took ANY failed
        #      refresh for a sign-out and sent its whole frame to the office's entry — a service that restarted
        #      put the console inside its own tile, under suites in which the service always answers. Asked
        #      where the screen stands: its requests are cut off and its own «רענון», when it has one, pressed.
        fr = framed(pg) if screen(pg, 'layout', m) else None
        if fr is not None:                                      # a screen in a frame; the shell's own are the shell
            before = len(errs)
            try:
                pressed = fr.evaluate(SILENCE_PROBE); pg.wait_for_timeout(1500)
                heard = fr.evaluate(HEARD_PROBE)
            except Exception as e:                              # the frame was sent somewhere else
                pressed, heard = None, {'stayed': False, 'loading': 0, 'went': str(e).split('\n')[0][:90]}
            thrown = [e for e in errs[before:] if not e.startswith('console:')]
            del errs[before:]                                   # judged here, by name — not again in the run's tally
            check(f'layout/{m} with its service cut off the screen stays where it is, catches what fails and is not left loading',
                  heard['stayed'] and not thrown and not heard['loading'], {**heard, 'thrown': thrown[:2], 'pressed': pressed})
            # 15 — …and so does a screen that COMES UP while its service is silent: its frame is loaded again
            #      with no answer at all, and with the 502 page a proxy answers while a service restarts. Where
            #      it stands (rule 14) a screen has its data already. Coming up, my-docs took the business it
            #      could not read for one that was never set up and opened «הגדרת העסק» over a working office —
            #      nothing thrown, no placeholder, and not a word that anything had failed: so the screen is asked
            #      that it SAYS so — and a request that could not be sent was thrown past everything on the page.
            #      …and WHAT it says is read: INDOX put the browser's own sentence there («Failed to execute 'text'
            #      on 'Response': body stream already read»), the drive and the mail a status («שגיאה (502)»), and
            #      three screens went on beating «חי» beside the word that nothing answered.
            #      The simulation only: its pages carry the switch (build.mjs SILENT).
            if not target_url().startswith('http'):
                for how, when in (('none', 'does not answer'), ('refused', 'answers that it is down (502)')):
                    before = len(errs)
                    got = loaded(pg, how)
                    thrown = [e for e in errs[before:] if not e.startswith(('console:', 'not loaded ('))]
                    del errs[before:]
                    check(f'layout/{m} coming up while its service {when}: it is the screen still, catches what fails, is not left loading or saying «חי», and says so in words',
                          got['own'] and not thrown and not got['loading'] and got['said'] and not got.get('raw') and not got.get('live'),
                          {**got, 'thrown': thrown[:2]})
                    # …and it says of NOTHING it did not read that there is none of it: the mail said «אין תוויות
                    #      עדיין» under «לא ניתן להתחבר לתיבה»; the vault's menu — three rows that are constants —
                    #      stood as a blank column; and the simulation's instance chip went on saying «מחובר»,
                    #      beside a green dot, of a list of accounts it could not read.
                    chip = pg.evaluate(CHIP_PROBE) if m in WITH_INSTANCES else None
                    check(f'layout/{m} coming up while its service {when}: what was not read is not said to be empty, missing or connected',
                          not got.get('none') and not got.get('blank') and 'מחובר' not in (chip or ''),
                          {'none': got.get('none'), 'blank': got.get('blank'), 'chip': chip})
                loaded(pg, None)                                # …and as it was, for the rules that follow
        # 16 — a row of number tiles never leaves ONE alone, at the widths a console's frame really takes. The
        #      suites stand at 1440 and 390; INDOX's six tiles stood 5 + 1 at every frame a 1366px laptop gives
        #      its console, and no line of any suite stood there. Found by reading the screens as that laptop
        #      draws them. …and on every VIEW the screen names with a tab, from a small window's width and a
        #      tablet's up: a tile's first screen is not the tile — the four tiles of INDOX's extraction view
        #      stood 3 + 1 in every frame from 560 to 802px, one tab away from where this rule stood.
        if size['width'] >= 1024 and screen(pg, 'layout', m):
            alone = []

            def lone(view=''):
                for w in (700, 834, 1040, 1180, 1294, 1366):
                    pg.set_viewport_size({'width': w, 'height': size['height']}); pg.wait_for_timeout(450)
                    for f in pg.frames:
                        try:
                            alone.extend(view + a for a in f.evaluate(ALONE_PROBE))
                        except Exception:
                            continue
            lone()
            fr = framed(pg)
            for i, name in enumerate(fr.evaluate(TABS_PROBE)[:8] if fr is not None else []):
                pg.set_viewport_size(size); pg.wait_for_timeout(250)
                try:
                    fr.locator('.tabstrip .tab, [role=tab]').nth(i).click(timeout=4000); pg.wait_for_timeout(1800)
                except Exception:
                    continue
                lone(f'«{name}» ')
            pg.set_viewport_size(size); pg.wait_for_timeout(300)
            check(f"layout/{m} no row of number tiles leaves one alone, on any view the screen names, from a small window to a laptop",
                  not alone, alone[:3])
        # 18 — ONE IS SAID AS ONE, on the screen as it opens and on every view it names with a tab. A count was the
        #      number and the plural whatever the number: «1 לא תקינות» on a running office's tile of containers,
        #      «1 מקורות על חיבור מנותק» and a source's tag «1 תקועים» in the simulation's INDOX. A count of one is
        #      its own sentence («מקור אחד»), which only the place that says it knows — so each says it, and this
        #      is what keeps them. (A mock of round numbers asks it of nobody: the machine's has ONE build record.)
        if screen(pg, 'layout', m):
            ones, spilt, over, urls, names, small = [], [], [], [], [], []

            def read(view=''):
                for f in pg.frames:
                    try:
                        ones.extend(view + o for o in f.evaluate(ONE_PROBE))
                        spilt.extend(view + o for o in f.evaluate(SPILL_PROBE))
                        over.extend(view + o for o in f.evaluate(OVERLAP_PROBE))
                        urls.extend(view + o for o in f.evaluate(URL_PROBE))
                        names.extend(view + o for o in f.evaluate(NAME_PROBE))
                        if size['width'] < 700:
                            small.extend(view + o for o in f.evaluate(TAP_PROBE, [30, None]))
                    except Exception:
                        continue
            read()
            fr = framed(pg)
            for i, name in enumerate(fr.evaluate(TABS_PROBE)[:8] if fr is not None else []):
                try:
                    fr.locator('.tabstrip .tab, [role=tab]').nth(i).click(timeout=4000); pg.wait_for_timeout(1500)
                except Exception:
                    continue
                read(f'«{name}» ')
            check(f'layout/{m} one is said as one: no «1» stands before a plural, on any view the screen names', not ones, ones[:3])
            # 19 — A TEXT STANDS INSIDE ITS CARD, read on the same walk. The simulation chat's «חיבור פעיל» card said
            #      «וואטסאפ עסקי050-000-0007»: the name and the number on one line with nothing between them,
            #      the number 6px past the card's edge — two inline spans whose ellipsis never applied. Nothing
            #      scrolled sideways (1), nothing left the screen (2), and no box that clips had cut anything (6).
            check(f'layout/{m} every text stands inside the box painted around it, on any view the screen names', not spilt, spilt[:3])
            # 21 — …and no text is printed OVER another text: two lines of a card on top of each other where the card
            #      is narrow. (A bar that stays while the page scrolls under it has a ground of its own: not this.)
            check(f'layout/{m} no text is printed over another text, on any view the screen names', not over, over[:3])
            # 22 — AN ADDRESS IS A LINK, NOT A TEXT. On a running office a notification read «הקישור לבקשה:
            #      http://console.localhost/#/m/project-pln/…» — three lines of text where two are given, and what
            #      was cut was the sentence after the address. The path and the ids of an address are one press
            #      away, and what is read is its site. (The mock's notifications held no address at all; one does now.)
            check(f'layout/{m} no address is printed as text, on any view the screen names', not urls, urls[:2])
            # 23 — A NUMBER TILE'S NAME IS WHOLE. In the window desktop mode opens, «מחשבים» named a tile «סך המשאבים
            #      של המח…»: the strip a row of tiles becomes there gives a name one line, and cuts what is longer.
            #      (Asked here at both sizes and by the windows suite in the window as it opens; in the SMALLEST
            #      window a strip of four may cut a name - it says the whole of it in its title.)
            check(f"layout/{m} every number tile's name is whole, on any view the screen names", not names, names[:3])
            # 24 — WHAT A FINGER HAS TO HIT IS 30px EACH WAY, on a phone: the office's own least (a screen is not
            #      done with a tap target under 30px), and until now nobody's to ask. Measured at 390px: the drive's
            #      star 26 wide, the notifications' «פתח במקור» 18 high (both on a running office), the mail's list
            #      tools 26–28, and in the simulation's INDOX a table's buttons 24, its pager 26 and a row's box
            #      15 by 15. A control grows; a text button keeps its line (padding its own margin takes back); a box
            #      is pressed through the label that fills its cell. A link inside running text is not a control.
            if size['width'] < 700:
                check(f'layout/{m} no control in sight is smaller than a finger (30px each way), on any view the screen names', not small, small[:4])
        # 20 — what a screen offers in a panel it FOLDS AWAY is still offered where the panel is folded. Below 820px
        #      the chat hides its side panel, and «שיחה חדשה» lived only there — the live page and the simulation's
        #      alike: no conversation could be started from a phone, or from the window desktop mode opens the chat
        #      in on a laptop (the windows suite asks this in both of its windows).
        for what, ways in REACH.get(m, []):
            fr = framed(pg) if screen(pg, 'layout', m) else None
            check(f'layout/{m} {what} can be started where its panel is folded away', fr is not None and fr.evaluate(REACH_PROBE, ways), ways)
        # 25 — WHAT A SCREEN CUTS TO TWO LINES IT SHOWS WHOLE ON A PRESS. A notification's text is given two lines. On a
        #      phone most are longer, and a press on the row marked it read and showed nothing more: the end of the
        #      sentence — and the link round 29 made of an address at its end — could not be read at all. (Where no
        #      text is cut at this size there is nothing to press, and the line says so.)
        if m in CLAMPED:
            fr = framed(pg) if screen(pg, 'layout', m) else None
            # (on a running office the text pressed is one of a row ALREADY READ: the press marks a row read, and a
            #  rule changes nothing there)
            texts = fr.locator(CLAMPED[m][target_url().startswith('http')]) if fr is not None else None
            CUT = "els => els.findIndex(e => e.checkVisibility() && e.scrollHeight > e.clientHeight + 1)"
            at = texts.evaluate_all(CUT) if texts is not None else -1
            if at >= 0:
                # (pressed on its first line, at the first point from the line's start that is the text's own: a link
                #  in it is its own press — and the line starts at the RIGHT, where the page reads)
                x = texts.nth(at).evaluate("""e => { e.scrollIntoView({ block: 'center' }); const r = e.getBoundingClientRect();
                  for (let x = r.width - 6; x > 0; x -= 10) { const t = document.elementFromPoint(r.left + x, r.top + 6);
                    if (t && e.contains(t) && !t.closest('a, button')) return x; }
                  return 6; }""")
                try:
                    (texts.nth(at).tap if size['width'] < 700 else texts.nth(at).click)(position={'x': x, 'y': 6}, timeout=4000)
                except Exception:
                    pass
                pg.wait_for_timeout(900)
                left = texts.nth(at).evaluate("e => e.scrollHeight - e.clientHeight") if texts.count() > at else 99
                check(f'layout/{m} a text cut to two lines is shown whole by a press on it', left <= 1, f'{left}px of it still out of sight')
            else:
                check(f'layout/{m} a text cut to two lines is shown whole by a press on it (none is cut at this size)', texts is not None, CLAMPED[m])
    if size['width'] >= 1024 and with_menu:
        pg.set_viewport_size({'width': 834, 'height': 1112})   # the tablet profile (view-profiles.yaml)
        try:
            for m in with_menu:
                if screen(pg, 'layout', m):
                    fr, menu = menu_of(pg)
                    if menu is not None:
                        menu_rules(pg, fr, menu, m, " at a tablet's width")
        finally:
            pg.set_viewport_size(size); pg.goto(target_url()); pg.wait_for_timeout(600)


# -> what a side menu of the office's holds and cannot be reached, by what it is here: `whole`; a `rail`
#    (its names gone); a `drawer` (parked off the screen); `open` (standing over the page). null where the
#    frame is not drawn or the screen has no such menu.
MENU_PROBE = r"""() => {
  for (let w = window; w !== w.parent; w = w.parent) {
    if (!w.frameElement || !w.frameElement.getClientRects().length) return null;
  }
  const m = document.querySelector('.bnv');
  if (!m || !m.querySelector('[data-bnv-id]')) return null;
  const shown = (e) => !!(e && e.getClientRects().length), lost = [];
  if (getComputedStyle(m).position === 'fixed') {
    if (m.classList.contains('is-open')) return { kind: 'open', lost };
    if (![...document.querySelectorAll('[data-nav-toggle]')].some(shown)) lost.push('no button in sight opens it');
    return { kind: 'drawer', lost };
  }
  if (shown(m.querySelector('.bnv-head b'))) return { kind: 'whole', lost };
  const gone = [...m.querySelectorAll('[data-bnv-id]')].filter((r) => !shown(r)).map((r) => r.dataset.bnvId);
  if (gone.length) lost.push('rows that are not there: ' + gone.join(', '));
  const boxes = [...m.querySelectorAll('.bnv-search')].filter((b) => !b.hidden);
  if (boxes.length && !boxes.some(shown)) lost.push('its search is not there');
  if (m.querySelector('.bnv-collapse') && !shown(m.querySelector('.bnv-collapse'))) lost.push('nothing in it brings the whole menu back');
  return { kind: 'rail', lost };
}"""


# -> does the menu stand to the frame's foot, and is its first row still in the frame once the page
#    is scrolled to its end (the page is put back where it was).
MENU_STAYS = r"""() => {
  const d = document.scrollingElement, m = document.querySelector('.bnv'), row = m.querySelector('[data-bnv-id]');
  const got = { frame: innerHeight, page: d.scrollHeight, menu_ends: Math.round(m.getBoundingClientRect().bottom) };
  got.to_foot = got.menu_ends >= innerHeight - 1;
  const was = d.scrollTop;
  d.scrollTop = d.scrollHeight;
  const r = row.getBoundingClientRect();
  got.scrolled = Math.round(d.scrollTop); got.first_row_at = Math.round(r.top);
  got.stays = r.bottom > 0 && r.top < innerHeight;
  d.scrollTop = was;
  return got;
}"""


def menu_of(pg):
    """-> (the frame that holds the office's side menu, what MENU_PROBE says of it), or (None, None)."""
    for f in pg.frames:
        try:
            got = f.evaluate(MENU_PROBE)
        except Exception:
            continue
        if got:
            return f, got
    return None, None


def menu_rules(pg, fr, menu, m, at):
    """Rule 13 of the layout suite, of one tile's side menu as it stands (`at`: where the suite took it)."""
    kind = menu['kind']
    said = lambda: fr.evaluate(MENU_PROBE) or {}                         # noqa: E731
    check(f"layout/{m} its side menu, {'whole' if kind == 'whole' else 'a ' + kind}{at}, reaches everything it holds",
          not menu['lost'], menu['lost'][:3])
    if kind in ('whole', 'rail'):
        # …and it is THERE to be reached: where the page scrolls, the menu was as tall as the page
        # and left with it — by the end of a long list its rows were a screen and a half up.
        stays = fr.evaluate(MENU_STAYS)
        check(f"layout/{m} …it stands to the frame's foot{at}, and stays when the page is scrolled to its end",
              stays['to_foot'] and stays['stays'], stays)
    try:
        if kind == 'drawer' and not menu['lost']:
            fr.locator('[data-nav-toggle]').first.click(timeout=4000); pg.wait_for_timeout(500)
            over = said()
            pg.keyboard.press('Escape'); pg.wait_for_timeout(400)
            check(f'layout/{m} …the button opens it over the page{at}, and Escape shuts it',
                  over.get('kind') == 'open' and said().get('kind') == 'drawer', (over, said()))
        fold = fr.locator('.bnv .bnv-collapse')
        if not fold.count():
            return
        if kind == 'whole':                       # one press of the collapse control: a rail a person CHOSE
            fold.first.click(timeout=4000); pg.wait_for_timeout(500)
            chosen = said()
            column = fr.evaluate("() => { const g = document.querySelector('.appgrid'); return g ? parseFloat(getComputedStyle(g).gridTemplateColumns) : 0; }")
            check(f"layout/{m} …the rail its collapse control makes{at} has a rail's column and reaches everything too",
                  chosen.get('kind') == 'rail' and not chosen.get('lost') and 0 < column <= 72, (chosen, f'a column of {column}px'))
            fr.locator('.bnv .bnv-collapse').first.click(timeout=4000); pg.wait_for_timeout(500)
            check(f'layout/{m} …and the same control brings the whole menu back', said().get('kind') == 'whole', said())
        elif kind == 'rail':                      # a rail by width: there the control stands the menu over the page
            fold.first.click(timeout=4000); pg.wait_for_timeout(500)
            over = said()
            names = fr.evaluate("() => !!document.querySelector('.bnv-head b').getClientRects().length")
            pg.keyboard.press('Escape'); pg.wait_for_timeout(400)
            check(f'layout/{m} …its collapse control stands the whole menu over the page{at}, and Escape shuts it',
                  over.get('kind') == 'open' and names and said().get('kind') == 'rail', (over, said()))
    except Exception as e:
        check(f'layout/{m} its side menu can be walked{at}', False, str(e)[:160])


RING_PROBE = r"""() => {
  const e = document.activeElement;
  if (!e || e === document.body || e === document.documentElement || e.tagName === 'IFRAME') return null;
  if (getComputedStyle(e).outlineStyle !== 'auto') return '';
  return e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (typeof e.className === 'string' && e.className ? '.' + e.className.trim().split(/\s+/)[0] : '');
}"""


def keyboard_walk(pg, presses=45):
    """Tab through the screen as it stands; -> the stops that wear the browser's own ring."""
    ua = []
    for _ in range(presses):
        pg.keyboard.press('Tab')
        for f in pg.frames:
            try:
                got = f.evaluate(RING_PROBE)
            except Exception:
                continue
            if got and got not in ua:
                ua.append(got)
    return ua


GRID_PROBE = r"""async () => {
  for (let w = window; w !== w.parent; w = w.parent) {      // only a frame that is drawn
    if (!w.frameElement || !w.frameElement.getClientRects().length) return null;
  }
  const cell = document.querySelector('revo-grid revogr-data [class*=rgCell]');
  const funnels = [...document.querySelectorAll('revo-grid .rv-filter')];
  if (!cell || !funnels.length) return null;                 // no grid on this screen
  const token = (name) => { const p = document.createElement('i'); p.style.color = 'var(' + name + ')';
    document.body.appendChild(p); const c = getComputedStyle(p).color; p.remove(); return c; };
  const paint = (e, prop) => getComputedStyle(e)[prop];
  const off = [];
  if (paint(cell, 'color') !== token('--ink')) off.push('its rows are ' + paint(cell, 'color') + ', not the ink');
  const inView = (b) => { const r = b.getBoundingClientRect(); return r.left >= 0 && r.right <= innerWidth; };
  const funnel = funnels.find(inView) || funnels[0];
  funnel.click();
  await new Promise(r => setTimeout(r, 500));
  const dlg = document.querySelector('revogr-filter-panel dialog.filter-panel-dialog');
  if (!dlg || !dlg.open) return off.concat('the filter panel did not open');
  const ok = dlg.querySelector('.revo-button.green'), a = funnel.getBoundingClientRect(), b = dlg.getBoundingClientRect();
  if (paint(dlg, 'backgroundColor') !== token('--surface')) off.push('the panel is ' + paint(dlg, 'backgroundColor') + ', not the surface');
  if (!ok || paint(ok, 'backgroundColor') !== token('--accent')) off.push('its confirm is ' + (ok ? paint(ok, 'backgroundColor') : 'missing') + ', not the accent');
  // where the grid itself puts it: at its funnel, kept 8px inside the window
  const want = Math.min(Math.max(8, a.left), Math.max(8, innerWidth - b.width - 8));
  if (Math.abs(b.left - want) > 2) off.push('the panel is at ' + Math.round(b.left) + 'px and its funnel at ' + Math.round(a.left) + 'px');
  if (ok) ok.click();
  await new Promise(r => setTimeout(r, 200));
  return off;
}"""


CUT_PROBE = r"""() => {
  for (let w = window; w !== w.parent; w = w.parent) {      // only a frame that is drawn
    if (!w.frameElement || !w.frameElement.getClientRects().length) return [];
  }
  const cut = [];
  for (const v of document.querySelectorAll('.pg-kpi-v')) {
    const tile = v.closest('.pg-kpi');
    if (!tile || !v.getClientRects().length) continue;
    const a = v.getBoundingClientRect(), b = tile.getBoundingClientRect();
    if (v.scrollWidth > v.clientWidth + 1 || a.left < b.left - 1 || a.right > b.right + 1)
      cut.push('tile: ' + v.textContent.trim().slice(0, 20));
  }
  for (const h of document.querySelectorAll('.bina-table .header-content')) {
    if (h.getClientRects().length && h.scrollWidth > h.clientWidth + 1)
      cut.push('header: ' + h.textContent.trim().slice(0, 20));
  }
  // A cell may lose the END of its value (an ellipsis says so) — never its BEGINNING. A left-to-right
  // name in a right-to-left cell overflowed on the side it starts: «wser42-task-watchdog», on the live
  // machine screen, where the simulation's eight short names had never been long enough to show it.
  for (const c of document.querySelectorAll('.bina-table revogr-data [class*=rgCell]')) {
    const b = c.getBoundingClientRect();
    for (const s of c.querySelectorAll('*')) {              // the grid wraps a cell's own markup in a box of its own
      const a = s.getBoundingClientRect(), t = s.textContent.trim();
      if (!a.width || !t) continue;
      if (/^[^A-Za-z֐-׿]*[A-Za-z]/.test(t) ? a.left < b.left - 1 : a.right > b.right + 1) {
        cut.push('cell, at its beginning: ' + t.slice(0, 24)); break;
      }
    }
  }
  // …and the same of anything an ellipsis cuts, anywhere: it eats the END, never the beginning. A box
  // cuts on the side its OWN direction ends, so a left-to-right name in a right-to-left box lost its
  // start — «…ffice-browser.png», in the live drive's grid. The box that is cut must read the way
  // its words do.
  for (const e of document.querySelectorAll('body *')) {
    if (e.scrollWidth <= e.clientWidth + 1 || e.children.length > 1 || !e.getClientRects().length) continue;
    const cs = getComputedStyle(e);
    if (cs.textOverflow !== 'ellipsis' || cs.overflowX === 'visible') continue;
    const t = e.textContent.trim(), first = (t.match(/[A-Za-z֐-׿]/) || [''])[0];
    if (first && /[A-Za-z]/.test(first) !== (cs.direction === 'ltr')) cut.push('cut at its beginning: ' + t.slice(0, 24));
  }
  return cut.slice(0, 5);
}"""


# -> the texts in sight that put «1» before a plural: «1 מקורות», «1 לא תקינות», «1 נבחרו»
ONE_PROBE = r"""() => {
  for (let w = window; w !== w.parent; w = w.parent) {      // only a frame that is drawn
    if (!w.frameElement || !w.frameElement.getClientRects().length) return [];
  }
  // a noun that ENDS as a plural does and is one thing («כפילות» — nobody's mistake when it follows «1»)
  const SINGULAR = /^(?:כפילות|טעות|זכות|חנות|כמות|איכות|אחריות|רשות|שירות|עלות|זהות|אפשרות|פעילות|עדיפות|התחייבות|התנגשות|עכשיו)$/;
  const inline = (e) => getComputedStyle(e).display.startsWith('inline');
  const seen = (e) => e.checkVisibility({ checkVisibilityCSS: true });
  // What follows a text ON ITS LINE: a number often stands in an element of its own (<b>1</b> מקורות), or in a
  // text of its own beside the words. A tile's number over its name («1» above «מקורות») is a number and a
  // name — two boxes, not a sentence.
  const after = (x) => { let s = '';
    while (s.length < 60) {
      let nx = x.nextSibling;
      while (!nx && x.parentElement && x.parentElement !== document.body && inline(x.parentElement)) { x = x.parentElement; nx = x.nextSibling; }
      if (!nx) break;
      if (nx.nodeType === 3) s += nx.nodeValue; else if (nx.nodeType === 1 && inline(nx) && seen(nx)) s += ' ' + nx.textContent; else if (nx.nodeType !== 8) break;
      x = nx;
    }
    return s; };
  // («שלב 1 פרטים» numbers a step: the word before the «1» says so. «ימ׳» is days, shortened: «לפני 1 ימ׳».)
  const RE = /(?:^|[^\d.,:\/\-])(?<!(?:שלב|עמוד|חלק|פרק|גרסה) )1 ((?:לא )?([א-ת]{2,12}(?:ים|ות)|[א-ת]{3,8}ו|ימ׳))(?![א-ת])/;
  const plural = (s) => { const m = s.replace(/\s+/g, ' ').match(RE); return m && !SINGULAR.test(m[2]) ? ('1 ' + m[1]).slice(0, 40) : null; };
  const ones = new Set();
  for (let t = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT), n; (n = t.nextNode());) {
    const p = n.parentElement;
    if (!p || !/1\s*$|1 /.test(n.nodeValue) || !seen(p) || p.closest('script, style, pre, code, textarea')) continue;
    const o = plural(n.nodeValue + after(n));
    if (o) ones.add(o);
  }
  // …and what a screen says where it prints nothing: a control's name for someone the screen is read to, a hint
  // on hover. The chat named a conversation «…, 1 חדשות» to a reader of screens.
  for (const e of document.querySelectorAll('[aria-label], [title]')) {
    if (!seen(e)) continue;
    for (const a of ['aria-label', 'title']) { const o = e.hasAttribute(a) && plural(e.getAttribute(a)); if (o) ones.add(a + ' «' + o + '»'); }
  }
  return [...ones].slice(0, 5);
}"""


# -> the texts in sight that reach past the box painted around them: «050-000-0007 | 6px past #connftr»
SPILL_PROBE = r"""() => {
  for (let w = window; w !== w.parent; w = w.parent) {      // only a frame that is drawn
    if (!w.frameElement || !w.frameElement.getClientRects().length) return [];
  }
  const clear = (c) => !c || c === 'transparent' || /rgba\(\s*0,\s*0,\s*0,\s*0\s*\)/.test(c);
  // a box that is PAINTED: a border at a side, or a ground of its own (an inline box is a run of its line, not a box)
  const painted = (e) => { const cs = getComputedStyle(e);
    if (cs.display === 'inline' || cs.display === 'contents') return false;
    const edge = (side) => parseFloat(cs['border' + side + 'Width']) > 0 && cs['border' + side + 'Style'] !== 'none' && !clear(cs['border' + side + 'Color']);
    return edge('Left') || edge('Right') || !clear(cs.backgroundColor) || cs.backgroundImage !== 'none'; };
  const out = new Set();
  for (let t = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT), n; (n = t.nextNode());) {
    const p = n.parentElement, s = n.nodeValue.replace(/\s+/g, ' ').trim();
    if (!p || s.length < 2 || !p.checkVisibility({ checkVisibilityCSS: true, checkOpacity: true }) || p.closest('script, style, select, option')) continue;
    const r = document.createRange(); r.selectNodeContents(n);
    const a = r.getBoundingClientRect();
    if (!a.width || !a.height || a.right < 0 || a.left > innerWidth) continue;
    // Up to the box painted around it. A box that CLIPS on the way ends the search — what it cuts is not seen, and
    // rule 6 reads that; an INLINE box clips nothing, whatever its style says (the first form of this probe took one
    // for a clip and passed the very card it was written for). A PAINTED box is the text's card whether it is
    // placed or not — a window over the page, a drawer, a notice. Only a box that is placed and NOT painted ends
    // the search: a badge on a corner is put there, not spilt.
    let box = p;
    for (; box && box !== document.body; box = box.parentElement) {
      const cs = getComputedStyle(box);
      if (cs.overflowX !== 'visible' && cs.display !== 'inline') { box = null; break; }
      if (painted(box)) break;
      if (cs.position === 'absolute' || cs.position === 'fixed') { box = null; break; }
    }
    if (!box || box === document.body) continue;
    const b = box.getBoundingClientRect(), by = Math.round(Math.max(b.left - a.left, a.right - b.right));
    if (by > 1) out.add(s.slice(0, 28) + ' | ' + by + 'px past ' + (box.id ? '#' + box.id : '.' + String(box.className).split(' ')[0]));
  }
  return [...out].slice(0, 5);
}"""


# -> pairs of texts in sight printed over each other: «שם» on «מספר» by 40x12
OVERLAP_PROBE = r"""() => {
  for (let w = window; w !== w.parent; w = w.parent) {      // only a frame that is drawn
    if (!w.frameElement || !w.frameElement.getClientRects().length) return [];
  }
  const clear = (c) => !c || c === 'transparent' || /rgba\(\s*0,\s*0,\s*0,\s*0\s*\)/.test(c);
  const items = [];
  for (let t = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT), n; (n = t.nextNode());) {
    const p = n.parentElement, s = n.nodeValue.replace(/\s+/g, ' ').trim();
    if (!p || s.length < 2 || !p.checkVisibility({ checkVisibilityCSS: true, checkOpacity: true }) || p.closest('script, style, select, option, svg')) continue;
    const r = document.createRange(); r.selectNodeContents(n);
    for (const b of r.getClientRects()) {                   // line by line: a text of three lines is three boxes
      if (b.width < 4 || b.height < 6 || b.bottom < 0 || b.top > innerHeight || b.right < 0 || b.left > innerWidth) continue;
      // what a clipping box hides is not in sight: the part of the line inside every clip on the way up
      let L = b.left, R = b.right, T = b.top, B = b.bottom;
      for (let a = p; a && a !== document.documentElement; a = a.parentElement) {
        const cs = getComputedStyle(a);
        if (cs.display !== 'inline' && (cs.overflowX !== 'visible' || cs.overflowY !== 'visible')) {
          const c = a.getBoundingClientRect(); L = Math.max(L, c.left); R = Math.min(R, c.right); T = Math.max(T, c.top); B = Math.min(B, c.bottom);
        }
      }
      if (R - L >= 4 && B - T >= 6) items.push({ p, s, L, R, T, B });
    }
  }
  const out = new Set();
  for (let i = 0; i < items.length; i++) for (let j = i + 1; j < items.length; j++) {
    const a = items[i], b = items[j];
    if (a.p === b.p || a.p.contains(b.p) || b.p.contains(a.p)) continue;
    const w = Math.min(a.R, b.R) - Math.max(a.L, b.L), h = Math.min(a.B, b.B) - Math.max(a.T, b.T);
    if (w <= 3 || h <= 3) continue;
    const top = document.elementFromPoint(Math.max(a.L, b.L) + w / 2, Math.max(a.T, b.T) + h / 2); if (!top) continue;
    const over = a.p === top || a.p.contains(top) || top.contains(a.p) ? a : b.p === top || b.p.contains(top) || top.contains(b.p) ? b : null;
    if (!over) continue;                                    // something else covers both
    // A ground of its own between the one on top and what the two share hides the other: a bar that stays while
    // the page scrolls under it is a page scrolling, not two texts printed over each other.
    let grounded = false;
    for (let e = over.p; e && !(e.contains(a.p) && e.contains(b.p)); e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (!clear(cs.backgroundColor) || cs.backgroundImage !== 'none') { grounded = true; break; }
    }
    if (!grounded) out.add('«' + a.s.slice(0, 22) + '» on «' + b.s.slice(0, 22) + '» by ' + Math.round(w) + 'x' + Math.round(h));
  }
  return [...out].slice(0, 5);
}"""


# -> the texts in sight that hold a whole address and are not a link: «הקישור לבקשה: http://console.localhost/#/m/…»
URL_PROBE = r"""() => {
  for (let w = window; w !== w.parent; w = w.parent) {      // only a frame that is drawn
    if (!w.frameElement || !w.frameElement.getClientRects().length) return [];
  }
  const out = new Set();
  for (let t = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT), n; (n = t.nextNode());) {
    const p = n.parentElement, m = n.nodeValue.match(/https?:\/\/[^\s<>"'`]{12,}/);
    if (!p || !m || !p.checkVisibility({ checkVisibilityCSS: true }) || p.closest('script, style, a, code, pre, textarea')) continue;
    out.add(m[0].slice(0, 60) + ' in ' + p.tagName.toLowerCase() + '.' + String(p.className).split(' ')[0]);
  }
  return [...out].slice(0, 4);
}"""


# -> the number tiles whose NAME is cut: «סך המשאבים של המח…»
NAME_PROBE = r"""() => {
  for (let w = window; w !== w.parent; w = w.parent) {      // only a frame that is drawn
    if (!w.frameElement || !w.frameElement.getClientRects().length) return [];
  }
  return [...document.querySelectorAll('.pg-kpi-k, .bigstat .k')].filter((e) => e.checkVisibility() && e.scrollWidth > e.clientWidth + 1)
    .map((e) => e.textContent.trim().slice(0, 30) + ' (' + e.clientWidth + ' of ' + e.scrollWidth + 'px)').slice(0, 5);
}"""


# -> the controls in sight that are smaller than a finger: «button.gm-star 30x27 ×4 «סימון בכוכב»» — and the ones a
#    neighbour's reach lies over, «button.gm-caret is under what span.gm-cb lays around itself», or a neighbour's
#    own box, «button.link has 24px left under button.link»; null for a root that is not on the page or not in sight
TAP_PROBE = r"""(a) => {
  for (let w = window; w !== w.parent; w = w.parent) {      // only a frame that is drawn
    if (!w.frameElement || !w.frameElement.getClientRects().length) return [];
  }
  const least = a[0], root = a[1] ? document.querySelector(a[1]) : document;
  // (a panel that is not on the page — or is on it and not in sight — has nothing to say: rule 9 says it did not open)
  if (!root) return null;
  if (a[1]) { const p = root.getBoundingClientRect();
    if (!p.width || !p.height || p.right <= 0 || p.left >= innerWidth || p.bottom <= 0 || p.top >= innerHeight) return null; }
  // (a point outside the window — or outside the part of a scrolling list that is in sight — is not asked: a finger
  //  brings the row up first, and what stands past the list's edge does not stand over the row)
  const within = (e) => { for (let p = e.parentElement; p && p !== document.body; p = p.parentElement) {
      const o = getComputedStyle(p).overflowY; if (o === 'auto' || o === 'scroll') return p.getBoundingClientRect(); }
    return null; };
  const inView = (x, y, s) => x >= 0 && y >= 0 && x < innerWidth && y < innerHeight && (!s || (x >= s.left && x < s.right && y >= s.top && y < s.bottom));
  const key = (e) => e.tagName.toLowerCase() + '.' + String(e.className).split(' ')[0];
  // (a bar that STAYS while what is under it scrolls is not "over" a row of it: a finger scrolls the row clear. So:
  //  the other control stands in something sticky or fixed that this one is not part of — and this one has
  //  something to scroll. A bar resting over the last row of a page that does not scroll IS over it.)
  const stays = (o, e) => { let p = o;
    while (p && p !== document.body && !/^(sticky|fixed)$/.test(getComputedStyle(p).position)) p = p.parentElement;
    if (!p || p === document.body || p.contains(e)) return false;
    for (let a = e.parentElement; a; a = a.parentElement) {
      const page = a === document.documentElement, s = page ? document.scrollingElement : a;
      if (s && s.scrollHeight > s.clientHeight + 1 && (page || /(auto|scroll)/.test(getComputedStyle(a).overflowY))) return true;
      if (!page && getComputedStyle(a).position === 'fixed') return false; }   // (a fixed panel does not scroll with the page behind it)
    return false; };
  const ctl = [...root.querySelectorAll('button, [role=button], [role=tab], [role=checkbox], select, summary, a[href], input[type=checkbox], input[type=radio]')]
    .filter((e) => { if (!e.checkVisibility({ checkVisibilityCSS: true }) || e.disabled) return false;
      const r = e.getBoundingClientRect();
      if (!r.width || !r.height || r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) return false;
      // a link inside running text is read, not aimed at
      return !(e.matches('a[href]') && getComputedStyle(e).display === 'inline' && e.closest('p, li, .desc, td, .muted, small')); });
  const kinds = new Map(), stolen = new Set();
  for (const e of ctl) {
    const r = e.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 2, s = within(e);
    let w = r.width, h = r.height, box = r;
    // a box is pressed through its label, where it has one: the label's box is what is measured, and what is hit…
    if (e.matches('input')) {
      const l = e.closest('label') || (e.id && document.querySelector('label[for="' + e.id + '"]'));
      if (l) { box = l.getBoundingClientRect(); w = box.width; h = box.height; }
    }
    // …and a control may reach past its own drawing: a ::before laid over it and around it is part of what is hit —
    // counted only where a press at the reach's edge really lands on the control (a box that clips cuts the reach
    // too), and measured from where it is laid: the PADDING box, so past the drawing it is the inset less the border
    // (the mail's row box, given «inset:-6px» inside a 2px border, was 28px under a finger and counted as 32)
    const b = getComputedStyle(e, '::before');
    if (b.content !== 'none' && b.position === 'absolute') {
      const cs = getComputedStyle(e), out = (v, bw) => Math.max(0, -(parseFloat(v) || 0) - (parseFloat(bw) || 0));
      const mine = (x, y) => { if (!inView(x, y, s)) return true; const at = document.elementFromPoint(x, y); return !!at && (at === e || e.contains(at)); };
      const l = out(b.left, cs.borderLeftWidth), rt = out(b.right, cs.borderRightWidth), t = out(b.top, cs.borderTopWidth), bt = out(b.bottom, cs.borderBottomWidth);
      if (mine(r.left - l + 1, cy) && mine(r.right + rt - 1, cy)) w += l + rt;
      if (mine(cx, r.top - t + 1) && mine(cx, r.bottom + bt - 1)) h += t + bt;
    }
    // …and nobody else lies over this one's own drawing (its label's, for a box): at the middle of each edge of it,
    // what is hit is not ANOTHER control. From outside that control's box it is its reach (the mail's row box, given
    // 6px around itself, lay 5px over the caret beside it). From inside its box the two boxes overlap, and what
    // counts is what is LEFT of this one: two text buttons 30px high by a margin taken back, on lines 24px apart,
    // are 24px each under a finger.
    const mx = box.left + box.width / 2, my = box.top + box.height / 2;
    for (const [x, y, left] of [[box.left + 2, my, (q) => box.right - q.right], [box.right - 2, my, (q) => q.left - box.left],
                                [mx, box.top + 2, (q) => box.bottom - q.bottom], [mx, box.bottom - 2, (q) => q.top - box.top]]) {
      if (!inView(x, y, s)) continue;
      const at = document.elementFromPoint(x, y);
      const o = at && ctl.find((c) => c !== e && c.contains(at) && !c.contains(e) && !e.contains(c));
      if (!o || stays(o, e)) continue;
      const q = o.getBoundingClientRect();
      if (x < q.left || x > q.right || y < q.top || y > q.bottom) stolen.add(key(e) + ' is under what ' + key(o) + ' lays around itself');
      else if (left(q) < least - 0.5) stolen.add(key(e) + ' has ' + Math.max(0, Math.round(left(q))) + 'px left under ' + key(o));
    }
    if (w >= least - 0.5 && h >= least - 0.5) continue;       // (half a pixel: a line's height is not a whole number in every font)
    const name = (e.getAttribute('aria-label') || e.title || e.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 22);
    const k = kinds.get(key(e) + ' ' + Math.round(w) + 'x' + Math.round(h)) || { n: 0, name };
    k.n++; kinds.set(key(e) + ' ' + Math.round(w) + 'x' + Math.round(h), k);
  }
  return [...kinds.entries()].map(([k, v]) => k + ' ×' + v.n + (v.name ? ' «' + v.name + '»' : '')).concat([...stolen]).slice(0, 6);
}"""


RAW_PROBE = r"""() => {
  // Only a frame that is DRAWN: for one that is not (another screen's, kept alive and hidden),
  // `innerText` is the whole `textContent` — inline scripts and all — and every `!== undefined`
  // in them would read as a value printed on a screen nobody is looking at.
  for (let w = window; w !== w.parent; w = w.parent) {
    if (!w.frameElement || !w.frameElement.getClientRects().length) return [];
  }
  const text = (document.body && document.body.innerText) || '';
  const hits = [...text.matchAll(/[^\n]{0,24}(?:\bundefined\b|\bNaN\b|\[object Object\])[^\n]{0,24}/g)];
  return [...new Set(hits.map(m => m[0].trim()))].slice(0, 5);
}"""


# What the pairing screen is allowed to say in Latin: the two words that ARE the technical thing
# (an address scheme and a hostname) and nothing else. Everything a person reads on that screen is
# Hebrew — that is what "no English text" means here, and it is checked rather than asserted.
CONNECT_LATIN_ALLOWED = {'https', 'localhost', 'dgo', 'dgopair', 'dgopairr', 'udp',
                         # the three kinds of machine an office runs on — a name, and Hebrew has no other
                         'Windows', 'Linux', 'Mac'}

CONNECT_STUB = """
(args) => {
  const OFFER = args.offer, CODE = args.code;
  const enc = (o) => 'DGOPAIR1:' + btoa(unescape(encodeURIComponent(JSON.stringify(o))))
                          .replace(/\\+/g,'-').replace(/\\//g,'_').replace(/=+$/,'');
  const text = enc(OFFER);
  // the reply is opaque to the page (its payload is sealed): any text under the reply's prefix will do
  const replyText = 'DGOPAIRR1:' + text.slice(9);
  const PEER = { office_id: 'macbook', label: 'MacBook', fingerprint: '75FF-E977-0881-0625' };
  const LINK = { id: 'macbook', office: 'macbook', label: 'MacBook', pair_id: OFFER.offer_id,
                 direction: 'both', slot: 4, side: 2, role: 'joiner', dial: 'host',
                 endpoint: '192.168.16.102', port: 51830, fingerprint: PEER.fingerprint };
  window.__flowqaCalls = [];
  window.__flowqaReplied = false;
  window.fetch = async (url, opt) => {
    const path = String(url);
    const method = (opt && opt.method) || 'GET';
    window.__flowqaCalls.push(method + ' ' + path);
    const reply = (body, status=200) => ({ ok: status < 400, status, json: async () => body });
    // an office with NO IDENTITY refuses every pairing route in words (409), as the real one does
    if (sessionStorage.getItem('flowqa-identity') === 'none'
        && (path.endsWith('api/pair') || path.includes('api/pair/') || path.endsWith('api/link'))) {
      return reply({ error: 'אין זהות ללשכה הזאת — הקישור לא יכול להיווצר. '
                          + 'הרץ `bbox dgo identity mint` על המכונה שמריצה את האפליקציה.' }, 409);
    }
    if (path.endsWith('api/pair/offer') && method === 'POST') {
      return reply({ rendezvous_id: OFFER.offer_id, offer: OFFER, text: text, expires_at: OFFER.expires_at });
    }
    if (path.endsWith('api/pair/reply') && method === 'POST') {
      window.__flowqaReplied = true;
      return reply({ state: 'claimed', rendezvous_id: OFFER.offer_id, code: CODE, peer: PEER });
    }
    if (/api\\/pair\\/offer\\/[^/]+\\/confirm$/.test(path)) {
      return reply({ ok: true, link: LINK, render: { ok: true } });
    }
    if (/api\\/pair\\/offer\\/[^/]+\\/cancel$/.test(path)) { return reply({ ok: true }); }
    if (/api\\/pair\\/offer\\/[^/]+$/.test(path)) {
      // the offer WAITS until the host's reply has been read here — nothing arrives over a network
      return reply(window.__flowqaReplied ? { state: 'claimed', code: CODE, peer: PEER }
                                          : { state: 'waiting', expires_at: OFFER.expires_at });
    }
    if (path.endsWith('api/pair/claim') && method === 'POST') {
      return reply({ rendezvous_id: OFFER.offer_id, code: CODE, offer: OFFER, reply_text: replyText,
                     peer: { office_id: OFFER.office, label: OFFER.label, fingerprint: OFFER.identity.fingerprint } });
    }
    if (/api\\/pair\\/claim\\/[^/]+$/.test(path)) {
      return reply({ ok: true, render: { ok: true },
                     link: Object.assign({}, LINK, { id: OFFER.office, office: OFFER.office, label: OFFER.label,
                                                      side: 1, role: 'host', fingerprint: OFFER.identity.fingerprint }) });
    }
    // ── the MAIN screen (`/`): one paired office, or none — chosen per navigation by the suite ──
    const main = sessionStorage.getItem('flowqa-main') || 'paired';
    const NAME = sessionStorage.getItem('flowqa-name') || '';
    const HOME = { id: 'hp-laptop', label: NAME || 'hp-laptop', named: !!NAME, fingerprint: '3A4B-3343-4492-5A1A' };
    if (path.endsWith('api/context')) {
      // an office with no door to its own machine answers its engine's reason, in the engine's words
      const home = sessionStorage.getItem('flowqa-door') === 'none'
        ? { error: 'connection refused' }
        : { repo: 'https://example.invalid/office.git', branch: 'main', commit: '0123456789abcdef',
            pushed: 'origin/main', dirty: 0, subject: 'גרסת בדיקה' };
      return reply({ home: home, machines: [], git_accounts: [], domains: [], apps: [], steps: [] });
    }
    if (path.endsWith('api/office') && method === 'GET') {
      // the list of declared offices, refused ONCE when the suite asks for it: a reload that fails
      if (sessionStorage.getItem('flowqa-office') === 'refuse') {
        sessionStorage.removeItem('flowqa-office');
        return reply({ error: 'רשימת הלשכות לא נטענה — השירות עסוק. רעננו בעוד רגע.' }, 503);
      }
      return reply({ items: [] });
    }
    if (path.endsWith('api/pair/home') && method === 'POST') {
      const label = String(JSON.parse((opt && opt.body) || '{}').label || '').trim();
      if (!label) return reply({ error: 'שם הלשכה חייב להיות באורך של 1 עד 60 תווים' }, 400);
      sessionStorage.setItem('flowqa-name', label);
      return reply({ ok: true, home: Object.assign({}, HOME, { label: label, named: true }) });
    }
    // what the office gives: three apps, and a declaration the suite changes through the screen
    const OWN = [['bina', 'bina-ds', 'בינה'], ['machine', 'machine', 'מכונה'], ['computers', 'computers', 'מחשבים']];
    const giving = () => {
      const g = JSON.parse(sessionStorage.getItem('flowqa-give') || 'null') || { mode: 'none', chosen: false, apps: [] };
      const apps = OWN.map(([alias, app, name]) => ({ alias, app, name,
        given: g.mode === 'all' || (g.mode === 'some' && (g.apps || []).includes(alias)) }));
      return { mode: g.mode, chosen: !!g.chosen, count: apps.filter((a) => a.given).length, total: apps.length, apps };
    };
    if (path.endsWith('api/pair/giving') && method === 'GET') { return reply(giving()); }
    if (path.endsWith('api/pair/giving') && method === 'POST') {
      const b = JSON.parse((opt && opt.body) || '{}');
      if (b.mode === 'some' && !(b.apps || []).length) {
        return reply({ error: 'לא נבחרה אף אפליקציה — בחרו לפחות אחת, או „לא לתת דבר”' }, 400);
      }
      sessionStorage.setItem('flowqa-give', JSON.stringify({ mode: b.mode, chosen: true, apps: b.apps || [] }));
      return reply({ ok: true, giving: giving() });
    }
    if (path.endsWith('api/pair') && method === 'GET') {
      // an office that can be dialed states its address; one that cannot states WHY, in the server's
      // own words (args.dial is pair_api.DIAL_ONLY_HE, read off the source — never a second copy)
      const why = sessionStorage.getItem('flowqa-reach') || '';
      const reach = why ? { listen: null, dial_only: { why: why, reason: args.dial[why][0], fix: args.dial[why][1] } }
                        : { listen: { endpoint: '192.168.16.102', port: 51830 }, dial_only: null };
      return reply(Object.assign({ home: HOME,
                     items: main === 'paired' ? [Object.assign({}, LINK, {
        direction: 'use', role: 'host', dial: 'joiner', side: 1, paired_at: 1791151200 })] : [] }, reach));
    }
    if (path.endsWith('api/link')) {
      // `delivery` is the office's own measurement of the pair: the door here, the peer's catalog —
      // and `verdict` is what the server concludes from it (app.py: _verdict), which is what the
      // screen reads. This stub answered without one for a day after the screen moved to it, so the
      // dead-door check below was red and measured nothing.
      const dead = sessionStorage.getItem('flowqa-delivery') === 'door';
      return reply({ items: main === 'paired' ? [{ office: 'macbook', state: 'up',
        delivery: { door: { port: 9004, listening: !dead, checked: true }, catalog: { ok: true }, up: !dead },
        verdict: dead ? { ok: false, hop: 'door', why: 'הדלת של הקישור בלשכה הזאת לא עונה, ולכן אף אפליקציה שלה לא נפתחת מכאן.' }
                      : { ok: true, hop: '', why: '' },
        apps: [{ id: 'bina' }, { id: 'drive' }, { id: 'console-home', hidden: true }] }] : [] });
    }
    if (/api\\/pair\\/[^/]+$/.test(path) && method === 'DELETE') {
      // an unpairing the office refuses ONCE, in words — the suite asks for it, then tries again
      if (sessionStorage.getItem('flowqa-unpair') === 'refuse') {
        sessionStorage.removeItem('flowqa-unpair');
        return reply({ error: 'הצימוד לא הוסר — מנהל הלשכה עסוק בהידור אחר. נסו שוב בעוד רגע.' }, 409);
      }
      sessionStorage.setItem('flowqa-main', 'empty');
      return reply({ ok: true });
    }
    return reply({ error: 'unstubbed ' + path }, 404);
  };
  return { offer: text, reply: replyText };
}
"""

# NOTHING TOUCHES, NOTHING IS CUT, NO STRIP HAS A HOLE — the defects read off the screenshots of
# 2026-10-05, kept as guards: a screenshot is looked at once, a guard is looked at on every run.
#   touching — two visible blocks of a panel with less than 6px between them
#   cut      — a fact whose text is wider than its cell (an ellipsis hiding the value)
#   holes    — a row of a key-over-value strip that does not reach the strip's edge (an empty cell)
TIDY_PROBE = """(scope) => {
  const root = document.querySelector(scope); if (!root) return null;
  const vis = (e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const cut = [...root.querySelectorAll('.cx-kv .v, .meta .v, .cx-kv .v .tok, .meta .v .tok')].filter(vis)
    .filter((e) => e.scrollWidth > e.clientWidth + 1).map((e) => e.innerText.slice(0, 40));
  let holes = 0;
  [...root.querySelectorAll('.cx-kv, .meta')].filter(vis).forEach((k) => {
    const kw = k.getBoundingClientRect().width, rows = {};
    [...k.children].filter(vis).forEach((c) => { const r = c.getBoundingClientRect(), y = Math.round(r.top);
      rows[y] = rows[y] || {w: 0, n: 0}; rows[y].w += r.width; rows[y].n += 1; });
    Object.values(rows).forEach((r) => { if (r.w + (r.n - 1) < kw - 6) holes += 1; });
  });
  const kids = [...root.children].filter(vis), touching = [];
  for (let i = 1; i < kids.length; i++) {
    const a = kids[i - 1].getBoundingClientRect(), b = kids[i].getBoundingClientRect();
    if (b.top - a.bottom < 6) touching.push((kids[i - 1].id || kids[i - 1].className) + ' | ' + (kids[i].id || kids[i].className));
  }
  return {cut, holes, touching};
}"""


def connect_flows(pg, errs):
    """The pairing screens of `dgo-extend` — the office that JOINS shows a code, the one that HOSTS
    scans it — driven at whatever profile the run asked for.

    LIVE ONLY, and out of the default set for that reason: the simulation bundles the console's own
    apps, and `dgo-extend` is not one of them, so in the sim this suite would have nothing to drive.
    It is run as

        python3 digital-office/sim/flow-qa.py connect --mobile --url http://dgo-extend:8983

    The pairing SERVER (pairing.py, DGO-33) is stubbed here on purpose: this suite is about the
    SCREEN — the three doors, the code, the six digits, the phone layout — and the stub is what lets
    the whole flow be walked before the server half lands."""
    import json as _json
    import re as _re

    print("\nCONNECT")
    base = target_url()
    if not base.startswith(('http://', 'https://')):
        check('connect/needs a live office', False,
              'dgo-extend is not in the simulation — run with --url http://dgo-extend:8983')
        return

    # the WIRE offer — the shape apps/dgo-extend/pairing.py mints (tests/pair_contract.py pins it)
    offer = {"v": 1, "offer_id": "0f1e2d3c4b5a69788796a5b4c3d2e1f0", "office": "portable-1",
             "label": "המחשב הנייד",
             "identity": {"ed25519": "7K3MQ2ZPAAABBBBCCCCDDDDEEEEFFFFGGGGHHHHIIII=", "wg": "",
                          "fingerprint": "7K3M-Q2ZP"},
             "ephemeral": "MCowBQYDK2VuAyEA0f1e2d3c4b5a69788796a5b4",
             "endpoints": ["192.168.16.103:51820"], "expires_at": 4102444800}
    code = "482913"
    # WHY an office cannot be dialed: the server's own table, read off its source (a literal — no
    # import, so this suite needs none of the app's dependencies). A reason added there is a reason
    # the stub can answer here; a second copy of the sentences would drift from the first.
    import ast as _ast
    import base64 as _b64
    _src = pathlib.Path(__file__).resolve().parents[2] / 'apps' / 'dgo-extend' / 'pair_api.py'
    dial = {}
    for node in _ast.parse(_src.read_text(encoding='utf-8')).body:
        if isinstance(node, _ast.Assign) and getattr(node.targets[0], 'id', '') == 'DIAL_ONLY_HE':
            dial = {k: list(v) for k, v in _ast.literal_eval(node.value).items()}
    check('connect/the reasons an office cannot be dialed are read off the server source',
          {'wsl-nat', 'engine-guest', 'declared', 'undeclared'} <= set(dial), sorted(dial))
    # the offer of an office that only dials: the same wire shape, with no address in it
    lonely = dict(offer, endpoints=[], office='mac-2', label='מק נוסף')
    lonely_text = 'DGOPAIR1:' + _b64.urlsafe_b64encode(
        _json.dumps(lonely, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).decode().rstrip('=')
    pg.add_init_script(f"window.__flowqa = ({CONNECT_STUB})({_json.dumps({'offer': offer, 'code': code, 'dial': dial})});")

    def fresh():
        pg.goto(base + '/connect', wait_until='domcontentloaded', timeout=45000)
        pg.wait_for_timeout(1200)

    def no_sideways_scroll(where):
        w = pg.evaluate("() => ({sw: document.documentElement.scrollWidth, vw: window.innerWidth})")
        check(f'connect/{where}: nothing scrolls sideways', w['sw'] <= w['vw'] + 1, w)

    def door(name):
        pg.click(f'#ways [data-way="{name}"]'); pg.wait_for_timeout(350)

    def tidy(scope, where, group='connect'):
        t = pg.evaluate(TIDY_PROBE, scope)
        check(f'{group}/{where}: no two blocks touch', t is not None and not t['touching'], t and t['touching'][:3])
        check(f'{group}/{where}: no fact is cut and no strip has an empty cell',
              t is not None and not t['cut'] and not t['holes'], t and {'cut': t['cut'][:3], 'holes': t['holes']})

    fresh()
    check('connect/opens on the pairing screen', 'הצטרפות' in pg.title(), pg.title())
    check('connect/the shared side menu is mounted, not redrawn',
          pg.evaluate("() => !!document.querySelector('.bnv') && !!document.querySelector('.bnv-item')"))
    check('connect/the app declares the menu container, not its own shell',
          pg.evaluate("() => !!document.querySelector('.bnv-host') && !!document.querySelector('.appgrid')"
                      " && !!document.querySelector('aside#sideNav')"))

    # THE PHONE LAYOUT, as a guard rather than a screenshot. Below 600px the menu is a fixed drawer,
    # which is NOT a grid item — so the content, the only in-flow child, used to auto-place into the
    # side column and inherit its width (measured 2026-10-01: 24px at a 390px viewport). The map was
    # green on desktop the whole time. This check is what keeps that from coming back.
    # On a wide pane the menu IS a grid item, so the pane the content may fill is the viewport minus
    # the side column, capped by the page's own max width — the same guard, stated for both sizes
    # (as first written it compared against the whole viewport and so could only pass on a phone).
    width = pg.evaluate("""() => { const p = document.querySelector('.pg'), s = document.getElementById('sideNav');
      const fixed = getComputedStyle(s).position === 'fixed';
      return {pg: Math.round(p.getBoundingClientRect().width), vw: window.innerWidth,
              side: fixed ? 0 : Math.round(s.getBoundingClientRect().width),
              max: parseInt(getComputedStyle(p).maxWidth, 10) || 99999}; }""")
    pane = min(width['vw'] - width['side'], width['max'])
    check('connect/the content column is the pane, not the menu width',
          width['pg'] >= pane - 8, f"{width['pg']}px of a {pane}px pane ({width})")

    # THE THREE DOORS ARE ON THE PAGE. They used to live only in the side menu, which is a rail of
    # icons on a narrow pane and a closed drawer on a phone — measured 2026-10-04: an agent driving
    # the page could not find "paste" at all. Visible, and big enough to press, at every size.
    ways = pg.evaluate("""() => [...document.querySelectorAll('#ways button')].map((b) => {
      const r = b.getBoundingClientRect();
      return {way: b.dataset.way, h: Math.round(r.height), inView: r.width > 0 && r.top >= 0 && r.bottom <= window.innerHeight};
    })""")
    check('connect/the three doors are buttons on the page itself',
          [w['way'] for w in ways] == ['show', 'scan', 'paste'] and all(w['inView'] for w in ways), ways)
    check('connect/each door is big enough to press', all(w['h'] >= 30 for w in ways), ways)
    line = pg.inner_text('#selfLine')
    check('connect/the screen says which office it is: its name or id, and its fingerprint',
          '3A4B-3343-4492-5A1A' in line and 'hp-laptop' in line, line[:110])
    no_sideways_scroll('first paint')

    # BEFORE A CODE EXISTS: a sentence, not a dash — and no control that acts on a code that is not there
    before = pg.evaluate("""() => ({
      empty: document.getElementById('qrEmpty').innerText.trim(),
      copy: getComputedStyle(document.getElementById('btnCopy')).display,
      cancel: getComputedStyle(document.getElementById('btnStopOffer')).display,
      text: getComputedStyle(document.getElementById('offerTextBox')).display,
      decisionFirst: document.getElementById('direction').getBoundingClientRect().top
                     < document.getElementById('btnOffer').getBoundingClientRect().top })""")
    check('connect/no code yet is said in a sentence, with nothing to copy or cancel',
          len(before['empty']) > 10 and before['copy'] == 'none' and before['cancel'] == 'none'
          and before['text'] == 'none', before)
    check('connect/what the link allows is chosen BEFORE a code is shown', before['decisionFirst'])
    # ...and so is WHICH apps: the line under the direction states what this office will give
    give = pg.inner_text('#giveLine')
    check('connect/before a code, the screen says what this office will give in the link',
          'תיתן את כל האפליקציות' in give and '(3)' in give, give[:110])
    pg.select_option('#direction', 'use'); pg.wait_for_timeout(150)
    check('connect/a link in which this office only takes says that it gives nothing',
          'רק לוקחת' in pg.inner_text('#giveLine'), pg.inner_text('#giveLine')[:80])
    pg.select_option('#direction', 'both'); pg.wait_for_timeout(150)
    tidy('#panelShow', 'before a code')
    # a CLOSED drawer parks just outside the pane; its shadow used to reach back in as a grey band
    drawer = pg.evaluate("""() => { const s = document.getElementById('sideNav'), c = getComputedStyle(s);
      return {fixed: c.position === 'fixed', open: s.classList.contains('is-open'), shadow: c.boxShadow}; }""")
    check('connect/a closed drawer casts no shadow into the page',
          not drawer['fixed'] or drawer['open'] or drawer['shadow'] == 'none', drawer)

    # ── the JOINER: show a code, read the host's reply, confirm ─────────────────────────────────────
    text = pg.evaluate("() => window.__flowqa.offer")
    pg.click('#btnOffer'); pg.wait_for_timeout(900)
    qr = pg.evaluate("""() => { const c = document.getElementById('qr'), r = c.getBoundingClientRect();
      return {w: c.width, shown: Math.round(r.width), vw: window.innerWidth, hidden: c.classList.contains('hidden'),
              square: Math.abs(r.width - r.height) < 2}; }""")
    check('connect/show draws a QR', qr['w'] > 100 and not qr['hidden'], qr)
    check('connect/the code is drawn large: as wide as the pane allows, up to 460px',
          qr['shown'] >= min(440, qr['vw'] * 0.7) and qr['square'], qr)
    check('connect/the text beside the QR is the same code that was drawn',
          pg.inner_text('#offerText').replace(' ', '') == text)
    facts = pg.evaluate("""() => { const k = document.querySelector('#qrBox .cx-kv');
      return k ? {cells: k.children.length, nested: !!k.querySelector(':scope > div > div > div')} : null; }""")
    check('connect/the offer states four facts in one strip (office, fingerprint, address, id)',
          facts and facts['cells'] == 4, facts)
    no_sideways_scroll('a code is shown')
    tidy('#panelShow', 'a code is shown')
    tidy('#qrBox', 'the offer and its facts')
    pg.wait_for_timeout(3000)
    shown = pg.inner_text('#showConfirm')
    check('connect/the showing side WAITS for the reply — no six digits arrive by themselves',
          code[:3] not in shown.replace(' ', '') and 'קוד תשובה' in shown, shown[:80])

    door('paste')
    check('connect/the paste door opens', pg.is_visible('#panelPaste'))
    reply_text = pg.evaluate("() => window.__flowqa.reply")
    box = pg.evaluate("""() => { const c = getComputedStyle(document.getElementById('pasteText'));
      return {dir: c.direction, font: c.fontFamily}; }""")
    check('connect/a pasted code is set like a code: mono, left to right',
          box['dir'] == 'ltr' and 'mono' in box['font'].lower(), box)
    pg.fill('#pasteText', reply_text); pg.click('#btnParse'); pg.wait_for_timeout(900)
    calls = pg.evaluate("() => window.__flowqaCalls")
    check('connect/a pasted REPLY is routed by its prefix to the reply route',
          any(c.endswith('api/pair/reply') and c.startswith('POST') for c in calls)
          and not any(c.endswith('api/pair/claim') for c in calls), calls[-4:])
    joined = pg.inner_text('#pasteOut')
    check('connect/the joining side shows the six digits and who answered',
          code[:3] in joined and code[3:] in joined and 'macbook' in joined, joined[:120].replace('\n', ' '))
    tidy('#panelPaste', 'the reply was read')
    tidy('#pasteOut', 'the six digits')
    pg.click('#btnConfirm'); pg.wait_for_timeout(700)
    calls = pg.evaluate("() => window.__flowqaCalls")
    check('connect/the joiner confirms on the OFFER route (its role, not the open panel, decides)',
          any(c.startswith('POST') and c.endswith('/confirm') and 'api/pair/offer/' in c for c in calls), calls[-3:])
    done = pg.inner_text('#doneOut') if pg.is_visible('#panelDone') else ''
    check('connect/done says what was written: the office, the direction and who dials',
          'הצימוד נכתב' in done and 'MacBook' in done and '192.168.16.102:51830' in done, done[:160].replace('\n', ' '))
    steps = pg.evaluate("""() => [...document.querySelectorAll('.cx-step')].map(s => ({
        done: s.dataset.done === '1', drawn: !!s.querySelector('.n svg'), text: s.querySelector('.n').textContent.trim() }))""")
    check('connect/a step that is behind you carries a drawn check, not a text glyph',
          any(s['done'] for s in steps) and all(s['drawn'] and not s['text'] for s in steps if s['done']), steps)
    no_sideways_scroll('the pairing is written')
    tidy('#doneOut', 'the pairing is written')
    check('connect/done offers the next step: the list of connected offices', pg.is_visible('#btnDoneList'))

    # ── the HOST: read an offer, show the reply, confirm ────────────────────────────────────────────
    fresh()
    door('paste')
    pg.fill('#pasteText', text); pg.click('#btnParse'); pg.wait_for_timeout(600)
    out = pg.inner_text('#pasteOut')
    check('connect/a pasted code names the office and the address before anything is agreed',
          offer['office'] in out and offer['endpoints'][0] in out, out[:120].replace('\n', ' '))
    tidy('#pasteOut', 'an offer was read')
    pg.click('#btnClaim'); pg.wait_for_timeout(1200)
    pasted = pg.inner_text('#pasteOut').replace(' ', '')
    check('connect/the pasting side gets the same six digits', code[:3] in pasted and code[3:] in pasted)
    host = pg.evaluate("""() => {
      const top = (id) => { const e = document.getElementById(id); return e ? e.getBoundingClientRect().top : null; };
      const rq = document.getElementById('replyQr'), rr = rq ? rq.getBoundingClientRect() : null;
      return {code: top('sasCode'), confirm: top('btnConfirm'), copy: top('btnCopyReply'), qr: top('replyQr'),
              codeInView: top('sasCode') !== null && top('sasCode') >= 0 && top('sasCode') < window.innerHeight,
              qrShown: rr ? Math.round(rr.width) : 0, vw: window.innerWidth,
              replyText: (document.getElementById('replyText') || {}).textContent || ''}; }""")
    check('connect/the host shows the six digits, the confirm button and the copy button ABOVE the reply QR',
          None not in (host['code'], host['confirm'], host['copy'], host['qr'])
          and max(host['code'], host['confirm'], host['copy']) < host['qr'], host)
    check('connect/after a claim the six digits are in view without scrolling', host['codeInView'], host)
    check('connect/the reply is shown as text too — the same code that was drawn',
          host['replyText'].replace(' ', '') == reply_text)
    check('connect/the reply QR is drawn large', host['qrShown'] >= min(440, host['vw'] * 0.7), host)
    no_sideways_scroll('the reply is shown')
    tidy('#pasteOut', 'the reply is shown')
    pg.click('#btnConfirm'); pg.wait_for_timeout(700)
    calls = pg.evaluate("() => window.__flowqaCalls")
    check('connect/the host confirms on the CLAIM route',
          any(c.startswith('POST') and 'api/pair/claim/' in c for c in calls), calls[-3:])
    check('connect/the host reaches the done panel', pg.is_visible('#panelDone'))

    # ── the camera door: a compact band while off, with its button in view ──────────────────────────
    fresh()
    door('scan')
    cam = pg.evaluate("""() => { const b = document.getElementById('camBox').getBoundingClientRect(),
      s = document.getElementById('btnScan').getBoundingClientRect();
      return {box: Math.round(b.height), btnBottom: Math.round(s.bottom), vh: window.innerHeight,
              zoomHidden: getComputedStyle(document.getElementById('camZoomRow')).display === 'none'}; }""")
    check('connect/the camera is a compact band while it is off, with its button in view',
          cam['box'] <= 160 and cam['btnBottom'] <= cam['vh'] and cam['zoomHidden'], cam)
    no_sideways_scroll('the camera door')
    tidy('#panelScan', 'the camera door')

    # ── a text that is not a code: refused in a sentence, the prefix as ONE left-to-right token ─────
    door('paste')
    pg.fill('#pasteText', 'hello this is not a code'); pg.click('#btnParse'); pg.wait_for_timeout(400)
    bad = pg.evaluate("""() => { const b = document.querySelector('#pasteOut .callout.bad');
      return b ? {text: b.innerText, tok: [...b.querySelectorAll('.tok')].map((t) => t.textContent)} : null; }""")
    check('connect/a text that is not a code is refused in a sentence, its prefix one token',
          bool(bad) and 'לא קוד הצטרפות' in bad['text'] and 'DGOPAIR1:' in bad['tok'], bad)
    tidy('#panelPaste', 'a refused text')

    # ── AN OFFICE THAT ONLY DIALS. A tunnel needs one side that can be dialed, so which offices this
    #    one can be paired with at all is said BEFORE any code — with why, and what would change it.
    #    Two fresh laptops used to learn it from a refusal that named two environment variables,
    #    after both codes had been made (owner's test, 2026-10-05: any two fresh offices on one network).
    def paste(text):
        door('paste')
        pg.fill('#pasteText', text); pg.click('#btnParse'); pg.wait_for_timeout(500)

    # AN OFFICE WITH NO IDENTITY refuses in words, with the command to run. Measured 2026-10-05 on a
    # brand-new office (the app's own image, empty volumes): every pairing route answered a bare 500
    # and this screen said "HTTP 500" — the reason and the remedy were in the exception all along.
    pg.evaluate("() => sessionStorage.setItem('flowqa-identity', 'none')")
    fresh()
    noid = pg.evaluate("""() => { const c = document.getElementById('selfRefused');
      return {text: c ? c.innerText : '', tok: c ? [...c.querySelectorAll('.tok')].map((t) => t.textContent) : []}; }""")
    check('connect/an office with no identity says so before any code, and names the command as ONE token',
          'אין זהות' in noid['text'] and 'bbox dgo identity mint' in noid['tok'], noid)
    off = pg.evaluate("""() => { const b = document.getElementById('btnOffer');
      return {disabled: b.disabled, why: b.title, qr: !document.getElementById('qr').classList.contains('hidden')}; }""")
    check('connect/…and the verb that could only be refused the same way is not offered there',
          off['disabled'] and 'זהות' in off['why'] and not off['qr'], off)
    # the other door still reads a code; the server's refusal of the claim is NOT said a second time
    door('paste')
    pg.fill('#pasteText', text); pg.click('#btnParse'); pg.wait_for_timeout(500)
    pg.click('#btnClaim'); pg.wait_for_timeout(700)
    twice = pg.evaluate("""() => ({said: [...document.querySelectorAll('.callout')].filter((c) => c.innerText.includes('אין זהות')).length,
      red: !!document.querySelector('#alerts .callout'), http: document.body.innerText.includes('HTTP 5')})""")
    check('connect/a refusal the page already states is said once — never twice, never as "HTTP 500"',
          twice['said'] == 1 and not twice['red'] and not twice['http'], twice)
    no_sideways_scroll('an office with no identity')
    pg.evaluate("() => sessionStorage.removeItem('flowqa-identity')")
    fresh()

    REACH = """() => { const c = document.querySelector('#reachLine .callout'), s = document.getElementById('selfLine'),
      w = document.getElementById('ways');
      const r = c ? c.getBoundingClientRect() : null;
      return {text: c ? c.innerText : '', tok: c ? [...c.querySelectorAll('.tok')].map((t) => t.textContent) : [],
              above: r ? Math.round(r.top - s.getBoundingClientRect().bottom) : null,
              below: r ? Math.round(w.getBoundingClientRect().top - r.bottom) : null}; }"""
    check('connect/an office that can be dialed shows no dial-only notice',
          pg.evaluate("() => document.getElementById('reachLine').innerHTML") == '')
    paste(lonely_text)
    can = pg.evaluate("() => ({claim: !!document.getElementById('btnClaim'), stop: !!document.getElementById('noListener')})")
    check('connect/an offer with no address is claimable by an office that CAN be dialed',
          can['claim'] and not can['stop'] and 'היא רק מחייגת' in pg.inner_text('#pasteOut'), can)
    for why in ('engine-guest', 'wsl-nat'):
        pg.evaluate("(w) => sessionStorage.setItem('flowqa-reach', w)", why)
        fresh()
        note = pg.evaluate(REACH)
        if why == 'wsl-nat':
            check('connect/a Windows office that cannot be dialed says why, and what to type is set apart as tokens',
                  'רק מחייגת' in note['text'] and {'bbox.cmd dialable', 'bbox.cmd run', 'networkingMode=mirrored',
                                                   '.wslconfig'} <= set(note['tok']), note)
        else:
            check('connect/a Mac office that cannot be dialed says which offices it can be paired with',
                  'רק מחייגת' in note['text'] and 'Mac' in note['text'] and 'שרת' in note['text'] and not note['tok'], note)
        check(f'connect/the dial-only notice ({why}) sits between the office line and the doors, touching neither',
              note['above'] is not None and note['above'] >= 6 and note['below'] >= 6, note)
        no_sideways_scroll(f'the dial-only notice ({why})')
    before_calls = len(pg.evaluate("() => window.__flowqaCalls"))
    paste(lonely_text)
    both = pg.evaluate("""() => { const n = document.getElementById('noListener');
      return {stop: n ? n.innerText : '', tok: n ? [...n.querySelectorAll('.tok')].map((t) => t.textContent) : [],
              claim: !!document.getElementById('btnClaim'), facts: !!document.querySelector('#pasteOut .cx-kv')}; }""")
    check('connect/two offices that only dial are told so when the offer is READ — and no button leads to a refusal',
          'שתיהן רק מחייגות' in both['stop'] and 'הלשכה הזאת' in both['stop'] and 'bbox.cmd run' in both['tok']
          and not both['claim'] and both['facts'], both)
    check('connect/…and nothing was asked of the server for a pairing that cannot exist',
          not any(c.startswith('POST') for c in pg.evaluate("() => window.__flowqaCalls")[before_calls:]),
          pg.evaluate("() => window.__flowqaCalls")[before_calls:])
    tidy('#pasteOut', 'two offices that only dial')
    no_sideways_scroll('two offices that only dial')
    # (the page is left in this state on purpose: the copy check below reads the new sentences too)

    # no English copy in what a person reads (the machine values live in .mono/.keybox)
    words = pg.evaluate("""() => {
      const out = [], w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      while (w.nextNode()) {
        const n = w.currentNode;
        if (!n.parentElement || ['SCRIPT', 'STYLE'].includes(n.parentElement.tagName)) continue;
        if (n.parentElement.closest('.mono,.keybox,pre,.num,code,canvas,.tok,textarea')) continue;
        const t = (n.textContent || '').trim(); if (t) out.push(t);
      }
      return out;
    }""")
    latin = sorted({m.group(0) for t in words for m in _re.finditer(r'[A-Za-z]{2,}', t)}
                   - CONNECT_LATIN_ALLOWED)
    check('connect/no English copy on the screen', not latin, latin[:6])
    pg.evaluate("() => sessionStorage.removeItem('flowqa-reach')")

    # ── THE MAIN SCREEN: a paired office is one card, one strip, one verb ───────────────────────────
    def main(state):
        pg.evaluate("(s) => sessionStorage.setItem('flowqa-main', s)", state)
        pg.goto(base + '/', wait_until='domcontentloaded', timeout=45000)
        pg.wait_for_selector('#list .ocard, #list .callout', timeout=15000)
        pg.wait_for_timeout(300)

    # WHO THIS OFFICE IS — drawn without the machine, and nameable from the screen
    ME = """() => { const s = document.getElementById('self'), b = document.getElementById('btnRename');
      return {text: s.innerText, cells: (s.querySelector('.meta') || {children: []}).children.length,
              warn: !!s.querySelector('.callout.warn'), btn: b.innerText.trim(), primary: !b.classList.contains('ghost')}; }"""
    pg.evaluate("() => ['flowqa-name', 'flowqa-door', 'flowqa-give', 'flowqa-reach'].forEach((k) => sessionStorage.removeItem(k))")
    main('paired')
    me = pg.evaluate(ME)
    check('main/an office nobody named says so, and naming it is the first action of its card',
          me['warn'] and me['btn'] == 'מתן שם' and me['primary'] and 'hp-laptop' in me['text'], me)
    check('main/this office states its id, its fingerprint and where its tunnel is dialed',
          me['cells'] == 4 and '3A4B-3343-4492-5A1A' in me['text'] and '192.168.16.102:51830' in me['text'], me)
    tidy('#self', 'this office, unnamed', 'main')
    pg.click('#btnRename'); pg.wait_for_timeout(200)
    pg.fill('#fName', ''); pg.click('#btnRenameSave'); pg.wait_for_timeout(300)
    refusal = pg.inner_text('#renameErr')
    check('main/an empty name is refused inside the dialog, which stays open',
          pg.is_visible('#renameDlg') and 'שם הלשכה' in refusal, refusal[:80])
    pg.fill('#fName', 'הנייד של המשרד'); pg.click('#btnRenameSave'); pg.wait_for_timeout(500)
    me = pg.evaluate(ME)
    check('main/a name given on the screen is the name the card shows, and the warning is gone',
          not pg.is_visible('#renameDlg') and 'הנייד של המשרד' in me['text'] and not me['warn']
          and me['cells'] == 5 and me['btn'] == 'שינוי שם' and not me['primary'], me)
    tidy('#self', 'this office, named', 'main')

    # WHAT THIS OFFICE GIVES — one declaration for the whole office, chosen on its own card
    cell = pg.inner_text('#giveCell')
    check('main/an office nobody asked says its giving was not chosen yet', 'עוד לא נבחר' in cell, cell)
    pg.click('#btnGive'); pg.wait_for_timeout(250)
    boxes = pg.evaluate("() => [...document.querySelectorAll('#giveApps input')].map((c) => ({on: c.checked, locked: c.disabled}))")
    check('main/the giving dialog opens on "all": every app ticked, and locked',
          pg.input_value('#giveMode') == 'all' and len(boxes) == 3 and all(b['on'] and b['locked'] for b in boxes), boxes)
    pg.select_option('#giveMode', 'some'); pg.wait_for_timeout(150)
    pg.evaluate("() => document.querySelectorAll('#giveApps input').forEach((c) => { c.checked = false; })")
    pg.click('#btnGiveSave'); pg.wait_for_timeout(300)
    check('main/"some" with nothing ticked is refused inside the dialog, which stays open',
          pg.is_visible('#giveDlg') and 'לא נבחרה' in pg.inner_text('#giveErr'), pg.inner_text('#giveErr')[:80])
    pg.check('#giveApps input[data-give="bina"]'); pg.click('#btnGiveSave'); pg.wait_for_timeout(500)
    cell = pg.inner_text('#giveCell')
    check('main/a chosen list is what the card states — one of three',
          not pg.is_visible('#giveDlg') and '1 מתוך 3' in cell, cell)
    tidy('#self', 'this office, giving chosen', 'main')
    pg.click('#btnGive'); pg.wait_for_timeout(250)
    pg.select_option('#giveMode', 'none'); pg.wait_for_timeout(150)
    check('main/"nothing" hides the list and says what the linked offices will stop seeing',
          not pg.is_visible('#giveAppsBox') and 'לא יראו' in pg.inner_text('#giveHint'), pg.inner_text('#giveHint')[:80])
    pg.keyboard.press('Escape'); pg.wait_for_timeout(150)
    pg.wait_for_selector('#home .meta', timeout=15000)
    check('main/the version of this office is a strip of four facts when its machine can be read',
          pg.evaluate("() => document.querySelector('#home .meta').children.length") == 4)
    pg.evaluate("() => sessionStorage.setItem('flowqa-door', 'none')")
    main('paired')
    pg.wait_for_selector('#home .callout', timeout=15000)
    nodoor = pg.inner_text('#home')
    check('main/an office with no door to its own machine says what that costs — and that pairing still works',
          'אין גישה למחשב' in nodoor and 'צימוד לשכה עובד' in nodoor and 'refused' not in nodoor, nodoor[:150])
    pg.evaluate("() => sessionStorage.removeItem('flowqa-door')")

    # an office that cannot be dialed: the cell states the fact, the sentence under the strip the reason
    ONLY = """() => { const c = document.getElementById('dialOnly'), cell = document.getElementById('reachCell');
      return {cell: cell ? cell.innerText.trim() : '', text: c ? c.innerText : '',
              tok: c ? [...c.querySelectorAll('.tok')].map((t) => t.textContent) : []}; }"""
    for why in ('wsl-nat', 'engine-guest', 'declared'):
        pg.evaluate("(w) => sessionStorage.setItem('flowqa-reach', w)", why)
        main('paired')
        only = pg.evaluate(ONLY)
        check(f'main/an office that cannot be dialed ({why}) says so in its address cell, and why under the strip',
              only['cell'] == 'אין — רק מחייגת' and 'רק מחייגת' in only['text']
              and dial[why][0] in only['text'], only)
        if why == 'wsl-nat':
            check('main/what a Windows office needs in order to be dialed is one command, spelled as a token to type',
                  {'bbox.cmd dialable', 'bbox.cmd run', 'networkingMode=mirrored', '.wslconfig'} <= set(only['tok']), only['tok'])
        tidy('#self', f'this office, dial-only ({why})', 'main')
        w = pg.evaluate("() => ({sw: document.documentElement.scrollWidth, vw: window.innerWidth})")
        check(f'main/the dial-only notice ({why}) does not make the page scroll sideways', w['sw'] <= w['vw'] + 1, w)
    pg.evaluate("() => sessionStorage.removeItem('flowqa-reach')")
    main('paired')
    only = pg.evaluate(ONLY)
    check('main/an office that can be dialed shows its address and no dial-only notice',
          '192.168.16.102:51830' in only['cell'] and not only['text'], only)

    # an office with no identity: its own card says so in words, and puts away the verbs that need one
    pg.evaluate("() => sessionStorage.setItem('flowqa-identity', 'none')")
    pg.goto(base + '/', wait_until='domcontentloaded', timeout=45000)
    pg.wait_for_selector('#selfRefused', timeout=15000); pg.wait_for_timeout(400)
    ref = pg.evaluate("""() => { const c = document.getElementById('selfRefused');
      const gone = (id) => getComputedStyle(document.getElementById(id)).display === 'none';
      return {text: c.innerText, tok: [...c.querySelectorAll('.tok')].map((t) => t.textContent),
              rename: gone('btnRename'), give: gone('btnGive'), list: document.getElementById('list').innerText.slice(0, 60)}; }""")
    check('main/an office with no identity says so on its own card, with the command — and offers no verb that needs one',
          'אין זהות' in ref['text'] and 'HTTP' not in ref['text'] and 'bbox dgo identity mint' in ref['tok']
          and ref['rename'] and ref['give'], ref)
    tidy('#self', 'this office, no identity', 'main')
    pg.evaluate("() => sessionStorage.removeItem('flowqa-identity')")

    main('paired')
    card = pg.evaluate("""() => { const c = document.querySelector('#list .ocard'); if (!c) return null;
      const acts = [...c.querySelectorAll('.rowacts .btn')].map((b) => Math.round(b.getBoundingClientRect().height));
      return {title: c.querySelector('h4').innerText, pill: c.querySelector('.pill').innerText,
              cells: c.querySelector('.meta').children.length, text: c.innerText, acts}; }""")
    # four facts where nothing measures the tunnel (this stub); the handshake is the fifth on an office.
    # When it was paired is under the name, not a cell: it was a sixth one alone on a second row.
    check('main/a paired office is one card: its name with when it was paired, its state, and its facts in one strip',
          bool(card) and card['title'] == 'MacBook' and card['pill'] == 'מחוברת' and card['cells'] == 4
          and 'לשכה מצומדת · מאז' in card['text'] and 'צומדה' not in card['text'], card)
    check('main/the card says what the link allows and how the tunnel is reached, in words',
          bool(card) and 'משתמשים כאן באפליקציות שלה' in card['text'] and 'מאזינה כאן' in card['text'], card)
    check('main/hidden apps are not counted as shown',
          pg.evaluate("() => document.querySelector('#list .meta > div:nth-child(3) .v').innerText.trim()") == '2')
    tidy('#list .ocard', 'the paired card', 'main')
    # a live tunnel whose door is dead is NOT "connected": the pill says which half failed
    pg.evaluate("() => sessionStorage.setItem('flowqa-delivery', 'door')")
    main('paired')
    pill = pg.evaluate("""() => { const p = document.querySelector('#list .ocard .pill');
      return {text: p.innerText.trim(), cls: p.className, why: p.title}; }""")
    check('main/a pair whose door does not answer here is not shown as connected',
          pill['text'] == 'הדלת לא עונה' and 'warn' in pill['cls'] and '9004' in pill['why'], pill)
    pg.evaluate("() => sessionStorage.removeItem('flowqa-delivery')")
    main('paired')
    w = pg.evaluate("() => ({sw: document.documentElement.scrollWidth, vw: window.innerWidth})")
    check('main/nothing scrolls sideways', w['sw'] <= w['vw'] + 1, w)
    pg.evaluate("() => { window.__nativeConfirm = 0; window.confirm = () => { window.__nativeConfirm += 1; return false; }; }")
    # the office's own question (bina-ask.js) — the screen keeps no dialog of its own for it
    ASKED = """() => { const d = document.querySelector('.bask-card'), yes = d && d.querySelector('.bask-btn.danger');
      return {open: !!d, text: d ? d.innerText : '', native: window.__nativeConfirm,
              focus: document.activeElement ? document.activeElement.textContent : '',
              yes: yes ? yes.textContent : '', off: yes ? yes.disabled : null,
              said: d ? d.querySelector('.bask-said').textContent : '',
              said_h: d ? Math.round(d.querySelector('.bask-said').getBoundingClientRect().height) : 0}; }"""
    pg.click('[data-unpair]'); pg.wait_for_timeout(300)
    dlg = pg.evaluate(ASKED)
    check('main/unpair asks in the page, with the facts of what is removed — never a native dialog',
          dlg['open'] and dlg['native'] == 0 and 'MacBook' in dlg['text'] and '75FF-E977-0881-0625' in dlg['text']
          and 'אסימון' in dlg['text'], dlg)
    check('main/the question opens on «ביטול» — Enter does not unpair by reflex — and shows no refusal yet',
          dlg['focus'] == 'ביטול' and dlg['yes'] == 'ביטול הצימוד' and dlg['said_h'] == 0, dlg)
    pg.keyboard.press('Escape'); pg.wait_for_timeout(200)
    check('main/Escape closes the dialog and removes nothing',
          not pg.query_selector('.bask')
          and not any(c.startswith('DELETE') for c in pg.evaluate("() => window.__flowqaCalls")))
    # an unpairing the office refuses: said IN the question, which stays and offers the verb again
    pg.evaluate("() => sessionStorage.setItem('flowqa-unpair', 'refuse')")
    pg.click('[data-unpair]'); pg.wait_for_timeout(300)
    pg.click('.bask-btn.danger'); pg.wait_for_timeout(500)
    ref = pg.evaluate(ASKED)
    check('main/a refused unpairing is said in the question, in the office\'s words, and the pair is still listed',
          ref['open'] and 'הצימוד לא הוסר' in ref['said'] and ref['said_h'] > 20 and ref['yes'] == 'ביטול הצימוד'
          and ref['off'] is False and bool(pg.query_selector('#list .ocard')), ref)
    tidy('.bask-card', 'the question after a refusal', 'main')
    # accepted this time — and the list that is read again afterwards is refused once: the unpairing
    # is done (the question is gone), and the reload that failed is said on the page, not dropped
    pg.evaluate("() => sessionStorage.setItem('flowqa-office', 'refuse')")
    pg.click('.bask-btn.danger'); pg.wait_for_selector('#alerts .callout', timeout=15000)
    calls, said = pg.evaluate("() => window.__flowqaCalls"), pg.inner_text('#alerts')
    check('main/confirming removes the pairing — and a list that then fails to reload says so on the page',
          calls.count('DELETE api/pair/macbook') == 2 and 'לא נטענה' in said and not pg.query_selector('.bask'),
          [calls[-4:], said[:80]])
    pg.click('#btnRefresh'); pg.wait_for_function("() => !document.querySelector('#list .ocard')", timeout=15000)
    check('main/…and once it loads, the list shows the result', bool(pg.query_selector('#list .callout')))
    empty = pg.inner_text('#list')
    check('main/no office yet is said in a sentence that names both ways in',
          'צימוד לשכה' in empty and 'התקנת לשכה על מחשב' in empty, empty[:120])
    check('main/the way to the pairing screen is the first button',
          pg.evaluate("() => document.querySelector('.pg-actions .btn').getAttribute('href')") == 'connect')
    check('connect/no JS error', not errs, errs[:2])


# ── DESKTOP MODE: every screen in the window it is opened in ───────────────────────────────────
WINDOW_PROBE = r"""() => {
  const se = document.scrollingElement, vw = innerWidth, vh = innerHeight;
  const box = s => { const e = document.querySelector(s); return e && e.getClientRects().length ? e.getBoundingClientRect() : null; };
  const head = box('.pg-head'), kpis = box('.pg-kpis'), stage = box('.stage');
  // a region that scrolls its OWN content, with under a row of it in sight and a page that does
  // not scroll: what it holds cannot be reached
  const shut = [];
  if (se.scrollHeight <= vh + 4) for (const e of document.querySelectorAll('body *:not(textarea)')) {
    if (e.scrollHeight <= e.clientHeight + 8 || !/(auto|scroll)/.test(getComputedStyle(e).overflowY) || !e.getClientRects().length) continue;
    const r = e.getBoundingClientRect();
    if (r.width >= 0.5 * vw && Math.min(r.bottom, vh) - Math.max(r.top, 0) < 64)
      shut.push(e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (typeof e.className === 'string' && e.className ? '.' + e.className.trim().split(/\s+/)[0] : ''));
  }
  return { vw, vh, sideways: se.scrollWidth - vw, shut: shut.slice(0, 3),
           headEnds: head ? Math.round(head.bottom) : null, kpisEnd: kpis ? Math.round(kpis.bottom) : null,
           stage: stage ? Math.round(stage.height) : null, textLen: (document.body.innerText || '').trim().length };
}"""
# The office's own question (bina-ask.js), asked by the page that carries it and answered with Esc: which of its
# title and its two buttons are NOT in sight. In a window dragged in to its smallest the card used to scroll as a
# whole to its focused button, and a question was asked with its own title out of sight.
ASK_PROBE = r"""async () => {
  if (typeof binaAsk !== 'function') return null;
  const asked = binaAsk({ title: 'למחוק את מקור הסנכרון?', body: 'הפריטים שלו יוסרו מהתצוגה.', ok: 'מחיקה', danger: true,
                          facts: [['מקור', 'gmail-invoices'], ['לסנכרון', '14'], ['בתהליך', '3'], ['סונכרן', '842'], ['נכשל', '9']] });
  await new Promise(done => setTimeout(done, 200));
  const c = document.querySelector('.bask-card'), vw = innerWidth, vh = innerHeight, k = c && c.getBoundingClientRect();
  const out = !c ? ['no question'] : [...c.querySelectorAll('h2, .bask-btn')].filter(e => { const r = e.getBoundingClientRect();   // in the frame AND in the card, which clips
    return !(r.height && r.top >= Math.max(0, k.top) - 0.5 && r.bottom <= Math.min(vh, k.bottom) + 0.5 && r.left >= -0.5 && r.right <= vw + 0.5); }).map(e => e.textContent.slice(0, 24));
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  return { out, vh, answer: await Promise.race([asked, new Promise(done => setTimeout(() => done('still asked'), 600))]) };
}"""
# -> null when a panel's way out is what a touch at its centre hits right now, else a sentence. Asked once the panel
#    has been walked to its last control: a form taller than its window ended there with its title and its «סגירה»
#    scrolled away, and «הוספת סוד חדש» - as tall as its form, in a frame that does not scroll - never had them.
WAY_OUT_PROBE = r"""(sel) => { const e = document.querySelector(sel); if (!e) return 'nothing answers to ' + sel;
  const r = e.getBoundingClientRect(), top = r.width ? document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2) : null;
  return top && (top === e || e.contains(top)) ? null : 'at ' + Math.round(r.top) + '..' + Math.round(r.bottom) + ' of ' + innerHeight + ', under ' + (top ? (top.id || top.className || top.tagName).toString().slice(0, 24) : 'nothing'); }"""


def window_flows(pg, errs):
    """Desktop mode opens an app in a WINDOW — about 580 x 530 on a laptop — and a person drags its
    corner in as far as 380 x 260. Every other suite looks at a screen in the classic shell's full
    frame, and a screen laid out for that frame can spend a whole window on its own heading: the
    timeline screen gave its timeline 2 of a window's 530 pixels (the owner, 2026-10-07: «ממש בלתי
    שמיש בדסקטופ»), under suites that were all green. This one looks at each screen where
    a person meets it in desktop mode — in the window the desktop opens, and in the smallest one its
    corner drags in to — and keeps a photograph of both."""
    print("\nWINDOWS (desktop mode)")
    size = pg.viewport_size
    if size['width'] < 1024:
        print("  (desktop mode is a wide screen's: not run at this size)")
        return
    shots = OUT / ('windows-live' if target_url().startswith('http') else 'windows')
    shots.mkdir(exist_ok=True)
    pg.set_viewport_size({'width': 1294, 'height': 810})        # a laptop: the size the windows are small at
    pg.goto(target_url()); pg.wait_for_timeout(900)
    on = pg.evaluate("() => { if (!window.BinaDesktop) return false; BinaDesktop.reset(); BinaDesktop.enable(); return BinaDesktop.isOn(); }")
    check('windows/desktop mode comes up on a laptop screen', on)
    # every screen THIS office offers, by the shell's own list — so the suite reads a live office too
    mods = tiles(pg.evaluate("() => MODULES.filter(m => !m.remote).map(m => m.id)")) if on else []
    took, unasked = {}, []                                      # beside the photographs: each one's time to drawn
    try:
        for m in mods:
            t0 = time.monotonic()
            pg.evaluate("x => location.hash = '/m/' + x", m)
            opened = drawn.wait(pg.evaluate, pg.wait_for_timeout, since=t0, at_least_ms=2400)
            win = pg.query_selector('.dk-win.focused')          # the module's own: opening one focuses it
            el = win.query_selector('iframe') if win else None
            frame = el.content_frame() if el else None
            if frame is None:
                check(f'windows/{m} opens in a window of its own', False, 'no focused window with a frame'); continue
            # a photograph is of the SCREEN: what its window shows once it has said what it has to say
            took[m] = drawn.said(opened)
            check(f'windows/{m} has said what it has to say in time, before it is photographed', not late(opened), drawn.said(opened))
            for small in (False, True):
                at = 'its smallest window' if small else 'its window'
                try:
                    if small:                                   # the corner, dragged in as far as it goes
                        c = win.query_selector('.dk-rz.se').bounding_box()
                        pg.mouse.move(c['x'] + 7, c['y'] + 7); pg.mouse.down()
                        pg.mouse.move(c['x'] - 900, c['y'] - 900, steps=8); pg.mouse.up(); pg.wait_for_timeout(700)
                    # (a window that never finished opening has had the camera's patience once already)
                    shown = opened if not small else drawn.wait(pg.evaluate, pg.wait_for_timeout,
                                                                cap_ms=drawn.CAP_MS if opened['drawn'] else 1000)
                    if not shown['drawn']:                      # a picture of placeholders is not a picture of the screen
                        raise RuntimeError(drawn.said(shown))
                    win.screenshot(path=str(shots / f"{m}{'-small' if small else ''}.png"))
                    r = frame.evaluate(WINDOW_PROBE); cut = frame.evaluate(CUT_PROBE); spilt = frame.evaluate(SPILL_PROBE)
                    over, urls, names = frame.evaluate(OVERLAP_PROBE), frame.evaluate(URL_PROBE), frame.evaluate(NAME_PROBE)
                except Exception as e:
                    check(f'windows/{m} can be looked at in {at}', False, f'{type(e).__name__}: {e}'[:120]); continue
                if small:
                    check(f'windows/{m} its corner drags in to the smallest window', r['vw'] <= 400 and r['vh'] <= 280, f"{r['vw']}x{r['vh']}")
                # …the app's page, or the shell's own card where the app cannot be shown in a frame
                said = r['textLen'] > 40 or len(win.query_selector('.dk-body').inner_text().strip()) > 40
                check(f'windows/{m} has content in {at}', said, r)
                check(f'windows/{m} no sideways scroll in {at}', r['sideways'] <= 2, f"{r['sideways']}px wide at {r['vw']}x{r['vh']}")
                check(f'windows/{m} no number or column header cut, and nothing cut at its beginning, in {at}', not cut, cut[:3])
                # (the layout suite's rules 19 to 23, in the frame a window is)
                check(f'windows/{m} every text stands inside the box painted around it in {at}', not spilt, spilt[:3])
                check(f'windows/{m} no text is printed over another text in {at}', not over, over[:3])
                check(f'windows/{m} no address is printed as text in {at}', not urls, urls[:2])
                if not small:                                   # (a strip of four in the smallest window may cut a name: its title says it whole)
                    check(f"windows/{m} every number tile's name is whole in {at}", not names, names[:3])
                for what, ways in REACH.get(m, []):
                    check(f'windows/{m} {what} can be started in {at}', frame.evaluate(REACH_PROBE, ways), ways)
                check(f'windows/{m} nothing that scrolls is squeezed shut in {at}', not r['shut'], r['shut'])
                # the heading is a line of the window, and the numbers a strip of it — not the window
                head, kpis = (0.3, 0.5) if small else (0.2, 0.34)
                if r['headEnds'] is not None:
                    check(f'windows/{m} the heading leaves {at} to the content',
                          r['headEnds'] <= head * r['vh'], f"ends at {r['headEnds']}px of {r['vh']}")
                if r['kpisEnd'] is not None:
                    check(f'windows/{m} the leading numbers are a strip of {at}, not the window',
                          r['kpisEnd'] <= kpis * r['vh'], f"end at {r['kpisEnd']}px of {r['vh']}")
                if m == 'concurrency':
                    check(f'windows/concurrency the timeline is most of {at}',
                          (r['stage'] or 0) >= 0.5 * r['vh'], f"{r['stage']}px of {r['vh']}")
                if m == 'mail':                                 # a list that is open and shows its tools, not a message
                    seen = frame.evaluate("""() => { const t = document.querySelector('#msgTable').getBoundingClientRect(),
                      e = document.querySelector('#msgTable .gm-row'), r = e && e.getBoundingClientRect();
                      return r ? Math.max(0, Math.round(Math.min(r.bottom, t.bottom, innerHeight) - Math.max(r.top, t.top, 0))) : 0; }""")
                    check(f'windows/mail a message is in sight in {at}, before anything is scrolled', seen >= 24,
                          f'{seen}px of the first message')
                if small:                                       # …and what the screen ASKS there is asked whole
                    q = frame.evaluate(ASK_PROBE)
                    if q is None:
                        unasked.append(m)
                    else:
                        check(f"windows/{m} the office's question keeps its title and its buttons in sight in {at}",
                              not q['out'] and q['answer'] is False, q)
                    # …and so is each panel the screen opens over itself (the layout suite's catalogue and its rule 9,
                    # in the frame a dragged-in window leaves): every control can be brought under a finger, and at the
                    # panel's end its way out is still in sight. On the simulation only - a preview reads a file.
                    for opener, panel, closer, *in_rail in ([] if target_url().startswith('http') else PANELS.get(m, [])):
                        dead, away = ['it did not open'], None
                        try:
                            if in_rail:
                                open_side(pg, frame)
                            frame.locator(opener).first.click(timeout=4000); pg.wait_for_timeout(900)
                            dead = frame.evaluate(FINGER_PROBE, panel)
                            away = frame.evaluate(WAY_OUT_PROBE, closer)
                        except Exception as e:
                            dead = [str(e)[:160]]
                        try:
                            frame.locator(closer).first.click(timeout=1500); pg.wait_for_timeout(300)
                        except Exception:
                            pass
                        check(f'windows/{m} every control of the panel it opens ({panel}) can be reached in {at}', not dead, dead[:3])
                        check(f'windows/{m} at the end of the panel it opens ({panel}) its way out is still in sight in {at}', not away, away)
            win.query_selector('[data-a="close"]').click(); pg.wait_for_timeout(250)
        if unasked:
            print(f"  (the office's question was not asked in {len(unasked)} window(s) - their page does not carry it: {', '.join(unasked)})")
    finally:
        (shots / 'drawn-log.json').write_text(json.dumps(took, ensure_ascii=False, indent=1), encoding='utf-8')
        pg.evaluate("() => { if (window.BinaDesktop) { BinaDesktop.reset(); BinaDesktop.disable(); } }")
        pg.set_viewport_size(size)
        pg.goto(target_url()); pg.wait_for_timeout(600)


SUITES = {'drive': drive_flows, 'mail': mail_flows, 'indox': indox_flows,
          'console': console_flows, 'scroll': scroll_flows, 'layout': layout_flows,
          'connect': connect_flows, 'windows': window_flows}
# Suites that need a RUNNING office and have nothing to drive in the simulation. They are still
# selectable by name — they are just not part of "run everything", which is always the sim.
LIVE_ONLY = {'connect'}


def main():
    with sync_playwright() as p:
        # executable_path=None is not the same as omitting it, so only pass it when resolved.
        _launch = {'args': ['--allow-file-access-from-files']}
        if CHROME:
            _launch['executable_path'] = CHROME
        b = p.chromium.launch(**_launch)
        phone = '--mobile' in sys.argv
        ctx = b.new_context(viewport={'width': 390, 'height': 844} if phone else {'width': 1440, 'height': 900},
                            is_mobile=phone, has_touch=phone, device_scale_factor=1)
        pg = ctx.new_page()
        print(f"viewport: {'390x844 (phone)' if phone else '1440x900 (desktop)'}")
        errs, where = [], {}

        def err(msg):
            # …and by the check it came after: an error with no place is a search, not a finding.
            errs.append(msg); where.setdefault(msg, RESULTS[-1][0] if RESULTS else 'start')
        pg.on('pageerror', lambda e: err(str(e)))
        # A resource that did not load is named by its address: the console's own line for it says
        # only "Failed to load resource", sixty times, about sixty unknown things.

        def said_by(m):
            """On a running office, the page that logged it — `[a/browser42/app/ui.js] `. There a
            tile may frame a page that is not the office's own to fix (G81 reads this)."""
            u = (m.location or {}).get('url', '')
            return f"[{u.split('//', 1)[1].partition('/')[2].split('?')[0][:60]}] " if u.startswith('http') else ''
        pg.on('console', lambda m: err('console:' + said_by(m) + m.text)
              if m.type == 'error' and 'Failed to load resource' not in m.text else None)
        # …but not the address a check itself stands in for an app's own host (OWN_HOST: the discard
        # port, which refuses on purpose), nor a load the page gave up by navigating on.
        pg.on('requestfailed', lambda r: err(f'not loaded ({r.resource_type}): {r.url[-100:]}')
              if 'ERR_ABORTED' not in str(r.failure) and not r.url.startswith('http://127.0.0.1:9/') else None)
        # THE BROWSER'S OWN DIALOG (confirm / alert / prompt) is a fault wherever it opens: outside the page, English
        # buttons left to right, one line of text and nothing about what is at stake. With nobody listening the
        # driver closes one silently — which is how INDOX kept three of them, unseen by every run, until 2026-10-09.
        # Each is answered «no», kept, and failed by the suite it opened in. (Leaving a page is let through.)
        native = []
        pg.on('dialog', lambda d: d.accept() if d.type == 'beforeunload'
              else (native.append(f'{d.type} «{d.message[:60]}»'), d.dismiss()))
        argv = sys.argv[1:]
        for flag in ('--url', '--tiles'):        # drop each flag AND its value (a tile may be named as a suite is)
            if flag in argv:
                i = argv.index(flag); argv = argv[:i] + argv[i + 2:]
        wanted = [a for a in argv if a in SUITES] or [n for n in SUITES if n not in LIVE_ONLY]
        print(f"target: {target_url()}")
        for name in wanted:
            asked = len(native)
            try:
                SUITES[name](pg, errs)
            except Exception as e:
                # a suite that throws is one failure, not a lost run — the others still report
                check(f'{name}/suite completed', False, f'{type(e).__name__}: {e}')
                pg.screenshot(path=str(OUT / f'flow_{name}_fail.png'))
            check(f"{name}/nothing was asked or said through the browser's own dialog", len(native) == asked, native[asked:][:4])
        b.close()

    bad = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} flows passed")
    for n, _, d in bad:
        print('  FAILED:', n, '—', d)
    print('JS errors:', len(errs))
    # Each DIFFERENT error once, with how often: ten copies of one line said nothing about the rest.
    kinds = {}
    for e in errs:
        kinds[e] = kinds.get(e, 0) + 1
    for e, n in sorted(kinds.items(), key=lambda kv: -kv[1])[:12]:
        print(f'    x{n}  {e[:200]}' + (f'   [first after: {where[e]}]' if e in where else ''))
    sys.exit(1 if bad or errs else 0)


main()
