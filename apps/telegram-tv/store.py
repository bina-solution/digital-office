"""store — the catalog cache: chats, movies and the few facts that outlive one request.

This is a CACHE of something that lives in Telegram, and that is the whole design constraint: every
row here can be rebuilt from a re-scan, so nothing in this file is state the deployment would mourn.
The one thing it is NOT allowed to be is the source of truth about ACCOUNTS — the session string, the
api_id and the api_hash live in the credential plane (connections), never here (see accounts.py).

Two nouns, matching the vocabulary of the app:

  chat   — a Telegram dialog the office can see in the library. `enabled` says the owner wants its
           contents in the TV, `scraper` says HOW a movie is recovered from it (see scrapers.py), and
           `scraper_locked` records that a person chose it, so a later auto-detection pass may not
           silently overrule them.
  movie  — one playable file, identified by `<chat_id>:<message_id>`. That id is STABLE across
           re-scans on purpose: it is a URL path (/api/stream/<id>) and a resume position in the
           browser, and a random uuid — what the Android original used — would lose both on every
           refresh.

sqlite (stdlib), one connection per process, guarded by a lock. The app is a single uvicorn worker,
so this is sufficient; it would not be under multiple workers, and the schema does not pretend
otherwise.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
  chat_id        INTEGER PRIMARY KEY,
  account_id     TEXT    NOT NULL DEFAULT '',
  title          TEXT    NOT NULL DEFAULT '',
  kind           TEXT    NOT NULL DEFAULT '',
  username       TEXT    NOT NULL DEFAULT '',
  has_video      INTEGER NOT NULL DEFAULT 0,
  enabled        INTEGER NOT NULL DEFAULT 0,
  scraper        TEXT    NOT NULL DEFAULT '',
  scraper_locked INTEGER NOT NULL DEFAULT 0,
  movie_count    INTEGER NOT NULL DEFAULT 0,
  seen_at        INTEGER NOT NULL DEFAULT 0,
  synced_at      INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS movies (
  id                TEXT    PRIMARY KEY,
  chat_id           INTEGER NOT NULL,
  message_id        INTEGER NOT NULL,
  account_id        TEXT    NOT NULL DEFAULT '',
  title             TEXT    NOT NULL DEFAULT '',
  year              TEXT    NOT NULL DEFAULT '',
  rating            TEXT    NOT NULL DEFAULT '',
  tags              TEXT    NOT NULL DEFAULT '',
  description       TEXT    NOT NULL DEFAULT '',
  quality           TEXT    NOT NULL DEFAULT '',
  file_name         TEXT    NOT NULL DEFAULT '',
  mime              TEXT    NOT NULL DEFAULT '',
  size              INTEGER NOT NULL DEFAULT 0,
  duration          INTEGER NOT NULL DEFAULT 0,
  width             INTEGER NOT NULL DEFAULT 0,
  height            INTEGER NOT NULL DEFAULT 0,
  doc_id            INTEGER NOT NULL DEFAULT 0,
  access_hash       INTEGER NOT NULL DEFAULT 0,
  poster_message_id INTEGER NOT NULL DEFAULT 0,
  date              INTEGER NOT NULL DEFAULT 0,
  scraped_at        INTEGER NOT NULL DEFAULT 0,
  series            TEXT    NOT NULL DEFAULT '',
  series_key        TEXT    NOT NULL DEFAULT '',
  season            INTEGER NOT NULL DEFAULT 0,
  episode           INTEGER NOT NULL DEFAULT 0,
  quality_label     TEXT    NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL DEFAULT '');
"""

#: Indexes are created AFTER the migrations, never inside SCHEMA: `CREATE TABLE IF NOT EXISTS` leaves
#: an existing table alone, so an index on a column the migrations are about to add would be a hard
#: `no such column` at startup — on exactly the deployment that has data, and only there.
INDEXES = """
CREATE INDEX IF NOT EXISTS movies_chat ON movies(chat_id);
CREATE INDEX IF NOT EXISTS movies_series ON movies(series_key, season, episode);
"""

#: Columns added AFTER the first released schema. `CREATE TABLE IF NOT EXISTS` does not add a column
#: to a table that already exists, so a shipped app that gains a column needs an explicit migration —
#: otherwise the ALTER-less upgrade path is a silent `no such column` on every read, on the one
#: deployment that has data. Applied in order, idempotently, at open.
MIGRATIONS = (
    # `enabled_locked` = a PERSON decided whether this chat is in the library. Only a person may
    # change it again; automatic discovery sets `enabled` while this is 0 (see mark_discovered).
    ("chats", "enabled_locked", "INTEGER NOT NULL DEFAULT 0"),
    # `peeked_at` = when discovery last looked at this chat's recent messages. Without it every sync
    # re-reads every dialog, which is what earns a FloodWait from Telegram (measured: 14s sleeps).
    ("chats", "peeked_at", "INTEGER NOT NULL DEFAULT 0"),
    # how many of a chat's messages one scan reads. A series channel publishes hundreds of episodes
    # (Friends: 236 x 2 qualities), and the deployment-wide default exists for the ordinary channel,
    # not for the one a person adopted on purpose.
    ("chats", "scan_limit", "INTEGER NOT NULL DEFAULT 0"),
    # the episode coordinates of a film, filled at scan time by episodes.py (0/'' = a standalone film)
    ("movies", "series", "TEXT NOT NULL DEFAULT ''"),
    ("movies", "series_key", "TEXT NOT NULL DEFAULT ''"),
    ("movies", "season", "INTEGER NOT NULL DEFAULT 0"),
    ("movies", "episode", "INTEGER NOT NULL DEFAULT 0"),
    ("movies", "quality_label", "TEXT NOT NULL DEFAULT ''"),
    # what ffprobe found inside the file (container, codecs) — cached because probing costs a couple
    # of MB of download, and the answer never changes for a message
    ("movies", "probe_json", "TEXT NOT NULL DEFAULT ''"),
)

#: The columns of a movie, in the order `replace_chat_movies` writes them. Kept as one list so the
#: INSERT and the row→dict projection can never disagree about the shape.
MOVIE_COLUMNS = (
    "id", "chat_id", "message_id", "account_id", "title", "year", "rating", "tags", "description",
    "quality", "file_name", "mime", "size", "duration", "width", "height", "doc_id", "access_hash",
    "poster_message_id", "date", "scraped_at", "series", "series_key", "season", "episode",
    "quality_label",
)


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript("PRAGMA journal_mode=WAL;\n" + SCHEMA)
            self._migrate()
            self._db.executescript(INDEXES)
            self._db.commit()

    def _migrate(self) -> None:
        for table, column, decl in MIGRATIONS:
            have = {r["name"] for r in self._db.execute(f"PRAGMA table_info({table})").fetchall()}
            if column not in have:
                self._db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ── chats ────────────────────────────────────────────────────────────────────────────────
    def upsert_chat(self, *, chat_id: int, account_id: str, title: str, kind: str, username: str,
                    seen_at: int | None = None) -> None:
        """Record that a dialog EXISTS, and nothing else.

        It never touches `enabled`, `scraper` or `peeked_at`: those are the outcome of a pass or a
        decision, and an identity update that also reset them would make the settings screen a lottery
        (and, in the first release of this file, silently disabled every chat it had just discovered —
        the discovery pass found films, the scan then had nothing enabled to scan, and the library came
        out empty while every log said the sync had worked)."""
        now = int(time.time()) if seen_at is None else int(seen_at)
        with self._lock:
            self._db.execute(
                """INSERT INTO chats (chat_id, account_id, title, kind, username, seen_at)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(chat_id) DO UPDATE SET
                     title=excluded.title, kind=excluded.kind, username=excluded.username,
                     seen_at=excluded.seen_at,
                     account_id=CASE WHEN excluded.account_id<>'' THEN excluded.account_id
                                     ELSE chats.account_id END""",
                (int(chat_id), account_id, title or "", kind or "", username or "", now))
            self._db.commit()

    def mark_discovered(self, chat_id: int, *, has_video: bool, peeked_at: int | None = None) -> None:
        """The result of looking at a chat's recent messages.

        A chat that HAS video is switched on automatically — that is how the library fills itself on
        the first sync, the way the Android original showed every chat — UNLESS a person has already
        decided about it (`enabled_locked`). A chat with no video is left exactly as it was: not
        disabled (its films may be older than the peek window) and not enabled (there is nothing to
        show yet)."""
        now = int(time.time()) if peeked_at is None else int(peeked_at)
        with self._lock:
            self._db.execute(
                """UPDATE chats SET has_video=?, peeked_at=?,
                     enabled=CASE WHEN ?=1 AND enabled_locked=0 THEN 1 ELSE enabled END
                   WHERE chat_id=?""",
                (1 if has_video else 0, now, 1 if has_video else 0, int(chat_id)))
            self._db.commit()

    def chats_to_peek(self, *, older_than: int) -> list[dict]:
        """Dialogs whose recent messages discovery should look at again (never-peeked first)."""
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM chats WHERE peeked_at < ? ORDER BY peeked_at ASC, lower(title)",
                (int(older_than),)).fetchall()
        return [dict(r) for r in rows]

    def chats_to_scan(self, limit: int) -> tuple[list[dict], int]:
        """(chats to scan now, how many are left over) — a ROTATION, not the same head every time.

        Ordered by `synced_at` ascending, so a chat that has never been scanned comes first and one
        that was scanned in the previous run comes last. With a per-run cap that means repeated syncs
        walk the whole library instead of re-reading the same first N channels forever — which is what
        a plain "top N by size" would do."""
        with self._lock:
            # `enabled_locked` = a person adopted this chat by hand, so the "does it look like it
            # has films" heuristic must not be allowed to drop it out of the scan: a series channel
            # between seasons posts no video for weeks, and a library that silently forgets it is
            # exactly the failure the owner cannot see.
            where = "enabled=1 AND (has_video=1 OR enabled_locked=1)"
            total = self._db.execute(f"SELECT COUNT(*) n FROM chats WHERE {where}").fetchone()["n"]
            rows = self._db.execute(
                f"""SELECT * FROM chats WHERE {where}
                    ORDER BY synced_at ASC, movie_count DESC, lower(title) LIMIT ?""",
                (int(limit),)).fetchall() if limit else self._db.execute(
                f"""SELECT * FROM chats WHERE {where}
                    ORDER BY synced_at ASC, movie_count DESC, lower(title)""").fetchall()
        return [dict(r) for r in rows], max(0, total - len(rows))

    def prune_kinds(self, kinds: set[str]) -> int:
        """Forget dialogs of a kind this app does not library (private chats by default).

        Rows a PERSON enabled or configured are kept whatever their kind: the settings screen is his,
        and silently deleting the row behind a chat he switched on is the one thing a housekeeping
        pass must not do. Returns how many rows were dropped."""
        kinds = {k for k in kinds if k}
        if not kinds:
            return 0
        marks = ",".join("?" * len(kinds))
        with self._lock:
            rows = self._db.execute(
                f"""SELECT chat_id FROM chats WHERE kind NOT IN ({marks})
                    AND enabled_locked=0 AND enabled=0 AND scraper_locked=0""",
                tuple(sorted(kinds))).fetchall()
            ids = [r["chat_id"] for r in rows]
            for cid in ids:
                self._db.execute("DELETE FROM movies WHERE chat_id=?", (cid,))
                self._db.execute("DELETE FROM chats WHERE chat_id=?", (cid,))
            self._db.commit()
        return len(ids)

    def set_chat(self, chat_id: int, *, enabled: bool | None = None, scraper: str | None = None,
                 lock_scraper: bool | None = None, lock_enabled: bool | None = None,
                 scan_limit: int | None = None) -> None:
        sets, args = [], []
        if enabled is not None:
            sets.append("enabled=?")
            args.append(1 if enabled else 0)
        if scraper is not None:
            sets.append("scraper=?")
            args.append(scraper)
        if lock_scraper is not None:
            sets.append("scraper_locked=?")
            args.append(1 if lock_scraper else 0)
        if lock_enabled is not None:
            sets.append("enabled_locked=?")
            args.append(1 if lock_enabled else 0)
        if scan_limit is not None:
            sets.append("scan_limit=?")
            args.append(max(0, int(scan_limit)))
        if not sets:
            return
        with self._lock:
            self._db.execute(f"UPDATE chats SET {', '.join(sets)} WHERE chat_id=?", (*args, int(chat_id)))
            self._db.commit()

    def chat(self, chat_id: int) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM chats WHERE chat_id=?", (int(chat_id),)).fetchone()
        return dict(row) if row else None

    def chats(self, *, enabled_only: bool = False, with_video: bool = False) -> list[dict]:
        q, args = "SELECT * FROM chats", []
        where = []
        if enabled_only:
            where.append("enabled=1")
        if with_video:
            where.append("has_video=1")
        if where:
            q += " WHERE " + " AND ".join(where)
        q += " ORDER BY movie_count DESC, lower(title)"
        with self._lock:
            return [dict(r) for r in self._db.execute(q, args).fetchall()]

    def mark_synced(self, chat_id: int, *, movie_count: int, scraper: str,
                    synced_at: int | None = None) -> None:
        now = int(time.time()) if synced_at is None else int(synced_at)
        with self._lock:
            self._db.execute(
                """UPDATE chats SET movie_count=?, synced_at=?,
                     scraper=CASE WHEN scraper_locked=1 AND scraper<>'' THEN scraper ELSE ? END
                   WHERE chat_id=?""",
                (int(movie_count), now, scraper, int(chat_id)))
            self._db.commit()

    # ── movies ───────────────────────────────────────────────────────────────────────────────
    def replace_chat_movies(self, chat_id: int, movies: list[dict], *, scraped_at: int | None = None) -> int:
        """Replace every movie of one chat with the result of a scan.

        A scan is authoritative for the window it covered: a movie whose message was deleted in
        Telegram must disappear from the library, and an upsert-only writer would keep serving a
        dead card forever. The cost is that a scan limited to N messages drops what the previous,
        longer scan found — which is why the scan limit is a setting, not a constant (sync_limit)."""
        now = int(time.time()) if scraped_at is None else int(scraped_at)
        rows = []
        for m in movies:
            if not movie_is_complete(m):
                continue
            rows.append(tuple(now if c == "scraped_at" else m.get(c) for c in MOVIE_COLUMNS))
        with self._lock:
            self._db.execute("DELETE FROM movies WHERE chat_id=?", (int(chat_id),))
            if rows:
                self._db.executemany(
                    f"INSERT OR REPLACE INTO movies ({','.join(MOVIE_COLUMNS)}) "
                    f"VALUES ({','.join('?' * len(MOVIE_COLUMNS))})", rows)
            self._db.execute(
                "UPDATE chats SET movie_count=(SELECT COUNT(*) FROM movies WHERE chat_id=?) WHERE chat_id=?",
                (int(chat_id), int(chat_id)))
            self._db.commit()
        return len(rows)

    def movie(self, movie_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM movies WHERE id=?", (movie_id,)).fetchone()
        return dict(row) if row else None

    def movies(self, *, chat_ids: list[int] | None = None, q: str = "", limit: int = 2000,
               offset: int = 0) -> list[dict]:
        where, args = [], []
        if chat_ids:
            where.append(f"chat_id IN ({','.join('?' * len(chat_ids))})")
            args += [int(c) for c in chat_ids]
        if q:
            where.append("(title LIKE ? OR description LIKE ? OR tags LIKE ? OR file_name LIKE ?)")
            like = f"%{q}%"
            args += [like, like, like, like]
        sql = "SELECT * FROM movies"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY date DESC, id DESC LIMIT ? OFFSET ?"
        args += [int(limit), int(offset)]
        with self._lock:
            return [dict(r) for r in self._db.execute(sql, args).fetchall()]

    def counts(self) -> dict:
        with self._lock:
            c = self._db.execute("SELECT COUNT(*) n FROM chats").fetchone()["n"]
            e = self._db.execute("SELECT COUNT(*) n FROM chats WHERE enabled=1").fetchone()["n"]
            m = self._db.execute("SELECT COUNT(*) n FROM movies").fetchone()["n"]
        return {"chats": c, "chats_enabled": e, "movies": m}

    # ── series ───────────────────────────────────────────────────────────────────────────────
    def series(self) -> list[dict]:
        """Every show in the library, with its episode count and its poster (taken from the FIRST
        episode, because a show's identity in this UI is one card, not a wall of files)."""
        with self._lock:
            rows = self._db.execute(
                """SELECT m.series_key, m.series, m.chat_id, COUNT(DISTINCT m.season * 1000 + m.episode) n,
                          MIN(m.season) season_from, MAX(m.season) season_to,
                          (SELECT id FROM movies p WHERE p.series_key = m.series_key
                            ORDER BY p.season, p.episode, p.size DESC LIMIT 1) poster_id
                     FROM movies m WHERE m.series_key <> ''
                    GROUP BY m.series_key ORDER BY n DESC, m.series""").fetchall()
        return [dict(r) for r in rows]

    def series_rows(self, series_key: str) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                """SELECT * FROM movies WHERE series_key=?
                   ORDER BY season, episode, size DESC""", (series_key,)).fetchall()
        return [dict(r) for r in rows]

    def movie_ids_missing_episodes(self) -> list[dict]:
        """Rows whose episode fields were never derived (i.e. every row written before episodes.py
        existed). Re-deriving them from the title costs nothing and rescues a whole series library
        without re-reading a single Telegram message."""
        with self._lock:
            rows = self._db.execute(
                "SELECT id, chat_id, title, file_name FROM movies WHERE series_key=''").fetchall()
        return [dict(r) for r in rows]

    def set_episode_fields(self, movie_id: str, *, series: str, series_key: str, season: int,
                           episode: int, quality_label: str) -> None:
        with self._lock:
            self._db.execute(
                """UPDATE movies SET series=?, series_key=?, season=?, episode=?, quality_label=?
                    WHERE id=?""",
                (series or "", series_key or "", int(season or 0), int(episode or 0),
                 quality_label or "", movie_id))
            self._db.commit()

    def set_media_info(self, movie_id: str, *, duration: int, width: int, height: int) -> None:
        """Write back what ffprobe learned.

        A film delivered as a DOCUMENT carries no duration or resolution in Telegram's own metadata
        (the file name has it, the message does not), so before a probe every episode of a series had
        `duration: 0` — which means no progress bar, no "22 דק׳", no resume that knows where the end
        is. The probe costs one small read and answers all three permanently."""
        sets, args = [], []
        if duration and int(duration) > 0:
            sets.append("duration=?")
            args.append(int(duration))
        if width and height:
            sets.append("width=?")
            args.append(int(width))
            sets.append("height=?")
            args.append(int(height))
        if not sets:
            return
        with self._lock:
            self._db.execute(f"UPDATE movies SET {', '.join(sets)} WHERE id=?", (*args, movie_id))
            self._db.commit()

    def get_probe(self, movie_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT probe_json FROM movies WHERE id=?", (movie_id,)).fetchone()
        if not row or not row["probe_json"]:
            return None
        try:
            import json as _json
            return _json.loads(row["probe_json"])
        except ValueError:
            return None

    def set_probe(self, movie_id: str, probe: dict) -> None:
        import json as _json
        with self._lock:
            self._db.execute("UPDATE movies SET probe_json=? WHERE id=?",
                             (_json.dumps(probe, ensure_ascii=False), movie_id))
            self._db.commit()

    def forget_chat_movies(self, chat_id: int) -> None:
        with self._lock:
            self._db.execute("DELETE FROM movies WHERE chat_id=?", (int(chat_id),))
            self._db.execute("UPDATE chats SET movie_count=0, synced_at=0 WHERE chat_id=?", (int(chat_id),))
            self._db.commit()

    # ── meta ─────────────────────────────────────────────────────────────────────────────────
    def meta_get(self, key: str, default=None):
        with self._lock:
            row = self._db.execute("SELECT v FROM meta WHERE k=?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["v"])
        except ValueError:
            return default

    def meta_set(self, key: str, value) -> None:
        with self._lock:
            self._db.execute("INSERT INTO meta (k, v) VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                             (key, json.dumps(value, ensure_ascii=False)))
            self._db.commit()


def movie_is_complete(m: dict) -> bool:
    """A movie row is only written when it has the things a card needs: an id, a chat and a
    message to fetch the file from. A scanner bug that produces half-rows must not reach the UI as a
    card that cannot be played."""
    return bool(m.get("id")) and bool(m.get("message_id")) and bool(m.get("chat_id"))
