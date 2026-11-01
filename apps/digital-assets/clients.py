"""digital-assets.clients — the two doors to the net front: social accounts and websites.

This app never speaks to a platform itself. Social accounts are the `social` capability's
(social-list: `social.v1`), websites are the `sites` capability's. Both are optional at runtime
(`wants`, weak): with either absent the app still works, and every plan item that needed it says so.
"""
from __future__ import annotations

import os

import requests

SOCIAL_URL = os.environ.get("SOCIAL_URL", "http://social-list:8986").rstrip("/")
SITES_URL = os.environ.get("SITES_URL", "http://sites:8979").rstrip("/")
TIMEOUT = 20


class Unavailable(Exception):
    """The other service did not answer (not: it answered no)."""


def _req(method: str, url: str, **kw):
    kw.setdefault("timeout", TIMEOUT)
    try:
        r = requests.request(method, url, **kw)
    except requests.RequestException as e:
        # read by a person, inside a Hebrew sentence: what happened, never the exception's class name
        raise Unavailable("לא ענה בזמן" if isinstance(e, requests.Timeout)
                          else "אינו רץ בלשכה הזאת" if isinstance(e, requests.ConnectionError)
                          else "לא ענה") from e
    try:
        body = r.json() if r.content else {}
    except ValueError:
        body = {"error": r.text[:300]}
    return r.status_code, body


def _said(code: int, body: dict) -> str:
    """What a service that answered no said — its own sentence, else the status in the reader's words."""
    return body.get("error") or f"ענה בשגיאה {code}"


# ── social-list ──────────────────────────────────────────────────────────────────────────────────
def social_overview() -> dict:
    code, body = _req("GET", f"{SOCIAL_URL}/api/overview")
    if code >= 400:
        raise Unavailable(_said(code, body))
    return body


def social_accounts() -> list[dict]:
    code, body = _req("GET", f"{SOCIAL_URL}/api/accounts")
    if code >= 400:
        raise Unavailable(_said(code, body))
    return body.get("accounts") or []


def social_capabilities(account_id: str) -> dict:
    code, body = _req("POST", f"{SOCIAL_URL}/capabilities", json={"account": account_id})
    if code >= 400:
        return {"error": _said(code, body), "status": code}
    return body


def social_profile(account_id: str) -> dict:
    code, body = _req("GET", f"{SOCIAL_URL}/api/accounts/{account_id}/profile")
    return body if code < 400 else {"error_body": body}


def social_update_profile(account_id: str, changes: dict, *, client: str, actor: str,
                          summary: str = "", watch: bool = False) -> tuple[int, dict]:
    return _req("PATCH", f"{SOCIAL_URL}/api/accounts/{account_id}/profile",
                json={"changes": changes, "client": client, "actor": actor, "summary": summary,
                      "watch": watch, "wait": 0})


def social_create_post(account_id: str, post: dict, *, client: str, actor: str,
                       watch: bool = False) -> tuple[int, dict]:
    return _req("POST", f"{SOCIAL_URL}/api/accounts/{account_id}/posts",
                json={"post": post, "client": client, "actor": actor, "watch": watch, "wait": 0})


def social_job(job_id: str) -> dict | None:
    code, body = _req("GET", f"{SOCIAL_URL}/api/jobs/{job_id}")
    return body if code == 200 else None


# ── sites ────────────────────────────────────────────────────────────────────────────────────────
def sites_list() -> list[dict]:
    code, body = _req("GET", f"{SITES_URL}/api/sites")
    if code >= 400:
        raise Unavailable(_said(code, body))
    return body.get("sites") or []


def sites_slots(site_id: str) -> tuple[int, dict]:
    return _req("GET", f"{SITES_URL}/api/sites/{site_id}/slots")


def sites_apply(site_id: str, bundle: dict, *, actor: str, client: str) -> tuple[int, dict]:
    return _req("POST", f"{SITES_URL}/api/sites/{site_id}/slots/apply",
                json={"bundle": bundle, "actor": actor, "client": client}, timeout=120)
