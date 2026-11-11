# Operating `security` — «אבטחה»

Who reaches this office and what it calls, with a fail2ban built in. Base app (layer 2), every office
runs it: two containers from one image — `security` (API + screen, behind the sign-in) and
`security-sensor` (host network, NET_ADMIN + NET_RAW only, no listener; over `security_sensor`).

## Read
```bash
curl -s http://security:8995/api/summary?hours=24 | jq .kpi          # requests, addresses, bans, outbound
curl -s http://security:8995/api/inbound?hours=24 | jq '.rows[:5]'    # one row per address: place, network, apps, users
curl -s http://security:8995/api/inbound/<ip>                         # one address: hits, sign-ins, bans, totals
curl -s http://security:8995/api/outbound?hours=24 | jq '.rows[:5]'   # by destination: names, who called, declared?
curl -s http://security:8995/api/egress | jq '.undeclared'             # what went out that no app declared
curl -s http://security:8995/api/signins?hours=168 | jq .keys         # SSH keys that signed in, by label
curl -s http://security:8995/api/links?hours=24                       # what other offices opened here
curl -s http://security:8995/api/bans                                 # mode, jails, active, watching
curl -s http://security:8995/api/network | jq .facts                  # interfaces, listeners, router, sensor
curl -s http://security:8995/api/host/overview                        # the machine
curl -s http://security:8995/api/herd                                 # every linked office's summary
```
Over a link: `./bbox remote <office> security /api/summary`; from the shell the same reads:
`./bbox security summary|inbound|outbound [hours]`, `ip <address>`, `bans|herd`.

## Change (refused over a link unless SECURITY_REMOTE_CONTROL=1)
```bash
H='content-type: application/json'; S=http://security:8995/api
curl -s -X POST $S/bans -H "$H" -d '{"ip":"203.0.113.9","minutes":60,"reason":"…"}'
curl -s -X DELETE $S/bans/203.0.113.9
curl -s -X POST $S/rules -H "$H" -d '{"kind":"allow","value":"203.0.113.0/24","note":"…"}'
curl -s -X POST $S/rules -H "$H" -d '{"kind":"block","value":"203.0.113.50"}'
curl -s -X PUT $S/settings -H "$H" -d '{"mode":"enforce"}'
```

## How it decides
* Jails (jails.py): scan (12 failures or 3 probe paths / 10 min on public/unrouted/door), auth (5 failed
  sign-ins / 15 min), sshd (5 / 10 min). Ban 1 h × 4 per repeat, max 7 days.
* Never banned: private ranges, the office's own addresses, linked offices, any address that signed in
  successfully in 30 days, the allow list.
* **A 404 on `/` or a favicon on a name nobody routes is not a scan** (DGO-1597) — that is every browser
  and checker asking a hostname it never saw (Exampleu: four AWS Oregon addresses). Any other path, and
  every failing status but 404 on `/`, counts.
* **One ssh attempt is one event**: sshd's two lines name one socket (address+port); the second is
  dropped, a sign-in on that connection never is. Rows say why (`how`: `invalid-user`, the method, `preauth`).
* **A cap is not a total.** `/api/inbound/<ip>` shows 300/100/100, `totals` says what it holds;
  `/api/signins` lists every failure (`failed`: `src`+`reason`) and ssh ADDRESS (`sources`, not keys),
  each bounded with its real number beside it.
* **The certificate is visible**: `/.well-known/acme-challenge/…` is kind `acme`, never scan evidence,
  and traefik's ACME lines (its only trace: it writes no access line) are events; a failing renewal
  is a notice.
* Mode: a new office starts in **observe** — bans recorded as «היה נחסם», nothing dropped. The owner
  switches to **enforce** on the screen (Bans → מעבר לאכיפה); an agent never flips it.
* Enforcement: the sensor's own nftables table `inet dgo_security` (prerouting, priority -300: before
  docker's NAT, ufw and the edge). Elements carry their own timeout; `nft list table inet dgo_security`
  shows it.
* Volume: that table counts bytes per PUBLIC address (`vol_out4/6`, `vol_in4/6`, idle 2 h), apart so a
  refusal never touches the ban chains; the outbound rows' `bytes_out`/`bytes_in` are these counters.
* Who called: a flow's app is named WHEN IT IS INGESTED (`flow.who`) from a 15-minute memory of the
  engine's address map; a one-off container by its image (`image:node`). Names: DNS answers and TLS
  server names off the wire, a reverse name (PTR) once a day for an address nobody named.
* Routers: the sensor probes the default gateway (`role: gateway`) and every address in
  `SECURITY_ROUTER_HINTS` (`role: declared`). On a Mac/Windows office the gateway is the VM host
  itself — the screen calls it the virtual router; the declared one is the router at home.
* Egress (egress.py, DGO-1561): `egress.yaml` says where each app may go (a compose service; `@host`;
  `@unnamed` or `image:` for a container known by address or image); `SECURITY_EGRESS_EXTRA` adds an office's
  own. A row to a stranger no app was declared for is `declared: false` (`kpi.out_undeclared`), judged by the
  RESOLVER's answers in the window (`name.via = 'dns'`), never a TLS name or a PTR, which the client or the
  address owner chooses. Marked only, nothing dropped. A file that does not load is `health.egress`, never
  «no rules». A new outbound need is a line in egress.yaml with why.

## Traps
* The edge must keep `--accesslog=true` (stdout). Common-log and JSON both parse.
* On a laptop the office runs in a VM (Lima, WSL): the edge sees the VM's NAT, not the client, so inbound
  addresses there are the host's; vps1 sees real ones.
* GeoIP: DB-IP lite fetched on first start into `/data/geo` (CC BY 4.0); `SECURITY_GEO=country|off`. The
  edition held is the month in the file's name (`*.mmdb.edition`), never its build date (DB-IP stamps
  one a month early; judging by it re-fetched 60 MB per restart).
* The sensor reads `/var/log` and `/root/.ssh` read-only. No host root mount (S19).
* Self-test: `python3 platform-base/security/tests/selftest.py` (the image runs it in its build).
