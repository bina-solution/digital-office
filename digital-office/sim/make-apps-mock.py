#!/usr/bin/env python3
"""Write digital-office/sim/mocks/app-management.js from the manifests themselves.

The simulation's apps screen is the REAL frontend (platform-base/app-management/static) over a mock
of its API. The catalogue it shows is not invented: names, icons, versions, layers and summaries are
read from every app.json, and the dispositions are the product's first run (the platform, n8n,
drive, mail, indox with apitools, the office agent) — the same set the proposed default state file
holds. Re-run after adding an app:

    python3 digital-office/sim/make-apps-mock.py
"""
import glob
import io
import json
import os
import pathlib

repo = str(pathlib.Path(__file__).resolve().parents[2])
ON = {"app-management", "traefik", "postgres", "redis", "authentik", "connections", "autoheal",
      "console", "n8n", "notifications", "any-concurrency", "machine", "data-management", "bina-ui",
      "apitools", "indox", "bina-ds", "drive", "mail"}

apps = []
for m in sorted(glob.glob(repo + "/apps/*/app.json") + glob.glob(repo + "/platform-base/*/app.json")):
    a = json.load(open(m, encoding="utf-8"))
    base = "platform-base" in m.replace("\\", "/")
    title = a.get("title") or {}
    mod = next(((r.get("module") or {}) for r in (a.get("routing") or []) if r.get("module")), {})
    summary = a.get("summary") or a.get("description") or {}
    if isinstance(summary, dict):
        summary = summary.get("he") or summary.get("en") or ""
    services = a.get("services")
    n = len(services) if isinstance(services, (list, dict)) and services else 1
    kind = a.get("kind") or "service"
    total = 0 if kind in ("library", "blueprint") else n
    on = a["id"] in ON
    apps.append({
        "id": a["id"], "name": title.get("he") or mod.get("name") or a["id"], "name_en": title.get("en") or "",
        "summary": summary or mod.get("desc") or "", "icon": mod.get("icon") or a.get("icon") or "app",
        "version": a.get("version") or "1.0.0", "layer": a.get("layer"), "core": base, "kind": kind,
        "installed": on, "enabled": on, "archived": False, "present": on,
        "running": total if on else 0, "total": total, "health": "healthy" if on and total else "none",
        "state": "enabled" if on else "disabled", "state_by": None, "state_desired": "enabled" if on else "disabled",
        "volumes": [v if isinstance(v, str) else (v or {}).get("name") for v in ((a.get("data") or {}).get("volumes") or [])][:3],
        "on_uninstall": (a.get("data") or {}).get("on_uninstall") or "keep",
        "launch": ({"embed": bool(mod.get("embed", True)), "module": mod.get("alias") or a["id"], "url": ""} if mod else None),
        "services": [],
    })

js = '''/* Mock backend for the apps screen (app-management) — the REAL frontend over this.
   GENERATED from the manifests by digital-office/sim/make-apps-mock.py (names, icons, versions, layers and
   summaries are every app.json's own); the dispositions are the product's first run. The verbs
   work on this in-memory copy, so installing, switching off and removing can be driven and seen. */
(function(){
  var APPS = __APPS__;
  function conds(a){
    var t = "2026-10-06T18:40:44Z", on = a.enabled, up = on && a.running === a.total;
    return [{type:"Resolved",status:"True",reason:"InCatalog",message:"",lastTransitionTime:t},
            {type:"Installed",status:a.installed?"True":"False",reason:a.installed?"ContainersPresent":"NotInstalled",message:"",lastTransitionTime:t},
            {type:"Started",status:up?"True":"False",reason:up?"AllContainersRunning":"Disabled",message:up?(a.running+"/"+a.total):"switched off by the operator",lastTransitionTime:t},
            {type:"Ready",status:up?"True":"False",reason:up?"AllChecksPassed":"Disabled",message:"",lastTransitionTime:t}];
  }
  function list(){
    APPS.forEach(function(a){ a.conditions = conds(a); });
    var inst = APPS.filter(function(a){ return !a.core; });
    return { apps: APPS, project: "digital-office",
             counts: { total: APPS.length, core: APPS.length - inst.length, installable: inst.length,
                       running: APPS.filter(function(a){ return a.enabled && a.total; }).length } };
  }
  function find(u){ var m = u.match(/api\\/apps\\/([^\\/?]+)/); return m && APPS.filter(function(a){ return a.id === decodeURIComponent(m[1]); })[0]; }
  function set(a, on, extra){
    a.enabled = on; a.installed = on || a.installed; a.present = a.installed;
    a.running = on ? a.total : 0; a.health = on && a.total ? "healthy" : "none";
    a.state = a.state_desired = on ? "enabled" : "disabled"; a.state_by = "user";
    if (extra) Object.keys(extra).forEach(function(k){ a[k] = extra[k]; });
    return { ok: true, id: a.id, state: a.state };
  }
  window.__mock([
    [/api\\/apps\\/[^\\/]+\\/room/, function(u){ var a = find(u) || {};
      return { id: a.id, ok: true, need: { memory_mb: 256, cpus: 0.3, apps: 1 },
               have: { memory_available_mb: 5200, memory_total_mb: 15800, disk_available_mb: 412000, ncpu: 8, load1: 0.6, load_per_cpu: 0.08 },
               problems: [], summary: "אפשר להציב אפליקציה אחת ב-256MB זיכרון" }; }],
    [/api\\/apps\\/[^\\/]+\\/job/, function(){ return { state: "done", ok: true }; }],
    [/api\\/apps\\/[^\\/]+\\/enable/, function(u){ var a = find(u); return a ? set(a, true) : { error: "unknown app" }; }],
    [/api\\/apps\\/[^\\/]+\\/disable/, function(u){ var a = find(u); return a ? set(a, false) : { error: "unknown app" }; }],
    [/api\\/apps\\/[^\\/]+\\/unarchive/, function(u){ var a = find(u); return a ? set(a, true, { archived: false }) : { error: "unknown app" }; }],
    [/api\\/apps\\/[^\\/]+\\/archive/, function(u){ var a = find(u); return a ? set(a, false, { archived: true }) : { error: "unknown app" }; }],
    [/api\\/apps\\/[^\\/]+\\/uninstall/, function(u){ var a = find(u); return a ? set(a, false, { installed: false, present: false }) : { error: "unknown app" }; }],
    [/api\\/apps(\\?|$)/, function(){ return list(); }],
    [/api\\/catalog(\\?|$)/, function(){ return { entries: [], ref: "", error: null }; }],
    // one office: no linked office in the simulation, and the screen says so in its own words
    [/\\/api\\/modules/, function(){ return { modules: [] }; }],
    [/\\/a\\/dgo-extend\\/api\\/link/, function(){ return { home: { id: "office" }, items: [], serve: {} }; }]
  ]);
})();
'''.replace("__APPS__", json.dumps(apps, ensure_ascii=False, indent=1))
out = repo + "/digital-office/sim/mocks/app-management.js"
io.open(out, "w", encoding="utf-8", newline="\n").write(js)
print("wrote", os.path.relpath(out, repo), "·", len(apps), "apps ·", sum(1 for a in apps if a["enabled"]), "on ·", len(js) // 1024, "KB")
