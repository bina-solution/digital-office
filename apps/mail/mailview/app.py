"""mailview — מייל: read-only + tagging web UI for the CONNECTED email account.

Talks ONLY to the inbox abstraction (http://mailapi:8970) — never to a mail
server directly — so it renders whichever account GMAIL_IMAP_MODE points at:
'local' (GreenMail mailserver) or 'gmail' (real account via app password). Same UI,
same tags, either backend. Serves a my-docs/מסמכים שלי-styled RTL SPA (static/) plus a thin
proxy API (inbox is network-internal). Mutations = label add/remove, and sending: compose
(and the reader's reply / reply-all / forward) post to /api/send, which is the mail service's
own /send and nothing more.
"""
import os, base64, json, re, time, calendar, datetime
import urllib.parse
import requests
from email.utils import parsedate_to_datetime
from flask import Flask, request, jsonify, send_from_directory, Response, has_request_context

# ── Sentry/GlitchTip error reporting (platform standard) ──────────────────────────
# Wired declaratively: glitchtip-push mints this service's project + deterministic DSN into
# MAILVIEW_SENTRY_DSN in .env; compose maps it to SENTRY_DSN. No-op if unset.
_SENTRY_DSN = os.getenv("SENTRY_DSN")
if _SENTRY_DSN:
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=_SENTRY_DSN,
            environment=os.getenv("SENTRY_ENVIRONMENT", os.getenv("DEPLOYMENT_NAME", "production")),
            release=os.getenv("SENTRY_RELEASE"),
            traces_sample_rate=0.0,
            send_default_pii=False,
        )
    except Exception:  # never let telemetry break the app
        pass

app = Flask(__name__, static_folder="static", static_url_path="")
GI = os.environ.get("GMAIL_IMAP_URL", "http://mailapi:8970")
# One keep-alive pool for every hop to the mail service. Bare requests.request() opened and tore
# down a TCP connection per call, and this proxy fronts EVERY read the SPA makes — a message open is
# three upstream calls on its own. requests.Session is thread-safe for plain requests like these.
_HTTP = requests.Session()


# ── the explicit-connection contract (mailapi service.py `_explicit_connection_required`) ──────
# The mail service's canonical ops REFUSE a call that names no connection: `/data/active.json` is a
# shared pointer, flipped by a human clicking the account bar AND by any test run that needs a
# different mailbox, so an op that omitted the id ran against whoever the pointer last named. This
# UI was one of the callers that omitted it — every `gi()` op below used to travel without one.
#
# The owner's rule is not "the UI is exempt", it is "two separate calls: one to GET the selected
# connection, one to ACT with it — never act blindly". `_selected()` is the first call and
# `_OPS`-matching paths in `gi()` carry its answer onto the second. That keeps the account bar's
# convenience while making the id something this client STATES rather than something the service
# INFERS, which is the whole distinction.
#
# Cached for _SEL_TTL seconds, not forever: switching accounts must take effect without a restart,
# and a per-op round trip to /connections would double this UI's request count. A resolution
# FAILURE is never cached — the next request retries rather than pinning a transient outage.
_OPS = ("/search", "/message/", "/thread/", "/labels", "/append", "/send", "/ui/")
_SEL = {"id": None, "at": 0.0}
_SEL_TTL = 30.0
# The empty-value shapes mailapi's own `_backend` rejects. Normalising them HERE too means a client
# that sends `?connection_id=` (an unrendered template, the shape the 2026-08-07 access log caught)
# is treated as having named nothing, rather than as having named the empty string.
_BLANK = ("", "undefined", "null", "none")


class Upstream(Exception):
    """A mailapi answer this UI could not use — carrying the SERVICE's own status and message.

    `gi()` used to end in a bare `raise_for_status()`. Every upstream 4xx therefore became an opaque
    Flask 500 whose real sentence existed only inside a traceback, which is why the explicit-connection
    400 was invisible in this app's own logs for the length of an outage: the UI showed `שגיאה (500)`
    and the log showed a generic 500, and neither said `requires an explicit connection_id`. The
    diagnosis has to travel to the browser, so it is carried, not discarded.
    """

    def __init__(self, status, message, path=None, payload=None):
        super().__init__(message)
        self.status, self.message, self.path, self.payload = status, message, path, payload


@app.errorhandler(Upstream)
def _upstream_error(e):
    """A 4xx is the caller's problem and travels verbatim (status AND text). Anything else is this hop
    failing to get a usable answer out of a service it can normally reach — a gateway fault, 502 —
    regardless of what the far end labelled it."""
    code = e.status if 400 <= (e.status or 0) < 500 else 502
    app.logger.warning("mailview: upstream %s on %s — %s", e.status, e.path, e.message)
    body = {"error": e.message, "upstream_status": e.status, "upstream_path": e.path}
    if isinstance(e.payload, dict):
        body["upstream"] = e.payload
    return jsonify(body), code


def _clean(cid):
    cid = cid.strip() if isinstance(cid, str) else None
    return None if (cid or "").lower() in _BLANK else cid


def _requested_cid():
    """The SPA's own choice, when it made one — the true two-call shape. A client that has already
    read /connections (the account bar has) names the mailbox it means and this hop only carries it.
    Read from the query string, and from the JSON body on a mutation. Absent one, `_selected()`
    supplies the active connection as an explicit, LOGGED default — never an inferred one."""
    if not has_request_context():
        return None
    cid = _clean(request.args.get("connection_id"))
    if not cid and request.method != "GET":
        cid = _clean((request.get_json(silent=True) or {}).get("connection_id"))
    return cid


def _selected():
    """Call 1 of 2: which connection has the operator selected? Answered by /connections — the plane
    that knows about the client's real mailbox. NOT /engine/profiles, which lists only the local
    dovecot test accounts: resolving there would send the owner's label edits to a test mailbox and
    report success, which is worse than the outage this fixes.

    Cannot-resolve is an ERROR, not a skip. Returning None here and letting the op travel bare would
    be the same silent resolution one layer out, and would put a mailbox's identity in the hands of
    whatever `/data/active.json` last pointed at. A transient /connections blip reuses the last known
    good id (a real answer, previously verified); with no last known good, the request fails loudly
    and nothing is sent.

    Cached for _SEL_TTL seconds, not forever: switching accounts must take effect without a restart,
    and a per-op round trip would double this UI's request count. Failures are never cached.
    """
    import time
    now = time.time()
    if _SEL["id"] and (now - _SEL["at"]) < _SEL_TTL:
        return _SEL["id"]
    try:
        r = _HTTP.get(GI + "/connections", timeout=10)
        r.raise_for_status()
        cid = _clean((r.json() or {}).get("active"))
    except Exception as exc:
        if _SEL["id"]:
            app.logger.warning("mailview: /connections unreachable (%s) — reusing last selected %s",
                               exc, _SEL["id"])
            return _SEL["id"]
        raise Upstream(503, "mailview: could not determine which mail connection is selected — "
                            f"GET {GI}/connections failed ({exc}). Nothing was sent to any mailbox.",
                       path="/connections")
    if not cid:
        raise Upstream(409, "mailview: no mail connection is selected (/connections returned "
                            "active=null). Choose an account in the account bar, or call this "
                            "endpoint with an explicit connection_id. Nothing was sent to any "
                            "mailbox.", path="/connections")
    if cid != _SEL["id"]:
        app.logger.info("mailview: selected mail connection = %s", cid)
    _SEL["id"], _SEL["at"] = cid, now
    return cid


def gi(path, method="GET", body=None, timeout=60):
    """Call 2 of 2. Canonical-op paths carry an explicit connection — in the body for a JSON method,
    as a query param for a GET. A path that already names one is left alone, so a caller can still
    target a specific mailbox. Non-op paths (/healthz, /organizer/*) are untouched: they do not act
    on mail and the service does not require an id for them.

    There is deliberately no `or` fallback and no conditional spread on the id. `{**(x and {...})}`
    omits the key on a falsy value instead of failing, which is precisely how an op ends up resolved
    implicitly — the shape behind the original incident. Here the id is either stated or the request
    raises before a single byte reaches a mailbox.
    """
    if any(path.startswith(p) for p in _OPS) and "connection_id=" not in path:
        cid = _requested_cid()
        if cid is None:
            cid = _selected()          # explicit default, or raises — never travels blind
        if body is not None or method != "GET":
            body = dict(body or {})
            body.setdefault("connection_id", cid)
        else:
            path += ("&" if "?" in path else "?") + "connection_id=" + cid
    try:
        r = _HTTP.request(method, GI + path, json=body, timeout=timeout)
    except requests.RequestException as exc:
        raise Upstream(504, f"mailview: {method} {path} could not reach the mail service ({exc})",
                       path=path)
    if r.status_code >= 400:
        payload, msg = None, (r.text or "").strip()[:800]
        try:
            payload = r.json()
            if isinstance(payload, dict):
                msg = payload.get("error") or payload.get("message") or msg
        except ValueError:
            pass
        raise Upstream(r.status_code, msg or f"mail service returned {r.status_code}",
                       path=path, payload=payload)
    try:
        return r.json()
    except ValueError:
        raise Upstream(502, f"mailview: {method} {path} returned a non-JSON body "
                            f"({r.headers.get('content-type')})", path=path)


# ── organizer settings (mail-organizer-refactor.md §7) ─────────────────────────
# The tag-rule organiser now lives in the MAIL app. These proxy the mailapi
# options plane so the SPA can read/save rules without a new network edge.
@app.get("/api/organizer/defaults")
def organizer_defaults():
    return jsonify(gi("/organizer/defaults"))


@app.put("/api/organizer/defaults")
def organizer_defaults_put():
    body = request.get_json(force=True, silent=True) or {}
    r = _HTTP.put(GI + "/organizer/defaults", json=body, timeout=60)
    try:
        return jsonify(r.json()), r.status_code
    except ValueError:
        # same defect as gi()'s old raise_for_status: an upstream error page is not JSON, and
        # decoding it blind turned a readable 4xx into an opaque 500 here too.
        raise Upstream(r.status_code if r.status_code >= 400 else 502,
                       (r.text or "").strip()[:800] or f"mail service returned {r.status_code}",
                       path="/organizer/defaults")


@app.get("/organizer")
def organizer_page():
    return send_from_directory("static", "index.html")


@app.get("/")
@app.get("/attention")
@app.get("/v/<path:_rest>")
@app.get("/label/<path:_rest>")
@app.get("/message/<path:_rest>")
@app.get("/settings")
@app.get("/settings/<path:_rest>")
def index(_rest=None):
    """SPA entry — every screen is a URL (deep-linkable, refresh-safe):
    `/` inbox · `/attention` · `/v/<view>` (starred, sent, drafts, important, all, spam, trash) ·
    `/label/<name>` · `/?q=` · `/message/<id>` · `/organizer` · `/settings[/<section>]`.
    The client (static/app.js applyUrl) reads the same grammar; a reload on any of them lands on
    the same screen, standalone or mounted under the console's /a/mailview/ prefix."""
    return send_from_directory("static", "index.html")


def _active_conn():
    """The ACTIVE connection's catalog row — an IMAP-free read (~ms). {} when unavailable.

    Exists because the two readers below used to learn `user`/`mode` from `/healthz`, and healthz
    NOOPs the write IMAP connection. Under Gmail's per-command throttle (measured live 2026-08-31:
    ~10s PER IMAP COMMAND on this deployment's account) that put a 10-20s upstream stall inside
    /api/account on every SPA boot and inside whichever /api/messages call refreshed the mode cache.
    The catalog answers the same two questions from the vault listing without touching IMAP at all."""
    try:
        r = _HTTP.get(GI + "/connections", timeout=10)
        r.raise_for_status()
        d = r.json() or {}
        act = d.get("active")
        return next((c for c in (d.get("connections") or []) if c.get("id") == act), None) or {}
    except Exception:
        return {}


@app.get("/api/account")
def account():
    inst = _active_conn()
    user = (inst.get("account_hint") or "").strip()
    if user:
        return jsonify({"user": user,
                        "mode": "local" if inst.get("protocol") == "mail_imap_local" else "gmail"})
    h = gi("/healthz")   # catalog unavailable or hint empty — the old (IMAP-noop) path still answers
    return jsonify({"user": h.get("user", "?"), "mode": h.get("mode", "gmail")})


@app.get("/api/labels")
def labels():
    return jsonify(gi("/labels"))


@app.post("/api/labels")
def labels_create():
    """Create a label on the named mailbox (`connection_id` in the body or query) — the mail app is
    the one place a tag is made (owner rule 2026-09-02: INDOX picks tags from the connection, it
    never creates them). Idempotent at the service: an existing label answers as existing."""
    b = request.get_json(force=True, silent=True) or {}
    name = str(b.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    return jsonify(gi("/labels/create", "POST", {"name": name}))


@app.get("/api/connections")
def connections():
    """The mail connection catalog (id, label, protocol, account_hint, active) — served through
    this embedded UI so a sibling app in the console shell (INDOX's sync editor) can list mailboxes
    same-origin, without a network edge of its own into the mail service."""
    return jsonify(gi("/connections"))


@app.get("/api/label-map")
def label_map():
    """KEY -> label NAME for the tag-rule vocabulary the label engine itself runs on
    (mail-organizer-refactor.md §Config model). A straight pass-through of mailapi's
    /organizer/settings — the SAME resolution point mailLabelEngine01 uses (`Load
    Settings` node reads `.gmail.labels[KEY].name`), so the row triage dot (see
    static/app.js) can never show a stale label TEXT: the vocabulary changed once
    already for this client (see ai/context/hacohen-cutover-plan-2026-08-05.md §B) and
    will again. No connection_id: this is the mail-scoped defaults singleton, exactly
    what the engine's own scheduled (no-override) run resolves against."""
    return jsonify(gi("/organizer/settings"))


FAIL_RE = re.compile(r"נכשל|לא מזוהה")           # attention-queue label set
# synthetic battery mail: injection markers, demo senders, and the unique-corpus
# alias token every synthetic doc subject is stamped with (bnyas-3, dltvt-tyyr-2…)
TEST_RE = re.compile(
    r"הזרקת בדיקה|Demo Link|@demo\.indox|demo\+\d+@|@[\w.-]*example\.com"
    r"|\b[a-z]{2,}(?:-[a-z]{2,})*-\d{1,2}\b")

_mode_cache = {"v": None, "t": 0.0}


def _mode():
    """Backend mode (60s cache) — decides the test-mail default: the local mailserver
    IS the demo, so test mail shows there; on the real account it hides.

    Resolved from the connection CATALOG (protocol of the active connection), not from /healthz —
    see `_active_conn()`: the healthz read cost one write-conn IMAP NOOP, which under Gmail's
    command throttle stalled a list load by 10-20s once a minute. /healthz remains the fallback
    when the catalog cannot answer, so a degraded connections plane cannot take the mode with it."""
    import time
    if _mode_cache["v"] is None or time.time() - _mode_cache["t"] > 60:
        inst = _active_conn()
        if inst.get("protocol"):
            _mode_cache["v"] = "local" if inst["protocol"] == "mail_imap_local" else "gmail"
            _mode_cache["t"] = time.time()
        else:
            try:
                _mode_cache["v"] = gi("/healthz").get("mode", "gmail")
                _mode_cache["t"] = time.time()
            except Exception:
                return _mode_cache["v"] or "gmail"
    return _mode_cache["v"]


def _ts(m):
    try:
        return parsedate_to_datetime(m.get("date", "")).timestamp()
    except Exception:
        return 0


# ── the inbox time window ─────────────────────────────────────────────────────
#
# THIS is where calendar meaning lives, and mailapi deliberately has none of it. The mail service
# takes one number — `since_ts`, an absolute instant — and owns the IMAP mechanics (widen a day, AND
# a `SINCE` term, refine on INTERNALDATE; see mailapi/app.py). Everything that needs to know what a
# HUMAN means by "today" is here, one hop from the browser that can actually answer it.
#
# ⚠ THE TIMEZONE IS THE USER'S, NEVER THE SERVER'S, AND THAT IS NOT A STYLE CHOICE. This container
# runs UTC; the client reading this inbox is in Asia/Jerusalem (UTC+3 in summer). A "today" computed
# from server time would begin three hours late — every message this client received between 00:00
# and 03:00 local would be missing from "today", every day, silently. So the browser sends its own
# `new Date().getTimezoneOffset()` and the day/month boundaries are cut in THAT frame.
#
# The two sub-day windows are exempt from all of it: "the last 30 minutes" is the same 30 minutes in
# every timezone on earth. Only the CALENDAR windows (today / this month) need an offset at all,
# which is why the offset is read but not required.
WINDOWS = ("all", "30m", "1h", "today", "month")
_WINDOW_SECONDS = {"30m": 1800, "1h": 3600}


def _since_ts(win, tz_off_min, now=None):
    """The absolute instant a window starts, or None for "all" (and for anything unrecognised —
    an unknown window must widen to everything, never silently hide mail).

    `tz_off_min` is the browser's `Date.prototype.getTimezoneOffset()`: minutes to ADD to local time
    to reach UTC, so it is NEGATIVE east of Greenwich (Israel in summer sends -180). Clamped to the
    real range of earth's offsets (-14h..+14h) so a malformed or hostile value cannot move the day
    boundary by years; an unparseable one means UTC, which is only ever wrong by hours and never
    wrong by a whole window.
    """
    win = (win or "all").strip().lower()
    if win not in WINDOWS or win == "all":
        return None
    now = time.time() if now is None else now
    if win in _WINDOW_SECONDS:
        return now - _WINDOW_SECONDS[win]
    try:
        shift = max(-14 * 60, min(14 * 60, int(tz_off_min))) * 60
    except (TypeError, ValueError):
        shift = 0
    # Shift the instant into the user's frame, cut the boundary there, shift the boundary back.
    # `utcfromtimestamp` on an already-shifted epoch is the standard way to get a NAIVE datetime
    # that reads as local wall-clock; `calendar.timegm` is its exact inverse. Doing it in this
    # order is what keeps the arithmetic reversible and the boundary exact.
    loc = datetime.datetime.utcfromtimestamp(now - shift)
    loc = loc.replace(hour=0, minute=0, second=0, microsecond=0)
    if win == "month":
        loc = loc.replace(day=1)
    return calendar.timegm(loc.timetuple()) + shift


def _window_args():
    """(win, since_ts) for this request. One reader, so every search on this endpoint — including
    the multi-search `attention` view — applies the same window from the same instant."""
    win = (request.args.get("win") or "all").strip().lower()
    if win not in WINDOWS:
        win = "all"
    return win, _since_ts(win, request.args.get("tz"))


@app.get("/api/messages")
def messages():
    """List messages: label filter, free-text query (gmail grammar passthrough), or
    view=attention (union of failure labels, merged + deduped across searches).
    Synthetic battery mail is hidden unless test=1 (count returned for the toggle)."""
    label = (request.args.get("label") or "").strip()
    text = (request.args.get("q") or "").strip()
    limit = int(request.args.get("limit", 100))
    view = (request.args.get("view") or "").strip().lower()
    # THE INBOX IS A FOLDER, NOT A FILTER. The landing view used to search `[Gmail]/All Mail` with
    # no INBOX criterion at all, so "דואר נכנס" listed every message the account had ever archived,
    # and archiving one from this UI could not visibly remove it — the client faked the removal in
    # memory and a reload put it back. Selecting the real INBOX folder makes the list the mailbox's
    # own answer, and makes `archived` (= remove INBOX, see MARK_LABELS) an action whose effect
    # survives a refresh. Every other scope keeps All Mail in gmail mode so a label view, a search
    # and "כל הדואר" still see archived mail; the local backend has one folder either way.
    is_inbox = view in ("", "inbox") and not label and not text
    folder = "INBOX" if (is_inbox or _mode() != "gmail") else "[Gmail]/All Mail"
    win, since_ts = _window_args()
    total, has_more, next_cursor = None, False, 0
    if view == "attention":
        fails = [l for l in gi("/labels").get("labels", []) if FAIL_RE.search(l)]
        msgs = []
        if fails:
            # ONE search, not one per failure label. Both backends speak `(a OR b OR c)` — Gmail's
            # X-GM-RAW natively, the local grammar via its parenthesized-OR group — so the union the
            # loop used to assemble client-side (N sequential /search round trips, each a full IMAP
            # SEARCH+FETCH on the shared backend connection) is the server's job. Under Gmail's
            # per-command throttle N searches cost N× the whole view; locally they serialized behind
            # the one connection lock. A single search also dedups by construction.
            terms = ["label:" + l.replace(" ", "-") for l in fails]
            body = {"query": terms[0] if len(terms) == 1 else "(" + " OR ".join(terms) + ")",
                    "limit": limit, "folder": folder}
            if since_ts is not None:
                body["since_ts"] = since_ts
            msgs = sorted(gi("/search", "POST", body).get("messages", []), key=_ts, reverse=True)
        total = len(msgs)
    else:
        parts = []
        if view and view in VIEW_QUERIES and VIEW_QUERIES[view]:
            parts.append(VIEW_QUERIES[view])
        if label:
            # Gmail's X-GM-RAW matches labels by their hyphenized form (spaces -> '-');
            # the local backend resolves that form too, so one shape serves both.
            parts.append("label:" + label.replace(" ", "-"))
        if text:
            parts.append(text)
        body = {"limit": limit, "folder": folder}
        if request.args.get("before_uid"):
            body["before_uid"] = int(request.args["before_uid"])
        if since_ts is not None:
            # Sent alongside `query`/`criteria`, never instead of them: the mail service ANDs it into
            # the same SEARCH, so a window composes with a label filter or a text search rather than
            # overriding one. Note it is NOT expressed as Gmail's `newer_than:` grammar — that would
            # only work on the Gmail backend and would silently do nothing on the local one.
            body["since_ts"] = since_ts
        if parts:
            body["query"] = " ".join(parts)
        else:
            body["criteria"] = ["ALL"]
        d = gi("/search", "POST", body)
        msgs = d.get("messages", [])
        msgs.reverse()                  # newest first for the UI
        total = d.get("total")
        has_more = bool(d.get("has_more"))
        next_cursor = d.get("next_cursor") or 0
    t = request.args.get("test")
    show_test = t == "1" if t in ("0", "1") else _mode() == "local"
    test_total = sum(1 for m in msgs
                     if TEST_RE.search((m.get("subject") or "") + " " + (m.get("from") or "")))
    if not show_test and test_total:
        msgs = [m for m in msgs
                if not TEST_RE.search((m.get("subject") or "") + " " + (m.get("from") or ""))]
    # `win` is echoed so the UI can prove which window the SERVER actually applied, rather than
    # trusting the one it asked for — an out-of-date tab or a clamped/unknown value would otherwise
    # label a full list as filtered.
    return jsonify({"messages": msgs, "count": len(msgs),
                    "total": total if total is not None else len(msgs),
                    "has_more": has_more, "next_cursor": next_cursor,
                    "test_total": test_total, "test_hidden": not show_test,
                    "win": win, "since_ts": since_ts})


@app.get("/api/message/<mid>")
def message(mid):
    """Message for reading: meta mode = headers + text/html parts + attachment LIST only.
    On the real-Gmail backend this avoids downloading multi-MB attachment bytes per open
    (bytes stream on demand via /api/attachment)."""
    return jsonify(gi(f"/message/0?id={mid}&meta=true&attachments=false"))


@app.get("/api/attachment/<mid>/<int:idx>")
def attachment(mid, idx):
    """Stream one attachment's bytes (for inline preview / download)."""
    d = gi(f"/message/0?id={mid}&attachments=true", timeout=120)
    atts = d.get("attachments", [])
    if idx >= len(atts) or "data_base64" not in atts[idx]:
        return jsonify({"error": "not found"}), 404
    a = atts[idx]
    data = base64.b64decode(a["data_base64"])
    fn = a.get("filename", "attachment")
    return Response(data, mimetype=a.get("mimeType", "application/octet-stream"),
                    headers={"Content-Disposition": f"inline; filename*=UTF-8''{requests.utils.quote(fn)}"})


N8N = os.environ.get("N8N_URL", "http://n8n:5678")


@app.get("/api/doc-context/<mid>")
def doc_context(mid):
    """Pipeline state for a message — via the n8n API layer (mailApi01 webhook ->
    indoxApiRouter01), never the DB directly.

    Two different answers used to collapse into one: "this message is not a document" and "the
    document system could not be asked" both came back as `{found: 0}`, so an n8n outage looked
    like a mailbox full of personal mail. A failure now says so (`unavailable` + the reason) and
    the reader shows it as a failure, not as an absence."""
    try:
        r = _HTTP.get(N8N + "/webhook/mail-api/doc-context",
                      params={"source_id": mid}, timeout=30)
        r.raise_for_status()
        return jsonify(r.json())
    except Exception as exc:
        app.logger.warning("mailview: doc-context unavailable for %s — %s", mid, exc)
        return jsonify({"found": 0, "docs": [], "unavailable": True,
                        "error": f"{type(exc).__name__}: {exc}"[:300]})


@app.post("/api/tag")
def tag():
    """{id, add:[names], remove:[names]} — the one mutation this app performs."""
    b = request.get_json(force=True)
    mid = b["id"]
    if b.get("add"):
        gi("/labels/add", "POST", {"id": mid, "labels": b["add"]})
    if b.get("remove"):
        gi("/labels/remove", "POST", {"id": mid, "labels": b["remove"]})
    return jsonify({"ok": True})


# System-view names the rebuilt UI's left rail selects. Kept as one table rather than scattered
# `if` branches so the UI and this file cannot disagree about what "starred" means — and so adding a
# view is one line here instead of a new endpoint.
#
# These are Gmail's own label names. The local backend resolves the same hyphenized form (see
# _query_to_criteria), so one shape serves both backends — the same trick /api/messages already
# uses for label filtering.
VIEW_QUERIES = {
    "inbox":     "",                  # a FOLDER, not a query — see messages()
    "starred":   "label:STARRED",
    "important": "label:IMPORTANT",
    "sent":      "label:SENT",
    "draft":     "label:DRAFT",
    "drafts":    "label:DRAFT",       # the rail's id; "draft" alone made טיוטות list the whole box
    "spam":      "label:SPAM",
    "trash":     "label:TRASH",
    "unread":    "is:unread",
    "archived":  "-label:INBOX",
    "all":       "",
}

# What each mark means in label terms. `archive` is the one that is not a label ADD — Gmail archives
# by REMOVING INBOX, and modelling it as anything else loses the mail.
#
# No `trash` and no `snooze`, on purpose. The mail service has no move-to-trash op (the local
# backend is one folder and filters TRASH out of every write; Gmail's \Trash is a folder COPY, not
# an X-GM-LABELS store) and no snooze at all. The client used to paint both as done in memory and a
# reload undid them; it now offers neither rather than a button that lies.
MARK_LABELS = {
    "starred":   ("STARRED", None),
    "important": ("IMPORTANT", None),
    "unread":    ("UNREAD", None),
    "archived":  (None, "INBOX"),
}


@app.post("/api/mark")
def mark():
    """{id|ids, mark:starred|important|unread|archived, on:bool} — state the intent once.

    The UI used to have to know that starring is an add and archiving is a remove, and compose two
    /api/tag calls per action. That put mail semantics in the client, where every caller had to
    reimplement them and could get archive backwards — which does not error, it just loses the mail
    from the inbox with no trace of why.
    """
    b = request.get_json(force=True) or {}
    ids = b.get("ids") or ([b["id"]] if b.get("id") else [])
    what = (b.get("mark") or "").strip().lower()
    on = bool(b.get("on", True))
    if not ids:
        return jsonify({"error": "id or ids required"}), 400
    if what not in MARK_LABELS:
        return jsonify({"error": f"unknown mark {what!r}",
                        "known": sorted(MARK_LABELS)}), 400

    add_label, remove_label = MARK_LABELS[what]
    # `on` flips the direction: starring adds STARRED, un-starring removes it; archiving removes
    # INBOX, un-archiving puts it back.
    add = [add_label] if (add_label and on) else ([remove_label] if (remove_label and not on) else [])
    rem = [add_label] if (add_label and not on) else ([remove_label] if (remove_label and on) else [])
    for mid in ids:
        if add:
            gi("/labels/add", "POST", {"id": mid, "labels": add})
        if rem:
            gi("/labels/remove", "POST", {"id": mid, "labels": rem})
    return jsonify({"ok": True, "count": len(ids), "mark": what, "on": on})


@app.post("/api/send")
def send():
    """{to, subject, body} — the compose window's one call, straight through to the mail service.

    `body` is duplicated into `body_text` because the two backends disagree on the key: the Gmail
    backend reads `body`, the local (GreenMail) one reads `body_text`. Sending both is a one-line
    accommodation here; picking one would make compose work against exactly one of the two accounts
    this app is built to serve interchangeably, and fail silently against the other — the message
    would be accepted, sent empty.

    The connection is attached by `gi()` like every other op — the selected account, stated, not the
    one `/data/active.json` happened to point at when the send landed. A compose window is the single
    worst place to resolve a mailbox implicitly: the wrong answer leaves the client's signature on a
    message from an account they never chose.
    """
    b = request.get_json(force=True) or {}
    to = (b.get("to") or "").strip()
    if not to:
        return jsonify({"error": "to required"}), 400
    body = b.get("body") or ""
    return jsonify(gi("/send", "POST", {"to": to, "subject": b.get("subject") or "",
                                        "body": body, "body_text": body}))


@app.get("/api/thread/<mid>")
def thread(mid):
    """The conversation a message belongs to — a straight pass-through to the mail service.

    That endpoint did not exist until this port; it is also what `Mail Label Engine`'s disabled
    `Get Gmail Thread` node needed, which is why three label rules could never match.

    `bodies` travels through. The reader asks for `bodies=false` (headers only — one BODY.PEEK[HEADER]
    per message instead of a full RFC822 fetch whose attachment bytes were then thrown away for an
    80-character snippet); the rules preview asks for bodies when a rule reads `thread.*`.
    """
    bodies = (request.args.get("bodies") or "").strip().lower()
    q = "?bodies=false" if bodies == "false" else ""
    return jsonify(gi(f"/thread/{mid}{q}"))


# ── the mailbox's own settings (N12: the second mail client's three screens, moved here) ────────
# Mailbox creation, the private-mail DNS/DKIM checklist and the guided provider connect used to be
# reachable only in the mail SERVICE's own UI (mailapi.localhost) — a second client with its own
# copy of the message list. These proxies bring the three screens into this one client under
# /settings; the message-list half of that UI is what the service removes. Paths outside `_OPS`,
# so `gi()` attaches no connection id on its own — the ones that need one (the admin ring on
# /mailboxes) state it explicitly below.
@app.get("/api/setup/status")
def setup_status():
    """DNS / DKIM / PTR / port readiness of the private mail server (read-only, uncached upstream)."""
    return jsonify(gi("/setup/status", timeout=60))


@app.get("/api/mailboxes")
def mailboxes_list():
    return jsonify(gi("/mailboxes"))


@app.post("/api/mailboxes")
def mailboxes_create():
    """Create a mailbox AND its connection (one act, the service's rule). The service guards this
    with its admin ring, keyed on the connection the request acts as — so the selected connection
    travels explicitly, and a Gmail selection is refused by the service with its own sentence."""
    b = request.get_json(force=True, silent=True) or {}
    local = str(b.get("local") or "").strip().lower()
    if not local:
        return jsonify({"error": "שם תיבה נדרש"}), 400
    cid = _requested_cid() or _selected()
    return jsonify(gi("/mailboxes", "POST", {"local": local, "password": b.get("password") or "",
                                              "display_name": b.get("display_name"),
                                              "connection_id": cid}))


@app.delete("/api/mailboxes/<path:address>")
def mailboxes_delete(address):
    cid = _requested_cid() or _selected()
    path = "/mailboxes/" + urllib.parse.quote(address, safe="") + "?connection_id=" + urllib.parse.quote(cid, safe="")
    return jsonify(gi(path, "DELETE"))


@app.get("/api/providers")
def providers():
    """The provider-first catalog the guided connect flow renders (local first, then Gmail)."""
    return jsonify(gi("/providers"))


def _forget_selection():
    """The selected-connection cache and the mode cache both describe the pointer this call just
    moved; a stale answer would send the next op to the previous account for up to 30 s."""
    _SEL["id"], _SEL["at"] = None, 0.0
    _mode_cache["v"], _mode_cache["t"] = None, 0.0


@app.post("/api/connections")
def connections_add():
    """Attach an EXISTING mailbox (app password / OAuth) as a connection — never a local one, which
    the service refuses (a local address is created on the mailbox screen)."""
    b = request.get_json(force=True, silent=True) or {}
    body = {k: b.get(k) for k in ("protocol", "label", "secret", "account_hint") if b.get(k) is not None}
    return jsonify(gi("/connections", "POST", body))


@app.delete("/api/connections/<cid>")
def connections_delete(cid):
    r = gi("/connections/" + urllib.parse.quote(cid, safe=""), "DELETE")
    _forget_selection()
    return jsonify(r)


@app.get("/api/connections/<cid>/probe")
def connections_probe(cid):
    """Verify one connection without selecting it — the same probe /readyz runs."""
    return jsonify(gi("/connections/" + urllib.parse.quote(cid, safe="") + "/probe", timeout=90))


@app.post("/api/connections/select")
def connections_select():
    b = request.get_json(force=True, silent=True) or {}
    cid = _clean(b.get("id"))
    if not cid:
        return jsonify({"error": "id required"}), 400
    r = gi("/connections/select", "POST", {"id": cid})
    _forget_selection()
    return jsonify(r)


@app.get("/healthz")
def healthz():
    """This container's health = the UI proxy is up and the mail SERVICE is reachable — never the
    IMAP account's speed. Proxying mailapi's /healthz here NOOP'd the write IMAP connection, and
    under Gmail's per-command throttle (~10s/command, measured live 2026-08-31) that answer took
    10-20s — longer than this container's compose healthcheck timeout, so mailview flapped
    unhealthy exactly when Gmail was slow, which is when the operator most needs the UI to stay up.
    /connections is IMAP-free (a vault listing, ~ms) and still proves the upstream hop works; the
    account's own health remains mailapi's /healthz+/readyz job."""
    r = _HTTP.get(GI + "/connections", timeout=8)
    r.raise_for_status()
    return jsonify({"status": "ok"})
