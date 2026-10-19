# n8n main: heap/CPU degradation from zombie waiting drain shells (2026-08-24)

## Symptom
n8n.localhost (editor UI + /rest, served by main) unusably slow while console.localhost answered
in milliseconds. Measured on 2026-08-24: `/healthz` inside the container 0.6–9.5s; `/rest/settings`
via traefik 2.1–7.2s; main CPU 131% of an (by-then) uncapped allowance; RSS 3.0GB against a
3072MB heap cap → constant aggressive GC = multi-second event-loop freezes.

## Root cause (measured, not theorized)
**11 stale `waiting` executions of `indoxV2BaseDrain01` holding 290MB of execution_data blobs**
(largest 45MB; oldest waiting since 10:07 UTC). Main's wait-tracker re-loads and re-parses every
waiting execution's full blob on every poll cycle — same mechanic as the 2026-08-18 253MB-blob
OOM crashloop. The shells accumulated because operator `mode=all` webhook fires bypass the
drain's Solo Check by design, and the session's supervisor was blind to running drains for hours
(its alive-query matched the workflow by display name, which no longer contains "BaseDrain") —
so it kept firing new full drains on top of live ones. Each fire left a Poll-Progress wait shell
that never terminated (its batch cohort was consumed by later drains, so its exit condition
never fired).

Secondary finding, same day: a half-failed `bbox n8n push` under load left `indoxV2ActionsGDoc01`
updated but **unpublished** (`active=false`, `activeVersionId` NULL) — every gdoc dispatch died
with "Workflow is not active and cannot be executed" until it was re-published with the
reconciler's publish-model UPDATE. Push-tool API-key probe flakiness under the same load caused
mint collisions ("There is already an entry with this name") until the two stale
`user_api_keys` rows (`bbox-n8n`, `bbox-push-app`) were deleted (owner-approved).

## Fixes applied 2026-08-24
- Killed the 10 superseded shells (status→crashed, blobs deleted), kept the live drain.
- Clean main restart afterwards: RSS 3.0GB → 1.1GB; `/rest/settings` 0.21–0.46s.
- Supervisor alive-query fixed to match `workflowId='indoxV2BaseDrain01'` (never display name).
- Dedicated `n8n webhook` processor container deployed; internal bus URLs moved to it
  (webhook container carried 134 enqueues vs main's 49 in the first 15 minutes).
- Main: CPU cap removed (+`cpu_shares: 2048`), heap 2048→3072 (cgroup 4G = ×1.3 floor).

## Not implemented (owner: no added complexity) — recorded for later
1. **Drain wait cap**: Poll Progress waits forever; a bounded retry count (exit + log after N
   polls) would make stacked shells impossible regardless of who fires drains.
2. **Heap watchdog**: alert (or restart) when main RSS crosses ~2.5GB — today's degradation
   never self-heals; docker only restarts on process death, not on unhealthy/slow.
3. Optional scheduled off-peak graceful restart of main.

## Ops notes
- A slow-but-alive main is invisible to `restart: unless-stopped`. Check `waiting` executions
  and their blob sizes FIRST when the UI degrades:
  `SELECT count(*), pg_size_pretty(sum(octet_length(d.data))::bigint) FROM execution_entity e
   LEFT JOIN execution_data d ON d."executionId"=e.id WHERE e.status='waiting';`
- Stale editor tabs re-save old graphs over pushes and hold dead push websockets — close them
  after deploys.
