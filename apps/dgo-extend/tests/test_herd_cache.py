#!/usr/bin/env python3
"""give.load_herd's cache never answers an older herd file than the one on disk — «racily clean» (git's word).

The cache was keyed on (path, mtime_ns, size). A herd file written again within the kernel's file-clock granularity,
at the same size, kept both: test_clients changed one 19-character join PIN for another within one tick, and the
client joiner kept the old PIN (vps1, G72 at 8307508c5, once in many runs). The clock is the kernel's, so this test
makes the tick itself: the same size, and the mtime set back to the old one with os.utime.

    python3 apps/dgo-extend/tests/test_herd_cache.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import give  # noqa: E402

FAIL: list = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        FAIL.append(what)


HERD = "offices:\n  macbook:\n    key: KEY-MAC\n  exampleu:\n    key: KEY-EXU\n    pin: {pin}\n"


def main() -> int:
    d = Path(tempfile.mkdtemp(prefix="herd-cache-"))
    f = d / "herd.yaml"
    try:
        f.write_text(HERD.format(pin="0A0A-0000-0000-0001"), encoding="utf-8")
        old = os.stat(f).st_mtime_ns
        check(give.load_herd(f)["offices"]["exampleu"]["pin"] == "0A0A-0000-0000-0001", "the first read")

        # THE TICK: rewritten in place at the same size, and within one tick of the kernel's file clock — so its stat is
        # the SAME as before in every field the key holds (inode, mtime, ctime, size). The clock is the kernel's, so the
        # stat the loader sees is pinned to the first one; only the file's text changes.
        first = os.stat(f)
        f.write_text(HERD.format(pin="AAAA-BBBB-CCCC-DDDD"), encoding="utf-8")
        check(os.stat(f).st_size == first.st_size, "…the second write has the same size")
        real_stat, real_time = give.Path.stat, give.time.time
        give.Path.stat = lambda self, *a, **k: first if str(self) == str(f) else real_stat(self, *a, **k)
        try:
            give.time.time = lambda: first.st_mtime + 0.1          # still young
            got = give.load_herd(f)["offices"]["exampleu"]["pin"]
            # …and git's own case (the second reader): that read was made while the file was young; it is rewritten
            # again in the same tick, and the next call comes only after the file has settled — no call between
            f.write_text(HERD.format(pin="CCCC-DDDD-EEEE-FFFF"), encoding="utf-8")
            give.time.time = lambda: first.st_mtime + 5.0          # settled
            settled = give.load_herd(f)["offices"]["exampleu"]["pin"]
        finally:
            give.Path.stat, give.time.time = real_stat, real_time
        check(got == "AAAA-BBBB-CCCC-DDDD",
              "a file changed within one tick (the same inode, mtime, ctime and size) is read again, not answered from the cache")
        check(settled == "CCCC-DDDD-EEEE-FFFF",
              "what was read while the file was young is not trusted once it settles (git's racily-clean rule)")
        _ = old

        # an atomic replace (git's own way): a new inode, the same size and mtime
        tmp = d / "herd.yaml.new"
        tmp.write_text(HERD.format(pin="EEEE-FFFF-0000-1111"), encoding="utf-8")
        os.utime(tmp, ns=(old, old))
        os.replace(tmp, f)
        check(give.load_herd(f)["offices"]["exampleu"]["pin"] == "EEEE-FFFF-0000-1111", "…and so is one replaced atomically")

        # the cache still works for a file that has settled: parsed once, then answered from the key (the clock is
        # moved on, since «young» is judged by the later of mtime and ctime and ctime cannot be set back)
        calls = [0]
        real, real_now = give.yaml.safe_load, give.time.time
        give.yaml.safe_load = lambda text: (calls.__setitem__(0, calls[0] + 1), real(text))[1]
        give.time.time = lambda: real_now() + 10
        try:
            give.load_herd(f); give.load_herd(f); give.load_herd(f)
        finally:
            give.yaml.safe_load, give.time.time = real, real_now
        check(calls[0] == 1, f"a settled file is parsed once and then cached ({calls[0]} parse(s) for three reads)")

        # a write that keeps the old mtime (`cp -p`, `touch -r`) is young by its ctime: not trusted to the key
        f.write_text(HERD.format(pin="1111-2222-3333-4444"), encoding="utf-8")
        past = time.time_ns() - 10 * 1_000_000_000
        os.utime(f, ns=(past, past))
        check(give.load_herd(f)["offices"]["exampleu"]["pin"] == "1111-2222-3333-4444"
              and give.load_herd.__globals__["_cache"]["entry"][0] is None,
              "a write that keeps an old mtime is young by its ctime: read, and stored without its key")

        # an mtime in the FUTURE (a copied file, a clock stepped back) is not «young»: cached, not parsed per call
        ahead = time.time_ns() + 3600 * 1_000_000_000
        os.utime(f, ns=(ahead, ahead))
        calls[0] = 0
        give.yaml.safe_load = lambda text: (calls.__setitem__(0, calls[0] + 1), real(text))[1]
        try:
            give.load_herd(f); give.load_herd(f); give.load_herd(f)
        finally:
            give.yaml.safe_load = real
        check(calls[0] == 1, f"a file stamped an hour ahead is parsed once, not on every call ({calls[0]} parse(s))")
    finally:
        for p in d.iterdir():
            p.unlink()
        d.rmdir()
    print(f"\n{'FAILED: ' + str(len(FAIL)) if FAIL else 'all passed'}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
