#!/usr/bin/env python3
"""test_pair_qr — §9's “Rogue office by QR” is a test: what a camera photographs is PUBLIC (rel-3).

SECTION 9 OF THE RELEASE (rel-3, `apps/project-pln/plans/dgo-dev.yaml`): every security claim is a
test. §9's threat table has one row about the pairing QR — “Rogue office by QR → single-use, 10-min
offer” — and no mitigation there is worth anything unless the payload itself carries nothing secret:
a QR is displayed on a screen and photographed off it. `pair_api.py`'s own claim is that the offer
(`DGOPAIR1:`) is public material only — the joiner's office id, its PUBLIC Ed25519 and WireGuard keys,
its candidate addresses — and that the link token is minted at the CLAIM, sealed to the offer's
ephemeral key, and never appears in any answer to either screen. Until today that claim lived in a
`selftest()` only `python3 apps/dgo-extend/pair_api.py` ran, so nothing that gates a change ran it
(gate G72 is the one that does; its discovery takes `apps/<app>/tests/test_*`).

Eleven claims, each measured by DRIVING THE REAL CODE in memory — `pair_api.Pairing` over
`pair_api._MemoryPorts` (the app's own test seam) and a temp directory for the stores. No office is
touched, no socket is opened, no browser is driven:

  qr.the-payload-is-what-a-scan-reads  the text the API shows is byte-identical to what
                                       `pairing.parse_offer` → `pairing.offer_text` round-trips, so what
                                       is measured here is exactly what a camera captures;
  qr.carries-public-material-only      every field of that payload is on the public allow-list, no
                                       field is NAMED like a secret, and the office's private identity
                                       appears nowhere in it — a photograph is worth nothing;
  qr.no-token-in-any-answer            no answer to either screen (offer, claim, claim read-back,
                                       reply) carries a field named like a token or a private key;
  qr.nothing-is-written-before-both-…  after the offer and the claim, and before either operator
                                       confirms, neither vault and neither record list has changed;
  qr.both-screens-show-the-same-code   the six digits are the same on both sides, and the joiner is
                                       told who answered — the one check a person performs;
  qr.a-wrong-code-writes-nothing       a wrong code is refused on BOTH sides and writes nothing;
  qr.a-photograph-cannot-confirm       confirming before the reply was read is refused: holding the
                                       photographed payload is not the same as having the secret;
  qr.the-offer-is-answered-once        after the pair is written the offer reads `confirmed`, and
                                       neither side can confirm it a second time;
  qr.an-old-offer-is-refused           §9's other number in that same sentence: the window. The clock
                                       is moved past `pairing.OFFER_TTL` (the invite side's own
                                       technique) and the offer is refused at every door that reads
                                       it — the joiner's poll, its reply, its confirmation, and the
                                       HOST's claim, which is where a replayed photograph arrives —
                                       while one second inside the window the same flow still pairs;
  qr.an-offer-cannot-buy-a-longer-win…  (DOCUMENTED GAP — see below) the window belongs to the
                                       ANSWERING office, so an offer that declares thirty days must
                                       not be answered at all;
  qr.its-own-selftest-is-green         the module's remaining decisions (slots, direction, giving,
                                       names, twin offices) are run as they are written.

ONE OF THE ELEVEN IS A DOCUMENTED GAP, not a pass. “10-min offer” is a promise about the office that
ANSWERS, and the offer's `expires_at` is the SENDER's field: `pair_api.Pairing.claim` compares it to
now and never caps it against `pairing.OFFER_TTL`, so a host answers an offer that declares a month —
the rule the join door already applies (`join_api.Hub.join`, «תוקף ההצעה אינו התוקף שהלשכה הזאת
מקבלת»). That claim is listed in `KNOWN_GAPS` and reported as XFAIL; the marker is not a place to
leave a pass, and a gap that closes without it being removed is an XPASS, which FAILS this file.

THE PROOF THAT IT CAN FAIL is `--inject`: four regressions, each written into the module IN MEMORY (a
monkeypatched `Pairing.offer` that puts a private value into the payload the QR is made of; a
monkeypatched `Pairing.claim` whose answer carries the token; a `Pairing.offer` whose offer is good
for a day; and a `pairing.is_expired` that never says yes) — nothing on disk, no source file
touched — and each one is required to be CAUGHT by the claim that names it. A mutation nobody catches
is a failure of this file's sensitivity, and it says so and exits 1.

Run:  python3 apps/dgo-extend/tests/test_pair_qr.py            # exit 0 = every claim held (a
                                                              #   documented gap does not fail it)
      python3 apps/dgo-extend/tests/test_pair_qr.py --inject   # …and each regression caught
Exit 1 = a claim is broken (or an injection went unnoticed), or a documented gap closed and its
marker stayed. The file prints claim names, counts and booleans; it never prints a key, a seed or a
token — values are compared in memory, never printed.
"""
from __future__ import annotations

import base64
import json
import re
import secrets
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import pair_api                                                     # noqa: E402
import pairing                                                      # noqa: E402
from pair_api import PairError                                      # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="qr-claims-"))

#: What the QR is allowed to carry: the joiner's public identity and where it listens. A field added
#: to the offer without being named here FAILS — that is the point of a declared allow-list.
PUBLIC_FIELDS = {"v", "offer_id", "office", "label", "direction", "identity", "endpoints", "listen",
                 "used_slots", "ephemeral", "created_at", "expires_at"}
#: A name that would make a field a secret whatever it holds.
SECRET_NAME = re.compile(r"priv|seed|secret|token|passw|bearer", re.I)


# ── the bench: two in-memory offices, one offer, one claim ───────────────────────────────────────
def offices():
    """(the joiner's ports, the host's ports) — the owner's own case: a LAN address on one side."""
    joiner = pair_api._MemoryPorts("hp-laptop", "HP", slot=1,
                                   listen={"endpoint": "192.168.16.102", "port": 51830})
    host = pair_api._MemoryPorts("macbook", "MacBook", slot=2)
    return joiner, host


def blocked(fn, *a, **k) -> bool:
    try:
        fn(*a, **k)
        return False
    except PairError:
        return True


def refusal(fn, *a, **k) -> str:
    """The refusal's own words, or "" when the call was allowed.

    A claim about a WINDOW needs the reason and not only the fact: a call refused because an id is
    unknown is a different refusal from one refused because the window closed, and only the second is
    what §9's “10-min offer” promises an operator.
    """
    try:
        fn(*a, **k)
    except PairError as e:
        return str(e)
    return ""


#: What makes a refusal a refusal about the window (`pairing.py` and `pair_api.py` speak Hebrew).
EXPIRY_WORDS = re.compile(r"פג|expir", re.I)


def clocked():
    """Two offices whose clock this FILE holds — the invite side's technique, moved to the QR side.

    `test_one_off_invites.py`'s `c_expired_admits_nobody` hands `join_api.Hub` a `now` eight days
    ahead; the pairing engine has the same seam (`pair_api.Pairing(ports, now=…)`, which it passes
    down to `pairing.Offers`), so the same move is available here and nothing waits ten minutes. The
    clock is a one-cell LIST because the claim has to move the very clock the engine reads.
    """
    clock = [time.time()]
    joiner, host = offices()
    return (clock, pair_api.Pairing(joiner, now=lambda: clock[0]),
            pair_api.Pairing(host, now=lambda: clock[0]), joiner, host)


def _key_names(obj, path="") -> list[str]:
    """Every dict key anywhere in an answer, with where it sat."""
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            found.append(f"{path}.{k}" if path else str(k))
            found += _key_names(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found += _key_names(v, f"{path}[{i}]")
    return found


def _offer_of(joiner):
    """(the engine, its offer, the payload a camera would capture, and the parsed payload)."""
    engine = pair_api.Pairing(joiner)
    offer = engine.offer("serve")
    payload = offer["text"]
    return engine, offer, payload, pairing.parse_offer(payload)


# ── the claims ──────────────────────────────────────────────────────────────────────────────────
def c_the_payload_is_what_a_scan_reads() -> list[str]:
    """The text the API hands the screen IS the QR payload, and a scan reads back the same bytes."""
    joiner, _host = offices()
    _engine, offer, payload, parsed = _offer_of(joiner)
    if not payload.startswith(pairing.PREFIX):
        return [f"the payload does not start with the offer's own prefix ({pairing.PREFIX})"]
    if pairing.offer_text(parsed) != payload:
        return ["the payload does not survive its own round trip — a scan would read something else"]
    if offer["offer"]["offer_id"] != parsed["offer_id"]:
        return ["the offer object and the payload describe two different offers"]
    if parsed["identity"] != {k: joiner.home()["identity"][k] for k in ("ed25519", "wg", "fingerprint")}:
        return ["the payload's identity is not the joiner's own public identity"]
    return []


def c_carries_public_material_only() -> list[str]:
    """Everything a photograph of the QR is worth: nothing."""
    joiner, _host = offices()
    _engine, _offer, payload, parsed = _offer_of(joiner)
    unknown = sorted(set(parsed) - PUBLIC_FIELDS)
    if unknown:
        return [f"the payload carries fields that are not declared public: {unknown}"]
    named = sorted({f for f in parsed if SECRET_NAME.search(f)})
    if named:
        return [f"the payload carries a field NAMED like a secret: {named}"]
    private = joiner.identity_private()
    if private and (private in payload or private in json.dumps(parsed)):
        return ["the payload carries the office's private identity — the QR alone would admit it"]
    raw = base64.b64decode(private + "=" * (-len(private) % 4)) if private else b""
    if raw and base64.b64encode(raw).decode().rstrip("=") in payload:
        return ["the payload carries the private key in another encoding"]
    if parsed["identity"].get("ed25519") != joiner.home()["identity"]["ed25519"]:
        return ["the payload's Ed25519 is not the public half the office publishes"]
    return []


def c_no_token_in_any_answer() -> list[str]:
    """Neither screen is ever handed the link token, and no answer grows a private field."""
    joiner, host = offices()
    engine = pair_api.Pairing(joiner)
    claimer = pair_api.Pairing(host)
    offer = engine.offer("serve")
    claim = claimer.claim(offer["text"])
    read_back = claimer.claim_state(claim["rendezvous_id"])
    reply = engine.offer_reply(claim["reply_text"], offer["rendezvous_id"])
    leaked = []
    for where, answer in (("offer", offer), ("claim", claim), ("claim read-back", read_back),
                          ("reply", reply)):
        for name in _key_names(answer):
            if SECRET_NAME.search(name.rsplit(".", 1)[-1]):
                leaked.append(f"{where}: {name}")
    if leaked:
        return [f"an answer to a screen carries a secret-named field — {leaked}"]
    if host.vault or joiner.vault:
        return ["a vault was written before either operator confirmed"]
    return []


def c_nothing_is_written_before_both_confirm() -> list[str]:
    """The pairing exists only when two people have each confirmed on their own screen."""
    joiner, host = offices()
    engine = pair_api.Pairing(joiner)
    claimer = pair_api.Pairing(host)
    offer = engine.offer("serve")
    claimer.claim(offer["text"])
    if joiner.records or host.records or joiner.vault or host.vault:
        return ["an offer and a claim wrote a record or a token before anybody confirmed"]
    return []


def c_both_screens_show_the_same_code() -> list[str]:
    """The one check a person performs: six digits, identical on both screens, and who answered."""
    joiner, host = offices()
    engine = pair_api.Pairing(joiner)
    claimer = pair_api.Pairing(host)
    offer = engine.offer("serve")
    claim = claimer.claim(offer["text"])
    got = engine.offer_reply(claim["reply_text"], offer["rendezvous_id"])
    if got["code"] != claim["code"]:
        return ["the two screens show different digits — the only human check the pairing has"]
    if got["peer"]["office_id"] != "macbook":
        return ["the joiner is not told which office answered"]
    if not (len(claim["code"]) == 6 and claim["code"].isdigit()):
        return [f"the code is not six digits: {len(claim['code'])} characters"]
    return []


def c_a_wrong_code_writes_nothing() -> list[str]:
    """Six digits are a check, not a formality: a wrong one is refused on both sides."""
    joiner, host = offices()
    engine = pair_api.Pairing(joiner)
    claimer = pair_api.Pairing(host)
    offer = engine.offer("serve")
    claim = claimer.claim(offer["text"])
    engine.offer_reply(claim["reply_text"], offer["rendezvous_id"])
    wrong = "000000" if claim["code"] != "000000" else "111111"
    if not blocked(engine.offer_confirm, offer["rendezvous_id"], wrong):
        return ["a wrong code was accepted on the joiner's screen"]
    if not blocked(claimer.claim_confirm, claim["rendezvous_id"], wrong):
        return ["a wrong code was accepted on the host's screen"]
    if joiner.records or host.records or joiner.vault or host.vault:
        return ["a wrong code wrote a record or a token"]
    return []


def c_a_photograph_cannot_confirm() -> list[str]:
    """Holding the payload is not holding the secret: no confirmation before the reply was read."""
    joiner, host = offices()
    engine = pair_api.Pairing(joiner)
    claimer = pair_api.Pairing(host)
    offer = engine.offer("serve")
    claim = claimer.claim(offer["text"])
    if not blocked(engine.offer_confirm, offer["rendezvous_id"], claim["code"]):
        return ["the joiner confirmed a pair whose reply it never read — a photographed QR would do"]
    if joiner.records or host.records:
        return ["confirming before the reply was read wrote a record"]
    return []


def c_the_offer_is_answered_once() -> list[str]:
    """A pair is written once; the offer that made it is spent."""
    joiner, host = offices()
    engine = pair_api.Pairing(joiner)
    claimer = pair_api.Pairing(host)
    offer = engine.offer("serve")
    claim = claimer.claim(offer["text"])
    engine.offer_reply(claim["reply_text"], offer["rendezvous_id"])
    engine.offer_confirm(offer["rendezvous_id"], claim["code"])
    claimer.claim_confirm(claim["rendezvous_id"], claim["code"])
    if not (joiner.records.get("macbook") and host.records.get("hp-laptop")):
        return ["both confirmations did not write both records"]
    if engine.offer_state(offer["rendezvous_id"]).get("state") != "confirmed":
        return [f"a spent offer reads {engine.offer_state(offer['rendezvous_id']).get('state')!r}"]
    if not blocked(engine.offer_confirm, offer["rendezvous_id"], claim["code"]):
        return ["the same offer was confirmed twice"]
    if not blocked(claimer.claim_confirm, claim["rendezvous_id"], claim["code"]):
        return ["the same claim was confirmed twice"]
    return []


def c_an_old_offer_is_refused() -> list[str]:
    """§9's “single-use, **10-min offer**”, measured by MOVING THE CLOCK — nothing here waits.

    §9's row is one sentence with two numbers in it, and until now only the first was a test: single
    use is `c_the_offer_is_answered_once`, and the ten minutes were carried by the module's own
    `selftest()` and by `pairing.Offers` (test_link_security.py), never by the FLOW — the offer the
    console mints, the host that answers it, and the joiner that confirms it. The invite side already
    measures its own window this way (`test_one_off_invites.py`: `c_expired_admits_nobody`); this is
    the same move on the QR.

    FOUR DOORS read an offer, and every one of them must say no once `OFFER_TTL` has passed:
    the joiner's poll (`offer_state` — what its screen counts down), the joiner reading the host's
    reply (`offer_reply`), the joiner confirming (`offer_confirm` — the pair is written there), and
    the host reading an offer (`claim`). The last is the one that matters most: a photographed QR,
    replayed later, reaches the host's own door first, with no joiner involved at all.

    AND THE HONEST PATH IS MEASURED, one second before the deadline: the same clock that refuses at
    +5 s pairs at -1 s. Without that half a refusal would be indistinguishable from a pairing that
    is simply broken.
    """
    problems = []
    # (1) TEN MINUTES is the number §9 writes, and both sides count down from the offer's own field.
    if pairing.OFFER_TTL != 600:
        problems.append(f"§9's offer is ten minutes; the module says OFFER_TTL={pairing.OFFER_TTL}")

    # (2) INSIDE THE WINDOW — one second before `expires_at` — the flow still completes end to end.
    clock, engine, claimer, joiner, host = clocked()
    live = engine.offer("serve")
    window = live["offer"]["expires_at"] - live["offer"]["created_at"]
    if window != pairing.OFFER_TTL:
        problems.append(f"the offer carries a window of {window}s, not OFFER_TTL={pairing.OFFER_TTL}")
    clock[0] = float(live["offer"]["expires_at"]) - 1
    # reported as a problem rather than raised: a mutation that breaks the honest path must be CAUGHT
    # by this claim and name itself, not crash out of it
    try:
        answered = claimer.claim(live["text"])
        got = engine.offer_reply(answered["reply_text"], live["rendezvous_id"])
        engine.offer_confirm(live["rendezvous_id"], answered["code"])
        claimer.claim_confirm(answered["rendezvous_id"], got["code"])
    except PairError as e:
        problems.append(f"an offer one second INSIDE its ten minutes was refused: {e}")
    if not (joiner.records.get("macbook") and host.records.get("hp-laptop")):
        problems.append("an offer one second INSIDE its ten minutes did not pair the two offices — "
                        "the refusals below would then be measuring a broken flow, not a window")

    # (3) PAST THE WINDOW. Three offers are minted at t0 and two of them are answered — and one of
    # those two is also READ — inside the window, so what is refused below is an offer the host
    # really replied to and a code the joiner really holds: not a malformed text, and not a step that
    # was never reached. Then the clock moves ten minutes and five seconds: exactly the move
    # `pair_api.selftest` makes (`clock[0] += pairing.OFFER_TTL + 5`).
    clock2, engine2, claimer2, joiner2, host2 = clocked()
    t0 = clock2[0]
    late = engine2.offer("serve")
    late_reply = claimer2.claim(late["text"])                  # answered inside the window
    late2 = engine2.offer("serve")
    late2_reply = claimer2.claim(late2["text"])
    read2 = engine2.offer_reply(late2_reply["reply_text"], late2["rendezvous_id"])   # …and read
    late3 = engine2.offer("serve")                             # read only after the window
    if claimer2.claim_state(late2_reply["rendezvous_id"]).get("state") != "claimed" \
            or not engine2.offer_state(late2["rendezvous_id"]).get("code"):
        problems.append("the two offices were not mid-pairing when the clock moved — the refusals "
                        "below would then be about nothing")
    clock2[0] = t0 + pairing.OFFER_TTL + 5
    # the predicate both sides read: `pairing.is_expired`, the same function the invite door calls
    # (`join_api.py`: «ההצעה פגה — הלשכה המצטרפת שולחת חדשה»)
    if not pairing.is_expired(late["offer"], clock2[0]):
        problems.append("ten minutes past the offer, the module's own `is_expired` still calls it "
                        "live — the window is nobody's rule")

    # door 1: the joiner's screen. It must say `expired`, and say it before anything pops the row.
    shown = engine2.offer_state(late["rendezvous_id"]).get("state")
    if shown != "expired":
        problems.append(f"the joiner's screen shows an offer past its window as {shown!r}")

    # door 2: the joiner reading the host's reply — the step that turns a reply into a claim.
    said = refusal(engine2.offer_reply, late_reply["reply_text"], late["rendezvous_id"])
    if not said:
        problems.append("the host's reply was still read after the offer's window closed — a "
                        "photograph of the QR would then be worth a link, however long it sat")
    elif not EXPIRY_WORDS.search(said):
        problems.append(f"the reply was refused, but not for the window: {said!r}")

    # door 3: the joiner confirming a claim it already holds — the step that WRITES the pair.
    said = refusal(engine2.offer_confirm, late2["rendezvous_id"], read2["code"])
    if not said:
        problems.append("a confirmation was accepted for an offer past its window — the ten minutes "
                        "would then be a countdown on a screen and nothing else")
    elif not EXPIRY_WORDS.search(said):
        problems.append(f"the confirmation was refused, but not for the window: {said!r}")

    # door 4: the HOST reading an offer — the door a replayed photograph arrives at first.
    said = refusal(claimer2.claim, late3["text"])
    if not said:
        problems.append("the host answered an offer ten minutes and five seconds old — the QR is "
                        "then a standing invitation, not a ten-minute one")
    elif not EXPIRY_WORDS.search(said):
        problems.append(f"the host refused the old offer, but not for the window: {said!r}")

    # (4) AND NONE OF THE REFUSALS WROTE ANYTHING — no record, no token, on either side.
    if joiner2.records or host2.records or joiner2.vault or host2.vault:
        problems.append("an offer past its window wrote a record or a token")
    return problems


def c_an_offer_cannot_buy_a_longer_window() -> list[str]:
    """The ten minutes are THIS OFFICE's rule, not a number the offer carries for itself.

    §9's row — “single-use, 10-min offer” — is a promise about the office that ANSWERS an offer, and an
    offer arrives as untrusted text (a pasted code, a photographed QR). Its `expires_at` is the
    sender's own field, so a sender can declare a month; if the host reads that number as its window,
    `OFFER_TTL` is a default and not a limit.

    THE JOIN DOOR ALREADY REFUSES EXACTLY THIS (`join_api.Hub.join`: an offer that says it lives
    longer, or was made in the future, “is not one this code wrote” —
    «תוקף ההצעה אינו התוקף שהלשכה הזאת מקבלת»). The QR door does not, and it is the door a pasted
    code reaches first. Measured here, and recorded as a documented gap rather than as a pass — the
    marker is `KNOWN_GAPS`, and it becomes a FAILURE the day the gap closes without the marker being
    removed (the rule `test_link_security.py` follows).

    The control matters as much as the claim: the SAME bench answers the SAME offer minted with the
    window this code writes, so a refusal of the long-lived one is about its window and not about a
    bench that cannot pair at all.
    """
    joiner = pair_api._MemoryPorts("hp-laptop", "HP", slot=1)
    host = pair_api._MemoryPorts("macbook", "MacBook", slot=2,
                                 listen={"endpoint": "192.168.16.102", "port": 51830})
    claimer = pair_api.Pairing(host)
    identity = pair_api._public(joiner.home()["identity"])
    normal, _p = pairing.new_offer("hp-laptop", identity, [], ttl=pairing.OFFER_TTL)
    said = refusal(claimer.claim, pairing.offer_text(normal))
    if said:
        return [f"the bench cannot answer even a ten-minute offer ({said}) — this claim measures "
                f"nothing"]
    greedy, _q = pairing.new_offer("hp-laptop", identity, [], ttl=30 * 86400)
    said = refusal(claimer.claim, pairing.offer_text(greedy))
    if not said:
        return ["the host answered an offer that declares a THIRTY-DAY window: the ten minutes are "
                "then a number in the payload and not a rule of the office that answers, and the "
                "host's claim — the sealed reply and the token in its memory — lives as long as the "
                "sender says"]
    return []


def c_its_own_selftest_is_green() -> list[str]:
    """Everything else this module decides, run exactly as it is written."""
    return [f"the module's own selftest: {p}" for p in pair_api.selftest()]


CLAIMS = [
    ("qr.the-payload-is-what-a-scan-reads", c_the_payload_is_what_a_scan_reads),
    ("qr.carries-public-material-only", c_carries_public_material_only),
    ("qr.no-token-in-any-answer", c_no_token_in_any_answer),
    ("qr.nothing-is-written-before-both-confirm", c_nothing_is_written_before_both_confirm),
    ("qr.both-screens-show-the-same-code", c_both_screens_show_the_same_code),
    ("qr.a-wrong-code-writes-nothing", c_a_wrong_code_writes_nothing),
    ("qr.a-photograph-cannot-confirm", c_a_photograph_cannot_confirm),
    ("qr.the-offer-is-answered-once", c_the_offer_is_answered_once),
    ("qr.an-old-offer-is-refused", c_an_old_offer_is_refused),
    ("qr.an-offer-cannot-buy-a-longer-window", c_an_offer_cannot_buy_a_longer_window),
    ("qr.its-own-selftest-is-green", c_its_own_selftest_is_green),
]

#: The claims whose code path is MISSING today — the claim → what is not written yet. A claim here is
#: measured and reported as XFAIL instead of failing the file — the gap stays visible, in the suite a
#: gate runs, rather than in a sentence somebody wrote once. And the marker is not a place to leave a
#: pass: a KNOWN_GAP claim that starts holding is an XPASS, which FAILS this file until the marker is
#: removed (the rule `test_link_security.py` follows since it was written).
KNOWN_GAPS = {
    "qr.an-offer-cannot-buy-a-longer-window":
        "pair_api.Pairing.claim compares the offer's `expires_at` to now and never caps it against "
        "pairing.OFFER_TTL — the rule the join door applies (`join_api.Hub.join`: «תוקף ההצעה אינו "
        "התוקף שהלשכה הזאת מקבלת»). The QR host therefore answers an offer that declares any window "
        "the sender likes, and keeps it — sealed reply and token — in memory that long.",
}

#: (the regression, the claim that must catch it) — each one is written into the module IN MEMORY.
INJECTIONS = [
    ("the payload the QR is made of carries a private value", "qr.carries-public-material-only"),
    ("the host's answer carries the link token", "qr.no-token-in-any-answer"),
    ("the offer the screen shows is good for a day", "qr.an-old-offer-is-refused"),
    ("the window is not enforced where an offer is read", "qr.an-old-offer-is-refused"),
]


def _inject_regression(what: str) -> list[tuple[str, object]]:
    if what == "the payload the QR is made of carries a private value":
        original = pair_api.Pairing.offer

        def leaky(self, direction="", label=""):
            out = original(self, direction, label)
            offer = dict(out["offer"], wg_private="LEAK-NOT-A-PUBLIC-FACT")   # …and the QR follows it
            return dict(out, offer=offer, text=pairing.offer_text(offer))
        pair_api.Pairing.offer = leaky
        return [("Pairing.offer", original)]
    if what == "the host's answer carries the link token":
        original_claim = pair_api.Pairing.claim

        def leaky_claim(self, *a, **k):
            return dict(original_claim(self, *a, **k), token="LEAK-NOT-A-TOKEN")
        pair_api.Pairing.claim = leaky_claim
        return [("Pairing.claim", original_claim)]
    if what == "the offer the screen shows is good for a day":
        original_offer = pair_api.Pairing.offer

        def long_lived(self, direction="", label=""):
            out = original_offer(self, direction, label)
            offer = dict(out["offer"], expires_at=int(out["offer"]["created_at"]) + 86400)
            return dict(out, offer=offer, text=pairing.offer_text(offer), expires_at=offer["expires_at"])
        pair_api.Pairing.offer = long_lived
        return [("Pairing.offer", original_offer)]
    if what == "the window is not enforced where an offer is read":
        # the ONE predicate `pairing.accept` / `pairing.open_reply` / `pair_api.Pairing.claim` all
        # read; the store's own comparisons (`pairing.Offers`) are left alone on purpose, so this
        # measures the door rather than the countdown.
        original_expired = pairing.is_expired
        pairing.is_expired = lambda offer, now=None: False
        return [("pairing.is_expired", original_expired)]
    raise SystemExit(f"unknown injection: {what}")


def main(argv: list[str]) -> int:
    inject = "--inject" in argv
    failed: list[str] = []
    gaps: list[tuple[str, str]] = []
    for name, claim in CLAIMS:
        try:
            problems = claim()
        except Exception as e:                                # a claim that cannot be measured is not a pass
            problems = [f"raised {type(e).__name__}: {e}"]
        if problems and name in KNOWN_GAPS:
            gaps.append((name, problems[0]))
            print(f"XFAIL {name}")
            print(f"     {problems[0]}")
        elif problems:
            failed.append(name)
            print(f"FAIL {name}")
            for p in problems:
                print(f"     {p}")
        elif name in KNOWN_GAPS:
            # The gap was closed and the marker stayed: that is a FAILURE, not a pass — a marker
            # nobody removes is how a claim that now holds goes back to being documentation.
            failed.append(name)
            print(f"XPASS {name}")
            print(f"     the gap is closed now — remove it from KNOWN_GAPS (was: {KNOWN_GAPS[name]})")
        else:
            print(f"PASS {name}")
    # THE SUMMARY IS THE LAST LINE: a gate that runs this file prints it as the one-line report
    # (`plane-tests-lint`), so it carries the verdict AND what is still open.
    print(f"the pairing QR: {'PASS' if not failed else 'FAIL'} "
          f"({len(CLAIMS) - len(failed) - len(gaps)}/{len(CLAIMS)} claims held"
          + (f", {len(gaps)} documented gap(s) still open" if gaps else "") + ")")
    if failed:
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
                setattr(getattr(pair_api, name.split(".")[0]), name.split(".")[1], old)
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
