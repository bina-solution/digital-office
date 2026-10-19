#!/usr/bin/env python3
"""One-off probe: drive the real INDOX document browser, flip a row's STATUS via the
inline enum <select>, and report what happened. Talks directly to the incoming-documents
container (no Traefik/Authentik hop needed — the BFF has no auth check of its own, and the
SPA's BASE_PATH defaults to '/' when there's no <base> tag, i.e. when not console-embedded).
"""
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

TARGET = sys.argv[1] if len(sys.argv) > 1 else "http://172.18.0.22:8080"
ROW_ID = sys.argv[2] if len(sys.argv) > 2 else "1773244929307a59hlr"
NEW_STATUS = sys.argv[3] if len(sys.argv) > 3 else "ACTION_RESTART"
OUT_DIR = Path("/data/probe")
OUT_DIR.mkdir(parents=True, exist_ok=True)

exe = (
    os.getenv("UI_CHROME_BIN")
    or next((str(g) for g in sorted(Path("/root/.cloakbrowser").glob("*/chrome"))), None)
    or next((str(g) for g in sorted(Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome"))), None)
)

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True, executable_path=exe or None,
        args=["--no-sandbox", "--disable-dev-shm-usage", "--ignore-certificate-errors", "--disable-gpu"],
    )
    ctx = browser.new_context(ignore_https_errors=True, viewport={"width": 2600, "height": 900}, locale="he-IL")
    page = ctx.new_page()
    logs = []
    page.on("console", lambda m: logs.append(f"[console:{m.type}] {m.text}"))
    page.on("pageerror", lambda e: logs.append(f"[pageerror] {e}"))
    net = []

    def on_req(req):
        if "/documents" in req.url and req.method in ("PATCH", "PUT"):
            net.append(f"[REQ] {req.method} {req.url} body={req.post_data}")

    def on_resp(resp):
        if "/documents" in resp.url and resp.request.method in ("PATCH", "PUT"):
            try:
                body = resp.text()
            except Exception:
                body = "<unreadable>"
            net.append(f"[RESP] {resp.status} {resp.url} body={body[:500]}")

    page.on("request", on_req)
    page.on("response", on_resp)

    url = f"{TARGET}/repos/incoming-documents-main/documents"
    print(f"navigating to {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(1500)
    try:
        page.wait_for_load_state("networkidle", timeout=9000)
    except Exception:
        pass
    page.wait_for_timeout(1000)

    # search for the target row to isolate it (also proves free-text search still works)
    search = page.locator("input.bt-search")
    search.click()
    search.fill(ROW_ID)
    page.wait_for_timeout(1500)
    try:
        page.wait_for_load_state("networkidle", timeout=6000)
    except Exception:
        pass
    page.wait_for_timeout(500)

    page.screenshot(path=str(OUT_DIR / "1_searched.png"))

    # sanity: how many rows / columns does the grid element itself carry
    info = page.evaluate(
        "(() => { const g = document.querySelector('revo-grid'); "
        "return {columns: g && g.columns ? g.columns.length : null, "
        "source: g && g.source ? g.source.length : null}; })()"
    )
    print("grid element state:", info)

    # find the STATUS enum <select> — poll: RevoGrid (re)virtualizes columns/rows on
    # every source/filter change, so the cell can briefly not exist right after a
    # re-render even though the grid element's own .columns/.source already have it.
    sel = page.locator("select.bt-enumcell")
    count = 0
    for attempt in range(15):
        count = sel.count()
        if count > 0:
            break
        if attempt == 5:
            # try scrolling the grid viewport horizontally to bring STATUS into view
            page.evaluate(
                "(() => { const vp = [...document.querySelectorAll('revogr-viewport-scroll')]"
                ".sort((a,b)=>b.clientWidth-a.clientWidth)[0]; if (vp) vp.scrollLeft = vp.scrollWidth; })()"
            )
        page.wait_for_timeout(600)
    print("enum selects found (after polling):", count)

    page.screenshot(path=str(OUT_DIR / "2_before_edit.png"))

    if count == 0:
        print("RESULT: STATUS enum select not reachable in DOM")
    else:
        before_val = sel.first.input_value()
        print("current STATUS value in grid:", before_val)
        sel.first.select_option(NEW_STATUS)
        page.wait_for_timeout(2500)
        try:
            page.wait_for_load_state("networkidle", timeout=6000)
        except Exception:
            pass
        page.wait_for_timeout(500)
        page.screenshot(path=str(OUT_DIR / "3_after_edit.png"))
        toast = page.locator(".toast, [class*=toast]")
        print("toast text:", toast.all_inner_texts() if toast.count() else None)

        # reload the page fresh and re-search, to prove the change survived a real reload
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1200)
        search2 = page.locator("input.bt-search")
        search2.click()
        search2.fill(ROW_ID)
        page.wait_for_timeout(1500)
        try:
            page.wait_for_load_state("networkidle", timeout=6000)
        except Exception:
            pass
        page.wait_for_timeout(500)
        page.screenshot(path=str(OUT_DIR / "4_after_reload.png"))
        sel2 = page.locator("select.bt-enumcell")
        after_val = sel2.first.input_value() if sel2.count() else None
        print("STATUS value after reload:", after_val)

    print("\n--- console/page logs ---")
    for l in logs[-40:]:
        print(l)

    print("\n--- network (PATCH/PUT to /documents) ---")
    for l in net:
        print(l)

    browser.close()
