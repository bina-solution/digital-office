# Master Key Table — every `.env` secret & setting (companion to `central-business-system-master-map.md`)

One `.env` at repo root (gitignored; `cp .env.ex .env`) feeds `docker compose` for the whole stack.
`DEPLOYMENT_DOMAIN` is declared once; every `*_BASE_URL`/`*_HOST` derives from it. Everything marked
`change_me…`/`your-…`/empty in `.env.ex` is a placeholder that MUST be overwritten before a real bring-up.

**Kind legend:** **text-secret** (random hex/opaque token) · **password** (human login) · **app-password**
(provider-issued, e.g. Gmail IMAP) · **oauth** (client id/secret + browser consent) · **qr-session**
(WhatsApp Baileys `auth_info`) · **dsn** (Sentry/GlitchTip or Postgres DSN) · **url/config**
(non-secret host/flag/tunable) · **derived** (computed from another var — GlitchTip DSNs from
`GLITCHTIP_SECRET_KEY`, Supabase JWTs from `SUPABASE_JWT_SECRET`).

## Deployment / domain / edge
| Key | Purpose | Consumed by | Kind | Required? | Default? |
|---|---|---|---|---|---|
| `DEPLOYMENT_NAME` | container-name suffix + compose project | all / bbox | url/config | yes | `bina-deployment` |
| `DEPLOYMENT_DOMAIN` | root domain; every host derives | traefik/all | url/config | **yes (per-tenant)** | `hacohen.bina-solutions.co.il` (Hacohen-locked) |
| `DEV_DOMAIN` | dev subdomain base | traefik | derived | no | yes |
| `TRAEFIK_API_BASE_URL` / `_DASHBOARD` / `_INSECURE` / `TRAEFIK_ACME_EMAIL` | dashboard host + toggles + ACME email | traefik | url/config | ACME email for TLS | hosts yes; email `you@example.com` |
| `PORTAINER_BASE_URL` | portainer host (pw in `portainer_password.txt`, auto-gen) | portainer | url/config | no | yes |
| `TZ` | timezone | all | url/config | no | `Asia/Jerusalem` |
| `DBS_ALLOWED_IPS` | IP allow-list for TCP redis/postgres entrypoints | traefik | url/config | no | **literal operator IPs (de-Hacohen)** |

## n8n DB + core
| Key | Purpose | Consumed by | Kind | Required? | Default? |
|---|---|---|---|---|---|
| `POSTGRES_USER` / `POSTGRES_DB` | n8n Postgres user/db | n8n-postgres, creds `tJ195…`/`CPi9…` | url/config | yes | `hacohen` / `n8n` |
| `POSTGRES_PASSWORD` | n8n Postgres password | n8n-postgres, `N8N_DB_DSN` | **password** | **yes** | `change_me…` |
| `N8N_VERSION` | single source of truth for n8n image (main+workers+runners MUST match) | n8n build | url/config | yes | `2.17.0` |
| `N8N_BASE_URL` | n8n public host | n8n/traefik | url/config | yes | derived |
| `N8N_ENCRYPTION_KEY` | **AES key encrypting ALL n8n creds at rest** | n8n | **text-secret** | **yes** | `change_me…` (`openssl rand -hex 32`) |
| `N8N_USER_MANAGEMENT_JWT_SECRET` | login session JWT signing | n8n | **text-secret** | **yes** | `change_me…` |
| `N8N_OWNER_EMAIL/_PASSWORD/_FIRSTNAME/_LASTNAME` | owner bootstrapped via REST `/owner/setup` by n8n-push | n8n-push | password | **yes** | `admin@example.com` / `ChangeMe1` |
| `N8N_SECURE_COOKIE` / `_LOG_LEVEL` / `_WEBHOOK_TTL` | runtime flags | n8n | url/config | no | `true`/`info`/`1500` |
| `N8N_RUNNERS_AUTH_TOKEN` | task-runner ↔ n8n auth | n8n + runners | **text-secret** | if external runners | `change_me…` |
| `N8N_API_KEY` | public REST API key (`Fxy5…`); minted per-instance in UI | apitools, FV, n8n cred | **text-secret (per-instance)** | for API flows | `your-n8n-api-key-here` |
| `N8N_WEBHOOK_USER` / `_PASS` | CI/CD webhook basic-auth (`gBwY…`,`dSaW…`) | n8n creds | password | yes | `cicd` / `change_me…` |
| `N8N_DB_DSN` | apitools reads+decrypts n8n creds directly | apitools | dsn | for apitools | `postgresql://…@n8n-postgres:5432/n8n` |
| `N8N_SENTRY_DSN` | n8n error tracking | n8n | dsn (derived) | no (auto) | empty |

## n8n Google OAuth client (via `CREDENTIALS_OVERWRITE_DATA`)
| Key | Purpose | Kind | Required? | Default? |
|---|---|---|---|---|
| `N8N_GOOGLE_OAUTH_CLIENT_ID` / `_SECRET` | shared Google client for Sheets/Drive nodes | **oauth** | **yes for Google automations** | `your-google-…` |
| `N8N_GMAIL_OAUTH_CLIENT_ID` / `_SECRET` | Gmail node OAuth client | **oauth** | if `GMAIL_BACKEND=oauth` | `your-gmail-…` |
> Per-tenant refresh tokens (Gmail `jft0…`, Sheets `e2kn…`, Drive `KirW…`, Sheets-Trigger `DfQP…`) are NOT env-managed; break on encryption-key drift → `PATCH data:{}` + re-consent.

## GlitchTip (alerts) + Sentry DSNs
| Key | Purpose | Kind | Required? | Default? |
|---|---|---|---|---|
| `GLITCHTIP_SECRET_KEY` | Django secret **and** deterministic-DSN seed `sha256(SECRET:name)` | **text-secret** | **yes** | `change_me…` |
| `GLITCHTIP_DB_PASSWORD` | glitchtip Postgres pw | **password** | yes | `change_me…` |
| `GLITCHTIP_ADMIN_EMAIL` / `_PASSWORD` | admin auto-created by glitchtip-push | password | yes | `admin@hacohen…` |
| `GLITCHTIP_ORG_NAME` | org (blueprint) | url/config | no | `Hacohen` (business-locked) |
| `GLITCHTIP_BASE_URL`/`_EMAIL_URL`/`_FROM_EMAIL`/`_MAX_EVENT_LIFE_DAYS`/`_ENABLE_REGISTRATION`/`_ENABLE_ORG_CREATION` | host + SMTP + policy | url/config | no | derived; `consolemail://`; `noreply@hacohen…` |
| `SENTRY_ENVIRONMENT` | env tag | url/config | no | `production` |
| `N8N_SENTRY_DSN`,`APITOOLS_SENTRY_DSN`,`WHATSAPP_HACOHANIM_SENTRY_DSN`,`LIBRECHAT_SENTRY_DSN` | per-app error routing (written back by glitchtip-push) | **dsn (derived)** | no (auto) | empty |

## Authentik (SSO / forward-auth)
| Key | Purpose | Kind | Required? | Default? |
|---|---|---|---|---|
| `AUTHENTIK_BASE_URL` | auth host; providers' `external_host` derive from `*_BASE_URL` | url/config | yes | derived |
| `AUTH_EXTERNAL_URL` / `AUTH_PROTOCOL` | outpost redirect (leave UNSET on prod) | url/config | no (prod) | fall back to `https://${AUTHENTIK_BASE_URL}` |
| `AUTHENTIK_SECRET_KEY` | Django secret; **clean hex ≥50 chars, NO newline** (a CR breaks the outpost → gated apps 404) | **text-secret** | **yes** | `change-me…` (`openssl rand -hex 50`) |
| `AUTHENTIK_POSTGRES_PASSWORD` | authentik Postgres pw | **password** | yes | `change_me…` |
| `AUTHENTIK_BOOTSTRAP_USER` / `_PASSWORD` / `_EMAIL` | initial `akadmin` | password | yes | `akadmin` / `change_me…` |
| `AUTHENTIK_BOOTSTRAP_TOKEN` | API token (homepage widget) | **text-secret** | no | empty (`openssl rand -hex 32`) |
| `GOOGLE_OAUTH_CLIENT_ID` / `_SECRET` | Google social login **in Authentik** (distinct from n8n client; manual admin config) | **oauth** | no | empty |

## WhatsApp (chat/Baileys — live) + Evolution/ChatBase (declared, unbuilt)
| Key | Purpose | Kind | Required? | Default? |
|---|---|---|---|---|
| **`data/auth_info`** (no env var) | Baileys multi-file WhatsApp session — the QR-paired key; deleted on logout → re-pair | **qr-session** | **yes (manual scan)** | none |
| `CHAT_APP_BASE_URL` / `_PORT` | chat host/port | url/config | no | derived / `3000` |
| `CHAT_AUTH_USER` / `_PASS` | chat login + n8n `Chat Auth` cred (`BmKl…`) | password | yes | `chat` / `change-me` (⚠ `.env.ex` also ships `AUTH_PASSWORD=12345`) |
| `WHSP2_EVOLUTION_API_KEY` | Evolution API auth — **declared, no container/code** | text-secret | (unbuilt) | `change_me…` |
| `WHSP2_EVOLUTION_BASE_URL` / `WHSP2_APP_BASE_URL` | Evolution + app hosts — **unbuilt** | url/config | (unbuilt) | derived |
| `CHATBASE_SESSION_SECRET` | chatbase session signing — **unbuilt** | text-secret | (unbuilt) | `change_me…` |
| `CHATBASE_USERNAME` / `_PASSWORD` / `_BASE_URL` / `_ADMINS` / `_DAILY_MESSAGE_LIMIT` | chatbase — **unbuilt** | password/config | (unbuilt) | `admin` / `change_me…` |

## AI providers + LibreChat
| Key | Purpose | Kind | Required? | Default? |
|---|---|---|---|---|
| `GEMINI_API_KEY` | Google AI; `ai-studio-bs-extraction` cred (`6mfc…`) — invoice/BS extractors | **text-secret (external)** | for Gemini | `your-google-ai-…` |
| `GOOGLE_VISION_API_KEY` | Vision OCR (billing); bypassed by `OCR_ENGINE=local` | **text-secret** | for Vision OCR | `your-google-vision-…` (⚠ **hard-coded fallback in `ocr_processor.py:19`**) |
| `OPENAI_API_KEY` | OpenAI; `OpenAi account` cred (`xu8Y…`) + embeddings | **text-secret (external)** | for OpenAI | `sk-your-…` |
| `ANTHROPIC_API_KEY` | Claude via anthropic-proxy | **text-secret (external)** | for Claude | `sk-ant-your-…` |
| `DEEPSEEK_API_KEY` / `_BASE_URL` | DeepSeek routing | text-secret / url | no | `sk-your-…` |
| `JINA_API_KEY` | reranker for web search | **text-secret** | no | `your-jina-…` |
| `LIBRECHAT_CREDS_KEY`(hex32)/`_CREDS_IV`(hex16) | encrypt stored LibreChat user creds | **text-secret** | yes (if librechat) | `change_me…` |
| `LIBRECHAT_JWT_SECRET`/`_JWT_REFRESH_SECRET` | session JWTs | **text-secret** | yes (if librechat) | `change_me…` |
| `LIBRECHAT_RAG_DB_PASSWORD` | RAG vector DB pw | **password** | yes (if librechat) | `change_me…` |
| `LIBRECHAT_BASE_URL`/`_ALLOW_REGISTRATION`/`_EMBEDDINGS_PROVIDER`/`ENDPOINTS` | host + flags | url/config | no | derived / `false` / `openai` |

## Supabase (self-hosted shared data layer)
| Key | Purpose | Kind | Required? | Default? |
|---|---|---|---|---|
| `SUPABASE_DB_PASSWORD` | Supabase Postgres pw; `INDOX Supabase` cred (`yY8F…`) | **password** | yes | `change_me…` |
| `SUPABASE_JWT_SECRET` | HS256 secret signing ANON/SERVICE keys + PostgREST | **text-secret** | yes | `change_me…` |
| `SUPABASE_COOKIE_KEY` | studio/meta cookie signing | **text-secret** | yes | `change_me…` |
| `SUPABASE_ANON_KEY` / `SUPABASE_SERVICE_KEY` | JWTs from `SUPABASE_JWT_SECRET` (via `supabase-keygen.py`); service key → `supabaseStorage001` | **derived (JWT)** | yes | `your-supabase-…jwt` |
| `SUPABASE_DB_NAME/_DB_USER/_DB_PORT/_BASE_URL/_STUDIO_BASE_URL/_FILE_SIZE_LIMIT/_STORAGE_BUCKET/_CREDS_NAME` | config | url/config | no | `postgres`/`postgres`/`5433`/…/`52428800`/`default` |
| `SUPABASE_DASHBOARD_USERNAME` / `_PASSWORD` | kong basic-auth | password | no | change_me |

## Redis / Firecrawl / SearXNG / Ollama (in-network)
| Key | Purpose | Kind | Required? | Default? |
|---|---|---|---|---|
| `REDIS_PASSWORD` | Redis auth; `Redis Local` cred (`BoJE…`) + authentik redis | **password** | **yes** | `change_me…` |
| `REDIS_HOST`/`REDIS_PORT`/`REDISINSIGHT_BASE_URL` | hosts | url/config | no | derived / `6379` |
| `FIRECRAWL_BULL_AUTH_KEY` | firecrawl queue auth | **text-secret** | yes (if firecrawl) | `change_me…` |
| `FIRECRAWL_API_URL`/`_API_KEY`/`_VERSION` | self-hosted scraper | url/config | no | in-network / `fc-selfhosted` / `v1` |
| `SEARXNG_INSTANCE_URL` | self-hosted search | url/config | no | in-network |
| `OLLAMA_INTERNAL_URL` | in-network n8n→ollama (`7EtG…`) | url/config | no | `http://ollama:11434` |
| `OLLAMA_BASE_URL`/`_NUM_PARALLEL`/`_MAX_LOADED_MODELS` | host + tunables | url/config | no | derived / `2` / `2` |

## Gmail-IMAP + integration backends
| Key | Purpose | Kind | Required? | Default? |
|---|---|---|---|---|
| `GMAIL_IMAP_USER` | mailbox address + SMTP login | url/config | yes if IMAP | `person2@example.com` (business-locked) |
| `GMAIL_IMAP_APP_PW` | Google **app password** (full mailbox access) | **app-password** | **yes if IMAP** | `your-gmail-app-password` |
| `GMAIL_IMAP_HOST`/`_PORT` / `GMAIL_SMTP_HOST`/`_PORT` | servers (safe defaults) | url/config | no | `imap.gmail.com:993` / `smtp.gmail.com:465` |
| `GMAIL_IMAP_MODE` | `gmail` \| `local` (selects backend module) | url/config | no | `gmail` |
| `GMAIL_BACKEND` | `imap` \| `oauth` \| `none` (baked into router at push) | url/config | no | `imap` |
| `LOCALMAIL_USER`/`_PW` (+ `LOCALMAIL_IMAP/SMTP_*`) | GreenMail creds (dev/CI) | config/dev-secret | no | `indox`/`indox` |
| `DRIVE_BACKEND` / `INDOX_DATA_BACKEND` | `google\|local` / `supabase\|sheets` | url/config | no | `google` / `supabase` |
| `GSHEET_CREDS_EMAIL` | which Google cred row apitools uses | url/config | no | `your-service-account@…` |
| `OCR_ENGINE` | `local` (Tesseract) avoids Vision billing | url/config | no | `local` |

## Balance-sheet / settings / MCP / ERP / Document-AI / Kafka (n8n adjacent)
| Key | Purpose | Kind | Required? | Default? |
|---|---|---|---|---|
| `BS_WEBHOOK_USER` / `_PASS` | `Incoming Documents` cred (`azPh…`) | password | yes | `admin` / `change_me…` |
| `SETTINGS_AUTH_USER` / `_PASS` | `Settings Auth` cred (`m44S…`) | password | yes | `settings` / `change-me` |
| `MCP_AUTH_TOKEN` | header-auth for n8n MCP Server Triggers (`2qKU…`,`77wJ…`) | **text-secret** | for MCP | `change-me` (`openssl rand -hex 24`) |
| `PRIORITY_USER`/`_PASS`, `PRIORITY_TEST_USER`/`_PASS` | Priority ERP basic-auth (`LKWC…`,`PKgR…`) | password | no (blank ok) | empty |
| `DOCUMENT_AI_SA_EMAIL` / `_PRIVATE_KEY` | GCP service-account (`wxbv…`); key single-line w/ `\n` | **oauth/SA-key** | no | empty |
| `KAFKA_BOOTSTRAP_SERVERS` / `KAFKA_CLIENT_ID` | Redpanda broker (`bo3Q…`) | url/config | no | `redpanda:9092` / `incoming-documents-api` |
| `INCOMING_DOCS_ENABLED`/`_API_PREFIX`/`_TOPIC_PREFIX`/`_BASE_URL` | pipeline config | url/config | no | `true` / `/incomingDocuments` / … |
| `TELEGRAM_BOT_TOKEN` | `N8N TG LOGGER` cred (`Emuw…`) + dev bot | **text-secret (external)** | no | `your-telegram-bot-token` |

## browser42 / machine / agent-runner / OpenHands / hosts
| Key | Purpose | Kind | Required? | Default? |
|---|---|---|---|---|
| `BROWSER42_MCP_TOKEN` | Bearer required on `/mcp` (fail-closed) | **text-secret** | **yes** | empty (`openssl rand -hex 32`) |
| `BROWSER42_VNC_PASSWORD` | optional noVNC extra factor | **password** | no | empty |
| `BROWSER42_STATE_PASSPHRASE` | passphrase for `b42 dump/load` encrypted state | **password** | for state restore | empty |
| `MACHINE_CLEANUP_ALLOWED_ACTIONS` | allow-list; empty disables cleanup | url/config | no | empty |
| `AGENT_RUNNER_TOKEN` | any-concurrency agent-runner auth | **text-secret** | if used | `change_me…` |
| `OPENHANDS_JWT_SECRET` | OpenHands session JWT | **text-secret** | if used | `change_me…` |
| `DISPATCHER_TOKEN` | WhatsApp→OpenHands bridge auth | **text-secret** | if used | `change_me…` |
| `PLANE_API_KEY` / `_WORKSPACE_SLUG` / `_BASE_URL` | Plane MCP (LibreChat) | **text-secret** / config | no | `your-plane-…` |
| `*_BASE_URL` (MACHINE, HOMEPAGE, BROWSER42, ANY_CONCURRENCY, MORNING, APITOOLS, GLITCHTIP, INCOMING_DOCS, FV, …) | service hostnames | url/config | no | derived from domain |
| `FV_SCHEDULE_MINUTES` | feature-validation cron cadence | url/config | no | `360` |

## Business-document legal layer (apitools doc_data — optional/dev-default)
| Key | Purpose | Kind | Required? | Default? |
|---|---|---|---|---|
| `SIGN_CERT_P12` / `_PASSWORD` / `_CERTIFIED` | CA-issued signing cert for LEGAL originals (else dev self-signed) | **app-password/cert** | no | dev self-signed |
| `ALLOCATION_BACKEND` / `ITA_ALLOCATION_URL` / `_TOKEN` | Israeli Tax Authority allocation-number API (חשבוניות ישראל) | url + **text-secret** | no | `stub` |

> Nit: `FIRECRAWL_VERSION` appears twice in `.env.ex` (lines 112 & 152) — dedupe when productizing.

## Key-kind → unified `connections` sourcing
| Kind | How the connections service sources it |
|---|---|
| text-secret | **Vault-generated on install** (auto-mint, inject, rotate); owner never sees them |
| password (machine) | vault-generated; **human logins** set once via wizard form, stored in vault |
| app-password | **guided-capture UI** → stored as vault text secret |
| oauth | **OAuth broker** owns the client, runs consent, stores+refreshes tokens; owner clicks "Connect" |
| qr-session | **QR pairing UI** renders the Baileys QR inline, persists/mirrors `auth_info`, surfaces "re-pair" |
| dsn / derived | **auto-derived, never asked** (recomputed from root secret / assembled by push scripts) |
| url/config | **`.env` seed / templating** from one `DEPLOYMENT_DOMAIN`; backend toggles become dashboard switches |

## When `.env` is lost or replaced

It happened once (2026-09-29: the generator ran over a live office). Nothing fails at that moment —
every container keeps the environment it was created with — and that is also what makes it
recoverable: the old values are still inside the containers created before the loss. The procedure
that recovered 19 of 19 generated secrets is in
[issues/ci-env-sh-overwrites-a-live-env.yaml](../../issues/ci-env-sh-overwrites-a-live-env.yaml)
("Recovery that worked"). Do it BEFORE the next `up` of any service: a re-created container is
handed the new values, and with it goes the last copy of the old ones. Since then
`scripts/ci-env.sh` refuses to write over an existing `.env` (`CI_ENV_FORCE=1` to force) and names
the file it wrote.
