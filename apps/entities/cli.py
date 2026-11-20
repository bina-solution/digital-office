#!/usr/bin/env python3
"""«ישויות» from the shell — runs inside the app's container, against its API on loopback (hooks/cli):

  ./bbox entities list [role] [--q <word>] [--kind person|organization]
  ./bbox entities show <id>
  ./bbox entities add <person|organization> "<name>" [--role <role>]... [<field>=<value>]... [<role>.<field>=<value>]...
  ./bbox entities set <id> [name="<name>"] [kind=person|organization] [<field>=<value>]... [<role>.<field>=<value>]...
                                                               (an empty value removes; a kind its roles fit)
  ./bbox entities role <id> <role> [<field>=<value>]...        add a role, or change its fields
  ./bbox entities unrole <id> <role>
  ./bbox entities relate <person-id> works_at <organization-id> ["<title>"]   ·  relate <id> handles <id>
  ./bbox entities party <id>                                   the block a document prints
  ./bbox entities patterns                                     the kinds, the roles and their fields
  ./bbox entities history [<id>]

Roles: company · customer · supplier · salesperson · contact. One line per entity: id | kind | name | roles | key.
The documents' own old list of customers moves here by itself: the ledger hands it over the first time it finds
«ישויות» answering (apps/apitools/src/doc_data/entities.py, «the customers»).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API = os.environ.get("ENTITIES_SELF_URL", "http://127.0.0.1:8999").rstrip("/")


def call(method: str, path: str, body=None):
    req = urllib.request.Request(API + path, method=method,
                                 data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None,
                                 headers={"content-type": "application/json", "x-actor": "cli"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode() or "{}").get("detail")
        except ValueError:
            detail = ""
        sys.exit(f"[entities] {e.code}: {detail or e.reason}")
    except urllib.error.URLError as e:
        sys.exit(f"[entities] {API} did not answer: {e.reason}")


def line(e: dict) -> str:
    return " | ".join([e["id"], e["kind"], e["name"], ",".join(e.get("roles") or []) or "-", e.get("key") or "-"])


def pairs(args: list[str]) -> tuple[dict, dict, str | None]:
    """field=value and role.field=value → (entity fields, {role: fields}, name)."""
    fields, roles, name = {}, {}, None
    for a in args:
        if "=" not in a:
            sys.exit(f"[entities] expected field=value, got {a!r}")
        k, v = a.split("=", 1)
        if k == "name":
            name = v
        elif "." in k:
            role, f = k.split(".", 1)
            roles.setdefault(role, {})[f] = v
        else:
            fields[k] = v
    return fields, roles, name


def show(e: dict) -> None:
    print(line({**e, "roles": sorted(e["roles"]), "key": ""}).rstrip(" | -"))
    for k, v in e["fields"].items():
        print(f"  {k}: {v}")
    for role, f in e["roles"].items():
        print(f"  [{role}]" + "".join(f"  {k}: {v}" for k, v in f.items()))
    for r in e["relations"]:
        arrow = "→" if r["direction"] == "out" else "←"
        print(f"  {r['kind']} {arrow} {r['other']['name']} ({r['other']['id']}){' · ' + r['title'] if r['title'] else ''}")
    if e.get("archived"):
        print("  (archived)")


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("help", "-h", "--help"):
        print(__doc__)
        return 0
    verb, rest = argv[0], argv[1:]
    seg = lambda s: urllib.parse.quote(str(s), safe="")    # noqa: E731 — an id or a role as one path segment
    if verb == "list":
        role = rest[0] if rest and not rest[0].startswith("--") else ""
        q = rest[rest.index("--q") + 1] if "--q" in rest else ""
        kind = rest[rest.index("--kind") + 1] if "--kind" in rest else ""
        rows = call("GET", "/api/entities?" + urllib.parse.urlencode({"role": role, "q": q, "kind": kind}))["entities"]
        for e in rows:
            print(line(e))
        print(f"({len(rows)})")
    elif verb == "show" and rest:
        show(call("GET", f"/api/entities/{seg(rest[0])}"))
    elif verb == "add" and len(rest) >= 2:
        kind, name, tail = rest[0], rest[1], rest[2:]
        wanted = [tail[i + 1] for i, a in enumerate(tail) if a == "--role" and i + 1 < len(tail)]
        tail = [a for i, a in enumerate(tail) if a != "--role" and (i == 0 or tail[i - 1] != "--role")]
        fields, roles, _ = pairs(tail)
        for r in wanted:
            roles.setdefault(r, {})
        show(call("POST", "/api/entities", {"kind": kind, "name": name, "fields": fields, "roles": roles}))
    elif verb == "set" and rest:
        eid = seg(rest[0])
        fields, roles, name = pairs(rest[1:])
        kind = fields.pop("kind", None)           # `kind=organization`: the kind, corrected — refused while a role
        e = None                                  # or a «works at» would no longer fit
        if fields or name is not None or kind is not None:
            e = call("PATCH", f"/api/entities/{eid}", {"fields": fields, **({"name": name} if name is not None else {}),
                                                       **({"kind": kind} if kind is not None else {})})
        for role, f in roles.items():
            e = call("PUT", f"/api/entities/{eid}/roles/{seg(role)}", {"fields": f})
        show(e or call("GET", f"/api/entities/{eid}"))
    elif verb == "role" and len(rest) >= 2:
        fields, _, _ = pairs(rest[2:])
        show(call("PUT", f"/api/entities/{seg(rest[0])}/roles/{seg(rest[1])}", {"fields": fields}))
    elif verb == "unrole" and len(rest) == 2:
        show(call("DELETE", f"/api/entities/{seg(rest[0])}/roles/{seg(rest[1])}"))
    elif verb == "relate" and len(rest) >= 3:
        show(call("POST", "/api/relations", {"from": rest[0], "kind": rest[1], "to": rest[2],
                                             "title": rest[3] if len(rest) > 3 else ""}))
    elif verb == "party" and rest:
        print(json.dumps(call("GET", f"/api/entities/{seg(rest[0])}/party"), ensure_ascii=False, indent=2))
    elif verb == "patterns":
        p = call("GET", "/api/patterns")
        for k, r in p["roles"].items():
            print(f"{k} «{r['he']}» ({'/'.join(r['kinds'])}): " + ", ".join(f["key"] for f in r["fields"]))
    elif verb == "history":
        q = f"?entity={seg(rest[0])}" if rest else ""
        for ev in call("GET", "/api/events" + q)["events"]:
            print(f"{ev['at']} {ev['kind']} {ev.get('entity_id') or ''} {ev['summary']} ({ev['actor']})")
            for k, x in (ev.get("detail") or {}).items():       # a field's before → after; a role's, one level down
                if isinstance(x, list) and len(x) == 2:
                    print(f"    {k}: {x[0] or '-'} → {x[1] or '-'}")
                elif isinstance(x, dict):
                    for kk, xx in x.items():
                        print(f"    {k}.{kk}: {xx[0] or '-'} → {xx[1] or '-'}" if isinstance(xx, list) and len(xx) == 2
                              else f"    {k}.{kk}: {xx}")
                else:
                    print(f"    {k}: {x}")
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
