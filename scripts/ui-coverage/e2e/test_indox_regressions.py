#!/usr/bin/env python3
"""
test_indox_regressions.py — the six INDOX regressions the owner has specifically complained
about, each driven through the real UI and checked against the backend:

  F. table pagination past page 1 — row IDs differ between page 1 and page 2
  G. inline STATUS -> ACTION_RESTART persists AND the state machine acts on it
  H. month navigation matches a direct SQL COUNT
  I. server-side filter/sort (request body actually changes, not client-side only)
  J. card view degrades gracefully (missing thumbnail, long title)
  K. the document page renders honest empty/error states, never raw JSON, in DocumentStage

Ported from (not duplicating) the existing manual probes scripts/ui-coverage/_regression_probe.py
and scripts/ui-coverage/_status_edit_probe.py, which already proved these selectors work live —
this file turns that into real, asserting, cleanup-safe Suite checks navigated through the
console (never the container-IP shortcut those probes use) so it's a genuine UI test.

Run:
    python3 scripts/ui-coverage/e2e/test_indox_regressions.py
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Suite, new_browser, new_context, open_console_module, psql_one, poll_until, ARTIFACTS  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

# These suites print Hebrew document text. On a host whose stdout is not already UTF-8 that
# raises UnicodeEncodeError on the first Hebrew character, and the traceback reads as a
# test failure rather than an encoding one. Same guard the gates use. (G10)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


REPO = "incoming-documents-main"


def grid_first_row_id(fl):
    """The ID of the grid's first row.

    This used to return `JSON.stringify(s[0]).slice(0,300)` and F compared THAT between pages.
    RevoGrid's row objects carry 106 columns whose keys serialise in alphabetical order, and the
    alphabetically-first ~30 (ACTION_LOG, AI_*, ALSO_SEEN_AS, API_TOOLS_*, BASE_EXTRACTION_*, BS_*)
    are null on essentially every row — so the first 300 characters were an identical run of
    `"KEY":null,` for ANY two rows and the comparison could never fail, no matter how broken
    pagination was. Measured live 2026-08-11: page 1 -> ['doc_msof4muk8m5klm', ...], page 2 ->
    ['doc_msm7eso8pcbaq8', ...] — genuinely different rows that the old helper reported as equal.
    Returning the real ID is what F's own label ("page 2's first row id differs from page 1's")
    always claimed to be testing, and matches how check_g/check_k already read the same grid."""
    return fl.locator("revo-grid").first.evaluate(
        "g => { const s = g && g.source; return s && s.length ? (s[0].ID || s[0].id) : null; }"
    )


def grid_rows(fl):
    return fl.locator("revo-grid").first.evaluate("g => (g && g.source && g.source.length) || 0")


def open_documents(pg, reset: bool = True):
    """'מסמכים' is a TOP-LEVEL nav link (App.tsx SECTIONS, one row of the shared side menu
    `.side.bnv .bnv-item` -> /documents),
    not a `.subnav .stab` sub-tab — an earlier version of this used the wrong selector level and
    every check below it failed identically (the app was still sitting on the dashboard route).
    See test_indox.py's `goto_section()` docstring for the same distinction.

    `reset=True` (default) also puts the page back into a KNOWN state, which this helper did not
    do before and which silently broke every check that ran after check_i. `open_gated()` navigates
    to the same `console.localhost:8000/#/m/incoming` URL the page is already on, so the browser
    treats it as a same-document navigation and the embedded app is never reloaded: check_i types
    'קישור' into the table search, and that React state (BinaTable's `q` — component state, not
    localStorage) survived into check_j and check_k, which then read a grid filtered to ZERO rows
    and reported "cards rendered 0" / "could resolve a row id: False" as if the product were
    broken. Measured 2026-08-11: after check_i, search='קישור' and grid rows=0 for the rest of the
    run; 'קישור' matches 0 documents in NAME/COMPANY_NAME by direct SQL, so the empty grid was the
    app answering honestly. Each check is supposed to be independent — so make it independent."""
    fl = open_console_module(pg, "incoming", wait_ms=3200)
    fl.locator(".side.bnv .bnv-item", has_text="מסמכים").first.click(timeout=8000)
    pg.wait_for_timeout(2600)
    if reset:
        reset_documents_view(pg, fl)
    return fl


def reset_documents_view(pg, fl, budget_s: float = 25.0):
    """Clear anything a previous check left on the documents page (table search, card view) and
    wait for the grid to actually repopulate. Drives the real controls — no state is faked."""
    try:
        back = fl.locator(".bt-viewtoggle button", has_text="טבלה")
        if back.count():
            back.first.click(timeout=6000)
            pg.wait_for_timeout(600)
    except Exception:
        pass
    try:
        search = fl.locator("input.bt-search").first
        if search.count() and (search.input_value() or "").strip():
            search.fill("")
            pg.wait_for_timeout(900)
    except Exception:
        pass
    # and back to 'all months' — check_h selects a month bucket, which is server-side state on the
    # same page and would otherwise narrow the corpus for every check that follows it.
    try:
        chips = fl.locator("button.bt-chip")
        if chips.count() > 1:
            chips.first.click(timeout=6000)
            pg.wait_for_timeout(800)
    except Exception:
        pass
    deadline = time.time() + budget_s
    while time.time() < deadline:
        try:
            if grid_rows(fl) > 0:
                return True
        except Exception:
            pass
        pg.wait_for_timeout(500)
    return False


def click_pgbtn(pg, fl, glyph: str, expect_change_from: str | None, tries: int = 3):
    """Click a pagination button and WAIT FOR THE EFFECT (the grid's first row id changing),
    retrying the click if it was swallowed. Returns the new first-row id, or None.

    Uses dispatch_event('click') rather than Locator.click(). RevoGrid's absolutely-positioned
    cell layer intermittently sits over the pagination bar, so Playwright's actionability check
    reports `<div class="rgCell bt-editable"> ... intercepts pointer events` and the click times
    out after 8s — check_f raised TimeoutError on 2 of 4 observed runs (2026-08-11). `force=True`
    is NOT the fix: it only skips Playwright's own check, the synthesised mouse event still lands
    on whatever element is topmost, so the grid cell ate it and the page never turned (measured —
    first row id unchanged after a forced click). dispatch_event delivers the event to the button
    itself and paginated on every attempt.

    NOTE this is a workaround for a genuine, if minor, UI defect: `document.elementFromPoint()` at
    the '›' button's own centre returned `DIV.rgCell` (not the button) in one measured state, i.e.
    a real user's click can land on the grid instead of the button. Reported, not silenced —
    see the lane report. The assertion below is unchanged: the ids must genuinely differ."""
    btn = fl.locator(".bt-pgbtn", has_text=glyph).first
    for _ in range(tries):
        try:
            btn.dispatch_event("click")
        except Exception:
            return None
        for _ in range(20):
            pg.wait_for_timeout(500)
            now = grid_first_row_id(fl)
            if now and now != expect_change_from:
                return now
    return grid_first_row_id(fl)


def check_f_pagination(pg, s: Suite):
    fl = open_documents(pg)
    page1 = poll_until(lambda: grid_first_row_id(fl), tries=10, interval_s=1.0)
    nxt = fl.locator(".bt-pgbtn", has_text="›")
    if nxt.count() == 0:
        s.check("F/pagination: next-page control present", False, "no .bt-pgbtn '›' found")
        return
    page2 = click_pgbtn(pg, fl, "›", page1)
    s.check("F/pagination: page 2's first row id differs from page 1's",
            bool(page1) and bool(page2) and page1 != page2, f"p1={page1} p2={page2}")
    prev = fl.locator(".bt-pgbtn", has_text="‹")
    if prev.count():
        back = click_pgbtn(pg, fl, "‹", page2)
        s.check("F/pagination: '‹' returns to the page-1 row set",
                bool(back) and back == page1, f"p1={page1} back={back}")


def check_g_action_restart(pg, s: Suite):
    fl = open_documents(pg)
    sel = fl.locator("select.bt-enumcell")
    count = 0
    for attempt in range(15):
        count = sel.count()
        if count:
            break
        pg.wait_for_timeout(500)
    if count == 0:
        s.check("G/status-restart: STATUS enum cell reachable", False, "no select.bt-enumcell")
        return
    row_id = fl.locator("revo-grid").first.evaluate(
        "g => { const s = g && g.source; return s && s.length ? (s[0].ID || s[0].id) : null; }")
    before_val = sel.first.input_value()
    sel.first.select_option("ACTION_RESTART")
    pg.wait_for_timeout(2000)

    db_val = None
    if row_id:
        db_val = poll_until(
            lambda: psql_one(f"SELECT \"STATUS\" FROM public.incoming_documents "
                              f"WHERE \"ID\" = '{row_id}';"),
            tries=8, interval_s=1.0)
    s.check("G/status-restart: PATCH persisted ACTION_RESTART in Postgres",
            db_val == "ACTION_RESTART", f"before={before_val} db={db_val} id={row_id}")

    # survives a real reload. 'מסמכים' is a TOP-LEVEL menu row (`.side.bnv .bnv-item`), never a
    # `.subnav .stab` — this line asked for the sub-tab level (the very confusion this module's
    # open_documents() docstring warns about), so after the reload it could only ever time out
    # and drop the whole check into run()'s "completed without crashing" catch-all.
    # A full reload restarts the console SPA, the Authentik forward-auth hop and the embedded app.
    # The old code allowed a flat 2.5s + 2.2s for all of that and then read the value once; a
    # first paint alone measured ~10s on this host, so it read an empty page and reported None.
    # Reuse open_documents(), which is the same settle/hydrate path every other check in this file
    # depends on — a reload followed by a fresh open is still a reload.
    pg.reload()
    try:
        fl2 = open_documents(pg)
        reloaded = grid_rows(fl2) > 0
    except Exception as e:
        fl2 = pg.frame_locator("iframe")
        reloaded = False
        print(f"  WARN  reload path: {type(e).__name__}: {e}")
    # Read the value of the ROW WE EDITED, from the app's own re-fetched data. The old assertion
    # read `sel2.first.input_value()` — the first row of whatever order the reloaded grid came
    # back in, which is only the edited row by coincidence: this is a live table under a running
    # pipeline, and rows are inserted/reordered between the edit and the reload. Scoping to
    # `row_id` is what "the value survives a reload" actually means.
    #
    # The assertion is "the reloaded UI shows what is actually stored", NOT the literal string
    # 'ACTION_RESTART'. Persistence was already proven against Postgres above; what a reload adds
    # is that the grid re-reads the backend instead of serving a stale client cache. Pinning it to
    # 'ACTION_RESTART' would make it a race the test cannot win: ACTION_RESTART is a signal the
    # engine is meant to consume, and it does — this same run watched the pickup move this row off
    # ACTION_RESTART on its own. A test that fails when the product does its job correctly is
    # testing the wrong thing.
    def ui_value():
        if not (reloaded and row_id):
            return None
        return fl2.locator("revo-grid").first.evaluate(
            "(g, id) => { const s = g && g.source; if (!s) return null;"
            " const r = s.find(x => (x.ID || x.id) === id); return r ? (r.STATUS ?? null) : 'ROW_NOT_ON_PAGE'; }",
            row_id)

    def db_value():
        return psql_one(f"SELECT \"STATUS\" FROM public.incoming_documents WHERE \"ID\" = '{row_id}';")

    after_reload, stored = None, None
    for _ in range(10):
        after_reload, stored = ui_value(), db_value()
        if after_reload is not None and after_reload == stored:
            break
        pg.wait_for_timeout(1000)
    s.check("G/status-restart: value survives a page reload (UI re-reads stored STATUS)",
            after_reload is not None and after_reload == stored,
            f"row={row_id} ui={after_reload} db={stored} gridReloaded={reloaded}")

    if row_id:
        acted = poll_until(
            lambda: (psql_one(f"SELECT \"STATUS\" FROM public.incoming_documents "
                               f"WHERE \"ID\" = '{row_id}';") or "") != "ACTION_RESTART",
            tries=40, interval_s=8.0)
        final_status = psql_one(f"SELECT \"STATUS\" FROM public.incoming_documents "
                                 f"WHERE \"ID\" = '{row_id}';")
        s.check("G/status-restart: the state machine acted on it (STATUS moved on)",
                bool(acted), f"final STATUS={final_status}")


_HE_MONTHS = {
    "ינואר": 1, "פברואר": 2, "מרץ": 3, "מרס": 3, "אפריל": 4, "מאי": 5, "יוני": 6,
    "יולי": 7, "אוגוסט": 8, "ספטמבר": 9, "אוקטובר": 10, "נובמבר": 11, "דצמבר": 12,
}

# A FAITHFUL SQL re-implementation of the backend's own `_month_key_of()`
# (apps/indox/app/incoming_documents/api/__init__.py): a DOC_DATE buckets by its ISO prefix
# `YYYY-MM`, OR by `D/M/YY(YY)` (2-digit years => 20YY), with month 1-12 and year 1990-2100;
# anything else is "no date". The version this check used before —
# `substring("DOC_DATE" from 1 for 7)` — only ever matched the ISO form, and on the live corpus
# (measured 2026-08-11) that is 5,345 of 22,641 rows: it reported 25 for 2026-12 where both the
# app and the real data say 28. Verified against three independent buckets before being used
# here: 2026-12 -> 28, 2094-07 -> 1, and the whole table -> 22,641, each matching the UI's own
# chip exactly.
_MONTH_KEY_CTE = (
    "WITH m AS (SELECT \"DOC_DATE\" AS d, regexp_match(\"DOC_DATE\", "
    "'^([0-9]{1,2})[./]([0-9]{1,2})[./]([0-9]{2}|[0-9]{4})$') AS dm "
    "FROM public.incoming_documents), "
    "k AS (SELECT CASE "
    "WHEN d ~ '^[0-9]{4}-[0-9]{2}' "
    "AND (substring(d from 1 for 4))::int BETWEEN 1990 AND 2100 "
    "AND (substring(d from 6 for 2))::int BETWEEN 1 AND 12 "
    "THEN substring(d from 1 for 7) "
    "WHEN dm IS NOT NULL AND dm[1]::int BETWEEN 1 AND 31 AND dm[2]::int BETWEEN 1 AND 12 "
    "AND (CASE WHEN length(dm[3])=2 THEN ('20'||dm[3])::int ELSE dm[3]::int END) "
    "BETWEEN 1990 AND 2100 "
    "THEN lpad((CASE WHEN length(dm[3])=2 THEN ('20'||dm[3])::int ELSE dm[3]::int END)::text,4,'0')"
    "||'-'||lpad((dm[2]::int)::text,2,'0') "
    "ELSE NULL END AS mk FROM m) "
)


def sql_month_count(key: str):
    return psql_one(_MONTH_KEY_CTE + f"SELECT count(*) FROM k WHERE mk = '{key}';")


def parse_month_chip(label: str):
    """('YYYY-MM' | None, count | None) for a chip like 'דצמבר 2026 28' / 'כל החודשים 22,641'.

    The labels are produced by `toLocaleDateString('he-IL', {year:'numeric', month:'long'})`, i.e.
    a Hebrew month NAME plus a year — there is no numeric month and no separator in them at all.
    The regex this check used before (`(20\\d{2})[.\\-/](\\d{1,2})|...`) required a `.`/`-`/`/`
    between the two numbers, so it could not match any real chip and H had never once compared a
    UI number to a SQL number — it only ever reported its own parse failure."""
    mo = yr = cnt = None
    for tok in label.split():
        t = tok.strip()
        if t in _HE_MONTHS:
            mo = _HE_MONTHS[t]
        elif re.fullmatch(r"\d{4}", t) and yr is None and 1990 <= int(t) <= 2100:
            yr = int(t)
        elif re.fullmatch(r"[\d,]+", t):
            cnt = int(t.replace(",", ""))
    return (f"{yr:04d}-{mo:02d}" if (mo and yr) else None), cnt


def check_h_month_nav(pg, s: Suite):
    fl = open_documents(pg)
    chips = fl.locator("button.bt-chip")
    # The month index is a SEPARATE backend aggregate, not part of the grid's own query — measured
    # 2026-08-11 at ~4.3s after the page renders, during which exactly one placeholder chip
    # ('כל החודשים 0') is mounted. Reading the strip without waiting for it is how this check saw
    # a single 0-count chip and drew conclusions from it.
    labels = []
    for _ in range(60):
        labels = [chips.nth(i).inner_text().strip() for i in range(chips.count())]
        if len(labels) > 1:
            break
        pg.wait_for_timeout(500)
    if len(labels) <= 1:
        s.check("H/month-nav: month index populated (more than the 'all' chip)", False, labels)
        return

    # H1 — the 'all months' chip must agree with a plain COUNT(*).
    all_key, all_cnt = parse_month_chip(labels[0])
    total = psql_one("SELECT count(*) FROM public.incoming_documents;")
    s.check("H/month-nav: 'all months' chip total == SQL COUNT(*)",
            all_key is None and all_cnt is not None and total == str(all_cnt),
            f"chip={labels[0]!r} -> {all_cnt} vs sql={total}")

    # H2 — a real month bucket's advertised count must equal a direct SQL COUNT for that month.
    # Prefer a bucket that fits inside one 50-row page so H3 below can compare exactly.
    cands = []
    for i, lab in enumerate(labels):
        key, cnt = parse_month_chip(lab)
        if key and cnt and cnt <= 45:
            cands.append((cnt, i, key, lab))
    if not cands:
        s.check("H/month-nav: a real month chip small enough to verify exists", False, labels[:6])
        return
    cnt, idx, key, label = max(cands)
    sql_count = sql_month_count(key)
    s.check(f"H/month-nav: chip {label!r} ({key}) count == SQL COUNT for that month",
            sql_count == str(cnt), f"chip={cnt} sql={sql_count}")

    # H3 — and CLICKING it must actually show those documents. This is the check's whole point:
    # a bucket you cannot open is not month navigation. Kept as a real assertion even though it
    # currently fails on a genuine product defect (the index counts D/M/YYYY dates, the filter
    # sends `startswith 'YYYY-MM'` against the raw string and cannot match them) — see the lane
    # report. Loosening it would hide ~8,039 documents that month navigation counts but will not
    # open.
    chips.nth(idx).click(timeout=8000)
    shown = None
    for _ in range(40):
        pg.wait_for_timeout(500)
        shown = grid_rows(fl)
        if shown == cnt:
            break
    s.check(f"H/month-nav: clicking {label!r} shows the {cnt} documents it advertises",
            shown == cnt, f"chip advertises {cnt}, grid shows {shown} (key={key})")
    # leave the strip on 'all months' so the checks after this one see the whole corpus
    try:
        chips.first.click(timeout=6000)
        pg.wait_for_timeout(800)
    except Exception:
        pass


def check_i_server_side(pg, s: Suite):
    fl = open_documents(pg)
    seen = []

    def on_req(req):
        if "documents/query" in req.url and req.method == "POST":
            seen.append(req.post_data or "")

    pg.on("request", on_req)
    search = fl.locator("input.bt-search")
    if search.count():
        search.click()
        search.fill("קישור")
        pg.wait_for_timeout(1800)
    header = fl.locator(".header-content").first
    if header.count():
        header.click()
        pg.wait_for_timeout(1200)
    pg.remove_listener("request", on_req)
    s.check("I/server-side filter+sort: search/sort actually issued a documents/query POST",
            len(seen) > 0, len(seen))
    if seen:
        has_filter_or_sort = any(('"filter"' in b or '"order"' in b or '"search"' in b) for b in seen)
        s.check("I/server-side filter+sort: request body actually carries filter/sort/search",
                has_filter_or_sort, seen[-1][:200])


def check_j_card_view(pg, s: Suite):
    fl = open_documents(pg)
    toggle = fl.locator(".bt-viewtoggle button", has_text="כרטיסים")
    if toggle.count() == 0:
        s.check("J/card-view: view toggle present", False, "no .bt-viewtoggle 'כרטיסים' button")
        return
    toggle.first.click(timeout=8000)
    cards = fl.locator(".bt-card-item")
    # wait for the card list to mount rather than sampling it once at a fixed 1.8s
    for _ in range(30):
        if cards.count():
            break
        pg.wait_for_timeout(500)
    s.check("J/card-view: cards rendered", cards.count() > 0, cards.count())
    if cards.count():
        placeholders = fl.locator(".bt-card-thumb-ph")
        # graceful degrade = EITHER every card has a real thumb, OR the ones missing one show the
        # placeholder glyph — never a raw broken-image / blank box. We can't force a doc to lack a
        # thumbnail here without seeding one, so this asserts the NEGATIVE: no native broken-image
        # icons ever appear (browser sets an `img` a natural size of 0 with alt text showing).
        broken = fl.locator(".bt-card-thumb img").evaluate_all(
            "els => els.filter(e => e.complete && e.naturalWidth === 0).length")
        s.check("J/card-view: no broken native <img> glyphs in card thumbnails",
                broken == 0, broken)
        titles_ok = fl.locator(".bt-card-title").evaluate_all(
            "els => els.every(e => e.textContent && e.textContent.trim().length > 0)")
        s.check("J/card-view: every card has a non-empty title", bool(titles_ok))
    back = fl.locator(".bt-viewtoggle button", has_text="טבלה")
    if back.count():
        back.first.click(timeout=8000)


def check_k_honest_states(pg, s: Suite):
    fl = open_documents(pg)
    row_id = poll_until(lambda: grid_first_row_id(fl), tries=20, interval_s=1.0)
    if not row_id:
        s.check("K/document-page: could resolve a row id to open", False,
                f"grid rows={grid_rows(fl)}")
        return
    # Open the document THE WAY THE UI DOES: a single click on the ID cell. DocumentBrowserPage's
    # `onRowClick` navigates only from the primary-key column ("editable grid: open only from the
    # ID (link-styled) column"), so this is the product's own path to the detail page.
    #
    # This previously did `window.location.hash = '#/document/' + id`, which could never work and
    # silently left the suite on the LIST page — every assertion below it then failed against the
    # wrong screen (observed 2026-08-11: the "DocumentViewer card found" failure dumped the
    # documents list, "שורות: 22641", not a document). Two independent reasons: main.tsx mounts a
    # BrowserRouter (a MemoryRouter only in the `about:srcdoc` case), so routing is by PATH and a
    # fragment is not a route at all; and the route is `/repos/:repo/documents/:id` (App.tsx),
    # not the `/document/:id` this comment used to claim.
    # Address the cell by its COLUMN INDEX, not by its text: RevoGrid virtualises columns and
    # renders no column name into the DOM (a cell carries only `data-rgcol`/`data-rgrow`), and
    # matching on the id string alone missed it.
    col = fl.locator("revo-grid").first.evaluate(
        "g => { const cols = (g && g.columns) || [];"
        " const i = cols.findIndex(c => (c.prop || c.name) === 'ID');"
        " return { idx: i, props: cols.map(c => c.prop || c.name).slice(0, 12) }; }")
    cell = None
    if col and col.get("idx", -1) >= 0:
        cell = fl.locator(f'.rgCell[data-rgrow="0"][data-rgcol="{col["idx"]}"]').first
    if cell is None or cell.count() == 0:
        s.check("K/document-page: the row's ID cell is clickable in the grid", False,
                f"row={row_id} columnIndex={col}")
        return
    cell.click(timeout=8000)
    viewer_ready = False
    for _ in range(40):
        pg.wait_for_timeout(500)
        if fl.locator(".stage-sources .stab", has_text="חילוץ מסומן").count():
            viewer_ready = True
            break

    body = fl.locator("body").inner_text()
    # scope to the document STAGE only (identified by its source-tab labels), not the whole
    # page — the change-history panel is DELIBERATELY a raw JSON dump and must not be flagged.
    # [2026-09-02] The card is DocumentStage now, and its tab row is `.stage-sources`, not the
    # settings-page `.subnav` the old viewer borrowed. Selecting on the old class silently
    # matched nothing, which this check would have reported as "card not found" on a perfectly
    # good screen.
    viewer = fl.locator(".doc-stage")
    if viewer.count() == 0:
        s.check("K/document-page: document stage found on the detail page", False,
                f"viewerReady={viewer_ready} url={pg.url} body={body[:160]!r}")
        return
    vtext = viewer.first.inner_text()
    looks_like_raw_json = vtext.strip().startswith("{") or '"error"' in vtext
    s.check("K/document-page: viewer shows an honest state, not a raw JSON/error dump",
            not looks_like_raw_json, vtext[:200])
    broken_imgs = viewer.first.locator("img").evaluate_all(
        "els => els.filter(e => e.complete && e.naturalWidth === 0).length")
    s.check("K/document-page: no broken native <img> in the viewer", broken_imgs == 0, broken_imgs)


def run(pg) -> Suite:
    s = Suite("indox-regressions")
    for fn in (check_f_pagination, check_g_action_restart, check_h_month_nav,
               check_i_server_side, check_j_card_view, check_k_honest_states):
        try:
            fn(pg, s)
        except Exception as e:
            s.check(f"{fn.__name__} completed without crashing", False, f"{type(e).__name__}: {e}")
    return s


def main():
    with sync_playwright() as p:
        browser = new_browser(p)
        ctx = new_context(browser)
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        try:
            s = run(pg)
        except Exception as e:
            pg.screenshot(path=str(ARTIFACTS / "indox_regressions_fail.png"))
            print(f"  FAIL  indox-regressions/suite crashed — {type(e).__name__}: {e}")
            browser.close()
            sys.exit(1)
        browser.close()

    print(f"\n{s.summary()}")
    for n, d in s.failed_list:
        print(f"  FAILED: {n} — {d}")
    if errs:
        print(f"JS errors: {len(errs)}")
        for e in errs[:5]:
            print("   ", e[:200])
    sys.exit(1 if s.failed_list or errs else 0)


if __name__ == "__main__":
    main()
