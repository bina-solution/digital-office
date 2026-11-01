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

ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
ENDPOINT_RE = re.compile(r"^[a-z0-9.\-]+(:\d+)?$")


def apply_link_plane(body: dict, d: dict) -> tuple[dict, str | None]:
    """Apply `identity`, `tunnel`, `links` and `serve` from a request body onto a declaration.

    Returns (declaration, error-or-None). Callers pass the merged dict through and stop on error, so
    a half-valid declaration is never written.
    """
    if "identity" in body:
        i = body.get("identity") or {}
        for k in ("ed25519", "wg"):
            v = (i.get(k) or "")
            if v and (not isinstance(v, str) or len(v) < 32):
                return d, f"identity.{k} חייב להיות המפתח הציבורי (base64), לא משהו אחר"
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
            if not re.match(r"^[a-z0-9-]+$", app_id):
                return d, f"serve.{app_id} אינו מזהה אפליקציה תקין"
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
PAIR_ID_RE = re.compile(r"^[0-9a-f]{16,64}$")
HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9.\-]{0,251}[a-z0-9])?$")


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
        if not isinstance(value, str) or len(value) < 32:
            return None, f"identity.{key} של {oid} חסר — בלי המפתח הציבורי אין מנהרה ואין זהות"
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
                        "listen_port": port if dial in ROLES and dial != role else None},
             "links": [{"office": home_id, "direction": direction}],
             "paired_at": int(doc.get("paired_at") or 0)}
    return clean, None


def selftest_paired() -> list[str]:
    problems = []
    key = "A" * 43 + "="
    good = {"id": "hp-laptop", "label": "HP", "kind": PAIRED, "pair_id": "ab" * 16,
            "identity": {"ed25519": key, "wg": key, "fingerprint": "AAAA-BBBB"},
            "tunnel": {"slot": 3, "side": 1, "role": "host", "dial": "host",
                       "endpoint": "192.168.16.102", "port": 51830},
            "links": [{"office": "macbook", "direction": "use"}], "paired_at": 1,
            "machine": "computer_ssh-x", "token": "REDACTED-value-1"}
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
    cases = [
        ("the office itself", dict(good, id="macbook")),
        ("no pair_id", dict(good, pair_id="")),
        ("no WireGuard key", dict(good, identity={"ed25519": key, "wg": ""})),
        ("a slot another pair holds", dict(good, tunnel=dict(good["tunnel"], slot=2))),
        ("a side that contradicts the role", dict(good, tunnel=dict(good["tunnel"], side=2))),
        ("an endpoint with a scheme", dict(good, tunnel=dict(good["tunnel"], endpoint="http://x"))),
        ("an endpoint that carries a port", dict(good, tunnel=dict(good["tunnel"], endpoint="h:1"))),
        ("a port out of range", dict(good, tunnel=dict(good["tunnel"], port=70000))),
        ("a link to another office", dict(good, links=[{"office": "vps1", "direction": "use"}])),
        ("an unknown direction", dict(good, links=[{"office": "macbook", "direction": "all"}])),
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
    return problems


if __name__ == "__main__":
    bad = selftest_paired()
    for b in bad:
        print("FAIL", b)
    print("declaration.py selftest:", "PASS" if not bad else f"{len(bad)} problem(s)")
    raise SystemExit(1 if bad else 0)
