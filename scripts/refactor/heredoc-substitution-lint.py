#!/usr/bin/env python3
"""heredoc-substitution-lint — gate G88: an unquoted here-document's TEXT is never executed.

    python3 scripts/refactor/heredoc-substitution-lint.py              # exit 1 on a finding
    python3 scripts/refactor/heredoc-substitution-lint.py --self-test
    python3 scripts/refactor/heredoc-substitution-lint.py --files      # list what it reads
    python3 scripts/refactor/heredoc-substitution-lint.py --file PATH  # judge one file (a proof run)

WHY THIS EXISTS. `bbox help` prints its help out of `usage()`, one `cat <<EOF` — UNQUOTED, because the
help text names `${c1}`, `${c0}` and `${DN}` and those have to expand. What an unquoted here-document
does is not only expand: it RUNS. One line of that help text, written the way a person writes a
filename inside a sentence — ITSELF declares a `hooks/update` and is handed to that door instead — was
therefore a COMMAND SUBSTITUTION, executed every time anyone asked bbox for help: `./bbox: line 478:
hooks/update: No such file or directory` on stderr, and the help line printed with the word missing
(measured 2026-10-24). `hooks/update` happened not to exist; an app's own `hooks/update` — the very
thing that sentence is about — WOULD have been run by an unrelated `bbox help`, with whatever
arguments and environment the caller had. Nothing read a help screen for code, because a help screen
is not code: that is the defect — a heredoc makes it code while looking exactly like text.

WHAT IT LOOKS FOR. In the body of every UNQUOTED here-document: an unescaped backtick, or an
unescaped `$(`. `<<'EOF'`, `<<"EOF"` and `<<\\EOF` are quoted and their bodies are not read at all —
quoting is the fix when a body is literal text. `$(( … ))` is arithmetic expansion and is NOT a
finding: it runs no command (measured in `apps/bina-ds/self-update.sh:536`, an unquoted heredoc that
prints `$(( MAX_WAIT / 60 )) min` on purpose). A `\\`` and a `\\$(` are escapes and are not findings —
that is what a body WITH a real substitution does to print the character. A here-document that is
never terminated is a finding too: bash then reads the REST OF THE FILE as its body (measured — bash
warns "here-document at line 1 delimited by end-of-file" and carries on), so one missing `EOF`
silently turns every later line into text that runs.

SCOPE. `bbox`, every shell file under `scripts/`, `platform-base/` and `apps/` — where "shell file" is
a `*.sh`, or a file with NO extension whose shebang names a shell (`scripts/dc`, and the 106
`apps/*/hooks/*` + `platform-base/*/hooks/*` with no suffix, which is exactly where the defect above
was born: `apps/n8n/hooks/pull` carried two of these bodies). `bbox.cmd` is batch and is not one.
**A scan that finds no file FAILS**: green and blind look alike (the lesson of G42's
re-pointing, which passed on zero files for seven weeks).

WHAT IT DOES NOT DO. It does not judge a quoted here-document, a backtick in ordinary code (`x=$(ls)`
is how a shell works), or a substitution a body obviously wants. The one shape it reports is the one
that hid here: a literal-looking body that the shell executes.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys
import tempfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]

#: `<<EOF`, `<<-EOF`, `<< EOF`, `<<'EOF'`, `<<"EOF"`, `<<\EOF`. A here-STRING (`<<<`) is skipped below
#: rather than here: its operand may be a bare word, which this pattern would otherwise read as one.
HEREDOC = re.compile(
    r"<<(-?)[ \t]*(?:'([^']*)'|\"([^\"]*)\"|\\([A-Za-z_][A-Za-z0-9_]*)|([A-Za-z_][A-Za-z0-9_]*))")
SHEBANG = re.compile(r"^#!.*\b(?:ba|da|k|z)?sh\b")


class Heredoc:
    __slots__ = ("delim", "strip_tabs", "quoted", "opened_at")

    def __init__(self, delim: str, strip_tabs: bool, quoted: bool, opened_at: int):
        self.delim, self.strip_tabs, self.quoted, self.opened_at = delim, strip_tabs, quoted, opened_at


def is_escaped(text: str, idx: int) -> bool:
    """True when the character at idx sits behind an ODD run of backslashes (`\\`` prints a backtick)."""
    n, i = 0, idx - 1
    while i >= 0 and text[i] == "\\":
        n, i = n + 1, i - 1
    return n % 2 == 1


def scan_text(text: str, name: str = "<text>") -> list[tuple[str, int, str]]:
    """Findings as (name, line, what the shell would run) for one shell file's text."""
    findings: list[tuple[str, int, str]] = []
    pending: list[Heredoc] = []

    for lineno, line in enumerate(text.splitlines(), 1):
        if pending:
            hd = pending[0]
            candidate = line.lstrip("\t") if hd.strip_tabs else line
            if candidate == hd.delim:                 # nothing else on the line: bash's own rule
                pending.pop(0)
                continue
            if hd.quoted:                             # a quoted body is text by definition
                continue
            said: set[str] = set()
            for i, ch in enumerate(line):
                if ch == "`" and "backtick" not in said and not is_escaped(line, i):
                    said.add("backtick")
                    findings.append((name, lineno,
                                     "unquoted here-document (opened at line %d) RUNS a backtick"
                                     % hd.opened_at))
                elif ch == "$" and line[i + 1:i + 2] == "(" and "substitution" not in said \
                        and not is_escaped(line, i):
                    if line[i + 2:i + 3] == "(":      # $(( … )) is arithmetic: it runs no command
                        continue
                    said.add("substitution")
                    findings.append((name, lineno,
                                     "unquoted here-document (opened at line %d) RUNS a $(…)"
                                     % hd.opened_at))
            continue

        if line.lstrip().startswith("#"):             # a comment starts no here-document
            continue
        for m in HEREDOC.finditer(line):
            if line[m.start() + 2:m.start() + 3] == "<" or line[m.start() - 1:m.start()] == "<":
                continue                              # `<<<` here-string (and its second and third `<`)
            quoted = m.group(2) is not None or m.group(3) is not None or m.group(4) is not None
            delim = m.group(5) or (m.group(2) or m.group(3) or m.group(4)) or ""
            pending.append(Heredoc(delim, m.group(1) == "-", quoted, lineno))

    for hd in pending:
        findings.append((name, hd.opened_at,
                         "here-document opened here is never terminated by `%s` — bash reads the "
                         "REST OF THE FILE as its body" % hd.delim))
    return findings


def line_at(path: pathlib.Path, n: int) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return lines[n - 1].strip() if 0 < n <= len(lines) else ""


def shell_shebang(p: pathlib.Path) -> bool:
    """True when `p` carries no extension and its first line names a shell (`dc`, `hooks/pull`)."""
    if p.suffix or p.name.lower().endswith((".cmd", ".bat")):
        return False
    try:
        first = p.read_text(encoding="utf-8", errors="replace").splitlines()[:1]
    except OSError:
        return False
    return bool(first and SHEBANG.match(first[0]))


def shell_files() -> list[pathlib.Path]:
    """bbox + every shell file of scripts/, platform-base/ and apps/ — the gate's denominator."""
    found: list[pathlib.Path] = []
    cmd = REPO / "bbox"
    if cmd.is_file():
        found.append(cmd)
    for tree in ("scripts", "platform-base", "apps"):
        for p in sorted((REPO / tree).rglob("*")):
            if not p.is_file() or p.name.lower().endswith((".cmd", ".bat")):
                continue
            if p.suffix == ".sh" or shell_shebang(p):
                found.append(p)
    seen: set[pathlib.Path] = set()
    unique: list[pathlib.Path] = []
    for p in found:
        real = p.resolve()
        if real not in seen:
            seen.add(real)
            unique.append(p)
    return unique


def run(files: list[pathlib.Path], bare: bool = False) -> int:
    """Judge `files`; `bare` prints absolute paths (a --file proof run)."""
    if not files:
        print("heredoc-substitution-lint: NO shell file found (bbox, scripts/, platform-base/, apps/ "
              "— *.sh and every no-extension file whose shebang names a shell) — a gate that reads "
              "nothing cannot pass")
        return 1
    findings: list[tuple[str, int, str]] = []
    paths: dict[str, pathlib.Path] = {}
    for p in files:
        name = str(p) if bare else p.relative_to(REPO).as_posix()
        paths[name] = p
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            findings.append((name, 0, "cannot be read (%s)" % e))
            continue
        findings.extend(scan_text(text, name))
    for name, lineno, what in findings:
        print("  FAIL  %s:%d  %s" % (name, lineno, what))
        text = line_at(paths[name], lineno)
        if text:
            print("        %s" % (text[:160],))
    print("\n%d shell file(s) scanned, %d finding(s)" % (len(files), len(findings)))
    if findings:
        print("\nFix: quote the here-document (`<<'EOF'`) when its body is text, or escape the\n"
              "character (`\\`` and `\\$(`) when the body must stay unquoted to expand something else.")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--self-test", action="store_true", help="prove the gate catches, and spares")
    ap.add_argument("--files", action="store_true", help="print the shell files it reads")
    ap.add_argument("--file", action="append", default=None,
                    help="judge this one file (a proof run on pre-fix code); repeatable")
    a = ap.parse_args(argv)

    if a.self_test:
        return self_test()

    if a.file:
        files = [pathlib.Path(f) for f in a.file]
        missing = [f for f in files if not f.is_file()]
        if missing:
            print("cannot read: %s" % ", ".join(str(m) for m in missing))
            return 1
    else:
        files = shell_files()

    if a.files:
        for p in files:
            print(p if a.file else p.relative_to(REPO).as_posix())
        return 0

    return run(files, bare=bool(a.file))


# ── the self-test: a gate only ever seen passing has not been tested (GATES.md) ─────────────────
CASES: list[tuple[str, bool, str]] = [
    # (file text after the shebang, must be reported, why)
    ("cat <<EOF\nITSELF declares a `hooks/update` here\nEOF\n", True, "a backtick in an unquoted body"),
    ("cat <<EOF\nrun $(date) now\nEOF\n", True, "a $( ) in an unquoted body"),
    ("cat <<EOF\nopen `then\nclose`\nEOF\n", True, "the backtick pair, one finding per line"),
    ("cat <<EOF\nliteral \\`backtick\\` and \\$(cmd)\nEOF\n", False, "escaped: that is how it is printed"),
    ("cat <<EOF\n$(( MAX_WAIT / 60 )) min\nEOF\n", False, "$(( )) is arithmetic, it runs no command"),
    ("cat <<'EOF'\na `backtick` and $(cmd)\nEOF\n", False, "a QUOTED body is text by definition"),
    ("cat <<\"EOF\"\na `backtick`\nEOF\n", False, "a double-quoted delimiter is quoted"),
    ("cat <<\\EOF\na `backtick`\nEOF\n", False, "a backslash-quoted delimiter is quoted"),
    ("x=$(ls); y=`date`\n", False, "a backtick in ordinary code is how a shell works"),
    ("cat <<<\"$(ls)\"\n", False, "a here-STRING is not a here-document"),
    ("# cat <<EOF with a `comment`\necho hi\n", False, "a comment starts no here-document"),
    ("cat <<-EOF\n\ta `backtick`\n\tEOF\n", True, "<<- substitutes too; tab-indented body"),
    ("cat <<-EOF\n\tfine\n\tEOF\n", False, "<<- terminated by a tab-indented delimiter"),
    ("cat <<EOF\nno terminator and a `backtick`\n", True, "never terminated: bash runs the rest"),
    ("cat <<EOF\nEOF   \nplain text after\n", True, "trailing spaces do not terminate it"),
    ("cat << EOF\nfine\nEOF\n", False, "a space before the delimiter is still a here-document"),
    ("cat <<EOF\n$(cat <<INNER)\ntext\nINNER\nEOF\n", True, "a substitution that opens a nested heredoc still runs"),
]
EMPTY_SCAN = "a scan that finds no file FAILS"
COLLECT_SHEBANG = "the SHEBANG decides: hooks/pull in, README and notes.txt out"


def self_test() -> int:
    ok = 0
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="heredoc-lint-"))
    for n, (body, expected, why) in enumerate(CASES, 1):
        p = tmp / ("case%02d.sh" % n)
        p.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
        got = bool(scan_text(p.read_text(encoding="utf-8"), str(p)))
        good = got == expected
        ok += good
        print("  [%s] %-56s %s" % ("ok " if good else "FAIL", why,
                                   "reported" if got else "not reported"))
    # The zero-file rule, exercised without trusting the tree: an empty checkout must NOT pass.
    global REPO
    saved, REPO = REPO, tmp / "empty-checkout"
    try:
        empty = run(shell_files()) == 1
    finally:
        REPO = saved
    ok += empty
    print("  [%s] %-56s %s" % ("ok " if empty else "FAIL", EMPTY_SCAN,
                               "exit 1" if empty else "exit 0"))
    # The DENOMINATOR, exercised the same way: a file with no extension is collected by its SHEBANG
    # (where the defect lived: apps/n8n/hooks/pull), and a no-extension file without one is not.
    tree = tmp / "collect-checkout"
    (tree / "apps" / "demo" / "hooks").mkdir(parents=True)
    (tree / "platform-base" / "demo").mkdir(parents=True)
    (tree / "apps" / "demo" / "hooks" / "pull").write_text(
        "#!/usr/bin/env bash\ncat <<EOF\na `backtick`\nEOF\n", encoding="utf-8")
    (tree / "apps" / "demo" / "README").write_text("no shebang here\n", encoding="utf-8")
    (tree / "platform-base" / "demo" / "notes.txt").write_text(
        "#!/usr/bin/env bash\nnot a shell file: it has an extension\n", encoding="utf-8")
    saved, REPO = REPO, tree
    try:
        got = [p.relative_to(tree).as_posix() for p in shell_files()]
        hits = bool(scan_text((tree / "apps/demo/hooks/pull").read_text(), "pull"))
    finally:
        REPO = saved
    collected = got == ["apps/demo/hooks/pull"] and hits
    ok += collected
    print("  [%s] %-56s %s" % ("ok " if collected else "FAIL", COLLECT_SHEBANG,
                               ", ".join(got) if got else "nothing collected"))
    print("\nheredoc-substitution-lint self-test: %d/%d passed" % (ok, len(CASES) + 2))
    return 0 if ok == len(CASES) + 2 else 1


if __name__ == "__main__":
    sys.exit(main())
