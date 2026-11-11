"""The proof an office gives the herd store that it is the office the link says it is (DGO-1523, slice 3).

WHY A PROOF OF ITS OWN

    The herd store is another office's data-management (the HP's), reached through that office's link
    door as a door with no tile (DGO-945): `backup-store`, its paths narrowed to /repo/ and
    /api/repo-runs. The door removes what the peer wrote about which office it is and writes
    `x-dgo-office` from the link (apps/dgo-extend/link-proxy.py OFFICE_HEADER) — but it SIGNS nothing
    for a door with no tile (its route carries no mapped user), and any container on the serving
    office's network can write that header too. So the header says which link a request came over, and
    the asking office proves it holds that link: an HMAC with the pair's own secret.

    The secret is the link token a pairing sealed to both ends (apps/dgo-extend/pairing.py), kept in
    each office's vault as a `dgo_link` instance and found by NAME exactly as the door finds it
    (`names_office`, link-proxy.py and apps/project-pln/office_identity.py). No other office holds it.
    What is signed starts with its own word (`dgo-backup-v1`), so a proof is never also a door's
    identity signature (`v1\\n<office>\\n<user>\\n<ts>`), and the reverse.

    THE LIMIT, said plainly: inside either office, the vault answers a `dgo_link` secret to any
    container that asks it (its caller check covers relayed calls only). So a container on the store's
    own network can make a proof — the same trust the door's own identity signature rests on. What it
    could then do is append to the repository given to that office (never delete, never read it in
    clear: the data is encrypted with a key only the backing-up office holds). Closing it is the vault's
    caller check for `dgo_link*`, a security item of its own.

THE HEADER

    x-dgo-backup-proof: v1 <office> <target> <unix seconds> <nonce: 32 hex> <hmac-sha256 hex>
    signed text:        dgo-backup-v1\\n<office>\\n<target>\\n<ts>\\n<nonce>

    It holds for WINDOW seconds either side of the store's clock, for the target it names, for the
    office the door names, and once: a nonce seen is refused until it could no longer be fresh.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.request

VAULT = (os.environ.get("CONNECTIONS_URL") or "http://connections:8990").rstrip("/")
HEADER = "x-dgo-backup-proof"
#: written by the serving office's door from the link the request came over (link-proxy.py OFFICE_HEADER)
OFFICE_HEADER = "x-dgo-office"
VERSION = "v1"
WINDOW = 300
#: an office id as the link names it: catalog.OFFICE_RE (always fullmatch, never `$`)
OFFICE_RE = re.compile(r"[a-z][a-z0-9-]{1,30}")
_TARGET = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
_TS = re.compile(r"[0-9]{1,12}")
_NONCE = re.compile(r"[0-9a-f]{32}")
_MAC = re.compile(r"[0-9a-f]{64}")
#: how long the vault's answer is trusted: a pair's secret does not rotate under a live link
SECRET_TTL = 60.0
CACHE_MAX = 128


class NotProved(Exception):
    """The request is not from the office it claims; the reason is for this office's log only."""


class Unavailable(Exception):
    """The vault did not answer: whether the proof holds is unknown, which is not «it does not»."""


def signed_text(office: str, target: str, ts: int, nonce: str) -> str:
    return f"dgo-backup-{VERSION}\n{office}\n{target}\n{int(ts)}\n{nonce}"


def make(office: str, target: str, secret: str, now: float | None = None) -> str:
    """The header value for one request to `target`, as `office`."""
    ts = int(time.time() if now is None else now)
    nonce = secrets.token_hex(16)
    mac = hmac.new(secret.encode("utf-8"), signed_text(office, target, ts, nonce).encode("utf-8"),
                   hashlib.sha256).hexdigest()
    return f"{VERSION} {office} {target} {ts} {nonce} {mac}"


# ── the pair's secret, from this office's vault ─────────────────────────────────────────────────
_CACHE: dict[str, tuple[float, str]] = {}
_CACHE_LOCK = threading.Lock()


def forget() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def names_office(row: dict, office: str) -> bool:
    """Is this `dgo_link` row the link with `office`? link-proxy.py's rule, exactly: `dgo_link-<office>`
    from a pairing, or `<a>-><b> <direction>` in a converged row's hint — never a split on `-`, since
    office ids carry hyphens (hp-laptop)."""
    iid = str((row or {}).get("id") or "").lower()
    if iid == f"dgo_link-{office}":
        return True
    hint = str((row or {}).get("account_hint") or "").lower().split(" ", 1)[0]
    return office in hint.split("->") if "->" in hint else False


def _get(path: str) -> dict:
    try:
        with urllib.request.urlopen(VAULT + path, timeout=10) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {}
        raise Unavailable(f"the vault answered {e.code}") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise Unavailable(f"the vault did not answer: {e}") from e


def link_secret(office: str) -> str:
    """The secret this office shares with `office` over their link; '' when no link row names it."""
    office = (office or "").strip().lower()
    if not OFFICE_RE.fullmatch(office):
        return ""
    now = time.monotonic()
    with _CACHE_LOCK:
        hit = _CACHE.get(office)
        if hit and now - hit[0] < SECRET_TTL:
            return hit[1]
    token = ""
    for row in _get("/api/instances?protocol=dgo_link").get("instances") or []:
        iid = str((row or {}).get("id") or "")
        # an agent's credential a linked office handed over is not the pair's secret (DGO-1127)
        if iid.startswith("dgo_link-serve-") and iid.endswith("-agent"):
            continue
        if not names_office(row, office) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", iid):
            continue
        token = str((_get(f"/api/instances/{iid}/secret").get("secret") or {}).get("token") or "")
        if token:
            break
    with _CACHE_LOCK:
        # a name with no link is remembered too (a forged one must not cost a vault call per request),
        # and the table is bounded: the oldest answer goes first
        _CACHE[office] = (now, token)
        while len(_CACHE) > CACHE_MAX:
            del _CACHE[min(_CACHE, key=lambda o: _CACHE[o][0])]
    return token


# ── checking one ────────────────────────────────────────────────────────────────────────────────
class _Seen:
    """Nonces already taken, each kept until a proof carrying it could no longer be fresh."""

    def __init__(self):
        self._lock = threading.Lock()
        self._until: dict[str, float] = {}

    def take(self, nonce: str, now: float) -> bool:
        with self._lock:
            for n in [n for n, t in self._until.items() if t <= now]:
                del self._until[n]
            if nonce in self._until:
                return False
            self._until[nonce] = now + 2 * WINDOW + 1
            return True


SEEN = _Seen()


def verify(value: str | None, door_office: str | None, target: str, now: float | None = None) -> str:
    """The office `value` proves, for a request the door says came from `door_office`, to `target`.
    Raises NotProved (with the reason, for this office's log) or Unavailable (the vault is silent)."""
    now = time.time() if now is None else now
    if not door_office:
        raise NotProved("no door wrote the office: the request did not come over a link")
    parts = (value or "").split(" ")
    if len(parts) != 6 or parts[0] != VERSION:
        raise NotProved("not a proof (its shape)")
    _, office, tgt, ts, nonce, mac = parts
    if not (OFFICE_RE.fullmatch(office) and _TARGET.fullmatch(tgt) and _TS.fullmatch(ts)
            and _NONCE.fullmatch(nonce) and _MAC.fullmatch(mac)):
        raise NotProved("not a proof (a field)")
    if office != door_office:
        raise NotProved(f"the proof names {office}, the door {door_office}")
    if tgt != target:
        raise NotProved(f"the proof was made for {tgt}, not {target}")
    if abs(now - int(ts)) > WINDOW:
        raise NotProved(f"the proof is {int(now) - int(ts)} s from this office's clock")
    secret = link_secret(office)
    if not secret:
        raise NotProved(f"no link with {office} in this office's vault")
    want = hmac.new(secret.encode("utf-8"), signed_text(office, tgt, int(ts), nonce).encode("utf-8"),
                    hashlib.sha256).hexdigest()
    if not hmac.compare_digest(want, mac):
        raise NotProved(f"the proof does not verify with the {office} link's secret")
    if not SEEN.take(nonce, now):
        raise NotProved("this proof was used already")
    return office
