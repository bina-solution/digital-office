#!/usr/bin/env python3
"""
test_indox.py — INDOX core E2E: add a sync registry entry, upload a file into the watched
drive folder and watch it processed to COMPLETED, exercise settings, add a company, and drive
the sync board (run / pause / edit / delete), each verified against the backend.

Navigation is always through console.localhost (never incoming-documents.localhost/drive.localhost
directly). Auth is the shared Authentik flow in common.py. All backend checks go straight at
Postgres (public.incoming_documents / public.companies / public.settings on supabase-db) — the
same tables apps/indox/hooks/test.py and the app itself use — not a re-read of the UI's own DOM.

Run:
    python3 scripts/ui-coverage/e2e/test_indox.py
Cleanup:
    python3 scripts/ui-coverage/e2e/cleanup.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    Suite, new_browser, new_context, open_console_module, psql, psql_one, qa_name, QA_TAG,
    poll_until, ARTIFACTS,
)
from playwright.sync_api import sync_playwright  # noqa: E402

# These suites print Hebrew document text. On a host whose stdout is not already UTF-8 that
# raises UnicodeEncodeError on the first Hebrew character, and the traceback reads as a
# test failure rather than an encoding one. Same guard the gates use. (G10)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


REPO = "incoming-documents-main"

# Boolean settings that gate live document extraction. This suite must never leave one of these
# off: flipping either stalls the pipeline these tests share with production traffic.
EXTRACTION_KILLSWITCHES = {"extraction_ai_enabled", "extraction_local_enabled"}


def q(v: str) -> str:
    return v.replace("'", "''")


def setting_value(key: str):
    return psql_one(f"SELECT value FROM public.settings WHERE key = '{q(key)}';")


def doc_status(name: str):
    return psql_one(f"SELECT \"STATUS\" FROM public.incoming_documents "
                     f"WHERE \"NAME\" = '{q(name)}' ORDER BY created_at DESC LIMIT 1;")


def sync_registry_names():
    out = psql("SELECT value FROM public.settings WHERE key='sync_registry';").strip()
    if not out:
        return []
    try:
        arr = json.loads(out)
        return [e.get("name") for e in arr if isinstance(e, dict)]
    except Exception:
        return []


def company_row(mzhe1: str):
    out = psql(f"SELECT \"שם חברה\" FROM public.companies WHERE \"מזהה 1\" = '{q(mzhe1)}' "
               f"ORDER BY created_at DESC LIMIT 1;").strip()
    return out or None


def click_confirm(pg, locator):
    """Some sync-board actions (delete) fire a native window.confirm()."""
    pg.once("dialog", lambda d: d.accept())
    locator.click(timeout=8000)


def close_stray_modal(pg, fl):
    """Same rationale as test_drive.py's helper: one section's failed write can leave a
    drawer/modal open and block every click after it — clear it before moving on."""
    try:
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(300)
    except Exception:
        pass


def goto_section(pg, fl, label, wait=2400):
    """Click a TOP-LEVEL nav link (the shared side menu's row, `.side.bnv .bnv-item`, e.g.
    'הגדרות' -> /settings,
    'סנכרון' -> /sync) — NOT the inner `.subnav .stab` sub-tabs those pages render once loaded.
    Both settings sub-tabs (הגדרות מערכת / חברות) live under /settings; the sync-registry drawer
    and sync board both live under /sync's own 'מקורות' sub-tab. Conflating the two levels was a
    real bug in an earlier version of this suite (every section failed identically because the
    app was still sitting on the dashboard route, which has no `.subnav` at all)."""
    # the top-level nav is the SHARED side menu now (bina-nav): `.side .bnv-item`, one row per
    # SECTIONS entry. `.tabstrip nav .tab` is gone from the DOM — these suites kept clicking a
    # class the app had stopped rendering, which is a test that fails for the wrong reason.
    fl.locator(".side.bnv .bnv-item", has_text=label).first.click(timeout=8000)
    pg.wait_for_timeout(wait)


def run(pg) -> Suite:
    s = Suite("indox")

    # ── C. settings ───────────────────────────────────────────────────────────
    fl = open_console_module(pg, "incoming", wait_ms=3200)
    s.check("incoming-documents app loads", fl.locator("body").inner_text().strip() != "")

    def tab(label, wait=2200):
        fl.locator(".subnav .stab", has_text=label).first.click(timeout=8000)
        pg.wait_for_timeout(wait)

    try:
        goto_section(pg, fl, "הגדרות")
        tab("הגדרות מערכת")
        switches = fl.locator("button.switch")
        # SettingsPage renders `{!loading && section === 'system' && ...}`, so the whole card is
        # absent until the settings fetch resolves. `tab()` waits a flat 2.2s and this read the
        # count once, immediately after — under live load that lands before the fetch returns and
        # reported "no button.switch found" for a page that has three of them
        # (activePrioritySync / extraction_ai_enabled / extraction_local_enabled, confirmed live
        # 2026-08-11). Wait for the control instead of guessing how long the backend will take.
        for _ in range(30):
            if switches.count():
                break
            pg.wait_for_timeout(500)
        if switches.count():
            # WHICH switch: every boolean setting renders the same `button.switch` with
            # aria-label={row.key} (SettingsPage.tsx), and on this deployment two of the three
            # boolean settings are `extraction_ai_enabled` / `extraction_local_enabled` — the live
            # extraction kill-switches. `switches.first` picked whichever the page happened to
            # render first, so this check could turn extraction OFF on a running pipeline; and
            # because the restoring click sat AFTER the assertion with no `finally`, any failure
            # between the two clicks (a timeout, a failed re-read) left it off permanently.
            # Toggling a switch is what's under test, not which key it belongs to, so prefer one
            # that cannot stall the pipeline, and restore + verify unconditionally.
            n = switches.count()
            keys = [(switches.nth(i).get_attribute("aria-label") or "") for i in range(n)]
            order = sorted(range(n), key=lambda i: keys[i] in EXTRACTION_KILLSWITCHES)
            idx = order[0]
            sw, key = switches.nth(idx), keys[idx]
            before_db = setting_value(key) if key else None
            before_cls = sw.get_attribute("class") or ""
            was_on = "on" in before_cls.split()
            try:
                sw.click(timeout=6000)
                # the button restyles only after its own save round-trip resolves; under live
                # pipeline load that took longer than the flat 900ms this used to allow, so the
                # class was read before it flipped even though the value did reach Postgres
                now_on = was_on
                for _ in range(24):
                    pg.wait_for_timeout(500)
                    now_on = "on" in (sw.get_attribute("class") or "").split()
                    if now_on != was_on:
                        break
                after_cls = sw.get_attribute("class") or ""
                s.check("settings switch toggles", now_on != was_on,
                        f"[{key}] {before_cls} -> {after_cls}")
                # and it must actually reach public.settings, not just restyle the button
                if key and before_db is not None:
                    flipped = poll_until(
                        lambda: setting_value(key) != before_db, tries=8, interval_s=1.0)
                    s.check("settings switch persisted to public.settings", bool(flipped),
                            f"[{key}] before={before_db} after={setting_value(key)}")
            finally:
                # put it back whatever happened above, and PROVE it went back
                try:
                    if (sw.get_attribute("class") or "").split().count("on") != int(was_on):
                        sw.click(timeout=6000)
                        pg.wait_for_timeout(900)
                except Exception as e:
                    print(f"  WARN  could not click {key} back: {type(e).__name__}: {e}")
                if key and before_db is not None:
                    restored = poll_until(
                        lambda: setting_value(key) == before_db, tries=10, interval_s=1.0)
                    s.check("settings switch restored to its original value", bool(restored),
                            f"[{key}] wanted={before_db} now={setting_value(key)}")
        else:
            s.check("settings switches are present", False, "no button.switch found")
    except Exception as e:
        s.check("settings section completed without crashing", False, f"{type(e).__name__}: {e}")
    finally:
        close_stray_modal(pg, fl)

    # ── D. add a company ─────────────────────────────────────────────────────
    mzhe1 = "900000001"
    try:
        goto_section(pg, fl, "הגדרות")
        tab("חברות")
        mzhe1 = QA_TAG.replace("QA_E2E_", "").replace("_", "")[:9]  # digits/letters, kept short
        mzhe1 = "".join(c for c in mzhe1 if c.isdigit()) or "900000001"
        company_name = qa_name("company")

        add_btn = fl.locator("button.btn", has_text="הוסף שורה")
        s.check("add-company button present", add_btn.count() > 0)
        if add_btn.count():
            add_btn.first.click(timeout=8000)
            pg.wait_for_timeout(1200)
            # '＋ הוסף שורה' opens <NewRowDrawer> — the record is typed BEFORE it exists,
            # so there is no blank row to hunt for and nothing to type into by position.
            # (Until 2026-09-02 this leg drove the opposite flow: the button POSTed an
            # empty seed, the server refused it for carrying no `instance`, the client
            # read only `ok` and dropped the error, and the button did nothing at all.
            # Both halves are fixed — the POST is instance-scoped and a refusal now
            # surfaces in the drawer — so the guard that used to refuse to type into
            # row 0 has no job left to do.)
            drawer = fl.locator(".drawer-ov")
            s.check("add-company drawer opened", drawer.count() > 0)
            if drawer.count():
                # fields carry their COLUMN KEY in `data-key` — an addressable selector,
                # unlike the positional cell coordinates this leg used to guess at
                for key, value in (("שם חברה", company_name), ("מזהה 1", mzhe1)):
                    fld = drawer.locator(f'input[data-key="{key}"]')
                    if fld.count() == 0:
                        s.check(f"add-company: field {key!r} present in drawer", False)
                        continue
                    fld.first.fill(value, timeout=6000)
                save = drawer.locator("button", has_text="הוסף").last
                # the button is disabled until every required field is filled and every
                # validator passes — a disabled button here means the form rejected our
                # input, which is a finding, not a reason to keep clicking
                s.check("add-company: save enabled once the record is valid",
                        save.count() > 0 and save.first.is_enabled())
                if save.count() and save.first.is_enabled():
                    save.first.click(timeout=8000)
                    pg.wait_for_timeout(1500)
                # a save that failed leaves the drawer OPEN with the server's message in it
                if drawer.count() and drawer.first.is_visible():
                    bad = drawer.locator(".callout.bad")
                    s.check("add-company: drawer closed after save", False,
                            bad.first.inner_text() if bad.count() else "drawer still open")

        got = poll_until(lambda: company_row(mzhe1), tries=10, interval_s=1.5)
        s.check("new company persisted in public.companies", got is not None, got)
    except Exception as e:
        s.check("add-company section completed without crashing", False, f"{type(e).__name__}: {e}")
    finally:
        close_stray_modal(pg, fl)

    # ── A. add a sync registry entry ─────────────────────────────────────────
    pipe_name = qa_name("pipe")
    added_registry = False
    try:
        goto_section(pg, fl, "סנכרון")
        tab("מקורות", wait=2600)
        new_pipe_btn = fl.locator("button.btn", has_text="מקור סנכרון חדש")
        s.check("'new sync source' button present", new_pipe_btn.count() > 0)
        if new_pipe_btn.count():
            new_pipe_btn.first.click(timeout=8000)
            pg.wait_for_timeout(1200)
            drawer = fl.locator(".drawer-ov")
            if drawer.count():
                # step 1: connection — pick whichever radio is offered
                radios = drawer.locator('input[type=radio][name=conn]')
                if radios.count():
                    radios.first.check()
                # The wizard's forward button is labelled 'המשך' (SyncStatePage.tsx:930), never
                # 'הבא'. With the wrong label `nxt.count()` was 0, EVERY `if nxt.count():` below
                # was skipped, the wizard never left step 1, and the suite reported "new sync
                # registry entry persisted: False" — as though the backend had dropped the write,
                # when in fact nothing was ever submitted. 'הבא' is kept as a fallback so the
                # check still works if the label is reworded back.
                nxt = drawer.locator("button", has_text="המשך")
                if nxt.count() == 0:
                    nxt = drawer.locator("button", has_text="הבא")
                # It is also DISABLED until the step's own requirement is met (step 1 needs a
                # connection, step 2 needs a source folder), so advance only once it is enabled.
                def advance(label: str) -> bool:
                    if nxt.count() == 0:
                        return False
                    for _ in range(20):
                        if nxt.first.is_enabled():
                            nxt.first.click(timeout=6000)
                            pg.wait_for_timeout(900)
                            return True
                        pg.wait_for_timeout(300)
                    s.check(f"sync wizard: '{label}' step could be completed", False,
                            "forward button stayed disabled")
                    return False

                advance("connection")
                # step 2: pick a source folder + archive folder. The pickers are populated from a
                # LIVE Drive/Gmail listing (the BFF calls drive:8975/api/files), so the step opens
                # showing 'טוען…' with no <select> in the DOM at all — measured still loading 3s
                # in. Selecting immediately therefore chose nothing, `src` stayed unset and the
                # wizard's forward button stayed disabled forever. Wait for the pickers.
                selects = drawer.locator("select")
                for _ in range(60):
                    if selects.count():
                        break
                    pg.wait_for_timeout(500)
                for i in range(selects.count()):
                    sel = selects.nth(i)
                    opts = sel.locator("option")
                    if opts.count() > 1:
                        sel.select_option(index=1)
                        pg.wait_for_timeout(400)
                advance("folders")
                # step 3: name. NOT `input.first` — the wizard keeps earlier steps' inputs
                # (the step-1 connection radios) mounted in the DOM rather than unmounting them,
                # so `.first` picked the radio and `.fill()` threw (radios aren't fillable). Scope
                # to a real text input instead.
                name_input = drawer.locator('input[type=text], input:not([type])').first
                if name_input.count() == 0:
                    name_input = drawer.locator('input:not([type=radio]):not([type=checkbox])').first
                if name_input.count():
                    name_input.fill(pipe_name)
                advance("name")
                # step 4: create ('יצירת מקור' for a new source, 'שמירה' when editing)
                create_btn = drawer.locator("button", has_text="יצירת מקור")
                if create_btn.count():
                    create_btn.first.click(timeout=8000)
                    pg.wait_for_timeout(1800)
                    added_registry = True
        # Poll for the ENTRY, not merely for a non-empty registry. `sync_registry_names()` returns
        # the 13 pre-existing names on its very first call, which is truthy, so poll_until stopped
        # immediately and this asserted against a registry read ~0s after the click. Measured
        # 2026-08-11 under live load: the write landed, but later than the old 8 x 1.5s window —
        # the run reported "not persisted" while a subsequent check in the SAME run printed the
        # registry with 'QA_E2E_..._pipe' present. Wait for the condition, and give the write a
        # budget that reflects what this host actually does under pipeline load.
        poll_until(lambda: pipe_name in (sync_registry_names() or []), tries=40, interval_s=1.5)
        names = sync_registry_names()
        s.check("new sync registry entry persisted", added_registry and pipe_name in (names or []),
                f"looked for {pipe_name!r} in {names}")
    except Exception as e:
        s.check("add-sync-registry section completed without crashing", False,
                f"{type(e).__name__}: {e}")
    finally:
        close_stray_modal(pg, fl)

    # ── E. sync board: run / pause / edit / delete, each confirmed persisted ──
    try:
        goto_section(pg, fl, "סנכרון")
        tab("מקורות", wait=2200)
        card = fl.locator(".card", has_text=pipe_name)
        s.check("new pipe shows a card on the sync board", card.count() > 0)
        if card.count():
            # run
            run_btn = card.first.locator("button.btn", has_text="הרץ עכשיו")
            if run_btn.count():
                run_btn.first.click(timeout=10000)
                pg.wait_for_timeout(2000)
                s.check("'run now' accepted (no crash)", True)
            # pause
            pause_btn = card.first.locator("button.link", has_text="השהה")
            if pause_btn.count():
                pause_btn.first.click(timeout=8000)
                pg.wait_for_timeout(1200)
                # Poll for the CONDITION, not for the row. This used to poll
                # `psql("SELECT value ...")`, whose result is a non-empty JSON string on every
                # call — always truthy — so poll_until returned on its FIRST iteration and the
                # registry was read within milliseconds of the click, before the PATCH could land.
                # It never waited at all, and reported the pre-click value as a failure.
                def paused_flag():
                    try:
                        arr = json.loads(
                            psql("SELECT value FROM public.settings WHERE key='sync_registry';")
                            or "[]")
                    except Exception:
                        return None
                    entry = next((e for e in arr if e.get("name") == pipe_name), None)
                    return entry.get("enabled") if entry else None

                poll_until(lambda: paused_flag() is False, tries=15, interval_s=1.0)
                enabled_val = paused_flag()
                s.check("pause persisted enabled=false in the backend", enabled_val is False,
                        enabled_val)
            # edit
            edit_btn = card.first.locator("button.link", has_text="עריכה")
            renamed = pipe_name + "_edited"
            if edit_btn.count():
                edit_btn.first.click(timeout=8000)
                pg.wait_for_timeout(1000)
                drawer2 = fl.locator(".drawer-ov")
                if drawer2.count():
                    # Editing opens the SAME 4-step wizard at step 2 (`useState(existing ? 2 : 1)`),
                    # so neither the name field (step 3) nor the commit button (step 4) is mounted
                    # yet — walk forward to them the way an operator does.
                    fwd = drawer2.locator("button", has_text="המשך")
                    for _ in range(4):
                        ni = drawer2.locator('input[type=text], input:not([type])').first
                        if ni.count():
                            ni.fill(renamed)
                            break
                        if fwd.count() and fwd.first.is_enabled():
                            fwd.first.click(timeout=6000)
                            pg.wait_for_timeout(900)
                        else:
                            break
                    # then on to the final step where the commit button lives
                    for _ in range(3):
                        if drawer2.locator("button", has_text="שמירה").count():
                            break
                        if fwd.count() and fwd.first.is_enabled():
                            fwd.first.click(timeout=6000)
                            pg.wait_for_timeout(900)
                        else:
                            break
                    # The edit drawer's commit button is 'שמירה' (SyncStatePage.tsx:935 — the same
                    # step-4 button that reads 'יצירת מקור' when creating). Neither 'שמיר' nor
                    # 'שמור' is a substring of it, so this located nothing and the edit was never
                    # submitted; the assertion below then passed only via its `or pipe_name not in
                    # names` escape clause, which is true whenever the rename silently did nothing.
                    save_btn = drawer2.locator("button", has_text="שמירה")
                    if save_btn.count() == 0:
                        save_btn = drawer2.locator("button", has_text="שמור")
                    if save_btn.count():
                        save_btn.first.click(timeout=8000)
                        pg.wait_for_timeout(1500)
                # same defect as the create poll above: the old lambda returned the (always
                # non-empty) name list, so it never waited. Require the RENAME specifically —
                # the old `or pipe_name not in names2` escape clause also let this pass when the
                # edit silently did nothing at all.
                poll_until(lambda: renamed in (sync_registry_names() or []),
                           tries=40, interval_s=1.5)
                names2 = sync_registry_names()
                s.check("edit persisted a new name in the backend", renamed in (names2 or []),
                        names2)
            # delete (whatever the current name is now) — a reload resets the embedded app to
            # its own root route (the OUTER console hash survives reload, the INNER react-router
            # state does not), so re-drive both nav levels, not just the sub-tab.
            pg.reload()
            pg.wait_for_timeout(2500)
            fl2 = pg.frame_locator("iframe")
            try:
                goto_section(pg, fl2, "סנכרון")
                fl2.locator(".subnav .stab", has_text="מקורות").first.click(timeout=8000)
                pg.wait_for_timeout(1500)
            except Exception:
                pass
            cur_name = renamed if renamed in (sync_registry_names() or []) else pipe_name
            card2 = fl2.locator(".card", has_text=cur_name)
            del_btn = card2.locator("button.link", has_text="מחיקה")
            if del_btn.count():
                click_confirm(pg, del_btn.first)
                pg.wait_for_timeout(1800)
            poll_until(lambda: cur_name not in (sync_registry_names() or []),
                       tries=40, interval_s=1.5)
            names3 = sync_registry_names()
            s.check("delete persisted — entry gone from the backend registry",
                    cur_name not in (names3 or []), names3)
    except Exception as e:
        s.check("sync-board section completed without crashing", False, f"{type(e).__name__}: {e}")
    finally:
        close_stray_modal(pg, fl)

    # ── B. upload into the watched folder, watch it reach COMPLETED ─────────
    # Best-effort: only run this leg if we actually created a drive-backed pipe above
    # (skipped cleanly, with a clear reason, if the drawer flow above didn't complete —
    # this leg is the slowest and most environment-dependent part of the suite).
    if added_registry:
        fname = qa_name("watched-upload") + ".txt"
        content = f"E2E indox watched-folder probe {QA_TAG}\n".encode("utf-8")
        tmp = Path(tempfile.gettempdir()) / fname
        tmp.write_bytes(content)
        try:
            dfl = open_console_module(pg, "drive", wait_ms=2600)
            dfl.locator("#filePick").set_input_files(str(tmp))
            # the upload is a real round trip to the drive service, then a list refresh — wait for
            # the row rather than sampling the table once at a flat 2s
            row = dfl.locator(f'tr[data-id]:has-text("{fname}")')
            for _ in range(40):
                if row.count():
                    break
                pg.wait_for_timeout(500)
            s.check("watched-folder upload appears in drive UI", row.count() > 0,
                    f"{fname} not listed after 20s")
        except Exception as e:
            s.check("could upload into the watched folder via drive UI", False, str(e))
        finally:
            tmp.unlink(missing_ok=True)

        status = poll_until(lambda: doc_status(fname), tries=60, interval_s=8.0)
        s.check("uploaded document reached COMPLETED automatically",
                status == "COMPLETED", f"last observed STATUS={status}")

    # ── D. THE DOCUMENT VIEW ────────────────────────────────────────────────
    #
    # Two defects shipped through every green run of this suite because nothing here ever
    # opened a document. Both are now assertions:
    #
    #   A. The overlay urls are rendered into <img src>, not fetched through call(), so they
    #      carried no ?instance= — the BFF read schema `public`, PostgREST 404'd, Flask
    #      answered 500, and the screen quietly showed a preview instead of the extraction.
    #      Checked by reading the url the page actually asked for.
    #   B. The stage centred an overflowing page with `align-items:center`, putting the top of
    #      every tall document ABOVE scrollTop 0 where no scrollbar can reach it (141-163px,
    #      measured). Checked by comparing the image's top against the stage's at scroll 0 —
    #      the one number that cannot be true while the bug exists.
    #
    # Everything here reads geometry from the live DOM; none of it depends on which document
    # the table happens to open, so it stays true as the data changes.
    try:
        fl = open_console_module(pg, "incoming", wait_ms=3000)
        goto_section(pg, fl, "מסמכים")
        row = fl.locator('a[href*="/documents/doc_"]').first
        for _ in range(30):
            if row.count():
                break
            pg.wait_for_timeout(500)
        s.check("documents table lists a document to open", row.count() > 0)
        if row.count():
            row.click(timeout=8000)
            stage = fl.locator(".doc-stage")
            for _ in range(40):
                if stage.count():
                    break
                pg.wait_for_timeout(500)
            s.check("document view renders the stage", stage.count() > 0)

            if stage.count():
                geo = fl.locator(".stage").first.evaluate(
                    """(st) => {
                        st.scrollTop = 0;
                        const img = st.querySelector('.stage-canvas img');
                        const empty = st.querySelector('.stage-empty');
                        const wrap = st.ownerDocument.querySelector('.wrap');
                        const data = st.ownerDocument.querySelector('.doc-data');
                        const r = st.getBoundingClientRect();
                        return {
                          hasImg: !!img,
                          src: img ? img.getAttribute('src') : '',
                          natW: img ? img.naturalWidth : 0,
                          topRel: img ? Math.round(img.getBoundingClientRect().top - r.top) : null,
                          emptyExplained: !!(empty && empty.textContent.trim()),
                          pageScrolls: !!(wrap && wrap.scrollHeight > wrap.clientHeight + 1),
                          dataScrollsAlone: !!(data && data.scrollHeight > data.clientHeight),
                          stageH: Math.round(r.height),
                        };
                    }"""
                )

                # A — every document asset url names its tenant
                if geo["hasImg"]:
                    s.check("document image url carries ?instance=", "instance=" in (geo["src"] or ""),
                            geo["src"])
                    s.check("document image actually decoded", geo["natW"] > 0,
                            f"naturalWidth={geo['natW']} for {geo['src']}")
                else:
                    # no image is only acceptable as an EXPLAINED absence, never a blank frame
                    s.check("a document with no raster explains itself", geo["emptyExplained"])

                # B — the top of the page is reachable at scroll origin
                if geo["topRel"] is not None:
                    s.check("document top is not clipped above the scroll origin",
                            geo["topRel"] >= 0, f"image starts {geo['topRel']}px above the stage")

                # the layout contract: the page itself never scrolls; its columns do
                s.check("the document page itself does not scroll", not geo["pageScrolls"])
                s.check("the stage was given a real height", geo["stageH"] > 120, geo["stageH"])
    except Exception as e:
        s.check("document-view section completed without crashing", False, f"{type(e).__name__}: {e}")

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
            pg.screenshot(path=str(ARTIFACTS / "indox_fail.png"))
            print(f"  FAIL  indox/suite crashed — {type(e).__name__}: {e}")
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
