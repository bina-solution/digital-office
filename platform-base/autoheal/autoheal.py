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

import json
import http.client
import os
import socket
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
    except (OSError, ValueError) as e:
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
    """The Docker list filter for what this service may restart: running, labelled, and — when the
    deployment is known — in its compose project. Label filters AND together."""
    return {"label": [f"{LABEL}=true"] + ([f"com.docker.compose.project={project}"] if project else []),
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


def main():
    log(f"starting — label={LABEL}=true interval={INTERVAL}s streak={STREAK} "
        f"cooldown={int(COOLDOWN)}s max_restarts={MAX_RESTARTS}/{int(WINDOW / 3600)}h "
        f"dry_run={DRY_RUN}")
    log(f"never restarts services matching: {', '.join(NEVER_RESTART)}")

    project = own_project()
    if project:
        log(f"this deployment is compose project {project!r}: restarting only its labelled "
            f"containers, and reporting (never restarting) any of its containers held unhealthy "
            f"for {int(WATCH_AFTER)}s")
    else:
        log("cannot tell which deployment this is (no container named autoheal-<DEPLOYMENT_NAME>): "
            "every labelled container on this engine counts as eligible, as it always did, and an "
            "unhealthy container that may not be restarted will NOT be reported")

    streaks = {}          # name -> consecutive unhealthy observations
    since, noticed = {}, set()   # the notice-only watch: first seen unhealthy / already reported
    history = {}          # name -> [restart timestamps]
    refused = set()       # name -> already reported (a config error is reported once, not forever)
    blind = 0             # consecutive cycles with no view of the daemon

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
        sick = unhealthy_here(project) if project else None
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

        # Written only after a cycle COMPLETED — a heartbeat written at the top of the loop would
        # keep ticking while the body was stuck, which is exactly the mistake worker-liveness.sh
        # made when it trusted a log file's mtime.
        try:
            with open(HEARTBEAT, "w", encoding="utf-8") as fh:
                fh.write(f"{int(time.time())} watching={len(rows)}\n")
        except OSError as e:
            log(f"could not write heartbeat: {e}")

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
    check("an unknown one leaves the label alone (the old, engine-wide reading)",
          opted_in(None)["label"], [f"{LABEL}=true"])

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
