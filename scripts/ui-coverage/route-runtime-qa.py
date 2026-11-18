#!/usr/bin/env python3
"""route-runtime-qa — the RUNTIME half of G83: every screen the inventory declares, opened at its
own console address and read back out of a real browser.

G83 (`scripts/refactor/embed-route-lint.py`) is the STATIC half: it asks whether an app's source
reads the path the shell hands it and writes its own path back. This is the other half, and it is
the one the owner asked for — "the address is the state, in every app": for every view
`scripts/ui-coverage/inventory.py` declares for THIS office, open `#/m/<module><route>` in the
console and require that

  1. the frame has ARRIVED at that route — its own URL is `/a/<proxy><route>`, the identity mapping
     the console contract is built on (a view whose route is the module's root is allowed to land on
     the app's own default screen: that is what "open the app" means); and
  2. the shell's own address bar CARRIES the route back, so the screen can be copied and sent.

The route of a view comes from the inventory itself: after `rewrite_for_console` a framed view's
`url` is `/#/m/<module>`, and its own inner route is the leading `frame_src` step. Views that share a
route (a rail item and the drawer inside it) are measured once and counted each — the route is a
property of the address, not of the recipe.

    bash scripts/ui-coverage/route-runtime-qa.sh        # the ONE command: params, browser, verdict

Exit code is non-zero when any declared view fails: it did not open at its address, the shell's
address does not carry it back, it was NOT DRAWN — `drawn.py`'s rule, so a screen still saying
«טוען…» (or still a skeleton, or still growing) at the camera's cap is a FAILURE, never a PASS with
a note beside it (rel-2; the 2026-10-27 card measured `sites/new` and `sites/adopt` never drawn and
the run exit 0) — or ITS OWN ADDRESS THREW (rel-2ג). The browser's `pageerror`s were collected,
counted and printed and never reached the verdict: a run carrying 39 of them printed `FAILED 0` and
exited 0. A runtime error is now a failure of the SCREEN it happened on, the first one is printed with
that screen's name, and it stops failing the run only when the screen is named in
`runtime-error-exclusions.yaml` with a `why` and a `root` — an exemption that matches no declared
screen is a failure of the run, unless the inventory says its app does not run on this office
(`not_here`): then it is another office's record, printed as a NOTE. A screen that IS drawn but took longer than `drawn.BUDGET_MS` is
SLOW: it is printed
on its own line with its address and time, listed in the JSON's `slow`, and is NOT a failure — the
acceptance is «נצבע», not «נצבע מהר». `--self-test` drives this verdict against a page that never
stops loading, and against one that is drawn and throws. A route carrying a
parameter (`:type`, `{name}`) is reported as SKIPPED with its name: filling it is
`resolve_params.py`'s job, and a guessed value would measure the guess.

THE PARAMETERS ARE NOT A HAND STEP (rel-2). The values come from `resolve_params.py`, which asks
each app's own live API on the HOST (it reads the containers through `docker exec`) and writes
`data/browser42/ui-params.json` — a GITIGNORED file that nothing in this path used to produce. So on
a fresh clone, and in CI, every parameterised view was SKIPPED and the run was whole only on the
office where someone had made that file by hand. `route-runtime-qa.sh` is that missing half: it
resolves when the file is absent or empty (or with `--resolve`), WARNS and continues if the resolve
fails, and then runs this file in the browser image. Run standalone — inside an image that carries
Playwright + Chromium, on the office network, with the checkout mounted — it is the same driver:

    docker run --rm --network traefik-network -v "$PWD:/w" -w /w \\
      --entrypoint python3 <an-image-with-playwright> \\
      scripts/ui-coverage/route-runtime-qa.py --url http://console:8000
"""
from __future__ import annotations

import argparse
import contextlib
import json
import re
import sys
from pathlib import Path
import unicodedata
from urllib.parse import unquote, urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import drawn  # noqa: E402  (the office's one "is this screen drawn" rule)
import inventory  # noqa: E402  (the denominator: what this office has)
import yaml  # noqa: E402  (the exemption declaration, rel-2ג)

from playwright.sync_api import sync_playwright  # noqa: E402

# Hebrew in what this prints: a view's route and the app's own address can both be Hebrew (a mail
# label is), so the report carries it. Python's stdout is the ANSI codepage on Windows (cp1255) and
# dies on it; Linux and macOS are already UTF-8, where this is a no-op. Same guard as drawn.py.
# stderr too: the admins' door refusal (REFUSED_JS, «למנהלי הלשכה בלבד») is Hebrew as well (fd069d387, G10)
for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(AttributeError, ValueError):
        _stream.reconfigure(encoding="utf-8")

AUTH = {"X-authentik-username": "admin", "X-authentik-email": "admin@office.local",
        "X-authentik-name": "Admin", "X-authentik-groups": "authentik Admins"}

FRAME_WAIT_MS, FRAME_POLL_MS = 20000, 250

#: the console's refusal at an admins' door: its card (`data-card` on <html>, platform-base/console/app.py `_card`)
#: whose line is «למנהלי הלשכה בלבד» (`_not_for_you`) — the card of an app with no screen is a different line
#: (2899be18f, DGO-1813)
REFUSED_JS = ("() => !!document.documentElement && document.documentElement.hasAttribute('data-card')"
              " && ((document.querySelector('.xn-sub') || {}).textContent || '').trim() === 'למנהלי הלשכה בלבד'")


def norm(path: str) -> str:
    """A path without its trailing slash — `/a/drive/` and `/a/drive` are one address."""
    p = unp(path).split("?")[0].split("#")[0]
    return p.rstrip("/") or "/"


def unp(s: str) -> str:
    """An address in the one spelling two of them can be compared in: percent-decoded and NFC.

    A route reaches this file as TEXT — the inventory's `frame_src` with the app's own value filled in
    (`mail/label/אוטומציה-דוחות-גיול-נכשלה`, a label the office really has). The browser normalises
    the same address to its wire spelling before it is read back (`location.hash` and a frame's URL
    are ALWAYS percent-encoded: `/label/%D7%90%D7%95…`), so comparing the two as strings asked whether
    the browser spells Hebrew the way a Python literal does — it does not, and a screen that opened
    perfectly was reported as one that never arrived. This is the same address, not a favicon."""
    return unicodedata.normalize("NFC", unquote(s))


def canon(s: str) -> str:
    """A route in the one form two of them can be compared in: leading slash, no trailing slash, no
    fragment, query kept. `norm` is the same idea for a path alone — this one is safe for a console
    address, whose own `#` is not a fragment separator to strip."""
    p, _, q = unp(s).split("#")[0].partition("?")
    return (p.rstrip("/") or "/") + (("?" + q) if q else "")


def view_route(v: dict) -> str | None:
    """The view's own inner route, or None when the inventory cannot name one.

    A framed view's `steps[0]` is the leading `frame_src` the compiler wrote; without it the view is
    the module's root. `None` means the step is a recipe without an address (a tab inside a screen)
    and there is nothing of its own to open."""
    steps = v.get("steps") or []
    for s in steps:
        src = s.get("frame_src")
        if src:
            proxy = v.get("proxy") or ""
            for pref in (f"/a/{proxy}", f"/a/{proxy}/"):
                if src.startswith(pref):
                    return "/" + src[len(pref):].lstrip("/") if src != pref else "/"
            return src if src.startswith("/") else "/" + src
        break
    return "/"


def fill(route: str, subs: dict) -> str:
    """A parameterised route with the values `resolve_params.py` resolved for THIS office.

    The map already resolves `{folder}`, `{id}`, `{site}`, `{account}`/`{domain}` from each app's own
    API (onto a real screen of this office, never a guess), so the address of a detail view is
    measurable for the same reason a root screen is: the app has one."""
    out = route
    for k, val in (subs or {}).items():
        forms = {k}
        if k.startswith("{") and k.endswith("}"):     # the map writes both styles: {folder} and :repo
            forms.add(":" + k[1:-1])
        for f in forms:
            out = out.replace(f, str(val))
    return out


def frames_of(page, proxy: str):
    for f in page.frames:
        if f is page.main_frame:
            continue
        if f"/a/{proxy}" in urlparse(f.url).path:
            return f
    return None


def measure(page, base: str, module: str, proxy: str, route: str, redirect: bool = False) -> dict:
    """Open one address and read the things the contract is made of."""
    deep = f"{base}/#/m/{module}{'' if route == '/' else route}"
    page.goto("about:blank")           # a fresh page: the address before this one must not answer
    page.goto(deep, wait_until="domcontentloaded", timeout=60000)
    rp = canon(route).split("?")[0]     # the route's PATH: a query, or an app's own `#` mirror inside
    if rp == "/":                        # its address, is not a path to wait for
        rp = ""
    frame, waited, seen_at = None, 0, ""
    while waited < FRAME_WAIT_MS:
        page.wait_for_timeout(FRAME_POLL_MS)
        waited += FRAME_POLL_MS
        f = frames_of(page, proxy)
        if f is None:
            continue
        seen_at = urlparse(f.url).path
        # The frame must be the one THIS request asked for. Waiting for "a frame of this app" was
        # enough to read the PREVIOUS address's frame while the new one was still coming: `sync`
        # was reported as sitting on `/repos`. A root request asks for no particular screen, so any
        # frame of the app is its answer; a REDIRECT has to be waited for until it has moved, or it
        # is read mid-flight sitting on the address it is about to leave (`/sync`, twice).
        if not rp or (redirect and norm(seen_at) != rp) or \
                (not redirect and norm(seen_at).endswith(rp)):
            frame = f
            break
    if frame is None:
        return {"arrived": False, "mirrored": False, "frame": seen_at, "hash": "",
                "why": f"no frame of /a/{proxy} at {rp} after {waited / 1000:g}s"
                       + (f" (the app is on {seen_at})" if seen_at else "")}
    d = drawn.wait(page.evaluate, page.wait_for_timeout)
    # REFUSED — the admins' door answered its card (403, «למנהלי הלשכה בלבד») AT the requested address. Read
    # through the checks below it would pass: the frame is where it was asked to be and the shell names it.
    # It is the run that is not signed in as an admin (DGO-1813), and it is said as that, never as a PASS.
    try:
        refused = frame.evaluate(REFUSED_JS)
    except Exception:  # noqa: BLE001 — a frame that navigated away mid-read is not a refusal
        refused = False
    if refused:
        return {"arrived": False, "mirrored": False, "frame": urlparse(frame.url).path, "hash": "",
                "why": "the admins' door refused this run's identity (its 403 card) — sign in as an admin "
                       "(--storage-state from bbox flow-qa-session)"}
    fr = urlparse(frame.url)
    # THE FRAME'S ADDRESS KEEPS ITS QUERY (fixed 2026-11-09). `norm` throws away everything after `?`
    # by design — it is the PATH comparison — and it was used here, so `got_path` could never carry a
    # `?`: the search-term check below fired on EVERY route that has one, and `frame` in the JSON named
    # an address the frame was never on (`/a/drive/search` for `/a/drive/search?q=doc`). Measured
    # against a `drive` that does take `q` out of the address: its search field held `פגישות`,
    # `api/search?q=פגישות` was in its own resource log and the row was drawn. A query IS the screen's
    # state (the office's rule, «הכתובת היא המצב»), so dropping it measured the wrong thing and then
    # blamed the app for it. `canon` is the same normalisation with the query kept.
    got_path = canon(fr.path + ("?" + fr.query if fr.query else ""))
    got_hash = page.evaluate("() => location.hash")
    req = canon(f"/a/{proxy}{'' if route == '/' else route}")
    # ARRIVED — the app opened the screen that was asked for. Two shapes are honest: the frame is
    # exactly at the requested path, or the app answered with a LONGER address that ends in it,
    # because the screen needs a segment the view's route does not carry (incoming documents the
    # instance: `/documents` answers at `/i/<instance>/documents`). What is not honest, and is
    # caught here, is an app that ignores the path and shows its default screen.
    path_c = canon(got_path.split("?")[0])
    if redirect:
        # A REDIRECT address (the inventory marks it: the app's own source calls it a redirect) is not
        # a screen and promises only one thing — an old link still lands INSIDE the app, and the
        # address bar then names where it landed (the mirror check below). `/repos` answering the
        # documents screen is that promise kept, not a failure.
        arrived = path_c.startswith(f"/a/{proxy}/") and path_c != canon(req.split("?")[0])
        why = "" if arrived else f"the redirect {req} did not resolve inside the app ({got_path})"
    elif route == "/":                    # the module's root: the app's own default screen is right
        arrived = path_c == canon(f"/a/{proxy}") or path_c.startswith(f"/a/{proxy}/")
        why = "" if arrived else f"opened /a/{proxy} but the frame is at {got_path}"
    else:
        arrived = path_c == canon(req.split("?")[0]) or \
            (path_c.startswith(f"/a/{proxy}/") and path_c.endswith(rp))
        why = "" if arrived else f"asked for {req}, the frame is at {got_path}"
    # A query in the route is the screen's own state (a search term): an app that opens the screen
    # but does not take the term out of the address is SAID, and is not a screen that failed to open.
    if arrived and "?" in req and "?" not in got_path:
        why = f"opened, but the app did not take {req.split('?')[1]} out of the address"
    # MIRRORED — the shell's address names the screen the frame is actually ON (the identity
    # mapping). Comparing with the REQUEST instead would fail an app that canonicalises its own
    # address (`/` -> `/dash`), which is the app being right, not the shell being wrong. The PATH is
    # what must agree; a query the shell still carries after an app dropped it is the app's gap to
    # close and is said as one (the NOTE above), not a screen that failed to open.
    tail = got_path[len(f"/a/{proxy}"):] if got_path.startswith(f"/a/{proxy}") else ""
    want_hash = canon(f"/m/{module}{'' if tail == '/' else tail}")
    got_route = canon(got_hash.lstrip("#")) if got_hash.startswith("#/") else ""
    frame_query = tail.partition("?")[2]
    mirrored = got_route.split("?")[0] == want_hash.split("?")[0] and \
        (not frame_query or frame_query in got_route)
    if not mirrored:
        why = (why + "; " if why else "") + (f"the shell's address holds {got_hash or 'nothing'}, "
                                             f"the frame is on {got_path}")
    if not d["drawn"]:
        why = (why + "; " if why else "") + drawn.said(d)
    # `drawn`/`is_drawn`/`slow` are the measurement, and the VERDICT is not made here: rel-2 found
    # `drawn` measured, written to the JSON and then left out of the pass/fail decision, so a screen
    # photographed as «טוען…» at the camera's cap printed PASS and the run exited 0 — the exact
    # failure the 2026-10-27 card measured on `sites/new` (never drawn, PASS, EXIT 0). `is_drawn` is
    # the boolean the run is decided on; `drawn` stays the sentence for a person.
    return {"arrived": arrived, "mirrored": mirrored, "frame": got_path, "hash": got_hash,
            "drawn": drawn.said(d), "is_drawn": bool(d["drawn"]),
            # SLOW is only a finding of a screen that DID open: an undrawn screen is a FAIL and its
            # own sentence already says it (`drawn.wait` reports `slow` for it too).
            "slow": bool(d["drawn"] and d["slow"]), "drawn_ms": d["ms"], "why": why}


def passed(m: dict) -> bool:
    """THE VERDICT of one view, in one place — and the whole of rel-2 lives in this line.

    Three things, none optional: the frame ARRIVED at the route, the shell's address CARRIES it
    back, and the screen was DRAWN (`drawn.py`: nothing in sight is a skeleton/a spinner/«טוען…»,
    and it has stopped growing). The run used to ask only the first two, so a screen photographed as
    «טוען…» at the camera's cap printed PASS and the process exited 0 — measured 2026-10-27 on
    `sites/new` and `sites/adopt`. `--self-test` drives this function over a page that never stops
    loading, so the omission cannot come back unnoticed.
    """
    return bool(m["arrived"] and m["mirrored"] and m["is_drawn"])


def exit_code(fails: list[str]) -> int:
    """A run's verdict as a number, in ONE place: one view that failed is not a passing run."""
    return 1 if fails else 0


# ── A RUNTIME ERROR ON A SCREEN IS A FAILURE OF THAT SCREEN (rel-2ג) ─────────────────────────────
# `page.on("pageerror", …)` was collected, printed as a count and written to the JSON — and never
# reached `fails`. So a run with 39 JS errors (React #418, a hydration mismatch) printed `FAILED 0`
# and exited 0: exactly the disease `drawn` had, a measurement that exists beside the verdict
# instead of inside it. The rule now is the same rule as «נצבע»: the error is a failure of the
# SCREEN it happened on (a different screen's errors are a different screen's business), the first
# one is printed with the screen's own name, and the denominator keeps counting it once.
#
# AN EXEMPTION IS A NAMED PROMISE, NEVER A SILENT ONE. `runtime-error-exclusions.yaml` holds records
# of `app`, `view`, `why` (what the error IS) and `root` (where the fault lives, and the item that
# owns it). A record is matched by NAME; a record that matches no declared screen is itself a
# failure, because an orphan exemption is a hole in the measurement, not a pass.
RUNTIME_EXCL = HERE / "runtime-error-exclusions.yaml"
EXCL_FIELDS = ("app", "view", "why", "root")


def load_runtime_exclusions(inv: dict, path: Path | None = None) -> tuple[dict, list[str]]:
    """({(app, view): {why, root}}, failures of the declaration itself).

    The file is optional (no file = no exemptions, which is the honest state of a healthy run). What
    is NOT optional is the shape: every record says all four things, every record names a screen
    this office actually declares, and no screen is exempted twice. Anything else is returned as a
    failure of the RUN — a declaration that does not hold is not an exemption.
    """
    p = Path(path) if path is not None else RUNTIME_EXCL
    if not p.exists():
        return {}, []
    try:
        rows = yaml.safe_load(p.read_text(encoding="utf-8")) or []
    except Exception as e:  # noqa: BLE001  a broken declaration is said, never swallowed
        return {}, [f"{p.name} is not readable YAML: {e}"]
    if not isinstance(rows, list):
        return {}, [f"{p.name} must be a list of {', '.join(EXCL_FIELDS)} records"]
    declared = {(v["app"], v["id"]) for v in inv["views"]}
    # One file for every office: an exemption of an app the INVENTORY says this office does not run (`not_here`) is
    # another office's record, not an orphan here (vps1 runs no Plane, and its run failed on «project-pln main» — the
    # HP's and EXF's record; DGO-1839). It is said, never dropped quietly; any other key that names no screen (a typo,
    # another naming scheme) is still an orphan.
    not_here = set(inv.get("not_here") or {})
    out: dict = {}
    bad: list[str] = []
    for i, r in enumerate(rows, 1):
        if not isinstance(r, dict):
            bad.append(f"{p.name} row {i}: not a record — {', '.join(EXCL_FIELDS)} are required")
            continue
        missing = [k for k in EXCL_FIELDS if not str(r.get(k) or "").strip()]
        if missing:
            bad.append(f"{p.name} row {i}: says nothing in {', '.join(missing)} — an exemption "
                       f"without a reason or a root is a hiding place")
            continue
        key = (str(r["app"]).strip(), str(r["view"]).strip())
        if key not in declared and key[0] in not_here:
            print(f"  NOTE  {p.name}: «{key[0]} {key[1]}» is another office's record — {key[0]} does not run here")
            continue
        if key not in declared:
            bad.append(f"{p.name}: «{key[0]} {key[1]}» matches no declared screen — an orphan "
                       f"exemption is a failure, not a pass")
            continue
        if key in out:
            bad.append(f"{p.name}: «{key[0]} {key[1]}» is declared twice")
            continue
        out[key] = {"why": str(r["why"]).strip(), "root": str(r["root"]).strip()}
    return out, bad


def runtime_error_words(errs: list[str], limit: int = 200) -> str:
    """The FIRST runtime error, on one line and short — what `FAIL <app> <view> — …` says."""
    s = " ".join(str(errs[0]).split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


def screen_verdict(base_ok: bool, errs: list[str], exclusion: dict | None,
                   detail: str = "") -> tuple[str, str]:
    """ONE SCREEN'S VERDICT, in one place: 'pass' | 'fail' | 'excluded', and the words for it.

    `base_ok` is the screen's own verdict without JS (drawn at its address, or not);
    `errs` are the runtime errors the browser raised while THAT address was being measured;
    `exclusion` is the record this screen is named in, if it is. Three outcomes and no fourth:

      - not drawn → fail, whatever else is true of it (an exemption names an ERROR, never a screen
        that never appeared, so it cannot rescue one);
      - drawn, clean → pass;
      - drawn, threw → excluded when it is named, fail when it is not.

    A screen that failed and also threw says both, in one line, so a runtime error is never a
    thing the reader of a failed screen has to go and find in a log.
    """
    if not base_ok:
        words = (f" · runtime error on it: {runtime_error_words(errs)}" if errs else "")
        return "fail", (detail or "unknown") + words
    if not errs:
        return "pass", ""
    said = runtime_error_words(errs)
    if exclusion:
        return "excluded", f"runtime_error: {said} — {exclusion['why']} (root: {exclusion['root']})"
    return "fail", f"runtime error on a drawn screen: {said}"


# ── THE SECOND MEASUREMENT PATH: a first_party view that has no proxy (rel-2, phase 2) ─────────
# The loop below used to start with `if not v.get("framed") or v["tier"] != "first_party":
# continue` — a SILENT skip. Sixteen of this office's own screens (console ×9, machine ×4, cad,
# meet, project-pln) therefore sat outside a denominator that printed «72 declared view(s) … 72 open
# and drawn» and exited 0: a perfect guide to a denominator that was not the office. A view with no
# proxy is not a view without a screen — it simply stands on a host of its own, so it is opened
# THERE, with the same identity the framed path carries (`AUTH`), and judged by the same rule.

ROOT = HERE.parent.parent


def app_json(app: str) -> dict:
    """The app's own manifest, from the layer it declares itself in."""
    for rel in (f"apps/{app}/app.json", f"platform-base/{app}/app.json"):
        p = ROOT / rel
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return {}
    return {}


def app_base(app: str, console_url: str, hosts: dict) -> str:
    """The address an app answers on, taken from the DECLARATION and never from memory.

    `--hosts MACHINE_BASE_URL=http://machine:8080,cad=http://cad:3000` wins (a smaller engine, a
    dev box); else the `url` of the app's own console module in its app.json — what the compiler
    renders and what the console itself frames; else its health probe's address. The console is the
    exception: this run was handed it already (`--url`), and the framed half measures it there.
    """
    if app == "console" or app == "CONSOLE_BASE_URL":
        return console_url.rstrip("/")
    for k in (f"{app.upper().replace('-', '_')}_BASE_URL", app):
        if hosts.get(k):
            return str(hosts[k]).rstrip("/")
    j = app_json(app)
    for r in j.get("routing") or []:
        u = str((r.get("module") or {}).get("url") or "")
        if u.startswith(("http://", "https://")) and "${" not in u:
            return u.rstrip("/")
    probe = str((j.get("health") or {}).get("probe", {}).get("http") or "")
    if probe.startswith(("http://", "https://")):
        p = urlparse(probe)
        return f"{p.scheme}://{p.netloc}"
    return ""


def direct_target(v: dict) -> str:
    """Where on its own host this view stands.

    `/#/m/<module>` is the CONSOLE's address for an app that lives on a host of its own
    (`host_override: console` in the inventory) — opening it would measure the console's tile, not
    the app's screen, so such a view is opened at the app's root. Everything else is taken as the
    inventory spells it: a `#/…` state, a `/install.html`, or a plain route.
    """
    u = (v.get("url") or "").strip()
    if v["app"] != "console" and re.match(r"^/?(\?)?#/m/", u):
        return "/"
    return u or "/"


def hc(s: str) -> str:
    """A `#/…` address in the one spelling two of them can be compared in (`canon` strips a `#`,
    which in a console address is the route's own separator, not a fragment)."""
    return unp(s).rstrip("/") or "/"


def measure_direct(page, base: str, target: str, steps: list, timeout_ms: int = 60000) -> dict:
    """Open one view at its OWN address — no console, no frame, no proxy to translate for it."""
    t = target or "/"
    url = base + ("/" + t if t.startswith("#") else t if t.startswith("/") else "/" + t)
    try:
        page.goto("about:blank")
    except Exception:                                           # noqa: BLE001
        # A previous view's door that never answered leaves the tab on `chrome-error://`, and the
        # navigation to about:blank is then interrupted by the error page finishing. That is the
        # tab settling, not this view — the `goto` below is what is measured.
        page.wait_for_timeout(300)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    except Exception as e:                                      # noqa: BLE001  a door that is shut
        # NOT a drawn screen and NOT a silent pass: the caller decides whether a shut door is an
        # exclusion said by name (the app is switched off here) or a failure — it is never a PASS.
        return {"arrived": False, "mirrored": False, "frame": "", "hash": "", "drawn": "",
                "is_drawn": False, "slow": False, "drawn_ms": 0, "shut": True,
                "why": f"{url} answered nothing: {str(e).splitlines()[0][:160]}"}
    steps_ok, steps_why = True, []
    for st in steps or []:
        try:
            if "js" in st:
                page.evaluate(st["js"])
            elif "click" in st:
                page.click(st["click"], timeout=8000)
            elif "frame_src" in st:
                continue          # the console's own step: this view is opened directly
            page.wait_for_timeout(400)
        except Exception as e:                                  # noqa: BLE001  a recipe, not a verdict
            steps_ok = False
            steps_why.append(f"{list(st)[0]} {st.get('click', '')[:40]} did not apply: "
                             f"{str(e).splitlines()[0][:120]}")
    page.wait_for_timeout(600)
    d = drawn.wait(page.evaluate, page.wait_for_timeout)
    got = urlparse(page.url)
    want = urlparse(url)
    arrived = norm(got.path) == norm(want.path)
    mirrored = (not want.fragment) or hc(got.fragment).startswith(hc(want.fragment))
    why = "" if arrived else f"asked for {url}, the page is at {page.url}"
    if arrived and want.fragment and not mirrored:
        why = f"opened, but its address holds #{got.fragment or ''} and not #{want.fragment}"
    if not d["drawn"]:
        why = (why + "; " if why else "") + drawn.said(d)
    if not steps_ok:
        why = (why + "; " if why else "") + "; ".join(steps_why)
    return {"arrived": arrived, "mirrored": mirrored, "frame": got.path,
            "hash": "#" + got.fragment if got.fragment else "",
            "drawn": drawn.said(d), "is_drawn": bool(d["drawn"]),
            "slow": bool(d["drawn"] and d["slow"]), "drawn_ms": d["ms"],
            "direct": True, "steps_ok": steps_ok, "url": url, "why": why}


WAKE_HEADER = "X-Dgo-Wake"
WAKE_WAIT_S = 180.0


def declares_on_demand(app: str) -> bool:
    """True when the app's own app.json declares `routing[].on_demand` — it runs only while it is used."""
    return any(isinstance(r, dict) and r.get("on_demand") for r in (app_json(app).get("routing") or []))


def waker_url(hosts: dict) -> str:
    """The address of the WAKER. The compiler gives app-management a priority-1 copy of every
    on_demand route's routers behind the `X-Dgo-Wake` header (reconcile.on_demand_labels): while an
    app sleeps, its own address lands there and the waker starts its containers. That is the door
    used here — never a `docker start` of this driver's own."""
    raw = hosts.get("DGO_WAKE_URL") or hosts.get("WAKE_URL") or "http://app-management:8080"
    return str(raw).rstrip("/")


def wake_on_demand(app: str, base: str, hosts: dict, wait_s: float = WAKE_WAIT_S) -> tuple[bool, str]:
    """Wake an app of ours that declares `on_demand`, then wait for its OWN address to answer.

    (ok, why). A False is this office's FAILURE, said with the real reason — never a quiet
    exclusion: a screen of ours that drops out of the measurement is the defect this run exists for.
    """
    import time
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen

    url = waker_url(hosts)
    said = ""
    try:
        with urlopen(Request(url + "/", headers={WAKE_HEADER: app, "Accept": "application/json"}),
                     timeout=30) as r:
            said = r.read(400).decode("utf-8", "replace")
    except HTTPError as e:          # the waker answers 503 «starting» — that IS the wake, not a fault
        said = e.read(400).decode("utf-8", "replace")
    except (URLError, OSError, ValueError) as e:   # noqa: BLE001  the view's reason, in its own words
        return False, (f"the waker at {url} did not answer ({type(e).__name__}: "
                       f"{str(e).splitlines()[0][:120]}) — no wake request reached it")
    deadline, last = time.monotonic() + wait_s, "no answer yet"
    while True:
        try:
            with urlopen(Request(base + "/", headers={"Accept": "text/html"}), timeout=10) as r:
                if r.status < 500:
                    return True, ""
                last = f"HTTP {r.status}"
        except HTTPError as e:
            if e.code < 500:        # 401/403/404 is an app that is AWAKE and answering
                return True, ""
            last = f"HTTP {e.code}"
        except Exception as e:      # noqa: BLE001  the asleep door: no DNS, no route, refused
            last = f"{type(e).__name__}: {str(e).splitlines()[0][:120]}"
        if time.monotonic() >= deadline:
            return False, (f"it declares on_demand, so it was woken through the waker ({url}, "
                           f"{WAKE_HEADER}: {app}; it said {said[:160] or 'nothing'}) but {base} "
                           f"never answered within {int(wait_s)}s — last: {last}")
        time.sleep(3)


def direct_verdict(m: dict) -> str:
    """The verdict for a view measured at its own address: 'pass' or 'fail' — and nothing else. A
    door that answers NOTHING is a failure of a screen of ours; exclusion belongs to `third_party`
    alone, with its number and its reason (rel-2)."""
    return "pass" if (m.get("arrived") and m.get("is_drawn")) else "fail"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://console:8000", help="the console the owner uses")
    ap.add_argument("--only", default="", help="measure only views whose app contains this")
    ap.add_argument("--json", default="ci-artifacts/route-runtime/route-runtime.json")
    ap.add_argument("--params", default="data/browser42/ui-params.json",
                    help="what resolve_params.py resolved on this office (fills {folder}, {id}, …)")
    ap.add_argument("--shot-dir", default="ci-artifacts/route-runtime")
    ap.add_argument("--hosts", default="",
                    help="NAME=URL pairs for the apps measured at their own address "
                         "(MACHINE_BASE_URL=http://machine:8080,cad=http://cad:3000). Default: each "
                         "app's own console module url, from its app.json")
    ap.add_argument("--storage-state", default="",
                    help="a signed-in browser (bbox flow-qa-session writes ci-artifacts/flow-qa/storage-state.json):"
                         " with it, --url is the office's real console address and nothing is forged")
    ap.add_argument("--no-identity", action="store_true",
                    help="send no identity at all — through traefik on an office whose SSO is off, traefik writes it")
    a = ap.parse_args()
    if a.storage_state and a.no_identity:
        ap.error("--storage-state and --no-identity are two ways of signing in; name one")
    if not a.storage_state and not a.no_identity:
        # DGO-1813: the console believes a groups header only from a sign-in hop from stage two on; until then it
        # NAMES this run in its log (console-unproved-admin). Said here so the run is not read as signed in.
        print("note: no --storage-state — the admin identity is FORGED in headers (refused by the console from "
              "DGO-1813's stage two; mint a session with `bbox flow-qa-session` and pass it, or --no-identity through "
              "traefik on an office whose SSO is off)")

    params: dict = {}
    pfile = Path(a.params)
    if pfile.exists():
        params = json.loads(pfile.read_text(encoding="utf-8"))
    else:
        print(f"note: {a.params} is not there — parameterised routes are reported as SKIPPED "
              f"(run scripts/ui-coverage/resolve_params.py first to measure them)")

    inv = inventory.build()
    if inv["errors"]:
        print("the inventory itself is not clean — a denominator that drifted is not a measurement:")
        for e in inv["errors"]:
            print("  DRIFT " + e)
        return 2

    seen: dict[tuple[str, str], dict] = {}
    rows, skipped, excluded = [], [], []
    # A VIEW IS COUNTED ONCE, AND ONLY AS WHAT IT WAS (rel-2): `drawn_keys` is what was actually
    # drawn at its address, `failed_keys` what was not, and a key can be in neither both nor in
    # MEASURED after it was excluded by name (`measured_keys` used to keep the cad row that had
    # already been moved to `excluded` — 88 measured + 1 excluded out of 88 own views).
    drawn_keys: set[tuple[str, str]] = set()
    failed_keys: set[tuple[str, str]] = set()
    fails: list[str] = []
    # THE EXEMPTIONS, READ BEFORE ANYTHING IS MEASURED (rel-2ג): a declaration that does not hold —
    # a record missing its reason or its root, or one that names no screen of this office — is a
    # failure of the RUN, said now, in the output the reader is looking at.
    runtime_excl, excl_declared_bad = load_runtime_exclusions(inv)
    for _bad in excl_declared_bad:
        print(f"  FAIL  {_bad}")
        fails.append(_bad)
    hosts: dict = {}
    for pair in (a.hosts or "").split(","):
        if "=" in pair:
            k, _, val = pair.partition("=")
            hosts[k.strip()] = val.strip()
    direct_rows, dseen, bases = [], {}, {}

    def skip_as_failure(v: dict, why: str) -> None:
        # A SKIPPED SCREEN OF OURS IS A FAILURE OF THE RUN, SAID IN ITS OWN WORDS (rel-2). The
        # acceptance is «zero routes skipped on a missing parameter», and a SKIP used to reach the
        # verdict only sideways: the view was in neither MEASURED nor EXCLUDED, so the denominator
        # caught it as «unaccounted — no measurement path took it» — which never printed the
        # parameter that was missing, the one thing a fresh clone has to be told. Counted in FAILED
        # here, with the SKIP line's own reason, so a clone whose `resolve_params.py` did not
        # produce `{folder}` fails loudly and names it.
        skipped.append((v["app"], v["id"], why))
        failed_keys.add((v["app"], v["id"]))
        fails.append(f"{v['app']} {v['id']} — skipped: {why}")
        print(f"  FAIL  {v['app']:<16} {v['id']:<28} — skipped: {why}")

    for v in inv["views"]:
        if v["tier"] != "first_party":
            # THIRD PARTY IS NOT SILENCE (rel-2). Somebody else's product is outside this office's
            # denominator — and the run now SAYS so, by name and with its number, so "outside" is a
            # statement it makes rather than a view it forgot.
            if not a.only or a.only in v["app"]:
                excluded.append((v["app"], v["id"], "third_party",
                                 "another product's own screens (its own sign-in and its own "
                                 "routes) — not this office's coverage"))
            continue
        if a.only and a.only not in v["app"]:
            continue
        if not v.get("framed"):
            # A SCREEN OF OURS WITH NO PROXY: measured at its own address below (rel-2).
            app = v["app"]
            if app not in bases:
                bases[app] = app_base(app, a.url, hosts)
            target = direct_target(v)
            base = bases[app]
            if not base:
                # NOT an exclusion: a screen of ours with nothing to open is a screen of ours that
                # was not measured, and an unmeasured screen of ours is a failure (rel-2).
                what = f"{app} {v['id']} — no address: {app}'s app.json names no routable url"
                failed_keys.add((app, v["id"]))
                fails.append(what)
                print(f"  FAIL  {app:<16} {v['id']:<28} — no address: {app}'s app.json names no "
                      f"routable url")
                continue
            direct_rows.append((app, v["id"], base, target, v.get("steps") or [],
                                (base, target, json.dumps(v.get("steps"), sort_keys=True)) in dseen))
            continue
        module, proxy = v.get("console_module"), v.get("proxy")
        route = view_route(v)
        if not module or not proxy or route is None:
            skip_as_failure(v, "the inventory names no module/proxy/route for it")
            continue
        if "{" in route or ":" in route:
            # A parameter is resolved per app, and the map also keeps LITERALS that belong to no app
            # (`hours`, taken from any-concurrency's own WINS) — those are merged into every app's subs.
            app_subs = params.get(v["app"])
            subs = {k: val for k, val in params.items() if not isinstance(val, dict)}
            if isinstance(app_subs, dict):
                subs.update(app_subs)
            route = fill(route, subs)
        if ":" in route or "{" in route:
            missing = sorted(set(re.findall(r"\{[^}]*\}|:[A-Za-z_]+", route)))
            skip_as_failure(v, f"parameterised route {route} — no value for "
                               f"{', '.join(missing)}")
            continue
        rows.append((v["app"], v["id"], module, proxy, route, route in seen,
                     v.get("kind") == "redirect"))

    slow: list[str] = []
    js_on_addr: dict = {}
    js_msgs: dict = {}
    djs: dict = {}
    rt_excluded: list[tuple[str, str, str]] = []
    rt_status: dict[tuple[str, str], str] = {}
    framed_ok = direct_ok = framed_excl = direct_excl = 0
    # ── AN APP OF OURS THAT RUNS ON DEMAND IS WOKEN BEFORE IT IS MEASURED (rel-2) ────────────────
    # `cad` is enabled with `on_demand: {idle: 2h}`: autoheal stops it once nobody uses it, its
    # address then answers nothing, and this driver used to read that as «door shut» and print it as
    # an EXCLUSION — quietly taking one of this office's own screens out of the measurement, which is
    # exactly the defect this run exists for. It is woken first, through the office's OWN waker (the
    # compiler's `X-Dgo-Wake` route on app-management, never a `docker start`), and a wake that
    # fails is that view's FAILURE, with its real reason in the output.
    wake_failed: dict[str, str] = {}
    for _app in sorted({v["app"] for v in inv["views"] if v["tier"] == "first_party"
                        and (not a.only or a.only in v["app"]) and declares_on_demand(v["app"])}):
        _base = app_base(_app, a.url, hosts)
        if not _base:
            continue                                  # said as a FAIL by its own view below
        woke_ok, wake_why = wake_on_demand(_app, _base, hosts)
        print(("  WAKE  " if woke_ok else "  WAKE-FAIL  ") + f"{_app:<16} {_base}"
              + ("" if woke_ok else f" — {wake_why}"))
        if not woke_ok:
            wake_failed[_app] = wake_why
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        signed_in = {"storage_state": a.storage_state} if a.storage_state else \
            {} if a.no_identity else {"extra_http_headers": AUTH}
        context = browser.new_context(**signed_in, viewport={"width": 1440, "height": 900}, locale="he-IL")
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        for app, vid, module, proxy, route, cached, redirect in rows:
            key = (module, route)
            if not cached:
                before = len(errors)
                seen[key] = measure(page, a.url, module, proxy, route, redirect)
                if redirect and not (seen[key]["arrived"] and seen[key]["mirrored"]):
                    # An OLD LINK, opened once more. A redirect resolves the instance over the wire
                    # before it moves, so a first load can be read mid-flight — and a person holding
                    # an old bookmark gets the screen on the reload they would try next. One retry,
                    # and if that fails too it is a FAIL: this is not a way to hide a broken address.
                    seen[key] = measure(page, a.url, module, proxy, route, redirect)
                # A page error belongs to the address it happened on: "the office has 2 JS errors"
                # is not something anyone can act on (rel-2ג). The MESSAGES are kept, not merely
                # counted, because the sentence a failure is said in is the error's own.
                js_msgs[key] = list(errors[before:])
                js_on_addr[key] = len(js_msgs[key])
            m = seen[key]
            # THE VERDICT — four things now, and none of them optional: the frame arrived at the
            # route, the shell's address carries it back, the screen was DRAWN (drawn.py: nothing in
            # sight is a skeleton/a spinner/«טוען…», and it has stopped growing), and the screen that
            # RAN did not throw. Leaving `drawn` out printed PASS for a screen that never showed
            # anything (rel-2); leaving the errors out printed PASS — and `FAILED 0`, EXIT 0 — for a
            # screen that threw 39 of them (rel-2ג). `screen_verdict` holds all of it in one place.
            verdict, said = screen_verdict(passed(m), js_msgs.get(key) or [],
                                           runtime_excl.get((app, vid)), m["why"] or "unknown")
            if verdict == "pass":
                drawn_keys.add((app, vid))
            elif verdict == "fail":
                failed_keys.add((app, vid))
                if (app, vid) in runtime_excl:
                    rt_status[(app, vid)] = "not-applied"
            else:
                rt_excluded.append((app, vid, said))
                rt_status[(app, vid)] = "applied"
            addr = f"{module}{'' if route == '/' else route}"
            print({"pass": "  PASS  ", "fail": "  FAIL  ", "excluded": "  EXCL  "}[verdict] +
                  f"{app:<16} {addr:<28} frame={m['frame'] or '-'}"
                  + (f"  [{vid}]" if vid else "")
                  + (f"  JS errors: {js_on_addr[key]}" if js_on_addr.get(key) else ""))
            if verdict == "pass":
                framed_ok += 1
                # A drawn screen that took longer than a person's patience (drawn.BUDGET_MS) is SAID,
                # on its own line and in the JSON's `slow` list — never only in a file nobody reads:
                # `computers/c/local/net` measured 4.5–6.6s twice and appeared in no output at all.
                # WHY IT IS NOT FATAL: rel-2's acceptance is «נצבע», not «נצבע מהר», and the shape
                # drawn.py draws for each tool is the tool's own to say — but see the summary line,
                # which counts them, so a slow office is visible without failing the run.
                if m["slow"]:
                    said = f"{m['drawn_ms'] / 1000:.1f}s to its information " \
                           f"(a screen may take {drawn.BUDGET_MS / 1000:g}s)"
                    slow.append(f"{app} {module}{route} ({vid or '-'}) — {said}")
                    print(f"        SLOW  {app} {addr} — {said}")
                if m["why"]:
                    # It opened. What is said here is what the screen does NOT carry out of its
                    # address (a search term an app opens the screen for but does not read back) —
                    # a gap to close, not a screen that failed to open.
                    print("        NOTE  " + m["why"])
            elif verdict == "fail":
                # The words `screen_verdict` handed back ARE the failure — the drawn reason, the
                # runtime error, or both on one line. A shot is taken of what a person would see.
                fails.append(f"{app} {module}{route} ({vid or '-'}) — {said}")
                print("        " + said)
                Path(a.shot_dir).mkdir(parents=True, exist_ok=True)
                try:
                    page.screenshot(path=str(Path(a.shot_dir) / f"fail-{app}-{route.strip('/').replace('/', '-') or 'root'}.png"))
                except Exception:  # noqa: BLE001  a photograph must never decide the verdict
                    pass
            else:
                # EXEMPT BY NAME (rel-2ג): the screen is drawn, it threw, and the declaration says
                # which fault this is and who owns it. It is printed HERE with its error and its
                # root — an exemption the reader cannot see is a hidden failure.
                framed_excl += 1
                print("        " + said)
        # ── the second path: every first_party view that has no proxy, at its OWN address ─────────
        for app, vid, base, target, steps, cached in direct_rows:
            dkey = (base, target, json.dumps(steps, sort_keys=True))
            if not cached:
                dbefore = len(errors)
                dseen[dkey] = measure_direct(page, base, target, steps)
                # THE SAME RULE AT AN APP'S OWN ADDRESS (rel-2ג): a page error is the screen's.
                djs[dkey] = list(errors[dbefore:])
            m = dseen[dkey]
            label = base + ("" if target in ("", "/") else target)
            # A DOOR THAT ANSWERS NOTHING IS A FAILURE, NOT AN EXCLUSION (rel-2). Exclusion is kept
            # for `third_party` alone — plus a runtime error exempted BY NAME: an app of ours that
            # was woken and still does not answer is a broken screen of this office, said with the
            # door's own words in its reason, and an exemption never rescues it.
            detail = m["why"] or "unknown"
            if app in wake_failed:
                # The WAKE is the reason the screen was not there, and it is said first.
                detail = f"not woken: {wake_failed[app]}; the door said {detail}"
            verdict, said = screen_verdict(direct_verdict(m) == "pass", djs.get(dkey) or [],
                                           runtime_excl.get((app, vid)), detail)
            if verdict == "pass":
                drawn_keys.add((app, vid))
            elif verdict == "fail":
                failed_keys.add((app, vid))
                if (app, vid) in runtime_excl:
                    rt_status[(app, vid)] = "not-applied"
            else:
                rt_excluded.append((app, vid, said))
                rt_status[(app, vid)] = "applied"
            print({"pass": "  PASS  ", "fail": "  FAIL  ", "excluded": "  EXCL  "}[verdict] +
                  f"{app:<16} {target:<28} {label}"
                  + (f"  [{vid}]" if vid else "")
                  + (f"  JS errors: {len(djs.get(dkey) or [])}" if djs.get(dkey) else ""))
            if verdict == "pass":
                direct_ok += 1
                if m["slow"]:
                    said = f"{m['drawn_ms'] / 1000:.1f}s to its information"
                    slow.append(f"{app} {label} ({vid or '-'}) — {said}")
                    print(f"        SLOW  {app} {label} — {said}")
                if m["why"]:
                    print("        NOTE  " + m["why"])
            elif verdict == "fail":
                fails.append(f"{app} {label} ({vid or '-'}) — {said}")
                print("        " + said)
                Path(a.shot_dir).mkdir(parents=True, exist_ok=True)
                try:
                    page.screenshot(path=str(Path(a.shot_dir) /
                                             f"fail-{app}-{target.strip('/').replace('/', '-') or 'root'}.png"))
                except Exception:  # noqa: BLE001
                    pass
            else:
                direct_excl += 1
                print("        " + said)
        browser.close()

    # ── THE DENOMINATOR, COUNTED (rel-2): declared / measured / excluded / failed ────────────────
    # What this run answers to is the inventory's OWN list of this office's screens. A first_party
    # view that is neither measured here nor excluded under its own name is an unaccounted screen,
    # and an unaccounted screen is a failure — never a silent skip.
    # MEASURED IS ONLY WHAT WAS DRAWN (rel-2). A view that failed is in `failed_keys` and nowhere
    # else; a key that was excluded by name never reaches MEASURED, so the four numbers add up to
    # what the inventory declared instead of overlapping by one.
    measured_keys = set(drawn_keys)
    # EXCLUDED IS TWO KINDS AND BOTH ARE NAMED (rel-2ג): somebody else's product (`third_party`), and
    # a runtime error this office has declared by app+view with its reason and its root. The second
    # kind only ever MOVES a screen out of FAILED when the screen was drawn — a screen that never
    # appeared is not an error to exempt, so it stays failed and is counted once, there.
    ex_keys = {(e[0], e[1]) for e in excluded} | {(app, vid) for app, vid, _ in rt_excluded}
    wanted = [v for v in inv["views"] if v["tier"] == "first_party"
              and (not a.only or a.only in v["app"])]
    unaccounted = [f"{v['app']} {v['id']}" for v in wanted
                   if (v["app"], v["id"]) not in measured_keys | failed_keys | ex_keys]
    if unaccounted:
        # Measured IS not enough: a view no path picked up at all is still an unmeasured screen.
        for u in unaccounted:
            print(f"  FAIL  {u} — no measurement path took it (not framed, not direct, not excluded)")
        fails.extend(f"{u} — unaccounted: no measurement path took it" for u in unaccounted)
        failed_keys |= {(v["app"], v["id"]) for v in wanted
                        if (v["app"], v["id"]) not in measured_keys | ex_keys}
    # DECLARED = MEASURED + EXCLUDED + FAILED, and a run whose own arithmetic does not hold is a
    # failure of the run: a denominator that does not add up is not a measurement.
    # (`--only` measures one app on purpose, so its denominator is the filtered set, not the office.)
    counted = len(measured_keys) + len(ex_keys) + len(failed_keys)
    if not a.only and counted != len(inv["views"]):
        fails.append(f"the denominator does not add up: declared {len(inv['views'])} ≠ "
                     f"measured {len(measured_keys)} + excluded {len(ex_keys)} + failed {len(failed_keys)}"
                     f" ({counted})")

    routed = sum(1 for r in rows if r[4] != "/")
    print(f"\n{len(inv['views'])} declared view(s) in the manifest — this office's own: "
          f"{len(wanted)}, of which {len(measured_keys & {(v['app'], v['id']) for v in wanted})} measured "
          f"and {len(ex_keys & {(v['app'], v['id']) for v in wanted})} excluded by name")
    print(f"{len(rows)} framed view(s) measured over {len(seen)} address(es): "
          f"{framed_ok} open and drawn at their own address, "
          f"{len(rows) - framed_ok - framed_excl} failed"
          + (f", {framed_excl} drawn but exempted for a runtime error" if framed_excl else ""))
    print(f"{len(direct_rows)} view(s) with no proxy measured at their own address "
          f"({len({r[2] for r in direct_rows})} address(es)): {direct_ok} open and drawn"
          + (f", {direct_excl} drawn but exempted for a runtime error" if direct_excl else ""))
    print(f"{routed} framed view(s) carry an inner route of their own; the rest are a module's root screen")
    if slow:
        print(f"{len(slow)} drawn but SLOW (over a person's {drawn.BUDGET_MS / 1000:g}s, not a failure):")
        for line in slow:
            print(f"  SLOW  {line}")
    if skipped:
        print(f"{len(skipped)} skipped:")
        for app, vid, why in skipped:
            print(f"  SKIP  {app} {vid} — {why}")
    if excluded:
        print(f"{len(excluded)} excluded BY NAME (not measured, and not hidden):")
        for app, vid, kind, why in excluded:
            print(f"  EXCL  {app} {vid} — {kind}: {why}")
    if rt_excluded:
        print(f"{len(rt_excluded)} screen(s) exempted BY NAME for a runtime error — the error, its "
              f"reason and its root are said, nothing is hidden:")
        for app, vid, said in rt_excluded:
            print(f"  EXCL  {app} {vid} — {said}")
    # AN EXEMPTION THAT DID NOTHING IS SAID (rel-2ג). Two ways that happens, and only one of them is
    # the screen's own problem: the screen failed for a reason of its own (the exemption cannot
    # rescue a screen that never appeared), or the error is gone. Neither is quiet — but neither is
    # a failure of the RUN, because the run's failures are named above.
    for (app, vid), rec in runtime_excl.items():
        st = rt_status.get((app, vid))
        if st is None and (app, vid) not in failed_keys:
            st = "unused"
        if st == "unused":
            print(f"  NOTE  exemption not needed in this run: {app} {vid} — the screen carried no "
                  f"runtime error ({rec['root']})")
        elif st == "not-applied":
            print(f"  NOTE  exemption NOT applied: {app} {vid} — the screen failed on its own, and "
                  f"an exemption never rescues a screen that was not drawn ({rec['root']})")
    print(f"JS errors: {len(errors)}" + ("" if not errors else f" — {errors[:3]}"))
    for (m, r), msgs in js_msgs.items():
        if msgs:
            print(f"  JS on {m}{r}: {len(msgs)}")
    for dkey, msgs in djs.items():
        if msgs:
            print(f"  JS on {dkey[0]}{dkey[1]}: {len(msgs)}")
    print(f"\nDECLARED {len(inv['views'])}  MEASURED {len(measured_keys)}  "
          f"EXCLUDED {len(ex_keys)}  FAILED {len(failed_keys)}"
          f"  (measured + excluded + failed = {counted})")
    Path(a.json).parent.mkdir(parents=True, exist_ok=True)
    Path(a.json).write_text(json.dumps(
        {"declared": len(inv["views"]), "measured": len(measured_keys),
         "excluded": len(ex_keys), "failed_count": len(failed_keys),
         "counted": counted, "adds_up": bool(a.only) or counted == len(inv["views"]),
         "views": len(rows), "addresses": len(seen), "failed": fails, "slow": slow,
         "skipped": skipped,
         "exclusions": [{"app": e[0], "id": e[1], "kind": e[2], "why": e[3]} for e in excluded],
         "runtime_error_exemptions": [{"app": app, "id": vid, "why": said} for app, vid, said in rt_excluded],
         "runtime_error_exemptions_declared": [
             {"app": k[0], "id": k[1], "why": v["why"], "root": v["root"],
              "status": rt_status.get(k, "unused")} for k, v in runtime_excl.items()],
         # THE COUNTER AND THE PER-VIEW MAP ARE TWO KEYS (rel-2). They shared the name `measured`,
         # and the map overwrote the number: the JSON said `"measured": 48` (the FRAMED screens)
         # while the same run printed `MEASURED 87` (framed + direct). The 2026-11-08 note «48 ולא
         # 87» is exactly a reader being handed the wrong number. `measured` is the denominator's
         # own figure — DECLARED = MEASURED + EXCLUDED + FAILED — and the framed screens are `framed`.
         "framed": {f"{m}{r}": {"arrived": d["arrived"], "mirrored": d["mirrored"],
                                  "drawn": d.get("is_drawn"), "slow": d.get("slow"),
                                  "drawn_ms": d.get("drawn_ms"),
                                  "frame": d["frame"], "hash": d["hash"],
                                  "said": d.get("drawn")}
                      for (m, r), d in seen.items()},
         "direct": {f"{r[0]} {r[3]}": {"base": r[2], "steps_ok": d.get("steps_ok"),
                                       "arrived": d["arrived"], "mirrored": d["mirrored"],
                                       "drawn": d.get("is_drawn"), "slow": d.get("slow"),
                                       "drawn_ms": d.get("drawn_ms"), "shut": d.get("shut", False),
                                       "said": d.get("drawn"), "why": d.get("why", "")}
                    for r in direct_rows
                    for d in [dseen.get((r[2], r[3], json.dumps(r[4], sort_keys=True)), {})]},
         # A RUNTIME ERROR IS IN THE JSON WITH ITS WORDS, NOT ONLY ITS NUMBER (rel-2ג): the count
         # was here all along and the verdict ignored it; the messages are what a fix needs.
         "js_error_total": len(errors),
         "js_errors": {f"{m}{r}": n for (m, r), n in js_on_addr.items() if n},
         "js_error_messages": {f"{m}{r}": msgs for (m, r), msgs in js_msgs.items() if msgs},
         "js_error_messages_direct": {f"{k[0]}{k[1]}": msgs for k, msgs in djs.items() if msgs}},
        ensure_ascii=False, indent=2), encoding="utf-8")
    return exit_code(fails)


def _self_test() -> int:
    """The VERDICT against a console that is only its contract (rel-2).

    The finding was not that `drawn` was unmeasured — `drawn.py` measured it and the JSON carried
    it — but that the run's answer left it out, so a screen photographed as «טוען…» at the camera's
    cap printed PASS and the process exited 0. A test of the measurement would therefore have
    passed on the broken code. This one drives `measure()` for real (chromium, drawn.py, a page that
    never stops saying «טוען…») and then asks the two questions the run is actually made of:

        is a screen that was never drawn a PASS?                    (it must not be)
        and does the run that saw it exit 0?                        (it must not)

    The mock console is a contract, not an app: `#/m/<module><route>` frames `/a/<module><route>`
    and leaves the hash alone (so module == proxy here), which is exactly what a framed view is.

        bash scripts/ui-coverage/route-runtime-qa.sh --self-test      # in the browser image
    """
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    SHELL = """<!doctype html><meta charset="utf-8"><body><script>
      const h = location.hash;                       // #/m/<module><route>
      if (h.startsWith('#/m/')) {
        const rest = h.slice(4), i = rest.indexOf('/');
        const mod = i < 0 ? rest : rest.slice(0, i), route = i < 0 ? '/' : rest.slice(i);
        document.body.innerHTML = '<iframe src="/a/' + mod + route + '"></iframe>';
      }
    </script></body>"""
    # …and the screens: one that is there, one that says «טוען…» for ever, one that says it for five
    # seconds and then shows the same information (a SLOW screen, not a broken one), and — rel-2ג —
    # one that is DRAWN and THROWS, which is the screen the card was written for.
    OK = """<!doctype html><meta charset="utf-8"><body><h1>the screen</h1><p>its information</p></body>"""
    FOREVER = """<!doctype html><meta charset="utf-8"><body><div class="sk">טוען…</div></body>"""
    SLOW = """<!doctype html><meta charset="utf-8"><body><div class="sk" id="s">טוען…</div>
      <script>setTimeout(() => { document.body.innerHTML = '<h1>the screen</h1><p>its information</p>'; }, 5000)</script>
      </body>"""
    # A drawn screen whose script raises — the real thing's own words, from the card.
    THROWS = """<!doctype html><meta charset="utf-8"><body><h1>the screen</h1><p>its information</p>
      <script>throw new Error("Minified React error #418; visit https://react.dev/errors/418")</script>
      </body>"""

    class Mock(BaseHTTPRequestHandler):
        def do_GET(self):                                            # noqa: N802  (http.server's name)
            if self.path in ("/", "/index.html"):
                body = SHELL
            elif self.path.rstrip("/").endswith("/never"):
                body = FOREVER
            elif self.path.rstrip("/").endswith("/slow"):
                body = SLOW
            elif self.path.rstrip("/").endswith("/throws"):
                body = THROWS
            else:
                body = OK
            raw = body.encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("content-length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *a):                                   # a test's own noise
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Mock)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox"])
            page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
            # THE BROWSER'S OWN ERRORS ARE COLLECTED HERE TOO (rel-2ג), with the same
            # `page.on("pageerror")` `main()` uses and the same per-address window — so the throwing
            # screen below is MEASURED, not simulated.
            errs: list[str] = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            drew = measure(page, base, "mock", "mock", "/")
            slowd = measure(page, base, "mock", "mock", "/slow")
            never = measure(page, base, "mock", "mock", "/never")
            # BEFORE the shut-door case below: that one leaves the tab on a chrome-error page, and
            # the next `goto` is then interrupted by it.
            at = len(errs)
            threw = measure(page, base, "mock", "mock", "/throws")
            threw_errs = list(errs[at:])
            direct_drew = measure_direct(page, base, "/ok", [])
            direct_never = measure_direct(page, base, "/never", [])
            direct_shut = measure_direct(page, "http://127.0.0.1:9", "/", [])
            browser.close()
    finally:
        srv.shutdown()

    def is_pass(m: dict) -> bool:
        return passed(m)

    # THE SECOND PATH (rel-2 phase 2) — a view with no proxy is opened at its own address, and it
    # is judged by the same rule. Driven here for real, over the same three mock screens.
    cases = [
        ("a screen that is drawn at its own address passes", drew, is_pass),
        ("…and so does a view with no proxy, at its own address", direct_drew, is_pass),
        ("a view with no proxy that says «טוען…» for ever is NOT a pass", direct_never,
         lambda m: not is_pass(m)),
        ("…and a door that answers nothing is not a PASS", direct_shut,
         lambda m: m.get("shut") and not is_pass(m)),
        # rel-2: a shut door of a screen of OURS is a FAILURE said by name — exclusion is kept for
        # `third_party` alone. Asserted on the verdict function the run itself uses.
        ("…and a shut door is a FAILURE of a screen of ours, never an exclusion",
         direct_shut, lambda m: direct_verdict(m) == "fail"),
        ("…while a drawn screen at its own address is a pass by the same rule",
         direct_drew, lambda m: direct_verdict(m) == "pass"),
        ("…and it is not called slow", drew, lambda m: not m["slow"]),
        ("a screen that says «טוען…» for ever is NOT a pass", never, lambda m: not is_pass(m)),
        ("…and its words name what was in the way",
         never, lambda m: "NEVER DRAWN" in m["why"] and ".sk" in m["why"]),
        ("…and the run that saw it exits non-zero, not 0",
         never, lambda m: exit_code([f"mock /never — {m['why']}"]) == 1),
        # The rule THIS FIX REPLACED — `ok = arrived and mirrored`. It is asserted to hold on the
        # same measurement, so the case cannot rot into one that would pass on the old code too.
        ("…and the rule before the fix (arrived and mirrored, drawn ignored) is why it was a PASS",
         never, lambda m: m["arrived"] and m["mirrored"] and not m["is_drawn"]),
        ("a slow screen IS drawn (it is a finding, not a failure)", slowd, is_pass),
        ("…and it is reported as SLOW, with its time",
         slowd, lambda m: m["slow"] and m["drawn_ms"] > drawn.BUDGET_MS
         and m["drawn"].startswith("SLOW") and str(drawn.BUDGET_MS // 1000) in m["drawn"]),
    ]
    # ── rel-2ג: THE SCREEN THAT IS DRAWN AND THROWS ──────────────────────────────────────────────
    # This is the card's own finding: a run carrying 39 JS errors (React #418, a hydration mismatch)
    # printed `FAILED 0` and exited 0, because `js_errors` was collected beside the verdict instead of
    # inside it. The mock screen below is drawn, and it throws, so both readings are real:
    threw_case = (threw, threw_errs, None)
    exempt_case = (threw, threw_errs,
                   {"why": "the self-test's own declaration", "root": "rel-2ג: a mock screen that throws"})
    cases += [
        ("a drawn screen that throws is a FAILURE of that screen (it used to be a PASS)",
         threw_case,
         lambda t: is_pass(t[0]) and len(t[1]) == 1
         and screen_verdict(True, t[1], None)[0] == "fail"),
        ("…and the run that saw it exits 1, not 0",
         threw_case,
         lambda t: exit_code([f"mock /throws — {screen_verdict(True, t[1], None)[1]}"]) == 1),
        ("…and it is said with the error's own words, not only its number",
         threw_case, lambda t: "#418" in screen_verdict(True, t[1], None)[1]),
        ("…and the same screen, exempted BY NAME, comes back as an exemption",
         exempt_case, lambda t: screen_verdict(True, t[1], t[2])[0] == "excluded"),
        ("…and the exemption PRINTS its reason and its root",
         exempt_case,
         lambda t: "the self-test's own declaration" in screen_verdict(True, t[1], t[2])[1]
         and "root: rel-2ג" in screen_verdict(True, t[1], t[2])[1]),
        ("…and an exemption does not rescue a screen that was never drawn",
         (never, ["Minified React error #418"], exempt_case[2]),
         lambda t: screen_verdict(False, t[1], t[2])[0] == "fail"),
        ("…and a drawn screen with no error is a pass, exemption or not",
         (drew, [], exempt_case[2]), lambda t: screen_verdict(True, [], t[2])[0] == "pass"),
    ]
    # THE EXEMPTION FILE IS A DECLARATION, AND ITS SHAPE IS PART OF THE VERDICT (rel-2ג): a record
    # that names no declared screen is a FAILURE — an orphan exemption is a hole, not a pass — and so
    # is a record that says nothing about WHY or WHERE. A good record loads with both.
    import tempfile
    inv_mock = {"views": [{"app": "sites", "id": "sites/new"},
                          {"app": "console", "id": "console/display"}]}
    with tempfile.TemporaryDirectory() as td:
        def decl(name: str, text: str):
            pth = Path(td) / name
            pth.write_text(text, encoding="utf-8")
            return load_runtime_exclusions(inv_mock, pth)

        good, good_bad = decl("good.yaml", "- app: sites\n  view: sites/new\n"
                                           "  why: the screen's own hydration error #418\n"
                                           '  root: "rel-2ד: hydration in apps/sites/static/app.js:120"\n')
        orphan, orphan_bad = decl("orphan.yaml", "- app: sites\n  view: sites/does-not-exist\n"
                                                 "  why: an error nobody has\n  root: nowhere\n")
        mute, mute_bad = decl("mute.yaml", "- app: sites\n  view: sites/new\n  why: ''\n")
        elsewhere_text = "- app: project-pln\n  view: main\n  why: another office's screen\n  root: its own build\n"
        (Path(td) / "elsewhere.yaml").write_text(elsewhere_text, encoding="utf-8")
        elsewhere = load_runtime_exclusions({**inv_mock, "not_here": {"project-pln": 1}}, Path(td) / "elsewhere.yaml")
        unknown = decl("unknown.yaml", elsewhere_text)            # the same record, but nothing says it is not here
        cases += [
            ("…and an exemption of an app the inventory says does not run here is another office's, not an orphan",
             elsewhere, lambda t: t == ({}, [])),
            ("…but one whose app nobody knows (a typo, another naming) is still an orphan",
             unknown, lambda t: len(t[1]) == 1 and "orphan" in t[1][0]),
            ("an exemption that names a real screen loads, with its why and its root",
             (good, good_bad),
             lambda t: len(t[0]) == 1 and not t[1]
             and "rel-2ד" in t[0][("sites", "sites/new")]["root"]),
            ("…and an exemption that names NO declared screen is a failure of the run",
             (orphan, orphan_bad), lambda t: len(t[1]) == 1 and "orphan" in t[1][0]),
            ("…and an exemption with no reason and no root is a failure too",
             (mute, mute_bad), lambda t: len(t[1]) == 1 and "hiding place" in t[1][0]),
            ("…and no declaration file at all is no exemption and no failure",
             load_runtime_exclusions(inv_mock, Path(td) / "absent.yaml"),
             lambda t: t == ({}, [])),
        ]
    bad = 0
    for name, got, holds in cases:
        good_h = bool(holds(got))
        bad += not good_h
        print(("  PASS  " if good_h else "  FAIL  ") + name
              + ("" if good_h else (f" — arrived={got['arrived']} mirrored={got['mirrored']} "
                                    f"drawn={got['drawn']!r} why={got['why']!r}"
                                    if isinstance(got, dict) else f" — got {got!r}")))
    print(f"route-runtime-qa: {len(cases) - bad}/{len(cases)} hold"
          + ("" if not bad else " — a screen that was never drawn, or one that throws, does NOT "
                                "change the run's answer"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(_self_test() if "--self-test" in sys.argv[1:] else main())
