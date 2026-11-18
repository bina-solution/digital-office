"""digital-assets.clients — the two doors to the net front: social accounts and websites.

This app never speaks to a platform itself. Social accounts are the `social` capability's
(social-list: `social.v1`), websites are the `sites` capability's. Both are optional at runtime
(`wants`, weak): with either absent the app still works, and every plan item that needed it says so.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable

import requests

SOCIAL_URL = os.environ.get("SOCIAL_URL", "http://social-list:8986").rstrip("/")
SITES_URL = os.environ.get("SITES_URL", "http://sites:8979").rstrip("/")
TIMEOUT = 20

# ── an ABSENT optional service must cost a screen nothing ────────────────────────────────────────
# `social` is `wants`: the app works without it, and its absence is a sentence on the screen. But an absent service
# is not free: with no social-list in the office, resolving its name costs ~15 s, and the overview the screen awaits
# before it draws anything paid 7.5 s of it (measured on EXF's office 2026-11-05, its e52b414; DGO-1839). So a read the
# screen waits on has a DEADLINE, and a FAILURE — an absent or silent service — is remembered for OPTIONAL_FAIL_TTL:
# the first screen pays at most the deadline, the ones after it nothing. An answer is never remembered (EXF's took both
# for two minutes): a service that answers is read fresh, so an account connected a moment ago is on the next screen.
OPTIONAL_DEADLINE = 2.0
OPTIONAL_FAIL_TTL = 60.0
_optional_lock = threading.Lock()
_optional_failed: dict[str, tuple[float, Exception]] = {}


class Unavailable(Exception):
    """The other service did not answer (not: it answered no)."""


def optional(key: str, read: Callable[[], Any], deadline: float = OPTIONAL_DEADLINE) -> Any:
    """`read()`, or Unavailable within `deadline` seconds — and a failure is remembered for OPTIONAL_FAIL_TTL."""
    with _optional_lock:
        hit = _optional_failed.get(key)
    if hit and hit[0] > time.monotonic():
        raise hit[1]
    box: list[tuple[str, Any]] = []
    done = threading.Event()

    def run() -> None:
        try:
            box.append(("ok", read()))
        except Unavailable as e:
            box.append(("err", e))
        except Exception:                       # noqa: BLE001 — a foreign failure is «it did not answer»
            box.append(("err", Unavailable("לא ענה")))
        finally:
            done.set()

    threading.Thread(target=run, name=f"optional:{key}", daemon=True).start()
    kind, value = box[0] if done.wait(deadline) else ("err", Unavailable("לא ענה בזמן"))
    with _optional_lock:
        if kind == "err":
            _optional_failed[key] = (time.monotonic() + OPTIONAL_FAIL_TTL, value)
        else:
            _optional_failed.pop(key, None)
    if kind == "err":
        raise value
    return value


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
    # the overview and the channels screen wait for this one, and `social` is optional: see `optional()`
    return optional("social_accounts", _social_accounts)


def _social_accounts() -> list[dict]:
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
