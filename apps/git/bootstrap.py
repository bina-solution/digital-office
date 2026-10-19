"""git.bootstrap — the ONE credential the office mints for its own forge.

Why this exists. Every other account this app holds is created by a PERSON in the connect wizard: a
provider, an auth method, a token the owner pastes, and the vault keeps it. The local forge cannot
work that way — it is ours, it is created by this app's compose, and asking the owner to log into a
forge that exists only because the office started it, generate a token by hand and paste it into a
wizard is the kind of ceremony that ends with a deployment whose forge is unreachable-by-design.

So the office mints it. The two halves live in two containers and this module is the seam:

  * the FORGE holds the admin CLI (`forgejo admin user create|generate-access-token`) and is the only
    place a user can be created. It runs as the `git` user, never as root — Forgejo refuses to run
    as root, and that refusal is a real sentence from a real run, not a theory;
  * the GIT service (this process) is the only one that can reach the credential plane's instance
    API, and it already owns the protocol→provider mapping for `git_forge_local`.

`hooks/prepare` runs the forge half with docker exec, captures the password and the token from that
command's OUTPUT (never from a command-line argument — a secret in argv is a secret in `ps`), and
pipes them here over stdin. This module then VERIFIES the token against the forge before storing it
(platform-service-contract §4b: a connection is verified, never merely added) and writes it to the
vault as one `git_forge_local` instance.

Idempotent by construction: `--check` answers whether a WORKING account already exists, and the hook
mints a new token only when it does not. Re-running is therefore free, and the recovery path after a
lost token is the same command.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import httpx

import accounts

FORGE_URL = (os.environ.get("FORGE_URL") or "http://forge:3000").rstrip("/")
PROTOCOL = "git_forge_local"
TOKEN_NAME = os.environ.get("GIT_FORGE_TOKEN_NAME", "office-agent")
_VT = 15.0


def _out(payload: dict, code: int = 0) -> int:
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return code


def _verify(base_url: str, token: str) -> dict:
    """Call the forge with the token. A token that does not answer `whoami` is not stored."""
    with httpx.Client(timeout=httpx.Timeout(_VT)) as c:
        r = c.get(f"{base_url}/api/v1/user",
                  headers={"Authorization": f"token {token}", "Accept": "application/json"})
    if r.status_code != 200:
        raise RuntimeError(f"הפורג' דחה את הטוקן (HTTP {r.status_code}).")
    return r.json()


def _local_instances() -> list[dict]:
    insts, err = accounts.vault_list()
    if err:
        raise RuntimeError(f"שירות החיבורים אינו זמין ({err}).")
    return [i for i in insts if (i.get("protocol") or "") == PROTOCOL]


def check() -> dict:
    """Is the office already able to act on its own forge? The hook's decision input."""
    try:
        locals_ = _local_instances()
    except RuntimeError as e:
        return {"ok": False, "vault": False, "reason": str(e), "has_account": False}
    if not locals_:
        return {"ok": True, "vault": True, "has_account": False,
                "reason": "לא נוצר עדיין חשבון לפורג' המקומי."}
    inst = locals_[0]
    sec = accounts.vault_secret(inst["id"]) or {}
    token = (sec.get("token") or "").strip()
    base = (sec.get("base_url") or FORGE_URL).rstrip("/")
    if not token:
        return {"ok": True, "vault": True, "has_account": False, "instance": inst["id"],
                "reason": "החשבון קיים בוולט בלי טוקן."}
    try:
        who = _verify(base, token)
    except (RuntimeError, httpx.HTTPError) as e:
        return {"ok": True, "vault": True, "has_account": False, "instance": inst["id"],
                "reason": f"הטוקן השמור אינו עובד: {e}"}
    return {"ok": True, "vault": True, "has_account": True, "instance": inst["id"],
            "login": who.get("login"), "base_url": base,
            # Whether the vault also holds a PASSWORD for the forge's web login. Forgejo's own login
            # is the only door until SSO covers this host, and a password nobody stored is a password
            # nobody has — so the hook mints and stores one when this is false.
            "has_password": bool((sec.get("password") or "").strip()),
            "active": accounts.active_id() == inst["id"]}


def register(payload: dict) -> dict:
    """Store (or refresh) the forge credential. Verified before it is written."""
    token = (payload.get("token") or "").strip()
    username = (payload.get("username") or "").strip() or "office"
    password = payload.get("password") or ""
    base = (payload.get("base_url") or FORGE_URL).rstrip("/")
    if not token:
        raise ValueError("לא התקבל טוקן מהפורג'.")
    who = _verify(base, token)
    secret = {"kind": "pat", "token": token, "username": username, "base_url": base,
              "host": base}
    if password:
        # The owner's break-glass login for the forge UI. Stored, not printed: the account screen is
        # where a person reads it, and it is replaced the day SSO covers the forge.
        secret["password"] = password
    existing = _local_instances()
    if existing:
        inst_id = existing[0]["id"]
        out, status = accounts.vault_update_secret(inst_id, secret)
        if status >= 300:
            raise RuntimeError(f"עדכון הסוד בוולט נכשל: {out}")
        action = "updated"
    else:
        label = f"פורג' מקומי: {who.get('login') or username}"
        out, status = accounts.vault_add(PROTOCOL, label, secret,
                                         account_hint=f"{who.get('login') or username}@{base}")
        if status >= 300:
            raise RuntimeError(f"שמירת החשבון בוולט נכשלה: {out}")
        inst_id = out.get("id")
        action = "created"
    accounts.forget_probe(inst_id)
    # The forge is the office's OWN account: on a fresh deployment there is no active account yet,
    # and leaving it unselected would make every op answer "no active account" for no reason.
    if not accounts.active_id():
        accounts.set_active(inst_id)
    return {"ok": True, "action": action, "instance": inst_id, "login": who.get("login"),
            "base_url": base, "active": accounts.active_id(),
            "token_name": payload.get("token_name") or TOKEN_NAME}


def main() -> int:
    ap = argparse.ArgumentParser(description="the office's own forge credential")
    ap.add_argument("--check", action="store_true", help="report whether a working account exists")
    ap.add_argument("--register", action="store_true", help="read the credential JSON on stdin")
    ap.add_argument("--doctor", action="store_true", help="print the whole picture")
    args = ap.parse_args()
    try:
        if args.register:
            raw = sys.stdin.read().strip()
            if not raw:
                return _out({"ok": False, "error": "לא התקבל JSON ב-stdin."}, 1)
            return _out(register(json.loads(raw)))
        if args.doctor:
            return _out({"check": check(),
                         "forge": {"url": FORGE_URL,
                                   "healthz": _healthz()},
                         "protocols": accounts.OWNED_PROTOCOLS,
                         "active": accounts.active_id()})
        return _out(check())
    except (RuntimeError, ValueError, json.JSONDecodeError) as e:
        return _out({"ok": False, "error": str(e)}, 1)
    except httpx.HTTPError as e:
        return _out({"ok": False, "error": "לא ניתן להגיע לפורג'."}, 1)


def _healthz() -> dict:
    try:
        with httpx.Client(timeout=httpx.Timeout(5.0)) as c:
            r = c.get(f"{FORGE_URL}/api/healthz")
        return {"ok": r.status_code == 200, "status": r.status_code}
    except httpx.HTTPError as e:
        return {"ok": False, "error": type(e).__name__}


if __name__ == "__main__":
    raise SystemExit(main())
