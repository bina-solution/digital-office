#!/usr/bin/env python3
"""data-volumes-lint — gate G26: `data.volumes` in app.json must tell the truth about the app's state.

    python3 scripts/refactor/data-volumes-lint.py

`data.volumes` is the field that answers "what would I lose if this app's state went away". Nothing
reads it today, which is exactly why it rotted: `drive` declares `[]` while owning `localdrive_data`,
and several apps keep state in host binds no manifest mentions.

That matters the moment anyone writes backup tooling, because `data.volumes` is the only
machine-readable inventory of state this platform has — a backup derived from it would silently skip
every volume the manifest forgot, and you would not find out until a restore. A wrong inventory is
worse than no inventory: it produces a backup that appears to succeed.

So this gate asserts the two directions that can be checked statically:

  1. COMPLETE  — every top-level named volume in the app's compose appears in `data.volumes`, and so
                 does every writable host bind that holds state.
  2. GROUNDED  — every name in `data.volumes` is a volume the app's compose actually declares, so an
                 entry cannot outlive the volume it names.

Read-only mounts, the docker socket, build contexts and source-code binds are not state and are
skipped — see SKIP rules below. A genuine exception goes in platform/data-volumes-waivers.yaml with
a reason, so "we thought about it" and "we forgot" stop looking identical.

Exit 0 = every app's declaration matches its compose. Exit 1 = at least one does not.
"""
import sys, pathlib, json, subprocess

try:
    import yaml
except ImportError:
    sys.exit("PyYAML required")

REPO = pathlib.Path(__file__).resolve().parents[2]
ROOTS = ("apps", "platform-base")

# Pseudo-paths and host devices: real, but not this app's state to back up.
SKIP_PREFIX = ("/var/run", "/proc", "/sys", "/dev", "/etc/localtime", "/etc/timezone")


def tracked_paths():
    """Every path git tracks, plus every directory containing one.

    This is the load-bearing rule of the gate: **if git tracks it, it is not state.** State is by
    definition the thing that is NOT in the repo — it is what a fresh clone does not have and a
    restore has to put back. Everything else mounted from the tree (authentik's ./blueprints, n8n's
    ./workflows, postgres's ./volumes/db/*.sql, supabase's kong.yml) is configuration being injected
    into a container, and backing it up would just be backing up the repo.

    Deriving it from git rather than from a hand-written list of directory names means the rule
    cannot drift as directories are renamed, and a new config mount never needs a new exception.
    """
    try:
        # BYTES, decoded explicitly. `text=True` decodes with the platform codepage, and this repo
        # tracks Hebrew filenames — on a Windows checkout that raises UnicodeDecodeError (cp1255)
        # and the gate dies before it checks anything.
        raw = subprocess.run(["git", "ls-files", "-z"], cwd=REPO,
                             capture_output=True, check=True).stdout
        out = raw.decode("utf-8", errors="surrogateescape")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None                                   # not a git checkout — fall back to declaring
    paths = set()
    for rel in out.split("\0"):
        if not rel:
            continue
        p = pathlib.PurePosixPath(rel)
        paths.add(p.as_posix())
        for parent in p.parents:
            if parent.as_posix() not in (".", "/"):
                paths.add(parent.as_posix())
    return paths


TRACKED = tracked_paths()


def load_yaml(p):
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as e:                                    # a broken compose is G12's problem
        print(f"  ! could not parse {p.relative_to(REPO).as_posix()}: {e}")
        return {}


def bind_is_state(source, mount, app_dir):
    """Is this host bind holding state the app would want restored?"""
    s = source.replace("\\", "/")
    if s.startswith(SKIP_PREFIX) or s == "/":
        return False
    if isinstance(mount, str) and mount.rstrip().endswith(":ro"):
        return False
    if isinstance(mount, dict) and mount.get("read_only"):
        return False
    if TRACKED is None:
        return True

    # Resolve the bind the way compose does — relative to the compose file's directory.
    if s.startswith("/"):
        try:
            rel = pathlib.Path(s).resolve().relative_to(REPO).as_posix()
        except ValueError:
            return True          # an absolute path outside the tree: unresolvable here, so declare
                                 # it or waive it with a reason. Cannot be judged statically.
    else:
        try:
            rel = (app_dir / s).resolve().relative_to(REPO).as_posix()
        except ValueError:
            return True

    return rel not in TRACKED    # tracked by git => config being injected, not state


def _repo_rel(app_dir, source):
    """A bind source resolved the way compose resolves it, as a repo-relative path (None if outside)."""
    s = source.replace("\\", "/")
    try:
        base = pathlib.Path(s) if s.startswith("/") else app_dir / s
        return base.resolve().relative_to(REPO).as_posix()
    except ValueError:
        return None


def scan(app_dir):
    """(named_volumes, stateful_binds) declared across every compose file in this app."""
    named, binds = set(), set()
    # ONLY docker-compose.yml — the file the compiler includes. Siblings like
    # docker-compose.standalone.yml are self-contained harnesses for running a service outside the
    # platform (any-concurrency's brings its own n8n + postgres); their volumes are never created by
    # a real deployment, so demanding they be declared as platform state would be a lie in the other
    # direction.
    for cf in [app_dir / "docker-compose.yml"]:
        if not cf.exists():
            continue
        cfg = load_yaml(cf)
        for v in (cfg.get("volumes") or {}):
            named.add(v)
        for svc in (cfg.get("services") or {}).values():
            if not isinstance(svc, dict):
                continue
            for m in svc.get("volumes") or []:
                if isinstance(m, dict):
                    src = m.get("source")
                    if m.get("type") == "bind" and src and bind_is_state(src, m, app_dir):
                        binds.add(src.replace("\\", "/"))
                elif isinstance(m, str):
                    src = m.split(":")[0]
                    if src.startswith((".", "/")) and bind_is_state(src, m, app_dir):
                        binds.add(src)
    return named, binds


def main():
    waiv_path = REPO / "platform/data-volumes-waivers.yaml"
    waivers = load_yaml(waiv_path) if waiv_path.exists() else {}

    missing, orphan, checked = [], [], 0
    for root in ROOTS:
        for app_dir in sorted((REPO / root).iterdir()):
            manifest = app_dir / "app.json"
            if not app_dir.is_dir() or not manifest.exists():
                continue
            try:
                app = json.loads(manifest.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                print(f"G26 FAIL — {manifest.relative_to(REPO).as_posix()} is not valid JSON: {e}")
                return 1

            app_id = app.get("id") or app_dir.name
            # data.paths declares a BIND the app owns, and this gate's whole job is "declared or
            # waived". Counting only data.volumes would leave an app that correctly declared its
            # bind still failing, and push a real declaration into the waiver file — where it would
            # read as "we decided this is not app state", the opposite of what it means.
            declared = (set((app.get("data") or {}).get("volumes") or [])
                        | set((app.get("data") or {}).get("paths") or []))
            named, binds = scan(app_dir)
            if not named and not binds and not declared:
                continue
            checked += 1

            waived = set(waivers.get(app_id) or [])
            for v in sorted((named | binds) - declared - waived):
                # A bind is written relative to its compose file ("../../data/power") while data.paths
                # is repo-relative ("data/power"); the same directory must count as declared either way.
                if v in binds and _repo_rel(app_dir, v) in declared:
                    continue
                missing.append((app_id, v, "named volume" if v in named else "stateful bind"))
            # ORPHAN applies to VOLUMES only. A named volume that no compose file creates is a typo
            # or a rename, and catching that is the check's whole point. A declared PATH is a
            # different claim: it says "this directory's state is mine", and it is legitimately made
            # about directories this scan does not classify as stateful binds — platform-base/
            # traefik/config is tracked config that also holds acme.json, an untracked file carrying
            # every issued TLS private key. Judging paths by the volume rule marked both authentik
            # and traefik orphaned for declaring exactly what they own. Paths are checked for
            # EXISTENCE instead, just below.
            declared_paths = set((app.get("data") or {}).get("paths") or [])
            for v in sorted(set((app.get("data") or {}).get("volumes") or [])
                            - named - binds - waived):
                orphan.append((app_id, v))
            # …or for being a BIND of this app's own compose: a directory the stack creates at its
            # first `up` (machine's data/power, git-ignored) does not exist on a clone that has never
            # run, and that is not a typo — the compose names it. What is still caught is the path
            # that neither exists nor is bound by anything: a declaration about nothing.
            bound = {_repo_rel(app_dir, b) for b in binds}
            for p in sorted(declared_paths - waived):
                if not (REPO / p).exists() and p not in bound:
                    orphan.append((app_id, p + "  (declared in data.paths: not on disk, and no bind of this app names it)"))

    if missing:
        print(f"G26 FAIL — {len(missing)} volume(s) hold state no app.json declares "
              f"(a backup built from data.volumes would skip them):")
        for app_id, v, kind in missing:
            print(f"  {app_id:24} {kind:15} {v}")
    if orphan:
        print(f"G26 FAIL — {len(orphan)} data.volumes entr(ies) name nothing the compose declares:")
        for app_id, v in orphan:
            print(f"  {app_id:24} {'declared, absent':15} {v}")
    if missing or orphan:
        print("  -> add it to data.volumes in the app's app.json, or waive it with a reason in "
              "platform/data-volumes-waivers.yaml")
        return 1

    print(f"G26 PASS — {checked} app(s) declare exactly the state their compose creates")
    return 0


if __name__ == "__main__":
    sys.exit(main())
