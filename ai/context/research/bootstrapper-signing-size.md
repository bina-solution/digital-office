# Bootstrapper research: signing, size, OS realities, hosting (2026-10-14)

Scope: `dgo-install` (stdlib Go, Ed25519-verified `manifest.json`, fails closed), `packaging/relsign`, `build-binaries.sh`
(`CGO_ENABLED=0 -trimpath -buildvcs=false -ldflags "-s -w"`), manifest at `https://digital-office.co.il/dl/<os>/<arch>/manifest.json`.
Target: one stub per OS, ≤5 MB, "next, next".

## 0. Measured here (Go 1.22.3, `CGO_ENABLED=0 -trimpath`, bytes)

| Probe | Imports | win/amd64 plain | **win/amd64 `-s -w`** | darwin/arm64 `-s -w` | linux/amd64 `-s -w` |
|---|---|---|---|---|---|
| A hello | `fmt` | 1,984,000 | **1,328,128** | 1,365,954 | 1,228,952 |
| B "obvious" stub | `net/http` `encoding/json` `fmt` `crypto/ed25519` `crypto/sha256` | 7,480,832 | **5,179,392** | 4,945,042 | 5,042,328 |
| C "minimal" stub | `crypto/tls` + hand-written HTTP/1.1 GET, `crypto/ed25519`, `crypto/sha256`, `os` | 5,519,360 | **3,786,752** | 3,559,234 | 3,653,784 |
| D Bubble Tea v1.3.4 alone | `bubbletea`, `os` | — | **2,874,368** | — | — |

B is today's `dgo-install` (same imports plus `flag`,`net/url`,`os/exec`,`time`): **5.2 MB is already the stripped size** —
`build-binaries.sh` line 143 passes `-s -w`. 5,179,392 B = 4.94 MiB (Explorer shows "4.93 MB"): fix the budget in bytes.
Peer: `rustup-init.exe` x86_64 = 12,721,664 B (HEAD, static.rust-lang.org, 2026-10-14).

## 1. Signed manifest + self-update

| Scheme (2026) | What it is | Fit for a solo vendor with one offline key |
|---|---|---|
| **minisign / raw Ed25519** | Detached sig, 8-byte key id, signed *trusted comment* (put file name + version there against downgrade); new code must use the BLAKE2b-prehashed `ED` form — [spec v0.12](https://jedisct1.github.io/minisign/) | **Proportionate.** No rotation/revocation in the format — add it (below). Zig ships every artifact + `.minisig`, packagers pin the key ([0.16.0](https://ziglang.org/download/0.16.0/zig-x86-linux-0.16.0.tar.xz.minisig), [ziggit](https://ziggit.dev/t/cd-via-gh-f-gl/8269?page=2)) |
| **TUF / go-tuf v2** | Root/targets/snapshot/timestamp roles, thresholds, chained `root.json` rotation — [spec v1.0.37, 2026-10-08](https://theupdateframework.github.io/specification/latest/) | Overkill as code (online timestamp key; go-tuf v2 threshold-0 and panic bugs until 2.3.1, path traversal until 2.4.1 — [advisories](https://releasealert.dev/github/theupdateframework/go-tuf/cves)). **Borrow its rules.** |
| **Sigstore / cosign keyless** | OIDC identity + Fulcio cert + Rekor log; trust root itself via TUF ([FAQ](https://docs.sigstore.dev/about/faq/)) | Moves signing to an online CI identity; verifier pulls TUF+Fulcio+Rekor+protobuf (Debian `sigstore-go` 1.1.4 = 14.5 MiB, [pkg](https://packages.debian.org/sid/source/sigstore-go)). Optional extra layer, never the stub's path. |
| **Notation (Notary v2)** | X.509 trust stores for OCI artifacts ([2026-08-11](https://oneuptime.com/blog/post/2026-08-11-cosign-vs-notation-image-signing/view)) | Only for registry distribution. No. |

| Peer | Updater | Verification |
|---|---|---|
| rustup | `rustup-init` (12.7 MB), `curl \| sh` | HTTPS + `.sha256`; GPG **removed in 1.26.0**, "missing key rotation" ([2023-04-25](https://blog.rust-lang.org/2023/04/25/Rustup-1.26.0/)); rustls since 1.28.0 ([2025-03-02](https://blog.rust-lang.org/2025/03/02/Rustup-1.28.0/)) |
| **Tailscale** | `tailscale update` | **Ed25519 two-tier**: offline *root keys compiled in*, online *signing keys* in `distsign.pub` signed by a root, per-file `.sig`; several roots so one retires without a new client ([distsign](https://pkg.go.dev/tailscale.com/clientupdate/distsign)) |
| Syncthing | built-in | ECDSA per binary, pubkey compiled in; GPG-signed checksums for humans ([docs](https://docs.syncthing.net/dev/release-signing.html)) |
| Caddy | `caddy upgrade` | experimental, backs up old binary, no checksum/signature mentioned ([docs](https://caddyserver.com/docs/command-line)) |
| Deno | `deno upgrade` | HTTPS; `--checksum` only with a user-supplied hash ([docs](https://docs.deno.com/runtime/reference/cli/upgrade/)) |
| Bun | `bun upgrade` | HTTPS only ([docs](https://bun.com/guides/util/upgrade)) |

**Recommendation — Tailscale shape, TUF rules, minisign bytes:**
- Stub embeds **two root public keys** (one in a safe). `keys.json` (+ `.sig` by a root) lists active signing keys with `not_after`.
  Signing-key rotation = new `keys.json`; revocation = drop it, bump its version. Root rotation = new stub signed by the spare root ([TUF §6.1](https://theupdateframework.github.io/specification/latest/)).
- **Sign the whole manifest bytes** (not `version\nurl\nsha256` as today) so new fields are covered; keep SHA256SUMS + `.minisig` for humans.
- **Rollback + freeze**: integer `version` persisted by the client, never decreasing ([TUF §4.3, §5.4.3](https://theupdateframework.github.io/specification/latest/)); `expires` checked against a time fixed at update start (§5.1, §5.4.4); `min_bootstrapper` makes old stubs self-update first.
- Per-target `sig` is redundant once the manifest is signed; `size` bounds the download before hashing.

```json
{"schema":1,"channel":"stable","version":42,"released":"2026-10-14T00:00:00Z","expires":"2026-11-13T00:00:00Z",
 "min_bootstrapper":"1.2.0","signing_key_id":"k2026a",
 "targets":{"windows/amd64":{"url":"https://digital-office.co.il/dl/windows/amd64/dgo-core-1.9.3.zip","size":48213001,"sha256":"…"}}}
```
`manifest.json.sig` = Ed25519 over the raw file (minisign `ED` prehash if `minisign -V` compatibility is wanted).

## 2. Size: under 5 MB on windows/amd64

| Lever | Effect | Verdict |
|---|---|---|
| `-s -w` | −31% (7.48→5.18 MB); the Go FAQ's sanctioned reducer ([faq](https://go.dev/doc/faq)) | already done |
| **Drop `net/http`** (≈60-line HTTP/1.1 GET over `crypto/tls`) | **−1.39 MB (5.18→3.79 MB)**; the h2 bundle alone ≈0.6 MB ([issue 35082](https://golang.org/issue/35082)) | **the lever.** Cost: no proxy/redirect/HTTP2 — fine for a fixed URL; send `Connection: close`, refuse chunked |
| Drop `fmt`, `encoding/json` | small — `reflect`/`asn1` stay via `crypto/x509` | cheap, do it |
| `GOAMD64=v3` | −5 KB (5,174,272 / 3,782,656) | skip |
| garble `-tiny` | 2–15% claimed ([README](https://awesome.ecosyste.ms/projects/github.com%2Fburrowers%2Fgarble)); hides panics, hurts AV reputation | skip |
| **UPX** | Defender flags *packed* output ([SANS ISC 2022](https://isc.sans.edu/diary/28960)); macOS crash [#612](https://goodfirstissue.org/upx/upx/issues/612) open since 2022, no arm64 Mach-O ([Wikipedia](https://en.wikipedia.org/wiki/UPX)); Apple's notary rejects what it can't unpack ([Go CL](https://go.googlesource.com/go/+/a106f55360744cdaf41edc5f3e265dedf7bbf566)) | **never** |
| Bubble Tea | +1.55 MB → C + TUI ≈ 5.3 MB | too fat |
| Fyne / webview | cgo, OpenGL/WebKit, tens of MB ([Fyne](https://docs.fyne.io/explore/compiling/)) | no |

**Floor** for stdlib HTTPS + Ed25519: **≈3.6–3.8 MB** (runtime 1.3 MB + `crypto/tls`+`x509`+`net` ≈2.4 MB). Go 1.25's DWARF5 is moot once `-w` strips DWARF ([LWN](https://lwn.net/Articles/1033646/)).

## 3. OS realities for "next, next"

**Windows** ([code-signing options, 2026-08-29](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options); [SmartScreen reputation, 2026-05-04](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation))

| Fact | Consequence |
|---|---|
| Unsigned EXE: "Windows protected your PC"; reputation per *file hash*, reset each release; enterprises / Smart App Control may block outright | unsigned stub is dead for business users |
| **Azure Artifact Signing** (~$9.99/mo): orgs US/CA/EU/UK, individuals US/CA only | **unavailable to an Israeli vendor** |
| OV cert $150–300/yr worldwide, HSM/token mandatory since June 2023; EV ($400+) no longer bypasses SmartScreen (2024) | buy OV, one identity for everything; "several weeks and hundreds of clean installs", no consumer submission path |
| Stub installers rarely change, so reputation persists across releases ([Lawrence 2024-11-15, upd. 2026-09-24](https://textslashplain.com/2024/11/15/best-practices-for-smartscreen-apprep/)) | **keep the stub stable; change manifest + payload** |
| MSIX = trusted cert + Store; winget `portable` type copies the EXE to `%LOCALAPPDATA%\Microsoft\WinGet\Packages`, symlink in `Links` ([Settings.md](https://github.com/microsoft/winget-cli/blob/master/doc/Settings.md)); submissions hash-validated and scanned ([Learn](https://learn.microsoft.com/vi-vn/windows/package-manager/package/repository)) | signed plain EXE now, winget manifest later, no MSIX |
| Go binaries trip AV heuristics ([faq](https://go.dev/doc/faq)) | sign, add VERSIONINFO, no packer |

**macOS**: Developer ID + notarization need the $99/yr program ([memberships](https://developer.apple.com/support/compare-memberships)). Sequoia removed the Ctrl-click bypass ([2024](https://www.bleepingcomputer.com/news/apple/macos-sequoia-brings-better-gatekeeper-stalkerware-protections)). A bare Mach-O **cannot be stapled**; notarize the outermost `.pkg`/`.dmg`; a quarantined tool double-clicked in Finder fails regardless, so install via `.pkg` (installed files aren't quarantined) or run from Terminal ([Quinn/DTS 2021](https://developer.apple.com/forums/thread/689337)). `curl` sets no quarantine xattr, so `curl | sh` skips Gatekeeper ([Unit 42](https://unit42.paloaltonetworks.com/gatekeeper-bypass-macos)). Homebrew 5.0 demands signed + notarized casks ([Workbrew](https://workbrew.com/blog/homebrew-5-0-0)) and 75 stars/30 forks (225/90 self-submitted) ([policy](https://docs.brew.sh/Package-Acceptance-Policy)). → signed, notarized **`.pkg`** (root layout, `/etc/paths.d`) + `curl | sh`.

**Linux**: norm = POSIX script, all logic in one `main()` called on the last line so a truncated download runs nothing; Tailscale's adds a signed apt/rpm repo, `sudo`/`doas`, `set -eu`, HTTPS only ([install.sh](https://tailscale.com/install.sh)). Layer 0 is daemons → `.deb/.rpm` or binary + `systemctl --user`; `loginctl enable-linger` survives logout, polkit may deny it ([loginctl(1)](https://manpages.org/systemd-loginctl)). Flatpak is "for desktop applications", exports no systemd services ([docs](https://docs.flatpak.org/en/latest/introduction.html)); AppImage likewise — skip.

**UI**: native dialogs, no cgo, ~no bytes: [ncruces/zenity](https://github.com/ncruces/zenity) (Win32 via `x/sys`, `osascript` on macOS, system `zenity` on Linux) for language/terms/location; flags (`--accept-terms --lang he --dir`) for unattended. The real wizard belongs to DGO core.

## 4. Hosting

| Option | Limits | Notes |
|---|---|---|
| **GitHub Releases** | free, 2 GiB/file, no bandwidth cap ([docs](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)) | `…/releases/latest/download/<asset>` is a stable redirect ([docs](https://docs.github.com/en/repositories/releasing-projects-on-github/linking-to-releases)); **never call the API from the stub: 60 req/h unauthenticated** ([limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)) |
| **Cloudflare R2** behind `digital-office.co.il/dl` | 10 GB, 1 M class A, 10 M class B free, **egress free**, $0.015/GB-mo ([pricing](https://developers.cloudflare.com/r2/pricing/)) | caching only on a custom domain, not `r2.dev` ([docs](https://developers.cloudflare.com/r2/buckets/public-buckets/)) |
| Pages / Workers assets | 25 MiB per file ([limits](https://developers.cloudflare.com/pages/platform/limits)) | stub yes, core payloads no |
| GHCR via ORAS | free public | token dance, classic PATs ([oras](https://oras.land/docs/how_to_guides/remote_registries)) — no |

**CDN gotchas** ([defaults](https://developers.cloudflare.com/cache/concepts/default-cache-behavior/)): Cloudflare does **not** cache `.json` by default but **does** cache `.exe/.zip/.dmg/.gz`, 120-min TTL when no `Cache-Control` — a payload replaced in place is stale for 2 h. So: versioned immutable payload names (`max-age=31536000, immutable`); manifest `public, max-age=60, must-revalidate` + ETag, published *after* payloads, purged on release; `.sig` same TTL; assert `cf-cache-status` in CI.

## Stack and the three biggest risks

**Stack**: stdlib stub without `net/http` (≈3.8 MB); two embedded Ed25519 roots → online signing keys → whole-manifest signature with monotonic `version`, `expires`, `min_bootstrapper`; OV Authenticode (Windows), Developer ID + notarized `.pkg` (macOS), `curl | sh` + signed repo later (Linux); payloads on R2 at `digital-office.co.il/dl`, mirrored to GitHub Releases; zenity-style dialogs, flags for unattended.

1. **Windows trust**: Artifact Signing excludes Israel; OV needs an HSM and weeks of reputation; a changing stub resets it.
2. **Size is architectural**: already stripped; only removing `net/http` clears 5 MB, at the price of proxy/redirect support.
3. **Keys**: one key with no rotation plan = a new stub per incident; the two-root + signing-key layer must exist before the first public release.
