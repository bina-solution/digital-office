# secret-base — the deployment's secret & credential control plane

**Rename + expansion of `development/connections/`.** "connections" undersells it: it is already the
single encrypted store + declarative catalog + health-probing + injector + OAuth broker for every
secret in the estate. **secret-base** makes that its explicit identity and grows it into the one place
to **view, edit, rotate, and connect** every kind of secret and credential.

---

## 0. What exists TODAY (must be preserved — nothing lost)

`development/connections/` (Flask, ~552 lines, `app.py` + `providers/*.yaml` + `manifests/*.yaml` +
`ui.html` + `cli.py` + `inject.sh` + `rollout/*.override.yml`):

- **Vault** — Fernet-encrypted KV at `data/vault.enc`, unlocked by ONE root key
  (`CONNECTIONS_ROOT_KEY`). Secret-zero. `vault_read/write` (atomic temp+rename).
- **Declarative catalog** — `providers/{10-infra,20-n8n,30-google,40-apps}.yaml`; 51 connections.
  Each entry: `id, title, title_he, kind, env, envs_extra, consumers, probe, now, automint, oauth,
  derive_from, optional`. Grouped by file prefix (Infra&Edge / n8n / Google / Apps&Data).
- **Kinds today** (17 text-secret, 17 password, 5 config, 4 derived, 3 oauth-client, 1 each
  sa-key/qr-session/oauth-grant/cert/app-password).
- **Resolution chain** — `vault DB override (encrypted, wins) → .env (live default) → derived → unset`.
  `resolve()` is read-only; a saved value is stored encrypted and WINS; un-overridden tracks .env live.
- **Auto-mint** — machine secrets (`automint` spec: hex/password) are generated if absent, so `.env`
  entries are OPTIONAL. `mint_pass()` runs once; `regenerate` rotates.
- **Health probes** — `http/tcp/redis/present/derived/qr/oauth-grant` hit the LIVE service, so green
  = it actually works, not just "present." `probe()`.
- **Manifest** — `manifests/consumers.yaml`: per-service `requires` (+ `as:` env-alias renames). Drives
  the install wizard, fail-fast boot, and the injector.
- **Injector** — `GET /api/export/<service>?format=env` resolves a service's required connections →
  `KEY=value` (with `as` aliases + `envs_extra` companions). `inject.sh` + `rollout/*.override.yml`
  make services read secrets FROM here instead of `.env` directly. `GET /api/export-all` = the whole set.
- **OAuth broker** — `/oauth/<cid>/start` + `/oauth/callback`: the WHOLE consent flow lives here;
  exchanges code→tokens, stores in the vault, and **injects into n8n credentials** via n8n's REST API
  (`inject_into_n8n`). "Connect Google" with nothing on the consumer side.
- **QR bridge** — proxies the WhatsApp bot's pairing QR + live state (`/api/qr/<cid>[/png]`) with the
  admin basic-auth, so pairing happens inside the plane.
- **Feature flags** — `/api/features[/<service>]` enable/disable a service (console greys the module).
- **API** — `/api/connections` (status + summary + install_blockers), `set`/`add`/`regenerate`/
  `disconnect`, `resolve`, `manifest`. **Values are MASKED — never leaked today.**
- **UI** — `ui.html` (Bina RTL, embedded in the console as "חיבורים ומפתחות").
- **CLI** — `cli.py`, declarative-driven.

> Every one of these stays. secret-base is a superset.

---

## 1. Vision — three pillars, one base

secret-base is the single pane for everything secret, organized as three pillars over the SAME vault:

1. **סיסמאות אפליקציות — App passwords.** The human/admin login for every app: n8n owner, GlitchTip
   admin, Portainer, chat, Supabase Studio, Authentik akadmin, Grafana, … Each row: app, URL, user,
   password (reveal + copy), rotate, "פתח אפליקציה". This is what the user explicitly asked for —
   "view and edit passwords of n8n, glitchtip, portainer, etc."
2. **סודות תשתית — Infrastructure secrets.** Encryption keys, JWT secrets, root keys, DB passwords,
   DSNs, IP allowlists, deterministic-derived keys. Auto-minted, rotatable, with **impact** (which
   services must restart / re-encrypt on rotation — e.g. `n8n-encryption-key` drift breaks cred
   decryption; the plane warns + can orchestrate).
3. **חיבורי אימות — Auth connections.** A first-class, **protocol-aware** credential manager for
   service/outbound auth — a "Claude-connections"-like system that owns the full lifecycle
   (connect → store → test → refresh → inject → revoke) for MANY protocols:
   - `api-key` / `bearer-token` (single or multi-key, rotatable)
   - `basic-auth` (user + password)
   - `oauth2` (client creds + grant + **auto-refresh**)
   - `qr-session` (Baileys / WhatsApp)
   - `service-account` (Google SA JSON)
   - `certificate` (.p12 signing cert)
   Adding a protocol = one handler + catalog entries. "connections" (the current OAuth/QR flows) is
   just this third pillar.

The current `kind` field maps onto **protocol** (auth pillar) or **pillar** directly; a `pillar` field
is added to the catalog (backward-compat: inferred from kind/group when absent).

---

## 2. Key deltas vs today

| Delta | Today | secret-base |
|---|---|---|
| **Reveal actual value** | masked only, never leaked | **reveal-on-demand** (explicit click → `GET /api/reveal/<cid>` with a confirm; audit-logged). An admin secrets manager must let you SEE + copy the value. |
| **Pillars** | one flat list grouped by file | 3 pillars (app-password / infra / auth-connection) + search + per-pillar health |
| **Protocols** | implicit `kind` | explicit protocol handlers (connect/test/refresh/revoke/inject), extensible |
| **OAuth refresh** | stores grant, no refresh | self-maintained: background refresh of expiring tokens |
| **Edit UX** | prompt() + masked | mature reveal→edit→save inline (datagrid standard), copy, rotate, rotate-impact |
| **Audit** | none | append-only audit log (view/edit/rotate/connect/revoke + when) |
| **App-password affordances** | generic secret rows | app URL + user + "open app" + rotate-and-sync-to-app where possible |
| **Name/brand** | "connections / חיבורים ומפתחות" | **secret-base / בסיס הסודות** |

---

## 3. Data model additions (backward-compatible)

Catalog entry gains (all optional; inferred when absent):
```yaml
- id: portainer-admin
  pillar: app-password          # app-password | infra | auth-connection  (inferred from kind/group if omitted)
  protocol: basic-auth          # for auth-connection pillar
  reveal_ok: true               # may be revealed in the UI (default true for self-hosted admin)
  rotate: true                  # rotatable (automint or app-synced)
  app: {name: Portainer, url_env: PORTAINER_BASE_URL, login: {user_env: ..., pass_env: ...}}
  impact: [portainer]           # services affected by a rotation
```
Vault gains: `__audit__` (append-only event list), unchanged for everything else. New reveal + audit
endpoints; existing endpoints unchanged.

---

## 4. API additions (existing routes unchanged)

- `GET  /api/reveal/<cid>` → the actual resolved value (confirm-gated; audit-logged). **The one route
  that returns a real value** — everything else stays masked.
- `GET  /api/audit` → recent events.
- `POST /api/rotate/<cid>` → generalizes `regenerate` to app-synced rotation where a handler exists.
- `POST /api/conn/<cid>/test` → protocol handler's live test (beyond the passive probe).
- Auth-connection protocol handlers (server-side): `connect`, `test`, `refresh`, `revoke`, `inject`.
- Pillar in `/api/connections` rows (so the UI can group by pillar).

---

## 5. UI — beautiful, three-pillar (Bina, RTL)

- Header: **בסיס הסודות** + one-line health (X healthy / Y need action / Z secrets) + global search + ＋add.
- Three pillar tabs (or sections): **סיסמאות אפליקציות · סודות תשתית · חיבורי אימות**, each a **dense
  DataGrid** (the console's table standard): name (he+id), protocol/kind chip, status dot, source badge,
  **value** (••• → reveal → copy), actions (edit / rotate / reveal / connect / revoke / open-app).
- Auth-connection rows show a protocol icon (🔑 api-key, 👤 basic, 🔓 oauth, 📱 qr, 📄 sa, 🔏 cert) and a
  Connect/Reconnect/Revoke lifecycle + last-refresh.
- Reveal flow: click 👁 → brief confirm → value shown for ~20s + copy, then re-masks; audit event.
- Rotate flow: confirm + show impact ("ישפיע על: n8n — יש להפעיל מחדש") → rotate → optionally trigger.
- Embedded in the console; obeys the console double-nav rule (single-column, no second dark rail).

---

## 6. Rename plan (careful — preserve every wire)

Two-stage to avoid breaking the injector / console / CI:
1. **Rebrand (low-risk, first):** user-facing name → secret-base everywhere the user sees it (UI title,
   console module `חיבורים ומפתחות` → `בסיס הסודות` + id, docs). Internal container/dir/routes stay
   `connections` so `inject.sh`, `rollout/*`, `manifests`, `APP_BASES["connections"]`, CI keep working.
2. **Full rename (later, deliberate):** `development/connections` → `development/secret-base`, container
   `connections-*` → `secret-base-*`, add a compat alias/route for `connections` during transition,
   update `production/compose.yml` include, console `APP_BASES`, `inject.sh` `CONN_URL`, CI, memory.
   Grep-driven, each reference verified, done as ONE reviewed change.

`CONNECTIONS_ROOT_KEY` env keeps working; add `SECRET_BASE_ROOT_KEY` as an accepted alias.

---

## 7. Phased build

- **P0 — pillar+protocol model** in the catalog (add `pillar`/`protocol`/`reveal_ok`/`rotate`/`app`,
  inferred when absent) + `/api/reveal` + `/api/audit`. Backward-compatible.
- **P1 — app-passwords pillar**: catalog every app admin login as `pillar: app-password`; UI pillar with
  reveal/copy/rotate/open-app.
- **P2 — auth-connections protocols**: formalize handlers (api-key/basic/oauth2/qr/sa/cert), OAuth
  auto-refresh, per-connection `test`.
- **P3 — beautiful UI**: three-pillar DataGrid, reveal/rotate/connect flows, audit view.
- **P4 — infra rotation + impact**: rotate encryption keys with orchestration + warnings.
- **P5 — rename** (stage 2) + CLI parity + docs.

Each phase: backward-compatible, verified (once the stack is up), nothing lost.
</content>
