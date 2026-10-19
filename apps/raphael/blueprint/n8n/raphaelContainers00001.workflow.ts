import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : Raphael — container scan
// Nodes   : 2  |  Connections: 1
//
// Schedule (every 15 min)
//    -> Scan containers
// </workflow-map>
//
// Raphael's container-awareness scan (rap-007): read the machine overview, take a status inventory of
// THIS office's compose project, and post ONE notice (source "raphael") when a container has CRASHED
// or is crash-looping (status "dead" / "restarting") — the states the machine scan (rap-006) does not
// cover, which flags only running-but-unhealthy. The two are complementary and never double-notice.
// Credential-free (internal service URLs only), so the n8n encryption-key drift does not touch it. It
// scans and REPORTS a suggested action; it never restarts or removes a container itself. The project is
// self-identified from the `machine` container's own compose-project label, so it does not hardcode a
// deployment name and never counts a neighbour stack sharing the engine.

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Schedule":{"main":[[{"node":"Scan containers","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"id":"AppTagRaphael0001","name":"app:raphael"},{"id":"RoleTagRaphaelInfra","name":"role:infra"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: null,
    /*__n8n__*/ staticData: null,
    id: 'raphaelContainers00001',
    name: 'Raphael — container scan',
    active: true,
    isArchived: false,
    tags: ['app:raphael', 'role:infra'],
    settings: { errorWorkflow: 'errorHandler01', executionOrder: 'v1' },
})
export class RaphaelContainerScanWorkflow {
    @node({
        id: 'raphael-cont-sched-01',
        name: 'Schedule',
        type: 'n8n-nodes-base.scheduleTrigger',
        version: 1.2,
        position: [0, 0],
    })
    Schedule = {
        rule: { interval: [{ field: 'minutes', minutesInterval: 15 }] },
    };

    @node({
        id: 'raphael-scan-cont-01',
        name: 'Scan containers',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [220, 0],
    })
    ScanContainers = {
        jsCode: `const OV = 'http://machine:8080/api/overview';
const NOTIFY = 'http://notifications:8977/api/notifications';
let ov;
try {
  ov = await this.helpers.httpRequest({ method: 'GET', url: OV, json: true, timeout: 20000 });
} catch (e) {
  return [{ json: { scan: 'containers', ok: false, error: 'machine overview unreachable: ' + String(e) } }];
}
const conts = Array.isArray(ov.containers) ? ov.containers : [];
const self = conts.find(c => ((c.labels || {})['com.docker.compose.service']) === 'machine');
const project = self ? (self.labels || {})['com.docker.compose.project'] : null;
const ours = project ? conts.filter(c => ((c.labels || {})['com.docker.compose.project']) === project) : conts;
// Inventory by status, so the finding carries the whole picture even when nothing is wrong.
const inventory = {};
for (const c of ours) { const s = c.status || 'unknown'; inventory[s] = (inventory[s] || 0) + 1; }
// Anomaly = a container that has crashed or is crash-looping. rap-006 already covers running-but-
// unhealthy, so this one deliberately does NOT re-flag that — the two scans do not double-notice.
const crashed = ours.filter(c => c.status === 'dead' || c.status === 'restarting')
  .map(c => (c.name || c.raw_name) + ' (' + c.status + ')');
if (crashed.length) {
  try {
    await this.helpers.httpRequest({
      method: 'POST', url: NOTIFY, json: true, timeout: 20000,
      body: { source: 'raphael', source_id: 'scan-containers-crashed',
        title: 'רפאל: ' + crashed.length + ' קונטיינרים קרסו או בלולאת ריסטארט',
        body: crashed.join(', ') + ' — מוצע לבדוק את היומנים ולשקול recreate', level: 'warn' },
    });
  } catch (e) { /* the notice is best-effort; the finding is still returned */ }
}
return [{ json: { scan: 'containers', ok: crashed.length === 0, project: project,
  total: ours.length, inventory: inventory, crashed: crashed.length, containers: crashed } }];
`,
    };

    @links()
    defineRouting() {
        this.Schedule.out(0).to(this.ScanContainers.in(0));
    }
}
