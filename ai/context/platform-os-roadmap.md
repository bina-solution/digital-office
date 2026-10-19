# Platform OS — refactor roadmap

Where the app engine stands and what is left to make it a product someone else can install.
Derived from a survey of Android PackageManager, Flatpak/portals, Snap, Nix, Kubernetes/OLM,
Home Assistant, OSGi, Debian/apt, macOS entitlements, YunoHost and Fuchsia — each item below names
the system the mechanism comes from.

## Done

| # | Mechanism | Prior art |
|---|---|---|
| ✅ | **Explicit provider selection** — binding → `default_provider` → sole candidate; ambiguity fails the plan and names every candidate | Android preferred-activity, Debian update-alternatives, Snap default-provider |
| ✅ | **`conflicts` enforced** — fails naming *both* apps, never silently drops one | Gateway API ("MUST NOT pick a winner"), Debian Breaks vs Conflicts |
| ✅ | **Claim arbitration** — two apps cannot claim one host or console tile | Debian Conflicts, Android package-name uniqueness |
| ✅ | **Generations + rollback** — every render archives the previous `.generated/` | Nix profile generations |
| ✅ | **Dispositions with provenance** — enabled / disabled / **archived**, `by: user` never silently undone | Android app states |
| ✅ | **`archived`** — drop images + containers, KEEP volumes and the tile | Android 15 app archiving |
| ✅ | **Per-app automations** — `blueprints.n8n` imported on enable, removed on disable | OSGi bundle lifecycle |
| ✅ | **App store UI** — mine / store / core, in-UI confirms, measured progress, zero browser dialogs | Google Play |
| ✅ | **19 invariant gates in CI** — G0–G15 structural, plus **G16** app conditions, **G17** the compiler's resolver, **G18** healthcheck binaries, **G19** sub-workflow inputs. The last four all exist because something failed SILENTLY: a probe reporting on itself, a resolver guessing a provider, a sub-workflow call passing null. See [fresh-machine-findings.md](fresh-machine-findings.md) | Fuchsia Scrutiny |
| ✅ | **Signed catalog + install-by-ref** — a signed index file with per-entry hashes; `bbox app install <id\|url\|file>` fetches, verifies, validates against the live catalog, refuses on conflict, then installs through the existing lifecycle. Ed25519 (pure stdlib), public keys pinned in `platform/trust/keyring.json` | F-Droid index-v2 (`entry.jar` → index hash → per-APK hash) |
| ✅ | **Pre-install disclosure** — computed from the manifest AND the compose file: credentials first, then root-equivalent powers (docker socket, host paths, published ports, unauthenticated routes), apps pulled in as providers, routes, storage, cost | Home Assistant rating, F-Droid Anti-Features, Flathub |
| ✅ | **Status conditions + failure taxonomy** — `Resolved/Installed/Started/Ready`, each with `status True\|False\|Unknown`, `reason`, `message`, `observedGeneration`, `lastTransitionTime`; `progressDeadlineSeconds` turns a stale `NotReady` into `ProgressDeadlineExceeded`; `AuthFailed` is read from the credential plane, not guessed from container health, and outranks every other Ready reason. 21 unit tests, gate G16 | Kubernetes conditions + Home Assistant's three-way failure split |

## Next — in dependency order

### 1. Fresh-machine install proof — **done**
`scripts/fresh-machine-check.sh` clones into a scratch dir with no `.env`, no `.generated/` and
no volumes, and proves compile + render + compose + gates from nothing. It runs in the
`platform-invariants` lane, so "works on this laptop" is no longer load-bearing.

### 2. Credential broker — **mechanism built, migration begun**
`connections` is now a broker: `POST /api/broker/lease` identifies the caller from the docker socket
(source address → container → `com.docker.compose.service`), cross-checked against a container id
the caller proves it owns; grants only what that app's own `app.json` `connections[]` declares;
refuses everything else by name; mints single-use, seconds-lived capability tokens; and appends every
decision to an fsync'd grant log readable at `GET /api/broker/audit`. `/api/export-all` — the last
step of the documented kill chain — is now loopback-only. `platform-base/connections/test_broker.py`
holds the refusals as a gate (34 assertions, no docker needed).

An app opts out of standing plaintext with a `broker` block in its own manifest; the compiler emits
`.generated/connections.override.yml` — `drive` is the first app cut over, running with
`SUPABASE_SERVICE_KEY` and `SUPABASE_DB_PASSWORD` blank in its environment.
What remains is the long part: the other five apps still hold standing plaintext
env, `CONN_BROKER_MODE` is still `warn` (unidentified callers are served and logged, identified ones
are fully policed), and the per-account `/api/instances/*` routes are logged but not yet policy-gated.
*Flatpak portals + macOS Powerbox + Vault/SPIFFE — three independent designs, same shape: broker out
of process, selection is consent, result narrow and revocable.*

### 3. Status conditions + failure taxonomy — **done, see Done table.** What is left
`AuthFailed` is sourced from `connections`' required/`needs_action` rows, which covers every
credential the platform knows about — but an app that authenticates outside the credential plane
(a token it stores itself) is still invisible to it. The honest fix is a per-app auth probe the
manifest declares; nothing needs one yet, so it is not built.

### 4. `RESOLVED` as an all-or-nothing gate, and the plan as an artifact
Resolution succeeds or fails as a whole, reporting *every* diagnostic, before a single container
starts. `bbox plan` writes `.generated/plans/<id>.yaml`; `bbox apply <id>` executes exactly that and
fails if the inputs changed underneath. *OSGi RESOLVED + OLM InstallPlan.*

### 5. Signed catalog + install-by-ref — **done, see Done table.** What is left
`bbox catalog build|verify|show|trust` + `bbox app install <ref>` ship the index, the Ed25519
signature chain, the disclosure and the store's install-from-URL/file affordance. Deliberately NOT
done, and each is a real F-Droid feature: **index diffs** (a full re-download every time is fine at
this size), **mirrors** (`repo.mirrors` is in the format, unread), **per-entry signing keys**,
**revocation** (distrust = delete the keyring entry; nothing propagates), and **catalog-driven
upgrade** — `manifest_sha256` and `version` are in every entry, so "this app has an update" is one
comparison away, but no verb performs it.

### 6. Capability versioning
`capabilities[].version`; consumers `^1.3`, implementers `~1.3`. Require minimums, avoid maximums.
Catches the break where a provider changes a response shape and the consumer fails at runtime
instead of at compile. *OSGi provider/consumer asymmetry + OLM.*

### 7. Snapshot-on-uninstall
Always snapshot, retain 31 days, `--purge` to skip — replacing `on_uninstall: prompt`. A modal at
2am gets the wrong answer; a 31-day window never does. *Snap.*

### 8. Per-app networks from the `use` graph
An app can only reach capabilities it declared. Today every container on `traefik-network` can
reach every other. *Android `<queries>`.*

### 9. Pre-install disclosure — **done, see Done table.** What is left
The **mechanical safety score** is not implemented, on purpose: a single number invites the ritual
APT deleted its `Yes, do as I say!` prompt to escape (caution #2 above). The disclosure names each
power instead. Reconsider only with evidence that the list is being scrolled past.

### 10. Transient start
`bbox apps start X --transient` — run now without changing the persistent disposition. The state
file is autostart; the running container is current state; today they are conflated. *OSGi
`START_TRANSIENT`.*

## Known debt

- **G9 is clear** — it now PASSES `--strict`, so no base app names a layer-3 app anywhere. It had
  been failing (exit 1), which meant the `platform-invariants` CI lane was red on every push. The
  three inversions were authentik's committed blueprint (moved to each app's `routing[].sso`),
  supabase's kong.yml (three dead routes to a disabled studio, removed) and portainer's secret,
  which needed the mechanism the entry below used to say was missing: `contributes.
  connection_providers` lets an app declare whole credential-catalog entries, compiled into the
  registry `connections` mounts.
- **`_ADMIN_TOOLS` is gone.** It hardcoded five apps' display text in a codebase owning none of
  them, and two of the five were layer-3. The route holding it (`console /api/apps`) had no callers
  left — the apps screen is app-management, which already derives every tile from the manifests —
  so it was deleted rather than reimplemented.
- **The compiler's resolver is now tested** (`platform/manager/test_resolve.py`, 33 cases, gate
  G17) alongside the catalog (`catalog_selftest.py`, 22 assertions). Both suites are mostly
  refusals, and the resolver one was mutation-checked — reinstating the old `ok[:1]` provider
  selection makes it fail. What is still untested is the RENDER half: `render_routing`,
  `render_broker` and the generation/rollback verbs are exercised only by a full bring-up.
- **App-author documentation is written**: [build-your-first-app.md](build-your-first-app.md) walks
  the manifest field by field (identity, capabilities, use-strengths, routing, connections, data,
  health, blueprints), the verbs, the gates to run before calling it done, and the two rules —
  declare rather than register, and uninstall must be `rm -rf` on the app's directory.
  [app-catalog.md](app-catalog.md) covers publishing and installing by reference.
- **Traefik v3.3 pins docker API 1.24**, so the platform cannot run on Docker 29 — 29's hard floor
  is 1.40 and `DOCKER_MIN_API_VERSION` is capped there, so the historical workaround silently does
  nothing and every route 404s while traefik reports healthy. `bbox baseline` P0 fails fast on it
  now. The real fix is a traefik release whose docker provider negotiates the version; that needs
  its own validation pass across every route and the authentik forward-auth chain.
- **Hebrew-only UI**, single-machine assumptions (`DEPLOYMENT_NAME`, host ports).

## Automation coverage

Measured against a green baseline (6,689 executions), after retiring measured-dead workflows:

| App | Workflows | Nodes run | Coverage |
|---|---|---|---|
| mail | 3 | 22 / 23 | 95.7% |
| drive | 1 | 11 / 12 | 91.7% |
| n8n (stdlib) | 7 | 71 / 105 | 67.6% |
| indox | 68 | 1358 / 2060 | 65.9% |
| **total** | **80** | **1462 / 2206** | **66.3%** |

Up from 52% before triage. The remaining gap is **untriggered entry points, not dead code**: of the
never-executed workflows, none lacks a trigger and most are API routers or sub-workflows the
baseline never calls. Closing it means driving each app's API router — which is what `bbox test
<app>` is for.

⚠ One coverage number is a lie by omission: the gmail lanes inject mail that already carries the
to_sync label, so **labelling is never exercised**. See `mail-organizer-refactor.md`.

## Three cautions from the survey

- **Hard rejection is consistently regretted.** Fedora bans `Conflicts:`, Debian prefers `Breaks`,
  Homebrew calls `conflicts_with` a last resort. Reach for isolation, declared overrides or
  capability indirection first.
- **A confirmation ritual that becomes muscle memory is worse than none.** APT deleted its
  `Yes, do as I say!` prompt because people typed it without reading. Prefer a hard refusal plus a
  documented flag.
- **State the polarity of any priority number in its field name.** Debian higher-wins, Nix
  lower-wins, DNF lower-wins — there is no convention, and you will get it wrong twice.
