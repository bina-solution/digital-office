#!/usr/bin/env python3
"""app-management — the platform control plane (layer 1).

Stage 1: the catalog + live status. Reads every app.json manifest and platform.state.yaml straight
from the mounted repo (the manifests ARE the source of truth — no need to re-run the compiler just
to list apps), and joins that with live container state from the docker socket.

Later stages add enable / disable / uninstall with real apply. The lifecycle LOGIC lives here — the
platform's app-management surface is one app, not scattered across bbox and the console.
"""
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # Hebrew titles; cp1255 default on Windows crashes

import glob
import json
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import yaml
from flask import Flask, jsonify, request, send_from_directory

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # its own modules, however it is loaded
import admission  # noqa: E402

try:
    import docker as docker_sdk
except Exception:  # pragma: no cover - the SDK is always installed, but never crash the catalog
    docker_sdk = None

REPO = os.getenv("REPO_DIR", "/repo")


def _repo_env(name: str, _depth: int = 0) -> str:
    """One value out of the deployment's .env (the container mounts the repo; it has no copy of the
    env itself), with `${OTHER}` references expanded the way compose expands them — the production
    file spells DEPLOYMENT_DOMAIN as `${COMPANY_SLUG}.${COMPANY_BASE_DOMAIN}`. Empty when absent or
    blank — never a guess."""
    v = (os.environ.get(name) or "").strip()
    if not v:
        try:
            with open(os.path.join(REPO, ".env"), encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith(name + "="):
                        v = line[len(name) + 1:].strip().strip('"').strip("'")
                        break
        except OSError:
            v = ""
    if "${" in v and _depth < 5:
        import re as _re
        v = _re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}",
                    lambda m: _repo_env(m.group(1), _depth + 1) or (m.group(2) or ""), v)
    return v.strip()


def _is_localhost(v: str) -> bool:
    """True for a bare host / URL whose HOSTNAME is localhost or a *.localhost twin. The hostname
    alone decides — a value may carry the edge's host port (`n8n.localhost:8080` on the macOS
    engine, where an unprivileged process cannot bind :80), and `.localhost:8080` does not end
    with `.localhost`."""
    h = re.sub(r"^https?://", "", v).split("/", 1)[0].rsplit(":", 1)[0].lower()
    return h == "localhost" or h.endswith(".localhost")


def _public_origin(app_id: str, host: str, base_url_env: str | None) -> str:
    """Where an app's UI is reachable from the operator's browser.

    One owner for the public host: the same `<APP>_BASE_URL` variable reconcile renders into every
    emitted `Host()` rule (reconcile.base_url_env) — so the tile opens exactly the host traefik
    routes. Order: the routing entry's own `sso.base_url_env` → `<APP>_BASE_URL` → `<host>.<DEPLOYMENT_DOMAIN>`
    → `<host>.localhost`. https for any real domain; http only for localhost twins.

    [2026-09-17] Apps > n8n opened `http://n8n.localhost` — refused. n8n declares no
    `sso.base_url_env` (auth: none), so this fell straight to the `.localhost` guess and dropped
    the :8080 the macOS engine's edge lives on, although `.env` said `N8N_BASE_URL=n8n.localhost:8080`
    all along. The apps that DID declare one fared no better: `.localhost:8080` failed the
    `.endswith('.localhost')` test and came back as https://."""
    v = ""
    for name in (base_url_env, _base_url_env(app_id)):
        v = _repo_env(name) if name else ""
        if v:
            break
    if v:
        if not v.startswith(("http://", "https://")):
            v = ("http://" if _is_localhost(v) else "https://") + v
        return v.rstrip("/")
    dom = _repo_env("DEPLOYMENT_DOMAIN") or _repo_env("COMPANY_BASE_DOMAIN")
    if dom and dom != "localhost":
        return f"https://{host}.{dom}"
    return f"http://{host}.localhost"
PROJECT = os.getenv("COMPOSE_PROJECT", "deployment-hacohen")
STATE = os.path.join(REPO, "platform.state.yaml")
RECONCILE = os.path.join(REPO, "platform", "manager", "reconcile.py")
# apps/ holds layer 3 (installable); platform-base/ holds layers 1-2 (core, protected).
ROOTS = {"apps": 3, "platform-base": 12}
# One lifecycle op at a time: edits to platform.state.yaml + a reconcile render + the container
# apply must not interleave, or two clicks could corrupt the state file or race the compile.
_LIFECYCLE = threading.Lock()

# The catalog/install machinery is layer-1 MECHANISM and lives with the compiler, so the CLI
# (`bbox app install`) and this control plane run the same code — not two implementations of
# "install an app" that drift.
sys.path.insert(0, os.path.join(REPO, "platform", "manager"))
# ONE parser of a disposition. This module used to carry THREE inline copies (_dispo_of, the
# _catalog loop, and reconcile_once), and they disagreed with the compiler's `disposition()` on the
# shapes that matter:
#
#   entry                     reconcile (what RUNS)   app.py (what the UI SHOWED)
#   app absent from state     disabled                 ENABLED
#   {} (present, empty)       disabled                 ENABLED
#
# enabled_ids() only iterates apps present in state, so an app the compiler will never start was
# displayed as enabled in the apps screen — the control plane disagreeing with the thing it controls.
# reconcile is authoritative because it is what brings containers up.
#
# Imported in the same guarded block as the rest: a broken import must degrade the store, never kill
# the catalog screen. There is deliberately NO local fallback parser — a fallback is how the second
# copy got here in the first place.
try:
    import appinstall
    import catalog as catalog_mod
    from reconcile import disposition as _disposition
    from reconcile import base_url_env as _base_url_env
except Exception as _e:
    appinstall = catalog_mod = None
    _CATALOG_IMPORT_ERROR = str(_e)

    def _disposition(_entry):
        raise RuntimeError(f"reconcile.disposition unavailable: {_CATALOG_IMPORT_ERROR}")

    def _base_url_env(app_id):
        # the same one-line convention as reconcile.base_url_env; a launch URL must not die with
        # the catalog import
        return app_id.upper().replace("-", "_") + "_BASE_URL"
else:
    _CATALOG_IMPORT_ERROR = None

app = Flask(__name__, static_folder="static")

_SENTRY_DSN = os.getenv("SENTRY_DSN")
if _SENTRY_DSN:
    try:
        import sentry_sdk
        sentry_sdk.init(dsn=_SENTRY_DSN, traces_sample_rate=0.0)
    except Exception:
        pass


# ── manifests + state ─────────────────────────────────────────────────────────

def _load_manifests():
    """Every app.json under apps/ and platform-base/, tagged with its root + dir."""
    out = []
    for root in ROOTS:
        for path in sorted(glob.glob(os.path.join(REPO, root, "*", "app.json"))):
            try:
                m = json.load(open(path, encoding="utf-8"))
            except Exception as e:
                out.append({"id": os.path.basename(os.path.dirname(path)), "_broken": str(e),
                            "_root": root, "_dir": os.path.dirname(path)})
                continue
            m["_root"] = root
            m["_dir"] = os.path.dirname(path)
            out.append(m)
    return out


def _load_state():
    try:
        st = yaml.safe_load(open(STATE, encoding="utf-8")) or {}
    except Exception:
        st = {}
    return (st.get("apps") or {})


#: What a compose file declares is read ONCE, until the file changes. One /api/apps answer asked for
#: every app's services twice (the dependency pass, then the listing) and each time parsed the whole
#: file with the pure-Python YAML loader: 38 files, 370 KB, 2.9 s of every answer on the HP office
#: (measured 2026-10-09) — for a list of names that changes when somebody edits a compose file. The
#: apps screen asks every 5 s and its answers took 5 to 13: the screen stood as six grey cards.
_SERVICES = {}     # compose path -> ((mtime_ns, size), [service names])


def _services_of(manifest):
    """Service names an app declares in its compose (so we can find its containers).

    A manifest may legitimately declare no compose (e.g. a UI-only pseudo app) — `compose` is then
    absent or null, and the app simply has no containers of its own.
    """
    fname = manifest.get("compose")
    if not fname:
        return []
    path = os.path.join(manifest.get("_dir") or REPO, fname)
    try:
        st = os.stat(path)
        seen = _SERVICES.get(path)
        if not seen or seen[0] != (st.st_mtime_ns, st.st_size):
            with open(path, encoding="utf-8") as f:
                doc = yaml.safe_load(f) or {}
            seen = _SERVICES[path] = ((st.st_mtime_ns, st.st_size), list((doc.get("services") or {}).keys()))
        return list(seen[1])                 # the caller's own list: the remembered one is not handed out
    except Exception:
        return []


# ── live container state ────────────────────────────────────────────────────

#: The index is read by every /api/apps call (the screen polls every 5 s, several screens at once),
#: so it is cached briefly and fetched by ONE caller at a time. Measured 2026-09-29 on the 5 GiB
#: macOS engine under swap pressure: the old per-container read (docker-py `containers.list()`
#: without `sparse` = one inspect per container, ~45 of them, 60 s client timeout) took 62–67 s,
#: the console's 40 s proxy gave up with a 502, and the page read the error body as "no apps".
_CIDX_TTL = float(os.getenv("APP_MANAGEMENT_DOCKER_TTL", "4"))
_CIDX_TIMEOUT = int(os.getenv("APP_MANAGEMENT_DOCKER_TIMEOUT", "15"))
_CIDX = {"at": 0.0, "value": None}
_CIDX_LOCK = threading.Lock()
_HEALTH_RE = re.compile(r"\((healthy|unhealthy|health: starting)\)")


def _container_index():
    """{service_name: {status, health, exit_code, restart}} for every container in this project.

    ONE list call (`sparse=True` = the /containers/json answer, no per-container inspect), with the
    health read from the status line ("Up 2 hours (healthy)"). Only containers that are NOT running
    are inspected — they are the few whose exit code and restart policy matter (a finished one-shot
    job is not a dead service, see _app_runtime). A failed read keeps the last good index instead of
    replacing it with nothing: "docker did not answer this time" is not "no containers exist".
    """
    if docker_sdk is None:
        return None
    now = time.time()
    if _CIDX["value"] is not None and now - _CIDX["at"] < _CIDX_TTL:
        return _CIDX["value"]
    if not _CIDX_LOCK.acquire(timeout=_CIDX_TIMEOUT + 5):
        return _CIDX["value"]                       # somebody else is reading; answer with the last
    try:
        if _CIDX["value"] is not None and time.time() - _CIDX["at"] < _CIDX_TTL:
            return _CIDX["value"]
        client = docker_sdk.from_env(timeout=_CIDX_TIMEOUT)
        idx = {}
        for c in client.containers.list(all=True, sparse=True,
                                        filters={"label": f"com.docker.compose.project={PROJECT}"}):
            a = c.attrs or {}
            labels = a.get("Labels") or {}
            svc = labels.get("com.docker.compose.service")
            if not svc:
                continue
            status = a.get("State") or ""                # running | exited | created | restarting …
            m = _HEALTH_RE.search(a.get("Status") or "")
            health = {"healthy": "healthy", "unhealthy": "unhealthy",
                      "health: starting": "starting"}.get(m.group(1)) if m else None
            exit_code, policy = None, ""
            if status != "running":
                try:
                    full = client.api.inspect_container(a.get("Id"))
                    exit_code = (full.get("State") or {}).get("ExitCode")
                    policy = ((full.get("HostConfig") or {}).get("RestartPolicy") or {}).get("Name", "")
                except Exception:
                    pass
            idx[svc] = {"status": status, "health": health, "exit_code": exit_code,
                        "restart": policy}
        _CIDX.update(at=time.time(), value=idx)
        return idx
    except Exception:
        return _CIDX["value"]
    finally:
        _CIDX_LOCK.release()


# ── conditions: health as a set of claims, not one boolean ─────────────────────
# `health` collapsed everything into one word, so "the probe has not run yet", "a dependency is
# down" and "this app is broken" were indistinguishable — and a caller could not tell whether what
# it was reading reflected its own last edit.
#
# Kubernetes' shape solves all three and is worth copying exactly:
#   type    an open set, so a new condition is additive and old readers ignore it
#   status  True / False / **Unknown** — "not yet determined" is expressible, and the API
#           convention is explicit that a missing condition means Unknown, never False
#   reason  a machine-readable CamelCase token; message is for humans
#   observedGeneration  answers "has my change been applied yet" without polling heuristics
#
# The taxonomy on top is Home Assistant's, and it is the part that matters operationally: most
# systems collapse failure into "error", then either retry forever on an expired credential or
# page someone about a transient blip.
#   NotReady   — transient. Retry quietly. Show it, do not alarm.
#   AuthFailed — a human must re-authorise. Retrying is pointless and hides the problem.
#   Error      — permanent. Stop.
# Six apps here hold OAuth grants that expire; without AuthFailed they would retry forever and
# report healthy-ish while doing nothing.
COND_NOT_READY = "NotReady"
COND_AUTH_FAILED = "AuthFailed"
COND_ERROR = "Error"

# A probe answering 401/403 is not "unhealthy", it is "nobody can fix this by waiting".
_AUTH_STATUSES = (401, 403)


# The credential plane already knows which grants have lapsed; asking it is the only honest way to
# emit AuthFailed. Deriving it from container health would be a guess — a container whose token
# expired is perfectly healthy by every probe it runs.
CONNECTIONS_URL = os.getenv("CONNECTIONS_INTERNAL_URL", "http://connections:8990")
_AUTH_CACHE = {"at": 0.0, "by_service": {}}
_AUTH_TTL = 20.0        # the catalog polls every 5s; re-asking that often would be rude and useless


def _auth_blockers():
    """{service: [connection titles]} for required credentials that a human must go re-authorise.

    Only `missing`/`needs_action` on a REQUIRED connection counts. An optional one that is unset is
    a choice, not a fault, and reporting it would train the operator to ignore the badge.
    """
    now = time.time()
    if now - _AUTH_CACHE["at"] < _AUTH_TTL:
        return _AUTH_CACHE["by_service"]
    out = {}
    try:
        import urllib.request
        with urllib.request.urlopen(CONNECTIONS_URL + "/api/connections", timeout=3) as r:
            if r.status in _AUTH_STATUSES:
                raise RuntimeError("connections refused us")   # our own creds, not the app's
            rows = (json.loads(r.read().decode("utf-8")) or {}).get("connections") or []
        for row in rows:
            if not row.get("required") or row.get("status") not in ("missing", "needs_action"):
                continue
            label = row.get("title_he") or row.get("title") or row.get("id")
            for svc in (row.get("consumers") or []):
                out.setdefault(svc, [])
                if label not in out[svc]:
                    out[svc].append(label)
    except Exception:
        # connections being down is ITS problem, surfaced on ITS card. It must not turn every other
        # app's Ready condition into a lie, so we simply report no auth blockers.
        out = {}
    _AUTH_CACHE.update(at=now, by_service=out)
    return out


# lastTransitionTime is only meaningful if it marks the moment the STATUS changed — restamping it
# on every poll would make every condition look one second old forever and destroy the one thing it
# is for: knowing how long something has been stuck.
_TRANSITIONS = {}                      # (app_id, cond_type) -> (status, iso_ts, monotonic_ts)

# How long an app may sit not-Ready before we stop calling it "still starting". Deployments that
# never converge are the norm, not the exception, and without a deadline they look like progress
# forever. Same idea as a Deployment's progressDeadlineSeconds; n8n's own migrations take minutes,
# so the default is generous and an app can raise it in its manifest.
DEFAULT_PROGRESS_DEADLINE = 600


def _iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def _stamp(aid, cond):
    """Attach lastTransitionTime, holding the previous stamp while the status is unchanged."""
    key = (aid, cond["type"])
    prev = _TRANSITIONS.get(key)
    if prev and prev[0] == cond["status"]:
        cond["lastTransitionTime"], mono = prev[1], prev[2]
    else:
        now = time.time()
        cond["lastTransitionTime"], mono = _iso(now), time.monotonic()
        _TRANSITIONS[key] = (cond["status"], cond["lastTransitionTime"], mono)
    cond["_since"] = time.monotonic() - mono          # seconds in this status; stripped before JSON
    return cond


def _generation():
    """The rendered-config generation these conditions were observed against.

    The compiler archives .generated/generations/NNNN on every render, so the highest number IS the
    current config. Reporting it lets a caller answer "has my edit been applied yet" by comparing,
    instead of polling and guessing — which is the whole point of observedGeneration.
    """
    d = os.path.join(REPO, ".generated", "generations")
    try:
        ns = [int(x) for x in os.listdir(d) if x.isdigit()]
        return max(ns) if ns else 0
    except Exception:
        return 0


def _conditions(*a, **kw):
    """The condition list for one app. Order is Resolved -> Installed -> Started -> Ready."""
    out = _build_conditions(*a, **kw)
    for cond in out:
        cond.pop('_since', None)      # bookkeeping for the deadline check, not API
    return out


def _build_conditions(aid, rt, dispo, gen, deps_unmet, auth_missing=(), deadline=None):
    def c(t, status, reason, message=""):
        return _stamp(aid, {"type": t, "status": status, "reason": reason, "message": message,
                            "observedGeneration": gen})

    out = []
    unknown = rt.get("running") is None          # no docker view at all

    # Resolved: the compiler placed this app in the rendered config.
    out.append(c("Resolved", "True", "InCatalog"))

    if dispo == "archived":
        out.append(c("Installed", "True", "Archived", "images removed, data kept"))
        out.append(c("Started", "False", "Archived"))
        out.append(c("Ready", "False", "Archived", "unarchive to run"))
        return out

    installed = bool(rt.get("present")) or dispo == "enabled"
    out.append(c("Installed", "True" if installed else "False",
                 "ContainersPresent" if installed else "NotInstalled"))

    if unknown:
        # Deliberately Unknown rather than False: we could not look, which is not the same as
        # having looked and found nothing.
        out.append(c("Started", "Unknown", "DockerUnavailable"))
        out.append(c("Ready", "Unknown", "DockerUnavailable"))
        return out

    total, running = rt.get("total") or 0, rt.get("running") or 0
    if dispo != "enabled":
        out.append(c("Started", "False", "Disabled", "switched off by the operator"))
        out.append(c("Ready", "False", "Disabled"))
        return out

    if total and running == total:
        out.append(c("Started", "True", "AllContainersRunning", f"{running}/{total}"))
    elif running:
        out.append(c("Started", "False", "SomeContainersDown", f"{running}/{total}"))
    else:
        out.append(c("Started", "False", "NoContainersRunning", f"0/{total}"))

    h = rt.get("health")
    # Checked first and unconditionally: an expired grant outranks every other Ready reason,
    # because it is the only one waiting will never resolve. Reporting "starting" over it would
    # send the operator to wait for something that is never coming.
    if auth_missing:
        out.append(c("Ready", "False", COND_AUTH_FAILED,
                     "נדרש חיבור מחדש: " + ", ".join(sorted(auth_missing))))
    elif deps_unmet:
        out.append(c("Ready", "False", COND_NOT_READY,
                     "waiting on " + ", ".join(sorted(deps_unmet))))
    elif h == "starting":
        out.append(c("Ready", "False", COND_NOT_READY, "containers still starting"))
    elif h == "unhealthy":
        out.append(c("Ready", "False", COND_ERROR, "a container reports unhealthy"))
    elif running == total and h in ("healthy", "none"):
        # `total == 0` is included deliberately: an app that owns no container (kind: ui or
        # blueprint) is Ready once it is enabled — its installation IS its content, and there is
        # nothing left that could still be coming up.
        out.append(c("Ready", "True", "AllChecksPassed" if total else "NoServicesToRun"))
    else:
        out.append(c("Ready", "False", COND_NOT_READY, f"{running}/{total} running"))

    # A NotReady that has outlived its deadline is not still starting — it is stuck, and saying
    # otherwise is how a stack sits broken for an hour while the UI shows a hopeful spinner.
    ready = out[-1]
    limit = deadline or DEFAULT_PROGRESS_DEADLINE
    if ready["reason"] == COND_NOT_READY and ready.pop("_since", 0) > limit:
        ready.update(reason="ProgressDeadlineExceeded",
                     message=f"{ready['message']} — לא הגיעה למצב תקין תוך {limit}s")
    return out


def _unmet_deps(m, by_id, runtime_of):
    """Hard-used capabilities whose provider is not Ready — the reason an app is NotReady."""
    unmet = set()
    HARD = {"requires", "requisite", "binds_to"}
    for u in (m.get("use") or []):
        if not isinstance(u, dict) or u.get("strength", "requires") not in HARD:
            continue
        cap = u.get("capability")
        for other, om in by_id.items():
            caps = {(c if isinstance(c, str) else c.get("name"))
                    for c in (om.get("capabilities") or [])}
            if cap in caps:
                r = runtime_of(other)
                if r and r.get("total") and (r.get("running") or 0) < r["total"]:
                    unmet.add(f"{cap} ({other})")
    return unmet


def _app_runtime(services, cidx, enabled=True):
    """Aggregate an app's services into a single (state, running, total, health).

    `enabled` matters only for compose-less apps: with no containers to observe, the DISPOSITION
    is the only truth about whether the app is doing anything."""""
    total = len(services)
    if cidx is None:
        return {"state": "unknown", "running": None, "total": total, "health": "unknown",
                "present": None}
    present = [cidx[s] for s in services if s in cidx]

    # A migration/bootstrap container that exited 0 has SUCCEEDED. Counting only `status ==
    # running` made glitchtip permanently 4/5 — its `glitchtip-migrate` job runs once, exits 0 and
    # stays exited by design — so the app reported NotReady forever and the operator had a
    # never-clearing amber dot with nothing to fix. The exit code alone is not enough to tell a
    # finished job from a dead service; `restart: no` is what says the author meant it to end.
    def satisfied(c):
        return c["status"] == "running" or (
            c["status"] == "exited" and c.get("exit_code") == 0
            and (c.get("restart") or "no") == "no")

    running = sum(1 for c in present if satisfied(c))
    healths = [c["health"] for c in present if c["status"] == "running"]
    if total == 0:
        # An app with no compose (kind: ui / blueprint) has nothing that can be down. Falling
        # through here reported bina-ui as NotReady "0/0 running" — permanently, and for an app
        # whose installation IS its content.
        #
        # But "nothing can be down" is not the same as "running". A DISABLED blueprint app
        # (google-workspace-agent, whose content is n8n workflows that are removed on disable)
        # reported installed=False enabled=False state=running — three fields, one of them a lie.
        # With no containers to observe, the disposition IS the state.
        return {"state": "running" if enabled else "stopped",
                "running": 0, "total": 0, "health": "none", "present": len(present)}
    if running == 0:
        state, health = "stopped", "none"
    elif running < total:
        state, health = "partial", "degraded"
    else:
        state = "running"
        if any(h == "unhealthy" for h in healths):
            health = "unhealthy"
        elif any(h == "starting" for h in healths):
            health = "starting"
        else:
            health = "healthy"
    # `present` (containers that EXIST, running or not) is what distinguishes a DISABLED app from
    # an UNINSTALLED one — see the catalog's `installed`.
    return {"state": state, "running": running, "total": total, "health": health,
            "present": len(present)}


def _catalog():
    state = _load_state()
    cidx = _container_index()
    _gen = _generation()
    _auth = _auth_blockers()
    _mans = _load_manifests()
    _by_id = {x.get("id"): x for x in _mans if x.get("id")}
    # runtime is computed once per app and reused when resolving other apps' dependencies, so a
    # catalog call stays one docker query rather than N-squared lookups.
    _enabled_ids = {aid for aid in _by_id if _disposition(state.get(aid)) == "enabled"}
    _rt_cache = {aid: _app_runtime(_services_of(x), cidx, aid in _enabled_ids)
                 for aid, x in _by_id.items()}
    apps = []
    for m in _mans:
        aid = m.get("id")
        root = m.get("_root")
        core = root == "platform-base"          # layer 1-2 = core platform, protected
        # DISPOSITION, not a boolean. `archived` means images/containers dropped to reclaim disk
        # while volumes and the catalog tile are KEPT — Android 15's app archiving, which exists
        # precisely because "uninstall to free space" throws away the data people care about.
        entry = state.get(aid) or {}
        dispo = _disposition(entry)
        enabled = dispo == "enabled"
        if m.get("_broken"):
            apps.append({"id": aid, "broken": m["_broken"], "core": core,
                         "enabled": enabled, "layer": None})
            continue
        routing = m.get("routing") or [{}]
        # the UI lives on the routing entry that declares a module (mail's UI is mailview, not the
        # inbox API on routing[0]); fall back to the first entry for apps with no module.
        # The UI route is the one that declares a `module` — an app's console tile. Requiring
        # module.id was wrong: the id is OPTIONAL and defaults to the app id three lines below
        # (`module.get("id") or aid`), so any app whose module omits it fell through to
        # routing[0]. For supabase that is KONG, the API gateway, which has no page at "/" — so
        # Apps > Supabase > Open landed on "no Route matched with those values".
        # Presence of a module is the declaration; its id is a detail.
        r_ui = next((r for r in routing if r.get("module")), routing[0])
        module = r_ui.get("module") or {}
        # launch target: an embedded app opens inside the console shell (#/m/<tile-id>); anything
        # else opens its own host in a new tab. This is what lets the apps screen also be a launcher,
        # so the console's separate #/m/apps grid is redundant.
        host = r_ui.get("host")
        launch = None
        if host:
            # `module.url` lets an app declare its own landing path. The schema always allowed it;
            # the console ignored it and always sent people to "/". That is wrong for any app whose
            # UI does not live at the root — browser42 serves noVNC at /view/ and only redirects
            # from "/", which is exactly the redirect a browser can cache. Honouring the declaration
            # keeps the knowledge in the app, where it belongs, and means the console never has to
            # know what browser42 is.
            _path = (module.get("url") or "").strip()
            # [2026-09-02] THE PUBLIC HOST IS THE DEPLOYMENT'S, NOT `.localhost`. This built
            # `http://<host>.localhost` unconditionally, so on a real domain Apps > Supabase > Open
            # sent the browser to a host that only exists on a laptop. The routing entry already
            # declares where its UI lives (`sso.base_url_env`, resolved by reconcile from
            # DEPLOYMENT_DOMAIN into .env); this container mounts the repo, so it reads the same
            # answer. Order: the entry's own base-url env → DEPLOYMENT_DOMAIN → .localhost.
            _origin = _public_origin(aid, host, (r_ui.get("sso") or {}).get("base_url_env"))
            if _path and not _path.startswith(("http://", "https://")):
                _url = f"{_origin}/{_path.lstrip('/')}"
            elif _path:
                _url = _path
            else:
                _url = _origin
            launch = {"url": _url,
                      "embed": bool(module.get("embed")),
                      "module": module.get("id") or aid}
        services = _services_of(m)
        rt = _app_runtime(services, cidx, enabled)
        _rt_cache[aid] = rt
        title = m.get("title") or {}
        summary = m.get("summary") or {}
        apps.append({
            "id": aid,
            "name": title.get("he") or title.get("en") or aid,
            "name_en": title.get("en") or aid,
            "summary": summary.get("he") or summary.get("en") or "",
            "layer": m.get("layer"),
            "kind": m.get("kind"),
            "version": m.get("version"),
            "icon": module.get("icon") or "app",
            "core": core,
            "launch": launch,
            "enabled": enabled,
            # INSTALLED and ENABLED are different questions, and conflating them made "disable"
            # look like "uninstall": the app vanished from My apps into the store even though its
            # containers were still there, stopped. An app is installed if its containers exist
            # (whatever their state) or it is enabled — the latter covers kind: blueprint apps,
            # which own no container and whose installation IS their imported workflows.
            "conditions": _conditions(
                aid, rt, dispo, _gen,
                _unmet_deps(m, _by_id, lambda o: _rt_cache.get(o)),
                sorted({t for sv in services for t in _auth.get(sv, [])}),
                m.get("progress_deadline_seconds")),
            "state_desired": dispo,
            "archived": dispo == "archived",
            "state_by": entry.get("by"),
            # An archived app is still INSTALLED — that is the whole point: its data and its tile
            # survive, only the images and containers are gone.
            "installed": bool(enabled) or bool(rt.get("present")) or dispo == "archived",
            "services": services,
            "on_uninstall": (m.get("data") or {}).get("on_uninstall", "keep"),
            "volumes": (m.get("data") or {}).get("volumes") or [],
            **rt,
        })
    apps.sort(key=lambda a: (a["core"], not a["enabled"], a["id"]))
    return apps


# ── lifecycle (enable / disable + real apply) ───────────────────────────────
#
# One change is, in order (`_apply`):
#   1) the desired state (platform.state.yaml) — written by the compiler, the file's one writer,
#   2) the compile (`reconcile.py render`) — so a later `bbox run` agrees with what was done here,
#   3) the containers — started or stopped over the socket when they exist; CREATED through
#      scripts/dc when they do not (the repo is mounted at its host path so compose resolves the
#      same build contexts and bind sources the CLI does),
#   4) on enable, the rest of the bring-up `bbox run` gives an app: its `prepare` hook before (3),
#      a wait until its containers answer, sign-in for a host it gates, then its `onboard` hook,
#   5) its automations (n8n blueprints) in or out.
# Nothing here needs a shell on the machine — which is what lets a linked office place an app on
# this one through this API alone.


def _manifest(aid):
    for m in _load_manifests():
        if m.get("id") == aid:
            return m
    return None


def _set_disposition(aid, dispo, by="user"):
    """Write apps.<id> — delegated to reconcile.set_disposition(), the one writer.

    This used to carry its own regex copy. The compiler owns the format of platform.state.yaml: it
    is the file's only reader (`disposition()`), and a second writer here is how the two shapes
    `{ enabled: bool }` and `{ state: ..., by: ... }` came to be written by different surfaces.
    Shelled rather than imported because reconcile.py lives at /repo in this container while the
    service runs from /app — the same reason _render() shells out.

    Returns True when the file says it now (written, or already there), False when it could not be
    written. Callers MUST check: a failed desired-state write that still performs the container
    action leaves the two out of step.
    """
    # `--create`: an app that has a manifest and no line in the state file yet — every app the day
    # its folder arrives — gets its line here. Without it the first "install" of such an app wrote
    # nothing, compiled nothing, and then failed at compose with "no such service" (found
    # 2026-10-05 installing a new app from this API). Every caller has already resolved `aid` to a
    # manifest, so this can never invent an app.
    r = subprocess.run(["python3", RECONCILE, "set-state", "--app", aid, "--state", dispo,
                        "--by", by, "--create"], cwd=REPO, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        app.logger.warning("set-state %s -> %s failed: %s", aid, dispo,
                           (r.stderr or r.stdout or "").strip()[:200])
        return False
    return True


def _render():
    """Recompile .generated/* from the manifests + state. Pure python; raises on failure."""
    r = subprocess.run(["python3", RECONCILE, "render"], cwd=REPO,
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "reconcile render failed").strip()[:400])
    return (r.stdout or "").strip().splitlines()[-1:]


def _app_containers(services):
    """docker-py containers for an app's services (running or stopped)."""
    client = docker_sdk.from_env()
    out = []
    for c in client.containers.list(all=True,
                                    filters={"label": f"com.docker.compose.project={PROJECT}"}):
        if c.labels.get("com.docker.compose.service") in services:
            out.append(c)
    return out


# The compose interpreter that lived here is gone: _host_repo, _env_map, _interp,
# _routing_labels and _create_service — ~155 lines re-deriving docker-compose semantics in
# docker-py, necessarily a subset of the schema, silently dropping any field it did not
# translate. _install now shells to scripts/dc, the one canonical invocation, which also puts
# the control plane under gate G7. _host_repo went with them: the repo is mounted at its host
# path now (BBOX_REPO_HOST), so there is no container-vs-daemon path to translate.


def _install(aid):
    """Create the app's containers — through scripts/dc, the ONE compose invocation.

    This used to translate compose semantics into docker-py calls by hand: container_name, image,
    environment (list and mapping forms), volumes (bind vs named, relative-path resolution, modes),
    labels, routing labels, ports, command, entrypoint, user, cap_add. A second implementation of
    what compose already does, and necessarily a SUBSET — a field it did not translate was dropped
    silently rather than refused. Its own comment recorded the cost: dropping `command:` cost
    portainer its `--admin-password-file`, so a gallery-installed portainer booted into the
    unauthenticated "create initial admin" wizard.

    appinstall.start_services() had it right and said why — "the same one `bbox run` uses, so an
    installed app is started exactly like every other app". Doing the same here also brings the
    control plane under gate G7; the docker-py path was outside it entirely.

    Two things make this correct rather than merely shorter, and both were learned by breaking it:

    COMPOSE_PROJECT_NAME is mandatory. compose derives the project from --project-directory's
    basename; from here that would be the mount point, not the clone dir, so compose would find
    none of the running containers and build a PARALLEL project (repo_* networks and volumes,
    container_name collisions) — the "forks a second project" failure in running-on-wsl.md.
    PROJECT comes from COMPOSE_PROJECT, which compose itself interpolated in, so this propagates
    the one authority rather than guessing at it.

    Same-path mounting is what makes bind sources resolvable at all: see BBOX_REPO_HOST in
    scripts/lib.sh and the note in this app's own docker-compose.yml.

    Returns (created, errors) ALWAYS. It used to return a jsonify() tuple on the platform-base
    guard and a 2-tuple otherwise, while its only caller unpacks two values — so that guard would
    have raised ValueError instead of refusing. The guard belongs to the caller and now lives there.
    """
    services = _services_of(_manifest(aid) or {})
    if not services:
        return [], []
    have = {c.labels.get("com.docker.compose.service") for c in _app_containers(services)}
    want = [s for s in services if s not in have]
    if not want:
        return [], []
    failed = _compose_up(want)
    return ([], [failed]) if failed else (want, [])


def _compose_up(services):
    """`scripts/dc up -d <services>` — the one compose invocation. None, or what went wrong.

    Compose creates what is missing and recreates what was compiled differently since it started,
    and leaves the rest alone — so the same call installs an app and brings a running one in line."""
    r = subprocess.run(["bash", "scripts/dc", "up", "-d", *services],
                       cwd=REPO, capture_output=True, text=True, timeout=1800,
                       encoding="utf-8", errors="replace",
                       env={**os.environ, "COMPOSE_PROJECT_NAME": PROJECT})
    if r.returncode == 0:
        return None
    return (f"compose up failed ({r.returncode}): "
            + ((r.stderr or r.stdout or "").strip()[-400:] or "no output"))


def _signin_refresh():
    """Make sign-in serve every host that was just compiled — the sign-in app's own verb.

    A host that is declared and compiled is not yet a host a person can open: the sign-in layer
    keeps the set it loaded, and a new one answers 404 there until that app's `refresh` hook has
    run (its header tells the whole story). `bbox run` runs it; this plane has to as well, or an app
    switched on from the apps screen — or by a linked office — is up, healthy, and unreachable.
    Reached by the ROLE the app plays (`forward-auth`), never by its name."""
    state = _load_state()
    for m in _load_manifests():
        if _disposition(state.get(m.get("id"))) != "enabled":
            continue
        if any((c or {}).get("name") == "forward-auth" for c in m.get("capabilities") or []):
            # Longer than the sum of the hook's own bounds, which it states: three minutes for a
            # server that has only just started, fifteen for a sentinel asked to apply every
            # blueprint again, a minute and a half for the outpost to learn after that, four for the
            # server it may then restart (1410 s) — its slow path; the usual one is a few seconds.
            # A shorter bound here killed it mid-wait on the first real install (hp-laptop,
            # 2026-10-05: 420 s) and left the new host unserved while the job said it had finished.
            return _run_hook(m, "refresh", 1560)
    return None


def _hook_said(r):
    """One line for what a hook did: where it got to, or — when it failed — WHY.

    A hook writes its progress on stdout and its reason on stderr. Reporting the last stdout line
    of a FAILED hook named the last thing that had worked: drive's automations were refused on
    hp-laptop for a mismatched N8N_ENCRYPTION_KEY, and every converge reported the error as
    "PostgREST default privileges present" (2026-10-05). So a failure is its stderr: the line that
    says FATAL or ERROR with the line that finishes its sentence, else the last one."""
    out = [l.strip() for l in (r.stdout or "").splitlines() if l.strip()]
    if r.returncode == 0:
        return out[-1] if out else ""
    err = [l.strip() for l in (r.stderr or "").splitlines() if l.strip()]
    loud = next((i for i, l in enumerate(err) if "FATAL" in l or "ERROR" in l), None)
    if loud is not None:
        more = err[loud + 1] if loud + 1 < len(err) and not err[loud + 1].startswith("[") else ""
        return f"{err[loud]} {more}".strip()[:400]
    return (err[-1] if err else out[-1] if out else f"exit {r.returncode}")[:400]


def _workflow_hooks():
    """The hooks directory of the app that PROVIDES `workflow` — resolved through the compiler, never
    named. The automation engine is an installable app since core-001 (apps/n8n), and this control
    plane is layer 1: naming it would be the inversion G9 forbids, and would also be wrong on an
    office that runs no engine at all (agents and control only). The compiler answers with the ONE
    enabled provider (it refuses an ambiguous answer), and its directory is wherever the catalog
    found the manifest. None when no engine is enabled — the callers say so rather than guess."""
    r = subprocess.run(["python3", RECONCILE, "capability-provider", "--capability", "workflow"],
                       cwd=REPO, capture_output=True, text=True, timeout=60)
    pid = (r.stdout or "").strip().splitlines()[-1].strip() if r.returncode == 0 and (r.stdout or "").strip() else ""
    if not pid:
        return None
    for root in ("apps", "platform-base"):
        d = os.path.join(REPO, root, pid, "hooks")
        if os.path.isdir(d):
            return d
    return None


def _blueprint_apply(aid, install):
    """Import (or remove) an app's n8n workflows when it is enabled (or disabled).

    The manifest contract is `blueprints.n8n`: "imported on enable and removed on disable". Without
    this, enabling an automation-only app (kind: blueprint, no containers) flipped
    platform.state.yaml and did nothing observable — the app read as installed while n8n held none
    of its workflows. Delegates to the same hooks the CLI uses so there is exactly one
    implementation of import/remove — the hooks of whichever app provides `workflow` here.

    Best-effort by design: a failure here must not strand the lifecycle call that already
    succeeded, so it is reported, not raised. No engine enabled is reported the same way: an app
    that REQUIRES workflow never reaches this point without one (the compiler pulls the provider in
    first), so the case is an app that only wants automations, on an office that runs none.
    """
    m = _manifest(aid) or {}
    if not ((m.get("blueprints") or {}).get("n8n") or "").strip():
        return None
    hook = "push" if install else "unpush"
    hooks = _workflow_hooks()
    if not hooks:
        return {"hook": hook, "ok": False,
                "detail": "no enabled app provides `workflow` — the automations have nowhere to go"}
    try:
        r = subprocess.run(
            # REPO, never a literal "/repo": the repo is mounted at its HOST path now (so compose
            # can resolve bind sources — see this app's docker-compose.yml), and a baked-in /repo
            # simply does not exist any more. It failed silently too: the hook is best-effort, so
            # the caller recorded a blueprint "applied" that had never run.
            ["bash", os.path.join(hooks, hook), "--app", aid],
            cwd=REPO, capture_output=True, text=True, timeout=600,
            encoding="utf-8", errors="replace")
        return {"hook": hook, "ok": r.returncode == 0, "detail": _hook_said(r)}
    except Exception as e:
        return {"hook": hook, "ok": False, "detail": str(e)}


def _blueprint_present(aid):
    """Does the n8n INSTANCE hold this app's declared workflows? True / False / None (cannot tell).

    None is not False, and conflating them would be the bug this is here to fix: "n8n is down" must
    never be read as "the workflows are missing", because the repair for missing is to import, and
    importing against a half-started instance is how you get a partial set.
    """
    hooks = _workflow_hooks()
    if not hooks:
        return None                                       # no engine enabled: nobody can tell
    r = subprocess.run(["bash", os.path.join(hooks, "present"), "--app", aid],
                       cwd=REPO, capture_output=True, text=True, timeout=120,
                       encoding="utf-8", errors="replace")
    return {0: True, 1: False}.get(r.returncode)          # 2 (or anything else) -> None


def reconcile_once():
    """Converge ACTUAL state to DESIRED state for every enabled app. Returns a report.

    The control plane was entirely transition-driven: every mutation hung off an HTTP POST, so
    `_blueprint_apply` fired on enable/disable and never again. That is fine until actual state
    changes underneath desired state — and it does. `bbox reset` wipes the volumes while
    platform.state.yaml still says `enabled`, so n8n comes back EMPTY, every app reads as installed,
    and nothing anywhere notices: no transition happened, so no handler ran. Measured: 82 workflows
    to 0, with `bbox status` still printing "blueprint clean" because that check only ever compared
    git to git.

    A control plane converges desired to actual. This is that loop, made explicit and callable
    rather than left implicit in whoever last clicked something.

    Deliberately conservative — it only ADDS what desired state says should exist:
      * containers declared but absent  -> compose up (via _install)
      * blueprint declared but missing from the instance -> import (via _blueprint_apply)
    It never removes or deactivates. Convergence that deletes needs a much stronger definition of
    "should not exist" than "I did not see it", and n8n's own push has the same rule.
    """
    report = {"checked": [], "converged": [], "skipped": [], "errors": []}
    state = _load_state()
    for m in _load_manifests():
        aid = m.get("id")
        if not aid or m.get("_broken"):
            continue
        entry = state.get(aid)
        # Only enabled apps. A disabled or archived app being "missing" is the desired state.
        dispo = _disposition(entry)   # third copy — same one parser
        if dispo != "enabled":
            continue
        report["checked"].append(aid)

        services = _services_of(m)
        if services:
            have = {c.labels.get("com.docker.compose.service") for c in _app_containers(services)}
            if have != set(services) and m.get("_root") != "platform-base":
                created, errs = _install(aid)
                if created:
                    report["converged"].append({"app": aid, "action": "containers", "created": created})
                report["errors"] += [{"app": aid, "error": e} for e in errs]

        if ((m.get("blueprints") or {}).get("n8n") or "").strip():
            present = _blueprint_present(aid)
            if present is False:
                r = _blueprint_apply(aid, True) or {}
                # VERIFY, do not assume. Reporting "converged" off the fact that we called
                # something is how a control plane starts lying: the first version of this recorded
                # a successful blueprint apply while the hook had failed on a stale path and
                # imported nothing. Re-ask the same question that found the drift.
                if r.get("ok") and _blueprint_present(aid) is True:
                    report["converged"].append({"app": aid, "action": "blueprint", "detail": r.get("detail")})
                else:
                    report["errors"].append({"app": aid, "action": "blueprint",
                                             "error": r.get("detail") or "apply did not restore the blueprint"})
            elif present is None:
                report["skipped"].append({"app": aid, "why": "blueprint presence undeterminable"})
    return report


@app.post("/api/reconcile")
def api_reconcile():
    """Converge the estate. Safe to call repeatedly; a converged estate reports nothing done."""
    if request.headers.get(OFFICE_HEADER):
        # A request that crossed a link cannot write this office's own state (§9 of the pairing
        # contract), and converging IS writing it: every enabled app is brought in line and its
        # containers recreated. The refusal `api_apply` and `api_remote_put` already answer with.
        return jsonify(error="a linked office does not converge this office"), 403
    with _LIFECYCLE:
        try:
            rep = reconcile_once()
        except Exception as e:                       # never let a converge attempt kill the plane
            return jsonify(ok=False, error=str(e)), 500
    return jsonify(ok=not rep["errors"], **rep), (200 if not rep["errors"] else 500)


def _run_hook(m, verb, timeout):
    """Run `<app dir>/hooks/<verb>` when the app ships one. None when it does not.

    The same files `bbox run` and `bbox <app> <verb>` run — an app's bring-up is the app's own
    business (`prepare` before its containers start, `onboard` once they answer), and this plane
    only decides WHEN. Best-effort like every caller of these hooks: a failed bootstrap is reported
    with its last words, never swallowed and never fatal to the lifecycle that called it."""
    hook = os.path.join(m.get("_dir", ""), "hooks", verb)
    if not os.path.exists(hook):
        return None
    if not os.access(hook, os.X_OK):                 # the rule `run_app_hooks` has: said, not skipped
        return {"ran": False, "rc": 126, "out": f"hooks/{verb} is there and is not executable — not run"}
    try:
        r = subprocess.run(["bash", hook], cwd=REPO, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace",
                           env={**os.environ, "APP_ID": m.get("id", ""), "COMPOSE_PROJECT_NAME": PROJECT})
        return {"ran": True, "rc": r.returncode, "out": (r.stdout or r.stderr or "").strip()[-400:]}
    except Exception as e:
        return {"ran": True, "rc": -1, "out": str(e)[:200]}


# ── the two other planes a lifecycle change may need ──────────────────────────────────────────
#
# An app's DATA is data-management's (the one owner of export / import and of the archives), and a
# LINKED OFFICE is reached through the console's door (`/a/<alias>.<office>/` — the one place that
# knows how this office reaches another and as whom). This plane drives both and restates neither:
# placing an app on another office, or bringing one here with its data, is a sequence of calls any
# operator could make by hand, in the one order that never leaves an app half moved.
DATA_URL = os.getenv("DATA_MANAGEMENT_URL", "http://data-management:8080").rstrip("/")
CONSOLE_URL = os.getenv("CONSOLE_INTERNAL_URL", "http://console:8000").rstrip("/")
OFFICE_HEADER = "X-DGO-Office"      # written by the link's door: the office a request came from
_OFFICE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_ARCHIVE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,150}$")


def _call(method, url, body=None, timeout=60):
    """One JSON call to another plane. (status, payload); status 0 means nobody answered."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}
    except (OSError, ValueError) as e:
        return 0, {"error": str(e)}


def _peer(office, path=""):
    """A linked office's app-management, through this office's console door."""
    return f"{CONSOLE_URL}/a/app-management.{office}/api/apps{path}"


def _data_job(verb, **query):
    """Run one data-management job (export / pull / import) to its end. (ok, job) — the job's `log`
    is the tail of what it said, and on a failure that tail IS the reason."""
    status, started = _call("POST", f"{DATA_URL}/api/{verb}?{urllib.parse.urlencode(query)}")
    if status != 200 or not started.get("job"):
        why = started.get("detail") or started.get("error") or f"HTTP {status}"
        if status == 0:
            why = ("this office's data-management did not answer — it carries an app's data in and "
                   f"out, and has to be switched on ({why})")
        return False, {"log": [str(why)]}
    deadline = time.time() + 6 * 3600
    while time.time() < deadline:
        time.sleep(2)
        status, job = _call("GET", f"{DATA_URL}/api/jobs/{started['job']}?tail=12")
        if status == 404:
            return False, {"log": ["data-management restarted and no longer knows the job"]}
        if status == 200 and job.get("state") in ("done", "failed"):
            return job["state"] == "done", job
    return False, {"log": [f"the {verb} did not finish in six hours"]}


def _said(job):
    return " · ".join(str(x) for x in (job.get("log") or [])[-4:])[:600]


def _held_volumes(m):
    """The app's declared volumes that already EXIST here — data this office holds for the app."""
    client = docker_sdk.from_env()
    held = []
    for v in (m.get("data") or {}).get("volumes") or []:
        name = v if isinstance(v, str) else (v or {}).get("name")
        try:
            client.volumes.get(f"{PROJECT}_{name}")
            held.append(name)
        except docker_sdk.errors.NotFound:
            pass
    return held


def _carry_in(aid, src):
    """The app's data, from the office that exported it: fetched over the link, then restored into
    the instance that has just come up here. None when it arrived whole, else the reason."""
    ok, pulled = _data_job("pull", office=src["office"], name=src["archive"])
    if not ok:
        return f"the app's data could not be fetched from {src['office']}: {_said(pulled)}"
    ok, restored = _data_job("import", path=pulled["out"], app=aid)
    if not ok:
        return f"the app's data arrived and could not be restored: {_said(restored)}"
    return None


def _wait_ready(services, seconds):
    """Wait until the app's own containers answer — by the ONE definition of that (`_app_runtime`)."""
    deadline = time.time() + seconds
    _CIDX["at"] = 0.0                # an index read before this change began says nothing about it
    while True:
        rt = _app_runtime(services, _container_index(), True)
        if not services or (rt["state"] == "running" and rt["health"] == "healthy"):
            return True
        if time.time() >= deadline:
            return False
        time.sleep(3)


def _apply(aid, m, enable, step=lambda _name: None, patience=-1, restore=None):
    """One lifecycle change, start to finish. Returns (payload, http status).

    ENABLING IS THE WHOLE BRING-UP of that app, in the order `bbox run` gives every app: its
    `prepare` hook, its containers (created through scripts/dc when they do not exist), a wait until
    they answer, sign-in for its host, its `onboard` hook, its automations. It used to stop at
    "containers created", so an
    app installed from this screen — or by a linked office, through this API — was running and not
    usable until somebody ran `bbox run` on the machine (measured 2026-10-05: the MacBook's agent
    could enable project-pln on hp-laptop over the link and could not bootstrap it, and asked the
    owner for SSH). A machine nobody can type on is exactly where this plane is the only hand.

    The lock covers what two changes could corrupt between them — the state file, the compile, the
    compose project. The wait and the app's own bootstrap run after it: they concern one app, and
    `_JOBS` already keeps a second change away from that app. `patience` is how long a caller that
    answers a person may wait for the lock (-1: a job, which waits its turn).

    `restore` ({office, archive}) makes it a bring-up WITH THE APP'S DATA, which is what arriving
    from another office means: once the fresh instance answers, its data is fetched and restored
    (`_carry_in`), the instance is waited for again, and only then is `onboard` run — on the data
    that arrived, so an app's first-run bootstrap never mints an owner or a key for an instance
    that is about to be replaced by one that already has them.
    """
    services = _services_of(m)
    # the app's OWN allowance for a first start (the number its Progressing condition is judged by)
    allowance = int(m.get("progress_deadline_seconds") or DEFAULT_PROGRESS_DEADLINE)
    hooks, acted, created, errs, needed, providers_down = {}, [], [], [], [], []
    if not _LIFECYCLE.acquire(timeout=patience):
        return {"error": "another app is being brought up — try again when it is done", "id": aid,
                "busy": sorted(a for a, j in _JOBS.items() if not j["finished"].is_set())}, 409
    try:
        step("state")
        # writes either form, so an entry already migrated to `{ state: ... }` is updated too
        if not _set_disposition(aid, "enabled" if enable else "disabled"):
            # the desired state did not change hands, so nothing after this may: containers started
            # for an app the state file still calls disabled are what the next `bbox run` stops
            return {"error": "the desired state could not be written (see this service's log)", "id": aid}, 500
        try:
            _render()
        except Exception as e:
            return {"error": f"recompile failed: {e}", "id": aid}, 500
        if enable:
            step("prepare")
            hooks["prepare"] = _run_hook(m, "prepare", 600)
        step("containers")
        containers = _app_containers(services)
        have = {c.labels.get("com.docker.compose.service") for c in containers}
        # SWITCHED OFF IS NOT STOPPED when an enabled app requires this one. The compiler keeps a
        # required provider's services in the compiled office whatever its own line says (drive
        # requires supabase's object store), and the next `bbox run` starts them again — so
        # stopping them here only broke the app that needs them until somebody ran it. The line is
        # written, the containers stay, and the answer says who keeps them.
        needed = _required_by(aid) if not enable else []
        for c in containers:
            try:
                if enable and c.status != "running":
                    c.start(); acted.append(c.name)
                elif not enable and not needed and c.status == "running":
                    c.stop(timeout=20); acted.append(c.name)
            except Exception as e:
                return {"error": f"docker {'start' if enable else 'stop'} {c.name}: {e}", "id": aid}, 500
        # enabling an app whose containers don't exist (a gallery install or a previously-uninstalled
        # app) CREATES them — that is what makes "install" work, not just "start". Core apps never
        # reach this: `_lifecycle` refuses them before anything is written.
        if enable and (have != set(services)):
            created, errs = _install(aid)
    finally:
        _LIFECYCLE.release()
    late = f"the app's containers did not all answer within {allowance}s"
    if enable and not errs:
        step("health")
        if not _wait_ready(services, allowance):
            errs.append(late)
    if enable and restore and not errs:
        step("restore")
        problem = _carry_in(aid, restore)
        if problem:
            errs.append(problem)
        elif not _wait_ready(services, allowance):
            errs.append(late + " after its data was restored")
    if enable and not errs:
        if any((r or {}).get("auth") == "sso" for r in m.get("routing") or []):
            step("signin")
            hooks["signin"] = _signin_refresh()
        step("onboard")
        hooks["onboard"] = _run_hook(m, "onboard", allowance + 600)
    # the providers this app pulls in (its hard closure, from the compiler): enabling a dependent
    # must not leave its provider's containers down. START any that are compiled but stopped — fast
    # and safe, they already exist — and NAME in `providers_down` any that is not up at all. Bringing
    # a provider up FROM NOTHING is its own full bring-up (prepare, onboard, and for n8n the
    # owner-signed blueprint push — own-031); it is reported here, never forced, and never fails the
    # dependent's own enable.
    if enable and not errs:
        own = set(services)
        extra = [s for s in (_closure_services(aid) or []) if s not in own]
        if extra:
            step("providers")
            present = {c.labels.get("com.docker.compose.service"): c for c in _app_containers(extra)}
            for s in extra:
                c = present.get(s)
                if c is None:
                    providers_down.append(s)
                elif c.status != "running":
                    try:
                        c.start(); acted.append(c.name)
                    except Exception as e:                       # noqa: BLE001
                        providers_down.append(f"{s} ({type(e).__name__})")
    # automations follow the app: imported on enable, removed on disable — but a provider switched
    # off while an enabled app still needs it KEEPS its workflows too, for the same reason its
    # containers stay (see `needed`, computed above): unpushing them would strand the dependent
    # (disabling INDOX while chat needs indox-api would delete the 69 workflows chat's flows call).
    if not enable and needed:
        blueprint = {"kept": f"required by {', '.join(needed)}"}
    else:
        step("automations")
        blueprint = _blueprint_apply(aid, enable)
    rt = _app_runtime(services, _container_index(), enable)
    # ok reflects what happened. It was hardcoded True, so a wholly failed install returned HTTP
    # 200 with ok=True and the UI reported success, while create_errors was read by nobody.
    return ({"ok": not errs, "id": aid, "enabled": enable, "acted": acted, "created": created,
             "create_errors": errs, "blueprint": blueprint, "required_by": needed,
             "providers_down": providers_down,
             "restored": restore if (restore and not errs) else None,
             "hooks": {k: v for k, v in hooks.items() if v}, **rt}, 200 if not errs else 500)


# A bring-up — and a move, which contains one — is a JOB: it is as long as its slowest part, an image nobody has built yet (ten
# minutes and more on a laptop), a database's first start, an app's own bootstrap. The call used to be
# synchronous behind a 120 s worker timeout and a 40 s console proxy, so the one install that mattered
# most ended as a gateway error while the work went on unseen. Now the call answers as soon as the
# work is DONE or after `BRINGUP_WAIT_S`, whichever is first: 202 with the step it is at means "still
# going", and `GET /api/apps/<id>/job` then answers exactly what the call would have — 202 again, or
# the result with its status. One table, in ONE process (see the Dockerfile's `-w 1`).
BRINGUP_WAIT_S = 20
_JOBS = {}          # app id -> its latest job: {step, started, finished, result, code}


def _job_answer(aid, job, wait=0):
    if job["finished"].wait(wait):
        return jsonify(**job["result"]), job["code"]
    return jsonify(ok=True, id=aid, state="running", step=job["step"],
                   seconds=int(time.time() - job["started"])), 202


def _being_brought_up(aid):
    """The 409 for a change to an app whose bring-up is still running, or None."""
    job = _JOBS.get(aid)
    if not job or job["finished"].is_set():
        return None
    return jsonify(error="the app is being brought up — wait for it to finish", id=aid,
                   state="running", step=job["step"]), 409


def _start_job(aid, work):
    """Run `work(step)` -> (payload, status) as this app's job, and return the job."""
    job = _JOBS[aid] = {"step": "queued", "started": time.time(),
                        "finished": threading.Event(), "result": None, "code": None}

    def run():
        try:
            job["result"], job["code"] = work(lambda name: job.update(step=name))
        except Exception as e:                       # never leave a job that says "running" forever
            job["result"], job["code"] = {"error": f"{type(e).__name__}: {e}", "id": aid}, 500
        job["finished"].set()

    threading.Thread(target=run, daemon=True, name=f"job-{aid}").start()
    return job


def _lifecycle(aid, enable, restore=None):
    m = _manifest(aid)
    if not m:
        return jsonify(error="unknown app", id=aid), 404
    if m.get("_root") == "platform-base":
        # layer 1-2 = core platform. Disabling traefik/redis/authentik/... breaks the stack (and
        # the control plane itself). The catalog marks these `core`; the UI hides the controls, and
        # the API refuses them as defence in depth.
        return jsonify(error="core platform app — protected from lifecycle changes", id=aid), 403
    if docker_sdk is None:
        return jsonify(error="docker socket unavailable"), 503
    if not enable:
        busy = _being_brought_up(aid)
        if busy:
            return busy
        payload, code = _apply(aid, m, False, patience=BRINGUP_WAIT_S)
        return jsonify(**payload), code
    job = _JOBS.get(aid)
    if not job or job["finished"].is_set():          # a second "enable" joins the one in flight
        if restore:
            # ARRIVING WITH DATA REPLACES WHAT IS HERE, so it is refused when there is anything here
            # to replace: the archiver empties each of the app's volumes before it fills them. An
            # office that holds this app's data says so and is left alone; removing that data is a
            # separate decision with its own verb (uninstall with purge).
            held = _held_volumes(m)
            if held:
                return jsonify(error="this office already holds data of this app — bringing it from "
                                     "another office would replace it. Remove it here with its data "
                                     "first (uninstall, purge), or choose another office.",
                               id=aid, volumes=held), 409
        job = _start_job(aid, lambda step: _apply(aid, m, True, step, restore=restore))
    return _job_answer(aid, job, BRINGUP_WAIT_S)


def _move(aid, m, to, step, wake=False):
    """This app, with its data, to a linked office — and switched off here only once it is THERE.

    Three steps, each one a verb that already exists: this office's data-management exports the app;
    that office's app-management brings it up from that archive (it fetches it over the link —
    `_carry_in` on its side — and the archiver there compares what arrived with what left, fact by
    fact); this office switches its own copy off. Nothing is deleted anywhere: the app's volumes
    stay here until somebody uninstalls it, so every failure before the last step leaves the app
    running here exactly as it was, and the last step is undone by switching it on again.

    The export is taken from the RUNNING app (its stores have to answer to be read), so what is
    written to it between the export and the switch-off stays on this side. That window is the
    length of the move, and it is the mover's to keep quiet.

    `wake`: an app that is switched off here is switched on for the read — the ordinary bring-up,
    not a second way to start containers — and a move that then fails switches it off again, so
    every failure still leaves the app as it was found. It is asked for, never assumed: starting an
    app is exactly what an office that is moving it away for its weight may not want to do unasked.
    """
    woke = False

    def as_found(answer, code):
        if woke:
            _apply(aid, m, False)
            answer["error"] += " (it was switched on here for the read, and is switched off again)"
        return answer, code

    if wake and _app_runtime(_services_of(m), _container_index(), True)["state"] != "running":
        step("wake")
        here, code = _apply(aid, m, True)
        woke = True
        if code != 200:
            why = here.get("error") or (here.get("create_errors") or [f"HTTP {code}"])[0]
            return as_found({"error": f"the app could not be switched on here to be read: {why}",
                             "id": aid, "here": here}, 500)
    step("export")
    ok, exported = _data_job("export", app=aid)
    if not ok:
        return as_found({"error": f"the app could not be exported here: {_said(exported)}", "id": aid}, 500)
    archive = os.path.basename(exported["out"])
    step("place")
    status, there = _call("POST", _peer(to, f"/{aid}/enable"), {"restore": {"archive": archive}})
    silent = 0
    while status in (202, 0) and silent < 60:        # three minutes of no answer at all ends it
        silent = silent + 1 if status == 0 else 0
        time.sleep(3)
        status, there = _call("GET", _peer(to, f"/{aid}/job"))
    if status != 200:
        why = there.get("error") or (there.get("create_errors") or [f"HTTP {status}"])[0]
        return as_found({"error": f"{to} did not bring the app up with its data — here it is "
                                  f"untouched: {why}", "id": aid, "archive": archive, "there": there}, 502)
    step("off")
    here, code = _apply(aid, m, False)
    return {"ok": code == 200, "id": aid, "moved_to": to, "archive": archive,
            "there": there, "here": here}, code


# ── room: does THIS office have space for an app? ───────────────────────────────────────────────
#
# Asked before an app is placed anywhere — by the apps screen for every office it offers, and by a
# move of the office it is moving to. The office answers about ITSELF: the rule is `admission.py`
# and the facts are read here, from inside this container, which sees the machine's memory and load
# and the engine's disk without any door to the machine.

def _machine_here():
    """This machine as the admission rule reads one, or {} when it cannot be read (the rule then
    refuses, saying the machine was not looked at — never an approval by default)."""
    mem = {}
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                key, _, rest = line.partition(":")
                if key in ("MemTotal", "MemAvailable"):
                    mem[key] = int(rest.split()[0]) * 1024
        load = os.getloadavg()[0]
        free = shutil.disk_usage("/").free      # this container's root is on the engine's own disk
    except (OSError, ValueError, IndexError):
        return {}
    return {"ncpu": os.cpu_count() or 0, "load": load,
            "memory": {"total": mem.get("MemTotal", 0), "available": mem.get("MemAvailable", 0)},
            "disk": {"available": free}, "host": _host_here()}


def _host_here():
    """The machine UNDER this office's VM, as the office's host-side pass last wrote it
    (`data/power/host.json` — the file the machine screen reads too), or {}: no host-side part
    here, or a report older than fifteen minutes, which is not a measurement any more."""
    try:
        doc = json.load(open(os.path.join(REPO, "data", "power", "host.json"), encoding="utf-8"))
        if time.time() - float(doc["updated_at"]) > 900:
            return {}
        return {"mem_total": int(doc["mem_total"]), "mem_free": int(doc["mem_free"])}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def _app_need(m):
    """What an app asks for, in its own words: `resources` in its manifest, else the limits its own
    compose file gives its services, summed. None when it says neither — an app that declares
    nothing is not an app that needs nothing, and the answer has to say which it is."""
    res = m.get("resources") or {}
    if res.get("memory"):
        return {"memory": res["memory"], "cpus": res.get("cpus") or 0}
    mem = cpus = 0.0
    try:
        doc = yaml.safe_load(open(os.path.join(m.get("_dir") or REPO, m.get("compose") or ""),
                                  encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    for svc in (doc.get("services") or {}).values():
        lim = (((svc or {}).get("deploy") or {}).get("resources") or {}).get("limits") or {}
        mem += admission.mib(lim.get("memory"))
        try:
            cpus += float(lim.get("cpus") or 0)
        except (TypeError, ValueError):
            pass
    return {"memory": f"{mem:.0f}M", "cpus": round(cpus, 2)} if mem else None


@app.get("/api/apps/<aid>/room")
def api_room(aid):
    """Would this app fit on this office right now? `{ok, need, have, problems[], summary}` — the
    refusals are Hebrew sentences with the numbers in them (`admission.check`)."""
    m = _manifest(aid)
    if not m:
        return jsonify(error="unknown app", id=aid), 404
    need = _app_need(m)
    verdict = admission.check(_machine_here(), [{"id": aid, "resources": need or {}}])
    if need is None:
        # disk and load were still judged; memory could not be, and saying "0MB fits" would be a lie
        verdict["undeclared"] = True
        if verdict["ok"]:
            verdict["summary"] = "האפליקציה לא מצהירה כמה זיכרון היא צריכה — נבדקו הדיסק והעומס בלבד"
    return jsonify(id=aid, **verdict)


@app.get("/api/apps/<aid>/job")
def api_job(aid):
    job = _JOBS.get(aid)
    if not job:
        return jsonify(error="no bring-up of this app since this service started", id=aid), 404
    return _job_answer(aid, job)


# ── routes ────────────────────────────────────────────────────────────────

@app.post("/api/apps/<aid>/archive")
def api_archive(aid):
    """Reclaim disk WITHOUT losing anything the user cares about.

    Removes the app's containers and its images; keeps every named volume, keeps the manifest in
    the catalog, keeps the tile. This is Android 15's app archiving, and on a single-VPS business
    box disk is the scarce resource — "uninstall it to free space" is the wrong trade because it
    throws away the data. Unarchive re-pulls and starts again.
    """
    if request.headers.get(OFFICE_HEADER):
        # §9: a request that crossed a link cannot write this office's own state — and what to take
        # off this office's disk is this office's decision. `enable` WITH `restore` is the one
        # lifecycle verb a peer has business in (it is how a move places an app here).
        return jsonify(error="a linked office does not archive this office's apps"), 403
    m = _manifest(aid)
    if not m:
        return jsonify(error="unknown app", id=aid), 404
    if m.get("_root") == "platform-base":
        return jsonify(error="core platform app — protected", id=aid), 403
    if docker_sdk is None:
        return jsonify(error="docker socket unavailable"), 503
    busy = _being_brought_up(aid)
    if busy:
        return busy
    needed = _still_needed(aid)
    if needed:
        return needed

    client = docker_sdk.from_env()
    services = _services_of(m)
    removed_c, removed_i, errs = [], [], []
    with _LIFECYCLE:
        _blueprint_apply(aid, False)          # automations follow the app out
        for c in _app_containers(services):
            img = None
            try:
                img = c.image.id
            except Exception:
                pass
            try:
                c.remove(force=True); removed_c.append(c.name)
            except Exception as e:
                errs.append(f"{c.name}: {e}")
            if img:
                try:
                    client.images.remove(img, force=False); removed_i.append(img[:19])
                except Exception:
                    pass                       # shared base layers are legitimately still in use
        _set_disposition(aid, "archived")
        try:
            _render()
        except Exception as e:
            errs.append(f"recompile: {e}")
    return jsonify(ok=True, id=aid, archived=True, containers_removed=removed_c,
                   images_removed=removed_i, errors=errs,
                   volumes_kept=(m.get("data") or {}).get("volumes") or [])


@app.post("/api/apps/<aid>/unarchive")
def api_unarchive(aid):
    """Bring an archived app back: re-create from its compose and start it. Data was never gone."""
    if request.headers.get(OFFICE_HEADER):
        return jsonify(error="a linked office does not bring this office's apps back"), 403
    return _lifecycle(aid, True)


@app.post("/api/apps/<aid>/enable")
def api_enable(aid):
    """Bring the app up. `{"restore": {"archive": <name>, "office": <office>}}` brings it up WITH ITS
    DATA from the linked office that exported that archive.

    WHICH office is the link's answer when there is one: a request that crossed a link carries the
    office it came from, written by the door (`OFFICE_HEADER`), and that wins over the body — so a
    linked office can have its OWN export fetched and nobody else's."""
    restore = (request.get_json(silent=True) or {}).get("restore")
    if request.headers.get(OFFICE_HEADER) and not isinstance(restore, dict):
        # A linked office reaches this route for ONE thing: a move placing an app HERE with its data
        # (`_move` on the other side POSTs `{"restore": {archive, …}}`). Everything else this route
        # does is a plain switch-on of this office's own app — writing this office's own state, which
        # §9 refuses a request that crossed a link. Measured 2026-10-09 (DGO-49): the header was only
        # READ here (to pick whose export to fetch) and never a refusal.
        return jsonify(error="a linked office brings an app here only with its data — a plain "
                             "switch-on of this office's apps is this office's own decision"), 403
    if restore is not None:
        if not isinstance(restore, dict):
            return jsonify(error="restore must be {archive, office}", id=aid), 400
        office = str(request.headers.get(OFFICE_HEADER) or restore.get("office") or "").strip().lower()
        archive = str(restore.get("archive") or "").strip()
        if not _OFFICE_RE.match(office) or not _ARCHIVE_RE.match(archive):
            return jsonify(error="restore needs the archive's name and the office that holds it",
                           id=aid), 400
        restore = {"office": office, "archive": archive}
    return _lifecycle(aid, True, restore)


@app.post("/api/apps/<aid>/apply")
def api_apply(aid):
    """Bring ONE running app in line with what is compiled now: recompile, let compose recreate
    whichever of its services changed, and make sign-in serve any host that appeared.

    For an app whose compiled shape changes while it runs without its disposition changing — the
    link plane's sidecar gains a network alias for every app a linked office starts to give. That
    used to be a shell line the app ran on "the machine" over SSH."""
    if request.headers.get(OFFICE_HEADER):
        # A request that crossed a link cannot write this office's own state: applying recompiles
        # and lets compose RECREATE containers here — the route §9 names beside `PUT /api/remote`,
        # which refuses the same caller. Measured 2026-10-09 by the §9 tests
        # (`apps/dgo-extend/tests/test_link_security.py`), which found it reachable unguarded.
        return jsonify(error="a linked office does not apply this office's apps"), 403
    m = _manifest(aid)
    if not m:
        return jsonify(error="unknown app", id=aid), 404
    if m.get("_root") == "platform-base":
        return jsonify(error="core platform app — it is applied by `bbox run`", id=aid), 403
    if docker_sdk is None:
        return jsonify(error="docker socket unavailable"), 503
    if _disposition(_load_state().get(aid)) != "enabled":
        return jsonify(error="the app is switched off — nothing of it is running to bring in line",
                       id=aid), 409
    busy = _being_brought_up(aid)
    if busy:
        return busy
    services = _services_of(m)
    if not _LIFECYCLE.acquire(timeout=BRINGUP_WAIT_S):
        return jsonify(error="another app is being brought up — try again when it is done", id=aid), 409
    try:
        try:
            _render()
        except Exception as e:
            return jsonify(error=f"recompile failed: {e}", id=aid), 500
        failed = _compose_up(services) if services else None
    finally:
        _LIFECYCLE.release()
    signin = _signin_refresh()
    return (jsonify(ok=not failed, id=aid, applied=services, signin=signin, error=failed),
            200 if not failed else 500)


# ── what linked offices give this one: the `remote:` block ───────────────────────────────────
#
# The link plane (dgo-extend) builds the block from the catalogs its peers publish; the compiler
# owns the file and validates the block (`reconcile.set_remote`); this plane is the way between
# them, because it is the one service that holds the checkout. The link plane used to reach the
# file by running a script on "the machine that runs this office" over SSH — which an office with
# no such door never could (hp-laptop has none, by its owner's decision), so there every app a
# linked office added waited for a person to run a command.
#
# For THIS office's own link plane only. A request that crossed a link is refused: what this
# office shows of other offices is not something one of those offices declares.

def _closure_services(aid):
    """Every compose service this app's HARD closure needs — itself and the providers it pulls in,
    in dependency order (the compiler's `services --for`). [] when it could not be asked, so a
    failure here never strands the app's own bring-up (the caller falls back to the app's own)."""
    code, out, err = _compiler("services", "--for", aid)
    if code != 0:
        app.logger.warning("services --for %s: %s", aid, (err or out)[-200:])
        return []
    return [s for s in re.split(r"[,\s]+", (out or "").strip()) if s]


def _required_by(aid):
    """The enabled apps that cannot run without this one — the compiler's answer, [] when nobody
    (or when it could not be asked: a guard that refuses on its own failure would lock every app).
    """
    code, out, err = _compiler("required-by", "--app", aid)
    if code != 0:
        app.logger.warning("required-by %s: %s", aid, (err or out)[-200:])
        return []
    try:
        return [str(x) for x in json.loads(out or "[]")]
    except ValueError:
        return []


def _still_needed(aid):
    """The refusal for a verb that would take this app's containers or data away while an enabled
    app requires it, or None. One sentence, with the names."""
    needed = _required_by(aid)
    if not needed:
        return None
    return jsonify(error=f"{aid} is required by {', '.join(needed)} on this office — it runs because "
                         f"they need it. Switch those off (or move them) first.",
                   id=aid, required_by=needed), 409


def _compiler(*args, stdin=None):
    r = subprocess.run(["python3", RECONCILE, *args], cwd=REPO, capture_output=True, text=True,
                       input=stdin, timeout=120, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


@app.get("/api/remote")
def api_remote_get():
    code, out, err = _compiler("remote-get")
    if code != 0:
        return jsonify(error=err[-300:] or "the state file could not be read"), 500
    return jsonify(remote=json.loads(out or "[]"))


def withdrawn_tiles(block, tiles):
    """Tiles of linked offices that are still COMPILED although their office no longer gives the app.

    Declaring the block writes the state file; it is the compile that takes a tile and its route
    away, and nothing asked for one when an app was only withdrawn (the link plane applies what was
    GAINED). Measured 2026-10-06 on hp-laptop: the MacBook had stopped giving two apps, the block
    said so, and both tiles stood in the rail for days, each opening onto "the office answered, the
    app is not there (404)".

    Only for an office that IS in the block. One that did not answer is absent from it: its apps are
    unconfirmed, not withdrawn, and they keep their tiles — the link marks them unreachable. It is
    what is compiled that is read, not what changed, so a compile that was missed is made up for."""
    gives = {str(e.get("office") or ""): {str(a.get("alias") or "") for a in (e.get("apps") or [])}
             for e in block if isinstance(e, dict)}
    return [str(t.get("id")) for t in tiles or []
            if isinstance(t, dict) and isinstance(t.get("remote"), dict)
            and str(t["remote"].get("office")) in gives
            and str(t["remote"].get("alias") or "") not in gives[str(t["remote"].get("office"))]]


def _compiled_tiles():
    try:
        with open(os.path.join(REPO, ".generated", "registry", "console.modules.yaml"), encoding="utf-8") as f:
            return yaml.safe_load(f) or []
    except (OSError, yaml.YAMLError):
        return []


@app.put("/api/remote")
def api_remote_put():
    if request.headers.get(OFFICE_HEADER):
        return jsonify(error="a linked office does not declare what this office shows of others"), 403
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get("remote"), list):
        return jsonify(error='send {"remote": [...]} — the whole block'), 400
    if not _LIFECYCLE.acquire(timeout=BRINGUP_WAIT_S):
        return jsonify(error="another change is being applied — try again when it is done"), 409
    gone, compile_error = [], ""
    try:
        code, out, err = _compiler("remote-set", "--json", stdin=json.dumps(body["remote"]))
        if code == 0:
            gone = withdrawn_tiles(body["remote"], _compiled_tiles())
            if gone:
                try:
                    _render()
                except Exception as e:                      # noqa: BLE001 — said in the answer
                    compile_error = str(e)[-300:]
    finally:
        _LIFECYCLE.release()
    if code == 1:
        return jsonify(error="the compiler refuses this block — nothing written",
                       refused=[ln.strip(" -") for ln in err.splitlines() if ln.strip()]), 422
    if code != 0:
        return jsonify(error=err[-300:] or "the block could not be written"), 500
    return jsonify(ok=True, **json.loads(out), withdrawn=gone,
                   **({"compile_error": compile_error} if compile_error else {}))


@app.post("/api/apps/<aid>/move")
def api_move(aid):
    """Move this app, with its data, to a linked office: `{"to": <office>}` — plus `"wake": true`
    for an app that is switched off here (it is switched on for the read), and `"force": true` to
    move although the destination says it has no room. A job, followed at
    `<app>/job` like a bring-up. See `_move` for what it does and what it never does."""
    if request.headers.get(OFFICE_HEADER):
        # §9's own sentence: "a move is never handed on from a request that itself arrived over a
        # link" — a move ends by switching this office's copy OFF (that is state), and it asks a peer
        # to act; a linked office naming what this one owns is a second office moving another's app.
        return jsonify(error="a move is never handed on from a request that itself arrived over a "
                             "link"), 403
    m = _manifest(aid)
    if not m:
        return jsonify(error="unknown app", id=aid), 404
    if m.get("_root") == "platform-base":
        return jsonify(error="core platform app — it is part of every office and does not move",
                       id=aid), 403
    if docker_sdk is None:
        return jsonify(error="docker socket unavailable"), 503
    asked = request.get_json(silent=True) or {}
    to, wake = str(asked.get("to") or "").strip().lower(), asked.get("wake") is True
    anyway = asked.get("force") is True
    if not _OFFICE_RE.match(to):
        return jsonify(error="name the linked office to move to: {\"to\": <office>}", id=aid), 400
    busy = _being_brought_up(aid)
    if busy:
        return busy
    needed = _still_needed(aid)
    if needed:
        return needed
    # Refusals that need nothing to have happened yet — said before a byte is exported.
    rt = _app_runtime(_services_of(m), _container_index(), True)
    if rt["state"] != "running" and not wake:
        return jsonify(error="the app is not running here — its data is read from its running "
                             "stores. Switch it on first, or have the move do it for the read: "
                             "{\"to\": <office>, \"wake\": true}", id=aid, **rt), 409
    status, far = _call("GET", _peer(to))
    theirs = next((a for a in far.get("apps") or [] if a.get("id") == aid), None)
    if status != 200:
        return jsonify(error=f"{to} is not an office this one can place apps on — it is not "
                             f"linked, does not give its app-management, or did not answer",
                       id=aid, to=to, status=status), 502
    if not theirs:
        return jsonify(error=f"{to} has no app '{aid}' in its catalog", id=aid, to=to), 409
    if theirs.get("installed") or theirs.get("enabled"):
        return jsonify(error=f"{aid} is already installed on {to}", id=aid, to=to), 409
    # ROOM, in the destination's own words — before a byte is exported. An office that does not
    # answer the question (it predates it) is not refused for that; one that answers "no" is, with
    # its sentence, unless the caller says `"force": true`: the rule is deliberately cautious (an
    # app's limit plus headroom against what is free NOW), and the owner may know better.
    status, room = _call("GET", _peer(to, f"/{aid}/room"))
    if status == 200 and room.get("ok") is False and not anyway:
        return jsonify(error=f"{to} says it has no room for {aid}: {room.get('summary') or ''} "
                             f"— to move it anyway: {{\"to\": <office>, \"force\": true}}",
                       id=aid, to=to, room=room), 409
    job = _start_job(aid, lambda step: _move(aid, m, to, step, wake))
    return _job_answer(aid, job, BRINGUP_WAIT_S)


@app.post("/api/apps/<aid>/disable")
def api_disable(aid):
    """Switch the app off here. Refused for a request that crossed a link: what runs on this office
    is this office's own state (§9), and a peer that wants it gone says so over its own link plane."""
    if request.headers.get(OFFICE_HEADER):
        return jsonify(error="a linked office does not switch this office's apps off"), 403
    return _lifecycle(aid, False)


def _remove_volumes(vols):
    """Remove an app's named volumes. Compose prefixes them with the project name."""
    client = docker_sdk.from_env()
    removed, failed = [], []
    for v in vols:
        for name in (f"{PROJECT}_{v}", v):  # try the prefixed name first, then a literal external one
            try:
                client.volumes.get(name).remove(force=True)
                removed.append(name)
                break
            except docker_sdk.errors.NotFound:
                continue
            except Exception as e:
                failed.append(f"{name}: {e}")
                break
    return removed, failed


@app.post("/api/apps/<aid>/uninstall")
def api_uninstall(aid):
    if request.headers.get(OFFICE_HEADER):
        # The heaviest verb here: containers AND — with `purge` — the app's volumes. §9 refuses a
        # request that crossed a link this office's own state, and data is the part of it nobody
        # can bring back.
        return jsonify(error="a linked office does not uninstall this office's apps"), 403
    m = _manifest(aid)
    if not m:
        return jsonify(error="unknown app", id=aid), 404
    if m.get("_root") == "platform-base":
        return jsonify(error="core platform app — cannot be uninstalled", id=aid), 403
    if docker_sdk is None:
        return jsonify(error="docker socket unavailable"), 503
    busy = _being_brought_up(aid)
    if busy:
        return busy
    needed = _still_needed(aid)
    if needed:
        return needed

    # data policy: request body wins (the UI resolves a "prompt" app by asking the user); otherwise
    # the app's declared on_uninstall decides. This is the on_uninstall contract every app.json has
    # carried but nothing implemented until now.
    policy = (m.get("data") or {}).get("on_uninstall", "keep")
    body = request.get_json(silent=True) or {}
    purge = bool(body["purge"]) if "purge" in body else (policy == "purge")

    with _LIFECYCLE:
        _set_disposition(aid, "disabled")
        try:
            _render()   # drops the app from the compiled compose, SSO providers, tiles, DSNs
        except Exception as e:
            return jsonify(error=f"recompile failed: {e}"), 500
        # stop + REMOVE the containers (uninstall, not just disable)
        removed_containers = []
        for c in _app_containers(_services_of(m)):
            try:
                c.remove(force=True); removed_containers.append(c.name)
            except Exception as e:
                return jsonify(error=f"docker remove {c.name}: {e}"), 500
        # the app's own cleanup (DB rows, n8n blueprints, SSO...) — reported, never blocking
        hook = _run_hook(m, "uninstall", 120)
        removed_vols, vol_errs = ([], [])
        if purge:
            removed_vols, vol_errs = _remove_volumes((m.get("data") or {}).get("volumes") or [])

    return jsonify(ok=True, id=aid, purged=purge, policy=policy,
                   removed_containers=removed_containers, removed_volumes=removed_vols,
                   volume_errors=vol_errs, hook=hook,
                   note="uninstalled; the app stays in the catalog as available to install")


# ── install-by-reference (the signed catalog) ────────────────────────────────
#
# TWO CALLS, ON PURPOSE. `preview` fetches + verifies + validates and STAGES the bytes; `install`
# completes from that same staged copy. A single call that re-fetched after the user consented
# would be a time-of-check/time-of-use hole: the user would approve a disclosure computed from one
# download and install a different one. So the disclosure and the installed bytes are the same
# bytes, by construction.
_STAGED = {}                 # token -> {dir, id, prov, disclosure, created}
_STAGE_TTL = 20 * 60
_STAGE_MAX = 8


def _stage_gc():
    now = time.time()
    for tok in [t for t, s in _STAGED.items() if now - s["created"] > _STAGE_TTL]:
        shutil.rmtree(_STAGED.pop(tok)["work"], ignore_errors=True)
    while len(_STAGED) > _STAGE_MAX:
        tok = min(_STAGED, key=lambda t: _STAGED[t]["created"])
        shutil.rmtree(_STAGED.pop(tok)["work"], ignore_errors=True)


@app.get("/api/catalog")
def api_catalog_index():
    """The local signed index, if this deployment has built one. Refused if it does not verify."""
    if catalog_mod is None:
        return jsonify(error=f"catalog unavailable: {_CATALOG_IMPORT_ERROR}"), 503
    ref = request.args.get("ref") or str(catalog_mod.DEFAULT_OUT / catalog_mod.INDEX_NAME)
    try:
        index, meta = catalog_mod.load_index(ref, require_signature=True)
    except Exception as e:
        return jsonify(error=str(e), ref=ref, entries=[]), 200
    return jsonify(meta=meta, repo=index.get("repo"), entries=index.get("entries") or [])


@app.post("/api/catalog/preview")
def api_catalog_preview():
    """Fetch + verify + validate a candidate and return the PRE-INSTALL DISCLOSURE. Writes nothing
    into apps/ or platform.state.yaml. Accepts a JSON {ref} or an uploaded file."""
    if appinstall is None:
        return jsonify(error=f"catalog unavailable: {_CATALOG_IMPORT_ERROR}"), 503
    _stage_gc()
    work = tempfile.mkdtemp(prefix="bbox-install-")
    try:
        up = request.files.get("file")
        if up and up.filename:
            blob_path = os.path.join(work, os.path.basename(up.filename) or "artifact.zip")
            up.save(blob_path)
            ref, body = blob_path, {}
        else:
            body = request.get_json(silent=True) or {}
            ref = (body.get("ref") or "").strip()
            if not ref:
                shutil.rmtree(work, ignore_errors=True)
                return jsonify(error="no ref and no file"), 400
        app_dir, prov = appinstall.stage(
            ref, index_ref=body.get("index") or None,
            expect_sha=(body.get("sha256") or None),
            # An UPLOAD is an operator handing the platform a file it chose. There is no signature
            # to demand, so it is accepted and reported as unverified — unless its hash happens to
            # match an entry in the signed index, which stage() checks and upgrades.
            allow_unverified=bool(body.get("allow_unverified") or (up and up.filename)),
            workdir=os.path.join(work, "stage"))
        manifest, cat, state, dis, refusals = appinstall.inspect(app_dir, prov)
    except SystemExit as e:          # reconcile.py exits on a broken catalog; do not take us with it
        shutil.rmtree(work, ignore_errors=True)
        return jsonify(error=f"catalog is not loadable: {e}"), 500
    except Exception as e:
        shutil.rmtree(work, ignore_errors=True)
        return jsonify(error=str(e)), 400
    token = secrets.token_urlsafe(18)
    _STAGED[token] = {"work": work, "dir": str(app_dir), "id": manifest.get("id"),
                      "prov": prov, "disclosure": dis, "refusals": refusals,
                      "created": time.time()}
    return jsonify(token=token, id=manifest.get("id"), version=manifest.get("version"),
                   provenance={k: v for k, v in prov.items() if k != "entry"},
                   disclosure=dis, refusals=refusals, installable=not refusals)


@app.post("/api/catalog/install")
def api_catalog_install():
    """Complete a previewed install: place the STAGED bytes, then hand over to the SAME lifecycle
    every other install uses (`_lifecycle`) so there is one code path that starts an app."""
    if request.headers.get(OFFICE_HEADER):
        # It writes apps/<id> AND enables it — this office's own state twice over. A peer installs an
        # app on itself; a move places one HERE through `enable` with `restore`, from THIS office's
        # own screen (the mover's request is not one that arrived over a link).
        return jsonify(error="a linked office does not install into this office"), 403
    if appinstall is None:
        return jsonify(error=f"catalog unavailable: {_CATALOG_IMPORT_ERROR}"), 503
    body = request.get_json(silent=True) or {}
    st = _STAGED.get((body.get("token") or "").strip())
    if not st:
        return jsonify(error="unknown or expired staging token — preview again"), 410
    if st["refusals"]:
        return jsonify(error="refused: " + "; ".join(st["refusals"])), 409
    aid = st["id"]
    with _LIFECYCLE:
        try:
            # placed DISABLED, then enabled through the normal lifecycle below — so an install
            # goes through exactly the transitions an operator's enable click does.
            appinstall.place(st["dir"], aid, enable=False)
        except Exception as e:
            return jsonify(error=f"place failed: {e}"), 500
    shutil.rmtree(_STAGED.pop(body["token"])["work"], ignore_errors=True)
    resp, code = _lifecycle(aid, True)    # the one bring-up; 202 while it is still going
    data = resp.get_json()
    data["installed_from"] = st["prov"].get("how")
    data["verified"] = bool(st["prov"].get("verified"))
    return jsonify(**data), code


# ── this office's own record — the install wizard's ONE write ─────────────────────────────────
#
# Who this office is: its name, the animal and hue that mark its apps on every linked office, the
# terms it accepted and when its wizard finished. It is the `office:` block of platform.state.yaml,
# written by the compiler (`reconcile.set_office`, the file's one writer — shelled like
# `_set_disposition`, and for the same reason) and read by the console to decide whether a visitor
# meets the install wizard or the shell. The wizard (platform-base/console/static/install.*) is the
# only writer; `installed_at` is its last step's signature.

def _office_get():
    r = subprocess.run(["python3", RECONCILE, "office-get"], cwd=REPO,
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "office-get failed").strip()[:300])
    return json.loads(r.stdout or "{}")


def _office_set(fields, by="wizard"):
    """(written, errors) — the compiler validates before it writes; its sentences come back as-is."""
    r = subprocess.run(["python3", RECONCILE, "office-set", "--by", by], cwd=REPO,
                       input=json.dumps(fields), capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        said = [ln.strip().lstrip("- ").strip() for ln in (r.stderr or r.stdout or "").splitlines()]
        return False, [s for s in said if s] or ["office record refused"]
    return True, []


def _office_installed(rec):
    """Installed = the wizard's own signature (`installed_at`) — OR any layer-3 app switched on.

    The second half is for the offices that existed before the wizard did: measured 2026-10-09 on
    hp-laptop, the first console image carrying the wizard served it at `/` to an office running
    twenty apps, because no record had ever been written there. An office with an installable app
    enabled was set up — by this wizard or by a person before it — and must never be handed the
    wizard again. An office whose owner chose zero apps still counts as installed through its record.
    """
    if rec.get("installed_at"):
        return True
    try:
        state = _load_state()
        roots = {m.get("id"): m.get("_root") for m in _load_manifests()}
    except Exception:
        return False
    return any(_disposition(entry) == "enabled" and roots.get(aid) == "apps"
               for aid, entry in state.items())


@app.get("/api/office")
def api_office_get():
    """`{office: {…}, installed: bool}` — see `_office_installed` for what "installed" means."""
    try:
        rec = _office_get()
    except Exception as e:
        return jsonify(error=str(e)), 500
    return jsonify(office=rec, installed=_office_installed(rec))


@app.put("/api/office")
def api_office_put():
    if request.headers.get(OFFICE_HEADER):
        # Who THIS office is — its name, its animal, its colour — is its own to say. A linked office
        # reads the record through the catalog; it does not write it (§9 of the pairing contract).
        return jsonify(error="a linked office does not write this office's identity"), 403
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="the office record is a JSON object of its fields"), 400
    ok, errs = _office_set(body)
    if not ok:
        return jsonify(error="; ".join(errs), errors=errs), 400
    try:
        rec = _office_get()
    except Exception as e:
        return jsonify(error=str(e)), 500
    return jsonify(ok=True, office=rec, installed=_office_installed(rec))


@app.get("/healthz")
def healthz():
    return jsonify(ok=True)


@app.get("/readyz")
def readyz():
    cidx = _container_index()
    return jsonify(ok=True, docker=cidx is not None, repo=os.path.isfile(STATE))


@app.get("/api/apps")
def api_apps():
    try:
        apps = _catalog()
    except Exception as e:
        return jsonify(error=str(e)), 500
    return jsonify(
        project=PROJECT,
        counts={
            "total": len(apps),
            "installable": sum(1 for a in apps if not a["core"]),
            "running": sum(1 for a in apps if a.get("state") == "running"),
            "core": sum(1 for a in apps if a["core"]),
        },
        apps=apps,
    )


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/<path:path>")
def static_files(path):
    return send_from_directory(app.static_folder, path)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
