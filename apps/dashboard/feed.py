#!/usr/bin/env python3
"""The control centre's collector (DGO-1124): one state file for the dashboard's page, every 20 seconds.

The owner, 2026-11-02: «I get up in the morning, I open the MacBook, and the first thing I see is every
computer, alive, connected, green». A computer's dot is three readings, all inside the office network and
all read-only:

  * the link: dgo-extend's /api/map, which lists every linked office with its state, the age of its
    last handshake, its label and its commit;
  * whether that office's own machine takes commands: its Computers app's built-in computer
    (`computer_local-local`) is `ok`, as it is on the Dell and vps1, or `no_ssh`, as it is on the HP.
    For this office the app is read at http://computers:8977; for a linked one at the link alias
    http://computers.<office>:9005, the same door `bbox remote` uses;
  * the herd's own declaration, apps/computers/herd.yaml (mounted read-only): who belongs, under what
    label, in what role. An office declared there and missing from the map is drawn as not linked,
    never left out.

Green is up and takes commands; sky is up with no command door; plum is down; hollow is not linked.
The feed («היום») is dgo-extend's /api/link/history — each time a link went down or came back — and every
work item of the last 24 hours that opened, started, closed or was cancelled, read live (plane_loop).

The standard library only: it runs on a stock python image, so the Mac (a command centre) builds nothing.
"""
import datetime
import glob
import http.server
import json
import math
import os
import re
import socketserver
import tempfile
import threading
import time
import urllib.error
import urllib.request

OUT = os.environ.get("DASHBOARD_STATE", "/data/state.json")
EVERY = int(os.environ.get("DASHBOARD_EVERY", "20"))
EXTEND = os.environ.get("DGO_EXTEND_URL", "http://dgo-extend:8983").rstrip("/")
COMPUTERS = os.environ.get("COMPUTERS_URL", "http://computers:8977").rstrip("/")
HERD = os.environ.get("DASHBOARD_HERD", "/herd.yaml")
REGISTRY = os.environ.get("DASHBOARD_REGISTRY", "/registry")
# Times are written as epoch seconds (`*_ts`, `at`) and the page shows them in the reader's own clock: an
# offset written here was an hour off on 2026-11-02 (the Mac reads UTC+3, it said +2).
# 15 min: a pass is some 80 requests and the whole DGO project in memory, and the Mac is an 8 GB machine
# (2026-11-02: its engine reached load 99 swapping); a topic's progress does not move by the minute
PLANE_EVERY = int(os.environ.get("DASHBOARD_PLANE_EVERY", "900"))
# …and between two full reads, ONE request every PLANE_LIVE_EVERY s: the items Plane changed last (the owner,
# 2026-11-03: «everything updates live in the control centre, every change in the work items, and I see how
# every item closes in today's log»). An item whose state moved is a line of today's log at once, and the
# topics' bars and the tiles move with it; more changed than one page holds brings the full read forward.
PLANE_LIVE_EVERY = int(os.environ.get("DASHBOARD_PLANE_LIVE_EVERY", "30"))
LIVE_PAGE = 50                                     # the items changed last, asked in one page
FULL_RETRY = 120                                   # a first full read that failed is tried again after this
DAY_LINES = 600                                   # today's log: every line of the last 24 h, up to this many
                                                  # (2026-11-03 held 300 by 02:30: 175 closed, 117 opened)
PLANE_WS = os.environ.get("PLANE_WORKSPACE", "bina")
PLANE_PROJECT = os.environ.get("DASHBOARD_PLANE_PROJECT", "DGO")
OWNER_LABEL = "בעלים"


def get(url, timeout=8):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:        # it answered: its own words beside the code, not just "HTTP Error 502"
        body = e.read(300).decode("utf-8", "replace").strip() if e.fp else ""
        return {"_error": f"HTTP {e.code}: {body}"[:200]}
    except Exception as e:                     # an office that does not answer is a reading, not a crash
        return {"_error": str(e)[:200]}


def herd_offices(path):
    """apps/computers/herd.yaml's `offices:` section: {id: {label, role, aliases}}.

    Read by hand because the image has no YAML library and this block is regular: two-space office keys,
    four-space fields, six-space `he:`. Anything this cannot read is left out, and the map still lists
    every linked office under its own label."""
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except OSError:
        return {}
    out, cur, inside, in_role = {}, None, False, False
    for raw in lines:
        line = raw.split(" #", 1)[0].rstrip()
        if not line.strip():
            continue
        if not line.startswith(" "):
            inside = line.startswith("offices:")
            continue
        if not inside:
            continue
        m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if m:
            cur, in_role = m.group(1), False
            out[cur] = {"label": cur, "role": "", "aliases": []}
            continue
        if cur is None:
            continue
        m = re.match(r"^    (label|aliases|role):\s*(.*)$", line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            in_role = key == "role" and not val
            if key == "label":
                out[cur]["label"] = val.strip("'\"")
            elif key == "aliases":
                out[cur]["aliases"] = [a.strip() for a in val.strip("[]").split(",") if a.strip()]
            continue
        m = re.match(r"^      he:\s*(.*)$", line)
        if m and in_role:
            out[cur]["role"] = m.group(1).strip().strip("'\"")
    return out


def local_state(url):
    """The office's own machine as its Computers app sees it: (state, reason).

    `probe=1`: without a probe the built-in computer carries no state at all (measured 2026-11-02 on vps1
    and fireplace, both of which take commands). The app caches a probe (COMPUTERS_PROBE_TTL, 20 s), so
    this costs one SSH round trip per office per pass at most. Offices are read one after another, so
    the timeout is short: four slow ones must still leave a write inside the health window (150 s)."""
    got = get(f"{url}/api/computers?probe=1", timeout=12)
    if "_error" in got:
        return "unreachable", "אפליקציית המחשבים לא ענתה"
    for c in got.get("computers") or []:
        if c.get("id") == "computer_local-local":
            return c.get("state") or ("ok" if c.get("ok") else "unknown"), c.get("reason") or ""
    return "unknown", ""


def door(office, alias="computers"):
    """http://<alias>.<office>:<port> — the port the SERVING office published for that app, from the
    compiler's own record (.generated/registry/remote.<office>.<alias>.json), as `bbox remote` reads it.
    Each linked office has its own port: a fixed one reaches whichever office owns it (measured: 9005 is
    the HP's, so vps1 and fireplace read as the HP)."""
    try:
        with open(os.path.join(REGISTRY, f"remote.{office}.{alias}.json"), encoding="utf-8") as f:
            rec = json.load(f)
        port = int(rec.get("link_port") or rec.get("port") or 0)
    except (OSError, ValueError):
        return ""
    return f"http://{alias}.{office}:{port}" if port else ""


def plane_base():
    """Plane's API through the door of the office that runs it (herd.yaml puts project-pln on the HP).
    No token: that office's door signs the request as the identity it declared for this one (the same
    contract `bbox project-pln` relies on, apps/project-pln/tasks.py token_for). A Plane of this office's
    own is http://plane:80.

    WHICH office is herd.yaml's to say (`apps: project-pln: <office>`): a client's office serves its own
    Plane over the link too, and the first registry file is FPG's (measured: 401 there)."""
    try:
        m = re.search(r"^apps:\s*$.*?^\s+project-pln:\s*([A-Za-z0-9_-]+)",
                      open(HERD, encoding="utf-8").read(), re.M | re.S)
    except OSError:
        m = None
    if m:
        office = m.group(1)                         # the office id, or one of its aliases (the Dell's)
        for o in [office] + herd_offices(HERD).get(office, {}).get("aliases", []):
            url = door(o, "plane")
            if url:
                return f"{url}/api/v1/workspaces/{PLANE_WS}"
    return f"http://plane:80/api/v1/workspaces/{PLANE_WS}"


def pages(base, path):
    """Every result of a Plane list, following its cursor."""
    out, cursor = [], ""
    for _ in range(60):                                   # 6000 rows at most: a runaway cursor ends here
        sep = "&" if "?" in path else "?"
        got = get(f"{base}{path}{sep}per_page=100" + (f"&cursor={cursor}" if cursor else ""), timeout=30)
        if "_error" in got:
            raise RuntimeError(got["_error"])
        rows = got.get("results", got) if isinstance(got, dict) else got
        out += rows if isinstance(rows, list) else []
        if not (isinstance(got, dict) and got.get("next_page_results") and got.get("next_cursor")):
            return out
        cursor = got["next_cursor"]
    return out


def instant(iso):
    """An ISO time as epoch seconds with its microseconds: two changes in one second stay two."""
    try:
        return datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def epoch(iso):
    return int(instant(iso))


def plane_read(prev=None):
    """Progress per Plane module, the totals and the last day's opened/closed items.

    Counted HERE from each module's own issue list and each issue's state group: the module list's own
    `completed_issues`/`started_issues` read 1 and 1 for a module of 123 items (measured 2026-11-02).

    `prev` is the last reading's live state: an item whose state moved since then and that no live ask saw
    (it moved during this read, or between the last ask and it) is still a line — `lines` — and the
    watermark the next live ask starts from is taken BEFORE the pages, so a change made while they are
    read is newer than it and is read again, never skipped (the second reader, 2026-11-03)."""
    base = plane_base()
    proj = next((p for p in pages(base, "/projects/") if p.get("identifier") == PLANE_PROJECT), None)
    if not proj:                                    # a bare StopIteration would say nothing on the page
        raise RuntimeError(f"no Plane project {PLANE_PROJECT} at {base}")
    P = f"/projects/{proj['id']}"
    group = {s["id"]: s["group"] for s in pages(base, f"{P}/states/")}
    owner = {l["id"] for l in pages(base, f"{P}/labels/") if l.get("name") == OWNER_LABEL}
    head = get(f"{base}{P}/issues/?order_by=-updated_at&per_page=1", timeout=30)
    if "_error" in head:
        raise RuntimeError(head["_error"])
    newest = [r for r in (head.get("results", []) if isinstance(head, dict) else []) if isinstance(r, dict)]
    high = instant(newest[0].get("updated_at")) if newest else 0.0
    issues = pages(base, f"{P}/issues/")
    g = {i["id"]: group.get(i.get("state"), "") for i in issues}
    topics = []
    for m in pages(base, f"{P}/modules/"):
        # a row may name its issue under `issue` (apps/project-pln/plan.py reads it the same way)
        ids = [k for k in (str(i.get("issue") or i.get("id"))
                           for i in pages(base, f"{P}/modules/{m['id']}/module-issues/")) if k in g]
        done = sum(g[i] in ("completed", "cancelled") for i in ids)
        started = sum(g[i] == "started" for i in ids)
        if len(ids) >= 5 and done < len(ids):
            topics.append({"name": m.get("name") or "", "done": done, "started": started, "total": len(ids), "ids": ids})
    topics.sort(key=lambda t: (-t["started"], -t["total"]))
    topics = topics[:12]
    day = time.time() - 86400
    events = []
    for i in issues:
        ref = f"{PLANE_PROJECT}-{i.get('sequence_id')}"
        made, closed = epoch(i.get("created_at")), epoch(i.get("completed_at")) if i.get("completed_at") else 0
        if made > day:
            events.append({"ts": made, "kind": "open", "text": "נפתח: " + (i.get("name") or "")[:90], "ref": ref})
        if closed > day and g[i["id"]] == "completed":
            events.append({"ts": closed, "kind": "done", "text": "נסגר: " + (i.get("name") or "")[:90], "ref": ref})
    # a start, a cancel or a reopen since the last reading that no live ask saw: Plane keeps no time of it, so
    # only this comparison can make it a line (an open or a close is rebuilt above from Plane's own fields)
    lines = []
    for i in issues:
        was = ((prev or {}).get("known") or {}).get(i["id"])
        line = moved(was["g"], g[i["id"]], i) if was else None
        if line and line.get("live"):
            lines.append(line)
    # what the live ask (plane_live) compares against: each item's state group, and the watermark
    known = {i["id"]: {"g": g[i["id"]], "own": bool(owner & set(i.get("labels") or []))} for i in issues}
    live = {"base": base, "P": P, "group": group, "owner": owner, "known": known,
            "topic_ids": [t.pop("ids") for t in topics], "high": high}
    return {"topics": topics, "totals": recount(live, topics), "events": events, "lines": lines, "_live": live}


def moved(was, new, r):
    """The line for an item whose state group went from `was` (None: an item not seen before) to `new`, or None.
    A line Plane's own fields cannot rebuild later (a start, a cancel, a reopen) is marked `live`."""
    ref, name = f"{PLANE_PROJECT}-{r.get('sequence_id')}", (r.get("name") or "")[:90]
    at = epoch(r.get("updated_at"))
    if was is None:
        return {"ts": epoch(r.get("created_at")) or at, "kind": "open", "text": "נפתח: " + name, "ref": ref}
    if was == new:
        return None
    if new == "completed":
        return {"ts": epoch(r.get("completed_at")) or at, "kind": "done", "text": "נסגר: " + name, "ref": ref}
    if new == "cancelled":
        return {"ts": at, "kind": "cancel", "text": "בוטל: " + name, "ref": ref, "live": 1}
    if was in ("completed", "cancelled"):
        return {"ts": at, "kind": "open", "text": "נפתח מחדש: " + name, "ref": ref, "live": 1}
    if new == "started":
        return {"ts": at, "kind": "start", "text": "התחיל: " + name, "ref": ref, "live": 1}
    return None


def recount(live, topics):
    """The topics' bars and the tiles, from each item's state group as last known (in place for the topics)."""
    g = {i: k["g"] for i, k in live["known"].items()}
    for t, ids in zip(topics, live["topic_ids"]):
        t["done"] = sum(g.get(i) in ("completed", "cancelled") for i in ids)
        t["started"] = sum(g.get(i) == "started" for i in ids)
    return {"all": len(g), "completed": sum(v == "completed" for v in g.values()),
            "started": sum(v == "started" for v in g.values()),
            "owner": sum(k["own"] for k in live["known"].values() if k["g"] not in ("completed", "cancelled"))}


def plane_live(live):
    """ONE request: the items Plane changed last. Each item whose state group moved since the last reading is a
    line of today's log. Returns (lines, overflow): overflow when a full page came back and every row of it is
    new, so more may have changed than one page holds and the full read should come now, not in up to
    PLANE_EVERY seconds."""
    got = get(f"{live['base']}{live['P']}/issues/?order_by=-updated_at&per_page={LIVE_PAGE}", timeout=30)
    if "_error" in got:
        raise RuntimeError(got["_error"])
    rows = [r for r in (got.get("results", []) if isinstance(got, dict) else []) if isinstance(r, dict) and r.get("id")]
    fresh = [r for r in rows if instant(r.get("updated_at")) > live["high"]]
    lines, overflow = [], len(rows) >= LIVE_PAGE and len(fresh) == len(rows)
    for r in sorted(fresh, key=lambda r: instant(r.get("updated_at"))):
        new = live["group"].get(r.get("state"))
        if new is None:                             # a state made since the full read: the full read comes now,
            overflow = True                         # and its comparison with `known` makes this item's line
            continue
        line = moved((live["known"].get(r["id"]) or {}).get("g"), new, r)
        if line:
            lines.append(line)
        live["known"][r["id"]] = {"g": new, "own": bool(live["owner"] & set(r.get("labels") or []))}
    if fresh:
        live["high"] = max(instant(r.get("updated_at")) for r in fresh)
    return lines, overflow


def day_lines(full, live_lines):
    """Today's work-item lines: what the full read rebuilds from Plane's own fields (opened, closed), and what
    only the live ask saw (started, cancelled, reopened; and a close or an open the next full read has not
    rebuilt yet), each once; the last 24 hours, newest first."""
    # an open or a close the full read rebuilt is ITS line: the live ask's copy of it goes, even when a rename or
    # a later save changed the text or the time — but a close AFTER the one it rebuilt (reopened and closed
    # again since that read) is a new line and stays (a reopen is marked `live` and stays)
    rebuilt = {}
    for e in full:
        rebuilt[(e["ref"], e["kind"])] = max(rebuilt.get((e["ref"], e["kind"]), 0), e["ts"])
    live_lines = [e for e in live_lines if e.get("live") or e["ts"] > rebuilt.get((e["ref"], e["kind"]), -1)]
    since, seen, out = time.time() - 86400, set(), []
    for e in sorted(full + live_lines, key=lambda e: e["ts"], reverse=True):
        key = (e["ref"], e["kind"], e["ts"], e["text"])
        if e["ts"] > since and key not in seen:
            seen.add(key)
            out.append(e)
    return out[:DAY_LINES]


def saved_live_lines(path):
    """The lines only the live ask could see, from the last state file: a restart must not lose them."""
    try:
        with open(path, encoding="utf-8") as f:
            return [e for e in (json.load(f).get("feed") or [])
                    if isinstance(e, dict) and e.get("live") and isinstance(e.get("ts"), (int, float))
                    and isinstance(e.get("ref"), str) and isinstance(e.get("kind"), str) and isinstance(e.get("text"), str)
                    and e["ts"] > time.time() - 86400]
    except Exception:                               # a file nobody can read is no saved line, never a dead thread
        return []


PLANE = {"topics": [], "totals": None, "events": [], "live": [], "error": ""}


def plane_loop():
    """Plane in its own thread, never holding up the computers' dots: the full read (some 80 requests through
    the door) every PLANE_EVERY seconds, and the live ask (one request) every PLANE_LIVE_EVERY seconds between
    them. A failed pass keeps the last good reading and says why."""
    PLANE["live"] = saved_live_lines(OUT)
    last_full, early, failed = -float(PLANE_EVERY), False, ""
    while True:
        doing = "live"
        try:
            since = time.time() - last_full
            # a full read comes every PLANE_EVERY; sooner (but never within FULL_RETRY of the last, so a long plan
            # sync cannot chain them) when the live ask overflowed or no full read has succeeded yet
            if since >= PLANE_EVERY or ((early or PLANE.get("_live") is None) and since >= FULL_RETRY):
                doing, last_full, early = "full", time.time(), False   # a failed read waits its turn too
                got = plane_read(PLANE.get("_live"))
                PLANE["live"] = day_lines([], PLANE["live"] + got.pop("lines"))
                PLANE.update(got)
                failed = ""
            elif PLANE.get("_live") is not None:
                lines, overflow = plane_live(PLANE["_live"])
                if lines:
                    PLANE["live"] = day_lines([], PLANE["live"] + lines)
                PLANE["totals"] = recount(PLANE["_live"], PLANE["topics"])
                early = early or overflow           # more changed than one page holds: a full read comes soon
            PLANE["error"] = failed                 # a failed full read stays said until one succeeds
        except Exception as e:
            if doing == "full":
                failed = str(e)[:200]
            PLANE["error"] = str(e)[:200]
            print(f"dashboard-feed: plane ({doing}): {e!r}", flush=True)
        time.sleep(PLANE_LIVE_EVERY)


def collect():
    now = time.time()
    m = get(f"{EXTEND}/api/map")
    herd = herd_offices(HERD)
    alias = {a: oid for oid, o in herd.items() for a in o["aliases"]}
    home = (m.get("home") or {}).get("id") or os.environ.get("DGO_OFFICE_ID") or "local"
    rows, seen = [], set()

    st, why = local_state(COMPUTERS)
    home_key = alias.get(home, home)               # the Dell declares portable-ubuntu, herd.yaml says dell
    h = herd.get(home_key, {})
    rows.append({"id": home, "office": home, "group": "העדר שלנו", "name": h.get("label") or "המחשב הזה",
                 "role": h.get("role") or "", "state": "up" if st == "ok" else "half", "when": "כאן",
                 "facts": [["מצב", "הלשכה הזאת"], ["פקודות", "יש" if st == "ok" else (why or st)]],
                 "note": "תחנת הבקרה: מכאן רואים ומפעילים את כל המחשבים.",
                 "link": "/a/computers/c/local/res"})
    seen.add(home_key)

    for it in m.get("items") or []:
        oid = it.get("office") or ""
        key = alias.get(oid, oid)
        h = herd.get(key, {})
        ours = key in herd
        age = it.get("handshake_age_s")
        up = it.get("state") == "up"
        facts = [["קישור", f"{'מחובר' if up else 'מנותק'} ({it.get('transport') or '?'})"]]
        if isinstance(age, (int, float)):
            facts.append(["נשמע לאחרונה", f"לפני {int(age // 60)} דק׳" if age >= 60 else f"לפני {int(age)} שנ׳"])
        commit = (it.get("commit") or "")[:8]
        facts.append(["גרסה", commit or "לא ידועה (גרסה ישנה)"])
        row = {"id": oid, "office": oid, "group": "העדר שלנו" if ours else (it.get("herd") or "לקוחות"),
               "name": h.get("label") or it.get("label") or oid, "role": h.get("role") or it.get("herd") or "",
               "link": f"/a/computers/c/{oid}/res", "facts": facts}
        if up:
            url = door(oid)
            st, why = local_state(url) if url else ("unshared", "המחשבים שלו לא משותפים למחשב הזה")
            row["state"] = "up" if st == "ok" else "half"
            row["when"] = "עכשיו" if (age or 0) < 180 else f"לפני {int(age // 60)} דק׳"
            facts.append(["פקודות", "יש" if st == "ok" else (why or "אין")])
            row["note"] = ("מחובר, ואפשר להריץ בו פקודות." if st == "ok" else
                           "מחובר, אבל אי אפשר להריץ בו פקודות מכאן: " + (why or st) + ".")
        else:
            since = int(now - (age or 0))
            row.update({"state": "down", "since_ts": since, "when_ts": since,
                        "why": it.get("state_error") or "הקישור לא עונה",
                        "note": "הקישור לא עונה. אם המחשב עצמו כבוי או קפוא, צריך יד ליד המחשב."})
        rows.append(row)
        seen.add(key)

    for oid, h in herd.items():                     # declared, and missing from the map: not linked
        if oid in seen:
            continue
        rows.append({"id": oid, "office": oid, "group": "העדר שלנו", "name": h["label"], "role": h["role"],
                     "state": "none", "when": "", "facts": [["קישור", "לא מקושר למחשב הזה"]],
                     "note": "מוצהר בעדר, אבל לא מקושר למחשב הזה.", "link": "—"})

    feed = []
    hist = get(f"{EXTEND}/api/link/history")
    names = {r["office"]: r["name"] for r in rows}
    for e in sorted(hist.get("items") or [], key=lambda e: e.get("at") or 0, reverse=True):
        if e.get("kind") != "change":
            continue
        n = names.get(e.get("office"), e.get("office"))
        why = re.split(r"[:—(]|, ", e.get("why") or "", maxsplit=1)[0].strip()[:70]   # the first clause: a log line, not the essay
        feed.append({"ts": int(e.get("at") or now), "kind": "done" if e.get("ok") else "bad",
                     "text": f"{n} {'חזר לקישור' if e.get('ok') else 'נפל מהקישור'}" + (f": {why}" if why else ""),
                     "ref": ""})
        if len(feed) >= 12:
            break

    feed = sorted(feed + day_lines(PLANE["events"], PLANE["live"]), key=lambda f: f["ts"], reverse=True)[:DAY_LINES]
    errors = {k: v["_error"] for k, v in (("map", m), ("history", hist)) if "_error" in v}
    if PLANE["error"]:
        errors["plane"] = PLANE["error"]
    return {"at": int(now), "computers": rows, "feed": feed, "topics": PLANE["topics"],
            "totals": PLANE["totals"], "errors": errors}


# ── the console on the LAN: the switch behind the screen's card (DGO-1125) ──────────────────────────────
# The host's console door (packaging/macos/lan-door.py --policy) listens on the LAN while policy.json says
# on and writes status.json beside it; both live in the repo's data/lan, mounted here at LAN_DIR. This is
# the one writer of the policy's switch, and it names who switched it; the door itself rewrites only the
# ADDRESS, when the Mac was given another one behind the same router (lan-door.py `follow`, r030-002) —
# never the switch, and never onto another network. The card sits in this screen because its
# code is mounted, not built (the network screen's is baked into an image, and images cannot be published
# while GitHub's billing is stopped).
#
# WHO MAY SWITCH IT (the second reader, 2026-11-02): the API listens on a UNIX SOCKET in a volume only the
# page's caddy shares, not on the office network where any container could call it; a request must carry
# the signed-in identity the edge wrote (X-authentik-username); and one that came through a linked office's
# door (X-DGO-Office) may read but never switch. The address is never the client's to choose: it is the
# one the door found this Mac leaving the LAN from (status.json), so a VPN or bridge interface cannot be
# opened.
LAN_DIR = os.environ.get("DASHBOARD_LAN_DIR", "/lan")
LAN_SOCK = os.environ.get("DASHBOARD_LAN_SOCK", "/run/lan/api.sock")


def lan_read(name):
    try:
        with open(os.path.join(LAN_DIR, name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def lan_policy_from(body, who):
    """The policy a PUT asks for, or (None, why)."""
    if not isinstance(body, dict) or not isinstance(body.get("on"), bool):
        return None, "on must be true or false"
    if not body["on"]:
        old = lan_read("policy.json") or {}
        return {**{k: old[k] for k in ("address", "port") if k in old}, "on": False, "until": 0,
                "by": who, "at": int(time.time())}, ""
    address = str((lan_read("status.json") or {}).get("address") or "")
    if not address:
        return None, "the door has not said this Mac's LAN address yet (is the engine's console door running?)"
    try:
        port = int(body.get("port") or 8080)
        hours = float(body.get("hours") or 0)
    except (ValueError, TypeError):
        return None, "port or hours is not readable"
    if not 1024 <= port <= 65535 or port == 51443:
        return None, "the port must be 1024-65535 and not 51443"
    if not math.isfinite(hours) or hours < 0 or hours > 24 * 31:
        return None, "hours must be 0 (never) to 744"
    return {"on": True, "address": address, "port": port, "until": int(time.time() + hours * 3600) if hours else 0,
            "by": who, "at": int(time.time())}, ""


class LanApi(http.server.BaseHTTPRequestHandler):
    def _send(self, code, obj):
        raw = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.split("?")[0] != "/api/lan":
            return self._send(404, {"error": "not here"})
        # the console's NAME on the LAN (DGO-1126, apps/lan-console): .env's LAN_DOMAIN, or "" and the page
        # takes the same default as the compiler, the address as a name
        self._send(200, {"policy": lan_read("policy.json") or {"on": False}, "status": lan_read("status.json"),
                         "domain": os.environ.get("LAN_DOMAIN", "").strip()})

    def do_PUT(self):
        if self.path.split("?")[0] != "/api/lan":
            return self._send(404, {"error": "not here"})
        if self.headers.get("X-DGO-Office"):
            return self._send(403, {"error": "only this office switches its own console on the LAN"})
        who = self.headers.get("X-authentik-username") or ""
        if not who:
            return self._send(401, {"error": "not signed in"})
        try:
            n = max(0, min(int(self.headers.get("Content-Length") or 0), 4096))
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self._send(400, {"error": "not JSON"})
        policy, why = lan_policy_from(body, who)
        if policy is None:
            return self._send(400, {"error": why})
        os.makedirs(LAN_DIR, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=LAN_DIR, prefix=".policy-", suffix=".json")   # one per write: two at once never share it
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(policy, f)
        os.replace(tmp, os.path.join(LAN_DIR, "policy.json"))
        print(f"dashboard-feed: lan policy {'on ' + policy['address'] + ':' + str(policy['port']) if policy['on'] else 'off'} by {who}", flush=True)
        self._send(200, {"policy": policy, "status": lan_read("status.json")})

    def log_message(self, *a):
        pass


class UnixHTTPServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def get_request(self):                         # a unix peer has no address; the handler wants a pair
        conn, _ = super().get_request()
        return conn, ("unix", 0)


def lan_api():
    os.makedirs(os.path.dirname(LAN_SOCK), exist_ok=True)
    try:
        os.unlink(LAN_SOCK)
    except FileNotFoundError:
        pass
    UnixHTTPServer(LAN_SOCK, LanApi).serve_forever()


def write(state):
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(tmp, OUT)                           # the page never reads half a file


if __name__ == "__main__":
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    threading.Thread(target=plane_loop, daemon=True).start()
    threading.Thread(target=lan_api, daemon=True).start()
    while True:
        try:
            write(collect())
        except Exception as e:                      # keep the last good file; say why in the log
            print(f"dashboard-feed: {e!r}", flush=True)
        time.sleep(EVERY)
