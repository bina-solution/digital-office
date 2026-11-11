#!/usr/bin/env python3
"""test_app_update.py — `bbox update <app>` compiles first and brings up a provider the app newly requires that has
no container, before it touches the app; a provider that has containers is never touched (DGO-1583).

    python3 scripts/test_app_update.py

Two halves.

THE UPDATE (scripts/app-update.sh) runs from a throwaway tree where everything it asks of an office is a stub: the
compiler (`reconcile.py render` and `rollback`: exit codes, and a generation archived or not), the keys of .env
(scripts/env-secrets.py), the plan (scripts/app-update-plan.py: a file), compose (scripts/dc: the compiled
services, the containers and their states, build and up with exit codes, every call logged), docker (the state of
a container from the same file; one image id for everything unless a case says otherwise) and the apps' hooks,
which log into compose's log so their order against the containers is read from one place. Each case states the
shape it reproduces. Needs bash; no engine, no network.

THE PLAN (scripts/app-update-plan.py) is asked of THIS checkout's catalog, as the update asks it on an office:
drive's closure holds the split's two engines, a service name finds its app, a name nothing declares says so.
It needs PyYAML (the compiler does): where there is none, the half is NOT RUN and says so in the words gate G72
reads as «needs a package» — never a pass.
"""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
FAILS = []


def check(name, cond, out=""):
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        FAILS.append(name)
        for ln in (out or "").splitlines()[-14:]:
            print("      | " + ln)


PLAN_STUB = r'''import os, sys
stub = os.environ["STUB"]
sys.stdout.write(open(os.path.join(stub, "plan")).read())
print(" ".join(sys.argv[1:]), file=open(os.path.join(stub, "plan.asked"), "a"))
rc = os.path.join(stub, "plan.rc")
sys.exit(int(open(rc).read()) if os.path.exists(rc) else 0)
'''

SECRETS_STUB = r'''import os, sys
print("secrets " + " ".join(sys.argv[1:]), file=open(os.path.join(os.environ["STUB"], "dc.log"), "a"))
'''

COMPILER_STUB = r'''import os, pathlib, shutil, sys
# the compiler, played: render archives the compile it replaces (whole, or in part) and writes a new one; a refusal
# before any of that is a manifest it rejects; rollback copies a generation back over the live compile
stub, gen = os.environ["STUB"], pathlib.Path(".generated")
print(" ".join(sys.argv[1:]), file=open(os.path.join(stub, "dc.log"), "a"))
def has(name):
    return os.path.exists(os.path.join(stub, name))
def rc(name):
    return int(open(os.path.join(stub, name)).read()) if has(name) else 0
def live(root):
    return sorted(p for p in root.iterdir() if p.name != "generations")
if sys.argv[1] == "rollback":
    if rc("rollback.rc"):
        print("FATAL could not restore", file=sys.stderr)
        sys.exit(rc("rollback.rc"))
    src = gen / "generations" / sys.argv[3]
    for p in live(gen):
        shutil.rmtree(p) if p.is_dir() else p.unlink()
    for p in live(src):
        (shutil.copytree if p.is_dir() else shutil.copy2)(p, gen / p.name)
    sys.exit(0)
if has("render.refuses"):                                        # a manifest it rejects: nothing is written
    print("\n".join(f"  info  app{i}: pulled in as provider" for i in range(8)), file=sys.stderr)
    print("  ERROR dependency CYCLE: a -> b -> a (break it with dependency:'weak')", file=sys.stderr)
    print("\n".join(f"  info  app{i}: bound by platform.state.yaml" for i in range(8)), file=sys.stderr)
    print("RESOLVE FAILED — 1 error(s)", file=sys.stderr)
    sys.exit(1)
gens = gen / "generations"
n = max([int(d.name) for d in gens.iterdir()] + [0]) + 1
dst = gens / f"{n:04d}"
dst.mkdir(parents=True)
for p in live(gen):                                              # the archive of the compile it replaces
    (shutil.copytree if p.is_dir() else shutil.copy2)(p, dst / p.name)
(gen / "compose.yml").write_text("new compile\n")
# the new compile's apps: the split's two engines join drive's closure unless a case says otherwise
order = open(os.path.join(stub, "new-order")).read().split() if has("new-order") else \
    ["forward-auth", "connections", "postgres", "supabase", "drive-local", "drive-google", "drive"]
(gen / "resolved.json").write_text('{"order": [' + ", ".join(f'"{a}"' for a in order) + "]}\n")
if rc("render.rc"):
    print("SERVE PLAN REFUSED — apps/broken/app.json: not a manifest", file=sys.stderr)
sys.exit(rc("render.rc"))
'''

DC_STUB = r'''#!/usr/bin/env bash
# compose, played: every call is logged; `ps` reads ${STUB}/ps («service state» per line), `up` adds what it names
echo "dc $*" >> "${STUB}/dc.log"
case "$1 ${2:-}" in
  "config --services") cat "${STUB}/declared" ;;
  "config -q")         [ -f "${STUB}/configq.rc" ] && { echo "service \"x\" refers to undefined volume y"; exit "$(cat "${STUB}/configq.rc")"; } ;;
  "config --images")   echo "img-$3" ;;
  "ps -a")
    if [ "${3:-}" = -q ]; then awk -v s="$4" '$1 == s {print "cid-" s; exit}' "${STUB}/ps"
    else [ -f "${STUB}/ps.rc" ] && exit "$(cat "${STUB}/ps.rc")"; cat "${STUB}/ps"; fi ;;
  "ps -q") ;;
  build*)
    shift; exit "$(cat "${STUB}/build.rc.$1" 2>/dev/null || echo 0)" ;;
  "up -d")
    shift 2; rc=0; svcs=()
    for a in "$@"; do case "${a}" in -*|[0-9]*) ;; *) svcs+=("${a}") ;; esac; done
    for s in "${svcs[@]}"; do [ -f "${STUB}/up.rc.${s}" ] && rc="$(cat "${STUB}/up.rc.${s}")"; done
    if [ "${rc}" = 0 ]; then
      for s in "${svcs[@]}"; do   # created, or recreated/started: its state is what ${STUB}/after-up.<s> says
        grep -v "^${s} " "${STUB}/ps" > "${STUB}/ps.new"; mv "${STUB}/ps.new" "${STUB}/ps"
        echo "${s} $(cat "${STUB}/after-up.${s}" 2>/dev/null || echo running)" >> "${STUB}/ps"
      done
      echo "[bbox] recreating dgo-link — the container whose network it lives in was replaced"
    else
      echo "Error response from daemon: Conflict. The container name is already in use"
    fi
    exit "${rc}" ;;
esac
exit 0
'''

LIB_STUB = r'''# scripts/lib.sh, played: only the deploy ledger's check (G90), refusing when ${STUB}/ledger.rc says so
deploy_ledger_gate() {
  echo "ledger $*" >> "${STUB}/dc.log"
  [ -f "${STUB}/ledger.rc" ] || return 0
  echo "deploy: REFUSED — this checkout (HEAD abc) does not contain def, the commit this office last ran." >&2
  return 1
}
'''

DOCKER_STUB = r'''#!/usr/bin/env bash
# a container's state comes from ${STUB}/ps; one image id for every container and tag unless ${STUB}/image.after
if [ "$1" = inspect ]; then
  svc="${4#cid-}"; st="$(awk -v s="${svc}" '$1 == s {print $2; exit}' "${STUB}/ps")"
  case "$3" in
    *ExitCode*)
      case "${st}" in running) echo "running healthy 0" ;; starting) echo "running starting 0" ;;
                      unhealthy) echo "running unhealthy 0" ;;
                      completed) echo "exited  0" ;; failing) echo "exited  1" ;; *) echo "${st}  0" ;; esac ;;
    *RestartCount*) cat "${STUB}/restarts.${svc}" 2>/dev/null || echo 0 ;;
    *State.Status*) [ "${st}" = running ] && echo "running healthy" || echo "${st} " ;;
    *Config.Image*) echo "img-${svc}" ;;
    *) echo "sha256:0123456789abcdef0123456789abcdef" ;;
  esac
elif [ "$1" = image ]; then
  cat "${STUB}/image.after" 2>/dev/null || echo "sha256:0123456789abcdef0123456789abcdef"
fi
exit 0
'''

PLAN = """named drive drive apps drive
provider platform-base connections 600 connections
later connections sign-in
provider apps supabase 600 rest storage kong
provider apps drive-local 600 drive-local
provider apps drive-google 600 drive-google
"""


class Office:
    """An office that runs drive and its vault, compiled with the split's two engines that it never ran."""

    def __init__(self, root, name):
        self.repo = root / "repo"
        self.stub = root / f"stub.{name}"
        shutil.rmtree(self.repo / "apps", ignore_errors=True)
        shutil.rmtree(self.repo / ".generated", ignore_errors=True)
        shutil.rmtree(self.repo / "data", ignore_errors=True)
        (self.repo / ".generated" / "generations" / "0007").mkdir(parents=True)
        (self.repo / ".generated" / "registry").mkdir()
        (self.repo / ".generated" / "compose.yml").write_text("the compile this office runs\n")
        (self.repo / ".generated" / "registry" / "office.apps.json").write_text("{}\n")
        # the compile from before the split: drive ran on the vault and supabase, and neither engine existed
        self.found(["forward-auth", "connections", "postgres", "supabase", "drive"])
        self.stub.mkdir()
        (self.stub / "plan").write_text(PLAN)
        (self.stub / "declared").write_text("\n".join(
            ["connections", "rest", "storage", "kong", "drive", "drive-local", "drive-google"]) + "\n")
        (self.stub / "ps").write_text("connections running\nrest running\nstorage running\ndrive running\n")
        self.hook("apps", "drive-local", "prepare")
        self.hook("apps", "drive-local", "onboard")
        self.out, self.rc = "", None

    def found(self, order):
        """The compile this update finds: .generated/resolved.json's `order` (None: no such file)."""
        p = self.repo / ".generated" / "resolved.json"
        if order is None:
            p.unlink()
        else:
            p.write_text('{"order": [' + ", ".join(f'"{a}"' for a in order) + "]}\n")

    def hook(self, root, aid, verb, rc=0):
        p = self.repo / root / aid / "hooks" / verb
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f'#!/bin/sh\necho "hook {aid} {verb}" >> "${{STUB}}/dc.log"\nexit {rc}\n')
        p.chmod(0o755)

    def put(self, name, text):
        (self.stub / name).write_text(text)

    def add(self, name, text):
        with open(self.stub / name, "a") as f:
            f.write(text)

    def run(self, *args, script="scripts/app-update.sh", **extra):
        env = {**os.environ, "STUB": str(self.stub), "APP_UPDATE_POLL": "0",
               "PATH": f"{self.repo.parent / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}"}
        for k in ("APP_UPDATE_FORCE", "APP_UPDATE_TIMEOUT", "PROVIDER_UP_BUILD"):
            env.pop(k, None)
        env.update(extra)
        r = subprocess.run(["bash", script, *args], cwd=self.repo, env=env,
                           capture_output=True, text=True, timeout=120)
        self.out, self.rc = r.stdout + r.stderr, r.returncode
        return self

    def provider_up(self, *args, **extra):
        """scripts/provider-up.sh RUN, as the apps screen's enable runs it (DGO-1496), not sourced as the update does."""
        return self.run(*args, script="scripts/provider-up.sh", **extra)

    def log(self):
        p = self.stub / "dc.log"
        return p.read_text().splitlines() if p.exists() else []

    def logged(self, line):
        return line in self.log()

    def touched(self, svc):
        """Whether anything was built, brought up or hooked for `svc` (reading its state is not touching it)."""
        return any(ln.startswith(("dc build", "dc up", "hook")) and svc in ln.split() for ln in self.log())

    def before(self, a, b):
        log = self.log()
        return a in log and b in log and log.index(a) < log.index(b)

    def said(self, text):
        return text in self.out

    def compile(self):
        return (self.repo / ".generated" / "compose.yml").read_text()

    def pending(self):
        p = self.repo / "data" / ".deploy" / "update-pending"
        return p.read_text().split() if p.exists() else None


def up(svc):
    return f"dc up -d --no-deps {svc}"


def the_update(tmp):
    repo = tmp / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "platform" / "manager").mkdir(parents=True)
    (tmp / "bin").mkdir()
    shutil.copy(HERE / "app-update.sh", repo / "scripts" / "app-update.sh")
    shutil.copy(HERE / "provider-up.sh", repo / "scripts" / "provider-up.sh")   # its bring-up, sourced
    (repo / "scripts" / "app-update-plan.py").write_text(PLAN_STUB)
    (repo / "scripts" / "env-secrets.py").write_text(SECRETS_STUB)
    (repo / "scripts" / "lib.sh").write_text(LIB_STUB)
    (repo / ".env").write_text("DEPLOYMENT_NAME=t\n")
    (repo / "platform" / "manager" / "reconcile.py").write_text(COMPILER_STUB)
    (repo / "scripts" / "dc").write_text(DC_STUB)
    (tmp / "bin" / "docker").write_text(DOCKER_STUB)
    (repo / "scripts" / "dc").chmod(0o755)
    (tmp / "bin" / "docker").chmod(0o755)

    # 1. Exampleu's take (DGO-1577): the checkout moved to the split and `bbox update drive` is the update. The keys
    #    of .env and the compile come first, the two engines that have no container are built and brought up
    #    alone, in the plan's order, with drive-local's own hooks around its containers, and only then is drive
    #    itself built.
    o = Office(tmp, "absent").run("drive")
    check("the deploy ledger, then the keys of .env, then the compile, before anything is asked of compose",
          o.before("ledger build", "secrets --env .env --if-fresh") and o.before("secrets --env .env --if-fresh", "render")
          and o.before("render", "dc config -q") and o.before("dc config -q", "dc config --services"), o.out)
    check("the update says it compiled, and that a rollback in force ends there",
          o.said("compiled the checkout, as `bbox run` does (a `bbox rollback` in force ends here)"), o.out)
    asked = o.stub / "plan.asked"
    check("the plan is asked for the named app", asked.exists() and asked.read_text().split() == ["drive"], o.out)
    check("drive-local: its prepare, then its build, then its containers alone, then its onboard",
          o.before("hook drive-local prepare", "dc build drive-local")
          and o.before("dc build drive-local", up("drive-local"))
          and o.before(up("drive-local"), "hook drive-local onboard"), o.out)
    check("drive-google comes up after drive-local (the plan's order)", o.before(up("drive-local"), up("drive-google")), o.out)
    check("both are up before drive is built", o.before(up("drive-google"), "dc build drive"), o.out)
    check("a provider that runs (connections) is never built, brought up or hooked", not o.touched("connections"), o.out)
    check("supabase, up in part (kong has no container), is left alone and not named",
          not o.touched("kong") and not o.said("== supabase"), o.out)
    check("the update says why each engine came up",
          o.said("== drive-local — the checkout makes drive require it, and it is not up here: bringing it up first")
          and o.said("ok — drive-google is up: drive-google"), o.out)
    check("what the engine's own steps did beside it is passed on",
          o.said("[bbox] recreating dgo-link — the container whose network it lives in was replaced"), o.out)
    check("and goes on to drive, which exits 0", o.said("== drive\n") and o.said("nothing to apply") and o.rc == 0, o.out)

    # 2. A provider that has a container and is stopped is somebody's decision (or an on-demand app asleep):
    #    named, never started or rebuilt by an update.
    o = Office(tmp, "stopped")
    o.found(["forward-auth", "connections", "postgres", "supabase", "drive-local", "drive"])   # it ran here before
    o.add("ps", "drive-local exited\n")
    o.run("drive")
    check("a stopped provider is named", o.said("== drive-local — required by drive and not running (drive-local)"), o.out)
    check("and not built, brought up or hooked", not o.touched("drive-local"), o.out)
    check("the absent one beside it still comes up, and drive is updated",
          o.logged(up("drive-google")) and o.logged("dc build drive") and o.rc == 0, o.out)

    # 3. A provider this office does not compile (it runs on a linked office) is not this office's to bring up.
    o = Office(tmp, "remote")
    o.put("declared", "connections\nrest\nstorage\nkong\ndrive\ndrive-local\n")
    o.run("drive")
    check("a provider no compiled service of which is here is skipped in silence",
          not o.touched("drive-google") and not o.said("drive-google") and o.rc == 0, o.out)

    # 4. A provider that does not come up: the app that needs it keeps the image it runs (a new drive with no
    #    engine would answer every account «not answering»), the providers after it are not tried, the update fails.
    o = Office(tmp, "down")
    o.put("up.rc.drive-local", "1")
    o.run("drive")
    check("the provider's failure is said with compose's own words",
          o.said("Error response from daemon: Conflict"), o.out)
    check("nothing is updated, and it says so",
          o.said("nothing updated — drive keeps the image it runs: the provider drive-local did not come up")
          and not o.logged("dc build drive"), o.out)
    check("the next provider is not tried", not o.touched("drive-google"), o.out)
    check("its onboard does not run", not o.logged("hook drive-local onboard"), o.out)
    check("exit 1", o.rc == 1, o.out)

    o = Office(tmp, "nobuild")
    o.put("build.rc.drive-local", "1")
    o.run("drive")
    check("a provider whose build fails holds the update too",
          o.said("build FAILED") and o.said("nothing updated") and not o.logged("dc build drive") and o.rc == 1, o.out)

    # 5. The wait is as long as the provider's own first start (its progress_deadline_seconds, as app-management
    #    waits), not the update's 240 s; a run-once service that finished counts as done; one that failed holds.
    o = Office(tmp, "slow")
    o.put("after-up.drive-local", "starting")
    o.run("drive")
    check("a provider still starting is waited for as long as its first start may take (600 s, not 240)",
          o.said("not up after 600s: drive-local (running starting 0)") and o.said("nothing updated") and o.rc == 1, o.out)
    o = Office(tmp, "runonce")
    o.put("after-up.drive-local", "completed")
    o.run("drive")
    check("a run-once service that exited 0 is done", o.said("ok — drive-local is up") and o.rc == 0, o.out)
    o = Office(tmp, "runfail")
    o.put("after-up.drive-local", "failing")
    o.run("drive")
    check("one that exited non-zero holds the update", o.said("drive-local: exited  1") and o.rc == 1, o.out)
    o = Office(tmp, "unhealthy")
    o.put("after-up.drive-local", "unhealthy")
    o.run("drive")
    check("an unhealthy reading during a first start is waited through (as app-management waits), not failed at once",
          o.said("not up after 600s: drive-local (running unhealthy 0)") and o.rc == 1, o.out)
    o = Office(tmp, "crashloop")
    o.put("after-up.drive-local", "restarting")
    o.put("restarts.drive-local", "3")
    o.run("drive")
    check("a crash loop fails at once, not after the whole 600 s",
          o.said("drive-local: restarted 3 times") and not o.said("not up after") and o.rc == 1, o.out)

    # 6. A compile that fails BEFORE it writes (a manifest it rejects) leaves the office's last compile whole: the
    #    update goes on with it as it did before, brings up no provider, and exits 1 — the checkout did not compile.
    o = Office(tmp, "nocompile")
    o.put("render.refuses", "")
    o.run("drive")
    check("a refused manifest is said with the compiler's own error, not only its last lines",
          o.said("the compile FAILED") and o.said("ERROR dependency CYCLE") and o.said("it wrote nothing"), o.out)
    check("the compile this office runs is untouched", o.compile() == "the compile this office runs\n", o.out)
    check("no provider is brought up and the plan is not asked",
          not o.touched("drive-local") and not (o.stub / "plan.asked").exists(), o.out)
    check("the app itself is still updated as before, and the update exits 1", o.logged("dc build drive") and o.rc == 1, o.out)

    # 7. A compile that fails AFTER it began to write (the serve plan, a registry), or one compose refuses: answered
    #    as `bbox run` answers it — nothing updated, nothing built, no compile «put back» that might not be whole.
    o = Office(tmp, "halfcompile")
    o.put("render.rc", "1")
    o.run("drive")
    check("a compile that stopped after it began to write: no app updated, as `bbox run` refuses it too",
          o.said("no app updated — the compile stopped after it began to write")
          and not any(ln.startswith(("dc build", "dc up", "rollback")) for ln in o.log()) and o.rc == 1, o.out)
    check("…and it names the generation that puts back the compile it replaced",
          o.said("generation 0008 is the .generated/ it replaced (python3 platform/manager/reconcile.py rollback --for 0008)")
          and o.said("The edge's zz-serve.yaml and the sign-in blueprint are outside it"), o.out)
    o = Office(tmp, "configrefused")
    o.put("configq.rc", "1")
    o.run("drive")
    check("a compile compose refuses: no app updated, with compose's words and the way back",
          o.said("no app updated — compose refuses the new compile") and o.said("undefined volume")
          and o.said("rollback --for 0008")
          and not any(ln.startswith(("dc build", "dc up")) for ln in o.log()) and o.rc == 1, o.out)

    # 7b. The deploy ledger (G90) is asked before the compile: a checkout that drops what this office runs changes
    #     nothing at all — not the compile, which writes the edge's and the sign-in's files too.
    o = Office(tmp, "ledger")
    o.put("ledger.rc", "1")
    o.run("drive")
    check("a checkout the deploy ledger refuses: nothing compiled, nothing updated",
          o.said("deploy: REFUSED") and o.said("nothing updated — the deploy ledger refuses this checkout")
          and not o.logged("render") and not o.logged("secrets --env .env --if-fresh") and o.rc == 1, o.out)

    # 7c. Only what the CHECKOUT added is brought up: a provider that was already in the compile this update found,
    #     is not pending and has no container was taken down (`bbox stop` removes containers) or left out by
    #     choice — named, with what it means for the app, and not touched.
    o = Office(tmp, "takendown")
    o.found(["forward-auth", "connections", "postgres", "supabase", "drive-google", "drive"])
    o.run("drive")
    check("a provider already in the found compile, not pending, with no container: named, not brought up",
          o.said("== drive-google — required by drive, has no container here, and is not pending from an update")
          and o.said("drive is updated without it, and the update exits 1") and not o.touched("drive-google"), o.out)
    check("…while the one the checkout added still comes up, and the update exits 1 (not a success without it)",
          o.logged(up("drive-local")) and o.logged("dc build drive") and o.rc == 1, o.out)
    check("a first update with no pending file says nothing of the missing file", "No such file" not in o.out, o.out)

    # 7d. What the checkout added stays pending until it is up. A retry after a provider failed brings it up — its
    #     own failed update's compile already holds it, so «absent from the found compile» alone would miss it.
    o = Office(tmp, "retry")
    o.put("after-up.drive-local", "failing")            # its first start crashes, and leaves its container behind
    o.run("drive")
    first = o.rc
    check("a provider whose first start crashed stays pending (both engines are)",
          first == 1 and o.pending() == ["drive-local", "drive-google"] and not o.logged("dc build drive"), o.out)
    (o.stub / "after-up.drive-local").unlink()
    (o.stub / "dc.log").unlink()
    o.run("drive")
    check("the retry brings it up again despite the container it left, then the other, then updates drive",
          o.logged(up("drive-local")) and o.logged(up("drive-google")) and o.logged("dc build drive") and o.rc == 0, o.out)
    check("…and nothing is pending once both are up", o.pending() == [], o.out)
    o = Office(tmp, "retrynone")
    o.put("up.rc.drive-local", "1")                     # its `up` fails outright: no container at all
    o.run("drive")
    (o.stub / "up.rc.drive-local").unlink()
    o.run("drive")
    check("a retry after an `up` that created nothing brings it up too",
          o.logged(up("drive-local")) and o.logged("dc build drive") and o.rc == 0 and o.pending() == [], o.out)

    # 7e. …and an update of ANOTHER app first: its compile already holds the engines, and they are still new to drive.
    o = Office(tmp, "otherfirst")
    o.put("plan", "named mail mail apps mailapi\nprovider platform-base connections 600 connections\n")
    o.put("declared", "connections\nrest\nstorage\nkong\ndrive\ndrive-local\ndrive-google\nmailapi\n")
    o.add("ps", "mailapi running\n")
    o.run("mail")
    check("an update of mail leaves the engines it added pending", o.pending() == ["drive-local", "drive-google"], o.out)
    o.put("plan", PLAN)
    o.run("drive")
    check("…and the next update of drive still brings them up",
          o.logged(up("drive-local")) and o.logged(up("drive-google")) and o.rc == 0, o.out)

    # 7f. A pending provider that has containers (brought up by `bbox run`, or the apps screen) leaves the list, so a
    #     later `bbox stop` of it is never undone by an update.
    o = Office(tmp, "cleaned")
    o.found(["forward-auth", "connections", "postgres", "supabase", "drive-local", "drive-google", "drive"])
    (o.repo / "data" / ".deploy").mkdir(parents=True)
    (o.repo / "data" / ".deploy" / "update-pending").write_text("drive-google\n")
    o.add("ps", "drive-local running\ndrive-google running\n")
    o.run("drive")
    check("a pending provider found up leaves the list", o.pending() == [] and not o.touched("drive-google"), o.out)
    o = Office(tmp, "namedup")
    o.found(["forward-auth", "connections", "postgres", "supabase", "drive-local", "drive-google", "drive"])
    (o.repo / "data" / ".deploy").mkdir(parents=True)
    (o.repo / "data" / ".deploy" / "update-pending").write_text("drive-local\ndrive-google\n")
    o.add("ps", "drive-local running\n")
    o.put("plan", "named drive-local drive-local apps drive-local\n")
    o.run("drive-local")
    check("an app updated by name and up leaves the list; the others stay", o.pending() == ["drive-google"] and o.rc == 0, o.out)
    o = Office(tmp, "namedcrashed")
    o.put("after-up.drive-local", "failing")            # drive's update: drive-local's first start crashes
    o.run("drive")
    o.put("plan", "named drive-local drive-local apps drive-local\n")
    o.run("drive-local")                                # «nothing to apply» over the crashed container
    check("a named update that finds the crashed container «nothing to apply» does not take it off the list",
          o.said("nothing to apply") and "drive-local" in (o.pending() or []), o.out)
    o.put("plan", PLAN)
    o.run("drive")
    check("…so the next update of drive tries it again, and holds drive while it still crashes",
          o.said("bringing it up first") and o.said("nothing updated") and o.rc == 1, o.out)
    o = Office(tmp, "nofound")
    o.found(None)
    o.run("drive")
    check("a found compile that cannot be read: said, and no provider is brought up",
          o.said("the compile this update found could not be read") and not o.touched("drive-local"), o.out)

    # 8. A plan the compiler refuses (a dependency cycle): said, no provider, the app updated as before.
    o = Office(tmp, "noplan")
    o.put("plan.rc", "1")
    o.run("drive")
    check("a refused plan is said and brings up nothing",
          o.said("the providers of drive could not be resolved") and not o.touched("drive-local"), o.out)
    check("and the app is updated as before", o.logged("dc build drive") and o.rc == 0, o.out)

    # 9. «No container» means «new» only when the containers could be listed and the office runs: a `ps` that fails
    #    (an engine under load) or an office that was taken down must not bring every provider up again.
    o = Office(tmp, "nops")
    o.put("ps.rc", "1")
    o.run("drive")
    check("containers that cannot be listed: said, and no provider is brought up",
          o.said("the office's containers could not be listed — no provider is brought up")
          and not o.touched("drive-local") and not o.touched("connections"), o.out)
    o = Office(tmp, "stoppedoffice")
    o.put("ps", "connections exited\nrest exited\nstorage exited\ndrive exited\n")
    o.run("drive")
    check("an office where nothing runs: said, and no provider is brought up",
          o.said("nothing of this office is running") and not o.touched("drive-local"), o.out)
    o = Office(tmp, "elsewhere")
    o.put("declared", "connections\nrest\nstorage\nkong\ndrive-local\ndrive-google\n")
    o.run("drive")
    check("a named app not compiled on this office: said, and none of its providers is brought up",
          o.said("drive is not compiled on this office — no provider is brought up")
          and not o.touched("drive-local") and not o.touched("drive-google"), o.out)

    # 10. A provider's hook that fails is loud and fails the update, as a bring-up says it, and stops nothing.
    o = Office(tmp, "badhook")
    o.hook("apps", "drive-local", "prepare", 3)
    o.run("drive")
    check("a failed prepare is said", o.said("drive-local: its prepare hook FAILED (exit 3)"), o.out)
    check("the provider still comes up and drive is updated", o.logged(up("drive-local")) and o.logged("dc build drive"), o.out)
    check("and the update exits 1", o.rc == 1, o.out)

    # 11. What a provider's bring-up leaves to `bbox run` is said.
    o = Office(tmp, "later")
    o.put("ps", "rest running\nstorage running\ndrive running\n")
    o.found(["postgres", "supabase", "drive"])          # the vault is what this checkout adds here
    o.run("drive")
    check("a provider with a gated host: its sign-in refresh is left to `bbox run`, and said",
          o.said("the sign-in refresh of the host it gates comes with the next `bbox run`"), o.out)

    # 12. The app's own recreate is the one it always was: compose starts the app's own dependencies with it (its
    #     database, its init and migrate containers), so there is no --no-deps on it, nor on a rollback.
    o = Office(tmp, "recreate")
    o.put("image.after", "sha256:fedcba9876543210fedcba9876543210")
    o.run("drive")
    check("the app's recreate is `up -d --force-recreate <svc>`, its dependencies with it",
          o.logged("dc up -d --force-recreate drive") and o.rc == 0, o.out)

    # 13. A named app with no container is created by its own update, as before; its hooks are the enable path's.
    o = Office(tmp, "freshnamed")
    o.put("plan", "named drive-local drive-local apps drive-local\n")
    o.put("image.after", "sha256:fedcba9876543210fedcba9876543210")
    o.run("drive-local")
    check("a named app with no container: created by its recreate, no hook of its own run",
          o.logged("dc up -d --force-recreate drive-local") and not any(ln.startswith("hook") for ln in o.log()), o.out)

    # 14. Named arguments go in the closure's order: a named provider before the app that needs it.
    o = Office(tmp, "order")
    o.put("plan", "named drive-local drive-local apps drive-local\nnamed drive drive apps drive\n")
    o.run("drive", "drive-local")
    check("`bbox update drive drive-local` updates drive-local first",
          o.before("dc build drive-local", "dc build drive"), o.out)

    # 15. --timeout reaches the providers' wait, in both of its forms (the spaced one used to name a service).
    o = Office(tmp, "timeout")
    o.put("after-up.drive-local", "starting")
    o.put("plan", "named drive drive apps drive\nprovider apps drive-local 60 drive-local\n")
    o.run("drive", "--timeout", "120")
    check("--timeout 120 (spaced) is the wait, and 120 is not updated as a service",
          o.said("not up after 120s") and not o.logged("dc build 120"), o.out)
    o = Office(tmp, "timeout2")
    o.put("after-up.drive-local", "starting")
    o.put("plan", "named drive drive apps drive\nprovider apps drive-local 60 drive-local\n")
    o.run("drive", "--timeout=90")
    check("--timeout=90 too", o.said("not up after 90s"), o.out)
    o = Office(tmp, "timeout3").run("drive", "--timeout")
    check("--timeout with no value is a usage error (exit 2), and nothing runs", o.rc == 2 and o.log() == [], o.out)
    o = Office(tmp, "timeout4").run("drive", "--timeout", "5m")
    check("--timeout that is not whole seconds is a usage error (exit 2), and nothing runs", o.rc == 2 and o.log() == [], o.out)

    # 16. What a provider's bring-up by an update does not do is said: its n8n automations.
    o = Office(tmp, "automations")
    o.put("plan", PLAN + "later drive-local automations\n")
    o.run("drive")
    check("a provider with automations: said that an update does not push them, and what does",
          o.said("its automations (n8n blueprints) are not pushed by an update: `bbox n8n push drive-local` does"), o.out)

    # 17. The same bring-up RUN, as the apps screen's enable runs it for a provider that has no container (DGO-1496):
    #     one provider, from the checkout the file sits in; its exit says up, not up, up with a hook that failed, usage.
    o = Office(tmp, "run-up").provider_up("apps", "drive-local", "600", "drive-local")
    check("run: drive-local's prepare, its build, its containers alone, its onboard, then exit 0 saying so",
          o.before("hook drive-local prepare", "dc build drive-local")
          and o.before("dc build drive-local", up("drive-local"))
          and o.before(up("drive-local"), "hook drive-local onboard")
          and o.rc == 0 and o.said("ok — drive-local is up: drive-local"), o.out)
    check("run: nothing else is asked of compose (no compile, no other service)",
          not o.logged("render") and not o.touched("drive") and not o.touched("connections"), o.out)
    o = Office(tmp, "run-build")
    o.put("build.rc.drive-local", "1")
    o.provider_up("apps", "drive-local", "600", "drive-local")
    check("run: a build that fails is exit 1, said, and nothing is brought up",
          o.rc == 1 and o.said("build FAILED") and not o.logged(up("drive-local")), o.out)
    o = Office(tmp, "run-crash")
    o.put("after-up.drive-local", "failing")
    o.provider_up("apps", "drive-local", "600", "drive-local")
    check("run: a first start that exits is exit 1, with its state, and no onboard",
          o.rc == 1 and o.said("drive-local: exited  1") and not o.logged("hook drive-local onboard"), o.out)
    o = Office(tmp, "run-hook")
    o.hook("apps", "drive-local", "onboard", rc=4)
    o.provider_up("apps", "drive-local", "600", "drive-local")
    check("run: up with an onboard that failed is exit 3, both said",
          o.rc == 3 and o.said("drive-local: its onboard hook FAILED (exit 4)")
          and o.said("ok — drive-local is up: drive-local"), o.out)
    o = Office(tmp, "run-usage").provider_up("apps", "drive-local", "10m", "drive-local")
    check("run: seconds that are not whole seconds is a usage error (exit 2), and nothing runs",
          o.rc == 2 and o.log() == [], o.out)
    o = Office(tmp, "run-usage2").provider_up("apps", "drive-local", "600")
    check("run: no service is a usage error (exit 2), and nothing runs", o.rc == 2 and o.log() == [], o.out)
    o = Office(tmp, "run-missing").provider_up("apps", "drive-local", "600", "drive-local", PROVIDER_UP_BUILD="missing")
    check("run, as the enable runs it (PROVIDER_UP_BUILD=missing): no build of its own, `up` alone, and it is up",
          not o.logged("dc build drive-local") and o.logged(up("drive-local")) and o.rc == 0, o.out)

    # 18. A checkout that lost provider-up.sh is said as such, before anything is compiled or brought up.
    o = Office(tmp, "no-bring-up")
    (o.repo / "scripts" / "provider-up.sh").rename(o.repo / "scripts" / "provider-up.sh.away")
    try:
        o.run("drive")
    finally:
        (o.repo / "scripts" / "provider-up.sh.away").rename(o.repo / "scripts" / "provider-up.sh")
    check("no provider-up.sh: «this checkout is incomplete; nothing updated», exit 1, nothing asked of the office",
          o.rc == 1 and o.said("scripts/provider-up.sh could not be read — this checkout is incomplete; nothing updated")
          and o.log() == [], o.out)


def the_plan():
    try:
        import yaml  # noqa: F401 — the compiler's own requirement
    except ImportError:
        return "No module named 'yaml' — the plan half needs PyYAML, as the compiler does"

    def plan(*names):
        r = subprocess.run([sys.executable, str(HERE / "app-update-plan.py"), *names], cwd=REPO,
                           capture_output=True, text=True, timeout=60)
        return r.returncode, [ln.split() for ln in r.stdout.splitlines()], r.stderr
    rc, rows, err = plan("drive")
    providers = [r[2] for r in rows if r[0] == "provider"]
    check("the plan names drive as drive's own app, with its root and its service",
          rc == 0 and ["named", "drive", "drive", "apps", "drive"] in rows, err)
    check("drive's closure holds the split's two engines, each with the time of its first start and its service",
          ["provider", "apps", "drive-local", "600", "drive-local"] in rows
          and ["provider", "apps", "drive-google", "600", "drive-google"] in rows, err)
    check("the engine's own providers come before it (dependency order)",
          "connections" in providers and providers.index("connections") < providers.index("drive-local"), err)
    check("the named app itself is not a provider row", "drive" not in providers, err)
    check("what a provider's bring-up leaves to others is a row of its own (the vault's sign-in, n8n's automations)",
          ["later", "connections", "sign-in"] in rows and ["later", "n8n", "automations"] in rows, err)
    rc, rows, err = plan("drive", "drive-local")
    named = [r[1] for r in rows if r[0] == "named"]
    check("named apps come in dependency order (drive-local before drive)", named == ["drive-local", "drive"], err)
    rc, rows, err = plan("mailapi", "no-such-service")
    check("a service name finds the app that declares it", any(r[:3] == ["named", "mailapi", "mail"] for r in rows), err)
    check("a name nothing declares says so, last", rows and rows[1] == ["named", "no-such-service", "-", "-"] and rc == 0, err)
    rc, rows, err = plan()
    check("no name is a usage error", rc == 2, err)
    return None


def main():
    if shutil.which("bash") is None:
        print("NOT RUN  the update half: no bash here")
    else:
        with tempfile.TemporaryDirectory() as t:
            the_update(pathlib.Path(t))
    missing = the_plan()
    print()
    if FAILS:
        print(f"test_app_update: {len(FAILS)} FAILED")
        return 1
    if missing:
        # in the words gate G72 reads as «needs a package»: NOT RUN, never a pass
        print(f"test_app_update: the update half passed; NOT RUN: {missing}")
        return 1
    print("test_app_update: all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
