# The apps of DGO · האפליקציות של הלשכה

Every app of this release, from its own manifest (`app.json` — its title, in English and Hebrew, and what it is). Each folder also holds the app's brief, `AGENT.md`: how it is operated. On a running office, `./bbox context <app>` says what an app is and does there now, and `./bbox apps enable <app>` turns one on.

## The core — every office has these (`platform-base/`)

| app | name | what it is |
|---|---|---|
| [`app-management`](../platform-base/app-management/) | App Management · ניהול אפליקציות | The platform control plane — install, enable, disable and uninstall apps |
| [`authentik`](../platform-base/authentik/) | Authentik · משתמשים וכניסה | Identity, SSO and access control |
| [`autoheal`](../platform-base/autoheal/) | Autoheal · ריפוי עצמי | Restarts containers Docker has marked unhealthy |
| [`bina-ui`](../platform-base/bina-ui/) | Bina UI · ספריית ממשק | Shared UI components — tables, design tokens |
| [`connections`](../platform-base/connections/) | Connections · חיבורים ומפתחות | The credential plane — keys, connections, OAuth broker |
| [`console`](../platform-base/console/) | Console · המרכז | The unified business-system shell |
| [`containers`](../platform-base/containers/) | Containers · מכולות | The engine every container app runs on — on every OS |
| [`data-management`](../platform-base/data-management/) | Data Management · ניהול נתונים | The platform's data inventory, full backup and restore |
| [`follow-runner`](../platform-base/follow-runner/) | Follow · מעקב אחרי הגרסה היציבה | An office whose bbox runs inside containers takes dgo-stable by itself, every 30 minutes, health-checked and rolled back |
| [`forward-auth`](../platform-base/forward-auth/) | Forward-auth · זהות וכניסה | The identity and forward-auth service — one Go binary, replacing authentik (core-006) |
| [`glitchtip`](../platform-base/glitchtip/) | GlitchTip · מעקב שגיאות | Sentry-compatible error tracking |
| [`https-redirect`](../platform-base/https-redirect/) | HTTPS redirect · הפניה ל-HTTPS | Port 80 answers 308 to https on a server office — and serves nothing |
| [`machine`](../platform-base/machine/) | Machine · מכונה | Host and Docker metrics — containers, storage, resources |
| [`notifications`](../platform-base/notifications/) | Notifications · התראות | Notification centre — errors and system events |
| [`postgres`](../platform-base/postgres/) | PostgreSQL · בסיס נתונים | The platform database |
| [`redis`](../platform-base/redis/) | Redis · מטמון ותורים | Cache, queues and locks |
| [`security`](../platform-base/security/) | Security · אבטחה | Who reaches the office and what it calls — address maps, inbound and outbound, a built-in fail2ban, the router, the machine and the herd |
| [`traefik`](../platform-base/traefik/) | Traefik · נתב הקצה | The edge router — routing, TLS and forward-auth |

## The apps — each office chooses (`apps/`)

| app | name | what it is |
|---|---|---|
| [`android-emulator`](android-emulator/) | Android emulator · אמולטור אנדרואיד | An Android phone emulated in the office: seen and used from its screen, APKs installed on it, kept cool by the machine's heat |
| [`any-concurrency`](any-concurrency/) | Any Concurrency · כל מקביל | Deployment-wide concurrency observability |
| [`apitools`](apitools/) | API Tools · כלי מסמכים | OCR, value extraction, Hebrew speech-to-text and the document ledger |
| [`archify`](archify/) | Archify · ארכיטקטורה | The office's diagrams — architecture, sequences and lifecycles rendered from sources kept in the repository |
| [`bina-claude`](bina-claude/) | Claude Desktop · קלוד דסקטופ | The official Claude Desktop app inside the office, with ONE sign-in per instance — its screen in the console, and the CLI, the API and the flow on that same sign-in. Another instance is another Claude account |
| [`bina-ds`](bina-ds/) | Azaria · עזריה | The office agent — a Hebrew-native DeepSeek Harness that follows and acts across every app |
| [`browser42`](browser42/) | Browser42 · דפדפן | Shared stealth browser for automation and QA, with a shared clipboard and a live view |
| [`calculator`](calculator/) | Calculator · מחשבון | The office's small calculator — born from a request, not from an installation |
| [`chat`](chat/) | Chat · צ׳אט | The chat service — local chat plus WhatsApp and Telegram via connections, with bots attachable per connection |
| [`ci-runner`](ci-runner/) | CI runner · מריץ CI | The office's GitHub Actions runner: what runs now and who asked, what waits at the door and why, the last jobs, pause and resume |
| [`computers`](computers/) | Computers · מחשבים | Every office's computer — live resources and network for this machine and every linked office's, plus servers attached over SSH |
| [`dashboard`](dashboard/) | Control centre · מרכז הבקרה | Every computer of every office with its dot, and the work under way |
| [`dgo-cloud`](dgo-cloud/) | DGO Cloud · DGO Cloud | A managed DGO in the cloud in a minute: sign-up (Google or e-mail), monthly payment by Cardcom, a Hostinger server ready in advance, an LLM router with credit — and the management of every client and server |
| [`dgo-extend`](dgo-extend/) | Office extension · הרחבת הלשכה | Create, link and run further digital office instances from here — an office is a declaration, a link is a one-way trust, and an app placed on another office appears here as one more connection of the same capability |
| [`digital-assets`](digital-assets/) | Identity · זהות | The one place the business is defined — name, legal details, contact details, marks, colours, texts, content and media — and the whole office reads it from here: documents, websites, networks and products |
| [`documents`](documents/) | Documents · מסמכים | Every document of the business in one list — what it issued and what came in by mail and Drive — one search, no data moved |
| [`domain-internic`](domain-internic/) | InterNIC · אינטרניק | The InterNIC domain provider — the portal sign-in, mail verification, reading domains and DNS zones and writing records, through the office browser |
| [`domains`](domains/) | Domains · דומיינים | The business's domains — registry expiry, DNS hosts and registrars behind one interface, and the records the world actually resolves |
| [`drive`](drive/) | Files · קבצים | Every file of the business in one place — documents, photos, recordings, meetings and videos; every app and agent reads and writes here |
| [`drive-google`](drive-google/) | Google Drive · Google Drive | The engine of «Files» that connects Google Drive accounts — signed in with Google, or a service account folders are shared with; shown inside «Files» |
| [`drive-local`](drive-local/) | Office storage · אחסון הלשכה | The engine of «Files» that keeps the files on the office's own server — storage, index, profiles and share links; shown inside «Files» |
| [`element`](element/) | Element · אלמנט | Element, the official Matrix client, inside the office: its screen in the console, and the CLI and the API on the owner's account (chat.v1). |
| [`entities`](entities/) | Entities · ישויות | Everyone the business works with — people and organizations — in one place, each with its roles: customer, supplier, company, salesperson, contact. Documents and the whole office take them from here |
| [`esign`](esign/) | Signatures · חתימות | A document goes out for signature as one link (with a per-document password if wanted), the signer signs, and the signed copy lands in «קבצים» — and the link opens nothing else in the office |
| [`git`](git/) | Version control · ניהול גרסאות | An abstraction over the VCS APIs — GitHub/GitLab accounts, a local forge (Forgejo) that hosts and DISPLAYS every repository, mirrors of external repos, and code pushes acting as the owner |
| [`github-hooks`](github-hooks/) | GitHub webhook intake · קליטת אירועי GitHub | The public door GitHub posts events to: keeps each delivery as it came and answers at once, knowing no secret and no account; the git app verifies and records |
| [`google-workspace-agent`](google-workspace-agent/) | Google Workspace Agent · סוכן Google Workspace | MCP servers exposing Google Drive, Sheets and Gmail to n8n AI agents, plus an integration health probe. Automation only — this app owns no container. |
| [`hello-bina`](hello-bina/) | Hello Bina · שלום בינה | A third-party sample app — one tiny static page |
| [`image-store`](image-store/) | Image registry · מאגר התמונות | The images the line's proof built, by digest, so that every office pulls them instead of building: the origin on the machine that builds, and on every other office a mirror that pulls from it over the link |
| [`indox`](indox/) | INDOX · מסמכים נכנסים | End-to-end incoming-document processing — sync, extract, file and browse |
| [`lan-console`](lan-console/) | Console on the LAN · הקונסול ברשת המקומית | This office's console at its LAN address, for a phone on the same Wi-Fi, with the same sign-in |
| [`mail`](mail/) | Mail · מייל | The whole mail capability — local mailbox, external-provider adapters, one abstraction API, and a UI |
| [`meet`](meet/) | Video meetings · פגישות לשכה | The office's video meetings — Jitsi Meet in Hebrew, from a browser or a phone; hosts sign in with the office account, guests join by link |
| [`my-docs`](my-docs/) | Documents · מסמכים | Business document ledger — invoices and documents |
| [`n8n`](n8n/) | Automations · אוטומציות | The automation engine — schedules, triggers, workflows |
| [`newsflow`](newsflow/) | NewsFlow · זרימת חדשות | Every news item that matters to BINA Solutions — collected through the office browser, organised by category, in one place |
| [`notify-relay`](notify-relay/) | Notice relay · ממסר ההתראות | On an office with no notice board of its own: every notice is carried to the herd's board over the link, and kept until it answers |
| [`obsidian`](obsidian/) | Obsidian · אובסידיאן | The office's vault — real Obsidian in the browser, on the office's vault folder |
| [`office-routes`](office-routes/) | Network · ניהול רשת | The office's own routes — what is reachable, from where, and at which address. Closed by default; opened from this screen. |
| [`ollama`](ollama/) | Ollama · מודלים מקומיים | Run local LLMs on your own hardware |
| [`openhands`](openhands/) | OpenHands · סוכן קוד | Autonomous coding agent |
| [`operatives`](operatives/) | Operative Collective · אוסף האופרטיבים | Every action the office can do, as one short plain-text recipe each: where it runs, and the one a request needs |
| [`portainer`](portainer/) | Portainer · Portainer | Docker container management |
| [`project-pln`](project-pln/) | Projects · ניהול פרויקטים | Self-hosted Plane — projects, work items, cycles and modules, with no cloud dependency |
| [`raphael`](raphael/) | Raphael · רפאל | The guardian agent's automations — scheduled n8n scans that trigger Raphael only on an anomaly. Owns no container; the agent itself is a bina-ds preset. |
| [`redisinsight`](redisinsight/) | RedisInsight · מפקח Redis | Browser and debugger for the cache and queues |
| [`signal`](signal/) | Signal · סיגנל | Signal Desktop, the official client, inside the office: its screen in the console, linked to the owner's phone. No API: Signal has no official headless side. |
| [`sites`](sites/) | Sites · אתרים | The business's websites end to end — and the office serves them itself at a public path: uptime, visits, security, SEO, beauty and content taken from digital assets |
| [`slack`](slack/) | Slack · סלאק | Slack's own Linux client inside the office: its screen in the console, and the CLI and the API on the owner's account (chat.v1). |
| [`social-list`](social-list/) | Social networks · רשתות חברתיות | Every social network the business is on behind one API — profile, posts, comments and reactions, through the office browser (browser42) or the network's own API |
| [`supabase`](supabase/) | Supabase · סופאבייס | Browse and manage the database — tables, storage and REST API |
| [`telegram`](telegram/) | Telegram · טלגרם | The office's Telegram — the owner's account, the chats the office listens to, and every message there as an event on the stream |
| [`telegram-tv`](telegram-tv/) | Telegram TV · טלגרם TV | The film library hiding inside Telegram channels — a row per chat, a card per film, a player that streams straight from Telegram |
| [`terminal`](terminal/) | Terminal · טרמינל | A command line on any machine in the office — pick a machine and work on it. Also opened from any row of the computers screen. |
