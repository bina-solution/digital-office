# An "npm for dgo": package format, registry, resolution, supply chain, federation

Research note, 2026-10-14. Scope: `dgo install <app>` on a clean machine, a console store of layer-1 blueprints, later `dgo-net`. Constraints honoured: solo vendor, Go stdlib, Ed25519 already in `packaging/relsign`, images on GHCR.

## 0. Two facts measured today (curl against ghcr.io, 2026-10-14)

1. **The project's GHCR packages are private.** The anonymous token endpoint (`/token?scope=repository:solomonboltin/digital-office/<app>:pull`) returned no token for `any-concurrency`, `console`, `bina-ds`; a public image (`sigstore/cosign/cosign`) returned one. GitHub: "When you first publish a package, the default visibility is private" and "You can also access public container images anonymously" ([docs][ghcr]). First blocker for any clean-machine install.
2. **GHCR does not serve the OCI 1.1 referrers API.** `GET /v2/sigstore/cosign/cosign/referrers/<digest>` returned `404 MANIFEST_UNKNOWN`; the spec requires 200 even when empty, so clients fall back to `sha256-<digest>.sig` tags ([OCI, 2024-03-13][oci11]) — visible in that repo's `tags/list`. Signatures on GHCR live as tags.

## 1. Format and registry — comparison

| Option | Discovery | Versions / deps | Mirrors, offline, air-gap | Fit for Ed25519 + Go stdlib | Verdict |
|---|---|---|---|---|---|
| **OCI artifacts on GHCR (ORAS)** — `oras push --artifact-type`, manifest `artifactType`, anonymous pull of public packages ([ORAS][oras]; [ghcr]) | none built in (tags only) | tags + digests; no range semantics | `oras cp --to-oci-layout`, `--from-oci-layout`, `-r` copies referrers, tar layouts, `oras backup/restore` ([oras-cp]); zot pull-through/periodic sync, `syncLegacyCosignTags` ([zot]) | pull = 3 JSON GETs over `net/http` (proved above); oras-go/v2 needs only image-spec + x/sync ([pkg.go.dev][orasgo]) | **blob store: yes** |
| **Static signed index** — Go-proxy layout "even a site serving from a fixed file system … can be a module proxy"; `@v/list`, `.info`, `.zip` ([go.dev/ref/mod][gomod]); Homebrew moved installs to JSON from formulae.brew.sh on 2023-02-16 ([brew4]); Cloudron ships a `CloudronVersions.json` per package ([cloudron]) | one file = whole catalog, trivial to browse/cache | explicit, resolver-defined | any HTTP/CDN/git/USB; sumdb-style log later ([gomod]) | one Ed25519 signature over the index (relsign today) | **catalog: yes** |
| **Helm chart in OCI** — `Chart.yaml` deps with `condition`/`tags`/`alias`, lock file "to rebuild the dependencies to an exact version" ([helm-charts]; [helm-dep]) | Artifact Hub annotations ([ah]) | semver ranges + Chart.lock | digests "more secure than a tag" ([helm-reg]) | Helm-shaped | copy the schema, not the tool |
| **Compose as OCI** — `docker compose publish`, `-f oci://`, `--resolve-image-digests` ([compose], 2025-03-17) | none | none | none | n/a | **no**: "can't publish … service(s) containing bind mounts" — dgo apps bind-mount `./apps/...` |
| **apt repo** — apt 3.0 (Sequoia, deb822 `Signed-By`), Debian 13, 2025-08-09 ([lwn]) | apt search | strong solver | mature | Debian-only | no (Windows/macOS hosts) |
| **winget-pkgs / tap-style git repo** — manifest-per-version PR repo, `ManifestVersion 1.12.0` ([winget], 2026-09-14) | git + PR review | `PackageDependencies` "from the same source" ([winget-inst]) | git clone | signatures by sha256 only | good *authoring* flow for the index |
| **Custom HTTP registry** | whatever you build | whatever you build | you run it | stdlib | no: a second service to operate alone |

**Recommendation (2026):** a **hybrid** — the catalog is a static, Ed25519-signed JSON index built from a git repo (`dgo-index`, winget-style one directory per app/version), served from GitHub (Release asset + raw) *and* pushed as an OCI artifact; each package is an OCI artifact on GHCR (`ghcr.io/solomonboltin/dgo/<app>:<ver>` = tar of the app directory + `package.yaml`), images referenced **by digest**. `dgo install` needs `net/http`, `encoding/json`, `crypto/ed25519`, `archive/tar`. Air-gap: `dgo bundle <blueprint>` writes an ORAS-compatible OCI layout dir/tar; an office may run zot as a pull-through mirror. The index names blob URLs, so a mirror or a plain directory is a valid registry.

## 2. `package.yaml` — fields and their precedents

| Field | Copy from |
|---|---|
| `id`, `version` (semver), `layer`, `kind` | existing `app.json`; Umbrel `manifestVersion/id/version` ([umbrel]) |
| `title{he,en}`, `summary{he,en}`, `description` | AppStream `name`/`summary` with `xml:lang`, Flathub guidelines ([flathub]) |
| `category`, `screenshots[{image,caption}]`, `icon`, `developer`, `website`, `support` | Flathub ("must have one or more screenshots"); Umbrel `gallery`, `tagline`, `submitter`; Artifact Hub `screenshots`, `category` ([ah]) |
| `targets[{os,arch}]`, `minPlatform` | Homebrew bottle "hash … for the given OS/architecture" ([brew-bottles]); HA `arch`, `homeassistant` ([ha]) |
| `images[{service,ref,digest}]` | Compose `--resolve-image-digests`; HA `image` whose tag must equal `version` ([ha]) |
| `provides[]` / `requires[{capability,strength,ops}]` | HA `services` `provide` / `want` / `need` ([ha]) — identical to today's `use[].strength` |
| `data.volumes`, `data.sql`, `on_uninstall` | HA `map`, `backup: hot/cold`; YunoHost `[resources]` provisioned before install ([ynh]) |
| `connections[{id,required,note}]` (install questions) | YunoHost `[install]` questions, Cloudron `addons` ([cloudron]) |
| `hooks{install,upgrade,remove}`, `compose`, `blueprints` | winget `InstallerSwitches.Silent/Upgrade/Repair` ([winget-inst]); existing hooks |
| `stage` (stable/experimental/deprecated), `releaseNotes`/`changes[{kind,description}]` | HA `stage` ([ha]); Artifact Hub `changes` kinds ([ah]) |
| `signatures[{key,sig}]` over the canonical digest line, `provenance` (URL) | relsign's "version\npayload_url\nsha256" message |

## 3. Dependency resolution for app sets

- **Capabilities, not packages.** Keep `requires: [{capability: workflow}]`; a provider is chosen from (a) installed, (b) the blueprint's pin, (c) the index default (`workflow → n8n`, `ocr → apitools`). HA's `need/want/provide` is the exact precedent ([ha]); Helm's `condition`/`tags` toggle optional sub-components ([helm-charts]).
- **Ranges + lockfile.** Caret ranges as in Cargo ("1.0" = `>=1.0.0,<2.0.0`; the lock holds "exact information") ([cargo]); npm's `lockfileVersion 3` records versions + integrity hashes, `npm ci` fails on drift ([npm]); Nix pins `narHash` ([nix]). `dgo.lock` = exact versions + artifact and image digests; `dgo install --locked` fails on drift.
- **Algorithm.** Go's MVS: "the highest required versions comprise the build list: they are the minimum versions that satisfy all requirements" ([gomod]) — deterministic, no SAT solver, a page of stdlib Go.
- **Blueprints** (`ai`, `automation`, `project`, `indox`, `mail`, `drive`) are packages with only `requires` plus a lock — Helm umbrella charts — so the store "recommends" by listing six entries.

## 4. Supply chain — what is proportionate

- **Root of trust stays Ed25519 + offline key.** Keyed signing suits consumers who "verify the signature offline, years after issuance"; keyless suits frequent online CI signing ([evertrust]). Cosign v3 (2025-10-08) defaulted the new bundle, `--trusted-root`, `--use-signing-config` ([cosign3]); Rekor v2 went GA 2025-10-10 ([rekor2]), yet sigstore.dev "will continue using Rekor v1 as the default log for the foreseeable future" (2026-06-28) ([rekor-evo]); verifying bundles in Go drags in protobuf, CT, rekor-tiles ([sigstore-go]). Sigstore stays **CI-side only**.
- **Borrow TUF cheaply**: index carries `version` + `expires` (freeze/rollback), root key offline, a CI "snapshot" key; thresholds later (TUF 1.0.37, 2026-10-08 [tuf]). A sumdb-style append-only log of index hashes can come with dgo-net ([gomod]).
- **Provenance for free**: `actions/attest-build-provenance` (public repo → public Sigstore) gives SLSA v1.0 Build L2, L3 via a reusable workflow, `gh attestation verify --signer-workflow` ([gh-attest]; [gh-l3]); SLSA v1.1 approved 2025-04-21, v1.2 2025-11-24 ([slsa]). Record the attestation URL in `package.yaml`; do not verify it in `dgo`.
- **Scanning**: `aquasecurity/trivy-action@v0.36.0` with `severity: CRITICAL,HIGH`, `ignore-unfixed`, SARIF to code scanning, SBOM `format: github` to Dependency Graph ([trivy]). Syft/Grype split only if a customer asks for SPDX/CycloneDX.

## 5. Federation precedents for `dgo-net`

| Precedent | Model | Fit |
|---|---|---|
| **MTA-STS (RFC 8461, 2018-09)** — DNS TXT `_mta-sts.<domain>` `v=STSv1; id=…`, policy at `https://mta-sts.<domain>/.well-known/mta-sts.txt`, `max_age`, no DNSSEC ([rfc8461]) | DNS discovery + HTTPS signed body | **phase 1**: `_dgo.<office>` TXT → `/.well-known/dgo/catalog.json` signed with the office key |
| **Nostr NIP-01/89** — one signed `event` (pubkey, kind, tags, sig), relays "expose a websocket endpoint", addressable kinds 30000–39999 replace by `d` tag; NIP-89 handler events 31990/31989 ([nip01]; [nip89]) | key identity, dumb relays | **phase 2**: `dgo-net` = a relay of signed catalog events; an office announces packages/handlers |
| **ActivityPub (W3C Rec 2018-01-23)** — actors, inbox/outbox ([ap]); **Matrix v1.19** — room DAG, state resolution ([matrix]) | always-on server mesh | heavier than needed |
| **AT Protocol** — PDS/relay/app-view, DIDs, lexicons; open federation since 2025-01 ([atproto]) | richest | too much for one vendor |

## Two biggest risks

1. **GHCR coupling**: packages private by default (all are today), no referrers API, docs say classic PATs only ([ghcr]); any GitHub policy change strands installs. Mitigation: index names blob URLs, `dgo mirror`/bundle from day one.
2. **Key custody and resolver scope**: one Ed25519 key is one point of failure (TUF: rotate by threshold, keep root offline [tuf]); and a resolver that grows past caret + MVS + lockfile becomes a solo vendor's permanent tax.

## Sources

[ghcr]: https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry (accessed 2026-10-14)
[oci11]: https://opencontainers.org/posts/blog/2024-03-13-image-and-distribution-1-1/ (2024-03-13)
[oras]: https://oras.land/docs/compatible_oci_registries (accessed 2026-10-14)
[oras-cp]: https://oras.land/docs/commands/oras_cp and https://github.com/oras-project/oras/releases (accessed 2026-10-14)
[orasgo]: https://pkg.go.dev/oras.land/oras-go/v2@v2.6.3?tab=imports (accessed 2026-10-14)
[zot]: https://zotregistry.dev/v2.1.22/articles/mirroring/ (v2.1.22, accessed 2026-10-14)
[gomod]: https://go.dev/ref/mod (accessed 2026-10-14)
[brew4]: https://brew.sh/2023/02/16/homebrew-4.0.0/ (2023-02-16)
[brew-bottles]: https://docs.brew.sh/Bottles (accessed 2026-10-14)
[cloudron]: https://docs.cloudron.io/packaging/manifest and /packaging/publishing (accessed 2026-10-14)
[helm-charts]: https://helm.sh/docs/topics/charts/ (accessed 2026-10-14)
[helm-dep]: https://helm.sh/docs/helm/helm_dependency_update/ (accessed 2026-10-14)
[helm-reg]: https://helm.sh/docs/topics/registries/ (accessed 2026-10-14)
[ah]: https://artifacthub.io/docs/topics/annotations/helm/ (accessed 2026-10-14)
[compose]: https://docs.docker.com/compose/how-tos/oci-artifact/ ; https://github.com/docker/docs/pull/22240 (merged 2025-03-17)
[lwn]: https://lwn.net/SubscriberLink/1017315/9dbc0f74fd61964b/ (2025-04); Debian 13 2025-08-09 via https://computingforgeeks.com/things-to-do-after-installing-debian-13-trixie/
[winget]: https://learn.microsoft.com/en-us/windows/package-manager/package/manifest (2026-09-14)
[winget-inst]: https://github.com/microsoft/winget-pkgs/blob/master/doc/manifest/schema/1.12.0/installer.md (accessed 2026-10-14)
[umbrel]: https://raw.githubusercontent.com/getumbrel/umbrel-apps/master/nextcloud/umbrel-app.yml (accessed 2026-10-14)
[flathub]: https://docs.flathub.org/docs/for-app-authors/metainfo-guidelines (accessed 2026-10-14)
[ha]: https://developers.home-assistant.io/docs/add-ons/configuration/ (accessed 2026-10-14)
[ynh]: https://yunohost.org/en/packaging_v2 and /packaging_manifest (accessed 2026-10-14)
[cargo]: https://doc.rust-lang.org/nightly/cargo/reference/resolver.html (accessed 2026-10-14)
[npm]: https://docs.npmjs.com/cli/v11/configuring-npm/package-lock-json (accessed 2026-10-14)
[nix]: https://nixos.wiki/wiki/Flakes (accessed 2026-10-14)
[evertrust]: https://evertrust.io/guide/sigstore (accessed 2026-10-14)
[cosign3]: https://blog.sigstore.dev/cosign-3-0-available/ (2025-10-08)
[rekor2]: https://blog.sigstore.dev/rekor-v2-ga/ (2025-10-10)
[rekor-evo]: https://blog.sigstore.dev/rekor-evolution/ (2026-06-28)
[sigstore-go]: https://pkg.go.dev/github.com/sigstore/sigstore-go@v1.3.0/pkg/verify?tab=imports (accessed 2026-10-14)
[tuf]: https://theupdateframework.github.io/specification/latest/ (1.0.37, 2026-10-08)
[gh-attest]: https://github.blog/security/supply-chain-security/configure-github-artifact-attestations-for-secure-cloud-native-delivery/ (2024-07-30, updated 2025-09-23)
[gh-l3]: https://docs.github.com/en/actions/security-for-github-actions/using-artifact-attestations/using-artifact-attestations-and-reusable-workflows-to-achieve-slsa-v1-build-level-3 (accessed 2026-10-14)
[slsa]: https://slsa.dev/blog/2025/04/slsa-v1.1 (2025-04-21); https://slsa.dev/blog/2025/11/announce-slsa-v1.2 (2025-11-24)
[trivy]: https://github.com/aquasecurity/trivy-action (accessed 2026-10-14)
[rfc8461]: https://www.rfc-editor.org/rfc/rfc8461 (2018-09)
[nip01]: https://github.com/nostr-protocol/nips/blob/master/01.md (accessed 2026-10-14)
[nip89]: https://nips.4rs.nl/nips/89 (accessed 2026-10-14)
[ap]: https://www.w3.org/TR/activitypub/ (2018-01-23)
[matrix]: https://spec.matrix.org/latest/ (v1.19, accessed 2026-10-14)
[atproto]: https://atproto.com/guides/overview ; https://atproto.com/blog/looking-back-2024 (2025-01)
