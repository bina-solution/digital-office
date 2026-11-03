"""cli — «טלגרם TV», the office's films from Telegram, for agents and for the person at the server's shell. Reads only.

The hooks pipe THIS file into the telegram-tv container (`dcx exec -T telegram-tv python - <verb> … <
apps/telegram-tv/cli.py`), so it runs from the checkout with no image rebuild, and talks to the
service's own API on 127.0.0.1.

    status                   the account and the client: connected, and is it working
    movies [query] [N]       the films it knows, matching a query (default 50)
    series                   what the app considers a show, with its episode count
    sync                     how the sync of the chats is doing

Refreshing (a full re-read of every chat) and probing a film's playback stay on the screen and the
API (AGENT.md).
"""
import json
import sys
import urllib.error
import urllib.request

API = "http://127.0.0.1:8982"


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
        sys.exit(f"telegram-tv: {doc.get('message') or doc.get('detail') or doc.get('error') or e.reason} (HTTP {e.code})")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        sys.exit(f"telegram-tv: the service does not answer on {API} ({getattr(e, 'reason', e)})")
    except ValueError:
        sys.exit("telegram-tv: the answer was not JSON")


def main(argv):
    verb, args = (argv[0] if argv else ""), argv[1:]
    if verb == "status":
        data = call("POST", "/status", {})
    elif verb == "movies":
        body = {"q": args[0] if args else "", "limit": 50}
        if len(args) > 1:
            try:
                body["limit"] = max(1, min(1000, int(args[1])))
            except ValueError:
                sys.exit(f"telegram-tv: a count is a number, not {args[1]!r}")
        data = call("POST", "/listMovies", body)
    elif verb == "series":
        data = call("GET", "/api/series")
    elif verb == "sync":
        data = call("GET", "/api/sync/status")
    else:
        sys.exit(__doc__)
    print(json.dumps(data, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
