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
- each office's Computers `/api/computers?probe=1`. This office's is at `http://computers:8977`. A linked
  office's is at its link alias, `http://computers.<office>:<port>`. The port comes from
  `.generated/registry/remote.<office>.computers.json`, as `bbox remote` reads it, and it differs per office;
- herd.yaml's `offices:`.

`dashboard` (caddy) serves `static/` and `/data/`.

```bash
./bbox remote macbook dashboard /data/state.json        # what the page shows now (from another office)
docker logs dashboard-feed-<deployment>                  # a pass that failed says why; the last good file stays
```

The workbench mock is this page plus a measured day: `python3 digital-office/sim/build-dashboard-mock.py`.

Rules: the palette is theme-tokens.css only (gate G27; this page is in its targets). The collector never
writes to any office; a red dot is a reading, and fixing it is the computer's own item (DGO-1122 for the
Dell).
