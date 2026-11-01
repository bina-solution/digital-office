#!/usr/bin/env python3
"""paginated-list-lint — gate G36: a provider list call is paginated or explicitly bounded.

    python3 scripts/refactor/paginated-list-lint.py [--self-test]

WHY THIS GATE EXISTS (a real outage, 2026-08-05):

`apps/drive/adapters/google.py::_list()` issued ONE Google Drive `files.list` request and returned
`d.get("files", [])` without ever following `nextPageToken`. Drive caps a page at ~460-1000 items
regardless of the `pageSize` asked for, so every folder larger than one page silently reported only
its first page. No error, no warning, no log line — the rest of the folder simply looked absent.

On the client's real archive that hid **43,326 of 78,651 documents** (the count went 35,325 ->
78,651 the moment pagination was added). Folders that actually held 17,066 / 2,001 / 1,967 files all
reported exactly 460. A sync built on that lister would have declared itself complete having moved
the first 460 files of each folder.

The tell was that `folders()` — ten lines above `_list()` in the same class — already looped on
`nextPageToken` correctly. This was an inconsistency, not a decision, and nothing caught it.

THE RULE: if a call asks a remote provider to list things, it must either
  (a) follow the provider's continuation token (`nextPageToken` / `pageToken` / `cursor`), or
  (b) pass an explicit, deliberate bound (a `limit`/`pageSize` argument that a human chose).

A bounded call is fine — a UI browse view or a "latest 200" probe SHOULD be bounded. What is not
fine is an unbounded-looking call that quietly truncates, because the caller then treats a partial
answer as the whole truth.

WHAT IS FLAGGED: a request whose params include a page-size key, in a function that never mentions a
continuation token and takes no limit. Scoped to the provider adapters, which is where this class of
bug actually bites; nothing else in the tree talks pagination.
"""
import argparse
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]

#: Where remote-provider listing actually happens. Keeping the scope tight keeps the gate honest —
#: a broad scan over the whole tree would drown in false positives from unrelated `limit=` kwargs.
SCOPED = (
    "apps/drive/adapters/",
    "apps/mail/mailapi/",
)

EXEMPT = {
    "scripts/refactor/paginated-list-lint.py",   # this file
}

#: the provider asked for a page of results
PAGE_SIZE = re.compile(r"""["']?(?:pageSize|maxResults|per_page|page_size)["']?\s*[:=]""")
#: a page size of a few items is a PROBE ("is this account alive?"), not a listing — nobody mistakes
#: one row for the whole dataset, so pagination is meaningless there.
PROBE_SIZE = re.compile(r"""["']?(?:pageSize|maxResults|per_page|page_size)["']?\s*[:=]\s*[1-5]\b""")
#: the code knows about continuation
CONTINUATION = re.compile(r"""nextPageToken|pageToken|next_cursor|before_uid|continuation|page_token""")
#: the call is deliberately capped by an argument the caller chose
BOUNDED = re.compile(r"""\blimit\b|\btake\b|\bmax_results\b|\bcap\b""")


def _functions(text):
    """Yield (start_line, name, body) for each def in a python source, cheaply.

    Indentation-based rather than AST-based so the self-test can feed fragments that are not
    importable modules.
    """
    lines = text.splitlines()
    starts = [i for i, l in enumerate(lines) if re.match(r"\s*def\s+\w+", l)]
    for n, i in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        name = re.match(r"\s*def\s+(\w+)", lines[i]).group(1)
        yield i + 1, name, "\n".join(lines[i:end])


def scan_text(rel, text):
    if not rel.endswith(".py"):
        return []
    if rel in EXEMPT or not any(rel.startswith(s) for s in SCOPED):
        return []
    out = []
    for line_no, name, body in _functions(text):
        if not PAGE_SIZE.search(body):
            continue
        if PROBE_SIZE.search(body) or CONTINUATION.search(body) or BOUNDED.search(body):
            continue
        out.append((rel, line_no, name))
    return out


def scan(overrides=None):
    overrides = overrides or {}
    findings = []
    seen = set()
    for scope in SCOPED:
        base = REPO / scope
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            rel = p.relative_to(REPO).as_posix()
            seen.add(rel)
            text = overrides.get(rel)
            if text is None:
                try:
                    text = p.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
            findings += scan_text(rel, text)
    for rel, text in overrides.items():
        if rel not in seen:
            findings += scan_text(rel, text)
    return findings


SELF_TEST = [
    # THE ACTUAL BUG — one request, a page size, no token, no limit.
    ("the real 2026-08-05 defect", "apps/drive/adapters/google.py",
     'def _list(self, qs):\n'
     '    d = self._json("GET", f"{API}/files", params={\n'
     '        "q": qs, "fields": f"files({FIELDS})", "pageSize": 500})\n'
     '    return [_item(f) for f in d.get("files", [])]\n', True),
    ("page size, no continuation, mail side", "apps/mail/mailapi/app.py",
     'def search(self, b):\n'
     '    r = self._req("GET", url, params={"maxResults": 200})\n'
     '    return r.json()["messages"]\n', True),

    # the fix — follows the token
    ("paginates properly", "apps/drive/adapters/google.py",
     'def _list(self, qs, limit=None):\n'
     '    out, page = [], None\n'
     '    while True:\n'
     '        d = self._json("GET", f"{API}/files", params={\n'
     '            "q": qs, "pageSize": 1000,\n'
     '            **({"pageToken": page} if page else {})})\n'
     '        out += d.get("files", [])\n'
     '        page = d.get("nextPageToken")\n'
     '        if not page:\n'
     '            return out\n', False),
    # deliberately capped — a browse view, which is legitimate
    ("explicitly bounded by the caller", "apps/drive/adapters/google.py",
     'def trashed(self, limit=1000):\n'
     '    d = self._json("GET", f"{API}/files", params={"pageSize": limit})\n'
     '    return d.get("files", [])\n', False),
    # cursor-style pagination (the mail service uses before_uid, not a token)
    ("cursor pagination", "apps/mail/mailapi/app.py",
     'def search(self, b):\n'
     '    before = int(b.get("before_uid") or 0)\n'
     '    r = self._req("GET", url, params={"maxResults": 200})\n'
     '    return r.json()\n', False),
    # a readiness probe — one row, deliberately. Not a listing.
    ("health probe, pageSize 1", "apps/drive/adapters/google.py",
     'def probe(self):\n'
     '    r = self._req("GET", f"{API}/files", params={"pageSize": 1, "fields": "files(id)"})\n'
     '    return None if r.status_code < 400 else _reason(r)\n', False),
    # no listing at all
    ("not a list call", "apps/drive/adapters/google.py",
     'def delete(self, fid):\n'
     '    return self._json("DELETE", f"{API}/files/{fid}")\n', False),
    # out of scope — same shape, but not a provider adapter
    ("out of scope path", "scripts/whatever.py",
     'def go():\n    r = get(url, params={"pageSize": 100})\n    return r.json()\n', False),
]


def self_test():
    bad = 0
    for label, rel, text, should in SELF_TEST:
        got = bool(scan_text(rel, text))
        if got != should:
            bad += 1
        print(f"  [{'ok ' if got == should else 'FAIL'}] "
              f"{'caught' if got else 'allowed':<8} "
              f"({'must catch' if should else 'must allow'}): {label}")
    print(f"\nG36 self-test: {len(SELF_TEST) - bad}/{len(SELF_TEST)} passed")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    findings = scan()
    if findings:
        print(f"G36 FAIL — {len(findings)} provider list call(s) that truncate silently:")
        for rel, line_no, name in findings:
            print(f"    {rel}:{line_no}  in {name}()")
        print("\n  A list call must either follow the provider's continuation token")
        print("  (nextPageToken / pageToken / cursor) or take an explicit limit the caller chose.")
        print("  An unbounded call that returns one page reports the rest of the data as ABSENT —")
        print("  on 2026-08-05 that hid 43,326 of 78,651 documents with no error.")
        return 1
    print("G36 PASS — every provider list call paginates or is explicitly bounded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
