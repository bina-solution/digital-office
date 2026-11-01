#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_corpus.py — builds the E2E load-test document corpus + the `loadtest` demo blueprint that
`bbox indox demo run loadtest` consumes (after patch_inject_workflow.py + provision.py have run).

PIVOT (2026-08-06, coordinator-approved): real PDF bytes are now sourced by COPYING from the
existing `data/data-set-2/{invoice,shipment,unknown,balance_sheet}/` fixture corpus (1,633 real,
previously-verified documents with real company names/dates/amounts already in their dataset.csv)
instead of live-rendering via apitools. Live rendering measured at ~8-9s/doc (apitools CPU-bound,
drove host RAM to 221MB free + 1.6GB swapped mid-run) — ~2-2.5 CPU-hours just to generate 1,000
files, before any injection starts, on a host that already OOM-kills at low memory. Reusing real
fixture bytes is near-instant (file copies) and is not "fakier" — same real PDFs, same real
extracted content, just not freshly rendered. TYPE is deliberately NOT set from the fixture's own
label — only the mail/drive BUCKET the file is placed in (folder-routed, exactly how the real
production pipes classify by source folder) is under our control; the real pipeline's own AI
classifier decides TYPE from content, same as any real client document. This is more faithful to
"no fakery" than the original apitools-render plan, not less.

Split, per the owner's spec, applied at whatever --count is given:
  50% -> e2e-mail (LOCAL MAIL engine): grouped into emails of 1-3 attachments each, varied senders
         (one synthetic @e2e-loadtest.local address per real company from the fixture)
  50% -> e2e-drive-gdoc / e2e-drive-bs (LOCAL drive engine, second source path)
  Within each half: ~96% gdoc / ~4% bs (the owner's ~24,000:1,000 ratio)
  count<=3 (single/tiny proof runs): deterministic mail-first allocation instead of ratio math, so
  a single-document test always exercises the primary (mail) path with a general doc.

Every artifact carries the e2e-loadtest marker: filenames are prefixed `E2ELT_`, sender addresses are
on `*.e2e-loadtest.local` — on top of the SYNC_NAME the pipes stamp on every ingested row (e2e-mail /
e2e-drive-gdoc / e2e-drive-bs), which is the primary marker. doc_id/invoice numbers are left as the
fixture's own REAL values (overriding a real document's real invoice number would itself be fakery).

Usage:
  python3 gen_corpus.py --count 1000 --outdir <state-dir> --provision <state-dir>/provision.json
"""
import argparse
import csv
import json
import os
import random
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DEMO_DIR = os.path.join(ROOT, "apps", "indox", "blueprint", "demo")
FILES_DIR = os.path.join(ROOT, "apps", "indox", "blueprint", "demo-docs", "e2e-loadtest", "files")
FIXTURE_ROOT = os.path.join(ROOT, "data", "data-set-2")
GDOC_FOLDERS = ["invoice", "shipment", "unknown"]
BS_FOLDER = "balance_sheet"


def load_fixture_pool(folder):
    csvp = os.path.join(FIXTURE_ROOT, folder, "dataset.csv")
    rows = []
    if not os.path.exists(csvp):
        return rows
    with open(csvp, encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            lp = (r.get("LOCAL_PATH") or "").strip()
            if not lp:
                continue
            full = os.path.join(FIXTURE_ROOT, folder, lp)
            if not os.path.exists(full):
                continue
            rows.append({
                "folder": folder, "local_path": full,
                "ext": full.rsplit(".", 1)[-1].lower(),
                "company_id": (r.get("COMPANY_ID") or "").strip() or "000000000",
                "company_name": (r.get("COMPANY_NAME") or "").strip() or "Unknown Supplier",
                "doc_date": (r.get("DOC_DATE") or "").strip(),
            })
    return rows


def alloc_pattern(count, gdoc_ratio):
    """List of (bucket, subtype) pairs, length == count."""
    if count <= 3:
        base = [("mail", "gdoc"), ("drive", "gdoc"), ("mail", "bs")]
        return base[:count]
    half = count // 2
    pattern = []
    for bucket, n in (("mail", half), ("drive", count - half)):
        n_bs = max(1, round(n * (1 - gdoc_ratio))) if n > 0 else 0
        n_gdoc = n - n_bs
        pattern += [(bucket, "gdoc")] * n_gdoc + [(bucket, "bs")] * n_bs
    return pattern


def build_plan(count, gdoc_ratio, rnd):
    pattern = alloc_pattern(count, gdoc_ratio)
    rnd.shuffle(pattern)
    gdoc_pool = []
    for folder in GDOC_FOLDERS:
        gdoc_pool += load_fixture_pool(folder)
    bs_pool = load_fixture_pool(BS_FOLDER)
    rnd.shuffle(gdoc_pool)
    rnd.shuffle(bs_pool)
    need_gdoc = sum(1 for _, s in pattern if s == "gdoc")
    need_bs = sum(1 for _, s in pattern if s == "bs")
    if need_gdoc > len(gdoc_pool) or need_bs > len(bs_pool):
        raise RuntimeError(
            f"fixture corpus too small: need {need_gdoc} gdoc (/{len(gdoc_pool)} available), "
            f"{need_bs} bs (/{len(bs_pool)} available) — data/data-set-2 has {len(gdoc_pool)+len(bs_pool)} "
            f"files total; reduce --count or extend the fixture set for a larger run")
    gi = bi = 0
    plan = []
    os.makedirs(FILES_DIR, exist_ok=True)
    for idx, (bucket, subtype) in enumerate(pattern, start=1):
        if subtype == "gdoc":
            src = gdoc_pool[gi]; gi += 1
        else:
            src = bs_pool[bi]; bi += 1
        base = os.path.basename(src["local_path"])
        fname = f"E2ELT_{idx:05d}_{base}"
        dst = os.path.join(FILES_DIR, fname)
        shutil.copyfile(src["local_path"], dst)
        plan.append({
            "idx": idx, "bucket": bucket, "subtype": subtype,
            "company_id": src["company_id"], "company_name": src["company_name"],
            "sender_email": f"ap-{src['company_id']}@e2e-loadtest.local",
            "doc_date": src["doc_date"], "filename": fname, "source_fixture": src["folder"],
        })
    return plan


def group_mail_items(mail_items, rnd):
    """1-3 attachments per email, sequential grouping so a group never mixes companies
    (a real vendor email carries only that vendor's documents)."""
    by_company = {}
    for it in mail_items:
        by_company.setdefault(it["company_id"], []).append(it)
    groups = []
    gi = 0
    for co_id, items in by_company.items():
        rnd.shuffle(items)
        i = 0
        while i < len(items):
            size = rnd.choice([1, 2, 3])
            chunk = items[i:i + size]
            gi += 1
            gid = f"g{gi:05d}"
            for it in chunk:
                it["group"] = gid
            groups.append(chunk)
            i += size
    return groups


def yaml_dump_syncs(plan, mail_groups):
    """Hand-rolled, deterministic YAML for the syncs: block (avoids a pyyaml dependency mismatch
    with demo.py's own loader and keeps key order stable for review). No doc_id/type fields —
    those aren't read by the e2e-* Build nodes and fabricating them would misrepresent real files.
    Every line is built explicitly with its final indentation — no textwrap.dedent() over content
    that itself contains embedded newlines/indentation, which silently defeats dedent's common-
    leading-whitespace algorithm (a real bug caught on the first single-doc test run)."""
    lines = ["syncs:", "  e2e-mail:"]

    def entry_lines(it, extra=None):
        L = [f"  - name: {it['filename']}",
             f"    path: e2e-loadtest/files/{it['filename']}",
             f"    company_id: '{it['company_id']}'",
             f"    sender_name: {json.dumps(it['company_name'], ensure_ascii=False)}",
             f"    sender_email: {it['sender_email']}"]
        if extra:
            for k, v in extra.items():
                L.append(f"    {k}: {v}")
        return L

    for grp in mail_groups:
        for it in grp:
            lines.extend(entry_lines(it, {"group": it["group"]}))
    drive_items = [it for it in plan if it["bucket"] == "drive"]
    for key in ("gdoc", "bs"):
        lines.append(f"  e2e-drive-{key}:")
        for it in [x for x in drive_items if x["subtype"] == key]:
            lines.extend(entry_lines(it))
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=1000)
    ap.add_argument("--gdoc-ratio", type=float, default=0.96)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--provision", required=True)
    ap.add_argument("--deployment-name", default="shlomo-laptop")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    rnd = random.Random(a.seed)

    with open(a.provision, encoding="utf-8") as f:
        prov = json.load(f)

    plan = build_plan(a.count, a.gdoc_ratio, rnd)
    print(f"[gen_corpus] plan: {len(plan)} docs "
          f"(mail={sum(1 for p in plan if p['bucket']=='mail')}, drive={sum(1 for p in plan if p['bucket']=='drive')}, "
          f"bs={sum(1 for p in plan if p['subtype']=='bs')}, gdoc={sum(1 for p in plan if p['subtype']=='gdoc')})")
    print(f"[gen_corpus] {len(plan)} real fixture files copied to {FILES_DIR}")

    mail_items = [p for p in plan if p["bucket"] == "mail"]
    mail_groups = group_mail_items(mail_items, rnd)
    n_emails = len(mail_groups)
    print(f"[gen_corpus] {len(mail_items)} mail docs grouped into {n_emails} emails "
          f"(avg {len(mail_items)/max(n_emails,1):.2f} attachments/email)")

    companies = {}
    for p in plan:
        companies[p["company_id"]] = p["company_name"]
    company_lines = []
    for cid, name in companies.items():
        company_lines.append(f"- id: '{cid}'")
        company_lines.append(f"  name: {json.dumps(name, ensure_ascii=False)}")
        company_lines.append(f"  email: ap-{cid}@e2e-loadtest.local")

    header_lines = [
        "# AUTO-GENERATED by scripts/ops/e2e-loadtest/gen_corpus.py — do not hand-edit.",
        f"# E2E load-test blueprint — {a.count} documents (real fixture bytes from data/data-set-2),",
        f"# mail+drive split, ~{a.gdoc_ratio:.0%} gdoc / {1-a.gdoc_ratio:.0%} bs.",
        "# Marker: filenames E2ELT_*, sender domain *@e2e-loadtest.local,",
        "#         SYNC_NAME in (e2e-mail, e2e-drive-gdoc, e2e-drive-bs).",
        "# Cleanup: scripts/ops/e2e-loadtest-cleanup.sql",
        "name: loadtest",
        f'description: "E2E load-test — {a.count} real documents via LOCAL MAIL + LOCAL DRIVE"',
        f"mail_connection_id: {prov['mail_connection_id']}",
        f"drive_connection_id: {prov['drive_connection_id']}",
        "drive_folders:",
        f"  gdoc_to_sync: {prov['drive_folders']['gdoc_to_sync']}",
        f"  bs_to_sync: {prov['drive_folders']['bs_to_sync']}",
        "companies:",
    ] + company_lines

    yml_path = os.path.join(DEMO_DIR, "loadtest.yml")
    with open(yml_path, "w", encoding="utf-8") as f:
        f.write("\n".join(header_lines) + "\n")
        f.write(yaml_dump_syncs(plan, mail_groups))

    with open(os.path.join(a.outdir, "plan.json"), "w", encoding="utf-8") as f:
        json.dump({"plan": plan, "mail_groups": [[it["filename"] for it in g] for g in mail_groups]}, f, ensure_ascii=False)

    print(f"[gen_corpus] wrote {yml_path}")
    print("[gen_corpus] next: bbox indox demo run loadtest --wait")


if __name__ == "__main__":
    main()
