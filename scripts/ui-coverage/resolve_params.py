#!/usr/bin/env python3
"""
resolve_params.py — find real ids for the parameterised routes, host-side.

/repos/:repo, /repos/:repo/documents/:id, /folder/{id}, /message/{id} can't be visited
blind. This asks each app's own API for a live id and writes ui-params.json, which
capture.py substitutes into URLs and frame_src before deciding whether to skip.

Host-side on purpose: an in-browser fetch through the console reverse proxy came back
empty, and the map must not stay blocked on that. Here we talk to each container directly.

Also seeds INDOX documents when the repo is empty — most of INDOX's routes are
document-shaped, so an empty repo makes them permanently unreachable. The full
`bbox indox demo run` path drives the whole n8n sync pipeline; this writes the same kind
of rows straight through the documents upsert API, which is all the UI map needs.

Run: python3 scripts/ui-coverage/resolve_params.py [--data data/browser42]
"""
from __future__ import annotations
# Hebrew output: python defaults stdout to the ANSI codepage on Windows (cp1255) and dies
# with UnicodeEncodeError. Linux/macOS are already UTF-8 — a no-op there.
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"): _sys.stdout.reconfigure(encoding="utf-8")

import argparse
import json
import re
import subprocess
from pathlib import Path


def _deployment_name() -> str:
    """Match ci-ui-map.sh: read DEPLOYMENT_NAME from .env, default bina-deployment.

    The old hardcoded "shlomo-laptop" is only right on one dev laptop; in CI the
    deployment name comes from ci-env.sh, so container lookups (`<svc>-<DN>`) silently
    resolved to nothing and every param stayed unresolved. Discover it instead.
    """
    try:
        for ln in Path(".env").read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"^DEPLOYMENT_NAME=(.*)$", ln.strip())
            if m:
                return m.group(1).strip().strip('"') or "bina-deployment"
    except Exception:
        pass
    return "bina-deployment"


DN = _deployment_name()


def _container(service: str) -> str:
    """Real container name for a compose service — `<svc>` or `<svc>-<DN>`, whichever
    docker actually shows. Robust to deployment-name drift between laptop and CI."""
    try:
        names = subprocess.run(["docker", "ps", "--format", "{{.Names}}"],
                               capture_output=True, timeout=15).stdout.decode().split()
    except Exception:
        names = []
    for cand in (f"{service}-{DN}", service):
        if cand in names:
            return cand
    for n in names:  # last resort: prefix match (`<svc>-<something>`)
        if n == service or n.startswith(f"{service}-"):
            return n
    return f"{service}-{DN}"

INDOX_DOCS = [
    {"ID": "demo-inv-1001", "TYPE": "INVOICE", "SHORT_DOC_ID": "06146",
     "COMPANY_DOC_ID": "SI256006146", "COMPANY_ID": "570043745",
     "COMPANY_NAME": "סבח סוכנויות בע\"מ", "NAME": "חשבונית מס 06146",
     "DOC_DATE": "12/06/2026", "DOC_TOTAL_AMOUNT": "5400"},
    {"ID": "demo-shp-5001", "TYPE": "SHIPMENT", "SHORT_DOC_ID": "05179",
     "COMPANY_DOC_ID": "S0125005179", "COMPANY_ID": "513498345",
     "COMPANY_NAME": "פוליראן תעשיות", "NAME": "תעודת משלוח 05179",
     "DOC_DATE": "03/06/2026", "SHIPMENT_DOC_ID": "S0125005179"},
    {"ID": "demo-ord-7001", "TYPE": "ORDER", "SHORT_DOC_ID": "10004",
     "COMPANY_DOC_ID": "PO25010004", "COMPANY_ID": "511301129",
     "COMPANY_NAME": "אגן שיווק", "NAME": "הזמנת רכש 10004",
     "DOC_DATE": "28/05/2026", "PURCHASE_ID": "PO25010004"},
    {"ID": "demo-inv-1002", "TYPE": "INVOICE", "SHORT_DOC_ID": "00818",
     "COMPANY_DOC_ID": "SI266000818", "COMPANY_ID": "512093170",
     "COMPANY_NAME": "ישראל קרטון", "NAME": "חשבונית מס 00818",
     "DOC_DATE": "14/05/2026", "DOC_TOTAL_AMOUNT": "12800"},
    {"ID": "demo-inv-1003", "TYPE": "INVOICE", "SHORT_DOC_ID": "01661",
     "COMPANY_DOC_ID": "SI256001661", "COMPANY_ID": "511020471",
     "COMPANY_NAME": "מ.ש. הכהנים בע\"מ", "NAME": "חשבונית מס 01661",
     "DOC_DATE": "22/04/2026", "DOC_TOTAL_AMOUNT": "3120"},
]


def pyrun(container: str, code: str, timeout: int = 60) -> str:
    try:
        r = subprocess.run(["docker", "exec", _container(container), "python3", "-c", code],
                           capture_output=True, timeout=timeout)
        return r.stdout.decode("utf-8", "replace").strip()
    except Exception:
        return ""


def indox_probe(build_code, timeout: int = 60) -> str:
    """Run an INDOX probe, resilient to the app refusing its own loopback.

    incoming-documents' gunicorn answers peers on :8080 but REFUSES connections to
    127.0.0.1 from inside its own container (a hairpin/bind quirk — the healthcheck is
    `unhealthy` for the same reason). So probing it in-container came back empty and every
    :type/:name stayed unresolved → the extraction detail screens were skipped. Probe it the
    way its real clients do: first try in-container loopback (works for the other apps), then
    fall back to a PEER (the console container) hitting it by compose DNS `incoming-documents`,
    which is exactly the path the console reverse proxy uses and is proven to answer 200.

    `build_code(base_url)` returns the probe code for a given base URL; the last non-empty
    JSON line of stdout is returned.
    """
    for exec_container, base in (("incoming-documents", "http://127.0.0.1:8080/incomingDocuments"),
                                 ("console", "http://incoming-documents:8080/incomingDocuments")):
        out = pyrun(exec_container, build_code(base), timeout=timeout)
        if out:
            try:
                got = json.loads(out.splitlines()[-1])
                if got:
                    return out
            except Exception:
                pass
    return ""


def indox(subs: dict) -> None:
    # NOTE: INDOX mounts its API under INCOMING_DOCS_API_PREFIX (/incomingDocuments).
    # A bare /repos hits the SPA fallback and returns HTML, which reads as "no data".
    def build(B):
        return f'''
import urllib.request, json
B = "{B}"
repos = json.loads(urllib.request.urlopen(B + "/repos", timeout=15).read()).get("repos", [])
if not repos:
    print(json.dumps({{}})); raise SystemExit
name = repos[0].get("name")
D = f"{{B}}/repos/{{name}}/documents"
q = urllib.request.Request(D + "/query", data=b"{{}}",
                           headers={{"Content-Type": "application/json"}})
rows = json.loads(urllib.request.urlopen(q, timeout=20).read())
rows = rows.get("documents") or rows.get("items") or rows.get("rows") or []
if not rows:
    body = json.dumps({json.dumps(INDOX_DOCS, ensure_ascii=False)}, ensure_ascii=False).encode()
    rq = urllib.request.Request(D, data=body, method="PUT",
                                headers={{"Content-Type": "application/json"}})
    urllib.request.urlopen(rq, timeout=30).read()
    rows = json.loads(urllib.request.urlopen(q, timeout=20).read())
    rows = rows.get("documents") or rows.get("items") or rows.get("rows") or []
out = {{":repo": name}}
if rows:
    doc = rows[0]
    for k in ("ID", "id", "pk"):
        if doc.get(k):
            out[":id"] = str(doc[k]); break
print(json.dumps(out, ensure_ascii=False))
'''
    out = indox_probe(build)
    try:
        got = json.loads(out.splitlines()[-1]) if out else {}
    except Exception:
        got = {}
    if got:
        subs["incoming-documents"] = got


def indox_extraction(subs: dict) -> None:
    """Resolve a real doc for the extraction DETAIL route /extraction/:type/:name.

    This is the crown-jewel INDOX screen — the bounding-box overlay, the OCR
    character-recognition overlay and the original-document preview all live here as
    tab panes. Its route carries TWO params (:type, :name); the dataset endpoint returns
    docs whose id is "<type>/<file>", so split that into the two substitutions the
    capture driver needs. Without this the route matches the leftover ':' and is skipped,
    which is exactly how the richest screens went uncaptured.
    """
    def build(B):
        return f'''
import urllib.request, json
B = "{B}"
d = json.loads(urllib.request.urlopen(B + "/extraction/dataset", timeout=25).read())
docs = d.get("docs") or []
out = {{}}
if docs:
    doc = docs[0]
    did = doc.get("id") or ""
    typ = doc.get("type") or (did.split("/", 1)[0] if "/" in did else "")
    name = did.split("/", 1)[1] if "/" in did else (doc.get("file") or "")
    if typ and name:
        out[":type"] = typ
        out[":name"] = name
print(json.dumps(out, ensure_ascii=False))
'''
    out = indox_probe(build)
    try:
        got = json.loads(out.splitlines()[-1]) if out else {}
    except Exception:
        got = {}
    if got:
        subs.setdefault("incoming-documents", {}).update(got)


def simple(subs: dict, app: str, container: str, port: int,
           path: str, key: str, placeholder: str, id_keys: tuple) -> None:
    code = (f'import urllib.request,json;'
            f'd=json.loads(urllib.request.urlopen("http://127.0.0.1:{port}{path}",timeout=12).read());'
            f'rows=d.get("{key}") if isinstance(d,dict) else d;'
            f'print(json.dumps(rows[0] if rows else None,ensure_ascii=False))')
    out = pyrun(container, code)
    try:
        row = json.loads(out.splitlines()[-1]) if out else None
    except Exception:
        row = None
    val = None
    if isinstance(row, str):
        val = row
    elif isinstance(row, dict):
        for k in id_keys:
            if row.get(k) not in (None, ""):
                val = str(row[k])
                break
        if val is None:  # fallback: any id-like field (fileId, folderId, …)
            for k, v in row.items():
                if "id" in k.lower() and v not in (None, "") and isinstance(v, (str, int)):
                    val = str(v)
                    break
    if val:
        subs.setdefault(app, {})[placeholder] = val


def domains(subs: dict) -> None:
    """domains: ONE call answers both placeholders.

    `/#/a/{account}/d/{domain}/<tab>` needs an account id AND a domain name, and the app's
    `/api/domains` list carries the owning account beside each name — so asking twice would
    only risk the two disagreeing. A registry with no domain leaves both unresolved; the
    per-domain tabs then report as SKIPPED rather than being filled with an invented name.
    """
    code = ('import urllib.request,json;'
            'd=json.loads(urllib.request.urlopen("http://127.0.0.1:8980/api/domains",timeout=20).read());'
            'rows=d.get("domains") or [];'
            'r=rows[0] if rows else {};'
            'print(json.dumps({"account":(r.get("account") or {}).get("id"),'
            '"domain":r.get("name")},ensure_ascii=False))')
    out = pyrun("domains", code, timeout=40)
    try:
        row = json.loads(out.splitlines()[-1]) if out else {}
    except Exception:
        row = {}
    if row.get("account"):
        subs.setdefault("domains", {})["{account}"] = str(row["account"])
    if row.get("domain"):
        subs.setdefault("domains", {})["{domain}"] = str(row["domain"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/browser42")
    a = ap.parse_args()

    subs: dict = {}
    indox(subs)
    indox_extraction(subs)
    simple(subs, "drive", "drive", 8975, "/api/folders", "folders",
           "{folder}", ("id", "folderId", "label", "name"))
    # /api/files is EMPTY without a folder — it lists files WITHIN a folder. Query it with the
    # folder we just resolved so {file} actually gets an id (this, not a key mismatch, was why the
    # drive file route stayed SKIPPED).
    _fld = subs.get("drive", {}).get("{folder}")
    if _fld:
        from urllib.parse import quote
        simple(subs, "drive", "drive", 8975,
               "/api/files?folder=" + quote(_fld, safe=""), "files",
               "{file}", ("id", "fileId", "name"))
    simple(subs, "mailview", "mailview", 8976, "/api/messages", "messages",
           "{id}", ("id", "uid", "mid"))
    simple(subs, "mailview", "mailview", 8976, "/api/labels", "labels",
           "{label}", ("name", "label", "id"))

    # [2026-09-27] sites and domains joined the map. Their detail views are parameterised
    # (`#/s/{site}/<tab>`, `#/a/{account}/d/{domain}/<tab>`), so with no id every one of them is
    # SKIPPED and the app looks like a single screen. Both ids come from the app's own API; a
    # fleet with no sites stays unresolved, which the map reports honestly rather than hiding.
    simple(subs, "sites", "sites", 8979, "/api/overview", "sites", "{site}",
           ("id", "sid", "label"))
    domains(subs)

    out = Path(a.data) / "ui-params.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(subs, ensure_ascii=False, indent=1), encoding="utf-8")
    for app, d in sorted(subs.items()):
        for k, v in d.items():
            print(f"  {app:<20} {k:<10} -> {v}")
    if not subs:
        print("  (nothing resolved — apps have no data)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
