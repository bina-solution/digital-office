#!/usr/bin/env python3
"""Make suite corpora hash-DISJOINT so suites can run in parallel.

The pipeline dedups docs by md5-of-file-bytes; suites that source the SAME demo-doc
file collide (DOUBLE) when run concurrently. This generates per-suite byte-variants:
identical rendered content + a suite-tag trailer (PDF: comment after %%EOF; PNG:
bytes after IEND — both ignored by renderers/Tesseract) => distinct hashes.

For each variant it also CLONES the ai_extraction_cache fixture row (cache_key =
<kind>:<md5>) so cached AI extraction keeps hitting. OCR is NOT cloned — apitools
re-runs Tesseract per new hash (per ruling: OCR really runs; identical pixels =>
identical results). Suite workflow Configs are repointed to the variant paths.

Idempotent: re-running regenerates the same variants (content-addressed by input).
"""
import hashlib, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, 'production', 'n8n', 'demo-docs')
CACHE = os.path.join(ROOT, 'production', 'n8n', 'fixtures', 'ai-extraction-cache.json')

# suite tag -> (workflow code file, shared source paths to variant). Blueprints are
# *.workflow.ts (ai/context/n8n-as-code-migration.md); the doc paths live in code/expression
# strings, so the same text replace applies. Falls back to the legacy .json mid-migration.
SUITES = {
    'dbf': ('apps/indox/blueprint/n8n/indoxV2DocBaseTest01.workflow.ts', [
        'balance_sheet/files/asyp-shr-ts-1.pdf', 'invoice/files/agn-3.pdf',
        'order/files/PO25010001.png', 'shipment/files/by-gy-4.pdf']),
    'plp': ('apps/indox/blueprint/n8n/indoxV2PipelineTest01.workflow.ts', [
        'balance_sheet/files/asyp-shr-ts-1.pdf', 'balance_sheet/files/asyp-shr-ts-2.pdf',
        'balance_sheet/files/khhn-pvr-1.pdf', 'invoice/files/agn-3.pdf',
        'invoice/files/arkhh-3.pdf', 'invoice/files/khpr-mnhm-5.pdf',
        'invoice/files/nbl-3.pdf', 'invoice/files/ysh-krtvn-4.pdf',
        'order/files/PO25010001.png', 'order/files/PO25010002.png',
        'order/files/PO25010003.png', 'order/files/PO25010004.png',
        'order/files/PO25010005.png', 'shipment/files/by-gy-4.pdf',
        'shipment/files/dyavr-4.pdf', 'shipment/files/mbnh-drvm-1.pdf',
        'shipment/files/pvlyrn-5.pdf', 'shipment/files/sbh-5.pdf']),
}
# gdoc + bs keep the ORIGINAL files (gdoc has KW pins tied to its corpus; bs is disjoint).

def variant_path(rel, tag):
    base, ext = rel.rsplit('.', 1)
    return f'{base}.{tag}.{ext}'

def md5(b): return hashlib.md5(b).hexdigest()

cache = json.load(open(CACHE, encoding='utf-8'))
by_key = {r['cache_key']: r for r in cache}
added_rows, made = 0, 0

for tag, (wf_rel, rels) in SUITES.items():
    wf_path = os.path.join(ROOT, wf_rel)
    if not os.path.exists(wf_path) and wf_rel.endswith('.workflow.ts'):
        wf_path = os.path.join(ROOT, wf_rel[:-len('.workflow.ts')] + '.json')  # pre-flip fallback
    wf = open(wf_path, encoding='utf-8').read()
    for rel in rels:
        src = os.path.join(DOCS, rel.replace('/', os.sep))
        data = open(src, 'rb').read()
        trailer = (b'\n%%variant:' if rel.endswith('.pdf') else b'variant:') + tag.encode() + b'\n'
        vdata = data + trailer
        vrel = variant_path(rel, tag)
        vabs = os.path.join(DOCS, vrel.replace('/', os.sep))
        with open(vabs, 'wb') as fh:
            fh.write(vdata)
        made += 1
        # clone every cache row of the ORIGINAL hash under the variant hash
        oh, vh = md5(data), md5(vdata)
        for key, row in list(by_key.items()):
            kind, _, h = key.partition(':')
            if h == oh:
                nk = f'{kind}:{vh}'
                if nk not in by_key:
                    by_key[nk] = {**row, 'cache_key': nk}
                    added_rows += 1
        # repoint the suite Config at the variant
        if rel in wf:
            wf = wf.replace(rel, vrel)
    open(wf_path, 'w', encoding='utf-8').write(wf)
    print(f'{tag}: {len(rels)} variants, config repointed ({wf_rel})')

json.dump(sorted(by_key.values(), key=lambda r: r['cache_key']),
          open(CACHE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(f'variants written: {made}; cache rows added: {added_rows}; cache total: {len(by_key)}')
