#!/usr/bin/env python3
"""kadima.py — «קדימה» from a meeting to its end, measured (DGO-1847).

The owner says «קדימה <word>» after a meeting. Two things follow, and this tool measures both:

1. The WORD is a meeting first: the newest room that is the word, starts with it, or holds it, and only then a
   meeting whose title holds it (`resolve`). «קדימה exx» is exx101, recorded minutes before, not a lane's name.
2. When the meeting decided to build a product, «קדימה» goes on until the product's END STATE stands. The product
   declares that end state in `apps/<app>/product.json`, and `check` lists what is still missing:
   - the meeting, its own Plane project, its sources, its research and its requirements, each point traced;
   - the reference app it is designed from, the apps it reuses, its identity, roles, view-as and beauty gate;
   - its mailbox declared in apps/mail/app.json;
   - with --live: its domains on the office, the apex's 301 to www, the app answering (a sign-in redirect elsewhere
     is a finding), its mail (MX on the office, SPF, DMARC, a published DKIM key), and its site with the house line,
     links back, the office's logo in a tag and a link to the app.
   Points only a person can give (status `owner`) are listed apart with their item, never as findings.
   It ends with the «כניסה» block: how a person gets in. The owner's report opens with it.

Every item here is a direction the owner had to give by hand on 2026-11-11/12 («קדימה exx», issues/ of DGO-1847).
Stdlib only: it runs on the desk, an office's shell and a fresh clone alike.

    kadima.py resolve WORD… [--rows FILE|-]     rows: the output of `cli.py meetings N` and/or `cli.py recordings N`
    kadima.py check [APP|DIR…] [--live] [--json]   default: every apps/*/product.json
    kadima.py product-for ROOM                  the app whose product.json names that meeting
    kadima.py --self-test
"""
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
# Words that say «meeting» around the name: «קדימה פגישת exx101», «kadima meeting exx».
STOP = {"פגישת", "פגישה", "הפגישה", "פגישות", "meeting", "meet", "the", "את", "של", "קדימה", "kadima"}
STATUSES = {
    "done": "where",      # met — where in the code or the office
    "later": "why",       # the meeting itself put it later, or a later stage of the spec
    "owner": "item",      # only a person can give it — its item, labelled בעלים
    "partial": "gap",     # some of it — a finding until done
    "missing": "gap",     # asked for, not there — a finding
}
OPEN_STATUSES = {"partial", "missing"}


def _d(v):
    """A part of product.json that must be an object: anything else reads as empty (and is reported as missing)."""
    return v if isinstance(v, dict) else {}


# ── 1. the word → the meeting ─────────────────────────────────────────────────────────────────────────────────

def parse_rows(text):
    """Rows of `cli.py meetings` («YYYY-MM-DD HH:MM  room  title  page») and `cli.py recordings` («YYYY-MM-DD HH:MM
    room  [state]  people  session/file»): fields are two or more spaces apart; a room or a title is one-spaced
    (cli.flat), so the stamp's one space never splits. A row with no room (flat('') is empty) is skipped."""
    rows = []
    for line in text.splitlines():
        line = line.rstrip()
        if not line or line.startswith(("no meetings", "no recordings")):
            continue
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) < 2 or re.fullmatch(r"\[[^\]]+\]", parts[1]) or parts[1].startswith(("http://", "https://")):
            continue
        row = {"started": parts[0], "room": parts[1], "title": "", "page": "", "state": "", "kind": "meeting"}
        for p in parts[2:]:
            if p.startswith(("http://", "https://")):
                row["page"] = p
            elif re.fullmatch(r"\[[^\]]+\]", p):
                row["state"], row["kind"] = p.strip("[]"), "recording"
            elif row["kind"] == "recording":
                continue                        # people, session/file
            elif not row["title"]:
                row["title"] = p
        rows.append(row)
    return rows


def _tier(word, row):
    w, room, title = word.casefold(), row["room"].casefold(), row["title"].casefold()
    if room == w:
        return 0
    if room.startswith(w):
        return 1
    if w in room:
        return 2
    if w and w in title:
        return 3
    return None


def resolve(words, rows):
    """The meeting the words name: best tier first, then the newest. Returns (best, others). Rows of one room are
    merged case-blind — a page's room is lower-cased by server.flows(), a recording keeps the room as typed."""
    tokens = [t for w in words for t in re.split(r"\s+", w.strip()) if t and t.casefold() not in STOP]
    merged = {}
    for r in rows:
        key = r["room"].casefold()
        if key not in merged:
            merged[key] = dict(r)
            continue
        m = merged[key]
        if r.get("page") and not m.get("page"):
            m["room"] = r["room"]                # the page's spelling is the one its address uses
        for k in ("title", "page", "state"):
            if r.get(k) and not m.get(k):
                m[k] = r[k]
        if r["started"] > m["started"]:
            m["started"] = r["started"]
    hits = []
    for r in merged.values():
        tiers = [t for t in (_tier(tok, r) for tok in tokens) if t is not None]
        if tiers:
            hits.append((min(tiers), r))
    hits.sort(key=lambda h: h[1]["started"], reverse=True)   # newest first ("-" sorts last) …
    hits.sort(key=lambda h: h[0])                             # … within the best tier (a stable sort)
    if not hits:
        return None, []
    return hits[0][1], [h[1] for h in hits[1:6]]


# ── 2. the product's end state ────────────────────────────────────────────────────────────────────────────────

def _path(p):
    return p if os.path.isabs(p) else os.path.join(REPO, p)


def _local_only(p):
    """Where a source may live outside the repo, so its existence is not checked here: ci-artifacts/ (gitignored, on
    the desk that made it), an office drive (`hp:`, `drive:`), an absolute path or an address."""
    return p.startswith(("ci-artifacts/", "drive:", "hp:", "/")) or "://" in p


def load_product(arg):
    for cand in (arg, os.path.join(arg, "product.json"), os.path.join(REPO, "apps", arg, "product.json")):
        if cand and os.path.isfile(_path(cand)):
            with open(_path(cand), encoding="utf-8") as f:
                return json.load(f), os.path.relpath(_path(cand), REPO)
    raise SystemExit(f"kadima: no product.json for {arg!r}")


def all_products():
    apps = os.path.join(REPO, "apps")
    return sorted(os.path.join("apps", d, "product.json") for d in os.listdir(apps)
                  if os.path.isfile(os.path.join(apps, d, "product.json")))


def check_requirements(path):
    """(findings, counts, owner) — every point needs a known status and its evidence; partial and missing are
    findings; `owner` points are returned apart, with their item."""
    out, counts, owner = [], {}, []
    try:
        with open(_path(path), encoding="utf-8") as f:
            doc = json.load(f)
    except FileNotFoundError:
        return [f"requirements: {path} is not there"], counts, owner
    except (OSError, ValueError):
        return [f"requirements: {path} is not readable JSON"], counts, owner
    items = _d(doc).get("items") or []
    if not isinstance(items, list) or not items:
        return [f"requirements: {path} lists no point of the meeting"], counts, owner
    seen = set()
    for it in items:
        if not isinstance(it, dict):
            out.append(f"requirements: an entry that is not an object ({str(it)[:40]})")
            continue
        rid, st = str(it.get("id") or "?"), it.get("status")
        counts[str(st)] = counts.get(str(st), 0) + 1
        if rid in seen:
            out.append(f"requirements {rid}: the id is used twice")
        seen.add(rid)
        if st not in STATUSES:
            out.append(f"requirements {rid}: status {st!r} is none of {', '.join(STATUSES)}")
            continue
        need = STATUSES[st]
        if not str(it.get(need) or "").strip():
            out.append(f"requirements {rid}: {st} without `{need}`")
        if not str(it.get("quote") or it.get("ask") or "").strip():
            out.append(f"requirements {rid}: no quote and no ask — what was said is the point")
        what = str(it.get("ask") or it.get("quote") or "")[:90]
        if st in OPEN_STATUSES:
            out.append(f"requirements {rid} [{st}]: {what} — {it.get('gap') or ''}"[:220])
        elif st == "owner":
            owner.append(f"{rid}: {what} — {it.get('item') or '?'}")
    return out, counts, owner


def _mailbox_declared(addr):
    """The mailbox is a profile of apps/mail/app.json: an object with id == the local part and domain == the domain."""
    local, _, dom = addr.partition("@")
    try:
        with open(os.path.join(REPO, "apps", "mail", "app.json"), encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return False
    stack = [doc]
    while stack:
        v = stack.pop()
        if isinstance(v, dict):
            if v.get("id") == local and v.get("domain") == dom:
                return True
            stack.extend(v.values())
        elif isinstance(v, list):
            stack.extend(v)
    return False


def check_static(p, here):
    f = []

    def need(cond, line):
        if not cond:
            f.append(line)

    p = _d(p)
    m = _d(p.get("meeting"))
    need(m.get("room"), "meeting.room: which meeting decided this product")
    if "rooms" in m:
        rs = m.get("rooms")
        need(isinstance(rs, list) and all(_room_name(r) for r in rs),
             "meeting.rooms: a list of the product's later meetings, each a room's name (a string is one meeting: [\"…\"])")
    pl = _d(p.get("plane"))
    need(pl.get("project"), "plane.project: the product's own Plane project (its key)")
    if pl.get("plan"):
        if os.path.isfile(_path(pl["plan"])):
            with open(_path(pl["plan"]), encoding="utf-8") as fh:
                need(re.search(r"\b" + re.escape(pl.get("project") or "\0") + r"\b", fh.read()),
                     f"plane.plan {pl['plan']} does not name the project {pl.get('project')}")
        else:
            f.append(f"plane.plan {pl['plan']} is not in the repo")
    else:
        f.append("plane.plan: the plan file that files the product's items")
    src = p.get("sources")
    need(isinstance(src, list) and src, "sources: what the meeting showed or its people sent (the spec on screen, a drive folder)")
    for s in src if isinstance(src, list) else []:
        s = _d(s) if not isinstance(s, str) else {"what": s, "where": s}
        w = s.get("where") or ""
        need(w, f"sources: «{s.get('what', '?')}» has no `where`")
        if w and not _local_only(w):
            need(os.path.exists(_path(w)), f"sources: {w} is not in the repo")
    r = p.get("research") or ""
    rp = _path(r) if isinstance(r, str) and r else ""
    need(rp and os.path.isdir(rp) and any(n.endswith(".md") for n in os.listdir(rp)),
         "research: a folder of research notes, written BEFORE the design")
    if p.get("requirements"):
        # one file, or one per meeting: exx101's points and the owner's follow-ups in one, exx102's 300-odd in its own
        files = p["requirements"] if isinstance(p["requirements"], list) else [p["requirements"]]
        counts, owner = {}, []
        for rq in files:
            rf, c, o = check_requirements(rq) if isinstance(rq, str) and rq else (
                [f"requirements: {rq!r} is not a file's path"], {}, [])
            f.extend(rf)
            owner.extend(o)
            for k, v in c.items():
                counts[k] = counts.get(k, 0) + v
        here["requirements"], here["owner"] = counts, owner
    else:
        f.append("requirements: every point of the meeting traced to where it is met")
    ref = p.get("reference_app") or ""
    need(isinstance(ref, str) and ref and os.path.isdir(os.path.join(REPO, "apps", ref)),
         f"reference_app {ref!r}: the herd's app the design follows, mapped live")
    reuse = p.get("reuse") if isinstance(p.get("reuse"), list) else []
    for a in reuse:
        need(isinstance(a, str) and os.path.isdir(os.path.join(REPO, "apps", a)), f"reuse: {a} is not an app of this repo")
    need(reuse, "reuse: the herd apps leaned on instead of rebuilt (documents, signing, mail, sites…)")
    ident = p.get("identity")
    need(ident in ("own", "office"), "identity: own (outside people) or office")
    if ident == "own":
        need(p.get("main_account"), "main_account: the main admin's address (never a password)")
    roles = p.get("roles") if isinstance(p.get("roles"), list) else []
    if len(roles) > 1:
        va = _d(p.get("view_as"))
        ok = bool(va.get("file") and va.get("route") and os.path.isfile(_path(va["file"])))
        if ok:
            with open(_path(va["file"]), encoding="utf-8") as fh:
                ok = va["route"] in fh.read()
        need(ok, f"view_as: {len(roles)} roles and no view-as route found — declare {{file, route}} "
                 f"({va.get('route')} in {va.get('file')})")
    b = _d(p.get("beauty")).get("gate") or ""
    need(b and os.path.isfile(_path(b)), f"beauty.gate {b or '—'}: the product's screen gate (every screen × width × role), in the repo")
    d = _d(p.get("domains"))
    for k in ("office_ip", "app", "site", "apex"):
        need(d.get(k), f"domains.{k}")
    mail = _d(p.get("mail"))
    box = mail.get("mailbox") or ""
    need(box, "mail.mailbox: the product's own mailbox (resets, invitations)")
    if box:
        need(_mailbox_declared(box), f"mail.mailbox {box}: no profile of apps/mail/app.json is that address")
    need(mail.get("dkim_selector"), "mail.dkim_selector: the selector the office's mail signs this domain with")
    s = _d(p.get("site"))
    for k in ("app", "id", "house_line", "logo"):
        need(s.get(k), f"site.{k}")
    need(isinstance(s.get("backlinks"), list) and s.get("backlinks"),
         "site.backlinks: links back to Bina Solutions and the Digital Office")
    need(_d(p.get("way_in")).get("password"), "way_in.password: how the main account sets its password")
    return f


# live probes — injectable for the tests

class Unreadable(Exception):
    """A lookup that got no answer (DNS over HTTPS down, rate-limited, offline): never reported as a wrong record."""


def _doh(name, rtype, get=None):
    url = "https://cloudflare-dns.com/dns-query?" + urllib.parse.urlencode({"name": name, "type": rtype})
    st, _, body = (get or _get)(url, {"accept": "application/dns-json"})
    if st != 200:
        raise Unreadable(f"{name} {rtype}")
    try:
        data = json.loads(body or "")
    except ValueError:
        raise Unreadable(f"{name} {rtype}") from None
    want = {"A": 1, "CNAME": 5, "MX": 15, "TXT": 16}[rtype]
    return [str(a.get("data", "")) for a in data.get("Answer") or [] if a.get("type") == want]


class _NoFollow(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _get(url, headers=None):
    """(status, location, body) — no redirect followed; 10 s."""
    req = urllib.request.Request(url, headers={"user-agent": "dgo-kadima-check", **(headers or {})})
    opener = urllib.request.build_opener(_NoFollow)
    try:
        with opener.open(req, timeout=10) as r:
            return r.status, r.headers.get("location") or "", r.read(600_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("location") or "", ""
    except (urllib.error.URLError, OSError) as e:
        return 0, "", str(e)


def _links_to(html, host):
    return re.search(r"""href\s*=\s*["']https?://(?:www\.)?""" + re.escape(host.removeprefix("www.")) + r"""[/"'?#:]""",
                     html, re.I) is not None


def check_live(p, get=None):
    get = get or _get
    f = []
    p = _d(p)
    d, mail, s = _d(p.get("domains")), _d(p.get("mail")), _d(p.get("site"))
    ip = d.get("office_ip")
    for k in ("app", "site", "apex"):
        host = d.get(k)
        if not host:
            continue
        try:
            a = _doh(host, "A", get)
        except Unreadable:
            f.append(f"dns: {host} could not be read (DNS over HTTPS did not answer) — not checked")
            continue
        if ip not in a:
            f.append(f"dns: {host} → {', '.join(a) or 'nothing'}, not the office ({ip}) — write it through {d.get('registrar') or 'the registrar app'}")
    if d.get("apex") and d.get("site"):
        st, loc, _ = get(f"https://{d['apex']}/")
        if st not in (301, 308) or urllib.parse.urlsplit(loc).hostname != d["site"]:
            f.append(f"https://{d['apex']}/ answers {st} {loc or ''} — the apex 301s to {d['site']}")
    if d.get("app"):
        st, loc, _ = get(f"https://{d['app']}/")
        to = urllib.parse.urlsplit(loc).hostname if loc else None
        if not (st == 200 or (300 <= st < 400 and to in (None, d["app"]))):
            f.append(f"https://{d['app']}/ answers {st or 'nothing'} {loc or ''} — the app answers itself"
                     + (" (a sign-in elsewhere is the office's door, not the product's)" if to else ""))
    if d.get("site"):
        st, _, html = get(f"https://{d['site']}/")
        if st != 200:
            f.append(f"https://{d['site']}/ answers {st or 'nothing'}")
        else:
            if s.get("house_line") and s["house_line"] not in html:
                f.append(f"site: «{s['house_line']}» is not on {d['site']}")
            for link in s.get("backlinks") or []:
                host = urllib.parse.urlsplit(link if "://" in link else "https://" + link).hostname or link
                if not _links_to(html, host):
                    f.append(f"site: no link back to {host}")
            if s.get("logo") and not re.search(r"<[^>]*" + re.escape(s["logo"]) + r"[^>]*>", html):
                f.append(f"site: the office's logo ({s['logo']}) is in no tag of the page")
            if d.get("app") and not _links_to(html, d["app"]):
                f.append(f"site: no link to the app ({d['app']})")
    apex = d.get("apex")
    if apex and mail.get("mailbox"):
        try:
            mx = [m.split()[-1].rstrip(".") for m in _doh(apex, "MX", get) if m.split()]
            mx = [h for h in mx if h]                                  # «0 .» is a null MX: no mail at all
            if not mx:
                f.append(f"mail: {apex} has no MX")
            elif ip and not any(ip in _doh(h, "A", get) for h in mx):
                f.append(f"mail: {apex}'s MX ({', '.join(mx)}) does not reach the office ({ip})")
            if not any("v=spf1" in t for t in _doh(apex, "TXT", get)):
                f.append(f"mail: {apex} has no SPF")
            if not any("v=DMARC1" in t for t in _doh("_dmarc." + apex, "TXT", get)):
                f.append(f"mail: _dmarc.{apex} has no DMARC")
            sel = mail.get("dkim_selector")
            if sel and not any(re.search(r"p=[A-Za-z0-9+/]{40,}", t.replace('" "', "").replace('"', ""))
                               for t in _doh(f"{sel}._domainkey.{apex}", "TXT", get)):
                f.append(f"mail: DKIM {sel}._domainkey.{apex} is not published (or its key is empty)")
        except Unreadable:
            f.append(f"mail: {apex}'s records could not be read (DNS over HTTPS did not answer) — not checked")
    return f


def way_in(p):
    p = _d(p)
    d, w = _d(p.get("domains")), _d(p.get("way_in"))
    name = p.get("name") or p.get("product") or "?"
    lines = [f"כניסה ל-{name}"]
    if d.get("app"):
        lines.append(f"  כתובת: https://{d['app']}")
    if p.get("main_account"):
        lines.append(f"  חשבון ראשי: {p['main_account']}")
    if w.get("password"):
        lines.append(f"  סיסמה: {w['password']}")
    if d.get("site"):
        lines.append(f"  האתר: https://{d['site']}")
    return "\n".join(lines)


def check(arg, live=False, get=None):
    p, rel = load_product(arg)
    here = {"product": _d(p).get("product") or arg, "file": rel}
    findings = check_static(p, here)
    if live:
        findings += check_live(p, get)
    here["findings"] = findings
    here["way_in"] = way_in(p)
    return here


def _room_name(r):
    """A room as product.json may write it: a name, or a number («101»). Anything else, or empty, names no room."""
    return str(r).casefold() if isinstance(r, (str, int)) and not isinstance(r, bool) and str(r) else None


def names_room(p, room, which="both"):
    """Does this product.json name the meeting? Either the meeting that decided the product (`meeting.room`) or a later
    meeting of the same product (`meeting.rooms`). exx102 went on with Examplex a day after exx101 decided it, and
    «קדימה exx102» has to find Examplex's end state, not «none declared». `which`: "decided", "later" or "both"."""
    m = _d(_d(p).get("meeting"))
    rooms = ([m.get("room")] if which in ("decided", "both") else []) + \
        (m.get("rooms") if which in ("later", "both") and isinstance(m.get("rooms"), list) else [])
    want = str(room).casefold()
    return any(_room_name(r) == want for r in rooms)


def product_for(room):
    """The product of a meeting. The product that the meeting DECIDED wins over one that only lists it as a later
    meeting, whatever the order of the apps."""
    loaded = []
    for rel in all_products():
        try:
            with open(os.path.join(REPO, rel), encoding="utf-8") as f:
                loaded.append((rel, _d(json.load(f))))
        except (OSError, ValueError):
            continue
    for which in ("decided", "later"):
        for rel, p in loaded:
            if names_room(p, room, which):
                return rel
    return None


# ── the doors ─────────────────────────────────────────────────────────────────────────────────────────────────

def _print_check(r):
    n = len(r["findings"])
    counts = r.get("requirements") or {}
    tally = " · ".join(f"{k} {v}" for k, v in sorted(counts.items()))
    print(f"product {r['product']} ({r['file']}): {'END STATE STANDS' if not n else f'{n} missing'}"
          + (f" — requirements: {tally}" if tally else ""))
    for line in r["findings"]:
        print(f"  ✗ {line}")
    for line in r.get("owner") or []:
        print(f"  בעלים {line}")
    print()
    print(r["way_in"])


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    verb, args = argv[0], argv[1:]
    if verb == "--self-test":
        return self_test()
    if verb == "resolve":
        rows_from = None
        if "--rows" in args:
            i = args.index("--rows")
            rows_from = args[i + 1] if i + 1 < len(args) and not args[i + 1].startswith("--") else "-"
            args = args[:i] + args[i + 1 + (rows_from != "-" or (i + 1 < len(args) and args[i + 1] == "-")):]
        if rows_from in (None, "-"):
            text = sys.stdin.read()
        else:
            try:
                with open(rows_from, encoding="utf-8") as fh:
                    text = fh.read()
            except OSError:
                print(f"kadima: the rows file {rows_from} cannot be read", file=sys.stderr)
                return 2
        best, others = resolve(args, parse_rows(text))
        if not best:
            print(f"no meeting matches {' '.join(args)!r} — «קדימה» is then the release line (ai/context/kadima.md)")
            return 1
        print(f"room: {best['room']}")
        for k in ("started", "title", "state", "page"):
            if best.get(k):
                print(f"{k}: {best[k]}")
        rel = product_for(best["room"])
        print(f"product: {rel or '— none declared; if the meeting decided one, its first commit declares apps/<app>/product.json'}")
        for o in others:
            print(f"  also: {o['room']}  {o['started']}  {o.get('title') or ''}".rstrip())
        return 0
    if verb == "product-for":
        rel = product_for(args[0]) if args else None
        print(rel or "")
        return 0 if rel else 1
    if verb == "check":
        live, as_json = "--live" in args, "--json" in args
        targets = [a for a in args if not a.startswith("--")] or all_products()
        results = [check(t, live) for t in targets]
        if as_json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            for r in results:
                _print_check(r)
        return 1 if any(r["findings"] for r in results) else 0
    print(__doc__)
    return 2


# ── self-test ─────────────────────────────────────────────────────────────────────────────────────────────────

def self_test():
    import tempfile
    ok = True
    n = 0

    def eq(name, got, want):
        nonlocal ok, n
        n += 1
        if got != want:
            ok = False
            print(f"FAIL {name}: {got!r} != {want!r}")

    # the formats cli.py prints (server.py's started = «YYYY-MM-DD HH:MM»)
    rows = parse_rows(
        "2026-11-11 21:51  EXX101  [done]  -  aa5b/EXX101_2026-11-11-21-51-48.mp4\n"
        "2026-11-09 16:00  exu103  [done]  דנה  bb/exu103.mp4\n"
        "2026-11-11 21:51  exx101  Examplex — פלטפורמת B2B  https://c/a/meet/flow/exx101/\n"
        "2026-11-01 11:00  exxa-old  ישיבה ישנה  https://c/a/meet/flow/exxa-old/\n"
        "2026-11-08 11:00  bs101    https://c/a/meet/flow/bs101/\n"
        "2026-11-07 10:00    [done]  -  cc/_x.mp4\n"
        "no recordings\n")
    eq("rows (the roomless recording skipped)", len(rows), 5)
    eq("empty title is not the page", [r["title"] for r in rows if r["room"] == "bs101"], [""])
    best, others = resolve(["exx"], rows)
    eq("«קדימה exx» → exx101 (prefix, newest)", best["room"], "exx101")
    eq("page and recording merge case-blind", (best["page"], best["state"]), ("https://c/a/meet/flow/exx101/", "done"))
    eq("the older prefix is an alternative", [o["room"] for o in others], ["exxa-old"])
    eq("«פגישת exx101» → exact", resolve(["פגישת", "exx101"], rows)[0]["room"], "exx101")
    eq("a title word", resolve(["B2B"], rows)[0]["room"], "exx101")
    eq("nothing", resolve(["zzz"], rows)[0], None)
    eq("stop words alone match nothing", resolve(["קדימה"], rows)[0], None)
    eq("newest within a tier", resolve(["b"], parse_rows(
        "2026-11-01 09:00  b1  x  https://c/1/\n2026-11-10 09:00  b2  y  https://c/2/\n"))[0]["room"], "b2")
    two = {"meeting": {"room": "exx101", "rooms": ["exx102"]}}
    eq("a later meeting of the product names it (case-blind)", names_room(two, "EXX102"), True)
    eq("…and the meeting that decided it still does", names_room(two, "exx101"), True)
    eq("another room does not", names_room({"meeting": {"room": "exx101"}}, "exx102"), False)
    eq("rooms that are not a list are no crash", names_room({"meeting": {"room": "x1", "rooms": "x2"}}, "x2"), False)
    eq("a meeting that is not an object is no crash", names_room({"meeting": "exx101"}, "exx101"), False)
    eq("a room written as a number still names it", names_room({"meeting": {"room": 101}}, "101"), True)
    eq("an empty room names nothing", names_room({"meeting": {"room": ""}}, ""), False)
    eq("«decided» ignores the later meetings", names_room(two, "exx102", "decided"), False)
    eq("«later» ignores the deciding meeting", names_room(two, "exx101", "later"), False)
    eq("a string for rooms is a finding", any("meeting.rooms" in x for x in check_static(
        {"meeting": {"room": "x1", "rooms": "x2"}}, {})), True)
    eq("a list of rooms is none", any("meeting.rooms" in x for x in check_static(
        {"meeting": {"room": "x1", "rooms": ["x2"]}}, {})), False)

    ci = os.path.join(REPO, "ci-artifacts")
    with tempfile.TemporaryDirectory(dir=ci if os.path.isdir(ci) else None) as tmp:
        req = os.path.join(tmp, "req.json")
        with open(req, "w", encoding="utf-8") as fh:
            json.dump({"items": [
                {"id": "r1", "quote": "ברמה של וולט", "status": "done", "where": "x.js"},
                {"id": "r2", "ask": "invite an agent", "status": "missing", "gap": "no button"},
                {"id": "r3", "ask": "market data", "status": "later"},
                {"id": "r1", "ask": "dup", "status": "maybe"},
                {"id": "r4", "ask": "prices", "status": "owner", "item": "DGO-1833"},
                "a string"]}, fh)
        rf, counts, owner = check_requirements(req)
        eq("requirements findings", len(rf), 5)  # r2 open, r3 later w/o why, dup id, unknown status, a non-object
        eq("requirements counts", counts, {"done": 1, "missing": 1, "later": 1, "maybe": 1, "owner": 1})
        eq("owner points listed apart", owner, ["r4: prices — DGO-1833"])
        eq("a missing file", check_requirements(os.path.join(tmp, "none.json"))[0][0].endswith("is not there"), True)
        here2 = {}
        two_files = check_static({"meeting": {"room": "x1"}, "requirements": [req, req]}, here2)
        eq("a list of requirement files is read file by file, and counted together",
           (here2["requirements"].get("done"), sum("[missing]" in x for x in two_files)), (2, 2))
        eq("an entry of the list that is not a path is a finding",
           any("is not a file's path" in x for x in check_static({"requirements": [req, 7]}, {})), True)
        eq("an empty product misses every part", len(check_static({}, {})) >= 20, True)
        odd = {"meeting": "exx101", "sources": ["ci-artifacts/x"], "view_as": True, "roles": ["a", "b"],
               "domains": "x", "mail": None, "site": [], "requirements": req}
        eq("odd shapes are findings, not crashes", any("view_as" in x for x in check_static(odd, {})), True)

    good = {"domains": {"office_ip": "93.184.216.7", "app": "app.x.co", "site": "www.x.co", "apex": "x.co"},
            "mail": {"mailbox": "person82@example.com", "dkim_selector": "mail"},
            "site": {"house_line": "מבית הלשכה הדיגיטלית", "backlinks": ["https://bina.example", "digital-office.co.il"],
                     "logo": "office-mark"}}
    page = ('<a href="https://app.x.co/">app</a> מבית הלשכה הדיגיטלית <img src="office-mark.svg" alt="">'
            '<a href="https://bina.example/">b</a><a href="https://digital-office.co.il/">d</a>')
    key = '"v=DKIM1; k=rsa; p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAx"'

    def fake(answers, apex_loc="https://www.x.co/", html=page, app=(200, ""), doh=200):
        def get(url, headers=None):
            if "dns-query" in url:
                if doh != 200:
                    return doh, "", ""
                q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
                k = (q["name"][0], q["type"][0])
                t = {"A": 1, "MX": 15, "TXT": 16}[k[1]]
                return 200, "", json.dumps({"Answer": [{"type": t, "data": v} for v in answers.get(k, [])]})
            if url == "https://x.co/":
                return 301, apex_loc, ""
            if url == "https://www.x.co/":
                return 200, "", html
            if url == "https://app.x.co/":
                return app[0], app[1], ""
            return 404, "", ""
        return get

    full = {("app.x.co", "A"): ["93.184.216.7"], ("www.x.co", "A"): ["93.184.216.7"], ("x.co", "A"): ["93.184.216.7"],
            ("x.co", "MX"): ["10 mail.x.co."], ("mail.x.co", "A"): ["93.184.216.7"], ("x.co", "TXT"): ['"v=spf1 a mx -all"'],
            ("_dmarc.x.co", "TXT"): ['"v=DMARC1; p=quarantine"'], ("mail._domainkey.x.co", "TXT"): [key]}
    eq("live: all standing", check_live(good, fake(full)), [])
    parked = {**full, ("x.co", "A"): ["93.184.216.15"]}
    eq("live: a parked apex", len(check_live(good, fake(parked))), 1)
    eq("live: no 301", any("301s" in x for x in check_live(good, fake(full, apex_loc=""))), True)
    eq("live: a sign-in elsewhere is not the app", any("door" in x for x in check_live(
        good, fake(full, app=(302, "https://auth.office/login")))), True)
    eq("live: the app's own sign-in redirect passes", check_live(good, fake(full, app=(302, "/login"))), [])
    eq("live: a site without the house and its logo", len(check_live(good, fake(full, html=(
        '<a href="https://app.x.co/">a</a><a href="https://bina.example/">b</a>'
        '<a href="https://digital-office.co.il/">d</a> office-mark')))), 2)
    mailto = page.replace('<a href="https://digital-office.co.il/">d</a>', 'mailto:hello@digital-office.co.il')
    eq("live: a mailto is no backlink",
       any("digital-office.co.il" in x for x in check_live(good, fake(full, html=mailto))), True)
    eq("live: DKIM unpublished", any("DKIM" in x for x in check_live(
        good, fake({k: v for k, v in full.items() if k != ("mail._domainkey.x.co", "TXT")}))), True)
    eq("live: an empty DKIM key (revoked)", any("DKIM" in x for x in check_live(
        good, fake({**full, ("mail._domainkey.x.co", "TXT"): ['"v=DKIM1; p="']}))), True)
    eq("live: a null MX is no mail", any("no MX" in x for x in check_live(
        good, fake({**full, ("x.co", "MX"): ["0 ."]}))), True)
    eq("live: an MX off the office", any("does not reach" in x for x in check_live(
        good, fake({**full, ("mail.x.co", "A"): ["9.9.9.9"]}))), True)
    down = check_live(good, fake(full, doh=429))
    eq("live: DNS over HTTPS down is «could not be read», never a wrong record",
       (any("could not be read" in x for x in down), any("not the office" in x for x in down)), (True, False))
    print(f"self-test: {'ok' if ok else 'FAILED'} ({n} cases)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
