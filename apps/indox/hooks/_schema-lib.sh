# _schema-lib.sh — the pieces apply-schema and schema-drift MUST agree on. Sourced, never run.
#
# One owner for two facts that started drifting the day they were pasted twice:
#
# 1. WHICH CONTAINER IS THE DATABASE. The first drafts hand-parsed .env and defaulted to
#    `supabase-db-local`, while scripts/lib.sh — which every sibling hook in this directory
#    sources — defaults DEPLOYMENT_NAME to `bina-deployment` and resolves `${VAR}` references
#    the way compose does. On any host without DEPLOYMENT_NAME in .env, these two hooks alone
#    died "postgres container is not running" while every lib.sh-based tool worked. So: the
#    same lib, the same DN, one spelling of the container name.
#
# 2. WHICH STATEMENTS NEVER REACH A TENANT APPLY. Historically schema.sql declared three
#    SHARED views as `public.` — company_registry, extraction_queries,
#    v_indox_priority_local_dupes — with unqualified table names in their bodies. Applied under
#    `search_path = <instance>, public`, every apply silently repointed the shared view at
#    whichever tenant ran last (measured: after `apply-schema levi`, public.company_registry
#    read indox_levi and returned 0 rows where hacohen has 1,180 — and the live pipeline reads
#    that view).
#
#    [cutover 2026-08-31] Those three are now declared TENANT-LOCAL in schema.sql (unqualified,
#    so the apply preamble's search_path lands them inside the tenant) — the fixture finally
#    produces the per-tenant copies that were previously made by hand. `strip_public_views`
#    therefore matches NOTHING on the current fixture; it stays as the regression guard: a
#    future `create or replace view public.<x>` snuck into schema.sql must never reach a tenant
#    apply, for exactly the measured reason above. One copy, shared by both hooks, so the guard
#    cannot diverge between provisioning and the drift gate.

_SL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
. "${_SL_ROOT}/scripts/lib.sh"   # read_env / DN — compose-grade .env resolution
INDOX_PG="supabase-db-${DN}"

# indox_resolve_instance [<id>] — echoes "id|schema" for the tenant an operator tool should act
# on, or dies with the choices. Resolution order:
#   1. an explicit id (argument or INDOX_INSTANCE) — validated against the registry;
#   2. no id: the SINGLE enabled instance whose purpose is not 'test'. The test tenant is a
#      standing fixture on every deployment, so "default to the only enabled instance" stopped
#      resolving the day it landed — purpose='test' exists in the registry precisely so tools
#      can skip it when defaulting. Two enabled production tenants = genuinely ambiguous = the
#      caller must name one; defaulting by sort order would point sync tooling at whichever
#      tenant alphabetizes first, which is a cross-tenant action wearing a convenience.
# The resolution is always PRINTED to stderr so no default is ever silent.
indox_resolve_instance() {
  local want="${1:-${INDOX_INSTANCE:-}}" rows hit n
  rows="$(docker exec "${INDOX_PG}" psql -U postgres -d postgres -tA -F'|' -c \
    "select id, schema_name, coalesce(purpose,'') from public.indox_instances where enabled order by id" \
    2>/dev/null | sed '/^$/d')"
  [ -n "${rows}" ] || { echo "indox: no enabled instances in public.indox_instances" >&2; return 1; }
  if [ -n "${want}" ]; then
    hit="$(printf '%s\n' "${rows}" | awk -F'|' -v w="${want}" '$1==w{print $1"|"$2; exit}')"
    [ -n "${hit}" ] || { echo "indox: instance '${want}' is not an enabled registered instance (have: $(printf '%s\n' "${rows}" | cut -d'|' -f1 | tr '\n' ' '))" >&2; return 1; }
    echo "indox: acting on instance '${want}'" >&2
    printf '%s\n' "${hit}"; return 0
  fi
  hit="$(printf '%s\n' "${rows}" | awk -F'|' '$3!="test"{print $1"|"$2}')"
  n="$(printf '%s\n' "${hit}" | sed '/^$/d' | wc -l | tr -d ' ')"
  if [ "${n}" = "1" ]; then
    echo "indox: no instance named — defaulting to the sole production tenant '$(printf '%s' "${hit}" | cut -d'|' -f1)'" >&2
    printf '%s\n' "${hit}"; return 0
  fi
  echo "indox: ${n} enabled production tenants ($(printf '%s\n' "${rows}" | awk -F'|' '$3!="test"{printf "%s ", $1}')) — name one: --instance <id> or INDOX_INSTANCE" >&2
  return 1
}

strip_public_views() {
  awk '
    /^create or replace view public\./ { skipping = 1 }
    skipping { if (/;[[:space:]]*$/) { skipping = 0 }; next }
    { print }
  '
}
