import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : Raphael — machine scan
// Nodes   : 2  |  Connections: 1
//
// Schedule (every 15 min)
//    -> Scan machine
// </workflow-map>
//
// Raphael's first scheduled scan: read the machine overview, and if any container of THIS office's
// compose project is unhealthy, post ONE notice to the notification centre (source "raphael"). It is
// credential-free on purpose — it calls internal service URLs only (no OAuth creds), so the n8n
// encryption-key drift does not touch it. It scans and REPORTS; it never acts on the system. The
// project is self-identified from the `machine` container's own compose-project label, so it does not
// hardcode a deployment name and never counts a neighbour stack sharing the engine.

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Schedule":{"main":[[{"node":"Scan machine","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"id":"AppTagRaphael0001","name":"app:raphael"},{"id":"RoleTagRaphaelInfra","name":"role:infra"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: null,
    /*__n8n__*/ staticData: null,
    id: 'raphaelMachine00001',
    name: 'Raphael — machine scan',
    active: true,
    isArchived: false,
    tags: ['app:raphael', 'role:infra'],
    settings: { errorWorkflow: 'errorHandler01', executionOrder: 'v1' },
})
export class RaphaelMachineScanWorkflow {
    @node({
        id: 'raphael-sched-01',
        name: 'Schedule',
        type: 'n8n-nodes-base.scheduleTrigger',
        version: 1.2,
        position: [0, 0],
    })
    Schedule = {
        rule: { interval: [{ field: 'minutes', minutesInterval: 15 }] },
    };

    @node({
        id: 'raphael-scan-machine-01',
        name: 'Scan machine',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [220, 0],
    })
    ScanMachine = {
        jsCode: `const OV = 'http://machine:8080/api/overview';
const NOTIFY = 'http://notifications:8977/api/notifications';
// ONE IS SAID AS ONE. «1 קונטיינרים לא בריאים» is what a count with a fixed plural says (DGO-526) —
// the same rule the mail screen already writes out: a count of one is its own sentence, and any other
// is the number as the office writes numbers, with the plural. n8n Code nodes cannot import, so the
// two lines live in each scan that names a count.
const num = n => Number(n).toLocaleString('he-IL');
const one = (n, single, many) => (Number(n) === 1 ? single : num(n) + ' ' + many);
let ov;
try {
  ov = await this.helpers.httpRequest({ method: 'GET', url: OV, json: true, timeout: 20000 });
} catch (e) {
  return [{ json: { scan: 'machine', ok: false, error: 'machine overview unreachable: ' + String(e) } }];
}
const conts = Array.isArray(ov.containers) ? ov.containers : [];
const self = conts.find(c => ((c.labels || {})['com.docker.compose.service']) === 'machine');
const project = self ? (self.labels || {})['com.docker.compose.project'] : null;
const ours = project ? conts.filter(c => ((c.labels || {})['com.docker.compose.project']) === project) : conts;
const bad = ours.filter(c => c.health === 'unhealthy').map(c => c.name || c.raw_name);
//: what this scan closed, if anything (so the closing is as visible as the opening)
let closed = null;
if (bad.length) {
  try {
    await this.helpers.httpRequest({
      method: 'POST', url: NOTIFY, json: true, timeout: 20000,
      body: { source: 'raphael', source_id: 'scan-machine-unhealthy',
        title: 'רפאל: ' + one(bad.length, 'קונטיינר אחד לא בריא', 'קונטיינרים לא בריאים'), body: bad.join(', '), level: 'warn' },
    });
  } catch (e) { /* the notice is best-effort; the finding is still returned */ }
} else {
  // CLEAN → close this scan's own notice if it is still open (DGO-537, from-azaria §56): an alarm
  // nobody closes keeps asking, and a scan that finds nothing left its old notice on the owner's
  // list for ever otherwise. Only THIS scan's id, and only while it is unread.
  try {
    const list = await this.helpers.httpRequest({ method: 'GET', url: NOTIFY + '?limit=60',
                                                  json: true, timeout: 15000 });
    const rows = Array.isArray(list && list.notifications) ? list.notifications : [];
    for (const row of rows) {
      if (row && row.source_id === 'scan-machine-unhealthy' && !row.is_read) {
        await this.helpers.httpRequest({ method: 'POST', url: NOTIFY + '/' + row.id + '/read',
                                         json: true, timeout: 10000 });
        closed = 'scan-machine-unhealthy';
      }
    }
  } catch (e) { /* a notice left open is not a failure of the scan */ }
}
return [{ json: { scan: 'machine', ok: bad.length === 0, project: project, unhealthy: bad.length, containers: bad, closed: closed } }];
`,
    };

    @links()
    defineRouting() {
        this.Schedule.out(0).to(this.ScanMachine.in(0));
    }
}
