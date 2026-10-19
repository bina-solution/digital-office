#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Keep the E2E fixture corpus DATED RELATIVE TO NOW.

WHY THIS EXISTS
---------------
INDOX terminalises any document whose content date is older than
`settings.OldDocumentMonthsBack` months as `STATUS=OLD`. That rule is wall-clock
relative. `apps/indox/blueprint/demo-docs/` is a fixed snapshot of real (anonymised)
2025 documents. So every suite lane that asserts "this document reaches COMPLETED" is
asserting something that stops being true the moment the corpus ages past the window —
and it is the CORPUS that is wrong, not the product.

Until 2026-08-06 nobody noticed, because `indoxV2TestFixtures01` seeded
`OldDocumentMonthsBack=1200` from `fixtures/settings.json` before every suite: the
suites ran with a 100-year window and never exercised the rule at all. That seeding was
removed the same day (it clobbered operator config), the suites started running at the
configured value of 6 — and the stale corpus surfaced as `STATUS:OLD` failures.

The fix is NOT to widen the window for the tests: that re-hides the rule and re-creates
the defect that was just removed. The fix is a corpus whose printed dates are computed
from the clock at seed time. This script is that generator, and `bbox indox test` calls
it in `--check` mode before every run (see apps/indox/hooks/test.py), so a fresh clone
six months from now re-stamps the corpus instead of going red.

WHAT IT DOES
------------
For each target below it replaces the PRINTED date on the document — the same pixels
Tesseract reads — with a date computed from the database clock, then re-OCRs through
apitools to prove the new date is readable and the old one is gone. It then repairs
everything keyed to the file's bytes: the committed AI-extraction cache fixture
(`fixtures/ai-extraction-cache.json`, keyed by md5), the unique-corpus map, and a new
manifest `demo-docs/fixtures/corpus-dates.json` recording the anchor and both hashes.

Usage:
  python3 scripts/refresh-corpus-dates.py --check      # exit 1 if the corpus needs a refresh
  python3 scripts/refresh-corpus-dates.py              # re-stamp whatever is stale
  python3 scripts/refresh-corpus-dates.py --force      # re-stamp everything
  python3 scripts/refresh-corpus-dates.py --purge-uploads
        # ALSO drop the already-uploaded copies from drive_files, so the suites upload the
        # refreshed bytes instead of reusing what they uploaded before the refresh. Needed
        # on a stack that has run the suites before; a no-op on a fresh clone.

Requires only python3 + docker on the host: the OCR and the stamping both run inside the
apitools container (scripts/refresh-corpus-dates.worker.py), which is the engine the
pipeline itself uses.
"""
import argparse
import datetime as dt
import hashlib
import io
import json
import os
import subprocess
import sys

# These suites print Hebrew document text. On a host whose stdout is not already UTF-8 that
# raises UnicodeEncodeError on the first Hebrew character, and the traceback reads as a
# test failure rather than an encoding one. Same guard the gates use. (G10)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, 'apps', 'indox', 'blueprint', 'demo-docs')
FIXTURES = os.path.join(ROOT, 'apps', 'indox', 'blueprint', 'fixtures')
MANIFEST = os.path.join(DOCS, 'fixtures', 'corpus-dates.json')
WORKER = os.path.join(ROOT, 'scripts', 'refresh-corpus-dates.worker.py')

# ── the targets ───────────────────────────────────────────────────────────────────────
# Only documents whose lane asserts a NON-terminal outcome (COMPLETED) belong here: a
# fixture that must age out (pipeline's `plc_old` coverage case, seeded DOC_DATE
# 01/01/2020) is deliberately absent — that one is SUPPOSED to be old.
#
# `token` is the date exactly as OCR reads it off the page, `offset_days` how far before
# the anchor to place it. Two dates on one document keep their relative order (a shipment
# printed the day after its delivery note still reads that way).
TARGETS = [
    {'path': 'invoice/files/agn-3.plb.pdf', 'kind': 'invoice',
     'lane': 'pipeline/bare plb_inv', 'upload_prefix': 'plb_',
     # 22/04/25 sits under `תאריך חשבונית` (verified against the real base query,
     # settings.q_v3_date_base -> apitools /documentJsonQuery: result "22/04/25", matched on
     # "תאריך חשבונית"). 31/08/25 is the `לתשלום עד` payment-due date — refreshed with it so
     # the invoice does not end up dated 2026 with a 2025 due date.
     'dates': [{'token': '22/04/25', 'fmt': '%d/%m/%y', 'offset_days': 30},
               {'token': '31/08/25', 'fmt': '%d/%m/%y', 'offset_days': -100}]},
    {'path': 'order/files/PO25010001.plb.png', 'kind': 'invoice',
     'lane': 'pipeline/bare plb_ord', 'upload_prefix': 'plb_',
     'dates': [{'token': '05/11/2025', 'fmt': '%d/%m/%Y', 'offset_days': 30}]},
    {'path': 'shipment/files/by-gy-4.plb.pdf', 'kind': 'invoice',
     'lane': 'pipeline/bare plb_shp', 'upload_prefix': 'plb_',
     'dates': [{'token': '18/11/25', 'fmt': '%d/%m/%y', 'offset_days': 30},
               {'token': '17/11/25', 'fmt': '%d/%m/%y', 'offset_days': 31},
               {'token': '17/11/2025', 'fmt': '%d/%m/%Y', 'offset_days': 31}]},
    # [2026-08-22] gdoc's lifecycle document (gdt_lc_1), uploaded as fxgd-dltvt-tyyr-2.pdf.
    # It asserts COMPLETED, so by this list's own inclusion rule it always belonged here and was
    # simply never added: TARGETS covered the pipeline lane only, the manifest tracked three
    # files, and --check answered "fresh" about those three while saying nothing about this one.
    # gdoc's lifecycle therefore ended at OLD with the refresher reporting success.
    # Tokens read off the page by apitools /documentOcr on the real file:
    #   08/12/25  under `תאריך`        -> the document date, 8.5 months back, past the 6-month
    #                                     cutoff. THIS is what aged the row out.
    #   30/04/26  under `תאריך פרעון`  -> the payment-due date, carried so the invoice does not
    #                                     end up dated 2026 with a stale due date. Same reasoning
    #                                     as the `לתשלום עד` token on agn-3 above.
    # The original doc->due gap is 143 days; placing the document at anchor-30 puts the due date
    # at anchor+113, which preserves it exactly.
    {'path': 'invoice/files/dltvt-tyyr-2.pdf', 'kind': 'invoice',
     'lane': 'gdoc/lifecycle gdt_lc_1', 'upload_prefix': 'fxgd-',
     'dates': [{'token': '08/12/25', 'fmt': '%d/%m/%y', 'offset_days': 30},
               {'token': '30/04/26', 'fmt': '%d/%m/%y', 'offset_days': -113}]},
    # [2026-08-23] gdoc CHECK 5's fifteen batch fixtures (gdx_inv1-5 / gdx_ord1-5 / gdx_shp1-5).
    # Measured cause, not a guess: with a 6-month window (cutoff 2026-02-23) these documents
    # carried 2025 dates, so base extraction ran, stamped API_TOOLS_ID, and the row was then
    # aged out to OLD -- 16 rows in one run. --check answered 'fresh' throughout, because it
    # only inspects files in this list, and this list covered the .plb. COPIES of three of them
    # (agn-3.plb.pdf, PO25010001.plb.png, by-gy-4.plb.pdf) while the batch reads the PLAIN
    # files. Same documents, different filenames: agn-3.pdf OCRs to 22/04/25 + 31/08/25, byte
    # for byte the tokens already declared for agn-3.plb.pdf above.
    # Every token below was read off the real file by apitools /documentOcr?cache=false, and the
    # first token of each entry is the DOCUMENT date -- the one the OLD gate compares. The
    # offsets preserve each document's internal gaps (invoice->due, teuda->hafatsa) so a
    # refreshed file stays internally consistent instead of being dated 2026 with a 2025 due
    # date. gdx_shp4 (sbh-5.pdf, 09/04/26) is already inside the window and is listed anyway:
    # it is the one shipment that reaches COMPLETED today, and leaving it unmanaged is how the
    # other fourteen got here.
    {'path': 'invoice/files/khpr-mnhm-5.pdf', 'kind': 'invoice',
     'lane': 'gdoc/batch gdx_inv1', 'upload_prefix': 'gdx_inv1-',
     'dates': [{'token': '30/10/25', 'fmt': '%d/%m/%y', 'offset_days': 30},
               {'token': '31/01/26', 'fmt': '%d/%m/%y', 'offset_days': -63}]},
    {'path': 'invoice/files/nbl-3.pdf', 'kind': 'invoice',
     'lane': 'gdoc/batch gdx_inv2', 'upload_prefix': 'gdx_inv2-',
     'dates': [{'token': '30/06/25', 'fmt': '%d/%m/%y', 'offset_days': 30}]},
    {'path': 'invoice/files/agn-3.pdf', 'kind': 'invoice',
     'lane': 'gdoc/batch gdx_inv3', 'upload_prefix': 'gdx_inv3-',
     'dates': [{'token': '22/04/25', 'fmt': '%d/%m/%y', 'offset_days': 30},
               {'token': '31/08/25', 'fmt': '%d/%m/%y', 'offset_days': -101}]},
    {'path': 'invoice/files/arkhh-3.pdf', 'kind': 'invoice',
     'lane': 'gdoc/batch gdx_inv4', 'upload_prefix': 'gdx_inv4-',
     'dates': [{'token': '29/05/25', 'fmt': '%d/%m/%y', 'offset_days': 30},
               {'token': '10/06/25', 'fmt': '%d/%m/%y', 'offset_days': 18}]},
    {'path': 'invoice/files/ysh-krtvn-4.pdf', 'kind': 'invoice',
     'lane': 'gdoc/batch gdx_inv5', 'upload_prefix': 'gdx_inv5-',
     'dates': [{'token': '14/01/26', 'fmt': '%d/%m/%y', 'offset_days': 30},
               {'token': '01/05/26', 'fmt': '%d/%m/%y', 'offset_days': -77}]},
    {'path': 'order/files/PO25010001.png', 'kind': 'invoice',
     'lane': 'gdoc/batch gdx_ord1', 'upload_prefix': 'gdx_ord1-',
     'dates': [{'token': '05/11/2025', 'fmt': '%d/%m/%Y', 'offset_days': 30}]},
    {'path': 'order/files/PO25010002.png', 'kind': 'invoice',
     'lane': 'gdoc/batch gdx_ord2', 'upload_prefix': 'gdx_ord2-',
     'dates': [{'token': '12/11/2025', 'fmt': '%d/%m/%Y', 'offset_days': 30}]},
    {'path': 'order/files/PO25010003.png', 'kind': 'invoice',
     'lane': 'gdoc/batch gdx_ord3', 'upload_prefix': 'gdx_ord3-',
     'dates': [{'token': '20/11/2025', 'fmt': '%d/%m/%Y', 'offset_days': 30}]},
    {'path': 'order/files/PO25010004.png', 'kind': 'invoice',
     'lane': 'gdoc/batch gdx_ord4', 'upload_prefix': 'gdx_ord4-',
     'dates': [{'token': '28/11/2025', 'fmt': '%d/%m/%Y', 'offset_days': 30}]},
    {'path': 'order/files/PO25010005.png', 'kind': 'invoice',
     'lane': 'gdoc/batch gdx_ord5', 'upload_prefix': 'gdx_ord5-',
     'dates': [{'token': '03/12/2025', 'fmt': '%d/%m/%Y', 'offset_days': 30}]},
    {'path': 'shipment/files/by-gy-4.pdf', 'kind': 'invoice',
     'lane': 'gdoc/batch gdx_shp1', 'upload_prefix': 'gdx_shp1-',
     'dates': [{'token': '18/11/25', 'fmt': '%d/%m/%y', 'offset_days': 30},
               {'token': '17/11/25', 'fmt': '%d/%m/%y', 'offset_days': 31},
               {'token': '17/11/2025', 'fmt': '%d/%m/%Y', 'offset_days': 31}]},
    {'path': 'shipment/files/dyavr-4.pdf', 'kind': 'invoice',
     'lane': 'gdoc/batch gdx_shp2', 'upload_prefix': 'gdx_shp2-',
     'dates': [{'token': '18/01/26', 'fmt': '%d/%m/%y', 'offset_days': 30}]},
    {'path': 'shipment/files/mbnh-drvm-1.pdf', 'kind': 'invoice',
     'lane': 'gdoc/batch gdx_shp3', 'upload_prefix': 'gdx_shp3-',
     'dates': [{'token': '09/06/25', 'fmt': '%d/%m/%y', 'offset_days': 30},
               {'token': '10/06/25', 'fmt': '%d/%m/%y', 'offset_days': 29}]},
    {'path': 'shipment/files/sbh-5.pdf', 'kind': 'invoice',
     'lane': 'gdoc/batch gdx_shp4', 'upload_prefix': 'gdx_shp4-',
     'dates': [{'token': '09/04/26', 'fmt': '%d/%m/%y', 'offset_days': 30}]},
    {'path': 'shipment/files/pvlyrn-5.pdf', 'kind': 'invoice',
     'lane': 'gdoc/batch gdx_shp5', 'upload_prefix': 'gdx_shp5-',
     'dates': [{'token': '03/06/25', 'fmt': '%d/%m/%y', 'offset_days': 30}]},
    # [2026-08-23] THE UPLOAD NAMES EMBED A CONTENT HASH, and it is a FOURTH reader of a date
    # this script moves. The suite uploads as plp_inv1-khpr-mnhm-5.a8896d.pdf -- that a8896d is
    # an md5 prefix. Re-stamping changes the file's md5, the literal in the suite does not move,
    # and the already-uploaded copy under the old name is found and reused: the documents then
    # extract the PREVIOUS date while the ground truth carries the new one, which is exactly the
    # 'completed=3/17, LOCAL.date 30/10/2025 != 24/07/2026' this run reported. The prefixes
    # below were read out of drive_files rather than guessed -- the first pass assumed plx_ from
    # the row ids and purged 2 of 17.
    # [2026-08-23] THE PIPELINE BATCH -- all seventeen .plp. fixtures, none of which had ever
    # been listed. Measured, not assumed: 16 of the 17 came back STATUS:OLD in pipeline check 2
    # (completed=1/17), and the ONE that passed is plx_shp4, whose page prints 09/04/26 -- the
    # only date inside the 6-month window. Every token below was read off the document through
    # the live q_v3_date_base via apitools /documentJsonQuery, so these are the pixels the
    # extractor actually reads rather than the literals the suite happens to expect.
    {'path': 'balance_sheet/files/asyp-shr-ts-2.plp.pdf', 'kind': 'invoice',
     'lane': 'pipeline/batch plx_bs1', 'upload_prefix': 'plx_bs1-',
     'dates': [{'token': '05/11/25', 'fmt': '%d/%m/%y', 'offset_days': 30}]},
    {'path': 'balance_sheet/files/khhn-pvr-1.plp.pdf', 'kind': 'invoice',
     'lane': 'pipeline/batch plx_bs2', 'upload_prefix': 'plx_bs2-',
     'dates': [{'token': '03/11/25', 'fmt': '%d/%m/%y', 'offset_days': 30}]},
    {'path': 'invoice/files/khpr-mnhm-5.plp.pdf', 'kind': 'invoice',
     'lane': 'pipeline/batch plx_inv1', 'upload_prefix': 'plp_inv1-',
     'dates': [{'token': '30/10/25', 'fmt': '%d/%m/%y', 'offset_days': 30}]},
    {'path': 'invoice/files/nbl-3.plp.pdf', 'kind': 'invoice',
     'lane': 'pipeline/batch plx_inv2', 'upload_prefix': 'plp_inv2-',
     'dates': [{'token': '30/06/25', 'fmt': '%d/%m/%y', 'offset_days': 30}]},
    {'path': 'invoice/files/agn-3.plp.pdf', 'kind': 'invoice',
     'lane': 'pipeline/batch plx_inv3', 'upload_prefix': 'plp_inv3-',
     'dates': [{'token': '22/04/25', 'fmt': '%d/%m/%y', 'offset_days': 30}]},
    {'path': 'invoice/files/arkhh-3.plp.pdf', 'kind': 'invoice',
     'lane': 'pipeline/batch plx_inv4', 'upload_prefix': 'plp_inv4-',
     'dates': [{'token': '29/05/25', 'fmt': '%d/%m/%y', 'offset_days': 30}]},
    {'path': 'invoice/files/ysh-krtvn-4.plp.pdf', 'kind': 'invoice',
     'lane': 'pipeline/batch plx_inv5', 'upload_prefix': 'plp_inv5-',
     'dates': [{'token': '14/01/26', 'fmt': '%d/%m/%y', 'offset_days': 30}]},
    {'path': 'order/files/PO25010001.plp.png', 'kind': 'invoice',
     'lane': 'pipeline/batch plx_ord1', 'upload_prefix': 'plp_ord1-',
     'dates': [{'token': '05/11/2025', 'fmt': '%d/%m/%Y', 'offset_days': 30}]},
    {'path': 'order/files/PO25010002.plp.png', 'kind': 'invoice',
     'lane': 'pipeline/batch plx_ord2', 'upload_prefix': 'plp_ord2-',
     'dates': [{'token': '12/11/2025', 'fmt': '%d/%m/%Y', 'offset_days': 30}]},
    {'path': 'order/files/PO25010003.plp.png', 'kind': 'invoice',
     'lane': 'pipeline/batch plx_ord3', 'upload_prefix': 'plp_ord3-',
     'dates': [{'token': '20/11/2025', 'fmt': '%d/%m/%Y', 'offset_days': 30}]},
    {'path': 'order/files/PO25010004.plp.png', 'kind': 'invoice',
     'lane': 'pipeline/batch plx_ord4', 'upload_prefix': 'plp_ord4-',
     'dates': [{'token': '28/11/2025', 'fmt': '%d/%m/%Y', 'offset_days': 30}]},
    {'path': 'order/files/PO25010005.plp.png', 'kind': 'invoice',
     'lane': 'pipeline/batch plx_ord5', 'upload_prefix': 'plp_ord5-',
     'dates': [{'token': '03/12/2025', 'fmt': '%d/%m/%Y', 'offset_days': 30}]},
    {'path': 'shipment/files/by-gy-4.plp.pdf', 'kind': 'invoice',
     'lane': 'pipeline/batch plx_shp1', 'upload_prefix': 'plp_shp1-',
     'dates': [{'token': '18/11/25', 'fmt': '%d/%m/%y', 'offset_days': 30}]},
    {'path': 'shipment/files/dyavr-4.plp.pdf', 'kind': 'invoice',
     'lane': 'pipeline/batch plx_shp2', 'upload_prefix': 'plp_shp2-',
     'dates': [{'token': '18/01/26', 'fmt': '%d/%m/%y', 'offset_days': 30}]},
    {'path': 'shipment/files/mbnh-drvm-1.plp.pdf', 'kind': 'invoice',
     'lane': 'pipeline/batch plx_shp3', 'upload_prefix': 'plp_shp3-',
     'dates': [{'token': '09/06/25', 'fmt': '%d/%m/%y', 'offset_days': 30}]},
    {'path': 'shipment/files/sbh-5.plp.pdf', 'kind': 'invoice',
     'lane': 'pipeline/batch plx_shp4', 'upload_prefix': 'plp_shp4-',
     'dates': [{'token': '09/04/26', 'fmt': '%d/%m/%y', 'offset_days': 30}]},
    {'path': 'shipment/files/pvlyrn-5.plp.pdf', 'kind': 'invoice',
     'lane': 'pipeline/batch plx_shp5', 'upload_prefix': 'plp_shp5-',
     'dates': [{'token': '03/06/25', 'fmt': '%d/%m/%y', 'offset_days': 30}]},
    {'path': 'balance_sheet/files/asyp-shr-ts-1.plp.pdf', 'kind': 'invoice',
     'lane': 'pipeline/bare plb_bs', 'upload_prefix': 'plb_',
     # [2026-08-23] NOW LISTED, and the note below is left in place because it is the thing
     # that was wrong. Measured against the live queries rather than reasoned about: both
     # q_v3_date_base and q_v3_date_bs, run through apitools /documentJsonQuery on this file
     # (md5 4546e87e19dd8f631af71cae821215ee), return "07/09/25" at matched_step 1. They do
     # NOT land on the card's 01/01/80 period boundary at all. 07/09/25 is 11.5 months before
     # 2026-08-23, so the 6-month OLD gate aged the document out and pipeline check 1 failed
     # with `plb_bs STATUS:OLD` -- exactly the failure this script exists to prevent, on the
     # one bare document that had been excused from it.
     'dates': [{'token': '07/09/25', 'fmt': '%d/%m/%y', 'offset_days': 30}]},
]
# SUPERSEDED 2026-08-23 -- kept as the record of a claim that was reasoned rather than run.
# The 4th bare document (balance_sheet/files/asyp-shr-ts-1.plp.pdf) is NOT listed: its
# only תאריך-labelled value is the card's `01/01/80` period boundary, which a 2-digit
# year parses forward, so it already passes. The lvyrvn-3/-5 cards the `bs` suite uses
# are not listed either — see the report: their DOC_DATE comes out 01/01/1980 because
# base extraction picks the `תאריך מ..עד` FILTER boundary, not a document date. Stamping
# that token would hide an extraction defect, not refresh a stale fixture.

TGT_BY_PATH = {t['path']: t for t in TARGETS}
DEPLOYMENT = None


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, **kw)


def docker(*args):
    """Reach the engine the same way the caller already does.

    Run from a shell, bare `docker` picks up whatever context that shell has — on this
    project's Windows/WSL host that is the WRONG engine, and the failure mode is a
    confident "container not found" rather than an error. Run from `bbox`, DOCKER_HOST is
    already exported and pointing at the right daemon, and adding our own -H produces
    "Cannot connect to tcp://localhost:2375/run/bbox-docker.sock". So: defer to
    DOCKER_HOST when it is set, otherwise name the project socket explicitly.
    """
    pre = []
    if not os.environ.get('DOCKER_HOST'):
        sock = os.environ.get('BBOX_DOCKER_SOCK', '/run/bbox-docker.sock')
        # BBOX_DOCKER_SOCK is a bare PATH (scripts/lib.sh exports DOCKER_HOST="unix://$it").
        # Passing the path to `docker -H` unprefixed makes the CLI read it as a path on the
        # default tcp host — "Cannot connect to tcp://localhost:2375/run/bbox-docker.sock".
        pre = ['-H', sock if '://' in sock else 'unix://' + sock]
    return sh(['docker'] + pre + list(args))


def env(key, default=''):
    path = os.path.join(ROOT, '.env')
    if os.path.exists(path):
        for line in open(path, encoding='utf-8', errors='replace'):
            if line.startswith(key + '='):
                return line.split('=', 1)[1].strip()
    return default


def psql(sql):
    global DEPLOYMENT
    DEPLOYMENT = DEPLOYMENT or env('DEPLOYMENT_NAME', 'shlomo-laptop')
    o = docker('exec', 'supabase-db-' + DEPLOYMENT, 'psql', '-U', 'postgres', '-d',
               'postgres', '-t', '-A', '-c', sql)
    if o.returncode != 0:
        sys.exit('psql failed: ' + o.stderr.decode('utf-8', errors='replace')[:300])
    return o.stdout.decode('utf-8', errors='replace').strip()


def db_now():
    """The clock the product compares against — never the host wall clock."""
    raw = psql('select to_char(now() at time zone \'UTC\', \'YYYY-MM-DD"T"HH24:MI:SS\');')
    return dt.datetime.strptime(raw, '%Y-%m-%dT%H:%M:%S')


def months_back():
    """The window THE PRODUCT will judge these documents by — not a second opinion about it.

    [2026-08-22] This read `OldDocumentMonthsBack` and nothing else. The decide gate reads
    `__CFG().old_document_months_back`:

        indoxV2ActionsGlobal01:1243
        try { const v = Number(__CFG().old_document_months_back); if (...) return v; } catch (e) {}
        return 6;

    Two names for one fact, and this deployment still carries a row `OldDocumentMonthsBack = 1200`
    — residue of the force-seed the 2026-08-06 change removed. So the checker resolved 1200,
    reported "fresh (OLD window 1200 months)" and re-stamped nothing, while decide resolved 6 and
    aged the corpus out. gdoc's lifecycle ended at OLD with the refresher reporting success:

        corpus DOC_DATEs  18/11/2025  29/05/2025  12/11/2025      cutoff 2026-02-22

    Fine for a hundred-year window, hopeless for a six-month one.

    The CamelCase row is deliberately NOT honoured, even as a fallback. The product does not read
    it, so honouring it here would recreate the exact disagreement this fixes — measured: with the
    fallback in place --check still answered "fresh (OLD window 1200 months)".

    Nor is 6 merely a default here. indoxV2ActionsGlobal01:998 records that __CFG() is empty on
    this path -- "0 of 96 sampled executions carried it, which also means every existing __CFG()
    consumer here has been silently using its hardcoded fallback" -- so the gate resolves 6
    regardless of any settings row. The snake_case read is kept so that if that channel is ever
    populated this follows the product rather than diverging from it again.
    """
    raw = psql("select value from settings where key='old_document_months_back' limit 1;")
    try:
        v = int(str(raw).strip())
        if v > 0:
            return v
    except (TypeError, ValueError):
        pass
    return 6


def md5_of(path):
    with open(path, 'rb') as fh:
        return hashlib.md5(fh.read()).hexdigest()


def load_manifest():
    try:
        return json.load(open(MANIFEST, encoding='utf-8'))
    except Exception:
        return {'anchor_utc': None, 'files': {}}


def stale(man, now, window_days):
    """A target is stale when it was never stamped, or its stamped date has drifted past
    HALF the OLD window. Half, not all, so `bbox indox test` never starts a suite with a
    fixture that will age out mid-battery."""
    bad = []
    for t in TARGETS:
        rec = (man.get('files') or {}).get(t['path'])
        if not rec:
            bad.append((t['path'], 'never stamped'))
            continue
        if rec.get('md5_new') != md5_of(os.path.join(DOCS, t['path'].replace('/', os.sep))):
            bad.append((t['path'], 'file changed since it was stamped'))
            continue
        try:
            d = dt.datetime.strptime(rec['doc_date'], '%Y-%m-%d')
        except Exception:
            bad.append((t['path'], 'unreadable stamped date'))
            continue
        age = (now - d).days
        if age > window_days / 2:
            bad.append((t['path'], 'stamped date is %d days old (window %d)' % (age, window_days)))
    return bad


def stamp(target, now, prev=None):
    """Re-stamp one document. `prev` is its manifest record from the last refresh.

    The token to replace is whatever is CURRENTLY printed — the original 2025 date on a
    virgin checkout, but the previous refresh's date on a stack that has been refreshed
    before. Reading it from the manifest is what makes this idempotent across months; a
    generator that always looked for the original token would silently no-op on its second
    run and then report a date the document does not carry.
    """
    rel = target['path']
    src = os.path.join(DOCS, rel.replace('/', os.sep))
    ext = rel.rsplit('.', 1)[-1].lower()
    old_md5 = md5_of(src)
    current = {}
    if prev:
        for r in prev.get('replacements', []):
            current[r['from']] = r['to']       # original token -> what is on the page now
    reps, doc_date = [], None
    for i, d in enumerate(target['dates']):
        new = now - dt.timedelta(days=d['offset_days'])
        if i == 0:
            doc_date = new
        frm = current.get(d['token'], d['token'])
        to = new.strftime(d['fmt'])
        if frm == to:
            continue                            # already carries exactly this date
        reps.append({'from': frm, 'to': to, 'origin': d['token']})
    if not reps:
        print('  %-42s already carries the target dates' % rel)
        return {'lane': target['lane'], 'kind': target['kind'],
                'md5_old': (prev or {}).get('md5_old', old_md5), 'md5_new': old_md5,
                'doc_date': doc_date.strftime('%Y-%m-%d'),
                'replacements': (prev or {}).get('replacements', [])}
    # Stamp in the container and leave the result there. Nothing is written back into the
    # repo until EVERY target has verified (see main): a half-refreshed corpus — some files
    # re-dated, the md5-keyed AI cache and the manifest still describing the old ones — is
    # worse than an unrefreshed one, and is exactly what an abort mid-loop used to leave.
    slot = '/tmp/_rcd_%s.%s' % (abs(hash(rel)) % 10 ** 8, ext)
    job = {'path': slot, 'ext': ext, 'replacements': reps}
    tmp = os.path.join(ROOT, 'ci-artifacts', '_rcd')
    os.makedirs(tmp, exist_ok=True)
    jf = os.path.join(tmp, 'job.json')
    json.dump(job, open(jf, 'w', encoding='utf-8'))
    docker('cp', src, 'apitools:' + slot)
    docker('cp', jf, 'apitools:/tmp/_rcd.job.json')
    docker('cp', WORKER, 'apitools:/tmp/_rcd_worker.py')
    o = docker('exec', 'apitools', 'python3', '/tmp/_rcd_worker.py',
               '/tmp/_rcd.job.json', '/tmp/_rcd.out.json')
    if o.returncode != 0:
        sys.exit('stamp worker failed for %s:\n%s' % (rel, o.stderr.decode(errors='replace')[-1500:]))
    o = docker('exec', 'apitools', 'cat', '/tmp/_rcd.out.json')
    res = json.loads(o.stdout.decode('utf-8', errors='replace'))
    if not res.get('ok'):
        sys.exit('NOT VERIFIED for %s: old still readable=%s, new readable=%s (expected %s), '
                 'tokens %s -> %s%s'
                 % (rel, res.get('still_present'), res.get('now_present'), res.get('expected'),
                    res.get('tokens_before'), res.get('tokens_after'),
                    '  ** CONTENT LOST **' if res.get('content_lost') else ''))
    print('  %-42s %s -> %s  [%s, %d pass%s] verified'
          % (rel, reps[0]['from'], reps[0]['to'], res['engine'], res['passes'],
             'es' if res['passes'] != 1 else ''))
    return {'lane': target['lane'], 'kind': target['kind'], 'md5_old': old_md5,
            '_slot': slot, '_src': src, 'md5_new': res['md5'],
            'doc_date': doc_date.strftime('%Y-%m-%d'),
            # `replacements` is keyed by the ORIGINAL token so the next refresh knows what
            # is on the page today; `applied` is what actually changed on THIS run, which
            # is what the AI-cache repair has to rewrite.
            'replacements': [{'from': r['origin'], 'to': r['to']} for r in reps],
            'applied': [{'from': r['from'], 'to': r['to']} for r in reps]}


def repair_suite_ground_truth(changed, wf, label):
    """gdoc check 5 compares GT === AI === KW. Its GT is a literal date in the suite itself.

    `Batch Config` in indoxV2GDocTest01 carries the expected values for the fifteen batch
    fixtures, each with a "date" field holding what the page printed WHEN THE ENTRY WAS WRITTEN.
    Re-stamping moves the page and leaves that literal behind, so every document then extracts
    correctly and disagrees with a ground truth that describes the previous corpus: the check
    reported "0/15 identical" with all fifteen extractions right.

    Exactly the same failure repair_ai_cache exists to prevent, one reader further along. A date
    this script moves has three committed readers -- the file, the AI cache, and this -- and a
    refresh that updates two of them is not a refresh.
    """
    # [2026-08-23] Now takes the suite as an argument. The pipeline batch has exactly the same
    # shape -- a "path"/"date" pair per fixture in its own Config -- and exactly the same
    # failure mode, which is what pipeline check 2 was reporting as 16/17 drifted.
    path = os.path.join(ROOT, 'apps', 'indox', 'blueprint', 'n8n', wf)
    if not os.path.exists(path):
        print('  ! %s not found - ground truth not repaired' % label)
        return
    src = io.open(path, encoding='utf-8', newline='').read()
    touched = 0
    for rel, rec in changed.items():
        base = rel.rsplit('/', 1)[-1]
        # the GT entry is identified by the fixture's file name, then its "date" literal is moved
        for r in rec.get('applied', []):
            old4, new4 = _four(r['from']), _four(r['to'])
            pat = '"path": "%s"' % rel
            i = src.find(pat)
            if i < 0:
                continue
            seg_end = src.find('}', i)
            seg = src[i:seg_end]
            for a, b in ((r['from'], r['to']), (old4, new4)):
                if '"date": "%s"' % a in seg:
                    seg = seg.replace('"date": "%s"' % a, '"date": "%s"' % b)
                    touched += 1
            src = src[:i] + seg + src[seg_end:]
    io.open(path, 'w', encoding='utf-8', newline='').write(src)
    print('  %s ground truth: %d date(s) moved' % (label, touched))

def repair_ai_cache(changed):
    """The committed AI-extraction cache is keyed by the file's md5 and carries the same
    date the document prints. Re-stamping changes both, so a refresh that skipped this
    would leave the AI half of base extraction silently unprimed."""
    path = os.path.join(FIXTURES, 'ai-extraction-cache.json')
    rows = json.load(open(path, encoding='utf-8'))
    by_key = {r['cache_key']: r for r in rows}
    touched = 0
    for rel, rec in changed.items():
        old_key = '%s:%s' % (rec['kind'], rec['md5_old'])
        row = by_key.get(old_key)
        if not row:
            print('  ! no AI-cache row for %s (%s) — nothing to rekey' % (rel, old_key))
            continue
        row['cache_key'] = '%s:%s' % (rec['kind'], rec['md5_new'])
        val = row['value']
        for r in rec.get('applied', []):
            # the cache stores dd/mm/yyyy even where the page prints dd/mm/yy
            old4 = _four(r['from'])
            new4 = _four(r['to'])
            val = val.replace(r['from'], r['to']).replace(old4, new4)
        row['value'] = val
        touched += 1
    json.dump(rows, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('  ai-extraction-cache.json: %d row(s) rekeyed' % touched)


def _four(tok):
    d, m, y = tok.split('/')
    return '%s/%s/%s' % (d, m, y if len(y) == 4 else '20' + y)


def repair_unique_map(changed):
    path = os.path.join(DOCS, 'fixtures', 'unique-corpus-map.json')
    try:
        rows = json.load(open(path, encoding='utf-8'))
    except Exception:
        return
    n = 0
    for row in rows:
        rec = changed.get(row.get('vrel'))
        if rec and row.get('new_md5') == rec['md5_old']:
            row['new_md5'] = rec['md5_new']
            n += 1
    json.dump(rows, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('  unique-corpus-map.json: %d row(s) updated' % n)


def purge_uploads(changed):
    """Drop the pre-refresh copies the suites uploaded, so `Need Upload?` re-uploads the
    refreshed bytes instead of reusing the stale ones.

    The suites resolve an existing upload by NAME (`Resolve Links A` matches
    `drive_files.name` against the lane's `upname`), so identical bytes are never
    re-fetched — which means a corpus refresh is invisible until the old row is gone.
    Purge by the lane's upload prefix, not by document name: that is exactly the set the
    refreshed files belong to, and nothing else. Backed up first (AGENTS.md)."""
    prefixes = sorted({TGT_BY_PATH[rel].get('upload_prefix') for rel in changed
                       if TGT_BY_PATH[rel].get('upload_prefix')})
    if not prefixes:
        print('  drive_files: no upload prefix declared — nothing purged')
        return
    like = ' OR '.join("name LIKE '%s%%'" % p.replace('_', r'\_') for p in prefixes)
    stamp_id = dt.datetime.utcnow().strftime('%Y%m%d%H%M%S')
    bak = 'bak_drive_files_corpusrefresh_' + stamp_id
    psql('CREATE TABLE %s AS SELECT * FROM drive_files WHERE %s;' % (bak, like))
    kept = psql('SELECT count(*) FROM %s;' % bak)
    psql('DELETE FROM drive_files WHERE %s;' % like)
    print('  drive_files: %s row(s) purged (backup: %s)' % (kept, bak))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--purge-uploads', action='store_true')
    a = ap.parse_args()

    now = db_now()
    window_days = months_back() * 30
    man = load_manifest()
    bad = stale(man, now, window_days)

    if a.check:
        if bad:
            print('[corpus-dates] STALE — %d fixture(s) need re-stamping:' % len(bad))
            for p, why in bad:
                print('   %-42s %s' % (p, why))
            sys.exit(1)
        print('[corpus-dates] fresh (anchor %s, OLD window %d months)'
              % (man.get('anchor_utc'), window_days // 30))
        sys.exit(0)

    todo = TARGETS if a.force else [t for t in TARGETS if t['path'] in {p for p, _ in bad}]
    if not todo:
        print('[corpus-dates] nothing to do (all fixtures inside the window)')
        return
    print('[corpus-dates] anchor %s (db clock), OLD window %d months, %d file(s)'
          % (now.strftime('%Y-%m-%d %H:%M:%S'), window_days // 30, len(todo)))
    changed = {}
    for t in todo:
        changed[t['path']] = stamp(t, now, (man.get('files') or {}).get(t['path']))
    # every target verified — only now does anything land in the working tree
    for rel, rec in changed.items():
        if rec.get('_slot'):
            docker('cp', 'apitools:' + rec['_slot'], rec['_src'])
            actual = md5_of(rec['_src'])
            if actual != rec['md5_new']:
                sys.exit('copy-back mismatch for %s: %s != %s' % (rel, actual, rec['md5_new']))
            print('  wrote %s  md5 %s -> %s' % (rel, rec['md5_old'][:8], actual[:8]))
        rec.pop('_slot', None)
        rec.pop('_src', None)
    repair_ai_cache(changed)
    repair_suite_ground_truth(changed, 'indoxV2GDocTest01.workflow.ts', 'indoxV2GDocTest01')
    repair_suite_ground_truth(changed, 'indoxV2PipelineTest01.workflow.ts', 'indoxV2PipelineTest01')
    repair_unique_map(changed)
    if a.purge_uploads:
        purge_uploads(changed)

    man['anchor_utc'] = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    man['old_window_months'] = window_days // 30
    man.setdefault('files', {}).update(changed)
    man['_readme'] = ('Generated by scripts/refresh-corpus-dates.py. doc_date is the date now '
                      'PRINTED on the document; the E2E lanes that assert COMPLETED depend on it '
                      'staying inside settings.OldDocumentMonthsBack.')
    os.makedirs(os.path.dirname(MANIFEST), exist_ok=True)
    json.dump(man, open(MANIFEST, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('[corpus-dates] manifest written: %s' % os.path.relpath(MANIFEST, ROOT))


if __name__ == '__main__':
    main()
