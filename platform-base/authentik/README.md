# Authentik - Identity & Access Management

Centralized authentication service for the deployment, providing user management, Google OAuth, and Traefik ForwardAuth integration.

## Architecture

| Container | Role | Port |
|-----------|------|------|
| authentik-server | Web UI + API + embedded outpost | 9000 |
| authentik-worker | Background tasks (Celery) | - |
| authentik-postgres | Dedicated PostgreSQL 16 | 5432 |

Uses the shared Redis service (DB index 1) for caching and sessions.

## URL

- **Production**: `https://auth.hacohen.bina-solutions.co.il`
- **Local**: `http://auth.localhost`

## Setup

### 1. Configure environment variables

Copy the Authentik section from `.env.ex` to `.env` and fill in:

```bash
# Generate secret key
openssl rand -base64 60

# Generate DB password
openssl rand -hex 16
```

### 2. Start the service

```bash
docker compose up -d authentik-server authentik-worker authentik-postgres
```

### 3. Initial login

Navigate to `https://auth.hacohen.bina-solutions.co.il/if/flow/initial-setup/`
- If `AUTHENTIK_BOOTSTRAP_PASSWORD` was set: login with `$AUTHENTIK_BOOTSTRAP_USER` (default: `akadmin`) / your bootstrap password
- If not: follow the initial setup wizard

### 4. Configure Google OAuth

1. Create OAuth credentials at https://console.cloud.google.com/apis/credentials
2. Set authorized redirect URI: `https://auth.hacohen.bina-solutions.co.il/source/oauth/callback/google/`
3. In Authentik admin → Directory → Federation & Social login → Create → Google OAuth Source
4. Enter Client ID and Client Secret

### 5. ForwardAuth (Traefik Integration) — Fully Declarative

Sign-in for an app is **declared by the app** and compiled; nothing is added here by hand.

- An app puts `"auth": "sso"` on its `routing[]` entry in its own `app.json` (an installable app
  also carries an `sso` block: slug, display name, the variable that names its host).
- `platform/manager/reconcile.py` (`render_authentik`) writes
  `blueprints/zz-generated-apps.yaml` (gitignored): a **proxy provider** (forward_single) and an
  **application** per host, and the **embedded outpost**'s list of providers. The committed
  `blueprints/deployment-apps.yaml` holds only the base estate (console, connections, machine,
  traefik, apps, any-concurrency).
- **One provider per host, always.** authentik's outpost files providers under `host[:port]`, and a
  second provider for a host freezes its refresh for ever — no host declared after that is served
  until the server is restarted. The compiler therefore writes an app's `-local` twin only where it
  is another host (an edge on a port, or a real domain) and binds the outpost to the first provider
  that names a host.
- An installable app's host is written into the generated blueprint as a **literal**, resolved from
  this office's `.env` at compile time. Only the committed blueprint resolves hosts with `!Env`, and
  the compiler renders exactly those variables onto the three sign-in services.
- A new host reaches the outpost by itself: the worker applies the generated blueprint within
  seconds of every change of the file and tells the outpost, which loads the host. Nothing is
  re-created when an app is switched on or off.
- `outpost-ready.py` is the probe: is every host the compiled blueprint gates served by the outpost?
  It reads the hosts from the blueprint itself (`context.gated_hosts`), so it needs no token and no
  API, and asks about the hosts of THIS render. It is the sentinel's health check
  (`authentik-bootstrap`), the bootstrap gate, and what `hooks/refresh` asks.
- `./bbox authentik refresh` (`hooks/refresh`) asks first and is done in seconds when the answer is
  yes. Otherwise, in the order of cost: it waits (90 s); it has the sentinel apply every blueprint
  again (minutes, no outage) — for a render nobody applied; and only then restarts the server (a
  minute of 404/5xx on every gated host) — for an outpost that will not learn.
- The sentinel (`bootstrap.sh`) applies every blueprint when it starts — a first boot, a change of
  what only it applies (its script, the probe, the committed blueprints, `.env`), or the hook asking.
  It then stays up as the health reporter; it does not exit when the outpost is slow, because
  starting again only applies everything again.

Tests: `bash platform-base/authentik/test_refresh.sh` (when the hook restarts, and when it must
not), `python3 platform-base/authentik/test_outpost_ready.py` (what the probe calls served), and the
blueprint cases in `platform/manager/test_resolve.py`.

### Protected Services

| Service | ForwardAuth | Reason |
|---------|------------|--------|
| Homepage | ✅ Yes | No built-in auth |
| RedisInsight | ✅ Yes | No built-in auth |
| Ollama | ✅ Yes | No built-in auth |
| Traefik Dashboard | ✅ Yes | No built-in auth |
| n8n | ❌ No | Has own user management |
| LibreChat | ❌ No | Has own user management |
| Portainer | ❌ No | Has own password auth |
| GlitchTip | ❌ No | Has own user management |
| Authentik | ❌ No | Must be public for login |

## User Management

- **Groups**: Create groups in admin → Directory → Groups (e.g., `admins`, `developers`, `viewers`)
- **Access policies**: Attach groups to applications to control who can access what
- **Users**: Create in admin → Directory → Users, or let users self-register via Google OAuth
