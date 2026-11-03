# Omni `dgo` binary + the registry at apps.net.digital-office.co.il — research notes

Date: 2026-10-14. Desk research, read-only. Scope: (1) one-binary design in Go, (2) engine provisioning per OS, (3) the public app registry, (4) "dgo-net" services. Dates are the source's publication/last-update date; "secondary" marks a claim not confirmed against a primary source before the search budget ran out (OCI 1.1 referrers wording, winget REST routes, GHCR limits, the openSUSE no-admin report).

## 0. Executive summary

1. Shape: **one file, several processes** — `dgo` is CLI *and* supervisor, re-executing itself as `dgo be-child console|control|vault|engine` (Tailscale's `be-child` + k0s's supervisor of "naked" processes); the vault gets its own process, user and crash domain; one artifact to sign, mirror, update.
2. Role by argv[0]/env/subcommand (Tailscale `ts_include_cli`); modules compiled in Caddy-style; **no runtime plugin loading in layer 0**; extensions, if ever, via WASM (wazero/Extism), not hashicorp/go-plugin.
3. Assets pre-compressed before `go:embed` (toolchain compression declined Aug 2023); JSON config at start or over a local admin socket; koanf over Viper; kardianos/service; slog + otelslog (OTel Go logs still beta); telemetry Go-style, local counters, upload opt-in.
4. Self-update = stage beside target, verify signature, rename; on Windows rename the running `.exe` to `.old` first and sweep it on next start.
5. Layer 0 (CLI, daemon, control plane, console, vault) = **native processes, no container engine**; the engine is a provisioned dependency of layer-3 apps only; its absence means "apps unavailable", never "office down" (k0s; Home Assistant dropped Supervised in 2025).
6. Engine per OS: Windows = WSL2 + project Docker CE 28.x (admin once; WSL is now a standalone open-source package, `wsl --update`); macOS = Lima **vz + vzNAT**, no sudo, Docker CE pinned in the guest, edge on :8080; Linux VPS = Docker CE 28.x rootful; no-root Linux = rootless Docker/Podman with known gaps; sandbox = `dockerd` started by the binary. Docker 29 is a hard no while Traefik is 3.3.
7. Registry: a **static, signed, sparse index** (Cargo sparse × npm abbreviated packument × Go proxy "a static file server is a proxy") on R2 + CDN, zero compute on the install path; `config.json` root with a `dl` template; one JSON per package; `yanked` and channel tags the only mutable fields; `all.json.zst` (+ per-os/arch shards) for search and offline bundles.
8. Integrity: TUF roles (root offline 2-of-3; timestamp/snapshot online) against freeze, rollback, mix-and-match; publishers hold registered Ed25519/minisign keys; Sigstore keyless attestations from GitHub OIDC add provenance; images stay in GHCR, cosign-signed; sumdb-style transparency log later.
9. DNS: `apps.` index, `dl.` blobs, `img.` OCI, `id.` trust anchor, `relay[N].` DERP, `log.` transparency — Tailscale's split.
10. dgo-net: pairing by short-lived code/QR binding both offices' keys plus a secret (Tailscale invites × Matrix QR), new peers quarantined; hosted DERP-style blind relay, office-run relays allowed; federation starts pairwise with signed Entity-Statement-like JWTs (OpenID Federation 1.0 Final only 2026-02-17); telemetry opt-in, counters only.
11. Trust model: the vendor can never decrypt traffic, log into an office, push code silently, de-anonymise telemetry, or strand an office.
12. Risks: WSL on Windows (admin, `0x8007274c` hangs with no upstream diagnosis, mirrored mode gated per build); key custody and trust bootstrap (root rotation, metadata expiry, provenance ≠ review); engine/version coupling and fate-sharing (Docker 29 vs Traefik 3.3, rootless gaps, vault in the console's crash domain if single-process).

## 1. One binary, many roles

### 1.1 Precedents

| Project | How the roles split | Copy |
|---|---|---|
| Caddy | "a single, self-contained, static binary with zero external dependencies"; "command, core library, and modules"; modules register by being imported, fixed at build time; runtime loading declined, WASM "maybe" in a future major; config "is a JSON document" loaded at start or via an admin socket [1][2] | build-time module registry; JSON config + admin socket |
| Tailscale | `tailscale` CLI vs privileged `tailscaled` (Windows service "Tailscale") [4]; `ts_include_cli` links both into one file; `shouldRunCLI()` = `filepath.Base(os.Args[0])=="tailscale"` or `TS_BE_CLI`, done "for space savings reasons"; helpers run as `be-child` subcommands of the same binary [3][5] | argv[0]/env dispatch; `be-child` |
| k0s | "single, self-extracting binary that embeds Kubernetes binaries"; "acts as the process supervisor for all other control plane components", each a "naked" process; "no container engine or kubelet running on controllers by default"; workers get containerd + runc [6] | supervisor of children; no engine on the control node |
| k3s | control plane + kubelet + kube-proxy in one process; containerd unpacked and managed as a separate binary [7] | one process is possible but couples everything |
| Gitea | assets via generated bindata + `go:embed`, gzip best compression, merged 2025-06-12; "reduces more than 1MB"; statigz rejected as "about 20MB+" [8] | compress before embedding |
| Home Assistant | Core + Supervised deprecated 2025-05-22; Supervised was 3.3% of installs and "extremely complex"; only OS and Container remain [25] | do not ship a "supervise someone else's Docker" mode |

### 1.2 Building blocks

| Concern | Recommendation | Evidence |
|---|---|---|
| Assets | pre-compress (.br/.gz/zstd) at build and serve by `Accept-Encoding`; `embed` stores files uncompressed and the toolchain flag (Go issue 61322) was declined, confirmed Aug 2023 | [8][9][10] |
| Plugins | none at runtime in the core (Caddy). If ever needed: WASM — wazero ("zero dependency", no CGO, 1.0 March 2023); knqyf263/go-plugin (protobuf over wazero, sandboxed, Go ≥1.24); Extism (host functions) — over hashicorp/go-plugin (subprocess RPC/gRPC, v1.8.0 2026-04-29, per-arch binaries, no sandbox) | [11][12] |
| Config | koanf (fewer deps, modular; Authelia migrated off Viper) or a plain struct + env; Viper is heavier and lower-cases keys | [13] |
| Self-update | stage in the target's directory, verify signature, `rename`; Windows returns ERROR_ACCESS_DENIED on a running exe, so rename it to `.old`, move the new file in, delete `.old` next run; minio/selfupdate offers bsdiff + minisign but last released v0.6.0 on 2022-10-19 | [14] |
| Service install | kardianos/service v1.3.0 (2026-07-06, newer exists): Windows SCM callbacks, systemd/Upstart/SysV/OpenRC, launchd; Start/Stop must return within seconds | [15] |
| Logging/telemetry | slog + `otelslog` bridge; OTel Go logs API/SDK still described as beta in 2026 docs — pin versions; telemetry as Go 1.23 does it (Aug 2024): local counters by default, `telemetry on` to upload, weekly aggregated public publish | [16][17] |

### 1.3 What one binary buys and costs

Buys: one artifact to sign, verify, mirror and self-update; CLI and daemon cannot skew (Tailscale's reason: space) [3]; copy-and-run installs [6]. Costs: fate-sharing and privilege mixing — the daemon is the privileged half [4]; a bigger file [8]; an upgrade restarts everything. Keep the buys with **one file, several processes**: `dgo` supervises `dgo be-child …` children (k0s + Tailscale), the vault in its own process and user, modules compiled in, nothing loaded at runtime in layer 0.

## 2. Engine provisioning per OS

| OS | Recommended | Admin? | Known traps (dated) |
|---|---|---|---|
| Windows | WSL2 `Ubuntu` + project Docker CE 28.x inside (existing `bbox.cmd` hand-off); WSL as the standalone package, `wsl --update` | Microsoft's page (2025-06-09) still says "Open PowerShell in administrator mode" [18]; one tracker says `--no-distribution` stopped prompting in March 2025 (secondary) [22]; the Hyper-V firewall rule for mirrored-mode inbound needs admin [20] | WSL open-sourced 2025-05-19; 2.6.0 (2025-06-20) "First open source release"; `lxcore.sys`, `p9rdr.sys` stay closed [19]. Mirrored mode needs Win11 22H2+; some builds answer "does not have the required features" (26100.3194, 2025) [20]. `Wsl/Service/0x8007274c` = Windows socket timeout to `wslservice`: #11975 (2024-08-30) closed by a bot 2024-09-06 undiagnosed; community mitigations `wsl --shutdown`, cap memory/CPU in `.wslconfig`, `wsl --update`, reboot; it recurs [21]. Install-failure class #9521 open since 2023-01-23 [22] |
| macOS | Lima **vz** (default since Lima 1.0 on macOS ≥13.5) + **vzNAT**, which "does not need the socket_vmnet binary and the sudoers file"; Docker CE pinned in the guest (existing `~/.bbox/macos`) | none — only socket_vmnet "requires root" [23] | vz: no `legacyBIOS`, no cross-arch guest; :80 needs root, hence :8080 [23] |
| Linux VPS | Docker CE 28.x rootful under systemd | root once | Docker 29 makes Traefik 3.3 discover zero routers, silently (CLAUDE.md) |
| Linux, no root | rootless Docker or Podman | none | no overlay network (Docker), ports <1024 need `net.ipv4.ip_unprivileged_port_start`, cgroup v2 + systemd user session required, overlay2 needs kernel ≥5.11, Podman needs `/etc/subuid` [24] |
| Cloud sandbox | `dockerd` started by the binary (existing `need_docker`) | n/a | registries must be allowed (CLAUDE.md) |

**Should layer 0 avoid containers?** Yes. k0s controllers run no engine [6]; Tailscale and Syncthing are plain daemons [4][42]; Home Assistant dropped generic-host Docker for complexity [25]. The engine is a dependency of layer-3 apps only; `dgo engine doctor` is the one place that knows WSL/Lima/dockerd.

## 3. The registry at apps.net.digital-office.co.il

### 3.1 Protocol precedents

| Registry | Shape | Lesson |
|---|---|---|
| npm | one packument per package; `dist-tags` = channels; abbreviated doc via `Accept: application/vnd.npm.install-v1+json` keeps `name, modified, dist-tags, versions[dependencies, deprecated, dist.tarball, dist.integrity]`; `/-/v1/search` with `text,size,from` [28] | channels as mutable tags; a tiny install document |
| crates.io sparse | `config.json` root with `dl` template; one file per crate, one JSON line per version; "should not be modified after they are added except for the `yanked` field"; yank never deletes; sparse default since Rust 1.70 (2023-06-01) [29] | static files over plain HTTP; yank = flag |
| Go proxy + sumdb | fixed paths `@v/list`, `@v/<v>.info|.mod|.zip`, `@latest`; "even a site serving from a fixed file system (including a `file://` URL) can be a module proxy"; sumdb is a Merkle "Transparent Log… backed by Trillian"; x/mod v0.40.0 (2026-08-13) fixed two forgery bugs — verifiers are subtle [30] | static proxy; transparency log of every publish |
| Homebrew 4 | JSON API default since 2023-02-16 — "significantly faster… migrating from Git-cloned taps to JSON downloads"; `formula.json`, `formula/<name>.json`, `cask.json` [31] | whole-catalogue JSON for search + per-item JSON |
| winget REST | `Microsoft.Rest` source type; reference server v1.10.0 [32] | only if a server-side API is wanted; it is not |
| Flathub/OSTree | summary split per arch (6.6 MB → 2.7 MB) + ~20 KB deltas (2020-11-20) [33] | per-platform shards; deltas |
| Nix flake-registry | one JSON v2 file of `from→to` aliases [34] | an alias/mirror file is enough |
| OCI | Helm ≥3.8 charts as OCI; Flux verifies cosign (2022-11-24); distribution-spec v1.1.0 released 2024-02-15 (referrers API wording not re-verified, secondary) [35] | images stay in OCI; OCI is not the app index |

### 3.2 Recommended layout

DNS: `apps.net…` index + search JSON (CDN); `dl.net…` tarballs (R2); `img.net…` → GHCR or own OCI registry; `id.net…` federation trust anchor; `relay.net…`, `relayN.net…` DERP; `log.net…` transparency log (later) — Tailscale's `login/controlplane/log/console` + `derpN` split [44].

Index — static, signed, Cargo-sparse × npm-abbreviated:

| Path | Content | Mutable? |
|---|---|---|
| `/v1/config.json` | `dl` template, channel names, TUF root URL, mirror list | rarely |
| `/v1/p/<name>.json` | `{name, modified, channels:{stable,beta}, versions:[{version(semver), platforms:[{os,arch,url,sha256,size,sig}], image:{ref,digest}, min_dgo, deprecated, yanked}]}` | only `channels`, `yanked`, `deprecated` |
| `/v1/all.json.zst`, `/v1/all-<os>-<arch>.json.zst` | catalogue snapshot for `dgo search` and offline bundles | regenerated |
| `/v1/tuf/{root,timestamp,snapshot,targets}.json` | TUF metadata over every index file | per spec |
| `dl.net…/<name>/<ver>/<os>-<arch>.tar.zst` + `.minisig` | artifact + detached signature | never |

Publisher identity: vendor = TUF root (2-of-3 offline) + online targets/snapshot/timestamp keys — compromising "less than a given threshold of keys, cannot compromise clients" (spec 1.0.37, 2026-10-08) [39]; publishers = registered Ed25519 keys, minisign-compatible, trusted comments carrying name/version "to prevent downgrade attacks" [37]; plus Sigstore keyless attestations from GitHub OIDC, verified with pinned `--certificate-identity`/`--certificate-oidc-issuer` (mandatory in cosign 2) [36]; images cosign-signed in GHCR [35]. npm/PyPI took this path (provenance 2023-04-19; npm trusted publishing GA July 2025, secondary), yet 2026 incidents shipped malware *with valid attestations* via `pull_request_target` — provenance is not review [38].

Abuse/revocation: yank flag + `deprecated` text; TUF timestamp expiry exposes a frozen or replayed index; root rotation must keep old keys (a vendor lost one and stranded its agents); metadata expiry (52 weeks in one deployment) needs a calendar [39].

Cost at small scale: R2 egress free, $0.015/GB-month, free tier 10 GB + 1M Class A + 10M Class B (2026-10-01) [40]; GitHub Pages soft 100 GB/month and 1 GB per site [40]; Bunny $0.01/GB EU/NA [40]; Docker Hub anonymous 100 pulls/6 h per IPv4 (10/h was announced for 2025-04-01 and not enforced) [26]; GHCR publishes no pull limit (secondary, 2026) [27].

Mirrors/offline: a mirror is `rclone sync` of the tree plus its own `config.json`; `dgo bundle` = snapshot + blobs + TUF metadata; deltas for refresh (Flathub) [33].

## 4. dgo-net services

| Service | Precedent | Design |
|---|---|---|
| Invitation / pairing | Tailscale invite links: single-use or reusable up to 1,000 times, expire in 30 days, shared machines quarantined (inbound only) [41]; Syncthing device IDs are "essentially part of the public key", an introducer propagates trust [42]; Matrix QR encodes both master keys plus a random shared secret [43] | code/QR = {inviter office key, invite secret}, short-lived, single-use; both sides verify keys; the new office starts quarantined |
| Relays | DERP "blindly forwards already-encrypted traffic… impossible for a DERP server to decrypt"; custom `derper` allowed; derp1–28 as of Aug 2025, static control IPs since Jul 2025 [44]; Headscale's embedded DERP is off by default, needs STUN udp/3478; a lone relay is a single point of failure [45]; Syncthing relays join a community pool by default [42] | hosted `relay.net…` DERP-style, ciphertext only; offices add their own via a published `derpmap.json`; TURN only if WebRTC appears (Cloudflare $0.05/GB after 1 TB free, Twilio $0.40/GB — vendor figures, 2026) [46] |
| Identity federation | OpenID Federation 1.0 Final 2026-02-17: signed Entity Statements, Trust Chains to a Trust Anchor; "trust can be mediated by a third party" [47] | start pairwise: each office is its own OIDC issuer (authentik) exchanging signed Entity-Statement-like JWTs; `id.net…` becomes an optional Trust Anchor later |
| Telemetry | Go: local counters by default, upload opt-in, weekly aggregated publish [17] | `dgo telemetry on`; counters only, no identifiers |

Trust model — the vendor must never be able to: read office traffic (relay is blind) [44]; log into an office (keys live in the office vault; the vendor signs the catalogue, not sessions); push code silently (TUF + client-pinned roots + a transparency log make every publish auditable) [30][39]; identify an office from telemetry [17]; strand an office (static mirrors, offline bundles, `dl` template rewrite).

## 5. Biggest risks

1. **WSL on Windows** — admin on first install, `0x8007274c` service hangs with no upstream diagnosis, mirrored mode gated per build [18][20][21].
2. **Key custody and trust bootstrap** — root rotation, metadata expiry, dependence on public Sigstore/Rekor, provenance ≠ review [36][38][39].
3. **Engine/version coupling and fate-sharing** — Docker 29 vs Traefik 3.3 (project), rootless gaps [24]; a single process puts the vault in the console's crash domain — hence supervisor + `be-child`.

Secondary: OpenID Federation tooling is young [47]; OTel Go logs are beta [16].

## Sources

1. Caddy architecture — https://caddyserver.com/docs/architecture (current, fetched 2026-10-14)
2. Caddy issue #5183, runtime plugins — https://github.com/caddyserver/caddy/issues/5183
3. Tailscale `cmd/tailscaled/tailscaled.go`, `with_cli.go` (main, fetched 2026-10-14) — https://github.com/tailscale/tailscale/blob/main/cmd/tailscaled/tailscaled.go
4. Tailscale, tailscaled reference — https://tailscale.com/docs/reference/tailscaled
5. OpenWrt tailscale Makefile `GO_PKG_TAGS:=ts_include_cli` — https://git.freifunk-franken.de/mirror/openwrt-packages/src/commit/b3270866f8d55f2e3400edfca25b15de5e6ff8ee/net/tailscale/Makefile
6. k0s architecture (stable, fetched 2026-10-14) — https://docs.k0sproject.io/stable/architecture/
7. k3s explained — https://traefik.io/blog/k3s-explained ; k3s containerd (2026-03-20) — https://oneuptime.com/blog/post/2026-03-20-k3s-containerd/markdown
8. Gitea PR #34692 (merged 2025-06-12) — https://github.com/go-gitea/gitea/pull/34692
9. V. Bernat, Compressing embedded files in Go (2025) — https://vincent.bernat.ch/en/blog/2025-go-embed-compressed ; Go issue 61322 — https://go.dev/issue/61322
10. statigz — https://pkg.go.dev/github.com/vearutop/statigz
11. hashicorp/go-plugin v1.8.0 (2026-04-29) — https://pkg.go.dev/github.com/hashicorp/go-plugin
12. wazero (1.0 March 2023) — https://wazero.io/ ; knqyf263/go-plugin — https://github.com/knqyf263/go-plugin ; Extism go-sdk — https://pkg.go.dev/github.com/extism/go-sdk
13. Viper vs Koanf (Jan 2025) — https://itnext.io/golang-configuration-management-library-viper-vs-koanf-eea60a652a22 ; (2026-06-21) — https://www.pistack.xyz/posts/2026-06-21-application-configuration-libraries-viper-koanf-configrs-typesafe/
14. minio/selfupdate v0.6.0 (2022-10-19) — https://pkg.go.dev/github.com/minio/selfupdate ; Windows rename pattern — https://pkg.go.dev/github.com/thebtf/aimux/pkg/updater
15. kardianos/service v1.3.0 (2026-07-06) — https://pkg.go.dev/github.com/kardianos/service
16. OTel Go logs status — https://openobserve.ai/opentelemetry/go.md ; https://coralogix.com/docs/opentelemetry/instrumentation-options/golang-opentelemetry-instrumentation.md ; otelslog — https://uptrace.dev/guides/opentelemetry-slog
17. Go telemetry — https://go.dev/doc/telemetry ; blog 2024-09-03 — https://go.googlesource.com/website/+/refs/heads/master/_content/blog/gotelemetry.md ; devclass 2024-08-14 — https://devclass.com/2024/08/14/go-1-23-released-with-telemetry-uploaded-to-google-but-opt-in-after-developer-feedback
18. Install WSL (ms.date 2025-06-09) — https://learn.microsoft.com/en-us/windows/wsl/install
19. WSL is now open source (2025-05-19) — https://blogs.windows.com/windowsdeveloper/2025/05/19/the-windows-subsystem-for-linux-is-now-open-source/ ; WSL 2.6.0 (2025-06-20) — https://github.com/microsoft/WSL/releases/tag/2.6.0
20. WSL networking (ms.date 2024-07-16) — https://learn.microsoft.com/en-us/windows/wsl/networking ; mirrored not supported on 26100.3194 (2025) — https://learn.microsoft.com/en-us/answers/questions/3898666/wsl-mirrored-networking-mode-is-not-supported-wind
21. `0x8007274c`: WSL #11975 (2024-08-30, closed 2024-09-06) — https://github.com/microsoft/WSL/issues/11975 ; Cursor forum (2025) — https://forum.cursor.com/t/wsl-connection-to-cursor-server-failed/152258 ; MS Q&A — https://learn.microsoft.com/en-us/answers/questions/1524521/wsl2-0x8007274c
22. openSUSE #178561 (Mar 2025, secondary) — https://progress.opensuse.org/issues/178561 ; WSL #9521 (2023-01-23, open) — https://github.com/microsoft/WSL/issues/9521
23. Lima VM types — https://lima-vm.io/docs/config/vmtype/ ; vz — https://lima-vm.io/docs/config/vmtype/vz/ ; VMNet (vzNAT, socket_vmnet) — https://lima-vm.io/docs/config/network/vmnet/
24. Docker rootless troubleshooting — https://docs.docker.com/engine/security/rootless/troubleshoot/ ; podman-rootless(7) — https://man.archlinux.org/man/podman-rootless.7.en
25. Home Assistant deprecation (2025-05-22) — https://home-assistant.io/blog/2025/05/22/deprecating-core-and-supervised-installation-methods-and-32-bit-systems/ ; architecture discussion #1198 — https://github.com/home-assistant/architecture/discussions/1198
26. Docker Hub pull limits — https://docs.docker.com/docker-hub/usage/pulls/ ; GitLab (2025-03-24) — https://about.gitlab.com/blog/prepare-now-docker-hub-rate-limits-will-impact-gitlab-ci-cd/ ; heise — https://heise.de/-10329047
27. Registry comparison (2026, secondary) — https://guptadeepak.com/tools/top-8-container-registries-2026/
28. npm registry API — https://github.com/npm/registry/blob/main/docs/REGISTRY-API.md ; package metadata — https://github.com/npm/registry/blob/main/docs/responses/package-metadata.md
29. Cargo index format — https://doc.rust-lang.org/cargo/reference/registry-index.html ; Rust 1.70 (2023-06-01) — https://blog.rust-lang.org/2023/06/01/Rust-1.70.0/ ; cargo-yank — https://www.mankier.com/1/cargo-yank
30. Go modules reference (GOPROXY protocol, checksum database) — https://go.dev/ref/mod ; sumdb proposal — https://go.googlesource.com/proposal/+/refs/heads/master/design/25530-sumdb.md ; x/mod v0.40.0 advisories (2026-08-13) — https://groups.google.com/g/golang-dev/c/LLsoNHridf4
31. Homebrew 4.0.0 (2023-02-16) — https://brew.sh/2023/02/16/homebrew-4.0.0/ ; API — https://formulae.brew.sh/docs/api/
32. winget-cli-restsource releases — https://github.com/microsoft/winget-cli-restsource/releases ; winget source — https://learn.microsoft.com/windows/package-manager/winget/source
33. Scaling Flathub (2020-11-20) — https://blogs.gnome.org/alexl/2020/11/20/scaling-flathub/
34. Nix flake-registry — https://github.com/NixOS/flake-registry ; nix3 registry — https://nix.dev/manual/nix/2.27/command-ref/new-cli/nix3-registry
35. Helm OCI + Flux cosign (2022-11-24) — https://www.cncf.io/blog/2022/11/24/verify-the-integrity-of-the-helm-charts-stored-in-oci-compliant-registries-as-oci-artifacts/ ; distribution-spec v1.1.0 (2024-02-15) — https://github.com/opencontainers/distribution-spec/releases/tag/v1.1.0
36. Sigstore keyless — https://edu.chainguard.dev/open-source/sigstore/how-to-keyless-sign-a-container-with-sigstore ; cosign 2 identity flags (2026-08-11) — https://oneuptime.com/blog/post/2026-08-11-cosign-keyless-signing-explained/markdown ; adoption/Rekor limits (2026) — https://jacar.es/en/sigstore-in-image-registries-adoption-and-reality/
37. minisign(1) — https://manpages.opensuse.org/Tumbleweed/minisign/minisign.1.en.html
38. npm provenance (2023-04-19) — https://github.blog/security/supply-chain-security/introducing-npm-package-provenance/ ; PyPI attestations — https://docs.pypi.org/attestations/security-model/ ; 2026 critique — https://dev.to/indra_gustiprasetya_a80a/why-npm-trusted-publishing-didnt-stop-the-attack-1kib
39. TUF spec 1.0.37 (2026-10-08) — https://theupdateframework.github.io/specification/latest/ ; RH TAS 52-week expiry — https://docs.redhat.com/en/documentation/red_hat_trusted_artifact_signer/1.1/html/administration_guide/updating-the-tuf-metadata-files_admin ; root-rotation incident — https://knowledgebase.securityhive.io/en/articles/606543-securityhive-vulnerability-agent-update-issue-due-to-root-key-rotation
40. R2 pricing (2026-10-01) — https://developers.cloudflare.com/r2/pricing/ ; GitHub Pages limits — https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits ; Bunny pricing — https://docs.bunny.net/cdn/pricing
41. Tailscale sharing — https://tailscale.com/kb/1084/sharing ; inviting vs sharing — https://tailscale.com/docs/reference/inviting-vs-sharing
42. Syncthing getting started — https://docs.syncthing.net/v1.0.0/intro/getting-started.html ; introducer — https://docs.syncthing.net/v1.0.0/users/introducer.html ; relay server — https://docs.syncthing.net/users/strelaysrv ; stdiscosrv — https://mankier.com/1/stdiscosrv
43. Matrix MSC1543 QR verification — https://github.com/matrix-org/matrix-spec-proposals/blob/main/proposals/1543-qr_code_key_verification.md
44. Tailscale DERP — https://tailscale.com/kb/1232/derp-servers ; firewall ports (Jul/Aug 2025 notes) — https://tailscale.com/kb/1082/firewall-ports
45. Headscale DERP — https://headscale.net/stable/ref/derp/
46. TURN pricing (2026, vendor) — https://www.expressturn.com/vs-coturn-self-hosted ; https://www.metered.ca/blog/azure-turn-server/
47. OpenID Federation 1.0 Final (2026-02-17) — https://openid.net/specs/openid-federation-1_0.html ; explainer — https://nhimg.org/faq/what-is-the-difference-between-openid-federation-and-normal-oidc-trust/
