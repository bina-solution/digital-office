#!/usr/bin/env python3
"""test_load_failed — does the apps screen still PROMISE a load after the load has failed?

    python3 platform-base/app-management/test_load_failed.py [--static <dir>] [--old-rev HEAD]

The owner's screenshot (DGO-521, `apps-coming-up-silent.png`): app-management open, its own failure
card in the grid — «רשימת האפליקציות עוד לא נטענה — שירות ניהול האפליקציות איטי או מופעל מחדש» — and
the header above it reading «טוען את רשימת האפליקציות…». The screen said two opposite things at once,
and the false one was in the place a person looks first.

WHY IT CANNOT BE CHECKED BY READING THE FILE. The defect is a state, not a sentence: it appears only
when the FIRST read fails — a later failure keeps the last list on screen and says so in the note
(the `STATE.apps.length` branch). So this runs the real screen against a real failing service.

TWO ARMS, ONE BROWSER.
  · OLD — `static/app.js` as of `--old-rev` (git). Expected: the loading sentence over the failure
    card. That is the defect, reproduced rather than described.
  · NEW — the working copy. Expected: a header that says the list is NOT loaded, and the reason still
    in the grid. If NEW ever prints «טוען…» over the failure card, this exits 1.

Guarded for a machine that cannot run it (no playwright, no browser, no git revision): it says
"not run" and exits 0, so a gate suite may call it anywhere. Exit 1 only when the new arm lies.
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import pathlib
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading

try:
    from playwright.sync_api import sync_playwright
except ImportError:                                     # pragma: no cover - host without it
    print("not run: no playwright here (the ui-capture image has it)")
    sys.exit(0)

REPO = pathlib.Path(__file__).resolve().parents[2]
HERE = pathlib.Path(__file__).resolve().parent
LOADING = "טוען את רשימת האפליקציות…"
TRUTHFUL = "רשימת האפליקציות לא נטענה"
#: what the console's 502 looks like to this screen — the sentence the owner saw in the card.
REASON = "אין תשובה מהשירות (502)"


def old_source(rev: str) -> str | None:
    """The screen as it was, straight out of git. None when this is not a git checkout."""
    rel = "platform-base/app-management/static/app.js"
    try:
        r = subprocess.run(["git", "show", f"{rev}:{rel}"], cwd=str(REPO),
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 and r.stdout else None


class Handler(http.server.SimpleHTTPRequestHandler):
    """The app's own files, and a service that is DOWN.

    Every read the screen makes fails the way a slow or restarting service fails: 502 with a body.
    `/api/apps` is the one that matters; the rest are here so the screen runs its real boot path
    (the catalogue, the linked-office half) instead of stopping on an unhandled rejection.
    """

    def do_GET(self) -> None:                           # noqa: N802 - BaseHTTPRequestHandler API
        if self.path.split("?")[0].startswith(("/api/", "/a/")):
            body = json.dumps({"message": REASON}, ensure_ascii=False).encode()
            self.send_response(502)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, *a) -> None:                  # noqa: ARG002 - quiet by design
        pass


def arm(name: str, app_js: str, static: pathlib.Path, out: pathlib.Path, port: int) -> dict:
    """Serve one version of the screen, load it in Chromium, and read what it says."""
    serve = out / name
    serve.mkdir(parents=True, exist_ok=True)
    shutil.copy(static / "index.html", serve / "index.html")
    (serve / "app.js").write_text(app_js, encoding="utf-8")

    os.chdir(serve)
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    got: dict = {"arm": name, "url": f"http://127.0.0.1:{port}/"}
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(
                executable_path=os.environ.get("LOAD_FAILED_CHROME", "/usr/bin/chromium"),
                args=["--no-sandbox", "--disable-dev-shm-usage"])
            pg = b.new_page(viewport={"width": 1180, "height": 820})
            pg.goto(got["url"], wait_until="domcontentloaded", timeout=60000)
            # the failure card is the signal that the first read is over and the screen has decided
            pg.wait_for_selector("#grid .empty", timeout=20000)
            pg.wait_for_timeout(700)                    # let the 5 s poll (and render) settle
            got["sub"] = pg.inner_text("#sub").strip()
            got["grid"] = " ".join(pg.inner_text("#grid").split())
            got["loading_sentence_still_shown"] = LOADING in got["sub"]
            shot = out / f"{name}.png"
            pg.screenshot(path=str(shot), full_page=True)
            got["screenshot"] = str(shot)
            b.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
    return got


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--static", default=str(HERE / "static"), help="the screen's own directory")
    ap.add_argument("--out", default=os.environ.get("LOAD_FAILED_OUT", "/tmp/dgo521-load-failed"))
    ap.add_argument("--old-rev", default="HEAD", help="the revision the OLD arm is taken from")
    ap.add_argument("--old-static", default="",
                    help="the OLD arm's own directory, for a machine with no git (a mounted copy)")
    ap.add_argument("--port", type=int, default=8123)
    args = ap.parse_args()

    static, out = pathlib.Path(args.static), pathlib.Path(args.out)
    if not (static / "index.html").exists() or not (static / "app.js").exists():
        print(f"not run: {static} does not hold the screen (index.html + app.js)")
        return 0
    out.mkdir(parents=True, exist_ok=True)

    new_js = (static / "app.js").read_text(encoding="utf-8")
    old_js, old_where = None, ""
    if args.old_static:
        p = pathlib.Path(args.old_static) / "app.js"
        if p.exists():
            old_js, old_where = p.read_text(encoding="utf-8"), str(p)
    if old_js is None:
        old_js, old_where = old_source(args.old_rev), f"{args.old_rev}:static/app.js"
    report: dict = {"static": str(static), "old_rev": old_where}

    if old_js and old_js != new_js:
        report["old"] = arm("old", old_js, static, out, args.port)
        print(f"OLD ({old_where})  header: «{report['old']['sub']}»")
        print(f"             card:   «{report['old']['grid'][:110]}…»")
        print(f"             the defect is reproduced: {report['old']['loading_sentence_still_shown']}")
    else:
        report["old"] = None
        print(f"OLD arm not run: no differing revision at {old_where} (the fix is the committed one)")

    report["new"] = arm("new", new_js, static, out, args.port)
    n = report["new"]
    print(f"NEW          header: «{n['sub']}»")
    print(f"             card:   «{n['grid'][:110]}…»")
    print(f"             screenshot: {n['screenshot']}")
    print(json.dumps(report, ensure_ascii=False)[:0] or "", end="")
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    bad = []
    if n["loading_sentence_still_shown"]:
        bad.append(f"the header still says «{LOADING}» over a failed load")
    if n["sub"] != TRUTHFUL:
        bad.append(f"the header is «{n['sub']}», not «{TRUTHFUL}»")
    if REASON not in n["grid"]:
        bad.append(f"the grid no longer carries the reason «{REASON}»")
    if bad:
        print("FAIL")
        for b in bad:
            print(f"  · {b}")
        return 1
    print("PASS — a failed load is stated in the header (and its reason is still in the card),")
    print("       in a real Chromium, against a service answering 502")
    return 0


if __name__ == "__main__":
    sys.exit(main())
