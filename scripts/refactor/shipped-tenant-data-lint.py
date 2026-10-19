#!/usr/bin/env python3
"""shipped-tenant-data-lint — gate G56: shipped blueprints carry no tenant-specific data.

    python3 scripts/refactor/shipped-tenant-data-lint.py [--self-test] [--update-baseline]

WHY THIS GATE EXISTS

G40 (`fixture-live-key-lint.py`) polices `apps/*/blueprint/fixtures/*settings*.json` — the
files the UI seeder reads. It was written after a fixture's `sync_registry` row was upserted
over a real client's live registry twice on 2026-08-05.

It does not police the OTHER shipped surface: `apps/*/blueprint/n8n/**` and `blueprint/demo/**`.
Those are bootstrapped into every new deployment just as surely, and on 2026-08-06 a deliberate
sweep found 243 pieces of one client's data sitting in them — including
`indoxV2SearchWarehouse01` hardcoding that client's `סרוקות הצליח` Drive folder id as the
fallback for its warehouse search, so a brand-new deployment would have searched the OLD
client's Drive on first run. That one is fixed; the rest are baselined below.

WHAT IT LOOKS FOR, AND WHY EACH MATTERS

  drive-folder-url / drive-open-url   real Drive folder or FILE ids. A leak: the new tenant's
                                      workflow reads the old tenant's documents, silently and
                                      successfully. Worst class — it works.
  known-prod-folder-id                the pipe folders this deployment syncs, by id.
  connection-instance-id              a connection that will not exist on a new deployment.
                                      Portability break, not a leak: it fails LOUDLY.
  client-mailbox                      real people's addresses in demo seeds and tag rules.

THE BASELINE IS DEBT, NOT PERMISSION

`shipped-tenant-data-baseline.json` records the hits that already existed when this gate landed,
keyed by file. The gate fails on anything NOT in it, so the surface cannot get worse while the
existing debt is paid down. Shrinking the baseline is the fix; `--update-baseline` after a genuine
cleanup is how you record progress. Adding to it to make a new leak pass is the one thing it must
never be used for — which is why the counts are per-file rather than a global total: a new leak in
an already-listed file still fails once the count goes up.
"""
import argparse, collections, json, os, pathlib, re, sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]
BASELINE = pathlib.Path(__file__).resolve().parent / "shipped-tenant-data-baseline.json"

ROOTS = ("apps", "platform-base", "platform", "packaging")
SKIP_DIRS = {"node_modules", "__pycache__", ".git", "dist", "ci-artifacts", "context-collection"}
SHIPPED = re.compile(r"(^|/)(blueprint|fixtures)(/|$)")

PATTERNS = (
    ("drive-folder-url", re.compile(r"drive\.google\.com/drive/folders/[A-Za-z0-9_-]{20,}")),
    ("drive-open-url", re.compile(r"drive\.google\.com/(?:file/d/|open\?id=)[A-Za-z0-9_-]{20,}")),
    # BARE ids, with no URL around them — the shape the actual incident took. The
    # indoxV2SearchWarehouse01 leak was a naked `"1YpapJ3vJDYo…"` inside a JS expression,
    # so every URL-shaped pattern above sailed straight past it. This gate's own
    # regression test caught that omission on its first run; without this entry G56
    # would have passed the very leak it was written for.
    #
    # An explicit id list, not a length heuristic, for G40's reason: `SyncProcGDoc0001`
    # and `indoxGmailLinkDownloader01` are Drive-id-shaped and are platform workflow ids.
    # The cost is that the list needs a line per production folder — which is exactly the
    # set `data/registry/sync_registry.json` already enumerates, so it is auditable.
    ("known-prod-folder-id", re.compile(
        r"1YpapJ3vJDYo_idP3aZiFJR_1WoEaCNhu|1stuMSjbnyUTCtbq6KIzooHCGXpEey_7P|"
        r"11rj5zDw2lhYnc8zMUxmYADKIJaPaunhb|1xthreeBl1VD-5uN9PFu9Zi-0IABQDwst|"
        r"1DYzDE5T3c2PGFOfNwnmCP3jjSqr2DiBx|1PYaVJ4dKdOl1iGJlVKFT0pzJ_Rs2mYNL|"
        r"1m25RdFEkfv_5KjSqFGM8gpjupXWZuUW2|16GXkekZeHSyYtvkcoDGrEYiEu6Nn5Z1b|"
        r"1qTtoAQ1b-9c0gpdbfGy48fSRcskNzNgG|1zTQxUKtm1h7GUcGdb3ltSY0HjEsINzEV|"
        r"1gwx2QFdZCXjv4RvkY7qAY09ARi0aNBKI|1Lmhka14VGQMVGr4VQFRpF1YDEdOUnUhM")),
    ("connection-instance-id", re.compile(
        r"(?:drive_google_service_account|mail_imap_app_password|mail_imap_local|drive_local)"
        r"-[0-9a-f]{6,}")),
    ("client-mailbox", re.compile(
        r"\b(?:hachohen|hacohen\.agent|hachohen\.rikuz|hacohanim\.pituah|shimshon300|"
        r"hachohen\.office|ah0529898)[\w.+-]*@[\w.-]+", re.I)),
)

#: Same judgement as G40's placeholder rule, and for the same reason: a gate that fires on
#: legitimate tenant-neutral config gets disabled, and a disabled gate protects nothing.
ALLOW = re.compile(r"PLACEHOLDER|CHANGEME|EXAMPLE|example\.com|localhost|\.local\b|"
                   r"e2e-loadtest|demo\.indox|CLIENT_|<[A-Z_]+>", re.I)


def scan(overrides=None):
    """-> {relpath: {label: count}}. `overrides` maps relpath -> text, for the self-test."""
    found = collections.defaultdict(collections.Counter)
    if overrides:
        for rel, txt in overrides.items():
            for label, pat in PATTERNS:
                for hit in set(pat.findall(txt)):
                    line = next((l for l in txt.splitlines() if hit in l), "")
                    if not ALLOW.search(line):
                        found[rel][label] += 1
        return found
    for root in ROOTS:
        for dirpath, dirnames, filenames in os.walk(REPO / root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            if not SHIPPED.search(str(pathlib.Path(dirpath)).replace("\\", "/")):
                continue
            for fn in filenames:
                p = pathlib.Path(dirpath) / fn
                rel = str(p.relative_to(REPO)).replace("\\", "/")
                try:
                    txt = p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for label, pat in PATTERNS:
                    for hit in set(pat.findall(txt)):
                        line = next((l for l in txt.splitlines() if hit in l), "")
                        if not ALLOW.search(line):
                            found[rel][label] += 1
    return found


def load_baseline():
    if not BASELINE.exists():
        return {}
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--update-baseline", action="store_true")
    a = ap.parse_args()

    if a.self_test:
        cases = [
            ("a real Drive file id in a shipped workflow", {
                "apps/x/blueprint/n8n/w.json":
                    '{"url":"https://drive.google.com/file/d/1YpapJ3vJDYo_idP3aZiFJR_1WoEaCNhu"}'}, True),
            ("a connection instance id in a shipped workflow", {
                "apps/x/blueprint/n8n/w.json": '{"connection_id":"drive_google_service_account-ea660043"}'}, True),
            ("a client mailbox in a demo seed", {
                "apps/x/blueprint/demo/seed.json": '{"email":"person9@example.com"}'}, True),
            ("PLACEHOLDER ids are allowed", {
                "apps/x/blueprint/fixtures/f.json": '{"to_sync":"PLACEHOLDER_TO_SYNC_FOLDER_ID"}'}, False),
            ("a local/dev connection is allowed", {
                "apps/x/blueprint/n8n/w.json": '{"host":"localhost","to":"a@e2e-loadtest.local"}'}, False),
        ]
        ok = 0
        for name, files, must_catch in cases:
            caught = bool(scan(overrides=files))
            good = caught == must_catch
            ok += good
            print(f"  [{'ok ' if good else 'BAD'}] {'caught ' if caught else 'allowed'} "
                  f"(must {'catch' if must_catch else 'allow'}): {name}")
        print(f"\nG56 self-test: {ok}/{len(cases)} passed")
        return 0 if ok == len(cases) else 1

    found = scan()
    if a.update_baseline:
        BASELINE.write_text(json.dumps({k: dict(v) for k, v in sorted(found.items())},
                                       ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        tot = sum(sum(v.values()) for v in found.values())
        print(f"G56 baseline updated: {len(found)} file(s), {tot} hit(s) -> "
              f"{BASELINE.relative_to(REPO)}")
        return 0

    base = load_baseline()
    regressions = []
    for rel, counts in sorted(found.items()):
        allowed = base.get(rel, {})
        for label, n in sorted(counts.items()):
            if n > allowed.get(label, 0):
                regressions.append(f"{rel}: {label} {allowed.get(label, 0)} -> {n}")
    tot = sum(sum(v.values()) for v in found.values())
    btot = sum(sum(v.values()) for v in base.values())
    if regressions:
        print("G56 FAIL — new tenant-specific data in a shipped blueprint:")
        for r in regressions:
            print(f"  {r}")
        print("\n  Shipped blueprints are bootstrapped into every NEW deployment. A real Drive id\n"
              "  there means the new tenant reads the OLD tenant's documents — silently, and\n"
              "  successfully. Read the setting instead of hardcoding it (see\n"
              "  apps/indox/blueprint/n8n/indoxV2SearchWarehouse01.json 'WH Req (settings)').")
        return 1
    print(f"G56 PASS — {tot} known tenant-data hit(s) in {len(found)} shipped file(s), "
          f"all within the baseline ({btot}). No new ones.")
    if tot < btot:
        print(f"  baseline is now stale ({btot} -> {tot}) — debt was paid down; "
              f"re-run with --update-baseline to record it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
