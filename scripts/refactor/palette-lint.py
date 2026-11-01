#!/usr/bin/env python3
"""palette-lint — gate G82: a screen names no colour of its own.

    python3 scripts/refactor/palette-lint.py [--self-test] [--update-baseline] [--files [PATH]]

WHY THIS GATE EXISTS

The office has ONE palette — «Olive Grove» — written once, in
`platform-base/bina-ui/theme-tokens.css`, and stamped into every screen (G27). The owner,
2026-10-07: "I want this to be the one and only color pallet for entire dgo ... every app that is
dgo built". On that day the screens named 2,815 colours of their own, 649 different ones, in 104
files: each app's private copy of an older palette, the tints it had mixed for itself, a "dark
theme" section that existed only to re-colour what a light literal had hard-coded, and canvases
that painted from hex strings. So changing the office's colours changed a part of what a person
saw, and the rest stayed whatever each file happened to say.

WHAT IT COUNTS

A colour LITERAL in a front-end source under `apps/` and `platform-base/`: `#rgb`, `#rrggbb`,
`#rrggbbaa`; `rgb()` / `rgba()` / `hsl()` / `hsla()` written with numbers; and the URL-encoded
`%23rrggbb` an inline SVG carries. A fallback counts too — `var(--line,#e3e8ec)` is a second
palette waiting for the day the token is missing. Not counted: a copy of a shared block (between
`@bina-<name>:start` and `:end` — it is its source's, and the source is counted once, in
`platform-base/bina-ui/`), and a colour BUILT at run time from a token (`"rgba(" + r + …`).
Colour NAMES (`white`, `black`) are not parsed: a mask's `black` is not a colour on the screen,
and nobody has yet written `tomato` here.

And what the SERVER draws or declares: a literal inside a STRING of a Python source (a comment
draws nothing — an issue number in one, `#1070`, is not a colour) and in a YAML declaration. The
sweep of the screens passed these by, and three of them were still in the colours of before:
the card the link's door answers with, telegram-tv's poster, INDOX's instance colours. There a
token often cannot be named — a picture, a QR code, a field of another program — so one of the
palette's own VALUES is not counted; any other colour is.

WHAT IS ALLOWED BY NAME (`ALLOWED` below — each with its reason; this is not debt)

  the palette itself      theme-tokens.css is where the colours ARE written
  the mark as an image    a favicon — a file, or an inline `rel="icon"` data URI — cannot name a token
  a QR code               black on white in every theme, or a camera does not read it
  somebody else's page    what browser42 draws INSIDE the page it shows, where no token exists
  somebody else's mark    a network's or a provider's tile is ITS colour (digital-assets, chat,
                          social-list's list of networks)
  a colour as DATA        the starting value of a colour field — the control takes only a literal
  paper                   an e-mail's own page, and the page that is printed: ink on white paper
  the screen of a film    telegram-tv's hero and player stand on black (one declaration, `--film`)
  inside another product  the agent harness's side menu and the office's mark on it: that page
                          carries no block and turns dark by its OWN switch, so the palette's
                          values are written for its two grounds (three lines of the brand plugin);
                          the colours of Plane's states and labels, and of a label in the forge:
                          a field of that product, and its own legend (hub ui2-040) — also where
                          a patch QUOTES them from Plane's bundle to find the words beside them
  a business document     what apitools prints for a business's customers: ink on paper, in a
                          palette of its own until the owner decides otherwise (hub ui2-039)

and vendored code (`vendor/`, `revo-grid/`, `*.min.*`), test fixtures, research and reports are
not a DGO-built screen at all, so they are not read.

THE BASELINE IS DEBT, NOT PERMISSION

`palette-baseline.json` records, per file, how many literals were there the last time the file
was recorded. The gate fails when a file's count RISES, when a file that had none names one, and
when a count has FALLEN without being recorded (`--update-baseline`, after a real clean-up) — so
the number only ever goes down, and never quietly creeps back up to an old ceiling. A new literal
is fixed by naming a token of the palette; if the palette lacks the role, the role is added THERE,
once. The baseline is never raised to let one in.
"""
import argparse
import collections
import io
import json
import pathlib
import re
import subprocess
import sys
import tokenize

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]
BASELINE = pathlib.Path(__file__).resolve().parent / "palette-baseline.json"

ROOTS = ("apps/", "platform-base/")
PALETTE = "platform-base/bina-ui/theme-tokens.css"
#: a screen's source — and what the server draws (.py) or declares (.yaml)
FRONT = re.compile(r"\.(html|css|js|mjs|jsx|ts|tsx|ejs|svg|vue|py|ya?ml)$")
SERVER = re.compile(r"\.(py|ya?ml)$")
#: not a DGO-built screen: somebody else's code, a test's stand-in for somebody else's page, a
#: document that is kept and not served
NOT_A_SCREEN = re.compile(
    r"(^|/)(vendor|node_modules|dist|dist-sim|__pycache__|tests?|fixtures?|blueprint|research|reports|diagrams|plans)/"
    r"|\.min\.|/revo-grid/|\.(test|spec)\.|(^|/)test_[^/]*\.py$|(^|/)ARCHITECTURE\.html$")

#: (path, line — or None for the whole file, reason). Allowed by NAME: none of these is debt.
ALLOWED = [
    (r"^platform-base/bina-ui/theme-tokens\.css$", None, "the palette: where the colours are written"),
    (r"(^|/)favicon\.svg$", None, "the mark as an image: a file cannot name a token"),
    (r"^platform-base/bina-ui/brand/.*\.svg$", None,
     "the office's mark as image files (the site's logo, the favicon): a file cannot name a token, "
     "and its three values ARE the palette's — olive, lime, the ground"),
    (r".", r"<link\b[^>]*\brel=[\"']icon[\"']", "the mark as an inline image: a data URI cannot name a token"),
    (r".", r"\.(qrwrap|cx-qr|qr-box)\b[^{}]*\{[^}]*background:#fff", "a QR code is read black on white, in every theme"),
    (r"^apps/telegram-tv/static/style\.css$", r"--film:#000;", "a film is shown on black, in a light office and in a dark one"),
    (r"^apps/dgo-extend/static/connect\.js$", r"(fillStyle|style\.background) = \"#(fff|000)\"", "a QR code is drawn black on white, in every theme"),
    (r"^apps/browser42/(browser-clipboard|extension/cursor)\.js$", None,
     "drawn inside the page the office's browser shows — somebody else's page, where no token exists"),
    (r"^apps/digital-assets/static/app\.js$", r"\b(facebook|instagram|youtube|github|discord|whatsapp|linkedin|tiktok|telegram|threads): '#",
     "a network's tile is the network's own colour — its mark, not the office's"),
    (r"^apps/chat/src/api/ui/chat\.ejs$", r"\bchat_(wa_baileys|tg_bot):\{", "a provider's tile is the provider's own colour — its mark"),
    (r"^apps/mail/mailview/static/index\.html$", r"\.(rp-body|thm-b) iframe\{[^}]*background:#fff",
     "an e-mail's own page stays on the white paper it was written for, in every theme"),
    (r"^apps/mail/mailview/static/index\.html$", r"^\s*body\{overflow:visible;background:#fff;color:#000\}", "the printed page: ink on paper"),
    (r"^apps/mail/mailview/static/app\.js$", r"<style>body\{font:14px|\.h\{color:#444", "the printed page: ink on paper"),
    (r"^apps/digital-assets/static/app\.js$", r"<input type=\"color\"",
     "a colour FIELD's starting value is data: the control takes a literal and nothing else"),
    (r"^apps/bina-ds/plugins/brand-bina/lib/client\.js$", r"--dsw-specific-sidebar-fill:|^\s*const MARK = ",
     "written INTO another product's page (the agent harness): it carries no token block, and its dark ground is its own switch"),
    (r"^apps/project-pln/(bootstrap\.(py|yaml)|plan\.py)$", None,
     "written INTO another product (Plane): the colours of its states and labels are its fields, and its own legend (ui2-040)"),
    (r"^apps/project-pln/patches/hebrew-strings\.py$", r"defaultStateName:`",
     "quoted FROM another product's bundle (Plane) to find the words beside it, and written back unchanged: its state groups' own colours"),
    (r"^apps/git/adapters/forge\.py$", r"\b_LABEL_COLOR = ", "a label's colour inside the forge: another product's field"),
    (r"^apps/social-list/platforms\.yaml$", r"^\s*color: \"#", "a network's tile is the network's own colour — its mark, not the office's"),
    (r"^apps/apitools/src/doc_gen/", None,
     "a business document: ink on paper, in a palette of its own until the owner decides otherwise (ui2-039)"),
]

BLOCK = re.compile(r"@(bina-[a-z-]+):start.*?@\1:end", re.S)
#: `#` + 3/4/6/8 hex digits that is a colour and not an id, an anchor or an entity: not after `&`
#: (`&#39;`), a word character or `/`; not `url(#…)` / `href="#…"`; and not followed by what follows
#: a selector (`#add{`, `#bed .row`, `#bed>.row`, `#fab[open]`, `#fab:hover`) or more of a name
#: (`#add-row`).
HEX = re.compile(r"(?<![&\w/])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![\w-])(?!\s*[{\[>~+]|\s*\.[A-Za-z_-]|:[A-Za-z])")
NOT_HEX_BEFORE = re.compile(r"(url\(\s*[\"']?|href\s*=\s*[\"']?|for\s*=\s*[\"']?"
                            r"|(?:\$|querySelector(?:All)?|closest|matches)\(\s*[\"'])$")   # $('#cAdd') is an id
FUNC = re.compile(r"\b(?:rgba?|hsla?)\(\s*[\d.]")           # written with numbers — not built from a token
ENCODED = re.compile(r"%23(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![0-9a-zA-Z])")


def own_block(rel: str, name: str) -> bool:
    """Is the block `name` WRITTEN in `rel` (its source, under bina-ui/) rather than copied into it?"""
    stem = pathlib.PurePosixPath(rel).stem
    return rel.startswith("platform-base/bina-ui/") and name in (stem, "bina-" + stem, stem + "-js")


def six(hexa: str) -> str:
    """`#fff` and `#FFFFFF` are one colour."""
    h = hexa.lstrip("#").lower()
    return "".join(c * 2 for c in h) if len(h) in (3, 4) else h


_VALUES = None


def palette_values() -> frozenset:
    """Every colour VALUE the palette writes — what a picture the server draws may write, and nothing else."""
    global _VALUES
    if _VALUES is None:
        _VALUES = frozenset(six(m.group(0)) for m in HEX.finditer((REPO / PALETTE).read_text(encoding="utf-8")))
    return _VALUES


def strings_only(source: str) -> str:
    """A Python source with everything but its string literals blanked, the line numbers kept."""
    rows = [""] * (source.count("\n") + 2)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type in (tokenize.STRING, getattr(tokenize, "FSTRING_MIDDLE", tokenize.STRING)):
                for i, part in enumerate(tok.string.split("\n")):
                    rows[tok.start[0] - 1 + i] += " " + part
    except (tokenize.TokenError, SyntaxError):
        return source                                   # not Python after all: read it as it is
    return "\n".join(rows)


def literals(rel: str, text: str):
    """-> [(line number, the literal)] — every colour literal `rel` writes itself."""
    # a copy of a block is its source's: blank it, keeping the line numbers
    text = BLOCK.sub(lambda m: m.group(0) if own_block(rel, m.group(1)) else "\n" * m.group(0).count("\n"), text)
    whole = [why for path, line, why in ALLOWED if line is None and re.search(path, rel)]
    if whole:
        return []
    by_line = [re.compile(line) for path, line, why in ALLOWED if line is not None and re.search(path, rel)]
    server = bool(SERVER.search(rel))
    rows = text.split("\n")
    # `row` is the line as it is written (what an allowance names); `seen` is what of it can reach a screen
    out = []
    for n, (row, seen) in enumerate(zip(rows, strings_only(text).split("\n") if rel.endswith(".py") else rows), 1):
        if "#" not in seen and "%23" not in seen and "rgb" not in seen and "hsl" not in seen:
            continue
        if any(rx.search(row) for rx in by_line):
            continue
        for m in HEX.finditer(seen):
            if server and six(m.group(0)) in palette_values():
                continue
            if not NOT_HEX_BEFORE.search(seen[:m.start()]):
                out.append((n, m.group(0)))
        out += [(n, m.group(0) + "…)") for m in FUNC.finditer(seen)]
        out += [(n, m.group(0)) for m in ENCODED.finditer(seen)]
    return out


#: Somebody else's component drawn INSIDE the office's screens, and the sheet that dresses it. A
#: variable the component reads and is not given falls back to the component's own colour, and it
#: shows where nobody looked: the office's tables drew black rows on the dark ground and a white
#: filter panel, with fifteen of the grid's variables never set (found 2026-10-07, by opening one).
GRID, GRID_SKIN = "platform-base/bina-ui/revo-grid", "platform-base/bina-ui/bina-table.css"
#: read by the grid and deliberately not given: the skin replaces the whole declaration that reads it
GRID_REPLACED = ("--revo-grid-shadow", "--revo-grid-filter-panel-shadow")


def not_given(component: str, skin: str) -> list:
    """The variables `component` (its sources, as one text) reads and `skin` never sets."""
    reads = set(re.findall(r"var\(\s*(--revo-grid-[\w-]+)", component))
    return sorted(v for v in reads if v not in GRID_REPLACED and not re.search(re.escape(v) + r"\s*:", skin))


def tracked():
    names = subprocess.run(["git", "-C", str(REPO), "ls-files", "--", *ROOTS], capture_output=True,
                           text=True, encoding="utf-8").stdout.splitlines()
    return [f for f in names if FRONT.search(f) and not NOT_A_SCREEN.search(f)]


def scan():
    """-> {relpath: [(line, literal)]} for every screen source that names a colour."""
    found = {}
    for rel in tracked():
        try:
            hits = literals(rel, (REPO / rel).read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if hits:
            found[rel] = hits
    return found


def self_test() -> int:
    stamped = "/* @bina-theme-tokens:start */\n:root{--ink:#1f2a17}\n/* @bina-theme-tokens:end */\n"
    cases = [
        ("a literal in a rule", "apps/x/static/index.html", "a{color:#fff}", 1),
        ("a fallback is a second palette", "apps/x/static/index.html", "a{color:var(--ink,#15202b)}", 1),
        ("eight digits, and an rgba with numbers", "apps/x/static/a.css", "a{color:#11223344;background:rgba(0,0,0,.5)}", 2),
        ("hsl with numbers", "apps/x/static/a.css", "a{color:hsl(120 50% 50%)}", 1),
        ("an inline SVG's encoded colour", "apps/x/static/a.css", "a{background:url(\"data:image/svg+xml,%3Csvg fill='%230e9f6e'/%3E\")}", 1),
        ("a copy of a shared block is its source's", "apps/x/static/index.html", stamped + "a{color:var(--ink)}", 0),
        ("…but the block's source is counted", "platform-base/bina-ui/bina-page.css", "/* @bina-page:start */\na{color:#fff}\n/* @bina-page:end */", 1),
        ("…and a copy that sits beside the sources is still a copy", "platform-base/bina-ui/bina-ui.css", stamped + "a{color:var(--ink)}", 0),
        ("a script's own block (its marker says -js)", "platform-base/bina-ui/bina-nav.js", "/* @bina-nav-js:start */\nvar c = \"#fff\";\n/* @bina-nav-js:end */", 1),
        ("the palette itself is where colours are written", "platform-base/bina-ui/theme-tokens.css", ":root{--ink:#1f2a17}", 0),
        ("a colour built from a token at run time", "apps/x/static/app.js", 'const c = "rgba(" + r + "," + g + ")"; const d = `rgba(${n},1)`;', 0),
        ("an id selector made of hex letters", "apps/x/static/a.css", "#add{display:none} #bed .row{margin:0} #fab[open]{top:0} #add-row{left:0}", 0),
        ("an anchor, an entity, an SVG reference", "apps/x/static/index.html", '<a href="#fade">x</a> &#39; &#x27; <rect fill="url(#bad)"/>', 0),
        ("an id handed to a selector call", "apps/x/static/app.js", "$('#cAdd').onclick = f; document.querySelector(\"#fade\").remove();", 0),
        ("…while a colour handed to a style is one", "apps/x/static/app.js", "el.style.color = '#cadd';", 1),
        ("a favicon's inline image", "apps/x/static/index.html", "<link rel=\"icon\" href=\"data:image/svg+xml,%3Csvg fill='%2356693f'/%3E\">", 0),
        ("a QR code's white ground", "platform-base/console/static/style.css", ".qrwrap{display:flex;background:#fff}", 0),
        ("…and nothing else may borrow that reason", "platform-base/console/static/style.css", ".card{display:flex;background:#fff}", 1),
        ("the office's values inside another product's page", "apps/bina-ds/plugins/brand-bina/lib/client.js",
         "body{--dsw-specific-sidebar-fill:#f9fafb;--dsw-specific-sidebar-nav-item-hover:#eceeed}\n\t\tconst MARK = { background: \"#56693f\", color: \"#f3f5f7\" };", 0),
        ("…and the rest of that plugin still names none", "apps/bina-ds/plugins/brand-bina/lib/client.js", "tag.style.color = \"#fff\";", 1),
        ("another product's own colours, quoted from its bundle to find the words beside them", "apps/project-pln/patches/hebrew-strings.py",
         "P = [(\"{backlog:{key:`backlog`,label:`Backlog`,defaultStateName:`Backlog`,color:`#d9d9d9`}\",\n"
         "      \"{backlog:{key:`backlog`,label:`מלאי`,defaultStateName:`מלאי`,color:`#d9d9d9`}\", 1)]", 0),
        ("…and the rest of that patch still names none", "apps/project-pln/patches/hebrew-strings.py", "CSS = \".chip{color:#3f76ff}\"", 1),
        ("a token is not a literal", "apps/x/static/index.html", "a{color:var(--ink);box-shadow:0 0 0 1px var(--line)}", 0),
        ("a picture the server draws writes the palette's VALUE (it cannot name a token)", "apps/x/app.py",
         "SVG = '<rect fill=\"#56693f\"/><text fill=\"#FFF\">x</text>'", 0),
        ("…and any other colour there is one of its own", "apps/x/app.py", "SVG = '<rect fill=\"#0e9f6e\"/>'\nQR = dict(dark=\"#000\")", 2),
        ("…in an f-string and over several lines too", "apps/x/app.py", "CARD = f'''<style>\nbody{{background:#101010;color:{ink}}}\n</style>'''", 1),
        ("a comment in server code draws nothing", "apps/x/app.py", "# upstream issue #1070, and the bar \"#457571 webhook\"\nx = 1  # see #abc", 0),
        ("…while a front-end source may not write even the palette's value", "apps/x/static/app.js", "el.style.color = '#56693f';", 1),
        ("a colour a manifest declares", "apps/x/platforms.yaml", "- id: own\n  color: \"#6b4d9c\"\n- id: own2\n  color: \"var(--olive)\"", 1),
        ("a network's mark in the networks' list", "apps/social-list/platforms.yaml", "  - id: facebook\n    color: \"#1877f2\"", 0),
    ]
    ok = 0
    for name, rel, text, want in cases:
        got = len(literals(rel, text))
        ok += got == want
        print(f"  [{'ok ' if got == want else 'BAD'}] counted {got} (must be {want}): {name}")
    skipped = [f for f in ("apps/x/static/vendor/grid.css", "platform-base/bina-ui/revo-grid/a.entry.js",
                           "apps/x/static/fixture/panel.html", "apps/x/research/notes.html", "apps/x/static/app.min.js",
                           "apps/x/test_app.py", "apps/x/tests/test_page.py", "apps/x/blueprint/n8n/mail.yaml")
               if FRONT.search(f) and not NOT_A_SCREEN.search(f)]
    ok += not skipped
    print(f"  [{'ok ' if not skipped else 'BAD'}] vendored code, fixtures, tests and research are not read{': ' + ', '.join(skipped) if skipped else ''}")
    want = ("apps/drive/static/index.html", "platform-base/console/static/style.css", "apps/chat/src/api/ui/login.ejs",
            "apps/dgo-extend/link-proxy.py", "apps/social-list/platforms.yaml")
    read = [f for f in want if FRONT.search(f) and not NOT_A_SCREEN.search(f)]
    ok += len(read) == len(want)
    print(f"  [{'ok ' if len(read) == len(want) else 'BAD'}] a screen's page, stylesheet and template are read — and the server's source and a manifest")
    grid = "a{color:var(--revo-grid-text)}b{box-shadow:0 0 1px var( --revo-grid-shadow, #000)}c{background:var(--revo-grid-background,#fff)}"
    for name, skin, want in (
            ("a variable the grid reads and the skin does not set", ".bina-table revo-grid{--revo-grid-background:var(--surface)}", ["--revo-grid-text"]),
            ("…every one set (a shadow the skin replaces whole is not asked for)",
             ".bina-table revo-grid{--revo-grid-background:var(--surface);--revo-grid-text:var(--ink)}", [])):
        got = not_given(grid, skin)
        ok += got == want
        print(f"  [{'ok ' if got == want else 'BAD'}] not given: {got} (must be {want}): {name}")
    total = len(cases) + 4
    print(f"\nG82 self-test: {ok}/{total} passed")
    return 0 if ok == total else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--files", nargs="?", const="", metavar="PATH",
                    help="list every counted literal with its line (all files, or those under PATH)")
    a = ap.parse_args()
    if a.self_test:
        return self_test()

    found = scan()
    counts = {rel: len(hits) for rel, hits in sorted(found.items())}
    total = sum(counts.values())
    if a.files is not None:
        for rel, hits in sorted(found.items()):
            if rel.startswith(a.files):
                for n, lit in hits:
                    print(f"{rel}:{n}: {lit}")
        return 0
    if a.update_baseline:
        BASELINE.write_text(json.dumps(counts, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
        print(f"G82 baseline recorded: {total} colour literal(s) in {len(counts)} file(s) -> {BASELINE.relative_to(REPO)}")
        return 0

    base = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {}
    btotal = sum(base.values())
    up = [f"{rel}: {base.get(rel, 0)} -> {n}" for rel, n in counts.items() if n > base.get(rel, 0)]
    down = [f"{rel}: {n} -> {counts.get(rel, 0)}" for rel, n in sorted(base.items()) if counts.get(rel, 0) < n]
    if up:
        print("G82 FAIL — a screen names a colour of its own:")
        for row in up:
            print(f"  {row}")
        print("\n  The office has one palette (platform-base/bina-ui/theme-tokens.css). Name one of its\n"
              "  tokens instead — `python3 scripts/refactor/palette-lint.py --files <path>` lists the\n"
              "  literals with their lines. If the palette lacks the role, add the role THERE, once.")
        return 1
    if down:
        print(f"G82 FAIL — the baseline is stale ({btotal} recorded, {total} found): colours were taken out and\n"
              f"  the lower count was not recorded, so the old ceiling still stands. Record it:\n"
              f"    python3 scripts/refactor/palette-lint.py --update-baseline")
        for row in down[:12]:
            print(f"  {row}")
        return 1
    grid = "".join(f.read_text(encoding="utf-8", errors="replace") for f in sorted((REPO / GRID).glob("*.js")))
    if not grid:
        print(f"G82 FAIL — the vendored grid was not found at {GRID}: what it reads cannot be checked.")
        return 1
    bare = not_given(grid, (REPO / GRID_SKIN).read_text(encoding="utf-8"))
    if bare:
        print(f"G82 FAIL — the grid ({GRID}) is drawn inside the office's screens, and {GRID_SKIN} does not\n"
              f"  give it {len(bare)} of the variables it reads, so there it paints in its OWN colours:")
        for v in bare:
            print(f"  {v}")
        print("\n  Set each on `.bina-table revo-grid` to a token of the palette — and open a table's filter\n"
              "  panel and drag a range on the dark ground before calling it done.")
        return 1
    print(f"G82 PASS — {total} colour literal(s) left in {len(counts)} file(s), each within what was recorded; "
          f"no screen names a new one, and the grid is given every variable it reads.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
