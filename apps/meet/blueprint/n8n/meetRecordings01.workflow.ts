import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : Meet — every recording becomes a Plane item with its full transcripts
// Nodes   : 8  |  Connections: 7
//
// A recording is ready (webhook: meet-start runs it, one run at a time: the moment a recording ends,
// each minute for a quarter hour while it has no item yet, and every five minutes)
//   ·   Every 15 minutes (the safety net: does nothing while meet-start runs it)
//    -> Plan the run
//      -> Route
//        [submit]     -> Fetch the audio -> Send to the transcriber -> Remember the job
//        [write]      -> Write the Plane item   (both transcripts, a silent or given-up recording,
//                                                or the Whisper transcript put into an older item)
// </workflow-map>
//
// WHY (DGO-834, the owner 2026-10-21): «every time something it saved, so it would create a plain
// ticket with video … and tag it … and then also give the full transcription there … everything
// ready on our plane». Declared with the app it serves, like INDOX's automations (app.json
// `blueprints.n8n`), and imported by `./bbox n8n push meet`.
//
// TWO TRANSCRIPTS, NO TRANSLATION (DGO-955, the owner 2026-10-22, MEET-13: «לא צריך לתרגם פגישות …
// פשוט צריך לתמלל בשתי השפות … אנחנו רוצים בשפה שהדברים נאמרו»). Every recording is transcribed
// twice by the office's `speech` capability: ivrit.ai's Whisper for the Hebrew, and OpenAI's own
// Whisper for the English, each stretch in the language it was spoken. Both go on the item.
//
// WHAT IT CALLS, all inside the office:
//   · http://meet-start:8001/api/recordings — the meet app's machines' door (it answers n8n's
//     containers only): every finished recording, its audio (jibri/finalize.sh writes it), who
//     started it, its console link, and where this office's Plane answers (hooks/prepare derives it);
//   · http://apitools-asr:8987 — the office's `speech` capability, both models;
//   · Plane's API through that address (the link door signs the call in: no key here), project MEET
//     (apps/project-pln/plans/meetings.yaml), one item per recording keyed by its session and file;
//   · http://notifications:8977 — the owner hears about each item, and about each failure.
//
// A ONE-HOUR MEETING TAKES MORE THAN AN HOUR TO TRANSCRIBE on vps1's one core, so nothing here waits:
// a run sends new audio (two jobs at the transcriber at most, and none while it is down or full),
// collects finished transcripts and writes their items; the jobs in between live in this workflow's
// static data. ONE RECORDING NEVER HOLDS UP THE OTHERS: every node past the plan continues on a
// failed item, a node that fails says so (the notice centre, at most hourly) instead of throwing, and
// an item left unwritten is written by a later run. Plane is the record: a recording whose item is
// there is never sent again, even if the static data is lost. A recording that ended before this
// workflow's first run and has no audio is left alone (finalize.sh did not exist then).
@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Every 15 minutes":{"main":[[{"node":"Plan the run","type":"main","index":0}]]},"A recording is ready":{"main":[[{"node":"Plan the run","type":"main","index":0}]]},"Plan the run":{"main":[[{"node":"Route","type":"main","index":0}]]},"Route":{"main":[[{"node":"Fetch the audio","type":"main","index":0}],[{"node":"Write the Plane item","type":"main","index":0}]]},"Fetch the audio":{"main":[[{"node":"Send to the transcriber","type":"main","index":0}]]},"Send to the transcriber":{"main":[[{"node":"Remember the job","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"id":"AppTagMeet00001","name":"app:meet"},{"id":"RoleTagMeetRec01","name":"role:recordings"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: null,
    /*__n8n__*/ staticData: null,
    id: 'meetRecordings01',
    name: 'Meet — recordings to Plane, with their transcripts',
    active: true,
    isArchived: false,
    tags: ['app:meet', 'role:recordings'],
    settings: { errorWorkflow: 'errorHandler01', executionOrder: 'v1' },
})
export class MeetRecordingsWorkflow {
    @node({
        id: 'meet-rec-clock-01',
        name: 'Every 15 minutes',
        type: 'n8n-nodes-base.scheduleTrigger',
        version: 1.2,
        position: [0, 300],
    })
    Clock = {
        rule: {
            interval: [{ field: 'minutes', minutesInterval: 15 }],
        },
    };

    // DGO-907 (the owner: «triggred on new rec»): meet-start runs this, one run at a time: the moment a
    // recording ends, once a minute in the quarter hour after (a short meeting's transcript is made by
    // then), and every five minutes. No data is taken from the call: it only says «look now». It is
    // answered when the run ENDS (empty), and meet-start waits for that before its next call; the
    // clock above does nothing while meet-start's call is going or its last one worked lately (the
    // plan reads both from meet-start), so two runs seldom write one recording. The edge routes
    // /webhook/* to the public too: only the office's own network may call this one (n8n trusts one
    // proxy hop, N8N_PROXY_HOPS, so a caller through the edge is its public address and is refused).
    @node({
        id: 'meet-rec-hook-01',
        webhookId: '6d1f3c2a-8e4b-4f7a-9c51-2b7e0d4a9f11',
        name: 'A recording is ready',
        type: 'n8n-nodes-base.webhook',
        version: 2.1,
        position: [0, 480],
    })
    Ready = {
        httpMethod: 'POST',
        path: 'meet-recordings',
        responseMode: 'lastNode',
        responseData: 'noData',
        options: { ipWhitelist: '10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,127.0.0.1,::1' },
    };

    @node({
        id: 'meet-rec-plan-01',
        name: 'Plan the run',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [240, 300],
    })
    Plan = {
        jsCode: `// One run of the recordings' pipeline: what to send, what came back, what to write.
// Items out, by route: 'submit' sends a recording's audio to the transcriber for one of its two
// passes; 'write' writes its Plane item (kind 'speech' or 'silent'), or puts the Whisper transcript
// into an item written before there were two (touch 'whisper').
const helpers = this.helpers;
// Meet's recordings and the transcriber, by the addresses their apps declare. In an office that runs
// neither (the HP, DGO-945), the push writes the linked offices' doors here instead
// (scripts/link-endpoints-apply): vps1's «recordings», the Dell's «speech».
const MEET = 'http://meet-start:8001';
const ASR = 'http://apitools-asr:8987';
let PLANE = '';                    // Plane: set below, once meet-start has said how it is reached
const WS = 'bina';                 // the office's Plane workspace (apps/project-pln/bootstrap.yaml)
const SOURCE = 'meet-recording';   // with the recording's key, what its Plane item is found by
const IN_FLIGHT = 2;               // jobs at the transcriber at once: one core works, the rest wait here
const GIVE_UP_AFTER = 3;           // attempts per recording and pass before that pass is given up
const NO_AUDIO_AFTER_S = 30 * 60;  // a recording still without its audio this long after it ended
// A RECORDING IS NEVER GIVEN UP FOR GOOD (the owner, 2026-10-22: «we must get the transcription for
// this meet and any other meet will ever do»). One whose passes failed is written saying so (its
// item is not "finished": FAILED_MARK), and every RETRY_AFTER_MS it is sent again from the start,
// RETRY_ROUNDS times in all; when a round succeeds, its item is written over whole. One that lost a
// single pass is written with the other, and its rounds send that pass alone (HE_LOST, EN_LOST).
const RETRY_AFTER_MS = 6 * 3600 * 1000;
const RETRY_ROUNDS = 8;
const FAILED_MARK = 'התמלול לא הושלם';
// EVERY RECORDING IS TRANSCRIBED TWICE, and nothing is translated (DGO-955, the owner 2026-10-22:
// «פשוט צריך לתמלל בשתי השפות … בשפה שהדברים נאמרו»): ivrit.ai's Whisper for the Hebrew, and
// OpenAI's own Whisper for the English — each stretch in the language it was spoken (\`auto\`), so a
// meeting held in English, or in both, has its words as they were said.
const PASSES = {
  he: { model: 'ivrit', language: 'he' },
  en: { model: 'whisper', language: 'auto' },
};
const EN_TITLE = 'Transcript (Whisper';   // how the writer's second section begins
// An item this writer finished carries MARK in its footer (every item it writes does, silent and
// failed ones too) and no PENDING_EN: the line an item written before its Whisper pass came back has
const MARK = 'ivrit.ai + Whisper';
const PENDING_EN = '(the Whisper transcript is still being made';
// …and the line it writes for one pass given up: that pass alone is tried again in a later round, and
// its transcript put in place of the line (touch 'hebrew' / 'whisper'), the rest of the item kept
const HE_LOST = 'התמלול בעברית נכשל';
const EN_LOST = 'The Whisper transcript failed';
const HE_TITLE = '<h2>תמלול בעברית (ivrit.ai)</h2>';   // (the line counts right under it, as the writer reads it)

// Only read until the run knows it has work (ONE RUN AT A TIME below): n8n saves this static data at
// the end of a run that wrote to it, and a run that only stepped aside must not save its old copy over
// the one the run it stepped aside for has just saved.
const state = $getWorkflowStaticData('global');

const why = (e) => String((e && (e.description || e.message)) || e).slice(0, 300);
// A request's HTTP status. In n8n's task runner the error reaches this code as its message only
// («Request failed with status code 404», measured on vps1 2026-10-21), so that is read too.
const statusOf = (e) => {
  const n = Number((e && (e.httpCode || (e.response && e.response.status) || e.statusCode || e.status)) || 0);
  const m = /status code (\\d{3})/.exec(String((e && (e.message || e.description)) || e));
  return n || (m ? Number(m[1]) : 0);
};
const rows = (x) => (Array.isArray(x) ? x : (x && x.results) || []);
const notify = (level, title, body) => helpers.httpRequest({
  method: 'POST', url: 'http://notifications:8977/api/notifications', json: true, timeout: 15000,
  body: { source: 'meet', source_id: 'recordings', level, title, body, link: '/#/m/meet' },
}).catch(() => {});

// meet-start down or answering nonsense: said on the first run and then every twelfth (with
// meet-start down only the clock runs this: every three hours), and the run ends quietly (a thrown
// error here would reach errorHandler01 on every run).
let listing;
try {
  listing = await helpers.httpRequest({ method: 'GET', url: MEET + '/api/recordings', json: true, timeout: 30000 });
  if (!listing || !Array.isArray(listing.recordings)) {
    throw new Error('meet-start answered without a list of recordings: ' + JSON.stringify(listing).slice(0, 200));
  }
} catch (e) {
  state.listFails = (state.listFails || 0) + 1;
  if (state.listFails === 1 || state.listFails % 12 === 0) {
    await notify('error', 'פגישות: רשימת ההקלטות לא נקראה', 'ניסיון ' + state.listFails + ' · ' + why(e));
  }
  return [];
}
// ONE RUN AT A TIME. meet-start runs this through the webhook and waits for each run to end; its
// door says whether a call is going (and since when) and when one last worked. A run of the clock
// (the safety net) meanwhile does nothing: two runs at once would upload and write one recording
// twice. A call going for twenty minutes is one that hangs, and the clock works.
const viaHook = typeof $input !== 'undefined' && !!(($input.first() || {}).json || {}).webhookUrl;
const hook = listing.hook || null;
const nowS = Date.now() / 1000;
if (!viaHook && hook && ((hook.busy && nowS - (Number(hook.busy_since) || 0) < 20 * 60)
    || nowS - (Number(hook.ok_at) || 0) < 10 * 60)) {
  try { $execution.customData.set('outline', 'meet-start מריץ'); } catch (e) { /* as below */ }
  return [];
}
if (state.listFails) state.listFails = 0;
state.jobs = state.jobs || {};       // key -> { he: { id, at }, en: { id, at } }
state.done = state.done || {};       // key -> { issue, at, rev }
state.tries = state.tries || {};     // key|pass -> attempts that failed
state.failed = state.failed || {};   // key -> why it was given up (its item still has to be written)
state.planeFails = state.planeFails || {};   // key -> writes that failed (the writer's)
// what the translation kept here before DGO-955 took it out
delete state.english; delete state.needsEnglish; delete state.translator;
// The first run's time. A recording older than it that has no audio is one this workflow never had
// a part in (it ended before finalize.sh existed): it is left alone, not filed as a failure.
state.since = state.since || Math.floor(Date.now() / 1000);
const recs = listing.recordings.filter((r) => r.done);   // the others are still recording (newest first)
// Plane through meet-start's relay when its door has one (the link signs the call in: DGO-945, and
// the only way an office that runs this workflow for another reaches it), else at the address
// meet-start names (a meet-start from before the relay). The writer is handed the same.
PLANE = listing.plane_relay ? MEET + '/api/plane' : String(listing.plane_api || '');
const base = { plane_api: listing.plane_api, console: listing.console, plane: PLANE };
const out = [];
// Nowhere to write (no linked office publishes Plane: apps/meet/hooks/prepare): nothing is
// transcribed for an item that cannot be written. Said on the first run and then daily.
if (!base.plane_api) {
  state.noPlane = (state.noPlane || 0) + 1;
  if (state.noPlane === 1 || state.noPlane % 288 === 0) {
    await notify('warning', 'פגישות: אין לאן לכתוב את ההקלטות', 'אף משרד מקושר לא מפרסם Plane (MEET_PLANE_API_URL ריק); ההקלטות נשמרות, ולא נפתחים להן פריטים.');
  }
  return [];
}
state.noPlane = 0;

// a recording's jobs, one per pass (a job kept before DGO-955 is its Hebrew pass); a recording that
// is gone (deleted from the recorder's volume) is forgotten
const jobsOf = (key) => {
  const j = state.jobs[key];
  if (!j) return (state.jobs[key] = {});
  return j.id ? (state.jobs[key] = { he: j }) : j;
};
const present = new Set(recs.map((r) => r.session + '/' + r.file));
for (const k of Object.keys(state.jobs)) if (!present.has(k)) delete state.jobs[k];
const tries = (key, p) => state.tries[key + '|' + p] || 0;
const lost = (key, p) => tries(key, p) >= GIVE_UP_AFTER;
// an item written before there were two transcripts, or before its Whisper pass came back, gets the
// Whisper transcript put into it (touch 'whisper')
const WRITER = 5;
// a recording written as failed, due another round: sent again from the start (its attempts cleared);
// one that failed one pass only (failed 'he' or 'en') has that pass sent again, and its transcript
// put into the item in place of the line that said it failed (the other pass, and the rest, kept)
state.rounds = state.rounds || {};   // key -> rounds already tried (the first is 1)
for (const rec of recs) {
  const key = rec.session + '/' + rec.file;
  const d = state.done[key];
  if (!d || !d.failed || !rec.audio || Date.now() - (d.at || 0) < RETRY_AFTER_MS) continue;
  if ((state.rounds[key] || 1) >= RETRY_ROUNDS) continue;
  state.rounds[key] = (state.rounds[key] || 1) + 1;
  if (d.failed === 'en' || d.failed === 'he') {
    state.done[key] = Object.assign({}, d, { failed: false }, d.failed === 'en' ? { rev: WRITER - 1 } : { again: 'he' });
    if (state.jobs[key]) delete state.jobs[key][d.failed];
    delete state.tries[key + '|' + d.failed];
    continue;
  }
  delete state.done[key];
  delete state.failed[key];
  delete state.jobs[key];
  delete state.tries[key + '|he'];
  delete state.tries[key + '|en'];
}
const older = (key) => !!state.done[key] && (state.done[key].rev || 1) < WRITER;
// an item whose Hebrew pass is tried again (touch 'hebrew')
const heAgain = (key) => !!state.done[key] && !older(key) && state.done[key].again === 'he';
const touching = (key) => older(key) || heAgain(key);
const wants = (key) => (older(key) ? ['en'] : heAgain(key) ? ['he'] : ['he', 'en']);

function mmss(sec) {
  const s = Math.max(0, Math.floor(sec || 0));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  const two = (n) => (n < 10 ? '0' : '') + n;
  return (h ? h + ':' + two(m) : two(m)) + ':' + two(r);
}

// WHISPER WRITES WORDS INTO SILENCE, and ivrit.ai's model writes the Knesset's: on the office's silent
// recordings it gave «תודה רבה.» and «אדוני היושב-ראש, חבריי חברי הכנסת» (measured on vps1,
// 2026-10-21, nine recordings). Such a segment is told by the model's own confidence (its average log
// probability: real speech there -0.27…-0.46, these -0.63…-0.89) and by a rate no one speaks at (six
// words in 0.6 s; twelve spread over 18 s of silence). It is left out of either transcript; a
// recording left with no segment in either is filed as «אין דיבור».
const MIN_CONFIDENCE = -0.6;
const MAX_WORDS_PER_S = 6;
const MIN_WORDS_PER_S_OVER_5S = 1;
const clean = (t) => String(t || '').replace(/[\\u200e\\u200f\\u202a-\\u202e]/g, '').trim();
function heard(s) {
  const text = clean(s.text);
  if (!text) return false;
  if (typeof s.confidence === 'number' && s.confidence < MIN_CONFIDENCE) return false;
  if (typeof s.start !== 'number' || typeof s.end !== 'number') return true;   // no timing to judge by
  const secs = Math.max(0.01, s.end - s.start);
  const words = text.split(/\\s+/).filter(Boolean).length;
  if (words >= 2 && words / secs > MAX_WORDS_PER_S) return false;
  // (three words at least: a lone «כן» that Whisper stretches over the silence after it is kept)
  if (words >= 3 && secs > 5 && words / secs < MIN_WORDS_PER_S_OVER_5S) return false;
  return true;
}
// …and what both models write into a silent room even with good confidence (fireplace, 2026-10-26:
// three silent recordings came back «תודה רבה. תודה רבה. תודה רבה.» / «Thank you. You» and were filed
// «תומלל»). A transcript made ONLY of these is no speech; one such line inside real talk is kept.
const STOCK = new Set(['תודה רבה', 'תודה', 'תודה רבה לכם', 'thank you', 'thanks', 'thank you very much', 'you', 'bye', 'שלום']);
const stock = (t) => STOCK.has(clean(t).toLowerCase().replace(/[.,!?…]+/g, ' ').replace(/ +/g, ' ').trim());
// …and what Whisper writes into silence from its training subtitles, in any language — never said in a
// meeting here (fireplace, 2026-10-27, MEET-35: «Продолжение следует...» = «to be continued» at the end of a
// 46-s Hebrew test call). Always dropped, alone or among real talk.
const NEVER_SAID = /^(продолжение следует|субтитры|редактор субтитров|subtitles by the amara\\.org community|thanks for watching|thank you for watching|sous-titrage|untertitel)/i;
const linesOf = (result) => {
  let segs = ((result && result.segments) || []).filter(heard).filter((s) => !NEVER_SAID.test(clean(s.text)));
  if (segs.length && segs.every((s) => stock(s.text))) return '';
  // …and the same phrase repeated through a recording with real talk in it («Thank you.» every 30 s in
  // fpg103, 2026-10-26) is the model filling gaps, not people: three or more stock lines are all dropped.
  const stockLines = segs.filter((s) => stock(s.text)).length;
  if (stockLines >= 3) segs = segs.filter((s) => !stock(s.text));
  return segs.map((s) => '[' + mmss(s.start) + '] ' + clean(s.text)).join('\\n');
};
// the model that made a transcript, and how fast, as the transcriber reports it (the owner: «when I
// get it there I also see which model did the transcription»)
const modelOf = (result) => (result && result.model
  ? Object.assign({}, result.model, { rtf: (result.usage && result.usage.rtf) || null }) : null);

// One recording's item, from what its passes gave: a transcript each, or null for one given up.
function ready(rec, key, r, error, more) {
  const he = r && r.he, en = r && r.en;
  const heLines = linesOf(he), enLines = linesOf(en);
  const any = he || en;
  const item = Object.assign({}, base, {
    kind: heLines || enLines ? 'speech' : 'silent', route: 'write', key, rec, error: error || null, rev: WRITER,
    duration: any && any.duration ? Math.round(any.duration) : null,
    he_lines: heLines, en_lines: enLines,
    models: { he: modelOf(he), en: modelOf(en) },
    lost: { he: !!r && !he && lost(key, 'he'), en: !!r && !en && lost(key, 'en') },
    // a failed recording is sent again later (RETRY_ROUNDS in all), when its sound is there
    retry: !!rec.audio && (state.rounds[key] || 1) < RETRY_ROUNDS,
    // …and in which office: the transcriber of a linked office is its door, «speech.<office>»
    // (DGO-945, the owner: «transcription … should work always on the portable machine»)
    asr_office: (/^http:\\/\\/speech\\.([a-z0-9-]+):/.exec(ASR) || [])[1] || null,
  }, more || {});
  return { json: item };
}

// TWO RUNS MAY STILL OVERLAP now and then (a clock run that began just before meet-start's call, a
// call that hung, meet-start restarted while its run went on), and this static data is saved only
// when a run ends, the last one's over the other's. So it is only a memory: what is true is asked of
// the two places that know it.
//   · Plane: an item there for a recording means it is done. Asked before a recording is sent, and
//     before its transcripts are written; a Plane that does not answer is no "no" for long (the
//     writer looks again before it writes, and Plane refuses a second item with the same key).
//   · The transcriber's own list of its jobs: a recording's audio already queued, running or done
//     there for a pass (by its name, size and model) is not sent again.
let project;   // undefined: not asked yet
async function inPlane(key) {
  if (!base.plane_api) return null;
  const api = (path) => helpers.httpRequest({ method: 'GET', url: PLANE + '/api/v1/workspaces/' + WS + path, json: true, timeout: 20000 });
  try {
    if (project === undefined) project = rows(await api('/projects/?per_page=100')).find((p) => p.identifier === 'MEET') || null;
    if (!project) return null;
    const got = await api('/projects/' + project.id + '/issues/?external_source=' + SOURCE + '&external_id=' + encodeURIComponent(key));
    return (got && got.id) ? got : (rows(got).find((i) => i.external_source === SOURCE && i.external_id === key) || null);
  } catch (e) {
    return null;   // 404 is "none"; anything else, the writer asks again before it writes
  }
}
// An item Plane has is done; one this writer did not finish (no MARK, or its Whisper transcript still
// to come or given up) gets that one put in (and one whose Hebrew pass was given up, that one: settled)
const finished = (issue) => {
  const html = String((issue && issue.description_html) || '');
  return html.includes(MARK) && !html.includes(PENDING_EN) && !html.includes(EN_LOST) && !failedItem(issue);
};
// an item written for a recording whose transcription failed (as this writer says it, or as the ones
// before it did): written over whole when a retry succeeds
const failedItem = (issue) => {
  const html = String((issue && issue.description_html) || '');
  return [FAILED_MARK, '<strong>התמלול נכשל', '<strong>שליחת השמע לתמלול נכשלה'].some((s) => html.includes(s));
};
function settled(key, issue) {
  const whole = finished(issue);
  const heLost = whole && String(issue.description_html || '').includes(HE_TITLE + '<p>' + HE_LOST);
  state.done[key] = { issue: issue.id, at: Date.now(), from: 'plane', rev: whole ? WRITER : WRITER - 1, again: heLost ? 'he' : null };
  if (whole && !heLost) delete state.jobs[key];   // (a Hebrew job already sent is the one its touch waits for)
  delete state.failed[key];
  delete state.planeFails[key];
}

// A Hebrew room's file name carries the room escaped (%d7%a9…), and the name the upload arrives
// under may be escaped once more on the way: both sides are compared fully unescaped.
const norm = (s) => {
  let x = String(s || '');
  for (let i = 0; i < 3; i++) {
    let y;
    try { y = decodeURIComponent(x); } catch (e) { break; }
    if (y === x) break;
    x = y;
  }
  return x;
};
let asrJobs = null;   // null: the transcriber did not answer; its jobs are then asked by the ids kept here
try {
  asrJobs = rows((await helpers.httpRequest({ method: 'GET', url: ASR + '/speechJobs?limit=100', json: true, timeout: 30000 })).jobs);
} catch (e) {
  asrJobs = null;
}
const LIVE = ['queued', 'processing', 'completed'];
// A recording's job for one pass: one the transcriber still has queued, running or done for this
// audio and this model (newest first; a job from before there were two models is the Hebrew one),
// else the one this memory holds. A failed job no run here holds was counted by the run that held
// it, so it is not counted again.
function jobOf(rec, key, p) {
  const known = jobsOf(key)[p];
  if (!asrJobs) return known ? { id: known.id } : null;
  const mine = asrJobs.filter((j) => (known && j.id === known.id)
    || (j.source && norm(j.source.name) === norm(rec.audio) && Number(j.source.bytes) === Number(rec.audio_bytes)
        && ((j.options && j.options.model) || 'ivrit') === PASSES[p].model));
  const live = mine.find((j) => LIVE.includes(j.status));
  if (live) return live;
  if (known) return mine.find((j) => j.id === known.id) || { id: known.id };
  return null;
}

// 1. What the transcriber finished, failed, or is still working on, pass by pass. A new recording is
// written once its Hebrew pass has answered (a meeting's item does not wait hours for the second
// pass: the Whisper transcript is put into it when it comes); an older item is gone over once its
// Whisper pass has answered, or been given up.
const WRITE_TRIES = 6;     // runs that go over an item Plane has but could not finish (half an hour)
let busy = 0;
for (const rec of recs) {
  const key = rec.session + '/' + rec.file;
  if ((state.done[key] && !touching(key)) || state.failed[key]) continue;
  if (!rec.audio) {
    // an older item whose audio is gone: nothing to transcribe, and its translation's leftovers still
    // come off (a touch Plane keeps refusing ends like a write does: the item stays as it is)
    if (older(key)) {
      if ((state.planeFails[key] || 0) >= WRITE_TRIES) state.done[key].rev = WRITER;
      else out.push(ready(rec, key, {}, null, { touch: 'whisper', lost: { he: false, en: true }, no_audio: true }));
    } else if (heAgain(key)) {
      // nothing left to transcribe: the item says so, instead of the round it promised
      if ((state.planeFails[key] || 0) >= WRITE_TRIES) state.done[key].again = null;
      else out.push(ready(rec, key, {}, null, { touch: 'hebrew', lost: { he: true, en: false }, no_audio: true }));
    }
    continue;
  }
  const mine = jobsOf(key);
  const r = {};
  const waits = {};
  for (const p of wants(key)) {
    if (lost(key, p)) continue;
    const job = jobOf(rec, key, p);
    if (!job) { waits[p] = true; continue; }        // not sent yet: part 2 sends it
    mine[p] = { id: job.id, at: (mine[p] && mine[p].at) || Date.now() };
    let st = (job.status && job.status !== 'completed') ? job : null;
    if (!st) {
      try {
        st = await helpers.httpRequest({ method: 'GET', url: ASR + '/transcriptionStatus?id=' + encodeURIComponent(job.id), json: true, timeout: 30000 });
      } catch (e) {
        // the transcriber forgot the job (its volume was reset): the audio is sent again below
        if (statusOf(e) === 404) delete mine[p];
        else busy += 1;   // it does not answer now: the job is counted as still running
        waits[p] = true;
        continue;
      }
    }
    if (st.status === 'completed') {
      // a finished job's status already carries its result; asked for apart only when it does not
      r[p] = (st.result && st.result.segments) ? st.result : null;
      if (!r[p]) {
        try {
          r[p] = await helpers.httpRequest({ method: 'GET', url: ASR + '/transcriptionResult?id=' + encodeURIComponent(job.id) + '&format=verbose_json', json: true, timeout: 60000 });
        } catch (e) {
          waits[p] = true;   // the next run asks again
        }
      }
    } else if (st.status === 'error' || st.status === 'cancelled') {
      delete mine[p];
      // its queue was full, or the transcriber restarted before it began: not the recording's fault. A
      // job interrupted while it ran counts (a recording that brings the transcriber down would else be
      // sent again for ever, and take every other queued job down with it).
      const code = st.error && st.error.code;
      if (!(code === 'queue_full' || (code === 'interrupted' && !st.started))) {
        state.tries[key + '|' + p] = tries(key, p) + 1;
      }
      if (!lost(key, p)) waits[p] = true;
    } else {
      busy += 1;        // queued or processing
      waits[p] = true;
    }
  }
  if (older(key)) {
    if (waits.en) continue;
    // a touch Plane keeps refusing ends like a write does: the item stays as it is
    if ((state.planeFails[key] || 0) >= WRITE_TRIES) { state.done[key].rev = WRITER; continue; }
    // its Whisper transcript, or (given up) the line that says so, goes into the item
    out.push(ready(rec, key, { en: r.en || null }, null, { touch: 'whisper' }));
    continue;
  }
  if (heAgain(key)) {
    if (waits.he) continue;
    if ((state.planeFails[key] || 0) >= WRITE_TRIES) { state.done[key].again = null; continue; }
    // its Hebrew transcript, or (given up again) the line that says so, goes into the item
    out.push(ready(rec, key, { he: r.he || null }, null, { touch: 'hebrew' }));
    continue;
  }
  // a new recording: written once its Hebrew pass has answered; one with no Hebrew words waits for the
  // Whisper pass (it may be a meeting held in English), and so does one whose Hebrew pass was given up
  if (waits.he || (waits.en && !linesOf(r.he))) continue;
  if (!r.he && !r.en) {
    state.failed[key] = 'התמלול נכשל בשני המודלים (ניסיונות: ' + tries(key, 'he') + ', ' + tries(key, 'en') + ')';
    out.push(ready(rec, key, null, state.failed[key]));
    continue;
  }
  // an item this memory tried to write and could not finish (its file not attached yet) is not
  // "done" because Plane has it: the writer goes over it again, WRITE_TRIES times at most; after that
  // the item stays as Plane has it, and the owner is told its file is not on it. An item Plane has
  // that this memory did not write (another run, or memory lost) is taken as Plane has it — unless it
  // says its transcription failed: this round's transcripts are written over it.
  const fails = state.planeFails[key] || 0;
  if (!fails || fails >= WRITE_TRIES) {
    const found = await inPlane(key);
    if (found && !failedItem(found)) {
      settled(key, found);
      if (fails) {
        await notify('warning', 'פגישות: הקובץ לא צורף לפריט: ' + rec.room,
          'הפריט נכתב, והקובץ לא צורף (ניסיונות: ' + fails + '); ההקלטה בקישור שבפריט.');
      }
      continue;
    }
  }
  out.push(ready(rec, key, r, null, { en_pending: !!waits.en }));
}

// 2. What is new, and what was given up (its item is written, it is never transcribed again); then
// the older items' Whisper pass, one at a time and only while no new recording waits to be sent: a
// meeting just held is never queued behind the older ones.
let asr;   // undefined: not asked yet; null: down or full
const emitted = new Set(out.map((i) => i.json.key));
async function send(rec, key) {
  const mine = jobsOf(key);
  for (const p of wants(key)) {
    if (mine[p] || lost(key, p)) continue;
    if (busy >= IN_FLIGHT) return;
    // a transcriber that is down or full is not sent anything: a recording's attempts are not spent on it
    if (asr === undefined) {
      asr = await helpers.httpRequest({ method: 'GET', url: ASR + '/speechHealth', json: true, timeout: 15000 }).catch(() => null);
      const q = asr && asr.jobs;
      if (q && q.queue_limit && q.queue_depth >= q.queue_limit) asr = null;
    }
    if (!asr) return;
    // …nor a Whisper pass it cannot run (a transcriber from before it had two models would run it as
    // Hebrew, refuse «auto», and spend the pass's attempts): the pass waits, and the owner is told daily
    if (PASSES[p].model !== 'ivrit' && !(asr.models && asr.models[PASSES[p].model])) {
      if (!state.noWhisperAt || Date.now() - state.noWhisperAt > 24 * 3600 * 1000) {
        state.noWhisperAt = Date.now();
        await notify('warning', 'פגישות: למתמלל אין את Whisper', 'התמלול בעברית נכתב; התמלול של Whisper יתווסף כשהמתמלל יעודכן (apitools-asr, DGO-955).');
      }
      continue;
    }
    busy += 1;
    out.push({ json: Object.assign({}, base, { kind: 'submit', route: 'submit', key, pass: p,
      model: PASSES[p].model, language: PASSES[p].language, session: rec.session, audio: rec.audio }) });
  }
}
// (a recording written this run with its Whisper transcript still to come has that pass sent now)
const pendingEn = new Set(out.filter((i) => i.json.en_pending).map((i) => i.json.key));
for (const rec of recs) {
  const key = rec.session + '/' + rec.file;
  if (state.done[key] || (emitted.has(key) && !pendingEn.has(key))) continue;
  if (state.failed[key]) {
    const found = (state.planeFails[key] || 0) >= WRITE_TRIES ? await inPlane(key) : null;
    // written, its file not attached: as Plane has it (and, failed, tried again in a later round)
    if (found) state.done[key] = { issue: found.id, at: Date.now(), from: 'plane', rev: WRITER, failed: true };
    else out.push(ready(rec, key, null, state.failed[key]));
    continue;
  }
  if (!rec.audio) {
    if (rec.mtime > state.since && Date.now() / 1000 - rec.mtime > NO_AUDIO_AFTER_S) {
      state.failed[key] = 'אין קובץ שמע להקלטה הזו (jibri/finalize.sh לא כתב אותו)';
      out.push(ready(rec, key, null, state.failed[key]));
    }
    continue;
  }
  const mine = jobsOf(key);
  if (!mine.he && !mine.en && !lost(key, 'he') && !lost(key, 'en') && busy < IN_FLIGHT) {
    const found = await inPlane(key);   // written by a run whose memory was lost: not sent again
    if (found && !failedItem(found)) { settled(key, found); continue; }
  }
  await send(rec, key);
}
// (one being written, or whose write Plane refuses, holds nothing up: its next run sends it)
const waitsToBeSent = (rec) => {
  const key = rec.session + '/' + rec.file;
  if (state.done[key] || state.failed[key] || !rec.audio || emitted.has(key) || state.planeFails[key]) return false;
  const mine = jobsOf(key);
  return wants(key).some((p) => !mine[p] && !lost(key, p));
};
if (!recs.some(waitsToBeSent)) {
  for (const rec of recs) {
    const key = rec.session + '/' + rec.file;
    if (busy >= 1) break;
    if (touching(key) && rec.audio && !emitted.has(key)) await send(rec, key);
  }
}

// What this run does, in words, on its bar in any-concurrency (it reads an execution's «outline»)
// and in n8n's own list of executions: «2 לתמלול · 1 לכתיבה · 1 בתמלול».
const count = (route) => out.filter((i) => i.json.route === route).length;
const said = [
  count('submit') && count('submit') + ' לתמלול',
  count('write') && count('write') + ' לכתיבה',
  busy && busy + ' בתמלול',
].filter(Boolean).join(' · ') || 'אין מה לעשות';
try { $execution.customData.set('outline', said); } catch (e) { /* an n8n without custom data: the bar says #id */ }
return out;`,
    };

    @node({
        id: 'meet-rec-route-01',
        name: 'Route',
        type: 'n8n-nodes-base.switch',
        version: 3.2,
        position: [480, 300],
    })
    Route = {
        rules: {
            values: [
                {
                    conditions: {
                        options: { caseSensitive: true, leftValue: '', typeValidation: 'loose', version: 2 },
                        conditions: [{ leftValue: '={{ $json.route }}', rightValue: 'submit', operator: { type: 'string', operation: 'equals' } }],
                        combinator: 'and',
                    },
                },
                {
                    conditions: {
                        options: { caseSensitive: true, leftValue: '', typeValidation: 'loose', version: 2 },
                        conditions: [{ leftValue: '={{ $json.route }}', rightValue: 'write', operator: { type: 'string', operation: 'equals' } }],
                        combinator: 'and',
                    },
                },
            ],
        },
        options: {},
    };

    @node({
        id: 'meet-rec-audio-01',
        name: 'Fetch the audio',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [720, 120],
        onError: 'continueRegularOutput',
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 5000,
    })
    FetchAudio = {
        method: 'GET',
        url: "={{ 'http://meet-start:8001/api/recordings/' + encodeURIComponent($json.session) + '/' + encodeURIComponent($json.audio) }}",
        options: {
            timeout: 300000,
            response: { response: { responseFormat: 'file', outputPropertyName: 'data' } },
        },
    };

    // One pass of a recording: the model and the language the plan named (ivrit/he, whisper/auto).
    @node({
        id: 'meet-rec-asr-01',
        name: 'Send to the transcriber',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [960, 120],
        onError: 'continueRegularOutput',
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 10000,
    })
    SendAudio = {
        method: 'POST',
        url: 'http://apitools-asr:8987/transcribe?async=1',
        sendBody: true,
        contentType: 'multipart-form-data',
        bodyParameters: {
            parameters: [
                { name: 'model', value: "={{ $('Plan the run').item.json.model }}" },
                { name: 'language', value: "={{ $('Plan the run').item.json.language }}" },
                { name: 'response_format', value: 'verbose_json' },
                { parameterType: 'formBinaryData', name: 'file', inputDataFieldName: 'data' },
            ],
        },
        options: { timeout: 300000 },
    };

    @node({
        id: 'meet-rec-remember-01',
        name: 'Remember the job',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1200, 120],
        onError: 'continueRegularOutput',
    })
    Remember = {
        mode: 'runOnceForEachItem',
        jsCode: `// The transcriber took the audio for one pass and answered with its job: keep it for the runs that
// follow. When the audio could not be fetched or sent, the attempt counts (a full queue does not):
// after GIVE_UP_AFTER of them (the plan's three) that pass is given up, and the item is written
// with what the other pass gave.
const GIVE_UP_AFTER = 3;
const src = $('Plan the run').item.json;
const state = $getWorkflowStaticData('global');
state.jobs = state.jobs || {};
state.tries = state.tries || {};
const j = state.jobs[src.key];
const mine = !j ? {} : (j.id ? { he: j } : j);
state.jobs[src.key] = mine;
if ($json.id) {
  mine[src.pass] = { id: $json.id, at: Date.now() };
  return { json: { key: src.key, pass: src.pass, job: $json.id, status: $json.status, eta_seconds: $json.eta_seconds } };
}
const err = $json.error || $json;
const code = Number((err && (err.httpCode || err.status)) || 0);
const why = String((err && (err.description || err.message)) || JSON.stringify(err)).slice(0, 300);
if (code === 429) return { json: { key: src.key, pass: src.pass, error: why, counted: false } };
const t = src.key + '|' + src.pass;
const n = (state.tries[t] || 0) + 1;
state.tries[t] = n;
return { json: { key: src.key, pass: src.pass, error: why, attempt: n, given_up: n >= GIVE_UP_AFTER } };`,
    };

    @node({
        id: 'meet-rec-plane-01',
        name: 'Write the Plane item',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [720, 420],
    })
    WritePlane = {
        mode: 'runOnceForEachItem',
        jsCode: `// One recording, one Plane item in project MEET: written once, keyed by the recording, so a run
// that repeats (a failure after Plane answered) edits the same item instead of opening a second.
// It carries both transcripts (DGO-955): ivrit.ai's Hebrew, and Whisper's, each stretch as spoken.
// An item written before there were two (touch 'whisper') gets the Whisper transcript in place of
// the English section it had — a translation, or the line that said one was to come — and loses the
// label that said so; nothing else of it is touched (the owner may have edited it).
// A failure here is said (the notice centre, at most once an hour per recording) and NOT thrown: the
// other recordings of this run go on, and the next run tries this one again.
// Two overlapping runs may both write one recording: Plane refuses the second item with the same
// key, and that run edits the first instead. The owner is told once, when the item is opened.
const helpers = this.helpers;
const MEET = 'http://meet-start:8001';   // (another office's door, where push wrote one: the plan's note)
const WS = 'bina';                       // the office's Plane workspace (apps/project-pln/bootstrap.yaml)
const SOURCE = 'meet-recording';
const EN_TITLE = 'Transcript (Whisper';  // the second section's heading
const PENDING_EN = '(the Whisper transcript is still being made';   // (the plan looks for it)
const HE_LOST = 'התמלול בעברית נכשל';     // a pass given up, as the item says it (the plan looks for it)
const EN_LOST = 'The Whisper transcript failed';
const HE_TITLE = '<h2>תמלול בעברית (ivrit.ai)</h2>';
const OLD_EN = '<h2>Transcript (English)</h2>';   // the translation's section, before DGO-955
const OLD_PENDING = '(the English translation is still to come';   // …and its line while it waited
const OLD_LABEL = 'ממתין לתרגום';         // the translation's label, before DGO-955: taken off
const MODEL_FACT = 'מודל התמלול';
const state = $getWorkflowStaticData('global');
state.planeFails = state.planeFails || {};
let src = { key: '?', rec: {} };
const notify = (level, title, body, link) => helpers.httpRequest({
  method: 'POST', url: 'http://notifications:8977/api/notifications', json: true, timeout: 15000,
  body: { source: 'meet', source_id: src.key, level, title, body, link },
}).catch(() => {});

const esc = (s) => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const lines = (text, dir) => text.split('\\n').filter(Boolean).map((l) => '<p dir="' + dir + '">' + esc(l) + '</p>').join('');
const rows = (x) => (Array.isArray(x) ? x : (x && x.results) || []);
// the error reaches a Code node in n8n's task runner as its message only: the status is read there too
const statusOf = (e) => {
  const n = Number((e && (e.httpCode || (e.response && e.response.status) || e.statusCode || e.status)) || 0);
  const m = /status code (\\d{3})/.exec(String((e && (e.message || e.description)) || e));
  return n || (m ? Number(m[1]) : 0);
};

try {
  src = $('Plan the run').item.json;
  const rec = src.rec;
  const plane = src.plane_api;
  // as the plan reached it: meet-start's relay, or Plane's own address (the plan says why)
  const PLANE = src.plane || (MEET + '/api/plane');
  const api = (method, path, body) => helpers.httpRequest({
    method, url: PLANE + '/api/v1/workspaces/' + WS + path, json: true, body, timeout: 60000,
  });
  if (!plane) throw new Error('meet-start says no Plane address: apps/meet/hooks/prepare derives MEET_PLANE_API_URL from the link registry');
  const project = rows(await api('GET', '/projects/?per_page=100')).find((p) => p.identifier === 'MEET');
  if (!project) throw new Error('Plane has no project MEET: ./bbox project-pln plan meetings creates it');
  const P = '/projects/' + project.id;
  const labelIds = {};
  for (const l of rows(await api('GET', P + '/labels/?per_page=100'))) labelIds[l.name] = l.id;

  const models = src.models || {};
  const one = (m) => (m && m.name
    ? m.name + (m.revision ? ' @' + String(m.revision).slice(0, 8) : '') + (m.compute ? ' · ' + m.compute : '')
      + (m.rtf ? ' · פי ' + m.rtf + ' מזמן אמת' : '')
    : null);
  const model = ([one(models.he), one(models.en)].filter(Boolean).join(' | ') || '—')
    + (src.asr_office ? ' · תומלל ב-' + src.asr_office : '');
  const lost = src.lost || {};
  const heSection = HE_TITLE + (src.he_lines ? lines(src.he_lines, 'rtl')
    : '<p>' + (lost.he ? HE_LOST + '.' + (src.no_audio ? ' אין עוד שמע לתמלל.' : src.retry ? ' הוא ינוסה שוב בעוד 6 שעות.' : '')
      : 'אין בו דיבור בעברית.') + '</p>');
  const enSection = '<h2>' + EN_TITLE + ', each part as spoken)</h2>' + (src.en_lines ? lines(src.en_lines, 'auto')
    : '<p>' + (src.en_pending ? PENDING_EN + ': it is added here when it is ready)'
      : src.no_audio ? 'There is no audio left to transcribe.'
      : lost.en ? EN_LOST + '.' + (src.retry ? ' It is tried again in six hours.' : '') : 'Whisper found no speech in it.') + '</p>');
  // a pass given up is tried again in a later round: that pass alone ('he', 'en'), or the whole
  // recording when neither gave a transcript (true). A touch answers for its own pass only.
  const heFailed = lost.he && src.touch !== 'whisper' && !src.no_audio;
  const enFailed = lost.en && src.touch !== 'hebrew' && !src.en_pending && !src.no_audio;
  const failedPass = src.error ? true : heFailed ? 'he' : enFailed ? 'en' : false;
  // every item this writer writes says it (the plan reads «ivrit.ai + Whisper» as written by it)
  const FOOTER = '<p><em>נכתב אוטומטית מאפליקציית הפגישות (apps/meet, תמלול: ivrit.ai + Whisper).</em></p>';
  // A meeting with speech that holds a minute or more of full silence (jibri/finalize.sh measured it):
  // said at the top of its item and in its notice (DGO-959: the owner's phone stopped sending his voice
  // when he showed another app, and 21 minutes were recorded silent with nobody in the room to hear it).
  const clock = (sec) => {
    const s = Math.max(0, Math.floor(sec || 0)), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
    const two = (n) => (n < 10 ? '0' : '') + n;
    return (h ? h + ':' + two(m) : two(m)) + ':' + two(r);
  };
  const SILENT_MARK = 'שקט מלא בהקלטה';
  const gaps = (rec.silences || []).filter((g) => Array.isArray(g) && g[1] - g[0] >= 60);
  const gapText = gaps.map((g) => clock(g[0]) + '–' + clock(g[1]) + ' (' + Math.max(1, Math.round((g[1] - g[0]) / 60)) + ' דק׳)').join(', ');
  const SILENT_NOTE = gaps.length ? '<p><strong>⚠️ ' + SILENT_MARK + ': ' + esc(gapText) + '. אם דיברו אז, הקול לא הגיע להקלטה'
    + ' — למשל טלפון שעבר לאפליקציה אחרת כשההתראות של Jitsi כבויות.</strong></p>' : '';

  // Plane answers (external_source, external_id) with the item itself, and 404 with none
  // (apps/project-pln/plan.py reads it the same way); an API that ignores the pair answers a page.
  const lookup = async () => {
    try {
      const got = await api('GET', P + '/issues/?external_source=' + SOURCE + '&external_id=' + encodeURIComponent(src.key));
      return (got && got.id) ? got : (rows(got).find((i) => i.external_source === SOURCE && i.external_id === src.key) || null);
    } catch (e) {
      if (statusOf(e) !== 404) throw e;
      return null;
    }
  };
  let found = await lookup();
  // Plane's own module id: the console that shows the notice resolves it to its Plane tile, a local
  // one or a linked office's (console/static/module-ref.js, the remote tile's home id) — this
  // workflow may run in either kind of office (DGO-945)
  const linkOf = (id) => '/#/m/project-pln/' + WS + '/projects/' + project.id + '/issues/' + id;
  const labelsOf = (issue) => (issue.labels || []).map((l) => (l && typeof l === 'object' ? l.id : l)).filter(Boolean);

  // An item written before there were two transcripts, or before its Whisper pass came back: the
  // Whisper transcript (or the line that says it failed) goes where its English section was, or its
  // «still being made» line, or (none) before the writer's closing paragraphs; its model joins the
  // list of facts; the translation's label comes off. Only what the writers themselves wrote is
  // replaced — the heading and the paragraphs of the shapes they write — so an item the owner edited
  // loses nothing of his. An item no longer there is left alone. An item whose Hebrew pass was given up
  // and is tried again (touch 'hebrew') gets its Hebrew transcript in place of the line that said so.
  if (src.touch) {
    state.done = state.done || {};
    if (!found) {
      state.done[src.key] = Object.assign({}, state.done[src.key], { rev: src.rev, again: null });
      return { json: { key: src.key, issue: null, touched: 'gone' } };
    }
    let cur = String(found.description_html || '');
    const hebrew = src.touch === 'hebrew';
    const words = hebrew ? src.he_lines : src.en_lines;
    if (hebrew) {
      // the line under its heading that said it failed; edited away, the transcript goes before the
      // Whisper section or the writer's closing paragraphs (the owner's text is never cut)
      const h = cur.indexOf(HE_TITLE);
      const end = h >= 0 && cur.startsWith('<p>' + HE_LOST, h + HE_TITLE.length) ? cur.indexOf('</p>', h + HE_TITLE.length) : -1;
      if (end >= 0) {
        cur = cur.slice(0, h) + heSection + cur.slice(end + 4);
      } else if (src.he_lines) {
        const at = Math.min(...['<h2>' + EN_TITLE, '<p>מצורף קול ההקלטה', '<p>לא צורף קובץ', '<p><em>']
          .map((s) => cur.indexOf(s)).filter((i) => i >= 0), cur.length);
        cur = cur.slice(0, at) + heSection + cur.slice(at);
      }
    } else {
      // the writers' own paragraphs from \`at\` on: English lines, or the line that said one was coming
      const own = (at) => {
        for (;;) {
          if (!['<p dir="ltr">', '<p dir="auto">', '<p>' + OLD_PENDING, '<p>' + PENDING_EN, '<p>' + EN_LOST].some((s) => cur.startsWith(s, at))) return at;
          const end = cur.indexOf('</p>', at);
          if (end < 0) return at;
          at = end + 4;
        }
      };
      let slot = null;
      const old = cur.indexOf(OLD_EN);
      if (old >= 0) slot = [old, own(old + OLD_EN.length)];
      const mine = cur.indexOf('<h2>' + EN_TITLE);
      if (!slot && mine >= 0 && (cur.includes(PENDING_EN) || cur.includes(EN_LOST))) {
        const h = cur.indexOf('</h2>', mine);
        if (h > mine) slot = [mine, own(h + 5)];
      }
      if (slot) {
        cur = cur.slice(0, slot[0]) + enSection + cur.slice(slot[1]);
      } else if (mine < 0 && (src.en_lines || (lost.en && !src.no_audio))) {
        // no section of either kind: before the writer's closing paragraphs (the file's note, the footer)
        const at = Math.min(...['<p>מצורף קול ההקלטה', '<p>לא צורף קובץ', '<p><em>']
          .map((s) => cur.indexOf(s)).filter((i) => i >= 0), cur.length);
        cur = cur.slice(0, at) + enSection + cur.slice(at);
      }
    }
    if (words) cur = cur.split('<p>אין דיבור בהקלטה הזו.</p>').join('');
    // a long silence in a meeting with speech: said under the list of facts, once
    if (SILENT_NOTE && !cur.includes(SILENT_MARK) && (words || cur.includes('<p dir="rtl">')) && cur.includes('</ul>')) {
      const ul = cur.indexOf('</ul>') + 5;
      cur = cur.slice(0, ul) + SILENT_NOTE + cur.slice(ul);
    }
    const fact = cur.indexOf('<strong>' + MODEL_FACT + ':</strong>');
    const m = hebrew ? models.he : models.en;
    const made = one(m);
    if (made && fact >= 0) {
      const close = cur.indexOf('</li>', fact);
      if (close > fact && !cur.slice(fact, close).includes(m.name)) cur = cur.slice(0, close) + ' | ' + esc(made) + cur.slice(close);
    } else if (made && cur.indexOf('</ul>') >= 0) {
      const ul = cur.indexOf('</ul>');
      cur = cur.slice(0, ul) + '<li><strong>' + esc(MODEL_FACT) + ':</strong> ' + esc(made) + '</li>' + cur.slice(ul);
    }
    cur = cur.split('תמלול: ivrit.ai)').join('תמלול: ivrit.ai + Whisper)');
    let labels = labelsOf(found).filter((id) => id !== labelIds[OLD_LABEL]);
    if (words && labelIds['אין דיבור'] && labels.includes(labelIds['אין דיבור'])) {
      labels = labels.filter((id) => id !== labelIds['אין דיבור']).concat(labelIds['תומלל'] ? [labelIds['תומלל']] : []);
    }
    await api('PATCH', P + '/issues/' + found.id + '/', { description_html: cur, labels });
    state.done[src.key] = Object.assign({}, state.done[src.key], { issue: found.id, rev: src.rev, again: null, failed: failedPass },
      failedPass ? { at: Date.now() } : {});
    delete state.planeFails[src.key];
    if (state.jobs) delete state.jobs[src.key];
    if (words) {
      await notify('info', (hebrew ? 'התמלול בעברית נוסף: ' : 'התמלול של Whisper נוסף: ') + rec.room,
        'MEET-' + found.sequence_id + ' · ' + rec.started, linkOf(found.id));
    }
    return { json: { key: src.key, issue: 'MEET-' + found.sequence_id, touched: src.touch } };
  }

  const want = ['הקלטה', src.kind === 'speech' ? 'תומלל' : (src.error ? null : 'אין דיבור')].filter(Boolean);
  const minutes = src.duration ? Math.max(1, Math.round(src.duration / 60)) + ' דק׳' : '—';
  const facts = [
    ['חדר', rec.room], ['התחילה', rec.started], ['משך', minutes],
    ['נפתחה על ידי', rec.initiator || '—'], ['משתתפים', (rec.people || []).join(', ') || '—'],
    [MODEL_FACT, model],
  ].map((f) => '<li><strong>' + esc(f[0]) + ':</strong> ' + esc(f[1]) + '</li>').join('');
  let html = '<h2>הקלטה</h2><ul>' + facts + '</ul>';
  html += rec.video_url ? '<p><a href="' + esc(rec.video_url) + '">צפייה בהקלטה</a> (' + esc(rec.file) + ')</p>' : '';
  if (src.kind === 'speech') html += SILENT_NOTE;
  // (FAILED_MARK: the plan reads it as «not finished»; a later round writes this item over)
  if (src.error) {
    html += '<p><strong>⚠️ התמלול לא הושלם: ' + esc(src.error)
      + (src.retry ? ' — הוא ינוסה שוב מההתחלה בעוד 6 שעות, ויחליף את הפריט הזה.' : '') + '</strong></p>';
  }
  // (a recording with no words that lost one pass says which, so that pass's later round has its place)
  if (src.kind === 'speech' || (!src.error && (lost.he || lost.en))) {
    html += heSection + enSection;
  } else if (!src.error) {
    html += '<p>אין דיבור בהקלטה הזו.</p>';
  }
  html += FOOTER;

  const body = {
    name: 'פגישה · ' + rec.room + ' · ' + rec.started,
    description_html: html,
    labels: want.map((n) => labelIds[n]).filter(Boolean),
    external_source: SOURCE,
    external_id: src.key,
  };

  let issue = null;
  if (!found) {
    try {
      issue = await api('POST', P + '/issues/', body);
    } catch (e) {
      if (statusOf(e) !== 409) throw e;
      found = await lookup();            // another run opened it a moment ago: edit that one
      if (!found) throw e;
    }
  }
  if (found) issue = await api('PATCH', P + '/issues/' + found.id + '/', body);

  // The recording itself, on the item (the owner: «upload the file to Plain»), once: the video when
  // this Plane takes its size (its FILE_SIZE_LIMIT, 50 MB here, about ten minutes of meeting), else
  // its sound (about 15 MB an hour). Plane signs a form, meet-start (the one container that holds the
  // file) posts it to Plane's store through that form, and Plane is told it arrived. A store that
  // does not answer is thrown to the catch below, so a later run attaches it; a file this Plane does
  // not take is said on the item.
  const A = P + '/issues/' + issue.id + '/issue-attachments/';
  const nameOf = (a) => String((a && ((a.attributes && a.attributes.name) || a.name)) || '');
  const have = rows(await api('GET', A)).map(nameOf);
  let attached = [rec.file, rec.audio].find((n) => n && have.includes(n)) || null;
  const refused = [];
  for (const f of [{ name: rec.file, type: 'video/mp4', size: rec.bytes }, { name: rec.audio, type: 'audio/ogg', size: rec.audio_bytes }]) {
    if (attached || !f.name || !f.size) continue;
    let made;
    try {
      made = await api('POST', A, { name: f.name, type: f.type, size: f.size });
    } catch (e) {
      if (statusOf(e) !== 400) throw e;
      refused.push(f.name + ': ' + String((e && (e.description || e.message)) || e).slice(0, 120));
      continue;                          // this Plane does not take the type: the next file
    }
    const form = (made && made.upload_data) || {};
    try {
      await helpers.httpRequest({
        method: 'POST', json: true, timeout: 660000, body: { url: form.url, fields: form.fields },
        url: MEET + '/api/recordings/' + encodeURIComponent(rec.session) + '/' + encodeURIComponent(f.name) + '/to-plane',
      });
    } catch (e) {
      if (statusOf(e) !== 413) throw e;
      refused.push(f.name + ': ' + Math.round(f.size / 1048576) + ' MB, more than this Plane takes');
      continue;                          // too big for this Plane: the next, smaller file
    }
    await api('PATCH', A + made.asset_id + '/', {});
    attached = f.name;
  }
  if (attached !== rec.file) {
    const note = attached ? 'מצורף קול ההקלטה (' + esc(attached) + '); הסרטון עצמו בקישור למעלה.'
      : 'לא צורף קובץ: ' + esc(refused.join(' · ') || 'אין קובץ לצרף');
    if (!String(issue.description_html || '').includes(note)) {
      issue = await api('PATCH', P + '/issues/' + issue.id + '/', { description_html: html.replace(FOOTER, '<p>' + note + '</p>' + FOOTER) });
    }
  }
  delete state.planeFails[src.key];

  // written with its Whisper transcript still to come: the plan puts it in when it is back (the
  // job stays in memory for that); else finished
  state.done = state.done || {};
  state.done[src.key] = { issue: issue.id, at: Date.now(), rev: src.en_pending ? (src.rev || 1) - 1 : (src.rev || 1),
    failed: failedPass };
  if (state.jobs && !src.en_pending) delete state.jobs[src.key];
  if (state.failed) delete state.failed[src.key];

  const link = linkOf(issue.id);
  // the notice centre keeps one notice per recording (source_id): an item opened says what it is
  if (!found) {
    await notify(src.error || (src.kind === 'speech' && gaps.length) ? 'warning' : 'info',
      (src.kind === 'speech' ? 'הפגישה תומללה: ' : 'הפגישה נשמרה: ') + rec.room,
      'MEET-' + issue.sequence_id + ' · ' + rec.started + (src.error ? ' · ' + src.error : '')
        + (src.kind === 'speech' || src.error ? '' : ' · אין דיבור')
        + (src.kind === 'speech' && gaps.length ? ' · ⚠️ ' + SILENT_MARK + ': ' + gapText : ''), link);
  }
  return { json: { key: src.key, issue: 'MEET-' + issue.sequence_id, link, kind: src.kind, opened: !found, attached, refused } };
} catch (e) {
  const n = (state.planeFails[src.key] || 0) + 1;
  state.planeFails[src.key] = n;
  const why = String((e && (e.description || e.message)) || e).slice(0, 300);
  // a touch that failed left the item as it was, which is fine: it is tried again (WRITE_TRIES at
  // most, the plan's), and not said
  if (!src.touch && (n === 1 || n % 12 === 0)) {
    await notify('error', 'הפגישה לא נכתבה ל-Plane: ' + ((src.rec && src.rec.room) || src.key), 'ניסיון ' + n + ' · ' + why, '/#/m/meet');
  }
  return { json: { key: src.key, error: why, attempt: n } };
}`,
    };
}
