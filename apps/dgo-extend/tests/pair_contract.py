#!/usr/bin/env python3
"""pair_contract — the pairing codes, run through BOTH languages (the check that did not exist).

`pairing.py` (the server) and `static/connect.js` (the screen) each had a passing selftest and spoke
two different formats (`DGOPAIR1:` with offer_id/office/identity vs `dgo1:` with office_id/…): two
green tests, and a pairing that could never start. So this file is not another unit test of either
side — it hands one side's OUTPUT to the other side's READER:

  · an offer the server mints is parsed by the page's own `parseOffer`, and every field the screen
    shows is compared with what the server wrote;
  · the text the page would encode is read back by the server's `parse_offer`;
  · the grouped display form (six groups, any spacing) survives the round trip in both directions;
  · a reply is routed by prefix on both sides and refused as an offer on both sides;
  · then the engine itself: two in-memory offices pair end to end (`pair_api.selftest`), and the
    record validator's refusals hold (`declaration.selftest_paired`).

    python3 apps/dgo-extend/tests/pair_contract.py        # non-zero exit on the first broken promise

Needs `node` and `openssl` — both are on every machine the gate runs on.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "apps/dgo-extend"
sys.path.insert(0, str(APP))

import catalog      # noqa: E402
import declaration  # noqa: E402
import pair_api     # noqa: E402
import pairing      # noqa: E402

NODE = r"""
const C = require(process.argv[1]);
const input = JSON.parse(require("fs").readFileSync(0, "utf8"));
const out = {};
const o = C.parseOffer(input.offer_text);
const { wire, ...view } = o;
out.view = view;
// compared key-order-free: the server writes its JSON with sorted keys, and order is not content
const canon = (v) => Array.isArray(v) ? v.map(canon)
  : (v && typeof v === "object") ? Object.keys(v).sort().reduce((o, k) => (o[k] = canon(v[k]), o), {}) : v;
out.wire_equal = JSON.stringify(canon(wire)) === JSON.stringify(canon(input.offer));
out.grouped = C.groupText(input.offer_text);
out.grouped_view_equal = JSON.stringify((({ wire, ...v }) => v)(C.parseOffer(out.grouped))) === JSON.stringify(view);
out.reencoded = C.encodeOffer(input.offer);
out.kinds = [C.kindOf(input.offer_text), C.kindOf(out.grouped), C.kindOf(input.reply_text),
             C.kindOf(C.groupText(input.reply_text)), C.kindOf("nothing")];
try { C.parseOffer(input.reply_text); out.reply_as_offer = "accepted"; }
catch (e) { out.reply_as_offer = "refused"; }
out.prefixes = [C.OFFER_PREFIX, C.REPLY_PREFIX];
out.expired = C.offerExpired(o, input.offer.expires_at + 1);
process.stdout.write(JSON.stringify(out));
"""


def main() -> int:
    problems: list[str] = []
    node = shutil.which("node")
    if not node:
        print("FAIL  node is not installed — the cross-language half cannot run")
        return 1

    import base64
    priv, pub = pairing._ed25519_keypair()
    joiner_identity = {"ed25519": "r1QoNoPc9DH0vFFq2GMHhASMM9oBJQQcMCxSMjxB6Pk=",
                       "wg": "OUBWvxLVZJDWW19J9sZPePVPi3i1rickvdqcXagbbns=",
                       "fingerprint": "3A4B-3343-4492-5A1A"}
    host_identity = {"ed25519": base64.b64encode(pub[-32:]).decode(), "wg": "W" * 43 + "=",
                     "fingerprint": "75FF-E977-0881-0625"}
    offer, eph = pairing.new_offer(
        "hp-laptop", joiner_identity, ["192.168.16.102:51830"],
        extra={"label": "הלפטופ של הבית", "used_slots": [1], "direction": "serve",
               "listen": {"endpoint": "192.168.16.102", "port": 51830}})
    offer_text = pairing.offer_text(offer)
    reply = pairing.accept(offer, "macbook", priv, host_identity, token="t" * 64, direction="use",
                           tunnel={"slot": 3, "dial": "host", "endpoint": "192.168.16.102", "port": 51830},
                           extra={"label": "MacBook"})
    reply_text = pairing.reply_text(reply)

    got = subprocess.run([node, "-e", NODE, str(APP / "static/connect.js")],
                         input=json.dumps({"offer": offer, "offer_text": offer_text,
                                           "reply_text": reply_text}, ensure_ascii=False),
                         capture_output=True, text=True, encoding="utf-8", timeout=60)
    if got.returncode != 0:
        print("FAIL  the page could not read what the server minted:", got.stderr.strip()[-600:])
        return 1
    js = json.loads(got.stdout)

    want = {"office_id": offer["office"], "label": offer["label"],
            "identity_pubkey": offer["identity"]["ed25519"],
            "fingerprint": offer["identity"]["fingerprint"], "ephemeral_pubkey": offer["ephemeral"],
            "endpoints": offer["endpoints"], "rendezvous_id": offer["offer_id"],
            "expires_at": offer["expires_at"], "direction": "serve"}
    if js["view"] != want:
        problems.append(f"the page shows something else than the server wrote: {js['view']} != {want}")
    if not js["wire_equal"]:
        problems.append("the page must keep the server's offer object untouched (a Hebrew label included)")
    if not js["grouped_view_equal"]:
        problems.append("the six-group display form must parse to the same offer on the page")
    if js["prefixes"] != [pairing.PREFIX, pairing.REPLY_PREFIX]:
        problems.append(f"the two sides disagree about the prefixes: {js['prefixes']}")
    if js["kinds"] != ["offer", "offer", "reply", "reply", ""]:
        problems.append(f"the page must route a code by its prefix: {js['kinds']}")
    if js["reply_as_offer"] != "refused":
        problems.append("the page must refuse a reply where an offer is expected")
    if js["expired"] is not True:
        problems.append("an offer past its expiry is expired on the page as well")

    # the other direction: what the page shows / encodes is read by the SERVER's reader
    for name, text in (("the grouped form", js["grouped"]), ("the page's own encoding", js["reencoded"])):
        try:
            if pairing.parse_offer(text) != offer:
                problems.append(f"the server reads {name} as a different offer")
        except pairing.PairingError as e:
            problems.append(f"the server refuses {name}: {e}")
    grouped_reply = " ".join(reply_text[i:i + 37] for i in range(0, len(reply_text), 37))
    try:
        grant, code = pairing.open_reply(offer, eph, pairing.parse_reply(grouped_reply))
        if grant.get("token") != "t" * 64 or code != reply["host_sas"]:
            problems.append("a reply carried as grouped text must open to the same grant and code")
    except pairing.PairingError as e:
        problems.append(f"a reply carried as grouped text does not open: {e}")
    if len(reply_text) > 1500:
        problems.append(f"the reply is {len(reply_text)} characters — too dense a QR to read off a screen")

    problems += [f"pairing.py: {x}" for x in pairing.selftest()]
    problems += [f"declaration.py: {x}" for x in declaration.selftest_paired()]
    problems += [f"pair_api.py: {x}" for x in pair_api.selftest()]

    # §9 (sec-010) — the trust boundary of a PAIRED office: what a peer may READ and DO over the link.
    # Three facts, each guarded where it lives: the record grants no machine — nothing may SSH to a
    # peer (declaration.selftest_paired, above); the control door serves only the catalog
    # (tests/phase3.py c_link_listener); and the APP door reaches only the SERVED apps — the
    # serving-side decision asserted HERE, because it is what let a paired office read the other's
    # /api/instances (2026-10-04): the pair served `{"*": {}}`, and `*` is "my other office" — it
    # publishes the OPERATING apps too (app-management, computers, connections/the vault). A serve
    # that NAMES apps gives only those, never the control/vault/machine plane. (ai/context/
    # dgo-pairing-contract.md §E.)
    ops = {"apps": [{"app": "app-management", "alias": "apps", "port": 8010},
                    {"app": "computers", "alias": "computers", "port": 8020},
                    {"app": "connections", "alias": "connections", "port": 8030},
                    {"app": "drive", "alias": "drive", "port": 8975}]}
    star = {r["app"] for r in catalog.publishable(ops, {"*": {}})["apps"]}
    if not {"app-management", "computers", "connections"} <= star:
        problems.append(f"§9 paired boundary: serve `*` must publish the operating apps "
                        f"(vault + machine plane) — the owner's 'my other office', got {sorted(star)}")
    narrow = {r["app"] for r in catalog.publishable(ops, {"drive": {"port": 8975}})["apps"]}
    if narrow != {"drive"}:
        problems.append(f"§9 paired boundary: a serve that NAMES apps gives only those, never the "
                        f"vault/machine plane, got {sorted(narrow)}")

    for line in problems:
        print("FAIL ", line)
    print(f"pair_contract: {'PASS' if not problems else str(len(problems)) + ' problem(s)'}"
          f"  (offer {len(offer_text)} chars, reply {len(reply_text)} chars)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
