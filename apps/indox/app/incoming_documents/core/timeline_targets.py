"""Which INDOX instances one GET /timeline/spans call is served for (DGO-1815).

any-concurrency pulls INDOX's timeline as one lane (`SPAN_SOURCE_INDOX`, declared once in apps/indox/app.json), so it
cannot name an instance — and an instance-less call used to be answered from INDOX's default schema, the first
client's books. Now:
  * a call that NAMES an instance (`?instance=`, already bound by the blueprint's before-request hook) is served for
    that one, as before — its ids unprefixed; its spans now also say which in `meta.instance`;
  * a call that names none is served for EVERY enabled production instance in the registry (purpose not 'test':
    the standing test tenant's suite runs are not the office's work), each span saying which;
  * a registry that lists none, or was never read, keeps the old answer — the default schema, unlabelled — so a
    timeline degrades to what it showed, never to nothing (once read, a failed read serves the last good list:
    api._enabled_instance_rows).

Pure, and importable on its own (no package imports), so its rule is tested without Flask or a database.
"""
import re

SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")          # the same rule as api._SAFE_ID
SAFE_SCHEMA = re.compile(r"^[a-z][a-z0-9_]*$")     # the same rule as api._SAFE_SCHEMA


def timeline_targets(named, bound_schema, registry_rows):
    """[(instance id, schema)] to serve, in order; ("", None) means «the default schema, as before»."""
    if named:
        return [(str(named), bound_schema)]
    rows = [r for r in (registry_rows or []) if isinstance(r, dict) and r.get("enabled") is not False
            and str(r.get("purpose") or "") != "test"
            and SAFE_ID.match(str(r.get("id") or "")) and SAFE_SCHEMA.match(str(r.get("schema_name") or ""))]
    if not rows:
        return [("", None)]
    return [(str(r["id"]), str(r["schema_name"])) for r in rows]
