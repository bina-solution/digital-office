#!/usr/bin/env python3
"""flow_demo.py — a few minutes of the office telling what it did, on a redis of its OWN, so «כל מקביל»'s
`flow` lane can be seen (and photographed) without touching an office's streams (DGO-1402).

    REDIS_HOST_INTERNAL=<demo redis> REDIS_PASSWORD=<its password> PYTHONPATH=<dir of flowpub.py> \
        python3 flow_demo.py [seconds=90]

It publishes through the office's ONE publisher (platform-base/redis/flowpub.py) exactly as the five apps
of DGO-1402 do — sites, meet, drive, connections, notifications — so what the lane draws is what those
apps will draw: bars for work with a duration, instants for the rest. NEVER point it at an office's own
redis: every agent of the office reads those streams, and these events did not happen.
"""
from __future__ import annotations

import random
import sys
import threading
import time

import flowpub

SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 90.0
rnd = random.Random(1402)


def bar(app: str, kind: str, title: str, seconds: float, data: dict | None = None, fail: bool = False) -> None:
    try:
        with flowpub.span(app, kind, title, data):
            time.sleep(seconds)
            if fail:
                raise RuntimeError("demo failure")
    except RuntimeError:
        pass


def later(delay: float, fn, *a, **kw) -> None:
    threading.Timer(delay, fn, a, kw).start()


def main() -> int:
    t_end = time.time() + SECONDS
    flowpub.emit("notifications", "notice.info", "גיבוי לילי הושלם", {"source": "data-management"})
    flowpub.emit("connections", "connection.tested", "החיבור «google-drive» נבדק", {"id": "google-drive", "status": "healthy"})
    flowpub.emit("meet", "meeting.opened", "נפתחה פגישה חדשה (3fa2c1d0)", {"room_ref": "3fa2c1d0"})
    later(2, bar, "sites", "site.deploy", "פריסת «example.co.il»", 14, {"site": "exampleu"})
    later(4, bar, "drive", "file.upload", "העלאת קובץ pdf (2048 KB)", 6, {"size": 2097152, "kind": "pdf"})
    later(5, bar, "drive", "file.upload", "העלאת קובץ mp4 (90112 KB)", 22, {"size": 92274688, "kind": "mp4"})
    later(7, flowpub.emit, "meet", "meeting.entered", "כניסה לפגישה (3fa2c1d0)", {"room_ref": "3fa2c1d0"})
    later(9, flowpub.emit, "connections", "connection.revealed", "ערך של «openai-api-key» הוצג", {"id": "openai-api-key"})
    later(12, bar, "meet", "recordings.process", "עיבוד ההקלטות (תמלול ופריט)", 25, {"reason": "ended", "recordings": 1})
    later(13, flowpub.emit, "meet", "recording.ready", "הקלטה חדשה מוכנה", {"session": "a1b2c3"})
    later(16, flowpub.emit, "notifications", "notice.warning", "הדיסק של המחשב «HP» מעל 90%", {"source": "machine"})
    later(18, bar, "sites", "site.deploy", "פריסת «bina-solutions.co.il»", 8, {"site": "bina"}, True)
    later(20, flowpub.emit, "drive", "folder.created", "נוצרה תיקייה")
    later(24, flowpub.emit, "connections", "connection.tested.failed", "החיבור «linet» נבדק", {"id": "linet", "status": "error"})
    later(27, flowpub.emit, "notifications", "notice.error", "Bina Claude התנתק", {"source": "bina-claude"})
    later(30, flowpub.emit, "drive", "items.trashed", "הועברו לאשפה 3 פריטים", {"count": 3})
    later(33, flowpub.emit, "sites", "site.down", "האתר לא עונה", {"site": "old-landing"})
    later(36, flowpub.emit, "connections", "instance.created", "נוסף המופע «exampleu»", {"id": "exampleu"})
    # …and the two that carried their own copy of the publisher until they moved onto this one (DGO-1402's follow-up)
    later(3, flowpub.emit, "telegram", "account.connected", "טלגרם מחובר: הלשכה", {"account": "office"})
    later(11, flowpub.emit, "telegram", "message.new", "הודעה חדשה ב«צוות»", {"chat_id": -100123, "chat": "צוות"})
    later(15, flowpub.emit, "domain-internic", "login.ok", "הלשכה התחברה לפורטל אינטרניק")
    later(19, flowpub.emit, "telegram", "desk.request", "msg 4021 · taken", {"message_id": 4021, "state": "taken"})
    later(23, flowpub.emit, "domain-internic", "record.created", "A www ב-example.co.il נכתבה בפורטל", {"domain": "example.co.il"})
    later(29, flowpub.emit, "domain-internic", "record.update_failed", "TXT _dmarc ב-bina.co.il: הפורטל לא ענה", {"domain": "bina.co.il"})
    # …and a steady trickle until the end, so the lane is alive when it is photographed
    while time.time() < t_end:
        time.sleep(rnd.uniform(3, 7))
        app = rnd.choice(["drive", "notifications", "connections", "sites", "meet", "telegram"])
        if app == "telegram":
            flowpub.emit("telegram", "message.new", "הודעה חדשה ב«צוות»", {"chat_id": -100123, "chat": "צוות"})
            continue
        if app == "drive":
            later(0, bar, "drive", "file.upload", "העלאת קובץ jpg (512 KB)", rnd.uniform(1, 5), {"kind": "jpg"})
        elif app == "notifications":
            flowpub.emit("notifications", "notice.info", "משימה הושלמה", {"source": "project-pln"})
        elif app == "connections":
            flowpub.emit("connections", "connection.tested", "החיבור «telegram» נבדק", {"id": "telegram", "status": "healthy"})
        elif app == "sites":
            flowpub.emit("sites", "site.up", "האתר חזר לענות", {"site": "old-landing"})
        else:
            flowpub.emit("meet", "meeting.entered", "כניסה לפגישה (9b1e04aa)", {"room_ref": "9b1e04aa"})
    time.sleep(2)
    print("published:", flowpub.stats())
    return 0 if flowpub.stats()["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
