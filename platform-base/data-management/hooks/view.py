#!/usr/bin/env python3
#: bbox data view [--app ID] [--json] [--archive DIR] [--gaps-only] — every byte of state this deployment owns
"""Render the data inventory in a terminal.

    This is a CLIENT of the data-management API and computes nothing. The same JSON renders the
    console page at console.localhost -> ניהול נתונים -> סיכום הנתונים. If the two ever disagree it
    is a rendering bug here, never a difference of opinion about what data exists.
"""
from __future__ import annotations

import sys as _sys
# Prints Hebrew/bidi text. On a host whose stdout is not already UTF-8 that raises
# UnicodeEncodeError on the first Hebrew character, and the traceback reads as a logic
# failure rather than an encoding one. Same guard the gates use. (G10)
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(_sys.stderr, "reconfigure"):
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")


import argparse
import json
import os
import sys
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _client import call                                   # noqa: E402


def human(n):
    """Decimal units, matching docker's own formatting — the volumes table prints docker's raw
    strings beside these, and mixing 1024-based totals with 1000-based strings makes the same
    number appear twice at two values."""
    if n is None:
        return "-"
    n = float(n)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1000 or u == "TB":
            return f"{n:.0f}{u}" if u == "B" else f"{n:.1f}{u}"
        n /= 1000.0


def render_app(d, app_id):
    """One app: everything it owns, and nothing else. The unit a per-app export moves."""
    a = next((x for x in (d.get("by_app") or []) if x["id"] == app_id), None)
    if not a:
        known = ", ".join(x["id"] for x in (d.get("by_app") or []) if x.get("store_count"))
        sys.exit(f"[bbox data view] no app '{app_id}'. Apps that own data: {known}")
    print("=" * 98)
    print(f" {a['id']}   layer {a.get('layer')}   {human(a['bytes'])} in {a['store_count']} store(s)"
          + ("" if a.get("enabled") is not False else "   [DISABLED — data kept]"))
    print("=" * 98)
    print(f"   {'store':<54}{'kind':<9}{'size':>10}  origin")
    for s in sorted(a["stores"], key=lambda r: -(r.get("bytes") or 0)):
        size = human(s["bytes"]) if s.get("bytes") is not None else (s.get("keys") or "-")
        print(f"   {s['name'][:54]:<54}{s['kind']:<9}{str(size):>10}  {s.get('provenance') or '-'}")
    print("=" * 98)
    return 0


def render(d, gaps_only=False):
    s = d.get("summary") or {}
    risk = s.get("at_risk") or []

    if gaps_only:
        unc = d.get("unclaimed") or []
        if not risk and not unc:
            print("nothing at risk — every store on this host is claimed and goes into a backup")
        for v in risk:
            print(f"{v['why']:<30} {v['volume']:<38} {v.get('size') or '?':>9}  "
                  f"declared by {', '.join(v.get('declared_by') or []) or '-'}")
        for u in sorted(unc, key=lambda r: -(r.get("bytes") or 0)):
            print(f"{'UNCLAIMED (' + u['kind'] + ')':<30} {u['name']:<38} "
                  f"{human(u.get('bytes')):>9}  {u.get('why', '')}")
        return

    W = 98
    print("=" * W)
    print(f" DATA VIEW   deployment={d.get('deployment')}   project={d.get('project')}")
    print("=" * W)

    print("\n SUMMARY")
    print(f"   BACKUP FOOTPRINT {human((s.get('volume_bytes') or 0) + (s.get('bind_bytes') or 0))}"
          f"   = volumes {human(s.get('volume_bytes'))} + binds {human(s.get('bind_bytes'))}")
    print(f"   (databases {human(s.get('db_bytes'))} are INSIDE those volumes — not added again)")
    print(f"   volumes {s.get('volumes')}   at risk {s.get('volumes_at_risk')}   "
          f"binds {s.get('binds')}   databases {s.get('databases')}")
    print(f"   apps {s.get('apps_enabled')}/{s.get('apps_total')} enabled, "
          f"{s.get('apps_with_hooks')} with backup hooks")

    if risk:
        print(f"\n !! {len(risk)} VOLUME(S) WILL NOT BE IN A BACKUP")
        for v in risk:
            print(f"      {v['volume']:<38} {v.get('size') or '?':>9}  {v['why']}"
                  + (f"  (declared by {', '.join(v['declared_by'])})" if v.get("declared_by") else ""))
    else:
        print("\n ✓ every volume on this host is covered by the backup")

    # ── the app-centric view. Same JSON the console renders; this is the terminal's rendering of it.
    by_app = [a for a in (d.get("by_app") or []) if a.get("store_count")]
    if by_app:
        print(f"\n DATA BY APP ({len(by_app)} app(s) own state)")
        print(f"   {'app':<20}{'size':>10}  {'stores':>6}  contents")
        for a in by_app:
            kinds = {}
            for s in a["stores"]:
                kinds[s["kind"]] = kinds.get(s["kind"], 0) + 1
            shape = ", ".join(f"{v} {k}" for k, v in sorted(kinds.items()))
            flag = "" if a.get("enabled") is not False else "  [disabled]"
            print(f"   {a['id']:<20}{human(a['bytes']):>10}  {a['store_count']:>6}  {shape}{flag}")

    unc = d.get("unclaimed") or []
    if unc:
        tot = sum(u.get("bytes") or 0 for u in unc)
        print(f"\n !! {len(unc)} STORE(S) NO APP CLAIMS  ({human(tot)})")
        print("    In a whole-host archive, but not exportable or restorable per app.")
        for u in sorted(unc, key=lambda r: -(r.get("bytes") or 0))[:12]:
            print(f"      {u['kind']:<7}{u['name']:<52}{human(u.get('bytes')):>10}")
        if len(unc) > 12:
            print(f"      … and {len(unc) - 12} more")

    print(f"\n VOLUMES ({len(d.get('volumes') or [])})")
    print(f"   {'volume':<40}{'size':>10}  {'coverage':<30}declared by")
    for v in d.get("volumes") or []:
        print(f"   {v['short']:<40}{(v.get('size') or '-'):>10}  {v['coverage']:<30}"
              f"{', '.join(v.get('declared_by') or []) or '-'}")

    if d.get("declared_absent"):
        print(f"\n DECLARED BUT NOT ON THIS HOST ({len(d['declared_absent'])}) — app not installed, harmless")
        for a in d["declared_absent"]:
            print(f"   {a['volume']:<40}declared by {', '.join(a['declared_by'])}")

    print(f"\n BINDS holding untracked files ({len(d.get('binds') or [])})")
    if d.get("bind_error"):
        print(f"   !! {d['bind_error']}")
    for b in d.get("binds") or []:
        print(f"   {b['path']:<52}{human(b.get('bytes')):>10}  {b['coverage']}")

    print("\n DATABASES")
    for inst in d.get("databases") or []:
        if inst.get("error"):
            print(f"   {inst['container']:<44}!! {inst['error']}")
            continue
        print(f"   {inst['container']}  (psql -U {inst.get('user')})")
        for db in inst.get("databases") or []:
            tabs = db.get("tables") or []
            print(f"     {db['name']:<26}{human(db.get('bytes')):>10}   {len(tabs)} tables with rows")
            for t in tabs[:8]:
                r = f"~{t['rows']:,}" if t.get("rows") is not None else "-"
                print(f"        {t['name']:<50}{r:>14}")
            if len(tabs) > 8:
                print(f"        … and {len(tabs) - 8} more")

    print("\n REDIS")
    for r in d.get("redis") or []:
        print(f"   {r['container']:<44}keys={r.get('keys') or '-'}  {r.get('error') or ''}")

    print("\n SECRET PATHS (a git clone does not bring these; the archive carries them)")
    for p in d.get("secret_paths") or []:
        print(f"   {p['path']:<52}{(human(p['bytes']) if p['exists'] else 'absent'):>10}")

    print("\n" + "=" * W)


def render_archive(m):
    # KEY NAMES COME FROM THE WRITER, not from what reads well here. deployment-archive.py writes
    # deployment_name / created_utc, and each artifact records `bytes`. This function originally read
    # deployment / created / size — all three absent — so it printed "None" for the deployment, "None"
    # for the date and 0 bytes total for a real 50GB archive. An inventory tool that reports an
    # archive as empty is worse than one that refuses to open it.
    arts = m.get("artifacts") or {}
    by_kind, total = {}, 0
    for name, meta in sorted(arts.items()):
        size = meta.get("bytes") if isinstance(meta, dict) else None
        total += size or 0
        by_kind.setdefault(meta.get("kind", "?") if isinstance(meta, dict) else "?", []).append((name, size))
    print("=" * 98)
    print(f" ARCHIVE   {m.get('deployment_name')}   project={m.get('compose_project')}   "
          f"mode={m.get('mode')}   created={m.get('created_utc')}   format={m.get('format_version')}")
    print("=" * 98)
    for kind, rows in sorted(by_kind.items()):
        print(f"\n {kind.upper()} ({len(rows)})")
        for name, size in rows:
            print(f"   {name:<62}{human(size):>10}")
    print("\n" + "=" * 98)
    print(f" {len(arts)} artifacts, {human(total)} total")
    print(" quiesced: writers stopped — cross-store consistent" if m.get("quiesced")
          else " NOT quiesced: each store internally consistent, the SET may skew by seconds")
    print("=" * 98)


def main():
    ap = argparse.ArgumentParser(prog="bbox data view")
    ap.add_argument("--json", action="store_true", help="raw API response")
    ap.add_argument("--archive", metavar="DIR", help="describe an archive instead of the live host")
    ap.add_argument("--gaps-only", action="store_true", help="only what will NOT be backed up")
    ap.add_argument("--refresh", action="store_true", help="force a fresh sweep instead of the cached one")
    ap.add_argument("--app", metavar="ID", help="only what this app owns — the unit a per-app export moves")
    a = ap.parse_args()

    if a.archive:
        path = f"/api/inventory?archive={quote(a.archive)}"
    else:
        # wait=true is not optional here. The service answers immediately with whatever sections have
        # landed so the console can fill in progressively; a CLI printing that same partial view would
        # read as the complete one — "0 volumes at risk" before the volume sweep has run is the exact
        # false all-clear this tool exists to prevent. So the CLI blocks and the browser does not.
        path = "/api/inventory?wait=true" + ("&refresh=true" if a.refresh else "")
    d = call("GET", path)

    if not a.archive and not d.get("complete"):
        print(f"[bbox data] WARNING: inventory incomplete ({d.get('error') or d.get('state')}) — "
              f"sections read: {', '.join(d.get('ready') or []) or 'none'}", file=sys.stderr)

    if a.json:
        print(json.dumps(d, indent=2, ensure_ascii=False))
    elif a.archive:
        render_archive(d)
    elif a.app:
        return render_app(d, a.app)
    else:
        render(d, gaps_only=a.gaps_only)

    # Non-zero when something would be missed, so CI and cron can gate on it. UNCLAIMED counts:
    # such a store still rides along in a whole-host archive, but it cannot be exported or restored
    # per app, and if it is genuinely orphaned nothing will notice when it stops existing.
    s = d.get("summary") or {}
    return 1 if (s.get("volumes_at_risk") or s.get("unclaimed")) else 0


if __name__ == "__main__":
    sys.exit(main())
