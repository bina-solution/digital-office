import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : Bina — one-off day cycle (2026-10-14): mincha · arvit · shacharit in ninety minutes
// Nodes   : 2  |  Connections: 1
//
// Schedule (one-off, 2026-10-14 only): 16:48 mincha · 17:18 arvit · 17:48 shacharit, Asia/Jerusalem
//    -> Start the cycle
// </workflow-map>
//
// WHY IT EXISTS. The owner, 2026-10-14 16:18: «תפעיל מנחה ערבית שחרית (מחזור שלם, תזמן במרחקים של 30
// דק) … בעצם יבצע מחזור יום שלם עם תקציב של 5 שקל בשעה וחצי הקרובות (מבלי שתפעיל ידנית הכל צריך להיות
// מתוזמן כדי לבחון איך יום טבעי יתפקד וניתוח לעומק לאחר מכן של היום התפוקה והעלויות)». So the day is
// compressed into ninety minutes and left to the office's own machinery: three scheduled fires, no
// human hand, the door opened with the day's ₪5.00 grant.
//
// THE HOURS MOVED ONCE, by 14 minutes, and why: the three fires were first set for 16:51/17:21/17:51,
// and the routine's own folder («שגרת עזריה» — the workspace every cycle is now filed under) had to be
// deployed — a rebuild of bina-ds that restarts the door. Landing that restart in the middle of the
// run would have cost a cycle, so the run was moved to 16:48/17:18/17:48 and the deploy went first.
//
// ONE-OFF BY CONSTRUCTION. Each cron expression names the day (`14 10` = 14 October), so nothing here
// fires tomorrow: this is a test artifact that is removed once its three cycles have run. The office's
// real clock — `binaSeder00001`, 07:00 · 13:00 · 21:00 — is untouched by it.
//
// WHICH CYCLE, WITHOUT A CLOCK HAND. The three fires land inside the clock's *mincha* window (the real
// clock names a cycle by the hour, and all three times are mincha hours), so this workflow names the
// cycles itself: a small table of the three times, matched to the minute, with a three-minute
// tolerance so a fire n8n delivered a little late still runs the right cycle.
//
// A CYCLE IS A FULL AUTONOMOUS SESSION that spends the day's budget, so the door refuses a caller that
// does not name the clock (`{"by": "bina-seder"}`) — the same name the office's real clock sends. A
// refused or unreachable door is reported to the notice centre AND rethrown (see the code node): a
// scheduled cycle that did not happen is the one outcome a clock must never produce silently.
@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Clock 16:48 / 17:18 / 17:48 (2026-10-14)":{"main":[[{"node":"Start the cycle","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"id":"AppTagBina0001","name":"app:bina-ds"},{"id":"RoleTagBinaInfra","name":"role:infra"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: null,
    /*__n8n__*/ staticData: null,
    id: 'binaDayRun00001',
    name: 'Bina — one-off day cycle (2026-10-14)',
    active: true,
    isArchived: false,
    tags: ['app:bina-ds', 'role:infra'],
    settings: { errorWorkflow: 'errorHandler01', executionOrder: 'v1' },
})
export class BinaDayRunWorkflow {
    @node({
        id: 'bina-dayrun-clock-01',
        name: 'Clock 16:48 / 17:18 / 17:48 (2026-10-14)',
        type: 'n8n-nodes-base.scheduleTrigger',
        version: 1.2,
        position: [0, 0],
    })
    Clock = {
        rule: {
            interval: [
                { field: 'cronExpression', expression: '48 16 14 10 *' },
                { field: 'cronExpression', expression: '18 17 14 10 *' },
                { field: 'cronExpression', expression: '48 17 14 10 *' },
            ],
        },
    };

    @node({
        id: 'bina-dayrun-start-01',
        name: 'Start the cycle',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [220, 0],
    })
    Start = {
        jsCode: `// Which cycle is due: by the minute, with a three-minute tolerance, so a fire delivered a little
// late still runs the right one. Outside the three windows this node says so and opens nothing.
const PLAN = { '16:48': 'mincha', '17:18': 'arvit', '17:48': 'shacharit' };
const SEDER = 'http://bina-ds:3081/v1/seder/';
const now = new Date();
const hhmm = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'Asia/Jerusalem', hour: '2-digit', minute: '2-digit', hour12: false,
}).format(now);
function toMinutes(s) { return Number(s.slice(0, 2)) * 60 + Number(s.slice(3)); }

let cycle = PLAN[hhmm] || null;
if (!cycle) {
  for (const key of Object.keys(PLAN)) {
    if (Math.abs(toMinutes(key) - toMinutes(hhmm)) <= 3) { cycle = PLAN[key]; break; }
  }
}
if (!cycle) {
  return [{ json: { started: false, reason: 'no cycle is due at ' + hhmm } }];
}

// A FAILED FIRE IS NEVER SILENT (same shape as the office's real clock): the notice centre hears about
// it, and the error is rethrown so the execution fails loudly in n8n as well.
let answer;
try {
  answer = await this.helpers.httpRequest({
    method: 'POST', url: SEDER + cycle, json: true, timeout: 30000,
    body: { by: 'bina-seder' },
  });
} catch (e) {
  await this.helpers.httpRequest({
    method: 'POST', url: 'http://notifications:8977/api/notifications', json: true, timeout: 15000,
    body: {
      source: 'bina-ds', source_id: 'seder-dayrun', level: 'error',
      title: 'הרצת יום מדומה: הסדר ' + cycle + ' לא נפתח',
      body: ('הפעלת הסדר ' + cycle + ' נכשלה: '
        + String((e && (e.description || e.message)) || e)).slice(0, 300),
      link: '/#/m/bina',
    },
  }).catch(() => {});
  throw e;
}
return [{ json: { cycle, at: hhmm, ...(answer || {}) } }];`,
    };
}
