"""telegram — «טלגרם», the office's Telegram: the owner's account, the chats it listens to, and their events.

WHAT THIS IS. The office's one door to Telegram as a PERSON uses it: the owner connects his own account here
(scan a QR, or phone + code), chooses which chats the office listens to, and every new message there becomes an
event on the office's event stream — `dgo:flow:telegram` (flow.v1) — where agents and automations listen
(`./bbox telegram flow`). It can also write into a chat, and ask a bot (BotFather) for something on his behalf.

WHY A USER ACCOUNT. A bot sees only what is sent to it; the owner asked for HIS Telegram — his groups, his
BotFather. So this is an MTProto user client (Telethon), like telegram-tv's, and it uses the SAME account
plane: an account is an instance of protocol `telegram_user` in the vault (connections), with the same secret
(`api_id`, `api_hash`, `session`, `phone`). One login serves both apps; this app holds no copy of the session.
It is a separate app because the film library is heavy (sync, ffmpeg) and the owner keeps it off the HP; and
ONE process should hold an account's connection, so the two never run against one account on one office.

PRIVACY, DELIBERATELY. The stream is read by every agent of the office, so a chat reaches it only when a person
switched it on (`/api/watch`). The group named in TELEGRAM_WATCH_DEFAULT is suggested on the first connection,
because it is the group the owner asked the office to work with.
"""
from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import os
import re
import tempfile
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import requests
import segno
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from redis import asyncio as aioredis
from telethon import TelegramClient, events, utils
from telethon.errors import RPCError, SessionPasswordNeededError
from telethon.sessions import StringSession
from telethon.tl import functions, types

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("telegram")

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("TG_DATA_DIR", "/data")
ACTIVE_PATH = os.path.join(DATA, "active.json")
WATCH_PATH = os.path.join(DATA, "watch.json")
CONNECTIONS_URL = os.environ.get("CONNECTIONS_URL", "http://connections:8990").rstrip("/")
PROTOCOL = "telegram_user"
BOT_PROTOCOL = "telegram_bot"
API_ID = int(os.environ.get("TG_DEFAULT_API_ID", "414329"))
API_HASH = os.environ.get("TG_DEFAULT_API_HASH", "af17b872310e6467fcd3d0aa82dc0d56")
WATCH_DEFAULT = [t.strip() for t in os.environ.get("TELEGRAM_WATCH_DEFAULT", "").split("|") if t.strip()]

# The event stream (flow.v1, ai/context/build-your-first-app.md): capped, and its TTL renewed with every event.
STREAM = "dgo:flow:telegram"
# written through the office's ONE publisher (DGO-1402): it caps the stream at ~1000 and renews 30 days itself
import sys as _sys

_sys.path.insert(0, "/opt/dgo")
try:
    import flowpub as _flowpub
except ImportError:
    _flowpub = None
TEXT_MAX = 2000
#: A bot token: `<bot id>:<35 chars>`. The trailing look-ahead, not `\b`: a token may END in `-`, where `\b`
#: backtracks and keeps a truncated token (the second reader, DGO-1300).
TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_-])(\d{6,12}:[A-Za-z0-9_-]{30,})(?![A-Za-z0-9_-])")
#: BotFather answers with tokens; its chat is never published (user id 93372553 is BotFather's, fixed by Telegram).
BOTFATHER_ID = 93372553

SERVICE, INTERFACE = "telegram", "telegram.v1"
OPS = ["status", "listChats", "watch", "send", "flow", "history", "mark", "saveMedia"]
#: a chat's whole thread from the CLI (`chat <x> history all`, DGO-1320) — Telethon paces itself through flood waits
HISTORY_MAX = 10000


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_json(path: str, doc) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False)
    os.replace(tmp, path)


def read_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


# ── the event stream ─────────────────────────────────────────────────────────────────────────
class Flow:
    """`dgo:flow:telegram`, written through the office's ONE publisher (platform-base/redis/flowpub.py, mounted
    read-only at /opt/dgo — docker-compose.yml): it caps the stream, renews its TTL, never blocks and never raises
    — Telegram keeps working when redis is away, and the screen says the stream is not being written (DGO-1402;
    this class carried its own copy of the contract until then). Reading the stream back (`last`) stays here."""

    def __init__(self):
        pw = os.environ.get("REDIS_PASSWORD", "")
        self.r = aioredis.Redis(host=os.environ.get("REDIS_HOST_INTERNAL", "redis"), port=6379, password=pw or None,
                                decode_responses=True, socket_timeout=5, socket_connect_timeout=5)
        self._read_error: str | None = None

    @property
    def published(self) -> int:
        return _flowpub.stats()["sent"] if _flowpub is not None else 0

    @property
    def error(self) -> str | None:
        if _flowpub is None:
            return "the office's publisher is not mounted (/opt/dgo/flowpub.py)"
        return _flowpub.stats()["last_error"] or self._read_error

    async def publish(self, type_: str, title: str, data: dict | None = None, link: str = "") -> None:
        # flowpub only queues (a microsecond under a lock): nothing here waits on redis, on the event loop or off it
        if _flowpub is not None:
            _flowpub.emit(SERVICE, type_, title, data or {}, link)

    async def last(self, n: int) -> list[dict]:
        try:
            rows = await self.r.xrevrange(STREAM, count=max(1, min(500, n)))
            self._read_error = None
        except Exception as e:                               # noqa: BLE001
            self._read_error = f"{type(e).__name__}: {e}"[:200]
            return []
        out = []
        for eid, f in rows:
            try:
                data = json.loads(f.get("data") or "{}")
            except ValueError:
                data = f.get("data")
            out.append({"id": eid, "type": f.get("type", ""), "title": f.get("title", ""), "at": f.get("at", ""),
                        "link": f.get("link", ""), "data": data})
        return out


FLOW = Flow()


# ── the vault (the same account plane as telegram-tv) ────────────────────────────────────────
async def vault(method: str, path: str, body=None) -> tuple[dict, int]:
    """The vault, off the event loop: a slow connections must not stall every route and Telegram's pings."""
    return await asyncio.to_thread(_vault, method, path, body)


def _vault(method: str, path: str, body=None) -> tuple[dict, int]:
    try:
        r = requests.request(method, f"{CONNECTIONS_URL}{path}", json=body, timeout=15)
        try:
            return (r.json() or {}), r.status_code
        except ValueError:
            return {}, r.status_code
    except requests.RequestException as e:
        log.warning("vault %s %s: %r", method, path, e)
        return {"error": "שירות החשבונות אינו זמין"}, 0


async def instances(glob: str = "telegram_user") -> tuple[list[dict], str | None]:
    out, code = await vault("GET", f"/api/instances?protocol={glob}")
    if code != 200:
        return [], out.get("error") or f"HTTP {code}"
    return list(out.get("instances") or []), None


def active_id() -> str | None:
    return (read_json(ACTIVE_PATH, {}) or {}).get("deployment")


def set_active(iid: str | None) -> None:
    write_json(ACTIVE_PATH, {"deployment": iid} if iid else {})


# ── the account: one client, its listener ────────────────────────────────────────────────────
class Account:
    def __init__(self):
        self.client: TelegramClient | None = None
        self.me: dict = {}
        self.instance: dict | None = None
        self.reason: str | None = "לא חובר חשבון טלגרם"
        self.lock = asyncio.Lock()
        self._watch_task: asyncio.Task | None = None
        self._lost_said = False                              # one account.lost per outage, not one per retry

    async def lost(self, title: str, data: dict) -> None:
        if not self._lost_said:
            self._lost_said = True
            await FLOW.publish("account.lost", title, data)

    @property
    def ok(self) -> bool:
        return self.client is not None and self.reason is None

    def later(self, seconds: float) -> None:
        """Try start() again — for what passes by itself (the vault booting after us, the network), never
        for a revoked login, which only the owner can fix."""
        asyncio.get_running_loop().call_later(seconds, lambda: asyncio.create_task(self.start()))

    async def start(self) -> None:
        async with self.lock:
            await self._stop()
            want = active_id()
            if not want:
                self.reason = "לא חובר חשבון טלגרם"
                return
            insts, err = await instances()
            if err:
                self.reason = err
                self.later(30)
                return
            self.instance = next((i for i in insts if i.get("id") == want), None)
            if self.instance is None:
                self.reason = "החשבון הפעיל אינו קיים יותר בחיבורים — יש לחבר מחדש"
                return
            out, code = await vault("GET", f"/api/instances/{want}/secret")
            sec = (out or {}).get("secret") or {}
            if code != 200 or not sec.get("session"):
                self.reason = "לא ניתן לקרוא את פרטי החשבון משירות החשבונות"
                if code == 0 or code >= 500:
                    self.later(30)
                return
            client = TelegramClient(StringSession(sec["session"]), int(sec.get("api_id") or API_ID),
                                    str(sec.get("api_hash") or API_HASH), device_model="Bina office",
                                    system_version="Linux", app_version="telegram 0.1", lang_code="he",
                                    # bounded: start() holds the lock, and a login's finish waits on it;
                                    # once connected, auto_reconnect keeps it up
                                    connection_retries=5, retry_delay=5, auto_reconnect=True,
                                    flood_sleep_threshold=60)
            try:
                await client.connect()
                if not await client.is_user_authorized():
                    raise RuntimeError("ההרשאה בוטלה בטלגרם — יש להתחבר מחדש")
                me = await client.get_me()
            except Exception as e:                           # noqa: BLE001
                await client.disconnect()
                self.reason = str(e)[:200] if isinstance(e, RuntimeError) else f"{type(e).__name__}: {e}"[:200]
                await self.lost(f"החיבור לטלגרם נכשל: {self.reason}", {"instance": want})
                if not isinstance(e, RuntimeError):          # the network, not a revoked login: try again later
                    self.later(300)
                return
            self.client = client
            self.me = {"id": me.id, "name": " ".join(x for x in [me.first_name, me.last_name] if x),
                       "username": me.username or "", "phone": me.phone or ""}
            self.reason = None
            self._lost_said = False
            client.add_event_handler(on_message, events.NewMessage())
            # a group that becomes a supergroup changes its id: the service message says so (DGO-1318)
            client.add_event_handler(on_migrate, events.Raw((types.UpdateNewMessage, types.UpdateNewChannelMessage)))
            self._watch_task = asyncio.create_task(self._watch_disconnect(client))
            await FLOW.publish("account.connected", f"טלגרם מחובר: {self.me['name'] or self.me['username']}",
                               {"instance": want, "user": self.me["username"]})
            if not os.path.exists(WATCH_PATH):
                try:
                    await suggest_default_watch()
                except Exception as e:                       # noqa: BLE001 - a suggestion, never the connection
                    log.warning("default watch not suggested: %r", e)
            else:
                t = asyncio.create_task(refresh_watched(client))
                BACKGROUND.add(t)
                t.add_done_callback(BACKGROUND.discard)

    async def _watch_disconnect(self, client: TelegramClient) -> None:
        try:
            await client.disconnected
        except Exception:                                    # noqa: BLE001
            pass
        if self.client is client:
            self.reason = "החיבור לטלגרם נותק — מנסה שוב בעוד דקה"
            await self.lost("החיבור לטלגרם נותק", {})
            # Telethon gave up reconnecting (connection_retries): start over in a minute, for as long as the
            # same account is still the active one. A login or a select in between replaces this client.
            await asyncio.sleep(60)
            if self.client is client and active_id():
                asyncio.create_task(self.start())

    async def _stop(self) -> None:
        client, self.client = self.client, None
        if self._watch_task:
            self._watch_task.cancel()
            self._watch_task = None
        if client is not None:
            try:
                await client.disconnect()
            except Exception:                                # noqa: BLE001
                pass

    async def stop(self) -> None:
        async with self.lock:
            await self._stop()

    def need(self) -> TelegramClient:
        if not self.ok:
            raise HTTPException(status_code=409, detail=self.reason or "טלגרם אינו מחובר")
        return self.client


ACCOUNT = Account()


def watched() -> dict[str, dict]:
    return {str(c["id"]): c for c in (read_json(WATCH_PATH, {}) or {}).get("chats", [])}


def chat_kind(entity) -> str:
    if isinstance(entity, types.User):
        return "bot" if entity.bot else "user"
    if isinstance(entity, types.Channel):
        return "group" if entity.megagroup else "channel"
    return "group"


def chat_title(entity) -> str:
    if isinstance(entity, types.User):
        return " ".join(x for x in [entity.first_name, entity.last_name] if x) or entity.username or str(entity.id)
    return getattr(entity, "title", "") or str(getattr(entity, "id", ""))


async def suggest_default_watch() -> None:
    """The first connection: listen to the group the owner named (TELEGRAM_WATCH_DEFAULT), if he is in it."""
    chats = []
    if WATCH_DEFAULT and ACCOUNT.ok:
        want = {t.casefold() for t in WATCH_DEFAULT}
        async for d in ACCOUNT.client.iter_dialogs(limit=300):
            if (d.name or "").strip().casefold() in want:
                chats.append({"id": d.id, "title": d.name, "kind": chat_kind(d.entity)})
    write_json(WATCH_PATH, {"chats": chats})
    for c in chats:
        await FLOW.publish("watch.on", f"מאזין לצ׳אט «{c['title']}» (הצעת ברירת מחדל)", {"chat_id": c["id"]})


async def on_message(event) -> None:
    w = watched().get(str(event.chat_id))
    if w is None:
        return
    msg = event.message
    try:
        sender = await event.get_sender()
    except Exception:                                        # noqa: BLE001
        sender = None
    who = chat_title(sender) if sender is not None else ""
    media = media_of(msg)
    # a caption is text and the picture beside it is media — both are said (a captioned screenshot reached the
    # stream as its words alone, DGO-1318); the file itself is GET /api/media
    text = TOKEN_RE.sub("[טוקן של בוט — הוסתר]", msg.message or "")   # a pasted token never reaches every agent
    shown = media and media["kind"] != "webpage"             # a link's preview is the link, already in the text
    line = (text.replace("\n", " ") + (f" [{media['label']}]" if shown else "")).strip()
    title = f"«{w['title']}» · {who}: {line[:160]}" if who else f"«{w['title']}»: {line[:160]}"
    await FLOW.publish("message.new", title, {
        "chat_id": event.chat_id, "chat": w["title"], "message_id": msg.id, "sender": who,
        "sender_id": getattr(sender, "id", None), "out": bool(msg.out), "text": text[:TEXT_MAX],
        "media": media,
        "reply_to": getattr(msg.reply_to, "reply_to_msg_id", None) if msg.reply_to else None})


#: what a person calls each kind of attachment, for the line in the stream
MEDIA_LABEL = {"photo": "תמונה", "video": "וידאו", "voice": "הודעה קולית", "audio": "שמע", "sticker": "מדבקה",
               "gif": "GIF", "document": "קובץ", "webpage": "קישור", "geo": "מיקום", "contact": "איש קשר",
               "poll": "סקר", "other": "מדיה"}
#: the largest file GET /api/media hands out — the container has 192M, and a file is held whole while it is sent
MEDIA_MAX = int(os.environ.get("TG_MEDIA_MAX_BYTES", str(20 * 1024 * 1024)))
#: one download at a time: a file costs about twice its size while it is held (the second reader, DGO-1318)
MEDIA_SLOT = asyncio.Semaphore(1)
#: what may be shown INLINE. The type is the sender's word: an `text/html` or `image/svg+xml` "document" from any
#: member of a watched group, opened inline on this app's signed-in origin, would run as the owner (the second
#: reader). Anything else is handed over as a download, and nothing is ever sniffed or allowed to script.
MEDIA_INLINE = {"image/jpeg", "image/png", "image/webp", "image/gif", "video/mp4", "audio/ogg", "audio/mpeg"}
#: every read-modify-write of the watch file, so a migration does not lose to a switch made at the same moment
WATCH_LOCK = asyncio.Lock()
#: background tasks a connection starts, held so the loop does not drop them before they end
BACKGROUND: set = set()


def media_of(msg) -> dict | None:
    """The attachment of a message as data — kind, name, size, type — or None. Never the bytes."""
    m = getattr(msg, "media", None)
    if m is None:
        return None
    if isinstance(m, types.MessageMediaWebPage):
        kind = "webpage"
    elif isinstance(m, (types.MessageMediaGeo, types.MessageMediaGeoLive, types.MessageMediaVenue)):
        kind = "geo"
    elif isinstance(m, types.MessageMediaContact):
        kind = "contact"
    elif isinstance(m, types.MessageMediaPoll):
        kind = "poll"
    elif getattr(msg, "photo", None) is not None:
        kind = "photo"
    elif getattr(msg, "sticker", None) is not None:
        kind = "sticker"
    elif getattr(msg, "gif", None) is not None:
        kind = "gif"
    elif getattr(msg, "voice", None) is not None:
        kind = "voice"
    elif getattr(msg, "video", None) is not None:
        kind = "video"
    elif getattr(msg, "audio", None) is not None:
        kind = "audio"
    elif getattr(msg, "document", None) is not None:
        kind = "document"
    else:
        kind = "other"
    f = getattr(msg, "file", None) if kind not in ("webpage", "geo", "contact", "poll") else None
    out = {"kind": kind, "label": MEDIA_LABEL[kind]}
    if f is not None:
        out.update(name=getattr(f, "name", None) or "", size=int(getattr(f, "size", 0) or 0),
                   mime=getattr(f, "mime_type", None) or "")
    return out


async def refresh_watched(client) -> None:
    """The watch file as Telegram says it is now: each chat's CURRENT title, and the link between a group and the
    supergroup it became. Both drift while the app is down or before it knew — the owner renamed the supergroup
    «בינה פתרונות ראשי» while its watch still said «Bina Solutions Main», and the pair watched by hand carried no
    link, so a title found half the thread (DGO-1320's reader). A deactivated group still names its successor
    (`migrated_to`). Run on every connection; one entity per watched chat; a failure leaves the file as it was."""
    try:
        await client.get_dialogs(limit=500)                  # the in-memory entity cache (as history and mark)
        start = watched()
        if not start:
            return                                           # nothing watched — or a file that does not read
        found = {}
        for key in list(start):
            try:
                ent = await client.get_entity(int(key))
            except (ValueError, RPCError):
                continue
            cid = getattr(getattr(ent, "migrated_to", None), "channel_id", None)
            found[key] = (chat_title(ent), utils.get_peer_id(types.PeerChannel(cid)) if cid else None)
        added = []
        async with WATCH_LOCK:
            w = watched()
            changed = False
            for key, (title, new) in found.items():
                if key not in w:
                    continue                                 # switched off meanwhile
                # a title renamed WHILE this ran (on_migrate stored it) is the newer one: kept
                if title and title != w[key].get("title") and w[key].get("title") == start[key].get("title"):
                    w[key]["title"], changed = title, True
                if new is not None and w[key].get("migrated_to") != new:
                    w[key]["migrated_to"], changed = new, True
                if new is not None and str(new) not in w:
                    # migrated while the app was down: the new id is watched, as a live migration would be
                    w[str(new)] = {"id": new, "title": w[key]["title"], "kind": "group", "migrated_from": int(key)}
                    added.append((new, int(key), w[key]["title"]))
                    changed = True
                elif new is not None and w[str(new)].get("migrated_from") != int(key):
                    w[str(new)]["migrated_from"], changed = int(key), True
            if changed:
                write_json(WATCH_PATH, {"chats": list(w.values())})
        for new, old, title in added:
            await FLOW.publish("watch.on", f"«{title}» הפכה לקבוצת-על — מאזין למזהה החדש",
                               {"chat_id": new, "migrated_from": old})
    except Exception as e:                                   # noqa: BLE001 - a refresh, never the connection
        log.warning("watched chats not refreshed: %r", e)


async def on_migrate(update) -> None:
    """A watched group became a supergroup: Telegram gives it a NEW id, and the old one stops receiving. The
    watch moves by itself — the new id is watched, the old one kept (its history is the thread before), and
    watch.on says so. Seen from either side: MigrateTo in the old group, ChannelMigrateFrom in the new one.
    A watched chat's NEW TITLE is kept too (MessageActionChatEditTitle), so the CLI finds it by the name it has."""
    msg = getattr(update, "message", None)
    act = getattr(msg, "action", None)
    if isinstance(act, types.MessageActionChatEditTitle):
        cid = utils.get_peer_id(msg.peer_id)
        async with WATCH_LOCK:
            w = watched()
            if str(cid) not in w or w[str(cid)].get("title") == act.title:
                return
            old_title, w[str(cid)]["title"] = w[str(cid)].get("title"), act.title
            write_json(WATCH_PATH, {"chats": list(w.values())})
        await FLOW.publish("chat.renamed", f"«{old_title}» נקראת עכשיו «{act.title}»",
                           {"chat_id": cid, "title": act.title, "was": old_title})
        return
    if isinstance(act, types.MessageActionChatMigrateTo):
        old, new = utils.get_peer_id(msg.peer_id), utils.get_peer_id(types.PeerChannel(act.channel_id))
    elif isinstance(act, types.MessageActionChannelMigrateFrom):
        old, new = utils.get_peer_id(types.PeerChat(act.chat_id)), utils.get_peer_id(msg.peer_id)
    else:
        return
    async with WATCH_LOCK:
        w = watched()
        if str(old) not in w or str(new) in w:
            return                                           # not ours, or already moved (the other side's message)
        prev = w[str(old)]
        w[str(new)] = {"id": new, "title": prev["title"], "kind": "group", "migrated_from": old}
        prev["migrated_to"] = new
        write_json(WATCH_PATH, {"chats": list(w.values())})
    log.info("watched chat %s migrated to %s", old, new)
    await FLOW.publish("watch.on", f"«{prev['title']}» הפכה לקבוצת-על — מאזין למזהה החדש",
                       {"chat_id": new, "migrated_from": old})


# ── the login wizard (QR or phone) ───────────────────────────────────────────────────────────
class Login:
    """One login at a time. Nothing reaches the vault until Telegram says the login succeeded."""

    IDLE = {"step": "idle", "qr_svg": None, "error": None, "hint": None, "phone": ""}

    def __init__(self):
        self.state = dict(self.IDLE)
        self.client: TelegramClient | None = None
        self.task: asyncio.Task | None = None

    async def start(self, mode: str, phone: str = "") -> dict:
        if self.state["step"] in ("starting", "qr", "code", "password"):
            return {**self.state, "error": "התחברות כבר פעילה — בטלו אותה כדי להתחיל מחדש"}
        await self.reset()
        self.state = {**self.IDLE, "step": "starting", "phone": phone}
        self.client = TelegramClient(StringSession(), API_ID, API_HASH, device_model="Bina office",
                                     system_version="Linux", app_version="telegram 0.1", lang_code="he")
        try:
            await self.client.connect()
            if mode == "qr":
                qr = await self.client.qr_login()
                self._qr(qr)
                self.task = asyncio.create_task(self._qr_loop(qr))
            else:
                if not re.fullmatch(r"\+?\d{8,15}", phone or ""):
                    raise ValueError("מספר הטלפון אינו תקין — עם קידומת מדינה, למשל +972…")
                await self.client.send_code_request(phone)
                self.state.update(step="code", hint="הקוד נשלח לטלגרם שלך. מזינים אותו כאן.")
        except Exception as e:                               # noqa: BLE001
            self.state.update(step="failed", error=login_error(e))
        return self.state

    def _qr(self, qr) -> None:
        # The QR is a picture: it carries the palette's values (gate G82 lets a value through where a token
        # cannot be named) — the dark ink and the paper.
        self.state.update(step="qr", qr_svg=segno.make(qr.url, error="l").svg_data_uri(
            scale=6, dark="#1f2a17", light="#ffffff"),
            hint="בטלפון: טלגרם ← הגדרות ← מכשירים ← קישור מכשיר, וסורקים. הקוד מתחדש מעצמו.")

    async def _qr_loop(self, qr) -> None:
        while True:
            try:
                left = (qr.expires - datetime.now(timezone.utc)).total_seconds()
            except Exception:                                # noqa: BLE001
                left = 25.0
            try:
                await qr.wait(timeout=max(1.0, left + 2))
                await self.finish()
                return
            except asyncio.TimeoutError:
                pass
            except SessionPasswordNeededError:
                self.state.update(step="password", qr_svg=None, hint="לחשבון יש אימות דו-שלבי: מזינים את הסיסמה.")
                return
            except Exception as e:                           # noqa: BLE001
                self.state.update(step="failed", error=login_error(e))
                return
            try:
                await qr.recreate()
                self._qr(qr)
            except Exception as e:                           # noqa: BLE001
                self.state.update(step="failed", error=login_error(e))
                return

    async def code(self, code: str) -> dict:
        if self.state["step"] != "code" or self.client is None:
            return {**self.state, "error": "אין שלב קוד פעיל"}
        try:
            await self.client.sign_in(phone=self.state["phone"], code=str(code).strip())
            await self.finish()
        except SessionPasswordNeededError:
            self.state.update(step="password", error=None, hint="לחשבון יש אימות דו-שלבי: מזינים את הסיסמה.")
        except Exception as e:                               # noqa: BLE001
            self.state.update(error=login_error(e))
        return self.state

    async def password(self, password: str) -> dict:
        if self.state["step"] != "password" or self.client is None:
            return {**self.state, "error": "אין שלב סיסמה פעיל"}
        try:
            await self.client.sign_in(password=password)
            await self.finish()
        except Exception as e:                               # noqa: BLE001
            self.state.update(error=login_error(e))
        return self.state

    async def finish(self) -> None:
        """The one place a session string is written anywhere: into the vault, as a telegram_user instance."""
        c = self.client
        me = await c.get_me()
        name = " ".join(x for x in [me.first_name, me.last_name] if x)
        hint = self.state.get("phone") or (f"@{me.username}" if me.username else "")
        out, code = await vault("POST", "/api/instances", {
            "protocol": PROTOCOL, "label": name or hint or "טלגרם", "account_hint": hint,
            "secret": {"api_id": str(API_ID), "api_hash": API_HASH, "session": c.session.save(),
                       "phone": self.state.get("phone") or (me.phone or "")}})
        if code >= 400 or not out.get("id"):
            self.state.update(step="failed", error=out.get("error") or f"שמירת החשבון נכשלה (HTTP {code})")
            return
        set_active(out["id"])
        await self.reset()
        self.state = {**self.IDLE, "step": "connected", "hint": f"החשבון {name or hint} מחובר"}
        await ACCOUNT.start()

    async def reset(self) -> None:
        # Never the task we are running in: a QR login finishes INSIDE _qr_loop, and cancelling it there
        # killed its own finish — the vault had the session, and the screen kept a stale QR (second reader).
        if self.task and self.task is not asyncio.current_task():
            self.task.cancel()
        self.task = None
        if self.client is not None:
            try:
                await self.client.disconnect()
            except Exception:                                # noqa: BLE001
                pass
            self.client = None

    async def cancel(self) -> dict:
        await self.reset()
        self.state = dict(self.IDLE)
        return self.state


def login_error(e: Exception) -> str:
    name = type(e).__name__
    table = {"PhoneNumberInvalid": "מספר הטלפון אינו תקין — עם קידומת מדינה, למשל +972…",
             "PhoneCodeInvalid": "הקוד שגוי — נסו שוב", "PhoneCodeExpired": "פג תוקף הקוד — מתחילים מחדש",
             "PasswordHashInvalid": "סיסמת האימות הדו-שלבי שגויה",
             "FloodWait": "טלגרם הגביל את הקצב — נסו שוב בעוד כמה דקות",
             "PhoneNumberBanned": "המספר חסום בטלגרם"}
    for k, v in table.items():
        if k in name:
            return v
    return str(e)[:200] if isinstance(e, ValueError) else f"{name}: {e}"[:200]


LOGIN = Login()


# ── a bot's token, from BotFather, straight into the vault ───────────────────────────────────
async def bot_token_to_vault(bot: str, label: str) -> dict:
    """Ask BotFather, as the connected account, for `bot`'s token and store it in THIS office's vault as a
    `telegram_bot` instance named `label`. The token is never returned, logged or published — only where it went.

    The path is the one a person takes to READ a token: `/mybots` → the bot → «API Token», which shows the
    CURRENT token. Not `/token`, which BotFather words as "generate a new token" — a new token would cut off
    whatever uses the bot today. The bot is matched EXACTLY (case, `@`, `_` and spaces aside, an optional
    trailing `bot`): "bina solution agent" is @bina_solution_agent_bot, and never the first bot containing "bina".
    """
    client = ACCOUNT.need()
    norm = lambda s: re.sub(r"[@_\s]", "", s or "").casefold()          # noqa: E731
    want = norm(bot)
    async with client.conversation("BotFather", timeout=40) as conv:
        await conv.send_message("/mybots")
        ask = await conv.get_response()
        names = [b.text for row in (ask.buttons or []) for b in row]
        hits = [n for n in names if norm(n) in (want, want + "bot")]
        if len(hits) != 1:
            return {"ok": False, "detail": f"BotFather לא הציע בדיוק בוט אחד בשם {bot} "
                                           f"(בוטים בחשבון: {', '.join(names) or 'אין'})"}
        pick = hits[0]
        await ask.click(text=pick)
        menu = await conv.get_edit()
        api = next((b.text for row in (menu.buttons or []) for b in row if "token" in b.text.casefold()
                    and "revoke" not in b.text.casefold()), None)
        if api is None:
            return {"ok": False, "detail": "בתפריט של הבוט ב-BotFather אין כפתור API Token"}
        await menu.click(text=api)
        ans = await conv.get_edit()
    m = TOKEN_RE.search(ans.message or "")
    if not m:
        return {"ok": False, "detail": "BotFather לא ענה בטוקן (התשובה לא נשמרה)"}
    username = pick.lstrip("@")
    existing = [i for i in (await instances(BOT_PROTOCOL))[0] if i.get("label") == label]
    secret = {"token": m.group(1), "username": username}
    if existing:
        out, code = await vault("PUT", f"/api/instances/{existing[0]['id']}/secret",
                                {"secret": secret, "replace": True})
        iid = existing[0]["id"]
    else:
        out, code = await vault("POST", "/api/instances", {"protocol": BOT_PROTOCOL, "label": label,
                                                           "account_hint": f"@{username}", "secret": secret})
        iid = out.get("id")
    if code >= 400 or not iid:
        return {"ok": False, "detail": out.get("error") or f"שמירה בחיבורים נכשלה (HTTP {code})"}
    await FLOW.publish("bot.token.stored", f"הטוקן של @{username} נשמר בחיבורים בשם «{label}»",
                       {"bot": username, "instance": iid})
    return {"ok": True, "instance": iid, "bot": username, "label": label}


# ── HTTP ─────────────────────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(_app: FastAPI):
    async def warm():
        await asyncio.sleep(2)
        try:
            await ACCOUNT.start()                            # retries by itself what passes by itself
        except Exception:                                    # noqa: BLE001 - the screen must stay reachable
            log.exception("account start failed")
    task = asyncio.create_task(warm())
    yield
    task.cancel()
    await LOGIN.reset()
    await ACCOUNT.stop()


app = FastAPI(title="telegram", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=os.path.join(ROOT, "static")), name="static")


def ok(op: str, data) -> dict:
    return {"ok": True, "op": op, "data": data}


@app.get("/healthz")
def healthz():
    """The process, not Telegram: an expired session must not put the container in a restart loop."""
    return {"ok": True, "service": SERVICE}


@app.get("/readyz")
def readyz():
    if not ACCOUNT.ok:
        raise HTTPException(status_code=503, detail=ACCOUNT.reason or "טלגרם אינו מחובר")
    return {"ok": True}


@app.get("/manifest")
def manifest():
    return {"service": SERVICE, "interface": INTERFACE, "ops": OPS, "stream": STREAM}


@app.get("/ops")
def ops():
    return {"ops": OPS}


async def status_doc() -> dict:
    return {"connected": ACCOUNT.ok, "reason": ACCOUNT.reason, "me": ACCOUNT.me if ACCOUNT.ok else {},
            "instance": (ACCOUNT.instance or {}).get("id"), "watched": list(watched().values()),
            "flow": {"stream": STREAM, "published": FLOW.published, "error": FLOW.error},
            "login": LOGIN.state}


@app.get("/api/status")
async def api_status():
    return await status_doc()


@app.post("/status")
async def op_status(_: dict | None = None):
    return ok("status", await status_doc())


@app.get("/api/accounts")
async def api_accounts():
    insts, err = await instances()
    return {"accounts": insts, "active": active_id(), "error": err}


@app.post("/api/accounts/select")
async def api_select(body: dict):
    iid = (body or {}).get("id") or ""
    insts, err = await instances()
    if err:
        raise HTTPException(status_code=503, detail=err)
    if iid not in {i.get("id") for i in insts}:
        raise HTTPException(status_code=404, detail="אין חשבון כזה בחיבורים")
    set_active(iid)
    await ACCOUNT.start()
    return await status_doc()


@app.post("/api/login/start")
async def login_start(body: dict):
    mode = (body or {}).get("mode") or "qr"
    if mode not in ("qr", "phone"):
        raise HTTPException(status_code=400, detail="mode הוא qr או phone")
    return await LOGIN.start(mode, ((body or {}).get("phone") or "").replace(" ", ""))


@app.get("/api/login/state")
def login_state():
    return LOGIN.state


@app.post("/api/login/code")
async def login_code(body: dict):
    return await LOGIN.code((body or {}).get("code") or "")


@app.post("/api/login/password")
async def login_password(body: dict):
    return await LOGIN.password((body or {}).get("password") or "")


@app.post("/api/login/cancel")
async def login_cancel():
    return await LOGIN.cancel()


async def list_chats(q: str = "", limit: int = 100) -> list[dict]:
    client = ACCOUNT.need()
    w = watched()
    out = []
    async for d in client.iter_dialogs(limit=500):
        if q and q.casefold() not in (d.name or "").casefold():
            continue
        out.append({"id": d.id, "title": d.name, "kind": chat_kind(d.entity),
                    "username": getattr(d.entity, "username", None) or "", "unread": d.unread_count,
                    "watched": str(d.id) in w})
        if len(out) >= limit:
            break
    return out


@app.get("/api/chats")
async def api_chats(q: str = "", limit: int = 100):
    return {"chats": await list_chats(q, max(1, min(500, limit)))}


@app.post("/listChats")
async def op_list_chats(body: dict | None = None):
    b = body or {}
    return ok("listChats", {"chats": await list_chats(b.get("q") or "", int(b.get("limit") or 100))})


async def set_watch(chat_id: int, on: bool) -> dict:
    client = ACCOUNT.need()
    entry = None
    if on:
        if int(chat_id) == BOTFATHER_ID:
            raise HTTPException(status_code=403, detail="BotFather עונה בטוקנים — הצ׳אט שלו לא נשלח לזרם")
        try:
            ent = await client.get_entity(int(chat_id))
        except ValueError:
            # The session keeps its entity cache in memory: after a restart an id is unknown until the
            # dialogs are read once.
            await client.get_dialogs(limit=500)
            try:
                ent = await client.get_entity(int(chat_id))
            except ValueError:
                raise HTTPException(status_code=404, detail="אין צ׳אט כזה בחשבון")
        entry = {"id": int(chat_id), "title": chat_title(ent), "kind": chat_kind(ent)}
    # the network first, then ONE read-modify-write under the lock: a migration arriving meanwhile is kept
    async with WATCH_LOCK:
        w = watched()
        gone = None
        if entry is not None:
            w[str(chat_id)] = {**w.get(str(chat_id), {}), **entry}
        elif str(chat_id) in w:
            gone = w.pop(str(chat_id))
        write_json(WATCH_PATH, {"chats": list(w.values())})
    if entry is not None:
        await FLOW.publish("watch.on", f"מאזין לצ׳אט «{entry['title']}»", {"chat_id": int(chat_id)})
    elif gone is not None:
        await FLOW.publish("watch.off", f"הפסיק להאזין לצ׳אט «{gone['title']}»", {"chat_id": int(chat_id)})
    return {"watched": list(w.values())}


@app.post("/api/watch")
async def api_watch(body: dict):
    try:
        cid = int((body or {}).get("chat_id"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="chat_id הוא מספר")
    on = (body or {}).get("on", True)
    if isinstance(on, str) and on.lower() in ("true", "false", "1", "0"):
        on = on.lower() in ("true", "1")
    if not isinstance(on, bool):
        # never `bool("false")`: from a shell or n8n that is True, and a chat would be published by mistake
        raise HTTPException(status_code=400, detail="on הוא true או false")
    return await set_watch(cid, on)


@app.post("/watch")
async def op_watch(body: dict):
    return ok("watch", await api_watch(body))


async def send(chat_id: int, text: str) -> dict:
    """Writes as the OWNER: only into a WATCHED chat (history's rule), never to BotFather — a caller on the
    office's network could otherwise post anywhere in his name, or send BotFather /revoke."""
    if watched().get(str(chat_id)) is None or int(chat_id) == BOTFATHER_ID:
        raise HTTPException(status_code=403, detail="רק צ׳אט שמאזינים לו — הפעל האזנה קודם")
    client = ACCOUNT.need()
    if not text.strip():
        raise HTTPException(status_code=400, detail="אין מה לשלוח")
    msg = await client.send_message(int(chat_id), text[:4096])
    return {"chat_id": int(chat_id), "message_id": msg.id}


@app.post("/api/send")
async def api_send(body: dict):
    try:
        cid = int((body or {}).get("chat_id"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="chat_id הוא מספר")
    return await send(cid, str((body or {}).get("text") or ""))


@app.post("/send")
async def op_send(body: dict):
    return ok("send", await api_send(body))


async def history(chat_id: int, limit: int) -> dict:
    """A WATCHED chat's messages from before the stream began, oldest first: the stream carries only what
    arrives after a chat is switched on, and the owner asked for the group's whole thread (DGO-1300).
    Only a watched chat, because a watched chat is already shared with every agent; anything else stays his.
    Tokens are masked exactly as in the stream."""
    w = watched().get(str(chat_id))
    if w is None or int(chat_id) == BOTFATHER_ID:
        raise HTTPException(status_code=403, detail="רק צ׳אט שמאזינים לו — הפעל האזנה קודם")
    client = ACCOUNT.need()
    try:
        ent = await client.get_entity(int(chat_id))
    except ValueError:
        # the session keeps its entity cache in memory (set_watch's own case): read the dialogs once
        await client.get_dialogs(limit=500)
        try:
            ent = await client.get_entity(int(chat_id))
        except ValueError:
            raise HTTPException(status_code=404, detail="אין צ׳אט כזה בחשבון")
    out = []
    # wait_time=0: Telethon otherwise sleeps up to 1 s per 100 messages whenever the limit is over 3000, and the
    # whole thread (DGO-1320) took longer than its caller waits; Telegram's own flood waits are still slept through
    async for msg in client.iter_messages(ent, limit=limit, wait_time=0):
        if getattr(msg, "action", None) is not None:
            continue                                         # joins, pins, renames: the stream never carries them
        # the page of history already carries its senders: no network call per message (a flood wait)
        sender = msg.sender
        out.append({"message_id": msg.id, "at": msg.date.isoformat() if msg.date else None,
                    "sender": chat_title(sender) if sender is not None else "",
                    "sender_id": msg.sender_id, "out": bool(msg.out),
                    "text": TOKEN_RE.sub("[טוקן של בוט — הוסתר]", msg.message or "")[:TEXT_MAX],
                    "media": media_of(msg),
                    "reply_to": getattr(msg.reply_to, "reply_to_msg_id", None) if msg.reply_to else None})
    out.reverse()
    return {"chat_id": int(chat_id), "chat": w["title"], "messages": out}


async def watched_message(chat_id: int, message_id: int):
    """(client, message, its file as data, the watched chat) — the ONE rule of `/api/media` and of the save to the
    drive: a watched chat is already shared with every agent; anything else stays the owner's, BotFather always;
    and the file's kind and size are read from Telegram's own record of it, never from the sender's word."""
    w = watched().get(str(chat_id))
    if w is None or int(chat_id) == BOTFATHER_ID:
        raise HTTPException(status_code=403, detail="רק צ׳אט שמאזינים לו — הפעל האזנה קודם")
    client = ACCOUNT.need()
    try:
        msg = await client.get_messages(int(chat_id), ids=int(message_id))
    except ValueError:
        await client.get_dialogs(limit=500)                  # the in-memory entity cache, as in history
        try:
            msg = await client.get_messages(int(chat_id), ids=int(message_id))
        except ValueError:
            raise HTTPException(status_code=404, detail="אין צ׳אט כזה בחשבון")
    media = media_of(msg) if msg is not None else None
    if not media or "size" not in media:
        raise HTTPException(status_code=404, detail="להודעה הזו אין קובץ")
    return client, msg, media, w


@app.get("/api/media")
async def api_media(chat_id: int, message_id: int):
    """The file of one message in a WATCHED chat — the picture a caption came with (DGO-1318), held whole and handed
    back. A larger file goes to the office's drive instead, in pieces (`POST /api/media/save`, DGO-1805)."""
    client, msg, media, _w = await watched_message(chat_id, message_id)
    if media["size"] > MEDIA_MAX:
        raise HTTPException(status_code=413, detail=(
            f"הקובץ גדול מ-{MEDIA_MAX // (1024 * 1024)}MB להצגה כאן — שומרים אותו בקבצים: «שמור בקבצים» במסך הטלגרם, "
            f"./bbox telegram media-save {int(chat_id)} {int(message_id)}, או POST /api/media/save"))
    async with MEDIA_SLOT:
        data = await client.download_media(msg, file=bytes)
    if not data:
        raise HTTPException(status_code=404, detail="להודעה הזו אין קובץ")
    name = media.get("name") or f"{chat_id}-{message_id}"
    mime = (media.get("mime") or "").lower()
    inline = mime in MEDIA_INLINE
    disp = "inline" if inline else "attachment"
    return Response(data, media_type=mime if inline else "application/octet-stream",
                    headers={"Content-Disposition": f"{disp}; filename*=UTF-8''{requests.utils.quote(name, safe='')}",
                             "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox",
                             "Cache-Control": "no-store"})


# ── a message's file, of ANY size, into the office's drive (DGO-1805) ──────────────────────────────────────────────
# The owner sent a 97 MB video to the group and asked «אתה יכול להוריד דרך החשבון האישי ולתמלל»: `/api/media` holds a
# file whole in this 192M container, so it refuses above 20 MiB. Telegram streams (`iter_download`), and the drive
# takes a file in pieces (tus, apps/drive `/api/uploads` — the protocol meet's copier uses): what is held here at
# once is one piece and one request, whatever the file's size. The file lands at «טלגרם/<chat>/<message>-<name>».
#: the office's drive, and the profile whose files these are (as meet's copier: MEET_DRIVE_URL / MEET_DRIVE_PROFILE)
DRIVE_URL = os.environ.get("TG_DRIVE_URL", "http://drive:8975").strip().rstrip("/")
DRIVE_PROFILE = os.environ.get("TG_DRIVE_PROFILE", "admin").strip()
#: this app's own folder in the drive: kept by it (no rename / move / trash from the drive's screen), a folder a chat
DRIVE_FOLDER = "טלגרם"
#: one piece to the drive, and one request to Telegram (its largest): about 4.5 MB held, for 97 MB or 2 GB
DRIVE_PIECE = 4 * 1024 * 1024
SAVE_REQUEST = 512 * 1024
#: one save at a time: two would hold two pieces, and Telegram paces one account's downloads anyway
SAVE_SLOT = asyncio.Semaphore(1)
#: how long the drive may take to hash and store a file once every byte is in (meet allows twenty minutes)
SAVE_FINISH_S = 1200
#: the whole of one save, download and finish: a download that hangs must not hold SAVE_SLOT — and with it every other
#: save — for good. 2 GB at a slow 1 MB/s is about 35 minutes; three hours is a stuck one.
SAVE_MAX_S = int(os.environ.get("TG_SAVE_MAX_SECONDS", str(3 * 3600)))


def _drive(method: str, path: str, body: dict | None = None, data: bytes | None = None,
           headers: dict | None = None, timeout: int = 120) -> dict:
    """One call to the office's drive as DRIVE_PROFILE — blocking (requests), so it is called through
    asyncio.to_thread. The drive's refusal is raised in its own words; an outage in this app's."""
    kw = {"json": {**body, "profile_id": DRIVE_PROFILE}} if body is not None else {"data": data, "headers": headers or {}}
    try:
        r = requests.request(method, DRIVE_URL + path, params={"profile_id": DRIVE_PROFILE}, timeout=timeout, **kw)
    except requests.RequestException as e:
        log.warning("drive %s %s: %s", method, path, e)
        raise HTTPException(status_code=502, detail="שירות הקבצים אינו עונה — הקובץ לא נשמר") from None
    if r.status_code >= 400:
        try:
            why = str((r.json() or {}).get("error") or "")
        except ValueError:
            why = ""
        if r.status_code == 413:
            why = why or "הקבצים לא מקבלים קובץ בגודל הזה"
        raise HTTPException(status_code=413 if r.status_code == 413 else 502,
                            detail=f"{why or 'שירות הקבצים סירב'} ({r.status_code}) — הקובץ לא נשמר")
    try:
        return r.json() if r.content else {}
    except ValueError:
        return {}


def _in_drive(path: str) -> bool:
    """Is a file already at `path`? A save of the same message answers the file that is there (not a second copy).
    An unanswered question is «no»: the save then goes on, and the drive says why if it cannot take it."""
    try:
        r = requests.get(DRIVE_URL + "/api/fs", params={"path": path, "profile_id": DRIVE_PROFILE}, timeout=30)
    except requests.RequestException:
        return False
    return r.status_code == 200


def _drop_upload(sid: str) -> None:
    """A session that will not finish is removed at once — never left with its bytes on the drive's disk."""
    try:
        _drive("DELETE", f"/api/uploads/{sid}")
    except HTTPException:
        pass                                                 # best effort: the drive's own sweep takes it later


#: what never goes into a drive path from a chat's title or a file's name: `/` `\`, the control characters (C0, DEL,
#: C1) and the invisible marks that reorder or hide text (bidi overrides and isolates, zero-width) — a right-to-left
#: override in a name can disguise its extension in the drive's listing (the second reader)
_UNSAFE = re.compile(r"[\x00-\x1f\x7f-\x9f/\\​-‏‪-‮⁦-⁩﻿]+")


def _segment(text: str, limit: int = 120) -> str:
    """One path segment of the drive, from a chat's title or a file's name. Too long, it is cut before its
    extension, never through it."""
    s = _UNSAFE.sub(" ", str(text or "")).strip().strip(".").strip()
    if len(s) > limit:
        stem, dot, ext = s.rpartition(".")
        s = (stem[: limit - len(ext) - 1].rstrip() + "." + ext) if dot and 0 < len(ext) <= 16 else s[:limit].rstrip()
    return s


def save_name(media: dict, message_id: int) -> str:
    """`<message>-<the file's own name>`, or `<message>-<kind>.<ext>` when it has none (a video sent as a video):
    the message's number first, so one message is one file and a second save finds it."""
    name = _segment(media.get("name") or "")
    if not name:
        ext = mimetypes.guess_extension((media.get("mime") or "").split(";")[0].strip().lower()) or ""
        name = f"{media.get('kind') or 'file'}{ext}"
    return f"{int(message_id)}-{name}"


async def _close(it) -> None:
    """End a download that stops early: Telethon's borrows a connection to the file's data centre."""
    for attr in ("close", "aclose"):
        fn = getattr(it, attr, None)
        if fn is not None:
            res = fn()
            if asyncio.iscoroutine(res):
                await res
            return


async def stream_to_drive(client, msg, media: dict, folder: str, name: str) -> None:
    size, mime = int(media["size"]), media.get("mime") or "application/octet-stream"
    whole = None
    if media.get("kind") == "photo":
        # a photo (10 MB at most) through download_media, which picks its largest size — the session is opened with
        # the bytes it gave, not the size the record named (Telethon may choose another). Its DOWNLOAD waits for
        # /api/media's own slot, so the two never download a whole file at the same time; the photo's bytes may still
        # be held during its upload while /api/media serves one — about 30 MB at most, well inside 192M. Holding the
        # slot through the upload would stop /api/media for minutes (the second reader).
        async with MEDIA_SLOT:
            whole = await client.download_media(msg, file=bytes) or b""
        size = len(whole)
    if size <= 0:
        raise HTTPException(status_code=422, detail="טלגרם לא מסר קובץ (0 בתים) — אין מה לשמור")
    try:   # the app's folder, marked as its own — once it exists this is a no-op, and the upload below says why if not
        await asyncio.to_thread(_drive, "POST", "/api/fs/mkdir", {"path": "/" + DRIVE_FOLDER, "system": DRIVE_FOLDER})
    except HTTPException:
        pass
    s = await asyncio.to_thread(_drive, "POST", "/api/uploads", {"size": size, "name": name, "mime": mime,
                                                                 "path": folder})
    sid, off, buf = s["id"], 0, bytearray()

    async def put(piece: bytes) -> None:
        """One piece, at `off`. A failed send is not the end of a download that may be minutes old: the drive is
        asked where it stands — it may have stored the piece and only the answer was lost — and the piece is sent
        once more from there; a second failure, or the drive anywhere else, ends it."""
        nonlocal off
        if off + len(piece) > size:                          # never past the size the session was opened with
            raise HTTPException(status_code=502, detail=f"טלגרם מסר יותר מ-{size} בתים — הקובץ לא נשמר")
        for attempt in (1, 2):
            try:
                await asyncio.to_thread(_drive, "PATCH", f"/api/uploads/{sid}", None, piece,
                                        {"Upload-Offset": str(off), "Content-Type": "application/offset+octet-stream",
                                         "Tus-Resumable": "1.0.0"}, 300)
                off += len(piece)
                return
            except HTTPException as e:
                if attempt == 2 or e.status_code == 413:     # the ceiling is not a passing error
                    raise
                log.warning("a piece at %s of %s did not go through (%s) — asking the drive where it stands",
                            off, sid, e.detail)
            await asyncio.sleep(2)
            try:
                st = await asyncio.to_thread(_drive, "GET", f"/api/uploads/{sid}")
                at = int(st.get("offset", -1))
            except (HTTPException, TypeError, ValueError):
                continue                                     # it does not say: the piece is sent again from `off`
            if off + len(piece) == size and st.get("state") in ("complete", "finishing", "done", "failed"):
                # the LAST piece is in: a finished session's part file is gone and its offset reads 0 (the second
                # reader) — the finish poll below says how it ended
                off = size
                return
            if at == off + len(piece):                       # it was stored; only its answer was lost
                off = at
                return
            if at != off:
                raise HTTPException(status_code=502, detail=f"הקבצים במקום {at} ולא {off} — הקובץ לא נשמר")

    try:
        if whole is not None:
            await put(whole)
            whole = None
        else:
            it = client.iter_download(msg.media, request_size=SAVE_REQUEST, file_size=size)
            try:
                async for chunk in it:
                    buf += chunk
                    while len(buf) >= DRIVE_PIECE:
                        with memoryview(buf) as mv:          # ONE copy of the piece (a slice, then bytes, was two)
                            piece = bytes(mv[:DRIVE_PIECE])
                        del buf[:DRIVE_PIECE]
                        await put(piece)
            finally:
                await _close(it)
            if buf:
                await put(bytes(buf))
                buf.clear()
        if off != size:
            raise HTTPException(status_code=502, detail=f"טלגרם מסר {off} מתוך {size} בתים — הקובץ לא נשמר")
    except BaseException:
        await asyncio.to_thread(_drop_upload, sid)
        raise
    try:
        await _await_stored(sid)
    except asyncio.CancelledError:                           # the save's deadline while the drive stores it: the
        await asyncio.to_thread(_drop_upload, sid)           # session goes too, so «failed» never turns up later
        raise


async def _await_stored(sid: str) -> None:
    """The drive hashes and stores what it was sent: seconds, a minute. Done, failed, or given up (which drops it)."""
    misses = 0
    for _ in range(SAVE_FINISH_S // 2):
        try:
            st = await asyncio.to_thread(_drive, "GET", f"/api/uploads/{sid}")
            misses = 0
        except HTTPException:                                # a passing error while it stores is not a failure —
            misses += 1                                      # the drive goes on; five in a row is one
            if misses >= 5:                                  # given up: the session goes, so a file said «failed»
                await asyncio.to_thread(_drop_upload, sid)   # never appears later as «already there»
                raise
            await asyncio.sleep(2)
            continue
        if st.get("state") == "done":
            return
        if st.get("state") == "failed":
            await asyncio.to_thread(_drop_upload, sid)
            raise HTTPException(status_code=413 if st.get("error_status") == 413 else 502,
                                detail=f"{st.get('error') or 'הקבצים לא שמרו אותו'} — הקובץ לא נשמר")
        await asyncio.sleep(2)
    await asyncio.to_thread(_drop_upload, sid)
    raise HTTPException(status_code=504, detail="הקבצים לא סיימו לשמור את הקובץ בתוך עשרים דקות — הקובץ לא נשמר")


#: the saves this process started, by (chat, message): «saving», then «saved» or «failed» with the reason. A save
#: runs in the background — a large file takes minutes, and the console's door gives up on a silent request after
#: 40 s (the second reader) — so the start answers at once, and the state is asked (GET) or heard on the stream.
SAVES: dict[tuple[int, int], dict] = {}


async def _run_save(key, client, msg, media: dict, folder: str, name: str, out: dict, label: str) -> None:
    async with SAVE_SLOT:
        try:
            try:   # a timeout cancels the download inside, which drops its upload session on the way out
                await asyncio.wait_for(stream_to_drive(client, msg, media, folder, name), timeout=SAVE_MAX_S)
            except asyncio.TimeoutError:
                raise HTTPException(status_code=504, detail=f"השמירה לא הסתיימה בתוך {SAVE_MAX_S // 60} דקות — "
                                                            "הקובץ לא נשמר") from None
        except HTTPException as e:
            SAVES[key] = {**out, "state": "failed", "error": e.detail}
            await FLOW.publish("media.failed", f"{label} — לא נשמר בקבצים: {e.detail}", {**out, "error": e.detail})
            return
        except Exception as e:                               # noqa: BLE001 — Telegram's own failure, said in words
            log.warning("saving %s #%s to the drive failed: %r", key[0], key[1], e)
            why = "ההורדה מטלגרם נכשלה — הקובץ לא נשמר"
            SAVES[key] = {**out, "state": "failed", "error": why}
            await FLOW.publish("media.failed", f"{label} — {why}", {**out, "error": why})
            return
    SAVES[key] = {**out, "state": "saved", "already": False}
    await FLOW.publish("media.saved", f"{label} → קבצים{out['path']}", out)


async def save_media(chat_id: int, message_id: int) -> dict:
    """The one verb behind the four channels: the file of one message in a WATCHED chat, any size, into the drive.
    The guards answer at once; the file is saved in the background — its record says «saving», then «saved» (with
    its path) or «failed» (with the reason), and the stream says the same as `media.saved` / `media.failed`."""
    client, msg, media, w = await watched_message(chat_id, message_id)
    if int(media.get("size") or 0) <= 0:
        raise HTTPException(status_code=422, detail="טלגרם לא מסר את גודל הקובץ — אין מה לשמור")
    # the chat's id beside its title: a group and the supergroup it became share a title, and their message numbers
    # come from two counters — without it, «already there» could answer the OTHER chat's file (the second reader)
    folder = f"/{DRIVE_FOLDER}/{_segment(w.get('title')) or 'chat'} ({int(chat_id)})"
    name = save_name(media, message_id)
    out = {"chat_id": int(chat_id), "message_id": int(message_id), "chat": w.get("title") or "", "path": f"{folder}/{name}",
           "name": name, "size": int(media["size"]), "kind": media.get("kind"), "mime": media.get("mime") or ""}
    label = f"«{w.get('title') or chat_id}» #{int(message_id)} [{media.get('label') or 'קובץ'}] {out['size'] / 1048576:.1f}MB"
    key = (int(chat_id), int(message_id))
    there = await asyncio.to_thread(_in_drive, out["path"])
    # from here to the task's start NOTHING awaits: two starts in the same moment cannot both pass (the second reader)
    if (SAVES.get(key) or {}).get("state") == "saving":
        return SAVES[key]
    if there:
        SAVES[key] = {**out, "state": "saved", "already": True}
        return SAVES[key]
    SAVES[key] = {**out, "state": "saving", "already": False}
    task = asyncio.create_task(_run_save(key, client, msg, media, folder, name, out, label))
    BACKGROUND.add(task)
    task.add_done_callback(BACKGROUND.discard)
    return SAVES[key]


def _save_body(body: dict | None) -> tuple[int, int]:
    b = body or {}
    try:
        return int(b.get("chat_id")), int(b.get("message_id"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="chat_id ו-message_id הם מספרים") from None


def _saved_answer(rec: dict):
    return JSONResponse(rec, status_code=202 if rec.get("state") == "saving" else 200)


@app.post("/api/media/save")
async def api_media_save(body: dict | None = None):
    """Start saving the file of one message in a WATCHED chat — any size — into the office's drive, streamed in
    pieces (DGO-1805). 202 {state: saving, path} while it runs; 200 {state: saved, already: true} when it is there."""
    return _saved_answer(await save_media(*_save_body(body)))


@app.get("/api/media/save")
async def api_media_save_state(chat_id: int, message_id: int):
    """Where a save stands: saving, saved (with its path) or failed (with the reason)."""
    rec = SAVES.get((int(chat_id), int(message_id)))
    if rec is None:
        raise HTTPException(status_code=404, detail="לא התחילה כאן שמירה של ההודעה הזו (או שהשירות הופעל מחדש)")
    return _saved_answer(rec)


@app.post("/saveMedia")
async def op_save_media(body: dict | None = None):
    return ok("saveMedia", await save_media(*_save_body(body)))


@app.get("/api/history")
async def api_history(chat_id: int, limit: int = 200):
    return await history(chat_id, max(1, min(HISTORY_MAX, limit)))


@app.post("/history")
async def op_history(body: dict | None = None):
    b = body or {}
    try:
        cid = int(b.get("chat_id"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="chat_id הוא מספר")
    try:
        limit = int(b.get("limit") or 200)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="limit הוא מספר")
    return ok("history", await history(cid, max(1, min(HISTORY_MAX, limit))))


async def mark(chat_id: int, message_id: int, emoji: str) -> dict:
    """A reaction on one message of a WATCHED chat, as the connected account (DGO-1320: the owner marks the
    group's messages 👀 ✍ 👌 🏆). "" takes the account's reaction off. The account, not the bot: the thread before
    the group became a supergroup lives in the old group, which the bot no longer has. Telegram decides what it
    accepts — a chat's allowed reactions, a migrated group — and a refusal is said in Telegram's own words."""
    w = watched().get(str(chat_id))
    if w is None or int(chat_id) == BOTFATHER_ID:
        raise HTTPException(status_code=403, detail="רק צ׳אט שמאזינים לו — הפעל האזנה קודם")
    client = ACCOUNT.need()
    try:
        peer = await client.get_input_entity(int(chat_id))
    except ValueError:
        await client.get_dialogs(limit=500)                  # the in-memory entity cache, as in history
        try:
            peer = await client.get_input_entity(int(chat_id))
        except ValueError:
            raise HTTPException(status_code=404, detail="אין צ׳אט כזה בחשבון")
    reaction = [types.ReactionEmoji(emoticon=emoji)] if emoji else None   # None: the canonical "take it off"
    try:
        await client(functions.messages.SendReactionRequest(peer=peer, msg_id=int(message_id), reaction=reaction))
    except RPCError as e:
        log.info("reaction refused on %s/%s: %r", chat_id, message_id, e)       # the class name goes to the log (G76)
        raise HTTPException(status_code=422, detail=f"טלגרם סירב: {e.message or 'בלי סיבה'}")
    await FLOW.publish("message.mark", f"«{w['title']}» · הודעה {message_id}: {emoji or 'הסימון הוסר'}",
                       {"chat_id": int(chat_id), "message_id": int(message_id), "emoji": emoji})
    return {"chat_id": int(chat_id), "message_id": int(message_id), "emoji": emoji}


def _mark_body(body: dict | None) -> tuple[int, int, str]:
    b = body or {}
    try:
        cid, mid = int(b.get("chat_id")), int(b.get("message_id"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="chat_id ו-message_id הם מספרים")
    # without the variation selector: a phone's «✍️» is Telegram's «✍» (REACTION_INVALID otherwise)
    emoji = str(b.get("emoji") or "").strip().replace("️", "")
    if len(emoji) > 16:
        raise HTTPException(status_code=400, detail="emoji הוא סימן אחד")
    return cid, mid, emoji


@app.post("/api/mark")
async def api_mark(body: dict):
    return await mark(*_mark_body(body))


@app.post("/mark")
async def op_mark(body: dict):
    return ok("mark", await mark(*_mark_body(body)))


@app.get("/api/flow")
async def api_flow(last: int = 50):
    return {"stream": STREAM, "events": await FLOW.last(last), "error": FLOW.error}


@app.post("/flow")
async def op_flow(body: dict | None = None):
    return ok("flow", await api_flow(int((body or {}).get("last") or 50)))


@app.post("/api/bots/token")
async def api_bot_token(body: dict):
    b = body or {}
    bot, label = (b.get("bot") or "").strip(), (b.get("label") or "").strip()
    if not bot or not label:
        raise HTTPException(status_code=400, detail="צריך bot (שם המשתמש של הבוט) ו-label (השם בחיבורים)")
    try:
        res = await bot_token_to_vault(bot, label)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="BotFather לא ענה בזמן")
    if not res.get("ok"):
        raise HTTPException(status_code=422, detail=res.get("detail"))
    return res


@app.get("/")
@app.get("/{route:path}")
def index(route: str = ""):
    """Every screen address answers the page; the page reads its route from its own URL (G83)."""
    if route.startswith("api/") or "static/" in route:          # `/account/static/app.js` is a 404, not the page
        raise HTTPException(status_code=404)
    return FileResponse(os.path.join(ROOT, "static", "index.html"), headers={"Cache-Control": "no-cache"})
