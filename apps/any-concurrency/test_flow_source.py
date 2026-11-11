#!/usr/bin/env python3
"""test_flow_source.py — how «כל מקביל» draws an app's event stream (flow_source.py, DGO-1402), fed by the
office's own publisher (platform-base/redis/flowpub.py `fields_of`): the two halves of flow.v1 read together.

    python3 apps/any-concurrency/test_flow_source.py      (G72 runs it; standard library only)
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "platform-base", "redis"))

import flow_source as fs  # noqa: E402
import flowpub  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"\n        {detail}"))
    if not ok:
        FAILS.append(name)


def entry(app: str, type_: str, title: str, data: dict | None = None, link: str = "") -> tuple[str, dict]:
    """What a stream entry looks like when the publisher wrote it: its fields as XADD sent them."""
    f = flowpub.fields_of(app, type_, title, data, link)
    assert f is not None, (app, type_)
    return f"dgo:flow:{app}", dict(zip(f[0::2], f[1::2]))


def main() -> int:
    opened: dict = {}

    # 1. an instant: one event → one span of src `flow`, its row the app, its label the title
    key, f = entry("notifications", "notice.error", "התחברות נכשלה", {"source": "bina-claude"}, "#/m/notify")
    s = fs.span_of(key, "1700000000000-0", f, opened)
    check("an event is an instant in its app's row",
          s and s["src"] == "flow" and s["svc"] == "notifications" and s["s"] == s["e"] and s["d"] == 0
          and s["label"] == "התחברות נכשלה", repr(s))
    check("…coloured by its verb (error) and carrying its facts",
          s and s["status"] == "error" and s["meta"]["source"] == "bina-claude" and s["meta"]["link"] == "#/m/notify"
          and s["meta"]["type"] == "notice.error", repr(s))
    check("…its id is the entry's, so a re-read is the same span", s and s["id"] == "flow:notifications:1700000000000-0")

    # 2. a bar: <kind>.started … <kind>.ended with one data.span → ONE id, opened then closed
    k, f1 = entry("sites", "site.deploy.started", "פריסה", {"span": "ab12", "site": "exampleu"})
    a = fs.span_of(k, "1700000000000-0", {**f1, "at": "2026-11-10T01:00:00.000Z"}, opened)
    k, f2 = entry("sites", "site.deploy.ended", "פריסה", {"span": "ab12", "site": "exampleu", "t0": 0, "ms": 4000})
    b = fs.span_of(k, "1700000004000-0", {**f2, "at": "2026-11-10T01:00:04.000Z"}, opened)
    check("the start is a running bar", a and a["status"] == "running" and a["e"] is None and a["svcid"] == "site.deploy", repr(a))
    check("the end closes the SAME bar (same id), success, 4 s long",
          b and b["id"] == a["id"] and b["status"] == "success" and b["e"] - b["s"] == 4000 and b["s"] == a["s"], repr(b))
    check("…and is no longer remembered as open", a["id"] not in opened)
    check("…the bar keeps the event's facts, not the span's bookkeeping",
          b and b["meta"].get("site") == "exampleu" and "t0" not in b["meta"] and "span" not in b["meta"], repr(b and b["meta"]))

    # 3. an end whose start this reader never saw (before the window, before a restart): its own t0 starts it
    k, f3 = entry("meet", "recordings.process.failed", "עיבוד", {"span": "zz", "t0": 1700000000000, "ms": 9000})
    c = fs.span_of(k, "1700000009000-0", {**f3, "at": "2023-11-14T22:13:29.000Z"}, opened)
    check("an end without its start starts at its t0, red", c and c["status"] == "error" and c["s"] == 1700000000000
          and c["e"] == 1700000009000, repr(c))

    # 4. what is not the contract is nothing — never a crash
    check("a key outside dgo:flow:* is not an event", fs.span_of("other:drive", "1-0", f, opened) is None)
    check("a type with no dot is not an event", fs.span_of("dgo:flow:drive", "1-0", {"type": "x", "title": "t"}, opened) is None)
    check("broken data is read as no data", fs.span_of("dgo:flow:drive", "1700000000000-0",
                                                       {"type": "file.uploaded", "data": "{not json"}, opened) is not None)
    check("an entry with no time takes the entry id's", (fs.span_of("dgo:flow:drive", "1700000000123-0",
                                                                   {"type": "a.b"}, opened) or {}).get("s") == 1700000000123)

    # 5. the verbs: cancel, fail, everything else success
    st = {t: (fs.span_of("dgo:flow:x", "1700000000000-0", {"type": t}, {}) or {}).get("status")
          for t in ("a.canceled", "a.lost", "a.connected", "a.new", "site.down")}
    check("canceled/lost/down/connected/new read as they are said",
          st == {"a.canceled": "canceled", "a.lost": "error", "a.connected": "success", "a.new": "success",
                 "site.down": "error"}, json.dumps(st))
    # 5a. the outcome is the verb's LAST word: domain-internic says `record.update_failed` and
    #     `login.credential_plane_unreachable` — drawn as successes until DGO-1732's shots showed it
    st = {t: (fs.span_of("dgo:flow:x", "1700000000000-0", {"type": t}, {}) or {}).get("status")
          for t in ("record.update_failed", "record.create_failed", "login.credential_plane_unreachable",
                    "job.user_cancelled", "record.created", "login.ok", "failed_login.retried")}
    check("a compound verb is read by its last word",
          st == {"record.update_failed": "error", "record.create_failed": "error",
                 "login.credential_plane_unreachable": "error", "job.user_cancelled": "canceled",
                 "record.created": "success", "login.ok": "success", "failed_login.retried": "success"}, json.dumps(st))

    # 5b. what a person wrote never reaches the timeline, and an event's data cannot rename its type/app/link
    k, fp = entry("telegram", "message.new", "הודעה חדשה",
                  {"text": "סוד אישי", "sender": "דני", "chat": "צוות", "type": "x.y", "app": "drive",
                   "nested": {"a": 1}, "long": "א" * 500})
    t = fs.span_of(k, "1700000000000-0", fp, {})
    check("a message's text and sender stay off the timeline", t and "text" not in t["meta"] and "sender" not in t["meta"]
          and t["meta"].get("chat") == "צוות", repr(t and t["meta"]))
    check("…data cannot rename the event's type or app", t and t["meta"]["type"] == "message.new" and t["meta"]["app"] == "telegram",
          repr(t and t["meta"]))
    check("…only short scalar facts", t and "nested" not in t["meta"] and len(t["meta"].get("long", "")) == fs.FACT_MAX,
          repr(t and {k: len(str(v)) for k, v in t["meta"].items()}))

    # 6. the memory of open bars is bounded
    many: dict = {}
    for i in range(fs.OPEN_MAX + 50):
        fs.span_of("dgo:flow:x", f"{1700000000000 + i}-0", {"type": "w.started", "data": json.dumps({"span": f"s{i}"})}, many)
    check("open bars remembered are capped", len(many) == fs.OPEN_MAX, str(len(many)))

    print(f"\n{'all passed' if not FAILS else f'{len(FAILS)} failed'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
