#!/usr/bin/env python3
"""REAL end-to-end run over every live sync registry, on this machine's own connections.

For each gmail pipe: N real e-mails are SENT (SMTP, from the mailbox to itself) — attachment
pipes carry a PDF from the demo corpus, the link pipe carries a public PDF URL in the body — and
each message is then given the pipe's to-sync label. For each drive pipe: N files are UPLOADED
into the pipe's source folder. Every document is unique bytes (a run stamp is appended after the
PDF's %%EOF, which every reader tolerates) and carries the run TAG in its subject / file name, so
`indox-e2e-timeline.py --tag <tag>` finds exactly this run and nothing else. The switches are
turned on, a sync pass is started, and the run is polled until every item is delivered and every
document reached a terminal status — then the timeline prints.

    python3 scripts/ops/indox-e2e-real.py --tenant hacohen --per-pipe 3 --wait-min 60

Runs on the docker host (laptop: WSL). Talks to the mail / drive apps through their containers
(no host port is needed), to Postgres through supabase-db, to the BFF through its container.
Synthetic data is MARKED by the tag; nothing here touches the client's connections.
"""
import argparse
import base64
import json
import os
import random
import subprocess
import sys
import time
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):          # Hebrew on a Windows console (cp1255) raises without it
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DOCKER = os.environ.get("DOCKER_CMD", "docker -H unix:///run/bbox-docker.sock" if os.path.exists("/run/bbox-docker.sock") else "docker")
LINK_PDF_URL = "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"


def sh(cmd: str, inp: str | None = None, check: bool = True) -> str:
    r = subprocess.run(cmd, shell=True, input=inp, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise SystemExit(f"{cmd[:120]}… → {r.stderr.strip()[:400]}")
    return r.stdout


def container(prefix: str) -> str:
    for n in sh(f"{DOCKER} ps --format '{{{{.Names}}}}'").split():
        if n.startswith(prefix):
            return n
    raise SystemExit(f"no running container starting with {prefix}")


def psql(c: str, sql: str) -> str:
    return sh(f"{DOCKER} exec -i {c} psql -U postgres -d postgres -Atq", inp=sql)


def py_in(c: str, code: str, payload: dict | None = None) -> str:
    """Run python inside a container, the payload as JSON on stdin (arbitrary size). The script
    travels base64-encoded — the only shell-safe way through `docker exec` on every host."""
    script = "import json,sys\nP=json.loads(sys.stdin.read()) if not sys.stdin.isatty() else {}\n" + code
    b64 = base64.b64encode(script.encode()).decode()
    r = subprocess.run(f"{DOCKER} exec -i {c} python3 -c \"import base64;exec(base64.b64decode('{b64}').decode())\"",
                       shell=True, input=json.dumps(payload or {}), capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"in {c}: {r.stderr.strip()[:600]}")
    return r.stdout


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="hacohen")
    ap.add_argument("--instance", default="incoming-documents-main")
    ap.add_argument("--per-pipe", type=int, default=3)
    ap.add_argument("--tag", default="e2e-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M"))
    ap.add_argument("--wait-min", type=int, default=60)
    ap.add_argument("--only", help="comma-separated pipe names")
    ap.add_argument("--no-kick", action="store_true", help="do not start a pass; wait for the tick")
    ap.add_argument("--old-months", type=int, default=36,
                    help="ageing window for the run (the corpus is dated 2025; 0 = leave the tenant's value)")
    ap.add_argument("--keep-window", action="store_true",
                    help="leave the widened window in place after the run. Measured 2026-09-02: restoring it "
                         "re-ages every completed 2025-dated document to OLD on the next pass (the late age "
                         "gate re-decides changed rows), which is correct product behaviour but hides the "
                         "COMPLETED rows from whoever inspects the run afterwards.")
    a = ap.parse_args()
    tag = a.tag
    schema = f"indox_{a.tenant}"
    db, mail, drive, bff, demo = (container("supabase-db"), container("mailapi-"), container("drive-"),
                                  container("incoming-documents-"), container("indox-demo-docs"))
    out_dir = os.path.join("data", "_e2e"); os.makedirs(out_dir, exist_ok=True)
    sent_file = os.path.join(out_dir, f"{tag}.sent.json")

    # 1. the registry, as it is — from the TENANT's settings table, the one the engine reads
    #    (syncV3Main0001 'Read Config': indox_<tenant>.settings; public.settings is the console
    #    instance's mirror and can lag a direct edit).
    reg = json.loads(psql(db, f"select value from {schema}.settings where key='sync_registry' order by updated_at desc nulls last limit 1;") or "[]")
    only = set(a.only.split(",")) if a.only else None
    pipes = [e for e in reg if e.get("enabled", True) and (not only or e["name"] in only)]
    print(f"run {tag}: {len(pipes)} pipes → {[p['name'] for p in pipes]}")

    # 2. label names from the ONE rules store (the mail app's organizer settings)
    labels = json.loads(py_in(mail, "import urllib.request\nd=json.loads(urllib.request.urlopen('http://127.0.0.1:8970/organizer/settings',timeout=60).read().decode())\nprint(json.dumps({k:v.get('name') for k,v in ((d.get('gmail') or {}).get('labels') or {}).items()}))"))

    # 3. the corpus: PDFs by type from the demo container
    def corpus(kind: str, n: int) -> list[tuple[str, bytes]]:
        names = sh(f"{DOCKER} exec -i {demo} sh -c 'ls /srv/{kind}/files/*.pdf 2>/dev/null | grep -v \"\\.dbf\\.\\|\\.plp\\.\" | head -40'").split()
        random.shuffle(names)
        picks = names[:n]
        outp = []
        for pth in picks:
            b64 = sh(f"{DOCKER} exec -i {demo} sh -c 'base64 -w0 {pth}'")
            outp.append((os.path.basename(pth), base64.b64decode(b64)))
        return outp

    def stamped(data: bytes, mark: str) -> bytes:
        return data + f"\n%{mark}\n".encode()

    sent: dict[str, str] = {}
    plan_mail: list[dict] = []
    plan_drive: list[dict] = []
    for e in pipes:
        kind = "balance_sheet" if str(e.get("type_hint") or e.get("fallback_type") or "").upper() == "BALANCE_SHEET" else "invoice"
        if e.get("source") == "gmail":
            to_key = (e.get("labels") or {}).get("to_sync")
            lab = labels.get(to_key) or to_key
            is_link = e["name"].endswith("link") or to_key == "DOC_LINK_TO_SYNC"
            docs = [] if is_link else corpus(kind, a.per_pipe)
            for i in range(a.per_pipe):
                base = f"{tag}-{e['name']}-{i+1}"
                if is_link:
                    plan_mail.append({"pipe": e["name"], "subject": f"{base} link", "label": lab,
                                      "body": f"{base}\nמסמך מקושר: {LINK_PDF_URL}\n", "attachments": []})
                else:
                    fname, data = docs[i % len(docs)]
                    plan_mail.append({"pipe": e["name"], "subject": f"{base} {fname}", "label": lab,
                                      "body": f"{base}\nמצורף מסמך לבדיקת קצה-לקצה.\n",
                                      "attachments": [{"filename": f"{base}-{fname}", "mimeType": "application/pdf",
                                                       "data_base64": base64.b64encode(stamped(data, base)).decode()}]})
        else:
            pair = (e.get("pairs") or [{}])[0]
            folder = pair.get("to_sync") or pair.get("from")
            docs = corpus(kind, a.per_pipe)
            for i in range(a.per_pipe):
                base = f"{tag}-{e['name']}-{i+1}"
                fname, data = docs[i % len(docs)]
                plan_drive.append({"pipe": e["name"], "folder": folder, "name": f"{base}-{fname}",
                                   "data_base64": base64.b64encode(stamped(data, base)).decode(), "connection": e.get("connection")})

    # 4. send the mails, then label them
    mail_conn = next((e.get("connection") for e in pipes if e.get("source") == "gmail"), None)
    if plan_mail and mail_conn:
        acct = json.loads(py_in(mail, "import urllib.request\nprint(urllib.request.urlopen('http://127.0.0.1:8970/connections/%s/probe' % P['cid'],timeout=60).read().decode())", {"cid": mail_conn}))
        to_addr = acct.get("account_hint")
        print(f"mailbox {mail_conn} = {to_addr}: sending {len(plan_mail)} messages")
        res = py_in(mail, """
import urllib.request, time
out=[]
for m in P['msgs']:
    body=json.dumps({'to':P['to'],'subject':m['subject'],'body':m['body'],'attachments':m['attachments'],'connection_id':P['cid']}).encode()
    req=urllib.request.Request('http://127.0.0.1:8970/send',data=body,headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=180) as r: out.append({'subject':m['subject'],'ok':True,'at':time.time()})
    except Exception as ex: out.append({'subject':m['subject'],'ok':False,'err':str(ex)[:200]})
print(json.dumps(out))""", {"msgs": plan_mail, "to": to_addr, "cid": mail_conn})
        for r in json.loads(res):
            if r["ok"]:
                sent[r["subject"]] = datetime.fromtimestamp(r["at"], tz=timezone.utc).isoformat()
            else:
                print("  send FAILED:", r["subject"], r["err"])
        print(f"  sent {sum(1 for r in json.loads(res) if r['ok'])}/{len(plan_mail)}; waiting 45 s for delivery, then labelling")
        time.sleep(45)
        res = py_in(mail, """
import urllib.request, time
out=[]
for m in P['msgs']:
    q=json.dumps({'folder':'[Gmail]/All Mail','query':'subject:"%s" newer_than:1d' % m['subject'],'limit':5,'connection_id':P['cid'],'allow_unknown_labels':True}).encode()
    ids=[]
    for attempt in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8970/search',data=q,headers={'Content-Type':'application/json'}),timeout=300) as r:
                d=json.loads(r.read().decode()); ids=[str(x['id']) for x in d.get('messages',[]) if x.get('id')]
        except Exception as ex: ids=[]
        if ids: break
        time.sleep(20)
    if not ids: out.append({'subject':m['subject'],'ok':False,'err':'not found after search'}); continue
    b=json.dumps({'ids':ids,'labels':[m['label']],'connection_id':P['cid']}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8970/labels/add',data=b,headers={'Content-Type':'application/json'}),timeout=300) as r: out.append({'subject':m['subject'],'ok':True,'ids':ids,'label':m['label']})
    except Exception as ex: out.append({'subject':m['subject'],'ok':False,'err':str(ex)[:200]})
print(json.dumps(out))""", {"msgs": plan_mail, "cid": mail_conn})
        labelled = json.loads(res)
        print(f"  labelled {sum(1 for r in labelled if r['ok'])}/{len(labelled)}" + "".join(f"\n  label FAILED: {r['subject']} {r.get('err')}" for r in labelled if not r["ok"]))

    # 5. upload the drive files
    if plan_drive:
        res = py_in(drive, """
import urllib.request, base64, uuid, time
out=[]
for f in P['files']:
    boundary='----e2e'+uuid.uuid4().hex
    data=base64.b64decode(f['data_base64'])
    parts=[]
    for k,v in (('name',f['name']),('folderId',f['folder']),('connection_id',f['connection'])):
        parts.append(('--%s\\r\\nContent-Disposition: form-data; name="%s"\\r\\n\\r\\n%s\\r\\n' % (boundary,k,v)).encode())
    parts.append(('--%s\\r\\nContent-Disposition: form-data; name="file"; filename="%s"\\r\\nContent-Type: application/pdf\\r\\n\\r\\n' % (boundary,f['name'])).encode()+data+b'\\r\\n')
    parts.append(('--%s--\\r\\n' % boundary).encode())
    body=b''.join(parts)
    req=urllib.request.Request('http://127.0.0.1:8975/upload?connection_id='+f['connection'],data=body,headers={'Content-Type':'multipart/form-data; boundary='+boundary})
    try:
        with urllib.request.urlopen(req,timeout=300) as r: j=json.loads(r.read().decode()); out.append({'name':f['name'],'ok':True,'id':j.get('id'),'at':time.time()})
    except Exception as ex: out.append({'name':f['name'],'ok':False,'err':str(ex)[:300]})
print(json.dumps(out))""", {"files": plan_drive})
        ups = json.loads(res)
        for r in ups:
            if r["ok"]:
                sent[r["name"]] = datetime.fromtimestamp(r["at"], tz=timezone.utc).isoformat()
            else:
                print("  upload FAILED:", r["name"], r["err"])
        print(f"  uploaded {sum(1 for r in ups if r['ok'])}/{len(ups)}")
    json.dump(sent, open(sent_file, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"sent map: {sent_file}")

    # 6. switches on, a pass now. The demo corpus is dated 2025, so under the operator's ageing
    # window (OldDocumentMonthsBack, 6) every document would park as OLD before extraction ran and
    # the run would prove nothing past typing. The window is widened for the run and restored at
    # the end — the value is the tenant's, read back before it is touched, and restored verbatim.
    psql(db, "\n".join(f"insert into public.settings (instance,key,value) values ('{a.instance}','{k}','true') on conflict (instance,key) do update set value='true';"
                       for k in ("indoxOn", "indoxSyncOn", "indoxDrainOn")))
    print("switches: indoxOn / indoxSyncOn / indoxDrainOn = true")
    old_months_before = psql(db, f"select coalesce(json_agg(json_build_object('instance',instance,'value',value)),'[]') from {schema}.settings where key='OldDocumentMonthsBack';").strip()
    if a.old_months:
        psql(db, f"update {schema}.settings set value='{int(a.old_months)}' where key='OldDocumentMonthsBack';")
        print(f"OldDocumentMonthsBack: {old_months_before} → {a.old_months} for this run (restored at the end)")
    if not a.no_kick:
        kick = py_in(bff, "import urllib.request\nreq=urllib.request.Request('http://127.0.0.1:8080/incomingDocuments/sync/run?instance=%s' % P['t'],data=b'{}',headers={'Content-Type':'application/json'})\nprint(urllib.request.urlopen(req,timeout=600).read().decode()[:400])", {"t": a.tenant})
        print("pass:", kick.strip()[:300])

    # 7. poll until settled
    t0 = time.time()
    tagq = tag.replace("'", "")
    while time.time() - t0 < a.wait_min * 60:
        st = psql(db, f"""select coalesce(json_agg(row_to_json(t)),'[]') from (
  select status, count(*)::int as n from {schema}.sync_ledger where coalesce(listing->>'subject','') like '%{tagq}%' or coalesce(listing->>'name','') like '%{tagq}%' group by 1) t;""")
        ds = psql(db, f"""select coalesce(json_agg(row_to_json(t)),'[]') from (
  select "STATUS" as s, count(*)::int as n from {schema}.incoming_documents
  where "NAME" like '%{tagq}%' or "ATTACHMENT_TEXT" like '%{tagq}%' group by 1) t;""")
        # (update_name rewrites NAME to company+number mid-pipeline; ATTACHMENT_TEXT keeps the
        #  original file name, so a renamed document stays in the count until it is terminal.)
        items = {r["status"]: r["n"] for r in json.loads(st or "[]")}
        docs = {r["s"]: r["n"] for r in json.loads(ds or "[]")}
        expected = len(plan_mail) + len(plan_drive)
        pending_items = sum(v for k, v in items.items() if k in ("discovered", "claimed", "failed"))
        active_docs = sum(v for k, v in docs.items() if k in ("IN_PROGRESS", "TO_EXTRACT", "ACTION_RESTART", None, ""))
        print(f"  {int(time.time()-t0)//60:3d}m  items {items} / {expected}   docs {docs}")
        if sum(items.values()) >= expected and pending_items == 0 and active_docs == 0 and sum(docs.values()) > 0:
            break
        time.sleep(60)
    if a.old_months and not a.keep_window:
        for row in json.loads(old_months_before or "[]"):
            psql(db, f"update {schema}.settings set value='{row['value']}' where key='OldDocumentMonthsBack' and instance='{row['instance']}';")
        print(f"OldDocumentMonthsBack restored: {old_months_before}")
    elif a.old_months:
        print(f"OldDocumentMonthsBack left at {a.old_months} (--keep-window); the tenant's value was {old_months_before}")
    print("\n=== timeline ===")
    os.system(f"python3 scripts/ops/indox-e2e-timeline.py --tenant {a.tenant} --tag {tag} --sent {sent_file} --json {os.path.join(out_dir, tag + '.timeline.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
