#!/usr/bin/env python3
"""Drive injector for the LOCAL drive backend (drive api - local).

highload-inject.py uploads with a raw Google Drive credential — invisible to a stack
whose DRIVE_BACKEND resolves to local. This stages data-set-2 files into the n8n
container and uploads each via `driveApi01 {op:upload, params:{name, folderId}}`
(binary rides the item, exactly like the suites' 'Upload to Drive'), so the files land
in the LOCAL replica's to_sync folders where the sync scanner actually LISTs.

  python scripts/_inject_drive_local.py --inv 2 --ship 1 --unk 1 --bs 1
"""
import sys, os, csv, json, random, shutil, subprocess, importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location('hli', os.path.join(ROOT, 'scripts', 'highload-inject.py'))
hli = importlib.util.module_from_spec(spec)
sys.argv_backup, sys.argv = sys.argv, [sys.argv[0]]  # keep hli's main() from running on import
spec.loader.exec_module(hli)
sys.argv = sys.argv_backup

GENERAL = hli.GENERAL_FOLDER   # GeneralDocsSource1 to_sync
BS = hli.BS_FOLDER             # BalanceSheetSource1 to_sync


def arg(name, d):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else d


def pick(dtype, n):
    base = os.path.join(ROOT, 'data', 'data-set-2', dtype)
    rows = [r for r in csv.DictReader(open(os.path.join(base, 'dataset.csv'), encoding='utf-8'))
            if r.get('LOCAL_PATH') and os.path.exists(os.path.join(base, r['LOCAL_PATH']))]
    random.shuffle(rows)
    return [os.path.join(base, r['LOCAL_PATH']) for r in rows[:n]]


def main():
    counts = {'invoice': int(arg('--inv', '0')), 'shipment': int(arg('--ship', '0')),
              'unknown': int(arg('--unk', '0')), 'balance_sheet': int(arg('--bs', '0'))}
    out = os.path.join(ROOT, 'data', '_runs', 'idl_stage')
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    n = 0
    for dtype, cnt in counts.items():
        prefix = 'BSF' if dtype == 'balance_sheet' else 'GEN'   # folder routing via filename prefix
        for fp in pick(dtype, cnt):
            shutil.copy(fp, os.path.join(out, f'{prefix}__a2-{dtype[:3]}{n}__{os.path.basename(fp)}'))
            n += 1
    if n == 0:
        print('nothing to inject'); return
    hli.login()
    path = hli.stage_to_n8n(out, 'drvlocal')
    code = (
        "return $input.all().map((it,i)=>{const fn=it.binary.data.fileName||'';"
        f"const folder=fn.startsWith('BSF__')?'{BS}':'{GENERAL}';"
        "const name=fn.replace(/^(BSF|GEN)__/,'');"
        "return {json:{op:'upload', params:{name, folderId:folder}}, binary:it.binary, pairedItem:{item:i}};});")
    wf = {"name": "a2-inject:drive-local", "nodes": [
        {"parameters": {}, "id": "t1", "name": "M", "type": "n8n-nodes-base.manualTrigger", "typeVersion": 1, "position": [0, 0]},
        {"parameters": {"fileSelector": f"{path}/*", "options": {}}, "id": "t2", "name": "Read", "type": "n8n-nodes-base.readWriteFile", "typeVersion": 1, "position": [220, 0]},
        {"parameters": {"jsCode": code}, "id": "t3", "name": "Build", "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [440, 0]},
        {"parameters": {"workflowId": {"__rl": True, "value": "driveApi01", "mode": "id"},
                        "workflowInputs": {"mappingMode": "defineBelow",
                                           "value": {"op": "={{ $json.op }}", "params": "={{ $json.params }}"}},
                        "options": {"waitForSubWorkflow": True}},
         "id": "t4", "name": "Up", "type": "n8n-nodes-base.executeWorkflow", "typeVersion": 1.2, "position": [660, 0]}],
        "connections": {"M": {"main": [[{"node": "Read", "type": "main", "index": 0}]]},
                        "Read": {"main": [[{"node": "Build", "type": "main", "index": 0}]]},
                        "Build": {"main": [[{"node": "Up", "type": "main", "index": 0}]]}},
        "settings": {}}
    print(f'uploading {n} files via driveApi01 (local backend)...')
    print('->', hli.run_eph(wf, 'Read', timeout=300))

if __name__ == '__main__':
    main()
