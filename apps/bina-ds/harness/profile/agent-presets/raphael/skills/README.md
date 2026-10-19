# רפאל's skills

Raphael's scanning/awareness skills ship here, one directory per skill (`<name>/SKILL.md`), and are
loaded by the `skill-filesystem` row of this preset's `agent.cordis.yml` (its `customSkillDirs` points
at this folder). Each skill orchestrates an existing engine and turns its output into healing
suggestions — it does not re-implement the engine.

Planned (one per awareness aspect — see Plane DGO items rap-003…rap-009, parent req-001 / DGO-461):

| skill (to build) | aspect | engine it drives |
|---|---|---|
| `scan-appearance` | UI/flows beauty | beautiful-score via sites-render, flow-qa, live-ui-map, + an LLM read of the screenshots |
| `scan-code` | code base | run-gates.py (the gate suite) + the lints |
| `scan-access` | access/security | computers audit, route-claim / sso gates, exposure checks (per OS) |
| `scan-machines` | machines | machine /api/overview, any-concurrency, `bbox status` |
| `scan-containers` | containers | machine + autoheal, scoped to our compose project |
| `scan-data` | data layer | data-management /api/inventory, data-volumes gate |
| `pentest` | authorized hardness check (rap-009) | **owner-armed only** — the office's own read-only engines, against the owner's own DGO; `pentest/pentest.py --armed` |

Until these exist, Raphael reads the engines directly. The automations that run the scans on a
schedule and trigger Raphael live under `apps/raphael/blueprint/n8n/` (rap-002).
