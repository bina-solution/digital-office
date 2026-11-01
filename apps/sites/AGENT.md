# Operating `sites`

The office's websites. A **site** is a row in this app's own store (`/data/sites.db`); the **machine**
it runs on is an instance of `computer_ssh` in the credential plane, owned by `computers`; the
**stack** on that machine is a directory rendered from the site's record (`bina-site.v1`, see
`runtime.py`). Nothing here holds an SSH key, an address or a copy of the fleet.

Vocabulary:
- **managed** (`source: office`) — the office renders and deploys the stack;
  **adopted** (`source: adopted`) — the site predates the office, is monitored and scanned here, and
  its own deployment is left alone until someone runs „העבר לדפוס הקבוע”;
- a **finding** is one rule that failed, keyed by (site, check, code, url) — it disappears on its own
  when a later run stops reporting it;
- the **pattern**: `<root>/docker-compose.yml` + `nginx/default.conf` + `site.meta.json` + README +
  `site/` (content) + `logs/access.log` (the visits), one compose project, one container `site-<id>`;
- the **public path** (`public.py`) — the address the world sees: a **domain** (from the `domains`
  app) + a **path**, and a **mode**: `container` (the site's own stack serves it) or `office` (THIS
  app serves it, **no SSO**, container stopped, content cached in `/data/public/<id>`). Texts,
  images and logos always come from `digital-assets` (`site_kit` + `data-da` attributes).

## What you can do from here

```bash
# the fleet of sites, with uptime, visits and open findings
curl -s http://sites:8979/api/overview
curl -s http://sites:8979/api/sites/<id>
curl -s http://sites:8979/api/sites/<id>/findings
curl -s http://sites:8979/api/sites/<id>/uptime?hours=24
curl -s http://sites:8979/api/sites/<id>/visits?days=7
curl -s http://sites:8979/api/sites/<id>/stack      # the files a deploy WOULD write

# act on a site
curl -s -X POST http://sites:8979/api/sites/<id>/probe      # one uptime check now
curl -s -X POST http://sites:8979/api/sites/<id>/scan \
     -H 'content-type: application/json' -d '{"checks":["security","seo","beauty"]}'
curl -s -X POST http://sites:8979/api/sites/<id>/deploy     # render + rebuild + up
curl -s -X POST http://sites:8979/api/sites/<id>/start|stop|restart|collect
curl -s http://sites:8979/api/sites/<id>/logs?lines=200

# machines (read-only here — they are `computers`' nouns)
curl -s http://sites:8979/api/machines
curl -s http://sites:8979/api/machines/<mid>/edge           # what publishes sites on that machine
```

The **public path** and the **asset slots** (also as ops `publishSite`, `slots`, `applySlots`):

```bash
curl -s http://sites:8979/api/public     # what the office serves · /api/domains for the picker
curl -s -X PATCH http://sites:8979/api/sites/<id> -H 'content-type: application/json' \
     -d '{"public":{"mode":"office","entries":[{"domain":"ex.co.il","path":"/"}]}}'   # CONVERGES
curl -s -X POST http://sites:8979/api/sites/<id>/sync|publish        # cache / edge, on demand
curl -s http://sites:8979/api/sites/<id>/slots                       # already a digital asset?
curl -s -X POST http://sites:8979/api/sites/<id>/slots/apply -d '{"bundle":{"slots":{…}}}'  # push
```

The same surface exists as canonical ops (`POST /listSites`, `/getSite`, `/checkSite`, `/scan`, …) —
`GET /ops` is the machine-readable list.

## Traps

- **A site is not a machine.** Never SSH anywhere; if an action must run on a machine, it belongs in
  `computers` (`POST /api/computers/<id>/exec`). This app does it for you and reports what came back.
- **`deploy` overwrites the files on the machine.** The rendered files are the contract; a hand edit
  there survives until the next deploy and then is gone. Change the RECORD, then deploy.
- **Deleting a site keeps its files** unless `purge_files=1&confirm=<id>`; that flag is the one
  irreversible thing in this app, and it is deliberately awkward to send.
- **An adopted site's `start/stop` acts on the container that is really serving it** — the legacy
  container name, not `site-<id>`. Do not assume the pattern's container name for an adopted site.
- **Beauty needs the renderer.** `sites-render` owns Chromium; when it is unhealthy the beauty check
  reports „שירות הרינדור אינו זמין” and the rest of the app is unaffected. That is not a site finding.
- **Visits come from the site's own log.** For an adopted site that is the container's stdout, so the
  numbers start at the moment it was adopted — history cannot be recovered from a log that was never
  kept, and no check should claim otherwise.
- Sites on a machine need a working **edge** (traefik) there; `default_edge(machine)` discovers the
  network, entrypoints, ACME resolver and available middlewares, and falls back to declaring
  `provider: none` rather than rendering labels that route nothing.
- **`mode: office` stops the site's container** — that is what "the office serves it" means. Going
  back is one record change (`mode: container`) plus a start; nothing on the machine is removed.
- **A public router carries no forward-auth** — that is the definition of a public path, and the one
  way this app could publish something private: check `entries` before saving. Two routers per entry
  (plain + TLS), because a router with a `tls` block does not answer on the plain entrypoint.
- **`digital-assets` may be unreachable** (it can live in another office, via the link's door —
  `DIGITAL_ASSETS_HOST`). Then pages are served as they are and `/.assets/…` answers 503: an asset
  service that naps must not take a website down, nor silently show nothing.
