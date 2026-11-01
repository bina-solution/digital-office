# apps/git — "ניהול גרסאות", the office's version control

This app is the deployment's **abstraction over the VCS APIs** plus the **local forge that hosts and
displays the repositories**. It is one app with two containers: `git` (the service: accounts, ops,
the smart-HTTP proxy, the mirror engine) and `forge` (Forgejo).

## What it replaced, and what it kept

The app used to be only the first half: an account plane over GitHub/GitLab with a provider-agnostic
op surface and a credential-injecting proxy. Every repository the office could act on was visible
only in somebody else's web UI, with somebody else's login, one account at a time. Building a code
browser (file tree, diffs, blame, issues, PR view, releases) is a product, not a feature, so the
answer was to run one: **Forgejo**, and to make every repository appear in it. This app then tried
building that browser anyway (2026-09-29: a repository list, a file tree, issues, PRs, releases) and
deleted it the next day for the very same reason — it was the worse of two places showing the same
thing (DGO-57).

| kept | added |
|---|---|
| the op surface (`git.v1`) and its normalization | a third provider, `forgejo` (`git_forge_local`), so the local forge is driven through the SAME ops |
| the vault as the only home of a credential | mirrors: external repositories copied into the forge through the proxy |
| the `/git/<code>/<account>/…` smart-HTTP proxy | `lc` — the local forge as a remote, on the same door |
| one account switcher, one connect wizard | a bootstrap hook that mints the forge credential so nobody types a token |

## Why Forgejo and not GitLab

Measured on this engine (macOS host, 8 GB machine → a 4 vCPU / 4.8 GiB Linux guest running ~40
containers):

| | GitLab CE | Forgejo 16.0.5 |
|---|---|---|
| upstream requirement | **8 vCPU / 16 GB** baseline, **8 GB** floor, 40 GB disk ([docs.gitlab.com](https://docs.gitlab.com/install/requirements/)) | no published floor; measured **144 MiB idle** |
| image | 1.5 GB compressed | 197 MB |
| database | PostgreSQL (own instance, 5–12 GB) | sqlite (in its own volume) |
| what the office needs from it | browse/issue/PR/release | browse/issue/PR/release |

GitLab on this machine would not be "slow" — it would exhaust a guest whose swap is already saturated
and let the OOM killer pick a victim among the office's containers. Forgejo gives the same surface
for a fraction of the memory.

**The seam is the provider, not the platform.** A GitLab backend would be a new module in
`adapters/` plus a compose service: `API v4` is already implemented for gitlab.com accounts
(`adapters/gitlab.py`, used against self-managed instances too), `git_forge_local`'s protocol would
point at it, and the mirrors engine is provider-agnostic by construction. What cannot be swapped is
the *display*: if a GitLab instance ever runs here, its own UI becomes the display and the app's
`/api/overview` links would point at it.

## The pieces

| file | what it owns |
|---|---|
| `app.py` | the platform service contract (`/manifest`, `/readyz`, `/connections`, `/providers`), the canonical ops, the mirror API, `/api/overview` |
| `accounts.py` | protocol → (provider, kind) table and the provider catalogue the wizard is built from; the vault client; the active-account pointer |
| `credentials.py` | one secret → API headers + git basic-auth pair, including the GitHub App / OAuth refresh paths |
| `adapters/` | `github.py`, `gitlab.py`, `forge.py` — one normalized shape per op, provider differences reported as `applied: native\|approximated` |
| `proxy.py` | the smart-HTTP proxy: `/git/<gh\|gl\|any\|lc>/<account>/<owner>/<repo>.git`, credential injected per request, bodies streamed |
| `mirrors.py` | the mirror registry, the sync engine, its guards, the scheduler |
| `bootstrap.py` + `hooks/prepare` | the forge's admin user, its access token, and the vault write — the only credential this app mints for itself |
| `static/` | the control panel: accounts (with the wizard and the probed states) and mirror declarations — and NO repository display, which is Forgejo's |

## The screen (2026-09-30): two screens, and the display is Forgejo

The owner's direction settled what this app IS: 99% of the display is someone else's open-source work.
So `/a/git-accounts/` keeps only what Forgejo cannot know — the accounts the office acts with, and the
mirrors it declares — and everything that DISPLAYS a repository (list, tree, one file, issues, PRs,
releases) is Forgejo, which the shell offers as its own tile (`module.git`, `external`, opening
`forge.<domain>`). An earlier version of this app WAS a repository browser in GitHub's shape: it was
built, verified, and then deleted on purpose (DGO-57). Two places that show a repository is one place
too many, and the second one is always the worse one.

| route | what it shows |
|---|---|
| `#/accounts` (and `#/`) | the office's accounts: provider, login, the PROBED state of each credential, probe / select / disconnect, and the connect wizard built from `/providers` |
| `#/mirrors` | the declared copies: source repository, its copy in the forge, size and last sync, sync / remove, and the declaration form |

The accounts screen paints TWICE on purpose: the cheap `/connections?probe=0` list renders instantly,
then each credential is probed and the chips are corrected. `ok` / `git_only` / `needs_action` each get
their own sentence, a credential that needs the owner shows the provider's own reason, and nothing this
app has not been taught is coloured green. A `/connections` that answers with a `reason` (the vault is
unreachable) is shown as exactly that — never as "no accounts".

The read endpoints the deleted browser needed still exist — `GET /api/repos?account=&q=`,
`GET /api/repo?account=&repo=&ref=`, and the `listDir` op behind a file tree — because the abstraction
is the product: GitHub, GitLab and the local forge produce the same shapes (`applied:
native|approximated`), so another app may read a repository through this one. This UI no longer calls
them.

### The navigation is DECLARED (DGO-53)

The app owns no navigation markup. `index.html` carries the three things an adopter contributes — the
container the menu measures (`.bnv-host`), the grid whose side column the component sizes
(`.appgrid`), and ONE empty `<aside id="sideNav">` — and `app.js` hands the shared component a
description of what the app has: brand (the app's name and the account it is acting as), one primary
action ("חבר חשבון"), its two screens as rows, its mirrors as rows carrying the state the service
reported, and a footer that opens the forge. The component builds every row, owns the breakpoints
(full menu ≥840px, rail 600–839px, drawer below 600px) and remembers the rail the owner chose. Five
promises are executed by `node platform-base/bina-ui/test_bina_nav.mjs`, which lists this app as an adopter; the
app's own declaration is asserted in `apps/git/tools/ui-selfcheck.mjs`.

Two traps this adoption taught, both measured rather than guessed:

* **The content cell must be placed explicitly.** At phone width the component sets the side column to
  `0px` and takes the drawer out of flow, so the content becomes the first in-flow grid item and
  auto-placement drops it into the 0px track: the screen rendered a top bar and 390×844 of nothing
  (`main {x:390, w:0}`, `grid-template-columns: 0px 390px`). `.appgrid > .main{grid-column:2}` is what
  makes the content "whatever is left" at every width the component decides.
* **A remount closes the drawer.** The declaration follows the data (mirror states, account counts), so
  the menu is rebuilt when it changes — but only when it really changed: the accounts screen paints
  twice (cheap list, then probed states) and a naive remount would slam a phone's drawer shut
  mid-interaction.

## The screen's offline proof

The screen's historical defects were pure-logic bugs — a router that rejoined a repository name out of
the wrong segments, a branch picker that discarded its own choice, a menu mounted into an element the
console also owns. A screenshot shows all three as "the page is empty".

```bash
node apps/git/tools/ui-selfcheck.mjs            # both screens, the office's notice, and the deleted half (run by G72)
python3 apps/git/tools/repoindex-selfcheck.py   # 25 assertions — the multi-account fan-out
bash apps/git/tools/post-build-verify.sh        # build → health → the read paths → a real capture
```

It evaluates the SHIPPED `static/app.js` in a Node VM with a small DOM stub and drives BOTH screens
against a canned `fetch` router: the route shapes, the formatters, the two-paint accounts screen (the
instant "לא נבדק", then the probed states, the reason of a credential that needs the owner, the
service's own state words refused), the mirror rows (a failed sync's reason, the source account named
by label rather than by vault id, the forge origin taken from the service instead of hardcoded), and
which tab the top bar marks. Its last section runs the OTHER way — it fails if repository display grows
back into this app (`viewRepo`, `repoRow`, `mdToHtml`, `#/r/…`) or if the page loses the shared blocks
the platform syncs (gate G27), which is the failure a rewrite like this one invites.

`repoindex-selfcheck.py` is the backend half. `accounts` and `mirrors` are replaced by recording stubs
before the module is imported, and what it proves is what the fan-out is FOR: every account
contributes, ONE failing account is reported beside the others instead of emptying the screen, a
code-only credential says so instead of looking empty, a mirror is attached to the repository it copies
rather than becoming a row of its own, search filters on name and description, and the cache really
absorbs a second read (the only thing between a refreshing browser and a shared GitHub quota). It is
dev tooling — the Dockerfile copies explicit files, so `tools/` never reaches the image and is never
served. `post-build-verify.sh` is the same idea end to end.

## The forge's origin on this engine: it nests under the console

On a real domain every app is same-site with the console (`*.bina-solutions.co.il` shares its
registrable domain), so a link from the console to `forge.<domain>` carries the console's cookies and
the browser is happy. On this engine the domain is `localhost`, which is NOT a registered TLD: a
browser then reads the registrable domain off the **last two labels**, so `forge.localhost` and
`console.localhost` are two different sites — and the forge is opened from inside the console's frame.
The fix is one label: the forge's public origin on this engine is **`forge.console.localhost:8080`**,
which is same-site with `console.localhost` (Chrome resolves `*.localhost` at any depth).

Three variables carry that origin, and the difference between them is the whole trap:

| variable | value here | who reads it |
|---|---|---|
| `FORGE_BASE_URL` | `forge.console.localhost:8080` — **host AND port** | traefik's rule and authentik's provider origin |
| `FORGE_ROOT_URL` | `http://forge.console.localhost:8080` | Forgejo's own links and the app's `browse_url` |
| `FORGE_HOST` | `forge.console.localhost` | Forgejo's `DOMAIN` (a hostname, never a host:port) |

**The port belongs in the value and must never reach the RULE.** traefik matches `Host()` against the
request's host with its port stripped and compares the rest literally, so a rule that contains one
matches nothing at all. Measured on 2026-09-30, same container, same request:

```
Host(`forge.console.localhost:8080`)  →  404      # a port inside the rule: compared literally, dead
Host(`forge.console.localhost`)       →  200      # the request's port is ignored — this is the rule
Host(`forge.localhost`)               →  200      # the -local router, unchanged
Host(`nope.localhost`)                →  404      # control
```

That is why `reconcile.py`'s `traefik_host()` (d3497a85) reads this machine's `.env` at render time and
renders the HOST PART of a ported value as a literal — compose interpolation cannot split a string, so
the value keeps the port the identity provider needs while the router gets a port-less rule. A
port-less value, or a render with no `.env` (CI), keeps the old `${VAR:-fallback}` form.

All three reach BOTH containers they matter to: `FORGE_ROOT_URL` is passed to the `git` service as
well as to Forgejo, because the SERVICE is what prints the links (`/api/overview` → `forge.url`, and
every mirror's `browse_url` via `mirrors.public_base()`). It was not, briefly: the service fell back
to the routing value and every link it handed out became the port-less host — which still answered on
this engine only because traefik also publishes :80 here. `FORGE_BASE_URL` is the RULE and
`FORGE_ROOT_URL` is the ORIGIN, and one variable cannot be both (issues/
one-base-url-feeds-two-matchers-with-opposite-rules.yaml). `apps/git/selftest.py` now asserts that what
the service advertises is what it was configured with, so the fallback cannot come back quietly.

`scripts/ci-env.sh` emits these three values only in its edge-port branch, i.e. only on an engine whose
edge is not :80 — the VPS (and `.env.ex`, which stays domain-shaped) is untouched. The bare
`forge.localhost` keeps working through the `-local` router, so nothing that was bookmarked breaks;
what changes is the origin the app ADVERTISES (`/api/overview` → `forge.url`, and every mirror's
`browse_url`), which is now same-site with the console that links to it.

## Single sign-on for the forge — SWITCHED ON (DGO-58, 2026-10-01)

The forge route is `auth: "sso"`: traefik's forward-auth authenticates the host, Forgejo believes the
header, and the owner arrives inside the console's frame already signed in as the edge user — no second
login form. `apps/git/app.json` declares the provider (`sso.slug: forge`, `base_url_env: FORGE_BASE_URL`,
`local_twin: true`), so the compiled blueprint registers TWO providers: `Forgejo Provider`
(`http://forge.console.localhost:8080`, from the value) and `Forgejo Local Provider`
(`http://forge.localhost`, the bare twin). Forgejo's side is four environment variables in
`docker-compose.yml`, and the SECTION each one belongs to is the whole trap:

| variable | section | what it does |
|---|---|---|
| `ENABLE_REVERSE_PROXY_AUTHENTICATION` | `[service]` | trust the header at all |
| `ENABLE_REVERSE_PROXY_AUTO_REGISTRATION` | `[service]` | create the user from the header on first sight (registration itself stays OFF — the door is the office SSO, not a form) |
| `REVERSE_PROXY_AUTHENTICATION_USER` | **`[security]`** | WHICH header (`X-authentik-username`) |
| `REVERSE_PROXY_TRUSTED_PROXIES` | **`[security]`** | which peers may assert it (docker's pool by default; pin it with `docker network inspect traefik-network`) |

**Measured, and the reason this table exists:** with the header name and the trusted-proxy list addressed
to `[service]`, Forgejo accepts them, writes them into `app.ini` under the wrong section, and is then
INERT — the header defaults to `X-WEBAUTH-USER` and the trusted range to `127.0.0.0/8,::1/128`, so
traefik's header is ignored and the tile shows Forgejo's own login form while every container reports
healthy. The docs put both under `[security]`. Two more facts worth remembering:

* **Reverse-proxy auth does not cover the API.** `curl -H 'X-authentik-username: …' /api/v1/user` answers
  `403` even when everything is right; the WEB UI (`/`) is the test — with the header it renders the
  dashboard as that user.
* The forge's own login stays available on the bare `forge.localhost` twin, which is what makes a
  misconfiguration debuggable (and is why the twin is declared).

## Status — built, served, and what is left

The screen lives in `apps/git/static/` and is copied into the image by the Dockerfile, so it becomes the
LIVE screen when the app is built, not when the file is saved. Built and recreated on 2026-09-30:
`./scripts/dc build git && ./scripts/dc up -d git`, after which `/healthz` and `/readyz` answer 200 and
the served page is the two-screen app (the served `app.js` carries no repository code at all).

What was verified live, in a real Chromium, on the console's own path `/a/git-accounts/`: the title
"ניהול גרסאות — חשבונות", three account rows from the vault, the accounts tab marked, the top bar naming
the active credential, and **zero page errors and zero console errors**.

```bash
bash apps/git/tools/post-build-verify.sh        # build → health → the read paths → a capture
PANEL_SHOTS=1 bash apps/git/tools/post-build-verify.sh   # …and every evidence screen of DGO-59
```

`apps/git/tools/panel-shot.py` is the capture itself, versioned beside the app (mounted read-only into
the ui-capture image): the app's own origin for the two screens, the console's path
(`http://console:8000/a/git-accounts/`) for the shell view, and — with `PANEL_SHOTS=1` — the accounts
screen, the connect wizard, the mirror screen, both again at 390px, and the forge page the tile opens.
Two harness facts it encodes, each learned by failing: **never map every host to the edge**
(`MAP * <ip>` swallows the SERVICE names too, so `git:8978` resolves to traefik and the run dies on
`ERR_CONNECTION_REFUSED`), and **the forge is photographed on :80** — the link the owner follows carries
`:8080`, which inside `traefik-network` is traefik's own dashboard rather than the ingress.

**Capturing this app: use its in-network origin.** A capture container cannot follow the edge's
`auth.localhost:8080` redirect (inside `traefik-network` that port is traefik's own dashboard, not the
ingress), so a console capture has to go to the console *service* — `http://console:8000/a/git-accounts/`
— which bypasses the forward-auth middleware while rendering the same page. The forge is the same
lesson from the other side: from inside the network its edge host is `http://forge.localhost/` (port 80);
`:8080` is the host's mapping and answers traefik's 404. Both are properties of the capture harness, not
of the app.

The last change on top of that build — the accounts screen now paints twice and shows each
credential's PROBED state instead of a blanket "לא נבדק", plus two fixes the live screen exposed (a
vault error that clears, "1 חשבון") — is in the repo and NOT yet in the running container, so the image
is behind by a commit or two until the next build. `post-build-verify.sh` is exactly
that build, and step 3 is what tells you whether it happened.

Still to capture when the engine is free: the two screens at 390px, and the forge page the tile opens.

## Operating it

`AGENT.md` is the brief (it is what the compiler hands to an agent as this app's operating context).
The short version:

```bash
./bbox app git prepare                       # bootstrap the forge credential (idempotent)
curl -s http://git:8978/api/overview         # forge, local repos, accounts, mirrors
./scripts/dc logs --tail 50 git
./scripts/dc logs --tail 50 forge
```

## The one trap that cost a clone

`git` gzips its upload-pack request once the body passes a few hundred bytes and declares it with
`Content-Encoding: gzip`. The proxy used to rebuild the upstream header set from scratch, so the gzip
bytes arrived at GitHub without the header that explains them: a bare `HTTP 400`, an empty body, and
"expected 'packfile'" in the client. Every small repository cloned fine, and the office's own 1.3 GB
repository could not be cloned at all. `proxy.py` now forwards `Content-Type` and `Content-Encoding`
with the body it forwards, and `AGENT.md` records why that loop must stay.
