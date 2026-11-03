# AUD-C5-001331 — severe office events to the owners (the office watch)

**Status: installed on fpg-vps since 2026-10-29 (`office-watch.timer`, once a minute); stale mounts added the same day at 16:03Z (FPG-497).** This folder is the source of what runs there — `server/office-watch.py` = `/usr/local/sbin/office-watch` (md5 c4532605…), the units and the settings template as installed. Its test suite: 68/68. First built by lane R2-L9d, 2026-10-29.
Design: lane-R2-L9a `AUD-C5-001331/README.md`. Nothing on any server was changed while building this.

## What it does
`office-watch` — a small Python 3 (stdlib only) check, run once a minute by a systemd timer at low priority
(nice 19, idle IO, CPUWeight 20, ≤ 128 MB, 45 s timeout; no SCHED_IDLE so a busy CPU cannot starve it).
Each run (well under 2 s: /proc reads, one `docker ps`, one statvfs, one log read) looks at:

| Event | Opens (level `error`) | Closes («back to normal», level `info`) | source_id |
|---|---|---|---|
| CPU at its limit | host busy % (from /proc/stat deltas) ≥ `CPU_PCT` **or** PSI cpu `some` avg60 ≥ `PSI_PCT`, every minute for `CPU_MIN` minutes in a row | under the limit for `CPU_CLEAR_MIN` minutes (body: how long, peak %) | `cpu` |
| A service down | a container of the office's compose project (label `com.docker.compose.project=fireplace`) or a `WATCH_EXTRA` name is `unhealthy`, `restarting`, `dead` or exited non-zero on `SERVICE_RUNS` checks in a row (autoheal gets the first) | healthy/running again, or the container vanished | `svc-<name>` |
| Disk nearly full | a `DISK_PATHS` mount ≥ `DISK_PCT` used (df's Capacity) or < `DISK_FREE_GB` free | back under both with a 1-point / 0.5 GB band (no flapping) | `disk-root` |
| Off-site backup failing | the newest line of X-17's `/var/backups/fpg-offsite/offsite.log` for a profile is `status=failed` (body: exit code, last good copy), or no `status=ok` for longer than `OFFSITE_MAX_AGE_H` (core 26 h, full 194 h; a profile with no line yet counts from the log's first line) | a fresh `status=ok` line | `offsite-core`, `offsite-full`; `offsite-log` if the log is missing |

**Each event is told exactly once when it opens and once when it clears.** The state file
(`/var/lib/office-watch/state.json`) keeps, per event, what is true (`want`) and what the notice centre has
accepted (`told`); a post is made only when they differ, and `told` advances only on HTTP 200/201 — so a
notice centre that is down gets the post on the first run after it is back, never twice. One broken check
never silences the others. `docker ps` failing keeps the services as they were (no false «back»).

## The notice centre contract (read live, read-only, 2026-10-29 ~05:08Z)
`notifications-fireplace` (live `/app/app.py` md5 4e9de532…): `POST /api/notifications`, JSON
`{source, title, source_id, body, level, link, meta}` (source + title required; level `error|warning|info`),
**upsert by (source, source_id)** → `201 {"id", "created": true}` new / `200 {"created": false}` updated; a post
whose `meta` has no `lastSeen` re-surfaces the row as unread. So one row per event, updated as the story goes on
(opened → back to normal) — exactly meet-start's `say()` (source `meet-health`) and X-17's `notify()` (source
`office-backup`). This watch posts `source: "office-watch"`, titles ≤ 200 chars, bodies ≤ 2000, `link` = `LINK`.
**Delivery from the host = X-17's way:** `docker inspect` the IP of `notifications-<OFFICE>` → `http://IP:8977`
(or a fixed `NOTICE_URL`). No auth on that API (office network only). Timeout 5 s.

**The phone leg:** the platform notice centre has **no push** today (no VAPID/subscriptions/service worker in
the live app; the only Web Push in the office is chimney-services' own, behind user sessions, no endpoint a
host job can call). The watch writes `error` rows, so the L9a design — Web Push in the notifications app for
`error` rows (a platform change, Shlomo's call; per-user devices = M5-T42) — rings the phones with **no change
here**. Until then: `ALSO_POST_URLS` sends the same JSON, once per change, to any extra receiver (e.g. a push
endpoint) — a setting, no code.

## Settings — `/etc/default/office-watch` (owners change a value; next run picks it up)
`CPU_PCT=90` `CPU_MIN=5` `CPU_CLEAR_MIN=2` `PSI_PCT=80` (0 = off) · `WATCH_EXTRA="site-fireplace-guys
site-fireplace-guys-forms"` (live, `unless-stopped`, no compose label) `IGNORE="*-init-*"` `SERVICE_RUNS=2`
`EXITED_ZERO_OK=1` (an init job that exited 0 is fine) · `DISK_PATHS=/` `DISK_PCT=90` `DISK_FREE_GB=5` ·
`OFFSITE_LOG=/var/backups/fpg-offsite/offsite.log` (empty = off) `OFFSITE_MAX_AGE_H="core=26 full=194"` ·
`OFFICE=fireplace` `NOTICE_URL=` `LINK=` `ALSO_POST_URLS=`. An existing file is never overwritten by deploy.

Live values seen read-only: 2 cores, PSI `some` avg60 ≈ 19 % at rest, `/` 45 % used (55 GB free), X-17 timers
active (core daily ~03:52Z, full Sun), offsite.log 1 line `status=ok` 04:41Z, 62 containers, all running/healthy
except `fireplace-mailserver-init-1` (exited 0 → ignored).

## Files
`server/office-watch.py` → `/usr/local/sbin/office-watch` · `server/office-watch.service`, `server/office-watch.timer`
(every minute at :30, `AccuracySec=5s`, first run 2 min after boot) → `/etc/systemd/system/` ·
`server/office-watch.default` → `/etc/default/office-watch` (only if absent) · `README.md` → `/usr/local/share/doc/office-watch/`
· `deploy.sh`, `rollback.sh`, `MANIFEST.md5` · `test/` (suite, fake docker, `last-run.txt`).

## Run order (on the office's server, as root, from a copy of this folder)
1. `DRY=1 bash deploy.sh` — guards (root, host `srv2085127`, tools, python ≥ 3.9, md5 of every package file,
   the notice centre answers a read-only GET 200) + one `--check` look (posts nothing, writes nothing). Read it.
2. `bash deploy.sh` — backup to `/root/office-watch-backup-<stamp>/` → install → `systemd-analyze verify` →
   daemon-reload → the first real run (`systemctl start`, must leave a state file) → **one test row**
   (`deploy-test-<stamp>`: «TEST — the office watch is installed (nothing is wrong)», warning, then closed as
   «TEST — the office watch works», info; same row) → timer enabled + active. Any failure after the backup
   rolls back by itself.
3. Check: the console's notice centre shows the TEST row; `systemctl list-timers office-watch.timer`;
   `journalctl -u office-watch -n 20` (it prints only when it tells something or a check fails).
4. Undo any time: `bash rollback.sh [/root/office-watch-backup-<stamp>]` (timer off, files back/removed, state
   back; rows already told stay as history). Needs the owner's own words for the live write
   (memory: live-office-writes-need-the-owners-own-words).

## How proven (locally: 53/53 when first built; 68/68 with the stale-mount checks of FPG-497)
`python test/test_office_watch.py` drives the real `office-watch.py` with a fake `/proc` (stat + pressure),
a fake `docker` CLI, a fake disk, a fake offsite.log, a fake clock and a fake notice centre that speaks the live
contract (upsert, 201/200, 503 when «down»): CPU 95 % 4 min → nothing, 5 min → one, still high → none, 1 min
calm → none, 2 min calm → one recovery (peak in body), one row for the whole story, broken hot spells never add
up, PSI ≥ 80 % alone also tells; a service unhealthy 1 check → none, 2 → one, recovered → one, exit-0 init and
non-project containers never, a WATCH_EXTRA site exited 137 → once, restarting → told, docker down → no false
recovery, vanished → closes once; disk over → one, no duplicate, no flapping at the line, recovery once, low free
GB also tells; offsite failed line → one (exit code + last good copy), no duplicate, good copy → one recovery,
27 h stale → one, full overdue → once, log removed → one; notice centre down → tried, nothing counted, told on
the first run after, never twice; address via `docker inspect` (X-17 way), no address → no crash then told;
`--test` → one row opened (warning) + closed (info), exit 1 when refused; `--check` posts/writes nothing; a
broken state file → fresh start kept as `.bad`; a broken disk check does not silence the service check.
`bash -n deploy.sh rollback.sh` clean (Git Bash).

## NOT verified
Nothing ran on fpg-vps (lane rule): not `deploy.sh`, not `systemd-analyze verify` (no systemd here), not a real
timer run, not the real run time/memory under a busy CPU; shellcheck not available; the docker `{{.State}}`
format was read live (works on the server's Docker) but the full watch never ran against the live `docker ps`;
the phones: no push exists in the notice centre yet (see «The phone leg»). Known limits: a container
`docker rm`-ed while healthy is not noticed (only ones the watch had told about close); a mass outage tells one row
per service (no grouping); if Docker itself is down the notice centre (a container) is down too — the watch
logs it and tells nothing until it is back.

## Owner question
The CPU limit and how long it may last before a notice — default **90 % for 5 minutes** (also PSI 80 %);
change `CPU_PCT` / `CPU_MIN` in `/etc/default/office-watch`. Also: should the two `site-fireplace-guys*`
containers be watched (default yes)?
