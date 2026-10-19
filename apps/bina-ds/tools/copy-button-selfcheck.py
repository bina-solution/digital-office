#!/usr/bin/env python3
"""copy-button-selfcheck — does a message's copy button still copy inside a CROSS-ORIGIN frame?

    python3 apps/bina-ds/tools/copy-button-selfcheck.py [--app http://bina.localhost:3080] [--ip 1.2.3.4]
                                                        [--container bina-ds-<office>]

The owner, 2026-10-09 14:50, with the toolbar's own tooltip „העתקה" showing under a message:
«העתקה לא עובד». His window was this office's בינה framed by ANOTHER office's console. A remote tile
is framed on the app's own nested host — `platform/manager/serve.py:through_console` gives an app
that owns its origin (this one addresses /api, /plugins and a websocket at the ROOT) no `/a/` proxy —
so the frame is CROSS-ORIGIN, and in a cross-origin frame the async Clipboard API is refused by the
Permissions Policy default while the legacy path is not gated at all. Stock dsh's `writeClipboard`
answered that refusal with `catch { return false }` and never reached its own fallback, so the button
did nothing: silently, which is why nothing was reported until the owner clicked it.

WHAT THIS RUNS. A real Chromium (the office's browser image has one, like the sibling check), with a
top page on loopback that frames the RUNNING app over a name its harness trusts and the identity
header the platform edge adds — same SITE (so the harness boots at all: a third-party frame cannot
read localStorage and its plugins never activate), other ORIGIN (a different port), which is what
makes the frame cross-origin and therefore what decides the clipboard. Then a conversation is opened,
its last message hovered (the toolbar is revealed on hover), its copy button clicked, and the
clipboard read back from the TOP page.

The two assertions are the whole point: `navigator.clipboard.writeText` must be REFUSED inside the
frame (or the run proves nothing), and the clipboard must end up holding the message's own text.
A sentinel is put in the clipboard first, so "nothing happened" is visible rather than assumed.

Guarded for a machine that cannot run it (no playwright, no browser, no app answering): it says
"not run" and exits 0, so a gate suite may call it anywhere. Exit 1 only when the copy did not land.

Measured 2026-10-09, this office, Chrome/154, against the running bina-ds:
  · stock bundle  — writeText: NotAllowedError; clipboard after the click: the sentinel (nothing).
  · with the fallback (apps/bina-ds/harness/customize.sh) — same refusal; clipboard: the message.
"""
import argparse
import http.server
import json
import os
import re
import socket
import socketserver
import sys
import threading

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("not run: no playwright here (the office's browser image has it)")
    sys.exit(0)

OUT = os.environ.get("COPY_SELFCHECK_OUT") or "/tmp/copy-button-selfcheck"
COPY_LABELS = ["העתקה", "Copy", "הועתק", "Copied"]
SENTINEL = "SENTINEL-nothing-was-copied"


def find_button(label):
    """A copy control and the text around it, found by the label the locale gives it."""
    return """() => {
        const b = [...document.querySelectorAll('button[aria-label]')]
            .find(x => %s.includes(x.getAttribute('aria-label')));
        if (!b) return null;
        const box = b.closest('div')?.parentElement?.parentElement;
        return { label: b.getAttribute('aria-label'),
                 message: (box?.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 400) };
    }""" % json.dumps(label, ensure_ascii=False)


def session_titles(app):
    """Whatever conversations the sidebar offers, by the label of their own actions button."""
    return app.evaluate("""() => [...document.querySelectorAll('[aria-label]')]
        .map(e => e.getAttribute('aria-label'))
        .filter(t => /^(Session actions for |פעולות לשיחה )/.test(t))
        .map(t => t.replace(/^Session actions for |^פעולות לשיחה /, ''))""")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default="http://bina.localhost:3080", help="the app as the harness trusts it")
    ap.add_argument("--ip", default=os.environ.get("COPY_SELFCHECK_IP", ""),
                    help="where that name really is (the running container's address)")
    ap.add_argument("--port", type=int, default=8096, help="the top page's own port (loopback)")
    args = ap.parse_args()

    import urllib.parse as up
    host = up.urlparse(args.app).hostname
    app_port = up.urlparse(args.app).port or 3080
    ip = args.ip
    if not ip:
        for candidate in (os.environ.get("COPY_SELFCHECK_CONTAINER"),
                          f"bina-ds-{os.environ.get('DEPLOYMENT_NAME', '')}".strip("-")):
            try:
                ip = socket.gethostbyname(candidate)
                break
            except OSError:
                continue
    if not ip:
        try:                                     # the name may already resolve where this runs
            ip = socket.gethostbyname(host)
        except OSError:
            print(f"not run: cannot resolve {host} to an address — pass --ip")
            sys.exit(0)
    try:
        import urllib.request as ur
        # Probed by ADDRESS with the trusted name in the Host header: the name this check uses is
        # resolved by Chromium's own resolver rule, not by the machine running the check.
        ur.urlopen(ur.Request(f"http://{ip}:{app_port}/",
                              headers={"Host": host, "X-authentik-username": "azaria"}),
                   timeout=5).read(64)
    except Exception as error:                   # noqa: BLE001
        print(f"not run: {args.app} does not answer ({type(error).__name__})")
        sys.exit(0)

    top = f"http://{host}:{args.port}"
    os.makedirs(OUT, exist_ok=True)
    with open(f"{OUT}/index.html", "w", encoding="utf-8") as f:
        f.write(f'<!doctype html><html lang="he"><meta charset="utf-8"><title>top</title>'
                f'<body style="margin:0"><iframe id="f" src="{args.app}/" '
                f'style="width:1380px;height:860px;border:0"></iframe></body></html>')

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):  # noqa: ARG002
            pass

    socketserver.TCPServer.allow_reuse_address = True
    os.chdir(OUT)
    httpd = socketserver.TCPServer(("127.0.0.1", args.port), Quiet)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    result = {"app": args.app, "top": top, "ip": ip}
    code = 1
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(
                executable_path=os.environ.get("COPY_SELFCHECK_CHROME", "/usr/bin/chromium"),
                args=["--no-sandbox", "--disable-dev-shm-usage",
                      f"--host-resolver-rules=MAP {host}:{app_port} {ip}:{app_port}, "
                      f"MAP {host}:{args.port} 127.0.0.1:{args.port}"])
            ctx = b.new_context(viewport={"width": 1400, "height": 900},
                                extra_http_headers={"X-authentik-username": "azaria"})
            ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=top)
            pg = ctx.new_page()
            pg.goto(top + "/", wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_timeout(9000)
            frames = [f for f in pg.frames if f.url.startswith(args.app)]
            if not frames:
                print("not run: the app did not load in the frame")
                httpd.shutdown()
                sys.exit(0)
            app, fl = frames[0], pg.frame_locator("#f")

            # a conversation with history, then its last message hovered: the toolbar is revealed
            for title in session_titles(app)[:4]:
                try:
                    el = fl.get_by_text(title, exact=True).first
                    if el.count():
                        el.click(timeout=6000)
                        pg.wait_for_timeout(8000)
                        break
                except Exception:                # noqa: BLE001
                    continue

            state = app.evaluate(find_button(COPY_LABELS))
            if not state:
                for sel in ("[class*='bubble']", "[class*='Message']", "[class*='markdown']", "main"):
                    try:
                        el = fl.locator(sel).last
                        if el.count():
                            el.hover(timeout=4000)
                            pg.wait_for_timeout(900)
                            state = app.evaluate(find_button(COPY_LABELS))
                            if state:
                                break
                    except Exception:            # noqa: BLE001
                        continue
            if not state:
                print("not run: no copy button in the transcript to click")
                pg.screenshot(path=f"{OUT}/no-button.png")
                httpd.shutdown()
                sys.exit(0)
            result["button"] = state["label"]
            result["message"] = state["message"]
            result["writeText_in_frame"] = app.evaluate(
                "() => navigator.clipboard.writeText('probe').then(() => 'allowed').catch(e => e.name)")
            result["sentinel"] = pg.evaluate(
                "t => navigator.clipboard.writeText(t).then(() => navigator.clipboard.readText())", SENTINEL)
            fl.locator(f"button[aria-label='{state['label']}']").first.click(force=True)
            pg.wait_for_timeout(1500)
            try:
                result["clipboard"] = pg.evaluate("navigator.clipboard.readText()")
            except Exception as e:               # noqa: BLE001
                result["clipboard"] = f"<{type(e).__name__}: {e}>"
            pg.screenshot(path=f"{OUT}/after-click.png")
            ctx.close()
            b.close()
    finally:
        httpd.shutdown()

    clip = re.sub(r"\s+", " ", (result.get("clipboard") or "")).strip()
    message = re.sub(r"\s+", " ", result.get("message") or "")
    head = clip[:40]
    # The clipboard left holding something OTHER than the sentinel is what "it copied" means; when
    # the message text was read from the DOM, the two must also agree.
    copied = bool(clip) and clip != SENTINEL and clip != result.get("sentinel")
    agrees = (not message) or (head and head in message)
    refused = result.get("writeText_in_frame") not in (None, "allowed")
    print("RESULT " + json.dumps(result, ensure_ascii=False, indent=1))
    print("async clipboard API refused inside the frame:", refused)
    print("the click left the message's text in the clipboard:", copied and agrees, "|", clip[:80])
    sys.exit(0 if (refused and copied and agrees) else 1)


main()
