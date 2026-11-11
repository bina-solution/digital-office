#!/usr/bin/env python3
"""test_one_off_invites — §9's ONE-OFF INVITE (`DGOJOIN1:`) is a test, not a paragraph (rel-3).

SECTION 9 OF THE RELEASE (rel-3, `apps/project-pln/plans/dgo-dev.yaml`): every security claim is a
test. The claim here is `join_api.py`'s own: an office that can only DIAL joins another by one line
of its `.env` — an INVITE, Tailscale's auth key — with nobody looking at either screen. What that
sentence is worth is entirely made of the refusals around it, and until today they lived in a
`selftest()` that only `python3 apps/dgo-extend/join_api.py` ran, so nothing that gates a change ran
them (gate G72 is the one that does; its discovery takes `apps/<app>/tests/test_*`).

There are 14 claims, and every one of them is measured by DRIVING THE REAL CODE in memory — `Hub`,
`Joiner`, `pair_api.Pairing` and `pair_api._MemoryPorts` (the app's own test seam), the counter's own
`http` in place of the network, and a temp directory for the stores. No office is touched, no socket
is opened, no container is started:

  invite.a-reusable-key-names-its-office   a reusable key for ANY name would let one leaked line
                                           become any number of offices — refused at the mint;
  invite.an-office-with-no-door-cannot-…   a host that publishes no link address has nowhere to invite
                                           to — refused, in words that say so;
  invite.the-listing-carries-no-key        what the screen lists back holds neither half of the key;
  invite.the-host-keeps-the-public-half     the inviting office's own store holds the PUBLIC half
                                           only: the access key exists in the text alone, so a stolen
                                           disk admits nobody;
  invite.single-use-admits-one-office      one office joins from one `.env` line, nobody looking;
  invite.single-use-refuses-the-second     …and the same line admits nobody after that;
  invite.bound-to-the-office-it-names      an invite minted for one id admits no other id;
  invite.revoked-admits-nobody             revocation is a refusal, not a note
  invite.expired-admits-nobody             as is its window (the clock is the module's own `now`);
  invite.a-forged-key-admits-nobody        the key that signs must be the one the host minted;
  invite.a-reply-from-an-unpinned-office-…   an answer from an office the invite did not pin writes
                                           nothing on the joiner;
  invite.reusable-counts-and-stays-live    a reusable invite counts its uses and rests live;
  invite.a-join-never-replaces-a-paired-…  a join replaces only a record a join wrote, never the one
                                           two people paired from their screens;
  invite.a-reborn-office-replaces-its-own  a sandbox reborn with new keys under the same id replaces
                                           its own last record;
  invite.its-own-selftest-is-green         the module's remaining refusals (the approval path, the
                                           offer's proof, the reply's WireGuard binding, the routes)
                                           are run as they are written — one claim, one run.

THE PROOF THAT IT CAN FAIL is `--inject`: three regressions, each written into the module IN MEMORY
(a monkeypatched `_new_invite_key`, `invite_create`, `invite_revoke` — nothing on disk, no source
file touched), and each one is required to be CAUGHT by the claim that names it. A mutation nobody
catches is a failure of this file's sensitivity, and it says so and exits 1.

Run:  python3 apps/dgo-extend/tests/test_one_off_invites.py            # exit 0 = every claim held
      python3 apps/dgo-extend/tests/test_one_off_invites.py --inject   # …and each regression caught
Exit 1 = a claim is broken (or an injection went unnoticed). The file prints claim names, counts and
booleans; it never prints a key, a seed or a token — the values it compares are compared in memory.
"""
from __future__ import annotations

import json
import secrets
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import join_api                                                     # noqa: E402
import pair_api                                                     # noqa: E402
from pair_api import PairError                                      # noqa: E402

LINK = "link.example.org"
TMP = Path(tempfile.mkdtemp(prefix="invite-claims-"))


# ── the bench: the app's own in-memory offices, and its own `http` ───────────────────────────────
def hub_of(ports, host: str = LINK):
    return join_api.Hub(pair_api.Pairing(ports),
                        TMP / f"hub-{ports.home()['id']}-{secrets.token_hex(3)}.json",
                        host=lambda: host)


def shim(hub, source: str = "203.0.113.5"):
    """The counter's own HTTP, in memory: exactly the two paths the carrier gives this module."""
    def http(method, url, body=None, headers=None):
        try:
            if method == "POST" and url.endswith("/join"):
                return 200, hub.join(body or {}, source)
            if method == "GET" and "/join/" in url:
                out = hub.poll(url.rsplit("/", 1)[1], (headers or {}).get("X-Dgo-Poll", ""))
                return (404 if out.get("state") == "unknown" else 200), out
        except PairError as e:
            return e.status, {"error": str(e)}
        return 404, {"error": "no such path"}
    return http


def joiner_of(ports, hub, env, name: str = ""):
    return join_api.Joiner(pair_api.Pairing(ports), TMP / f"joiner-{secrets.token_hex(3)}.json",
                           http=shim(hub), env=env)


def ports(oid: str, label: str, slot: int = 1):
    return pair_api._MemoryPorts(oid, label, slot=slot)


def refused(fn, *a, **k) -> bool:
    try:
        fn(*a, **k)
        return False
    except PairError:
        return True


def minted_pair():
    """A live host, its pin, one reusable invite, and the text that leaves the building."""
    host_ports = pair_api._MemoryPorts("vps1", "vps1", slot=1,
                                       listen={"endpoint": "console.example.org", "port": 51830})
    hub = hub_of(host_ports)
    text = hub.invite_create("claude-cloud", "both", reusable=True)["text"]
    return host_ports, hub, text, host_ports.home()["identity"]["ed25519"]


# ── the claims ──────────────────────────────────────────────────────────────────────────────────
def c_a_reusable_key_names_its_office() -> list[str]:
    """A reusable key for ANY name would let one leaked line become any number of offices."""
    _host, hub, _text, _pin = minted_pair()
    if not refused(hub.invite_create, "", "both", None, True):
        return ["a reusable invite for ANY office is minted — one leaked line would admit many"]
    if not refused(hub.invite_create, "Bad Name", "both", None, True):
        return ["an office id that is not one is invited to anyway"]
    return []


def c_an_office_with_no_door_cannot_invite() -> list[str]:
    """Nothing to pin, nowhere to send: a host that publishes no link address mints no invite."""
    host_ports = pair_api._MemoryPorts("vps1", "vps1", slot=1,
                                       listen={"endpoint": "console.example.org", "port": 51830})
    if not refused(hub_of(host_ports, host="").invite_create, "claude-cloud"):
        return ["an office with no public link door minted an invite to nowhere"]
    return []


def c_the_listing_carries_no_key() -> list[str]:
    """What the screen lists back is not a key, and not half of one."""
    _host, hub, text, _pin = minted_pair()
    listing = hub.invites()
    if len(listing) != 1:
        return [f"one minted invite lists as {len(listing)}"]
    row = listing[0]
    for name in ("key", "seed", "priv", "pub", "private"):
        if name in row:
            return [f"the invite's listing carries `{name}`"]
    if join_api.parse_invite(text)["key"] in json.dumps(row):
        return ["the listing carries the invite's access key"]
    return []


def c_the_host_keeps_the_public_half() -> list[str]:
    """The access key exists in the TEXT alone: a stolen store admits nobody."""
    _host, hub, text, _pin = minted_pair()
    seed = join_api.parse_invite(text)["key"]
    if seed in json.dumps(hub.store.load()):
        return ["the inviting office's store holds the invite's private key"]
    if "seed" in json.dumps(hub.store.load()):
        return ["the store grew a `seed` field"]
    return []


def c_single_use_admits_one_office() -> list[str]:
    """One line of a sandbox's `.env`, and nobody has to be in front of either screen."""
    _host, hub, _text, _pin = minted_pair()
    once = hub.invite_create("", "both")
    lab = ports("lab-1", "Lab")
    got = joiner_of(lab, hub, {"DGO_JOIN": once["text"]}).step()
    if got.get("state") != "joined" or "vps1" not in lab.records:
        return [f"a single-use invite did not join its first office: {got.get('state')}"]
    return []


def c_single_use_refuses_the_second() -> list[str]:
    """…and the same text, held by somebody else, is worth nothing afterwards."""
    _host, hub, _text, _pin = minted_pair()
    once = hub.invite_create("")
    first, second = ports("lab-1", "Lab"), ports("lab-2", "Lab")
    if joiner_of(first, hub, {"DGO_JOIN": once["text"]}).step().get("state") != "joined":
        return ["the first office did not join, so the second use was never measured"]
    if joiner_of(second, hub, {"DGO_JOIN": once["text"]}).step().get("state") == "joined":
        return ["a single-use invite admitted a second office"]
    if second.records:
        return ["the refused second office wrote a record anyway"]
    return []


def c_bound_to_the_office_it_names() -> list[str]:
    """An invite minted for one id admits no other id."""
    _host, hub, _text, _pin = minted_pair()
    single = hub.invite_create("claude-cloud", "use")
    someone = ports("someone", "X")
    if joiner_of(someone, hub, {"DGO_JOIN": single["text"]}).step().get("state") == "joined":
        return ["an invite for one office admitted another"]
    return []


def c_revoked_admits_nobody() -> list[str]:
    """Revocation is a refusal, not a note."""
    _host, hub, _text, _pin = minted_pair()
    inv = hub.invite_create("claude-cloud", "both")
    hub.invite_revoke(join_api.parse_invite(inv["text"])["id"])
    fresh = ports("claude-cloud", "Claude Cloud")
    if joiner_of(fresh, hub, {"DGO_JOIN": inv["text"]}).step().get("state") == "joined":
        return ["a revoked invite still admitted the office it named"]
    if fresh.records:
        return ["a revoked invite wrote a record on the joiner"]
    return []


def c_expired_admits_nobody() -> list[str]:
    """The window is the module's own clock, so it is measured by moving it."""
    host_ports = pair_api._MemoryPorts("vps1", "vps1", slot=1,
                                       listen={"endpoint": "console.example.org", "port": 51830})
    hub = hub_of(host_ports)
    late = hub.invite_create("lab-3", "both")
    row = hub.store.load()["invites"][join_api.parse_invite(late["text"])["id"]]
    future = join_api.Hub(pair_api.Pairing(host_ports), TMP / f"hub-late-{secrets.token_hex(3)}.json",
                          host=lambda: LINK, now=lambda: time.time() + 8 * 86400)
    future.store.save({"invites": {row["id"]: row}})
    if not refused(future._join_invited, "x", {"office": "lab-3"}, row["id"], "", ""):
        return ["an expired invite admitted an office eight days later"]
    return []


def c_a_forged_key_admits_nobody() -> list[str]:
    """The key that signs must be the one the host minted, and the host never kept it."""
    _host, hub, text, _pin = minted_pair()
    parsed = join_api.parse_invite(text)
    _other_seed, _other_pub = join_api._new_invite_key()
    other_seed, _pub = join_api._new_invite_key()
    forged = join_api.invite_text({"v": 1, "hub": parsed["hub"], "id": parsed["id"], "key": other_seed,
                                  "pin": parsed["pin"], "office": "claude-cloud"})
    fresh = ports("claude-cloud", "Claude Cloud")
    if joiner_of(fresh, hub, {"DGO_JOIN": forged}).step().get("state") == "joined":
        return ["an invite whose key is not the one the host minted admitted an office"]
    if fresh.records:
        return ["a forged invite wrote a record on the joiner"]
    return []


def c_reply_from_an_unpinned_office_writes_nothing() -> list[str]:
    """The joiner pins the host's identity: an answer signed by any other key is refused."""
    _host, _hub, _text, pin = minted_pair()
    fake_ports = pair_api._MemoryPorts("vps1", "fake vps1", slot=1)
    fake_hub = hub_of(fake_ports)
    doc = join_api.parse_invite(fake_hub.invite_create("claude-cloud", "both", reusable=True)["text"])
    repinned = join_api.invite_text({"v": 1, "hub": doc["hub"], "id": doc["id"], "key": doc["key"],
                                    "pin": pin, "office": "claude-cloud"})
    victim = ports("claude-cloud", "Claude Cloud")
    state = joiner_of(victim, fake_hub, {"DGO_JOIN": repinned}).step()
    if state.get("state") == "joined":
        return ["a reply from an office the invite did not pin was accepted"]
    if victim.records:
        return ["a reply from an unpinned office wrote a record"]
    return []


def c_reusable_counts_and_stays_live() -> list[str]:
    """A reusable invite is usable and counted — and the count is the operator's to read."""
    _host, hub, text, _pin = minted_pair()
    if joiner_of(ports("claude-cloud", "Claude Cloud"), hub, {"DGO_JOIN": text}).step().get("state") != "joined":
        return ["a reusable invite did not admit its first office"]
    row = hub.invites()[0]
    if (row.get("uses"), row.get("state")) != (1, "live"):
        return [f"a reusable invite after one join reads uses={row.get('uses')} state={row.get('state')}"]
    return []


def c_a_join_never_replaces_a_paired_record() -> list[str]:
    """An office paired by two people under that name is not overwritten by a join."""
    _host, hub, _text, _pin = minted_pair()
    host_ports = pair_api._MemoryPorts("vps1", "vps1", slot=1,
                                       listen={"endpoint": "console.example.org", "port": 51830})
    host_ports.records["hp-laptop"] = {"id": "hp-laptop", "kind": "paired", "tunnel": {"slot": 3}}
    hub2 = hub_of(host_ports)
    inv = hub2.invite_create("hp-laptop", "both", reusable=True)
    impostor = ports("hp-laptop", "HP?")
    joined = joiner_of(impostor, hub2, {"DGO_JOIN": inv["text"]}).step().get("state") == "joined"
    if joined or host_ports.records["hp-laptop"].get("tunnel", {}).get("door"):
        return ["a join replaced (or overwrote the tunnel of) a record a pairing wrote"]
    return []


def c_a_reborn_office_replaces_its_own() -> list[str]:
    """A sandbox is reborn with new keys under the same id, and the same line joins it again."""
    host_ports, hub, text, _pin = minted_pair()
    if joiner_of(ports("claude-cloud", "Claude Cloud"), hub, {"DGO_JOIN": text}).step().get("state") != "joined":
        return ["the fresh sandbox did not join, so the reborn case was never measured"]
    reborn = ports("claude-cloud", "Claude Cloud")
    if joiner_of(reborn, hub, {"DGO_JOIN": text}).step().get("state") != "joined":
        return ["a reborn sandbox did not replace its own last record"]
    if host_ports.records["claude-cloud"]["identity"]["ed25519"] != reborn.home()["identity"]["ed25519"]:
        return ["the host still holds the reborn sandbox's OLD identity"]
    return []


def c_its_own_selftest_is_green() -> list[str]:
    """Everything else this module refuses, run exactly as it is written."""
    return [f"the module's own selftest: {p}" for p in join_api.selftest()]


CLAIMS = [
    ("invite.a-reusable-key-names-its-office", c_a_reusable_key_names_its_office),
    ("invite.an-office-with-no-door-cannot-invite", c_an_office_with_no_door_cannot_invite),
    ("invite.the-listing-carries-no-key", c_the_listing_carries_no_key),
    ("invite.the-host-keeps-the-public-half", c_the_host_keeps_the_public_half),
    ("invite.single-use-admits-one-office", c_single_use_admits_one_office),
    ("invite.single-use-refuses-the-second", c_single_use_refuses_the_second),
    ("invite.bound-to-the-office-it-names", c_bound_to_the_office_it_names),
    ("invite.revoked-admits-nobody", c_revoked_admits_nobody),
    ("invite.expired-admits-nobody", c_expired_admits_nobody),
    ("invite.a-forged-key-admits-nobody", c_a_forged_key_admits_nobody),
    ("invite.a-reply-from-an-unpinned-office-writes-nothing", c_reply_from_an_unpinned_office_writes_nothing),
    ("invite.reusable-counts-and-stays-live", c_reusable_counts_and_stays_live),
    ("invite.a-join-never-replaces-a-paired-record", c_a_join_never_replaces_a_paired_record),
    ("invite.a-reborn-office-replaces-its-own", c_a_reborn_office_replaces_its_own),
    ("invite.its-own-selftest-is-green", c_its_own_selftest_is_green),
]

#: (the regression, the claim that must catch it) — each one is written into the module IN MEMORY.
INJECTIONS = [
    ("the host keeps the access key too", "invite.the-host-keeps-the-public-half"),
    ("a minted invite is reusable whatever it was asked for", "invite.single-use-refuses-the-second"),
    ("revocation stops doing anything", "invite.revoked-admits-nobody"),
]


def _patch(name: str, value) -> tuple[str, object]:
    """Set one module attribute and hand back what was there, so the run can put it back."""
    old = getattr(join_api, name)
    setattr(join_api, name, value)
    return name, old


def _inject_regression(what: str) -> list[tuple[str, object]]:
    if what == "the host keeps the access key too":
        # the private half written where the public half belongs: a stolen store then admits anybody
        original_new_key = join_api._new_invite_key

        def seed_where_the_public_half_belongs():
            seed, _pub = original_new_key()
            return seed, seed
        return [_patch("_new_invite_key", seed_where_the_public_half_belongs)]
    if what == "a minted invite is reusable whatever it was asked for":
        original = join_api.Hub.invite_create

        def forced(self, office="", direction="both", ttl=None, reusable=False, label=""):
            out = original(self, office, direction, ttl, reusable, label)
            doc = self.store.load()                      # …and its single use is edited away afterwards
            row = doc["invites"][join_api.parse_invite(out["text"])["id"]]
            row["reusable"] = True
            self.store.save(doc)
            return out
        join_api.Hub.invite_create = forced
        return [("Hub.invite_create", original)]
    if what == "revocation stops doing anything":
        old = join_api.Hub.invite_revoke
        join_api.Hub.invite_revoke = lambda self, iid: {}
        return [("Hub.invite_revoke", old)]
    raise SystemExit(f"unknown injection: {what}")


def main(argv: list[str]) -> int:
    inject = "--inject" in argv
    failures = 0
    for name, claim in CLAIMS:
        try:
            problems = claim()
        except Exception as e:                                # a claim that cannot be measured is not a pass
            problems = [f"raised {type(e).__name__}: {e}"]
        if problems:
            failures += 1
            print(f"FAIL {name}")
            for p in problems:
                print(f"     {p}")
        else:
            print(f"PASS {name}")
    print(f"one-off invites: {'PASS' if not failures else 'FAIL'} "
          f"({len(CLAIMS) - failures}/{len(CLAIMS)} claims held)")
    if failures:
        return 1
    if not inject:
        return 0

    unnoticed = 0
    for what, must_catch in INJECTIONS:
        undo = _inject_regression(what)
        try:
            caught = bool(dict(CLAIMS)[must_catch]())
        except Exception as e:                                # a mutation may make a claim raise; that IS caught
            caught = True
            print(f"     ({must_catch} raised {type(e).__name__} under the injection)")
        finally:
            for name, old in undo:
                target, attr = (join_api, name) if "." not in name else (
                    getattr(join_api, name.split(".")[0]), name.split(".")[1])
                setattr(target, attr, old)
        if caught:
            print(f"CAUGHT {must_catch} by: {what}")
        else:
            unnoticed += 1
            print(f"UNCAUGHT {must_catch}: {what} went unnoticed — this file is not sensitive to it")
    print(f"injection: {'PASS' if not unnoticed else 'FAIL'} "
          f"({len(INJECTIONS) - unnoticed}/{len(INJECTIONS)} regressions caught)")
    return 1 if unnoticed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
