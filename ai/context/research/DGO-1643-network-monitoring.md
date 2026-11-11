# DGO-1643 — network monitoring for the security app: inbound, outbound, a graph per app and per peer

Research item from the product review of Exampleu's office (`bina-261109-vjlwcr`, MEET-28). Read
2026-11-09. Our own side is measured on the HP that day; every third-party claim carries the URL it
was read from, and anything I did not verify is marked as such.

**Recommendation: do not add a monitoring app. The security app already *is* the monitor — it has
the one thing no external tool can attribute — and what it lacks is a graph layer, not a collector.**
If an external lens is still wanted for the machine itself, the only one worth a container is
**Netdata** (GPL-3.0 agent, ~150 MiB, per-cgroup/per-app charts), with its telemetry off and no
Netdata Cloud. ntopng is rejected on our topology, Zeek+Arkime on container count, nethogs-style and
the router tools on what they cannot answer.

---

## 1. What "monitoring" means here (and what is measured today)

The office is not a flat network. Traffic enters through one edge (traefik), leaves through the WSL
host's NAT, and the interesting question is never "which IP talked to which IP" — it is **which of OUR
apps talked to which peer, how much, and when**. That attribution cannot be reconstructed from
packets: it comes from the engine's own address map and from the edge's own log.

Measured on the HP, 2026-11-09 16:37 UTC (`curl http://security:8995/api/...`):

| | value |
|---|---|
| `summary?hours=24` | 2,733 requests, 4 client addresses, 29 failures, **962 outbound destinations**, **13,455 outbound connections** |
| one `outbound` row (live) | `93.184.216.10` · `api.deepseek.com` · **app `bina-ds`** · 3.43 GB out / 324 MB in · 1,290 flows · `US`, `Seattle`, `AS16509 Amazon` |
| one `inbound` row (live) | `172.18.0.1` · 2,135 hits · apps `console`, `forward-auth`, `browser42-caddy`, `dgo-port80` · «המחשב הזה, דרך המנוע» |
| the two containers | `security` **0.51 % CPU, 59 MiB** (limit 320 MiB) · `security-sensor` **3.14 %, 20 MiB** (160 MiB) |
| its store | SQLite, `security.db` 1.3 MB + 4.2 MB WAL, `/data` 136 MB (GeoIP DB-IP lite included) |

So the data plan already answers three of the four questions the item asks — **inbound, outbound,
and per peer** — with bytes, at 60 days of retention (`platform-base/security/store.py`, `RETENTION`),
for about 80 MiB and 3.6 % of a core on a 2-core/8 GB box. The per-app key is `flow.who`, written at
ingestion from the engine's address map (`app.py` `_who`, DGO-1597), and it is also what makes a
"graph per app" possible without a tap.

**What is missing is a graph.** The screen (`platform-base/security/static/index.html`) draws tables
and a world map (`/api/map`); it has no chart component. And `flow`/`vol` are keyed by **day**
(`PRIMARY KEY(day, …)`), so even if a chart were drawn it could only step per day — no hour, no
"what happened at 14:20".

## 2. The field, judged on the three things the item asks for

Footprint column = what the tool documents or requires, against our measured 80 MiB / 3.6 % baseline.

| tool | licence (read 2026-11-09) | one container under our compiler? | footprint on 2-core/8 GB | per app / per peer graphs |
|---|---|---|---|---|
| **ntopng** | **GPL-3.0** ([LICENSE](https://github.com/ntop/ntopng/blob/dev/LICENSE)); the fuller editions are commercial (ntop's own pricing page) | *No, not on this topology.* It needs to **see the traffic** — an interface in promiscuous mode, or a NetFlow/sFlow feed. Our flows live on the WSL host's interfaces; a bridge-attached container sees only its own. That means a second host-network container with `NET_ADMIN`/`NET_RAW` next to `security-sensor`, i.e. a second place that can put an interface in promiscuous mode on the office's machine | the heaviest of the field: a C++ engine plus an internal Redis and RRD history, documented for a few GB of RAM on real networks; it would be the largest resident process on the box | **yes** — per host, per application (nDPI), with RRD graphs. But "application" is the *protocol* (TLS, Google, Telegram), not `bina-ds`; it cannot know which of our containers opened the flow |
| **Netdata** | agent **GPL-3.0** ([LICENSE](https://github.com/netdata/netdata/blob/master/LICENSE)); **the UI is closed-source, delivered from a CDN**, and Cloud is closed ([README](https://github.com/netdata/netdata/blob/master/README.md)) | **yes** — one container, and it reads the host/containers through cgroups + the docker socket, no tap needed. It is a metrics agent, not a flow collector | documented "**~5 % CPU and 150 MiB RAM** by default; **<1 % CPU and ~100 MiB** with ML and alerts off" — a real number from the project, and it is the lightest of the field after ours | **per app: yes** (a container's cgroup *is* our app: `n8n-hp`, `browser42-browser-hp`), with per-second history and tiered retention. **Per peer: no** — interfaces and connections per PID, not "which office / which host". And its screen is a CDN-loaded UI, which is a second internet dependency for the office's own console — and an owner's-policy question (`DGO-1407`'s spirit: no outside service in the path) |
| **Zeek + dashboards** (Arkime/Elastic) | Zeek **BSD-3-Clause** ([COPYING](https://github.com/zeek/zeek/blob/master/COPYING)); Arkime **Apache-2.0** ([LICENSE](https://github.com/arkime/arkime/blob/main/LICENSE)) | **no** — Zeek needs a tap (same problem as ntopng), writes connection logs to disk, and Arkime stores its index in Elasticsearch/OpenSearch: **three or more containers**, a JVM, and gigabytes of disk | the only option here that would not fit the box comfortably: a capture engine, a JVM search cluster and their disks; on 8 GB it competes with the office itself | the most forensic detail of the field (every connection, full pcap) — and the least answer to "which app": it knows IPs and protocols, so an analyst would have to join it to our own map by hand |
| **nethogs-style per-process** (nethogs GPL-2.0, [COPYING](https://github.com/raboof/nethogs/blob/main/COPYING)) | GPL-2.0 | no: it reads `/proc/net/*` on the host and wants root; not a service, a TUI | ~ a few MB | **per process only, live**: no history, no store, no graph, no inbound side, and in containers the process is the proxy, not the app |
| **OPNsense / pfSense** | OPNsense **BSD-2-Clause** ([LICENSE](https://github.com/opnsense/core/blob/master/LICENSE)); *pfSense CE's licence not verified here* | not a container at all: they ARE the router (FreeBSD). Their value is per-rule/per-interface traffic graphs (OPNsense's Reporting, pfSense's `Insight`), plus an ntopng package on both | n/a for us | the graph-per-rule idea is exactly right — but it requires the office to **be** behind that router. Our office is a Docker host on a home/café network; the "router" is somebody else's box and the WSL NAT |
| *(frontier, no container)* | — | — | — | **the security app itself**: 80 MiB, 3.6 %, and the only source that knows the app name and the peer office |

## 3. Recommendation

**One recommendation: keep collection where it is and give the security app a graph layer; add no
container.** Reasons, in order of weight:

1. **The attribution is ours and cannot be bought.** `flow.who` names the app; `trust.label` and
   `link_items()` name the peer (this machine, a linked office, a cloud); `name`/`addr` give reverse
   names, GeoIP, ASN and org. ntopng would add DPI labels ("Google"), Netdata would add cgroup
   totals; neither would say "`bina-ds` → `api.deepseek.com`, 3.4 GB today".
2. **One more privileged sniffer is a security regression.** `security-sensor` is the office's one
   `NET_ADMIN`/`NET_RAW` container (S19: no host root mount, no listener). A second privileged
   container to feed ntopng doubles that surface for data we already have.
3. **The gap is a table and 40 lines of SVG.** Two changes, both inside `platform-base/security`:
   - a bucket table `graph(ts_hour, kind, key, bytes_out, bytes_in, n)` written by the same loops
     that already write `flow`/`vol` — hourly, 14 days retention, then rolled into the existing daily
     rows;
   - `/api/graphs?hours=24&by=app|peer` returning series, and one SVG sparkline/bar component on the
     screen, in the palette (`theme-tokens.css`, gate G27), beside the existing tables.
   That is smaller than the app's own `hostinfo.py`, and it keeps the console's one door.
4. **If the office wants an infrastructure lens as well** (CPU, memory, disk, per-container
   throughput, alerts on the machine), the one app worth a container is **Netdata** — one container,
   `netdata/netdata`, host `/proc` + docker socket read-only, `--disable-telemetry` (or
   `.opt-out-from-anonymous-statistics`) in its compose, no Cloud token, and its dashboard framed as
   a tile. It answers a *different* question (the machine, not the peers) and it must not replace the
   security screen's own data.

### What the graph would show, and where the data comes from

```
nftables counters (sensor)  ──vol(day, ip)──┐
edge access log (traefik)   ──hit(ts)───────┤
engine address map + flows  ──flow(day, who)┴──► hourly buckets ──► /api/graphs ──► the screen
                                                (new, 14 d)                        (SVG, tokens)
```

Per app: `flow.who` × `bytes_out/bytes_in`; per peer: `dst` (named by `name`, placed by `addr`).
Inbound per app: `hit.app` (already 3 days at event granularity, `hit_day` for longer). All of it
exists; the bucket table only changes the resolution.

### Sequence, if this becomes an item

1. `graph` table + writer (one migration on start, like the other `CREATE TABLE IF NOT EXISTS`).
2. `/api/graphs` with `by=app|peer`, `hours` ≤ 24×14, and the same `window()` guard as the other
   endpoints.
3. The screen: one chart per tab (inbound, outbound, apps, peers) + "top 5 moved" line; no new
   dependency, no chart library.
4. Only then, optionally, the Netdata container behind a feature switch in `platform.state.yaml`.

## 4. What was NOT verified (so nobody builds on a guess)

* ntopng's and Zeek's documented RAM figures were **not** read from their docs in this session (the
  guide URLs moved); the footprint column for them is engineering estimate against our measured
  baseline, and must be measured in a staging container before any adoption.
* pfSense CE's licence was not read; OPNsense's was (BSD-2-Clause).
* Netdata's UI-from-CDN behaviour is stated by its own README ("Closed-source but free… delivered via
  CDN"); whether a fully local UI is possible in the current agent was not verified — it is the
  first thing to check if that path is ever taken.

## Sources (read 2026-11-09)

* ntopng licence, GPL-3.0 — https://github.com/ntop/ntopng/blob/dev/LICENSE
* Netdata agent licence (GPL-3.0), resource figures, UI/Cloud closed, telemetry opt-out —
  https://github.com/netdata/netdata/blob/master/README.md
* Zeek licence (BSD-3-Clause, LBNL) — https://github.com/zeek/zeek/blob/master/COPYING
* Arkime licence (Apache-2.0) — https://github.com/arkime/arkime/blob/main/LICENSE
* nethogs licence (GPL-2.0) — https://github.com/raboof/nethogs/blob/main/COPYING
* OPNsense licence (BSD-2-Clause) — https://github.com/opnsense/core/blob/master/LICENSE
* In-repo: `platform-base/security/store.py` (the schema and `RETENTION`), `platform-base/security/app.py`
  (`/api/summary`, `/api/inbound`, `/api/outbound`, `_who`, `/api/map`, `spans`),
  `platform-base/security/AGENT.md` (the sensor, the counters, the design of who-calls-whom).
