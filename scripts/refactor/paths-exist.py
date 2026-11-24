#!/usr/bin/env python3
"""paths-exist — gate G0: every host path the rendered compose references must EXIST.

    python3 scripts/refactor/paths-exist.py [config.yml]

With no argument the config is the render itself, `bash scripts/dc config` — see `default_input()`.
A config that cannot be produced, or one that declares no service at all, is a FAILURE (exit 2),
never a green line over nothing.

Why this exists as a separate gate: the retired G1 (compose-equiv, deleted 2026-07-30) compared
config TEXT. It could not notice that a path which still renders identically has stopped existing
on disk — and NOTHING comparing text ever can. Docker then does the worst possible thing: for a
bind mount it silently CREATES an empty directory and the service comes up "healthy" reading
nothing. So this gate asserts a PROPERTY of the render rather than its bytes, which is why it
outlived G1.

That is exactly what happened moving chat: `connections` kept mounting
apps/chat/data, docker created it empty, and the WhatsApp pairing probe
would have read an empty dir forever. G1 passed the whole time.

So: after every move, assert the filesystem agrees with the config.
Exit 0 = every referenced host path exists. Exit 1 = at least one is missing. Exit 2 = no config
could be read, so nothing was checked.

The second half of the gate asks the same question of a SCRIPT's references (see
`dead_script_refs()`): a script naming "${REPO_ROOT}/sibling" expects that file in the tree, and a
move leaves the text looking right while bash reports "No such file or directory" into a log nobody
reads. That check carries the same waiver as the host paths — one entry per reference, named, with
its reason, in `platform/external-script-refs.yaml`, which must reach empty — because some
references are deliberately not files we ship: a lock note written on demand, a test's own fixture,
a build artifact. A waiver never skips a file or a directory whole, and one that outlived its
reference fails.
"""
import sys, pathlib, re, subprocess


def engine_sees(path):
    """Is this host path one the ENGINE is already using? Asked WITHOUT creating anything.

    G0 resolves host paths for a compose render, and a render is applied by the engine — so "does
    this path exist" belongs to the engine's machine. Inside a container (the office agent's, an
    in-image CI lane) `p.exists()` is false for every host path the container did not receive under
    the same name: `/run/bbox-docker.sock` arrives as `/var/run/docker.sock`, and this gate invented
    nine missing binds that are present on the host (measured 2026-10-09). A false red is worse than a
    true one — it teaches people to ignore the gate that catches docker's worst silent failure: a bind
    whose source vanished becomes an EMPTY DIRECTORY and the service comes up "healthy" reading
    nothing (the `apps/chat/data` incident this file's own docstring remembers).

    Ask the engine what its RUNNING containers already mount. Never a throwaway `-v`: measured
    2026-10-09, `docker run -v <missing>:/x` CREATES the missing source, so it answers "exists" for
    every path and would turn this gate permanently green. A path no running container declares keeps
    the ordinary `p.exists()` answer; no docker at all means "cannot say".
    """
    try:
        ids = subprocess.run(["docker", "ps", "-q"], capture_output=True, text=True,
                             timeout=30).stdout.split()
        if not ids:
            return False
        sources = subprocess.run(["docker", "inspect", "--format",
                                  '{{range .Mounts}}{{.Source}}{{"\\n"}}{{end}}', *ids],
                                 capture_output=True, text=True, timeout=60).stdout
        return path in sources.split()
    except Exception:
        return False

try:
    import yaml
except ImportError:
    sys.exit("PyYAML required")

REPO = pathlib.Path(__file__).resolve().parents[2]
GEN = REPO / ".generated"


def _from_dc_config():
    """The merged project, exactly as docker resolves it: `bash scripts/dc config` -> stdout.

    `-f .generated/compose.yml` plus the routing and connections overlays, every `${VAR}`
    interpolated, every relative path (resolved against ITS OWN compose file's directory, which is
    what compose does with an included file — measured 2026-11-03: apps/apitools' `./logs` becomes
    apps/apitools/logs, not <repo>/logs). It starts nothing and reads no engine state; on this
    office it takes 4.8 s for 58 services.

    It is also the same render ci-verify.yml feeds G0 (that job writes `./scripts/dc config` into
    /tmp/candidate.yml and passes the path in), so the bare gate and the CI gate now check the same
    thing instead of two different guesses.
    """
    dc = REPO / "scripts" / "dc"
    if not dc.exists():
        return None, "scripts/dc is missing"
    try:
        r = subprocess.run(["bash", str(dc), "config"], cwd=str(REPO),
                           capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as e:
        return None, "scripts/dc config did not run: %s" % e
    if r.returncode != 0:
        tail = [ln for ln in (r.stderr or "").strip().splitlines() if ln.strip()][-1:]
        if not (GEN / "compose.yml").is_file():
            return None, ("%s has not been rendered yet — run `python3 platform/manager/"
                          "reconcile.py render` first (scripts/dc read: %s)"
                          % ((GEN / "compose.yml").relative_to(REPO),
                             tail[0] if tail else "no output"))
        return None, "scripts/dc config exited %d%s" % (r.returncode,
                                                        (": " + tail[0]) if tail else "")
    try:
        return yaml.safe_load(r.stdout), "scripts/dc config"
    except yaml.YAMLError as e:
        return None, "scripts/dc config printed no YAML: %s" % e


def data_home_stores():
    """The stores every app declares in the DGO folder — `data.paths` under data/ of apps/*/app.json and
    platform-base/*/app.json (DGO-2019). `bbox run`'s data move makes each before `up` (seeded, or moved into from its
    old volume or folder), so a fresh checkout's render binds them before they exist and that is no miss: a bind to
    data/ that NO app declares still is."""
    import json
    out = set()
    for mf in sorted(REPO.glob("apps/*/app.json")) + sorted(REPO.glob("platform-base/*/app.json")):
        try:
            paths = ((json.loads(mf.read_text(encoding="utf-8")).get("data") or {}).get("paths") or [])
        except (OSError, ValueError):
            continue
        out |= {str(p).rstrip("/") for p in paths if str(p).startswith("data/")}
    return out


def store_decided(rel):
    """Whether a run already decided this store (the data move's record exists: data/.moves/<app>/<store>.json): then
    it was made, and a folder missing now was removed — the empty-folder case this gate exists for, never exempt."""
    parts = rel.split("/", 2)
    sub = parts[2] if len(parts) > 2 else "_"
    return (REPO / "data" / ".moves" / parts[1] / (sub.replace("/", "__") + ".json")).exists()


def default_input():
    """The config to check when no path was given: (cfg, how) or (None, why).

    It used to be `.refactor/candidate.yml`, a gitignored render that a cleanup deleted. Running the
    gate bare — which is exactly what `run-gates.py --all` does — then died on FileNotFoundError
    BEFORE checking a single path, so the battery counted G0 as a crash that said nothing about the
    tree, while the gate's own docstring says a vanished path is how docker silently mounts an empty
    directory.

    WHY NOT READ `.generated/compose.yml` ITSELF, which is the declaration that always exists: because
    it is an `include:` LIST, not a config — it declares ZERO services, so a gate handed it would
    print "all 0 host paths exist" and pass over nothing, which is the one answer this file must
    never give. The same file is what `scripts/dc config` starts from, and that command resolves the
    chain it names into services with real, absolute paths. So: no second parser here, no guess at
    how compose merges, one source — and when it cannot be produced, (None, why), so `main()` fails
    loudly instead of passing quietly.
    """
    cfg, how = _from_dc_config()
    if cfg is None:
        return None, how
    if not isinstance(cfg, dict) or not (cfg.get("services") or {}):
        return None, "%s declares no service (nothing to assert)" % how
    return cfg, how


def host_paths(cfg):
    """Yield (service, kind, path) for every host path compose will touch."""
    for name, svc in (cfg.get("services") or {}).items():
        b = svc.get("build")
        if isinstance(b, dict) and b.get("context"):
            yield name, "build.context", b["context"]
        elif isinstance(b, str):
            yield name, "build", b
        for v in svc.get("volumes") or []:
            if isinstance(v, dict):
                if v.get("type") == "bind" and v.get("source"):
                    yield name, "bind", v["source"]
            elif isinstance(v, str) and (v.startswith(("/", ".")) or ":\\" in v or ":/" in v[1:3]):
                src = v.split(":")[0] if not v[1:3] == ":\\" else v.rsplit(":", 2)[0]
                yield name, "bind", src
        for e in svc.get("env_file") or []:
            yield name, "env_file", e if isinstance(e, str) else e.get("path", "")


# "${SCRIPT_DIR}/n8n-push", "${SCRIPTS}/x", "${REPO_ROOT}/bbox" — a script reaching for another
# file in the tree by variable-rooted path.
SCRIPT_REF = re.compile(r'"\$\{(SCRIPT_DIR|SCRIPTS|REPO_ROOT|UM_DIR|SELF_DIR)\}/([\w./-]+)"')
# SCRIPT_DIR/SELF_DIR/UM_DIR are each script's OWN directory — resolving them to a fixed
# "scripts" flagged scripts/ui-coverage/run_capture.sh for its own capture.py, which is right
# beside it. SCRIPTS and REPO_ROOT are absolute roots.
OWN_DIR = {"SCRIPT_DIR", "SELF_DIR", "UM_DIR"}
VAR_ROOT = {"SCRIPTS": "scripts", "REPO_ROOT": ""}

# A directory the script CREATES is an output, not a rotted reference. ci-artifacts/ is gitignored
# (build output), so it is absent from a fresh clone and G0 flagged baseline.sh / extract-gate.sh
# for a path they both `mkdir -p` themselves. Match the two shapes actually used:
#   mkdir -p "${REPO_ROOT}/ci-artifacts"          -- literal
#   ART="${REPO_ROOT}/ci-artifacts"; mkdir -p "${ART}"   -- via a variable
MKDIR_LITERAL = re.compile(r'mkdir\s+(?:-\w+\s+)*"\$\{(?:\w+)\}/([\w./-]+)"')
ASSIGN_REF = re.compile(r'(\w+)="\$\{(?:SCRIPT_DIR|SCRIPTS|REPO_ROOT|UM_DIR|SELF_DIR)\}/([\w./-]+)"')


def created_dirs(text):
    """Relative paths this script guarantees exist by creating them."""
    made = set(MKDIR_LITERAL.findall(text))
    assigned = {var: rel for var, rel in ASSIGN_REF.findall(text)}
    for var, rel in assigned.items():
        if re.search(r'mkdir\s+(?:-\w+\s+)*"\$\{%s\}"' % re.escape(var), text):
            made.add(rel)
    return made


def dead_script_refs():
    """Shell scripts invoking a sibling that no longer exists.

    Same failure as a vanished bind mount, different medium: a move leaves the reference behind and
    the text still looks right. scripts/ci-verify.sh called "${SCRIPT_DIR}/n8n-push" for the whole
    refactor after the hook moved to apps/n8n/hooks/push. Bash reports "No such file or
    directory" INTO the step's own log file, the step records a generic failure, and the baseline
    reported five red checks that all cascaded from one dead path.
    """
    out = []
    for f in sorted((REPO / "scripts").rglob("*")):
        if not f.is_file() or f.suffix not in ("", ".sh") or "__pycache__" in f.as_posix():
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        made = created_dirs(text)
        for m in SCRIPT_REF.finditer(text):
            var, rel = m.group(1), m.group(2)
            base = f.parent if var in OWN_DIR else REPO / VAR_ROOT[var]
            target = (base / rel).resolve()
            # only flag a reference that looks like a FILE we ship, not a runtime artifact
            if target.exists() or "/tmp" in rel or rel.endswith(("/", ".log", ".json", ".yml")):
                continue
            # the script creates it itself (gitignored build output) — absent in a fresh clone by design
            if rel in made:
                continue
            # .env is operator/CI-generated config (scripts/ci-env.sh), never shipped. A script
            # sourcing it is correct; a fresh checkout simply has not generated it yet.
            if rel == ".env" or rel.startswith(".env"):
                continue
            try:
                shown = target.relative_to(REPO).as_posix()
            except ValueError:
                shown = target.as_posix()
            out.append((f.relative_to(REPO).as_posix(), m.group(0), shown))
    return out


def _load(path):
    p = REPO / path
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def script_ref_waivers():
    """`platform/external-script-refs.yaml`'s entries: (file, ref, the times that file makes it, why).

    The same declaration `external-paths.yaml` makes for a host path, for a reference that is
    deliberately not a file we ship. One entry covers ONE text in ONE file, so a new reference of a
    text it does not name — or one more of a text it does — still fails.
    """
    out = []
    for e in (_load("platform/external-script-refs.yaml").get("script_refs") or []):
        out.append((str(e["file"]), str(e["ref"]), int(e.get("count", 1)), str(e.get("why", ""))))
    return out


def judge_script_refs(dead, waivers):
    """(fails, acknowledged, stale) over the dead references.

    fails: what no entry names, plus the occurrences past a named entry's count.
    stale: an entry nothing references any more, or one that declares more than the file makes — a
    waiver may not outlive what it explains, exactly as a host-path waiver may not.
    """
    held = {}
    for src, ref, _resolved in dead:
        k = (src, ref.strip('"'))
        held[k] = held.get(k, 0) + 1
    left, acked, stale = dict(held), [], []
    for f, ref, count, _why in waivers:
        n = held.get((f, ref), 0)
        if not n:
            stale.append(f"{f}: {ref} is acknowledged in platform/external-script-refs.yaml and nothing "
                         f"references it: remove its entry")
            continue
        acked.append((f, ref, min(n, count)))
        left[(f, ref)] = n - min(n, count)
        if n < count:
            stale.append(f"{f}: {ref} is acknowledged {count} time(s) and referenced {n}: lower its count")
    fails = []
    for src, ref, resolved in dead:
        k = (src, ref.strip('"'))
        if left.get(k, 0) > 0:
            left[k] -= 1
            fails.append((src, ref, resolved))
    return fails, acked, stale


def main():
    if len(sys.argv) > 1:
        cand = pathlib.Path(sys.argv[1])
        if not cand.is_file():
            print(f"G0 FAIL — the config named on the command line does not exist: {cand}")
            print("  Nothing was checked. An empty answer is not a pass (exit 2).")
            return 2
        try:
            cfg = yaml.safe_load(cand.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            print(f"G0 FAIL — {cand} is not YAML: {e}")
            return 2
        how = cand.as_posix()
    else:
        cfg, how = default_input()
        if cfg is None:
            print("G0 FAIL — no compose config to check, so NO path was checked: %s" % how)
            print("  The gate must run against a declaration that exists, and the one it renders by")
            print("  default is `bash scripts/dc config` (render first: `python3 platform/manager/"
                  "reconcile.py render`).")
            print("  A green line over zero services is the one answer it must not give (exit 2).")
            return 2

    if not isinstance(cfg, dict) or not (cfg.get("services") or {}):
        print(f"G0 FAIL — {how} declares zero services; nothing to assert, so this is not a pass.")
        return 2

    allow = _load("platform/external-paths.yaml")

    missing, waived, checked, made = [], [], 0, []
    stores = data_home_stores()
    for svc, kind, raw in host_paths(cfg):
        if not raw:
            continue
        p = pathlib.Path(raw.replace("\\", "/"))
        # docker.sock and other pseudo/host-absolute paths outside the repo are not ours to assert
        s = p.as_posix()
        if s.startswith(("/var/run", "/proc", "/sys", "/dev")) or s == "/":
            continue
        if not p.is_absolute():
            p = REPO / p
        checked += 1
        if not p.exists() and not engine_sees(s):
            try:
                rel = p.resolve().relative_to(REPO.resolve()).as_posix()
            except ValueError:
                rel = None
            st = next((x for x in stores if rel and (rel == x or rel.startswith(x + "/"))), None)
            if st and not store_decided(st):
                made.append((svc, kind, rel))              # a store the data move makes before `up` (DGO-2019)
                continue
            (waived if s in allow or raw in allow else missing).append((svc, kind, s))

    # BOTH findings in ONE run. The dead-sibling check used to return before the path report, so a
    # rotted script reference hid every missing host path behind it — the same "a gate that stops
    # early checks nothing" shape as the input default this file just lost.
    dead_fails, dead_waived, dead_stale = judge_script_refs(dead_script_refs(), script_ref_waivers())
    if dead_fails:
        print(f"G0 FAIL - {len(dead_fails)} script(s) invoke a sibling that does not exist:")
        for src, ref, resolved in dead_fails:
            print(f"  {src}: {ref}   ->   {resolved}")
        print("  -> the file moved; call it through ./bbox so the path cannot rot again")
    for s in dead_stale:
        print(f"G0 FAIL - {s}")

    if missing:
        print(f"G0 FAIL — {len(missing)} referenced host path(s) do not exist "
              f"(docker would silently create empty dirs):")
        for svc, kind, s in missing:
            print(f"  {svc:24} {kind:14} {s}")
    if dead_fails or dead_stale or missing:
        print(f"G0 — {checked - len(waived) - len(made)} enforced host path(s) checked in {how}; "
              f"{len(missing)} missing, {len(waived)} waived, {len(made)} declared store(s) the data move makes")
        return 1
    if waived:
        print(f"G0 note — {len(waived)} acknowledged external path(s) "
              f"(platform/external-paths.yaml — must reach empty):")
        for svc, kind, s in waived:
            print(f"  {svc:24} {kind:14} {s}")
    if dead_waived:
        print(f"G0 note — {sum(n for _, _, n in dead_waived)} acknowledged script reference(s) "
              f"(platform/external-script-refs.yaml — must reach empty):")
        for f, ref, n in dead_waived:
            print(f"  {f}: {ref}   x{n}")
    if made:
        print(f"G0 note — {len(made)} declared store(s) in data/ not made yet: `bbox run`'s data move makes each before "
              f"`up` (DGO-2019): {', '.join(sorted({r for _, _, r in made}))}")
    print(f"G0 PASS — all {checked - len(waived) - len(made)} enforced host paths exist (from {how})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
