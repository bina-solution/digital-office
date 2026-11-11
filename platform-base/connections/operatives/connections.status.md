---
id: connections.status
title: Which connections the office has, and whether each one answers
title_he: מצב החיבורים של הלשכה
when:
  - מה מצב החיבורים
  - אילו חיבורים יש בלשכה
  - איזה חיבור לא עובד
  - החיבורים עובדים
  - מה חסר בחיבורים
  - connections status
inputs: {id: "one connection's id, when the person named one; empty for all"}
reaches_people: false
check: 'how many are healthy, each one that is degraded, needs action or is missing with its detail — or that the connections app did not answer'
---
1. Every connection, each probed live now:
   - here: `curl -s http://connections:8990/api/connections`
   - linked: `./bbox remote <office> connections /api/connections`
   It answers `{connections: [...], summary: {total, by_status, install_blockers}}`. Read only `id`, `title_he`, `status`, `detail` and `required` from each row. NEVER repeat `masked`, `clear` or any value: those are the office's secrets and settings.
2. A named connection: `curl -s -X POST http://connections:8990/api/conn/<id>/test` re-probes that one now and answers `{status, detail, ok}`.
3. Answer: the totals from `summary.by_status`, then one line for each row that is `degraded`, `needs_action` or `missing`, with its `detail`, and the ids in `summary.install_blockers` (required and not working). `unset` is a row nobody here uses: count it, do not list it.
4. A 503 says the vault is unreadable: say that, it is not "no connections". No answer means the connections app is down: say so.
5. This only reads. Setting or connecting one is the owner's, on the connections screen.
