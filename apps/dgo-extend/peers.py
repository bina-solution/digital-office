"""dgo-extend.peers — an app that RUNS on a remote office and is still shown HERE.

The idea in one line: an office can host an app, and the home office keeps the app's tile and keeps
opening it, without the app's container running at home.

Three facts make that possible, and each has exactly one owner:

1. **The choice is declared.** `placement:` in the office declaration (`/data/dgo/<id>.yaml`)
   lists the apps that belong to that office while staying visible at home. The declaration is
   written from the app's screen, and a converge makes the world match it.

2. **The door is the office's, not a new trust plane.** The remote edge gets ONE router per placed
   app, on `peer.<office-domain>`, whose rule requires a per-office token header
   (a `Header(...)` rule on the X-Office-Peer token). This app holds that token and is the only caller that adds it:
   the browser never sees the peer host, the peer host is not reachable without the token, and the
   app that runs there keeps its own SSO on its own host — this adds a door, it does not open one.

3. **The home console learns about it from the app that declares it.** Each placement writes one
   file into `peers/` — the tile (taken from the REMOTE office's own compiled registry, so the name,
   icon and group are the app's own words, not a second copy) and the base URL, which points at this
   service's `/peer/…` door. The console mounts that directory read-only and merges it with what the
   compiler produced, so a placed app appears in the rail exactly like a local one.

Nothing here duplicates the compiler: an app placed remotely is DISABLED at home (the state step
writes that), which is why the compiler has no tile for it — and why the peer registry has one.
"""
from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path

STATE = Path(os.environ.get("DGO_STATE_DIR", "/data"))
TOKENS = STATE / "peer-tokens.json"
PEERS = STATE / "peers"
#: The host the peer routers live on, under the office's own domain: `peer.<office domain>`.
PEER_HOST = "peer"
#: Where the console looks for this registry (declared in app.json `contributes.volumes`).
CONSOLE_DIR = "/app/peers.d"


def _load_tokens() -> dict:
    try:
        return json.loads(TOKENS.read_text())
    except (OSError, ValueError):
        return {}


def token_for(oid: str, create: bool = True) -> str | None:
    """The office's peer token. Mnemonic-free and per office: it grants "reach the apps of THIS
    office", and deleting the office's declaration revokes nothing on the machine — the token is in
    the file that is rewritten on the next converge."""
    toks = _load_tokens()
    if toks.get(oid):
        return toks[oid]
    if not create:
        return None
    toks[oid] = secrets.token_hex(32)
    STATE.mkdir(parents=True, exist_ok=True)
    tmp = TOKENS.with_suffix(".tmp")
    tmp.write_text(json.dumps(toks, indent=2))
    tmp.chmod(0o600)
    tmp.replace(TOKENS)
    return toks[oid]


def peer_url(office: dict, alias: str) -> str:
    """The public peer URL of one placed app on its remote office."""
    return f"https://{PEER_HOST}.{office['domain']}/{alias}/"


def _file(oid: str, alias: str) -> Path:
    return PEERS / f"{oid}--{alias}.json"


def home_label() -> str:
    """How THIS office names itself — the name the tile of a placed app says it belongs to.

    `converge.set_home_label` is the only writer (`bbox dgo label`, and the office record), and this
    is its read side for the peer record below: the record is the tile the owner sees, and the tile's
    sentence is `<office> לא זמינה כרגע` — which is worth nothing if `<office>` is a machine id like
    `local`. An office that never named itself falls back to its id rather than to an empty string.
    """
    try:
        doc = json.loads((STATE / "home.json").read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return "local"
    lab = doc.get("label")
    if isinstance(lab, dict):
        lab = lab.get("he") or lab.get("en")
    return str(lab or doc.get("id") or "local").strip()


def write(oid: str, alias: str, module: dict, base: str, label: str | None = None) -> None:
    """Publish ONE placement to the console: the tile + where to reach it.

    `label` is the office's own name, and it is written into the record on purpose: the console does
    not know the offices (it is handed tiles, not a fleet), so a record without it can only render the
    office's id. Optional so a caller holding a richer name — or a test — can say so itself.
    """
    PEERS.mkdir(parents=True, exist_ok=True)
    m = {k: v for k, v in (module or {}).items() if k != "service"}   # `service` is a local probe
    m["embed"] = f"/a/{alias}/"
    doc = {"office": oid, "alias": alias, "label": str(label if label is not None else home_label()),
           "module": m, "base": base}
    tmp = _file(oid, alias).with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(_file(oid, alias))


def read(oid: str, alias: str) -> dict | None:
    """One published placement, or None — the door asks this before it proxies anywhere."""
    try:
        return json.loads(_file(oid, alias).read_text())
    except (OSError, ValueError):
        return None


def clear(oid: str, alias: str) -> bool:
    p = _file(oid, alias)
    if p.exists():
        p.unlink()
        return True
    return False


def clear_office(oid: str, keep: set[str]) -> list[str]:
    """Drop the placements of one office that are no longer declared. Returns what was removed —
    a silently stale tile is worse than no tile: it opens a host that is no longer routed."""
    gone = []
    for p in sorted(PEERS.glob(f"{oid}--*.json")):
        alias = p.stem.split("--", 1)[1]
        if alias not in keep:
            p.unlink()
            gone.append(alias)
    return gone


def publish_link(verdicts: dict) -> None:
    """Hand the console what was just MEASURED about every linked office: `{office: {ok, hop}}`.

    The console marks a linked office's tiles from this before anybody opens one, and names the hop
    on the card it shows instead of a dead frame. It used to read an `ok` that nothing wrote — every
    tile of an office whose tunnel had been dead for fifteen hours looked alive (2026-10-04).
    Written whole after every projection pass, with the time: a file nobody has rewritten for five
    minutes is not a measurement, and the console treats it as none.
    """
    PEERS.mkdir(parents=True, exist_ok=True)
    tmp = (PEERS / "link.json").with_suffix(".tmp")
    tmp.write_text(json.dumps({"at": int(time.time()), "offices": verdicts}, ensure_ascii=False) + "\n")
    tmp.replace(PEERS / "link.json")
