"""The link's own repair loop (`app.heal_links`) — the bookkeeping, with no tunnel and no peer.

Run inside the app's image (it imports the app): `python3 tests/heal_links_selftest.py` from
`apps/dgo-extend`, or `docker run --rm --network none -v "$PWD:/src:ro" -w /src --entrypoint python3
<the dgo-extend image> tests/heal_links_selftest.py`. Exit code 0 = every check held.

Written from the MacBook office, 2026-10-19: hp-laptop's pair had been down for ten days and the
loop had neither searched for it nor moved a port — because every pass recorded its `down_since`
and then threw it away when the next pair's (vps1's) refused rotation reloaded the whole file.
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
STATE = tempfile.mkdtemp(prefix="heal-state-")
TUNNEL = tempfile.mkdtemp(prefix="heal-tunnel-")
os.environ["DGO_STATE_DIR"] = STATE
os.environ["DGO_TUNNEL_DIR"] = TUNNEL

import app  # noqa: E402

# The REAL measurement, kept before this file stubs it out (`app._tunnel_measured = lambda: alive`):
# the window `alive` is computed with is a fact only the real function can be asked about.
REAL_TUNNEL_MEASURED = app._tunnel_measured

app.STATE_DIR = Path(STATE)
NOW = time.time()
HP = {"office": "hp-laptop", "dial": "home", "slot": 4, "endpoint": "192.168.16.100",
      "endpoint_port": 51830, "record": {"id": "hp-laptop", "kind": "paired",
                                         "identity": {"wg": "x" * 43 + "="}}}
VPS = {"office": "vps1", "dial": "home", "slot": 2, "endpoint": "staging.digital-office.co.il",
       "endpoint_port": 51820, "record": {"id": "vps1"}}
DOWN = {"hp-laptop": {"ok": False}, "vps1": {"ok": False}}
calls = {"find": [], "rotate": []}
alive: dict = {}

app.cv.home_office = lambda: {"id": "macbook", "tunnel": {"slot": 2}}
app.all_declarations = lambda: [HP["record"], VPS["record"]]
app._link_pairs = lambda home, records: [HP, VPS]
app._tunnel_measured = lambda: alive


def fake_find(oid, why=""):
    calls["find"].append(oid)
    state = app._find_state()
    entry = dict(state.get(oid) or {})
    state[oid] = {**entry, "at": time.time(), "count": int(entry.get("count") or 0) + 1}
    app._write_find_state(state)
    return {"office": oid, "ok": True}


def fake_render():
    return {"rendered": []}


app.find_peer = fake_find
app.render_tunnel = fake_render
# …and WHERE this office sits. `net.dialable_from_here` is this office's OWN reachability (an office
# at a public address may not dial a home /24 it is not on — lnk-032), a fact about the office and not
# about the repair. Pinned True because this file tests the repair loop's BOOKKEEPING and has to give
# the same answer on every office: on vps1 the real predicate refuses every LAN pair, and the two
# search cases below failed there for that reason alone (measured 2026-11-01, on the code before
# DGO-1096 as well — the failures are the host's, not the repair's).
import net as netmod  # noqa: E402
netmod.dialable_from_here = lambda *a, **k: True
problems = []

# vps1 has spent its rotations (HEAL_MAX): every pass asks once more and is refused, writing nothing.
app._write_listen_ports({"vps1": {"port": 52532, "count": app.HEAL_MAX, "at": NOW - 99999,
                                  "down_since": NOW - 99999}})
app.heal_links(DOWN)
if not (app._listen_ports().get("hp-laptop") or {}).get("down_since"):
    problems.append("a pair's first sighting down is RECORDED, whatever the pair after it is refused")

# The clock runs: past FIND_AFTER the pair is looked for (its endpoint is a LAN address)…
doc = app._listen_ports()
doc["hp-laptop"]["down_since"] = NOW - max(app.HEAL_AFTER, app.FIND_AFTER) - 5
app._write_listen_ports(doc)
app.heal_links(DOWN)
if calls["find"] != ["hp-laptop"]:
    problems.append(f"a LAN pair down past FIND_AFTER is searched for (and a named one never), got {calls['find']}")

# …and after FIND_MAX searches it is still looked for, at the slower pace, until it answers.
state = app._find_state()
state["hp-laptop"] = {"count": app.FIND_MAX + 5, "at": NOW - app.FIND_COOLDOWN_AWAY - 5}
app._write_find_state(state)
calls["find"].clear()
app.heal_links(DOWN)
if calls["find"] != ["hp-laptop"]:
    problems.append(f"a peer that stays away is still searched for, got {calls['find']}")

# A tunnel that handshakes is not repaired by moving its address or its port.
alive.update({"wg4": {"alive": True}})
state = app._find_state()
state["hp-laptop"] = {"count": 1, "at": NOW - 99999}
app._write_find_state(state)
calls["find"].clear()
before = (app._listen_ports().get("hp-laptop") or {}).get("port")
doc = app._listen_ports()
doc["hp-laptop"]["at"] = NOW - app.HEAL_COOLDOWN - 5           # a rotation would be due by the clock
app._write_listen_ports(doc)
app.heal_links(DOWN)
if calls["find"] or (app._listen_ports().get("hp-laptop") or {}).get("port") != before:
    problems.append("a pair whose tunnel is alive is neither searched for nor re-ported")

# A pair on the TCP path (2026-10-19) is its carrier's to heal: its interface sends to 127.0.0.1, so
# no port and no address of it is repaired here, however long it is down.
TCP = {"office": "carried", "dial": "home", "slot": 6, "endpoint": "192.168.16.103",
       "endpoint_port": 51830, "transport": "tcp", "record": {"id": "carried", "kind": "paired"}}
app._link_pairs = lambda home, records: [TCP]
alive.clear()
doc = app._listen_ports()
doc["carried"] = {"down_since": NOW - 99999}
app._write_listen_ports(doc)
calls["find"].clear()
app.heal_links({"carried": {"ok": False}})
if calls["find"] or (app._listen_ports().get("carried") or {}).get("port"):
    problems.append("a tcp pair is never searched for or re-ported: its carrier redials on its own")

# The MacBook at a coffee shop (2026-11-01): every PUBLIC pair it dials died at one moment, because its own
# network moved. Both get a fresh source port on THIS pass, with no first sighting to wait out, and a status
# still «ok» from a pass that ran before the tunnels died does not hold one back.
FP = {"office": "fireplace", "dial": "home", "slot": 6, "endpoint": "93.184.216.10",
      "endpoint_port": 51820, "record": {"id": "fireplace"}}
app._link_pairs = lambda home, records: [VPS, FP]
app.all_declarations = lambda: [VPS["record"], FP["record"]]
app._write_listen_ports({})
gone = int(NOW) - 230
alive.clear()
alive.update({"wg2": {"alive": False, "handshake_at": gone}, "wg6": {"alive": False, "handshake_at": gone + 40}})
app.heal_links({"vps1": {"ok": False}, "fireplace": {"ok": True}})
moved = {o: (app._listen_ports().get(o) or {}).get("port") for o in ("vps1", "fireplace")}
if not all(moved.values()):
    problems.append(f"a laptop that changed networks re-ports every public pair on one pass, got {moved}")
if not all((app._listen_ports().get(o) or {}).get("down_since") for o in ("vps1", "fireplace")):
    problems.append("a pair re-ported on its first sighting keeps `down_since`, so its budget resets when it is back")
alive.update({"wg2": {"alive": True, "handshake_at": int(NOW)}, "wg6": {"alive": True, "handshake_at": int(NOW)}})
app.heal_links({"vps1": {"ok": True}, "fireplace": {"ok": True}})
if any((app._listen_ports().get(o) or {}).get("count") for o in ("vps1", "fireplace")):
    problems.append("a roamed pair that is back starts a fresh budget (count 0): the seventh move must not be refused")

# …while one public pair that died ALONE waits for HEAL_AFTER as before: it may be the peer that is down.
app._write_listen_ports({})
alive.update({"wg6": {"alive": True, "handshake_at": int(NOW)}})
app.heal_links({"vps1": {"ok": False}, "fireplace": {"ok": True}})
if (app._listen_ports().get("vps1") or {}).get("port"):
    problems.append("a single public pair down on its first sighting is not re-ported yet")

# ── DGO-1096, the SECOND half: a STUCK handshake on ONE interface ────────────────────────────────
# Not the whole office: one pair. Its handshake age grows past HEAL_AFTER while this side keeps SENDING
# (`tx`) and the far side receives nothing (`rx == 0`) — a home NAT/router holding the OLD network's
# mapping for our source port, kept open by the 25 s keepalives. The port moves FIRST, and the address
# search — equally due by its own clock below — does NOT run in that pass: a search repairs the peer's
# ADDRESS, and nothing measured here says the peer's address moved.
STUCK_AGE = app.HEAL_AFTER + 40
if app._stuck_handshake({"alive": True, "handshake_age_s": 20, "tx": 10, "rx": 0}) is not None:
    problems.append("a handshake renewed 20 s ago is not stuck, whatever it is sending")
if app._stuck_handshake({"alive": False, "handshake_age_s": STUCK_AGE, "tx": 10, "rx": 7}) is not None:
    problems.append("a stale handshake that DID receive is not stuck: the far side heard us")
if app._stuck_handshake({"handshake_age_s": STUCK_AGE, "tx": 10, "rx": 0}) != STUCK_AGE:
    problems.append("a stale handshake, sending and receiving nothing, is stuck for that many seconds")

app._link_pairs = lambda home, records: [HP]
app.all_declarations = lambda: [HP["record"], VPS["record"]]
app._write_listen_ports({})
app._write_find_state({})
alive.clear()
alive.update({"wg4": {"alive": True, "handshake_age_s": STUCK_AGE, "tx": 991, "rx": 0,
                      "handshake_at": int(NOW) - int(STUCK_AGE)}})
# The pair is ALREADY past both clocks the older repairs answer to — the search's and the rotation's —
# so nothing but the stuck decision can decide this pass.
doc = app._listen_ports()
doc["hp-laptop"] = {"down_since": NOW - max(app.HEAL_AFTER, app.FIND_AFTER) - 60, "count": 0, "at": 0}
app._write_listen_ports(doc)
calls["find"].clear()
before = (app._listen_ports().get("hp-laptop") or {}).get("port")
app.heal_links({"hp-laptop": {"ok": False}})
moved = (app._listen_ports().get("hp-laptop") or {}).get("port")
was = (app._listen_ports().get("hp-laptop") or {}).get("was")
if not moved or moved == before:
    problems.append("a stuck handshake moves the port (age past HEAL_AFTER, sending, receiving nothing)")
if calls["find"]:
    problems.append(f"a stuck handshake moves the port BEFORE any other repair — no search that pass, got {calls['find']}")
if not was:
    problems.append("the rotation keeps the port it moved FROM, so the move can be read as a sentence")
if (app._listen_ports().get("hp-laptop") or {}).get("count") != 1:
    problems.append("a stuck handshake is ONE rotation, not a new budget every pass")
# …once per episode: the next pass is inside the shared cooldown and touches nothing.
app.heal_links({"hp-laptop": {"ok": False}})
if (app._listen_ports().get("hp-laptop") or {}).get("port") != moved:
    problems.append("a second rotation in the same stuck episode is refused by the shared cooldown")
# …and a handshake that ARRIVES again is not a stuck one, whatever the catalog says.
alive.update({"wg4": {"alive": True, "handshake_age_s": 20, "tx": 4000, "rx": 900,
                      "handshake_at": int(NOW) - 20}})
doc = app._listen_ports()
doc["hp-laptop"]["at"] = NOW - app.HEAL_COOLDOWN - 5            # a rotation would be due by the clock
app._write_listen_ports(doc)
app.heal_links({"hp-laptop": {"ok": False}})
if (app._listen_ports().get("hp-laptop") or {}).get("port") != moved:
    problems.append("a fresh handshake is never re-ported, however long the office behind it is down")
# …while a pair that is merely SWITCHED OFF keeps the search's turn: `rx > 0` is a mapping that
# worked, so the port is not the suspect.
alive.update({"wg4": {"alive": False, "handshake_age_s": STUCK_AGE, "tx": 5000, "rx": 8123,
                      "handshake_at": int(NOW) - int(STUCK_AGE)}})
app._write_find_state({})
doc = app._listen_ports()
doc["hp-laptop"] = {"down_since": NOW - max(app.HEAL_AFTER, app.FIND_AFTER) - 60, "at": 0}
app._write_listen_ports(doc)
calls["find"].clear()
app.heal_links({"hp-laptop": {"ok": False}})
if calls["find"] != ["hp-laptop"]:
    problems.append(f"a stale handshake that DID receive is not a stuck one: the search keeps its turn, got {calls['find']}")

# The history says it in words, in a row of its own: the pair's (ok, hop) need not change in the pass
# that ran the repair, and the moved source port is invisible from both ends of the tunnel.
app._record_link_history([{"office": "hp-laptop", "verdict": {"ok": False, "hop": "tunnel", "why": "x"},
                           "tunnel": {"handshake_age_s": int(app.HEAL_AFTER) + 40}}],
                         [{"office": "hp-laptop", "ok": True, "port": moved, "was": was, "count": 1,
                           "why": "לחיצת היד נתקעה 220 שניות"}])
rows = [r for r in app.load_link_history(50) if r.get("kind") == "repair"]
if not rows or "הוזז פורט מקור" not in str(rows[-1].get("fixed_by") or ""):
    problems.append("the rotation is recorded in the link history as «הוזז פורט מקור <port>»")
if rows and (rows[-1].get("port") != moved or rows[-1].get("from_port") != was):
    problems.append("the repair row carries BOTH ends of the move (`from_port` and `port`)")

# ── THE VERIFICATION'S THREE FINDS ON DGO-1096 (2026-11-01) ──────────────────────────────────────
# FIND 1 — A PAIR THAT ANSWERS IS NEVER RE-PORTED ON A FRESH COUNTER. `rx`/`tx` are CUMULATIVE for the
# life of the interface and restart at zero when the tunnel container is rebuilt, so a HEALTHY pair
# with `rx = 0` and a handshake older than `HEAL_AFTER` reads exactly like a stuck one by the
# INTERFACE's numbers alone. The catalog is the second witness and it is the one that wins: the pair
# answers, so the tunnel works, and moving the port would buy a needless disconnect and re-handshake.
app._link_pairs = lambda home, records: [HP]
app.all_declarations = lambda: [HP["record"], VPS["record"]]
app._write_listen_ports({})
app._write_find_state({})
alive.clear()
alive.update({"wg4": {"alive": True, "handshake_age_s": STUCK_AGE, "tx": 991, "rx": 0,
                      "handshake_at": int(NOW) - int(STUCK_AGE)}})
calls["find"].clear()
app.heal_links({"hp-laptop": {"ok": True}})                  # the catalog ANSWERS
if (app._listen_ports().get("hp-laptop") or {}).get("port"):
    problems.append("FIND 1: a pair whose catalog ANSWERS is never re-ported, however one-sided and "
                    "stale its interface counters look (rx/tx restart at zero with the tunnel container)")
if calls["find"]:
    problems.append(f"FIND 1: a pair that answers is not searched for either, got {calls['find']}")
# …and the same holds when the handshake is old enough that the interface is not `alive` at all: the
# gate is the VERDICT, not the shape of the counters.
alive.update({"wg4": {"alive": False, "handshake_age_s": STUCK_AGE + 120, "tx": 991, "rx": 0,
                      "handshake_at": int(NOW) - int(STUCK_AGE) - 120}})
app.heal_links({"hp-laptop": {"ok": True}})
if (app._listen_ports().get("hp-laptop") or {}).get("port"):
    problems.append("FIND 1: a pair that answers is not re-ported even when its interface is not `alive`")

# FIND 2 — THE CASE THE BRANCH WAS BUILT FOR: the pair does NOT answer, it keeps SENDING and receives
# nothing, its counters are FRESH (just established), and its handshake age is past `HEAL_AFTER`. The
# source port moves, on this very first sighting.
app._write_listen_ports({})
app._write_find_state({})
calls["find"].clear()
alive.update({"wg4": {"alive": True, "handshake_age_s": STUCK_AGE, "tx": 7, "rx": 0,
                      "handshake_at": int(NOW) - int(STUCK_AGE)}})
app.heal_links({"hp-laptop": {"ok": False}})                 # NOTHING answers
fresh_moved = (app._listen_ports().get("hp-laptop") or {}).get("port")
if not fresh_moved:
    problems.append("FIND 2: a pair that does NOT answer, sending and receiving nothing on FRESH "
                    "counters, moves its source port")
if (app._listen_ports().get("hp-laptop") or {}).get("count") != 1:
    problems.append("FIND 2: that repair is ONE rotation, counted once")
if calls["find"]:
    problems.append(f"FIND 2: the port moves before any search, got {calls['find']}")

# FIND 3 — the `roamed` bypass of a stale «ok» is UNTOUCHED (regression of 1df8bd35): every public pair
# this office dials died at one moment, so its own network moved, and a status still «ok» from a pass
# that ran before the tunnels died must not hold the repair back.
app._link_pairs = lambda home, records: [VPS, FP]
app.all_declarations = lambda: [VPS["record"], FP["record"]]
app._write_listen_ports({})
app._write_find_state({})
gone2 = int(NOW) - 230
alive.clear()
alive.update({"wg2": {"alive": False, "handshake_at": gone2},
              "wg6": {"alive": False, "handshake_at": gone2 + 40}})
calls["find"].clear()
app.heal_links({"vps1": {"ok": True}, "fireplace": {"ok": True}})   # a STALE «ok», both of them
roamed_moved = {o: (app._listen_ports().get(o) or {}).get("port") for o in ("vps1", "fireplace")}
if not all(roamed_moved.values()):
    problems.append("FIND 3: a roamed office re-ports every public pair on one pass even with a stale "
                    f"«ok» beside it, got {roamed_moved}")

# FIND 4 (the third find's proof) — the window `alive` is computed with IS `HEAL_AFTER`, not a second
# bound whose number happens to be 180 today: move the env and both move, or the measurement and the
# repair decided on it drift apart in silence.
saved_after = app.HEAL_AFTER
(Path(TUNNEL) / "wg-state.json").write_text(json.dumps(
    {"at": int(time.time()),
     "pairs": {"wg9": {"handshake": int(time.time()) - 90, "endpoint": "(none)", "rx": 0, "tx": 0}}}),
    encoding="utf-8")
app.HEAL_AFTER = 60.0
if (REAL_TUNNEL_MEASURED().get("wg9") or {}).get("alive"):
    problems.append("FIND 4: `alive` is not HEAL_AFTER — a 90 s handshake read as alive with HEAL_AFTER=60")
app.HEAL_AFTER = 120.0
if not (REAL_TUNNEL_MEASURED().get("wg9") or {}).get("alive"):
    problems.append("FIND 4: `alive` is not HEAL_AFTER — a 90 s handshake read as dead with HEAL_AFTER=120")
app.HEAL_AFTER = saved_after

print("heal_links selftest:", "PASS" if not problems else "FAIL")
for p in problems:
    print("  -", p)
sys.exit(1 if problems else 0)
