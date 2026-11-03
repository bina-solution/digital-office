"""cli — the office's websites, for agents and for the person at the server's shell. Reads, and one check.

The hooks pipe THIS file into the sites container (`dcx exec -T sites python - <verb> … <
apps/sites/cli.py`), so it runs from the checkout with no image rebuild, and talks to the service's
own API on 127.0.0.1 with no address and no key on a line.

    ls                       every site: its state, its address, its last check
    show <id>                one site, whole
    findings <id>            what its last scan found
    uptime <id> [hours]      its uptime checks (default 24 h)
    logs <id> [lines]        its container's log (default 200 lines)
    probe <id>               one uptime check now — the only call here that writes: it records the
                             sample, and a change of state notifies, as the scheduler's check would

Deploy, start, stop, restart and publish change a live site: they stay on the screen and the API
(AGENT.md).
"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "http://127.0.0.1:8979"


def call(method, path, params=None):
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, data=b"" if method == "POST" else None, method=method)
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        try:
            doc = json.loads(e.read() or b"{}")
        except ValueError:
            doc = {}
        sys.exit(f"sites: {doc.get('message') or doc.get('detail') or doc.get('error') or e.reason} (HTTP {e.code})")
    except (urllib.error.URLError, TimeoutError, OSError) as e:      # a read timeout too, not a traceback
        sys.exit(f"sites: the service does not answer on {API} ({getattr(e, 'reason', e)})")
    try:
        return json.loads(body or b"{}")
    except ValueError:
        return body.decode("utf-8", "replace")


def show(data):
    print(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=1))


def site(sid):
    return "/api/sites/" + urllib.parse.quote(sid, safe="")


def main(argv):
    verb, args = (argv[0] if argv else ""), argv[1:]
    if verb == "ls":
        show(call("GET", "/api/overview"))
    elif verb == "show" and args:
        show(call("GET", site(args[0])))
    elif verb == "findings" and args:
        show(call("GET", site(args[0]) + "/findings"))
    elif verb == "uptime" and args:
        show(call("GET", site(args[0]) + "/uptime", {"hours": args[1] if len(args) > 1 else 24}))
    elif verb == "logs" and args:
        show(call("GET", site(args[0]) + "/logs", {"lines": args[1] if len(args) > 1 else 200}))
    elif verb == "probe" and args:
        show(call("POST", site(args[0]) + "/probe"))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
