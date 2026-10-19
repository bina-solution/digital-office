#!/usr/bin/env python3
"""
capture.py — walk every view in ui-inventory.json, screenshot it, and record which
view code ran while the shutter was open.

Runs inside the ui-capture container (scripts/ui-coverage/Dockerfile) — a minimal, single-
purpose python+chromium image driven by run_capture.sh. N of them run on the stack network in
parallel (one per shard), each launching its OWN headless Chromium and reaching the console
DIRECTLY by its container IP (UI_HOST_RESOLVER), so there is no Traefik hop and no browser42.

Design notes
------------
* Launches its own Chromium per shard (UI_OWN_BROWSER, the default) rather than sharing one
  over CDP — a fresh context with ignore_https_errors, since the apps use a self-signed cert.
* Coverage is started once per APP and taken at the end of that app's views. That matches
  SPA semantics: hash/DOM navigation inside console or my-docs does NOT reload the page,
  so coverage accumulates across the app's screens exactly as it should.
* Script SOURCE is pulled from V8 (Debugger.getScriptSource) and stored next to the
  ranges. That way coverage is computed against the exact text V8 measured — which is
  what makes inline <script> blocks (connections/ui.html, machine, notifications)
  measurable at all, and removes any "is the file on disk the same as what shipped?" doubt.
* Every PNG is validated: a blank page, an Authentik wall, or an error page counts as a
  FAILED capture, not a captured view. A screenshot of a login screen is not coverage.

Outputs (under /data):
    output/ui/<app>__<view>.png
    ui-capture-results.json    per-view status
    ui-raw-coverage.json       {app: {scripts:[{url,source,functions}], css:[...]}}
"""
from __future__ import annotations
# Hebrew output: python defaults stdout to the ANSI codepage on Windows (cp1255) and dies
# with UnicodeEncodeError. Linux/macOS are already UTF-8 — a no-op there.
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"): _sys.stdout.reconfigure(encoding="utf-8")

import json
import os
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

DATA = Path("/data")
OUT = DATA / "output" / "ui"
INV = DATA / "ui-inventory.json"
ENVMAP = DATA / "ui-env.json"
PARAMS_FILE = DATA / "ui-params.json"   # ids resolved host-side by ci-ui-map.sh

AK_USER = os.getenv("AK_USER", "akadmin")
AK_PASS = os.getenv("AK_PASS", "")
N8N_USER = os.getenv("N8N_USER", "")
N8N_PASS = os.getenv("N8N_PASS", "")
PT_PASS = os.getenv("PT_PASS", "")
GT_USER = os.getenv("GT_USER", "")
GT_PASS = os.getenv("GT_PASS", "")
VNC_PASS = os.getenv("VNC_PASS", "")
WA_USER = os.getenv("WA_USER", "")
WA_PASS = os.getenv("WA_PASS", "")

# ── view profile ─────────────────────────────────────────────────────────────
# The viewport is NOT hardcoded here: profiles live in view-profiles.yaml next to this file, shared
# with the offline sim map (digital-office/sim/ui-map.py), so a viewport is declared once and the two
# maps can never disagree. Pick one with UI_MAP_PROFILE=mobile|tablet|desktop (default: the file's
# `default`, i.e. desktop — so existing baselines are unchanged).
def _load_profile():
    name = os.getenv("UI_MAP_PROFILE", "").strip()
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "view-profiles.yaml")
    try:
        import yaml
        doc = yaml.safe_load(open(path, encoding="utf-8").read())
        name = name or doc.get("default", "desktop")
        prof = doc["profiles"][name]
        return name, prof
    except Exception as e:                                   # never let the map die over config
        print(f"[ui-map] profile '{name or 'default'}' unavailable ({e}); using built-in desktop")
        return "desktop", {"width": 1440, "height": 900, "dsf": 1,
                           "is_mobile": False, "has_touch": False}


PROFILE_NAME, PROFILE = _load_profile()
VIEWPORT = {"width": PROFILE["width"], "height": PROFILE["height"]}
CTX_KWARGS = {
    "device_scale_factor": PROFILE.get("dsf", 1),
    "is_mobile": bool(PROFILE.get("is_mobile", False)),
    "has_touch": bool(PROFILE.get("has_touch", False)),
}
print(f"[ui-map] view profile: {PROFILE_NAME} "
      f"({VIEWPORT['width']}x{VIEWPORT['height']} @{CTX_KWARGS['device_scale_factor']}x)")

OWN_BROWSER = os.getenv("UI_OWN_BROWSER", "1") != "0"


# ── Authentik SSO (ported from ci-screenshots.sh — hard-won, keep the shape) ──

def on_ak_wall(page) -> bool:
    u = page.url or ""
    if "/flow/" in u or "outpost.goauthentik.io" in u:
        return True
    try:
        return bool(re.search(r"Welcome to authentik|Login to continue|Email or Username",
                              page.content(), re.I))
    except Exception:
        return False


def settle(page, ms: int = 1500):
    try:
        page.wait_for_load_state("networkidle", timeout=9000)
    except Exception:
        pass
    page.wait_for_timeout(ms)
    hydrate(page)


def hydrate(page, target: int = 60, budget_ms: int = 12000):
    """Wait until the DOM actually has content, not just until the network is quiet.

    Web-component SPAs (authentik) and heavy dashboards serve a near-empty shell and mount
    later, so networkidle + a fixed sleep caught them mid-hydration — authentik/login was
    failing with 26 nodes, which is the shell, not the app. Polls until the node count
    stops growing and clears a floor, then gives up quietly (a genuinely empty page is a
    real failure and validate() should still call it).
    """
    last, stable = -1, 0
    for _ in range(int(budget_ms / 400)):
        try:
            n = page.evaluate("document.querySelectorAll('*').length")
        except Exception:
            return
        if n >= target and n == last:
            stable += 1
            if stable >= 2:
                return
        else:
            stable = 0
        last = n
        page.wait_for_timeout(400)


def hydrate_frame(page, target: int = 60, budget_ms: int = 18000):
    """Wait for the EMBEDDED app to finish mounting, not just the shell around it.

    `hydrate()` waits on the top document, which for a framed view is the console — it is fully
    rendered long before the app inside `#frame` has asked for its data. Measured 2026-09-28:
    app-management renders its side menu only after `/api/apps` answers (a call that probes every
    installed app and takes 20-40s on this host), so three different views were captured as three
    byte-identical loading skeletons — the map reported them CAPTURED because the SHELL was real.
    That is the same class of false positive as a blank screenshot: the artefact exists, the screen
    does not.
    """
    last, stable = -1, 0
    for _ in range(int(budget_ms / 400)):
        try:
            frames = [f for f in page.frames if f != page.main_frame]
            if not frames:
                return
            n = frames[0].evaluate("document.querySelectorAll('*').length")
        except Exception:
            return
        if n >= target and n == last:
            stable += 1
            if stable >= 2:
                return
        else:
            stable = 0
        last = n
        page.wait_for_timeout(400)


def ak_login(page) -> bool:
    for _ in range(3):
        try:
            page.get_by_role("textbox").first.fill(AK_USER)
            page.keyboard.press("Enter")
            page.wait_for_timeout(1200)
            page.locator("input[type=password]").first.fill(AK_PASS)
            page.keyboard.press("Enter")
            page.wait_for_url(lambda u: "/flow/" not in u, timeout=15000)
            settle(page)
            return True
        except Exception:
            page.wait_for_timeout(1000)
    return False


def open_gated(page, url: str) -> bool:
    for _ in range(3):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass
        settle(page)
        if not on_ak_wall(page):
            return True
        ak_login(page)
    return not on_ak_wall(page)


def n8n_login(page, base: str, user: str, pw: str):
    """n8n keeps its own session and drops it readily — ported from ci-screenshots.sh,
    which re-checks before every navigation for exactly that reason."""
    try:
        page.goto(base + "/signin", wait_until="domcontentloaded", timeout=25000)
        settle(page, 900)
        if page.locator("input[type=email], input[name=email]").count():
            page.locator("input[type=email], input[name=email]").first.fill(user)
            page.locator("input[type=password]").first.fill(pw)
            page.keyboard.press("Enter")
            settle(page, 1500)
    except Exception:
        pass


def portainer_login(page, base: str, pw: str):
    try:
        page.goto(base + "/", wait_until="domcontentloaded", timeout=25000)
        settle(page, 1200)
        u = page.locator("input#username, input[name=username]")
        if u.count():
            u.first.fill("admin")
            page.locator("input[type=password]").first.fill(pw)
            page.keyboard.press("Enter")
            settle(page, 2000)
    except Exception:
        pass


def glitchtip_login(page, base: str, email: str, pw: str):
    try:
        page.goto(base + "/accounts/login/", wait_until="domcontentloaded", timeout=25000)
        settle(page, 1000)
        if page.locator("input[type=password]").count():
            page.locator("input[type=email], input[name=login]").first.fill(email)
            page.locator("input[type=password]").first.fill(pw)
            page.keyboard.press("Enter")
            settle(page, 2000)
    except Exception:
        pass


def redisinsight_consent(page, base: str):
    """First run shows an EULA whose Submit stays disabled until the terms switch is on."""
    try:
        page.goto(base + "/", wait_until="domcontentloaded", timeout=25000)
        settle(page, 1500)
        sw = page.locator("[role=switch]")
        if sw.count():
            sw.last.click(timeout=5000)
            page.wait_for_timeout(500)
            for sel in ("button[type=submit]", "button:has-text('Submit')"):
                if page.locator(sel).count():
                    page.locator(sel).first.click(timeout=5000)
                    break
            settle(page, 2000)
    except Exception:
        pass


def browser42_connect(page, base: str, pw: str):
    """/view/ is noVNC, which gates on the VNC password before showing the desktop."""
    try:
        page.goto(base + "/view/", wait_until="domcontentloaded", timeout=25000)
        settle(page, 1500)
        if page.locator("input[type=password]").count():
            page.locator("input[type=password]").first.fill(pw)
            page.keyboard.press("Enter")
            settle(page, 2500)
    except Exception:
        pass


def chat_login(page, base: str):
    try:
        page.goto(base + "/login", wait_until="domcontentloaded", timeout=20000)
        settle(page, 800)
        if page.locator("input[type=password]").count():
            page.locator("input").first.fill(WA_USER or "admin")
            page.locator("input[type=password]").first.fill(WA_PASS or "admin")
            page.keyboard.press("Enter")
            settle(page)
    except Exception:
        pass


# ── screenshot validation: a captured view must actually show the app ────────

BAD_TEXT = re.compile(
    r"Welcome to authentik|Email or Username|"
    # 5xx: pair the CODE with its own default-error-page wording, not a bare "504 " — that
    # matched INSIDE real content on 2026-08-06 (notifications legitimately renders GlitchTip
    # alert titles like "SLOW Response: 504 in 181234ms", reporting a real slow apitools call
    # elsewhere in the stack) and turned a correctly-captured, fully-hydrated view into a false
    # "failed: error/login page" on every retry. A gateway's own default error page always
    # carries the code AND the standard phrase together; content that merely mentions a status
    # code as data does not.
    r"Bad Gateway|502 Bad Gateway|"
    r"503 Service (Temporarily )?Unavailable|"
    r"504 Gateway Time-?out|"
    r"Cannot GET|Application error|nginx|Internal Server Error", re.I)

# A screenshot of a sign-in form or a consent gate is not a screenshot of the app. The
# first version only knew about Authentik walls and 5xx pages, so portainer's
# "Log in to your account", GlitchTip's login and RedisInsight's EULA all counted as
# CAPTURED and inflated view coverage. Views that ARE a login (chat/login,
# authentik/login) opt out via `expects_login`.
# Deliberately English-only. The Hebrew "התחבר" was in here and produced a FALSE
# POSITIVE on console/install: in Hebrew it means "connect", which the install wizard
# uses on legitimate buttons for linking Google/WhatsApp. A validator that rejects real
# screens is worse than one that misses a few, so ambiguous wording is out and the
# password-field heuristic below carries the Hebrew UIs.
LOGIN_TEXT = re.compile(
    r"Log ?in to your account|Sign in to your|Sign in to continue|"
    r"Welcome back! Please enter|Create an account", re.I)
CONSENT_TEXT = re.compile(
    r"EULA|End User License|Privacy settings|Terms of Service|I agree|"
    r"Accept .{0,20}terms", re.I)


def validate(page, png: Path, framed: bool = False,
             expects_login: bool = False) -> tuple[bool, str]:
    if not png.exists() or png.stat().st_size < 3000:
        return False, "png missing/too small"
    try:
        body = page.inner_text("body", timeout=3000)[:4000]
    except Exception:
        body = ""
    if BAD_TEXT.search(body):
        m = BAD_TEXT.search(body)
        return False, f"error/login page ({m.group(0)!r})"
    if not expects_login:
        if LOGIN_TEXT.search(body):
            return False, f"shows a sign-in form ({LOGIN_TEXT.search(body).group(0)!r})"
        if CONSENT_TEXT.search(body):
            return False, f"shows a consent/EULA gate ({CONSENT_TEXT.search(body).group(0)!r})"
        try:
            # a bare password field with little else is a login screen even when the
            # wording doesn't match any phrase above
            if page.locator("input[type=password]").count() and \
                    page.evaluate("document.querySelectorAll('*').length") < 400:
                return False, "shows a password field (not signed in)"
        except Exception:
            pass
    try:
        nodes = page.evaluate("document.querySelectorAll('*').length")
        # A SMALL page is not an EMPTY one. The floor needs both facts: few nodes AND almost no
        # text. It was node-count alone, and the office's first-run wizard (`/install.html`,
        # core-004) — 38 nodes, because a wizard step is a heading, two paragraphs and a button —
        # came back `near-empty DOM (38 nodes)` while drawing every word it means to draw
        # (measured 2026-10-10: a false red on the one screen a person is supposed to read).
        # A shell stuck on its spinner keeps ~30 nodes and the single word "טוען…", so it is
        # still caught by the text half.
        text = body.strip()
        if nodes < 40 and len(text) < 200:
            return False, f"near-empty DOM ({nodes} nodes, {len(text)} chars of text)"
    except Exception:
        pass
    if framed:
        # the shell always has plenty of nodes, so an empty/broken embed would sail
        # through the page-level check — inspect the app inside the frame too
        try:
            inner = page.eval_on_selector(
                FRAME_SEL,
                "el => { const d = el.contentDocument;"
                " return d ? {n: d.querySelectorAll('*').length,"
                "             t: (d.body && d.body.innerText || '').slice(0, 2000)} : null; }")
            if not inner:
                return False, "embed frame unreachable"
            if inner["n"] < 30:
                # Say WHY in the verdict, not only that the frame is thin. When the shell's own
                # content pane is still on its "טוען…" spinner, the module never got its turn: the
                # console's boot is what failed, and EVERY framed view fails with the same
                # sentence. Measured 2026-10-10 — one dead shell (`biz is not defined` at
                # app.js:657, a stale call left by a refactor) was reported as 17 unrelated app
                # failures, and the sentence pointed at the apps instead of at the shell.
                try:
                    stuck = page.evaluate(
                        "() => { const c = document.getElementById('content');"
                        " return !!(c && c.querySelector('.spin') && !c.classList.contains('hidden')); }")
                except Exception:
                    stuck = False
                return False, ("console shell never opened the app (its content pane is still on the "
                               "spinner)" if stuck else f"embedded app near-empty ({inner['n']} nodes)")
            if BAD_TEXT.search(inner["t"] or ""):
                return False, f"embedded app shows error/login"
        except Exception:
            pass
    return True, "ok"


# ── coverage over raw CDP (Playwright's page.coverage is Node-only) ──────────

# styleSheetId -> sourceURL, learned from CSS.styleSheetAdded. ruleUsage entries carry
# only a styleSheetId, so without this map every stylesheet folds onto a synthetic key
# that report.py can't resolve to a repo path — which is why CSS read "n/a". The hook is
# registered once per CDP session (ids repeat across sessions, so re-arming is harmless).
_SHEET_URLS: dict[str, str] = {}
_CDP_HOOKED: set[int] = set()


def cov_start(cdp):
    try:
        cdp.send("Profiler.enable")
        cdp.send("Debugger.enable")
        cdp.send("Profiler.startPreciseCoverage", {"callCount": False, "detailed": True})
    except Exception as e:
        print(f"    ! JS coverage unavailable: {e}")
    try:
        cdp.send("DOM.enable")
        # Register the sheet->url listener BEFORE CSS.enable so the initial batch of
        # styleSheetAdded events (fired on enable for every existing sheet) is captured.
        if id(cdp) not in _CDP_HOOKED:
            def _on_added(p):
                h = p.get("header") or {}
                sid = h.get("styleSheetId")
                if sid:
                    _SHEET_URLS[sid] = h.get("sourceURL") or ""
            cdp.on("CSS.styleSheetAdded", _on_added)
            _CDP_HOOKED.add(id(cdp))
        cdp.send("CSS.enable")
        cdp.send("CSS.startRuleUsageTracking")
    except Exception as e:
        print(f"    ! CSS coverage unavailable: {e}")


def cov_take(cdp) -> dict:
    scripts, css = [], []
    try:
        res = cdp.send("Profiler.takePreciseCoverage")
        for entry in res.get("result", []):
            url = entry.get("url") or ""
            if not url or url.startswith(("chrome-extension://", "devtools://")):
                continue
            try:
                src = cdp.send("Debugger.getScriptSource",
                               {"scriptId": entry["scriptId"]}).get("scriptSource", "")
            except Exception:
                continue
            if not src:
                continue
            scripts.append({"url": url, "source": src, "functions": entry.get("functions", [])})
    except Exception as e:
        print(f"    ! takePreciseCoverage failed: {e}")
    try:
        # stopRuleUsageTracking returns ONLY the rules that matched (used=true), so a
        # used-count/total-count ratio is always 100% — meaningless. Measure BYTE coverage
        # instead, the way Chrome's own Coverage panel does: used = sum of the byte ranges
        # of matched rules, total = the stylesheet's length. Unused rules aren't listed but
        # their bytes are still in the denominator, so un-photographed states show as a gap.
        usage = cdp.send("CSS.stopRuleUsageTracking").get("ruleUsage", [])
        used_bytes: dict[str, int] = {}
        for r in usage:
            if r.get("used"):
                sid = r.get("styleSheetId")
                used_bytes[sid] = used_bytes.get(sid, 0) + (
                    r.get("endOffset", 0) - r.get("startOffset", 0))
        for sid, ub in used_bytes.items():
            try:
                text = cdp.send("CSS.getStyleSheetText", {"styleSheetId": sid}).get("text", "")
            except Exception:
                text = ""
            total = len(text)
            if not total:
                continue
            css.append({"styleSheetId": sid, "url": _SHEET_URLS.get(sid, ""),
                        "total": total, "used": min(ub, total), "len": total})
    except Exception as e:
        print(f"    ! CSS usage failed: {e}")
    return {"scripts": scripts, "css": css}


def merge_cov(takes: list[dict]) -> dict:
    """Keep per-view takes SEPARATE — do not concatenate their V8 ranges.

    V8 ranges are only meaningful within one take: coverage is computed by painting
    count>0 ranges and then subtracting count==0 blocks. Concatenating two takes lets a
    zero-count range from view B erase a line that view A genuinely executed, which is
    why merging raw ranges left the number stuck at 27% while the screenshots improved.
    The union must happen on computed LINE SETS, which report.py does by feeding each
    take to the accumulator separately (it ORs covered lines)."""
    return {"takes": [t for t in (takes or []) if t.get("scripts") or t.get("css")]}


# ── parameterised routes: resolve real ids from the live APIs ────────────────
#
# /repos/:repo and /folder/{id} can't be visited blind, and skipping them left 9 views
# permanently uncounted. seed_demo.py put real records behind these apps, so the ids
# exist — we just have to ask. Fetching through the console proxy means the request
# carries the same session the screenshots use.
PARAM_APIS = {
    # drive folders carry id/label (/api/folders), files carry fileId (app.py ops) —
    # NOT a bare id/name, which is why {file} never resolved and the tile stayed SKIPPED.
    "drive": [("{folder}", "/api/folders", ("id", "folderId", "label", "name")),
                   ("{file}", "/api/files", ("fileId", "id", "name"))],
    "mailview": [("{label}", "/api/labels", ("name", "label", "id")),
                 ("{id}", "/api/messages", ("id", "uid", "mid"))],
    # INDOX mounts its API under INCOMING_DOCS_API_PREFIX (default /incomingDocuments);
    # a bare /repos hits the SPA fallback and returns HTML, which is why this looked like
    # "no data" when the repos were there all along.
    "incoming-documents": [(":repo", "/incomingDocuments/repos", ("name", "repo", "id"))],
}


def _first_id(payload, keys):
    """Pull the first usable id out of whatever shape the API returned."""
    rows = payload
    if isinstance(payload, dict):
        for k in ("items", "rows", "data", "results", "folders", "files",
                  "messages", "labels", "repos"):
            if isinstance(payload.get(k), list):
                rows = payload[k]
                break
    if not isinstance(rows, list) or not rows:
        return None
    r = rows[0]
    if isinstance(r, str):
        return r
    if isinstance(r, dict):
        for k in keys:
            if r.get(k) not in (None, ""):
                return str(r[k])
        # fallback: any id-like field (fileId, folderId, docId, uid, …) so an unforeseen key name
        # doesn't leave the route SKIPPED
        for k, val in r.items():
            if "id" in k.lower() and val not in (None, "") and isinstance(val, (str, int)):
                return str(val)
    return None


def resolve_params(page, app: str, proxy: str, base: str = "") -> dict:
    # Host-resolved ids win: the host can query each container's API directly, whereas an
    # in-browser fetch through the console proxy came back empty. The in-browser path is
    # kept as a fallback for anything the host didn't supply.
    subs = {}
    try:
        if PARAMS_FILE.exists():
            subs.update(json.loads(PARAMS_FILE.read_text(encoding="utf-8")).get(app, {}))
    except Exception:
        pass
    for placeholder, api, keys in PARAM_APIS.get(app, []):
        if placeholder in subs:
            continue
        # absolute: a relative fetch resolves against whatever page the browser
        # is currently on, which for the first app in a shard is about:blank
        url = (base.rstrip("/") + (f"/a/{proxy}{api}" if proxy else api))
        try:
            payload = page.evaluate(
                "async u => { const r = await fetch(u, {credentials:'include'});"
                " return r.ok ? await r.json() : null; }", url)
        except Exception:
            payload = None
        got = _first_id(payload, keys) if payload is not None else None
        if got:
            subs[placeholder] = got
        else:
            kind = type(payload).__name__ if payload is not None else "no-response"
            n = len(payload) if isinstance(payload, (list, dict)) else "-"
            print(f"    ! {placeholder} unresolved from {url} ({kind}, n={n})")
    if subs:
        print(f"    resolved ids: {subs}")
    return subs


def apply_subs(text: str, subs: dict) -> str:
    for k, v in subs.items():
        text = text.replace(k, v)
    return text


# ── the walk ─────────────────────────────────────────────────────────────────

def base_url(view: dict, envmap: dict) -> str:
    host = envmap.get(view["host_env"]) or view["host_local"]
    host = host.replace("https://", "").replace("http://", "").rstrip("/")
    return ("http://" if host.endswith(".localhost") or "localhost" in host else "https://") + host


FRAME_SEL = "#frame"          # console/static/index.html — the embed iframe

# ── visible-region coverage ──────────────────────────────────────────────────
# Code-execution coverage answers "did this line run"; it does NOT answer "did the
# user SEE this". A region can be in the DOM (its handlers ran) yet be display:none,
# collapsed to zero height, or scrolled off-viewport — never actually photographed.
# This probe records, per shot, which "significant regions" were genuinely VISIBLE, so
# report.py can compute screenshot coverage and name every region no shot ever showed.
REGION_PROBE = r"""
() => {
  const RX = /(drawer|modal|dialog|overlay|panel|card|tab|timeline|accordion|collaps|menu|dropdown|popover|sheet|toast|section|view|sidebar|hud|detail|editor|list|grid|chart|form|filter)/i;
  const els = [...document.querySelectorAll('div,section,aside,dialog,details,nav,form,table,canvas,ul,[role],[id]')];
  const seen = new Set(); const out = [];
  for (const el of els) {
    const id = el.id || '';
    const cls = (typeof el.className === 'string' ? el.className : '') || '';
    const role = (el.getAttribute && el.getAttribute('role')) || '';
    const tag = el.tagName.toLowerCase();
    const significant = id || RX.test(cls) || RX.test(role) ||
                        ['dialog','aside','details','canvas','table','form'].includes(tag);
    if (!significant) continue;
    // Skip controls that are never meant to be seen: a hidden file <input> is the click
    // target behind an "upload" label, not a visible region — counting it can never reach 100%.
    if (tag === 'input') { const t = (el.getAttribute('type')||'').toLowerCase();
      if (t === 'file' || t === 'hidden') continue; }
    const key = id ? '#'+id : tag+'.'+cls.split(/\s+/).slice(0,2).join('.');
    if (!key || seen.has(key)) continue; seen.add(key);
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    // NB: do NOT use offsetParent to detect hidden ancestors — it is null for every
    // position:fixed element (drawers, modals, overlays), which would mark a fully-shown
    // drawer as hidden. checkVisibility() handles display:none on self+ancestors correctly.
    const cv = (typeof el.checkVisibility === 'function')
      ? el.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})
      : (cs.display!=='none' && cs.visibility!=='hidden');
    const shown = cv && parseFloat(cs.opacity||'1')>0 && r.width>3 && r.height>3;
    const inVp = r.bottom>0 && r.right>0 && r.top < innerHeight && r.left < innerWidth;
    out.push({key, visible: !!(shown && inVp)});
  }
  return out;
}
"""


AUDIT_JS = r"""
(() => {
  const out = { ok: true };
  const S = (v, n) => String(v).slice(0, n || 90);
  try {
    const de = document.documentElement, bd = document.body;
    out.doc = { w: de.clientWidth, h: de.clientHeight, scrollW: de.scrollWidth };
    out.pageOverflow = Math.max(0, de.scrollWidth - de.clientWidth);
    out.elements = bd ? bd.querySelectorAll('*').length : 0;

    const vis = el => {
      const cs = getComputedStyle(el);
      if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) return false;
      const r = el.getBoundingClientRect();
      return r.width > 0.5 && r.height > 0.5;
    };
    const desc = el => {
      const cls = (typeof el.className === 'string' && el.className.trim())
        ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : '';
      return S(el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + cls);
    };
    const bgOf = el => {                       // effective background: walk up to the first painted one
      for (let n = el; n && n !== document.documentElement; n = n.parentElement) {
        const c = getComputedStyle(n).backgroundColor;
        if (c && c !== 'transparent' && c.indexOf('rgba(0, 0, 0, 0)') !== 0) return c;
      }
      return 'rgb(255, 255, 255)';
    };
    const rgb = c => { const m = String(c).match(/[\d.]+/g) || []; return [+m[0] || 0, +m[1] || 0, +m[2] || 0]; };
    const lum = c => { const p = rgb(c).map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }); return 0.2126 * p[0] + 0.7152 * p[1] + 0.0722 * p[2]; };
    const contrast = (a, b) => { const l1 = lum(a), l2 = lum(b); return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05); };

    // The pointer decides the target: 44px on a phone, 28px under a mouse. Hard-coding 44 made
    // every desktop view look like it had failed the touch dimension (27 of 27 targets "small"),
    // which is a true statement about a finger and a false one about a mouse.
    const T = (window.__auditTarget || 44);
    const clipped = [], spilling = [], small = [], contrastFails = [], tinyText = [];
    const fonts = {}, lineRatios = {}, colors = {}, bgs = {}, heads = {}, btnH = {};
    let interactive = 0, textNodes = 0;
    // Real counts alongside the samples. The samples exist to NAME a defect in the report; the
    // counts exist to SCORE it — a version that scored off the samples treated eight 10px badges
    // and eight hundred as the same page, and zeroed a whole dimension at five defects.
    const counts = { clip: 0, spill: 0, small: 0, tiny: 0, squeezed: 0, contrast: 0 };
    const vw = de.clientWidth;

    if (bd) for (const el of bd.querySelectorAll('*')) {
      if (!vis(el)) continue;
      const cs = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      if (el.scrollWidth > el.clientWidth + 2 && !/auto|scroll/.test(cs.overflowX) && cs.overflowX !== 'visible') {
        counts.clip++;
        if (clipped.length < 8) clipped.push(desc(el));
      }
      if (r.right > vw + 2 && cs.position !== 'fixed') {
        counts.spill++;
        if (spilling.length < 8) spilling.push(desc(el) + ' @' + Math.round(r.right));
      }
      if (el.matches('button,a[href],input,select,textarea,[role=button],[role=tab]')) {
        interactive++;
        const h = Math.round(r.height), w = Math.round(r.width);
        // A 16px star inside a 42px row is NOT a touch failure: the thing a finger hits is the
        // row. Counting the inner control made a dense mail list (202 of 213 "too small") read
        // as the worst screen in the office, which is a statement about the RULE, not the row.
        // So a small control is excused when an interactive ancestor already offers the target.
        let excused = false;
        for (let n = el.parentElement; n && n !== bd; n = n.parentElement) {
          if (n.matches('button,a[href],[role=button],[role=tab],label,tr')) {
            const nr = n.getBoundingClientRect();
            if (nr.height >= T && nr.width >= T) { excused = true; break; }
          }
        }
        if (!excused && (h < T || w < T)) {
          counts.small++;
          if (small.length < 8) small.push(desc(el) + ' ' + w + 'x' + h);
        }
      }
      const hasText = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
      if (hasText) {
        textNodes++;
        const fs = Math.round(parseFloat(cs.fontSize) * 2) / 2;
        fonts[fs] = (fonts[fs] || 0) + 1;
        if (fs < 11) { counts.tiny++; if (tinyText.length < 8) tinyText.push(desc(el) + ' ' + fs + 'px'); }
        const lh = cs.lineHeight === 'normal' ? parseFloat(cs.fontSize) * 1.2 : parseFloat(cs.lineHeight);
        if (lh && fs && r.height > lh * 1.8) {
          const ratio = Math.round((lh / fs) * 100) / 100;
          if (ratio < 1.3) { counts.squeezed++; lineRatios[ratio] = (lineRatios[ratio] || 0) + 1; }
        }
        const bgr = bgOf(el), ratio = contrast(cs.color, bgr);
        const big = parseFloat(cs.fontSize) >= 18 || (parseFloat(cs.fontSize) >= 14 && parseInt(cs.fontWeight, 10) >= 700);
        if (ratio < (big ? 3 : 4.5)) {
          counts.contrast++;
          if (contrastFails.length < 8) {
            contrastFails.push(desc(el) + ' ' + ratio.toFixed(2) + ':1 ' + cs.color + ' on ' + bgr);
          }
        }
        colors[cs.color] = (colors[cs.color] || 0) + 1;
        bgs[bgr] = (bgs[bgr] || 0) + 1;
      }
      if (/^H[1-3]$/.test(el.tagName)) {
        (heads[el.tagName] = heads[el.tagName] || []).push(Math.round(parseFloat(cs.fontSize)));
      }
      if (el.tagName === 'BUTTON' || (el.classList && el.classList.contains('btn'))) {
        const h = Math.round(r.height);
        btnH[h] = (btnH[h] || 0) + 1;
      }
    }
    const top = (o, n) => Object.entries(o).sort((a, b) => b[1] - a[1]).slice(0, n || 6);
    out.clipped = clipped;
    out.spilling = spilling;
    out.interactive = interactive;
    out.smallTargets = small;
    out.textNodes = textNodes;
    out.counts = counts;
    out.target = (typeof T === 'number' ? T : null);
    out.fonts = fonts;
    out.tinyText = tinyText;
    out.lowLineHeight = lineRatios;
    out.contrastFails = contrastFails;
    out.textColors = top(colors, 8);
    out.bgColors = top(bgs, 8);
    out.distinctTextColors = Object.keys(colors).length;
    out.distinctBgColors = Object.keys(bgs).length;
    out.headings = Object.fromEntries(Object.entries(heads).map(([k, v]) => [k, v[0]]));
    out.buttonHeights = top(btnH, 6);
  } catch (e) {
    out.ok = false;
    out.error = S(e && e.message ? e.message : e, 140);
  }
  return out;
})()
"""


def page_audit(page, framed: bool = False) -> dict:
    """Measure what the score is MADE of — in the page the screenshot came from.

    In-page and in-load on purpose: a second browser pass would cost as much as the capture
    itself and could measure a different render (the stack is live; data moves between passes).
    For a framed view the numbers come from the APP's own document, because that is where the
    variation between our apps lives — the console chrome around it is one implementation for
    every tile, and measuring it 130 times would drown the signal.
    """
    try:
        target = page
        if framed:
            others = [f for f in page.frames if f != page.main_frame]
            if others:
                target = others[0]
        tgt = 44 if PROFILE.get("has_touch") else 28
        return target.evaluate(f"window.__auditTarget = {tgt};\n" + AUDIT_JS)
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:100]}"}


def probe_regions(page, framed: bool) -> list[dict]:
    """Significant regions and whether each was actually visible in THIS shot."""
    try:
        if framed:
            fr = next((f for f in page.frames
                       if f is not page.main_frame and f.url not in ("", "about:blank")), None)
            if fr is None:
                return []
            return fr.evaluate(REGION_PROBE)
        return page.evaluate(REGION_PROBE)
    except Exception:
        return []


def _frame(page):
    """The console renders each embedded app in #frame; wait for it to be live.

    ‏25s, not 15: measured 2026-09-28, telegram-tv's `view-series` recipe timed out waiting for the
    frame while the same app's `view-home` captured fine — the frame is created by the console's
    hash router, and a heavy first paint on this 4-core host can push it past 15s. `frame_click`
    already allowed itself 25s for the same reason; the two budgets should not disagree.
    """
    page.wait_for_selector(FRAME_SEL, timeout=25000)
    fl = page.frame_locator(FRAME_SEL)
    fl.locator("body").wait_for(state="attached", timeout=25000)
    return fl


def run_steps(page, steps: list[dict]):
    """Run a view's recipe. `frame_*` steps act INSIDE the console's embedded app."""
    for st in steps or []:
        try:
            if "frame_src" in st:
                # navigate the embedded app without leaving the shell, so the shot keeps
                # the console chrome around it. The console builds #frame asynchronously after
                # the hash route resolves, so eval_on_selector raced it and threw "Failed to
                # find" — which silently dropped the detail nav and left every extraction pane
                # showing the LIST page (all three tiles byte-identical). Wait for #frame first.
                page.wait_for_selector(FRAME_SEL, timeout=15000)
                page.eval_on_selector(
                    FRAME_SEL, "(el, src) => { el.src = src; }", st["frame_src"])
                page.wait_for_timeout(2200)
                _frame(page)
            elif "frame_js" in st:
                # The console loads the embedded app into #frame asynchronously (hash route
                # -> showEmbed sets #frame.src), so the child frame may not exist yet when a
                # frame_js-only recipe runs. Wait for the embed iframe, then prefer the real
                # app frame over the about:blank sibling before driving the app's own JS.
                _frame(page)
                fr = next((f for f in page.frames
                           if f is not page.main_frame and f.url not in ("", "about:blank")),
                          None) or next(
                          (f for f in page.frames if f is not page.main_frame), None)
                if fr is None:
                    return "frame_js: no embedded frame"
                try:
                    fr.wait_for_load_state("domcontentloaded", timeout=8000)
                except Exception:
                    pass
                fr.evaluate(st["frame_js"])
            elif "frame_click" in st:
                # embedded apps paint their nav only after their first data fetch, so
                # wait for the control to exist before clicking rather than racing it
                # (an 8s straight click timed out on every connections tab)
                tgt = _frame(page).locator(st["frame_click"]).first
                tgt.wait_for(state="visible", timeout=25000)
                tgt.click(timeout=10000)
            elif "frame_key" in st:
                _frame(page).locator("body").press(st["frame_key"], timeout=6000)
            elif "js" in st:
                # run JS in the app's own page (own-domain apps) — symmetric with frame_js.
                # Lets a state driver dismiss a first-run overlay and call the app's own view/
                # modal function, so the captured state doesn't depend on click actionability.
                page.evaluate(st["js"])
            elif "click" in st:
                page.locator(st["click"]).first.click(timeout=6000)
            elif "key" in st:
                page.keyboard.press(st["key"])
            elif "fill" in st:
                page.locator(st["fill"][0]).first.fill(st["fill"][1], timeout=6000)
            page.wait_for_timeout(800)
        except Exception as e:
            return f"step {list(st)[0]} failed: {str(e)[:70]}"
    return None


def main() -> int:
    """Shardable so the capture can run N processes in parallel.

    Parallelism is by PROCESS, not thread: Playwright's sync API objects can't be shared
    across threads, and each shard opening its own CDP connection to the same Chromium is
    both simpler and more robust. Sharding is by APP so an app's views stay in one process
    — they share a page and its accumulated coverage, which is the whole point.

    Usage:  ui-capture.py [app ...] [--shard I/N]
    """
    inv = json.loads(INV.read_text(encoding="utf-8"))
    envmap = json.loads(ENVMAP.read_text(encoding="utf-8")) if ENVMAP.exists() else {}
    argv = [a for a in sys.argv[1:]]
    shard_i, shard_n, tag = 0, 1, ""
    if "--shard" in argv:
        k = argv.index("--shard")
        shard_i, shard_n = (int(x) for x in argv[k + 1].split("/"))
        del argv[k:k + 2]
        tag = f".{shard_i}"
    only = set(argv) or None
    OUT.mkdir(parents=True, exist_ok=True)

    by_app: dict[str, list] = {}
    for v in inv["views"]:
        if only and v["app"] not in only:
            continue
        by_app.setdefault(v["app"], []).append(v)

    if shard_n > 1:
        # LPT bin-packing: assign each app (largest first) to the currently-least-loaded shard,
        # so the one heavy app (incoming-documents, ~16 slow extraction views) never stacks on
        # top of others and dominate the wall-clock. Deterministic — every shard runs the same
        # packing and keeps only its own apps. Balances far better than size-sorted round-robin
        # (which handed shard 0 the biggest + 5th + 9th apps and made it the long pole).
        ordered = sorted(by_app, key=lambda a: -len(by_app[a]))
        load = [0] * shard_n
        owner: dict[str, int] = {}
        for a in ordered:
            s = min(range(shard_n), key=lambda i: load[i])
            owner[a] = s
            load[s] += len(by_app[a])
        by_app = {a: vs for a, vs in by_app.items() if owner[a] == shard_i}
        print(f"[shard {shard_i}/{shard_n}] {len(by_app)} apps, "
              f"{sum(len(v) for v in by_app.values())} views: {sorted(by_app)}")

    results, raw_cov = [], {}

    def checkpoint() -> None:
        """Persist this shard's results after EVERY view.

        The shard used to write its two files once, at the very end. A shard killed by
        SHARD_TIMEOUT therefore lost every screenshot it had already taken: measured
        2026-09-27, three shards ran 1264s against a 900s cap, printed `CAPTURED ok` for
        dozens of views, and the merge afterwards reported **0 captured** while the PNGs sat
        on disk. That is the same class of lie this file already carries a scar for (the old
        `ls *.png | wc -l` success line measured the filesystem, not the work) — a timeout
        must degrade to a PARTIAL result, never to "nothing happened". A few KB per view is
        nothing next to a screenshot.
        """
        try:
            (DATA / f"ui-capture-results{tag}.json").write_text(
                json.dumps({"results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
            (DATA / f"ui-raw-coverage{tag}.json").write_text(
                json.dumps(raw_cov, ensure_ascii=False), encoding="utf-8")
        except Exception as e:                      # a failed checkpoint must not kill the shard
            print(f"  ! checkpoint failed: {type(e).__name__}: {str(e)[:60]}")

    with sync_playwright() as p:
        # Each shard LAUNCHES ITS OWN headless Chromium rather than sharing the cloaked
        # one over CDP. Sharing was the reason 3 of 4 shards died mid-run: every shard's
        # pages land in one browser, blow past BROWSER42_MAX_TABS, and browser42-reaper
        # sweeps them every 30s — plus concurrent CDP load on a single browser is exactly
        # what ai/context/browser42-cli.md warns crashes Chrome. Own browser per shard
        # removes the tab cap, the reaper and the contention in one move. It runs in the
        # same container, so the *.localhost -> Traefik forwarder still resolves, and we
        # do our own logins anyway so the shared profile's cookies aren't needed.
        if OWN_BROWSER:
            # Reuse the cloak browser's own Chromium binary rather than `playwright
            # install` (no bundled browser in this image, and a download per CI run is
            # both slow and fragile). Same binary the shared instance runs, just our own
            # process — which is the whole point.
            exe = os.getenv("UI_CHROME_BIN") or next(
                (str(g) for g in sorted(Path("/root/.cloakbrowser").glob("*/chrome"))), None) or next(
                (str(g) for g in sorted(Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome"))), None)
            args = ["--no-sandbox", "--disable-dev-shm-usage",
                    "--ignore-certificate-errors", "--disable-gpu"]
            # host-side runs (outside browser42) need *.localhost mapped to Traefik themselves, since
            # the browser42 loopback forwarder isn't in scope. UI_HOST_RESOLVER carries e.g.
            # "MAP *.localhost 127.0.0.1" so a sharded host-side capture reaches the stack via Traefik.
            hr = os.getenv("UI_HOST_RESOLVER")
            if hr:
                args.append(f"--host-resolver-rules={hr}")
            browser = p.chromium.launch(headless=True, executable_path=exe or None, args=args)
        else:
            browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        try:
            # Viewport, deviceScaleFactor, is_mobile and has_touch all come from the active view
            # profile (see _load_profile). The scale factor keeps downscaled map tiles and the
            # zoomable gallery crisp; is_mobile/has_touch make phone and tablet profiles behave like
            # real touch devices, so hover-only affordances correctly do NOT appear.
            ctx = browser.new_context(ignore_https_errors=True, viewport=VIEWPORT,
                                      locale="he-IL", **CTX_KWARGS)
        except Exception:
            ctx = browser.contexts[0]
        page = ctx.new_page()
        try:
            page.evaluate(f"window.name = 'b42:ui-map{tag or 0}'")
        except Exception:
            pass

        # ── warm-up: prime the console shell + its slow backend before the real loop ──────────
        # ROOT CAUSE of the console/my-docs first-shot failures: console boot() awaits
        # fetch("/api/business") (proxied to apitools) on the home route, and apitools is slow right
        # after the seed loads it — so boot blocks before rendering and the first views come back
        # near-empty / with no #frame. One throwaway load here pays the SSO + apitools/overview
        # warm-up cost once, so the real captures start against a warm stack instead of eating it.
        try:
            warm_base = base_url(next(iter(by_app.values()))[0], envmap)
            open_gated(page, warm_base + "/#/")
            page.wait_for_timeout(1500)
            for _ in range(6):   # poll the home shell until console actually renders (or ~18s)
                try:
                    n = page.evaluate("document.querySelectorAll('*').length")
                except Exception:
                    n = 0
                if n and n > 40:
                    break
                page.wait_for_timeout(2500)
                try:
                    page.reload(wait_until="domcontentloaded", timeout=20000)
                except Exception:
                    pass
            print(f"warm-up: console shell primed ({app if False else 'home'})")
        except Exception as e:
            print(f"warm-up skipped: {str(e)[:60]}")

        retry_queue = []   # (results_idx, view, base, subs) for failed first-party views to re-shoot warm
        for app, views in by_app.items():
            base = base_url(views[0], envmap)
            print(f"\n=== {app}  ({len(views)} views)  {base}")
            cdp = ctx.new_cdp_session(page)
            app_cov = []
            cov_start(cdp)

            if views[0]["auth"] == "own":
                if app == "chat":
                    chat_login(page, base)
                elif app == "n8n" and N8N_USER:
                    n8n_login(page, base, N8N_USER, N8N_PASS)
                elif app == "portainer" and PT_PASS:
                    portainer_login(page, base, PT_PASS)
                elif app == "glitchtip" and GT_USER:
                    glitchtip_login(page, base, GT_USER, GT_PASS)
            if app == "redisinsight":
                redisinsight_consent(page, base)
            elif app == "browser42" and VNC_PASS:
                browser42_connect(page, base, VNC_PASS)

            subs = resolve_params(page, app, views[0].get("proxy", ""), base)
            for v in views:
                # ':' is legal in a Linux filename and illegal on Windows, so a view id
                # like repos-:repo wrote fine inside the container and then vanished on
                # the copy to the host — the result still said CAPTURED while the tile had
                # no image. Sanitise once, here, so name and status can't disagree.
                name = f"{app}__{v['id']}".replace(":", "-")
                png = OUT / f"{name}.png"
                status, note = "failed", ""
                try:
                    url = v.get("url") or "/"
                    # parameterised routes (":repo", "{folder}") can't be visited blind.
                    # For framed views the parameter hides in the frame_src step, so check
                    # the PATH values only — an earlier version regexed json.dumps(steps)
                    # and matched the JSON syntax's own "{" and ":", skipping every framed
                    # view that had a recipe.
                    url = apply_subs(url, subs)
                    for st_ in (v.get("steps") or []):
                        if "frame_src" in st_:
                            st_["frame_src"] = apply_subs(st_["frame_src"], subs)
                    paths = [url] + [s["frame_src"] for s in (v.get("steps") or [])
                                     if "frame_src" in s]
                    if any(re.search(r"[:{]", p.replace("/#/", "")) for p in paths):
                        status, note = "skipped", "parameterised route (needs seeded id)"
                        results.append({**v, "status": status, "note": note, "png": None})
                        print(f"  - {v['id']:<24} SKIP  {note}")
                        checkpoint()
                        continue
                    full = base + (url if url.startswith("/") else "/" + url)
                    # A hash-only change is a SAME-DOCUMENT navigation: the browser does
                    # not reload, so whatever the previous view left open stays open.
                    # That is how one Ctrl-K palette leaked into all 39 framed tiles —
                    # every one of them photographed the same stuck modal. Force a real
                    # document load so each view starts from a clean DOM.
                    # WHAT EXACTLY IS OPENED, said out loud. A view that renders empty is
                    # indistinguishable from a view whose URL was never the one the caller
                    # meant — measured 2026-10-09 (DGO-56): the capture's edge proxy logged the
                    # console's own assets and then nothing, and there was no way to tell whether
                    # the frame, the module URL or the navigation itself was the one that differed.
                    print(f"[ui-map] open: {full}", flush=True)
                    prev = page.url or ""
                    same_doc = prev.split("#")[0] == full.split("#")[0] and "#" in full
                    if v["auth"] == "authentik":
                        open_gated(page, full)
                    else:
                        page.goto(full, wait_until="domcontentloaded", timeout=30000)
                        settle(page)
                    if same_doc:
                        try:
                            page.reload(wait_until="domcontentloaded", timeout=30000)
                            settle(page)
                        except Exception:
                            pass
                    try:                      # belt and braces for non-hash leftovers
                        page.keyboard.press("Escape")
                        page.wait_for_timeout(200)
                    except Exception:
                        pass
                    if v.get("steps"):
                        err = run_steps(page, v["steps"])
                        if err:
                            note = err
                    if v.get("framed"):
                        hydrate_frame(page)
                    page.wait_for_timeout(600)
                    for kw in ({"animations": "disabled", "timeout": 20000},
                               {"timeout": 10000}, {"timeout": 6000}):
                        try:
                            page.screenshot(path=str(png), **kw)
                            break
                        except Exception:
                            continue
                    ok, why = validate(page, png, framed=bool(v.get("framed")),
                                       expects_login=("login" in v["id"]))
                    regions = probe_regions(page, framed=bool(v.get("framed")))
                    audit = page_audit(page, framed=bool(v.get("framed")))
                    app_cov.append(cov_take(cdp))
                    cov_start(cdp)          # re-arm for the next view
                    status = "captured" if ok else "failed"
                    note = note or why
                except Exception as e:
                    note = f"{type(e).__name__}: {str(e)[:90]}"
                    regions = []
                    audit = None
                results.append({**v, "status": status, "note": note, "regions": regions,
                                "audit": audit,
                                "png": f"ui/{name}.png" if status == "captured" else None})
                print(f"  - {v['id']:<24} {status.upper():<9} {note[:60]}")
                checkpoint()
                # The first apps captured (console, then my-docs) can fail because the console home
                # probes every backend serially (/api/overview) before those backends have warmed up;
                # by the time later apps are shot the whole stack is warm. Queue failed first-party
                # views to re-shoot at the end rather than lose the tile to a cold-start race.
                if status == "failed" and v.get("tier") != "third_party" and "login" not in v["id"]:
                    retry_queue.append((len(results) - 1, v, base, dict(subs)))

            # Coverage is taken AFTER EVERY VIEW and merged, not once per app. Forcing a
            # reload to clear stuck modals also resets V8's counters, so a single take at
            # the end only ever saw the last page load — that alone dropped the reported
            # number from 33% to 27% while the screenshots were getting BETTER.
            raw_cov[app] = merge_cov(app_cov)
            try:
                cdp.detach()
            except Exception:
                pass

        # ── warm-system retry pass ───────────────────────────────────────────────────────────
        # Re-shoot the first-party views that failed on the first go. The whole stack is warm now
        # (every later app captured fine), so a console-home /api/overview probe that stalled at the
        # start — dropping console + my-docs to a near-empty DOM / frame timeout — now returns fast.
        # Only failures are retried, so the happy path is unaffected; caps at 40 to bound a bad run.
        if retry_queue:
            print(f"\n=== retry {len(retry_queue)} failed first-party views (stack warm) ===")
            for idx, v, base, subs in retry_queue[:40]:
                app = v["app"]
                name = f"{app}__{v['id']}".replace(":", "-")
                png = OUT / f"{name}.png"
                status, note, regions = "failed", "", []
                try:
                    url = apply_subs(v.get("url") or "/", subs)
                    full = base + (url if url.startswith("/") else "/" + url)
                    if v["auth"] == "authentik":
                        open_gated(page, full)
                    else:
                        page.goto(full, wait_until="domcontentloaded", timeout=30000)
                        settle(page)
                    try:
                        page.reload(wait_until="domcontentloaded", timeout=30000)
                        settle(page)
                    except Exception:
                        pass
                    try:
                        page.keyboard.press("Escape")
                        page.wait_for_timeout(200)
                    except Exception:
                        pass
                    if v.get("steps"):
                        note = run_steps(page, v["steps"]) or ""
                    page.wait_for_timeout(900)
                    for kw in ({"animations": "disabled", "timeout": 20000},
                               {"timeout": 10000}, {"timeout": 6000}):
                        try:
                            page.screenshot(path=str(png), **kw)
                            break
                        except Exception:
                            continue
                    ok, why = validate(page, png, framed=bool(v.get("framed")),
                                       expects_login=("login" in v["id"]))
                    regions = probe_regions(page, framed=bool(v.get("framed")))
                    audit = page_audit(page, framed=bool(v.get("framed")))
                    status = "captured" if ok else "failed"
                    note = note or why
                except Exception as e:
                    note = f"retry {type(e).__name__}: {str(e)[:80]}"
                    audit = None
                if status == "captured":
                    results[idx] = {**v, "status": status, "note": note, "regions": regions,
                                    "audit": audit, "png": f"ui/{name}.png"}
                    print(f"  - {v['id']:<24} RECOVERED")
                    checkpoint()
                else:
                    print(f"  - {v['id']:<24} still-failed  {note[:50]}")

        try:
            page.close()
        except Exception:
            pass

    (DATA / f"ui-capture-results{tag}.json").write_text(
        json.dumps({"results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    (DATA / f"ui-raw-coverage{tag}.json").write_text(
        json.dumps(raw_cov, ensure_ascii=False), encoding="utf-8")
    cap = sum(1 for r in results if r["status"] == "captured")
    print(f"\ncaptured {cap}/{len(results)} views "
          f"({sum(1 for r in results if r['status']=='skipped')} skipped)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
