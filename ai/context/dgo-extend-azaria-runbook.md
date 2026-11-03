# Runbook — what is left on the remote-office lane (עזריה, DGO-30/32), 2026-10-01

Written with file tools only: the session's shell is dead (`Error: spawn bash ENOENT` — every command,
mine and a fresh subagent's, fails before it runs). Nothing below has been executed since.

## State that is already true and verified

* `dgo` branch on GitHub is at `281409fd` (my two commits: `c23e1d2d` dgo-extend/serve plane,
  `281409fd` the agent CLI). vps1 was converged to `719537ab` with `dgo-extend` enabled — that was
  **before** these two commits, so vps1 still runs the older code.
* vps1's published ports work again (`console.staging.digital-office.co.il` → 302) after the
  `forward policy drop` fix, applied live; the fix is in `c23e1d2d` so the next converge keeps it.
* The Mac's tunnel `wg0` is up (ping from vps1's host to `10.79.2.1` answers, ~85 ms) and the link
  proxy listens on `10.79.2.1:3080`, `:3081`, `:8983` for `10.79.2.2` only.
* The Mac's `serve:` declaration is `{bina-ds: {port: 3080, agent_api_port: 3081, identity.to: akadmin},
  dgo-extend: {port: 8983}}` and `label: MacBook`.
* **The tile does not depend on the `bina-ds` restart.** The peer's route sends the app the authority
  it answers under (`Host: bina.localhost`, from the app's own `sso.default_host`) — measured: the
  nested console host answers nothing, `bina.localhost` answers 200. The declared extra authority
  (below) is what makes the OTHER shape work — passing the frame's own host through, which keeps
  server-emitted absolute URLs usable — and it lands with the next `bina-ds` recreate.

## Prepared, uncommitted (no shell in the session)

* `apps/bina-ds/docker-compose.yml`: `DSH_TRUSTED_HOSTS` gains a final
  `${BINA_DS_TRUSTED_HOSTS:-}` term, documented.
* `.env` (this office): `BINA_DS_TRUSTED_HOSTS=bina.console.staging.digital-office.co.il`
  — the nested host vps1's console frames this agent under.
* `.env.ex`: the same key as an empty template entry with the rule spelled out.
* To apply: `./bbox data backup` is not needed; the sequence is
  `./scripts/dc up -d --build bina-ds` **through `apps/bina-ds/self-update.sh`** (health gate +
  rollback), only while `uptime` reports load1 < 30 — it restarts this session's own container, so run
  it as the LAST action of a turn.

## Steps left, in order

1. **Converge vps1 on `281409fd`** (the commit carries the `serve:` plane and the handoff):
   `PUT /api/office/vps1` with `source.commit=281409fd`, then
   `POST /api/office/vps1/converge`. The `state` step now writes vps1's `serve:` block, `run`
   reconciles it into the nested-host router + the console tile + the authentik provider, and the
   `link` step hands the Mac's agent token into vps1's vault.
2. **Prove the tile**: `curl -kI https://bina.console.staging.digital-office.co.il/` → 302 (the router
   exists and this office's SSO guards it), and from a container on vps1
   `curl -H 'Host: bina.localhost' -H 'X-authentik-username: akadmin' http://10.79.2.1:3080/` → 200
   (the served app answers over the tunnel under the identity the edge writes).
3. **Prove the agent** (`DGO-32`'s acceptance): on vps1,
   `cd /root/deployment-hacohen && ./bbox agent list` → the Mac's session ids
   (`b9987618`, `7d332102`, `b2b527d3` were the ones measured on 2026-10-01).
4. Only then: the phase-3 gate's two live checks (`apps/dgo-extend/tests/phase3.py`,
   `c_live_tile` / `c_agent_list`) get their real probes and `bbox dgo test 3` goes 11/11.
   **Careful:** another lane is rewriting that file right now (it moved from `serve:` to a `remote:`
   projection model) — coordinate before touching it.
5. `bina-ds` self-update: **not needed** for the acceptance above. If it is run for another reason,
   only through `apps/bina-ds/self-update.sh`, and only when `uptime` says load1 < 30.

## Collision to respect

`apps/dgo-extend/{app.py,converge.py,linkproxy.py,tests/phase3.py}` plus new
`catalog.py/placement.py/projection.py/admission.py` are being edited by a second lane in the same
checkout (uncommitted, ~600 lines). A rebuild of the container from that tree produced a mismatched
image (`app.py` calling `linkproxy.write(control_bind=…)` before `linkproxy.py` had it → 500) — build
only from a committed, consistent revision, and never `git stash` on the shared tree.
