"""The door's signature and the pair's secret, proved without a door, a vault or a machine (link_identity.py).

Run: python3 platform-base/connections/test_link_identity.py

What is being proved, and why each case is here: `x-dgo-office` used to be believed on its own, so any caller that
could reach the port could claim an office and be answered from the shared set — measured 2026-11-01, `x-dgo-office:
nosuchoffice` returned an office's whole fleet. These are the cases that turn the claim into a fact, the ones that
must keep being REFUSED, and how this office's copy of a pair's secret is found in the credential plane.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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
ok, kind, why = L.verify(claim(office="vps1"), office="macbook", secret=SECRET)
check("the office in the header must be the office that was signed", not ok, why)
check("…and that is a mismatch, said as one", kind == "mismatch", kind)
ok, kind, why = L.verify(claim(secret=OTHER), office="macbook", secret=SECRET)
check("another secret does not verify (a stranger's signature)", not ok, why)
check("…a bad mac", kind == "bad-mac", kind)
old = int(time.time()) - L.SIG_WINDOW - 5
ok, kind, why = L.verify(claim(ts=old), office="macbook", secret=SECRET)
check("an old signature is refused", not ok, why)
check("…as stale", kind == "stale", kind)
check("…and says it is stale, not that it is a lie", "עדכנית" in why or "שניות" in why, why)
edge = int(time.time()) - L.SIG_WINDOW + 30
ok, kind, why = L.verify(claim(ts=edge), office="macbook", secret=SECRET)
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

# ── the secret cache: one read per office per ttl; a vault that did not answer is asked again ───
reads = []


def fetch(office):
    reads.append(office)
    if office == "boom":
        raise OSError("vault down")
    if office == "silent":
        return None
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
secrets.get("silent")
secrets.get("silent")
check("a vault that did not answer (None) is not remembered: the next ask reads again",
      reads.count("silent") == 2, str(reads))

# ── the whole door flow, in one line each ──────────────────────────────────────────────────────
check("a local request carries neither header", L.parse("") is None)
fields = L.parse(claim())
check("the door's own claim parses to its four fields",
      fields is not None and fields[0] == "macbook" and fields[1] == "owner")

# ── where a request came from: the second proof, for a door older than the signature ─────────────
DOOR = ["172.18.0.26"]
check("a request from the link's door is recognised", L.from_the_door("172.18.0.26", DOOR))
check("…and a container next door is not", not L.from_the_door("172.18.0.45", DOOR))
check("an unknown source is not the door", not L.from_the_door("", DOOR))
check("a door whose address could not be resolved admits nobody", not L.from_the_door("172.18.0.26", []))
check("the door may hold several addresses (one per network it is on)",
      L.from_the_door("10.0.0.5", ["172.18.0.26", "10.0.0.5"]))

# ── link_secret: this office's copy of a pair's secret, matched as the door matches it ───────────
ROWS = [
    {"id": "dgo_link-serve-macbook-agent", "account_hint": "macbook->here"},      # a credential handed over
    {"id": "dgo_link-hp-laptop", "account_hint": "pair"},
    {"id": "dgo_link-x1", "account_hint": "macbook->vps1 since 11-01"},
    {"id": "dgo_link-hp", "account_hint": ""},
]
TOKENS = {"dgo_link-serve-macbook-agent": "AGENT", "dgo_link-hp-laptop": "HP", "dgo_link-x1": "MAC", "dgo_link-hp": ""}


def vault(status=200, secret_status=200, raise_on=None):
    asked = []

    def get_json(path, params):
        asked.append(path)
        if raise_on and raise_on in path:
            raise OSError("down")
        if path == "/api/instances":
            return status, {"instances": ROWS}
        iid = path.split("/")[3]
        return secret_status, {"secret": {"token": TOKENS.get(iid, "")}}
    return get_json, asked


get, asked = vault()
check("the pair's row by its id", L.link_secret(get, "hp-laptop") == "HP")
check("…a hyphenated office is never split: «hp» is not «hp-laptop»", L.link_secret(vault()[0], "hp") == "")
check("the pair's row by its hint «<a>-><b>»", L.link_secret(vault()[0], "macbook") == "MAC")
check("a credential a linked office handed over (dgo_link-serve-*-agent) is never the pair's secret",
      L.link_secret(vault()[0], "macbook") != "AGENT")
check("an office the vault holds no pair for: \"\" (it answered)", L.link_secret(vault()[0], "nosuchoffice") == "")
check("a vault that answered badly: None (refuse), never \"\"", L.link_secret(vault(status=500)[0], "hp-laptop") is None)
check("…the secret's own read failing: None", L.link_secret(vault(secret_status=503)[0], "hp-laptop") is None)
check("…a vault that raises: None", L.link_secret(vault(raise_on="/api/instances")[0], "hp-laptop") is None)
get, asked = vault()
check("an office id that is not an id is never asked", L.link_secret(get, "Not An Id") == "" and asked == [])

print()
if fails:
    print(f"{len(fails)} FAILED:")
    for f in fails:
        print("  - " + f)
    sys.exit(1)
print("all checks passed")
