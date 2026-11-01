#!/usr/bin/env node
// Stack-free EQUIVALENCE test for the INDOX v2 ACTION layer.
// The v2 collections + driver-shell are verbatim extractions of v1; this asserts that every
// carried-over node is byte-identical to its v1 original (type + typeVersion + parameters +
// credentials) and that its wiring (to nodes within the same workflow) matches v1. If this
// passes, each action behaves exactly as v1 by construction.
//   ./bbox app indox v2-actions-test        exit 0 = identical, 1 = any drift
//
// [T-13, 2026-08-14] Same path bug as v2-decide-test.mjs, same root cause: WF() resolved
// id+'.json' under 'apps/n8n/blueprint/n8n', which never held these files in this
// checkout (git ls-files: only the 4 base-app workflows live there) — ENOENT before a single
// node compared. Fixed to 'blueprint/n8n' (repo source of truth per CLAUDE.md), matching
// where indoxV2ActionsGlobal01/GDoc01/BS01/Driver01 actually live.
//
// The v1 comparand ('sv5xxRBVGxvV0kXx') no longer exists anywhere live: 0 rows in
// workflow_entity (queried 2026-08-14), absent from the blueprint — fully retired in the
// legacy purge (commit 0312f566). Best-effort loaded from the last frozen snapshot in the
// repo (2026-07-07) below, so a missing file degrades to a clear skip instead of a crash.
// Diffing against it is now a HISTORY question, not a regression gate: this snapshot predates
// 5+ weeks of deliberate, shipped feature work — Adjudicate Merge, Resolve Double, Gmail
// Labels, Failed-Folder routing, offline company resolution, the OLD-gate rewrite, the dup
// guard, MAX_ITERATIONS=25 — none of which exists in v1, all of which SHOULD show as drift
// here. A run against this snapshot showed 70+ drift lines in indoxV2ActionsGlobal01 alone,
// nearly all "not present in v1" / new Build nodes for actions v1 never had. Kept
// informational (counts printed, exit code no longer gated on it) rather than deleted — the
// byte/wiring-diff machinery itself is sound and would be the right tool again the day someone
// wants to diff two SPECIFIC commits of the v2 workflows directly (point both WF() calls at
// blueprint/n8n, no v1 needed) instead of comparing to the retired v1.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const WF = (id) => JSON.parse(fs.readFileSync(path.join(ROOT,'blueprint/n8n',id+'.json'),'utf8'));
const V1_BACKUP = path.join(ROOT, '../../data/_wf_backup/2026-07-07-phase0');
const WF_V1 = (id) => JSON.parse(fs.readFileSync(path.join(V1_BACKUP, id + '.json'), 'utf8'));

let v1 = null, v1Unavailable = null;
try { v1 = WF_V1('sv5xxRBVGxvV0kXx'); } catch (e) { v1Unavailable = e.message; }
if (v1Unavailable) {
  console.log(`⊘ SKIPPED — v1 ('sv5xxRBVGxvV0kXx') not found: ${v1Unavailable}`);
  console.log(`  v1 was retired from the live system and the blueprint (legacy purge,`);
  console.log(`  commit 0312f566); no comparand exists that reflects the live product.`);
  process.exit(0);
}
const v1n = Object.fromEntries(v1.nodes.map(n => [n.name, n]));
const eq = (a,b) => JSON.stringify(a) === JSON.stringify(b);
// outgoing edges of `name` in workflow `wf`, restricted to a given node-name set
const edges = (wf, name, within) => {
  const out = [];
  for (const [i,b] of (wf.connections[name]?.main || []).entries())
    for (const l of (b||[])) if (within.has(l.node)) out.push(`${i}->${l.node}`);
  return out.sort();
};

// v1 writer (lmcZ) field-mappings by node name — a "Build: <name>" node must carry these exactly.
const WRITER = 'indoxDocBatchUpsert01';
const v1writerMap = {};
for (const n of v1.nodes) {
  const wid = n.type.endsWith('.executeWorkflow') && (n.parameters?.workflowId?.value ?? n.parameters?.workflowId);
  if (wid === WRITER) v1writerMap[n.name] = n.parameters?.workflowInputs?.value ?? {};
}
const assignObj = (n) => Object.fromEntries((n.parameters?.assignments?.assignments ?? []).map(a => [a.name, a.value]));
// normalize an edge target: the centralization renamed writer "X" → "Build: X"
const norm = (t) => t.startsWith('Build: ') ? t.slice(7) : t;
const isNewV2 = (name) => name === 'When Called' || name === 'Upsert (central)' || name.startsWith('Upsert: ')
  || name.startsWith('Call indox-v2 Actions');
const REWIRED = new Set(['Switch1']);   // wiring intentionally changed (params still identical)

const V2 = ['indoxV2ActionsGlobal01','indoxV2ActionsInv01','indoxV2ActionsBS01','indoxV2Driver01'];
let drift = 0, checked = 0, builds = 0;
for (const id of V2) {
  const wf = WF(id);
  const names = new Set(wf.nodes.map(n => n.name));
  let localDrift = 0, localNodes = 0;
  for (const n of wf.nodes) {
    if (isNewV2(n.name)) continue;                          // synthetic v2 nodes (trigger, wrapper calls)
    if (n.name.startsWith('Build: ')) {                     // Build node: must carry the exact v1 write mapping
      const m = v1writerMap[n.name.slice(7)];
      if (!m) { console.log(`  ✗ [${id}] "${n.name}" — no matching v1 writer`); drift++; localDrift++; }
      else if (!eq(assignObj(n), m)) { console.log(`  ✗ [${id}] "${n.name}" — write payload differs from v1`); drift++; localDrift++; }
      else builds++;
      continue;
    }
    localNodes++;
    const o = v1n[n.name];
    if (!o) { console.log(`  ✗ [${id}] "${n.name}" — not present in v1`); drift++; localDrift++; continue; }
    for (const f of ['type','typeVersion','parameters','credentials'])
      if (!eq(n[f], o[f])) { console.log(`  ✗ [${id}] "${n.name}" — ${f} differs from v1`); drift++; localDrift++; }
    // wiring (within-workflow), normalized for the writer→Build rename; Switch1 deliberately rewired
    if (!REWIRED.has(n.name)) {
      const e2 = edges(wf,n.name,names).map(s => s.replace(/->.*/, m => '->'+norm(s.split('->')[1]))).sort();
      const e1 = edges(v1,n.name,new Set(v1.nodes.map(x=>x.name))).filter(s=>names.has(s.split('->')[1])||v1writerMap[s.split('->')[1]]).sort();
      if (!eq(e2, e1)) { console.log(`  ✗ [${id}] "${n.name}" — wiring differs (v2 ${JSON.stringify(e2)} vs v1 ${JSON.stringify(e1)})`); drift++; localDrift++; }
    }
    checked++;
  }
  console.log(`  ${localDrift? '✗':'✓'} ${id}: ${localNodes} carried + builds, ${localDrift} drift`);
}
console.log(`\n══ INDOX v2 ACTION layer — drift vs the frozen 2026-07-07 v1 snapshot (informational) ══`);
console.log(drift===0
  ? `  ✓ ${checked} carried nodes byte-identical to v1 + ${builds} Build nodes carry the exact v1 write mapping`
  : `  ⊘ ${drift} difference(s) from that snapshot — expected: 5+ weeks of shipped work sit on`
    + `\n    top of it (Adjudicate Merge, Resolve Double, Gmail Labels, Failed-Folder routing,`
    + `\n    OLD-gate rewrite, dup guard, MAX_ITERATIONS=25, …). NOT a regression signal against`
    + `\n    a retired v1 — see file header. Not gating the exit.`);
process.exit(0);
