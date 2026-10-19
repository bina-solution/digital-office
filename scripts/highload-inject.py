#!/usr/bin/env python3
"""
highload-inject — per-type, per-source high-load injector for INDOX verification.
Extends fresh-company-test-state-inject with EXPLICIT per-type counts (not n//4) and MIXED-type
Drive uploads (the stock script only did BS to Drive). Sources covered here: gmail (IMAP append) +
drive (folder upload). table-link source is handled separately (scripts/highload-inject-links.py)
because it needs live Drive file IDs + a supabase INSERT.

BS counts are intentionally kept LOW by the caller: each BS doc explodes into ~140 line-invoices and
the line-change poll is the known throughput bottleneck — 50 BS/source would generate ~14k lines and
never drain "fast". Non-BS types (invoice/shipment/unknown) carry the high-volume stress test.

Usage:
  highload-inject.py --gmail-inv 50 --gmail-ship 50 --gmail-unk 50 --gmail-bs 3 \
                     --drive-inv 50 --drive-ship 50 --drive-unk 50 --drive-bs 3
Run via Windows python3 (UTF-8).
"""
import sys, os, json, time, subprocess, shutil, csv, re, random

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = 'http://localhost:5678'
CK = os.path.join(ROOT, 'data', '_runs', 'hli_cookies.txt')
DN = 'shlomo-laptop'
CRED_DRIVE = 'KirWFwoFdEFmnN0R'
# IMPORTANT: To-Process == BalanceSheetSourceFolder1 (same Drive folder id) -> anything dropped there is
# typed BALANCE_SHEET by the BS Sync runner. General docs (invoice/shipment/unknown) MUST go to a
# GeneralDocs source folder instead, or they get mis-typed as BS.
BS_FOLDER = '1M9h_cpKmz5O7dNC2KzbUeEyvczLsWylM'        # BalanceSheetSourceFolder1 (== DocumentsToProcessFolder)
GENERAL_FOLDER = '1tK4m0VyC2spEV8ByPYrPt6DKdI53tXp1'   # GeneralDocsSourceFolder1
TO_PROCESS = BS_FOLDER  # back-compat
LABEL_DOC = 'Label_11'   # save-documents
LABEL_BS = 'Label_10'    # save-aging-reports (BS)
TYPE_LABEL = {'invoice': LABEL_DOC, 'shipment': LABEL_DOC, 'unknown': LABEL_DOC, 'balance_sheet': LABEL_BS}
random.seed()


def arg(name, d):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else d


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


def run_eph(wf, start, timeout=300):
    r = rest('POST', '/rest/workflows', wf)
    wid = r.get('data', {}).get('id')
    if not wid:
        return {'_err': 'create failed', 'r': str(r)[:200]}
    try:
        rest('POST', f'/rest/workflows/{wid}/run', {"startNodes": [{"name": start}], "triggerToStartFrom": {"name": "M", "data": {"main": [[{"json": {}}]]}}})
        for _ in range(timeout // 5):
            time.sleep(5)
            st = psql(f"select status from execution_entity where \"workflowId\"='{wid}' order by \"startedAt\" desc limit 1;")
            if st and st != 'running':
                return {'status': st}
        return {'status': 'timeout'}
    finally:
        rest('POST', f'/rest/workflows/{wid}/archive')
        rest('DELETE', f'/rest/workflows/{wid}')


def stage_to_n8n(src_dir, sub):
    host = os.path.join(ROOT, 'production', 'n8n', 'workflows', '_hli_' + sub)
    shutil.rmtree(host, ignore_errors=True)
    os.makedirs(host)
    for f in os.listdir(src_dir):
        shutil.copy(os.path.join(src_dir, f), os.path.join(host, f))
    subprocess.run(['docker', 'exec', f'n8n-{DN}', 'sh', '-lc',
                    f'rm -rf /home/node/.n8n-files/hli_{sub} && mkdir -p /home/node/.n8n-files/hli_{sub} && cp /home/node/workflows/_hli_{sub}/* /home/node/.n8n-files/hli_{sub}/ 2>/dev/null; ls /home/node/.n8n-files/hli_{sub} | wc -l'],
                   capture_output=True, text=True)
    return f'/home/node/.n8n-files/hli_{sub}'


def inject_gmail(counts):
    """counts: dict type->count. Builds MIME per type, IMAP-appends with the right download label."""
    out = os.path.join(ROOT, 'data', '_runs', 'hli_gmail')
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    bm = os.path.join(ROOT, 'data', '_runs', 'build_mime.py')
    for dtype, cnt in counts.items():
        if cnt <= 0:
            continue
        subprocess.run(['python3', bm, dtype, str(cnt), TYPE_LABEL[dtype], out], capture_output=True, text=True, encoding='utf-8', errors='replace')
    nfiles = len([f for f in os.listdir(out) if f.endswith('.txt')])
    if nfiles == 0:
        return 0
    path = stage_to_n8n(out, 'gmail')
    code = (
        "const out=[]; const items=$input.all();\n"
        "for(let i=0;i<items.length;i++){const fn=items[i].binary.data.fileName||'';"
        "const m=fn.match(/__(Label_\\d+)\\.txt$/); const label=m?m[1]:'Label_11';"
        "const buf=await this.helpers.getBinaryDataBuffer(i,'data');"
        "const mime=Buffer.from(buf.toString('utf8').trim(),'base64');"
        "out.push({json:{raw_base64:mime.toString('base64'),labels:[label],folder:'INBOX'}});}\nreturn out;")
    wf = {"name": "highload-inject:gmail", "nodes": [
        {"parameters": {}, "id": "t1", "name": "M", "type": "n8n-nodes-base.manualTrigger", "typeVersion": 1, "position": [0, 0]},
        {"parameters": {"fileSelector": f"{path}/*.txt", "options": {}}, "id": "t2", "name": "Read", "type": "n8n-nodes-base.readWriteFile", "typeVersion": 1, "position": [220, 0]},
        {"parameters": {"jsCode": code}, "id": "t3", "name": "Build", "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [440, 0]},
        {"parameters": {"method": "POST", "url": "http://mailapi:8970/append", "sendBody": True, "specifyBody": "json", "jsonBody": "={{ { raw_base64: $json.raw_base64, labels: $json.labels, folder: $json.folder } }}", "options": {"batching": {"batch": {"batchSize": 1, "batchInterval": 200}}, "timeout": 60000}},
         "id": "t4", "name": "Insert", "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2, "position": [660, 0], "retryOnFail": True, "maxTries": 4, "waitBetweenTries": 2000}],
        "connections": {"M": {"main": [[{"node": "Read", "type": "main", "index": 0}]]}, "Read": {"main": [[{"node": "Build", "type": "main", "index": 0}]]}, "Build": {"main": [[{"node": "Insert", "type": "main", "index": 0}]]}}, "settings": {}}
    print(f"  gmail: built {nfiles} MIME ({counts}), IMAP-appending...")
    print("  ->", run_eph(wf, "Read", timeout=420))
    return nfiles


def _stage_drive_type(dtype, n, out, used):
    base = os.path.join(ROOT, 'data', 'data-set-2', dtype)
    csvp = os.path.join(base, 'dataset.csv')
    if not os.path.exists(csvp):
        return 0
    rows = [r for r in csv.DictReader(open(csvp, encoding='utf-8')) if r.get('LOCAL_PATH') and os.path.exists(os.path.join(base, r['LOCAL_PATH']))]
    random.shuffle(rows)
    made = 0
    for r in rows:
        if made >= n:
            break
        cn = (r.get('COMPANY_NAME') or 'Supplier').strip() or 'Supplier'
        d = (r.get('BS_LINE_DATE') or r.get('DOC_DATE') or '').strip()
        mm, yy = '09', '25'
        m = re.search(r'(\d{4})-(\d{2})-(\d{2})', d) or re.search(r'(\d{2})/(\d{2})/(\d{4})', d)
        if m:
            g = m.groups()
            (yy, mm) = (g[0][2:], g[1]) if len(g[0]) == 4 else (g[2][2:], g[1])
        fp = os.path.join(base, r['LOCAL_PATH'])
        ext = fp.rsplit('.', 1)[-1]
        safe = re.sub(r'[\\/:*?"<>|]', '', cn).strip()[:40] or 'Supplier'
        name = f"{safe} {mm}.{yy}.{ext}"
        if name in used:
            name = f"{safe} {mm}.{yy}-{dtype[:3]}{made}.{ext}"
        used.add(name)
        shutil.copy(fp, os.path.join(out, name))
        made += 1
    return made


def _upload_dir(out, sub, folder_id, label):
    n = len([f for f in os.listdir(out) if os.path.isfile(os.path.join(out, f))])
    if n == 0:
        return 0
    path = stage_to_n8n(out, sub)
    wf = {"name": f"highload-inject:drive-{sub}", "nodes": [
        {"parameters": {}, "id": "t1", "name": "M", "type": "n8n-nodes-base.manualTrigger", "typeVersion": 1, "position": [0, 0]},
        {"parameters": {"fileSelector": f"{path}/*", "options": {}}, "id": "t2", "name": "Read", "type": "n8n-nodes-base.readWriteFile", "typeVersion": 1, "position": [220, 0]},
        {"parameters": {"resource": "file", "operation": "upload", "name": "={{ $binary.data.fileName }}", "driveId": {"__rl": True, "mode": "list", "value": "My Drive"}, "folderId": {"__rl": True, "mode": "id", "value": folder_id}, "options": {}},
         "id": "t3", "name": "Up", "type": "n8n-nodes-base.googleDrive", "typeVersion": 3, "position": [440, 0], "retryOnFail": True, "maxTries": 4, "waitBetweenTries": 3000, "credentials": {"googleDriveOAuth2Api": {"id": CRED_DRIVE, "name": "x"}}}],
        "connections": {"M": {"main": [[{"node": "Read", "type": "main", "index": 0}]]}, "Read": {"main": [[{"node": "Up", "type": "main", "index": 0}]]}}, "settings": {}}
    print(f"  drive: uploading {n} {label} files -> {folder_id}...")
    print("  ->", run_eph(wf, "Read", timeout=900))
    return n


def inject_drive(counts):
    """General docs (invoice/shipment/unknown) -> GeneralDocsSourceFolder1; BS -> BalanceSheetSourceFolder1.
    The folder determines the sync runner + initial TYPE, so they MUST be separated."""
    used = set()
    # general docs
    gen_out = os.path.join(ROOT, 'data', '_runs', 'hli_drive_gen')
    shutil.rmtree(gen_out, ignore_errors=True)
    os.makedirs(gen_out)
    for dtype in ('invoice', 'shipment', 'unknown'):
        cnt = counts.get(dtype, 0)
        if cnt > 0:
            m = _stage_drive_type(dtype, cnt, gen_out, used)
            print(f"  drive stage(general) {dtype}: {m}")
    # BS docs
    bs_out = os.path.join(ROOT, 'data', '_runs', 'hli_drive_bs')
    shutil.rmtree(bs_out, ignore_errors=True)
    os.makedirs(bs_out)
    if counts.get('balance_sheet', 0) > 0:
        m = _stage_drive_type('balance_sheet', counts['balance_sheet'], bs_out, used)
        print(f"  drive stage(bs) balance_sheet: {m}")
    g = _upload_dir(gen_out, 'drive_gen', GENERAL_FOLDER, 'general->GeneralDocsSource1')
    b = _upload_dir(bs_out, 'drive_bs', BS_FOLDER, 'bs->BalanceSheetSource1')
    return g + b


if __name__ == '__main__':
    login()
    gmail = {'invoice': int(arg('--gmail-inv', '0')), 'shipment': int(arg('--gmail-ship', '0')),
             'unknown': int(arg('--gmail-unk', '0')), 'balance_sheet': int(arg('--gmail-bs', '0'))}
    drive = {'invoice': int(arg('--drive-inv', '0')), 'shipment': int(arg('--drive-ship', '0')),
             'unknown': int(arg('--drive-unk', '0')), 'balance_sheet': int(arg('--drive-bs', '0'))}
    print(f"=== highload-inject: gmail={gmail} drive={drive} ===")
    g = inject_gmail(gmail) if any(gmail.values()) else 0
    d = inject_drive(drive) if any(drive.values()) else 0
    print(f"DONE: gmail={g} drive={d}")
