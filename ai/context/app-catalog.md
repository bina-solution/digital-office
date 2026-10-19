# The signed app catalog — publishing an app, and installing one

How an app gets from someone else's machine into this platform. Mechanism lives in
`platform/manager/{catalog,signing,appinstall}.py`; the trust model is `platform/trust/README.md`.

## The format

Three files, and the chain between them is the whole design (it is F-Droid's index-v2, adapted):

```
index-v1.json        the catalog. One entry per app: id, version, title, summary, layer, kind,
                     capabilities provided/used, connections (credentials) it will request,
                     routes, volumes, resources, the n8n workflows it ships, facts read out of
                     its compose file (images, published ports, host mounts, docker socket),
                     manifest_sha256, and an artifact {url, size, sha256}.
index-v1.sig.json    a detached Ed25519 signature over {sha256, size} of index-v1.json.
artifacts/<id>-<v>.zip   the app directory, packed deterministically (sorted, fixed timestamps),
                     so the same tree always produces the same sha256.
```

One signature covers everything: sig → index hash → per-artifact hash. Verification needs no
server, so the catalog can live on S3, a raw git URL, or a USB stick, and a mirror can be untrusted
because the bytes are checked rather than the source.

## Publishing (what a third-party author does)

```bash
bbox catalog keygen --label "acme apps"      # once. secret stays local, public half is pinned
mkdir -p acme/apps/my-app                    # app.json + docker-compose.yml (+ hooks/, blueprint/)
bbox catalog build --source acme/apps --out acme/pub --base-url https://apps.acme.example
# upload acme/pub/ anywhere static. Publish the key id + public key somewhere YOU control.
```

`app.json` must validate against `platform/schema/app.schema.json`; `bbox apps validate` is the
same check the installer runs. `layer` must be 3 — layers 1-2 are the platform chassis and the
installer refuses them.

## Installing

```bash
bbox catalog trust <key-id> <public-key-hex>          # the one trust decision. Out of band.
bbox app install my-app --index https://apps.acme.example/index-v1.json --dry-run   # disclose only
bbox app install my-app --index https://apps.acme.example/index-v1.json
```

Or from the store screen (`apps.localhost` → חנות האפליקציות): paste a URL, or pick a file. Same
code path, same disclosure, and the disclosure is computed from the bytes that get installed —
`preview` stages them and `install` completes from that same staging, so the thing you approved is
the thing you get.

Other refs: a raw URL or path (needs `--sha256`, or `--allow-unverified`, or a hash the signed
index already vouches for), and a local directory with an `app.json` for an author iterating.

## What is checked, in order

1. index signature against a **pinned** public key — an untrusted key is refused, even though the
   envelope carries a key of its own
2. artifact sha256 against the signed index
3. archive members for path traversal
4. the manifest, via `reconcile.validate()` with the candidate spliced into the live catalog —
   structure, types, and the id / route-host / console-tile claim conflicts
5. `reconcile.resolve(roots=[id])` — the provider closure and any declared conflict
6. the disclosure is shown
7. only then: placed in `apps/<id>`, registered in `platform.state.yaml`, recompiled, started
   through the normal lifecycle

`python3 platform/manager/catalog_selftest.py` asserts every one of those refusals.

## Known gaps for an author

- **No upgrade verb.** Entries carry `version` and `manifest_sha256`, so "an update exists" is one
  comparison away, but nothing performs it; reinstalling means uninstall then install.
- **No `bbox app package`.** Authors build a whole catalog (`--source`) rather than one artifact.
- **No revocation.** Distrust is `bbox catalog keys` + deleting the entry by hand.
- **`.env` is not part of an app.** An app needing a new environment variable still requires an
  operator edit; only declared `connections` are wired automatically.
- **Images are pulled unverified by Docker**, not by this chain. The catalog signs the app
  *definition*; `image: acme/foo:latest` is still trust-on-pull. Digest-pin in your compose.
