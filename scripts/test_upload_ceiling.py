#!/usr/bin/env python3
"""The largest file «קבצים» takes is ONE value, the same in the template and in both readers' defaults (DGO-1785).

Why it exists: drive (DRIVE_MAX_UPLOAD) and supabase storage (FILE_SIZE_LIMIT) both read SUPABASE_FILE_SIZE_LIMIT.
ab7025454 gave drive a 2 GiB default, but .env.ex pinned 50 MB and storage's own default stayed 50 MB, so every
office ran at 50 MB: exu101's 388 MB video never reached Exampleu's «קבצים», and the owner's 97 MB Telegram video
(#825, DGO-1805) was refused with 413. These cases read the real tree.

    python3 scripts/test_upload_ceiling.py
"""
import pathlib
import re
import sys
import unittest

# Its messages carry Hebrew: on a host whose stdout is not UTF-8 (Windows) the first one would raise instead (G10).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[1]
KEY = "SUPABASE_FILE_SIZE_LIMIT"
EXU101 = 388 * 1000 ** 2        # Exampleu's first meeting, 2:13 h of video (DGO-1785)
TG825 = 97_153_903              # the owner's Telegram video, #825 (DGO-1805)


def default_in(compose, inner):
    """The default `inner: ${KEY:-<n>}` (or `- inner=${KEY:-<n>}`) gives in one compose file."""
    text = (REPO / compose).read_text(encoding="utf-8")
    got = re.findall(rf"^\s*-?\s*{inner}\s*[:=]\s*\$\{{{KEY}:-(\d+)\}}", text, re.M)
    if len(got) != 1:
        raise AssertionError(f"{compose}: {inner} reads ${{{KEY}:-…}} {len(got)} times, not once")
    return int(got[0])


def template():
    got = re.findall(rf"^{KEY}=(\d+)\s*$", (REPO / ".env.ex").read_text(encoding="utf-8"), re.M)
    if len(got) != 1:
        raise AssertionError(f".env.ex: {KEY} is set {len(got)} times, not once")
    return int(got[0])


class Ceiling(unittest.TestCase):
    def test_drive_and_its_store_default_to_the_same_ceiling(self):
        self.assertEqual(default_in("apps/drive/docker-compose.yml", "DRIVE_MAX_UPLOAD"),
                         default_in("apps/supabase/docker-compose.yml", "FILE_SIZE_LIMIT"))

    def test_storage_reads_no_other_ceiling(self):
        # storage-api reads UPLOAD_FILE_SIZE_LIMIT before FILE_SIZE_LIMIT, and a standard upload's own limit
        # (measured in v1.48.26's dist/config.js): any of them in its compose splits the two again
        text = (REPO / "apps/supabase/docker-compose.yml").read_text(encoding="utf-8")
        for other in ("UPLOAD_FILE_SIZE_LIMIT", "FILE_SIZE_LIMIT_STANDARD_UPLOAD"):
            self.assertNotIn(other, text)

    def test_the_template_gives_every_new_office_that_ceiling(self):
        self.assertEqual(template(), default_in("apps/drive/docker-compose.yml", "DRIVE_MAX_UPLOAD"))

    def test_a_meetings_video_and_the_owners_telegram_video_fit(self):
        for size in (EXU101, TG825):
            self.assertLess(size, template())


if __name__ == "__main__":
    unittest.main(verbosity=2)
