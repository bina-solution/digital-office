"""cli — the office's security picture, for agents and for the person at the server's shell. Reads only.

The hooks pipe THIS file into the security container (`dcx exec -T security python - <verb> … <
platform-base/security/cli.py`), so it runs from the checkout with no image rebuild, and talks to the
service's own API on 127.0.0.1 with no address and no key on a line.

    summary [hours]          requests, addresses, bans, outbound — the numbers (default 24 h)
    inbound [hours]          who reached the office, by address: place, network, apps, users
    ip <address>             one address: its hits, sign-ins and bans
    outbound [hours]         where the office reached out to, and who called
    bans                     the mode, the jails, the active bans
    herd                     every linked office's summary

Banning, rules and the enforce mode stay on the screen and the API (AGENT.md).
"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "http://127.0.0.1:8995"


def get(path, params=None):
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            doc = json.loads(e.read() or b"{}")
        except ValueError:
            doc = {}
        sys.exit(f"security: {doc.get('message') or doc.get('detail') or doc.get('error') or e.reason} (HTTP {e.code})")
    except (urllib.error.URLError, TimeoutError, OSError) as e:      # a read timeout too, not a traceback
        sys.exit(f"security: the service does not answer on {API} ({getattr(e, 'reason', e)})")
    except ValueError:
        sys.exit("security: the answer was not JSON")


def hours(args, default=24):
    return {"hours": args[0] if args else default}


def main(argv):
    verb, args = (argv[0] if argv else ""), argv[1:]
    if verb == "summary":
        data = get("/api/summary", hours(args))
    elif verb == "inbound":
        data = get("/api/inbound", hours(args))
    elif verb == "ip" and args:
        data = get("/api/inbound/" + urllib.parse.quote(args[0], safe=""))
    elif verb == "outbound":
        data = get("/api/outbound", hours(args))
    elif verb == "bans":
        data = get("/api/bans")
    elif verb == "herd":
        data = get("/api/herd")
    else:
        sys.exit(__doc__)
    print(json.dumps(data, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
