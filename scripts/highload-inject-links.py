#!/usr/bin/env python3
"""
highload-inject-links — the THIRD INDOX source: a row added to the table with just a LINK (no attachment
in gmail, not dropped in the watched Drive folder). Simulates an operator pasting a doc link into the table.

How: upload N staged files to a DEDICATED Drive folder (NOT the watched To-Process folder, so the folder
scanner ignores them), capture each file id via a Code node that writes ids->json in the n8n container,
then directly INSERT incoming_documents rows with SOURCE_TYPE=GOOGLE_DRIVE_FILE + LINK=drive file url.
The supabase table-change trigger fires the main workflow on each INSERT -> main downloads from LINK and
processes exactly like a scanned doc. Uses the same GOOGLE_DRIVE_FILE shape the drive scanner emits.

Usage: highload-inject-links.py --inv 10 --ship 10 --unk 10 --bs 1
Run via Windows python3 (UTF-8).
"""
import sys, os, json, time, subprocess, shutil, csv, re, random, hashlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = 'http://localhost:5678'
CK = os.path.join(ROOT, 'data', '_runs', 'hll_cookies.txt')
DN = 'shlomo-laptop'
CRED_DRIVE = 'KirWFwoFdEFmnN0R'
IDS_FILE = '/home/node/.n8n-files/hll_link_ids.json'
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


def psql_n8n(q):
    return subprocess.run(['docker', 'exec', f'n8n-postgres-{DN}', 'psql', '-U', 'hacohen', '-d', 'n8n', '-tAc', q],
                          capture_output=True, text=True, encoding='utf-8', errors='replace').stdout.strip()


def sb(q):
    return subprocess.run(['docker', 'exec', f'supabase-db-{DN}', 'psql', '-U', 'postgres', '-d', 'postgres', '-tAc', q],
                          capture_output=True, text=True, encoding='utf-8', errors='replace')


def run_eph(wf, start, timeout=400):
    r = rest('POST', '/rest/workflows', wf)
    wid = r.get('data', {}).get('id')
    if not wid:
        return None, {'_err': 'create failed', 'r': str(r)[:200]}
    try:
        rest('POST', f'/rest/workflows/{wid}/run', {"startNodes": [{"name": start}], "triggerToStartFrom": {"name": "M", "data": {"main": [[{"json": {}}]]}}})
        for _ in range(timeout // 5):
            time.sleep(5)
            st = psql_n8n(f"select status from execution_entity where \"workflowId\"='{wid}' order by \"startedAt\" desc limit 1;")
            if st and st != 'running':
                return wid, {'status': st}
        return wid, {'status': 'timeout'}
    finally:
        rest('POST', f'/rest/workflows/{wid}/archive')
        rest('DELETE', f'/rest/workflows/{wid}')


def stage(counts):
    out = os.path.join(ROOT, 'data', '_runs', 'hll_files')
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    used = set()
    tot = 0
    for dtype, cnt in counts.items():
        if cnt <= 0:
            continue
        base = os.path.join(ROOT, 'data', 'data-set-2', dtype)
        csvp = os.path.join(base, 'dataset.csv')
        if not os.path.exists(csvp):
            continue
        rows = [r for r in csv.DictReader(open(csvp, encoding='utf-8')) if r.get('LOCAL_PATH') and os.path.exists(os.path.join(base, r['LOCAL_PATH']))]
        random.shuffle(rows)
        made = 0
        for r in rows:
            if made >= cnt:
                break
            cn = (r.get('COMPANY_NAME') or 'Supplier').strip() or 'Supplier'
            fp = os.path.join(base, r['LOCAL_PATH'])
            ext = fp.rsplit('.', 1)[-1]
            safe = re.sub(r'[\\/:*?"<>|]', '', cn).strip()[:36] or 'Supplier'
            name = f"LINK {safe} 09.25-{dtype[:3]}{made}.{ext}"
            if name in used:
                name = f"LINK {safe}-{tot}.{ext}"
            used.add(name)
            shutil.copy(fp, os.path.join(out, name))
            made += 1
            tot += 1
        print(f"  staged {dtype}: {made}")
    # copy into container workflows mount
    host = os.path.join(ROOT, 'production', 'n8n', 'workflows', '_hll_files')
    shutil.rmtree(host, ignore_errors=True)
    os.makedirs(host)
    for f in os.listdir(out):
        shutil.copy(os.path.join(out, f), os.path.join(host, f))
    subprocess.run(['docker', 'exec', f'n8n-{DN}', 'sh', '-lc',
                    'rm -rf /home/node/.n8n-files/hll_files && mkdir -p /home/node/.n8n-files/hll_files && cp /home/node/workflows/_hll_files/* /home/node/.n8n-files/hll_files/ 2>/dev/null; ls /home/node/.n8n-files/hll_files | wc -l'],
                   capture_output=True, text=True)
    return tot


def make_folder():
    """Create a dedicated (non-watched) Drive folder; return its id by reading the Code-written file."""
    code = ("const fs=require('fs');"
            "const id=$input.first().json.id;"
            "fs.writeFileSync('/home/node/.n8n-files/hll_folder_id.txt', String(id));"
            "return [{json:{folderId:id}}];")
    wf = {"name": "highload-link:mkfolder", "nodes": [
        {"parameters": {}, "id": "t1", "name": "M", "type": "n8n-nodes-base.manualTrigger", "typeVersion": 1, "position": [0, 0]},
        {"parameters": {"resource": "folder", "operation": "create", "name": "INDOX-TableLinkSources", "driveId": {"__rl": True, "mode": "list", "value": "My Drive"}, "folderId": {"__rl": True, "mode": "id", "value": "root"}, "options": {}},
         "id": "t2", "name": "Mk", "type": "n8n-nodes-base.googleDrive", "typeVersion": 3, "position": [220, 0], "onError": "continueRegularOutput", "credentials": {"googleDriveOAuth2Api": {"id": CRED_DRIVE, "name": "x"}}},
        {"parameters": {"jsCode": code}, "id": "t3", "name": "Save", "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [440, 0]}],
        "connections": {"M": {"main": [[{"node": "Mk", "type": "main", "index": 0}]]}, "Mk": {"main": [[{"node": "Save", "type": "main", "index": 0}]]}}, "settings": {}}
    run_eph(wf, "Mk", timeout=120)
    out = subprocess.run(['docker', 'exec', f'n8n-{DN}', 'cat', '/home/node/.n8n-files/hll_folder_id.txt'],
                         capture_output=True, text=True, encoding='utf-8', errors='replace').stdout.strip()
    return out


def upload_capture(folder_id):
    """Upload staged files to folder_id; a Code node writes [{id,name}] to IDS_FILE."""
    code = ("const fs=require('fs');"
            "const files=$input.all().map(i=>({id:i.json.id,name:i.json.name,size:i.json.size||'',md5:i.json.md5Checksum||''}));"
            f"fs.writeFileSync('{IDS_FILE}', JSON.stringify(files));"
            "return [{json:{count:files.length}}];")
    wf = {"name": "highload-link:upload", "nodes": [
        {"parameters": {}, "id": "t1", "name": "M", "type": "n8n-nodes-base.manualTrigger", "typeVersion": 1, "position": [0, 0]},
        {"parameters": {"fileSelector": "/home/node/.n8n-files/hll_files/*", "options": {}}, "id": "t2", "name": "Read", "type": "n8n-nodes-base.readWriteFile", "typeVersion": 1, "position": [220, 0]},
        {"parameters": {"resource": "file", "operation": "upload", "name": "={{ $binary.data.fileName }}", "driveId": {"__rl": True, "mode": "list", "value": "My Drive"}, "folderId": {"__rl": True, "mode": "id", "value": folder_id}, "options": {}},
         "id": "t3", "name": "Up", "type": "n8n-nodes-base.googleDrive", "typeVersion": 3, "position": [440, 0], "retryOnFail": True, "maxTries": 4, "waitBetweenTries": 3000, "credentials": {"googleDriveOAuth2Api": {"id": CRED_DRIVE, "name": "x"}}},
        {"parameters": {"jsCode": code}, "id": "t4", "name": "Save", "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [660, 0]}],
        "connections": {"M": {"main": [[{"node": "Read", "type": "main", "index": 0}]]}, "Read": {"main": [[{"node": "Up", "type": "main", "index": 0}]]}, "Up": {"main": [[{"node": "Save", "type": "main", "index": 0}]]}}, "settings": {}}
    _, st = run_eph(wf, "Read", timeout=600)
    print("  upload:", st)
    out = subprocess.run(['docker', 'exec', f'n8n-{DN}', 'cat', IDS_FILE],
                         capture_output=True, text=True, encoding='utf-8', errors='replace').stdout.strip()
    try:
        return json.loads(out)
    except Exception:
        return []


def insert_rows(files):
    """Direct INSERT into incoming_documents -> table-change trigger fires main."""
    n = 0
    for f in files:
        fid = f.get('id')
        if not fid:
            continue
        name = (f.get('name') or '').replace("'", "''")
        link = f"https://drive.google.com/file/d/{fid}"
        did = 'LINK_' + hashlib.md5(fid.encode()).hexdigest()[:16]
        md5 = (f.get('md5') or '').replace("'", "''")
        size = str(f.get('size') or '')
        q = (f"insert into incoming_documents (\"ID\",\"NAME\",\"LINK\",\"SOURCE_LINK\",\"SOURCE_TYPE\","
             f"\"SOURCE_ID\",\"HASH\",\"SIZE\") values "
             f"('{did}','{name}','{link}','{link}','GOOGLE_DRIVE_FILE','{fid}','{md5}','{size}') "
             f"on conflict (\"ID\") do nothing;")
        r = sb(q)
        if 'INSERT' in (r.stdout + r.stderr):
            n += 1
        elif r.stderr.strip():
            print("   insert err:", r.stderr.strip()[:120])
    return n


if __name__ == '__main__':
    login()
    counts = {'invoice': int(arg('--inv', '0')), 'shipment': int(arg('--ship', '0')),
              'unknown': int(arg('--unk', '0')), 'balance_sheet': int(arg('--bs', '0'))}
    print(f"=== highload-inject-links: {counts} ===")
    tot = stage(counts)
    print(f"  staged total: {tot}")
    fid = make_folder()
    print(f"  folder id: {fid}")
    if not fid:
        print("  ABORT: no folder id"); sys.exit(1)
    files = upload_capture(fid)
    print(f"  uploaded+captured: {len(files)} ids")
    ins = insert_rows(files)
    print(f"DONE: inserted {ins} table-link rows (SOURCE_TYPE=GOOGLE_DRIVE_FILE)")
