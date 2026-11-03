"""cli — «מסמכים שלי», the business's documents, for agents and for the person at the server's shell. Reads only.

The hooks pipe THIS file into the my-docs container (`dcx exec -T my-docs python - <verb> … <
apps/my-docs/cli.py`), so it runs from the checkout with no image rebuild. my-docs forwards `/api/…`
as-is to apitools' ledger, so these are the ledger's own answers.

    documents [N] [--type <t>] [--status <s>] [--customer <id>]   the newest N documents (default 20)
    show <id>                one document, with its lines
    events <id>              its audit trail
    customers                the customers
    items                    the items
    integrity                numbering continuity and the tamper chain (the ledger's /documents/verify;
                             it loads every issued PDF, and on an office with no signing certificate its
                             first call makes the development one — it changes no document)

Not here, on purpose: issue, cancel, pay, allocation (final or money); `send` (it marks a document
sent and e-mails nothing); and download — the first download of an issued document uses up its
«מקור» (AGENT.md).
"""
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "http://127.0.0.1:8000/api"
# A document id is letters, digits, `_` and `-` (`doc_` + hex). Anything else is refused: the
# pass-through decodes `%2F`, so `x/download` would reach the one GET that writes (it uses up «מקור»).
ID = re.compile(r"[A-Za-z0-9_-]{1,80}")


def get(path, params=None):
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    try:
        with urllib.request.urlopen(url, timeout=150) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            doc = json.loads(e.read() or b"{}")
        except ValueError:
            doc = {}
        sys.exit(f"my-docs: {doc.get('message') or doc.get('error') or e.reason} (HTTP {e.code})")
    except (urllib.error.URLError, TimeoutError, OSError) as e:      # a read timeout too, not a traceback
        sys.exit(f"my-docs: the service does not answer on {API} ({getattr(e, 'reason', e)})")
    except ValueError:
        sys.exit("my-docs: the answer was not JSON")


def main(argv):
    verb, args = (argv[0] if argv else ""), argv[1:]
    if verb == "documents":
        params, it = {"limit": 20}, iter(args)
        for a in it:
            if a in ("--type", "--status", "--customer"):
                value = next(it, "")
                if not value or value.startswith("--"):
                    sys.exit(f"my-docs: {a} needs a value")
                params["customer_id" if a == "--customer" else a[2:]] = value
            elif re.fullmatch(r"[0-9]{1,4}", a):
                params["limit"] = max(1, min(200, int(a)))
            else:
                sys.exit(f"my-docs: what is {a!r}?\n{__doc__}")
        data = get("/documents", params)
    elif verb in ("show", "events") and args:
        if not ID.fullmatch(args[0]):
            sys.exit(f"my-docs: {args[0]!r} is not a document id")
        doc = "/documents/" + args[0]
        data = get(doc if verb == "show" else doc + "/events")
    elif verb in ("customers", "items"):
        data = get("/" + verb)
    elif verb == "integrity":         # not `verify`: that name is the platform's health hook for every app
        data = get("/documents/verify")
    else:
        sys.exit(__doc__)
    print(json.dumps(data, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
