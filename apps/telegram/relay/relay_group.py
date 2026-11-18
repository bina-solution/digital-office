#!/usr/bin/env python3
#: relay-group — every new message in ONE Telegram group, handed to ONE agent session as a «TG:» line
#:   ./bbox telegram relay-group --chat "Bina Solutions Main" --session <session-id> [--bot-name NAME] [--from ID] [--once]
#
# WHY IT EXISTS (DGO-1339). The group's answerer was a Claude app session that watched the office's event
# stream by itself; when that app signed out (2026-11-04 07:45 UTC) nothing listened any more and the group went
# silent (`apps/project-pln/plans/tg-group.yaml`, tg-g-001). This is the interim listener: the app's own stream
# (`dgo:flow:telegram`, flow.v1 — the events `./bbox telegram flow --json` prints) is read for messages in ONE
# group, and each one is delivered to an agent session that answers there.
#
# WHY IT TALKS TO REDIS ITSELF. `./bbox telegram flow` reads redis by `docker exec` into the redis container,
# because the HOST cannot reach redis's port (platform-base/redis/flow.py). This runs in a container on the
# office's own `traefik-network`, where redis IS reachable — so it speaks RESP directly, with no CLI, no engine
# socket and no privilege: the password arrives in the environment (as it does for every app), the agent's
# action token from a read-only file, and nothing else. The filter is the stream's: type `message.new` in this
# chat, from anyone but the bot — so the bot's own answers cannot make a loop.
#
# WHAT IT DELIVERS. The session gets the message, its number, and what it answers:
#     TG: <sender> <HH:MM> UTC msg <n> <text>
#     ↩ msg <m> (<who>, <HH:MM>): «<the message he replied to>»            when he replied to one
#     [תמונה] <kind> <name> <size> chat_id=… message_id=… (file: ./bbox telegram media …)   when it carried a file
#     desk: ./bbox telegram desk take <n> DGO-… — …                        the record it opened (desk.py)
# The line carries the message, never a decision: the answerer decides. Every delivered line is in the log with
# the event id, the message number and the session, so "did it arrive, and when" is answered from the log.
#
# WHY THE NUMBER AND THE QUOTE (DGO-1352). Until 2026-11-05 the line was `TG: <sender> <HH:MM> UTC <text>`: no
# number, and nothing of the message he was replying to. Read in the thread, that one omission answered him on the
# wrong subject twice in an afternoon — «זה לא עובד לא פותח לי שום דפדפן», a reply to the Google sign-in message,
# was answered about the news app's browser; «הקישור לא עובד», a reply to the Claude sign-in link, was answered
# about the news app's link — and without a number the answerer could neither reply to his message nor mark it,
# so ✍ 👌 🏆 never appeared. Every message of the group (his and the bot's) is now remembered by number in
# redis (desk.py, `dgo:desk:msgs:<chat>`), because the stream keeps ~1000 events and the news channels the
# office also watches push the group's own messages out of it within hours.
#
# WHY IT SWEEPS. An answerer that wakes only on a new message stops when it replies; whatever it promised in the
# reply has nobody to do it (the thread: «שלושת התיקונים שאני עושה» — then nothing, until he wrote again). Every
# `--sweep` seconds (10 minutes) the relay reads the open requests (desk.py) and, when there are any and the session
# is idle, hands it ONE message with them, oldest first. It decides nothing and posts nothing in the group. Ten
# minutes, not thirty: a backlog of 43 open requests took a day just to be picked up at thirty (the owner,
# 2026-11-05: «מה לגבי כל העבודה שביקשתי הכל מושלם ?»); a request someone carries is held out by its promise, so a
# shorter window costs nothing when nothing is waiting.
#
# Environment: REDIS_HOST (redis) REDIS_PORT (6379) REDIS_PASSWORD · AGENT_URL (http://bina-ds:3081)
#              AGENT_TOKEN_FILE (/run/agent-token) or BBOX_AGENT_TOKEN · STATE_FILE (/state/last-id)
#              RELAY_BOT_NAMES (extra sender names to skip, comma separated) · RELAY_RESET (1 = ignore the cursor)
#              TELEGRAM_URL (http://telegram:8984, for a quote older than what redis remembers)
#              DESK_SWEEP_SECONDS (600; 0 = never) · DESK_STALE_SECONDS (1800)
# Exit: 0 on a clean stop or a `--once` pass; 3 when redis or the agent door is out of reach.
import argparse
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request

STREAM = "dgo:flow:telegram"
BLOCK_MS = 15000
#: The bot's own names, as the event stream spells them (`sender` is the display name in the group), so a row
#: written by anything else — a person, an automation with its own name — is the kind that gets forwarded.
#: «Azaria» is the bot's display name in the group since it was renamed: without it the office's notices and the
#: bot's own replies became requests on the desk (62 of 96 open records on 2026-11-13, DGO-1878).
DEFAULT_BOT_NAMES = ("Bina Agent", "BinaSolutionsAgentBot", "Azaria")
#: A file is named by the chat and the message number, never by an address: the answerer brings it in with the
#: app's own verb (`./bbox telegram media <chat_id> <message_id> <path>`), so the line it is handed carries no
#: internal hostname — these lines end up quoted in the group, and the group never gets an internal address.


def log(msg: str) -> None:
    print("[relay] " + time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + " " + msg, flush=True)


try:                                   # the request ledger (desk.py, beside this file); without it the relay
    import desk                        # still delivers — a container started with this file alone must not die
except ImportError:                    # on a missing neighbour, it says so once and goes on
    desk = None
try:                                   # the owner's commands — «משימה:», «מצב», «קדימה», «חסום» — done here, before
    import commands                    # the answerer (commands.py, DGO-1329); without the file every message is
except ImportError:                    # the answerer's, as before
    commands = None


class Redis:
    """The one reply shape this reader needs: arrays of arrays of bulk strings (XREAD / XRANGE)."""

    def __init__(self, host: str, port: int, password: str, timeout: float = BLOCK_MS / 1000 + 30):
        self.host, self.port, self.password = host, port, password
        self.timeout = timeout
        self.sock = None
        self.rf = None

    def connect(self) -> None:
        self.close()
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.rf = self.sock.makefile("rb")
        if self.password:
            self.cmd("AUTH", self.password)

    def close(self) -> None:
        for obj in (self.rf, self.sock):
            try:
                if obj:
                    obj.close()
            except OSError:
                pass
        self.sock = self.rf = None

    def _reply(self):
        line = self.rf.readline()
        if not line:
            raise ConnectionError("redis closed the connection")
        head = line.rstrip(b"\r\n")
        kind, rest = head[:1], head[1:]
        if kind == b"+":
            return rest.decode("utf-8", "replace")
        if kind == b"-":
            raise ConnectionError("redis refused: " + rest.decode("utf-8", "replace")[:300])
        if kind == b":":
            return int(rest)
        if kind == b"$":
            n = int(rest)
            if n < 0:
                return None
            return self.rf.read(n + 2)[:-2].decode("utf-8", "replace")
        if kind == b"*":
            n = int(rest)
            return None if n < 0 else [self._reply() for _ in range(n)]
        raise ConnectionError("redis sent an unknown reply: %r" % head[:60])

    def cmd(self, *args):
        out = [b"*%d\r\n" % len(args)]
        for a in args:
            a = a if isinstance(a, (bytes, bytearray)) else str(a).encode("utf-8")
            out.append(b"$%d\r\n%s\r\n" % (len(a), a))
        self.sock.sendall(b"".join(out))
        return self._reply()


def agent_token(path: str) -> str:
    """The agent.v1 action token, read at every delivery — a restarted agent may have written a new one."""
    tok = os.environ.get("BBOX_AGENT_TOKEN", "").strip()
    if tok:
        return tok
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read().strip()


def bot_token(label: str) -> str:
    """The bot's token out of the vault, in memory — the relay marks a message it has received (DGO-1346),
    which is the bot's own act and needs the bot, not the owner's account."""
    vault = os.environ.get("CONNECTIONS_URL", "http://connections:8990").rstrip("/")
    rows = json.load(urllib.request.urlopen(vault + "/api/instances", timeout=30)).get("instances") or []
    cands = [r for r in rows if r.get("protocol") == "telegram_bot"]
    pick = next((r for r in cands if (r.get("label") or "").strip() == label), None) or (cands[0] if len(cands) == 1 else None)
    if pick is None:
        return ""
    secret = json.load(urllib.request.urlopen(vault + "/api/instances/%s/secret" % pick["id"], timeout=30))
    return ((secret or {}).get("secret") or {}).get("token", "").strip()


def mark_received(token: str, chat_id, message_id, emoji: str = "👀") -> None:
    """Say «seen» on the message itself. The owner's message 144: «נראה שאתה לא מחובר בכלל» — a listener that
    delivers without a mark looks dead, even when the answer comes a minute later. The bot IS an admin
    (measured 2026-11-04: getChatMember → administrator), so this is one call, and a failure here must
    never cost the delivery."""
    if not token:
        return
    body = json.dumps({"chat_id": chat_id, "message_id": int(message_id),
                       "reaction": [{"type": "emoji", "emoji": emoji}]}).encode("utf-8")
    req = urllib.request.Request("https://api.telegram.org/bot%s/setMessageReaction" % token,
                                 data=body, method="POST",
                                 headers={"content-type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status != 200:
            raise ConnectionError("mark: HTTP %s" % resp.status)


def tell_agent(session: str, text: str, token_path: str) -> None:
    """POST the line to the session — the door `./bbox agent send <id> <text>` uses."""
    base = os.environ.get("AGENT_URL", "http://bina-ds:3081").rstrip("/")
    url = base + "/v1/sessions/" + session + "/messages"
    body = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
    last = ""
    for attempt, delay in enumerate((0, 5, 20), start=1):
        if delay:
            time.sleep(delay)
        try:
            req = urllib.request.Request(
                url, data=body, method="POST",
                headers={"content-type": "application/json; charset=utf-8",
                         "authorization": "Bearer " + agent_token(token_path)})
            # 240 s: bina-claude's driver can take up to 200 s to hand a message to the desktop app, and a send
            # cut short there is a send that may have happened (apps/bina-claude/adapter/server.mjs:259,268)
            with urllib.request.urlopen(req, timeout=240) as resp:
                if resp.status in (200, 201, 202):
                    return
                last = "HTTP %s" % resp.status
        except urllib.error.HTTPError as e:
            answer = e.read()[:2000].decode("utf-8", "replace")
            last = "HTTP %s %s" % (e.code, answer[:200])
            if e.code == 504:
                log("the door timed out on its own side (504): taken as delivered, never sent twice")
                return
            if e.code == 502 and ("not-confirmed" in answer or "Return pressed" in answer):
                # typed and Return pressed; only the door's look at the transcript came too early (a busy session
                # shows the text later). Sending again put msg 986 in front of the session for hours, and the
                # cursor never passed it, so nothing after it arrived (DGO-1878)
                log("the door typed the text and has not seen it yet (502 not-confirmed): taken as delivered, "
                    "never sent twice")
                return
            if e.code in (401, 409, 429, 502, 503):
                continue                      # a replaced token, a send in flight, a door restarting: try again
            break                             # anything else is the door's answer: no retry will change it
        except (TimeoutError, socket.timeout) as e:
            # the request went out and the answer did not come back: it may have been delivered, and a second
            # send would put the same message in front of the session twice
            log("no answer from the door in time (%s): taken as delivered, never sent twice" % e)
            return
        except (urllib.error.URLError, OSError) as e:
            last = str(e)[:200]
    raise ConnectionError("the agent door did not take the message: " + last)


def agent_busy(session: str, token_path: str) -> bool:
    """Is the session in a turn right now? The sweep waits for an idle session rather than queueing a nudge
    behind work in progress. A door that cannot say counts as busy: a missed sweep costs one window."""
    base = os.environ.get("AGENT_URL", "http://bina-ds:3081").rstrip("/")
    try:
        req = urllib.request.Request(base + "/v1/sessions/" + session,
                                     headers={"authorization": "Bearer " + agent_token(token_path)})
        with urllib.request.urlopen(req, timeout=30) as resp:
            s = json.loads(resp.read().decode("utf-8", "replace")) or {}
    except (urllib.error.URLError, OSError, ValueError):
        return True
    return busy_of(s)


def agent_sessions(token_path: str) -> list:
    """The agent door's sessions (agent.v1 GET /v1/sessions) — for the table of «מצב» and «קדימה»."""
    base = os.environ.get("AGENT_URL", "http://bina-ds:3081").rstrip("/")
    req = urllib.request.Request(base + "/v1/sessions", headers={"authorization": "Bearer " + agent_token(token_path)})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return (json.loads(resp.read().decode("utf-8", "replace")) or {}).get("sessions") or []


def command_context(args, token_path: str):
    """What a command needs from the relay (commands.Context): its OWN redis connection for a thread — the loop's
    socket is the loop's alone — the door to the answerer, the bot, and the agents' sessions."""
    if commands is None:
        return None

    def fresh_redis():
        r = Redis(os.environ.get("REDIS_HOST", "redis"), int(os.environ.get("REDIS_PORT", "6379")),
                  os.environ.get("REDIS_PASSWORD", ""), timeout=30)
        r.connect()
        return r
    return commands.Context(redis_fn=fresh_redis, deliver=lambda text: tell_agent(args.session, text, token_path),
                            bot=commands.Bot(lambda: bot_token(args.bot)),
                            sessions_fn=lambda: agent_sessions(token_path))


def busy_of(s: dict) -> bool:
    """agent.v1 says it as `running` (a turn in progress) and `queue` (messages waiting) — both adapters, bina-ds
    and bina-claude. A `state` word is read too, for a door that speaks one."""
    if not isinstance(s, dict):
        return True
    if s.get("running") or s.get("queue"):
        return True
    return str(s.get("state") or s.get("status") or "").lower() in ("running", "busy", "working")


_QUOTE_MISSES = set()      # (chat, msg) the history did not have: asked once, not on every reply to it


def quote_of(r, data: dict) -> dict:
    """The message he replied to, by its number: from redis first (desk.py remembers the group's messages),
    then from the app's own history — the same reader `./bbox telegram history` uses — once per number, short
    and bounded, because the owner's message waits for it. {} when neither has it."""
    ref = data.get("reply_to")
    if not ref:
        return {}
    if desk is not None:
        try:
            got = desk.recall(r, data.get("chat_id"), ref)
            if got:
                return dict(got, message_id=ref)
        except (ConnectionError, OSError, ValueError, TypeError):
            pass
    miss = (str(data.get("chat_id")), str(ref))
    if miss in _QUOTE_MISSES:
        return {}
    base = os.environ.get("TELEGRAM_URL", "http://telegram:8984").rstrip("/")
    try:
        url = "%s/api/history?chat_id=%s&limit=200" % (base, int(data.get("chat_id")))
        with urllib.request.urlopen(url, timeout=10) as resp:
            rows = (json.loads(resp.read().decode("utf-8", "replace")) or {}).get("messages") or []
    except urllib.error.HTTPError as e:       # the history refused: what it said is logged, the quote is just absent
        try:
            said = e.read(200).decode("utf-8", "replace")
        except Exception:                     # noqa: BLE001 — a body that breaks off is no body; still not a crash
            said = ""
        log("quote %s: the history answered %s %s" % (ref, e.code, said))
        rows = []
    except Exception:                         # noqa: BLE001 — IncompleteRead, BadStatusLine…: a quote, not a crash
        rows = []
    for m in rows:
        if str(m.get("message_id")) == str(ref):
            return {"message_id": ref, "sender": m.get("sender") or "", "at": m.get("at") or "",
                    "text": (m.get("text") or "").strip()[:600], "media": bool(m.get("media"))}
    _QUOTE_MISSES.add(miss)
    return {}


def media_line(data: dict) -> str:
    media = data.get("media") or {}
    if not media:
        return ""
    kind = (media.get("kind") or "").strip() or "file"
    label = "תמונה" if kind == "photo" else (media.get("label") or "קובץ")
    bits = ["[%s]" % label, kind]
    if media.get("name"):
        bits.append(str(media["name"]))
    if media.get("size"):
        bits.append(str(media["size"]) + "B")
    chat, msg = data.get("chat_id"), data.get("message_id")
    bits.append("chat_id=%s message_id=%s" % (chat, msg))
    bits.append("(file: ./bbox telegram media %s %s)" % (chat, msg))
    return " ".join(bits)


def is_from_bot(ev: dict, bot_names) -> bool:
    return (str((ev.get("data") or {}).get("sender") or "").strip()) in bot_names


def in_chat(ev: dict, chat: str, chat_id: str) -> bool:
    data = ev.get("data") or {}
    if chat_id:
        return str(data.get("chat_id")) == str(chat_id)
    return not chat or (data.get("chat") or "") == chat


def wanted(ev: dict, chat: str, chat_id: str, bot_names) -> bool:
    """A message of a PERSON in this group — the kind that is delivered, and that becomes a request."""
    if ev.get("type") != "message.new" or not in_chat(ev, chat, chat_id):
        return False
    sender = ((ev.get("data") or {}).get("sender") or "").strip()
    return bool(sender) and sender not in bot_names


def note_saved_file(r, ev: dict) -> bool:
    """A message's file reached the drive (`media.saved`): its request's record, if it has one, carries the path —
    written to the relay's own hash (desk.FILES), never by rewriting the record the answerer may be editing at the
    same second (the second reader). Like the ledger's other writes, never the reason the relay stops: a refused
    write costs the path, not the run."""
    data = ev.get("data") or {}
    if desk is None or data.get("chat_id") is None or data.get("message_id") is None or not data.get("path"):
        return False
    try:
        if r.cmd("HGET", desk.REQUESTS, desk.field(data["chat_id"], data["message_id"])) is None:
            return False                                     # no request: the bot's own message, or one from before
        desk.add_file(r, data["chat_id"], data["message_id"], data["path"])
        return True
    except Exception as e:                                   # noqa: BLE001 — see the docstring
        if _lost_socket(e):
            raise
        log(f"the record of {data.get('message_id')} did not take its drive path ({e})")
        return False


def note_group_message(r, ev: dict, bot_names) -> tuple:
    """The ledger's part of one group message, and NEVER the reason a message is not delivered: redis that
    refuses writes (it is shared, and full is `noeviction`) costs the record, not his message. Returns
    (recorded, mark): whether his message is a request record now, and the mark it should carry — 👀 when new,
    the record's own when a replay or a re-read meets one that has already moved on."""
    if desk is None:
        return False, "👀"
    data = ev.get("data") or {}
    recorded, mark = False, "👀"
    try:
        if is_from_bot(ev, bot_names):
            if data.get("reply_to"):
                desk.add_answer(r, data.get("chat_id"), data.get("reply_to"), data.get("message_id"))
            recorded, mark = False, ""
        elif (data.get("sender") or "").strip():           # a message with no sender is never a request
            if desk.create(r, desk.new_record(data, ev.get("at") or "")):
                recorded, mark = True, "👀"
            else:
                rec = desk.load(r, data.get("chat_id"), data.get("message_id")) or {}
                recorded, mark = True, desk.MARKS.get(rec.get("state"), "👀")
    except Exception as e:                       # noqa: BLE001 — see the docstring: the delivery comes first
        if _lost_socket(e):
            raise                                # the connection itself is gone: reconnect and read this again
        log("msg %s: the ledger did not take it (%s) — delivered without a record"
            % (data.get("message_id"), str(e)[:200]))
    try:
        desk.remember(r, data, ev.get("at") or "")
    except Exception as e:                       # noqa: BLE001 — a quote that will be missing later, nothing more
        if _lost_socket(e):
            raise
        log("msg %s: not remembered for quoting (%s)" % (data.get("message_id"), str(e)[:200]))
    return recorded, mark


def _lost_socket(e: Exception) -> bool:
    """A redis that ANSWERED with a refusal (full, read-only) is the ledger's problem; a connection that is gone
    is everyone's — the loop must reconnect before it hands on anything, or the cursor walks past messages."""
    if isinstance(e, ConnectionError) and str(e).startswith("redis refused"):
        return False
    return isinstance(e, (ConnectionError, OSError))


def sweep(r, session: str, token_path: str, stale_s: float) -> str:
    """Hand the answerer what is still open — once, when it is idle and there is something. Returns what it did,
    for the log. It reads the ledger and nothing else; it never writes in the group."""
    if desk is None:
        return "no ledger"
    t = time.time()
    pruned = desk.prune(r, t)
    recs = desk.open_requests(desk.all_records(r), t, stale_s)
    if not recs:
        return "nothing open" + (" (%d closed record(s) pruned)" % pruned if pruned else "")
    if agent_busy(session, token_path):
        return "%d open, the session is busy" % len(recs)
    tell_agent(session, desk.sweep_text(recs, t), token_path)
    return "%d open, handed to %s" % (len(recs), session)


def line_for(ev: dict, quote: dict = None, ledger: bool = False) -> str:
    """The message as the answerer reads it: who, when, its NUMBER, its words, the message it replies to (quoted),
    its file, and — when the ledger holds it — the one desk verb that turns the answer into a record."""
    data = ev.get("data") or {}
    at = str(ev.get("at") or "")
    stamp = at[11:16] if len(at) >= 16 else at              # 2026-11-04T08:22:44Z -> 08:22
    text = (data.get("text") or "").strip().replace("\r", "")
    head = "TG: %s %s UTC" % (data.get("sender"), stamp)
    if data.get("message_id") is not None:
        head += " msg %s" % data.get("message_id")
    body = " ".join(x for x in (text, media_line(data)) if x) or "[הודעה בלי טקסט]"
    lines = [head + " " + body]
    if data.get("reply_to"):
        if quote:
            q_at = str(quote.get("at") or "")
            q_text = " ".join((quote.get("text") or "").split())
            if len(q_text) > 400:
                q_text = q_text[:399] + "…"
            lines.append("↩ msg %s (%s, %s): «%s»%s" % (
                data.get("reply_to"), quote.get("sender") or "?", q_at[11:16] if len(q_at) >= 16 else q_at,
                q_text or "[בלי טקסט]", " [עם קובץ]" if quote.get("media") else ""))
        else:
            lines.append("↩ msg %s (not found: `./bbox telegram chat <group> history all` has it) — "
                         "answer THAT message's subject" % data.get("reply_to"))
    if ledger:
        lines.append("desk: ./bbox telegram desk take %s DGO-… (the item it is carried under), `desk promise` for "
                     "every promise in your answer, `desk done %s --proof …` only when he can see it live — a "
                     "reply is not progress (apps/telegram/relay/DESK.md)"
                     % (data.get("message_id"), data.get("message_id")))
    return "\n".join(lines)


def read_state(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def write_state(path: str, eid: str) -> None:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8") as fh:
            fh.write(eid)
        os.replace(path + ".tmp", path)
    except OSError:                        # a read-only state file must not end the listener
        pass


def main(argv) -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--chat", default="Bina Solutions Main", help="the group's title, as the stream spells it")
    ap.add_argument("--chat-id", default="", help="…or its id, when two chats share a title")
    ap.add_argument("--session", required=True, help="the agent.v1 session that answers there")
    ap.add_argument("--bot-name", action="append", default=[], help="a sender name to skip (repeatable)")
    ap.add_argument("--from", dest="start", default="", help="the stream id to start after (default: now)")
    ap.add_argument("--once", action="store_true", help="one bounded pass over what is already there, then exit")
    ap.add_argument("--no-mark", action="store_true", help="do not put 👀 on a message as it is delivered")
    ap.add_argument("--bot", default=os.environ.get("TELEGRAM_BOT_LABEL", "בוט טלגרם ראשי"),
                    help="the vault's bot whose mark is «seen»")
    ap.add_argument("--sweep", type=float, default=float(os.environ.get("DESK_SWEEP_SECONDS") or "600"),
                    help="seconds between two hand-overs of the open requests (0 = never)")
    ap.add_argument("--stale", type=float, default=float(os.environ.get("DESK_STALE_SECONDS") or "1800"),
                    help="a request untouched this long is handed over again")
    args = ap.parse_args(argv[1:])
    if desk is None:
        log("desk.py is not beside this file: messages are delivered, but no request is recorded and nothing "
            "is swept — run the relay from its whole directory (apps/telegram/relay)")
    elif desk._flowpub is None:
        # the relay writes nearly every desk record, so without the publisher the control centre, «כל מקביל» and
        # `bbox telegram flow` hear no request at all — said once here, not per record (DGO-1732)
        log("flowpub.py is not mounted: requests are recorded, but no `desk.request` reaches the office's stream — "
            "mount platform-base/redis/flowpub.py at /opt/dgo/flowpub.py:ro")

    bot_names = set(DEFAULT_BOT_NAMES) | {n.strip() for n in args.bot_name if n.strip()}
    bot_names |= {n.strip() for n in os.environ.get("RELAY_BOT_NAMES", "").split(",") if n.strip()}
    state_file = os.environ.get("STATE_FILE", "/state/last-id")
    token_path = os.environ.get("AGENT_TOKEN_FILE", "/run/agent-token")

    resume = "" if os.environ.get("RELAY_RESET", "") not in ("", "0", "false") else read_state(state_file)
    cursor = resume or args.start
    if not cursor and not args.once:
        cursor = "$"                       # from now on: the group's past is not replayed into the session
    log("watching «%s» on %s from %s -> session %s"
        % (args.chat or args.chat_id, STREAM, cursor or "the stream's start", args.session))

    redis_host, redis_port = os.environ.get("REDIS_HOST", "redis"), int(os.environ.get("REDIS_PORT", "6379"))
    if desk is not None:
        desk.follow_redis(redis_host, redis_port)   # the request's event goes where its record is written
    r = Redis(redis_host, redis_port, os.environ.get("REDIS_PASSWORD", ""))
    forwarded = 0
    ctx = None if args.once else command_context(args, token_path)    # a replay by hand runs no command
    bot_tok = ""                       # read from the vault on the first delivery, kept in memory only
    last_sweep = time.time()           # the first hand-over waits one window: a restart is not a reason to nudge
    while True:
        try:
            if not r.sock:
                r.connect()
            if cursor == "$":
                # «from now on» as an id: a first delivery that fails must be read again after the reconnect,
                # and XREAD from "$" would skip it and everything sent during the outage
                last = r.cmd("XREVRANGE", STREAM, "+", "-", "COUNT", 1) or []
                cursor = last[0][0] if last else "0-0"
                log("from now on = after %s" % cursor)
            if args.sweep > 0 and not args.once and time.time() - last_sweep >= args.sweep:
                last_sweep = time.time()
                try:
                    log("sweep: " + sweep(r, args.session, token_path, args.stale))
                except Exception as e:           # noqa: BLE001 — a failed sweep waits for the next window
                    log("sweep: not handed over (%s)" % str(e)[:200])
            if args.once and not cursor:
                page = r.cmd("XREVRANGE", STREAM, "+", "-", "COUNT", 20) or []
                if not page:
                    log("nothing on the stream yet")
                    return 0
                cursor = page[-1][0]        # the oldest of the page; read forward from it
                got = [[STREAM, r.cmd("XRANGE", STREAM, cursor, "+", "COUNT", 200) or []]]
            else:
                got = r.cmd("XREAD", "BLOCK", BLOCK_MS, "STREAMS", STREAM, cursor)
            if not got:
                if args.once:
                    log("once: nothing new")
                    return 0
                continue
            for _stream, entries in got:
                for eid, flat in entries:
                    fields = dict(zip(flat[0::2], flat[1::2]))
                    raw = fields.get("data") or ""
                    try:
                        data = json.loads(raw) if raw else {}
                    except ValueError:
                        data = {}
                    if not isinstance(data, dict):
                        data = {}
                    ev = {"id": eid, "type": fields.get("type") or "", "at": fields.get("at") or "",
                          "app": fields.get("app") or "telegram", "data": data}
                    if ev["type"] == "media.saved" and in_chat(ev, args.chat, args.chat_id):
                        note_saved_file(r, ev)                  # the record carries the drive path (DGO-1805)
                        cursor = eid
                        write_state(state_file, eid)
                        continue
                    if not wanted(ev, args.chat, args.chat_id, bot_names):
                        if ev["type"] == "message.new" and in_chat(ev, args.chat, args.chat_id):
                            note_group_message(r, ev, bot_names)        # the bot's own: remembered, never delivered
                        cursor = eid
                        write_state(state_file, eid)
                        continue
                    recorded, mark = note_group_message(r, ev, bot_names)
                    line = line_for(ev, quote_of(r, data), ledger=recorded and mark in ("👀", "✍"))
                    cmd = None
                    if ctx is not None:
                        try:
                            cmd = commands.take(r, ev, line, ctx)
                        except Exception as e:     # noqa: BLE001 — a command that breaks is the answerer's message
                            if _lost_socket(e):
                                raise
                            log("msg %s: the command failed (%s) — handed to the answerer as it is"
                                % (data.get("message_id"), str(e)[:200]))
                    if cmd:
                        mark = cmd.get("mark") or mark
                        if cmd.get("note"):
                            line += "\n" + cmd["note"]
                    try:
                        if not cmd or cmd.get("deliver", True):
                            tell_agent(args.session, line, token_path)
                    except ConnectionError as e:
                        # the cursor stays BEFORE this message: the retry after the reconnect reads it again
                        log("%s NOT delivered (%s); it is read again after the reconnect" % (eid, e))
                        raise
                    cursor = eid
                    forwarded += 1
                    write_state(state_file, eid)
                    log("%s %s msg %s «%s»%s (%d chars) -> %s"
                        % (eid, "delivered" if not cmd or cmd.get("deliver", True) else "a command, handed over by "
                           "its own thread:", data.get("message_id"), data.get("sender"),
                           " ↩ msg %s" % data.get("reply_to") if data.get("reply_to") else "", len(line), args.session))
                    if not args.no_mark:
                        try:
                            if not bot_tok:
                                bot_tok = bot_token(args.bot)
                            mark_received(bot_tok, data.get("chat_id"), data.get("message_id"), mark)
                        except Exception as e:          # a mark is a courtesy; the delivery already happened
                            log("msg %s not marked (%s)" % (data.get("message_id"), str(e).replace(
                                bot_tok or "", "***")[:160]))
                    if args.once:
                        log("once: %d forwarded" % forwarded)
                        return 0
        except (ConnectionError, OSError) as e:
            log("redis or the door went away (%s); retrying in 5s" % e)
            r.close()
            time.sleep(5)
            if args.once:
                return 3


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except KeyboardInterrupt:
        sys.exit(0)
