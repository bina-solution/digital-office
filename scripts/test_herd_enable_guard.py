#!/usr/bin/env python3
"""test_herd_enable_guard.py — `bbox apps enable` does not start an app the herd runs on another office (DGO-579).

    python3 scripts/test_herd_enable_guard.py       (G72 runs it; no PyYAML needed)

On 2026-10-14 an agent ran `bbox apps enable browser42` on vps1 while the herd's ONE browser was the HP's. This
holds, on a temp checkout with a herd file and a state file:
  * the guard refuses an app the herd places on another office, naming it; lets through its home office (by key
    or alias, any case, and a placement written by an alias), an app the herd does not place, an app already
    enabled here, a client's office (not the herd's), an office with no id, an office that declares ANOTHER
    herd whatever it is called, and `--anyway`; an office that declares the herd's own name is the herd's;
  * the office comes from the environment: a `--office` in the arguments is an unknown option;
  * bbox's own `apps enable` block (lifted out of bbox as it is, with lib.sh's read_env_value) asks the guard
    with the office's id and herd as `.env` gives them, quoted and commented, writes nothing when it refuses —
    `--office hp-laptop` typed after the app id included — writes when it passes, and drops `--anyway`;
  * an unknown option is refused by bbox's name, not the helper's.
On the code before DGO-579 there is no guard: bbox writes browser42's state on vps1.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FAILS: list[str] = []
HERD = """herd: Bina Solutions   # what its offices declare as DGO_HERD
offices:
  vps1:
    ssh: root@x
  hp-laptop:
    aliases: [hp]
  dell:
    aliases: [portable-ubuntu, portable]
apps:
  browser42: hp-laptop
  sites: vps1
  ollama: portable
"""
STATE = """schema_version: 1
apps:
  browser42: { state: disabled, by: user }
  sites:     { enabled: true }
  ollama:    { state: disabled }
"""


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"\n        {detail}"))
    if not ok:
        FAILS.append(name)


def tree() -> Path:
    root = Path(tempfile.mkdtemp(prefix="dgo579-"))
    (root / "scripts").mkdir()
    for f in ("herd_home.py", "herd_enable_guard.py"):
        if (REPO / "scripts" / f).is_file():
            shutil.copy(REPO / "scripts" / f, root / "scripts" / f)
    (root / "apps" / "computers").mkdir(parents=True)
    (root / "apps" / "computers" / "herd.yaml").write_text(HERD)
    (root / "platform.state.yaml").write_text(STATE)
    return root


def guard(root: Path, office: str, *argv: str, herd: str = "") -> tuple[int, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("DGO_GUARD_")}
    env.update(DGO_GUARD_OFFICE=office, DGO_GUARD_HERD=herd)
    r = subprocess.run([sys.executable, str(root / "scripts" / "herd_enable_guard.py"), *argv],
                       capture_output=True, text=True, timeout=30, env=env)
    return r.returncode, r.stdout


def lifted(path: Path, pattern: str) -> str:
    m = re.search(pattern, path.read_text(encoding="utf-8"), re.M | re.S)
    return m.group(0) if m else ""


def bbox_enable(root: Path, office_raw: str, *argv: str, herd_raw: str = "") -> tuple[int, str]:
    """bbox's `enable|disable)` block, lifted as it is, with set-state stubbed to log what it would write. `.env`'s
    raw values come through read_env; lib.sh's own read_env_value (lifted too) takes their quotes and comments off."""
    block = lifted(REPO / "bbox", r"^      enable\|disable\)\n.*?;;\n")
    value = lifted(REPO / "scripts" / "lib.sh", r"^read_env_value\(\) \{\n.*?^\}\n")
    if not block or not value:
        return 99, "bbox has no `enable|disable)` block, or lib.sh no read_env_value"
    script = f"""set -euo pipefail
REPO_ROOT='{root}'; cy=''; c0=''; LOG='{root}/log'
die() {{ echo "DIE $*" >> "$LOG"; exit 1; }}
say() {{ :; }}
read_env() {{ case "$1" in DGO_OFFICE_ID) printf '%s' '{office_raw}' ;; DGO_HERD) printf '%s' '{herd_raw}' ;; esac; }}
{value}
python3() {{
  case "$*" in *reconcile.py*set-state*) echo "WRITE $*" >> "$LOG"; return 0 ;; *reconcile.py*render*) return 0 ;; esac
  command '{sys.executable}' "$@"
}}
run_apps() {{
  sub="$1"; shift
  case "$sub" in
{block}  esac
}}
run_apps "$@"
"""
    (root / "log").unlink(missing_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("DGO_GUARD_")}
    r = subprocess.run(["bash", "-c", script, "bash", *argv], capture_output=True, text=True, timeout=30, env=env)
    return r.returncode, (root / "log").read_text() if (root / "log").exists() else ""


def main() -> int:
    root = tree()
    try:
        rc, out = guard(root, "vps1", "browser42")
        check("vps1 enabling browser42 (the herd runs it on hp-laptop): refused, naming hp-laptop",
              rc == 1 and "the herd runs browser42 on hp-laptop" in out and "--anyway browser42" in out, f"rc={rc} {out!r}")
        check("…and it gives no made-up address (a tile is <alias>.<the office's declared id>, not <app>.<key>)",
              "browser42.hp-laptop" not in out, out)
        rc, out = guard(root, "vps1", "ollama")
        check("a placement written by an alias (ollama: portable) names the office by its key",
              rc == 1 and "the herd runs ollama on dell" in out, f"rc={rc} {out!r}")
        rc, out = guard(root, "VPS1", "browser42", herd="bina solutions")
        check("an office that declares the herd's own name (any case) is the herd's", rc == 1, f"rc={rc} {out!r}")
        for name, office, argv, herd in (
                ("its home office lets it through", "hp-laptop", ("browser42",), ""),
                ("…by an alias of the home office too", "hp", ("browser42",), ""),
                ("…in any case", "HP-Laptop", ("browser42",), ""),
                ("a placement by alias: the office it names is home, by its key or another alias",
                 "portable-ubuntu", ("ollama",), ""),
                ("an app the herd does not place is not its business", "vps1", ("computers",), ""),
                ("an app already enabled here: enabling it again changes nothing", "hp-laptop", ("sites",), ""),
                ("a client's office (not the herd's) gets no word", "exampleu", ("browser42",), ""),
                ("an office with no id gets no word", "", ("browser42",), ""),
                ("an office called vps1 that declares ANOTHER herd is not ours: no word", "vps1", ("browser42",), "Acme"),
                ("--anyway lets it through", "vps1", ("--anyway", "browser42"), "")):
            rc, out = guard(root, office, *argv, herd=herd)
            check(name, rc == 0 and out == "", f"rc={rc} {out!r}")
        rc, out = guard(root, "vps1", "browser42", "--office", "hp-laptop")
        check("a `--office` in the arguments is an unknown option, not a choice of whose rule applies",
              rc == 2 and "unknown option --office" in out, f"rc={rc} {out!r}")

        # an office key YAML does not read as text (`no:` is False to PyYAML), listed first so every lookup walks
        # past it: the other offices keep their answers
        herd_file = root / "apps" / "computers" / "herd.yaml"
        herd_file.write_text(HERD.replace("offices:\n", "offices:\n  no:\n    label: Norway\n"))
        rc, out = guard(root, "vps1", "sites")
        check("a herd file with an office key that is not text (`no:`): its home office still enables its own app",
              rc == 0 and out == "", f"rc={rc} {out!r}")
        rc, out = guard(root, "vps1", "browser42")
        check("…and an app of another office is still refused with its reason, not with an empty one",
              rc == 1 and "the herd runs browser42 on hp-laptop" in out, f"rc={rc} {out!r}")
        herd_file.write_text(HERD)

        rc, log = bbox_enable(root, '"vps1"   # the VPS', "enable", "browser42")
        check("bbox apps enable browser42 on vps1 (.env quoted and commented): refused, and nothing is written",
              rc != 0 and "DIE browser42: the herd runs browser42 on hp-laptop" in log and "WRITE" not in log, f"rc={rc} {log!r}")
        rc, log = bbox_enable(root, "vps1", "enable", "browser42", "--office", "hp-laptop")
        check("bbox apps enable browser42 --office hp-laptop on vps1: refused, and nothing is written",
              rc != 0 and "unknown option --office" in log and "WRITE" not in log, f"rc={rc} {log!r}")
        rc, log = bbox_enable(root, "vps1", "enable", "browser42", herd_raw="'Acme'")
        check("bbox on an office called vps1 whose .env declares herd 'Acme': written", rc == 0 and "WRITE" in log,
              f"rc={rc} {log!r}")
        rc, log = bbox_enable(root, "vps1", "enable", "--anyway", "browser42")
        check("bbox apps enable --anyway browser42: written, without the --anyway word",
              rc == 0 and "set-state --app browser42 --state enabled" in log and "--anyway" not in log, f"rc={rc} {log!r}")
        rc, log = bbox_enable(root, "hp-laptop", "enable", "browser42", "computers")
        check("on its home office: both written", rc == 0 and log.count("WRITE") == 2, f"rc={rc} {log!r}")
        rc, log = bbox_enable(root, "vps1", "disable", "browser42")
        check("disable is never the guard's business", rc == 0 and "--state disabled" in log, f"rc={rc} {log!r}")
        rc, log = bbox_enable(root, "vps1", "enable", "--foo", "x")
        check("an unknown option is refused in bbox's words", rc != 0 and "DIE bbox apps enable: unknown option --foo" in log,
              f"rc={rc} {log!r}")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print(f"\n{'all passed' if not FAILS else f'{len(FAILS)} failed'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
