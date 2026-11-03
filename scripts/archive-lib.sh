#!/usr/bin/env bash
# archive-lib.sh — helpers shared by every hooks/backup and hooks/restore.
# Source it AFTER scripts/lib.sh, which provides DN, running, say, die.
#
# ── WHY THIS FILE EXISTS: `cn` IS NOT SAFE FOR A DESTRUCTIVE OPERATION ──────────────────────────
#
# scripts/lib.sh `cn <svc>` resolves a compose service to whatever container docker actually shows,
# and its LAST resort is a regex:
#
#     printf '%s\n' "$names" | grep -E "^${svc}(-[a-z0-9-]+)?$" | head -1
#
# That fallback exists for a good reason — it makes read-only tooling survive deployment-name drift
# between a laptop (`…-local-dev`) and CI (`…-<DN>`). It is exactly wrong for a restore. On a host
# running TWO deployments, `cn supabase-db` from the deployment named `restore-test` finds no
# `supabase-db-restore-test`, no bare `supabase-db`, and then MATCHES `supabase-db-shlomo-laptop` —
# the live one. The next line in a restore hook is `drop database`.
#
# This is not hypothetical: restoring into a second deployment on the same host is the DOCUMENTED
# way to test an archive without touching production, so the dangerous path is the recommended one.
#
# So destructive hooks resolve strictly: `<svc>-${DN}`, present in `docker ps`, or nothing. A hook
# that cannot find its own container must FAIL, never widen its search.
#
# ── AND THE OTHER HALF: A DEPLOYMENT'S CONTAINERS ARE NOT ITS VOLUMES ──────────────────────────
#
# DEPLOYMENT_NAME suffixes CONTAINER names. The compose PROJECT name — the basename of the clone
# directory — prefixes VOLUME names. Two checkouts in directories of the same name share volumes no
# matter how differently DEPLOYMENT_NAME is set. `archive_project` is the one place that is spelled.

# archive_container <service> — "<service>-${DN}" if it is running, else empty + a reason on stderr.
archive_container() {
  local svc="${1:?usage: archive_container <service>}" want="${1}-${DN}"
  if docker ps --format '{{.Names}}' 2>/dev/null | grep -Fxq "${want}"; then
    printf '%s' "${want}"
    return 0
  fi
  echo "[archive-lib] ${want} is not running (deployment '${DN}')." >&2
  return 1
}

# archive_require <service> — the same, but aborts the caller. For hooks that cannot proceed.
archive_require() {
  local c
  c="$(archive_container "$1")" || {
    echo "[archive-lib] refusing to guess which container to use — a destructive hook that widens" >&2
    echo "              its search can find ANOTHER deployment's database on the same host." >&2
    exit 1
  }
  printf '%s' "${c}"
}

# archive_stop <service...> — stop this deployment's containers, and only this deployment's.
archive_stop() {
  local svc c
  for svc in "$@"; do
    c="$(archive_container "${svc}" 2>/dev/null || true)"
    [ -n "${c}" ] && docker stop "${c}" >/dev/null 2>&1 || true
  done
  return 0
}

# archive_project — the compose project name, i.e. the prefix on every named volume.
archive_project() {
  printf '%s' "${COMPOSE_PROJECT_NAME:-$(basename "${REPO_ROOT}" | tr '[:upper:]' '[:lower:]')}"
}

# factq <name> <value> [<relation>] — emit one FACT line; an empty value is the literal `absent` ONLY
# when <relation> is named and the database says it does not exist (`to_regclass`, asked through the
# hook's own `q`). With no relation, or a relation that exists, an empty value stays an empty fact,
# which the archiver refuses: a query that FAILED (quoting, credentials) must never pass as "absent"
# on both sides of a restore (the second reader of DGO-1037).
#
# WHY THIS EXISTS (measured 2026-10-11 on wbc-vps — a deployment that could not be backed up at all)
#
# Every backup hook reaches its database through a helper that sends psql's stderr to /dev/null,
# because an expected table may legitimately not exist yet. The consequence is that a FAILED query
# and an ABSENT relation both come back as an empty string — and `echo "FACT users $(...)"` then
# prints `FACT users `, which scripts/deployment-archive.py refuses BY DESIGN:
#
#     emitted an EMPTY fact: 'FACT credential_blob_sha'. The underlying query failed; a silently
#     missing fact makes the restore diff vacuous.
#
# That refusal is correct — the archive must not claim a measurement it does not have. But the hooks
# were written for an estate that has run every migration and holds every table, so on a deployment
# whose `public` schema has three tables (no indox/tenancy layer, an n8n with zero credential rows)
# the export died on the first fact and `bbox data export` was unusable — there was NO WAY to back
# that machine up. Two distinct causes, both fixed here and at the call sites:
#
#   1. a relation that does not exist  -> `absent` (this helper)
#   2. an aggregate over zero rows     -> SQL NULL, which prints as nothing.
#      `string_agg`/`md5` over an empty set is NULL, not ''. Those call sites now wrap the aggregate
#      in `coalesce(..., 'empty')`, which keeps "nothing here" distinguishable from "no such table".
#
# `absent` is a truthful fact, and the restore side re-emits the same value for the same absent
# relation, so the diff still compares like with like. Absence of a measurement is not evidence of a
# good one — but absence of a TABLE is a fact about the deployment, and it must not block a backup.
factq() {
  local v="${2-}" rel="${3-}"
  if [ -z "${v// /}" ] && [ -n "${rel}" ] && [ "$(q "select to_regclass('${rel}') is null;")" = t ]; then
    v=absent
  fi
  echo "FACT $1 ${v}"
}
