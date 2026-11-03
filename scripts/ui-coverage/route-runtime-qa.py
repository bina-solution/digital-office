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

    docker run --rm --network traefik-network -v "$PWD:/w" -w /w \
      --entrypoint python3 deployment-hacohen-sites-render:latest \
      scripts/ui-coverage/route-runtime-qa.py --url http://console:8000

Exit code is non-zero when any declared view fails to open at its address. A route carrying a
parameter (`:type`, `{name}`) is reported as SKIPPED with its name: filling it is
`resolve_params.py`'s job, and a guessed value would measure the guess.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import drawn  # noqa: E402  (the office's one "is this screen drawn" rule)
import inventory  # noqa: E402  (the denominator: what this office has)

from playwright.sync_api import sync_playwright  # noqa: E402

AUTH = {"X-authentik-username": "admin", "X-authentik-email": "admin@office.local",
        "X-authentik-name": "Admin", "X-authentik-groups": "authentik Admins"}

FRAME_WAIT_MS, FRAME_POLL_MS = 20000, 250


def norm(path: str) -> str:
    """A path without its trailing slash — `/a/drive/` and `/a/drive` are one address."""
    p = path.split("?")[0].split("#")[0]
    return p.rstrip("/") or "/"


def canon(s: str) -> str:
    """A route in the one form two of them can be compared in: leading slash, no trailing slash, no
    fragment, query kept. `norm` is the same idea for a path alone — this one is safe for a console
    address, whose own `#` is not a fragment separator to strip."""
    p, _, q = s.split("#")[0].partition("?")
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
    fr = urlparse(frame.url)
    got_path, got_hash = norm(fr.path + ("?" + fr.query if fr.query else "")), \
        page.evaluate("() => location.hash")
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
    return {"arrived": arrived, "mirrored": mirrored, "frame": got_path, "hash": got_hash,
            "drawn": drawn.said(d), "why": why}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://console:8000", help="the console the owner uses")
    ap.add_argument("--only", default="", help="measure only views whose app contains this")
    ap.add_argument("--json", default="ci-artifacts/route-runtime/route-runtime.json")
    ap.add_argument("--params", default="data/browser42/ui-params.json",
                    help="what resolve_params.py resolved on this office (fills {folder}, {id}, …)")
    ap.add_argument("--shot-dir", default="ci-artifacts/route-runtime")
    a = ap.parse_args()

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
    rows, skipped = [], []
    for v in inv["views"]:
        if not v.get("framed") or v["tier"] != "first_party":
            continue
        if a.only and a.only not in v["app"]:
            continue
        module, proxy = v.get("console_module"), v.get("proxy")
        route = view_route(v)
        if not module or not proxy or route is None:
            skipped.append((v["app"], v["id"], "the inventory names no module/proxy/route for it"))
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
            skipped.append((v["app"], v["id"], f"parameterised route {route} — no value for "
                                               f"{', '.join(missing)}"))
            continue
        rows.append((v["app"], v["id"], module, proxy, route, route in seen,
                     v.get("kind") == "redirect"))

    fails: list[str] = []
    js_on_addr: dict = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        context = browser.new_context(extra_http_headers=AUTH,
                                      viewport={"width": 1440, "height": 900}, locale="he-IL")
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
                # is not something anyone can act on.
                js_on_addr[key] = len(errors) - before
            m = seen[key]
            ok = m["arrived"] and m["mirrored"]
            print(("  PASS  " if ok else "  FAIL  ") +
                  f"{app:<16} {module}{'' if route == '/' else route:<28} frame={m['frame'] or '-'}"
                  + (f"  [{vid}]" if vid else "")
                  + (f"  JS errors: {js_on_addr[key]}" if js_on_addr.get(key) else ""))
            if not ok:
                detail = m["why"] or "unknown"
                fails.append(f"{app} {module}{route} ({vid or '-'}) — {detail}")
                print("        " + detail)
                Path(a.shot_dir).mkdir(parents=True, exist_ok=True)
                try:
                    page.screenshot(path=str(Path(a.shot_dir) / f"fail-{app}-{route.strip('/').replace('/', '-') or 'root'}.png"))
                except Exception:  # noqa: BLE001  a photograph must never decide the verdict
                    pass
            elif m["why"]:
                # It opened. What is said here is what the screen does NOT carry out of its address
                # (a search term an app opens the screen for but does not read back) — a gap to
                # close, not a screen that failed to open.
                print("        NOTE  " + m["why"])
        browser.close()

    routed = sum(1 for r in rows if r[4] != "/")
    print(f"\n{len(rows)} declared view(s) measured over {len(seen)} address(es): "
          f"{len(rows) - len(fails)} open at their own address, {len(fails)} do not")
    print(f"{routed} carry an inner route of their own; the rest are a module's root screen")
    if skipped:
        print(f"{len(skipped)} skipped:")
        for app, vid, why in skipped:
            print(f"  SKIP  {app} {vid} — {why}")
    print(f"JS errors: {len(errors)}" + ("" if not errors else f" — {errors[:3]}"))
    if js_on_addr:
        for (m, r), n in js_on_addr.items():
            if n:
                print(f"  JS on {m}{r}: {n}")
    Path(a.json).parent.mkdir(parents=True, exist_ok=True)
    Path(a.json).write_text(json.dumps(
        {"views": len(rows), "addresses": len(seen), "failed": fails, "skipped": skipped,
         "measured": {f"{m}{r}": {"arrived": d["arrived"], "mirrored": d["mirrored"],
                                  "frame": d["frame"], "hash": d["hash"], "drawn": d.get("drawn")}
                      for (m, r), d in seen.items()},
         "js_errors": {f"{m}{r}": n for (m, r), n in js_on_addr.items() if n}}, ensure_ascii=False, indent=2), encoding="utf-8")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
