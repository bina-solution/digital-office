# Linux — installer, signing, distribution

Target: one self-extracting `.run` that lands a container runtime offline, loads the image set, and
brings the stack up. Exactly **one sudo**, at install. Rootless was ruled out in
[README.md](README.md) and nothing here revisits it.

## ⚠️ A live blocker this research surfaced, unrelated to packaging

**`traefik:v3.3` cannot route on a Docker 29 host.** Engine 29.0 raised the daemon's minimum API to
**v1.44**; Traefik's Docker provider pins client API 1.24, producing `client version 1.24 is too
old` (traefik#12253). `platform-base/traefik/docker-compose.yml:5` pins `v3.3`. Current is
**v3.7.9**; the fix landed in the v3.6.x line.

**Correction to an earlier draft of this file.** I wrote that the repo works around this by
starting dockerd with `DOCKER_MIN_API_VERSION=1.24`. That is not true on Docker 29, and the real
situation is worse. Docker 29 raised the daemon's *hard* minimum to 1.40 and **caps
`DOCKER_MIN_API_VERSION` at that value**, so the historical workaround is accepted and silently does
nothing. Setting `DOCKER_API_VERSION` on the traefik container does not help either — traefik 3.3
hardcodes the version rather than reading the environment.

**The failure is silent, which is what makes it dangerous.** Traefik starts, reports healthy,
discovers **zero** routers, and every `*.localhost` host 404s — presenting as a hundred unrelated
test failures rather than as one version incompatibility.

So there is no workaround: the stack requires **Docker 28.x**. `bbox baseline` P0 now fails fast
rather than warning, and `CLAUDE.md` documents it. For packaging this is a hard preflight in the
installer, not a warning — and it raises the stakes on the real fix, which is moving to a traefik
whose docker provider negotiates the API version. That change needs validation across every route
and the authentik forward-auth chain, so it stays deliberately unbundled.

## Installing Docker offline

Package sets are five files each, ~85 MB (deb) / ~95 MB (rpm). Docker publishes **dedicated `rocky/`
and `alma/` trees** alongside `rhel/` and `centos/` — use them.

**Do not use `dpkg -i` / `rpm -ivh`.** The documented recipe fails with unmet dependencies on any
host missing `iptables`/`nftables`, and gives no ordering resolution. `docker-ce` now hard-depends
on **both** `iptables` and `nftables`, neither guaranteed on a minimal cloud image; the RPM side
additionally requires **`container-selinux`**, which lives in AppStream/BaseOS rather than Docker's
repo and is the usual airgap failure. It is 59 KB — bundle it from Rocky/Alma, which are freely
redistributable.

Ship a **file-backed local repo** instead, so the package manager resolves ordering itself:

```bash
# Debian/Ubuntu — repo built with dpkg-scanpackages at bundle time
apt-get -o Dir::Etc::SourceList=/tmp/binaos.list -o Dir::Etc::SourceParts=/dev/null \
        install -y --no-install-recommends docker-ce docker-ce-cli containerd.io \
        docker-compose-plugin docker-buildx-plugin
# RHEL family — repo built with createrepo_c
dnf -y install --disablerepo='*' --repofrompath=binaos,/opt/binaos/repo/rpm \
    --setopt=binaos.gpgcheck=0 docker-ce docker-ce-cli containerd.io \
    docker-compose-plugin docker-buildx-plugin
```

`[trusted=yes]` is acceptable here specifically because the repo arrives *inside* the
cosign-verified payload — apt-level GPG would be redundant. Say so in a comment or a reviewer will
rightly flag it.

`--no-install-recommends` matters: `docker-ce`'s Recommends include `git`.

**Fallback:** the static tarball (`docker-<ver>.tgz`, 83 MB, one file, every distro) carries a
complete runtime. Docker says plainly it is not recommended for production — no security updates,
no SELinux wiring, and `iptables` is still a runtime requirement the binary doesn't declare. Use it
only for unrecognised distros; don't ship both eagerly.

## Docker already present — the decision rule

| Condition | Action |
|---|---|
| No binary, no socket | install ours |
| Engine **< 24.0** | **refuse**, print the version. Never auto-upgrade a running daemon — it breaks the customer's unrelated workloads |
| Engine ≥ 24.0, no compose plugin | install **only** `docker-compose-plugin` |
| Engine ≥ 24.0, compose ≥ v2.20 | **use existing**, install nothing |
| rootless | **refuse** with a specific message — traefik needs :80/:443 |
| storage driver differs from ours | **adapt, never flip** |

That last row is not a preference. Engine 29 makes the containerd image store the default for fresh
installs; writing `"features": {"containerd-snapshotter": true}` into an existing
`/etc/docker/daemon.json` makes **every image the customer had vanish from `docker images`**. The
data is still on disk, but the support ticket is real. Read `docker info` `Driver` and adapt.

Also refuse a Podman shim — compose networking, `:z` handling and healthcheck timing all differ from
moby semantics, which this stack assumes.

## The single file, and the disk problem

Three streaming candidates were evaluated. **AppImage is disqualified twice over**: it needs FUSE 2
(renamed/removed on modern distros), and its `--appimage-extract-and-run` fallback materialises the
whole payload in the CWD — the exact failure being avoided. It also cannot install a system runtime.

**Recommended: a shell header with byte-addressed appended segments**, the shape conda's
`constructor` uses — `dd` per segment, each piped straight to its consumer, nothing in `/tmp`.

```
[ shell header ~40 KB   ]
[ SEG1 control  ~2 MB   ]  manifest.json, manifest.sigstore.json, cosign.pub, compose, units
[ SEG2 runtime  ~90 MB  ]  the local deb/rpm repo for this host
[ SEG3 images   ~3 GB   ]  NEVER extracted
```

```bash
dd if="$0" bs=1M iflag=skip_bytes,count_bytes skip=$SEG3_OFF count=$SEG3_LEN status=none \
  | zstd -dc --long=27 | docker load
```

`--long=27` must stay pinned to what `build-bundle.sh` compresses with.

makeself also works — its `--tar` mode streams `dd`→decompress→`tar` — but its default path extracts
to `$TMPROOT`, which is fatal on a tmpfs `/tmp`.

### `docker load` peak disk is worse than assumed, and it depends on the storage driver

**Classic overlay2:** moby's `tarexport/load.go` does `os.MkdirTemp` then untars the **entire**
archive before importing. It honours the daemon's `TMPDIR`, which defaults to `<data-root>/tmp` — so
it lands in `/var/lib/docker/tmp`, not `/tmp`. **Peak ≈ 10 GB scratch + ~9.3 GB final ≈ 20 GB on the
Docker data root**, plus the 3 GB installer.

**containerd image store:** `image_exporter.go` streams into the content store — no full extraction.
But it stores blobs *and* snapshots, and `docker save` emits *uncompressed* layer tars, so naive use
is no better.

**The optimization that follows:** build the bundle as an **OCI archive with compressed layer
blobs** (`skopeo copy --dest-compress-format zstd`) rather than `docker save`. Content store then
holds ~2.5–3 GB compressed + ~9.3 GB snapshots ≈ **12 GB peak instead of ~20 GB**. Architecturally
sound, **not measured** — it belongs next to the size measurement in Milestone 1.

**Preflight `df` on `DockerRootDir`, not `/`**: ≥25 GB classic, ≥15 GB containerd. Refuse with the
actual number rather than dying halfway through a 20-minute load.

All of which is a further argument for the pre-bake approach on macOS/Windows, where this cost
disappears entirely.

## systemd and uninstall

`Type=oneshot` + `RemainAfterExit=yes` is correct — `docker compose up -d` returns immediately, so
systemd supervises the *action* while Docker supervises the containers. **`TimeoutStartSec=0`
matters**: a 40-service first bring-up exceeds the 90 s default and systemd would kill it mid-start.

Uninstall separates three tiers deliberately:

```
/etc/binaos/     CONFIG   survives by default
/opt/binaos/     PROGRAM  removed
named volumes    DATA     survives by default
/var/lib/docker  RUNTIME  removed only if WE installed docker
```

`docker compose down` keeps named volumes; `down --volumes` destroys them. That one flag is the
entire config/data boundary — make it impossible to hit accidentally, and gate `--purge` behind
typing the deployment name. Write an **install receipt** recording whether the engine pre-existed,
so `--remove-docker` is a no-op when it did.

## SELinux — including one that affects this repo today

**The `:z`/`:Z` labels in this repo may currently be doing nothing.** Docker does not enable SELinux
support by default; `"selinux-enabled": true` is required, and relabeling is silently ignored on
hosts without SELinux. So the labels are a no-op on the current VPS and only become live on
RHEL-family with the daemon flag set.

Three rules for when they do become live:
- **`:Z` on a system path bricks the host.** Docker's own words: bind-mounting `/home` or `/usr` with
  `Z` "renders your host machine inoperable". Add a preflight that refuses any `:Z` source outside
  `/opt/binaos` and `/var/lib/binaos`.
- **`:Z` is per-container exclusive** (unique MCS category). Any path shared between two services
  must be `:z`. A `:Z` on a shared path produces intermittent permission denials that look like a
  race. Audit the four occurrences in `apps/browser42/docker-compose.yml`.
- **Relabel cost is per-start.** `:z` walks and `setxattr`s every file on every container start —
  minutes on a large Postgres or Ollama volume. The durable fix is `semanage fcontext` once at
  install, then drop `:z`.

## Signing

Sign a **small manifest**, not the tarball. Signing 3 GB directly means the customer reads 3 GB
before learning anything is wrong, cannot verify incrementally, and cannot verify parts. This is
exactly Zarf's model: every file → `checksums.txt` → aggregate hash in the yaml → cosign over the
yaml.

```bash
cosign sign-blob --key cosign.key --bundle manifest.sigstore.json \
  --tlog-upload=false --use-signing-config=false --yes manifest.json

cosign verify-blob --key cosign.pub --bundle manifest.sigstore.json \
  --insecure-ignore-tlog=true manifest.json
```

Three flags do the offline work and **all three are required**:
- `--tlog-upload=false` — no Rekor upload. Deprecated in 3.0.3 with no clean replacement yet; expect churn.
- `--use-signing-config=false` — **the one people miss.** Defaults to true and makes cosign fetch
  service URLs from the TUF CDN *even with a local key*. Without it, signing is not offline.
- `--insecure-ignore-tlog=true` on verify — `--key` alone does **not** suppress Rekor.

Deprecated, don't use: `--private-infrastructure`, `--offline` (its own help admits it still hits
TUF), `--rekor-url`.

**Rotation is the weak point** — there is no official procedure for rotating a plain key pair. Make
the installer accept a **list** of public keys now, so you are not forced into
`cosign trusted-root create` under pressure.

Verification order, fail closed: signature over manifest → SHA-256 of the whole `.run` → per-segment
hashes as read → post-load `docker image inspect` against the manifest's digests. Do not `tee` into
`docker load`; that verifies after loading, which is not verification.

> Correction to [README.md](README.md): the claim that Replicated's `.airgap` is "a plain unsigned
> tarball" overstates it. `AirgapSpec` does carry a `Signature` field; what could not be found is any
> *verifying* code or documentation. "No documented bundle-signature verification" is the defensible
> phrasing.

## Hosting

**Cloudflare R2, custom domain.** Per 1000 downloads of a 3 GB artifact (3 TB egress) + 50 GB
stored: **R2 ≈ $0.60**, B2+Cloudflare ≈ $0.28, **S3+CloudFront ≈ $171**, S3 direct ≈ $262. The
README's "cents vs ~$255" holds.

Four things decide the design beyond price:
1. **Cloudflare's max cacheable file is 512 MB** (5 GB Enterprise). A 3 GB monolith is uncacheable on
   every non-Enterprise plan — the strongest argument for splitting.
2. **Never serve from `r2.dev`** — rate-limited, development only. Custom domain always.
3. **VPS behind free Cloudflare is a ToS problem** for 3 TB/month of installers. R2 is a paid product
   and isn't subject to it.
4. B2+Cloudflare saves $0.32/month for a two-vendor dependency with no documented cap. Take R2.

**Split into 12 × 256 MiB parts** + the signed manifest: under the cache ceiling so every part is
edge-cacheable, worst-case rework ≤256 MiB. Ship the monolith too if you like — `cat part-*`
reproduces it.

**`curl -C -` is not safe unattended.** curl never sends `If-Range`; it stats the local file, sends a
bare `Range: bytes=<size>-`, and if the artifact changed it splices new bytes onto an old prefix and
**exits 0**. Use `aria2c -c -x8 -s8 --checksum=sha-256=<hex>` — its control file records which ranges
actually landed. Note `-x` defaults to 1.

## Updates

**Don't build a binary delta for v1.** At 1000 downloads/month the full artifact costs $0.60 on R2;
a delta system saves $0.55 and buys a build pipeline, baseline tracking, and a new class of
"my update is corrupt" tickets. Split parts + aria2 already solve resumability.

Binary deltas are also close to worst-case on this artifact: zstd encodes as back-references with
entropy state dependent on everything preceding, so one changed byte early decorrelates the entire
downstream stream. `zstd --patch-from` needs `windowSize > srcSize` — `--long=31` for a 3 GB
reference, i.e. **~2 GiB resident during patch apply on a customer VPS**.

**When it is time, the answer is an OCI blob set-difference, and it is nearly free.** The image-layout
spec makes identical content one content-addressed path, so month-over-month unchanged base and
runtime layers are byte-identical by digest — ship only the blobs not in the baseline.
`regctl image copy` documents exactly this ("only pulls layers that do not exist at the target").

**Measure before deciding**: produce two consecutive months' OCI layouts and diff the
`blobs/sha256/` name+size sets. And note the precondition — if base images aren't pinned and every
digest churns monthly, no delta scheme saves anything. Layer-level delta is a build-discipline
problem before it is a transport problem.

Zarf's `--differential` will not help: it works at **image** granularity, not layer, so a rebuilt tag
re-includes the whole image even when 95% of its layers are identical.
