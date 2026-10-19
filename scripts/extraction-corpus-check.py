#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Standalone extraction-corpus check — the n8n pipeline, minus n8n.

Depends on apitools ONLY. Replicates EXACTLY what the live pipeline does:

  n8n `Load V3 Config`  -> here: the q_v3_% rows read from the DECLARATIVE fixture
                           (apps/indox/blueprint/fixtures/settings.json — the same rows
                           n8n-push seeds into the DB the workflows read).
  n8n `Fan Fields`      -> here: one /documentJsonQuery per (doc, field) from
                           cfg.q_v3_routing[category], sequentially per doc —
                           the n8n httpRequest node is sequential per item too.
  n8n `Collect`         -> here: identical value semantics (result.result;
                           matches[0].option when matches[]), identical _ERRORS
                           ("call died" is never conflated with "not on the doc").
  BFF scoring/dataset   -> IMPORTED from the BFF module itself (TYPES, truth,
                           corrected_truth, _score comparators, _score_doc) —
                           zero drift with the product by construction.

Env: APITOOLS_BASE (default http://127.0.0.1:8080), EXTRACTION_DATASET_DIR,
     SETTINGS_FIXTURE, CHECK_CONCURRENCY (doc-level pool, default 6),
     EXPECTED_DOCS / EXPECTED_VALUES / EXTRACTION_GATE_BUDGET_S for the verdict.
Exit 0 only on 100% accuracy, zero errors, inside the budget.
"""
from __future__ import annotations

import sys as _sys
# Prints Hebrew/bidi text. On a host whose stdout is not already UTF-8 that raises
# UnicodeEncodeError on the first Hebrew character, and the traceback reads as a logic
# failure rather than an encoding one. Same guard the gates use. (G10)
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(_sys.stderr, "reconfigure"):
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")


import io
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.environ.setdefault('EXTRACTION_DATASET_DIR', str(REPO / 'apps/indox/blueprint/demo-docs'))
os.environ.setdefault('EXTRACTION_RUNS_DIR', str(REPO / '.gate-tmp/runs'))
os.environ.setdefault('EXTRACTION_UPLOADS_DIR', str(REPO / '.gate-tmp/uploads'))
os.environ.setdefault('EXTRACTION_DRAW_CACHE_DIR', str(REPO / '.gate-tmp/draws'))
os.environ.setdefault('APITOOLS_BASE', 'http://127.0.0.1:8080')
sys.path.insert(0, str(REPO / 'apps/indox/app'))

from incoming_documents import extraction as ex  # noqa: E402  (the product's own logic)

SETTINGS_FIXTURE = Path(os.getenv('SETTINGS_FIXTURE', REPO / 'apps/indox/blueprint/fixtures/settings.json'))
# BFF dataset type -> Fan Fields CATEGORY (mirrors hooks jqexv3-run-{invoice,shipment,bs})
CATEGORY = {'invoice': 'invoice', 'shipment': 'shipment', 'balance_sheet': 'bs'}


COMPANIES_FIXTURE = Path(os.getenv(
    'COMPANIES_FIXTURE', REPO / 'apps/indox/blueprint/demo-docs/companies.json'))


def _registry_ids() -> list:
    """`Load V3 Config`'s second half: the tenant's company identifiers.

    In the workflows this is a SELECT over public.companies. Here it is the corpus's
    own declarative company list — same role, same shape, no DB dependency (this
    script depends on apitools only, deliberately)."""
    rows = json.load(io.open(COMPANIES_FIXTURE, encoding='utf-8'))
    out, seen = [], set()
    for r in rows if isinstance(rows, list) else []:
        for key in ('id', 'id1', 'מזהה 1', 'מזהה 2'):
            v = str(r.get(key) or '')
            if len(v) == 9 and v.isdigit() and v not in seen:
                seen.add(v)
                out.append(v)
    return sorted(out)


def _bind_registry(q, ids, where='q_v3'):
    """Port of the workflows' `Fan Fields` bindRegistry(). Must stay behaviourally
    identical to the JS in apps/indox/blueprint/n8n/JQExV3*.json — including throwing
    on an unresolved sentinel, so this checker can never grade a run in which the
    literal string '@registry_ids' was sent to apitools and matched nothing."""
    if isinstance(q, str) and q == '@registry_ids':
        if not ids:
            raise SystemExit(f'@registry_ids is empty (at {where}) — {COMPANIES_FIXTURE} '
                             f'yielded no 9-digit company identifiers')
        return ids
    if isinstance(q, list):
        return [_bind_registry(x, ids, f'{where}[{i}]') for i, x in enumerate(q)]
    if isinstance(q, dict):
        return {k: _bind_registry(v, ids, f'{where}.{k}') for k, v in q.items()}
    return q


def load_cfg() -> dict:
    """The workflows' `Load V3 Config`: jsonb_object_agg over settings q_v3_%."""
    rows = json.load(io.open(SETTINGS_FIXTURE, encoding='utf-8'))
    rows = rows if isinstance(rows, list) else rows.get('settings') or rows.get('rows')
    cfg = {}
    for r in rows:
        k = r.get('key') or ''
        if k.startswith('q_v3_'):
            v = r.get('value')
            cfg[k] = json.loads(v) if isinstance(v, str) else v
    if 'q_v3_routing' not in cfg:
        raise SystemExit('settings fixture has no q_v3_routing — wrong fixture?')
    ids = _registry_ids()
    return {k: _bind_registry(v, ids, k) for k, v in cfg.items()}


def query_field(client, fid: str, query: dict):
    """One value call — the `Query apitools` node + `Collect` semantics, verbatim."""
    try:
        resp = client.post(f"{ex.APITOOLS_BASE}/documentJsonQuery",
                           json={'file_id': fid, 'ocr_json_query': query},
                           timeout=300.0)  # the workflows' 300s budget
        rp = resp.json()
    except Exception as e:  # timeout / transport — the n8n continueRegularOutput shape
        return None, f'{type(e).__name__}: {e}'[:200]
    r = (rp.get('result') or {}).get('result') if rp.get('result') else None
    if isinstance(r, dict) and isinstance(r.get('matches'), list):
        m0 = r['matches'][0] if r['matches'] else {}
        return (m0.get('option') if isinstance(m0, dict) else None), None
    if r is None and rp.get('error'):
        return None, str(rp.get('message') or rp.get('error'))[:200]
    return r, None


def run_category(client, fid: str, category: str, cfg: dict):
    """`Fan Fields` for one doc+category: sequential per-field calls, like n8n."""
    routing = (cfg.get('q_v3_routing') or {}).get(category) or {}
    fields, errors, timings = {}, {}, {}
    for field, qkey in routing.items():
        query = cfg.get(qkey)
        if query is None:
            errors[field] = f'missing query {qkey}'
            continue
        t0 = time.perf_counter()
        val, err = query_field(client, fid, query)
        timings[field] = int((time.perf_counter() - t0) * 1000)
        fields[field] = val
        if err:
            errors[field] = err
    return fields, errors, timings


def extract_one(client, doc: dict, cfg: dict) -> dict:
    """The BFF's _extract_one with the two n8n hooks replaced by run_category."""
    t0 = time.time()
    path = ex._doc_path(doc['type'], doc['file'])
    if path is None:
        raise RuntimeError('file missing')
    ocr = ex._ocr_hash(path)
    fid = ocr.get('hash')
    if not fid:
        raise RuntimeError('apitools OCR returned no hash')
    base_f, base_e, base_t = run_category(client, fid, 'base', cfg)
    typ_cat = CATEGORY[doc['type']]
    type_f, type_e, type_t = run_category(client, fid, typ_cat, cfg)
    fields = {
        'COMPANY_ID': base_f.get('COMPANY_ID'),
        'BASE_DATE': base_f.get('DOC_DATE'),
        'DETECTED_TYPE': base_f.get('TYPE'),
    }
    fields.update(type_f)
    value_errors = {**base_e, **type_e}
    return {
        'hash': fid,
        'fields': fields,
        'value_errors': value_errors,
        'ops': {
            'ocr_engine': ocr.get('ocr_engine'), 'ocr_ms': ocr.get('ocr_ms'),
            'ocr_at': ocr.get('ocr_at'),
            'ocr_apitools_version': ocr.get('ocr_apitools_version'),
            'apitools_version': ocr.get('apitools_version'),
            'base_hook_s': round(sum(base_t.values()) / 1000, 1),
            'type_hook_s': round(sum(type_t.values()) / 1000, 1),
            'value_ms': {**base_t, **type_t},
        },
        'elapsed_s': round(time.time() - t0, 1),
    }


def main() -> int:
    import httpx
    cfg = load_cfg()
    docs = [d for d in ex._load_dataset() if d['type'] in CATEGORY]
    conc = int(os.getenv('CHECK_CONCURRENCY', '6'))
    exp_docs = int(os.getenv('EXPECTED_DOCS', '138'))
    exp_vals = int(os.getenv('EXPECTED_VALUES', '527'))
    budget = int(os.getenv('EXTRACTION_GATE_BUDGET_S', '4800'))
    print(f'corpus: {len(docs)} docs | apitools: {ex.APITOOLS_BASE} | conc={conc}')
    t0 = time.time()
    results = {}

    def _transient(e):
        # A slot-contention failure, NOT a wrong answer. When the whole stack shares the host CPU,
        # the gate's cold apitools starves and returns 429 (all OCR slots busy past the wait
        # timeout) or the client read times out. Those clear once a slot frees — retrying is
        # correct. A genuine extraction MISMATCH is never an exception (it returns a scored result
        # with ok<total), so no amount of retrying here can hide a wrong value.
        s = str(e)
        return (isinstance(e, (httpx.TimeoutException, httpx.ConnectError, httpx.PoolTimeout,
                               httpx.RemoteProtocolError))
                or "429" in s or "TOO MANY" in s or "timed out" in s or "503" in s
                or "Connection" in s)

    def process(doc):
        # Transient infra failures retry with exponential backoff until they clear or the run's
        # budget is spent — a 429 under load used to survive both of two 3s-apart attempts and end
        # the run with a hard error on ~3 heavy shipment docs. A NON-transient error still gets a
        # single retry (a real bug should not pass by luck).
        with httpx.Client() as client:
            delay, last, err = 3.0, None, None
            for attempt in range(1, 9):
                try:
                    r = ex._score_doc(doc, extract_one(client, doc, cfg))
                    r.setdefault('error', None)
                    return r
                except Exception as exc:
                    # [2026-08-23] BIND THE EXCEPTION TO A NAME THAT OUTLIVES THE HANDLER.
                    # `except ... as e` UNBINDS e when the clause ends (PEP 3110 deletes it), and
                    # the _transient(e) test below sits one line OUTSIDE the handler -- so the
                    # first exception of any run raised UnboundLocalError instead of deciding
                    # whether to retry. pool.map re-raises, so one transient 429 -- the exact
                    # thing this block exists to absorb -- killed the whole gate, which then
                    # reported "extraction gate FAILED --" with an empty reason. Measured on
                    # baseline3: P5c printed "gate did not report" and the run produced no score
                    # at all. The retry logic guarded here had therefore never once executed.
                    err = exc
                    last = {'id': doc['id'], 'ok': 0, 'total': 0, 'values': [],
                            'error': f'attempt {attempt}: {exc}'[:200]}
                exhausted = (time.time() - t0) > budget
                if exhausted or (not _transient(err) and attempt >= 2) or attempt >= 8:
                    return last
                time.sleep(min(delay, 60)); delay *= 2
            return last

    with ThreadPoolExecutor(max_workers=conc) as pool:
        for r in pool.map(process, docs):
            results[r['id']] = r
            done = len(results)
            ok = sum(x.get('ok') or 0 for x in results.values())
            tot = sum(x.get('total') or 0 for x in results.values())
            print(f'[{done}/{len(docs)}] accuracy={ok}/{tot} last={r["id"]} '
                  f'({r.get("elapsed_s")}s){" ERROR: " + str(r.get("error")) if r.get("error") else ""}',
                  flush=True)

    wall = int(time.time() - t0)
    ok = sum(r.get('ok') or 0 for r in results.values())
    tot = sum(r.get('total') or 0 for r in results.values())
    errs = [(k, r['error']) for k, r in results.items() if r.get('error')]
    fails = [(k, [(v.get('field'), v.get('got')) for v in r.get('values', [])
                  if isinstance(v, dict) and v.get('ok') is False])
             for k, r in results.items() if not r.get('error') and r.get('ok') != r.get('total')]
    # ACCURACY and COVERAGE have different denominators and must never be read for each
    # other. accuracy = correct / fields-that-have-ground-truth (a field the document does
    # not print is N/A, not a miss). coverage = fields-that-produced-a-value / fields-tried.
    # Shipment DOC_TOTAL_AMOUNT is the worked example: accuracy 1/1, coverage 1/15, because
    # 14 of those delivery notes print no amount anywhere. Quoting the coverage figure as if
    # it were accuracy is what made that field look catastrophic when it was perfect.
    cov = sum(r.get('got') or 0 for r in results.values())
    att = sum(r.get('attempted') or 0 for r in results.values())
    na = sum(r.get('na') or 0 for r in results.values())
    print(f'\nRESULT: docs={len(results)}/{exp_docs} '
          f'accuracy={ok}/{tot} (correct / with-ground-truth, expected {exp_vals}) '
          f'coverage={cov}/{att} (produced-a-value / attempted, {na} N-A) '
          f'wall={wall}s budget={budget}s')
    print('        accuracy is the gate; coverage is context — they have different denominators')
    for f in fails:
        print('  VALUE FAIL:', f)
    for e in errs:
        print('  DOC ERROR :', e)
    bad = []
    if len(results) != exp_docs:
        bad.append(f'docs {len(results)} != {exp_docs}')
    if tot != exp_vals:
        bad.append(f'scored values {tot} != {exp_vals}')
    if ok != tot:
        bad.append(f'ACCURACY {ok}/{tot}')
    if errs:
        bad.append(f'{len(errs)} doc error(s)')
    if wall > budget:
        bad.append(f'SPEED {wall}s > budget {budget}s')
    if bad:
        print('::error::extraction gate FAILED: ' + '; '.join(bad))
        return 1
    print('extraction gate PASSED: 100% accuracy inside the speed budget')
    return 0


if __name__ == '__main__':
    sys.exit(main())
