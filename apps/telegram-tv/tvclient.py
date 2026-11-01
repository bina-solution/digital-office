"""tvclient — the one place that talks to Telegram (MTProto, via Telethon).

WHY A USER CLIENT AND NOT A BOT. The Android original is a TDLib user client, and it has to be: the
films are ordinary video messages in channels the owner is a member of, and the Bot API has no
"list my dialogs" and no "give me message 4172 of that channel". A bot can only see what is pushed to
it. So this app holds a USER session — which is exactly why the session string is treated as a
credential and lives in the credential plane, never in this container's own files (accounts.py).

Three responsibilities, and they are the three things that cannot be faked:

  * SESSION   — connect, report whether it is authorised, stop.
  * LIBRARY   — dialogs and message history, normalised into scrapers.Msg (pure data, so the parsing
                policy never touches the network).
  * BYTES     — random access into a file: `iter_range(start, length)`. This is what makes the web
                player possible at all, and it is why the app does not download a 4 GB film to disk
                before showing the first frame.

The one Telethon rule worth writing down: `iter_download`'s `offset` must be a multiple of 4096
(MIN_CHUNK_SIZE) and its `limit` is a count of CHUNKS, not bytes. Both are handled here once, so no
caller has to remember them.
"""
from __future__ import annotations

import asyncio
import io
import logging

from telethon import TelegramClient
from telethon.errors import FileReferenceExpiredError, FileReferenceInvalidError
from telethon.sessions import StringSession
from telethon.tl import types

import scrapers

log = logging.getLogger("telegram-tv.client")

MIN_CHUNK = 4096
#: 512 KiB per Telegram request — the library's own maximum, so a range costs as few round trips as
#: the protocol allows.
CHUNK = 512 * 1024


class TvError(RuntimeError):
    """Something the caller must SHOW the owner: expired session, lost channel access, Telegram
    refusing the file. Never swallowed into an empty list — an empty library and a broken connection
    must not look the same in the UI."""


class TvClient:
    def __init__(self, api_id: int, api_hash: str, session: str, *, label: str = ""):
        self.label = label
        self.api_id = int(api_id)
        self.client = TelegramClient(
            StringSession(session or ""), self.api_id, api_hash,
            device_model="Bina office", system_version="Linux", app_version="telegram-tv 0.1",
            lang_code="he", connection_retries=3, retry_delay=1, timeout=30, request_retries=5,
            flood_sleep_threshold=120,
        )
        self._entities: dict[int, object] = {}
        self._media: dict[str, object] = {}

    # ── session ──────────────────────────────────────────────────────────────────────────────
    async def start(self) -> None:
        await self.client.connect()
        if not await self.client.is_user_authorized():
            raise TvError("החיבור לטלגרם אינו מורשה — צריך להתחבר מחדש")

    async def stop(self) -> None:
        try:
            await self.client.disconnect()
        except Exception:                                    # noqa: BLE001 - teardown never raises
            log.debug("disconnect failed", exc_info=True)

    async def me(self):
        try:
            return await self.client.get_me()
        except Exception:                                    # noqa: BLE001
            return None

    # ── library ──────────────────────────────────────────────────────────────────────────────
    async def entity(self, chat_id: int):
        """The peer object for a chat id, cached. `get_entity` resolves from the session's own cache,
        which is empty on a fresh process — hence the one retry after a dialogs refresh, which is
        what populates it."""
        chat_id = int(chat_id)
        if chat_id in self._entities:
            return self._entities[chat_id]
        try:
            ent = await self.client.get_entity(chat_id)
        except Exception:                                    # noqa: BLE001
            await self.client.get_dialogs(limit=None)
            ent = await self.client.get_entity(chat_id)
        self._entities[chat_id] = ent
        return ent

    async def dialogs(self, limit: int | None = None) -> list[dict]:
        out = []
        async for d in self.client.iter_dialogs(limit=limit):
            ent = d.entity
            out.append({
                "chat_id": int(d.id),
                "title": d.name or "",
                "username": (getattr(ent, "username", None) or ""),
                "kind": ("user" if d.is_user else "group" if d.is_group else "channel"),
                # a broadcast channel and a megagroup both answer `is_channel`; both can hold films,
                # so the distinction kept is the one the UI shows, not one the scanner branches on
                "broadcast": bool(getattr(ent, "broadcast", False)),
                "members": int(getattr(ent, "participants_count", 0) or 0),
            })
        return out

    async def history(self, chat_id: int, limit: int) -> list[scrapers.Msg]:
        """The last `limit` messages of a chat, OLDEST FIRST.

        The ordering is load-bearing: every scraper recovers a film's poster and info from the
        messages BEFORE the file, and iter_messages yields newest-first. Reversing here (once) is
        what keeps that rule out of the scrapers."""
        ent = await self.entity(chat_id)
        msgs: list[scrapers.Msg] = []
        async for m in self.client.iter_messages(ent, limit=int(limit)):
            if getattr(m, "action", None) is not None:       # joins, pins, title changes: not content
                continue
            msgs.append(scrapers.normalize(m))
        msgs.reverse()
        return msgs

    # ── bytes ────────────────────────────────────────────────────────────────────────────────
    async def media_for(self, movie: dict):
        """The downloadable media for a stored movie: refetched from the message, because Telegram
        file references EXPIRE and a stored one starts failing after a while (which would look like
        "this film is broken" for exactly the old films nobody has played recently)."""
        mid = movie["id"]
        if mid in self._media:
            return self._media[mid]
        media = None
        try:
            ent = await self.entity(movie["chat_id"])
            msg = await self.client.get_messages(ent, ids=int(movie["message_id"]))
            if msg is not None:
                media = msg.document or msg.photo or msg.media
        except Exception as e:                               # noqa: BLE001
            log.warning("refetch of %s failed (%s); falling back to the stored document", mid, e)
        if media is None and movie.get("doc_id"):
            # Last resort: the id/access-hash pair captured at scan time. Documents accept an empty
            # file reference; if Telegram refuses, the error surfaces to the player instead of a
            # silent zero-byte response.
            media = types.InputDocument(id=int(movie["doc_id"]),
                                        access_hash=int(movie["access_hash"] or 0),
                                        file_reference=b"")
        if media is None:
            raise TvError("לא נמצא הקובץ בטלגרם — ייתכן שההודעה נמחקה")
        self._media[mid] = media
        return media

    def forget_media(self, movie_id: str) -> None:
        self._media.pop(movie_id, None)

    async def iter_range(self, media, start: int, length: int, *, chunk: int = CHUNK,
                         on_progress=None):
        """Yield exactly the requested byte range, in chunks, straight from Telegram.

        `start` is aligned down to the protocol's 4096 boundary and the surplus is dropped from the
        first chunk, so the bytes the caller receives begin exactly at `start` while Telegram sees a
        legal request."""
        aligned = start - (start % MIN_CHUNK)
        skip = start - aligned
        want = skip + int(length)
        chunks = (want + chunk - 1) // chunk
        produced = 0
        stream = None
        try:
            stream = self.client.iter_download(media, offset=aligned, limit=chunks,
                                               chunk_size=chunk, request_size=chunk)
            async for part in stream:
                data = bytes(part)
                if skip:
                    data = data[skip:]
                    skip = 0
                if not data:
                    continue
                if produced + len(data) > length:
                    data = data[:int(length) - produced]
                produced += len(data)
                if on_progress:
                    on_progress(produced)
                yield data
                if produced >= length:
                    break
        except asyncio.CancelledError:
            # The browser closing the player mid-film is NORMAL; it must not be logged as a failure,
            # and the generator must stop pulling bytes from Telegram.
            raise
        finally:
            if stream is not None:
                try:
                    await stream.close()
                except Exception:                            # noqa: BLE001
                    pass

    async def thumb_bytes(self, movie: dict, _retry: bool = True) -> bytes | None:
        """The poster of a movie: the chat's own photo message when the scraper found one, otherwise
        the video's embedded thumbnail."""
        media = None
        try:
            ent = await self.entity(movie["chat_id"])
            poster_id = int(movie.get("poster_message_id") or 0)
            ids = [poster_id] if poster_id else [int(movie["message_id"])]
            msg = await self.client.get_messages(ent, ids=ids[0])
            if msg is not None:
                media = msg.photo or msg.document or msg.media
        except Exception as e:                               # noqa: BLE001
            log.warning("poster fetch for %s failed: %s", movie.get("id"), e)
            return None
        if media is None:
            return None
        buf = io.BytesIO()
        try:
            await self.client.download_media(media, file=buf, thumb=-1)
        except (FileReferenceExpiredError, FileReferenceInvalidError):
            if not _retry:
                return None
            try:
                await self.client.get_dialogs(limit=None)     # refresh the entity cache, then once more
                return await self.thumb_bytes(movie, _retry=False)
            except Exception:                                # noqa: BLE001
                return None
        except Exception as e:                               # noqa: BLE001
            log.warning("poster download for %s failed: %s", movie.get("id"), e)
            return None
        return buf.getvalue() or None
