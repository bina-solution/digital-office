import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : Raphael — data-layer scan
// Nodes   : 2  |  Connections: 1
//
// Schedule (every 6 h)
//    -> Scan data
// </workflow-map>
//
// Raphael's data-layer scan (rap-008): ask data-management for the office's data inventory and, if any
// store is AT RISK (unclaimed by any app, or not backed up), post ONE notice (source "raphael"). Every
// valuable datum should sit in the standard place, declared and backed up; this names the ones that do
// not. Credential-free (internal URL only), so the n8n key drift does not touch it. Six-hourly, because
// the inventory sweep is heavy (~110 s). It scans and REPORTS; it never moves or deletes data.

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Schedule":{"main":[[{"node":"Scan data","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"id":"AppTagRaphael0001","name":"app:raphael"},{"id":"RoleTagRaphaelInfra","name":"role:infra"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: null,
    /*__n8n__*/ staticData: null,
    id: 'raphaelData00001',
    name: 'Raphael — data-layer scan',
    active: true,
    isArchived: false,
    tags: ['app:raphael', 'role:infra'],
    settings: { errorWorkflow: 'errorHandler01', executionOrder: 'v1' },
})
export class RaphaelDataScanWorkflow {
    @node({
        id: 'raphael-data-sched-01',
        name: 'Schedule',
        type: 'n8n-nodes-base.scheduleTrigger',
        version: 1.2,
        position: [0, 0],
    })
    Schedule = {
        rule: { interval: [{ field: 'hours', hoursInterval: 6 }] },
    };

    @node({
        id: 'raphael-scan-data-01',
        name: 'Scan data',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [220, 0],
    })
    ScanData = {
        jsCode: `const INV = 'http://data-management:8080/api/inventory?wait=true';
const NOTIFY = 'http://notifications:8977/api/notifications';
let inv;
try {
  inv = await this.helpers.httpRequest({ method: 'GET', url: INV, json: true, timeout: 180000 });
} catch (e) {
  return [{ json: { scan: 'data', ok: false, error: 'data-management inventory unreachable: ' + String(e) } }];
}
if (inv.state && inv.state !== 'ready') {
  return [{ json: { scan: 'data', ok: false, error: 'inventory not ready: ' + inv.state } }];
}
const sum = inv.summary || {};
const atRisk = Array.isArray(sum.at_risk) ? sum.at_risk : [];
if (atRisk.length) {
  const names = atRisk.map(a => (a.volume || a.name) + ' (' + (a.why || 'at risk') + ')');
  try {
    await this.helpers.httpRequest({
      method: 'POST', url: NOTIFY, json: true, timeout: 20000,
      body: { source: 'raphael', source_id: 'scan-data-at-risk',
        title: 'רפאל: ' + atRisk.length + ' נפחי נתונים בסיכון', body: names.join(', '), level: 'warn' },
    });
  } catch (e) { /* the notice is best-effort; the finding is still returned */ }
}
return [{ json: { scan: 'data', ok: atRisk.length === 0, at_risk: atRisk.length, volumes: sum.volumes, databases: sum.databases } }];
`,
    };

    @links()
    defineRouting() {
        this.Schedule.out(0).to(this.ScanData.in(0));
    }
}
