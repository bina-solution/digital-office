#!/usr/bin/env python3
"""
test_mail.py — Mail E2E: send mail between two LOCAL users through the real UI, verify arrival
against the mail backend (mailapi -> real Dovecot/Postfix, not a mock), then run the real Mail
Label Engine (n8n workflow mailLabelEngine01) and assert the UI's triage indicator matches what
the engine actually wrote — not merely that a dot rendered.

Uses ONLY the local mail engine (admin@local.test / user2@local.test, both provisioned by
apps/mail/docker-compose.yml's mailserver-init) — never the real client mailbox
(mail_imap_app_password-51185288 / person9@example.com). See ai/context and the repo's own
memory: real-mailbox injection is forbidden for exactly this kind of test.

User stories covered
---------------------
1. As user "admin", I compose and send a mail to "user2" through the Mail UI, and the message is
   actually delivered — verifiable straight from mailapi (the same backend the UI itself calls),
   not just "a compose window closed without error".
2. As user "user2", after the Mail Label Engine has run, the triage dot next to that message in
   the UI reflects EXACTLY the triage state implied by the labels the engine actually applied
   (computed independently in Python from mailapi's /organizer/settings label map + the mail app's
   own TRIAGE_KEYS table) — not a stale, hardcoded, or merely-present dot.

Navigation is always through console.localhost (never mail.localhost directly), same rule as
every other suite here.

Run:
    python3 scripts/ui-coverage/e2e/test_mail.py
Cleanup:
    python3 scripts/ui-coverage/e2e/cleanup.py
"""

from __future__ import annotations

import sys as _sys
# These suites print Hebrew document text. On a host whose stdout is not already UTF-8 that
# raises UnicodeEncodeError on the first Hebrew character, and the traceback reads as a
# test failure rather than an encoding one. Same guard the gates use. (G10)
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(_sys.stderr, "reconfigure"):
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")


import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    Suite, new_browser, new_context, open_console_module, mailapi_call, qa_name, QA_TAG,
    n8n_login, n8n_run_workflow, n8n_wait_execution, poll_until, ARTIFACTS,
)
from playwright.sync_api import sync_playwright  # noqa: E402

MAIL_LABEL_ENGINE_WF = "mailLabelEngine01"
# n8n exports this node name with a TYPOGRAPHIC apostrophe (U+2019) — a plain ASCII "'" will not
# match, and the run silently 404s with no obviously-related error. Verified against
# scripts/_run_label_engine_test.py, which already drives this workflow successfully.
TRIGGER_NODE = "When clicking ‘Execute workflow’"

TRIAGE_KEYS = {
    "failed":    ["FAILED_DOC", "FAILED_BS", "ACTION_FAILED", "FOUND_UNKNOWN"],
    "processed": ["SYNCED_DOC", "SYNCED_BS", "SAVED_INVOICE", "SAVED_SHIPMENT", "ACTION_DONE"],
    "waiting":   ["DOC_TO_SYNC", "BS_TO_SYNC", "DOC_LINK_TO_SYNC", "IN_PROGRESS"],
}
TRIAGE_ORDER = ["failed", "processed", "waiting"]


def get_profiles():
    status, data = mailapi_call("/engine/profiles")
    if status != 200 or not data:
        raise RuntimeError(f"mailapi /engine/profiles failed: {status} {data}")
    by_id = {p["id"]: p for p in data.get("profiles", [])}
    return by_id


def label_map():
    """KEY -> resolved label text, straight from mailapi (same source mailview's loadLabelMap()
    uses) — never hardcode the Hebrew text, it has already changed once on this deployment."""
    status, data = mailapi_call("/organizer/settings")
    if status != 200 or not data:
        raise RuntimeError(f"mailapi /organizer/settings failed: {status} {data}")
    labels = ((data.get("gmail") or {}).get("labels")) or {}
    return {k: v.get("name") for k, v in labels.items() if v.get("name")}


def expected_triage(applied_labels: set[str], names: dict) -> str:
    for state in TRIAGE_ORDER:
        keys = TRIAGE_KEYS[state]
        wanted = {names[k] for k in keys if k in names}
        if applied_labels & wanted:
            return state
    return ""


def switch_account(pg, fl, display_text: str) -> bool:
    """Same account-switcher pattern flow-qa.py uses for drive/mail/indox."""
    sw = pg.locator(".dosw-top .dosw-btn")
    if sw.count() == 0:
        return False
    sw.first.click()
    pg.wait_for_timeout(600)
    items = pg.locator(".dosw-menu .dosw-it")
    for i in range(items.count()):
        if display_text in (items.nth(i).inner_text() or ""):
            items.nth(i).click()
            pg.wait_for_timeout(1800)
            return True
    pg.keyboard.press("Escape")
    return False


def run(pg) -> Suite:
    s = Suite("mail")
    profiles = get_profiles()
    s.check("both local profiles are provisioned (admin + user2)",
            "admin" in profiles and "user2" in profiles, list(profiles))
    admin_addr = profiles.get("admin", {}).get("address", "admin@local.test")
    user2_addr = profiles.get("user2", {}).get("address", "user2@local.test")
    user2_cid = profiles.get("user2", {}).get("connection_id")

    marker = uuid.uuid4().hex[:10]
    subject = qa_name(f"mail-{marker}") + " invoice"          # 'invoice' -> triggers INVOICE_RELATED
    body = f"E2E mail probe {QA_TAG} marker={marker}. This references an invoice for testing."

    fl = open_console_module(pg, "mail", wait_ms=2800)
    s.check("mail app loads", fl.locator("#sideNav .bnv-primary").count() > 0
            or fl.locator("body").inner_text().strip() != "")

    # make sure we're sending AS admin
    switch_account(pg, fl, "מנהל")
    pg.wait_for_timeout(800)

    # ── 1. compose + send through the real UI ────────────────────────────────
    compose_btn = fl.locator("#sideNav .bnv-primary").first
    compose_btn.click(timeout=8000)
    pg.wait_for_timeout(700)
    win = fl.locator(".mlc-ov, .mlc-win")
    s.check("compose window opens", win.count() > 0)

    win.locator("[data-to]").fill(user2_addr)
    win.locator("[data-subj]").fill(subject)
    win.locator("[data-body]").fill(body)

    with pg.expect_event("response", lambda r: "/api/send" in r.url, timeout=15000) as resp_info:
        win.locator(".mlc-send, [data-send]").first.click()
    resp = resp_info.value
    s.check("POST api/send returned 2xx", 200 <= resp.status < 300, resp.status)

    # ── 2. verify arrival straight from the mail backend (mailapi -> real IMAP) ─
    def find_msg():
        status, data = mailapi_call("/search", "POST", {
            "connection_id": user2_cid, "folder": "INBOX", "query": marker, "limit": 5,
        })
        if status != 200 or not data:
            return None
        msgs = data.get("messages") or []
        return msgs[0] if msgs else None

    msg = poll_until(find_msg, tries=20, interval_s=3.0)
    s.check("message reached user2's mailbox (verified via mailapi, not the UI)", msg is not None,
            msg)
    uid = msg.get("uid") if msg else None

    # ── 3. run the REAL label engine, then check the UI's triage dot against what
    #      the engine actually wrote (independently recomputed, not just "a dot exists") ──
    ck = n8n_login()
    s.check("n8n login (for triggering the label engine)", bool(ck))
    exec_id = n8n_run_workflow(MAIL_LABEL_ENGINE_WF, TRIGGER_NODE, cookie=ck)
    s.check("mail label engine execution started", exec_id is not None, exec_id)
    if exec_id:
        status = n8n_wait_execution(exec_id, budget_s=420, poll_s=10)
        s.check("mail label engine execution finished (not stuck running)",
                status not in ("timeout", "running"), status)

    names = label_map()
    # re-fetch the message straight from the backend, post-engine, for its final label set
    status, data = mailapi_call("/search", "POST", {
        "connection_id": user2_cid, "folder": "INBOX", "query": marker, "limit": 5,
    })
    msgs = (data or {}).get("messages") or []
    msg2 = msgs[0] if msgs else None
    s.check("message still resolvable after the engine ran", msg2 is not None)
    applied = set((msg2 or {}).get("labels") or [])
    want_state = expected_triage(applied, names)
    invoice_label = names.get("INVOICE_RELATED")
    s.check("label engine applied INVOICE_RELATED to a message whose body says 'invoice'",
            bool(invoice_label) and invoice_label in applied,
            f"applied={sorted(applied)} wanted={invoice_label}")

    # switch the UI to user2 and read the triage dot for this exact message
    switch_account(pg, fl, "משתמש 2")
    pg.wait_for_timeout(1500)
    search = fl.locator("#sideNav .bnv-search input")
    if search.count():
        search.fill(marker)
        search.press("Enter")
        pg.wait_for_timeout(1500)
    row = fl.locator(f'.gm-row', has_text=marker)
    if row.count() == 0 and uid:
        row = fl.locator(f'.gm-row[data-id="{uid}"]')
    s.check("sent message is visible in user2's inbox in the UI", row.count() > 0)
    if row.count():
        cls = row.first.locator(".gm-triage").get_attribute("class") or ""
        ui_state = next((st for st in TRIAGE_ORDER if st in cls.split()), "")
        s.check("UI triage dot matches the state derived from the engine's own labels",
                ui_state == want_state, f"ui={ui_state!r} expected={want_state!r} class={cls!r}")

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
            pg.screenshot(path=str(ARTIFACTS / "mail_fail.png"))
            print(f"  FAIL  mail/suite crashed — {type(e).__name__}: {e}")
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
