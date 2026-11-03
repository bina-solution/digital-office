#!/usr/bin/env python3
"""deploy-forward-lint — gate G90: an office never deploys a tree that drops what it already runs.

    python3 scripts/refactor/deploy-forward-lint.py             # exit 1 on a finding
    python3 scripts/refactor/deploy-forward-lint.py --self-test
    python3 scripts/refactor/deploy-forward-lint.py --files     # list what it reads

WHY THIS EXISTS (DGO-1016). On 2026-10-16 14:14 UTC a converge from the MacBook checked vps1 out at
d24547e2, the commit its declaration had been saved with eight days earlier, and every service was
rebuilt from it. 418 commits that vps1 was running went without a word, among them the price of a
conversation in Azaria's sessions (apps/bina-ds/plugins/cost-meter). The owner had asked for that
feature and then found it gone. Every later session that touched vps1 checked out another commit
without it, so it stayed gone for six days.

Two places now hold the rule, and this gate holds them:
  1. the converge's code step (`apps/dgo-extend/converge.py::code_script`): a machine whose HEAD is not
     inside the declared commit is not checked out. It stops with exit 3 and names what would go;
  2. `dcx` (scripts/lib.sh), the one door to compose (G7): a build or recreate from a HEAD that does
     not contain the commit this machine last ran (data/.deploy/deployed) is refused.

WHAT IT CHECKS.
  A. Every tracked script of the product that MOVES a checkout to another commit (`checkout --detach`,
     `checkout -f`, `switch --detach`, `reset --hard`) is the guarded code step, or is EXEMPT here with
     the reason. The scan set is printed; an empty one fails.
  B. `dcx` calls `deploy_ledger_gate` before it admits the command, and `deploy_ledger_record` after.
  C. The ledger, for real: a temporary repository A → B → C (+ a side commit S), lib.sh sourced over it,
     and the gate asked in each state (no ledger, same HEAD, back, forward, sideways, on purpose, a
     dry run, a question).
  D. The converge's own selftest (apps/dgo-extend/tests/forward_only_selftest.py), which runs the
     code step's real script against real checkouts.
Static and office-free; needs git and bash. ~3 s.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROOTS = ["bbox", "scripts", "apps", "platform-base", "platform", "packaging"]
SKIP_PARTS = {"node_modules", "tests", "test", "__pycache__", "blueprint", "fixtures", "vendor", "legacy"}
SUFFIXES = {".py", ".sh", ".mjs", ".js", ".go", ""}
TEST_FILE = re.compile(r"(^test_|_test\.|\.test\.|selftest)")
# A command that puts a checkout at ANOTHER commit. `checkout -- <path>` restores a file; not this.
# Written in a shell line, or as an argument list (python/go: "checkout", "--detach").
MOVE = re.compile(
    r"\bgit\b[^\n#]*?\b(?:checkout\s+(?:(?:--quiet|-q)\s+)?(?:--detach|--force|-f\b)"
    r"|switch\s+(?:(?:--quiet|-q)\s+)?(?:--detach|-d\b)|reset\s+--hard)"
    r"""|["']checkout["']\s*,\s*["'](?:--detach|--force|-f)["']"""
    r"""|["']switch["']\s*,\s*["'](?:--detach|-d)["']|["']reset["']\s*,\s*["']--hard["']""")
GUARD = "merge-base --is-ancestor"
EXEMPT = {
    "apps/sites/runtime.py": "a published site's OWN repository, rebuilt from its branch; not an office",
    "scripts/ci-publish-e2e-results": "CI's results branch in a throwaway clone; not an office",
    "scripts/refactor/deploy-forward-lint.py": "this gate (its patterns and its own test repository)",
}


def tracked() -> list[Path]:
    out = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z", "--", *ROOTS],
                         capture_output=True, text=True, check=True).stdout
    files = []
    for rel in filter(None, out.split("\0")):
        p = Path(rel)
        if SKIP_PARTS & set(p.parts) or p.suffix not in SUFFIXES or TEST_FILE.search(p.name):
            continue
        files.append(p)
    return files


def find_moves(files: list[Path]) -> list[str]:
    """A: every checkout-mover outside the guarded code step and the exempt list."""
    found = []
    for rel in files:
        key = rel.as_posix()
        if key in EXEMPT:
            continue
        try:
            text = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in MOVE.finditer(text):
            # A comment that NAMES the command is not a script that runs it (packaging/qa-gallery-full.sh
            # explains why it never runs `git reset --hard`).
            if re.search(r"(^|\s)#", text[text.rfind("\n", 0, m.start()) + 1:m.start()]):
                continue
            # The guard must stand in the same script, before the move: the scope is the text from the
            # start of the enclosing python def / shell function (or the file) up to the move.
            start = max(text.rfind("\ndef ", 0, m.start()), text.rfind("() {", 0, m.start()), 0)
            if GUARD not in text[start:m.start()]:
                line = text.count("\n", 0, m.start()) + 1
                found.append(f"{key}:{line}: moves a checkout with no never-back guard before it: "
                             f"{m.group(0).strip()[:80]}")
    return found


def dcx_wiring(lib: str) -> list[str]:
    """B: dcx asks the ledger before it admits, and writes it after."""
    m = re.search(r"\ndcx\(\) \{\n(.*?)\n\}\n", lib, re.S)
    if not m:
        return ["scripts/lib.sh: no dcx() found"]
    body, bad = m.group(1), []
    g, a, r = body.find('deploy_ledger_gate "$@"'), body.find('compose_admit "$@"'), body.find('deploy_ledger_record "$@"')
    if g < 0:
        bad.append("scripts/lib.sh: dcx() does not call deploy_ledger_gate")
    elif a >= 0 and g > a:
        bad.append("scripts/lib.sh: dcx() asks the ledger only after compose_admit took the build slot")
    if r < 0:
        bad.append("scripts/lib.sh: dcx() never records what it deployed (deploy_ledger_record)")
    for fn in ("deploy_ledger_gate()", "deploy_ledger_record()"):
        if fn not in lib:
            bad.append(f"scripts/lib.sh: {fn} is not defined")
    return bad


LEDGER_PROBE = r'''
set -u
. "$LIB" >/dev/null 2>&1
ask() { deploy_ledger_gate "$@" >/dev/null 2>"$T/err"; echo "$?"; }
c() { git -C "$REPO_ROOT" -c advice.detachedHead=false checkout -q --detach "$1"; }
c "$C";  echo "none=$(ask up -d)"
deploy_ledger_record up -d;  echo "recorded=$(cut -d' ' -f1 "$DEPLOY_LEDGER")"
echo "same=$(ask up -d --build)"
c "$B";  echo "back_up=$(ask up -d)"; echo "back_build=$(ask build bina-ds)"
grep -q "feature C" "$T/err" && echo "named=1" || echo "named=0"
echo "back_ps=$(ask ps)"; echo "back_dry=$(ask up -d --dry-run)"; echo "back_config=$(ask config)"
echo "back_allowed=$(BBOX_ALLOW_ROLLBACK=1 ask up -d)"
c "$S";  echo "sideways=$(ask up -d)"
c "$B";  deploy_ledger_record exec web sh -c up;  echo "exec_kept=$(cut -d' ' -f1 "$DEPLOY_LEDGER")"
BBOX_ALLOW_ROLLBACK=1 deploy_ledger_record up -d;  echo "rolled=$(cut -d' ' -f1 "$DEPLOY_LEDGER")"
c "$C";  echo "forward=$(ask up -d)"
printf '%s x\n' 0123456789abcdef0123456789abcdef01234567 > "$DEPLOY_LEDGER"
c "$B";  echo "unknown=$(ask up -d)"
'''
# `forward` asks with the ledger at B and HEAD at C, so it goes through the ancestry test itself.
LEDGER_WANT = {"none": "0", "recorded": "<C>", "same": "0", "back_up": "1", "back_build": "1", "named": "1",
               "back_ps": "0", "back_dry": "0", "back_config": "0", "back_allowed": "0", "sideways": "1",
               "exec_kept": "<C>", "rolled": "<B>", "forward": "0", "unknown": "0"}


def _git(cwd: Path, *a: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *a], capture_output=True, text=True, check=True).stdout.strip()


def ledger_behaviour(lib_path: Path) -> list[str]:
    """C: the ledger, asked for real over a temporary repository."""
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        repo = t / "office"
        repo.mkdir()
        _git(repo, "init", "-q", "-b", "main")
        ids = {}
        for name in ("A", "B", "C"):
            (repo / name).write_text(name)
            _git(repo, "add", name)
            _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", f"feature {name}")
            ids[name] = _git(repo, "rev-parse", "HEAD")
        _git(repo, "checkout", "-q", "-b", "side", ids["B"])
        (repo / "S").write_text("S")
        _git(repo, "add", "S")
        _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "feature S")
        ids["S"] = _git(repo, "rev-parse", "HEAD")
        env = dict(os.environ, REPO_ROOT=str(repo), LIB=str(lib_path), T=str(t),
                   B=ids["B"], C=ids["C"], S=ids["S"], BBOX_ALLOW_ROLLBACK="0")
        r = subprocess.run(["bash", "-c", LEDGER_PROBE], capture_output=True, text=True, env=env)
        got = dict(ln.split("=", 1) for ln in r.stdout.splitlines() if "=" in ln)
        bad = []
        for k, want in LEDGER_WANT.items():
            want = ids[want[1]] if want in ("<B>", "<C>") else want
            if got.get(k) != want:
                bad.append(f"ledger: {k} answered {got.get(k)!r}, expected {want!r}")
        if bad and r.stderr.strip():
            bad.append("ledger probe stderr: " + r.stderr.strip()[-300:])
        return bad


def converge_behaviour() -> list[str]:
    """D: the code step's own script, run against real checkouts."""
    test = REPO / "apps/dgo-extend/tests/forward_only_selftest.py"
    if not test.exists():
        return [f"{test.relative_to(REPO).as_posix()} is missing"]
    r = subprocess.run([sys.executable, str(test)], capture_output=True, text=True)
    return [] if r.returncode == 0 else ["converge selftest: " + (r.stdout.strip().splitlines() or ["no output"])[-1]]


def self_test() -> int:
    """The scanner finds a planted unguarded move, passes a guarded one, and the ledger probe fails on
    a lib.sh whose gate always says yes (the pre-fix behaviour)."""
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        global REPO
        real = REPO
        try:
            REPO = t
            (t / "bad.sh").write_text('cd "$P"\ngit -c advice.detachedHead=false checkout --quiet --detach "$C"\n'
                                      '# a comment that names git reset --hard is not a move\n')
            (t / "good.sh").write_text('step() {\n  git merge-base --is-ancestor "$cur" "$C" || exit 3\n'
                                       '  git checkout --quiet --detach "$C"\n}\n')
            got = find_moves([Path("bad.sh"), Path("good.sh")])
        finally:
            REPO = real
        ok &= len(got) == 1 and got[0].startswith("bad.sh:2:")
        print(("PASS" if len(got) == 1 else "FAIL") + f" scanner: planted unguarded move found, guarded one passed ({got})")
        lib = (REPO / "scripts/lib.sh").read_text(encoding="utf-8")
        yes = t / "lib-pre-fix.sh"
        yes.write_text(lib.replace("deploy_ledger_gate() {", "deploy_ledger_gate() {\n  return 0", 1), encoding="utf-8")
        pre = ledger_behaviour(yes)
        ok &= bool(pre)
        print(("PASS" if pre else "FAIL") + f" ledger probe fails on a gate that always admits ({len(pre)} findings)")
        anc = 'git -C "${REPO_ROOT}" merge-base --is-ancestor "${was}" "${head}" && return 0'
        no = t / "lib-no-forward.sh"
        no.write_text(lib.replace(anc, "false && return 0", 1), encoding="utf-8")
        stuck = ledger_behaviour(no) if anc in lib else []
        ok &= any(f.startswith("ledger: forward ") for f in stuck)
        print(("PASS" if stuck else "FAIL") + f" ledger probe fails on a gate that refuses every move, forward too ({stuck[:1]})")
        ok &= not ledger_behaviour(REPO / "scripts/lib.sh")
        print(("PASS" if ok else "FAIL") + " ledger probe passes on this tree")
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return self_test()
    files = tracked()
    if "--files" in argv:
        print("\n".join(p.as_posix() for p in files))
        return 0
    if not files:
        print("G90 FAIL — no tracked script was found to scan (is this a git checkout?)")
        return 1
    lib = (REPO / "scripts/lib.sh").read_text(encoding="utf-8")
    findings = find_moves(files) + dcx_wiring(lib) + ledger_behaviour(REPO / "scripts/lib.sh") + converge_behaviour()
    print(f"G90 scanned {len(files)} tracked scripts for a checkout that moves; exempt: {len(EXEMPT)}; "
          f"ledger probe {len(LEDGER_WANT)} states; converge selftest run")
    for f in findings:
        print("  " + f)
    print("G90 " + ("FAIL" if findings else "PASS") + " — an office never deploys a tree that drops what it runs")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
