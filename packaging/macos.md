# macOS — implementable spec

> **Status 2026-09-17 — what runs today (Phase 2a).** The native `.app` below is still the
> target; what exists now is the same engine shape as Windows, delivered with Lima:
> `./bbox run` on a Mac fetches a pinned, checksum-verified Lima (Apache-2.0, ~45 MB, into
> `~/.bbox/macos`), boots an Ubuntu 24.04 arm64 guest on Apple's Virtualization.framework with
> **Docker CE 28.5.2 pinned** (`apt-mark hold`) and the same `10-bbox-endpoint.conf` drop-in the
> VPS has, mounts `$HOME` into the guest so the checkout is at the SAME path, and hands every bbox
> verb across as root — the exact design of `bbox.cmd → WSL`. No admin, no Docker Desktop, no
> Homebrew. Files: [`engine.yaml`](macos/engine.yaml) (the guest, pinned image digest + provisioning),
> [`engine.sh`](macos/engine.sh) (`bbox engine start|stop|status|shell|socket|doctor|destroy`),
> [`fetch-runtime.sh`](macos/fetch-runtime.sh) (the Lima pin). Two costs, both from this spec's
> "honest :80/:443 answer": the edge is on **`http://<app>.localhost:8080`** (an unprivileged
> process cannot bind :80 on macOS — measured), and amd64-only images need Rosetta, which is
> Apple's to install (`softwareupdate --install-rosetta`); the engine uses it when present. Sizing:
> a ≤8 GB Mac gives the guest 5 GiB (the `ci-small` floor) and 4 cpus; `BBOX_VM_MEM/CPUS/DISK`
> override. Safari before macOS 26 does not resolve `*.localhost` — use Chrome there.
>
> **The port is not cosmetic.** authentik's proxy outpost matches a request to its provider by the
> full `Host` header, port included, so every browser-facing `*_BASE_URL` (and `AUTH_EXTERNAL_URL`)
> must read `<host>.localhost:8080` on this engine. `bbox run` generates exactly that `.env` when
> none exists (`scripts/ci-env.sh` with `CI_DEPLOYMENT_NAME=local CI_EDGE_PORT=8080`); a hand-written
> `.env` with bare hosts gives a 404 on every SSO-gated app while `bbox status` reports all green.
> Measured first run on an 8 GB M-series Mac, baseline of 37 services: ~5 min warm, ~4.2 GiB of
> the 5 GiB guest in use, 33/33 healthy.

Target: a signed, notarized `.app` using Apple's Virtualization.framework that boots a Linux guest,
runs dockerd inside it, and brings the stack up. macOS is the **only** one of the three platforms
where zero-admin is genuinely achievable — see the Tier 0 / Tier 1 split below for the one caveat.

**Deployment target: macOS 13.** `VZEFIBootLoader`, `VZEFIVariableStore`, and a host-reachable NAT
IP are all 13.0+.

## Four decisions that differ from the first draft

**1. `VZEFIBootLoader` + a bootable raw disk, not kernel + initrd.** `VZLinuxBootLoader` on arm64
needs an *uncompressed* kernel (arm64 has no self-decompressor), so the kernel+initrd path means
owning a gunzip step and a kernel cmdline. Every EFI-capable project converged on EFI; Lima's vz
driver shipped EFI-only and no Lima template uses the kernel/initrd path at all.

**2. Pre-bake `/var/lib/docker` into the guest disk image.** This is the biggest single change and
it is not macOS-specific. Rather than shipping a `docker save` tarball and importing it on the
customer's machine, the guest image is built in CI with every pinned image already pulled into its
docker data root — the approach `kind` uses for node images.

| | `docker load` at first run | pre-baked image |
|---|---|---|
| First run | 8–25 min, dominated by the import | ~30 s boot |
| Peak disk | ~34 GB (bundle + unpacked layers) | ~15 GB |

It also deletes a whole class of failure: no partially-imported state, no "extract 3 GB to `%TEMP%`
on a full C: drive". **This supersedes the `docker load`-on-first-run design in the main README for
macOS and Windows.** It does *not* apply to Linux, where we install into the host's own Docker and
`docker load` remains correct.

**3. Payload outside the `.app`.** `codesign` SHA-256s every byte under the bundle into
`CodeResources` (special slot -3) and Gatekeeper re-hashes on first launch, so a 3 GB payload
inside the bundle makes signing and first launch both O(3 GB) — and any in-place extraction breaks
the signature. Apple's explicit guidance is to put non-executable data *next to* the notarized
component inside one disk image.

**4. gvisor-tap-vsock is not needed.** It is, by its own README, "a replacement for libslirp and
VPNKit" — it exists for QEMU/Hyper-V/UML, which have no NAT of their own. VZ does.

## Networking, and the honest :80/:443 answer

The guest binding :80/:443 is a non-issue — Traefik is root inside the VM. The constraint is only
about the macOS **host**. Binding <1024 on macOS requires root with no per-user exemption (XNU
gates it on `PRIV_NETINET_RESERVEDPORT` → `EACCES`); LaunchAgents run as the user, so only a
LaunchDaemon can, and installing one needs admin.

But **connecting out to a low port was never privileged**, which is the escape hatch OrbStack uses:
resolve the name to the container's real IP and connect to :80 there, with no host-side bind.
Docker Desktop took the other route and pays for it with `com.docker.vmnetd` in
`/Library/PrivilegedHelperTools` — that is their admin prompt at install.

What actually blocks a clean URL here is **DNS, not ports**. This stack routes by `Host()` header
across 31 unique subdomains, so the port can be anything but the name must resolve. Without admin
we cannot write `/etc/hosts` or `/etc/resolver/`.

**Tier 0 — zero admin (default).** `DEPLOYMENT_DOMAIN=bina.localhost`, host proxy on a high
loopback port, URLs like `http://n8n.bina.localhost:8080`.
- Plain HTTP is correct here and not worth fighting: W3C Secure Contexts treats a host ending in
  `.localhost` as **Potentially Trustworthy**, so WebCrypto, service workers and `getUserMedia` all
  work without TLS.
- This also dodges a hard wall — a trusted root CA **cannot** be installed without user
  interaction. Apple DTS: "there's no supported solution. This isn't a bug but a deliberate
  security hardening." So a bundled mkcert-style CA is out.
- Drop `--certificatesresolvers.myresolver.acme.*` from the macOS profile. ACME cannot work
  airgapped, and `platform-base/traefik/docker-compose.yml` currently sets an httpchallenge
  resolver unconditionally.
- ⚠️ **Safari does not resolve `*.localhost` before macOS 26** (WebKit bug 160504, fixed below
  WebKit in Tahoe). Chrome and Firefox bypass the system resolver and always work. This is the real
  cost of Tier 0 and belongs in the install docs, not in a footnote.

**Tier 1 — one admin prompt (optional).** A LaunchDaemon that keeps 31 `/etc/hosts` entries pointed
at the guest IP. With that alone you get `http://n8n.bina.test` on port 80 connecting *straight to
the guest* — no host bind at all. Pin the guest MAC via `VZMACAddress` so the vmnet DHCP lease is
stable. Mark the `/etc/hosts` block with sentinel comments so uninstall can remove it surgically.

**Also remap 5432 and 6379.** Traefik binds both as entrypoints
(`platform-base/traefik/docker-compose.yml:22-23`). They are >1024 so they are free, but they will
collide with a local Postgres or Redis on a developer's Mac.

## Inbound: what reaches the guest, and what the guest is told (2026-10-05)

`engine.yaml`'s `portForwards` is the whole answer to "what can dial this Mac", and it is deliberately
short: the edge (guest 80/443 → host 8080/8443) and the **pair tunnel's UDP port** (51830 → 51830 on
`0.0.0.0`, `proto: udp`). The tunnel rule is what makes mac↔mac and mac↔Windows(NAT) pair at all —
before it, a Mac office could only DIAL, and the contract's screens said so
([`ai/context/dgo-pairing-contract.md`](../ai/context/dgo-pairing-contract.md) §C). Two facts about
that rule are easy to get wrong and are therefore written down in `engine.yaml` next to it: Lima
binds `127.0.0.1` unless `hostIP` says otherwise, and **UDP is only supported by the GRPC
forwarder** (the default since Lima v1.1.0, so the pinned 2.2.0 has it; `LIMA_SSH_PORT_FORWARDER=true`
silently cannot).

The guest cannot see its Mac's LAN address, nor whether a packet reaches it — so `engine.sh` hands
both across in the same `limactl shell` every command already goes through, as `BBOX_HOST_LAN_ADDR` /
`BBOX_HOST_UDP_PORT`. The hand-off needs the rule declared and the Mac to have an address; it **never
waits for the socket**, and that is a correction with a reason — the chain closes in ONE direction:
rule → the office publishes the port → something in the guest listens → Lima opens the Mac's socket
(`hostagent.go`: only a `static: true` rule is bound at startup, and that path is `forwardTCP`, TCP
only; every other rule reaches the forwarder through a guest port event). Gating the hand-off on the
socket is therefore a closed loop — no hand-off, no declaration, nothing listening, no socket — and a
fresh Mac would stay `engine-guest` forever. The socket is a **measurement**: `./bbox engine forwards`
prints the whole chain (declared · guest listening · Mac socket) and names the one link that is open,
and after a Mac `bbox run` the same check runs once, warning only when `.env` already publishes the
port and the guest is up but the Mac holds nothing — which is when the two real candidates (macOS
incoming-connection consent, `LIMA_SSH_PORT_FORWARDER`) apply.
`apps/dgo-extend/hooks/prepare` consumes the two variables; with nothing handed over the guest stays
`DGO_WG_DIAL_ONLY=engine-guest`, exactly as before.

```bash
./bbox engine forwards           # the chain — declared · guest listening · Mac socket — and the open link
./bbox engine forwards --apply   # an engine created before the rule: stop → edit → start → bbox run
./bbox engine doctor             # the same facts beside versions and sizing
```

`--apply` converges the DECLARATION and nothing else, so an instance that already declares the rule
costs no downtime at all. It must be run from the Mac's own Terminal: it stops the guest, and the
office (agents included) lives inside it. Nothing in this stack declares a restart policy, so no
container comes back on its own — that is why the same run ends with `bbox run`.

## Guest image — Alpine, and the licensing that decides it

Licensing rules out the obvious choice. Canonical's IP policy permits redistributing **unmodified**
Ubuntu images, but "any redistribution of modified versions of Ubuntu must be approved… otherwise
you must remove and replace the Trademarks and will need to recompile the source code". Installing
Docker into the image makes it modified. Colima ignores this; a paid closed-source product should
not.

**Use Alpine.** musl (MIT) instead of glibc removes the LGPL relinking obligation, shrinking the
GPL surface to roughly busybox + kernel + iptables. Start from the `-uefi-` cloud images, or clone
[`lima-vm/alpine-lima`](https://github.com/lima-vm/alpine-lima)'s `mkimage` pipeline (Apache-2.0),
which is already proven under vz and is what Rancher Desktop ships.

> **GPL obligation — do not defer this.** Shipping a Linux kernel means *conveying* GPL-2.0 code.
> GPLv2 §3(c) (passing along someone else's offer) "is allowed only for noncommercial
> distribution", so a commercial installer needs either accompanying machine-readable source or a
> **written offer valid three years**. Automate a pinned source-tarball snapshot in the same CI job
> that builds the image; retrofitting this is painful. Our own closed-source host app is
> unaffected — it talks to GPL programs at arm's length over vsock, exactly as Lima and podman do.

**Gate the kernel config.** dockerd needs `CONFIG_OVERLAY_FS`, `CONFIG_BRIDGE`,
`CONFIG_BRIDGE_NETFILTER`, `CONFIG_VETH`, `CONFIG_IP_NF_NAT`, cgroup v2 + `CONFIG_CGROUP_BPF` and
more. Make `moby/moby contrib/check-config.sh` a hard CI gate: build → boot under VZ → run it →
fail on any missing option.

## Disk

`VZDiskImageStorageDeviceAttachment` accepts **RAW** and **ASIF** only — never qcow2. RAW is the
baseline and is already sparse on APFS. ASIF is macOS 26+, has no API (shell out to `diskutil image
create`), and has known sandbox issues — treat it as an opportunistic optimization.

Grow by `ftruncate()`ing the raw file while the VM is off, then `growpart` + `resize2fs` in-guest.
There is no VZ resize API.

Location: `~/Library/Application Support/<bundle-id>/` as a bundle holding `Disk.img`,
`MachineIdentifier` and `NVRAM`. **Not `Caches`** — the system may delete it under disk pressure and
silently destroy the VM.

**Time Machine will back up a 15 GB disk image in full on every change**, with no block-level dedup,
because `Application Support` is not in `StdExclusions.plist`. Set the sticky xattr
`com.apple.metadata:com_apple_backup_excludeItem` on the bundle at creation; verify with
`tmutil isexcluded`.

**Do not sandbox.** Non-sandboxed is the normal Developer ID VZ configuration, avoids the
`diskutil` sandbox bug, and avoids container-path redirection for a multi-GB image.

## Signing and notarization

The entitlements file is genuinely this short:

```xml
<dict>
    <key>com.apple.security.virtualization</key>
    <true/>
</dict>
```

A standard **$99/yr** membership is sufficient — the entitlement is a plain Boolean needing no
provisioning profile or Apple approval. Hardened runtime does not conflict with VZ and needs no
exceptions; do **not** add `allow-jit` (VZ is not a JIT — guest code runs at EL1 and the host maps
no RWX pages). `com.apple.security.hypervisor` is for Hypervisor.framework and is not needed.

**The Zip64 limit is a ZIP limit, not a submission limit.** A DMG has no documented size cap;
submissions of ~100 GB are reported working. The failure mode when it does bite is misleading — it
reports "The signature of the binary is invalid" when the signature is fine.

Order — this is the one place Apple's "notarize only the outermost container" rule and the fact
that a DMG-stapled ticket does not travel pull in opposite directions:

```
1. codesign the .app inside-out (--options runtime --timestamp --entitlements)
2. notarytool submit MyApp.zip        → fast, tens of MB
3. stapler staple MyApp.app           ← ticket now travels with the app
4. build DMG (UDZO): MyApp.app + the payload as a SIBLING
5. codesign the DMG
6. [optional] notarytool submit + staple the DMG   → 30–90 min upload
```

Budget **30–90 min upload** plus minutes-to-hours processing for a 2–5 GB DMG; upload is the
bottleneck and is fragile (S3 Transfer Acceleration; multipart failures are common on some
networks). Limit is **75 notarizations/day**.

⚠️ **App translocation**: a quarantined app launched *from* the DMG runs from a randomized
read-only mount, so relative paths to the sibling payload break. Require drag-to-`/Applications`
first, then read the payload by absolute path from the mounted volume, verifying a SHA-256 pinned
inside the signed binary.

## Uninstall

Dragging to Trash leaves the entire ~15 GB disk image behind — this is exactly Docker Desktop's
reputation problem. Ship an in-app **Uninstall** that stops the VM, deletes the Application Support
bundle, unloads the LaunchAgent, and invokes the Tier 1 daemon's self-uninstall if one was
installed.

## Sleep, screen lock and the lid — built (2026-09-29)

A sleeping Mac freezes the VM and everything in it; measured on this MacBook, idle sleep followed
the display turning off by ~7 s (pmset `sleep 1`, on power AND on battery), and running agents spent
28 of 43 hours frozen. No container runtime on macOS (Docker Desktop, OrbStack, Colima, Lima,
Podman) keeps the Mac awake; OrbStack even pauses containers on sleep.

- **Policy** — the console's settings view (הגדרות מסוף → "חשמל ושינה"): per situation (screen
  locked/display off, lid closed) × power source (AC, battery), "keep working" or "sleep"; plus a
  battery floor and a thermal guard. Stored in `data/power/policy.json` through the machine service
  (`/api/power`, the owner of host facts).
- **Enforcement** — `packaging/macos/power-agent.py`, started by `bbox engine start` (and any
  `./bbox …` hand-off), tied to the engine's host-agent PID; `./bbox engine power status|start|stop`.
  Screen lock / display off: a `caffeinate -i` assertion (no admin). Lid closed: macOS sleeps no
  matter what an assertion says; the only switch is `pmset -a disablesleep 1` (root), used only if
  the owner installs the narrow sudoers rule the card shows (plus a boot job that clears it, since it
  persists across reboots). `disablesleep` also disables macOS's own low-battery and
  thermal-emergency sleep, so the agent's battery floor and thermal guard (critical at once, serious
  for 5 min) are not optional; releasing with the lid closed is followed by `pmset sleepnow`.
- **Without the admin step**: AC + an external display keeps a closed Mac running (clamshell mode).
- Status (what the agent saw, recent sleeps/wakes from `pmset -g log`) is in `data/power/status.json`.

## Intel Macs

The same app works — VZ supports both architectures. But there is **no cross-arch emulation**, so
Intel runs amd64 guests and Apple Silicon runs arm64: **two disk images, roughly double the artifact
matrix.** That is the real cost, not code. Note that podman-machine-os builds `applehv` for aarch64
only — nobody in this space ships Intel VZ artifacts, so expect to find the bugs.

## Host sizing — from this stack's actual numbers

Declared memory limits across the stack total **45.2 GB** (reservations 9.6 GB). `ollama` (6 G) and
`openhands` (8 G) are the top two and are already gallery apps shipping disabled, which removes 14 GB
of ceiling from a default install — keep it that way for the laptop profile.

Realistic guest allocation is **12–16 GB RAM**, so: **24 GB Mac minimum, 32 GB comfortable.** State
it as a hard requirement. Clamp `cpuCount` to `min(physicalCores - 2, …)` — setting it above
physical cores is documented to grind both host and guest.


## Building for macOS ON LINUX — corrected, and it is the standard path

An earlier draft of this file implied a Mac is required to *build*. That conflated two different
things: **running** macOS in a VM is licence-restricted to Apple hardware; **building for** macOS
on Linux is routine and done on Linux CI every day.

The full pipeline, all Linux-native:

| Need | Tool | Linux |
|---|---|---|
| Compile Go for darwin/arm64 | `GOOS=darwin GOARCH=arm64 go build` | built in |
| Compile cgo + Apple frameworks | **osxcross** + macOS SDK | yes |
| Code-sign the `.app` | **`rcodesign`** (apple-codesign, Rust) | yes |
| **Notarize** with Apple | `rcodesign notarize` — talks to the notary API directly | **yes** |
| Build the `.dmg` | **`libdmg-hfsplus`** | yes |

**VERIFIED on the portable box (2026-07-28):** Go 1.24.5 installed, `go tool dist list` reports
`darwin/amd64` and `darwin/arm64`. Cross-compilation targets are available with no extra setup.

This matters more here than it would elsewhere because the spec already rejected a Swift host app
in favour of **vfkit** (crc-org, Apache-2.0) — which is **Go**. That choice was made to avoid
Swift, and it happens to make the cross-build tractable.

**The one real caveat:** vfkit uses cgo to reach `Virtualization.framework`, so it is not a pure
`GOOS=darwin` build — it needs osxcross with the macOS SDK extracted from Xcode. Pure-Go parts
(the launcher, port forwarding, lifecycle) cross-compile with nothing extra.

**A Mac is still needed to TEST** — you cannot run the `.app` on Linux to see whether it works.
Build, sign and notarize: Linux. Verify it launches: a Mac, or a macOS CI runner.

## Open questions

- Whether the 75/day notarization limit is per Apple ID, Team ID, or certificate. Asked twice on
  Apple's forums, never answered.
- Whether Time Machine honors `isExcludedFromBackupKey` — Apple's doc never names Time Machine. The
  xattr path is the verified one.
- The exact macOS version that introduced ASIF in `VZDiskImageStorageDeviceAttachment`.
- OrbStack's DNS mechanism for `*.orb.local` — the architecture is well-supported by inference, the
  implementation detail is not confirmed.
