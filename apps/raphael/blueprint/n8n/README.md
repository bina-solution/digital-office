# Raphael's scheduled scans (n8n)

Each `*.workflow.ts` here is one hard-coded scan: a Schedule Trigger → probe an engine → a verdict →
on an anomaly, post a notice (`notifications`, source `raphael`) and trigger a Raphael agent session
(bina-ds `/v1/sessions`). They are tagged `app:raphael`, carry `errorWorkflow: errorHandler01`, and
import/remove with the app's enable/disable (and with `./bbox raphael start`).

Planned, one per awareness aspect (the agent's matching scan skill drives the same engine when he is
triggered — see `apps/bina-ds/harness/profile/agent-presets/raphael/skills/`):

| workflow (to add) | probes | anomaly |
|---|---|---|
| `raphaelMachine00001` | `machine:8080/api/overview` | unhealthy containers, load/mem over cap |
| `raphaelData00001` | `data-management:8080/api/inventory` | UNCLAIMED / at_risk data |
| `raphaelGates00001` | the gate suite (via a runner) | a gate newly red |
| `raphaelAppear00001` | `sites-render:8981/score` per installed app | a beauty regression |
| `raphaelPentest00001` | `computers:8977/api/computers/<id>/audit` (rap-009) | an error/warn host finding |

**Shipped so far** (validated with `./bbox n8n code validate`, gate-clean — not in G47/G45):
`raphaelMachine00001` (machine health → notice on an unhealthy container of this office's project) and
`raphaelData00001` (data layer → notice on an at-risk / unclaimed store). `raphaelGates00001` and
`raphaelAppear00001` follow the same Schedule→Code pattern.

`./bbox raphael start` imports whatever ships here into the office's n8n. It restarts n8n (a
production touch), so on a live office it runs on the owner's yes; on a fresh instance it also needs
the n8n-owner sign-in (own-031).
