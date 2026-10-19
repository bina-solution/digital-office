"""library — the app's runtime: the live Telegram client, the sync job, the login wizard, and the
bytes the browser asks for.

Three things are worth understanding before changing this file.

1. ONE CLIENT, LAZILY. A Telegram client costs a login and a connection; it is created on the first
   request that needs it and dropped when the active account changes. Nothing here runs at import
   time, so a deployment with no Telegram account still starts, still answers /healthz, and shows the
   connection screen instead of crash-looping.

2. THE SYNC IS A JOB, NOT A REQUEST. Discovering dialogs and reading a few hundred messages per
   channel takes minutes on a real library, so `POST /api/sync` starts a background task and the UI
   polls /api/sync/status. A request that awaited it would be killed by the console's 40-second proxy
   timeout (see platform-base/console/app.py) — the sync would "work at the app's own origin and
   silently fail inside the console", which is the exact failure the platform already paid for once.

3. THE BYTES ARE STREAMED. `stream()` yields a byte range straight from Telegram. Nothing is written
   to disk and no film is downloaded twice.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time

import requests
import segno
from telethon import TelegramClient
from telethon.errors import (FileReferenceExpiredError, FileReferenceInvalidError,
                             PhoneCodeInvalidError, PhoneCodeExpiredError, SessionPasswordNeededError)
from telethon.sessions import StringSession

import accounts
import episodes as episodes_mod
import scrapers
from artwork import Artwork, ArtworkQueue
from cache import Cache
from tvclient import TvClient, TvError

log = logging.getLogger("telegram-tv.library")

DISCOVER_LIMIT = int(os.environ.get("TV_DISCOVER_LIMIT", "30"))
SYNC_LIMIT = int(os.environ.get("TV_SYNC_LIMIT", "400"))
DIALOG_LIMIT = int(os.environ.get("TV_DIALOG_LIMIT", "500"))
#: How many chats ONE sync reads films from. Telegram throttles per-account, and a library can easily
#: hold hundreds of channels; the cap makes a sync finish and the rotation (store.chats_to_scan) makes
#: the next one continue where this one stopped instead of re-reading the same head. 0 = no cap.
SYNC_MAX_CHATS = int(os.environ.get("TV_SYNC_MAX_CHATS", "40"))
#: How long a discovery peek stays valid. Re-peeking every dialog on every sync is what earns a
#: FloodWait; a week is short enough that a channel which starts posting films is noticed, and long
#: enough that an ordinary sync reads nothing but the chats it is going to scan anyway.
PEEK_REFRESH_HOURS = float(os.environ.get("TV_PEEK_REFRESH_HOURS", "168"))
#: Pause between two Telegram reads. Deliberate: the flood limit is per account and the penalty is a
#: 14-60s sleep in the middle of a sync (measured), so pacing costs less time than being throttled.
REQUEST_PAUSE = float(os.environ.get("TV_REQUEST_PAUSE", "0.7"))
#: Dialog kinds worth recording at all — channels and groups publish catalogues, private chats do not.
DISCOVER_KINDS = os.environ.get("TV_DISCOVER_KINDS", "channel,group")
#: How many frames a chat may add to the artwork queue per scan. Bounded because each one costs ~40s
#: of decode: a 100-episode series fills its shelf over a few minutes instead of owning the CPU.
ARTWORK_PER_CHAT = int(os.environ.get("TV_ARTWORK_PER_CHAT", "6"))
POSTER_DIR = os.environ.get("TV_POSTER_DIR", "/data/posters")
ARTWORK_DIR = os.environ.get("TV_ARTWORK_DIR", "/data/artwork")
#: Default api credentials, used only when the owner does not supply their own in the wizard. They
#: are the ones the Android original shipped with (its own author's app registration); a Telegram
#: api_id is a client identity, not a secret, but an owner who has one of their own should use it.
DEFAULT_API_ID = int(os.environ.get("TV_DEFAULT_API_ID", "414329"))
DEFAULT_API_HASH = os.environ.get("TV_DEFAULT_API_HASH", "af17b872310e6467fcd3d0aa82dc0d56")


class Library:
    def __init__(self, store):
        self.store = store
        self._client: TvClient | None = None
        self._client_instance: str | None = None
        self._client_lock = asyncio.Lock()
        self.artwork = Artwork(ARTWORK_DIR)
        self.artwork_queue: ArtworkQueue | None = None      # set once the app exists (needs raw_url)
        self.cache = Cache(store, self)
        self._job: dict = {"state": "idle"}
        #: The application's event loop, captured at startup. A job must be created ON that loop —
        #: `asyncio.create_task` from a threadpool thread (which is where FastAPI runs a plain `def`
        #: route) raises "no running event loop", and the sync silently never happened while the
        #: request returned 500. Scheduling through the captured loop makes that impossible whichever
        #: thread asks for a sync.
        self._loop: asyncio.AbstractEventLoop | None = None
        self._me = None
        self._me_at = 0.0

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    # ── the live client ──────────────────────────────────────────────────────────────────────
    async def client(self) -> TvClient:
        """The client for the ACTIVE account, recreated when the active account changes."""
        inst, secret, reason = accounts.resolve()
        if reason or inst is None or not secret:
            raise TvError(reason or "לא הוגדר חשבון טלגרם — יש להתחבר")
        wanted = inst["id"]
        async with self._client_lock:
            if self._client is not None and self._client_instance == wanted:
                return self._client
            if self._client is not None:
                await self._client.stop()
                self._client = None
            client = TvClient(int(secret.get("api_id") or DEFAULT_API_ID),
                              str(secret.get("api_hash") or DEFAULT_API_HASH),
                              str(secret.get("session") or ""), label=inst.get("label") or wanted)
            await client.start()
            self._client, self._client_instance = client, wanted
            return client

    async def drop_client(self) -> None:
        async with self._client_lock:
            if self._client is not None:
                await self._client.stop()
            self._client, self._client_instance = None, None

    async def status(self) -> dict:
        """What the header chip shows. A failure here is REPORTED, never raised: the UI must be able
        to render "the session is broken" instead of an error page."""
        inst, secret, reason = accounts.resolve()
        out = {"instance": (inst or {}).get("id"), "label": (inst or {}).get("label"),
               "account_hint": (inst or {}).get("account_hint"), "ok": False, "reason": reason,
               "counts": self.store.counts(), "last_sync": self.store.meta_get("last_sync"),
               "job": dict(self._job)}
        if inst is None or not secret:
            return out
        try:
            client = await self.client()
            # `me()` is a network round trip (measured 3-5s on this link) and the UI polls /api/status;
            # the account's own identity does not change, so it is fetched once per five minutes.
            now = time.time()
            if not self._me or now - self._me_at > 300:
                self._me, self._me_at = await client.me(), now
            me = self._me
            out.update(ok=True, reason=None,
                       user=({"id": getattr(me, "id", None),
                              "username": getattr(me, "username", None),
                              "name": " ".join(x for x in [getattr(me, "first_name", None),
                                                           getattr(me, "last_name", None)] if x)}) if me else None)
        except Exception as e:                               # noqa: BLE001
            out["reason"] = str(e) or type(e).__name__
        return out

    # ── the sync job ─────────────────────────────────────────────────────────────────────────
    def job(self) -> dict:
        return dict(self._job)

    def start_sync(self, *, full: bool = False, only_chat: int | None = None) -> dict:
        if self._job.get("state") == "running":
            return self.job()
        self._job = {"state": "running", "phase": "מתחיל", "started": int(time.time()),
                     "chat": "", "index": 0, "total": 0, "movies": 0, "error": None,
                     "scanned": 0, "remaining": 0, "peeked": 0, "skipped": 0, "capped": False}
        self._spawn(self._run_sync(full=full, only_chat=only_chat))
        return self.job()

    def _spawn(self, coro) -> None:
        """Run a job on the application's loop, from whichever thread asked for it."""
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(lambda: asyncio.ensure_future(coro))
            return
        asyncio.ensure_future(coro)                          # already on a loop (tests, startup)

    async def _run_sync(self, *, full: bool, only_chat: int | None = None) -> None:
        """The sync job.

        `only_chat` scans ONE chat and nothing else — the answer to "I just adopted a channel, show me
        its films". Waiting for the rotation would mean up to forty other chats being read first, and
        that is exactly the kind of wait that makes a person close the tab."""
        job = self._job
        try:
            client = await self.client()
            if only_chat is not None:
                chat = self.store.chat(only_chat)
                if not chat:
                    raise TvError("הצ׳אט לא נמצא בספרייה")
                job.update(phase="קורא סרטים", total=1, index=0, chat=chat.get("title") or "")
                depth = int(chat.get("scan_limit") or 0) or SYNC_LIMIT
                msgs = await client.history(only_chat, depth)
                sid = chat["scraper"] if (chat["scraper_locked"] and chat["scraper"]) \
                    else scrapers.detect(msgs)
                movies = scrapers.extract(sid, msgs, only_chat, chat.get("title") or "")
                for m in movies:
                    m["account_id"] = self._client_instance or ""
                n = self.store.replace_chat_movies(only_chat, movies)
                self.store.mark_synced(only_chat, movie_count=n, scraper=sid)
                if self.artwork_queue is not None:
                    for row in movies[:ARTWORK_PER_CHAT]:
                        self.artwork_queue.ensure(self.store.movie(row["id"]) or row)
                job.update(index=1, movies=n, scanned=1, phase="הסתיים", state="done",
                           finished=int(time.time()))
                self.store.meta_set("last_sync", int(time.time()))
                return
            job.update(phase="קורא את רשימת הצ׳אטים")
            dialogs = await client.dialogs(limit=DIALOG_LIMIT)
            # Films live in CHANNELS and GROUPS. A private conversation is not a library, and reading
            # one is also the most intrusive request this app could make — so by default only the two
            # kinds that publish a catalogue are even recorded.
            kinds = {k.strip() for k in DISCOVER_KINDS.split(",") if k.strip()}
            dialogs = [d for d in dialogs if not kinds or d["kind"] in kinds]
            for d in dialogs:
                self.store.upsert_chat(chat_id=d["chat_id"], account_id=self._client_instance or "",
                                       title=d["title"], kind=d["kind"], username=d["username"])
            # Housekeeping: drop the dialogs this app does not library, so the settings screen lists
            # channels and groups and the peek cache is not spent on private conversations.
            dropped = self.store.prune_kinds(kinds)
            if dropped:
                log.info("pruned %d dialog(s) outside %s", dropped, ",".join(sorted(kinds)))

            # ── discovery: which chats actually publish video ────────────────────────────────
            #
            # Cached by `peeked_at`, because re-reading every dialog on every sync is what earns a
            # FloodWait from Telegram — measured on this deployment: 500 dialogs at ~8s each with
            # `Sleeping for 14s on GetHistoryRequest flood wait` in the log. A `full` sync ignores the
            # cache; an ordinary one only looks at chats whose peek has gone stale (and at chats never
            # peeked, which is every new one).
            cutoff = 0 if full else int(time.time()) - PEEK_REFRESH_HOURS * 3600
            to_peek = self.store.chats_to_peek(older_than=cutoff)
            job.update(phase="בודק מה יש בכל צ׳אט", total=len(to_peek), index=0, skipped=0)
            for i, chat in enumerate(to_peek):
                job.update(index=i + 1, chat=chat["title"] or str(chat["chat_id"]))
                try:
                    msgs = await client.history(chat["chat_id"], DISCOVER_LIMIT)
                except Exception as e:                       # noqa: BLE001 - one bad chat, not a bad sync
                    log.warning("discovery failed for %s: %s", chat["chat_id"], e)
                    continue
                self.store.mark_discovered(chat["chat_id"],
                                           has_video=any(m.kind == "video" for m in msgs))
                job["peeked"] = job.get("peeked", 0) + 1
                await asyncio.sleep(REQUEST_PAUSE)           # stay under the flood limit, see below

            # ── reindex: derive episode coordinates for rows scanned before episodes.py existed ──
            #
            # Pure name parsing, no network: it rescues a whole series library (the Friends bot's 104
            # episodes were already sitting in the store as loose files) in milliseconds, instead of
            # waiting for a re-read that costs a flood-limited history call.
            job.update(phase="מזהה סדרות ופרקים", total=0, index=0, chat="")
            job["reindexed"] = self.reindex_episodes()

            # ── the scan: per-run cap, rotating ─────────────────────────────────────────────
            wanted, remaining = self.store.chats_to_scan(SYNC_MAX_CHATS)
            job.update(phase="קורא סרטים", total=len(wanted), index=0, chat="",
                       remaining=remaining, capped=bool(remaining))
            for i, chat in enumerate(wanted):
                job.update(index=i + 1, chat=chat["title"] or str(chat["chat_id"]))
                try:
                    depth = int(chat.get("scan_limit") or 0) or SYNC_LIMIT
                    msgs = await client.history(chat["chat_id"], depth)
                    sid = chat["scraper"] if (chat["scraper_locked"] and chat["scraper"]) \
                        else scrapers.detect(msgs)
                    movies = scrapers.extract(sid, msgs, chat["chat_id"], chat.get("title") or "")
                    for m in movies:
                        m["account_id"] = self._client_instance or ""
                    n = self.store.replace_chat_movies(chat["chat_id"], movies)
                    if self.artwork_queue is not None:
                        for row in movies[:ARTWORK_PER_CHAT]:
                            self.artwork_queue.ensure(self.store.movie(row["id"]) or row)
                    self.store.mark_synced(chat["chat_id"], movie_count=n, scraper=sid)
                    job["movies"] = job.get("movies", 0) + n
                    job["scanned"] = job.get("scanned", 0) + 1
                except Exception as e:                       # noqa: BLE001
                    log.warning("scan failed for %s: %s", chat["chat_id"], e)
                    job["error"] = f"{chat['title']}: {e}"
                await asyncio.sleep(REQUEST_PAUSE)
            self.store.meta_set("last_sync", int(time.time()))
            job.update(state="done", phase="הסתיים", finished=int(time.time()))
        except asyncio.CancelledError:
            job.update(state="cancelled", phase="בוטל")
            raise
        except Exception as e:                               # noqa: BLE001
            log.warning("sync failed: %s", e, exc_info=True)
            job.update(state="error", phase="שגיאה", error=str(e), finished=int(time.time()))

    def reindex_episodes(self) -> int:
        """Fill in {series, season, episode, quality} for rows that have none, from their titles.

        Returns how many rows changed. Called at the start of every sync because it is free and
        idempotent, and because the alternative — asking the owner to wait for a full re-read before he
        can see that his series became a series — is not a trade this app gets to make."""
        changed = 0
        for row in self.store.movie_ids_missing_episodes():
            chat = self.store.chat(row.get("chat_id")) if row.get("chat_id") else None
            info = episodes_mod.parse(row.get("title", ""), row.get("file_name", ""),
                                      fallback_series=(chat or {}).get("title", ""))
            if not info.is_episode:
                continue
            self.store.set_episode_fields(
                row["id"], series=info.series, series_key=episodes_mod.series_key(
                    int(row.get("chat_id") or 0), info.series),
                season=info.season, episode=info.episode, quality_label=info.quality)
            changed += 1
        if changed:
            log.info("reindexed %d row(s) into series", changed)
        return changed

    # ── bytes for the browser ────────────────────────────────────────────────────────────────
    async def stream(self, movie: dict, start: int, length: int):
        """The requested byte range, with ONE retry after refreshing an expired file reference.

        Telegram's file references expire; the failure surfaces as the film stopping mid-playback,
        which looks like a broken film rather than a stale reference. Refetching the message once and
        continuing is the difference between "sometimes the player dies" and "it just works"."""
        client = await self.client()
        try:
            media = await client.media_for(movie)
            async for chunk in client.iter_range(media, start, length):
                yield chunk
            return
        except (FileReferenceExpiredError, FileReferenceInvalidError):
            client.forget_media(movie["id"])
            media = await client.media_for(movie)
            async for chunk in client.iter_range(media, start, length):
                yield chunk

    async def poster(self, movie: dict) -> bytes | None:
        """Artwork for a card, in four steps of decreasing luck.

        1. A frame generated from the film itself (artwork.py) — checked FIRST, because it is the one
           that exists for a series episode delivered as a plain document.
        2. The poster Telegram holds: a photo message the scraper linked, or the video's thumbnail.
        3. Nothing yet, but a frame is QUEUED — return nothing WITHOUT remembering it as "no poster",
           so the client's retry picks it up when the decoder is done.
        4. Nothing, attempted and impossible (no video stream at all) — remembered for a few hours.

        The distinction between (3) and (4) is the whole function: the first version wrote the same
        marker for both, so every film whose artwork had merely been queued was remembered as
        posterless and stayed grey forever."""
        os.makedirs(POSTER_DIR, exist_ok=True)
        mid = movie["id"]
        path = os.path.join(POSTER_DIR, re.sub(r"[^A-Za-z0-9_-]", "_", mid) + ".jpg")
        miss = path + ".miss2"
        try:
            if os.path.exists(path):
                with open(path, "rb") as fh:
                    return fh.read()
        except OSError:
            pass
        if self.artwork.has_poster(mid):
            try:
                with open(self.artwork.poster_path(mid), "rb") as fh:
                    return fh.read()
            except OSError:
                pass
        if self.artwork.failed(mid):
            return None
        try:
            if os.path.exists(miss) and time.time() - os.path.getmtime(miss) < 6 * 3600:
                return None
        except OSError:
            pass
        data = None
        try:
            data = await (await self.client()).thumb_bytes(movie)
        except Exception as e:                               # noqa: BLE001
            log.warning("poster for %s failed: %s", mid, e)
        if data:
            try:
                with open(path, "wb") as fh:
                    fh.write(data)
            except OSError:
                pass
            return data
        if self.artwork_queue is not None:
            # queued, not hopeless: no marker, so the client's retry finds the real still later
            self.artwork_queue.ensure(movie)
            return None
        try:
            open(miss, "wb").close()
        except OSError:
            pass
        return None

    def raw_url(self, movie: dict) -> str:
        """What ffmpeg should read for this film: the CACHED FILE when it is on disk, the app's own
        range endpoint otherwise.

        The difference is not cosmetic. Over HTTP, seeking to 6% of a 700 MB episode means asking
        Telegram for megabytes and waiting for them (measured: ~40 seconds per generated poster).
        Off a local file it is a `seek()` — the same frame in well under a second, and no network at
        all. Artwork and remuxing both go through here, so both get faster for anything played once."""
        try:
            if self.cache.complete(movie):
                return self.cache.path(movie)
        except Exception:                                    # noqa: BLE001 - fall back to HTTP
            pass
        return f"{os.environ.get('TV_SELF_URL', 'http://127.0.0.1:8982').rstrip('/')}/api/raw/{movie['id']}"

    async def record_probe(self, movie: dict, info: dict) -> None:
        """Persist the duration/resolution ffprobe found, so the UI has a progress bar."""
        if not info:
            return
        self.store.set_media_info(movie["id"], duration=int(info.get("duration") or 0),
                                  width=int(info.get("width") or 0), height=int(info.get("height") or 0))


# ── the login wizard ─────────────────────────────────────────────────────────────────────────

class LoginWizard:
    """One wizard at a time, deliberately.

    Two concurrent logins would create two Telegram authorisations, two instances in the vault and an
    ambiguous "which one is active" — for a flow a person runs once. Refusing the second start with a
    sentence is better than a race nobody can see.

    The wizard holds the Telegram client for the duration of the login and never touches the vault
    until the login SUCCEEDS: a half-finished login must not leave an unusable account behind."""

    def __init__(self, library: Library):
        self.library = library
        self.state: dict = {"step": "idle", "mode": None, "phone": "", "qr_svg": None,
                            "error": None, "hint": None, "started": 0}
        self._client = None
        self._task = None

    def snapshot(self) -> dict:
        s = dict(self.state)
        s.pop("_internal", None)
        return s

    async def start(self, *, mode: str, api_id=None, api_hash=None, phone: str = "") -> dict:
        if self.state["step"] in ("qr", "code", "password"):
            return {"error": "תהליך התחברות כבר פעיל — בטלו אותו כדי להתחיל מחדש"}
        await self._reset()
        api_id = int(api_id or DEFAULT_API_ID)
        api_hash = str(api_hash or DEFAULT_API_HASH)
        self.state = {"step": "starting", "mode": mode, "phone": phone, "qr_svg": None,
                      "error": None, "hint": None, "started": int(time.time())}
        try:
            self._client = TelegramClient(StringSession(), api_id, api_hash,
                                          device_model="Bina office", system_version="Linux",
                                          app_version="telegram-tv 0.1", lang_code="he",
                                          flood_sleep_threshold=120)
            await self._client.connect()
            if mode == "qr":
                qr = await self._client.qr_login()
                self.state.update(step="qr", qr_svg=segno.make(qr.url, error="l").svg_data_uri(
                    scale=6, dark="#1f2a17", light="#ffffff"), hint=_qr_hint(qr))
                self._task = asyncio.create_task(self._qr_loop(qr))
            else:
                sent = await self._client.send_code_request(phone)
                self.state.update(step="code", phone=phone, hint=getattr(sent, "type", None) and
                                  "הקוד נשלח. אפשר למלא אותו כאן.")
        except Exception as e:                               # noqa: BLE001
            log.warning("login start failed: %s", e, exc_info=True)
            self.state.update(step="failed", error=_login_error(e))
        return self.snapshot()

    async def _qr_loop(self, qr) -> None:
        """Wait for the phone to approve the QR, and refresh the token the moment it expires.

        The refresh is not optional and its TIMING is not optional either: an expired QR imports
        nothing, so a token that is displayed a few seconds past its expiry is a login screen that
        simply never works — measured on this stack, the first implementation waited on the library's
        own timeout and left an expired code on screen for ~20 seconds per cycle. So the wait is
        bounded by the token's OWN `expires`, and every return that is not a success is followed by a
        recreate."""
        while True:
            left = _seconds_left(qr)
            try:
                await qr.wait(timeout=max(1.0, left + 2))
            except asyncio.TimeoutError:
                pass                                          # expired: fall through and refresh
            except Exception as e:                            # noqa: BLE001
                self.state.update(step="failed", error=_login_error(e))
                return
            else:
                await self._finish()
                return
            try:
                await qr.recreate()
                self.state["qr_svg"] = segno.make(qr.url, error="l").svg_data_uri(
                    scale=6, dark="#1f2a17", light="#ffffff")
                self.state["hint"] = _qr_hint(qr)
            except Exception as e:                            # noqa: BLE001
                self.state.update(step="failed", error=_login_error(e))
                return

    async def code(self, code: str) -> dict:
        if self.state.get("step") != "code" or self._client is None:
            return {"error": "אין שלב קוד פעיל"}
        try:
            await self._client.sign_in(phone=self.state["phone"], code=str(code).strip())
        except SessionPasswordNeededError:
            self.state.update(step="password", error=None, hint="לחשבון יש סיסמת אימות דו-שלבי.")
        except (PhoneCodeInvalidError, PhoneCodeExpiredError) as e:
            self.state.update(error="הקוד שגוי או שפג תוקפו — נסו שוב או בקשו קוד חדש")
            log.info("code rejected: %s", e)
        except Exception as e:                               # noqa: BLE001
            self.state.update(step="failed", error=_login_error(e))
            return self.snapshot()
        if self.state.get("step") == "code":
            await self._finish()
        return self.snapshot()

    async def password(self, password: str) -> dict:
        if self.state.get("step") != "password" or self._client is None:
            return {"error": "אין שלב סיסמה פעיל"}
        try:
            await self._client.sign_in(password=password)
            await self._finish()
        except Exception as e:                               # noqa: BLE001
            self.state.update(error=_login_error(e))
        return self.snapshot()

    async def cancel(self) -> dict:
        await self._reset()
        self.state = {"step": "idle", "mode": None, "phone": "", "qr_svg": None, "error": None,
                      "hint": None, "started": 0}
        return self.snapshot()

    async def _reset(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:                                # noqa: BLE001
                pass
            self._client = None

    async def _finish(self) -> None:
        """The login succeeded: mint the vault instance, make it active, and drop the temporary
        client. This is the only place that writes a session string anywhere."""
        client = self._client
        try:
            session = client.session.save()
            me = await client.get_me()
        except Exception as e:                               # noqa: BLE001
            self.state.update(step="failed", error=_login_error(e))
            return
        phone = self.state.get("phone") or ""
        hint = phone or (f"@{me.username}" if getattr(me, "username", None) else "")
        name = " ".join(x for x in [getattr(me, "first_name", None), getattr(me, "last_name", None)] if x)
        label = name or hint or "טלגרם"
        instance_id, err = accounts.create_instance(
            protocol=accounts.PROTOCOL, label=label, account_hint=hint,
            secret={"api_id": str(client.api_id), "api_hash": str(client.api_hash),
                    "session": session, "phone": phone})
        if err or not instance_id:
            self.state.update(step="failed", error=err or "יצירת החשבון נכשלה")
            return
        accounts.set_active(instance_id)
        await self._reset()
        await self.library.drop_client()
        self.state = {"step": "connected", "mode": None, "phone": phone, "qr_svg": None,
                      "error": None, "hint": f"החשבון {label} מחובר", "started": int(time.time()),
                      "instance": instance_id}
        self.library.start_sync()


def _seconds_left(qr) -> float:
    """Seconds until the QR token expires. Telethon hands back a tz-aware UTC datetime; a naive
    subtraction here would raise on every login and turn the refresh loop into a failed wizard."""
    try:
        from datetime import datetime, timezone
        expires = qr.expires
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return (expires - datetime.now(timezone.utc)).total_seconds()
    except Exception:                                        # noqa: BLE001
        return 25.0


def _qr_hint(qr) -> str:
    left = int(_seconds_left(qr))
    if left <= 1:
        return "הקוד פג — מרענן קוד חדש…"
    return (f"סורקים את הקוד באפליקציית טלגרם (הגדרות → מכשירים → קישור מכשיר). "
            f"הקוד בתוקף עוד {left} שניות ומתחדש מעצמו.")


def _login_error(e: Exception) -> str:
    """Telegram's errors, in Hebrew and actionable. A raw exception in the wizard tells the owner
    nothing they can act on."""
    name = type(e).__name__
    if isinstance(e, (requests.RequestException,)):          # pragma: no cover - network only
        return "אין חיבור לטלגרם מהשרת"
    table = {
        "ApiIdInvalidError": "ה-api_id או ה-api_hash אינם תקינים — אפשר להנפיק אותם ב-my.telegram.org",
        "PhoneNumberInvalidError": "מספר הטלפון אינו תקין — יש להזין אותו עם קידומת מדינה, למשל 972...",
        "PhoneNumberBannedError": "המספר חסום בטלגרם",
        "PhoneNumberUnoccupiedError": "אין חשבון טלגרם עם המספר הזה",
        "PasswordHashInvalidError": "סיסמת האימות הדו-שלבי שגויה",
        "FloodWaitError": "טלגרם הגביל את הקצב — יש לנסות שוב בעוד כמה דקות",
        "AuthKeyUnregisteredError": "ההרשאה בוטלה בטלגרם — יש להתחבר מחדש",
        "UserDeactivatedBanError": "החשבון חסום בטלגרם",
    }
    for key, msg in table.items():
        if key.lower() in name.lower() or key.lower() in str(e).lower():
            return msg
    return f"{name}: {e}"[:300]
