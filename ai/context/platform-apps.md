# How an app works

The complete contract. Companion to [platform-operating.md](platform-operating.md) (how to run it)
and [platform-os-refactor.md](platform-os-refactor.md) (why it is shaped this way).

## An app is a folder with a manifest

```
apps/<id>/
  app.json               the ONLY thing the platform reads. Everything else is the app's business.
  docker-compose.yml     its services
  blueprint/n8n/*.json   its workflows, if it has any
  connections.override.yml   its secret-injection overlay, if it uses the vault
  <anything else>        Dockerfile, source, fixtures, hooks — the platform never looks
```

There is no registration step. Drop the folder in, flip one line of state, run. Nothing else in
the repo has to learn the app's name — that is the whole point, and it is enforced.

## The one rule: dependencies point down, never up

```
apps/ (layer 3)   ──── declares what it needs ────►   platform-base/ (layers 1-2)
platform-base/    ──── NEVER names ───────X──────►    apps/
```

A base app that hardcodes a layer-3 name is broken by definition: uninstall that app and the base
still refers to it. This is not theory — `glitchtip/blueprint.yml` listed `my-docs`, `localdrive`,
`mailview`, `apitools`, and still listed `librechat` and `feature-validation` long after both were
deleted; the console shipped a tile and a proxy route for a service parked in `attic/` that 502'd
on click; authentik published an SSO application for `ollama` while ollama was disabled.

Where a manifest lives **is** its layer, and the loader treats a mismatch as a fatal error, not a
warning. Gate **G9** (`layering-lint.py`) enforces the rule; it parses the documents and counts
only values hanging off keys that actually wire services together, so prose doesn't inflate it.

## What an app declares

### Identity and placement
```json
{ "id": "indox", "layer": 3, "kind": "service",
  "title": {"he": "מסמכים נכנסים", "en": "Incoming Documents"} }
```
`id` must equal the directory name. `layer: 3` must be under `apps/`.

### Capabilities it provides, and needs
```json
"capabilities": [{"name": "indox-api", "type": "protocol", "endpoint": "http://incoming-documents:8080"}],
"use": [
  {"capability": "ocr",   "strength": "requires", "ops": ["documentOcr", "documentJsonQuery"]},
  {"capability": "drive", "strength": "requires", "ops": ["list","download","upload","move"]},
  {"capability": "chat",  "strength": "wants", "dependency": "weak", "ops": ["sendDocument"]}
]
```
Dependencies are on **capabilities**, not names — so any app providing `drive` satisfies it.
`strength` (`requires|wants|requisite|binds_to|conflicts`) says *whether*; `after` says *when*;
`ops` is negotiated — the resolver refuses a provider that lacks an op you require.
`dependency: "weak"` is the only sanctioned way to break a cycle.

### What it contributes INTO a base app
This is how the layering rule survives contact with reality. `any-concurrency` genuinely needs
apitools' container name to tail its logs — but it may not know it. So apitools says so:

```json
"contributes": {
  "env":     {"any-concurrency": {"APITOOLS_CONTAINER": "apitools"},
              "console": {"APITOOLS_URL": "${MY_DOCS_APITOOLS_URL:-http://apitools:8080}"}},
  "volumes": {"connections": ["./apps/chat/data:/wa:ro"]},
  "connection_probes": {"gmail-app-password": "http://mailapi:8970/healthz"}
}
```
The compiler merges these onto the base service. The rendered config is identical to writing them
in the base app's compose — only the *source of the declaration* moves, which is why this costs
nothing at G1. Paths are **repo-root-relative**: they land in the generated overlay, whose
relative paths resolve against `--project-directory`.

### Routing, SSO and its console tile
```json
"routing": [{
  "host": "incoming-documents", "port": 8080, "auth": "sso", "emit_labels": false,
  "sso":    {"slug": "incoming-documents", "base_url_env": "INCOMING_DOCS_BASE_URL",
             "default_host": "incoming-documents.localhost",
             "display_name": "Incoming Documents", "local_twin": false},
  "module": {"alias": "incoming", "name": "מסמכים נכנסים", "icon": "inbox",
             "group": "עסק", "desc": "עיבוד מסמכים אוטומטי", "order": 4, "embed": true}
}]
```
`auth: sso` is mutable, never frozen at install (Cloudron's documented failure mode).
`emit_labels: false` means the app carries its own traefik labels.

### Error reporting
```json
"observability": {"sentry_platform": "python"}
"observability": {"sentry_project": "incoming-docs", "sentry_platform": "python"}
```

### Secrets it needs
```json
"connections": [{"id": "gemini-key", "required": true},
                {"id": "supabase-service-key", "required": true}]
```

## What the compiler does with all of it

`reconcile.py render` reads every manifest plus `platform.state.yaml` and writes `.generated/`:

| Output | Built from | Consumed by |
|---|---|---|
| `compose.yml` | each enabled app's `compose` | docker compose |
| `routing.override.yml` | `routing[]` labels + all `contributes` | docker compose |
| `glitchtip.projects.yml` | `observability{}` | `scripts/glitchtip-push` |
| `registry/console.modules.yaml` | `routing[].module{}` | console (mounted `/app/generated`) |
| `registry/console.app_bases.json` | `routing[].module.alias/url` | console |
| `registry/connections.consumers.yaml` | `connections[]` | connections (mounted) |
| `registry/connections.probes.json` | `contributes.connection_probes` | connections |
| `…/authentik/blueprints/zz-generated-apps.yaml` | `routing[].sso` | authentik (already mounted) |

Everything in that table used to be a hand-edited list of app names living inside a base app.

## The consequence, stated plainly

Set `enabled: false` for an app and re-render. Its container stops **and**: its console tile
disappears, its `/a/<alias>/` proxy route disappears, its SSO provider and application disappear,
its GlitchTip project is no longer requested, its secret requirements leave the connections
manifest, and the env it contributed to base apps is no longer merged.

Nothing has to be remembered and edited in a second place. `ollama` proves it: it ships enabled
`false`, so it produces **no** authentik entries at all — while the old hand-written blueprint
published an SSO application for it regardless.

## Adding an app, end to end

```bash
mkdir apps/my-thing
$EDITOR apps/my-thing/app.json          # id/layer/kind/title + what it uses and contributes
$EDITOR apps/my-thing/docker-compose.yml
$EDITOR platform.state.yaml             # apps: { my-thing: {enabled: true} }
python3 platform/manager/reconcile.py validate   # contract + layer/dir rule
./bbox run
```

Removing it is deleting those two lines of state. Nothing else in the tree mentions it — and
G9 fails the build if anything ever does.

## Proof: a rebuild from absolutely nothing

`bbox reset --force` (20 volumes destroyed) → **every first-party image deleted** → `docker
builder prune -af` → `bbox run`. 2026-07-22, ~16 min to a converged stack.

⚠️ **Use `./scripts/first-party-images --rmi`, not a name-prefix grep.** The first attempt at this
swept `docker images | grep '^deployment-hacohen-'`, which misses any service that overrides
compose's default image name — `incoming-documents-local` and `my-docs-local` both do. So 13 of
15 were rebuilt and indox and my-docs quietly reused day-old images. Both were subsequently
deleted and rebuilt from source, and the sweep now asks compose what it builds.

Verified on that stack, where every value below is COMPILED from `app.json` and appears in no
hand-written file:

```
containers                49 · 34 healthy · 0 unhealthy
console module tiles      12  dashboard pinkas drive mail incoming whatsapp concurrency
                              alerts machine apps connections install     (original order)
connections               51 providers; gemini-key consumers ['apitools','incoming-documents']
                              derived from the apps' own connections[]; gmail probe contributed
authentik                 both blueprints successful; embedded outpost 28 of 28 providers,
                              none unattached
SSO gating                drive / my-docs / chat / inbox / incoming-documents / console  -> 302
ollama (enabled: false)   0 authentik applications
glitchtip                 13 projects configured
ci-verify                 24/25 (the 1 is the documented Windows-only curl cookie-jar issue)
n8n                       119/119 workflows imported, 113 published == 113 declared,
                              25/25 credentials restored from the blueprint
INDOX E2E                 7/7 suites GREEN — sync_kernel 6/6 · sync_sources 10/10 ·
                              sync_full 6/6 · doc_base 3/3 · bs 4/4 · gdoc 5/5 · pipeline 3/3
static gates              G0 · G1 · G5 · G6 · G7 · G8 all PASS; G9 debt 5
```

The `ollama` line is the one that proves the whole chain: it is present in the catalog, has a
full `routing[].sso` block, and produces **nothing** — because `platform.state.yaml` says
`enabled: false`. The old hand-written blueprint published an SSO application for it regardless.

### What only a virgin database could catch

The compiled outpost sets `authentik_host: !Context authentik_external_host`, and `!Context`
resolves against the blueprint's **own** `context:` block — which lived in the sibling
`deployment-apps.yaml`. On the warm dev machine everything looked fine, because the outpost
already held its providers from before the migration. On a fresh database authentik rejected the
whole blueprint (`should be "str" instead of value "None"`), created none of the 10 generated
providers, and left the outpost holding **0 of 18** — every SSO host would have been unreachable.

That is the third bug in this refactor whose entire signature was *"works on the machine that has
run before"*, after `perf-profile-apply` reading a moved path and the n8n `localhost`→`::1` probe.
A clean rebuild is not a formality.
