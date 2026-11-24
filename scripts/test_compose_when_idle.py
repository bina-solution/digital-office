#!/usr/bin/env python3
"""test_compose_when_idle.py — an `up` never recreates an app at work under its people (DGO-2129).

On 2026-11-19 the HP's follow took dgo-stable, and its `bbox run` recreated bina-claude-desktop-hp at 18:39Z with
every agent session of the office in it. An app that hosts such work says `"recreate": "when-idle"` in its app.json,
and its hooks/busy says when it is at work (exit 0 and a line; exit 1 when idle).

1. dcx (scripts/lib.sh), read out of lib.sh as it is, with compose, the catalog (when_idle.py) and the app's hooks
   played by stubs. A container's id and start time are what say it was recreated or restarted, never the command.
     busy                       → everything else goes up; the app is not built, not backed up, not recreated; it is
                                  held, said, and noted in data/.held/ with the build it waits for
     idle                       → the rest first; then its build, asked again, its backup, its up, its file mounts'
                                  refresh, and the resume, told only what changed
     busy during the build      → held after the build: no window for a session started meanwhile
     BBOX_RECREATE_BUSY=1       → the go: recreated though busy, with the backup and the resume
     a command names it         → no go: held when busy (a restart noted as a force), and it exits 75; with the go, a
                                  restart resumes only what restarted
     follow names it            → (BBOX_RECREATE_WHEN_IDLE=1) waits for a quiet moment like a whole-stack up, exit 0
     a held note that built     → follow's later `up` builds first, and the note goes only once it went up
     a held note that forced    → follow's later `up` forces the recreate it asked for (never beside --no-recreate)
     a held restart             → comes back as a restart, never a recreate it did not ask for
     it, and another service    → the other goes up with its refreshes; the command exits 75
     a hook it ships unreadable → held (a path gone, an EIO): never a recreate on a guess
     a relative hooks folder    → found from this checkout (the last list read may come from another path)
     its up fails               → the note stays; the command fails
     a backup that fails        → held when idle; with the go the command fails, never a false ok
     a hook that cannot answer, an engine that cannot say what runs → taken as at work, running
     a catalog that cannot be read → the last list read holds; with none ever read, the command runs, said
     nothing changed            → no resume; the note goes (it is as declared)
     a service that needs it    → waits with it (compose would recreate it for its dependent)
     it does not run            → nothing waits: nobody to cut
     another app, `logs`, a dry run → untouched, and nobody is asked
2. The real apps/bina-claude/hooks/busy and at-work.py, against a desktop's home played by files: a session counts
   only while its process runs (the pid's start tick is the file's procStart), an idle one with a Bash job of its own
   still running counts too, and the hook keeps the busy contract.
3. when_idle.py's rule for the services that need a «when-idle» app's own.
On the code before DGO-2129, dcx passes the whole `up` to compose: the first check of part 1 fails, and parts 2–3
have nothing to run. Needs bash and python3; part 2 needs Linux's /proc.
"""
import importlib.util
import json
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
LIB = HERE / "lib.sh"
WANT = ("dcx", "when_idle_hook", "when_idle_busy", "when_idle_held", "when_idle_marks", "compose_when_idle_split",
        "compose_when_idle_up", "compose_self_guard", "compose_self_helper")
APP = "bina-claude bina-claude-desktop bina-claude-desktop-home"
SERVICES = APP.split() + ["n8n", "console"]
RUNNING = ["bina-claude", "bina-claude-desktop", "n8n", "console"]          # the home maker is a one-shot, exited

STUBS = r"""
set -uo pipefail
say() { echo "[bbox] $*"; }; warn() { echo "[bbox] warn: $*"; }; die() { echo "die: $*"; exit 1; }
cy=; cr=; c0=; BBOX_COMPOSE=/bin/true
_dcx_exec_direct() { return 1; }; export_host_tz() { :; }; export_cert_resolver() { :; }
compose_is_recreate() { return 1; }; ccr_clamp_nofile() { :; }; bbox_assert_engine_socket() { :; }
deploy_ledger_gate() { return 0; }; compose_admit() { return 0; }
compose_is_up() { local a; for a in "$@"; do case "$a" in up) return 0 ;; -*) ;; *) return 1 ;; esac; done; return 1; }
filemount_refresh() { echo "$*" >> "$T/fm"; }; netns_rejoin() { :; }; cpu_caps_apply() { :; }; deploy_ledger_record() { :; }
# run from the host, as follow is: the self guard (a command that would replace its own container) does not apply. This
# test is often run from inside an agent's container, the very Claude Desktop it is about.
bbox_self_service() { return 1; }
docker() { [ "$1 $2" = "inspect -f" ] && cat "$T/start.$4" 2>/dev/null; return 0; }
# compose: the services, the running ones, each one's container (an up makes a new one, a restart a new start), and
# what was run
_dcx_run() {
  case "$*" in
    "config --services") printf '%s\n' __SERVICES__ ;;
    "ps --services --status running")
      [ -f "$T/ps-fails" ] && return 1
      if [ -f "$T/running" ]; then cat "$T/running"; else printf '%s\n' __RUNNING__; fi ;;
    "ps -a --format {{.Service}} {{.ID}}"*) shift 4; for s in "$@"; do [ -f "$T/id.$s" ] && echo "$s $(cat "$T/id.$s")"; done ;;
    *) echo "$*" >> "$T/ran"
       local sub="$1" names="" s n id; shift
       for s in "$@"; do case "$s" in -*) ;; *) names="$names $s" ;; esac; done
       case "$sub" in
         build) : > "$T/built" ;;
         up|create)
           if [ -f "$T/up-fails" ] && [[ " $names " == *" bina-claude-desktop "* ]]; then return 1; fi
           # a one-shot (the home maker) runs again at every up that names it, changed or not
           if [ -f "$T/oneshot-runs" ] && [[ " $names " == *" bina-claude-desktop-home "* ]]; then
             id="$(cat "$T/id.bina-claude-desktop-home")"; echo ran-again > "$T/start.$id"; fi
           [ -f "$T/no-change" ] && return 0
           for s in ${names:-__SERVICES__}; do
             n=$(( $(cat "$T/n" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$T/n"
             echo "$s-c$n" > "$T/id.$s"; echo "t$n" > "$T/start.$s-c$n"
           done ;;
         restart) for s in ${names:-__SERVICES__}; do id="$(cat "$T/id.$s" 2>/dev/null)" && echo restarted > "$T/start.$id"; done ;;
       esac ;;
  esac
}
"""


def functions(text: str) -> str:
    """The functions as lib.sh has them. One it lacks is left out: on the code before DGO-2129, dcx is still read out
    and run, and it is the one that hands the whole `up` to compose."""
    out = []
    for name in WANT:
        m = re.search(rf"^{name}\(\) \{{.*?^\}}\n", text, re.S | re.M)
        if m:
            out.append(m.group(0))
    if not any(o.startswith("dcx()") for o in out):
        raise SystemExit("FAIL  scripts/lib.sh no longer defines dcx() — nothing to test")
    for line in text.splitlines():      # the globals (not functions; the old code has only the self guard's)
        if re.match(r"^(DCX_MAIN_ARGS|DCX_LATER_PRE|DCX_LATER_SUB|DCX_LATER_OPTS|COMPOSE_LATER|COMPOSE_GUARD_RC|COMPOSE_SELF)=", line):
            out.append(line + "\n")
    return "".join(out)


class Checks:
    def __init__(self):
        self.bad = 0

    def __call__(self, ok, what, out=""):
        print(("PASS  " if ok else "FAIL  ") + what)
        if not ok:
            self.bad += 1
            print("\n".join("        " + l for l in str(out).splitlines()[-14:]))


def part_dcx(check):
    text = LIB.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as t:
        tp = pathlib.Path(t)
        hooks = tp / "repo/apps/bina-claude/hooks"
        hooks.mkdir(parents=True)
        (tp / "repo/platform/manager").mkdir(parents=True)
        (tp / "repo/platform/manager/when_idle.py").write_text(
            "import os, sys\np = os.path.join(os.environ['T'], 'catalog')\n"
            "os.path.exists(os.path.join(os.environ['T'], 'catalog-fails')) and sys.exit(1)\n"
            f"print(open(p).read().strip() if os.path.exists(p) else "
            f"'bina-claude\\t{APP}\\t-\\t{hooks}\\t-\\t-\\tbusy,before-recreate,after-recreate')\n")
        (hooks / "busy").write_text(
            'echo busy >> "$T/hooks"\n[ -f "$T/busy-hangs" ] && exit 124\n'
            '[ -f "$T/busy-after-build" ] && [ -f "$T/built" ] && { echo "a session started during the build"; exit 0; }\n'
            '[ -f "$T/busy" ] && { cat "$T/busy"; exit 0; }\nexit 1\n')
        (hooks / "before-recreate").write_text(
            'echo "before $DGO_RECREATE_SERVICES" >> "$T/hooks"\n[ -f "$T/backup-fails" ] && { echo "disk full"; exit 1; }\nexit 0\n')
        (hooks / "after-recreate").write_text('echo "after $DGO_RECREATE_SERVICES" >> "$T/hooks"\n')
        body = STUBS.replace("__SERVICES__", " ".join(SERVICES)).replace("__RUNNING__", " ".join(RUNNING))
        script = tp / "dcx.sh"
        script.write_text(f"REPO_ROOT={tp / 'repo'}\n" + body + functions(text) + 'dcx "$@"; echo "rc=$?"\n')
        held_dir = tp / "repo/data/.held"

        def run(*args, env=None, files=(), note=None, keep_cache=False):
            for p in tp.iterdir():
                if p.is_file() and p.name != "dcx.sh":
                    p.unlink()
            cache = tp / "repo/data/when-idle.apps"
            kept = cache.read_text() if keep_cache and cache.exists() else None
            shutil.rmtree(tp / "repo/data", ignore_errors=True)
            if kept is not None:
                cache.parent.mkdir(parents=True)
                cache.write_text(kept)
            for s in SERVICES:
                (tp / f"id.{s}").write_text(f"{s}-old\n")
                (tp / f"start.{s}-old").write_text("t0\n")
            for f in files:
                name, _, content = f.partition("=")
                (tp / name).write_text(content + "\n" if content else "")
            if note:
                held_dir.mkdir(parents=True, exist_ok=True)
                for s, line in note.items():
                    (held_dir / s).write_text(line + "\n")
            e = {**os.environ, "T": str(tp)}
            for k in ("BBOX_RECREATE_BUSY", "BBOX_RECREATE_WHEN_IDLE"):
                e.pop(k, None)
            e.update(env or {})
            r = subprocess.run(["bash", str(script), *args], capture_output=True, text=True, env=e, timeout=60)
            read = lambda n: (tp / n).read_text().splitlines() if (tp / n).exists() else []
            made = {}
            for s in SERVICES:
                cid = (tp / f"id.{s}").read_text().strip()
                start = (tp / f"start.{cid}").read_text().strip() if (tp / f"start.{cid}").exists() else ""
                made[s] = "recreated" if cid != f"{s}-old" else ("restarted" if start == "restarted" else "")
            held = {p.name: p.read_text().rstrip("\n").split("\t") for p in held_dir.glob("*")} if held_dir.exists() else {}
            return dict(out=r.stdout + r.stderr, ran=read("ran"), hooks=read("hooks"), fm=read("fm"), made=made, held=held)

        BUSY = "busy=9 Claude session(s) at work"
        rest = "n8n console"

        r = run("up", "-d", "--build", files=[BUSY])
        check(r["made"]["bina-claude-desktop"] == "" and r["made"]["bina-claude"] == "" and r["made"]["n8n"] == "recreated",
              "busy: a take's `up --build` leaves the app's running containers alone (DGO-2129's incident)", r)
        check(r["ran"] == [f"up -d --build {rest}"], "busy: everything else goes up, and the app is not even built", r)
        check(sorted(r["held"]) == APP.split() and all(v[3] == "build" for v in r["held"].values())
              and "held: bina-claude bina-claude-desktop" in r["out"] and "rc=0" in r["out"],
              "busy: it is said, and noted in data/.held/ with the build it waits for", r)
        check(r["hooks"] == ["busy"], "busy: asked once; no backup, no resume", r)
        check(r["fm"] == [f"up -d --build {rest}"], "busy: the rest's file-mount refresh never names it", r)

        r = run("up", "-d", "--build")
        check(r["ran"] == [f"up -d --build {rest}", f"build {APP}", f"up -d {APP}"],
              "idle: the rest first; then its build, and its up", r)
        check(r["hooks"] == ["busy", "busy", f"before {APP}", f"after {APP}"],
              "idle: asked before and after its build, the backup, then the resume of what changed", r)
        check(all(v == "recreated" for v in r["made"].values()) and r["held"] == {} and f"up {APP}" in r["fm"],
              "idle: all of it recreated, nothing held, and its file mounts refreshed in its own window", r)

        r = run("up", "-d", "--build", files=["busy-after-build"])
        check(r["ran"] == [f"up -d --build {rest}", f"build {APP}"] and r["made"]["bina-claude-desktop"] == ""
              and r["hooks"] == ["busy", "busy"] and "after its build" in r["out"]
              and r["held"].get("bina-claude-desktop", ["", "", "", ""])[3] == "build",
              "a session that starts during its build holds it: the build leaves no window", r)

        r = run("up", "-d", env={"BBOX_RECREATE_BUSY": "1"}, files=[BUSY])
        check(r["ran"] == [f"up -d {rest}", f"up -d {APP}"] and r["made"]["bina-claude-desktop"] == "recreated"
              and r["hooks"] == [f"before {APP}", f"after {APP}"],
              "BBOX_RECREATE_BUSY=1: the go recreates it though busy, with the backup and the resume", r)

        r = run("restart", "bina-claude-desktop", files=[BUSY])
        check(r["ran"] == [] and r["made"]["bina-claude-desktop"] == "" and "rc=75" in r["out"]
              and r["held"].get("bina-claude-desktop", [""] * 5)[4] == "restart",
              "naming it is no go: a restart of it while busy is held (noted a restart), and exits 75 — never a false ok", r)

        r = run("up", "-d", "--no-deps", "bina-claude-desktop", env={"BBOX_RECREATE_WHEN_IDLE": "1"}, files=["no-change"],
                note={"bina-claude-desktop": "2026-11-20 10:00:00 UTC\tbina-claude\t9 at work\t-\trestart"})
        check(r["ran"] == ["up -d --no-deps bina-claude-desktop", "restart bina-claude-desktop"]
              and r["made"]["bina-claude-desktop"] == "restarted" and r["held"] == {},
              "a held restart: the up converges, then a restart since nothing changed — never a recreate it did not ask", r)

        r = run("up", "-d", "--no-deps", *APP.split(), env={"BBOX_RECREATE_WHEN_IDLE": "1"},
                files=["no-change", "oneshot-runs"],
                note={"bina-claude-desktop": "2026-11-20 10:00:00 UTC\tbina-claude\t9 at work\t-\trestart"})
        check(r["ran"] == [f"up -d --no-deps {APP}", "restart bina-claude-desktop"]
              and r["made"]["bina-claude-desktop"] == "restarted",
              "a held restart is per service: the one-shot that runs at every up does not count as the desktop's", r)

        r = run("restart", "bina-claude-desktop", env={"BBOX_RECREATE_BUSY": "1"},
                note={"bina-claude-desktop": "2026-11-20 10:00:00 UTC\tbina-claude\t9 at work\t-\t-"})
        check(r["ran"] == ["up -d bina-claude-desktop"] and r["made"]["bina-claude-desktop"] == "recreated"
              and r["held"] == {},
              "a restart of a service with a plain note (a take held) runs as an up: the note is done, not dropped", r)

        r = run("up", "-d", "--no-recreate", "--no-deps", "bina-claude-desktop", env={"BBOX_RECREATE_WHEN_IDLE": "1"},
                note={"bina-claude-desktop": "2026-11-20 10:00:00 UTC\tbina-claude\t9 at work\t-\t-"})
        check(list(r["held"]) == ["bina-claude-desktop"] and "stays" in r["out"],
              "--no-recreate keeps even a plain note: it never does what a note waits for", r)

        r = run("restart", "bina-claude-desktop", env={"BBOX_RECREATE_BUSY": "1"},
                note={"bina-claude-desktop": "2026-11-20 10:00:00 UTC\tbina-claude\t9 at work\tbuild\t-"})
        check(r["ran"] == ["build bina-claude-desktop", "up -d bina-claude-desktop"]
              and r["made"]["bina-claude-desktop"] == "recreated" and r["held"] == {},
              "a restart that is due a build runs as an up: a restart would keep the old image, and drop the note", r)

        r = run("up", "-d", "--no-recreate", "--no-deps", "bina-claude-desktop", env={"BBOX_RECREATE_WHEN_IDLE": "1"},
                note={"bina-claude-desktop": "2026-11-20 10:00:00 UTC\tbina-claude\t9 at work\t-\tforce"})
        check(r["ran"] == ["up -d --no-recreate --no-deps bina-claude-desktop"]
              and list(r["held"]) == ["bina-claude-desktop"] and "stays" in r["out"],
              "a held force beside --no-recreate: nothing compose would refuse is added, and the note stays", r)

        r = run("up", "-d", files=[BUSY, f"catalog=bina-claude\t{APP}\t-\t{hooks}\t-\t-\tbefore-recreate,after-recreate"])
        check(r["ran"] == [f"up -d {rest}"] and sorted(r["held"]) == APP.split() and "ships no hooks/busy" in r["out"],
              "a «when-idle» app that ships no hooks/busy is taken as at work: nothing could ever say it is idle", r)

        r = run("up", "-d", "n8n", "bina-claude-desktop", files=[BUSY])
        check(r["ran"] == ["up -d n8n"] and r["made"]["n8n"] == "recreated" and r["fm"] == ["up -d n8n"]
              and "rc=75" in r["out"],
              "a command naming it and another: the other goes up with its refreshes, and the command exits 75", r)

        r = run("up", "-d", files=[f"catalog=bina-claude\t{APP}\t-\t/nowhere/hooks\t-\t-\tbusy,before-recreate,after-recreate"])
        check(r["ran"] == [f"up -d {rest}"] and sorted(r["held"]) == APP.split() and "cannot be read" in r["out"]
              and r["hooks"] == [], "a hook it ships that cannot be read (a path gone, an EIO) holds it: no recreate on a guess", r)

        r = run("up", "-d", files=[f"catalog=bina-claude\t{APP}\t-\tapps/bina-claude/hooks\t-\t-\tbusy,before-recreate,after-recreate"])
        check(r["ran"] == [f"up -d {rest}", f"up -d {APP}"] and r["hooks"] == ["busy", f"before {APP}", f"after {APP}"],
              "a hooks folder relative to the checkout (the last list read, from another path) is found from this one", r)

        r = run("restart", "bina-claude-desktop", env={"BBOX_RECREATE_BUSY": "1"}, files=[BUSY])
        check(r["ran"] == ["restart bina-claude-desktop"] and r["made"]["bina-claude-desktop"] == "restarted"
              and r["hooks"] == ["before bina-claude-desktop", "after bina-claude-desktop"] and "rc=0" in r["out"],
              "a restart with the go: backed up, restarted, and only what restarted is resumed", r)

        r = run("up", "-d", "--no-deps", "bina-claude-desktop", env={"BBOX_RECREATE_WHEN_IDLE": "1"},
                note={"bina-claude-desktop": "2026-11-20 10:00:00 UTC\tbina-claude\t9 at work\t-\tforce"})
        check(r["ran"] == ["up -d --no-deps --force-recreate bina-claude-desktop"]
              and r["made"]["bina-claude-desktop"] == "recreated" and r["held"] == {},
              "a held force (a restart, or --force-recreate): follow's retry forces it, not a plain up that changes nothing", r)

        r = run("up", "-d", files=[BUSY, "ps-fails"])
        check(r["ran"] == [f"up -d {rest}"] and sorted(r["held"]) == APP.split(),
              "an engine that cannot say what runs is taken as running it: held, not recreated", r)

        r = run("up", "-d", files=[BUSY, "catalog-fails"], note={})
        check(r["ran"] == ["up -d"] and "none were ever read" in r["out"],
              "a catalog never read here: the command runs as it always did, and says so", r)
        run("up", "-d", "n8n")                              # a good read leaves the last list behind
        r = run("up", "-d", files=[BUSY, "catalog-fails"], keep_cache=True)
        check(r["ran"] == [f"up -d {rest}"] and sorted(r["held"]) == APP.split() and "the last list read" in r["out"],
              "a catalog that cannot be read now: the last list read holds it", r)

        r = run("up", "-d", "--no-deps", "bina-claude-desktop", env={"BBOX_RECREATE_WHEN_IDLE": "1"}, files=[BUSY])
        check(r["ran"] == [] and list(r["held"]) == ["bina-claude-desktop"] and "rc=0" in r["out"],
              "follow naming it (BBOX_RECREATE_WHEN_IDLE=1) waits for a quiet moment", r)

        note = {"bina-claude-desktop": "2026-11-20 10:00:00 UTC\tbina-claude\t9 at work\tbuild"}
        r = run("up", "-d", "--no-deps", "bina-claude-desktop", env={"BBOX_RECREATE_WHEN_IDLE": "1"}, note=note)
        check(r["ran"] == ["build bina-claude-desktop", "up -d --no-deps bina-claude-desktop"]
              and r["made"]["bina-claude-desktop"] == "recreated" and r["held"] == {},
              "a held note that built: follow's retry builds first, recreates, and the note goes", r)

        r = run("up", "-d", "--no-deps", "bina-claude-desktop", env={"BBOX_RECREATE_WHEN_IDLE": "1"},
                files=["up-fails"], note={"bina-claude-desktop": "2026-11-20 10:00:00 UTC\tbina-claude\t9 at work\t-"})
        check(list(r["held"]) == ["bina-claude-desktop"] and "rc=0" not in r["out"]
              and not any(h.startswith("after") for h in r["hooks"]),
              "an up of it that fails keeps the note, and the command fails", r)

        r = run("up", "-d", files=["backup-fails"])
        check(r["ran"] == [f"up -d {rest}"] and sorted(r["held"]) == APP.split()
              and "before-recreate failed: disk full" in r["out"] and "rc=0" in r["out"],
              "a backup that fails holds it: never a recreate without it", r)

        r = run("up", "-d", "bina-claude-desktop", env={"BBOX_RECREATE_BUSY": "1"}, files=["backup-fails"])
        check(r["ran"] == [] and "rc=1" in r["out"] and "not recreated" in r["out"] and r["held"] == {},
              "the go with a backup that fails: the command fails and says why, never a false ok", r)

        r = run("up", "-d", files=["busy-hangs"])
        check(r["ran"] == [f"up -d {rest}"] and sorted(r["held"]) == APP.split() and "did not answer" in r["out"],
              "a busy hook that cannot answer is taken as at work", r)

        r = run("up", "-d", "--no-deps", "bina-claude-desktop", env={"BBOX_RECREATE_WHEN_IDLE": "1"},
                files=["no-change"], note={"bina-claude-desktop": "2026-11-20 10:00:00 UTC\tbina-claude\t9 at work\t-"})
        check(r["ran"] == ["up -d --no-deps bina-claude-desktop"] and r["hooks"] == ["busy", "before bina-claude-desktop"]
              and r["held"] == {}, "nothing changed: nobody is resumed, and the note goes (it is as declared)", r)

        r = run("up", "-d", "worker", files=[BUSY, f"catalog=bina-claude\t{APP}\tworker\t{hooks}\t-\t-"])
        check(r["ran"] == [] and list(r["held"]) == ["worker"],
              "a service that needs it waits with it: compose would recreate it for its dependent", r)

        r = run("up", "-d", files=[BUSY, "running=n8n"])
        check(r["ran"] == ["up -d"] and r["hooks"] == [], "it does not run: nothing waits, nobody is asked", r)

        r = run("up", "-d", "n8n", files=[BUSY])
        check(r["ran"] == ["up -d n8n"] and r["hooks"] == [] and r["held"] == {},
              "an up of another app is untouched, and nobody is asked", r)

        r = run("logs", "--tail", "5", files=[BUSY])
        check(r["ran"] == ["logs --tail 5"] and r["hooks"] == [], "a command that is no up is untouched", r)

        r = run("--dry-run", "up", "-d", files=[BUSY])
        check(r["ran"] == ["--dry-run up -d"] and r["hooks"] == [], "a dry run is a question: untouched", r)


def part_busy_hook(check):
    hook, atwork = ROOT / "apps/bina-claude/hooks/busy", ROOT / "apps/bina-claude/at-work.py"
    if not (hook.exists() and atwork.exists()):
        check(False, "apps/bina-claude/hooks/busy and at-work.py exist", f"missing: {hook} / {atwork}")
        return
    # part 1 plays the hooks with stubs: their own text is read here, so a quote that breaks one is caught
    for h in ("busy", "before-recreate", "after-recreate"):
        r = subprocess.run(["bash", "-n", str(ROOT / "apps/bina-claude/hooks" / h)], capture_output=True, text=True)
        check(r.returncode == 0, f"apps/bina-claude/hooks/{h} parses (bash -n)", r.stderr)
    if not os.path.exists("/proc/self/stat"):
        print("SKIP  the busy hook's sessions: no /proc on this machine (they are read inside the desktop, on Linux)")
        return
    with tempfile.TemporaryDirectory() as t:
        tp = pathlib.Path(t)
        repo = tp / "repo"
        (repo / "scripts").mkdir(parents=True)
        (repo / "apps/bina-claude/hooks").mkdir(parents=True)
        (repo / "scripts/lib.sh").write_text("read_env_value() { echo dn; }\ntimeout_bin() { :; }\n"
                                             "office_project() { echo dn-project; }\nnpath() { printf '%s' \"$1\"; }\n")
        shutil.copy(hook, repo / "apps/bina-claude/hooks/busy")
        shutil.copy(atwork, repo / "apps/bina-claude/at-work.py")
        fake = tp / "fake"
        home = fake / "home"
        (fake / "bin").mkdir(parents=True)
        (home / ".claude/sessions").mkdir(parents=True)
        (fake / "bin/docker").write_text(
            '#!/usr/bin/env bash\ncase "$1" in\n'
            '  ps) case "$*" in *label=com.docker.compose.project=*) [ -f "$FAKE/other-project" ] && exit 0 ;; esac\n'
            '      [ -f "$FAKE/down" ] || echo bina-claude-desktop-dn\n'
            '      case "$*" in *label=com.docker.compose.service=*) ;; *) echo n8n-dn ;; esac ;;\n'
            '  exec) [ -f "$FAKE/exec-fails" ] && exit 1\n'
            '        while [ $# -gt 0 ] && [ "$1" != python3 ]; do shift; done; [ $# -gt 0 ] || exit 1; shift\n'
            '        CLAUDE_DESKTOP_HOME="$FAKE/home" exec python3 "$@" ;;\nesac\n')
        (fake / "bin/docker").chmod(0o755)

        def tick(pid):
            return open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[19]

        live, quiet = subprocess.Popen(["sleep", "120"]), subprocess.Popen(["sleep", "120"])
        # a session whose turn ended while a Bash job of its own still runs: the shell under it, as the app starts one.
        # A group of its own, ended whole: a sleep left behind would hold the caller's pipe open for two minutes
        job = subprocess.Popen(["bash", "-c", "bash -c 'source /x/.claude/shell-snapshots/s.sh 2>/dev/null; sleep 120; true'"
                                " & wait"], start_new_session=True)
        dead = subprocess.Popen(["true"]); dead.wait()
        now = int(time.time() * 1000)

        def session(pid, sid, status, proc=None):
            (home / f".claude/sessions/{pid}.json").write_text(json.dumps(
                {"pid": pid, "hostSessionId": sid, "status": status, "startedAt": now, "procStart": proc}))

        try:
            session(live.pid, "local_a", "busy", tick(live.pid))
            session(dead.pid, "local_dead", "busy", "1")                      # its process is gone
            session(os.getpid(), "local_reused", "busy", str(int(tick(os.getpid())) + 1))   # another process has its pid
            session(quiet.pid, "local_idle", "idle", tick(quiet.pid))
            for _ in range(100):                                                # the job's shell is started
                if subprocess.run(["pgrep", "-f", "/x/.claude/shell-snapshots/"], capture_output=True).returncode == 0:
                    break
                time.sleep(0.1)
            session(job.pid, "local_job", "idle", tick(job.pid))
            env = {**os.environ, "FAKE": str(fake), "PATH": f"{fake / 'bin'}:{os.environ['PATH']}"}
            env.pop("DGO_INSTANCE_ID", None)

            def busy():
                r = subprocess.run(["bash", str(repo / "apps/bina-claude/hooks/busy")], capture_output=True, text=True,
                                   env=env, timeout=60)
                return r.returncode, r.stdout.strip()

            rc, out = busy()
            check(rc == 0 and out == "2 Claude session(s) at work in bina-claude",
                  "the busy hook: exit 0 and a line; a dead process and a reused pid are not counted", f"{rc} {out}")
            ids = subprocess.run(["python3", str(atwork), "ids"], capture_output=True, text=True,
                                 env={**env, "CLAUDE_DESKTOP_HOME": str(home)}, timeout=60).stdout.split()
            check(ids == ["local_a", "local_job"],
                  "at-work.py ids: whom to resume, the idle session with a job still running under it included", ids)
            session(live.pid, "local_a", "idle", tick(live.pid))
            os.killpg(job.pid, signal.SIGKILL)
            job.wait()
            time.sleep(0.3)
            rc, out = busy()
            check(rc == 1 and out == "", "the busy hook: exit 1 and nothing when no session is at work", f"{rc} {out}")
            (fake / "other-project").write_text("")
            rc, out = busy()
            check(rc == 0 and "not in the project" in out,
                  "the busy hook: a desktop running outside the project it could name is at work, not «not running»",
                  f"{rc} {out}")
            (fake / "other-project").unlink()
            (repo / "scripts/lib.sh").rename(repo / "scripts/lib.sh.away")
            rc, out = busy()
            check(rc == 0 and "lib.sh cannot be read" in out, "the busy hook: a lib.sh that cannot be read is at work",
                  f"{rc} {out}")
            (repo / "scripts/lib.sh.away").rename(repo / "scripts/lib.sh")
            (fake / "exec-fails").write_text("")
            rc, out = busy()
            check(rc == 0 and "cannot be counted" in out, "the busy hook: a desktop that cannot be counted is at work",
                  f"{rc} {out}")
            (fake / "down").write_text("")
            rc, out = busy()
            check(rc == 1, "the busy hook: a desktop that does not run cuts nothing (exit 1)", f"{rc} {out}")
        finally:
            for p in (live, quiet):
                p.kill()
                p.wait()
            if job.poll() is None:
                os.killpg(job.pid, signal.SIGKILL)
            job.wait()


def part_dependents(check):
    path = ROOT / "platform/manager/when_idle.py"
    if not path.exists():
        check(False, "platform/manager/when_idle.py exists", str(path))
        return
    spec = importlib.util.spec_from_file_location("when_idle", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    if not (hasattr(m, "needs") and hasattr(m, "dependents")):
        check(False, "when_idle.py names the services that need a «when-idle» app's own", "no needs()/dependents()")
        return
    got = m.needs({"depends_on": {"a": {"condition": "service_started"}}, "network_mode": "service:b",
                   "volumes_from": ["c:ro", "container:x"]})
    check(got == {"a", "b", "c"}, "when_idle.py: what a service needs (depends_on, network_mode, volumes_from)", got)
    graph = {"bina-claude-desktop": {"bina-claude"}, "worker": {"bina-claude-desktop"}, "sidecar": {"worker"},
             "n8n": set()}
    got = m.dependents(["bina-claude", "bina-claude-desktop"], graph)
    check(got == ["sidecar", "worker"], "when_idle.py: the services that need its own, through another too", got)
    if hasattr(m, "ships"):
        with tempfile.TemporaryDirectory() as t:
            h = pathlib.Path(t) / "hooks"
            h.mkdir()
            (h / "busy").write_text("")
            (h / "before-recreate").mkdir()                     # not a file: not a hook
            got = (m.ships(h), m.ships(pathlib.Path(t) / "none"))
        check(got == (["busy"], []), "when_idle.py: the hooks a folder ships (a missing one is none; a folder no hook)", got)


def main() -> int:
    if not shutil.which("bash"):
        print("NOT RUN no bash on this machine")
        return 1
    check = Checks()
    part_dcx(check)
    part_busy_hook(check)
    part_dependents(check)
    print("test_compose_when_idle: " + ("ok" if not check.bad else f"{check.bad} FAILED"))
    return 1 if check.bad else 0


if __name__ == "__main__":
    sys.exit(main())
