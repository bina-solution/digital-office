"""panel-shot — a MINIMAL live-browser check of one console page, and the evidence pass for DGO-57.

Why this file exists: `bbox ui-map` is the platform's full capture (inventory + coverage + regions +
a merged map), and on this engine it spent its 15-minute shard budget on the retry path and reported
`embedded app near-empty (15 nodes)` for the app panel — a verdict about the capture, not about the
app. This does the part that answers the question ("does the panel render, and does its JS throw?")
with one headless Chromium, one page at a time, and prints the DOM counts, the rendered text and every
console/page error so the answer is evidence rather than a screenshot nobody can read.

With PANEL_SHOTS=1 it also walks the app the way a person does — both screens, the connect wizard
opened by its real button, and both screens again at 390px — and records, per screen, the text and
whether the page overflows horizontally at phone width. Those shots are the acceptance evidence for
DGO-57/59 (the app shows accounts and mirrors; Forgejo shows repositories).

Run inside the ui-capture image (it carries the Chromium this platform pins):

  docker run --rm --network traefik-network \
    -v "<repo>/data/ui-map:/data" -v "<repo>/apps/git/tools:/tools:ro" \
    -e UI_HOST_RESOLVER="MAP console.localhost <traefik-ip>, MAP forge.console.localhost <traefik-ip>" \
    -e AK_USER=akadmin -e AK_PASS=<authentik admin password> \
    -e PANEL_URL=http://console:8000/a/git-accounts/ -e PANEL_SHOTS=1 \
    ui-capture:latest python3 -u /tools/panel-shot.py

Never use `MAP * <ip>`: it maps the SERVICE names too (`git`, `console`), which then resolve to the edge
and the capture dies on ERR_CONNECTION_REFUSED against a port nothing listens on.
"""
import json
import os
import sys

from playwright.sync_api import sync_playwright

CONSOLE = os.environ.get("PANEL_CONSOLE", "http://console.localhost")
PANEL = os.environ.get("PANEL_URL", CONSOLE + "/a/git-accounts/")
FORGE = os.environ.get("PANEL_FORGE", "http://forge.localhost/")
AK_USER = os.environ.get("AK_USER", "akadmin")
AK_PASS = os.environ.get("AK_PASS", "")
# The capture writes panel-shot.png / forge-shot.png here and its evidence screens into
# <PANEL_OUT>/shots. It is the CONTAINER's mount point by default; a caller mounting the checkout's
# data/ui-map elsewhere says so with PANEL_OUT.
OUT = os.environ.get("PANEL_OUT", "/data")
SHOTS = os.environ.get("PANEL_SHOTS", "") == "1"


def settle(page, ms=2500):
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(ms)


def on_ak_wall(page) -> bool:
    return "/flow/" in page.url or "authentik" in page.url


def ak_login(page) -> bool:
    for _ in range(3):
        try:
            page.get_by_role("textbox").first.fill(AK_USER)
            page.keyboard.press("Enter")
            page.wait_for_timeout(1500)
            page.locator("input[type=password]").first.fill(AK_PASS)
            page.keyboard.press("Enter")
            page.wait_for_url(lambda u: "/flow/" not in u, timeout=20000)
            settle(page)
            return True
        except Exception:
            page.wait_for_timeout(1000)
    return False


def probe(page) -> dict:
    """What the page actually shows: node counts, the panel's own text, the frame's text.

    The reader falls through to the top-level document when there is no `#frame`, so the SAME probe
    answers for the console page (app embedded) and for the app on its own origin.
    """
    out = {}
    try:
        out["url"] = page.url
        out["title"] = page.title()
        out["nodes"] = page.evaluate("document.querySelectorAll('*').length")
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        return out
    try:
        out["frame"] = page.eval_on_selector(
            "#frame",
            "el => { const d = el.contentDocument; return d ? {n: d.querySelectorAll('*').length,"
            " t: (d.body && d.body.innerText || '').replace(/\\s+/g,' ').slice(0,1200),"
            " src: el.getAttribute('src')} : null; }")
    except Exception:
        out["frame"] = None
    try:
        out["app"] = page.evaluate("""() => {
          const d = document.getElementById('frame')?.contentDocument || document;
          // The account line and the current screen live in the DECLARED menu (DGO-53), not in a top
          // bar of the app's own: the brand's context line and the menu's active row are the truth.
          const active = d.querySelector('.bnv-item.is-active');
          return {
            who: (d.querySelector('.bnv-head small')?.textContent || '').trim(),
            nav_active: active ? active.getAttribute('data-bnv-id') : null,
            nav_rows: d.querySelectorAll('.bnv-item').length,
            menu_open: (d.getElementById('sideNav')?.className || '').includes('is-open'),
            rows: d.querySelectorAll('.item-row').length,
            buttons: d.querySelectorAll('.btn').length,
            selected_provider: d.querySelectorAll('.pick').length,
            main: (d.getElementById('main')?.innerText || '').replace(/\\s+/g, ' ').slice(0, 700),
          };
        }""")
    except Exception as e:
        out["app"] = f"{type(e).__name__}: {e}"
    return out


def main() -> int:
    errors, console_msgs = [], []
    with sync_playwright() as p:
        args = ["--no-sandbox", "--disable-dev-shm-usage", "--ignore-certificate-errors",
                "--disable-gpu"]
        hr = os.environ.get("UI_HOST_RESOLVER")
        if hr:
            args.append(f"--host-resolver-rules={hr}")
        exe = os.environ.get("UI_CHROME_BIN") or None
        browser = p.chromium.launch(headless=True, executable_path=exe, args=args)
        ctx = browser.new_context(ignore_https_errors=True, viewport={"width": 1440, "height": 900},
                                  locale="he-IL")
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: console_msgs.append(f"{m.type}: {m.text}")
                if m.type in ("error", "warning") else None)

        report = {"login": None, "panel": None, "forge": None,
                  "page_errors": errors, "console": console_msgs}
        try:
            page.goto(PANEL, wait_until="domcontentloaded", timeout=45000)
            settle(page)
            if on_ak_wall(page):
                report["login"] = ak_login(page)
                page.goto(PANEL, wait_until="domcontentloaded", timeout=45000)
                settle(page)
            else:
                report["login"] = "not required"
            page.screenshot(path=f"{OUT}/panel-shot.png", full_page=True)
            report["panel"] = probe(page)

            if SHOTS:
                evidence(page, report)
            page.goto(FORGE, wait_until="domcontentloaded", timeout=45000)
            settle(page, 2000)
            page.screenshot(path=f"{OUT}/forge-shot.png", full_page=True)
            report["forge"] = {"url": page.url, "title": page.title(),
                               "nodes": page.evaluate("document.querySelectorAll('*').length"),
                               "text": page.evaluate("document.body.innerText.replace(/\\s+/g,' ').slice(0,300)")}
        except Exception as e:
            report["fatal"] = f"{type(e).__name__}: {e}"
        finally:
            try:
                browser.close()
            except Exception:
                pass
        print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


# ── the evidence pass (DGO-57) ────────────────────────────────────────────────────────────────────
# Two screens, the wizard opened by its real button, and both screens again at 390px. Routes are hash
# routes, so "navigating" is a real navigation the app's own router handles — not a mock. Each screen
# records its text plus whether it overflows horizontally, which is the one phone-width failure a
# screenshot of a table cannot show you.
def evidence(page, out: dict) -> None:
    import pathlib

    d = pathlib.Path(OUT, "shots")
    d.mkdir(parents=True, exist_ok=True)
    base = PANEL if PANEL.endswith("/") else PANEL + "/"

    def read():
        return page.evaluate("""() => {
          const doc = document.getElementById('frame')?.contentDocument || document;
          const de = doc.documentElement;
          return {text: (doc.body.innerText || '').replace(/\\s+/g, ' ').slice(0, 1400),
                  rows: doc.querySelectorAll('.item-row').length,
                  overflow: Math.max(0, de.scrollWidth - de.clientWidth),
                  width: de.clientWidth};
        }""")

    def go(route: str, wait: int = 3200):
        page.goto(base + route, wait_until="domcontentloaded", timeout=45000)
        settle(page, wait)

    def shot(name: str, note: str, full: bool = True):
        page.wait_for_timeout(1200)
        # A full-page shot of a long list is tens of thousands of pixels tall and the browser can
        # spend the whole timeout rasterising it — which is a failed capture reported as "the screen
        # is missing". Long lists are captured as viewport shots; the rest full-page.
        page.screenshot(path=str(d / f"{name}.png"), full_page=full, timeout=120000)
        got = read()
        got["note"] = note
        out.setdefault("screens", {})[name] = got

    # 1-3 · desktop: the two screens, and the wizard opened by clicking the real provider button
    go("#/accounts")
    shot("01-accounts", "the office's accounts, one row each: provider, login, state, actions")
    page.evaluate("""() => {
      const doc = document.getElementById('frame')?.contentDocument || document;
      doc.querySelector('[data-p="github"]')?.click();
    }""")
    settle(page, 1200)
    page.evaluate("""() => {
      const doc = document.getElementById('frame')?.contentDocument || document;
      doc.querySelector('.pick')?.click();
    }""")
    settle(page, 1200)
    shot("02-connect-wizard", "a provider chosen, a method chosen — the fields come from /providers")

    go("#/mirrors")
    shot("03-mirrors", "the declared mirrors, their forge copy, and the declaration form")

    # 4-5 · the phone width the owner asked about (390px = iPhone 14/15 logical width)
    page.set_viewport_size({"width": 390, "height": 844})
    go("#/accounts")
    shot("04-accounts-390", "390px: the top bar wraps, no horizontal scroll")
    go("#/mirrors")
    shot("05-mirrors-390", "390px: the mirrors screen")

    # 6 · the menu the app DECLARES, as a phone shows it: the component's drawer, opened by the
    #     component's own control (data-nav-toggle). This is the adoption DGO-53 asked for — the app
    #     contributes a declaration and an empty <aside>, never a row.
    page.set_viewport_size({"width": 390, "height": 844})
    go("#/accounts")
    page.evaluate("""() => {
      const doc = document.getElementById('frame')?.contentDocument || document;
      const t = doc.getElementById('navToggle');
      if (t) t.click();
      const side = doc.getElementById('sideNav');
      return !!side;
    }""")
    settle(page, 1200)
    shot("08-menu-drawer-390", "390px: the menu the app declares, opened by the component's burger")

    # 7 · the shell's own road to the forge: the tile the owner clicks to reach repositories
    page.set_viewport_size({"width": 1440, "height": 900})
    go("#/mirrors")
    href = page.evaluate("""() => {
      const doc = document.getElementById('frame')?.contentDocument || document;
      return doc.getElementById('open-forge')?.getAttribute('href') || null;
    }""")
    out["forge_link"] = href
    if href:
        # The link the OWNER's browser follows carries the edge port (`http://forge.console.localhost:8080`).
        # Inside traefik-network that port is traefik's own dashboard, not the ingress, so the capture
        # goes to the same host on :80 — the same router, the same page, minus the harness limitation.
        # Both are recorded: the link is evidence, the port-stripped URL is what was photographed.
        import re as _re
        shot_url = _re.sub(r"^(https?://[^/:]+):\d+", r"\1", href)
        out["forge_link_captured"] = shot_url
        page.goto(shot_url, wait_until="domcontentloaded", timeout=45000)
        settle(page, 3000)
        page.screenshot(path=str(d / "06-forge-from-the-app.png"), full_page=False, timeout=120000)
        out.setdefault("screens", {})["06-forge-from-the-app"] = {
            "note": "where 'open the forge' lands — the repository list is Forgejo's",
            "url": page.url, "title": page.title(),
            "text": page.evaluate("document.body.innerText.replace(/\\s+/g,' ').slice(0,400)")}
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(shot_url, wait_until="domcontentloaded", timeout=45000)
        settle(page, 2500)
        page.screenshot(path=str(d / "07-forge-390.png"), full_page=False, timeout=120000)
        out.setdefault("screens", {})["07-forge-390"] = {
            "note": "the forge at 390px, the width the acceptance asks about",
            "text": page.evaluate("document.body.innerText.replace(/\\s+/g,' ').slice(0,300)")}


if __name__ == "__main__":
    sys.exit(main())
