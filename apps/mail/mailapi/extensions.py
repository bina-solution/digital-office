"""extensions — apps register UI into this service's slots; the service renders and never interprets.

Contract §4c. Any app POSTs `{app, slot, spec}`; the mail UI renders `spec` into `slot`. The spec is
OPAQUE here: this module validates its shape (so a bad registration fails loudly at write time, not
silently at render time) and stores it. It never reads a field for meaning, which is what keeps
invariant (b) true — mail cannot learn what any app's labels are FOR, only that they exist and what
to call them. Apps are symmetric: the first one to use this gets no special treatment in code.

Storage: /data/extensions.json (the volume that already holds the active pointer), read per request
so a registration is visible immediately and survives a restart.
"""
import json
import os
import re
import tempfile
import time

EXT_PATH = os.environ.get("EXTENSIONS_PATH", "/data/extensions.json")

# The slots this service offers (§4c). A slot it does not render is refused at registration: an app
# must never believe it registered something that will never appear.
SLOTS = ("rail", "container_badge", "item_action", "dropzone")
_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


def _load_all():
    try:
        with open(EXT_PATH, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return []
    return d.get("extensions") or [] if isinstance(d, dict) else []


def _save_all(rows):
    d = os.path.dirname(EXT_PATH) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"extensions": rows}, f, ensure_ascii=False)
        os.replace(tmp, EXT_PATH)      # atomic: a crashed write can never strand a half-file
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def listing(slot=None, app=None):
    return [r for r in _load_all()
            if (not slot or r.get("slot") == slot) and (not app or r.get("app") == app)]


def register(app, slot, spec):
    """Upsert by (app, slot) — an app re-registering replaces its own extension and touches no one
    else's. Returns (record, None) or (None, reason)."""
    if not _NAME.match(str(app or "")):
        return None, "app must be lowercase [a-z0-9_-]"
    if slot not in SLOTS:
        return None, f"unknown slot {slot!r}; this service renders {', '.join(SLOTS)}"
    if not isinstance(spec, dict):
        return None, "spec must be an object"
    rec = {"app": app, "slot": slot, "spec": spec, "updated_at": int(time.time())}
    rows = [r for r in _load_all() if not (r.get("app") == app and r.get("slot") == slot)]
    rows.append(rec)
    _save_all(rows)
    return rec, None


def unregister(app, slot):
    rows = _load_all()
    keep = [r for r in rows if not (r.get("app") == app and r.get("slot") == slot)]
    if len(keep) == len(rows):
        return False
    _save_all(keep)
    return True
