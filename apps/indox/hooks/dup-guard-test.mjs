#!/usr/bin/env node
//: no-regression proof for the LINE_HASH double-action guard
//
// Runs the *deployed* 'Dup Guard: Double Action' code — read live out of n8n's own database, not
// a copy pasted in here — against the states the guard has to tell apart. If someone edits that
// node in the n8n editor, this test judges the edit; there is nothing to keep in sync.
//
// THE LAW UNDER TEST (owner, 2026-08-26): a DOUBLE ACTION is the same action dispatched again
// ON AN UNCHANGED LINE with no ACTION_RESTART between. Not "dispatched again" — that refused
// legitimate work every sweep (measured 2026-08-26: 256 of 256 driver failures in 24 h, 7,216
// blocked lines over 1,180 documents, none of them a real loop, all of them a field that had
// legitimately changed underneath a decision).
//
//   ./bbox app indox dup-guard-test
// Exit 0 = every case behaves, 1 = any case does not.
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');

// DEPLOYMENT_NAME from the environment, else .env — never a hardcoded deployment, or this test
// silently probes nothing on any machine but one.
const envFile = (k) => {
  try {
    const line = fs.readFileSync(path.join(ROOT, '.env'), 'utf8')
      .split('\n').find((l) => l.startsWith(k + '='));
    return line ? line.slice(k.length + 1).trim() : '';
  } catch { return ''; }
};
const DN = process.env.DEPLOYMENT_NAME || envFile('DEPLOYMENT_NAME');
if (!DN) { console.error('FATAL: DEPLOYMENT_NAME is not set and not in .env'); process.exit(1); }
const N8N_DB = `n8n-postgres-${DN}`;
const SB_DB = `supabase-db-${DN}`;

// The project's own docker engine, same as apps/indox/hooks/fixture-sweep.py — not whatever
// DOCKER_HOST happens to point at.
const DOCKER_ENV = { ...process.env, DOCKER_HOST: 'unix://' + (process.env.BBOX_DOCKER_SOCK || '/run/bbox-docker.sock') };

const psql = (container, user, db, sql) =>
  execFileSync('docker', ['exec', '-i', container, 'psql', '-U', user, '-d', db, '-tAF|', '-c', sql],
    { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024, env: DOCKER_ENV });

// ── the code under test: whatever is LIVE in n8n right now ───────────────────────────────────
const GUARD_SQL = `select n->'parameters'->>'jsCode'
  from workflow_entity w, lateral jsonb_array_elements(w.nodes::jsonb) n
 where w.id='indoxV2Driver01' and n->>'name'='Dup Guard: Double Action'`;
const src = psql(N8N_DB, 'hacohen', 'n8n', GUARD_SQL);
if (!src || !src.trim()) {
  console.error('FATAL: could not read the live Dup Guard code from n8n');
  process.exit(1);
}
// The guard must stay a pure function of its items — no node references, or this harness would
// be testing something the real run does not do.
for (const forbidden of ["$('", '$node[', '$workflow']) {
  if (src.includes(forbidden)) {
    console.error(`FATAL: guard references ${forbidden} — it is no longer a pure item transform`);
    process.exit(1);
  }
}

function runGuard(items) {
  const $input = { all: () => items };
  // eslint-disable-next-line no-new-func
  new Function('$input', src)($input);
  return items;
}

// ── fixtures ──────────────────────────────────────────────────────────────────────────────────
const H_NOW = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';   // the line as it stands
const H_OLD = 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';   // the line as it stood before a real change
const iso = (msAgo) => new Date(Date.now() - msAgo).toISOString().replace('Z', '+00:00');
const HOUR = 3600e3;

const ent = (a, hoursAgo, h, open) =>
  ({ a, s: iso(hoursAgo * HOUR), e: open ? null : iso((hoursAgo - 0.01) * HOUR), h });

const line = (over = {}) => ({
  ID: 'zz_guard_probe', ACTION: 'select_base', STATUS: 'COMPLETED',
  __line_hash: H_NOW, ACTION_HISTORY: [], ...over,
});

const CASES = [
  { name: 'same action, SAME line hash, no restart between  -> BLOCKED (the loop)',
    item: line({ ACTION_HISTORY: [ent('mark_completed', 1, H_NOW), ent('select_base', 2, H_NOW)] }),
    expect: 'blocked' },

  { name: 'same action, line CHANGED since (a plain date edit)  -> allowed',
    item: line({ ACTION_HISTORY: [ent('mark_completed', 1, H_OLD), ent('select_base', 2, H_OLD)] }),
    expect: 'allowed' },

  { name: 'same action, SAME hash, but ACTION_RESTART after it  -> allowed',
    item: line({ ACTION_HISTORY: [ent('restart_gdoc', 1, H_NOW), ent('select_base', 2, H_NOW)] }),
    expect: 'allowed' },

  { name: 'same action, SAME hash, restart came BEFORE it  -> BLOCKED',
    item: line({ ACTION_HISTORY: [ent('select_base', 1, H_NOW), ent('restart_gdoc', 2, H_NOW)] }),
    expect: 'blocked' },

  { name: 'history row predates the rule (h = null)  -> allowed (fail-open)',
    item: line({ ACTION_HISTORY: [ent('select_base', 2, null)] }),
    expect: 'allowed' },

  { name: 'line arrived without a hash  -> allowed (fail-open)',
    item: line({ __line_hash: null, ACTION_HISTORY: [ent('select_base', 2, H_NOW)] }),
    expect: 'allowed' },

  { name: 'same hash but a DIFFERENT action  -> allowed',
    item: line({ ACTION: 'select_type', ACTION_HISTORY: [ent('select_base', 2, H_NOW)] }),
    expect: 'allowed' },

  { name: 'matching dispatch still OPEN and < 20 min old  -> in-flight skip, not an error',
    item: line({ ACTION_HISTORY: [ent('select_base', 0.1, H_NOW, true)] }),
    expect: 'inflight' },

  { name: 'matching dispatch older, a CHANGED one in between  -> BLOCKED (line came back)',
    item: line({ ACTION_HISTORY: [ent('select_base', 1, H_OLD), ent('select_base', 3, H_NOW)] }),
    expect: 'blocked' },

  { name: 'the action itself is a restart_*  -> never a double',
    item: line({ ACTION: 'restart_gdoc', ACTION_HISTORY: [ent('restart_gdoc', 2, H_NOW)] }),
    expect: 'allowed' },

  // THE REGRESSION THE OWNER REPORTED, both halves.
  { name: 'REGRESSION: completion flag set + dispatched, but line CHANGED  -> allowed (old signal B blocked this)',
    item: line({ BASE_SELECTION_COMPLETED: 'true', STATUS: 'COMPLETED',
                 ACTION_HISTORY: [ent('select_base', 2, H_OLD)] }),
    expect: 'allowed' },

  { name: 'REGRESSION: *_COMPLETED cleared by hand, so the line changed  -> allowed',
    item: line({ ACTION: 'extract_base_doc', BASE_EXTRACTION_COMPLETED: '',
                 ACTION_HISTORY: [ent('extract_base_doc', 2, H_OLD)] }),
    expect: 'allowed' },
];

// ── live-data cases ───────────────────────────────────────────────────────────────────────────
// Real documents, real dispatch rows, and — this is the point — the REAL ACTION_HISTORY, built by
// the same lateral query indoxV2Driver01 :: 'Get Action History' runs, with the same LIMIT 16 and
// the same {a,s,e,h} shape. So this is not a hand-made approximation of the driver's input: it IS
// the driver's input. The only thing supplied here is which action decide would propose, taken
// from the document's own newest dispatch.
//
// STATUS is forced to COMPLETED so the in-flight escape hatch cannot mask the verdict — most live
// rows sit IN_PROGRESS, which is deliberately skipped (concurrency is the lock's domain), and that
// would make both cases pass for the wrong reason.
const HISTORY_SQL = (id) => `
select coalesce(h.hist, '[]'::jsonb)
  from (select '${id}'::text as "ID") i
  left join lateral (
    select jsonb_agg(jsonb_build_object(
             'a', e."ACTION", 's', e."STARTED_AT", 'e', e."ENDED_AT", 'h', e."LINE_HASH")
             order by e."STARTED_AT" desc) as hist
      from (select x."ACTION", x."STARTED_AT", x."ENDED_AT", x."LINE_HASH"
              from public.indox_action_execution_log x
             where x."ID" = i."ID" order by x."STARTED_AT" desc limit 16) e) h on true`;

function liveCases() {
  const out = [];
  const q = (pred, label, expect) => {
    const sql = `select l."ID", l."ACTION", public.indox_line_hash(d.*)
                   from public.indox_action_execution_log l
                   join public.incoming_documents d on d."ID" = l."ID"
                  where l."LINE_HASH" is not null and ${pred}
                    and not exists (select 1 from public.indox_action_execution_log r
                                     where r."ID" = l."ID" and r."ACTION" like 'restart%'
                                       and r."STARTED_AT" > l."STARTED_AT")
                    -- The dispatch must be SETTLED, or the in-flight escape hatch answers first and
                    -- the case proves nothing: an OPEN bracket is a live race, which the guard skips
                    -- on purpose (concurrency is the lock's job). Closed is the whole requirement --
                    -- the 20-minute race window is only consulted for an OPEN bracket, so demanding
                    -- age here as well was over-constraint that made this case unfindable.
                    and l."ENDED_AT" is not null
                    and not exists (select 1 from public.indox_action_execution_log o
                                     where o."ID" = l."ID" and o."ACTION" = l."ACTION"
                                       and o."ENDED_AT" is null)
                  order by l."STARTED_AT" desc limit 1`;
    const row = psql(SB_DB, 'postgres', 'postgres', sql).trim();
    if (!row) { console.log(`  (no live row available for: ${label})`); return; }
    const [id, action, nowHash] = row.split('|');
    const history = JSON.parse(psql(SB_DB, 'postgres', 'postgres', HISTORY_SQL(id)).trim());
    out.push({
      name: `LIVE ${label} — ${id} / ${action} (${history.length} real history rows)`,
      item: { ID: id, ACTION: action, STATUS: 'COMPLETED', __line_hash: nowHash,
              ACTION_HISTORY: history },
      expect,
    });
  };
  q(`l."LINE_HASH" = public.indox_line_hash(d.*)`, 'dispatch whose line has NOT moved since', 'blocked');
  q(`l."LINE_HASH" <> public.indox_line_hash(d.*)`, 'dispatch whose line HAS moved since', 'allowed');
  return out;
}

// ── run ───────────────────────────────────────────────────────────────────────────────────────
const verdict = (j) => (j.__inflight_skip ? 'inflight' : (j.__dup_in_log ? 'blocked' : 'allowed'));

let pass = 0, fail = 0;
const all = [...CASES, ...liveCases()];
for (const c of all) {
  const got = verdict(runGuard([{ json: c.item }])[0].json);
  const ok = got === c.expect;
  ok ? pass++ : fail++;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${c.name}` + (ok ? '' : `   [expected ${c.expect}, got ${got}]`));
}
console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
