#!/usr/bin/env python3
"""menu-host-lint — gate G107: the side menu stands in the component's grid, and no page sizes it itself.

    python3 scripts/refactor/menu-host-lint.py
    python3 scripts/refactor/menu-host-lint.py --self-test

WHY. The owner's product review of Exampleu's office (2026-11-09, DGO-1591): «חצי תפריט … לא נפתח, לא נסגר …
באג מזעזע … ראיתי את זה כבר כמה פעמים בכמה מקומות». Measured on the live office: at 600–839px of its frame the
Sites menu was the component's rail — the names hidden — in a box 238px wide and 119px tall, with nothing that
opened it. The component (platform-base/bina-ui/bina-nav.css) decides the menu's column through its host
contract — `.bnv-host` › `.appgrid` › the menu + the page, `--bnv-side`: the whole menu, a 56/64px rail, a
drawer — and «an app that keeps its own grid-template-columns:252px 1fr opts out of every size behaviour». Six
pages had kept a flex row of their own with the menu at 238/252px: sites, domains, social-list, connections,
telegram-tv, and INDOX's React shell. The component cannot fix a host that does not ask; this gate is what
asks.

WHAT IT CHECKS, in every tracked page (*.html; legacy/, ci-artifacts/ and the digital-office/ workbench aside)
whose markup holds a menu (an element with the class `bnv`, outside a <template>):
  1. the menu's parent element has the class `appgrid` (the component's column), and an element ABOVE that grid
     has `bnv-host` (the container the sizes ask: a container cannot query itself, so a host put on the grid
     leaves `--bnv-side` unanswered while the menu's rail styles still apply — the half menu again);
  2. the page's own styles — its <style> elements and the local stylesheets it links, the component's stamped
     block (@bina-nav:start…end) and CSS comments taken out — size neither the menu nor its grid: no rule whose
     subject is the menu (any of its classes, `.bnv` included, its #id, or its tag) sets width, max-width,
     min-width (other than 0), flex, flex-basis or inline-size, no `.appgrid` rule sets grid-template-columns
     (the opt-out the component names), and the menu carries no such inline style. A box the app sizes is a box
     the rail cannot narrow.
A menu written in JSX (INDOX's webapp) is not read here: a page that builds its menu in script is named by its
own app. KNOWN: the pages below, each with why — debt, not permission: a page may not join the list, and one
that stops offending fails until its line goes (the list only shrinks). A scan that reads no menu FAILS.
"""
from __future__ import annotations

import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

# It prints Hebrew (G10): python on Windows writes it in the console's codepage and dies on its own output.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]

#: The pages that still keep a shell of their own, each with why — remove a line when its page is fixed.
KNOWN: dict[str, str] = {
    # [2026-11-20] the console LEFT this list: it has no side menu any more — a computer is the desk, and the phone's
    # shell navigates by its home and its bar (DGO-2132).
}

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
#: elements whose start closes an open <p> (the HTML parser's implied end tag): without it, a stray <p> before
#: the menu would read as the menu's parent
CLOSES_P = {"address", "article", "aside", "blockquote", "details", "div", "dl", "fieldset", "figure", "footer",
            "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "main", "menu", "nav", "ol", "p", "pre",
            "section", "table", "ul"}
SIZE = re.compile(r"(?<![\w-])(width|max-width|flex|flex-basis|inline-size)\s*:|(?<![\w-])min-width\s*:\s*(?!0(px)?\s*(;|!|$))")
GRID = re.compile(r"(?<![\w-])grid-template-columns\s*:")
STAMP = re.compile(r"/\*\s*@bina-nav:start\s*\*/.*?/\*\s*@bina-nav:end\s*\*/", re.S)
COMMENT = re.compile(r"/\*.*?\*/", re.S)
RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")


class Menus(HTMLParser):
    """The menus of a page (an element whose class list holds `bnv`), each with its parent's classes and
    whether a `bnv-host` stands above that parent; the text of the page's <style> elements; its stylesheets."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, list[str]]] = []
        # (its classes, its id, its tag, its inline style, its parent's classes, a host above the parent, line)
        self.menus: list[tuple[list[str], str, str, str, list[str], bool, int]] = []
        self.styles: list[str] = []
        self.links: list[str] = []
        self._in_style = False
        self._template = 0

    def _menu(self, tag, attrs):
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        if "bnv" in classes and not self._template:
            parent = self.stack[-1][1] if self.stack else []
            host = any("bnv-host" in c for _, c in self.stack[:-1])
            self.menus.append((classes, a.get("id") or "", tag, a.get("style") or "", parent, host, self.getpos()[0]))
        return classes

    def handle_starttag(self, tag, attrs):
        if tag in CLOSES_P and self.stack and self.stack[-1][0] == "p":
            self.stack.pop()
        a = dict(attrs)
        if tag == "link" and "stylesheet" in (a.get("rel") or "").lower().split() and a.get("href"):
            self.links.append(a["href"])
        classes = self._menu(tag, attrs)
        if tag == "template":
            self._template += 1
        if tag == "style":
            self._in_style = True
            self.styles.append("")
        if tag not in VOID:
            self.stack.append((tag, classes))

    def handle_startendtag(self, tag, attrs):
        self._menu(tag, attrs)

    def handle_endtag(self, tag):
        if tag == "style":
            self._in_style = False
        if tag == "template" and self._template:
            self._template -= 1
        for i in range(len(self.stack) - 1, -1, -1):   # pop to the matching tag: a stray close never drifts it
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self._in_style and self.styles:
            self.styles[-1] += data


def own_css(text: str) -> str:
    """A page's own CSS: the component's stamped block and every comment taken out."""
    return COMMENT.sub(" ", STAMP.sub(" ", text))


def subject(selector: str) -> str:
    """The compound a selector styles (its last one), negations dropped: `.shell > .side:not(.x)` → `.side`."""
    sel = re.sub(r":(not|is|where|has)\([^)]*\)", "", selector.strip())
    parts = re.split(r"\s*[>+~]\s*|\s+", sel)
    return parts[-1] if parts else ""


def targets(compound: str, classes: list[str], ident: str, tag: str) -> bool:
    if any(re.search(r"\." + re.escape(c) + r"(?![\w-])", compound) for c in classes if not c.startswith("is-")):
        return True
    if ident and re.search(r"#" + re.escape(ident) + r"(?![\w-])", compound):
        return True
    return bool(re.match(re.escape(tag) + r"(?![\w-])", compound))


def check(text: str, linked: str = "") -> tuple[int, list[str]]:
    """(menus read, problems) for one page's text; `linked` is the CSS of the local stylesheets it links."""
    p = Menus()
    p.feed(text)
    problems = []
    css = own_css("\n".join(p.styles) + "\n" + linked)
    rules = [(sel, body) for sels, body in RULE.findall(css) for sel in sels.split(",") if sel.strip()
             and not sel.strip().startswith("@")]
    for classes, ident, tag, style, parent, host, line in p.menus:
        if "appgrid" not in parent:
            problems.append(f"line {line}: the menu's parent is `{' '.join(parent) or '(none)'}`, not `.appgrid` — "
                            f"the component's column (bina-nav.css: `.bnv-host` › `.appgrid` › the menu)")
        elif not host:
            problems.append(f"line {line}: no `.bnv-host` above the menu's `.appgrid` — the container its sizes ask "
                            f"(a container cannot query itself: `--bnv-side` would never be answered)")
        if SIZE.search(style):
            problems.append(f"line {line}: the menu carries a size of its own — style=\"{style.strip()[:80]}\"")
        for sel, body in rules:
            if targets(subject(sel), classes, ident, tag) and SIZE.search(body):
                problems.append(f"line {line}: the page sizes its menu itself — `{sel.strip()[:60]}{{{body.strip()[:80]}}}`")
                break
    if p.menus:
        for sel, body in rules:
            if re.search(r"\.appgrid(?![\w-])", subject(sel)) and GRID.search(body):
                problems.append(f"the page sets the menu's grid itself — `{sel.strip()[:60]}{{{body.strip()[:80]}}}` "
                                f"(the component's column is `--bnv-side`; its own columns opt out of every size)")
                break
    return len(p.menus), problems


def linked_css(page: Path, text: str) -> str:
    """The local stylesheets a page links (an app serves `static/x.css` beside or under its page)."""
    p = Menus()
    p.feed(text)
    out = []
    for href in p.links:
        if re.match(r"^(https?:)?//|^data:", href):
            continue
        href = href.split("?")[0].split("#")[0].lstrip("/")
        for base in (page.parent, page.parent.parent):
            f = base / href
            if f.is_file():
                try:
                    out.append(f.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError):
                    pass
                break
    return "\n".join(out)


def pages() -> list[str]:
    out = subprocess.run(["git", "ls-files", "*.html"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    # digital-office/ is the dev-only UI workbench (mocks of screens, not a layer): an office serves none of it
    return [f for f in out.splitlines() if not f.startswith(("legacy/", "ci-artifacts/", "digital-office/"))]


def main() -> int:
    files = pages()
    read = menus = 0
    failed = []
    offending = set()
    for f in files:
        try:
            text = (ROOT / f).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        read += 1
        n, problems = check(text, linked_css(ROOT / f, text) if "bnv" in text else "")
        menus += n
        if problems:
            offending.add(f)
            if f not in KNOWN:
                failed += [f"{f} {p}" for p in problems]
    for f, why in KNOWN.items():
        if f not in offending:
            failed.append(f"{f} no longer offends (or is gone): remove its line from KNOWN — the list only shrinks")
    print(f"menu-host-lint: {read} page(s) read, {menus} menu(s) in their markup, {len(offending)} keep a shell of their own "
          f"({len(KNOWN)} known)")
    if menus == 0:
        print("G107 FAIL — no menu read in any page: the scan found nothing, which is not a pass")
        return 1
    for line in failed:
        print("  FAIL", line)
    if failed:
        print("G107 FAIL — the side menu must stand in the component's grid (.bnv-host › .appgrid) and be sized by it "
              "alone (DGO-1591)")
        return 1
    print("G107 PASS — every menu in a page's markup stands in the component's grid, and no page sizes it")
    return 0


def self_test() -> int:
    host = '<div class="shell bnv-host"><div class="appgrid">{menu}<main></main></div></div>'
    menu = '<aside class="side bnv" id="sideNav"><div class="bnv-head"></div></aside>'
    stamp = "/* @bina-nav:start */ .bnv{width:252px} /* @bina-nav:end */"

    def page(css, body=None):
        return f"<style>{css}</style>" + (body if body is not None else host.format(menu=menu))
    cases = [
        (page(".shell .side{border-inline-end:1px solid red}" + stamp), 1, 0, "a menu in .appgrid, unsized (the stamp aside)"),
        (page("/* was .side{width:238px} */ .shell .side{min-width:0}"), 1, 0, "a comment and min-width:0 are not sizes"),
        (page("") + '<template><aside class="side bnv"></aside></template>', 1, 0, "a <template> mock is not a menu"),
        (page("", '<div class="bnv-host"><div class="appgrid"><p>intro' + menu + '<main></main></div></div>'), 1, 0,
         "an unclosed <p> before the menu is not its parent"),
        (page(".shell{display:flex}", '<div class="shell"><aside class="side bnv"></aside><main></main></div>'), 1, 1,
         "a menu in a flex row of its own"),
        (page(".shell .side{flex:none;width:238px}"), 1, 1, "a menu the page sizes by its class"),
        (page(".shell .bnv{width:238px}"), 1, 1, "…by the component's own class"),
        (page(".side,.x{width:238px}"), 1, 1, "…in a selector list"),
        (page(".side:not(.x){width:238px}"), 1, 1, "…with a negation"),
        (page("#sideNav{width:238px}"), 1, 1, "…by its id"),
        (page("aside{flex-basis:238px}"), 1, 1, "…by its tag"),
        (page("", host.format(menu='<aside class="side bnv" style="width:238px"></aside>')), 1, 1, "…inline"),
        (page("", '<div class="shell"><div class="appgrid bnv-host">' + menu + '<main></main></div></div>'), 1, 1,
         "a grid with no host above it (a container cannot query itself)"),
        (page(".shell .appgrid{grid-template-columns:252px 1fr}"), 1, 1, "a grid with columns of the page's own"),
    ]
    bad = 0
    for text, n_want, want, what in cases:
        n, problems = check(text)
        got = 1 if problems else 0
        if n != n_want or got != want:
            print(f"  self-test FAIL: {what}: {n} menu(s), {len(problems)} problem(s), want {n_want} menu(s) and "
                  f"{'a failure' if want else 'none'} — {problems[:1]}")
            bad += 1
    passes = sum(1 for c in cases if not c[2])
    print("menu-host-lint self-test:", "FAIL" if bad else
          f"PASS ({len(cases)} cases: {passes} pass, {len(cases) - passes} are caught)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv[1:] else main())
