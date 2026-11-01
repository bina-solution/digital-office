#!/usr/bin/env python3
"""fixture-live-key-lint — gate G40: a demo/QA fixture never carries a live-operational key.

    python3 scripts/refactor/fixture-live-key-lint.py [--self-test]

WHY THIS GATE EXISTS

`apps/indox/blueprint/fixtures/settings.json` is read by `scripts/ui-coverage/seed.sh` (`bbox
ui-map` / `bbox seed`) to make a bare stack's UI render real-looking content for screenshots.
`ui-map.sh` runs it by DEFAULT, before every capture, unless `UI_MAP_SKIP_SEED=1` — seeding is
opt-OUT, not opt-in.

On 2026-08-05 that fixture's `sync_registry` row — 6 demo pipe entries — got upserted straight over
a REAL client's live sync registry, TWICE, deleting two configured drive pipes and blanking the
`connection` field on two more. `sync_registry` is not demo data; it is config `apps/indox/app/
incoming_documents/api/__init__.py` itself calls out (its own comment, verbatim) as one of the
settings rows that "may not be blind-overwritten from this basic editor" — folder-routing URLs and
`sync_registry` are named together, explicitly, as the same category. This gate is the second half
of that incident's fix (the first half, `seed.sh` switching to `INSERT ... ON CONFLICT DO NOTHING`,
makes an existing key un-overwritable; it does NOT stop a live key from being seeded as another
tenant's opening state on that tenant's very first, empty-table seed — a fresh deployment has
nothing yet for `ON CONFLICT` to protect). The fixture must simply never carry one of these keys.

THE RULE

No `apps/*/blueprint/fixtures/settings.json` (or any file matching `apps/*/blueprint/fixtures/
*settings*.json`) may contain a row whose `key` is on `LIVE_OPERATIONAL_KEYS` below. That set is a
denylist, not an allowlist, deliberately: everything else in the fixture (keyword lists, the `q_*`
apitools query JSONs, extraction thresholds) is generic algorithm config, identical for every
tenant, safe to ship and reseed anywhere — only named, tenant-specific "connections, labels,
credentials-adjacent config" keys are barred.

Denylisted here, and why (all removed from the fixture in the same change that added this gate):

  sync_registry                        the sync pipeline itself — connections, folder/label ids
  WhatsappAdmins                       real admin phone numbers (access-control list)
  GmailToWhatsappAllowedMails          real sender allow-list (access-control list)
  GmailDocsDownloadIgnoredMails        real sender ignore-list (access-control list)
  *Folder / *Folder1 / *Folder2 / *Folder3-suffixed keys, and any settings key whose value is a
  literal `drive.google.com/drive/folders/...` URL — every one of these is one real tenant's Drive
  folder id. Shipping them in a fixture used to bootstrap a brand-new deployment would silently
  point that new tenant's pipeline at the OLD tenant's Drive folders on its very first seed — a
  cross-tenant data leak, not just an overwrite risk, and `seed.sh`'s insert-only fix does nothing
  to prevent it (nothing pre-exists yet to protect on a first seed).

The URL-shaped check is a pattern, not just a name list, on purpose: a name denylist is only ever as
complete as the last audit (this file's own history proves it — this exact class of key hid in the
fixture across at least one earlier pass). A literal live Drive-folder URL as a fixture VALUE is
always wrong regardless of what its key happens to be called.
"""
import argparse
import json
import pathlib
import re
import sys

# Self-test fixtures embed Hebrew fixture values (they're drawn from the real fixture this gate
# polices) and findings echo fixture values verbatim — both can hit stdout. Python defaults stdout
# to the platform's ANSI codepage outside lib.sh's PYTHONIOENCODING=utf-8 (Windows/WSL invocation),
# which raises UnicodeEncodeError on the first Hebrew character — see portability-lint.py (G10).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]

#: Exact-name denylist — the keys this incident (and its own prior history) actually found.
LIVE_OPERATIONAL_KEYS = {
    "sync_registry",
    "WhatsappAdmins",
    "GmailToWhatsappAllowedMails",
    "GmailDocsDownloadIgnoredMails",
    "BalanceSheetDestFolder1",
    "BalanceSheetSourceFolder1",
    "DocumentsToProcessFolder",
    "GeneralDocsDestFolder1",
    "GeneralDocsDestFolder2",
    "GeneralDocsDestFolder3",
    "GeneralDocsSourceFolder1",
    "GeneralDocsSourceFolder2",
    "GeneralDocsSourceFolder3",
    "GmailDownloadedBalanceDocsFolder",
    "GmailDownloadedDocumentsFolder",
    "ProcessedDocumentsFailsFolder",
    "ProcessedDocumentsFolder",
    "WarehouseScansSourceFolder",
}

#: Defense in depth for the name list above: a key whose bare NAME wasn't anticipated but whose
#: VALUE is unmistakably one real tenant's live Google Drive folder is the same landmine.
_DRIVE_FOLDER_URL = re.compile(r"drive\.google\.com/drive/folders/[A-Za-z0-9_-]+")

#: Fixtures this gate polices. Currently only apps/indox ships one; the globs are future-proofed
#: for any other app that grows a settings-shaped fixture the same seeder pattern would read.
#:
#: THE SECOND GLOB CLOSES A LOOPHOLE THIS GATE SHIPPED WITH (added 2026-08-06). The rule was
#: enforced by FILENAME: only `*settings*.json` was ever opened. A file named
#: `sync_registry.json` sitting in the very same fixtures directory, holding the very same
#: denylisted content in its native list-of-entries shape, passed the gate untouched — and one
#: was briefly written during the registry-declarativeness work before this was noticed. The
#: gate's own docstring already argues that a name list "is only ever as complete as the last
#: audit"; that applies to the file names as much as to the key names.
FIXTURE_GLOBS = (
    "apps/*/blueprint/fixtures/*settings*.json",
    "apps/*/blueprint/fixtures/*sync_registry*.json",
    "apps/*/blueprint/fixtures/*registry*.json",
)
FIXTURE_GLOB = FIXTURE_GLOBS[0]  # kept for callers/messages that name a single pattern

#: Registry entries carry Drive ids in known places — `pairs[]` (every folder role) and a gmail
#: pipe's `dest_folder`. Checking exactly those beats a length heuristic: an n8n workflow id
#: (`indoxGmailLinkDownloader01`, 26 chars) and a connection instance id are both Drive-id-shaped
#: and neither is a Drive folder, so a generic "long opaque string" rule would cry wolf on the
#: tenant-neutral example and get itself disabled.
_PAIR_ID_FIELDS = ("to_sync", "synced", "failed", "in_progress", "from", "to", "failed_to")
_PLACEHOLDER = re.compile(r"PLACEHOLDER|CHANGEME|EXAMPLE|\bTODO\b", re.I)


def _rows(text: str):
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, list):
        return None
    return data


def scan_fixture(rel: str, text: str):
    """Return a list of (key_or_None, reason) problems for one fixture file's text."""
    rows = _rows(text)
    if rows is None:
        return []  # not this gate's problem — not a {key,value}-list fixture at all
    problems = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        k = row.get("key")
        v = row.get("value")
        if k in LIVE_OPERATIONAL_KEYS:
            problems.append((k, f"'{k}' is on the live-operational denylist"))
        elif isinstance(v, str) and _DRIVE_FOLDER_URL.search(v):
            problems.append((k, f"value looks like a real, live Google Drive folder URL: {v[:80]!r}"))
        elif k is None and ("pairs" in row or "dest_folder" in row):
            # A sync_registry ENTRY, not a {key,value} settings row. Same denylisted content,
            # different shape — this is what the filename loophole used to let through.
            problems += _scan_registry_entry(row)
    return problems


def _scan_registry_entry(entry):
    """Flag real Drive folder ids in a tracked registry-shaped fixture entry.

    A tracked registry file may document the SHAPE; it may never carry one tenant's live
    folder ids, for the reason in this module's docstring — a new deployment bootstrapped
    from the repo would point at the old tenant's Drive on its first seed.
    """
    out = []
    name = entry.get("name") or "(unnamed entry)"
    candidates = []
    for pair in entry.get("pairs") or []:
        if isinstance(pair, dict):
            candidates += [(f, pair.get(f)) for f in _PAIR_ID_FIELDS]
    candidates.append(("dest_folder", entry.get("dest_folder")))
    for field, val in candidates:
        if not isinstance(val, str) or not val.strip():
            continue
        if _PLACEHOLDER.search(val):
            continue
        out.append((f"{name}.{field}",
                    f"registry entry '{name}' carries what looks like a REAL Drive folder id "
                    f"in {field}={val[:48]!r} — tracked fixtures must use PLACEHOLDER ids; the "
                    f"deployment's real registry belongs in data/registry/ (gitignored)"))
    return out


def scan(overrides=None):
    overrides = overrides or {}
    findings = []  # (rel, key, reason)
    seen = set()
    paths = sorted({q for g in FIXTURE_GLOBS for q in REPO.glob(g)})
    for p in paths:
        rel = str(p.relative_to(REPO)).replace("\\", "/")
        seen.add(rel)
        text = overrides.get(rel)
        if text is None:
            try:
                text = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
        for k, reason in scan_fixture(rel, text):
            findings.append((rel, k, reason))
    for rel, text in overrides.items():
        if rel not in seen:
            for k, reason in scan_fixture(rel, text):
                findings.append((rel, k, reason))
    return findings


SELF_TEST = [
    # --- the filename loophole, closed 2026-08-06 -----------------------------------
    # A registry-shaped file next to settings.json used to be invisible to this gate.
    # These two cases are the regression test for that: the real ids must fail, the
    # tenant-neutral shape must pass, so the example file stays committable.
    ("a real Drive folder id in a sync_registry-named fixture",
     "apps/_probe/blueprint/fixtures/sync_registry.json",
     json.dumps([{"name": "drive-gdoc-scanned", "source": "drive",
                  "pairs": [{"to_sync": "1stuMSjbnyUTCtbq6KIzooHCGXpEey_7P",
                             "synced": "1YpapJ3vJDYo_idP3aZiFJR_1WoEaCNhu",
                             "failed": "11rj5zDw2lhYnc8zMUxmYADKIJaPaunhb"}]}]), True),
    ("a gmail pipe's real dest_folder in a registry-named fixture",
     "apps/_probe/blueprint/fixtures/sync_registry.json",
     json.dumps([{"name": "gmail-doc", "source": "gmail",
                  "dest_folder": "ld19fd16971a5e326590441"}]), True),
    ("the tenant-neutral example (PLACEHOLDER ids) is allowed",
     "apps/_probe/blueprint/fixtures/sync_registry.example.json",
     json.dumps([{"name": "example-drive-pipe", "source": "drive",
                  "connection": "drive_google_service_account-CHANGEME",
                  "processor_wf": "SyncProcGDoc0001",
                  "pairs": [{"to_sync": "PLACEHOLDER_TO_SYNC_FOLDER_ID",
                             "synced": "PLACEHOLDER_SYNCED_FOLDER_ID",
                             "failed": "PLACEHOLDER_FAILED_FOLDER_ID"}]}]), False),
    # --- original cases ---------------------------------------------------------------
    ("sync_registry in a fixture", "apps/_probe/blueprint/fixtures/settings.json",
     json.dumps([{"key": "sync_registry", "value": "[]"}]), True),
    ("WhatsappAdmins in a fixture", "apps/_probe/blueprint/fixtures/settings.json",
     json.dumps([{"key": "WhatsappAdmins", "value": "050-000-0010"}]), True),
    ("a named-safe key with a live drive-folder URL value", "apps/_probe/blueprint/fixtures/settings.json",
     json.dumps([{"key": "SomeNewFolderNobodyDenylistedYet",
                  "value": "https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOpQrSt"}]), True),
    # must never flag generic algorithm config — that is most of the real fixture today
    ("generic keyword list", "apps/_probe/blueprint/fixtures/settings.json",
     json.dumps([{"key": "invoice_kws", "value": "[\"חשבונית מס\"]"}]), False),
    ("a q_* apitools query blob", "apps/_probe/blueprint/fixtures/settings.json",
     json.dumps([{"key": "q_v3_type", "value": "{\"action\": \"find after\"}"}]), False),
    ("a non-fixture-shaped json file", "apps/_probe/blueprint/fixtures/manifest.json",
     json.dumps({"not": "a list"}), False),
    ("not JSON at all", "apps/_probe/blueprint/fixtures/README.md", "# not json\n", False),
]


def self_test():
    bad = 0
    for label, rel, text, should in SELF_TEST:
        got = bool(scan_fixture(rel, text))
        if got != should:
            bad += 1
        print(f"  [{'ok ' if got == should else 'FAIL'}] "
              f"{'caught' if got else 'allowed':<8} "
              f"({'must catch' if should else 'must allow'}): {label}")
    print(f"\nG40 self-test: {len(SELF_TEST) - bad}/{len(SELF_TEST)} passed")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()

    findings = scan()
    if findings:
        print(f"G40 FAIL — {len(findings)} live-operational key(s) found in a demo/QA fixture:\n")
        for rel, k, reason in findings:
            print(f"  {rel}: key={k!r}")
            print(f"      {reason}")
        print("\nA fixture read by scripts/ui-coverage/seed.sh seeds a fresh, EMPTY stack too — a")
        print("live-operational key here becomes another tenant's opening config on its first seed,")
        print("not just an overwrite risk. Remove the key/value from the fixture; the app already")
        print("degrades gracefully when it is absent (see e.g. GET /sync/registry -> {registry: []}).")
        return 1

    # [2026-08-23 G66/C] AN EMPTY SCAN IS A RED, NEVER A PASS. This repo has already lived the
    # other way: twelve gates globbed apps/*/blueprint/n8n/*.json after blueprints became
    # .workflow.ts in 52b32aa4, matched nothing, looped over nothing, and printed their success
    # line for weeks. Green and blind are indistinguishable from OUTSIDE, so nothing surfaced it.
    # The glob is right today; this guard is what makes it stay honest if the layout moves again.
    n_fx = len({q for g in FIXTURE_GLOBS for q in REPO.glob(g)})
    if not n_fx:
        print(f"G40 FAIL - scanned 0 fixture(s) matching {list(FIXTURE_GLOBS)!r}."
              f" That is not a clean run, it is no run.")
        return 1

    print(f"G40 PASS — no live-operational key found in any of "
          f"{len({q for g in FIXTURE_GLOBS for q in REPO.glob(g)})} fixture(s) matching "
          f"{list(FIXTURE_GLOBS)!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
