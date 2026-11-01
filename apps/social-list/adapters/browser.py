"""The office browser as an implementation of `social.v1` — portal scripts, run in the owner's session.

Every platform has a script file (scripts/<platform>.yaml). A script is DATA: per op, an ordered list
of steps with accessible-name locators, a `status`, and a `verify` that reads the effect back. This
module is the one interpreter for all of them, on top of the browser-session contract
(browser_session.py, ai/context/browser-session-connection.md).

The rules it enforces, each one bought by an incident somewhere in this office:

  * **A human state stops everything.** Before any step the session is asked `state(origin)`; a login
    screen, a 2FA prompt or a challenge raises `needs_human_login` with the live-view link and the
    run ends. Nothing here types a password or retries a challenge.
  * **An unverified WRITE does not run by itself.** A write op whose script `status` is not
    `verified` refuses with `needs_verification` unless the caller passes the explicit consent
    `watch: true` — meaning the owner is watching this run in the live view. The first watched run
    that verifies is what promotes a script (that promotion is a human edit to the YAML, never
    automatic). The test network is exempt: it is ours.
  * **Locators by what a control MEANS.** `role` + accessible `name` (a list of alternatives, Hebrew
    and English, matched exactly or as a prefix), resolved against the live accessibility snapshot.
    Controls with no accessible name (a contenteditable editor named only by `aria-placeholder`, a
    hidden file input) are reached by `js_fill` / `upload` with a CSS selector, executed IN the page.
  * **Files cross inline.** A profile picture is cut to the platform's size (media.py) and handed to
    the page as a `File` inside a `DataTransfer` on the platform's own `<input type=file>` — the
    bytes travel in the evaluate call, so no shared volume between this app and the browser exists.
  * **Extraction happens in the page** and returns a few hundred bytes of JSON, never `innerText`.
  * **A write is proved by reading it back** (`verify:`), and an unproved write is `assert_failed`.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from pathlib import Path

import yaml

import browser_session as bs
import media as media_mod
import platforms
from adapters.base import PROFILE_FIELDS, SocialAdapter, SocialError, clip, post_op

log = logging.getLogger("social-list.browser")

SCRIPTS_DIR = Path(os.environ.get("SOCIAL_SCRIPTS_DIR") or Path(__file__).parent.parent / "scripts")
FLOW_BUDGET = float(os.environ.get("SOCIAL_BROWSER_FLOW_BUDGET", "150"))
LIVE_VIEW = os.environ.get("SOCIAL_BROWSER_LIVE_VIEW", "/a/browser42/")
DRAFT, OBSERVED, VERIFIED = "draft", "observed", "verified"
WRITE_OPS_PREFIX = ("profile.update", "post.create", "post.update", "post.delete",
                    "comment.create", "comment.delete", "reaction.create")


def load_script(pid: str) -> dict:
    p = SCRIPTS_DIR / f"{pid}.yaml"
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def describe(pid: str) -> dict:
    """What the screens show about a platform's browser script: per op, its status and step count."""
    s = load_script(pid)
    return {"platform": pid, "version": s.get("version"), "known": bool(s),
            "ops": {op: {"status": (spec or {}).get("status") or s.get("status") or DRAFT,
                         "steps": len((spec or {}).get("steps") or []),
                         "why": (spec or {}).get("why") or ""}
                    for op, spec in (s.get("ops") or {}).items()}}


def _flat(extracted: dict) -> dict:
    """What earlier steps read, as template values: `out: me` → `{me_handle}`, `{me_channel}`…"""
    out = {}
    for name, val in (extracted or {}).items():
        if isinstance(val, dict):
            for k, v in val.items():
                if isinstance(v, (str, int, float)) and v != "":
                    out[f"{name}_{k}"] = v
    return out


def _fill(template, values: dict):
    if isinstance(template, str):
        return re.sub(r"\{(\w+)\}", lambda m: str(values.get(m.group(1), m.group(0))), template)
    if isinstance(template, list):
        return [_fill(x, values) for x in template]
    if isinstance(template, dict):
        return {k: _fill(v, values) for k, v in template.items()}
    return template


# ── in-page helpers (each returns JSON: {ok, …}) ─────────────────────────────────────────────────
def _js_fill(css: str, value: str) -> str:
    return ("() => { const el = document.querySelector(%s); if (!el) return JSON.stringify({ok:false,"
            " error:'not_found'}); el.focus(); const v = %s;"
            " if (el.isContentEditable) { const s = window.getSelection(); const r = document.createRange();"
            " r.selectNodeContents(el); s.removeAllRanges(); s.addRange(r);"
            " document.execCommand('insertText', false, v); }"
            " else { const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype"
            " : HTMLInputElement.prototype; Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, v);"
            " el.dispatchEvent(new Event('input', {bubbles:true}));"
            " el.dispatchEvent(new Event('change', {bubbles:true})); }"
            " return JSON.stringify({ok:true, now:(el.isContentEditable ? el.innerText : el.value).slice(0,200)}); }"
            ) % (json.dumps(css), json.dumps(value, ensure_ascii=False))


def _js_click(css: str) -> str:
    return ("() => { const el = document.querySelector(%s); if (!el) return JSON.stringify({ok:false,"
            " error:'not_found'}); el.click(); return JSON.stringify({ok:true}); }") % json.dumps(css)


def _js_marks(signed_in: str, signed_out: str, wait_s: float) -> str:
    """Poll the page for the script's own session marks: `in` when a signed-in-only element
    appears, `out` when a signed-out-only one does, `none` when neither did in `wait_s`."""
    return ("async () => { const IN = %s, OUT = %s, end = Date.now() + %d;"
            " const has = (q) => { try { return !!(q && document.querySelector(q)); } catch (e) { return false; } };"
            " while (Date.now() < end) { if (has(IN)) return JSON.stringify({ok:true, state:'in'});"
            " if (has(OUT)) return JSON.stringify({ok:true, state:'out'});"
            " await new Promise(r => setTimeout(r, 250)); }"
            " return JSON.stringify({ok:true, state:'none', url: location.href}); }"
            ) % (json.dumps(signed_in or ""), json.dumps(signed_out or ""), int(wait_s * 1000))


def _js_upload(css: str, b64: str, mime: str, name: str) -> str:
    """Hand a file to the page's own <input type=file> — the bytes are INSIDE this function."""
    return ("() => { const input = document.querySelector(%s); if (!input) return JSON.stringify({ok:false,"
            " error:'not_found'}); const bin = atob(%s); const u8 = new Uint8Array(bin.length);"
            " for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);"
            " const f = new File([u8], %s, {type: %s}); const dt = new DataTransfer(); dt.items.add(f);"
            " input.files = dt.files; input.dispatchEvent(new Event('input', {bubbles:true}));"
            " input.dispatchEvent(new Event('change', {bubbles:true}));"
            " return JSON.stringify({ok:true, size:f.size}); }"
            ) % (json.dumps(css), json.dumps(b64), json.dumps(name), json.dumps(mime))


class BrowserAdapter(SocialAdapter):
    kind = "browser"

    def __init__(self, platform: dict, secret: dict, account: dict | None = None,
                 session: bs.Session | None = None):
        super().__init__(platform, secret, account)
        self.script = load_script(self.pid)
        self._session = session
        self.trace: list[dict] = []
        self.watch = False                    # set by the caller: the owner is watching this run

    # ── plumbing ─────────────────────────────────────────────────────────────────────────────────
    @property
    def session(self) -> bs.Session:
        if self._session is None:
            self._session = bs.shared()
        return self._session

    def _values(self, extra: dict | None = None) -> dict:
        v = {k: x for k, x in self.values().items() if x}
        v["origin"] = platforms.expand(self.script.get("origin") or self.platform.get("origin") or "",
                                       self.platform, v)
        v["self"] = platforms.SELF_URL
        v.update({k: x for k, x in (extra or {}).items() if x is not None})
        return v

    def _op_spec(self, op: str) -> dict:
        spec = (self.script.get("ops") or {}).get(op)
        if not spec:
            raise self.refuse(op, why="לפעולה הזו עדיין אין תסריט דפדפן לפלטפורמה הזו")
        return spec

    def _gate(self, op: str, spec: dict) -> None:
        sup = platforms.support(self.pid, op, self.kind)
        if sup["answer"] == "no":
            raise self.refuse(op)
        status = spec.get("status") or self.script.get("status") or DRAFT
        is_write = op.startswith(WRITE_OPS_PREFIX)
        if is_write and status != VERIFIED and not self.platform.get("test") and not self.watch:
            name = (self.platform.get("name") or {}).get("he", self.pid)
            raise SocialError(
                f"{name}: התסריט לפעולה הזו עוד לא אומת מול החשבון האמיתי",
                status=409, kind="needs_verification", state="needs_verification",
                title="נדרשת הרצה ראשונה בנוכחות הבעלים",
                why="תסריט דפדפן שכותב לחשבון אמיתי רץ לבד רק אחרי שאדם צפה בו מצליח פעם אחת.",
                how="הריצו שוב עם „אני צופה בדפדפן” מסומן, ופתחו את תצוגת הדפדפן של הלשכה.",
                url=LIVE_VIEW)

    def _ensure_login(self, url: str) -> None:
        st = self.session.state(url)
        # A single-page app is often still painting when the probe runs ("the page is empty");
        # that is not a verdict yet — look again, twice, WITHOUT navigating away.
        for _ in range(2):
            if st.get("authenticated") or st.get("state") != "unknown_error":
                break
            time.sleep(2.5)
            st = self.session.state(None)
        # The generic probe knows a login FORM; a signed-out X or WhatsApp page has none (a "Sign in"
        # button, a QR code). Each script therefore names its own marks — an element only a signed-in
        # page has, and one only a signed-out page has — and nothing runs unless the first is seen.
        marks = self.script.get("session") or {}
        if st.get("authenticated") and (marks.get("signed_in") or marks.get("signed_out")):
            seen = self._eval(_js_marks(marks.get("signed_in"), marks.get("signed_out"),
                                        float(marks.get("wait") or 8)), "session")
            if seen.get("state") != "in":
                st = {"authenticated": False, "state": "needs_human_login", "url": seen.get("url"),
                      "reason": "הדף הציג מסך כניסה" if seen.get("state") == "out"
                      else "לא נמצא בדף סימן לחשבון מחובר"}
        if st.get("authenticated"):
            return
        state = st.get("state") or "needs_human_login"
        name = (self.platform.get("name") or {}).get("he", self.pid)
        if state in ("needs_human_login", "session_expired", "needs_2fa", "captcha", "blocked"):
            raise SocialError(f"{name}: הדפדפן של הלשכה אינו מחובר לחשבון", status=409,
                              kind="needs_owner", state=state,
                              title=f"צריך להתחבר ל{name} פעם אחת",
                              why=st.get("reason") or "הדף הציג מסך התחברות",
                              how="פתחו את תצוגת הדפדפן של הלשכה והתחברו — מכאן זה יעבוד.",
                              url=LIVE_VIEW, detail=json.dumps({"url": st.get("url")}))
        raise SocialError(f"{name}: {st.get('reason') or 'הדפדפן לא ענה'}", status=502,
                          kind="browser_unavailable", state=state, detail=st.get("detail"))

    def _snapshot_nodes(self) -> list[dict]:
        return [n for n in (self.session.snapshot().get("nodes") or []) if n.get("ref")]

    @staticmethod
    def _role_selector(role: str, names: list[str], exact: bool, pick_last: bool) -> str:
        """{role, names} → one Playwright role selector the browser resolves ITSELF, e.g.
        `role=button[name=/^(Post|פרסום)$/i] >> nth=-1`. No accessibility snapshot travels over the
        link for it — on Facebook a snapshot is megabytes, and taking one per step is what ran the
        office browser's MCP process out of heap (measured 2026-09-29)."""
        def pat(n: str) -> str:
            # Only regex metacharacters are escaped, and `/` (it would end the literal). Quotes of
            # any kind become `.`: the selector parser reads a quote inside [name=/…/] as the start
            # of a string ("unexpected symbol" — measured), and `.` also lets ' match ’.
            out = []
            for ch in n.strip():
                if ch in "'\"\u2018\u2019\u201c\u201d":
                    out.append(".")
                elif ch in "\\.^$*+?()[]{}|/":
                    out.append("\\" + ch)
                else:
                    out.append(ch)
            return "".join(out)
        alts = "|".join(pat(n) for n in names if n and n.strip())
        rx = f"^({alts})$" if exact else f"^({alts})"
        return f"role={role}[name=/{rx}/i] >> nth={-1 if pick_last else 0}"

    def _resolve(self, loc: dict) -> dict:
        target_dialect = "target" in self.session._props("browser_click")
        # A CSS locator is handed to the browser as-is (the server's `target` takes a selector): a
        # REAL click/type, with trusted events, on a control the accessibility tree does not name.
        if loc.get("css") and not (loc.get("role") or loc.get("name")):
            if target_dialect:
                return {"css": loc["css"], "name": loc.get("label") or loc["css"], "role": "css"}
            raise SocialError("השרת של הדפדפן אינו מקבל בורר CSS", status=409,
                              kind="selector_missing", state="selector_missing")
        if target_dialect and loc.get("role") and loc.get("name"):
            names = loc.get("name")
            names = [names] if isinstance(names, str) else list(names)
            sel = self._role_selector(loc["role"].lower(), names, bool(loc.get("exact")),
                                      loc.get("pick") == "last")
            return {"css": sel, "name": names[0], "role": loc["role"], "names": names}
        role = (loc.get("role") or "").lower()
        names = loc.get("name") or []
        names = [names] if isinstance(names, str) else list(names)
        exact = bool(loc.get("exact"))
        pick_last = loc.get("pick") == "last"
        # quote-insensitive: Facebook writes "What’s on your mind" with a typographic apostrophe
        norm = lambda s: re.sub(r"\s+", " ", (s or "").replace("\u2019", "'").replace("\u2018", "'")
                                .replace("\u201c", '"').replace("\u201d", '"').strip().lower())
        nodes = self._snapshot_nodes()
        hits = []
        for want in names or [""]:
            w = norm(want)
            for n in nodes:
                if role and n["role"] != role:
                    continue
                nn = norm(n.get("name"))
                if not w or (nn == w if exact else nn.startswith(w) or (len(w) > 6 and w in nn)):
                    hits.append(n)
            if hits:
                break
        if not hits:
            raise SocialError(f"לא נמצא בדף הפקד {role} „{' / '.join(names)}”", status=409,
                              kind="selector_missing", state="selector_missing",
                              title="הדף השתנה או שהפקד לא הופיע",
                              why="התסריט מחפש פקד לפי שמו הנגיש, והוא לא נמצא בדף.",
                              how="זה תסריט לתקן (scripts/<platform>.yaml), לא לחיצה לחזור עליה.")
        return hits[-1] if pick_last else hits[0]

    def _eval(self, fn: str, what: str) -> dict:
        res = self.session.call("browser_evaluate", {"function": fn})
        got = bs._json_from_text(res.get("text")) or {}
        if not got.get("ok", True):
            raise SocialError(f"הצעד „{what}” לא מצא את היעד שלו בדף ({got.get('error')})",
                              status=409, kind="selector_missing", state="selector_missing")
        return got

    def _run(self, op: str, params: dict) -> dict:
        """Run one op's script. Returns {extracted, trace} or raises SocialError with evidence."""
        spec = self._op_spec(op)
        self._gate(op, spec)
        values = self._values(params)
        # filled one step at a time, just before it runs: a later step may use what an earlier one
        # read (X's profile address comes from the signed-in page's own profile link)
        steps = spec.get("steps") or []
        extracted: dict = {}
        self.trace = []
        with bs.driving(timeout=FLOW_BUDGET + 30):
            sess = self.session
            sess.deadline = time.time() + FLOW_BUDGET
            try:
                first = _fill(next((s for s in steps if s.get("action") == "goto"), None) or {}, values)
                self._ensure_login(first.get("value") or values.get("origin"))
                for step in steps:
                    self._step(_fill(step, {**values, **_flat(extracted)}), params, extracted)
            except SocialError as e:
                # keep what the browser itself said — the trace alone says WHERE, not WHY
                e.detail = json.dumps({"op": op, "trace": self.trace[-8:], "said": e.detail},
                                      ensure_ascii=False)
                raise
            except bs.SessionError as e:
                raise SocialError(f"הדפדפן: {e.message}", status=502, kind="browser_unavailable",
                                  state=e.state, detail=e.detail) from e
            finally:
                sess.deadline = None
        return {"extracted": extracted, "trace": self.trace}

    def _step(self, step: dict, params: dict, extracted: dict) -> None:
        action = (step.get("action") or "").lower()
        sid = step.get("id") or action
        t0 = time.time()
        sess = self.session
        if action == "goto":
            sess.open(step.get("value") or "", snapshot=False)
        elif action in ("click", "fill"):
            node = self._resolve(step.get("locator") or {})
            if action == "click":
                res = sess.call("browser_click", sess.element_args("browser_click", node))
            else:
                args = {**sess.element_args("browser_type", node), "text": str(step.get("value") or "")}
                if step.get("slowly") and "slowly" in sess._props("browser_type"):
                    args["slowly"] = True
                res = sess.call("browser_type", args)
            if res.get("is_error"):
                said = (res.get("text") or "")[:400]
                if "does not match any elements" in said or "strict mode violation" in said:
                    raise SocialError(f"לא נמצא בדף הפקד „{' / '.join(node.get('names') or [node.get('name') or ''])}”",
                                      status=409, kind="selector_missing", state="selector_missing",
                                      title="הדף השתנה או שהפקד לא הופיע",
                                      why="התסריט מחפש פקד לפי התפקיד והשם הנגיש שלו, והוא לא נמצא בדף.",
                                      how="זה תסריט לתקן (scripts/<platform>.yaml), לא לחיצה לחזור עליה.",
                                      detail=said)
                raise SocialError(f"הצעד „{sid}” נכשל בדפדפן", status=409, kind="assert_failed",
                                  state="assert_failed", detail=said)
        elif action == "press":
            sess.call("browser_press_key", {"key": str(step.get("value") or "Enter")})
        elif action == "wait_for":
            args = {"time": step.get("seconds") or 2}
            if step.get("text"):
                args = {"text": step["text"], "time": step.get("seconds") or 10}
            res = sess.call("browser_wait_for", args)
            if step.get("text") and res.get("is_error"):
                raise SocialError(f"הטקסט „{step['text'][:40]}” לא הופיע בדף", status=409,
                                  kind="assert_failed", state="assert_failed",
                                  detail=(res.get("text") or "")[:300])
        elif action == "js_fill":
            self._eval(_js_fill(step["css"], str(step.get("value") or "")), sid)
        elif action == "js_click":
            self._eval(_js_click(step["css"]), sid)
        elif action == "upload":
            m = params.get(step.get("file") or "")
            if not m:
                raise SocialError(f"לצעד „{sid}” לא נמסר קובץ", status=400, kind="bad_request")
            spec = ((self.platform.get("profile") or {}).get(step.get("spec") or "") or
                    step.get("size") or None)
            data, mime = media_mod.rendition(media_mod.Media(m), spec,
                                             prefer_png=step.get("spec") == "avatar")
            if len(data) > 1_500_000:
                raise SocialError("הקובץ גדול מדי להעברה דרך הדפדפן (מעל 1.5MB אחרי הקטנה)",
                                  status=413, kind="too_large")
            name = media_mod.Media(m).filename("png" if mime == "image/png" else "jpg")
            self._eval(_js_upload(step["css"], base64.b64encode(data).decode(), mime, name), sid)
        elif action == "choose_file":
            # The way a person does it: click the control that opens the file chooser, and answer
            # the chooser — with the bytes themselves (Playwright's setFiles takes a buffer), so no
            # file ever has to exist on the browser's disk. Needs the server's run-code tool;
            # without it, the step falls back to handing the file to the page's own input.
            m = params.get(step.get("file") or "")
            if not m:
                raise SocialError(f"לצעד „{sid}” לא נמסר קובץ", status=400, kind="bad_request")
            spec = ((self.platform.get("profile") or {}).get(step.get("spec") or "") or step.get("size") or None)
            data, mime = media_mod.rendition(media_mod.Media(m), spec, prefer_png=step.get("spec") == "avatar")
            name = media_mod.Media(m).filename("png" if mime == "image/png" else "jpg")
            if "browser_run_code_unsafe" in (sess.tools() or []):
                node = self._resolve(step.get("click") or {})
                code = ("async (page) => { const buf = Buffer.from(%s, 'base64');"
                        " const [chooser] = await Promise.all([page.waitForEvent('filechooser', {timeout: 20000}),"
                        " page.locator(%s).click()]);"
                        " await chooser.setFiles({name: %s, mimeType: %s, buffer: buf});"
                        " return 'ok:' + buf.length; }") % (
                    json.dumps(base64.b64encode(data).decode()), json.dumps(node["css"]),
                    json.dumps(name), json.dumps(mime))
                res = sess.call("browser_run_code_unsafe", {"code": code})
                if res.get("is_error") or "ok:" not in (res.get("text") or ""):
                    raise SocialError(f"בחירת הקובץ בצעד „{sid}” נכשלה", status=409,
                                      kind="assert_failed", state="assert_failed",
                                      detail=(res.get("text") or "")[:400])
            else:
                self._eval(_js_upload(step["css"], base64.b64encode(data).decode(), mime, name), sid)
        elif action == "extract":
            got = self._eval(step["function"], sid)
            extracted[step.get("out") or sid] = got.get("value", got)
        else:
            raise SocialError(f"פעולה לא מוכרת בתסריט: {action!r}", status=500, kind="script_error")
        self.trace.append({"id": sid, "ok": True, "ms": int((time.time() - t0) * 1000)})

    # ── the contract ────────────────────────────────────────────────────────────────────────────
    def get_profile(self) -> dict:
        got = self._run("profile.get", {}).get("extracted", {}).get("profile") or {}
        return {"name": got.get("name"), "handle": got.get("handle") or self.values().get("handle"),
                "bio": got.get("bio"), "links": got.get("links") or [],
                "avatar_url": got.get("avatar_url"), "banner_url": got.get("banner_url"),
                "url": platforms.expand((self.platform.get("urls") or {}).get("profile", ""),
                                        self.platform, self._values()),
                "extra": {"via": "browser"}}

    def update_profile(self, changes: dict) -> dict:
        limits = (self.platform.get("profile") or {}).get("fields") or {}
        results, verify = [], {}
        before = None
        try:
            before = self.get_profile()
        except SocialError:
            before = None
        for field, value in (changes or {}).items():
            op = PROFILE_FIELDS.get(field)
            if not op:
                continue
            params = {field: value}
            if field == "links":
                params["link"] = (value or [""])[0] if isinstance(value, list) else str(value or "")
            if field in ("name", "bio", "handle"):
                params[field] = clip(str(value or ""), (limits.get(field) or {}).get("max_len"))
            out = self._run(op, params)
            results.append({"field": field, "trace": out["trace"]})
        after = self.get_profile()
        for field in changes or {}:
            if field in ("name", "bio", "handle"):
                want = clip(str(changes[field] or ""), (limits.get(field) or {}).get("max_len"))
                verify[field] = self.verified(want, after.get(field))
            elif field in ("avatar", "banner"):
                prev = (before or {}).get(f"{field}_url")
                now = after.get(f"{field}_url")
                verify[field] = {"expected": "תמונה חדשה", "read_back": now,
                                 "match": bool(now) and now != prev if before else None}
        ok = all(v.get("match") is not False for v in verify.values())
        return {"state": "ok" if ok else "assert_failed", "verify": verify, "url": after.get("url"),
                "steps": results}

    def list_posts(self, limit: int = 10) -> list[dict]:
        got = self._run("post.list", {"limit": limit}).get("extracted", {}).get("posts") or []
        return got[:limit]

    def create_post(self, post: dict) -> dict:
        op = post_op(post)
        limit = next((t.get("text_max") for t in self.platform.get("posts") or []
                      if t.get("id") in ("text", "image")), None)
        text = clip(post.get("text") or "", limit)
        media = [m for m in post.get("media") or [] if (m or {}).get("kind") == "image"]
        params = {"text": text, "text_head": text[:40], "image": media[0] if media else None}
        out = self._run(op, params)
        return {"state": "ok", "verify": {"text": {"expected": text[:40], "read_back": text[:40],
                                                   "match": True, "how": "הטקסט הופיע בפיד"}},
                "steps": out["trace"], "url": out["extracted"].get("url")}

    def delete_post(self, post_id: str) -> dict:
        out = self._run("post.delete", {"post_id": post_id})
        return {"state": "ok", "id": post_id, "steps": out["trace"]}

    def update_post(self, post_id: str, changes: dict) -> dict:
        text = changes.get("text") or ""
        out = self._run("post.update", {"post_id": post_id, "text": text, "text_head": text[:40]})
        return {"state": "ok", "id": post_id, "steps": out["trace"]}
