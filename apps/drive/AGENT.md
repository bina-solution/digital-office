# Operating «קבצים» (the `drive` app)

The office's one place for files. The owner drops what he wants you to work on into a folder here
and names it by its **path** — `/הקלטות/הקלטה חדשה 3.m4a`, `/מסמכים/חוזים` — so work by path, not by
id. Apps write here too: meeting recordings and transcripts under `/פגישות`, the recorder's takes
under `/הקלטות`. A folder an app writes into is marked (`system`) and cannot be renamed, moved or
deleted.

## From the server's shell

```bash
./bbox drive ls /הקלטות                         # what is in a folder
./bbox drive find הקלטה                          # names that hold a text, with their paths
./bbox drive get "/הקלטות/הקלטה חדשה 3.m4a" /tmp/   # a file to the host (streams; any size)
./bbox drive put ./summary.md "/פגישות/2026-10-28/"   # a file into a folder (made on demand)
./bbox drive mkdir "/פגישות/2026-10-28"
```

## From inside the office network (a container on traefik-network)

```bash
curl -s --get --data-urlencode "path=/הקלטות" http://drive:8975/api/fs                  # a folder and what is in it
curl -s --get --data-urlencode "path=/הקלטות/x.m4a" -o x.m4a http://drive:8975/api/fs/content
curl -s -X PUT --data-binary @out.md -H 'Content-Type: text/markdown' \
     "http://drive:8975/api/fs/content?path=$(python3 -c 'import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))' '/פגישות/2026-10-28/סיכום.md')"
```

`PUT …/api/fs/content` keeps an existing file and names the new one «name (2)»; `&mode=replace` moves
the old one to the trash first. A file over ~100 MB from a browser goes through the resumable upload
(`POST /api/uploads`, tus 1.0) — from a container, the PUT above streams any size.

## Rules

- **Never delete.** Trash only with the owner's go-ahead in his own words; permanent delete is his.
- Put what you produce **beside its source** with a name a person understands (the transcript of
  `/הקלטות/x.m4a` is `/הקלטות/x — תמלול.md`), never in the root.
- The owner's files are his: read them for the task he gave, do not copy them out of the office.
- A share link (`/file/d/<id>/view`) opens the file for anyone who has it — give one only when asked.
