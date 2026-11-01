#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_inject_workflow.py — additive, idempotent extension of
apps/indox/blueprint/n8n/IndoxInjectDemo01.json so `bbox indox demo run <name>` can express the
owner's E2E load-test spec: multi-attachment emails and a LOCAL (never-real-Google) drive path.

Adds three new Read/Build/Send node-triples at the END of the existing sequential chain:
  e2e-mail          -> gmailApiRouter01 op:append  (1-3 files grouped into one MIME email each)
  e2e-drive-gdoc     -> driveApi01 op:upload (general docs)
  e2e-drive-bs       -> driveApi01 op:upload (balance-sheet docs)

Zero behaviour change for existing blueprints (welcome/small/large): the new Build nodes filter
strictly on bp.syncs['e2e-mail'] / ['e2e-drive-gdoc'] / ['e2e-drive-bs'], which those blueprints
never define, so they emit zero items and the new Send nodes no-op.

Safety fix baked into the NEW nodes only (existing gmail-doc/gmail-bs/drive-gdoc/drive-bs are left
untouched — this script does not touch them): every emitted `params` object carries an EXPLICIT
`connection_id` read from the blueprint (`bp.mail_connection_id` / `bp.drive_connection_id`), never
relying on gmailApiRouter01 / driveApi01's active-connection fallback. Both downstream HTTP nodes
(gmailApiImap01's /append, driveApi01's d:upload) already forward `params.connection_id` verbatim
(driveApi01.json's d:upload node has an explicit connection_id bodyParameter; gmailApiImap01 sends
`$json.params` as the whole POST body) — so no changes to those workflows are needed.

Usage:  python3 scripts/ops/e2e-loadtest/patch_inject_workflow.py [--check]
Then deploy with `bbox n8n push` (one push at a time — check `ps aux | grep "[n]8n push"` first).
"""
import json
import os
import sys

import sys as _sys
# Prints Hebrew/bidi text. On a host whose stdout is not already UTF-8 that raises
# UnicodeEncodeError on the first Hebrew character, and the traceback reads as a logic
# failure rather than an encoding one. Same guard the gates use. (G10)
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(_sys.stderr, "reconfigure"):
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
WF = os.path.join(ROOT, "apps", "indox", "blueprint", "n8n", "IndoxInjectDemo01.json")

NEW_NAMES = {"Read e2e-mail", "Build e2e-mail", "Send e2e-mail",
             "Read e2e-drive-gdoc", "Build e2e-drive-gdoc", "Send e2e-drive-gdoc",
             "Read e2e-drive-bs", "Build e2e-drive-bs", "Send e2e-drive-bs"}

FILES_GLOB = "/home/node/.n8n-files/demo-docs/e2e-loadtest/files/*"

BUILD_MAIL_JS = r"""function enchdr(s){ return '=?UTF-8?B?'+Buffer.from(String(s),'utf8').toString('base64')+'?='; }
function b64lines(s){ return s.replace(/(.{76})/g,'$1\r\n'); }
function mimePart(filename, contentB64){
  const ext=(filename.split('.').pop()||'').toLowerCase();
  const ct = ext==='pdf' ? 'application/pdf' : (ext==='png'?'image/png':'image/jpeg');
  return ['Content-Type: '+ct+'; name="'+filename+'"','Content-Transfer-Encoding: base64',
    'Content-Disposition: attachment; filename="'+enchdr(filename)+'"','',b64lines(contentB64),''].join('\r\n');
}
function buildMime(o){
  const b='bnd_'+Math.random().toString(36).slice(2,12);
  const head=['From: '+o.from,'To: '+o.to,'Date: '+(o.date||new Date().toUTCString()),
    'Subject: '+enchdr(o.subject),'MIME-Version: 1.0',
    'Content-Type: multipart/mixed; boundary="'+b+'"','',
    '--'+b,'Content-Type: text/plain; charset="UTF-8"','Content-Transfer-Encoding: base64','',
    Buffer.from(o.body,'utf8').toString('base64'),''].join('\r\n');
  const parts = o.attachments.map(a => '--'+b+'\r\n'+mimePart(a.filename, a.contentB64)).join('');
  return Buffer.from(head+'\r\n'+parts+'--'+b+'--\r\n','utf8').toString('base64');
}
const items=$input.all();
const bp=(()=>{try{return $('Plan').first().json.bp||{}}catch(e){return {}}})();
const list=((bp.syncs)||{})['e2e-mail']||[];
const _S=new Set(list.map(f=>(f&&f.name)||f));
const wi=items.map((it,i)=>({i,fn:(it.binary&&it.binary.data&&it.binary.data.fileName)||''})).filter(r=>_S.has(r.fn));
const _byName={}; for(const f of list) _byName[(f&&f.name)||f]=f;
const _coById={}; for(const c of (bp.companies||(bp.company?[bp.company]:[]))) _coById[String(c.id)]={name:c.name,email:c.email};
const connId=bp.mail_connection_id||'';
const groups={};
for(const r of wi){ const meta=_byName[r.fn]||{}; const gid=meta.group||r.fn; (groups[gid]=groups[gid]||[]).push({r,meta}); }
const out=[];
for(const gid of Object.keys(groups)){
  const entries=groups[gid]; const first=entries[0].meta;
  const co=_coById[String(first.company_id)]||{};
  const from=(first.sender_name||co.name||'E2E Supplier')+' <'+(first.sender_email||co.email||('e2e+'+gid+'@e2e-loadtest.local'))+'>';
  const subj='מסמכים '+(co.name||first.company_id||gid);
  const atts=[];
  for(const e of entries){ const buf=await this.helpers.getBinaryDataBuffer(e.r.i,'data'); atts.push({filename:e.r.fn,contentB64:buf.toString('base64')}); }
  const mime=buildMime({from,to:'e2e-loadtest@e2e-loadtest.local',subject:subj,
    body:'E2E load-test injected message ('+entries.length+' attachment(s)).',attachments:atts,date:first.mail_date});
  const params={raw_base64:mime,folder:'INBOX'};
  if(connId) params.connection_id=connId;
  out.push({json:{op:'append',params}});
}
return out;"""

BUILD_DRIVE_JS_TMPL = r"""const items=$input.all();
const bp=(()=>{try{return $('Plan').first().json.bp||{}}catch(e){return {}}})();
const list=((bp.syncs)||{})['%(SYNC)s']||[];
const _S=new Set(list.map(f=>(f&&f.name)||f));
const wi=items.map((it,i)=>({i,fn:(it.binary&&it.binary.data&&it.binary.data.fileName)||''})).filter(r=>_S.has(r.fn));
const _byName={}; for(const f of list) _byName[(f&&f.name)||f]=f;
const _coById={}; for(const c of (bp.companies||(bp.company?[bp.company]:[]))) _coById[String(c.id)]={name:c.name,email:c.email};
const folderId=(bp.drive_folders||{})['%(FOLDER_KEY)s']||'';
const connId=bp.drive_connection_id||'';
return wi.map(r=>{
  const meta=_byName[r.fn]||{}; const co=_coById[String(meta.company_id)]||{};
  const params={folderId,name:(co.name?(co.name+' '):'')+r.fn};
  if(connId) params.connection_id=connId;
  return {json:{op:'upload',params},binary:items[r.i].binary};
});"""


def node(id_, name, type_, typever, pos, params, extra=None):
    n = {"id": id_, "name": name, "type": type_, "typeVersion": typever, "position": pos, "parameters": params}
    if extra:
        n.update(extra)
    return n


def make_triple(idbase, sync_name, y, build_js, target_wf):
    read = node(idbase + "a", f"Read {sync_name}", "n8n-nodes-base.readWriteFile", 1,
                [1220, y], {"fileSelector": FILES_GLOB, "options": {}})
    build = node(idbase + "b", f"Build {sync_name}", "n8n-nodes-base.code", 2,
                 [1420, y], {"jsCode": build_js})
    send = node(idbase + "c", f"Send {sync_name}", "n8n-nodes-base.executeWorkflow", 1.2,
                [1620, y], {"workflowId": {"__rl": True, "value": target_wf, "mode": "id"}, "options": {}},
                extra={"onError": "continueRegularOutput", "alwaysOutputData": True})
    return read, build, send


def main():
    check_only = "--check" in sys.argv
    with open(WF, encoding="utf-8") as f:
        d = json.load(f)

    existing = {n["name"] for n in d["nodes"]}
    if NEW_NAMES <= existing:
        print("[patch] already applied — no-op")
        return 0
    if check_only:
        print("[patch] NOT applied yet")
        return 1

    triples = [
        make_triple("e2e0001-0000-0000-0000-00000000mail", "e2e-mail", 500,
                    BUILD_MAIL_JS, "gmailApiRouter01"),
        make_triple("e2e0002-0000-0000-0000-0000000gdoc", "e2e-drive-gdoc", 700,
                    BUILD_DRIVE_JS_TMPL % {"SYNC": "e2e-drive-gdoc", "FOLDER_KEY": "gdoc_to_sync"},
                    "driveApi01"),
        make_triple("e2e0003-0000-0000-0000-00000000e-bs", "e2e-drive-bs", 900,
                    BUILD_DRIVE_JS_TMPL % {"SYNC": "e2e-drive-bs", "FOLDER_KEY": "bs_to_sync"},
                    "driveApi01"),
    ]

    for triple in triples:
        d["nodes"].extend(triple)

    conns = d["connections"]
    # rewire the end of the existing chain ("Send gmail-link" is currently a dead end) into ours
    conns["Send gmail-link"] = {"main": [[{"node": "Read e2e-mail", "type": "main", "index": 0}]]}
    chain = [
        ("Read e2e-mail", "Build e2e-mail"), ("Build e2e-mail", "Send e2e-mail"),
        ("Send e2e-mail", "Read e2e-drive-gdoc"),
        ("Read e2e-drive-gdoc", "Build e2e-drive-gdoc"), ("Build e2e-drive-gdoc", "Send e2e-drive-gdoc"),
        ("Send e2e-drive-gdoc", "Read e2e-drive-bs"),
        ("Read e2e-drive-bs", "Build e2e-drive-bs"), ("Build e2e-drive-bs", "Send e2e-drive-bs"),
    ]
    for a, b in chain:
        conns[a] = {"main": [[{"node": b, "type": "main", "index": 0}]]}

    with open(WF, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    print(f"[patch] added {len(NEW_NAMES)} nodes to {WF}")
    print("[patch] next: bbox n8n push   (check `ps aux | grep \"[n]8n push\"` first — one push at a time)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
