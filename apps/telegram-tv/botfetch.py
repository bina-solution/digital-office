"""botfetch — asking a SOURCE BOT for the episodes the library is missing.

The Friends bot in this office is a button menu over ten seasons, and it does not publish a catalogue:
it sends an episode — as a video file — only when that episode is asked for. Everything in the library
today is what the owner happened to request by hand over two evenings. That is why a "channel with 236
episodes" showed 52: the other 184 were never asked for.

So the app asks, the way the owner asked:

    "עונה 5"            → the bot answers with a grid of that season's episode buttons
    "עונה 5 פרק 20"     → the bot posts the episode (in two qualities) into the chat

and then the ordinary scan picks the files up and the series fills in.

This is the only place in the app that writes to Telegram as the owner, and it is built accordingly:

  * it is SLOW on purpose. One message every `TV_FETCH_PAUSE` seconds, and it waits for the bot's file
    before asking for the next: an account that hammers button menus gets flood-limited, and a
    flood-limited account is the owner's whole Telegram, not this app.
  * it asks for what is MISSING, discovered from the bot's own menu, never by guessing a season's
    length — a wrong episode number is a dead message in someone's chat.
  * it is resumable and capped (`TV_FETCH_MAX` requests per run), so it can be started again and
    continues where it stopped instead of starting over.
  * every message it sends is logged with its text, so the owner can audit the conversation.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time

log = logging.getLogger("telegram-tv.botfetch")

PAUSE = float(os.environ.get("TV_FETCH_PAUSE", "12"))
WAIT_FOR_FILE = float(os.environ.get("TV_FETCH_WAIT", "120"))
MAX_REQUESTS = int(os.environ.get("TV_FETCH_MAX", "40"))
#: How many failures in a row end the run. A bot that stopped answering, or a menu that changed shape,
#: must not turn into two hundred messages into the owner's chat.
MAX_FAILURES = int(os.environ.get("TV_FETCH_MAX_FAILURES", "3"))

EP_LABEL = re.compile(r"עונה\s*(\d{1,2})\s*(?:פרק|אפיזודה)\s*(\d{1,3})")


class BotFetch:
    def __init__(self, library):
        self.library = library
        self._job: dict = {"state": "idle"}
        self._task: asyncio.Task | None = None

    def job(self) -> dict:
        return dict(self._job)

    def start(self, chat_id: int, *, seasons: list[int] | None = None,
              only_missing: bool = True) -> dict:
        if self._job.get("state") == "running":
            return self.job()
        self._job = {"state": "running", "phase": "מתחיל", "started": int(time.time()),
                     "chat_id": chat_id, "seasons": seasons or [], "sent": 0, "received": 0,
                     "skipped": 0, "season": None, "episode": None, "log": [], "error": None,
                     "cap": MAX_REQUESTS}
        self._task = asyncio.ensure_future(self._run(chat_id, seasons or list(range(1, 11))))
        return self.job()

    def stop(self) -> dict:
        if self._task is not None:
            self._task.cancel()
            self._task = None
        self._job.update(state="stopped", phase="הופסק", finished=int(time.time()))
        return self.job()

    # ── the run ──────────────────────────────────────────────────────────────────────────────
    async def _run(self, chat_id: int, seasons: list[int]) -> None:
        job = self._job
        failures = 0
        client = await self.library.client()
        entity = await client.entity(chat_id)
        try:
            for season in seasons:
                if job["sent"] >= MAX_REQUESTS:
                    job.update(phase="הסתיים (הגיע למכסה)", state="done", finished=int(time.time()))
                    self._scan(chat_id)
                    return
                job.update(season=season, phase=f"מבקש את עונה {season}")
                episodes = await self._menu_episodes(client, entity, chat_id, season)
                if not episodes:
                    failures += 1
                    self._note(job, f"עונה {season}: לא התקבל תפריט")
                    if failures >= MAX_FAILURES:
                        job.update(state="error", phase="נעצר", error="הבוט לא מחזיר תפריט",
                                   finished=int(time.time()))
                        return
                    continue
                have = self._episodes_in_library(chat_id, season)
                missing = [ep for ep in episodes if ep not in have]
                self._note(job, f"עונה {season}: {len(episodes)} פרקים בתפריט, "
                                f"{len(have)} בספרייה, {len(missing)} חסרים")
                for ep in missing:
                    if job["sent"] >= MAX_REQUESTS:
                        job.update(phase="הסתיים (הגיע למכסה)", state="done", finished=int(time.time()))
                        self._scan(chat_id)
                        return
                    job.update(episode=ep, phase=f"מבקש עונה {season} פרק {ep}")
                    ok = await self._ask(client, entity, chat_id, season, ep)
                    job["sent"] += 1
                    job["received"] += bool(ok)
                    job["skipped"] += (not ok)
                    failures = failures + 1 if not ok else 0
                    self._note(job, f"עונה {season} פרק {ep}: {'התקבל' if ok else 'לא התקבל קובץ'}")
                    if failures >= MAX_FAILURES:
                        job.update(state="error", phase="נעצר",
                                   error="הבוט לא מחזיר קבצים — עצרתי כדי לא להציף את הצ'אט",
                                   finished=int(time.time()))
                        self._scan(chat_id)
                        return
                    await asyncio.sleep(PAUSE)
                self._scan(chat_id)
            job.update(state="done", phase="הסתיים", finished=int(time.time()))
        except asyncio.CancelledError:
            job.update(state="stopped", phase="הופסק", finished=int(time.time()))
            raise
        except Exception as e:                                   # noqa: BLE001
            log.warning("bot fetch failed: %s", e, exc_info=True)
            job.update(state="error", phase="שגיאה", error=str(e), finished=int(time.time()))

    async def _menu_episodes(self, client, entity, chat_id: int, season: int) -> list[int]:
        """Ask for the season and read the episode numbers out of the BOT'S OWN buttons.

        The list comes from the bot, never from an assumption about how long a season is: asking for an
        episode that does not exist puts a dead message in the owner's chat, and a wrong season length
        would do it twenty times over."""
        await client.client.send_message(entity, f"עונה {season}")
        log.info("botfetch: sent 'עונה %s'", season)
        deadline = time.time() + WAIT_FOR_FILE
        while time.time() < deadline:
            await asyncio.sleep(2.0)
            msgs = await client.history(chat_id, 3)
            for m in reversed(msgs):
                labels = [lab for row in (m.buttons or []) for lab in row]
                if not any(f"עונה {season}" in lab for lab in labels):
                    continue
                found = set()
                for lab in labels:
                    hit = EP_LABEL.search(lab)
                    if hit and int(hit.group(1)) == season:
                        found.add(int(hit.group(2)))
                if found:
                    return sorted(found)
        return []

    async def _ask(self, client, entity, chat_id: int, season: int, episode: int) -> bool:
        """Ask for one episode and wait until the file is actually in the chat."""
        before = {m.id for m in await client.history(chat_id, 5)}
        await client.client.send_message(entity, f"עונה {season} פרק {episode}")
        log.info("botfetch: sent 'עונה %s פרק %s'", season, episode)
        deadline = time.time() + WAIT_FOR_FILE
        while time.time() < deadline:
            await asyncio.sleep(3.0)
            msgs = await client.history(chat_id, 5)
            new_videos = [m for m in msgs if m.kind == "video" and m.id not in before]
            if new_videos:
                return True
        return False

    def _episodes_in_library(self, chat_id: int, season: int) -> set[int]:
        """Which episodes of that season the library already holds — from the store, by chat and
        season, with no assumption about the show's name."""
        rows = self.library.store.movies(chat_ids=[chat_id], limit=5000)
        return {int(r.get("episode") or 0) for r in rows
                if int(r.get("season") or 0) == season and int(r.get("episode") or 0) > 0}

    def _scan(self, chat_id: int) -> None:
        """Bring what the bot just sent into the library. Deliberately the ordinary scan, so a fetched
        episode is indistinguishable from one that was always there."""
        try:
            self.library.start_sync(full=False, only_chat=chat_id)
        except Exception as e:                                   # noqa: BLE001
            log.info("botfetch: scan after fetch not started: %s", e)

    def _note(self, job: dict, line: str) -> None:
        log.info("botfetch: %s", line)
        job.setdefault("log", []).append(f"{time.strftime('%H:%M:%S')} {line}")
        del job["log"][:-60]
