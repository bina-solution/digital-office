"""accounts — this app's view of the credential plane (connections, :8990).

A Telegram account here is NOT a row in this app. It is a connection INSTANCE of protocol
`telegram_user` in the vault, exactly like a Google mailbox is an instance of `mail_gmail_oauth`.
What the app persists is one thing only: which instance it is currently acting as (the binding), in
`/data/active.json`.

Why that matters beyond tidiness: the session string in that instance is a full login — anyone
holding it is the owner, on Telegram, until they are logged out. Keeping it in the vault means it is
one copy, in the one place the deployment already backs up, reveals and audits; and it means removing
the account is a vault operation, not a hunt through a container.

The module deliberately mirrors `apps/drive/connections_client.py`:

  * a LISTING degrades (the vault being down yields an empty list plus the reason, and the app keeps
    answering), while a RESOLUTION does not (an op never silently runs as somebody else);
  * the vault's own error is carried to the UI as a reason, because "no accounts" and "the vault is
    unreachable" are different screens.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile

import requests

log = logging.getLogger("telegram-tv.accounts")

CONNECTIONS_URL = os.environ.get("CONNECTIONS_URL", "http://connections:8990").rstrip("/")
PROTOCOL = os.environ.get("TV_PROTOCOL", "telegram_user")
PROTOCOL_GLOB = "telegram_*"
ACTIVE_PATH = os.environ.get("TV_ACTIVE_PATH", "/data/active.json")
#: The binding is a {scope -> instance id} map with one scope today, from day one on purpose: the
#: day per-user selection arrives the scope key becomes the user and nothing else moves.
DEFAULT_SCOPE = "deployment"
TIMEOUT = 15


def _instances() -> tuple[list[dict], str | None]:
    try:
        r = requests.get(f"{CONNECTIONS_URL}/api/instances", params={"protocol": PROTOCOL_GLOB},
                         timeout=TIMEOUT)
        r.raise_for_status()
        return list((r.json() or {}).get("instances", [])), None
    except (requests.RequestException, ValueError) as e:
        log.warning("_instances: %r", e)
        return [], "שירות החשבונות אינו זמין"


def list_instances() -> tuple[list[dict], str | None]:
    insts, err = _instances()
    return [i for i in insts if (i.get("protocol") or "").startswith("telegram_")], err


def active_id() -> str | None:
    try:
        with open(ACTIVE_PATH, encoding="utf-8") as fh:
            return (json.load(fh) or {}).get(DEFAULT_SCOPE)
    except (OSError, ValueError):
        return None


def set_active(instance_id: str | None) -> None:
    payload = {} if not instance_id else {DEFAULT_SCOPE: instance_id}
    os.makedirs(os.path.dirname(ACTIVE_PATH) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(ACTIVE_PATH) or ".", prefix=".active-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    os.replace(tmp, ACTIVE_PATH)


def resolve() -> tuple[dict | None, dict | None, str | None]:
    """(instance, secret, reason) for the ACTIVE account.

    Never falls back to "some other account": playing a film from the wrong Telegram account is not a
    degraded experience, it is the wrong person's library. A missing active pointer therefore resolves
    to (None, None, reason) and the UI shows the connection screen."""
    insts, err = list_instances()
    if err:
        return None, None, err
    want = active_id()
    if not want:
        return None, None, None
    inst = next((i for i in insts if i.get("id") == want), None)
    if inst is None:
        return None, None, "החשבון הפעיל אינו קיים יותר — יש לבחור חשבון"
    secret = get_secret(want)
    if not secret:
        return inst, None, "לא ניתן לקרוא את פרטי החשבון משירות החשבונות"
    return inst, secret, None


def get_secret(instance_id: str) -> dict | None:
    try:
        r = requests.get(f"{CONNECTIONS_URL}/api/instances/{instance_id}/secret", timeout=TIMEOUT)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return (r.json() or {}).get("secret") or {}
    except (requests.RequestException, ValueError) as e:
        log.warning("secret fetch for %s failed: %s", instance_id, e)
        return None


def put_secret(instance_id: str, secret: dict) -> bool:
    """Write a refreshed session back. Merge semantics are the vault's default, which is what a
    re-login wants: the phone/api pair stays, the session string is replaced."""
    try:
        r = requests.put(f"{CONNECTIONS_URL}/api/instances/{instance_id}/secret",
                         json={"secret": secret, "replace": True}, timeout=TIMEOUT)
        r.raise_for_status()
        return True
    except requests.RequestException as e:
        log.warning("secret write-back for %s failed: %s", instance_id, e)
        return False


def create_instance(*, protocol: str, label: str, secret: dict, account_hint: str = "") -> tuple[str | None, str | None]:
    """(instance id, error). The id is minted by the vault (`<protocol>-<8 hex>`), never here — an id
    invented by an app is an id that can collide with one the vault already has."""
    try:
        r = requests.post(f"{CONNECTIONS_URL}/api/instances", timeout=TIMEOUT,
                          json={"protocol": protocol, "label": label, "secret": secret,
                                "account_hint": account_hint})
        if r.status_code >= 400:
            return None, (r.json() or {}).get("error") or f"HTTP {r.status_code}"
        return (r.json() or {}).get("id"), None
    except (requests.RequestException, ValueError) as e:
        log.warning("create_instance: %r", e)
        return None, "שירות החשבונות אינו זמין"


def delete_instance(instance_id: str) -> tuple[bool, str | None]:
    try:
        r = requests.delete(f"{CONNECTIONS_URL}/api/instances/{instance_id}", timeout=TIMEOUT)
        if r.status_code == 404:
            return True, None
        if r.status_code >= 400:
            return False, f"HTTP {r.status_code}"
        return True, None
    except requests.RequestException as e:
        log.warning("delete_instance: %r", e)
        return False, "שירות החשבונות אינו זמין"
