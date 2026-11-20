"""dgo-extend.clients — a company's office we set up, linked to ours ONE WAY, by the herd file (DGO-1636, DGO-964).

THE RULE (the owner, MEET-13, DGO-964). While we set up a company's office our herd is linked to it one way: we see
and manage it, it sees nothing of ours; at hand-over the link is cut and the company goes on alone. A client's office
runs DGO Extend of its own, so it is linked as a JOIN pair (DGO-1363), never an installed tunnel: our office asks the
client's link door to join, and the owner approves it once, on the client's screen.

THE DECLARATION. The herd file (apps/computers/herd.yaml, mounted read-only at /herd) names each client:

    clients:
      exampleu:
        herd: Exampleu                                   # the company's herd (a label)
        door: https://link.exampleu.digital-office.co.il # the client's link door
        pin: 0A0A-0000-0000-0001                       # its fingerprint (or Ed25519 key): no other office is taken
        by: [macbook]                                  # the offices of OURS that join it

An office of ours named in `by` — and holding the key the herd file gives that name, never by name alone (a client
runs this same checkout) — joins the client beside its own DGO_JOIN (join_api.ClientJoiner), asking `use`. A client
with no pin, or a door that is not https, is never joined: the approval on its screen is the only person in the loop,
and the pin is what makes the answer the client's.

ONE WAY, held on OUR side, twice: the client joiner accepts only the host's `serve` (join_api.ClientJoiner), and this
office's effective `serve:` narrows every client to nothing (`narrow`, applied in converge.with_give) — by its record's
id and by its pinned identity, whatever `serve:` says. Withholding needs no key: never giving a client is never wrong.
The narrowing covers what `serve:` gives (apps, shared apps, doors with no tile); the link's own control door and the
catalog listener are the direction's (`use` renders no serving half), not this map's.

HAND-OVER. The link is cut by unpairing it — from either office's screen, one action (DGO-964) — and only then is the
client's line removed from the herd file. Removing the line stops asking and lifts the narrowing; it does not unpair.
"""
from __future__ import annotations

import logging
import re

import yaml

import give
import join_api

log = logging.getLogger("dgo-extend.clients")

KEY = "clients"
#: a client's id, as an office id is written (catalog.OFFICE_RE)
CLIENT_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}\Z")


def load_herd_text(text: str) -> dict:
    """The herd file's text as give.load_herd reads it (for the tests and `bbox` readers)."""
    doc = yaml.safe_load(text) or {}
    return doc if isinstance(doc, dict) else {}


def _by(spec: dict) -> list[str]:
    by = spec.get("by")
    by = [by] if isinstance(by, str) else by
    return [str(b).strip().lower() for b in by] if isinstance(by, list) else []


def _valid(doc: dict, cid: str, spec) -> dict | None:
    """{door, pin, herd} of one client entry, or None (said once) when it cannot be joined safely."""
    if not CLIENT_RE.match(str(cid)) or not isinstance(spec, dict):
        give._once("the herd file's client %r is not an office id with a mapping — not joined", cid)
        return None
    if give.entry_of(doc, str(cid)):
        give._once("the herd file's client %s is the name of an office of OURS — never joined as a client", cid)
        return None
    door, pin = str(spec.get("door") or "").strip(), str(spec.get("pin") or "").strip()
    if not pin:
        give._once("the herd file's client %s has no pin — a join any office could answer is never made", cid)
        return None
    try:
        cfg = join_api.parse_declaration({"DGO_JOIN": door, "DGO_JOIN_PIN": pin, "DGO_JOIN_DIRECTION": "use"})
    except join_api.PairError as e:
        give._once("the herd file's client %s cannot be joined: %s", cid, e)
        return None
    if not cfg or cfg.get("invite") or not door.startswith("https://"):
        give._once("the herd file's client %s names no https door — not joined", cid)
        return None
    return {"door": cfg["hub"], "pin": pin, "herd": str(spec.get("herd") or cid)}


def mine(doc: dict, home: dict) -> dict:
    """{client id: {door, pin, herd}} — the clients THIS office joins: named in their `by`, and this office holding
    the key the herd file gives that name. {} for anything else."""
    table = (doc or {}).get(KEY)
    if not isinstance(table, dict) or not table:
        return {}
    me = give.entry_of(doc, str((home or {}).get("id") or ""))
    if not me:
        return {}
    want, have = give._herd_key(doc, me), give._key((home or {}).get("identity"))
    if not want or have != want:
        give._once("this office is called %s, but its key is not the one the herd file gives %s — it joins no "
                   "client", (home or {}).get("id"), me)
        return {}
    out = {}
    for cid, spec in table.items():
        if isinstance(spec, dict) and any(give.entry_of(doc, b) == me for b in _by(spec)):
            ok = _valid(doc, str(cid), spec)
            if ok:
                out[str(cid)] = ok
    return out


def declaration(spec: dict) -> dict:
    """The join declaration a client joiner reads — DGO_JOIN's own words, asking `use`."""
    return {"DGO_JOIN": spec["door"], "DGO_JOIN_PIN": spec["pin"], "DGO_JOIN_DIRECTION": "use"}


def _pinned(identity, pin: str) -> bool:
    ident = identity if isinstance(identity, dict) else {}
    if not pin:
        return False
    if str(ident.get("fingerprint") or "").upper() == pin.upper() or str(ident.get("ed25519") or "") == pin:
        return True
    try:
        return join_api.pin_holds(pin, ident) and bool(ident.get("ed25519"))
    except Exception:                                   # noqa: BLE001 — an identity it cannot read is not the client
        return False


def withheld(doc: dict, home: dict, records: list) -> set:
    """The ids of this office's records that are a client of ours — by the record's id, or by the client's pinned
    identity (a client not yet named as the herd names it). Only on an office of OURS (by name, as the admin
    withholding: our rule is not a client herd's own rule between its offices; no key is asked, since never giving a
    client is never wrong), and never one of our own offices (a client entry that names or pins one is a mistake)."""
    table = (doc or {}).get(KEY)
    if not isinstance(table, dict) or not table or not give.entry_of(doc, str((home or {}).get("id") or "")):
        return set()
    out = set()
    for cid, spec in table.items():
        if give.entry_of(doc, str(cid)):
            give._once("the herd file's client %s is the name of an office of OURS — nothing is withheld for it", cid)
            continue
        pin = str((spec or {}).get("pin") or "").strip() if isinstance(spec, dict) else ""
        for rec in records or []:
            if not isinstance(rec, dict) or not rec.get("id"):
                continue
            rid = str(rec["id"]).strip().lower()
            if give.entry_of(doc, rid):
                continue                                 # one of ours is never a client, whatever a pin matches
            if rid == str(cid).strip().lower() or _pinned(rec.get("identity"), pin):
                out.add(rid)
    return out


def narrow(serve_map, cut: set) -> dict:
    """A COPY of `serve_map` that gives each office in `cut` nothing: `only.<office>: []`, and no door with no tile
    (`services.<alias>.to`) names it. The map given is never changed; nothing to cut returns it as it is."""
    if not cut:
        return serve_map
    out = dict(serve_map or {})
    only = dict(out.get("only") or {}) if isinstance(out.get("only"), dict) else {}
    for office in sorted(cut):
        only[office] = []
    out["only"] = only
    if isinstance(out.get("services"), dict):
        services = {}
        for alias, spec in out["services"].items():
            if isinstance(spec, dict) and "to" in spec:
                raw = spec["to"]
                # a `to` that is not a name or a list of names is given to nobody here: never guessed open
                to = [raw] if isinstance(raw, str) else list(raw) if isinstance(raw, (list, tuple)) else []
                spec = {**spec, "to": [o for o in to if str(o).strip().lower() not in cut]}
            services[alias] = spec
        out["services"] = services
    return out


def _text(value) -> str:
    """One line of at most 60 characters a person reads (a herd's name, an office's, a server's address), or ""."""
    text = " ".join(str(value or "").split()) if isinstance(value, (str, int, float)) else ""
    return text if len(text) <= 60 else ""


def declared(doc: dict) -> dict:
    """{client id: {herd, label, host, pin, by}} — EVERY client office the herd file names, linked or not (DGO-2026).

    The owner, 2026-11-19: «I want to see all of our clients, every herd of theirs organised». The map draws a
    client's herd from the moment its line is written here: an office of it that no link reaches yet is drawn as one
    («not linked yet»), with the server it runs on (`host`). Several lines may share one `herd` — a company with two
    offices (a server and a tablet). Nothing here joins anything: that is `mine`, with its door and pin.
    One of OUR offices' names is never a client's."""
    table = (doc or {}).get(KEY)
    if not isinstance(table, dict):
        return {}
    out = {}
    for cid, spec in table.items():
        cid = str(cid)
        if not CLIENT_RE.match(cid) or not isinstance(spec, dict) or give.entry_of(doc, cid):
            continue
        out[cid] = {"herd": _text(spec.get("herd")) or cid, "label": _text(spec.get("label")),
                    "host": _text(spec.get("host")), "pin": _text(spec.get("pin")), "by": _by(spec)}
    return out


def entry_for(doc: dict, rec: dict) -> str:
    """The client id the herd file gives the office this record describes, or "". A line with a pin is that client
    only by the pinned identity — under its own id or under a name of its own (Examplex's office joined by its hostname
    first) — so a stranger that pairs under the id `exampleu` is not drawn as Exampleu; a line with no pin, by its id. One
    of OUR offices is never a client, whatever an entry names or pins. (Display only: `withheld` matches by id OR pin,
    since withholding more is never wrong.)"""
    if not isinstance(rec, dict) or not rec.get("id"):
        return ""
    rid = str(rec["id"]).strip().lower()
    if give.entry_of(doc, rid):
        return ""
    table = declared(doc)
    own = table.get(rid)
    if own is not None and (not own["pin"] or _pinned(rec.get("identity"), own["pin"])):
        return rid
    return next((cid for cid, c in table.items() if c["pin"] and _pinned(rec.get("identity"), c["pin"])), "")
