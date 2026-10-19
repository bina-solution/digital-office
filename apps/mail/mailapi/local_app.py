"""LOCAL mail BACKEND — the same HTTP contract as the Gmail backend, served from our own
Postfix + Dovecot (`mailserver` service) instead of real Gmail.

Was a standalone Flask app selected at process start by GMAIL_IMAP_MODE=local; now a backend class
resolved per REQUEST from the selected connection — protocol `mail_imap_local`, one REAL vault
instance per declared profile, each carrying its own {username, password} (profiles.py). service.py
owns the routes; the bodies moved here verbatim as methods and return the same payloads.

Why a separate backend (not shims in app.py): app.py leans on Gmail-proprietary IMAP
extensions at ~36 sites (X-GM-MSGID identity, X-GM-LABELS, X-GM-RAW search, All Mail).
Locally those concepts map cleanly onto base IMAP:

  identity   id == hex(INBOX UID)          (all messages live ONLY in INBOX)
  labels     IMAP keywords (custom flags). Hebrew/space names aren't atoms, so each
             label name gets a deterministic atom `kw<base32(utf8)>`; the name<->atom registry
             lives PER PROFILE at /data/labels/<connection_id>.json (see LABEL_REGISTRY_DIR below)
             and self-rebuilds from flags. One dovecot mailbox per profile already isolates
             messages/folders/flags; the registry file is the one piece of this backend's state
             that used to be shared across every profile in the container regardless.
  search     the bounded gmail-query grammar the workflows actually use is translated
             to IMAP SEARCH: label:X -> KEYWORD, -label:X -> UNKEYWORD, AND implicit,
             (a OR b), newer_than:Nd|m -> SINCE, is:unread -> UNSEEN, free text -> TEXT,
             has:attachment -> post-filter, in:/-in: -> ignored (no such concept here).
  /send      SMTP to our own Postfix, which delivers locally or attempts real off-box delivery
             and BOUNCES honestly when it cannot; always archived under the SENT keyword.

Deterministic by construction: no search-index lag, no OVERQUOTA, no label-name
normalization quirks — the CI/e2e path for the gmail syncs.
"""
import os, base64, hashlib, json, time, threading, email, smtplib, datetime, quopri, re as _re
from email.header import decode_header, make_header
from email.utils import formatdate, format_datetime, make_msgid
from collections import Counter
from imapclient import IMAPClient

# The time-window primitive is IMPORTED, not reimplemented. This module is the deterministic
# stand-in for the Gmail backend, so a second copy of the SINCE widening / INTERNALDATE refinement
# is exactly the kind of drift that makes a green local test prove nothing about the real mailbox.
# Safe direction: adapters.py imports both modules and app.py imports neither of them, so this adds
# no cycle. `_bs_leaves` joins for the same reason: the metadata-only /message path below reads
# attachment name/mime/size out of BODYSTRUCTURE exactly the way the Gmail backend does, and a
# second BODYSTRUCTURE walker is a second place for the two backends' `attachments` to disagree.
from app import imap_since_date, decode_part, _bs_leaves

_START = time.time()

# LOCALMAIL_* — its own namespace: the compose file always passes the GMAIL_* vars with
# Gmail defaults, so reusing them here would point local mode at imap.gmail.com.
IMAP_HOST = os.environ.get("LOCALMAIL_IMAP_HOST", "mailserver")
IMAP_PORT = int(os.environ.get("LOCALMAIL_IMAP_PORT", "143"))
IMAP_SSL = os.environ.get("LOCALMAIL_IMAP_SSL", "0") == "1"
SMTP_HOST = os.environ.get("LOCALMAIL_SMTP_HOST", "mailserver")
SMTP_PORT = int(os.environ.get("LOCALMAIL_SMTP_PORT", "25"))

# ── what does "sent" mean here? ────────────────────────────────────────────────
# The backend now talks to a REAL MTA (Postfix, in the `mailserver` service). That changes what this
# function can honestly claim, and it is worth being precise about, because the previous answer was
# wrong in a way nothing detected.
#
# Under GreenMail — a TEST double — every recipient was accepted, and an address it had never seen
# got a freshly-created local mailbox with the message in it. Proven, not assumed:
#     POST /send {"to":"deliverability-probe@example.com"} -> {"ok":true,"via":"smtp"}
#     greenmail: 'Created user login deliverability-probe@example.com ... because it didn't exist'
# The API said sent. Nothing left the host. GreenMail is gone for exactly this reason.
#
# Postfix cannot do that. It either delivers, queues and retries, or bounces — and it says which.
# So the honest report is QUEUED: our MTA has accepted responsibility for the message. Final delivery
# is asynchronous by nature (SMTP has always worked this way; even Gmail only promises acceptance),
# and the outcome lands in the mail log rather than in this response.
#
#   "mta"   (default) — hand off to our own Postfix. It delivers locally, and attempts the internet
#                       if the host can reach port 25 outbound.
#   "relay"           — hand off to an external smarthost instead (SES/SendGrid/Mailgun/Gmail SMTP),
#                       which needs auth and a From at a domain carrying SPF/DKIM.
SMTP_MODE = (os.environ.get("LOCALMAIL_SMTP_MODE") or "mta").strip().lower()
SMTP_USER = os.environ.get("LOCALMAIL_SMTP_USER", "")
SMTP_PW = os.environ.get("LOCALMAIL_SMTP_PW", "")
SMTP_STARTTLS = os.environ.get("LOCALMAIL_SMTP_STARTTLS", "1") == "1"
# The envelope sender. On a relay this must be a domain you control and that carries SPF/DKIM, or
# receivers will reject or spam-file it regardless of what the relay accepts.
SMTP_FROM = os.environ.get("LOCALMAIL_SMTP_FROM", "")
_u = os.environ.get("LOCALMAIL_USER", "indox")
# The mailbox lives at <user>@<the deployment's mail domain>. This used to hardcode "@local.test",
# which is right on a laptop and wrong on every real deployment — and wrong in the most confusing
# possible way, because BOTH halves looked correct in isolation:
#
#   mailserver-init provisioned  person110@example.com   (it appends MAIL_DOMAIN)
#   this backend logged in as    indox@local.test                          (it appended local.test)
#
# so a freshly deployed company got `[AUTHENTICATIONFAILED] Authentication failed` against a mailbox
# that existed, with a password that was correct, for an account nobody had mistyped. The two sides
# must derive the address from the SAME variable or they will drift again.
_domain = os.environ.get("MAIL_DOMAIN", "local.test").strip() or "local.test"
USER = _u if "@" in _u else _u + "@" + _domain
PW = os.environ.get("LOCALMAIL_PW", "indox")

# ── the label registry is PER PROFILE ───────────────────────────────────────────
# It used to be one file for the whole container (`/data/labels.json`), which was fine when there
# was exactly one local mailbox. Once app-engine-pattern.md gave the private engine N profiles, each
# with its OWN dovecot mailbox, this file became the one piece of local-mode state that stayed
# deployment-wide: messages/folders/flags are correctly isolated per profile (separate IMAP
# mailboxes do that for free), but /labels decoded every profile's keyword atoms through the SAME
# name registry — so `admin` and `user2` saw an identical ~35-name label list regardless of which
# mailbox was actually selected, and a label admin created was visible (as a bare atom string, once
# user2 happened to apply the same keyword) to a mailbox that never touched it.
#
# Keyed by CONNECTION ID — the same currency every other per-request choke point in this service
# uses (adapters._backends, the secret cache, the active pointer) — rather than by mailbox address,
# so a profile whose vault instance is recreated (adapters.py's "declared, mailbox live, instance
# gone" path) starts a fresh registry rather than silently inheriting one it has no proof it owns.
# No migration from the old shared file: per the operator, a fresh per-profile file is the clean
# answer, and a brand-new profile must not inherit another profile's label vocabulary.
LABEL_REGISTRY_DIR = os.environ.get("LABEL_REGISTRY_DIR", "/data/labels")


def _safe_reg_key(connection_id):
    """A connection id is already filesystem-safe (`<protocol>-<8hex>`), but this is a path
    component built from caller-supplied data, so it is never trusted blindly."""
    key = str(connection_id or "").strip()
    if not key or key in (".", "..") or _re.search(r"[^A-Za-z0-9_.-]", key):
        return "_unscoped"      # no connection id at all — never expected in practice (every
                                # LocalBackend is built from a resolved connection id), but a
                                # per-process fallback file beats crashing the request.
    return key


def _reg_path_for(connection_id):
    return os.path.join(LABEL_REGISTRY_DIR, _safe_reg_key(connection_id) + ".json")

_cmd_stats = Counter()

SYSTEM = {"INBOX", "SENT", "DRAFT", "DRAFTS", "SPAM", "TRASH", "STARRED", "IMPORTANT", "UNREAD"}

# Of those, these two are IMAP FLAGS rather than folders, so they DO discriminate in a single-folder
# model and must survive the SYSTEM filter on both read and write. Dropping them was a silent
# double no-op: `label:STARRED` matched every message (no constraint at all) and adding STARRED
# stored nothing — so the Starred view showed the whole mailbox and starring appeared to work.
#
# INBOX/SENT/DRAFT/SPAM/TRASH stay out on purpose: this backend has one folder, so they have nowhere
# to go and pretending otherwise would lose mail.
FLAG_LABELS = {"STARRED": r"\Flagged", "IMPORTANT": "IMPORTANT"}


# SENT is a real IMAP keyword here, and it became one the day /send started writing it (below).
# Before that, an outgoing message was archived to INBOX under `SENT-COPY` alone — a label BOTH mail
# UIs deliberately hide as machine bookkeeping — so `label:SENT` matched nothing, every נשלח view
# reported "לא נשלחו הודעות", and the mail was not missing but mislabelled.
#
# It is deliberately NOT in FLAG_LABELS: that table is applied by labels_add/labels_remove in the
# direction it is given, and "this message was sent" is not a property a reader hand-applies to
# someone else's mail — only the send path writes it. It IS honoured on the read side (_term below),
# which is all a view needs.
KW_SENT = "SENT"


# UNREAD is the third system flag this backend can honour, and the only INVERTED one: IMAP stores
# \Seen, the API speaks UNREAD, so adding UNREAD REMOVES \Seen and removing UNREAD ADDS it. It cannot
# join FLAG_LABELS above, which the add/remove paths apply in the direction they were given — an
# UNREAD in that table would set a \Seen when asked to mark unread, i.e. exactly backwards.
# It is not a keyword either: routed to the keyword path it registered an atom named UNREAD in the
# label registry, so "UNREAD" then appeared in /labels as if it were one of the reader's own labels.
_SEEN = "\\Seen"


def _split_flag_labels(labels):
    """(keyword labels, imap flags) — flags being the system labels this backend can honour."""
    kw, flags = [], []
    for l in labels:
        if str(l).upper() == "UNREAD":
            continue                       # handled separately — see _wants_unread / _SEEN
        if str(l).upper() in FLAG_LABELS:
            flags.append(FLAG_LABELS[str(l).upper()])
        else:
            kw.append(l)
    return kw, flags


def _wants_unread(labels):
    """Did this add/remove name UNREAD? The caller inverts it into a \\Seen write."""
    return any(str(l).upper() == "UNREAD" for l in labels)


# ── label name <-> keyword atom registry ────────────────────────────────────────
#: dovecot's `mail_max_keyword_length`. A STORE naming a longer keyword is refused outright with
#: "[CANNOT] Keyword length too long", which imapclient raises and Flask turns into a 500.
_MAX_KEYWORD = 50


def _atom(name):
    """label name -> a keyword atom that dovecot will actually accept.

    base32 expands 5 bytes to 8 characters, and Hebrew costs 2 UTF-8 bytes per character, so a
    Hebrew label cost ~3.3x its length as a keyword: 'אינדוקס - מסמכים כללי - לטיפול' (29 chars)
    became an 87-character atom against a 50-character limit. THIRTEEN of the twenty-six labels on
    this stack — every INDOX label, all of them Hebrew — could not be applied at all. The symptom was
    not a validation error but a Flask 500 with an HTML body, which n8n reported as "The service was
    not able to process your request", so the mail_organizer lane failed with no hint of the cause.

    The encoding was never load-bearing. `_reg_label` persists atom -> name and `_decode_atoms`
    resolves through that registry — nothing anywhere reverses the base32 — so an atom only has to be
    stable, unique and short. Hash the ones that do not fit.

    Short names keep their exact base32 atom, which is why this needs no migration: every label that
    works today keeps working, byte for byte, and only the ones that could never be stored change.
    """
    b32 = base64.b32encode(name.encode("utf-8")).decode().rstrip("=").lower()
    atom = "kw" + b32
    if len(atom) <= _MAX_KEYWORD:
        return atom
    # 16 hex chars of blake2s -> a fixed 19-character atom, whatever the name. 64 bits is far more
    # than enough to keep a per-mailbox label set collision-free, and a collision would be visible in
    # the registry rather than silent.
    return "kwh" + hashlib.blake2s(name.encode("utf-8"), digest_size=8).hexdigest()


# mtime-keyed registry cache. `_decode_atoms` runs once PER MESSAGE of every /search page and
# /thread reassembly, and each call used to open+parse the registry file again — a 100-row page paid
# 100 identical file reads inside the backend lock. The registry is tiny and changes rarely (a label
# create/delete), so cache the parsed dict per path and let the file's mtime invalidate it: an
# external writer (there is none today — only this process writes it) is still picked up on the next
# stat. Readers get the SHARED dict and must not mutate it; the two mutators below copy first.
_REG_CACHE = {}   # reg_path -> (mtime_ns, dict)


def _load_reg(reg_path):
    try:
        st = os.stat(reg_path)
    except OSError:
        return {}
    hit = _REG_CACHE.get(reg_path)
    if hit and hit[0] == st.st_mtime_ns:
        return hit[1]
    try:
        reg = json.load(open(reg_path, encoding="utf-8"))
    except Exception:
        return {}
    _REG_CACHE[reg_path] = (st.st_mtime_ns, reg)
    return reg


def _save_reg(reg_path, reg):
    try:
        os.makedirs(os.path.dirname(reg_path), exist_ok=True)
        json.dump(reg, open(reg_path, "w", encoding="utf-8"), ensure_ascii=False)
        try:   # keep the cache coherent with what was just written, without a re-parse
            _REG_CACHE[reg_path] = (os.stat(reg_path).st_mtime_ns, dict(reg))
        except OSError:
            _REG_CACHE.pop(reg_path, None)
    except Exception:
        pass


def _reg_label(reg_path, name):
    """name -> atom, persisting the mapping (in THIS profile's registry) so /labels can decode
    back. Junk guard: refuse system names and '-'-prefixed artifacts (negated query terms
    leak in as 'labels' from some callers — e.g. the recurring '-INBOX')."""
    name = str(name).strip().strip('"')
    if not name or name.startswith("-"):
        return None
    if name.upper() in SYSTEM:
        return name.upper()
    reg = _load_reg(reg_path)
    a = _atom(name)
    if reg.get(a) != name:
        reg = dict(reg)        # never mutate the cached dict (see _REG_CACHE)
        reg[a] = name
        _save_reg(reg_path, reg)
    return a


def _decode_atoms(reg_path, flags):
    """IMAP FLAGS -> the label names the API speaks.

    Backslash flags used to be skipped wholesale, which quietly threw away the two pieces of state
    every mail UI is built on. The backend stored them and could SEARCH them — `is:unread` and
    `label:STARRED` both work — but a message summary reported `labels: []`, so nothing that read a
    message could tell that it was unread or starred. Downstream that is not a missing badge: the
    reader had no bold rows, no unread counts in its rail, "select all unread" selected nothing (and
    therefore no bulk bar and no undo), and a star did not survive a refetch because the client seeds
    its starred set from exactly this field.

    \\Seen is reported by its ABSENCE, as UNREAD — the name the rest of the platform uses (Gmail's),
    so one client works against either backend. Every call site fetches b"FLAGS", so an empty tuple
    here means "no flags", not "not asked".
    """
    reg = _load_reg(reg_path)
    out, seen = [], False
    for f in flags or ():
        f = f.decode() if isinstance(f, (bytes, bytearray)) else str(f)
        if f.startswith("\\"):
            low = f.lower()
            if low == "\\seen":
                seen = True
            elif low == "\\flagged":
                out.append("STARRED")
            continue                        # \Recent, \Answered, \Draft, \Deleted: no API meaning
        out.append(reg.get(f, f))
    if not seen:
        out.append("UNREAD")
    return out


def _labels_from(b):
    ls = b.get("labels") or ([b["label"]] if b.get("label") else []) or b.get("labelIds") or []
    if isinstance(ls, str):
        ls = [ls]
    return [l for l in ls if l]


# ── labels-as-folders: the human mirror for webmail (Roundcube) ────────────────
# Keywords on INBOX stay the API's source of truth (deterministic /search); each label
# ALSO exists as a real IMAP folder holding a COPY of the message — the same shape Gmail
# itself exposes over IMAP — so email.localhost shows labels + sync progress natively.
# The mirror is a VIEW: the HTTP API never reads it, so drift is cosmetic, not corrupting.
def _human_labels(b):
    return [n for n in _labels_from(b) if n and n.upper() not in SYSTEM]


# ── the bounded gmail-query grammar -> IMAP SEARCH ─────────────────────────────
_TOKEN = _re.compile(r'-?(?:label:|subject:)"[^"]*"|-?(?:label:|subject:|in:|has:|is:|newer_than:)?[^\s()]+')


def _gmail_form(name):
    """Gmail's label-search normalization: every space becomes a hyphen."""
    return name.replace(" ", "-")


def _resolve_atoms(reg_path, name):
    """Gmail query form -> matching registered atoms (no registration side effects).
    Matches every registered label whose gmail-hyphenized form equals the query term —
    exactly Gmail's semantics ('אינדוקס---דוחות-גיול---לטיפול' hits 'אינדוקס - דוחות גיול - לטיפול')."""
    if name.upper() in SYSTEM:
        return [name.upper()]
    reg = _load_reg(reg_path)
    hits = [a for a, rname in reg.items() if rname == name or _gmail_form(rname) == name]
    return hits or [_atom(name)]


def _query_to_criteria(reg_path, q, log=None):
    """Returns (criteria_list, post_filters:set). Supports the grammar the workflows use:
    label:/-label: (quoted or gmail-hyphenized), AND (implicit), (a OR b), has:attachment,
    is:unread, newer_than:Nd|Nm, subject:, from:/to:, in:/-in: (ignored), free text.
    Top-level OR (outside parentheses) fails LOUDLY — silently AND-ing it would make
    scanners claim the wrong mails; parenthesize instead."""
    crit, post = [], set()
    q = (q or "").replace(" AND ", " ").strip()
    for grp in _re.findall(r"\(([^()]+ OR [^()]+)\)", q):
        parts = [p.strip() for p in grp.split(" OR ")]
        acc = _term(reg_path, parts[0], post, log)
        for p in parts[1:]:
            acc = ["OR"] + acc + _term(reg_path, p, post, log)
        crit += acc
        q = q.replace("(" + grp + ")", " ")
    if _re.search(r"(^|\s)OR(\s|$)", q):
        raise ValueError("top-level OR is not supported by local mode — parenthesize: (a OR b)")
    for tok in _TOKEN.findall(q):
        crit += _term(reg_path, tok, post, log)
    return (crit or ["ALL"]), post


def _term(reg_path, tok, post, log=None):
    tok = tok.strip()
    if not tok:
        return []
    neg = tok.startswith("-")
    body = tok[1:] if neg else tok
    if body.startswith("label:"):
        atoms = _resolve_atoms(reg_path, body[6:].strip('"'))
        if atoms == ["UNREAD"]:
            return ["SEEN" if neg else "UNSEEN"]
        if atoms == ["STARRED"]:
            return ["UNFLAGGED" if neg else "FLAGGED"]
        if atoms == ["IMPORTANT"]:
            return ["UNKEYWORD", "IMPORTANT"] if neg else ["KEYWORD", "IMPORTANT"]
        if atoms == [KW_SENT]:
            # `label:SENT` is what BOTH UIs ask for when the reader opens נשלח (mailview's
            # VIEW_QUERIES, mailapi's SYSVIEW). It used to fall through to the filter below, come
            # back as [] and collapse the whole query to ALL — so the Sent view fetched the entire
            # mailbox and then found nothing in it that was labelled SENT. It is a real keyword now.
            return ["UNKEYWORD", KW_SENT] if neg else ["KEYWORD", KW_SENT]
        atoms = [a for a in atoms if a not in SYSTEM]
        if not atoms:
            return []          # single-folder model: INBOX/DRAFT etc. are not discriminating
        if neg:
            out = []
            for a in atoms:            # NOT any -> all UNKEYWORD (AND)
                out += ["UNKEYWORD", a]
            return out
        acc = ["KEYWORD", atoms[0]]
        for a in atoms[1:]:            # any -> OR chain
            acc = ["OR"] + acc + ["KEYWORD", a]
        return acc
    if body.startswith("in:"):
        return []
    if body == "has:attachment":
        post.add("neg_att" if neg else "att")
        return []
    if body == "is:unread":
        return ["SEEN" if neg else "UNSEEN"]
    m = _re.match(r"newer_than:(\d+)([dm])", body)
    if m:
        import datetime
        n, unit = int(m.group(1)), m.group(2)
        since = datetime.date.today() - datetime.timedelta(days=n * (30 if unit == "m" else 1))
        return ["SINCE", since]
    def _n(c):
        return (["NOT"] + c) if neg else c
    if body.startswith("subject:"):
        return _n(["SUBJECT", body[8:].strip('"')])
    if body.startswith("from:"):
        return _n(["FROM", body[5:].strip('"')])
    if body.startswith("to:"):
        return _n(["TO", body[3:].strip('"')])
    if _re.match(r"[a-z_]+:", body):
        # unknown gmail operator: warn loudly and skip rather than TEXT-matching the literal
        if log:
            log.warning("local search: unsupported operator %r ignored", body)
        return []
    return _n(["TEXT", body.strip('"')])


def _hdr(msg, name):
    v = msg.get(name)
    if not v:
        return ""
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
        return str(v)


def _date_of(msg, data):
    """Date header, falling back to IMAP INTERNALDATE — injected mail can be dateless."""
    v = _hdr(msg, "Date")
    if v:
        return v
    dt = data.get(b"INTERNALDATE")
    return format_datetime(dt) if dt else ""


def _bs_has_att(bs):
    try:
        if bs and not isinstance(bs[0], (bytes, bytearray)):
            return any(_bs_has_att(s) for s in bs[0] if isinstance(s, (list, tuple)))
        pp = bs[2] if len(bs) > 2 else None
        if isinstance(pp, (list, tuple)):
            for k in range(0, len(pp) - 1, 2):
                if isinstance(pp[k], (bytes, bytearray)) and pp[k].upper() == b"NAME":
                    return True
        if len(bs) > 8 and isinstance(bs[8], (list, tuple)) and bs[8]:
            d0 = bs[8][0]
            if isinstance(d0, (bytes, bytearray)) and d0.lower() == b"attachment":
                return True
    except Exception:
        pass
    return False


# Fetching a message BODY is a READ, and IMAP treats a plain RFC822/BODY[] fetch as one: the server
# sets \Seen as a side effect. Every body fetch in this backend now asks for BODY.PEEK[], which is the
# same bytes with that side effect suppressed, and the answer comes back under b"BODY[]".
#
# This was not a subtlety, it was why the mailbox had no unread mail at all. `thread()` fetches the
# body of EVERY uid in the folder to reassemble a conversation, so ONE call to /thread — which the
# reader makes when a message is opened — marked the entire mailbox read. Unread counts, bold rows and
# "select all unread" therefore only ever worked until the first message was opened, once, ever.
#
# Marking read stays where it belongs: an explicit /labels/remove UNREAD, which the reader already
# sends when a person opens a message. A machine reading mail is not a person having read it.
def _raw(data):
    return data.get(b"BODY[]") or data.get(b"RFC822") or b""


def _summary(reg_path, uid, data):
    raw = data.get(b"BODY[HEADER]") or _raw(data)
    msg = email.message_from_bytes(raw)
    bs = data.get(b"BODYSTRUCTURE")
    has_att = _bs_has_att(bs) if bs else False
    hexid = format(int(uid), "x")
    return {
        "uid": int(uid), "id": hexid, "gm_msgid": str(int(uid)), "gm_thrid": str(int(uid)),
        "threadId": hexid,
        "from": _hdr(msg, "From"), "to": _hdr(msg, "To"),
        "subject": _hdr(msg, "Subject"), "date": _date_of(msg, data),
        "labels": _decode_atoms(reg_path, data.get(b"FLAGS")),
        "hasAttachment": has_att,
    }


class BadMessageId(ValueError):
    """`id`/`ids` was not a message id. Carries the offending value so the caller can be fixed.

    MEASURED 2026-08-06: the live pipeline called POST /labels/add with
    {"id": "person52@example.com", "labelIds": ["אינדוקס - חשבונית נשמרה"]} — a MAILBOX ADDRESS
    where a hex message id belongs (`incoming_documents.SOURCE_ID` holds the sender address on 2,298
    GMAIL rows). `int(addr, 16)` raised a bare ValueError, Flask answered 500 with its default HTML
    page ("the server is overloaded or there is an error in the application"), and the defect was
    filed for two sessions as a LOAD problem. It is not load: it is one malformed argument, and it
    fails identically on an idle server. A 400 naming the value is the difference.
    """


def _uid_of(b):
    ids = b.get("ids") or ([b["id"]] if b.get("id") else [])
    if ids:
        out = []
        for g in ids:
            try:
                out.append(int(str(g), 16))
            except (TypeError, ValueError):
                raise BadMessageId(
                    "not a message id: %r — expected the hex id returned by /search or /message "
                    "(uid in hex), not an address or a name" % (g,))
        return out
    return [int(u) for u in (b.get("uids") or ([b["uid"]] if b.get("uid") else []))]


class LocalBackend:
    """One PROFILE on the private mail engine — one dovecot mailbox, addressed as its own IMAP/SMTP
    identity. There are N of these per deployment, one per profile declared in app.json (see
    profiles.py), and the credential comes from the profile's vault instance:
    `LocalBackend(user, pw)` is the same shape as `GmailBackend(user, pw)`.

    It used to be built as a bare `LocalBackend()` reading LOCALMAIL_* from the environment, which
    made the identity a property of the PROCESS — so every local instance resolved to the same
    mailbox no matter what credentials it held. The defaults below survive only as the seed the
    admin profile ADOPTS on an existing deployment; nothing resolves through them at request time.

    probe_fail_code is 500: local mode's /readyz has always answered 500 on a failed probe (it is
    healthz()'s verdict — one IMAP noop), and the compose healthcheck keys on the status code. Keep it
    here, on the adapter, so moving the mode from env-switch to selection cannot drift it.
    """

    protocol = "mail_imap_local"
    probe_fail_code = 500

    def __init__(self, user=None, password=None, imap_host=None, imap_port=None,
                 smtp_host=None, smtp_port=None, imap_ssl=None, connection_id=None):
        self.user = user or USER
        self.password = password or PW
        self.imap_host = imap_host or IMAP_HOST
        self.imap_port = int(imap_port or IMAP_PORT)
        self.imap_ssl = IMAP_SSL if imap_ssl is None else imap_ssl
        self.smtp_host = smtp_host or SMTP_HOST
        self.smtp_port = int(smtp_port or SMTP_PORT)
        # This profile's OWN label registry (see the module-level comment above LABEL_REGISTRY_DIR).
        # adapters._build passes the connection id it already resolved; nothing here re-derives it.
        self.connection_id = connection_id
        self.reg_path = _reg_path_for(connection_id)
        self._lock = threading.RLock()
        self._client = None
        self._sent_box = None              # resolved once per backend — see _sent_folder()
        self._sent_backfilled = False      # the one-time repair in _reconcile_sent()
        self.log = None                    # set by service.py so warnings land in the app logger

    def _conn(self):
        if self._client is not None:
            try:
                self._client.noop()
                return self._client
            except Exception:
                try:
                    self._client.logout()
                except Exception:
                    pass
                self._client = None
        c = IMAPClient(self.imap_host, port=self.imap_port, ssl=self.imap_ssl, timeout=30)
        c.login(self.user, self.password)
        c.capabilities()   # populate the cache — imapclient needs it before sending
                           # UTF-8 literals (Hebrew SEARCH crashes on None otherwise)
        c.select_folder("INBOX")
        self._client = c
        if not self._sent_backfilled:
            self._sent_backfilled = True   # set BEFORE running: a repair that throws must not loop
            self._reconcile_sent(c)
        return c

    def close(self):
        try:
            if self._client is not None:
                self._client.logout()
        except Exception:
            pass
        self._client = None

    def _warn(self, *a):
        if self.log:
            self.log.warning(*a)

    # ── mirror helpers (label folders) ─────────────────────────────────────────
    def _ensure_folder(self, c, name):
        try:
            if not c.folder_exists(name):
                c.create_folder(name)
            try:
                c.subscribe_folder(name)
            except Exception:
                pass
        except Exception as e:
            self._warn("mirror: ensure folder %r failed: %s", name, e)

    # ── the \Sent mailbox ──────────────────────────────────────────────────────
    #: Only reached when the server advertises NO \Sent mailbox at all. Order matters: the first of
    #: these that already EXISTS wins, and one is created only if none does.
    _SENT_FALLBACKS = ("Sent", "Sent Messages", "Sent Items")

    def _sent_folder(self, c):
        """The mailbox a mail client files an outgoing copy in — RESOLVED, never hardcoded.

        RFC 6154 lets the server name it: the mailbox carrying the \\Sent SPECIAL-USE attribute in
        LIST is the sent one, whatever it is called. That is the only answer that survives a server
        configured differently or localized, and this deployment answers it —

            (b'\\\\HasNoChildren', b'\\\\Sent') b'.' 'Sent'

        because docker-mailserver's dovecot ships `mailbox Sent { auto = subscribe; special_use =
        \\Sent }`. `auto = subscribe` is why LIST reports it while `/var/mail/<domain>/<user>/` has no
        `.Sent` directory: dovecot materializes the maildir on the first write, and until this
        function existed there was never one.

        imapclient decodes LIST names from modified-UTF-7 and re-encodes them on APPEND/SELECT, so a
        Hebrew or otherwise non-ASCII mailbox name needs no handling here — the Hebrew label folders
        on this very mailbox come back as ordinary str.
        """
        if self._sent_box:
            return self._sent_box
        name = None
        try:
            for flags, _delim, fname in c.list_folders():
                fl = {(f.decode() if isinstance(f, (bytes, bytearray)) else str(f)).lower()
                      for f in (flags or ())}
                if "\\sent" in fl:
                    name = fname if isinstance(fname, str) else fname.decode("utf-8", "replace")
                    break
        except Exception as e:
            self._warn("sent: LIST failed, falling back to a conventional name: %s", e)
        if not name:
            # No SPECIAL-USE advertised. Adopt an existing conventional mailbox rather than creating
            # a second one next to it — two Sent folders is the failure this ordering avoids.
            for cand in self._SENT_FALLBACKS:
                try:
                    if c.folder_exists(cand):
                        name = cand
                        break
                except Exception:
                    pass
        name = name or self._SENT_FALLBACKS[0]
        self._ensure_folder(c, name)
        self._sent_box = name
        return name

    def _reconcile_sent(self, c):
        """One-time repair for everything this backend sent BEFORE it learned to file a sent copy.

        Nothing was lost: every message /send submitted was archived to INBOX, just under `SENT-COPY`
        alone — a label both UIs hide as machine bookkeeping — so a mailbox holding hundreds of
        genuinely sent messages showed "לא נשלחו הודעות". The bytes being present is exactly what
        makes a backfill possible: add the keyword the views key on, and copy them into \\Sent.

        Idempotent by construction — it selects the messages carrying SENT-COPY that do NOT yet carry
        SENT, so a second run selects nothing. Best-effort: a repair must never take the connection
        it is riding on with it, so every failure is a warning and INBOX is always left selected.
        """
        n = 0
        try:
            c.select_folder("INBOX")
            uids = c.search(["KEYWORD", _atom("SENT-COPY"), "UNKEYWORD", KW_SENT])
            if not uids:
                return 0
            c.add_flags(uids, [KW_SENT, _SEEN])
            box = self._sent_folder(c)
            c.select_folder("INBOX")
            c.copy(uids, box)
            n = len(uids)
            self._warn("sent: backfilled %d archived message(s) into %r", n, box)
        except Exception as e:
            self._warn("sent: backfill failed (harmless — retried on the next connection): %s", e)
        finally:
            try:
                c.select_folder("INBOX")
            except Exception:
                pass
        return n

    def _msgids_of(self, c, uids):
        """Message-ID header per INBOX uid (INBOX must be selected)."""
        out = {}
        resp = c.fetch(uids, [b"BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)]"])
        for uid, data in resp.items():
            for k, v in data.items():
                if b"HEADER" in k and v:
                    m = _re.search(rb"<[^>]+>", v)
                    if m:
                        out[uid] = m.group(0).decode()
        return out

    def _mirror_add(self, c, uids, names):
        if not (uids and names):
            return
        c.select_folder("INBOX")
        mids = self._msgids_of(c, uids)
        for name in names:
            self._ensure_folder(c, name)
            try:
                c.select_folder(name)
                missing = [u for u in uids
                           if not (mids.get(u) and c.search(["HEADER", "Message-ID", mids[u]]))]
                c.select_folder("INBOX")
                if missing:
                    c.copy(missing, name)
            except Exception as e:
                self._warn("mirror: copy -> %r failed: %s", name, e)
                try:
                    c.select_folder("INBOX")
                except Exception:
                    pass
        c.select_folder("INBOX")

    def _mirror_sync_folder(self, c, name):
        """Make the label folder EXACTLY mirror the INBOX messages carrying its keyword.
        Deterministic + self-healing: wipe and re-copy from the source of truth, so it
        needs no per-message correlation (injected mail may lack Message-ID headers)."""
        atom = _atom(name)
        self._ensure_folder(c, name)
        try:
            c.select_folder("INBOX")
            keep = c.search(["KEYWORD", atom])
            c.select_folder(name)
            existing = c.search(["ALL"])
            if existing:
                c.delete_messages(existing)
                c.expunge()
            c.select_folder("INBOX")
            if keep:
                c.copy(keep, name)
        except Exception as e:
            self._warn("mirror: resync %r failed: %s", name, e)
            try:
                c.select_folder("INBOX")
            except Exception:
                pass

    def _mirror_remove(self, c, uids, names):
        if not names:
            return
        for name in names:
            self._mirror_sync_folder(c, name)
        c.select_folder("INBOX")

    # ── health ─────────────────────────────────────────────────────────────────
    def healthz(self):
        try:
            with self._lock:
                self._conn().noop()
            return {"status": "ok", "user": self.user, "mode": "local"}, 200
        except Exception as e:
            return {"status": "error", "error": f"{type(e).__name__}: {e}"}, 500

    def probe(self):
        # Identical pass/fail to healthz() (an IMAP noop; 200 ok / 500 error) — the compose healthcheck
        # requires BOTH /healthz and /readyz to be 200, so the codes here must not move.
        return self.healthz()

    def stats(self):
        up = max(1.0, time.time() - _START)
        return {"uptime_s": round(up), "commands_total": sum(_cmd_stats.values()),
                "cmds_per_min": round(sum(_cmd_stats.values()) / (up / 60), 1),
                "by_command": dict(_cmd_stats.most_common()), "mode": "local"}

    def stats_reset(self):
        _cmd_stats.clear()
        return {"ok": True}

    # ── ops ────────────────────────────────────────────────────────────────────
    def search(self, b):
        """See app.py::GmailBackend.search for the `since_uid`/`uidvalidity`/`uidnext` contract this
        mirrors — this local (dovecot) backend is the deterministic CI/e2e stand-in for the Gmail one,
        so the two must agree on the incremental-sync primitive or a test against `local` would prove
        nothing about the real path."""
        limit = int(b.get("limit", 50))
        since = int(b.get("since_uid") or 0)
        before = int(b.get("before_uid") or 0)
        since_ts = b.get("since_ts")
        since_ts = float(since_ts) if since_ts not in (None, "") else None
        with self._lock:
            c = self._conn()
            c.select_folder("INBOX")
            status = c.folder_status("INBOX", ["UIDVALIDITY", "UIDNEXT"])
            uidvalidity = status.get(b"UIDVALIDITY", status.get("UIDVALIDITY"))
            uidnext = status.get(b"UIDNEXT", status.get("UIDNEXT"))
            if b.get("query"):
                try:
                    crit, post = _query_to_criteria(self.reg_path, b["query"], self.log)
                except ValueError as e:
                    return {"error": str(e), "query": b["query"]}, 400
            else:
                crit, post = list(b.get("criteria") or ["ALL"]), set()
            if since:
                crit = crit + ["UID", "%d:*" % (since + 1)]
            if since_ts is not None:
                # Stage 1, same shared helper the Gmail backend uses — see app.py.
                crit = crit + ["SINCE", imap_since_date(since_ts)]
            uids = c.search(crit, charset="UTF-8")
            uids = sorted(uids)
            if since:
                # Same zero-cost correctness net as app.py::GmailBackend.search, proven necessary
                # there against real Gmail (RFC 3501's UID-range clamp maps a lower bound beyond the
                # mailbox's largest UID down to that largest UID instead of matching nothing — so the
                # server-side term alone can hand back an already-seen message on a "nothing new"
                # pass). Applied here too so `local` stays a faithful stand-in for the real contract
                # rather than one that happens not to need the guard.
                uids = [u for u in uids if u > since]
            candidates = uids                 # the widened window, before paging
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
                resp = c.fetch(uids, [b"BODY.PEEK[HEADER]", b"FLAGS", b"BODYSTRUCTURE", b"INTERNALDATE"])
                for uid in uids:
                    data = resp.get(uid)
                    if not data:
                        continue
                    if since_ts is not None:
                        # Stage 2, on the fetch we already do — see app.py::GmailBackend.search for
                        # the measurement that put it here rather than in a pass of its own.
                        dt = data.get(b"INTERNALDATE")
                        if dt is not None and dt.timestamp() < since_ts:
                            continue
                    s = _summary(self.reg_path, uid, data)
                    if "att" in post and not s["hasAttachment"]:
                        continue
                    if "neg_att" in post and s["hasAttachment"]:
                        continue
                    out.append(s)
                    kept.append(uid)
            if since_ts is not None:
                # Same rule as the Gmail backend, and see its comment for the measurement that ruled
                # out the cheaper UID-order arithmetic: exact only when the whole candidate set was
                # fetched on a first page, otherwise a labelled upper bound.
                if not before and len(candidates) <= limit:
                    total = len(kept)
                else:
                    total = len(candidates)
        _cmd_stats["search"] += 1
        self._warn("SEARCH q=%r crit=%r -> uids=%s", (b.get("query") or b.get("criteria")), None, [m["uid"] for m in out])
        return {"messages": out, "count": len(out), "total": total,
                "has_more": has_more, "next_cursor": next_cursor,
                "uidvalidity": uidvalidity, "uidnext": uidnext}

    def _message_meta(self, uid):
        """Metadata-only /message — the same contract the Gmail backend's `meta=true` branch keeps:
        BODYSTRUCTURE + headers + the text parts, NEVER the attachment bytes. This backend used to
        serve meta by fetching the full BODY.PEEK[] and merely omitting `data_base64` from the JSON,
        so every reader open still moved the whole multi-MB MIME from dovecot into this process and
        parsed it — the exact cost the meta mechanism exists to avoid, paid inside the one lock every
        local op shares. Attachment `size` is now the BODYSTRUCTURE estimate and `content_id` is
        absent, exactly as on the Gmail meta path — a meta caller could never rely on either across
        backends. The caller falls back to the full fetch on any error, same as Gmail's."""
        with self._lock:
            c = self._conn()
            c.select_folder("INBOX")
            resp = c.fetch([uid], [b"BODYSTRUCTURE", b"BODY.PEEK[HEADER]", b"FLAGS", b"INTERNALDATE"])
            if uid not in resp:
                return {"error": "not found"}, 404
            data = resp[uid]
            leaves = _bs_leaves(data.get(b"BODYSTRUCTURE")) if data.get(b"BODYSTRUCTURE") else []
            text_leaves = [l for l in leaves if not l["is_att"] and l["type"] == "text"]
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
        msg = email.message_from_bytes(data.get(b"BODY[HEADER]") or b"")
        atts = [{"filename": l["filename"] or "attachment",
                 "mimeType": f"{l['type']}/{l['subtype']}", "size": l["size"]}
                for l in leaves if l["is_att"]]
        hexid = format(int(uid), "x")
        _cmd_stats["fetch"] += 1
        return {"uid": int(uid), "id": hexid, "gm_msgid": str(int(uid)), "gm_thrid": str(int(uid)),
                "threadId": hexid,
                "from": _hdr(msg, "From"), "to": _hdr(msg, "To"),
                "subject": _hdr(msg, "Subject"), "date": _date_of(msg, data),
                "labels": _decode_atoms(self.reg_path, data.get(b"FLAGS")),
                "body_text": body_text, "body_html": body_html, "attachments": atts, "meta": True}

    def message(self, uid, args, log=None):
        gid = args.get("id")
        if gid:
            uid = int(gid, 16)
        want_att = args.get("attachments", "true") == "true"
        meta = args.get("meta") == "true"
        if meta:
            try:
                return self._message_meta(uid)
            except Exception as e:
                self._warn("meta fetch failed (uid=%s): %r; falling back to full fetch", uid, e)
        with self._lock:
            c = self._conn()
            c.select_folder("INBOX")
            resp = c.fetch([uid], [b"BODY.PEEK[]", b"FLAGS", b"INTERNALDATE"])
            if uid not in resp:
                return {"error": "not found"}, 404
            data = resp[uid]
        msg = email.message_from_bytes(_raw(data))
        body_text, body_html, atts = "", "", []
        for part in (msg.walk() if msg.is_multipart() else [msg]):
            ct = part.get_content_type()
            disp = part.get_content_disposition()
            fn = part.get_filename()
            if fn or disp == "attachment":
                payload = part.get_payload(decode=True) or b""
                # `content_id` is what tells an EMBEDDED image apart from a real attachment: Gmail
                # sends its notification logo as Content-Disposition ATTACHMENT with a Content-ID
                # the HTML references as <img src="cid:...">, so disposition alone cannot classify
                # it. Reported raw — this service says what the message contains, and the caller
                # decides what it means. Only the full walk has it; the BODYSTRUCTURE meta path
                # cannot see Content-ID and omits the key rather than guessing, so ABSENT means
                # unknown and never "not embedded".
                a = {"filename": str(make_header(decode_header(fn))) if fn else "attachment",
                     "mimeType": ct, "size": len(payload),
                     "content_id": (part.get("Content-ID") or "").strip("<> ")}
                if want_att and not meta:
                    a["data_base64"] = base64.b64encode(payload).decode()
                atts.append(a)
            elif ct == "text/plain" and not body_text:
                body_text = decode_part(part)
            elif ct == "text/html" and not body_html:
                body_html = decode_part(part)
        hexid = format(int(uid), "x")
        out = {"uid": uid, "id": hexid, "gm_msgid": str(uid), "gm_thrid": str(uid), "threadId": hexid,
               "from": _hdr(msg, "From"), "to": _hdr(msg, "To"),
               "subject": _hdr(msg, "Subject"), "date": _date_of(msg, data),
               "labels": _decode_atoms(self.reg_path, data.get(b"FLAGS")),
               "body_text": body_text, "body_html": body_html, "attachments": atts}
        if meta:
            out["meta"] = True
        _cmd_stats["fetch"] += 1
        return out

    def thread(self, tid, args=None, log=None):
        """The conversation a message belongs to.

        GreenMail has no X-GM-THRID, so there is nothing to ask the server for — local mode has to
        reconstruct the thread. It does it the way mail clients did before Gmail: RFC 5322
        `Message-ID` / `In-Reply-To` / `References`, falling back to a normalised subject when a
        sender strips those (many do).

        This is deliberately honest about being an approximation: it will group a reply chain
        correctly, and it will group two unrelated mails that share a subject line. Gmail's own
        threading makes the same trade.
        """
        args = args or {}
        want_bodies = str(args.get("bodies", "true")).lower() != "false"
        try:
            uid = int(str(tid), 16)
        except ValueError:
            try:
                uid = int(tid)
            except ValueError:
                return {"error": "bad thread id"}, 400

        def norm_subject(v):
            v = (v or "").strip()
            while True:
                low = v.lower()
                for p in ("re:", "fw:", "fwd:", "תשובה:", "העברה:"):
                    if low.startswith(p):
                        v = v[len(p):].strip()
                        break
                else:
                    return v.lower()

        with self._lock:
            c = self._conn()
            c.select_folder("INBOX")
            resp = c.fetch([uid], [b"BODY.PEEK[]", b"FLAGS", b"INTERNALDATE"])
            if uid not in resp:
                return {"error": "not found"}, 404
            seed = email.message_from_bytes(_raw(resp[uid]))
            seed_subject = norm_subject(_hdr(seed, "Subject"))
            # The thread's identity: every Message-ID it references, plus its own.
            ids = set()
            for h in ("Message-ID", "In-Reply-To"):
                v = (seed.get(h) or "").strip()
                if v:
                    ids.add(v)
            ids.update((seed.get("References") or "").split())

            # Membership is decided from HEADERS ONLY, then bodies are fetched for the members
            # alone. This used to fetch BODY.PEEK[] for every UID in the folder — the linker reads
            # nothing but Message-ID/In-Reply-To/References/Subject, so reassembling one
            # conversation moved the ENTIRE mailbox (attachments included) from dovecot into this
            # process, inside the one lock every local op shares. On a mailbox of thousands of
            # documents that made "open a message" an O(mailbox-bytes) operation; the reader calls
            # /thread on every open. Same pick predicate, same response — only the bytes moved
            # change.
            all_uids = sorted(c.search(["ALL"]))
            _HDRS = b"BODY.PEEK[HEADER.FIELDS (MESSAGE-ID IN-REPLY-TO REFERENCES SUBJECT)]"
            hdrs = c.fetch(all_uids, [_HDRS]) if all_uids else {}
            member_uids = []
            for u in sorted(hdrs):
                raw = b""
                for k, v in hdrs[u].items():   # response key mirrors the request key minus .PEEK
                    if b"HEADER" in k and v:
                        raw = v
                        break
                m = email.message_from_bytes(raw)
                mid = (m.get("Message-ID") or "").strip()
                refs = set((m.get("References") or "").split())
                irt = (m.get("In-Reply-To") or "").strip()
                if irt:
                    refs.add(irt)
                linked = bool(ids & (refs | ({mid} if mid else set()))) or u == uid
                if linked or norm_subject(_hdr(m, "Subject")) == seed_subject:
                    member_uids.append(u)
            members = c.fetch(member_uids, [b"BODY.PEEK[]", b"FLAGS", b"INTERNALDATE"]) if member_uids else {}

        picked = []
        for u in sorted(members):
            data = members[u]
            picked.append((u, data, email.message_from_bytes(_raw(data))))

        messages = []
        for u, data, m in picked:
            body_text, body_html, atts = "", "", []
            for part in (m.walk() if m.is_multipart() else [m]):
                ct = part.get_content_type()
                fn = part.get_filename()
                if fn or part.get_content_disposition() == "attachment":
                    payload = part.get_payload(decode=True) or b""
                    a = {"filename": str(make_header(decode_header(fn))) if fn else "attachment",
                         "mimeType": ct, "size": len(payload),
                         "content_id": (part.get("Content-ID") or "").strip("<> ")}
                    if want_bodies:
                        a["data_base64"] = base64.b64encode(payload).decode()
                    atts.append(a)
                elif ct == "text/plain" and not body_text:
                    body_text = decode_part(part)
                elif ct == "text/html" and not body_html:
                    body_html = decode_part(part)
            hexid = format(int(u), "x")
            messages.append({
                "uid": int(u), "id": hexid, "gm_msgid": str(int(u)), "gm_thrid": format(uid, "x"),
                "threadId": format(uid, "x"),
                "from": _hdr(m, "From"), "to": _hdr(m, "To"),
                "subject": _hdr(m, "Subject"), "date": _date_of(m, data),
                "labels": _decode_atoms(self.reg_path, data.get(b"FLAGS")),
                "body_text": body_text, "body_html": body_html, "attachments": atts,
            })
        messages.sort(key=lambda x: x["uid"])
        first = messages[0] if messages else {}
        _cmd_stats["fetch"] += 1
        return {
            "threadId": format(uid, "x"), "gm_thrid": str(uid), "count": len(messages),
            "messages": messages,
            # Flattened for the label-engine rules, which read thread.from / thread.text directly.
            "from": first.get("from", ""), "subject": first.get("subject", ""),
            "text": first.get("body_text", "") or "",
        }

    def labels_add(self, b):
        raw = _labels_from(b)
        _kw_raw, sys_flags = _split_flag_labels(raw)
        labels = [_reg_label(self.reg_path, l) for l in _kw_raw]
        labels = [l for l in labels if l and l not in SYSTEM]
        labels += sys_flags
        try:
            uids = _uid_of(b)
        except BadMessageId as e:
            return {"ok": False, "error": str(e)}, 400
        with self._lock:
            c = self._conn()
            c.select_folder("INBOX")
            if uids and labels:
                c.add_flags(uids, labels)
                self._mirror_add(c, uids, _human_labels(b))
            # marking UNREAD is CLEARING \Seen — the one label whose add is a flag removal
            if uids and _wants_unread(raw):
                c.remove_flags(uids, [_SEEN])
        _cmd_stats["store"] += 1
        self._warn("LABEL+ uids=%s labels=%r", uids, _labels_from(b))
        # `remove` — the same optional list the Gmail backend honours (2026-09-03): the sync's
        # source feedback takes the to-sync label off in the call that adds the outcome label.
        # Runs after the lock above is released; labels_remove takes it again.
        remove = [str(x) for x in (b.get("remove") or []) if str(x).strip() and str(x) not in raw]
        removed = []
        if uids and remove:
            self.labels_remove({k: v for k, v in b.items() if k not in ("labels", "label", "labelIds", "remove")} | {"labels": remove})
            removed = remove
        return {"ok": True, "uids": uids, "added": _labels_from(b), "removed": removed}

    def labels_remove(self, b):
        raw = _labels_from(b)
        _kw_raw, sys_flags = _split_flag_labels(raw)
        labels = [_reg_label(self.reg_path, l) for l in _kw_raw]
        labels = [l for l in labels if l and l not in SYSTEM]
        labels += sys_flags
        try:
            uids = _uid_of(b)
        except BadMessageId as e:
            return {"ok": False, "error": str(e)}, 400
        with self._lock:
            c = self._conn()
            c.select_folder("INBOX")
            if uids and labels:
                c.remove_flags(uids, labels)
                self._mirror_remove(c, uids, _human_labels(b))
            # …and removing UNREAD is SETTING \Seen. This is what "open a message" writes.
            if uids and _wants_unread(raw):
                c.add_flags(uids, [_SEEN])
        _cmd_stats["store"] += 1
        self._warn("LABEL- uids=%s labels=%r", uids, _labels_from(b))
        return {"ok": True, "uids": uids, "removed": _labels_from(b)}

    def labels_list(self):
        reg = _load_reg(self.reg_path)
        return {"labels": sorted(set(reg.values())) + sorted(SYSTEM)}

    def labels_create(self, b):
        _reg_label(self.reg_path, b["name"])
        if str(b["name"]).upper() not in SYSTEM:
            with self._lock:
                self._ensure_folder(self._conn(), b["name"])
        return {"ok": True, "name": b["name"]}

    # `labels_rebuild` (POST /labels/rebuild) and `labels_delete` (POST /labels/delete) were removed
    # 2026-09-02 (RELEASE-DECISIONS N12): zero callers anywhere in the tree. The per-label mirror
    # resync they shared (`_mirror_sync_folder`) stays — `labels_remove` still uses it.

    def append(self, b):
        """Same contract as gmail mode: {raw_base64?|raw?, labels?:[names], folder?, flags?}."""
        raw = base64.b64decode(b["raw_base64"]) if b.get("raw_base64") else b["raw"].encode()
        msg = email.message_from_bytes(raw)
        changed = False
        if not msg.get("Date"):          # keep local mail well-formed regardless of caller
            msg["Date"] = formatdate(localtime=True)
            changed = True
        if not msg.get("Message-ID"):    # mirror correlation + threading need one
            # Same derivation as /send: the deployment's mail domain, not a literal. "local.test"
            # was right on a laptop and wrong on every real deployment.
            msg["Message-ID"] = make_msgid(domain=_domain)
            changed = True
        if changed:
            raw = msg.as_bytes()
        atoms = [a for a in (_reg_label(self.reg_path, l) for l in _labels_from(b)) if a and a not in SYSTEM]
        with self._lock:
            c = self._conn()
            resp = c.append("INBOX", raw, flags=atoms + list(b.get("flags") or []))
            uid = None
            m = _re.search(rb"APPENDUID\s+\d+\s+(\d+)", resp if isinstance(resp, (bytes, bytearray)) else str(resp).encode())
            if m:
                uid = int(m.group(1))
            if uid:
                self._mirror_add(c, [uid], _human_labels(b))
        _cmd_stats["append"] += 1
        return {"ok": True, "uid": uid, "id": format(uid, "x") if uid else None}

    def send(self, b):
        """{to, subject, body_text?|body_html?, attachments?:[{filename,mimeType,data_base64}]}
        — sent via local SMTP, archived to INBOX under the SENT keyword (what the API and both UIs
        read), and, when the send actually succeeded, APPENDed to the \\Sent mailbox (what every
        real IMAP client reads)."""
        from email.message import EmailMessage
        m = EmailMessage()
        m["From"] = SMTP_FROM or self.user
        m["To"] = b.get("to", self.user)
        m["Subject"] = b.get("subject", "")
        m["Date"] = formatdate(localtime=True)
        # Message-ID is NOT optional. RFC 5322 lists it as SHOULD, but the receivers that matter
        # treat it as MUST: Google answers a message without one with
        #     550 5.7.1 Messages missing a valid Message-ID header are not accepted
        # so a send path that omits it is a send path Gmail can refuse outright. Nothing downstream
        # supplied it either — Postfix only synthesises missing headers under conditions this
        # submission does not meet — and the omission was invisible from here, showing up only as
        # `message-id=<>` in the postfix cleanup log.
        #
        # The right-hand side is the deployment's own mail domain (same MAIL_DOMAIN the mailbox
        # address is derived from), never a literal: a Message-ID whose domain is not ours is at
        # best useless for correlation and at worst looks forged. make_msgid() supplies the
        # uniqueness (time + pid + randomness) so nothing here has to invent it.
        m["Message-ID"] = make_msgid(domain=_domain)
        if b.get("body_html"):
            m.set_content(b.get("body_text") or " ")
            m.add_alternative(b["body_html"], subtype="html")
        else:
            m.set_content(b.get("body_text") or "")
        for a in b.get("attachments") or []:
            data = base64.b64decode(a.get("data_base64") or "")
            mt = (a.get("mimeType") or "application/octet-stream").split("/")
            m.add_attachment(data, maintype=mt[0], subtype=mt[-1], filename=a.get("filename") or "attachment")
        raw = m.as_bytes()
        err = None
        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30) as S:
                if SMTP_MODE == "relay":
                    if SMTP_STARTTLS:
                        S.starttls()
                    if SMTP_USER:
                        S.login(SMTP_USER, SMTP_PW)
                S.send_message(m)
            sent_via = "smtp"
        except Exception as e:
            sent_via = "archive-only"
            err = f"{type(e).__name__}: {e}"
        with self._lock:
            c = self._conn()
            # Copy 1 — INBOX + keywords, because that is this backend's whole data model (see the
            # module docstring): the HTTP API only ever selects INBOX, so a message that is not here
            # cannot be searched, opened or listed at all. `SENT` is the keyword every Sent view
            # keys on; `SENT-COPY` stays alongside it because it is what the existing archive is
            # tagged with and what both UIs' isMachineLabel rule already knows to hide.
            c.append("INBOX", raw, flags=[_SEEN, KW_SENT, _reg_label(self.reg_path, "SENT-COPY")])
            # Copy 2 — the \Sent mailbox, because SMTP submission files nothing. Handing a message to
            # an MTA delivers it to the RECIPIENT; putting a copy in the sender's Sent folder has
            # always been the client's job, done with exactly this IMAP APPEND. Without it postfix
            # logs `status=sent` for hundreds of messages while the maildir has no Sent directory at
            # all — which is what any real mail client (Thunderbird, Roundcube, a phone) reads.
            #
            # Only on success: a message the MTA refused was never sent, and filing it under \Sent
            # would be a lie told to every client that opens the folder. \Seen because a message you
            # wrote yourself is not unread, and INTERNALDATE=now so it sorts as just-sent.
            if err is None:
                try:
                    box = self._sent_folder(c)
                    c.append(box, raw, flags=[_SEEN], msg_time=datetime.datetime.now())
                except Exception as e:
                    # The message DID go out. A failed archive must not turn that into an error.
                    self._warn("sent: APPEND to %r failed: %s", self._sent_box, e)
                finally:
                    c.select_folder("INBOX")
        _cmd_stats["send"] += 1

        # Report what HAPPENED, not what was attempted. `ok` means the request succeeded; `delivered`
        # answers "did it go anywhere", and is never optimistic:
        #   queued  — a real MTA accepted responsibility. That is the strongest promise SMTP allows;
        #             final delivery is asynchronous and shows up in the mail log, not here.
        #   no      — the MTA refused it. The copy archived to INBOX is the only trace.
        # There is no longer a third case where we accepted a message that was never going anywhere:
        # that was GreenMail, and removing it is what makes "queued" true rather than hopeful.
        out = {"ok": err is None, "via": sent_via, "mode": SMTP_MODE}
        if err:
            out.update({"delivered": "no", "error": err,
                        "detail": "שרת הדואר דחה את ההודעה. עותק נשמר בתיבה."})
        else:
            out.update({"delivered": "queued",
                        "detail": "התקבל אצל שרת הדואר להעברה. מסירה סופית מתועדת ביומן הדואר."})
        return out
