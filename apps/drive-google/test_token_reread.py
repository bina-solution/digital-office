"""A renewal starts from the vault, not from what this process still holds (EXU-24).

    python3 apps/drive-google/test_token_reread.py

An office that reads a client's Drive only connects it again, read-only. The vault then holds the new, narrow
grant — but this engine may still hold the old, full one in its cache, and a renewal from the old refresh token
(which Google still honours) would bring full Drive access back. So a renewal reads the vault first:

    · the vault's grant is the one renewed (its refresh token), never the cached one, when the vault answers
    · a grant the vault now refuses to hand out (wider than the read-only declaration) is dropped, and said
    · when the vault cannot answer, the token held is renewed, as before
    · an account the vault refuses is never used from an empty cache either

No network: `requests.post` (Google's token door) and the vault client are stood in.
"""
import importlib
import os
import sys
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _have(name):
    try:
        importlib.import_module(name)
    except Exception:                               # noqa: BLE001 — absent, or its own imports are
        sys.modules[name] = types.ModuleType(name)


for _name in ("requests", "connections_client"):
    _have(_name)
G = importlib.import_module("gdrive")
FAILS = []


def check(cond, what):
    print(("PASS  " if cond else "FAIL  ") + what)
    if not cond:
        FAILS.append(what)


class Resp:
    status_code = 200

    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body


def main() -> int:
    os.environ["N8N_GOOGLE_OAUTH_CLIENT_ID"] = "client-for-test"
    os.environ["N8N_GOOGLE_OAUTH_CLIENT_SECRET"] = "token-test-not-a-google-secret"
    renewed_with, written = [], []
    G.requests.post = lambda url, data=None, timeout=None, **kw: (
        renewed_with.append(data["refresh_token"]) or Resp({"access_token": "fresh-" + data["refresh_token"],
                                                            "expires_in": 3599, "scope": "openid drive.readonly"}))
    G.requests.RequestException = getattr(G.requests, "RequestException", Exception)
    G.cx.update_secret = lambda cid, secret: written.append((cid, secret)) or True
    vault = {"answer": None}
    G.cx.get_secret = lambda cid: vault["answer"]
    a = G.GoogleDriveAdapter({"id": "drive_google_oauth-1", "account_hint": "reader@example.com"})
    expired = int(time.time()) - 10

    # the engine still holds the OLD full grant; the vault holds the NEW read-only one
    G._CACHE["drive_google_oauth-1"] = {"access_token": "old", "refresh_token": "old-r", "expires_at": expired,
                                        "scope": "openid drive"}
    vault["answer"] = {"protocol": "drive_google_oauth",
                       "secret": {"access_token": "new", "refresh_token": "new-r", "expires_at": expired,
                                  "scope": "openid drive.readonly"}}
    tok = a._token()
    check(renewed_with == ["new-r"] and tok["access_token"] == "fresh-new-r",
          "a renewal uses the vault's grant (the account connected again), not the one this process held")
    check(G._CACHE["drive_google_oauth-1"]["refresh_token"] == "new-r" and written[-1][1]["refresh_token"] == "new-r",
          "…and the old grant is gone from the cache and from what is written back")

    # the vault refuses the grant (wider than the office's read-only declaration)
    G._CACHE["drive_google_oauth-1"] = {"access_token": "old", "refresh_token": "old-r", "expires_at": expired}
    vault["answer"] = {"refused": "drive_google_oauth מחובר כאן לקריאה בלבד — יש לחבר את החשבון מחדש"}
    n = len(renewed_with)
    try:
        a._token()
        raised = None
    except G.GoogleAuthError as e:
        raised = str(e)
    check(raised and "לקריאה בלבד" in raised and len(renewed_with) == n and "drive_google_oauth-1" not in G._CACHE,
          "a grant the vault refuses is not renewed, is dropped from the cache, and is said")
    try:
        a._token()
        raised = None
    except G.GoogleAuthError as e:
        raised = str(e)
    check(raised and "לקריאה בלבד" in raised, "…and from an empty cache it is never used either")

    # the vault cannot answer: the token held is renewed, as before
    G._CACHE["drive_google_oauth-1"] = {"access_token": "held", "refresh_token": "held-r", "expires_at": expired}
    vault["answer"] = None
    tok = a._token()
    check(renewed_with[-1] == "held-r" and tok["access_token"] == "fresh-held-r",
          "when the vault cannot answer, the token held is renewed, as before")

    def raises():
        try:
            a._token()
            return None
        except G.GoogleAuthError as e:
            return str(e)

    # the vault answers with no refresh token: connect again — the held grant is not renewed behind its back
    G._CACHE["drive_google_oauth-1"] = {"access_token": "held", "refresh_token": "held-r", "expires_at": expired}
    vault["answer"] = {"protocol": "drive_google_oauth", "secret": {"access_token": "x"}}
    n = len(renewed_with)
    said = raises()
    check(said and "refresh token" in said and len(renewed_with) == n and "drive_google_oauth-1" not in G._CACHE,
          "the vault's grant has no refresh token: nothing is renewed, the held grant is dropped, and it is said")

    # the vault refuses to KEEP the renewal (it is wider than the declaration): the renewed grant is not used
    G._CACHE["drive_google_oauth-1"] = {"access_token": "held", "refresh_token": "held-r", "expires_at": expired}
    vault["answer"] = None
    G.cx.update_secret = lambda cid, secret: {"refused": "drive_google_oauth מחובר כאן לקריאה בלבד"}
    said = raises()
    check(said and "לקריאה בלבד" in said and "drive_google_oauth-1" not in G._CACHE,
          "a renewal the vault refuses to keep is not used: dropped from the cache, and said")

    print(f"{'OK' if not FAILS else 'FAILED'}: {len(FAILS)} failure(s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
