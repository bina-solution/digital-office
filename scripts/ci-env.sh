#!/usr/bin/env bash
# ci-env.sh — generate the CI .env (random secrets; *.localhost over http). Shared by
# ci-verify.yml and indox-e2e.yml so the environment definition cannot drift between lanes.
# compose .env interpolation is ORDER-SENSITIVE: vars other lines reference must come first.
set -euo pipefail
rnd() { openssl rand -hex 24; }
# OFFICE_DOMAIN: a REAL office on a real domain (apps/dgo-extend provisions remote dgo-extend through
# this file, so there is one generator of a fresh .env, not two). Every host becomes
# <host>.<OFFICE_DOMAIN> over https, the operator emails live on that domain, and the perf profile
# is left to `bbox run` (ensure_perf_profile sizes it to the machine's cores). Unset = the CI/laptop
# .env this script always produced, byte-for-byte.
DOMAIN="${OFFICE_DOMAIN:-localhost}"
if [ -n "${OFFICE_DOMAIN:-}" ]; then PROTO=https; ADMIN="admin@${OFFICE_DOMAIN}"; else PROTO=http; ADMIN=""; fi
# Refuse to overwrite: this file generates SECRETS, and regenerating over a live office's .env
# orphans every database password it holds (issues/ci-env-sh-overwrites-a-live-env.yaml).
if [ -s .env ] && [ "${CI_ENV_FORCE:-0}" != 1 ]; then
  echo "ci-env.sh: .env already exists — refusing to overwrite it (CI_ENV_FORCE=1 to force)" >&2
  exit 3
fi
# The edge's identity service FOLLOWS THE STATE this .env is generated beside (r030-005's second
# reader): a checkout whose platform.state.yaml still runs authentik gets authentik, whatever the
# product default says, or traefik asks a sign-in that is not running and every gated host fails.
# forward-auth only where the state runs it and not authentik (both on is the switch-over window,
# which keeps authentik until the office's own switch). No state yet: the product default's.
# CI_IDENTITY still overrides.
_state=platform.state.yaml; [ -f "${_state}" ] || _state=platform.state.default.yaml
_on() { [ -f "${_state}" ] && grep -Eq "^  $1:[[:space:]]*\{[^}]*(enabled:[[:space:]]*true|state:[[:space:]]*enabled)" "${_state}"; }
IDENTITY=authentik
if _on forward-auth && ! _on authentik; then IDENTITY=forward-auth; fi
OVR='DEPLOYMENT_NAME|DEPLOYMENT_DOMAIN|DEV_DOMAIN|AUTH_EXTERNAL_URL|AUTH_PROTOCOL|AUTHENTIK_SECRET_KEY|AUTHENTIK_POSTGRES_PASSWORD|AUTHENTIK_BOOTSTRAP_USER|AUTHENTIK_BOOTSTRAP_PASSWORD|AUTHENTIK_BOOTSTRAP_TOKEN|AUTHENTIK_BOOTSTRAP_EMAIL|POSTGRES_PASSWORD|REDIS_PASSWORD|N8N_USER_MANAGEMENT_JWT_SECRET|N8N_ENCRYPTION_KEY|N8N_OWNER_EMAIL|N8N_OWNER_PASSWORD|N8N_RUNNERS_AUTH_TOKEN|N8N_SECURE_COOKIE|GLITCHTIP_SECRET_KEY|GLITCHTIP_DB_PASSWORD|GLITCHTIP_ENABLE_ORG_CREATION|GLITCHTIP_ADMIN_EMAIL|GLITCHTIP_ADMIN_PASSWORD|PORTAINER_ADMIN_PASSWORD|BROWSER42_MCP_TOKEN|BROWSER42_VNC_PASSWORD|DRIVE_BACKEND|GMAIL_BACKEND|GMAIL_IMAP_MODE|LOCALMAIL_USER|LOCALMAIL_PW|SUPABASE_JWT_SECRET|SUPABASE_ANON_KEY|SUPABASE_SERVICE_KEY|SUPABASE_DB_PASSWORD|SUPABASE_DASHBOARD_PASSWORD|SUPABASE_COOKIE_KEY|PLANE_DB_PASSWORD|PLANE_S3_SECRET_KEY|PLANE_OWNER_EMAIL|PLANE_OWNER_PASSWORD|PLANE_OWNER_FIRSTNAME|PLANE_OWNER_LASTNAME|PERFORMANCE_PROFILE|INCOMING_DOCS_SUPABASE_URL|APITOOLS_DB_HOST|FORWARD_AUTH_SECRET|DGO_IDENTITY|CHAT_AUTH_PASS|BS_WEBHOOK_PASS|N8N_WEBHOOK_PASS|SETTINGS_AUTH_PASS|MCP_AUTH_TOKEN|AGENT_RUNNER_TOKEN|DISPATCHER_TOKEN|N8N_API_KEY|CONNECTIONS_ROOT_KEY|OPENHANDS_JWT_SECRET|SUPABASE_POSTGRES_PASSWORD|SUPABASE_AUTHENTICATOR_PASSWORD'
# OVR is every key the block's echo lines write (the *_BASE_URL/*_ROOT_URL/FORGE_* lines it derives
# have filters of their own): .env.ex's line for it is dropped, or the key is in .env twice
# and a reader that takes the FIRST line (perf-profile-apply) gets the template's empty value. 5b663f1d
# put PERFORMANCE_PROFILE= in .env.ex, and from then on no .env made here applied its profile — the
# phone's machine ran every native CPU cap and 10 s probes under emulation (DGO-1084). Checked below.
{
  # CI_DEPLOYMENT_NAME: the container-name suffix. "ci" on the runners; the macOS engine passes
  # "local" so a laptop stack is not labelled as a CI one (`n8n-local`, not `n8n-ci`).
  echo "DEPLOYMENT_NAME=${CI_DEPLOYMENT_NAME:-ci}"
  echo "DEPLOYMENT_DOMAIN=${DOMAIN}"
  echo "DEV_DOMAIN=${DOMAIN}"
  # CI_EDGE_PORT: where the edge lands on the HOST when it is not :80. On macOS an unprivileged
  # process cannot bind :80, so traefik's :80 is forwarded to host :8080 (packaging/macos/engine.yaml)
  # and every browser-facing redirect authentik issues must carry the port, or the login round-trip
  # lands on a closed port. Host() routers ignore the port, so only this URL needs it.
  echo "AUTH_EXTERNAL_URL=auth.${DOMAIN}${CI_EDGE_PORT:+:${CI_EDGE_PORT}}"
  # Every browser-facing host must carry the port too, not just auth: authentik's proxy outpost
  # matches a request to its provider by the FULL Host header (measured 2026-09-17:
  # "console.localhost:8080" -> 404, "console.localhost" -> 302), and each provider's
  # external_host is built from <APP>_BASE_URL. So the host-shaped *_BASE_URL lines of .env.ex
  # (<host>.${DEPLOYMENT_DOMAIN} / <host>.${DEV_DOMAIN}) are emitted as <host>.localhost:<port>
  # when an edge port is set. The -local traefik routers match the bare host regardless; the
  # -http/-https twins simply never match (harmless).
  if [ -n "${CI_EDGE_PORT:-}" ]; then
    # The forge is the one host that NESTS UNDER THE CONSOLE on this engine (`localhost` is an
    # unregistered TLD, so a browser reads the registrable domain off the LAST TWO labels:
    # `forge.localhost` and `console.localhost` are different sites, while the forge is opened inside
    # the console's frame; `forge.console.localhost` is the same site as the console). A real domain
    # needs none of this — `*.bina-solutions.co.il` is one site already — so the template keeps its
    # domain-shaped value and only this branch differs.
    #
    # The generic rewrite below SKIPS the forge (`| grep -vE '^FORGE_BASE_URL='`), or the line would
    # be emitted twice — once nested, once flat.
    #
    # The port IS here, and the RULE is not: traefik matches `Host()` against the request host with
    # its port stripped, so a rule that contains one never matches anything (measured
    # 2026-09-30: `Host(forge.console.localhost:8080)` answered 404 for a request to
    # forge.console.localhost:8080 while `Host(forge.console.localhost)` answered 200 for the very
    # same request and entrypoint). reconcile.traefik_host() reads this file at render time and emits
    # the host part as a literal, so the value keeps the port the IDENTITY provider needs and the
    # router still gets a port-less rule.
    sed -nE 's/^FORGE_BASE_URL=forge\.\$\{(DEPLOYMENT_DOMAIN|DEV_DOMAIN)\}$/FORGE_BASE_URL=forge.console.localhost:'"${CI_EDGE_PORT}"'/p' .env.ex
    # `|| [ $? -eq 1 ]`: when the forge is the template's only such line, the filter leaves nothing —
    # grep's "no line selected" exit 1, which `set -o pipefail` turned into the whole script's: every new
    # Mac's first `bbox run` got a 51-line .env with no secrets and no profile, since 139a1354 (DGO-610).
    # Only that exit is tolerated: grep's own error (2) still stops the script.
    sed -nE 's/^([A-Z0-9_]+_BASE_URL)=([a-z0-9-]+)\.\$\{(DEPLOYMENT_DOMAIN|DEV_DOMAIN)\}$/\1=\2.localhost:'"${CI_EDGE_PORT}"'/p' .env.ex \
      | { grep -vE '^FORGE_BASE_URL=' || [ $? -eq 1 ]; }
    # `<APP>_ROOT_URL=https://<host>.${DEPLOYMENT_DOMAIN}` is the OTHER shape a browser-facing origin
    # takes: a product's OWN idea of itself, printed into the URLs it hands out (Forgejo's clone
    # URLs). Same port rewrite, and the scheme drops to http — this engine has no certificate for
    # *.localhost, and an app told to advertise https://forge.localhost hands out dead links.
    sed -nE 's/^FORGE_ROOT_URL=https?:\/\/forge\.\$\{(DEPLOYMENT_DOMAIN|DEV_DOMAIN)\}$/FORGE_ROOT_URL=http:\/\/forge.console.localhost:'"${CI_EDGE_PORT}"'/p' .env.ex
    sed -nE 's/^([A-Z0-9_]+_ROOT_URL)=https?:\/\/([a-z0-9-]+)\.\$\{(DEPLOYMENT_DOMAIN|DEV_DOMAIN)\}$/\1=http:\/\/\2.localhost:'"${CI_EDGE_PORT}"'/p' .env.ex \
      | { grep -vE '^FORGE_ROOT_URL=' || [ $? -eq 1 ]; }
    # FORGE_HOST is neither a *_BASE_URL nor a *_ROOT_URL, so the template's line is dropped below
    # and this is the only place it is written: it is Forgejo's own `DOMAIN`, and it must match the
    # host its links are served from (no port — DOMAIN is a hostname).
    echo "FORGE_HOST=forge.console.localhost"
  fi
  echo "AUTH_PROTOCOL=${PROTO}"
  if [ -n "${CI_EDGE_PORT:-}" ]; then
    # drop the host-shaped originals; the port-bearing lines below replace them
    grep -vE "^(${OVR})=" .env.ex | grep -vE '^[A-Z0-9_]+_(BASE_URL|ROOT_URL)=(https?://)?[a-z0-9-]+\.\$\{(DEPLOYMENT_DOMAIN|DEV_DOMAIN)\}$' | grep -vE '^FORGE_HOST='
  else
    grep -vE "^(${OVR})=" .env.ex
  fi
  echo "AUTHENTIK_SECRET_KEY=$(rnd)$(rnd)"
  echo "AUTHENTIK_POSTGRES_PASSWORD=$(rnd)"
  echo "AUTHENTIK_BOOTSTRAP_USER=akadmin"
  echo "AUTHENTIK_BOOTSTRAP_PASSWORD=$(rnd)"
  echo "AUTHENTIK_BOOTSTRAP_TOKEN=$(rnd)"
  echo "AUTHENTIK_BOOTSTRAP_EMAIL=${ADMIN:-ci@example.com}"
  echo "POSTGRES_PASSWORD=$(rnd)"
  echo "REDIS_PASSWORD=$(rnd)"
  # forward-auth's cookie signing key (96 hex), written always: harmless where authentik is the
  # identity, and what a fresh forward-auth office cannot start without (DGO-1090). CI_IDENTITY picks
  # the edge's identity service; without it, the one the state on disk runs (IDENTITY, above):
  # forward-auth for a fresh office since 0.3.0 (r030-005), authentik for a state that still runs it.
  echo "FORWARD_AUTH_SECRET=$(rnd)$(rnd)"
  echo "DGO_IDENTITY=${CI_IDENTITY:-${IDENTITY}}"
  echo "N8N_USER_MANAGEMENT_JWT_SECRET=$(rnd)"
  echo "N8N_ENCRYPTION_KEY=${N8N_ENCRYPTION_KEY_SECRET:-$(rnd)}"
  echo "N8N_OWNER_EMAIL=${ADMIN:-person5@example.com}"
  echo "N8N_OWNER_PASSWORD=Ci$(rnd)9X"
  echo "N8N_RUNNERS_AUTH_TOKEN=$(rnd)"
  # CI is http-only (*.localhost over http): n8n's secure cookie would block the UI.
  echo "N8N_SECURE_COOKIE=$([ "$PROTO" = https ] && echo true || echo false)"
  echo "GLITCHTIP_SECRET_KEY=$(rnd)"
  echo "GLITCHTIP_DB_PASSWORD=$(rnd)"
  echo "GLITCHTIP_ENABLE_ORG_CREATION=true"
  echo "GLITCHTIP_ADMIN_EMAIL=${ADMIN:-person5@example.com}"
  # Random always, CI included. An office made without an admin address got a FIXED password here,
  # published with this file; the HP was made that way (DGO-980). Every reader takes it from .env.
  echo "GLITCHTIP_ADMIN_PASSWORD=G$(rnd)9x!"
  echo "PORTAINER_ADMIN_PASSWORD=P$(rnd)"
  echo "BROWSER42_MCP_TOKEN=$(rnd)"
  echo "BROWSER42_VNC_PASSWORD="
  # The template's own values for these were REAL and copied as they were, so every office made here
  # shared them with every other and with whoever holds the template (DGO-1220, measured 2026-11-03:
  # 10 of them in each fresh .env, and vps1 runs on them). Minted per office like the rest. N8N_API_KEY
  # is n8n's to issue (apps/n8n/hooks/push-app ensure_api_key makes one when there is none), the vault's
  # root key is secret-zero (platform-base/connections), and the two dead SUPABASE_*_PASSWORD keys are
  # stripped above, so keygen.py below writes fresh ones.
  echo "CHAT_AUTH_PASS=$(rnd)"
  echo "BS_WEBHOOK_PASS=$(rnd)"
  echo "N8N_WEBHOOK_PASS=$(rnd)"
  echo "SETTINGS_AUTH_PASS=$(rnd)"
  echo "MCP_AUTH_TOKEN=$(rnd)"
  echo "AGENT_RUNNER_TOKEN=$(rnd)"
  echo "DISPATCHER_TOKEN=$(rnd)"
  echo "N8N_API_KEY="
  echo "CONNECTIONS_ROOT_KEY=$(rnd)$(rnd)"
  echo "OPENHANDS_JWT_SECRET=$(rnd)"
  # Integration-API backends:
  # indox data plane is supabase-only (sheets fully legacy, no toggle to set).
  echo "DRIVE_BACKEND=local"
  # imap + GMAIL_IMAP_MODE=local (below) = the gmail ROUTER serves GreenMail local mail —
  # required by the sync-v3 suites (they inject/search via gmailApiRouter01, which bakes
  # this value in at n8n-push; 'none' made every suite append die at first gmail call —
  # runs #50/#57). The old 'none' predates localmail: back then imap meant a credless
  # real-Gmail shell that error-looped scanners; local mode has no creds to fail.
  echo "GMAIL_BACKEND=imap"
echo "GMAIL_IMAP_MODE=local"
echo "LOCALMAIL_USER=indox"
# CI's local mailbox keeps its known password; a real office's is its own (DGO-1220)
if [ -n "${OFFICE_DOMAIN:-}" ]; then echo "LOCALMAIL_PW=$(rnd)"; else echo "LOCALMAIL_PW=indox"; fi
  # ci-small perf profile — values come from platform/profiles/perf-profiles.yml (applied below);
  # settings rows land later via n8n-push (db is not up yet at env-gen time)
  # A real office's is left empty, as the template has it, for `bbox run` to size to its machine. Two
  # lines: the first is quoted as it stands by packaging/dgo (engine.go ciEnvRE, oracle_test.go).
  [ -n "${OFFICE_DOMAIN:-}" ] || echo "PERFORMANCE_PROFILE=ci-small"
  [ -z "${OFFICE_DOMAIN:-}" ] || echo "PERFORMANCE_PROFILE="
  # supabase compose reads THESE names (keygen writes SUPABASE_POSTGRES_PASSWORD — different var)
  echo "SUPABASE_DB_PASSWORD=$(rnd)"
  echo "SUPABASE_DASHBOARD_PASSWORD=$(rnd)"
  echo "SUPABASE_COOKIE_KEY=$(rnd)"
  # Plane (apps/project-pln) carries its own postgres, rabbitmq and minio, so it carries three
  # secrets of its own. Its compose requires them (`:?`), which is the point: the shipped defaults
  # were the word "plane", and a deployment that never noticed would be running a database whose
  # password is on the internet. Generated here like every other secret on a fresh machine.
  echo "PLANE_DB_PASSWORD=$(rnd)"
  echo "PLANE_S3_SECRET_KEY=$(rnd)"
  # …and the OWNER's own login (apps/project-pln/hooks/onboard). Plane has no bootstrap of its own,
  # so a fresh instance is unusable until an admin exists: the hook creates one from these values on
  # the first `bbox run`, which is what makes Plane work out of the box like every other app here.
  # The email is the same human as everywhere else, so it defaults to n8n's owner.
  echo "PLANE_OWNER_EMAIL=${ADMIN:-person5@example.com}"
  echo "PLANE_OWNER_PASSWORD=Pl$(rnd)9X"
  echo "PLANE_OWNER_FIRSTNAME=${ADMIN:+Admin}"
  echo "PLANE_OWNER_LASTNAME="
  # Cross-service supabase reach on the CI network: incoming-documents + apitools run on
  # traefik-network only, where kong/db are aliased `supabase-kong`/`supabase-db`. The bare
  # defaults (kong:8000 / db) resolve to supabase-net IPs these apps can't reach, so the INDOX
  # documents grid 500s and my-docs renders empty. Point them at the traefik-network aliases so a
  # from-scratch CI/cloud bring-up renders real content. (ui-map.yml also sets these; harmless dup.)
  echo "INCOMING_DOCS_SUPABASE_URL=http://supabase-kong:8000"
  echo "APITOOLS_DB_HOST=supabase-db"
} > .env
# A key twice means OVR is behind .env.ex again: said, with the keys (a warning for now, not a refusal).
twice="$(grep -oE '^[A-Za-z0-9_]+=' .env | sort | uniq -d | tr -d '=' | tr '\n' ' ' || true)"
[ -z "${twice}" ] || echo "ci-env.sh: WARNING — .env holds these keys twice, the template's line and this script's; add them to OVR: ${twice}" >&2
# real supabase JWTs (the .env.ex placeholders are not valid tokens — storage rejects them);
# keygen fills ONLY missing keys, which is why the placeholders are stripped above.
python3 platform-base/postgres/hooks/keygen.py
python3 scripts/perf-profile-apply || true
# The file is named in full: "CI .env generated (261 keys)." was true on the day it replaced a live
# office's file, and gave whoever read the transcript no hint of which file that had been.
echo "${OFFICE_DOMAIN:+office }${OFFICE_DOMAIN:-CI} .env generated: $(pwd)/.env ($(grep -c = .env) keys)."
