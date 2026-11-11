"""flow.py — what a notice's event may carry: its ANSWERS and its audience, checked (DGO-1329).

Every notice that is news is also an event on the office's stream, `dgo:flow:notifications` (flow.v1). The event
is published by app.py's `_flow`, through the office's ONE publisher, platform-base/redis/flowpub.py (DGO-1402):
this module publishes nothing and holds no copy of the stream's contract (platform-base/redis/
test_flow_publishers.py refuses one). It keeps the two rules a notice's event shares with the POST that made it:

- `actions_of(meta)` — the notice's answers, `meta.actions`: what may be done about it, e.g. «חסום» → the
  security app's ban. [{id, label, op, args}], at most ACTIONS_MAX, each part bounded, `op` of the form
  `<app>.<op>`. A bad list is an error the POST answers with (400), never a list silently trimmed. The app that
  owns an op executes it; nothing here, and nothing reading the stream, acts on a notice by itself. An answer's
  args are an address, an id — never a secret: the stream is read by every agent of the office.
- `audience(meta)` — `meta.to` as push.py reads it (a name or a list of them; empty = everyone).

The control centre's relay to the owner's group (apps/dashboard/group.py) reads the event's `data.actions`,
`data.level`, `data.source_id` and `data.body` from here. Deciding what reaches a person, and how often, is the
reader's: push.py's gate for the phones, the relay's list for the group (DGO-1326).

Until 2026-11-10 this module also published the event itself, with its own queue and redis client (hp-dgo,
DGO-1329), beside app.py's flowpub event (mac-dgo, DGO-1402): two writers of one stream. The release that took
both (DGO-969) kept ONE writer and moved this module's fields onto it.
"""
import json
import re

#: an answer on a notice: a short id, the words on it, and the op of the app that executes it — each part
#: bounded, because anyone on the office network may post a notice and the stream lives in redis, whose
#: memory every app shares (the second reader: a 500 KB args went through, 1000 of them fill redis)
ACTIONS_MAX = 4
ID_MAX, LABEL_MAX, OP_MAX, ARGS_MAX = 64, 40, 64, 512
OP_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\.[A-Za-z0-9_-]+$")


def actions_of(meta):
    """The answers a notice offers, checked: [{id, label, op, args}] — at most ACTIONS_MAX, each with an id,
    a label and an op of the form `<app>.<op>`. Returns (actions, error); a bad list is an error the POST
    answers with, never a list silently trimmed."""
    acts = (meta or {}).get("actions") if isinstance(meta, dict) else None
    if acts in (None, []):
        return [], None
    if not isinstance(acts, list) or len(acts) > ACTIONS_MAX:
        return None, f"meta.actions: a list of at most {ACTIONS_MAX}"
    out = []
    for a in acts:
        if not isinstance(a, dict):
            return None, "meta.actions: each answer is an object {id, label, op, args}"
        aid, label, op = str(a.get("id") or ""), str(a.get("label") or ""), str(a.get("op") or "")
        if not aid or len(aid) > ID_MAX or not label or len(label) > LABEL_MAX or len(op) > OP_MAX \
                or not OP_RE.match(op):
            return None, (f"meta.actions: each answer needs an id (≤ {ID_MAX}), a label (≤ {LABEL_MAX}) and an "
                          f"op «<app>.<op>» (≤ {OP_MAX})")
        args = a.get("args") or {}
        if not isinstance(args, dict):
            return None, "meta.actions: args is an object"
        if len(json.dumps(args, ensure_ascii=False).encode()) > ARGS_MAX:
            return None, f"meta.actions: args is at most {ARGS_MAX} bytes — an address or an id, not content"
        out.append({"id": aid, "label": label, "op": op, "args": args})
    return out, None


def audience(meta):
    """The audience, read as push.py reads meta.to (a name or a list of them). Its own copy, two lines,
    so this module never imports push (which loads the Web Push stack at import)."""
    t = (meta or {}).get("to") if isinstance(meta, dict) else None
    return {str(x).strip().lower() for x in ([t] if isinstance(t, str) else (t or [])) if str(x).strip()}
