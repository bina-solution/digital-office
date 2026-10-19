# ══════════════════════════════════════════════════════════════════════════════════════════════
#  COMPANY IDENTITY — the ONE line a new deployment edits. Everything else in this file derives.
# ══════════════════════════════════════════════════════════════════════════════════════════════
#
# Set BUSINESS_NAME. That is the whole of onboarding a company, plus FIVE DNS records: one for the
# web surface (below) and four for mail (ai/context/mail-multi-tenant.md). Adding PEOPLE to the
# company afterwards needs none at all — see LOCALMAIL_USER further down.
#
#   BUSINESS_NAME=Hacohen
#     └─ COMPANY_SLUG        = hacohen                          (derived — see the note below)
#        ├─ DEPLOYMENT_NAME  = hacohen                          (container-name suffix)
#        ├─ DEPLOYMENT_DOMAIN= hacohen.digital-office.co.il     (every *_BASE_URL hangs off this)
#        │  └─ console.hacohen.digital-office.co.il, mail.hacohen…, n8n.hacohen…, auth.hacohen…
#        ├─ MAIL_DOMAIN      = hacohen.digital-office.co.il     (= DEPLOYMENT_DOMAIN)
#        │  └─ address       = person1@example.com
#        └─ MAIL_DKIM_SELECTOR = hacohen
#
# ── THE DNS RECORD THAT PUTS THE WEB SURFACE ONLINE ───────────────────────────────────────────
#   A    *.<slug>.digital-office.co.il   ->   <this VPS's public IP>
#
# ONE record for every host this deployment serves: console, n8n, auth, apitools, the mail UI,
# drive, alerts — everything. It covers TLS too: traefik's ACME resolver does an HTTP-01 challenge
# per host, and every host resolves through this one row, so certificates issue with no further DNS.
#
# It is a ONE-LABEL wildcard. `*.<slug>.digital-office.co.il` matches
# `console.<slug>.digital-office.co.il` and does NOT match `drive.dev.<slug>.digital-office.co.il`.
# So every host must be exactly <host>.<slug>.digital-office.co.il — which is why DEV_DOMAIN below
# is DEPLOYMENT_DOMAIN itself and not `dev.${DEPLOYMENT_DOMAIN}`, and why no app may introduce a
# deeper host unless a second wildcard is published for it.
#
# MAIL needs records of its own (MX / SPF / DKIM / DMARC on <slug>.digital-office.co.il, plus a
# PTR set at the VPS provider — the one record no registrar access can produce). They are NOT
# listed here: ai/context/mail-multi-tenant.md is the single authoritative place for the mail
# identity and its DNS. The MAIL_* block further down derives from the SAME slug, so a company's
# web host and its mail domain cannot drift apart.
# ──────────────────────────────────────────────────────────────────────────────────────────────

# The single display name for this deployment's owner. Feeds visible branding (homepage title via
# {{HOMEPAGE_VAR_BUSINESS_NAME}}), the glitchtip org default, AND — through COMPANY_SLUG — every
# hostname and the mail address. The ledger business profile (name/ID/VAT) is set separately in
# the onboarding wizard.
BUSINESS_NAME=Hacohen

# DERIVED — DO NOT HAND-EDIT the two values below. Compose cannot lowercase a string or replace
# characters, so the slug is computed at RENDER time: `platform/manager/reconcile.py :: sync_identity`
# runs on every render (and `bbox run` renders before it brings anything up, via ensure_rendered),
# rewrites the assignment that follows each `#@derived slug` marker, and writes it back here.
# A fresh clone therefore needs no manual step — nothing in this stack starts before a render.
#
# Rule: lowercase, any run of non-alphanumerics -> "-", trimmed of leading/trailing "-".
#   "Hacohen" -> hacohen   "Bina Solutions" -> bina-solutions   "staging" -> staging
#
# They are LITERALS, not `${COMPANY_SLUG}`, because the shell and python helpers that read this
# file parse it line-by-line (scripts/lib.sh `read_env`, which feeds every `<svc>-<DEPLOYMENT_NAME>`
# container name) — a value still needing interpolation would reach docker as literal text.
#
# The `#@derived slug` marker is what makes the rewrite safe: sync_identity touches ONLY the line
# directly under a marker. Delete the marker (or the line under it, as scripts/ci-env.sh does for
# DEPLOYMENT_NAME) and that variable becomes a plain hand-set value that nothing overwrites.
#@derived slug
COMPANY_SLUG=hacohen
# The container-name suffix (`n8n-hacohen`, `mailserver-hacohen`). Same slug, so one company =
# one name everywhere; CI strips this line and sets its own, which the marker rule then leaves be.
#@derived slug
DEPLOYMENT_NAME=hacohen

# The SHARED base domain this platform hosts companies under. One zone, one owner. A company that
# later brings its own domain changes this one line (and then owns its own MX/SPF/DMARC/PTR).
COMPANY_BASE_DOMAIN=digital-office.co.il

# ── Deployment domain — derived; every *_BASE_URL/*_HOST below derives from IT ──
DEPLOYMENT_DOMAIN=${COMPANY_SLUG}.${COMPANY_BASE_DOMAIN}
# Deliberately the SAME host as DEPLOYMENT_DOMAIN. It used to be `dev.${DEPLOYMENT_DOMAIN}`, which
# put drive/chat one label deeper than the wildcard A record covers — `*.hacohen.digital-office…`
# does not match `drive.dev.hacohen.digital-office…`, so those hosts resolved nowhere and no
# certificate could be issued for them. Keep it equal unless you also publish a second wildcard.
DEV_DOMAIN=${DEPLOYMENT_DOMAIN}

# Nested-Docker / low-limit hosts (e.g. CI sandboxes): the n8n Postgres requests a high
# open-files ulimit. If the runtime rejects it ("operation not permitted"), cap it here.
# Normal hosts: leave unset (defaults 102400/262144).
# PG_NOFILE_SOFT=4096
# PG_NOFILE_HARD=4096

# LibreChat enabled endpoints (agents must be included for web search to work)
ENDPOINTS=openAI,agents,anthropic,google,custom

# Traefik configuration,
TRAEFIK_API_BASE_URL=traefik.${DEPLOYMENT_DOMAIN}
TRAEFIK_API_DASHBOARD=false # should be the same as TRAEFIK_API_INSECURE
TRAEFIK_API_INSECURE=false # change to false in production
# The contact address Let's Encrypt registers the ACME account against. IT MUST BE A REAL DOMAIN.
#
# This shipped as `you@example.com`, and Let's Encrypt REJECTS that outright:
#   400 urn:ietf:params:acme:error:invalidContact
#   "contact email has forbidden domain \"example.com\""
# So no account is ever created, no certificate is ever issued, traefik serves its self-signed
# default, and every https:// host shows a browser warning. It does not fail loudly at boot — it
# fails once per domain, per retry, in the traefik log, which is the last place anyone looks when
# the symptom is "the certificate is wrong".
#
# example.com, example.org, example.net, .invalid, .test and .localhost are all refused the same way.
TRAEFIK_ACME_EMAIL=admin@${DEPLOYMENT_DOMAIN}


# Portainer configuration
PORTAINER_BASE_URL=portainer.${DEPLOYMENT_DOMAIN}


# N8N DB configuration
POSTGRES_USER=hacohen
POSTGRES_PASSWORD=CHANGE_ME
POSTGRES_DB=n8n
N8N_DB_HOST=n8n-db.${DEPLOYMENT_DOMAIN}

# N8N configuration
# Single source of truth for the n8n version — used by the built image (Dockerfile build arg, main +
# workers) AND the n8nio/runners image. They MUST match; bump here, then rebuild + recreate.
N8N_VERSION=2.17.4
N8N_BASE_URL=n8n.${DEPLOYMENT_DOMAIN}
# Generate with: openssl rand -hex 32
N8N_ENCRYPTION_KEY=CHANGE_ME
# Generate with: openssl rand -hex 32
N8N_USER_MANAGEMENT_JWT_SECRET=CHANGE_ME
# Owner account for a FRESH instance. n8n has no native owner env var, so the push hook (bbox n8n push all)
# bootstraps it via the REST setup endpoint when no owner exists yet (idempotent: skipped if one
# already exists, e.g. after `n8n-push --full`). Password rules: 8-64 chars, >=1 number, >=1 capital.
N8N_OWNER_EMAIL=shlomo@local.dev
N8N_OWNER_PASSWORD=CHANGE_ME
N8N_OWNER_FIRSTNAME=Admin
N8N_OWNER_LASTNAME=User
N8N_SECURE_COOKIE=CHANGE_ME
N8N_LOG_LEVEL=info
N8N_WEBHOOK_TTL=1500
# GlitchTip DSN for n8n error tracking (get from GlitchTip project settings)
N8N_SENTRY_DSN=

# Sentry/GlitchTip configuration
SENTRY_ENVIRONMENT=production
# GlitchTip DSNs (get from each GlitchTip project's settings)
APITOOLS_SENTRY_DSN=
CHAT_SENTRY_DSN=
LIBRECHAT_SENTRY_DSN=

# ── Optional service groups ───────────────────────────────────────────────────
# Comma-separated compose profiles to bring up. Ships with browser42 ON, matching the historical
# bring-up. Drop it (COMPOSE_PROFILES=) on a deployment that drives its browser from elsewhere:
# saves 4 containers + ~2GB image. Explicitly named services start regardless of this list.
COMPOSE_PROFILES=

# WhatsApp bot session/data dir on the host. Default = the live hacohen-vps path; set this on
# any other machine (it is a bind mount, so a wrong path silently yields an empty data dir).
# NOTE: a HOST path, not an app name — it is NOT renamed when the app is. It holds the
# WhatsApp pairing session; repointing it silently loses the link and forces a new QR scan.
WHATSAPP_DATA_DIR=/home/solomonboltin/whatsapp-hacohanim/data

# Chat configuration
#
# UPGRADING FROM A DEPLOYMENT THAT PREDATES THIS RENAME (was WADMIN_*): the host CHANGES from
# wadmin.<domain> to chat.<domain>, which needs a DNS record and a fresh certificate — that is the
# point of the rename and there is deliberately no fallback to the old host. The PASSWORD does not
# need migrating: connections reads the old `wadmin-auth` vault key under the new `chat-auth` id
# (RENAMED_CONNECTIONS in platform-base/connections/app.py), so the credential keeps working until
# it is re-minted. The old authentik application and provider are removed by
# platform-base/authentik/blueprints/zzz-migrations.yaml.
CHAT_APP_BASE_URL=chat.${DEPLOYMENT_DOMAIN}
CHAT_APP_PORT=3000
# Chat basic-auth (n8n 'Chat Auth' cred, env-managed via blueprint credential_overrides)
CHAT_AUTH_USER=chat
CHAT_AUTH_PASS=CHANGE_ME

# API Tools configuration
APITOOLS_BASE_URL=apitools.${DEPLOYMENT_DOMAIN}
MY_DOCS_BASE_URL=my-docs.${DEPLOYMENT_DOMAIN}
# drive's UI host. MUST be declared for the same reason as CONSOLE/CONNECTIONS below: the
# authentik blueprint gates drive via `!Env [DRIVE_BASE_URL, drive.localhost]`, and an undeclared
# var silently becomes a provider for drive.localhost — unreachable on a domain, 404 with no hint.
# NOTE: drive's own traefik labels still derive their Host() from `drive.${DEV_DOMAIN}` and
# publish a `web`-only router (no websecure/certresolver), so https://drive.* has no cert yet.
DRIVE_BASE_URL=drive.${DEPLOYMENT_DOMAIN}

# ── Browser-facing hosts of the apps that declared a base_url_env but had no line here ──────────
# Same failure as MAIL_BASE_URL above: an undeclared key falls back to the app's default_host
# ("<app>.localhost"), so on any office with a real domain — every office the dgo-extend app
# provisions — these apps compiled an authentik provider and a router no browser can reach.
BINA_DS_BASE_URL=bina.${DEPLOYMENT_DOMAIN}
COMPUTERS_BASE_URL=computers.${DEPLOYMENT_DOMAIN}
DIGITAL_ASSETS_BASE_URL=digital-assets.${DEPLOYMENT_DOMAIN}
DOMAINS_BASE_URL=domains.${DEPLOYMENT_DOMAIN}
GIT_BASE_URL=git.${DEPLOYMENT_DOMAIN}
HELLO_BINA_BASE_URL=hello-bina.${DEPLOYMENT_DOMAIN}
DGO_EXTEND_BASE_URL=dgo-extend.${DEPLOYMENT_DOMAIN}
SITES_BASE_URL=sites.${DEPLOYMENT_DOMAIN}
SOCIAL_LIST_BASE_URL=social-list.${DEPLOYMENT_DOMAIN}
TELEGRAM_TV_BASE_URL=telegram-tv.${DEPLOYMENT_DOMAIN}
# The mail UI (mailview) host. Until 2026-09-17 the mail app declared no base_url_env, so its
# authentik provider was compiled with a hard "http://mail.localhost" on EVERY deployment — and a
# deployment whose edge is not on :80 (the macOS engine, :8080) could not reach it at all.
MAIL_BASE_URL=mail.${DEPLOYMENT_DOMAIN}

# ── Version control (apps/git): the office's own forge ──────────────────────────────────────────
# FORGE_BASE_URL is the git app's SECOND host, and it must be declared for the same reason
# MAIL_BASE_URL is: the compiled traefik `forge-http`/`forge-https` routers read
# `Host(${FORGE_BASE_URL})`, and an undeclared var falls back to `forge.localhost` — a host no
# domain deployment can reach, so the code library 404s on production only.
FORGE_BASE_URL=forge.${DEPLOYMENT_DOMAIN}
# Forgejo's OWN idea of its origin: its UI prints clone URLs from it, so a mismatch shows a working
# repository with an unreachable address. https on a domain; the macOS engine needs its edge port.
FORGE_ROOT_URL=https://forge.${DEPLOYMENT_DOMAIN}
FORGE_HOST=forge.${DEPLOYMENT_DOMAIN}
# In-network origin — the git service's `local` provider and the mirror engine call the forge here.
FORGE_URL=http://forge:3000

# Consolidation pillars — the unified RTL shell (המרכז) + the credential plane. Both are
# product surfaces, so they derive from DEPLOYMENT_DOMAIN like my-docs/machine/homepage.
# MUST be declared: production/compose.yml brings both up by default and their Host() rules
# fall back to *.localhost, which no domain deployment can reach.
CONSOLE_BASE_URL=console.${DEPLOYMENT_DOMAIN}
CONNECTIONS_BASE_URL=connections.${DEPLOYMENT_DOMAIN}
# (MAIL_UI_BASE_URL is gone: the mail API no longer serves a browser client of its own — mailview
# at mail.* is the one mail client. n8n, mailview and the console reach mailapi by container name.)
# The app gallery (מכונה/apps) and the alerts centre (התראות). Neither was declared here, so
# both fell through to a `.localhost` default: app-management's authentik provider published
# `https://apps.localhost` as its external_host on EVERY deployment, which forward-auth then
# 404'd for the real host. Same must-be-declared rule as the two above.
APP_MANAGEMENT_BASE_URL=apps.${DEPLOYMENT_DOMAIN}
NOTIFICATIONS_BASE_URL=alerts-svc.${DEPLOYMENT_DOMAIN}
# The single OAuth redirect URI is <CONNECTIONS_PUBLIC_URL>/oauth/callback — it must be registered
# verbatim on the Google OAuth client. Leave as-is for a domain deploy; on a LOCAL box set
# CONNECTIONS_PUBLIC_URL=http://127.0.0.1:8990 (connections publishes that loopback callback so
# Google can reach it directly, bypassing Traefik/Authentik).
CONNECTIONS_PUBLIC_URL=https://${CONNECTIONS_BASE_URL}


# ── MAIL SERVER (Postfix/Dovecot) — the deployment's own MAIL IDENTITY ────────────────────────
# These five were undeclared here until 2026-07-29, so `cp .env.ex .env` produced a deployment
# whose entire mail identity was defaulted, and every value below had to be remembered by a human
# and hand-typed into the VPS's .env. That is exactly the un-recreatable state this file exists to
# prevent. The DEFAULTS BELOW ARE THE LAPTOP-SAFE ONES and are safe to ship; the comment on each
# says what a PUBLIC deployment must set instead. A public deployment also needs DNS —
# ai/context/mail-multi-tenant.md §DNS has the five records, and GO-LIVE.md §8 has the exact block
# used by the bina-devops staging deployment.
#
# The domain this server IS — the deployment's OWN subdomain, the same one the web is served on.
# MX is a per-DOMAIN record: companies that share a base domain must also share one inbound host,
# and every message for every client would pass through one relay. A per-company subdomain gives
# each company an MX pointing at its own machine, which is the premise of one VPS per company.
# Rationale and the full record set: ai/context/mail-multi-tenant.md.
# Anything ending .test/.local/.localhost puts mailsetup in local-only mode (it then reports ready
# with no DNS at all) — the right answer on a laptop, not on a VPS.
MAIL_DOMAIN=${DEPLOYMENT_DOMAIN}
# Postfix's HELO name and the A/MX target. MUST equal the PTR name of MAIL_PUBLIC_IP or receivers
# reject or spam-file the mail. The wildcard A record already resolves it; the PTR is set at the
# VPS provider.
MAIL_FQDN=mail.${DEPLOYMENT_DOMAIN}
# DKIM selector — the label in <selector>._domainkey.<MAIL_DOMAIN>, i.e.
# `<slug>._domainkey.<slug>.digital-office.co.il`. The domain is already per-company, so the
# selector does not have to be; it is anyway, because it makes the zone readable and because a
# company that later brings its OWN domain keeps a name that still says who the key belongs to.
# DECLARED, never defaulted: unset, compose falls back to DEPLOYMENT_NAME while mailsetup.py falls
# back to "mail", and a selector that disagrees with the published record means every message fails
# DKIM with nothing logged.
MAIL_DKIM_SELECTOR=${COMPANY_SLUG}
# The address the world reaches this server at. Left empty, mailsetup auto-detects via OpenDNS,
# which is wrong behind NAT/a load balancer and then reports correct DNS as three failures.
MAIL_PUBLIC_IP=
# WHICH IP PROTOCOL THIS SERVER SENDS FROM. `ipv4` (the default) is a deliverability setting, not a
# networking preference, and leaving it alone is almost always right.
#
# PTR and SPF are facts about ONE address. A dual-stacked VPS has two, the provider ships a default
# IPv6 PTR that names their machine rather than yours, and `v=spf1 mx ~all` authorises only the A
# record unless you also published an AAAA. So every delivery Postfix happens to make over IPv6
# fails forward-confirmed reverse DNS AND SPF — and on IPv6 Gmail REJECTS that outright instead of
# spam-filing it. Which protocol gets used is not ours to decide message by message; Postfix picks
# per remote MX. Mail that "works" on a dual stack is one DNS answer away from not working.
#
# Set to `all` only after BOTH: (1) the IPv6 rDNS at your VPS provider answers with MAIL_FQDN, and
# (2) the SPF record covers the v6 address (`ip6:<addr>`, or an AAAA that `mx`/`a` expands to).
# The mail setup checklist then grows two rows that verify exactly those two, so you are not taking
# your own word for it. Also set MAIL_PUBLIC_IP6 so it checks the right address.
MAIL_INET_PROTOCOLS=ipv4
MAIL_PUBLIC_IP6=
# Spam filtering. 1 turns on BOTH Amavis and SpamAssassin — they are one chain, not two features:
# in docker-mailserver SpamAssassin is a Perl module Amavis loads, so SpamAssassin without Amavis
# scans nothing at all while reading as enabled. Costs ~200-300 MB RSS in the mailserver container;
# leave 0 on a laptop or in CI. Spam is tagged and filed to Junk, never bounced or discarded.
MAIL_ENABLE_SPAM=0
# Antivirus. OFF by default and that is a memory decision, not a security opinion: ClamAV's
# signature database is over 1 GB resident since 2024, which is more than this whole mail container
# is otherwise allowed. Turn it on only where the host has the RAM to spare, and raise
# MAIL_MEM_LIMIT with it (2560M or more).
MAIL_ENABLE_CLAMAV=0
# Which interface port 25 is published on. 127.0.0.1 (the default) means NO MAIL FROM THE INTERNET
# EVER ARRIVES — and no health check can detect that, because every probe runs inside the network.
# A public deployment: 0.0.0.0.
MAIL_BIND=127.0.0.1
# The mailboxes on this server. LOCALMAIL_USER is the PRIMARY and stays a scalar — it is the one
# account mailapi authenticates as. LOCALMAIL_EXTRA_USERS is every mailbox that exists only to
# RECEIVE (a per-company address, a role address): comma- or space-separated, each entry `name`
# (qualified with MAIL_DOMAIN), a full `name@domain`, or `name:password` to give it one of its own.
# mailserver-init provisions them create-only, so re-running never rewrites a password.
#
# ── this variable vs. the mail UI's mailbox screen ────────────────────────────────────────────
# Adding a person to the company is done from the UI (מייל → חשבונות → תיבות דואר בדומיין), which
# writes the account through `mailboxd` — the one process with the mail config volume mounted
# read-write. That needs no DNS and no restart, because the domain's records already cover every
# address at it, and it is the answer for "user2 joined the company on a Tuesday".
#
# This variable is for the mailboxes that must exist on ANY machine that stages this repo: a role
# address the automations send to, a postmaster alias, anything a workflow hard-codes. The
# difference is not convenience, it is survival — a UI-created mailbox lives in the mail_config
# VOLUME, so it is gone the moment the volume is, while an address listed here is re-provisioned by
# mailserver-init on the next bring-up anywhere.
#
# What is NOT supported either way is appending to postfix-accounts.cf over ssh: that account is
# invisible to the repo, invisible to the UI's list, and cannot be reproduced on a second
# deployment. Both paths above exist so nobody ever needs to.
#
# The PRIMARY is the company address: admin@<MAIL_DOMAIN> = admin@<slug>.digital-office.co.il.
# The company lives in the DOMAIN, so the local part is the plain role name. Both halves are the
# same slug, so `console.hacohen.…` and `admin@hacohen.…` cannot drift apart.
LOCALMAIL_USER=admin
LOCALMAIL_EXTRA_USERS=


# inbox service. LOCAL-FIRST by default: a clean install serves the built-in local mailbox
# (Postfix/Dovecot, the `mailserver` service) with zero config, so the mail service comes up
# HEALTHY out of the box. A real mailbox
# is connected THROUGH the connections UI (which overrides this), or by setting GMAIL_IMAP_MODE=gmail
# + a real app password below. Left at the placeholder, mode=gmail would fail auth and report
# unhealthy on first boot — so the shipped default must be local.
GMAIL_IMAP_MODE=local
# app-password IMAP (no OAuth/Gmail-API quota) — only used when GMAIL_IMAP_MODE=gmail.
# Capture the app password per ai/context/gmail-onboardin-imap-stmp.md; HOST/PORT default to
# imap.gmail.com:993.
GMAIL_IMAP_USER=person2@example.com
GMAIL_IMAP_APP_PW=your-gmail-app-password
# GMAIL_IMAP_HOST=imap.gmail.com
# GMAIL_IMAP_PORT=993


# Redis configuration
REDIS_HOST=redis.${DEPLOYMENT_DOMAIN}
REDIS_PORT=6379
REDIS_PASSWORD=CHANGE_ME



REDISINSIGHT_BASE_URL=redisinsight.${DEPLOYMENT_DOMAIN}


# Ollama configuration
OLLAMA_BASE_URL=ollama.${DEPLOYMENT_DOMAIN}
# In-network URL for n8n->ollama ('Ollama account' cred). Deploy ollama or point elsewhere.
OLLAMA_INTERNAL_URL=http://ollama:11434
OLLAMA_NUM_PARALLEL=2
OLLAMA_MAX_LOADED_MODELS=2

# WhatsApp Evolution API
WHSP2_EVOLUTION_BASE_URL=whsp2-evo.${DEPLOYMENT_DOMAIN}
WHSP2_EVOLUTION_API_KEY=change_me_to_secure_api_key
WHSP2_APP_BASE_URL=whsp2.${DEPLOYMENT_DOMAIN}


# Plane MCP Server (internal only - used by LibreChat)
# NOT the same thing as PROJECT_PLN_BASE_URL (the bottom of this file): this is Plane CLOUD's API
# root, that is the origin of the self-hosted instance. A blanket rename of one to the other fed the
# cloud URL into the app as its own public origin — WEB_URL became "https://https://api.plane.so"
# and CORS_ALLOWED_ORIGINS was rejected by Django with corsheaders.E014.
PLANE_API_KEY=CHANGE_ME
PLANE_WORKSPACE_SLUG=your-workspace-slug
PLANE_BASE_URL=https://api.plane.so

# SearXNG (self-hosted web search - no external API keys needed)
SEARXNG_INSTANCE_URL=http://searxng-bina-deployment:8080

# Firecrawl (self-hosted web scraper - no external API keys needed)
FIRECRAWL_API_URL=http://firecrawl-api-bina-deployment:3002
FIRECRAWL_API_KEY=CHANGE_ME
FIRECRAWL_BULL_AUTH_KEY=change_me_to_secure_key
FIRECRAWL_VERSION=v1

# Jina AI Reranker (for web search result ranking)
JINA_API_KEY=CHANGE_ME

# General configuration
# TZ=Asia/Jerusalem   # optional: default is the HOST machine timezone

# Balance Sheet Webhook Auth (N8N "Incoming Documents" credential)
BS_WEBHOOK_USER=admin
BS_WEBHOOK_PASS=CHANGE_ME
# 31.97.196.129: Production svm IP
# 24.242.246.1 : willi home
# 187.147.152.83 : random coffee shop
# http://31.97.196.129/
DBS_ALLOWED_IPS=217.132.156.41,31.97.196.82,213.137.71.16,31.97.196.129,24.242.246.1,187.147.152.83

# ChatBase - Multi-account WhatsApp chat management
CHATBASE_BASE_URL=chatbase.${DEPLOYMENT_DOMAIN}
# Generate with: openssl rand -hex 32
CHATBASE_SESSION_SECRET=change_me_to_random_32_hex_chars
CHATBASE_USERNAME=admin
CHATBASE_PASSWORD=change_me_to_secure_password
CHATBASE_ADMINS=
CHATBASE_DAILY_MESSAGE_LIMIT=100

# LibreChat Configuration
LIBRECHAT_BASE_URL=librechat.${DEPLOYMENT_DOMAIN}
# Generate with: openssl rand -hex 16
LIBRECHAT_CREDS_KEY=change_me_to_random_32_hex_chars
# Generate with: openssl rand -hex 16
LIBRECHAT_CREDS_IV=change_me_to_random_16_hex_chars
# Generate with: openssl rand -hex 32
LIBRECHAT_JWT_SECRET=change_me_to_random_32_hex_chars
# Generate with: openssl rand -hex 32
LIBRECHAT_JWT_REFRESH_SECRET=change_me_to_random_32_hex_chars
LIBRECHAT_ALLOW_REGISTRATION=false
LIBRECHAT_RAG_DB_PASSWORD=change_me_to_secure_password
LIBRECHAT_EMBEDDINGS_PROVIDER=openai
OPENAI_API_KEY=CHANGE_ME

# Task Runner Auth Token (production external mode)
# Generate with: openssl rand -hex 32
N8N_RUNNERS_AUTH_TOKEN=CHANGE_ME

# GlitchTip error tracking configuration
GLITCHTIP_BASE_URL=glitchtip.${DEPLOYMENT_DOMAIN}
# Generate with: openssl rand -hex 32
GLITCHTIP_SECRET_KEY=CHANGE_ME
# Generate with: openssl rand -hex 16
GLITCHTIP_DB_PASSWORD=CHANGE_ME
# SMTP format: smtp://user:password@smtp.example.com:587
GLITCHTIP_EMAIL_URL=consolemail://
# Derived like every other address on this deployment. It used to be a literal
# person3@example.com, which is how the LIVE .env ended up sending alert mail
# from a domain the deployment no longer serves while DEPLOYMENT_DOMAIN said something else.
GLITCHTIP_FROM_EMAIL=noreply@${DEPLOYMENT_DOMAIN}
GLITCHTIP_MAX_EVENT_LIFE_DAYS=90
GLITCHTIP_ENABLE_REGISTRATION=true
GLITCHTIP_ENABLE_ORG_CREATION=false
# Declarative bootstrap (scripts/glitchtip-push): admin user + org + projects with
# DETERMINISTIC DSNs are auto-created on bring-up. Set the *_SENTRY_DSN above from the
# DSNs it prints (they're stable across `down -v` — derived from GLITCHTIP_SECRET_KEY).
GLITCHTIP_ADMIN_EMAIL=ci@local.dev
GLITCHTIP_ADMIN_PASSWORD=CHANGE_ME
GLITCHTIP_ORG_NAME=${BUSINESS_NAME}
# The org's URL slug — what the alerts poller (`notifications`) puts in every GlitchTip API path.
# It was never declared here, so BOTH consumers fell through to a literal `hacohen`
# (platform-base/notifications/docker-compose.yml and app.py): any other company's deployment
# polled an org that does not exist, got 404, and showed an empty — not failing — alerts screen.
# Same slug as everything else, so the org GlitchTip creates and the org we poll cannot diverge.
GLITCHTIP_ORG_SLUG=${COMPANY_SLUG}


# Authentik (Auth Service) configuration
AUTHENTIK_BASE_URL=auth.${DEPLOYMENT_DOMAIN}
# LOCAL-PARITY toggle: make the embedded outpost redirect *.localhost forward-auth
# to a locally-reachable, same-instance auth host. On a LOCAL dev box uncomment:
#   AUTH_EXTERNAL_URL=auth.localhost
#   AUTH_PROTOCOL=http
# On the VPS / any public deploy, LEAVE BOTH UNSET — they default to
# https://${AUTHENTIK_BASE_URL}, so prod is unchanged. (Never copy a local .env to prod.)
# Generate with: openssl rand -hex 50   (hex — NO line wraps, NO special chars)
# ⚠️ Do NOT use `openssl rand -base64 60`: it WRAPS its output at column 64, and that
# wrap-newline (a stray \r on Windows) gets captured INTO the value. A CR mid-key makes
# authentik's embedded outpost send an invalid Authorization header → it loads zero
# providers → every Authentik-gated app (browser42.localhost, machine.localhost, …)
# returns "Not Found" (forward-auth 404). If you must use base64, strip newlines:
#   openssl rand -base64 60 | tr -d '\n'
AUTHENTIK_SECRET_KEY=CHANGE_ME
# Generate with: openssl rand -hex 16
AUTHENTIK_POSTGRES_PASSWORD=CHANGE_ME
# Initial admin credentials (only used on first start)
AUTHENTIK_BOOTSTRAP_USER=akadmin
AUTHENTIK_BOOTSTRAP_PASSWORD=CHANGE_ME
AUTHENTIK_BOOTSTRAP_EMAIL=admin@${DEPLOYMENT_DOMAIN}
# Bootstrap API token (auto-creates on first start, used by Homepage widget)
# Generate with: openssl rand -hex 32
AUTHENTIK_BOOTSTRAP_TOKEN=CHANGE_ME
# Google OAuth (configure in Authentik admin after first login)
# https://console.cloud.google.com/apis/credentials
GOOGLE_OAUTH_CLIENT_ID=
GOOGLE_OAUTH_CLIENT_SECRET=


CHANGE_ME

# Machine dashboard
MACHINE_BASE_URL=machine.${DEPLOYMENT_DOMAIN}
# Comma-separated allow-list. Leave empty to disable cleanup execution.
MACHINE_CLEANUP_ALLOWED_ACTIONS=

# browser42 — stealth browser + Playwright MCP + live view
BROWSER42_BASE_URL=browser42.${DEPLOYMENT_DOMAIN}
# CPU ceiling for the shared Chromium. Host-dependent, so it is env-driven: docker REFUSES to
# create a container whose cpu limit exceeds the engine's core count, and that single refusal
# aborts the whole app rather than warning — "range of CPUs is from 0.01 to 4.00, as there are
# only 4 CPUs available" — leaving a successful build and zero containers. 6 is a ceiling, not a
# reservation: keep it on a big host, and `bbox run`/`bbox up` lowers it to the host's core count
# via `bbox_clamp_cpus_to_host` (it rewrites `*_CPUS=` keys in .env, which is why this one is a
# key and not a literal).
BROWSER42_CPUS=6
# The same rule for n8n's database, which was the LAST literal CPU ceiling on the platform: as a
# literal it could not be sized by a profile nor lowered by a host, so `bbox run` aborted the whole
# bring-up on a 2-core machine ("range of CPUs is from 0.01 to 2.00") — measured 2026-09-30 when an
# office was converged onto a 2-core server. 3 is a ceiling, not a reservation.
N8N_DB_CPUS=3
# Size of the virtual desktop Chromium renders into. It is not a cosmetic knob: the container has
# no GPU (--ozone-platform=x11 + software rasterization), so every pixel is composited on the CPU
# and then VNC-encoded — the cost scales with the pixel count even when nobody is watching. 1280x800
# is 44% of 1920x1080. A human opening /view loses nothing: noVNC runs with resize=remote and
# re-negotiates the desktop to the viewer's own window.
BROWSER42_SCREEN_WIDTH=1280
BROWSER42_SCREEN_HEIGHT=800
# Idle sleep: after this many seconds with no agent verb, no /view session, no tab change and no
# live task, Chrome exits gracefully (session, cookies and logins stay in the profile) and nothing
# relaunches it until the next use — an idle headed Chromium otherwise holds ~75% of a core and,
# under load, crash-restarts itself (measured 2026-09-30). The next MCP call, `bbox b42` verb or
# /view visit wakes it and --restore-last-session brings the tabs back. Runtime override:
# `bbox b42 sleep after <seconds>` (data/browser42/settings.json). 0 = never sleep.
BROWSER42_IDLE_SLEEP_S=120

# bina-ds agent.v1 adapter (ai/context/agent-contract.md): where the docker host publishes it. Loopback
# only by default — `bbox agent` reaches it on 127.0.0.1 from Linux, WSL and the macOS engine alike.
BINA_DS_AGENT_BIND=127.0.0.1
BINA_DS_AGENT_PORT=3081
# noVNC password — OPTIONAL extra factor. Leave EMPTY (default) to disable VNC auth:
# access is already gated by Authentik at the edge. Set a strong value to require it.
BROWSER42_VNC_PASSWORD=
CHANGE_ME
BROWSER42_MCP_TOKEN=CHANGE_ME
# Debug mode for the Playwright MCP. Set non-empty (e.g. 1) to enable: a full
# per-action session log + Playwright trace are written to data/browser42/output/,
# and verbose MCP logs go to the container's stderr (docker logs). Empty = off.
BROWSER42_DEBUG=
# Passphrase for production/browser42/browser42-state.sh {dump,load,verify}. When set,
# those commands use it automatically (no prompt) so local dump/restore is seamless.
# Per-host secret: stays in this gitignored .env, never travels with the .enc dump.
# For cross-host restore, share it out-of-band and set it in the target host's .env.
BROWSER42_STATE_PASSPHRASE=

CHANGE_ME
FV_BASE_URL=fv.${DEV_DOMAIN}
FV_SCHEDULE_MINUTES=0
# Generate from n8n UI: Settings → n8n API
N8N_API_KEY=CHANGE_ME

N8N_WEBHOOK_USER=cicd
N8N_WEBHOOK_PASS=CHANGE_ME

# Rocket.Chat
ROCKETCHAT_BASE_URL=rocketchat.${DEPLOYMENT_DOMAIN}

# Supabase (Self-Hosted) configuration
SUPABASE_DB_NAME=postgres
SUPABASE_DB_USER=postgres
SUPABASE_DB_PASSWORD=CHANGE_ME
SUPABASE_DB_PORT=5433
# Generate with: openssl rand -hex 32
SUPABASE_JWT_SECRET=CHANGE_ME
# Generate with: openssl rand -hex 32
SUPABASE_COOKIE_KEY=CHANGE_ME
# Note: Generate JWT tokens for ANON_KEY and SERVICE_KEY using jwt.io or the provided script
# ANON_KEY: Generate with HS256, payload: {"iss":"supabase","role":"anon"}
# SERVICE_KEY: Generate with HS256, payload: {"iss":"supabase","role":"service_role"}
SUPABASE_ANON_KEY=CHANGE_ME
SUPABASE_SERVICE_KEY=CHANGE_ME
SUPABASE_BASE_URL=supabase.${DEV_DOMAIN}
SUPABASE_STUDIO_BASE_URL=supabase-studio.${DEV_DOMAIN}
SUPABASE_FILE_SIZE_LIMIT=52428800
SUPABASE_STORAGE_BUCKET=default

# ── incoming-documents (Phase 3) ──────────────────────────────────────
INCOMING_DOCS_ENABLED=true
INCOMING_DOCS_API_PREFIX=/incomingDocuments
INCOMING_DOCS_TOPIC_PREFIX=incoming-documents
INCOMING_DOCS_BASE_URL=incoming-documents.${DEV_DOMAIN}

# n8n credential lookup (Phase 3.1) — apitools reads + decrypts the
# matching n8n credential at backend init time. Email/name substring
# selects which row to use when several credentials of the same type
# exist (e.g. multiple Google accounts).
N8N_DB_DSN=postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@n8n-postgres:5432/${POSTGRES_DB}
GSHEET_CREDS_EMAIL=your-service-account@example.com
# GSHEET_SA_CREDS_NAME=Document AI Connection  # SA lacks Sheets/Drive perms; using OAuth path
SUPABASE_CREDS_NAME=Supabase account

# --- n8n OAuth client overrides ----------------------------------------
# Injected into n8n via CREDENTIALS_OVERWRITE_DATA (assembled in compose) so the
# stored credentials need only hold OAuth tokens, not the client id/secret.
# Get these from https://console.cloud.google.com/apis/credentials
# NOTE: distinct from GOOGLE_OAUTH_CLIENT_* above (those are reserved for Authentik).
# Shared Google client for Sheets / Drive / Sheets-Trigger nodes
N8N_GOOGLE_OAUTH_CLIENT_ID=your-google-client-id.apps.googleusercontent.com
N8N_GOOGLE_OAUTH_CLIENT_SECRET=CHANGE_ME
# Gmail client (can be a separate Google project)
N8N_GMAIL_OAUTH_CLIENT_ID=your-gmail-client-id.apps.googleusercontent.com
N8N_GMAIL_OAUTH_CLIENT_SECRET=CHANGE_ME

# Anthropic API key — used by the proxy for Claude model passthrough.
# When a claude-* model is requested, the proxy forwards directly to Anthropic.
# Set this to a valid Anthropic key to enable Claude models.
ANTHROPIC_API_KEY=CHANGE_ME

# DeepSeek V4 Pro — used by anthropic-proxy for DeepSeek model routing
DEEPSEEK_API_KEY=CHANGE_ME
DEEPSEEK_BASE_URL='https://api.deepseek.com'
# Generate with: openssl rand -hex 32
AGENT_RUNNER_TOKEN=CHANGE_ME
AGENT_RUNNER_MAX_CONCURRENCY=3
AGENT_RUNNER_TIMEOUT_MS=600000
ANY_CONCURRENCY_BASE_URL=any-concurrency.${DEPLOYMENT_DOMAIN}

# OpenPilot AI Development Platform
AUTOPILOT_BASE_URL=autopilot.${DEV_DOMAIN}

# ── OpenHands AI Coding Platform ─────────────────────────────────────────
OPENHANDS_BASE_URL=openhands.${DEPLOYMENT_DOMAIN}
# The openhands dispatcher's public host (Telegram webhook target + every link its bot sends).
DISPATCH_BASE_URL=dispatch.${DEPLOYMENT_DOMAIN}
# Generate with: openssl rand -hex 32
OPENHANDS_JWT_SECRET=change_me_to_random_32_hex_chars
# Dispatcher bridge (WhatsApp → OpenHands)
# Generate with: openssl rand -hex 32
DISPATCHER_TOKEN=CHANGE_ME

# ── Development Projects ────────────────────────────────────────────────
HELLO_BASE_URL=hello.${DEV_DOMAIN}
CHESS_BASE_URL=chess.${DEV_DOMAIN}
TELEGRAM_BOT_TOKEN=CHANGE_ME
# errorHandler01's Telegram alert branch (n8n). Gated OFF by default: `apps/n8n/hooks/push`
# (gate_telegram_notifier) only enables the node when this is exactly "true" AND TELEGRAM_BOT_TOKEN
# above is set to a real token (not empty, not this placeholder) — either condition failing leaves
# the branch disabled so the handler cannot fail on its own notifier.
ERROR_NOTIFY_TELEGRAM=false
# glitchtipReporter01's HTTP send to GlitchTip. Same gate shape as ERROR_NOTIFY_TELEGRAM above:
# `apps/n8n/hooks/push` (gate_glitchtip_reporter) only enables the send when this is
# exactly "true" AND N8N_SENTRY_DSN is set AND the ingest host answers from inside n8n. Anything
# else writes REPORTING_ENABLED=false into the reporter's GEN:REPORT_GATE block, so the execution
# records a visible `__report_skipped` with the reason instead of attempting a doomed POST.
# Default false: on 2026-08-06 a stopped glitchtip turned every error into a reporter failure,
# which (via a stale exclusion id in step 3b) re-entered errorHandler01 and span a ~1,200/hour
# reporter<->handler cycle that was 93% of the entire error board. Independently of this flag the
# reporter can no longer EMIT an error at all — HTTP Request has onError=continueErrorOutput into
# a "Sink Unreachable (suppressed)" node — but leaving the send off when there is no sink keeps
# the noise out of the execution list too.
ERROR_REPORT_GLITCHTIP=false

# ktivayehudit-clone2 static site
KTIVAYEHUDIT_CLONE2_BASE_URL=ktivayehudit-clone2.${DEV_DOMAIN}
GEMINI_API_KEY=CHANGE_ME

# --- n8n adjacent-automation creds (env-managed via blueprint credential_overrides) ---
# MCP_AUTH_TOKEN: header-auth token for the n8n MCP Server Triggers (generate: openssl rand -hex 24)
MCP_AUTH_TOKEN=CHANGE_ME
# Priority ERP basic-auth (httpBasicAuth creds). Leave blank if not using Priority.
PRIORITY_USER=
PRIORITY_PASS=
CHANGE_ME
PRIORITY_TEST_PASS=
CHANGE_ME
 escapes.
DOCUMENT_AI_SA_EMAIL=
DOCUMENT_AI_SA_PRIVATE_KEY=

CHANGE_ME
GOOGLE_VISION_API_KEY=CHANGE_ME
SETTINGS_AUTH_USER=settings
SETTINGS_AUTH_PASS=CHANGE_ME
# Optional: override OAuth redirect base for local n8n creds (e.g. http://127.0.0.1:5678). Blank=use N8N_BASE_URL.
N8N_OAUTH_BASE=
# THE SCHEME n8n ITSELF ADVERTISES (editor base URL, webhook URL, the push-origin header). It is
# correct as `https` for any real DEPLOYMENT_DOMAIN, and WRONG on a `DEPLOYMENT_DOMAIN=localhost`
# deployment: traefik serves `*.localhost` on the plain `web` entrypoint and ACME cannot issue a
# certificate for a `.localhost` name, so nothing is listening on 443 there.
#
# ==> ON A LOCALHOST DEPLOYMENT, SET THIS TO `http`. <==
#
# Six places default to `${N8N_PROTOCOL:-https}` (apps/n8n/docker-compose.yml ×5,
# apps/any-concurrency/docker-compose.yml ×1) and compose cannot branch on the host, so
# this single line is what makes them right. The one symptom it used to produce that reached a
# user — any-concurrency's "open in n8n" deep link emitting https:// for n8n.localhost — no longer
# depends on it: that builder now derives the scheme from the host family itself
# (`_public_n8n_url()` in apps/any-concurrency/app.py, and `_public_url()` in
# platform-base/connections/app.py for the same class of "open app" link). n8n's OWN advertised
# URLs still follow this variable.
N8N_PROTOCOL=https

# apitools OCR engine: local (Tesseract) avoids Google Vision billing
OCR_ENGINE=local

# ── Integration-API backends ──
# indox api (data): supabase ONLY — google sheets is fully legacy (the old
# INDOX_DATA_BACKEND toggle is gone; indoxApiRouter01 talks only to supabase).
#
# DRIVE_BACKEND / GMAIL_BACKEND were removed here (contract §4). driveApi01 / gmailApiRouter01 call
# the drive (:8975) and mail (:8970) services unconditionally and hold no Google credential. Which
# account an op runs on is now the SERVICE's active connection — pick it in the drive/mail UI (or
# POST /connections/select); GET /readyz names the one that is actually live. It is a per-deployment
# choice made against the real account, not a constant baked into a workflow at push time.

# ── Business-document legal layer (apitools doc_data) ──
# Digital signature (מסמך ממוחשב): default = dev self-signed (NON-CERTIFIED).
# For a LEGAL original, supply a CA-issued cert and attest it:
#   SIGN_CERT_P12=/run/secrets/signer.p12
#   SIGN_CERT_PASSWORD=...
#   SIGN_CERT_CERTIFIED=true
# Allocation number (חשבוניות ישראל / SHAAM): stub (dev) | live (real ITA API).
ALLOCATION_BACKEND=stub
#ITA_ALLOCATION_URL=https://...
#ITA_ALLOCATION_TOKEN=...
SUPABASE_POSTGRES_PASSWORD=CHANGE_ME
SUPABASE_AUTHENTICATOR_PASSWORD=CHANGE_ME
TRUST_EDGE_AUTH=true

# The chat relay's own signing key (32-byte hex, == openssl rand -hex 32). Auto-minted by
# connections when absent; set it here to pin one. Stable across restarts by design.
CHAT_RELAY_KEY=

CHANGE_ME
# the shipped defaults used to be the word "plane". Generated on a fresh machine by
# scripts/ci-env.sh; rotate them while the instance is empty — that means recreating
# plane-db and plane-mq, which are the only places these are stored.
PLANE_DB_PASSWORD=
CHANGE_ME
# (apps/project-pln/patches/redis-broker.py). A leftover key in an existing .env is simply ignored.
PLANE_S3_SECRET_KEY=

CHANGE_ME
# refuses every sign-in until somebody fills in the instance-admin form under /god-mode/ and then
# creates a workspace by hand. apps/project-pln/hooks/onboard applies bootstrap.yaml instead
# (declarative, idempotent, and it runs on every `bbox run`), and signs the owner in with these.
#
# The email defaults to N8N_OWNER_EMAIL — the same human everywhere in this office. The PASSWORD is
# deliberately NOT inherited from n8n (that would copy a secret into a second product's database for
# no gain): leave it empty and the hook mints one INTO THIS FILE on first use, never printing it.
# Set it by hand only while the instance is still empty, and then run ./bbox run.
PLANE_OWNER_EMAIL=
PLANE_OWNER_PASSWORD=
CHANGE_ME
PLANE_OWNER_LASTNAME=
# One-off hand-over, for an instance that already has an administrator and should belong to someone
# else: name that person in PLANE_OWNER_EMAIL, set this to 1, and run ./bbox project-pln onboard.
# Without it the hook refuses to add or replace an owner — releasing an administrator is not a
# decision a bring-up may reach on its own. The old admin row is soft-deleted (running again with
# its address puts it back) and the hand-over is named in the hook's output.
PLANE_OWNER_TAKE_OVER=

# ── Plane (apps/project-pln) ────────────────────────────────────────────────────────────────────
# The public origin exactly as the browser spells it (see apps/project-pln/README.md). Plane's
# WEB_URL, CORS_ALLOWED_ORIGINS and its attachment URLs all hang off these two values.
PROJECT_PLN_BASE_URL=plane.${DEPLOYMENT_DOMAIN}
# The scheme a browser reaches THIS office on — the office's own, never a constant. It said `https`
# here, so an office on `http://…localhost` (every laptop) brought Plane up advertising
# https://plane.localhost: a sign-in that redirects to a host nothing serves (hp-laptop, 2026-10-05).
PROJECT_PLN_PROTOCOL=${AUTH_PROTOCOL}
# The FULL browser origin (scheme + port), for Plane's own WEB_URL/CORS — ONLY when it is not
# `<PROJECT_PLN_PROTOCOL>://<PROJECT_PLN_BASE_URL>`, which is what the app derives when this is
# empty (and which already carries the port on an engine whose edge is not on 80/443).
PROJECT_PLN_PUBLIC_URL=
# ── prebuilt images (DGO-41) ─────────────────────────────────────────────────────────────────────
# Which tag of ghcr.io/solomonboltin/digital-office/<app> this deployment pulls when the CI-images
# overlay is applied (`OVERLAYS=platform/profiles/ci-images.yml ./scripts/dc up -d --no-build`).
# `latest` follows the branch; a commit SHA pins exactly what the declaration names. Unset = the
# services are built from source, which stays the default (a GHCR package from a private repo is
# private, and a fresh clone must not depend on reaching it).
IMAGE_TAG=latest

# ── which REMOTE console may frame this office's agent (DGO-30/32) ─────────────────────────────
# A served tile lives on the SERVING office's console as a NESTED host —
# `<alias>.console.<that office's domain>` — and the harness (apps/bina-ds) refuses every authority
# it was not told about. Name here each office that may show this agent, space-separated and
# port-less; empty means only this office frames it. The compose turns this into DSH_TRUSTED_HOSTS.
# On a `.localhost` edge add the nested host in BOTH spellings — the console frames it with its own
# port when the edge is on :8080 (`externalUrl()`), and the harness matches the authority literally:
# measured 2026-10-05, `Host: bina.macbook.console.localhost` and `…:8080` both answered 403 on
# /api while every request was addressed to the wrong office through the console's origin.
BINA_DS_TRUSTED_HOSTS=

# ── this office's own tunnel listen port (dgo-extend/net.py:local_listen_port) ───────────────────
# Empty = the pair's port (51820). Only the DIALING side may set it: the far end's port is the
# address this office dials (`<peer endpoint>:51820`) and moving it unilaterally is a link that stops
# handshaking with no error anywhere. Set it when the path blackholes the one flow sourced from
# 51820 while every other flow from the same machine crosses — measured 2026-10-04 on the macbook,
# where 51830 handshook in 10 seconds and the link had been dead for 15 hours. See
# ai/context/connection-status-standard.md §1.
DGO_WG_PORT=
# A LISTENING office (one that another office dials after a screen pairing) declares where it is
# reached: DGO_WG_ENDPOINT is the host/IP the other side dials, DGO_WG_PUBLISH_PORT the UDP port
# `dgo-net` publishes for it, DGO_WG_PUBLISH_BIND=0.0.0.0 turns the publication on (default: loopback,
# i.e. nothing reachable). Set DGO_WG_PORT to the same port. Leave all three empty on an office that
# can only dial (a Mac). The machine's own firewall must allow the UDP port — on Windows that is one
# rule in the Hyper-V firewall, created once by an administrator.
DGO_WG_ENDPOINT=
DGO_WG_PUBLISH_PORT=
DGO_WG_PUBLISH_BIND=
# A LOCAL office (DEPLOYMENT_DOMAIN empty or localhost) does this for itself: on a machine that can
# receive a packet, `bbox run` (apps/dgo-extend/hooks/prepare) fills the three keys above with the
# machine's LAN address and port 51830 and marks them DGO_WG_AUTO=1 — an address it wrote, which it
# also follows when the lease moves. DGO_WG_AUTO=0 is yours to write: "this office only dials".
# An address YOU declared (no DGO_WG_AUTO=1 beside it) is never rewritten, and a public server is
# never made dialable by default.
DGO_WG_AUTO=
# Written by the same hook, never by hand: WHY this machine cannot be dialed, where it cannot —
# `wsl-nat` (Windows whose WSL is not in mirrored networking) or `engine-guest` (the macOS engine).
# The office's screen turns it into a sentence with what would change it; the hook clears it on the
# first run in which the machine can receive.
DGO_WG_DIAL_ONLY=
