"""social-list.platforms — the catalogue (platforms.yaml), read once and asked everywhere.

Everything that differs between Facebook and GitHub is DATA in platforms.yaml: the kinds an account
can be connected by, the profile limits, the post types, and the op × kind support matrix. This
module loads it, checks that it is internally consistent (a catalogue that can disagree with itself
is worse than a small one — the domains app learned that from its provider map), and answers the
three questions the rest of the app asks:

  * which platform and kind does this connection PROTOCOL belong to?  (`by_protocol`)
  * may this op run on this platform through this kind?               (`support`)
  * what does a screen need to draw the catalogue?                    (`catalog`)
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

import yaml

_PATH = Path(os.environ.get("SOCIAL_PLATFORMS_FILE") or Path(__file__).with_name("platforms.yaml"))
SELF_URL = os.environ.get("SOCIAL_LIST_URL", "http://social-list:8986").rstrip("/")


def _own_address() -> str:
    """How the OFFICE BROWSER reaches this app: this container's own IP, read at start.

    Not the container NAME: Chromium caches Docker's DNS answer (TTL 600 s), so after every
    redeploy the office browser kept dialling the old container address — ERR_CONNECTION_REFUSED
    for up to ten minutes (measured 2026-09-29) — while every other container resolved the new one.
    An IP literal has nothing to cache. Not the edge either: Traefik's forward-auth answers 404 for
    a host until authentik's blueprint for it is applied."""
    import socket
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if ip and not ip.startswith("127."):
            return f"http://{ip}:8986"
    except OSError:
        pass
    return SELF_URL


BROWSER_SELF_URL = (os.environ.get("SOCIAL_LIST_BROWSER_URL") or _own_address()).rstrip("/")

KINDS = ("browser", "api")
ANSWERS = ("yes", "limited", "no")

_lock = threading.Lock()
_cache: dict = {}


class CatalogError(Exception):
    pass


def _load() -> dict:
    with _lock:
        mtime = _PATH.stat().st_mtime
        if _cache.get("mtime") == mtime:
            return _cache["data"]
        data = yaml.safe_load(_PATH.read_text(encoding="utf-8")) or {}
        problems = validate(data)
        if problems:
            raise CatalogError("platforms.yaml is inconsistent: " + "; ".join(problems))
        _cache.update({"mtime": mtime, "data": data})
        return data


def validate(data: dict) -> list[str]:
    """Every problem at once, never the first one only — a catalogue is fixed in one sitting."""
    out: list[str] = []
    ops = data.get("ops") or {}
    if not ops:
        out.append("no ops vocabulary")
    seen_ids, seen_protocols = set(), set()
    for p in data.get("platforms") or []:
        pid = p.get("id")
        if not pid:
            out.append("a platform without an id")
            continue
        if pid in seen_ids:
            out.append(f"{pid}: duplicate id")
        seen_ids.add(pid)
        kinds = p.get("kinds") or {}
        if not kinds:
            out.append(f"{pid}: no kinds")
        for kind, spec in kinds.items():
            if kind not in KINDS:
                out.append(f"{pid}: unknown kind {kind!r}")
            proto = (spec or {}).get("protocol")
            if not proto:
                out.append(f"{pid}.{kind}: no protocol")
            elif proto in seen_protocols:
                out.append(f"{pid}.{kind}: protocol {proto} used twice")
            else:
                seen_protocols.add(proto)
        for op, answer in (p.get("ops") or {}).items():
            if op not in ops:
                out.append(f"{pid}: op {op!r} is not in the vocabulary")
            for kind, value in (answer or {}).items():
                if kind in ("why", "na"):
                    continue
                if kind not in KINDS:
                    out.append(f"{pid}.{op}: unknown kind {kind!r}")
                elif value not in ANSWERS:
                    out.append(f"{pid}.{op}.{kind}: {value!r} is not one of {ANSWERS}")
        missing = [op for op in ops if op not in (p.get("ops") or {})]
        if missing:
            out.append(f"{pid}: ops not answered: {', '.join(missing)}")
    return out


def data() -> dict:
    return _load()


def ops_vocabulary() -> dict:
    return data().get("ops") or {}


def platforms(include_test: bool = True) -> list[dict]:
    out = []
    for p in data().get("platforms") or []:
        if not include_test and p.get("test"):
            continue
        out.append(p)
    return out


def get(pid: str) -> dict | None:
    return next((p for p in platforms() if p.get("id") == pid), None)


def by_protocol(protocol: str) -> tuple[dict | None, str | None]:
    """A connection protocol → (platform, kind). The account's protocol IS the choice of adapter."""
    for p in platforms():
        for kind, spec in (p.get("kinds") or {}).items():
            if (spec or {}).get("protocol") == protocol:
                return p, kind
    return None, None


def all_protocols() -> list[str]:
    return sorted({(spec or {}).get("protocol") for p in platforms()
                   for spec in (p.get("kinds") or {}).values() if (spec or {}).get("protocol")})


def support(pid: str, op: str, kind: str) -> dict:
    """{answer, why} for one op on one platform through one kind. Unknown = "no", never an error."""
    p = get(pid) or {}
    kspec = (p.get("kinds") or {}).get(kind)
    if not kspec:
        return {"answer": "no", "why": "אין לפלטפורמה הזו חיבור מהסוג הזה"}
    entry = (p.get("ops") or {}).get(op) or {}
    why = (entry.get("why") or {}).get("he") or ""
    if entry.get("na"):
        return {"answer": "no", "why": why or "אין דבר כזה בפלטפורמה"}
    answer = entry.get(kind, "no")
    return {"answer": answer, "why": why}


def expand(template: str, platform: dict, values: dict | None = None) -> str:
    """Fill `{origin}`, `{self}`, `{handle}`… in a URL template. Unknown keys stay visible, on
    purpose: a URL with `{handle}` in it is an honest "we do not know the handle yet"."""
    values = dict(values or {})
    origin = origin_of(platform)
    values.setdefault("origin", origin)
    values.setdefault("self", SELF_URL)
    values.setdefault("browser_self", BROWSER_SELF_URL)
    out = template or ""
    for k, v in values.items():
        if v is not None:
            out = out.replace("{" + k + "}", str(v))
    return out


def origin_of(platform: dict) -> str:
    return ((platform.get("origin") or "").replace("{browser_self}", BROWSER_SELF_URL)
            .replace("{self}", SELF_URL))


def catalog() -> dict:
    """What the connect wizard and the matrix screen draw — the catalogue with URLs resolved."""
    out = []
    for p in platforms():
        kinds = []
        for kind, spec in (p.get("kinds") or {}).items():
            kinds.append({"kind": kind, **(spec or {})})
        # the recommended kind first — the order IS the recommendation
        kinds.sort(key=lambda k: 0 if k.get("recommended") else 1)
        out.append({**p, "origin": origin_of(p), "kinds": kinds})
    return {"ops": ops_vocabulary(), "support": data().get("support") or {}, "platforms": out}
