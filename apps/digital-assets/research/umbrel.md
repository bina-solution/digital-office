# Umbrel (Umbrel, Inc.) — net-front scan

> **Observed:** 2026-09-29 (one week after umbrelOS 2.0 shipped, on the last day of its launch-week discount).
> **Why Umbrel:** the closest analogue to Digital Office. It is a self-hosted home-server OS with a one-click App Store, and it also sells its own hardware.
> **Method:** primary sources first.
> - **GitHub:** API calls via `gh` for org and repo metadata, all 102 `getumbrel/umbrel` releases, manifests and README history.
> - **YouTube:** RSS feed, uploads playlist and per-video `publishDate`.
> - **X:** the public syndication endpoints, plus 6,254 tweet IDs archived in the Wayback Machine. Dates are decoded from the snowflake IDs; the text of about 150 key-date posts was fetched.
> - **Community:** the forum's Discourse JSON and the Discord invite API.
> - **History:** Wayback CDX and snapshots, plus the commits of the archived `getumbrel/umbrel-website` repo, which reconstruct the site before the first Wayback capture.
> - **Not used:** browser tools. No images were downloaded; visuals are described from page text, alt text, sizes and upload timestamps only.
>
> **Legend:** ✓ read from a primary source · ~ approximate or inferred · ? third-party or search-snippet only. The WebSearch budget ran out partway through, so late items rely on direct fetches (see §8).

---

## 1. Snapshot

**What it is.** Umbrel, Inc. makes umbrelOS, a browser-based home-cloud and home-server OS that installs self-hosted apps in one click from the Umbrel App Store. It also sells its own plug-and-play hardware: Umbrel Home and Umbrel Pro.
- **Legal and HQ:** the Terms of Service are governed by Delaware law. There is no HQ: "Our headquarters are on the internet" (seed post). The careers page describes the company as remote-first and flat ("zero managers"), with one annual retreat.

**Founders and origin.** Mayank Chhabra (cofounder & CEO) and Luke Childs (cofounder & CTO).
- In 2019 (~October, per Bitcoin Magazine/search) Mayank moved his Bitcoin node from the cloud to a Raspberry Pi.
- He designed a Figma UI prototype and presented it at a small Bitcoin/Lightning meetup in Chiang Mai, Thailand (~late Dec 2019).
- Luke, a UK open-source developer living in Thailand, attended that meetup. They had met a few days earlier at a Christmas Eve party, and Luke joined as cofounder "a few months later" (seed post ✓).

**First public trace.** The public identity was reserved on **2020-01-01**: the X account @getumbrel was created at 09:00 UTC and the GitHub org `getumbrel` at 09:03 UTC ✓.
- **2020-01-22:** a "Coming Soon" waitlist page went up ✓.
- **2020-08-16:** the product launched as an invite-only beta for waitlist users. It was positioned as "your personal Bitcoin node" ✓.
- **2020-12-30:** the App Store arrived ✓.
- **2021-08-05:** the pivot to "a personal server OS for everyone" came with v0.4 ✓.

**Funding.** One disclosed round: **$3M seed, announced 2021-10-29, led by OSS Capital** ✓.
- **Other investors:** Naval Ravikant, Sahil Lavingia, Slow Ventures, Andreas Antonopoulos, Owen Gunden, Max Webster, Stephen Cole, Fulgur Ventures, Mimesis Capital, Huat Ventures and Village Global ✓.
- **Before the seed:** the founders funded development from their savings ✓.
- **After the seed:** no later round was found (? search snippet says none).

**Hardware line.**
- Partner box from The Bitcoin Machines: 2021-09-29, $429/$559.
- Umbrel Home, 1st generation: 2023-05-30, $699.
- Upgraded Umbrel Home (N100): 2024-02-13, $399.
- All-new Umbrel Home (N150, up to 4 TB): 2025-06-10.
- Umbrel Pro (4× NVMe, CNC aluminium and walnut): 2026-02-04, $699 / 599 € / £529.

**OS line.**
- umbrelOS 1.0, a ground-up rebuild: 2024-03-18.
- umbrelOS 2.0: 2026-09-22.

**Scale indicators** (observed 2026-09-29 unless noted):

| Indicator | Value | Source |
|---|---|---|
| GitHub `getumbrel/umbrel` | 12,172 ★ · 804 forks · 109 watchers · 102 releases (2020-07-07 → 2026-09-22) | GitHub API ✓ |
| GitHub `getumbrel/llama-gpt` | 10,936 ★ (launched 2023-08-16) | GitHub API ✓ |
| GitHub `getumbrel/umbrel-apps` | 781 ★ · 712 forks · **392 app packages** (395 top-level dirs minus `.claude`/`.github`/`.tools`); marketed as "300+ apps" | GitHub API ✓ |
| GitHub org | 1,149 followers · 42 public repos | GitHub API ✓ |
| X `@umbrel` | **75,328 followers** · follows 1 · 17,817 posts | X syndication ✓ |
| YouTube `@UmbrelYt` | **13.7K subscribers** · 39 videos · 1,219,031 views | channel page ✓ |
| Discord | 4,118 members (522 online) | invite API ✓ |
| Telegram `t.me/getumbrel` | 4,236 members | t.me page ✓ |
| Forum `community.umbrel.com` | 8,507 users · 6,092 topics · 52,744 posts; last 30 days: 37 topics, 195 posts, 203 active users | Discourse `/about.json` ✓ |
| Reddit `r/getumbrel` | 7.8k | shields.io proxy ~ |
| Product Hunt | 583 followers · 4 launches | PH page ✓ |
| Instagram `@getumbrel` | 184 followers · 1 post (dormant) | IG meta ✓ |
| LinkedIn `company/umbrel` | ~716 followers (undated) | search snippet ? |
| Users | "over 13,000 people" running Umbrel; "90% of all the Lightning Network nodes launched over the last year" (both 2021-10-29) | seed post ✓ |
| Revenue | "$3.7M revenue, 5-person team, 2024" | getlatka.com ? (unverified; treat as rumor) |

---

## 2. Net-front inventory

### 2a. Website sections

| Channel | URL / handle | Exists since | Followers (date) | Profile bio / title (verbatim) | Avatar / banner (described) | What is posted there | Cadence | Notes |
|---|---|---|---|---|---|---|---|---|
| **Home** | umbrel.com (was getumbrel.com) | getumbrel.com 2020-01-22; umbrel.com live 2022-06-07 ✓ | n/a | Title "Umbrel - Personal home cloud and OS for self-hosting"; H1 "Your cloud, in your home." | OG card `umbrel.com/og/umbrel.jpg` 1200×630; hero = the product on a desk beside a laptop | Current-launch hero (umbrelOS 2.0 + keynote), product cards, 9 feature blocks, use-case categories, app-icon wall, iPhone/Mac app, "self-hosting vs. the cloud", cost math, path chooser, tweet wall, newsletter (§4) | Re-skinned at every major launch: 2020-06, 2020-10, 2022-06, 2023-05, 2024-02, 2026-02, 2026-09 | Next.js today; ~Framer in 2024–25 (`framer.umbrel.com/umbrelos` linked 2024-03-22). Has a live-chat support widget |
| **Product: umbrelOS** | umbrel.com/umbrelos | ≤2024-03-22; a dedicated `/umbrelos-1-0` page existed 2024-02 ✓ | n/a | "umbrelOS - An elegant OS for your home server"; H1 "Stores, streams, syncs, and just slaps." | UI screenshot carousel, box shots of Home/Pro | What's new in 2.0, six use cases (Files, Local AI, Bitcoin, Media, Network, Automation), "The craft" details, privacy, 8 channel videos | Per OS release | CTAs "Watch the keynote" / "Download umbrelOS" / "Buy an Umbrel" |
| **Product: Umbrel Home** | umbrel.com/umbrel-home | 2023-05-30 ✓ | n/a | "Umbrel Home \| Plug and Play Home Cloud Server"; "More room. More responsive." | Renders, lifestyle photos, "bento" hardware close-ups | 5 use cases with apps, two-step setup, specs table, box contents, Home-vs-Pro comparison, 5 embedded videos | Per hardware revision (2023, 2024, 2025) | JSON-LD offer $599–$949 USD (2026-09-29) |
| **Product: Umbrel Pro** | umbrel.com/umbrel-pro | 2026-02-04 ✓ | n/a | "Umbrel Pro \| Home Cloud with up to 32TB storage"; H1 "32 terabytes of cloud. On your desk." | 3D renders, thermal diagrams, lifestyle, 7 videos | Use cases, design (aluminium + American walnut), FailSafe, 3-step setup, specs, FAQ | Launched once | JSON-LD offer $699–$1,899 USD; the launch PH tagline said "16TB" |
| **Store / pricing** | in-page cart on product pages | ~2023-05-30 (pre-orders) | n/a | "Choose your storage size" / "Choose your Umbrel Pro" | — | Storage configurator (1/2/4 TB; Pro 0/2/4/8 TB pre-installed), "What will you use your Umbrel for?" recommender, Umbrel Protect add-on ("2 years of total protection") | Promo banners at launches ("10% off … until Sep 29") | "Shipping to {country}. All customs duties & taxes prepaid." |
| **Downloads** | umbrel.com/downloads | unknown | n/a | H1 "Your hardware. Your cloud." | — | umbrelOS 2.0.0 images: Intel/AMD `.img.xz` 1.5 GB, Raspberry Pi 5/4 `.img.zip` 1.3 GB, VM `.iso` 1.8 GB; beta-program link; iPhone/Mac app links | Per release | Artifacts at `download.umbrel.com/release/<ver>/` |
| **Docs / support** | umbrel.com/support | unknown (guides lived on the forum in 2021–23) | n/a | "How can we help?" / "Chat with us or search our knowledge base." | Thumbnail per featured article | ~72 articles in 12 categories (§4); live chat; links to forum/Discord; person43@example.com | Updated at each release (e.g. "What is Umbrel?" last updated 2026-09-23) | Article = title, "last updated", screenshots |
| **Blog** | blog.getumbrel.com (Medium; was medium.com/getumbrel) | 2020-12-30 (first post) ✓ | n/a | Publication "Umbrel Blog" | Medium header images | 7 posts only: launch essays, the seed/manifesto, a license explainer, one how-to | ~1–2/yr; **dormant since 2024-02-13** | Long-form moved to YouTube keynotes and forum posts |
| **Changelog / releases** | github.com/getumbrel/umbrel/releases | 2020-07-07 ✓ (umbrel-os builds from 2020-02-25) | n/a | "umbrelOS X.Y" | 4:3 "bento" hero image per release | Release notes + download list (§4) | 102 releases; 2020: 25 · 2021: 25 · 2022: 12 · 2023: 1 · 2024: 19 · 2025: 11 · 2026 (to Sep): 9 | Also in-OS "release history" in the 2.0 App Store |
| **Community / forum** | community.umbrel.com (was community.getumbrel.com) | Discourse created 2021-03-29; announced 2021-04-30 ✓ | 8,507 users (2026-09-29) | "A friendly place to discuss all things Umbrel and to connect with the community." | — | Announcements (49 topics), Support (3,750), General (726), Bitcoin & Lightning (612), Guides (147) | Announcements: 2021: 20 · 2022: 12 · 2023: 3 · 2024: 6 · 2025: 5 · 2026: 3 | Founder posts every launch |
| **App store (web)** | apps.umbrel.com | 2023-03-07 ✓; rebuilt 2026-05-07 ✓ | n/a | "Umbrel App Store: Discover self-hosted apps for your home server"; H1 "Hundreds of apps. One home server. All yours." | App icons (256 px SVG), 1440×900 gallery | "Serving hot now", carousel, "Most installs", "New arrivals", categories, all-apps sort | Continuous (per app PR) | Per-app badges `apps.umbrel.com/api/app/<id>/badge-{dark,light}.svg` |
| **App store (in-OS)** | umbrelOS › App Store | 2020-12-30 (v0.3.0) ✓ | n/a | "The superpowers are endless." | — | Discover, categories, featured collections, search, update shelf, compatibility checks, release history (2.0) | Continuous | Community App Stores since 0.5.2 (2022-10-25) |
| **Careers** | umbrel.com/careers | hiring call 2021-10-29 (seed post); page date unknown | n/a | "Build the future of Umbrel." / "Our most important work lies ahead of us, and you can be a part of it." | — | Values, how we work, 8 remote roles (FE, BE, full-stack, native lead, systems, electrical design, product design, marketing lead), benefits | Evergreen | Apply at person44@example.com with three "why"s |
| **About / manifesto** | none as a page | — | n/a | — | — | Covered by support "What is Umbrel?", the home-page "Self-hosting vs. the cloud" block, and the seed post "How it all began" | — | Gap to copy: no About page |
| **Press / brand kit** | none found | — | n/a | — | — | Only an "As seen on" strip: 9to5Mac, Gizmodo, Decrypt, XDA Developers, heise online | — | Logos circulate via Simple Icons (hex 5351FB) and aggregators |
| **Newsletter** | footer form "Stay in the loop" | waitlist email capture since 2020-01-22 | unknown | "Follow our journey in helping people truly own their data. Better yet, be a part of it." | — | Email signup only; no public archive | unknown | Provider unknown |
| **Affiliates** | affiliate.umbrel.com | unknown | n/a | "Share something worth owning. Earn along the way." | — | 10% per Home/Pro sale, capped at $50/$70 per unit, 30-day cookie, $100 payout threshold, approval within 3 days, no follower minimum | Evergreen | Creator/YouTuber channel |
| **Legal** | umbrel.com/legal/* | ToS updated 2023-05-30 | n/a | "Umbrel, Inc." | — | ToS, privacy, umbrelOS ToS, returns, shipping, warranty, Umbrel Protect | Per hardware launch | — |
| **Short links** | link.umbrel.com/* | ≤2021-08 (bit.ly before) | n/a | — | — | e.g. `/ios-app`, `/macos-app`, `/pi-update`, `/surprise` (0.5 announcement) | Per launch | Keep campaign links stable |
| Historical | testnet.getumbrel.com | 2020 | n/a | — | — | Public testnet demo node (early README) | retired | — |

### 2b. Off-site channels

| Channel | URL / handle | Exists since | Followers (date) | Profile bio (verbatim) | Avatar / banner (described) | What is posted there | Cadence | Notes |
|---|---|---|---|---|---|---|---|---|
| **GitHub** | github.com/getumbrel | 2020-01-01 ✓ | 1,149 org followers; umbrel 12,172 ★ (2026-09-29) | "The ultimate home server and home cloud OS. Buy an Umbrel Home, or install umbrelOS on a Raspberry Pi." | Not inspected. README banner `static.getumbrel.com/github/github-banner-umbrel.svg` (2020) | Code, releases, app manifests, app-submission PRs, Community App Store template, LlamaGPT | Commits weekly; releases ~monthly (2024–26) | Repo description (sic): "An elegant home server OS. Run OpenClaw, store your files and, and do more with over 300 apps in the Umbrel App Store." README badges use `#5351FB` since 2020-07 |
| **YouTube** | youtube.com/@UmbrelYt (ID `UC2LGxBlCmo8ItKUedN2A9dQ`) | joined 2020-05-25; first public upload 2021-08-06 ✓ | 13.7K subs, 1.22M views (2026-09-29) | Starts "Umbrel is a small computer that lives in your home, and becomes your cloud. Not the kind you sit at." | Not inspected | Launch films, trailers, the 2.0 keynote, hardware making-of/unboxing/setup, feature explainers, tutorials, shorts/ads (§5) | 39 videos total; 2021: 1 · 2022: 1 · 2023: 6 · 2024: 3 · 2025: 11 · 2026: 17 (≈2/mo, launch-clustered) | Top videos: umbrelOS 1.0 intro 285K; Making Umbrel Pro 235K; 2.0 keynote 101K; 2.0 trailer 88K |
| **X** | x.com/umbrel (was @getumbrel) | 2020-01-01 ✓; renamed to @umbrel between 2022-02-14 and 2022-05-17 ~ | 75,328 (2026-09-29); gained ~700 in 18 h on 2020-08-26 | Name "Umbrel ☂️". Bio: "Your private home cloud for files, photos & videos storage, local AI models and agents (OpenClaw/Hermes), Bitcoin node & more ✨ → https://t.co/Y8ayOgyTrH". 2020-03 bio: "#Bitcoin and #Lightning⚡️ like never before. Coming soon" | Avatar image uploaded 2025-01-30, banner uploaded 2026-02-07 (decoded from image URLs; visuals not inspected) | Teasers, launch threads, app-arrival posts, memes, polls, promo countdowns, reposts of user praise | 17,817 posts in 81 months ≈ 220/mo incl. replies and reposts; launch weeks show ~1–3 originals/day plus reposts | Primary launch channel. The bio is rewritten to name the hottest feature/app (e.g. 🦞 OpenClaw) |
| **LinkedIn** | linkedin.com/company/umbrel | unknown | ~716 (undated) ? | "A beautiful OS to run a server in your home" ? | Not accessible | Hiring (inferred) | unknown | Walled; snippet only |
| **Facebook** | none found | — | — | — | — | — | — | Only user groups mention Umbrel |
| **Instagram** | instagram.com/getumbrel | unknown | 184 (2026-09-29) | "Personal Server OS for Everyone" | Not inspected | 1 post | Dormant | The 2021 tagline was never updated |
| **TikTok** | none found | — | — | — | — | — | — | Vertical video goes to YouTube Shorts instead |
| **Discord** | discord.gg/efNtFzqtdx | server created 2022-01-28 ~ (from snowflake) | 4,118 members (2026-09-29) | "Stay connected with the latest updates, discussions, and troubleshooting tips. Engage, share ideas, and get help." | Not inspected | Chat, beta feedback (release notes point here) | Continuous | Replaced Telegram as the main chat |
| **Telegram** | t.me/getumbrel | ≤2020-07-07 (README badge) ✓ | 4,236 (2026-09-29) | "Umbrel (Official)" · "umbrel.com" | Not inspected | Early community chat ("#umbrelheads", 2020) | Legacy | Primary support channel in 2020–21 |
| **Reddit** | reddit.com/r/getumbrel | ≤2020-07-07 (README badge) ✓ | 7.8k ~ (2026-09-29, shields.io) | unknown (walled) | unknown | User community | unknown | Listed in the site footer |
| **Product Hunt** | producthunt.com/products/umbrel | first launch 2022-06-07 ✓ | 583 | "The ultimate home cloud & OS for self-hosting" | — | 4 launches: Umbrel (2022-06-07, 195 upvotes) · Umbrel Home (2023-05-31, 31) · umbrelOS 1.0 (2024-03-20, 145) · Umbrel Pro (2026-02-09, 328–344, #3 of the day) | 1 per major launch | Announced with an "Aaaand we're live on @ProductHunt" tweet |
| **Hacker News** | founder account `mayankchhabra` | 2022-06-07 ✓ | — | — | — | Show HN: Umbrel (2022-06-07, 225 pts/135 comments) · home server (2023-05-30, 13) · LlamaGPT (2023-08-16, 225/75) · Files (2025-01-27, 1) · Umbrel Pro (2026-02-05, 2/8). Earned: "Umbrel – Personal Cloud" (2025-12-15, 220/122) | Big launches only | The founder answers in comments |
| **Newsletter / email** | footer form | 2020-01-22 (waitlist) ✓ | unknown | see above | — | 2020: beta invites in waves of 100/200/400 | unknown | No archive |
| **Podcast** | none found | — | — | — | — | — | — | Gap (§8) |
| **Events** | none found | — | — | — | — | Internal annual retreat only (careers page) | — | The 2020 prototype was shown at a meetup |
| **Merch** | none found | — | — | — | — | — | — | — |
| Docker Hub | hub.docker.com/u/getumbrel | ~2020 | unknown | — | — | Official app images (bitcoin, lightning, …) | Per app update | Supply-chain channel |

---

## 3. Identification

### Name and handles

| Item | Value | Notes |
|---|---|---|
| Company / brand | **Umbrel** (legal: Umbrel, Inc.) | The display name carries the ☂️ emoji as a glyph: "Umbrel ☂️" on X, Instagram and the 2020 og:title |
| OS | **umbrelOS**, lowercase u + OS | Called "Umbrel OS" in 2020–22 builds and "Umbrel vX" releases until 0.5.3. **The first release named "umbrelOS" was 0.5.4 (2023-06-21)** |
| Hardware | Umbrel Home · Umbrel Pro | Revisions are labeled by year ("Umbrel Home (2025)") |
| Store | Umbrel App Store (apps.umbrel.com) | Badge copy: "Get it on umbrelOS" |
| Native apps | Umbrel for iPhone · Umbrel for Mac | Android and Windows "coming soon" |
| Handle split | `getumbrel`: GitHub, Instagram, Telegram, Reddit, Docker Hub, Medium, old domain getumbrel.com · `umbrel`: X (since 2022), LinkedIn, umbrel.com · `@UmbrelYt`: YouTube | The "get-" prefix is from the pre-domain era; umbrel.com was acquired by the 0.5 launch (2022-06-07) |

### Taglines over time

| Date | Where | Tagline (verbatim) |
|---|---|---|
| 2020-01-22 | getumbrel.com | "Umbrel \| Coming Soon" · "Be the first one to know when we launch" |
| 2020-03 | X bio | "#Bitcoin and #Lightning⚡️ like never before. Coming soon" |
| 2020-04-25 | getumbrel.com | "Umbrel Bitcoin and Lightning Node" · "Request early access" |
| 2020-06-06 → 2020-10 | getumbrel.com | "Become Bitcoin" (title "Umbrel - Become Bitcoin") |
| 2020-07 (X) | posts | "Running #Bitcoin" / "Running #Lightning⚡️" / "Running #Umbrel☂️" (echoes Hal Finney's 2009 "Running bitcoin") |
| 2020-10 → 2022-06 | getumbrel.com | "Umbrel — your personal Bitcoin node." · H1 "running a node is for everyone." |
| 2021-08-05 | X / blog | "A Personal Server OS for Everyone" |
| 2021-10-29 | blog | "get a server in every home" |
| 2022-06-07 | umbrel.com | "A beautiful personal server OS for self-hosting." · "De-google yourself." |
| 2023-05-30 | X | "Home is where your data belongs." |
| 2023-06 | umbrel.com | "The ultimate home server and OS for self-hosting" · "Goodbye, cloud. Hello, server in your home." |
| 2024-03 → now | umbrel.com title | "Personal home cloud and OS for self-hosting" |
| 2025-01-27 | X (Files) | "All your files. Under your roof." |
| 2026-02-04 | X (Pro) | "The ultimate home cloud server." |
| 2026-09 | umbrel.com H1 | "Your cloud, in your home." · "The cloud is just someone else's computer. Umbrel is yours." |
| 2026-09 | /umbrelos | "An elegant OS for your home server" · "Stores, streams, syncs, and just slaps." |
| 2026-09-22 | X (2.0) | "Just a small computer, at home, that becomes your cloud." |

The arc runs: *become Bitcoin* → *personal server for everyone* → *beautiful personal server OS* → *ultimate home server* → *personal home cloud*. Each rename followed a new audience, but "node" and "sovereignty" copy is kept for the Bitcoin base.

### Descriptions

- **Short (≤160):**
  - GitHub org bio: "The ultimate home server and home cloud OS. Buy an Umbrel Home, or install umbrelOS on a Raspberry Pi."
  - Product Hunt: "The ultimate home cloud & OS for self-hosting".
- **Meta description (site-wide, verbatim):** "Bring the cloud to your home with umbrelOS - a beautiful home server OS for self-hosting, and Umbrel Home and Umbrel Pro - plug-and-play home servers. Install Nextcloud, Jellyfin, Bitcoin node, and hundreds of self-hosted apps in one click."
- **Long (support "What is Umbrel?", summarized):**
  - Umbrel is a small device in your home that stores files, backs up photos, streams media and runs your own AI. You get cloud convenience while the data stays with you, used from any browser plus the iPhone/Mac apps.
  - umbrelOS is the OS that powers every Umbrel, pitched as "macOS or Windows for your home server". It sets up in minutes with no technical skills.

### Terminology glossary (Umbrel's own nouns)

| Term | Meaning |
|---|---|
| umbrelOS | The OS: browser UI, App Store, built-in apps |
| "your Umbrel" | The user's server, whatever its hardware |
| Umbrel Home / Umbrel Pro | First-party servers: palm-sized N150 up to 4 TB / 4× NVMe N300 up to 32 TB |
| DIY hardware | umbrelOS on a Raspberry Pi, x86 PC/NAS or VM ("Choose your path: Plug it in. Go Pro. Or build it.") |
| umbrel.local | The local address that opens the dashboard ("Go to umbrel.local") |
| Umbrel App Store | The in-OS store and apps.umbrel.com |
| Community App Store | Third-party store added by URL; there is a template repo |
| Official app | First-party app ("An official app from Umbrel"), e.g. Bitcoin Node, Lightning Node |
| Swappable apps / `implements` | Alternative apps that satisfy a dependency (Bitcoin Knots for Bitcoin Node; Fulcrum for Electrs) |
| Widgets | Live home-screen cards served by apps (Widgets API, 7 types) |
| Dock / wallpapers | macOS-like dock (since 0.5) and hand-curated wallpapers; the wallpaper also sets the UI accent color |
| ⌘K / Ctrl-K search | Universal search over apps, files, photos and settings |
| Quick actions | Right-click menus on icons and the desktop |
| Live Usage | Real-time CPU/RAM/storage/GPU per app |
| Files | Built-in file manager (1.4) with SMB sharing and Time Machine target |
| Rewind | "Time travel" restore from backups inside Files (1.5) |
| Backups | Encrypted hourly/daily/weekly/monthly snapshots to USB, NAS or another Umbrel |
| Umbrel Private Cloud | Announced E2E-encrypted "trustless" cloud backup (early access, 2025-09) |
| Photos | Built-in photo library (2.0) fed by the iPhone app |
| Machines | One-click VMs (Windows, Ubuntu, Debian, Android) in the browser (2.0) |
| FailSafe (Mode) | RAID (ZFS raidz1) across drives; can be enabled later without wiping |
| Storage Manager | Combine drives, FailSafe, SSD acceleration (2.0) |
| Download from cloud | Pull or mirror Dropbox, OneDrive, iCloud Drive, Nextcloud, WebDAV (2.0) |
| AI agents / MCP server | Connect Claude Code, Codex, OpenClaw, Cursor with scoped, revocable tokens (2.0) |
| Shortcuts | Home-screen tiles for URLs, ports and Docker containers (1.7) |
| umbrelOS Beta Program | Opt-in public betas under Settings › Advanced settings (1.1+) |
| Umbrel Protect | 2-year hardware protection add-on |
| Migration Assistant | Move everything to a new Umbrel (0.5.4) |
| Bento | Internal name for the grid-style hero image of a release ("bento 2.0", "files_app_launch_bento") |
| #umbrelheads | Community nickname coined in 2020 ("thankfully not 'umbrellas'") |
| home cloud / personal server | Category nouns (2021–23 "personal server"; 2024+ "home cloud") |

### Colors

| Name | Hex | Source |
|---|---|---|
| Brand violet (canonical) | `#5351FB` | Simple Icons (source umbrel.com); GitHub README badges since 2020-07 ✓ |
| Website brand token | `#5351F3` (`--color-brand`) · hover `#4543DF` · soft `#8583FF` | umbrel.com CSS ✓ |
| Accent teal | `#14B8A6` (`--color-accent-teal`) | umbrel.com CSS ✓ |
| Violet ramp | `#C4B4FF` · `#A685FF` · `#8D54FF` | umbrel.com CSS ✓ |
| Base neutral | `#09090B` (zinc-950) + white alphas (`#FFFFFF1A`–`#FFFFFFE6`) | umbrel.com CSS ✓ (dark glass UI) |
| umbrelOS UI | destructive `#E03E3E` · success `#299E16` · dialog `#1E1E1E` · theme-color `#000000`; the accent (`--color-brand`) **is derived from the chosen wallpaper's HSL** | `packages/ui/tailwind.config.ts`, `providers/wallpaper.tsx` ✓ |

### Typography

- **Website headings:** Google Sans (fallback "Product Sans", then Inter).
- **Website body:** Inter (variable).
- **Website accents:** a narrative italic accent in Playfair (`--font-narrative-accent`), plus Dancing Script preloaded on the home page ✓. Its use as a handwritten accent is inferred ~.
- **umbrelOS UI:** Inter for sans, Roboto for mono ✓.

### Theme

Dark-first everywhere: black and zinc backgrounds, translucent "glass" panels, blurred wallpapers (glassmorphism, named explicitly in the 1.0 blog post), and a violet accent. Dark mode shipped as a headline feature of 0.5 (2022). Marketing shots are dark UI on bright lifestyle or desk photography.

### Logo and usage (not visually inspected)

- **Brand glyph:** the ☂️ emoji in display names.
- **Wordmark:** "umbrelOS" is always lowercase-u in running text.
- **Assets:** a README banner SVG, and App Store badges in dark and light variants ("Get it on umbrelOS"), generated per app.
- **Press kit:** none official. Third-party logo sites republish the mark with `#5351FB`.

### Illustration style

- **Hardware:** product renders (3D hero) and lifestyle desk photography.
- **Release visuals:** "bento" grid composites for each release at 4:3 (3000×2250 or 3840×2880); browser-framed UI screenshots; app-icon walls (60+ icons).
- **Proof and data:** tweet cards as testimonials, and a cost chart ("Do the math").
- **Craft footage:** CNC machining macro footage (Making Umbrel Pro).
- **Motion:**
  - 40–70 s launch films at 16:9 (to 2024) and 4:3 (1440×1080 / 1920×1440, 2025–26).
  - 43–58 s trailers and a 10:53 keynote with chapters.
- **Early era (2020):** 1440×900 app cards and lowercase meme images.

### Voice and tone

Two registers, used deliberately:

1. **Keynote-declarative** for announcements:
   - "Introducing X." followed by sentence fragments ("Out today." / "Rolling out today." / "Ships worldwide, Feb 9.").
   - Superlatives ("our biggest update ever", "the ultimate home cloud").
   - Rhythmic triads ("Stores, streams, syncs…").
2. **Lowercase meme-native** for everyday X posts:
   - Examples: "we cooked", "locked in", "wen big update umbrel", "lfggg", "ayyyy folks", "running out of space on your umbrel? …".
   - Bitcoin-culture humor was the 2020 base ("Running $USD 💵", the SSH password "moneyprintergobrr").

Constant themes across both: anti-Big-Tech ownership framing ("someone else's computer"), privacy and sovereignty, craft and beauty, and gratitude to the community ("Umbrel Pro exists because of you."). Founders and team appear on camera (Luke's install demo, nmfretz's Photos demo).

---

## 4. Content structure

### About / who we are

There is no About page. The story is spread across three places:
- The support article "What is Umbrel?" (sections: umbrelOS → Umbrel apps for iPhone and Mac → Umbrel Home and Umbrel Pro → What can you do with Umbrel?).
- The careers page (mission, how we work, benefits).
- The seed post's "How it all began": Pi node → Figma prototype → Chiang Mai meetup → cofounder → self-funded → launch 2020-08-16 → hiring.

### Docs and tutorials (umbrel.com/support)

- **Hub:** "How can we help?" with a live-chat button and 6 featured cards (Setting up Umbrel Pro, Setting up Umbrel Home, Connecting to your Umbrel, Installing an app, Using Files, Backing up your data).
- **Knowledge base:** 12 categories, ~72 articles (sitemap): Getting started (8) · Install on your own hardware (4) · Apps (8) · Basics (13) · Files (4) · Photos (5, including "Moving from Google Photos / Apple Photos / Immich") · Machines (1) · Storage (2) · Backups & recovery (3) · Troubleshooting (3) · Advanced (5, including "Connecting AI agents", "GPU acceleration") · App guides (3).
- **Article anatomy:** title, "last updated" date, short intro, H2 sections, screenshots.
- **Video tutorials** (unboxing, setup, install, backup/restore) live on YouTube and are embedded on product pages.
- **Migration articles:** "Moving from X" pieces are a conversion device.

### App Store listing — every field of ONE listing (Immich)

**Source files.**
- Manifest: `getumbrel/umbrel-apps/immich/umbrel-app.yml`, next to `docker-compose.yml`, plus `exports.sh` and `hooks/` when needed.
- Assets: the separate repo `getumbrel/umbrel-apps-gallery/immich/`, which holds `icon.svg`, `1.jpg`, `2.jpg`, `3.jpg`.

**Manifest fields** (in the order the packaging guide requires for new packages; all values are from the live Immich manifest unless marked):

| Field | Type | Immich value (or example) | Rule / meaning |
|---|---|---|---|
| `manifestVersion` | number | `1.1` | App-framework compatibility (`1` default; `1.1` enables hooks; e.g. `1.3` refuses older umbrelOS) |
| `id` | kebab-case string | `immich` | = directory name; stable forever |
| `implements` | app id | (e.g. Bitcoin Knots → `bitcoin`) | Only for real drop-in providers ("swappable apps") |
| `storage.dataRoot` | path | `data` | Where app data lives (2.0 storage management) |
| `folderAccess[]` | list {id, name, note, mounts[{service, targetPath, readOnly}]} | "External Library" → `/mnt/external-library`, read-only | User-selectable folders (2.0) |
| `category` | enum | `files` → shown as "Files & Productivity" | Taxonomy ids seen: `files`, `bitcoin`, `media`, `networking`, `social`, `automation`, `finance`, `ai`, `developer` |
| `name` | string | `Immich` | Upstream name users recognize |
| `version` | string | `"v3.2.2"` | Upstream version, never `latest` |
| `tagline` | string (~50 chars) | "High-performance photo and video backup solution" | Shown under the name everywhere |
| `description` | folded markdown (`>-`) | intro paragraph → ⚠️ warning → "Features:" bullet list | Put first-run and security notes at the top |
| `releaseNotes` | folded markdown | what changed → breaking-change ⚠️ → fix summary → "Full release notes can be found at <url>" | Empty (`""`) on first submission; shown as "What's new" |
| `developer` | string | `Alex Tran` | Links to `website` |
| `website` | url | `https://www.immich.app` | — |
| `dependencies` | list of app ids | `[]` (Bitcoin apps list `bitcoin`, `electrs`) | Must be installed first |
| `repo` | url | `https://github.com/immich-app/immich` | Shown as "Source code: Public" |
| `support` | url | `https://github.com/immich-app/immich/discussions` | — |
| `port` | int | `2283` | Unique host port for the app URL |
| `gallery` | list of filenames | `[1.jpg, 2.jpg, 3.jpg]` | **3–5 images, 1440×900**; submitted as screenshots/PNG, finalized and hosted by Umbrel |
| `path` | string | `""` | Sub-path appended to the URL |
| `defaultUsername` / `defaultPassword` | string | `""` / `""` | Shown to the user on first open |
| `deterministicPassword` | bool | (Nextcloud: `true`) | Displays the per-install `APP_PASSWORD` |
| `torOnly` | bool | (Nextcloud: `false`) | Legacy Tor flag |
| `permissions` | list | `[GPU]` | Also `STORAGE_DOWNLOADS` |
| `widgets[]` | list {id, type, refresh, endpoint, link, example} | (Bitcoin Node: `four-stats` 5 s, `text-with-progress` 2 s) | Types: text-with-buttons, text-with-progress, two-stats-with-guage [sic], three-stats, four-stats, list, list-emoji |
| `backupIgnore` | list of globs | (Bitcoin Node: `data/bitcoin/blocks` …) | Exclude regenerable data from Backups |
| `icon` | url | omitted | Official store: **256×256 SVG, square, no rounded corners** (rounded by CSS), hosted in the gallery repo; community stores may set `icon` |
| `submitter` | string | `levma` | Shown as "Submitted by" |
| `submission` | url | `https://github.com/getumbrel/umbrel-apps/pull/239` | The PR or commit |

**Web listing anatomy** (apps.umbrel.com/app/immich), top to bottom:
1. Title "Immich | Umbrel App Store".
2. Icon, name, tagline, and the button "Get it on umbrelOS".
3. Gallery (3 images).
4. Info card: Version · Category (linked) · Source code "Public" · Developed by · Submitted by · Compatibility "umbrelOS 0.5 or later".
5. Description.
6. "What's new": one entry per version with its date and a release-notes link.
7. Related apps (6).
8. Footer "Explore umbrelOS" with the disclaimer "Trademarks and copyright of all apps belong to their respective developers."

**Submission flow.**
- **2026 pull-request template:** title patterns `Add <app>` / `Update <app> to <version>` / `Fix <app> <issue>`, then Type → App (id, upstream, version) → Summary → Verification (device/local/none; amd64/arm64) → Notes (permissions, dependencies, credentials) → screenshots and a logo reference.
- **Asset handling:** Umbrel's team pins image digests, resolves port conflicts, and designs the final gallery.
- **Contributor guide:** since 2026-06 it is agent-first. `AGENTS.md` routes to `.claude/skills/{umbrel-package-app, umbrel-update-app, umbrel-test-app, umbrel-develop-app}`, with a linter.

**Store taxonomy** (display names seen): AI · Bitcoin · Files & Productivity · Finance · Media · Networking · Home & Automation (+ Social, Developer ids). The home page groups the store as Files · Local AI · Bitcoin · Media · Network · Automation, each with 3 featured apps.

### Website home page — sections in order (umbrel.com, 2026-09-29)

1. Promo bar: "Last day - 10% off Umbrel Home & Pro until Sep 29". Geo line: "Shipping to {country} — All customs duties & taxes prepaid."
2. Nav: Umbrel Home · Umbrel Pro · umbrelOS · App Store · Support.
3. Hero: H1 "Your cloud, in your home." · sub "The cloud is just someone else's computer. Umbrel is yours." · one-sentence body listing jobs (photos, files, movies, AI, Bitcoin node) · desk hero image.
4. "As seen on": press logos.
5. Product tiles: Umbrel Home "Palm-sized home cloud." · Umbrel Pro "The ultimate home server." · umbrelOS (NEW) · App Store "The superpowers are endless." · Support "Help is always at hand."
6. umbrelOS 2.0 (NEW): "Our biggest update ever." · "Watch the keynote (10:53)" · UI screenshot carousel.
7. Nine feature blocks, each a headline plus a NEW badge: "Your photos, finally home." · "Run entire operating systems." · "300+ Apps. One Click." · "Bring your cloud home." · "A home cloud for everyone." · "Your AI can use it too." · "Effortless Storage" · "Private by Design" · "Built-in Backups".
8. Use cases: "Everything the cloud promises. Nothing it takes." Six categories × 3 apps, with an icon wall.
9. App Store: "Hundreds of apps. One home server. All yours." → "Browse the App Store".
10. Umbrel app (NEW): "Your cloud, in your pocket." → Download for iPhone / Mac (Windows/Android soon).
11. "Self-hosting vs. the cloud": "Keep the convenience. Change who holds the keys." Four rows: Ownership / Cost ("Rent, forever." vs "Buy once.") / Privacy / Lock-in & control ("Their house, their rules." vs "Your house, your rules.").
12. "Do the math": "iCloud 2TB is $120 a year. Forever." Compared after 1, 5 and 10 years against one purchase.
13. "Choose your path": "Plug it in. Go Pro. Or build it." DIY / Home / Pro with a comparison table.
14. "From the community": "Nothing but love from people coming home." About 9 embedded tweets with handles and dates.
15. "Start your journey": "Learn the ideas. Then pick your first app." (Why self-host? · What is Umbrel? · Run a Bitcoin node · Host your files).
16. Closing line: "Because the cloud doesn't have to be somewhere else. It can be home." Then "Stay in the loop" and the email field.
17. Footer: Products · Community (Forum, Discord, Reddit, X, Telegram) · Company (GitHub, Careers, Affiliates, Legal, Partner email) · © 2026 Umbrel.

(Items 11–15 come from the page's embedded data; their exact order may differ slightly.)

### Blog post types (Medium, 2020-12 → 2024-02)

- **Launch essay "Introducing X — <positioning line>":**
  - Hook ("One year ago it was a dream. Today, it's real.")
  - Video embed.
  - "The story/backstory", then "Under the hood".
  - One H2 plus screenshot per feature.
  - Hardware tie-in with a three-currency price.
  - "The road ahead", then "Your role" (Discord and forum CTA) and a warm sign-off.
- **Funding/manifesto post:** journey metrics → mission → the personal-computer → personal-server analogy → round and investors → origin story → "We're hiring" → thank-you.
- **Policy explainer:** "Everything you need to know about Umbrel's new license" (PolyForm Noncommercial, 2021-08-05).
- **How-to:** "How to install Umbrel on Casa Node 2", timed to a competitor sunsetting its node.

### Newsletter

The only visible element is the email field ("Stay in the loop"). In 2020 the waitlist email drove the phased beta invites. No archive and no cadence are visible (§8).

### News / press

There is no press page. Coverage is earned around funding and hardware:
- Bitcoin Magazine: 2021-09-29, 2021-10-29, 2023-05-30.
- The Block: 2021-08.
- Nasdaq syndication.
- The "As seen on" logos: 9to5Mac, Gizmodo, Decrypt, XDA Developers, heise online.

### Releases / changelog — format of ONE entry (umbrelOS 1.7, 2026-04-27)

- **Tag and title:** tag `1.7.0`, title "umbrelOS 1.7". Pre-releases use "umbrelOS 1.7 Beta 1" and are flagged pre-release.
- **Line 1:** "umbrelOS 1.7 brings <5 features>, and several performance improvements and bug fixes."
- **Keynote link** (major releases only): "→ Watch the keynote".
- **Hero:** a 4:3 "bento" image, e.g. `umbrelOS_1.7_-_Bento` at 3000×2250.
- **`### New features`:** bullets in the form `**Shortcuts:** one or two benefit sentences`, usually 5–12 of them.
- **Community CTA:** "Join the Umbrel Community Discord to share your feedback on this update…"
- **`### Downloads`:** `SHA256SUMS`, `SHA256SUMS.ots` (OpenTimestamps), `umbrelos-amd64-usb-installer.iso`, `umbrelos-amd64.img.xz`, `.update` files, and Pi `.img.zip`.
- **2020–21 format, for contrast:** one intro line, then an auto-generated commit list ("- Add X (#333) sha (@author)"), then a `Diff:` compare link.
- **Minor releases** use the same shape with sections New features / Enhancements / Bug fixes.

### Forum announcement format (Announcements category, founder-authored)

1. "Hey everyone,"
2. One line of excitement.
3. "→ Watch the reveal: <YouTube>"
4. The bento image.
5. Feature one-liners.
6. "To try it today…" with the beta-enrolment path or download link.
7. A request for feedback in the thread.
8. A date promise ("See you on September 22.").
9. Arrow link list: product page, iPhone app, Mac app, X announcement.

Release-era titles follow the pattern "Umbrel 0.4.14 is now out with <headline apps>". Some are playful, e.g. "It's tappening — Announcing Umbrel v0.3.10" for Taproot.

### Vision / manifesto

The canonical text is the seed post (2021-10-29). It argues that the personal computer moved computing out of corporate mainframes, and the personal server will move it out of corporate data centers. Personal servers "will become as ubiquitous as the internet routers today". Surveillance capitalism is the enemy, and self-hosting means your data is never handed out.

Today the same idea is compressed into:
- the home-page pair "someone else's computer / Umbrel is yours";
- the four "Self-hosting vs. the cloud" rows;
- the careers-page mission: data ownership, no subscriptions, and delightful UX for NAS software "stuck in outdated paradigms".

---

## 5. Media timeline

Dates are UTC and derived from the primary source (X dates are decoded from post IDs). ~ marks an approximate date.

| Date | Stage | Channel(s) | Media | Title | URL | Note |
|---|---|---|---|---|---|---|
| 2019-10 ~ | pre-launch | X (founder) | post | Mayank moves his Bitcoin node from the cloud to a Raspberry Pi | https://blog.getumbrel.com/seed-6d09aa08f8ac | Origin story; month from a search snippet ~ |
| 2019-12 ~ | pre-launch | offline meetup | talk | Figma UI prototype shown at a Bitcoin/Lightning meetup in Chiang Mai | https://blog.getumbrel.com/seed-6d09aa08f8ac | Met Luke days earlier at a Christmas Eve party |
| 2020-01-01 | pre-launch | X, GitHub | accounts | @getumbrel and github.com/getumbrel created the same morning | https://github.com/getumbrel | X 09:00:05Z, org 09:03:48Z |
| 2020-01-22 | teaser | website | landing | getumbrel.com "Umbrel \| Coming Soon", "Be the first one to know when we launch" | https://github.com/getumbrel/umbrel-website/commits/master | Waitlist email capture |
| 2020-02-19 | pre-launch | GitHub | repo | umbrel-os repo; first build 0.0.1.6 on 02-25 | https://github.com/getumbrel/umbrel-os/releases | — |
| 2020-03-17 | teaser | X | repost | First archived X activity: repost of Hal Finney's "Running bitcoin"; bio "…Coming soon" | https://web.archive.org/web/20200324234023/https://twitter.com/getumbrel | Snapshot shows 1 post and ~6 followers (parsed) ~. The "Running X" motif starts here |
| 2020-04-25 | teaser | website | landing | "Umbrel Bitcoin and Lightning Node — Request early access" | https://github.com/getumbrel/umbrel-website/commit/45a718984f64f9a85a4cc2df93084b4fa305df3e | WebGL gradient page |
| 2020-05-11 | teaser | X | GIF | "Happy #Bitcoin Halving!" Block 630,000 arrives live on an Umbrel node | https://x.com/getumbrel/status/1259933148281835520 | First product glimpse (828×1250 GIF), pinned to a Bitcoin cultural moment |
| 2020-05-25 | pre-launch | YouTube | channel | Channel created | https://www.youtube.com/@UmbrelYt | No public upload until 2021-08-06 |
| 2020-06-06 | teaser | website | landing | Site v2 "Become Bitcoin" with share image | https://github.com/getumbrel/umbrel-website/commit/831eccdb735b27ba01717a699d43c26a3105ad46 | — |
| 2020-07-03 | teaser | X | image | "Running #Bitcoin" + dashboard screenshot (2880×1806) | https://x.com/getumbrel/status/1279097216578117632 | 281 likes. Next day: beta "coming out in ~2 weeks" |
| 2020-07-07 | release | GitHub | release | getumbrel/umbrel v0.1.2; v0.1.3-beta and Umbrel OS v0.0.4-beta on 07-08 | https://github.com/getumbrel/umbrel/releases | Code public before the "launch" |
| 2020-07-08 | community | X | image thread | "Running $USD 💵" meme thread | https://x.com/getumbrel/status/1280881278082904066 | Humor register established |
| 2020-07-13 | teaser | X | image | "Running #Lightning⚡️" screenshot | https://x.com/getumbrel/status/1282719857960644608 | 246 likes |
| 2020-07-19 | community | X (CTO) | photo | Luke's dev setup "Running Umbrel OS v0.0.4-beta.3" | https://x.com/lukechilds/status/1284780883191279616 | Founders building in public |
| 2020-08-15 | launch | X, GitHub | image + thread | "Running #Umbrel☂️" + phased-rollout thread; v0.2.0 | https://x.com/getumbrel/status/1294685944784646144 | Invites 100 → 200 → 400 "just like halvings"; Telegram "#umbrelheads" |
| 2020-08-16 | launch | email, X | post | Download invites sent to the first 100 waitlist users | https://x.com/getumbrel/status/1295022263083757569 | **The founders' official launch date** |
| 2020-08-22 | launch | email, X | post | Invites to the next 200 | https://x.com/getumbrel/status/1297201052672901121 | — |
| 2020-08-26 | milestone | X | post | "~700 new followers … in the last 18 hours" | https://x.com/getumbrel/status/1298655041625051136 | After an influencer shout-out |
| 2020-08-30 | release | X | image | v0.2.6 automatic Lightning channel backups; next 400 invites | https://x.com/getumbrel/status/1300161025841311744 | Release post doubles as a rollout update |
| 2020-09-09 | launch | email, X | post | Invites to *everyone* on the waitlist | https://x.com/getumbrel/status/1303733668242796544 | — |
| 2020-09-28 | release | X | image | v0.2.11 connects 8 wallets ("knock knock…") | https://x.com/getumbrel/status/1310605077246173191 | 284 likes |
| 2020-10-17 | launch | website, X | landing | All-new getumbrel.com: "no more waitlist", install steps, parts list | https://x.com/getumbrel/status/1317509698078208000 | General availability; site v3.0 |
| 2020-12-29 | teaser | X | post | "everyone asks 'when big update umbrel?' but no one asks how r u umbrel" | https://x.com/getumbrel/status/1343908945849507840 | 149 likes, one day before |
| 2020-12-30 | release | X, blog, GitHub | thread + article | Introducing the Umbrel App Store (v0.3.0, 7 apps) | https://blog.getumbrel.com/introducing-the-umbrel-app-store-7a2068c64a10 | 11-post X thread, 624 likes, 1440×900 app cards; https://x.com/getumbrel/status/1344291684243312643 |
| 2021-03-31 | community | blog | article | How to install Umbrel on Casa Node 2 | https://blog.getumbrel.com/install-umbrel-on-casa-node-2-94d1991359cb | Captures a sunsetting competitor's users |
| 2021-04-30 | community | forum | post | Introducing the new Umbrel Community forum | https://community.umbrel.com/t/introducing-the-new-umbrel-community-forum/40 | Discourse created 2021-03-29 |
| 2021-05-03 | release | forum | post | "It's tappening — Announcing Umbrel v0.3.10" | https://community.umbrel.com/t/its-tappening-announcing-umbrel-v0-3-10/452 | Punny release titles |
| 2021-08-05 | pivot | X, blog, forum, GitHub | video + thread + article | Umbrel 0.4 "A Personal Server OS for Everyone" | https://blog.getumbrel.com/introducing-umbrel-v0-4-e5b67d02c43a | X 1,824 likes, 47 s video (1152×720). Same day: license moved to PolyForm Noncommercial |
| 2021-08-06 | release | YouTube | video | Introducing Umbrel 0.4 (first public YouTube upload, 47 s) | https://www.youtube.com/watch?v=JRfJMx1C7NQ | — |
| 2021-09-29 | hardware | forum, press | post | Plug-and-play Umbrel server from The Bitcoin Machines ($429/$559) | https://bitcoinmagazine.com/business/umbrel-plug-and-play-bitcoin-node-self-hosting-server | Partner hardware came before its own |
| 2021-10-29 | funding | blog, forum, X, press | article | "Umbrel raises $3M in seed round to get a server in every home" + hiring | https://blog.getumbrel.com/seed-6d09aa08f8ac | 13,000+ users; OSS Capital lead |
| 2022-01-28 ~ | community | Discord | server | Discord server created | https://discord.gg/efNtFzqtdx | Date from the server snowflake |
| 2022-02/05 ~ | rebrand | X | handle | @getumbrel → @umbrel | https://x.com/umbrel | Window 2022-02-14 → 2022-05-17 (Wayback) |
| 2022-04-20 | release | GitHub | repo | umbrel-apps repo: App Store split from the core | https://github.com/getumbrel/umbrel-apps | App updates decoupled from OS updates |
| 2022-06-06 | teaser | X | posts | "the best is yet to come" · "wen big update umbrel…" · (06-07) "turn on post notifications" | https://x.com/umbrel/status/1533805351849852928 | Day-before and morning-of teasers |
| 2022-06-07 | launch · rebrand | X, YouTube, blog, forum, PH, HN, website | video + 10-post thread | Umbrel 0.5 "A beautiful personal server OS for self-hosting"; **umbrel.com goes live** | https://x.com/umbrel/status/1534164270459473921 | X 1,240 likes (63 s video). Show HN 225 pts/135 comments. PH 195 upvotes |
| 2022-09-06 | release | X | video | 7 media apps (Plex, Jellyfin, *arr): "become your own netflix" | https://x.com/umbrel/status/1567221691113426944 | 252 likes; casual voice |
| 2022-10-25 | release | forum, GitHub | post | 0.5.2: Community App Stores, Tor toggle, store search | https://community.umbrel.com/t/umbrel-0-5-2-is-here-with-community-app-stores-tor-access-toggle-search-in-app-store-and-more/9981 | Template repo 2022-09-25 |
| 2023-02-06 | release | YouTube, forum | video | Official Nostr Relay app | https://www.youtube.com/watch?v=YjNa1MKvdrs | Rides a trending protocol |
| 2023-03-07 | release | X, YouTube | video + thread | Introducing apps.umbrel.com + developer badges | https://x.com/umbrel/status/1633112336662773760 | 15 s video; badge card 3200×1800 |
| 2023-05-29 | teaser | X | image | "uh oh" | https://x.com/umbrel/status/1663138439322279936 | 387 likes, one day before |
| 2023-05-30 | hardware | X, YouTube, website, HN, press | video | Introducing Umbrel Home: pre-order at $699 | https://x.com/umbrel/status/1663534602366091269 | 1,309 likes, 46 s video; ships June 2023 |
| 2023-05-31 | hardware | Product Hunt | launch | Umbrel Home on Product Hunt | https://www.producthunt.com/products/umbrel | 31 upvotes |
| 2023-06-21 | release · rebrand | GitHub, YouTube, forum | video | umbrelOS 0.5.4: **first release named "umbrelOS"** | https://github.com/getumbrel/umbrel/releases/tag/v0.5.4 | Redesigned App Store, Migration Assistant |
| 2023-08-16 | release | GitHub, X, HN, YouTube | repo + video | Introducing LlamaGPT (offline Llama 2 chatbot) | https://github.com/getumbrel/llama-gpt | 10.9K★; Show HN 225 pts; the AI angle begins |
| 2024-02-13 | reveal · hardware | X, YouTube, blog, forum | trailer + article | "The wait is over." umbrelOS 1.0 reveal + upgraded Umbrel Home $399, shipping today | https://x.com/umbrel/status/1757422669996441741 | 752 likes (69.5 s). Last Medium post |
| 2024-03-18 | release | GitHub, YouTube, forum | video | umbrelOS 1.0 GA: "Introducing umbrelOS 1.0" (2:08) | https://www.youtube.com/watch?v=Q-vmmboobEM | 285K views (channel #1). Forum "How to update" 24.6K views |
| 2024-03-20 | launch | Product Hunt | launch | umbrelOS 1.0: "Turn a Raspberry Pi into your home cloud" | https://www.producthunt.com/products/umbrel?launch=umbrelos-1-0 | 145 upvotes |
| 2024-04-17 | release | GitHub, forum | notes | umbrelOS 1.1: Terminal + **umbrelOS Beta Program** | https://github.com/getumbrel/umbrel/releases/tag/1.1.0 | Institutionalizes public betas |
| 2024-11-25 | release | GitHub, forum | notes | umbrelOS 1.3: swappable apps (beta 11-18) | https://github.com/getumbrel/umbrel/releases/tag/1.3.0 | — |
| 2025-01-27 | reveal | X, YouTube, forum, HN | video | "All your files. Under your roof." Files + public beta | https://x.com/umbrel/status/1883861532389556333 | 60 s 4:3 video; YouTube 61.5K |
| 2025-01-30 | community | YouTube | video | Self-host DeepSeek-R1 with umbrelOS (25 s) | https://www.youtube.com/watch?v=Rehe_yhxDXg | Trend-jacking the news |
| 2025-02-28 | release | GitHub | notes | umbrelOS 1.4 GA (Files) | https://github.com/getumbrel/umbrel/releases/tag/1.4.0 | +32 days after the reveal |
| 2025-03-18 | brand | YouTube | film | "Somewhere Along the Way" (52 s brand film) | https://www.youtube.com/watch?v=kcQhNLEoIt8 | Ownership manifesto as a film |
| 2025-06-10 | hardware | X, YouTube, forum, website | video | All-new Umbrel Home (N150, up to 4 TB): pre-order | https://community.umbrel.com/t/introducing-the-all-new-umbrel-home-now-with-up-to-4tb-ssd-storage/22968 | Ships 2025-06-24; audience-triad copy |
| 2025-06-25 | release | YouTube, forum | video | The all-new Bitcoin Node app | https://community.umbrel.com/t/the-all-new-bitcoin-node-rebuilt-from-the-ground-up/23096 | Keeps the Bitcoin base engaged |
| 2025-08-06 | hardware | YouTube | video | Umbrel Home (2025): Unboxing (1:30) | https://www.youtube.com/watch?v=ujoqRwwO2LQ | — |
| 2025-09-23 | reveal | X, YouTube, forum | video + thread | Introducing Backups on umbrelOS (1.5 public beta) + Umbrel Private Cloud early access | https://x.com/umbrel/status/1970508327479320862 | 58 s 4:3 video + 3200×2400 cards |
| 2025-11-05 | release | X, GitHub | video | "umbrelOS 1.5 with Backups. Rolling out today." | https://x.com/umbrel/status/1986033496528433363 | Quote of the reveal post; +43 days |
| 2025-11-15 | hardware | YouTube | video | Umbrel Home (2025): Setup (4:15) | https://www.youtube.com/watch?v=Vb-WH92RT5k | Backup tutorial on 11-22 |
| 2025-12-15 | milestone | HN | earned | "Umbrel – Personal Cloud" on the HN front page (220 pts, 122 comments) | https://news.ycombinator.com/item?id=46279187 | Not posted by Umbrel |
| 2026-01-28 | teaser | X | 4-image set | "tap to see" (four 3240×1012 panoramic crops) | https://x.com/umbrel/status/2016504742709694813 | Umbrel Pro teaser run starts (T-7) |
| 2026-01-31 → 02-02 | teaser | X | images | "we cooked" · "clear some desk space, you're gonna need it" · "locked in" · "final form" | https://x.com/umbrel/status/2017626208268402878 | 2160×2160 squares, one per day |
| 2026-02-03 | release | X | image | OpenClaw is live on the Umbrel App Store | https://x.com/umbrel/status/2018699999136362630 | 712 likes; primes the AI use case (T-1) |
| 2026-02-04 | hardware | X, YouTube, website | film + thread | "Introducing Umbrel Pro. The ultimate home cloud server." Order at $699 / 599 € / £529, ships Feb 9 | https://x.com/umbrel/status/2019085572019757567 | 7:08 4:3 film + 45 s "Reveal" cut + 4-card thread |
| 2026-02-05 | hardware | YouTube, X, HN | video | Making Umbrel Pro (2:18) | https://www.youtube.com/watch?v=4IAXfgBnRe8 | 235K views; founder's Show HN comment |
| 2026-02-09 | hardware | Product Hunt, X | launch + photos | First Umbrel Pros ship; PH #3 Product of the Day | https://x.com/umbrel/status/2020817986140152301 | 4 portrait photos of boxes |
| 2026-02-17 | hardware | YouTube | video | Umbrel Pro Unboxing (3:28) | https://www.youtube.com/watch?v=GIBEjRUQCsM | Setup 02-19 (6:20) |
| 2026-02-25 | release | YouTube | video | OpenClaw on Your Own Hardware (13:35) | https://www.youtube.com/watch?v=GcyWtBpDr5E | Use-case long-form |
| 2026-03-17 → 04-13 | community | YouTube Shorts | shorts/ads | "Pick how much of the cloud…", "0 to 32TB Home Cloud in 60 Seconds", "No Talking. Just a Home Server Unboxing.", "Milled From Solid Aluminum" | https://www.youtube.com/watch?v=HBp3mXkuEow | 15–60 s; ASMR unboxing 29K views |
| 2026-04-21 | reveal | X, YouTube, forum, GitHub | video | Introducing umbrelOS 1.7 + public beta | https://x.com/umbrel/status/2046572864967733275 | 47 s 4:3 video |
| 2026-04-27 | release | X, GitHub | video | "umbrelOS 1.7. Rolling out now to all users." | https://x.com/umbrel/status/2048803401572778206 | +6 days |
| 2026-05-07 | release | YouTube, website | video | apps.umbrel.com rebuilt; App Store passes 300+ apps | https://www.youtube.com/watch?v=JoOcuH123hg | 14 s spot |
| 2026-09-02 | reveal | X, YouTube, forum, GitHub | trailer | "Introducing umbrelOS 2.0 … Arriving September 22. Public beta rolling out today." | https://x.com/umbrel/status/2095200468645675324 | 1,815 likes; trailer (43 s, 4:3) 88K views |
| 2026-09-22 | launch | YouTube, X, GitHub, forum, website | keynote | umbrelOS 2.0 out: keynote (10:53) + overview (2:26) + iPhone/Mac apps | https://www.youtube.com/watch?v=lBsKk_NNg2A | Launch-week 10% off Home/Pro to 09-29 |
| 2026-09-25 | release | YouTube, X | video | How to install umbrelOS: any PC or NAS, FailSafe demo (12:51, Luke on camera) | https://www.youtube.com/watch?v=nEXx2oES3WI | Deep dive #1 (+3 days) |
| 2026-09-28 | release | YouTube, X | video | Photos in umbrelOS 2.0 + iPhone backup (5:55) | https://www.youtube.com/watch?v=xwXYT44jrj0 | Deep dive #2. A local-AI/GPU deep dive is promised next |

**Recurring rhythm in one line.**
- **2020–22:** release-train era, with a release every ~2 weeks, each announced on X and the forum.
- **2023:** quiet year (hardware and AI experiments).
- **2024–26:** 2–3 feature reveals a year (each a public beta, then GA), one hardware beat a year, point releases in between, and YouTube explainers clustered around each beat.

---

## 6. Repeatable media units

| id | Name | Trigger | Channels | Assets | Copy structure | Cadence | Examples |
|---|---|---|---|---|---|---|---|
| **U1** | Teaser drip | 1–7 days before a reveal | X | 1–5 posts; each a 2160×2160 square or text-only (optionally a 4× 3240×1012 "tap to see" set) | Lowercase ≤4 words ("uh oh" / "we cooked" / "locked in" / "final form") + a partial or cropped image; no product name | Before every big beat (4–6/yr) | https://x.com/umbrel/status/2016504742709694813 · https://x.com/umbrel/status/1663138439322279936 · https://x.com/umbrel/status/1533805351849852928 |
| **U2** | "Introducing X" reveal | Major OS feature or version; new hardware | X (lead), YouTube, forum, GitHub (beta tag), website hero swap | 1 hero video 40–70 s (16:9 to 2024; 4:3 1440×1080 or 1920×1440 since 2025); 3–7 feature cards; 1 bento 4:3 (3000×2250 / 3840×2880) | "Introducing <Name>." → one-line promise in fragments → availability line ("Arriving <date>. Public beta rolling out today." or "Order now for $X / €Y / £Z. Ships worldwide, <date>.") → video | 3–4/yr | https://x.com/umbrel/status/2095200468645675324 · https://x.com/umbrel/status/1883861532389556333 · https://x.com/umbrel/status/2019085572019757567 |
| **U3** | Feature-card thread | Same post as U2 | X | 3–10 replies, each 1 image (1440×900 in 2020 → 2880×1800 in 2021–22 → 3200×2400 4:3 in 2025–26) | Per card: benefit headline sentence → 1–2 sentences → image. Last card: thank-you to the community + order/beta link | With every U2 | https://x.com/getumbrel/status/1344291739612241922 · https://x.com/umbrel/status/2019085714189861184 · https://x.com/umbrel/status/1970508347452596228 |
| **U4** | Public beta → GA pair | Beta opens on reveal day; GA when stable | X (quote-post), GitHub (beta N → GA), forum | GA: 1 cut-down video 25–47 s | GA post = "<Name>. Rolling out today/now." quoting the reveal post | Every OS feature release; gap 6–43 days | https://x.com/umbrel/status/1986033496528433363 · https://x.com/umbrel/status/2048803401572778206 |
| **U5** | Trailer / launch film / keynote | Reveal (trailer) and GA (film/keynote) | YouTube, X native upload, website embed, forum | Trailer 43–58 s; intro film 2–7 min; keynote ~11 min with chapters; YouTube title "Introducing <X>: <promise>" | Keynote chapters: intro → "<X> in two minutes" → one chapter per feature → design → hardware → outro | Per major version / hardware | https://www.youtube.com/watch?v=dMwqgDeTskg · https://www.youtube.com/watch?v=lBsKk_NNg2A · https://www.youtube.com/watch?v=Q-vmmboobEM |
| **U6** | GitHub release notes | Every tag (betas included) | GitHub, in-OS update dialog | 1 bento 4:3 image; downloads list | "<ver> brings A, B, C, and several performance improvements and bug fixes." → [keynote link] → bento → "New features" bullets "**Name:** benefit" → Discord CTA → Downloads + SHA256SUMS(.ots) | ~1/month (2024–26) | https://github.com/getumbrel/umbrel/releases/tag/2.0.0 · https://github.com/getumbrel/umbrel/releases/tag/1.7.0 · https://github.com/getumbrel/umbrel/releases/tag/v0.3.0 |
| **U7** | Founder forum announcement | Reveal and GA | Forum (Announcements) | 1 bento image; arrow link list | "Hey everyone," → excitement → "→ Watch the reveal" → image → feature one-liners → how to try → ask for feedback → date promise → links | 3–6/yr (20/yr in 2021) | https://community.umbrel.com/t/introducing-umbrelos-2-0/25444 · https://community.umbrel.com/t/umbrelos-2-0-is-out-now/25501 · https://community.umbrel.com/t/introducing-umbrelos-1-0-rebuilt-from-the-ground-up/15196 |
| **U8** | Hardware lifecycle series | New device | YouTube, X, website | Reveal film (7 min) + 45 s cut → making-of (2:18) → ship-day photos (4 portrait) → unboxing (1:30–3:30) → setup (4–6 min) → use-case long-form (13 min) → shorts | Each video title "<Device> <Stage>: <benefit>" | Days 0, +1, +5, +13, +15, +21 (Pro) | https://www.youtube.com/watch?v=4IAXfgBnRe8 · https://www.youtube.com/watch?v=GIBEjRUQCsM · https://www.youtube.com/watch?v=xtRyoUMiPBk |
| **U9** | Post-launch deep dives | 3–6 days after GA | YouTube, X clip | 5–13 min video with a named team member on camera | Hook ("Replace Google Photos & iCloud…") → live demo → CTA (download or buy) | 2–3 per major release | https://www.youtube.com/watch?v=nEXx2oES3WI · https://www.youtube.com/watch?v=xwXYT44jrj0 |
| **U10** | App-arrival post | Notable app lands in the store | X (+ YouTube for flagship apps) | 1 screenshot 1920×1440 or a 15–35 s video | Casual: "hell yeah! <app> is live on the umbrel app store" → what it does → why it's safer on Umbrel (sandbox) | Ad hoc (~monthly) | https://x.com/umbrel/status/2018699999136362630 · https://x.com/umbrel/status/1567221691113426944 · https://www.youtube.com/watch?v=YjNa1MKvdrs |
| **U11** | Launch-platform posts | Big launch day | Product Hunt, Show HN, X ("we're live on @ProductHunt") | PH gallery + tagline; Show HN link post + founder comment with specs | PH tagline "<promise>"; HN comment: "Hey HN, I'm one of the founders… Specs:… we'll be hanging out in the comments" | 4 PH launches, 5 Show HNs in 6 years | https://www.producthunt.com/products/umbrel · https://news.ycombinator.com/item?id=31657527 · https://news.ycombinator.com/item?id=46901524 |
| **U12** | Launch-week promo countdown | GA week of a big release | X, website banner, YouTube description | Banner text; 2–4 posts | "10% off Umbrel Home and Umbrel Pro (up to $200) … until <date>" → "last 2 days…" → "last 24 hours…" | Per major launch + Black Friday | https://x.com/umbrel (2026-09-26 → 09-29 posts) |
| **U13** | Wall of love | Continuous; spikes after launches | Website section "From the community", X reposts | 5–10 embedded tweets (avatar, handle, date, quote) | "Nothing but love from people coming home." + real user posts | Updated per site redesign; daily reposts in launch weeks | umbrel.com (home, /umbrel-home, /umbrel-pro) · getumbrel.com 2020 (9 embeds) |
| **U14** | Culture / meme posts | Bitcoin moments, news, product in-jokes | X | Text or reaction image; lowercase | One-liner joke tied to the product ("running out of space on your umbrel? …") or a cultural hook (#FullNodeFriday, halving) | Several/week (2020–22); lighter now | https://x.com/getumbrel/status/1344185234363830279 · https://x.com/getumbrel/status/1281619821830893568 |
| **U15** | Shorts and ad spots | Between launches | YouTube Shorts, X | 14–60 s, vertical or 16:9; "#tech #nas" | Visual hook (ASMR unboxing, machining, "0 to 32TB in 60 seconds") → product name → URL | ~2–4/mo in 2026 H1 | https://www.youtube.com/watch?v=HBp3mXkuEow · https://www.youtube.com/watch?v=O6NsCH6XGU0 · https://www.youtube.com/watch?v=fW57DOg2X4U |
| **U16** | App Store listing + app update notes | New app PR / app version bump | umbrel-apps repo → in-OS store → apps.umbrel.com | icon 256×256 SVG; gallery 3–5 × 1440×900; manifest | tagline → description (notes first, features list) → releaseNotes per version ("Full release notes…") | Continuous (daily merges) | https://apps.umbrel.com/app/immich · https://github.com/getumbrel/umbrel-apps/blob/master/immich/umbrel-app.yml |
| **U17** | Milestone / funding / hiring essay | Round closed, usage milestone | Blog (Medium), forum, X, press | 2,000–3,000 words; 4–6 photos; press syndication | Journey recap + metrics → mission → round/investors → origin story → hiring → thanks | Once (2021) | https://blog.getumbrel.com/seed-6d09aa08f8ac · https://community.umbrel.com/t/we-ve-raised-a-3m-seed-round-and-are-now-hiring/4365 |
| **U18** | Waitlist wave invites (one-time launch mechanic) | Pre-GA beta | Website waitlist, email, X | Wave posts | "Invitations … to the next N users on the waitlist" (N doubles: 100 → 200 → 400 → everyone) → "no more waitlist" site relaunch | Weekly for ~2 months (2020) | https://x.com/getumbrel/status/1294685944784646144 · https://x.com/getumbrel/status/1303733668242796544 · https://x.com/getumbrel/status/1317509698078208000 |

---

## 7. The reveal sequence

### 7a. The original reveal (nothing → launched), 2020

| # | Date | Step | Channels | Gap (days) |
|---|---|---|---|---|
| 1 | 2020-01-01 | Reserve identity: X @getumbrel and GitHub org, same morning | X, GitHub | — |
| 2 | 2020-01-22 | "Coming Soon" page with waitlist email capture | website | 21 |
| 3 | 2020-03-17 | First X activity: repost of Hal Finney's "Running bitcoin"; bio "…Coming soon" | X | 55 |
| 4 | 2020-04-25 | Positioning page "Bitcoin and Lightning Node — Request early access" | website | 39 |
| 5 | 2020-05-11 | First product glimpse on a cultural moment (halving block 630,000 on an Umbrel) | X | 16 |
| 6 | 2020-06-06 | Site v2 with the tagline "Become Bitcoin" and a share image | website | 26 |
| 7 | 2020-07-03 | Screenshot teaser series "Running #Bitcoin" / "#Lightning" plus "beta in ~2 weeks" replies | X | 27 |
| 8 | 2020-07-07 | Code and beta builds public on GitHub (umbrel v0.1.2, Umbrel OS v0.0.4-beta) | GitHub | 4 |
| 9 | 2020-08-15 | v0.2.0 + "Running #Umbrel☂️" + announced phased rollout plan + Telegram invite | X, GitHub, Telegram | 39 |
| 10 | 2020-08-16 | **Launch:** invites to the first 100 waitlist users | email, X | 1 |
| 11 | 2020-08-22 | Wave 2 (200) | email, X | 6 |
| 12 | 2020-08-31 | Wave 3 (400), paired with v0.2.6 | email, X | 9 |
| 13 | 2020-09-09 | Everyone on the waitlist | email, X | 9 |
| 14 | 2020-10-17 | GA: "no more waitlist" site relaunch with install guide and parts list | website, X | 38 |
| 15 | 2020-12-30 | Platform moment: App Store (7 partner apps kept secret for two weeks) | X, blog, GitHub | 74 |
| 16 | 2021-08-05 | Category expansion: "personal server OS for everyone" (0.4) + license change | X, blog, forum, YouTube | 218 |
| 17 | 2021-10-29 | Funding + hiring essay | blog, forum, press | 85 |
| 18 | 2022-06-07 | Rebrand launch: umbrel.com, 0.5 redesign, first PH + Show HN | all | 221 |
| 19 | 2023-05-30 | Own hardware (Umbrel Home) | X, YouTube, website, PH, HN | 357 |

**Shape.** Reserve → waitlist → mood tagline → cultural-moment glimpse → screenshot teasers → open code → waitlist waves → no-waitlist GA → platform (store) → category widening → money → rebrand → hardware.

**Timing.**
- First trace to first user: **228 days** (2020-01-01 → 2020-08-16).
- First user to general availability: **62 days** (2020-08-16 → 2020-10-17).

### 7b. The shape that repeats for every later launch

```
T-7 … T-1   Teaser drip on X (cryptic crops/squares, lowercase one-liners, "turn on notifications")
T-1         Momentum post (a hot app lands in the store, e.g. OpenClaw) — optional
T0          REVEAL: "Introducing X." hero video (trailer) + numbered feature-card thread
            + founder forum post + GitHub beta tag (OS) / order page live (hardware)
            + website hero swapped; availability line gives the GA/ship date
T0…T+2      Product Hunt + Show HN (big launches only); making-of film (hardware, T+1)
T+5…T+43    GA / ships: "X. Rolling out today." (quote of the reveal) + GitHub release
            + keynote or intro film + forum "is out now" + launch-week discount
GA+3…GA+21  Deep-dive / unboxing / setup / use-case videos with a named team member
GA+0…GA+7   Wall-of-love reposts; promo countdown ("last 2 days", "last 24 hours")
Later       Shorts/ads recut from launch footage; website sections gain "NEW" badges
```

### 7c. Per-launch gaps

| Launch | Teaser → reveal | Reveal → GA/ship | Follow-ups |
|---|---|---|---|
| Umbrel App Store (v0.3.0, 2020) | 1 d ("when big update umbrel?") | 0 (same day) | "how do u guys like the update" +1 d |
| Umbrel 0.5 + umbrel.com (2022) | 1 d | 0 (live on reveal) | PH + Show HN same day |
| Umbrel Home 1st gen (2023) | 1 d ("uh oh") | pre-order day 0; ships June 2023 (exact date unknown) | PH +1 d |
| umbrelOS 1.0 + Home N100 (2024) | none found | **34 d** (02-13 → 03-18); Home ships day 0 | PH +2 d after GA; 1.1 +30 d |
| Files / umbrelOS 1.4 (2025) | none found | 32 d (01-27 → 02-28) | 1.4.1 +59 d |
| Umbrel Home 2025 | none found | ships +14 d (06-10 → 06-24) | unboxing +57 d, setup +158 d |
| Backups / umbrelOS 1.5 (2025) | none found before the reveal; a GA-morning one-liner ("…do yourself a favour") | 43 d (09-23 → 11-05) | backup tutorial +17 d |
| **Umbrel Pro (2026)** | **7 d** (01-28 → 02-04), 5 teaser posts | ships +5 d (02-09); making-of +1 d; PH +5 d | unboxing +13, setup +15, OpenClaw film +21 |
| umbrelOS 1.7 (2026) | none found | 6 d (04-21 → 04-27) | poll "what do u *mainly* use your umbrel for" on GA day |
| **umbrelOS 2.0 (2026)** | trailer is the teaser | **20 d** (09-02 → 09-22), beta 2 at +15 | deep dives +3 and +6 d; 10% promo 7 d |

**Pattern to copy for "startup-tail".**
1. Announce with a date and let people use the beta immediately.
2. Ship on the promised date with a longer film.
3. Spend the next week on deep dives and social proof.

Hardware adds a making-of film the day after the reveal and ships within a week of the reveal.

---

## 8. Gaps (not verified)

- **X is walled.**
  - No follower history. The 2020-03-24 snapshot parse (1 post, ~6 followers) is low-confidence.
  - The handle-change date is only bracketed (2022-02-14 → 2022-05-17).
  - The original-vs-reply split of the 17,817 posts is unknown.
  - Post texts come from public syndication for archived IDs only, and the Wayback coverage is uneven (e.g. almost nothing archived Mar–Jul 2021 or 2023).
- **LinkedIn** (follower count and tagline from a search snippet, undated) and **Reddit** (count via shields.io only; sidebar and creation date unknown) could not be opened.
- **Not found:** TikTok, an official Facebook page, a podcast, merch, events or a press kit. Absence was not exhaustively proven because the WebSearch budget (200 calls/session) ran out midway.
- **Pre-2020-07-26 website history** was reconstructed from commits to `getumbrel/umbrel-website`, not from renders. The dates are when the commits were made, not necessarily when they were deployed.
- **Images were not inspected** (no-download rule). Logo shape, avatar and banner content are therefore undescribed; only URLs, sizes and upload dates are recorded.
- **Newsletter:** provider, cadence and archive unknown.
- **Prices.**
  - The 2025 Umbrel Home pre-order line reads "$399 / 279 € / £239" in both the forum and X posts. The EU/UK figures look inconsistent with the USD figure but are recorded as posted.
  - Current JSON-LD shows Home $599–$949 and Pro $699–$1,899. The cart was not checked.
  - Umbrel Pro launched as "16TB" (PH tagline) and now says "up to 32TB". The date of that change is unknown.
- **Dates.** The exact ship date of the 1st-gen Umbrel Home in 2023 is unknown ("June 2023"). The origin months (Oct 2019 node, Dec 2019 meetup) are approximate.
- **Business figures.** No user count after 2021 (13,000+) and no unit sales were published. The getlatka revenue figure is unverified.
- **umbrelOS 1.6 / 1.6.1** shipped only on Umbrel Pro and were never tagged (per a forum reply). Contents unknown.
- **Discord** creation date comes from the server snowflake. Discord replaced Telegram as the main chat, but the switch date is unknown.
- **Product Hunt** upvotes for Umbrel Pro differ between sources (328 vs 344).
- **Store categories:** display names for `social` and `developer` were not confirmed.

---

## Appendix — blueprint input

```yaml
# blueprint-input
company: Umbrel
observed_at: "2026-09-29"
channels:
  - {platform: website, handle: umbrel.com, url: "https://umbrel.com/", since: "2020-01-22 (getumbrel.com); umbrel.com 2022-06-07", followers: null, bio: "Umbrel - Personal home cloud and OS for self-hosting", cadence: "hero re-cut at every major launch (2-4/yr)"}
  - {platform: product_page, handle: /umbrelos, url: "https://umbrel.com/umbrelos", since: "<=2024-03-22", followers: null, bio: "umbrelOS - An elegant OS for your home server", cadence: "per OS release"}
  - {platform: product_page, handle: /umbrel-home, url: "https://umbrel.com/umbrel-home", since: "2023-05-30", followers: null, bio: "Umbrel Home | Plug and Play Home Cloud Server", cadence: "per hardware revision (2023, 2024, 2025)"}
  - {platform: product_page, handle: /umbrel-pro, url: "https://umbrel.com/umbrel-pro", since: "2026-02-04", followers: null, bio: "32 terabytes of cloud. On your desk.", cadence: "launched once"}
  - {platform: downloads, handle: /downloads, url: "https://umbrel.com/downloads", since: unknown, followers: null, bio: "Your hardware. Your cloud.", cadence: "per release"}
  - {platform: help, handle: /support, url: "https://umbrel.com/support", since: unknown, followers: null, bio: "How can we help?", cadence: "updated per release (~72 articles, 12 categories)"}
  - {platform: blog, handle: "Umbrel Blog (Medium)", url: "https://blog.getumbrel.com", since: "2020-12-30", followers: null, bio: "Umbrel Blog", cadence: "7 posts 2020-12..2024-02; dormant"}
  - {platform: changelog, handle: getumbrel/umbrel releases, url: "https://github.com/getumbrel/umbrel/releases", since: "2020-07-07", followers: null, bio: "umbrelOS X.Y", cadence: "102 releases; ~1/mo 2024-26 incl. betas"}
  - {platform: forum, handle: community.umbrel.com, url: "https://community.umbrel.com", since: "2021-04-30 (created 2021-03-29)", followers: 8507, bio: "A friendly place to discuss all things Umbrel and to connect with the community.", cadence: "announcements 3-6/yr (20 in 2021)"}
  - {platform: app_store, handle: apps.umbrel.com, url: "https://apps.umbrel.com", since: "2023-03-07 (in-OS store 2020-12-30)", followers: null, bio: "Hundreds of apps. One home server. All yours.", cadence: "continuous; 392 packages"}
  - {platform: careers, handle: /careers, url: "https://umbrel.com/careers", since: "2021-10-29 (hiring call)", followers: null, bio: "Build the future of Umbrel.", cadence: evergreen}
  - {platform: affiliates, handle: affiliate.umbrel.com, url: "https://affiliate.umbrel.com/", since: unknown, followers: null, bio: "Share something worth owning. Earn along the way.", cadence: evergreen}
  - {platform: newsletter, handle: "Stay in the loop", url: "https://umbrel.com/", since: "2020-01-22 (waitlist)", followers: null, bio: "Follow our journey in helping people truly own their data. Better yet, be a part of it.", cadence: unknown}
  - {platform: github, handle: getumbrel, url: "https://github.com/getumbrel", since: "2020-01-01", followers: 1149, bio: "The ultimate home server and home cloud OS. Buy an Umbrel Home, or install umbrelOS on a Raspberry Pi.", cadence: "commits weekly; releases ~monthly"}
  - {platform: youtube, handle: "@UmbrelYt", url: "https://www.youtube.com/@UmbrelYt", since: "2020-05-25 (first upload 2021-08-06)", followers: 13700, bio: "Umbrel is a small computer that lives in your home, and becomes your cloud. Not the kind you sit at.", cadence: "39 videos; ~2/mo in 2026, launch-clustered"}
  - {platform: x, handle: umbrel, url: "https://x.com/umbrel", since: "2020-01-01 (as @getumbrel)", followers: 75328, bio: "Your private home cloud for files, photos & videos storage, local AI models and agents (OpenClaw/Hermes), Bitcoin node & more ✨ → https://t.co/Y8ayOgyTrH", cadence: "~220 posts/mo lifetime incl. replies+reposts; 1-3 originals/day in launch weeks"}
  - {platform: discord, handle: Umbrel, url: "https://discord.gg/efNtFzqtdx", since: "2022-01-28 (~)", followers: 4118, bio: "Stay connected with the latest updates, discussions, and troubleshooting tips. Engage, share ideas, and get help.", cadence: continuous}
  - {platform: telegram, handle: getumbrel, url: "https://t.me/getumbrel", since: "<=2020-07-07", followers: 4236, bio: "Umbrel (Official) — umbrel.com", cadence: legacy}
  - {platform: reddit, handle: r/getumbrel, url: "https://reddit.com/r/getumbrel", since: "<=2020-07-07", followers: 7800, bio: null, cadence: unknown}
  - {platform: producthunt, handle: umbrel, url: "https://www.producthunt.com/products/umbrel", since: "2022-06-07", followers: 583, bio: "The ultimate home cloud & OS for self-hosting", cadence: "1 per major launch (4 total)"}
  - {platform: hackernews, handle: mayankchhabra, url: "https://news.ycombinator.com/item?id=31657527", since: "2022-06-07", followers: null, bio: null, cadence: "Show HN per big launch (5 total)"}
  - {platform: instagram, handle: getumbrel, url: "https://www.instagram.com/getumbrel/", since: unknown, followers: 184, bio: "Personal Server OS for Everyone", cadence: "dormant (1 post)"}
  - {platform: linkedin, handle: company/umbrel, url: "https://www.linkedin.com/company/umbrel", since: unknown, followers: 716, bio: "A beautiful OS to run a server in your home", cadence: unknown}
  - {platform: facebook, handle: null, url: null, since: null, followers: null, bio: null, cadence: "none found"}
  - {platform: tiktok, handle: null, url: null, since: null, followers: null, bio: null, cadence: "none found"}
  - {platform: podcast, handle: null, url: null, since: null, followers: null, bio: null, cadence: "none found"}
  - {platform: events, handle: null, url: null, since: null, followers: null, bio: null, cadence: "none found (internal annual retreat)"}
  - {platform: merch, handle: null, url: null, since: null, followers: null, bio: null, cadence: "none found"}
  - {platform: docker_hub, handle: getumbrel, url: "https://hub.docker.com/u/getumbrel", since: "~2020", followers: null, bio: null, cadence: "per app update"}
identity:
  name: Umbrel
  legal_name: "Umbrel, Inc."
  handles: {x: umbrel, x_former: getumbrel, github: getumbrel, youtube: "@UmbrelYt", instagram: getumbrel, telegram: getumbrel, reddit: getumbrel, linkedin: "company/umbrel", producthunt: umbrel, docker: getumbrel, domains: [umbrel.com, getumbrel.com, apps.umbrel.com, community.umbrel.com, link.umbrel.com, download.umbrel.com, affiliate.umbrel.com, blog.getumbrel.com]}
  taglines:
    - {date: "2020-01-22", text: "Be the first one to know when we launch"}
    - {date: "2020-03", text: "#Bitcoin and #Lightning⚡️ like never before. Coming soon"}
    - {date: "2020-04-25", text: "Umbrel Bitcoin and Lightning Node — Request early access"}
    - {date: "2020-06-06", text: "Become Bitcoin"}
    - {date: "2020-10-17", text: "Umbrel — your personal Bitcoin node."}
    - {date: "2021-08-05", text: "A Personal Server OS for Everyone"}
    - {date: "2021-10-29", text: "get a server in every home"}
    - {date: "2022-06-07", text: "A beautiful personal server OS for self-hosting."}
    - {date: "2023-05-30", text: "Home is where your data belongs."}
    - {date: "2023-06", text: "The ultimate home server and OS for self-hosting"}
    - {date: "2024-03", text: "Personal home cloud and OS for self-hosting"}
    - {date: "2025-01-27", text: "All your files. Under your roof."}
    - {date: "2026-02-04", text: "The ultimate home cloud server."}
    - {date: "2026-09", text: "Your cloud, in your home."}
    - {date: "2026-09", text: "The cloud is just someone else's computer. Umbrel is yours."}
    - {date: "2026-09", text: "Stores, streams, syncs, and just slaps."}
    - {date: "2026-09-22", text: "Just a small computer, at home, that becomes your cloud."}
  short_description: "The ultimate home server and home cloud OS. Buy an Umbrel Home, or install umbrelOS on a Raspberry Pi."
  long_description: "Bring the cloud to your home with umbrelOS - a beautiful home server OS for self-hosting, and Umbrel Home and Umbrel Pro - plug-and-play home servers. Install Nextcloud, Jellyfin, Bitcoin node, and hundreds of self-hosted apps in one click."
  terminology:
    - {term: umbrelOS, meaning: "the browser-based home-cloud OS (lowercase u); named so in releases since 0.5.4 (2023-06-21)"}
    - {term: "your Umbrel", meaning: "the user's server regardless of hardware"}
    - {term: "Umbrel Home", meaning: "palm-sized plug-and-play server (N150, 1-4 TB)"}
    - {term: "Umbrel Pro", meaning: "4x NVMe aluminium+walnut server (N300, up to 32 TB)"}
    - {term: "DIY hardware", meaning: "umbrelOS on Raspberry Pi, x86 PC/NAS or VM"}
    - {term: umbrel.local, meaning: "local address to open the dashboard"}
    - {term: "Umbrel App Store", meaning: "in-OS store + apps.umbrel.com, 300+ apps"}
    - {term: "Community App Store", meaning: "third-party store added by URL (template repo)"}
    - {term: "Official app", meaning: "first-party app, e.g. Bitcoin Node"}
    - {term: "Swappable apps", meaning: "alternatives that implement a dependency (manifest implements)"}
    - {term: Widgets, meaning: "live home-screen cards served by apps (7 types)"}
    - {term: Dock, meaning: "macOS-like app launcher (since 0.5)"}
    - {term: Wallpapers, meaning: "hand-curated backgrounds that also set the UI accent color"}
    - {term: "Cmd/Ctrl-K search", meaning: "universal search over apps, files, photos, settings"}
    - {term: "Quick actions", meaning: "right-click menus on icons/desktop"}
    - {term: "Live Usage", meaning: "real-time CPU/RAM/storage/GPU by app"}
    - {term: Files, meaning: "built-in file manager (1.4) with network shares"}
    - {term: Rewind, meaning: "time-travel restore of files from backups (1.5)"}
    - {term: Backups, meaning: "encrypted hourly..monthly snapshots to USB/NAS/another Umbrel"}
    - {term: "Umbrel Private Cloud", meaning: "announced end-to-end encrypted cloud backup (early access)"}
    - {term: Photos, meaning: "built-in photo library fed by the iPhone app (2.0)"}
    - {term: Machines, meaning: "one-click VMs: Windows, Ubuntu, Debian, Android (2.0)"}
    - {term: FailSafe, meaning: "RAID (ZFS raidz1) across drives, can be enabled later"}
    - {term: "Storage Manager", meaning: "combine drives, FailSafe, SSD acceleration (2.0)"}
    - {term: "AI agents (MCP server)", meaning: "connect Claude Code/Codex/OpenClaw/Cursor with scoped tokens (2.0)"}
    - {term: Shortcuts, meaning: "home-screen tiles for URLs, ports, containers (1.7)"}
    - {term: "umbrelOS Beta Program", meaning: "opt-in public betas in Settings > Advanced (1.1+)"}
    - {term: "Umbrel Protect", meaning: "2-year hardware protection add-on"}
    - {term: Bento, meaning: "internal name for the 4:3 grid hero image of a release"}
    - {term: "#umbrelheads", meaning: "community nickname (2020)"}
  colors:
    - {name: brand_violet, hex: "#5351FB"}
    - {name: site_brand_token, hex: "#5351F3"}
    - {name: brand_hover, hex: "#4543DF"}
    - {name: brand_soft, hex: "#8583FF"}
    - {name: accent_teal, hex: "#14B8A6"}
    - {name: violet_300, hex: "#C4B4FF"}
    - {name: violet_400, hex: "#A685FF"}
    - {name: violet_500, hex: "#8D54FF"}
    - {name: base_zinc_950, hex: "#09090B"}
    - {name: os_destructive, hex: "#E03E3E"}
    - {name: os_success, hex: "#299E16"}
    - {name: os_dialog, hex: "#1E1E1E"}
    - {name: os_theme, hex: "#000000"}
  typography: "Site: Google Sans headings (fallback Product Sans, Inter), Inter body, Playfair italic narrative accent, Dancing Script script accent. umbrelOS: Inter sans, Roboto mono."
  theme: "dark-first glassmorphism: black/zinc backgrounds, translucent blurred panels, wallpapers; violet accent (OS accent derived from wallpaper)"
  logo: "Umbrel glyph = ☂️ emoji in display names; lowercase 'umbrelOS' wordmark; dark/light 'Get it on umbrelOS' badges; no official press kit (visuals not inspected)"
  illustration: "3D product renders, desk lifestyle photography, 4:3 'bento' release composites, browser-framed UI screenshots, app-icon walls, tweet cards, CNC machining footage; 2020: 1440x900 app cards + memes"
  voice: "two registers: keynote-declarative ('Introducing X.' + fragments + superlatives + triads) for launches; lowercase meme-native ('we cooked', 'wen big update', 'lfggg') for daily X; anti-Big-Tech ownership, privacy, craft, gratitude to community"
content:
  sections:
    - {id: about, title: "What is Umbrel? (support) + careers + seed post", structure: "no About page; device in your home -> umbrelOS -> iPhone/Mac apps -> Home/Pro -> what you can do; origin story lives in the seed essay"}
    - {id: home, title: "Home", structure: "promo bar -> hero H1+sub+body+desk image -> As seen on -> 5 product tiles -> current launch (keynote) -> 9 NEW feature blocks -> 6 use-case categories x3 apps -> App Store CTA -> iPhone/Mac app -> self-hosting vs cloud (4 rows) -> do the math (cost) -> choose your path (DIY/Home/Pro) -> wall of love -> start your journey -> closing line + newsletter -> footer"}
    - {id: product, title: "Umbrel Home / Umbrel Pro", structure: "hero + price 'From' + Buy now -> use cases with apps -> setup steps -> umbrelOS features -> hardware highlights -> specs table -> in the box -> comparison -> testimonials -> videos -> FAQ"}
    - {id: help, title: "Support", structure: "How can we help? + live chat -> 6 featured cards -> 12 categories (~72 articles) -> article: title, last updated, intro, H2 + screenshots; video tutorials on YouTube"}
    - {id: app_store, title: "Umbrel App Store", structure: "hero -> Serving hot now -> carousel -> Most installs -> New arrivals -> categories -> all apps (sort A-Z/new/updated) -> listing (see app_store_listing)"}
    - {id: blog, title: "Umbrel Blog (Medium)", structure: "'Introducing X — positioning' -> hook -> video -> backstory -> under the hood -> H2 per feature + screenshot -> hardware + 3-currency price -> road ahead -> your role (Discord/forum) -> sign-off"}
    - {id: releases, title: "GitHub releases", structure: "'umbrelOS X.Y' -> 'X.Y brings A, B, C, and several performance improvements and bug fixes.' -> [keynote link] -> 4:3 bento -> New features bullets **Name:** benefit -> Discord CTA -> Downloads + SHA256SUMS(.ots)"}
    - {id: forum_announcement, title: "Forum Announcements", structure: "Hey everyone -> excitement -> '→ Watch the reveal' -> bento -> feature one-liners -> how to try (beta path) -> feedback ask -> date promise -> arrow links (site, apps, X post)"}
    - {id: newsletter, title: "Stay in the loop", structure: "footer email field; no public archive"}
    - {id: press, title: "As seen on", structure: "logo strip only (9to5Mac, Gizmodo, Decrypt, XDA, heise); no press kit"}
    - {id: vision, title: "Manifesto (seed post + home page)", structure: "personal computer -> personal server revolution; surveillance capitalism; 'someone else's computer / Umbrel is yours'; rent vs buy; your house your rules"}
app_store_listing:
  fields:
    - {name: manifestVersion, type: number, example: "1.1"}
    - {name: id, type: "kebab-case string = dir name", example: immich}
    - {name: implements, type: "app id (optional)", example: "bitcoin (for Bitcoin Knots)"}
    - {name: storage.dataRoot, type: path, example: data}
    - {name: folderAccess, type: "list {id, name, note, mounts[{service, targetPath, readOnly}]}", example: "External Library -> /mnt/external-library (read-only)"}
    - {name: category, type: "enum (files|bitcoin|media|networking|social|automation|finance|ai|developer)", example: "files (shown 'Files & Productivity')"}
    - {name: name, type: string, example: Immich}
    - {name: version, type: "string (upstream)", example: "v3.2.2"}
    - {name: tagline, type: "string ~50 chars", example: "High-performance photo and video backup solution"}
    - {name: description, type: "folded markdown", example: "intro -> ⚠️ note -> 'Features:' bullet list"}
    - {name: releaseNotes, type: "folded markdown (empty on first submit)", example: "what changed -> breaking-change ⚠️ -> fixes -> 'Full release notes can be found at <url>'"}
    - {name: developer, type: string, example: "Alex Tran"}
    - {name: website, type: url, example: "https://www.immich.app"}
    - {name: dependencies, type: "list of app ids", example: "[]"}
    - {name: repo, type: url, example: "https://github.com/immich-app/immich"}
    - {name: support, type: url, example: "https://github.com/immich-app/immich/discussions"}
    - {name: port, type: "int (unique)", example: "2283"}
    - {name: gallery, type: "list of filenames (3-5 x 1440x900)", example: "[1.jpg, 2.jpg, 3.jpg]"}
    - {name: path, type: string, example: '""'}
    - {name: defaultUsername, type: string, example: '""'}
    - {name: defaultPassword, type: string, example: '""'}
    - {name: deterministicPassword, type: bool, example: "true (Nextcloud)"}
    - {name: torOnly, type: bool, example: "false (Nextcloud)"}
    - {name: permissions, type: "list (GPU|STORAGE_DOWNLOADS)", example: "[GPU]"}
    - {name: widgets, type: "list {id, type, refresh, endpoint, link, example}", example: "four-stats every 5s (Bitcoin Node)"}
    - {name: backupIgnore, type: "list of globs", example: "data/bitcoin/blocks"}
    - {name: icon, type: "256x256 SVG, square, no rounded corners (hosted by Umbrel)", example: "umbrel-apps-gallery/immich/icon.svg"}
    - {name: submitter, type: string, example: levma}
    - {name: submission, type: url, example: "https://github.com/getumbrel/umbrel-apps/pull/239"}
    - {name: "web: info_card", type: derived, example: "Version, Category, Source code: Public, Developed by, Submitted by, Compatibility: umbrelOS 0.5 or later"}
    - {name: "web: whats_new", type: derived, example: "one entry per version with date + release-notes link"}
    - {name: "web: related_apps", type: derived, example: "6 apps"}
    - {name: "web: badge", type: "svg url", example: "https://apps.umbrel.com/api/app/immich/badge-dark.svg"}
timeline:
  - {date: "2019-10", stage: pre-launch, channels: [x], media: post, title: "Founder moves his Bitcoin node to a Raspberry Pi (~)", url: "https://blog.getumbrel.com/seed-6d09aa08f8ac"}
  - {date: "2019-12", stage: pre-launch, channels: [event], media: talk, title: "Figma prototype shown at Chiang Mai Bitcoin/Lightning meetup (~)", url: "https://blog.getumbrel.com/seed-6d09aa08f8ac"}
  - {date: "2020-01-01", stage: pre-launch, channels: [x, github], media: account, title: "@getumbrel + github.com/getumbrel created", url: "https://github.com/getumbrel"}
  - {date: "2020-01-22", stage: teaser, channels: [website], media: landing, title: "Umbrel | Coming Soon (waitlist)", url: "https://github.com/getumbrel/umbrel-website/commits/master"}
  - {date: "2020-03-17", stage: teaser, channels: [x], media: repost, title: "Repost of Hal Finney 'Running bitcoin'; bio 'Coming soon'", url: "https://web.archive.org/web/20200324234023/https://twitter.com/getumbrel"}
  - {date: "2020-04-25", stage: teaser, channels: [website], media: landing, title: "Bitcoin and Lightning Node — Request early access", url: "https://github.com/getumbrel/umbrel-website/commit/45a718984f64f9a85a4cc2df93084b4fa305df3e"}
  - {date: "2020-05-11", stage: teaser, channels: [x], media: gif, title: "Happy #Bitcoin Halving! block 630,000 on an Umbrel node", url: "https://x.com/getumbrel/status/1259933148281835520"}
  - {date: "2020-06-06", stage: teaser, channels: [website], media: landing, title: "Become Bitcoin (site v2)", url: "https://github.com/getumbrel/umbrel-website/commit/831eccdb735b27ba01717a699d43c26a3105ad46"}
  - {date: "2020-07-03", stage: teaser, channels: [x], media: image, title: "Running #Bitcoin (dashboard screenshot)", url: "https://x.com/getumbrel/status/1279097216578117632"}
  - {date: "2020-07-07", stage: release, channels: [github], media: release, title: "umbrel v0.1.2 / Umbrel OS v0.0.4-beta", url: "https://github.com/getumbrel/umbrel/releases"}
  - {date: "2020-07-13", stage: teaser, channels: [x], media: image, title: "Running #Lightning", url: "https://x.com/getumbrel/status/1282719857960644608"}
  - {date: "2020-08-15", stage: launch, channels: [x, github], media: thread, title: "Running #Umbrel + phased rollout plan; v0.2.0", url: "https://x.com/getumbrel/status/1294685944784646144"}
  - {date: "2020-08-16", stage: launch, channels: [email, x], media: post, title: "Invites to first 100 waitlist users (launch day)", url: "https://x.com/getumbrel/status/1295022263083757569"}
  - {date: "2020-08-22", stage: launch, channels: [email, x], media: post, title: "Invites to next 200", url: "https://x.com/getumbrel/status/1297201052672901121"}
  - {date: "2020-08-30", stage: release, channels: [x], media: image, title: "v0.2.6 channel backups; next 400 invites", url: "https://x.com/getumbrel/status/1300161025841311744"}
  - {date: "2020-09-09", stage: launch, channels: [email, x], media: post, title: "Invites to everyone on the waitlist", url: "https://x.com/getumbrel/status/1303733668242796544"}
  - {date: "2020-10-17", stage: launch, channels: [website, x], media: landing, title: "All-new getumbrel.com, no more waitlist", url: "https://x.com/getumbrel/status/1317509698078208000"}
  - {date: "2020-12-30", stage: release, channels: [x, blog, github], media: thread, title: "Introducing the Umbrel App Store (v0.3.0)", url: "https://blog.getumbrel.com/introducing-the-umbrel-app-store-7a2068c64a10"}
  - {date: "2021-04-30", stage: community, channels: [forum], media: post, title: "Introducing the new Umbrel Community forum", url: "https://community.umbrel.com/t/introducing-the-new-umbrel-community-forum/40"}
  - {date: "2021-08-05", stage: pivot, channels: [x, blog, forum, github], media: video, title: "Introducing Umbrel 0.4 — A Personal Server OS for Everyone", url: "https://blog.getumbrel.com/introducing-umbrel-v0-4-e5b67d02c43a"}
  - {date: "2021-09-29", stage: hardware, channels: [forum, press], media: post, title: "Plug-and-play Umbrel server from The Bitcoin Machines", url: "https://bitcoinmagazine.com/business/umbrel-plug-and-play-bitcoin-node-self-hosting-server"}
  - {date: "2021-10-29", stage: funding, channels: [blog, forum, x, press], media: article, title: "Umbrel raises $3M in seed round to get a server in every home", url: "https://blog.getumbrel.com/seed-6d09aa08f8ac"}
  - {date: "2022-01-28", stage: community, channels: [discord], media: server, title: "Discord server created (~)", url: "https://discord.gg/efNtFzqtdx"}
  - {date: "2022-04-20", stage: release, channels: [github], media: repo, title: "umbrel-apps repo (store split from core)", url: "https://github.com/getumbrel/umbrel-apps"}
  - {date: "2022-06-07", stage: launch, channels: [x, youtube, blog, forum, producthunt, hackernews, website], media: video, title: "Introducing Umbrel 0.5 — A beautiful personal server OS; umbrel.com live", url: "https://x.com/umbrel/status/1534164270459473921"}
  - {date: "2022-09-06", stage: release, channels: [x], media: video, title: "7 media-server apps (Plex, Jellyfin, *arr)", url: "https://x.com/umbrel/status/1567221691113426944"}
  - {date: "2022-10-25", stage: release, channels: [forum, github], media: post, title: "0.5.2 Community App Stores", url: "https://community.umbrel.com/t/umbrel-0-5-2-is-here-with-community-app-stores-tor-access-toggle-search-in-app-store-and-more/9981"}
  - {date: "2023-03-07", stage: release, channels: [x, youtube], media: video, title: "Introducing apps.umbrel.com + badges", url: "https://x.com/umbrel/status/1633112336662773760"}
  - {date: "2023-05-29", stage: teaser, channels: [x], media: image, title: "uh oh", url: "https://x.com/umbrel/status/1663138439322279936"}
  - {date: "2023-05-30", stage: hardware, channels: [x, youtube, website, hackernews, press], media: video, title: "Introducing Umbrel Home ($699 pre-order)", url: "https://x.com/umbrel/status/1663534602366091269"}
  - {date: "2023-06-21", stage: rebrand, channels: [github, youtube, forum], media: video, title: "umbrelOS 0.5.4 (first 'umbrelOS' release)", url: "https://github.com/getumbrel/umbrel/releases/tag/v0.5.4"}
  - {date: "2023-08-16", stage: release, channels: [github, x, hackernews, youtube], media: repo, title: "Introducing LlamaGPT", url: "https://github.com/getumbrel/llama-gpt"}
  - {date: "2024-02-13", stage: reveal, channels: [x, youtube, blog, forum], media: trailer, title: "umbrelOS 1.0 reveal + upgraded Umbrel Home $399", url: "https://x.com/umbrel/status/1757422669996441741"}
  - {date: "2024-03-18", stage: release, channels: [github, youtube, forum], media: video, title: "Introducing umbrelOS 1.0 (GA)", url: "https://www.youtube.com/watch?v=Q-vmmboobEM"}
  - {date: "2024-03-20", stage: launch, channels: [producthunt], media: launch, title: "umbrelOS 1.0 on Product Hunt", url: "https://www.producthunt.com/products/umbrel?launch=umbrelos-1-0"}
  - {date: "2024-04-17", stage: release, channels: [github, forum], media: notes, title: "umbrelOS 1.1: Terminal + Beta Program", url: "https://github.com/getumbrel/umbrel/releases/tag/1.1.0"}
  - {date: "2024-11-25", stage: release, channels: [github, forum], media: notes, title: "umbrelOS 1.3: swappable apps", url: "https://github.com/getumbrel/umbrel/releases/tag/1.3.0"}
  - {date: "2025-01-27", stage: reveal, channels: [x, youtube, forum, hackernews], media: video, title: "Introducing Files on umbrelOS (public beta)", url: "https://x.com/umbrel/status/1883861532389556333"}
  - {date: "2025-02-28", stage: release, channels: [github], media: notes, title: "umbrelOS 1.4 GA", url: "https://github.com/getumbrel/umbrel/releases/tag/1.4.0"}
  - {date: "2025-03-18", stage: event, channels: [youtube], media: video, title: "Somewhere Along the Way (brand film)", url: "https://www.youtube.com/watch?v=kcQhNLEoIt8"}
  - {date: "2025-06-10", stage: hardware, channels: [x, youtube, forum, website], media: video, title: "All-new Umbrel Home (up to 4TB)", url: "https://community.umbrel.com/t/introducing-the-all-new-umbrel-home-now-with-up-to-4tb-ssd-storage/22968"}
  - {date: "2025-06-25", stage: release, channels: [youtube, forum], media: video, title: "The all-new Bitcoin Node app", url: "https://community.umbrel.com/t/the-all-new-bitcoin-node-rebuilt-from-the-ground-up/23096"}
  - {date: "2025-09-23", stage: reveal, channels: [x, youtube, forum], media: video, title: "Introducing Backups on umbrelOS (1.5 public beta)", url: "https://x.com/umbrel/status/1970508327479320862"}
  - {date: "2025-11-05", stage: release, channels: [x, github], media: video, title: "umbrelOS 1.5 with Backups. Rolling out today.", url: "https://x.com/umbrel/status/1986033496528433363"}
  - {date: "2025-12-15", stage: milestone, channels: [hackernews], media: earned, title: "Umbrel – Personal Cloud (HN front page, 220 pts)", url: "https://news.ycombinator.com/item?id=46279187"}
  - {date: "2026-01-28", stage: teaser, channels: [x], media: image, title: "tap to see (Umbrel Pro teaser 1/5)", url: "https://x.com/umbrel/status/2016504742709694813"}
  - {date: "2026-01-31", stage: teaser, channels: [x], media: image, title: "clear some desk space, you're gonna need it", url: "https://x.com/umbrel/status/2017626208268402878"}
  - {date: "2026-02-03", stage: release, channels: [x], media: image, title: "OpenClaw live on the Umbrel App Store", url: "https://x.com/umbrel/status/2018699999136362630"}
  - {date: "2026-02-04", stage: hardware, channels: [x, youtube, website], media: video, title: "Introducing Umbrel Pro ($699 / 599 € / £529, ships Feb 9)", url: "https://x.com/umbrel/status/2019085572019757567"}
  - {date: "2026-02-05", stage: hardware, channels: [youtube, x, hackernews], media: video, title: "Making Umbrel Pro", url: "https://www.youtube.com/watch?v=4IAXfgBnRe8"}
  - {date: "2026-02-09", stage: hardware, channels: [producthunt, x], media: photo, title: "First Umbrel Pros ship; PH #3 of the day", url: "https://x.com/umbrel/status/2020817986140152301"}
  - {date: "2026-02-17", stage: hardware, channels: [youtube], media: video, title: "Umbrel Pro Unboxing", url: "https://www.youtube.com/watch?v=GIBEjRUQCsM"}
  - {date: "2026-02-25", stage: release, channels: [youtube], media: video, title: "OpenClaw on Your Own Hardware", url: "https://www.youtube.com/watch?v=GcyWtBpDr5E"}
  - {date: "2026-04-03", stage: community, channels: [youtube], media: short, title: "No Talking. Just a Home Server Unboxing.", url: "https://www.youtube.com/watch?v=HBp3mXkuEow"}
  - {date: "2026-04-21", stage: reveal, channels: [x, youtube, forum, github], media: video, title: "Introducing umbrelOS 1.7 (public beta)", url: "https://x.com/umbrel/status/2046572864967733275"}
  - {date: "2026-04-27", stage: release, channels: [x, github], media: video, title: "umbrelOS 1.7. Rolling out now to all users.", url: "https://x.com/umbrel/status/2048803401572778206"}
  - {date: "2026-05-07", stage: release, channels: [youtube, website], media: video, title: "apps.umbrel.com rebuilt; 300+ apps", url: "https://www.youtube.com/watch?v=JoOcuH123hg"}
  - {date: "2026-09-02", stage: reveal, channels: [x, youtube, forum, github], media: trailer, title: "Introducing umbrelOS 2.0 — Arriving September 22 (public beta)", url: "https://x.com/umbrel/status/2095200468645675324"}
  - {date: "2026-09-22", stage: launch, channels: [youtube, x, github, forum, website], media: keynote, title: "Introducing umbrelOS 2.0: Your cloud, at home (keynote)", url: "https://www.youtube.com/watch?v=lBsKk_NNg2A"}
  - {date: "2026-09-25", stage: release, channels: [youtube, x], media: video, title: "How to install umbrelOS (deep dive)", url: "https://www.youtube.com/watch?v=nEXx2oES3WI"}
  - {date: "2026-09-28", stage: release, channels: [youtube, x], media: video, title: "Photos in umbrelOS 2.0 (deep dive)", url: "https://www.youtube.com/watch?v=xwXYT44jrj0"}
units:
  - {id: U1, name: teaser_drip, trigger: "1-7 days before a reveal", channels: [x], assets: [{kind: square_image, spec: "2160x2160 cropped/partial product", count: "1-5"}, {kind: panorama_set, spec: "4x 3240x1012 'tap to see'", count: "0-1"}, {kind: text_post, spec: "lowercase <=4 words", count: "1-3"}], copy: "cryptic one-liner ('uh oh', 'we cooked', 'locked in', 'final form') + partial image; never names the product", cadence: "before each big beat (4-6/yr)"}
  - {id: U2, name: introducing_reveal, trigger: "major OS feature/version or new hardware", channels: [x, youtube, forum, github, website], assets: [{kind: hero_video, spec: "40-70 s; 16:9 (<=2024) or 4:3 1440x1080/1920x1440 (2025+)", count: 1}, {kind: bento_image, spec: "4:3 3000x2250 or 3840x2880", count: 1}, {kind: feature_card, spec: "3200x2400 4:3 (2025+); 2880x1800 (2021-22); 1440x900 (2020)", count: "3-7"}], copy: "'Introducing <Name>.' -> one-line promise in fragments -> availability line (date + 'Public beta rolling out today' | price $/€/£ + ship date) -> video", cadence: "3-4/yr"}
  - {id: U3, name: feature_card_thread, trigger: "same post as U2", channels: [x], assets: [{kind: feature_card, spec: "one image per reply", count: "3-10"}], copy: "benefit headline sentence -> 1-2 sentences -> image; final reply = thanks to community + order/beta link", cadence: "with every U2"}
  - {id: U4, name: beta_then_ga_pair, trigger: "beta opens at reveal; GA when stable", channels: [x, github, forum], assets: [{kind: cutdown_video, spec: "25-47 s", count: 1}, {kind: release_tags, spec: "beta.1..beta.N -> GA", count: "2-4"}], copy: "'<Name>. Rolling out today.' quoting the reveal post", cadence: "every OS feature release; gap 6-43 days"}
  - {id: U5, name: film_trailer_keynote, trigger: "reveal (trailer) and GA (film/keynote)", channels: [youtube, x, website, forum], assets: [{kind: trailer, spec: "43-58 s", count: 1}, {kind: intro_film, spec: "2-7 min 16:9 or 4:3", count: "0-1"}, {kind: keynote, spec: "~11 min with chapters, native X upload too", count: "0-1"}], copy: "YouTube title 'Introducing <X>: <promise>'; keynote chapters intro -> '<X> in two minutes' -> one chapter per feature -> design -> hardware -> outro", cadence: "per major version/hardware"}
  - {id: U6, name: github_release_notes, trigger: "every tag", channels: [github, in_app], assets: [{kind: bento_image, spec: "4:3", count: 1}, {kind: downloads_list, spec: "SHA256SUMS(.ots), iso, img.xz, update, pi img", count: 1}], copy: "'<ver> brings A, B, C, and several performance improvements and bug fixes.' -> [keynote] -> bento -> New features bullets '**Name:** benefit' -> Discord CTA -> Downloads", cadence: "~1/mo (2024-26)"}
  - {id: U7, name: founder_forum_post, trigger: "reveal and GA", channels: [forum], assets: [{kind: bento_image, spec: "4:3", count: 1}, {kind: link_list, spec: "arrow links", count: 1}], copy: "'Hey everyone,' -> excitement -> '→ Watch the reveal' -> image -> feature one-liners -> how to try -> ask feedback -> date promise -> links", cadence: "3-6/yr"}
  - {id: U8, name: hardware_lifecycle_series, trigger: "new device", channels: [youtube, x, website], assets: [{kind: reveal_film, spec: "~7 min + 45 s cut", count: 1}, {kind: making_of, spec: "~2:20", count: 1}, {kind: ship_day_photos, spec: "4 portrait 3024x4032", count: 1}, {kind: unboxing, spec: "1:30-3:30", count: 1}, {kind: setup, spec: "4-6 min", count: 1}, {kind: use_case_film, spec: "~13 min", count: 1}], copy: "'<Device> <Stage>: <benefit>' titles; making-of = materials + craft story", cadence: "days 0, +1, +5, +13, +15, +21"}
  - {id: U9, name: post_launch_deep_dive, trigger: "3-6 days after GA", channels: [youtube, x], assets: [{kind: video, spec: "5-13 min, named team member on camera", count: "2-3"}], copy: "hook ('Replace Google Photos & iCloud...') -> live demo -> download/buy CTA", cadence: "per major release"}
  - {id: U10, name: app_arrival_post, trigger: "notable app lands in store", channels: [x, youtube], assets: [{kind: screenshot, spec: "1920x1440", count: 1}, {kind: video, spec: "15-35 s (optional)", count: "0-1"}], copy: "casual: '<app> is live on the umbrel app store' -> what it does -> why safer on Umbrel", cadence: "~monthly"}
  - {id: U11, name: launch_platforms, trigger: "big launch day", channels: [producthunt, hackernews, x], assets: [{kind: ph_launch, spec: "tagline + gallery", count: 1}, {kind: show_hn, spec: "link post + founder comment with specs", count: 1}], copy: "'Aaaand we're live on @ProductHunt!' / 'Hey HN, I'm one of the founders... Specs: ... we'll be hanging out in the comments'", cadence: "4 PH + 5 Show HN in 6 yrs"}
  - {id: U12, name: launch_week_promo, trigger: "GA week / Black Friday", channels: [x, website, youtube], assets: [{kind: banner, spec: "site-wide promo bar", count: 1}, {kind: countdown_post, spec: "text", count: "2-4"}], copy: "'10% off Umbrel Home and Umbrel Pro (up to $200) until <date>' -> 'last 2 days' -> 'last 24 hours'", cadence: "per major launch"}
  - {id: U13, name: wall_of_love, trigger: "continuous; spikes post-launch", channels: [website, x], assets: [{kind: tweet_embed, spec: "avatar, handle, date, quote", count: "5-10"}], copy: "'From the community — Nothing but love from people coming home.' + real user posts; reposts in launch week", cadence: "per site redesign; daily reposts in launch weeks"}
  - {id: U14, name: culture_meme_post, trigger: "Bitcoin/news moments, in-jokes", channels: [x], assets: [{kind: text_or_meme, spec: "lowercase one-liner", count: 1}], copy: "joke tied to product or cultural hook (#FullNodeFriday, halving, 'wen big update')", cadence: "several/week 2020-22; lighter now"}
  - {id: U15, name: shorts_ads, trigger: "between launches", channels: [youtube, x], assets: [{kind: short_video, spec: "14-60 s, '#tech #nas'", count: "2-4/mo"}], copy: "visual hook (ASMR unboxing, machining, '0 to 32TB in 60 seconds') -> product -> URL", cadence: "2-4/mo (2026 H1)"}
  - {id: U16, name: app_store_listing, trigger: "new app PR / version bump", channels: [github, in_app, app_store_web], assets: [{kind: icon, spec: "256x256 SVG, square", count: 1}, {kind: gallery, spec: "1440x900", count: "3-5"}, {kind: manifest, spec: "umbrel-app.yml", count: 1}], copy: "tagline -> description (notes first, features list) -> releaseNotes per version ('Full release notes...')", cadence: "continuous"}
  - {id: U17, name: milestone_funding_essay, trigger: "round closed / usage milestone", channels: [blog, forum, x, press], assets: [{kind: essay, spec: "2,000-3,000 words, 4-6 photos", count: 1}], copy: "journey + metrics -> mission -> round/investors -> origin story -> hiring -> thanks", cadence: "once so far (2021)"}
  - {id: U18, name: waitlist_waves, trigger: "pre-GA beta", channels: [website, email, x], assets: [{kind: wave_post, spec: "text", count: "4-5"}, {kind: site_relaunch, spec: "'no more waitlist' page", count: 1}], copy: "'invitations ... to the next N users on the waitlist' with N doubling 100->200->400->everyone -> 'no more waitlist'", cadence: "weekly for ~2 months (2020)"}
reveal_sequence:
  - {step: 1, what: "reserve identity: X @getumbrel + GitHub org same morning", channels: [x, github], gap_days_from_previous: null}
  - {step: 2, what: "'Coming Soon' waitlist page", channels: [website], gap_days_from_previous: 21}
  - {step: 3, what: "first X activity (Hal Finney 'Running bitcoin' repost); bio 'Coming soon'", channels: [x], gap_days_from_previous: 55}
  - {step: 4, what: "positioning page 'Bitcoin and Lightning Node — Request early access'", channels: [website], gap_days_from_previous: 39}
  - {step: 5, what: "first product glimpse on a cultural moment (halving GIF)", channels: [x], gap_days_from_previous: 16}
  - {step: 6, what: "mood tagline site 'Become Bitcoin'", channels: [website], gap_days_from_previous: 26}
  - {step: 7, what: "screenshot teaser series 'Running #Bitcoin/#Lightning' + beta ETA", channels: [x], gap_days_from_previous: 27}
  - {step: 8, what: "code + beta builds public", channels: [github], gap_days_from_previous: 4}
  - {step: 9, what: "'Running #Umbrel' + phased rollout plan + Telegram", channels: [x, github, telegram], gap_days_from_previous: 39}
  - {step: 10, what: "LAUNCH: invites to first 100 waitlist users", channels: [email, x], gap_days_from_previous: 1}
  - {step: 11, what: "wave 2 (200)", channels: [email, x], gap_days_from_previous: 6}
  - {step: 12, what: "wave 3 (400) with v0.2.6", channels: [email, x], gap_days_from_previous: 9}
  - {step: 13, what: "everyone on the waitlist", channels: [email, x], gap_days_from_previous: 9}
  - {step: 14, what: "GA: 'no more waitlist' site relaunch", channels: [website, x], gap_days_from_previous: 38}
  - {step: 15, what: "platform moment: App Store with secret partner apps", channels: [x, blog, github], gap_days_from_previous: 74}
  - {step: 16, what: "category widening: 'personal server OS for everyone' (0.4)", channels: [x, blog, forum, youtube], gap_days_from_previous: 218}
  - {step: 17, what: "funding + hiring essay", channels: [blog, forum, press], gap_days_from_previous: 85}
  - {step: 18, what: "rebrand launch: umbrel.com + 0.5 + first Product Hunt + Show HN", channels: [x, youtube, blog, forum, producthunt, hackernews, website], gap_days_from_previous: 221}
  - {step: 19, what: "own hardware: Umbrel Home", channels: [x, youtube, website, producthunt, hackernews], gap_days_from_previous: 357}
launch_template:
  - {step: T-7, what: "teaser drip (cryptic squares/crops, lowercase one-liners)", channels: [x], gap_days_from_previous: null}
  - {step: T-1, what: "momentum post (hot app lands) — optional", channels: [x], gap_days_from_previous: 6}
  - {step: T0, what: "REVEAL: 'Introducing X.' video + feature-card thread + founder forum post + beta tag / order page + site hero swap", channels: [x, youtube, forum, github, website], gap_days_from_previous: 1}
  - {step: T+1, what: "making-of film (hardware) / Product Hunt + Show HN (big launches)", channels: [youtube, producthunt, hackernews], gap_days_from_previous: 1}
  - {step: GA, what: "'X. Rolling out today.' + GitHub release + keynote/intro film + forum 'is out now' + launch-week discount", channels: [x, github, youtube, forum, website], gap_days_from_previous: "5-43"}
  - {step: GA+3, what: "deep dives with a named team member; unboxing/setup for hardware", channels: [youtube, x], gap_days_from_previous: 3}
  - {step: GA+7, what: "promo countdown ends; wall-of-love reposts; shorts recut from launch footage", channels: [x, youtube], gap_days_from_previous: 4}
```
