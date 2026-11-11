#!/usr/bin/env python3
#: commands — what the owner types in the group that the office does BY ITSELF, before any agent reads it (DGO-1329):
#:   «משימה: <מילים>»              a work item now: DGO-n and the link he opens, as a reply, within seconds
#:   «מצב»                          the office as one table — the herd, the work, the meetings, «כל מקביל», שליטה ובקרה,
#:                                  stability, his open requests, the agents — in about 20 seconds
#:   «קדימה» [אחרי <פגישה>]          the same table first, then the answerer takes it forward (the meeting's items, his
#:                                  open requests); every item it opens appears in the group by itself (dashboard-group)
#:   «חסום <כתובת>», or «חסום» as a reply to a notice that offered it   the truth of what the office that saw the
#:                                  address does with a ban: enforcing, or only watching
#
# WHY A PARSER BEFORE THE AGENT (the owner, 2026-11-03 12:40, group): «תבנה אוטומציות שבעצם מאפשרות ניהול מלא דרך הקבוצה
# יצירת משימות וגם פקודת קדימה … כל פעם שip חדש פונה אלינו … אני יכול גם להגיב אם לחסום»; and 2026-11-04 09:40: «קדימה
# אמור בתכלס לקבל תמונת מצב מלאה על המערכת במקביל … בזמן אמת ובמהירות». Until now each of these went to the answerer, a
# model session: a «משימה» was an item minutes later or never, and «קדימה» was five `bbox` reads one after another
# (the Plane read alone 200 s). A command with a fixed meaning needs no model: it is done here, in seconds, and the
# answerer is told what was done, so it never opens a second item or answers a table it did not make.
#
# WHO, AND WHEN. Only the owner's own account: the telegram app IS his account, so his messages carry `out: true`; the
# bot's answers and anyone else's do not. «מצב» and «קדימה» are commands only when they stand alone: as a REPLY to a
# message («מה המצב?» about that subject, «קדימה» to a proposal) they are the answerer's.
#
# ONCE, AND NEVER LOST (the second reader). The relay delivers at least once, so a command meets its message again
# after a reconnect. «משימה» is idempotent by itself — the item is found by its identity (external_id <chat>:<msg>)
# before one is made, and a POST that failed is looked up again before anything is said — and the reply goes out only
# when the desk holds no answer for the message yet. The table commands take a two-minute lease (SET NX EX) while they
# run and skip a message the desk shows answered. Their hand-over to the answerer is retried for minutes; what still
# fails stays an open request on the desk, and the sweep brings it back.
#
# WHAT IS NEVER DONE HERE. Nothing that changes another office: a linked office may read a security app and never write
# to it (platform-base/security guard_write), so «חסום» reads the mode of the office that saw the address and says
# what is true; the ban itself is that office's own act. An internal address is never posted: say_group's patterns
# mask it in place (the rest of the line still goes out).
#
# Environment: PLANE_URL (http://project-pln:80) PLANE_WORKSPACE (bina) GROUP_PLANE_PROJECT (DGO)
#              CONSOLE_PUBLIC_URL (https://console.staging.digital-office.co.il) CONSOLE_PLANE_MODULE (plane.hp-laptop)
#              DASHBOARD_URL (http://dashboard:80) CONNECTIONS_URL (http://connections:8990) GROUP_TZ (Asia/Jerusalem)
import ipaddress
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    import desk
except ImportError:              # the relay says it once; a command without the ledger still answers
    desk = None
try:
    import say_group
except ImportError:
    say_group = None

PLANE = os.environ.get("PLANE_URL", "http://project-pln:80").rstrip("/")
PLANE_WS = os.environ.get("PLANE_WORKSPACE", "bina")
PROJECT = os.environ.get("GROUP_PLANE_PROJECT", "DGO")
CONSOLE = os.environ.get("CONSOLE_PUBLIC_URL", "https://console.staging.digital-office.co.il").rstrip("/")
PLANE_MODULE = os.environ.get("CONSOLE_PLANE_MODULE", "plane.hp-laptop")
DASHBOARD = os.environ.get("DASHBOARD_URL", "http://dashboard:80").rstrip("/")
VAULT = os.environ.get("CONNECTIONS_URL", "http://connections:8990").rstrip("/")
BOT_API = os.environ.get("TELEGRAM_BOT_API", "https://api.telegram.org").rstrip("/")
LEASE = "dgo:desk:cmd:%s:%s"
LEASE_TTL = 300                  # a command running (Plane's retries included); after this a replay may run it again
TITLE_MAX = 200
SNAPSHOT_TIMEOUT = 25            # the snapshot's own parts are cut at 18 s; the table is due within 30 s
HAND_OVER = (0, 10, 20, 40, 60, 90)   # seconds before each try of a thread's hand-over to the answerer (~3.5 min)
RLM, LRI, PDI = "‏", "⁦", "⁩"   # a line that starts with «DGO-n» or an address stays right-to-left

TASK = re.compile(r"^\s*משימה(?:\s+חדשה)?\s*[:：\-–]\s*(?P<words>\S.*)$", re.S)
STATUS = re.compile(r"^\s*(?:מה\s+ה)?מצב\s*[?!.]*\s*$")
FORWARD = re.compile(r"^\s*(?:ו?יאללה\s+)?קדימה(?![\w])[\s,.:!\-–]*(?P<rest>.*)$", re.S)
BAN = re.compile(r"^\s*חסום(?![\w])\s*[:\-–]?\s*(?P<ip>\S+)?\s*$")


def log(msg: str) -> None:
    print("[commands] " + time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + " " + msg, flush=True)


def lost(e: Exception) -> bool:
    """A redis connection that is GONE (the loop must reconnect and read the message again) — as opposed to a redis that
    answered with a refusal (full, read-only), which is the ledger's problem and never the message's."""
    if isinstance(e, ConnectionError) and str(e).startswith("redis refused"):
        return False
    return isinstance(e, (ConnectionError, OSError))


def ltr(s) -> str:
    """An address or an id inside a Hebrew line, kept left-to-right without turning the line around."""
    return LRI + str(s) + PDI


# ── what a message is ─────────────────────────────────────────────────────────────────────────────────────────
def is_ip(s: str) -> bool:
    try:
        ipaddress.ip_address(s)
        return True
    except ValueError:
        return False


def parse(data: dict):
    """(verb, argument) for a command of the OWNER's, or None. Only his own account's messages (`out`)."""
    if not data or not data.get("out"):
        return None
    text = (data.get("text") or "").strip()
    if not text:
        return None
    m = TASK.match(text)
    if m:
        return "task", m.group("words").strip()
    reply = bool(data.get("reply_to"))
    if STATUS.match(text) and not reply:
        return "status", ""
    m = FORWARD.match(text)
    if m and not reply:
        return "forward", " ".join(m.group("rest").split())
    m = BAN.match(text)
    if m:
        ip = (m.group("ip") or "").strip().rstrip(".!")
        if ip and not is_ip(ip):
            return None
        if ip or reply:
            return "ban", ip
    return None


# ── the ledger, best effort ───────────────────────────────────────────────────────────────────────────────────
def answered(r, data) -> list:
    """The bot's answers the desk holds for this message ([] when none, or when the desk cannot say)."""
    if desk is None:
        return []
    try:
        return desk.answers_of(r, data.get("chat_id"), data.get("message_id"))
    except Exception as e:                       # noqa: BLE001
        if lost(e):
            raise
        return []


def ledger(r, what: str, fn):
    """One write of the desk's: done, or logged — a full redis costs the record, never the command's answer. A lost
    connection is raised, so the loop reconnects (the main loop's) or the thread gives up its own."""
    if desk is None:
        return None
    try:
        return fn()
    except Exception as e:                       # noqa: BLE001
        if lost(e):
            raise
        log("the desk did not take %s (%s)" % (what, str(e)[:160]))
        return None


def lease(r, data) -> bool:
    """True when this run may do the table command: no answer on the desk, and no other run of it in the last
    LEASE_TTL seconds. A redis that refuses the write lets it run (once is worth more than never)."""
    if answered(r, data):
        return False
    try:
        return r.cmd("SET", LEASE % (data.get("chat_id"), data.get("message_id")), str(int(time.time())),
                     "NX", "EX", LEASE_TTL) == "OK"
    except Exception as e:                       # noqa: BLE001
        if lost(e):
            raise
        log("msg %s: the lease was not written (%s) — the command runs" % (data.get("message_id"), str(e)[:120]))
        return True


# ── the small things every command needs ──────────────────────────────────────────────────────────────────────
def http_json(url: str, body=None, headers=None, timeout: float = 20, method: str = None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method or ("POST" if data is not None else "GET"),
                                 headers=dict({"content-type": "application/json; charset=utf-8"}, **(headers or {})))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
        return json.loads(raw) if raw.strip() else {}


def vault_secret(instance: str) -> dict:
    got = http_json("%s/api/instances/%s/secret" % (VAULT, urllib.parse.quote(instance)), timeout=15)
    return (got or {}).get("secret") or {}


def local_time(ts: float) -> str:
    """HH:MM where the owner is (Asia/Jerusalem), the zone database's when the image has one."""
    try:
        from zoneinfo import ZoneInfo
        import datetime
        return datetime.datetime.fromtimestamp(ts, ZoneInfo(os.environ.get("GROUP_TZ", "Asia/Jerusalem"))).strftime("%H:%M")
    except Exception:                            # noqa: BLE001 — no zone data in a slim image: Israel's winter time
        return time.strftime("%H:%M", time.gmtime(ts + 2 * 3600))


def clean(text: str) -> str:
    """The reply with every internal address masked in place (say_group's own patterns) — the line still goes out."""
    if say_group is None:
        return text
    for pattern, _what in say_group.INTERNAL:
        text = pattern.sub("[כתובת פנימית]", text)
    return text


class Bot:
    """The bot's own voice: replies in the group, and the marks. The token from the vault, in memory, re-read hourly."""

    def __init__(self, token_fn):
        self.token_fn, self.tok, self.at = token_fn, "", 0.0

    def token(self) -> str:
        if not self.tok or time.time() - self.at > 3600:
            self.tok, self.at = self.token_fn(), time.time()
        return self.tok

    def reply(self, chat_id, message_id, text: str):
        """The message id of the reply, or None. Internal addresses are masked first (clean)."""
        body = {"chat_id": chat_id, "text": clean(text)[:4000], "disable_web_page_preview": True,
                "reply_parameters": {"message_id": int(message_id), "allow_sending_without_reply": True}}
        try:
            got = http_json("%s/bot%s/sendMessage" % (BOT_API, self.token()), body, timeout=30)
            return ((got or {}).get("result") or {}).get("message_id")
        except Exception as e:                   # noqa: BLE001 — said without the token
            log("msg %s: the reply was not sent (%s)" % (message_id, str(e).replace(self.tok or "\0", "***")[:160]))
            return None

    def mark(self, chat_id, message_id, emoji: str) -> None:
        """The desk's mark on his message (desk.MARKS) — a courtesy: a failure is logged, never raised."""
        if desk is None or not emoji:
            return
        try:
            desk.set_mark(self.token(), chat_id, message_id, emoji)
        except Exception as e:                   # noqa: BLE001
            log("msg %s: not marked %s (%s)" % (message_id, emoji, str(e).replace(self.tok or "\0", "***")[:80]))


# ── «משימה: …» — a work item, at once ─────────────────────────────────────────────────────────────────────────
class LookupUnanswered(RuntimeError):
    """Plane did not answer whether the message already has its item — nobody may say «there is none»."""


class Plane:
    """Plane's API on the office that runs it, with the office's own key — the one `bbox project-pln` uses."""

    def __init__(self):
        self.key, self.pid = "", ""
        self.base = "%s/api/v1/workspaces/%s" % (PLANE, PLANE_WS)
        self.pause = time.sleep

    def call(self, path: str, body=None, timeout: float = 20):
        # the office's key is shared (bbox project-pln, the control centre's feed) and Plane allows it 60 requests a
        # minute: a 429 waits what Plane says (at most 10 s) and asks again, twice; a 401 reads the key again, once
        for attempt in range(3):
            if not self.key:
                self.key = str(vault_secret("plane_local_api_token-local").get("token") or "").strip()
                if not self.key:
                    raise RuntimeError("the vault holds no plane_local_api_token-local")
            try:
                return http_json(self.base + path, body, headers={"X-API-Key": self.key}, timeout=timeout)
            except urllib.error.HTTPError as e:
                if e.code == 401 and attempt == 0:
                    self.key = ""
                    continue
                if e.code != 429 or attempt == 2:
                    raise
                try:
                    wait = min(10.0, float(e.headers.get("Retry-After") or 5))
                except (TypeError, ValueError):
                    wait = 5.0
                time.sleep(wait)
        raise RuntimeError("Plane did not answer")

    def project(self) -> str:
        if not self.pid:
            got = self.call("/projects/")
            rows = got.get("results", got) if isinstance(got, dict) else got
            self.pid = next((p["id"] for p in rows or [] if p.get("identifier") == PROJECT), "")
            if not self.pid:
                raise RuntimeError("no Plane project %s" % PROJECT)
        return self.pid

    def find(self, ext: str):
        """The item that carries this identity, or None (Plane answers the one item, or 404)."""
        try:
            got = self.call("/projects/%s/issues/?external_source=telegram&external_id=%s"
                            % (self.project(), urllib.parse.quote(ext)))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise
        rows = got.get("results") if isinstance(got, dict) and "results" in got else (
            [got] if isinstance(got, dict) and got.get("id") else got)
        return next((i for i in rows or [] if isinstance(i, dict) and i.get("external_id") == ext), None)

    def item_for(self, chat_id, message_id, title: str, body_html: str) -> tuple:
        """(the item, made_now): the item this message already has, or a new one. Never two items for one message: a
        POST that timed out or failed may have been stored, so it is looked up again before anything else is said
        (plan.py does the same, the reason in its own words)."""
        ext = "%s:%s" % (chat_id, message_id)
        hit = self.find(ext)
        if hit:
            return hit, False
        try:
            made = self.call("/projects/%s/issues/" % self.project(),
                             {"name": title, "description_html": body_html, "priority": "medium",
                              "external_source": "telegram", "external_id": ext}, timeout=30)
            return made, True
        except Exception as e:                   # noqa: BLE001 — stored or not, Plane is asked before we say a word
            self.pause(5)                        # a create that timed out may still be committing
            try:
                hit = self.find(ext)
            except Exception as e2:              # noqa: BLE001
                raise LookupUnanswered("the create failed (%s) and the lookup did not answer either (%s)"
                                       % (str(e)[:80], str(e2)[:80]))
            if hit:
                return hit, True
            raise

    def link(self, item: dict) -> str:
        return "%s/#/m/%s/%s/projects/%s/issues/%s" % (CONSOLE, PLANE_MODULE, PLANE_WS, self.project(), item.get("id"))


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def task_title(words: str) -> str:
    first = " ".join((words.strip().splitlines() or [""])[0].split())
    return first if len(first) <= TITLE_MAX else first[:TITLE_MAX - 1] + "…"


def task_body(words: str, data: dict, at: str) -> str:
    paras = "".join("<p>%s</p>" % esc(p.strip()) for p in words.strip().splitlines() if p.strip())
    src = "מהקבוצה «Bina Solutions Main», הודעה %s של %s, %s UTC (נפתח מ«משימה:» בלי סוכן — commands.py)." % (
        data.get("message_id"), esc(str(data.get("sender") or "")), at[:16].replace("T", " "))
    if data.get("media"):
        src += " ההודעה באה עם קובץ — הוא בקבוצה, בהודעה הזאת."
    return paras + "<p>%s</p>" % src


# ── the context the relay hands in ────────────────────────────────────────────────────────────────────────────
class Context:
    """What a command needs from the relay: a NEW redis connection for a thread (the relay's own socket is the
    loop's alone), the door to the answerer, the bot, and the agents' sessions."""

    def __init__(self, redis_fn, deliver, bot, sessions_fn=None, plane=None, pause=time.sleep):
        self.redis_fn, self.deliver, self.bot = redis_fn, deliver, bot
        self.sessions_fn = sessions_fn or (lambda: [])
        self.plane = plane or Plane()
        self.pause = pause

    def hand_over(self, text: str, msg) -> bool:
        """The message to the answerer, tried again for minutes (a send in flight, a door restarting). False when it
        never went: the request stays open on the desk, and the sweep brings it back."""
        for wait in HAND_OVER:
            if wait:
                self.pause(wait)
            try:
                self.deliver(text)
                return True
            except Exception as e:               # noqa: BLE001
                log("msg %s: not handed to the answerer yet (%s)" % (msg, str(e)[:120]))
        log("msg %s: never handed to the answerer — the desk's sweep brings it back" % msg)
        return False


def _record(r, data):
    return ledger(r, "the record", lambda: desk.load(r, data.get("chat_id"), data.get("message_id")))


def _move(r, data, ctx, verb: str, fn, mark: str) -> bool:
    """A record's move (take, drop) stored and marked — best effort. True when it moved."""
    rec = _record(r, data)
    if not rec or rec.get("state") not in desk.OPEN:
        return False
    try:
        fn(rec)
    except ValueError as e:                      # the record's own rule refused it (desk.py): said, not raised
        log("msg %s: %s refused by the desk (%s)" % (data.get("message_id"), verb, e))
        return False
    ledger(r, verb, lambda: desk.store(r, rec))
    ctx.bot.mark(data.get("chat_id"), data.get("message_id"), mark)
    return True


def do_task(r, ev, words: str, ctx) -> dict:
    data = ev.get("data") or {}
    chat, msg = data.get("chat_id"), data.get("message_id")
    title = task_title(words)
    try:
        item, new = ctx.plane.item_for(chat, msg, title, task_body(words, data, str(ev.get("at") or "")))
    except Exception as e:                       # noqa: BLE001 — said to him and to the answerer, never swallowed
        why = str(e)[:160]
        log("msg %s: «משימה» — no item (%s)" % (msg, why))
        before = answered(r, data)
        sent = None if before else ctx.bot.reply(
            chat, msg, RLM + "⚠️ לא נפתח פריט: Plane לא ענה עכשיו. הבקשה עברה לסוכן, והוא יפתח אותו.")
        if sent:
            ledger(r, "the answer", lambda: desk.add_answer(r, chat, msg, sent))
        told = ("he already has an answer to this message" if before else
                "he was told Plane did not answer (msg %s)" % sent if sent else "he was NOT told — tell him")
        # what is KNOWN: Plane answered «no such item» only when the lookups themselves answered
        known = isinstance(e, urllib.error.HTTPError) and not isinstance(e, LookupUnanswered)
        return {"mark": "", "note": "commands: «משימה» — the relay made no item (%s). %s Then open ONE (`./bbox "
                                    "project-pln report`) and `desk take %s DGO-…`; %s." % (
                                        why, "Plane says it holds none for this message." if known else
                                        "Plane did not answer whether this message already has one: look first — the "
                                        "relay writes «הודעה %s» in the item's description." % msg, msg, told)}
    ref = "%s-%s" % (PROJECT, item.get("sequence_id"))
    sent = None
    if not answered(r, data):                    # a replay of a message already answered says nothing again
        sent = ctx.bot.reply(chat, msg, RLM + "📌 %s · %s\n%s" % (ref, title, ctx.plane.link(item)))
        if sent:
            ledger(r, "the answer", lambda: desk.add_answer(r, chat, msg, sent))
    _move(r, data, ctx, "take", lambda rec: desk.take(rec, [ref], by="commands"), "✍")
    log("msg %s: «משימה» → %s (%s)%s" % (msg, ref, "new" if new else "it already had it",
                                          "" if sent else ", no reply sent now"))
    file_note = (" His message came with a file: put it on the item (`./bbox telegram media %s %s <path>`, then "
                 "`./bbox project-pln tasks attach %s <path>`)." % (chat, msg, ref)) if data.get("media") else ""
    told = ("answered him with its link (msg %s)" % sent) if sent else (
        "he already has an answer to this message" if answered(r, data) else "the reply did NOT go out — tell him DGO-n")
    return {"mark": "✍", "note": "commands: the relay ALREADY has %s for this «משימה» and %s. Do not open another item. "
                                 "It is a request of his like any other: do the work, or put a worker on it "
                                 "(DESK.md).%s" % (ref, told, file_note)}


# ── «מצב» / «קדימה» — the table, then (קדימה) the answerer ────────────────────────────────────────────────────
def snapshot_lines() -> tuple:
    """(the dashboard's table — apps/dashboard/snapshot.py — or one line saying why there is none, the owner's offset
    from UTC as the dashboard measured it, or None)."""
    try:
        got = http_json(DASHBOARD + "/api/snapshot", timeout=SNAPSHOT_TIMEOUT)
        off = got.get("tz_offset")
        return ([str(x) for x in got.get("lines") or []] or ["(מרכז הבקרה ענה בלי שורות)"],
                off if isinstance(off, int) else None)
    except Exception as e:                       # noqa: BLE001
        return ["🖥 מרכז הבקרה לא ענה: %s" % str(e)[:120]], None


def desk_line(r, t: float, this) -> str:
    """His open requests, without the message being answered now."""
    if desk is None:
        return ""
    recs = [x for x in ledger(r, "the open requests", lambda: desk.all_records(r)) or []
            if x.get("state") in desk.OPEN and str(x.get("message_id")) != str(this)]
    if not recs:
        return "💬 הקבוצה: אין בקשה פתוחה"
    old = min(recs, key=lambda x: desk.parse_at(x.get("at")))
    unanswered = sum(1 for x in recs if not x.get("answers"))
    return "💬 הקבוצה: %d בקשות פתוחות%s · הוותיקה: הודעה %s, לפני %s" % (
        len(recs), " (%d בלי תשובה)" % unanswered if unanswered else "", old.get("message_id"),
        desk.age(t - desk.parse_at(old.get("at"))))


def sessions_line(rows: list, t: float = None) -> str:
    """The agents of this office: who is working now (by title), and how many worked in the last day."""
    if rows is None:
        return "🤖 סוכנים: לא ענה"
    t = time.time() if t is None else t
    rows = [s for s in rows if isinstance(s, dict) and not s.get("blank")]
    busy = [s for s in rows if s.get("running") or s.get("queue")
            or str(s.get("state") or "").lower() in ("running", "busy", "working")]
    day = sum(1 for s in rows if desk is not None and t - desk.parse_at(s.get("updated_at") or "") < 86400)
    line = "🤖 סוכנים: %d עובדים עכשיו" % len(busy)
    if busy:
        line += " — " + " · ".join(" ".join(str(s.get("title") or s.get("id") or "").split())[:45] for s in busy[:4])
    if day:
        line += " · %d עבדו ב-24 השעות האחרונות" % day
    return line


def table(r, ctx, t: float, this=None) -> str:
    lines, off = snapshot_lines()
    when = time.strftime("%H:%M", time.gmtime(t + off)) if off is not None else local_time(t)
    out = ["📸 תמונת מצב · %s" % when] + lines
    try:
        line = desk_line(r, t, this)
    except Exception as e:                       # noqa: BLE001 — the thread's own connection: a line, not the table
        line = "💬 הקבוצה: לא נקראה — %s" % str(e)[:60]
    if line:
        out.append(line)
    try:
        out.append(sessions_line(ctx.sessions_fn(), t))
    except Exception as e:                       # noqa: BLE001
        out.append("🤖 סוכנים: לא ענה — %s" % str(e)[:80])
    # every LINE right-to-left — an entry's own lines too («   • vps1: …» starts with a Latin name)
    return "\n".join(RLM + line for x in out for line in str(x).split("\n"))


def run_table(ev, verb: str, rest: str, line_for_agent: str, ctx) -> None:
    """In its own thread, with its own redis: the table as a reply; «מצב» is then answered (👌), «קדימה» is handed to
    the answerer with the table, to be taken forward. Each part apart: a table that cannot be built is still a reply
    that says why, a desk that refuses costs the record, and the hand-over is tried for minutes."""
    data = ev.get("data") or {}
    chat, msg = data.get("chat_id"), data.get("message_id")
    t0 = time.time()
    r = None
    try:
        r = ctx.redis_fn()
    except Exception as e:                       # noqa: BLE001 — no redis: the table still goes out, without the desk
        log("msg %s: no redis for the table (%s)" % (msg, str(e)[:120]))
    text = table(r, ctx, t0, msg) if r is not None else "\n".join(RLM + x for x in ["📸 תמונת מצב"] + snapshot_lines()[0])
    sent = ctx.bot.reply(chat, msg, text)
    log("msg %s: «%s» → the table in %.1f s (%s)" % (msg, "מצב" if verb == "status" else "קדימה", time.time() - t0,
                                                   "msg %s" % sent if sent else "NOT sent"))
    try:
        if r is not None and sent:
            ledger(r, "the answer", lambda: desk.add_answer(r, chat, msg, sent))
            if verb == "status":
                _move(r, data, ctx, "drop", lambda rec: desk.drop(
                    rec, "«מצב» — the table, answered by the relay (msg %s)" % sent, by="commands"), "👌")
    except Exception as e:                       # noqa: BLE001 — the thread's connection went: the record waits
        log("msg %s: the desk was not updated (%s)" % (msg, str(e)[:120]))
    finally:
        if r is not None:
            try:
                r.close()
            except Exception:                    # noqa: BLE001
                pass
    if verb == "status":
        if not sent:                             # a table that never went out is the answerer's to answer
            ctx.hand_over(line_for_agent + "\ncommands: «מצב» — the relay's table did NOT go out (see its log). "
                          "Answer him with the state yourself.", msg)
        return
    focus = (" The focus he named: «%s»." % rest) if rest else ""
    posted = ("the table above is ALREADY posted as the reply (msg %s) — do not post it again" % sent) if sent else (
        "the table above did NOT go out — post it to him first (`./bbox telegram say-group --for %s`)" % msg)
    ctx.hand_over(line_for_agent + "\n" + text + "\ncommands: «קדימה» — %s. Now take it forward, in this turn:%s (1) a "
                  "meeting he named, or the newest meeting not yet processed: run the «קדימה» recipe "
                  "(apps/operatives/operatives/office.forward.md) — every item you open appears in the group by itself; "
                  "(2) then the oldest open requests of the desk." % (posted, focus), msg)


# ── «חסום» — the truth of a ban ───────────────────────────────────────────────────────────────────────────────
def offered_ban(reply_to):
    """(ip, office) of the «חסום» a notice in the group offered — dashboard-group keeps every posted notice that has
    answers by its message id (apps/dashboard/group.py, /data/group.json); office "" is the office that posted it.
    None when the message he answered offered no ban."""
    got = http_json(DASHBOARD + "/data/group.json", timeout=15)
    posted = ((got or {}).get("relay") or {}).get("posted") or {}
    n = posted.get(str(reply_to)) or {}
    for a in n.get("actions") or []:
        if a.get("op") == "security.ban" and (a.get("args") or {}).get("ip"):
            return a["args"]["ip"], n.get("office") or ""
    return None


def security_modes() -> dict:
    """{office: mode} of every security app the dashboard reaches ('' = its own office), from the snapshot."""
    got = http_json(DASHBOARD + "/api/snapshot", timeout=SNAPSHOT_TIMEOUT)
    return {x.get("office") or "": x.get("mode") or "?" for x in ((got.get("parts") or {}).get("security") or [])}


def run_ban(ev, ip: str, line_for_agent: str, ctx) -> None:
    """In its own thread (the snapshot it reads takes up to 25 s): the measured truth as a reply, the request carried
    under DGO-1329, then the message to the answerer."""
    data = ev.get("data") or {}
    chat, msg = data.get("chat_id"), data.get("message_id")
    office = None                                # None: typed by him, no notice says which office saw it
    if not ip and data.get("reply_to"):
        try:
            ip, office = offered_ban(data.get("reply_to")) or ("", None)
        except Exception as e:                   # noqa: BLE001
            log("msg %s: the notice it answers was not read (%s)" % (msg, str(e)[:120]))
    if not ip:
        sent = ctx.bot.reply(chat, msg, RLM + "לא מצאתי כתובת לחסום: ההודעה שענית עליה לא הציעה «חסום». "
                                              "אפשר לכתוב «חסום <כתובת>».")
        ctx.hand_over(line_for_agent + "\ncommands: «חסום» with no address the relay could find — %s." % (
            "he was told so (msg %s)" % sent if sent else "he was NOT told; tell him"), msg)
        return
    try:
        modes = security_modes()
    except Exception as e:                       # noqa: BLE001
        modes = {}
        log("msg %s: the security modes were not read (%s)" % (msg, str(e)[:120]))
    # the office the notice came from; typed by him, the public one — vps1 is where strangers' addresses arrive
    where = office if office is not None else ("vps1" if "vps1" in modes else next(iter(modes), ""))
    mode = modes.get(where, "")
    name = where or "הלשכה הזאת"
    if mode == "observe":
        text = ("🛡 %s: האבטחה של %s במצב צפייה — היא רושמת, ולא חוסמת אף כתובת בפועל. "
                "כדי שחסימה תעבוד צריך להעביר אותה לאכיפה (DGO-1329)." % (ltr(ip), ltr(name)))
    elif mode == "enforce":
        text = ("🛡 %s: %s אוכף חסימות, אבל לשכה מקושרת לא כותבת לאבטחה של לשכה אחרת (כך היא בנויה) — "
                "הבקשה נרשמה, והחסימה נעשית מ-%s עצמו (DGO-1329)." % (ltr(ip), ltr(name), ltr(name)))
    else:
        text = "🛡 %s: לא הצלחתי לקרוא את מצב האבטחה של %s עכשיו — הבקשה נרשמה (DGO-1329)." % (ltr(ip), ltr(name))
    sent = ctx.bot.reply(chat, msg, RLM + text)
    log("msg %s: «חסום %s» at %s (%s) — %s" % (msg, ip, where or "?", mode or "unread",
                                               "answered msg %s" % sent if sent else "NOT answered"))
    r = None
    try:
        r = ctx.redis_fn()
        if sent:
            ledger(r, "the answer", lambda: desk.add_answer(r, chat, msg, sent))
        _move(r, data, ctx, "take", lambda rec: desk.take(rec, ["DGO-1329"], by="commands"), "✍")
    except Exception as e:                       # noqa: BLE001
        log("msg %s: the desk was not updated (%s)" % (msg, str(e)[:120]))
    finally:
        if r is not None:
            try:
                r.close()
            except Exception:                    # noqa: BLE001
                pass
    ctx.hand_over(line_for_agent + "\ncommands: «חסום %s» — %s the measured truth (%s at %s) and carries it under "
                  "DGO-1329: a linked office never writes to another office's security, so a real ban is that office's "
                  "own act." % (ip, "the relay answered him (msg %s) with" % sent if sent else "his reply did NOT go out; "
                                "tell him", mode or "mode unread", where or "?"), msg)


# ── the one entry the relay calls ─────────────────────────────────────────────────────────────────────────────
def take(r, ev: dict, line_for_agent: str, ctx):
    """None when the message is not a command. Otherwise {"mark": the desk mark to set ("" = leave it), "note": what
    the answerer is told, "deliver": False when the command hands the message over itself, from its thread}."""
    data = ev.get("data") or {}
    cmd = parse(data)
    if cmd is None:
        return None
    verb, arg = cmd
    # one run per message at a time (the lease), and none for a message already answered: a replay of the stream
    # meets a command that ran, or is running — never a second item or a second table
    if not lease(r, data):
        log("msg %s: «%s» is answered or running — not again" % (data.get("message_id"), verb))
        return {"mark": "", "note": "commands: this «%s» is already answered or being answered by the relay (a replay "
                                    "of the stream); nothing to do for it." % verb, "deliver": False}
    if verb == "task":
        target, args = run_task, (ev, arg, line_for_agent, ctx)
    elif verb == "ban":
        target, args = run_ban, (ev, arg, line_for_agent, ctx)
    else:
        target, args = run_table, (ev, verb, arg, line_for_agent, ctx)
    # each command reads Plane or the snapshot (seconds to minutes when they are slow): in its own thread, so the next
    # message is never held behind it; each hands the message to the answerer itself, with what it did
    threading.Thread(target=target, args=args, daemon=True, name="%s-%s" % (verb, data.get("message_id"))).start()
    return {"mark": "", "note": "", "deliver": False}


def run_task(ev, words: str, line_for_agent: str, ctx) -> None:
    """«משימה» in its own thread, with its own redis: the item, the reply, the desk — then the answerer, told what was
    done (do_task's note)."""
    msg = (ev.get("data") or {}).get("message_id")
    r = None
    try:
        r = ctx.redis_fn()
        note = do_task(r, ev, words, ctx)["note"]
    except Exception as e:                       # noqa: BLE001 — the answerer still gets the message
        log("msg %s: «משימה» failed (%s)" % (msg, str(e)[:200]))
        note = ("commands: «משימה» — the relay's run broke (%s). Look for an item whose description says «הודעה %s» "
                "before opening one." % (str(e)[:120], msg))
    finally:
        if r is not None:
            try:
                r.close()
            except Exception:                    # noqa: BLE001
                pass
    ctx.hand_over(line_for_agent + "\n" + note, msg)
