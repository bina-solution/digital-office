"""/api/link says each pair's last SEARCH for its moved address — so «the office moved» and «the office is off»
no longer read the same (issues/hp-link-dead-for-25-hours-and-the-office-hub-died-with-it.yaml, DGO-1848).

Run inside the app's image (it imports the app): `python3 tests/test_link_search.py` from `apps/dgo-extend`, or
`docker run --rm --network none -v "$PWD:/src:ro" -w /src --entrypoint python3 <the dgo-extend image>
tests/test_link_search.py`. Exit code 0 = every check held.
"""
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
STATE = tempfile.mkdtemp(prefix="search-state-")
TUNNEL = tempfile.mkdtemp(prefix="search-tunnel-")
os.environ["DGO_STATE_DIR"] = STATE
os.environ["DGO_TUNNEL_DIR"] = TUNNEL

import app  # noqa: E402

app.STATE_DIR = Path(STATE)
FAIL = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        FAIL.append(what)


def write_result(want, tried, found=""):
    lines = [f"want {want}", f"tried {tried}"] + ([f"found {found}"] if found else [])
    (Path(TUNNEL) / "scan.result").write_text("\n".join(lines) + "\n", encoding="utf-8")


# no search ever ran: nothing is said
check(app._search_said(None) is None and app._search_said({}) is None, "no search ran: the field is None")

# a count that is not a number, or zero, is not a search
check(app._search_said({"count": "0"}) is None and app._search_said({"count": "x"}) is None,
      "a count of 0 or not a number: no search is said")

# a search that FOUND the office says where, and where it was
said = app._search_said({"count": 1, "adopted": "10.0.0.6", "was": "10.0.0.5", "tried": 3, "endpoint": "10.0.0.5"})
check(said["running"] is False and said["found"] == "10.0.0.6" and said["was"] == "10.0.0.5"
      and said["timed_out"] is False, "a search that found the office says the new address and the old one")

# a search under way
running = {"want": "hp-laptop-1", "at": 100.0, "endpoint": "192.168.16.102", "count": 1, "candidates": 64}
said = app._search_said(running)
check(said["running"] is True and said["around"] == "192.168.16.102" and said["found"] is None,
      "a search under way is said as running, around the address it looks at, nothing found yet")

# an earlier search FOUND the office; the next one finds nothing — it must not still read as found
app._write_find_state({"hp-laptop": {"count": 2, "at": time.time(), "endpoint": "192.168.16.102", "tried": 3,
                                     "adopted": "192.168.16.100", "was": "192.168.16.102",
                                     "want": "hp-laptop-2"}})
write_result("hp-laptop-2", 64)
answer = app.collect_found_peer("hp-laptop", app._find_state()["hp-laptop"])
said = app._search_said(app._find_state().get("hp-laptop"))
check(answer and answer["ok"] is False and answer["tried"] == 64, "a search that finds nothing answers not-found")
check(said["running"] is False and said["tried"] == 64 and said["found"] is None and said["was"] is None,
      "…and /api/link says it tried 64 and found nothing — not the address an EARLIER search found")

# a search that runs out of time is said AS that — not as «no answer from N» (which reads «the office is off»),
# and keeps no count or address from an earlier search
app._write_find_state({"vps1": {"count": 2, "at": time.time() - 10_000, "endpoint": "10.0.0.5", "tried": 64,
                                "adopted": "10.0.0.6", "was": "10.0.0.5", "want": "vps1-9"}})
write_result("someone-else", 1)
answer = app.collect_found_peer("vps1", app._find_state()["vps1"])
said = app._search_said(app._find_state().get("vps1"))
check(answer and answer["ok"] is False and said["running"] is False and said["timed_out"] is True
      and said["found"] is None and said["tried"] is None,
      "a search that ran out of time says timed_out, with no earlier search's count or found address")

# the NEXT answer clears timed_out
app._write_find_state({"vps1": {**app._find_state()["vps1"], "want": "vps1-10", "at": time.time()}})
write_result("vps1-10", 5)
app.collect_found_peer("vps1", app._find_state()["vps1"])
said = app._search_said(app._find_state().get("vps1"))
check(said["timed_out"] is False and said["tried"] == 5, "an answer after a time-out is said as that answer alone")

# a NEW search starts clean: while it runs, no earlier result rides along
src_find = (HERE / "app.py").read_text(encoding="utf-8")
check("entry = {k: v for k, v in (state.get(oid) or {}).items() if k not in SEARCH_RESULT}" in src_find,
      "a new search starts from the entry without the last search's result")

# the field is in /api/link's items (the reader is wired, not only written)
src = (HERE / "app.py").read_text(encoding="utf-8")
check('"search": _search_said(searches.get(oid))' in src and "searches = _find_state()" in src,
      "/api/link's items carry `search`, read once per answer")

shutil.rmtree(STATE, ignore_errors=True)
shutil.rmtree(TUNNEL, ignore_errors=True)
print("test_link_search: all passed" if not FAIL else f"test_link_search: {len(FAIL)} failure(s)")
sys.exit(1 if FAIL else 0)
