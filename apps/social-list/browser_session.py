# Lifted from apps/domains/browser_session.py — ai/context/web-engine.md marks it "generic (lift as-is)". The only
# edits are the logger name and (webengine) the env names of the DB path. Keep the two copies in step.
"""domains.browser_session — the reference client for `browser_session.v1`
(ai/context/browser-session-connection.md).

Why this file exists at all, in an app about domains
----------------------------------------------------
Because the office's own registrar publishes no API. When the only way to act on a service is the
way a human acts on it, an app has exactly two honest options: say it cannot, or drive the browser
the owner already logged into. This module is the second option, and it is written as a CONTRACT
rather than as a scraper: five ops about a session and a page (`state`, `open`, `read`, `act`,
`screen`), a fixed vocabulary of failure states, and the rule that a state needing a human stops
everything.

Transport, and why it is behind one class
-----------------------------------------
Today the office browser (`apps/browser42`) exposes `@playwright/mcp` over HTTP with a bearer token;
tomorrow it may expose the REST ops of the contract directly. Consumers must not care, so the MCP
JSON-RPC handshake, the SSE decoding and the accessibility-snapshot parsing all live HERE, and
`Session.state/open/read/act/screen` is the only surface an app ever calls.

Three decisions worth arguing with, all deliberate:

  * **locators are resolved from the live accessibility tree**, by role and accessible name, and only
    then by CSS. The contract says why: an accessible name is what the page MEANS, a CSS path is a
    transcription of today's markup.
  * **every action is verified by reading the value back** — the same rule the sites app applies to a
    deploy. "The click succeeded" is not evidence that a record changed.
  * **a session that needs a human never retries.** `needs_human_login` / `needs_2fa` / `captcha` /
    `session_expired` stop the flow, keep the screen, and tell the owner. Retrying is how an account
    gets locked, and the lockout costs more than the action was ever worth.
"""
from __future__ import annotations

import base64
import contextlib
import json
import logging
import os
import re
import threading
import time

import requests

log = logging.getLogger("browser_session")

DEFAULT_ENDPOINT = os.environ.get("BROWSER_SESSION_ENDPOINT", "http://browser42-caddy:80/mcp")
TOKEN = os.environ.get("BROWSER42_MCP_TOKEN", "")
TIMEOUT = int(os.environ.get("BROWSER_SESSION_TIMEOUT", "45"))

#: The states of the contract. `HUMAN` states stop everything and are reported, never retried.
OK = "ok"
NEEDS_HUMAN = ("needs_human_login", "needs_2fa", "captcha", "session_expired")
HARD_STOP = NEEDS_HUMAN + ("selector_missing", "assert_failed", "blocked", "unknown_error")

LOGIN_HINTS = re.compile(
    r"(sign\s?in|log\s?in|התחברות|כניסה|התחבר|password|סיסמה|connexion|anmelden)", re.I)


def fix_text(s: str) -> str:
    """Repair the one encoding bug every MCP-over-HTTP hop seems to grow.

    The accessibility snapshot of a Hebrew page arrives as `×©× ××©×ª××©` — UTF-8 bytes that were
    decoded as cp1252 somewhere in the transport and then re-encoded. It is not the PAGE's problem
    (the page is fine) and it is not something a Hebrew-only app can ignore: a locator that matches
    an accessible name is matching a name nobody can read. Repaired once, here, so every reader of
    this module gets real text.
    """
    if not s or not isinstance(s, str):
        return s or ""
    if not any(ch in s for ch in "×ÃÂ"):
        return s
    for enc in ("cp1252", "latin-1"):
        try:
            return s.encode(enc).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return s


#: One JS probe answers the whole "am I logged in?" question, because the accessibility tree does
#: not: this office's own registrar renders its password field as a plain textbox with a Hebrew
#: placeholder, and a snapshot-only check happily reported a logged-in session ON THE LOGIN PAGE.
#: (Found 2026-09-23, driving the real portal.) The DOM knows; ask it.
JS_PROBE = """() => ({
  url: location.href,
  title: document.title || '',
  text: (document.body ? document.body.innerText : '').slice(0, 1200),
  len: document.body ? document.body.innerText.length : 0,
  forms: document.forms.length,
  links: document.links.length,
  password_fields: document.querySelectorAll('input[type=password]').length,
  passwordish: Array.from(document.querySelectorAll('input')).filter(
    i => /password|passwd|סיסמה|סיסמ/i.test((i.type||'')+(i.name||'')+(i.id||'')+
         (i.placeholder||'')+(i.getAttribute('aria-label')||''))).length,
  login_words: /(התחברות|כניסה למערכת|שכחת סיסמה|sign in|log in|password|סיסמה)/i.test(
    document.body ? document.body.innerText : ''),
  challenge: /(incapsula|request unsuccessful|incident id|just a moment|checking your browser)/i
    .test((document.title||'') + ' ' + (document.body ? document.body.innerText : ''))
})"""


class SessionError(Exception):
    """A failure of the CONTRACT, not of the page: transport, handshake, or an unsupported op."""

    def __init__(self, message: str, *, state: str = "unknown_error", detail: str | None = None):
        super().__init__(message)
        self.message = message
        self.state = state
        self.detail = detail


#: ONE session per process, deliberately.
#:
#: Every `initialize` opens a session in the MCP server, and the first version of this module opened
#: a new one per call — including on every `/api/browser` health check. After an hour of that the
#: browser's MCP process had accumulated dozens of live sessions, was logging
#: `MaxListenersExceededWarning: 11 unhandledRejection listeners`, and started answering requests with
#: "aborting with incomplete response: context canceled" — which surfaced as
#: "הדפדפן של הלשכה אינו זמין (ConnectionError)" in the middle of a flow. The office has exactly one
#: browser and one conversation with it.
_shared: "Session | None" = None
_shared_lock = threading.Lock()
_avail_cache: dict = {"at": 0.0, "value": None}
AVAIL_TTL = 30.0


#: ONE browser, ONE driver at a time. The office browser is a single Chromium with a single set of
#: tabs, so two threads reading through it do not merely go slowly — they open tabs for each other,
#: navigate each other's pages and close each other's work. Every flow that drives the browser takes
#: this lock; the timeout is longer than a whole flow's budget so a stuck reader fails loudly instead
#: of deadlocking every other one forever.
_DRIVE = threading.RLock()


@contextlib.contextmanager
def driving(timeout: float = 240.0):
    got = _DRIVE.acquire(timeout=timeout)
    if not got:
        raise SessionError("הדפדפן תפוס בפעולה אחרת ולא התפנה בזמן", state="timeout",
                           detail=f"waited {timeout}s")
    try:
        yield
    finally:
        _DRIVE.release()


def shared() -> "Session":
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = Session()
        return _shared


def reset_shared() -> None:
    """Drop the shared session so the next call re-handshakes (used after a transport failure)."""
    global _shared
    with _shared_lock:
        _shared = None
        _avail_cache["value"] = None


def available(force: bool = False) -> dict:
    """Is a browser session reachable at all? Never raises — the app must render without one."""
    if not TOKEN:
        return {"available": False, "reason": "לא הוגדר טוקן לדפדפן של הלשכה",
                "endpoint": DEFAULT_ENDPOINT, "how": "הגדר BROWSER42_MCP_TOKEN (מסך „דפדפן”)."}
    now = time.time()
    if not force and _avail_cache["value"] and now - _avail_cache["at"] < AVAIL_TTL:
        return _avail_cache["value"]
    try:
        s = shared()
        tools = s.tools()
        out = {"available": True, "endpoint": s.endpoint, "tools": len(tools),
               "has_snapshot": "browser_snapshot" in tools}
    except SessionError as e:
        reset_shared()
        out = {"available": False, "reason": e.message, "detail": e.detail,
               "endpoint": DEFAULT_ENDPOINT}
    _avail_cache.update({"at": now, "value": out})
    return out


class Session:
    """One conversation with the office browser. Create, use, drop — it is cheap and stateless; the
    browser holds the session, this object holds a JSON-RPC round trip."""

    def __init__(self, endpoint: str | None = None, token: str | None = None,
                 group: str | None = None):
        self.endpoint = (endpoint or DEFAULT_ENDPOINT).rstrip("/")
        self.token = token if token is not None else TOKEN
        self.group = group                      # the tab group: this app's tabs, nobody else's
        self.sid: str | None = None
        self._ready = False
        self._id = 0
        self._tools: list[str] = []
        self._schemas: dict[str, dict] = {}

    # ── transport ────────────────────────────────────────────────────────────────────────────────
    #: A whole SESSION's budget, shared by every call in it. Set by the caller (`ZoneEditor`), and
    #: enforced here rather than only between steps: one MCP call can block for its own timeout, and
    #: a flow of twenty of them held this app's worker for minutes (observed 2026-09-23, with the
    #: API going unhealthy while a portal run waited on a browser that was not answering).
    deadline: float | None = None

    def _post(self, payload: dict, expect_reply: bool = True) -> dict | None:
        if self.deadline and time.time() > self.deadline:
            raise SessionError("חרגתי מתקציב הזמן של הפעולה בדפדפן", state="timeout")
        headers = {"content-type": "application/json",
                   "accept": "application/json, text/event-stream"}
        if self.token:
            headers["authorization"] = f"Bearer {self.token}"
        if self.sid:
            headers["mcp-session-id"] = self.sid
        try:
            r = requests.post(self.endpoint, json=payload, headers=headers, timeout=TIMEOUT)
        except requests.RequestException as e:
            # ONE retry with a fresh handshake. The office's Docker DNS is demonstrably flaky under
            # load ("lookup browser42-browser on 127.0.0.11:53: server misbehaving" appears in the
            # browser's own logs), and a session that the server has dropped answers nothing. Both
            # are transient, and both look identical from here — so the retry is unconditional, and
            # the second failure is the real one.
            if getattr(self, "_retried", False):
                raise SessionError("הדפדפן של הלשכה אינו זמין",
                                   detail=str(e)[:300]) from e
            self._retried = True
            self.sid = None
            self._ready = False
            try:
                r = requests.post(self.endpoint, json=payload,
                                  headers={k: v for k, v in headers.items()
                                           if k != "mcp-session-id"}, timeout=TIMEOUT)
            except requests.RequestException as e2:
                raise SessionError("הדפדפן של הלשכה אינו זמין",
                                   detail=str(e2)[:300]) from e2
        finally:
            self._retried = False
        sid = r.headers.get("mcp-session-id")
        if sid:
            self.sid = sid
        if r.status_code == 401:
            raise SessionError("הטוקן של הדפדפן נדחה — בדוק את BROWSER42_MCP_TOKEN",
                               state="blocked")
        if r.status_code >= 300 and not r.content:
            raise SessionError(f"הדפדפן החזיר {r.status_code}", state="unknown_error")
        if not expect_reply:
            return None
        return self._decode(r.text)

    @staticmethod
    def _decode(text: str) -> dict:
        """MCP answers as JSON or as an SSE stream (`event: message\\ndata: {...}`). Both are one
        message here, and a client that handles only one of them works until the server changes its
        mind about which."""
        text = (text or "").strip()
        if not text:
            return {}
        if text.startswith("{"):
            try:
                return json.loads(text)
            except ValueError as e:
                raise SessionError("הדפדפן החזיר JSON פגום", detail=text[:200]) from e
        for line in text.splitlines():
            if line.startswith("data:"):
                try:
                    return json.loads(line[5:].strip())
                except ValueError:
                    continue
        # A big evaluate result comes back as an SSE stream whose `data:` line is long, or as a
        # MULTI-line SSE payload that a naive line-by-line reader cannot see. Find the first JSON
        # object anywhere in the body before giving up: the alternative is calling a perfectly valid
        # answer "unintelligible", which is what happened when reading a real zone editor.
        obj = _json_from_text(text)
        if obj is not None:
            return obj
        raise SessionError("הדפדפן החזיר תשובה שאינה מובנת", detail=text[:200])

    def _rpc(self, method: str, params: dict | None = None, _retry: bool = True) -> dict:
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            msg["params"] = params
        out = self._post(msg) or {}
        err = out.get("error")
        if err:
            text = json.dumps(err)
            # A session the server no longer knows ("Server not initialized", an unknown
            # `mcp-session-id`) is a HANDSHAKE problem, not a browser problem: re-initialize once and
            # retry the very same call. Without this, a single dropped session turns into
            # "the browser is unavailable" for every later call in a long-lived process — which is
            # exactly what happened the first time this app drove a real portal.
            if _retry and re.search(r"not initialized|session (not found|expired|invalid)",
                                    text, re.I):
                log.info("mcp session dropped (%s) — re-handshaking", text[:80])
                self.sid = None
                self._handshake()
                return self._rpc(method, params, _retry=False)
            raise SessionError(f"שגיאה מהדפדפן: {err.get('message') or err}",
                               detail=text[:300])
        return out.get("result") or {}

    def _handshake(self) -> None:
        """initialize + the initialized notification. Always sent, never assumed.

        The `initialize` RESULT is what proves the server opened a session; the `mcp-session-id`
        header is nice to have and not always present, so a session that "exists" only because
        `self.sid` was set is a session that will fail on the next call.
        """
        try:
            self._rpc("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "bina-domains", "version": "1.0"},
            }, _retry=False)
        except SessionError as e:
            # "Server already initialized" is a SUCCESS in disguise: the office has one browser and
            # one conversation with it, and a second handshake against a live session is refused
            # rather than duplicated. Treating it as a failure made every call after the first look
            # like an outage — the same class of mistake as reading a 200 WAF challenge as "up".
            if "already initialized" not in f"{e.message} {e.detail or ''}".lower():
                raise
            log.info("mcp session already initialized — reusing it")
        # `notifications/initialized` is a NOTIFICATION: no id, and the server answers nothing.
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, expect_reply=False)

    def connect(self) -> "Session":
        if not self._ready:
            self._handshake()
            self._ready = True
        return self

    def tools(self) -> list[str]:
        if self._tools:
            return self._tools
        self.connect()                      # tools/list is refused before the handshake
        res = self._rpc("tools/list", {})
        self._tools = [t.get("name") for t in (res.get("tools") or []) if t.get("name")]
        self._schemas = {t.get("name"): (t.get("inputSchema") or {}) for t in (res.get("tools") or [])
                         if t.get("name")}
        return self._tools

    # ── the server's argument dialect ─────────────────────────────────────────────────────────────
    #: `@playwright/mcp` renamed the element argument from `ref` to `target` (which also accepts a
    #: unique CSS selector) and made `scale` required on screenshots. The office browser runs
    #: `@playwright/mcp@latest`, so the dialect is READ from the server's own tool schemas, never
    #: assumed — measured 2026-09-29: every click/type sent with `ref` failed with "Invalid
    #: arguments … expected string, received undefined at target" after the upgrade.
    def _props(self, tool: str) -> dict:
        if not self._schemas:
            try:
                self.tools()
            except SessionError:
                return {}
        return (self._schemas.get(tool) or {}).get("properties") or {}

    def element_args(self, tool: str, node: dict) -> dict:
        """{element, target|ref} for a node from the snapshot (or a CSS node from `locate`)."""
        name = node.get("name") or node.get("css") or node.get("role") or "element"
        if "target" in self._props(tool):
            return {"element": name, "target": node.get("ref") or node.get("css")}
        return {k: v for k, v in {"element": name, "ref": node.get("ref")}.items() if v}

    def screenshot_args(self) -> dict:
        props = self._props("browser_take_screenshot")
        return {"scale": "css"} if "scale" in props else {}

    def call(self, tool: str, args: dict | None = None, _fresh_retry: bool = True) -> dict:
        """Call one browser tool; on a DEAD SESSION, start a brand-new one and try once more.

        Re-handshaking on the same object is not enough when the server has forgotten the session
        entirely: it answers "Server not initialized" for the new handshake too. The office has one
        browser, so the recovery is to DROP the conversation and open a clean one — which is cheap
        and always correct. (Learned the hard way: this is the difference between a flow that works
        after the browser has been rebuilt and one that reports a phantom outage.)
        """
        try:
            return self._call(tool, args)
        except SessionError as e:
            if _fresh_retry and re.search(r"not initialized|session (not found|expired|invalid)",
                                          f"{e.message} {e.detail or ''}", re.I):
                log.info("mcp session is gone — opening a fresh one")
                reset_shared()
                return shared().call(tool, args, _fresh_retry=False)
            raise

    def _call(self, tool: str, args: dict | None = None) -> dict:
        """Call one browser tool and return `{text, image, is_error}` — normalized, because the MCP
        result shape (content blocks of text/image) is transport detail, not something an app should
        parse in every check it writes."""
        self.connect()
        res = self._rpc("tools/call", {"name": tool, "arguments": args or {}})
        out = {"text": "", "image": None, "is_error": bool(res.get("isError"))}
        for block in res.get("content") or []:
            if block.get("type") == "text":
                out["text"] += fix_text(block.get("text"))
            elif block.get("type") == "image":
                out["image"] = block.get("data")
        if out["is_error"]:
            out["error"] = out["text"][:400]
        return out

    # ── the contract's five ops ──────────────────────────────────────────────────────────────────
    def current_url(self) -> str:
        """Where the browser is, asked cheaply (one JS call, no navigation)."""
        try:
            res = self.call("browser_evaluate", {"function": "() => location.href"})
            m = re.search(r"https?://\S+", res.get("text") or "")
            return (m.group(0) if m else "").rstrip('"').strip()
        except SessionError:
            return ""

    def open(self, url: str, retries: int = 1, snapshot: bool = True) -> dict:
        """Navigate — or RELOAD when we are already there.

        Re-navigating to the URL we are already on is not a harmless way to refresh a page: the
        navigation is issued while the page's own fetch is in flight, and @playwright/mcp answers it
        with a failed navigation rather than a fresh page (observed 2026-09-23, twice, with a 60s
        stall). A reload expresses the intent exactly and does not race anything.

        `snapshot=False` skips the accessibility tree: on X or Facebook it is megabytes, and taking
        one after every navigation is what ran the office browser's MCP process out of heap
        (2026-09-29). A caller that only needs the title and then asks the page itself (a login
        probe, a portal script addressing controls by role selector) passes False.
        """
        if self.current_url() == url.rstrip("/"):
            self.call("browser_evaluate", {"function": "() => { location.reload(); return 'ok'; }"})
            time.sleep(1.5)
            res = {"text": "reload"}
        else:
            res = self.call("browser_navigate", {"url": url})
            for _ in range(retries):
                if not res.get("is_error"):
                    break
                time.sleep(1.5)
                res = self.call("browser_navigate", {"url": url})
            if res.get("is_error"):
                raise SessionError(f"לא ניתן לפתוח את {url}", state="unknown_error",
                                   detail=(res.get("text") or "")[:300])
        if not snapshot:
            t = re.search(r"Page Title:\s*(.+)$", res.get("text") or "", re.M)
            return {"url": url, "title": t.group(1).strip() if t else None,
                    "text": (res.get("text") or "")[:400], "nodes": [], "snapshot": ""}
        snap = self.snapshot()
        return {"url": url, "title": snap.get("title"), "text": (res.get("text") or "")[:400],
                "nodes": snap.get("nodes") or [], "snapshot": snap.get("raw", "")[:4000]}

    def snapshot(self) -> dict:
        """The accessibility tree, parsed into `{role, name, ref}` nodes.

        Parsing rather than regex-matching one target: the tree is what makes role+name locators
        possible at all, and it doubles as the evidence shown to the owner when a step fails ("this
        is the page I was looking at").
        """
        res = self.call("browser_snapshot", {})
        raw = fix_text(res.get("text") or "")
        nodes, title = [], None
        for line in raw.splitlines():
            m = re.match(r"^(?P<indent>\s*)- (?P<role>[A-Za-z_]+)(?: \"(?P<name>[^\"]*)\")?"
                         r"(?P<rest>.*)$", line)
            if not m:
                if title is None:
                    t = re.search(r"Page Title:\s*(.+)$", line.strip())
                    if t:
                        title = t.group(1).strip()
                continue
            ref = re.search(r"\[ref=([^\]]+)\]", m.group("rest") or "")
            nodes.append({"role": m.group("role").lower(), "name": fix_text(m.group("name") or ""),
                          "ref": ref.group(1) if ref else None,
                          "depth": len(m.group("indent"))})
        if title is None:
            t = re.search(r"Page Title:\s*(.+)$", raw)
            title = t.group(1).strip() if t else None
        return {"nodes": nodes, "raw": raw, "title": title,
                "login_ish": bool(LOGIN_HINTS.search(raw[:4000]))}

    def locate(self, locator: dict) -> dict | None:
        """A locator → the node that matches it, in the contract's order of preference."""
        snap = self.snapshot()
        nodes = [n for n in snap["nodes"] if n.get("ref")]
        role = (locator.get("role") or "").lower().strip()
        name = (locator.get("name") or locator.get("label") or "").strip().lower()

        def norm(s: str) -> str:
            return re.sub(r"\s+", " ", (s or "").strip().lower())

        role_aliases = {"input": "textbox", "field": "textbox", "link": "link", "btn": "button",
                        "select": "combobox", "dropdown": "combobox"}
        role = role_aliases.get(role, role)
        if role or name:
            for n in nodes:
                if role and n["role"] != role:
                    continue
                if name and norm(name) not in norm(n["name"]):
                    continue
                return n
        if locator.get("testid"):
            got = self.call("browser_evaluate", {
                "function": "() => { const el = document.querySelector('[data-testid=\"%s\"]');"
                            " return el ? 'found' : null; }" % locator["testid"]})
            if "found" in (got.get("text") or ""):
                return {"role": "css", "name": locator["testid"], "ref": None,
                        "css": f'[data-testid="{locator["testid"]}"]'}
        if locator.get("css"):
            return {"role": "css", "name": locator["css"], "ref": None, "css": locator["css"]}
        return None

    def state(self, origin: str | None = None) -> dict:
        """Is this session logged in? THE question that decides whether anything else is attempted.

        Answered from the DOM, with the URL and the visible text as corroboration, and never from
        "the page did not look like a login screen". The first version of this method asked the
        accessibility tree whether a password field was present; the portal renders its password
        field as a plain textbox with a Hebrew placeholder, so the office was told it had a live
        session — on the login page, in front of the owner. The evidence below is what a human would
        look at: the URL, whether there is a password-ish input, and what the page says.
        """
        try:
            if origin:
                self.open(origin, snapshot=False)
            res = self.call("browser_evaluate", {"function": JS_PROBE})
            probe = _json_from_text(res.get("text"))
        except SessionError as e:
            return {"authenticated": False, "state": e.state, "reason": e.message,
                    "detail": e.detail}
        if not probe:
            return {"authenticated": False, "state": "unknown_error",
                    "reason": "לא הצלחתי לקרוא את מצב הדף בדפדפן",
                    "detail": (res.get("text") or "")[:200]}
        url = probe.get("url") or origin or ""
        evidence = {"url": url, "title": probe.get("title"), "len": probe.get("len"),
                    "forms": probe.get("forms"), "links": probe.get("links")}
        if probe.get("challenge"):
            return {"authenticated": False, "state": "blocked",
                    "reason": "האתר הציג חסימת בוטים (Incapsula/WAF) שלא עברנו אותה",
                    "how": "נסה שוב מהדפדפן של הלשכה (תצוגה חיה) — סשן אנושי עובר אותה.",
                    **evidence}
        login_path = re.search(r"/(user/)?(login|signin|sign-in|entrar|anmelden)", url, re.I)
        if probe.get("password_fields") or probe.get("passwordish") or (
                login_path and probe.get("len", 0) < 3000):
            return {"authenticated": False, "state": "needs_human_login",
                    "reason": "הדפדפן של הלשכה אינו מחובר לאתר הזה",
                    "how": "פתח את תצוגת הדפדפן של הלשכה, התחבר פעם אחת — ומכאן זה יעבוד.",
                    **evidence}
        if probe.get("len", 0) < 120:
            return {"authenticated": False, "state": "unknown_error",
                    "reason": "הדף ריק או שלא נטען", **evidence}
        return {"authenticated": True, "state": OK, "reason": "",
                "evidence_why": "אין טופס התחברות, הדף נטען, והכתובת אינה מסך התחברות",
                **evidence}

    def act(self, steps: list[dict], verify: dict | None = None, url: str | None = None) -> dict:
        """Run a portal script's steps, then prove the effect by reading it back."""
        started = time.time()
        trace: list[dict] = []
        if url:
            self.open(url)
        for step in steps:
            sid = step.get("id") or step.get("action")
            t0 = time.time()
            try:
                res = self._step(step)
            except SessionError as e:
                trace.append({"id": sid, "ok": False, "state": e.state, "error": e.message,
                              "ms": int((time.time() - t0) * 1000)})
                return self._result(e.state, trace, {"url": url}, started,
                                    reason=e.message, detail=e.detail)
            trace.append({"id": sid, "ok": True, "ms": int((time.time() - t0) * 1000),
                          "read": res.get("read")})
            if step.get("expect") and not self._expect(step["expect"], res):
                return self._result("assert_failed", trace, {"url": url}, started,
                                    reason=f"השלב {sid} רץ אבל התוצאה אינה כמצופה")
            if res.get("state") in HARD_STOP:
                return self._result(res["state"], trace, {"url": url}, started,
                                    reason=res.get("reason"))
        if verify:
            got = self.read(verify.get("read_back") or {})
            want = str(verify.get("value") or "")
            match = _compare(got.get("value"), want, verify.get("compare") or "equals")
            if not match:
                return self._result("assert_failed", trace, {"url": url}, started,
                                    reason=f"הכתיבה לא אומתה: התקבל {got.get('value')!r} "
                                           f"במקום {want!r}",
                                    verify={"read_back": got.get("value"), "expected": want})
            return self._result(OK, trace, {"url": url}, started,
                                verify={"read_back": got.get("value"), "expected": want,
                                        "match": True})
        return self._result(OK, trace, {"url": url}, started)

    def _step(self, step: dict) -> dict:
        action = (step.get("action") or "").lower()
        loc = step.get("locator") or {}
        value = step.get("value")
        if action == "goto":
            self.open(value or step.get("url") or "")
            return {}
        node = None
        if loc and action not in ("wait_for", "eval", "read"):
            node = self.locate(loc)
            if not node:
                snap = self.snapshot()
                if snap.get("login_ish"):
                    raise SessionError("נראה שהסשן אינו מחובר יותר", state="session_expired")
                raise SessionError(f"לא נמצא הפקד: {loc}", state="selector_missing")
        if action == "click":
            return self.call("browser_click", self.element_args("browser_click", node))
        if action == "fill":
            return self.call("browser_type", {**self.element_args("browser_type", node),
                                              "text": "" if value is None else str(value)})
        if action == "select":
            return self.call("browser_select_option",
                             {**self.element_args("browser_select_option", node),
                              "values": [str(value)]})
        if action == "press":
            return self.call("browser_press_key", {"key": str(value or "Enter")})
        if action == "wait_for":
            if step.get("text"):
                return self.call("browser_wait_for", {"text": step["text"],
                                                      "time": step.get("seconds") or 10})
            return self.call("browser_wait_for", {"time": step.get("seconds") or 2})
        if action == "read":
            got = self.read(loc)
            return {"read": got.get("value")}
        if action == "assert":
            got = self.read(loc)
            ok = _compare(got.get("value"), str(value or ""), step.get("compare") or "contains")
            if not ok:
                raise SessionError(f"הבדיקה נכשלה: {got.get('value')!r} ≠ {value!r}",
                                   state="assert_failed")
            return {"read": got.get("value")}
        if action == "eval":
            out = self.call("browser_evaluate", {"function": step.get("function") or "() => null"})
            return {"read": out.get("text")}
        raise SessionError(f"פעולה לא מוכרת בצעד: {action!r}", state="unknown_error")

    def read(self, locator: dict) -> dict:
        node = self.locate(locator or {})
        if not node:
            return {"value": None, "found": False}
        return {"value": node.get("name"), "found": True, "role": node.get("role")}

    def screen(self) -> str | None:
        res = self.call("browser_take_screenshot", self.screenshot_args())
        return res.get("image")

    def _expect(self, expect: dict, res: dict) -> bool:
        if expect.get("text_contains"):
            return expect["text_contains"] in (res.get("text") or "")
        return True

    def _result(self, state: str, trace: list[dict], evidence: dict, started: float,
                reason: str | None = None, detail: str | None = None,
                verify: dict | None = None) -> dict:
        out = {"state": state, "steps": trace, "reason": reason, "detail": detail,
               "verify": verify or {}, "needs_owner": state in NEEDS_HUMAN,
               "ms": int((time.time() - started) * 1000),
               "evidence": {**evidence, "at": int(time.time())}}
        if state != OK:
            try:
                shot = self.screen()
                if shot:
                    out["evidence"]["screenshot_base64"] = shot[:200_000]
            except SessionError:
                pass
        return out


def _json_from_text(text: str | None) -> dict | None:
    """`browser_evaluate` wraps its answer in prose ("### Result\n{…}") and sometimes in a Playwright
    snippet. The payload is the first JSON object in the text — found by brace matching, not by a
    regex, because these payloads contain nested objects and strings with braces in them."""
    if not text:
        return None
    # a quoted payload (`### Result\n"{\"url\":…}"`) is the JSON of a JSON string
    quoted = re.search(r'"\{.*\}"', text, re.S)
    if quoted and text.lstrip().startswith("### Result"):
        try:
            inner = json.loads(quoted.group(0))
            if isinstance(inner, str):
                return json.loads(inner)
        except ValueError:
            pass
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except ValueError:
                        break
        start = text.find("{", start + 1)
    return None


def _has_content(nodes: list[dict]) -> bool:
    """A page with a form AND real content is a logged-in page that happens to have a search box;
    a page that is ONLY a form is a login screen. The distinction is worth the four lines: guessing
    "not logged in" on a working session would make the feature useless."""
    interesting = [n for n in nodes if n["role"] not in ("generic", "text", "paragraph")]
    return len(interesting) > 6


def _compare(got, want: str, mode: str) -> bool:
    g = "" if got is None else str(got)
    if mode == "equals":
        return g.strip() == want.strip()
    if mode == "regex":
        return bool(re.search(want, g))
    if mode == "dns_equals":
        return want.strip().rstrip(".") in g
    return want.strip() in g


def screenshot_bytes(b64: str | None) -> bytes | None:
    if not b64:
        return None
    try:
        return base64.b64decode(b64)
    except (ValueError, TypeError):
        return None
