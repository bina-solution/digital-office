#!/usr/bin/env python3
"""Audit every Google API call site across all n8n workflows. Output a high-level overview focused on
Sheets (the tight quota): read vs write, per-doc vs batch, cached or not. Identifies call hotspots."""
import json, glob, os, re
from collections import defaultdict

SHEET_READ = {'read', '', 'getMany', 'lookup', None, 'get'}
SHEET_WRITE = {'append', 'update', 'appendOrUpdate', 'delete', 'clear', 'upsert'}

def load(f):
    try: return json.load(open(f, encoding='utf-8', errors='replace'))
    except Exception: return None

active = {}
for ln in open('data/_runs/active_map.txt', encoding='utf-8', errors='replace') if os.path.exists('data/_runs/active_map.txt') else []:
    if '|' in ln:
        i, a = ln.strip().split('|'); active[i] = (a == 't')

agg = defaultdict(int)
hotspots = []
rows = []
for f in sorted(glob.glob('apps/n8n/blueprint/n8n/*.json')):
    d = load(f)
    if not d: continue
    wid = os.path.basename(f).replace('.json', '')
    act = active.get(wid, True)
    if not act: continue
    name = d.get('name', '?')
    # build node->is-in-loop map (downstream of a splitInBatches bs=1 == per-doc)
    for n in d['nodes']:
        t = n['type']
        tl = t.split('.')[-1]
        p = n.get('parameters', {}) or {}
        api = None; op = ''; kind = ''
        if 'googleSheets' in t and 'Trigger' not in t:
            api = 'Sheets'; op = p.get('operation', 'read') or 'read'
            kind = 'READ' if op in SHEET_READ else ('WRITE' if op in SHEET_WRITE else op)
        elif t.endswith('googleSheetsTrigger'):
            api = 'Sheets'; op = 'trigger(poll)'; kind = 'READ'
        elif 'googleDrive' in t and 'Trigger' not in t:
            api = 'Drive'; op = p.get('operation', '?'); kind = 'DRIVE'
        elif t.endswith('googleDriveTrigger'):
            api = 'Drive'; op = 'trigger(poll)'; kind = 'DRIVE'
        elif tl == 'gmail':
            api = 'Gmail'; op = p.get('operation', '?'); kind = 'GMAIL'
        elif tl in ('googleGemini', 'googlePalmApi') or 'lmChatGoogleGemini' in t:
            api = 'Gemini'; op = 'generate'; kind = 'GEMINI'
        elif tl == 'httpRequest':
            url = str(p.get('url', ''))
            if 'sheets.googleapis' in url:
                api = 'Sheets'; kind = 'BATCH-WRITE' if 'batchUpdate' in url else 'READ'; op = 'http:' + ('batchUpdate' if 'batchUpdate' in url else 'values')
            elif 'gmail.googleapis' in url: api = 'Gmail'; op = 'http'; kind = 'GMAIL'
            elif 'googleapis.com/drive' in url or 'www.googleapis.com/drive' in url: api = 'Drive'; op = 'http'; kind = 'DRIVE'
        if not api: continue
        retry = n.get('retryOnFail', False)
        agg[f'{api}:{kind}'] += 1
        if api == 'Sheets' and kind in ('READ', 'WRITE'):
            hotspots.append((name, n['name'], kind, op, retry))
        rows.append((name, n['name'], api, op, kind, retry))

# write report
out = ['# Google API usage audit (active workflows) — 2026-06-21\n',
       '## Aggregate call sites by API:kind']
for k in sorted(agg, key=lambda x: -agg[x]):
    out.append(f'- {k}: {agg[k]}')
out.append('\n## Sheets READ/WRITE call sites (the tight quota — each is a quota hit per execution):')
out.append('| Workflow | Node | R/W | op | retry |')
out.append('|---|---|---|---|---|')
for nm, node, kind, op, retry in sorted(hotspots):
    out.append(f'| {nm} | {node} | {kind} | {op} | {"✓" if retry else "—"} |')
open('next-7h/GOOGLE-API-AUDIT.md', 'w', encoding='utf-8').write('\n'.join(out))
print('AGGREGATE:', dict(agg))
print('Sheets R/W call sites:', len(hotspots))
print('-> next-7h/GOOGLE-API-AUDIT.md')
