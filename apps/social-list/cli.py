"""cli — the office's social networks, for agents and for the person at the server's shell. Reads only.

The hooks pipe THIS file into the social-list container (`dcx exec -T social-list python - <verb> … <
apps/social-list/cli.py`), so it runs from the checkout with no image rebuild, and talks to the
service on 127.0.0.1.

    accounts [platform]          every account: its network and kind (API or browser) — from the
                                 credential plane, no network asked
    activity                     the log of everything done on the owner's behalf

A profile and the posts are NOT here, on purpose: `getProfile` / `listPosts` re-read a cold or stale
cache from the network — for a browser account that drives the office browser, the owner's signed-in
session. Read them on the screen. Posting, replying, editing a profile and every other write act as
the owner in public and stay on the screen and the API (AGENT.md).
"""
import json
import re
import sys
import urllib.error
import urllib.request

API = "http://127.0.0.1:8986"
# adapters/http.py's own patterns: this file is piped into the container, so it imports nothing of the app's
SECRET_IN_URL = re.compile(r"([A-Za-z_]*(?:token|secret|key|signature|password|proof|sig|code))=[^&\s'\"]+", re.I)
SECRET_IN_HEADER = re.compile(r"\b(bearer|bot|oauth)\s+[^\s'\"\\]{12,}", re.I)    # a token, not a word


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            doc = json.loads(e.read() or b"{}")
        except ValueError:
            doc = {}
        # SocialError puts the person's sentence in `error` and what to do in `how` (adapters/base.py)
        said = doc.get("error") or doc.get("message") or doc.get("detail") or e.reason
        how = f" — {doc['how']}" if doc.get("how") else ""
        sys.exit(f"social-list: {said}{how} (HTTP {e.code})")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        sys.exit(f"social-list: the service does not answer on {API} ({getattr(e, 'reason', e)})")
    except ValueError:
        sys.exit("social-list: the answer was not JSON")


def main(argv):
    verb, args = (argv[0] if argv else ""), argv[1:]
    if verb == "accounts":
        data = call("POST", "/listAccounts", {"platform": args[0]} if args else {})
    elif verb == "activity":
        data = call("GET", "/api/activity")
    else:
        sys.exit(__doc__)
    # rows written before adapters/http.py dropped a token from a failed URL may still hold one
    print(SECRET_IN_HEADER.sub(r"\1 …", SECRET_IN_URL.sub(r"\1=…", json.dumps(data, ensure_ascii=False, indent=1))))


if __name__ == "__main__":
    main(sys.argv[1:])
