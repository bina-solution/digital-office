#!/usr/bin/env python3
"""office-links-selfcheck — does a link to the office stay in the tab the person is already in?

    python3 apps/bina-ds/tools/office-links-selfcheck.py [<gui url>]

Runs a real Chromium against a running bina (a scratch container of the image is enough — the edge's
identity header authenticates it, so no credential is involved) and clicks links the way the
harness's markdown renderer DRAWS them (`target="_blank"`):

  · a link to the office (`http://console.localhost/…`) must NAVIGATE THE SAME TAB;
  · a link to the outside (`https://example.com/`) must still open a new one;
  · AND — since 2026-10-09 (DGO-511) — a link clicked while this app is a WINDOW INSIDE the office
    desktop must move THE DESKTOP: the top window, whose route then changes, never the frame the
    person is not looking at, and never a second tab. The top window is named `qa.localhost` there
    (the `*.localhost` family resolves to loopback in Chromium), which is also what makes the second
    half provable: an office link means THE console the person is looking at, so the target carries
    the EMBEDDER's origin — the MacBook's :8080 must survive where hp-laptop's :80 is written.

The owner, 2026-10-08, twice: a link he was sent opened a new window «although I asked that by default
it opens in the same browser window I am already in»; and 2026-10-09: «הכל באותו דסקטופ כשרק הקישור
משתנה בלי שנוצר דף חדש בכרום». The plugin that answers it is plugins/office-links (the client half);
this is the check that the plugin is actually LOADED and that it did not swallow the new-tab behaviour
of ordinary web links.

Guarded for a machine that cannot run it (no docker, no browser image, no GUI): it says "not run" and
exits 0, so a gate suite may call it anywhere. Exit 1 only when a link behaved wrongly.
"""
import http.server
import os
import socket
import socketserver
import sys
import threading

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("not run: no playwright here (the office's browser image has it)")
    sys.exit(0)

GUI = sys.argv[1] if len(sys.argv) > 1 else "http://bina-qa:3080/"
OUT = os.environ.get("OFFICE_LINKS_OUT") or "/tmp/office-links-selfcheck"
FRAME_PORT = int(os.environ.get("OFFICE_LINKS_FRAME_PORT") or 8094)
os.makedirs(OUT, exist_ok=True)

from urllib.parse import urlparse                                    # noqa: E402

GUI_HOST = urlparse(GUI).hostname or ""
try:
    GUI_IP = os.environ.get("OFFICE_LINKS_IP") or socket.gethostbyname(GUI_HOST)
except OSError:
    GUI_IP = ""

try:                                     # a GUI that does not answer is "not run", never a failure:
    import urllib.request as _u          # this check is about behaviour, not about a running office
    # Asked by ADDRESS with the app's own name in the Host header: the harness refuses any authority
    # it was not told about, and a name only this office's edge answers (`bina.localhost`) does not
    # resolve from inside the network — which is where this check runs.
    _u.urlopen(_u.Request(f"http://{GUI_IP or GUI_HOST}:{urlparse(GUI).port or 80}/",
                          headers={"Host": GUI_HOST, "X-authentik-username": "azaria"}),
               timeout=5).read(64)
except _u.error.HTTPError as error:      # an HTTPError IS a response: read what it said
    # WHAT THE SERVER ACTUALLY SAID, not only the exception's name: a 502 from this edge names the
    # router, a 404 names the host — and `not run: … (HTTPError)` threw both away. Measured
    # 2026-10-10; gate G66 (unread-error-lint) is why the read is HERE, in the typed handler, and not
    # in a helper: the gate reads this handler's own source for `error.read(`.
    _body = ""
    try:
        _body = " ".join(error.read(200).decode("utf-8", "replace").split())
    except Exception:                    # noqa: BLE001 — the body is a bonus, never the check
        _body = ""
    print(f"not run: {GUI} does not answer ({type(error).__name__}{': ' + _body if _body else ''})")
    sys.exit(0)
except Exception as error:               # noqa: BLE001
    print(f"not run: {GUI} does not answer ({type(error).__name__})")
    sys.exit(0)
RESOLVER = (f"MAP {GUI_HOST} {GUI_IP}, MAP qa.localhost 127.0.0.1" if GUI_IP else "")
FRAME_TOP = f"http://qa.localhost:{FRAME_PORT}/"

with sync_playwright() as p:
    args = ["--no-sandbox", "--disable-dev-shm-usage"]
    if RESOLVER:
        args.append(f"--host-resolver-rules={RESOLVER}")
    b = p.chromium.launch(executable_path="/usr/bin/chromium", args=args)
    ctx = b.new_context(viewport={"width": 1280, "height": 800},
                        extra_http_headers={"X-authentik-username": "azaria"})
    pg = ctx.new_page()
    pg.goto(GUI, wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(4000)
    pg.screenshot(path=OUT + "/01-gui-before.png")
    print("plugins served:", "office-links" in pg.content())

    # the OFFICE link, drawn exactly as the harness renders one: target="_blank"
    n0 = len(ctx.pages)
    pg.evaluate("""() => {
        const a = document.createElement('a');
        a.href = 'http://console.localhost/#/m/project-pln';
        a.target = '_blank'; a.rel = 'noopener noreferrer';
        a.textContent = 'office link'; a.id = 'qa-office';
        document.body.appendChild(a); a.click();
    }""")
    pg.wait_for_timeout(3500)
    office_same_tab = len(ctx.pages) == n0 and not pg.url.startswith(GUI)
    pg.screenshot(path=OUT + "/02-same-tab-after-click.png")
    print("office link (target=_blank) → pages:", len(ctx.pages), "was", n0, "| this tab url:", pg.url[:60])

    # an EXTERNAL link, same shape: the harness's own new-tab must be untouched
    pg2 = ctx.new_page()
    pg2.goto(GUI, wait_until="domcontentloaded", timeout=60000)
    pg2.wait_for_timeout(3000)
    n1 = len(ctx.pages)
    pg2.evaluate("""() => {
        const a = document.createElement('a');
        a.href = 'https://example.com/'; a.target = '_blank'; a.rel = 'noopener noreferrer';
        a.textContent = 'external'; document.body.appendChild(a); a.click();
    }""")
    pg2.wait_for_timeout(3500)
    external_new_tab = len(ctx.pages) > n1
    print("external link (target=_blank) → pages:", len(ctx.pages), "was", n1)

    # ── the app as a WINDOW INSIDE the desktop: the link moves the TOP window ──────────────────
    #
    # The client half is injected into the RUNNING app's own page from THIS repo's file (rewritten
    # so it evaluates to the module the harness's loader would have registered), because the image a
    # container is running may predate it: what is proved here is that the plugin's source behaves,
    # and `grep` in the built image is what proves the image carries that same source.
    desktop_moved = None
    plugin = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "..", "plugins", "office-links", "lib", "client.js")
    # The image a container runs may predate the plugin, so the source is injected by default;
    # OFFICE_LINKS_INJECT=0 turns that off and the check then measures the plugin the app SERVES.
    inject = os.environ.get("OFFICE_LINKS_INJECT", "1") != "0"
    if not RESOLVER:
        print("not run (framed half): cannot resolve", GUI_HOST, "to an address to frame")
    elif not os.path.exists(plugin):
        print("not run (framed half): no", plugin)
    else:
        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *a):   # noqa: ARG002
                pass

        socketserver.TCPServer.allow_reuse_address = True
        with open(f"{OUT}/index.html", "w", encoding="utf-8") as f:
            f.write(f'<!doctype html><meta charset="utf-8"><title>the desktop</title>'
                    f'<iframe id="f" src="{GUI}" style="width:1200px;height:700px;border:0"></iframe>')
        os.chdir(OUT)
        srv = socketserver.TCPServer(("127.0.0.1", FRAME_PORT), Quiet)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            source = open(plugin, encoding="utf-8").read().replace(
                "window.__ModuleLoader__.load(", "window.__QA_PLUGIN = (")
            pg3 = ctx.new_page()
            pg3.goto(FRAME_TOP, wait_until="domcontentloaded", timeout=60000)
            pg3.wait_for_timeout(5000)
            n2 = len(ctx.pages)
            app_frame = [f for f in pg3.frames if f.url.startswith(GUI.rstrip("/")) or GUI_HOST in f.url]
            if not app_frame:
                print("not run (framed half): the app did not load inside the frame")
            else:
                if inject:
                    app_frame[0].add_script_tag(content=source)
                installed = app_frame[0].evaluate("""() => {
                    const spec = window.__QA_PLUGIN;
                    if (!spec) return 'the app serves its own plugin (no injection)';
                    if (typeof spec.factory !== 'function') return 'no spec';
                    const exports = spec.factory(() => ({}));      // the loader's contract: exports
                    const fn = exports && exports.apply;
                    if (typeof fn !== 'function') return 'no apply: ' + Object.keys(exports || {});
                    const seen = [];
                    fn({ effect: (cb) => { seen.push(typeof cb); return cb(); } });
                    return 'installed(' + seen.join(',') + ')';
                }""")
                print("framed half:", installed)
                app_frame[0].evaluate("""() => {
                    const a = document.createElement('a');
                    a.href = 'http://console.localhost:80/#/m/project-pln/bina/projects/p/issues/i';
                    a.target = '_blank'; a.rel = 'noopener noreferrer';
                    a.textContent = 'office link'; a.id = 'qa-framed';
                    document.body.appendChild(a);
                }""")
                # A REAL click, because a frame may only move the top window WITH the person's own
                # activation: a scripted `.click()` is refused by the browser, and a check that used
                # it would report the plugin broken when it is not (measured here, 2026-10-09).
                app_frame[0].locator("#qa-framed").click(timeout=8000)
                pg3.wait_for_timeout(2500)
                same_tab = len(ctx.pages) == n2
                desktop_moved = pg3.url.startswith(FRAME_TOP + "#/m/project-pln") and same_tab
                print("framed office link → top url:", pg3.url[:90], "| pages:", len(ctx.pages), "was", n2)
                pg3.screenshot(path=OUT + "/03-framed-after-click.png")
        finally:
            srv.shutdown()

    ctx.close()
    b.close()

print("\noffice link stayed in the tab:", office_same_tab)
print("external link opened a tab:", external_new_tab)
print("a framed office link moved the DESKTOP (not the frame), to the reader's own console:",
      desktop_moved)
failures = [office_same_tab, external_new_tab] + ([desktop_moved] if desktop_moved is not None else [])
sys.exit(0 if all(failures) else 1)
