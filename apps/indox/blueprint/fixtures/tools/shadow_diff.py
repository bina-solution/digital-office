#!/usr/bin/env python3
"""
KW fixture shadow-diff harness (migration Step 2).

Proves a per-type fixture's kw_extract (query_after/below + normalizer) reproduces the
LIVE KW columns, WITHOUT touching the live pipeline. For each test doc it calls the real
apitools /documentJsonQuery with the fixture's queries, normalizes via the shared registry
(production/n8n/lib/normalizers.js), and diffs against the live incoming_documents columns.
Empty diff == the fixture is faithful and the generic kwExtract01 engine can cut over.

Usage:  python shadow_diff.py <TYPE> <id1,id2,...>
Example: python shadow_diff.py INVOICE gdx_inv1,gdx_inv2,gdx_inv3,gdx_inv4,gdx_inv5

Requires: docker (supabase-db + apitools containers), node (for the normalizer lib).
"""
import json, subprocess, sys, os, tempfile

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
FIXTURES = os.path.join(REPO, "production", "n8n", "fixtures")
LIB = os.path.join(REPO, "production", "n8n", "lib", "normalizers.js")
# fixture target -> live column its normalized value must equal
CMP = {"INVOICE_ID": "SHORT_DOC_ID", "DOC_DATE": "DOC_DATE", "DOC_TOTAL_AMOUNT": "DOC_TOTAL_AMOUNT",
       "PURCHASE_ID": "PURCHASE_ID", "SHIPMENT_DOC_ID": "SHIPMENT_DOC_ID"}

def sh(args): return subprocess.run(args, capture_output=True, text=True, encoding="utf-8").stdout

def apitools_container():
    return sh(["docker", "ps", "--filter", "name=apitools", "--format", "{{.Names}}"]).strip().split("\n")[0]

def main():
    typ = sys.argv[1] if len(sys.argv) > 1 else "INVOICE"
    ids = (sys.argv[2] if len(sys.argv) > 2 else "gdx_inv1,gdx_inv2,gdx_inv3,gdx_inv4,gdx_inv5").split(",")
    fx = json.load(open(os.path.join(FIXTURES, f"fixture_{typ}.json"), encoding="utf-8"))
    fields = fx["kw_extract"]["fields"]
    nz = {f["target"]: f["normalizer"] for f in fields}

    cols = ",".join(f'"{c}"' for c in ["ID", "API_TOOLS_ID"] + sorted(set(CMP.values())))
    idlist = ",".join(f"'{i}'" for i in ids)
    rows = sh(["docker", "exec", "supabase-db-shlomo-laptop", "psql", "-U", "postgres", "-d", "postgres",
               "-tAF|", "-c", f'SELECT {cols} FROM incoming_documents WHERE "ID" IN ({idlist}) ORDER BY "ID"'])
    hdr = ["ID", "API_TOOLS_ID"] + sorted(set(CMP.values()))
    docs = []
    for line in rows.strip().split("\n"):
        if not line.strip(): continue
        p = line.split("|"); r = dict(zip(hdr, p))
        docs.append({"id": r["ID"], "at": r["API_TOOLS_ID"], "live": {c: r.get(c, "") for c in set(CMP.values())}})

    manifest = {"docs": docs, "fields": [{"target": f["target"], "after": f["query_after"], "below": f.get("query_below")} for f in fields]}
    tmp = tempfile.gettempdir()
    open(os.path.join(tmp, "sd_manifest.json"), "w", encoding="utf-8").write(json.dumps(manifest, ensure_ascii=False))
    atc = apitools_container()
    subprocess.run(["docker", "cp", os.path.join(tmp, "sd_manifest.json"), f"{atc}:/tmp/manifest.json"],
                   env={**os.environ, "MSYS_NO_PATHCONV": "1"})
    subprocess.run(["docker", "exec", atc, "python3", "-c", r"""
import urllib.request,json
m=json.load(open('/tmp/manifest.json'))
def q(at,query):
    try:
        d=json.dumps({'file_id':at,'ocr_json_query':query}).encode()
        r=urllib.request.urlopen(urllib.request.Request('http://localhost:8080/documentJsonQuery',d,{'Content-Type':'application/json'}),timeout=45)
        res=json.load(r).get('result'); return res.get('result') if isinstance(res,dict) else res
    except Exception: return None
out=[]
for doc in m['docs']:
    row={'id':doc['id'],'live':doc['live'],'raw':{}}
    for f in m['fields']:
        v=q(doc['at'],f['after'])
        if not v and f.get('below'): v=q(doc['at'],f['below'])
        row['raw'][f['target']]=v
    out.append(row)
open('/tmp/sd_raw.json','w').write(json.dumps(out,ensure_ascii=False))
"""])
    subprocess.run(["docker", "cp", f"{atc}:/tmp/sd_raw.json", os.path.join(tmp, "sd_raw.json")],
                   env={**os.environ, "MSYS_NO_PATHCONV": "1"})

    node = f"""
const {{makeNormalizers}}=require({json.dumps(LIB)}); const N=makeNormalizers();
const raw=JSON.parse(require('fs').readFileSync({json.dumps(os.path.join(tmp,'sd_raw.json'))},'utf8'));
const nz={json.dumps(nz)}, cmp={json.dumps(CMP)};
let diffs=0,tot=0;
for(const d of raw) for(const t of Object.keys(cmp)){{
  const norm=N.registry[nz[t]]||((v)=>v==null?null:String(v).trim());
  const g=String(norm(d.raw[t])||''), l=String((d.live[cmp[t]]||'').trim()); tot++;
  if(g!==l){{diffs++; console.log('DIFF '+d.id+' '+t+': engine=\"'+g+'\" live=\"'+l+'\"');}}
}}
console.log('\\nSHADOW-DIFF ['+{json.dumps(typ)}+']: '+(tot-diffs)+'/'+tot+' match ('+diffs+' diffs)');
process.exit(diffs?1:0);
"""
    r = subprocess.run(["node", "-e", node]); sys.exit(r.returncode)

if __name__ == "__main__":
    main()
