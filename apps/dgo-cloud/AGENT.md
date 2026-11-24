# Operating «DGO Cloud» (the `dgo-cloud` app)

DGO Cloud is DGO net's first product (DGO-1893; the front's plan: ai/context/dgo-net.md): a person signs up (Google or
e-mail), pays ₪99 a month by Cardcom, and gets a managed DGO of their own on a Hostinger server within seconds, with
₪24 a month of AI credit in the office's LLM router (DeepSeek, Claude, OpenAI). Bina manages every client server from
the admin screen («ניהול»). It runs on vps1, the herd's storefront. Notes and decisions: `.claude/notes/DGO-1893.md`;
the providers' API facts: `research_notes/DGO cloud 2026-11-15/`.

## The pieces (one stdlib-Python service, one SQLite file in `data/dgo-cloud/state`, the volume `dgo_cloud_data` until DGO-2019)

| module | what | the outside party |
|---|---|---|
| `accounts.py` | DGO net accounts: scrypt passwords, Google sign-in, httpOnly session (hash kept), one-time links, VIEW AS | Google OAuth |
| `billing.py` + `cardcom.py` | the plan, checkout on Cardcom's hosted page (`ChargeAndCreateToken` + tax invoice), monthly token charges, top-ups, cancel | Cardcom v11 |
| `provision.py` + `hostinger.py` | the warm pool, the claim, the nodes' door (hello/poll/jobs/progress), ACME httpreq | Hostinger API |
| `node/` | what runs ON a client server: `bootstrap.sh` (Hostinger's post-install, one boot token), `install.sh` (served at `/node/install.sh`), `agent.py` (dials out; closed verb list) | — |
| `router.py` + `prices.json` | the LLM router: OpenAI- and Anthropic-shaped doors, metering from the provider's own usage, the wallet | DeepSeek, OpenAI, Anthropic |
| `dnsd.py` | the authoritative name server of `cloud.digital-office.co.il` (node names, ACME TXT) | — |
| `server.py` | the doors, the scheduler (pool tick every 20 s; billing every 5 min) | — |

## Money rules (do not loosen)

- A payment counts only when `GetLpResult` says so (ResponseCode 0, the transaction's 0, the amount and ReturnValue
  ours). The return page and the webhook are triggers. `verify()` acts once (`UPDATE … WHERE status='pending'`).
- A renewal's idempotency key is `sub<id>-p<period>`; Cardcom refuses a repeat (608) and returns the first result.
- Agorot everywhere. Plan credit expires at the period's end; a top-up never does; usage takes the plan's first.
- Nothing is deleted: a subscription ends, a node is released (its row stays), a key is revoked. Every write is audited.

## Who may do what

- A buyer: their own account, subscription, server (password shown ONCE, then a new one by job), wallet, invoices.
- An admin (`accounts.admin`, seeded from `DGOCLOUD_ADMINS`): everything in «ניהול», VIEW AS a client (read-only, 60
  min, audited), wallet adjustments (±₪1,000), refunds, the pool, the price FX/margin, jobs to any node.
- A node: only through its secret, only for itself (ACME for its own name only), only the verbs in `agent.py`.
- The router: a `dk_` key; refused (402) when its account is not paying or the wallet is at zero.

## The doors

`GET /api/me|dashboard|usage`, `POST /api/auth/signup|login|logout|forgot|reset|verify`, `GET /api/auth/google`,
`POST /api/account`, `/api/checkout {plan}`, `/api/topup {amount}`, `/api/pay/<id>/verify`, `/api/subscription/cancel|
resume`, `/api/my-dgo/reveal|new-password`; admin under `/api/admin/…` (overview, accounts, account/<id>[/status|credit|
admin|cancel], nodes[/order], nodes/<id>/job|release|retry, node/<id>/jobs, pool, pricing, payments[/<id>/refund],
usage, audit, keys/new, view-as). Nodes: `/api/node/hello|poll|progress|job/<id>`, `/api/acme/present|cleanup`.
Cardcom: `/api/cardcom/webhook`. Router: any path on `dgo-llm.<domain>` (or `/llm/…`): `/v1/chat/completions`,
`/chat/completions`, `/v1/messages`, `/v1/models`. Browser writes carry `X-DGO: 1`.

## Running it

- A laptop: `.claude/launch.json` → `dgo-cloud-dev` (Cardcom and the provider simulated) and
  `python3 apps/dgo-cloud/tests/sim_node.py ci-artifacts/dgo-cloud-dev` for a stand-in server running the real agent.
- Tests, each file in its own process (the two HTTP ones start `server.py` in-process, once, with their own
  environment): `for t in test_cloud test_router_http test_site_http; do python3 -m unittest apps/dgo-cloud/tests/$t.py;
  done`.
- vps1 (.env): `DGOCLOUD_ADMINS`, `CARDCOM_TERMINAL`/`CARDCOM_API_NAME`(/`CARDCOM_API_PASSWORD`), `HOSTINGER_API_TOKEN`,
  `DGOCLOUD_OPS_KEY` (Bina's ops public key — on vps1, its root's `/root/.ssh/id_ed25519.pub`), `DGOCLOUD_SSH_FROM`
  (Bina's addresses), `DGOCLOUD_ZONE_IP` (vps1's, 93.184.216.5), `DGOCLOUD_DNS_BIND=93.184.216.5` (the public address
  itself, NOT 0.0.0.0: systemd-resolved holds 127.0.0.53:53 and 127.0.0.54:53 there, measured 2026-11-15) +
  `DGOCLOUD_DNS_HOST_PORT=53` (and, once vps1 applies the host baseline, `HOST_DOORS_UDP_EXTRA=53`,
  `HOST_DOORS_TCP_EXTRA=53`), the three provider keys, and Google's client with the redirect
  `https://dgo-cloud.<domain>/api/auth/google/callback`. Then `bbox app enable dgo-cloud`, and
  `bbox dgo-cloud admin <email>` for the first admin if the office's mail cannot deliver the verify link.

## Traps

- `CARDCOM_SIMULATE=1` answers every payment locally — never on a live office (the admin overview says so in red).
- `DGOCLOUD_ZONE=sslip.io` gives each server `<a-b-c-d>.sslip.io` with no zone of ours — a laptop's and a test's path,
  NOT a sale's: sslip.io is not on the Public Suffix List (checked 2026-11-15), so its Let's Encrypt quota (50 new
  certificates a week) is shared with every sslip.io user in the world and an order can be refused any day. A paying
  client gets a name in our delegated zone (DGO-1894, the two InterNIC records).
- A node's first install takes 10–20 minutes; the pool absorbs it. Three failed installs in six hours stop buying until
  a person looks («שרתים»).
- `prices.json` dates its prices; a provider's price change is a commit there. The admin changes only FX and margin.
