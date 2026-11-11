# DGO-1614 — the photos from the phone go to the office at home (read-only research and a design)

Item `DGO-1614`, from meeting `bs106` (the owner, 2026-11-09): an app like Google Photos and Google
Drive — **every person with their own photos, one office responsible for the storage, and on the
phone you see what was backed up and what can be deleted.** No build in this note: this is the engine,
the placement and the shape, so the next item can be a build.

Sources were read on 2026-11-09 (each one linked in §7). Nothing here was measured on the office
except the machine facts, which are ours: the HP (6 cores, 9 GB RAM, 859 GB free disk, ~2 GB RAM
available while the office is live) and the Dell (4 threads, 15 GB, **28 GB free disk**, CI's only
runner, `x86_pkg_temp` 87 °C at rest tonight).

---

## 1. The engine: Immich, and why not PhotoSync

| | **Immich** | **PhotoSync** (what the owner uses today) |
|---|---|---|
| what it is | self-hosted photo/video library: server + web + mobile apps, per-user libraries, backup with per-asset state | a transfer utility on the phone: it moves photos to destinations (SMB/WebDAV/FTP/S3/…); it is not a library |
| licence | **AGPL-3.0** ([repo](https://github.com/immich-app/immich), read 2026-11-09) | **commercial, closed source** — its code is not in the owner's or bina-solutions' GitHub, and this note does not ask him for it; treat it as a paid black box |
| server side | yes: users, albums, dedup, thumbnails, search, trash, sessions | **none**: every phone writes to a share by itself; nothing knows what was backed up across people |
| the office's four channels | an API (documented OpenAPI), a CLI, a web UI, per-user state to hang events on | no API to speak (a file transfer), no server state, no events |
| verdict | **the engine to design on** | its role stays what it is: an option for a phone that must push to a share; it cannot be "one office responsible for the storage" |

**Immich is the only open engine that answers the item as written.** Its phone app has exactly the
three things the owner asked for: *background upload of selected albums*, *a per-asset state (backed
up / local only)*, and **«Free Up Space» — delete from the phone only what is safely on the server**
(["Mobile App"](https://docs.immich.app/features/mobile-app)). It also has a **read-only / kid mode**
(`Settings → Advanced → Read-only Mode`) — the "every child with their own photos" part, without a
child being able to wipe the library from the phone.

Honest alternatives, one line each: **Nextcloud** (AGPL, photos app, much heavier: a full PHP stack),
**PhotoPrism** (own licence, ML-first, weaker mobile app), **Ente** (AGPL, end-to-end encrypted —
the office could not run face recognition or help with a lost photo), **Syncthing** (MPL-2.0, perfect
at moving bytes, no library, no "what was backed up", so it cannot show a person what is safe to
delete). Immich wins on the mobile side, which is where this item's value is.

### The licence question, in one paragraph

AGPL-3.0 means: run it, modify it, and if we *offer the modified software to others over a network*,
we must offer them the source. Bina Solutions runs Immich for its own office and its own family — no
modified Immich is offered to third parties — so the obligation is the ordinary one (keep the source
available for the engine's own files; do not ship a closed fork of it). What must **not** happen:
DGO code being linked into Immich's own modules as if it were ours to relicense. Our app therefore
wraps it (HTTP + its API), never patches its source.

## 2. Footprint, and where it goes (the herd rule)

Immich's own requirements ([docs](https://docs.immich.app/install/requirements)): **min 6 GB RAM /
2 cores, recommended 8 GB / 4 cores**; the ML container on amd64 needs `x86-64-v2` (any CPU since
~2012); Postgres holds 1–3 GB and should sit on local SSD, and **needs ~2 GB of its own** when limits
are used; thumbnails and transcoding grow a library by **10–20 %**. Below 6 GB the docs' own answer is
*run it with machine learning disabled*.

Immich is **five containers** in its compose: `immich-server` (API + web), `immich-machine-learning`
(faces, CLIP/smart search, OCR), `database` (Postgres + vector extension), `redis`, and the ML cache
volume. The ML service is a **separate HTTP service** (`IMMICH_MACHINE_LEARNING_URL`,
[env vars](https://docs.immich.app/install/environment-variables)) — which is what makes the herd rule
possible at all: the library and the database stay where the bytes are, the heavy inference can be
somewhere else.

| | **HP — the always-on centre** | **Dell — the workshop** |
|---|---|---|
| RAM | 9 GB total, **~2 GB free** while the office runs; 6 cores | 15 GB, 4 threads |
| disk | **859 GB free** | **28 GB free** — cannot hold a family library |
| today | traefik, the apps, Plane, n8n, the ASR's *caller* | CI's only runner, Ollama, the ASR, 87 °C at rest |
| verdict | **the library lives here**: server + Postgres + redis, ML **off** at first. Disk is the one thing the HP has and the phones need | ML (faces + CLIP) belongs here by the herd's own rule — but **not tonight**: 28 GB free and a hot CPU shared with CI. It is a later step, with a thermal guard, exactly as the ASR's run now is |

Numbers to expect on the HP with ML off: `immich-server` a few hundred MB, Postgres ~300 MB–1 GB with
its own limit raised to 2 GB, redis tens of MB. That is a real cost on a box with 2 GB free — so the
first phase must cap it (`resources:` in app.json, the compose's own limits) and the office stays
healthy; the owner's other apps are not to be squeezed by a photo library.

**Storage is the design's hard part**, and it is not RAM: one phone's camera roll is 5–20 GB a year,
a family is 50–150 GB a year, and Immich adds 10–20 % for its derivatives. 859 GB is a few years — so
the app must report disk (it can: `/api/server/storage`), and the flow must raise a notice at a
threshold. An external disk on the HP is the growth path, not a bigger VM.

## 3. The shape as a DGO app — four channels, and the engine mode

The office's rule for an app that wraps somebody else's engine (the same shape `project-pln` and
`n8n` already have): **the engine is declared, not re-implemented.** Our app owns `app.json`, the
tile, the SSO, the channels and the data directory; Immich runs as the services that declaration
names, and DGO code never reaches into Immich's volume, database or files.

| channel | what it is here |
|---|---|
| **ui** | the console tile. Immich's own web UI is a root-built SPA (like Plane's), so the tile is `external: true` with the engine on **its own host** (`photos.<office host>`), framed the way Plane is (`module.url` = the in-network address, the browser is signed in through `/.dgo/enter`). No second UI is written: a photo library's screen is the one thing not worth rebuilding |
| **cli** | `./bbox photos status\|users\|albums\|usage\|backup-report <person>` — thin verbs over the API, so an agent (and I) can answer "did everyone's phone upload today" without a browser |
| **api** | a capability `photos` (ops: `status`, `accounts`, `albums`, `assets`, `storage`, `usage`) served by the app's own small service, which holds the Immich API key **in the credential plane**, never in a config file. Other apps (drive, dashboard) call this, not Immich |
| **flow** | events on `dgo:flow:photos`: `photo.backed-up`, `photo.deleted`, `storage.low`, `person.quiet` (a phone that has not uploaded for N days). Immich has no webhook of its own in v3 — the app's poller reads `/api/jobs` + `/api/server/storage` and writes the events, the same way `notifications` polls GlitchTip |

**The drive (the `drive` app, `/מחקרים`) is not the photo store.** Three rules keep them apart:

1. **Originals live in Immich** (its own volume). The drive holds **documents**, and a photo library
   in the drive would be a second library with no dedup, no trash, and no "what is safe to delete".
2. **The drive gets the index, not the pixels**: the app writes `/תמונות/<person>/` with one small
   text file per month (`2026-11 · 214 photos · 3.1 GB · backed up`). It is what a person opens in the
   drive to see the state of the family's backup without the photo app — `createFromText`, the
   drive's own op.
3. **When a photo is a document** (a passport scan, a receipt), it goes to the drive as a file —
   the same way recordings land in `/פגישות`. A share link from Immich is pasted into the drive note
   when a person needs to send one.

## 4. What the phone does — no port opened

The phone reaches the office the way the other offices do, through **the link, not a new door**:

```
phone  ──HTTPS 443──►  vps1 edge (public, valid certificate)  ──dgo link (WireGuard)──►  HP: immich-server
```

* **Nothing is opened on the home router.** The only public thing is vps1's 443, which already exists;
  the office declares its photo host in `serve:` to vps1 the way `speech` is declared to the HP
  (`apps/apitools/app.json`), and vps1's link proxy carries it. That is also the item's own sentence:
  *through DGO Extend / the link*.
* **At home, on the LAN**, the same host can also be answered locally (the office's LAN route,
  `office-routes`) — but the **phone always keeps the public HTTPS name**, so moving between home and
  away never re-points the app. Immich's mobile app signs in with a server URL; a name that does not
  change and a certificate that is valid are the two things it needs.
* **HTTPS is not optional**: Immich sets `upgrade-insecure-requests` by default and a phone will not
  keep a plain-HTTP session for background uploads. The engine's own host must therefore be under the
  office certificate; `*.localhost` is useless to a phone.
* **The app is from the store** (Apple/Google), signed and published by the Immich project — the
  office does not build a phone app, and there is no key of ours to leak. A kid's phone signs in to
  **its own user** and is set to **Read-only Mode**.

## 5. The plan in phases (each one shippable and reversible)

1. **Library on the HP, ML off.** `immich-server` + `postgres` + `redis` as the app's services, on its
   own host behind the link, SSO off for the phone path (the phone has Immich's own login) and SSO on
   for the web tile. One user per person. Proof: one phone uploads 50 photos, «Free Up Space» offers
   exactly those, and the web tile shows them.
2. **The channels.** The `photos` capability, `bbox photos …`, the flow events, and the drive index
   files (`/תמונות/<person>/…`). Proof: an event on the stream per backup, and a drive folder that
   says which phone uploaded when.
3. **Faces and smart search on the Dell** — only when the Dell has disk and a cool head: the ML
   container pointed at the HP's server (`IMMICH_MACHINE_LEARNING_URL` over the link), `--cpus 1.5`,
   thermal guard, and `MACHINE_LEARNING_MODEL_TTL` left at 300 s so the models unload when idle.
   Until then those features are simply off (the app hides them).
4. **Growth.** Disk threshold event, an external disk on the HP, and a backup of the library —
   an un-backed-up family archive on one home machine is the failure mode this whole item is about.

## 6. Risks and the honest no's

* **«Free Up Space» and WhatsApp/iCloud.** Immich's docs are explicit: removing local files breaks
  media in chat apps (WhatsApp shows them blurry/missing), and with iCloud Photos a deletion on the
  phone propagates to iCloud. The design keeps WhatsApp albums and iCloud shared albums in
  `Keep albums` (default) and only frees camera-roll items past a cutoff date — the owner confirms the
  cutoff once, per phone.
* **One machine, one copy** is not a backup. Phase 4 is not optional.
* **CPU/RAM on the HP tonight**: 2 GB free. Phase 1 must cap the containers and be watched; if the
  office is squeezed, the library moves to a bigger disk before it moves to the Dell (the Dell has no
  room, and it is CI's runner).
* **AGPL**: no closed fork, no patched Immich. Wrap it.
* **PhotoSync is not replaced by a decision made here** — it stays on any phone that prefers it; what
  the office gains is a *library* that knows what arrived.

## 7. Sources (read 2026-11-09)

* Immich repository — AGPL-3.0, active — https://github.com/immich-app/immich
* Requirements (RAM min 6 GB / rec 8 GB, CPU 2/4, x86-64-v2 for ML since v3, Postgres 1–3 GB + 2 GB,
  derivatives +10–20 %) — https://docs.immich.app/install/requirements
* Environment variables (the ML service as a separate HTTP service, `CPU_CORES`, model TTL, DB/redis
  URLs, secrets from files) — https://docs.immich.app/install/environment-variables
* Mobile app (server URL at sign-in, per-asset backup state, «Free Up Space», album sync, read-only /
  kid mode, iCloud and WhatsApp caveats) — https://docs.immich.app/features/mobile-app
* Mobile backup (background upload, album selection, dedup by checksum, Wi-Fi only by default) —
  https://docs.immich.app/features/mobile-backup
* In-repo, for the DGO side: `apps/drive/AGENT.md` (the drive's ops and its rules),
  `apps/apitools/app.json` (`speech` declared to a linked office — the `serve:` shape this design
  copies), `ai/context/dgo-herd.md` (HP the always-on centre, the Dell the workshop, 2 cores/15 GB),
  `ai/context/build-your-first-app.md` (app.json, routing/module, SSO, data volumes),
  `apps/office-routes/AGENT.md` (the LAN route, and why it is the owner's to open).
