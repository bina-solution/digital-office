"""cli — «התראות», the office's notice board, for agents and for the person at the server's shell. Reads only.

The hooks pipe THIS file into the notifications container (`dcx exec -T notifications python - <verb> …
< platform-base/notifications/cli.py`), so it runs from the checkout with no image rebuild, and talks
to the service's own API on 127.0.0.1.

    list [N] [--unread] [--source <s>] [--level error|warning|info]   the newest N notices (default 20)
    show <id>                one notice, whole
    unread                   how many are unread
    stats                    counts by source and level

Marking read, deleting and posting stay on the screen and the API (AGENT.md): a notice posted at
level `error` rings every subscribed phone.
"""
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "http://127.0.0.1:8977"


def get(path, params=None):
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            doc = json.loads(e.read() or b"{}")
        except ValueError:
            doc = {}
        sys.exit(f"notifications: {doc.get('message') or doc.get('error') or e.reason} (HTTP {e.code})")
    except (urllib.error.URLError, TimeoutError, OSError) as e:      # a read timeout too, not a traceback
        sys.exit(f"notifications: the service does not answer on {API} ({getattr(e, 'reason', e)})")
    except ValueError:
        sys.exit("notifications: the answer was not JSON")


def main(argv):
    verb, args = (argv[0] if argv else ""), argv[1:]
    if verb == "list":
        params, it = {"limit": 20}, iter(args)
        for a in it:
            if a == "--unread":
                params["unread"] = 1
            elif a in ("--source", "--level"):
                value = next(it, "")
                if not value or value.startswith("--"):
                    sys.exit(f"notifications: {a} needs a value")
                # the API ignores a level it does not know and answers everything: refuse it here
                if a == "--level" and value not in ("error", "warning", "info"):
                    sys.exit(f"notifications: a level is error, warning or info, not {value!r}")
                params[a[2:]] = value
            elif re.fullmatch(r"[0-9]{1,4}", a):
                params["limit"] = max(1, min(500, int(a)))
            else:
                sys.exit(f"notifications: what is {a!r}?\n{__doc__}")
        data = get("/api/notifications", params)
    elif verb == "show" and args:
        data = get("/api/notifications/" + urllib.parse.quote(args[0], safe=""))
    elif verb == "unread":
        data = get("/api/notifications/unread-count")
    elif verb == "stats":
        data = get("/api/notifications/stats")
    else:
        sys.exit(__doc__)
    print(json.dumps(data, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
