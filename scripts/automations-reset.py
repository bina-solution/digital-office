#!/usr/bin/env python3
"""
automations-reset — clean the incoming-documents AUTOMATION STATE for the current tenant.

Distinct from `bbox reset` (which is `docker compose down -v`, an INFRA wipe). This clears the
*application* state so the tenant is a clean slate for re-onboarding:

  reset-indox        : clear data rows in the data tab + log tabs; trash files in the 5 Drive folders
  reset-label-engine : remove automation Gmail labels from all messages; (optionally) trash injected
                       test messages; clear the label-engine + settings Redis caches
  redis              : delete process_lock.* and cache keys

Mechanism: drives the existing n8n Google creds via ephemeral helper workflows over the internal REST
(no token minting). Idempotent. Safe by default: --dry-run prints what it WOULD do.

Usage: automations-reset.py [--dry-run] [--force] [--no-gmail] [--no-drive] [--no-sheet] [--no-redis]
Env: reads .env for N8N_OWNER_*, INDOX_SHEET_ID, REDIS_PASSWORD, cred IDs.
"""
# Hebrew output: python defaults stdout to the ANSI codepage on Windows (cp1255) and dies
# with UnicodeEncodeError. Linux/macOS are already UTF-8 — a no-op there.
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"): _sys.stdout.reconfigure(encoding="utf-8")
import sys, os, json, time, subprocess, urllib.request, urllib.parse, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRY = '--dry-run' in sys.argv
FORCE = '--force' in sys.argv
SKIP = {k.replace('--no-', '') for k in sys.argv if k.startswith('--no-')}
BASE = 'http://localhost:5678'

# cred IDs (stable in this deployment)
CRED_SHEETS = 'e2knIZpw8YF0QBAB'
CRED_DRIVE = 'KirWFwoFdEFmnN0R'
CRED_GMAIL = '41BKgLp83YYyfEM3'
DATA_TAB = 'מסמכים נכנסים'
LOG_TABS = ['לוג שייום מסמכים בדרייב', 'לוג מיילים - שמירת מסמכים', 'לוג מיילים - דוחות גיול', 'לוג מיילים - פעולות']
# automation labels to strip from messages (the scanner/handler tags)
AUTO_LABELS = ['Label_10', 'Label_11', 'Label_13', 'Label_19']  # for-BS, for-docs, in-progress, handled


def env(key, default=''):
    for ln in open(os.path.join(ROOT, '.env'), encoding='utf-8', errors='replace'):
        if ln.startswith(key + '='):
            return ln.split('=', 1)[1].strip()
    return default


os.makedirs(os.path.join(ROOT, 'data', '_runs'), exist_ok=True)
CK = os.path.join(ROOT, 'data', '_runs', 'reset_cookies.txt')


def login():
    body = json.dumps({"emailOrLdapLoginId": env('N8N_OWNER_EMAIL'), "password": env('N8N_OWNER_PASSWORD')})
    r = subprocess.run(['curl', '-s', '-c', CK, '-X', 'POST', f'{BASE}/rest/login',
                        '-H', 'Content-Type: application/json', '-d', body], capture_output=True, text=True, encoding='utf-8', errors='replace')
    if '"id"' not in r.stdout and 'email' not in r.stdout:
        print('login response:', r.stdout[:160])


def rest(method, path, body=None):
    cmd = ['curl', '-s', '-b', CK, '-X', method, f'{BASE}{path}', '-H', 'Content-Type: application/json']
    if body is not None:
        cmd += ['--data-binary', json.dumps(body, ensure_ascii=False)]
    out = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace').stdout
    try:
        return json.loads(out)
    except Exception:
        return {'_raw': out}


def deref(arr, x, dep=0):
    if dep > 70:
        return '<deep>'
    if isinstance(x, str) and x.isdigit() and int(x) < len(arr):
        return deref(arr, arr[int(x)], dep + 1)
    if isinstance(x, dict):
        return {k: deref(arr, v, dep + 1) for k, v in x.items()}
    if isinstance(x, list):
        return [deref(arr, v, dep + 1) for v in x]
    return x


def run_wf(name, node, cred_type, cred_id, http_params, start='Run'):
    """Create an ephemeral workflow with one httpRequest node, run it, return the node's JSON output, delete it."""
    wf = {"name": name, "nodes": [
        {"parameters": {}, "id": "t1", "name": "Manual", "type": "n8n-nodes-base.manualTrigger", "typeVersion": 1, "position": [0, 0]},
        {"parameters": {**http_params, "authentication": "predefinedCredentialType", "nodeCredentialType": cred_type, "options": http_params.get('options', {})},
         "id": "t2", "name": "Run", "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2, "position": [240, 0],
         "credentials": {cred_type: {"id": cred_id, "name": "x"}}}],
        "connections": {"Manual": {"main": [[{"node": "Run", "type": "main", "index": 0}]]}}, "settings": {}}
    r = rest('POST', '/rest/workflows', wf)
    wid = r.get('data', {}).get('id')
    if not wid:
        return {'_err': 'create failed', '_r': r}
    try:
        rest('POST', f'/rest/workflows/{wid}/run', {"startNodes": [{"name": "Run"}], "triggerToStartFrom": {"name": "Manual", "data": {"main": [[{"json": {}}]]}}})
        time.sleep(4)
        # fetch latest execution
        ex = subprocess.run(['docker', 'exec', f'n8n-postgres-{env("DEPLOYMENT_NAME","shlomo-laptop")}', 'psql', '-U', 'hacohen', '-d', 'n8n', '-tAc',
                             f"select id from execution_entity where \"workflowId\"='{wid}' order by \"startedAt\" desc limit 1;"], capture_output=True, text=True, encoding='utf-8', errors='replace').stdout.strip()
        d = rest('GET', f'/rest/executions/{ex}?includeData=true').get('data', {})
        if not d.get('data'):
            return {'_status': d.get('status'), '_noout': True}
        arr = json.loads(d['data'])
        root = deref(arr, arr[0])
        rd = root.get('resultData', {})
        if rd.get('error'):
            return {'_error': str(rd['error'].get('message'))[:160]}
        try:
            return {'ok': True, 'out': rd['runData']['Run'][0]['data']['main'][0]}
        except Exception:
            return {'ok': True, 'out': None}
    finally:
        # archive + delete ephemeral wf
        rest('POST', f'/rest/workflows/{wid}/archive')
        rest('DELETE', f'/rest/workflows/{wid}')


SHEET = env('INDOX_SHEET_ID')


def gget(path):
    return run_wf('_rst get', None, 'googleSheetsOAuth2Api', CRED_SHEETS, {"url": f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET}{path}"})


def sheet_meta():
    r = gget("?fields=sheets.properties(sheetId,title)")
    if not r.get('ok'):
        return {}
    return {s['properties']['title']: s['properties']['sheetId'] for s in r['out'][0]['json'].get('sheets', [])}


def clear_tab(title, gid):
    # count rows
    enc = urllib.parse.quote(title)
    r = gget(f"/values/{enc}!A1:A100000")
    n = len(r['out'][0]['json'].get('values', [])) if r.get('ok') else 0
    if n <= 1:
        print(f"   [{title}] already empty ({n} rows)")
        return 0
    print(f"   [{title}] {n} rows -> clearing rows 2..{n}" + (" (DRY)" if DRY else ""))
    if DRY:
        return n - 1
    body = {"requests": [{"deleteDimension": {"range": {"sheetId": gid, "dimension": "ROWS", "startIndex": 1, "endIndex": n}}}]}
    rr = run_wf('_rst clr', None, 'googleSheetsOAuth2Api', CRED_SHEETS,
                {"method": "POST", "url": f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET}:batchUpdate",
                 "sendBody": True, "specifyBody": "json", "jsonBody": json.dumps(body)})
    print(f"      -> {'cleared' if rr.get('ok') else rr}")
    return n - 1


def trash_files_batched(fid):
    """One ephemeral workflow: List files in folder -> SplitOut -> PATCH trashed=true (auto-loops per item)."""
    q = urllib.parse.quote(f"'{fid}' in parents and trashed=false")
    wf = {"name": "_rst dtrash", "nodes": [
        {"parameters": {}, "id": "t1", "name": "Manual", "type": "n8n-nodes-base.manualTrigger", "typeVersion": 1, "position": [0, 0]},
        {"parameters": {"url": f"https://www.googleapis.com/drive/v3/files?q={q}&fields=files(id)&pageSize=1000&supportsAllDrives=true&includeItemsFromAllDrives=true",
                        "authentication": "predefinedCredentialType", "nodeCredentialType": "googleDriveOAuth2Api", "options": {}},
         "id": "t2", "name": "List", "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2, "position": [220, 0],
         "credentials": {"googleDriveOAuth2Api": {"id": CRED_DRIVE, "name": "x"}}},
        {"parameters": {"fieldToSplitOut": "files", "options": {}},
         "id": "t3", "name": "Split", "type": "n8n-nodes-base.splitOut", "typeVersion": 1, "position": [440, 0]},
        {"parameters": {"method": "PATCH", "url": "=https://www.googleapis.com/drive/v3/files/{{ $json.id }}?supportsAllDrives=true",
                        "authentication": "predefinedCredentialType", "nodeCredentialType": "googleDriveOAuth2Api",
                        "sendBody": True, "specifyBody": "json", "jsonBody": '={{ {"trashed": true} }}',
                        "options": {"batching": {"batch": {"batchSize": 10, "batchInterval": 200}}}},
         "id": "t4", "name": "Trash", "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2, "position": [660, 0],
         "credentials": {"googleDriveOAuth2Api": {"id": CRED_DRIVE, "name": "x"}}}],
        "connections": {"Manual": {"main": [[{"node": "List", "type": "main", "index": 0}]]},
                        "List": {"main": [[{"node": "Split", "type": "main", "index": 0}]]},
                        "Split": {"main": [[{"node": "Trash", "type": "main", "index": 0}]]}}, "settings": {}}
    r = rest('POST', '/rest/workflows', wf)
    wid = r.get('data', {}).get('id')
    if not wid:
        return {'_err': 'create failed'}
    try:
        rest('POST', f'/rest/workflows/{wid}/run', {"startNodes": [{"name": "List"}], "triggerToStartFrom": {"name": "Manual", "data": {"main": [[{"json": {}}]]}}})
        # poll until not running (up to ~90s)
        dn = env('DEPLOYMENT_NAME', 'shlomo-laptop')
        for _ in range(30):
            time.sleep(3)
            ex = subprocess.run(['docker', 'exec', f'n8n-postgres-{dn}', 'psql', '-U', 'hacohen', '-d', 'n8n', '-tAc',
                                 f"select status from execution_entity where \"workflowId\"='{wid}' order by \"startedAt\" desc limit 1;"],
                                capture_output=True, text=True, encoding='utf-8', errors='replace').stdout.strip()
            if ex and ex != 'running':
                return f"exec {ex}"
        return "timeout"
    finally:
        rest('POST', f'/rest/workflows/{wid}/archive')
        rest('DELETE', f'/rest/workflows/{wid}')


def seed_bootstrap():
    """After clearing, leave ONE sentinel row so Batch Upsert can derive headers (it errors on an empty
    data tab). Without this, the first doc on a fresh/reset tenant fails with 'Sheet data is empty'."""
    try:
        schema = json.loads(open(os.path.join(ROOT, 'data', '_runs', 'setup_SCHEMA.js'), encoding='utf-8').read().split('const S=', 1)[1].rsplit('return', 1)[0].strip().rstrip(';'))
        hdr = schema['dataHeaders']
    except Exception:
        return print("   [bootstrap] SCHEMA not available; skipping (run setup to seed)")
    row = [''] * len(hdr)
    for col, val in [('ID', '__bootstrap__'), ('STATUS', 'COMPLETED'), ('TYPE', 'UNKNOWN'),
                     ('NAME', 'bootstrap'), ('COMPANY_ID', '000000000'), ('COMPANY_NAME', 'bootstrap'),
                     ('COMPANY_NAME_COMPLETED', 'TRUE'), ('FIGURE_COMPANY_COMPLETED', 'TRUE')]:
        if col in hdr:
            row[hdr.index(col)] = val
    if DRY:
        return print("   [bootstrap] would seed sentinel row (DRY)")
    enc = urllib.parse.quote(DATA_TAB)
    r = run_wf('_rst seed', None, 'googleSheetsOAuth2Api', CRED_SHEETS,
               {"method": "POST", "url": f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET}/values/{enc}!A1:append?valueInputOption=RAW&insertDataOption=INSERT_ROWS",
                "sendBody": True, "specifyBody": "json", "jsonBody": json.dumps({"values": [row]}, ensure_ascii=False)})
    print(f"   [bootstrap] sentinel row seeded -> {'ok' if r.get('ok') else r}")


def reset_indox():
    print("== reset-indox ==")
    meta = sheet_meta()
    if 'sheet' not in SKIP:
        print(" clearing data + log tabs:")
        for t in [DATA_TAB] + LOG_TABS:
            if t in meta:
                clear_tab(t, meta[t])
            else:
                print(f"   [{t}] tab not found (skip)")
        seed_bootstrap()
    if 'drive' not in SKIP:
        print(" trashing files in the 5 Drive folders:")
        folders = json.load(open(os.path.join(ROOT, 'next-7h', 'pre-reset-snapshot.json')))['folders']
        for role, fid in folders.items():
            r = run_wf('_rst dls', None, 'googleDriveOAuth2Api', CRED_DRIVE,
                       {"url": f"https://www.googleapis.com/drive/v3/files?q=" + urllib.parse.quote(f"'{fid}' in parents and trashed=false") + "&fields=files(id,name)&pageSize=1000&supportsAllDrives=true&includeItemsFromAllDrives=true"})
            files = r['out'][0]['json'].get('files', []) if r.get('ok') else []
            print(f"   [{role}] {len(files)} files" + (" (DRY)" if DRY else " -> trashing in one batched workflow"))
            if DRY or not files:
                continue
            res = trash_files_batched(fid)
            print(f"      -> {res}")


def reset_label_engine():
    print("== reset-label-engine ==")
    if 'gmail' not in SKIP:
        for lab in AUTO_LABELS:
            r = run_wf('_rst gls', None, 'gmailOAuth2', CRED_GMAIL,
                       {"url": f"https://gmail.googleapis.com/gmail/v1/users/me/messages?labelIds={lab}&maxResults=500"})
            msgs = r['out'][0]['json'].get('messages', []) if r.get('ok') else []
            print(f"   [{lab}] {len(msgs)} messages" + (" (DRY)" if DRY else " -> removing label"))
            if DRY:
                continue
            # batchModify remove label (and TRASH the message too unless --keep-messages: these are the
            # in-flight/test docs; a clean slate means the inbox is clean for re-onboarding)
            ids = [m['id'] for m in msgs]
            remove = [lab]
            add = [] if 'keep-messages' in SKIP or '--keep-messages' in sys.argv else ['TRASH']
            for i in range(0, len(ids), 100):
                body = {"ids": ids[i:i+100], "removeLabelIds": remove}
                if add:
                    body["addLabelIds"] = add
                run_wf('_rst gmod', None, 'gmailOAuth2', CRED_GMAIL,
                       {"method": "POST", "url": "https://gmail.googleapis.com/gmail/v1/users/me/messages/batchModify",
                        "sendBody": True, "specifyBody": "json", "jsonBody": json.dumps(body)})
    if 'redis' not in SKIP:
        rp = env('REDIS_PASSWORD')
        dn = env('DEPLOYMENT_NAME', 'shlomo-laptop')
        patterns = ['n8n.process_lock.*', 'n8n.label-engine.*', 'n8n:cache:*settings*', 'n8n:cache:*compan*']
        print(" clearing Redis keys:", patterns, "(DRY)" if DRY else "")
        if not DRY:
            for pat in patterns:
                subprocess.run(['docker', 'exec', f'redis-{dn}', 'sh', '-lc',
                                f"redis-cli -a '{rp}' --no-auth-warning --scan --pattern '{pat}' | xargs -r redis-cli -a '{rp}' --no-auth-warning del"],
                               capture_output=True, text=True, encoding='utf-8', errors='replace')


def reset_supabase():
    """Supabase is the ONLY indox data backend (sheets is fully legacy — the
    INDOX_DATA_BACKEND toggle and the settings row backend_data are gone).
    Clear the incoming_documents TABLE (the equivalent of clearing the old
    sheet data tab). Fixed schema -> no bootstrap row needed."""
    if 'supabase' in SKIP:
        return
    dn = env('DEPLOYMENT_NAME', 'shlomo-laptop')
    print("== reset-supabase ==")
    cnt = subprocess.run(['docker', 'exec', f'supabase-db-{dn}', 'psql', '-U', 'postgres', '-d', 'postgres', '-tAc',
                          'select count(*) from incoming_documents;'], capture_output=True, text=True,
                         encoding='utf-8', errors='replace').stdout.strip()
    print(f"   incoming_documents: {cnt} rows" + (" (DRY)" if DRY else " -> deleting all (clean slate)"))
    if DRY:
        return
    r = subprocess.run(['docker', 'exec', f'supabase-db-{dn}', 'psql', '-U', 'postgres', '-d', 'postgres', '-c',
                        'delete from incoming_documents;'], capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    print(f"   -> {(r.stdout or r.stderr).strip()[:80]}")


def main():
    print(f"automations-reset  (DRY-RUN)" if DRY else "automations-reset  (LIVE — will modify tenant state)")
    if not DRY and not FORCE:
        print("Refusing to run live without --force (or --dry-run). Aborting.")
        sys.exit(2)
    login()
    reset_indox()
    reset_supabase()
    reset_label_engine()
    print("== done ==")


if __name__ == '__main__':
    main()
