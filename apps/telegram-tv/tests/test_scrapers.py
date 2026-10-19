"""Tests for the pure part of the app: the scrapers and the catalogue cache.

The parsing layer is where this app is most likely to break — a channel changes its poster format and
films silently lose their titles — and it is the part that needs no Telegram account, no network and
no container to test. Run it with:

    cd apps/telegram-tv && python3 -m unittest discover -s tests -v
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scrapers as S            # noqa: E402
from store import Store         # noqa: E402

AMSALEM_POSTER = '''"המטריקס"
שנה - 1999
איכות - BLU-RAY 1080p
דירוג: IMDb לסרט - 8.7
תרגום מובנה. עברית
ז'אנר - פעולה, מדע בדיוני
תקציר👇
האקר מגלה שהעולם שבו הוא חי הוא סימולציה.'''

# The regression that motivated the port: an info message mentioning a year that is NOT the film's
# (a file list, a resolution, "משנת 2019 ואילך") must not become the film's year.
NOISY_POSTER = '''"סרט אחר"
אוסף 2018-2022, 40 סרטים
איכות - HD 720p'''


def msg(i, kind, **kw):
    return S.Msg(id=i, chat_id=-100123, date=1_700_000_000 + i, kind=kind, **kw)


class DetectTests(unittest.TestCase):
    def test_hebrew_poster_chat_is_amsalem(self):
        msgs = [msg(1, "photo"), msg(2, "text", text=AMSALEM_POSTER), msg(3, "video", file_name="x.mkv")]
        self.assertEqual(S.detect(msgs), "amsalem")

    def test_plain_video_chat_is_default(self):
        msgs = [msg(1, "video", file_name="a.mp4"), msg(2, "video", file_name="b.mp4")]
        self.assertEqual(S.detect(msgs), "default")

    def test_album_is_detected_between_poster_and_file(self):
        msgs = [msg(1, "photo", grouped_id=7), msg(2, "video", grouped_id=7, file_name="a.mp4")]
        self.assertEqual(S.detect(msgs), "album")

    def test_empty_chat_scores_nothing(self):
        self.assertEqual(S.detect([msg(1, "text", text="שלום")]), "default")


class ParseTests(unittest.TestCase):
    def test_every_hebrew_field_is_recovered(self):
        parsed = S.parse_info(AMSALEM_POSTER)
        self.assertEqual(parsed["title"], "המטריקס")
        self.assertEqual(parsed["year"], "1999")
        self.assertEqual(parsed["quality"], "BLU-RAY 1080p")
        self.assertEqual(parsed["rating"], "8.7")
        self.assertEqual(parsed["tags"], ["פעולה", "מדע בדיוני"])
        self.assertIn("סימולציה", parsed["description"])

    def test_a_poster_with_only_a_title_still_parses(self):
        parsed = S.parse_info('"סרט"')
        self.assertEqual(parsed["title"], "סרט")
        self.assertNotIn("year", parsed)

    def test_a_year_inside_a_noisy_poster_is_not_claimed_as_the_film_year(self):
        # The bare-year fallback is only trusted in SHORT texts, so a long collection notice does not
        # silently stamp 2018 on a film that has no year at all.
        self.assertNotIn("year", S.parse_info(NOISY_POSTER + "\n" + ("עוד טקסט. " * 40)))


class ExtractTests(unittest.TestCase):
    def test_amsalem_movie_carries_poster_and_fields(self):
        msgs = [msg(1, "photo"), msg(2, "text", text=AMSALEM_POSTER),
                msg(3, "video", file_name="The.Matrix.1999.1080p.mkv", size=2_000_000_000, duration=8160)]
        movies = S.extract("amsalem", msgs, -100123)
        self.assertEqual(len(movies), 1)
        m = movies[0]
        self.assertEqual(m["id"], "-100123:3")
        self.assertEqual(m["title"], "המטריקס")
        self.assertEqual(m["poster_message_id"], 1)
        self.assertEqual(m["size"], 2_000_000_000)
        self.assertIn("ערוץ:-100123", m["tags"])

    def test_neighbours_are_looked_for_BACKWARDS_only(self):
        # A film must never adopt the NEXT film's poster — that is the failure that looks like a
        # working feature showing the wrong cover.
        msgs = [msg(1, "video", file_name="first.mp4"),
                msg(2, "photo"), msg(3, "text", text=AMSALEM_POSTER)]
        movies = S.extract("album", msgs, -100123)
        self.assertEqual(len(movies), 1)
        self.assertEqual(movies[0]["poster_message_id"], 0)

    def test_default_titles_fall_back_to_the_file_name(self):
        msgs = [msg(1, "video", file_name="The.Matrix.1999.1080p.x264.mkv")]
        self.assertEqual(S.extract("default", msgs, -100123)[0]["title"], "The Matrix 1999 1080p x264")


class FloorTests(unittest.TestCase):
    """A sticker is not a film, and neither is a 193 KB clip (both observed in the real library)."""

    def test_a_tiny_video_is_not_a_movie(self):
        msgs = [msg(1, "video", file_name="sticker.webm", size=193_824),
                msg(2, "video", file_name="Film.2020.mkv", size=4_000_000_000)]
        titles = [m["title"] for m in S.extract("default", msgs, -100123)]
        self.assertEqual(titles, ["Film 2020"])

    def test_an_unknown_size_is_kept(self):
        msgs = [msg(1, "video", file_name="Film.2020.mkv", size=0)]
        self.assertEqual(len(S.extract("default", msgs, -100123)), 1)

    def test_a_sticker_document_is_not_a_video(self):
        class DocumentAttributeSticker:     # the real Telethon class name is what the check reads
            file_name = "s.webm"

        class Doc:
            mime_type = "video/webm"
            size = 999
            id = 1
            access_hash = 2
            thumbs = None
            attributes = [DocumentAttributeSticker()]

        class Message:
            id = 5
            chat_id = -100123
            date = None
            grouped_id = 0
            document = Doc()
            photo = None
            video = None
            message = ""
            action = None

        self.assertEqual(S.normalize(Message()).kind, "other")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="tv-test-")
        self.store = Store(os.path.join(self.tmp, "library.db"))

    def tearDown(self):
        self.store.close()

    def test_settings_survive_a_discovery_pass(self):
        self.store.upsert_chat(chat_id=1, account_id="a", title="ערוץ", kind="channel", username="")
        self.store.mark_discovered(1, has_video=True)
        self.store.set_chat(1, enabled=False, lock_enabled=True, scraper="album", lock_scraper=True)
        # a later discovery pass must not resurrect the choice the owner made
        self.store.upsert_chat(chat_id=1, account_id="a", title="ערוץ", kind="channel", username="")
        self.store.mark_discovered(1, has_video=True)
        chat = self.store.chat(1)
        self.assertFalse(chat["enabled"])
        self.assertEqual(chat["scraper"], "album")

    def test_discovery_switches_on_a_chat_that_has_films(self):
        # THE regression this suite exists for: the first release inserted the chat as "no video yet"
        # and the discovery pass could no longer change that, so every sync ended with an empty
        # library while the logs reported success.
        self.store.upsert_chat(chat_id=1, account_id="a", title="ערוץ", kind="channel", username="")
        self.assertEqual(self.store.chat(1)["enabled"], 0)
        self.store.mark_discovered(1, has_video=True)
        self.assertEqual(self.store.chat(1)["enabled"], 1)

    def test_a_chat_without_film_is_not_switched_on(self):
        self.store.upsert_chat(chat_id=2, account_id="a", title="מודעות", kind="channel", username="")
        self.store.mark_discovered(2, has_video=False)
        self.assertEqual(self.store.chat(2)["enabled"], 0)

    def test_scan_rotates_so_a_cap_covers_the_whole_library(self):
        for chat_id in (1, 2, 3):
            self.store.upsert_chat(chat_id=chat_id, account_id="a", title=f"ערוץ {chat_id}",
                                   kind="channel", username="")
            self.store.mark_discovered(chat_id, has_video=True)
        first, remaining = self.store.chats_to_scan(2)
        self.assertEqual([c["chat_id"] for c in first], [1, 2])
        self.assertEqual(remaining, 1)
        for c in first:
            self.store.mark_synced(c["chat_id"], movie_count=0, scraper="default")
        second, remaining2 = self.store.chats_to_scan(2)
        self.assertEqual([c["chat_id"] for c in second], [3, 1])   # never-scanned first, then oldest
        self.assertEqual(remaining2, 1)                            # chat 2 is still owed a scan

    def test_a_database_from_the_previous_release_gains_the_new_columns(self):
        import sqlite3
        old = os.path.join(self.tmp, "old.db")
        db = sqlite3.connect(old)
        db.executescript("""CREATE TABLE chats (chat_id INTEGER PRIMARY KEY, account_id TEXT NOT NULL DEFAULT '',
                            title TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT '',
                            username TEXT NOT NULL DEFAULT '', has_video INTEGER NOT NULL DEFAULT 0,
                            enabled INTEGER NOT NULL DEFAULT 0, scraper TEXT NOT NULL DEFAULT '',
                            scraper_locked INTEGER NOT NULL DEFAULT 0, movie_count INTEGER NOT NULL DEFAULT 0,
                            seen_at INTEGER NOT NULL DEFAULT 0, synced_at INTEGER NOT NULL DEFAULT 0);
                            INSERT INTO chats (chat_id, title, has_video, enabled) VALUES (7, 'ישן', 1, 1);""")
        db.commit()
        db.close()
        migrated = Store(old)                              # must migrate, not raise on the first read
        try:
            self.assertEqual(migrated.chat(7)["enabled_locked"], 0)
            self.assertEqual(migrated.chat(7)["peeked_at"], 0)
            migrated.mark_discovered(7, has_video=True)
            self.assertEqual(migrated.chat(7)["has_video"], 1)
        finally:
            migrated.close()

    def test_a_rescan_is_authoritative_for_the_chat(self):
        rows = [{"id": "1:10", "chat_id": 1, "message_id": 10, "title": "א", "size": 5},
                {"id": "1:11", "chat_id": 1, "message_id": 11, "title": "ב", "size": 6}]
        self.store.upsert_chat(chat_id=1, account_id="a", title="ערוץ", kind="channel", username="")
        self.store.mark_discovered(1, has_video=True)
        self.assertEqual(self.store.replace_chat_movies(1, rows), 2)
        self.assertEqual(self.store.replace_chat_movies(1, rows[:1]), 1)
        self.assertEqual(self.store.counts()["movies"], 1)      # the deleted message left the library

    def test_a_half_row_never_reaches_the_ui(self):
        self.store.upsert_chat(chat_id=1, account_id="a", title="ערוץ", kind="channel", username="")
        self.store.mark_discovered(1, has_video=True)
        self.assertEqual(self.store.replace_chat_movies(1, [{"id": "1:9", "chat_id": 1}]), 0)

    def test_a_locked_scraper_is_not_overwritten_by_auto_detection(self):
        self.store.upsert_chat(chat_id=1, account_id="a", title="ערוץ", kind="channel", username="")
        self.store.mark_discovered(1, has_video=True)
        self.store.set_chat(1, scraper="amsalem", lock_scraper=True)
        self.store.mark_synced(1, movie_count=0, scraper="default")
        self.assertEqual(self.store.chat(1)["scraper"], "amsalem")


class RangeTests(unittest.TestCase):
    """parse_range decides whether seeking works. It is tested through app.py, so it needs fastapi —
    skipped locally, and run for real inside the container:

        docker exec telegram-tv-local python -m unittest discover -s /app/tests -v
    """

    @classmethod
    def setUpClass(cls):
        try:
            import app                                     # noqa: F401
        except ImportError as e:                           # pragma: no cover - local runs only
            raise unittest.SkipTest(f"app.py not importable here ({e})")

    def test_open_ended_request_is_a_window_not_the_whole_film(self):
        import app
        self.assertEqual(app.parse_range("bytes=0-", 100_000_000, window=1_000)[:2], (0, 999))
        self.assertTrue(app.parse_range("bytes=0-", 100_000_000, window=1_000)[2])

    def test_no_header_serves_from_the_start(self):
        import app
        self.assertEqual(app.parse_range("", 5_000, window=1_000)[:2], (0, 999))

    def test_a_seek_starts_where_the_player_asked(self):
        import app
        self.assertEqual(app.parse_range("bytes=123456-", 10_000_000, window=1_000)[:2], (123456, 124455))

    def test_a_closed_range_is_clamped_to_the_file(self):
        import app
        self.assertEqual(app.parse_range("bytes=0-999999999", 500, window=1_000)[:2], (0, 499))

    def test_an_offset_past_the_end_is_a_416(self):
        import app
        self.assertIsNone(app.parse_range("bytes=600-", 500))
        self.assertIsNone(app.parse_range("bytes=500-", 500))


if __name__ == "__main__":
    unittest.main()
