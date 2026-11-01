"""sites.checks — the catalogue of things the office asks a site.

One entry per question, and every entry returns the same shape:

    {"check": <name>, "state": "ok"|"warn"|"error", "summary": {...}, "findings": [ ... ]}

`findings` is what turns a scan into work: each one names the URL, the rule, the evidence and the
fix, and the store keys them by (site, check, code, url) so a re-run updates rather than appends and
a fixed warning disappears on its own (store.record_findings).

Adding a check is adding a module and one line here — that is the whole extension point, and it is
deliberate: the value of this app is the pattern underneath, and a check that needs a change in three
other files would be a check nobody adds.
"""
from __future__ import annotations

from . import beauty, security, seo, uptime, visits

#: name → (module, human name, what it answers, how often it is worth running by itself)
CATALOG: dict[str, dict] = {
    "security": {
        "module": security, "title": "אבטחת האתר",
        "question": "האם האתר עצמו מאובטח — TLS, כותרות, נתיבים חשופים",
        "kind": "scan", "default_hours": 24,
    },
    "seo": {
        "module": seo, "title": "SEO",
        "question": "האם מנוע חיפוש יכול למצוא את האתר ולהציג אותו נכון",
        "kind": "scan", "default_hours": 24 * 7,
    },
    "beauty": {
        "module": beauty, "title": "ציון יופי",
        "question": "מה הציון של beautiful-score בכל אחד משלושת הגדלים",
        "kind": "scan", "default_hours": 24 * 7,
    },
    "visits": {
        "module": visits, "title": "ביקורים",
        "question": "מי נכנס, לאן, ומאיפה — מתוך לוג השרת של האתר",
        "kind": "collect", "default_hours": 0,
    },
}

SCAN_CHECKS = tuple(k for k, v in CATALOG.items() if v["kind"] == "scan")


def modules() -> dict:
    return {k: v["module"] for k, v in CATALOG.items()}


def catalog() -> list[dict]:
    return [{"name": k, "title": v["title"], "question": v["question"], "kind": v["kind"],
             "default_hours": v["default_hours"]} for k, v in CATALOG.items()]


def run(name: str, site: dict, **opts) -> dict:
    entry = CATALOG.get(name)
    if not entry:
        raise KeyError(f"unknown check {name!r}")
    mod = entry["module"]
    if name == "security":
        return mod.run(site, deep=opts.get("deep", True))
    if name == "seo":
        return mod.run(site, max_pages=int(opts.get("max_pages") or 20),
                       deep=opts.get("deep", True))
    if name == "beauty":
        return mod.run(site, min_score=opts.get("min_score"),
                       viewports=opts.get("viewports"), mode=opts.get("mode", "ui"))
    raise KeyError(f"{name} is not runnable through run()")


__all__ = ["CATALOG", "SCAN_CHECKS", "catalog", "modules", "run", "uptime", "visits"]
