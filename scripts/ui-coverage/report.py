#!/usr/bin/env python3
"""
report.py — turn the raw browser coverage dump into the headline number:
"what % of our view code actually ran while the mockup was being photographed".

Runs on the HOST (the container does browser work, the host does analysis). The raw dump
carries each script's SOURCE as V8 saw it, so line mapping needs no repo lookup and no
sourcemaps — which is also what makes inline <script> blocks measurable.

Emits:
    ci-artifacts/ui-code-coverage.json   summary consumed by compose_map.py
    ci-artifacts/ui-coverage.junit.xml   one testcase per view + per code file
    ci-artifacts/ui-coverage.md          scorecard for the CI step summary
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from xml.sax.saxutils import escape

import yaml

import coverage_engine as ce
import ui_regions

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = Path(__file__).resolve().parent / "manifest.yaml"

# served URL -> repo path.
#
# Two things the first attempt got wrong, both visible in the raw dump:
#   1. these Flask apps serve their static dir at the ROOT ("/app.js"), not "/static/app.js"
#   2. every embedded app is ALSO loaded through the console reverse proxy at
#      "console.<domain>/a/<name>/app.js" — so the same source file arrives under two
#      different URLs and must fold onto one repo path, or coverage gets split in half.
#
# Vanilla apps ship their source verbatim, so once the URL is right the mapping is exact.
STATIC_DIR = {          # repo dir holding the served static assets
    "console":            "platform-base/console/static",
    "my-docs":            "apps/my-docs/static",
    "drive":         "apps/drive/static",
    "mailview":           "apps/mail/mailview/static",
    "machine":            "platform-base/machine/static",
    "notifications":      "platform-base/notifications/static",
    "any-concurrency":    "apps/any-concurrency/static",
}
HOST_APP = {            # standalone hostname prefix -> app
    "console": "console", "my-docs": "my-docs", "drive": "drive",
    "mail": "mailview", "machine": "machine", "alerts-svc": "notifications",
    "any-concurrency": "any-concurrency",
    "connections": "connections",
}
PROXY_APP = {           # console /a/<name>/ -> app  (see console/app.py APP_BASES)
    "my-docs": "my-docs", "drive": "drive", "mailview": "mailview",
    "machine": "machine", "alerts": "notifications", "any-concurrency": "any-concurrency",
    "connections": "connections", "incoming": "incoming-documents", "chat": "chat",
}
# apps whose UI lives in one HTML file (inline <script>): the document URL IS the source
INLINE_DOC = {
    "connections": "platform-base/connections/ui.html",
    "notifications": "platform-base/notifications/static/index.html",
    "machine": "platform-base/machine/static/index.html",
    "any-concurrency": "apps/any-concurrency/static/index.html",
}


def to_repo_path(url: str) -> str | None:
    m = re.search(r"//([^./]+)\.[^/]*/(.*)$", url)
    if not m:
        return None
    host, path = m.group(1), m.group(2).split("?")[0]

    # console reverse-proxy: /a/<name>/<rest>
    pm = re.match(r"a/([^/]+)/?(.*)$", path)
    if host == "console" and pm:
        app, rest = PROXY_APP.get(pm.group(1)), pm.group(2)
        if not app:
            return None
        if not rest:                       # the document itself -> inline script source
            return INLINE_DOC.get(app)
        d = STATIC_DIR.get(app)
        return f"{d}/{rest}" if d else None

    app = HOST_APP.get(host)
    if not app:
        return None
    if not path or path.endswith("/"):     # document URL -> inline script
        return INLINE_DOC.get(app)
    d = STATIC_DIR.get(app)
    return f"{d}/{path}" if d else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=str(ROOT / "ci-artifacts" / "ui-raw-coverage.json"))
    ap.add_argument("--results", default=str(ROOT / "ci-artifacts" / "ui-capture-results.json"))
    ap.add_argument("--outdir", default=str(ROOT / "ci-artifacts"))
    a = ap.parse_args()

    man = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    cc = man["code_coverage"]
    acc = ce.CoverageAccumulator(include=cc["include"], exclude=cc["exclude"])

    raw = json.loads(Path(a.raw).read_text(encoding="utf-8"))
    unmapped: set[str] = set()
    for app, blob in raw.items():
        # Each take is ONE view's coverage. They're fed to the accumulator separately so
        # it ORs the computed line sets; concatenating the raw V8 ranges instead would let
        # a zero-count range from one view erase a line another view genuinely ran.
        for take in (blob.get("takes") or [blob]):
            for s in take.get("scripts", []):
                rel = to_repo_path(s["url"])
                if not rel:
                    unmapped.add(s["url"])
                    continue
                if not acc.add_js(rel, s["source"], s["functions"], view=app):
                    unmapped.add(f"(out of scope) {rel}")
            for c in take.get("css", []):
                # Resolve the stylesheet's own sourceURL to a repo path (linked style.css
                # -> STATIC_DIR/rest; inline <style> -> the app's index.html). A sheet with
                # no learned URL (constructed / added before the hook) can't be attributed.
                rel = to_repo_path(c.get("url", ""))
                if not rel:
                    if c.get("url"):
                        unmapped.add(c["url"])
                    continue
                if not acc.add_css(rel, "", c["total"], c["used"], view=app):
                    unmapped.add(f"(out of scope) {rel}")

    summary = acc.summary(threshold=float(cc.get("threshold", 100)))
    summary["unmapped_scripts"] = sorted(unmapped)[:40]
    summary["missing_states"] = ce.missing_states_report(summary)

    out = Path(a.outdir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "ui-code-coverage.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    results = json.loads(Path(a.results).read_text(encoding="utf-8"))["results"]
    cap = [r for r in results if r["status"] == "captured"]
    fp = [r for r in results if r.get("tier") == "first_party"]
    fp_cap = [r for r in fp if r["status"] == "captured"]

    # ── visible-region coverage: only what a screenshot actually SHOWED counts ──
    # Union every shot's region probe per app: a region is "shown" if ANY captured state
    # rendered it visible; regions that stayed hidden in every shot are the un-photographed
    # UI. This is stricter than code coverage — a collapsed drawer whose handlers ran is
    # still not covered until a shot displays it.
    # A component rendered once per data row (connections' 86 #ex_<cred>/#it_<cred>/#pv_<cred>
    # editors, one per credential) is ONE distinct UI element repeated, not 86. Collapse an
    # id whose "<prefix>_" is shared by >=3 distinct ids into a single component key
    # (#ex_* etc.) so the denominator counts components, and photographing one instance covers
    # it. Prefixes that occur <3 times (unique ids like #send-document-form) are left intact.
    prefix_freq: dict[str, dict[str, int]] = {}
    for r in results:
        if r["status"] != "captured":
            continue
        pf = prefix_freq.setdefault(r["app"], {})
        for reg in (r.get("regions") or []):
            k = reg.get("key") or ""
            if k.startswith("#") and "_" in k:
                pf[k.split("_", 1)[0]] = pf.get(k.split("_", 1)[0], 0) + 1

    def _norm(app: str, k: str) -> str:
        if k.startswith("#") and "_" in k:
            pre = k.split("_", 1)[0]
            if prefix_freq.get(app, {}).get(pre, 0) >= 3:
                return pre + "_*"
        return k

    # runtime side: which region keys did a shot actually render VISIBLE (union across shots).
    region_seen: dict[str, dict[str, bool]] = {}
    for r in results:
        if r["status"] != "captured":
            continue
        app = r["app"]
        d = region_seen.setdefault(app, {})
        for reg in (r.get("regions") or []):
            k = reg.get("key")
            if not k:
                continue
            k = _norm(app, k)
            d[k] = d.get(k, False) or bool(reg.get("visible"))

    # ── the metric, done like test coverage ──────────────────────────────────────────────
    # Denominator = the regions the SOURCE can render (ui_regions.py, auto-scraped), NOT the union
    # of what happened to appear. A pane that never rendered therefore stays in the denominator and
    # surfaces as an uncovered region with its source file — it can't silently vanish. Numerator =
    # source regions a shot showed visible. The reveal recipes are just "tests" that raise this.
    src_regions = ui_regions.all_regions()          # {app: {key: 'file'}}
    vis_rows, vis_tot, vis_shown, missed_by_app = [], 0, 0, {}
    for app in sorted(src_regions):
        src = src_regions[app]
        if not src:
            continue
        seen = region_seen.get(app, {})
        shown = sum(1 for k in src if seen.get(k) is True)
        tot = len(src)
        vis_tot += tot
        vis_shown += shown
        vis_rows.append((app, shown, tot))
        # a source region is a MISS if no shot showed it visible (never rendered, or only hidden)
        missed_by_app[app] = sorted(f"{k}  ({src[k]})" for k in src if seen.get(k) is not True)
    vis_pct = round(100.0 * vis_shown / vis_tot, 1) if vis_tot else None
    summary["visible_regions_pct"] = vis_pct
    summary["visible_regions"] = {"shown": vis_shown, "total": vis_tot,
                                  "by_app": {a: {"shown": s, "total": t} for a, s, t in vis_rows},
                                  "missed": missed_by_app,
                                  "denominator": "source-derived (ui_regions.py)"}
    # keep the old runtime-union numbers too, for continuity / debugging
    runtime_by_app = {a: {"shown": sum(1 for v in d.values() if v), "total": len(d)}
                      for a, d in region_seen.items()}
    summary["visible_regions_runtime"] = runtime_by_app
    (out / "ui-code-coverage.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # JUnit: one case per view, plus one per code file below threshold
    cases = []
    for r in results:
        nm = f"ui-{r['app']}-{r['id']}"
        if r["status"] == "captured":
            cases.append(f'  <testcase classname="ui-view" name="{escape(nm)}"/>')
        elif r["status"] == "skipped":
            cases.append(f'  <testcase classname="ui-view" name="{escape(nm)}">'
                         f'<skipped message="{escape(r.get("note",""))}"/></testcase>')
        else:
            cases.append(f'  <testcase classname="ui-view" name="{escape(nm)}">'
                         f'<failure message="{escape(r.get("note","not captured"))}"/></testcase>')
    for f in summary["files"]:
        nm = f"uicode-{f['path']}"
        if f["below_threshold"]:
            msg = (f"{f['js_pct']}% of view code ran ({f['covered']}/{f['executable']} lines); "
                   f"uncovered lines = states never photographed: {f['uncovered_lines'][:15]}")
            cases.append(f'  <testcase classname="ui-code" name="{escape(nm)}">'
                         f'<failure message="{escape(msg)}"/></testcase>')
        else:
            cases.append(f'  <testcase classname="ui-code" name="{escape(nm)}"/>')
    fails = sum(1 for c in cases if "<failure" in c)
    (out / "ui-coverage.junit.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<testsuites><testsuite name="ui-coverage" tests="{len(cases)}" failures="{fails}">\n'
        + "\n".join(cases) + "\n</testsuite></testsuites>\n", encoding="utf-8")

    vpct = round(100.0 * len(cap) / len(results), 1) if results else 0
    fpct = round(100.0 * len(fp_cap) / len(fp), 1) if fp else 0
    md = [
        "## UI coverage",
        "",
        "Two coverage numbers, both auto-derived from source (like test coverage) and counting only "
        "UI that was actually **visible in the map** — not a hand-written list of views:",
        "",
        f"| metric (source-derived denominator) | value |",
        f"|---|---|",
        (f"| **visible-region coverage** — source regions shown in the map | **{vis_pct}%** "
         f"({vis_shown}/{vis_tot} regions) |"
         if vis_pct is not None else ""),
        f"| **view-code coverage (JS)** — view-code lines that ran while shot | **{summary['overall_js_pct']}%** "
        f"({summary['covered_lines']}/{summary['executable_lines']} lines) |",
        (f"| view-code coverage (CSS bytes) | **{summary['overall_css_pct']}%** "
         f"({summary['css_rules_used']}/{summary['css_rules_total']} bytes) |"
         if summary.get('overall_css_pct') is not None
         else "| view-code coverage (CSS bytes) | _n/a — no first-party stylesheet mapped_ |"),
        "",
        f"_capture health (diagnostic, not the coverage metric): {len(cap)}/{len(results)} declared "
        f"views photographed ({vpct}%); first-party {len(fp_cap)}/{len(fp)} ({fpct}%)._",
        "",
        "### Visible-region coverage by app — source regions never shown in the map",
        "",
        "Every entry is a real UI region the source can render that no screenshot displayed — the "
        "auto worklist. `(file)` is where it lives; drive it visible with a reveal recipe to close it.",
        "",
        "| app | shown/total | source regions never shown (file) |",
        "|---|---|---|",
    ]
    for app, s, t in vis_rows:
        miss = missed_by_app.get(app, [])
        md.append(f"| {app} | {s}/{t} | {', '.join('`'+h+'`' for h in miss[:8])}"
                  f"{' …' if len(miss) > 8 else ''} |")
    md += [
        "",
        "### View code by file",
        "",
        "| file | JS % | lines | seen in |",
        "|---|---|---|---|",
    ]
    for f in summary["files"]:
        md.append(f"| `{f['path']}` | {f['js_pct']}% | {f['covered']}/{f['executable']} | "
                  f"{', '.join(f['seen_in'][:4])} |")
    if summary["missing_states"]:
        md += ["", "### Un-photographed states (uncovered render branches)", ""]
        for m in summary["missing_states"][:8]:
            md.append(f"**`{m['path']}`** ({m['js_pct']}%)")
            for c in m["candidates"][:5]:
                md.append(f"- L{c['line']}: `{c['code']}`")
    (out / "ui-coverage.md").write_text("\n".join(md), encoding="utf-8")

    css_txt = f"{summary['overall_css_pct']}% CSS" if summary.get('overall_css_pct') is not None else "CSS n/a"
    vis_txt = f" | visible-regions {vis_pct}% ({vis_shown}/{vis_tot})" if vis_pct is not None else ""
    print(f"views {len(cap)}/{len(results)} ({vpct}%) | first-party {len(fp_cap)}/{len(fp)} "
          f"({fpct}%) | UI-code {summary['overall_js_pct']}% JS {css_txt}{vis_txt}")
    if summary["unmapped_scripts"]:
        print(f"  note: {len(summary['unmapped_scripts'])} script URL(s) not mapped to repo paths")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
