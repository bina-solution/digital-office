#!/usr/bin/env python3
"""build-handoff-mock — the single-file form of handoff-intent-mock (DGO-1434).

The source (`handoff-intent-mock.src.html`) LINKS the real stylesheets and the office's icon set, and
names the owner's pixels by path, which keeps it honest: it cannot drift from the palette or the
shell's own CSS, because it carries no copy of either. A person opens a single file from anywhere,
and a headless renderer shoots it without a web server, so this builder inlines them, verbatim:
  · every `<link rel="stylesheet">` and `<script src>` → inline (a `</script` inside is escaped);
  · every `../../ci-artifacts/handoff-mock/src/<file>` → a data: URI of that file;
  · `<!--@brand-->` → the office's mark, as platform-base/bina-ui/brand/mark.html draws it.

The output is a BUILD ARTIFACT under the gitignored ci-artifacts/: it carries the owner's own
screenshot (his addresses are on it) and copies of theme-tokens.css, which gate G27 keeps in one
place. Source tracked, output not.

    python3 digital-office/sim/build-handoff-mock.py          # → ci-artifacts/handoff-mock/handoff-mock.html
"""
from __future__ import annotations

import base64
import mimetypes
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
SRC = HERE / "handoff-intent-mock.src.html"
OUT = REPO / "ci-artifacts" / "handoff-mock" / "handoff-mock.html"
MARK = REPO / "platform-base" / "bina-ui" / "brand" / "mark.html"

LINK = re.compile(r'<link rel="stylesheet" href="(?P<href>[^"]+)"\s*/>')
SCRIPT = re.compile(r'<script src="(?P<src>[^"]+)"></script>')
PIXELS = re.compile(r'\.\./\.\./ci-artifacts/handoff-mock/src/(?P<name>[\w.-]+)')


def main() -> int:
    html = SRC.read_text(encoding="utf-8")

    def css(m: re.Match) -> str:
        p = (SRC.parent / m.group("href")).resolve()
        if not p.is_file():
            sys.exit(f"missing stylesheet: {m.group('href')}")
        return "<style>\n" + p.read_text(encoding="utf-8") + "\n</style>"

    def js(m: re.Match) -> str:
        p = (SRC.parent / m.group("src")).resolve()
        if not p.is_file():
            sys.exit(f"missing script: {m.group('src')}")
        return "<script>\n" + p.read_text(encoding="utf-8").replace("</script", "<\\/script") + "\n</script>"

    missing: list[str] = []

    def pixel(m: re.Match) -> str:
        p = REPO / "ci-artifacts" / "handoff-mock" / "src" / m.group("name")
        if not p.is_file():
            missing.append(m.group("name"))
            return m.group(0)
        mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode("ascii")

    html = LINK.sub(css, html)
    html = SCRIPT.sub(js, html)
    html = PIXELS.sub(pixel, html)
    if missing:
        sys.exit("missing pixels (cut them from the owner's shot first): " + ", ".join(sorted(set(missing))))
    mark = MARK.read_text(encoding="utf-8")
    svg = mark.split("<!-- @bina-brand:start -->", 1)[1].split("<!-- @bina-brand:end -->", 1)[0]
    html = html.replace("<!--@brand-->", svg)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"{OUT.relative_to(REPO)}  {OUT.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
