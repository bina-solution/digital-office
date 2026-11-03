# dgo-install — the tiny downloadable bootstrapper (core-007 / DGO-483, step 1 of the plan: DGO-595)

The small file the DGO website hands you when you click **Download**: one Windows `.exe`, one macOS
binary inside a `.dmg`, or one Linux file / one-line download. It is deliberately minimal — it is
**not** DGO core. Its whole job:

1. **Hello + accept terms.** (`--accept-terms`, or `--terms` to read them first.)
2. **Fetch `keys.json` and the signed manifest** for this OS/arch and **verify the chain** that starts at
   the release roots whose *public* halves are in the binary — the committed `roots.txt`, embedded.
3. **Download DGO core**, check its size and SHA-256 against the manifest, forward-only (never downgrade).
4. **Launch DGO core** — the larger binary that provisions the container engine and runs the install
   wizard (the app picker). That part is container-land; this stub is not.

So: `website → download → run → verify → DGO core → wizard`, with **no `git clone`** — exactly the
flow the owner asked for.

## Why not `curl | bash` / an unsigned download

The stub's **own** signature (Authenticode / notarization) proves who shipped *the stub*; it says
nothing about the bytes it later downloads. So those bytes are trusted only through a chain — TUF's
rules, a [DSSE](https://github.com/secure-systems-lab/dsse) envelope, Ed25519 — whose code is
[`packaging/trust`](../trust), the office's one signed-document layer: the stub verifies with it, relsign
signs in its encoding, and `dgo index` verifies the app store's index with the same rules:

```
root keys      offline, two or more; their PUBLIC halves are roots.txt, embedded in every stub
 └ keys.json   type dgo-keys, for one download `site`: the ONLINE signing keys, each valid in a window
    │          [not_before, not_after) and only for the document `types` it names; version, expires
    └ <os>/<arch>/manifest.json   type dgo-core-manifest, for the same `site`: version, expires,
       │                          min_bootstrapper, target, payload_url (under the site), sha256, size
       └ dgo-core[.exe]           exactly `size` bytes that hash to `sha256`
```

Two tiers because the key a release job holds (`DGO_RELEASE_KEY`) is online: it must be replaceable
without a new stub, and a new `keys.json` replaces it. The roots never leave the owner's safe, and there
are several so that one can retire while the stubs in the world still trust another. Every rule below is
enforced in the stub and has a test that fails without it:

- **Fail-closed.** No root in `roots.txt`, or no download site built in ⇒ a *development build*, which
  says so on its first screen and installs nothing.
- **The roots are pinned.** `roots.txt` is committed and embedded (`go:embed`, into a `[]byte`: the
  linker's `-X` sets only strings, so `-X main.rootKeys=…` is a build error): no build flag, variable or
  file outside the repository can put other roots in a stub. The release lane signs only when
  `roots.txt` holds exactly HEAD's bytes, read raw (`git cat-file`: no filter, no `git replace`, no
  index flag or staged edit can stand in), and HEAD is in a branch of origin — not a commit made only
  on the build machine. Those gates stop drift and unreviewed local commits; a hostile build machine
  can forge any local state, a remote-tracking ref included, and the defence there is the reproducible
  build: anyone can rebuild the tag and compare `SHA256SUMS`. It names none until the owner's key
  ceremony.
- **The whole document is signed**, payload type included (DSSE's PAE: `DSSEv1 <len> <type> <len> <body>`),
  so a field added later is signed the day it is added. Signatures are strict base64 of exactly 64 bytes.
- **Every signed document names its type, and a signature over one type never passes for another.**
  The office signs three kinds — key lists, core manifests, and the app store's index — and before this
  stub a store index, signed in the old manifest's shape under the same key, *was* accepted as a core
  manifest and installed as `dgo-core`. Now the envelope's `payloadType` must be the one the stub
  expects where it reads it, the type is inside the signed bytes (relabelling breaks the signature), and
  the signing key must be listed for that type: a key `keys.json` scopes to `dgo-app-index` cannot sign
  a core manifest even when it labels it correctly.
- **Both documents name their site, and the payload lives under it.** The same roots and the same
  release key serve more than one site (a stable `/dl`, a `/beta`, the store): `keys.json`'s and the
  manifest's signed `site` must be the one built in, and `payload_url` must be an https file under it
  (a clean path — `/dl/../beta/…` is not). A mirror or a redirect cannot carry `/beta` into `/dl`.
- **keys.json** must be signed by a root, unexpired, and its `version` may not fall below the list this
  computer accepted — nor below the list **this stub was built with** (the release lane bakes in its
  version and sha256), so a key revoked before the stub was built cannot install anywhere. At an equal
  version it must be *that very list*: a list changed without a new version is refused, so a revocation
  that forgot its "+ 1" fails loudly instead of leaving the old list standing beside it. Roots sign key
  lists, never manifests (and `relsign keys` refuses to list the root that signs the list, or to trust a
  listed key with `dgo-keys`). A key's window must open before it closes — an empty or inverted one
  refuses the whole list. A list may state `core_floor`, the oldest DGO core the site allows: no
  computer installs anything older — a fresh one included, which remembers nothing.
- **The manifest** must be signed by a key `keys.json` lists for `dgo-core-manifest`, inside that key's
  window; unexpired; for this computer's `target`; not older than the last manifest this computer
  accepted (a replayed old manifest is refused) nor than `core_floor`; and its `min_bootstrapper` must
  not be newer than this stub (else: "download the current installer").
- **Revocation undoes what the revoked key did, and opens nothing** (TUF §5.3.11). The memory of the
  newest manifest records the key that signed it and the keys listed beside it then, and so does the
  install record. While `keys.json` lists that key, its version binds every key. Once it does not:
  - a list that states `core_floor` puts the root's floor in its place, for every key, on this computer
    for good — so a leaked key's `999999999.0.0` gives way to the next real release, whichever listed
    key signs it, and nothing older than the floor comes back (`relsign keys` refuses to drop a key
    without stating it);
  - a list that states none (one made by hand) leaves the revoked key's version binding the keys that
    stood beside it — they may have signed older releases, which a replay would bring back. Any other
    key is free of it: a key **never listed before**, as the release after a leak is signed with, but
    also an old key listed again — the case only relsign's rule keeps out.

  The memory is kept per site **and per set of roots**, so a new generation of stubs (new roots, after
  a root leaked) inherits nothing from the old roots' lists — not a key list numbered `MaxInt64`, and
  not the core installed under it.
- **Size and SHA-256 pinned by the manifest**, checked after download; a mismatch ⇒ the bytes are deleted
  and nothing is replaced: the download lands in a file of its own (unique per run, synced to disk)
  beside the old core and is renamed over it only when it verifies — on Windows a running core steps
  aside to `dgo-core.exe.old` first, since Windows will not overwrite a running `.exe`.
- **Versions are release versions — dotted numbers (`1.4.0`).** A pre-release suffix would make
  `1.5.0-rc.2` sort above `1.5.0`, and an old signed pre-release could roll a release back, so the stub
  accepts none and `relsign` signs none (an unsigned draft may still carry a development label).
- **Forward-only.** `VERSION` beside the core is its record: the installed version on its first line (as
  it always was), then the sha256 of the bytes installed and who vouched for them (`signer k2,k1`: the
  key that signed, then the keys beside it). A core counts as installed only while its bytes still match
  and its key binds the offered release's key (as above): one a power cut left half-written is installed
  again, and another build signed under the same version cannot swap it back and forth. Accepted
  versions are remembered in `<user config dir>/dgo/install-state` (`%AppData%` on Windows,
  `~/Library/Application Support` on macOS, `$XDG_CONFIG_HOME` or `~/.config` on Linux), only ever raised
  while their keys are listed (or while the root states them: `core_floor`), and the key list's version
  the moment it verifies. Deleting that file only weakens rollback protection — the record still holds
  the installed core — and never blocks an install.
- **Payload paths are plain.** No backslash in `payload_url`'s path: some servers (IIS) read `%5C` as `/`,
  and `/dl/..\beta` would climb out of the site.

Every check is taken against one clock, fixed when the run begins; a refusal names the computer's own
clock, because a wrong clock is the usual reason a good manifest looks expired. A clock up to 10 minutes
slow still takes a key from the start of its window, and `relsign keys` opens a window a day before the
list is signed, so the routine re-sign never refuses a slow clock (or a dual-boot clock hours off) for a
key that was valid all along. An end or an expiry gets no grace: a frozen mirror would gain it too.

The envelope and the two documents (what `relsign` writes, one JSON line each):

```json
{"payloadType":"dgo-core-manifest","payload":"<base64 of the document>",
 "signatures":[{"keyid":"<first 8 bytes of sha256(public key), hex>","sig":"<base64 Ed25519 over the PAE>"}]}

{"site":"https://digital-office.co.il/dl","version":3,"expires":"2026-12-14T00:00:00Z","core_floor":"1.4.0",
 "keys":[{"public_key":"<base64>","types":["dgo-core-manifest"],
          "not_before":"2026-10-14T00:00:00Z","not_after":"2026-12-14T00:00:00Z"}]}

{"site":"https://digital-office.co.il/dl","version":"1.4.0","expires":"2027-01-13T00:00:00Z",
 "min_bootstrapper":"0.0.0","target":"linux/amd64",
 "payload_url":"https://digital-office.co.il/dl/linux/amd64/dgo-core","sha256":"<hex>","size":2453656}
```

The document types — one vocabulary for every DGO signer and verifier, defined once in `packaging/trust`:

| `payloadType` | document | signed by | verified by |
|---|---|---|---|
| `dgo-keys` | `keys.json` | a root | this stub, and `dgo index` for the store's own site's list |
| `dgo-core-manifest` | `<os>/<arch>/manifest.json` | a key listed with that type | this stub |
| `dgo-app-index` | the app store's `index.sig.json`: `{site, version, sha256, size}` of its `index.json` | a key listed with that type (`relsign index`, `dgo index build --key`) | `dgo index verify\|install` — this stub refuses it |

What a refusal cannot fix: a stub trusts its roots for life. A lost root is retired by signing with the
other; a *leaked* root means new stubs (a new generation with new roots in `roots.txt`) — which is why
the roots stay offline, and why a stub that rarely changes is cheap to replace when it must.

## Size — at most 4 MiB per target, a gate

`packaging/build-binaries.sh` fails the build when any `dgo-install` exceeds 4,194,304 bytes. Measured
(go1.22.3, `CGO_ENABLED=0 -trimpath -ldflags "-s -w"`, a release build; a development build is at most
512 bytes smaller):

| target | before (net/http) | after | |
|---|---:|---:|---:|
| windows/amd64 | 5,327,872 | 4,093,440 | −1,234,432 |
| windows/arm64 | 4,981,760 | 3,789,312 | −1,192,448 |
| darwin/amd64 | 5,287,104 | 4,048,656 | −1,238,448 |
| darwin/arm64 | 5,064,226 | 3,828,466 | −1,235,760 |
| linux/amd64 | 5,169,304 | 3,936,408 | −1,232,896 |
| linux/arm64 | 4,980,888 | 3,801,240 | −1,179,648 |

Three standard packages are deliberately absent: `net/http` (`https.go` is the client), `encoding/json`
(`packaging/trust` reads the documents with its own `jsonread.go`, 250 KB cheaper, proven against
`encoding/json` as its oracle) and `os/exec`
(`os.StartProcess`, 143 KB cheaper). The floor is TLS itself: `crypto/tls` + `crypto/x509` + `net` +
the runtime weigh 3.78 MB on windows/amd64 before a line of the stub.

The client (`https.go`): GET over HTTP/1.1, TLS 1.2+ against the **system's** roots, one total deadline
per fetch, redirects followed at most five times and only to `https://`, bodies by `Content-Length`, by
chunked coding or until close — never past the caller's limit (64 KiB for a document, the manifest's
`size` for the payload). `HTTPS_PROXY` (an `http://` proxy, through CONNECT) and `NO_PROXY` are honoured
as `net/http` honoured them, so an office behind a proxy still installs.

## Build

Development (compiles, inert — what `go build .` and CI's template build produce):

```
go vet ./... && go test ./... && go build .
```

Release — the download site, the key list's floor and the version, and strip; the roots are
`roots.txt` (`build-binaries.sh` does exactly this):

```
go build -trimpath -ldflags "-s -w \
  -X main.siteURL=https://digital-office.co.il/dl \
  -X main.keysFloor=<what `relsign floor keys.json` prints: version:sha256> \
  -X main.version=<stub version>" -o dgo-install .
```

The stub fetches `<site>/keys.json` and `<site>/<GOOS>/<GOARCH>/manifest.json`. Cross-compile for every OS
from one host (stdlib-only, so no C toolchain):

```
for t in windows/amd64 windows/arm64 darwin/amd64 darwin/arm64 linux/amd64 linux/arm64; do
  GOOS=${t%/*} GOARCH=${t#*/} go build -o dist/dgo-install-${t%/*}-${t#*/} .
done
```

## The keys — the owner's ceremony (D1), offline

Nothing private is ever in this repository, and no real key exists yet: the roots are the owner's.
Run the ceremony in a directory OUTSIDE the checkout — paths are taken from where you run it, and the
script refuses to write a key inside the repository or sign with one from there, where one `git add -A`
by any of its writers would publish it:

```
mkdir -p ~/dgo-keys && cd ~/dgo-keys
B=<checkout>/packaging/build-binaries.sh
bash $B --keygen root-a.pem       # and root-b.pem: two roots, kept offline
bash $B --pubkey root-a.pem       # and root-b: add each line to packaging/installer/roots.txt, review, commit
bash $B --keygen signing.pem      # the online key → the DGO_RELEASE_KEY secret
bash $B --relsign keys -signer root-a.pem -site https://digital-office.co.il/dl -version 1 \
     -key signing.pem -types dgo-core-manifest > keys.json   # lives 60 days; -expires changes that
```

A release then runs `build-binaries.sh <version> --keys keys.json --sign-key signing.pem` — or
`DGO_KEYS_JSON` (a path, or the JSON itself) in place of `--keys`; `.github/workflows/release-binaries.yml`
writes its `DGO_RELEASE_KEY` and `DGO_KEYS_JSON` to files and passes both flags, on a `v*` tag only —
its checkout must fetch the branches (`fetch-depth: 0`), or HEAD is in no branch of origin it can see.
It refuses without them (while `roots.txt` names no root, unless it holds HEAD's bytes, and unless HEAD
is in a branch of origin), and signs release versions only (dotted numbers): a run with a development
version such as `0.0.0-dev+<sha>` must leave `--sign-key` out, and then builds drafts.

- **Re-sign keys.json at least every 60 days** (its default life, `-expires` to change it), offline, with
  `-previous keys.json` and `version` + 1 (`-previous` also keeps the list's `core_floor`). The short
  life is deliberate: a revoked key stays good, for a computer whose stub predates the revocation and
  that never saw the new list, until the list that named it expires. A manifest lives until the
  earliest of its `expires`, its key's `not_after` and `keys.json`'s `expires`; the release lane
  re-signs manifests.
- **Publish keys.json before (or with) the stubs built on it**, and keep its cache short: a stub built
  on list N refuses list N − 1.
- **Rotate the signing key:** a new `keys.json`, `version` + 1, listing the new key (and the old one, if
  both should overlap). `-key KEY,FROM,UNTIL` schedules a key's window in advance; without one a key is
  valid from a day before the list is signed until the list expires.
- **Revoke it:** a new `keys.json` without it, `version` + 1, with `-previous` and `-core-floor` set to
  the newest real release — `relsign keys` refuses a list that drops a key `-previous` trusted for core
  manifests unless `-core-floor` is given on its command line (a floor carried over was stated for
  another day). Every computer that sees the list then holds that floor in place of what the revoked
  key pushed it to, refuses the old list, and takes the next real release over what the revoked key
  installed, whichever listed key signs it; every stub built after it refuses the old list outright.
  After a leak, sign the real release with a key **never listed before**: it has signed nothing a replay
  could bring back, and even under a list made by hand without `core_floor` it is free to install,
  where a key kept beside the leaked one stays held to what that key pushed a computer to.
- **One key per purpose:** give the app store its own key, `-types dgo-app-index`; then a leak of the
  store's key cannot sign a DGO core manifest. The store's list has its own floor, `-index-floor` (the
  newest real index), with the same rules: carried over by `-previous`, and required on the command line
  of a list that drops a key `-previous` trusted for `dgo-app-index`.
- **A leaked root:** new roots in `roots.txt`, a new generation of stubs; their memory starts clean.
- **Retire stubs:** raise `--min-bootstrapper`. Do it rarely — a stub that does not change keeps its
  SmartScreen reputation, the manifest and the payload are what change per release.

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
- **Self-update:** forward-only, verified through the same embedded roots (the model this stub uses).

## The release lane

`packaging/build-binaries.sh` builds this stub, `dgo` and `forward-auth` for all six targets with one
command — vet + tests first, `CGO_ENABLED=0 -trimpath -buildvcs=false`, the stub's 4 MiB gate, a double
build proving the bytes are reproducible, `SHA256SUMS`, and the download tree the website serves:
`dist/dl/keys.json` and `dist/dl/<os>/<arch>/{dgo-core[.exe], manifest.json}`.
`.github/workflows/release-binaries.yml` runs exactly that on a `v*` tag (attaching the binaries to the
GitHub release) or by hand (artifact only).

Signing is `packaging/relsign` (stdlib Go, `crypto/ed25519`): `keys` (a root signs the key list),
`manifest` (the online key signs a target's manifest, its sha256 and size read from the file), `index`
(the store's key signs the app index's document) and `floor` (the version and sha256 of a key list —
what a release stub is built with). relsign only produces, in `packaging/trust`'s encoding; the one
verifier is that package, as this stub runs it — before it says done, the script runs `TestReleaseTree`
over the tree it is about to publish (keys.json against the committed roots and against the floor baked
into the stubs, every manifest against keys.json, every payload against its manifest), so a release
cannot pass a check the installer would fail. `TestRelsignChainVerifiesInTheStub` signs with relsign
and verifies with the stub; `PAE` is pinned to the DSSE spec's test vector. Without `--sign-key`
the stubs are development builds and the manifests are `manifest.unsigned.json` drafts, which the stub
refuses. `--selftest` runs the whole chain with throwaway keys and proves a forged `keys.json`, another
list under the stubs' version and a swapped payload are refused.

## Status

Step 1 of the plan (DGO-595): the stub is under 4 MiB on all six targets with a gate, carries the key
layer (pinned roots → `keys.json` → whole-manifest signature with `site`, `version`, `expires`,
`min_bootstrapper`; every signed document typed, every key scoped to its types; the site's own
`core_floor`), refuses a replayed old manifest, a forged `keys.json` and anything signed for another
purpose or another site, and recovers from a leaked key by a revocation that states `core_floor` —
without opening a rollback to what a kept or re-listed key once signed. What remains — the
owner's: the roots (into `roots.txt`, by a reviewed commit), the signing key and the first `keys.json`
(D1), stored for the release lane (the `DGO_RELEASE_KEY` secret and `DGO_KEYS_JSON`, which
`release-binaries.yml` passes as `--sign-key` and `--keys`), and serving `dist/dl/` at
`https://digital-office.co.il/dl/`. Not in this slice: native dialogs for the three "next" screens (the
plan's step 1 lists them; today the screens are text with flags) and the per-OS code signing /
notarization of the stub itself. DGO core is `dgo` (core-005). Tracked as DGO-483 (parent req-461 /
DGO-461) and DGO-595.
