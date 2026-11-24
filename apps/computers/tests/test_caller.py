"""Who may change something on the computers app — the auth matrix, proved without a server (DGO-1304).

Run: python3 apps/computers/tests/test_caller.py

Every way in, every way a caller could pretend to be one of them, and the one that matters most: a header
typed by a container that is not the hop that writes it. Measured 2026-11-03, before this: any container
on the office network was accepted for `POST /api/computers/<id>/exec` — root on every machine of the fleet.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import caller as C  # noqa: E402
import link_identity as L  # noqa: E402

DOOR, CONSOLE, TRAEFIK, ANY = "172.18.0.10", "172.18.0.2", "172.18.0.27", "172.18.0.99"
SECRET = "6f1c2d3e4a5b6c7d8e9f0a1b2c3d4e5f"
TOKEN = "a" * 64
P = C.Policy(door_addrs={DOOR}, sso_addrs={CONSOLE, TRAEFIK}, share_to={"macbook"}, token=TOKEN,
             secret_of=lambda o: SECRET if o == "macbook" else "")
fails = []


def case(name, facts, want_ok, want_way="", policy=P, why_has=""):
    got = C.identify(facts, policy)
    ok = got.ok == want_ok and (not want_way or got.way == want_way) and (not why_has or why_has in got.why)
    if not ok:
        fails.append(name)
    print(("ok   " if ok else "FAIL ") + f"{name}  → {got.ok} {got.way} {got.who} {got.why[:60]}")


def sig(office, user="akadmin", ts=None, secret=SECRET):
    ts = int(time.time()) if ts is None else ts
    return f"v1 {office} {user} {ts} {L.signature(secret, office, user, ts)}"


# ── the four ways in ─────────────────────────────────────────────────────────────────────────────
case("door: shared office, signed", C.Facts(client=DOOR, office="macbook", claim=sig("macbook")), True, "door")
case("door: unsigned, while the pair HAS a secret → refused (must sign)",
     C.Facts(client=DOOR, office="macbook", user="akadmin"), False)
case("door: unsigned, the pair has no secret here (an office older than the signature)",
     C.Facts(client=DOOR, office="macbook", user="akadmin"), True, "door",
     policy=C.Policy(door_addrs={DOOR}, share_to={"macbook"}, secret_of=lambda o: ""))
case("sso: from the console", C.Facts(client=CONSOLE, user="owner"), True, "sso")
case("sso: from traefik", C.Facts(client=TRAEFIK, user="owner"), True, "sso")
case("token: right token, any address", C.Facts(client=ANY, bearer=TOKEN), True, "token")
case("loopback v4", C.Facts(client="127.0.0.1"), True, "loopback")
case("loopback v6", C.Facts(client="::1"), True, "loopback")

# ── what DGO-1304 found: a container with nothing ───────────────────────────────────────────────
case("a container with no identity", C.Facts(client=ANY), False, why_has="לא ידוע מי מבקש")
case("no address at all", C.Facts(client=""), False)

# ── pretending ──────────────────────────────────────────────────────────────────────────────────
case("SPOOF: x-dgo-office from a non-door address", C.Facts(client=ANY, office="macbook"), False,
     why_has="לא הגיעה מהדלת")
case("SPOOF: a valid signature replayed from a non-door address",
     C.Facts(client=ANY, office="macbook", claim=sig("macbook")), False, why_has="לא הגיעה מהדלת")
case("SPOOF: x-dgo-office + the right token from a non-door address (an office is judged as a door only)",
     C.Facts(client=ANY, office="macbook", bearer=TOKEN), False)
case("SPOOF: the sign-in header from a container", C.Facts(client=ANY, user="owner"), False)
case("SPOOF: the sign-in header from the door (a peer is a door, not the screen)",
     C.Facts(client=DOOR, user="owner"), False)
case("SPOOF: loopback-looking text in a header is not loopback", C.Facts(client=ANY, user="127.0.0.1"), False)
case("door: an office this office does not share with", C.Facts(client=DOOR, office="vps1"), False,
     why_has="COMPUTERS_SHARE_TO")
case("door: the vault did not answer → refused, signed or not",
     C.Facts(client=DOOR, office="macbook", user="akadmin"), False, why_has="שירות החשבונות",
     policy=C.Policy(door_addrs={DOOR}, share_to={"macbook"}, secret_of=lambda o: None))
case("door: the vault did not answer, with a signature → refused",
     C.Facts(client=DOOR, office="macbook", claim=sig("macbook")), False,
     policy=C.Policy(door_addrs={DOOR}, share_to={"macbook"}, secret_of=lambda o: None))
case("door: signature by another secret", C.Facts(client=DOOR, office="macbook",
                                                 claim=sig("macbook", secret="0" * 32)), False)
case("door: signature naming another office", C.Facts(client=DOOR, office="macbook", claim=sig("vps1")), False)
case("door: stale signature", C.Facts(client=DOOR, office="macbook", claim=sig("macbook", ts=1)), False)
case("door: a signature with no office", C.Facts(client=DOOR, claim=sig("macbook")), False)
case("token: wrong token", C.Facts(client=ANY, bearer="b" * 64), False, why_has="שגוי")
case("token: an office with no token minted refuses every bearer",
     C.Facts(client=ANY, bearer=""), False, policy=C.Policy(token=""))
case("token: empty policy token never matches a bearer",
     C.Facts(client=ANY, bearer="x"), False, policy=C.Policy(token=""))
case("door: nothing shared yet (empty COMPUTERS_SHARE_TO)", C.Facts(client=DOOR, office="macbook"), False,
     policy=C.Policy(door_addrs={DOOR}, share_to=set()))

# ── what a door may do: run on the shared computer, nothing else ───────────────────────────────
def check(name, got, want):
    print(("ok   " if got == want else "FAIL ") + f"{name} = {got}")
    if got != want:
        fails.append(name)


L_ = "computer_local-local"
check("door: exec on the shared computer", C.door_allows("POST", f"/api/computers/{L_}/exec"), True)
check("door: probe on the shared computer", C.door_allows("POST", f"/api/computers/{L_}/probe"), True)
check("door: exec on vps1", C.door_allows("POST", "/api/computers/computer_ssh-00000005/exec"), False)
check("door: delete a machine", C.door_allows("DELETE", f"/api/computers/{L_}"), False)
check("door: add a machine", C.door_allows("POST", "/api/computers"), False)
check("door: a share", C.door_allows("POST", f"/api/computers/{L_}/shares"), False)
check("door: stream", C.door_allows("POST", f"/api/computers/{L_}/stream"), False)
check("door: a connection", C.door_allows("DELETE", "/connections/x"), False)
# the interactive shell (DGO-1800): on the shared computer only, and DELETE closes a session and nothing else
check("door: open a shell on the shared computer", C.door_allows("POST", f"/api/computers/{L_}/shell"), True)
check("door: type into it", C.door_allows("POST", f"/api/computers/{L_}/shell/0a1b2c3d4e5f6071/input"), True)
check("door: resize it", C.door_allows("POST", f"/api/computers/{L_}/shell/0a1b2c3d4e5f6071/resize"), True)
check("door: close it", C.door_allows("DELETE", f"/api/computers/{L_}/shell/0a1b2c3d4e5f6071"), True)
check("door: a shell on vps1", C.door_allows("POST", "/api/computers/computer_ssh-00000005/shell"), False)
check("door: DELETE the shell route itself", C.door_allows("DELETE", f"/api/computers/{L_}/shell"), False)
check("door: DELETE a session's input", C.door_allows("DELETE", f"/api/computers/{L_}/shell/0a1b/input"), False)
check("door: a session id that is not one", C.door_allows("POST", f"/api/computers/{L_}/shell/../exec"), False)
check("warn+host: a shell on the host is enforced", C.enforced("POST", f"/api/computers/{L_}/shell", "warn", {L_}), True)
check("warn+host: a shell on another machine stays counted", C.enforced("POST", "/api/computers/y/shell", "warn", {L_}), False)

# ── where a refusal is real while the office is still in `warn` ────────────────────────────────
E = {L_}
check("warn, nothing enforced: exec on the host", C.enforced("POST", f"/api/computers/{L_}/exec", "warn", set()), False)
check("enforce: anything", C.enforced("POST", "/api/computers/x/exec", "enforce", set()), True)
check("warn+host: exec on the host", C.enforced("POST", f"/api/computers/{L_}/exec", "warn", E), True)
check("warn+host: exec on another machine stays counted", C.enforced("POST", "/api/computers/y/exec", "warn", E), False)
check("warn+host: a second record for the host (POST /api/computers)", C.enforced("POST", "/api/computers", "warn", E), True)
check("warn+host: delete it (no trailing slash)", C.enforced("DELETE", f"/api/computers/{L_}", "warn", E), True)
check("warn+host: stream from another machine INTO it", C.enforced("POST", "/api/computers/y/stream", "warn", E), True)
check("warn+host: a cleanup", C.enforced("POST", "/api/hosts/local/machine/cleanup/prune", "warn", E), True)
check("warn+host: a connection", C.enforced("POST", "/connections", "warn", E), True)

# ── the count's buckets are route TEMPLATES, so a caller cannot grow them ───────────────────────
check("shape: exec", C.route_shape("/api/computers/computer_ssh-1a2b/exec"), "/api/computers/{id}/exec")
check("shape: delete", C.route_shape("/api/computers/computer_ssh-1a2b"), "/api/computers/{id}")
check("shape: an invented path", C.route_shape("/api/computers/a/b/c/d"), "(other)")
check("shape: random", C.route_shape("/zz" + "x" * 40), "(other)")
check("shape: open a shell", C.route_shape("/api/computers/computer_ssh-1a2b/shell"), "/api/computers/{id}/shell")
check("shape: type into one", C.route_shape("/api/computers/c/shell/0a1b2c3d4e5f6071/input"),
      "/api/computers/{id}/shell/{sid}/input")
check("shape: close one", C.route_shape("/api/computers/c/shell/0a1b2c3d4e5f6071"), "/api/computers/{id}/shell/{sid}")
check("is_shell: a malformed session id is still a shell route", C.is_shell("/api/computers/c/shell/ZZ"), True)
check("is_shell: exec is not", C.is_shell("/api/computers/c/exec"), False)
check("is_shell: a machine named shell is not", C.is_shell("/api/computers/shell"), False)

# ── every shell route app.py serves is one the caller check knows (read off the decorators, not listed) ──
import re as _re  # noqa: E402
_routes = _re.findall(r'@app\.(get|post|delete)\("(/api/computers/\{cid\}/shell[^"]*)"\)',
                      open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app.py"),
                           encoding="utf-8").read())
check("app.py serves the five shell routes", len(_routes), 5)
for _m, _p in _routes:
    _path = _p.replace("{cid}", L_).replace("{sid}", "0a1b2c3d4e5f6071")
    check(f"{_m.upper()} {_p}: a shell route", C.is_shell(_path), True)
    check(f"{_m.upper()} {_p}: caller.RUN_RE knows it", C.RUN_RE.match(_path) is not None, True)
    check(f"{_m.upper()} {_p}: its own count bucket", C.route_shape(_path) != "(other)", True)

# ── the header's parser ─────────────────────────────────────────────────────────────────────────
for raw, want in (("Bearer abc", "abc"), ("bearer  abc ", "abc"), ("Basic abc", ""), ("", ""), ("Bearer", "")):
    got = C.bearer_of(raw)
    print(("ok   " if got == want else "FAIL ") + f"bearer_of({raw!r}) = {got!r}")
    if got != want:
        fails.append(f"bearer_of {raw!r}")

print(f"\n{'FAIL' if fails else 'PASS'} — {len(fails)} failing" + (": " + ", ".join(fails) if fails else ""))
sys.exit(1 if fails else 0)
