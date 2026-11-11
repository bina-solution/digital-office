"""snapshot.py — «מצב» and «קדימה»: the office as one table, every part read at once, in about 20 seconds (DGO-1339).

The owner, 2026-11-04 (group msg 129): «קדימה אמור בתכלס לקבל תמונת מצב מלאה על המערכת במקביל גם פגישות גם משימות גם כל
מקביל גם מצב העדר גם שליטה ובקרה … בזמן אמת ובמהירות ואז אפשר לחשוב קדימה». Until then «קדימה» was an agent running five
`bbox` reads one after another (apps/operatives/operatives/office.forward.md) — the Plane read alone took 200 s, and his
screenshot of 11:37 that day shows it «Synthesizing…» with nothing on the screen yet.

EVERY PART AT ONCE (the collector's at_once, SNAP_DEADLINE each): a part that does not answer in time, or answers with
an error, is its own line «לא ענה: <why>» and never holds up the rest.
  * the herd and the work items — the collector's own state file, written every 20 s, Plane live every 30 s: no wait;
  * the meetings — the office herd.yaml runs meet on (`apps: meet:`), through the link: `/flow/api/meetings`;
  * «כל מקביל» — this office's any-concurrency: n8n's queues, and its runs of the last hour;
  * שליטה ובקרה — the security app of every office this one reaches (and its own): enforcing or only watching,
    and what is banned now;
  * stability — this office's notice centre: the errors not yet read.
The group's own part (his open requests) and the agents' sessions are added by the relay that asked
(apps/telegram/relay/commands.py): it holds the desk and the agent door, and this collector holds neither.

Served on the collector's unix socket (feed.py, GET /api/snapshot; the page's caddy routes it): read-only, one build
at a time, and an ask within SNAP_KEEP seconds of a build gets that build. Nothing in it is a secret: what the page's
own /data/state.json already serves on the office network, plus counts and titles.
"""
import concurrent.futures
import datetime
import glob
import json
import os
import re
import socket
import threading
import time

SNAP_DEADLINE = 18                 # one part's whole budget: the relay's answer is due in 30 s, the post included
SNAP_KEEP = 10                     # a second ask within this many seconds gets the same build
_lock = threading.Lock()
_last = {"at": 0.0, "doc": None}
#: the snapshot's own workers: its reads can outlive their deadline (urllib's timeout is per socket operation), and on
#: the collector's shared pool they would hold the workers its passes need (the second reader)
POOL = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="snapshot")


def at_once(fn, items, default, deadline, what=""):
    """[fn(item) for item in items], all at once on this module's pool; one not back within `deadline` is `default`."""
    futures = [POOL.submit(fn, it) for it in items]
    if futures:
        concurrent.futures.wait(futures, timeout=deadline)
    out = []
    for f in futures:
        if not f.done():
            f.cancel()
            out.append(default)
        else:
            out.append(default if f.exception() is not None else f.result())
    return out

ANY = os.environ.get("ANY_CONCURRENCY_URL", "http://any-concurrency:8080").rstrip("/")
NOTICES = os.environ.get("NOTIFICATIONS_URL", "http://notifications:8977").rstrip("/")
SECURITY = os.environ.get("SECURITY_URL", "http://security:8995").rstrip("/")
#: the state rows' words for what a dot means, as the page says them
WORD = {"up": "מחובר", "half": "מחובר, בלי פקודות", "away": "הקישור מכאן לא עונה", "down": "לא עונה", "none": "לא מקושר"}


def app_office(herd_path, app):
    """The office herd.yaml runs `app` on (`apps: <app>: <office>`), or ""."""
    try:
        with open(herd_path, encoding="utf-8") as fh:
            m = re.search(r"^apps:\s*$.*?^\s+%s:\s*([A-Za-z0-9_-]+)" % re.escape(app), fh.read(), re.M | re.S)
    except OSError:
        return ""
    return m.group(1) if m else ""


def herd_part(state):
    """Every office of OUR herd with its dot, from the collector's last pass (the clients' offices are the page's)."""
    rows = [r for r in state.get("computers") or [] if r.get("group") == "העדר שלנו"]
    if not rows:
        raise ValueError("the control centre has not written its first pass yet")
    out = []
    for r in rows:
        out.append({"name": r.get("name") or r.get("office") or "?", "state": r.get("state") or "none",
                    "why": r.get("why") or "", "since_ts": r.get("since_ts") or 0, "home": bool(r.get("home"))})
    return {"offices": out, "at": state.get("at") or 0}


def work_part(state):
    """The work items as the page counts them: what is in progress, what waits for the owner, today's opens and closes,
    and the topics that move most."""
    totals = state.get("totals")
    if not totals:
        raise ValueError((state.get("errors") or {}).get("plane") or "Plane has not been read yet")
    day = [f for f in state.get("feed") or [] if isinstance(f, dict) and f.get("ref")]
    topics = [{"name": t.get("name") or "", "done": t.get("done") or 0, "total": t.get("total") or 0}
              for t in (state.get("topics") or [])[:3]]
    return {"started": totals.get("started") or 0, "owner": totals.get("owner") or 0,
            "opened": sum(1 for f in day if f.get("kind") == "open"),
            "closed": sum(1 for f in day if f.get("kind") == "done"), "topics": topics,
            "late": (state.get("errors") or {}).get("plane") or ""}


def meetings_part(get, base):
    """The newest meetings of the office that runs meet: its own list (meet-start's /flow/api/meetings)."""
    got = get(f"{base}/flow/api/meetings", timeout=SNAP_DEADLINE - 2)
    if isinstance(got, dict) and "_error" in got:
        raise ValueError(got["_error"])
    rows = got if isinstance(got, list) else (got.get("meetings") or got.get("items") or []) if isinstance(got, dict) else []
    out = []
    for m in rows[:3]:
        if not isinstance(m, dict):
            continue
        out.append({"title": " ".join(str(m.get("title") or m.get("room") or "").split())[:60],
                    "room": m.get("room") or "", "started": str(m.get("started") or "")[:16],
                    "state": m.get("state") or m.get("status") or ""})
    return {"meetings": out, "count": len(rows)}


def concurrency_part(get):
    """n8n now (its queues) and its last hour (runs that failed, runs still going) — this office's any-concurrency."""
    q = get(f"{ANY}/api/queue", timeout=SNAP_DEADLINE - 2)
    if "_error" in q:
        raise ValueError(q["_error"])
    queues = (q.get("queues") or {}) if q.get("available", True) else {}
    runs = get(f"{ANY}/api/executions?hours=1", timeout=SNAP_DEADLINE - 2)
    runs = runs if isinstance(runs, list) else []
    return {"active": sum(v.get("active") or 0 for v in queues.values()),
            "waiting": sum((v.get("wait") or 0) + (v.get("delayed") or 0) for v in queues.values()),
            "hour": len(runs), "running": sum(1 for r in runs if r.get("status") in ("running", "new", "waiting")),
            "failed": sum(1 for r in runs if r.get("status") in ("error", "crashed", "failed"))}


def security_part(get, office, base):
    got = get(f"{base}/api/bans", timeout=SNAP_DEADLINE - 2)
    if "_error" in got:
        raise ValueError(got["_error"])
    now, day = time.time(), time.time() - 86400
    hist = [h for h in got.get("history") or [] if isinstance(h, dict) and float(h.get("ts") or 0) > day]
    return {"office": office, "mode": got.get("mode") or "?",
            "active": sum(1 for b in got.get("active") or [] if not b.get("until") or float(b["until"]) > now),
            "day": len(hist)}


def stability_part(get):
    """The unread errors, and the two most frequent problems among them — once each, with how often: a maker that
    re-sends one problem every minute (autoheal's refusal, 2026-11-05) is one problem, not the top two."""
    got = get(f"{NOTICES}/api/notifications?unread=1&level=error&limit=50", timeout=SNAP_DEADLINE - 2)
    if "_error" in got:
        raise ValueError(got["_error"])
    rows = got.get("notifications") or []
    seen = {}
    for r in rows:
        title = " ".join(str(r.get("title") or "").split())
        if title:                                   # counted by the whole title, cut only to be shown
            seen[title] = seen.get(title, 0) + 1
    top = sorted(seen.items(), key=lambda kv: -kv[1])[:2]
    return {"errors": len(rows), "top": [t[:70] if n == 1 else f"{t[:70]} (×{n})" for t, n in top]}


#: where a page of HTML begins (a door's 401 answers with its sign-in page): everything from here is not a reason
HTML_STARTS = re.compile(r"<!doctype|<html|<head|<body|<title|<meta", re.I)


def why_silent(text):
    """A part that did not answer, as one short line the owner can read — the cause in Hebrew, then the answer's own
    short words when there are any, but never a page of HTML and never more than a line. urllib's own errors are
    wrapped in «<urlopen error …>»: unwrapped, not cut away (the second reader, DGO-1329)."""
    text = str(text or "")
    text = re.sub(r"<urlopen error (.*?)>", r"\1", text, flags=re.S)
    cut = HTML_STARTS.search(text)
    text = " ".join((text[:cut.start()] if cut else text).split())
    m = re.search(r"HTTP (\d{3}):?\s*(.*)", text)
    code, said = (int(m.group(1)), m.group(2).strip()) if m else (0, "")
    words = f": {said[:50]}" if said else ""
    if code in (401, 403):
        return f"אין הרשאה (HTTP {code}{words})"
    if code == 404:
        return f"מה שנשאל לא נמצא שם (HTTP 404{words})"
    if code == 429:
        return "Plane ביקש להאט — המפתח של הלשכה מוצה לדקה (HTTP 429)"
    if code >= 500:
        return f"ענה בשגיאה (HTTP {code}{words})"
    if re.search(r"timed? ?out|TimeoutError", text, re.I):
        return "לא ענה בזמן"
    if re.search(r"Errno 111|Connection refused", text, re.I):
        return "השירות לא מקבל חיבור — כנראה לא רץ (החיבור נדחה)"
    if re.search(r"Errno -[23]|Name or service not known|Temporary failure in name resolution", text, re.I):
        return "השירות לא מנותב לכאן (השם שלו לא ידוע ברשת של הלשכה)"
    if re.search(r"No route to host|Network is unreachable", text, re.I):
        return "אין דרך אל השירות ברשת"
    if "has not been read yet" in text:
        return "עוד לא נקרא מאז שהאוסף עלה"
    return text[:90] or "לא ענה"


def _resolves(host):
    try:
        socket.getaddrinfo(host, None)
        return True
    except OSError:
        return False


def security_doors(door, registry):
    """(office, base) for every security app this office reaches: its own when it runs one, and each linked office's
    that the compiler routed here (.generated/registry/remote.<office>.security.json)."""
    out = []
    host = SECURITY.split("//", 1)[-1].split(":")[0]
    if _resolves(host):
        out.append(("", SECURITY))
    for path in sorted(glob.glob(os.path.join(registry, "remote.*.security.json"))):
        office = os.path.basename(path)[len("remote."):-len(".security.json")]
        url = door(office, "security")
        if url:
            out.append((office, url))
    return out


def build(state_path, get, door, herd_path, registry, labels=None, now=time.time, at_once=at_once, names=None):
    """The table's data: {"at", "parts": {name: data}, "silent": {name: why}}. Every read at once (at_once)."""
    try:
        with open(state_path, encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError) as e:
        state = {"_error": f"the control centre's state is not readable: {e}"}
    reads = [("herd", lambda: herd_part(state)), ("work", lambda: work_part(state)),
             ("concurrency", lambda: concurrency_part(get)), ("stability", lambda: stability_part(get))]
    silent = {}
    meet = app_office(herd_path, "meet")
    meet_base = door(meet, "meet") if meet else ""
    if meet_base:
        reads.append(("meetings", lambda: meetings_part(get, meet_base)))
    else:
        silent["meetings"] = f"הפגישות רצות ב-{meet or '?'}, והדלת שלהן לא מנותבת לכאן"
    # each security app under its HERD name (the Dell's link id is portable-ubuntu, its notices say dell — the group's
    # «חסום» matches the two by this name; `names` maps a link id to it, feed.snapshot_now builds it from herd.yaml)
    for office, base in security_doors(door, registry):
        office = (names or {}).get(office, office)
        reads.append((f"security:{office}", lambda o=office, b=base: security_part(get, o, b)))

    def run(item):
        name, fn = item
        try:
            return name, fn(), ""
        except Exception as e:                       # noqa: BLE001 — a part that fails is a line, never the table
            return name, None, str(e)[:160]

    got = at_once(run, reads, None, SNAP_DEADLINE, "snapshot reads")
    parts = {}
    for (name, _fn), res in zip(reads, got):
        if res is None:
            silent[name] = f"לא ענה תוך {SNAP_DEADLINE} שניות"
        elif res[2]:
            silent[name] = why_silent(res[2])
        else:
            parts[name] = res[1]
    sec = [parts.pop(k) for k in sorted(list(parts)) if k.startswith("security:")]
    if sec:
        parts["security"] = sec
    return {"at": int(now()), "parts": parts, "silent": silent}


def cached(make, now=time.time):
    """One build at a time, and the last one again within SNAP_KEEP seconds: a page and a relay asking together cost
    one round of reads."""
    with _lock:
        if _last["doc"] is not None and now() - _last["at"] < SNAP_KEEP:
            return _last["doc"]
        doc = make()
        _last.update(at=now(), doc=doc)
        return doc


# ── the table as the owner reads it in the group ────────────────────────────────────────────────────────
def israel_offset(ts):
    """Israel's own rule (since 2013), for an image with no zone database (a stock alpine python): summer time from the
    Friday before the last Sunday of March, 02:00, to the last Sunday of October, 02:00 — UTC+3; otherwise UTC+2."""
    y = time.gmtime(ts).tm_year

    def last_sunday(month):
        d = datetime.date(y, month + 1, 1) - datetime.timedelta(days=1)
        return d - datetime.timedelta(days=(d.weekday() + 1) % 7)
    start = datetime.datetime.combine(last_sunday(3) - datetime.timedelta(days=2), datetime.time(0), datetime.timezone.utc)
    end = datetime.datetime.combine(last_sunday(10), datetime.time(0), datetime.timezone.utc) - datetime.timedelta(hours=1)
    return 10800 if start.timestamp() <= ts < end.timestamp() else 7200


def tz_offset(ts):
    """Seconds east of UTC where the owner is (Asia/Jerusalem): the zone database when the image has one, Israel's own
    rule when it does not."""
    try:
        from zoneinfo import ZoneInfo
        off = datetime.datetime.fromtimestamp(ts, ZoneInfo(os.environ.get("GROUP_TZ", "Asia/Jerusalem"))).utcoffset()
        if off is not None:
            return int(off.total_seconds())
    except Exception:                                # noqa: BLE001 — no zone data: the rule below
        pass
    return israel_offset(ts)


def day_month(iso):
    """«4.11» — the day first, as it is read in Israel; "" when the time is not readable."""
    try:
        d = datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return f"{d.day}.{d.month}"
    except (TypeError, ValueError):
        return ""


def _pct(done, total):
    return f"{round(100 * done / total)}%" if total else "—"


def _hhmm(ts, tz_offset):
    return time.strftime("%H:%M", time.gmtime(ts + tz_offset)) if ts else ""


def lines(doc, labels=None, tz_offset=0):
    """The table, one line per part (Hebrew; a part that did not answer says so in its own line)."""
    labels = labels or {}
    p, s = doc.get("parts") or {}, doc.get("silent") or {}
    out = []
    h = p.get("herd")
    if h:
        offs = h["offices"]
        good = [o for o in offs if o["state"] in ("up", "half")]
        bad = [o for o in offs if o["state"] not in ("up", "half")]
        line = f"🐑 העדר: {len(good)} מתוך {len(offs)} מחוברים"
        for o in bad:
            since = f" (מ-{_hhmm(o['since_ts'], tz_offset)})" if o.get("since_ts") else ""
            line += f"\n   • {o['name']}: {WORD.get(o['state'], o['state'])}{since}" + (
                f" — {o['why'][:90]}" if o.get("why") else "")
        out.append(line)
    elif "herd" in s:
        out.append(f"🐑 העדר: לא ענה — {s['herd']}")
    w = p.get("work")
    if w:
        line = (f"🗂 משימות: {w['started']} בעבודה · {w['owner']} מחכות לך · "
                f"ב-24 השעות האחרונות נפתחו {w['opened']}, נסגרו {w['closed']}")
        if w["topics"]:
            line += "\n   " + " · ".join(f"{t['name'][:40]} {_pct(t['done'], t['total'])}" for t in w["topics"])
        if w.get("late"):
            line += f"\n   (הקריאה האחרונה מ-Plane נכשלה: {why_silent(w['late'])})"
        out.append(line)
    elif "work" in s:
        out.append(f"🗂 משימות: לא ענה — {s['work']}")
    m = p.get("meetings")
    if m:
        if m["meetings"]:
            out.append("📅 פגישות: " + " · ".join(
                f"{x['title'] or x['room']}" + (f" ({day_month(x['started'])})" if day_month(x["started"]) else "")
                for x in m["meetings"]))
        else:
            out.append("📅 פגישות: אין פגישות מוקלטות")
    elif "meetings" in s:
        out.append(f"📅 פגישות: לא ענה — {s['meetings']}")
    c = p.get("concurrency")
    if c:
        out.append(f"⚙️ כל מקביל: n8n — {c['active']} רצות עכשיו, {c['waiting']} ממתינות · בשעה האחרונה {c['hour']} ריצות"
                   + (f", {c['failed']} נכשלו" if c["failed"] else ", אף אחת לא נכשלה"))
    elif "concurrency" in s:
        out.append(f"⚙️ כל מקביל: לא ענה — {s['concurrency']}")
    sec = p.get("security") or []
    if sec:
        out.append("🛡 שליטה ובקרה: " + " · ".join(
            f"{labels.get(x['office'], x['office']) or 'כאן'} — {'אוכף' if x['mode'] == 'enforce' else 'צופה בלבד (לא חוסם בפועל)' if x['mode'] == 'observe' else x['mode']}, "
            f"{x['active']} חסומים" + (f", {x['day']} אירועים היום" if x["day"] else "") for x in sec))
    silent_sec = [k for k in s if k.startswith("security:")]
    for k in silent_sec:
        out.append(f"🛡 {labels.get(k[9:], k[9:]) or 'כאן'}: לא ענה — {s[k]}")
    st = p.get("stability")
    if st:
        out.append(f"🔔 יציבות: {st['errors']} שגיאות שלא נקראו" + (" — " + " · ".join(st["top"]) if st["top"] else ""))
    elif "stability" in s:
        out.append(f"🔔 יציבות: לא ענה — {s['stability']}")
    return out
