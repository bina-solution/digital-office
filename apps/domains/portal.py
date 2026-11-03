"""domains.portal — the declarative scripts that drive a portal that has no API.

A portal script is DATA, not code: an ordered list of steps with role/name locators, an explicit
version, and a `status` that says how much it can be trusted. That is the whole design, and each part
earns its place:

  * **data**, because a selector changes when a panel is redesigned, and fixing it must not require a
    release of the app — nor re-deriving what the flow was;
  * **versioned**, because "the script that wrote this record" is part of the evidence;
  * **status-labelled**, because the single most dangerous thing this app could do is run an
    UNVERIFIED write against the owner's registrar. `draft` scripts are exploratory: they may open
    pages and read them, and they refuse to write. `verified` means a human watched that exact
    version perform the action, once, and the result was read back.

The statuses are deliberately blunt, and the app enforces them at the call site — not here, so a
reader can see the refusal next to the operation it protects.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

import browser_session as bs

log = logging.getLogger("domains.portal")

#: Where a script's lifecycle stands. `draft` = never run against a live login; `observed` = the
#: steps were read off the real page and the READS work; `verified` = a human watched this exact
#: version write something, and the value was read back.
DRAFT, OBSERVED, VERIFIED = "draft", "observed", "verified"

SCRIPTS: dict[str, dict] = {
    "internic": {
        "portal": "internic",
        "name": "פורטל אינטרניק",
        "origin": "https://portal.internic.co.il",
        "login_path": "/user/login",
        #: the panel's real paths, observed on the live site (2026-09-23/25). They live in the SCRIPT
        #: and not in the code: `/domains` and `/dns` both 404 — the list is the dashboard itself, and
        #: a zone is `/zone/<id>` reached from it. A new provider ships a script, not a code change.
        "paths": {"domains": "/dashboard/main", "zone": "/zone/{zone_id}"},
        "version": 1,
        "status": DRAFT,
        "why_draft": (
            "מסך ההתחברות של הפורטל מוגן ב-Incapsula ואינו נגיש לקורא שאינו דפדפן, ולכן הזרימה "
            "שאחרי ההתחברות טרם נצפתה. הסקריפט כאן יסתעף לעמודים ויקרא אותם (בטוח), ולא יכתוב "
            "דבר עד שאדם יצפה בפעולה אחת מוצלחת ויאשר."),
        "operations": {
            "list_domains": {
                "kind": "read",
                "steps": [
                    {"id": "domains-page", "action": "goto", "value": "/dashboard/main"},
                    {"id": "settle", "action": "wait_for", "seconds": 2},
                    {"id": "read", "action": "read",
                     "locator": {"role": "table"}, "compare": "contains"},
                ],
            },
            "read_zone": {
                "kind": "read",
                "steps": [
                    {"id": "zone-page", "action": "goto", "value": "/dashboard/main"},
                    {"id": "settle", "action": "wait_for", "seconds": 2},
                    {"id": "read", "action": "read", "locator": {"role": "table"}},
                ],
            },
            "set_nameservers": {"kind": "write", "needs_verification": True, "steps": [
                {"id": "ns-page", "action": "goto", "value": "/dashboard/main"},
                {"id": "settle", "action": "wait_for", "seconds": 2},
                # completed once the nameserver editor has been SEEN (see discover)
            ]},
            "set_autorenew": {"kind": "write", "needs_verification": True, "steps": [
                {"id": "domains-page", "action": "goto", "value": "/dashboard/main"},
                {"id": "settle", "action": "wait_for", "seconds": 2},
            ]},
            "set_lock": {"kind": "write", "needs_verification": True, "steps": [
                {"id": "domains-page", "action": "goto", "value": "/dashboard/main"},
                {"id": "settle", "action": "wait_for", "seconds": 2},
            ]},
            "renew": {"kind": "money", "needs_verification": True, "steps": [
                {"id": "domains-page", "action": "goto", "value": "/dashboard/main"},
                {"id": "settle", "action": "wait_for", "seconds": 2},
            ]},
            "register": {"kind": "money", "needs_verification": True, "steps": [
                {"id": "search-page", "action": "goto", "value": "/domains/search"},
                {"id": "settle", "action": "wait_for", "seconds": 2},
            ]},
            "get_auth_code": {"kind": "read", "steps": [
                {"id": "domains-page", "action": "goto", "value": "/dashboard/main"},
                {"id": "settle", "action": "wait_for", "seconds": 2},
                {"id": "read", "action": "read", "locator": {"role": "table"}},
            ]},
            # A record is WRITTEN by code, not by steps: `ZONE_WRITERS` below (DGO-1032). The step
            # script that stood here stopped after "open the dashboard", and run with the owner's
            # consent it would have reported a write that never happened.
        },
    },
    "sitesdepot": {
        "portal": "sitesdepot",
        "name": "Plesk של InterVision (sitesdepot)",
        "origin": "http://sitesdepot.com",
        "login_path": "/login_up.php",
        "version": 1,
        "status": DRAFT,
        "why_draft": (
            "ל-Plesk יש API אמיתי (/api/v2) — הנתיב המומלץ הוא מפתח API והרשאת IP, ולא דפדפן. "
            "הסקריפט כאן הוא גיבוי אם ה-API יישאר חסום. שים לב: הפאנל מציג תעודה של "
            "*.intervision.co.il שאינה תואמת את השם sitesdepot.com, ולכן HTTPS נכשל בדפדפן אמיתי — "
            "עובדים מולו ב-http או מבקשים מהספק את שם המארח הנכון."),
        "operations": {
            "list_domains": {"kind": "read", "steps": [
                {"id": "login-page", "action": "goto", "value": "/login_up.php"},
                {"id": "settle", "action": "wait_for", "seconds": 2},
            ]},
        },
    },
}


def script(portal: str) -> dict | None:
    return SCRIPTS.get(portal)


def describe(portal: str) -> dict:
    s = SCRIPTS.get(portal)
    if not s:
        return {"portal": portal, "known": False}
    ops = {name: {"kind": op.get("kind"), "status": s["status"],
                  "steps": len(op.get("steps") or []),
                  "needs_verification": bool(op.get("needs_verification"))}
           for name, op in (s.get("operations") or {}).items()}
    return {"portal": portal, "known": True, "name": s["name"], "origin": s["origin"],
            "version": s["version"], "status": s["status"], "why": s.get("why_draft", ""),
            "operations": ops}


def session_for(portal: str, endpoint: str | None = None) -> bs.Session:
    s = SCRIPTS.get(portal)
    if not s:
        raise KeyError(portal)
    return bs.Session(endpoint=endpoint, group=f"domains-{portal}")


def state(portal: str, endpoint: str | None = None) -> dict:
    """Is the office logged into this portal right now? Asked of the page, never assumed."""
    s = SCRIPTS.get(portal)
    if not s:
        return {"portal": portal, "known": False, "state": "unknown_error",
                "reason": "אין סקריפט לפורטל הזה"}
    try:
        sess = session_for(portal, endpoint)
        st = sess.state(s["origin"])
    except bs.SessionError as e:
        return {"portal": portal, "known": True, "authenticated": False, "state": e.state,
                "reason": e.message, "detail": e.detail}
    return {"portal": portal, "known": True, "script_status": s["status"], **st,
            "live_view": "/a/browser42/", "login_url": s["origin"] + s["login_path"]}


def connect_check(portal: str, endpoint: str | None = None) -> dict:
    """THE provider flow, in one function: is the office logged in, and does it have CONTROL?

    Three answers, and nothing else — because this is the screen the owner looks at when they add
    their registrar:

      `needs_human_login`  the browser is on a login page. One link, one instruction, no retries.
      `connected`          the panel's own domain list was READ from the owner's account, and the
                           evidence (the domain names it showed) is returned with it.
      `login_failed` / `browser_unavailable`
                           something concrete is wrong, named.

    "Verified" here means the office SAW the account's data — not that a form posted. A connection
    that claims success without reading anything is the one thing this flow must never do.
    """
    s = SCRIPTS.get(portal)
    if not s:
        return {"step": "unknown", "error": "אין סקריפט לפורטל הזה"}
    try:
        sess = session_for(portal, endpoint)
        with own_tab(sess):
            return _connect_check_in_tab(sess, portal, s)
    except bs.SessionError as e:
        return {"step": "browser_unavailable" if e.state in ("unknown_error", "timeout") else "error",
                "portal": portal, "state": e.state, "error": e.message, "detail": e.detail}


def _connect_check_in_tab(sess: "bs.Session", portal: str, s: dict) -> dict:
    """The body of `connect_check`, run inside a tab of our own (see `own_tab`)."""
    state_ = sess.state(s["origin"])
    if not state_.get("authenticated"):
        # Three different answers, and they must not be collapsed into one: "a human has to log in"
        # is an instruction for the owner, while "the browser did not answer" is a fault in the
        # office's own tooling. Reporting the second as `login_failed` sends the owner to a login
        # page that is already logged in.
        st = state_.get("state")
        step = ("needs_human_login" if st == "needs_human_login"
                else "browser_unavailable" if st in ("unknown_error", "timeout")
                else "login_failed")
        return {"step": step, "portal": portal, "state": st,
                "reason": state_.get("reason"), "how": state_.get("how"),
                "login_url": s["origin"] + s["login_path"], "live_view": "/a/browser42/",
                "page": {"url": state_.get("url"), "title": state_.get("title")},
                "hint": ("פתח את הדפדפן של הלשכה, התחבר לפורטל פעם אחת, ואז חזור לכאן "
                         "וללחוץ „בדוק שוב”.")}
    # Logged in — now PROVE control by reading the account's own data, and keep trying until the
    # panel has actually rendered it: "connected, 0 domains" is the evidence-free connection this
    # flow exists to avoid.
    page = sess.open(s["origin"] + (s.get("paths") or {}).get("domains", "/"))
    found, tries = {}, 0
    for tries in range(1, 9):
        try:
            found = bs._json_from_text(
                sess.call("browser_evaluate", {"function": _JS_EVIDENCE}).get("text")) or {}
        except bs.SessionError:
            found = {}
        if found.get("domains"):
            break
        sess.call("browser_wait_for", {"time": 1.5})
        if tries in (2, 5):                     # a reload once, in case the page half-rendered
            try:
                sess.open(s["origin"] + (s.get("paths") or {}).get("domains", "/"))
            except bs.SessionError:
                pass
    seen = [d for d in (found.get("domains") or []) if isinstance(d, str)][:50]
    links = [x for x in (found.get("labels") or []) if isinstance(x, str)]
    zone_link = any(_looks_like_dns(x) for x in links)
    return {"step": "connected", "portal": portal, "name": s["name"],
            "evidence": {"domains_seen": seen, "count": len(seen), "zone_screen": zone_link,
                         "page": {"url": page.get("url"), "title": page.get("title")}},
            "capabilities": {"read_domains": bool(seen), "write_dns": zone_link, "via": "browser"},
            "note": ("הלשכה קראה את רשימת הדומיינים מהחשבון שלך בפורטל"
                     + (" ומצאה גם מסך ניהול DNS." if zone_link else
                        " אבל לא זיהתה בו מסך ניהול DNS — נשלים אחריו."))}


def _looks_like_dns(text: str) -> bool:
    import re as _re
    return bool(_re.search(r"\b(dns|zone|רשומות|אזור)\b", (text or ""), _re.I))


def discover(portal: str, url: str | None = None, endpoint: str | None = None) -> dict:
    """Open a page in the office browser and REPORT WHAT IS THERE.

    This is how a script gets written without guessing: the office observes the real page — its
    controls, its tables, its links — and the owner sees exactly what the automation sees. It is also
    the safe first move after a human logs in: reading a page changes nothing.
    """
    s = SCRIPTS.get(portal)
    if not s:
        return {"portal": portal, "ok": False, "error": "אין סקריפט לפורטל הזה"}
    target = url or s["origin"]
    try:
        sess = session_for(portal, endpoint)
        st = sess.state(s["origin"])
        if not st.get("authenticated"):
            return {"portal": portal, "ok": False, **{k: st.get(k) for k in
                                                      ("state", "reason", "how", "url", "title")}}
        page = sess.open(target)
        nodes = page.get("nodes") or []
        interesting = [n for n in nodes if n["role"] not in ("generic", "paragraph", "text")]
        return {"portal": portal, "ok": True, "url": target, "title": page.get("title"),
                "controls": [{"role": n["role"], "name": n["name"]} for n in interesting[:40]],
                "counts": {"nodes": len(nodes), "links": sum(1 for n in nodes if n["role"] == "link"),
                           "tables": sum(1 for n in nodes if n["role"] == "table"),
                           "textboxes": sum(1 for n in nodes if n["role"] == "textbox")},
                "note": ("אלה הפקדים שהלשכה רואה בדף הזה. מהם נכתבים שלבי הסקריפט — בלי ניחושים, "
                         "ובלי לגעת בכלום."),
                }
    except bs.SessionError as e:
        return {"portal": portal, "ok": False, "state": e.state, "error": e.message,
                "detail": e.detail}


#: Which script operation performs which record action, best name first. A panel does not have to
#: offer "create" and "update" as separate screens — this one has a single zone form — so the mapping
#: belongs HERE, with the provider, and not as a `f"{action}_record"` guess in the app.
WRITE_OPS: dict[str, tuple[str, ...]] = {
    "create": ("create_record", "write_record"),
    "update": ("update_record", "write_record"),
    "delete": ("delete_record",),
}

#: What each record action is called when the owner reads about it. One vocabulary, used by every
#: refusal below — the screens show these words and nothing else.
ACTION_HE = {"create": "הוספת רשומה", "update": "עריכת רשומה", "delete": "מחיקת רשומה"}

#: The one explanation for "the office will not write in your panel yet", reused everywhere so the
#: same situation never produces two different sentences on two different screens.
DRAFT_TITLE = "הלשכה עוד לא כותבת בפורטל — צריך אישור אחד שלך"
DRAFT_WHY = ("כדי לשנות משהו בחשבון שלך, אדם צריך לראות את הפעולה הזו מצליחה פעם אחת. זו הגנה על "
             "הדומיין שלך, לא תקלה — ואחרי אישור אחד הפעולה הזו תרוץ מכאן בלי לשאול.")
#: Only the door every situation has: the watched run is offered where it exists — the new-record
#: window — and nowhere else (the second reader of DGO-1032: this sentence named a checkbox on screens
#: that had none).
DRAFT_HOW = "אפשר לעשות את השינוי ידנית בפורטל (קישור למטה)."

#: The actions a person watched succeed once, per portal (DGO-1032) — the one consent the draft gate
#: asks for. Kept with the office's data, not in this file: a write proved on this office's own account,
#: by its own browser, is a fact about the installation.
VERIFIED_FILE = Path(os.environ.get("DOMAINS_STATE_DIR", "/data")) / "portal-verified.json"


def _watched() -> dict:
    """{portal: {action: mark}}, every level checked: a file of another shape is no mark — it made the
    domain screen answer 500 (the third reader)."""
    try:
        data = json.loads(VERIFIED_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {p: {a: m for a, m in marks.items() if isinstance(m, dict)}
            for p, marks in data.items() if isinstance(marks, dict)}


def writer_version(portal: str, action: str) -> str:
    """The version a watched success vouches for: the code writer's own, else the step script's. A
    changed writer is an unwatched one — the mark was the portal's for ever (the third reader)."""
    return WRITER_VERSIONS.get((portal, action)) or str((SCRIPTS.get(portal) or {}).get("version") or "")


def verified(portal: str, action: str) -> bool:
    """May the office do this write unattended: its whole script is `verified`, or this very action, in
    this very version, was watched succeeding once — written, and read back from the server."""
    mark = (_watched().get(portal) or {}).get(action)
    return (SCRIPTS.get(portal) or {}).get("status") == VERIFIED or \
        bool(mark) and mark.get("version") == writer_version(portal, action)


def mark_verified(portal: str, action: str, by: str, record: dict) -> None:
    """The watched write succeeded: from now on this action, in this version, runs without asking. Who
    watched, when, and what was written are kept beside it — the whole consent, never just a flag."""
    data = _watched()
    data.setdefault(portal, {})[action] = {"at": int(time.time()), "by": by, "record": record,
                                           "version": writer_version(portal, action)}
    VERIFIED_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = VERIFIED_FILE.with_name(VERIFIED_FILE.name + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(temporary, VERIFIED_FILE)


#: Where each domain's zone editor lives, once one opened and PROVED itself that domain's (a fully qualified
#: name inside it, none outside): from then on a read goes straight to its address, and the dashboard —
#: where an unattended click could land on a setting a layout hides from any rule — is not touched again for
#: that domain (the ninth reader of DGO-1032). Beside the watched marks; a file of another shape is no memory.
def _zones_file() -> Path:
    return VERIFIED_FILE.with_name("portal-zones.json")


def _zones() -> dict:
    """{portal origin: {domain: zone id}} — per PORTAL: a zone id is the portal's own (another portal's door
    opened `<its origin>/zone/<InterNIC's id>` and forgot InterNIC's memory: the tenth reader). Ids are ASCII
    digits; anything else is no memory."""
    try:
        data = json.loads(_zones_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {o: {d: z for d, z in zones.items() if isinstance(d, str) and isinstance(z, str)
                and z.isascii() and z.isdigit()}
            for o, zones in data.items() if isinstance(o, str) and isinstance(zones, dict)}


def _keep_zone(origin: str, domain: str, zone_id: str | None) -> None:
    """Remember (or, with None, forget) a domain's zone address on one portal. A memory that cannot be
    written only means the next read opens the zone from the dashboard again."""
    data, domain = _zones(), (domain or "").strip().rstrip(".").lower()
    if zone_id:
        data.setdefault(origin, {})[domain] = zone_id
    else:
        data.get(origin, {}).pop(domain, None)
    try:
        _zones_file().parent.mkdir(parents=True, exist_ok=True)
        temporary = _zones_file().with_name(_zones_file().name + ".tmp")
        temporary.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(temporary, _zones_file())
    except OSError:
        pass


def operation_for(portal: str, action: str) -> str | None:
    """The operation this portal uses for `action`, or None when its script cannot do it at all."""
    ops = (SCRIPTS.get(portal) or {}).get("operations") or {}
    return next((name for name in WRITE_OPS.get(action, ()) if name in ops), None)


def supports_write(portal: str, action: str) -> bool:
    return (portal, action) in ZONE_WRITERS or operation_for(portal, action) is not None


def write_state(portal: str) -> dict:
    """Can the office WRITE here, in one object the screens can show BEFORE anything is clicked.

    Three different situations were being reported with one shrug of an error message: the script is
    a draft (unlockable by one watched action), the action was never scripted (needs a mapping), and
    the portal is fine. Saying which one it is, up front, is the difference between a screen the
    owner understands and a screen that keeps refusing for reasons it never states.
    """
    s = SCRIPTS.get(portal) or {}
    origin = s.get("origin") or ""
    actions = {a: supports_write(portal, a) for a in ("create", "update", "delete")}
    watched = {a: ok and verified(portal, a) for a, ok in actions.items()}
    # the record types a code writer fills whole — the screen holds back the rest before the click
    types = list(WRITABLE_TYPES) if (portal, "create") in ZONE_WRITERS else None
    status = s.get("status") or "unknown"
    if not s:
        return {"enabled": False, "state": "unknown", "actions": actions,
                "title": "אין סקריפט לפורטל הזה", "why": "", "how": "", "portal_url": origin}
    missing = [ACTION_HE[a] for a, ok in actions.items() if not ok]
    if status != VERIFIED and not (any(actions.values()) and all(watched[a] for a, ok in actions.items() if ok)):
        return {"enabled": False, "state": status, "actions": actions, "watched": watched, "types": types,
                "title": DRAFT_TITLE, "why": DRAFT_WHY, "how": DRAFT_HOW, "portal_url": origin,
                "missing": missing}
    return {"enabled": True, "state": VERIFIED, "actions": actions, "watched": watched, "types": types,
            "portal_url": origin,
            "title": "" if not missing else f"חלק מהפעולות עוד לא ממופות: {', '.join(missing)}",
            "why": "" if not missing else
                   "השאר עובד. אלה עוד לא נראו בפועל, ולכן הלשכה לא מנסה אותן.",
            "how": "" if not missing else "אפשר לעשות אותן ידנית בפורטל.", "missing": missing}


def _draft_refusal(portal: str, action: str, allow_draft_write: bool) -> dict | None:
    """The human gate in front of a write by a portal that is not `verified` — the refusal `run` gives a
    step script, given to a write done by code (`ZONE_WRITERS`) in the same words. An action watched
    succeeding once passes it from then on (`verified`)."""
    s = SCRIPTS.get(portal) or {}
    if verified(portal, action) or allow_draft_write:
        return None
    return {"ok": False, "state": "needs_verification", "portal": portal,
            "script_status": s.get("status"), "title": DRAFT_TITLE,
            "error": f"{ACTION_HE.get(action, action)} בפורטל עוד לא מאושרת.",
            "why": DRAFT_WHY, "how": DRAFT_HOW,
            "detail": s.get("why_draft", ""), "portal_url": s.get("origin") or ""}


def run_write(portal: str, action: str, params: dict, endpoint: str | None = None,
              allow_draft_write: bool = False) -> dict:
    """Run a record action, or refuse it in words the owner can act on."""
    if not supports_write(portal, action):
        return {"ok": False, "state": "not_scripted", "portal": portal,
                "title": f"{ACTION_HE.get(action, action)} — עוד לא ממופה לפורטל הזה",
                "error": (f"אף פעם לא ראינו את {ACTION_HE.get(action, action)} בפורטל הזה, ולכן "
                          f"הלשכה לא מנסה לנחש."),
                "why": "כל פעולה נכתבת רק אחרי שנצפתה עובדת פעם אחת בפועל.",
                "how": f"אפשר לעשות אותה ידנית בפורטל{(SCRIPTS.get(portal) or {}).get('origin') and ' (קישור למטה)' or ''}, ואז לאשר כאן.",
                "portal_url": (SCRIPTS.get(portal) or {}).get("origin") or ""}
    writer = ZONE_WRITERS.get((portal, action))
    if writer:
        refusal = _draft_refusal(portal, action, allow_draft_write)
        return refusal or writer(portal, params or {}, endpoint)
    res = run(portal, operation_for(portal, action) or "", params, endpoint, allow_draft_write)
    # The draft gate lives inside `run`, which does not know which ACTION was attempted — so it
    # names the script's operation (`write_record`). Put the owner's word back: "עריכת רשומה".
    if isinstance(res, dict) and not res.get("ok") and res.get("state") == "needs_verification":
        res = {**res, "error": f"{ACTION_HE.get(action, action)} בפורטל עוד לא מאושרת."}
    return res


def run(portal: str, operation: str, params: dict | None = None,
        endpoint: str | None = None, allow_draft_write: bool = False) -> dict:
    """Run one operation of a portal script, with the status gate in front of it."""
    s = SCRIPTS.get(portal)
    if not s:
        return {"ok": False, "state": "unknown_error", "error": "אין סקריפט לפורטל הזה"}
    op = (s.get("operations") or {}).get(operation)
    if not op:
        return {"ok": False, "state": "unknown_error",
                "error": f"הפעולה {operation} אינה מוגדרת לפורטל {s['name']}"}
    if op.get("kind") in ("write", "money") and s["status"] != VERIFIED and \
            not allow_draft_write:
        return {"ok": False, "state": "needs_verification", "portal": portal,
                "script_status": s["status"], "title": DRAFT_TITLE,
                "error": f"{ACTION_HE.get(operation.split('_')[0], operation)} בפורטל עוד לא מאושרת.",
                "why": DRAFT_WHY, "how": DRAFT_HOW,
                "detail": s.get("why_draft", ""), "portal_url": s.get("origin") or ""}
    params = params or {}
    try:
        sess = session_for(portal, endpoint)
        st = sess.state(s["origin"])
        if not st.get("authenticated"):
            return {"ok": False, "state": st.get("state"), "reason": st.get("reason"),
                    "how": st.get("how")}
        steps = [dict(step) for step in op["steps"]]
        for step in steps:                        # parameters fill placeholders in the script
            if isinstance(step.get("value"), str):
                for k, v in params.items():
                    step["value"] = step["value"].replace("{" + k + "}", str(v))
        verify = op.get("verify")
        if verify and op.get("kind") == "write":
            verify = {**verify, "value": params.get(verify.get("param") or "value")}
        res = sess.act(steps, verify=verify, url=s["origin"] + (op.get("start") or ""))
        return {"ok": res.get("state") == bs.OK, "portal": portal, "operation": operation,
                "script_version": s["version"], "script_status": s["status"], **res}
    except bs.SessionError as e:
        return {"ok": False, "state": e.state, "error": e.message, "detail": e.detail}


def catalog() -> list[dict]:
    return [describe(p) for p in SCRIPTS]


def save_script(portal: str, operations: dict, status: str | None = None) -> dict:
    """Persist a script learned at the office (the runtime counterpart of editing this file).

    Kept in the app's own volume rather than written into the source tree: a script the office
    LEARNED belongs to the installation, and a container that rewrites its own Python is a container
    whose next restart runs code nobody reviewed.
    """
    path = Path("/data/portal-scripts.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    cur = data.get(portal) or {}
    data[portal] = {**cur, "operations": {**(cur.get("operations") or {}), **operations},
                    "status": status or cur.get("status") or DRAFT,
                    "saved_at": __import__("time").time()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    # merge into the live registry so the next call sees it without a restart
    if portal in SCRIPTS:
        SCRIPTS[portal]["operations"].update(data[portal]["operations"])
        SCRIPTS[portal]["status"] = data[portal]["status"]
    return describe(portal)


# ── reading the panel: the data half of the abstract API ─────────────────────────────────────────
# These two functions are the whole "abstract API through the browser" story, and they were written
# from a LIVE session (2026-09-23, the owner logged in): the panel's domain list lives at
# `/dashboard/main` (the `/domains` path is a 404 there), and the zone editor is a per-domain page
# `/zone/<id>` reached by ticking the domain's row and clicking the `zone-edit` control — a control
# marked `visually-hidden`, which is why clicking it needs the DOM and not a picture of the screen.
#
# Both return the office's own shapes, so nothing above this file learns what Internic's HTML looks
# like (and a redesign is a change here, not in the API, the UI, or any consumer).

_JS_DOMAINS = """() => {
  const out = [];
  document.querySelectorAll('table').forEach(t => {
    const heads = Array.from(t.querySelectorAll('thead th, thead td')).map(h => (h.innerText||'').trim());
    if (!heads.some(h => /דומיין|domain/i.test(h))) return;
    Array.from(t.querySelectorAll('tbody tr')).forEach(r => {
      const cells = Array.from(r.querySelectorAll('td')).map(c => (c.innerText||'').replace(/\\s+/g,' ').trim());
      const name = cells.find(c => /^[a-z0-9.-]+\\.[a-z]{2,}$/i.test(c));
      if (!name) return;
      const expiry = cells.find(c => /^\\d{2}\\/\\d{2}\\/\\d{4}$/.test(c)) || '';
      const ns = (cells.find(c => /ns\\d|dns/i.test(c)) || '').split(/\\s+/).filter(Boolean);
      const contact = cells.slice(-1)[0] || '';
      out.push({name: name.toLowerCase(), expiry: expiry, nameservers: ns, contact: contact});
    });
  });
  return JSON.stringify({domains: out, url: location.href, title: document.title});
}"""

_ZONE_ROWS = """(doc) => {
  // The zone editor's real shape, read off the live panel (2026-09-23, re-read 2026-09-25): a RECORD
  // row carries `select[name=rectype_<n>]` together with `input[name=name_<n>]`, `ttl_<n>`,
  // `class_<n>` and `specs_<n>` (the value), where <n> is the record's own id. Every OTHER row with a
  // type <select> is a TEMPLATE: the "add a record" form, and the SRV priority/weight/port/target
  // sub-rows, have no per-record field names at all. Reading those positionally is how this reader
  // used to invent records that do not exist in the zone — an apex A at 93.184.216.11 that no resolver
  // ever answered, and two CNAMEs whose value was the domain itself. So a row counts as a record ONLY
  // if it carries the per-record field names, and its fields are matched by the SAME numeric suffix.
  const rows = [];
  const suffix = (el) => { const m = (el.name || '').match(/_([0-9]+)$/); return m ? m[1] : null; };
  Array.from(doc.querySelectorAll('tr')).forEach(tr => {
    const typeEl = tr.querySelector('select[name^="rectype_"]');
    // the value may be a <textarea>: the TXT rows' cells are resizable on the live panel, and the write
    // already fills one there — read as an <input> only, a TXT record was invisible to every read and
    // check (the third reader of DGO-1032)
    const specEl = tr.querySelector('input[name^="specs_"], textarea[name^="specs_"]');
    if (!typeEl || !specEl) return;
    const n = suffix(typeEl) || suffix(specEl);
    if (!n) return;
    const val = (prefix) => {
      const e = tr.querySelector('input[name="' + prefix + '_' + n + '"]');
      return e ? (e.value || '').trim() : null;
    };
    const content = (specEl.value || '').trim();
    const name = val('name');
    if (!content && !name) return;
    const prio = tr.querySelector('select[name="priority_' + n + '"]');
    // The suffix is the TYPE's index in this panel, not the record's: six CNAME rows all carry
    // `rectype_1`. So identity here is the row's ORDINAL within the read — the panel publishes no
    // per-record id at all, and inventing one from the suffix collapsed six records into one.
    rows.push({id: String(rows.length), type: (typeEl.value || '').toUpperCase(), name: name,
               ttl: val('ttl'), content: content, priority: prio ? prio.value : null});
  });
  return rows;
}"""

_JS_ZONE = """() => {
  const rows = (""" + _ZONE_ROWS + """)(document);
  return JSON.stringify({rows: rows, url: location.href, title: document.title,
                         zone_id: (location.pathname.split('/zone/')[1] || '').replace(/[^0-9].*$/, '') || null,
                         row_count: document.querySelectorAll('tr').length});
}"""

#: The zone as the SERVER holds it at this moment, read WITHOUT leaving the page a row was typed into:
#: the editor's own address fetched again and read by the same rules. The save writes the WHOLE zone from
#: the form, so a record added or changed on the server since the form loaded would be undone by it, and
#: the read-back would still look right (the second reader of DGO-1032). A page that renders its rows only
#: in the browser serves none here — then the guard says it could not run, never that it passed.
_JS_SERVER_ZONE = """async () => {
  try {
    const r = await fetch(location.href, {credentials: 'same-origin', cache: 'no-store'});
    if (!r.ok) return JSON.stringify({unavailable: 'http ' + r.status});
    const doc = new DOMParser().parseFromString(await r.text(), 'text/html');
    const rows = (""" + _ZONE_ROWS + """)(doc);
    return JSON.stringify(rows.length ? {rows: rows} : {unavailable: 'the served page has no record rows'});
  } catch (e) {
    return JSON.stringify({unavailable: String((e && e.name) || e)});
  }
}"""


class own_tab:
    """Do the work in a tab of OUR OWN, and leave the owner's page exactly where it was.

    The office browser is a real browser that the owner is looking at (it is on screen in the
    console). Every read here used to navigate the CURRENT tab to the portal — so a background
    refresh moved whatever page the owner had open, and two readers fought over one tab. Opening a
    tab, working in it, and closing it in `finally` costs one MCP call and removes both problems.

    Best-effort by design: if a new tab cannot be opened, the work happens in the current tab exactly
    as before rather than failing.
    """

    def __init__(self, sess: "bs.Session"):
        self.sess = sess
        self.before = 0

    def __enter__(self):
        # Take the ONE-driver lock for the whole read: two threads driving one browser do not just
        # go slowly, they open tabs for each other and close each other's work.
        self._drive = bs.driving()
        self._drive.__enter__()
        self.before = _tab_count(self.sess)
        if self.before:
            try:
                self.sess.call("browser_tabs", {"action": "new"})
            except bs.SessionError:
                self.before = 0                        # could not open one: stay where we are
        return self

    def __exit__(self, *exc):
        try:
            if self.before and _tab_count(self.sess) > self.before:
                try:
                    self.sess.call("browser_tabs", {"action": "close"})
                except bs.SessionError:
                    pass
        finally:
            self._drive.__exit__(None, None, None)
        return False


#: Control evidence for the connect flow: the SAME table reader the list screen uses. `innerText`
#: does not contain a table the panel keeps hidden while it renders, which is why "connected, 0
#: domains" used to be the answer here while the list screen happily read three.
_JS_EVIDENCE = r"""() => {
  const out = [];
  document.querySelectorAll('table').forEach(t => {
    const heads = Array.from(t.querySelectorAll('thead th, thead td'))
        .map(h => (h.innerText || '').trim());
    if (!heads.some(h => /דומיין|domain/i.test(h))) return;
    Array.from(t.querySelectorAll('tbody tr')).forEach(r => {
      const cells = Array.from(r.querySelectorAll('td'))
          .map(c => (c.innerText || '').replace(/\s+/g, ' ').trim());
      const name = cells.find(c => /^[a-z0-9.-]+\.[a-z]{2,}$/i.test(c));
      if (name) out.push(name.toLowerCase());
    });
  });
  const labels = Array.from(document.querySelectorAll('a,button'))
      .map(e => (e.innerText || '').trim()).filter(Boolean).slice(0, 40);
  return JSON.stringify({domains: Array.from(new Set(out)).slice(0, 50), labels: labels,
                         title: document.title});
}"""

#: Tick the domain's row, then open its zone editor. The panel opens it in a NEW TAB; `own_tab`
#: is what keeps that tab from being left behind in the owner's browser.
_JS_OPEN_ZONE = """(spec) => {
  // The domain's OWN row: a cell that IS the name. A row whose text merely contained it opened a sibling
  // (office.co.il inside digital-office.co.il) or a row whose nameserver cell named it — and a write then
  // went into another domain's zone (the second reader of DGO-1032). Nothing in another row is touched:
  // unticking "every other ticked box" would have clicked any switch a row carries (auto-renew, a lock) on
  // every read (the third reader). A row's selection box is its FIRST, as this read has always ticked it;
  // when another domain's is already ticked, the zone button could open that one — so nothing is opened.
  const want = (spec.domain || '').toLowerCase();
  const text = (c) => (c.innerText || c.textContent || '').replace(/\\s+/g, ' ').trim();
  const nameOf = (r) => { const c = Array.from(r.children).find(c => /^[a-z0-9.-]+\\.[a-z]{2,}$/i.test(text(c)));
                          return c ? text(c).toLowerCase() : null; };
  // ONLY in the domain list — a table whose header names it «דומיין» / domain, the rule the domains read
  // keeps (_JS_DOMAINS): a card placed before the list (an auto-renew card, a "recent domains" one) had its
  // toggle ticked by document order (the ninth reader). Two such tables holding it — visible or not — are
  // refused: with the list hidden while it renders, a visible card whose table also named «דומיין» was taken
  // as the list (the tenth). A copy the panel keeps for another layout names no column, and is no list.
  const listing = (t) => Array.from(t.querySelectorAll('th')).some(h => /דומיין|domain/i.test(text(h)));
  // (a copy NOT DRAWN whose row holds no box — a hidden phone layout — is no list to tick: the eleventh; a drawn
  // one still counts, or a favourites card with a box became the list when the list's own rows had none: the
  // twelfth)
  const mine = Array.from(document.querySelectorAll('tr'))
      .filter(r => nameOf(r) === want && r.closest('table') && listing(r.closest('table'))
                   && (r.querySelector('input[type=checkbox]') || r.getClientRects().length));
  if (new Set(mine.map(r => r.closest('table'))).size > 1)
    return JSON.stringify({found: true, zone: false, no_selection: true, why: 'two domain lists hold it'});
  const row = mine[0];
  if (!row) return JSON.stringify({found: false});
  // The selection box is the row's FIRST box — the rule this read has used on the live panel since
  // 2026-09-23 — and it is ticked only where its column is POSITIVELY a selection column: every header cell
  // over it is empty, says "select", or holds the select-all box, and none names a setting. Anything else
  // is refused. Four readers in a row found a header that named the renew switch some new way (a sortable
  // button, an icon, text hidden at this width, an i18n key…) past a list of setting words; a list of what
  // a selection column looks like cannot be walked past (the eighth reader). The live dashboard measured
  // has an empty header over it. Its VISUAL column finds the same column in the other rows of THIS table;
  // a box there that is ticked, under another domain's name, visible or not, means the zone button could
  // open that domain — nothing is opened. A refusal says what the header over the box said (`header`), so
  // the first live refusal is read from its answer. Once a zone has opened and proved itself this domain's,
  // its address is kept and the dashboard is not clicked again (_read_zone_in_tab, ZONES).
  // Columns are a GRID: colspans counted, and a cell that spans down (rowspan) holds its column in the rows
  // below — a cell index is not a column (the fifth reader), nor is a count of a row's own cells (the sixth).
  // A span ends with its row group (thead, tbody, tfoot), as the browser draws it, and rowspan=0 is "to the
  // end of the group": carried past it, a header's span stood over the body's boxes (the seventh).
  const grid = (t) => {
    const rows = Array.from(t.rows), at = rows.map(() => []);
    const end = rows.map((r, i) => { let j = i;
                                     while (j + 1 < rows.length && rows[j + 1].parentNode === r.parentNode) j++;
                                     return j; });
    rows.forEach((r, ri) => {
      let c = 0;
      for (const x of r.cells) {
        while (at[ri][c]) c++;
        const cs = Math.max(1, x.colSpan || 1);
        const last = x.rowSpan === 0 ? end[ri] : Math.min(end[ri], ri + Math.max(1, x.rowSpan || 1) - 1);
        for (let rr = ri; rr <= last; rr++)
          for (let dc = 0; dc < cs; dc++) at[rr][c + dc] = x;
        c += cs;
      }
    });
    return {rows, at, width: Math.max(0, ...at.map(a => a.length))};
  };
  // A setting named in Hebrew or by WHOLE English words (`Block` is no lock, Bootstrap's `mx-auto` no
  // auto-renew: the seventh reader); what a selection column's header says, whole.
  const SETTING = /חידוש|התחדש|מתחדש|לחדש|יחודש|יתחדש|הארכ|נעיל|נעול|\\brenew|\\b(?:un)?lock(?:s|ed|ing)?\\b|\\bauto[ _-]?(?:renew|extend)/i;
  const SETTING_WORD = /^(autorenew|renew|renewal|renewing|autoextend|extend|lock|locks|locked|locking|unlock)$/i;
  const SELECT = /^(?:בחר|בחרו|בחר י|בחירה|סמן|סמנו|סימון|(?:בחר|סמן|בחירת) הכו?ל|select|select all|select all rows|select row|choose)$/i;
  // «הכל», "all": "select" only beside a select-all box (a bare «הכל» over a setting column opened: the eleventh)
  const SELECT_ALL = /^(?:הכו?ל|all)$/i;
  const words = (s) => String(s || '').replace(/([a-z])([A-Z])/g, '$1 $2').split(/[^A-Za-z0-9]+/).filter(Boolean);
  const plain = (s) => String(s || '').replace(/[^\\p{L}\\p{N}]+/gu, ' ').trim();
  // The names an element carries: a title in any kit's attribute (Bootstrap's after its tooltip starts,
  // tippy's), an alt, a placeholder, a value; an aria-label only up to its ":" — DataTables writes
  // ": activate to sort column ascending" on every sortable header, the empty one too (the ninth reader).
  const TITLES = ['title', 'data-title', 'data-bs-title', 'data-original-title', 'data-bs-original-title',
                  'data-tippy-content'];
  const titled = (e) => [...TITLES.map(a => e.getAttribute(a) || ''),
                         (e.getAttribute('aria-label') || '').split(':')[0]].join(' ');
  const names = (e) => [titled(e), e.getAttribute('alt') || '', e.getAttribute('placeholder') || '',
                        e.getAttribute('value') || ''].join(' ');
  // the text of a cell, less what sits inside `not` (a selector) within it
  const textOf = (cell, not) => {
    const out = [], w = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT);
    for (let n = w.nextNode(); n; n = w.nextNode()) {
      const s = not && n.parentElement && n.parentElement.closest(not);
      if (!(s && s !== cell && cell.contains(s))) out.push(n.nodeValue);
    }
    return out.join(' ');
  };
  // A SELECT-ALL cell (one holding a checkbox) carries bulk controls and menus — a <select> of actions, a
  // dropdown, a closed <details> — which are left out: what is left of it, and its box's own names and
  // label, each say "select" or nothing, and nothing names a setting (the ninth reader: any word passed
  // beside a box — "Auto", «אוטומטי», a "renew all" box named only by its title). ANY OTHER header cell is
  // read whole — its text hidden or not, a button's, a list's, a <details>' (left out everywhere, a header
  // named by them read as empty: the ninth reader) — holds no form control, and is empty or "select".
  const BULK = 'select,option,input,textarea,details,ul,ol,menu,[role=menu],[role=listbox],.dropdown-menu';
  const NAMED = [...TITLES, 'alt', 'placeholder', 'value'];
  // Each SOURCE is judged on its own — the text, and each name — since DataTables copies a header's title into
  // its aria-label, and «בחר הכל בחר הכל» read whole was no "select" (the tenth reader). A setting is looked
  // for in all of it, the aria-label whole (cut at its ":", a setting after it was hidden: the tenth).
  const selecting = (cell) => {
    const box = cell.querySelector('input[type=checkbox]');
    const leave = (box ? BULK + ',' : '') + 'script,style';
    const left = (e) => { const s = e.closest(leave); return !!s && s !== cell && cell.contains(s); };
    const els = [cell, ...cell.querySelectorAll('*')].filter(e => !left(e));
    const raw = textOf(cell, leave);
    // what an element's aria-labelledby / aria-describedby point at is its name too (the eleventh reader)
    const refs = (e) => ['aria-labelledby', 'aria-describedby'].flatMap(a => (e.getAttribute(a) || '').split(/\\s+/))
        .filter(Boolean).map(id => document.getElementById(id)).filter(Boolean).map(text);
    const sources = [raw, ...els.flatMap(e => [...NAMED.map(a => e.getAttribute(a) || ''),
                                               (e.getAttribute('aria-label') || '').split(':')[0], ...refs(e)])];
    const whole = [raw, ...els.flatMap(e => [...NAMED, 'aria-label'].map(a => e.getAttribute(a) || '').concat(refs(e)))];
    // a select-all cell: EVERY box in it is read (a second, "renew all" box beside the first: the tenth)
    const boxes = box ? Array.from(cell.querySelectorAll('input[type=checkbox]')) : [];
    const boxSaid = boxes.flatMap(b => [...TITLES.map(a => b.getAttribute(a) || ''), b.getAttribute('aria-label') || '',
                                        ...refs(b), ...Array.from(b.labels || []).map(text)]);
    if (SETTING.test([...whole, ...boxSaid].join(' '))) return false;
    if (!box && cell.querySelector('input,select,textarea')) return false;
    const said = [...sources, ...boxSaid.map(s => s.split(':')[0])];
    // a glyph or a "#" — in the text OR a name (`title='↻'`, an icon's aria-label '🔁', an img's alt '⟳') —
    // is not empty, and says no "select" (the eleventh reader: in a name it was dropped as empty)
    if (said.some(s => s.trim() && !plain(s))) return false;
    return said.map(plain).filter(Boolean).every(s => SELECT.test(s) || (!!box && SELECT_ALL.test(s)));
  };
  const table = row.closest('table');
  const cb = row.querySelector('input[type=checkbox]');
  const g = table ? grid(table) : null;
  const ri = g ? g.rows.indexOf(row) : -1;
  const cell = cb ? Array.from(row.cells).find(x => x.contains(cb)) : null;
  const col = cell && ri >= 0 ? g.at[ri].indexOf(cell) : -1;
  if (!cb || col < 0) return JSON.stringify({found: true, zone: false, no_selection: true});
  // header rows: the thead's, and any row of <th> only that is not the foot (a summary row there is no
  // header). A cell as wide as the header itself is a toolbar or a title over every column: it names no
  // column — unless it names a setting, plainly or by a name it carries (its buttons and links are the
  // toolbar's), which refuses: a «חידוש אוטומטי» title stood over the renew column (the ninth reader). A
  // column with no header cell left is not known to be a selection one.
  const heads = g.rows.map((r, i) => i).filter(i => i !== ri && g.rows[i].parentNode !== table.tFoot
      && ((table.tHead && g.rows[i].parentNode === table.tHead)
          || (g.rows[i].cells.length && Array.from(g.rows[i].cells).every(x => x.tagName === 'TH'))));
  const hw = Math.max(0, ...heads.map(i => g.at[i].length));
  const wide = (c) => hw > 1 && (c.colSpan || 1) >= hw;
  const above = heads.map(i => g.at[i][col]).filter(Boolean);
  const over = above.filter(c => !wide(c));
  // (a wide cell's own text less its buttons and links, and the names on it AND its other children: a title
  // on a child icon named the setting past it — the tenth reader)
  const wideSays = (c) => {
    const leave = 'a,button,script,style,' + BULK;
    const left = (e) => { const s = e.closest(leave); return !!s && s !== c && c.contains(s); };
    return [textOf(c, leave), ...[c, ...c.querySelectorAll('*')].filter(e => !left(e))
              .flatMap(e => [...TITLES, 'alt', 'aria-label'].map(a => e.getAttribute(a) || ''))].join(' ');
  };
  const titled_over = above.filter(wide).some(c => SETTING.test(wideSays(c)));
  // the box: its domain's own name says nothing of it (lock-shop.co.il, autoparts.co.il); a word or label that
  // names a setting — in any kit's title attribute, its whole aria-label, what `aria-labelledby` points at, its
  // value (the tenth reader: a Bootstrap 4 or tippy title was not read) — or a switch of any kit, refuses
  const strip = (s) => { s = String(s || ''); let i;
                         while (want && (i = s.toLowerCase().indexOf(want)) >= 0) s = s.slice(0, i) + ' ' + s.slice(i + want.length);
                         return s; };
  const labelledBy = ['aria-labelledby', 'aria-describedby'].flatMap(a => (cb.getAttribute(a) || '').split(/\\s+/))
      .filter(Boolean).map(id => document.getElementById(id)).filter(Boolean).map(text);
  const boxSaid = strip([...TITLES.map(a => cb.getAttribute(a) || ''), cb.getAttribute('aria-label') || '',
                         ...labelledBy, ...Array.from(cb.labels || []).map(text)].join(' '));
  const boxWords = words(strip([cb.name, cb.id, cb.getAttribute('value') || '',
                                typeof cb.className === 'string' ? cb.className : ''].join(' ')));
  const isSwitch = cb.getAttribute('role') === 'switch' || !!cb.closest('.form-switch,.custom-switch,.switch');
  // …and its own CELL: text or an icon beside the box that names a setting («חידוש אוטומטי», a lock titled
  // «נעילת דומיין») — the box was ticked under an empty header (the eleventh reader)
  const cellSaid = strip([textOf(cell, 'script,style'), ...[cell, ...cell.querySelectorAll('*')].filter(e => e !== cb)
                            .flatMap(e => [...TITLES, 'alt', 'aria-label'].map(a => e.getAttribute(a) || ''))].join(' '));
  if (titled_over || !over.length || !over.every(selecting) || isSwitch || SETTING.test(boxSaid)
      || SETTING.test(cellSaid) || boxWords.some(w => SETTING_WORD.test(w)))
    return JSON.stringify({found: true, zone: false, no_selection: true,
                           header: above.map(c => [text(c), ...[c, ...c.querySelectorAll('*')].map(names)]
                                                   .join(' ').replace(/\\s+/g, ' ').trim().slice(0, 80)),
                           box: (boxSaid.trim() || boxWords.join(' ')).slice(0, 80)});
  // ANY other row of the list with a ticked box in this column — whatever its name cell holds (a badge, an
  // IDN: a name that is not exactly a domain left that row's tick uncounted, the tenth reader); the header
  // rows' select-all box is not a row's, and a cell across the WHOLE table where ours is not — a details row, a
  // responsive child row — is no row's selection box (the eleventh reader: their switches read as another
  // domain ticked, and the measured layout refused). Any narrower cell counts, whatever its colspan: skipped
  // for a colspan unlike ours, another domain's tick went uncounted (the twelfth)
  const headRows = new Set(heads);
  const span = (c) => Math.max(1, c.colSpan || 1);
  // (…and a row that is ONE cell wider than ours — a DataTables Responsive child row, spanning only the columns
  // still drawn — holds its row's HIDDEN columns, each part marked with its column (data-dt-column). It is read by
  // its own cell, whatever column ours is: past its colspan it was never asked (the reader of 31d13e30). Which part
  // is ours the mark cannot say — a `visible:false` column numbers DataTables' columns off the page's (the same
  // reader) — so a part with a ticked box counts unless its own title names a setting: its moved renew switch read
  // as another domain ticked (the reader of 42f2fa71), and with the selection column itself hidden another
  // domain's tick lives only there (the reader of 8c03fbcd). An unmarked one counts whole, as any narrower cell.
  // ANY one-cell row is read so, whatever its width: at one drawn column the child is no wider than ours, and its
  // part past column 0 went unread; and a title holding a box is a select-all header's copy — a selection column,
  // whatever its bulk menu names: «חידוש אוטומטי» in it hid another domain's tick (the reader of 537f0bef).)
  const partSaid = (p) => { const t = p.querySelector('.dtr-title');
                            if (!t || t.querySelector('input[type=checkbox]')) return '';
                            return [textOf(t, 'script,style'), ...[t, ...t.querySelectorAll('*')]
                                      .flatMap(e => [...TITLES, 'alt', 'aria-label'].map(a => e.getAttribute(a) || ''))].join(' '); };
  const boxTicked = (e) => Array.from(e.querySelectorAll('input[type=checkbox]')).some(b => b.checked);
  // (…a part whose title READS AS our selection header — copied without its box, or as text — is ours whatever its
  // bulk menu names; and a ticked box outside every part counts as in any other cell: the reader of 3a819f41)
  const headSaid = new Set(over.map(c => plain(c.textContent)).filter(Boolean));
  const ours = (p) => { const t = p.querySelector('.dtr-title'); return !!t && headSaid.has(plain(t.textContent)); };
  const loose = (one, parts) => Array.from(one.querySelectorAll('input[type=checkbox]'))
      .some(b => b.checked && !parts.some(p => p.contains(b)));
  const others = g.rows.filter((r, i) => r !== row && !headRows.has(i))
      .filter(r => { const at = g.at[g.rows.indexOf(r)][col];
                     // (…unless this column is a cell carried down from a row above: then that cell is the column)
                     const one = r.cells.length === 1 && (!at || at === r.cells[0] || span(r.cells[0]) > span(cell))
                         ? r.cells[0] : null;
                     const parts = one ? Array.from(one.querySelectorAll('[data-dt-column]')) : [];
                     if (parts.length) return parts.some(p => boxTicked(p) && (ours(p) || !SETTING.test(partSaid(p))))
                                              || loose(one, parts);
                     const c = one || at;
                     if (!c || c === cell || (span(c) >= g.width && span(cell) < g.width)) return false;
                     const b = c.querySelector('input[type=checkbox]'); return !!(b && b.checked); }).length;
  if (others) return JSON.stringify({found: true, zone: false, others_selected: others});
  if (!cb.checked) cb.click();
  const btn = document.querySelector('button.zone-edit')
           || Array.from(document.querySelectorAll('button'))
                .find(b => /zone/i.test(b.innerText || ''));
  if (!btn) return JSON.stringify({found: true, zone: false});
  btn.click();
  return JSON.stringify({found: true, zone: true});
}"""


def _tab_count(sess: "bs.Session") -> int:
    """How many tabs the browser has, or 0 when that cannot be determined (then nothing is closed)."""
    try:
        text = sess.call("browser_tabs", {"action": "list"}).get("text") or ""
    except bs.SessionError:
        return 0
    import re as _re
    return len(_re.findall(r"^\s*-\s*(\d+):", text, _re.M))


def read_domains(portal: str = "internic", endpoint: str | None = None) -> dict:
    """The account's domains, as the PANEL shows them (name, expiry, nameservers, contact).

    This is the panel's own truth, and it is worth having next to the registry's: the two agree
    today, and the day they do not is the day somebody changed a delegation without telling anyone.
    """
    s = SCRIPTS.get(portal)
    if not s:
        return {"ok": False, "error": "אין סקריפט לפורטל הזה"}
    try:
        sess = session_for(portal, endpoint)
        with own_tab(sess):
            return _read_domains_in_tab(sess, s)
    except bs.SessionError as e:
        return {"ok": False, "state": e.state, "error": e.message, "detail": e.detail}


def _read_domains_in_tab(sess: "bs.Session", s: dict) -> dict:
    """The body of `read_domains`, run inside a tab of our own."""
    st = sess.state(s["origin"])
    if not st.get("authenticated"):
        return {"ok": False, "state": st.get("state"), "reason": st.get("reason"),
                "how": st.get("how"), "authenticated": False}
    sess.open(s["origin"] + (s.get("paths") or {}).get("domains", "/dashboard/main"))
    data = bs._json_from_text(
        sess.call("browser_evaluate", {"function": _JS_DOMAINS}).get("text")) or {}
    domains = []
    for d in data.get("domains") or []:
        days = None
        if d.get("expiry"):
            try:
                dd, mm, yyyy = d["expiry"].split("/")
                import datetime as _dt
                exp = _dt.datetime(int(yyyy), int(mm), int(dd))
                d["expiry_iso"] = exp.strftime("%Y-%m-%d")
                days = (exp - _dt.datetime.now()).days
            except (ValueError, TypeError):
                d["expiry_iso"] = None
        d["days_left"] = days
        domains.append(d)
    return {"ok": True, "domains": domains, "count": len(domains),
            "page": {"url": data.get("url"), "title": data.get("title")}, "source": "portal"}


def read_zone(portal: str, domain: str, endpoint: str | None = None) -> dict:
    """Open ONE domain's zone editor in the panel and read what is in it."""
    s = SCRIPTS.get(portal)
    if not s:
        return {"ok": False, "error": "אין סקריפט לפורטל הזה"}
    try:
        sess = session_for(portal, endpoint)
        with own_tab(sess):
            return _read_zone_in_tab(sess, s, domain)
    except bs.SessionError as e:
        return {"ok": False, "state": e.state, "error": e.message, "detail": e.detail}


def _read_zone_in_tab(sess: "bs.Session", s: dict, domain: str) -> dict:
    """The body of `read_zone`, run inside a tab of our own."""
    st = sess.state(s["origin"])
    if not st.get("authenticated"):
        return {"ok": False, "state": st.get("state"), "reason": st.get("reason")}
    known = _zones().get(s["origin"], {}).get((domain or "").strip().rstrip(".").lower())
    if known:
        # its address, kept from a zone that proved itself this domain's: nothing on the dashboard is clicked
        sess.open(s["origin"] + (s.get("paths") or {}).get("zone", "/zone/{zone_id}").format(zone_id=known))
    else:
        sess.open(s["origin"] + (s.get("paths") or {}).get("domains", "/dashboard/main"))
        clicked = sess.call("browser_evaluate",
                            {"function": f"({_JS_OPEN_ZONE})({__import__('json').dumps({'domain': domain})})"})
        got = bs._json_from_text(clicked.get("text")) or {}
        if got.get("others_selected"):
            return {"ok": False, "state": "conflict",
                    "error": f"בפורטל מסומן כבר דומיין אחר ({got['others_selected']}) — לא נפתח דבר, כדי שלא "
                             f"ייפתח האזור שלו במקום של {domain}. בטלו את הסימון בפורטל ונסו שוב."}
        if got.get("no_selection"):
            # what the header over the box said, and the box itself: the first live refusal is read from here
            return {"ok": False, "state": "conflict",
                    "error": f"בשורה של {domain} בפורטל לא נמצאה תיבת בחירה שאפשר לסמן בבטחה — לא נלחץ "
                             f"דבר, כדי לא לשנות הגדרה (חידוש אוטומטי, נעילה) במקומה.",
                    "detail": json.dumps({k: got.get(k) for k in ("header", "box", "why")},
                                         ensure_ascii=False)[:400]}
        if not got.get("zone"):
            return {"ok": False, "state": "selector_missing",
                    "error": f"לא נמצא מסך עריכת ה-Zone עבור {domain} בפורטל",
                    "detail": str(got)[:200]}
    # The click NAVIGATES, and how long the editor takes to render is the panel's business, not
    # ours. So instead of one fixed sleep followed by one read — which is how this returned an empty
    # zone whenever the panel was a moment slow — poll for the COMPLETION PREDICATE: the URL is a
    # zone page AND it has at least one record row.
    data, attempts = {}, 0
    for attempts in range(1, 11):
        sess.call("browser_wait_for", {"time": 1.2})
        data = bs._json_from_text(
            sess.call("browser_evaluate", {"function": _JS_ZONE}).get("text")) or {}
        if (data.get("rows") or []) and "/zone/" in (data.get("url") or ""):
            break
    recs = []
    for r in data.get("rows") or []:
        if not r.get("content") and not r.get("name"):
            continue
        recs.append({"id": r.get("id"), "type": r.get("type"), "name": r.get("name"),
                     "content": r.get("content"), "ttl": r.get("ttl"),
                     "priority": r.get("priority")})
    # `other_rows` counts everything the editor rendered that is NOT a record — the add-a-record
    # form, the SRV sub-rows, headers — so a panel that changes shape shows up as a number instead
    # of as a quietly shorter zone.
    other = max(0, int(data.get("row_count") or 0) - len(recs))
    if not recs:
        # nothing read is no proof against the kept address — a slow load forgot it, and sent reads back to the
        # dashboard's clicks (the tenth reader): kept while the page is still that zone's. A page that is NOT
        # it any more (the panel sent the address elsewhere: the zone re-created under another id) forgets it —
        # kept, every read and write of the domain failed for good (the eleventh)
        # (a page that answered with an address, and not this zone's — `/zone/<id>` and no longer number; an
        # unreadable last attempt, no address at all, is no evidence: the twelfth reader)
        # …a page of the PANEL that is not its sign-in: an error page, about:blank, or a sign-in the session ran
        # out into says nothing about the address (the reader of 42f2fa71)
        # (the panel is its own scheme and host, not a name that starts with it — `<origin>.evil.example`; and a
        # sign-in or a zone is the page's PATH, not its query: the reader of 8c03fbcd)
        where = urlsplit(str(data.get("url") or ""))
        if known and f"{where.scheme}://{where.netloc}".lower() == s["origin"].lower() \
                and "/login" not in where.path.lower() \
                and not re.search(rf"/zone/{re.escape(known)}(?![0-9])", where.path, re.I):
            _keep_zone(s["origin"], domain, None)
        return {"ok": False, "state": "selector_missing",
                "error": f"עורך ה-Zone של {domain} לא הציג רשומות אחרי {attempts} ניסיונות",
                "detail": str(data.get("url"))[:200],
                "page": {"url": data.get("url"), "title": data.get("title")}}
    # the editor that opened is THIS domain's: a fully qualified name from outside it says it is not, and
    # its records are never shown, or written to, under this domain's name (a short name proves nothing
    # either way — the exact row match in _JS_OPEN_ZONE carries that). The read had no such check, and a
    # wrong zone the opener opened was shown as this one (the sixth reader).
    foreign = [r.get("name") for r in recs if str(r.get("name") or "").endswith(".")
               and not in_zone(fqdn(r.get("name"), domain), domain)]
    # …and PROVED it: the domain's own APEX among its records, fully qualified (a name merely inside it let a
    # child zone — all under shop.<domain>. — prove itself the parent's: the tenth reader). Only a proved
    # zone's address is kept; a kept address that no longer proves itself is forgotten (the next read opens it
    # from the dashboard again).
    # (the apex as the domain's own name, with its trailing dot or without — never `@`, which names no domain)
    apex = (domain or "").strip().rstrip(".").lower()
    proved = not foreign and any(str(r.get("name") or "").strip().rstrip(".").lower() == apex for r in recs)
    if known and not proved:
        _keep_zone(s["origin"], domain, None)
        return {"ok": False, "state": "conflict",
                "error": f"הכתובת שנשמרה לאזור של {domain} אינה מראה עוד את האזור שלו — לא נקרא ולא נכתב בו "
                         f"דבר; הקריאה הבאה תמצא אותו מחדש"}
    if foreign:
        return {"ok": False, "state": "conflict",
                "error": f"העורך שנפתח אינו של {domain} (בו {foreign[0]}) — לא נקרא ולא נכתב בו דבר"}
    if proved and data.get("zone_id") and data.get("zone_id") != known:
        _keep_zone(s["origin"], domain, str(data["zone_id"]))
    return {"ok": True, "domain": domain, "records": recs, "count": len(recs),
            "zone_id": data.get("zone_id"), "rows_seen": data.get("row_count"),
            "other_rows": other, "attempts": attempts,
            "page": {"url": data.get("url"), "title": data.get("title")},
            "note": "זה מה שמופיע בעורך ה-Zone של הפורטל עבור הדומיין הזה."}


# ── writing the panel: ONE record into the zone editor (DGO-1032) ────────────────────────────────
# Measured on the live panel on 2026-10-22, the day the records of an office's own subdomain went in:
#   * «הוסף רשומה ריקה» clones a template into a NEW row whose inputs carry no `name` attribute — the only
#     thing that tells it from the records, every one of which carries `name_<n>`. A write that fills
#     "the Name field" by its label finds an EXISTING record's name first (the apex's, that day): it
#     renames a record instead of adding one.
#   * the type is a <select>; choosing it runs the panel's `record_change()`, which REBUILDS the value
#     cell — so the value is set after the type, in the cell that exists then.
#   * «שמור שינויים» serialises the WHOLE zone (`update_zone_record()`) and asks «האם לשמור את
#     השינויים?» over «<N> רשומות». N must be the records read before, plus one: anything else is a zone
#     this write did not plan, and the dialog is cancelled.
#   * the write is proved by READING THE ZONE BACK from the server: the record there by name, type and
#     value, and every record that was there before still there.

_JS_ADD_ROW = """() => {
  const b = Array.from(document.querySelectorAll('button, a, input[type=button]'))
      .find(e => /הוסף רשומה ריקה/.test((e.innerText || e.value || '').trim()));
  if (!b) return JSON.stringify({found: false});
  b.click();
  return JSON.stringify({found: true});
}"""

#: The new row is the ONE visible row with a type <select> whose first input has no `name` and no value.
_JS_FILL_NEW = """(spec) => {
  const rows = Array.from(document.querySelectorAll('tr')).filter(tr =>
      tr.querySelector('select') && tr.offsetParent && tr.getClientRects().length);
  const fresh = rows.filter(tr => { const i = tr.querySelector('input');
      return i && !i.name && !(i.value || '').trim(); });
  if (fresh.length !== 1) return JSON.stringify({ok: false, fresh: fresh.length});
  const tr = fresh[0];
  const set = (el, v) => { el.value = v; ['input', 'change'].forEach(t =>
      el.dispatchEvent(new Event(t, {bubbles: true}))); };
  const inputs = tr.querySelectorAll('input');
  set(inputs[0], spec.name);
  if (inputs[1]) set(inputs[1], spec.ttl);
  const sel = tr.querySelector('select');
  const opt = Array.from(sel.options).find(o => (o.value || '').toUpperCase() === spec.type
      || (o.text || '').trim().toUpperCase().split(/\\s+/)[0] === spec.type);
  if (!opt) return JSON.stringify({ok: false, type: false,
      options: Array.from(sel.options).map(o => o.value)});
  sel.value = opt.value;
  sel.dispatchEvent(new Event('change', {bubbles: true}));
  tr.setAttribute('data-dgo-new', '1');
  return JSON.stringify({ok: true});
}"""

#: …and its value, AFTER the type rebuilt the cell. The row is the one marked above; the mark goes.
_JS_FILL_VALUE = """(spec) => {
  const tr = document.querySelector('tr[data-dgo-new="1"]');
  if (!tr) return JSON.stringify({ok: false, row: false});
  const v = tr.querySelector('input[name^="specs_"], textarea[name^="specs_"]');
  if (!v) return JSON.stringify({ok: false, value_cell: false});
  v.value = spec.value;
  ['input', 'change'].forEach(t => v.dispatchEvent(new Event(t, {bubbles: true})));
  tr.removeAttribute('data-dgo-new');
  const ins = tr.querySelectorAll('input'), sel = tr.querySelector('select');
  return JSON.stringify({ok: true, row: {name: ins[0] ? ins[0].value : '', ttl: ins[1] ? ins[1].value : '',
                                         type: sel ? sel.value : '', value: v.value}});
}"""

_JS_SAVE = """() => {
  const b = Array.from(document.querySelectorAll('button'))
      .find(e => /שמור שינויים/.test(e.innerText || ''));
  if (!b) return JSON.stringify({found: false});
  b.click();
  return JSON.stringify({found: true});
}"""

_JS_DIALOG = """() => {
  const t = (sel) => ((document.querySelector(sel) || {}).innerText || '').trim();
  return JSON.stringify({open: !!document.querySelector('.swal2-container'),
                         title: t('.swal2-title'), text: t('.swal2-html-container')});
}"""

_JS_ANSWER = """(spec) => {
  // the first VISIBLE of these, in this order: SweetAlert2 renders a hidden .swal2-close before its
  // buttons, and "the first match" clicked that (the third reader of DGO-1032)
  const order = spec.confirm ? ['.swal2-confirm'] : ['.swal2-cancel', '.swal2-deny', '.swal2-close'];
  const b = order.map(s => Array.from(document.querySelectorAll(s)).find(e => e.offsetParent))
                 .find(Boolean);
  if (b) b.click();
  return JSON.stringify({found: !!b});
}"""

SAVE_QUESTION = "האם לשמור את השינויים?"


def fqdn(name: str, domain: str) -> str:
    """A record's name as the panel writes it: fully qualified, with the trailing dot. `@` (or nothing,
    or the domain itself) is the apex; a bare label sits under the domain; a name that already ends in a
    dot is whole as it is — `fpg.example.com.` became fpg.example.com.<domain>. (the second reader)."""
    d = (domain or "").strip().rstrip(".").lower()
    raw = (name or "@").strip().lower()
    n = raw.rstrip(".")
    if n in ("@", "", d):
        return d + "."
    return (n if raw.endswith(".") or n.endswith("." + d) else f"{n}.{d}") + "."


def in_zone(name: str, domain: str) -> bool:
    d = (domain or "").strip().rstrip(".").lower()
    return name == d + "." or name.endswith("." + d + ".")


def _js(sess: "bs.Session", fn: str, spec: dict | None = None) -> dict:
    src = f"({fn})({json.dumps(spec, ensure_ascii=False)})" if spec is not None else fn
    return bs._json_from_text(sess.call("browser_evaluate", {"function": src}).get("text")) or {}


#: The types this writer fills completely: a name, a TTL, ONE value. MX carries a priority and SRV its
#: sub-rows, neither of which the new row was measured filling — offered by the panel, written half,
#: and reported done (the second reader of DGO-1032). Each joins once it is seen working.
WRITABLE_TYPES = ("A", "AAAA", "CNAME", "TXT")
#: The types whose value is a HOST NAME — compared, and written, as the zone means it: fully qualified.
HOST_VALUE_TYPES = ("CNAME", "MX", "NS", "SRV", "PTR")


def target(value: str, rtype: str, domain: str) -> str:
    """A value as the zone stores it. A host name is fully qualified with its dot — `www` is a name
    under the domain, `example.com` is itself — because a target without the dot is RELATIVE in a zone:
    `digital-office.co.il` would mean digital-office.co.il.digital-office.co.il. Anything else as given."""
    v = (value or "").strip()
    if (rtype or "").upper() not in HOST_VALUE_TYPES:
        return v
    if v.endswith("."):
        return v.lower()                               # a host name has no case
    return (v if "." in v else f"{v}.{(domain or '').strip().rstrip('.')}").lower() + "."


def _txt(value: str) -> str:
    """A TXT value the way it reads: one pair of quotes off, a split string joined (`"a" "b"` is `ab`)."""
    v = (value or "").strip()
    parts = re.findall(r'"((?:[^"\\]|\\.)*)"', v)
    return "".join(parts) if parts and re.fullmatch(r'\s*("(?:[^"\\]|\\.)*"\s*)+', v) else v


#: One TXT string holds 255 characters. A longer value goes in as several strings, which this panel was
#: never seen writing — so it is refused by name, not sent whole (the second reader of DGO-1032).
TXT_MAX = 255


def txt_value(value: str) -> str:
    """A TXT value as this panel keeps it: ONE quoted string (its own rows read so). Unquoted, a backend
    that passes the text through writes `v=spf1 a -all` as three strings."""
    inner = _txt(value)
    return '"' + inner.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _address(value: str) -> str:
    """An address as an address: `2001:DB8::1` and `2001:db8:0:0:0:0:0:1` are one AAAA. Compared as text,
    a record that landed read as missing, and the retry wrote it twice (the second reader)."""
    try:
        return ipaddress.ip_address(value.strip()).compressed
    except ValueError:
        return value.strip()


def _value(rtype: str, value: str, domain: str) -> str:
    v = (value or "").strip()
    if rtype in HOST_VALUE_TYPES:
        return target(v, rtype, domain)
    if rtype == "TXT":
        return _txt(v)
    if rtype in ("A", "AAAA"):
        return _address(v)
    return v


def _ttl(value) -> str:
    v = str(value if value is not None else "").strip()
    return str(int(v)) if v.isdigit() else v


def _same(a: dict, b: dict, domain: str) -> bool:
    """One record, however the panel writes it: names as fully qualified names (a row shown as `tfg`
    is tfg.<domain>.), a host-name value without its trailing dot and its case, a TXT value unquoted, an
    address as an address. Compared verbatim, a target the panel stored with its dot never matched what
    was written, and every retry added the record again (the second reader of DGO-1032)."""
    rtype = (a.get("type") or "").upper()
    if rtype != (b.get("type") or "").upper() or fqdn(a.get("name"), domain) != fqdn(b.get("name"), domain):
        return False
    return _value(rtype, a.get("content"), domain) == _value(rtype, b.get("content"), domain)


def _zone_key(records: list, domain: str) -> list:
    """A zone as a comparable whole — every record, its TTL and its priority included (an MX priority
    changed meanwhile was undone under a guard that said "checked", the third reader)."""
    return sorted(((r.get("type") or "").upper(), fqdn(r.get("name"), domain),
                   _value((r.get("type") or "").upper(), r.get("content"), domain), _ttl(r.get("ttl")),
                   str(r.get("priority") or ""))
                  for r in records)


def _clash(records: list, want: dict, domain: str) -> str | None:
    """The rule the panel would not enforce for us, on the zone read just now: a CNAME stands alone at its
    name — and never at the apex, whose SOA and NS this read does not even see (the third reader).
    Checked only in the drawer before, against a list that could be minutes old, and never for a caller
    of the op API (the second reader)."""
    here = [r for r in records if fqdn(r.get("name"), domain) == want["name"]]
    if want["type"] == "CNAME" and want["name"] == fqdn("@", domain):
        return f"CNAME לא יכול לשבת על {domain} עצמו — לצד ה-SOA וה-NS של האזור."
    if want["type"] == "CNAME" and here:
        return (f"ל-{want['name']} כבר יש רשומות ({', '.join(sorted({(r.get('type') or '?') for r in here}))}) "
                f"— CNAME לא יכול לעמוד לצדן.")
    if want["type"] != "CNAME" and any((r.get("type") or "").upper() == "CNAME" for r in here):
        return f"ל-{want['name']} יש CNAME — אי אפשר להוסיף לצדו רשומה נוספת."
    return None


def _zone_from_server(sess: "bs.Session", s: dict, zone_id: str | None, domain: str) -> dict:
    """The zone as the SERVER has it now: the editor loaded afresh, by its own URL — not the page the
    write was typed into, whose DOM shows the row whether or not it was saved."""
    if not zone_id:
        return _read_zone_in_tab(sess, s, domain)
    sess.open(s["origin"] + (s.get("paths") or {}).get("zone", "/zone/{zone_id}").format(zone_id=zone_id))
    data = {}
    for _ in range(10):
        sess.call("browser_wait_for", {"time": 1.2})
        data = bs._json_from_text(sess.call("browser_evaluate", {"function": _JS_ZONE}).get("text")) or {}
        if data.get("rows"):
            break
    rows = [r for r in data.get("rows") or [] if r.get("content") or r.get("name")]
    return {"ok": bool(rows), "records": rows, "zone_id": zone_id}


def internic_create(portal: str, params: dict, endpoint: str | None = None) -> dict:
    """Create ONE record in an InterNIC zone, proved by reading the zone back. Never another row."""
    s = SCRIPTS.get(portal) or {}
    domain = (params.get("domain") or "").strip().rstrip(".").lower()
    rtype = (params.get("type") or "").strip().upper()
    value = str(params.get("value") or "").strip()
    if not domain or not rtype or not value:
        return {"ok": False, "state": "invalid", "error": "חסרים דומיין, סוג או ערך לרשומה"}
    if rtype not in WRITABLE_TYPES:
        return {"ok": False, "state": "not_scripted", "portal": portal,
                "title": f"רשומת {rtype} — עוד לא ממופה לפורטל הזה",
                "error": f"הלשכה כותבת כאן רק {', '.join(WRITABLE_TYPES)}: לרשומת {rtype} יש שדות נוספים "
                         f"שלא נצפו נכתבים, וחצי רשומה אינה רשומה.",
                "how": "אפשר לעשות אותה ידנית בפורטל (קישור למטה).", "portal_url": s.get("origin") or ""}
    want = {"name": fqdn(params.get("name"), domain), "type": rtype,
            "content": txt_value(value) if rtype == "TXT" else target(value, rtype, domain),
            "ttl": _ttl(params.get("ttl") if params.get("ttl") not in (None, "") else 3600)}
    if not in_zone(want["name"], domain):
        return {"ok": False, "state": "invalid", "error": f"השם {want['name']} אינו בתוך {domain} — לא נכתב דבר"}
    bad = _invalid_name(params.get("name"), domain) or _invalid_value(rtype, value)
    if bad:
        return {"ok": False, "state": "invalid", "error": bad + " לא נכתב דבר."}
    if rtype == "TXT" and len(_txt(value).encode("utf-8")) > TXT_MAX:
        # octets, as DNS counts them: 200 Hebrew letters are 400 (the third reader)
        return {"ok": False, "state": "not_scripted", "portal": portal,
                "title": "רשומת TXT ארוכה — עוד לא ממופה לפורטל הזה",
                "error": f"ערך TXT של יותר מ-{TXT_MAX} בתים נכתב בכמה חלקים, וזה לא נצפה עובד בפורטל הזה.",
                "how": "אפשר להוסיף אותה ידנית בפורטל (קישור למטה).", "portal_url": s.get("origin") or ""}
    stage = {"confirmed": False}
    try:
        sess = session_for(portal, endpoint)
        with own_tab(sess):
            return _internic_create_in_tab(sess, s, domain, want, stage)
    except bs.SessionError as e:
        if stage["confirmed"]:
            # the browser went (its heap, a restart) AFTER the save was confirmed: the record may well be
            # there — said as unknown, with what was written, never as a plain failure (the third reader)
            return {"ok": False, "state": "unverified", "saved": True,
                    "error": "השמירה אושרה, ואז הדפדפן של הלשכה נפל — לא ידוע אם הרשומה נכתבה; בדקו בפורטל",
                    "detail": json.dumps({"written": want, "browser": e.state}, ensure_ascii=False)[:400]}
        return {"ok": False, "state": e.state, "error": e.message, "detail": e.detail}


def _invalid_name(name: str | None, domain: str) -> str | None:
    """A record's NAME as DNS has it — labels of letters, digits, `-` and `_`, a `*` only first, the FULL
    name no longer than 253 — held here as the value is: `a b` became `a b.<domain>.`, inside the zone, and
    was written once the action was watched (the sixth reader); the length of the name as given let a
    270-character full name through (the seventh)."""
    n = (name or "@").strip().rstrip(".")
    if n in ("@", ""):
        return None
    if len(fqdn(name, domain).rstrip(".")) > 253 or not all(
            (i == 0 and label == "*") or re.fullmatch(r"[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?", label,
                                                      re.I | re.ASCII)
            for i, label in enumerate(n.split("."))):
        return f"«{name}» אינו שם רשומה תקין."
    return None


def _invalid_value(rtype: str, value: str) -> str | None:
    """The drawer's own rules, held here too: a caller of the op API never saw the drawer (the third
    reader — an A record of `not-an-address` was written)."""
    v = (value or "").strip()
    try:
        if rtype == "A" and not isinstance(ipaddress.ip_address(v), ipaddress.IPv4Address):
            return "A מקבלת כתובת IPv4 בלבד."
        # a scoped address (`fe80::1%eth0`) is an address of one machine's interface, never a record
        if rtype == "AAAA" and ("%" in v or not isinstance(ipaddress.ip_address(v), ipaddress.IPv6Address)):
            return "AAAA מקבלת כתובת IPv6 בלבד."
    except ValueError:
        return f"{rtype} מקבלת כתובת IP בלבד."
    if rtype == "CNAME" and (len(v.rstrip(".")) > 253 or not re.fullmatch(
            r"(?:[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?\.)*[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?\.?", v,
            re.I | re.ASCII)):                        # the Kelvin sign is no `k` (the fifth reader)
        return "CNAME מקבלת שם מארח בלבד."
    return None


def _internic_create_in_tab(sess: "bs.Session", s: dict, domain: str, want: dict, stage: dict) -> dict:
    before = _read_zone_in_tab(sess, s, domain)
    if not before.get("ok"):
        return before
    records = before.get("records") or []        # this domain's editor: _read_zone_in_tab checked it
    existing = next((r for r in records if _same(r, want, domain)), None)
    if existing:
        # what the ZONE holds, its TTL too — the TTL asked for was reported (the third reader)
        return {"ok": True, "state": bs.OK, "unchanged": True,
                "record": {**want, "ttl": _ttl(existing.get("ttl")) or want["ttl"]},
                "note": "הרשומה כבר קיימת באזור — לא נכתב דבר"}
    clash = _clash(records, want, domain)
    if clash:
        return {"ok": False, "state": "conflict", "error": clash + " לא נכתב דבר."}
    # The guard's FIRST read, before the form is touched: the editor's own address, served again. It is
    # compared with the editor as it shows itself — a page whose fields its own script fills serves
    # something else, and comparing that with the live form just before the save said "the zone changed"
    # on every try (the fourth reader). So: served = shown, or the guard cannot work here, said so.
    served = _js(sess, _JS_SERVER_ZONE)
    if not isinstance(served.get("rows"), list) or _zone_key(served["rows"], domain) != _zone_key(records, domain):
        return {"ok": False, "state": "guard_unavailable",
                "error": "כתובת העורך אינה מגישה את מה שהעורך מציג, ולכן אין דרך לדעת אם האזור ישתנה עד "
                         "השמירה — לא נכתב דבר.",
                "detail": json.dumps({"guard": str(served.get("unavailable") or "served rows differ from the "
                                                   "editor's")[:120]}, ensure_ascii=False)}
    if not _js(sess, _JS_ADD_ROW).get("found"):
        return {"ok": False, "state": "selector_missing", "error": "לא נמצא הכפתור «הוסף רשומה ריקה»"}
    sess.call("browser_wait_for", {"time": 0.8})
    filled = _js(sess, _JS_FILL_NEW, {"name": want["name"], "ttl": want["ttl"], "type": want["type"]})
    if not filled.get("ok"):
        return {"ok": False, "state": "selector_missing",
                "error": ("לא נמצאה שורה חדשה אחת וריקה למילוי — לא נכתב דבר" if "fresh" in filled
                          else f"הסוג {want['type']} אינו ברשימת הסוגים של הפורטל — לא נכתב דבר"),
                "detail": json.dumps(filled, ensure_ascii=False)[:300]}
    sess.call("browser_wait_for", {"time": 0.8})       # record_change() rebuilds the value cell
    filled = _js(sess, _JS_FILL_VALUE, {"value": want["content"]})
    if not filled.get("ok"):
        return {"ok": False, "state": "selector_missing", "error": "לא נמצא שדה הערך בשורה החדשה"}
    # The row as it stands before anything is saved: if the type's rebuild reset more than the value
    # cell, the count below would still pass and a wrong row would be written (the second reader).
    row = filled.get("row") or {}
    if (fqdn(row.get("name"), domain) != want["name"] or (row.get("type") or "").upper() != want["type"]
            or (row.get("value") or "").strip() != want["content"] or str(row.get("ttl") or "") != want["ttl"]):
        return {"ok": False, "state": "assert_failed", "error": "השורה החדשה אינה מה שנכתב בה — לא נשמר דבר",
                "detail": json.dumps({"row": row, "wanted": want}, ensure_ascii=False)[:300]}
    # The save writes the WHOLE zone from this form: the server's zone must still be the one the form
    # loaded, or a change made meanwhile is undone (_JS_SERVER_ZONE). Read again just before the click and
    # compared with the FIRST served read — the same parser on both sides. A read that did not come back
    # with the zone saves NOTHING: a guard that could not run is not a guard that passed (the third
    # reader: an error answer read as "checked", and "unavailable" saved anyway).
    server = _js(sess, _JS_SERVER_ZONE)
    if not isinstance(server.get("rows"), list):
        return {"ok": False, "state": "guard_unavailable",
                "error": "לא הצלחתי לקרוא שוב את האזור מהשרת לפני השמירה, ולכן אין הוכחה שהוא לא השתנה "
                         "בינתיים — לא נשמר דבר.",
                "detail": json.dumps({"guard": str(server.get("unavailable") or "no answer")[:120]},
                                     ensure_ascii=False)}
    if _zone_key(server["rows"], domain) != _zone_key(served["rows"], domain):
        return {"ok": False, "state": "conflict",
                "error": "האזור בשרת השתנה מאז שנטען לעריכה — לא נשמר דבר, כדי לא לבטל את השינוי ההוא. "
                         "נסו שוב.",
                "detail": json.dumps({"loaded": len(served["rows"]), "on_server": len(server["rows"])})}
    guard = "checked"
    expect = f"{len(records) + 1} רשומות"
    if not _js(sess, _JS_SAVE).get("found"):
        return {"ok": False, "state": "selector_missing", "error": "לא נמצא הכפתור «שמור שינויים»"}
    dialog = {}
    for _ in range(10):
        sess.call("browser_wait_for", {"time": 0.5})
        dialog = _js(sess, _JS_DIALOG)
        if dialog.get("open"):
            break
    if not dialog.get("open") or dialog.get("title") != SAVE_QUESTION or dialog.get("text") != expect:
        _js(sess, _JS_ANSWER, {"confirm": False})
        # Said from what the server holds, never assumed: a panel that saved without asking, or before
        # its dialog showed, has the record although the save was "cancelled" (the second reader) — and a
        # zone that could not be read back is said as unknown, never as "not there" (the third).
        sess.call("browser_wait_for", {"time": 1})
        after = _zone_from_server(sess, s, before.get("zone_id"), domain)
        landed = any(_same(want, g, domain) for g in after.get("records") or [])
        return {"ok": False, "state": "assert_failed" if after.get("ok") else "unverified", "saved": landed,
                "error": (f"חלון השמירה לא אמר «{expect}», והשמירה בוטלה — אבל הרשומה נמצאת באזור בשרת"
                          if landed else
                          f"חלון השמירה לא אמר «{expect}» — השמירה בוטלה, והרשומה אינה באזור בשרת"
                          if after.get("ok") else
                          f"חלון השמירה לא אמר «{expect}» והשמירה בוטלה; האזור לא נקרא חזרה מהשרת, ולכן לא "
                          f"ידוע אם הרשומה שם — בדקו בפורטל"),
                "detail": json.dumps({"dialog": dialog, "read_back": bool(after.get("ok"))},
                                     ensure_ascii=False)[:300]}
    # Confirmed from the moment the click is SENT: the browser can fall inside this very call after the
    # panel saved (the fourth reader) — and a click that found no button confirmed nothing, so it goes
    # the way of a cancelled save, said from what the server holds.
    stage["confirmed"] = True
    # only the page's own "there is no button" un-confirms: an answer the tool could not give (`{}` —
    # the MCP's error) may follow a click that landed and saved, and is read back as a confirmed save
    # (the fifth reader: read as "no button", a landed save went unrecorded)
    if _js(sess, _JS_ANSWER, {"confirm": True}).get("found") is False:
        stage["confirmed"] = False
        _js(sess, _JS_ANSWER, {"confirm": False})
        sess.call("browser_wait_for", {"time": 1})
        after = _zone_from_server(sess, s, before.get("zone_id"), domain)
        landed = any(_same(want, g, domain) for g in after.get("records") or [])
        return {"ok": False, "state": "assert_failed" if after.get("ok") else "unverified", "saved": landed,
                "error": ("לא נמצא כפתור האישור בחלון השמירה — אבל הרשומה נמצאת באזור בשרת" if landed else
                          "לא נמצא כפתור האישור בחלון השמירה, והרשומה אינה באזור בשרת"
                          if after.get("ok") else
                          "לא נמצא כפתור האישור בחלון השמירה; האזור לא נקרא חזרה — בדקו בפורטל"),
                "detail": json.dumps({"dialog": dialog}, ensure_ascii=False)[:300]}
    # Nothing leaves the page while the panel's question is still open: navigating away 2 s after the
    # click could cut a slow save short (the third reader). Then the proof is the SERVER's zone, read
    # until the record shows (a slow save is not a failed one), each read a fresh load of its address.
    said = {}
    for _ in range(20):
        shown = _js(sess, _JS_DIALOG)
        if not shown.get("open"):
            break
        said = shown                                  # the panel's own answer, kept as evidence
        sess.call("browser_wait_for", {"time": 0.5})
    after, got, landed = {}, [], False
    for _ in range(3):
        sess.call("browser_wait_for", {"time": 2})
        after = _zone_from_server(sess, s, before.get("zone_id"), domain)
        got = after.get("records") or []
        landed = any(_same(want, g, domain) for g in got)
        if landed:
            break
    if not after.get("ok"):
        return {"ok": False, "state": "unverified", "saved": True,
                "error": "השמירה אושרה, אבל האזור לא נקרא חזרה מהשרת — לא ידוע אם הרשומה נכתבה; בדקו בפורטל",
                "detail": json.dumps({"written": want, "records_before": len(records)}, ensure_ascii=False)[:400]}
    missing = [r for r in records if not any(_same(r, g, domain) for g in got)]
    if not landed or missing:
        return {"ok": False, "state": "assert_failed", "saved": True,
                "error": ("הרשומה אינה באזור בשרת אחרי לחיצת האישור — ייתכן שהשמירה לא התבצעה כלל"
                          if not landed else
                          f"הרשומה נכתבה, אבל {len(missing)} רשומות שהיו באזור חסרות בו עכשיו — בדקו בפורטל"),
                "detail": json.dumps({"written": want, "found": landed, "records_before": len(records),
                                      "records_after": len(got), "missing": missing[:5],
                                      "panel_said": {k: said.get(k) for k in ("title", "text")} if said else None},
                                     ensure_ascii=False)[:800]}
    # what the SERVER holds is what is reported — its TTL too: a panel that keeps its own TTL must not be
    # logged as having taken the one asked for (the second reader)
    stored = next(g for g in got if _same(want, g, domain))
    record = {**want, "ttl": _ttl(stored.get("ttl")) or want["ttl"]}
    note = "הרשומה נכתבה, ונקראה חזרה מהאזור בשרת"
    if record["ttl"] != want["ttl"]:
        note += f" — הפורטל שמר TTL {record['ttl']} ולא {want['ttl']} שנתבקש"
    return {"ok": True, "state": bs.OK, "record": record, "ttl_asked": want["ttl"], "guard": guard,
            "records_before": len(records), "records_after": len(got), "note": note}


#: Writes done by code, per (portal, action). What is not here is not scripted, and says so: update
#: and delete wait until each is seen working on the panel once, as create was measured.
ZONE_WRITERS = {("internic", "create"): internic_create}
#: What a watched success vouches for (`verified`): bump it when the writer changes how it writes, and
#: the next write is watched again. 5: the editor is reached by its kept address (_zones), a route no
#: watched write took (the tenth reader).
WRITER_VERSIONS = {("internic", "create"): "internic-create-5 (2026-10-23)"}
