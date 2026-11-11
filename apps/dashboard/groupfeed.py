"""groupfeed.py — the owner's Telegram group, live inside the control centre (DGO-1329, step 8).

The owner, 2026-11-03 (the group): «הלוח בקרה מארגן ומציף את זה אצלו ומשם זה מגיע גם לקבוצה הראשית … וכמובן צט לייב לכל
מה שאני כותב». The group is where he asks and where the office answers; the control centre is where he looks first.
This puts the group's latest messages on the page, each one a tap away from Telegram itself — where he answers.

WHERE IT READS. The telegram app runs on one office (herd.yaml `apps: telegram:`, the HP): through that office's door
when it is linked here (`http://telegram.<office>:<port>`, the port the serving office published — feed.door), or the
app itself when it runs here. The group is DASHBOARD_GROUP_CHAT, or the watched group whose title is one of the main
group's names with the newest message (group.py's own rule: a group that became a supergroup stays watched for its
history, and only the new one talks) — never another chat.

WHAT IT WRITES. /data/group-live.json: {at, chat_id, title, link, messages: [{id, at, sender, bot, out, text, reply_to,
media, link}], error}. The newest GROUP_KEEP messages, oldest first; each with its t.me link (a supergroup's message
opens in the Telegram app with one tap). A read that fails keeps the last good messages and says why — across a
restart too: the file it wrote is where it starts.

WHERE IT RUNS. Only on the offices DASHBOARD_GROUP_LIVE_ON names (default: the MacBook, the owner's own screen). The
file is served to the office network without a sign-in, as the page's state is, and the group is the owner's: it is
never copied onto an office that does not show it to him — above all not the public vps1 (the second reader).

Standard library only, a thread of feed.py: nothing is built on the Mac (the owner, 2026-10-31).
"""
import json
import os
import re
import tempfile
import time
import urllib.parse

OUT = os.environ.get("DASHBOARD_GROUP_LIVE", "/data/group-live.json")
EVERY = int(os.environ.get("DASHBOARD_GROUP_EVERY", "15"))
GROUP_KEEP = 30
CHATS_EVERY = 600                    # the group's id, found again every ten minutes
NAMES = [t.strip() for t in os.environ.get(
    "DASHBOARD_GROUP_NAMES", "Bina Solutions Main|בינה פתרונות ראשי|בינה פיתרונות ראשי").split("|") if t.strip()]
BOTS = ("Bina Agent", "BinaSolutionsAgentBot")
LOCAL = os.environ.get("TELEGRAM_URL", "http://telegram:8984").rstrip("/")
OFFICE = os.environ.get("DGO_OFFICE_ID", "").strip()
ON = [o for o in re.split(r"[\s,]+", os.environ.get("DASHBOARD_GROUP_LIVE_ON", "macbook")) if o]


def enabled(office=OFFICE, on=ON):
    return bool(office) and office in on


def last_written(path=OUT):
    """What this reader wrote last — its messages are the page's until a read succeeds again."""
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        return doc if isinstance(doc, dict) and isinstance(doc.get("messages"), list) else None
    except (OSError, ValueError):
        return None


def telegram_base(herd, door, local=LOCAL):
    """The telegram app's address from here: the door of the office herd.yaml runs it on, else this office's own."""
    try:
        with open(herd, encoding="utf-8") as fh:
            m = re.search(r"^apps:\s*$.*?^\s+telegram:\s*([A-Za-z0-9_-]+)", fh.read(), re.M | re.S)
    except OSError:
        m = None
    if m:
        url = door(m.group(1), "telegram")
        if url:
            return url
    return local


def tme(chat_id, message_id=None):
    """https://t.me/c/<id>/<msg> — a supergroup's message (or the group itself) in the Telegram app; "" otherwise."""
    s = str(chat_id or "")
    if not s.startswith("-100"):
        return ""
    return f"https://t.me/c/{s[4:]}" + (f"/{int(message_id)}" if message_id else "")


def pick_group(chats, history_at):
    """The main group among the watched chats: a title of NAMES, the newest message — (id, title) or (None, "")."""
    best = None
    for c in chats or []:
        if not c.get("watched") or c.get("kind") != "group" or str(c.get("title", "")).strip() not in NAMES:
            continue
        at = history_at(c["id"])
        if best is None or at > best[0]:
            best = (at, c["id"], str(c.get("title") or ""))
    return (best[1], best[2]) if best else (None, "")


def shape(chat_id, rows):
    out = []
    for m in rows or []:
        if not isinstance(m, dict) or m.get("message_id") is None:
            continue
        sender = str(m.get("sender") or "").strip()
        out.append({"id": m.get("message_id"), "at": m.get("at") or "", "sender": sender,
                    "bot": sender in BOTS, "out": bool(m.get("out")),
                    "text": str(m.get("text") or "").strip()[:1200], "reply_to": m.get("reply_to"),
                    "media": bool(m.get("media")), "link": tme(chat_id, m.get("message_id"))})
    out.sort(key=lambda m: int(m["id"]))
    return out[-GROUP_KEEP:]


def write(doc, path=OUT):
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".group-live-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False)
    os.replace(tmp, path)


def loop(get, door, herd, every=EVERY, sleep=time.sleep, now=time.time, once=False, office=None):
    """Every `every` seconds: the group's newest messages into OUT. `get` is feed.get (JSON, or {"_error"})."""
    if not enabled(OFFICE if office is None else office):
        return None
    doc = {"at": 0, "chat_id": None, "title": "", "link": "", "messages": [], "error": ""}
    doc.update({k: v for k, v in (last_written() or {}).items() if k in doc})
    doc["chat_id"] = None                            # found again on the first pass: the old file only lends its messages
    chat_at = 0.0
    while True:
        try:
            base = telegram_base(herd, door)
            fixed = os.environ.get("DASHBOARD_GROUP_CHAT", "").strip()
            if fixed:
                doc["chat_id"] = int(fixed)
            elif doc["chat_id"] is None or now() - chat_at > CHATS_EVERY:
                chats = get(f"{base}/api/chats", timeout=10)
                if "_error" in chats:
                    raise RuntimeError(chats["_error"])

                def newest(cid):
                    q = urllib.parse.urlencode({"chat_id": cid, "limit": 1})
                    h = get(f"{base}/api/history?{q}", timeout=10)
                    if not isinstance(h, dict) or "_error" in h:     # a group not read is never «the older one»
                        raise RuntimeError((h or {}).get("_error") if isinstance(h, dict) else "history not readable")
                    msgs = h.get("messages") or []
                    return msgs[-1].get("at", "") if msgs else ""
                cid, title = pick_group(chats.get("chats"), newest)
                if cid is None:
                    raise RuntimeError("no watched group named " + " / ".join(NAMES))
                doc.update(chat_id=cid, title=title, link=tme(cid))
                chat_at = now()
            q = urllib.parse.urlencode({"chat_id": doc["chat_id"], "limit": GROUP_KEEP})
            got = get(f"{base}/api/history?{q}", timeout=10)
            if "_error" in got:
                raise RuntimeError(got["_error"])
            doc.update(at=int(now()), messages=shape(doc["chat_id"], got.get("messages")), error="")
        except Exception as e:                      # noqa: BLE001 — the last good messages stay; the page says why
            doc["error"] = f"{type(e).__name__}: {e}"[:200]
        try:
            write(doc)
        except OSError as e:
            print(f"dashboard-feed: group-live not written: {e}", flush=True)
        if once:
            return doc
        sleep(every)
