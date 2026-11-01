"""Idempotent boot seed for the organiser rules (RELEASE-DECISIONS N1: one rule store).

The tag rules used to live in indox's supabase table ``tag_rules``. They live here now — this
module seeds ``/data/organizer-defaults.json`` from the shipped fixture the first time the service
starts with an empty volume, so a fresh machine gets a working label engine without a manual
import. Existing volumes are NEVER touched: the seed is create-only, not update.

The seed goes through the SAME validation every PUT does (options.put_defaults), so the fixture
cannot drift into a shape the editor would refuse; ``test_organizer_rules.py`` proves the shipped
fixture passes. The fixture file is copied into the image by the Dockerfile.
"""
import json
import os

FIXTURE_PATH = os.environ.get(
    "ORGANIZER_SEED_FIXTURE", "/app/fixtures/tag_rules.json")


def _rows_from_fixture():
    try:
        with open(FIXTURE_PATH, encoding="utf-8") as f:
            rows = json.load(f)
    except (OSError, ValueError):
        return []
    if not isinstance(rows, list):
        return []
    # keep only the rule columns the engine + UI consume
    keep = ("EVENT", "KEY", "LABEL", "RULE", "TYPE", "label_id", "row_number")
    out = []
    for r in rows:
        if not isinstance(r, dict) or not r.get("KEY"):
            continue
        out.append({k: r[k] for k in keep if k in r})
    out.sort(key=lambda r: r.get("row_number") or 0)
    return out


def seed_if_missing():
    """Create the defaults singleton from the fixture when absent. Returns a
    short status string for the startup log."""
    import options
    if os.path.exists(options.DEFAULTS_PATH):
        return "organizer defaults already present — not seeding"
    rules = _rows_from_fixture()
    if not rules:
        return f"organizer seed skipped: no fixture rows at {FIXTURE_PATH}"
    doc = {"mail": {"organizer": {"mode": "default", "rules": rules}}}
    try:
        options.put_defaults(doc)
    except options.ValidationError as e:
        return "organizer seed REFUSED by validation: %s" % json.dumps(e.problems, ensure_ascii=False)[:800]
    return f"organizer defaults seeded from fixture ({len(rules)} rules)"
