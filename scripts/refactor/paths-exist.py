#!/usr/bin/env python3
"""paths-exist — gate G0: every host path the rendered compose references must EXIST.

    python3 scripts/refactor/paths-exist.py [.refactor/candidate.yml]

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
Exit 0 = every referenced host path exists. Exit 1 = at least one is missing.
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


def main():
    cand = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".refactor/candidate.yml")
    cfg = yaml.safe_load(cand.read_text(encoding="utf-8"))

    allow = {}
    ap = REPO / "platform/external-paths.yaml"
    if ap.exists():
        allow = yaml.safe_load(ap.read_text(encoding="utf-8")) or {}

    missing, waived, checked = [], [], 0
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
            (waived if s in allow or raw in allow else missing).append((svc, kind, s))

    dead = dead_script_refs()
    if dead:
        print(f"G0 FAIL - {len(dead)} script(s) invoke a sibling that does not exist:")
        for src, ref, resolved in dead:
            print(f"  {src}: {ref}   ->   {resolved}")
        print("  -> the file moved; call it through ./bbox so the path cannot rot again")
        return 1

    if missing:
        print(f"G0 FAIL — {len(missing)} referenced host path(s) do not exist "
              f"(docker would silently create empty dirs):")
        for svc, kind, s in missing:
            print(f"  {svc:24} {kind:14} {s}")
        return 1
    if waived:
        print(f"G0 note — {len(waived)} acknowledged external path(s) "
              f"(platform/external-paths.yaml — must reach empty):")
        for svc, kind, s in waived:
            print(f"  {svc:24} {kind:14} {s}")
    print(f"G0 PASS — all {checked - len(waived)} enforced host paths exist")
    return 0


if __name__ == "__main__":
    sys.exit(main())
