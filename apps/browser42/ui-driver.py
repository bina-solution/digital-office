#!/usr/bin/env python3
"""b42-ui.py — drive the shared Browser42 Chromium over CDP for Console-UI testing.

Usage (inside the browser42-browser container, or anywhere with CDP access):
    python3 b42-ui.py <action> [args]

Actions:
    tabs                    list all tabs (index, name, url, title)
    open <url> [tag]        open a URL in the shared context, tag it, print its handle
    shot <out.png> [tag]    screenshot the tab with `tag` (or the newest) to <out.png>
    eval <tag> <js>         evaluate JS in the tagged tab, print JSON result
    click <tag> <selector>  click a CSS selector in the tagged tab
    type <tag> <selector> <text>   fill a CSS selector in the tagged tab
    wait <tag> <ms>         wait in the tagged tab
"""
import base64
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

CDP = os.environ.get("B42_CDP", "http://localhost:9222")


def _connect():
    p = sync_playwright().start()
    b = p.chromium.connect_over_cdp(CDP)
    return p, b


def _name(pg):
    try:
        return pg.evaluate("window.name")
    except Exception:
        return ""


def _pages(b):
    return [pg for ctx in b.contexts for pg in ctx.pages]


def _by_tag(b, tag):
    return next((pg for pg in _pages(b) if _name(pg) == tag), None)


def _newest(b):
    pages = _pages(b)
    return pages[-1] if pages else None


def action_tabs(b):
    out = []
    for i, pg in enumerate(_pages(b)):
        try:
            url = pg.url
            title = pg.title()
        except Exception:
            url, title = "?", "?"
        out.append({"i": i, "name": _name(pg), "url": url[:90], "title": title[:50]})
    print(json.dumps(out, ensure_ascii=False, indent=2))


def action_open(b, url, tag):
    ctx = b.contexts[0]
    pg = ctx.new_page()
    if tag:
        pg.evaluate(f"window.name = {tag!r}")
    pg.goto(url, wait_until="domcontentloaded", timeout=45000)
    print(json.dumps({"ok": True, "name": _name(pg), "url": pg.url}, ensure_ascii=False))
    sys.stdout.flush()
    os._exit(0)  # keep the tab alive


def action_shot(b, out, tag):
    pg = _by_tag(b, tag) if tag else _newest(b)
    if pg is None:
        print(json.dumps({"ok": False, "error": "no matching tab"}))
        return 2
    pg.screenshot(path=out, timeout=30000)
    size = os.path.getsize(out)
    print(json.dumps({"ok": True, "out": out, "bytes": size, "url": pg.url[:90]}, ensure_ascii=False))


def action_eval(b, tag, js):
    pg = _by_tag(b, tag) if tag else _newest(b)
    if pg is None:
        print(json.dumps({"ok": False, "error": "no matching tab"}))
        return 2
    result = pg.evaluate(js)
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, default=str))


def action_click(b, tag, selector):
    pg = _by_tag(b, tag) if tag else _newest(b)
    if pg is None:
        print(json.dumps({"ok": False, "error": "no matching tab"}))
        return 2
    pg.click(selector, timeout=15000)
    print(json.dumps({"ok": True, "clicked": selector, "url": pg.url[:90]}, ensure_ascii=False))


def action_type(b, tag, selector, text):
    pg = _by_tag(b, tag) if tag else _newest(b)
    if pg is None:
        print(json.dumps({"ok": False, "error": "no matching tab"}))
        return 2
    pg.fill(selector, text, timeout=15000)
    print(json.dumps({"ok": True, "filled": selector, "text": text[:40]}, ensure_ascii=False))


def action_wait(b, tag, ms):
    pg = _by_tag(b, tag) if tag else _newest(b)
    if pg is None:
        print(json.dumps({"ok": False, "error": "no matching tab"}))
        return 2
    pg.wait_for_timeout(int(ms))
    print(json.dumps({"ok": True, "waited": int(ms)}, ensure_ascii=False))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    verb = sys.argv[1]
    args = sys.argv[2:]
    p, b = _connect()
    try:
        if verb == "tabs":
            return action_tabs(b)
        if verb == "open":
            return action_open(b, args[0], args[1] if len(args) > 1 else "")
        if verb == "shot":
            return action_shot(b, args[0], args[1] if len(args) > 1 else "")
        if verb == "eval":
            return action_eval(b, args[0], args[1])
        if verb == "click":
            return action_click(b, args[0], args[1])
        if verb == "type":
            return action_type(b, args[0], args[1], args[2])
        if verb == "wait":
            return action_wait(b, args[0], args[1])
        print(f"unknown action: {verb}")
        return 2
    finally:
        sys.stdout.flush()


if __name__ == "__main__":
    sys.exit(main())
