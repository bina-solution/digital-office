# DGO facts — the only things an article may say about DGO (as of 2026-10-19)

Every sentence about DGO, Bina Solutions or "the office" in any piece of content comes from this file.
If a piece needs a fact about DGO that is not here, write the placeholder `[[fact: what must be checked]]`
instead of a guess. Never write a number about DGO that is not in this file. When a fact here changes,
the change happens here first (work item DGO-661, «דף העובדות»), and the content is re-checked against it.

Facts about the outside world (a project's license, a SaaS price, a law) come from your own research,
each with its source in `sources:`.

## Names

| What | Hebrew | English | Notes |
|---|---|---|---|
| The product | הלשכה הדיגיטלית | Digital Office | Short form **DGO** in both languages. First mention in an article: «הלשכה הדיגיטלית (DGO)». |
| The company | בינה סולושנס | Bina Solutions | Develops and provides DGO. Site: bina-solutions.co.il |
| One installation | לשכה | an office | Several linked offices are "your DGO". |
| The office agent | עזריה | Azaria | Runs in the agent app «בינה» (DeepSeek Harness, in Hebrew). |
| Product site | — | — | https://digital-office.co.il |
| Public source code | — | — | https://github.com/bina-solution/digital-office |

Say «מופע» for an instance, never "tenancy".

## Release and license

- The first public release went out on **2026-10-19** under **GNU AGPL v3**, for the whole repository.
- In plain words: anyone may use, run, study and change DGO, and sell services on it. Whoever runs a
  *modified* version for other people over a network must offer those people its source code
  (section 13).
- Some bundled upstream apps keep their own licences. **n8n uses the Sustainable Use License
  ("fair-code"), which is not open source by the OSI definition.** The plan is to move n8n out of the
  core and make it an optional add-on.
- The DGO console does **not yet** show users a link to the running version's source (work item
  DGO-657 is open). Do not claim it does.

## Where it runs

- **One command:** `./bbox run`. On Windows it is `bbox.cmd run`, from CMD or PowerShell, in a plain
  `git clone` anywhere on C:. It hands off to WSL and runs the project's own Docker engine there.
- **No Docker Desktop, ever** — not on Windows and not on Mac.
- **Mac:** the same `./bbox run`, from a clone under your home folder.
  - DGO creates its own small Linux machine (Lima with Apple's virtualization, Docker CE 28.5.2) under
    `~/.bbox/macos`, with no admin rights.
  - Apps answer at `http://<app>.localhost:8080`.
- **Linux or a VPS:** runs directly on Docker 28.x. Docker 29 is not supported yet: the edge router
  (Traefik 3.3) starts but finds no routes on it.
- **First run:** builds the images, about 10–15 minutes on a small machine. Later runs are cached.
- **It adapts:** `bbox run` sizes the stack to the machine's cores and starts Docker if it is not running.
- **Measured, our own machines:**
  - `vps1` is a Hostinger KVM 2: 2 vCPU, 8 GB RAM, 100 GB disk, Debian 12, Paris. It runs a full
    office and the company's public sites.
  - The MacBook office runs inside a 4-CPU / 5 GiB virtual machine.

## What a person sees and gets

- **The console («המרכז»):** a Hebrew, right-to-left desktop in the browser.
  - Every app opens in its own window.
  - It works on a phone, a tablet and a desktop.
- **One sign-in for every app** (authentik).
- **Apps:** installed, enabled, disabled and removed from the screen «ניהול אפליקציות».
- **Credentials:** one vault, «חיבורים ומפתחות», holds keys, passwords and OAuth logins. Apps receive
  them from the vault and never store them.
- **Built-in operations:**
  - a notification centre;
  - machine health (containers, storage, CPU, memory);
  - full backup and restore of all the office's data («ניהול נתונים»);
  - automatic restart of services that report themselves unhealthy («ריפוי עצמי»).
- **Backups are per app.** Each app declares what its backup holds. Examples from `bbox help`:
  - n8n: its database dump plus its `.n8n` volume, which holds n8n's encryption key;
  - Plane: its database and its object store (projects, work items, every file);
  - authentik: its database (users, groups, tokens, providers);
  - Supabase: its auth users and its storage index.

### Bina's own apps (first-party)

- **INDOX — «מסמכים»:** incoming documents end to end — sync, extraction, filing, display.
- **«מסמכים שלי» (my-docs):** the business's own documents, such as invoices.
- **«כלי מסמכים» (apitools):** OCR and value extraction from scanned business documents. Tesseract
  inside.
- **«דרייב»:** files, local and through Google Drive.
- **«מייל»:** a local mailbox plus Gmail/IMAP, behind one interface.
- **«צ׳אט»:** local chat, WhatsApp and Telegram through connections, and bots that attach to any
  connection.
- **«דפדפן» (browser42):** the office's shared browser for automation, with a live view.
  - AI agents drive it through Playwright MCP.
  - A login or a payment waits for the owner.
- **«ניהול גרסאות» (git):** GitHub/GitLab accounts, a local forge (Forgejo) for every repository, and
  mirrors.
- **«סוכן Google Workspace»:** MCP servers that expose Google Drive, Sheets and Gmail to AI agents.
- **«הרחבת הלשכה» (dgo-extend):** links offices together (see below).
- **«מחשבים»:** the office's own machine and SSH servers.
- **«אתרים»:** hosts and monitors the business's websites — uptime, visits, security, SEO and a
  beauty score.
- **«נכסים דיגיטליים»:** the business's logo, names, texts and media, organised once and pushed to
  every channel.
- **«רשתות חברתיות»:** every social network behind one interface, through the office browser.
- **«דומיינים»:** domain expiry, DNS and registrars.
- **«כל מקביל»:** a live timeline of everything running in parallel.
- **Platform services:** «ניהול אפליקציות», «התראות», «מכונה», «ניהול נתונים».

### Open-source projects that run inside DGO today

**18 as apps:**
- n8n
- authentik
- Traefik
- PostgreSQL (the Supabase build)
- Redis
- GlitchTip
- Supabase (Studio, storage, API)
- Portainer CE
- RedisInsight
- Ollama
- OpenHands
- Plane (in Hebrew, the `plane-he` build)
- Forgejo (inside «ניהול גרסאות»)
- docker-mailserver (the engine of «מייל»)
- DeepSeek Harness (the agent app «בינה»)
- Archify (the office's diagrams)
- CloakBrowser (the browser engine of browser42)
- block/buzz (the chat relay)

**Inside apps, as parts:**
- Playwright MCP and noVNC (in the browser)
- LiteLLM (in OpenHands)
- MinIO (in chat and in Plane)
- Valkey
- Caddy
- PostgREST and Kong (in Supabase)
- WireGuard (in dgo-extend)
- Tesseract (in apitools)
- Baileys (the WhatsApp library in chat)

**Not in DGO yet — packages planned:**
- Nextcloud
- Immich
- Paperless-ngx
- Stirling-PDF
- Vaultwarden
- Mattermost
- Chatwoot
- Cal.com
- Vikunja
- Metabase
- NocoDB
- Plausible
- LibreChat
- SearXNG
- Home Assistant
- Odoo

For these, say the DGO package is on its way («בדרך לחנות של DGO»). Never say "one click today". You may
explain how people run them in Docker now.

## Linking offices — DGO Extend, «המשולש»

- Every office is one `./bbox run` on one machine. Offices link to each other.
  - The company's own setup: the owner's MacBook, an HP laptop (Windows/WSL) and a small VPS.
  - Each one is linked to the other two.
- **Ways to link:**
  - **Pairing from the screens:** a QR code, the camera, or an offer pasted as text. Both screens show
    the same six digits.
  - **Declaring a machine:** this office installs the other office over SSH, as it did with the VPS.
  - **Joining by declaration (`DGO_JOIN`):** for an office with nobody at its screen.
- **The link:** an encrypted WireGuard tunnel. When a network blocks UDP (measured on Windows/Hyper-V),
  the pair rides a TCP path instead.
- **Remote apps:** an app that runs on one office opens as a tile in another office's console.
  - Measured: Plane runs on the HP and opens from the MacBook's console at
    `plane.hp-laptop.console.localhost`.
- **The point:** run open source wherever there is a machine, and reach it from wherever you are.
- **Honest limit:** an office on a laptop is offline while that laptop sleeps or is off. The other
  offices keep working.

## Money

- DGO itself costs nothing.
- What you pay for:
  - your hardware;
  - optionally a small VPS (the vps1 class: Hostinger KVM 2);
  - any paid API you choose to use, for example an AI model's API.
- There is no managed cloud offer yet. Never state its price: `[[fact: managed cloud price]]`.

## Never claim

- A certification or approval that was not verified. For example: Israeli Tax Authority–registered
  invoicing software, ISO, or accessibility compliance.
- User counts, customer names, revenue, or GitHub stars beyond what was measured. The public repo had
  **1 star on 2026-10-19**.
- The signed app store with `dgo install` (work item DGO-599, in progress). It is not released yet.
- An English version of the product site. It is not live yet.
