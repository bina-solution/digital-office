#!/usr/bin/env python3
"""inbox — the Gmail IMAP/SMTP BACKEND, as a connection-scoped adapter.

This module used to BE the service: a Flask app whose account came from env at import time, picked
over local_app.py by GMAIL_IMAP_MODE at process start. That made a RUNTIME fact (which account the
operator selected) a BUILD-TIME switch. It is now a backend class: service.py owns the routes and
asks adapters.resolve_active() which backend answers each request, so one process serves every
protocol. The HTTP contract is unchanged — the route bodies moved here verbatim as methods and
return exactly the same payloads (n8n's gmailApiImap01 must keep working untouched).

Two auth methods share this ONE IMAP code path; only login() differs:
  * password — a Gmail app-password (protocol mail_imap_app_password, incl. the GMAIL_IMAP_* env
    bootstrap account)
  * xoauth2  — an OAuth access token (protocol mail_gmail_oauth); the token comes from a callable so
    a refresh mid-life is invisible to everything below.

Canonical contract (shared with "gmail api - oauth" via the "gmail api" router):
  * message identifier = **Gmail hex id** (same value the OAuth Gmail node returns as $json.id).
    IMAP keys natively by uid; we map id<->uid via the X-GM-MSGID search extension in [Gmail]/All Mail
    (id == format(int(X-GM-MSGID),'x')). Endpoints accept `id`/`ids` OR `uid`/`uids`.
  * labels = **names** (account-stable across tenants, unlike Gmail's per-account Label_NN ids).
    System labels (INBOX/SENT/...) are mapped to the IMAP \\Flag form for X-GM-LABELS.

Uses imapclient (handles modified-UTF-7 Hebrew label folders + Gmail X-GM-LABELS + gmail_search/X-GM-RAW).
Per-backend: ONE IMAP connection per mailbox (owner rule), guarded by one re-entrant lock, with
auto-reconnect on error. Read-only by default; the only writes are explicit label add/remove + append.

LATENCY (RELEASE-DECISIONS N11, backend half):
  * a checkout NOOPs the connection only after it has been idle for IDLE_NOOP_S (see there);
  * the INTERACTIVE reads (search, thread, labels, `meta=true` message) wait at most LOCK_WAIT_S
    for the lock and then answer 503 "mailbox busy" naming what holds it, so a reader is never
    queued past the console's 40 s proxy budget behind a 300 s sync fetch. The full-body fetch the
    sync deliveries use waits as long as it takes — N deliveries queuing on the one connection is
    the designed behaviour (gmailApiImap01 `http:get`, timeout 300 s), and a delivery must land;
  * /healthz and /readyz take the lock non-blocking and report a busy mailbox as healthy;
  * a body cache on /data (bodycache.py) is filled by every full fetch and thread read and served
    by the `meta=true` read, so an INDOX-touched message opens without IMAP.
"""
import os, ssl, smtplib, base64, threading, time, email, imaplib, functools, quopri, codecs
from email.message import EmailMessage
from email.header import decode_header, make_header
from email.utils import format_datetime, formatdate, make_msgid, parseaddr
from imapclient import IMAPClient

# Label management lives entirely in settings (tag_rules) — workflows resolve KEY->name via
# settings.gmail.labels and pass NAMES here. This service is a dumb executor: it does NOT resolve
# Label_NN ids (that responsibility moved out; account-specific ids, if ever needed for the OAuth
# backend, are cached by gmailApiRouter into tag_rules.label_id). Only system-label \Flag mapping
# remains below (required by IMAP X-GM-LABELS for INBOX/SENT/etc.).

# Defaults for the env-configured (bootstrap) account. NOT read at import as hard requirements any
# more: this module is imported in EVERY mode now, so a missing GMAIL_IMAP_USER must not KeyError a
# local-only deployment at startup — it simply means no env account exists (see cc.env_instance()).
IMAP_HOST = os.environ.get("GMAIL_IMAP_HOST", "imap.gmail.com")
IMAP_PORT = int(os.environ.get("GMAIL_IMAP_PORT", "993"))
SMTP_HOST = os.environ.get("GMAIL_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("GMAIL_SMTP_PORT", "465"))
ALL_MAIL = "[Gmail]/All Mail"

import contextlib, re as _re, collections
from flask import g as _g, has_request_context, request as _request

import bodycache

# ── IMAP command instrumentation ───────────────────────────────────────────────
# Gmail OVERQUOTA = too many IMAP commands / bandwidth per window. We had ZERO visibility into how many
# commands each request/pipeline issues. Count every command (by type) globally + per-request so we can
# find the offenders (per-label STORE storms, id->uid SEARCH per op, redundant SELECT/noop, retry loops).
# Process-wide on purpose: the quota that matters is Gmail's per-account one, and /stats reports the
# whole process — these counters are NOT per-backend state.
_cmd_stats = collections.Counter()
_ep_cmds = collections.Counter()    # total commands attributed to each endpoint
_ep_hits = collections.Counter()    # request count per endpoint
_START = time.time()
_COUNTED = ("noop", "login", "oauth2_login", "select_folder", "search", "gmail_search", "fetch",
            "add_gmail_labels", "remove_gmail_labels", "append", "create_folder",
            "delete_folder", "list_folders", "copy", "expunge", "folder_status")

# GMAIL_IMAP_READ_POOL / READ_POOL_SIZE retired 2026-09-01: there is no read pool any more. One
# account holds exactly ONE IMAP connection (see GmailBackend._read_conn / _conn). The env var, if
# still set in a .env, is simply ignored.
# Per-checkout liveness noop is only needed to catch conns Gmail dropped while IDLE (~30min). Under
# Gmail command-throttling a noop costs as much as the real op (≈6.5s each, measured) so doing it on
# EVERY checkout doubles per-op latency AND adds to the command volume that triggers the throttle.
# Only noop when the conn has actually been idle beyond this window (IMPLEMENTED in `_conn` as of
# N11 — this comment described it for weeks while every checkout still nooped, RELEASE-DECISIONS
# §2.7). Every successful command re-stamps `_last_ok` (see `_instrument`); a command that FAILS
# clears it, so the next checkout noops and reconnects and @quota_retry's retry lands on a live
# socket instead of the dead one.
IDLE_NOOP_S = int(os.environ.get("GMAIL_IMAP_IDLE_NOOP_S", "240"))
# How long an INTERACTIVE read waits for the one connection before answering 503 "mailbox busy".
# 30 s sits under the console's 40 s proxy budget with margin for the op itself. `max_wait_s` on
# the request overrides it per call (0 = wait as long as it takes). The full-body fetch, label
# writes and append never use it by default — see the module docstring.
LOCK_WAIT_S = float(os.environ.get("GMAIL_IMAP_LOCK_WAIT_S", "30"))
# When a `meta=true` read is served from the body cache, the live labels are refreshed only if the
# connection frees up within this many seconds; otherwise the labels seen at cache time are
# returned, flagged `labels_live: false`. Small on purpose: the point of the cache is an open that
# does not queue behind IMAP.
CACHE_LABELS_WAIT_S = float(os.environ.get("GMAIL_IMAP_CACHE_LABELS_WAIT_S", "2"))
_DEFAULT_WAIT = object()      # sentinel: "the module-level LOCK_WAIT_S, read at call time"


def _wait_for(params, default):
    """The lock wait a request asked for: `max_wait_s` absent -> `default`; 0 or negative -> wait
    forever (None); positive -> that many seconds. `params` is a body dict or the query args."""
    v = params.get("max_wait_s") if params is not None else None
    if v in (None, ""):
        return default
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    return None if v <= 0 else v


def _op_label(op):
    """What a busy mailbox is reported as doing: the request that holds it, when there is one."""
    try:
        if has_request_context():
            return "%s %s [%s]" % (_request.method, _request.path, op)
    except Exception:
        pass
    return op


class MailboxBusy(Exception):
    """The mailbox's one IMAP connection stayed busy for the whole bounded wait. service.py turns
    this into 503 {"error": "mailbox busy", "busy_with": ...} — an answer the client can show
    ("the mailbox is busy with a sync fetch, try again") instead of a proxy timeout."""

    def __init__(self, user, busy, waited):
        op, since = busy if busy else ("unknown", None)
        self.user, self.busy_with, self.waited = user, op, waited
        self.busy_for = int(time.time() - since) if since else None
        super().__init__("mailbox busy: %s has held the IMAP connection of %s for %ss (waited %ss)"
                         % (op, user, self.busy_for, waited))

    def payload(self):
        return {"error": "mailbox busy", "busy_with": self.busy_with, "busy_for_s": self.busy_for,
                "waited_s": self.waited, "mailbox": self.user}


def _instrument(c):
    """Wrap an IMAPClient instance so every IMAP command is counted globally + into the active
    request, and every SUCCESSFUL command re-stamps `_last_ok` — the liveness proof `_conn` reads
    instead of issuing a NOOP on every checkout (IDLE_NOOP_S)."""
    for name in _COUNTED:
        orig = getattr(c, name, None)
        if orig is None or getattr(orig, "_counted", False):
            continue
        def mk(nm, fn):
            def w(*a, **k):
                _cmd_stats[nm] += 1
                try:
                    _g._cmds = getattr(_g, "_cmds", 0) + 1
                except Exception:
                    pass
                r = fn(*a, **k)
                c._last_ok = time.time()
                return r
            w._counted = True
            return w
        setattr(c, name, mk(name, orig))
    return c


def quota_retry(view):
    """Make an op resilient to transient Gmail failures: (a) an OVERQUOTA SELECT aborts (and kills)
    the connection; (b) Gmail drops the socket with EOF under an append/op burst (IMAP4.abort / OSError).
    Either way the conn is replaced (see _read_conn) and the whole op is retried with backoff so a
    transient blip self-heals instead of surfacing as a 500. Hard/sustained failures still 500."""
    @functools.wraps(view)
    def wrapped(*a, **k):
        delays = [2, 5, 10, 20]
        for i in range(len(delays) + 1):
            try:
                return view(*a, **k)
            except (imaplib.IMAP4.abort, imaplib.IMAP4.error, OSError) as e:
                # retry transient socket aborts/EOF (non-OVERQUOTA too) and OVERQUOTA blips
                transient = isinstance(e, (imaplib.IMAP4.abort, OSError)) or "OVERQUOTA" in str(e).upper()
                if transient and i < len(delays):
                    time.sleep(delays[i])
                    continue
                raise
    return wrapped


# Gmail system labels: Gmail-API / workflows use UPPER ids (INBOX, SENT, ...); IMAP X-GM-LABELS
# uses the \\Flag form. Map so canonical name-based label ops work for system labels too.
_SYS_LABELS = {
    "INBOX": "\\Inbox", "SENT": "\\Sent", "IMPORTANT": "\\Important",
    "STARRED": "\\Starred", "TRASH": "\\Trash", "DRAFT": "\\Draft",
    "SPAM": "\\Junk", "UNREAD": "\\Unread",
}


def _imap_label(x):
    # Dumb: names pass through; only system names map to their IMAP \\Flag form for X-GM-LABELS.
    return _SYS_LABELS.get(x, x)


def _already_exists(e):
    """Is this IMAP CREATE failure just 'the folder is already there'?

    MEASURED 2026-08-06: the guard here used to test `"already exists" in str(e).lower()`, and Gmail
    IMAP does not say that. It says:

        create failed: [ALREADYEXISTS] Duplicate folder name sv3s_pb_failed (Failure) [THROTTLED]

    — no space in ALREADYEXISTS, and the human half reads "Duplicate folder name". So the guard never
    matched, the exception propagated, and Flask answered POST /labels/create with a bare 500 HTML
    page. That produced 36 n8n executions in `gmail api` + `gmail api - imap smtp` failing on
    a label that already existed, which is the definition of an idempotent no-op. Match on the
    RESPONSE CODE first (that is the part the RFC pins), the prose second.
    """
    s = str(e).lower()
    return ("alreadyexists" in s.replace(" ", "")
            or "already exists" in s
            or "duplicate folder" in s
            or "duplicate mailbox" in s)


def _labels_from(b):
    """Accept labels|label (names) OR labelIds (Gmail short ids); normalize all to IMAP labels."""
    src = b.get("labels") or b.get("labelIds") or ([b["label"]] if b.get("label") else [])
    # Guard: a caller passing a single name as a bare string (e.g. "לטיפול") must NOT be iterated
    # char-by-char — that fragments one Hebrew label into one label per letter (א ה ו …). Wrap it.
    if isinstance(src, str):
        src = [src]
    return [_imap_label(x) for x in src if x is not None and str(x).strip() != ""]


# ── label vocabulary: KEY (rule identifier) vs NAME (what Gmail calls the label) ───────────────
#
# THE MOST EXPENSIVE FAILURE CLASS THIS SERVICE HAS, because its symptom is a 200 with `total: 0`
# — indistinguishable from the honest answer "this pipe is drained". A search that CANNOT match by
# construction must never be reported as a search that found nothing.
#
# MEASURED live against this client's Gmail, 2026-08-10, folder `[Gmail]/All Mail`, one connection,
# minutes apart:
#
#   label:SYNCED_DOC                       ->        0   ← tag-rule KEY, not a label name
#   label:IN_PROGRESS                      ->        0
#   label:SYNCED_BS                        ->        0
#   label:DOC_TO_SYNC                      ->        0
#   label:"אינדוקס - מסמכים כללי - טופל"    ->        0   ← the CORRECT name, quoted. still zero.
#   label:אינדוקס---מסמכים-כללי---טופל      ->       70   ← same label, spaces hyphenized
#   label:אוטומציה-שמירת-מסמכים-טופל         ->   15,575   ← the name the label engine actually stamps
#
# Two independent faults stack, and each one alone is enough to produce a believable zero:
#
#  (1) KEY vs NAME. `settings.sync_registry` stores KEYs (`{"synced": "SYNCED_DOC"}`); what is on
#      the message is the rule's LABEL. Every caller was expected to join the two itself. The ones
#      that forget do not fail — they get 0, and 0 reads as "done".
#
#  (2) X-GM-RAW MATCHES ONLY THE HYPHENIZED FORM. Gmail's `label:` operator matches a name with its
#      spaces replaced by '-', and QUOTING DOES NOT RESCUE IT over this transport — proven above:
#      the quoted full name returned 0 while the same label hyphenized returned 70. Quoting is not
#      the problem (the hyphenized name IN QUOTES also returns 70); the spaces are. Callers were
#      each expected to remember `.replace(/ /g, '-')`, and a name that also carries a stray
#      trailing space (this deployment has one: SUPPLIER_MAIL = "מייל-מספק ") hyphenizes into
#      `מייל-מספק-`, which matches nothing at all.
#
# Both are handled HERE, in the one place every caller passes through, instead of in each caller —
# and anything still unresolvable is refused rather than answered with a zero. See
# `GmailBackend.search`.

# Gmail search tokens that name something other than a user label. They never appear in
# `LIST` output, so they must be exempt from the existence check or the mail UI's own views
# (`label:STARRED`, `-label:INBOX`, `label:SENT`) would be refused.
_GMAIL_PSEUDO_LABELS = {
    "INBOX", "SENT", "DRAFT", "DRAFTS", "SPAM", "TRASH", "STARRED", "IMPORTANT",
    "UNREAD", "READ", "CHAT", "CHATS", "ALL", "ANYWHERE", "MUTED", "PERSONAL",
    "SOCIAL", "PROMOTIONS", "UPDATES", "FORUMS", "RESERVATIONS", "PURCHASES",
}

# One `label:`/`-label:` term. The value is either a quoted run or an unquoted run of
# non-space, non-paren characters (Gmail's own tokenisation for this operator).
_LABEL_TERM_RE = _re.compile(r'(?P<neg>-?)label:(?P<val>"[^"]*"|[^\s()]+)', _re.UNICODE)


def gmail_label_token(name):
    """The ONE form `X-GM-RAW label:` matches — trimmed, then spaces -> '-'.

    `.strip()` is load-bearing and is not tidying: a rule whose LABEL carries a trailing space
    hyphenizes into a token with a trailing '-' that matches no label on any mailbox."""
    return str(name or "").strip().replace(" ", "-")


def rewrite_label_terms(query, key_to_name, name_by_token):
    """Rewrite every label term in a Gmail query into the form Gmail can actually match.

    `key_to_name`   — rule KEY -> label NAME (the organizer/tag-rule vocabulary).
    `name_by_token` — hyphenized token -> real label name, i.e. what the mailbox actually has.

    Returns ``(query, terms)``. Each term is
    ``{"raw", "negated", "resolved", "token", "status"}`` with status one of:
      ``matched``   — names a label that exists on the mailbox (possibly via its KEY)
      ``system``    — a Gmail pseudo-label (INBOX/STARRED/...), passed through untouched
      ``unknown``   — resolves to nothing that exists; the caller must be told, not handed a 0

    Pure function on purpose: no IMAP, no I/O, no globals — so the regression guard can drive it
    with a fixture vocabulary and assert the exact pre-fix strings that returned zero."""
    terms = []

    def _sub(m):
        raw = m.group("val")
        neg = m.group("neg")
        quoted = raw.startswith('"') and raw.endswith('"') and len(raw) >= 2
        val = raw[1:-1] if quoted else raw
        rec = {"raw": val, "negated": bool(neg)}
        if val.upper() in _GMAIL_PSEUDO_LABELS:
            rec.update(resolved=val, token=val, status="system")
            terms.append(rec)
            return m.group(0)
        # KEY -> NAME. THE RULE ALWAYS WINS, EVEN WHEN THE RAW KEY IS ALSO A REAL LABEL.
        #
        # An earlier version of this deferred to the literal label whenever one existed, on the
        # reasoning that a caller who types a name means that name and that resolving it away
        # would hide a stray. Measured live, that reasoning was exactly backwards: this mailbox
        # carries a stray label literally named `DOC_LINK_TO_SYNC` (something applied the raw KEY
        # instead of the resolved name — see issues/mail-label-registry-split.yaml) with ONE
        # message on it, while the KEY's real label `לטיפול-אוטומציה-קישור-למסמך` carries 1,917.
        # So `label:DOC_LINK_TO_SYNC` — the exact string the gmail-link registry row stores —
        # answered 1 instead of 1,917: a 0.05%-of-reality number, which is worse than the zero
        # this whole guard exists to abolish, because it looks like a real answer.
        #
        # The stray is not hidden, it is REPORTED: `shadowed_literal_label` on the term says a
        # label literally named after the KEY also exists, so the artefact is louder than before
        # rather than quieter, and nobody has to already suspect it to see it.
        resolved = val
        shadowed = False
        if val in key_to_name:
            resolved = key_to_name[val]
            shadowed = gmail_label_token(val) in name_by_token
        token = gmail_label_token(resolved)
        rec.update(resolved=resolved, token=token,
                   status="matched" if token in name_by_token else "unknown")
        if shadowed:
            rec["shadowed_literal_label"] = val
        terms.append(rec)
        return neg + "label:" + token

    return _LABEL_TERM_RE.sub(_sub, query), terms


def _label_name_by_key(connection_id=None):
    """rule KEY -> label NAME, from the organizer options this service already owns.

    Deliberately the SAME source `/organizer/settings` serves the label engine, so what search
    resolves and what the engine applies cannot drift apart. Imported lazily and failure-tolerant:
    a deployment with no options volume must still be able to search."""
    try:
        import options as _options
        # One rule store for every mailbox (RELEASE-DECISIONS N1): `connection_id` is accepted for
        # the callers that still pass it and changes nothing.
        rules = _options.rules_of(_options.get_defaults())
    except Exception:
        return {}
    out = {}
    for r in rules or []:
        k = (r.get("KEY") or "").strip()
        n = (r.get("LABEL") or "").strip()
        # `-INBOX` (ARCHIVE_PROMO) is a REMOVE directive in the rules grid, not a label name.
        if k and n and not n.startswith("-"):
            out[k] = n
    return out


def decode_part(part):
    """Decode ONE text part to str, tolerating charsets that IANA has and Python does not.

    [g3 2026-08-09] `.decode(part.get_content_charset() or "utf-8", "replace")` raised
    `LookupError: unknown encoding: iso-8859-8-i` on real Hebrew mail and killed the whole
    /message request. The `"replace"` errors-arg does NOT save you: LookupError comes from the
    CODEC LOOKUP, before any byte is decoded, so the error handler never gets a chance.

    `iso-8859-8-i` / `-e` are IANA charset labels for Hebrew that only carry BIDI layout intent
    (implicit / explicit); the octets are plain iso-8859-8. Python's codec registry has no alias
    for them, so strip the suffix. Anything still unknown falls back to utf-8 rather than throwing —
    a mojibake body is recoverable, a 500 on the whole message is not.
    """
    raw = part.get_payload(decode=True) or b""
    cs = (part.get_content_charset() or "utf-8").strip().lower()
    if cs.endswith(("-i", "-e")):
        cs = cs[:-2]
    try:
        codecs.lookup(cs)
    except (LookupError, ValueError):
        cs = "utf-8"
    return raw.decode(cs, "replace")


def _render_message(uid, data, want_att=True):
    """One RFC822 blob -> the message payload both `message()` and `thread()` return.

    Extracted rather than duplicated: this is the shape n8n's gmailApiImap01 `shape:get` reads
    (`attachments` feeds `attachmentsMeta`, which feeds the label engine's rule evaluator), so two
    copies of it drifting apart would break rules silently — the exact failure mode this codebase
    has already paid for once.
    """
    msg = email.message_from_bytes(data[b"RFC822"])
    body_text, body_html, atts = "", "", []
    for part in (msg.walk() if msg.is_multipart() else [msg]):
        ct = part.get_content_type()
        disp = part.get_content_disposition()
        fn = part.get_filename()
        if fn or disp == "attachment":
            try:
                payload = part.get_payload(decode=True) or b""
                a = {"filename": str(make_header(decode_header(fn))) if fn else "attachment",
                     "mimeType": ct, "size": len(payload),
                     "content_id": (part.get("Content-ID") or "").strip("<> ")}
                if want_att:
                    a["data_base64"] = base64.b64encode(payload).decode()
                atts.append(a)
            except Exception:
                pass
        elif ct == "text/plain" and not body_text:
            body_text = decode_part(part)
        elif ct == "text/html" and not body_html:
            body_html = decode_part(part)
    return {
        "uid": int(uid), "id": _gmail_id(data.get(b"X-GM-MSGID")),
        "gm_msgid": str(data.get(b"X-GM-MSGID", "")), "gm_thrid": str(data.get(b"X-GM-THRID", "")),
        "threadId": _gmail_id(data.get(b"X-GM-THRID")),
        "from": _hdr(msg, "From"), "to": _hdr(msg, "To"),
        "subject": _hdr(msg, "Subject"), "date": _date_of(msg, data),
        "labels": _decode_labels(data.get(b"X-GM-LABELS")),
        "body_text": body_text, "body_html": body_html, "attachments": atts,
    }


def _gmail_id(gm_msgid):
    """Gmail hex message-id from the numeric X-GM-MSGID (matches Gmail API $json.id)."""
    return format(int(gm_msgid), "x") if gm_msgid else ""


def _hdr(msg, h):
    v = msg.get(h, "")
    try:
        # not make_header(): raw 8-bit headers come back as ('unknown-8bit', bytes)
        # chunks and make_header degrades every byte to U+FFFD — decode as UTF-8.
        parts = []
        for chunk, enc in decode_header(v):
            if isinstance(chunk, bytes):
                parts.append(chunk.decode(enc if enc and enc != "unknown-8bit" else "utf-8", "replace"))
            else:
                parts.append(chunk)
        return "".join(parts)
    except Exception:
        return v


def _decode_labels(raw):
    from imapclient import imap_utf7
    out = []
    for l in (raw or []):
        if isinstance(l, bytes):
            l = l.decode("utf-8", "replace")
        l = str(l).strip('"')
        if "&" in l:                     # X-GM-LABELS names arrive modified-UTF-7 encoded
            try:
                l = imap_utf7.decode(l.encode("ascii"))
            except Exception:
                pass
        out.append(l)
    return out


# ── the time-window primitive (`since_ts`) ────────────────────────────────────
#
# ONE OWNER for "show me only mail at or after instant T", used by BOTH backends (local_app imports
# the two helpers below) so the deterministic local stand-in cannot drift from the real Gmail path.
#
# THE CONTRACT IS AN ABSOLUTE INSTANT, DELIBERATELY — `since_ts` is epoch seconds (UTC), never a
# date, never a "window name", never a timezone. Calendar vocabulary ("today", "this month") and the
# USER's timezone are the CLIENT's business (mailview's /api/messages computes them from the
# browser's own UTC offset). This layer owns only the IMAP mechanics. That split is the whole reason
# the classic timezone bug cannot occur here: there is no place in this file where a day boundary is
# guessed, and the mail container runs UTC while this client is Asia/Jerusalem (UTC+3), so any
# server-side notion of "today" would have been wrong for three hours out of every day.
#
# ── WHY TWO STAGES, AND WHY THE SECOND ONE IS NOT REMOVABLE ──
#
# IMAP SEARCH's date keys (SINCE / BEFORE / SENTSINCE) have DATE GRANULARITY ONLY — RFC 3501 §6.4.4:
# SINCE matches "messages whose internal date ... is within or later than the specified date", and
# the comparison explicitly DISREGARDS TIME AND TIMEZONE. There is no wire syntax for "since 14:30".
# So a 30-minute or 1-hour window CANNOT be expressed to the server, at all, by any argument. It is
# not a limitation of this code and it is not fixable by sending a cleverer criterion.
#
#   Stage 1 (server, cheap, does the real work): AND `SINCE <date>` into the criteria. This is what
#   makes a window fast — the server never materialises the other 80,000 UIDs.
#   Stage 2 (client, exact): compare each returned message's INTERNALDATE against `since_ts`. This
#   happens INSIDE the summary FETCH that `search()` already performs, never as a pass of its own —
#   see the measured note at that site for what a separate pass cost.
#
# ⚠ TO WHOEVER "OPTIMISES" THIS NEXT: deleting stage 2 makes 30m and 1h silently mean "today", and
# deleting the -1 day widening in stage 1 makes windows silently DROP mail near midnight. Both fail
# by returning a plausible, wrong list rather than by erroring. Neither is dead code.
#
# WHY THE WIDENING IS EXACTLY ONE DAY: stage 1's date is computed from `since_ts` in UTC, but the
# server compares against the date it stored, in whatever timezone that message carried. Two clocks
# naming the same instant can disagree about the calendar date by at most one day (real UTC offsets
# span -12..+14). Subtracting one day therefore guarantees ZERO false negatives — the set the server
# returns is always a superset of the true window — and stage 2 removes the false positives it let
# in. Widening is the safe direction: a false positive is corrected below, a false negative is mail
# the user never learns exists.
_IMAP_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def imap_since_date(ts):
    """The `SINCE` argument for a window starting at epoch `ts`, widened one day (see above).

    Formatted from an explicit month table rather than strftime("%d-%b-%Y") ON PURPOSE: %b is
    LOCALE-DEPENDENT, and this string goes on the wire as an IMAP date, which RFC 3501 defines with
    English month abbreviations only. A container that ever gets a non-C LC_TIME would otherwise emit
    something the server rejects — a locale-dependent bug in a protocol constant, found only in
    production and only in some deployments."""
    tm = time.gmtime(ts - 86400)
    return "%02d-%s-%04d" % (tm.tm_mday, _IMAP_MONTHS[tm.tm_mon - 1], tm.tm_year)


# A NOTE ON `.timestamp()`, which stage 2 relies on in both backends: it is correct for BOTH of
# imapclient's INTERNALDATE shapes, and that is not luck. With `normalise_times=True` (its default,
# and what this client uses) imapclient returns a NAIVE datetime already converted to this process's
# local timezone, and naive `.timestamp()` interprets its argument as local time; with
# `normalise_times=False` it returns an AWARE datetime and `.timestamp()` honours the offset. So the
# comparison does not depend on the container happening to run UTC — exactly the kind of ambient
# assumption that survives every test and then breaks on one host.


def _date_of(msg, data):
    """Date header, falling back to IMAP INTERNALDATE — injected mail can be dateless."""
    v = _hdr(msg, "Date")
    if v:
        return v
    dt = data.get(b"INTERNALDATE")
    return format_datetime(dt) if dt else ""


def _msg_summary(uid, data):
    raw = data.get(b"RFC822") or data.get(b"BODY[]") or b""
    msg = email.message_from_bytes(raw) if raw else email.message_from_bytes(
        data.get(b"BODY[HEADER]", b""))
    # search() fetches only headers (+ BODYSTRUCTURE, see below) — never RFC822/BODY[] — so `msg`
    # above is headers-only and msg.is_multipart() is always False, which used to make hasAttachment
    # unconditionally False regardless of the real message. BODYSTRUCTURE carries attachment presence
    # (filename/disposition) without downloading the body, so prefer it; only fall back to the
    # full-body walk for callers that DID fetch RFC822/BODY[] (there are none today, but the fallback
    # keeps this function correct if one is added).
    bs = data.get(b"BODYSTRUCTURE")
    if bs:
        has_att = any(leaf["is_att"] for leaf in _bs_leaves(bs))
    else:
        has_att = any(
            (p.get_filename() or (p.get_content_disposition() == "attachment"))
            for p in (msg.walk() if msg.is_multipart() else [])
        )
    return {
        "uid": int(uid),
        "id": _gmail_id(data.get(b"X-GM-MSGID")),
        "gm_msgid": str(data.get(b"X-GM-MSGID", "")),
        "gm_thrid": str(data.get(b"X-GM-THRID", "")),
        "threadId": _gmail_id(data.get(b"X-GM-THRID")),
        "from": _hdr(msg, "From"),
        "to": _hdr(msg, "To"),
        "subject": _hdr(msg, "Subject"),
        "date": _date_of(msg, data),
        "labels": _decode_labels(data.get(b"X-GM-LABELS")),
        "hasAttachment": has_att,
    }


def _bs_leaves(bs, prefix=""):
    """Walk an IMAP BODYSTRUCTURE (imapclient tuple) into leaf parts.
    Returns list of {num,type,subtype,enc,charset,size,filename,is_att}. `size` is the *decoded*
    byte estimate (base64 → *3/4) so it matches the full-fetch binary fileSize the Label Engine scores on.
    Inclusion mirrors the full /message walk: a leaf is an attachment iff it has a filename or
    disposition=='attachment' (inline-without-filename parts are ignored, same as the full path)."""
    leaves = []
    # multipart: bs[0] is a sequence of sub-structures, bs[1] is the subtype
    if bs and not isinstance(bs[0], (bytes, bytearray)):
        for i, sub in enumerate(bs[0], 1):
            if isinstance(sub, (list, tuple)):
                leaves += _bs_leaves(sub, f"{prefix}{i}.")
        return leaves

    def _dec(x):
        """Always returns a str — every caller immediately does .lower()/.upper() on the result.

        A real client mailbox contains messages whose BODYSTRUCTURE nests a list where the spec
        suggests an atom (e.g. bs[8][0], the content-disposition, arriving as a tuple). Returning
        that value unchanged made `.lower()` raise AttributeError, which 500'd the WHOLE search
        response — one malformed message taking out a 300-message page. That was survivable while
        _bs_leaves only ran on the single-message meta path; it became load-bearing the moment
        search started calling it per message to answer hasAttachment.
        """
        if isinstance(x, (bytes, bytearray)):
            return x.decode("ascii", "replace")
        if isinstance(x, str):
            return x
        if isinstance(x, (list, tuple)):
            return _dec(x[0]) if x else ""
        return "" if x is None else str(x)

    def _kv(seq):
        d = {}
        if isinstance(seq, (list, tuple)):
            for k in range(0, len(seq) - 1, 2):
                key = seq[k]
                if isinstance(key, (bytes, bytearray)):
                    d[key.decode("ascii", "replace").upper()] = seq[k + 1]
        return d

    typ = _dec(bs[0]).lower()
    sub = _dec(bs[1]).lower() if len(bs) > 1 else ""
    pp = _kv(bs[2] if len(bs) > 2 else None)
    charset = _dec(pp.get("CHARSET")) if pp.get("CHARSET") else ""
    enc = _dec(bs[5]).upper() if len(bs) > 5 else ""
    size = bs[6] if len(bs) > 6 and isinstance(bs[6], int) else 0
    fn_raw = pp.get("NAME")
    disp = None
    if len(bs) > 8 and isinstance(bs[8], (list, tuple)) and bs[8]:
        disp = _dec(bs[8][0]).lower()
        dp = _kv(bs[8][1] if len(bs[8]) > 1 else None)
        if dp.get("FILENAME") is not None:
            fn_raw = dp.get("FILENAME")
    filename = ""
    if fn_raw is not None:
        raw = fn_raw.decode("utf-8", "replace") if isinstance(fn_raw, (bytes, bytearray)) else str(fn_raw)
        try:
            filename = str(make_header(decode_header(raw)))
        except Exception:
            filename = raw
    num = prefix[:-1] if prefix else "1"
    # base64 BODYSTRUCTURE size is the *encoded* octet count incl. 76-char-line CRLFs; decoded ≈ ×0.7308
    # (3/4 minus line-wrap overhead) → matches the full-fetch decoded fileSize the Label Engine scores on.
    dsize = int(size * 0.7308) if enc == "BASE64" else size
    leaves.append({"num": num, "type": typ, "subtype": sub, "enc": enc, "charset": charset,
                   "size": dsize, "filename": filename, "is_att": bool(filename) or disp == "attachment"})
    return leaves


class GmailBackend:
    """One Gmail account, ONE IMAP connection. Everything that used to be a module global (the
    connection, the id->uid cache) is per-instance state, because those are per-ACCOUNT facts: a
    cached uid or a logged-in socket from account A is meaningless for B.

    probe_fail_code is 503: a Gmail account that cannot be reached is 'upstream unavailable', and the
    compose healthcheck keys on the status code — /readyz has answered 503 in gmail mode since it was
    written, so the code belongs to the adapter and must not drift when selection moves it around.
    """

    protocol = "mail_imap_app_password"
    probe_fail_code = 503

    def __init__(self, user, password=None, token_provider=None,
                 imap_host=None, imap_port=None, smtp_host=None, smtp_port=None):
        self.user = user
        # Gmail prints app-passwords in 4-char groups; users paste them that way.
        self.password = (password or "").replace(" ", "")
        # A CALLABLE, not a token: an access token expires mid-process, and every conn we open later
        # (pool refills, reconnects after an abort) must mint a fresh one without re-resolving.
        self.token_provider = token_provider
        self.imap_host = imap_host or IMAP_HOST
        self.imap_port = int(imap_port or IMAP_PORT)
        self.smtp_host = smtp_host or SMTP_HOST
        self.smtp_port = int(smtp_port or SMTP_PORT)

        # ONE connection per account, full stop (owner rule 2026-09-01). Reads and writes share
        # the SAME socket, serialized by a single re-entrant lock — mirroring LocalBackend
        # (local_app.py). The old fixed-size read pool opened READ_POOL_SIZE+1 sockets per
        # instance, and stale instances (fingerprint churn, container recreate) left their sockets
        # ESTABLISHED, so one Gmail account accumulated dozens of connections against its ~15 cap.
        # A single lock-guarded connection makes that impossible: an account can never hold more
        # than one live IMAP socket, and there is nothing to leak between generations.
        # RLock (not Lock) so a read that internally resolves labels — or a write that reuses the
        # read path — re-enters on the same thread without deadlocking.
        self._lock = threading.RLock()     # serializes EVERY IMAP op on the one connection
        self._client = None                # the one and only connection (read + write)
        self._busy_with = None             # (op label, since) while the lock is held — for 503s
        self._depth = 0                    # RLock re-entry depth, so busy_with names the OUTER op
        self._uid_cache = {}               # gmail hex id -> uid in [Gmail]/All Mail
        self._label_idx = None             # (taken_at, {hyphenized token -> real label name})
        self._label_idx_lock = threading.Lock()
        self._cache = bodycache.shared()   # parsed messages on /data, keyed by account + gmail id

    # ── connections ────────────────────────────────────────────────────────────
    def _login(self, c):
        if self.token_provider is not None:
            c.oauth2_login(self.user, self.token_provider())
        else:
            c.login(self.user, self.password)

    def _make_conn(self):
        c = IMAPClient(self.imap_host, port=self.imap_port, ssl=True, timeout=30)
        self._login(c)
        _cmd_stats["login"] += 1          # login itself is several protocol commands; track reconnect churn
        c = _instrument(c)
        c._last_ok = time.time()          # fresh conn is live; skip the next checkout's liveness noop
        return c

    @contextlib.contextmanager
    def _read_conn(self, op="op", wait=_DEFAULT_WAIT):
        """Yield THE connection for an op. There is no pool: reads and writes share the single
        `self._client` socket, serialized by `self._lock` (an RLock).

        `wait` bounds the time spent waiting for that lock: the module's LOCK_WAIT_S by default,
        a number of seconds, or None to wait as long as it takes. When the bound expires the op
        raises MailboxBusy naming the op that holds the connection and for how long — the reader
        gets a 503 it can show instead of queuing past its proxy's budget. Writes and the
        deliveries' full fetch pass None: a delivery must land, and N of them queuing on the one
        connection is the designed shape (gmailApiImap01 `http:get`, 300 s).

        Reads never nest two connections (search resolves its label vocabulary BEFORE entering this
        block), so serializing them on one lock cannot self-deadlock; the RLock additionally makes a
        same-thread re-entry safe, and `_depth` keeps `busy_with` naming the outermost op.

        A command that raises inside the block clears the connection's `_last_ok`, so the next
        checkout NOOPs it and reconnects if it is dead — that is what lets `_conn` skip the NOOP on
        every other checkout without @quota_retry re-using a dead socket."""
        if wait is _DEFAULT_WAIT:
            wait = LOCK_WAIT_S
        if wait is None:
            self._lock.acquire()
        elif not self._lock.acquire(timeout=wait):
            raise MailboxBusy(self.user, self._busy_with, wait)
        c = None
        try:
            self._depth += 1
            if self._depth == 1:
                self._busy_with = (_op_label(op), time.time())
            c = self._conn()
            yield c
        except BaseException:
            if c is not None:
                c._last_ok = 0.0
            raise
        finally:
            self._depth -= 1
            if self._depth == 0:
                self._busy_with = None
            self._lock.release()

    def _busy_payload(self):
        b = self._busy_with
        if not b:
            return {}
        return {"busy_with": b[0], "busy_for_s": int(time.time() - b[1])}

    def _conn(self):
        """Return the one live IMAPClient, reconnecting if the previous socket died. Caller holds
        self._lock (RLock) — every read and write path acquires it, so there is exactly one socket
        for this account at any time.

        IDLE_NOOP_S, honoured: a connection that completed a command less than IDLE_NOOP_S ago is
        live by construction and is handed back without a NOOP. Only one that has sat idle longer
        (Gmail drops those after ~30 min) is NOOPed, and reconnected if that fails."""
        c = self._client
        if c is not None:
            if time.time() - getattr(c, "_last_ok", 0.0) < IDLE_NOOP_S:
                return c
            try:
                c.noop()
                c._last_ok = time.time()
                return c
            except Exception:
                try:
                    c.logout()
                except Exception:
                    pass
                self._client = None
        # _make_conn logs in, instruments the command counters and stamps _last_ok.
        self._client = self._make_conn()
        return self._client

    def close(self):
        """LOGOUT the one socket this backend owns. Called on connection re-select / secret rotation
        (adapters.resolve_active, forget) AND on process shutdown (adapters.close_all via the atexit
        hook in entry.py) so a replaced or retired account does not leave a server-side Gmail session
        counting against the ~15/account cap."""
        with self._lock:
            c, self._client = self._client, None
        try:
            if c is not None:
                c.logout()
        except Exception:
            pass

    def _select(self, c, folder, readonly=False):
        """SELECT a folder, but SKIP if this connection is already on it — Gmail counts every SELECT
        against its per-account command/bandwidth quota, and SELECT [Gmail]/All Mail is heavy. Repeated
        redundant SELECTs (one per request, per label-add) were the root cause of [OVERQUOTA] flakiness.
        Always selects read-write so one cached SELECT serves both search and store on the same folder."""
        if getattr(c, "_sel_folder", None) == folder:
            return
        c.select_folder(folder)
        c._sel_folder = folder

    def _uids_for_ids(self, c, ids):
        """Resolve Gmail hex message-ids -> IMAP uids via X-GM-MSGID. Cached: the same id is hit many times
        in one pipeline (the engine issues K addLabels per email = K identical id->uid searches) and across
        runs — caching turns those into 0 SEARCH commands, a major OVERQUOTA reducer. Caller must have ALL_MAIL
        selected. Stale cache entries self-heal: a missing message fails downstream and is re-resolved next call."""
        uids, miss = [], []
        for gid in ids:
            u = self._uid_cache.get(str(gid))
            if u:
                uids.append(u)
            else:
                miss.append(str(gid))
        for gid in miss:
            try:
                r = list(c.search([b"X-GM-MSGID", int(gid, 16)]))
                if r:
                    self._uid_cache[gid] = r[0]
                    uids.append(r[0])
            except Exception:
                pass
        return uids

    # ── health ─────────────────────────────────────────────────────────────────
    def healthz(self):
        # Liveness check that must NOT contend with the lock (held for the whole of a 300 s sync
        # fetch) — otherwise heavy load makes the container flap to "unhealthy" even though it is
        # serving fine. Try the lock non-blocking: if an op is in progress the service is alive AND
        # busy → healthy, and the answer names what it is busy with. Only touch IMAP when the lock
        # is free — and then through `_conn`, which NOOPs only a connection idle beyond IDLE_NOOP_S,
        # so two health routes polling every 30 s cost the account nothing while it is working.
        if self._lock.acquire(blocking=False):
            try:
                self._conn()
                return {"status": "ok", "user": self.user}, 200
            except Exception as e:
                return {"status": "error", "error": f"{type(e).__name__}: {e}"}, 500
            finally:
                self._lock.release()
        return {"status": "ok", "user": self.user, "note": "busy (an op holds the connection)",
                **self._busy_payload()}, 200

    def probe(self):
        # Readiness = the one connection can reach the account. Same non-blocking shape as healthz
        # (N11: a probe that queued behind a sync fetch used to hang /readyz, the compose
        # healthcheck and mail01's per-connection probe for minutes): a busy mailbox is a reachable
        # mailbox. A dead account still answers probe_fail_code so the orchestrator restarts the
        # container; the reason carried back is the account's own error.
        if not self._lock.acquire(blocking=False):
            return {"status": "ok", "user": self.user, "note": "busy (an op holds the connection)",
                    **self._busy_payload()}, 200
        try:
            self._conn()
        except Exception as e:
            return {"status": "error", "error": f"{type(e).__name__}: {e}"}, self.probe_fail_code
        finally:
            self._lock.release()
        return {"status": "ok", "user": self.user}, 200

    # ── label vocabulary ───────────────────────────────────────────────────────
    LABEL_INDEX_TTL_S = 60

    def _label_index(self, refresh=False):
        """{hyphenized token -> real label name} for this mailbox, cached for LABEL_INDEX_TTL_S.

        Takes the connection itself (`labels_list` -> LIST). `search` resolves its vocabulary BEFORE
        it opens its own connection, so the LIST never extends the time the lock is held for the
        search, and a busy mailbox surfaces here as the same bounded MailboxBusy the search would
        raise — never as a hang."""
        now = time.time()
        with self._label_idx_lock:
            idx = self._label_idx
            if not refresh and idx is not None and now - idx[0] <= self.LABEL_INDEX_TTL_S:
                return idx[1]
        names = (self.labels_list() or {}).get("labels") or []
        built = {}
        for n in names:
            built[gmail_label_token(n)] = n
        with self._label_idx_lock:
            self._label_idx = (time.time(), built)
        return built

    def stats(self):
        up = max(1.0, time.time() - _START)
        return {
            "uptime_s": round(up),
            "commands_total": sum(_cmd_stats.values()),
            "cmds_per_min": round(sum(_cmd_stats.values()) / (up / 60), 1),
            "by_command": dict(_cmd_stats.most_common()),
            "by_endpoint_cmds": dict(_ep_cmds.most_common()),
            "by_endpoint_hits": dict(_ep_hits.most_common()),
            "avg_cmds_per_hit": {ep: round(_ep_cmds[ep] / _ep_hits[ep], 2) for ep in _ep_hits},
            "body_cache": self._cache.stats(),
            "lock": {"busy": bool(self._busy_with), **self._busy_payload(),
                     "read_wait_s": LOCK_WAIT_S, "idle_noop_s": IDLE_NOOP_S},
        }

    def stats_reset(self):
        _cmd_stats.clear(); _ep_cmds.clear(); _ep_hits.clear()
        return {"ok": True}

    # ── ops ────────────────────────────────────────────────────────────────────
    @quota_retry
    def search(self, b):
        """Body: {folder?:'INBOX', query?:'<gmail search>', criteria?:['UNSEEN',...], limit?:N,
        before_uid?:N (legacy cursor — page of matches strictly BELOW this uid, newest-first; what
        the mail UI's "load older" uses), since_uid?:N (incremental high-water mark — only matches
        with uid > since_uid, returned OLDEST-of-the-new-first)}.
        If query given -> gmail_search (X-GM-RAW). Else criteria (default ['ALL']) on the folder.

        `since_uid` is INDOX's Gmail incremental-sync primitive (ai/context/INDOX-UNIFIED-N8N-SPEC.md
        §3). This backend is IMAP (imapclient) with an app-password/XOAUTH2 login, not the Gmail REST
        API, so a `historyId` is not representable here at all — it is a Gmail-API-only concept. The
        transport's actual equivalent is a UID high-water mark: IMAP UIDs within one UIDVALIDITY
        generation are assigned strictly increasing and never reused, so "UID > last-seen" has exactly
        historyId's property (fetch only what arrived since last time) without needing CONDSTORE/
        MODSEQ (not guaranteed present; UID ordering already is, per RFC 3501 §2.3.1.1). `since_uid` is
        composed into the SEARCH command as an extra ANDed term (IMAP SEARCH implicitly ANDs multiple
        criteria in one round trip) rather than applied as a post-filter, so an incremental pass costs
        exactly one SEARCH + one STATUS command regardless of mailbox size — never a full re-list.

        `uidvalidity`/`uidnext` are ALWAYS returned (one cheap STATUS command, no SELECT required) so
        a caller holding a stored UID cursor can detect the one event that invalidates it — a
        UIDVALIDITY change (mailbox rebuild/migration) — and fall back to a full rescan rather than
        silently trusting a UID space that no longer means what it used to.

        Truncation direction differs by mode because it has to: the legacy (`before_uid`/plain) path
        takes the NEWEST `limit` matches (`uids[-limit:]`) — right for "show me recent mail" browsing,
        where paging older is optional. The `since_uid` path takes the OLDEST `limit` of the NEW
        matches (`uids[:limit]`) with `next_cursor` set to resume from there — because taking the
        newest-first here would silently skip the oldest unseen messages whenever more than `limit`
        arrived in one gap, which is exactly the kind of quiet loss this endpoint exists to prevent.
        A caller must keep calling with `since_uid=next_cursor` while `has_more` is true before
        persisting `next_cursor` as the new steady-state cursor.

        `since_ts` (epoch seconds, UTC) is the optional TIME WINDOW — "only mail at or after this
        instant". It is ANDed into the same SEARCH command as everything else (IMAP SEARCH implicitly
        ANDs its criteria), so a window costs no extra round trip on the search itself and composes
        with `query`/`criteria`/`before_uid` rather than replacing any of them. See `imap_since_date`
        above for the two-stage mechanics and, in particular, for why the exact
        sub-day part CANNOT be pushed to the server. Response shape is unchanged — `total` simply
        means, as it always has, "how many messages matched", which for a windowed call is the exact
        count inside the window.

        `since_ts` IS A VIEW CONCERN AND TOUCHES NO CURSOR. It is deliberately independent of
        `since_uid`: the incremental-sync callers (mailDiscovery01, syncV3Unit0001) pass `since_uid`
        and never a window, and the UI passes a window and never `since_uid`. The two compose
        correctly if anyone ever mixes them (both are just ANDed terms), but a window must never be
        introduced into a SYNC call — hiding messages from a pass whose job is to advance a
        high-water mark would let the cursor skip them permanently.

        `label:` TERMS ARE RESOLVED AND VERIFIED BEFORE THE SEARCH RUNS, and a term that names
        nothing on this mailbox is a 422 — never a 200 with `total: 0`. See the vocabulary note
        above `rewrite_label_terms` for the measurements; the short version is that BOTH
        `label:SYNCED_DOC` (a rule KEY, not a name) and `label:"<name with spaces>"` (the right
        name, unhyphenized) returned a clean zero on this account while 15,575 messages carried the
        label. Zero is also what a drained pipe returns, so every "this pipe is empty" conclusion
        drawn from this endpoint was unfalsifiable. It is now: a zero from here means the search ran
        against a label that demonstrably exists. Every response carries `label_terms` showing what
        each term was resolved to and whether it matched, so the reasoning is auditable after the
        fact rather than only at the moment someone thinks to check.

        `allow_unknown_labels: true` opts back into the old silent-zero behaviour for a caller that
        genuinely wants "0 when the label is absent" (probing whether a label exists at all). It is
        opt-IN because the failure it re-enables is exactly the one this guard exists to prevent.

        NO `snippet` FIELD, DELIBERATELY (N11). The summary FETCH asks for BODY.PEEK[HEADER] +
        BODYSTRUCTURE only; the first line of text/plain lives in a body part, so a snippet would
        cost a second FETCH of one part per message on every page — a body fetch, which is the
        exact cost this listing exists to avoid. The client drops snippets rather than this
        service faking them from the subject.

        `max_wait_s` bounds the wait for the mailbox's one connection (default LOCK_WAIT_S; 0 = wait
        as long as it takes); past it the answer is 503 "mailbox busy" (MailboxBusy).

        Returns {messages:[...], count, total, has_more, next_cursor, uidvalidity, uidnext,
        label_terms?}."""
        folder = b.get("folder", "INBOX")
        limit = int(b.get("limit", 50))
        since = int(b.get("since_uid") or 0)
        before = int(b.get("before_uid") or 0)
        since_ts = b.get("since_ts")
        since_ts = float(since_ts) if since_ts not in (None, "") else None

        # Resolve OUTSIDE the read connection — `_label_index` takes one of its own (see its note).
        query = b.get("query")
        label_terms = []
        if query and "label:" in query:
            by_key = _label_name_by_key(b.get("connection_id"))
            query, label_terms = rewrite_label_terms(query, by_key, self._label_index())
            if any(t["status"] == "unknown" for t in label_terms):
                # One retry against a FRESH listing before refusing: a label created seconds ago by
                # the label engine's own create pass must not be called unknown because our 60s
                # cache predates it.
                query, label_terms = rewrite_label_terms(
                    b["query"], by_key, self._label_index(refresh=True))
            unknown = [t for t in label_terms if t["status"] == "unknown"]
            if unknown and not b.get("allow_unknown_labels"):
                return {
                    "error": "unknown label(s) in query: %s — this search could not have matched "
                             "anything, so it is refused rather than answered with total:0"
                             % ", ".join(repr(t["raw"]) for t in unknown),
                    "unknown_labels": [t["raw"] for t in unknown],
                    "hint": "`label:` matches a label NAME, hyphenized (spaces -> '-'), not a "
                            "tag-rule KEY. KEYs from settings.sync_registry are resolved through "
                            "/organizer/settings automatically; a KEY that is not in the rules "
                            "cannot be. Pass allow_unknown_labels:true to get total:0 instead.",
                    "label_terms": label_terms,
                    "query": b.get("query"),
                }, 422

        with self._read_conn("search", wait=_wait_for(b, LOCK_WAIT_S)) as c:
            self._select(c, folder)
            status = c.folder_status(folder, ["UIDVALIDITY", "UIDNEXT"])
            uidvalidity = status.get(b"UIDVALIDITY", status.get("UIDVALIDITY"))
            uidnext = status.get(b"UIDNEXT", status.get("UIDNEXT"))
            if query:
                crit = [b"X-GM-RAW", query]
            else:
                crit = list(b.get("criteria") or ["ALL"])
            if since:
                crit = crit + ["UID", "%d:*" % (since + 1)]
            if since_ts is not None:
                # Stage 1 — the server does the expensive narrowing. ANDed as a plain extra term, so
                # `X-GM-RAW <query> SINCE <date>` and `UNSEEN SINCE <date>` are both one command.
                crit = crit + ["SINCE", imap_since_date(since_ts)]
            # CHARSET IS NOT OPTIONAL FOR THIS ACCOUNT'S SEARCHES.
            #
            # imapclient defaults `charset` to US-ASCII and encodes every `str` criterion with it,
            # so ANY non-ASCII search term raises UnicodeEncodeError before a single byte reaches
            # the server. Every INDOX gmail pipe searches by LABEL NAME, and this client's label
            # names are Hebrew (`לטיפול-אוטומציה-שמירת-מסמכים`, `אוטומציה-שמירת-מסמכים-נכשל`, …),
            # so `X-GM-RAW label:"<hebrew>"` was a hard 500 on the real mailbox — measured, not
            # inferred: `POST /search` with connection_id=<hachohen gmail> returned 500 for all six
            # configured label names while the same call against the ASCII-only local test mailbox
            # returned 200. The board's mail columns therefore could never show a client message.
            #
            # Sent as `SEARCH CHARSET UTF-8 ...` (RFC 3501 §6.4.4 — servers MUST support US-ASCII
            # and MAY support others; Gmail and Dovecot both accept UTF-8). Applied ONLY when a
            # criterion actually needs it, so every existing ASCII search keeps byte-identical
            # wire behaviour and no server that rejects the CHARSET argument is ever asked to
            # honour one it did not need.
            #
            # PRIMING `capabilities()` IS PART OF THE FIX, NOT HYGIENE. A non-ASCII criterion is too
            # long/8-bit to inline, so imapclient sends it as an IMAP literal — and `_send_literal`
            # reads `self._cached_capabilities` to decide between LITERAL+ and the synchronising
            # form. That cache is populated by `capabilities()`, which nothing on this pooled
            # connection had ever called, so the first UTF-8 search died on
            # `TypeError: argument of type 'NoneType' is not iterable` INSIDE imapclient — a second
            # failure hiding directly behind the first, and one that only appears once the charset
            # is right. One cheap call, cached on the connection for its lifetime.
            #
            # Verified live against this client's Gmail (2026-08-06, `[Gmail]/All Mail`): shipped
            # code raised UnicodeEncodeError for all seven configured label names; with charset +
            # priming the same searches returned 38,820 / 15,448 / 2,270 / 1,905 / 699 / 550 / 384.
            needs_utf8 = any(isinstance(x, str) and not x.isascii() for x in crit)
            if needs_utf8:
                if getattr(c, "_cached_capabilities", None) is None:
                    c.capabilities()
                uids = c.search(crit, "UTF-8")
            else:
                uids = c.search(crit)
            uids = sorted(uids)
            if since:
                # PROVEN (not assumed) live against this account: RFC 3501's UID-range clamp rule —
                # "if the upper OR LOWER bound of a UID sequence exceeds the mailbox's largest UID,
                # the server maps it down to the largest UID rather than returning nothing" — applies
                # to the LOWER bound too on Gmail's server. `since_uid=<current max>` (steady state,
                # nothing new) came back with count=1, the already-seen top message, not the empty
                # result the RFC's happy path implies; `since_uid=999999999` reproduced it identically,
                # ruling out a race with concurrently-arriving mail. Left alone this would hand the
                # incremental caller a message it already has on every "nothing new" pass — silent
                # RE-delivery, not silent loss, but a violation of "UID > since" all the same, and
                # exactly the kind of transport quirk a cursor design has to prove rather than assume.
                # The server-side UID term still does the expensive filtering (this is still one
                # SEARCH command, not a full re-list); this is a zero-cost in-memory correctness net
                # on top of it, not a fallback path.
                uids = [u for u in uids if u > since]
            candidates = uids                 # the widened window, before paging (see stage 2 below)
            total = len(uids)
            if before:
                uids = [u for u in uids if u < before]
            if since:
                has_more = len(uids) > limit
                uids = uids[:limit]
                next_cursor = uids[-1] if uids else since
            else:
                has_more = len(uids) > limit
                uids = uids[-limit:]
                next_cursor = uids[0] if uids else 0
            out = []
            kept = []
            if uids:
                resp = c.fetch(uids, [b"BODY.PEEK[HEADER]", b"BODYSTRUCTURE", b"X-GM-LABELS", b"X-GM-MSGID", b"X-GM-THRID", b"FLAGS", b"INTERNALDATE"])
                # ONLY THE UIDs WE ASKED FOR. An IMAP server may volunteer FETCH responses for
                # messages we did not request (RFC 3501 §5.2 — unsolicited responses carrying
                # changed FLAGS are explicitly allowed at any time), and imapclient hands those
                # back in the same dict. MEASURED on this account 2026-08-10: a search whose
                # `total` was 70 came back with 74 entries here, so four messages that never
                # matched the query were reported as matches — a caller paging `messages` saw
                # rows the search did not select. Filter to the requested set; it costs nothing
                # and `total` and `messages` can no longer disagree.
                wanted = set(uids)
                for uid, data in resp.items():
                    if uid not in wanted:
                        continue
                    # Stage 2, RIDING ON THE FETCH WE ALREADY DO — this is the whole performance
                    # story of the window, and it was MEASURED, not assumed. Refining the full
                    # candidate list in its own `FETCH INTERNALDATE` pass (the obvious
                    # implementation, and the first one here) cost one extra Gmail round trip of
                    # ~800ms, which on this account ate the entire ~600-800ms the narrowed SEARCH
                    # saves and left every window SLOWER than "all" — 30m measured 111% of All's
                    # p50, month 131%. The summary FETCH below already asks for INTERNALDATE for its
                    # own `date` field, so the exact time comparison is free here and costs a round
                    # trip anywhere else. Do not move it back out.
                    if since_ts is not None:
                        dt = data.get(b"INTERNALDATE")
                        # No INTERNALDATE -> KEEP. This is a view filter; the failure mode of
                        # guessing "too old" is hiding real mail.
                        if dt is not None and dt.timestamp() < since_ts:
                            continue
                    if b"RFC822" not in data and b"BODY[]" not in data:
                        data[b"BODY[HEADER]"] = data.get(b"BODY[HEADER]", b"")
                    out.append(_msg_summary(uid, data))
                    kept.append(uid)
            if since_ts is not None:
                # `total` for a windowed call, WITHOUT paying for a second round trip.
                #
                # ⚠ AN EARLIER VERSION OF THIS DERIVED `total` FROM UID ORDER — "everything at or
                # above the oldest message we kept is newer, so count those" — on the usual
                # assumption that a folder's UIDs ascend with arrival time. THAT ASSUMPTION IS FALSE
                # ON THIS ACCOUNT AND WAS CAUGHT BY MEASURING IT: against `[Gmail]/All Mail`, a 30m
                # window that correctly returned 3 messages reported `total` 84 — the whole widened
                # candidate set — because the lowest UID in that set carries a recent INTERNALDATE.
                # Gmail's All Mail does not promise UID order matches date order, so any arithmetic
                # resting on it silently produces a plausible wrong number. It is not re-derivable
                # from a cheaper signal; the honest options are an extra FETCH or an upper bound.
                #
                # So: claim an EXACT total only when it was actually established — first page, and
                # the whole candidate set fitted in it, meaning every candidate was fetched and
                # date-tested above. Otherwise report the candidate count, which is a true UPPER
                # BOUND (the window plus at most the one widened day, plus any pages not yet
                # fetched). An upper bound labelled as a count is a small honest imprecision; a
                # confidently wrong count is not.
                if not before and len(candidates) <= limit:
                    total = len(kept)
                else:
                    total = len(candidates)
        r = {"messages": out, "count": len(out), "total": total,
             "has_more": has_more, "next_cursor": next_cursor,
             "uidvalidity": uidvalidity, "uidnext": uidnext}
        if label_terms:
            # What each label term actually became, on EVERY response — not only failures. A zero
            # that carries `[{raw:'SYNCED_DOC', resolved:'אוטומציה-שמירת-מסמכים-טופל',
            # status:'matched'}]` is a fact about the mailbox; the same zero with no provenance is
            # the thing that let a "the gmail pipes are drained" conclusion stand unchallenged.
            r["label_terms"] = label_terms
        return r

    def _cache_put(self, payload, source, all_mail):
        """Write the cacheable projection of one rendered message. `all_mail` says whether
        `payload["uid"]` is a [Gmail]/All Mail uid (the only kind the cached-labels refresh may
        reuse); a folder-relative uid is not stored. Never raises, never stores attachment bytes."""
        try:
            gid = payload.get("id")
            if not gid:
                return False
            msg = dict(payload)
            if not all_mail:
                msg["uid"] = None
            return self._cache.put(self.user, gid, msg, source=source)
        except Exception:
            return False

    def _from_cache(self, gid, hit):
        """A `meta=true` answer served from the body cache: `cached: true`, `cached_at`, and the
        labels refreshed LIVE only when that is cheap — the uid is already known (from the entry or
        `_uid_cache`, so no SEARCH) and the connection frees up within CACHE_LABELS_WAIT_S (so the
        open never queues behind a sync fetch). Otherwise the labels seen at cache time are
        returned and `labels_live` says so."""
        out = dict(hit["message"])
        out.update(meta=True, cached=True, cached_at=hit.get("cached_at"),
                   cache_source=hit.get("source"), labels_live=False)
        uid = self._uid_cache.get(gid) or out.get("uid")
        if uid:
            try:
                with self._read_conn("message:labels", wait=CACHE_LABELS_WAIT_S) as c:
                    self._select(c, ALL_MAIL)
                    d = c.fetch([uid], [b"X-GM-LABELS", b"X-GM-MSGID"]).get(uid) or {}
                    # The uid must still name THIS message (a UIDVALIDITY change would not).
                    if _gmail_id(d.get(b"X-GM-MSGID")) == gid:
                        out["labels"] = _decode_labels(d.get(b"X-GM-LABELS"))
                        out["labels_live"] = True
                        self._uid_cache[gid] = uid
            except MailboxBusy:
                pass
            except Exception:
                pass
        return out

    @quota_retry
    def message(self, uid, args, log=None):
        """Full message incl body + attachments (base64).
        By IMAP uid:  /message/<uid>?folder=INBOX&attachments=true
        By Gmail id:  /message/0?id=<hex>&attachments=true   (resolved via All Mail)
        Metadata-only (no attachment bytes — for the Label Engine, which classifies on attachment
        name/mime/size only):  ...&meta=true  → fetches BODYSTRUCTURE + HEADER + text parts only
        (skips the multi-MB attachment download). Falls back to the full fetch on any parse error.

        BODY CACHE (N11): a `meta=true` read by Gmail id is answered from the cache when the message
        was ever fetched in full (a sync delivery), read in a thread, or read as meta before — zero
        IMAP commands, `cached: true` on the answer (see `_from_cache`). Every full fetch, thread
        read and meta read writes the cache. The full fetch itself never reads it: a delivery must
        carry the bytes.

        `max_wait_s` bounds the wait for the connection: the meta read defaults to LOCK_WAIT_S and
        answers 503 past it; the FULL fetch defaults to waiting as long as it takes (the sync
        deliveries queue on the one connection by design — gmailApiImap01 `http:get`, 300 s)."""
        folder = args.get("folder", "INBOX")
        gid = args.get("id")
        gid = gid.strip().lower() if isinstance(gid, str) else gid
        want_att = args.get("attachments", "true") == "true"
        if args.get("meta") == "true":
            if gid:
                hit = self._cache.get(self.user, gid)
                if hit:
                    return self._from_cache(gid, hit)
            try:
                with self._read_conn("message:meta", wait=_wait_for(args, LOCK_WAIT_S)) as c:
                    if gid:
                        self._select(c, ALL_MAIL)
                        found = self._uids_for_ids(c, [gid])
                        if not found:
                            return {"error": "not found"}, 404
                        uid = found[0]
                    else:
                        self._select(c, folder)
                    resp = c.fetch([uid], [b"BODYSTRUCTURE", b"BODY.PEEK[HEADER]",
                                           b"X-GM-LABELS", b"X-GM-MSGID", b"X-GM-THRID", b"INTERNALDATE"])
                    if uid not in resp:
                        return {"error": "not found"}, 404
                    data = resp[uid]
                    leaves = _bs_leaves(data.get(b"BODYSTRUCTURE")) if data.get(b"BODYSTRUCTURE") else []
                    text_leaves = [l for l in leaves if not l["is_att"] and l["type"] == "text"]
                    att_leaves = [l for l in leaves if l["is_att"]]
                    body_text, body_html = "", ""
                    if text_leaves:
                        keys = [f"BODY.PEEK[{l['num']}]".encode() for l in text_leaves]
                        td = c.fetch([uid], keys).get(uid, {})
                        for l in text_leaves:
                            raw = td.get(f"BODY[{l['num']}]".encode()) or b""
                            if l["enc"] == "BASE64":
                                try: raw = base64.b64decode(raw)
                                except Exception: pass
                            elif l["enc"] == "QUOTED-PRINTABLE":
                                try: raw = quopri.decodestring(raw)
                                except Exception: pass
                            txt = raw.decode(l["charset"] or "utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
                            if l["subtype"] == "plain" and not body_text:
                                body_text = txt
                            elif l["subtype"] == "html" and not body_html:
                                body_html = txt
                    atts = [{"filename": l["filename"] or "attachment",
                             "mimeType": f"{l['type']}/{l['subtype']}", "size": l["size"]} for l in att_leaves]
                msg = email.message_from_bytes(data.get(b"BODY[HEADER]") or b"")
                out = {
                    "uid": uid, "id": _gmail_id(data.get(b"X-GM-MSGID")),
                    "gm_msgid": str(data.get(b"X-GM-MSGID", "")), "gm_thrid": str(data.get(b"X-GM-THRID", "")),
                    "threadId": _gmail_id(data.get(b"X-GM-THRID")),
                    "from": _hdr(msg, "From"), "to": _hdr(msg, "To"),
                    "subject": _hdr(msg, "Subject"), "date": _date_of(msg, data),
                    "labels": _decode_labels(data.get(b"X-GM-LABELS")),
                    "body_text": body_text, "body_html": body_html, "attachments": atts, "meta": True,
                }
                self._cache_put(out, "meta", all_mail=bool(gid))
                return out
            except MailboxBusy:
                raise                      # a bounded wait must never fall through to an unbounded one
            except Exception as e:
                if log:
                    log.warning(f"meta fetch failed (uid={uid} id={gid}): {e!r}; falling back to full fetch")
                # fall through to the full RFC822 path below
        with self._read_conn("message:full", wait=_wait_for(args, None)) as c:
            if gid:
                self._select(c, ALL_MAIL)
                found = self._uids_for_ids(c, [gid])
                if not found:
                    return {"error": "not found"}, 404
                uid = found[0]
            else:
                self._select(c, folder)
            resp = c.fetch([uid], [b"RFC822", b"X-GM-LABELS", b"X-GM-MSGID", b"X-GM-THRID", b"INTERNALDATE"])
            if uid not in resp:
                return {"error": "not found"}, 404
            data = resp[uid]
        msg = email.message_from_bytes(data[b"RFC822"])
        body_text, body_html, atts = "", "", []
        for part in (msg.walk() if msg.is_multipart() else [msg]):
            ct = part.get_content_type()
            disp = part.get_content_disposition()
            fn = part.get_filename()
            if fn or disp == "attachment":
                if want_att:
                    try:
                        payload = part.get_payload(decode=True) or b""
                        atts.append({
                            "filename": str(make_header(decode_header(fn))) if fn else "attachment",
                            "mimeType": ct,
                            "size": len(payload),
                            "content_id": (part.get("Content-ID") or "").strip("<> "),
                            "data_base64": base64.b64encode(payload).decode(),
                        })
                    except Exception:
                        pass
            elif ct == "text/plain" and not body_text:
                body_text = decode_part(part)
            elif ct == "text/html" and not body_html:
                body_html = decode_part(part)
        out = {
            "uid": uid, "id": _gmail_id(data.get(b"X-GM-MSGID")),
            "gm_msgid": str(data.get(b"X-GM-MSGID", "")), "gm_thrid": str(data.get(b"X-GM-THRID", "")),
            "threadId": _gmail_id(data.get(b"X-GM-THRID")),
            "from": _hdr(msg, "From"), "to": _hdr(msg, "To"),
            "subject": _hdr(msg, "Subject"), "date": _date_of(msg, data),
            "labels": _decode_labels(data.get(b"X-GM-LABELS")),
            "body_text": body_text, "body_html": body_html, "attachments": atts,
        }
        # The sync deliveries' path: the whole message was just downloaded and parsed, so this is
        # the moment the cache is filled for free (attachment META only — bytes never land on disk).
        if want_att:
            self._cache_put(out, "full", all_mail=bool(gid))
        return out

    @quota_retry
    def thread(self, tid, args=None, log=None):
        """Every message of one conversation, oldest first. `tid` is a Gmail hex id — either the
        thread's own id (threadId) or ANY message in it, because callers rarely have the former.

        This endpoint did not exist, and its absence has been costing more than the missing feature.
        `Mail Label Engine`'s `Get Gmail Thread` node is disabled precisely because there was
        nothing to call, which is why three rules — BS_TO_SYNC, CORRESPONDENCE_STARTED and
        BS_REPORT_REQUEST — read `thread.messages[0].text` / `thread.from` and can never match. See
        ai/context/mail-organizer-refactor.md. One endpoint fixes those and the conversation view.

        Gmail threads natively (X-GM-THRID), and every fetch in this class already asks for it, so
        the work here is a search and an ordering — not new plumbing.
        """
        args = args or {}
        want_bodies = str(args.get("bodies", "true")).lower() != "false"
        with self._read_conn("thread", wait=_wait_for(args, LOCK_WAIT_S)) as c:
            self._select(c, ALL_MAIL)
            # Accept a message id as well as a thread id: resolve it to the thread it belongs to.
            thrid = None
            found = self._uids_for_ids(c, [str(tid)])
            if found:
                r = c.fetch([found[0]], [b"X-GM-THRID"])
                thrid = str(r.get(found[0], {}).get(b"X-GM-THRID", "")) or None
            if not thrid:
                # Not a message id — treat the value itself as a thread id (hex or decimal).
                try:
                    thrid = str(int(str(tid), 16))
                except ValueError:
                    thrid = str(tid)
            uids = c.search(["X-GM-THRID", thrid])
            if not uids:
                return {"error": "not found", "threadId": _gmail_id(thrid)}, 404
            uids = sorted(uids)
            fetch = [b"RFC822" if want_bodies else b"BODY.PEEK[HEADER]",
                     b"X-GM-LABELS", b"X-GM-MSGID", b"X-GM-THRID", b"FLAGS", b"INTERNALDATE"]
            resp = c.fetch(uids, fetch)

        messages = []
        for uid in uids:
            data = resp.get(uid)
            if not data:
                continue
            if want_bodies:
                m = _render_message(uid, data, want_att=False)
                # A thread read parses every message's RFC822 anyway — cache them (All Mail uids).
                self._cache_put(m, "thread", all_mail=True)
            else:
                m = _msg_summary(uid, data)
            messages.append(m)
        # Oldest first: a conversation reads top-down, and every consumer that wants "the first
        # message" (the rules above do) means the oldest one.
        messages.sort(key=lambda m: m.get("uid") or 0)
        first = messages[0] if messages else {}
        return {
            "threadId": _gmail_id(thrid),
            "gm_thrid": thrid,
            "count": len(messages),
            "messages": messages,
            # Flattened conveniences the label-engine rules read directly, so a rule does not have
            # to know the envelope shape: `thread.from`, `thread.subject`, `thread.text`.
            "from": first.get("from", ""),
            "subject": first.get("subject", ""),
            "text": first.get("body_text", "") or "",
        }

    @quota_retry
    def labels_add(self, b):
        """Body: {id|ids:[hex] (preferred) OR uid|uids:[int], labels|label:[names] OR labelIds:[Label_NN], folder?,
        remove?:[names]}.

        `remove` (2026-09-03): labels to take OFF the same messages in the same connection hold — one
        round trip for a state change. The sync's source feedback moves a message from the pipe's
        to-sync label to its synced/failed label; before this it could only ADD the outcome label, so
        every handled message kept wearing the to-sync label as well (measured on the real run
        e2e-final-1840: 9 of 9 messages carried both). A label that means "waiting for the
        automation" must come off when the automation is done, exactly as a drive file leaves
        to_sync for synced."""
        labels = _labels_from(b)
        remove = [str(x) for x in (b.get("remove") or []) if str(x).strip()]
        ids = b.get("ids") or ([b["id"]] if b.get("id") else [])
        with self._read_conn("labels_add", wait=_wait_for(b, None)) as c:
            if ids:
                self._select(c, ALL_MAIL)
                uids = self._uids_for_ids(c, ids)
            else:
                uids = [int(u) for u in (b.get("uids") or ([b["uid"]] if b.get("uid") else []))]
                self._select(c, b.get("folder", "INBOX"))
            if uids and labels:
                c.add_gmail_labels(uids, labels, silent=True)
            if uids and remove:
                c.remove_gmail_labels(uids, [r for r in remove if r not in labels], silent=True)
        return {"ok": True, "uids": uids, "added": labels, "removed": remove}

    @quota_retry
    def labels_remove(self, b):
        """Body: {id|ids:[hex] (preferred) OR uid|uids:[int], labels|label:[names] OR labelIds:[Label_NN], folder?}."""
        labels = _labels_from(b)
        ids = b.get("ids") or ([b["id"]] if b.get("id") else [])
        with self._read_conn("labels_remove", wait=_wait_for(b, None)) as c:
            if ids:
                self._select(c, ALL_MAIL)
                uids = self._uids_for_ids(c, ids)
            else:
                uids = [int(u) for u in (b.get("uids") or ([b["uid"]] if b.get("uid") else []))]
                self._select(c, b.get("folder", "INBOX"))
            if uids and labels:
                c.remove_gmail_labels(uids, labels, silent=True)
        return {"ok": True, "uids": uids, "removed": labels}

    @quota_retry
    def labels_list(self):
        with self._read_conn("labels_list") as c:
            folders = c.list_folders()
        return {"labels": [name for (_f, _d, name) in folders]}

    @quota_retry
    def labels_create(self, b):
        name = b["name"]
        with self._read_conn("labels_create", wait=_wait_for(b, None)) as c:
            try:
                c.create_folder(name)
            except Exception as e:
                if not _already_exists(e):
                    raise
        return {"ok": True, "name": name}

    # `labels_delete` (POST /labels/delete) was removed 2026-09-02 (RELEASE-DECISIONS N12): zero
    # callers in the tree — no workflow, no BFF, no UI ever deleted a Gmail label through here.

    @quota_retry
    def append(self, b):
        """Seed a message into the mailbox (replaces Gmail API messages.insert; no quota).
        Body: {raw_base64? | raw?, labels?:[names], folder?:'INBOX', flags?:[]}."""
        raw = base64.b64decode(b["raw_base64"]) if b.get("raw_base64") else b["raw"].encode()
        folder = b.get("folder", "INBOX")
        labels = _labels_from(b)
        with self._read_conn("append", wait=_wait_for(b, None)) as c:
            resp = c.append(folder, raw, flags=b.get("flags") or [])
            if labels:
                # O(1) label: use the APPENDUID (RFC 4315 UIDPLUS; Gmail supports it) instead of an
                # INBOX-size-dependent Message-ID search (the high-load injection slowdown). Fallback to search.
                uid = None
                try:
                    s = resp.decode() if isinstance(resp, (bytes, bytearray)) else str(resp)
                    m = _re.search(r"APPENDUID\s+\d+\s+(\d+)", s)
                    if m:
                        uid = int(m.group(1))
                except Exception:
                    uid = None
                self._select(c, folder)
                if uid:
                    c.add_gmail_labels([uid], labels, silent=True)
                else:
                    msg = email.message_from_bytes(raw)
                    mid = msg.get("Message-ID")
                    if mid:
                        uids = c.search(["HEADER", "Message-ID", mid])
                        if uids:
                            c.add_gmail_labels(uids, labels, silent=True)
        return {"ok": True}

    @quota_retry
    def send(self, b):
        msg = EmailMessage()
        frm = b.get("from", self.user)
        msg["From"] = frm
        msg["To"] = b["to"]
        msg["Subject"] = b.get("subject", "")
        # Date + Message-ID: RFC 5322 requires both, and receivers enforce Message-ID
        # ("550 5.7.1 Messages missing a valid Message-ID header are not accepted" from Google).
        # Gmail's submission service happens to fill them in, so this path was not the one that
        # broke — but relying on a particular smarthost's generosity for a header the standard
        # already requires is how the local path came to omit it, so compose it here as well.
        # The right-hand side is the sending account's OWN domain, taken from the From address.
        msg["Date"] = formatdate(localtime=True)
        _dom = (parseaddr(frm)[1].rsplit("@", 1) + [""])[1] or None
        msg["Message-ID"] = make_msgid(domain=_dom) if _dom else make_msgid()
        msg.set_content(b.get("body", ""))
        for a in b.get("attachments", []):
            msg.add_attachment(base64.b64decode(a["data_base64"]),
                               maintype=a.get("mimeType", "application/octet-stream").split("/")[0],
                               subtype=a.get("mimeType", "application/octet-stream").split("/")[-1],
                               filename=a.get("filename", "attachment"))
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, context=ctx) as S:
            if self.token_provider is not None:
                # smtplib has no XOAUTH2 mechanism: hand it the SASL string and let it base64 the
                # return value, exactly as it does for the built-in mechanisms.
                tok = self.token_provider()
                S.auth("XOAUTH2", lambda _challenge=None: "user=%s\1auth=Bearer %s\1\1" % (self.user, tok))
            else:
                S.login(self.user, self.password)
            S.send_message(msg)
        return {"ok": True}


class GmailOAuthBackend(GmailBackend):
    """Same IMAP/SMTP path, XOAUTH2 instead of an app-password. Separate class only so the protocol
    it answers for is explicit; behaviour is identical by construction."""

    protocol = "mail_gmail_oauth"
