#!/usr/bin/env python3
"""office-link-lint — gate G95: a link a person is given is built by the ONE builder.

    python3 scripts/refactor/office-link-lint.py             # exit 1 on a new finding
    python3 scripts/refactor/office-link-lint.py --self-test
    python3 scripts/refactor/office-link-lint.py --files     # list what it reads
    python3 scripts/refactor/office-link-lint.py --update-baseline   # after a real fix

WHY THIS EXISTS. The owner, 2026-11-06 (DGO-1433): «ותפסיק לשלוח לי קישורים שלא עובדים … דיווחתי על זה מיליון
פעם». The office handed him about eleven forms of link, built by hand in seven places, and none was opened past
the sign-in before it was sent: `/a/bina-claude.hp-laptop/` (a proxy mount that exists only for a tile with a
door — `{"error":"unknown_app"}` on his phone, on 11-04 and again on 11-06), `#/m/<tile>/<two UUIDs>` (a
fragment, which does not survive a typed sign-in), `http://console.localhost/…` (on his phone, his phone).
The standard is now ONE form, `https://<the hub's console>/go/<ref>`, resolved by the console at click time
(platform-base/console/links.py) and handed out by ONE builder that opens it first (`bbox console link`,
platform-base/console/link_cli.py). This gate is what keeps a new hand-built form from being written.

WHAT IT LOOKS FOR, in code (comments are not read — the comment that documents a fix quotes the form it removed):

    f"{console}/#/m/{module}/{ws}/projects/…"     →  a finding: the shell's route, built by hand
    `/a/${alias}.${office}/`                     →  a finding: a linked office's proxy mount, built by hand
    "http://console.localhost:8080/…"            →  a finding: a loopback console in a link
    "https://console.example/go/DGO-1433"        →  not: the builder's own form
    route('#/m/' + id)  in the shell itself      →  not: platform-base/console owns the grammar

SCOPE. Tracked code under apps/, platform-base/, platform/, scripts/ and packaging/ (.py .sh .js .mjs .ts .tsx
.go .html, and every file under a hooks/ directory). Not read: the console itself (platform-base/console — the
shell IS the route grammar, and links.py its resolver), tests and fixtures (they quote what they test), vendor/,
legacy/, documents. A scan that reads no file FAILS: green and blind look alike.

THE BASELINE IS DEBT, NOT PERMISSION (G82's and G89's shape). `office-link-baseline.json` records, per file,
how many hand-built links were there when the gate was written — the A1 inventory of the DGO-1433 research:
project-pln's tasks.py, meet's server, the dashboard, dgo-extend. The gate fails when a file's count RISES, when
a file that had none builds one, and when a count has FALLEN without being recorded (`--update-baseline`, after a
real move onto the builder) — so the number only goes down.
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
BASELINE = pathlib.Path(__file__).resolve().parent / "office-link-baseline.json"
ROOTS = ("apps", "platform-base", "platform", "scripts", "packaging")
EXT = (".py", ".sh", ".js", ".mjs", ".ts", ".tsx", ".go", ".html")

#: the shell's route ON A HOST — a link that leaves the page it was built on: `{CONSOLE}/#/m/…`, `${origin}/#/m/…`,
#: `base + "/#/m/…"`, `https://<host>/#/m/…`. A route with no host (`location.hash = "#/m/" + id`, a notice's
#: `link: "/#/m/bina"`) is the shell's own navigation on the page it is on, and is not read.
SHELL_ROUTE = re.compile(r"""(?:\}|https?://[^\s"'`]+|\+\s*["'`])/#/m/""")
#: a linked office's proxy mount, built from two names: `/a/{alias}.{office}`, `/a/${a}.${o}`, "/a/" + a + "." + o
REMOTE_MOUNT = re.compile(r"""/a/\{[^}\n]+\}\.\{|/a/\$\{[^}\n]+\}\.\$\{|/a/["'`]\s*\+[^+\n]+\+\s*["'`]\.""")
#: a loopback console as the host of a link
LOOPBACK = re.compile(r"""https?://console\.localhost\b""")
SHAPES = ((SHELL_ROUTE, "the shell's route (#/m/…) built by hand"),
          (REMOTE_MOUNT, "a linked office's proxy mount (/a/<alias>.<office>/) built by hand"),
          (LOOPBACK, "a loopback console (console.localhost) in a link"))
#: comments, in the languages read here: /* … */, <!-- … -->, `//` and `#` to the end of the line when they
#: start it or follow a space (a URL's `//` and a `#/m/` inside a string are not comments)
_BLOCK = re.compile(r"/\*.*?\*/|<!--.*?-->", re.S)
_LINE = re.compile(r"""^\s*(?://|#(?!/m/)).*$|(?<=\s)//(?!/)[^"'`\n]*$""", re.M)

SAYS = ("a link a person is given is built by the one builder — `./bbox console link <ref>` "
        "(platform-base/console/link_cli.py), which opens it past the sign-in first; in code, the form is "
        "`<hub console>/go/<ref>` (platform-base/console/links.py)")


def strip_comments(src: str) -> str:
    keep = lambda m: "\n" * m.group(0).count("\n")   # noqa: E731 — line numbers stay where they were
    return _LINE.sub("", _BLOCK.sub(keep, src))


def findings(source: str) -> list[tuple[int, str, str]]:
    """(line, what, the line) for every hand-built office link in `source`."""
    code = strip_comments(source)
    out, seen = [], set()
    for n, line in enumerate(code.splitlines(), 1):
        for rx, what in SHAPES:
            if rx.search(line) and n not in seen:
                seen.add(n)
                out.append((n, what, line.strip()[:160]))
    return out


def skipped(name: str) -> bool:
    low = name.lower()
    base = low.rsplit("/", 1)[-1]
    return (low.startswith("platform-base/console/") or low.startswith("legacy/")
            or "/vendor/" in low or "/node_modules/" in low or "/tests/" in low or "/test/" in low
            or "/fixtures/" in low or base.startswith("test_") or base.startswith("test-")
            or "_test." in base or ".test." in base or "selftest" in base or "selfcheck" in base
            or base.endswith(".min.js")
            or low == "scripts/refactor/office-link-lint.py")


def read_files(repo: pathlib.Path) -> list[pathlib.Path]:
    names = subprocess.run(["git", "-C", str(repo), "ls-files", "--", *ROOTS],
                           capture_output=True, text=True, encoding="utf-8").stdout.splitlines()
    return [repo / n for n in names
            if not skipped(n) and (n.endswith(EXT) or "/hooks/" in n and "." not in n.rsplit("/", 1)[-1])]


def scan(repo: pathlib.Path, files: list[pathlib.Path]) -> dict:
    out = {}
    for f in files:
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        got = findings(src)
        if got:
            out[f.relative_to(repo).as_posix()] = got
    return out


def check(repo: pathlib.Path, list_only: bool = False, update: bool = False, baseline: bool = True) -> int:
    files = read_files(repo)
    if not files:
        print("office-link-lint — G95 FAIL: no code file was found under " + ", ".join(ROOTS)
              + " — the scan is blind, not green")
        return 1
    if list_only:
        for f in files:
            print(f"  {f.relative_to(repo).as_posix()}")
        print(f"office-link-lint — G95: {len(files)} file(s) read")
        return 0
    found = scan(repo, files)
    counts = {rel: len(hits) for rel, hits in sorted(found.items())}
    total = sum(counts.values())
    if update:
        with open(BASELINE, "w", encoding="utf-8", newline="\n") as f:     # write_text(newline=) is 3.10+
            f.write(json.dumps(counts, ensure_ascii=False, indent=1) + "\n")
        print(f"G95 baseline recorded: {total} site(s) in {len(counts)} file(s) -> {BASELINE.relative_to(repo)}")
        return 0
    if not baseline:
        for rel, hits in found.items():
            for line, what, text in hits:
                print(f"  FAIL  {rel}:{line}  {what}  {text}")
        return 1 if total else 0
    base = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {}
    up = [(rel, base.get(rel, 0), n) for rel, n in counts.items() if n > base.get(rel, 0)]
    down = [(rel, n, counts.get(rel, 0)) for rel, n in sorted(base.items()) if counts.get(rel, 0) < n]
    for rel, _was, _n in up:
        for line, what, text in found[rel]:
            print(f"  FAIL  {rel}:{line}  {what}  {text}")
    print(f"office-link-lint — G95: {len(files)} file(s) read · {total} site(s), {sum(base.values())} recorded")
    if up:
        print("\nG95 FAIL — a link is built by hand:\n")
        for rel, was, n in up:
            print(f"  {rel}: {was} -> {n}")
        print(f"\n  {SAYS}")
        return 1
    if down:
        print("\nG95 FAIL — the baseline is stale: hand-built links were moved onto the builder and the lower "
              "count was not recorded. Record it:")
        for rel, was, n in down[:12]:
            print(f"  {rel}: {was} -> {n}")
        print("    python3 scripts/refactor/office-link-lint.py --update-baseline")
        return 1
    print(f"office-link-lint — G95: no new hand-built link, and the {len(base)} recorded file(s) match")
    return 0


def self_test() -> int:
    cases = {
        # ── caught ──────────────────────────────────────────────────────────────────────────────────
        "an item link by hand": ('url = f"{CONSOLE}/#/m/{module}/{ws}/projects/{pid}/issues/{iid}"\n', 1),
        "a shell route in JS": ("location.href = base + '/#/m/' + tile;\n", 1),
        "a remote mount, f-string": ('link = f"{base}/a/{alias}.{office}/"\n', 1),
        "a remote mount, template": ("const u = `${origin}/a/${alias}.${office}/`;\n", 1),
        "a remote mount, concatenated": ('u = "/a/" + alias + "." + office + "/";\n', 1),
        "a loopback console": ('BASE = "http://console.localhost:8080"\n', 1),
        "a shell route in a shell": ('echo "${CONSOLE}/#/m/plane/${WS}"\n', 1),
        # ── not caught ──────────────────────────────────────────────────────────────────────────────
        "the builder's form": ('link = f"{hub}/go/{ref}"\n', 0),
        "a python comment": ("# was: f\"{CONSOLE}/#/m/{module}\"\nx = 1\n", 0),
        "a js comment": ("// was: base + '#/m/' + tile\nx = 1;\n", 0),
        "a block comment": ("/* `/a/${alias}.${office}/` was wrong */\nx = 1;\n", 0),
        "a local mount": ('u = f"/a/{alias}/"\n', 0),
        "a url with // in it": ('u = "https://console.example.com/go/x"  // a note\n', 0),
        "a public console": ('u = "https://console.staging.digital-office.co.il/go/DGO-1"\n', 0),
        "the shell's own navigation": ('window.parent.location.hash = "#/m/" + id;\n', 0),
        "a notice's host-less route": ("link: '/#/m/bina',\n", 0),
    }
    got = {name: len(findings(src)) for name, (src, _n) in cases.items()}
    ok = all(got[name] == want for name, (_src, want) in cases.items())
    tmp = pathlib.Path(tempfile.mkdtemp())
    try:
        subprocess.run(["git", "init", "-q", str(tmp)], check=True)
        ok = ok and check(tmp) == 1                                           # nothing to scan: blind, not green
        app = tmp / "apps" / "x"
        (app / "tests").mkdir(parents=True)
        (tmp / "platform-base" / "console").mkdir(parents=True)
        (app / "tool.py").write_text(cases["the builder's form"][0], encoding="utf-8")
        (app / "tests" / "test_tool.py").write_text(cases["an item link by hand"][0], encoding="utf-8")
        (tmp / "platform-base" / "console" / "app.js").write_text(cases["a shell route in JS"][0], encoding="utf-8")
        subprocess.run(["git", "-C", str(tmp), "add", "-A"], check=True)
        ok = ok and check(tmp, baseline=False) == 0                         # a test and the shell are not read
        (app / "tool.py").write_text(cases["a remote mount, f-string"][0], encoding="utf-8")
        ok = ok and check(tmp, baseline=False) == 1
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    print("\noffice-link-lint self-test: "
          + ("7 shapes of a hand-built link are caught (an item route, a shell route in JS and in a shell, a remote "
             "mount as an f-string, a template and a concatenation, a loopback console); the builder's /go/ form, "
             "comments of three kinds, a local mount, a URL's // and a public console are not; tests and the shell "
             "itself are not read, and an empty scan fails"
             if ok else "FAILED — got " + str(got)))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--files", action="store_true", help="list the files this gate reads")
    ap.add_argument("--update-baseline", action="store_true",
                    help="record the current counts (after a real move onto the builder, never to let one in)")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    return check(REPO, list_only=a.files, update=a.update_baseline)


if __name__ == "__main__":
    sys.exit(main())
