#!/usr/bin/env bash
# authentik-bootstrap — configure SSO, then GATE on REAL readiness (not just "rows written").
#
# 1) Apply the deployment blueprint (providers/apps/embedded-outpost) as soon as authentik's
#    first-boot migrations have run. `ak apply_blueprint` exits non-zero until the tables exist
#    (e.g. "relation authentik_core_user does not exist"), then succeeds — so we retry in-process.
#    When every blueprint reads `successful`, say so where the hook can see it (/tmp/applied).
# 2) WAIT until the embedded outpost actually SERVES every gated host (forward-auth ≠ 404). The
#    blueprint writing provider rows is L2; the outpost learns them a moment later (L3) — this waits
#    for L3, which is exactly the gap that 404'd *.localhost right after a reset. WHICH hosts are
#    gated is not computed here: the compiled blueprint states them and outpost-ready.py reads them.
# 3) Stay running as a live SSO-readiness sentinel: the container healthcheck re-runs the probe, so
#    `depends_on: service_healthy` and `docker compose up --wait` gate on TRUE readiness. This is
#    the single source of truth shared by local (`bbox run`/`onboarding`) and CI.
#
# This runs when the container STARTS — a first boot, a `bbox run` after its inputs changed, or
# `hooks/refresh` restarting it because a declared host is not served. It does not run per app:
# the worker applies the compiled blueprint within seconds of every change of that file.
set -uo pipefail

# "The blueprints have been applied by THIS run" is a fact of this run only (a restarted container
# keeps its /tmp). The two files beside it belonged to the probe's earlier ways of knowing which
# hosts are gated; nothing reads them any more.
rm -f /tmp/applied /tmp/outpost-token /tmp/outpost-hosts

# EVERY blueprint in custom/, not just deployment-apps.yaml. The compiler generates
# zz-generated-apps.yaml from each app's OWN `sso:` block — that is how a layer-3 app carries its
# identity config without anything being hand-added to this base app (gate G9). Applying only
# deployment-apps.yaml meant the generated half was written and never loaded: enabling supabase
# from the gallery produced a correct blueprint, a correct route, a healthy container — and a 404,
# because authentik had no application for the slug. Sorted, so zz-* (which !KeyOf-references
# providers declared in deployment-apps.yaml) applies last.
#
# Before applying, CLEAR last_applied_hash on the custom instances. authentik decides whether a
# blueprint needs re-applying by hashing the FILE — but these blueprints resolve hosts through
# `!Env [SOMETHING_BASE_URL, default]`, so their OUTPUT depends on this container's environment,
# which the hash cannot see. Change a host in the env (or in a compose default) and re-deploy: the
# file is byte-identical, authentik skips it, and the proxy provider keeps the OLD external_host
# forever. That is not theoretical — renaming the mail API's host left `Mail-UI Provider` pointing
# at the previous name through a worker restart AND a full container recreate, so traefik forwarded
# to authentik and authentik answered 404 for a host it had never been told about. Re-applying is
# idempotent, so paying it on every boot is cheaper than the failure it prevents.
#
# NOT the compiled one. Its hosts are literals (the compiler resolves them from this office's .env),
# so its output is a function of the file alone and authentik's hash is exactly right about it.
# Clearing that hash too made the worker apply the whole file once more after every start of this
# container — forty-odd objects saved, each one an update the outpost has to work through.
#
# …and the probe's old token goes with it: outpost-ready.py used to ask authentik's API which hosts
# are gated, with a NON-EXPIRING API token of the admin account that this script minted and kept in
# /tmp. The probe reads the compiled blueprint now, so the token is a standing credential nobody
# uses — removed here, on every office that still holds one.
ak shell -c '
from authentik.blueprints.models import BlueprintInstance
from authentik.core.models import Token
n = BlueprintInstance.objects.filter(path__startswith="custom/").exclude(path="custom/zz-generated-apps.yaml").update(last_applied_hash="")
print("cleared last_applied_hash on", n, "committed blueprint(s)")
gone, _ = Token.objects.filter(identifier="outpost-ready-probe").delete()
print("retired probe token(s) removed:", gone)
' 2>/dev/null | grep -E '^(cleared|retired) ' || true

#
# `ak apply_blueprint` EXITS 0 EVEN WHEN THE BLUEPRINT FAILED. On a genuinely fresh database the
# server is still running its first-boot migrations while this runs, so the apply hits
#     relation "authentik_outposts_outpost" does not exist
# authentik records status=error on the instance — and the CLI still returns 0. The loop below then
# printed "all custom blueprints applied (attempt 1)" and moved on, leaving ZERO proxy providers.
# Bootstrap went on to poll an empty gated-host list forever, every *.localhost 404'd, and nothing in
# the logs said "failed". This is the fresh-install path, i.e. exactly what a new company hits.
#
# So success is no longer the CLI's exit code — it is authentik's own stored status for every custom
# instance. blueprints_ok returns non-zero until each one reads `successful`, which turns the retry
# loop into a real retry instead of a formality.
#
# THAT STATUS IS THE WORKER'S WORD, NOT THIS SCRIPT'S. The CLI above applies a blueprint and records
# nothing; the row is written by the worker's own apply task, and the worker starts one such task
# per file-change EVENT — a write is two (truncate, write), so every render of the generated
# blueprint runs two applies of it side by side. They agree until the render ADDS a provider: then
# both insert it, the second waits on the first's commit and fails on the duplicate name, and being
# the one that waited it is also the one that writes last — `error`, over a blueprint that is fully
# applied. Nothing looks at that row again until the worker's hourly scan. Measured on hp-laptop,
# 2026-10-05: an app switched on from the apps screen, both its providers in the database, and this
# loop on attempt 10 of 60 with every gated host answering "could not verify".
#
# So a row that does not read `successful` is settled HERE before it is judged, by running that
# same task in this process: authentik's own apply, alone, recording authentik's own verdict. A
# blueprint that is really refused still reads `error` afterwards and the loop still retries.
blueprints_ok() {
  ak shell -c '
import sys
from authentik.blueprints.models import BlueprintInstance
from authentik.blueprints.v1.tasks import apply_blueprint
qs = BlueprintInstance.objects.filter(path__startswith="custom/")
for b in qs:
    if b.status != "successful":
        apply_blueprint.apply(args=[b.pk.hex])
qs = qs.all()
bad = [(b.path, b.status) for b in qs if b.status != "successful"]
if not qs.exists() or bad:
    for p, s in bad:
        print("blueprint not applied:", p, "status:", s, file=sys.stderr)
    sys.exit(1)
' 2>&1 | grep -v '^{' >&2
  return "${PIPESTATUS[0]}"
}

applied=0
for i in $(seq 1 60); do
  # ABSOLUTE path. This was `ls custom/*.yaml`, and the authentik image's working directory is
  # `/` while the blueprints are bind-mounted at /blueprints/custom — so the glob matched NOTHING,
  # the loop body never ran, and `blueprints_ok` then passed because it only asks whether the
  # blueprint INSTANCES are `successful`, which they were, from a previous deployment. A gate that
  # cannot fail. Nothing was ever applied here; the worker's own periodic scan re-applied later
  # (this script clears last_applied_hash first, which is what made the worker notice), so the
  # apply landed AFTER this script had already computed the gated-host list and declared SSO
  # ready — from the OLD rows. Measured on the 2026-07-29 domain move: every gated host 404'd
  # while the bring-up reported "SSO fully ready".
  #
  # `bps` empty is now a hard error for the same reason: an empty loop must never read as success.
  if bps="$(ls /blueprints/custom/*.yaml 2>/dev/null | sort)" && [ -n "${bps}" ]      && for bp in ${bps}; do
       ak apply_blueprint "${bp}" || exit 1
     done && blueprints_ok; then
    # akadmin's password is set by the worker (AUTHENTIK_BOOTSTRAP_* in its env); set it
    # best-effort here too, once the user exists.
    ak shell -c "from authentik.core.models import User; import os; u=User.objects.filter(username=os.environ.get('AUTHENTIK_BOOTSTRAP_USER','akadmin')).first(); pw=os.environ.get('AUTHENTIK_BOOTSTRAP_PASSWORD',''); [ (u.set_password(pw), u.save()) for _ in [0] if u and pw ]" >/dev/null 2>&1 || true
    echo "all custom blueprints applied (attempt $i)"; applied=1; break
  fi
  echo "authentik not ready yet (attempt $i/60) — retrying in 5s"; sleep 5
done
[ "$applied" = 1 ] || { echo "ERROR: deployment-apps not applied after retries" >&2; exit 1; }
[ -n "${bps:-}" ] || { echo "ERROR: no blueprints found at /blueprints/custom/*.yaml — the bind mount is missing" >&2; exit 1; }

# Every blueprint reads `successful`, by this run. The hook that restarted this container to have
# that done (hooks/refresh, when a declared host is not served) waits on this file and on nothing
# else — the container's health is the outpost's answer, not this script's progress.
: > /tmp/applied

# Wait until the embedded outpost serves every host the compiled blueprint gates (the L2->L3 gap).
#
# AND STAY, WHATEVER THE ANSWER. This used to `exit 1` when the outpost had not come to serve them
# in ten minutes: docker restarted the container, and the container applied every blueprint again
# — each one a full authentik boot in a tenth of a core, an hour under load (MacBook, 2026-09-30) —
# to arrive at the same outpost, which nothing in here can make listen. A remedy that cures nothing
# and costs an hour is a loop. What can act on an outpost that will not learn is the hook, which
# has the engine; what this container owes it is the truth, and its healthcheck keeps telling it.
if python3 /outpost-ready.py --wait; then
  echo "SSO fully ready — embedded outpost serving all gated hosts"
else
  echo "ERROR: the blueprints are applied and the embedded outpost still does not serve every gated host." >&2
  echo "       Staying up and UNHEALTHY (python3 /outpost-ready.py says which); ./bbox authentik refresh acts on it." >&2
fi

# Stay alive as the readiness sentinel; the container healthcheck re-runs /outpost-ready.py so
# `docker ps` / `--wait` reflect live SSO readiness.
exec sleep infinity
