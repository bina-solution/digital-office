#!/usr/bin/env python3
"""Quick regression smoke test after the month-index / STATUS-persistence fixes:
pagination (page 2 != page 1), sort (NAME asc/desc changes first row), free-text
search (narrows the reported total), and the reported total itself. None of these
code paths were touched by this session's changes, but they are the six things
the task explicitly says must not regress."""
import os
import sys
from pathlib import Path

# Page text this probe echoes to stdout (search results, row content) can be Hebrew — python
# defaults stdout to the platform ANSI codepage outside lib.sh's PYTHONIOENCODING=utf-8, which
# raises UnicodeEncodeError on the first Hebrew character (portability-lint.py, G10).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

TARGET = sys.argv[1] if len(sys.argv) > 1 else "http://172.18.0.22:8080"
OUT_DIR = Path("/data/regress")
OUT_DIR.mkdir(parents=True, exist_ok=True)

exe = (
    os.getenv("UI_CHROME_BIN")
    or next((str(g) for g in sorted(Path("/root/.cloakbrowser").glob("*/chrome"))), None)
    or next((str(g) for g in sorted(Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome"))), None)
)


def grid_first_row_text(page):
    return page.evaluate(
        "(() => { const g = document.querySelector('revo-grid'); "
        "const s = g && g.source; return s && s.length ? JSON.stringify(s[0]).slice(0,200) : null; })()"
    )


def poll_for(page, fn, tries=15, interval_ms=600):
    for _ in range(tries):
        v = fn()
        if v:
            return v
        page.wait_for_timeout(interval_ms)
    return fn()


with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True, executable_path=exe or None,
        args=["--no-sandbox", "--disable-dev-shm-usage", "--ignore-certificate-errors", "--disable-gpu"],
    )
    ctx = browser.new_context(ignore_https_errors=True, viewport={"width": 2200, "height": 900}, locale="he-IL")
    page = ctx.new_page()

    url = f"{TARGET}/repos/incoming-documents-main/documents"
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(1500)
    try:
        page.wait_for_load_state("networkidle", timeout=9000)
    except Exception:
        pass
    page.wait_for_timeout(800)

    # ── total ──
    body_text = page.locator("body").inner_text()
    print("REGRESSION: page loaded, total text snippet:",
          [l for l in body_text.splitlines() if 'רשומות' in l or 'שורות' in l][:3])

    # ── pagination: page 1 vs page 2 ──
    page1_first = poll_for(page, lambda: grid_first_row_text(page))
    next_btn = page.locator("button", has_text="›").first
    next_btn.click()
    page.wait_for_timeout(1500)
    try:
        page.wait_for_load_state("networkidle", timeout=6000)
    except Exception:
        pass
    page2_first = poll_for(page, lambda: grid_first_row_text(page))
    print("REGRESSION: pagination — page1 first row == page2 first row?",
          page1_first == page2_first, "(should be False)")
    page.screenshot(path=str(OUT_DIR / "1_page2.png"))

    # back to page 1
    prev_btn = page.locator("button", has_text="‹").first
    prev_btn.click()
    page.wait_for_timeout(1200)

    # ── sort: click NAME header twice (asc, then desc) ──
    name_header = page.locator(".header-content", has_text="NAME").first
    if name_header.count() == 0:
        print("REGRESSION: NAME header not found in current column view (may need column picker) — skipping sort check")
    else:
        name_header.click()
        page.wait_for_timeout(1200)
        asc_first = poll_for(page, lambda: grid_first_row_text(page))
        name_header.click()
        page.wait_for_timeout(1200)
        desc_first = poll_for(page, lambda: grid_first_row_text(page))
        print("REGRESSION: sort — asc first == desc first?", asc_first == desc_first, "(should be False)")

    # ── free-text search ──
    search = page.locator("input.bt-search")
    search.click()
    search.fill("פנל אור")
    page.wait_for_timeout(1500)
    try:
        page.wait_for_load_state("networkidle", timeout=6000)
    except Exception:
        pass
    page.wait_for_timeout(500)
    body_text2 = page.locator("body").inner_text()
    print("REGRESSION: after search, total lines:",
          [l for l in body_text2.splitlines() if 'רשומ' in l or 'תוצא' in l][:3])

    browser.close()
