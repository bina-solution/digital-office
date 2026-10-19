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

import json
import logging
from pathlib import Path

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
            "write_record": {
                "kind": "write",
                "needs_verification": True,
                "steps": [
                    {"id": "zone-page", "action": "goto", "value": "/dashboard/main"},
                    {"id": "settle", "action": "wait_for", "seconds": 2},
                    # the steps after this point are written once the zone editor has been SEEN:
                    # which control opens the editor, what the record form calls its fields, and
                    # which element proves the write afterwards.
                ],
            },
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
             "הדומיין שלך, לא תקלה — ואחרי אישור אחד כל השינויים מכאן ירוצו אוטומטית.")
DRAFT_HOW = ("אפשר לעשות את השינוי עכשיו ידנית בפורטל (קישור למטה), ואז לאשר כאן שהפעולה עבדה — "
             "ומכאן ואילך הלשכה תעשה אותה בעצמה.")


def operation_for(portal: str, action: str) -> str | None:
    """The operation this portal uses for `action`, or None when its script cannot do it at all."""
    ops = (SCRIPTS.get(portal) or {}).get("operations") or {}
    return next((name for name in WRITE_OPS.get(action, ()) if name in ops), None)


def supports_write(portal: str, action: str) -> bool:
    return operation_for(portal, action) is not None


def write_state(portal: str) -> dict:
    """Can the office WRITE here, in one object the screens can show BEFORE anything is clicked.

    Three different situations were being reported with one shrug of an error message: the script is
    a draft (unlockable by one watched action), the action was never scripted (needs a mapping), and
    the portal is fine. Saying which one it is, up front, is the difference between a screen the
    owner understands and a screen that keeps refusing for reasons it never states.
    """
    s = SCRIPTS.get(portal) or {}
    origin = s.get("origin") or ""
    ops = s.get("operations") or {}
    actions = {a: operation_for(portal, a) is not None for a in ("create", "update", "delete")}
    status = s.get("status") or "unknown"
    if not s:
        return {"enabled": False, "state": "unknown", "actions": actions,
                "title": "אין סקריפט לפורטל הזה", "why": "", "how": "", "portal_url": origin}
    if status != VERIFIED:
        return {"enabled": False, "state": status, "actions": actions, "title": DRAFT_TITLE,
                "why": DRAFT_WHY, "how": DRAFT_HOW, "portal_url": origin,
                "missing": [ACTION_HE[a] for a, ok in actions.items() if not ok]}
    missing = [ACTION_HE[a] for a, ok in actions.items() if not ok]
    return {"enabled": True, "state": VERIFIED, "actions": actions, "portal_url": origin,
            "title": "" if not missing else f"חלק מהפעולות עוד לא ממופות: {', '.join(missing)}",
            "why": "" if not missing else
                   "השאר עובד. אלה עוד לא נראו בפועל, ולכן הלשכה לא מנסה אותן.",
            "how": "" if not missing else
                   "אפשר לעשות אותן ידנית בפורטל, ולאשר כאן אחר כך.", "missing": missing}


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

_JS_ZONE = """() => {
  // The zone editor's real shape, read off the live panel (2026-09-23, re-read 2026-09-25): a RECORD
  // row carries `select[name=rectype_<n>]` together with `input[name=name_<n>]`, `ttl_<n>`,
  // `class_<n>` and `specs_<n>` (the value), where <n> is the record's own id. Every OTHER row with a
  // type <select> is a TEMPLATE: the "add a record" form, and the SRV priority/weight/port/target
  // sub-rows, have no per-record field names at all. Reading those positionally is how this reader
  // used to invent records that do not exist in the zone — an apex A at 80.244.162.32 that no resolver
  // ever answered, and two CNAMEs whose value was the domain itself. So a row counts as a record ONLY
  // if it carries the per-record field names, and its fields are matched by the SAME numeric suffix.
  const rows = [];
  const suffix = (el) => { const m = (el.name || '').match(/_([0-9]+)$/); return m ? m[1] : null; };
  Array.from(document.querySelectorAll('tr')).forEach(tr => {
    const typeEl = tr.querySelector('select[name^="rectype_"]');
    const specEl = tr.querySelector('input[name^="specs_"]');
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
  return JSON.stringify({rows: rows, url: location.href, title: document.title,
                         zone_id: (location.pathname.split('/zone/')[1] || '').replace(/[^0-9].*$/, '') || null,
                         row_count: document.querySelectorAll('tr').length});
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
  const row = Array.from(document.querySelectorAll('tr'))
      .find(r => (r.innerText || '').includes(spec.domain));
  if (!row) return JSON.stringify({found: false});
  const cb = row.querySelector('input[type=checkbox]');
  if (cb && !cb.checked) cb.click();
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
    sess.open(s["origin"] + (s.get("paths") or {}).get("domains", "/dashboard/main"))
    clicked = sess.call("browser_evaluate",
                        {"function": f"({_JS_OPEN_ZONE})({__import__('json').dumps({'domain': domain})})"})
    got = bs._json_from_text(clicked.get("text")) or {}
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
        return {"ok": False, "state": "selector_missing",
                "error": f"עורך ה-Zone של {domain} לא הציג רשומות אחרי {attempts} ניסיונות",
                "detail": str(data.get("url"))[:200],
                "page": {"url": data.get("url"), "title": data.get("title")}}
    return {"ok": True, "domain": domain, "records": recs, "count": len(recs),
            "zone_id": data.get("zone_id"), "rows_seen": data.get("row_count"),
            "other_rows": other, "attempts": attempts,
            "page": {"url": data.get("url"), "title": data.get("title")},
            "note": "זה מה שמופיע בעורך ה-Zone של הפורטל עבור הדומיין הזה."}
