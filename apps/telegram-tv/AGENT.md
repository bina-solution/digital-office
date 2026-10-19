# Operating `telegram-tv`

The office's film library. Telegram is not a video platform, but its channels are used as one: a poster,
a description and a video file, and the whole catalogue exists only as messages. This app reads them and
shows a TV: **a row per chat, a card per film, series with seasons and episodes, a player that streams
straight from Telegram**.

Vocabulary: **account** = a `telegram_user` connection in the credential plane (api_id/api_hash + MTProto
session string, i.e. a full login). **chat** = a dialog; `enabled` = it is a row, `has_video` = a scan
found films. **scraper** = the policy turning messages into films (`default`, `album`, `amsalem` — the
last parses the Hebrew poster format); auto-detected unless a person locked it. **movie** = one playable
file, id `<chat_id>:<message_id>`, stable across re-scans. **series** = episodes derived from NAMES.

## What you can do from here

```bash
curl -s -X POST http://telegram-tv:8982/status   -H 'content-type: application/json' -d '{}'
curl -s        http://telegram-tv:8982/readyz     # 200 = account connected AND the client works
curl -s        http://telegram-tv:8982/api/series # what the app considers a show
curl -s        http://telegram-tv:8982/api/cache  # the local copy of what has been watched
curl -s -X POST http://telegram-tv:8982/listMovies -H 'content-type: application/json' \
     -d '{"q":"מטריקס","limit":20}'
curl -s        "http://telegram-tv:8982/api/play/<chat_id>:<message_id>"   # HOW this film can play
curl -s        http://telegram-tv:8982/api/chats/<chat_id>/history         # what is really in a chat
curl -s -X POST http://telegram-tv:8982/refresh -H 'content-type: application/json' -d '{"full":true}'
curl -s        http://telegram-tv:8982/api/sync/status
```

Canonical ops (`status`, `listChats`, `listMovies`, `getMovie`, `refresh`, `streamUrl`) answer
`{"ok":true,"op":…,"data":{…}}`; failures are 4xx/5xx with a Hebrew `detail`.

## Traps

- **Connecting an account is the OWNER's action, in the app** (`/a/telegram-tv/`): QR or phone+code. You
  never log in for him, never ask for the code, never handle the session string.
- **`/healthz` green does NOT mean Telegram works** — it reports the process, deliberately, so an expired
  session cannot put the container in a restart loop. Read `/readyz`, `status.ok` + `status.reason`.
- **Ask `/api/play/<id>` before claiming a film plays.** It probes the file and answers `direct`
  (browser-native), `remux` (ffmpeg copies the video, re-encodes only the audio, emits fragmented MP4) or
  `unsupported` with the codec named. "It is an mp4" proves nothing: Matroska and AC3 are invisible to a
  browser, which is why a raw byte URL is not a playable film.
- **A series is derived from NAMES** (`episodes.py`: `S6E4`, `עונה 3 פרק 12`, `3x12`, `פרק 12`). The same
  episode in two qualities is ONE episode; `/api/series/<chat_id>:<slug>` lists them under `variants`.
  Never re-derive it yourself — a wrong guess files a film as season 1 episode 1.
- **Artwork is generated in the BACKGROUND**, never inside a request (one frame is ~40s of ffmpeg, and
  the console proxy times out at 40s). `/api/poster/<id>` answers an intentional placeholder tile while
  it is pending (`X-TV-Poster: pending`); `POST /api/artwork/ensure/<id>` moves one film to the front.
- **`/api/cache` is the local copy of watched content** (LRU, `TV_CACHE_BYTES`); it is what makes a seek
  instant on a ~1 MiB/s link, and `POST /api/prefetch/<id>` warms it for the NEXT episode. Safe to lose.
- **A sync is a JOB**: `refresh` returns at once; poll `/api/sync/status`. `remaining` = chats owed to the
  next run (the scan ROTATES), `peeked` = dialogs whose "has films" answer was refreshed (cached for
  `TV_PEEK_REFRESH_HOURS`; `{"full":true}` ignores the cache).
- **The sync is paced on purpose** — Telegram throttles per account (measured: 14s flood sleeps) — so
  there is a pause between reads, only channels and groups are recorded, and `TV_SYNC_MAX_CHATS` (15)
  chats are read per run. Raising the cap makes the account throttled, not the library faster.
- **A scan is authoritative for the window it read**: the most recent `TV_SYNC_LIMIT` messages replace
  that chat's row, so an older film disappears. Raise the limit for a series chat (`scan_limit` per chat)
  rather than expecting a merge.
- **A chat discovered with video is switched on automatically; a chat a PERSON toggled carries
  `enabled_locked` and is never overruled.** Never flip `enabled` yourself — the settings screen is his.
- **Adopting a chat by hand is the door for what discovery skips** (a bot, a private chat):
  `POST /api/chats/adopt`, `GET /api/dialogs?q=…` searches the whole account live including those kinds,
  `POST /api/chats/<id>/scan` scans ONE chat now instead of waiting for the rotation.
- **`/api/chats/<id>/history` settles "my channel has more episodes than the app shows"**: it reports how
  many messages one read reaches and how many carry video. A bot chat is often tiny — its history is what
  the bot still has, not what once existed.
- **A sticker is not a film**: files under `TV_MIN_MOVIE_BYTES` (2 MiB) and `DocumentAttributeSticker`
  documents are dropped. Do not lower that floor to "find more films" — it finds sticker packs.
- **Deep links**: `?play=<id>&t=<seconds>` opens a film, `?series=<key>` opens a show.
- **One account is active at a time** (`/data/active.json`); an op never falls back to another instance.
  Deleting the instance removes the LOGIN, not the films — and may leave an entry in Telegram's own
  Devices screen for the owner to terminate.
