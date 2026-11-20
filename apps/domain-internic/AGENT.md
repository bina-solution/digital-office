# Operating `domain-internic`

The InterNIC provider of the generic `domains` app: an **external** provider app (it bridges a service that
runs elsewhere; ai/context/provider-apps.md). Everything that is InterNIC's lives here and nowhere else —
the portal's script and its zone writer (`portal.py`), the zone editor (`browser_ops.py`), the browser
contract client (`browser_session.py`), the sign-in (`login.py`). `domains` finds this app by its
name and calls its domain-provider.v1 ops; it holds no InterNIC code.

It runs where the office browser that is signed in to InterNIC runs (`apps/computers/herd.yaml`: the HP),
and the HP gives it to vps1 and the MacBook (`give:`), so `./bbox domain-internic …` works from any of them.

## The four channels

```bash
./bbox domain-internic status                    # signed in? credential row? which writes are the office's?
./bbox domain-internic login                     # sign in by itself (credential + the mailed code), once
./bbox domain-internic domains                   # the account's domains, off the portal
./bbox domain-internic zone digital-office.co.il # one zone, off the portal's own editor
./bbox domain-internic add-record digital-office.co.il A '*.exampleu' 93.184.216.10 [--ttl 3600] [--consent "<who>: <why>"]
./bbox domain-internic verified create           # has the office seen a create succeed (its own since)?
./bbox domain-internic flow                      # sign-ins, records, a lost session — the last 10, then live
```

- **ui** — the tile `/a/domain-internic/`: the session, the domains, a zone, what happened.
- **cli** — the verbs above (hooks/ → cli.py; on an office that does not run the app, `where.sh` sends the
  same verbs to the office that does, through the link — `scripts/herd_home.py`, as project-pln does).
- **api** — `GET /ops` names the ops; `GET /api/state`, `POST /api/login`, `POST /api/connect`,
  `GET /api/domains`, `GET /api/zones/{domain}`, `GET /api/write-state`, `POST /api/records`, `POST /api/run`,
  `POST /api/selftest`, `GET /api/verified`, `GET /api/flow`.
- **flow** — `dgo:flow:domain-internic`: `login.ok`, `login.<state>`, `record.created`, `record.create_failed`.
  Never a secret, a code or a cookie.

## How it reaches InterNIC — the access ladder, measured

The evidence for each rung is in `provider.json` (`ladder`). In short: **1. official API** — none from
InterNIC; the zone's own Plesk (sitesdepot) refuses API callers by IP until InterVision allows ours (DGO-1478).
**2. the portal's own routes** — to be observed in the browser's network log during one watched save
(DGO-1477). **3. the browser** — what runs today, every write read back. A rung is added beside the one
below it, never instead of it, until it is proven on the live account.

## Signing in by itself

- The credential is the row `domain-internic-login` in חיבורים ומפתחות (`DOMAIN_INTERNIC_USER`,
  `DOMAIN_INTERNIC_PASSWORD`). It declares the portal's address, so the office browser mirrors it into its
  own password store (`bbox b42 logins sync`, and at every browser start); `login` clicks the user field and
  picks that login. This app never holds the password: the MCP's type tool echoes what it typed, and the
  browser's DevTools port is the browser's own (DGO-983).
- A consent is taken only inside this container (the CLI at this office's shell); any other caller's
  `consented_by` is dropped. The watched marks of the old in-domains writer (vps1 `domains_state`) did not
  move: the first create here asks for one consent again.
- When the portal asks for a code it e-mailed, `login.py` reads it through the office's mail (mail.v1
  `search` + `get`) from the mailbox named by `DOMAIN_INTERNIC_MAIL_CONNECTION` (a connection id).
- ONE attempt per call. A captcha, an unknown form, a refused password or a missing code stops with its own
  state and the live view (`/a/browser42/`). Never loop a login: the registrar locks the account.

## Writes and the consent

- A write the office never saw succeed is refused (`needs_verification`) unless it carries a consent: the
  generic screen's (the edge's signed-in person) or the CLI's `--consent "<who>: <why>"` at the office's own
  shell. One consented create that the zone READ BACK, and that changed it, makes create the office's own
  (`/data/portal-verified.json`, with who and what) — from then on it runs alone.
- Only `create` is scripted (`ZONE_WRITERS`); update/delete are `not_scripted` and refused by name.
- `internic_create` re-reads the zone from the server before the save (no read, no save) and after it, and
  refuses a create that would clash with a record already there.

## Traps

- The portal is behind Imperva: a non-JS client gets 200 with a 212-byte challenge. Only a real browser.
- The panel's paths: the domain list is `/dashboard/main` (`/domains` 404s); a zone is `/zone/<id>`, reached
  by ticking the row and clicking `zone-edit` (visually hidden). The click may open a NEW TAB: count tabs
  first, close only the one you opened.
- A zone row is identified by its FIELD NAMES, not its position: `select[name=rectype_<n>]` AND
  `input[name=specs_<n>]`, `<n>` being the TYPE's index. Every other row with a type select is a TEMPLATE
  (the add-record form, SRV sub-rows); read positionally they invented an apex A no resolver answers. The
  page also ships hidden blocks — `#office365_template` (six Microsoft CNAMEs it only OFFERS), `#default_records_template`,
  `#empty_zone_record` — whose rows carry per-record names: they are skipped, or the save dialog's count refuses.
- Its tests: `python3 apps/domain-internic/test_write_record.py`, `test_portal_write.py`, and
  `test_portal_js.py` (needs Playwright with its Chromium; skipped without).
