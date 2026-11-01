"""dgo-extend.links — the token that authorizes ONE direction of ONE link.

A link is a directed edge between two office instances, and the tunnel underneath it proves only WHO
is calling. What proves that the caller is ALLOWED to is this token: one instance per link per
direction, in the credential plane like every other account in this office — not in this app's own
files, and not in the declaration (a token in a YAML file is a token in every backup, every `git
diff` and every screen that renders the declaration).

Vocabulary
----------
- **grant**: the instance held by the office that SERVES the link — it is the thing checked when a
  request arrives over the tunnel.
- The consuming office holds its own copy of the same token, so both ends can prove the link without
  a third party. Revoking is deleting the instance on the serving side and removing the `links[]`
  entry on the consuming side; the next converge removes the peer from both tunnels.

The protocol name is `dgo_link`; the catalogue entry lives in
platform-base/connections/providers/40-apps.yaml so the owner can SEE the links in the vault screen.
"""
from __future__ import annotations

import json
import os
import secrets
import urllib.error
import urllib.request

PROTOCOL = "dgo_link"
CONNECTIONS_URL = os.environ.get("CONNECTIONS_URL", "http://connections:8990").rstrip("/")


class LinkError(RuntimeError):
    """The credential plane refused or was unreachable — never silently treated as "no token"."""


def _call(method: str, path: str, body: dict | None = None, timeout: float = 20) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(CONNECTIONS_URL + path, data=data, method=method,
                                 headers={"content-type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read() or b"{}")
        except ValueError:
            detail = {}
        raise LinkError(f"כספת האישורים השיבה {e.code}: "
                        f"{detail.get('error') or detail.get('detail') or ''}".strip())
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise LinkError("כספת האישורים אינה זמינה") from e


def token_name(office: str, peer: str, direction: str) -> str:
    """The instance id of one link's token — deterministic, so two converges converge on the same row
    instead of minting a second token for the same link."""
    return f"{PROTOCOL}-{office}-{peer}-{direction}"


def find(office: str, peer: str, direction: str = "") -> list[dict]:
    got = _call("GET", f"/api/instances?protocol={PROTOCOL}")
    rows = (got.get("instances") or [])
    out = []
    for row in rows:
        hint = str(row.get("account_hint") or "")
        if f"{office}->{peer}" in hint and (not direction or direction in hint):
            out.append(row)
    return out


def ensure(office: str, peer: str, direction: str, label: str = "") -> dict:
    """Read the link's token, minting it once if this office has never held one.

    Idempotent by construction: the instance id is derived from (office, peer, direction), so a
    second call finds the row it would have created. A NEW token is minted only when there is none —
    re-minting would silently invalidate the copy the other office holds, and the symptom would be
    "the link stopped working after a converge".
    """
    name = token_name(office, peer, direction)
    for row in find(office, peer, direction):
        if row.get("id") == name:
            return row
    token = secrets.token_hex(32)
    created = _call("POST", "/api/instances", {
        "id": name, "protocol": PROTOCOL,
        "label": label or f"קישור {office} → {peer} ({direction})",
        "account_hint": f"{office}->{peer} {direction}",
        "secret": {"token": token, "office": office, "peer": peer, "direction": direction,
                   "created_at": __import__("time").time()},
    })
    if not created.get("ok", True) and created.get("error"):
        raise LinkError(f"יצירת האסימון נכשלה: {created.get('error')}")
    return {"id": name, "protocol": PROTOCOL, "label": label, "account_hint": f"{office}->{peer}",
            "secret": {"token": token, "direction": direction}}


def token(instance_id: str) -> str:
    got = _call("GET", f"/api/instances/{instance_id}/secret")
    return ((got.get("secret") or {})).get("token", "")


def revoke(instance_id: str) -> bool:
    """Delete one link's token. The other end keeps its copy until ITS declaration is converged —
    which is why revocation is a converge on both sides and not a single button."""
    got = _call("DELETE", f"/api/instances/{instance_id}")
    return bool(got.get("ok", True))


def selftest() -> list[str]:
    """Pure-name checks: no vault, no network."""
    problems = []
    if token_name("home", "vps1", "use") != "dgo_link-home-vps1-use":
        problems.append("the instance id must be derived from office+peer+direction")
    if token_name("home", "vps1", "use") == token_name("home", "vps1", "serve"):
        problems.append("the two directions must not share one token")
    return problems


if __name__ == "__main__":
    bad = selftest()
    for b in bad:
        print("FAIL", b)
    print("links.py selftest:", "PASS" if not bad else f"{len(bad)} problem(s)")
    raise SystemExit(1 if bad else 0)
