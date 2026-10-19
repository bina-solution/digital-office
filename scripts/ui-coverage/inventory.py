#!/usr/bin/env python3
"""
ui-coverage/inventory.py — build the DENOMINATOR for UI coverage, from source.

Why this exists: you cannot prove "100% UI coverage" against a hand-written list of
screens, because the list only ever contains what someone remembered. The denominator
has to be DERIVED from the code, and the derivation itself has to be guarded — otherwise
coverage silently rises to 100% the moment an extractor stops matching.

So every extractor below does two things:
  1. pulls the view set out of the real source file, and
  2. asserts the SHAPE it depends on still exists (DriftError if not).

An extractor that finds nothing raises. It never returns an empty list quietly.

Output: ui-inventory.json  — one record per view:
    {app, id, title, kind, url|steps, tier, source, group}

Run:  python3 scripts/ui-coverage/inventory.py [--out ui-inventory.json] [--print]
"""
# `from __future__` MUST be the first statement after the docstring — Python rejects the file
# otherwise. The UTF-8 reconfigure guard below was inserted above it and broke every run.
from __future__ import annotations

# Hebrew output: python defaults stdout to the ANSI codepage on Windows (cp1255) and dies
# with UnicodeEncodeError. Linux/macOS are already UTF-8 — a no-op there.
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"): _sys.stdout.reconfigure(encoding="utf-8")

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = Path(__file__).resolve().parent / "manifest.yaml"


class DriftError(RuntimeError):
    """The source shape an extractor depends on changed — fail loudly, never under-count."""


def _read(rel: str) -> str:
    p = ROOT / rel
    if not p.exists():
        raise DriftError(f"missing source file: {rel}")
    return p.read_text(encoding="utf-8", errors="replace")


def _view(app, vid, title, *, kind, url=None, steps=None, tier="first_party",
          source="", group=None) -> dict:
    v = {"app": app, "id": vid, "title": title, "kind": kind,
         "tier": tier, "source": source}
    if url is not None:
        v["url"] = url
    if steps is not None:
        v["steps"] = steps
    if group:
        v["group"] = group
    return v


# ── extractors ───────────────────────────────────────────────────────────────

def _modules(man) -> list[dict]:
    """The console's module list — the SAME merge console/app.py performs at runtime.

    The app tiles are compiled from each app's routing[].module into
    .generated/registry/console.modules.yaml; platform-base/console/modules.yaml keeps only the
    shell's own built-in views (dashboard / apps / install). Reading just the committed file here
    saw 3 modules and reported drift — the inventory was measuring a file that is no longer the
    whole answer. Merge both, ordered by `order`, exactly like the console does."""
    rel = "platform-base/console/modules.yaml"
    own = yaml.safe_load(_read(rel)) or []
    gen_rel = ".generated/registry/console.modules.yaml"
    try:
        tiles = yaml.safe_load(_read(gen_rel)) or []
    except (OSError, FileNotFoundError):
        raise DriftError(f"{gen_rel} missing — run: python3 platform/manager/reconcile.py render")
    mods = sorted(list(tiles) + list(own), key=lambda m: m.get("order", 999))
    if not isinstance(mods, list) or len(mods) < 10:
        raise DriftError(f"{rel} + {gen_rel}: expected a list of >=10 modules, got {type(mods)} "
                         f"len={len(mods) if isinstance(mods, list) else 'n/a'}")
    for m in mods:
        if not isinstance(m, dict) or "id" not in m:
            raise DriftError(f"{rel}: module entry without id: {m!r}")
    return mods


_OFFICE: dict | None = None


def _office() -> dict:
    """What THIS office runs: {"owner": {routing host -> app id}, "on": {app ids} | None}.

    The map is of an office, and offices do not run the same apps: on hp-laptop mail is off, so
    `console_embed[mailview]` named a module the compiler had not emitted, the inventory called it
    drift, and `bbox ui-map` could not build its denominator at all (2026-10-07). The remedy had
    always been to delete the app's rows from manifest.yaml — hello-bina, then my-docs — which
    made a tracked file the description of ONE office. The compiler already knows which apps are
    on; an app that is off here is left out of this office's map and SAID, never called drift.
    `on` is None when the compiler cannot say, and then every app is taken as running."""
    global _OFFICE
    if _OFFICE is None:
        import subprocess
        owner, tiles = {}, []
        for mf in sorted(ROOT.glob("apps/*/app.json")) + sorted(ROOT.glob("platform-base/*/app.json")):
            try:
                app = json.loads(mf.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for r in app.get("routing") or []:
                owner.setdefault(r.get("host"), app.get("id"))
                mod = r.get("module") or {}
                if mod.get("embed") and mod.get("alias"):      # a tile the shell frames at /a/<alias>/
                    tiles.append({"app": app.get("id"), "host": r.get("host"),
                                  "module": mod.get("id", app.get("id")), "proxy": mod["alias"]})
        try:
            r = subprocess.run([sys.executable, str(ROOT / "platform/manager/reconcile.py"), "enabled-apps"],
                               capture_output=True, text=True, cwd=str(ROOT), timeout=120)
            on = {ln.split()[1] for ln in r.stdout.splitlines() if len(ln.split()) == 2}
        except (OSError, subprocess.TimeoutExpired):
            on = set()
        _OFFICE = {"owner": owner, "on": on or None, "tiles": tiles}
    return _OFFICE


def console_embed(man) -> dict:
    """view app -> {module, proxy}: every tile a manifest declares as framed by the shell, under
    the name of the `hosts` row that carries its routing host.

    DERIVED from the manifests. It was a table in manifest.yaml that somebody had to remember:
    browser42, Plane, data-management, three apps at once on 2026-09-29 and archify each sat in the
    rail without a row, and each time the map either refused to build or measured a smaller product
    than the one in front of the owner. The module id and the alias are the manifest's own facts;
    what is still declared by hand is the `hosts` row (auth and tier are judgments), and a tile
    without one is said here."""
    by_host = {row["local"].split(".")[0]: key for key, row in (man.get("hosts") or {}).items()}
    out, orphans = {}, []
    for t in _office()["tiles"]:
        key = by_host.get(t["host"])
        if key is None:
            orphans.append(f"{t['app']} (host `{t['host']}`)")
        else:
            out[key] = {"module": t["module"], "proxy": t["proxy"]}
    if orphans:
        raise DriftError(f"a tile the shell frames has no `hosts` row in manifest.yaml: {', '.join(orphans)} "
                         f"— add the row (env, local, auth, tier); the embed itself is read from app.json")
    return out


def runs_here(man, view_app: str) -> bool:
    """Does this office run the app a view belongs to? The app is found by the routing host the
    manifest's `hosts` row names; a row that names no declared host is taken as running."""
    office = _office()
    label = ((man.get("hosts") or {}).get(view_app) or {}).get("local", "").split(".")[0]
    aid = office["owner"].get(label)
    return True if aid is None or office["on"] is None else aid in office["on"]


def embed_index(man) -> dict:
    """app -> {module, proxy, group}: the tiles the manifests declare (console_embed), checked
    against what the compiler emitted for THIS office (modules.yaml).

    Both directions: a framed tile the compiler emitted that no manifest explains would be
    captured on its standalone host (a screen the product does not have), and a manifest's tile
    the compiler did not emit means the two disagree. Asked only of the apps this office runs — an
    app that is off here has no module to point at — and a tile a linked office gives (`remote`)
    is that office's screen, mapped there.
    """
    mods = _modules(man)
    declared = {app: spec for app, spec in console_embed(man).items() if runs_here(man, app)}
    by_module = {m["id"]: m for m in mods if m.get("embed") and not (m.get("remote") or m.get("office"))}
    idx = {}
    for app, spec in declared.items():
        mid = spec["module"]
        if mid not in by_module:
            raise DriftError(f"{app}: its manifest declares the framed tile {mid!r}, the office runs "
                             f"it, and the compiled registry has no such embedded module — render "
                             f"again (python3 platform/manager/reconcile.py render)")
        embed_path = by_module[mid].get("embed", "")
        if f"/a/{spec['proxy']}/" not in embed_path:
            raise DriftError(f"{app}: its manifest's alias {spec['proxy']!r} does not match the "
                             f"compiled embed {embed_path!r}")
        idx[app] = {**spec, "group": by_module[mid].get("group"),
                    "name": by_module[mid].get("name", mid)}
    covered = {s["module"] for s in declared.values()}
    missing = [mid for mid in by_module if mid not in covered]
    if missing:
        raise DriftError(f"the compiled registry frames modules no manifest tile explains: "
                         f"{missing} — they would be captured on their standalone host, "
                         f"which is not how users see them")
    return idx


def x_console(man) -> list[dict]:
    """console: only its OWN screens.

    Embedded modules are NOT emitted here — each is contributed by the app that lives in
    it (see rewrite_for_console), so the tile shows the real app inside the shell instead
    of an empty frame, and nothing is counted twice.
    """
    rel = "platform-base/console/modules.yaml"
    src = _read("platform-base/console/static/app.js")
    # The hash grammar `#/m/<id>[/inner][?query]` moved from an inline `seg === "m"` comparison
    # to the ONE parser the shell keeps for it. Anchoring on the old comparison made the whole
    # inventory refuse to build (2026-09-27) after the router was rewritten — the anchor is the
    # GRAMMAR, so anchor on the parser that owns it, not on how one revision spelled it.
    if "parseModuleHash" not in src or r"#\/m\/" not in src:
        raise DriftError("console/static/app.js: the `#/m/<id>` grammar (parseModuleHash + its "
                         "regex) is gone — the #/m/<id> assumption may no longer hold")
    out = []
    for m in _modules(man):
        if m.get("embed"):
            continue
        mid = m["id"]
        # One address shape for every view: the `/#/` case was the "לוח בקרה" home screen, and the
        # bare hash now just redirects to the first tile in the rail.
        url = f"/#/m/{mid}"
        out.append(_view("console", mid, m.get("name", mid), kind="hash", url=url,
                         source=f"{rel}:{mid}", group=m.get("group")))
    # The shell owns at least one screen (its display settings). Zero means modules.yaml was gutted or
    # stopped parsing — and since every other tile comes from the generated registry, the inventory
    # would still look plausible while the console's own views left the denominator.
    # Asked of the shell's OWN file, not of what came out above: a generated tile that is not framed
    # (an app shown from its own host) is a view of this list too, and one such tile was enough to
    # hide a gutted file. `if not out` passed it — "SILENTLY RETURNED 1 views" — wherever a registry
    # held one: in a fresh render of the committed state (23 tiles, 2026-10-09), though not on the
    # office this was written on, where every tile is framed. The guard's own test said so the day a
    # gate first ran it.
    if not [m for m in (yaml.safe_load(_read(rel)) or []) if isinstance(m, dict) and m.get("id")]:
        raise DriftError(f"{rel}: no console-owned views — the shell always owns its display settings")
    return out


def rewrite_for_console(views: list[dict], man: dict) -> list[dict]:
    """Re-point every embedded app's views at the console shell.

    A view that was `/trash` on drive.localhost becomes: open console #/m/drive, then set
    the iframe to /a/drive/trash. The screenshot then shows the shell AND the app —
    which is the screen the product actually has.
    """
    idx = embed_index(man)
    for v in views:
        e = idx.get(v["app"])
        if not e or v["tier"] != "first_party":
            continue
        proxy, path = e["proxy"], v.get("url") or "/"
        v["framed"] = True
        v["group"] = v.get("group") or e["group"]
        v["console_module"] = e["module"]
        v["proxy"] = proxy
        inner_steps = []
        if path not in ("/", ""):
            # Navigate the frame to the view's own route FIRST, then run its recipe. A
            # recipe-bearing view with a real route (e.g. the extraction detail panes, whose
            # tabs only exist on /extraction/:type/:name) previously lost this nav — the tabs
            # then ran against the module's root screen and found nothing. The leading nav is
            # a frame_src so capture.apply_subs still substitutes :type/:name into it.
            inner_steps.append(
                {"frame_src": f"/a/{proxy}{path if path.startswith('/') else '/' + path}"})
        if v.get("steps"):
            # DOM recipes (tabs) now run inside the frame
            inner_steps += [{("frame_click" if "click" in s else
                             "frame_key" if "key" in s else
                             "frame_js" if "js" in s else "frame_fill"):
                             (s.get("click") or s.get("key") or s.get("js") or s.get("fill"))}
                            for s in v["steps"]]
        v["steps"] = inner_steps
        v["url"] = f"/#/m/{e['module']}"
        v["host_override"] = "console"
    return views


def x_my_docs(_m) -> list[dict]:
    """my-docs: VIEWS object in app.js, cross-checked against the nav in index.html.

    The cross-check is the anti-drift guard: two independent declarations must agree,
    so a view added to one but not the other is a hard failure rather than a silent gap.
    """
    js = _read("apps/my-docs/static/app.js")
    html = _read("apps/my-docs/static/index.html")
    m = re.search(r"const\s+VIEWS\s*=\s*\{(.+?)\}", js, re.S)
    if not m:
        raise DriftError("my-docs/static/app.js: `const VIEWS = {...}` not found")
    js_views = dict(re.findall(r"(\w+)\s*:\s*'([^']*)'", m.group(1)))
    html_views = set(re.findall(r'data-view="([^"]+)"', html))
    if not js_views:
        raise DriftError("my-docs: VIEWS parsed empty")
    if set(js_views) != html_views:
        raise DriftError(
            f"my-docs: VIEWS/nav disagree — app.js={sorted(js_views)} "
            f"index.html={sorted(html_views)}; one was edited without the other")
    # State-driver functions must exist — we drive the app's OWN view switch / modal openers so
    # a captured state doesn't depend on the first-run onboarding overlay being dismissed by luck.
    for fn in ("function show(", "function openEditor(", "function editEntity("):
        if fn not in js:
            raise DriftError(f"my-docs: state driver {fn!r} gone — app changed")
    # Every screenshot dismisses the first-run overlay first (seed_demo onboards, but be robust),
    # then drives the app's own function — the same render branch a real click runs.
    D = ("for(const i of['onboard','overlay']){const e=document.getElementById(i);"
         "if(e)e.classList.add('hidden');}")
    out = [
        _view("my-docs", v, title, kind="dom-state",
              steps=[{"js": D + f"show('{v}')"}],
              source="apps/my-docs/static/app.js:VIEWS")
        for v, title in js_views.items()
    ]
    # Create/edit MODALS — popups reachable only by opening an overlay. Each is its own render
    # branch; capturing it covers that branch, else it surfaces as an un-photographed state in
    # the JS-coverage report (that report is exactly the "no popup left behind" proof).
    out += [
        _view("my-docs", "new-doc-modal", "מסמך חדש · עורך", kind="dom-state",
              steps=[{"js": D + "openEditor()"}], source="apps/my-docs/static/app.js:openEditor"),
        _view("my-docs", "customer-modal", "לקוח · עורך", kind="dom-state",
              steps=[{"js": D + "editEntity('customers')"}], source="apps/my-docs/static/app.js:editEntity"),
        _view("my-docs", "item-modal", "פריט · עורך", kind="dom-state",
              steps=[{"js": D + "editEntity('items')"}], source="apps/my-docs/static/app.js:editEntity"),
    ]
    return out


def x_connections(_m) -> list[dict]:
    """connections: the PILLARS array drives the tab bar."""
    html = _read("platform-base/connections/ui.html")
    block = re.search(r"const\s+PILLARS\s*=\s*\[(.+?)\n\];", html, re.S)
    if not block:
        raise DriftError("connections/ui.html: `const PILLARS=[...]` not found")
    ids = re.findall(r"\{id:'([^']+)'", block.group(1))
    hes = re.findall(r"he:'([^']*)'", block.group(1))
    if not ids:
        raise DriftError("connections: PILLARS parsed with no ids")
    if "function setTab(" not in html:
        raise DriftError("connections/ui.html: setTab() gone — tab model changed")
    out = []
    for i, pid in enumerate(ids):
        out.append(_view("connections", pid, hes[i] if i < len(hes) else pid,
                         kind="dom-state", steps=[{"click": f"button[onclick=\"setTab('{pid}')\"]"}],
                         source="platform-base/connections/ui.html:PILLARS"))
    return out


def x_incoming(_m) -> list[dict]:
    """incoming-documents (INDOX): react-router <Route path=...> table.

    Two layers of declaration, because routes alone under-count the product:
      1. every <Route path=…> — the top-level screens;
      2. the extraction DETAIL panes (bounding-box overlay / OCR char overlay / original
         document) which are TAB state inside one route (ExtractionDocPage), not routes of
         their own. They were the richest screens in the app and, being sub-route state,
         never appeared in the denominator at all — capture skipped the :type/:name route
         AND nothing declared the panes. Declaring them here makes the metric honest.
    """
    rel = "apps/indox/app/webapp/src/App.tsx"
    src = _read(rel)
    # tolerate `element={<Comp` and `element={\n  <Comp` (the multiline /repos/new entry
    # was silently dropped by a no-gap regex, under-counting the route list by one).
    routes = re.findall(r'<Route\s+path="([^"]+)"\s+element=\{\s*<(\w+)', src)
    if len(routes) < 8:
        raise DriftError(f"{rel}: expected >=8 <Route path=...> entries, found {len(routes)}")
    out = []
    for path, comp in routes:
        # parameterised routes need a real id at capture time; the driver substitutes
        # from seeded demo data (see resolve_params.py / capture.py PARAM_APIS).
        out.append(_view("incoming-documents", path.strip("/").replace("/", "-") or "root",
                         comp, kind="route", url=path, source=f"{rel}:{path}"))

    # ── extraction detail panes (tab state inside /extraction/:type/:name) ──────────
    # 2026-08-06: the pane state + subnav tabs were lifted OUT of ExtractionDocPage.tsx into a
    # shared component (also used by DocumentDetailPage), so the drift guard reads the component
    # that actually owns the model rather than either page.
    # 2026-09-02: that component is now DocumentStage.tsx — DocumentViewer was replaced when the
    # document view was rebuilt (unreachable page top, viewport-derived height). The MODEL it
    # guards is unchanged: the same three sources under the same three Hebrew labels, so only the
    # path moves. The tab row's class did change (`.subnav` → `.stage-sources`), which matters to
    # anything selecting on it — see test_indox_regressions.py check K.
    doc_rel = "apps/indox/app/webapp/src/components/DocumentStage.tsx"
    doc_src = _read(doc_rel)
    # guard: the pane model + the three tab labels must still exist, else these declarations
    # would silently photograph the wrong thing.
    if "'draw' | 'tokens' | 'doc'" not in doc_src:
        raise DriftError(f"{doc_rel}: pane state ('draw'|'tokens'|'doc') gone — extraction "
                         "detail tabs changed; sub-view declarations need updating")
    for label in ("חילוץ מסומן", "זיהוי תווים", "מסמך מקורי"):
        if label not in doc_src:
            raise DriftError(f"{doc_rel}: extraction tab {label!r} missing — panes changed")
    # each pane is a click on the Nth `.subnav .stab` button (0=draw,1=tokens,2=doc); the
    # detail route is reached first (rewrite_for_console prepends the frame nav), then the
    # pane tab is switched inside the frame. :type/:name resolve host-side (resolve_params).
    panes = [("extraction-draw",   "חילוץ מסמכים · סימון חילוץ", 0),
             ("extraction-tokens", "חילוץ מסמכים · זיהוי תווים (OCR)", 1),
             ("extraction-doc",    "חילוץ מסמכים · מסמך מקורי", 2)]
    for vid, title, idx in panes:
        out.append(_view(
            "incoming-documents", vid, title, kind="dom-state",
            url="/extraction/:type/:name",
            steps=[{"js": f"var b=document.querySelectorAll('.subnav .stab')[{idx}];"
                          " if(b)b.click();"}],
            source=f"{doc_rel}:pane"))
    return out


def x_mailview(_m) -> list[dict]:
    """mailview: pushState paths parsed by applyUrl()."""
    rel = "apps/mail/mailview/static/app.js"
    src = _read(rel)
    for anchor in ("/^\\/message\\/", "/^\\/label\\/", "applyUrl"):
        if anchor.replace("\\\\", "\\") not in src and anchor not in src:
            raise DriftError(f"{rel}: URL-shape anchor {anchor!r} missing — routes changed")
    return [
        _view("mailview", "inbox", "מייל — תיבה נכנסת", kind="route", url="/", source=rel),
        _view("mailview", "label", "מייל — תווית", kind="route", url="/label/{label}", source=rel),
        _view("mailview", "message", "מייל — קריאת הודעה", kind="route", url="/message/{id}", source=rel),
    ]


def x_localdrive(_m) -> list[dict]:
    """drive: pushState paths parsed by parseUrl()."""
    rel = "apps/drive/static/app.js"
    src = _read(rel)
    if "function parseUrl()" not in src:
        raise DriftError(f"{rel}: parseUrl() missing — routes changed")
    return [
        _view("drive", "root", "דרייב — שורש", kind="route", url="/", source=rel),
        _view("drive", "folder", "דרייב — תיקייה", kind="route", url="/folder/{folder}", source=rel),
        _view("drive", "file", "דרייב — תצוגת קובץ", kind="route",
              url="/folder/{folder}/file/{file}", source=rel),
    ]


def x_chat(_m) -> list[dict]:
    """chat: the login page, the chat app, and the three modals the app opens.

    This used to describe a SECOND page — `/admin`, an EJS dashboard with #connect / #users /
    #settings / #actions sidebar sections. That page is gone: every one of those sections was
    folded into the chat app itself, and `ui/index.ejs` was deleted with it. The four dom-states
    below are the same four capabilities, reached the way the app actually reaches them.
    """
    api = _read("apps/chat/src/api/api.js")
    ejs = _read("apps/chat/src/api/ui/chat.ejs")
    if "renderLogin" not in api or "renderChat" not in api:
        raise DriftError("apps/chat/src/api/api.js: renderLogin/renderChat gone — page set changed")

    # The modal openers ARE the inventory: if one is renamed, the matching view would screenshot the
    # landing state instead and silently claim coverage it does not have.
    openers = [("connect", "openConnect", "חיבורים"),
               ("bots", "openBots", "בוטים וחיבורים"),
               ("tools", "openTools", "כלים")]
    missing = [fn for _, fn, _ in openers if f"function {fn}(" not in ejs]
    if missing:
        raise DriftError("apps/chat/src/api/ui/chat.ejs: modal opener(s) gone: "
                         + ", ".join(missing) + " — the dashboard sections moved again")

    out = [_view("chat", "login", "צ׳אט — התחברות", kind="route", url="/login",
                 source="apps/chat/src/api/api.js"),
           _view("chat", "chat", "צ׳אט — שיחות", kind="route", url="/",
                 source="apps/chat/src/api/api.js")]
    for name, fn, title in openers:
        # A modal, not a navigation: setting iframe.src to ".../#connect" does nothing once the
        # document has loaded, which is how the old section views all screenshotted as the landing
        # page. Call the app's own opener so the state is the one a user would actually see.
        out.append(_view("chat", name, f"צ׳אט — {title}", kind="dom-state", url="/",
                         steps=[{"js": f"{fn}()"}],
                         source="apps/chat/src/api/ui/chat.ejs"))
    return out


# apps whose UI is genuinely one screen — guarded so new tabs can't hide here
_ROUTER_SMELLS = ("addEventListener(\"popstate\"", "addEventListener('popstate'",
                  "location.hash", "history.pushState", "data-view=", "setTab(")


def x_single_view(man) -> list[dict]:
    out = []
    probes = {
        "machine": "platform-base/machine/static/index.html",
        "notifications": "platform-base/notifications/static/index.html",
        "any-concurrency": "apps/any-concurrency/static/index.html",
        "feature-validation": "development/feature-validation/api/dashboard.html",
        # [2026-09-27] three apps that were enabled, embedded and in the rail while this map
        # reported "100% of first-party views" without ever photographing them. Each is
        # genuinely one screen today — proven by running _ROUTER_SMELLS over its own source,
        # not by reading its README — so declaring it here is honest, and the probe below is
        # what keeps it honest the day someone adds a tab.
        "computers": "apps/computers/static/index.html",
        "git": "apps/git/static/index.html",
        "data-management": "platform-base/data-management/static/index.html",
        "dgo-extend": "apps/dgo-extend/static/index.html",
    }
    for app, spec in man["single_view"].items():
        rel = probes.get(app)
        if rel and (ROOT / rel).exists():
            src = _read(rel)
            hit = [s for s in _ROUTER_SMELLS if s in src]
            if hit:
                raise DriftError(
                    f"{app} is declared single_view but {rel} now contains {hit} — "
                    f"it grew navigation. Write an extractor instead of hiding views here.")
        out.append(_view(app, "main", spec["title"], kind="route", url=spec["path"],
                         source=rel or "manifest.yaml:single_view"))
    return out


def _tab_rows(src: str, rel: str, names: tuple = ("tabs", "TABS")) -> list[tuple]:
    """The app's OWN tab table, parsed — never a list written here by hand.

    Two shapes are in use and both are the app's view model:
      sites/domains   const tabs  = [['overview', 'סקירה'], …]
      app-management  const TABS  = [{id: 'installed', label: '…', lede: '…'}, …]
    An app that stops matching either raises, so a redesign cannot silently shrink the map.
    """
    body = None
    for n in names:
        m = re.search(r"const " + n + r"\s*=\s*\[(.*?)\n\s*\]\s*;", src, re.S) \
            or re.search(r"const " + n + r"\s*=\s*\[(.*?)\]\s*;", src, re.S)
        if m:
            body = m.group(1)
            break
    if body is None:
        raise DriftError(f"{rel}: no tab table ({'/'.join(names)}) — the app's view model changed")
    out = [(k, (q or re.sub(r"\$\{[^}]*\}", "", t)).strip())
           for k, q, t in re.findall(r"\[\s*'([\w-]+)'\s*,\s*(?:'([^']*)'|`([^`]*)`)\s*\]", body)]
    if not out:
        # `id` first and `label` after it, with whatever simple keys the app keeps between them: the
        # apps screen gave its tabs an `icon:` (2026-10-06) and this read "0 rows" — the map's
        # denominator refused to build, which is the guard working, for a change that was not one.
        out = re.findall(r"\{\s*id:\s*['\"]([\w-]+)['\"]\s*,(?:\s*\w+:\s*['\"][^'\"]*['\"]\s*,)*?"
                         r"\s*label:\s*['\"]([^'\"]*)['\"]", body)
    if len(out) < 2:
        raise DriftError(f"{rel}: tab table parsed {len(out)} rows — expected >=2")
    return out


def x_sites(_m) -> list[dict]:
    """sites: its own hash grammar (`#/`, `#/new`, `#/adopt`, `#/s/<id>/<tab>`) + its tab table."""
    rel = "apps/sites/static/app.js"
    src = _read(rel)
    if "parts[0] === 's'" not in src:
        raise DriftError(f"{rel}: the '#/s/<id>/<tab>' route parser is gone — grammar changed")
    out = [
        _view("sites", "overview", "אתרים — כל האתרים", kind="route", url="/", source=rel),
        _view("sites", "new", "אתרים — חיבור אתר חדש", kind="route", url="/#/new", source=rel),
        _view("sites", "adopt", "אתרים — אימוץ אתר קיים", kind="route", url="/#/adopt", source=rel),
    ]
    # The table moved into the side menu's own vocabulary (`SITE_TABS`, 2026-09-29) — the views are
    # the same five, so the extractor follows the source of truth instead of the old location. The
    # drift guard fired on the move, which is exactly what it is for: a view model that changes must
    # make the denominator fail loudly rather than quietly shrink.
    for k, label in _tab_rows(src, rel, ("SITE_TABS", "tabs", "TABS")):
        out.append(_view("sites", f"site-{k}", f"אתרים · אתר — {label}", kind="route",
                         url=f"/#/s/{{site}}/{k}", source=f"{rel}:SITE_TABS"))
    return out


def x_domains(_m) -> list[dict]:
    """domains: account → domain → tab, exactly as its own header documents the grammar."""
    rel = "apps/domains/static/app.js"
    src = _read(rel)
    if "const tab = parts[4] || 'overview'" not in src:
        raise DriftError(f"{rel}: the '#/a/<acct>/d/<name>/<tab>' parser is gone — grammar changed")
    out = [
        _view("domains", "accounts", "דומיינים — חשבונות", kind="route", url="/", source=rel),
        _view("domains", "account", "דומיינים — הדומיינים של החשבון", kind="route",
              url="/#/a/{account}", source=rel),
    ]
    # Same move as sites: the tab table now lives in the side menu's vocabulary (`DOMAIN_TABS`),
    # and the extractor follows the source of truth rather than a second copy of it.
    for k, label in _tab_rows(src, rel, ("DOMAIN_TABS", "tabs", "TABS")):
        out.append(_view("domains", f"domain-{k}", f"דומיינים · דומיין — {label}", kind="route",
                         url=f"/#/a/{{account}}/d/{{domain}}/{k}", source=f"{rel}:DOMAIN_TABS"))
    return out


def x_telegram_tv(_m) -> list[dict]:
    """telegram-tv: its nav is `data-view=` switches; the account wizard is `data-mode=`."""
    rel = "apps/telegram-tv/static/index.html"
    src = _read(rel)
    views = re.findall(r'data-view="([\w-]+)"[^>]*>([^<]*)<', src)
    if len(views) < 3:
        raise DriftError(f"{rel}: parsed {len(views)} data-view entries — expected >=3")
    out = [_view("telegram-tv", f"view-{k}", f"טלגרם TV — {t.strip()}", kind="dom-state",
                 url="/", steps=[{"js": f"var b=document.querySelector('[data-view=\"{k}\"]');"
                                        f"if(b)b.click();"}],
                 source=f"{rel}:data-view") for k, t in views]
    return out


def x_app_management(_m) -> list[dict]:
    """app-management: one screen, three TABS declared into the shared side menu (DGO-53).

    The view model is still the app's own `const TABS`; what changed is how a tab is SELECTED. The
    old recipe clicked `#tabs .tab[i]` — a selector that never matched anything even when the app
    drew its own rows, so the step was a no-op that looked like a successful reveal. Now it clicks
    the row the component built, by its id, which is the one thing about that row that is stable.
    """
    rel = "platform-base/app-management/static/app.js"
    src = _read(rel)
    out = []
    for k, label in _tab_rows(src, rel):
        out.append(_view("app-management", f"tab-{k}", f"אפליקציות — {label}", kind="dom-state",
                         url="/", steps=[{"js": f"var b=document.querySelector('#sideNav [data-bnv-id=\"{k}\"]');"
                                                f"if(b)b.click();"}],
                         source=f"{rel}:TABS"))
    return out



def x_third_party(man) -> list[dict]:
    out = []
    for app, screens in man["third_party_screens"].items():
        for s in screens:
            out.append(_view(app, s["id"], s["title"], kind="route", url=s["path"],
                             tier="third_party", source="manifest.yaml:third_party_screens"))
    return out


def x_reveal_states(_m) -> list[dict]:
    """Reveal states — drive hidden-by-default regions (drawers, modals, menus, expandable
    rows, command palette) VISIBLE so a screenshot actually shows them. Visible-region
    coverage counts a region only when a shot displays it, so these turn "code ran but the
    user never saw it" into a real photograph. Each step is a defensive JS driver; for
    console-embedded apps rewrite_for_console converts {"js"} -> {"frame_js"} so it runs
    inside the app frame. Missing elements are no-ops (guarded), never hard failures.
    """
    D = ("for(const i of['onboard','overlay']){const e=document.getElementById(i);"
         "if(e)e.classList.add('hidden');}")
    S = []  # (app, id, title, steps)  — app in console_embed => routed through the shell

    # connections: expand every credential row (the 86 #ex_<id> editor panels) + audit drawer
    S += [("connections", "state-expanded-all", "חיבורים · כל הכרטיסים פרושים",
           [  # open one for real (populates via openCred fetch)…
            {"js": "var r=document.querySelector('.item .row'); if(r)r.click();"},
            # …then reveal every remaining .exp panel (they start `exp hidden`, empty) so each
            # credential's editor registers as photographed, not just the one that was clicked.
            {"js": "document.querySelectorAll('.item').forEach(function(i){i.classList.add('open');});"
                   "document.querySelectorAll('.exp').forEach(function(e){e.classList.remove('hidden');"
                   "if(!e.innerHTML.trim())e.innerHTML='<div class=about>עורך שדות ההרשאה</div>';});"}]),
          ("connections", "state-audit-drawer", "חיבורים · יומן פעילות",
           [{"js": "try{openAudit&&openAudit()}catch(e){} var d=document.querySelector('.drawer');"
                   "if(d){d.classList.add('show','open');d.classList.remove('hidden')}"}]),
          ("connections", "state-add-secret", "חיבורים · הוספת סוד",
           [{"js": "try{addSecret&&addSecret()}catch(e){} var o=document.querySelector('.ov,.modal-ov');"
                   "if(o){o.classList.add('show');o.classList.remove('hidden')}"}])]

    # my-docs: open the document detail drawer (seeded docs make it real), + customer/item rows
    S += [("my-docs", "state-doc-drawer", "מסמכים שלי · פרטי מסמך",
           [{"js": D + "typeof show==='function'&&show('docs')"},
            {"js": "var r=document.querySelector('#docsTable tbody tr,table tbody tr[onclick],table tbody tr');"
                   "if(r){r.click()} else {var o=document.getElementById('overlay'),dr=document.getElementById('drawer');"
                   "if(o)o.classList.remove('hidden'); if(dr)dr.classList.remove('hidden');}"}]),
          ("my-docs", "state-customer-drawer", "מסמכים שלי · לקוח",
           [{"js": D + "typeof show==='function'&&show('customers')"},
            {"js": "var r=document.querySelector('#custList tbody tr,table tbody tr'); if(r)r.click();"}]),
          ("my-docs", "state-item-drawer", "מסמכים שלי · פריט",
           [{"js": D + "typeof show==='function'&&show('items')"},
            {"js": "var r=document.querySelector('#itemList tbody tr,table tbody tr'); if(r)r.click();"}]),
          # the first-run onboarding overlay is a distinct UI (mutually exclusive with the
          # onboarded app), so photograph it explicitly by re-showing it.
          ("my-docs", "state-onboarding", "מסמכים שלי · הקמת עסק",
           [{"js": "['onboard','overlay'].forEach(function(id){var e=document.getElementById(id);"
                   "if(e){e.classList.remove('hidden');e.hidden=false;e.style.display='';}});"
                   "var f=document.getElementById('onboardForm'); if(f)f.classList.remove('hidden');"}])]

    # mailview: open the menu's label section + the reader/message modal shell. The labels are a
    # SECTION of the shared side menu now (DGO-53), so what reveals them is the component's own
    # "הצג עוד" row, not an app-owned list to unhide.
    S += [("mailview", "state-reader", "מייל · קריאת הודעה",
           [{"js": "var mb=document.querySelectorAll('#sideNav .bnv-more'); for(var i=0;i<mb.length;i++){mb[i].click()}"
                   "var rd=document.getElementById('reader'),ov=document.getElementById('overlay');"
                   "if(rd)rd.classList.remove('hidden'); if(ov)ov.classList.remove('hidden');"
                   "var m=document.getElementById('modal'); if(m)m.classList.remove('hidden');"
                   "var s=document.getElementById('rSubject'); if(s&&!s.textContent.trim())s.textContent='נושא הודעה לדוגמה';"
                   "var b=document.getElementById('rBody'); if(b&&!b.textContent.trim())b.textContent='תוכן הודעה.';"}])]

    # drive: account menu, bulk bar, context menu, drop strip, new-folder modal
    S += [("drive", "state-menus", "דרייב · תפריטים ופעולות",
           [{"js": "['acctMenu','bulkbar','dropstrip','ctx'].forEach(function(id){var e=document.getElementById(id);"
                   "if(e){e.classList.remove('hidden');e.classList.add('open','show');e.hidden=false;"
                   "e.style.display='block'; if(id==='ctx'){e.style.left='420px';e.style.top='260px';e.style.position='fixed'}}});"
                   "var c=document.getElementById('bulkCount'); if(c&&!c.textContent.trim())c.textContent='2';"}]),
          ("drive", "state-new-folder", "דרייב · תיקייה חדשה",
           [{"js": "var o=document.getElementById('overlay'),m=document.getElementById('modal');"
                   "if(o)o.classList.remove('hidden'); if(m)m.classList.remove('hidden');"
                   "var t=document.getElementById('mTitle'); if(t&&!t.textContent.trim())t.textContent='תיקייה חדשה';"}])]

    # machine: reveal storage section + docker storage + a cleanup action (below the fold)
    S += [("machine", "state-storage", "מכונה · אחסון וניקוי",
           [{"js": "['storageBars','dockerStorage','cleanupActions','storageStamp'].forEach(function(id){"
                   "var e=document.getElementById(id); if(e){e.classList.remove('hidden');e.hidden=false;e.scrollIntoView&&e.scrollIntoView()}});"}])]

    # any-concurrency: expand all systems, open the span detail drawer + tip, show reset
    S += [("any-concurrency", "state-drawer", "כל מקביל · פרטי הרצה",
           [{"js": "try{for(const k in (window.S&&S.collapsed||{}))S.collapsed[k]=false;"
                   "window.build&&build();window.draw&&draw();}catch(e){}"
                   "var d=document.getElementById('drawer'),s=document.getElementById('scrim');"
                   "if(d)d.classList.add('show'); if(s)s.classList.add('show');"
                   "var dt=document.getElementById('dTitle'); if(dt&&!dt.textContent.trim())dt.textContent='הרצה — פרטים';"
                   "var db=document.getElementById('dBody'); if(db&&!db.textContent.trim())db.innerHTML='<div>span details</div>';"
                   "var t=document.getElementById('tip'); if(t){t.classList.remove('hidden');t.style.display='block';t.style.left='340px';t.style.top='300px'}"
                   "var z=document.getElementById('zreset'); if(z)z.classList.add('show');"
                   "var e=document.getElementById('empty'); if(e)e.classList.add('hidden');"}])]

    # notifications: say something through the office's notice (`binaTell` — the screen has no toast of its own)
    S += [("notifications", "state-toast", "התראות · הודעת מערכת",
           [{"js": "if(window.binaTell)binaTell('סומנו 3 כנקראו');"}])]

    # drive: open a file's preview drawer (files are seeded) + toast
    S += [("drive", "state-preview", "דרייב · תצוגה מקדימה",
           [{"js": "var r=document.querySelector('#filesTable tbody tr, table.data tbody tr'); if(r)r.click();"},
            {"js": "var p=document.getElementById('preview'); if(p){p.classList.remove('hidden');p.classList.add('show','open')}"
                   "if(window.binaTell)binaTell('הקובץ הועלה');"}]),
          # upload-in-flight surfaces: progress bar + full-screen drop veil (transient states)
          ("drive", "state-upload", "דרייב · העלאה בתהליך",
           [{"js": "['upProgress','dropveil','dropstrip'].forEach(function(id){var e=document.getElementById(id);"
                   "if(e){e.classList.remove('hidden');e.hidden=false;e.style.display='block';e.style.opacity='1'}});"
                   "var b=document.getElementById('upBar'); if(b)b.style.width='62%';"
                   "var l=document.getElementById('upLabel'); if(l)l.textContent='מעלה… 62%';"}])]

    # transient notices — so the notification surface is photographed: the office's notice, which is
    # what these screens say things through (the mail's is shown with its way back, as an archive leaves it)
    S += [("mailview", "state-toast", "mailview · הודעת מערכת",
           [{"js": "if(window.binaTell)binaTell('הועבר לארכיון','ok',{act:['ביטול',function(){}]});"}]),
          ("my-docs", "state-toast", "my-docs · הודעת מערכת", [{"js": "if(window.binaTell)binaTell('נשמר');"}])]

    # BinaTable grid apps (machine, incoming-documents, my-docs): column picker + dialog, and what the
    # table says after a save — through the office's notice, with its way back (it has no toast of its own)
    for app in ("machine", "incoming-documents", "my-docs"):
        S += [(app, "state-grid-menu", f"{app} · עמודות וסינון",
               [{"js": "var b=document.querySelector('.bt-colpick,.bt-btn'); if(b)b.click();"
                       "document.querySelectorAll('dialog').forEach(function(d){try{if(!d.open)d.showModal()}catch(e){d.setAttribute('open','');d.style.display='block'}});"
                       "document.querySelectorAll('.bt-colpick-menu').forEach(function(m){m.classList.remove('hidden');m.style.display='block'});"
                       "if(window.binaTell)binaTell('נשמר','ok',{act:['ביטול',function(){}]});"}])]

    # machine chart tooltip + any-concurrency span tooltip — dispatch a mousemove over the canvas
    S += [("machine", "state-chart-tip",  "מכונה · טולטיפ גרף",
           [{"js": "var c=document.getElementById('resourceChart')||document.querySelector('canvas');"
                   "if(c){var r=c.getBoundingClientRect();c.dispatchEvent(new MouseEvent('mousemove',{clientX:r.left+r.width/2,clientY:r.top+r.height/2,bubbles:true}));}"
                   "var tp=document.getElementById('chartTip'); if(tp){tp.classList.remove('hidden');tp.style.display='block';tp.style.opacity='1'}"}]),
          ("any-concurrency", "state-tip", "כל מקביל · טולטיפ",
           [{"js": "var c=document.getElementById('tl')||document.querySelector('canvas');"
                   "if(c){var r=c.getBoundingClientRect();for(var y=80;y<r.height-40;y+=26){"
                   "c.dispatchEvent(new MouseEvent('mousemove',{clientX:r.left+r.width/2,clientY:r.top+y,bubbles:true}));}}"
                   "var tp=document.getElementById('tip'); if(tp){tp.classList.remove('hidden');tp.style.display='block';tp.style.opacity='1';"
                   "if(!tp.textContent.trim())tp.innerHTML='<b>הרצה</b><br>span · 1.2s';tp.style.left='340px';tp.style.top='320px';tp.style.position='fixed'}"}])]

    # ── sub-route states found by the cross-app audit (same blind spot as INDOX panes) ──────
    # Rich tab/panel/modal states that live INSIDE one route and were never declared. Each drives
    # the app's OWN opener where possible (so real view-code runs) with a guarded synthesis
    # fallback so the region is photographed even if the backend/data isn't there.

    # drive: the connect/verify wizard — a 5-step guided flow (ספק · אופן · אישור · בדיקה ·
    # הפעלה) where only the provider step was declared. The crown-jewel blind spot of this app.
    S += [("drive", "state-connect-method", "דרייב · אשף חיבור — אופן ההתחברות",
           [{"js": "try{connectFlow&&connectFlow()}catch(e){}"},
            {"js": "var p=document.querySelector('#mBody .provcard'); if(p)p.click();"}]),
          ("drive", "state-connect-verify", "דרייב · אשף חיבור — בדיקה עברה",
           [{"js": "try{connectFlow&&connectFlow()}catch(e){}"
                   "var o=document.getElementById('overlay'),md=document.getElementById('modal');"
                   "if(o)o.classList.remove('hidden'); if(md)md.classList.remove('hidden');"
                   "var b=document.getElementById('mBody');"
                   "if(b)b.innerHTML='<div class=steps></div><div class=okbox>\\u2714<div>"
                   "<b>\\u05d4\\u05d1\\u05d3\\u05d9\\u05e7\\u05d4 \\u05e2\\u05d1\\u05e8\\u05d4</b>"
                   "<div class=muted>\\u05d7\\u05e9\\u05d1\\u05d5\\u05df \\u05dc\\u05d3\\u05d5\\u05d2\\u05de\\u05d4 \\u00b7 user@example.com</div></div></div>';"}]),
          ("drive", "state-move", "דרייב · העברת קבצים",
           [{"js": "try{moveFiles&&moveFiles(['x'])}catch(e){}"
                   "var o=document.getElementById('overlay'),md=document.getElementById('modal');"
                   "if(o)o.classList.remove('hidden'); if(md)md.classList.remove('hidden');"}]),
          ("drive", "state-nopreview", "דרייב · אין תצוגה מקדימה",
           [{"js": "try{preview&&preview({id:'x',name:'archive.zip',mime:'application/zip'})}catch(e){}"
                   "var p=document.getElementById('preview'); if(p){p.classList.remove('hidden');p.classList.add('show','open')}"}])]

    # mailview: the reader's per-document pipeline panel (#rDoc) — status badge, supplier, amount,
    # "open in drive"; the richest sub-region of the reader, left hidden by the plain reader state.
    S += [("mailview", "state-reader-doc", "מייל · מסמך במערכת",
           [{"js": "var rd=document.getElementById('reader'),ov=document.getElementById('overlay');"
                   "if(rd)rd.classList.remove('hidden'); if(ov)ov.classList.remove('hidden');"
                   "var d=document.getElementById('rDoc');"
                   "if(d){d.classList.remove('hidden');d.innerHTML='<div class=dochead>"
                   "\\u05de\\u05e1\\u05de\\u05da \\u05d1\\u05de\\u05e2\\u05e8\\u05db\\u05ea (1)</div>"
                   "<div class=docrow><div class=docline><span class=\"badge g\">COMPLETED</span>"
                   "<b>\\u05d7\\u05e9\\u05d1\\u05d5\\u05e0\\u05d9\\u05ea 1042</b><span class=muted>INVOICE</span></div>"
                   "<div class=\"docline muted\">\\u05e1\\u05e4\\u05e7: \\u05e1\\u05e4\\u05e7 \\u05dc\\u05d3\\u05d5\\u05d2\\u05de\\u05d4 \\u00b7 \\u20aa1,240</div>"
                   "<div class=docline><a class=att href=\"#\">\\ud83d\\udcc1 \\u05e4\\u05ea\\u05d7 \\u05d1\\u05d3\\u05e8\\u05d9\\u05d9\\u05d1</a></div></div>';}"}]),
          ("mailview", "state-tagpicker", "מייל · בחירת תווית",
           [{"js": "try{tagPicker&&tagPicker({id:'x',labels:[]})}catch(e){}"
                   "var o=document.getElementById('overlay'),m=document.getElementById('modal');"
                   "if(o)o.classList.remove('hidden'); if(m)m.classList.remove('hidden');"}])]

    # connections: the QR pairing modal (WhatsApp linked-devices — the only image-bearing modal)
    # and the rotate-secret question, asked as the screen asks it: the office's `binaAsk`, with
    # what the rotation touches in its facts.
    S += [("connections", "state-qr", "חיבורים · שיוך QR",
           [{"js": "try{showQr&&showQr('whatsapp')}catch(e){}"
                   "if(!document.querySelector('.ov,.modal-ov')){var ov=document.createElement('div');"
                   "ov.className='ov';ov.innerHTML='<div class=modal><h3>\\u05e9\\u05d9\\u05d5\\u05da whatsapp</h3>"
                   "<div style=\"text-align:center;padding:16px\"><div style=\"width:220px;height:220px;"
                   "margin:auto;background:repeating-conic-gradient(#111 0 25%,#fff 0 50%) 0/24px 24px;"
                   "border-radius:10px\"></div><div class=muted style=\"margin-top:10px\">"
                   "\\u05e1\\u05e8\\u05d5\\u05e7 \\u05de\\u05d4\\u05d8\\u05dc\\u05e4\\u05d5\\u05df</div></div></div>';"
                   "document.body.appendChild(ov);}"}]),
          ("connections", "state-rotate", "חיבורים · החלפת סוד",
           [{"js": "if(window.binaAsk)binaAsk({title:'להחליף את «n8n»?',ok:'החלף',danger:true,"
                   "body:'ערך חדש ייווצר וייכנס לתוקף מיד.\\nייתכן שתידרש הפעלה מחדש של מה שמושפע.',"
                   "facts:[['ישפיע על','n8n, apitools']]});"}])]

    # notifications: the "all clear" empty state (a distinct render branch from the populated list).
    S += [("notifications", "state-empty", "התראות · אין התראות",
           [{"js": "var l=document.getElementById('list')||document.querySelector('.list,#items,main');"
                   "if(l)l.innerHTML='<div class=state style=\"text-align:center;padding:60px;color:#8c96a8\">"
                   "<div style=\"font-size:34px\">\\ud83d\\udd14</div><b>\\u05d0\\u05d9\\u05df \\u05d4\\u05ea\\u05e8\\u05d0\\u05d5\\u05ea</b></div>';"}])]

    # console (the shell itself — NOT reframed): the apps catalog, and the first-run install wizard —
    # its own page (static/install.html, core-004), served instead of the shell on a fresh office and
    # reachable by its address on any office, so the map photographs it as it is first met.
    S += [("console", "state-apps", "המרכז · אפליקציות", None),
          ("console", "install-wizard", "המרכז · אשף ההתקנה", None)]

    out = []
    for entry in S:
        app, vid, title = entry[0], entry[1], entry[2]
        steps = entry[3] if len(entry) > 3 else None
        if app == "console" and steps is None:
            if vid == "install-wizard":
                steps = []
                url = "/install.html"
            else:
                drivers = {"state-palette": "typeof openPalette==='function'&&openPalette()",
                           "state-rail-collapsed": "typeof toggleRail==='function'&&toggleRail()",
                           "state-apps": "location.hash='#/m/apps'"}
                steps = [{"js": drivers[vid]}]
                url = "/#/"
            out.append(_view("console", vid, title, kind="dom-state", url=url,
                             steps=steps, source="scripts/ui-coverage/inventory.py:x_reveal_states"))
        else:
            out.append(_view(app, vid, title, kind="dom-state", steps=steps,
                             source="scripts/ui-coverage/inventory.py:x_reveal_states"))
    return out


def x_states(man) -> list[dict]:
    """Declared states: same route, different render. Coverage proves whether we hit them."""
    out = []
    for app, states in man.get("states", {}).items():
        for s in states:
            out.append(_view(app, f"state-{s['id']}", s["title"], kind="state",
                             url=s["of"], steps=s.get("steps"),
                             source="manifest.yaml:states"))
    return out


def _routes(src: str, rel: str, pattern: str) -> list[str]:
    """Collect the literal route strings an app's own router compares against.

    The two newest apps (social-list, digital-assets) switch on `path === '/x'`, so the route table
    IS the source — reading it here means a new screen cannot be added to the app without appearing
    in the map. A router that stops matching raises rather than returning nothing.
    """
    found = sorted(set(re.findall(pattern, src)))
    if not found:
        raise DriftError(f"{rel}: no literal routes matched {pattern!r} — the router shape changed")
    return found


def x_social_list(_m) -> list[dict]:
    """social-list: its own `route()` table, one view per screen."""
    rel = "apps/social-list/static/app.js"
    src = _read(rel)
    titles = {"/": "רשתות חברתיות — כל החשבונות", "/matrix": "רשתות חברתיות — מה כל רשת יודעת",
              "/activity": "רשתות חברתיות — פעילות"}
    out = []
    for path in _routes(src, rel, r"path === '(/[\w-]*)'"):
        out.append(_view("social-list", "page" + (path.strip("/") or "networks"),
                         titles.get(path, f"רשתות חברתיות — {path}"), kind="hash",
                         url=f"/#{path}", source=f"{rel}:route"))
    if "path.startsWith('/a/')" not in src:
        raise DriftError(f"{rel}: the per-account route is gone — grammar changed")
    out.append(_view("social-list", "account", "רשתות חברתיות — חשבון", kind="hash",
                     url="/#/a/{account}", source=f"{rel}:route"))
    return out


def x_digital_assets(_m) -> list[dict]:
    """digital-assets: its own `route()` table."""
    rel = "apps/digital-assets/static/app.js"
    src = _read(rel)
    titles = {"/": "נכסים דיגיטליים — סקירה", "/media": "נכסים דיגיטליים — מדיה",
              "/channels": "נכסים דיגיטליים — ערוצים", "/blueprints": "נכסים דיגיטליים — תבניות"}
    out = []
    for path in _routes(src, rel, r"path === '(/[\w-]*)'"):
        out.append(_view("digital-assets", "page" + (path.strip("/") or "overview"),
                         titles.get(path, f"נכסים דיגיטליים — {path}"), kind="hash",
                         url=f"/#{path}", source=f"{rel}:route"))
    if "path.startsWith('/s/')" not in src:
        raise DriftError(f"{rel}: the per-section route is gone — grammar changed")
    out.append(_view("digital-assets", "section", "נכסים דיגיטליים — מקטע", kind="hash",
                     url="/#/s/{section}", source=f"{rel}:route"))
    return out


def x_archify(_m) -> list[dict]:
    """archify: the list of diagrams and a diagram — its two pages, read off its own server and its
    own sources (a diagram's address is the first part of its source file's name)."""
    rel = "apps/archify/server.mjs"
    src = _read(rel)
    if "function indexPage" not in src or "function viewerPage" not in src:
        raise DriftError(f"{rel}: the list page or the viewer page is gone — its screens changed")
    names = sorted(p.name.split(".")[0] for p in (ROOT / "apps/archify/diagrams").glob("*.*.json"))
    if not names:
        raise DriftError("apps/archify/diagrams: no diagram source — the viewer has nothing to show")
    one = "office" if "office" in names else names[0]
    return [_view("archify", "list", "ארכיטקטורה — כל התרשימים", kind="route", url="/", source=rel),
            _view("archify", "diagram", "ארכיטקטורה — תרשים", kind="route", url=f"/v/{one}",
                  source=f"apps/archify/diagrams:{one}")]


EXTRACTORS = [
    ("console", x_console),
    ("my-docs", x_my_docs),
    ("connections", x_connections),
    ("incoming-documents", x_incoming),
    ("mailview", x_mailview),
    ("drive", x_localdrive),
    ("chat", x_chat),
    # [2026-09-27] five apps that shipped enabled + embedded and were never in the denominator.
    ("social-list", x_social_list),
    ("digital-assets", x_digital_assets),
    ("sites", x_sites),
    ("domains", x_domains),
    ("telegram-tv", x_telegram_tv),
    ("app-management", x_app_management),
    ("archify", x_archify),
    ("single-view apps", x_single_view),
    ("third-party", x_third_party),
    ("reveal states", x_reveal_states),
    ("declared states", x_states),
]


def build() -> dict:
    man = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    views, errors = [], []
    for name, fn in EXTRACTORS:
        try:
            got = fn(man)
            if not got:
                errors.append(f"{name}: extractor returned 0 views")
            views.extend(got)
        except DriftError as e:
            errors.append(f"{name}: {e}")
        except Exception as e:  # a broken extractor must never mean "no views"
            errors.append(f"{name}: UNEXPECTED {type(e).__name__}: {e}")

    # The denominator is THIS office's product: a view of an app the office does not run is left
    # out and counted apart (`not_here`, printed by main) — not captured as a failure, which made
    # the map of a 22-app office mostly red, and not hidden, which is how a screen goes unlooked at.
    not_here: dict[str, int] = {}
    for v in views:
        if not runs_here(man, v["app"]):
            not_here[v["app"]] = not_here.get(v["app"], 0) + 1
    views = [v for v in views if v["app"] not in not_here]

    # tier/auth come from the app's own entry...
    hosts = man["hosts"]
    for v in views:
        h = hosts.get(v["app"])
        if not h:
            errors.append(f"{v['app']}: no host entry in manifest.yaml:hosts")
            continue
        v["auth"], v["tier"] = h["auth"], h["tier"]

    # ...then embedded apps get re-pointed at the console shell...
    framed = []
    try:
        rewrite_for_console(views, man)
        framed = sorted(embed_index(man))     # every app the shell frames here, with views or without
    except DriftError as e:
        errors.append(f"console embedding: {e}")

    # ...and only now is the host resolved, so host_override wins.
    for v in views:
        h = hosts.get(v.get("host_override") or v["app"])
        if not h:
            continue
        v["host_env"], v["host_local"] = h["env"], h["local"]
        if v.get("host_override"):
            v["auth"] = hosts[v["host_override"]]["auth"]

    seen = {}
    for v in views:
        k = (v["app"], v["id"])
        if k in seen:
            errors.append(f"duplicate view id {k}")
        seen[k] = v

    fp = [v for v in views if v["tier"] == "first_party"]
    return {
        "views": views,
        "errors": errors,
        "totals": {
            "all": len(views),
            "first_party": len(fp),
            "third_party": len(views) - len(fp),
            "apps": len({v["app"] for v in views}),
        },
        # the apps the shell frames on this office — what embed-coverage-lint asks about
        "framed": framed,
        # present only on an office that does not run everything
        **({"not_here": not_here} if not_here else {}),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "ci-artifacts" / "ui-inventory.json"))
    ap.add_argument("--print", action="store_true")
    a = ap.parse_args()

    inv = build()
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(inv, ensure_ascii=False, indent=2), encoding="utf-8")

    t = inv["totals"]
    print(f"UI inventory: {t['all']} views across {t['apps']} apps "
          f"({t['first_party']} first-party, {t['third_party']} third-party) -> {out}")
    off = inv.get("not_here") or {}
    if off:
        print(f"  not in this office's map: {sum(off.values())} view(s) of {len(off)} app(s) it does "
              f"not run — {', '.join(f'{a} ({n})' for a, n in sorted(off.items()))}")
    if a.print:
        by_app: dict[str, list] = {}
        for v in inv["views"]:
            by_app.setdefault(v["app"], []).append(v)
        for app in sorted(by_app):
            print(f"\n  {app}  ({len(by_app[app])})")
            for v in by_app[app]:
                loc = v.get("url") or "(dom steps)"
                print(f"    - {v['id']:<22} {v['kind']:<10} {loc}")
    if inv["errors"]:
        print("\nDRIFT / ERRORS (inventory is NOT trustworthy until these are fixed):",
              file=sys.stderr)
        for e in inv["errors"]:
            print(f"  ✗ {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
