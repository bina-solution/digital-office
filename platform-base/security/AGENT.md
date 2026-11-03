# Operating `security` — «אבטחה»

Who reaches this office and what it calls, with a fail2ban built in. Base app (layer 2): every office
runs it. Two containers from one image: `security` (API + screen, behind the office's sign-in) and
`security-sensor` (host network, NET_ADMIN + NET_RAW only, no listener; talks through the
`security_sensor` volume).

## Read
```bash
curl -s http://security:8995/api/summary?hours=24 | jq .kpi          # requests, addresses, bans, outbound
curl -s http://security:8995/api/inbound?hours=24 | jq '.rows[:5]'    # by address: place, network, apps, users
curl -s http://security:8995/api/inbound/<ip>                         # one address: hits, sign-ins, bans
curl -s http://security:8995/api/outbound?hours=24 | jq '.rows[:5]'   # by destination: names, who called
curl -s http://security:8995/api/signins?hours=168 | jq .keys         # SSH keys that signed in, by label
curl -s http://security:8995/api/links?hours=24                       # what other offices opened here
curl -s http://security:8995/api/bans                                 # mode, jails, active, watching
curl -s http://security:8995/api/network | jq .facts                  # interfaces, listeners, router, sensor
curl -s http://security:8995/api/host/overview                        # the machine (Computers draws it)
curl -s http://security:8995/api/herd                                 # every linked office's summary
```
Over a link: `./bbox remote <office> security /api/summary`. From the shell, the same reads:
`./bbox security summary|inbound|outbound [hours]`, `./bbox security ip <address>`, `./bbox security bans|herd`.

## Change (refused when the request crossed a link, unless that office set SECURITY_REMOTE_CONTROL=1)
```bash
curl -s -X POST http://security:8995/api/bans -H 'content-type: application/json' -d '{"ip":"203.0.113.9","minutes":60,"reason":"…"}'
curl -s -X DELETE http://security:8995/api/bans/203.0.113.9
curl -s -X POST http://security:8995/api/rules -H 'content-type: application/json' -d '{"kind":"allow","value":"203.0.113.0/24","note":"…"}'
curl -s -X POST http://security:8995/api/rules -H 'content-type: application/json' -d '{"kind":"block","value":"203.0.113.50"}'
curl -s -X PUT http://security:8995/api/settings -H 'content-type: application/json' -d '{"mode":"enforce"}'
```

## How it decides
* Jails (jails.py): scan (12 failures or 3 probe paths in 10 min on public/unrouted/door), auth (5
  failed sign-ins in 15 min), sshd (5 failures in 10 min). Ban 1 h × 4 per repeat, max 7 days.
* Never banned: private ranges, the office's own addresses, linked offices, any address that signed
  in successfully in 30 days, the allow list.
* Mode: a new office starts in **observe** — bans are recorded as «היה נחסם», nothing is dropped.
  The owner switches to **enforce** on the screen (Bans → מעבר לאכיפה). Moving to enforce is a
  decision with facts on the screen; an agent does not flip it on its own.
* Enforcement: the sensor's own nftables table `inet dgo_security` (prerouting priority -300: before
  docker's NAT, ufw and the edge). Elements carry their own timeout. `nft list table inet dgo_security`
  on the machine shows it.
* Volume: the same table counts bytes per PUBLIC address in four dynamic sets (`vol_out4/6`,
  `vol_in4/6`, two hours of idle and an element expires), applied as a separate script so a refusal
  never touches the ban chains. The outbound rows' `bytes_out`/`bytes_in` are these counters.
* Who called: a flow's app is named WHEN IT IS INGESTED (`flow.who`) from a 15-minute memory of the
  engine's address map; a one-off container (no compose name) is named by its image (`node`, …).
  Names: DNS answers and TLS server names off the wire, and a reverse name (PTR) once a day for an
  address nobody named.
* Routers: the sensor probes the default gateway (`role: gateway`) and every address in
  `SECURITY_ROUTER_HINTS` (`role: declared`). On a Mac/Windows office the gateway is the VM host
  itself — the screen calls it the virtual router; the declared one is the router at home.

## Traps
* The edge must keep `--accesslog=true` (stdout). Common-log and JSON formats both parse.
* On a laptop the office runs in a VM (Lima, WSL): the edge sees the VM's NAT, not the client, so
  inbound addresses there are the host's. vps1 sees real addresses.
* GeoIP: DB-IP lite fetched on first start into `/data/geo` (CC BY 4.0). `SECURITY_GEO=country|off`.
  The edition held is the month in the name it was fetched under (`*.mmdb.edition`), never the file's
  build date — DB-IP stamps an edition a month early, and judging by that date re-fetched 60 MB on
  every restart (424 MB in a day, 2026-10-21).
* The sensor reads `/var/log` and `/root/.ssh` read-only. No host root mount (S19).
* Self-test: `python3 platform-base/security/tests/selftest.py` (the image runs it in its build).
