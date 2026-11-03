"""share — lend one of this office's machines to ANOTHER office, over HTTPS.

Why HTTPS: the office that borrows may sit where nothing but HTTPS leaves the machine — a Claude
cloud office's egress is a proxy that re-terminates TLS, so TCP 22 and WireGuard's UDP never arrive.
A share is therefore a WebSocket on this app's own host, relayed byte for byte to the machine's sshd:

    wss://<computers host>/share/<token>  ──▶  <machine>:<ssh port>      (the built-in host included)

What a share IS, in two halves that are created and revoked together:
  * the borrower's PUBLIC key in the machine's `authorized_keys`, tagged `computers-share:<sid>:<to>`
    so revoking removes exactly that line and nothing the owner wrote;
  * a token that opens the door. Only its sha256 is kept here; the door is shown ONCE, when the
    share is made. The token decides whether the stream opens at all, so the open internet meets a
    refusal and never the sshd banner — sshd's own key check is what authenticates the borrower.

The borrowing side is the same app: a computer added with `door` instead of an address is reached
through `door_client.py` as ssh's ProxyCommand, so exec, probe and stream work unchanged.

Records live in the app's own volume (/data/shares.json), beside the office key — the one other
credential this service owns.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
import threading
import time
from pathlib import Path

log = logging.getLogger("computers.share")

PUBKEY_RE = re.compile(r"^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(256|384|521)) [A-Za-z0-9+/=]{40,}$")
TO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")
TAG = "computers-share"

_lock = threading.Lock()


def _path(state_dir: Path) -> Path:
    return state_dir / "shares.json"


def _load(state_dir: Path) -> dict:
    """The shares on record — and NEVER "no shares" for "cannot read shares".

    A corrupt or unreadable file used to answer `{}`, which every door reads as "unknown token": the
    borrower's key stays in authorized_keys while the door refuses, and nothing anywhere says why.
    So the failure is logged, loudly, with the path.
    """
    p = _path(state_dir)
    try:
        rows = json.loads(p.read_text(encoding="utf-8"))
        return rows if isinstance(rows, dict) else {}
    except FileNotFoundError:
        return {}                      # no share was ever made here — a real, quiet empty
    except (OSError, ValueError) as e:
        log.error("shares file %s is unreadable (%s: %s) — every door is shut until it is fixed; "
                  "the borrowers' keys are still in authorized_keys", p, type(e).__name__, e)
        return {}


def _save(state_dir: Path, rows: dict) -> None:
    p = _path(state_dir)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(p)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def key_blob(public_key: str) -> str | None:
    """`<type> <base64>` of a public key line, its comment dropped — or None when it is not one."""
    parts = (public_key or "").strip().split()
    if len(parts) < 2:
        return None
    blob = f"{parts[0]} {parts[1]}"
    return blob if PUBKEY_RE.match(blob) else None


# A key appended to a file whose last line has no newline joins THAT line, as its comment: on FPG's server
# (2026-11-02) office-key@hp sat inside office-key@local's line and the HP was never authorized (DGO-1231).
# So every append here first ends the file's last line, when it has one that is not ended.
END_LAST_LINE = '{ [ -z "$(tail -c1 ~/.ssh/authorized_keys 2>/dev/null)" ] || echo >> ~/.ssh/authorized_keys; }'


def authorize_command(sid: str, to: str, blob: str) -> str:
    """Append the borrower's key to authorized_keys once, tagged with the share's id."""
    line = f"{blob} {TAG}:{sid}:{to}"
    return (f"mkdir -p ~/.ssh && chmod 700 ~/.ssh && touch ~/.ssh/authorized_keys && "
            f"chmod 600 ~/.ssh/authorized_keys && "
            f"(grep -q '^{blob} {TAG}:{sid}:' ~/.ssh/authorized_keys || "
            f"{{ {END_LAST_LINE} && echo '{line}' >> ~/.ssh/authorized_keys; }})")


def revoke_command(sid: str) -> str:
    """Remove this share's line, then SAY what is left: the count of lines still tagged with it.

    The `; true` this used to end with made ssh's exit code 0 whatever happened, so a revoke that
    removed nothing (read-only ~/.ssh, a file the ssh user cannot write) was reported to the owner as
    "key removed" — and the share row was dropped with it, leaving a root key nobody could enumerate.
    Printing the count is the proof; `app.py` reads it (`key_removed` is `0`, not `code == 0`).
    """
    f = "~/.ssh/authorized_keys"
    return (f"[ -f {f} ] || {{ echo 0; exit 0; }}; "
            f"sed -i '/ {TAG}:{sid}:/d' {f} || true; "
            f"n=$(grep -c ' {TAG}:{sid}:' {f} 2>/dev/null || true); echo \"${{n:-0}}\"")


def new_id() -> str:
    return "share-" + secrets.token_hex(4)


def create(state_dir: Path, sid: str, computer: str, to: str, blob: str) -> tuple[dict, str]:
    """(record, token) — called once the key is on the machine. The token is returned here and
    never again."""
    token = secrets.token_urlsafe(32)
    rec = {"id": sid, "computer": computer, "to": to, "key": blob.split()[1][-16:],
           "token_sha256": _digest(token), "created_at": int(time.time())}
    with _lock:
        rows = _load(state_dir)
        rows[sid] = rec
        _save(state_dir, rows)
    return public(rec), token


def public(rec: dict) -> dict:
    return {k: v for k, v in rec.items() if k != "token_sha256"}


def rows(state_dir: Path, computer: str | None = None) -> list[dict]:
    out = [public(r) for r in _load(state_dir).values() if not computer or r.get("computer") == computer]
    return sorted(out, key=lambda r: r.get("created_at") or 0)


def get(state_dir: Path, sid: str) -> dict | None:
    return _load(state_dir).get(sid)


def drop(state_dir: Path, sid: str) -> None:
    with _lock:
        rows_ = _load(state_dir)
        rows_.pop(sid, None)
        _save(state_dir, rows_)


def find(state_dir: Path, token: str) -> dict | None:
    """The share a door token opens, compared in constant time — or None."""
    if not token or len(token) < 32:
        return None
    d = _digest(token)
    hit = None
    for r in _load(state_dir).values():
        if hmac.compare_digest(r.get("token_sha256", ""), d):
            hit = r
    return hit
