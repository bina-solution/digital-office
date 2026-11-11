#!/usr/bin/env python3
"""test_baseline_env_untouched — scripts/baseline.sh does not write the office's .env itself (DGO-125).

    python3 scripts/test_baseline_env_untouched.py          # the self-test, then baseline.sh
    python3 scripts/test_baseline_env_untouched.py <file>   # the scan of another file (the old baseline.sh)

The owner (2026-07-27): «basiline should allwase use the given creds. passwords and all creds should be
consistent across all runs unless we delibiratly change them». baseline.sh's header said it never touches .env,
while two blocks of it did, on every run: PG_NOFILE_SOFT/HARD appended on a host with a low nofile limit (and left
there), and COMPOSE_PROFILES emptied unless BASELINE_WITH_BROWSER42=1. What a run needs differently is exported for
its own process (`ccr_clamp_nofile`, which dcx now calls for every caller) or chosen by its service set.

What it reads: every command line of baseline.sh — comment lines, trailing comments and here-document bodies
aside. What it refuses, on a path spelled `.env`, `./.env`, `"${REPO_ROOT}"/.env`, `${REPO_ROOT}/.env` or
`${SELF_DIR}/../.env`, quoted or not: a redirection into it (`>`, `>>`, `>|`, `&>`, `N>`), `sed -i`/`-Ei`/
`--in-place`, `perl -pi`, `awk -i inplace`, `tee`, `cp`/`mv`/`install`/`ln`/`rm`/`truncate`/`dd of=` onto it, a
python `open(…'.env', 'w'|'a')`, lib.sh's `env_set`, and any run of scripts/ci-env.sh (which mints a new .env).
Also `mv .env` away, `$PWD/.env` and `$(pwd)/.env`, `<>` and pathlib's `write_text`.
What it cannot see: a path held in a variable (`> "$E"`); a here-document whose BODY is a program that writes
.env (`python3 - <<PY … open(".env","w")`, the shape env_set has — bodies are skipped, as data); and what the
processes baseline starts write — its `bbox run` child appends what a manual `bbox run` does (a missing
PERFORMANCE_PROFILE, a hook's own keys), none of them a credential it rotates. G72 runs this file
(scripts/test_*.py) wherever the gates run.
"""
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
TARGET = REPO / "scripts" / "baseline.sh"

_DIR = r"""(?:\$\{?(?:REPO_ROOT|ROOT|PWD)\}?["']?/|\$\(pwd\)["']?/|\$\{?SELF_DIR\}?["']?/\.\./|\./)"""
ENV = r"""["']?""" + _DIR + r"""?\.env(?![.\w-])["']?"""
WRITES = [
    ("a redirection into .env", re.compile(r"(?:^|[^<>])(?:&>>?|\d?<?>>?\|?)\s*" + ENV)),
    ("mv of .env away", re.compile(r"\bmv\b(?:\s+-\w+)*\s+" + ENV + r"\s")),
    ("python write_text on .env", re.compile(r"""Path\(\s*['"][^'"]*\.env['"]\s*\)\.write_(?:text|bytes)""")),
    ("sed in place on .env", re.compile(r"\bsed\b(?=[^|;&]*\s(?:-[a-zA-Z]*i|--in-place))[^|;&]*\s" + ENV)),
    ("perl -i on .env", re.compile(r"\bperl\b[^|;&]*\s-[a-zA-Z]*i[^|;&]*\s" + ENV)),
    ("awk -i inplace on .env", re.compile(r"\bg?awk\b[^|;&]*-i\s*inplace[^|;&]*\s" + ENV)),
    ("tee onto .env", re.compile(r"\btee\b[^|;&<]*\s" + ENV)),          # `tee x < .env` reads it
    ("cp/mv/install/ln/rm onto .env",
     re.compile(r"\b(?:cp|mv|install|ln|rm)\b[^|;&]*\s" + ENV + r"\s*(?:$|[;&|)<>]|\d?>)")),
    ("truncate of .env", re.compile(r"\btruncate\b[^|;&]*\s" + ENV)),
    ("dd of=.env", re.compile(r"\bdd\b[^|;&]*\bof=" + ENV)),
    ("python open(.env) for writing", re.compile(r"""open\(\s*['"][^'"]*\.env['"]\s*,\s*['"][wax+]""")),
    ("env_set (lib.sh writes .env)", re.compile(r"(?:^|[\s;&|(])env_set\s")),
    ("a run of ci-env.sh (mints a new .env)", re.compile(r"ci-env\.sh")),
]
# `<<WORD` / `<<-WORD` / `<<'WORD'` starts a here-document; `<<<` (a here-string) and `1<<2` (a shift) do not
HEREDOC = re.compile(r"""(?<![<\w$(])<<-?\s*(['"]?)([A-Za-z_][A-Za-z0-9_]*)\1""")


def _outside_quotes(code, pos):
    """True when `pos` is outside a quoted string of this one line (an even number of unescaped quotes before it)."""
    head = re.sub(r"\\.", "", code[:pos])
    return head.count("'") % 2 == 0 and head.count('"') % 2 == 0


def command_lines(text):
    """(line number, code) for each line that is shell code: no comment lines, no here-document bodies, and a
    trailing ` # comment` cut off."""
    out, ending = [], None
    for n, raw in enumerate(text.splitlines(), 1):
        if ending is not None:
            if raw.strip() == ending:
                ending = None
            continue
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        code = re.sub(r"\s+#[^'\"]*$", "", line)
        out.append((n, code))
        for m in HEREDOC.finditer(code):
            if "((" not in code[:m.start()] and _outside_quotes(code, m.start()):
                ending = m.group(2)
                break
    return out


def findings(text):
    found = []
    for n, code in command_lines(text):
        for name, rx in WRITES:
            if rx.search(code):
                found.append((n, name, code))
    return found


CAUGHT = [
    "echo 'COMPOSE_PROFILES=' >> .env",
    "grep -q '^K=' .env && sed -i 's#^K=.*#K=1#' .env || echo K=1 >> .env",
    'printf "%s\\n" "$x" > "${REPO_ROOT}/.env"',
    'echo x > ".env"',
    "echo x >| .env",
    "cmd &> .env",
    "exec 3> .env",
    'echo x >> "${REPO_ROOT}"/.env',
    'echo x >> "${SELF_DIR}/../.env"',
    "sed -i 's/a/b/' \".env\"",
    "sed -Ei 's/a/b/' .env",
    "sed --in-place 's/a/b/' .env",
    "perl -pi -e 's/a/b/' .env",
    "awk -i inplace '{print}' .env",
    "cat .env.ex | tee -a .env >/dev/null",
    "cp .env.ex .env",
    "cp .env.ex .env 2>/dev/null || true",
    "mv /tmp/new.env ./.env",
    "mv x '.env' >/dev/null",
    "rm -f .env",
    "truncate -s 0 .env",
    "dd if=/tmp/x of=.env",
    "python3 -c \"open('.env','a').write('K=1')\"",
    "env_set PG_NOFILE_HARD 4096",
    "bash scripts/ci-env.sh",
    "mv .env /tmp/away",
    'echo x >> "$PWD/.env"',
    'echo x >> "$(pwd)/.env"',
    "exec 3<> .env",
    "python3 -c \"import pathlib; pathlib.Path('.env').write_text('K=1')\"",
]
CLEAN = [
    "[ -f .env ] || die \"no .env\"",
    "log \"using existing .env ($(grep -c = .env) keys)\"",
    "x=\"$(read_env POSTGRES_PASSWORD)\"",
    "grep -q '^K=' .env.ex",
    "cp .env.ex /tmp/env.copy",
    "cat .env > /tmp/env.copy",
    "tee /tmp/log < .env",
    "dcx config -q 2>/tmp/baseline-cfg.err",
    "# a comment that says >> .env",
    "python3 -c \"open('.env').read()\"",
]
# a write AFTER each of these must still be seen: none of them opens a here-document
NOT_HEREDOCS = ["cat <<< \"$x\"", "n=$(( 1<<2 ))", "(( a = b << c ))", "echo \"use <<EOF here\""]


def self_test():
    bad = 0
    for s in CAUGHT:
        if not findings(s):
            print(f"  SELF-TEST FAIL: not caught: {s}")
            bad += 1
    for s in CLEAN:
        if findings(s):
            print(f"  SELF-TEST FAIL: a read taken for a write: {s}")
            bad += 1
    if findings("cat > /tmp/x.env <<'EOF'\nK=1 >> .env\nEOF\necho ok"):
        print("  SELF-TEST FAIL: a here-document's body read as a command")
        bad += 1
    for s in NOT_HEREDOCS:
        if not findings(s + "\necho K=1 >> .env"):
            print(f"  SELF-TEST FAIL: `{s}` taken for a here-document hid the write after it")
            bad += 1
    print(f"self-test: {len(CAUGHT)} writes caught, {len(CLEAN) + 1} reads left alone, "
          f"{len(NOT_HEREDOCS)} non-here-documents seen through" if not bad else f"self-test: {bad} wrong")
    return 1 if bad else 0


def scan(path):
    text = path.read_text(encoding="utf-8")
    found = findings(text)
    for n, name, code in found:
        print(f"  FAIL {path.name}:{n}: {name}: {code}")
    if found:
        print(f"{path.name} writes .env in {len(found)} place(s) — it must use the office's .env as it is (DGO-125)")
        return 1
    print(f"OK — {path.name}: {len(command_lines(text))} command lines read, none writes .env")
    return 0


def main(argv):
    if len(argv) > 1 and argv[1] == "--self-test":
        return self_test()
    if len(argv) > 1:
        return scan(pathlib.Path(argv[1]))
    return self_test() or scan(TARGET)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
