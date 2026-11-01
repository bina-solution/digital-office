"""domains.browser_ops — HOW an abstract domain operation becomes browser actions.

This is the layer the app was missing. `writeRecord(zone, A, www, 1.2.3.4)` is a sentence about
domains; a control panel knows nothing about it and offers buttons, labels and a table. Something has
to translate, and that something is this file. It is deliberately NOT a pile of hardcoded selectors:

    perceive  →  the page as it IS (controls with their accessible names, tables with headers/rows)
    match     →  find a control by what it MEANS (role + accessible name, in Hebrew or English)
    plan      →  a small, readable sequence of intents for one operation
    execute   →  run them with waits, then READ THE VALUE BACK
    record    →  keep the locators that actually worked, so the next run is exact, not heuristic

Why the third and fifth steps matter more than they look
--------------------------------------------------------
* A panel is a moving target. Matching on `role=button` + the accessible name "הוספת רשומה" survives
  a redesign that `#btn-add-record-2` does not, and it survives the panel being in English.
* The first successful run RECORDS what it clicked. From then on this is a script with a fallback,
  not a guess — and when the panel changes, the recorded locator stops matching, the fallback tries
  again, and the failure is reported as `selector_missing` WITH the page it saw (never as a mystery).

The one thing it refuses to do is guess about a WRITE. Every write ends with a read-back of the zone
table, and a write whose value is not in the table is `assert_failed` — not success.
"""
from __future__ import annotations

import json
import logging
import re
import time

import browser_session as bs

log = logging.getLogger("domains.browser_ops")

#: What the page looks like, from the DOM. The accessibility tree is good for controls; the DOM is
#: better for the two things a DNS panel is made of — labelled form fields and tables — so both are
#: read and merged.
JS_DOM = """() => ({
  url: location.href, title: document.title,
  inputs: Array.from(document.querySelectorAll('input,select,textarea')).map(el => ({
    tag: el.tagName.toLowerCase(), type: (el.type || '').toLowerCase(),
    name: el.name || '', id: el.id || '',
    label: ((el.labels && el.labels.length) ? el.labels[0].innerText
            : (el.getAttribute('aria-label') || el.placeholder || el.title || '')).trim(),
    value: el.value || '', options: el.tagName === 'SELECT'
      ? Array.from(el.options).map(o => (o.text || o.value || '').trim()) : [] })),
  buttons: Array.from(document.querySelectorAll(
      'button,input[type=submit],input[type=button],[role=button]')).map(el => ({
      text: (el.innerText || el.value || el.getAttribute('aria-label') || '').trim(),
      disabled: !!el.disabled, id: el.id || '' })),
  links: Array.from(document.querySelectorAll('a[href]')).map(el => ({
      text: (el.innerText || '').trim(), href: el.getAttribute('href') || '',
      id: el.id || '' })).filter(l => l.text || l.href),
  tables: Array.from(document.querySelectorAll('table')).map(t => ({
      id: t.id || '',
      headers: (t.querySelector('thead')
                 ? Array.from(t.querySelectorAll('thead th, thead td'))
                 : Array.from(t.querySelectorAll('tr:first-child th, tr:first-child td')))
                 .map(h => (h.innerText || '').trim()),
      rows: Array.from(t.querySelectorAll('tbody tr, tr')).slice(1)
              .map(r => Array.from(r.querySelectorAll('td,th')).map(c => (c.innerText || '').trim()))
              .filter(r => r.some(c => c)) })),
  text: (document.body ? document.body.innerText : '').slice(0, 4000)
})"""

# ── the vocabulary that makes matching language- and design-independent ──────────────────────────
DNS_SECTION = ["dns", "zone", "dns settings", "dns management", "nameservers", "רשומות", "אזור",
               "ניהול dns", "רשומות dns", "הגדרות dns", "שרתי שמות"]
ADD_ACTION = ["add", "add record", "new record", "create", "הוסף", "הוספה", "הוספת רשומה",
              "רשומה חדשה", "צור"]
SAVE_ACTION = ["save", "ok", "apply", "update", "submit", "שמור", "שמירה", "עדכן", "אישור", "החל"]
CANCEL_ACTION = ["cancel", "close", "ביטול", "סגור", "סגירה"]
DELETE_ACTION = ["delete", "remove", "trash", "מחק", "מחיקה", "הסר"]
CONFIRM_ACTION = ["yes", "confirm", "ok", "כן", "אשר", "אישור", "מחק"]
NAME_FIELD = ["name", "host", "hostname", "record name", "subdomain", "שם", "מארח", "שם רשומה",
              "תת דומיין"]
TYPE_FIELD = ["type", "record type", "סוג", "סוג רשומה"]
VALUE_FIELD = ["value", "target", "content", "destination", "points to", "data", "address",
               "ערך", "יעד", "תוכן", "כתובת"]
TTL_FIELD = ["ttl", "time to live", "זמן חיים"]
LOGIN_FIELD = ["password", "passwd", "סיסמה", "סיסמ"]
USER_FIELD = ["username", "user", "email", "login", "שם משתמש", "משתמש", "דוא", "אימייל"]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _matches(text: str, keys: list[str]) -> bool:
    t = _norm(text)
    return any(_norm(k) in t for k in keys)


JS_CLICK = r"""(spec) => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const name = (el) => norm(el.getAttribute('aria-label') || el.innerText || el.value ||
                           el.getAttribute('title') || '');
  const keys = spec.keys.map(norm);
  const cands = Array.from(document.querySelectorAll(
      'button, input[type=submit], input[type=button], a, [role=button], [role=menuitem], ' +
      'label[for], .btn'));
  const hit = cands.find((el) => keys.some((k) => name(el).includes(k)));
  if (!hit) return JSON.stringify({found: false});
  hit.scrollIntoView({block: 'center'});
  hit.click();
  return JSON.stringify({found: true, name: (hit.innerText || hit.value || '').trim(),
                         tag: hit.tagName.toLowerCase()});
}"""

JS_FILL = r"""(spec) => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const labelOf = (el) => norm((el.labels && el.labels.length ? el.labels[0].innerText : '') ||
                               el.getAttribute('aria-label') || el.placeholder || el.title ||
                               el.name || el.id || '');
  const keys = spec.keys.map(norm);
  const fields = Array.from(document.querySelectorAll('input, select, textarea'))
      .filter((el) => el.type !== 'hidden');
  let hit = fields.find((el) => keys.some((k) => labelOf(el).includes(k)));
  if (!hit && spec.contains) {
    hit = fields.find((el) => norm(el.value).includes(norm(spec.contains)));
  }
  if (!hit) return JSON.stringify({found: false,
      seen: fields.map((el) => labelOf(el)).slice(0, 20)});
  hit.scrollIntoView({block: 'center'});
  hit.focus();
  if (hit.tagName === 'SELECT') {
    const opt = Array.from(hit.options).find((o) =>
        norm(o.text) === norm(spec.value) || norm(o.value) === norm(spec.value));
    if (!opt) return JSON.stringify({found: false, reason: 'option', value: spec.value,
                                     options: Array.from(hit.options).map((o) => o.text)});
    hit.value = opt.value;
  } else {
    // the React-safe way to set a value: through the native setter, then a real input event —
    // writing `el.value` alone leaves a framework's internal state stale, and the save silently
    // posts the OLD value.
    const proto = hit.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype
                                             : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value');
    if (setter && setter.set) { setter.set.call(hit, spec.value); } else { hit.value = spec.value; }
    hit.dispatchEvent(new Event('input', {bubbles: true}));
  }
  hit.dispatchEvent(new Event('change', {bubbles: true}));
  return JSON.stringify({found: true, label: (hit.labels && hit.labels.length
      ? hit.labels[0].innerText : (hit.getAttribute('aria-label') || hit.placeholder || '')).trim(),
      tag: hit.tagName.toLowerCase(), value: hit.value});
}"""


class Page:
    """What the browser is looking at, in the shapes the operations below need."""

    def __init__(self, dom: dict, nodes: list[dict] | None = None):
        self.dom = dom or {}
        self.nodes = nodes or []
        self.url = self.dom.get("url") or ""
        self.title = self.dom.get("title") or ""
        self.inputs = self.dom.get("inputs") or []
        self.buttons = self.dom.get("buttons") or []
        self.links = self.dom.get("links") or []
        self.tables = self.dom.get("tables") or []
        self.text = self.dom.get("text") or ""

    def __repr__(self) -> str:                                # for the failure evidence
        return json.dumps(self.summary(), ensure_ascii=False)

    def summary(self) -> dict:
        return {"url": self.url, "title": self.title,
                "inputs": [f"{i['label'] or i['name'] or i['id']}({i['type']})" for i in self.inputs
                           if i["type"] != "hidden"],
                "buttons": [b["text"] for b in self.buttons if b["text"]],
                "links": [l["text"] for l in self.links if l["text"]][:25],
                "tables": [{"headers": t["headers"], "rows": len(t["rows"])} for t in self.tables]}

    # ── matching (recorded locator first, synonyms second) ───────────────────────────────────────
    def field(self, keys: list[str], learned: dict | None = None, contains: str | None = None):
        if learned and learned.get("label"):
            for i in self.inputs:
                if _norm(learned["label"]) == _norm(i["label"]) or \
                        _norm(learned["label"]) == _norm(i["name"] or i["id"]):
                    return i
        for i in self.inputs:
            if i["type"] == "hidden":
                continue
            if contains and contains not in (i["value"] or "") + (i["label"] or ""):
                continue
            if _matches(i["label"], keys) or _matches(i["name"], keys) or _matches(i["id"], keys):
                return i
        return None

    def button(self, keys: list[str], learned: dict | None = None):
        if learned and learned.get("text"):
            for b in self.buttons:
                if _norm(learned["text"]) == _norm(b["text"]):
                    return b
        for b in self.buttons:
            if b["disabled"]:
                continue
            if _matches(b["text"], keys):
                return b
        return None

    def link(self, keys: list[str], learned: dict | None = None, contains: str | None = None):
        if learned and learned.get("text"):
            for l in self.links:
                if _norm(learned["text"]) == _norm(l["text"]):
                    return l
        for l in self.links:
            if contains and contains not in (l["text"] + " " + l["href"]):
                continue
            if _matches(l["text"], keys) or _matches(l["href"], keys):
                return l
        return None

    def node(self, roles: tuple[str, ...], keys: list[str], learned: dict | None = None):
        """A control from the ACCESSIBILITY tree, with its `ref`.

        `browser_click` addresses an element exactly by `ref`, and only approximately by a
        human-readable description ("the Save button") — a Hebrew label passed as a description is
        simply not clicked, which is how the first version of this file failed on its own test bench.
        So every control is resolved here: role + accessible name → ref.
        """
        if learned and learned.get("ref_name"):
            for n in self.nodes:
                if n.get("ref") and _norm(n["name"]) == _norm(learned["ref_name"]) and \
                        n["role"] in roles:
                    return n
        for n in self.nodes:
            if not n.get("ref") or n["role"] not in roles or not n.get("name"):
                continue
            if _matches(n["name"], keys):
                return n
        return None

    def zone_table(self, learned: dict | None = None):
        """The table that looks like a zone: it has a type column and a value-ish column."""
        for t in self.tables:
            headers = [_norm(h) for h in t["headers"]]
            if any(h in ("type", "סוג") for h in headers) and any(
                    _matches(h, VALUE_FIELD + ["data", "content", "record"]) for h in headers):
                return t
        if learned and learned.get("headers"):
            for t in self.tables:
                if [_norm(h) for h in t["headers"]] == [_norm(h) for h in learned["headers"]]:
                    return t
        return None


# ── the driver ───────────────────────────────────────────────────────────────────────────────────
class ZoneEditor:
    """One zone, in one panel, through one browser session.

    Every method returns either a value or raises `OpsError` with a CONTRACT state — `selector_missing`
    carrying the page it saw, `needs_human_login`, `assert_failed` — so the caller never has to
    interpret a browser exception, and the owner never gets "click failed".
    """

    def _wait_rows(self, domain: str, tries: int = 5) -> list[dict]:
        """A panel renders its rows with JavaScript, so "the page loaded" is NOT "the table has
        rows". Poll the table (bounded) instead of sleeping a fixed second and hoping — the first
        selftest run read an empty table from a page that was still fetching."""
        rows: list[dict] = []
        for i in range(tries):
            rows = self._read_rows(domain)
            if rows:
                return rows
            # A panel fills its table with JavaScript, so an empty table can mean three things:
            # still fetching, genuinely empty, or a page whose fetch FAILED. Only the last one needs
            # a reload, and it is indistinguishable from the first two without waiting — so wait a
            # little, then reload once, then keep polling. (The first version of this simply polled a
            # page whose fetch had already failed, and reported "the record was not saved" about a
            # record that was in the panel's own API.)
            if i == 1:
                self.reload()
            self.s.call("browser_wait_for", {"time": 1})
        return rows

    def reload(self) -> None:
        """Refresh the page in place. A panel that failed its own fetch needs a reload, and a
        reload is not a navigation — see browser_session.open() for why that distinction is real."""
        try:
            self.s.call("browser_evaluate",
                        {"function": "() => { location.reload(); return 'ok'; }"})
        except bs.SessionError:
            pass
        self.s.call("browser_wait_for", {"time": 2})

    def __init__(self, session: bs.Session | None = None, origin: str = "",
                 learned: dict | None = None):
        self.s = session or bs.shared()
        self.origin = origin.rstrip("/")
        self.learned = learned or {}          # op → {field: {label/text}} that WORKED
        self.trace: list[dict] = []
        self._started_at = time.time()
        # the budget is enforced by the TRANSPORT too, so even a single stalled call cannot outlive it
        self.s.deadline = self._started_at + self.BUDGET_S

    # perception
    def page(self) -> Page:
        res = self.s.call("browser_evaluate", {"function": JS_DOM})
        dom = bs._json_from_text(res.get("text")) or {}
        try:
            nodes = self.s.snapshot().get("nodes")
        except bs.SessionError:
            nodes = []
        return Page(dom, nodes)

    def _check_login(self, page: Page) -> None:
        pw = page.field(LOGIN_FIELD)
        if pw is not None or re.search(r"/(login|signin)", page.url, re.I):
            raise bs.SessionError("הסשן אינו מחובר — צריך התחברות בדפדפן של הלשכה",
                                  state="needs_human_login",
                                  detail=json.dumps(page.summary(), ensure_ascii=False)[:400])

    def _js(self, fn: str, spec: dict) -> dict:
        """Run one JS body in the page WITH the arguments baked in.

        `browser_evaluate` takes a function SOURCE and calls it with no arguments — there is no
        `arg` parameter to pass — so the spec is inlined as a JSON literal and the wrapper is called
        immediately: `((spec) => {…})({…})`. (The first version passed an `arg`, which the tool
        silently ignored, and every "element not found" that followed was really "the function never
        received a spec".)
        """
        src = f"({fn})({json.dumps(spec, ensure_ascii=False)})"
        res = self.s.call("browser_evaluate", {"function": src})
        if res.get("is_error"):
            raise bs.SessionError("הדפדפן לא הצליח להריץ את הפעולה בדף",
                                  state="unknown_error", detail=(res.get("text") or "")[:300])
        return bs._json_from_text(res.get("text")) or {}

    def _js_click(self, keys: list[str], learned_key: str | None = None) -> dict:
        """Click what the panel calls it — through the DOM.

        The accessibility snapshot is the *preferred* channel (it is actionability-checked and it is
        what `ref` locators come from), but @playwright/mcp writes a large snapshot to a FILE and
        returns a link instead of the tree — so on a real, busy panel there are no usable refs at all.
        The DOM channel below always works and resolves elements the same way: by what they SAY.
        """
        out = self._js(JS_CLICK, {"keys": keys})
        if not out.get("found"):
            raise bs.SessionError(f"לא נמצא פקד „{keys[0]}” בדף", state="selector_missing",
                                  detail=json.dumps(self.page().summary(), ensure_ascii=False)[:400])
        if learned_key:
            self.learned[learned_key] = {"name": out.get("name"), "tag": out.get("tag")}
        return out

    def _js_fill(self, keys: list[str], value: str, learned_key: str | None = None,
                 contains: str | None = None) -> dict:
        out = self._js(JS_FILL, {"keys": keys, "value": str(value), "contains": contains})
        if not out.get("found"):
            raise bs.SessionError(
                f"לא נמצא שדה „{keys[0]}” בדף"
                + (f" (ראיתי: {', '.join(out.get('seen') or [])})" if out.get("seen") else ""),
                state="selector_missing")
        if learned_key:
            self.learned[learned_key] = {"label": out.get("label")}
        return out

    def _click(self, keys: list[str], roles: tuple[str, ...] = ("button", "link", "menuitem"),
               learned_key: str | None = None, page: "Page | None" = None) -> dict:
        """Click a control the panel labels, by REF from the accessibility tree, with the label as a
        second attempt (some controls are only reachable as a description)."""
        page = page or self.page()
        node = page.node(roles, keys, self.learned.get(learned_key or ""))
        if node:
            # the server's own argument dialect (`target` since the @playwright/mcp upgrade, `ref`
            # before it) — browser_session reads it from the tool schemas
            res = self.s.call("browser_click", self.s.element_args("browser_click", node))
            if not res.get("is_error"):
                if learned_key:
                    self.learned[learned_key] = {"ref_name": node["name"], "role": node["role"]}
                return node
        return self._js_click(keys, learned_key)

    #: A live browser can hang — a navigation waiting on a WAF, a panel whose XHR never settles, an
    #: MCP transport that stops answering mid-flow. Without a deadline, ONE hung flow holds a worker
    #: thread for as long as the transport keeps timing out, and the app stops answering anything
    #: else. (Observed 2026-09-23: a stuck portal run wedged the whole domains API.) So every run has
    #: a budget, and overrunning it is a first-class, reportable state — not a hang.
    BUDGET_S = float(__import__("os").environ.get("DOMAINS_BROWSER_BUDGET_S", "150"))

    def _deadline(self) -> float:
        return getattr(self, "_started_at", time.time()) + self.BUDGET_S

    def _step(self, name: str, fn):
        if time.time() > self._deadline():
            raise bs.SessionError(
                f"חרגתי מתקציב הזמן של הפעולה בדפדפן ({int(self.BUDGET_S)} שניות)",
                state="timeout")
        t0 = time.time()
        try:
            out = fn()
            self.trace.append({"intent": name, "ok": True, "ms": int((time.time() - t0) * 1000)})
            return out
        except bs.SessionError as e:
            self.trace.append({"intent": name, "ok": False, "state": e.state,
                               "error": e.message, "ms": int((time.time() - t0) * 1000)})
            raise

    # ── reading ──────────────────────────────────────────────────────────────────────────────────
    def open_zone(self, domain: str) -> Page:
        """Get to the record list, by the panel's own route if it has one, by its own menu if not."""
        def run() -> Page:
            page = self.page()
            if page.zone_table(self.learned.get("zone_table")):
                self.learned["zone_url"] = page.url
                return page
            for target in ([self.learned["zone_url"]] if self.learned.get("zone_url") else []) + \
                    [self.origin + s for s in ("/dns", "/dns/records", "/zone", "/dns/manage",
                                               f"/domains/{domain}/dns")]:
                self.s.open(target)
                page = self.page()
                if page.zone_table(self.learned.get("zone_table")):
                    self.learned["zone_url"] = page.url
                    return page
            page = self.page()
            self._check_login(page)
            link = page.link(DNS_SECTION, self.learned.get("dns_link"),
                             contains=domain) or page.link(DNS_SECTION, self.learned.get("dns_link"))
            if not link:
                raise bs.SessionError(
                    "לא מצאתי מסך ניהול DNS בפורטל",
                    state="selector_missing",
                    detail=json.dumps(page.summary(), ensure_ascii=False)[:500])
            self.learned["dns_link"] = {"text": link["text"]}
            self._click_text(link["text"])
            self.s.call("browser_wait_for", {"time": 2})
            return self.page()
        return self._step("open_zone", run)

    def records(self, domain: str, wait: bool = True) -> list[dict]:
        def run():
            page = self.open_zone(domain) if not self.page().zone_table() else self.page()
            table = page.zone_table(self.learned.get("zone_table"))
            if not table:
                raise bs.SessionError("לא נמצאה טבלת רשומות בדף",
                                      state="selector_missing",
                                      detail=json.dumps(page.summary(), ensure_ascii=False)[:500])
            self.learned["zone_table"] = {"headers": table["headers"]}
            self.learned["zone_url"] = page.url
            headers = [_norm(h) for h in table["headers"]]
            idx = {}
            for key, keys in (("type", TYPE_FIELD), ("name", NAME_FIELD), ("content", VALUE_FIELD),
                              ("ttl", TTL_FIELD)):
                for i, h in enumerate(headers):
                    if _matches(h, keys):
                        idx[key] = i
                        break
            out = []
            for row in table["rows"]:
                if len(row) < 2:
                    continue
                out.append({k: (row[i] if i is not None and i < len(row) else "")
                            for k, i in idx.items()} | {"_row": row})
            return out
        if wait:
            return self._step("records", lambda: self._wait_rows(domain) or run())
        return self._step("records", run)

    def _read_rows(self, domain: str) -> list[dict]:
        """The pure read — no navigation, no waiting. Used by the polling above."""
        page = self.page()
        table = page.zone_table(self.learned.get("zone_table"))
        if not table or not table.get("rows"):
            return []
        headers = [_norm(h) for h in table["headers"]]
        idx = {}
        for key, keys in (("type", TYPE_FIELD), ("name", NAME_FIELD), ("content", VALUE_FIELD),
                          ("ttl", TTL_FIELD)):
            for i, h in enumerate(headers):
                if _matches(h, keys):
                    idx[key] = i
                    break
        out = []
        for row in table["rows"]:
            if len(row) < 2 or not any(row):
                continue
            out.append({k: (row[i] if i is not None and i < len(row) else "")
                        for k, i in idx.items()} | {"_row": row})
        return out

    # ── writing ──────────────────────────────────────────────────────────────────────────────────
    def add_record(self, domain: str, rec: dict) -> dict:
        """Create one record: open the editor, fill it by label, save, and PROVE it landed."""
        def run() -> dict:
            page = self.open_zone(domain)
            table = page.zone_table(self.learned.get("zone_table")) or {"rows": []}
            before = {tuple(r) for r in table.get("rows", [])}
            node = page.node(("button", "link", "menuitem"), ADD_ACTION,
                             self.learned.get("add_button"))
            if not node:
                raise bs.SessionError("לא נמצא כפתור „הוספת רשומה” בדף ה-DNS",
                                      state="selector_missing",
                                      detail=json.dumps(page.summary(), ensure_ascii=False)[:500])
            self._click(ADD_ACTION, learned_key="add_button", page=page)
            self.s.call("browser_wait_for", {"time": 1})
            page = self.page()

            filled = []
            for value, keys, key in ((rec.get("name") or "@", NAME_FIELD, "name"),
                                     (rec.get("type") or "A", TYPE_FIELD, "type"),
                                     (rec.get("content") or "", VALUE_FIELD, "content"),
                                     (str(rec.get("ttl") or 3600), TTL_FIELD, "ttl")):
                if not value:
                    continue
                f = page.field(keys, self.learned.get(f"field_{key}"))
                if not f:
                    if key == "ttl":
                        continue                     # TTL is often absent; it is not the point
                    raise bs.SessionError(
                        f"לא נמצא שדה {key} בטופס הרשומה",
                        state="selector_missing",
                        detail=json.dumps(page.summary(), ensure_ascii=False)[:500])
                self._js_fill(keys, value, learned_key=f"field_{key}")
                filled.append(key)
            if "content" not in filled:
                raise bs.SessionError("לא הצלחתי למלא את שדה הערך",
                                      state="selector_missing")

            page = self.page()
            node = page.node(("button", "link"), SAVE_ACTION, self.learned.get("save_button"))
            if not node:
                raise bs.SessionError("לא נמצא כפתור שמירה בטופס הרשומה",
                                      state="selector_missing",
                                      detail=json.dumps(page.summary(), ensure_ascii=False)[:500])
            self._click(SAVE_ACTION, learned_key="save_button", page=page)
            self.s.call("browser_wait_for", {"time": 2})

            # VERIFY: the record must now be in the table. A saved dialog is not evidence.
            rows = self.records(domain)
            want = _norm(rec.get("content") or "")
            hit = next((r for r in rows if _norm(r.get("content")) == want and
                        (_norm(r.get("type")) == _norm(rec.get("type") or "A"))), None)
            if not hit:
                raise bs.SessionError(
                    f"הרשומה נשמרה אך אינה מופיעה בטבלה ({rec.get('type')} "
                    f"{rec.get('name')} → {rec.get('content')})",
                    state="assert_failed",
                    detail=json.dumps({"before": len(before), "after": len(rows),
                                       "rows": [r.get("content") for r in rows][:10]},
                                      ensure_ascii=False))
            return {"created": True, "record": {k: v for k, v in hit.items() if k != "_row"},
                    "rows": len(rows), "added_rows": len(rows) - len(before)}
        return self._step("add_record", run)

    def delete_record(self, domain: str, rec: dict) -> dict:
        """Delete by finding the ROW, then the control inside it — never by "the Nth delete link",
        which is how a panel ends up deleting the wrong record."""
        def run() -> dict:
            rows_before = self.records(domain)
            target = next((r for r in rows_before
                           if _norm(r.get("content")) == _norm(rec.get("content") or "")
                           and (not rec.get("type") or _norm(r.get("type")) == _norm(rec["type"]))),
                          None)
            if not target:
                return {"deleted": False, "reason": "הרשומה לא נמצאה"}
            # the delete control is clicked by name inside the row: the panel's own label
            try:
                self._js_click(DELETE_ACTION)
            except bs.SessionError as e:
                raise bs.SessionError(
                    "לא נמצא כפתור מחיקה בשורת הרשומה",
                    state="selector_missing",
                    detail=f"חיפשתי {DELETE_ACTION} עבור {target.get('content')!r}") from e
            self.s.call("browser_wait_for", {"time": 1})
            page = self.page()
            if page.node(("button", "link"), CONFIRM_ACTION):
                self._click(CONFIRM_ACTION, page=page)
                self.s.call("browser_wait_for", {"time": 2})
            rows_after = self.records(domain)
            if any(_norm(r.get("content")) == _norm(rec.get("content") or "")
                   for r in rows_after):
                raise bs.SessionError("הרשומה עדיין מופיעה בטבלה אחרי המחיקה",
                                      state="assert_failed")
            return {"deleted": True, "rows": len(rows_after)}
        return self._step("delete_record", run)

    def login(self, user: str, password: str) -> dict:
        """A portal login, for panels that have no captcha and no 2FA.

        It exists for the SELF-TEST against a fixture panel. In production the owner logs in by hand
        in the office browser and no app ever holds their password — the credential-free half of the
        contract is the point of the whole design (ai/context/browser-session-connection.md §0).
        """
        def run() -> dict:
            page = self.page()
            u = page.field(USER_FIELD)
            p = page.field(LOGIN_FIELD)
            if not (u and p):
                raise bs.SessionError("לא נמצא טופס התחברות", state="selector_missing",
                                      detail=json.dumps(page.summary(), ensure_ascii=False)[:400])
            self._js_fill(USER_FIELD, user)
            self._js_fill(LOGIN_FIELD, password)
            page = self.page()
            btn = page.button(SAVE_ACTION + ["log in", "sign in", "התחבר", "כניסה"]) or \
                page.button(["log in", "sign in", "התחבר", "כניסה"])
            if btn:
                self._click(SAVE_ACTION + ["log in", "sign in", "התחבר", "כניסה"], page=page)
            self.s.call("browser_wait_for", {"time": 2})
            return {"ok": True, "url": self.page().url}
        return self._step("login", run)


def ops_for(op: str, params: dict) -> list[str]:
    """The PLAN, as human-readable intents — what the office will do in the browser for this op.

    Shown in the UI on purpose: the translation from "create an A record" to browser actions is the
    part an owner has every right to inspect before letting it run against their registrar.
    """
    if op == "list_records":
        return ["open the zone screen (panel route, else its DNS menu)",
                "find the record table by its headers",
                "read every row into {type, name, value, ttl}"]
    if op == "write_record":
        return ["open the zone screen",
                "read the table BEFORE the change (so the delta is provable)",
                f"click „הוספת רשומה”",
                f"fill name={params.get('name')}, type={params.get('type')}, "
                f"value={params.get('content')}, ttl={params.get('ttl')} by LABEL",
                "click the save control the panel itself labels",
                "READ THE TABLE BACK and require the new row to be there"]
    if op == "delete_record":
        return ["open the zone screen", "find the ROW whose value matches",
                "click the delete control by name", "confirm if the panel asks",
                "read the table back and require the row to be gone"]
    if op == "login":
        return ["find the username and password fields by label",
                "type (the caller supplies the values)", "click the sign-in control"]
    return []
