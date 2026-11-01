#!/usr/bin/env python3
"""theme-token-lint — gate G27: every bundled copy of a shared design block matches its source.

The gate carries N marked BLOCKS (see BLOCKS below). The first is the theme tokens; the
second is the side menu (`bina-nav.css`). Adding a shared block is a ROW in that list,
not a second near-identical script — a copy-pasted gate is the same duplication bug this
file exists to prevent, one level up.

(Was labelled G21 in CI, colliding with route-claim-lint.py, which is the G21 this repo means when
it says G21. Renumbered here and in the workflow; see scripts/refactor/GATES.md for the registry.)

Apps bundle a COPY of the design system on purpose: an app must stay independently installable, so
it cannot depend on a shared stylesheet at runtime. The price of that is drift, and drift is not
hypothetical here — before this gate, bina-ui.css and the mailview copy carried two different dark
palettes (#0f1613 vs #0d1411 for the same --bg), so the same app in OS-dark and in chosen-dark was
two different products, and the console had no dark palette at all while the apps did.

The block is delimited by the markers below, so a file can carry whatever else it needs around it —
the console adds its own --side rail variables after the shared block, which is fine and is why this
compares the DELIMITED REGION rather than the whole file.

    python3 scripts/refactor/theme-token-lint.py         # check  (non-zero on drift)
    python3 scripts/refactor/theme-token-lint.py --fix   # rewrite every copy from the source
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "platform-base/bina-ui/theme-tokens.css"
START = "/* @bina-theme-tokens:start */"
END = "/* @bina-theme-tokens:end */"

# Every surface a person can see. A file listed here MUST carry the block; that is the point — an app
# that silently has no dark palette is precisely the bug, so "absent" is a failure, not a skip.
TARGETS = [
    "platform-base/console/static/style.css",
    "platform-base/bina-ui/bina-ui.css",
    # [2026-10-01] dgo-extend's pairing screen (DGO-34). A file is a surface whether or not it is an
    # app's `index.html`: connect.html is opened by a person on a machine that is being joined, so it
    # needs the same palette, the same side menu and the same page chrome as every other screen.
    "apps/dgo-extend/static/connect.html",
    "platform-base/data-management/static/index.html",
    "apps/drive/static/index.html",
    "apps/mail/mailview/static/index.html",
    "apps/my-docs/static/style.css",
    "apps/computers/static/index.html",
    "apps/git/static/index.html",
    "apps/sites/static/index.html",
    "apps/domains/static/index.html",
    "apps/digital-assets/static/index.html",
    "apps/social-list/static/index.html",
    "apps/dgo-extend/static/index.html",
    "apps/telegram-tv/static/style.css",
    # [2026-10-07] Six screens wrote the palette out themselves and carried no block, so a change
    # of palette passed them by (the office became «Olive Grove» that day, DGO-450).
    "apps/any-concurrency/static/index.html",
    "platform-base/app-management/static/index.html",
    "platform-base/connections/ui.html",
    "platform-base/machine/static/index.html",
    "platform-base/notifications/static/index.html",
    "apps/archify/server.mjs",
    # [2026-10-07, later] …and four more that had done the same: the system-validation dashboard and
    # the three pages the chat service writes (sign-in, not-found, the admin itself).
    "apps/apitools/feature-validation/api/dashboard.html",
    "apps/chat/src/api/ui/login.ejs",
    "apps/chat/src/api/ui/404.ejs",
    "apps/chat/src/api/ui/chat.ejs",
    # …and the coding agent's dispatcher, whose pages (chat, issues, the two it answers with when
    # there is no remote screen) live in script strings and were two dark palettes of their own.
    "apps/openhands/dispatcher/lib/dashboard.js",
    # …and INDOX, the one app that is compiled: its sheet said "light-only, deliberately" while the
    # console was, and kept the old palette when the console's changed.
    "apps/indox/app/webapp/src/index.css",
]


# A1 — one type stack, everywhere. Checked separately from the delimited block because --font lives
# in each app's own :root, not in the shared theme region, so a marker-based copy cannot carry it.
#
# This is not hypothetical either: my-docs, machine, connections and INDOX were all missing
# "Assistant" — the Hebrew face — which is why the same Hebrew text set at a visibly different weight
# in those four apps than in the rest of the platform. Nothing errored. The system font stack simply
# fell through to the next entry, and it looked like a design choice.
CANONICAL_FONT = '"Segoe UI",system-ui,-apple-system,"Noto Sans Hebrew","Assistant",Arial,sans-serif'
FONT_RE = re.compile(r"--font:\s*([^;}]+)")
ALONE_RE = re.compile(r"""font(?:-family)?:[^;}]*Segoe UI(?!["']?\s*,\s*system-ui)[^;}]*""")
BLOCK_RE = re.compile(re.escape(START) + ".*?" + re.escape(END), re.S)

# Files that declare their own --font. A file NOT listed here is not exempt — it simply does not
# declare one and inherits, which is the preferred state.
FONT_TARGETS = [
    "platform-base/console/static/style.css",
    "platform-base/bina-ui/bina-ui.css",
    "platform-base/machine/static/index.html",
    "platform-base/data-management/static/index.html",
    "platform-base/notifications/static/index.html",
    "apps/any-concurrency/static/index.html",
    "platform-base/connections/ui.html",
    "apps/drive/static/index.html",
    "apps/mail/mailview/static/index.html",
    "apps/my-docs/static/style.css",
    "apps/indox/app/webapp/src/index.css",
    "apps/computers/static/index.html",
    "apps/git/static/index.html",
]


# ── the shared blocks this gate carries ──────────────────────────────────────
# One source file, N marked regions, every visible surface carrying a byte-identical copy.
# A surface listed here MUST carry the block — "absent" is a failure, not a skip, because an
# app that quietly kept its own side menu is exactly the drift this gate is for.
# Apps whose whole UI is one scrolling page: no router, so the menu names their SECTIONS.
NAV_JS_TARGETS: list[str] = [
    "apps/git/static/index.html",
    "apps/mail/mailview/static/index.html",
    "apps/dgo-extend/static/connect.html",
    "platform-base/app-management/static/index.html",
    "platform-base/data-management/static/index.html",
    "platform-base/notifications/static/index.html",
    "apps/indox/app/webapp/index.html",
    "apps/digital-assets/static/index.html",
]

# Apps that are one scrolling page: no router, no sections — their uniformity is the CHROME.
PAGE_TARGETS: list[str] = [
    "apps/computers/static/index.html",
    "apps/digital-assets/static/index.html",
    "apps/domains/static/index.html",
    "apps/sites/static/index.html",
    "apps/social-list/static/index.html",
    "apps/dgo-extend/static/connect.html",
    "platform-base/machine/static/index.html",
    "platform-base/notifications/static/index.html",
    "apps/any-concurrency/static/index.html",
    "platform-base/data-management/static/index.html",
    "apps/dgo-extend/static/index.html",
]

NAV_TARGETS: list[str] = [
    "platform-base/console/static/style.css",
    "apps/dgo-extend/static/connect.html",
    "platform-base/data-management/static/index.html",
    "apps/mail/mailview/static/index.html",
    "apps/drive/static/index.html",
    "apps/indox/app/webapp/src/index.css",
    "apps/telegram-tv/static/style.css",
    "platform-base/app-management/static/index.html",
    "apps/sites/static/index.html",
    "apps/domains/static/index.html",
    "platform-base/connections/ui.html",
    "apps/git/static/index.html",
    "apps/digital-assets/static/index.html",
    "apps/social-list/static/index.html",
    "platform-base/notifications/static/index.html",
]

BLOCKS = [
    {"name": "theme tokens", "source": "platform-base/bina-ui/theme-tokens.css",
     "start": START, "end": END, "targets": TARGETS},
    {"name": "side menu", "source": "platform-base/bina-ui/bina-nav.css",
     "start": "/* @bina-nav:start */", "end": "/* @bina-nav:end */", "targets": NAV_TARGETS},
    # The menu's BEHAVIOUR for a screen that is one page (no router, so no routes to list):
    # it names the sections the page already has and scrolls to them. Same doctrine — one
    # source, a byte-identical copy per app, absent is a failure.
    {"name": "side menu (sections)", "source": "platform-base/bina-ui/bina-nav.js",
     "start": "/* @bina-nav-js:start */", "end": "/* @bina-nav-js:end */", "targets": NAV_JS_TARGETS},
    # The page's chrome — header, live chip, card — for the apps that are ONE scrolling page and
    # therefore cannot take a side menu. Three header classes and four scales became one.
    {"name": "page chrome", "source": "platform-base/bina-ui/bina-page.css",
     "start": "/* @bina-page:start */", "end": "/* @bina-page:end */", "targets": PAGE_TARGETS},
    # The glyphs a tile may name (`routing[].module.icon`), for every surface that lists apps. Two
    # sets had grown — one app, two icons on two screens, and a box wherever the smaller set lacked
    # the name.
    {"name": "tile icons", "source": "platform-base/bina-ui/bina-icons.js",
     "start": "/* @bina-icons:start */", "end": "/* @bina-icons:end */",
     # …and the console's first-run wizard, which draws each app it offers with its tile's icon and
     # the office's animal with its glyph (install.js is served on its own, before the shell); and the
     # link screen, whose cards name a linked office and draw THAT office's animal beside the name
     # (flt-004 — the animal half of the office's mark, which is a glyph of this set or nothing).
     "targets": ["platform-base/console/static/app.js", "platform-base/app-management/static/app.js",
                 "platform-base/console/static/install.js", "apps/dgo-extend/static/app.js"]},
    # What a failed request is CALLED when the service sent no sentence of its own. Eight request
    # helpers ended in `body.error || "HTTP " + r.status`, so a service that was down -- the one that
    # cannot send a sentence -- was reported as "HTTP 502"; five said the answer "is not JSON".
    # A question and a notice asked INSIDE the page. Eight screens used the browser's own
    # confirm / alert / prompt (27 places): unstyled, left to right, and with no room for the
    # facts of what is about to be removed.
    {"name": "a question and a notice", "source": "platform-base/bina-ui/bina-ask.js",
     "start": "/* @bina-ask:start */", "end": "/* @bina-ask:end */",
     "targets": ["apps/computers/static/app.js", "apps/domains/static/app.js", "apps/sites/static/app.js",
                 "apps/git/static/app.js", "apps/my-docs/static/app.js", "apps/drive/static/app.js",
                 "platform-base/console/static/app.js", "platform-base/machine/static/index.html",
                 "platform-base/notifications/static/index.html", "apps/social-list/static/app.js",
                 "apps/digital-assets/static/app.js", "platform-base/connections/ui.html",
                 "platform-base/app-management/static/app.js", "apps/telegram-tv/static/app.js",
                 "apps/mail/mailview/static/app.js", "apps/chat/src/api/ui/chat.ejs",
                 "apps/dgo-extend/static/app.js", "apps/apitools/feature-validation/api/dashboard.html"]},
    # The office's ONE mark, drawn inline so its three parts wear the palette's tokens (the image
    # files beside the source carry the values, for a favicon and the site). Two screens drew their
    # own copies of it before (the shell, the first-run wizard); the simulator embeds the shell, and
    # the site copies the files — so this is where "the logo, integrated everywhere" is kept true.
    {"name": "the office's mark", "source": "platform-base/bina-ui/brand/mark.html",
     "start": "<!-- @bina-brand:start -->", "end": "<!-- @bina-brand:end -->",
     "targets": ["platform-base/console/static/index.html", "platform-base/console/static/install.html"]},
    {"name": "what a failed request is called", "source": "platform-base/bina-ui/bina-said.js",
     "start": "/* @bina-said:start */", "end": "/* @bina-said:end */",
     "targets": ["apps/dgo-extend/static/app.js", "apps/dgo-extend/static/connect.js", "apps/domains/static/app.js",
                 "apps/domains/static/store.js", "apps/sites/static/app.js", "apps/computers/static/app.js",
                 "apps/digital-assets/static/app.js", "apps/social-list/static/app.js",
                 "platform-base/app-management/static/app.js", "platform-base/console/static/power-settings.js",
                 "platform-base/data-management/static/index.html", "apps/telegram-tv/static/app.js",
                 "platform-base/console/static/install.js", "apps/my-docs/static/app.js",
                 "apps/drive/static/app.js", "apps/mail/mailview/static/app.js",
                 "platform-base/connections/ui.html", "apps/apitools/feature-validation/api/dashboard.html"]},
    # There WAS a "the screen in the address bar" block here (`platform-base/bina-ui/bina-route.js`),
    # stamped into each app so it could speak to the console about its route. It is gone: the shell
    # reads the frame's own URL instead (platform-base/console/static/app.js `watchFrameRoute`), so
    # an app takes part by using its own router, exactly like every other web app, and nothing is
    # copied into it. Owner's rule, 2026-10-12: no polling, no protocol in the apps.
]


# Whole FILES an app vendors — no markers, the file is the block. Not a list: every tracked
# `vendor/<name>` IS a copy, so a new app's copy is kept from the day it is added. (Until 2026-10-06
# nothing kept these at all; they happened to be identical when the grid's first-paint fix landed.)
VENDORED = ["platform-base/bina-ui/bina-table.js", "platform-base/bina-ui/bina-table.css"]

# Whole files copied to a NAMED place rather than a `vendor/` directory: the office's favicon is
# served from the shell's own static root (`/favicon.svg`), where a `vendor/` path would not be a
# favicon. Source -> the copies that must stay byte-identical to it.
VENDORED_COPIES = {
    "platform-base/bina-ui/brand/favicon.svg": ["platform-base/console/static/favicon.svg"],
}


def check_vendored(fix: bool) -> int:
    """Return the number of vendored copies that differ from their source."""
    bad = 0
    for rel in VENDORED + list(VENDORED_COPIES):
        want = (ROOT / rel).read_bytes().replace(b"\r\n", b"\n")
        copies = VENDORED_COPIES.get(rel) or subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "--", "*/vendor/" + Path(rel).name],
            capture_output=True, text=True).stdout.splitlines()
        for copy in copies:
            if (ROOT / copy).read_bytes().replace(b"\r\n", b"\n") == want:
                print(f"ok    {copy}  (a copy of {rel})")
            elif fix:
                (ROOT / copy).write_bytes(want)
                print(f"fixed {copy}  (a copy of {rel})")
            else:
                print(f"FAIL  {copy}: differs from {rel}")
                bad += 1
    return bad


def check_fonts(fix: bool) -> int:
    """Return the number of files whose --font drifted from the canonical stack."""
    norm = lambda s: re.sub(r"\s+", "", s).strip()
    bad = 0
    for rel in FONT_TARGETS:
        p = ROOT / rel
        if not p.exists():
            print(f"FAIL  {rel}: file not found (listed as declaring --font)")
            bad += 1
            continue
        text = p.read_text(encoding="utf-8")
        found = FONT_RE.search(text)
        if not found:
            print(f"FAIL  {rel}: no --font declaration (listed as declaring one)")
            bad += 1
            continue
        if norm(found.group(1)) == norm(CANONICAL_FONT):
            continue
        if fix:
            with p.open("w", encoding="utf-8", newline="") as fh:
                fh.write(FONT_RE.sub(lambda m: "--font:" + CANONICAL_FONT, text, count=1))
            print(f"fixed {rel}  (--font)")
        else:
            print(f"FAIL  {rel}: --font drifted from the canonical stack")
            bad += 1
    # …and wherever a screen names the stack's first family itself, `system-ui` follows it. The block's faces
    # make "Segoe UI" a family of Hebrew only (Hebrew at 800 had no face on Windows), so every other character
    # goes on to the NEXT family named: after `system-ui` that is the same face as before; after anything
    # else, a page's Latin changes face on Windows and nothing errors.
    for rel in TARGETS:
        text = (ROOT / rel).read_text(encoding="utf-8") if (ROOT / rel).exists() else ""
        alone = ALONE_RE.search(BLOCK_RE.sub("", text))
        if alone:
            print(f"FAIL  {rel}: names \"Segoe UI\" with no `system-ui` after it ({alone.group(0)[:60]})")
            bad += 1
    return bad


def region(text: str, path: str, start: str = START, end: str = END) -> str:
    """The delimited block, or a clear failure. Unbalanced markers are a hard error rather than a
    silent empty match — a truncated block is the drift this gate exists to catch."""
    i, j = text.find(start), text.find(end)
    if i < 0 or j < 0:
        raise LookupError(f"{path}: no '{start}' block (expected {start} … {end})")
    if j < i:
        raise LookupError(f"{path}: markers are inverted ({start})")
    return text[i:j + len(end)]


def carriers(marker: str) -> set[str]:
    """Every tracked surface under apps/ and platform-base/ whose text holds `marker`."""
    found = subprocess.run(["git", "-C", str(ROOT), "grep", "-lF", marker, "--", "apps", "platform-base"],
                           capture_output=True, text=True).stdout
    return set(found.splitlines())


def main() -> int:
    fix = "--fix" in sys.argv
    bad = 0
    for blk in BLOCKS:
        src = ROOT / blk["source"]
        if not src.exists():
            print(f"FAIL  missing source: {blk['source']}")
            bad += 1
            continue
        # A file that carries a block's markers and is not a row above is a copy nobody keeps: this
        # gate passes over it for ever. notifications held the side menu's markup and behaviour
        # around an EMPTY style block for exactly that reason, so its menu was drawn as browser-
        # default controls above the page, at every width, in every office (found 2026-10-06 by
        # looking at the screen).
        for rel in sorted(carriers(blk["start"]) - set(blk["targets"]) - {blk["source"]}):
            print(f"FAIL  {rel}: carries {blk['start']} and is not listed under '{blk['name']}'")
            bad += 1
        want = region(src.read_text(encoding="utf-8"), blk["source"], blk["start"], blk["end"])
        # A sheet that a SCRIPT carries sits inside that script's template string, and may not end it:
        # one backtick in a comment of the palette did, and two servers' own files stopped parsing
        # while every copy was byte-identical (2026-10-09). A dollar-brace would be read as the script's.
        if blk["source"].endswith(".css") and any(t.endswith((".js", ".mjs")) for t in blk["targets"]):
            for n, line in enumerate(want.splitlines(), 1):
                if "`" in line or "${" in line:
                    print(f"FAIL  {blk['source']}: line {n} of the block holds a backtick or a dollar-brace — "
                          f"a script carries this block inside a template string, which that ends: {line.strip()[:70]}")
                    bad += 1
        for rel in blk["targets"]:
            p = ROOT / rel
            if not p.exists():
                print(f"FAIL  {rel}: file not found ({blk['name']})")
                bad += 1
                continue
            text = p.read_text(encoding="utf-8")
            try:
                got = region(text, rel, blk["start"], blk["end"])
            except LookupError as e:
                print(f"FAIL  {e}")
                bad += 1
                continue
            if got == want:
                print(f"ok    {rel}  ({blk['name']})")
                continue
            if fix:
                # newline="" on write: these files are checked in with LF and a rewrite must not
                # flip them to CRLF on Windows, which would show up as a whole-file diff.
                with p.open("w", encoding="utf-8", newline="") as fh:
                    fh.write(text.replace(got, want))
                print(f"fixed {rel}  ({blk['name']})")
            else:
                print(f"FAIL  {rel}: {blk['name']} drifted from {blk['source']}")
                bad += 1

    bad += check_fonts(fix)
    bad += check_vendored(fix)

    if bad:
        print(f"\n{bad} file(s) drifted. Re-sync with:\n"
              f"  python3 scripts/refactor/theme-token-lint.py --fix")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
