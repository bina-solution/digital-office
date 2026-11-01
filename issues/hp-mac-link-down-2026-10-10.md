# The HP↔MacBook link is down — investigation (2026-10-10, 20:25–20:55 local, from hp-laptop)

Owner's request (voice transcript, verbatim): *"Deeply investigate why uh, HP disconnected from the
Mac uh, DGO. Currently, it's disconnected. So I want to deep, deeply investigate and find a way to
contact um, Azaria from the Max VGO, or even if not, it should be reported as an issue that it
disconnected and the connection should be restored. You have permissions to run everything."*

Hub item: **lnk-024 = DGO-503** — http://console.localhost/#/m/project-pln/bina/projects/e13492c5-ae57-4c34-8cd2-85e4aa65bab9/issues/83b516fd-04e6-4ed6-a765-f7a88093bbb3 (also reachable as plane.console.localhost).

## Verdict in one paragraph

The HP's half of the pair is intact and listening; nothing on the HP stops a packet. Nothing arrives
because the MacBook's office is not dialing anybody: its pair record still dials the HP at
`192.168.16.102` (the HP has been `192.168.16.100` since the DHCP lease of 2026-10-08 11:52 — hub
lnk-017), and, independently, the MacBook's **second** link (to vps1) is dead too, which a wrong HP
address cannot cause. The Mac answered ping at 170–350 ms (its "asleep" signature, seen before on
2026-10-06); a Wake-on-LAN magic packet brought it to ~100 ms, but its tunnel still answers nothing
on the LAN and vps1 still has no route to it. Restoring the link needs an action **on the Mac**
(wake it and keep it awake, `./bbox run`, and make its record dial `.100` or run the moved-pair
finder). No channel to the Mac's agent עזריה works from here right now: all three go through the Mac.

## What was measured on the HP (all healthy)

| Fact | Measured | Means |
|---|---|---|
| WireGuard interface | `dgo-net-hp`: `wg4`, public key `OUBWvxLV…`, listening port 51830, peer `+0B1Hc…` (the Mac), AllowedIPs `10.79.4.2/32` | rendered correctly for a listener (no `Endpoint`, contract §A) |
| Listener on the machine | container `0.0.0.0:51830/udp`, published to the host `0.0.0.0:51830` (`ss -ulnp` in WSL) | the port is open on the HP |
| Firewall | Hyper-V rules `DigitalOffice-WG-hp` + `-Host`: Inbound Allow UDP 51830, enabled | a packet for 51830 is let in |
| WSL mode | `.wslconfig`: `networkingMode=mirrored`; `eth1` carries `192.168.16.100` | the LAN reaches the distro directly |
| Declared address | `.env`: `DGO_WG_ENDPOINT=192.168.16.100`, port 51830, bind 0.0.0.0 | `hooks/prepare` followed the lease (lnk-018 fixed) |
| Handshake | `latest-handshakes 0` (never), `transfer 0 B / 0 B`, `endpoints (none)` | not one valid WireGuard packet reached wg4 since the container was created |
| Since when | the interface was (re)created 2026-10-09 19:31:16Z, and again 2026-10-10 17:42:26Z (another session's `bbox run`) | no handshake in either life |
| Link verdict | `/data/peers/link.json`: `macbook ok:false hop:tunnel` «המנהרה אליה לא מעבירה תנועה…»; `dgo-link` logs every minute «nothing answers at 10.79.4.2:8983 (No route to host)» | the office reads it right: the tunnel is dead |
| Pair record | `/data/dgo/macbook.yaml`: slot 4, this side 1 (host), `dial: joiner` (the Mac dials), `endpoint: 192.168.16.102`, `port: 51830` | the Mac is told to dial an address the HP no longer holds |
| HP's lease | Wi-Fi `192.168.16.100`, obtained 2026-10-08 11:52:19, expires 2026-10-10 21:57:56 | the address moved once already; it may move again tonight |

## What was measured about the Mac (`192.168.16.103`, MAC `5C-13-AC-45-D7-1B`)

| Probe | Result | Means |
|---|---|---|
| ping ×6 (before) | 168–351 ms, avg 273 ms, TTL 64 | on a LAN this is the sleeping-Mac signature (2026-10-06 02:45: «the Mac is asleep — ping answers, handshake stale») |
| TCP 22/80/443/8080/8983/51830 | all closed/filtered | as the contract says: the Lima engine forwards 80/443 to loopback only |
| UDP 51830/51820/51999 | no ICMP port-unreachable (silent) | dropped, or nothing listening and stealth |
| **The HP dialing the Mac** (runtime `wg set wg4 peer … endpoint 192.168.16.103:51830`, then `:51820`, keepalive 5 s, 25 s each) | **1.59 KiB sent, 0 B received, handshake still 0** | the Mac's tunnel does not answer on the LAN on either port — either not forwarded by Lima (engine-guest) or the office is not up |
| Wake-on-LAN magic packet (broadcast :9, :7, directed) | ping fell to 16–226 ms, avg 108 ms within 25 s | the Mac woke (or its NIC left low power); still no handshake, still no vps1 route 4 minutes later |
| vps1's route to the Mac's chat `bina.macbook.console.staging.digital-office.co.il` | **404** (cert valid, no router); `drive.macbook…` no certificate | vps1 no longer holds the Mac's routes: the Mac↔vps1 tunnel is dead as well |
| `origin/mac-dgo` | last commit `bba447d8`, 2026-10-04 22:22 | the Mac's branch on GitHub has not moved in six days; the moved-pair finder (`d155d62b`, lnk-017's fix) is on `hp-dgo`/`dgo-stable` only |

## Root cause, as far as the HP can see it

1. **The pair dials the HP at a stale address** (lnk-017): the HP is the listener, the Mac dials
   `192.168.16.102:51830`, and the HP has been `.100` since 2026-10-08 11:52. The HP side corrected
   its declaration (`.env`) on the next `bbox run` (after lnk-018 was fixed) but a listener cannot
   tell the dialer; the fix for that is on the dialing side (`app.py` `look_for_peer` — the Mac
   scans its last known /24 and a WireGuard handshake identifies the HP), and it is not on the Mac's
   published branch.
2. **On top of that, the Mac office is not dialing anybody today**: its link to vps1 (a public,
   static address — no lease involved) is dead too, both of the Mac's links died together as on
   2026-10-06 (lnk-014: «BOTH of the MacBook's links stopped in the same second»). A sleeping Mac
   pauses its Lima guest; after a wake the guest may need `./bbox run` (lnk-003: `dgo-link` left in a
   dead namespace after `dgo-net` is recreated).

So two faults stack: even with the Mac awake and running, it would dial `.102`; and today it is not
running its tunnel at all.

## Reaching the Mac's עזריה — every channel checked

| Channel | State | Why |
|---|---|---|
| His chat through vps1 (`console.staging…/#/m/bina.macbook`, standalone `bina.macbook.console.staging…`) | 404 | vps1's route to the Mac is gone (Mac↔vps1 tunnel dead) |
| His tile on the HP console (`bina.macbook.console.localhost`) | down | needs the HP↔Mac tunnel |
| The Mac's git mirror `macbook-git` (`git-accounts.macbook:9004`) | 502 | same tunnel |
| A hub comment (Plane runs on the HP) | written on lnk-024 | he reads Plane only through a link; none is up |
| He writes INTO this session from the Mac's browser (browser42 `claude-cc-link`) | one-way, and needs the Mac office up | — |

None works from the HP right now. The item carries what has to happen on the Mac.

## What restores the link (on the Mac — the owner, or עזריה once the Mac is up)

1. Wake the Mac and keep it awake while the offices are meant to be linked (or allow Wake on Demand).
2. `./bbox engine status` → `./bbox run`. Proof that the office is alive again: within a minute
   `https://bina.macbook.console.staging.digital-office.co.il/` answers a sign-in (302), not 404.
3. Its record for `hp-laptop` must dial `192.168.16.100:51830` (today it says `.102`) — either run
   the moved-pair finder (`d155d62b` from `dgo-stable`, then `bbox run`; `link.json` on the Mac
   says where it looked) or re-declare the endpoint there.
4. Optional, and the structural half: `./bbox engine forwards --apply` on the Mac so the Mac can be
   dialed too (today it is `engine-guest`: nobody can reach its UDP port, which is why the HP's own
   dial above could not help).
5. The owner's choice, not a requirement: a DHCP reservation for the HP in the router stops the
   address from moving again (the lease expires tonight 21:57).

Acceptance on the HP: `wg show wg4 latest-handshakes` shows a fresh handshake, `link.json` says
`ok`, a Mac tile opens from the HP console, and עזריה's chat opens through vps1.

## What this session touched (disclosure)

* Read-only everywhere, except two reversible probes: four Wake-on-LAN datagrams to the Mac's MAC,
  and a runtime `wg set` on `wg4` (peer endpoint `192.168.16.103:51830`, then `:51820`, keepalive
  5 s for 25 s each, then keepalive 0). Nothing on disk changed; the peer keeps a runtime endpoint
  of `192.168.16.103:51820` until the next render recreates the interface (the Mac's real packets
  would roam it anyway). No container was started, stopped or re-created by this session.
* The whole office was recreated at 20:42 local by someone else's `bbox run` (events: `dgo-net`,
  `dgo-link`, `dgo-extend`, `drive`, `connections`, `console`, … all re-created) — noted, not mine.
* The pair record on the HP still says `endpoint: 192.168.16.102` (cosmetic for a listener; `.env`
  says `.100`). Left as is; the record is written by the pairing and corrected by `listen_now` when
  a dialing office reaches the new address.
