# Operating «מרכז הבקרה» (the `dashboard` app)

The owner's first screen on the MacBook (DGO-1124). On the side is every computer of every office, each with a dot:

- **green**: linked, and its office's own machine takes commands;
- **sky**: linked, but no command door (today the HP: no SSH);
- **plum**: the link is down, which is a critical fault with a banner of its own;
- **hollow**: declared in apps/computers/herd.yaml but not linked to this office.

A click opens the computer in this office's Computers app (`/#/m/computers/c/<where>/res`). Below that are what
opened and closed on the links. Progress per Plane topic comes next.

It only reads. `dashboard-feed` (feed.py, standard library, stock python image) writes `/data/state.json`
every 30 s. Plane is read live (the owner, 2026-11-03: «every change in the work items, live, and how every
item closes in today's log»): a full read every 15 minutes (topics, totals), and between them ONE request every
30 s for the items changed last, so a close, a start or a cancel is a line of «היום» and moves its topic's bar
within a minute. «היום» keeps every line of the last 24 hours (up to 600), with each kind counted in its header.
The other sources:

- dgo-extend's `/api/map` and `/api/link/history`;
- each office's Computers `/api/computers/computer_local-local/status` — its own machine only, never the whole
  fleet, which is probed one machine after another and took 17–20 s on a laptop away from home (DGO-1353). This
  office's is at `http://computers:8977`. A linked office's is at its link alias, `http://computers.<office>:<port>`.
  The port comes from `.generated/registry/remote.<office>.computers.json`, as `bbox remote` reads it, and it differs
  per office. This office's fleet (`/api/computers?probe=1`) is still read beside each pass, unwaited, because the
  console's account bar colours every machine from that probe's cache;
- herd.yaml's `offices:`.

`dashboard` (caddy) serves `static/` and `/data/`.

**The group relay** (`dashboard-group`, group.py, DGO-1329/DGO-1326) follows this office's event stream
(`dgo:flow:*` in redis: every notice that is news, from notifications) and posts what `group-events.json`
calls important to the owner's Telegram group, as the bot. The list is data: which kinds post, a link drop
held 3 minutes for its return, repeats, and at most 20 an hour. Each office posts its own events, under
its name; `DASHBOARD_GROUP_RELAY=0` keeps one quiet. The token is read from the vault when it is used.
A notice's answers («חסום») are written under its line, and the message id is kept with the notice in
`/data/group.json` (also the state: cursors, counts, last error). It also posts every work item that
opens, closes or is cancelled, one line each («📌 / ✅ / ✖️ DGO-n · …»), with a pass's lines in one message.
Items have a budget of their own (30 messages an hour), separate from the alarms'. It reads them from the
feed's own «היום» in `/data/state.json`, so Plane is read once. Only the office that herd.yaml runs Plane on
posts them (`DASHBOARD_GROUP_ITEMS=auto`), because every office's feed reads that one Plane. A close that is
saved again is not a new close.

```bash
./bbox dashboard computers [--json]                      # a line per computer: up·half·down·away·none, since, why
./bbox remote macbook dashboard /data/state.json        # what the page shows now (from another office)
docker logs dashboard-feed-<deployment>                  # a pass that failed says why; the last good file stays
```

The workbench mock is this page plus a measured day: `python3 digital-office/sim/build-dashboard-mock.py`.

Rules: the palette is theme-tokens.css only (gate G27; this page is in its targets). The collector never
writes to any office; a red dot is a reading, and fixing it is the computer's own item (DGO-1122 for the
Dell).
