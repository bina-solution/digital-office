#!/usr/bin/env python3
"""The control centre's relay to the owner's Telegram group (DGO-1329 step 2, DGO-1326).

The owner, 2026-11-03 (group msg 87): «וכל פעם שיש עדכון חשוב בכללי זה צריך לקפוץ פה» — and (DGO-1329) the path
he named: the apps' notices → the control centre → the main group. This is that path's last leg:

  * it FOLLOWS the office's event stream (flow.v1: every `dgo:flow:<app>` stream in redis — notifications
    publishes every notice that is news there, with its audience and its answers);
  * it DECIDES by a list that is data, group-events.json: the first rule that matches; a kind kept off the
    group, a link drop held three minutes for its return, how soon the same notice may come again, a cap
    per hour that the kinds which must arrive (an answer, a deploy, a link) do not count against;
  * it POSTS one line per event AS THE BOT («בוט טלגרם ראשי»), never as the owner: the telegram app's
    /api/send writes as his own account. The token is read from the vault when it is used, never kept on
    disk, and never printed — an error is redacted by its SHAPE (/bot…/), not by its value. A notice's
    answers are written under its line («↩️ אפשר להשיב להודעה הזו: «חסום»»), and the message id is kept
    with the notice, so a reply finds what it answers (steps 4–5).

A notice addressed to some people (`to`, as push.py reads meta.to) never goes to the group: the group is
everyone in it. A send that fails (Telegram, the vault or the telegram app away — a deploy is exactly that
moment) waits and is tried again for six hours, never dropped. The state is written after every send, so a
restart does not post the same line twice.

Each office relays its OWN stream, prefixed with its name: the HP's events from the HP, the Mac's from the Mac.
The group is DASHBOARD_GROUP_CHAT, or the watched group whose title is one of DASHBOARD_GROUP_NAMES (the owner's
main group, by its names) with the newest message — never any other watched chat, so a client's group can
never receive the office's alerts. ONE office posts — the one herd.yaml runs telegram on (`DASHBOARD_GROUP_RELAY=auto`;
`1`/`0` say it outright) — and it reads the other herd offices' notices over the link (Relay.far). A first start
begins at each stream's end: the past is on the board, not news; an event older than an hour when it is read
(the relay was down) is said with its age.

The standard library only, as feed.py: a stock python image, so the Mac (a command centre) builds nothing —
which is why it speaks redis's protocol (RESP) itself.
"""
import datetime
import glob
import hashlib
import json
import os
import re
import socket
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

STATE = os.environ.get("DASHBOARD_GROUP_STATE", "/data/group.json")
#: the control centre's own reading (feed.py): its «היום» lines are every work item that opened, closed or was
#: cancelled — read here from the shared volume, so Plane is read once, by the feed (DGO-1329 step 3)
FEED = os.environ.get("DASHBOARD_STATE", "/data/state.json")
HERD = os.environ.get("DASHBOARD_HERD", "/computers/herd.yaml")
#: work items belong to the herd, not to one office: every office's feed reads the ONE Plane, so only the office
#: that runs it (herd.yaml `apps: project-pln:`) posts them — "auto"; "1" / "0" say it outright
ITEMS = os.environ.get("DASHBOARD_GROUP_ITEMS", "auto").strip().lower()
ITEMS_PER_HOUR = 30          # item messages (each a pass's lines together), apart from the alarms' cap
RULES = os.environ.get("DASHBOARD_GROUP_RULES", os.path.join(os.path.dirname(os.path.abspath(__file__)), "group-events.json"))
OFFICE = os.environ.get("DGO_OFFICE_ID", "") or os.environ.get("DEPLOYMENT_NAME", "")
REDIS_HOST = os.environ.get("REDIS_HOST_INTERNAL", "redis")
TELEGRAM = os.environ.get("TELEGRAM_URL", "http://telegram:8984").rstrip("/")
CONNECTIONS = os.environ.get("CONNECTIONS_URL", "http://connections:8990").rstrip("/")
BOT_API = os.environ.get("TELEGRAM_BOT_API", "https://api.telegram.org").rstrip("/")
BOT_LABEL = "בוט טלגרם ראשי"
GROUP_NAMES = [t.strip() for t in os.environ.get(
    "DASHBOARD_GROUP_NAMES", "Bina Solutions Main|בינה פתרונות ראשי|בינה פיתרונות ראשי").split("|") if t.strip()]
PREFIX = "dgo:flow:"
#: the notice centre's event is `notice.<level>` (one publisher, flowpub; its data says `new` and `level`), and
#: `notice.new` is what Relay.far makes of a linked office's notice read over REST. Every `notice.*` is a notice.
NOTICE_TYPES = ("notice.new", "notice.recurred")
NOTICE_PREFIX = "notice."
BLOCK_MS = 15000
#: the linked offices' notice centres («התראות», alias `alerts`) that the compiler routed to this office — read over
#: the link every FAR_EVERY seconds (Relay.far): the office that holds the bot posts for the offices that do not
REGISTRY = os.environ.get("DASHBOARD_REGISTRY", "/registry")
FAR_EVERY = 15
POWER_EVERY = 60            # a laptop's power word is written every 30 s; the drop it explains is judged 13 min on
FAR_OVERLAP = 120           # seconds every far read looks behind its newest notice (Relay.far)
KEEP_POSTED = 500           # message id → notice, for the replies that answer them
RETRY_FOR = 6 * 3600        # a send that keeps failing is given up after this, and counted
STALE = 3600                # an event read this late is said with its age
TOKEN_SHAPE = re.compile(r"bot[0-9]{5,}:[A-Za-z0-9_\-]+")


#: AN ADDRESS OF AN OFFICE'S OWN PLUMBING IS NEVER SAID IN THE GROUP — the rule the relay's replies keep
#: (apps/telegram/relay/say_group.py INTERNAL; the two apps cannot import each other, so it is this list, a little
#: wider). Any notice may carry one — a take carries the merged commit's subject, and three of the last 2000
#: dgo-stable subjects held a private address, five a `.localhost` name — so every line is masked in place, its
#: title and body BEFORE they are cut (a cut address is no longer one), and it still says what happened. An address
#: that ends a sentence is still an address («…at 10.20.0.7.»).
PLUMBING = (
    re.compile(r"(?<![\w.-])[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*\.localhost(?::\d+)?(?![\w-]|\.\w)"),   # forge.console…
    re.compile(r"https?://[A-Za-z0-9_-]+:\d+"),                                          # http://notifications:8977
    re.compile(r"(?<![\w.-])localhost:\d{2,5}"),
    re.compile(r"(?<![\d.])(?:127(?:\.\d{1,3}){3}|0\.0\.0\.0)(?!\d|\.\d)"),             # the loopback, any address
    re.compile(r"(?<![\d.])(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01])|169\.254"
               r"|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7]))\.\d{1,3}\.\d{1,3}(?!\d|\.\d)"),
    re.compile(r"(?<![\w:])(?:f[cd][0-9a-f]{2}|fe[89ab][0-9a-f]):[0-9a-f:]*[0-9a-f](?![\w:])", re.I),   # v6 ULA, link
    re.compile(r"(?<![\w:])::1(?![\w:])"),
    # an office's own name as a host part AND a port (the git door, a linked office's service): git-accounts.macbook:9004
    re.compile(r"(?<![\w.-])[A-Za-z0-9_][\w-]*\.(?:macbook|hp-laptop|portable-ubuntu|vps1|dell)(?=:\d{2,5})"),
)
BARE_TOKEN = re.compile(r"(?<![\w:])\d{6,12}:[A-Za-z0-9_-]{30,}(?![\w-])")                 # a bot token, not in a URL


def redact(text):
    return BARE_TOKEN.sub("<token>", TOKEN_SHAPE.sub("bot<token>", str(text)))


def unplumbed(text):
    text = redact(text)
    for pattern in PLUMBING:
        text = pattern.sub("‹כתובת פנימית›", text)
    return text


# ── redis, spoken directly (RESP2): AUTH, SCAN, XREAD, XREVRANGE — nothing else ────────────────────────
class RedisError(Exception):
    pass


class Redis:
    def __init__(self, host, password, port=6379, timeout=30):
        self.s = socket.create_connection((host, port), timeout=timeout)
        self.f = self.s.makefile("rb")
        try:
            if password:
                self.call("AUTH", password)
        except Exception:
            self.close()
            raise

    def call(self, *args):
        out = [b"*%d\r\n" % len(args)]
        for a in args:
            b = a if isinstance(a, bytes) else str(a).encode()
            out += [b"$%d\r\n" % len(b), b, b"\r\n"]
        self.s.sendall(b"".join(out))
        return read_reply(self.f)

    def close(self):
        try:
            self.s.close()
        except OSError:
            pass


def read_reply(f):
    line = f.readline()
    if not line.endswith(b"\r\n"):
        raise ConnectionError("redis closed the connection")
    kind, rest = line[:1], line[1:-2]
    if kind == b"+":
        return rest.decode()
    if kind == b"-":
        raise RedisError(rest.decode())
    if kind == b":":
        return int(rest)
    if kind == b"$":
        n = int(rest)
        if n < 0:
            return None
        data = f.read(n + 2)
        if len(data) != n + 2:
            raise ConnectionError("redis closed the connection mid-reply")
        return data[:-2].decode("utf-8", "replace")
    if kind == b"*":
        n = int(rest)
        return None if n < 0 else [read_reply(f) for _ in range(n)]
    raise RedisError(f"unexpected reply {line[:40]!r}")


def streams(r):
    """Every flow.v1 stream — of TYPE stream: one stray key under the prefix must not stop every XREAD."""
    found, cur = set(), "0"
    while True:
        cur, keys = r.call("SCAN", cur, "MATCH", PREFIX + "*", "COUNT", 200, "TYPE", "stream")
        found.update(keys or [])
        if cur == "0":
            return sorted(found)


def last_id(r, stream):
    last = r.call("XREVRANGE", stream, "+", "-", "COUNT", 1)
    return last[0][0] if last else "0-0"


def events_of(reply):
    """XREAD's answer → [(stream, id, {field: value})]."""
    out = []
    for stream, entries in reply or []:
        for eid, flat in entries or []:
            out.append((stream, eid, dict(zip(flat[0::2], flat[1::2]))))
    return out


def id_time(eid):
    """A stream id's own time (its milliseconds part), or None."""
    try:
        return int(str(eid).split("-")[0]) / 1000.0
    except ValueError:
        return None


def iso_time(iso):
    """An ISO-8601 time (a notice's last_seen: its own `+00:00`, or GlitchTip's `Z`) as epoch seconds; 0.0 if unread."""
    try:
        return datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return 0.0


# ── deciding ─────────────────────────────────────────────────────────────────────────────────────────────
def load_rules(path=RULES):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def notice_of(fields):
    """A notice as the rules read it (its data, its level in lower case), or None for anything else."""
    if fields.get("type") not in NOTICE_TYPES and not str(fields.get("type") or "").startswith(NOTICE_PREFIX):
        return None
    try:
        d = json.loads(fields.get("data") or "{}")
    except ValueError:
        return None
    if not isinstance(d, dict):
        return None
    d["type"] = fields["type"]
    d["title"] = fields.get("title", "")
    d["level"] = str(d.get("level") or "info").lower()
    return d


def matches(when, n):
    for k, want in (when or {}).items():
        if k == "has_actions":
            if bool(n.get("actions")) != bool(want):
                return False
            continue
        if k == "source_id_prefix":
            sid = str(n.get("source_id") or "")
            if not any(sid.startswith(p) for p in ([want] if isinstance(want, str) else want)):
                return False
            continue
        have = n.get(k)
        if isinstance(want, list):
            if have not in want:
                return False
        elif have != want:
            return False
    return True


def rule_for(n, rules):
    if n is None or n.get("to"):     # not a notice; or addressed to some people — the group is everyone
        return None
    for rule in rules.get("rules", []):
        if matches(rule.get("when"), n):
            return rule
    return None


#: dgo-extend's link notice: `link-down-<peer>-<epoch the outage began>` — its body says «מאז HH:MM» in the container's
#: clock (UTC); the owner reads Israel's, so the line is said in his (DGO-1357: «מאז 12:16» was 14:16 for him)
LINK_SID = re.compile(r"^link-(?:down|up)-(?P<peer>.+)-(?P<since>\d{9,})$")
SINCE = re.compile(r"^מאז \d{1,2}:\d\d")
SAME_PEER = 1800            # one office's outage seen from another office within this is the same outage (DGO-1357)


def peer_of(n):
    """The office a link notice is about (dgo-extend's `link-down-<peer>-<since>`), or ""."""
    m = LINK_SID.match(str((n or {}).get("source_id") or "")) if (n or {}).get("source") == "dgo-extend" else None
    return m.group("peer") if m else ""


def since_of(n):
    m = LINK_SID.match(str((n or {}).get("source_id") or ""))
    return int(m.group("since")) if m else 0


#: the guards of a laptop's power agent (packaging/macos/power-agent.py) that release it to sleep: what the owner reads,
#: what the laptop did, and what brings it back. Any other guard — «the engine is not running» — is an outage: then
#: the office itself stopped. On a Mac whose agent cannot clear SleepDisabled (power-agent.py set_lid), a guard
#: releases nothing: the Mac runs until the battery is empty or the heat shuts it down — so both say «כבה או נרדם».
GUARDS_HE = ((re.compile(r"^battery below (\d+)%$"), "הסוללה ירדה מתחת ל־{0}%", "כבה או נרדם",
              "כדי שיחזור צריך לחבר אותו לחשמל"),
             (re.compile(r"^thermal pressure"), "המחשב התחמם", "כבה או נרדם",
              "כדי שיחזור צריך להעיר או להדליק אותו כשיתקרר"))
SLEEP_SAID_EVERY = 6 * 3600     # a laptop's sleep is said at most this often: one low battery is one line, not one a lid
#: the relay's own lines, which no rule of group-events.json names: Relay.rule finds them for a retry
OWN_RULES = {rid: {"id": rid, "post": True, "uncapped": True, "repeat_minutes": 0} for rid in ("hello", "items", "sleep")}


def power_word(got, now):
    """What asleep judges from another office's data/power.json, in its shapes — or None: a page served over the link
    is data. `read_at` is this office's own clock, the one its link notices are told in."""
    if not isinstance(got, dict) or not isinstance(got.get("guards"), list):
        return None
    try:
        at = float(got.get("at"))
    except (TypeError, ValueError, OverflowError):
        return None
    pct = got.get("percent")
    return {"at": at, "read_at": now, "lock": str(got.get("lock") or ""), "lid": str(got.get("lid") or ""),
            "guards": [str(g)[:120] for g in got["guards"]][:8],
            "percent": pct if isinstance(pct, (int, float)) and not isinstance(pct, bool) else None}


def asleep(power, since, own=False):
    """(why, how, back): why a laptop's link drop at `since` is a sleep, what it did and what brings it back — said
    to the group when `back`; ("", "", "") when it is an outage.

    Its last word, read over the link before the drop (read_power, power_word: its control centre's data/power.json,
    which feed.power_brief writes) and only a word from the quarter hour before the drop: timed by this office's own
    clock when the notice is this office's own (`own`), by the laptop's for another office's notice, so a drifting
    clock fails as an outage, never as a silence. A guard of its power agent (the battery floor, heat) released it:
    said, with the cause — the machine decided, and the owner may want to plug it in. The owner's policy (status.json
    `wanted`, after the guards — never what macOS happens to do) lets it sleep when locked or closed: his own act, not
    said. A laptop held awake that drops, an unknown guard, a word in any other shape: an outage (DGO-1357: «a
    laptop that announced sleep is not an outage»)."""
    try:
        if not isinstance(power, dict) or not since:
            return "", "", ""
        at = float(power["at"])
        t = float(power["read_at"]) if own and power.get("read_at") else at
        if not since - 900 <= t <= since + 120 or abs(float(power.get("read_at") or at) - at) > 900:
            return "", "", ""                              # not the word before the drop, or a word nobody rewrites
        why, first = [], len(GUARDS_HE)
        for g in power["guards"]:
            i = next((i for i, guard in enumerate(GUARDS_HE) if guard[0].search(g)), None)
            if i is None:
                return "", "", ""                          # the engine stopped, or a guard this does not know
            why.append(GUARDS_HE[i][1].format(*GUARDS_HE[i][0].search(g).groups()))
            first = min(first, i)                          # the battery's way back before the heat's
        if why:
            return " ו".join(why), GUARDS_HE[first][2], GUARDS_HE[first][3]
        if "sleep" in (power["lock"], power["lid"]):
            return "לפי המדיניות שלו הוא ישן כשהוא נעול או סגור", "נרדם", ""
    except (KeyError, TypeError, ValueError, AttributeError):
        pass
    return "", "", ""


def owner_time(ts):
    """HH:MM where the owner is — snapshot.py's rule (the zone database, else Israel's own rule)."""
    try:
        import snapshot
        return time.strftime("%H:%M", time.gmtime(ts + snapshot.tz_offset(ts)))
    except Exception:                                # noqa: BLE001 — Israel's winter time
        return time.strftime("%H:%M", time.gmtime(ts + 7200))


def line_of(n, rules, office=OFFICE, age=None):
    n = dict(n, title=unplumbed(n.get("title") or ""), body=unplumbed(n.get("body") or ""))   # before any cut
    return unplumbed(said_of(n, rules, office, age))[:4000]


def said_of(n, rules, office, age):
    if n.get("raw"):                 # a message made whole by its maker (the work items' pass)
        return str(n.get("title") or "")[:4000]
    icon = rules.get("levels", {}).get(str(n.get("level") or "info").lower(), "•")
    office = n.get("office") or office          # a linked office's notice is said under ITS name (Relay.far)
    who = rules.get("offices", {}).get(office, office)
    m = LINK_SID.match(str(n.get("source_id") or "")) if n.get("source") == "dgo-extend" else None
    if m and SINCE.match(str(n.get("body") or "")):
        n = dict(n, body=SINCE.sub("מאז " + owner_time(int(m.group("since"))), str(n["body"]), count=1))
    text = f"{icon} {who}: {' '.join(str(n.get('title') or '').split())}"
    if age and age >= STALE:
        text += f" (לפני {int(age // 3600)} שע׳)" if age >= 7200 else " (לפני כשעה)"
    body = " ".join(str(n.get("body") or "").split())
    if body and body not in text:
        text += "\n" + body[:300]
    labels = [f"«{a.get('label')}»" for a in n.get("actions") or [] if a.get("label")]
    if labels:
        text += "\n↩️ אפשר להשיב להודעה הזו: " + " או ".join(labels)
    return text[:4000]


#: HOW A WORK ITEM IS SAID IN THE GROUP (DGO-2102; the owner, 2026-11-19, of «📁 🐘 HP: ✅ DGO-2043 · בעלים · שלושה
#: קבצים… — bina-solution»: «זה ממש מכוער איך שזה עכשו»). Its name first, in Hebrew, so the line stays right to left;
#: its number after the name; one heading per kind instead of «נסגר:» on every line; the label a name opens with said
#: as what it means to him (בעלים → «מחכה לך» / «היה אצלך»), a lane's tag («azds ·») dropped; never a login.
ITEM_VERB = re.compile(r"^(נסגר|נפתח מחדש|נפתח|בוטל|התחיל)\s*:\s*")
#: «בעלים ·» / «בעלים:» is the owner's; a lowercase tag with «·» («azds ·», «exx102 ·», «exu101 ·») is a lane's or a
#: client's — said after the number, never dropped (it names whose item it is). A lowercase word with a COLON names the
#: subject («vps1: הדיסק מלא», «drive: rm|trash…») and stays in the name (the second reader, 1,880 plan names).
ITEM_LABEL = re.compile(r"^(?:(?P<owner>בעלים)\s*[·:]|(?P<tag>[a-z][a-z0-9-]{1,7})\s*·)\s+")
LOGIN = re.compile(r"^[A-Za-z0-9._@-]+$")    # Plane's own name for an account — the owner's, which agents also write as
ITEM_HEADS = {"open": ("נפתחה משימה", "נפתחו {n} משימות"), "done": ("נסגרה משימה", "נסגרו {n} משימות"),
              "cancel": ("בוטלה משימה", "בוטלו {n} משימות")}
ITEM_HEAD_ANY = ("משימה אחת", "{n} משימות")    # a kind group-events.json adds later: still a sentence, one said as one
ITEMS_SHOWN = 5          # lines of one kind in a message; the rest of that kind is a count under its own heading
NAME_MAX = 80            # feed.py cuts a name at 90 mid-word: cut earlier, at a word, and say so with «…»
RLM = "‏"           # Telegram sets a line's direction by its first letter: every line starts right to left


def cut_name(name):
    """A name that was or must be cut, at a whole word, never leaving a bracket or a quote open, said cut with «…»."""
    base = name[:NAME_MAX + 1] if len(name) > NAME_MAX else name
    if " " in base:
        base = base.rsplit(" ", 1)[0]       # the word after the last space was cut — or base's 81st letter is a space
    for opens, closes in (("(", ")"), ("«", "»"), ("[", "]")):
        if base.count(opens) > base.count(closes):
            base = base[:base.rfind(opens)]
    base = base.rstrip(" ,;:·—-\"'")
    return (base or name[:NAME_MAX]) + "…"


def item_line(kind, ref, text, by=""):
    """«• <name> <ref>», then the marks: «· נפתחה מחדש» on a reopen; on the owner's item «· מחכה לך» when it opens,
    «· היה אצלך» when it closes or is cancelled, «· שלך» otherwise; a lane's or client's tag; «— <name>» only when
    Plane names a person, not a login. A name with nothing in it is the number alone."""
    words = " ".join(str(text or "").split())
    verb = ITEM_VERB.match(words)
    name = words[verb.end():] if verb else words
    feed_cut = len(name) >= 89                   # feed.py cut it at 90, mid-word: measured before a tag comes off
    label = ITEM_LABEL.match(name)
    if label:
        name = name[label.end():]
    head, sep, _ = name.partition(" — ")
    clause = bool(sep) and len(head.strip()) >= 20   # «pairing.py — …» alone would say nothing: a short head stays whole
    if clause:
        name = head
    name = name.strip()
    if len(name) > NAME_MAX or (feed_cut and not clause):
        name = cut_name(name)
    marks = []
    if verb and verb.group(1) == "נפתח מחדש":
        marks.append("נפתחה מחדש")
    if label and label.group("owner"):
        marks.append("מחכה לך" if kind == "open" else "היה אצלך" if kind in ("done", "cancel") else "שלך")
    if label and label.group("tag"):
        marks.append(label.group("tag"))
    by = " ".join(str(by or "").split())
    who = f" — {by[:40]}" if by and not LOGIN.match(by) else ""
    body = f"{name} {ref}" if name else ref
    return f"{RLM}• {body}" + "".join(f" · {m}" for m in marks) + who


class Relay:
    """The decisions over time: holds, repeats, retries, the hourly cap. Pure — send() and save() are handed
    in, so the tests drive it with a clock and a list."""

    def __init__(self, rules, send, state=None, now=time.time, save=lambda: None):
        self.rules, self.send, self.now, self.save = rules, send, now, save
        st = state or {}
        self.last = st.get("last", {})                 # "source|source_id" → when it was posted
        self.holds = st.get("holds", {})               # pair key → {"due", "n", "rule", "at"}
        self.down_posted = st.get("down_posted", {})   # pair key → when its drop was posted
        self.pending = st.get("pending", [])           # sends that failed: {"n", "rule", "at", "tries", "next", "key"}
        self.sent = st.get("sent", [])                 # times of the last hour's capped posts
        self.held_back = st.get("held_back", 0)        # posts the cap kept off, said in the next line
        self.posted = st.get("posted", {})             # message id → {notice, actions}
        self.items_from = st.get("items_from")         # «היום» lines older than this are the past, not news
        self.items_seen = st.get("items_seen", {})     # ref → {"kind", "ts", "at"}: the last change posted for it
        self.items_sent = st.get("items_sent", [])     # times of the last hour's item messages
        self.hello = st.get("hello", False)            # «הממסר פעיל» was said here (say_on)
        self.far_seen = st.get("far_seen", {})         # linked office → the newest notice time read from it (far)
        self.peer_down = st.get("peer_down", {})       # an office that fell → when its drop was said (one line per outage)
        self.peer_up = st.get("peer_up", {})           # …and when its return was said
        self.power = st.get("power", {})               # a laptop's link id → its power agent's last word (read_power)
        self.slept = st.get("slept", {})               # a laptop's last sleep → {"since", "at", "said", "up"} (tick)
        self.counts = st.get("counts", {})
        for c in ("posted", "skipped", "flicker", "repeat", "capped", "retried", "given_up", "up_without_down"):
            self.counts.setdefault(c, 0)

    def state(self):
        return {"last": self.last, "holds": self.holds, "down_posted": self.down_posted, "pending": self.pending,
                "sent": self.sent, "held_back": self.held_back, "posted": self.posted, "counts": self.counts,
                "items_from": self.items_from, "items_seen": self.items_seen, "items_sent": self.items_sent,
                "hello": self.hello, "far_seen": self.far_seen, "peer_down": self.peer_down, "peer_up": self.peer_up,
                "power": self.power, "slept": self.slept}

    def far(self, office, rows):
        """A linked office's notices, read from its own notice centre over the link (`far_doors`): each one that is
        new, or came back, since the last read is taken as its stream would have said it — the same rules, said
        under THAT office's name. vps1 is where a stranger's address is seen and where the herd's hub watches the
        links (DGO-1329, DGO-1357), and its notices never reached the group: only the HP's own stream was read.
        The first read of an office only sets where its news begins: its past is on its board, not news — and an
        empty or unreadable first answer begins it NOW, never at the epoch (its last 50 would all come at once).

        A notice's time is stamped before its database commits it, so two at once can land in either order: every
        read looks FAR_OVERLAP seconds behind the newest time taken, and a notice already taken at that same time is
        skipped by its id. The watermark moves with each notice BEFORE it is taken, and a notice that cannot be
        taken is counted and passed — a failure never makes the ones before it post again."""
        def when(r):
            return iso_time(r.get("last_seen") or r.get("created_at"))

        def key_of(r):
            return f"{r.get('id')}@{r.get('last_seen') or r.get('created_at')}"
        rows = [r for r in rows or [] if isinstance(r, dict) and when(r)]
        newest = max([when(r) for r in rows] + [0.0])
        seen = self.far_seen.get(office)
        if not isinstance(seen, dict):                 # first read (or an old plain-number state): news from now —
            at = newest or self.now()                  # and what it saw inside the overlap is already the past
            self.far_seen[office] = {"at": at, "ids": [key_of(r) for r in rows if when(r) > at - FAR_OVERLAP]}
            return 0
        took, since, done = 0, seen["at"] - FAR_OVERLAP, set(seen.get("ids") or [])
        for r in sorted(rows, key=when):
            t, key = when(r), key_of(r)
            if t <= since or key in done:
                continue
            seen["at"] = max(seen["at"], t)
            done.add(key)
            seen["ids"] = [k for k in seen.get("ids") or [] if iso_time(k.split("@", 1)[-1]) > t - 2 * FAR_OVERLAP][-200:] + [key]
            meta = r.get("meta") if isinstance(r.get("meta"), dict) else {}
            to = meta.get("to")
            data = {"id": r.get("id"), "source": r.get("source") or "", "source_id": str(r.get("source_id") or ""),
                    "level": r.get("level") or "info", "body": str(r.get("body") or "")[:2000],
                    "link": r.get("link") or "", "to": [to] if isinstance(to, str) else (to or []),
                    "actions": meta.get("actions") if isinstance(meta.get("actions"), list) else [], "office": office}
            try:
                self.take({"type": "notice.new", "title": str(r.get("title") or ""),
                           "data": json.dumps(data, ensure_ascii=False)}, at=t)
                took += 1
            except Exception as e:                     # noqa: BLE001 — one bad notice is counted, never re-posted
                self.counts["far_failed"] = self.counts.get("far_failed", 0) + 1
                print(f"dashboard-group: a notice of {office} was not taken: {type(e).__name__}: {e}"[:300], flush=True)
        return took

    def items(self, feed):
        """The control centre's «היום» lines (feed.py's state.json `feed`): a work item that opened, closed or
        was cancelled is news — all of a pass's news in ONE message, with a budget of its own (a day of closes
        must never push an alarm out of the group).

        A line is news when it is a CHANGE for its item: another kind than the last one posted for it, later
        than it. Not a new time: Plane moves a closed item's completed_at when it is saved again, and the
        same close would come back as new (the second reader). A line with no `ref` is a link's (it comes
        from the stream). The first reading only sets where news begins, and a line read more than an hour
        after it happened (the relay was down) is the past too."""
        spec = self.rules.get("items") or {}
        kinds = spec.get("kinds") or {}
        if not kinds:
            return
        t = self.now()
        if self.items_from is None:
            self.items_from = t
            return
        news, fresh = {}, {}                            # kind → its lines, oldest first; ref → what it is now
        for line in sorted([f for f in feed or [] if isinstance(f, dict)], key=lambda f: float(f.get("ts") or 0)):
            ref, kind, ts = str(line.get("ref") or ""), line.get("kind"), float(line.get("ts") or 0)
            if not ref or kind not in kinds or ts < self.items_from or t - ts > STALE:
                continue
            was = fresh.get(ref) or self.items_seen.get(ref)
            if was and (was["kind"] == kind or ts <= was["ts"]):
                continue
            fresh[ref] = {"kind": kind, "ts": ts, "at": t}
            # who did it, when Plane names a person (feed.py by_of) — item_line keeps a name and drops a login
            news.setdefault(kind, []).append(item_line(kind, ref, line.get("text"), line.get("by")))
        if not news:
            return
        self.items_sent = [s for s in self.items_sent if t - s < 3600]
        if len(self.items_sent) >= int(spec.get("per_hour", ITEMS_PER_HOUR)):
            # not marked seen: the next pass with room says them; a counter of its own — the alarms' «capped» counts
            # alarms, and a feed rewritten every 30 s would count one held pass ninety times there
            self.counts["items_capped"] = self.counts.get("items_capped", 0) + 1
            return
        self.items_seen.update(fresh)
        out = []
        for kind in [k for k in ITEM_HEADS if k in news] + [k for k in news if k not in ITEM_HEADS]:
            # the owner's first: a line that waits on him is never the one a long pass leaves unnamed
            lines = sorted(news[kind], key=lambda s: not any(m in s for m in (" · מחכה לך", " · היה אצלך", " · שלך")))
            one, many = ITEM_HEADS.get(kind, ITEM_HEAD_ANY)
            out.append(f"{RLM}{kinds[kind]} " + (one if len(lines) == 1 else many.format(n=len(lines))))
            out += lines[:ITEMS_SHOWN]
            if len(lines) > ITEMS_SHOWN:
                out.append(f"{RLM}(ועוד {len(lines) - ITEMS_SHOWN} בלוח הבקרה)")
        text = "\n".join(out)
        self.items_sent.append(t)
        n = {"source": "plane", "source_id": f"items:{int(t)}", "level": "info", "title": text, "raw": True}
        self.post(n, OWN_RULES["items"], at=t)

    def rule(self, rid):
        """A rule by its id — group-events.json's, or one of the relay's own lines (a retry finds it here too, so a
        line that was uncapped stays uncapped when it is tried again)."""
        return next((r for r in self.rules.get("rules", []) if r.get("id") == rid), None) or OWN_RULES.get(rid, {})

    def take(self, fields, at=None):
        """One event of the stream. `at` is the event's own time (its stream id), so a hold runs from when
        the drop happened, not from when a relay that was down read it."""
        at = at or self.now()
        n = notice_of(fields)
        rule = rule_for(n, self.rules)
        if not rule or not rule.get("post"):
            self.counts["skipped"] += 1
            return
        pair = rule.get("pair")
        if pair:
            sid = str(n.get("source_id") or "")
            if sid.startswith(pair["down"]):
                key = (n["office"] + ":" if n.get("office") else "") + sid[len(pair["down"]):]
                self.holds[key] = {"due": at + float(rule.get("hold_seconds", 0)), "n": n, "rule": rule["id"], "at": at}
                return
            if sid.startswith(pair["up"]):
                key = (n["office"] + ":" if n.get("office") else "") + sid[len(pair["up"]):]
                v = self.slept.get(peer_of(n))
                if v and not v.get("up"):                       # back from its sleep, at the notice's own time: a
                    v["up"] = at                                # drop begun after it is judged anew (same_sleep)
                if self.holds.pop(key, None) is not None:      # back before the hold ran out: a flicker
                    self.counts["flicker"] += 1
                    return
                if self.down_posted.pop(key, None) is None:    # its drop never reached the group: nor does this
                    self.counts["up_without_down"] += 1
                    return
                peer = peer_of(n)
                if peer and self.now() - self.peer_up.get(peer, 0) < SAME_PEER:   # its return was said already
                    self.counts["merged"] = self.counts.get("merged", 0) + 1
                    return
                if peer:
                    self.peer_up[peer] = self.now()
        self.post(n, rule, at)

    def tick(self):
        """Holds whose time came are news now; failed sends whose time came are tried again.

        ONE LINE PER OUTAGE, however many offices saw it (DGO-1357): the HP and vps1 each judge their own link to the
        MacBook, and both say it. A drop that comes due while another office's drop of the SAME office is still held
        is said once, with both views; one that comes after the same office's drop was said (SAME_PEER) is remembered
        for its return and not said again — and its return, too, is said once."""
        for key, h in list(self.holds.items()):
            if key not in self.holds or h["due"] > self.now():
                continue                                       # merged into another office's line this tick
            del self.holds[key]
            peer, since = peer_of(h["n"]), since_of(h["n"])
            # A SLEEP IS NOT AN OUTAGE: no drop is said, so no return either. Its verdict holds for the other views
            # of the same drop (same_sleep): the word read since may be one from a brief wake, and would make the
            # rest of the same sleep an outage and its return.
            same = self.same_sleep(peer, since)
            why, how, back = ("", "", "") if same or not peer else \
                asleep(self.power.get(peer), since, own=not h["n"].get("office"))
            if same or why:
                self.counts["slept"] = self.counts.get("slept", 0) + 1
                if not same:
                    said = self.slept.get(peer, {}).get("said", 0)
                    if back and self.now() - said >= SLEEP_SAID_EVERY:     # uncapped, as the drop it stands for
                        self.post(self.sleep_line(peer, since, why, how, back), OWN_RULES["sleep"], h.get("at"))
                        said = self.now()                      # sent, or kept and tried again: said either way
                    self.slept[peer] = {"since": since, "at": self.now(), "said": said, "up": 0}
                for k in [k for k, m in self.holds.items() if peer_of(m["n"]) == peer
                          and self.same_sleep(peer, since_of(m["n"]))]:
                    del self.holds[k]                          # the other views of the same sleep, with it
                continue
            mates = [(k, m) for k, m in self.holds.items() if peer and peer_of(m["n"]) == peer]
            if peer and not mates and self.now() - self.peer_down.get(peer, 0) < SAME_PEER:
                self.down_posted[key] = self.now()             # said from another office: its return still pairs
                self.counts["merged"] = self.counts.get("merged", 0) + 1
                continue
            for k, _ in mates:
                del self.holds[k]
            n = self.merged([h["n"]] + [m["n"] for _, m in mates]) if mates else h["n"]
            if self.post(n, self.rule(h["rule"]), h.get("at"), key=key):
                for k, _ in mates:
                    self.down_posted[k] = self.now()
                if peer:
                    self.peer_down[peer] = self.now()
        for p in list(self.pending):
            if p["next"] > self.now():
                continue
            self.pending.remove(p)
            if self.now() - p["at"] > RETRY_FOR:
                self.counts["given_up"] += 1
                continue
            self.counts["retried"] += 1
            self.post(p["n"], self.rule(p["rule"]), p["at"], key=p.get("key"), tries=p["tries"])
        self.prune()

    def post(self, n, rule, at=None, key=None, tries=0):
        # a linked office's notice repeats only itself: vps1's self-update is not the HP's of ten minutes before
        k = (n["office"] + ":" if n.get("office") else "") + f"{n.get('source')}|{n.get('source_id')}"
        # …and ONE OPEN PROBLEM IS ONE MESSAGE: a maker that gives every repeat a new id (autoheal's refusal, sent once
        # a minute as `no-project:<epoch>` — three identical lines in seconds, msgs 284–286, 2026-11-05) still repeats
        # the same LINE, and under a rule's repeat window that line is said once, whatever its id
        said = "line:" + hashlib.sha1(line_of(n, self.rules).encode("utf-8")).hexdigest()[:16]
        t = self.now()
        rep = float(rule.get("repeat_minutes", 0)) * 60
        if not tries and rep and any(x in self.last and t - self.last[x] < rep for x in (k, said)):
            self.counts["repeat"] += 1
            return False
        capped = not rule.get("uncapped")
        if capped and not tries:
            self.sent = [s for s in self.sent if t - s < 3600]
            if len(self.sent) >= int(self.rules.get("per_hour", 20)):
                self.held_back += 1
                self.counts["capped"] += 1
                return False
        text = line_of(n, self.rules, age=(t - at) if at else None)
        if self.held_back and capped:
            text += f"\n(ועוד {self.held_back} עדכונים בשעה האחרונה — בלוח ההתראות)" if self.held_back > 1 \
                else "\n(ועוד עדכון אחד בשעה האחרונה — בלוח ההתראות)"
        mid = self.send(text)
        if mid is None:                       # tried again: 30 s, 1 min, 2 min … at most every 30 min
            self.pending.append({"n": n, "rule": rule.get("id"), "at": at or t, "tries": tries + 1, "key": key,
                                 "next": t + min(1800, 30 * 2 ** tries)})
            return False
        if capped:
            self.held_back = 0
            self.sent.append(t)
        self.last[k] = self.last[said] = t
        if key is not None:
            self.down_posted[key] = t
        self.counts["posted"] += 1
        if n.get("actions"):
            self.posted[str(mid)] = {"notice": n.get("id"), "source": n.get("source"),
                                     "source_id": n.get("source_id"), "actions": n.get("actions"), "at": t,
                                     "office": n.get("office") or ""}   # "" = this office, as snapshot.py says it
            for old in sorted(self.posted, key=lambda m: self.posted[m]["at"])[:-KEEP_POSTED]:
                del self.posted[old]
        self.save()
        return True

    def merged(self, ns):
        """One office's drop seen from several offices, as ONE message: the drop once, then each office's own view
        (its time in the owner's clock and its measured cause, line_of's body)."""
        offices = self.rules.get("offices", {})
        names = [offices.get(n.get("office") or OFFICE, n.get("office") or OFFICE) for n in ns]
        icon = self.rules.get("levels", {}).get(str(ns[0].get("level") or "info").lower(), "•")
        text = [f"{icon} {' '.join(str(ns[0].get('title') or '').split())} — {' ו-'.join(names)}"]
        for name, n in zip(names, ns):
            body = line_of(dict(n, actions=[]), self.rules).partition("\n")[2]
            text.append(f"{name}: {' '.join(body.split())}" if body else name)
        return dict(ns[0], raw=True, title="\n".join(text), actions=[])

    def same_sleep(self, peer, since):
        """Whether a drop of `peer` begun at `since` is another view of the sleep already judged: begun at most three
        minutes before that drop (each office measures its own link), before the verdict was made, and before the
        laptop was back. A drop begun later is a new one, judged by its own word — however soon after."""
        v = self.slept.get(peer) if peer else None
        return bool(v) and v.get("since", 0) - 180 <= since <= v.get("at", 0) \
            and not (v.get("up") and since >= v["up"])

    def sleep_line(self, peer, since, why, how, back):
        name = self.rules.get("offices", {}).get(peer, peer)
        return {"source": "dashboard", "source_id": f"sleep-{peer}-{since}", "level": "info", "raw": True,
                "title": f"💤 {name} {how} ב־{owner_time(since)}: {why}. זו לא תקלה בקישור — {back}."}

    def say_on(self):
        """A relay that never ran here says once that it is on (DGO-1329 step 1): the owner sees the path is live
        before the first alarm has to use it. Once per office: the state remembers it, so a restart is silent, and a
        send that fails is tried again like any other."""
        if self.hello:
            return False
        self.hello = True
        n = {"source": "dashboard", "source_id": "relay-on", "level": "info",
             "title": "הממסר לקבוצה פעיל: מעכשיו כל עדכון חשוב של הלשכה מגיע לכאן לבד"}
        return self.post(n, OWN_RULES["hello"])

    def prune(self):
        t = self.now()
        keep = max([float(r.get("repeat_minutes", 0)) for r in self.rules.get("rules", [])] + [0]) * 60
        self.last = {k: v for k, v in self.last.items() if t - v < keep}
        self.down_posted = {k: v for k, v in self.down_posted.items() if t - v < 7 * 24 * 3600}
        self.peer_down = {k: v for k, v in self.peer_down.items() if t - v < 86400}
        self.peer_up = {k: v for k, v in self.peer_up.items() if t - v < 86400}
        self.slept = {k: v for k, v in self.slept.items() if t - max(v.get("at", 0), v.get("said", 0)) < SLEEP_SAID_EVERY}
        self.items_seen = {k: v for k, v in self.items_seen.items() if t - v.get("at", 0) < 14 * 86400}


# ── the group and the bot ────────────────────────────────────────────────────────────────────────────────
def get_json(url, timeout=15):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def far_doors(registry=REGISTRY, herd=HERD, alias="alerts", by_link=False):
    """{herd office: http://alerts.<link id>:<port>} — every office OF OUR HERD whose notice centre the compiler routed
    here, at the port the SERVING office published (its registry record, as `bbox remote` and feed.door read it).
    A client's office (EXF, EXW) may be linked too: its notices are its own, never the owner's group (the second
    reader). The link names an office by its own id — the Dell is `portable-ubuntu` — and herd.yaml's aliases map
    it to the herd's name, so the line says «Dell». Another app's doors by `alias`; `by_link` keys them by the
    link's id, the name a link notice gives (peer_of)."""
    import feed                                     # its reader of herd.yaml's offices, not a second one
    ours = {}
    for oid, o in feed.herd_offices(herd).items():
        for name in [oid, *o.get("aliases", [])]:
            ours[name] = oid
    out = {}
    for path in sorted(glob.glob(os.path.join(registry, f"remote.*.{alias}.json"))):
        link_id = os.path.basename(path)[len("remote."):-len(f".{alias}.json")]
        try:
            with open(path, encoding="utf-8") as fh:
                rec = json.load(fh)
            port = int(rec.get("link_port") or rec.get("port") or 0)
        except (OSError, ValueError, TypeError, AttributeError):
            continue
        if link_id in ours and port:
            out[link_id if by_link else ours[link_id]] = f"http://{alias}.{link_id}:{port}"
    return out


def read_power(relay, doors, now=time.time):
    """Each herd laptop's last word on sleep, from its control centre (data/power.json, feed.power_brief). A read that
    fails keeps the word before it: a laptop asleep does not answer, and the word read before its link dropped is
    the one its drop is judged by (asleep). An office with no power agent has no such file, and nothing is kept."""
    for link_id, base in doors.items():
        try:
            word = power_word(get_json(f"{base}/data/power.json", timeout=5), now())
        except Exception:                                   # noqa: BLE001 — asleep, or no power agent there
            continue
        if word:
            relay.power[link_id] = word


def read_far(relay, doors, errors):
    """One read of every linked office's notices (its newest 50); an office that does not answer is an error in
    the state, never a stop."""
    for office, base in doors.items():
        try:
            got = get_json(f"{base}/api/notifications?limit=50", timeout=8)
            relay.far(office, got.get("notifications") if isinstance(got, dict) else got)
            errors.pop(office, None)
        except Exception as e:                              # noqa: BLE001 — said in the state
            errors[office] = redact(f"{type(e).__name__}: {e}")[:200]


def group_chat():
    """DASHBOARD_GROUP_CHAT, or — among the telegram app's watched groups whose title is one of the main group's
    names — the one with the newest message: a group that became a supergroup stays watched for its history
    (DGO-1318), and only the new one talks. Never another chat."""
    if os.environ.get("DASHBOARD_GROUP_CHAT"):
        return int(os.environ["DASHBOARD_GROUP_CHAT"])
    best = None
    for c in get_json(f"{TELEGRAM}/api/chats").get("chats", []):
        if not c.get("watched") or c.get("kind") != "group" or str(c.get("title", "")).strip() not in GROUP_NAMES:
            continue
        q = urllib.parse.urlencode({"chat_id": c["id"], "limit": 1})
        msgs = get_json(f"{TELEGRAM}/api/history?{q}").get("messages") or []
        at = msgs[-1].get("at", "") if msgs else ""
        if best is None or at > best[0]:
            best = (at, c["id"])
    if best is None:
        raise RuntimeError(f"no watched group named {' / '.join(GROUP_NAMES)} — set DASHBOARD_GROUP_CHAT")
    return best[1]


def bot_token():
    """DASHBOARD_BOT_INSTANCE, or the vault's telegram_bot labelled «בוט טלגרם ראשי», or the only one there is."""
    inst = os.environ.get("DASHBOARD_BOT_INSTANCE", "")
    if not inst:
        rows = get_json(f"{CONNECTIONS}/api/instances?protocol=telegram_bot")
        rows = rows.get("instances", rows) if isinstance(rows, dict) else rows
        rows = [r for r in rows if r.get("protocol") == "telegram_bot"]
        named = [r for r in rows if (r.get("label") or "").strip() == BOT_LABEL]
        pick = named or (rows if len(rows) == 1 else [])
        if not pick:
            raise RuntimeError(f"{len(rows)} telegram_bot instance(s) and none labelled «{BOT_LABEL}» — set DASHBOARD_BOT_INSTANCE")
        inst = pick[0]["id"]
    sec = get_json(f"{CONNECTIONS}/api/instances/{urllib.parse.quote(inst)}/secret").get("secret") or {}
    tok = str(sec.get("token") or sec.get("bot_token") or "").strip()
    if not tok:
        raise RuntimeError(f"{inst} holds no token")
    return tok


#: A WORK ITEM'S NUMBER OPENS IT (DGO-2102): the ONE form a person is given, `https://<the hub's console>/go/<ref>`
#: (G95, DGO-1433) — herd.yaml's hub_console; the console resolves it when it is opened, after a sign-in too. Only the
#: project codes that exist are numbers (the office's own and each client's `plane:`): «UTF-8», «HTTP-500», «INV-40013»
#: are words, and the console would answer them «not found» (the second reader's count: UTF 86, INV 21, PDF 12 …).
OWN_KEYS = ("DGO", "MEET")


def herd_links(herd=HERD):
    """(hub_console, the project codes) from herd.yaml; ("", OWN_KEYS) when it cannot be read."""
    hub, keys = "", set(OWN_KEYS)
    try:
        with open(herd, encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip("\n")
                m = re.match(r"""^hub_console:\s*["']?([A-Za-z0-9.-]+)["']?\s*(#.*)?$""", line)
                if m:
                    hub = m.group(1)
                k = re.match(r"""^\s+plane:\s*["']?([A-Z]{2,6})["']?\s*(#.*)?$""", line)
                if k:
                    keys.add(k.group(1))
    except OSError:
        pass
    return hub, keys


def hub_console(herd=HERD):
    """herd.yaml's `hub_console:` — the host every link a person is given opens on; "" when it cannot be read."""
    return herd_links(herd)[0]


def ref_links(text, hub, keys=OWN_KEYS):
    """Telegram's text_link entities, one per work item number in `text` — offsets and lengths in UTF-16 code units,
    as Telegram counts them (an emoji such as 📌 is two). A number after a Hebrew prefix («ו-DGO-1898») is one too."""
    if not hub or not keys:
        return []
    ref = re.compile(r"(?<![A-Za-z0-9])(?<![A-Za-z0-9]-)((?:" + "|".join(sorted(map(re.escape, keys), key=len, reverse=True))
                     + r")-\d{1,6})(?![A-Za-z0-9-])")
    out = []
    for m in ref.finditer(text):
        out.append({"type": "text_link", "offset": len(text[:m.start()].encode("utf-16-le")) // 2,
                    "length": len(m.group(1).encode("utf-16-le")) // 2, "url": f"https://{hub}/go/{m.group(1)}"})
    return out[:100]                        # Telegram's own limit on a message's entities


class Bot:
    def __init__(self):
        self.tok, self.tok_at, self.chat, self.chat_at, self.error = None, 0, None, 0, None
        self.hub, self.keys = herd_links()

    def post_message(self, form):
        body = urllib.parse.urlencode(form).encode()
        with urllib.request.urlopen(f"{BOT_API}/bot{self.tok}/sendMessage", data=body, timeout=30) as r:
            return json.load(r)

    def send(self, text):
        try:
            if not self.tok or time.time() - self.tok_at > 600:
                self.tok, self.tok_at = bot_token(), time.time()
            if not self.chat or time.time() - self.chat_at > 3600:
                self.chat, self.chat_at = group_chat(), time.time()
            form = {"chat_id": self.chat, "text": text, "disable_web_page_preview": "true"}
            links = ref_links(text, self.hub, self.keys)
            try:
                res = self.post_message({**form, "entities": json.dumps(links)} if links else form)
            except urllib.error.HTTPError as e:
                # a link is never why a line is not said: Telegram refusing the entities (400) is said again without
                # them, before the 400 below would read as «the group moved»
                if not (links and e.code == 400):
                    raise
                res = self.post_message(form)
            self.error = None
            return res["result"]["message_id"]
        except Exception as e:                              # noqa: BLE001 — said in the state, never raised
            msg = f"{type(e).__name__}: {e}"
            if self.tok:
                msg = msg.replace(self.tok, "<token>")
            self.error = redact(msg)[:300]
            print(f"dashboard-group: not sent: {self.error}", flush=True)
            if isinstance(e, urllib.error.HTTPError):
                if e.code in (401, 404):
                    self.tok = None
                if e.code in (400, 403):                    # not in that chat, or it moved: find the group again
                    self.chat = None
            return None


# ── the loop ─────────────────────────────────────────────────────────────────────────────────────────────
def write_state(doc):
    d = os.path.dirname(STATE) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".group-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False)
    os.replace(tmp, STATE)


def items_here(office=OFFICE, herd=HERD, mode=ITEMS):
    """Whether THIS office posts the work items: the one herd.yaml runs Plane on (`apps: project-pln: <id>`,
    by its id or an alias — feed.py's plane_base reads the same line), unless DASHBOARD_GROUP_ITEMS says."""
    return runs_here("project-pln", office, herd, mode)


def far_here(office=OFFICE, herd=HERD, mode=os.environ.get("DASHBOARD_GROUP_FAR", "auto").strip().lower()):
    """Whether THIS office posts the linked offices' notices (Relay.far): the one herd.yaml runs the group's own app
    on (`apps: telegram: <id>`), so each far notice is posted once and by one office — never by every office that
    can read it — unless DASHBOARD_GROUP_FAR says."""
    return runs_here("telegram", office, herd, mode)


def runs_here(app, office, herd, mode):
    if mode in ("1", "true", "yes", "on"):
        return True
    if mode in ("0", "false", "no", "off"):
        return False
    try:
        with open(herd, encoding="utf-8") as fh:
            m = re.search(r"^apps:\s*$.*?^\s+%s:\s*([A-Za-z0-9_-]+)" % re.escape(app), fh.read(), re.M | re.S)
    except OSError:
        return False
    if not m or not office:
        return False
    import feed                                     # its reader of herd.yaml's offices, not a second one
    where = m.group(1)
    names = {where}
    for oid, o in feed.herd_offices(herd).items():
        if oid == where or where in o.get("aliases", []):
            names |= {oid, *o.get("aliases", [])}
    return office in names


def read_state():
    try:
        with open(STATE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def main():
    st = read_state()
    # ONE sender (DGO-1357): the office that runs telegram posts its own stream and reads every other herd office's
    # notices over the link; any other office stays quiet — a laptop away or asleep must never be the one that tells,
    # and two senders would say every outage twice. "auto" decides by herd.yaml; "1"/"0" say it outright.
    mode = os.environ.get("DASHBOARD_GROUP_RELAY", "auto").strip().lower()
    if mode in ("0", "false", "no", "off") or (mode == "auto" and not far_here()):
        print("dashboard-group: off here (DASHBOARD_GROUP_RELAY=%s; the office herd.yaml runs telegram on posts)"
              % mode, flush=True)
        while True:                                         # the state is kept; only `on` says it is quiet
            write_state({**st, "on": False, "at": time.time()})
            time.sleep(60)
    cursors = st.get("cursors", {})
    first = not cursors
    bot = Bot()
    doc = {"err": None}
    far_errors = {}                                         # linked office → why its notices were not read

    def save():
        write_state({"on": True, "office": OFFICE, "at": time.time(), "cursors": cursors, "error": doc["err"],
                     "bot_error": bot.error, "far_errors": far_errors, "relay": relay.state()})

    relay = Relay(load_rules(), bot.send, st.get("relay"), save=save)
    relay.say_on()
    scanned, r, feed_at, far_at, power_at = 0, None, 0, 0, 0
    items, far = items_here(), far_here()
    print(f"dashboard-group: relaying {OFFICE or 'this office'}'s stream to the group as the bot"
          f"{' — and the herd’s work items (Plane runs here)' if items else ''}", flush=True)
    while True:
        try:
            r = r or Redis(REDIS_HOST, os.environ.get("REDIS_PASSWORD", ""))
            if time.time() - scanned > 60:
                for s in streams(r):
                    if s not in cursors:   # at the first start, its end now; a stream born since, all of it
                        cursors[s] = last_id(r, s) if first else "0-0"
                scanned, first = time.time(), False
            if cursors:
                ks = list(cursors)
                reply = r.call("XREAD", "COUNT", 100, "BLOCK", BLOCK_MS, "STREAMS", *ks, *[cursors[k] for k in ks])
                for stream, eid, fields in events_of(reply):
                    cursors[stream] = eid            # before the send: a restart never posts the same line twice
                    relay.take(fields, at=id_time(eid))
            else:
                time.sleep(15)
            if items:                                # the feed's file, when it was written again
                try:
                    m = os.path.getmtime(FEED)
                except OSError:                      # not written yet
                    m = feed_at
                if m != feed_at:
                    feed_at = m                      # a file that cannot be read is skipped, never retried in a loop
                    try:
                        with open(FEED, encoding="utf-8") as fh:
                            day = json.load(fh)
                        relay.items(day.get("feed") if isinstance(day, dict) else None)
                    except Exception as e:           # noqa: BLE001 — the stream and the retries go on regardless
                        print(f"dashboard-group: the feed's file was not read: {type(e).__name__}: {e}", flush=True)
            if far and time.time() - far_at >= FAR_EVERY:   # the linked offices' notices, over the link (Relay.far)
                far_at = time.time()
                read_far(relay, far_doors(), far_errors)
            if far and time.time() - power_at >= POWER_EVERY:   # each laptop's last word before a sleep (asleep)
                power_at = time.time()
                read_power(relay, far_doors(alias="dashboard", by_link=True))
            relay.tick()
            doc["err"] = None
        except Exception as e:                              # noqa: BLE001 — said in the state, then again
            doc["err"] = redact(f"{type(e).__name__}: {e}")[:300]
            print(f"dashboard-group: {doc['err']}", flush=True)
            if r:
                r.close()
            r = None
            time.sleep(10)
        save()


if __name__ == "__main__":
    main()
