#!/usr/bin/env python3
"""test_rename_address — the pieces of FPG-34 that run as shell: the `accounts` step's detached script, the
ledger the hooks keep (scripts/lib.sh rename_note), the key reader and the key writer (read_env_value,
env_set), and connections' verdict over the ledger — each run for real, in bash, in a scratch folder.

The readers found what a mock could not: under `set -e` the script lost its RC line exactly when an app
refused (and a refusal stopped the converge); the ledger's `-` placeholder read as an owner; `sed -i`
replaced a linked .env with a copy. These run the real text.

Run: python3 apps/dgo-extend/tests/test_rename_address.py   (needs bash, awk, flock — the app's image has them)
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import converge  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
FAIL = []


def check(cond, what):
    if not cond:
        FAIL.append(what)


def bash(script: str, cwd: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", script], cwd=cwd, capture_output=True, text=True, timeout=60,
                          env={**os.environ, **(env or {})})


def test_detached_script():
    """What start_detached runs: `set -e` above rename_script — a failing bbox still says RC and CHANGED."""
    with tempfile.TemporaryDirectory() as d:
        Path(d, "bbox").write_text("#!/bin/bash\necho '[bbox] rename-address: first pass'\necho '[bbox] [x] waiting'\n"
                                   "echo '[bbox] rename-address: second pass (the verdict)'\n"
                                   "echo '[bbox] [plane] NOT moved'\n"
                                   "if { : >&9; } 2>/dev/null; then echo '[bbox] fd9 open'; else echo '[bbox] fd9 closed'; fi\n"
                                   "echo CHANGED=1\nexit 3\n")
        os.chmod(Path(d, "bbox"), 0o755)
        out = bash("set -e\n" + converge.rename_script(d, "old.example", "new.example"), d)
        facts = converge.parse_facts(out.stdout)
        check(out.returncode == 0 and facts.get("RC") == "3" and facts.get("CHANGED") == "1",
              f"a refusing bbox under set -e still reports RC=3 and CHANGED=1: rc={out.returncode} {out.stdout!r}")
        check("[x] waiting" not in out.stdout and "[plane] NOT moved" in out.stdout,
              "only the verdict pass is kept")
        check("fd9 closed" in out.stdout, f"bbox (and a dockerd it starts) never inherits the lock's fd: {out.stdout!r}")
        check(not Path(d, ".dgo-rename-address.lock").exists() and Path(d, "data/.locks/rename-address.lock").exists(),
              "the lock lives in data/.locks (gitignored), never beside the code")
        lock = Path(d, "data/.locks/rename-address.lock")
        # its own process group: killing only `flock` would leave its `sleep` holding the lock
        busy = subprocess.Popen(["flock", "-x", str(lock), "sleep", "5"], start_new_session=True)
        try:
            import time
            time.sleep(0.5)
            out = bash("set -e\n" + converge.rename_script(d, "old.example", "new.example"), d)
            check(converge.parse_facts(out.stdout).get("RC") == "busy",
                  f"a run while another holds the lock says RC=busy and moves nothing: {out.stdout!r}")
        finally:
            os.killpg(busy.pid, 9)
            busy.wait()
    # a lock this user cannot take (data/.locks a root container made, here a FILE so it fails even as
    # root) is skipped, never fatal — as heavy_admit treats the same directory
    with tempfile.TemporaryDirectory() as d:
        Path(d, "bbox").write_text("#!/bin/bash\necho '[bbox] rename-address: second pass (the verdict)'\necho CHANGED=0\n")
        os.chmod(Path(d, "bbox"), 0o755)
        Path(d, "data").mkdir()
        Path(d, "data/.locks").write_text("")
        out = bash("set -e\n" + converge.rename_script(d, "old.example", "new.example"), d)
        check(out.returncode == 0 and converge.parse_facts(out.stdout).get("RC") == "0",
              f"an unusable lock directory: the run goes on and reports RC=0: rc={out.returncode} {out.stdout!r} {out.stderr[-200:]!r}")


LIB = ROOT / "scripts" / "lib.sh"


def test_lib_helpers():
    with tempfile.TemporaryDirectory() as d:
        etc = Path(d, "etc")
        etc.mkdir()
        real = etc / "binaos.env"
        real.write_text('A="admin@old.example" # the owner\nB=admin@old.example # c\nC="has # inside"\nD=x\n')
        os.chmod(real, 0o600)
        Path(d, ".env").symlink_to(real)
        ledger = Path(d, "ledger")
        out = bash(f'. "{LIB}"; for k in A B C; do printf "%s=[%s]\\n" $k "$(read_env_value $k)"; done; '
                   'rename_note N8N_OWNER_EMAIL present "Admin,bob,"; rename_note N8N_OWNER_EMAIL behind ""; '
                   'rename_note PLANE_OWNER_EMAIL failed; rename_note - changed; rename_note "" present x; '
                   'env_set D "y&z#w\\\\q" && env_set NEW "v" && ! env_set bad v 2>/dev/null && echo SET-OK',
                   d, {"REPO_ROOT": d, "DGO_RENAME_LEDGER": str(ledger)})
        check("A=[admin@old.example]" in out.stdout and "B=[admin@old.example]" in out.stdout
              and "C=[has # inside]" in out.stdout, f"values read as compose reads them: {out.stdout!r} {out.stderr[-300:]!r}")
        check(ledger.read_text() == "N8N_OWNER_EMAIL present admin\nN8N_OWNER_EMAIL present bob\n"
              "PLANE_OWNER_EMAIL failed -\n- changed -\n", f"the ledger lines: {ledger.read_text()!r}")
        text = real.read_text()
        check("SET-OK" in out.stdout and Path(d, ".env").is_symlink() and "D=y&z#w\\q\n" in text and "NEW=v" in text
              and (real.stat().st_mode & 0o777) == 0o600 and not [p for p in etc.iterdir() if p.name != "binaos.env"],
              f"env_set writes the real file whole, keeps the link and the mode, leaves nothing beside it: {text!r}")


VERDICT = re.search(r"^verdict\(\) \{.*?^\}\n", (ROOT / "platform-base/connections/hooks/rename-address").read_text(),
                    re.S | re.M).group(0)


def test_connections_verdict():
    """connections' verdict, the function itself, over a ledger the hooks would leave."""
    with tempfile.TemporaryDirectory() as d:
        ledger = Path(d, "ledger")
        ledger.write_text("N8N_OWNER_EMAIL present admin\nN8N_OWNER_EMAIL behind ops\nPLANE_OWNER_EMAIL failed -\n"
                          "TRAEFIK_ACME_EMAIL any -\n- changed -\nA.B present x\nNUM_KEY behind 007\n")
        cases = {("N8N_OWNER_EMAIL", "admin"): "follow", ("N8N_OWNER_EMAIL", "ops"): "wait",
                 ("NUM_KEY", "7"): "follow", ("NUM_KEY", "007"): "wait",
                 ("PLANE_OWNER_EMAIL", "admin"): "wait", ("TRAEFIK_ACME_EMAIL", "anyone"): "follow",
                 ("-", "support"): "unowned", ("CUSTOM_KEY", "admin"): "unowned", ("AxB", "x"): "unowned"}
        for (key, who), want in cases.items():
            out = bash(f'. "{LIB}"; NEW=new.example; LEDGER="{ledger}"\n{VERDICT}verdict "{key}" "{who}"', d,
                       {"REPO_ROOT": d})
            check(out.stdout.strip() == want and not out.stderr.strip(),
                  f"verdict {key} {who}: {out.stdout.strip()!r} (want {want}) {out.stderr.strip()[:200]!r}")


BBOX_RENAME = re.search(r"^    # every enabled app's hook, twice.*?^    exit \"\$\{rc\}\" ;;\n",
                        (ROOT / "bbox").read_text(), re.S | re.M).group(0).replace('exit "${rc}" ;;', 'echo "EXIT=${rc}"')
STRICT = "set -euo pipefail\n"


def test_pending_renames():
    """An app that is OFF when the office changes domain is noted, and moves when it is on — lib.sh for real,
    under bbox's own `set -euo pipefail`, over a stand-in compiler, in a path with spaces: one line per app,
    every domain its people may be on, moved STRAIGHT to the office's domain (a round trip is one short move);
    every rename retargets every waiting line; each distinct move is replayed ONCE, in a rename's own shape
    over every app that is on (a throwaway first pass, then the verdict pass twice on one ledger — so the
    vault follows whatever its order); every app's own last verdict decides for it, and an app that fails
    waits on a line of its own; a read or write that fails is a failure; under the lock."""
    with tempfile.TemporaryDirectory() as base:
        d = str(Path(base, "a repo with spaces"))       # the Mac's checkout has them
        Path(d, "platform/manager").mkdir(parents=True)
        Path(d, "platform/manager/reconcile.py").write_text(
            "import pathlib, sys\nif pathlib.Path('broken').exists():\n    sys.exit(1)\n"
            "print(pathlib.Path('enabled.txt').read_text(), end='')\n")
        on = Path(d, "enabled.txt")
        on.write_text("apps a1\nplatform-base cx\n")
        log, note = Path(d, "hook.log"), Path(d, "data/.locks/rename-pending")
        Path(d, "data/.locks").mkdir(parents=True)
        lock = Path(d, "data/.locks/rename.lock")
        hooks = {
            # an app that moves people: its first try fails («failed» in the ledger), its verdict finds them
            # moved («present») — and it says whether it runs under the rename lock
            "gt": '[ "$DGO_RENAME_PASS" = 1 ] && echo "GT_KEY failed -" >>"$DGO_RENAME_LEDGER"\n'
                  '[ "$DGO_RENAME_PASS" = 2 ] && echo "GT_KEY present admin" >>"$DGO_RENAME_LEDGER"\n'
                  f'echo "gt-lock=$(flock -n "{lock}" true 2>/dev/null && echo free || echo held)" >>"{log}"\n',
            # the vault: in the verdict pass it follows only whom another app moved — it must see gt's FINAL
            # fact, and never the «failed» of gt's first try (it would wait on a person already moved)
            "cx": '[ "$DGO_RENAME_PASS" = 2 ] && echo "cx-saw-gt=$(grep -c "GT_KEY present" "$DGO_RENAME_LEDGER") '
                  'cx-saw-failed=$(grep -c "GT_KEY failed" "$DGO_RENAME_LEDGER")" >>"' + str(log) + '"\n'
                  # its verdict, as the real vault decides it: follow only a person an app stated present
                  '[ "$DGO_RENAME_PASS" = 2 ] && { grep -q "GT_KEY present" "$DGO_RENAME_LEDGER" && echo cx-verdict=follow '
                  '|| echo cx-verdict=unowned; } >>"' + str(log) + '"\n',
            "a1": "", "zz": "",
        }
        for root, aid in (("apps", "a1"), ("platform-base", "gt"), ("platform-base", "cx"), ("apps", "zz")):
            Path(d, root, aid, "hooks").mkdir(parents=True)
            hook = Path(d, root, aid, "hooks", "rename-address")
            hook.write_text(f'#!/bin/bash\nin="$(cat)"\necho "{aid} $DGO_RENAME_FROM $DGO_RENAME_TO $DGO_RENAME_PASS '
                            f'stdin=[$in]" >>"{log}"\n' + hooks[aid] +
                            f'exit "$(cat "{d}/{aid}.rc" 2>/dev/null || echo 0)"\n')
            os.chmod(hook, 0o755)
        Path(d, "zz.rc").write_text("1")                # an app with a standing refusal of its own
        env = {"REPO_ROOT": d}

        def sh(script):
            return bash(STRICT + f'. "{LIB}"\n' + script, d, env)
        dry = sh("note_pending_renames o1 o2 1")
        check("DRY RUN" in dry.stdout and not note.exists(), f"a dry run notes nothing: {dry.stdout!r} {dry.stderr[-200:]!r}")
        out = sh("note_pending_renames o1 o2 0; note_pending_renames o1 o2 0; note_pending_renames o2 o3 0")
        check(note.read_text() == "zz o3 o1,o2\ngt o3 o1,o2\n" and "gt is off here" in out.stdout,
              f"each app that is off: one line, the office's domain, every domain its people may be on: {note.read_text()!r}")
        # a round trip is one short move, never the legs again: A→B, B→A leaves «from B to A»
        saved = note.read_text()
        note.unlink()
        sh("note_pending_renames A B 0; note_pending_renames B A 0")
        check(note.read_text() == "zz A B\ngt A B\n", f"a round trip: {note.read_text()!r}")
        # EVERY waiting line owes the new domain: an app that is on but still waits, and one whose hook is gone
        note.write_text("a1 x2 x1\nqq q2 q1\n")
        out = sh("note_pending_renames x2 x3 0")
        check(note.read_text() == "a1 x3 x1,x2\nqq x3 q1,x2\nzz x3 x2\ngt x3 x2\n"
              and "a1 still waits" in out.stdout and "qq still waits" in out.stdout,
              f"every waiting line is retargeted: {note.read_text()!r} {out.stdout!r}")
        # a note that is there and cannot be read is a failure — never «nothing waits», which drops its lines
        note.unlink()
        note.mkdir()
        r = sh('note_pending_renames z1 z2 0 || echo "NOTE-FAILED"')
        check("NOTE-FAILED" in r.stdout and "cannot be read" in r.stdout, f"an unreadable note is a failure: {r.stdout!r}")
        note.rmdir()
        # which apps are on could not be read: nothing is noted (never «every app is off», replaying them all)
        Path(d, "broken").write_text("")
        r = sh('note_pending_renames z1 z2 0 || echo "NOTE-FAILED"')
        check("NOTE-FAILED" in r.stdout and "could not be read" in r.stdout and not note.exists(),
              f"no app list is a failure, and nothing is noted: {r.stdout!r}")
        Path(d, "broken").unlink()
        note.write_text(saved)
        # a note that cannot be written is a failure, said — never an abort under set -e, never «they will follow»
        Path(d, "data/.locks").rename(Path(d, "locks-dir"))
        Path(d, "data/.locks").write_text("a file where the folder should be")
        r = sh('note_pending_renames y1 y2 0 || echo "NOTE-FAILED"')
        check("NOTE-FAILED" in r.stdout and "could not be noted" in r.stdout, f"an unwritable note is a failure: {r.stdout!r} {r.stderr!r}")
        # …and bbox's own lines still say CHANGED, then the note's failure, then the exit code
        Path(d, "platform-base/cx/hooks/rename-address").write_text(
            Path(d, "platform-base/cx/hooks/rename-address").read_text().replace(
                "exit ", 'echo "- changed -" >>"$DGO_RENAME_LEDGER"\nexit ', 1))
        r = sh('old=y1 new=y2 dry=0\n' + BBOX_RENAME)
        o = r.stdout
        check("CHANGED=1" in o and "EXIT=1" in o and o.index("CHANGED=1") < o.index("could not be noted") < o.index("EXIT=1"),
              f"bbox: CHANGED is said, then the note's failure, and the rename exits non-zero: {o!r} {r.stderr[-300:]!r}")
        Path(d, "data/.locks").unlink()
        Path(d, "locks-dir").rename(Path(d, "data/.locks"))
        # gt and zz are turned on; both fail — each keeps its own line, whole
        on.write_text("apps a1\nplatform-base gt\nplatform-base cx\napps zz\n")
        Path(d, "gt.rc").write_text("1")
        log.write_text("")
        r = sh('run_pending_renames && echo RC=0 || echo "RC=$?"')
        check("RC=1" in r.stdout and sorted(note.read_text().splitlines()) == sorted(saved.splitlines()),
              f"a failed move keeps the app's line: {r.stdout!r} {note.read_text()!r}")
        # now gt moves: from each domain straight to o3, in a rename's own shape over every app that is on —
        # a first pass, then the verdict pass twice on one fresh ledger; on no stdin; under the rename lock
        Path(d, "gt.rc").write_text("0")
        Path(d, "zz.rc").write_text("0")
        note.write_text("gt o3 o1,o2\n")
        log.write_text("")
        r = sh('run_pending_renames && echo RC=0 || echo "RC=$?"')
        lines = log.read_text().splitlines()
        o1 = [ln for ln in lines if " o1 o3 " in ln]
        every = ["a1", "gt", "cx", "zz"]
        check("RC=0" in r.stdout and not note.exists()
              and o1 == [f"{a} o1 o3 {p} stdin=[]" for p in (1, 2, 2) for a in every]
              and any(" o2 o3 " in ln for ln in lines) and not any(" o1 o2 " in ln for ln in lines),
              f"each domain straight to the office's, every app, three passes: {r.stdout!r} {lines}")
        seen = [ln for ln in lines if ln.startswith("cx-saw")]
        check(len(seen) == 4 and all("cx-saw-failed=0" in s and "cx-saw-gt=0" not in s for s in seen),
              f"the vault sees gt's final facts, never the «failed» of its first try: {seen}")
        check(lines.count("gt-lock=held") == len([ln for ln in lines if ln.startswith("gt-lock=")]) > 0,
              f"the replay runs under the rename lock: {[ln for ln in lines if ln.startswith('gt-lock=')]}")
        # the vault fails beside gt's move: gt is done; the vault waits on a line of its own
        note.write_text("gt o3 o1\n")
        Path(d, "cx.rc").write_text("1")
        r = sh('run_pending_renames && echo RC=0 || echo "RC=$?"')
        check("RC=1" in r.stdout and note.read_text() == "cx o3 o1\n" and "cx did not finish its move" in r.stdout,
              f"a vault that fails beside the move waits on its own line: {r.stdout!r} {note.read_text()!r}")
        # …and when the VAULT is the app that waits — and runs BEFORE the app that moved the people — its last
        # verdict still follows them: the verdict pass runs twice on one ledger (one pass would read nothing)
        Path(d, "cx.rc").write_text("0")
        on.write_text("apps a1\nplatform-base cx\nplatform-base gt\napps zz\n")
        log.write_text("")
        r = sh('run_pending_renames && echo RC=0 || echo "RC=$?"')
        verdicts = [ln for ln in log.read_text().splitlines() if ln.startswith("cx-verdict=")]
        check("RC=0" in r.stdout and not note.exists() and verdicts[:1] == ["cx-verdict=unowned"]
              and verdicts[-1:] == ["cx-verdict=follow"],
              f"the vault before gt: unowned at first, follow in its last verdict: {r.stdout!r} {verdicts}")
        on.write_text("apps a1\nplatform-base gt\nplatform-base cx\napps zz\n")
        # a move that cannot even start (no temporary ledger): every app waiting on it keeps its line — never
        # «moved» by default
        note.write_text("gt o3 o1\nzz o3 o1\n")
        log.write_text("")
        r = sh('mktemp() { return 1; }\nrun_pending_renames && echo RC=0 || echo "RC=$?"')
        check("RC=1" in r.stdout and sorted(note.read_text().splitlines()) == ["gt o3 o1", "zz o3 o1"]
              and log.read_text() == "" and "could not start" in r.stdout,
              f"a move that cannot start keeps every waiting line: {r.stdout!r} {note.read_text()!r}")
        # one move, many apps waiting on it: replayed ONCE (each hook three times), not once per line
        note.write_text("gt o3 o1\nzz o3 o1\n")
        log.write_text("")
        r = sh('run_pending_renames && echo RC=0 || echo "RC=$?"')
        runs = [ln for ln in log.read_text().splitlines() if ln.startswith("a1 o1 o3 ")]
        check("RC=0" in r.stdout and not note.exists() and len(runs) == 3,
              f"a move several apps wait on is replayed once: {len(runs)} runs of a1 {r.stdout!r}")
        # an app's own standing refusal never holds another app back
        note.write_text("gt o3 o1\n")
        Path(d, "zz.rc").write_text("1")
        r = sh('run_pending_renames && echo RC=0 || echo "RC=$?"')
        check("RC=1" in r.stdout and note.read_text() == "zz o3 o1\n",
              f"zz's refusal is zz's line, gt is done: {r.stdout!r} {note.read_text()!r}")
        Path(d, "zz.rc").write_text("0")
        note.unlink()
        # one at a time: while a rename holds the lock, the replay waits its minute, then leaves it to the next run
        note.write_text("gt o3 o1\n")
        held = Path(d, "held")
        r = sh(f'flock "{lock}" sh -c \'touch "{held}"; sleep 4\' &\nwhile [ ! -e "{held}" ]; do sleep 0.1; done\n'
               'BBOX_RENAME_REPLAY_WAIT=1 run_pending_renames && echo RC=0 || echo "RC=$?"\nwait')
        check("RC=1" in r.stdout and "could not be taken" in r.stdout and note.read_text() == "gt o3 o1\n",
              f"a replay never runs beside a rename: {r.stdout!r} {r.stderr[-200:]!r}")
        # a note that cannot be rewritten is a failure, and the note stays as it was (the moves done are redone,
        # a no-op, by the next run)
        note.write_text("gt o3 o1\nqq o3 q1\n")
        Path(d, "data/.locks/rename-pending.new").mkdir()
        r = sh('run_pending_renames && echo RC=0 || echo "RC=$?"')
        check("RC=1" in r.stdout and "could not be rewritten" in r.stdout and note.read_text() == "gt o3 o1\nqq o3 q1\n",
              f"a rewrite that fails is a failure, the note unchanged: {r.stdout!r}")


def main() -> int:
    for t in (test_detached_script, test_lib_helpers, test_connections_verdict, test_pending_renames):
        before = len(FAIL)
        t()
        print(("PASS " if len(FAIL) == before else "FAIL ") + t.__name__)
    for f in FAIL:
        print("FAIL", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
