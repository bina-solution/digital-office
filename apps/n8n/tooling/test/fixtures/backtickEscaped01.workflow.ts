// FIXTURE (DGO-584) — backtickRaw01.workflow.ts with its backticks escaped: ONE well-formed
// literal, the whole body reaches n8n. Never pushed: this directory is no app's blueprint.
import { workflow, node, links } from '@n8n-as-code/transformer';

@workflow({
    id: 'backtickEscaped01',
    name: 'backtick escaped (fixture)',
    active: false,
    settings: { executionOrder: 'v1' },
})
export class BacktickEscapedFixtureWorkflow {
    @node({
        id: 'fixture-trigger-01',
        name: 'Manual Trigger',
        type: 'n8n-nodes-base.manualTrigger',
        version: 1,
        position: [0, 0],
    })
    ManualTrigger = {};

    @node({
        id: 'fixture-shape-01',
        name: 'Shape',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [220, 0],
    })
    Shape = {
        jsCode: `// Each item answers the caller as ({"by": "<agent>", "n": <count>}) — the n8n item
// envelope, closed by \`}\` on its own line.
const rows = $input.all().map((i) => i.json);
return rows.map((r) => ({ json: { by: r.by, n: rows.length } }));
`,
    };

    @node({
        id: 'fixture-count-01',
        name: 'Count',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [440, 0],
    })
    Count = {
        jsCode: `return [{ json: { count: $input.all().length } }];
`,
    };

    @links()
    defineRouting() {
        this.ManualTrigger.out(0).to(this.Shape.in(0));
        this.Shape.out(0).to(this.Count.in(0));
    }
}
