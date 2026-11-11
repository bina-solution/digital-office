"""The door's signature, proved without a door, a vault or a machine.

Run: python3 apps/computers/tests/test_link_identity.py

What is being proved, and why each case is here: `x-dgo-office` used to be believed on its own, so any
caller that could reach the port could claim an office and be answered from the shared set — measured
2026-11-01, `x-dgo-office: nosuchoffice` on this office's own `computers` returned the whole fleet.
These are the cases that turn the claim into a fact, and the ones that must keep being REFUSED.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import link_identity as L  # noqa: E402

SECRET = "6f1c2d3e4a5b6c7d8e9f0a1b2c3d4e5f"
OTHER = "00000000000000000000000000000000"

fails = []


def check(name, ok, detail=""):
    if not ok:
        fails.append(f"{name}{(' — ' + detail) if detail else ''}")
    print(("ok   " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))


def claim(office="macbook", user="owner", ts=None, secret=SECRET):
    ts = int(time.time()) if ts is None else int(ts)
    return f"v1 {office} {user} {ts} {L.signature(secret, office, user, ts)}"


# ── a real signature verifies, and only for the office it names ──────────────────────────────────
ok, kind, why = L.verify(claim(), office="macbook", secret=SECRET)
check("a signature the door would have written verifies", ok, why)
check("…and says so", kind == "ok", kind)

ok, kind, why = L.verify("", office="macbook", secret=SECRET)
check("no signature is its own case (a door older than this op, not a lie)", kind == "unsigned", kind)

ok, kind, why = L.verify(claim(office="macbook"), office="vps1", secret=SECRET)
check("the office in the header must be the office that was signed", not ok, why)
check("…and that is a mismatch, said as one", kind == "mismatch", kind)

ok, kind, why = L.verify(claim(secret=OTHER), office="macbook", secret=SECRET)
check("another secret does not verify (a stranger's signature)", not ok, why)
check("…a bad mac", kind == "bad-mac", kind)

# ── the window ───────────────────────────────────────────────────────────────────────────────────
old = int(time.time()) - (L.SIG_WINDOW + 30)
ok, kind, why = L.verify(claim(ts=old), office="macbook", secret=SECRET)
check("an old signature is refused", not ok, why)
check("…as stale", kind == "stale", kind)
check("…and says it is stale, not that it is a lie", "עדכנית" in why or "שניות" in why, why)

fresh = int(time.time()) - (L.SIG_WINDOW - 30)
ok, kind, why = L.verify(claim(ts=fresh), office="macbook", secret=SECRET)
check("the last minute of the window still passes", ok, why)

future = int(time.time()) + 3600
ok, kind, why = L.verify(claim(ts=future), office="macbook", secret=SECRET)
check("a signature from the future is refused too (a clock cannot widen it)", not ok, why)

# ── the shapes that never verify ────────────────────────────────────────────────────────────────
for name, bad in [
    ("no header at all", ""),
    ("a bare office header (the forgery that was served)", "macbook"),
    ("a truncated signature", claim().rsplit(" ", 1)[0]),
    ("a wrong version", claim().replace("v1 ", "v2 ", 1)),
    ("a tampered user", claim().replace("owner", "root")),
    ("an office that is not an id", claim(office="Mac Book")),
    ("a timestamp that is not a number", "v1 macbook owner soon deadbeef"),
]:
    ok, kind, why = L.verify(bad, office="macbook", secret=SECRET)
    check(f"refused: {name}", not ok, why)
    check(f"…with a sentence for the person: {name}", bool(why.strip()))

# ── no secret here = no identity, and it is said ───────────────────────────────────────────────
ok, kind, why = L.verify(claim(), office="macbook", secret="")
check("a pair with no secret here refuses (a check that cannot run must not pass)", not ok, why)

# ── the secret cache: one read per office per ttl, and a read that fails is "no secret" ────────
reads = []


def fetch(office):
    reads.append(office)
    if office == "boom":
        raise OSError("vault down")
    return SECRET


secrets = L.Secrets(fetch, ttl=60)
check("a secret is read once", secrets.get("macbook") == SECRET and len(reads) == 1, str(reads))
secrets.get("macbook")
check("…and the second ask is from memory", len(reads) == 1, str(reads))
check("a vault that raises is 'no secret', never an exception", secrets.get("boom") == "")
secrets.forget("macbook")
secrets.get("macbook")
check("forget() makes the next ask read again", len(reads) == 3, str(reads))
check("an office id that is not an id is never asked", secrets.get("Not An Id") == ""
      and len(reads) == 3, str(reads))

# ── the whole door flow, in one line each ──────────────────────────────────────────────────────
# a LOCAL request names nothing and is not asked anything: the app's other half of _door_caller.
check("a local request carries neither header", L.parse("") is None)
fields = L.parse(claim())
check("the door's own claim parses to its four fields",
      fields is not None and fields[0] == "macbook" and fields[1] == "owner")

# ── where a request came from: the second proof, for a door older than the signature ─────────────
#: The door's own address, as `dgo-net` resolves it inside the office network. Anything else in this
#: network is another container — which is exactly the caller the header alone could not tell apart.
DOOR = ["172.18.0.26"]

check("a request from the link's door is recognised", L.from_the_door("172.18.0.26", DOOR))
check("…and a container next door is not", not L.from_the_door("172.18.0.45", DOOR))
check("an unknown source is not the door", not L.from_the_door("", DOOR))
check("a door whose address could not be resolved admits nobody",
      not L.from_the_door("172.18.0.26", []))
check("the door may hold several addresses (one per network it is on)",
      L.from_the_door("10.0.0.5", ["172.18.0.26", "10.0.0.5"]))

print()
if fails:
    print(f"{len(fails)} FAILED:")
    for f in fails:
        print("  - " + f)
    sys.exit(1)
print("all checks passed")
