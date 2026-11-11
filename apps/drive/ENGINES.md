# «קבצים» and its engines — `drive`, `drive-local`, `drive-google` (DGO-1500)

The owner, 2026-11-09 (DGO-1494): the drive app is split into a private engine, Google Drive as an
external engine, and a generic drive app that unites them all and gives every account of every engine
in one protocol — and there, in its screen, a person connects their Drive account easily. The pattern is
`ai/context/provider-apps.md` (DGO-1473); the worked example is `apps/domains` + `apps/domain-internic`.

## The three apps

| app | kind | what it holds | what it never holds |
|---|---|---|---|
| `drive` «קבצים» | the GENERIC app | the screen (`static/`), every route callers use (`/api/*`, `/list` `/upload` … the §3 ops, `/connections`, `/manifest`, `/readyz`, `/providers`, `/engines`, `/extensions`), the binding (which drive the agents use by default), resumable uploads, the recorder, `bbox drive` | a line of any engine's code: no database, no storage client, no Google |
| `drive-local` «אחסון הלשכה» | engine (`provider.json` kind `engine`) | the office's own storage: the index in postgres (`drive_files`, `drive_folders`, `drive_profiles`), the bytes in supabase storage (bucket `drive`), its profiles and their keys, the share links `/file/d/<id>/view`, pictures and waveforms of its own files | a screen of its own: its state is shown in «קבצים» |
| `drive-google` «Google Drive» | engine (`provider.json` kind `external`) | Google Drive's API: an account signed in with Google (protocol `drive_google_oauth`, the consent through the herd's relay) and a service account (`drive_google_service_account`); exports of Docs/Sheets/Slides; its download cache | a screen of its own |

Nothing a caller sees moves: the generic app keeps the id `drive`, the address `http://drive:8975`, every
route, and every answer's shape; the vault keeps its rows under the same protocol names, so no account is
connected again and no file moves. A caller that names `connection_id=drive_local-admin` or a Google
account's id gets the same answer as before.

## Finding the engines — by name, as domains finds its providers

An engine is an app whose id is `drive-<engine>`: in this office's compiled registry
(`.generated/registry/office.apps.json`) or given by a linked office (`remote.<office>.<alias>.json`), ours
first (`apps/drive/engines.py`, the same rule as `apps/domains/provider_client.py`;
`DRIVE_ENGINE_<ID>_URL` overrides). Each answers `GET /ops`, which names the protocols it serves. The
vault protocol names follow the same rule: every engine's protocols are `drive_*`. Adding an engine adds
nothing to `drive`; removing its app removes its accounts from the list (they show as «needs action»,
never as somebody else's drive).

## The one protocol: `drive-engine.v1`

Every engine serves the same routes. Every JSON answer is `{"ok": true, …}` or
`{"ok": false, "error": "<Hebrew, for a person>", "status": <http>, "kind": "adapter"|"auth"|"profile"}`.

| route | what |
|---|---|
| `GET /ops` | `{interface: "drive-engine.v1", for: "drive", id, kind, service, ladder, protocols: {<proto>: {private}}, engines: [...], providers: [...], routes: [...]}` — `engines`/`providers` are this engine's rows of `drive`'s `/engines` and `/providers` (the connect dialog's catalogue); `routes` are the path prefixes `drive` hands to it verbatim (`/engine/`, `/file/d/` for drive-local; none for drive-google); `oauth` names a consent door `drive` opens itself at `/oauth/<name>/start|return|finish` (drive-google: `google` → connections' `google-workspace-grant`). `routes`, a `private` protocol and `oauth` are trusted only from an engine of this office, never from one a linked office gives |
| `POST /v1/accounts` `{instances}` | the vault rows of its protocols, annotated (a profile's name, admin flag, a row that cannot work says why) |
| `POST /v1/describe` `{connection_id}` | what this drive can do: `{protocol, private, profile_id, methods, views, creates}` — the generic app offers only what an engine can answer |
| `POST /v1/call/<method>` `{connection_id, args, kwargs}` | one op of the drive interface (below) → `{ok, result}` |
| `GET /v1/content?connection_id&id&want` (+`Range`) | a file's bytes, streamed, with the engine's own serving headers |
| `GET /v1/download?connection_id&file_id&file_id_mode` | the §3 `download` op's bytes |
| `PUT /v1/store?connection_id&size&md5&name&mime&folder` (body = the bytes) | store one file, streamed → `{ok, result: item}` |
| `PUT /v1/op_upload?connection_id&size&md5&name&mime&folder` | the §3 `upload` op (its answer is the engine's own file resource) |
| `POST /v1/thumb` `{connection_id, item, size}` | a picture of the file (`image/*` bytes) or 404 |
| `POST /v1/connect` `{protocol, label, secret, account_hint}` · `POST /v1/disconnect` `{connection_id}` | add / remove an account of this engine (each engine checks its own credential) |

The drive interface carried by `/v1/call/<method>` — the methods the in-process adapters had, with the
same arguments and results: `probe, folders, subfolders, create_folder, rename, move, trash, delete,
resolve_path, ensure_path, path_of, free_name, file, files, trashed_folders, shared_folders, views,
media_files, changes_rev, star, touch, storage, search, search_folders, peaks, op_list, op_move,
op_update, op_delete, op_create_from_text`. A method an engine does not have is absent from `describe`,
and the screen does not offer it.

A request carrying a profile key (`X-Drive-Profile-Key` / `Authorization: Bearer`) passes it to the
engine, which checks it (drive-local refuses a key of profile B on profile A's drive). A request without
a key acts as the drive `drive` is bound to: drive-local asks `drive` (`GET /connections/active`) and
takes nothing the request carries for it. What `drive` hands to an engine carries only the range, the
conditions, the body's type and the key — never the person's session (Cookie, the SSO headers) — and a
path that climbs (`.`/`..`) is refused before any hand-over.

## What moved where

- `adapters/local.py`, `profiles.py`, `db.py`, `bootstrap.py`, `media_jobs.py` → `apps/drive-local/`
  (with `app.json`'s `engine.profiles`, the supabase credentials, `use: sql, object-storage`).
- `adapters/google.py`, `google_sa.py`, `dlcache.py` (the consent pages stay `drive`'s — its screen opens
  and receives them, for the door the engine names in `/ops` `oauth`) →
  `apps/drive-google/` (with the Google OAuth client's id for refreshing a token).
- `drive` keeps `connections_client.py` (the vault list, the binding), `uploads.py`, `extensions.py`,
  `cli.py`, `static/`, and gains `engines.py` (finding the engines, the remote adapter).
- Volumes: `drive` keeps `localdrive_data` (the binding, the extension registry, upload sessions);
  `drive-local` has `drive_local_data` (the profile ledger, its pictures and waveforms — regenerated);
  `drive-google` has `drive_google_data` (the download cache — regenerated).

## Every account of every engine, one list

`GET /connections` lists the vault's `drive_*` rows (the vault is the truth), asks each engine to
annotate its own (`/v1/accounts`), and answers the same list it always did. An engine that is not running
or not answering marks its rows `needs_action` with the reason («המנוע … אינו זמין») — they never vanish
and never resolve to another drive. The side of «קבצים» shows them all under «כוננים».

## For backup (DGO-1505)

What to keep, by app: `drive-local` holds the office's files (supabase-db tables `drive_files`,
`drive_folders`, `drive_profiles`; storage bucket `drive`; volume `drive_local_data`); `drive` holds the
binding and the extension registry (volume `localdrive_data`; `uploads/` there is in-flight data);
`drive-google` holds only a cache. A backup that writes to «a chosen files app» writes through `drive`'s
`PUT /api/fs/content?path=…&connection_id=…` (any engine's account, by its connection id).

What restic needs of a store (DGO-1505's six, 2026-11-09), and where each stands, through `drive`:

| need | drive-local | drive-google |
|---|---|---|
| 1. delete with no trash left behind | yes, two calls: `POST /api/trash {ids}` then `POST /api/delete {ids}` (delete acts only on the trash, by design) | the same; Drive's own trash is emptied by the second call |
| 2. ranged read | yes: `GET /api/fs/content?path=` or `/api/file/<id>/content` with `Range:` (206) | yes (Drive `alt=media` with `Range:`) |
| 3. stat, «not found» exactly 404 | yes: `GET /api/fs?path=` → `{kind:"file", file:{size,…}}` or 404 | yes; with duplicate names Drive allows, the path names one of them |
| 4. a whole folder listed, with sizes, a just-written file at once | yes: `GET /api/files?folder=<id>&limit=&offset=` (paged; the index is the database, read after write) | listed whole (every Drive page); Drive's list after a write is not promised by Google to be immediate — not measured |
| 5. visible only once whole, and a create that fails when the name is taken | whole: the index row is written after the bytes are stored. Fails when taken: `mode=exclusive` → 409 (DGO-1500), by a look before the write — the index has no unique name, so two writers of one name at the same instant are not excluded here either | whole: a Drive upload creates the file when it completes. `mode=exclusive` → 409, by a look before the write (two writers of one name at the same instant are not excluded) |
| 6. a «backup store» mark on a folder | a folder an app keeps is marked (`system`, `PUT …&system=<the folder's name>`); leaving it out of the office's own backup is the backup's rule to apply | not needed: a Google account's files are not in the office's backup |
