#!/usr/bin/env python3
"""empty-env-lint — gate G115: a variable a compose file may pass EMPTY is read as unset, never as a value.
    python3 scripts/refactor/empty-env-lint.py              # every app's compose and code
    python3 scripts/refactor/empty-env-lint.py --self-test  # prove it can fail
WHY
A compose line `- NAME=${NAME:-}` hands the container an EMPTY string whenever the office declares nothing — not
an absent variable. Code that reads it with a default of its own (`os.environ.get("NAME", "600")`) gets the empty
string instead of its default: `float("")` raises, `int("")` raises, a path or a URL becomes "", a flag turns off.
On 2026-11-10 the MacBook's link app crash-looped 36 minutes on exactly that (`DGO_LINK_ALERT_AFTER`, issues/the-
macbooks-link-service-crash-looped-…yaml): fc2a3c066 added the compose line and, with it, the reader that copes
(`… or "600"`); an image older than the commit read the empty string as a float. The tree was consistent; the rule
this gate holds is that it STAYS consistent — the one way to read such a variable is «empty is unset»:
    python:  os.environ.get("NAME") or "600"          os.getenv("NAME") or default
    js/ts:   process.env.NAME || "600"
THE RULE
An entry under a service's `environment:` (list or mapping form) MAY BE EMPTY when its whole value is `${OUTER:-}`,
`${OUTER-}`, a bare `${OUTER}` / `$OUTER` (compose fills an unset variable with "" and only warns), `${OUTER:+x}`, a
nested `${A:-${B:-}}`, or nothing at all; the container-side name is the entry's own (`INNER=${OUTER:-}` → INNER).
Only the compose the app's manifest names is read (`app.json` `compose`; null or absent = no compose, as the compiler
reads it) — a side variant (any-concurrency's standalone file) may mean «empty = this source is off» on purpose.
That app's own code (.py; .js .mjs .cjs .ts .tsx — tests, vendored and built files left out) may not read such a
name with a default the empty string defeats:
    os.environ.get("NAME", <non-empty default>)  ·  os.getenv("NAME", <non-empty default>)   unless `or …` follows
    process.env.NAME ?? <non-empty>  ·  process.env["NAME"] ?? <non-empty>
WHAT IT IS NOT: G115 passes fc2a3c066 itself — the crash was an IMAGE older than its compose, which no check of one
tree can see (the crash issue's other task). It keeps the tree's readers right for the day such a pair meets.
NOT COVERED (said, not hidden; none occurs in the tree at landing): a helper of the app's own that takes a name and a
default (`_flag`, `_env`, `_seconds` — today called only with "" for these names); a name held in a constant or read
through an alias (`env = os.environ`), `setdefault`, `"X" in os.environ`; Go's `os.LookupEnv` helpers (`os.Getenv`
cannot tell "" from unset; forward-auth's `env()` can, and is called with "" for every name its compose may pass
empty); js destructuring defaults, `?.` chains and aliases; a flow-form or anchored `environment:` (`{…}`, `&x`, `*x`,
`<<:`), quoted keys; `env_file:` (an explicit `X=` in .env reaches the container as ""); environment the compiler
injects; code mounted from another app's directory; a concatenation of empties (`${A:-}${B:-}`).
The scan prints how many entries and files it read.
"""
from __future__ import annotations

import json
import pathlib
import posixpath
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
ROOTS = ("apps", "platform-base")
CODE = (".py", ".js", ".mjs", ".cjs", ".ts", ".tsx")
_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
_PY = re.compile(r"""(?<![\w.])(?:os\.)?(?:environ\.get|getenv)\(\s*["']([A-Z][A-Z0-9_]*)["']\s*,""")
_JS = re.compile(r"""\bprocess\.env(?:\.([A-Z][A-Z0-9_]*)|\[\s*["']([A-Z][A-Z0-9_]*)["']\s*\])\s*\?\?""")
_EMPTY_LITERALS = {'""', "''", "``", '""""""', "''''''", "None", "str()"}
_EMPTY_STR = re.compile(r"""^[rRbBuUfF]{0,2}(?:""|''|""""""|'''''')$""")


def in_comment(text: str, at: int, mark: str) -> bool:
    """Whether a comment mark comes before `at` on its line, outside quotes — or the line is a js block comment's
    `*` line. (A python docstring that quotes the bad form is still read: rare, and visible in the finding.)"""
    line = text[text.rfind("\n", 0, at) + 1:at]
    if mark == "//" and line.lstrip().startswith(("*", "/*")):
        return True
    quote, i = "", 0
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == "\\":
                i += 1
            elif ch == quote:
                quote = ""
        elif ch in "'\"`":
            quote = ch
        elif line.startswith(mark, i):
            return True
        i += 1
    return False


def uncomment(line: str) -> str:
    """The line without a YAML comment: a `#` after whitespace, outside quotes."""
    quote = ""
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i].rstrip()
    return line.rstrip()


def unquote(v: str) -> str:
    v = v.strip()
    return v[1:-1] if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"" else v


def may_be_empty(v: str) -> bool:
    """Whether compose may turn this WHOLE value into an empty string when the office declares nothing."""
    v = v.strip()
    if v == "":
        return True
    if re.fullmatch(r"\$\{" + _NAME + r"\}", v) or re.fullmatch(r"\$" + _NAME, v):
        return True
    m = re.fullmatch(r"\$\{" + _NAME + r"(:?[-+?])(.*)\}", v, re.S)
    if not m:
        return False
    op, rest = m.group(1).lstrip(":"), m.group(2)
    if op == "?":
        return False          # `${X:?err}` refuses to start instead
    if op == "+":
        return True           # `${X:+alt}` is "" whenever X is unset
    return may_be_empty(rest)


def env_entries(text: str) -> list[tuple[str, str]]:
    """(container-side name, value) of every entry under a service's `environment:`, list or mapping form."""
    out, env_indent = [], None
    for raw in text.splitlines():
        line = uncomment(raw)
        stripped = line.strip()
        if not stripped:
            continue
        indent = len(line) - len(line.lstrip(" "))
        if env_indent is not None and (indent < env_indent or (indent == env_indent and not stripped.startswith("-"))):
            env_indent = None
        if env_indent is None:
            if stripped == "environment:":
                env_indent = indent
            continue
        if stripped.startswith("- "):
            item = unquote(stripped[2:])
            name, eq, value = item.partition("=")
            if eq and re.fullmatch(_NAME, name.strip()):
                out.append((name.strip(), unquote(value)))
        else:
            m = re.fullmatch(r"(" + _NAME + r")\s*:\s*(.*)", stripped)
            if m and m.group(2) != "":       # `NAME:` alone passes the shell's NAME or nothing — never ""
                out.append((m.group(1), unquote(m.group(2))))
    return out


def office_composes(files: dict[str, str]) -> dict[str, str]:
    """{compose path: app dir} — the compose each manifest names (`compose`; null or absent = none, as reconcile)."""
    out = {}
    for path, text in files.items():
        parts = path.split("/")
        if len(parts) != 3 or parts[0] not in ROOTS or parts[2] != "app.json":
            continue
        try:
            manifest = json.loads(text)
        except ValueError:
            continue
        c = manifest.get("compose") if isinstance(manifest, dict) else None
        if isinstance(c, str) and c.strip():
            out[posixpath.normpath(f"{parts[0]}/{parts[1]}/{c.strip()}")] = parts[1]
    return out


def app_of(path: str) -> str:
    """apps/<id>/… or platform-base/<id>/… → <id>."""
    parts = path.split("/")
    return parts[1] if len(parts) > 2 and parts[0] in ROOTS else ""


def skipped(path: str) -> bool:
    """Tests, vendored and built files are not the app's running code."""
    parts = path.split("/")
    base = parts[-1]
    return (any(p in ("tests", "test", "__tests__", "vendor", "node_modules", "dist", "build") for p in parts[:-1])
            or base.startswith("test_") or base.endswith("_test.py") or ".test." in base or ".spec." in base
            or base.endswith(".min.js") or base.endswith(".d.ts"))


def scan(text: str, start: int, to_comma: bool) -> int:
    """The index of the depth-0 `)` (or, with to_comma, the first depth-0 `,` before it) from `start`, inside a
    call's argument list — strings and nested brackets skipped. -1 when none is found within 600 characters."""
    depth, i, quote = 0, start, ""
    while i < len(text) and i - start < 600:
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 1
            elif ch == quote:
                quote = ""
        elif ch in "'\"`":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            if depth == 0:
                return i
            depth -= 1
        elif ch == "," and depth == 0 and to_comma:
            return i
        i += 1
    return -1


def argument(text: str, start: int) -> tuple[str, int]:
    """The argument that starts at `start` (to the depth-0 `,` or `)`), and the index just past the call's own
    closing parenthesis (-1 when it cannot be found)."""
    stop = scan(text, start, to_comma=True)
    close = scan(text, start, to_comma=False)
    arg = text[start:stop if stop != -1 else len(text)].strip()
    return arg, (close + 1 if close != -1 else -1)


def check(files: dict[str, str]) -> tuple[list[str], int, int]:
    """(findings, may-be-empty entries, code files read) over {repo path: text}."""
    empty: dict[str, set[str]] = {}
    entries = 0
    for path, app in office_composes(files).items():
        for name, value in env_entries(files.get(path, "")):
            if may_be_empty(value):
                empty.setdefault(app, set()).add(name)
                entries += 1
    findings, read = [], 0
    for path, text in sorted(files.items()):
        if not path.endswith(CODE) or skipped(path):
            continue
        names = empty.get(app_of(path))
        if not names:
            continue
        read += 1
        if path.endswith(".py"):
            for m in _PY.finditer(text):
                if m.group(1) not in names or in_comment(text, m.start(), "#"):
                    continue
                default, end = argument(text, m.end())
                default = re.sub(r"^default\s*=\s*", "", default)
                if default in _EMPTY_LITERALS or default == "" or _EMPTY_STR.match(default):
                    continue
                if len(default) > 80:
                    default = default[:77] + "..."
                if end != -1 and re.match(r"\s*or\b", text[end:]):
                    continue          # `get("X", d) or d` copes already
                line = text[:m.start()].count("\n") + 1
                findings.append(f"{path}:{line} reads {m.group(1)} with the default {default}, but the "
                                f"compose may pass it EMPTY — the empty string wins: write "
                                f"`os.environ.get(\"{m.group(1)}\") or {default}`")
        else:
            for m in _JS.finditer(text):
                name = m.group(1) or m.group(2)
                if name not in names or in_comment(text, m.start(), "//"):
                    continue
                rhs = re.match(r"\s*(\"\"|''|``|undefined\b|null\b)(?![\w.])", text[m.end():])
                if rhs:
                    continue          # `?? ""` is «empty» either way
                line = text[:m.start()].count("\n") + 1
                findings.append(f"{path}:{line} reads process.env.{name} with `??`, but the compose may pass it "
                                f"EMPTY and «» is not nullish: write `||`")
    return findings, entries, read


def tree() -> dict[str, str]:
    listed = subprocess.run(["git", "-C", str(REPO), "ls-files", "--", *(r + "/" for r in ROOTS)],
                            capture_output=True, text=True, check=True).stdout.split("\n")
    out = {}
    for rel in filter(None, listed):
        if not (rel.endswith(CODE) or (rel.count("/") == 2 and rel.endswith("/app.json"))):
            continue
        try:
            out[rel] = (REPO / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
    for rel in office_composes(out):
        try:
            out[rel] = (REPO / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
    return out


def run() -> int:
    findings, entries, read = check(tree())
    print(f"empty-env-lint (G115): {entries} compose entries may pass a variable EMPTY when the office declares "
          f"none; {read} code file(s) of those apps read")
    for f in findings:
        print("  FAIL  " + f)
    if findings:
        print(f"G115 FAIL — {len(findings)} read(s) where an empty compose value defeats the default.")
        return 1
    print("G115 PASS — every such variable is read as «empty is unset».")
    return 0


def self_test() -> int:
    MA, MB = '{"id": "a", "compose": "docker-compose.yml"}', '{"id": "b", "compose": "docker-compose.yml"}'
    compose = ("services:\n  a:\n    environment:\n      - ALERT_AFTER=${ALERT_AFTER:-}\n      - KEPT=${KEPT:-5}\n"
               "      - INNER=${OUTER_NAME:-}\n      - NOTED=${NOTED:-}   # a comment after it\n"
               "      - NESTED=${NESTED:-${OLD_NESTED:-}}\n      - BARE=${BARE}\n"
               "    build:\n      args:\n        - BUILT=${BUILT:-}\n")
    mapping = "services:\n  b:\n    environment:\n      PORT: \"${PORT:-}\"\n      HOST: ${HOST:-x}\n"
    same = ("services:\n  c:\n    environment:\n    - SAME=${SAME:-}\n    - PLUS=${PLUS:+on}\n    - QUERY=${QUERY:?say it}\n"
            "    - UNBRACED=$UNBRACED\n    ports:\n    - 'AFTER=${AFTER:-}'\n")
    A = {"apps/a/app.json": MA, "apps/a/docker-compose.yml": compose}
    B = {"apps/b/app.json": MB, "apps/b/docker-compose.yml": mapping}
    C = {"apps/c/app.json": '{"id": "c", "compose": "docker-compose.yml"}', "apps/c/docker-compose.yml": same}
    PC = "apps/c/app.py"

    def f(base, code):
        return check({**base, **code})[0]

    def one(base, path, src):
        return len(f(base, {path: src})) == 1

    def none(base, path, src):
        return f(base, {path: src}) == []
    P, J = "apps/a/app.py", "apps/b/server.mjs"
    cases = [
        ("the crash of 2026-11-10: a float of a default the empty string defeats fails",
         one(A, P, 'X = float(os.environ.get("ALERT_AFTER", "600"))\n')),
        ("…and its fix passes: `get(NAME) or default`", none(A, P, 'X = float(os.environ.get("ALERT_AFTER") or "600")\n')),
        ("getenv with a default fails too, and names the line",
         (lambda r: len(r) == 1 and "apps/a/worker.py:2" in r[0])(
             f(A, {"apps/a/worker.py": "import os\nT = os.getenv('ALERT_AFTER', 'x')\n"}))),
        ("a default of None or \"\" (positional or `default=`) is «empty is unset» already: passes",
         none(A, P, 'a = os.environ.get("ALERT_AFTER", None)\nb = os.getenv("ALERT_AFTER", "")\n'
                    'c = os.getenv("ALERT_AFTER", default="")\n')),
        ("a call already followed by `or` copes: passes", none(A, P, 'x = int(os.environ.get("ALERT_AFTER", "5") or 5)\n')),
        ("a multi-line call with a trailing comma reads its default cleanly",
         (lambda r: len(r) == 1 and 'default "600", but' in r[0] and 'or "600"`' in r[0])(
             f(A, {P: 'x = os.getenv(\n    "ALERT_AFTER",\n    "600",\n)\n'}))),
        ("…and the same call with \"\" passes", none(A, P, 'x = os.getenv(\n    "ALERT_AFTER",\n    "",\n)\n')),
        ("a parenthesis inside the default's string is part of it",
         (lambda r: len(r) == 1 and '"a)b"' in r[0])(f(A, {P: 'x = os.getenv("ALERT_AFTER", "a)b")\n'}))),
        ("a RENAMED entry (INNER=${OUTER:-}) is read by its container-side name",
         one(A, P, 'x = os.getenv("INNER", "1")\n') and none(A, P, 'x = os.getenv("OUTER_NAME", "1")\n')),
        ("an entry with a trailing comment counts", one(A, P, 'x = os.getenv("NOTED", "1")\n')),
        ("a nested `${A:-${B:-}}` counts", one(A, P, 'x = os.getenv("NESTED", "1")\n')),
        ("a bare `${NAME}` counts (compose fills an unset one with \"\")", one(A, P, 'x = os.getenv("BARE", "1")\n')),
        ("a build arg is not the container's environment", none(A, P, 'x = os.getenv("BUILT", "1")\n')),
        ("a list at the SAME indent as `environment:` is read, and ends at the next key",
         one(C, PC, 'x = os.getenv("SAME", "1")\n') and none(C, PC, 'x = os.getenv("AFTER", "1")\n')),
        ("`${X:+on}` counts (\"\" when X is unset), `${X:?err}` does not (it refuses to start), `$X` counts",
         one(C, PC, 'x = os.getenv("PLUS", "1")\n') and none(C, PC, 'x = os.getenv("QUERY", "1")\n')
         and one(C, PC, 'x = os.getenv("UNBRACED", "1")\n')),
        ("a read inside a comment is not code (python `#`, js `//` and a block comment's `*` line)",
         none(A, P, '# was: os.getenv("ALERT_AFTER", "1")\n')
         and none(B, J, "// was: process.env.PORT ?? 1\n * process.env.PORT ?? 2\n")),
        ("a prefixed empty string (f\"\", r'') and js `?? null` / `?? undefined` are «empty is unset» already",
         none(A, P, 'x = os.getenv("ALERT_AFTER", f"")\ny = os.getenv("ALERT_AFTER", r\'\')\n')
         and none(B, J, "const a = process.env.PORT ?? null;\nconst b = process.env.PORT ?? undefined;\n")),
        ("a default too long to read is cut in the finding, never the rest of the file",
         (lambda r: len(r) == 1 and len(r[0]) < 400)(f(A, {P: 'x = os.getenv("ALERT_AFTER", ' + "a + " * 400 + "b\n"}))),
        ("a variable the compose passes WITH a default is not this case", none(A, P, 'k = int(os.environ.get("KEPT", "5"))\n')),
        ("the mapping form of an entry counts, and js `??` fails", one(B, J, "const p = Number(process.env.PORT ?? 8080);\n")),
        ("js bracket form and .ts count", one(B, "apps/b/src/main.ts", "const p = process.env['PORT'] ?? '8080';\n")),
        ("js `||` passes, and `?? \"\"` is empty either way", none(B, J, "const p = Number(process.env.PORT || 8080);\n"
                                                              "const q = process.env.PORT ?? '';\n")),
        ("a mapping entry with a default of its own is not this case", none(B, J, "const h = process.env.HOST ?? 'y';\n")),
        ("a default that is itself a lookup is read whole, and fails: the fallback name is never reached",
         (lambda r: len(r) == 1 and 'os.getenv("OLD", "")' in r[0])(
             f(A, {P: 'X = os.getenv("ALERT_AFTER", os.getenv("OLD", ""))\n'}))),
        ("another app's code is not read for this app's compose",
         none(A, "apps/z/app.py", 'X = float(os.environ.get("ALERT_AFTER", "600"))\n')),
        ("tests, vendored and built files are not read",
         f(A, {"apps/a/tests/test_x.py": 'os.environ.get("ALERT_AFTER", "1")\n',
               "apps/a/static/vendor/lib.js": "process.env.ALERT_AFTER ?? 1\n",
               "apps/a/dist/app.js": "process.env.ALERT_AFTER ?? 1\n"}) == []),
        ("only the compose the manifest names: a standalone variant's «empty = off» is its own",
         check({"apps/a/app.json": MA, "apps/a/docker-compose.standalone.yml": compose,
                P: 'X = float(os.environ.get("ALERT_AFTER", "600"))\n'})[0] == []),
        ("…a manifest with `compose: null` (or none) has no compose, as the compiler reads it",
         check({"apps/a/app.json": '{"id": "a", "compose": null}', "apps/a/docker-compose.yml": compose,
                P: 'X = float(os.environ.get("ALERT_AFTER", "600"))\n'})[0] == []),
        ("…and the manifest's own compose path is followed, a subdirectory too",
         len(check({"apps/a/app.json": '{"id": "a", "compose": "deploy/compose.office.yml"}',
                    "apps/a/deploy/compose.office.yml": compose,
                    P: 'X = float(os.environ.get("ALERT_AFTER", "600"))\n'})[0]) == 1),
    ]
    ok = 0
    for what, passed in cases:
        print(("PASS  " if passed else "FAIL  ") + what)
        ok += bool(passed)
    print(f"G115 self-test: {ok}/{len(cases)} passed")
    return 0 if ok == len(cases) else 1


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv[1:] else run())
