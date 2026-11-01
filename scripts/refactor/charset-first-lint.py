#!/usr/bin/env python3
"""charset-first-lint — every served page must declare its charset in the first bytes of <head>.

    python3 scripts/refactor/charset-first-lint.py

Mobile browsers decide a document's encoding by sniffing roughly the first 1024 bytes. A
`<meta charset="utf-8">` that appears after that window is not late — it is ignored, and the page is
decoded with the browser's fallback. For a Hebrew UI that means mojibake on phones while every
desktop browser renders it perfectly, which is precisely the shape of bug that survives review: it
cannot be seen on the machine it was written on.

This was found in the simulation, where the meta sat at byte ~65726 because a large inline <style>
preceded it. The same mistake is available to every page this platform serves, so it is checked
rather than remembered.

The rule, deliberately stricter than "somewhere in the head": the charset declaration must be the
FIRST element inside <head>. HTML5 requires it within the first 1024 bytes; putting it first is the
only version of that rule a human can verify by looking, and it costs nothing.
"""
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]

# Served pages only. The sim is excluded: it is not shipped, and it has its own build-time emitter.
ROOTS = [
    "apps/*/static/*.html",
    "apps/*/*/static/*.html",
    "apps/*/src/api/ui/*.ejs",
    "apps/indox/app/webapp/index.html",
    "platform-base/*/static/*.html",
    "platform-base/*/*.html",
]
SKIP_PARTS = ("node_modules", "dist", "legacy", "digital-office", "ci-artifacts", ".generated")

HEAD_OPEN = re.compile(r"<head[^>]*>", re.I)
CHARSET = re.compile(r'<meta[^>]+charset', re.I)
# comments and whitespace may precede the meta without pushing it past the sniff window
LEADING_NOISE = re.compile(r"^(?:\s|<!--.*?-->)*", re.S)


def check(path):
    """(ok, detail). Pages with no <head> at all are not served documents — skipped, not failed."""
    try:
        raw = path.read_bytes()
    except OSError as e:
        return True, "unreadable: %s" % e
    text = raw.decode("utf-8", "replace")
    m = HEAD_OPEN.search(text)
    if not m:
        return None, "no <head>"
    after = text[m.end():]
    cm = CHARSET.search(after)
    if not cm:
        return False, "no <meta charset> at all"
    # byte offset of the declaration in the real file, which is what the browser sniffs
    byte_off = len(text[: m.end() + cm.start()].encode("utf-8"))
    first = LEADING_NOISE.match(after).end()
    if cm.start() != first:
        return False, "not first in <head> (byte %d; %d chars of markup precede it)" % (byte_off, cm.start() - first)
    if byte_off > 1024:
        return False, "first in <head> but at byte %d, past the ~1024-byte sniff window" % byte_off
    return True, "byte %d" % byte_off


def main():
    seen, bad = [], []
    for pattern in ROOTS:
        for p in REPO.glob(pattern):
            if any(part in p.as_posix() for part in SKIP_PARTS):
                continue
            if p in seen:
                continue
            seen.append(p)
            ok, detail = check(p)
            if ok is None:
                continue
            rel = p.relative_to(REPO).as_posix()
            if ok:
                print("  ok    %-58s %s" % (rel, detail))
            else:
                bad.append((rel, detail))

    for rel, detail in bad:
        print("  FAIL  %-58s %s" % (rel, detail))
    print("\n%d page(s) checked, %d failing" % (len(seen), len(bad)))
    if bad:
        print("\nFix: make <meta charset=\"utf-8\"> the first element inside <head>.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
