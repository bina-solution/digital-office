# «קבצים» (apps/drive) — release state and what comes next

State on 2026-10-28: **released on the FPG office** (`drive-fireplace`, build `05e2857611ca` and on).
This file is the map for whoever picks the app up next; the agent brief is [AGENT.md](AGENT.md).

## What the release is

| Area | What it does | Where |
|---|---|---|
| The app | Home, my files, recent, starred, trash, search; photos (by month), music & audio (a player that keeps playing), videos (posters); list and grid; one selection model for mouse, keyboard and finger | `static/js/views.js`, `shell.js` |
| Viewers | ~50 kinds open in place (images, raw/heic via the server, video, audio, PDF, docx, sheets, code, text, markdown, html without scripts, zip, 3D, epub, fonts, vcf, ics, eml, torrent); the rest offer «open with» then download | `static/js/viewer.js`, `types.js` |
| Uploads | resumable (tus 1.0) — any size, survives a dropped line; folders by drag; paste | `uploads.py`, `static/js/upload.js` |
| Media on the server | probe, thumbnails (128–2048), waveforms; a browser recording is remuxed so it seeks | `media_jobs.py`, `media.py` |
| «הקלטות» | the recorder tile (`/rec/`): records in the browser, keeps every second on the device until saved, saves to `/הקלטות` | `static/js/recorder.js` |
| Agents | every file by path: `bbox drive ls/find/get/put/mkdir`, `api/fs` | [AGENT.md](AGENT.md) |
| Meetings | meet-start copies each recording into `/פגישות/<date> · <room>/` (FPG only, `apps/meet/start/server.py`) | — |
| **A small window is a widget** | a box under 300 tall, or under 560×440, shows ONE thing: what plays (the player's face), what is open (the viewer, its bar thinned), pictures one at a time (Photos, a folder of pictures), video posters, else the place's short list; the place's name switches place. The console's own smallest form (a window pushed far aside) gets play/pause + the track, pause/resume while recording, the upload percent (`bina:widget`) | `static/js/widget.js`, `files.css` («a window too small») |

## How it is proven (run these before any deploy)

```bash
python apps/drive/tests/ui/dev_server.py 8971 &          # the app on a mock, no stack
python apps/drive/tests/ui/layout_qa.py                  # 28 sizes × every state: 457 states, 0 issues
python apps/drive/tests/ui/layout_qa.py --dark           # the dark ground
python apps/drive/tests/ui/layout_qa.py --surface recorder   # «הקלטות»: 257 states
python apps/drive/tests/ui/flow_qa.py                    # mouse, touch, recorder, widget, console handshake
python apps/drive/test_core.py                           # the server
node digital-office/sim/build.mjs && python digital-office/sim/flow-qa.py drive   # inside the office (also --mobile, windows --tiles drive)
```

Deploy (FPG): one service, never a stack-wide up — stage `static.tgz` + the code, then
`deploy-files.sh` (aborts while an upload is running; backs up the image as `drive-backup:<ts>` and the
source to `/root/backups/drive-src-<ts>.tgz`; `up -d --no-build --no-deps drive`). Open windows offer
«רענון» by themselves (the build id in `/api/changes`).

## Next, in order

1. **Every app gets a small-window form** (the owner's rule, 2026-10-28: a tiny window shows only the
   most relevant thing). «קבצים» and «הקלטות» are the reference: measure the app's OWN box, swap the
   frame for one face, and say a `bina:widget` line to the console. Mail and notifications already say a
   line; the rest (chat, my-docs, INDOX, the console's own screens…) need their faces.
2. **«פתיחה באמצעות» companions** for what ~50 native viewers do not cover: Collabora/WOPI (office
   editing), Gotenberg (conversion to PDF), code-server, a CAD viewer — each an installable app that
   registers in the `open-with` slot. A resource decision first: the FPG server has 2 cores.
3. **The shared blocks' language**: `platform-base/bina-ui`'s `binaSaid` has no `L()` wrappers while
   the apps' copies (after the language commits) do — a `theme-token-lint.py --fix` re-stamps the
   Hebrew-only source over them. Put the `L()` version into the source once (owner of bina-ui).
4. **The recorder tile's glyph**: the console has no `mic` in its icon set (the tile uses `activity`);
   adding it needs a console rebuild, which waits for the console's own pending changes on FPG.
5. **An English tile name** for «הקלטות»: the app schema's module has no `name_en` (schema change).
6. **The simulator's drive data**: the mock has no audio or video files, so its Music and Videos are
   empty states — add a few so the sim's map shows the player and the posters.

## Known limits (said, not hidden)

- A console window pushed far to a side keeps the console's button form for good once «קבצים» has
  said a line there (the console has no "unsay"); the line goes empty when nothing plays.
- Media controls follow the app's existing right-to-left timeline (the wave fills from the right);
  whether transport buttons should stay left-to-right is an open design question.
