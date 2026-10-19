#!/usr/bin/env bash
# seed.sh — seed the platform with demo data so every UI renders real content (bbox seed).
#
# ONE seeding path, used identically by a local run and CI. Everything runs via `docker exec`
# from INSIDE a networked container (hitting 127.0.0.1 / service DNS), because the runner host
# cannot reach container bridge IPs in docker-in-docker — every host-side seed silently timed out,
# which is why my-docs/mail/drive rendered empty in every early CI run. Each seed is bounded by
# `timeout` so a hung backend can never stall the caller. All best-effort: never fatal.
#
# INSERT-ONLY, NEVER CLOBBER (2026-08-05 incident) — `public.settings` is not a demo table, it is
# the platform's live config store: `sync_registry` is the ONE source of truth for where a real
# deployment's drive/gmail sync pipes point (folder ids, connections), and this seeder used to
# UPSERT (`on conflict do update`) every row from apps/*/blueprint/fixtures/settings.json on every
# `bbox ui-map`/`bbox seed`. On a stack that had already been configured for a real client, that
# silently overwrote the live registry with this fixture's 6-entry demo registry — twice, on the
# same live client deployment, destroying real folder-connection config both times. The fix is
# structural, not (only) a denylist of "dangerous" keys (a list is only ever as complete as the
# last audit): every seed write below is `on conflict("instance","key") do nothing`. A fresh/empty
# stack still gets every fixture row (nothing to conflict with); a stack where an operator (or a
# prior sync run) already wrote a key keeps exactly what it has, forever, no matter what this file
# seeds next. See scripts/refactor/fixture-live-key-lint.py (gate G40) for the complementary check
# that keeps genuinely operational keys (sync_registry chief among them) out of the fixture in the
# first place — this insert-only discipline protects a key that already exists; G40 is what stops
# a live-operational key from ever being seeded as a brand-new tenant's opening config to begin
# with, which insert-only alone cannot do (a first, empty seed has nothing yet to conflict with).
set -uo pipefail
SEED_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$(cd "${SEED_DIR}/.." && pwd)/lib.sh"
cd "${REPO_ROOT}"

# ── settle data backends (fix startup-order races) ───────────────────────────
# apitools persists to supabase Postgres and mailapi reads the mailbox over IMAP, but neither
# gates on those stores — so on a cold bring-up apitools can boot before its schema DB accepts
# connections (my-docs then reads 500 → empty) and mailapi before the mailbox answers. A
# restart once the stores are healthy makes them reconnect. Cheap, idempotent, never fatal.
log "seed — settle data backends"
for svc in apitools mailapi incoming-documents; do
  c="$(cn "$svc")"; [ -n "$c" ] && docker restart "$c" >/dev/null 2>&1 && ok "restarted ${svc}" || warn "${svc} not found"
done
sleep 10

# ── supabase application schema (the tables the apps query) ───────────────────
# Each app owns its own tables now (apps/*/blueprint/fixtures/schema.sql); the platform owns only
# the shared log stream and the updated_at trigger function. Normally applied by an n8n workflow the
# screenshot stack never runs — without this INDOX 404s on kong/rest and drive has no file index.
#
# ORDER: the platform schema first, because an app's schema attaches triggers to what it defines
# (`public.touch_updated_at()`), and the n8n Postgres node sends a whole file as ONE transaction —
# so a missing dependency rolls the entire app schema back and looks like a missing file.
#
# The trailing `99_grants.sql` step is GONE with the file. Its comment used to claim the order was
# load-bearing because blanket grants must follow every app's tables. Measured false: applying it
# changed zero relacl entries and zero pg_default_acl rows — supabase's own ALTER DEFAULT PRIVILEGES
# already covers anon/authenticated/service_role for both owner roles. And a one-shot
# `grant on all tables` can never cover a table created LATER, so no position was ever correct.
# `apps/n8n/hooks/push` now ASSERTS those default privileges instead.
SBDB="$(cn supabase-db)"
if [ -n "$SBDB" ]; then
  log "seed — provision supabase schema (${SBDB})"
  t=0; until docker exec "$SBDB" pg_isready -U postgres -q 2>/dev/null || [ "$t" -ge 60 ]; do sleep 3; t=$((t+3)); done
  _schema_ok=1
  for _sql in apps/n8n/schema/01_platform.sql \
              apps/*/blueprint/fixtures/schema.sql; do
    [ -f "$_sql" ] || continue
    case "$_sql" in
      apps/indox/*)
        # NEVER pipe the tenancy schema bare. indox's schema.sql opens with a DO-block guard
        # that RAISEs when current_schema()='public' — and with ON_ERROR_STOP=0 psql logged the
        # refusal into the discarded stderr and applied every later statement into public
        # anyway, printing "app schemas applied": the exact shadow-copy failure the guard was
        # written to refuse, silently, on this stack. The applier that knows what a tenant is
        # is the app's own hook, so it is the only door.
        apps/indox/hooks/apply-schema --all >/dev/null 2>&1 || _schema_ok=0
        continue ;;
    esac
    # ON_ERROR_STOP=1: a statement that fails must fail the step, not scroll past into /dev/null.
    docker exec -i "$SBDB" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -q < "$_sql" >/dev/null 2>&1 \
      || _schema_ok=0
  done
  [ "$_schema_ok" = 1 ] && ok "app schemas applied" || warn "schema apply reported issues"
  # [cutover 2026-08-31] Seeded PER TENANT SCHEMA, not into public: public.settings is a compat
  # view scheduled for removal, and a view INSERT would have made this seeder the last silent
  # public writer. The schema list comes from the registry apply-schema just ensured.
  _schemas="$(docker exec "$SBDB" psql -U postgres -d postgres -tAc \
      "select schema_name from public.indox_instances where enabled" 2>/dev/null | tr -d ' \r')"
  [ -n "${_schemas}" ] || _schemas="indox_hacohen"
  for _sch in ${_schemas}; do
  python3 - apps/indox/blueprint/fixtures/settings.json "${_sch}" <<'PY' | docker exec -i "$SBDB" psql -U postgres -d postgres -q -v ON_ERROR_STOP=0 >/dev/null 2>&1 \
    && ok "settings seeded into ${_sch} (existing keys left untouched — insert-only)" || warn "settings seed reported issues (${_sch})"
import json, sys, re
rows = json.load(open(sys.argv[1], encoding="utf-8"))
sch = sys.argv[2]
assert re.fullmatch(r"[a-z][a-z0-9_]*", sch), sch
def esc(s): return "'" + str(s).replace("'", "''") + "'"
print("begin;")
for r in rows:
    k = r.get("key")
    if k is None: continue
    # DO NOTHING, not DO UPDATE: a key already present means either an operator configured it
    # or a previous run (demo or live) already wrote it — this seeder's only job is to fill gaps
    # on a fresh stack, never to re-assert fixture values over whatever is live now.
    #
    # Conflict target is ("instance","key"): the settings PK is (instance,key) with `instance`
    # defaulting to 'incoming-documents-main' (the scope constant inside each tenant schema).
    # `on conflict("key")` names no real constraint, postgres rejects the statement, and with a
    # single begin/commit the whole seed silently wrote NOTHING (measured 2026-08) — so any
    # future edit here must keep BOTH halves: the real conflict target AND do nothing.
    print(f'insert into "{sch}".settings("key","value") values({esc(k)},{esc(r.get("value",""))}) '
          'on conflict("instance","key") do nothing;')
print("commit;")
PY
  done
  docker exec "$SBDB" psql -U postgres -d postgres -q -c \
    "insert into storage.buckets(id,name,public) values('drive','drive',true) on conflict(id) do nothing;" >/dev/null 2>&1 \
    && ok "drive storage bucket ensured" || warn "drive bucket reported issues"
else
  warn "supabase-db not found; INDOX/drive will be empty"
fi

# ── demo data (in-container) ─────────────────────────────────────────────────
log "seed — demo data (in-container)"
AP="$(cn apitools)"
if [ -n "$AP" ] && docker cp "$(npath "${SEED_DIR}")/seed_demo.py" "$AP":/tmp/seed_demo.py 2>/dev/null; then
  timeout 120 docker exec "$AP" python3 /tmp/seed_demo.py --base http://127.0.0.1:8080 || warn "apitools seed timed out/errored"
else
  warn "apitools not found — my-docs stays empty"
fi

# mail: inject over SMTP from INSIDE mailapi, which reaches the 'mailserver' service (Postfix).
# Port 25, not GreenMail's old 3025 — a real MTA has no reason to sit on an odd port, and the
# seeder failing with 'Connection refused' is how that move announced itself.
#
# The recipient is read from the deployment's own env, NOT hardcoded. It used to be
# indox@local.test, which is right only on a laptop. On a company deployment the mailbox is
# indox@<MAIL_DOMAIN>, so every seeded message went to a domain this server does not host —
# and because PERMIT_DOCKER trusts the compose network, Postfix ACCEPTED it and tried to relay it
# to the outside world. The seeder printed "mail sent" three times, the mailbox stayed empty, and
# the mail bounced asynchronously into a log nobody reads.
GI="$(cn mailapi)"
[ -n "$GI" ] && timeout 75 docker exec -i "$GI" python3 - <<'PY' || warn "mail seed skipped"
import os, smtplib
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid

# Same derivation as the mail backend: <user>@<domain>, both from the deployment's env.
user = os.environ.get("LOCALMAIL_USER", "indox")
domain = (os.environ.get("MAIL_DOMAIN") or "local.test").strip() or "local.test"
to = user if "@" in user else "%s@%s" % (user, domain)
sender = "seed@%s" % domain
print("  seeding mail to", to)

for frm, subj, body in [
    ('ספק הענן בע"מ <billing@cloudvendor.example>', "חשבונית #INV-2048 — יולי", "חשבונית חודשית על סך 4,200 ₪."),
    ("לקוח חדש <dani@acme.example>", "בקשה להצעת מחיר", "אשמח להצעת מחיר ל-20 משתמשים."),
    ("מערכת INDOX <no-reply@%s>" % domain, "מסמך התקבל ועובד", "המסמך זוהה כחשבונית ועובד."),
]:
    try:
        # Message-ID as well as Date: seeded mail must look like real mail, and a message without
        # one is what threading, mirror correlation and strict receivers all trip over.
        m = MIMEText(body, "plain", "utf-8"); m["From"]=frm; m["To"]=to; m["Subject"]=subj; m["Date"]=formatdate()
        m["Message-ID"] = make_msgid(domain=domain)
        s = smtplib.SMTP("mailserver", 25, timeout=20)
        # A rejected recipient is a FAILURE, not a warning: sendmail() raises on a refused
        # recipient, which is what we want to see rather than a cheerful "mail sent".
        s.sendmail(sender, [to], m.as_string()); s.quit()
        print("  mail sent:", subj[:30])
    except Exception as e: print("  mail FAILED:", type(e).__name__, str(e)[:80])
PY

# drive: upload a couple of files from INSIDE drive (its own API on 127.0.0.1:8975).
LD="$(cn drive)"
[ -n "$LD" ] && timeout 60 docker exec -i "$LD" python3 - <<'PY' || warn "drive seed skipped"
import json, uuid, urllib.request
try:
    b = "http://127.0.0.1:8975"
    folders = json.loads(urllib.request.urlopen(b + "/api/folders", timeout=12).read()).get("folders", [])
    if folders:
        f0 = folders[0]; fid = f0.get("id") or f0.get("name") or f0.get("fid") or ""
        bnd = "x" + uuid.uuid4().hex
        def part(fn, d): return (f'--{bnd}\r\nContent-Disposition: form-data; name="files"; filename="{fn}"\r\nContent-Type: text/plain\r\n\r\n').encode() + d + b"\r\n"
        body = (f'--{bnd}\r\nContent-Disposition: form-data; name="folder"\r\n\r\n{fid}\r\n').encode()
        body += part("חשבונית-דוגמה.txt", "מסמך דוגמה לתצוגה מקדימה.".encode()) + part("הצעת-מחיר.txt", "הצעת מחיר #1024".encode())
        body += f"--{bnd}--\r\n".encode()
        req = urllib.request.Request(b + "/api/upload", data=body, method="POST", headers={"Content-Type": f"multipart/form-data; boundary={bnd}"})
        urllib.request.urlopen(req, timeout=25).read(); print("  drive uploaded 2 files")
    else:
        print("  drive: no folders to upload into")
except Exception as e: print("  drive:", str(e)[:80])
PY

# ── wait for the console's probe targets to settle before capture ────────────
# The console home probes connections + any-concurrency + mailview(→mailapi) + apitools SERIALLY;
# console is captured FIRST, so a slow probe renders it near-empty. Poll the seed-disturbed targets
# (apitools busy finishing the seed, mailapi's mailbox just changed) until they answer.
ready() {  # <service> <url>
  local c; c="$(cn "$1")"; local t=0
  [ -z "$c" ] && return 0
  while [ "$t" -lt 75 ]; do
    docker exec "$c" python3 -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('$2',timeout=4).status<500 else 1)" 2>/dev/null && return 0
    sleep 3; t=$((t + 3))
  done
  warn "$1 not ready after ${t}s — continuing"; return 0
}
log "seed — wait for console probe targets to settle"
ready mailapi "http://127.0.0.1:8970/readyz" && ok "mailapi ready"
ready apitools   "http://127.0.0.1:8080/business" && ok "apitools ready"
ok "seed done"
