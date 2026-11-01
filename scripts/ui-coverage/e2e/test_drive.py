#!/usr/bin/env python3
"""
test_drive.py — Drive E2E: upload, move, rename, create folder — all through the real UI,
each verified against the drive backend (Postgres tables drive_files / drive_folders on
supabase-db), not just "a UI element appeared".

User stories covered
---------------------
1. As a user, I upload a file through the Drive UI and it is indexed in the backend with the
   right name and a non-zero size.
2. As a user, I create a new folder through the UI and it exists as a real drive_folders row.
3. As a user, I move a file into that folder through the UI, and the file's `folder` column in
   Postgres is updated to the new folder's id (not just re-rendered in the right place).
4. As a user, I rename a file through the UI, and drive_files.name is updated in Postgres.

Navigation is ALWAYS through console.localhost — never drive.localhost directly (per the
platform's own rule: users never visit an app's standalone host, they open the console and see
the app framed — and the ui-coverage inventory only counts embedded views as real for exactly
this reason). Auth is the Authentik flow ported into common.py from capture.py's ak_login /
open_gated, the one piece of this repo's browser automation independently proven end-to-end.

Run:
    python3 scripts/ui-coverage/e2e/test_drive.py
Cleanup of everything this suite creates:
    python3 scripts/ui-coverage/e2e/cleanup.py
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    Suite, new_browser, new_context, open_console_module, psql, psql_one, qa_name, ARTIFACTS,
)
from playwright.sync_api import sync_playwright  # noqa: E402

# These suites print Hebrew document text. On a host whose stdout is not already UTF-8 that
# raises UnicodeEncodeError on the first Hebrew character, and the traceback reads as a
# test failure rather than an encoding one. Same guard the gates use. (G10)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")



def q(sql_val: str) -> str:
    return sql_val.replace("'", "''")


def db_file_row(name: str):
    out = psql(
        f"SELECT id, folder, size, trashed FROM drive_files WHERE name = '{q(name)}' "
        f"ORDER BY created_at DESC LIMIT 1;"
    ).strip()
    if not out:
        return None
    parts = out.split("|")
    return {"id": parts[0], "folder": parts[1], "size": parts[2], "trashed": parts[3]}


def db_folder_row(name: str):
    out = psql(f"SELECT id FROM drive_folders WHERE name = '{q(name)}' "
               f"ORDER BY created_at DESC LIMIT 1;").strip()
    return out or None


def wait_db(fn, tries=15, interval=1.0):
    for _ in range(tries):
        v = fn()
        if v:
            return v
        time.sleep(interval)
    return fn()


def modal_save(fl):
    fl.locator("#mFoot .primary").click()


def close_stray_modal(pg, fl):
    """Best-effort: dismiss whatever modal/overlay is left open so the NEXT step's clicks
    aren't intercepted by a stale `#overlay`. A previous step's write can fail server-side
    (see the active-connection check below) and leave its modal open with no visible error —
    without this, one failed write crashes every check after it instead of just its own."""
    try:
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(300)
    except Exception:
        pass
    try:
        close_btn = fl.locator("#mClose, .modal .close, [aria-label='סגור']")
        if close_btn.count() and close_btn.first.is_visible():
            close_btn.first.click(timeout=1500)
            pg.wait_for_timeout(300)
    except Exception:
        pass


def active_connection_label(pg) -> str:
    """The account-switcher chip in the console shell's account bar — reveals which backend
    connection drive is currently bound to (e.g. 'Google Drive · ...gserviceaccount.com' vs the
    local drive_local profile). Read BEFORE running any write step: if the active connection is
    a Google service account, every write below is expected to fail server-side (no storage, no
    Shared Drive — see apps/drive/app.py's `_explicit_connection_required` docstring, 2026-08-06
    incident) and that is an app/config defect this suite should report, not paper over."""
    try:
        return pg.locator(".dosw-top").first.inner_text(timeout=3000).strip()
    except Exception:
        return ""


def run(pg) -> Suite:
    s = Suite("drive")
    fl = open_console_module(pg, "drive", wait_ms=2800)

    # sanity: the files table actually rendered
    s.check("app loads", fl.locator("#filesTable").count() > 0)

    conn_label = active_connection_label(pg)
    is_google_svc = "gserviceaccount.com" in conn_label
    print(f"  [drive] active connection: {conn_label!r}"
          + (" — GOOGLE SERVICE ACCOUNT BOUND: writes are expected to fail server-side "
             "(no storage/Shared Drive on this account); every FAIL below that matches is "
             "that known config defect, not a UI or test defect." if is_google_svc else ""))

    # ── 1. upload ────────────────────────────────────────────────────────────
    fname = qa_name("upload") + ".txt"
    content = f"E2E drive upload probe — {fname}\n".encode("utf-8")
    tmp = Path(tempfile.gettempdir()) / fname
    tmp.write_bytes(content)

    pick = fl.locator("#filePick")
    pick.set_input_files(str(tmp))
    pg.wait_for_timeout(1800)

    ui_has_file = wait_db(
        lambda: fl.locator(f'tr[data-id]:has-text("{fname}")').count() > 0,
        tries=15, interval=1.0,
    )
    s.check("upload appears in the file list", ui_has_file)

    row = wait_db(lambda: db_file_row(fname), tries=15, interval=1.0)
    s.check("upload indexed in drive_files (backend)", row is not None, row)
    if row:
        s.check("uploaded file size matches what was sent",
                int(row["size"]) == len(content), f"db={row['size']} sent={len(content)}")
    file_id = row["id"] if row else None

    # ── 2. create folder ─────────────────────────────────────────────────────
    # Each numbered step is wrapped so a failed WRITE (e.g. the dangling-connection defect
    # above) reports its own check and a stray modal gets cleared, rather than throwing an
    # unhandled Locator timeout that aborts every check after it — losing exactly the
    # visibility a "run the suites and iterate" workflow depends on.
    folder_name = qa_name("folder")
    folder_id = None
    try:
        fl.locator("#newFolderBtn").click(timeout=8000)
        pg.wait_for_timeout(500)
        fl.locator("#mInput").fill(folder_name)
        modal_save(fl)
        pg.wait_for_timeout(1500)

        ui_has_folder = wait_db(
            lambda: fl.locator(f'tr.frow:has-text("{folder_name}")').count() > 0
            or folder_name in fl.locator("#viewTitle").inner_text(),
            tries=10, interval=1.0,
        )
        s.check("new folder appears in the UI", ui_has_folder)

        folder_id = wait_db(lambda: db_folder_row(folder_name), tries=15, interval=1.0)
        s.check("new folder exists in drive_folders (backend)", folder_id is not None, folder_id)
    except Exception as e:
        s.check("create-folder step completed without crashing", False, f"{type(e).__name__}: {e}")
    finally:
        close_stray_modal(pg, fl)

    # ── 3. move the uploaded file into the new folder ───────────────────────
    try:
        fl.locator('[data-place="mydrive"]').first.click(timeout=8000)
        pg.wait_for_timeout(1200)
        row_sel = fl.locator(f'tr[data-id="{file_id}"]') if file_id else fl.locator(
            f'tr[data-id]:has-text("{fname}")')
        s.check("uploaded row is present to move (depends on step 1)", row_sel.count() > 0)
        if row_sel.count():
            row_sel.first.hover()
            pg.wait_for_timeout(200)
            move_btn = fl.locator(f'tr[data-id]:has-text("{fname}") button[data-act="move"]')
            if move_btn.count() == 0:
                row_sel.first.click(button="right")
                pg.wait_for_timeout(500)
                fl.locator('#ctx button[data-c="move"]').click(timeout=6000)
            else:
                move_btn.first.click(timeout=6000)
            pg.wait_for_timeout(700)

            moved = False
            if fl.locator("#mSearch").count():
                fl.locator("#mSearch").fill(folder_name)
                pg.wait_for_timeout(600)
            pick_target = fl.locator(f'.pick:has-text("{folder_name}")')
            if pick_target.count():
                pick_target.first.click(timeout=6000)
                pg.wait_for_timeout(1300)
                moved = True
            s.check("move dialog offered the new folder as a target", moved)

            moved_row = wait_db(lambda: db_file_row(fname), tries=15, interval=1.0)
            s.check("file's folder column updated in Postgres after move",
                    bool(moved_row and folder_id and moved_row["folder"] == folder_id),
                    f"file.folder={moved_row and moved_row['folder']} target={folder_id}")
    except Exception as e:
        s.check("move step completed without crashing", False, f"{type(e).__name__}: {e}")
    finally:
        close_stray_modal(pg, fl)

    # ── 4. rename the file ───────────────────────────────────────────────────
    new_name = qa_name("renamed") + ".txt"
    try:
        fl.locator('[data-place="mydrive"]').first.click(timeout=8000)
        pg.wait_for_timeout(900)
        if folder_id and fl.locator(f'tr.frow:has-text("{folder_name}")').count():
            fl.locator(f'tr.frow:has-text("{folder_name}")').first.click(timeout=8000)
            pg.wait_for_timeout(1000)
        target_row = fl.locator(f'tr[data-id]:has-text("{fname}")')
        s.check("uploaded row is present to rename (depends on step 1)", target_row.count() > 0)
        if target_row.count():
            target_row.first.hover()
            pg.wait_for_timeout(200)
            rn_btn = fl.locator(f'tr[data-id]:has-text("{fname}") button[data-act="rename"]')
            if rn_btn.count() == 0:
                target_row.first.click(button="right")
                pg.wait_for_timeout(500)
                fl.locator('#ctx button[data-c="rename"]').click(timeout=6000)
            else:
                rn_btn.first.click(timeout=6000)
            pg.wait_for_timeout(600)
            fl.locator("#mInput").fill(new_name)
            modal_save(fl)
            pg.wait_for_timeout(1300)

            ui_renamed = wait_db(
                lambda: fl.locator(f'tr[data-id]:has-text("{new_name}")').count() > 0,
                tries=12, interval=1.0,
            )
            s.check("renamed file shows the new name in the UI", ui_renamed)

            renamed_row = wait_db(lambda: db_file_row(new_name), tries=15, interval=1.0)
            s.check("drive_files.name updated in Postgres after rename",
                    bool(renamed_row and file_id and renamed_row["id"] == file_id),
                    renamed_row)
    except Exception as e:
        s.check("rename step completed without crashing", False, f"{type(e).__name__}: {e}")
    finally:
        close_stray_modal(pg, fl)

    tmp.unlink(missing_ok=True)
    if is_google_svc:
        print("  [drive] NOTE: active connection was the Google service account for this whole "
              "run — any FAIL above is very likely that known config defect (drive writes "
              "refused server-side), not a UI or test defect. Re-run after the drive connection "
              "binding is fixed to confirm.")
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
            pg.screenshot(path=str(ARTIFACTS / "drive_fail.png"))
            print(f"  FAIL  drive/suite crashed — {type(e).__name__}: {e}")
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
