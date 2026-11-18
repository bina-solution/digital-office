#!/usr/bin/env python3
#: desk — every request the owner makes in the group, as a record that moves until it is done:
#:   ./bbox telegram desk list [--all] [--json]          the open requests, oldest first
#:   ./bbox telegram desk show <msg>                      one request, with its items, answers and promises
#:   ./bbox telegram desk take <msg> <DGO-n> [<DGO-m>…]   it is worked on, under those items        → ✍
#:   ./bbox telegram desk promise <msg> "<what>" [--hours 24]   a promise made in an answer, to be kept
#:   ./bbox telegram desk done <msg> --proof "<what he opens or sees>"   live and seen          → 👌
#:   ./bbox telegram desk close <msg>                     he has it                                → 🏆
#:   ./bbox telegram desk reopen <msg> ["<why>"]          he says it does not work                 → ✍
#:   ./bbox telegram desk drop <msg> "<why>"              not a request: a question answered, a thanks → 👌
#:   ./bbox telegram desk answer <msg> <answer_msg>       a message of the bot answers it (the relay records
#:                                                        this by itself for an answer sent with `say-group --for`)
#
# WHY IT EXISTS (DGO-1352). Read message by message, the group of 2026-11-03/04 shows one failure in many shapes:
# every message got an answer and almost none got done. The answer was the deliverable — «✍ קיבלתי (DGO-…)», a
# promise («אעדכן כאן כשהכל מושלם»), and the turn ended. Nothing remembered the request after the reply, nothing
# remembered the promise, and the marks said what the answerer wrote, not what happened: 👀 came from the relay and
# ✍ 👌 🏆 never came at all, because the answerer was never told a message's number. Of 45 items the thread named,
# 8 were completed — while delivered work sat in backlog and «started» work had nobody on it.
#
# So a request is a RECORD here, not a reply. The relay writes it when the message arrives (👀); the answerer moves
# it with the verbs above; the marks on the owner's message follow the record, set by the bot; and the relay's
# sweep reads the records and hands the answerer what is still open — between his messages too, which is the part
# that never happened before (an answerer that only wakes on a new message stops the moment it replies).
#
# THE RULES THE VERBS HOLD (each one is a failure from the thread):
#   * `done` needs `--proof`: what the owner can open or see himself. «נכנס לקוד», «נדחף», «יעלה בבנייה הבאה» are
#     not done (DGO-1323, DGO-1321, DGO-1336 were all «done» that way and none of them reached his phone).
#   * a promise is recorded when it is made and swept until it is kept («the proof screenshot will come here»
#     never came; the security research «חוזר לכאן עם התוכנית» never came back).
#   * `reopen` exists because «זה לא עובד» is a state, not a new request: the record keeps its items and its history.
#
# STORAGE. The office's redis, which the relay already speaks to: one hash, `dgo:desk:requests`, field
# `<chat_id>:<message_id>`, value a JSON record; and `dgo:desk:msgs:<chat_id>`, the group's recent messages by
# number (owner's and bot's), so an answer can quote the message he replied to after the event stream (capped at
# ~1000 events, mostly news channels) has dropped it. Every change of state is also an event on the stream,
# `desk.request`, so the control centre can show the open requests without asking anyone.
#
# BOUNDED, LIKE THE STREAM. Redis is shared, 256 MB, and refuses writes when full (noeviction); its backup hook
# fails an export on any key with no TTL (platform-base/redis/hooks/backup). So every desk key renews a 30-day
# EXPIRE on each write — the same contract the app's own stream keeps — closed records are pruned after 14 days,
# and the remembered messages are capped. A ledger nobody touched for a month is gone, as the stream is.
# Answers live in their own hash (`dgo:desk:answers`), written by the relay alone, so the relay never rewrites a
# record the answerer is editing at the same second; a record is created with HSETNX, never overwritten.
#
# Environment: REDIS_HOST (redis) REDIS_PORT (6379) REDIS_PASSWORD · CONNECTIONS_URL (http://connections:8990)
#              TELEGRAM_BOT_LABEL («בוט טלגרם ראשי») · DESK_CHAT_ID (the group; else the one record that matches)
#              DESK_TTL_SECONDS (2592000) · the stream's cap and TTL are the one publisher's (flowpub.py, DGO-1402),
#              mounted at /opt/dgo/flowpub.py; its event follows the ledger's REDIS_HOST/REDIS_PORT (follow_redis)
# Exit: 0 done · 2 bad usage · 3 redis, the vault or Telegram refused (its own words) · 4 no such request.
import argparse
import datetime
import json
import os
import re
import sys

REQUESTS = "dgo:desk:requests"
ANSWERS = "dgo:desk:answers"
#: where a request's file went in the office's drive (`media.saved`, DGO-1805) — the relay's alone, like ANSWERS, so
#: it never rewrites a record the answerer is editing; `load` puts it on the record as `media.path`
FILES = "dgo:desk:files"
MSGS = "dgo:desk:msgs:%s"
STREAM = "dgo:flow:telegram"           # written through flowpub (_event below), which caps it and renews its TTL
TTL = int(os.environ.get("DESK_TTL_SECONDS") or str(30 * 86400))
KEEP_CLOSED_S = 14 * 86400   # a closed or dropped record is kept this long after its last change, then pruned
MSGS_KEEP = 3000            # the group's messages remembered by number; the oldest beyond this are dropped
TEXT_KEEP = 1200            # a request's own words are kept whole up to this; an answer's quote is shorter

#: A request's states, in order, and the mark each one puts on the owner's message (the bot's reaction).
#: The four marks are the ones the owner asked for (DGO-1316): received, working, finished, delivered and closed.
#: `dropped` is a message that turned out not to be a request — a question answered, a thanks, an approval
#: recorded on its item — finished (👌) without a proof, so it leaves the sweep instead of being nagged forever.
STATES = ("received", "working", "done", "closed", "dropped")
MARKS = {"received": "👀", "working": "✍", "done": "👌", "closed": "🏆", "dropped": "👌"}
OPEN = ("received", "working")
#: What «proof he can see» looks like on the page: a link he opens, or a picture or file he looks at.
PROOF = re.compile(r"https?://\S+|\S+\.(?:png|jpe?g|webp|gif|mp4|webm|pdf)\b", re.I)


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_at(s: str) -> float:
    try:
        return datetime.datetime.strptime((s or "")[:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=datetime.timezone.utc).timestamp()
    except ValueError:
        return 0.0


def field(chat_id, message_id) -> str:
    return "%s:%s" % (int(chat_id), int(message_id))


# ── the record: pure functions, so the rules are tested without redis or Telegram ─────────────────────────────
def new_record(data: dict, at: str = "") -> dict:
    """A request as it arrives: the message's own words, what it replied to, its file — and «received»."""
    return {"chat_id": data.get("chat_id"), "message_id": data.get("message_id"),
            "at": at or now(), "sender": data.get("sender") or "",
            "text": (data.get("text") or "").strip()[:TEXT_KEEP],
            "reply_to": data.get("reply_to"), "media": data.get("media") or None,
            "state": "received", "items": [], "answers": [], "promises": [], "proof": "",
            "updated": at or now(), "history": [{"at": at or now(), "state": "received", "by": "relay"}]}


def move(rec: dict, state: str, by: str, note: str = "", at: str = "") -> dict:
    """The one way a record changes state. Returns the record (changed in place) — the caller stores it."""
    if state not in STATES:
        raise ValueError("no such state: %s" % state)
    stamp = at or now()
    rec["state"] = state
    rec["updated"] = stamp
    entry = {"at": stamp, "state": state, "by": by}
    if note:
        entry["note"] = note[:500]
    rec.setdefault("history", []).append(entry)
    return rec


def take(rec: dict, items: list, by: str = "answerer", at: str = "") -> dict:
    if rec.get("state") in ("done", "closed", "dropped"):
        raise ValueError("msg %s is %s — `desk reopen` it first, with why it is open again"
                         % (rec.get("message_id"), rec.get("state")))
    for it in items:
        it = it.strip().upper()
        if it and it not in rec.setdefault("items", []):
            rec["items"].append(it)
    if rec.get("state") != "working":
        move(rec, "working", by, "items: " + ", ".join(rec["items"]), at)
    return rec


def done(rec: dict, proof: str, by: str = "answerer", at: str = "") -> dict:
    """Finished — and SEEN: the proof is what the owner can open or look at himself, never a commit."""
    proof = (proof or "").strip()
    if not PROOF.search(proof):
        raise ValueError("done needs --proof: the link he opens or the screenshot he sees (a URL, or a .png/.jpg/"
                         ".mp4/.pdf), measured from his side — «committed» or «pushed» is not a proof")
    if not rec.get("items"):
        raise ValueError("done before take: name the item(s) this request was carried under first")
    rec["proof"] = proof[:500]
    for p in rec.get("promises") or []:
        p["kept"] = True
    return move(rec, "done", by, proof, at)


def promise(rec: dict, what: str, hours: float = 24.0, at: str = "") -> dict:
    what = (what or "").strip()
    if not what:
        raise ValueError("promise: what was promised, in the words it was said")
    stamp = at or now()
    due = datetime.datetime.fromtimestamp(parse_at(stamp) + hours * 3600, datetime.timezone.utc)
    # The newest promise is what the answerer owes now: an earlier open one is superseded, not kept — still in the
    # ledger as said, but no longer swept as overdue (a measured step and its next step, DGO-1878 msg 748)
    for p in rec.get("promises") or []:
        if not p.get("kept"):
            p["superseded"] = stamp
    rec.setdefault("promises", []).append({"what": what[:300], "at": stamp,
                                           "due": due.strftime("%Y-%m-%dT%H:%M:%SZ"), "kept": False})
    return rec


def answered(rec: dict, answer_id) -> dict:
    try:
        a = int(answer_id)
    except (TypeError, ValueError):
        return rec
    if a not in rec.setdefault("answers", []):
        rec["answers"].append(a)
    return rec


def drop(rec: dict, why: str, by: str = "answerer", at: str = "") -> dict:
    """Not a request after all — a question answered, a thanks, an approval recorded on its item. Finished
    without a proof, and only with the reason, so «dropped» can be read back and argued with."""
    why = (why or "").strip()
    if not why:
        raise ValueError("drop: why this message is not a request (e.g. «a question, answered in msg N»)")
    if rec.get("items"):
        raise ValueError("drop: it is carried under %s — a request with an item ends in done, not drop"
                         % ", ".join(rec["items"]))
    for p in rec.get("promises") or []:
        p["kept"] = True
    return move(rec, "dropped", by, why, at)


def overdue(rec: dict, t: float) -> list:
    """The promises of an OPEN record that are past due — a finished record owes nothing more."""
    if rec.get("state") not in OPEN:
        return []
    return [p for p in rec.get("promises") or []
            if not p.get("kept") and not p.get("superseded") and parse_at(p.get("due")) <= t]


def carried(rec: dict, t: float) -> list:
    """The promises of an open record still in force — someone is on it until their due time."""
    if rec.get("state") not in OPEN:
        return []
    return [p for p in rec.get("promises") or []
            if not p.get("kept") and not p.get("superseded") and parse_at(p.get("due")) > t]


def open_requests(records: list, t: float, stale_s: float = 1800.0) -> list:
    """What the sweep hands the answerer: open requests idle for `stale_s` that nobody is carrying, and any
    record with a promise past due — oldest first, the ones nobody answered at all before everything else.
    A promise in force holds a request out of the sweep until it is due: that is how a request carried by a
    worker, another session or another office is followed instead of being handed over again every 30 minutes."""
    out = []
    for r in records:
        late = overdue(r, t)
        idle = t - parse_at(r.get("updated") or r.get("at"))
        if late or (r.get("state") in OPEN and idle >= stale_s and not carried(r, t)):
            out.append(r)
    out.sort(key=lambda r: (bool(r.get("answers")), parse_at(r.get("at"))))
    return out


def age(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 3600:
        return "%dm" % (seconds // 60)
    if seconds < 172800:
        return "%dh" % (seconds // 3600)
    return "%dd" % (seconds // 86400)


def one_line(rec: dict, t: float, width: int = 110) -> str:
    text = " ".join((rec.get("text") or "").split())
    if len(text) > width:
        text = text[:width - 1] + "…"
    bits = ["msg %s" % rec.get("message_id"), rec.get("state") or "?", age(t - parse_at(rec.get("at")))]
    bits.append(",".join(rec.get("items") or []) or "no item")
    if not rec.get("answers"):
        bits.append("NOT ANSWERED")
    late = overdue(rec, t)
    if late:
        bits.append("promise overdue: «%s»" % late[0]["what"][:60])
    return "  ".join(bits) + "  «" + text + "»"


def sweep_text(recs: list, t: float, limit: int = 8) -> str:
    """The message the sweep sends the answerer. Short, in the order to work, and with the one rule that the
    thread proved is not obvious: a reply is not progress."""
    lines = ["DESK SWEEP — the owner's requests that are still open (oldest first). Take the FIRST one now: do it "
             "if it is small; if it is big, put a worker on it with the item's research as its brief, or find who "
             "already carries it (the item's latest comment), and record that with `desk promise N \"<who, what, "
             "by when>\" --hours H` — the sweep then leaves it alone until it is due. Carry it to «done» with "
             "proof he can see on his phone; a reply is not progress. One request per sweep. Capacity first: at most two "
             "workers running at once (`./bbox agent list`), and nothing that builds while the load is above 8 or "
             "the checkout's disk is above 95% (`uptime; df -h .`) — then promise «waiting for capacity» --hours 1. "
             "Repair nothing by hand: nothing under .git, nothing another worker started (containers, tabs, files) — "
             "a broken tool is a blocker you write on the request, then go on."]
    for r in recs[:limit]:
        lines.append("· " + one_line(r, t))
    if len(recs) > limit:
        lines.append("· … and %s more: ./bbox telegram desk list" % (len(recs) - limit))
    return "\n".join(lines)


# ── redis (the relay's RESP client, passed in) ────────────────────────────────────────────────────────────────
def _json(raw):
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def load(r, chat_id, message_id):
    rec = _json(r.cmd("HGET", REQUESTS, field(chat_id, message_id)))
    if rec is not None:
        rec["answers"] = sorted(set(rec.get("answers") or []) | set(answers_of(r, chat_id, message_id)))
        path = r.cmd("HGET", FILES, field(chat_id, message_id))
        if path:
            rec["media"] = {**(rec.get("media") or {}), "path": path}
    return rec


def add_file(r, chat_id, message_id, path: str) -> None:
    """The request's file is in the office's drive now: the answerer opens it from the record — a video, a scan —
    instead of asking Telegram again. The record's state and `updated` do not move (a file saved is not a request
    answered); one field, written by the relay alone, renewed like every desk key."""
    if len(str(path)) > 1000:                             # a cut path is a wrong one: none at all is said instead
        raise ValueError(f"a drive path of {len(str(path))} characters is not recorded")
    r.cmd("HSET", FILES, field(chat_id, message_id), str(path))
    r.cmd("EXPIRE", FILES, TTL)


def _publisher():
    """The office's ONE flow.v1 publisher (platform-base/redis/flowpub.py, DGO-1402): mounted at /opt/dgo where an
    app runs this (it wins), else read from the checkout this file sits in (the desk runs from it, hooks/desk).
    None when neither is there — the ledger is written all the same, the stream hears nothing, and the relay says
    so when it starts (relay_group.main)."""
    for where in ("/opt/dgo", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..",
                                           "platform-base", "redis")):
        if os.path.isfile(os.path.join(where, "flowpub.py")):
            if where not in sys.path:
                sys.path.insert(0, where)
            break
    try:
        import flowpub
        return flowpub
    except ImportError:
        return None


_flowpub = _publisher()


def follow_redis(host: str, port: int) -> None:
    """The event goes to the redis the ledger is written to. flowpub dials REDIS_HOST_INTERNAL (else `redis`), never
    REDIS_HOST; the desk and the relay are told their redis by REDIS_HOST — so where that names another one (a
    tunnel, a test redis) the ledger was written there and its event went to `redis:6379` (the second reader,
    DGO-1732). A REDIS_HOST_INTERNAL the container declares is kept."""
    os.environ.setdefault("REDIS_HOST_INTERNAL", host)
    os.environ.setdefault("REDIS_PORT_INTERNAL", str(port))


def _event(r, rec: dict) -> None:
    """`desk.request` on the app's stream, through the one publisher: capped, its TTL renewed, never in the
    ledger's way (a refused event is counted by flowpub, not raised into the answerer's command)."""
    data = {k: rec.get(k) for k in ("chat_id", "message_id", "state", "items", "proof")}
    if _flowpub is not None:
        _flowpub.emit("telegram", "desk.request", "msg %s · %s" % (rec.get("message_id"), rec.get("state")), data)


def create(r, rec: dict) -> bool:
    """A new request — written only if no record by that number exists (HSETNX): a replayed or re-read message
    never resets a record that has moved on. True when this call created it."""
    made = r.cmd("HSETNX", REQUESTS, field(rec["chat_id"], rec["message_id"]), json.dumps(rec, ensure_ascii=False))
    r.cmd("EXPIRE", REQUESTS, TTL)
    if made:
        _event(r, rec)
    return bool(made)


def store(r, rec: dict, event: bool = True) -> None:
    """A record the answerer moved. The answers are not written here — they live in ANSWERS (the relay's)."""
    keep = dict(rec, answers=[])
    if isinstance(rec.get("media"), dict) and "path" in rec["media"]:
        # the path lives in FILES alone (load puts it back): a record stored with it would show it in one listing
        # and not in another
        keep["media"] = {k: v for k, v in rec["media"].items() if k != "path"}
    r.cmd("HSET", REQUESTS, field(rec["chat_id"], rec["message_id"]), json.dumps(keep, ensure_ascii=False))
    r.cmd("EXPIRE", REQUESTS, TTL)
    if event:
        _event(r, rec)


def _answer_map(r) -> dict:
    """ANSWERS holds one field per answer, `<chat>:<msg>:<answer>` — read once into {<chat>:<msg>: [answers]}."""
    out = {}
    for f in r.cmd("HKEYS", ANSWERS) or []:
        parts = str(f).rsplit(":", 1)
        if len(parts) == 2 and parts[1].isdigit():
            out.setdefault(parts[0], []).append(int(parts[1]))
    return out


def answers_of(r, chat_id, message_id) -> list:
    return sorted(_answer_map(r).get(field(chat_id, message_id), []))


def add_answer(r, chat_id, message_id, answer_id) -> None:
    """The bot's message `answer_id` answers request `message_id`. One field per answer: atomic, idempotent."""
    r.cmd("HSET", ANSWERS, "%s:%s" % (field(chat_id, message_id), int(answer_id)), "1")
    r.cmd("EXPIRE", ANSWERS, TTL)


def all_records(r) -> list:
    flat = r.cmd("HGETALL", REQUESTS) or []
    by = _answer_map(r)
    files = r.cmd("HGETALL", FILES) or []                    # each request's saved file, read once — as load() does
    paths = dict(zip((str(k) for k in files[0::2]), files[1::2]))
    out = []
    for key, raw in zip(flat[0::2], flat[1::2]):
        rec = _json(raw)
        if rec is None:
            continue
        rec["answers"] = sorted(set(rec.get("answers") or []) | set(by.get(str(key), [])))
        if paths.get(str(key)):
            rec["media"] = {**(rec.get("media") or {}), "path": paths[str(key)]}
        out.append(rec)
    return out


def prune(r, t: float) -> int:
    """Finished records (done, closed, dropped) leave 14 days after their last change; answers whose request is
    gone — a bot reply to a message that was never a request — leave with them. Returns how many records went."""
    gone, keep = 0, set()
    for rec in all_records(r):
        key = field(rec["chat_id"], rec["message_id"])
        if rec.get("state") in ("done", "closed", "dropped") and t - parse_at(rec.get("updated")) > KEEP_CLOSED_S:
            r.cmd("HDEL", REQUESTS, key)
            gone += 1
        else:
            keep.add(key)
    for f in r.cmd("HKEYS", ANSWERS) or []:
        if str(f).rsplit(":", 1)[0] not in keep:
            r.cmd("HDEL", ANSWERS, f)
    for f in r.cmd("HKEYS", FILES) or []:                   # a file's path leaves with its request
        if str(f) not in keep:
            r.cmd("HDEL", FILES, f)
    return gone


def remember(r, data: dict, at: str = "") -> None:
    """One message of the group by its number — the owner's and the bot's — so a reply can be quoted later."""
    if data.get("chat_id") is None or data.get("message_id") is None:
        return
    key = MSGS % int(data["chat_id"])
    r.cmd("HSET", key, str(int(data["message_id"])), json.dumps(
        {"sender": data.get("sender") or "", "at": at or now(), "text": (data.get("text") or "").strip()[:600],
         "media": bool(data.get("media"))}, ensure_ascii=False))
    r.cmd("EXPIRE", key, TTL)
    if int(data["message_id"]) % 50 == 0:            # trim now and then, not on every message
        n = r.cmd("HLEN", key) or 0
        if n > MSGS_KEEP:
            ids = sorted(int(x) for x in (r.cmd("HKEYS", key) or []) if str(x).isdigit())
            for old in ids[: n - MSGS_KEEP]:
                r.cmd("HDEL", key, str(old))


def recall(r, chat_id, message_id):
    return _json(r.cmd("HGET", MSGS % int(chat_id), str(int(message_id))))


# ── the bot's mark ─────────────────────────────────────────────────────────────────────────────────────────
def set_mark(token: str, chat_id, message_id, emoji: str) -> None:
    import urllib.request
    body = json.dumps({"chat_id": chat_id, "message_id": int(message_id),
                       "reaction": [{"type": "emoji", "emoji": emoji}]}).encode("utf-8")
    req = urllib.request.Request("https://api.telegram.org/bot%s/setMessageReaction" % token, data=body,
                                 method="POST", headers={"content-type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status != 200:
            raise ConnectionError("mark: HTTP %s" % resp.status)


# ── the CLI ────────────────────────────────────────────────────────────────────────────────────────────────
def _redis():
    from relay_group import Redis                      # the relay's own client: one RESP reader in this app
    host, port = os.environ.get("REDIS_HOST", "redis"), int(os.environ.get("REDIS_PORT", "6379"))
    follow_redis(host, port)
    r = Redis(host, port, os.environ.get("REDIS_PASSWORD", ""), timeout=30)
    r.connect()
    return r


def _chat_of(r, msg: str, chat: str):
    """`<msg>` alone is the group's: DESK_CHAT_ID, else the one chat that has a request by that number."""
    if chat:
        return int(chat)
    if os.environ.get("DESK_CHAT_ID"):
        return int(os.environ["DESK_CHAT_ID"])
    hits = [rec["chat_id"] for rec in all_records(r) if str(rec.get("message_id")) == str(msg)]
    if len(set(hits)) == 1:
        return hits[0]
    sys.exit("desk: %s — pass --chat <id>" % ("no request numbered %s" % msg if not hits
                                               else "more than one chat has a request numbered %s" % msg))


def _mark(rec: dict, bot: str) -> str:
    from relay_group import bot_token
    tok = ""
    try:
        tok = bot_token(bot)
        if not tok:
            return "not marked (no bot token in the vault)"
        set_mark(tok, rec["chat_id"], rec["message_id"], MARKS[rec["state"]])
        return "marked " + MARKS[rec["state"]]
    except Exception as e:                                    # the record moved; the mark is its picture
        return "not marked (%s)" % (str(e).replace(tok, "***") if tok else str(e))[:160]


def main(argv) -> int:
    ap = argparse.ArgumentParser(prog="desk", add_help=True)
    ap.add_argument("verb", choices=["list", "show", "take", "promise", "done", "close", "reopen", "drop", "answer"])
    ap.add_argument("msg", nargs="?", default="")
    ap.add_argument("rest", nargs="*")
    ap.add_argument("--chat", default="")
    ap.add_argument("--proof", default="")
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--bot", default=os.environ.get("TELEGRAM_BOT_LABEL", "בוט טלגרם ראשי"))
    a = ap.parse_args(argv[1:])
    try:
        r = _redis()
    except (ConnectionError, OSError) as e:
        print("desk: redis did not answer (%s)" % e, file=sys.stderr)
        return 3
    t = datetime.datetime.now(datetime.timezone.utc).timestamp()

    if a.verb == "list":
        recs = sorted(all_records(r), key=lambda x: parse_at(x.get("at")))
        if not a.all:
            recs = [x for x in recs if x.get("state") in OPEN or overdue(x, t)]
        if a.json:
            print(json.dumps(recs, ensure_ascii=False, indent=1))
        else:
            print("\n".join(one_line(x, t) for x in recs) or "nothing open")
        return 0

    if not a.msg.isdigit():
        print("desk %s: which message? its number (msg N in the TG: line)" % a.verb, file=sys.stderr)
        return 2
    chat = _chat_of(r, a.msg, a.chat)
    rec = load(r, chat, a.msg)
    if rec is None:
        print("desk: no request msg %s in chat %s (only the owner's messages the relay delivered are requests)"
              % (a.msg, chat), file=sys.stderr)
        return 4

    try:
        if a.verb == "show":
            print(json.dumps(rec, ensure_ascii=False, indent=1))
            return 0
        if a.verb == "take":
            if not a.rest:
                raise ValueError("take: the item(s) — DGO-n — this request is carried under")
            take(rec, a.rest)
        elif a.verb == "promise":
            promise(rec, " ".join(a.rest), a.hours)
            store(r, rec)
            print("msg %s: promise recorded, due %s" % (a.msg, rec["promises"][-1]["due"]))
            return 0
        elif a.verb == "done":
            done(rec, a.proof)
        elif a.verb == "close":
            if rec.get("state") != "done":
                raise ValueError("close comes after done: the proof he can see is recorded first")
            move(rec, "closed", "answerer")
        elif a.verb == "reopen":
            move(rec, "working", "answerer", " ".join(a.rest) or "the owner says it does not work")
            rec["proof"] = ""
        elif a.verb == "drop":
            drop(rec, " ".join(a.rest))
        elif a.verb == "answer":
            if not a.rest or not a.rest[0].isdigit():
                raise ValueError("answer: the number of the bot's message that answers it")
            add_answer(r, rec["chat_id"], rec["message_id"], a.rest[0])
            print("msg %s: answered by msg %s" % (a.msg, a.rest[0]))
            return 0
    except ValueError as e:
        print("desk %s: %s" % (a.verb, e), file=sys.stderr)
        return 2
    store(r, rec)
    print("msg %s → %s · %s" % (a.msg, rec["state"], _mark(rec, a.bot)))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.exit(main(sys.argv))
