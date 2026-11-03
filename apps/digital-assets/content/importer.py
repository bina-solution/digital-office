"""digital-assets/content/importer.py — the content library INTO digital assets, idempotently.

Runs inside the digital-assets container (hooks/content pipes it in). The library arrives on stdin as
JSON rendered by content/render.py. For every piece:

  * its type's blueprint (`content-<type>`, which extends `content-library`) is applied, once per run;
  * its slot `content.<type>.<slug>-<lang>` is created under that blueprint, or its declaration
    (label, brief, constraints) refreshed;
  * a NEW VERSION is added only when the file changed — the file's sha256 is kept in the version's
    meta, so re-running the import adds nothing;
  * a version arrives as a draft. `CONTENT_ACTIVATE=1` also makes the newest version of each piece the
    active one — the version the site shows. Nothing here publishes: publishing is its own act.

Output: `[digital-assets] …` lines for the operator and one `RESULT|{json}` line for the hook.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("DIGITAL_ASSETS_URL_LOCAL") or "http://127.0.0.1:8985"
DRY = os.environ.get("CONTENT_DRY_RUN") == "1"
ACTIVATE = os.environ.get("CONTENT_ACTIVATE") == "1"
ACTOR = "import:content-library"
WORDS = {"article": [1800, 2400], "project": [450, 650], "tutorial": [1000, 2200],
         "comparison": [1200, 1800], "directory": [1500, 3000], "news": [400, 800],
         "report": [1000, 2500], "post": [40, 700], "glossary": [300, 6000]}
HE = {"article": "מאמר עומק", "project": "כרטיס פרויקט", "tutorial": "מדריך", "comparison": "השוואה",
      "directory": "מפתח", "news": "ידיעה", "report": "דוח", "post": "פוסטים", "glossary": "מילון"}


def log(msg: str) -> None:
    print(f"[digital-assets] {msg}", flush=True)


def call(method: str, path: str, body=None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"content-type": "application/json", "x-actor": ACTOR})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read().decode("utf-8")
            return (json.loads(raw) if raw else {}), r.status
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode("utf-8", "replace")[:300]}, e.code


def declaration(p: dict) -> dict:
    f = p["front"]
    lo, hi = WORDS[p["type"]]
    return {"label": {"he": f.get("title") or p["slug"], "en": f.get("title_en") or p["slug"]},
            "brief": {"he": f.get("summary") or ""},
            "constraints": {"type": p["type"], "words": [lo, hi], "note": f"{HE[p['type']]}, {lo:,}–{hi:,} מילים"},
            "lang": p["lang"]}


def main() -> None:
    spec = json.loads(sys.stdin.read() or "{}")
    pieces = spec.get("pieces") or []
    result = {"slots_created": [], "slots_refreshed": [], "versions": [], "unchanged": [], "activated": [],
              "problems": list(spec.get("problems") or []), "dry_run": DRY}
    for t in sorted({p["type"] for p in pieces}):
        if DRY:
            log(f"would apply blueprint content-{t}")
            continue
        out, code = call("POST", f"/api/blueprints/content-{t}/apply", {})
        if code != 200:
            result["problems"].append(f"blueprint content-{t}: HTTP {code} {out.get('error', '')}")
    for p in pieces:
        key = f"content.{p['type']}.{p['slug']}-{p['lang']}"
        q = urllib.parse.quote(key)
        slot, code = call("GET", f"/api/slots/{q}")
        want = declaration(p)
        if code == 404:
            if DRY:
                log(f"would create {key}")
            else:
                _, c2 = call("POST", "/api/slots", {
                    "key": key, "kind": "richtext", "label": want["label"]["he"], "label_en": want["label"]["en"],
                    "lang": p["lang"], "brief": want["brief"], "constraints": want["constraints"],
                    "targets": [] if p["type"] == "post" else [{"channel": "website"}, {"channel": "google-search"}],
                    "blueprint": f"content-{p['type']}"})
                if c2 != 200:
                    result["problems"].append(f"{key}: create HTTP {c2}")
                    continue
                slot = {"assets": []}
            result["slots_created"].append(key)
        elif code != 200:
            result["problems"].append(f"{key}: HTTP {code} {slot.get('error', '')}")
            continue
        else:
            diff = {k: v for k, v in want.items() if (slot.get(k) or {}) != v and k != "lang"}
            if diff:
                if not DRY:
                    call("PATCH", f"/api/slots/{q}", diff)
                result["slots_refreshed"].append(key)
        assets = slot.get("assets") or []
        mine = next((a for a in assets if (a.get("meta") or {}).get("content_sha") == p["sha"]), None)
        if mine is None:
            if DRY:
                log(f"would add a version to {key} ({p['words']} words)")
                result["versions"].append(key)
                continue
            meta = {**p["front"], "content_sha": p["sha"], "path": p["path"], "words_counted": p["words"]}
            out, c3 = call("POST", f"/api/slots/{q}/assets", {
                "text": p["body"], "title": p["front"].get("title") or p["slug"], "meta": meta,
                "source": "import", "author": p["front"].get("author") or "צוות בינה סולושנס",
                "status": "draft", "activate": ACTIVATE})
            if c3 != 200:
                result["problems"].append(f"{key}: version HTTP {c3} {out.get('error', '')}")
                continue
            result["versions"].append(key)
            if ACTIVATE:
                result["activated"].append(key)
            log(f"{key}: new version ({p['words']} words){' — active' if ACTIVATE else ' — draft'}")
        else:
            result["unchanged"].append(key)
            active = (slot.get("active") or {}).get("id")
            if ACTIVATE and active != mine["id"]:
                if not DRY:
                    call("POST", f"/api/assets/{mine['id']}/activate", {})
                result["activated"].append(key)
    print("RESULT|" + json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
