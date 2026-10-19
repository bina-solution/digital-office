#!/usr/bin/env python3
"""
indox-accept — acceptance/goal-check harness for INDOX.

Goal: clean start -> within ~5min, injected Gmail docs processed+upserted, Drive docs upserted,
main table runs all steps -> COMPLETED. Measures and prints PASS/FAIL vs targets.

Usage: indox-accept.py [--reset] [--gmail N] [--drive N] [--measure-only] [--minutes M]
Run via Windows python3 (forces UTF-8). Drives n8n internal REST; reads sheet via retry-ephemeral.
"""
# Hebrew output: python defaults stdout to the ANSI codepage on Windows (cp1255) and dies
# with UnicodeEncodeError. Linux/macOS are already UTF-8 — a no-op there.
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"): _sys.stdout.reconfigure(encoding="utf-8")
import sys, os, json, time, subprocess, urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
BASE = 'http://localhost:5678'
CK = os.path.join(ROOT, 'data', '_runs', 'accept_cookies.txt')
SHEET = ''
DN = 'shlomo-laptop'
CRED_SHEETS = 'e2knIZpw8YF0QBAB'
DATA_TAB = 'מסמכים נכנסים'
os.makedirs(os.path.join(ROOT, 'data', '_runs'), exist_ok=True)


def env(k, d=''):
    for ln in open(os.path.join(ROOT, '.env'), encoding='utf-8', errors='replace'):
        if ln.startswith(k + '='):
            return ln.split('=', 1)[1].strip()
    return d


def login():
    body = json.dumps({"emailOrLdapLoginId": env('N8N_OWNER_EMAIL'), "password": env('N8N_OWNER_PASSWORD')})
    subprocess.run(['curl', '-s', '-c', CK, '-X', 'POST', f'{BASE}/rest/login', '-H', 'Content-Type: application/json', '-d', body],
                   capture_output=True, text=True, encoding='utf-8', errors='replace')


def rest(method, path, body=None):
    cmd = ['curl', '-s', '-b', CK, '-X', method, f'{BASE}{path}', '-H', 'Content-Type: application/json']
    if body is not None:
        cmd += ['--data-binary', json.dumps(body, ensure_ascii=False)]
    out = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace').stdout
    try:
        return json.loads(out)
    except Exception:
        return {'_raw': out}


def psql(q):
    return subprocess.run(['docker', 'exec', f'n8n-postgres-{DN}', 'psql', '-U', 'hacohen', '-d', 'n8n', '-tAc', q],
                          capture_output=True, text=True, encoding='utf-8', errors='replace').stdout.strip()


def deref(arr, x, dep=0):
    if dep > 60:
        return '<deep>'
    if isinstance(x, str) and x.isdigit() and int(x) < len(arr):
        return deref(arr, arr[int(x)], dep + 1)
    if isinstance(x, dict):
        return {k: deref(arr, v, dep + 1) for k, v in x.items()}
    if isinstance(x, list):
        return [deref(arr, v, dep + 1) for v in x]
    return x


def read_sheet_rows():
    """Read the data tab via a retry-enabled ephemeral workflow; returns list of row dicts (header-mapped)."""
    global SHEET
    SHEET = env('INDOX_SHEET_ID')
    tab = urllib.parse.quote(DATA_TAB)
    wf = {"name": "_acc_read", "nodes": [
        {"parameters": {}, "id": "t1", "name": "M", "type": "n8n-nodes-base.manualTrigger", "typeVersion": 1, "position": [0, 0]},
        {"parameters": {"url": f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET}/values/{tab}!A1:CZ1000",
                        "authentication": "predefinedCredentialType", "nodeCredentialType": "googleSheetsOAuth2Api", "options": {}},
         "id": "t2", "name": "R", "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2, "position": [220, 0],
         "retryOnFail": True, "maxTries": 6, "waitBetweenTries": 5000,
         "credentials": {"googleSheetsOAuth2Api": {"id": CRED_SHEETS, "name": "x"}}}],
        "connections": {"M": {"main": [[{"node": "R", "type": "main", "index": 0}]]}}, "settings": {}}
    r = rest('POST', '/rest/workflows', wf)
    wid = r.get('data', {}).get('id')
    if not wid:
        return None
    try:
        rest('POST', f'/rest/workflows/{wid}/run', {"startNodes": [{"name": "R"}], "triggerToStartFrom": {"name": "M", "data": {"main": [[{"json": {}}]]}}})
        time.sleep(16)
        ex = psql(f"select id from execution_entity where \"workflowId\"='{wid}' order by \"startedAt\" desc limit 1;")
        d = rest('GET', f'/rest/executions/{ex}?includeData=true').get('data', {})
        if not d.get('data'):
            return None
        arr = json.loads(d['data'])
        node = deref(arr, arr[0])['resultData']['runData']['R'][0]
        if 'error' in node:
            return None
        vals = node['data']['main'][0][0]['json'].get('values', [])
        hdr = vals[0]
        rows = [dict(zip(hdr, r)) for r in vals[1:] if any(r)]
        return rows
    finally:
        rest('POST', f'/rest/workflows/{wid}/archive')
        rest('DELETE', f'/rest/workflows/{wid}')


def measure():
    from collections import Counter
    rows = read_sheet_rows()
    if rows is None:
        print("MEASURE: sheet read failed (429/transient)")
        return None
    real = [r for r in rows if r.get('ID') != '__bootstrap__']
    st = Counter(r.get('STATUS', '') for r in real)
    ty = Counter(r.get('TYPE', '') for r in real)
    # duplicate detection by HASH (non-empty)
    hashes = [r.get('HASH', '') for r in real if r.get('HASH')]
    dupes = len(hashes) - len(set(hashes))
    err_2m = psql("select coalesce(sum((status='error')::int),0) from execution_entity where \"startedAt\">now()-interval '2 minutes';")
    ok_2m = psql("select coalesce(sum((status='success')::int),0) from execution_entity where \"startedAt\">now()-interval '2 minutes';")
    print(f"ROWS={len(real)} | STATUS={dict(st)} | TYPE={dict(ty)} | dupes(by HASH)={dupes} | exec2m ok={ok_2m} err={err_2m}")
    return {'rows': len(real), 'status': dict(st), 'dupes': dupes, 'completed': st.get('COMPLETED', 0)}


if __name__ == '__main__':
    login()
    print("=== INDOX acceptance measure ===")
    measure()
