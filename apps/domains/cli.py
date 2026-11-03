"""cli — the office's domains, for agents and for the person at the server's shell. It writes nothing.

The hooks pipe THIS file into the domains container (`dcx exec -T domains python - <verb> … <
apps/domains/cli.py`), so it runs from the checkout with no image rebuild, and talks to the service's
canonical ops on 127.0.0.1 — the calls other apps make — with no address and no key on a line.

    accounts                 the domain accounts (API or browser), not probed
    ls [account]             the domains: of one account, or every domain the office knows
    show <domain> [account]  one domain: registrar, expiry, nameservers, its state here
    records <domain> [account]   its DNS records, as the account's provider reports them
    whois <domain>           ONE live query of the public registry (never in a loop: the registry
                             forbids high-volume querying; `show` carries the last watched record)

For a BROWSER account (a registrar with no API, such as InterNIC) `ls <account>`, `show` and
`records` drive the office's one browser — the same one the owner watches — to read the registrar's
panel; without `account`, the active account is used. Writes stay out of the CLI on purpose: a
record written through a panel needs a person's watched consent, and a money or irreversible op an
exact `confirm` (AGENT.md, Traps).
"""
import json
import sys
import urllib.error
import urllib.request

API = "http://127.0.0.1:8980"


def op(name, body=None):
    """POST /<name> with the body — or, with none, GET /<name>."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + "/" + name, data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            doc = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            doc = json.loads(e.read() or b"{}")
        except ValueError:
            doc = {}
        sys.exit(f"domains: {doc.get('error') or doc.get('detail') or e.reason} (HTTP {e.code})")
    except (urllib.error.URLError, TimeoutError, OSError) as e:      # a read timeout too, not a traceback
        sys.exit(f"domains: the service does not answer on {API} ({getattr(e, 'reason', e)})")
    except ValueError:
        sys.exit("domains: the answer was not JSON")
    if not doc.get("ok", True):
        sys.exit(f"domains: {doc.get('error') or doc}")
    data = doc.get("data", doc)
    # A read that failed inside an op can still come back as `ok` with the error response as its
    # data (`{"status_code": 502, "body": "…"}`, app.py `_op_get_domain`): say it failed, never print
    # it as an answer.
    if isinstance(data, dict) and "status_code" in data and "body" in data:
        sys.exit(f"domains: the read failed (HTTP {data['status_code']}): {data['body']}")
    # …and so can one that reports its own failure beside an empty list (`{"error": …, "domains": []}`)
    if isinstance(data, dict) and (data.get("error") or data.get("reason")):
        sys.exit(f"domains: the read failed: {data.get('error') or data.get('reason')}")
    return data


def show(data):
    print(json.dumps(data, ensure_ascii=False, indent=1))


def main(argv):
    verb, args = (argv[0] if argv else ""), argv[1:]
    if verb == "accounts":
        # unprobed (probe=1 would ask every account, browser ones too), and not through listAccounts:
        # its cache key holds no probe, so unprobed rows would replace the probed ones the screen reads
        show(op("connections?probe=0"))
    elif verb == "ls":
        show(op("listDomains", {"account": args[0]} if args else {}))
    elif verb in ("show", "records") and args:
        body = {"domain": args[0], **({"account": args[1]} if len(args) > 1 else {})}
        show(op("getDomain" if verb == "show" else "listRecords", body))
    elif verb == "whois" and args:
        show(op("whois", {"domain": args[0]}))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
