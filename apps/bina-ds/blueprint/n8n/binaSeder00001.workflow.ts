import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : Bina — the three סדרים (shacharit / mincha / arvit)
// Nodes   : 2  |  Connections: 1
//
// Schedule (07:00 · 13:00 · 21:00, Asia/Jerusalem)
//    -> Start the cycle
// </workflow-map>
//
// WHY IT LIVES HERE. The owner, 2026-10-14: «use n8n automation blueprinted inside bina-ds app. And
// remove pulse and all of this mod bullshit, keep clean and official like dsreleased». The office's
// clock is therefore DECLARED together with the app it drives — apps/bina-ds/blueprint/n8n/ — and
// imported by `./bbox n8n push bina-ds`. The container-side shell loop that used to do this
// (apps/bina-ds/pulse.sh) is deleted: nothing in the container polls, sleeps or wakes on a timer.
//
// WHAT IT CALLS. `POST http://bina-ds:3081/v1/seder/<cycle>` — a door the app owns, ONE verb wide:
// open a session, hand it the fixed brief of that cycle. It carries NO credential, and that is the
// design: the agent's Bearer token can list, read and drive every conversation, and n8n must not hold
// it. The door can do one narrow thing — start a cycle — and the caller has to say WHICH CLOCK it is
// (`{"by": "bina-seder"}`, the body this node sends): a cycle is a full autonomous session that spends
// the day's budget, so an accidental POST is refused in words rather than answered with one.
// The bound on a day is the DAY'S BUDGET, not a slot count — a day may hold several cycles. (Corrected
// 2026-10-14: this file used to claim a once-per-cycle guard the door never had, and that claim is how
// two probe requests came to open two real cycles.) To exercise the door and open nothing:
// `POST …/v1/seder/<cycle>` with `{"dry_run": true}`.
//
// THE CLOCK'S ZONE IS THE WORKFLOW'S, NOT THE INSTANCE'S (2026-11-02). The Clock node's crons below
// are read in `settings.timezone`; without it n8n reads them in GENERIC_TIMEZONE, which defaults to
// UTC (`${GENERIC_TIMEZONE:-UTC}`, apps/n8n/docker-compose.yml). Measured on vps1 (Etc/UTC)
// 11-01..11-02: the fires came at 09:00, 15:00 and 23:00 in Jerusalem, two hours late, and under
// summer time (UTC+3) the 10:00 and 00:00 fires fall outside the node's windows and open nothing
// (issues/vps1-automations-of-a-disabled-app-fail-every-three-minutes.yaml, root cause 4).
//
// WHAT A CYCLE THEN IS: the `seder` skill inside the session — eight named steps, a ₪1 day, a bounded
// round, and one הקפצה to the owner at the end. This workflow starts it and says nothing else.
@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Clock 07:00 / 13:00 / 21:00":{"main":[[{"node":"Start the cycle","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"id":"AppTagBina0001","name":"app:bina-ds"},{"id":"RoleTagBinaInfra","name":"role:infra"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: null,
    /*__n8n__*/ staticData: null,
    id: 'binaSeder00001',
    name: 'Bina — three cycles (סדרים)',
    active: true,
    isArchived: false,
    tags: ['app:bina-ds', 'role:infra'],
    settings: { errorWorkflow: 'errorHandler01', executionOrder: 'v1', timezone: 'Asia/Jerusalem' },
})
export class BinaSederWorkflow {
    @node({
        id: 'bina-seder-clock-01',
        name: 'Clock 07:00 / 13:00 / 21:00',
        type: 'n8n-nodes-base.scheduleTrigger',
        version: 1.2,
        position: [0, 0],
    })
    Clock = {
        rule: {
            interval: [
                { field: 'cronExpression', expression: '0 7 * * *' },
                { field: 'cronExpression', expression: '0 13 * * *' },
                { field: 'cronExpression', expression: '0 21 * * *' },
            ],
        },
    };

    @node({
        id: 'bina-seder-start-01',
        name: 'Start the cycle',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [220, 0],
    })
    Start = {
        jsCode: `// One clock, three cycles: the hour names the cycle. A window rather than an exact minute, so a
// trigger n8n delivered a little late (or an office that was restarting at :00) still starts the
// right cycle; the door refuses a cycle that already started today, so a wrong guess opens nothing.
const SEDER = 'http://bina-ds:3081/v1/seder/';
// WHEN THE CLOCK FIRED, NOT WHEN THIS NODE HAPPENED TO RUN (corrected 2026-10-14 18:1x). The hour used
// to come from a fresh new Date() taken inside this node, and n8n runs a scheduled workflow's nodes
// when a worker picks the execution up — not the instant the trigger fired. Measured that evening on
// the one-off day run: the arvit trigger fired at 17:18:00.156 and this node ran at 17:23, five minutes
// later behind a busy queue, so the window matched nothing, the node answered «no cycle is due» and the
// execution still read SUCCESS — a scheduled cycle skipped with nobody told. The Schedule Trigger's own
// item carries the fire time (timestamp, with the offset of the workflow's zone), so the cycle is now named by the
// clock's fact rather than by the queue's luck.
const first = $input.all()[0];
const fired = (first && first.json && first.json.timestamp) ? first.json.timestamp : new Date().toISOString();
const now = new Date(fired);
const hour = Number(new Intl.DateTimeFormat('en-GB', {
  timeZone: 'Asia/Jerusalem', hour: '2-digit', hour12: false,
}).format(now));

let cycle = null;
if (hour >= 5 && hour < 10) cycle = 'shacharit';
else if (hour >= 11 && hour < 18) cycle = 'mincha';
else if (hour >= 19 && hour < 24) cycle = 'arvit';

// A FIRE THAT NAMES NO CYCLE IS SAID OUT LOUD. This branch used to return quietly, which is how a
// skipped cycle could read as a green execution; the notice centre is told now, exactly like a refusal.
if (cycle === null) {
  await this.helpers.httpRequest({
    method: 'POST', url: 'http://notifications:8977/api/notifications', json: true, timeout: 15000,
    body: {
      source: 'bina-ds', source_id: 'seder-clock', level: 'warning',
      title: 'השעון ירה בשעה שאין בה סדר',
      body: 'הירייה נקראה בשעה ' + hour + ' (נקראת מהזמן שבו השעון ירה) — לא נפתח מחזור.',
      link: '/#/m/bina',
    },
  }).catch(() => {});
  return [{ json: { started: false, reason: 'no cycle is due at hour ' + hour, fired } }];
}

// A FAILED FIRE IS NEVER SILENT (corrected 2026-10-14, same day). This used to carry NO try/catch on
// purpose — "a door that is not there must FAIL this execution, so the office's shared error workflow
// says so out loud" — and that intent was right only while the mechanism existed. Measured today on
// this office: its n8n has no workflow with the id the settings name (errorHandler01), so a thrown
// error reached NOBODY — the run went red in n8n and the owner was told nothing, which is exactly the
// outcome the old comment promised could not happen. The notice centre is the office's own door and
// does not depend on an instance's error-workflow id, so the failure is reported there AND rethrown:
// the execution still fails loudly, and the owner hears about it.
let answer;
try {
  answer = await this.helpers.httpRequest({
    method: 'POST', url: SEDER + cycle, json: true, timeout: 30000,
    // WHICH CLOCK THIS IS. The door refuses a caller that does not name it (the body carries
    // {"by": "bina-seder"}), because a
    // cycle spends the day's budget and a stray POST must read as a refusal, not as a session.
    // \`fired\` is the clock's own time in the workflow's zone, sent only when the trigger gave one: the
    // door names the cycle's brief and record by it, not by its container's zone (vps1's is UTC;
    // arvit was titled 19:00, 2026-11-02). Without it the door reads its own clock, as before.
    body: (first && first.json && first.json.timestamp) ? { by: 'bina-seder', fired } : { by: 'bina-seder' },
  });
} catch (e) {
  await this.helpers.httpRequest({
    method: 'POST', url: 'http://notifications:8977/api/notifications', json: true, timeout: 15000,
    body: {
      source: 'bina-ds', source_id: 'seder-clock', level: 'error',
      title: 'השעון ירה ' + cycle + ' — הסדר לא נפתח',
      body: ('הפעלת הסדר ' + cycle + ' נכשלה: '
        + String((e && (e.description || e.message)) || e)).slice(0, 300),
      link: '/#/m/bina',
    },
  }).catch(() => {});
  throw e;
}
const out = { cycle, hour, ...(answer || {}) };

// A REFUSAL IS NOT A SILENT SUCCESS. Measured 2026-10-14: the 07:00 fire was refused and the
// execution still read "success", so nobody knew the morning cycle had not happened. Any refusal the
// door sends goes to the notice centre, with the door's own words for it.
if (out.started === false) {
  await this.helpers.httpRequest({
    method: 'POST', url: 'http://notifications:8977/api/notifications', json: true, timeout: 15000,
    body: {
      source: 'bina-ds', source_id: 'seder-clock', level: 'warning',
      title: 'השעון ירה ' + cycle + ' — הדלת סירבה',
      body: 'הסדר ' + cycle + ' לא נפתח. ' + (out.reason || out.error || ''),
      link: out.link || '/#/m/bina',
    },
  }).catch(() => {});
}
return [{ json: out }];`,
    };
}
