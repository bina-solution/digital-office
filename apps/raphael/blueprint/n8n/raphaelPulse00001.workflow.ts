import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : Raphael — office pulse
// Nodes   : 2  |  Connections: 1
//
// Schedule (every 5 min)
//    -> Pulse
// </workflow-map>
//
// The owner's ask, 2026-10-09: "set yourself a reminder every 5 minutes to verify that development
// is progressing as well as possible, fast and efficiently". This is that reminder, made durable: a
// clock that lives in n8n rather than inside one conversation's turn (the turn that was cut at
// 04:53 was doing exactly this, and died with the container).
//
// What it can honestly see from inside the office network, measured 2026-10-09:
//   GET http://bina-ds:3081/v1/health?deep=1   -> 200, no token: harness, uptime_s, sessions, live_model
//   GET http://machine:8080/api/overview       -> 200: every container of this compose project
//   GET/POST http://notifications:8977/api/…   -> 200: post a notice, and read back what was posted
// Listing or driving a session needs the agent Bearer token (`/v1/sessions` answers 401 — the token
// lives root-only inside bina-ds), so this workflow OBSERVES and REPORTS; waking a session is the
// job of a door that may hold that token (rap-002's open note) and of the self-update helper, which
// resumes whoever was mid-turn after a restart.
//
// It is credential-free on purpose, like Raphael's other scans: internal service URLs only, so the
// n8n encryption-key drift cannot touch it.
@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Pulse every 5 min":{"main":[[{"node":"Pulse","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"id":"AppTagRaphael0001","name":"app:raphael"},{"id":"RoleTagRaphaelInfra","name":"role:infra"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: null,
    /*__n8n__*/ staticData: null,
    id: 'raphaelPulse00001',
    name: 'Raphael — office pulse',
    active: true,
    isArchived: false,
    tags: ['app:raphael', 'role:infra'],
    settings: { errorWorkflow: 'errorHandler01', executionOrder: 'v1' },
})
export class RaphaelPulseWorkflow {
    @node({
        id: 'raphael-pulse-sched-01',
        name: 'Pulse every 5 min',
        type: 'n8n-nodes-base.scheduleTrigger',
        version: 1.2,
        position: [0, 0],
    })
    Schedule = {
        rule: { interval: [{ field: 'minutes', minutesInterval: 5 }] },
    };

    @node({
        id: 'raphael-pulse-01',
        name: 'Pulse',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [220, 0],
    })
    Pulse = {
        jsCode: `const HEALTH = 'http://bina-ds:3081/v1/health?deep=1';
const MACHINE = 'http://machine:8080/api/overview';
const NOTIFY = 'http://notifications:8977/api/notifications';
const REPEAT_MS = 30 * 60 * 1000;   // say the same thing at most every 30 minutes

const get = async (url) => {
  try {
    return { ok: true, body: await this.helpers.httpRequest({ method: 'GET', url, json: true, timeout: 15000 }) };
  } catch (e) {
    return { ok: false, error: String(e && e.message ? e.message : e) };
  }
};

const problems = [];
const fingerprint = {};

// 1. The agent's harness: the thing that does the work. Uptime + how many sessions the office holds.
const health = await get(HEALTH);
if (!health.ok) {
  problems.push({ id: 'pulse-agent-unreachable', level: 'error',
    title: 'הדופק: הסוכן של הלשכה לא עונה',
    body: 'בקשת התקינות ל-bina-ds נכשלה: ' + health.error });
} else {
  const h = health.body || {};
  fingerprint.harness = h.harness; fingerprint.uptime_s = h.uptime_s; fingerprint.sessions = h.sessions;
  if (h.ok !== true || h.harness !== 'up') {
    problems.push({ id: 'pulse-agent-down', level: 'error',
      title: 'הדופק: ההרנס של הסוכן אינו למעלה',
      body: 'harness=' + String(h.harness) + ' ok=' + String(h.ok) + ' — הסוכן לא יבצע עבודה עד שיחזור.' });
  }
}

// 2. The containers of THIS office (the machine app knows the compose project from its own labels).
const machine = await get(MACHINE);
if (!machine.ok) {
  problems.push({ id: 'pulse-machine-unreachable', level: 'warn',
    title: 'הדופק: אפליקציית המכונה לא עונה',
    body: 'לא הצלחתי לקרוא את מצב הקונטיינרים: ' + machine.error });
} else {
  // ONE IS SAID AS ONE (DGO-526) — see the note in raphaelMachine00001; a Code node cannot import.
  const num = n => Number(n).toLocaleString('he-IL');
  const one = (n, single, many) => (Number(n) === 1 ? single : num(n) + ' ' + many);
const containers = Array.isArray(machine.body && machine.body.containers) ? machine.body.containers : [];
  const self = containers.find((c) => ((c.labels || {})['com.docker.compose.service']) === 'machine');
  const project = self ? (self.labels || {})['com.docker.compose.project'] : null;
  const ours = project ? containers.filter((c) => ((c.labels || {})['com.docker.compose.project']) === project) : containers;
  const unhealthy = ours.filter((c) => c.health === 'unhealthy').map((c) => c.name || c.raw_name);
  fingerprint.containers = ours.length;
  if (unhealthy.length) {
    problems.push({ id: 'pulse-containers-unhealthy', level: 'warn',
      title: 'הדופק: ' + one(unhealthy.length, 'קונטיינר אחד לא בריא', 'קונטיינרים לא בריאים'),
      body: unhealthy.join(', ') });
  }
}

// 3. Say each problem once per window: read back what was already posted, and stay quiet if the same
//    sentence is there. A notice that repeats every five minutes stops being read.
if (problems.length) {
  const posted = await get(NOTIFY + '?limit=40');
  const recent = new Set();
  if (posted.ok) {
    const rows = Array.isArray(posted.body && posted.body.notifications) ? posted.body.notifications : [];
    const cutoff = Date.now() / 1000 - REPEAT_MS / 1000;
    for (const row of rows) {
      // The field is an ISO STRING ("2026-10-09T15:36:12.759454+00:00"). Number() on it is NaN, so
      // a numeric comparison was false for EVERY row, the recent set stayed empty, and the dedupe
      // suppressed
      // nothing at all — measured 2026-10-10: one unhealthy container re-woke the agent every tick for
      // hours, and the notice row was re-posted each time (the notification centre upserts by
      // (source, source_id), which also clears the read flag). Parse the date, and check BOTH spellings
      // of the same condition — the notice is source_id = problem.id, its wake is 'wake-' + problem.id.
      const created = Date.parse(row.created_at || 0) / 1000;
      if (Number.isFinite(created) && created >= cutoff && row.source_id) recent.add(row.source_id);
    }
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
                level: problem.level, link: '/#/m/machine' } });
    } catch (e) { /* the finding is still returned below */ }
    // ...and ASK THE AGENT TO ACT ON IT. An outside container holds no agent token by design, so the
    // wake travels as a notice whose source_id starts with "wake"; the agent's own timer reads it,
    // wakes the session that holds an active goal, and marks it read (apps/bina-ds/pulse.sh, the wake
    // queue). This is the last link of the owner's ask: if the automations found something weird, they
    // trigger Raphael from within the automations.
    try {
      await this.helpers.httpRequest({ method: 'POST', url: NOTIFY, json: true, timeout: 15000,
        body: { source: 'raphael', source_id: 'wake-' + problem.id,
                title: 'בקשת השכמה מהאוטומציה: ' + problem.title,
                body: problem.body, level: 'warn' } });
    } catch (e) { /* a failed wake request never hides the finding */ }
  }
}

const agent = health.ok ? ((health.body || {}).sessions ?? null) : null;

// The pulse CLOSES the notices it opened (DGO-537, from-azaria §56): an alarm nobody closes keeps
// asking, and a condition that has passed left its notice — and its wake copy — on the owner's list
// and in the wake queue for ever. Only this pulse's own ids (pulse-*) and their wake- copies are
// touched, and only while unread; a problem this run DOES see is never closed by it.
const liveIds = new Set(problems.map((p) => p.id));
const cleared = [];
const openRows = await get(NOTIFY + '?limit=60');
const noticeRows = (openRows.ok && Array.isArray(openRows.body && openRows.body.notifications))
  ? openRows.body.notifications : [];
for (const row of noticeRows) {
  const sid = String((row && row.source_id) || '');
  const own = sid.startsWith('pulse-') ? sid
            : (sid.startsWith('wake-pulse-') ? sid.slice('wake-'.length) : '');
  if (!own || !row.id || row.is_read) continue;
  if (liveIds.has(own)) continue;
  try {
    await this.helpers.httpRequest({ method: 'POST', url: NOTIFY + '/' + row.id + '/read',
                                     json: true, timeout: 10000 });
    cleared.push(sid);
  } catch (e) { /* a notice left open is not a failure of the pulse */ }
}
return [{ json: { pulse: true, at: new Date().toISOString(), problems: problems.length,
                  sent: problems.map((p) => p.id), cleared: cleared, agent_sessions: agent, ...fingerprint } }];
`,
    };

    @links()
    defineRouting() {
        this.Schedule.out(0).to(this.Pulse.in(0));
    }
}
