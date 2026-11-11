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
import concurrent.futures
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
#: a Plane of this office's own: the project-pln container, on the office network by its service name — and no
#: door signs for it, so it is asked with the office's own key (the vault's, in memory, never written down)
LOCAL_PLANE = os.environ.get("DASHBOARD_PLANE_URL", "http://project-pln:80").rstrip("/")
VAULT = os.environ.get("CONNECTIONS_URL", "http://connections:8990").rstrip("/")
KEYS = {}                                          # a base URL → the X-API-Key every request under it carries
#: Plane counts every request that carries a key against API_KEY_RATE_LIMIT (60/minute, apps/project-pln): a full
#: read is ~107 requests, so unpaced it was refused at the 61st and never completed — and it spent the same key's
#: minute that `bbox project-pln` and the group's «משימה» use (the second reader, DGO-1329). Two seconds apart: a
#: full read in ~3.5 minutes every 15, and half the key's minute left to the others. A door's request (no key) is
#: not counted and not paced.
KEY_PACE = float(os.environ.get("DASHBOARD_PLANE_KEY_PACE", "2.0"))
#: …and the key's other users still spend its minute: a 429 is that minute gone, so the SAME request is asked again
#: once it has turned, instead of throwing a full read away at its 40th page and starting over (ten 429s in 40
#: minutes on the HP, 2026-11-05, while its agents worked Plane with the same key)
RATE_WAIT = float(os.environ.get("DASHBOARD_PLANE_RATE_WAIT", "30"))
RATE_TRIES = 3
_paced = {"at": 0.0}
_pace = threading.Lock()


def get(url, timeout=8):
    attempt = 0
    while True:
        try:
            key = next((k for base, k in list(KEYS.items()) if url.startswith(base)), "")
            if key:
                with _pace:
                    time.sleep(max(0.0, _paced["at"] + KEY_PACE - time.time()))
                    _paced["at"] = time.time()
            req = urllib.request.Request(url, headers={"X-API-Key": key} if key else {})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:    # it answered: its own words beside the code, not just "HTTP Error 502"
            body = e.read(300).decode("utf-8", "replace").strip() if e.fp else ""
            attempt += 1
            if e.code == 429 and key and attempt < RATE_TRIES:     # never while holding the pace: others go on
                time.sleep(rate_wait(e.headers))
                continue
            return {"_error": f"HTTP {e.code}: {body}"[:200]}
        except Exception as e:                 # an office that does not answer is a reading, not a crash
            return {"_error": str(e)[:200]}


def rate_wait(headers):
    """How long a 429 asks to be left alone: Plane's own Retry-After (seconds) when it says, else RATE_WAIT; at
    most a minute — the key's window."""
    try:
        said = (headers or {}).get("Retry-After")
        return min(60.0, max(1.0, float(said))) if said else RATE_WAIT
    except (TypeError, ValueError):
        return RATE_WAIT


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


LOCAL_COMPUTER = "computer_local-local"


def local_state(url):
    """The office's own machine as its Computers app sees it: (state, reason).

    A probe: without one the built-in computer carries no state at all (measured 2026-11-02 on vps1 and
    examplef, both of which take commands). The app caches a probe (COMPUTERS_PROBE_TTL, 20 s), so this
    costs one SSH round trip per office per pass at most. The linked offices are read at once (collect,
    STATE_DEADLINE), so the timeout fits inside that round.

    ONE machine, never the fleet (DGO-1353): `/api/computers?probe=1` probes every machine the office holds,
    one after another and each up to ssh's 8 s, so the MacBook away from home — its two LAN machines timing
    out — answered in 17–20 s, and its own row read «the computers app did not answer» (2026-11-05). The
    machine's own route (`/status`, in every Computers app on every branch since 2026-09-29) is one probe; its
    404 is the app's own «no such machine», which the fleet said by leaving the row out."""
    got = get(f"{url}/api/computers/{LOCAL_COMPUTER}/status", timeout=8)
    if str(got.get("_error", "")).startswith("HTTP 404"):
        return "unknown", ""
    if "_error" in got:
        return "unreachable", "אפליקציית המחשבים לא ענתה"
    return got.get("state") or ("ok" if got.get("ok") else "unknown"), got.get("reason") or ""


_warming = threading.Lock()


def warm_fleet(url):
    """The fleet's probe, beside the pass and never waited for (DGO-1353). The console's account bar colours every
    machine from the Computers app's probe cache, which this feed's fleet read kept warm on every pass; the row now
    reads its own machine only (`local_state`), so the fleet is still probed here — one at a time, with the time a
    slow fleet needs."""
    if not _warming.acquire(blocking=False):
        return

    def run():
        try:
            get(f"{url}/api/computers?probe=1", timeout=60)
        finally:
            _warming.release()
    threading.Thread(target=run, daemon=True, name="fleet-warm").start()


def door(office, alias="computers"):
    """http://<alias>.<office>:<port> — the port the SERVING office published for that app, from the
    compiler's own record (.generated/registry/remote.<office>.<alias>.json), as `bbox remote` reads it.
    Each linked office has its own port: a fixed one reaches whichever office owns it (measured: 9005 is
    the HP's, so vps1 and examplef read as the HP)."""
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
    Plane over the link too, and the first registry file is EXF's (measured: 401 there).

    On the office that runs Plane there is no door: its own Plane is http://project-pln:80, asked with the
    office's key from the vault (`plane_local_api_token-local`, the key `bbox project-pln` itself uses). This
    used to be http://plane:80 with no key — a name nothing answers to on the HP (measured 2026-11-05 from its
    office network: «Name or service not known») — so the one office whose feed the group's work-item lines
    come from could never read Plane (DGO-1329). The key is read again at every full read: a rotated key is
    in use within one PLANE_EVERY."""
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
    base = f"{LOCAL_PLANE}/api/v1/workspaces/{PLANE_WS}"
    sec = get(f"{VAULT}/api/instances/plane_local_api_token-local/secret")
    key = str(((sec.get("secret") if isinstance(sec, dict) else None) or {}).get("token") or "").strip()
    if key:
        KEYS[base] = key
    return base


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
    who = members(base)
    if who:
        WHO.clear()
        WHO.update(who)
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
            events.append({"ts": made, "kind": "open", "text": "נפתח: " + (i.get("name") or "")[:90], "ref": ref,
                           **({"by": by_of(i, True)} if by_of(i, True) else {})})
        if closed > day and g[i["id"]] == "completed":
            events.append({"ts": closed, "kind": "done", "text": "נסגר: " + (i.get("name") or "")[:90], "ref": ref,
                           **({"by": by_of(i, False)} if by_of(i, False) else {})})
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


WHO = {}          # a Plane user id → the name the group reads (members(), at every full read)


def members(base):
    """{user id: name} of the workspace's members — who opened or closed an item, said in its line (the owner,
    2026-11-03: «כל פעם שסוכן פותח / סוגר משימה זה שולח פה עדכון» — and which agent did it, DGO-1329). An agent that
    acts with its own Plane account (`bbox project-pln tasks … --as azaria`) is named; one that acts with the office's
    key is the office's account. {} when the list is not readable: the lines go on without a name."""
    try:
        rows = pages(base, "/members/")
    except Exception:                               # noqa: BLE001 — a list not read is lines without a name
        return {}
    out = {}
    for row in rows:
        u = row.get("member") if isinstance(row, dict) and isinstance(row.get("member"), dict) else row
        if not isinstance(u, dict) or not u.get("id"):
            continue
        name = (u.get("display_name") or " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x).strip()
                or str(u.get("email") or "").split("@")[0])
        if name:
            out[str(u["id"])] = name
    return out


def by_of(r, opened):
    """The name of who opened (`created_by`) or last moved (`updated_by`) an item, or ""."""
    return WHO.get(str(r.get("created_by" if opened else "updated_by") or ""), "")


def moved(was, new, r):
    """The line for an item whose state group went from `was` (None: an item not seen before) to `new`, or None,
    with who made the change when Plane says it (`by`)."""
    line = _moved(was, new, r)
    if line:
        by = by_of(r, was is None)
        if by:
            line["by"] = by
    return line


def _moved(was, new, r):
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


def saved_state(path):
    """The last state file as it was before this collector wrote one — read ONCE, before any thread starts, so the
    first pass's own fresh file (no Plane reading in it yet) is never read back as the saved one."""
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        return doc if isinstance(doc, dict) else {}
    except Exception:                               # a file nobody can read is nothing saved, never a dead thread
        return {}


def saved_live_lines(saved):
    """The lines only the live ask could see, from the last state file (a path, or the state read once): a restart
    must not lose them."""
    try:
        doc = saved if isinstance(saved, dict) else saved_state(saved)
        return [e for e in (doc.get("feed") or [])
                if isinstance(e, dict) and e.get("live") and isinstance(e.get("ts"), (int, float))
                and isinstance(e.get("ref"), str) and isinstance(e.get("kind"), str) and isinstance(e.get("text"), str)
                and e["ts"] > time.time() - 86400]
    except Exception:                               # a file nobody can read is no saved line, never a dead thread
        return []


def saved_plane(saved, max_age=3600):
    """The Plane reading of the last state file — its counts, its topics, the day's opens and closes, and the last
    read's failure — while the FULL READ that made it (`plane_at`) is under an hour old. A restart, every deploy, must
    not empty «מצב»'s tasks row for the minutes the paced full read takes (measured on the HP, 2026-11-05: «עוד לא
    נקרא מאז שהאוסף עלה» for ~4 minutes), nor count its day from nothing («נסגרו 0»); and counts no full read renewed
    for an hour are not shown as fresh — the file itself is rewritten every pass, so its own age says nothing (the
    second reader). The full read replaces all of it as soon as it is done."""
    try:
        doc = saved if isinstance(saved, dict) else saved_state(saved)
        at = float(doc.get("plane_at") or 0)
        if not isinstance(doc.get("totals"), dict) or time.time() - at > max_age:
            return {}
        events = [e for e in doc.get("feed") or [] if isinstance(e, dict) and not e.get("live")
                  and e.get("kind") in ("open", "done") and isinstance(e.get("ref"), str) and e["ref"]
                  and isinstance(e.get("ts"), (int, float)) and isinstance(e.get("text"), str)]
        return {"totals": doc["totals"], "topics": [t for t in doc.get("topics") or [] if isinstance(t, dict)],
                "events": events, "read_at": at, "error": str((doc.get("errors") or {}).get("plane") or "")[:200]}
    except Exception:                               # nothing saved that can be trusted: read Plane as at a first start
        return {}


SAVED = saved_state(OUT)        # the state file as found at start: read at import, before any thread or pass rewrites it
PLANE = {"topics": [], "totals": None, "events": [], "live": [], "error": "", "read_at": None}


def plane_loop():
    """Plane in its own thread, never holding up the computers' dots: the full read (some 80 requests through
    the door) every PLANE_EVERY seconds, and the live ask (one request) every PLANE_LIVE_EVERY seconds between
    them. A failed pass keeps the last good reading and says why."""
    PLANE["live"] = saved_live_lines(SAVED)
    PLANE.update(saved_plane(SAVED))
    last_full, early, failed = -float(PLANE_EVERY), False, ""
    while True:
        doing = "live"
        try:
            since = time.time() - last_full
            # a full read comes every PLANE_EVERY; sooner (but never within FULL_RETRY of the last, so a long plan
            # sync cannot chain them) when the live ask overflowed or no full read has succeeded yet
            if since >= PLANE_EVERY or ((early or PLANE.get("_live") is None) and since >= FULL_RETRY):
                doing, last_full, early = "full", time.time(), False   # a failed read waits its turn too
                try:
                    got = plane_read(PLANE.get("_live"))
                finally:                            # …counted from when it ENDED: a read slowed by the key's
                    last_full = time.time()         # minute never runs straight into the next one
                PLANE["live"] = day_lines([], PLANE["live"] + got.pop("lines"))
                PLANE.update(got, read_at=time.time())
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


def hears(url, oid):
    """Whether the office whose Computers app is at `url` reads `oid`'s security service through ITS link now —
    or, when that read fails for any reason but time (a security app registered and not running answers the far
    door's own 502, vps1's documented case), `oid`'s machine service. One 200 is enough."""
    # 8 s and 8 s: the two reads fit ASK_DEADLINE (18 s, 2 s for the pool's queue) together — a longer first read (11 s, c0f35c84) left a
    # fallback answering at ~17 s cut at the deadline, «down» where «away» belongs; a far 504 at 10 s and our own
    # 8 s both read as a timeout, so the longer wait bought nothing
    got = get(f"{url}/api/hosts/{oid}/security/api/host/overview?brief=1", timeout=8)
    if "_error" in got and not timed_out(got["_error"]):
        got = get(f"{url}/api/hosts/{oid}/machine/api/overview?brief=1", timeout=8)
    return "_error" not in got


def timed_out(err):
    """A read that ran out of time — here, or at the far office's Computers app, which says its own upstream's
    timeout as HTTP 504 (computers' Herd._fetch) — and is not asked again within the pass."""
    return "timed out" in err or err.startswith("HTTP 504")


# A round's whole budget: urllib's timeout is per socket operation, not per request, so a slow far end could
# hold a read well past its own timeout — what is not back by then is read as not answered. A pass is the map
# and two rounds — the history with every office's own machine (STATE_DEADLINE), then the second eyes
# (ASK_DEADLINE): 8 + 10 + 18 = 36 s at worst, against EVERY's 20 s cadence — a slow pass is followed by the
# next one EVERY s later, never overlapped. The map's own read is the one outside that bound: its 8 s timeout
# is per socket operation like every urllib read, so a trickling extend could hold it longer.
STATE_DEADLINE = 10
# The two reads of hears() back to back (8 + 8) and a margin for the pool's queue: at 16 a security read failing
# late plus the machine's read was cut at the deadline and the row read «down» (7e6d6eb4's second read).
ASK_DEADLINE = 18

# One pool for every round of every pass, so the threads a trickling far end holds past a deadline cannot pile up
# from pass to pass: while they hold workers, a new round's calls wait for one and are read as not answered.
POOL = concurrent.futures.ThreadPoolExecutor(max_workers=32, thread_name_prefix="feed-ask")


LATE = {}   # what each kind of round last said of its stragglers: said again only when it changes


def at_once(fn, items, default, deadline, what="reads"):
    """[fn(item) for item in items], every call at once, each one not back within `deadline` — or that raised, or
    that never started — read as `default`."""
    futures = [POOL.submit(fn, it) for it in items]
    if futures:
        concurrent.futures.wait(futures, timeout=deadline)
    out, late, queued = [], 0, 0
    for f in futures:
        if not f.done():
            late += 1
            queued += f.cancel()                          # a call still queued never runs; one running ends on its own
            out.append(default)
        elif f.exception() is not None:
            out.append(default)
        else:
            out.append(f.result())
    # said, never silent — a pool starved by stragglers reads every office as not answering — but once per change,
    # not every pass: a hung office is one line when it hangs and one when it is back
    said = (f"{late} of {len(futures)} {what} not back in {deadline} s"
            f"{f', {queued} of them never started (the pool was full)' if queued else ''}") if late else ""
    if said != LATE.get(what, ""):
        LATE[what] = said
        print(f"dashboard-feed: {said or what + ': all back in time again'}", flush=True)
    return out


def heard_by_all(down, rows, reach):
    """{office: the name of an office this one reaches that reaches it now} for every office in `down` — a second
    pair of eyes for an office whose link from HERE does not answer. A dead link from this office is not the
    office being off the network: on 2026-11-03 at 21:19 the owner opened the MacBook's control centre through
    vps1's address and read «vps1 לא ברשת» — vps1 had dropped its side of the MacBook pair (DGO-1278) and was
    serving the page while the HP heard it 14 s before (DGO-1321). Only offices whose own Computers app answered
    this pass are asked (`reach`), and every ask runs at once — in one wave up to the pool's 32 — so a round costs
    one ask's time (8 s, 16 with the fallback, ASK_DEADLINE = 18 at most), never the sum: with two offices down and two
    up the sum was over a minute, past the 20 s refresh."""
    eyes = [r for r in rows if r.get("state") in ("up", "half") and not r.get("home") and reach.get(r["office"])]
    asks = [(oid, r) for oid in down for r in eyes if r["office"] != oid]
    answers = at_once(lambda a: hears(reach[a[1]["office"]], a[0]), asks, False, ASK_DEADLINE, "second-eyes asks")
    by = {}
    for (oid, r), ok in zip(asks, answers):                 # the first in the rows' order, whatever finished first
        if ok and oid not in by:
            by[oid] = r["name"]
    return by


def collect():
    now = time.time()
    m = get(f"{EXTEND}/api/map")
    # one round for everything that needs only the map, read at once: the link history (its default is 50 rows,
    # heartbeats among them — an outage of some hours would have its fall out of the window), this office's own
    # machine, and every linked office's own machine — so a pass is the map, this round and the second eyes
    ups = [it.get("office") or "" for it in m.get("items") or [] if it.get("state") == "up"]
    doors = {oid: door(oid) for oid in ups}
    unshared = ("unshared", "המחשבים שלו לא משותפים למחשב הזה")
    reads = [("history", None), ("home", COMPUTERS)] + [("office", oid) for oid in ups]
    warm_fleet(COMPUTERS)
    got = at_once(lambda r: (get(f"{EXTEND}/api/link/history?limit=2000") if r[0] == "history"
                             else local_state(r[1]) if r[0] == "home"
                             else local_state(doors[r[1]]) if doors[r[1]] else unshared),
                  reads, None, STATE_DEADLINE, "state reads")
    # not back in time is None; an empty history ({}) is an answer, kept as one
    hist = got[0] if got[0] is not None else {"_error": "the link history did not answer in time"}
    if isinstance(hist, list):          # a bare list is the items themselves — never an AttributeError in the pass
        hist = {"items": hist}
    late = ("unreachable", "אפליקציית המחשבים לא ענתה בזמן")
    home_state = got[1] if got[1] is not None else late
    states = {oid: s if s is not None else late for oid, s in zip(ups, got[2:])}
    # when each office last fell off this office's link, by the link's own history — a row that is down
    # says SINCE WHEN from what was recorded, never "now" (21:19 on the owner's screen was the minute he looked).
    # The FIRST fall after its last recovery: extend writes a change row on every (ok, hop) change, so a fall at
    # 100 and a hop change at 160, still down, began at 100; and `ok: None` is "not measured" (a restart), no fall
    fell = {}
    for e in sorted(hist.get("items") or [], key=lambda e: e.get("at") or 0):
        o, ok = e.get("office"), e.get("ok")
        if e.get("kind") != "change" or not o or ok is None:
            continue
        if ok:
            fell.pop(o, None)                        # back: the next fall starts a new outage
        elif o not in fell:
            fell[o] = int(e.get("at") or 0)
    reach = {}                                       # office → its Computers app's door, where it answered this pass
    herd = herd_offices(HERD)
    alias = {a: oid for oid, o in herd.items() for a in o["aliases"]}
    home = (m.get("home") or {}).get("id") or os.environ.get("DGO_OFFICE_ID") or "local"
    rows, seen = [], set()

    st, why = home_state
    home_key = alias.get(home, home)               # the Dell declares portable-ubuntu, herd.yaml says dell
    h = herd.get(home_key, {})
    rows.append({"id": home, "office": home, "group": "העדר שלנו", "name": h.get("label") or "המחשב הזה",
                 "role": h.get("role") or "", "state": "up" if st == "ok" else "half", "when": "כאן", "home": True,
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
            url = doors.get(oid, "")
            st, why = states.get(oid) or ("unreachable", "אפליקציית המחשבים לא ענתה")
            if st not in ("unreachable", "unshared"):
                reach[oid] = url
            row["state"] = "up" if st == "ok" else "half"
            row["when"] = "עכשיו" if (age or 0) < 180 else f"לפני {int(age // 60)} דק׳"
            facts.append(["פקודות", "יש" if st == "ok" else (why or "אין")])
            row["note"] = ("מחובר, ואפשר להריץ בו פקודות." if st == "ok" else
                           "מחובר, אבל אי אפשר להריץ בו פקודות מכאן: " + (why or st) + ".")
        else:
            # since when: the link's own record of the fall, else the last handshake; with neither, unknown
            since = fell.get(oid) or (int(now - age) if isinstance(age, (int, float)) else 0)
            row.update({"state": "down", "why": it.get("state_error") or "הקישור לא עונה",
                        "note": "הקישור לא עונה. אם המחשב עצמו כבוי או קפוא, צריך יד ליד המחשב."})
            if since:
                row.update({"since_ts": since, "when_ts": since})
            else:
                row["when"] = "לא ידוע מתי"
        rows.append(row)
        seen.add(key)

    # an office this one cannot reach, that another office reaches now, is on the network: only the link
    # from here is broken — said so, with the measured reason, and not counted as an office that is down
    here = rows[0]["name"]
    heard = heard_by_all([r["office"] for r in rows if r.get("state") == "down"], rows, reach)
    for row in rows:
        if row.get("state") != "down":
            continue
        by = heard.get(row["office"])
        if by:
            row.pop("when_ts", None)                 # heard NOW, through another office
            row.update({"state": "away", "heard_by": by, "when": "עכשיו", "reason": row["why"],
                        "why": f"הקישור הישיר מ-{here} לא עונה — {row['why']}; {by} מגיע אליו עכשיו",
                        "note": f"המחשב פועל ({by} מגיע אליו), אבל הקישור בינו לבין {here} לא עונה: "
                                "צריך לחבר מחדש את הזוג הזה, לא יד ליד המחשב."})
            row["facts"].append(["נשמע דרך", by])

    for oid, h in herd.items():                     # declared, and missing from the map: not linked
        if oid in seen:
            continue
        rows.append({"id": oid, "office": oid, "group": "העדר שלנו", "name": h["label"], "role": h["role"],
                     "state": "none", "when": "", "facts": [["קישור", "לא מקושר למחשב הזה"]],
                     "note": "מוצהר בעדר, אבל לא מקושר למחשב הזה.", "link": "—"})

    feed = []
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
            "totals": PLANE["totals"], "plane_at": PLANE.get("read_at"), "errors": errors}


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
        if self.path.split("?")[0] == "/api/snapshot":      # «מצב» / «קדימה»: read-only (snapshot.py, DGO-1339)
            return self._send(200, snapshot_now())
        if self.path.split("?")[0] != "/api/lan":
            return self._send(404, {"error": "not here"})
        # the console's NAME on the LAN (DGO-1126, apps/lan-console): .env's LAN_DOMAIN, or "" and the page
        # takes the same default as the compiler, the address as a name. `remote`: asked through a linked office's
        # door, where PUT is refused — the page shows the switch as read-only instead of a switch that fails (DGO-1321)
        self._send(200, {"policy": lan_read("policy.json") or {"on": False}, "status": lan_read("status.json"),
                         "domain": os.environ.get("LAN_DOMAIN", "").strip(),
                         "remote": bool(self.headers.get("X-DGO-Office"))})

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


def snapshot_now():
    """The office as one table for «מצב» and «קדימה» — this collector's state and its doors, every part read at once
    on the snapshot's own pool (snapshot.py beside this file, imported when first asked, so a pass never depends on
    it). A table that cannot be built is one line saying why, never the caddy's 502."""
    try:
        import snapshot
        herd = herd_offices(HERD)
        labels = {oid: o.get("label") or oid for oid, o in herd.items()}
        names = {a: oid for oid, o in herd.items() for a in [oid, *o.get("aliases", [])]}
        doc = snapshot.cached(lambda: snapshot.build(OUT, get, door, HERD, REGISTRY, labels, names=names))
        off = snapshot.tz_offset(doc.get("at") or time.time())
        return dict(doc, lines=snapshot.lines(doc, labels, off), tz_offset=off)
    except Exception as e:                          # noqa: BLE001 — said in the table
        return {"at": int(time.time()), "parts": {}, "silent": {"snapshot": str(e)[:160]},
                "lines": [f"🖥 מרכז הבקרה לא בנה את התמונה: {str(e)[:120] or 'סיבה לא נמסרה'}"]}


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


POWER = os.environ.get("DASHBOARD_POWER", "/power/status.json")
POWER_OUT = os.path.join(os.path.dirname(OUT), "power.json")


def power_brief(path=POWER):
    """This laptop's word on sleep, as its power agent decided it (packaging/macos/power-agent.py status.json): whether
    the owner's policy lets it sleep when locked or closed (`wanted`, after the guards — never `effective`, which is
    what macOS happens to do: with SleepDisabled cleared it says «sleep» while the policy says run, and every outage
    would pass as a sleep), and the guards (battery floor, heat) that released it — or None where there is no such
    agent. A laptop tells no one once it sleeps, so its last word waits in its control centre (data/power.json,
    beside the state): the office that posts to the group reads it over the link, and a drop that follows a sleep is
    said as a sleep, not an outage (DGO-1357, group.asleep)."""
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or not isinstance(d.get("updated_at"), (int, float)):
        return None
    want, power = d.get("wanted") or {}, d.get("power") or {}
    guards = (d.get("effective") or {}).get("guards")
    return {"at": d["updated_at"], "lock": want.get("lock"), "lid": want.get("lid"),
            "guards": [str(g) for g in guards] if isinstance(guards, list) else [],
            "source": power.get("source"), "percent": power.get("percent")}


def group_live():
    """The owner's group, live on the page (groupfeed.py beside this file, DGO-1329): its own thread and its own file,
    data/group-live.json, so the computers' pass never waits for Telegram."""
    import groupfeed
    groupfeed.loop(get, door, HERD)


def write(state, out=OUT):
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(tmp, out)                           # the page never reads half a file


if __name__ == "__main__":
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    threading.Thread(target=plane_loop, daemon=True).start()
    threading.Thread(target=lan_api, daemon=True).start()
    threading.Thread(target=group_live, daemon=True).start()
    while True:
        try:                                        # first and apart: a slow or failed pass never ages the word on sleep
            word = power_brief()
            if word:
                write(word, POWER_OUT)
        except Exception as e:
            print(f"dashboard-feed: power: {e!r}", flush=True)
        try:
            write(collect())
        except Exception as e:                      # keep the last good file; say why in the log
            print(f"dashboard-feed: {e!r}", flush=True)
        time.sleep(EVERY)
