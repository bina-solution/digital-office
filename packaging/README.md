# packaging — shipping this platform as one downloadable file

The goal, stated as asked: **one encrypted file, runs on Windows/macOS/Linux, contains the Docker
engine and every image, one click brings the whole system up, no external dependencies and no
additional downloads.**

Three parts of that are not physically achievable. They are named here first, because every plan
below is shaped by them and a roadmap that quietly drops them is worse than one that says so.

## What cannot be delivered, and why

**"No admin / no root" — impossible on Linux and Windows. Achievable only on macOS.**

- Linux has four independent blockers, any one of which is fatal. Ubuntu 23.10+ sets
  `kernel.apparmor_restrict_unprivileged_userns=1`, which denies `userns_create` to any binary
  without a permitting AppArmor profile — including an unconfined one in `$HOME`. Rootless
  Docker/Podman need ≥65,536 subordinate IDs in `/etc/subuid` plus the setuid `newuidmap` /
  `newgidmap` helpers. Traefik binds :80 and :443, which rootless cannot do without
  `net.ipv4.ip_unprivileged_port_start=80`. Every one of those fixes is itself root.
- Windows needs the `VirtualMachinePlatform` optional feature, which is off by default on 11
  (including 24H2/25H2) and is enabled by an elevated `DISM` call plus a reboot. The Store MSIX
  build of WSL does not avoid this — it still shells out to `wsl --install`.
- macOS is the exception. `com.apple.security.virtualization` is a plain Boolean entitlement, not
  a managed capability: no provisioning profile, no Apple approval. Apple DTS has confirmed VZ
  needs no admin at runtime. NAT networking needs no entitlement either.

  So: **one clearly-labelled privileged step, once, at install** — and on Windows, skipped
  entirely when WSL2 is already present. That is the honest version of the requirement.

**"Encrypted" — achievable as a filename, not as a security property.**

If the artifact decrypts unattended on the customer's machine, the key ships with it. That is not
an implementation weakness, it is the definition of the problem: ordinary cryptography protects
content from outsiders while trusting the user; this asks to protect content *from* the user, who
has full access to the decrypting agent. White-box crypto is the "hide it harder" answer and has
an unbroken losing record — all 94 entrants in the WhibOx 2017 contest were broken, and
Differential Computation Analysis extracts keys by binary instrumentation without reverse
engineering the obfuscation at all. And once loaded, `docker history` and `docker save` expose
every layer regardless.

Native OCI encryption (`ocicrypt`) does not close it either: it encrypts layer blobs only, so the
manifest, image config, `Env` and `Cmd` stay cleartext and the topology leaks anyway. It also
defeats layer dedup, which is where the size win lives.

**Take signing instead.** Tamper-evidence is fully achievable and is what the entire airgap
industry actually ships: Authenticode on the Windows exe, notarization on the macOS component, a
detached cosign key-pair signature plus published SHA-256. Nobody in this category encrypts the
artifact — Replicated's `.airgap` has a `Signature` field but no *documented* bundle-signature
verification, and Zarf and Ubuntu Core sign rather than encrypt.

Protecting IP from the machine owner needs a different mechanism entirely (hardware dongle,
node-locked activation, TPM sealing) or a contract. Confidential computing does not help: it
assumes the adversary cannot touch the hardware, which is false on-prem, and SEV-SNP is broken by
BadRAM with under $10 of gear.

**"No external dependencies" — already false before packaging.**

`.env.ex` carries `OPENAI_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_VISION_API_KEY`, `GOOGLE_OAUTH_*`,
`ANTHROPIC_API_KEY`, `FIRECRAWL_API_KEY`, `JINA_API_KEY`, `TELEGRAM_BOT_TOKEN` and
`WHSP2_EVOLUTION_API_KEY`, and Traefik's ACME resolver needs Let's Encrypt. The *bundle* can be
self-contained. The *product* cannot. Which one is being promised is a positioning decision, not
an engineering one.

## Size — the finding that changes the economics

The naive sum of `docker images` SIZE is ~18.7 GB, and that number is what makes this look
impractical. It is the wrong number twice over.

Layers inside a `docker save` archive are uncompressed tar, and `docker save` deduplicates layers
by DiffID across every image in one archive. Measured on this stack: the live image set
deduplicates to **≈9.3 GB on disk**, and zstd measured on `postgres:17` gives **3.17× at -3** and
**4.11× at -19** (460.8 MB raw → 112.1 MB).

> ### MEASURED, 2026-07-28: **2.20 GB**
>
> 29 images, deduplicated image store **11.53 GB**, `zstd -19 --long=27`, 44m36s wall on the WSL
> build host. The extrapolation predicted 2.4–3.2 GB; the real figure came in slightly better.

A 2.2 GB download is an ordinary product download, so the size objection to shipping this as one
file is answered. Two caveats worth carrying:

* The **first** run of this measurement reported a convincing 1.53 GB and was wrong — it covered 17
  of 29 images, because 12 first-party services declare only `build:` and no `image:`, so a scan of
  the compiled YAML could not see them. `build-bundle.sh` now uses `compose config --images` and
  refuses to proceed unless every service maps to an image. A plausible number from an incomplete
  set is worse than no number.
* `docker-repack` (cross-layer file dedup) plausibly reaches ~2 GB and is still untried.

## Architecture — the call

**Architecture A: signed per-OS installer + embedded runtime + offline OCI bundle.**

| | |
|---|---|
| Artifacts | `BinaOS-Setup.exe` (Authenticode) · `BinaOS.dmg` (notarized) · `BinaOS.run` (makeself, signed) |
| Runtime, Windows | embedded rootfs → `wsl --import` (non-elevated, streams from stdin) — [windows.md](windows.md) |
| Runtime, macOS | signed VZ `.app` (EFI boot, raw disk, NAT), payload a DMG **sibling** — [macos.md](macos.md) |
| Runtime, Linux | bundled `docker-ce`/`containerd.io` as a **local repo** (not `dpkg -i`) — [linux.md](linux.md) |
| Images | **pre-baked into the guest disk image** on macOS/Windows; `docker load` on Linux |
| Admin | macOS none (Tier 0) · Windows one UAC + reboot **only if VMP is off** · Linux one sudo |
| Size | ~2.5–3.5 GB |
| First run | **~30 s boot**, ~15 GB peak disk (was 8–25 min / ~34 GB — see below) |

### The correction that mattered most: pre-bake, don't `docker load`

The original design shipped a `docker save` tarball and imported it on the customer's machine. The
macOS research replaced that with building the guest disk image in CI with every pinned image
*already pulled into its docker data root* — what `kind` does for node images.

| | `docker load` at first run | pre-baked |
|---|---|---|
| First run | 8–25 min, dominated by the import | **~30 s boot** |
| Peak disk | ~34 GB (bundle + unpacked layers) | **~15 GB** |

It also deletes a class of failure rather than mitigating it: no partially-imported state, and no
"extract 3 GB to `%TEMP%` on a nearly-full C:" — which is not a hypothetical, it is what happened to
this repo's own dev machine. Applies to macOS and Windows (bake into the WSL rootfs tarball too).
Not to Linux, where we install into the host's own Docker and `docker load` stays correct.

`packaging/build-bundle.sh` keeps its job either way: it is how the image set gets into the guest
build in the first place, and it is still the right artifact for the Linux path.

Rejected: **B, a bootable appliance image** (the only design with genuinely no runtime and no admin
question, because it *is* the OS) — it takes over a machine and is not a double-click on the laptop
the customer already has. If customers get dedicated hardware, B is strictly better than A at
roughly the same effort, so this is the one decision worth revisiting. **C, hosted per-tenant**, is
weeks rather than months and eliminates every problem above, but it is not packaging.

## The next chapter: BinaOS native

The plan has been extended past "ship the stack as a file" to **become our own Docker Desktop**:
one executable per OS with dockerd embedded, layers 1–2 as native processes, and a layer 3 that
accepts both docker-compose apps and native apps. Full study and phase plan:
**[native-plan.md](native-plan.md)**. Key decisions made there: one Linux userland everywhere
(host shell is thin, guest does the work — the build matrix stays linux/amd64+arm64); supabase
decomposes (vanilla postgres to layer 1, rest+storage to a gallery app, kong likely dropped);
authentik replaced by Authelia (recommended) — the one genuinely hard item; and an undeclared
`drive → object-storage` dependency that must be declared regardless of everything else.

## Roadmap

Sequenced Windows-first: `wsl --import` is the cheapest runtime path, and Windows is the only one
of the three with no privileged-port problem.

**Milestone 0 — make the bundle buildable at all.** *(in progress)*
- [x] Cut the default install from 29 distinct images to 17 pulled + 10 built. Every GB removed
      here is a GB off the download, so image minimisation is a packaging task, not a cleanup task.
- [x] `scripts/refactor/image-pin-lint.py` (gate G15) — no floating tags. A bundle built from
      `glitchtip/glitchtip` (untagged) is not reproducible and its signature attests to nothing.
      Fixed three: glitchtip → 6.2.2, ollama → 0.32.5, redisinsight → 3.8.0.
- [ ] **`traefik:v3.3` cannot route on a Docker 29 host.** Engine 29 raised the daemon API floor to
      v1.44; Traefik's Docker provider pins 1.24. `platform-base/traefik/docker-compose.yml:5` is on
      v3.3. **There is no workaround** — Docker 29 caps `DOCKER_MIN_API_VERSION` at 1.40, so the
      historical flag is accepted and does nothing, and traefik 3.3 hardcodes its API version rather
      than reading `DOCKER_API_VERSION`. The failure is SILENT: traefik starts, reports healthy,
      finds zero routers, and every `*.localhost` 404s. The stack requires **Docker 28.x**; `bbox
      baseline` P0 now fails fast. For packaging this is a hard installer preflight, and the real
      fix (a traefik whose provider negotiates the API version) needs validation across every route
      and the forward-auth chain.
- [ ] ~~Digest pinning (`--digests`) for the shipped compose files~~ — **withdrawn, it would break
      airgap.** `docker save`/`load` transfers RepoTags but **not** RepoDigests (moby#43570), so
      `image: postgres@sha256:…` finds no local match after a `docker load` and reaches for a
      registry — the exact failure the bundle prevents. The correct split: pin digests in the
      *build*, ship *tags* in the customer's compose, and record digests in the *signed manifest*.
      `build-bundle.sh` now writes the digest of every image alongside its tag, since the manifest
      became the only place a digest can survive.

**Milestone 1 — replace the extrapolation with a measurement.**
- [x] `packaging/build-bundle.sh` — resolves images from the compiled stack, refuses to start
      under 6 GiB free, and streams `docker save` straight into zstd so the raw ~10 GB tar never
      touches disk. That last point is not hypothetical: doing it the obvious way is what filled
      this repo's own dev machine to zero bytes free and wedged its WSL VM.
- [x] `.github/workflows/release-bundle.yml` — manual-dispatch lane that runs it on a runner
      rather than a laptop, and puts the number in the job summary.
- [x] **Ran it: 2.20 GB** (29 images, 11.53 GB deduplicated store, zstd -19, 44m36s). The
      extrapolation is replaced by a measurement, and it held.
- [x] Coverage guard — the first run silently measured 17 of 29 images and looked fine. The build
      now refuses unless every compose service maps to an image in the list.
- [ ] Trial `docker-repack` on the two biggest: `supabase/postgres` (1.87 GB) and the n8n image.

**Milestone 2 — arm64.** Do this now; it is a `buildx` change today and a blocker later.

- [x] Survey the third-party set — `packaging/check-arch.py`, reads the registries directly, no
      Docker daemon needed. Result: **16/16 publish `linux/arm64`**. Zero third-party blockers,
      including all four that were open questions (supabase/postgres, supabase/studio,
      supabase/storage-api, authentik). This is better than assumed and it means macOS is
      reachable without replacing or forking a single upstream image.
- [x] `packaging/build-images.sh` — multi-arch buildx for the first-party set, deliberately off
      the `bbox run` path (a developer should not wait twice as long for an arm64 image they will
      never execute). Collapses the n8n triple: three services sharing one context, one Dockerfile
      and one set of build args, differing only by `command`, so 16 invocations become 14.
- [ ] **Run it on a runner with binfmt** and fix whatever the arm64 builds surface. This is now
      the *only* thing standing between the stack and an arm64 bundle.

Why it is a precondition rather than a nicety: on Apple Silicon the alternatives are
Rosetta-for-Linux, which is not preinstalled and whose installer downloads from Apple (breaking
the offline promise outright), or `qemu-user-static` binfmt, which works offline at roughly 10×
slower — across forty services that is not "slow", it is non-functional.

**Milestone 3 — Windows installer.** Embedded rootfs → `wsl --import` → dockerd → `docker load`
→ `bbox run`. Probe for VMP first and skip the UAC prompt when WSL2 already exists.

**Milestone 4 — signing.** cosign key-pair (not keyless: no Fulcio/Rekor dependency, and cosign 3
made `--bundle` required precisely to enable offline verification) + Authenticode via Azure
Trusted Signing. Note EV certificates no longer bypass SmartScreen, so the $300–900/yr option
buys nothing over $9.99/mo.

**Milestone 5 — Linux. BUILT AND VERIFIED, 2026-07-28.**

```
dist/BinaOS-2026.07.28-linux-amd64.run   2.48 GB   signed
     manifest.json                       6.5 KB    29 images, all with digests
     manifest.sigstore.json              383 B     cosign, offline-verifiable
     sha256 41f0e6d7d051b757a154e7d8847370e71da6e9990c1c491f56d886e969ac9158
```

`packaging/verify-artifact.sh` passes 8/8 against it: cosign verifies the manifest offline, size and
sha256 match, all three segments re-read correctly at their recorded offsets through the installer's
own `dd` invocation, and the images segment is a genuinely loadable docker archive rather than
merely well-formed zstd.

Built at zstd **-12** (2.47 GB) rather than -19 (2.20 GB) — a deliberate trade, see below.

**Two honest limits on this specific artifact:**
* The runtime segment is **202 bytes** — a placeholder. There is no bundled `docker-ce` repo yet, so
  this build *requires Docker already present* on the target. `packaging/linux/fetch-runtime.sh`
  is the missing piece.
* It is signed with a **throwaway key** generated on the build host. A real release needs a key
  whose public half is published and pinned.

**What it cost to get here, because the pattern is the lesson.** Five attempts failed, and every one
looked like success from the outside: an exit-0 build that left a zero-byte artifact (the status
came from a dropped `wsl.exe` connection, not from zstd); a `nohup … &` that never detached; a run
killed 26 minutes in by a `.wslconfig` edit; a retry blocked by the zero-byte corpse because `zstd`
refuses to overwrite; and a host OOM from building beside 37 running containers. `Wsl/Service/
0x8007274c` turned out to be this repo's own documented symptom of host memory exhaustion, not a
build fault — `wsl --shutdown` took the host from 0.8 GB to 8.7 GB free, exactly as `.wslconfig`
predicted.

The fixes that stuck: `setsid --fork` so the build outlives the connection, `zstd -f` so a rebuild
is idempotent, `BINAOS_QUIESCE=1` so it does not compete with the stack, and — most importantly —
verifying the artifact rather than the exit code.

**This laptop is the wrong build host.** 15.7 GB shared between Windows and a VM that needs ~10 GB
to compress an 11.53 GB image store is marginal, and it is why `-12` was used. Run releases on the
VPS or through `release-bundle.yml`.

**Milestone 6 — macOS.** Full spec: [macos.md](macos.md). A DMG has
no documented size cap (the Zip64 limit is a *ZIP* limit, not a submission limit), a standard $99/yr
membership is sufficient, and the entitlement is a plain Boolean. The expensive parts are the Swift
VZ host app, the Alpine guest-image pipeline, and the fact that Intel and Apple Silicon need
**separate disk images** — no cross-arch emulation — which roughly doubles the artifact matrix.

**Legal, and not deferrable: the GPL written offer.** Shipping a Linux kernel means conveying
GPL-2.0 code. GPLv2 §3(c) — passing along someone else's offer — is allowed only for
*noncommercial* distribution, so a commercial installer needs accompanying machine-readable source
or a **written offer valid three years**. Automate a pinned source-tarball snapshot in the same CI
job that builds the guest image; retrofitting this is painful. Our own closed-source host app is
unaffected — it talks to GPL programs at arm's length over vsock, exactly as Lima and podman do.

Choosing **Alpine over Ubuntu** for the guest is a licensing decision before it is a size one:
Canonical's IP policy permits redistributing *unmodified* images, but installing Docker makes it
modified, which requires either Canonical's approval or removing the trademarks and recompiling.
musl also removes the LGPL relinking obligation glibc would impose.

## Constraints worth writing down

- **zstd `--long`**: the decompressor defaults to a 128 MiB window. Compressing with windowLog >27
  makes decompression *fail* unless the extractor passes `--long=`. Use `--long=27`.
- **Peak disk on first run** is bundle + unpacked layers ≈ 34 GB. SFX archives conventionally
  extract to `%TEMP%` on C:, which alone can sink the install — this repo's own host is proof.
- **Hosting**: Cloudflare R2 or B2+Cloudflare have $0 egress. 1,000 downloads of a 3 GB artifact is
  cents on R2 versus roughly $255 on CloudFront. Resume must be mandatory.
- **Do not ship a no-hypervisor fallback.** QEMU TCG measures ~8× slower for x86-64 guests and up
  to 18.7× versus native. Forty services under that is not "slow", it is non-functional.
