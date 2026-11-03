import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : Raphael — collector watch
// Nodes   : 2  |  Connections: 1
//
// Schedule (every 15 min)
//    -> Watch the collector
// </workflow-map>
//
// The owner's instruction of 2026-10-09: "כל מקביל כבר מתפקד כמאסף ראשי אז אפשר שהאוטומציות של רפאל
// ישתמשו במה שאפשר שם" — any-concurrency IS the collector, so Raphael's automations read it instead of
// re-scanning the world. This workflow is the first one that does, and it is also the dead-man's switch
// the security reference asks for (ai/context/dgo-security-session.md): a source that stops answering,
// or a source whose spans go quiet, is the alarm.
//
// Measured shapes (2026-10-09):
//   GET http://any-concurrency:8080/api/sources
//     -> {"n8n":{"enabled":true,"ok":true,"last_ok":1791543467578,"error":null,"config":{…}}, "traefik":…, "docker":…, "webhook":…}
//   GET http://any-concurrency:8080/api/spans?limit=N
//     -> [{"id":"n8n:1","src":"n8n","svc":"Raphael — machine scan","svcid":"raphaelMachine00001","label":"#1 trigger",
//          "status":"success","s":…,"e":…,"d":7977,"meta":{…}}]   (newest first)
// Raphael's own runs appear there as spans of src "n8n", which is how the office sees its guardian work.
//
// Credential-free on purpose (internal service URLs only), like Raphael's other scans.
@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Watch every 15 min":{"main":[[{"node":"Watch the collector","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"id":"AppTagRaphael0001","name":"app:raphael"},{"id":"RoleTagRaphaelInfra","name":"role:infra"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: null,
    /*__n8n__*/ staticData: null,
    id: 'raphaelCollector00001',
    name: 'Raphael — collector watch',
    active: true,
    isArchived: false,
    tags: ['app:raphael', 'role:infra'],
    settings: { errorWorkflow: 'errorHandler01', executionOrder: 'v1' },
})
export class RaphaelCollectorWatchWorkflow {
    @node({
        id: 'raphael-collector-sched-01',
        name: 'Watch every 15 min',
        type: 'n8n-nodes-base.scheduleTrigger',
        version: 1.2,
        position: [0, 0],
    })
    Schedule = {
        rule: { interval: [{ field: 'minutes', minutesInterval: 15 }] },
    };

    @node({
        id: 'raphael-collector-01',
        name: 'Watch the collector',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [220, 0],
    })
    Watch = {
        jsCode: `const COLL = 'http://any-concurrency:8080';
// A PROOF run may point the alarms somewhere else. Running this node by hand (bbox n8n execute)
// is how its own behaviour is verified — and its side effect is to write REAL alarms: measured
// 2026-10-10, a proof run aimed at a dead collector wrote a notice and a wake request into the
// owner's list, with the proof's own port in the text (ECONNREFUSED 172.18.0.30:9). A run whose
// input carries a "notify" url writes them there instead; the schedule passes nothing, and behaves
// as before. The proof still returns its sent list, so what it proved stays visible.
let PROOF_NOTIFY = '';
try { PROOF_NOTIFY = ($input.first() && $input.first().json && $input.first().json.notify) || ''; } catch (e) {}
const NOTIFY = PROOF_NOTIFY || 'http://notifications:8977/api/notifications';
// ONE IS SAID AS ONE (G86) — see the note in raphaelMachine00001; a Code node cannot import.
const num = n => Number(n).toLocaleString('he-IL');
const one = (n, single, many) => (Number(n) === 1 ? single : num(n) + ' ' + many);
// MEASURED, then tuned: most sources here are LOG sources bound to a container (drive-hp,
// n8n-webhook-hp), and their last_ok is the last log line collected - a quiet container looks stale
// without anything being wrong. So a day of silence is the signal (worth a look), and ok===false -
// the collector failing to read at all - is the alarm. Crying wolf is how a dead-man's switch gets
// switched off.
const SOURCE_STALE_S = 86400;  // a source that has said nothing for a day
const SPAN_QUIET_S = 86400;    // a source whose spans went quiet for a day
const REPEAT_MS = 30 * 60 * 1000;
//: Sources that write a span when a TASK runs, not on a timer. An idle one is not a fault: browser42
//: posts on task start/end (apps/browser42/group-manager.py, reaper.py), so an office that has not
//: driven the browser for a day looks "quiet" forever while the browser is healthy and simply unused —
//: measured 2026-10-10, 26 hours of silence from a healthy browser, and the alarm fired on every tick.
//: Its real signals are the container check (raphaelContainers00001) and the task's own outcome.
const DEMAND_SOURCES = ['browser42'];

const get = async (url) => {
  try { return { ok: true, body: await this.helpers.httpRequest({ method: 'GET', url, json: true, timeout: 20000 }) }; }
  catch (e) { return { ok: false, error: String(e && e.message ? e.message : e) }; }
};

const nowS = Math.floor(Date.now() / 1000);
const problems = [];
const summary = { sources: 0, enabled: 0, stale: [], quiet: [], newest_span_s: null };

// 1. The collector's own sources: enabled and ok, with a fresh last_ok.
const sources = await get(COLL + '/api/sources');
if (!sources.ok) {
  problems.push({ id: 'collector-unreachable', level: 'error',
    title: 'הדופק: המאסף (כל מקביל) לא עונה',
    body: 'any-concurrency לא ענה על /api/sources: ' + sources.error });
} else {
  const rows = sources.body || {};
  summary.sources = Object.keys(rows).length;
  for (const [name, s] of Object.entries(rows)) {
    if (!s || s.enabled === false) continue;
    summary.enabled += 1;
    // A PUSH door is not a poller, and silence in it is the ABSENCE OF A PUSHER, not a fault: apps
    // post when they have something to say (browser42 on task start/end — see DEMAND_SOURCES below,
    // which already makes that call for its spans), so a null last_ok in an office that has not
    // driven the browser is the normal state of a healthy door. The lane says which it is (it
    // carries mode: 'push', any-concurrency/app.py) and answers for itself: a collector that cannot
    // be read is branch 1 above, and a door that stopped accepting answers the app that pushes.
    // Measured 2026-10-10: this loop raised the silent-source error for webhook on every tick.
    if (s.mode === 'push') continue;
    const ageS = s.last_ok ? nowS - Math.floor(s.last_ok / 1000) : null;
    if (s.ok === false || (ageS !== null && ageS > SOURCE_STALE_S)) {
      summary.stale.push(name);
      problems.push({ id: 'collector-source-' + name, level: s.ok === false ? 'error' : 'warn',
        title: 'הדופק: מקור במאסף שתק — ' + name,
        body: 'ok=' + String(s.ok) + (ageS === null ? ', מעולם לא הצליח' : ', עדכון מוצלח אחרון לפני ' + one(ageS, 'שנייה אחת', 'שניות')) +
              (s.error ? ' — ' + String(s.error).slice(0, 200) : '') });
    }
  }
}

// 2. The spans themselves: what moved, and what stopped moving. Raphael's own runs are spans here too,
//    so "the guardian works" is measurable rather than assumed.
const spans = await get(COLL + '/api/spans?limit=400');
if (spans.ok) {
  const list = Array.isArray(spans.body) ? spans.body : [];
  const newestPerSource = {};
  for (const span of list) {
    const src = span.src || '?';
    const s = Math.floor((span.s || 0) / 1000);
    if (!newestPerSource[src] || s > newestPerSource[src]) newestPerSource[src] = s;
  }
  if (Object.keys(newestPerSource).length) {
    summary.newest_span_s = Math.max(...Object.values(newestPerSource));
  }
  for (const [src, s] of Object.entries(newestPerSource)) {
    const quietS = nowS - s;
    if (DEMAND_SOURCES.includes(src)) continue;   // silent because nobody used it, not because it broke
    if (quietS > SPAN_QUIET_S) {
      summary.quiet.push(src + ':' + quietS);
      problems.push({ id: 'collector-quiet-' + src, level: 'warn',
        title: 'הדופק: ' + src + ' לא דיווח למאסף',
        body: 'הזרזיף האחרון של ' + src + ' נראה לפני ' + one(quietS, 'שנייה אחת', 'שניות') + ' (יותר מ-' + Math.round(SPAN_QUIET_S / 3600) + ' שעות).' });
    }
  }
}

// 3. Say each problem once per window, and CLOSE the ones that are gone.
//
// The closing half is why this node reads the notice list even when it has nothing to say. Until it
// existed, a problem this watch raised stayed UNREAD for ever after it was fixed: measured
// 2026-10-10 — the webhook lane was repaired at 19:35 and its 17:45 notice was still the first
// unread row, so the owner was handed an alarm about a lane that had been healthy for two hours
// (and asked about it twice). An alarm is closed by the same observer that opened it.
//
// Note the created_at handling: it arrives as an ISO string, so Number() gave NaN and this window
// never matched anything — the same bug the office pulse carried until 2026-10-10. Date.parse is
// what reads it.
const posted = await get(NOTIFY + '?limit=60');
const noticeRows = (posted.ok && Array.isArray(posted.body && posted.body.notifications))
  ? posted.body.notifications : [];
const recent = new Set();
const cutoff = Date.now() / 1000 - REPEAT_MS / 1000;
for (const row of noticeRows) {
  const at = Date.parse(row && row.created_at ? row.created_at : '') / 1000;
  if (at >= cutoff && row.source_id) recent.add(row.source_id);
}
for (const problem of problems) {
  if (recent.has(problem.id) || recent.has('wake-' + problem.id)) continue;
  try {
    await this.helpers.httpRequest({ method: 'POST', url: NOTIFY, json: true, timeout: 15000,
      body: { source: 'raphael', source_id: problem.id, title: problem.title, body: problem.body,
              // AN OFFICE-RELATIVE PATH, not an address (DGO-531). This used to be an absolute
              // address with the macOS engine's edge port written as a constant, so on this office —
              // whose console does not stand at that address — «פתח במקור» opened a tab
              // that did not load. The notifications screen resolves a relative path against the office
              // it is shown in (its own opens(): same origin, path "/", hash #/m/… — then it opens
              // INSIDE the office and not in a new tab), so this is right wherever the office stands.
              level: problem.level, link: '/#/m/any-concurrency' } });
  } catch (e) { /* the finding is still returned below */ }
  try {
    await this.helpers.httpRequest({ method: 'POST', url: NOTIFY, json: true, timeout: 15000,
      body: { source: 'raphael', source_id: 'wake-' + problem.id,
              title: 'בקשת השכמה מהמאסף: ' + problem.title, body: problem.body, level: 'warn' } });
  } catch (e) { /* a failed wake request never hides the finding */ }
}
// (b) The problems this run does NOT see: a notice of mine that is still unread is closed. Only ids
// this watch OWNS are touched — the collector- family and its wake- copies (a wake request for a
// problem that is over is the one that asks the owner the same question a second time), never
// another watcher's notices — and a live problem is never closed by a run that sees it.
const live = new Set(problems.map((p) => p.id));
const cleared = [];
for (const row of noticeRows) {
  const sid = String((row && row.source_id) || '');
  const own = sid.startsWith('collector-') ? sid
            : (sid.startsWith('wake-collector-') ? sid.slice('wake-'.length) : '');
  if (!own || !row.id || row.is_read) continue;
  if (live.has(own)) continue;
  try {
    await this.helpers.httpRequest({ method: 'POST', url: NOTIFY + '/' + row.id + '/read',
                                     json: true, timeout: 10000 });
    cleared.push(sid);
  } catch (e) { /* a notice left open is not a failure of the watch */ }
}

return [{ json: { watch: 'collector', at: new Date().toISOString(), problems: problems.length,
                  sent: problems.map((p) => p.id), cleared, ...summary } }];
`,
    };

    @links()
    defineRouting() {
        this.Schedule.out(0).to(this.Watch.in(0));
    }
}
