# any-concurrency — release plan

## Vision
Automation "god mode": one screen to observe, investigate, and act on every
async process across the deployment (n8n, traefik, docker, wa, apitools).
Every meaningful state lives in the URL so any view is shareable.

## Surface (preserved + new)
- Top: live/follow badges, source health, summary stats.
- Controls: window, source pills, service/status/search/group/incident toggles, expand/collapse.
- Concurrency strip (stacked area, log toggle).
- Overview brush with marker ticks for incidents.
- Gantt:
  - Hierarchy: source → prefix → service → task → parallel-packed lanes.
  - Title-on-dark-band inside wide spans (Bitwig).
  - Source icons in the gutter (Kdenlive).
  - Pinned-span gold outline + crosshair (Mixxx playhead).
  - Bottom-right zoom cluster (MuseScore).
- Task detail drawer (right side, `#sel=<spanId>`):
  - Span identity, times, full meta.
  - For n8n spans: deep link to executions UI, status/mode/retry chain,
    execution_metadata key/value table, workflow node summary.

## URL state (hash-based, debounced)
Round-trippable keys:
`h` hours · `src` active sources · `svc` · `st` status · `q` search ·
`hs` hideShort · `gs` groupBySrc · `g` group mode · `ly` logY ·
`im` incidents · `f` follow · `t0` `t1` (only when paused) ·
`cg` collapsedGroups · `xs` expandedServices · `xt` expandedTasks ·
`sel` selected span id · `pin` pinned span id.

## Backend additions
- `GET /api/span/{id}` — single span lookup across all stores.
- `GET /api/n8n/exec/{id}` — execution_entity row + execution_metadata
  + workflow node summary (name + type) + computed deep link URL.
- `/healthz` exposes `n8n_url` so the UI builds links without env.

## Verification
Playwright loads the app, asserts URL-state restoration, opens a span,
verifies the n8n deep link, exercises pin/copy-link and the zoom cluster.
