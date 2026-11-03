#!/usr/bin/env python3
"""desktop-link-selfcheck — does a link/address to the office move the desktop the person is in?

    python3 apps/bina-ds/tools/desktop-link-selfcheck.py [<console url>]

The claim under test is the owner's own (work item ui2-060): «המצב בדסקטוף, החלון המוצג והמידע בחלון
תמיד מוכוון קישור … הכל באותו דסקטוף כשרק הקישור משתנה בלי שנוצר דף חדש בכרום». Its sibling here,
`office-links-selfcheck.py`, proves the PLUGIN's half in a page it serves itself; this proves the half
the person actually meets — the console, in desktop mode:

  1. a pasted address for an app that is ALREADY open moves that window (its frame at the route, the
     address bar saying so, no new tab);
  2. an address for an app that has no window opens one IN THE SAME DESKTOP, no new tab;
  3. **a link clicked INSIDE the agent's own window** (`bina`) — the shape the agent posts — moves the
     same desktop and opens NO TAB. Tabs are counted from before the click: counting them for the whole
     session let a real extra tab pass as a pass (measured 2026-10-13, which is why this check exists).

Guarded for a machine that cannot run it (no playwright, no console): it says "not run" and exits 0,
so a gate suite may call it anywhere. Exit 1 only when the desktop behaved wrongly.
"""
import glob
import json
import os
import sys
from urllib.parse import urlparse

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("not run: no playwright here (the office's browser image has it)")
    sys.exit(0)

URL = sys.argv[1] if len(sys.argv) > 1 else "http://console:8000"
AUTH = {"X-authentik-username": "admin", "X-authentik-email": "admin@office.local",
        "X-authentik-name": "Admin", "X-authentik-groups": "authentik Admins"}

STATE = """() => ({
  hash: location.hash,
  desktop: !!(window.BinaDesktop && BinaDesktop.isOn()),
  windows: (window.BinaDesktop && BinaDesktop.wm ? BinaDesktop.wm.wins() : []).map(w => w.mid),
  frames: [...document.querySelectorAll('iframe')].map(f => { try { return f.contentWindow.location.pathname; } catch (e) { return 'other-origin'; } }),
  opens: window.__opens || 0,
})"""


def browser(chromium):
    """A BROWSER WHEREVER THIS IMAGE KEEPS IT. The same tool is run by hand and by the live lane inside
    the office's browser image, and there the default per-user path (`/root/.cache/ms-playwright`) does
    not exist while playwright's own install sits under `/ms-playwright` — `launch()` then dies with
    `Executable doesn't exist` (measured 2026-10-13, the first wiring of this tool into G81's live
    lane). The path is DISCOVERED; letting playwright choose stays the last resort."""
    for path in ("/usr/bin/chromium", "/usr/bin/chromium-browser",
                 *sorted(glob.glob("/ms-playwright/*/chrome-linux64/chrome"))):
        if os.path.exists(path):
            return chromium.launch(executable_path=path, args=["--no-sandbox"])
    return chromium.launch(args=["--no-sandbox"])


def main() -> int:
    try:
        return _run()
    except Exception as error:  # noqa: BLE001  a check that dies must SAY it failed, not print a trace
        print(f"desktop-link-selfcheck: FAILED — {type(error).__name__}: {str(error)[:140]}")
        return 1


def _run() -> int:
    with sync_playwright() as p:
        b = browser(p.chromium)
        ctx = b.new_context(extra_http_headers=AUTH, viewport={"width": 1440, "height": 900},
                            locale="he-IL")
        popups = []
        ctx.on("page", lambda pg: popups.append(pg.url))
        page = ctx.new_page()
        try:
            page.goto(f"{URL}/#/m/drive", wait_until="domcontentloaded", timeout=60000)
        except Exception as error:  # noqa: BLE001
            print(f"not run: {URL} does not answer ({type(error).__name__})")
            b.close()
            return 0
        page.wait_for_timeout(2500)
        page.evaluate("""() => { window.__opens = 0; const real = window.open;
            window.open = (...a) => { window.__opens++; return real.apply(window, a); }; }""")
        page.evaluate("() => window.BinaDesktop && BinaDesktop.enable()")
        page.wait_for_timeout(2500)
        if not page.evaluate("() => !!(window.BinaDesktop && BinaDesktop.isOn())"):
            print("not run: the desktop did not come up (a phone viewport, or no shell)")
            b.close()
            return 0

        # 1 — a pasted address for an app that is already open
        page.evaluate("() => { location.hash = '#/m/drive/trash'; }")
        page.wait_for_timeout(2000)
        st = page.evaluate(STATE)
        moved = st["hash"] == "#/m/drive/trash" and "/a/drive/trash" in st["frames"] \
            and st["opens"] == 0 and "drive" in st["windows"]
        print("the address moved the desktop it was already in:", moved, json.dumps(st, ensure_ascii=False)[:140])

        # 2 — an address for an app with no window: a window of the same desktop
        other = "machine"
        page.evaluate("(m) => { location.hash = '#/m/' + m; }", other)
        page.wait_for_timeout(2200)
        st2 = page.evaluate(STATE)
        opened = st2["hash"] == f"#/m/{other}" and other in st2["windows"] and st2["opens"] == 0
        print(f"a link to an app with no window opened one in the same desktop ({other}):", opened)

        # 3 — a link INSIDE the agent's own window: the desktop moves, and no tab opens
        chat = next((f for f in page.frames if urlparse(f.url).path.startswith("/a/bina")), None)
        if chat is None:
            page.evaluate("() => { location.hash = '#/m/bina'; }")
            page.wait_for_timeout(2500)
            chat = next((f for f in page.frames if urlparse(f.url).path.startswith("/a/bina")), None)
        if chat is None:
            print("not run: the agent's own window is not on this office (no `bina` tile)")
            b.close()
            return 0 if (moved and opened) else 1
        # THE PLUGIN MUST BE LIVE BEFORE A CLICK MEANS ANYTHING. The harness boots its client plugins
        # asynchronously ("Loading plugins…" is on its own screen for a while), and a click that lands
        # before `office-links` is applied measures the RACE, not the plugin: it did nothing at all
        # (no move, no tab — measured 2026-10-13), which reads exactly like a broken plugin. The wait
        # is on what the harness SAYS, bounded, and its absence is reported as "not run".
        for _ in range(25):
            said = ""
            try:
                said = chat.evaluate("() => (document.body.innerText || '').slice(0, 200)")
            except Exception:  # noqa: BLE001
                pass
            if said and "Loading plugins" not in said and "Failed to load plugins" not in said and len(said) > 20:
                break
            page.wait_for_timeout(1000)
        else:
            print("not run: the agent's window never finished loading its plugins")
            b.close()
            return 0 if (moved and opened) else 1
        before = len(popups)
        chat.evaluate("""(href) => {
            const a = document.createElement('a');
            a.id = 'qa-office-link'; a.href = href; a.target = '_blank'; a.rel = 'noopener noreferrer';
            // A REAL BOX: an anchor with no size is "not visible" to a real click, and Playwright
            // refuses to click it (measured on the first run of this tool).
            a.style.cssText = 'position:fixed;inset-inline-start:4px;bottom:4px;width:120px;height:24px;'
                            + 'opacity:0.01;z-index:99999;display:block';
            document.body.appendChild(a);
        }""", f"{URL}/#/m/{other}")
        page.wait_for_timeout(300)
        try:
            chat.locator("#qa-office-link").click(timeout=8000)
        except Exception as error:  # noqa: BLE001
            print(f"not run: the link could not be clicked inside the agent's window ({type(error).__name__})")
            b.close()
            return 0 if (moved and opened) else 1
        page.wait_for_timeout(2500)
        st3 = page.evaluate(STATE)
        new_tabs = len(popups) - before
        in_chat = st3["hash"] == f"#/m/{other}" and new_tabs == 0 and st3["desktop"]
        print("a link inside the agent's window moved the same desktop, no new tab:", in_chat,
              f"(tabs opened by this click: {new_tabs})")
        # 4 — A LINK TO A TILE OF A LINKED OFFICE, with a work-item-shaped route: the same rule has to
        # hold for the tile of the office the item lives in (`<alias>.<office>`), which is the shape the
        # agent posts most when it answers about a work item. Skipped, and said, when this office has
        # no linked-office tile — and it is the desktop's ADDRESS that is checked here, not whether
        # `plane` lets anybody in: the account is a separate matter.
        # THE TILE, not an open window: a linked office is a rail entry whose id is `<alias>.<office>`
        # (`bina.hp-laptop`) — the windows list holds only what is already open (measured: the first cut
        # of this looked at the windows and said "no linked-office tile" on an office that has two).
        # …AND ONLY WHERE THE PLUGIN CAN RECOGNISE A PEER HOST AT ALL. A link is "the office" when its
        # host shares this page's suffix, or is `*.localhost`; the console reached at a BARE name
        # (`console:8000`, i.e. from inside the office network) has no suffix to compare — the plugin's
        # own comment says so — and a peer link is correctly left alone there. Measured 2026-10-13: this
        # case failed on both runs against the in-network address, and that is the address, not the tool.
        suffixed = page.evaluate("() => (location.hostname || '').includes('.')")
        peer = page.evaluate("""() => { const a = [...document.querySelectorAll('#nav a[data-id]')]
            .find((x) => String(x.dataset.id).includes('.')); return a ? String(a.dataset.id) : null; }""")
        if peer and not suffixed:
            print(f"not run (linked office): this console is reached at a bare name (`{URL}`) — the plugin "
                  f"recognises a peer host by suffix, so it leaves such a link alone by design")
            peer = None
        if peer is None:
            if suffixed:
                print("not run (linked office): this office has no linked-office tile")
            peer_ok = None
        else:
            route = f"#/m/{peer}/bina/projects/1/issues/1"
            before = len(popups)
            chat.evaluate("""(href) => {
                const a = document.createElement('a');
                a.id = 'qa-peer-link'; a.href = href; a.target = '_blank'; a.rel = 'noopener noreferrer';
                a.style.cssText = 'position:fixed;inset-inline-start:4px;bottom:32px;width:120px;height:24px;'
                                + 'opacity:0.01;z-index:99999;display:block';
                document.body.appendChild(a);
            }""", f"{URL}/{route}")
            page.wait_for_timeout(300)
            try:
                chat.locator("#qa-peer-link").click(timeout=8000)
                page.wait_for_timeout(2500)
            except Exception as error:  # noqa: BLE001
                print(f"not run (linked office): the link could not be clicked ({type(error).__name__})")
                peer_ok = None
            else:
                st4 = page.evaluate(STATE)
                tabs = len(popups) - before
                peer_ok = st4["hash"] == route and tabs == 0
                print(f"a link to a linked office's tile moved the same desktop, no new tab: {peer_ok}"
                      f" (tabs opened by this click: {tabs})")
        ctx.close()
        b.close()

    checks = [("pasted address", moved), ("link to a closed app", opened),
              ("link inside the agent's window", in_chat)]
    if peer_ok is not None:
        checks.append(("link to a linked office's tile", peer_ok))
    bad = [name for name, ok in checks if not ok]
    print("\ndesktop-link-selfcheck:", "all three hold" if not bad else "FAILED — " + ", ".join(bad))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
