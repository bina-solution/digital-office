"""api-log-reads.py — the API request log keeps what a WRITE answered, not what a read did.

    RUN python3 /app/patches/api-log-reads.py    (Dockerfile, build time)

WHY. Plane writes one row per request made with an API key (`plane/middleware/logger.py`), and the
row holds the FULL response. For a write that is a few KB and worth having: it is what the request
changed. For a read it is a second copy of data Plane already holds — and a list of a project's work
items is 80 KB of it. Measured on hp-laptop, 2026-10-07, after the scheduler came back and the
daily prune had run:

    GET    17,471 rows · 81,450 characters stored per answer on average
    POST      676 rows ·  4,473
    PATCH     369 rows ·  1,646

15,219 rows were written on one working day — the office's own task CLI and the hook that asks the
hub what is left — so the table grew by about 300 MB a day and would settle near 1 GB even with
three days of retention. Nothing in Plane reads the column back: `APIActivityLogSerializer` is
defined and no view uses it.

So a GET's answer is not stored. The row still says who asked (the token's keyed digest), for what
(path, query), from where, and what came back (the status code). A read's row is under 1 KB.

Asserts its anchor, like every patch here: upstream changing how the row is built must fail the
build rather than quietly ship an image whose log grows by a project a request again.
"""
import pathlib
import sys

FILE = pathlib.Path("/app/backend/plane/middleware/logger.py")
OLD = '"response_body": self._safe_decode_body(response.content) if response.content else None,'
NEW = ('"response_body": self._safe_decode_body(response.content) '
       'if response.content and request.method != "GET" else None,')


def main() -> int:
    if not FILE.exists():
        print(f"api-log-reads: {FILE} is missing — the image layout changed, refusing to guess")
        return 1
    src = FILE.read_text(encoding="utf-8")
    if NEW in src:
        print("api-log-reads: already applied")
        return 0
    if src.count(OLD) != 1:
        print(f"api-log-reads: expected exactly one line that stores the response, found {src.count(OLD)} — refusing")
        return 1
    FILE.write_text(src.replace(OLD, NEW), encoding="utf-8")
    print("api-log-reads: a read's answer is no longer stored in the API request log (writes keep theirs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
