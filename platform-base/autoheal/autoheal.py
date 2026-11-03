#!/usr/bin/env python3
"""autoheal — restart the containers Docker has marked `unhealthy` that asked for it, and say so
about the ones it may not restart.

WHY THIS EXISTS
---------------
Docker computes health and then does nothing with it. `restart: unless-stopped` — which every
service in this estate declares — acts on PROCESS EXIT, not on health status. So a container whose
PID 1 is alive but whose work has stopped stays `unhealthy` for ever and no part of this repo
reacts. Measured 2026-08-10: `n8n-worker-1` consumed ZERO Bull jobs for over two hours at 95.5%
CPU while `bull:jobs:wait` sat at 132 and `bull:jobs:active` at 8 — exactly one worker's
`--concurrency=8`, i.e. the estate ran at half capacity. Docker said `unhealthy` the whole time.
A human noticed and typed `docker restart`; `active` went 8 -> 16 and base-extraction throughput
rose from ~123/hr to ~160/hr. This service is that human, and the owner's requirement is that no
human should have been needed.

WHAT IT DELIBERATELY IS NOT
---------------------------
Not a supervisor, not a reconciler, not a health *aggregator*. It answers exactly one question per
container — "has Docker said `unhealthy` about you, consistently, for long enough, and are you
allowed to be restarted?" — and its only verb is `POST /containers/<id>/restart`. It never creates,
removes, rebuilds, scales or reconfigures anything. That narrowness is the safety property: the
blast radius of a bug in here is a restart of a container that opted in.

The estate's existing control plane (platform-base/app-management `reconcile_once`) was considered
first and is the WRONG owner for this, for four reasons that are worth writing down so nobody
re-litigates it: (1) it has no timer — it only runs when something POSTs `/api/reconcile`; (2) it
explicitly skips `platform-base` apps for container convergence (`m.get("_root") != "platform-base"`),
and n8n lives there; (3) its docstring commits it to being purely ADDITIVE — "containers declared
but absent -> compose up", never touching a container that exists; and (4) reaching it means going
through `bbox run`'s `ensure_converged`, which also pushes repo blueprints over live n8n workflows.
A health-driven restart is a different concern with a different risk profile and it gets its own,
much smaller, service.

WHAT IT SAYS ABOUT THE REST
---------------------------
A container this service may not restart — it never opted in, or it is on the refusal list — could
report `unhealthy` for hours and nobody was told. On 2026-10-06 the sign-in sentinel did, for
fifteen, and two sign-in hosts went unserved; its state was on the machine screen for whoever
opened it. (It must not opt in: a restart in the middle of its apply starts the apply over.)

So one more thing is observed, and no verb goes with it: a container of THIS deployment that Docker
has held `unhealthy` for AUTOHEAL_WATCH_AFTER seconds gets ONE notice per episode, with its last
probe output. Twenty minutes by default — longer than a cold start, whose slowest piece is that
sentinel's own fifteen-minute apply — so bringing the office up tells nobody anything. No label is
needed and none was added: enrolling a container for a RESTART is a decision and stays opt-in;
being told it is broken is not one. The daemon is asked for the unhealthy ones as a filtered list,
so a healthy office costs one call a cycle.

────────────────────────────────────────────────────────────────────────────────────────────────
THE SAFETY ARGUMENT — read this before widening anything
────────────────────────────────────────────────────────────────────────────────────────────────
On 2026-08-10, at the moment this was designed, BOTH n8n workers reported `unhealthy` and only ONE
was actually wedged. worker-2 was processing normally at 103% CPU. An autoheal wired naively to
`unhealthy` would have restarted a healthy, busy worker — and, because the fault was in the probe
rather than in either worker, it would have done so again every couple of minutes, for ever.

The root cause was found and fixed in apps/n8n/worker-liveness.sh (it read a FIXED log
path that n8n's rotating file logger had renamed out from under it, so its progress fingerprint
could never change and its stall timer only ever grew). But "we fixed the sensor" is not a safety
argument, because the next sensor bug is not yet known. So this service assumes its input is
capable of being wrong, and four independent gates stand between `unhealthy` and a restart:

  1. OPT-IN, NEVER OPT-OUT.  A container is eligible only if it carries the label
     `binaos.autoheal=true`. A new service is never silently enrolled by existing here. Eligibility
     is declared in the same compose file as the service, so it shows up in the same diff.
     AND IT IS THIS DEPLOYMENT'S: the label used to be read engine-wide, and an engine can carry
     two stacks. hp-laptop does (measured 2026-10-07: 45 containers of one project, 8 of another,
     an autoheal in each), so each autoheal counted the other's labelled containers as its own —
     a wedged worker would have been restarted twice, under two breakers, and reported in the
     wrong office. The list is scoped to this service's own compose project.
  2. A HARD REFUSAL LIST that a label cannot override.  Stateful services are refused by name even
     when labelled, because the cost of being wrong is asymmetric and measured: restarting
     `n8n-postgres` or `supabase-db` forces WAL crash-recovery — 109 seconds of redo, ~2 minutes of
     estate-wide unavailability — to fix a fault a restart usually would not have fixed anyway.
  3. SUSTAINED, SELF-OBSERVED FAILURE.  Docker's own `unhealthy` already implies `retries`
     consecutive probe failures; this service requires AUTOHEAL_STREAK further consecutive
     observations of its own, spaced AUTOHEAL_INTERVAL apart, and resets the count on any single
     healthy reading. A blip cannot reach a restart.
  4. A CIRCUIT BREAKER.  Per container: a cooldown between restarts, and a cap on restarts per
     rolling window. Past the cap it STOPS restarting and escalates instead. This is the gate that
     bounds the damage of a sensor that is wrong the way worker-liveness.sh was wrong: a stuck-
     unhealthy container costs AUTOHEAL_MAX_RESTARTS restarts and then a loud notification, not an
     unbounded loop. Restarting is a hypothesis; a hypothesis that has failed N times is wrong, and
     continuing to apply it is how an autoheal turns one broken container into a broken estate.

Every restart, every refusal and every breaker trip is printed AND posted to the notifications app,
so a silent restart loop cannot exist: the loudest possible failure mode is the point.
"""

import calendar
import heapq
import itertools
import json
import http.client
import os
import re
import socket
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# ── configuration ───────────────────────────────────────────────────────────────────────────────
DOCKER_SOCK = os.environ.get("DOCKER_SOCK", "/var/run/docker.sock")
API_VERSION = os.environ.get("DOCKER_API_VERSION", "v1.41")

# The opt-in label. Chosen over willfarrell/autoheal's `autoheal=true` so it is namespaced and
# greppable, and so enabling this service can never accidentally inherit an eligibility decision
# made for a different tool in a different repo.
LABEL = os.environ.get("AUTOHEAL_LABEL", "binaos.autoheal")

INTERVAL = float(os.environ.get("AUTOHEAL_INTERVAL", "30"))
# 3 consecutive observations at 30s = 90s of sustained `unhealthy` on top of what Docker already
# required. For the n8n workers Docker's own gate is healthcheck interval 30s x retries 2, and the
# liveness probe itself refuses to fail until its own 240s grace has elapsed — so a worker restart
# stands behind ~5.5 minutes of continuously-measured, continuously-reconfirmed stall.
STREAK = int(os.environ.get("AUTOHEAL_STREAK", "3"))
RESTART_TIMEOUT = int(os.environ.get("AUTOHEAL_RESTART_TIMEOUT", "30"))   # SIGTERM->SIGKILL grace

# Cooldown: never restart the same container twice inside this window. Sized well above the n8n
# worker's `start_period: 180s` so a container is never restarted while it is still starting up —
# during start_period Docker reports `starting`, not `unhealthy`, but the cooldown means we do not
# depend on that subtlety being true for every image.
COOLDOWN = float(os.environ.get("AUTOHEAL_COOLDOWN", "900"))
MAX_RESTARTS = int(os.environ.get("AUTOHEAL_MAX_RESTARTS", "3"))
WINDOW = float(os.environ.get("AUTOHEAL_WINDOW", "21600"))               # 6h
# How long a container this service may NOT restart is held `unhealthy` before it is reported.
WATCH_AFTER = float(os.environ.get("AUTOHEAL_WATCH_AFTER", "1200"))      # 20 min: outlasts a cold start

NOTIFY_URL = os.environ.get("NOTIFY_URL", "http://notifications:8977/api/notifications")
DRY_RUN = os.environ.get("AUTOHEAL_DRY_RUN", "0").strip().lower() in ("1", "true", "yes")

# WHO WATCHES THE WATCHMAN. This file's mtime is bumped at the end of every cycle; the container's
# own healthcheck reads its age. A crashed autoheal is already covered by `restart: unless-stopped`
# (the process exits, Docker restarts it) — this covers the other shape, the one this whole service
# exists because of: a process that is alive but has stopped doing its work.
HEARTBEAT = os.environ.get("AUTOHEAL_HEARTBEAT", "/tmp/autoheal.heartbeat")

# ── the hard refusal list ───────────────────────────────────────────────────────────────────────
# Substrings matched against the compose SERVICE name. This is defence in depth, not the primary
# control — the primary control is that these services do not carry the opt-in label. It exists
# because the failure it prevents is unrecoverable-by-this-service and the label is one typo away.
#
# DATABASES: a restart forces WAL crash-recovery. Measured on n8n-postgres 2026-08-10: 109s of redo,
# roughly two minutes during which the whole estate cannot reach its state store. A wedged database
# needs a human with a query plan, not a power cycle.
#
# TRAEFIK: separately, and independently of this list, traefik declares NO healthcheck at all
# (verified live 2026-08-10 — it has no `State.Health` object), so it can never report `unhealthy`
# and is unreachable by this service by construction. It is named here anyway so that adding a
# healthcheck to traefik later cannot quietly make the edge restartable: restarting the edge drops
# every in-flight request and every forward-auth session in the estate.
NEVER_RESTART = tuple(s for s in os.environ.get(
    "AUTOHEAL_NEVER_RESTART",
    "postgres,-db,redis,valkey,mongo,mysql,mariadb,clickhouse,elasticsearch,traefik",
).split(",") if s.strip())


# ── docker engine API over the unix socket (stdlib only, same shape as connections/identity.py) ──
class _UnixHTTPConnection(http.client.HTTPConnection):
    """HTTPConnection over an AF_UNIX socket — the Docker Engine API's transport."""

    def __init__(self, path, timeout=10.0):
        super().__init__("localhost", timeout=timeout)
        self._unix_path = path

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect(self._unix_path)
        self.sock = s


def _docker(method, path, timeout=15.0):
    """One Docker API call. Returns (status, parsed-json-or-None); (None, None) if unreachable."""
    conn = _UnixHTTPConnection(DOCKER_SOCK, timeout=timeout)
    try:
        conn.request(method, f"/{API_VERSION}{path}")
        r = conn.getresponse()
        body = r.read()
        if not body:
            return r.status, None
        try:
            return r.status, json.loads(body.decode("utf-8"))
        except ValueError:
            return r.status, None
    except (OSError, ValueError, http.client.HTTPException) as e:
        log(f"docker api {method} {path} failed: {e}")
        return None, None
    finally:
        try:
            conn.close()
        except OSError:
            pass


def log(msg):
    """Every decision this service makes goes to stdout, which the json-file driver captures.

    An autoheal that restarts things quietly is worse than no autoheal: the restart erases the
    evidence of the fault that caused it, so if the line is not written the investigation that
    should follow has nothing to start from.
    """
    print(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} autoheal: {msg}", flush=True)


def notify(level, title, body, name, event_id):
    """Surface an event on the platform's own notification centre. Best-effort by design.

    Never raises and never blocks the loop: the notifications app being down must not stop the
    estate from healing itself. The stdout line above is the durable record; this is the one a
    human actually sees — so it is written for that human: Hebrew, the container's name the only
    token in it. The stdout lines stay English; they are the operator's record.

    `source_id` carries a per-event suffix ON PURPOSE. The notifications API dedupes on
    UNIQUE(source, source_id) and an existing row only re-surfaces as unread if `meta.count` grows —
    so a constant source_id would make the SECOND restart of a container silently invisible, which
    is precisely the "silent restart loop" this is here to prevent.
    """
    payload = {
        "source": "autoheal",
        "source_id": f"{name}:{event_id}",
        "title": title,
        "body": body,
        "level": level,
        "meta": {"container": name, "deployment": os.environ.get("DEPLOYMENT_NAME", "")},
    }
    try:
        req = urllib.request.Request(
            NOTIFY_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            if r.status not in (200, 201):
                log(f"notify: unexpected status {r.status}")
    except urllib.error.HTTPError as e:                      # the notifier answered, and refused
        log(f"notify: refused ({e.code}: {e.read().decode('utf-8', 'replace')[:200]}) "
            "- the stdout line above is still the record")
    except Exception as e:                                   # noqa: BLE001 - best effort, never fatal
        log(f"notify: could not post ({e}) - the stdout line above is still the record")


# ── the decision ────────────────────────────────────────────────────────────────────────────────
# A PURE FUNCTION of (observation, history). Pure so that it can be replayed against the observed
# 2026-08-10 incident state in --selftest and shown to restart worker-1 and NOT worker-2, rather
# than that claim resting on someone reading the loop and believing it.
#
# Returns (action, reason) where action is one of:
#   "restart"  — do it
#   "skip"     — nothing wrong, or not yet enough evidence, or too soon
#   "refuse"   — eligible by label but on the hard refusal list (a configuration error, reported)
#   "breaker"  — would restart, but this container has exhausted its budget; escalate instead
def decide(*, service, health, streak, last_restart_at, restarts_in_window, now,
           required_streak=None, cooldown=None, max_restarts=None):
    required_streak = STREAK if required_streak is None else required_streak
    cooldown = COOLDOWN if cooldown is None else cooldown
    max_restarts = MAX_RESTARTS if max_restarts is None else max_restarts

    # `health` is None for a container with no healthcheck, "starting" during start_period, and
    # "healthy"/"unhealthy" thereafter. Only one of those four is actionable, and treating the
    # other three as "not unhealthy" is the whole reason a container without a healthcheck (traefik,
    # glitchtip-worker, supabase-rest, glitchtip-valkey, indox-demo-docs — all verified to have no
    # `State.Health` on 2026-08-10) is untouchable by this service.
    if health != "unhealthy":
        return "skip", f"health={health!r}"

    for pat in NEVER_RESTART:
        if pat in service:
            return "refuse", (
                f"service name matches the hard refusal list entry {pat!r}. It is labelled "
                f"{LABEL}=true, which is a configuration error: this class of service is never "
                f"restarted automatically (a database restart forces WAL crash-recovery — measured "
                f"109s of redo and ~2min of estate-wide unavailability)."
            )

    if streak < required_streak:
        return "skip", f"unhealthy but only {streak}/{required_streak} consecutive observations"

    if last_restart_at and (now - last_restart_at) < cooldown:
        return "skip", (f"cooling down — restarted {int(now - last_restart_at)}s ago, "
                        f"cooldown is {int(cooldown)}s")

    if restarts_in_window >= max_restarts:
        return "breaker", (
            f"{restarts_in_window} restarts already in the last {int(WINDOW / 3600)}h and it is "
            f"STILL unhealthy. Restarting is evidently not the fix. Not restarting again — this "
            f"needs a human."
        )

    return "restart", f"unhealthy for {streak} consecutive checks ({int(streak * INTERVAL)}s)"


# ── the reviver: a container Docker gave up on (DGO-1163) ─────────────────────────────────────────
# MacBook, 2026-11-02 16:16Z: authentik-server crashed (exit 2), Docker's restart of it failed on a
# containerd timeout under load, and Docker does not try again after a restart that errored. It sat
# `Exited (2)` under `restart: unless-stopped` for 43 minutes; the console, sign-in and the LAN door
# answered 404/500 and nothing told anyone (issues/sign-in-server-crashed-under-load-and-docker-
# never-restarted-it.yaml). The restart policy is the declaration — «this should run» — and this
# finishes what Docker started: it STARTS such a container, nothing else. It never stops, kills or
# restarts a running one.
#
# WHICH ONES, by one fact Docker keeps. Under `unless-stopped`/`always` Docker's own restart manager
# restarts every crash; while it backs off the container is `restarting`, never `exited`. So a container
# still `exited` past a grace is one of two: STOPPED ON PURPOSE (a person, `compose stop`, a bbox verb,
# app-management) — Docker leaves no error — or ONE DOCKER COULD NOT START, which Docker records in
# State.Error (the incident: «could not load stale containerd task object: DeadlineExceeded»). Only the
# second is started. A successful start clears State.Error, so a stop after it never carries one.
# (Reading Docker's events to tell a stop from a crash was the first cut: the order differs by
# version — Docker 28 sends kill → stop → die — the daemon keeps only its last 256 events, and a
# reload signal is a kill that stops nothing; each of those could start a container a person had
# stopped. One field Docker sets itself has none of those holes.)
REVIVE_POLICIES = ("always", "unless-stopped")
REVIVE_GRACE = float(os.environ.get("AUTOHEAL_REVIVE_GRACE", "90"))       # Docker's own restart loop first
REVIVE_BACKOFF = float(os.environ.get("AUTOHEAL_REVIVE_BACKOFF", "60"))   # 60, 120, 240 … between starts
REVIVE_MAX = int(os.environ.get("AUTOHEAL_REVIVE_MAX", "4"))              # per WINDOW, then a person
REVIVE_OFF = os.environ.get("AUTOHEAL_REVIVE_LABEL", "binaos.autoheal.revive")   # =false: never revived


def decide_revive(*, policy, engine_error, finished_ago, starts, now,
                  opted_out=False, grace=None, backoff=None, max_starts=None):
    """A PURE FUNCTION, as decide(): (action, reason) for one exited container. `engine_error` is its
    State.Error (Docker failed to start it); `starts` are this service's earlier starts of it within
    WINDOW. Actions: "start", "skip", "breaker"."""
    grace = REVIVE_GRACE if grace is None else grace
    backoff = REVIVE_BACKOFF if backoff is None else backoff
    max_starts = REVIVE_MAX if max_starts is None else max_starts
    if opted_out:
        return "skip", f"{REVIVE_OFF}=false"
    if policy not in REVIVE_POLICIES:
        return "skip", f"restart policy {policy or 'no'!r}: not declared to keep running"
    if not engine_error:
        return "skip", "exited with no engine error: stopped on purpose (Docker restarts every crash itself)"
    if finished_ago < grace:
        return "skip", f"exited {int(finished_ago)}s ago: Docker's own restart gets {int(grace)}s first"
    if len(starts) >= max_starts:
        return "breaker", (f"started {len(starts)} times in the last {int(WINDOW / 3600)}h and it fell "
                           f"again: starting is not the fix")
    wait = backoff * (2 ** len(starts))
    if starts and now - starts[-1] < wait:
        return "skip", f"backing off: started {int(now - starts[-1])}s ago, next after {int(wait)}s"
    return "start", (f"Docker could not start it ({engine_error[:120]}), {policy}, exited "
                     f"{int(finished_ago)}s ago")


def exited_here(project):
    """This deployment's exited containers, one filtered list (None: the daemon did not answer)."""
    flt = json.dumps({"status": ["exited"], "label": [f"com.docker.compose.project={project}"]})
    status, rows = _docker("GET", f"/containers/json?all=1&filters={urllib.parse.quote(flt)}")
    return rows if status == 200 and rows is not None else None


def start(cid):
    status, _ = _docker("POST", f"/containers/{cid}/start", timeout=60)
    return status in (204, 304)


def _ago(iso, now):
    """Seconds since a Docker timestamp (2026-11-02T16:16:50.123456789Z)."""
    try:
        return max(0.0, now - calendar.timegm(time.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S")))
    except (TypeError, ValueError):
        return 0.0


def revive_cycle(project, st):
    """One cycle of the reviver: start what decide_revive says to, telling the owner each time. A daemon
    that does not answer changes nothing."""
    now = time.time()
    rows = exited_here(project)
    if rows is None:
        return
    me = f"autoheal-{os.environ.get('DEPLOYMENT_NAME') or 'bina-deployment'}"
    for row in rows:
        name = (row.get("Names") or ["/?"])[0].lstrip("/")
        if name == me:
            continue
        data = inspect(row.get("Id")) or {}
        s = data.get("State") or {}
        if s.get("Status") != "exited":
            continue
        labels = (data.get("Config") or {}).get("Labels") or {}
        starts = [t for t in st["starts"].get(name, []) if now - t < WINDOW]
        st["starts"][name] = starts
        action, reason = decide_revive(
            policy=((data.get("HostConfig") or {}).get("RestartPolicy") or {}).get("Name") or "",
            engine_error=str(s.get("Error") or ""), finished_ago=_ago(s.get("FinishedAt"), now),
            starts=starts, now=now,
            opted_out=str(labels.get(REVIVE_OFF, "")).lower() == "false")
        if action == "breaker":
            key = f"{name}/revive/{len(starts)}"
            if key not in st["told"]:
                st["told"].add(key)
                log(f"REVIVE BREAKER {name}: {reason}")
                notify("error", f"{name} נופל שוב ושוב",
                       f"הוא הופעל {len(starts)} פעמים ב-{int(WINDOW / 3600)} השעות האחרונות ונפל שוב. "
                       f"הוא לא יופעל עוד אוטומטית — צריך שמישהו יסתכל.\n\nהשגיאה האחרונה: "
                       f"{s.get('Error') or 'קוד יציאה ' + str(s.get('ExitCode'))}",
                       name, f"revive-breaker:{int(now)}")
            continue
        if action != "start":
            continue
        down = int(_ago(s.get("FinishedAt"), now) / 60)
        why = f"קוד יציאה {s.get('ExitCode')}; דוקר לא הצליח להפעיל אותו: {s.get('Error')}"
        if DRY_RUN:
            log(f"DRY RUN would start {name}: {reason}")
            continue
        log(f"STARTING {name}: {reason}")
        ok = start(row.get("Id"))
        st["starts"][name] = starts + [now]
        if ok:
            log(f"started {name} ({len(starts) + 1} start(s) in the last {int(WINDOW / 3600)}h)")
            notify("warning", f"{name} נפל והופעל מחדש",
                   f"הוא נפל ({why}) ודוקר לא הקים אותו שוב; הוא היה למטה {down} דקות. "
                   f"הלשכה הפעילה אותו (הפעלה {len(starts) + 1} מתוך {REVIVE_MAX} המותרות ב-"
                   f"{int(WINDOW / 3600)} שעות).",
                   name, f"revive:{int(now)}")
        else:
            log(f"FAILED to start {name} — docker refused the request")
            notify("error", f"ההפעלה של {name} נכשלה",
                   f"הוא נפל ({why}) לפני {down} דקות, ומנוע המכולות סירב להפעיל אותו. ניסיון נוסף "
                   f"אחרי ההמתנה.", name, f"revive-failed:{int(now)}")


# ── the overdue one-off (DGO-1231) ───────────────────────────────────────────────────────────────
# A container somebody ran BY HAND (`docker run`, not compose) that declares no restart is a one-off
# job. One that is still running long after any job should have ended is a leak, and nothing else in
# the office ever looks at it. Measured on The Fireplace Guys' server, 2026-11-02: a WebGL probe run
# under `timeout 150 docker run …` ran 8 hours at a full core (its PID 1, python3, ignores the
# SIGTERM `timeout` sends; there was no --init), and a `meet verify --call` box (`sleep infinity`)
# had outlived its run by 93 hours. On a 2-vCPU server the provider then throttled the whole office
# (69% CPU steal) and n8n's task runner fell into a restart loop.
#
# So: a running container with no compose container number (hand-run, and not a `compose run` job),
# restart policy no, running longer than its own `binaos.max-age` label (seconds) or ONEOFF_MAX_AGE,
# is STOPPED (10 s grace) and the owner is told — but only when it is plainly this office's: its
# (image-inherited) compose project is this office's (the hung probe ran this office's browser42
# image), or it OPTED IN with a `binaos.max-age` label (verify_call's box does). Any other overdue one
# with no project — a client's own `docker run -d` service, a CI runner, a devcontainer — is only
# REPORTED, once: the engine may hold things that are not the office's to stop. Another office's
# project is not this office's to report (own_project(), DGO-428). `binaos.keep=true` keeps one. The
# verbs here stay narrow: this adds `stop`, for these containers only, to restart and the reviver's start.
ONEOFF_MAX_AGE = float(os.environ.get("AUTOHEAL_ONEOFF_MAX_AGE", "21600"))   # 6 h
ONEOFF_EVERY = float(os.environ.get("AUTOHEAL_ONEOFF_EVERY", "300"))         # a look every 5 min
ONEOFF_AGE_LABEL = "binaos.max-age"
ONEOFF_KEEP_LABEL = "binaos.keep"


def decide_overdue(*, compose_made, policy, running_for, labels, project, own_project, max_age=None):
    """A PURE FUNCTION, as decide(): (action, reason) for one RUNNING container. Actions: "stop",
    "report" (overdue, but nothing says it is this office's), "skip"."""
    max_age = ONEOFF_MAX_AGE if max_age is None else max_age
    if compose_made or str(labels.get("com.docker.compose.oneoff", "")).lower() == "true":
        return "skip", "made by compose (a service, or a `compose run` job)"
    if (policy or "no") != "no":
        return "skip", f"restart policy {policy!r}: declared to keep running"
    if str(labels.get(ONEOFF_KEEP_LABEL, "")).lower() == "true":
        return "skip", f"{ONEOFF_KEEP_LABEL}=true"
    if project and project != own_project:
        return "skip", f"of project {project!r}: not this office's"
    try:
        limit = float(labels.get(ONEOFF_AGE_LABEL) or max_age)
    except ValueError:
        limit = max_age
    if not limit > 0:                                            # 0, negative, nan: the default
        limit = max_age
    if running_for < limit:
        return "skip", f"running {int(running_for)}s of its {int(limit)}s"
    over = f"a hand-run one-off, running {running_for / 3600:.1f} h (limit {limit / 3600:.1f} h)"
    if project == own_project or labels.get(ONEOFF_AGE_LABEL):
        return "stop", over
    return "report", over + ", with no project and no binaos.max-age: nothing says it is this office's"


def overdue_cycle(project, st):
    """One look for overdue one-offs, every ONEOFF_EVERY seconds. A daemon that does not answer changes
    nothing."""
    now = time.time()
    if now < st.get("next", 0):
        return
    st["next"] = now + ONEOFF_EVERY
    flt = json.dumps({"status": ["running"]})
    status, rows = _docker("GET", f"/containers/json?filters={urllib.parse.quote(flt)}")
    if status != 200 or rows is None:
        return
    for row in rows:
        labels = row.get("Labels") or {}
        if labels.get("com.docker.compose.container-number"):
            continue
        data = inspect(row.get("Id")) or {}
        name = (data.get("Name") or "/?").lstrip("/")
        started = (data.get("State") or {}).get("StartedAt")
        action, reason = decide_overdue(
            compose_made=False,
            policy=((data.get("HostConfig") or {}).get("RestartPolicy") or {}).get("Name") or "",
            running_for=_ago(started, now),
            labels=(data.get("Config") or {}).get("Labels") or {},
            project=labels.get("com.docker.compose.project") or "", own_project=project)
        key = (row.get("Id"), started)                            # a container started again is looked at again
        if action == "skip" or key in st["told"]:
            continue
        what = f"{data.get('Config', {}).get('Image')} {json.dumps(data.get('Path'))} {json.dumps(data.get('Args'))[:200]}"
        if action == "report" or DRY_RUN:
            st["told"].add(key)
            log(f"{'DRY RUN would stop' if action == 'stop' else 'OVERDUE (not ours to stop)'} {name}: {reason} :: {what}")
            notify("warning", f"{name} רץ ביד כבר יותר מדי זמן",
                   f"מכולה שהופעלה ביד (לא חלק מהלשכה), {reason}. היא לא נעצרה מכאן.\n\n{what}",
                   name, f"oneoff-report:{row.get('Id', '')[:12]}")
            continue
        status, _ = _docker("POST", f"/containers/{row.get('Id')}/stop?t=10", timeout=40)
        ok = status in (204, 304)
        if ok:
            st["told"].add(key)                                   # a failed stop is tried again next look
        log(f"{'STOPPED' if ok else 'FAILED to stop'} {name}: {reason} :: {what}")
        notify("warning" if ok else "error", f"{name} נעצר: עבודה חד-פעמית שלא הסתיימה",
               f"מכולה שהופעלה ביד, {reason}. {'היא נעצרה' if ok else 'מנוע המכולות סירב לעצור אותה'}"
               f" כדי שלא תצרוך את המעבד של הלשכה.\n\n{what}\n\nתווית {ONEOFF_KEEP_LABEL}=true משאירה מכולה כזו, "
               f"ו-{ONEOFF_AGE_LABEL}=<שניות> נותנת לה זמן אחר.",
               name, f"oneoff-stop:{row.get('Id', '')[:12]}")


# ── on demand (DGO-1270): an app that runs only while it is used ──────────────────────────────────
# The compiler labels the service of a `routing.on_demand` route with its idle window in seconds
# (IDLE_LABEL), and gives its address to the waker (app-management) while it is stopped, so opening it
# starts it again. This stops it once its network has been quiet for that window: every IDLE_EVERY the
# container's own counters (rx + tx, every interface) are read, and a look in which it moved less than
# IDLE_BYTES is a quiet one. Measured on The Fireplace Guys' CAD desktop, 2026-11-03: ~336 bytes a minute
# with nobody connected, megabytes a minute while a person has it open — its health probe runs on its own
# loopback and is not counted. The clock starts at the first look (a restarted autoheal gives a full
# window again), and a container whose counters went back (it was restarted) is in use. Only this
# office's containers; the verb is the `stop` this service already has for overdue one-offs.
IDLE_LABEL = "binaos.on-demand.idle"
IDLE_APP_LABEL = "binaos.on-demand.app"          # the app the waker's header names for this container
WAKE_HEADER_LABEL = ".headers.customrequestheaders.X-Dgo-Wake"
IDLE_EVERY = float(os.environ.get("AUTOHEAL_IDLE_EVERY", "300"))           # a look every 5 min
IDLE_BYTES = int(os.environ.get("AUTOHEAL_IDLE_BYTES", str(64 * 1024)))   # under this per look is quiet


def decide_idle(*, window, quiet_for, moved, wakeable=True, threshold=None):
    """A PURE FUNCTION, as decide(): (action, reason) for one RUNNING on-demand container. `moved` is
    what its network moved since the last look (None: no earlier look); `quiet_for` how long it has
    been under the threshold; `wakeable` whether a running container of this office carries its wake
    route (the waker is recreated by a render + up, not when an app is switched on from the screen, and
    a stopped app nothing answers for is a bare 404). Actions: "stop", "skip"."""
    threshold = IDLE_BYTES if threshold is None else threshold
    if not window > 0:                                           # 0, negative, nan: not on demand
        return "skip", "no idle window"
    if not wakeable:
        return "skip", "no running container carries its wake route yet: stopped, nothing would answer for it"
    if moved is None:
        return "skip", "first look: the clock starts now"
    if moved >= threshold:
        return "skip", f"in use: {moved} bytes since the last look"
    if quiet_for < window:
        return "skip", f"quiet {int(quiet_for)}s of its {int(window)}s"
    return "stop", (f"on demand, and its network quiet for {quiet_for / 60:.0f} min "
                    f"(its window is {window / 60:.0f} min)")


def network_bytes(cid):
    """rx + tx of every interface of a running container, from one stats reading. None: no answer, or a
    container with no network of its own (host, service: or container: mode) — whose use cannot be seen,
    so it is never called quiet."""
    status, stats = _docker("GET", f"/containers/{cid}/stats?stream=false&one-shot=true", timeout=20)
    if status != 200 or not isinstance(stats, dict) or not stats.get("networks"):
        return None
    return sum(int(n.get("rx_bytes") or 0) + int(n.get("tx_bytes") or 0)
               for n in stats["networks"].values())


def wake_routes(project):
    """The apps a running container of this office carries a wake route for (the X-Dgo-Wake header
    middleware the compiler puts on the waker), or None when the daemon does not answer."""
    flt = json.dumps({"status": ["running"], "label": [f"com.docker.compose.project={project}"]})
    status, rows = _docker("GET", f"/containers/json?filters={urllib.parse.quote(flt)}")
    if status != 200 or rows is None:
        return None
    return {v for r in rows for k, v in (r.get("Labels") or {}).items()
            if k.startswith("traefik.http.middlewares.") and k.endswith(WAKE_HEADER_LABEL)}


def idle_cycle(project, st):
    """One look at this office's running on-demand containers, every IDLE_EVERY seconds. A daemon that
    does not answer changes nothing."""
    now = time.time()
    if now < st.get("next", 0):
        return
    st["next"] = now + IDLE_EVERY
    flt = json.dumps({"status": ["running"], "label": [IDLE_LABEL, f"com.docker.compose.project={project}"]})
    status, rows = _docker("GET", f"/containers/json?filters={urllib.parse.quote(flt)}")
    if status != 200 or rows is None:
        return
    woken = wake_routes(project) if rows else set()
    if woken is None:
        return
    seen = set()
    for row in rows:
        cid = row.get("Id")
        name = (row.get("Names") or ["/?"])[0].lstrip("/")
        total = network_bytes(cid)
        if total is None:
            continue
        seen.add(cid)
        try:
            window = float((row.get("Labels") or {}).get(IDLE_LABEL) or 0)
        except ValueError:
            window = 0.0
        last = st["seen"].get(cid)
        if last is None:
            log(f"on demand: {name} — stopped once its network has been quiet for {window / 60:.0f} min")
        moved = None if last is None else (total - last["bytes"] if total >= last["bytes"] else IDLE_BYTES)
        if moved is None or moved >= IDLE_BYTES:
            last = st["seen"][cid] = {"bytes": total, "quiet_since": now}
        last["bytes"] = total
        action, reason = decide_idle(window=window, quiet_for=now - last["quiet_since"], moved=moved,
                                     wakeable=(row.get("Labels") or {}).get(IDLE_APP_LABEL) in woken)
        if action != "stop":
            continue
        if DRY_RUN:
            log(f"DRY RUN would stop {name}: {reason}")
            continue
        status, _ = _docker("POST", f"/containers/{cid}/stop?t=30", timeout=60)
        ok = status in (204, 304)
        log(f"{'ASLEEP' if ok else 'FAILED to stop'} {name}: {reason} — opening it starts it again")
        if ok:
            st["seen"].pop(cid, None)
    for gone in set(st["seen"]) - seen:
        st["seen"].pop(gone, None)


# ── files left in a RAM-backed /tmp (DGO-1271) ────────────────────────────────────────────────────
# Where the machine's /tmp is a tmpfs (Debian 13 makes it one), every file hand-run work leaves there is
# RAM — and swap, once memory runs short — until systemd-tmpfiles ages it out after 10 days. On The
# Fireplace Guys' server, 2026-11-02, 1,103 MB of it: four `meet verify` runs (689 MB of wav) and 164
# copies of chimney-services from a deploy's preflight (276 MB, a dozen more each day), on a server whose
# swap was full. Nothing saw it. This looks every TMP_EVERY at the machine's /tmp (mounted read-only at
# HOST_TMP): when it is a tmpfs holding more than TMP_LIMIT, the owner is told ONCE per episode, with the
# largest entries — names, sizes and ages, never contents — and the episode ends when it falls under 80%.
# Nothing is deleted from here: a file on a client's machine is not this service's to remove.
HOST_TMP = os.environ.get("AUTOHEAL_HOST_TMP", "/host-tmp")
TMP_LIMIT = float(os.environ.get("AUTOHEAL_TMP_LIMIT_MB", "512")) * 1024 * 1024
TMP_EVERY = float(os.environ.get("AUTOHEAL_TMP_EVERY", "900"))               # a look every 15 min


def decide_tmp(*, fstype, used, limit, told):
    """A PURE FUNCTION, as decide(): (action, reason) for one look at the machine's /tmp. Actions:
    "report" (tell the owner), "clear" (the episode is over), "skip"."""
    if fstype != "tmpfs":
        return "skip", f"/tmp is {fstype or 'not mounted here'}: on disk, not in memory"
    if used >= limit:
        if told:
            return "skip", "already told in this episode"
        return "report", f"{used / 2 ** 20:.0f} MB of files in a RAM-backed /tmp (the limit is {limit / 2 ** 20:.0f} MB)"
    if told and used < 0.8 * limit:
        return "clear", f"back to {used / 2 ** 20:.0f} MB"
    return "skip", f"{used / 2 ** 20:.0f} MB"


def mount_type(path, mountinfo=None):
    """The filesystem type of the mount at `path`, from /proc/self/mountinfo (None: not a mount point)."""
    if mountinfo is None:
        try:
            with open("/proc/self/mountinfo", encoding="utf-8", errors="replace") as f:
                mountinfo = f.read()
        except OSError:
            return None
    for line in mountinfo.splitlines():
        left, sep, right = line.partition(" - ")
        fields = left.split()
        if sep and len(fields) > 4 and fields[4] == path and right.split():
            return right.split()[0]
    return None


TMP_BUDGET = 200_000                 # entries one look may read: a /tmp of a million files is not walked whole
TMP_GROUPS = 1000                    # distinct name groups kept; the rest are counted together


def _clean(name):
    """A file name as text a notice can carry: undecodable bytes replaced, control characters dropped."""
    text = name.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
    return "".join(ch for ch in text if ch.isprintable())[:60]


def tmp_group(name):
    """The name a leftover is reported under: its words up to the first with a digit in it, the random or
    dated tail of mktemp and of a run's stamp ("chimney-r2-4J0yHQ" → "chimney", "meet-verify-47ilv6ic" →
    "meet-verify"). Many copies are one line, and a file's own name is said only when it has no tail."""
    words = re.split(r"[-_.]", _clean(name))
    kept = [w for w in itertools.takewhile(lambda w: not any(c.isdigit() for c in w), words[1:])]
    return "-".join([words[0]] + kept) if words and words[0] else _clean(name)


def tree_blocks(top, dev, budget, links):
    """Bytes really held (st_blocks) under `top`, on device `dev` only (a mount under /tmp is not /tmp), each
    hard-linked inode once, reading at most budget[0] entries — streamed, never a directory listed whole."""
    try:
        st = os.lstat(top)
    except OSError:
        return 0
    if st.st_dev != dev:
        return 0
    if not stat.S_ISDIR(st.st_mode):
        return st.st_blocks * 512
    total, stack = 0, [top]
    while stack and budget[0] > 0:
        try:
            it = os.scandir(stack.pop())
        except OSError:
            continue
        with it:
            for e in it:
                budget[0] -= 1
                if budget[0] <= 0:
                    break
                try:
                    s = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                if s.st_dev != dev:
                    continue
                if stat.S_ISDIR(s.st_mode):
                    stack.append(e.path)
                    continue
                if s.st_nlink > 1:
                    if (s.st_dev, s.st_ino) in links:
                        continue
                    links.add((s.st_dev, s.st_ino))
                total += s.st_blocks * 512
    return total


def largest_in(path, now, n=5):
    """([(bytes, group, count, age of its oldest in seconds)] — the `n` largest groups of `path`'s top-level
    entries — and whether every entry was read)."""
    try:
        dev = os.stat(path).st_dev
        it = os.scandir(path)
    except OSError:
        return [], True
    budget, links, groups = [TMP_BUDGET], set(), {}
    with it:
        for e in it:
            if budget[0] <= 0:
                break
            budget[0] -= 1
            try:
                age = max(0.0, now - e.stat(follow_symlinks=False).st_mtime)
            except OSError:
                continue
            key = tmp_group(e.name)
            if key not in groups and len(groups) >= TMP_GROUPS:
                key = "…"
            g = groups.setdefault(key, [0, 0, 0.0])
            g[0] += tree_blocks(e.path, dev, budget, links)
            g[1] += 1
            g[2] = max(g[2], age)
    top = heapq.nlargest(n, ((b, k, c, a) for k, (b, c, a) in groups.items()))
    return top, budget[0] > 0


def tmp_cycle(st):
    """One look at the machine's /tmp, every TMP_EVERY seconds."""
    now = time.time()
    if now < st.get("next", 0):
        return
    st["next"] = now + TMP_EVERY
    if not os.path.isdir(HOST_TMP):
        return
    fstype, used = mount_type(HOST_TMP), 0
    if fstype == "tmpfs":
        s = os.statvfs(HOST_TMP)
        used = (s.f_blocks - s.f_bfree) * s.f_frsize
    action, reason = decide_tmp(fstype=fstype, used=used, limit=TMP_LIMIT, told=st.get("told", False))
    if action == "clear":
        st["told"] = False
        log(f"/tmp {reason}: the episode is over")
        return
    if action != "report":
        return
    big, whole = largest_in(HOST_TMP, now)
    at_least = "" if whole else "לפחות "

    def line(size, group, count, age):
        many = f"{count} פריטים" if count > 1 else "פריט אחד"
        return f"• {group}{'*' if count > 1 else ''} — {many}, {at_least}{size / 2 ** 20:.0f} MB, הישן לפני {age / 86400:.1f} ימים"
    log(f"TMP {reason} :: " + ", ".join(f"{g} x{c} {s / 2 ** 20:.0f} MB" for s, g, c, _a in big))
    notify("warning", f"קבצים ב-/tmp תופסים {used / 2 ** 20:.0f} MB מהזיכרון",
           "ה-/tmp של המחשב הזה הוא זיכרון (tmpfs), ומה שעבודה שהורצה ביד משאירה בו תופס זיכרון ו-swap עד "
           "שהוא מתנקה לבד אחרי 10 ימים. כלום לא נמחק מכאן. הגדולים:\n" + "\n".join(line(*g) for g in big),
           "tmp", f"tmp-ram:{int(now)}")
    st["told"] = True


def watch_step(since, noticed, unhealthy_now, now, after=None):
    """One cycle of the notice-only watch — a PURE FUNCTION of (state, observation), like decide().

    `since` maps a container to when its current unbroken run of `unhealthy` was first seen;
    `noticed` holds the ones already reported in that run. Returns (since, noticed, due, recovered):
    `due` are reported now, once per episode; `recovered` had been reported and are unhealthy no
    longer. One reading that is not `unhealthy` ends the episode and restarts the clock.
    """
    after = WATCH_AFTER if after is None else after
    since = {name: since.get(name, now) for name in unhealthy_now}
    due = sorted(n for n, first in since.items() if now - first >= after and n not in noticed)
    return since, (noticed & set(since)) | set(due), due, sorted(noticed - set(since))


# ── the loop ────────────────────────────────────────────────────────────────────────────────────
def opted_in(project):
    """The Docker list filter for what this service may restart: running, labelled, and IN THIS
    COMPOSE PROJECT. Label filters AND together, and the project one is not optional.

    IT USED TO BE. With the deployment unknown — the container renamed, DEPLOYMENT_NAME changed, a
    hand-started instance, an inspect that failed once — the filter fell back to the bare label and
    this service could restart a NEIGHBOUR OFFICE's containers on an engine carrying two stacks
    (DGO-428). The old line called that "as it always did"; it is not a scope at all, it is the
    absence of one, and a restart it performs lands in somebody else's office. So: no project, no
    list. `own_project()` is asked once at start and a cycle without an answer refuses to act."""
    if not project:
        raise ValueError("no compose project: this service will not act on an engine it cannot scope")
    return {"label": [f"{LABEL}=true", f"com.docker.compose.project={project}"],
            "status": ["running"]}


def eligible_containers(project=None, attempts=3):
    """Running containers that opted in. Filtering server-side keeps the blast radius visible.

    RETRIES, because a single timeout used to blind the watchdog for a whole cycle. Observed
    2026-08-10 at 21:10:31 and again at 22:25:57: `GET /containers/json ... failed: timed out`
    followed by "no action taken this cycle". Both moments were exactly when supervision matters
    most — the daemon was under load, and the second one was seconds after a full daemon restart.
    A watchdog that stands down precisely when the machine is struggling is not a watchdog.
    Short backoff only; the caller still treats a total failure as unreachable.
    """
    flt = json.dumps(opted_in(project))
    for attempt in range(1, attempts + 1):
        status, rows = _docker("GET", f"/containers/json?filters={urllib.parse.quote(flt)}")
        if status == 200 and rows is not None:
            return rows
        if attempt < attempts:
            time.sleep(min(2.0 * attempt, 5.0))
    return None                           # daemon unreachable: distinct from "nothing eligible"


def inspect(cid):
    status, data = _docker("GET", f"/containers/{cid}/json")
    if status != 200 or not data:
        return None
    return data


def restart(cid):
    status, _ = _docker("POST", f"/containers/{cid}/restart?t={RESTART_TIMEOUT}",
                        timeout=RESTART_TIMEOUT + 30)
    return status in (204, 304)


def own_project():
    """The compose project this service runs in — the edge of what it may speak about. An engine can
    carry a neighbour's stack, and that stack's containers are not this deployment's to report."""
    data = inspect(f"autoheal-{os.environ.get('DEPLOYMENT_NAME') or 'bina-deployment'}") or {}
    return ((data.get("Config") or {}).get("Labels") or {}).get("com.docker.compose.project")


def unhealthy_here(project):
    """This deployment's running containers that Docker calls `unhealthy` right now, as one filtered
    list. None when the daemon did not answer — which is not "none of them is"."""
    flt = json.dumps({"health": ["unhealthy"], "status": ["running"],
                      "label": [f"com.docker.compose.project={project}"]})
    status, rows = _docker("GET", f"/containers/json?filters={urllib.parse.quote(flt)}")
    return rows if status == 200 and rows is not None else None


def last_probe(data):
    """The last line a container's own healthcheck printed — what a person needs first."""
    probe = ((data.get("State") or {}).get("Health") or {}).get("Log") or []
    out = (probe[-1].get("Output") or "").strip().splitlines()[-1:] if probe else []
    return out[0] if out else "(no probe output)"


def _heartbeat(watching, refused=""):
    """Written only after a cycle COMPLETED — a heartbeat written at the top of the loop would keep
    ticking while the body was stuck, which is exactly the mistake worker-liveness.sh made when it
    trusted a log file's mtime. `refused` names the scope this service refused to act in, so a
    heartbeat is never read as "nothing to do"."""
    try:
        with open(HEARTBEAT, "w", encoding="utf-8") as fh:
            fh.write(f"{int(time.time())} watching={watching}" + (f" refused={refused}" if refused else "") + "\n")
    except OSError as e:
        log(f"could not write heartbeat: {e}")


def main():
    log(f"starting — label={LABEL}=true interval={INTERVAL}s streak={STREAK} "
        f"cooldown={int(COOLDOWN)}s max_restarts={MAX_RESTARTS}/{int(WINDOW / 3600)}h "
        f"dry_run={DRY_RUN}")
    log(f"never restarts services matching: {', '.join(NEVER_RESTART)}")

    project = own_project()
    if not project:
        # FAIL CLOSED (DGO-428). The scope of this service is its compose project; an engine can
        # carry a neighbour office's stack, and without a project there is no way to tell the two
        # apart — so it acts on NOTHING and says so, once here and once a minute after that. The
        # container stays healthy on purpose: its heartbeat is how a person sees that the watchdog
        # is up while its scope is not, and an unhealthy supervisor would be restarted by nothing
        # (it carries no autoheal label itself).
        log("REFUSING TO ACT: cannot tell which compose project this is — no container named "
            f"autoheal-{os.environ.get('DEPLOYMENT_NAME') or 'bina-deployment'} carrying a "
            "com.docker.compose.project label. An engine can carry another office's stack "
            "(DGO-428), so no container will be restarted and none will be reported until this "
            "answers. Set DEPLOYMENT_NAME to this office's deployment name, or start this service "
            "from its compose file.")
        while True:
            _heartbeat(0, refused="no-project")
            notify("error", "הריפוי העצמי לא פועל — הפרויקט שלו לא ידוע",
                   "השירות אינו יודע איזו לשכה הוא משרת, ולכן אינו מפעיל מחדש ואינו מדווח על אף "
                   "מכולה: במנוע אחד יכולות לשבת שתי לשכות, ופעולה על מכולה של השכן היא נזק אמיתי. "
                   f"כדי לסדר: לוודא ש-DEPLOYMENT_NAME מתאים לשם הלשכה "
                   f"({os.environ.get('DEPLOYMENT_NAME') or 'bina-deployment'}) ולקום מהקומפוז שלה.",
                   "autoheal", f"no-project:{int(time.time())}")
            time.sleep(60)
    log(f"this deployment is compose project {project!r}: restarting only its labelled "
        f"containers, and reporting (never restarting) any of its containers held unhealthy "
        f"for {int(WATCH_AFTER)}s")

    streaks = {}          # name -> consecutive unhealthy observations
    since, noticed = {}, set()   # the notice-only watch: first seen unhealthy / already reported
    history = {}          # name -> [restart timestamps]
    refused = set()       # name -> already reported (a config error is reported once, not forever)
    blind = 0             # consecutive cycles with no view of the daemon
    revive = {"starts": {}, "told": set()}     # the reviver's starts per container, and breakers told
    overdue = {"next": 0, "told": set()}       # the one-off look: when next, and the ids already acted on
    idle = {"next": 0, "seen": {}}             # the on-demand look: when next, each one's counter and quiet clock
    tmp = {"next": 0, "told": False}           # the /tmp look: when next, and whether this episode was told
    log(f"starting this deployment's containers Docker failed to start (policy "
        f"{'/'.join(REVIVE_POLICIES)}, State.Error set, after {int(REVIVE_GRACE)}s, backoff "
        f"{int(REVIVE_BACKOFF)}s doubling, at most {REVIVE_MAX} starts in {int(WINDOW / 3600)}h)")

    while True:
        rows = eligible_containers(project)
        if rows is None:
            # ESCALATE A SUSTAINED BLACKOUT. A single stdout line was the only trace of this
            # before, so a watchdog that had gone blind looked identical to one with nothing to
            # do. Log every cycle (cheap, and the record matters), but notify once a blackout is
            # sustained — otherwise the failure of the supervisor is itself unsupervised.
            blind += 1
            log(f"docker socket unreachable — no action taken this cycle (consecutive={blind})")
            if blind == 3:
                notify("warning", "אין קשר למנוע המכולות",
                       f"כבר {int(blind * INTERVAL)} שניות המנוע אינו עונה. כל עוד זה נמשך, אף שירות "
                       f"אינו מושגח ואינו מופעל מחדש.",
                       "autoheal", f"blind:{int(time.time())}")
            time.sleep(INTERVAL)
            continue
        if blind:
            log(f"docker socket reachable again after {blind} blind cycle(s)")
            blind = 0

        seen = set()
        for row in rows:
            cid = row.get("Id")
            name = (row.get("Names") or ["/?"])[0].lstrip("/")
            service = (row.get("Labels") or {}).get("com.docker.compose.service", name)
            seen.add(name)

            data = inspect(cid)
            if not data:
                continue
            health = ((data.get("State") or {}).get("Health") or {}).get("Status")

            if health == "unhealthy":
                streaks[name] = streaks.get(name, 0) + 1
            else:
                # Any healthy reading clears the count. A fault must be CONTINUOUS to earn a
                # restart; an intermittent one is a different bug and a restart will not fix it.
                if streaks.get(name):
                    log(f"{name}: recovered on its own after {streaks[name]} unhealthy checks")
                streaks[name] = 0

            now = time.time()
            hist = [t for t in history.get(name, []) if now - t < WINDOW]
            history[name] = hist

            action, reason = decide(
                service=service, health=health, streak=streaks.get(name, 0),
                last_restart_at=hist[-1] if hist else None,
                restarts_in_window=len(hist), now=now,
            )

            # `refused` keys are namespaced by container AND by the state that produced them, so a
            # config error is reported once rather than every 30s, while a container that trips the
            # breaker again at a HIGHER restart count still gets a fresh, louder report.
            if action == "refuse":
                key = f"{name}/refuse"
                if key not in refused:
                    refused.add(key)
                    log(f"REFUSING {name}: {reason}")
                    notify("error", f"{name} לא יופעל מחדש אוטומטית",
                           "הוא סומן להפעלה מחדש אוטומטית, אבל שירות מהסוג הזה (מסד נתונים, קצה הרשת) "
                           "לעולם אינו מופעל כך: הפעלה מחדש של מסד נתונים עולה כשתי דקות שבהן הלשכה "
                           "כולה בלי אחסון. הסימון הוא טעות בהגדרת השירות.",
                           name, f"refuse:{int(now)}")
                continue

            if action == "breaker":
                key = f"{name}/breaker/{len(hist)}"
                if key not in refused:
                    refused.add(key)
                    log(f"CIRCUIT BREAKER {name}: {reason}")
                    notify("error", f"ההפעלה מחדש של {name} לא עוזרת",
                           f"{len(hist)} הפעלות מחדש ב-{int(WINDOW / 3600)} השעות האחרונות, והוא עדיין "
                           f"לא תקין. הוא לא יופעל מחדש שוב — צריך שמישהו יסתכל.",
                           name, f"breaker:{int(now)}")
                continue

            if action != "restart":
                continue

            detail = last_probe(data)
            held = int(streaks.get(name, 0) * INTERVAL)

            if DRY_RUN:
                log(f"DRY RUN would restart {name}: {reason} :: last probe: {detail}")
                continue

            log(f"RESTARTING {name}: {reason} :: last probe: {detail}")
            ok = restart(cid)
            history[name] = hist + [now]
            streaks[name] = 0
            if ok:
                log(f"restarted {name} ({len(history[name])} restart(s) in the last "
                    f"{int(WINDOW / 3600)}h)")
                notify("warning", f"{name} הופעל מחדש אוטומטית",
                       f"הוא היה לא תקין {held} שניות ברציפות.\n\n"
                       f"הפלט האחרון של בדיקת התקינות:\n{detail}\n\n"
                       f"הפעלה מחדש {len(history[name])} מתוך {MAX_RESTARTS} המותרות "
                       f"ב-{int(WINDOW / 3600)} שעות.",
                       name, f"restart:{int(now)}")
            else:
                log(f"FAILED to restart {name} — docker refused the request")
                notify("error", f"ההפעלה מחדש של {name} נכשלה",
                       f"מנוע המכולות סירב לבקשה. הוא לא תקין כבר {held} שניות.",
                       name, f"failed:{int(now)}")

        for gone in set(streaks) - seen:
            streaks.pop(gone, None)

        # THE REST OF THE DEPLOYMENT: a container this service may not restart (it never opted in;
        # one that opted in and is refused has had its own notice above) and that Docker has held
        # unhealthy for WATCH_AFTER. One notice per episode. No verb. A daemon that did not answer
        # leaves the clocks as they are — silence is not a recovery.
        sick = unhealthy_here(project)
        if sick is not None:
            ids = {(r.get("Names") or ["/?"])[0].lstrip("/"): r.get("Id") for r in sick
                   if (r.get("Labels") or {}).get(LABEL) != "true"}
            now = time.time()
            since, noticed, due, recovered = watch_step(since, noticed, set(ids), now)
            for name in recovered:
                log(f"{name}: no longer unhealthy (it had been reported)")
            for name in due:
                mins = int((now - since[name]) / 60)
                detail = last_probe(inspect(ids[name]) or {})
                log(f"UNHEALTHY {name}: for {mins} min, and not restartable from here "
                    f":: last probe: {detail}")
                notify("warning", f"{name} לא תקין כבר {mins} דקות",
                       "הוא אינו מופעל מחדש אוטומטית: לא סומן לכך, או שהוא מסוג שלעולם אינו מופעל "
                       f"כך.\n\nהפלט האחרון של בדיקת התקינות:\n{detail}",
                       name, f"unhealthy:{int(since[name])}")

        try:
            revive_cycle(project, revive)
        except Exception as e:                                   # noqa: BLE001 — the watchdog never dies of it
            log(f"reviver cycle failed ({type(e).__name__}: {e}) — the restart watch goes on")
        try:
            overdue_cycle(project, overdue)
        except Exception as e:                                   # noqa: BLE001 — the watchdog never dies of it
            log(f"one-off cycle failed ({type(e).__name__}: {e}) — the restart watch goes on")
        try:
            idle_cycle(project, idle)
        except Exception as e:                                   # noqa: BLE001 — the watchdog never dies of it
            log(f"on-demand cycle failed ({type(e).__name__}: {e}) — the restart watch goes on")
        try:
            tmp_cycle(tmp)
        except Exception as e:                                   # noqa: BLE001 — the watchdog never dies of it
            log(f"/tmp cycle failed ({type(e).__name__}: {e}) — the restart watch goes on")
        _heartbeat(len(rows))

        time.sleep(INTERVAL)


# ── selftest ────────────────────────────────────────────────────────────────────────────────────
def selftest():
    """Replay the observed 2026-08-10 state through decide(). No docker, no network.

    The point of this test is one specific claim: in the state actually measured that day — where
    BOTH workers reported `unhealthy` but only worker-1 was wedged — this service restarts worker-1
    and does not touch worker-2.
    """
    now = 1_786_388_880.0
    fails = []

    def check(label, got, want):
        ok = got == want
        print(f"  {'PASS' if ok else 'FAIL'}  {label}\n        got={got}\n        want={want}")
        if not ok:
            fails.append(label)

    print("\n=== the observed incident, 2026-08-10 ===")
    # worker-1: genuinely wedged. ZERO `Worker started/finished execution` lines for 2h+, 95.5% CPU,
    # bull:jobs:wait=132, and NONE of bull:jobs:active belonged to it (all 8 were worker-2's), so
    # the liveness probe's MINE=0 < CONCURRENCY=8 and its fingerprint had been frozen for hours.
    # Sustained: Docker had it unhealthy continuously.
    a, r = decide(service="n8n-worker-1", health="unhealthy", streak=3, last_restart_at=None,
                  restarts_in_window=0, now=now)
    check("worker-1 (wedged, unhealthy, sustained) -> RESTART", a, "restart")

    # worker-2: processing normally at 103% CPU, holding all 8 slots. Under the FIXED liveness probe
    # it reads healthy — verified live the same evening at mine=8/8, "progress 0s ago". Docker
    # therefore never marks it unhealthy, and health != "unhealthy" is the first gate.
    a2, r2 = decide(service="n8n-worker-2", health="healthy", streak=0, last_restart_at=None,
                    restarts_in_window=0, now=now)
    check("worker-2 (busy, healthy under fixed probe) -> SKIP", a2, "skip")

    # The dangerous counterfactual, stated as a test rather than a hope: even if a FUTURE sensor bug
    # marks a busy worker unhealthy, a single bad reading still cannot restart it.
    a3, _ = decide(service="n8n-worker-2", health="unhealthy", streak=1, last_restart_at=None,
                   restarts_in_window=0, now=now)
    check("worker-2 (one bad reading from a buggy probe) -> SKIP", a3, "skip")

    print("\n=== the hard refusal list ===")
    for svc in ("n8n-postgres", "supabase-db", "plane-db", "plane-redis", "traefik", "redis"):
        a4, _ = decide(service=svc, health="unhealthy", streak=99, last_restart_at=None,
                       restarts_in_window=0, now=now)
        check(f"{svc} unhealthy forever -> REFUSE", a4, "refuse")

    print("\n=== an app whose worker died under a living master (project-pln, 2026-09-30) ===")
    # Ten hours of `api RUNNING` with nothing bound: the master alive, its one worker gone. The
    # app's own check is strict now (200 from the API or unhealthy), and the app carries the label.
    a8, _ = decide(service="project-pln", health="unhealthy", streak=3, last_restart_at=None,
                   restarts_in_window=0, now=now)
    check("project-pln (API dead, unhealthy, sustained) -> RESTART", a8, "restart")
    a9, _ = decide(service="project-pln", health="starting", streak=0, last_restart_at=now - 1200,
                   restarts_in_window=1, now=now)
    check("project-pln (still booting, 20 min after a restart) -> SKIP", a9, "skip")

    print("\n=== the circuit breaker (what bounds a sensor that is simply wrong) ===")
    a5, _ = decide(service="n8n-worker-1", health="unhealthy", streak=9,
                   last_restart_at=now - 60, restarts_in_window=1, now=now)
    check("restarted 60s ago -> SKIP (cooldown)", a5, "skip")
    a6, _ = decide(service="n8n-worker-1", health="unhealthy", streak=9,
                   last_restart_at=now - 5000, restarts_in_window=3, now=now)
    check("3 restarts in window, still unhealthy -> BREAKER, not restart", a6, "breaker")

    print("\n=== whose containers: this deployment's, when it is known ===")
    check("a known project narrows the list to it",
          opted_in("mydgo")["label"], [f"{LABEL}=true", "com.docker.compose.project=mydgo"])
    # DGO-428: an unknown project is not a wider scope, it is no scope. Pinned as a REFUSAL, so a
    # future edit that "restores the old behaviour" fails here rather than in a neighbour's office.
    try:
        got = opted_in(None)
        check("an unknown project REFUSES (no engine-wide fallback)", got, "ValueError")
    except ValueError:
        check("an unknown project REFUSES (no engine-wide fallback)", "ValueError", "ValueError")
    for empty in ("", 0):
        try:
            opted_in(empty)
            check(f"project {empty!r} REFUSES too", "no raise", "ValueError")
        except ValueError:
            check(f"project {empty!r} REFUSES too", "ValueError", "ValueError")

    print("\n=== a container that may not be restarted: one notice per episode, never a verb ===")
    # The sign-in sentinel, 2026-10-06: `unhealthy` for fifteen hours, two hosts unserved, nobody
    # told. Replayed a minute at a time against the 20-minute threshold.
    def replay(minutes, sick_at):
        s, n, told, back = {}, set(), [], []
        for minute in range(minutes + 1):
            s, n, due, rec = watch_step(s, n, sick_at(minute), minute * 60.0, after=1200)
            told += [(minute, name) for name in due]
            back += [(minute, name) for name in rec]
        return told, back

    check("held unhealthy for an hour -> exactly ONE notice, at minute 20",
          replay(60, lambda m: {"authentik-bootstrap"}), ([(20, "authentik-bootstrap")], []))
    check("a cold start (unhealthy 15 minutes, then fine) -> NO notice",
          replay(60, lambda m: {"authentik-bootstrap"} if m < 15 else set()), ([], []))
    check("a second episode is a second notice, 20 minutes into IT",
          replay(90, lambda m: set() if 25 <= m < 30 else {"n8n-postgres"}),
          ([(20, "n8n-postgres"), (50, "n8n-postgres")], [(25, "n8n-postgres")]))
    check("one reading that is not unhealthy restarts the clock",
          replay(40, lambda m: set() if m == 19 else {"redis"}), ([(40, "redis")], []))
    check("two containers are counted apart",
          replay(30, lambda m: {"a"} | ({"b"} if m >= 5 else set())), ([(20, "a"), (25, "b")], []))

    print("\n=== containers with no healthcheck are unreachable by construction ===")
    for svc in ("glitchtip-worker", "supabase-rest", "indox-demo-docs"):
        a7, _ = decide(service=svc, health=None, streak=0, last_restart_at=None,
                       restarts_in_window=0, now=now)
        check(f"{svc} (no healthcheck, health=None) -> SKIP", a7, "skip")

    print("\n=== the reviver: a crashed container Docker gave up on (DGO-1163) ===")
    # authentik-server, MacBook 2026-11-02 16:16:50Z: exit 2, State.Error «could not load stale containerd
    # task object: DeadlineExceeded», unless-stopped, still exited 42 minutes later.
    err = "could not load stale containerd task object: DeadlineExceeded: context deadline exceeded"
    rv = lambda **k: decide_revive(**{**dict(policy="unless-stopped", engine_error=err,  # noqa: E731
                                              finished_ago=2520, starts=[], now=now), **k})[0]
    check("authentik-server (Docker's start failed, unless-stopped, 42 min) -> START", rv(), "start")
    check("exited with no engine error — a stop on purpose, whatever its code — -> SKIP", rv(engine_error=""), "skip")
    check("restart: no (a one-shot job) -> SKIP even with an engine error", rv(policy="no"), "skip")
    check("exited 30 s ago -> SKIP (Docker's own restart first)", rv(finished_ago=30), "skip")
    check("labelled binaos.autoheal.revive=false -> SKIP", rv(opted_out=True), "skip")
    check("started 70 s ago, fell again -> SKIP (backoff 120 s)", rv(starts=[now - 70]), "skip")
    check("started 200 s ago, fell again -> START (second try)", rv(starts=[now - 200]), "start")
    check("4 starts in the window and down again -> BREAKER", rv(starts=[now - 9000, now - 7000, now - 5000, now - 3000]),
          "breaker")
    check("a Docker timestamp is read as UTC", int(_ago("2026-11-02T16:16:50.123456789Z", 1793636210.0)), 0)

    # The overdue one-off (DGO-1231), from The Fireplace Guys' server on 2026-11-02.
    od = lambda **k: decide_overdue(**{**dict(compose_made=False, policy="no", running_for=8 * 3600,  # noqa: E731
                                              labels={}, project="fireplace", own_project="fireplace",
                                              max_age=6 * 3600), **k})[0]
    check("frosty_mendel (hand-run, this office's browser42 image, 8 h, restart no) -> STOP", od(), "stop")
    check("the old meet-verify box (pulled jibri image, no project, no label, 93 h) -> REPORT only",
          od(project="", running_for=93 * 3600), "report")
    check("a meet-verify box now (binaos.max-age=5400, no project, 93 h) -> STOP",
          od(project="", labels={ONEOFF_AGE_LABEL: "5400"}, running_for=93 * 3600), "stop")
    check("a client's own `docker run -d` service, restart no, no project, a year -> REPORT, never stop",
          od(project="", running_for=8760 * 3600), "report")
    check("a hand-run one-off of ANOTHER office's project -> SKIP (not ours to report)", od(project="staging"), "skip")
    check("a `compose run` job (oneoff=True, no container number), 8 h -> SKIP",
          od(labels={"com.docker.compose.oneoff": "True"}), "skip")
    check("site-fireplace-guys (hand-run, restart unless-stopped) -> SKIP", od(policy="unless-stopped"), "skip")
    check("a compose service, however old -> SKIP", od(compose_made=True, running_for=900 * 3600), "skip")
    check("a 60-minute call test, 70 min in -> SKIP", od(running_for=70 * 60), "skip")
    check("binaos.max-age=36000 at 8 h -> SKIP", od(labels={ONEOFF_AGE_LABEL: "36000"}), "skip")
    check("binaos.max-age=3600 at 2 h -> STOP", od(labels={ONEOFF_AGE_LABEL: "3600"}, running_for=7200), "stop")
    check("binaos.keep=true -> SKIP", od(labels={ONEOFF_KEEP_LABEL: "true"}, running_for=900 * 3600), "skip")
    for bad in ("soon", "0", "-5", "nan"):
        check(f"binaos.max-age={bad} means the default (6 h): at 1 h -> SKIP",
              od(labels={ONEOFF_AGE_LABEL: bad}, running_for=3600), "skip")

    print("\n=== on demand: an app that runs only while it is used (DGO-1270) ===")
    # The CAD desktop on The Fireplace Guys' server, 2026-11-03: ~336 bytes a minute with nobody
    # connected (≈1.7 KB a 5-minute look), megabytes while a person has it open; a 2 h window.
    idl = lambda **k: decide_idle(**{**dict(window=7200, quiet_for=7300, moved=1700,  # noqa: E731
                                            threshold=64 * 1024), **k})[0]
    check("cad, nobody connected, quiet 2 h 2 min (1.7 KB a look) -> STOP", idl(), "stop")
    check("cad, quiet 1 h 50 min -> SKIP", idl(quiet_for=6600), "skip")
    check("cad, a person has it open (3 MB since the last look) -> SKIP", idl(moved=3 << 20), "skip")
    check("the first look at it (no earlier reading) -> SKIP: the clock starts", idl(moved=None), "skip")
    check("exactly the threshold since the last look is use -> SKIP", idl(moved=64 * 1024), "skip")
    for bad in (0, -5, float("nan")):
        check(f"an idle window of {bad} -> SKIP (not on demand)", idl(window=bad), "skip")
    check("quiet 2 h, but no running container carries its wake route -> SKIP (it would be a bare 404)",
          idl(wakeable=False), "skip")

    # The look itself, over a fake engine: its counters, its clock, the waker's routes, and the one verb.
    net, sent, waker = {"bytes": 50_000, "networks": True}, [], {"routes": {"cad"}}

    def engine(method, path, timeout=15.0):
        if path.startswith("/containers/json"):
            if urllib.parse.quote(IDLE_LABEL) in path:
                return 200, [{"Id": "c1", "Names": ["/cad-fireplace"],
                              "Labels": {IDLE_LABEL: "7200", IDLE_APP_LABEL: "cad"}}]
            return 200, [{"Id": "w", "Labels": {f"traefik.http.middlewares.{a}-wake{WAKE_HEADER_LABEL}": a
                                                for a in waker["routes"]}}]
        if "/stats" in path:
            return 200, {"networks": {"eth0": {"rx_bytes": net["bytes"], "tx_bytes": 0}} if net["networks"] else None}
        sent.append(f"{method} {path.split('?')[0]}")
        return 204, None

    def look(st, moved=0, quiet=None):
        net["bytes"] += moved
        if quiet is not None:
            st["seen"]["c1"]["quiet_since"] = time.time() - quiet
        st["next"] = 0
        idle_cycle("fireplace", st)

    real = globals()["_docker"]
    globals()["_docker"] = engine
    try:
        st = {"next": 0, "seen": {}}
        look(st)
        check("the first look starts the clock and sends nothing", sent, [])
        look(st, moved=1700, quiet=7300)
        check("quiet for 2 h 2 min at 1.7 KB a look -> the one stop", sent, ["POST /containers/c1/stop"])
        sent.clear()
        st = {"next": 0, "seen": {}}
        look(st)
        look(st, moved=3 << 20, quiet=7300)
        check("3 MB since the last look is a person on it -> nothing sent, the clock starts again",
              (sent, int(time.time() - st["seen"]["c1"]["quiet_since"])), ([], 0))
        look(st, moved=-(net["bytes"] - 10), quiet=7300)
        check("counters that went back (it was restarted) are use, not quiet -> nothing sent", sent, [])
        st = {"next": 0, "seen": {}}
        waker["routes"] = set()
        look(st)
        look(st, moved=1700, quiet=7300)
        check("quiet 2 h, the waker not recreated since cad was switched on -> nothing sent", sent, [])
        waker["routes"], net["networks"] = {"cad"}, False
        st = {"next": 0, "seen": {}}
        look(st)
        check("a container with no network of its own is never read as quiet -> not even watched",
              (sent, st["seen"]), ([], {}))
    finally:
        globals()["_docker"] = real

    print("\n=== files left in a RAM-backed /tmp (DGO-1271) ===")
    mib = 2 ** 20
    dt = lambda **k: decide_tmp(**{**dict(fstype="tmpfs", used=1103 * mib, limit=512 * mib,  # noqa: E731
                                          told=False), **k})[0]
    check("FPG 2026-11-02: 1,103 MB in a tmpfs /tmp, limit 512 MB -> REPORT", dt(), "report")
    check("the same, already told in this episode -> SKIP (once per episode)", dt(told=True), "skip")
    check("41 MB after the leftovers were moved, told before -> CLEAR", dt(used=41 * mib, told=True), "clear")
    check("450 MB, told before (under the limit, over 80%) -> SKIP (no flapping)", dt(used=450 * mib, told=True), "skip")
    check("/tmp on disk (ext4), 5 GB -> SKIP: it is not memory", dt(fstype="ext4", used=5 << 30), "skip")
    check("/tmp not mounted into this container -> SKIP", dt(fstype=None), "skip")
    info = ("31 25 0:27 / /tmp rw,nosuid shared:13 - tmpfs tmpfs rw,size=4068044k\n"
            "512 498 0:27 / /host-tmp ro,relatime - tmpfs tmpfs rw,size=4068044k\n"
            "513 498 8:1 /var/tmp /var-tmp ro - ext4 /dev/sda1 rw\n")
    check("mountinfo: the host's /tmp bound read-only at /host-tmp is a tmpfs",
          (mount_type("/host-tmp", info), mount_type("/var-tmp", info), mount_type("/nope", info)),
          ("tmpfs", "ext4", None))
    check("a leftover's group: mktemp and run-stamp tails dropped, a plain name kept",
          [tmp_group(n) for n in ("chimney-r2-4J0yHQ", "meet-verify-47ilv6ic", "meet-verify-261030-0118",
                                  "chat81-r2f7oP", "fpg-verify-shots", "r6meet", "bad\nname\udcff")],
          ["chimney", "meet-verify", "meet-verify", "chat81", "fpg-verify-shots", "r6meet", "badname�"])
    import tempfile
    import types
    told, g = [], globals()
    saved = (g["HOST_TMP"], g["mount_type"], g["notify"], g["TMP_LIMIT"], os.statvfs)
    with tempfile.TemporaryDirectory() as d:
        try:
            for name in ("chimney-r2-4J0yHQ", "chimney-r2-cNAQ1S", "chimney-r2-ZcHTT1"):
                os.makedirs(os.path.join(d, name))
                with open(os.path.join(d, name, "app.py"), "wb") as f:
                    f.write(os.urandom(100_000))
            os.makedirs(os.path.join(d, "meet-verify-47ilv6ic", "audio"))
            with open(os.path.join(d, "meet-verify-47ilv6ic", "audio", "host.wav"), "wb") as f:
                f.write(os.urandom(400_000))
            os.link(os.path.join(d, "meet-verify-47ilv6ic", "audio", "host.wav"),
                    os.path.join(d, "meet-verify-47ilv6ic", "audio", "again.wav"))
            with open(os.path.join(d, "sparse"), "wb") as f:
                f.truncate(50 << 20)                                     # 50 MB long, nothing written
            os.symlink("/etc", os.path.join(d, "a-link"))
            big, whole = largest_in(d, time.time())
            mb = {k: round(b / 2 ** 20, 1) for b, k, _c, _a in big}
            check("groups: three chimney copies are one line, a hard link counted once, a sparse file by "
                  "the space it holds, a link never followed",
                  (whole, [k for _b, k, _c, _a in big][:2], {k: c for _b, k, c, _a in big}["chimney"],
                   mb["meet-verify"] < 0.6, mb["sparse"] < 1, mb.get("a-link", 0) < 0.01),
                  (True, ["meet-verify", "chimney"], 3, True, True, True))
            g["HOST_TMP"], g["mount_type"], g["TMP_LIMIT"] = d, (lambda path, mountinfo=None: "tmpfs"), 512 * mib
            g["notify"] = lambda level, title, body, name, event_id: told.append((level, title, body))
            os.statvfs = lambda p: types.SimpleNamespace(f_blocks=1_000_000, f_bfree=1_000_000 - 1103 * 256,
                                                         f_frsize=4096)
            st = {"next": 0, "told": False}
            tmp_cycle(st)
            st["next"] = 0
            tmp_cycle(st)
            check("a 1,103 MB tmpfs /tmp -> one warning, its groups named, not two",
                  (len(told), told[0][0] if told else None, "chimney* — 3 פריטים" in (told[0][2] if told else ""),
                   "1103 MB" in (told[0][1] if told else "")), (1, "warning", True, True))
        finally:
            g["HOST_TMP"], g["mount_type"], g["notify"], g["TMP_LIMIT"], os.statvfs = saved

    print()
    if fails:
        print(f"SELFTEST FAILED: {len(fails)} case(s): {fails}")
        return 1
    print("SELFTEST PASSED — every case above is the documented behaviour.")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    try:
        main()
    except KeyboardInterrupt:
        log("stopping")
