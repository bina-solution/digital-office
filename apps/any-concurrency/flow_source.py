"""flow_source.py — «כל מקביל» hears every app's event stream (flow.v1), one lane per app (DGO-1402).

The owner, 2026-11-05: «כל אפליקציה מציעה flow וכל מקביל פשוט נרשם לכולם בברירת מחדל». Every app that tells what
it did writes `dgo:flow:<app>` (platform-base/redis/flowpub.py, the one publisher); this file turns one event
into one span of the source `flow`, whose lane (`svc`) is the app — the same shape as the n8n section, one src
and one ring with a row per worker. app.py reads the streams (SCAN + XREAD on the office redis it already holds)
and hands every entry here; nothing here touches redis, so it is tested on its own (test_flow_source.py).

HOW AN EVENT BECOMES A SPAN
  * an event is an instant (s == e) in its app's row, labelled with its `title`;
  * `<kind>.started` … `<kind>.ended | .failed` sharing `data.span` is ONE bar: the start opens it (running),
    the end closes it under the same id — the store merges by id. The end carries `data.t0`, so a bar whose
    start fell outside the window (or before this process started) still has its true start;
  * the status is read off the verb: failed/error/lost/refused/crashed/down → error, started → running,
    canceled/cancelled → canceled, anything else → success.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

PREFIX = "dgo:flow:"
SRC = "flow"
LABEL_MAX = 120
#: open bars remembered for their end; beyond this the oldest is forgotten (its end still closes it by id)
OPEN_MAX = 5000
_FAIL = frozenset(("failed", "error", "errored", "lost", "refused", "crashed", "rejected", "down", "unreachable"))
_CANCEL = frozenset(("canceled", "cancelled", "aborted"))
#: data keys that are the span's own bookkeeping, not facts about the event
_OWN = frozenset(("span", "t0", "ms"))
#: data keys that carry what a PERSON wrote or who they are — kept off the timeline whatever the stream
_PRIVATE = frozenset(("text", "body", "message", "sender", "sender_id", "from", "to", "email", "phone"))
FACT_MAX = 120


def app_of(key: str) -> str | None:
    """`dgo:flow:drive` → `drive`; anything else is not a stream of the contract."""
    if not isinstance(key, str) or not key.startswith(PREFIX):
        return None
    app = key[len(PREFIX):]
    return app if app and ":" not in app else None


def entry_ms(entry_id: str) -> int:
    """A stream entry's id is `<ms>-<seq>`: the time redis took it."""
    try:
        return int(str(entry_id).split("-", 1)[0])
    except (TypeError, ValueError):
        return 0


def _iso_ms(s: str | None) -> int | None:
    if not s:
        return None
    try:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def _status(verb: str) -> str:
    # the outcome is the verb's LAST word: an app may say what failed before it (domain-internic's
    # `record.update_failed`, `login.credential_plane_unreachable`), and those were drawn as successes (DGO-1732)
    last = verb.rsplit("_", 1)[-1]
    if last in _FAIL:
        return "error"
    if last in _CANCEL:
        return "canceled"
    if verb == "started":
        return "running"
    return "success"


def span_of(key: str, entry_id: str, fields: dict[str, Any], opened: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """One stream entry → one span row (or None when it is not an event of the contract).

    `opened` is the caller's memory of bars still running (id → row), so an end finds its start; it is
    mutated here and bounded by OPEN_MAX."""
    app = app_of(key)
    if app is None or not isinstance(fields, dict):
        return None
    typ = str(fields.get("type") or "")
    if "." not in typ:
        return None
    kind, verb = typ.rsplit(".", 1)
    ms = _iso_ms(fields.get("at")) or entry_ms(entry_id)
    if not ms:
        return None
    try:
        data = json.loads(fields.get("data") or "{}")
    except (TypeError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    title = " ".join(str(fields.get("title") or typ).split())[:LABEL_MAX]
    # The span's facts are the event's SHORT scalar facts: a tooltip and /api/spans are read by everyone who
    # has the screen, and a stream may carry a person's words (telegram's `text`, a sender) for the agents
    # that were given that chat — the timeline is not one of them. The contract's own keys come last, so an
    # event's data cannot rename its type, its app or its link (the second reader, DGO-1402).
    meta: dict[str, Any] = {k: (v[:FACT_MAX] if isinstance(v, str) else v) for k, v in data.items()
                            if k not in _OWN and k not in _PRIVATE and isinstance(v, (str, int, float, bool))}
    meta.update({"type": typ, "app": app})
    if fields.get("link"):
        meta["link"] = str(fields["link"])
    sid = data.get("span")
    if sid:
        rid = f"{SRC}:{app}:{sid}"
        if verb == "started":
            row = {"id": rid, "src": SRC, "svc": app, "svcid": kind, "label": title, "status": "running",
                   "s": ms, "e": None, "d": None, "meta": meta}
            opened[rid] = row
            while len(opened) > OPEN_MAX:
                opened.pop(next(iter(opened)))
            return row
        start = opened.pop(rid, None)
        try:
            t0 = int(data.get("t0")) if data.get("t0") is not None else None
        except (TypeError, ValueError):
            t0 = None
        s = start["s"] if start else (t0 if t0 is not None else ms)
        s = min(s, ms)
        return {"id": rid, "src": SRC, "svc": app, "svcid": kind,
                "label": (start or {}).get("label") or title, "status": _status(verb),
                "s": s, "e": ms, "d": ms - s, "meta": {**((start or {}).get("meta") or {}), **meta}}
    return {"id": f"{SRC}:{app}:{entry_id}", "src": SRC, "svc": app, "svcid": kind, "label": title,
            "status": _status(verb), "s": ms, "e": ms, "d": 0, "meta": meta}
