"""The mail service (:8970) — routes only. One process, every protocol.

Each request resolves the backend from the SELECTED connection (adapters.resolve_active) instead of
from a process-wide GMAIL_IMAP_MODE decided at container start. The route table, the request bodies
and the response payloads are byte-for-byte what they were: n8n's gmailApiImap01 and mailview call
these paths and must keep working with no change (contract §3 — "this refactor moves ownership, not
schemas").

Every op accepts an optional `connection_id` (in the JSON body; a query param on the GET) to override
the active pointer for that one call — the contract's per-call override.

CANONICAL OPS NOW REQUIRE THAT OVERRIDE — it is no longer optional for the nine routes that act on
mail (search/message/thread/labels·add·remove·create/append/send).
See `_explicit_connection_required` below for why, and for why this is
DELIBERATELY BROADER than the identical fix on the drive side: `apps/drive/app.py`'s
`_explicit_connection_required` exempts its own `/api/*` UI plane ("the SSO session is the
authentication and the binding is the identity") — that exemption does NOT apply here. The owner
overrode it explicitly for mail: a "selected connection" may exist as a UI convenience, but even a
UI-triggered action must pass it as an explicit second call, never have it resolved implicitly inside
the op. `/healthz`, `/readyz`, `/stats`, `/connections/<cid>/probe`, `/setup/status` and the
connection-MANAGEMENT surface (`/connections*`, `/engine/profiles*`, `/mailboxes*`) are unaffected —
they report or manage the ambient pointer itself rather than acting on mail on its behalf, which is
exactly the distinction `/readyz`'s own docstring already draws ("ready = the ACTIVE connection
resolves").

`/organizer/settings` IS EXEMPT, and this docstring used to say it was not — the claim was wrong
about its own code and is corrected here rather than left standing (2026-08-09). That route never
calls `_backend`, never opens an IMAP connection and never reads or writes a message: with no
`connection_id` it serves the mail-scoped DEFAULTS singleton (`options.get_defaults()`), which is a
real document in its own right, NOT the active connection's options. So there is no wrong-mailbox
failure mode to close there — the whole hazard this module guards against is "an op silently ran
against whichever account the shared `/data/active.json` pointer named", and a route that resolves
to a named defaults document instead of to the pointer cannot exhibit it. Requiring an id there
would only break `mailLabelEngine01`'s three `Load Settings` nodes for no safety gain. What DOES
still apply to the organiser is that every op it then drives (`/labels/*`, `/search`, `/message`)
goes through the guard below, so a rule set loaded from defaults still cannot be applied to a
mailbox nobody named.

WIRING NOTE (2026-08-09): `require_explicit` existed, was fully documented, and was passed by ZERO
of the nineteen `_backend(` call sites — the guard was dead code and every canonical op still fell
through to the active pointer. Every call site below now passes the flag EXPLICITLY, True or False,
so "this route was considered" is visible at the call site and a newly added route cannot inherit
the unsafe default by omission.

ONE MAIL CLIENT (RELEASE-DECISIONS N12, 2026-09-02): this service no longer serves a browser client.
`static/`, `GET /` (ui_index), `/ui/unread` and `/ui/attachment` are gone with it, as are the
zero-caller planes `/connections/<cid>/options`, `/organizer/effective/<cid>`, `/labels/delete` and
`/labels/rebuild`. mailview is the UI; it calls the same op routes n8n does. The three screens the
old client had that mailview did not — mailbox creation (`/mailboxes`), DNS/DKIM setup status
(`/setup/status`) and the guided provider connect (`/providers`, `/connections/<cid>/probe`) — keep
their endpoints here, unchanged, for mailview to drive.
"""
import os

from flask import Flask, request, jsonify
from werkzeug.exceptions import HTTPException

import adapters
import app as gmail_backend
import connections_client as cc
import extensions
import mailboxes
import mailsetup
import options
import profiles
from connections_api import bp as connections_bp

# No static folder at all: the op paths live at the root (/search, /labels, …) and n8n owns them —
# there is no asset route left that could shadow one (the client that needed it was retired, N12).
app = Flask(__name__, static_folder=None)
app.register_blueprint(connections_bp)

# The engine bootstrap (ai/context/app-engine-pattern.md §6). Every profile apps/mail/app.json
# declares becomes a real dovecot mailbox AND a real vault instance, idempotently, on a fresh or an
# existing machine. In-process and with direct access to mailboxd — which is what resolves the
# chicken-and-egg the admin ring would otherwise have (you need an admin credential to create a
# profile; you need this to get the first one).
profiles.start()

CONNECTIONS_PUBLIC_URL = os.environ.get("CONNECTIONS_PUBLIC_URL", "https://connections.localhost").rstrip("/")


def _reply(r):
    """Backends return a payload, or (payload, status). One place to turn either into a response, so
    an op's status code is the backend's decision and nothing in the routing layer can reshape it."""
    if isinstance(r, tuple):
        return jsonify(r[0]), r[1]
    return jsonify(r)


def _body():
    return request.get_json(force=True, silent=True) or {}


def _explicit_connection_required():
    """Raise the actionable 400 for a canonical-op call that named no connection at all.

    2026-08-07, owner mandate: "we always should act on behalf of a specific connection, no
    default/fallback etc inside the api... every workflow acting on mail should know on which
    connection it's working on... no fallbacks or so-called selected connection at mail app level.
    we might have a selected connection but even then it's two separate calls — one to get the
    selected connection, one to act — never act blindly."

    That is the drive `_explicit_connection_required` incident (2026-08-06) again, one layer over:
    there, a MISSING id resolved silently to whatever the console happened to be bound to; here, the
    ambient pointer (`/data/active.json`) is a SHARED file — flipped by a human clicking the account
    bar and by any test run that needs a different mailbox. Measured live 2026-08-07: the label
    engine's own access log showed `GET /thread/<id>?connection_id=` and `GET /message/0?...&
    connection_id=` with the value EMPTY, and separately, a sync pipe named `mail-private` had been
    reading the CLIENT's Gmail because a dead registry id silently remapped onto whatever the pointer
    named. Neither call errored. A mail op against the wrong mailbox does not fail — it returns
    someone else's mail, or nothing, and an unattended pipeline treats that as ground truth.

    UNLIKE drive's version of this function, there is NO UI-plane exemption here — the owner
    considered and explicitly overruled it: "no fallbacks or so-called selected connection at mail
    app level... even then it's two separate calls." A browser-triggered action refuses exactly like
    an n8n workflow's. What the UI keeps is the CONVENIENCE of a selected connection (the account
    bar, `GET /connections` -> `active`) — it just has to pass that id back explicitly on the next
    call rather than have this service infer it, which is the "two separate calls" shape stated
    above. See `ai/context/...` mail-architecture map for the audit that inventoried every call site
    this closes.
    """
    conns = cc.list_instances()
    if conns:
        rows = "\n".join(
            f"    - connection_id={c.get('id')!r}  ({c.get('protocol')}, {c.get('label')})"
            for c in conns)
    else:
        rows = "    (none configured yet — the engine profile reconciler may still be provisioning)"
    raise adapters.AdapterError(
        "mail: this operation requires an explicit `connection_id` — none was passed. The "
        "deployment's active connection pointer (/data/active.json) is no longer used as an "
        "implicit default for ANY caller, UI included: it is a convenience for choosing which id "
        "to pass, not a fallback for omitting it. Read the selected connection first "
        "(`GET /connections` -> `active`), then pass that id explicitly on this call.\n"
        f"Available connections:\n{rows}",
        status=400, connection_id=None)


def _backend(connection_id=None, *, require_explicit):
    """The backend for this request. AdapterError (unknown id, unusable secret, vault down with
    nothing cached) is turned into its own status by _handle_adapter_error below.

    `require_explicit` is set by every canonical-op route (the nine mail actions) — see
    `_explicit_connection_required` for why. Routes that report on or
    manage the ambient pointer itself (`/healthz`, `/readyz`, `/stats`, and anything under
    `/connections*`/`/engine/profiles*`/`/mailboxes*`) pass False on purpose: those are not "act on
    mail on someone's behalf" calls.

    THE FLAG HAS NO DEFAULT, AND THAT IS THE FIX. It used to default to False, and the failure that
    followed was not a wrong decision at any call site — it was nineteen call sites that never made
    one. The parameter was written, documented, and referenced by this module's own docstring as
    "set by every canonical-op route" while not one caller passed it, so the guard read as live in
    review and was inert in production for two days (2026-08-07 → 2026-08-09), during which the
    suites deposited 148 test messages into the client's real Gmail. Keyword-only and mandatory
    means a route that forgets to decide raises TypeError on its first request instead of quietly
    inheriting the permissive answer: a new route cannot re-open this hole by omission, which is
    exactly how it was opened."""
    # An id that is present-but-empty is ABSENT, and this is not defensive tidying — it is the exact
    # shape the 2026-08-07 measurement caught in the label engine's access log: `?connection_id=`
    # and `&connection_id=`, the value empty. n8n renders an unresolved `={{ ... }}` to the empty
    # string (and, for a missing object key in a template literal, to "undefined"/"null"), so a
    # caller that MEANT to pass an id and got the expression wrong presents one of these. Normalising
    # them to None routes that caller to the actionable 400 naming the available connections, rather
    # than to the ambient pointer (empty string) or to a baffling 404 for a connection literally
    # named "undefined". Applied before the check so both branches see the same normalised value.
    if isinstance(connection_id, str):
        connection_id = connection_id.strip()
        if connection_id.lower() in ("", "undefined", "null", "none"):
            connection_id = None
    if require_explicit and not connection_id:
        _explicit_connection_required()
    cid, be = adapters.resolve_active(connection_id)
    be.log = app.logger          # backends warn through the service's logger, not their own
    return cid, be


@app.errorhandler(adapters.AdapterError)
def _handle_adapter_error(e):
    # A connection that cannot be resolved is a CONFIG fault, not a mail fault: say which connection
    # and why, so the console can render an actionable state chip rather than a 500.
    #
    # `connection_id` is the one that FAILED, which is not always the active one — every op takes a
    # per-call override, and this used to report cc.active() unconditionally. Sending through a
    # broken Gmail account answered with the LOCAL mailbox's id beside a message naming the Gmail
    # one: two accounts in one response, and the machine-readable field pointing at the innocent one.
    # Falling back to the active pointer only when the error genuinely has no connection attached.
    return jsonify({
        "error": str(e),
        "connection_id": e.connection_id or cc.active() or cc.default_id(),
    }), e.status


@app.errorhandler(profiles.ProfileError)
def _handle_profile_error(e):
    """An authorization or ring refusal from the ENGINE (§4). It is here and not in the UI on
    purpose: a rule the browser enforces is a rule n8n and curl do not have."""
    return jsonify({"ok": False, "error": str(e)}), e.status


@app.errorhandler(gmail_backend.MailboxBusy)
def _handle_mailbox_busy(e):
    """N11: an interactive read waited its bound for the mailbox's one IMAP connection and it was
    still held (a 300 s sync fetch, say). 503 with WHAT holds it and for how long, so the client can
    say "the mailbox is busy with a sync fetch — try again" instead of timing out at its proxy.
    `Retry-After` because a busy mailbox is exactly the case the header exists for."""
    resp = jsonify(e.payload())
    resp.headers["Retry-After"] = "5"
    return resp, 503


@app.errorhandler(Exception)
def _handle_unexpected(e):
    """Anything not already handled answers as JSON, naming itself.

    [g3 2026-08-09] Only the two handlers above existed, so every OTHER exception fell through to
    Flask's stock 265-byte HTML error page. n8n's `http:get` then surfaced `500 - "<!doctype html>
    <html lang=en><title>500 Internal Server Error</title>…"` and the real cause
    (`LookupError: unknown encoding: iso-8859-8-i`, app.py `decode_part`) was visible only in this
    container's log — the exact "an upstream error returned as HTML and swallowed opaquely" class
    the mailview half was fixed for today. The fix for that particular decode is in app.py; THIS is
    the guarantee that the next unforeseen one is legible from the caller instead of needing a log
    dive, and it changes no successful response.

    HTTPException (404/405/413/…) keeps its own status and description — Flask's abort() must not
    be reshaped into a 500.
    """
    if isinstance(e, HTTPException):
        return jsonify({"ok": False, "error": e.description, "status": e.code}), e.code
    app.logger.exception("unhandled exception on %s %s", request.method, request.path)
    return jsonify({
        "ok": False,
        "error": "%s: %s" % (type(e).__name__, e),
        "type": type(e).__name__,
        "path": request.path,
    }), 500


# ── per-request IMAP command attribution (Gmail /stats) ────────────────────────
@app.before_request
def _stats_begin():
    from flask import g
    g._cmds = 0


@app.after_request
def _stats_end(resp):
    try:
        from flask import g
        ep = request.url_rule.rule if request.url_rule else request.path
        gmail_backend._ep_cmds[ep] += getattr(g, "_cmds", 0)
        gmail_backend._ep_hits[ep] += 1
    except Exception:
        pass
    return resp


# ── health ─────────────────────────────────────────────────────────────────────
@app.get("/healthz")
def healthz():
    _cid, be = _backend(require_explicit=False)
    return _reply(be.healthz())


@app.get("/readyz")
def readyz():
    """§2: ready = the active connection resolves AND its adapter probe passes.

    ⚠ The compose healthcheck keys on the STATUS CODE (it requires 200 from both /healthz and
    /readyz), and the PROBE failure code is the ADAPTER's: 503 for a Gmail account (unreachable
    upstream), 500 for the local mailbox — exactly what each mode answered before selection existed.
    The codes live on the backend classes (probe_fail_code) so routing cannot drift them.

    A connection that cannot be RESOLVED at all is a different failure and answers 503 with the
    reason: there is no adapter, so there is no adapter code to use, and there must be no probe of
    some other account standing in for the selected one. `connection_id` is only ever the id we
    actually probed — never a fallback the caller did not choose."""
    try:
        cid, be = _backend(require_explicit=False)
    except adapters.AdapterError as e:
        return jsonify({"ready": False, "reason": str(e), "connection_id": None,
                        "active": cc.active()}), e.status
    r = be.probe()
    payload, code = (r if isinstance(r, tuple) else (r, 200))
    payload = dict(payload)
    payload["connection_id"] = cid
    # §2 says the answer carries `ready`. The FAILURE paths above build the payload here and set it;
    # the success path forwards the adapter's probe payload, and no adapter has ever included it —
    # so a perfectly healthy mailbox answered 200 with {mode,status,user} and no `ready` at all.
    # Every reader that keys on the documented field then had to guess, and the console guessed
    # "error": a green service painted as a red chip. Derive it from the status code rather than
    # asking each adapter to remember, because the code is already the contract's own truth (the
    # compose healthcheck keys on exactly that), so the two cannot drift apart. setdefault, so an
    # adapter that does answer for itself keeps the last word.
    payload.setdefault("ready", code == 200)
    return jsonify(payload), code


@app.get("/stats")
def stats():
    _cid, be = _backend(require_explicit=False)
    return _reply(be.stats())


@app.post("/stats/reset")
def stats_reset():
    _cid, be = _backend(require_explicit=False)
    return _reply(be.stats_reset())


# ── the 8 canonical ops (§3) — identical paths + payloads to before ────────────
@app.post("/search")
def search():
    b = _body()
    _cid, be = _backend(b.get("connection_id"), require_explicit=True)
    return _reply(be.search(b))


@app.get("/message/<int:uid>")
def message(uid):
    args = request.args
    _cid, be = _backend(args.get("connection_id"), require_explicit=True)
    return _reply(be.message(uid, args, log=app.logger))


@app.get("/thread/<tid>")
def thread(tid):
    """The conversation a message belongs to. `tid` is a Gmail hex id — the thread's own id or any
    message in it, because callers usually only have the latter.

    New endpoint. It is what `Mail Label Engine`'s disabled `Get Gmail Thread` node needed and
    never had, which is why BS_TO_SYNC / CORRESPONDENCE_STARTED / BS_REPORT_REQUEST have been unable
    to match — they read thread.text and thread.from against an empty object. The response carries
    those two flattened at the top level for exactly that reason.
    """
    args = request.args
    _cid, be = _backend(args.get("connection_id"), require_explicit=True)
    return _reply(be.thread(tid, args, log=app.logger))


@app.post("/labels/add")
def labels_add():
    b = _body()
    _cid, be = _backend(b.get("connection_id"), require_explicit=True)
    return _reply(be.labels_add(b))


@app.post("/labels/remove")
def labels_remove():
    b = _body()
    _cid, be = _backend(b.get("connection_id"), require_explicit=True)
    return _reply(be.labels_remove(b))


@app.get("/labels")
def labels_list():
    _cid, be = _backend(request.args.get("connection_id"), require_explicit=True)
    return _reply(be.labels_list())


@app.post("/labels/create")
def labels_create():
    b = _body()
    _cid, be = _backend(b.get("connection_id"), require_explicit=True)
    return _reply(be.labels_create(b))


@app.post("/append")
def append():
    b = _body()
    _cid, be = _backend(b.get("connection_id"), require_explicit=True)
    return _reply(be.append(b))


@app.post("/send")
def send():
    b = _body()
    _cid, be = _backend(b.get("connection_id"), require_explicit=True)
    return _reply(be.send(b))


# ── the connect / setup screens' endpoints (kept for mailview, N12) ──────────────
@app.get("/connections/<cid>/probe")
def connections_probe(cid):
    """Verify ONE connection without selecting it (§4b step 4: a connection is verified, not added).
    The same probe /readyz runs, so what the connect flow shows and what n8n trusts cannot disagree."""
    inst = next((i for i in cc.list_instances() if i.get("id") == cid), None)
    if not inst:
        return jsonify({"ok": False, "error": f"unknown connection {cid!r}"}), 404
    try:
        _cid, be = _backend(cid, require_explicit=True)
        r = be.probe()
        payload, code = (r if isinstance(r, tuple) else (r, 200))
        ok, reason = code == 200, payload.get("error", "")
    except adapters.AdapterError as e:
        ok, reason = False, str(e)
    return jsonify({"ok": ok, "reason": reason, "id": cid,
                    "account_hint": inst.get("account_hint")})


@app.get("/setup/status")
def setup_status():
    """Is the PRIVATE mailbox actually able to send and receive off-box, and if not, what is missing?

    The connect flow above answers "which account is this". This answers a different question that
    had no owner at all: the local mailbox always "works" — it accepts mail, serves IMAP, passes
    /readyz — while being completely unable to exchange mail with the outside world, because that
    depends on DNS records and a firewall this service does not control. Every one of those failures
    is silent from in here, so the operator's only signal was mail quietly not arriving.

    Read-only and side-effect free: it looks up public DNS, reads the PUBLIC half of the DKIM key,
    and opens two TCP connections. Deliberately NOT cached — an operator publishes a DNS record and
    immediately presses refresh to see whether it took, and a cache would show them yesterday.
    """
    def probe():
        """The LOCAL mailbox's own health, through the same adapter every op uses — so this cannot
        report a mailbox as healthy that the ops cannot reach.

        Pinned to the private engine's ADMIN PROFILE rather than to the active pointer, and that is
        the whole point: this endpoint is about the private mail server. If it followed the active
        connection, an operator with Gmail selected would get a green "your local mailbox is fine"
        that was really a report about Google. (It used to be pinned to the synthetic
        `mail_imap_local-local`; that id no longer exists, and the admin profile is what it meant.)"""
        local_id = profiles.default_instance_id()
        if not local_id:
            return False, ("שרת הדואר המקומי עדיין ללא פרופיל — האתחול טרם הושלם"
                           if not profiles.ledger()["profiles"] else "no local mail profile")
        try:
            _cid, be = _backend(local_id, require_explicit=True)
            r = be.probe()
            payload, code = (r if isinstance(r, tuple) else (r, 200))
            return code == 200, payload.get("error") or payload.get("status") or ""
        except Exception as e:
            return False, "%s: %s" % (type(e).__name__, e)

    return jsonify(mailsetup.status(imap_probe=probe, mailbox_list=mailboxes.summary))


# ── the domain's mailboxes (§the growth story, step 3) ────────────────────────
# Adding a person to a company is one line in the mail server's account file and ZERO DNS work,
# because the company's domain records already cover every address at it. These three routes are
# what makes that true from the UI instead of over ssh.
#
# They are a PROXY. mailapi holds no write capability — its mount of the mail server's config is
# read-only — so every mutation goes to `mailboxd`, which is the only process with the volume
# mounted read-write, has no route of its own, and validates the request against the one domain
# this deployment serves. The status codes below are mailboxd's own, forwarded verbatim: 409 for
# an address that already exists and for the primary mailbox are answers, not failures, and
# the UI shows the reason it gives (mailboxd's own sentence) rather than a generic error.
@app.get("/mailboxes")
def mailboxes_list():
    payload, code = mailboxes.listing()
    return jsonify(payload), code


@app.post("/mailboxes")
def mailboxes_create():
    """Creates the mailbox AND its connection, in ONE operation (§7).

    The password is already in the request body, so there was never a reason for these to be two
    steps — and while they were, a mailbox created here was not reachable as a profile at all: it
    existed on the mail server, received mail, and was invisible to the account bar. "Add a mail
    user" was undiscoverable for exactly that reason.

    Guarded by the admin ring, in the engine (§4): creating an identity is an admin act."""
    b = _body()
    profiles.require_admin(b.get("connection_id"))
    payload, code = profiles.create_profile(
        b.get("local") or (b.get("address") or "").split("@")[0],
        b.get("password") or "",
        display_name=b.get("display_name"),
        admin=bool(b.get("admin")))
    return jsonify(payload), code


@app.delete("/mailboxes/<path:address>")
def mailboxes_delete(address):
    """Removes the ACCOUNT and its connection. The maildir is deliberately left on disk and the
    response says where — a button that silently destroys a company's correspondence is not a
    feature (§9 law 8: deleting a profile removes access, never data).

    Admin ring: an admin may remove anyone, a profile may remove itself, and the LAST admin cannot be
    removed by anybody — otherwise profile management becomes unreachable."""
    target, _rec = profiles.by_address(address)
    profiles.require_admin(request.args.get("connection_id"), target_pid=target)
    payload, code = profiles.delete_profile(address)
    return jsonify(payload), code


# ── the private engine's profile plane (§8 slot 4) ────────────────────────────
@app.get("/engine/profiles")
def engine_profiles():
    """Who exists on the private engine, what each one's address and connection are, and whether the
    bootstrap reconciler is happy. No credential is ever in this payload."""
    return jsonify(profiles.listing())


@app.post("/engine/profiles/reconcile")
def engine_profiles_reconcile():
    """Force a reconcile pass. Idempotent by construction — run it twice and the second answer is an
    empty `actions` list, which is the property that makes `bbox run` safe on a live company."""
    profiles.require_admin((_body() or {}).get("connection_id"))
    r = profiles.run_now()
    return jsonify(r), (200 if r.get("ok") else 503)


@app.post("/engine/profiles")
def engine_profiles_create():
    """Create a profile: the mailbox AND its connection, in one operation.

    Address-keyed `POST /mailboxes` above is the same act and stays — it is what the mailbox screen
    calls, and it takes `local` because that screen is about an ADDRESS. This route takes `id`
    because chat and drive expose it under that name and a profile screen written once should work
    against all three engines. Same handler, same admin ring, same response."""
    b = _body()
    profiles.require_admin(b.get("connection_id"))
    payload, code = profiles.create_profile(
        b.get("id") or b.get("local") or (b.get("address") or "").split("@")[0],
        b.get("password") or "",
        display_name=b.get("display_name") or b.get("name"),
        admin=bool(b.get("admin") if b.get("admin") is not None else b.get("is_admin")))
    return jsonify(payload), code


@app.patch("/engine/profiles/<pid>")
def engine_profiles_patch(pid):
    """Rename, promote, demote. self ring for your own display name, admin ring for anyone's flag.

    `status` is REFUSED rather than ignored. Chat and drive can suspend a profile because their
    credential is a key they mint; a dovecot mailbox has no suspended state, and accepting the field
    to look consistent would be a button that reports success and changes nothing."""
    b = _body()
    is_admin = b.get("admin") if b.get("admin") is not None else b.get("is_admin")
    # Promoting yourself is the whole attack, so the flag is admin-ring even when the target is you.
    profiles.require_admin(b.get("connection_id"),
                           target_pid=(None if is_admin is not None else pid))
    if b.get("status") is not None:
        return jsonify({"ok": False, "error":
                        "לתיבת דואר מקומית אין מצב מושהה. להפסקת גישה — סובב את הסיסמה או מחק את "
                        "הפרופיל (הדואר נשמר).",
                        "rotate_at": "POST /engine/profiles/%s/key" % pid}), 400
    payload, code = profiles.update_profile(
        pid,
        display_name=(b.get("display_name") if b.get("display_name") is not None else b.get("name")),
        admin=(None if is_admin is None else bool(is_admin)))
    return jsonify(payload), code


@app.delete("/engine/profiles/<pid>")
def engine_profiles_delete(pid):
    """Remove ACCESS — the account and its connection. The maildir stays on disk; the response says
    where. Profile-keyed twin of `DELETE /mailboxes/<address>`, which the mailbox screen calls."""
    profiles.require_admin(request.args.get("connection_id"), target_pid=pid)
    payload, code = profiles.delete_profile(profiles.address_of(pid))
    return jsonify(payload), code


@app.post("/engine/profiles/<pid>/key")
@app.post("/engine/profiles/<pid>/password")
def engine_profile_rotate(pid):
    """Rotate one profile's credential. The mailbox hash and the vault instance move together.

    `/key` is the name chat and drive use; `/password` is mail's own and stays because for this
    engine the credential IS the mailbox password and calling it a key would be the vaguer word.

    self ring for your own profile, admin ring for anyone else's."""
    b = _body()
    profiles.require_admin(b.get("connection_id"), target_pid=pid)
    payload, code = profiles.rotate_password(pid, b.get("password") or b.get("key"))
    return jsonify(payload), code


@app.get("/providers")
def providers():
    """Provider-first catalog for the guided connect flow (§4b): users pick a PROVIDER, and each
    provider offers auth methods that each map to exactly one protocol. Local is first and is never
    hidden as a fallback."""
    return jsonify({"providers": [
        # The local provider's copy says "connect", never "create". An operator read this card as
        # "add a mail user", clicked through, and found a step that asks for nothing — because the
        # server is inside the deployment and mailapi derives its own credentials. The wording now
        # states that, and points at the screen where an address IS created (POST /mailboxes above).
        {"id": "local", "name": "תיבת דואר מקומית", "icon": "server", "builtin": True,
         "description": "שרת הדואר שמובנה במערכת. מחבר את התיבה הקיימת לקריאה — "
                        "יצירת כתובת חדשה נעשית במסך „הוספת כתובת דואר בחברה”.",
         "auth_methods": [{"id": "builtin", "label": "מובנה — לא נדרש חיבור",
                           "protocol": "mail_imap_local", "needs": [], "recommended": True,
                           "can": "קריאת דואר, חיפוש, תוויות ושליחה בתוך התיבה המקומית."}]},
        {"id": "gmail", "name": "Gmail", "icon": "mail", "description":
            "החשבון שלך ב־Google. הדואר נשאר ב־Gmail; המערכת עובדת עליו ישירות דרך IMAP.",
         "auth_methods": [
             {"id": "oauth", "label": "התחברות עם Google", "protocol": "mail_gmail_oauth",
              "needs": [], "recommended": True,
              "can": "קריאה, חיפוש, תוויות ושליחה בחשבון שתאשר.",
              "explain": "נפתח חלון של Google. לאחר האישור החשבון נוצר כאן ואפשר לבדוק אותו "
                         "ולהפעיל אותו. אפשר לסגור את החלון בכל שלב — לא ייווצר חיבור.",
              "start_url": f"{CONNECTIONS_PUBLIC_URL}/oauth/google-workspace-grant/start"
                           f"?as_instance=1&go=1"},
             {"id": "app_password", "label": "סיסמת אפליקציה", "protocol": "mail_imap_app_password",
              "needs": ["username", "password"],
              "can": "קריאה, חיפוש, תוויות ושליחה — בלי חלון אישור.",
              "explain": "דורש אימות דו־שלבי פעיל בחשבון Google, ואז יצירת סיסמת אפליקציה בת 16 "
                         "תווים. הזן את כתובת המייל המלאה ואת הסיסמה שנוצרה.",
              "help_url": "https://myaccount.google.com/apppasswords"}]},
    ]})


# ── extension slots (§4c) — an app registers UI, this service renders it ───────
@app.get("/extensions")
def extensions_list():
    """What is registered. `spec` is echoed back verbatim: this service stores and renders it, and
    never reads a field of it for meaning."""
    return jsonify({"extensions": extensions.listing(request.args.get("slot"),
                                                     request.args.get("app")),
                    "slots": list(extensions.SLOTS)})


@app.post("/extensions")
def extensions_register():
    b = _body()
    rec, err = extensions.register(b.get("app"), b.get("slot"), b.get("spec"))
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"ok": True, "app": rec["app"], "slot": rec["slot"]})


@app.delete("/extensions/<appname>/<slot>")
def extensions_unregister(appname, slot):
    return jsonify({"ok": extensions.unregister(appname, slot)})


# ── the organizer plane — THE rule store (RELEASE-DECISIONS N1 + N2) ───────────
#
# The label rules are OWNED by the mail app and live in ONE document (options.py). Every mailbox
# evaluates the same rules; the per-connection override plane (`/connections/<cid>/options`,
# `/organizer/effective/<cid>`, `mode: "override"`) had no callers and is gone. Routes are
# root-level like every other mailapi op, and none of them touches a mailbox — which is why they
# need no `connection_id` (see the module docstring on `/organizer/settings`).
@app.get("/organizer/defaults")
def organizer_defaults_get():
    """The editor's document. `previous` (the last document, for rollback) stays off the wire —
    the editor would only round-trip it — and is described by `rollback` instead."""
    doc, rollback = options.public_view(options.get_defaults())
    return jsonify({"defaults": doc, "rollback": rollback})


@app.put("/organizer/defaults")
def organizer_defaults_put():
    """Validate, then write (N2: "a bad rule cannot be saved").

    400 {error, problems: [{row, field, message}]} — the editor pins each problem to a cell:
      rules is a list; every rule has a unique UPPER_SNAKE KEY, a non-empty LABEL, TYPE
      ON_CREATE_EVENT or the system-mark form (TYPE == KEY with the never-match RULE), an integer
      row_number (renumbered 1..n on write, order preserved), a boolean `enabled` (default true)
      and a RULE that passes options.check_rule_syntax (balanced brackets, terminated strings, only
      the engine's helpers / email / thread / attachments / literals / arrow parameters).
    409 {error} — the document deletes or renames the PROCESSED row, the engine's only cursor;
      send {"confirm_processed": true} beside `mail` to do it anyway.
    200 {ok, defaults, rollback, ignored} — `ignored` names organizer-level keys that were dropped
      because nothing reads them (never a silent dead knob). The previous document is kept for
      POST /organizer/rollback."""
    b = _body()
    confirm = bool(b.pop("confirm_processed", False)) if isinstance(b, dict) else False
    try:
        doc, ignored = options.put_defaults(b, confirm_processed=confirm)
    except options.ValidationError as e:
        return jsonify({"error": str(e), "problems": e.problems}), 400
    except options.ProcessedGuard as e:
        return jsonify({"error": str(e), "confirm_with": {"confirm_processed": True}}), 409
    except ValueError as e:
        return jsonify({"error": str(e), "problems": []}), 400
    doc, rollback = options.public_view(doc)
    return jsonify({"ok": True, "defaults": doc, "rollback": rollback, "ignored": ignored})


@app.post("/organizer/rollback")
def organizer_rollback():
    """Swap the document with the one saved before the last PUT (and keep the swapped-out one as
    the new `previous`, so a rollback is itself reversible). 409 when there is nothing to go back to."""
    try:
        doc = options.rollback()
    except options.NothingToRollBack as e:
        return jsonify({"ok": False, "error": str(e)}), 409
    doc, rollback = options.public_view(doc)
    return jsonify({"ok": True, "defaults": doc, "rollback": rollback})


@app.get("/organizer/settings")
def organizer_settings():
    """The settings document the label engine consumes — the shape indoxSettings01 used to serve:
    {gmail: {labels: {KEY: {...}}, rows: [...]}}, plus `enabled` on every row and label (N2).

    `enabled` is EMITTED, NOT FILTERED: every row is here, disabled ones flagged, so the engine
    decides what to skip and the KEY -> name map stays complete for the sync callers that resolve
    label names through `labels` (a disabled rule's label still exists on the mailbox).
    `connection_id` is accepted (the engine's Load Settings nodes pass it) and changes nothing:
    one rule store serves every mailbox (N1)."""
    doc = options.get_defaults()
    rules = sorted(options.rules_of(doc), key=lambda r: r.get("row_number") or 0)
    labels, rows = {}, []
    for r in rules:
        if not isinstance(r, dict) or not r.get("KEY"):
            continue
        row = dict(r)
        row["enabled"] = options.enabled_of(r)
        rows.append(row)
        labels[r["KEY"]] = {
            "name": (r.get("LABEL") or "").strip(),
            "label_id": r.get("label_id") or None,
            "event": r.get("EVENT") or None,
            "rule": r.get("RULE") or None,
            "row_number": r.get("row_number"),
            "enabled": row["enabled"],
        }
    return jsonify({"gmail": {"labels": labels, "rows": rows}})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8970")))
