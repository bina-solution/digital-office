"""cli — the InterNIC provider at the office's shell: ./bbox domain-internic <verb> (== dgo domain-internic).

The hooks pipe THIS file into a container and it talks to the provider's domain-provider.v1 ops: into
domain-internic's own container (127.0.0.1:8981) on the office that runs it, or — on an office that does
not — into the credential plane's container, with DOMAIN_INTERNIC_API set to the linked office's door
(scripts/herd_home.py names it, as it does for Plane). Same verbs, same answers, either way.

    status                       signed in? credential there? which writes are the office's?
    login                        sign the office browser in by itself (one attempt, never a retry)
    domains                      the account's domains, read off the portal
    zone <domain>                one zone, read off the portal's own editor
    add-record <domain> <type> <name> <value> [--ttl N] [--consent "<who>: <why>"]
                                 one record, created through the portal and READ BACK. Without --consent
                                 it runs only if the office has already seen this action succeed once.
    verified [create]            has the office seen this action succeed (its own from now on)?
    flow                         see hooks/flow (the event stream, live)

Exit status: 0 when the provider answered ok, 1 when it answered a refusal (printed), 2 when it could
not be asked.
"""
import json
import os
import sys
import urllib.error
import urllib.request

API = (os.environ.get("DOMAIN_INTERNIC_API") or "http://127.0.0.1:8981").rstrip("/")


def call(method, path, body=None, timeout=300):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read() or b"{}")
        except ValueError:
            return {"ok": False, "state": "http_error", "error": f"HTTP {e.code}"}
    except (urllib.error.URLError, OSError) as e:
        print(f"domain-internic: the provider did not answer at {API}: {e}", file=sys.stderr)
        sys.exit(2)


def show(doc):
    print(json.dumps(doc, ensure_ascii=False, indent=1))
    return 0 if doc.get("ok") else 1


def flag(args, name, default=None):
    if name in args:
        i = args.index(name)
        if i + 1 >= len(args):
            print(f"domain-internic: {name} needs a value", file=sys.stderr)
            sys.exit(2)
        value = args[i + 1]
        del args[i:i + 2]
        return value
    return default


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    verb, args = argv[0], list(argv[1:])
    if verb == "status":
        st = call("GET", "/api/state")
        sess = st.get("session") or {}
        write = st.get("write") or {}
        print(f"session    {'signed in' if sess.get('authenticated') else sess.get('state')}  {sess.get('url') or ''}")
        cred = st.get("credential") or {}
        print(f"credential domain-internic-login: {cred.get('status') or ('not declared' if cred.get('known') else 'unknown')}"
              f"{'' if cred.get('rows') else '  (fill it once in חיבורים ומפתחות)'}")
        print(f"mailbox    {'named' if st.get('mail_connection') else 'not named (DOMAIN_INTERNIC_MAIL_CONNECTION)'}")
        print(f"writes     {'the office may write' if write.get('enabled') else write.get('state')}  {json.dumps(write.get('watched') or {})}")
        return 0 if st.get("ok") else 1
    if verb == "login":
        return show(call("POST", "/api/login", {}))
    if verb == "domains":
        return show(call("GET", "/api/domains"))
    if verb == "zone":
        if not args:
            print("usage: zone <domain>", file=sys.stderr)
            return 2
        return show(call("GET", f"/api/zones/{args[0]}"))
    if verb == "add-record":
        ttl = flag(args, "--ttl", "3600")
        consent = flag(args, "--consent")
        if len(args) != 4:
            print('usage: add-record <domain> <type> <name> <value> [--ttl N] [--consent "<who>: <why>"]',
                  file=sys.stderr)
            return 2
        domain, rtype, name, value = args
        body = {"action": "create", "domain": domain, "type": rtype, "name": name, "value": value, "ttl": ttl}
        if consent:
            body["consented_by"] = consent
        return show(call("POST", "/api/records", body, timeout=600))
    if verb == "verified":
        return show(call("GET", f"/api/verified?action={(args or ['create'])[0]}"))
    print(f"domain-internic: unknown verb {verb!r} (status, login, domains, zone, add-record, verified, flow)",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
