# Operating «קבצים» (the `drive` app)

The office's one place for files — and for every drive the office is connected to. A **drive** is a
connection: a profile of the office's own storage (`admin`, `user2`…), a Google account (signed in with
Google), or a Google service account. The owner drops what he wants you to work on into a folder here and
names it by its **path** — `/הקלטות/הקלטה חדשה 3.m4a`, `/מסמכים/חוזים` — so work by path, not by id. Apps
write here too: meeting recordings and transcripts under `/פגישות`, the recorder's takes under `/הקלטות`. A
folder an app writes into is marked (`system`) and cannot be renamed, moved or deleted.

## From any office's shell (`bbox drive …` and `dgo drive …` are the same door)

```bash
./bbox drive profile list                        # every drive: what it is, and the default (*)
./bbox drive -p admin ls /הקלטות                  # -p names a drive: profile id, address, name or connection id
./bbox drive -p person22@example.com files list /עבודה        # …a Google account by its address
./bbox drive -p admin folders list / · tree / --depth 2 · file "/מסמכים/x.pdf" · storage
./bbox drive find הקלטה                           # names that hold a text, with their paths
./bbox drive get "/הקלטות/הקלטה חדשה 3.m4a" ci-artifacts/   # to this machine (streams; any size)
./bbox drive put ./summary.md "/פגישות/2026-10-28/"          # into a folder (made on demand); --replace; --empty
./bbox drive mkdir · mv <path> <folder> · rename <path> <name> · rm <path> (trash) · restore <name> · link <path>
./bbox drive help                                 # all of it
```

Without `-p` the office's **default** drive is used (`*` in the list) and a write says so on stderr. On an
office that does not run the drive (the MacBook) the same commands reach the office that does, through the
link. Making another drive the default is `profile default <drive>` — a shared choice: only on the owner's words.

## From inside the office network (a container on traefik-network)

Every call takes `connection_id=<id>` (or `profile_id=<id>`) to name the drive; without it, the default.

```bash
curl -s "http://drive:8975/connections"                                                  # the drives
curl -s --get --data-urlencode "path=/הקלטות" http://drive:8975/api/fs                  # a folder and what is in it
curl -s --get --data-urlencode "path=/הקלטות/x.m4a" -o x.m4a http://drive:8975/api/fs/content
curl -s -X PUT --data-binary @out.md -H 'Content-Type: text/markdown' \
     "http://drive:8975/api/fs/content?path=$(python3 -c 'import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))' '/פגישות/2026-10-28/סיכום.md')"
curl -s "http://drive:8975/api/fs?path=/&connection_id=drive_google_oauth-1a2b3c4d"     # the same, on a Google account
```

`PUT …/api/fs/content` keeps an existing file and names the new one «name (2)»; `&mode=replace` moves the
old one to the trash first; `&mode=exclusive` refuses (409) when the path is taken. The body is the file
(a multipart form is refused, 415), and the drive is named only in the address or headers; an empty body
is refused (400, nothing trashed) unless `&empty=1` (`put --empty`). A file over ~100 MB from a browser goes through the resumable upload
(`POST /api/uploads`, tus 1.0) — from a container, the PUT above streams any size. A Google Doc, Sheet or
Slides file has no bytes of its own: `content` exports it (a PDF inline, the Office file with `dl=1`).

## Connecting a drive

The screen's «חיבור Google Drive» (in the side, under «כוננים»), one screen with two ways: **signing in
with Google** (one consent connects that account's Drive and Gmail; it returns through the herd's public
door, connections `OAUTH_RELAY_URL/oauth/relay`), or **sharing a folder with the office's address** (a
service account: the screen shows its address to copy, the person shares the folder in Google Drive, and
«בדיקה» shows what arrived — it reads, it cannot create files). «חיבור חשבון» lists every kind; a profile of
the office's storage is made in «ניהול פרופילים». Every new drive is checked (`/connections/<id>/probe`).

## The engines behind it (DGO-1500)

«קבצים» is the generic app; each drive is an account of an engine it finds by name: `drive-local` (the
office's own storage) and `drive-google` (Google Drive), one protocol (`drive-engine.v1`, ENGINES.md).
Nothing you call changes: the addresses and answers above are «קבצים»'s. `./bbox drive-local status` and
`./bbox drive-google status` say whether an engine answers and which accounts it holds.

## Rules

- **Never delete.** Trash only with the owner's go-ahead in his own words; permanent delete is his.
- Put what you produce **beside its source** with a name a person understands (the transcript of
  `/הקלטות/x.m4a` is `/הקלטות/x — תמלול.md`), never in the root.
- The owner's files are his — and a Google account's files are its owner's: read them for the task he
  gave, do not copy them out of the office or between drives unless he asked.
- A share link (`/file/d/<id>/view`) opens the file for anyone who has it — give one only when asked.
