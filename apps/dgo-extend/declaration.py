"""dgo-extend.declaration — the rules a declaration must satisfy, as pure functions.

Kept out of app.py for one reason: a rule that can only be exercised by importing the web stack is a
rule the gate cannot measure (app.py needs `requests`, so `import app` fails outside a container, and
the schema checks silently become "not run"). Nothing here imports anything but the standard library.

The link plane is the part that earns its refusals. A wrong slot means two offices whose packets
arrive at the wrong interface; a wrong direction means a link that carries traffic the other end
never agreed to; a `serve:` entry without a port opens a firewall rule for nothing. Each refusal is a
sentence in Hebrew that names the field and what to write instead.
"""
from __future__ import annotations

import re

#: Every rule in this module ends in `\Z`, never `$`: Python's `$` also matches just BEFORE a trailing
#: newline, so `^…$` accepted "macbook\n" (DGO-615). The callers here strip first; a rule that holds
#: only because its caller stripped is one new caller away from letting the line break through.
ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}\Z")
ENDPOINT_RE = re.compile(r"^[a-z0-9.\-]+(:\d+)?\Z")
#: An installed office's DOMAIN (`app.py`'s `validate`): DNS labels and a TLD, 4–200 characters. Kept
#: here, beside the other rules of a declaration, so the gate can ask it without the web stack.
DOMAIN_RE = re.compile(r"^(?=.{4,200}\Z)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}\Z")
#: A PUBLIC KEY as it travels (`identity.public()`'s `ed25519` and `wg`): base64 of the raw 32-byte key, 44
#: characters, canonical — the character before `=` carries no stray bits. Exactly what `wg` itself accepts
#: (`key_from_base64`). The key is written into the tunnel's file as a LINE, so the old "at least 32
#: characters" let a pairing grant add lines of its own — measured 2026-10-15: an AllowedIPs line, and a
#: PreUp hook that wg-quick ran as root in dgo-net (DGO-626).
KEY_RE = re.compile(r"^[A-Za-z0-9+/]{42}[AEIMQUYcgkosw048]=\Z")
#: A HERD's name (DGO-1003): the company a set of offices belongs to — «Bina Solutions», «WBC», «The
#: Fireplace Guys». A name a person reads, so any script; one line of 1–60 characters, nothing that is
#: not printable (it is drawn on another office's screen and written into its record): no control
#: character of either range, no line or paragraph separator (YAML folds them on reload), and no
#: invisible or direction-changing mark — a peer could otherwise show a heading that looks like
#: another herd's name (the second reader of DGO-1003).
HERD_RE = re.compile("^[^\x00-\x1f\x7f-\x9f​-‏ -‮⁦-⁩﻿]{1,60}\\Z")


def clean_herd(value) -> tuple[str, str | None]:
    """A herd name as it is stored: trimmed, or "" for none — and the refusal when it is not a name.

    An office says its own herd (`DGO_HERD`, published with its catalog); an office's record of a
    PEER may carry a herd mark of its own — the owner's word for an office whose code publishes none
    (WBC's, 2026-10-22: «mark the connection as an external herd»).
    """
    if not isinstance(value, str):
        # a peer's catalog is a stranger's JSON: a list or a map is no name, and is not made one
        return "", (None if value in (None, "") else "שם העדר הוא טקסט")
    text = value.strip()
    if not text:
        return "", None
    if not HERD_RE.match(text):
        return "", "שם העדר: שורה אחת של 1–60 תווים"
    return text, None


def apply_link_plane(body: dict, d: dict) -> tuple[dict, str | None]:
    """Apply `identity`, `tunnel`, `links` and `serve` from a request body onto a declaration.

    Returns (declaration, error-or-None). Callers pass the merged dict through and stop on error, so
    a half-valid declaration is never written.
    """
    if "identity" in body:
        i = body.get("identity") or {}
        for k in ("ed25519", "wg"):
            v = (i.get(k) or "")
            if v and (not isinstance(v, str) or not KEY_RE.match(v)):
                return d, f"identity.{k} חייב להיות המפתח הציבורי (base64 של 32 בתים, 44 תווים), לא משהו אחר"
        d["identity"] = {"ed25519": i.get("ed25519") or "", "wg": i.get("wg") or "",
                         "fingerprint": i.get("fingerprint") or ""}
    if "tunnel" in body:
        t = body.get("tunnel") or {}
        try:
            slot = int(t.get("slot"))
        except (TypeError, ValueError):
            return d, "tunnel.slot חייב להיות מספר 1–254 (ה-/24 של הזוג הזה)"
        if not 1 <= slot <= 254:
            return d, "tunnel.slot חייב להיות בין 1 ל-254"
        dial = (t.get("dial") or "home").strip()
        if dial not in ("home", "peer"):
            return d, "tunnel.dial הוא home (הלשכה הזו מחייגת) או peer (הצד השני מחייג)"
        ep = (t.get("endpoint") or "").strip()
        if ep and not ENDPOINT_RE.match(ep):
            return d, "tunnel.endpoint חייב להיות host או host:port של הצד שמאזין"
        relay = t.get("relay_for") or []
        if not isinstance(relay, list):
            return d, "tunnel.relay_for חייב להיות רשימת לשכות (ריק להשבה)"
        d["tunnel"] = {"slot": slot, "endpoint": ep, "dial": dial,
                       "relay_for": [str(x) for x in relay]}
    if "links" in body:
        links = body.get("links") or []
        if not isinstance(links, list):
            return d, "links חייב להיות רשימה"
        out = []
        for link in links:
            if not isinstance(link, dict):
                return d, "כל link חייב להיות אובייקט עם office ו-direction"
            oid = str(link.get("office") or "").strip().lower()
            if not ID_RE.match(oid):
                return d, f"link.office {link.get('office')!r} אינו מזהה לשכה תקין"
            direction = (link.get("direction") or "use").strip()
            if direction not in ("use", "serve", "both"):
                return d, ("link.direction הוא use (הלשכה הזו משתמשת באפליקציות של האחרת), "
                           "serve (האחרת משתמשת בשלנו) או both (שניהם — קישור דו-כיווני)")
            out.append({"office": oid, "direction": direction,
                        "token_ref": (link.get("token_ref") or "").strip() or None})
        seen = [link["office"] for link in out]
        if len(set(seen)) != len(seen):
            return d, "אותו link מוצהר פעמיים"
        d["links"] = out
    if "serve" in body:
        srv = body.get("serve") or {}
        if not isinstance(srv, dict):
            return d, "serve חייב להיות מפה של אפליקציה → {port}"
        clean = {}
        for app_id, spec in srv.items():
            if not re.match(r"^[a-z0-9-]+\Z", app_id):    # DGO-615: `\Z` like every rule here — `$` passed "bina-ds\n"
                return d, f"serve.{app_id!r} אינו מזהה אפליקציה תקין"
            port = (spec or {}).get("port") if isinstance(spec, dict) else spec
            try:
                port = int(port)
            except (TypeError, ValueError):
                return d, (f"serve.{app_id} חייב לשאת port — הפורט שהאפליקציה מאזינה עליו "
                           f"ברשת של הלשכה שמגישה אותה")
            if not 1 <= port <= 65535:
                return d, f"serve.{app_id}.port מחוץ לטווח"
            clean[app_id] = {"port": port}
        d["serve"] = clean
    return d, None


# ── a PAIRED peer: an office that linked itself to this one from its own screen (kind: paired) ─────
# The record is written from a GRANT, and a grant is input that arrived through a camera or a paste
# box. So this validator is the only writer's gate: `validate()` in app.py is for offices this office
# INSTALLS (they have a machine, a domain and a source), and a paired record has none of those — it
# would be refused there for the wrong reasons, or worse, accepted by a path that never looked.
PAIRED = "paired"
ROLES = ("host", "joiner")
DIALS = ("host", "joiner", "relay")
PAIR_ID_RE = re.compile(r"^[0-9a-f]{16,64}\Z")
HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9.\-]{0,251}[a-z0-9])?\Z")


def is_paired(doc: dict | None) -> bool:
    return (doc or {}).get("kind") == PAIRED


def validate_paired(doc: dict, home_id: str, taken_slots=()) -> tuple[dict | None, str | None]:
    """A paired peer's record, checked field by field. Returns (clean record, None) or (None, why).

    `home_id` is THIS office's id and `taken_slots` the pair slots other records already hold here
    (never including the record being replaced). The clean record carries exactly the contract's
    fields — an unknown key in a grant is dropped, not stored.
    """
    oid = str((doc or {}).get("id") or "").strip().lower()
    if not ID_RE.match(oid):
        return None, f"מזהה הלשכה המצומדת {doc.get('id')!r} אינו תקין (אותיות לטיניות קטנות, ספרות ומקף)"
    if oid == home_id:
        return None, f"לשכה אינה מצטמדת לעצמה ({home_id})"
    pair_id = str(doc.get("pair_id") or "")
    if not PAIR_ID_RE.match(pair_id):
        return None, "pair_id חסר או אינו מזהה הצעה (hex) — בלעדיו צימוד חוזר אינו אידמפוטנטי"
    ident = doc.get("identity") or {}
    for key in ("ed25519", "wg"):
        value = ident.get(key)
        if not isinstance(value, str) or not KEY_RE.match(value):
            return None, (f"identity.{key} של {oid} חסר או אינו מפתח ציבורי (base64 של 32 בתים, 44 תווים) — "
                          "בלי המפתח הציבורי אין מנהרה ואין זהות")
    t = doc.get("tunnel") or {}
    try:
        slot = int(t.get("slot"))
    except (TypeError, ValueError):
        return None, "tunnel.slot חייב להיות מספר 1–254 (ה-/24 של הזוג)"
    if not 1 <= slot <= 254:
        return None, "tunnel.slot חייב להיות בין 1 ל-254"
    if slot in {int(x) for x in taken_slots}:
        return None, f"ה-slot {slot} כבר תפוס בזוג אחר בלשכה הזאת — הצימוד לא נכתב"
    role = str(t.get("role") or "")
    if role not in ROLES:
        return None, "tunnel.role הוא host (הלשכה הזאת סרקה) או joiner (הלשכה הזאת הציגה את ההצעה)"
    try:
        side = int(t.get("side"))
    except (TypeError, ValueError):
        return None, "tunnel.side חייב להיות 1 או 2"
    if side != (1 if role == "host" else 2):
        return None, "tunnel.side אינו תואם את התפקיד: המארחת היא צד 1, המצטרפת צד 2"
    dial = str(t.get("dial") or "")
    if dial not in DIALS:
        return None, "tunnel.dial הוא host, joiner או relay — מי שמחייג"
    endpoint = str(t.get("endpoint") or "").strip().lower()
    port = t.get("port")
    if dial == "relay":
        endpoint, port = "", None
    else:
        # ONE fact, written on both ends: the address of the side that LISTENS. The dialing office
        # reads it to dial; the listening office reads the port to know what it promised to answer on.
        if not HOST_RE.match(endpoint):
            return None, "tunnel.endpoint חייב להיות שם מארח או כתובת של הצד שמאזין (בלי סכימה ובלי פורט)"
        try:
            port = int(port)
        except (TypeError, ValueError):
            return None, "tunnel.port חייב להיות הפורט (UDP) שהצד המאזין פרסם"
        if not 1 <= port <= 65535:
            return None, "tunnel.port מחוץ לטווח 1–65535"
    # HOW the pair's datagrams travel — a fact of the pair both records carry: WireGuard's own UDP, or
    # the carriers' TCP path (`tcp`); and, for a pair that rides an office's HTTPS door (a JOIN —
    # join_api.py), the door's URL, which the dialing side's carrier connects to.
    transport = str(t.get("transport") or "udp").strip().lower()
    if transport not in ("udp", "tcp"):
        return None, "tunnel.transport הוא udp או tcp"
    door = str(t.get("door") or "").strip()
    if door:
        from net import DOOR_URL_RE                        # one rule for what a door URL is
        if transport != "tcp":
            return None, "זוג שעובר בדלת HTTPS (tunnel.door) נוסע בנתיב TCP (tunnel.transport: tcp)"
        if not DOOR_URL_RE.match(door):
            return None, "tunnel.door הוא wss://<host>/carry — כתובת הדלת של הלשכה, בלי שום דבר אחר"
    links = doc.get("links") or []
    if not (isinstance(links, list) and len(links) == 1 and isinstance(links[0], dict)):
        return None, "לרשומה מצומדת יש קישור אחד בדיוק — אל הלשכה הזאת"
    if str(links[0].get("office") or "") != home_id:
        return None, f"הקישור של {oid} חייב להצביע על הלשכה הזאת ({home_id})"
    direction = str(links[0].get("direction") or "")
    if direction not in ("use", "serve", "both"):
        return None, "link.direction הוא use, serve או both"
    label = str(doc.get("label") or oid).strip()[:60] or oid
    clean = {"id": oid, "label": label, "kind": PAIRED, "pair_id": pair_id,
             "identity": {"ed25519": ident["ed25519"], "wg": ident["wg"],
                          "fingerprint": str(ident.get("fingerprint") or "")},
             # `listen_port` is DERIVED, never read from the grant: it is THIS office's own UDP port in
             # the pair, and it exists only on the side that listens (dial names the OTHER role). The
             # dialing side has none — its source port is its own business (DGO_WG_PORT).
             "tunnel": {"slot": slot, "side": side, "role": role, "dial": dial,
                        "endpoint": endpoint, "port": port,
                        "listen_port": port if dial in ROLES and dial != role else None,
                        **({"transport": "tcp"} if transport == "tcp" else {}),
                        **({"door": door} if door else {})},
             "links": [{"office": home_id, "direction": direction}],
             "paired_at": int(doc.get("paired_at") or 0)}
    herd, err = clean_herd(doc.get("herd"))
    if err:
        return None, err
    if herd:
        clean["herd"] = herd
    return clean, None


def selftest_paired() -> list[str]:
    problems = []
    key = "A" * 43 + "="
    good = {"id": "hp-laptop", "label": "HP", "kind": PAIRED, "pair_id": "ab" * 16,
            "identity": {"ed25519": key, "wg": key, "fingerprint": "AAAA-BBBB"},
            "tunnel": {"slot": 3, "side": 1, "role": "host", "dial": "host",
                       "endpoint": "192.168.16.102", "port": 51830},
            "links": [{"office": "macbook", "direction": "use"}], "paired_at": 1,
            "machine": "computer_ssh-x", "token": "must-not-be-stored"}
    clean, err = validate_paired(good, "macbook", taken_slots=[2])
    if err or not clean:
        return [f"a well-formed paired record must be accepted: {err}"]
    if clean["tunnel"]["listen_port"] is not None:
        problems.append("the side that DIALS (dial == role) has no listen_port of its own in the pair")
    listener, err = validate_paired(dict(good, tunnel=dict(good["tunnel"], side=2, role="joiner")), "macbook")
    if err or listener["tunnel"]["listen_port"] != 51830:
        problems.append("the side that is dialed (dial != role) listens on the pair's published port")
    if "machine" in clean or "token" in clean:
        problems.append("a paired record stores the contract's fields only — never a machine or a token")
    door = "wss://link.example.org/carry"
    joined, err = validate_paired(dict(good, tunnel=dict(good["tunnel"], transport="tcp", door=door)), "macbook")
    if err or joined["tunnel"].get("door") != door or joined["tunnel"].get("transport") != "tcp":
        problems.append(f"a joined pair keeps the door it rides and its TCP path: {err}")
    for why, tun in (("a door on the UDP path", dict(good["tunnel"], door=door)),
                     ("a door that is not wss://host/carry",
                      dict(good["tunnel"], transport="tcp", door="https://link.example.org/carry")),
                     ("a door URL with a line of its own",
                      dict(good["tunnel"], transport="tcp", door=door + "\nx")),
                     ("a transport that is neither", dict(good["tunnel"], transport="quic"))):
        if validate_paired(dict(good, tunnel=tun), "macbook")[1] is None:
            problems.append(f"{why} must be refused")
    cases = [
        ("the office itself", dict(good, id="macbook")),
        ("no pair_id", dict(good, pair_id="")),
        ("no WireGuard key", dict(good, identity={"ed25519": key, "wg": ""})),
        # a key is written into the tunnel's file as a LINE (DGO-626): one that carries a line of its own is
        # refused, and so is anything `wg` itself would refuse — the canonical 44 characters only
        ("a WireGuard key that carries a line of its own",
         dict(good, identity={"ed25519": key, "wg": key + "\nAllowedIPs = 0.0.0.0/0, ::/0"})),
        ("an Ed25519 key that is not a key", dict(good, identity={"ed25519": "x" * 44, "wg": key})),
        ("a key with stray bits before its `=`", dict(good, identity={"ed25519": key, "wg": "W" * 43 + "="})),
        ("a slot another pair holds", dict(good, tunnel=dict(good["tunnel"], slot=2))),
        ("a side that contradicts the role", dict(good, tunnel=dict(good["tunnel"], side=2))),
        ("an endpoint with a scheme", dict(good, tunnel=dict(good["tunnel"], endpoint="http://x"))),
        ("an endpoint that carries a port", dict(good, tunnel=dict(good["tunnel"], endpoint="h:1"))),
        ("a port out of range", dict(good, tunnel=dict(good["tunnel"], port=70000))),
        ("a link to another office", dict(good, links=[{"office": "vps1", "direction": "use"}])),
        ("an unknown direction", dict(good, links=[{"office": "macbook", "direction": "all"}])),
        # the one field read WITHOUT a strip: `$` matched before the line break and stored it (DGO-615)
        ("a pair_id that ends in a line break", dict(good, pair_id="ab" * 16 + "\n")),
    ]
    for name, doc in cases:
        got, why = validate_paired(doc, "macbook", taken_slots=[2])
        if got is not None or not why:
            problems.append(f"validate_paired must refuse {name}")
    relay, err = validate_paired(dict(good, tunnel=dict(good["tunnel"], dial="relay", endpoint="", port=None)),
                                 "macbook")
    if err or relay["tunnel"]["endpoint"] or relay["tunnel"]["port"] is not None:
        problems.append("a relayed pair names no endpoint of its own")
    if not is_paired(clean) or is_paired({"id": "vps1", "machine": "m"}):
        problems.append("is_paired is the record's own `kind`, nothing inferred")
    # A HERD mark (DGO-1003) is kept, trimmed; none is stored as none; a second line is refused.
    marked, err = validate_paired(dict(good, herd="  WBC "), "macbook")
    if err or (marked or {}).get("herd") != "WBC":
        problems.append(f"a paired record keeps the herd it is marked with, trimmed: {err}")
    if "herd" in clean:
        problems.append("a record marked with no herd stores none")
    if validate_paired(dict(good, herd="WBC\nAllowedIPs = 0.0.0.0/0"), "macbook")[1] is None:
        problems.append("a herd name with a line of its own must be refused")
    if clean_herd("x" * 61)[1] is None or clean_herd("The Fireplace Guys") != ("The Fireplace Guys", None):
        problems.append("a herd name is one line of 1–60 characters")
    return problems


def selftest_rules() -> list[str]:
    """Every rule of this module refuses a value that ENDS in a line break (DGO-615).

    Asked of the rule itself, not through its callers: they strip before they ask, which is exactly
    why a rule that let the line break through went unnoticed — and app.py's `validate` (which uses
    ID_RE and DOMAIN_RE) is only reachable with the web stack."""
    problems = []
    for name, rule, value in (("ID_RE", ID_RE, "macbook"),
                              ("ENDPOINT_RE", ENDPOINT_RE, "vps.example.org:51820"),
                              ("DOMAIN_RE", DOMAIN_RE, "office2.example.co.il"),
                              ("PAIR_ID_RE", PAIR_ID_RE, "ab" * 16),
                              ("HOST_RE", HOST_RE, "192.168.16.102"),
                              ("KEY_RE", KEY_RE, "A" * 43 + "=")):
        broken = value + "\n"
        if not rule.match(value):
            problems.append(f"{name} must accept {value!r}")
        if rule.match(broken):
            problems.append(f"{name} must refuse {broken!r}: a value that ends in a line break is not one")
    # …and the module's one inline rule: a declared office's `serve` key (DGO-615)
    for key, refused in (("bina-ds", False), ("bina-ds\n", True)):
        _d, err = apply_link_plane({"serve": {key: {"port": 3080}}}, {})
        if bool(err) != refused:
            problems.append(f"serve key {key!r} must be {'refused' if refused else 'kept'}, got {err!r}")
    # …and a declared office's own identity keys, which reach the tunnel's file as a line (DGO-626)
    for value, refused in (("A" * 43 + "=", False), ("A" * 43 + "=\nAllowedIPs = 0.0.0.0/0, ::/0", True),
                           ("W" * 43 + "=", True), ("short", True)):
        _d, err = apply_link_plane({"identity": {"wg": value}}, {})
        if bool(err) != refused:
            problems.append(f"identity.wg {value!r} must be {'refused' if refused else 'kept'}, got {err!r}")
    return problems


if __name__ == "__main__":
    bad = selftest_paired() + selftest_rules()
    for b in bad:
        print("FAIL", b)
    print("declaration.py selftest:", "PASS" if not bad else f"{len(bad)} problem(s)")
    raise SystemExit(1 if bad else 0)
