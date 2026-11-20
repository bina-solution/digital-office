"""cli — «מסמכים» for agents and for the person at the server's shell: one list over the issued and incoming documents.

The hooks pipe THIS file into the documents container (`dcx exec -T documents python - <verb> … < apps/documents/cli.py`),
so it runs from the checkout with no image rebuild and talks to the service on 127.0.0.1, with no address and no key.

    list [out|in|file] [N]   the newest N documents (default 20): issued, incoming, the office's files — or all
    show <id>                one document: the index row and the provider's own record
    search <words>           one search over both directions
    types                    the document types (data, not code)
    providers                which providers this office reads, and each one's last sync
    sync [local|indox|drive] [--accept-shrink]
                             read the providers now (reads only — it writes into no other app); a provider whose set
                             is half the list or less is refused and its rows kept, unless --accept-shrink
"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "http://127.0.0.1:8080"


def call(method, path, params=None, body=None):
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    data = json.dumps(body).encode() if body is not None else (b"" if method == "POST" else None)
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            sys.exit("documents: " + json.loads(e.read().decode("utf-8")).get("detail", f"HTTP {e.code}"))
        except ValueError:
            sys.exit(f"documents: HTTP {e.code}")
    except (urllib.error.URLError, OSError) as e:
        sys.exit(f"documents: the service does not answer ({e})")


def rows_out(rows):
    for r in rows:
        total = f"₪{r['total']:,.2f}" if isinstance(r.get("total"), (int, float)) else "—"
        arrow = {"in": "←", "out": "→"}.get(r["direction"], "·")      # «·» a file of the office's own («קבצים»)
        print(f"{arrow} {r['date'] or '—':10}  {r['type_name']:<16} {r['number'] or '—':<10} {total:>14}  "
              f"{(r['party'] or '—')[:30]:<30}  {r['state']}  [{r['id']}]")


def status_out(status):
    for s in status:
        print(f"  {s['provider']}: {s['said']} ({s['count']} מסמכים)")


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
        return 0
    verb, rest = argv[0], argv[1:]
    if verb == "list":
        params = {"limit": 20}
        for a in rest:
            if a in ("out", "in", "file"):
                params["direction"] = a
            elif a.isdigit():
                params["limit"] = int(a)
        d = call("GET", "/api/documents", params)["data"]
        rows_out(d["rows"])
        status_out(d["status"])
    elif verb == "show" and rest:
        print(json.dumps(call("GET", "/api/documents/" + urllib.parse.quote(rest[0], safe=""))["data"],
                         ensure_ascii=False, indent=1, default=str))
    elif verb == "search" and rest:
        d = call("GET", "/api/search", {"q": " ".join(rest)})["data"]
        rows_out(d["rows"])
        if not d["rows"]:
            print("לא נמצא")
    elif verb == "types":
        for t in call("GET", "/api/types")["data"]:
            print(f"{t['code']:<16} {t['name_he']:<16} {t['direction']}")
    elif verb == "providers":
        for p in call("GET", "/api/providers")["data"]:
            s = p.get("sync") or {}
            print(f"{p['id']:<6} {'מחובר' if p['bound'] else 'לא מחובר':<9} {p['title']} — {s.get('said', 'עוד לא סונכרן')}")
    elif verb == "sync":
        body = {"accept_shrink": True} if "--accept-shrink" in rest else {}
        named = [a for a in rest if not a.startswith("--")]
        if named:
            body["provider"] = named[0]
        for r in call("POST", "/api/sync", body=body)["data"]:
            print(f"{r['provider']}: " + (f"{r['count']} מסמכים (+{r['added']}, שונו {r['changed']}, ירדו {r['removed']})"
                                          if r["ok"] else f"{r.get('said') or 'לא סונכרן'}\n    (error: {r['error']})"))
    else:
        print(__doc__.strip())
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
