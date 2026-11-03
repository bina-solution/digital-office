"""cad-api's own CLI, run inside its container by `bbox cad <verb>` (hooks/): the same doors as the API.

    families [--json]
    takeoff <family> k=v … [material=galvanized sheet=48x120 qty=1 kerf=0] [--json]
    model <family> step|glb k=v …          the file on stdout
    verify                                 health + one known takeoff (turtle 35 × 32 = one sheet, MEET-41)
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8996"
OPTS = ("material", "sheet", "qty", "kerf")


def call(method: str, path: str, body=None, raw: bool = False):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.read() if raw else json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            why = json.loads(e.read()).get("detail")
        except ValueError:
            why = e.reason
        sys.exit(f"cad: {why}")
    except OSError as e:
        sys.exit(f"cad-api does not answer: {e}")


def kv(words):
    params, opts = {}, {}
    for w in words:
        if "=" not in w:
            sys.exit(f"cad: {w!r} is not key=value")
        k, v = w.split("=", 1)
        if k == "flues":
            v = json.loads(v)
        (opts if k in OPTS else params)[k] = v
    body = {"params": params, "qty": int(opts.get("qty", 1)), "kerf": float(opts.get("kerf", 0)),
            "sheet": {"material": opts.get("material", "galvanized")}}
    if "sheet" in opts:
        w, h = opts["sheet"].lower().split("x")
        body["sheet"].update({"w": float(w), "h": float(h)})
    return body


def show_takeoff(t: dict) -> None:
    print(f"{t['family']} {', '.join(f'{k}={v:g}' for k, v in t['params'].items() if isinstance(v, float))} · "
          f"{t['material']} · ×{t['qty']}")
    for p in t["pieces"]:
        print(f"  cut {p['qty']:>2} × {p['name']:<18} {p['w']:g} × {p['h']:g}")
    for i, s in enumerate(t["sheets"], 1):
        print(f"  sheet {i}: {s['w']:g}×{s['h']:g}, {len(s['placed'])} pieces, {s['fill']:.0%} used")
    for b in t["bom"]:
        print(f"  BOM {b['qty']:g} {b['unit']} {b['item']}")
    for n in t["notes"]:
        print(f"  note: {n}")
    for e in t["errors"]:
        print(f"  ERROR: {e}")


def main(argv) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    verb, rest = argv[0], argv[1:]
    as_json = "--json" in rest
    rest = [w for w in rest if w != "--json"]
    if verb == "families":
        fams = call("GET", "/api/families")["families"]
        if as_json:
            print(json.dumps(fams, ensure_ascii=False))
        for f in [] if as_json else fams:
            print(f"{f['id']:<8} {f['title']['en']} — " + ", ".join(
                f"{p['key']}" + ("" if p.get("default") is None else f"={p['default']}") for p in f["params"]))
            print(f"         {f['source']}")
        return 0
    if verb == "takeoff" and rest:
        t = call("POST", f"/api/families/{rest[0]}/takeoff", kv(rest[1:]))
        print(json.dumps(t, ensure_ascii=False)) if as_json else show_takeoff(t)
        return 1 if t["errors"] else 0
    if verb == "model" and len(rest) >= 2:
        body = kv(rest[2:])
        sys.stdout.buffer.write(call("POST", f"/api/families/{rest[0]}/model?format={rest[1]}", {"params": body["params"]}, raw=True))
        return 0
    if verb == "verify":
        h = call("GET", "/healthz")
        print(f"cad-api up · families {', '.join(h['families'])} · build123d {h['build123d']}")
        t = call("POST", "/api/families/turtle/takeoff", {"params": {"L": 35, "W": 32}})
        ok = len(t["sheets"]) == 1 and not t["errors"]
        print(f"turtle 35×32 → {len(t['sheets'])} sheet(s) in {t['ms']} ms "
              f"({'as Alan said, MEET-41 [31:03]' if ok else 'Alan said ONE sheet'})")
        return 0 if ok and not str(h["build123d"]).startswith("unavailable") else 1
    sys.exit(f"cad: unknown verb {verb!r} — {__doc__.strip().splitlines()[0]}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
