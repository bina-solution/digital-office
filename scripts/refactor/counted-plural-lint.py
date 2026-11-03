#!/usr/bin/env python3
"""counted-plural-lint — gate G89: a count of one is said as one.

    python3 scripts/refactor/counted-plural-lint.py             # exit 1 on a finding
    python3 scripts/refactor/counted-plural-lint.py --self-test
    python3 scripts/refactor/counted-plural-lint.py --files     # list what it reads
    python3 scripts/refactor/counted-plural-lint.py --update-baseline   # after a real fix

WHY THIS EXISTS. The owner read «רפאל: 1 קונטיינרים לא בריאים» in an alert (DGO-526) and «1 פריטים»
three times in INDOX's sync screen (DGO-530) — two items, one defect: a count glued to a fixed plural.
It is the defect a reader notices last and a writer never sees, because the sentence is only wrong at
exactly one value, and the value that is wrong is the one a fresh office is most likely to be in.
The rule is not new here: `apps/mail/mailview/static/app.js` writes it out —

    /* ONE IS SAID AS ONE … A count of one is its own sentence, which only the place that says it
       knows; any other is the number, written as the office writes a number, and the plural. */
    const num = n => Number(n).toLocaleString("he-IL");
    const one = (n, single, many) => (Number(n) === 1 ? single : `${num(n)} ${many}`);

— and this gate is what keeps the rest of the tree to it. The scan that produced it (2026-10-10) found
FIFTEEN sites in five files: the console's desktop mode («נפתחו 1 יישומים», «עוד 1 אפליקציות»), the
desktop's memory («טבלה · 1 פריטים»), raphael's collector («לפני 1 שניות»), sites («לפני 1 שניות»),
telegram-tv («1 סרטים · 1 סדרות», «נותרו 1 צ׳אטים») — every one of them a sentence a person reads.

WHAT IT LOOKS FOR. A Hebrew plural word (…ים / …ות, a geresh allowed: צ׳אטים) that is the first word of
a string literal or template directly AFTER a count expression:

    '… ' + bad.length + ' קונטיינרים לא בריאים'        →  a finding
    `${count} פריטים`                                   →  a finding
    one(n, 'קונטיינר אחד', 'קונטיינרים')                 →  not: the count picks its own sentence
    n === 1 ? 'פריט אחד' : n + ' פריטים'                 →  not: the branch is there

EXEMPTION IS LOCAL AND DELIBERATE: the singular branch has to be in the same expression or within a
few lines above it. A `one(` three screens away does not make this sentence right, and a gate that
guessed otherwise would be exempting every file that happens to hold one correct sentence.

SCOPE. Files a person reads copy from: a screen's own file (`static/**`, `ui.html`), a blueprint's
`jsCode` (an n8n notice is read by a person), and a compiled front-end's sources. `vendor/`, the shared
blocks' sources (kept by G27), `legacy/` and comments are not read — the comment that documents a fix
quotes the sentence it removed. A scan that finds no file at all FAILS: green and blind look alike.

THE BASELINE IS DEBT, NOT PERMISSION. `counted-plural-baseline.json` records, per file, how many sites
were there the last time it was recorded — G82's shape. The gate fails when a file's count RISES, when a
file that had none glues one, and when a count has FALLEN without being recorded (`--update-baseline`,
after a real fix) — so the number only ever goes down. It is recorded because the class is wide (44
sites in 10 apps on 2026-10-10) and a gate that arrives red is a gate that gets switched off; the
console's own screens were fixed in the commit that landed this, and the rest is a list to work through.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
import tempfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]
BASELINE = pathlib.Path(__file__).resolve().parent / "counted-plural-baseline.json"

HE = "\u0590-\u05ff"
#: a Hebrew plural: letters ending in ים or ות, with an optional geresh inside (צ׳אטים, ג׳ובות)
PLURAL = re.compile(rf"[{HE}][{HE}׳']{{1,}}(?:ים|ות)")
#: WHAT MAY SIT IMMEDIATELY BEFORE THE NOUN — a COUNT and, between it and the noun, nothing but a quote
#: and spaces. TWO SHAPES ARE COUNTS AND THE REST IS NOT, because this gate's first draft accepted any
#: `+ <expr> +` and reported 148 places, most of them a string: `${mIcon("shield")} הערכים נשמרים…`
#: has an ICON before the noun, and `'a' + svcName + ' חשבונות'` has a name. A call is not a count, and
#: neither is any expression but these. Measured against the tree: the precise form finds the real
#: sentences (DGO-526's and DGO-530's among them) and nothing else.
SIZEY = r"[A-Za-z_$][\w.$\[\]()]*\.(?:length|size|count|total|n)\b"
#: A COUNT WRAPPED FOR DISPLAY. The sync screen writes its number with its own formatter —
#: `${he(r.count)} פריטים` — and the first version of this gate saw the bare `n` and not the wrapped
#: one, so the three hints DGO-530 was opened about were the three it could not see (the parallel
#: session caught that; the note is in .claude/from-azaria.md). `he`/`num`/`fmt` are this tree's names
#: for "the number as the office writes numbers".
WRAPPED = r"(?:he|heNum|num|fmt|formatNumber|Number|toLocaleString)\s*\([^()]{1,60}\)"
COUNT_BEFORE = re.compile(
    #  x.length + ' ם…'   ·   x.items.length + " ם…"
    rf"(?:\+\s*(?:{SIZEY}|{WRAPPED}|\d+)\s*\+\s*['\"`]?\s*"
    #  `${x.length} ם…`  ·  `${rows.length} ם…`
    rf"|\$\{{\s*(?:{SIZEY}|{WRAPPED}|\d+)\s*\}}\s*['\"`]?\s*"
    #  `${n} ם…` — a bare number variable is a count (`s` seconds, `n` windows); nothing else.
    rf"|\$\{{[A-Za-z_$][\w$]*\}}\s*['\"`]?\s*"
    rf"|\+\s*[A-Za-z_$][\w$]*\s*\+\s*['\"`]?\s*"
    #  `{total} ם…` — JSX text: the same sentence with no quote in it at all (INDOX's sync screen,
    #  `<span>{total} פריטים</span>`). Its first version missed it, which is one of the three hints
    #  the owner counted in DGO-530.
    rf"|\{{\s*(?:{SIZEY}|{WRAPPED}|\d+|[A-Za-z_$][\w$]*)\s*\}}\s*['\"`]?\s*)$"
)
#: a singular branch: the count has its OWN sentence — `=== 1`, `> 1` (the drive picks its wording
#: with "more than one"), `one(`, or the Hebrew word. What the branch says is the writer's business;
#: that it exists for one is this gate's.
SINGULAR = re.compile(r"===\s*1\b|==\s*1\b|>\s*1\b|<=?\s*2\b|<=?\s*1\b|\bone\s*\(|אחד\b|אחת\b|single", re.U)
#: a NAME IN CAPITALS is a constant, not a count: `${PREVIEW_N} ההודעות האחרונות` is one sentence by
#: design (the number never moves). A live count is a property (`.length`) or a lower-case name.
CONSTANT = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")
_COMMENT = re.compile(r"/\*.*?\*/|<!--.*?-->|(?<=\s)//[^\n]*|^//[^\n]*", re.M | re.S)

SAYS = ("a count is glued to a fixed plural — one is said as one: "
        "`const one = (n, single, many) => (n === 1 ? single : num(n) + ' ' + many)` "
        "(see apps/mail/mailview/static/app.js)")


def const_name(tail: str) -> str:
    """The bare `${NAME}` right before the noun, when that is the shape — '' otherwise."""
    m = re.search(r"\$?\{\s*([A-Za-z_$][\w$]*)\s*\}\s*['\"`]?\s*$", tail) or \
        re.search(r"\$?\{\s*(?:he|heNum|num|fmt|formatNumber|Number|toLocaleString)\s*\(\s*([A-Za-z_$][\w$]*)\s*\)\s*\}\s*['\"`]?\s*$", tail)
    return m.group(1) if m else ""


def findings(source: str) -> list[tuple[int, str, str]]:
    """(line, word, the sentence around it) for every count glued to a fixed plural."""
    code = _COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), source)   # keep the line numbers
    out: list[tuple[int, str, str]] = []
    lines = code.splitlines()
    for m in PLURAL.finditer(code):
        head = code[:m.start()]
        tail = head[-80:]
        # the count has to be the thing just before the noun — nothing but a quote and spaces between
        if not COUNT_BEFORE.search(tail):
            continue
        if CONSTANT.match(const_name(tail)):
            continue
        line_no = code.count("\n", 0, m.start()) + 1
        window = "\n".join(lines[max(0, line_no - 4):line_no + 1])
        if SINGULAR.search(window):
            continue
        out.append((line_no, m.group(0), lines[line_no - 1].strip()[:150]))
    # one finding per line: the same sentence counted twice is one thing to fix
    seen: set[int] = set()
    return [f for f in out if not (f[0] in seen or seen.add(f[0]))]


def read_files(repo: pathlib.Path) -> list[pathlib.Path]:
    names = subprocess.run(["git", "-C", str(repo), "ls-files", "--", "apps", "platform-base"],
                           capture_output=True, text=True, encoding="utf-8").stdout.splitlines()
    out = []
    for n in names:
        if "/vendor/" in n or "/bina-ui/" in n or n.startswith("legacy/"):
            continue
        screen = "/static/" in n and n.endswith((".js", ".html", ".mjs")) or n.endswith("/ui.html")
        blueprint = n.endswith(".workflow.ts") and "/blueprint/n8n/" in n
        front_end = "/webapp/src/" in n and n.endswith((".js", ".ts", ".tsx", ".jsx"))
        if screen or blueprint or front_end:
            out.append(repo / n)
    return out


def scan(repo: pathlib.Path, files: list[pathlib.Path]) -> "dict[str, list[tuple[int, str, str]]]":
    """{relative file: [(line, word, sentence)]} for every file that has something to say."""
    out: "dict[str, list[tuple[int, str, str]]]" = {}
    for f in files:
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        got = findings(src)
        if got:
            out[f.relative_to(repo).as_posix()] = got
    return out


def check(repo: pathlib.Path, list_only: bool = False, update: bool = False,
          baseline: bool = True) -> int:
    files = read_files(repo)
    if not files:
        print("counted-plural-lint — G89 FAIL: no screen, blueprint or front-end file was found under "
              "apps/ or platform-base/ — the scan is blind, not green")
        return 1
    if list_only:
        for f in files:
            print(f"  {f.relative_to(repo).as_posix()}")
        print(f"counted-plural-lint — G89: {len(files)} file(s) read")
        return 0
    found = scan(repo, files)
    counts = {rel: len(hits) for rel, hits in sorted(found.items())}
    total = sum(counts.values())
    if update:
        BASELINE.write_text(json.dumps(counts, ensure_ascii=False, indent=1) + "\n",
                            encoding="utf-8", newline="\n")
        print(f"G89 baseline recorded: {total} site(s) in {len(counts)} file(s) -> "
              f"{BASELINE.relative_to(repo)}")
        return 0
    if not baseline:                       # the self-test's scratch tree: any finding is a failure
        for rel, hits in found.items():
            for line, word, text in hits:
                print(f"  FAIL  {rel}:{line}  «{word}»  {text}")
        return 1 if total else 0

    base = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {}
    up = [(rel, base.get(rel, 0), n) for rel, n in counts.items() if n > base.get(rel, 0)]
    down = [(rel, n, counts.get(rel, 0)) for rel, n in sorted(base.items()) if counts.get(rel, 0) < n]
    for rel, _was, n in up:
        for line, word, text in found[rel]:
            print(f"  FAIL  {rel}:{line}  «{word}»  {text}")
    print(f"counted-plural-lint — G89: {len(files)} file(s) read · {total} site(s), "
          f"{sum(base.values())} recorded")
    if up:
        print("\nG89 FAIL — a count is glued to a fixed plural:\n")
        for rel, was, n in up:
            print(f"  {rel}: {was} -> {n}")
        print(f"\n  {SAYS}\n  Fix it, then record the lower count: "
              f"python3 scripts/refactor/counted-plural-lint.py --update-baseline")
        return 1
    if down:
        print("\nG89 FAIL — the baseline is stale: sites were fixed and the lower count was not "
              "recorded, so the old ceiling still stands. Record it:")
        for rel, was, n in down[:12]:
            print(f"  {rel}: {was} -> {n}")
        print("    python3 scripts/refactor/counted-plural-lint.py --update-baseline")
        return 1
    print("counted-plural-lint — G89: every counted noun states its own singular, and the "
          f"{len(base)} recorded file(s) match")
    return 0


def self_test() -> int:
    cases = {
        # ── caught ────────────────────────────────────────────────────────────────────────────
        "concatenated count": ("title: 'רפאל: ' + bad.length + ' קונטיינרים לא בריאים',\n", 1),
        "count in a template": ("el.textContent = `${state.items.length} פריטים`;\n", 1),
        "count then seconds": ("return 'לפני ' + d + ' שניות';\n", 1),
        "count inside markup": ('b.innerHTML = "<b>" + pool.length + " פריטים</b>";\n', 1),
        "two counts, one line": ('x = c.movies + " סרטים · " + s.length + " סדרות";\n', 1),
        "a JSX text node": ("<span>{total} פריטים</span>\n", 1),
        "a wrapped count": ("title={`${he(r.count)} פריטים`}\n", 1),
        # ── not caught ────────────────────────────────────────────────────────────────────────
        "the rule itself": ("const one = (n, single, many) => (Number(n) === 1 ? single : num(n) + ' ' + many);\n", 0),
        "a branch on the same line": ("t = n === 1 ? 'פריט אחד' : n + ' פריטים';\n", 0),
        "a branch just above": ("const t = (n === 1)\n  ? 'פריט אחד'\n  : n + ' פריטים';\n", 0),
        "a helper call": ("t = one(pool.length, 'פריט אחד', 'פריטים');\n", 0),
        "a plural with no count": ("h.textContent = 'כל הפריטים נטענו';\n", 0),
        "a singular sentence": ("t = 'נפח נתונים אחד בסיכון';\n", 0),
        "another language": ("t = count + ' items';\n", 0),
        "a comment quoting the defect": ("// was: bad.length + ' קונטיינרים לא בריאים'\nt = '';\n", 0),
        "a url, not a comment": ('const u = "http://console:8000/api/apps"; // and x + \' פריטים\'\n', 0),
    }
    got = {name: len(findings(src)) for name, (src, _n) in cases.items()}
    ok = all(got[name] == want for name, (_src, want) in cases.items())
    # …and the gate as a whole: no file is a failure, a vendored file is not read, a screen is
    tmp = pathlib.Path(tempfile.mkdtemp())
    try:
        subprocess.run(["git", "init", "-q", str(tmp)], check=True)
        ok = ok and check(tmp) == 1                                       # nothing to scan
        static = tmp / "apps" / "x" / "static"
        (static / "vendor").mkdir(parents=True)
        (static / "app.js").write_text("t = one(n, 'פריט אחד', 'פריטים');\n", encoding="utf-8")
        (static / "vendor" / "lib.js").write_text(cases["concatenated count"][0], encoding="utf-8")
        subprocess.run(["git", "-C", str(tmp), "add", "-A"], check=True)
        ok = ok and check(tmp, baseline=False) == 0
        (static / "app.js").write_text(cases["concatenated count"][0], encoding="utf-8")
        ok = ok and check(tmp, baseline=False) == 1
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    print("\ncounted-plural-lint self-test: "
          + ("7 shapes of a glued count are caught (concatenated, template, markup, a JSX text node, a wrapped "
             "count, a bare number, two on one line); the rule itself, a branch on the line or just above, a helper call, a plural with "
             "no count, a singular sentence, another language and a comment are not; a vendored copy is not "
             "read and an empty scan fails"
             if ok else "FAILED — got " + str(got)))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--files", action="store_true", help="list the files this gate reads")
    ap.add_argument("--update-baseline", action="store_true",
                    help="record the current counts (after a real fix, never to let one in)")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    return check(REPO, list_only=a.files, update=a.update_baseline)


if __name__ == "__main__":
    sys.exit(main())
