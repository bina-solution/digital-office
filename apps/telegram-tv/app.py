"""telegram-tv — the office's Telegram film library, on a screen that is not a phone.

WHAT THIS IS. The Android original (github.com/solomonBoltin/TelegramTv) is a TV client that treats
Telegram as a film library: every chat is a row, every video message in it is a film, and a scraper
turns a channel's posting habits into a catalogue with posters, years and ratings. This app is that
idea as an office app — same scrapers, same rows-of-cards shape, but it runs in the office, is reached
at /a/telegram-tv/ behind the office SSO, holds its login in the credential plane, and plays through
the browser instead of ExoPlayer.

The three parts that are NOT a port, and why:

  * A USER SESSION IN A VAULT. The original kept a TDLib session in app-private storage on the TV.
    Here the session string is a connection instance of protocol `telegram_user` (accounts.py), so
    the office can list it, test it, and remove it — and the app itself holds no login at all.
  * RANGE STREAMING OVER HTTP. TDLib + ExoPlayer gave the original random access for free. A browser
    needs an HTTP server that answers `Range:` requests by pulling *those* bytes from Telegram
    (tvclient.iter_range), which is what makes seeking work without downloading a 4 GB film first.
  * A SYNC AS A JOB. A library that takes minutes to read must not be a request (see library.py).

The app owns no capability it forces on anyone; it PROVIDES one (`tv`) so another app or the office
agent can list what is in the library, and it consumes only the credential plane and the SSO the
platform already gives every app.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

import accounts
import episodes
import scrapers
from artwork import ArtworkQueue
from library import DIALOG_LIMIT, DEFAULT_API_HASH, DEFAULT_API_ID, Library, LoginWizard
from botfetch import BotFetch
from player import Players
from store import Store
from tvclient import TvError

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("telegram-tv")

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, "static")
DATA_DIR = os.environ.get("TV_DATA_DIR", "/data")
#: How many bytes one HTTP range response may carry. Browsers open a film with an open-ended range
#: (`bytes=0-`); honouring that literally means pulling the whole file through this process before
#: the player has decoded a frame. Answering with a bounded sub-range is legal HTTP, and the player
#: simply asks for the next window — which is what makes the first frame appear in a second.
STREAM_WINDOW = int(os.environ.get("TV_STREAM_WINDOW", str(16 * 1024 * 1024)))
#: Auto-sync on boot only if the library is at least this stale. Without it, every rebuild of this
#: container started a full rotation — forty channels read from Telegram — for nothing.
AUTOSYNC_HOURS = float(os.environ.get("TV_AUTOSYNC_HOURS", "6"))
#: How the app reaches ITSELF. ffmpeg is given this URL rather than bytes from a pipe: ffmpeg seeks,
#: and a seek is what makes jumping to minute 40 of a film cost a keyframe instead of a download. The
#: loopback hop is deliberate — the endpoint it reads is the same range-capable one the browser uses,
#: so there is exactly ONE implementation of "bytes out of a Telegram message".
SELF_URL = os.environ.get("TV_SELF_URL", "http://127.0.0.1:8982").rstrip("/")

SERVICE_NAME = "telegram-tv"
INTERFACE = "tv.v1"
OPS = ["status", "listChats", "listMovies", "getMovie", "refresh", "streamUrl"]

STORE = Store(os.path.join(DATA_DIR, "library.db"))
LIBRARY = Library(STORE)
LOGIN = LoginWizard(LIBRARY)
PLAYERS = Players(STORE)
BOTFETCH = BotFetch(LIBRARY)
# The artwork queue needs the app's own URL builder, which lives on the library — wired here, once,
# where both exist.
LIBRARY.artwork_queue = ArtworkQueue(LIBRARY.artwork, STORE, LIBRARY.raw_url,
                                     busy=lambda: LIBRARY.job().get("state") == "running")

RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


def parse_range(header: str, size: int, window: int = STREAM_WINDOW):
    """(start, end, partial) for a request against a file of `size` bytes, or None for a 416.

    Pure and separate from the route so the arithmetic can be tested without a client, a film or a
    network — this is the code that decides whether seeking works, and these are the cases a video
    element actually sends:

      `bytes=0-`            the opening request — a window, not the whole film
      `bytes=N-`            a seek: N up to one window
      `bytes=N-M`           a specific chunk (the browser filling its own buffer)
      no header / garbage   the whole file, windowed, answered 200 rather than 206
      N >= size             416 with `Content-Range: bytes */size`, which is what tells a player the
                            film really is that long instead of leaving it on an impossible offset
    """
    size = int(size)
    m = RANGE_RE.match((header or "").strip())
    asked = bool(m and (m.group(1) or m.group(2)))
    if asked:
        start = int(m.group(1) or 0)
        end = int(m.group(2)) if m.group(2) else size - 1
    else:
        start, end = 0, size - 1
    if start < 0 or start >= size:
        return None
    end = min(end, size - 1, start + window - 1)
    return start, end, asked or end < size - 1


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Start the first library read if an account is already connected — but do it in the background
    and tolerate failure: an app that refuses to boot because Telegram is unreachable is an app whose
    connection screen you cannot reach to fix it."""
    async def _warm():
        import asyncio
        await asyncio.sleep(5)
        try:
            inst, secret, reason = accounts.resolve()
            if not (inst and secret):
                return
            last = STORE.meta_get("last_sync") or 0
            age_h = (time.time() - last) / 3600 if last else 999
            if age_h < AUTOSYNC_HOURS:
                log.info("startup sync skipped: last one was %.1fh ago", age_h)
                return
            LIBRARY.start_sync(full=False)
        except Exception as e:                               # noqa: BLE001
            log.info("startup sync not started: %s", e)

    import asyncio
    LIBRARY.attach_loop(asyncio.get_running_loop())
    task = asyncio.create_task(_warm())
    yield
    task.cancel()
    await LIBRARY.drop_client()
    STORE.close()


app = FastAPI(title="telegram-tv", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


# ── projections ──────────────────────────────────────────────────────────────────────────────
def movie_public(row: dict) -> dict:
    """The movie as the UI and other apps see it. URLs are RELATIVE on purpose: the console serves
    this app under /a/<alias>/ and injects a <base>, so a root-absolute URL would escape the mount."""
    return {
        "id": row["id"],
        "chat_id": row["chat_id"],
        "title": row.get("title") or row.get("file_name") or "ללא שם",
        "year": row.get("year") or "",
        "rating": row.get("rating") or "",
        "quality": row.get("quality") or "",
        "tags": [t for t in (row.get("tags") or "").split(",") if t.strip()],
        "description": row.get("description") or "",
        "duration": int(row.get("duration") or 0),
        "size": int(row.get("size") or 0),
        "mime": row.get("mime") or "video/mp4",
        "date": int(row.get("date") or 0),
        "poster": f"api/poster/{row['id']}",
        # the 16:9 still: right for an episode row, a hero banner and the "next episode" card, where a
        # 2:3 poster would be cropped to a sliver
        "backdrop": f"api/backdrop/{row['id']}",
        "series_key": row.get("series_key") or "",
        "series": row.get("series") or "",
        "season": int(row.get("season") or 0),
        "episode": int(row.get("episode") or 0),
        "quality_label": row.get("quality_label") or "",
        "stream": f"api/stream/{row['id']}",
    }


def chat_public(row: dict) -> dict:
    return {"chat_id": row["chat_id"], "title": row.get("title") or str(row["chat_id"]),
            "username": row.get("username") or "", "kind": row.get("kind") or "",
            "enabled": bool(row.get("enabled")), "enabled_locked": bool(row.get("enabled_locked")),
            "has_video": bool(row.get("has_video")),
            "scraper": row.get("scraper") or "", "scraper_locked": bool(row.get("scraper_locked")),
            "movie_count": int(row.get("movie_count") or 0), "synced_at": int(row.get("synced_at") or 0),
            "peeked_at": int(row.get("peeked_at") or 0), "scan_limit": int(row.get("scan_limit") or 0)}


# ── platform surface ─────────────────────────────────────────────────────────────────────────
@app.get("/healthz")
def healthz():
    """Liveness ONLY: the process answers. Whether Telegram is reachable is /readyz, because a
    healthcheck that fails when a login expires puts the container into an autoheal restart loop
    that fixes nothing (and takes the connection screen down with it)."""
    return {"ok": True, "service": SERVICE_NAME, "counts": STORE.counts()}


@app.get("/readyz")
async def readyz():
    status = await LIBRARY.status()
    if not status.get("ok"):
        return JSONResponse(status_code=503, content={"ready": False, "reason": status.get("reason"),
                                                      "instance": status.get("instance")})
    return {"ready": True, "connection_id": status.get("instance")}


@app.get("/manifest")
async def manifest():
    status = await LIBRARY.status()
    return {"service": SERVICE_NAME, "interface": INTERFACE, "ops": OPS,
            "protocols": [accounts.PROTOCOL], "capabilities": {"tv": True},
            "state": {"connection_id": status.get("instance"), "ready": bool(status.get("ok")),
                      "counts": STORE.counts(), "sync": LIBRARY.job()}}


@app.get("/ops")
def ops():
    return {"service": SERVICE_NAME, "interface": INTERFACE, "ops": OPS,
            "params": {"listMovies": "q?, chat_id?, limit?", "getMovie": "id",
                       "streamUrl": "id", "refresh": "full?"}}


# ── accounts (the credential plane, through this app's lens) ─────────────────────────────────
@app.get("/connections")
async def connections():
    insts, err = accounts.list_instances()
    active = accounts.active_id()
    return {"active": active, "connections": insts, "reason": err,
            "defaults": {"api_id": DEFAULT_API_ID, "api_hash_hint": DEFAULT_API_HASH[:6] + "…"}}


@app.post("/connections/select")
async def connections_select(payload: dict):
    instance_id = (payload or {}).get("id")
    if instance_id:
        insts, _ = accounts.list_instances()
        if not any(i.get("id") == instance_id for i in insts):
            raise HTTPException(status_code=404, detail="חשבון לא נמצא")
    accounts.set_active(instance_id)
    await LIBRARY.drop_client()
    if instance_id:
        LIBRARY.start_sync(full=False)
    return {"ok": True, "active": accounts.active_id()}


@app.delete("/connections/{instance_id}")
async def connections_delete(instance_id: str):
    ok, err = accounts.delete_instance(instance_id)
    if not ok:
        raise HTTPException(status_code=502, detail=err or "מחיקת החשבון נכשלה")
    if accounts.active_id() == instance_id:
        accounts.set_active(None)
        await LIBRARY.drop_client()
    return {"ok": True}


# ── login wizard ─────────────────────────────────────────────────────────────────────────────
@app.post("/api/login/start")
async def login_start(payload: dict):
    payload = payload or {}
    mode = (payload.get("mode") or "qr").lower()
    if mode not in ("qr", "phone"):
        raise HTTPException(status_code=400, detail="mode must be qr or phone")
    if mode == "phone" and not (payload.get("phone") or "").strip():
        raise HTTPException(status_code=400, detail="צריך מספר טלפון")
    return await LOGIN.start(mode=mode, api_id=payload.get("api_id"),
                             api_hash=payload.get("api_hash"), phone=(payload.get("phone") or "").strip())


@app.get("/api/login/state")
def login_state():
    return LOGIN.snapshot()


@app.post("/api/login/code")
async def login_code(payload: dict):
    return await LOGIN.code((payload or {}).get("code") or "")


@app.post("/api/login/password")
async def login_password(payload: dict):
    return await LOGIN.password((payload or {}).get("password") or "")


@app.post("/api/login/cancel")
async def login_cancel():
    return await LOGIN.cancel()


# ── library ──────────────────────────────────────────────────────────────────────────────────
@app.get("/api/status")
async def status():
    return await LIBRARY.status()


@app.get("/api/catalog")
def catalog(q: str = "", limit: int = 400):
    """Rows for the TV screen: one row per enabled chat, newest films first. A search hits every
    enabled chat at once and returns a single flat row, because "where was that film" is not a
    question the owner should have to answer."""
    chats = [c for c in STORE.chats(enabled_only=True) if c["movie_count"] or c["has_video"]]
    if q.strip():
        movies = STORE.movies(chat_ids=[c["chat_id"] for c in chats] or None, q=q.strip(),
                              limit=max(1, min(int(limit), 500)))
        return {"rows": [{"chat": {"chat_id": 0, "title": f"חיפוש: {q.strip()}"},
                          "movies": [movie_public(m) for m in movies]}],
                "counts": STORE.counts(), "sync": LIBRARY.job()}
    rows = []
    for c in chats:
        movies = STORE.movies(chat_ids=[c["chat_id"]], limit=max(1, min(int(limit), 500)))
        rows.append({"chat": chat_public(c), "movies": [movie_public(m) for m in movies]})
    return {"rows": [r for r in rows if r["movies"]], "counts": STORE.counts(), "sync": LIBRARY.job()}


@app.get("/api/dialogs")
async def dialogs(q: str = "", limit: int = 60, kinds: str = ""):
    """LIVE search over EVERY dialog on the account — including the kinds the library does not keep.

    Why this exists: the library records channels and groups (see DISCOVER_KINDS in library.py), so a
    film collection that lives inside a private chat, a saved-messages pile or a BOT is invisible to
    the settings screen. The owner can therefore not even see the thing he wants, let alone add it.
    This searches the account itself and reports, per dialog, whether the library already holds it.

    `kinds` narrows the answer (e.g. `kinds=user` for bots and private chats); empty means all.
    """
    client = await LIBRARY.client()
    want = {k.strip() for k in kinds.split(",") if k.strip()}
    ql = q.strip().lower()
    rows = []
    for d in await client.dialogs(limit=DIALOG_LIMIT):
        if want and d["kind"] not in want:
            continue
        if ql and ql not in (d["title"] or "").lower() and ql not in (d["username"] or "").lower():
            continue
        row = STORE.chat(d["chat_id"])
        rows.append({**d, "in_library": bool(row),
                     "enabled": bool(row and row["enabled"]),
                     "movie_count": int(row["movie_count"]) if row else 0})
    rows.sort(key=lambda r: (not r["in_library"], -(r["movie_count"] or 0)))
    return {"dialogs": rows[:max(1, min(int(limit), 200))], "total": len(rows)}


@app.post("/api/chats/adopt")
async def chat_adopt(payload: dict):
    """Take ONE dialog into the library by hand, whatever kind it is.

    This is the door for everything the automatic discovery deliberately skips — a bot that publishes
    episodes, a private channel, a chat whose films are older than the peek window. It is *locked*:
    the library will keep scanning it even when its recent messages contain no video, because a person
    asked for it (store.chats_to_scan).
    """
    payload = payload or {}
    try:
        chat_id = int(payload.get("chat_id"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="צריך chat_id")
    client = await LIBRARY.client()
    found = next((d for d in await client.dialogs(limit=DIALOG_LIMIT) if d["chat_id"] == chat_id), None)
    if not found:
        raise HTTPException(status_code=404, detail="הצ׳אט לא נמצא בחשבון הטלגרם הזה")
    STORE.upsert_chat(chat_id=chat_id, account_id=LIBRARY._client_instance or "",
                      title=found["title"], kind=found["kind"], username=found["username"])
    STORE.mark_discovered(chat_id, has_video=True)
    STORE.set_chat(chat_id, enabled=True, lock_enabled=True)
    LIBRARY.start_sync(full=False)
    return {"ok": True, "chat": chat_public(STORE.chat(chat_id))}


@app.get("/api/chats")
def chats():
    return {"chats": [chat_public(c) for c in STORE.chats()],
            "scrapers": scrapers.choices(),
            "sync": LIBRARY.job()}


@app.post("/api/chats/{chat_id}")
async def chat_update(chat_id: int, payload: dict):
    payload = payload or {}
    if not STORE.chat(chat_id):
        raise HTTPException(status_code=404, detail="צ׳אט לא נמצא — צריך לסנכרן קודם")
    scraper = payload.get("scraper")
    if scraper is not None and scraper not in scrapers.SCRAPERS:
        raise HTTPException(status_code=400, detail="scraper לא מוכר")
    enabled = payload.get("enabled")
    scan_limit = payload.get("scan_limit")
    # `lock_enabled` is what makes a person's choice final: automatic discovery switches a chat on
    # when it finds films, and without this flag the next sync would switch it back on after the owner
    # turned it off (see store.mark_discovered).
    STORE.set_chat(chat_id, enabled=None if enabled is None else bool(enabled),
                   scraper=scraper if scraper else None,
                   lock_scraper=True if scraper else None,
                   lock_enabled=True if enabled is not None else None,
                   scan_limit=None if scan_limit is None else int(scan_limit))
    if enabled is False:
        STORE.forget_chat_movies(chat_id)         # switching a chat off removes its films from the UI
    elif enabled is True or scraper:
        LIBRARY.start_sync(full=False)
    return {"ok": True, "chat": chat_public(STORE.chat(chat_id))}


@app.get("/api/chats/{chat_id}/history")
async def chat_history_stats(chat_id: int, limit: int = 0, dump: int = 0):
    """What is actually IN a chat: how many messages one read reaches, how many of them carry video, and
    the id/date span they cover.

    This exists because "my channel has 236 episodes but the app shows 51" has three possible causes
    that look identical from the outside — the read hit the scan depth, Telegram stopped the read, or
    the chat simply does not contain them (deleted, or posted in another chat). Guessing between those
    is how a limit gets raised forever with no effect."""
    client = await LIBRARY.client()
    depth = int(limit or 0) or 100000
    msgs = []
    async for m in client.client.iter_messages(await client.entity(chat_id), limit=depth):
        if getattr(m, "action", None) is not None:
            continue
        msgs.append(m)
    videos = [m for m in msgs if getattr(m, "video", None) is not None or (
        getattr(m, "document", None) is not None and
        str(getattr(m.document, "mime_type", "")).startswith("video/"))]
    out = {"chat_id": chat_id, "messages_read": len(msgs), "videos": len(videos),
            "newest_id": msgs[0].id if msgs else 0, "oldest_id": msgs[-1].id if msgs else 0,
            "newest_date": msgs[0].date.isoformat() if msgs else None,
            "oldest_date": msgs[-1].date.isoformat() if msgs else None,
            "limit": depth}
    if dump:
        # `dump` answers "what does this bot actually say, and what can be clicked" — the read that has
        # to happen BEFORE anything is sent on the owner's behalf. Text and button labels only; a
        # hundred messages is plenty to learn a protocol and keeps the answer small.
        out["recent"] = [{
            "id": m.id, "date": m.date.isoformat(), "out": bool(getattr(m, "out", False)),
            "kind": ("video" if (getattr(m, "video", None) is not None or (
                getattr(m, "document", None) is not None and
                str(getattr(m.document, "mime_type", "")).startswith("video/")))
                else "photo" if getattr(m, "photo", None) is not None else "text"),
            "text": (getattr(m, "message", None) or "")[:400],
            "file_name": (getattr(getattr(m, "document", None), "attributes", None) and
                          next((getattr(a, "file_name", None) for a in m.document.attributes
                                if getattr(a, "file_name", None)), "")) or "",
            "buttons": [[b.text for b in row] for row in (getattr(m, "buttons", None) or [])],
        } for m in reversed(msgs[:int(dump)])]
    return out


@app.post("/api/chats/{chat_id}/fetch")
async def chat_fetch(chat_id: int, payload: dict | None = None):
    """Ask a SOURCE BOT for the episodes the library is missing (see botfetch.py).

    Owner-initiated by design: this writes to Telegram as the account. `{"seasons": [1,2,7]}` narrows
    it; the default asks every season for whatever is not in the library yet, slowly, and stops on its
    own after `TV_FETCH_MAX` requests or three failures in a row.
    """
    payload = payload or {}
    seasons = [int(s) for s in (payload.get("seasons") or [])] or list(range(1, 11))
    return {"ok": True, "job": BOTFETCH.start(chat_id, seasons=seasons)}


@app.get("/api/chats/{chat_id}/fetch/status")
def chat_fetch_status(chat_id: int):
    return BOTFETCH.job()


@app.post("/api/chats/{chat_id}/fetch/stop")
async def chat_fetch_stop(chat_id: int):
    return {"ok": True, "job": BOTFETCH.stop()}


@app.post("/api/chats/{chat_id}/say")
async def chat_say(chat_id: int, payload: dict):
    """Send ONE message to a chat as the account, and optionally wait for the reply.

    This is the only write this app performs on Telegram itself, and it exists for one job: asking a
    SOURCE bot for the content the library is missing. The Friends bot in this office keeps only its
    last ~184 messages, so seasons 1–2 and 7–10 are not in the chat to be scanned — the only way to get
    them is to ask, and asking means sending a message as the owner.

    It is therefore deliberately narrow (`text` only, one message per call, no loops) and it is an
    OWNER action: the agent may call it when the owner has asked for it, never on its own initiative.
    """
    payload = payload or {}
    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="צריך טקסט לשליחה")
    wait = min(30.0, max(0.0, float(payload.get("wait") or 6)))
    client = await LIBRARY.client()
    ent = await client.entity(chat_id)
    sent = await client.client.send_message(ent, text)
    reply = None
    if wait:
        # the bot answers within a second or two; reading the LAST message is enough and avoids a
        # long-poll loop on someone else's account
        deadline = time.time() + wait
        while time.time() < deadline:
            await asyncio.sleep(1.5)
            msgs = await client.history(chat_id, 3)
            newest = max(msgs, key=lambda m: m.id) if msgs else None
            if newest and newest.id > sent.id:
                reply = {"id": newest.id, "text": newest.text or newest.caption or "",
                         "kind": newest.kind}
                break
    log.info("sent %r to chat %s (id %s)", text[:60], chat_id, sent.id)
    return {"ok": True, "sent_id": sent.id, "reply": reply}


@app.post("/api/chats/{chat_id}/click")
async def chat_click(chat_id: int, payload: dict):
    """Press ONE inline button of a message (a bot menu is driven by buttons, not by text)."""
    payload = payload or {}
    client = await LIBRARY.client()
    ent = await client.entity(chat_id)
    msg = await client.client.get_messages(ent, ids=int(payload.get("message_id") or 0))
    if msg is None or not getattr(msg, "buttons", None):
        raise HTTPException(status_code=404, detail="להודעה הזו אין כפתורים")
    row, col = int(payload.get("row") or 0), int(payload.get("col") or 0)
    try:
        await msg.click(row, col)
    except (IndexError, TypeError):
        raise HTTPException(status_code=400, detail="אין כפתור במיקום הזה")
    label = msg.buttons[row][col].text
    await asyncio.sleep(min(20.0, max(0.0, float(payload.get("wait") or 6))))
    msgs = await client.history(chat_id, 3)
    newest = max(msgs, key=lambda m: m.id) if msgs else None
    log.info("clicked %r in chat %s", label, chat_id)
    return {"ok": True, "clicked": label,
            "reply": {"id": newest.id, "text": newest.text or newest.caption or "",
                      "kind": newest.kind} if newest else None}


@app.post("/api/chats/{chat_id}/scan")
async def chat_scan(chat_id: int):
    """Scan THIS chat now, ahead of the rotation — for the channel that was just adopted."""
    if not STORE.chat(chat_id):
        raise HTTPException(status_code=404, detail="הצ׳אט לא נמצא — יש לסנכרן קודם")
    return {"ok": True, "job": LIBRARY.start_sync(full=False, only_chat=chat_id)}


@app.post("/api/sync")
async def sync(payload: dict | None = None):
    job = LIBRARY.start_sync(full=bool((payload or {}).get("full")))
    return {"ok": True, "job": job}


@app.get("/api/sync/status")
def sync_status():
    return LIBRARY.job()


# ── media ────────────────────────────────────────────────────────────────────────────────────
def _placeholder_svg(title: str, sub: str = "") -> Response:
    """An intentional tile for a film whose still is still being generated.

    The renderer of this office flagged the alternative: a 404 makes the browser draw a broken-image
    icon, and a shelf of forty of them reads as a broken app rather than as a library warming up. This
    is the same artwork slot, filled with the title's own initial — and the client asks again until
    the real frame replaces it (the response says so in X-TV-Poster).

    Its colours are the office's palette, WRITTEN (a picture cannot name a token): the dark ground's
    olive falling to its ink, the initial in lime — the hue that speaks on a film's black
    (style.css, `--film`) — and the dark ground's quiet text."""
    initial = (title or "?").strip()[:1]
    label = (sub or "")[:18]
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="600" viewBox="0 0 400 600">'
        '<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#384629"/><stop offset="1" stop-color="#141b0f"/>'
        "</linearGradient></defs>"
        '<rect width="400" height="600" fill="url(#g)"/>'
        '<text x="200" y="300" text-anchor="middle" dominant-baseline="middle" '
        'font-family="system-ui,sans-serif" font-size="140" font-weight="700" fill="#a9b84c">'
        f"{initial}</text>"
        f'<text x="200" y="420" text-anchor="middle" font-family="system-ui,sans-serif" '
        f'font-size="26" fill="#a2a8a2">{label}</text></svg>')
    return Response(svg, media_type="image/svg+xml",
                    headers={"Cache-Control": "no-store", "X-TV-Poster": "pending"})


@app.get("/api/poster/{movie_id}")
async def poster(movie_id: str):
    row = STORE.movie(movie_id)
    if not row:
        raise HTTPException(status_code=404, detail="סרט לא נמצא")
    data = await LIBRARY.poster(row)
    if not data:
        return _placeholder_svg(row.get("title") or "", row.get("quality_label") or "")
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


def _range_headers(size: int, parsed) -> tuple[dict, int, int, int, bool]:
    start, end, partial = parsed
    length = end - start + 1
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Content-Range": f"bytes {start}-{end}/{size}",
        "Cache-Control": "private, max-age=0, no-store",
    }
    return headers, start, end, length, partial


async def _read_cached(path: str, start: int, length: int):
    """Read a byte range from the local cache copy. This is the difference between a seek that takes
    a second on a 1 MiB/s Telegram link and one that is instant."""
    loop = asyncio.get_running_loop()
    with open(path, "rb") as fh:
        fh.seek(start)
        remaining = length
        while remaining > 0:
            chunk = await loop.run_in_executor(None, fh.read, min(256 * 1024, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


@app.get("/api/stream/{movie_id}")
async def stream(movie_id: str, request: Request):
    """The bytes of a film, as a byte range. Cached copy first, Telegram second."""
    row = STORE.movie(movie_id)
    if not row:
        raise HTTPException(status_code=404, detail="סרט לא נמצא")
    size = int(row.get("size") or 0)
    if size <= 0:
        raise HTTPException(status_code=409, detail="גודל הקובץ אינו ידוע — יש לסנכרן מחדש")
    parsed = parse_range(request.headers.get("range") or "", size)
    if parsed is None:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    headers, start, _end, length, partial = _range_headers(size, parsed)
    headers["Cache-Control"] = "private, max-age=0, no-store"
    if LIBRARY.cache.complete(row):
        path = LIBRARY.cache.path(row)
        LIBRARY.cache.touch(path)
        headers["X-TV-Source"] = "cache"
        return StreamingResponse(_read_cached(path, start, length),
                                 status_code=206 if partial else 200,
                                 media_type=row.get("mime") or "video/mp4", headers=headers)
    try:
        await LIBRARY.client()
    except TvError as e:
        raise HTTPException(status_code=503, detail=str(e))
    # Watching a small file once is the moment to keep it: the next seek, the next rewatch and the
    # next viewer then cost nothing (cache.py decides which files are worth it).
    if start == 0:
        LIBRARY.cache.ensure(row, priority=True)
    headers["X-TV-Source"] = "telegram"
    return StreamingResponse(LIBRARY.stream(row, start, length),
                             status_code=206 if partial else 200,
                             media_type=row.get("mime") or "video/mp4", headers=headers)


@app.get("/api/raw/{movie_id}")
async def raw(movie_id: str, request: Request):
    """The file as bytes, unbounded and with an honest Content-Length — the endpoint ffmpeg reads.

    `/api/stream` deliberately answers a bounded window (it is what keeps a browser from pulling a 4 GB
    film through this process before the first frame). ffmpeg needs the opposite: a seekable resource
    whose Range requests are answered exactly, including one that starts at byte 900,000,000.
    """
    row = STORE.movie(movie_id)
    if not row:
        raise HTTPException(status_code=404, detail="סרט לא נמצא")
    size = int(row.get("size") or 0)
    if size <= 0:
        raise HTTPException(status_code=409, detail="גודל הקובץ אינו ידוע")
    parsed = parse_range(request.headers.get("range") or "", size, window=size)
    if parsed is None:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    start, end, partial = parsed
    length = end - start + 1
    if LIBRARY.cache.complete(row):
        path = LIBRARY.cache.path(row)
        LIBRARY.cache.touch(path)
        return StreamingResponse(_read_cached(path, start, length),
                                 status_code=206 if partial else 200,
                                 media_type=row.get("mime") or "application/octet-stream",
                                 headers={"Accept-Ranges": "bytes", "Content-Length": str(length),
                                          "Content-Range": f"bytes {start}-{end}/{size}",
                                          "Cache-Control": "no-store", "X-TV-Source": "cache"})
    try:
        await LIBRARY.client()
    except TvError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return StreamingResponse(LIBRARY.stream(row, start, length),
                             status_code=206 if partial else 200,
                             media_type=row.get("mime") or "application/octet-stream",
                             headers={"Accept-Ranges": "bytes", "Content-Length": str(length),
                                      "Content-Range": f"bytes {start}-{end}/{size}",
                                      "Cache-Control": "no-store"})


@app.get("/api/play/{movie_id}")
async def play(movie_id: str, t: int = 0, force: str | None = None):
    """Start watching: probe the file, decide how it can be played, and open a session if it needs one.

    The answer tells the client WHAT was decided and WHY (`probe.policy.reason`), so a film that cannot
    be played is explained instead of rendering as a black rectangle.
    """
    row = STORE.movie(movie_id)
    if not row:
        raise HTTPException(status_code=404, detail="סרט לא נמצא")
    if int(row.get("size") or 0) <= 0:
        raise HTTPException(status_code=409, detail="גודל הקובץ אינו ידוע — יש לסנכרן מחדש")
    try:
        await LIBRARY.client()
    except TvError as e:
        raise HTTPException(status_code=503, detail=str(e))
    result = await PLAYERS.open(row, f"{SELF_URL}/api/raw/{movie_id}", start=max(0, int(t)),
                                force=force)
    await LIBRARY.record_probe(row, result.get("probe") or {})
    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("reason") or "לא ניתן לנגן את הקובץ")
    result["movie"] = movie_public(row)
    return result


@app.get("/api/live/{session_id}")
async def live(session_id: str):
    """The remuxed stream. One ffmpeg per session, forwarded chunk by chunk."""
    if session_id not in PLAYERS.sessions:
        raise HTTPException(status_code=404, detail="הסשן הסתיים")
    return StreamingResponse(PLAYERS.stream(session_id), media_type="video/mp4",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@app.post("/api/live/{session_id}/close")
async def live_close(session_id: str):
    await PLAYERS.close(session_id)
    return {"ok": True}


@app.get("/api/play/status")
async def play_status():
    """Live sessions and what they decided — the diagnostic door for "why does this film stall"."""
    return PLAYERS.status()


@app.get("/api/backdrop/{movie_id}")
async def backdrop(movie_id: str):
    """The 16:9 still of a film, for the hero banner — generated from the film itself when Telegram
    has no artwork (see artwork.py)."""
    row = STORE.movie(movie_id)
    if not row:
        raise HTTPException(status_code=404, detail="סרט לא נמצא")
    await LIBRARY.poster(row)                      # generates poster + backdrop together
    path = LIBRARY.artwork.backdrop_path(movie_id)
    if not os.path.exists(path):
        return _placeholder_svg(row.get("title") or "", row.get("quality_label") or "")
    return Response(open(path, "rb").read(), media_type="image/jpeg",
                    headers={"Cache-Control": "private, max-age=86400"})


@app.post("/api/prefetch/{movie_id}")
async def prefetch(movie_id: str):
    """Warm the cache for a film nobody is watching yet — in practice, the NEXT episode.

    This is the only honest way "auto-play the next episode" starts instantly on this connection: at
    0.9–1.6 MiB/s a 180 MB episode needs two to three minutes, and that is exactly the length of the
    episode being watched."""
    row = STORE.movie(movie_id)
    if not row:
        raise HTTPException(status_code=404, detail="סרט לא נמצא")
    size = int(row.get("size") or 0)
    if size <= 0 or size > LIBRARY.cache.max_file_bytes:
        return {"ok": True, "queued": False,
                "reason": "הקובץ גדול מדי לשמירה מראש" if size else "גודל הקובץ אינו ידוע"}
    queued = LIBRARY.cache.prefetch(row)
    return {"ok": True, "queued": queued, "cached": LIBRARY.cache.complete(row),
            "size": size, "budget_bytes": LIBRARY.cache.budget_bytes}


@app.get("/api/cache")
def cache_status():
    return LIBRARY.cache.stat()


@app.post("/api/artwork/ensure/{movie_id}")
async def artwork_ensure(movie_id: str):
    """Put ONE film at the front of the artwork queue — what the hero banner asks for on load.

    Without it the banner is the last thing to get its still (the queue is a queue), and the first
    impression of the app is a placeholder while forty episodes it will never show are decoded first.
    """
    row = STORE.movie(movie_id)
    if not row:
        raise HTTPException(status_code=404, detail="סרט לא נמצא")
    if LIBRARY.artwork.has_poster(movie_id):
        return {"ok": True, "ready": True}
    if LIBRARY.artwork_queue is not None:
        LIBRARY.artwork_queue.ensure_front(row)
    return {"ok": True, "ready": False}


@app.get("/api/artwork")
def artwork_status():
    """How the background frame generation is doing — the honest answer to "why is this shelf empty"."""
    q = LIBRARY.artwork_queue
    return {"queue": q.status() if q else None}


@app.get("/api/series")
def series_list():
    rows = STORE.series()
    out = []
    for r in rows:
        first = STORE.movie(r["poster_id"]) if r.get("poster_id") else None
        out.append({"series_key": r["series_key"], "title": r["series"], "chat_id": r["chat_id"],
                    "episodes": int(r["n"] or 0), "season_from": int(r["season_from"] or 0),
                    "season_to": int(r["season_to"] or 0),
                    "poster_id": r.get("poster_id") or "",
                    "poster": f"api/poster/{r['poster_id']}" if r.get("poster_id") else None,
                    "sample": (first or {}).get("description") or ""})
    return {"series": out}


@app.get("/api/series/{series_key:path}")
def series_detail(series_key: str):
    rows = STORE.series_rows(series_key)
    if not rows:
        raise HTTPException(status_code=404, detail="סדרה לא נמצאה")
    grouped = episodes.group_episodes(rows)
    seasons = {}
    for ep in grouped:
        seasons.setdefault(ep["season"], []).append({
            "label": ep["label"], "episode": ep["episode"], "season": ep["season"],
            "description": ep["description"],
            "variants": [movie_public(v) | {"quality_label": v.get("quality_label") or ""}
                         for v in ep["variants"]]})
    return {"series_key": series_key, "title": rows[0].get("series") or "",
            "chat_id": rows[0]["chat_id"], "episodes": len(grouped),
            "seasons": [{"season": s, "episodes": seasons[s]} for s in sorted(seasons)]}


# ── canonical ops (for other apps and the office agent) ──────────────────────────────────────
def _ok(op: str, data: dict):
    return {"ok": True, "op": op, "data": data}


@app.post("/status")
async def op_status():
    return _ok("status", await LIBRARY.status())


@app.post("/listChats")
def op_list_chats():
    return _ok("listChats", {"chats": [chat_public(c) for c in STORE.chats()]})


@app.post("/listMovies")
def op_list_movies(payload: dict | None = None):
    payload = payload or {}
    chat_id = payload.get("chat_id")
    limit = int(payload.get("limit") or 200)
    rows = STORE.movies(chat_ids=[int(chat_id)] if chat_id else None, q=(payload.get("q") or ""),
                        limit=max(1, min(limit, 1000)))
    return _ok("listMovies", {"movies": [movie_public(r) for r in rows], "count": len(rows)})


@app.post("/getMovie")
def op_get_movie(payload: dict | None = None):
    row = STORE.movie(str((payload or {}).get("id") or ""))
    if not row:
        raise HTTPException(status_code=404, detail="סרט לא נמצא")
    return _ok("getMovie", {"movie": movie_public(row)})


@app.post("/refresh")
async def op_refresh(payload: dict | None = None):
    return _ok("refresh", {"job": LIBRARY.start_sync(full=bool((payload or {}).get("full")))})


@app.post("/streamUrl")
def op_stream_url(payload: dict | None = None):
    movie_id = str((payload or {}).get("id") or "")
    row = STORE.movie(movie_id)
    if not row:
        raise HTTPException(status_code=404, detail="סרט לא נמצא")
    return _ok("streamUrl", {"id": movie_id, "path": f"/api/stream/{movie_id}",
                             "in_network": f"http://{SERVICE_NAME}:8982/api/stream/{movie_id}",
                             "mime": row.get("mime") or "video/mp4", "size": int(row.get("size") or 0),
                             "title": row.get("title") or ""})


# ── the UI ───────────────────────────────────────────────────────────────────────────────────
@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"),
                        headers={"Cache-Control": "no-cache"})


@app.exception_handler(TvError)
async def tv_error_handler(_request: Request, exc: TvError):     # pragma: no cover - wiring only
    return JSONResponse(status_code=503, content={"detail": str(exc), "at": int(time.time())})
