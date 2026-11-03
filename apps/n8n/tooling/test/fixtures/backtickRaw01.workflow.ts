// FIXTURE (DGO-584) — the shape that lost a Code node's body in production: a RAW backtick inside
// jsCode, in a comment. Never pushed: this directory is no app's blueprint. Its twin
// backtickEscaped01.workflow.ts is the same file with the backticks escaped.
import { workflow, node, links } from '@n8n-as-code/transformer';

@workflow({
    id: 'backtickRaw01',
    name: 'backtick raw (fixture)',
    active: false,
    settings: { executionOrder: 'v1' },
})
export class BacktickRawFixtureWorkflow {
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
// envelope, closed by `}` on its own line.
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
