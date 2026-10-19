#!/usr/bin/env python3
"""DGO-5 · `bbox dgo test <n>` — the acceptance tests of one build phase, run against the declared
offices, printing PASS/FAIL with the measurement that decided it.

A gate is code, not a list. Each phase of ai/context/dgo-extend-plan.md ends in one, and this is the
frame they all use: a check is a function returning (ok, measured-text), every check runs (a failing
one never hides the next), and the exit code is the gate's answer — so a caller can depend on it.

    python3 apps/dgo-extend/tests/phase0.py          # all phases with a test file
    python3 apps/dgo-extend/tests/phase0.py 0        # phase 0 only
    python3 apps/dgo-extend/tests/phase0.py 0 vps1   # phase 0, one office
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
API = os.environ.get("DGO_EXTEND_URL", "")


# ── helpers ─────────────────────────────────────────────────────────────────────
def run(cmd: list[str], timeout: int = 120) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=ROOT)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 255, f"{type(e).__name__}: {e}"
    return p.returncode, (p.stdout + p.stderr).strip()


def container(prefix: str) -> str:
    """The running container of an app, by NAME PREFIX.

    Its name carries DEPLOYMENT_NAME, which is NOT exported in every place a gate runs (the owner's
    machine through the engine, a plain shell, CI), so anything that hardcodes `-local` works in one
    place and lies in the rest. Every app here is `<id>-<deployment>` and the id is enough.
    """
    code, out = run(["docker", "ps", "--filter", f"name=^{prefix}", "--format", "{{.Names}}"], 60)
    names = [n.strip() for n in out.splitlines() if n.strip()]
    return names[0] if code == 0 and names else ""


#: The last `inside()` failure, for the check that needs to say WHY it could not look.
LAST_INSIDE_ERR = ""


def inside(prefix: str, pycode: str, timeout: int = 60) -> str | None:
    """Run a snippet INSIDE an app's container — the one door that works from everywhere bbox runs:
    on the owner's machine the service name does not resolve and the edge wants a browser session,
    but the docker CLI is always there."""
    global LAST_INSIDE_ERR
    c = container(prefix)
    if not c:
        LAST_INSIDE_ERR = f"no running container matching {prefix}*"
        return None
    code, out = run(["docker", "exec", c, "python3", "-c", pycode], timeout)
    if code != 0 or not out:
        LAST_INSIDE_ERR = f"docker exec {c} exited {code}: {out[:160]}"
        return None
    return out


def http_json(url: str, headers: dict | None = None, timeout: int = 20):
    """(ok, payload_or_error) for one GET — the caller decides what a failure means."""
    try:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return True, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        return False, f"{type(e).__name__}: {e}"


def api(path: str, timeout: int = 20):
    """dgo-extend's API from wherever this runs: explicit URL, compose service name (inside the
    office network), then the container itself."""
    for base in [u for u in (API, "http://dgo-extend:8983") if u]:
        try:
            with urllib.request.urlopen(base.rstrip("/") + path, timeout=timeout) as r:
                return json.loads(r.read() or b"{}")
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            continue
    out = inside("dgo-extend-", "import urllib.request;print(urllib.request.urlopen("
                               f"'http://127.0.0.1:8983{path}',timeout=10).read().decode())")
    if out:
        try:
            return json.loads(out)
        except ValueError:
            pass
    return None


def offices() -> list[dict]:
    d = api("/api/office") or {}
    return d.get("items") or []


def check(name):
    def deco(fn):
        fn._check_name = name
        return fn
    return deco


# ── phase 0 · foundations (name, CLI, Plane, tree) ──────────────────────────────
@check("the app is `dgo-extend` and the compiler accepts it")
def c_name():
    manifest = ROOT / "apps/dgo-extend/app.json"
    if not manifest.exists():
        return False, "apps/dgo-extend/app.json is missing"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    code, out = run(["python3", "platform/manager/reconcile.py", "validate"], 180)
    if code != 0:
        return False, f"reconcile validate failed: {out.splitlines()[0] if out else '?'}"
    ok = data.get("id") == "dgo-extend" and data.get("title", {}).get("he") == "הרחבת הלשכה"
    return ok, f"id={data.get('id')} title={data.get('title', {}).get('he')} · validate clean"


@check("`bbox dgo` answers, and an unknown verb is refused")
def c_cli():
    code, out = run(["./bbox", "dgo"], 120)
    if code != 0:
        return False, f"bbox dgo exited {code}: {out[:160]}"
    declared = re.search(r"(\d+) office\(s\) declared", out)
    code2, out2 = run(["./bbox", "dgo", "no-such-verb"], 60)
    refused = code2 != 0
    return bool(declared) and refused, (f"{out.strip().splitlines()[0][:60]} · unknown verb "
                                        f"{'refused' if refused else 'ACCEPTED'}")


@check("the office tree is where the plan says it is")
def c_tree():
    need = ["app.json", "app.py", "converge.py", "move.py", "peers.py",
            "hooks/migrate", "hooks/prepare", "hooks/state", "hooks/test", "tests/phase0.py"]
    missing = [p for p in need if not (ROOT / "apps/dgo-extend" / p).exists()]
    state = (ROOT / "platform.state.yaml").read_text(encoding="utf-8")
    in_state = "dgo-extend:" in state and "offices:" not in state
    return not missing and in_state, (f"{len(need) - len(missing)}/{len(need)} files · "
                                      f"platform.state.yaml names dgo-extend: {in_state}")


#: `offices` as an app id: its folder, its host, its CLI group, its console alias, its entry in the
#: state file, its container.
STALE_ID = (r"apps/offices\b|\boffices\.(localhost|\$\{?DEPLOYMENT_DOMAIN)|\bbbox offices\b|/a/offices\b"
            r"|^\s+offices:\s*\{|\boffices-\$\{?DEPLOYMENT_NAME")


@check("no stale app id outside the migration and history")
def c_no_stale_id():
    # The retired ID, where an id stands — not the word. "offices" is also what this app is ABOUT,
    # and `-w offices` reported every file that says "linked offices" in a comment (39 of them on
    # 2026-10-06), so the check was red over prose and could not show a real stale reference.
    code, out = run(["grep", "-rlE", "--exclude-dir=node_modules", "--exclude-dir=__pycache__", STALE_ID,
                     "apps", "platform-base", "platform", "scripts", "bbox", "debian-install.sh",
                     "platform.state.yaml", ".env.ex"], 300)
    if "timed out" in out or code not in (0, 1):
        return False, f"the scan itself failed ({out[:80]}) — a gate that cannot run is not a pass"
    # The files below are ALLOWED to name the retired id, and they are the whole point: the migration
    # has to know what it is migrating FROM, the hook that calls it says so, and the test that guards
    # the rename necessarily mentions the old name. Everything else is a stale reference.
    allowed = ("ai/context/", "apps/project-pln/plans/", "platform/manager/reconcile.py",
               "apps/dgo-extend/hooks/migrate",
               "apps/dgo-extend/hooks/prepare", "apps/dgo-extend/hooks/test",
               "apps/dgo-extend/tests/")
    hits = [f.strip().lstrip("./") for f in out.splitlines() if f.strip()]
    stale = [h for h in hits if not h.startswith(allowed)]
    return not stale, (f"{len(stale)} unexpected · " + ", ".join(stale[:4]) if stale
                       else f"{len(hits)} hits, all in the migration/history")


@check("Plane holds the DGO project")
def c_plane():
    token = ""
    env = ROOT / ".env"
    if env.exists():
        # Only the LOCAL token, and by name: `.env` also carries the cloud placeholder
        # (`PLANE_API_KEY=your-plane…`), and a check that used it reported "no DGO project" over a
        # working project.
        m = re.search(r"^PLANE_LOCAL_API_TOKEN=(\S+)$", env.read_text(encoding="utf-8"), re.M)
        token = (m.group(1).strip() if m else "")
    if not token:
        # The vault holds the real one (minted by the Plane app). Reached from inside the office
        # network AND from the owner's machine, where only the container is reachable.
        ok, got = http_json("http://connections:8990/api/instances/plane_local_api_token-local/secret")
        if ok and isinstance(got, dict):
            token = ((got.get("secret") or {})).get("token", "")
        if not token:
            out = inside("connections-", "import urllib.request;print(urllib.request.urlopen("
                                         "'http://127.0.0.1:8990/api/instances/"
                                         "plane_local_api_token-local/secret',timeout=10).read().decode())")
            if out:
                try:
                    token = ((json.loads(out).get("secret") or {})).get("token", "")
                except ValueError:
                    token = ""
    if not token:
        return False, ("no Plane API token: .env has none and the credential plane did not "
                              f"answer ({LAST_INSIDE_ERR})")

    slug = os.environ.get("DGO_PLANE_WORKSPACE") or "bina"
    path = f"/api/v1/workspaces/{slug}/projects/"
    names, why = None, ""
    # The IDENTIFIER is the project's key — every ref (DGO-12) is made of it; the name is a label the
    # owner may change, and did («הלשכה הדיגיטלית»), which this check then read as "no DGO project".
    def named(doc):
        return [f"{p.get('identifier')} «{p.get('name')}»" for p in (doc.get("results") or [])]

    ok, pr = http_json(f"http://project-pln{path}", {"X-API-Key": token})
    if ok and isinstance(pr, dict):
        names = named(pr)
    else:
        why = str(pr)
        out = inside("project-pln-", "import urllib.request;"
                     f"r=urllib.request.Request('http://127.0.0.1:80{path}',"
                     f"headers={{'X-API-Key':'{token}'}});"
                     "print(urllib.request.urlopen(r,timeout=15).read().decode())")
        if out:
            try:
                names = named(json.loads(out))
            except ValueError:
                names = None
    if names is None:
        return False, f"Plane API did not answer (service name then container): {why}"
    if any(n.startswith("DGO ") for n in names):
        return True, f"workspace {slug}: DGO present ({len(names)} projects: {', '.join(names)})"
    return False, f"no DGO project in {slug}: {names}"


PHASES = {0: [c_name, c_cli, c_tree, c_no_stale_id, c_plane]}


def _load_later_phases():
    """Import phaseN.py for N > 0, INSIDE main and not at import time.

    phase1.py imports this file for the shared frame, so importing it at module level here is a
    circular import — and the failure is an AttributeError that reads like a broken phase file rather
    than what it is. The frame must be fully defined before a phase module can use it.
    """
    import importlib
    for n in range(1, 10):
        path = Path(__file__).resolve().parent / f"phase{n}.py"
        if not path.exists():
            continue
        try:
            mod = importlib.import_module(f"phase{n}")
            PHASES[n] = getattr(mod, f"PHASE{n}")
        except (ImportError, AttributeError) as e:
            print(f"  (phase {n} could not be loaded: {type(e).__name__}: {e})")


def main() -> int:
    _load_later_phases()
    want = sys.argv[1] if len(sys.argv) > 1 else None
    phases = [int(want)] if want and want.isdigit() and int(want) in PHASES else sorted(PHASES)
    failed = skipped = 0
    for n in phases:
        print(f"\n── phase {n}")
        for fn in PHASES[n]:
            # THREE verdicts. `None` is "this office has nothing of the kind to measure" — said,
            # counted and printed, because a check that passes over nothing and a check that passes
            # are not the same fact, and one that FAILS over nothing teaches people to ignore the gate.
            ok, measured = fn()
            print(f"  {'N/A ' if ok is None else 'PASS' if ok else 'FAIL'}  {fn._check_name}\n        {measured}")
            failed += 1 if ok is False else 0
            skipped += 1 if ok is None else 0
    print(f"\n{'PASS' if not failed else 'FAIL'} — {failed} failing check(s)"
          + (f", {skipped} not applicable on this office" if skipped else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
