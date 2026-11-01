# telegram-tv

The office version of **[solomonBoltin/TelegramTv](https://github.com/solomonBoltin/TelegramTv)** — an
Android TV client (Kotlin/Jetpack Compose + TDLib) that treats Telegram as a film library: every chat
is a row, every video message is a film, and a *scraper* turns a channel's posting habits into a
catalogue with posters, years and ratings.

This app is that same idea running inside the office: reached at `/a/telegram-tv/` behind the office
SSO, driven in the browser instead of on a TV, with the login held by the platform's credential plane
rather than by the app.

## What was ported, and what was not

| The original | Here | Why it changed |
|---|---|---|
| `ChatScrapper` / `MovieScrapper` (`DefaultChatScrapper`, `AmsalemChatScrapper`) | `scrapers.py` — `default`, `album`, `amsalem` | The pattern is kept, including the Hebrew field regexes. The original addressed a film's neighbours by arithmetic on the message id (`id - 1048576*3`), which only works inside one channel's private numbering; here the neighbours are found by walking back through the messages, and the album (`grouped_id`) is honoured when Telegram supplies one. |
| Channel detection by title containing „amsalem” | detection by the messages themselves (`scrapers.detect`) | A format is not a channel. The same poster format posted anywhere is now parsed by the same scraper. |
| TDLib + ExoPlayer `TelegramVideoSource` (random access into a file) | `tvclient.iter_range` + HTTP `Range` in `app.py` | A browser needs an HTTP server that answers `Range:` by pulling those exact bytes from Telegram. That is what makes seeking work without downloading a 4 GB film first. |
| `MovieDa` (Room) as the catalogue | `store.py` (sqlite) — a cache, not the source of truth | The films are in Telegram. Nothing here is worth a backup beyond a re-scan. |
| TDLib session in app-private storage | a `telegram_user` connection instance in the vault | A session string is a full login; it lives in the credential plane, where the office can list, test and revoke it — and the app holds no copy. |
| Netflix-shaped `MovieDashUI` | `static/` — rows of cards, search, resume, a full-screen player | Same shape, web: rows per chat, hover cards, `המשך צפייה`, and positions kept in the browser's own storage. |

## Playing well is a feature (added after measuring)

Three measurements decided the playback design, and they are the reason the app does not simply point a
`<video>` at Telegram's bytes:

| measured | consequence |
|---|---|
| most channels publish **Matroska**, and much of the rest has **AC3/E-AC3 audio** | a browser cannot open either. `/api/play/<id>` runs `ffprobe` and answers `direct` (play the bytes as they are), `remux` (ffmpeg copies the video, re-encodes only the soundtrack, emits fragmented MP4) or `unsupported` with the codec named — never a black rectangle |
| a Telegram download from this office runs at **0.9–1.6 MiB/s**, while a 1080p episode plays at 4.3 Mbit/s | episodes ship in several qualities; the player starts at the best and DROPS a level by itself if the stream stalls. `cache.py` keeps what was played on disk (LRU, 3 GB), and the **next episode is prefetched while the current one plays** — the only way auto-play starts instantly on this link |
| generating one artwork frame takes ~40s of ffmpeg seek+decode | artwork is never produced inside a request (the console proxy times out at 40s). A background queue generates 640×960 posters **and** 1600px backdrops from the film's own frames; until then the card gets an intentional placeholder tile, and the client re-asks until the real still arrives |

Series are recognised from the names (`episodes.py`): `S6E4`, `עונה 3 פרק 12`, `3x12`… become
`{series, season, episode, quality}`, the two qualities of one episode collapse into ONE card with a
quality switch, and the shelf gets "המשך צפייה", watched ticks, progress bars, next-episode auto-play
and resume — the things that make a pile of files a TV.

## The flow

1. **Connect** — open the app, scan the QR with Telegram (Settings → Devices → Link Desktop Device) or
   enter the phone number and the code Telegram sends. 2FA is asked for when the account has it.
2. **The wizard mints a `telegram_user` instance** in the credential plane (api_id, api_hash, session
   string, phone) and makes it the active account. Nothing is written to the app's own files.
3. **Sync** (background job) — reads the dialogs, peeks at each one to see whether it has films,
   enables the ones that do, then reads up to `TV_SYNC_LIMIT` messages of each enabled chat and runs
   the scraper.
4. **Watch** — the player asks `/api/stream/<id>` with a byte range; the server pulls that range from
   Telegram and streams it back.

## Files

```
app.py         FastAPI: the platform surface (/manifest, /ops, /connections, /readyz), the library
               API, HTTP Range streaming, poster bytes, and the UI
accounts.py    this app's view of the credential plane (instances, active binding)
library.py     the live client, the sync job, the login wizard, the byte/posters cache
tvclient.py    Telethon: dialogs, history, random-access ranges, thumbnails
scrapers.py    the pure parsing layer (messages in, movies out) — the part to unit-test
store.py       sqlite catalogue cache: chats, movies, meta
static/        the screen: rows, search, settings drawer, player, connection wizard
```

## Operating

```bash
./bbox apps enable telegram-tv
./scripts/dc up -d --build telegram-tv
./scripts/dc logs --tail 50 telegram-tv
curl -s http://telegram-tv:8982/readyz          # 200 only when an account is connected
```

Knobs that matter (all overridable in `.env`), and why they exist:

| Variable | Default | Why |
|---|---|---|
| `TV_SYNC_LIMIT` | 400 | how many recent messages of a chat one scan reads; the scan is authoritative for that window |
| `TV_SYNC_MAX_CHATS` | 40 | how many chats ONE sync reads films from. Telegram throttles per account (measured: 14s flood sleeps), so a sync is capped and the next one ROTATES — it continues with the chats this one did not reach instead of re-reading the same head |
| `TV_PEEK_REFRESH_HOURS` | 168 | how long the "does this chat have films" answer stays valid. Re-peeking every dialog on every sync is what earns the flood waits |
| `TV_REQUEST_PAUSE` | 0.7 | seconds between two Telegram reads; cheaper than being throttled |
| `TV_DISCOVER_KINDS` | `channel,group` | which dialogs are recorded at all — private chats do not publish catalogues |
| `TV_STREAM_WINDOW` | 16 MiB | the largest slice one HTTP range response carries |
| `TV_DEFAULT_API_ID` / `TV_DEFAULT_API_HASH` | the original app's pair | used only when the owner does not supply his own in the wizard |
| `TV_CACHE_BYTES` | 3 GiB | how much played content is kept on disk (LRU). This is what makes seeks and rewatches instant |
| `TV_CACHE_MAX_FILE` | 400 MiB | files up to this size are cached whole; a 4 GB film is streamed instead |
| `TV_MAX_SESSIONS` / `TV_SESSION_IDLE_SECONDS` | 3 / 45 | ffmpeg remux sessions: how many may exist, and when an abandoned one is killed |
| `TV_ARTWORK_CONCURRENCY` / `TV_ARTWORK_PER_CHAT` | 1 / 6 | how hard the frame generator may work; it pauses entirely while a sync runs |
| `TV_AUTOSYNC_HOURS` | 6 | boot starts a sync only if the library is this stale (a rebuild used to trigger a full rotation) |

The app's own brief for the office agent is `AGENT.md` (declared in `app.json`), so the agent learns
these ops and traps on every session without anything else being edited.
