// Prove public.indox_priority_signature(row) == the signature of what 'Map Request' actually
// sends, over REAL rows. The SQL function is the only definition used in production; this file
// is the independent check that it matches the shipped JS, so the two can never silently diverge.
//
// The JS side is NOT hand-copied from the blueprint. It is read out of the LIVE workflow's
// 'Map Request' node and evaluated, so if someone edits the mapping in n8n and forgets the
// migration, this fails instead of quietly re-sending (or never re-sending) client documents.
//
//   node scripts/ops/verify_priority_signature.mjs [rowLimit]
// exit 0 = every row agreed. exit 1 = mismatch (prints the offending field and both values).

import crypto from 'crypto';
import fs from 'fs';
import os from 'os';
import path from 'path';
import { execSync } from 'child_process';

const LIMIT = parseInt(process.argv[2] || '400', 10);
const sh = (c) => execSync(c, { encoding: 'utf8', maxBuffer: 256 * 1024 * 1024 });

// SQL goes to a file and is piped to psql's stdin. Passing it inline as `psql -tAc "..."` does
// not survive the trip: WSL rewrites bare /tmp paths into Windows ones and eats quoting, so the
// query arrives mangled or the file is looked for on the wrong filesystem entirely.
// `docker exec` also needs -i or it discards stdin without saying so.
const psql = (container, user, db, sql) => {
  const win = path.join(os.tmpdir(), `psig_${process.pid}.sql`);
  fs.writeFileSync(win, sql, 'utf8');
  const wsl = '/mnt/' + win[0].toLowerCase() + win.slice(2).replace(/\\/g, '/');
  const inner = `cat '${wsl}' | docker -H unix:///run/bbox-docker.sock exec -i ${container} ` +
                `psql -U ${user}${db ? ' -d ' + db : ''} -tAf -`;
  try { return sh(`wsl -d Ubuntu -- bash -c ${JSON.stringify(inner)}`); }
  finally { try { fs.unlinkSync(win); } catch { /* best effort */ } }
};

// ---------------------------------------------------------------- 0. copy-drift gate
// The function body exists twice on purpose: the migration advances an EXISTING database, the
// fixture schema is what a FRESH one gets. Two copies drift -- that is exactly how six columns
// went missing before (issues/schema-drift-fixture-vs-live.md). Diff them here so the drift
// surfaces as a failing check rather than as a driver that errors on a newly built machine.
const grabFn = (file) => {
  const m = fs.readFileSync(file, 'utf8')
    .match(/create or replace function public\.indox_priority_signature[\s\S]*?\$fn\$;/);
  return m ? m[0] : null;
};
const fromMigration = grabFn('scripts/ops/migrations/2026-08-22_priority_sync_signature.sql');
const fromFixture = grabFn('apps/indox/blueprint/fixtures/schema.sql');
if (!fromMigration || !fromFixture) {
  console.error('FATAL: indox_priority_signature missing from the migration or the fixture schema');
  process.exit(1);
}
if (fromMigration !== fromFixture) {
  console.error('FATAL: the migration and fixture copies of indox_priority_signature have DRIFTED.');
  console.error('       A fresh database would fingerprint differently from this one.');
  process.exit(1);
}
console.log('  copy-drift gate: migration and fixture definitions are identical');

// ---------------------------------------------------------------- 1. the LIVE mapping
const nodes = JSON.parse(psql('n8n-postgres-shlomo-laptop', 'hacohen', 'n8n',
  "SELECT nodes::text FROM workflow_entity WHERE id='indoxV2ActionsShip01'"));
const mapNode = nodes.find((n) => n.name === 'Map Request');
if (!mapNode) { console.error('FATAL: no Map Request node in the live indoxV2ActionsShip01'); process.exit(1); }

const assigns = mapNode.parameters.assignments.assignments;
console.log(`  live 'Map Request' fields: ${assigns.map((a) => a.name).join(', ')}`);

// Every field except the per-run execution id contributes to the fingerprint.
const SIGNED = assigns.filter((a) => a.name !== 'N8N_EXEID');
if (SIGNED.length !== assigns.length - 1) {
  console.error('FATAL: expected exactly one N8N_EXEID field to exclude'); process.exit(1);
}

// Evaluate an n8n "={{ expr }}" assignment against a row, honouring the declared type the way a
// Set node does (number stays a number, string is stringified).
function evalAssign(a, row) {
  const expr = String(a.value).replace(/^=/, '').replace(/^\{\{/, '').replace(/\}\}$/, '').trim();
  const fn = new Function('$json', '$execution', `return (${expr});`);
  const v = fn(row, { id: 'verify' });
  return a.type === 'number' ? Number(v) : (a.type === 'string' ? String(v) : v);
}

// Canonical form must match the SQL function byte for byte: values joined by the ASCII unit
// separator. JSON was the first attempt and failed on all 559 rows -- Postgres prints jsonb::text
// with a space after every comma, JSON.stringify does not. Identical values, different bytes.
const US = String.fromCharCode(31); // == SQL chr(31)
const canonical = (row) => SIGNED.map((a) => String(evalAssign(a, row))).join(US);
const jsSignature = (row) => crypto.createHash('md5').update(canonical(row)).digest('hex');

// ---------------------------------------------------------------- 2. real rows + SQL signature
// Rows are chosen to stress the mapping, not to flatter it: nulls, blanks, odd dates and amounts
// alongside ordinary completed documents.
const COLS = ['ID', 'SELECTED_COMPANY_ID', 'SELECTED_DOC_DATE', 'AI_DOC_ID', 'SELECTED_DOC_ID',
  'SELECTED_DOC_AMOUNT', 'SELECTED_DOC_SHIPMENT_ID', 'SELECTED_DOC_ORDER_ID', 'LINK', 'TYPE',
  'SOURCE_TYPE', 'FROM_OFFICE', 'SELECTION_CERTAINTY'];

const sql = `
WITH picked AS (
  (SELECT * FROM incoming_documents WHERE "STATUS"='COMPLETED' ORDER BY updated_at DESC LIMIT ${LIMIT})
  UNION
  (SELECT * FROM incoming_documents WHERE "SELECTED_DOC_DATE" IS NULL LIMIT 40)
  UNION
  (SELECT * FROM incoming_documents WHERE "SELECTED_COMPANY_ID" IS NULL LIMIT 40)
  UNION
  (SELECT * FROM incoming_documents WHERE "SELECTED_DOC_AMOUNT" ~ '[^0-9.]' LIMIT 40)
  UNION
  (SELECT * FROM incoming_documents WHERE length(coalesce("SELECTED_DOC_DATE",'')) BETWEEN 1 AND 9 LIMIT 40)
  UNION
  (SELECT * FROM incoming_documents WHERE "FROM_OFFICE" IS NOT NULL LIMIT 40)
)
SELECT json_agg(json_build_object(
  'sig', public.indox_priority_signature(p.*),
  ${COLS.map((c) => `'${c}', p."${c}"`).join(',\n  ')}
))::text FROM picked p;`;

const rows = JSON.parse(psql('supabase-db-shlomo-laptop', 'postgres', null, sql).trim() || '[]');
console.log(`  rows under test: ${rows.length}`);

// ---------------------------------------------------------------- 3. compare
let bad = 0;
for (const r of rows) {
  const js = jsSignature(r);
  if (js === r.sig) continue;
  if (++bad <= 5) {
    console.log(`\n  MISMATCH id=${r.ID}\n    sql=${r.sig}\n    js =${js}`);
    for (const a of SIGNED) console.log(`      ${a.name.padEnd(20)} js=${JSON.stringify(evalAssign(a, r))}`);
  }
}
console.log(`\n  ===== ${rows.length - bad}/${rows.length} agree, ${bad} mismatched =====`);
process.exit(bad ? 1 : 0);
