"""flow_qa.py — the interactions of «קבצים», done the way a person does them, on the mock.

    python apps/drive/tests/ui/dev_server.py 8971 &
    python apps/drive/tests/ui/flow_qa.py [--url http://127.0.0.1:8971/] [suites…]
    python apps/drive/tests/ui/flow_qa.py --size 412x760 --forced-dark     # one size: the suites that fit it
    python apps/drive/tests/ui/flow_qa.py --bar [--shots DIR]               # the release bar, every size below

--size WxH runs the suites a box of that size is used with (a phone: touch + recorder; a tablet:
touch + recorder + mouse; a desk: mouse + recorder; a box under 300 tall or under 560×440: the widget
suite) in a window of exactly that size. --forced-dark is the owner's phone (Samsung Internet): the
dark ground with Chrome's forced dark on top. --bar runs the release bar in one go: 412×760 forced
dark, 768×1024, 1280×900 and the 380×260 widget. At every state a flow reaches, the page is also
measured for layout glitches with layout_qa.py's probe (overflow, offscreen, overlap, cut labels,
small targets, broken pictures, bidi…): a glitch is a failure like a wrong route.

Every flow is a real input (a click, a double-click, a right-click, a hover, a tap, a long press, a
key) and every check reads the effect: the route, the selection, what is on the screen. The model
under test (views.js): a click or a tap OPENS; the circle, ctrl / shift or a long press SELECTS;
once something is selected a click adds or removes; right-click is the item's own menu and leaves
the selection as it was; the second click of a double-click is dropped. Exit 1 on any failure or
any error the page throws.
"""
import argparse
import os
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from layout_qa import PROBE  # noqa: E402 — the same glitch probe the layout walk uses

FAILS = []
# set by --size / --forced-dark / --dark / --shots (main); None = each suite's own size
OPT = {"size": None, "scheme": "light", "shots": "", "tag": ""}
BAR = [((412, 760), "forced", ["touch", "recorder"]),          # the owner's phone, Samsung Internet's forced dark
       ((768, 1024), "light", ["touch", "recorder", "mouse"]),  # a tablet, by finger and by pointer
       ((1280, 900), "light", ["mouse", "recorder"]),           # the desk
       ((380, 260), "light", ["widget"])]                       # the console's smallest window


def new_ctx(b, w, h, fixed=False, **kw):
    """A context at the suite's own size, or at --size when one is given (unless the size is part of what is
    tested: fixed=True); the colour ground from the options."""
    if OPT["size"] and not fixed:
        w, h = OPT["size"]
    print(f"  ({w}×{h}, {OPT['scheme']}{', forced dark' if OPT.get('forced') else ''})")
    return b.new_context(viewport={"width": w, "height": h}, locale="he-IL", color_scheme=OPT["scheme"], **kw)


def press(pg, loc):
    """A finger where the window has one, a pointer where it has not."""
    if pg.evaluate("() => matchMedia('(pointer: coarse)').matches"):
        loc.tap()
    else:
        loc.click()


def glitch(pg, label):
    """Measure the state a flow reached for layout glitches (layout_qa's probe) and keep its picture."""
    pg.wait_for_timeout(150)
    found = pg.evaluate(PROBE)
    vp = pg.viewport_size
    check(f"no layout glitch: {label} ({vp['width']}×{vp['height']})", not found, found)
    if OPT["shots"]:
        os.makedirs(OPT["shots"], exist_ok=True)
        safe = "".join(c if c.isalnum() else "-" for c in label.encode("ascii", "ignore").decode() or "state").strip("-")[:40]
        n = len([f for f in os.listdir(OPT["shots"]) if f.endswith(".png")])
        pg.screenshot(path=os.path.join(OPT["shots"], f"{OPT['tag']}{vp['width']}x{vp['height']}-{n:03d}-{safe}.png"))


def check(name, ok, got=""):
    print(("  ok   " if ok else "  FAIL ") + name + ("" if ok else f"   (got: {got})"))
    if not ok:
        FAILS.append(name)


def ready(pg):
    pg.wait_for_function("(() => { const r = F.state.route, l = F.state.list;"
                         " return l.key === [r.view, r.id || '', r.q || ''].join('\\u241f') && !l.loading; })()", timeout=15000)
    pg.wait_for_timeout(200)


def go(pg, route):
    pg.evaluate("(r) => { F.set({menu:null, sel:[], details:false, drawer:false}); F.viewer.close(); F.go(r); }", route)
    ready(pg)


def route(pg):
    return pg.evaluate("() => F.state.route.view + ':' + (F.state.route.id || '')")


def sel(pg):
    return pg.evaluate("() => F.state.sel.length")


def row_of(pg, name):
    return pg.locator(".lr", has=pg.locator(".fname", has_text=name)).first


def folder_id(pg, name):
    return pg.evaluate("(n) => F.state.folders.find((f) => f.name === n).id", name)


def mouse(b, url):
    print("mouse")
    ctx = new_ctx(b, 1280, 800)
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)[:200]))
    pg.goto(url, wait_until="networkidle")
    pg.wait_for_function("window.F && F.state && F.state.folders.length > 0", timeout=15000)
    pg.evaluate("() => { F.localSet('layout', 'list'); F.set({ layout: 'list' }); }")

    go(pg, {"view": "folder", "id": ""})
    docs = folder_id(pg, "מסמכים")
    row_of(pg, "מסמכים").click()
    ready(pg)
    check("a click on a folder opens it", route(pg) == "folder:" + docs, route(pg))
    check("…and selects nothing", sel(pg) == 0, sel(pg))

    go(pg, {"view": "folder", "id": ""})
    row_of(pg, "מסמכים").dblclick()
    pg.wait_for_timeout(700)
    ready(pg)
    check("a double-click opens one level, not two", route(pg) == "folder:" + docs, route(pg))
    check("…and its second click selects nothing in the folder it opened", sel(pg) == 0, sel(pg))

    go(pg, {"view": "folder", "id": ""})
    r1 = row_of(pg, "מסמכים")
    r1.hover()
    op = r1.locator(".check").evaluate("(el) => getComputedStyle(el).opacity")
    check("a pointer over a row shows its circle", op == "1", op)
    r1.locator(".check").click()
    check("the circle selects", sel(pg) == 1, sel(pg))
    check("…without opening", route(pg) == "folder:", route(pg))
    check("…and the selection bar appears", pg.locator(".selbar").is_visible())
    glitch(pg, "a selection, its bar")
    row_of(pg, "פרויקטים").click()
    check("with a selection open, a click adds the item", sel(pg) == 2, sel(pg))
    check("…and does not open it", route(pg) == "folder:", route(pg))
    row_of(pg, "פרויקטים").click()
    check("…a second click takes it out again", sel(pg) == 1, sel(pg))
    pg.keyboard.press("Escape")
    check("Escape clears the selection", sel(pg) == 0, sel(pg))

    row_of(pg, "פרויקטים").click(button="right")
    check("right-click opens the item's menu", pg.locator(".menu").is_visible())
    glitch(pg, "the item's menu")
    check("…leaves the selection as it was", sel(pg) == 0, sel(pg))
    check("…and marks the item while the menu is open", "ctx" in (row_of(pg, "פרויקטים").get_attribute("class") or ""))
    pg.keyboard.press("Escape")
    check("Escape closes the menu", pg.locator(".menu").count() == 0)
    check("…and the mark goes with it", "ctx" not in (row_of(pg, "פרויקטים").get_attribute("class") or ""))

    row_of(pg, "מסמכים").click(modifiers=["Control"])
    row_of(pg, "פרויקטים").click(modifiers=["Control"])
    check("ctrl+click selects one by one", sel(pg) == 2, sel(pg))
    row_of(pg, "פרויקטים").locator(".rowact").click()
    n = pg.evaluate("() => F.state.menu && F.state.menu.items.length")
    check("the ⋮ of a selected item is the selection's menu", bool(n), n)
    pg.keyboard.press("Escape")
    pg.keyboard.press("Escape")

    go(pg, {"view": "folder", "id": docs})
    row_of(pg, "דוח הכנסות 2026.xlsx").click()
    pg.wait_for_timeout(400)
    check("a click on a file opens the viewer", pg.locator(".vw").is_visible())
    glitch(pg, "a sheet in the viewer")
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(200)
    check("Escape closes the viewer", pg.locator(".vw").count() == 0)

    go(pg, {"view": "folder", "id": folder_id(pg, "תמונות מהשטח")})
    pg.evaluate("() => F.set({ layout: 'grid' })")
    pg.wait_for_timeout(200)
    card = pg.locator(".card").first
    card.hover()
    card.locator(".check").click()
    check("a card's circle selects", sel(pg) == 1, sel(pg))
    pg.keyboard.press("Escape")
    card.click()
    pg.wait_for_timeout(400)
    check("a click on a card opens it", pg.locator(".vw").is_visible())
    glitch(pg, "a picture in the viewer")
    pg.keyboard.press("Escape")
    pg.evaluate("() => F.set({ layout: 'list' })")

    go(pg, {"view": "photos"})
    tile = pg.locator(".tile").first
    tile.click()
    pg.wait_for_timeout(400)
    check("a click on a photo opens it", pg.locator(".vw").is_visible())
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(200)
    tile.hover()
    tile.locator(".check").click()
    check("a photo's circle selects it", sel(pg) == 1, sel(pg))
    check("…without opening it", pg.locator(".vw").count() == 0)
    pg.keyboard.press("Escape")

    go(pg, {"view": "music"})
    pg.locator(".tr").first.click()
    pg.wait_for_timeout(300)
    idx = pg.evaluate("() => F.state.player.index")
    check("a click on a track plays it", idx == 0, idx)
    glitch(pg, "music, a track playing")
    pg.evaluate("() => F.player.close()")

    go(pg, {"view": "home"})
    pg.locator(".fcard", has_text="הקלטות").click()
    ready(pg)
    check("a click on a folder card at home opens it", route(pg) == "folder:" + folder_id(pg, "הקלטות"), route(pg))
    glitch(pg, "a folder opened from home")

    for e in errs:
        check("no page error", False, e)
    ctx.close()


def touch(b, url):
    print("touch")
    ctx = new_ctx(b, 390, 844, has_touch=True, is_mobile=True, device_scale_factor=2)
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)[:200]))
    pg.goto(url, wait_until="networkidle")
    pg.wait_for_function("window.F && F.state && F.state.folders.length > 0", timeout=15000)

    go(pg, {"view": "folder", "id": ""})
    row_of(pg, "מסמכים").tap()
    ready(pg)
    check("a tap on a folder opens it", route(pg) == "folder:" + folder_id(pg, "מסמכים"), route(pg))
    glitch(pg, "a folder opened by a tap")

    go(pg, {"view": "folder", "id": ""})
    # a long press, the way a finger does it: down, held past the threshold, up, then the click the browser sends —
    # and Chrome on Android also sends contextmenu during the hold
    pg.evaluate("""async (name) => {
      const row = [...document.querySelectorAll('.lr')].find((r) => r.querySelector('.fname').textContent.includes(name));
      const at = row.getBoundingClientRect(), o = { bubbles: true, pointerType: 'touch', isPrimary: true, clientX: at.x + 60, clientY: at.y + 20 };
      row.dispatchEvent(new PointerEvent('pointerdown', o));
      await new Promise((r) => setTimeout(r, 650));
      row.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: o.clientX, clientY: o.clientY }));
      row.dispatchEvent(new PointerEvent('pointerup', o));
      row.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: o.clientX, clientY: o.clientY }));
    }""", "מסמכים")
    pg.wait_for_timeout(200)
    check("a long press selects", sel(pg) == 1, sel(pg))
    check("…does not open", route(pg) == "folder:", route(pg))
    check("…and the browser's contextmenu during the press opens no menu", pg.locator(".menu").count() == 0)
    glitch(pg, "a selection by long press")
    row_of(pg, "פרויקטים").tap()
    check("in a selection a tap adds", sel(pg) == 2, sel(pg))
    check("…and does not open", route(pg) == "folder:", route(pg))
    pg.locator(".selbar button").first.tap()
    check("the selection bar's ✕ ends the selection", sel(pg) == 0, sel(pg))

    # the add control: the top bar's + on a phone, the side's «חדש» where the side is open (a tablet, a desk)
    plus = pg.locator(".fx-top .icbtn.add")
    (plus if plus.count() else pg.locator(".side-new")).tap()
    items = pg.locator(".menu .mi").all_inner_texts()
    check("the + (or «חדש») opens upload, folder upload and new folder", len(items) == 3, items)
    glitch(pg, "the + menu")
    pg.locator(".menu .mi", has_text="תיקייה חדשה").tap()
    pg.locator(".bask input").fill("תיקיית בדיקה")
    pg.keyboard.press("Enter")
    pg.wait_for_function("() => F.state.list.folders.some((f) => f.name === 'תיקיית בדיקה')", timeout=8000)
    check("a new folder made from the + menu appears in the list", row_of(pg, "תיקיית בדיקה").is_visible())
    glitch(pg, "after a new folder")

    pg.locator("#files-pick").set_input_files(files=[{"name": "קבלה סרוקה.txt", "mimeType": "text/plain", "buffer": ("שורה " * 4000).encode("utf-8")}])
    pg.wait_for_function("() => F.state.list.files.some((f) => f.name === 'קבלה סרוקה.txt')", timeout=15000)
    check("a file chosen in the picker is uploaded into the open folder", row_of(pg, "קבלה סרוקה.txt").is_visible())
    glitch(pg, "after an upload")

    for e in errs:
        check("no page error", False, e)
    ctx.close()


def recorder(b, url):
    """«הקלטות» (/rec) with Chromium's fake microphone: what a person does with a recorder."""
    print("recorder (fake microphone)")
    touch = not OPT["size"] or OPT["size"][0] < 1024
    ctx = new_ctx(b, 390, 844, has_touch=touch, is_mobile=touch, device_scale_factor=2 if touch else 1)
    ctx.grant_permissions(["microphone"])
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)[:200]))
    pg.goto(url + "rec/", wait_until="networkidle")
    pg.wait_for_function("() => window.F && F.state.recList && !F.state.recList.loading", timeout=15000)
    names = lambda: pg.evaluate("() => (F.state.recList.files || []).map((f) => f.name)")
    takes = lambda: pg.evaluate("() => new Promise((res) => { const r = indexedDB.open('files-recorder'); r.onsuccess = () => {"
                                " const q = r.result.transaction('takes').objectStore('takes').getAll(); q.onsuccess = () => res(q.result.length); }; })")
    before = len(names())

    press(pg, pg.locator(".rc-rec"))
    pg.wait_for_function("() => F.state.rec.phase === 'recording'", timeout=10000)
    check("a tap on the big button starts a recording", True)
    glitch(pg, "recording")
    pg.wait_for_timeout(1600)
    press(pg, pg.locator(".rc-ctl .btn", has_text="השהיה"))
    t1 = pg.locator(".rc-clock").inner_text()
    pg.wait_for_timeout(1200)
    t2 = pg.locator(".rc-clock").inner_text()
    check("pause stops the clock", t1 == t2, f"{t1} → {t2}")
    press(pg, pg.locator(".rc-ctl .btn", has_text="המשך"))
    pg.wait_for_timeout(1300)
    check("…resume runs it on", pg.locator(".rc-clock").inner_text() != t2, pg.locator(".rc-clock").inner_text())
    check("what the microphone hears is measured while recording", pg.evaluate("() => F.recorder.eng.levels.length") > 10)
    press(pg, pg.locator(".rc-stop"))
    pg.wait_for_function(f"() => (F.state.recList.files || []).length > {before}", timeout=20000)
    new = [n for n in names() if n.startswith("הקלטה") and n.endswith((".webm", ".m4a", ".ogg"))]
    check("stop saves the take into «קבצים» → הקלטות, on top of the list", bool(new) and names()[0] == new[0], names()[:2])
    pg.wait_for_timeout(1700)
    check("…and nothing of it is left on the device once the server has it", takes() == 0, takes())
    check("the folder becomes the recorder's own", pg.evaluate("() => F.state.recList.folder && F.state.recList.folder.system") == "הקלטות")
    glitch(pg, "a saved take on top")

    press(pg, pg.locator(".rc-line").first)
    check("a tap on a recording opens it in place", pg.locator(".rc-open").count() == 1)
    glitch(pg, "a take opened in place")
    press(pg, pg.locator(".rc-big"))
    pg.wait_for_timeout(600)
    check("…its play button plays it", pg.evaluate("() => F.state.player.index >= 0 && F.player.cur().name") == names()[0])
    pg.evaluate("() => F.player.close()")

    n = len(names())
    press(pg, pg.locator(".rc-rec"))
    pg.wait_for_function("() => F.state.rec.phase === 'recording'", timeout=10000)
    pg.wait_for_timeout(1200)
    press(pg, pg.locator(".rc-ctl .btn", has_text="מחיקה"))
    press(pg, pg.locator(".bask button", has_text="מחיקה"))
    pg.wait_for_timeout(900)
    check("discard asks, then throws the take away — nothing saved", pg.evaluate("() => F.state.rec.phase") == "idle" and len(names()) == n and takes() == 0,
          [pg.evaluate("() => F.state.rec.phase"), len(names()), takes()])

    # a crash in the middle: the seconds already recorded are on the device, and are offered back
    press(pg, pg.locator(".rc-rec"))
    pg.wait_for_function("() => F.state.rec.phase === 'recording'", timeout=10000)
    pg.wait_for_timeout(2600)
    pg.reload(wait_until="networkidle")
    pg.wait_for_function("() => window.F && F.state.recList && !F.state.recList.loading", timeout=15000)
    pg.wait_for_timeout(600)
    check("after a reload mid-recording, the unsaved take is offered back", pg.locator(".rc-left").count() == 1)
    n = len(names())
    press(pg, pg.locator(".rc-left .btn", has_text="שמירה"))
    pg.wait_for_function(f"() => (F.state.recList.files || []).length > {n}", timeout=20000)
    pg.wait_for_timeout(1700)
    check("…and «שמירה» saves what was kept", takes() == 0 and pg.locator(".rc-left").count() == 0, [takes(), pg.locator(".rc-left").count()])

    for e in errs:
        check("no page error", False, e)
    ctx.close()

    # a microphone the person refused: a sentence that says how to allow it, and the button stays
    ctx = new_ctx(b, 390, 844)
    ctx.add_init_script("navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException('denied', 'NotAllowedError'));")
    pg = ctx.new_page()
    pg.goto(url + "rec/", wait_until="networkidle")
    pg.wait_for_function("() => window.F && F.state.recList && !F.state.recList.loading", timeout=15000)
    pg.locator(".rc-rec").click()
    pg.wait_for_timeout(500)
    msg = pg.locator(".rc-msg").inner_text() if pg.locator(".rc-msg").count() else ""
    check("a refused microphone says how to allow it", "מיקרופון" in msg and pg.locator(".rc-rec").is_enabled(), msg)
    glitch(pg, "a refused microphone")
    ctx.close()


def widget(b, url):
    """A window too small for the app (widget.js): one thing at a time, driven by hand."""
    print("widget, a small window (mouse and keyboard)")
    ctx = new_ctx(b, 380, 260)
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)[:200]))
    pg.goto(url, wait_until="networkidle")
    pg.wait_for_function("window.F && F.state && F.state.folders.length > 0", timeout=15000)
    ready(pg)
    frame = lambda: pg.evaluate("() => !!document.querySelector('.fx[data-tiny]') && !document.querySelector('.fx-side,.fx-top,.fx-tabs,.fx-content')")
    check("a 380×260 window is a widget — none of the app's frame inside it", frame())
    check("…home is its own short list", pg.locator(".wg-r").count() > 0 and pg.locator(".wg-place b").inner_text() == "בית", pg.locator(".wg-place b").inner_text())
    glitch(pg, "widget, home")

    def switch(to):
        pg.locator(".wg-place").first.click()
        pg.locator(".menu .mi").filter(has=pg.get_by_text(to, exact=True)).first.click()
        ready(pg)
    switch("תמונות")
    check("the place's name switches to Photos — a frame, one picture at a time", route(pg) == "photos:" and pg.locator(".wgf").count() == 1, route(pg))
    glitch(pg, "widget, photos")
    pg.wait_for_timeout(600)
    count = lambda: pg.locator(".wgf-cap .t > span").inner_text()
    c0 = count()
    pg.locator(".wgf").hover()
    pg.locator(".wgf-nav.next").click()
    pg.wait_for_timeout(250)
    c1 = count()
    check("the arrow on the picture steps to the next one", c1 != c0 and c1.startswith("2 "), f"{c0} → {c1}")
    pg.keyboard.press("ArrowLeft")
    pg.wait_for_timeout(250)
    check("…and ← (the next one, right to left) steps on", count().startswith("3 "), count())
    pg.locator(".wgf-btn").click()
    c2 = count()
    pg.wait_for_timeout(6800)
    check("pause holds the slideshow", count() == c2, f"{c2} → {count()}")
    pg.locator(".wgf-btn").click()
    pg.wait_for_timeout(7200)
    check("…and play runs it again by itself", count() != c2, f"{c2} → {count()}")
    pg.mouse.click(190, 130)
    pg.wait_for_timeout(500)
    check("a click on the picture opens it in the viewer", pg.locator(".vw").count() == 1)
    glitch(pg, "widget, the viewer")
    pg.wait_for_timeout(3000)
    check("…whose bar steps aside while nothing moves", pg.locator(".vw[data-idle]").count() == 1)
    pg.mouse.move(60, 60)
    pg.mouse.move(80, 70)
    check("…and comes back with the pointer", pg.locator(".vw[data-idle]").count() == 0)
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(300)
    check("Esc closes it, back to the frame", pg.locator(".vw").count() == 0 and pg.locator(".wgf").count() == 1)

    switch("מוזיקה ואודיו")
    first = pg.evaluate("() => F.player.titleOf([...F.state.list.files].sort((a, b) => String(b.created).localeCompare(String(a.created)))[0])")
    pg.locator(".wg-r").first.click()
    pg.wait_for_timeout(800)
    check("a click on a track plays it — the player's face takes the window", pg.locator(".wgp").count() == 1 and pg.locator(".wgp .ttl b").inner_text() == first,
          pg.locator(".wgp .ttl b").inner_text() if pg.locator(".wgp").count() else "no face")
    check("…playing", pg.evaluate("() => F.state.player.playing"))
    glitch(pg, "widget, the player's face")
    pg.locator(".wgp .ctl .big").click()
    pg.wait_for_timeout(300)
    check("the big button pauses", not pg.evaluate("() => F.state.player.playing"))
    pg.locator(".wgp .ttl .icbtn").first.click()
    pg.wait_for_timeout(200)
    check("⌄ folds the player into a line under the list", pg.locator(".wgp").count() == 0 and pg.locator(".wg-now").count() == 1 and pg.locator(".wg-r").count() > 0)
    glitch(pg, "widget, the player folded")
    pg.locator(".wg-now-open").click()
    check("…a click on that line opens it again", pg.locator(".wgp").count() == 1)
    pg.locator(".wgp .ttl .icbtn").nth(1).click()
    pg.wait_for_timeout(200)
    check("× closes the player, back to the list", pg.locator(".wgp,.wg-now").count() == 0 and pg.evaluate("() => F.state.player.index") == -1)

    switch("הקבצים שלי")
    docs = folder_id(pg, "מסמכים")
    pg.locator(".wg-r", has_text="מסמכים").first.click()
    ready(pg)
    check("a click on a folder opens it in the widget", route(pg) == "folder:" + docs and pg.locator(".wg-place b").inner_text() == "מסמכים", route(pg))
    glitch(pg, "widget, a folder")
    pg.locator(".wg-place").click()
    pg.locator(".menu .mi", has_text="לתיקייה").first.click()
    ready(pg)
    check("the switch's first entry goes up a folder", route(pg) == "folder:", route(pg))
    row = pg.locator(".wg-r:not(:has(.folder))").first
    name = row.get_attribute("data-id")
    row.click(button="right")
    labels = pg.locator(".menu .mi .lbl").all_inner_texts()
    check("a right click is the item's own menu", pg.evaluate("() => F.state.menu && F.state.menu.for") == name, pg.evaluate("() => F.state.menu && F.state.menu.for"))
    check("…without «פרטים», which a widget has no room to show", "פרטים" not in labels and "פתיחה" in labels, labels)
    pg.keyboard.press("Escape")
    pg.evaluate("() => F.set({ menu: null })")

    pg.set_viewport_size({"width": 1280, "height": 800})
    pg.wait_for_timeout(400)
    check("a larger window is the whole app again, in the same place", pg.locator(".fx-side").count() == 1 and pg.locator(".wg").count() == 0 and route(pg) == "folder:", route(pg))
    pg.evaluate("() => F.set({ sel: [F.state.list.files[0].id] })")
    pg.set_viewport_size({"width": 380, "height": 260})
    pg.wait_for_timeout(400)
    check("…and small again: the widget, with nothing left selected that it cannot show", frame() and sel(pg) == 0, sel(pg))
    check("no page errors", not errs, errs)
    ctx.close()

    print("widget, a 480×320 touch window")
    ctx = new_ctx(b, 480, 320, fixed=True, has_touch=True, device_scale_factor=2)
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)[:200]))
    pg.goto(url + "p/photos", wait_until="networkidle")
    pg.wait_for_function("window.F && F.state && F.state.folders.length > 0", timeout=15000)
    ready(pg)
    pg.wait_for_timeout(600)
    count = lambda: pg.locator(".wgf-cap .t > span").inner_text()
    c0 = count()
    # a swipe: the finger moves right — in a right-to-left gallery that brings the next picture
    cdp = ctx.new_cdp_session(pg)
    for kind, x in (("touchStart", 150), ("touchMove", 230), ("touchMove", 330), ("touchEnd", 330)):
        cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": [] if kind == "touchEnd" else [{"x": x, "y": 160}]})
    pg.wait_for_timeout(300)
    check("a swipe steps to the next picture", count() != c0 and count().startswith("2 "), f"{c0} → {count()}")
    check("…and opens nothing", pg.locator(".vw").count() == 0)
    pg.evaluate("() => F.go({ view: 'folder', id: '' })")
    ready(pg)
    row = pg.locator(".wg-r:not(:has(.folder))").first
    # a long press as the touch suite does it: down, held, the contextmenu Chrome sends during the hold, up, the click
    pg.evaluate("""async () => {
      const row = document.querySelector('.wg-r:not(:has(.folder))'), at = row.getBoundingClientRect();
      const o = { bubbles: true, pointerType: 'touch', isPrimary: true, clientX: at.x + 60, clientY: at.y + 20 };
      row.dispatchEvent(new PointerEvent('pointerdown', o));
      await new Promise((r) => setTimeout(r, 650));
      row.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: o.clientX, clientY: o.clientY }));
      row.dispatchEvent(new PointerEvent('pointerup', o));
      row.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: o.clientX, clientY: o.clientY }));
    }""")
    pg.wait_for_timeout(300)
    check("a long press is the item's menu (a sheet)", pg.locator(".menu.sheet").count() == 1 and pg.evaluate("() => F.state.menu && F.state.menu.for") == row.get_attribute("data-id"),
          pg.evaluate("() => F.state.menu && F.state.menu.for"))
    check("…once — the contextmenu of the same press adds no second one", pg.locator(".menu").count() == 1)
    check("…and opens nothing", pg.locator(".vw").count() == 0)
    check("no page errors", not errs, errs)
    ctx.close()

    print("«הקלטות», a small window (fake microphone)")
    ctx = new_ctx(b, 380, 260)
    ctx.grant_permissions(["microphone"])
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)[:200]))
    pg.goto(url + "rec/", wait_until="networkidle")
    pg.wait_for_function("() => window.F && F.state.recList && !F.state.recList.loading", timeout=15000)
    pg.wait_for_timeout(300)
    check("the recorder in a small window: the newest take and the button", pg.locator(".rc[data-tiny]").count() == 1 and pg.locator(".rc-list > .rc-row").count() >= 1 and pg.locator(".rc-rec").is_visible())
    glitch(pg, "widget, the recorder")
    pg.locator(".rc-rec").click()
    pg.wait_for_function("() => F.state.rec.phase === 'recording'", timeout=10000)
    pg.wait_for_timeout(1200)
    check("recording, the window is the recording alone", pg.locator(".rc[data-live]").count() == 1 and not pg.locator(".rc-top").is_visible() and pg.locator(".rc-clock").is_visible())
    glitch(pg, "widget, recording")
    n = pg.evaluate("() => F.state.recList.files.length")
    pg.locator(".rc-stop").click()
    pg.wait_for_function(f"() => F.state.recList.files.length > {n}", timeout=20000)
    pg.wait_for_timeout(400)
    check("stop saves it, and it is the take on show", pg.locator(".rc-list > .rc-row:not(.pending) .rc-t b").first.inner_text().startswith("הקלטה"))
    pg.locator(".rc-line").first.click()
    pg.wait_for_timeout(500)
    check("a click on the take plays it in the player's face", pg.locator(".rc[data-face] .wgp").count() == 1 and pg.evaluate("() => F.state.player.index") >= 0)
    pg.locator(".wgp .ttl .icbtn").first.click()
    pg.wait_for_timeout(200)
    check("⌄ goes back to the take and the button", pg.locator(".wgp").count() == 0 and pg.locator(".rc-rec").is_visible())
    check("no page errors", not errs, errs)
    pg.evaluate("() => F.player.close()")
    ctx.close()

    # the console's own smallest form (console desktop.js): a window pushed far to a side is one button and a
    # line, drawn from what the app says — here a parent page of the same origin stands where the console is
    print("widget, inside a parent that listens as the console does")
    ctx = new_ctx(b, 1000, 700, fixed=True)
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)[:200]))
    page = ('<!doctype html><html><body style="margin:0"><script>window.got = []; addEventListener("message", (e) => {'
            ' if (e.data && e.data.type === "bina:widget") got.push(e.data); });</script>'
            '<iframe id="app" src="/p/music" style="width:640px;height:600px;border:0"></iframe></body></html>')
    pg.route(url + "__parent", lambda r: r.fulfill(content_type="text/html", body=page))
    pg.goto(url + "__parent")
    pg.wait_for_function("() => { const w = document.getElementById('app').contentWindow; return w.F && w.F.state && !w.F.state.list.loading && w.F.state.list.files.length > 0; }", timeout=15000)
    fr = next(f for f in pg.frames if f.url.endswith("/p/music"))
    got = lambda: pg.evaluate("() => got.slice()")
    check("nothing is said to the console before there is something to say", got() == [], got())
    fr.evaluate("() => { F.player.audio.muted = true; }")
    fr.locator(".tr").first.click()
    pg.wait_for_timeout(900)
    title = fr.evaluate("() => F.player.titleOf(F.player.cur())")
    last = (got() or [{}])[-1]
    check("a playing track is said: its title, and the button is pause", last.get("label") == title and (last.get("action") or {}).get("icon") == "pause", last)
    pg.evaluate("() => document.getElementById('app').contentWindow.postMessage({ type: 'bina:widget-action', id: 'play' }, location.origin)")
    pg.wait_for_timeout(400)
    check("the console's button pauses it", not fr.evaluate("() => F.state.player.playing"))
    check("…and the button is said again, as play", ((got() or [{}])[-1].get("action") or {}).get("icon") == "play", (got() or [{}])[-1])
    fr.evaluate("() => window.postMessage({ type: 'bina:widget-action', id: 'play' }, location.origin)")
    pg.wait_for_timeout(400)
    check("a press that does not come from the console is not obeyed", not fr.evaluate("() => F.state.player.playing"))
    n = len(got())
    fr.evaluate("() => F.set({ size: { ...F.state.size } })")
    pg.wait_for_timeout(200)
    check("…and nothing is said twice", len(got()) == n, len(got()) - n)
    fr.evaluate("() => F.player.close()")
    pg.wait_for_timeout(300)
    check("closing the player clears the line", ((got() or [{}])[-1]) == {"type": "bina:widget", "label": ""}, (got() or [{}])[-1])
    check("no page errors", not errs, errs)
    ctx.close()


def run(url, suites, size=None, scheme="light", forced=False, tag=""):
    """One browser for one ground: forced dark is a browser switch (Chrome's WebContentsForceDark), as the UI map does."""
    OPT.update(size=size, scheme="dark" if forced else scheme, forced=forced, tag=tag)
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"]
                              + (["--enable-features=WebContentsForceDark"] if forced else []))
        for name, fn in (("mouse", mouse), ("touch", touch), ("recorder", recorder), ("widget", widget)):
            if name in suites:
                fn(b, url)
        b.close()


def fits(w, h):
    """The suites a box of this size is used with."""
    if h < 300 or (w < 560 and h < 440):
        return ["widget"]
    if w < 600:
        return ["touch", "recorder"]
    if w < 1024:
        return ["touch", "recorder", "mouse"]
    return ["mouse", "recorder"]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8971/")
    ap.add_argument("--size", default="", help="WxH[,WxH…]: run the suites that fit each size, in a window of exactly that size")
    ap.add_argument("--forced-dark", action="store_true", help="the owner's phone: the dark ground with Chrome's forced dark")
    ap.add_argument("--dark", action="store_true", help="the dark ground (prefers-color-scheme: dark)")
    ap.add_argument("--bar", action="store_true", help="the release bar: 412x760 forced dark, 768x1024, 1280x900, the 380x260 widget")
    ap.add_argument("--shots", default="", help="keep a picture of every state the glitch probe measured")
    ap.add_argument("suites", nargs="*", help="mouse, touch, recorder, widget (default: all, or what fits --size)")
    a = ap.parse_args()
    OPT["shots"] = a.shots
    scheme = "dark" if a.dark else "light"
    if a.bar:
        for (w, h), ground, suites in BAR:
            print(f"\n=== {w}×{h} {ground} — {', '.join(suites)} ===")
            run(a.url, a.suites or suites, (w, h), scheme if ground == "light" else "dark", ground == "forced", f"{ground}-")
    elif a.size:
        for one in a.size.split(","):
            w, h = (int(v) for v in one.lower().split("x"))
            print(f"\n=== {w}×{h}{' forced dark' if a.forced_dark else ''} ===")
            run(a.url, a.suites or fits(w, h), (w, h), scheme, a.forced_dark, ("forced-" if a.forced_dark else scheme + "-"))
    else:
        run(a.url, a.suites or ["mouse", "touch", "recorder", "widget"], None, scheme, a.forced_dark)
    print(f"\n{len(FAILS)} failed" if FAILS else "\nall flows passed")
    for f in FAILS:
        print("  FAIL " + f)
    sys.exit(1 if FAILS else 0)
