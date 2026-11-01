"""The connection-management HTTP surface (contract §2).

Registered by service.py alongside the op routes. There is one process and one backend registry now
(adapters.py), so selecting here IS what the ops route on — /manifest can finally advertise
ops_use_active_connection: true.
"""
from flask import Blueprint, request, jsonify

import adapters
import connections_client as cc
import extensions
import profiles

bp = Blueprint("connections_api", __name__)


def _outbound_scope():
    """"internet" | "mta" | "relay" | "unknown" — what handles outbound on the ACTIVE connection.

    A Gmail connection (app-password or OAuth) submits through Google, so it reaches the internet.
    The built-in local account submits to our own Postfix, which delivers or bounces — it never
    invents a mailbox for an unknown recipient, which is what the GreenMail test double used to do
    and why it was removed. The console shows this so "sent" cannot quietly mean two different
    things depending on which account happens to be selected.
    """
    try:
        _cid, be = adapters.resolve_active()
    except Exception:                                    # noqa: BLE001
        return "unknown"
    if getattr(be, "protocol", "") != cc.LOCAL_PROTOCOL:
        return "internet"
    # The local account now runs on a real MTA (Postfix), which delivers or bounces — it never
    # invents a mailbox for an unknown recipient the way the old GreenMail test double did. Whether
    # it REACHES the internet depends on the host being able to open port 25 outbound and on DNS
    # (MX/SPF/DKIM/PTR), neither of which this process can determine from inside a container.
    # "mta" is therefore the honest answer: a real mail server accepted it, and the mail log is where
    # the outcome lives.
    import local_app
    return "relay" if local_app.SMTP_MODE == "relay" else "mta"

@bp.get("/manifest")
def manifest():
    """What this service is and what it can do — the console and n8n authors discover mail here.

    `ops` comes from adapters.CANONICAL_OPS — the one dict the route table, the abstraction test
    and this advertisement are all held to — so the advertisement cannot drift from the
    implementation. It used to be a hand-kept list of eight names; the service had since grown
    getThread and stats, and neither was discoverable. Every op is answered by every protocol
    (the protocol-specific `rebuildLabels` retired with its zero callers, RELEASE-DECISIONS N12).
    """
    # Best-effort: the manifest must answer even when no connection resolves (a fresh install with a
    # dangling pointer still has to be discoverable, or the console cannot render the fix).
    try:
        _cid, be = adapters.resolve_active()
        ops = adapters.ops_for(be)
    except Exception:                                    # noqa: BLE001 — degrade, never 500 here
        ops = list(adapters.CANONICAL_OPS)
    return jsonify({
        "service": "mail",
        "protocols": cc.PROTOCOLS,
        "ops": ops,
        "slots": list(extensions.SLOTS),
        "capabilities": {
            "labels": True,
            "attachments": True,
            "send": True,
            "append": True,
            "search_query": True,
            # N12, one mail client: this service no longer serves a browser client of its own;
            # mailview (mail.*) is the UI, and it talks to these same ops.
            "ui": False,
            "extensions": True,                # §4c: apps register UI into the slots above
            "multi_connection": True,          # the connection registry below is live
            # TRUE as of the adapter layer: every op resolves its backend from the active pointer
            # (or its own connection_id override), and /readyz probes that same backend.
            "ops_use_active_connection": True,
            "connection_id_override": True,    # any op accepts {connection_id} for a single call
            # What handles outbound on the ACTIVE connection — Google, our own MTA, or an external
            # smarthost. Surfaced because "sent" means something different on each, and a caller
            # that cannot see which one is in play cannot reason about a message that never arrived.
            "outbound_scope": _outbound_scope(),
        },
    })


@bp.get("/connections")
def connections_list():
    # Report the EFFECTIVE active connection, not the raw pointer: an unset pointer means "use the
    # GMAIL_IMAP_MODE bootstrap default", so returning None here would render a fresh install as
    # "no account selected" when it is in fact ready and serving. cc.default_id() is the same
    # function the ops resolve through, so this can never disagree with what mail actually uses.
    conns = cc.list_instances()
    cid = cc.active()
    if not cid:
        return jsonify({"active": cc.default_id(), "connections": conns})
    if not any(c.get("id") == cid for c in conns):
        # A SET pointer that is not in our own list is dangling — the account was removed from the
        # vault directly. Say so here (a needs_action row, §4b) rather than reporting an `active`
        # nobody can find: /readyz already fails on this, and the two surfaces must tell one story.
        reason = "החשבון שנבחר (%s) אינו קיים יותר. בחר חשבון אחר או חבר אותו מחדש." % cid
        conns.append(cc.dangling_instance(cid, reason))
        return jsonify({"active": cid, "connections": conns, "reason": reason})
    return jsonify({"active": cid, "connections": conns})


@bp.post("/connections/select")
def connections_select():
    b = request.get_json(force=True, silent=True) or {}
    cid = b.get("id")
    if not cid:
        return jsonify({"ok": False, "error": "id required"}), 400
    # Selecting an id that does not exist would wedge every op behind a pointer that can never
    # resolve — validate against the list (which always contains the synthetic local id, so local
    # stays selectable even when secret-base is down).
    if cid not in [i.get("id") for i in cc.list_instances()]:
        return jsonify({"ok": False, "error": "unknown connection id", "id": cid}), 404
    cc.select(cid)
    return jsonify({"ok": True, "active": cid})


@bp.post("/connections")
def connections_add():
    b = request.get_json(force=True, silent=True) or {}
    protocol, label = b.get("protocol"), b.get("label")
    if not protocol or not label:
        return jsonify({"ok": False, "error": "protocol and label required"}), 400
    if protocol not in cc.PROTOCOLS:
        return jsonify({"ok": False, "error": "unsupported protocol", "protocol": protocol,
                        "supported": cc.PROTOCOLS}), 400
    if protocol == cc.LOCAL_PROTOCOL:
        # You do not CONNECT to the private engine, you create a profile ON it — and creating one is
        # what mints its connection (§7). This endpoint used to accept a mail_imap_local instance,
        # store it, list it and let you select it, and then serve the one shared mailbox regardless
        # of the credentials it had just been handed. There is no shape of request here that could
        # have been right: an address with a password is a mailbox, and a mailbox is created by the
        # process that owns the account file.
        return jsonify({"ok": False, "error":
                        "חשבון של שרת הדואר המקומי נוצר במסך תיבות הדואר, לא כאן — יצירת תיבה "
                        "יוצרת גם את החיבור שלה.",
                        "protocol": protocol, "create_at": "POST /mailboxes"}), 400
    try:
        r = cc.create_instance(protocol, label, b.get("secret") or {}, b.get("account_hint"))
    except cc.ConnectionsError as e:
        return jsonify({"ok": False, "error": str(e)}), e.status
    return jsonify(r), 201


@bp.delete("/connections/<cid>")
def connections_delete(cid):
    if cid == cc.ENV_ID:
        # Synthetic — it has no vault row to delete; its "vault" is the process env.
        return jsonify({"ok": False, "error": "a synthetic connection cannot be removed", "id": cid}), 400
    pid, _rec = profiles.by_instance(cid)
    if pid:
        # A local profile's connection is not a standalone credential you can throw away: the
        # mailbox behind it would keep receiving mail with nothing able to read it, and the engine
        # reconciler would rebuild the instance on the next pass (rotating the password, because it
        # is not kept outside the vault). Removing the PROFILE is the operation that exists.
        return jsonify({"ok": False, "id": cid, "profile": pid, "error":
                        "זהו פרופיל של שרת הדואר המקומי. הסרה נעשית במסך תיבות הדואר "
                        "(מחיקת התיבה מסירה גם את החיבור); התיבה עצמה נשמרת על הדיסק.",
                        "delete_at": "DELETE /mailboxes/%s" % (_rec or {}).get("address", "")}), 409
    try:
        cc.delete_instance(cid)
    except cc.ConnectionsError as e:
        return jsonify({"ok": False, "error": str(e)}), e.status
    # §2: "removing the active one clears active" — otherwise the pointer dangles at a dead id.
    if cc.active() == cid:
        cc.select(None)
    # Drop the deleted account's cached backend too: it holds live IMAP sockets against credentials
    # that no longer exist here, and its id could be reused by a later instance.
    adapters.forget(cid)
    return jsonify({"ok": True, "id": cid})
