"""The local domain's mailboxes, as seen by the mail API.

`mailboxd` (apps/mail/mailboxd/mailboxd.py) owns the account file; this module is the only thing
that talks to it, and it is deliberately thin. Every rule about what a mailbox may be called, which
domain it may live at, and what deleting one does lives THERE, next to the file being written —
not here, and not in the browser. Validating in three places is how the three drift apart, and the
one that matters is the one holding the file handle.

So what this adds is only what the caller cannot get from mailboxd itself:

  · a reachable/unreachable answer instead of an exception (the mailbox screen degrades to
    "unavailable" without taking the mail UI down with it), and
  · the CONNECTION between a mailbox and the rest of the setup story — a mailbox is only worth
    anything if the domain's DNS is already published, so mailsetup.py reports the list beside the
    DNS checklist rather than on a page of its own.

There is no authentication on the hop to mailboxd and none is needed: it has no route, no
published port, and lives only on the compose network. mailapi is behind authentik, so the
authenticated edge is the one the operator already passes through.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

MAILBOXD_URL = (os.environ.get("MAILBOXD_URL") or "http://mailboxd:8971").rstrip("/")
TIMEOUT = float(os.environ.get("MAILBOXD_TIMEOUT", "20"))


def _call(method, path, body=None):
    """(payload, status). Never raises: an unreachable writer is a STATE the UI renders, not a 500
    on a page whose other half (reading mail) is working fine."""
    url = MAILBOXD_URL + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read().decode("utf-8", "replace")
            return (json.loads(raw) if raw else {}), r.status
    except urllib.error.HTTPError as e:
        # mailboxd answers its refusals as JSON with a real status (409 for an address that already
        # exists, 409 for the primary mailbox). Forward BOTH verbatim: rewriting them here would turn
        # a precise, actionable message into "the request failed".
        raw = e.read().decode("utf-8", "replace")
        try:
            return json.loads(raw), e.code
        except Exception:
            return {"error": raw[:300] or "mailbox service error"}, e.code
    except Exception as e:
        return {"error": "שירות תיבות הדואר אינו זמין", "detail": "%s: %s" % (type(e).__name__, e),
                "available": False}, 503


def listing():
    payload, code = _call("GET", "/mailboxes")
    if code != 200:
        return {"available": False, "mailboxes": [], "count": 0,
                "error": payload.get("error", "unavailable")}, code
    payload["available"] = True
    return payload, 200


def create(body):
    return _call("POST", "/mailboxes", {
        "local": (body or {}).get("local", ""),
        "address": (body or {}).get("address", ""),
        "password": (body or {}).get("password", ""),
    })


def set_password(address, password):
    """Rotate ONE mailbox's password. Called by the engine reconciler when a profile's instance is
    gone and its credential is therefore unrecoverable — see profiles.py."""
    return _call("PUT", "/mailboxes/" + urllib.parse.quote(address, safe="") + "/password",
                 {"password": password})


def delete(address):
    return _call("DELETE", "/mailboxes/" + urllib.parse.quote(address, safe=""))


def summary():
    """Just enough for the setup checklist: the addresses, and whether we could ask at all.

    Passwords and hashes are never in this path — mailboxd does not return them and nothing here
    would have a use for one."""
    payload, code = _call("GET", "/mailboxes")
    if code != 200:
        return {"available": False, "count": 0, "addresses": []}
    return {"available": True,
            "count": payload.get("count", 0),
            "primary": payload.get("primary"),
            "addresses": [m.get("address") for m in payload.get("mailboxes", [])]}
