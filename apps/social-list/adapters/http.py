"""One HTTP helper for every API adapter — so every platform's failure reaches the screen the same way.

Platforms disagree on everything about errors (Graph: `{error:{message,code,type}}`, GitHub:
`{message, documentation_url}`, Discord: `{message, code, errors}`, Google: `{error:{message,
errors[]}}`, X: `{title, detail, errors[]}`), so the message is dug out of all of them here and the
status becomes one of the few states the screens know: `unauthorized` (the token is wrong or
expired — reconnect), `forbidden` (a missing scope/permission — name it), `rate_limited` (back off,
never hammer), `not_found`, or a plain provider error.
"""
from __future__ import annotations

import json

import requests

from adapters.base import SocialError

TIMEOUT = 30


def _message(payload) -> str:
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            return str(err.get("message") or err.get("error_user_msg") or err.get("type") or "")
        if isinstance(err, str):
            return err
        for k in ("message", "detail", "title", "error_description"):
            if payload.get(k):
                return str(payload[k])
        errs = payload.get("errors")
        if isinstance(errs, list) and errs:
            e0 = errs[0]
            return str(e0.get("message") if isinstance(e0, dict) else e0)
    if isinstance(payload, str):
        return payload.strip()[:300]
    return ""


def call(method: str, url: str, platform_name: str, *, ok=(200, 201, 202, 204), **kw):
    """Send; return the parsed body (dict/list/None). Raise SocialError with a Hebrew sentence."""
    kw.setdefault("timeout", TIMEOUT)
    try:
        r = requests.request(method, url, **kw)
    except requests.RequestException as e:
        raise SocialError(f"{platform_name}: אין תשובה מהשרת", status=502,
                          kind="network", detail=str(e)[:300]) from e
    try:
        body = r.json() if r.content else None
    except ValueError:
        body = r.text
    if r.status_code in ok:
        return body
    msg = _message(body)
    code = r.status_code
    if code == 401:
        he, kind = f"{platform_name}: ההרשאה נדחתה — הטוקן שגוי או שפג תוקפו. חברו מחדש.", "unauthorized"
    elif code == 403:
        he, kind = f"{platform_name}: אין הרשאה לפעולה הזו (חסרה הרשאה בטוקן או בתפקיד).", "forbidden"
    elif code == 404:
        he, kind = f"{platform_name}: לא נמצא — החשבון, העמוד או הפריט אינם קיימים או לא נגישים.", "not_found"
    elif code == 429:
        he, kind = f"{platform_name}: חריגה ממכסת הקריאות — הלשכה תחכה ולא תנסה שוב מיד.", "rate_limited"
    elif code in (400, 422):
        he, kind = f"{platform_name}: הפלטפורמה דחתה את הנתונים.", "rejected"
    else:
        he, kind = f"{platform_name}: שגיאה מהפלטפורמה (HTTP {code}).", "provider"
    if msg:
        he = f"{he} ({msg[:220]})"
    raise SocialError(he, status=code if code < 500 else 502, kind=kind, detail=msg or None,
                      provider_error=body if isinstance(body, (dict, list)) else None)


def data_uri(data: bytes, mime: str) -> str:
    import base64
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def dumps(o) -> str:
    return json.dumps(o, ensure_ascii=False)
