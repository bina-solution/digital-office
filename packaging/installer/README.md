# dgo-install — the tiny downloadable bootstrapper (core-007 / DGO-483)

The small file the DGO website hands you when you click **Download**: one Windows `.exe`, one macOS
binary inside a `.dmg`, or one Linux file / one-line download. It is deliberately minimal — it is
**not** DGO core. Its whole job:

1. **Hello + accept terms.** (`--accept-terms`, or `--terms` to read them first.)
2. **Fetch a signed manifest** for this OS/arch and **verify its Ed25519 signature** against a release
   public key baked into the binary at build time.
3. **Download DGO core**, verify its SHA-256 against the manifest, forward-only (never downgrade).
4. **Launch DGO core** — which is the larger binary that provisions the container engine and runs the
   install wizard (the app picker). That part is container-land; this stub is not.

So: `website → download → run → verify → DGO core → wizard`, with **no `git clone`** — exactly the
flow the owner asked for.

## Why not `curl | bash` / an unsigned download

The stub's **own** signature (Authenticode / notarization) proves who shipped *the stub*; it says
nothing about the bytes it later downloads. So the payload is trusted only via a manifest the release
key signed, and the **public** half of that key is compiled in. The security rules, all enforced in
`main.go`:

- **Fail-closed.** No baked-in key or manifest URL ⇒ the stub refuses to do anything. This template
  build is inert on purpose.
- **Signed manifest.** Ed25519 over `version\npayload_url\nsha256` (stable bytes, not JSON ordering).
- **Same host, HTTPS only.** The payload must come from the same host as the manifest, over TLS.
- **SHA-256 pinned by the manifest**, checked after download; mismatch ⇒ delete + refuse.
- **Forward-only.** Won't install a version older than the one already present (`VERSION` file).

## Build

Template (compiles, inert — what CI builds to prove it still compiles):

```
go vet ./... && go build .
```

Release — inject the key, the manifest URL and the version, and strip:

```
go build -trimpath -ldflags "-s -w \
  -X main.pubKeyB64=<ed25519 public key, std base64> \
  -X main.manifestURL=https://digital-office.co.il/dl/<os>/<arch>/manifest.json \
  -X main.version=<stub version>" -o dgo-install .
```

Cross-compile for every OS from one host (stdlib-only, so no C toolchain):

```
for t in windows/amd64 windows/arm64 darwin/amd64 darwin/arm64 linux/amd64 linux/arm64; do
  GOOS=${t%/*} GOARCH=${t#*/} go build -o dist/dgo-install-${t%/*}-${t#*/} .
done
```

## Packaging + signing per OS (the "world-leading-software" flow)

- **Windows:** sign the `.exe` with the org's code-signing cert and a trusted timestamp. Note (2024+):
  EV no longer grants instant SmartScreen trust — budget a reputation warm-up per release; never
  suppress signature verification.
- **macOS:** Developer ID signature + Hardened Runtime + a secure timestamp; `notarytool --wait`;
  **staple the app, then build the `.dmg`, then notarize + staple the `.dmg` too**; test first launch
  offline.
- **Linux:** publish the binary + a signed manifest + its checksum, the checksum/signature served
  from a **separate host**; a one-line installer downloads to a file, verifies, then runs — never
  pipes into a shell.
- **Self-update:** forward-only, verified against the same pinned key (the model this stub already uses).

## The release lane (2026-10-10)

`packaging/build-binaries.sh` builds this stub, `dgo` and `forward-auth` for all six targets with one
command — vet + tests first, `CGO_ENABLED=0 -trimpath -buildvcs=false`, a double build proving the
bytes are reproducible, `SHA256SUMS`, and the download tree the website serves:
`dist/dl/<os>/<arch>/{dgo-core[.exe], manifest.json}`. `.github/workflows/release-binaries.yml` runs
exactly that on a `v*` tag (attaching the binaries to the GitHub release) or by hand (artifact only).

Signing is `packaging/relsign` (stdlib Go, `crypto/ed25519` — the same call this stub verifies with),
over exactly `signedMessage()`'s bytes; `TestRelsignSignatureVerifiesInGo` here signs with relsign and
verifies with the stub, so the two copies of that line cannot drift. With `--sign-key` the script bakes
the public key and each target's manifest URL into every stub and verifies every manifest with the
public half before it says done; without a key the stubs are this inert template and the manifests are
`manifest.unsigned.json`, which the stub refuses. In CI the key is the repository secret
`DGO_RELEASE_KEY` (PEM), held for one job and deleted.

```
bash packaging/build-binaries.sh --keygen release-key.pem   # once, the owner's, kept offline
bash packaging/build-binaries.sh --pubkey release-key.pem   # the base64 the stub bakes in
bash packaging/build-binaries.sh 1.4.0 --sign-key release-key.pem --check-reproducible
```

## Status

The stub compiles and cross-compiles for all six targets and is fail-closed; the release lane above
produces the signed per-OS tree. What remains (owner / web): generating the release key and storing it
as `DGO_RELEASE_KEY`, serving `dist/dl/` from the website at `https://digital-office.co.il/dl/`, and
the per-OS code signing / notarization of the stub itself. DGO core is `dgo` (core-005, step 1 — the
CLI; the compiler and the planes follow). Tracked as DGO-483 (parent req-461 / DGO-461).
