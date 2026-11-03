"""cli — «כל מקביל», what ran at once, for agents and for the person at the server's shell. Reads only.

The hooks pipe THIS file into the any-concurrency container (`dcx exec -T any-concurrency python -
<verb> … < apps/any-concurrency/cli.py`), so it runs from the checkout with no image rebuild, and
talks to the service's own API on 127.0.0.1.

    sources                  each lane: enabled, answering, its last event
    queue                    the n8n queue now
    executions [hours]       n8n executions in the window (default 1 h, at most 336)
    spans [hours] [sources]  every span of the window (default 1 h; sources comma-separated)

A restart empties the memory-only lanes (the edge, docker, posted spans): an empty lane right after
one is not an idle office.
"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "http://127.0.0.1:8080"


def get(path, params=None):
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            said = json.loads(e.read() or b"{}").get("detail")
        except (ValueError, AttributeError):
            said = None
        sys.exit(f"any-concurrency: {said or e.reason} (HTTP {e.code})")
    except (urllib.error.URLError, TimeoutError, OSError) as e:      # a read timeout too, not a traceback
        sys.exit(f"any-concurrency: the service does not answer on {API} ({getattr(e, 'reason', e)})")
    except ValueError:
        sys.exit("any-concurrency: the answer was not JSON")


def hours(args, at=0):
    try:
        return max(0.01, min(336.0, float(args[at]))) if len(args) > at else 1.0
    except ValueError:
        sys.exit(f"any-concurrency: hours is a number, not {args[at]!r}")


def main(argv):
    verb, args = (argv[0] if argv else ""), argv[1:]
    if verb == "sources":
        data = get("/api/sources")
    elif verb == "queue":
        data = get("/api/queue")
    elif verb == "executions":
        data = get("/api/executions", {"hours": hours(args)})
    elif verb == "spans":
        params = {"hours": hours(args)}
        if len(args) > 1:
            params["sources"] = args[1]
        data = get("/api/spans", params)
    else:
        sys.exit(__doc__)
    print(json.dumps(data, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
