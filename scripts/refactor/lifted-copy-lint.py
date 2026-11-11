#!/usr/bin/env python3
"""lifted-copy-lint — gate G110: a file lifted from another app stays the same file (DGO-320).

    python3 scripts/refactor/lifted-copy-lint.py              # check every lifted copy in the tree
    python3 scripts/refactor/lifted-copy-lint.py --self-test  # prove it can fail

WHY

Some engines are generic and lifted, not shared: an app never reaches into another (AGENTS.md, layout), so an app
that needs one carries its own copy, with a header that says where it came from. The web engine is the case that
made this a gate (ai/context/web-engine.md marks webengine.py and browser_session.py «generic (lift as-is)»):
  apps/domains/webengine.py            → apps/social-list/, apps/digital-assets/
  apps/domain-internic/browser_session.py → apps/social-list/
Every lifted copy says «Keep the two copies in step», and nothing kept them: a fix made in one copy is absent in
the others, silently, and when b5e30566 moved browser_session.py from apps/domains to apps/domain-internic the
copy's header went on naming a file that no longer existed.

THE RULE (one class: every lifted file, not one script per engine)

A LIFTED COPY is any tracked file under apps/ or platform-base/ whose leading `#` header (`//` in JavaScript) says
`Lifted from <path>`. For each:
  - <path> must exist, and must not itself be a lifted copy (a header names the original, not a sibling);
  - the copy must be byte-for-byte the original, apart from what a copy may own:
      * its leading `#` (or `//`) header;
      * the logger's name:            logging.getLogger("<anything>")
      * the env names of a DB path:   os.environ.get("<PREFIX>WEBENGINE_DB") and
                                      os.environ.get("<PREFIX>STATE_DIR", …)
  - and so must any file of the original's NAME in another app (apps/*/<name>), header or not: a copy that lost
    its header is still a copy.
The original is always the side compared against, so the copy named in a finding is the one that drifted. The scan
prints how many copies it read. To change a lifted engine, change every copy; for a copy to own a new name, add
it to _ALLOWED.
"""
from __future__ import annotations

import difflib
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
ROOTS = ("apps/", "platform-base/")
_COMMENT = ("#", "//")                       # a header line: `#` (Python, shell) or `//` (JavaScript)
_LIFTED = re.compile(r"^(?:#|//).*\bLifted from (\S+?)(?=[\s—,;:]|$)")

# What a copy may make its own — each replaced by one fixed token before the files are compared.
_ALLOWED = (
    (re.compile(r'logging\.getLogger\("[^"\n]*"\)'), 'logging.getLogger(<LOGGER>)'),
    (re.compile(r'os\.environ\.get\("[A-Z0-9_]*WEBENGINE_DB"\)'), 'os.environ.get(<DB_ENV>)'),
    (re.compile(r'os\.environ\.get\("[A-Z0-9_]*STATE_DIR",'), 'os.environ.get(<STATE_DIR_ENV>,'),
)


def header_source(text: str) -> str | None:
    """The path a file's leading `#` / `//` header says it was lifted from, or None."""
    for line in text.splitlines():
        if not line.startswith(_COMMENT):
            return None
        m = _LIFTED.match(line)
        if m:
            return m.group(1)
    return None


def normalize(text: str) -> str:
    """The file as the engine it is: the leading `#` / `//` header dropped, the allowed names replaced."""
    lines = text.splitlines()
    while lines and lines[0].startswith(_COMMENT):
        lines.pop(0)
    out = "\n".join(lines)
    for pattern, token in _ALLOWED:
        out = pattern.sub(token, out)
    return out


def check(files: dict[str, str]) -> tuple[list[str], int]:
    """(findings, copies compared) over {repo path: text} — the whole tree, or a self-test's."""
    findings: list[str] = []
    pairs: dict[str, str] = {}                   # copy → original
    for path, text in sorted(files.items()):
        src = header_source(text)
        if src is None:
            continue
        if src not in files:
            findings.append(f"{path} says it was lifted from {src}, which does not exist (moved? name the original)")
            continue
        if header_source(files[src]) is not None:
            findings.append(f"{path} names {src}, which is itself a lifted copy: name the original")
            continue
        pairs[path] = src
    # a copy that lost its header is still a copy: every file of an original's NAME in another app
    for original in sorted(set(pairs.values())):
        name = original.rsplit("/", 1)[-1]
        for path in sorted(files):
            if path != original and path not in pairs and path.startswith("apps/") \
                    and path.count("/") == 2 and path.endswith("/" + name):
                pairs[path] = original
    for copy, original in sorted(pairs.items()):
        a, b = normalize(files[original]).splitlines(), normalize(files[copy]).splitlines()
        if a != b:
            diff = [d for d in difflib.unified_diff(a, b, original, copy, n=0, lineterm="")
                    if not d.startswith(("---", "+++"))][:8]
            findings.append(f"{copy} differs from its original {original} beyond the allowed names:\n      "
                            + "\n      ".join(diff))
    return findings, len(pairs)


def tree() -> dict[str, str]:
    """Every tracked text file under the roots whose header could name an original, plus those originals' names."""
    listed = subprocess.run(["git", "-C", str(REPO), "ls-files", "--", *ROOTS],
                            capture_output=True, text=True, check=True).stdout.split("\n")
    files = {}
    for rel in filter(None, listed):
        p = REPO / rel
        if p.suffix not in (".py", ".js", ".mjs", ".sh") or not p.is_file():
            continue
        try:
            files[rel] = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
    return files


def run() -> int:
    files = tree()
    findings, compared = check(files)
    print(f"lifted-copy-lint (G110): {len(files)} files read, {compared} lifted cop"
          + ("y" if compared == 1 else "ies") + " compared with their originals")
    for f in findings:
        print("  FAIL  " + f)
    if findings:
        print(f"G110 FAIL — {len(findings)} finding(s). A lifted engine is changed in every copy (the same engine "
              "everywhere); a copy that must own a new name adds it to _ALLOWED here.")
        return 1
    print("G110 PASS — every lifted copy is its original.")
    return 0


ENGINE = '''"""webengine — the engine."""
import logging, os
from pathlib import Path
log = logging.getLogger("{logger}")
DB_PATH = Path(os.environ.get("{db}")
               or (Path(os.environ.get("{state}", "/data")) / "webengine.db"))
def fetch(x):
    return {body}
'''


JS_BODY = 'import http from "node:http";\nhttp.createServer().listen(8080);\n'
JS_ORIG = "// apps/a/adapter/gate.mjs — the front door, told at length.\n//\n// Why it is so.\n" + JS_BODY
JS_HEAD = "// Lifted from apps/a/adapter/gate.mjs — keep the copies in step.\n"
JS_O, JS_A = "apps/a/adapter/gate.mjs", "apps/b/desktop/gate.mjs"


def self_test() -> int:
    orig = ENGINE.format(logger="domains.webengine", db="DOMAINS_WEBENGINE_DB", state="DOMAINS_STATE_DIR", body="x")
    head = "# Lifted from apps/domains/webengine.py — keep the copies in step.\n"
    lifted = head + ENGINE.format(logger="webengine", db="WEBENGINE_DB", state="APP_STATE_DIR", body="x")
    drifted = head + ENGINE.format(logger="webengine", db="WEBENGINE_DB", state="APP_STATE_DIR", body="x + 1")
    headless = ENGINE.format(logger="webengine", db="WEBENGINE_DB", state="APP_STATE_DIR", body="x - 1")
    O, A, B = "apps/domains/webengine.py", "apps/social-list/webengine.py", "apps/digital-assets/webengine.py"

    def f(files):
        return check(files)[0]
    cases = [
        ("the allowed differences (header, logger, DB env names) pass",
         f({O: orig, A: lifted, B: lifted}) == []),
        ("a change to the engine in one copy fails, naming THAT copy, not its siblings",
         (lambda r: len(r) == 1 and r[0].startswith(B) and "x + 1" in r[0])(f({O: orig, A: lifted, B: drifted}))),
        ("a fix made in the original only fails on every copy that lacks it",
         len(f({O: orig.replace("return x", "return x * 2"), A: lifted, B: lifted})) == 2),
        ("a header naming a file that does not exist fails (the move b5e30566 left one)",
         (lambda r: len(r) == 1 and "does not exist" in r[0])(
             f({"apps/domain-internic/webengine.py": orig, A: lifted}))),
        ("a header naming another copy, not the original, fails",
         any("itself a lifted copy" in x for x in f({O: orig, A: lifted,
                                                     B: "# Lifted from apps/social-list/webengine.py\n" + lifted[len(head):]}))),
        ("a copy of the original's name that lost its header is still compared",
         (lambda r: len(r) == 1 and r[0].startswith("apps/c/webengine.py"))(
             f({O: orig, A: lifted, "apps/c/webengine.py": headless}))),
        ("a `#` line below the docstring is code, not a header",
         len(f({O: orig, A: lifted.replace("import logging", "# note\nimport logging")})) == 1),
        ("no lifted copy anywhere: nothing to compare",
         check({O: orig})[1] == 0 and f({O: orig}) == []),
        # JavaScript says its header with `//` — the desktop apps' front door (gate.mjs) is one engine in four apps
        ("a `//` header lifts a JavaScript copy, and the copy's own header is its own",
         f({JS_O: JS_ORIG, JS_A: JS_HEAD + JS_BODY}) == [] and check({JS_O: JS_ORIG, JS_A: JS_HEAD + JS_BODY})[1] == 1),
        ("a change to a JavaScript copy's code fails, naming that copy",
         (lambda r: len(r) == 1 and r[0].startswith(JS_A))(
             f({JS_O: JS_ORIG, JS_A: JS_HEAD + JS_BODY.replace("8080", "8081")}))),
    ]
    ok = 0
    for what, passed in cases:
        print(("PASS  " if passed else "FAIL  ") + what)
        ok += bool(passed)
    print(f"G110 self-test: {ok}/{len(cases)} passed")
    return 0 if ok == len(cases) else 1


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv[1:] else run())
