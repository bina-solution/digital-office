# n8n: net-front scan (input for the `startup-tail` blueprint)

- **Company:** n8n (n8n GmbH, Berlin). Fair-code workflow automation with AI agents.
- **Observed:** 2026-09-29. All follower and star counts carry that date unless another date is given.
- **Method:** primary sources first.
  - n8n.io pages and sitemaps; blog.n8n.io (Ghost sitemap, RSS, `article:published_time`).
  - docs.n8n.io markdown exports; community.n8n.io (Discourse JSON API).
  - GitHub API; the npm registry (publish time of every version); the YouTube channel page and RSS.
  - Discord invite API; HN Algolia API; Wayback Machine CDX and raw captures of the n8n.io homepage from 2019 to 2026.
  - Search-engine results only for walled platforms (X, Instagram, Facebook, Reddit, Product Hunt).
- **Media:** no images were downloaded. Where a visual is described but was not seen, the entry says so.
- **Evidence tags:**
  - `[verified]`: read directly from the primary source.
  - `[snippet]`: search-engine snippet only, date unknown.
  - `[secondary]`: press, Wikipedia or an investor site.
  - `[uncertain]`: see the note in the row.

---

## 1. Snapshot

**Who and when.** n8n ("n eight n", a numeronym of *nodemation*) is a Berlin company founded by solo founder **Jan Oberhauser**.
- Jan was a former VFX compositor. He had already launched link.fish (2017) and a Google Sheets scraping add-on (2018-02-28) on HN.
- Work on n8n started around April 2018.
- The first public traces are the npm package `n8n@0.0.1` (2019-04-24) and an anonymous "Ask HN" about licensing the next day.
- The code went public on 2019-06-21/23 (npm 0.1.0, GitHub repo).
- The real launch was **2019-10-08**: #1 Product of the Day on Product Hunt the same day as a 728-point HN front page.
- n8n GmbH entered the Berlin register on 2019-11-27 `[secondary]`.

**Funding.**

| Date | Round | Amount | Lead | Others / valuation |
|---|---|---|---|---|
| 2019-12-27 | YC Startup School grant | $15k, equity-free | — | — |
| 2020-03-13 | Seed | $1.5M | Sequoia + firstminute | Runa, Obvious, Tiny VC, System.One, Kevin Hartz, Ilkka Paananen. Sequoia's first German seed. |
| 2021-04-26 | Series A | $12M | Felicis | Sequoia, firstminute, Harpoon |
| 2025-03-25 | Series B | €55M (~$60M) | Highland Europe | HV Capital, Sequoia, Felicis, Harpoon |
| 2025-10-09 | Series C | $180M | Accel | Meritech, Redpoint, Evantic, Visionaries Club, T.Capital, NVentures. Valuation $2.5B; total raised $240M. |
| 2026-05-12 | SAP strategic investment | amount not stated by n8n (Wikipedia: >€60M `[secondary]`) | — | Valuation $5.2B; n8n embedded in SAP Joule Studio |

**Scale (2026-09-29 unless dated).**
- **GitHub:** n8n-io/n8n has 206,249 stars and 60,929 forks. The org has 15,016 followers.
- **YouTube:** @n8n-io has 249K subscribers, 391 videos and 9.72M views.
- **LinkedIn:** 431,469 followers.
- **Discord:** 88,024 members, 7,189 online.
- **Forum:** 179,030 users, 47,752 topics and 574,877 posts.
- **X:** @n8n_io has about 81.4K followers `[snippet]`.
- **Reddit:** r/n8n has about 257k members `[secondary: gummysearch]`.
- **Company-stated (2026-05-12):** "1.7 million monthly active builders" and "1,400+ enterprise customers".
- **Team:** 62 people (2024-10), 71 (end of 2024).
- **ARR:** >$40M (2025-10) `[secondary]`.

---

## 2. Net-front inventory

### 2a. Website (n8n.io and sub-domains)

The sitemap index has 12 child sitemaps:
- pages: 253
- integrations: 2,278
- workflows: 12,738
- creators: 482
- cross-integrations: 46,963, plus 6 "non-native" pair sitemaps
- ai-benchmark: 60

| Section | URL | Exists since | Followers / size | Page copy (verbatim) | Visual | What is posted | Cadence | Notes |
|---|---|---|---|---|---|---|---|---|
| Home | https://n8n.io/ | 2019-10-08 (first Wayback capture on launch day) | GitHub counter 206,245; "200k+ community members"; "4.7/5 stars on G2" | H1 "AI agents and workflows you can see and control" | Dark-navy page, product canvas screenshots, logo wall | Positioning, proof, CTAs | H1 changes about yearly (see §3) | Footer still carries the 2022 slogan "Automate without limits". "See llms.txt" link at the top. |
| Product overview | https://n8n.io/features/ | unknown | — | nav: "Automate business processes without limits on your logic" | screenshots | Feature tour | ad hoc | — |
| AI, AI agents, RAG, MCP | /ai/ /ai-agents/ /rag/ /mcp/ | AI pages since about 2023-24 `[uncertain]` | — | nav: "Get to prod faster — and with more flexibility than coding alone"; MCP: "Build and update n8n workflows from inside your AI app" | canvas shots | AI positioning | ad hoc | — |
| Use-case pages | /itops/ /secops/ /automate-lead-management/ /supercharge-your-crm/ /limitless-integrations/ /embed/ /oem/ /saas/ | unknown | — | — | — | Solution landing pages | ad hoc | — |
| Pricing | /pricing/ and /pricing/startup-plan/ | 2020-12 (cloud early access) | — | — | — | Plans: Starter / Pro / Business / Enterprise (docs glossary) | Changes announced as events (2022-12-12, 2023-08-01, 2025-08-07) | Pricing changes are their own media unit (blog + forum + livestream). |
| Enterprise | /enterprise/ | unknown | — | "Enterprise-ready. Reliable. Scalable. Secure." | server imagery | Sales page | ad hoc | — |
| Docs | https://docs.n8n.io | 2019 (launch-day nav had "Documentation"); new docs site 2020-06-29; refreshed 2026-06-24 | GitHub n8n-docs: 1,799 stars | "Get set up on n8n, build your first workflow, and find inspiration…" | — | Deploy / Build / Integrations / AI / API / Embed / Changelog | continuous | `.md` for every page, llms.txt and sitemap.md. Key-concept glossary. |
| Blog | https://blog.n8n.io | Medium (medium.com/n8n-io) about 2019–2021; Ghost blog.n8n.io from 2021 | 298 posts in the current sitemap (older posts pruned) | — | Hero image per post | Announcements, funding, AI guides, tutorials, case studies | about 15 posts in 26 days (2026-08-31 → 09-25), so about 17/month | Tags: News, AI, Guides, Tutorial, Tips, Interview, Tools & alternatives, By partners, Production AI playbook, Security advisory… |
| Release notes | https://docs.n8n.io/changelog/release-notes.md (+ RSS feed) | 0.x archive from 2019 | 46 entries 2025-12-08 → 2026-09-15 | "A running log of feature-level updates from each n8n release, newest first." | none | One entry per minor | weekly | Three tiers: GitHub releases (every commit), Release notes (every feature), Changelog (curated). |
| Changelog (curated) | https://docs.n8n.io/changelog/readme.md | 2025-12-15 (first entry); "ICYMI: The docs now have a changelog" on 2026-07-08 | 52 entries | "A curated, narrative summary of the most important new n8n features as they roll out." | none | Benefit-led stories | about 6/month | — |
| Community forum | https://community.n8n.io | 2019-09-07 | 179,030 users; 771 new topics and 12,600 posts in the last 30 days | "Join the n8n Community to connect with other users, learn from detailed discussions, and share your automation insights. Explore topics and get support." | Discourse, branded | Q&A, Announcements (181 topics), Built with n8n, Feature requests, Jobs, Security advisories, Community Highlights | 25/day new topics | Announcements category = n8n's primary dated news feed (§5). |
| Templates | https://n8n.io/workflows/ | "Workflows" in launch-day nav (2019); Creator Hub 2023-11-22 | 12,575 templates ("12575 Workflow Automation Templates") | nav: "Explore +10k workflow automation templates" | Node-icon strips on cards | Community-made workflows | about 600/month (derived: 5k on 2025-09-04, 12.6k on 2026-09-29) | 28 category pages (AI, AI chatbot, RAG, CRM, SecOps…). |
| Integrations | https://n8n.io/integrations/ | "Nodes" in launch-day nav (2019) | 2,278 integration URLs + ~47k "A and B" pair pages | nav: "Seamlessly move and transform data between different apps with n8n." | App logos | One programmatic page per node + per node pair | continuous | Counts are inconsistent across surfaces: "400+" (GitHub), "500+" (home), "1000+" (Slack page), "1500+" (README). |
| Creators | https://n8n.io/creators/ | Creator Hub 2023-11-22 | 482 creator pages; top creator 352 templates | "Only the best. Verified n8n Automation Workflows Creators" | Avatars | Creator directory + "Become a verified creator" | continuous | Perks: product-team access, Verified Creator badge, private Discord channel, directory listing. |
| Careers | https://n8n.io/careers/ (+ 5 culture-code pages) | first job post 2020-02-17 | — | "Build the future of AI orchestration. Together." | team photos | Why n8n, founder note, Culture/Code, roles, benefits | ad hoc | Footer badge "Careers — Hiring". |
| About / manifesto | no /about page. See /press "About n8n", /careers, guidelines.n8n.design | — | — | "A brand built by doing, by shipping, by listening, and by making things work." (brand system) | — | Company story is spread across press, careers and anniversary posts | — | The /press boilerplate is stale: it still says "free and open node-based Workflow Automation Tool". |
| Press | https://n8n.io/press/ | unknown | 4 linked articles (seed and Series A era) | "Here you can find the main information about n8n such as guidelines, reusable assets and leadership profiles." | — | Articles, boilerplate, name guideline, links to brand guidelines and press kit, press email | rarely updated | Name rule: "always written in lowercase and pronounced 'n eight n'". |
| Brand guidelines / brand system | https://n8n.io/brandguidelines/ and https://guidelines.n8n.design/ | brand-system site first seen 2026-09-29 ("sneak peek") | — | "Share the power of automation with our n8n logo kit and its usage guidelines." | See §3 | Logo, colors, clear space, don'ts; the new system lists TOV/Logo/Colors/Typography/Grid/Graphic devices/Motion/Visual world/Applications as "Coming soon" | — | The new system uses custom fonts "n8n Baumer" and "n8n Baumer Mono". |
| Newsletter | https://n8n.io/newsletter/ | launch-day homepage had "Stay up to date: sign up to our mailing list" (2019-10-08) | unknown | "Bart and Johannes prepare a monthly roundup of the latest community stories and product development insights." | — | "meet-up announcements, product updates and featured workflows" | monthly | — |
| Case studies | https://n8n.io/case-studies/ | unknown | 34 pages | e.g. "How Huel built an AI first company culture and saved 1,000 hours of manual work" | Customer logos | Outcome stories | ad hoc | — |
| Comparisons / reports / benchmark | /vs/ (21 pages), /reports/2025- and 2026-ai-agent-development-tools/, /ai-benchmark/ (60 model pages) | 2025+ | — | — | — | SEO and analyst content | reports yearly | — |
| Events | https://luma.com/n8n-events, https://n8n.io/intheloop/ | meetups from 2021-02; Luma used 2024+ | — | In The Loop: "Bringing together the builders, leaders, and decision-makers shaping the future of automation." | Event posters on pink/dot grid (brand system) | Meetups, workshops, hackathons, conferences | several/month | In The Loop 2026: 13–14 Oct, Wilhelm Studios Berlin, max 1,200 attendees. |
| Partners / experts / affiliates / ambassadors | /partners/ /expert-partners/ experts.n8n.io /affiliates/ ambassadors.n8n.io | Affiliates 2023-11-28; Ambassadors 2024-06-06 | 19 ambassadors (2024); about 70 (2025) `[secondary]` | — | — | Program pages | — | — |
| Education | /education/ | unknown | — | — | — | Academic program | — | — |
| Merch | https://merch.n8n.io | observed 2026-09-29 | — | "We love that you're interested in our merch!" | — | Shopify store, password-protected, "Opening soon", open to selected community members | — | Brand-system shots show a tee "I'll build it myself", a cap, stickers "go with the [work]flow", and a macro keypad with a pink Run key. |

### 2b. Off-site channels

| Channel | URL / handle | Exists since | Followers (date) | Profile bio (verbatim) | Avatar / banner | What is posted | Cadence (per month) | Notes |
|---|---|---|---|---|---|---|---|---|
| GitHub (org) | github.com/n8n-io | 2018-11-30 | 15,016 followers; 50 public repos | "Free and open fair-code licensed node based Workflow Automation Tool." (org name "n8n - Workflow Automation") | avatar https://avatars.githubusercontent.com/u/45487711 (not viewed) | Code, releases, starters | — | Top repos: n8n (206k stars), self-hosted-ai-starter-kit (15.3k), n8n-docs (1.8k), n8n-hosting (1.7k), n8n-nodes-starter (1.2k). |
| GitHub (main repo) | github.com/n8n-io/n8n | 2019-06-22 (created) / 06-23 (published, per founder) | 206,249 stars; 60,929 forks | "Fair-code workflow automation platform with native AI capabilities. Combine visual building with custom code, self-host or cloud, 400+ integrations." | README banner image (not viewed) + editor screenshot | Releases (`n8n@x.y.z`, beta/stable tags), README | 24–49 releases/month in 2026; about 1 minor/week since 2019 | README H1 "n8n – The Platform for AI Agents and Workflow Automation". Star path: 5k (~5 months after publish), 10k (Nov 2019), 29.5k (2023-08), 40k (2024-04-04), 57.5k (2025-02), 75k (2025-04-08), 100k (2025-05-28), 150k (2025-10-20), 206k (2026-09-29). |
| YouTube | youtube.com/@n8n-io (channel id UCiHVTkJtWSdc9N3h0nUGWLg, title "n8n") | joined 2019-06-27; first known video 2019-09-05 | 249K subscribers; 391 videos; 9,720,204 views | "n8n gives technical teams a workflow automation platform that uniquely combines AI capabilities with business process automation. Connect any app or API while maintaining the flexibility of code with the speed of no-code." | avatar and banner URLs in channel og:image / imageBannerViewModel (not viewed) | Tutorials, courses, "Building With <partner>", launch and pitch videos, livestreams, meetup talks, podcast, event teasers | about 9 (15 videos 2026-08-05 → 09-22); lifetime about 4.5 | 18 playlists: Feature Spotlight, n8n Masterclass Podcast (17), at SCALE, Office Hours (45), The Studio (18), 30 Day AI Sprint (17), Advanced course (37), Beginner course (28), Hackmation, Community Meetup Talks, Community Meetups, Talks & Webinars, Livestreams, Get started with n8n.cloud, Tutorials… Country: Germany. |
| X / Twitter | x.com/n8n_io | Nov 2018 `[snippet]` | about 81.4K `[snippet, undated]` | "Workflow automation for technical teams to build AI solutions that integrate with any app or API at no-code speed and code flexibility." `[snippet]` | not seen (walled) | Features, quick tips, community news, events, YouTube videos | unknown; daily assumed `[uncertain]` | Walled: syndication endpoint rate-limited. Bio and count come only from search snippets. |
| LinkedIn | linkedin.com/company/n8n | unknown (company founded 2019) | 431,469 | Tagline "Flexible AI workflow automation for technical teams." About: "n8n is a workflow automation platform that uniquely combines AI capabilities with business process automation…" | cover image present (not described by source) | Event speakers (In The Loop), how-to posts, community events roundups, feature announcements, ambassador intros | about 5 posts in 24 h, so about 60–120/month `[estimate]` | Specialties: "AI, SOAR, Workflow Automation, and AI agents"; size 51-200 (as listed). |
| Facebook | facebook.com/n8nio | unknown | about 4,708 `[snippet, likely stale]` | "…an extendable workflow automation tool which enables you to connect anything to everything via its open, fair-code model." `[snippet]` | not seen | Mirror of X/LinkedIn content (per n8n's own 2024-09-02 post) | low | The bio reflects the 2020–21 positioning, so the account looks under-maintained. |
| Instagram | instagram.com/n8n.io | unknown | about 1,258 `[snippet, likely stale]` | "Extendable workflow automation tool which enables you to connect anything to everything via its open, fair-code model." `[snippet]` | not seen | Founder and people features (e.g. "Meet Jan Oberhauser, Founder and CEO", ~2025-10) | low | — |
| TikTok | none found | — | — | — | — | — | — | No official account found (the #n8n hashtag is creator-driven). |
| Bluesky | @n8n-io.bsky.social | 2024-09-02 | unknown | — | — | Same content as X/LinkedIn/Facebook | unknown | Opened when X was shut down in Brazil. |
| Discord | discord.gg/n8n (guild 832547762716278804) | server created 2021-04-16; announced 2021-04-27 | 88,024 members; 7,189 online | "Join n8n's Discord for collaborative learning, expert insights, and innovative solutions in automation and integration" | — | Chat; private Verified Creators channel | continuous | The forum stays the knowledge base; Discord is for real-time chat (2021 FAQ). |
| Reddit | reddit.com/r/n8n | unknown | about 257k members; about 131k weekly visitors `[secondary]` | "n8n is an extendable workflow automation tool. With a fair-code distribution model, n8n will always have visible source code…" `[snippet]` | not seen | User questions and showcases | high | Official vs community moderation not verified; the API was blocked. |
| Product Hunt | producthunt.com/products/n8n-io ("n8n: Workflow automation for technical people"); products/n8n-cloud | 2019-10-08 | 61 reviews, 5.0 avg `[secondary]` | 2019 tagline "Open source workflow automation tool" | — | Launches (see §5) | about 1 launch/year | 2019 #1 PoD (756 upvotes, hunter Chris Messina). Cloud 2020-12-09; Notion integration 2021-05-21; desktop 2021-11-04; community nodes 2022-08-11; 1.0 2023-07-24; AI Workflow Builder 2025-10-14 `[secondary]`. |
| Hacker News | no official account (n8n-io used once); founder `janober` | 2019-04-25 | — | — | — | Organic: launch 728 pts (2019), "Fair-code…" 132 (2021), 237 (2023), Series C 235 (2025), plus license criticism threads | organic | The founder answers in threads. HN is a proof channel, not a publishing channel. |
| Newsletter (email) | n8n.io/newsletter | 2019-10 (signup on launch page) | unknown | "Community News" | — | Monthly roundup | 1 | — |
| Podcast | "The n8n Masterclass": YouTube playlist on the official channel, plus Buzzsprout/Apple/Spotify | 2025 | 29 episodes `[snippet]` | "…each week breaks down real business wins using n8n and AI automation" `[snippet]` | — | Interviews with founders and agencies | about 4 | Host Dylan Watkins `[snippet]`. Whether n8n produces it or a partner does is unverified. |
| Events | luma.com/n8n-events; n8n.io/intheloop; forum | community meetups 2021-05; ambassadors 2024-06 | — | Luma: contact "community@n8n.io" to list an event | posters on pink grid | Meetups, workshops, hackathons, Fest, In The Loop conference | 2–8 meetups/month globally (2024–26) | Owned flagship events: n8n Fest (2025-07-09, 2026-07-16), n8n Builders Berlin (2025-09/10), In The Loop (2026-10-13/14). |
| Merch | merch.n8n.io | 2026 (pre-opening) | — | — | — | — | — | Gated. |
| Legacy content | medium.com/n8n-io; dev.to/n8n | Medium 2019–2021; dev.to 2020 | — | Medium: "Free, open and self-hostable fair-code licensed workflow automation tool." | — | Tutorials, user interviews | — | Superseded by blog.n8n.io. |
| Distribution | npm `n8n`; Docker `n8nio/n8n` / docker.n8n.io; `curl -fsSL https://get.n8n.io` | npm 2019-04-24 | 1,185 npm versions | — | — | Builds | weekly | The package page itself is a discovery surface. |

---

## 3. Identification

**Name.** n8n: always lowercase, pronounced "n eight n".
- The press page gives the story: good names were taken, so Jan picked "nodemation" ("node" for Node-View / Node.js, "mation" for automation). It was too long to type in a CLI, so it became the numeronym "n8n".
- Legal entity: n8n GmbH. Cloud brand: "n8n.cloud" (app.n8n.cloud), later just "n8n Cloud".

**Handle consistency.** "n8n" alone was not available anywhere, so every platform uses a suffix or separator: `n8n-io` (GitHub, YouTube @n8n-io, Bluesky), `n8n_io` (X), `n8n.io` (Instagram, domain), `n8nio` (Facebook, Docker Hub), `n8n` (LinkedIn company, Discord invite, npm, Reddit). The YouTube display name is "n8n"; the X display name is "n8n.io". *Lesson for the blueprint:* reserve one canonical separator early. n8n has four.

**Taglines over time** (homepage `<title>` / H1 from Wayback raw captures, `[verified]`):

| Observed | Headline | Title / meta |
|---|---|---|
| 2019-10-08 (launch) | "Open Source Alternative for Zapier/tray.io (Apache 2.0 with Commons Clause)" | "n8n.io - Workflow Automation" / "Free self hostable workflow automation tool"; PH: "Open source workflow automation tool" |
| 2020-04-15 | "Free and Open Workflow Automation Tool — fair-code licensed" | "n8n.io - Free and Open Workflow Automation Tool" |
| 2021-04-15 | "Extendable workflow automation" | same title |
| 2022-06-02 → 2023-01 | "Automate without limits" | from 2022-06-15: "n8n.io - a powerful workflow automation tool" |
| 2023-08-04 | "Build complex automations 10x faster, without fighting APIs" | "…source-available workflow automation tool…" |
| 2024-04-15 → 2025-02 | "Secure, AI-native workflow automation" | "Powerful Workflow Automation Software & Tools - n8n" |
| 2025-03-27 → 2026-02 | "Flexible AI workflow automation for technical teams" | "AI Workflow Automation Platform & Tools - n8n" (pitch video of the same name, 2025-03-27) |
| 2026-09-29 | "AI agents and workflows you can see and control" | "AI Workflow Automation Platform - n8n" |

Persistent slogans: the footer's "Automate without limits" (since 2022) and "Move fast. Break nothing." / "Simple enough to see. Powerful enough to ship." (2026).

**Short description (≤160 chars, current):** "Fair-code workflow automation platform with native AI capabilities. Combine visual building with custom code, self-host or cloud, 400+ integrations." (GitHub repo description, 148 chars)

**Long description (current, YouTube and LinkedIn):** "n8n gives technical teams a workflow automation platform that uniquely combines AI capabilities with business process automation. Connect any app or API while maintaining the flexibility of code with the speed of no-code."
- README variant: "Fair-code platform to build and deploy AI agents and workflows. Combine a visual canvas with custom code, run it self-hosted or in the cloud, and connect to 1500+ integrations."

**Terminology glossary** (n8n's own nouns, from docs "Key concept glossary" and product copy):

| Term | Meaning |
|---|---|
| workflow | A collection of connected nodes that automates a process; starts when a trigger fires |
| node | One step or component: fetch, transform, logic, or an app integration |
| trigger node | Special node that starts a workflow (schedule, webhook, app event, chat, form…) |
| execution | One run of a workflow; counted for quota (error-workflow runs excluded since 2.38) |
| credential | Stored authentication for an app or service, reused by nodes |
| expression | `{{ }}` JavaScript used to set parameters from earlier node data |
| canvas / editor | The visual UI where nodes are added and connected |
| cluster node / root node / sub-node | Root plus attached sub-nodes (model, memory, tool) that configure each other; how AI agents are built |
| AI Agent node | LLM-driven node that chooses tools; plus "n8n Agents" (2026): reusable agents you set up once |
| template | Pre-built workflow from n8n or the community, importable into an instance |
| community node / verified node | Third-party npm node packages; "verified" ones install on Cloud |
| data pinning | Freezing a node's output during development |
| sub-workflow / error workflow | A workflow called by another / one that runs when another fails |
| project | Grouping of workflows, credentials and variables with roles |
| data table | Built-in persistent storage (2025-09) |
| evaluation | Testing AI workflows against datasets (2025) |
| Chat Hub / Chat Trigger | Chat interfaces over workflows and agents |
| n8n Assistant / AI Workflow Builder | In-product agent that builds workflows from a description |
| MCP server / MCP trigger | Exposing workflows to AI apps via Model Context Protocol |
| task runner | Isolated process for Code-node execution |
| instance / queue mode / worker | A running n8n install; scaled mode with workers |
| edition / plan / entitlement / license | Community, Business or Enterprise editions; Starter, Pro, Business or Enterprise plans; features unlocked by a license key |
| fair-code / Sustainable Use License | n8n's source-available licensing model: Apache 2.0 + Commons Clause until 2022-03, then SUL |
| Gateway credits | Pay-as-you-go access to AI models without provider accounts (2026) |
| Canvas Groups | Collapsible node groups (2026) |
| Creator / Verified Creator | Template authors in the directory |
| Ambassador / Expert Partner | Community event hosts / certified consultants |
| Community Hangout / Livestream | Recurring community broadcasts |
| In The Loop | n8n's first conference (2026) |

**Colors.** Brand guidelines, `[verified]`:
- **Pink #EA4B71**: primary; the logo color.
- **Dark #040506**: "Brand Black".
- **White #FFFFFF**.

Site design tokens (n8n.io CSS 2026, `[verified]`):

| Token | Hex |
|---|---|
| shades-dark-navy | #1B1728 |
| shades-midnight-navy | #0E0918 |
| shades-deep-navy | #1F192A |
| primary-600 | #EE4F27 |
| primary-400 | #F96E49 |
| secondary / heading-orange | #FF9B26 |
| button-primary | #6B21EF |
| additional blue | #077AC7 |
| green-1 / green-2 | #186F44 / #35A670 |
| hazy-white | #F7F6FA |
| text-primary | #D1CECE |
| In The Loop black | #141414 |

Historical palettes:
- **2019 – early June 2022:** coral **#FF6D5A** as the primary, on Element-UI greys.
- **June 2022 – March 2025:** pink #EA4B71 logo on a navy **#101330** site with teal **#20B69E** and periwinkle **#8287EB**.

**Typography.**
- 2019–2022: Open Sans.
- 2022–2025: "sunset-gothic" + "moderat" web fonts.
- Since 2025-03-26: **Geomanist** (light/regular/medium, plus "geomanist-book"), with a mono font for code.
- The 2026 brand-system preview uses custom variable fonts **n8n Baumer** and **n8n Baumer Mono**, plus "dot type" (pixel/dot lettering on merch).

**Theme.**
- The website has been **dark-first** since 2025-03-26 ("Also, dark mode. Do I need to say more?").
- Micro-sites (In The Loop) run light: white, #141414 and pink.
- The forum auto-switches theme (2024-10).

**Logo.**
- Horizontal lockup: node-graph symbol plus lowercase "n8n" wordmark. The symbol reads as connected nodes, and the "8" is often read as a loop; that reading is secondary-source.
- The logo must be one of Pink, Dark or White: Brand Black on light, White on dark.
- Clear space is 4X. Minimum width is 100 px / 30 mm.
- Don'ts: "Don't use the wordmark alone", "Don't align vertically", no shadows, no busy backgrounds, no tilt, squeeze or stretch, "Don't reverse the icon and wordmark", don't change spacing or proportions.
- The app icon is a "pink symbol on black" (brand system).

**Rebrands:**
1. **2022-06-10..15** (bracketed by Wayback captures 06-09 vs 06-15): new website plus logo recolor from coral #FF6D5A to pink #EA4B71; logo moved from PNG to SVG. It launched with the "Automate without limits" era. No announcement post was found.
2. **2025-03-26:** website redesign "New fonts. New vibes. Same automation magic". Testing showed the old design felt "friendly, but also a bit toy-like", so they went tech-focused and dark. Called "the first step" toward a new visual identity. It shipped the day after Series B and the day before the new pitch video.
3. **2026 (in progress):** brand system "sneak peek" at guidelines.n8n.design. It pitches "n8n's next chapter: same directness, same principles, built for where automation is heading". Graphic devices: dot grid, pixel-grid progress ring, pill tags, pink inflatable shapes at events.

**Illustration and motion.**
- Product-as-illustration: real canvas screenshots with nodes and connections as heroes.
- Integration logo grids; line icons (Phosphor set `i-ph:` on site; white line icons on a black dot grid in the brand system); green icon gradients.
- Event posters on a pink grid; team and event photography; social cards (hiring, model launches such as "Moonshot Kimi", tutorials).
- Motion:
  - short teasers (24 s "Node Runner Reveal", 2026-09-15)
  - ~3 min pitch videos (174 s, 2025-03-27; "< 3 min" demo, 2019-09-05)
  - long tutorials (~25 min)
  - aftermovies (n8n Fest 2026)

**Voice and tone.** Builder-to-builder, technical, direct, lightly punny, community-first.
- Puns: "You starred us 100,000 times. We're feeling pretty triggered!", "Builders don't w8", "go with the [work]flow".
- Emphasis on control and transparency ("you can see and control", "Build AI agents you can actually follow").
- Anti-hype framing (careers: "not chasing the typical hype cycle").
- Emoji in forum titles (🎉 📸 🚀).
- Founder-signed posts for big moments (funding, license, anniversaries).

---

## 4. Content

**About / who-we-are.** There is no single About page. The pieces:
- **/press:** boilerplate, the name story, brand assets and press kit.
- **/careers:** sections in order:
  1. "Why n8n": product, community, people, potential ("$1bn ARR with fewer than 500 people")
  2. founder quote ("A note from our Founder, Jan")
  3. **Culture/Code**: 5 values, each with its own page:
     - WE ARE BUILDERS
     - WE ARE WELCOMING
     - WE DO THE RIGHT THING EVEN WHEN IT'S HARD
     - WE ARE EARLY
     - WE ARE MULTIPLIERS
  4. "Who thrives here"
  5. "Your impact"
  6. "Roles at n8n": Sales, Marketing, Engineering, Operations, Product & Design, People
  7. "Life at n8n": remote-first Europe/UK/some US, time off, learning budget, care, fair pay
  8. YouTube CTA
- **Anniversary posts:** 2021-06-23 (blog), 2024-10-08 (forum). These carry the company history.

**Docs and tutorials.**
- **docs.n8n.io sections:**
  - Get started (welcome, choose how to use, build your first workflow, learning paths, glossary)
  - Deploy (Cloud: trial, plans, admin dashboard, Gateway credits; Self-host: one-line setup, Docker, Compose, npm, cloud providers)
  - Build, Integrations (node plus credential page per app), Advanced AI, API, Embed
  - Changelog: release notes 0.x/1.x/2.x, breaking changes for v1/v2/v3, migration tool
- Every page is available as `.md`, and there is `llms.txt`.
- **Learning:**
  - YouTube Beginner (28 videos) and Advanced (37) courses
  - text courses Level 1 and Level 2 (2021–2022, retired 2026-06-18)
  - "Learning paths" with quizzes in the docs
  - forum Tutorials / Tips & Tricks categories
  - blog tutorials

**Integrations listing: every field of ONE listing** (https://n8n.io/integrations/slack/, in page order):
1. `<title>` "Slack integrations | Workflow automation with n8n"
2. meta/OG description "Integrate Slack with hundreds of other apps… Free and source-available."
3. OG image (global n8n-og-image.png)
4. twitter:site "@n8n_io"
5. breadcrumb "Back to integrations"
6. H1 "Integrate Slack with 1000+ apps and services"
7. intro paragraph (app-category phrase + verbs + "All within a building experience you will love.")
8. CTAs "Get Started" and "See n8n in action" (YouTube pitch video)
9. "Create workflows with Slack integrations": sortable grid of partner apps (Sort: Popularity), each linking to an A-and-B page
10. Documentation tiles: "Slack Node Docs + Examples" and "Slack Credential Docs"
11. "Popular ways to use the Slack integration": template cards (title, links to /workflows/<id>-<slug>/) with "Load more"
12. Documentation (repeat)
13. "Supported actions": resources (Channel, File, Message, Reaction, Star, User, User Group), each operation with a one-line description (e.g. Archive, Create, History, Invite, Send, Send and Wait for Response, Update…)
14. "About Slack": vendor blurb
15. "Related categories": Communication, HITL
16. "Similar integrations": 10 apps plus "Show all integrations"
17. logo wall "AI agents and workflows for technical teams at"
18. "Slack integration tutorials": blog cards with tag (Bot, Tutorial, Tips), title and excerpt
19. "Connect Slack with your company's tech stack…" with CTA "Contact Sales"
20. "FAQ about Slack integrations": 5 templated Q&As (setup; permissions/API keys; combining apps; common use cases; pricing model: "n8n charges only for full workflow executions")
21. "Need help setting up your Slack integration?": 5 live forum threads (title, date, author, excerpt, "Open topic")
22. testimonial wall
23. closing CTA "Simple enough to see. Powerful enough to ship."

**Template listing fields** (templates API record `/api/templates/workflows/2462`):

| Field | Example |
|---|---|
| id | 2462 |
| name | "Angie, personal AI assistant with Telegram voice and text" |
| totalViews / views / recentViews | 421,033 |
| createdAt | 2024-10-14 |
| description | markdown: "How it works" → steps |
| workflow | JSON: meta, nodes, connections, pinData |
| workflowInfo.nodeCount / nodeTypes | 15 |
| status / reviewStatus | published |
| readyToDemo | — |
| lastUpdatedBy | — |
| user | name, username, bio, verified, links[], avatar |
| nodes[] | id, icon, name, codex with alias, details, categories |
| categories[] | e.g. "Personal Productivity" |
| image[] | — |

**Home page sections in order** (2026-09-29):
1. Nav: Product (overview, Integrations, Templates, AI, MCP) · Use cases (10) · Docs (Self-host, Documentation, Our license, Changelog) · Community (Forum, Learn, Careers, Blog, Creators, Partners, Hire an expert, Events, Support) · Enterprise · Pricing · GitHub star counter · Sign in · Get Started
2. Hero: H1, sub-line "Build visually, go deep with code, connect to anything…", CTAs "Get started for free" / "Talk to sales"
3. Logo wall (12 enterprises)
4. Role tabs: IT Ops, Sec Ops, Dev Ops, Sales, plus a pitch video
5. Three proof cards: GitHub Top 50 206.2k stars; G2 4.7/5; 200k+ community
6. "Plug AI into your own data & over 500 integrations"
7. "Build AI agents you can actually follow" (3 sub-blocks)
8. "Code when you need it, UI when you don't"
9. "Move fast. Break nothing."
10. Case studies (Huel, Vodafone)
11. "Enterprise-ready" with 4 cards
12. Testimonial wall (X/LinkedIn handles)
13. Final CTA
14. Footer: 4 link groups (Company, Resources, Community, Legal) + 5 socials (X, GitHub, Discord, LinkedIn, YouTube) + "In The Loop — Oct 2026" badge

*Launch-day (2019) homepage for comparison:* nav → hero ("Open Source Alternative for Zapier/tray.io") → "Watch a Short demo (< 3 min)" → "Why use n8n?" (Free/Open Source · Easily extendable · Your data stays with you) → "What can be done with n8n?" (Automate daily tasks · Sync Data · React to events) → "How to get started?" (CLI · Docker) → "Stay up to date" newsletter → footer (GitHub n8n-io, Twitter n8n_io, Contact, Impressum, Privacy).

**Blog post types:**
- (a) product announcements: "Introducing X" / "Announcing X"
- (b) funding letters by the founder
- (c) milestone/retrospective posts (anniversary, "YYYY in Review")
- (d) SEO guides and listicles ("best AI agent builders", "RAG vs agentic RAG", "X alternatives")
- (e) series ("Production AI Playbook" 5 parts, "AI maturity" 3 parts)
- (f) tutorials and node spotlights
- (g) partner posts (tag "by partners": MongoDB, Firecrawl, IONOS…)
- (h) research reports
- (i) security advisories
- (j) internal stories ("How we use n8n: <name>", "Rebuilding our AI Assistant on n8n")

**Newsletter.** Monthly "Community News" by the community team: meet-ups, product updates, featured workflows.

**News / press.** /press lists 4 articles (TechCrunch seed and Series A, 2 German pieces), the boilerplate and the press email. Funding news is published simultaneously on the blog, the forum Announcements category (with a banner), press and social.

**Release notes: format of ONE entry** (docs Release notes, 2026-09-15):

```
## `n8n 2.40` Add Microsoft Dataverse core node, plus 31 other features
**Released:** 2026-09-15
* [Grist Node: Add OAuth2 as an authentication option](<GitHub PR URL>): <2–5 sentences: what changed,
  how to use it, defaults, backward compatibility>
* [AI Agent Node: Add option to force a tool call on the first iteration](<PR URL>): …
  (… 32 bullets total, one per feature, generated from merged PRs and reviewed)
```

Companion formats:
- **GitHub release** `n8n@2.41.0`: prerelease flag = beta. `# [2.41.0](compare-link) (2026-09-22)`, then `### Bug Fixes` / `### Features` / `### Performance Improvements` with `* **scope:** message ([#PR](…)) ([sha](…))`.
- **Changelog story:** `## <benefit headline>` / `**Released:** <date> in [n8n X.Y](…)` / 3–5 paragraphs covering what, why it matters, how to use, and availability per plan/version.
- **Channels:** `stable` (production) and `beta` (latest); "n8n releases a new minor version most weeks".
- **1.x-era entry (2024-01-10):** the version, "View the commits", release date, a one-line summary, highlighted features in info boxes, and a Contributors list.

**Vision / manifesto.**
- 2019: self-hosted, "your data stays with you", extendable.
- 2020–22: "fair-code" (n8n promoted the fair-code.io concept).
- 2025 Series B thesis: "AI, code, and humans" are "the winning recipe".
- 2025 Series C: orchestration puts AI to work reliably.
- Careers: "n8n is becoming the default orchestration layer between AI models and business systems".
- X bio line `[snippet]`: "Roadmaps adapt, principles stay: flexible, open, community-first, easy to start, ready for complexity."
- Brand system: "n8n was built for builders who wanted to see exactly how their systems worked, not hand that over to a black box."

---

## 5. Media timeline

| Date | Stage | Channel(s) | Media | Title | URL | Note |
|---|---|---|---|---|---|---|
| 2018-02-28 | pre-history | HN | post + founder comments | Founder launches a Google Sheets scraping add-on (after link.fish, 2017-11) | https://hn.algolia.com/api/v1/search?tags=comment,author_janober | Founder's HN-launch habit predates n8n |
| ~2018-04 | pre-launch | — | — | Work on n8n starts (Jan, then in VFX) | https://community.n8n.io/t/57000 | retrospective |
| 2018-09 / 2019-05 | pre-launch | (retrospective) | image | "n8n in September 2018 (pre-release)" and "May 2019 (pre-release)" UI screenshots | https://community.n8n.io/t/57000 | first shown publicly 2024-10-08 |
| 2018-11 | pre-launch | X | account | @n8n_io joined | https://x.com/n8n_io | `[snippet]` |
| 2018-11-30 | pre-launch | GitHub | org | n8n-io organization created | https://github.com/n8n-io | `[verified]` API |
| 2019-04-24 | pre-launch | npm | package | `n8n@0.0.1` published (name reserved) | https://www.npmjs.com/package/n8n | `[verified]` |
| 2019-04-25 | pre-launch | HN | Ask HN | "Ask HN: What License for New 'Open Source' Project? Commons Clause?" (by n8n-io) | https://news.ycombinator.com/item?id=19748652 | Project unnamed; 3 points |
| 2019-06-21 | reveal (soft) | npm | release | `n8n@0.1.0` (+0.1.1, 0.1.2 the same day) | https://www.npmjs.com/package/n8n?activeTab=versions | first usable release |
| 2019-06-22/23 | reveal (soft) | GitHub | repo | n8n-io/n8n published | https://github.com/n8n-io/n8n | API 06-22; founder says 23 June |
| 2019-06-27 | reveal (soft) | YouTube | channel | Channel created | https://www.youtube.com/@n8n-io/about | — |
| 2019-07-11 → 09-20 | release | npm / GitHub | releases | 0.4.0 → 0.21.0 (18 minors in 10 weeks) | https://www.npmjs.com/package/n8n?activeTab=versions | ship-in-public cadence |
| ~2019-08 | community | GitHub | PR | First pull request from a user ("two months after publishing") | https://blog.n8n.io/celebrating-n8n-second-anniversary/ | contributor RicardoE105 later hired |
| 2019-09-05 | teaser | YouTube | video (<3 min demo) | "n8n.io - Slack Notification on Github Star" | https://www.youtube.com/watch?v=3w7xIMKLVAg | embedded on launch homepage; 76,220 views |
| 2019-09-07/08 | community | forum | forum | community.n8n.io opens (Feedback, Announcements; first feature requests) | https://community.n8n.io/t/20 | — |
| 2019-10-04/06 | release | npm | release | 0.22.0 / 0.23.0 ("facelift" before launch) | https://www.npmjs.com/package/n8n | — |
| **2019-10-08** | **launch** | Product Hunt | launch post | "n8n — Open source workflow automation tool" | https://www.producthunt.com/products/n8n-io | #1 Product of the Day, 756 upvotes, 80 comments, hunter Chris Messina `[secondary]` |
| **2019-10-08** | **launch** | HN | link post | "N8n.io – Workflow automation alternative to Zapier" | https://news.ycombinator.com/item?id=21191676 | 728 pts / 196 comments; posted by "tablet". Founder: he "had actually planned to post it later" himself |
| 2019-10-08 | launch | website | page | "Open Source Alternative for Zapier/tray.io" + demo + newsletter signup | https://web.archive.org/web/20191008134525/https://n8n.io/ | earliest Wayback capture |
| 2019-10/11 | milestone | GitHub | stars | 5,000 stars (~5 months after publish); 10,000 "by November 2019" | https://blog.n8n.io/celebrating-n8n-second-anniversary/ | — |
| 2019-11-27 | company | — | registry | n8n GmbH registered (Berlin) | https://en.wikipedia.org/wiki/N8n | `[secondary]` |
| 2019-12-27 | milestone | forum | post | "n8n is one of the YC Startup School 2019 Grant Winners" | https://community.n8n.io/t/582 | $15k equity-free |
| 2020-02-17 | hiring | forum | post | "Job: Come and join n8n!" | https://community.n8n.io/t/844 | — |
| 2020-02-27 | community | forum | post | "Thank you RicardoE105 for 50+ integrations created!" | https://community.n8n.io/t/902 | contributor spotlight |
| 2020-03-01 | release | forum | advisory | "Please update n8n@0.55.0 to fix security issue!" | https://community.n8n.io/t/914 | first security advisory |
| **2020-03-13** | **funding** | TechCrunch, blog | article | Seed $1.5M (Sequoia + firstminute) | https://techcrunch.com/2020/03/13/n8n-a-fair-code-workflow-automation-platform-raises-seed-from-sequoia-as-vc-firm-steps-up-in-europe | "fair code" framing debuts in press |
| 2020-04 | hiring | (retrospective) | — | First team members join; 4 employees by June 2020 | https://community.n8n.io/t/57000 | — |
| 2020-04-15 | identity | website | page | H1 "Free and Open Workflow Automation Tool — fair-code licensed" | https://web.archive.org/web/20200415000000*/n8n.io | — |
| 2020-05-08 → 06-15 | content | dev.to, HN | articles | Tutorial and user-interview series ("Creating Telegram Bots with n8n…", "Mattias Larsson talks about running n8n on ships") | https://dev.to/n8n | cross-posted to HN by staff |
| 2020-06-29 | release | forum, docs | post | "New docs for n8n" | https://community.n8n.io/t/1666 | n8n-docs repo created 2020-05-23 |
| 2020-08-20 | community | forum, HN | Show HN | "Nodemaker launch" (community node generator) | https://community.n8n.io/t/2097 | 200 nodes by end of Oct 2020 |
| **2020-12-09** | **launch** | Product Hunt, forum | launch | "n8n.cloud Early Access launch on Product Hunt 🚀" | https://community.n8n.io/t/3322 | monetization reveal; GA January 2021 |
| 2020-12-30 | milestone | npm, GitHub | release | 100th release (0.100.0) | https://blog.n8n.io/celebrating-n8n-second-anniversary/ | "we release a new version every week" |
| 2021-01-04 | community | HN | post | "Fair-Code Automation with n8n.io" | https://news.ycombinator.com/item?id=25632892 | 132 pts |
| 2021-02-01 | event | forum | post | "Let's catch-up in an n8n meet-up! 🤝" | https://community.n8n.io/t/4121 | — |
| 2021-04-16 / 04-27 | community | Discord, forum | server + post | "The n8n community is now on Discord! 💭" | https://community.n8n.io/t/5473 | guild created 04-16 |
| **2021-04-26** | **funding** | blog, Medium, TechCrunch, forum, HN | article | "Announcing our $12m Series A funding" (Felicis) | https://blog.n8n.io/series-a-announcement/ | 16,000 community members cited in press `[secondary]` |
| 2021-05-03 | event | forum, YouTube | meetup | Monthly community meetups begin | https://community.n8n.io/t/5579 | — |
| 2021-05-21 | launch | Product Hunt | launch | "Notion n8n Integration is on Product Hunt 💪" | https://community.n8n.io/t/5890 | integration-as-launch |
| 2021-06-23 | milestone | blog, Medium | article | "Celebrating n8n's second anniversary" (Jan) | https://blog.n8n.io/celebrating-n8n-second-anniversary/ | 270+ integrations |
| 2021-11-04 | launch | Product Hunt | launch | "n8n desktop app is live on Product Hunt" | https://community.n8n.io/t/8883 | #30, 200 upvotes `[secondary]` |
| 2022-03-03 → 03-17 | pivot (license) | forum → blog | posts | "A new license for n8n" (heads-up) → "Announcing the new Sustainable Use License" | https://blog.n8n.io/announcing-new-sustainable-use-license/ | 14-day pre-announcement |
| 2022-03-15 | release | blog, forum | article | User Management MVP | https://blog.n8n.io/announcing-user-management/ | — |
| **2022-06-10..15** | **rebrand** | website | site + logo | New site; logo coral #FF6D5A → pink #EA4B71; "Automate without limits" | https://web.archive.org/web/20220615051024/https://n8n.io/ | Wayback bracket; no announcement found |
| 2022-08-11 | launch | Product Hunt | launch | "n8n community node repository launch on ProductHunt" | https://community.n8n.io/t/16587 | — |
| 2022-12-12 | pricing | forum | post | "Paid self-hosted features coming soon" | https://community.n8n.io/t/20716 | 9,419 views |
| 2022-12-31 | milestone | forum | post | "2022 in Review" | https://community.n8n.io/t/21320 | — |
| 2023-05-17 | release | forum | post | "Python Support and Release Versions" | https://community.n8n.io/t/26291 | — |
| **2023-07-19 → 07-24** | **launch (major)** | forum → blog, forum, Product Hunt | post / article | "n8n version 1 ready to be tested 🎉" → "n8n Version 1.0 - A new milestone in our journey" | https://blog.n8n.io/n8n-version-1/ | PH 786 upvotes `[secondary]` |
| 2023-08-04 | identity | website | page | H1 "Build complex automations 10x faster, without fighting APIs"; "29,504 Github users ❤️ n8n" | https://web.archive.org/web/20230804082546/https://n8n.io/ | — |
| **2023-10-04** | **launch (AI)** | docs, HN, forum, YouTube | release, Show HN, workshop | "LangChain in n8n (beta)" | https://news.ycombinator.com/item?id=37765778 | AI pivot reveal; workshop video 10-23 |
| 2023-10-13 → 11-15 | community | forum | contest | AI LangChain Contest → winners | https://community.n8n.io/t/31557 | — |
| 2023-11-22 | community | forum | post | "The Creator Hub is here!" | https://community.n8n.io/t/33281 | template creators program |
| 2023-11-28 | community | forum | post | "Are you an Affiliate yet?" | https://community.n8n.io/t/33519 | — |
| 2023-11-29 | release (AI GA) | docs | release | LangChain general availability (1.19.0) | https://docs.n8n.io/changelog/release-notes-1.x.md | Chat Trigger follows 2024-01-10 |
| 2024-04-04 | milestone | forum | post | "We just reached 40k stars on Github!" | https://community.n8n.io/t/43753 | — |
| 2024-04-15 | identity | website | page | H1 "Secure, AI-native workflow automation" | https://web.archive.org/web/20240415000000*/n8n.io | — |
| 2024-06-06 | community | forum | post | "Announcing the n8n Ambassador Program!" | https://community.n8n.io/t/47996 | 19 ambassadors, 14 events in 2024 |
| 2024-08-20/21 | launch (AI) | forum, blog, GitHub | post, article, repo | Self-hosted AI Starter Kit | https://blog.n8n.io/self-hosted-ai/ | repo now 15.3k stars |
| 2024-09-02 | channel | Bluesky | account | "New social media account: Bluesky" | https://community.n8n.io/t/53126 | — |
| 2024-10-08 | milestone | forum, social | post (#n8nTurns5) | "We're celebrating - n8n turns five!" | https://community.n8n.io/t/57000 | PH launch day = "true birthday" |
| 2024-10-29 | release (beta call) | forum | post | "Help Us Test the New n8n Canvas (Beta)" | https://community.n8n.io/t/60070 | — |
| 2025-01-21 | milestone | blog | article | "n8n's 2024 in Review" | https://blog.n8n.io/2024-in-review/ | team 37 → 71 |
| **2025-03-25** | **funding** | blog, forum, press | article + 1920×1080 banner | "n8n closes €55M Series B round led by Highland Europe" | https://blog.n8n.io/series-b/ | ARR 5x YoY; 230k active users `[secondary]` |
| **2025-03-26** | **rebrand** | website, forum | site | "New fonts. New vibes. Same automation magic" | https://community.n8n.io/t/92983 | dark, tech-focused redesign |
| 2025-03-27 | reveal | YouTube | video (174 s) | "n8n: Flexible AI Workflow Automation for Technical Teams [2025]" | https://www.youtube.com/watch?v=ZCuL2e4zC_4 | new tagline's pitch video |
| 2025-04-10 | release (AI) | forum | post | "We're adding MCP Client tool & MCP Trigger nodes" | https://community.n8n.io/t/99338 | 32k views |
| 2025-05-28 | milestone | forum | post (1920×1080) | "100k stars on GitHub! 🎉" | https://community.n8n.io/t/122554 | — |
| 2025-06-06 | release (AI) | blog | article | "Introducing Evaluations for AI workflows" | https://blog.n8n.io/introducing-evaluations-for-ai-workflows/ | beta call 05-22 |
| 2025-07-09 | event | Berlin, forum | event | First n8n Fest (invite-only) | https://community.n8n.io/t/137261 | — |
| 2025-08-07 | pricing | blog, forum, livestream | article | "New plan, no active workflow limits" | https://blog.n8n.io/build-without-limits-everything-you-need-to-know-about-n8ns-new-pricing/ | Q&A livestream 08-21 |
| 2025-09-22 | release | forum | post | "Data Tables Are Here! 📊" | https://community.n8n.io/t/192256 | — |
| 2025-09-29 → 10-13 | teaser → reveal | forum → forum, Product Hunt | posts | "AI-powered workflow-building coming soon" → "Introducing AI Workflow Builder (Beta)" | https://community.n8n.io/t/204919 | PH 10-14 `[secondary]` |
| **2025-10-09** | **funding** | blog, forum, HN, press | article | "n8n raises $180m to get AI closer to value with orchestration" | https://blog.n8n.io/series-c/ | $2.5B; HN 235 pts |
| 2025-10-20 | milestone | forum | post | "150,000 stars on GitHub ⭐" | https://community.n8n.io/t/208779 | — |
| **2025-11-25 → 12-08** | **launch (major)** | forum → blog, npm | post / article | "Announcing n8n version 2.0 - coming soon!" → "Introducing n8n 2.0" | https://blog.n8n.io/introducing-n8n-2-0/ | pre-announcement had 111,608 views |
| 2025-12-15 → 2026-01-28 | launch | forum → blog | posts | "Announcing Chat Hub Beta!" → "Introducing Chat Hub" | https://blog.n8n.io/introducing-chat-hub/ | — |
| **2026-05-12** | **funding / partnership** | blog (×2) | articles | "Announcing SAP's strategic investment in n8n" + SAP partnership | https://blog.n8n.io/n8n-sap/ | $5.2B valuation |
| 2026-07-09 → 09-09 | launch (AI) | forum → blog | posts | "Introducing the AI Assistant" → "Introducing n8n Assistant" | https://blog.n8n.io/introducing-n8n-assistant/ | — |
| 2026-07-16 | event | Berlin | event + aftermovie (07-23) | n8n Fest 2026 | https://community.n8n.io/t/304483 | — |
| 2026-08-05 → 09-25 | launch (AI) | forum → blog | posts | "Introducing n8n Agents" | https://blog.n8n.io/introducing-n8n-agents/ | — |
| 2026-08-19 → 10-13/14 | event | forum, web, YouTube, LinkedIn | tickets, teaser, conference | In The Loop 2026: early-bird tickets; "Node Runner Reveal" 24 s teaser (09-15); community discount (09-23) | https://n8n.io/intheloop/ | first conference |
| 2026-09-07 | community | forum | weekly series | "Introducing the n8n Community Weekly Challenge" | https://community.n8n.io/t/311603 | a new challenge every Monday |
| 2026 (first seen 09-29) | rebrand (preview) | guidelines.n8n.design | site | "n8n Brand System", "Thanks for taking a sneak peek" | https://guidelines.n8n.design/ | new typefaces and dot grid |

**Recurring rhythm since 2023** (representative, not listed row by row):
- weekly minor release (GitHub + npm + docs release notes)
- about 6 changelog stories/month
- about 17 blog posts/month (mostly SEO guides)
- about 9 YouTube videos/month
- about 25 new forum topics/day; Announcements about 3–8/month
- monthly livestream / hangout (2024–25)
- ambassador meetups several/month, each followed by a "Meetup - Report 📸"
- star-milestone posts at each round number
- 1–2 funding events/year since 2025
- 1 flagship Berlin event/year since 2025
- 1 major version about every 2.5 years (1.0 2023-07, 2.0 2025-12; 3.0 breaking-changes page already live)

---

## 6. Repeatable media units

Asset specs marked (est.) are inferred. Sizes without that mark were read from forum attachment metadata or YouTube page data.

**U01 · weekly-release-train**
- **Trigger:** weekly minor release. It goes out as `beta`, is promoted to `stable` about a week later, and gets daily patches incl. backports to the previous major (1.123.x).
- **Channels:** GitHub Releases; npm dist-tags (latest/stable/beta/next/rc); Docker; docs Release notes + RSS.
- **Assets:** auto-generated conventional-commit changelog; 1 docs entry "`n8n X.Y` <top feature>, plus N other features" with one bullet per PR; no visuals.
- **Copy:** headline = biggest feature + count → per bullet "<Node>: <imperative change>" → what changed → defaults / backward-compat.
- **Cadence:** about 4 minors/month since 2019 (41 minors in the first 6 months); 24–49 npm versions/month in 2026.
- **Examples:** https://github.com/n8n-io/n8n/releases/tag/n8n@2.41.0 · https://docs.n8n.io/changelog/release-notes.md · https://raw.githubusercontent.com/n8n-io/n8n-docs/main/feeds/release-notes.xml

**U02 · feature-story**
- **Trigger:** a notable feature reaches users.
- **Channels:** docs Changelog; forum Announcements; blog "Introducing / Announcing X"; YouTube demo (Feature Spotlight); LinkedIn / X.
- **Assets:** 1 hero screenshot or GIF (forum); changelog text (3–5 paragraphs); 1 YouTube demo of 2–10 min (est.); 1 social card.
- **Copy:** benefit headline → the problem before → what it does → how to enable → availability by plan/version → docs link → feedback ask.
- **Cadence:** changelog about 6/month; forum about 2–4/month; blog "Introducing…" about 1–2/month.
- **Examples:** https://docs.n8n.io/changelog/readme.md · https://community.n8n.io/t/302304 · https://blog.n8n.io/announcing-autosave/

**U03 · beta-call ("Help us test")**
- **Trigger:** a feature is ready for community testing.
- **Channels:** forum thread (feedback collector); optional survey or usability sign-up.
- **Assets:** 1 screenshot + enable instructions.
- **Copy:** "Help us test X (Beta)" → what it is → how to enable (flag / version / docker tag) → what feedback is wanted → known limits.
- **Cadence:** about 1/month.
- **Examples:** https://community.n8n.io/t/60070 · https://community.n8n.io/t/118962 · https://community.n8n.io/t/201703

**U04 · major-version launch**
- **Trigger:** a semver major (1.0, 2.0, 3.0 pending).
- **Channels:** forum "ready to be tested" / "coming soon" → docs breaking-changes page + migration guide/tool → release → blog "Introducing n8n X" → Product Hunt (1.0) → YouTube.
- **Assets:** breaking-changes doc; migration tool; blog hero image; PH listing.
- **Copy:** "a new milestone in our journey" → what's new → what breaks → how to migrate → thanks.
- **Gaps:** 5 days from test build to GA (1.0); 13 days from announcement to GA (2.0).
- **Examples:** https://blog.n8n.io/n8n-version-1/ · https://community.n8n.io/t/226475 · https://docs.n8n.io/changelog/v30-breaking-changes.md

**U05 · funding announcement**
- **Trigger:** a round closes.
- **Channels:** founder-signed blog post; press (a TechCrunch exclusive for seed and A; wide coverage for B and C); forum Announcements with banner; LinkedIn / X; investor posts; /press list; HN (organic).
- **Assets:** 1 banner (1920×1080 for Series B, 1920×1092 for Series C); team photo; founder letter.
- **Copy:** "We raised $X led by Y" → investor list → why now (market thesis) → growth metrics (multiples, users) → use of funds (product, community, hiring) → community promise + "we're hiring".
- **Cadence:** 157, 409, 1,429, 198 and 215 days between rounds.
- **Examples:** https://blog.n8n.io/series-a-announcement/ · https://blog.n8n.io/series-b/ · https://blog.n8n.io/series-c/

**U06 · star-milestone**
- **Trigger:** GitHub stars cross a round number (10k, 40k, 75k, 100k, 150k).
- **Channels:** forum; LinkedIn / X; live counter in site nav and home proof card.
- **Assets:** 1 celebratory 1920×1080 graphic.
- **Copy:** number + pun + thanks.
- **Cadence:** 1–6 months apart in 2025.
- **Examples:** https://community.n8n.io/t/43753 · https://community.n8n.io/t/122554 · https://community.n8n.io/t/208779

**U07 · anniversary / year-in-review**
- **Trigger:** June 23 (repo) or October 8 (Product Hunt "true birthday"), and year end.
- **Channels:** blog / Medium; forum; social hashtag (#n8nTurns5); community-awards livestream.
- **Assets:** 1920×1080 "5yrs" banner; 5–7 retrospective images (old UI screenshots, team photos, growth chart) at 1395×805.
- **Copy:** thanks → short dated history → numbers → team → what's next → "share your story".
- **Cadence:** yearly.
- **Examples:** https://blog.n8n.io/celebrating-n8n-second-anniversary/ · https://community.n8n.io/t/57000 · https://blog.n8n.io/2024-in-review/

**U08 · meetup → report**
- **Trigger:** an ambassador or local organizer hosts an event.
- **Channels:** Luma listing; forum event post; forum "<City> <Month> <Year> Meetup - Report 📸"; YouTube "Community Meetup Talks"; spin-off forum posts per talk; LinkedIn roundups.
- **Assets:** Luma page; 5–15 photos (est.); talk recordings.
- **Copy:** "Greetings from <City>!" / report → speakers → photos → recording links → next date.
- **Cadence:** about 2–8/month globally.
- **Examples:** https://community.n8n.io/t/50323 · https://community.n8n.io/t/56598 · https://luma.com/n8n-events

**U09 · community livestream / hangout**
- **Trigger:** a monthly slot.
- **Channels:** forum post titled "Community Hangout, <Day, Month D>: <Topic>"; YouTube Live → Livestreams playlist; "[recording available]" appended afterwards.
- **Assets:** 1 livestream of about 60 min (est.) + thumbnail.
- **Copy:** date + topic → guests → agenda → join link → recording.
- **Cadence:** about monthly (2024–25).
- **Examples:** https://community.n8n.io/t/49800 · https://community.n8n.io/t/73897

**U10 · contest / challenge**
- **Trigger:** a new capability to seed (LangChain 2023, agents 2025) or an engagement series.
- **Channels:** forum; YouTube workshop; partner hackathons.
- **Assets:** rules post, workshop video, winners post.
- **Copy:** "We're happy to announce the X Contest" → prizes → rules → deadline → winners.
- **Cadence:** several/year; weekly since 2026-09.
- **Examples:** https://community.n8n.io/t/31557 · https://community.n8n.io/t/184246 · https://community.n8n.io/t/311603

**U11 · workflow template (community listing)**
- **Trigger:** a creator submits a workflow and it passes review.
- **Channels:** /workflows/<id>-<slug>; /creators/<user>; in-app template gallery; "Popular ways to use…" on integration pages.
- **Assets:** workflow JSON + markdown description + node icons + creator avatar/bio/links.
- **Copy:** "How it works" → setup steps → requirements → customization.
- **Cadence:** about 600/month (est.).
- **Examples:** https://n8n.io/workflows/ · https://api.n8n.io/api/templates/workflows/2462 · https://n8n.io/creators/

**U12 · integration page (programmatic SEO)**
- **Trigger:** a node ships or updates.
- **Channels:** /integrations/<app>/; /integrations/<a>/and/<b>/; docs node + credential pages.
- **Assets:** logo + templated H1 + actions list + template list + 5 FAQs + 5 live forum threads.
- **Copy:** "Integrate <App> with 1000+ apps and services".
- **Cadence:** continuous (2,278 + ~47k pages).
- **Examples:** https://n8n.io/integrations/slack/ · https://n8n.io/integrations/gmail/and/google-sheets/

**U13 · tutorial / course video**
- **Trigger:** a feature, theme or partner.
- **Channels:** YouTube playlists (Beginner / Advanced course, Feature Spotlight, Office Hours, The Studio, 30 Day AI Sprint, "Building With <Partner>"); docs; blog.
- **Assets:** one 16:9 video of 5–30 min (e.g. 1,529 s) + thumbnail.
- **Copy:** "How to build X in n8n" / "Building With <Partner>: <use case>".
- **Cadence:** about 9/month (2026).
- **Examples:** https://www.youtube.com/watch?v=AbqPOLfLsm8 · https://www.youtube.com/watch?v=UdZOi8nOOyk

**U14 · SEO guide / series article**
- **Trigger:** keyword plan or thought-leadership series.
- **Channels:** blog (Guides, AI, ITOps, SecOps tags).
- **Assets:** 1,500–3,000 words (est.) + diagrams + template embeds.
- **Copy:** definition → patterns → how in n8n → template CTA.
- **Cadence:** about 12–15/month.
- **Examples:** https://blog.n8n.io/ai-agent-frameworks/ · https://blog.n8n.io/production-ai-playbook-introduction/

**U15 · comparison / report / benchmark**
- **Trigger:** a competitor or category keyword; annual research.
- **Channels:** /vs/<x> (21 pages); /reports/<year>-ai-agent-development-tools; /ai-benchmark/<model> (60); blog "best X".
- **Cadence:** report yearly; others ad hoc.
- **Examples:** https://n8n.io/vs/zapier/ · https://n8n.io/reports/2026-ai-agent-development-tools/ · https://n8n.io/ai-benchmark/

**U16 · case study**
- **Trigger:** a customer outcome.
- **Channels:** /case-studies/<slug> (34); home page block; YouTube ("The AI Employee That Saved 750 Hours"); blog "How we use n8n: <name>".
- **Copy:** "How <Company> <did X> and saved <number>" + named quote + role.
- **Examples:** https://n8n.io/case-studies/ · https://www.youtube.com/watch?v=MMBDzJde41Q

**U17 · flagship event cycle**
- **Trigger:** an owned event (n8n Fest, Builders Berlin, In The Loop).
- **Channels:** forum announcement → Luma or ticket page → micro-site → early-bird → teaser video → speaker posts on LinkedIn → community discount → event → photos / aftermovie → session recordings on YouTube.
- **Assets:** micro-site; 1 teaser of about 24 s; posters on pink grid; aftermovie; recordings.
- **Gaps:**
  - In The Loop: 27 days from early-bird to teaser, 8 more to discount, 21 more to the event.
  - Fest 2026: 51 days from announcement to event, 7 more to the aftermovie.
- **Examples:** https://n8n.io/intheloop/ · https://www.youtube.com/watch?v=sevVXhV0kec · https://community.n8n.io/t/304483

**U18 · program launch (community programs)**
- **Trigger:** a new program: Creator Hub, Affiliates, Ambassadors, Verified Creators, Expert partners.
- **Channels:** forum post, landing page or portal, LinkedIn "Meet our new Ambassadors".
- **Copy:** "Announcing the X Program!" → who it is for → what you get → how to apply.
- **Examples:** https://community.n8n.io/t/47996 · https://community.n8n.io/t/33281 · https://ambassadors.n8n.io/

**U19 · security advisory**
- **Trigger:** a vulnerability fix.
- **Channels:** forum Security Advisories; blog tag; GitHub advisory. HN picks up CVEs on its own.
- **Copy:** "Action required: … please upgrade" → affected versions → fixed version.
- **Examples:** https://community.n8n.io/t/914 · https://community.n8n.io/t/23431

---

## 7. The reveal sequence

**From nothing to launched (2018 → 2021).** Gaps are in days from the previous step.

| # | Step | What happened | Channels | Gap (days) |
|---|---|---|---|---|
| 0 | Founder pre-history | Jan launches small products on HN (link.fish 2017, Sheets add-on 2018). The audience habit exists before the product. | HN | — |
| 1 | Build privately + reserve names | Work starts about 2018-04; X @n8n_io 2018-11; GitHub org 2018-11-30. | X, GitHub | ~210 from start |
| 2 | Reserve the package name | `n8n@0.0.1` on npm (2019-04-24) | npm | 145 |
| 3 | Ask the crowd, anonymously | "Ask HN: what license…" (2019-04-25). Validates the strategy without revealing the product. | HN | 1 |
| 4 | Soft open-source reveal | npm 0.1.0 (06-21) → GitHub repo (06-22/23) → YouTube channel (06-27) | npm, GitHub, YouTube | 57 / 1 / 5 |
| 5 | Ship in public at high cadence | 18 minor releases in 10 weeks; docs written early ("the main reason why…" per the founder on HN); first outside PR (~Aug). | GitHub, npm, docs | continuous |
| 6 | Demo asset + community home | <3-min demo video (09-05); forum opens (09-07) | YouTube, forum | 70 / 2 |
| 7 | Launch day | UI "facelift" release (10-04/06). Then on 10-08: PH (#1, hunted by a famous hunter), HN front page (organic, 728 pts; founder answers every thread), site live with hero + demo + 3 benefits + 3 use cases + install paths + newsletter. | PH, HN, website, newsletter | 31 (108 from repo) |
| 8 | Proof after launch | 10k stars (Nov); company registered (11-27); YC Startup School grant (12-27); first job post (2020-02-17); contributor thank-you (02-27) | GitHub, forum | 50 / 30 / 52 / 10 |
| 9 | Funding reveal | Seed via TechCrunch exclusive; "fair code" framing | press, blog | 25 (157 from launch) |
| 10 | Content engine + ecosystem | dev.to tutorials and user interviews (May–Jun 2020), new docs (06-29), community tooling (Nodemaker 08-20) | dev.to, HN, docs, forum | 108 |
| 11 | Monetization launch | n8n.cloud Early Access on PH (2020-12-09) → 100th release (12-30) → cloud GA (Jan 2021) | PH, forum | 163 / 21 |
| 12 | Scale-up reveal | Series A (2021-04-26) + Discord (04-27) + monthly meetups (05-03) → 2nd-anniversary recap (06-23) | blog, press, Discord, forum | 117 / 1 / 6 / 51 |

**How the shape repeats for later launches.** Every big reveal since then follows a compressed version of the same shape:

```
teaser ("coming soon" / "ready to be tested" / beta call on the forum)
  → release inside the weekly train (docs release notes)
  → named reveal ("Introducing X": forum + blog + docs changelog)
  → video (demo, or a pitch for repositioning)
  → Product Hunt (for the biggest ones)
  → community activation (contest, workshop, livestream)
  → proof post (star milestone / "N templates published" / year in review)
```

Measured gaps:
- **1.0:** 5 days from test build to GA; PH on launch day.
- **LangChain / AI:** beta 2023-10-04 → contest 9 days → winners 33 days → GA 56 days after beta.
- **AI Workflow Builder:** "coming soon" 2025-09-29 → beta reveal 14 days → PH 1 day.
- **2.0:** "coming soon" 2025-11-25 → GA 13 days.
- **Chat Hub:** beta 2025-12-15 → blog "Introducing" 44 days.
- **n8n Assistant:** forum 2026-07-09 → blog 62 days.
- **n8n Agents:** forum 2026-08-05 → blog 51 days.
- **Repositioning after Series B:** funding 2025-03-25 → site redesign +1 day → pitch video "Flexible AI Workflow Automation for Technical Teams" +1 day. That is a 3-day "new chapter" burst.
- **Series C:** funding 2025-10-09 → AI Workflow Builder beta +4 days → PH +1 → 150k-stars post +7.
- **In The Loop:** early-bird → teaser 27 days → discount 8 days → event 21 days.

**Takeaways for the `startup-tail` blueprint:**
- In 2019 the reveal was **developer-first and asset-light**: one 3-minute demo, one landing page, one PH + HN day.
- The forum is the canonical dated log. Blog and press are for the big moments.
- Later launches reuse the same tail with the forum beta call in front. The blog "Introducing" post often comes weeks later, as consolidation rather than as the reveal.

---

## 8. Gaps (could not verify)

- **X/Twitter:** walled. Follower count (81.4K), join month (Nov 2018) and bio come only from search snippets. Posting cadence and the first tweet are unknown. The avatar and banner were not seen.
- **Instagram and Facebook:** counts (1,258 / 4,708) are from undated snippets and are probably stale. First-post dates are unknown. No official TikTok was found. Bluesky follower count is unknown.
- **Reddit r/n8n:** member count is from a third-party site (257k). Whether n8n owns or moderates it is unverified; the API was blocked.
- **Product Hunt:** only the 2019 launch has solid numbers (hunted.space). The 1.0 rank ("#154, 786 upvotes"), the desktop app (#30, 200) and AI Workflow Builder (#21, 690) come from search snippets only. The Product Hunt site itself was not fetched.
- **The June 2022 rebrand:** dated only by Wayback bracketing (06-09 → 06-15). No announcement or design rationale was found. The logo symbol was not viewed (no images downloaded). The node-graph and loop reading of the "8" is secondary-source.
- **Star milestones before 2023:** from n8n's own retrospective (5k about 5 months after publish; 10k by Nov 2019). The GitHub stargazer-timestamp API returned 404.
- **"162k GitHub stars" in blog posts:** 1.0, 2024 review, Series C and SAP all show 162k. That is the blog template's live star counter captured at fetch time, not a figure from those dates. It is ignored.
- **Earliest blog:** 2019–2020 Medium archive pages did not render. The first n8n blog post and its date are unknown. The Ghost sitemap has been pruned to 298 posts, oldest 2022.
- **YouTube:** the channel's oldest video list could not be enumerated. The 2019-09-05 demo is the earliest found, not proven to be the first. Upload dates for the 1.0 and 2.0 launch videos are unknown.
- **Other unknowns:**
  - newsletter subscriber count and archive
  - the podcast's producer (n8n or partner)
  - merch launch date
  - LinkedIn page creation date
  - the ambassador count in 2026
- **Funding details:** the SAP amount (>€60M) and ARR (>$40M) are from Wikipedia, not n8n. Series B valuation (~€250M) is secondary.
- **Website "since" dates:** for /features, /ai, /enterprise, /case-studies, /vs and the reports these are unknown (not in the sampled Wayback captures).

---

## Appendix

```yaml
# blueprint-input
company: n8n
observed_at: "2026-09-29"
channels:
  - {platform: website, handle: "n8n.io", url: "https://n8n.io/", since: "2019-10-08", followers: "GitHub counter 206,245; '200k+ community members'", bio: "AI agents and workflows you can see and control", cadence: "H1 repositioned about yearly"}
  - {platform: docs, handle: "docs.n8n.io", url: "https://docs.n8n.io", since: "2019-10 (new site 2020-06-29)", followers: null, bio: "Get set up on n8n, build your first workflow, and find inspiration for what to automate.", cadence: "weekly release notes; ~6 changelog stories/month"}
  - {platform: blog, handle: "blog.n8n.io", url: "https://blog.n8n.io", since: "2019 (Medium) / 2021 (Ghost)", followers: null, bio: null, cadence: "~17 posts/month (2026-09)"}
  - {platform: forum, handle: "community.n8n.io", url: "https://community.n8n.io", since: "2019-09-07", followers: "179,030 users", bio: "Join the n8n Community to connect with other users, learn from detailed discussions, and share your automation insights. Explore topics and get support.", cadence: "~25 new topics/day; Announcements ~3-8/month"}
  - {platform: templates, handle: "n8n.io/workflows", url: "https://n8n.io/workflows/", since: "2019-10", followers: "12,575 templates", bio: "Explore +10k workflow automation templates", cadence: "~600 new templates/month (est.)"}
  - {platform: integrations, handle: "n8n.io/integrations", url: "https://n8n.io/integrations/", since: "2019-10", followers: "2,278 pages + ~47k pair pages", bio: "Seamlessly move and transform data between different apps with n8n.", cadence: continuous}
  - {platform: github, handle: "n8n-io", url: "https://github.com/n8n-io/n8n", since: "2018-11-30 (org) / 2019-06-22 (repo)", followers: "206,249 stars; 60,929 forks; 15,016 org followers", bio: "Fair-code workflow automation platform with native AI capabilities. Combine visual building with custom code, self-host or cloud, 400+ integrations.", cadence: "24-49 releases/month; ~1 minor/week"}
  - {platform: youtube, handle: "@n8n-io", url: "https://www.youtube.com/@n8n-io", since: "2019-06-27", followers: "249K subscribers; 391 videos; 9.72M views", bio: "n8n gives technical teams a workflow automation platform that uniquely combines AI capabilities with business process automation. Connect any app or API while maintaining the flexibility of code with the speed of no-code.", cadence: "~9 videos/month"}
  - {platform: x, handle: "@n8n_io", url: "https://x.com/n8n_io", since: "2018-11 [snippet]", followers: "~81.4K [snippet, undated]", bio: "Workflow automation for technical teams to build AI solutions that integrate with any app or API at no-code speed and code flexibility. [snippet]", cadence: unknown}
  - {platform: linkedin, handle: "company/n8n", url: "https://www.linkedin.com/company/n8n/", since: unknown, followers: "431,469", bio: "Flexible AI workflow automation for technical teams.", cadence: "~60-120 posts/month (est.)"}
  - {platform: facebook, handle: "n8nio", url: "https://www.facebook.com/n8nio/", since: unknown, followers: "~4,708 [snippet, stale]", bio: "an extendable workflow automation tool which enables you to connect anything to everything via its open, fair-code model. [snippet]", cadence: low}
  - {platform: instagram, handle: "n8n.io", url: "https://www.instagram.com/n8n.io/", since: unknown, followers: "~1,258 [snippet, stale]", bio: "Extendable workflow automation tool which enables you to connect anything to everything via its open, fair-code model. [snippet]", cadence: low}
  - {platform: tiktok, handle: null, url: null, since: null, followers: null, bio: null, cadence: "none found"}
  - {platform: bluesky, handle: "@n8n-io.bsky.social", url: "https://bsky.app/profile/n8n-io.bsky.social", since: "2024-09-02", followers: unknown, bio: null, cadence: "mirrors X/LinkedIn"}
  - {platform: discord, handle: "discord.gg/n8n", url: "https://discord.gg/n8n", since: "2021-04-16", followers: "88,024 members", bio: "Join n8n's Discord for collaborative learning, expert insights, and innovative solutions in automation and integration", cadence: continuous}
  - {platform: reddit, handle: "r/n8n", url: "https://www.reddit.com/r/n8n/", since: unknown, followers: "~257k [secondary]", bio: "n8n is an extendable workflow automation tool... [snippet]", cadence: high}
  - {platform: producthunt, handle: "n8n-io", url: "https://www.producthunt.com/products/n8n-io", since: "2019-10-08", followers: "61 reviews, 5.0", bio: "Open source workflow automation tool (2019)", cadence: "~1 launch/year"}
  - {platform: hackernews, handle: "none (founder: janober)", url: "https://news.ycombinator.com/item?id=21191676", since: "2019-04-25", followers: null, bio: null, cadence: organic}
  - {platform: newsletter, handle: "Community News", url: "https://n8n.io/newsletter/", since: "2019-10", followers: unknown, bio: "Bart and Johannes prepare a monthly roundup of the latest community stories and product development insights.", cadence: monthly}
  - {platform: podcast, handle: "The n8n Masterclass", url: "https://www.youtube.com/playlist?list=PLlET0GsrLUL5FnLsRCh0BwmQTtv81dk6a", since: "2025", followers: "29 episodes [snippet]", bio: null, cadence: "~weekly"}
  - {platform: events, handle: "n8n Community Events", url: "https://luma.com/n8n-events", since: "2021-02 (meetups)", followers: unknown, bio: "contact community@n8n.io to list an event", cadence: "2-8 meetups/month; 1 flagship/year"}
  - {platform: merch, handle: "merch.n8n.io", url: "https://merch.n8n.io", since: "2026 (gated)", followers: null, bio: "We love that you're interested in our merch!", cadence: null}
identity:
  name: n8n
  handles: ["n8n.io", "n8n-io", "n8n_io", "n8nio", "n8n", "@n8n-io.bsky.social"]
  taglines:
    - {date: "2019-10-08", text: "Open Source Alternative for Zapier/tray.io"}
    - {date: "2020-04-15", text: "Free and Open Workflow Automation Tool"}
    - {date: "2021-04-15", text: "Extendable workflow automation"}
    - {date: "2022-06-02", text: "Automate without limits"}
    - {date: "2023-08-04", text: "Build complex automations 10x faster, without fighting APIs"}
    - {date: "2024-04-15", text: "Secure, AI-native workflow automation"}
    - {date: "2025-03-27", text: "Flexible AI workflow automation for technical teams"}
    - {date: "2026-09-29", text: "AI agents and workflows you can see and control"}
  short_description: "Fair-code workflow automation platform with native AI capabilities. Combine visual building with custom code, self-host or cloud, 400+ integrations."
  long_description: "n8n gives technical teams a workflow automation platform that uniquely combines AI capabilities with business process automation. Connect any app or API while maintaining the flexibility of code with the speed of no-code."
  terminology:
    - {term: workflow, meaning: "Collection of connected nodes that automates a process; starts on a trigger"}
    - {term: node, meaning: "One step: fetch, transform, logic, or app integration"}
    - {term: trigger node, meaning: "Node that starts a workflow (schedule, webhook, app event, chat, form)"}
    - {term: execution, meaning: "One run of a workflow; the billing unit"}
    - {term: credential, meaning: "Stored authentication for an app, reused by nodes"}
    - {term: expression, meaning: "JavaScript in {{ }} that sets parameters from earlier data"}
    - {term: canvas, meaning: "Visual editor surface where nodes are connected"}
    - {term: cluster node, meaning: "Root node plus sub-nodes (model, memory, tool); how AI agents are composed"}
    - {term: AI Agent, meaning: "LLM node that chooses tools; 'n8n Agents' are reusable agents (2026)"}
    - {term: template, meaning: "Pre-built importable workflow from n8n or the community"}
    - {term: community node, meaning: "Third-party npm node package; 'verified' ones run on Cloud"}
    - {term: data pinning, meaning: "Freezing a node's output during development"}
    - {term: error workflow, meaning: "Workflow that runs when another fails"}
    - {term: sub-workflow, meaning: "Workflow called from another workflow"}
    - {term: project, meaning: "Group of workflows, credentials, variables with roles"}
    - {term: data table, meaning: "Built-in persistent storage (2025)"}
    - {term: evaluation, meaning: "Testing AI workflows against datasets"}
    - {term: n8n Assistant, meaning: "In-product agent that builds workflows from a description"}
    - {term: MCP server/trigger, meaning: "Exposes workflows to AI apps via Model Context Protocol"}
    - {term: task runner, meaning: "Isolated process for Code node execution"}
    - {term: edition, meaning: "Community, Business or Enterprise variant of self-hosted n8n"}
    - {term: plan, meaning: "Starter, Pro, Business, Enterprise subscription tier"}
    - {term: fair-code, meaning: "n8n's source-available licensing model (Sustainable Use License since 2022-03)"}
    - {term: Gateway credits, meaning: "Pay-as-you-go access to AI models without provider accounts"}
    - {term: Verified Creator, meaning: "Badge for approved template authors"}
    - {term: Ambassador, meaning: "Community member who hosts local n8n events"}
    - {term: In The Loop, meaning: "n8n's first conference (Berlin, 2026-10-13/14)"}
  colors:
    - {name: "Pink (primary, logo)", hex: "#EA4B71"}
    - {name: "Dark / Brand Black", hex: "#040506"}
    - {name: White, hex: "#FFFFFF"}
    - {name: "Dark navy (site bg)", hex: "#1B1728"}
    - {name: "Midnight navy", hex: "#0E0918"}
    - {name: "Primary orange-red", hex: "#EE4F27"}
    - {name: "Secondary orange", hex: "#FF9B26"}
    - {name: "Button purple", hex: "#6B21EF"}
    - {name: "Accent blue", hex: "#077AC7"}
    - {name: "Green", hex: "#35A670"}
    - {name: "Legacy coral primary (2019-2022)", hex: "#FF6D5A"}
    - {name: "Legacy navy (2022-2025)", hex: "#101330"}
    - {name: "Legacy teal (2022-2025)", hex: "#20B69E"}
  typography: "Geomanist (site since 2025-03-26); custom 'n8n Baumer' + 'n8n Baumer Mono' variable fonts in the 2026 brand-system preview; earlier sunset-gothic + moderat (2022-25) and Open Sans (2019-22)"
  theme: "dark-first website since 2025-03-26 (navy/black + pink); light micro-sites for events; brand system = black, white, grey, pink with dot grid"
  logo: "Horizontal lockup: node-graph symbol + lowercase 'n8n' wordmark; only Pink #EA4B71, Dark #040506 or White; 4X clear space; min 100 px / 30 mm; never wordmark alone, never vertical; recolored coral->pink 2022-06-10..15; app icon = pink symbol on black"
  illustration: "Real product-canvas screenshots as heroes, integration logo grids, Phosphor line icons, dot-grid and pixel-grid graphic devices, event posters on pink grid, team and event photography; motion = 24 s teasers, ~3 min pitch videos, 5-30 min tutorials, aftermovies"
  voice: "Builder-to-builder, technical, direct, lightly punny ('feeling pretty triggered', 'Builders don't w8'), control/transparency emphasis, anti-hype, community-first, founder-signed for big moments"
content:
  sections:
    - {id: about, title: "About (press + careers)", structure: "No /about page. /press: boilerplate, name story, brand assets, press kit, press email. /careers: Why n8n (product, community, people, potential) -> founder note -> Culture/Code (Builders, Welcoming, Right thing, Early, Multipliers) -> Who thrives -> Your impact -> Roles -> Life at n8n"}
    - {id: home, title: "Home page", structure: "nav -> hero H1 + sub + 2 CTAs -> logo wall -> role tabs + pitch video -> 3 proof cards (GitHub stars, G2, community) -> integrations -> AI agents (3 blocks) -> code+UI -> 'Move fast. Break nothing.' -> case studies -> enterprise (4 cards) -> testimonial wall -> final CTA -> footer (4 groups, 5 socials)"}
    - {id: docs, title: "Docs & tutorials", structure: "Get started / Deploy (Cloud, self-host) / Build / Integrations (node + credential page per app) / Advanced AI / API / Embed / Changelog; glossary; learning paths; .md + llms.txt exports; YouTube Beginner + Advanced courses"}
    - {id: templates, title: "Templates library", structure: "count headline -> category filters (AI, Sales, IT Ops, Marketing, Document Ops, Support, Other) -> popular integrations -> verified creators -> template pages (/workflows/<id>-<slug>)"}
    - {id: integrations, title: "Integration page", structure: "see app_store_listing"}
    - {id: blog, title: "Blog", structure: "types: Introducing/Announcing, funding letters, anniversaries/year-in-review, SEO guides and listicles, series (Production AI Playbook), tutorials, partner posts, research, security advisories, 'How we use n8n'"}
    - {id: newsletter, title: "Community News", structure: "monthly email by community team: meet-up announcements, product updates, featured workflows"}
    - {id: press, title: "Press", structure: "articles list -> About n8n boilerplate -> name guideline -> brand guidelines + press kit links -> press email"}
    - {id: release_notes, title: "Release notes entry", structure: "'## n8n X.Y <top feature>, plus N other features' -> '**Released:** YYYY-MM-DD' -> one bullet per feature: '[<Node>: <imperative>](PR link): 2-5 sentence explanation'; plus GitHub conventional-commit release and curated Changelog story"}
    - {id: vision, title: "Vision / manifesto", structure: "fair-code + self-hosted control (2019-22) -> 'AI, code, and humans' (2025) -> 'default orchestration layer between AI models and business systems' (careers) -> brand system: 'A brand built by doing, by shipping, by listening, and by making things work.'"}
    - {id: events, title: "Events", structure: "Luma calendar of ambassador meetups/workshops/hackathons + owned flagships (n8n Fest, Builders Berlin, In The Loop) with micro-site, agenda, speakers, FAQ, tickets"}
app_store_listing:
  fields:
    - {name: page_title, type: string, example: "Slack integrations | Workflow automation with n8n"}
    - {name: meta_description, type: string, example: "Integrate Slack with hundreds of other apps. Create sophisticated automations between Slack and your stack using n8n. Free and source-available."}
    - {name: og_image, type: image_url, example: "https://n8n.io/n8n-og-image.png"}
    - {name: slug, type: string, example: "slack"}
    - {name: logo, type: image, example: "Slack logo"}
    - {name: h1, type: string, example: "Integrate Slack with 1000+ apps and services"}
    - {name: intro, type: text, example: "Unlock Slack's full potential with n8n, connecting it to similar Communication apps and over 1000 other services..."}
    - {name: ctas, type: "list[link]", example: "Get Started; See n8n in action (YouTube)"}
    - {name: partner_apps, type: "list[app ref]", example: "Google Sheets, Postgres, MySQL, Airtable, Gmail... (sortable by popularity; each links to /integrations/slack/and/<app>/)"}
    - {name: docs_links, type: "list[url]", example: "Slack Node Docs + Examples; Slack Credential Docs"}
    - {name: popular_templates, type: "list[template ref]", example: "Back up your n8n workflows to Github; AI Personal Assistant; ... (paged, 'Load more')"}
    - {name: supported_actions, type: "map[resource -> list[{operation, description}]]", example: "Channel: Archive - 'Archives a conversation'; Message: Send, Send and Wait for Response, Update..."}
    - {name: about_app, type: text, example: "Slack is a powerful collaboration tool for businesses of all sizes..."}
    - {name: related_categories, type: "list[string]", example: "Communication; HITL"}
    - {name: similar_integrations, type: "list[app ref]", example: "Gmail, Telegram, Discord, Mautic, Pushover, SendGrid, ClickUp, Twilio"}
    - {name: tutorials, type: "list[{tag, title, excerpt, url}]", example: "Bot/Tutorial - How to make a Slack bot: Python vs low-code"}
    - {name: sales_cta, type: link, example: "Contact Sales"}
    - {name: faq, type: "list[{question, answer}]", example: "How can I set up Slack integration in n8n? ... (5 templated Q&As)"}
    - {name: community_threads, type: "list[{title, date, author, excerpt, url}]", example: "Slack node token rotation issue - March 16, 2026 - Sergiy B."}
    - {name: template_record, type: object, example: "{id: 2462, name, totalViews: 421033, createdAt: 2024-10-14, description (markdown), workflow JSON, workflowInfo.nodeCount: 15, status: published, user {name, username, bio, verified, links, avatar}, nodes[], categories[], image[]}"}
timeline:
  - {date: "2018-02-28", stage: pre-history, channels: [hackernews], media: post, title: "Founder launches Google Sheets scraping add-on (after link.fish 2017)", url: "https://hn.algolia.com/api/v1/search?tags=comment,author_janober"}
  - {date: "2018-04", stage: pre-launch, channels: [], media: none, title: "Work on n8n starts", url: "https://community.n8n.io/t/57000"}
  - {date: "2018-09", stage: pre-launch, channels: [forum], media: image, title: "Pre-release UI screenshots (Sep 2018, May 2019), shown retrospectively", url: "https://community.n8n.io/t/57000"}
  - {date: "2018-11", stage: pre-launch, channels: [x], media: account, title: "@n8n_io joins X", url: "https://x.com/n8n_io"}
  - {date: "2018-11-30", stage: pre-launch, channels: [github], media: org, title: "GitHub org n8n-io created", url: "https://github.com/n8n-io"}
  - {date: "2019-04-24", stage: pre-launch, channels: [npm], media: package, title: "n8n@0.0.1 published (name reserved)", url: "https://www.npmjs.com/package/n8n"}
  - {date: "2019-04-25", stage: pre-launch, channels: [hackernews], media: post, title: "Ask HN: What License for New 'Open Source' Project? Commons Clause?", url: "https://news.ycombinator.com/item?id=19748652"}
  - {date: "2019-06-21", stage: reveal, channels: [npm], media: release, title: "n8n@0.1.0 first usable release", url: "https://www.npmjs.com/package/n8n?activeTab=versions"}
  - {date: "2019-06-22", stage: reveal, channels: [github], media: repo, title: "n8n-io/n8n repository published", url: "https://github.com/n8n-io/n8n"}
  - {date: "2019-06-27", stage: reveal, channels: [youtube], media: channel, title: "YouTube channel created", url: "https://www.youtube.com/@n8n-io/about"}
  - {date: "2019-07-11", stage: release, channels: [github, npm], media: release, title: "0.4.0 -> 0.21.0: 18 minor releases in 10 weeks", url: "https://www.npmjs.com/package/n8n?activeTab=versions"}
  - {date: "2019-08", stage: community, channels: [github], media: pull-request, title: "First pull request from a user", url: "https://blog.n8n.io/celebrating-n8n-second-anniversary/"}
  - {date: "2019-09-05", stage: pre-launch, channels: [youtube], media: video, title: "n8n.io - Slack Notification on Github Star (<3 min demo)", url: "https://www.youtube.com/watch?v=3w7xIMKLVAg"}
  - {date: "2019-09-07", stage: community, channels: [forum], media: forum, title: "community.n8n.io opens", url: "https://community.n8n.io/t/20"}
  - {date: "2019-10-04", stage: release, channels: [npm], media: release, title: "0.22.0/0.23.0 pre-launch facelift", url: "https://www.npmjs.com/package/n8n"}
  - {date: "2019-10-08", stage: launch, channels: [producthunt], media: post, title: "n8n - Open source workflow automation tool (#1 Product of the Day)", url: "https://www.producthunt.com/products/n8n-io"}
  - {date: "2019-10-08", stage: launch, channels: [hackernews], media: post, title: "N8n.io - Workflow automation alternative to Zapier (728 pts)", url: "https://news.ycombinator.com/item?id=21191676"}
  - {date: "2019-10-08", stage: launch, channels: [website, newsletter], media: page, title: "Open Source Alternative for Zapier/tray.io", url: "https://web.archive.org/web/20191008134525/https://n8n.io/"}
  - {date: "2019-11", stage: milestone, channels: [github], media: stars, title: "10,000 GitHub stars (5k about five months after publishing)", url: "https://blog.n8n.io/celebrating-n8n-second-anniversary/"}
  - {date: "2019-11-27", stage: milestone, channels: [], media: registry, title: "n8n GmbH registered in Berlin", url: "https://en.wikipedia.org/wiki/N8n"}
  - {date: "2019-12-27", stage: milestone, channels: [forum], media: post, title: "n8n is one of the YC Startup School 2019 Grant Winners", url: "https://community.n8n.io/t/582"}
  - {date: "2020-02-17", stage: hiring, channels: [forum], media: post, title: "Job: Come and join n8n!", url: "https://community.n8n.io/t/844"}
  - {date: "2020-02-27", stage: community, channels: [forum], media: post, title: "Thank you RicardoE105 for 50+ integrations created!", url: "https://community.n8n.io/t/902"}
  - {date: "2020-03-01", stage: release, channels: [forum], media: post, title: "Please update n8n@0.55.0 to fix security issue!", url: "https://community.n8n.io/t/914"}
  - {date: "2020-03-13", stage: funding, channels: [press, blog], media: article, title: "Seed $1.5M led by Sequoia and firstminute", url: "https://techcrunch.com/2020/03/13/n8n-a-fair-code-workflow-automation-platform-raises-seed-from-sequoia-as-vc-firm-steps-up-in-europe"}
  - {date: "2020-04", stage: hiring, channels: [], media: none, title: "First team members join", url: "https://community.n8n.io/t/57000"}
  - {date: "2020-04-15", stage: rebrand, channels: [website], media: page, title: "H1 'Free and Open Workflow Automation Tool - fair-code licensed'", url: "https://web.archive.org/web/20200415000000*/n8n.io"}
  - {date: "2020-05-08", stage: community, channels: [devto, hackernews], media: article, title: "Tutorial + user-interview series on dev.to", url: "https://dev.to/n8n"}
  - {date: "2020-06-29", stage: release, channels: [forum, docs], media: post, title: "New docs for n8n", url: "https://community.n8n.io/t/1666"}
  - {date: "2020-08-20", stage: community, channels: [forum, hackernews], media: post, title: "Nodemaker launch", url: "https://community.n8n.io/t/2097"}
  - {date: "2020-12-09", stage: launch, channels: [producthunt, forum], media: post, title: "n8n.cloud Early Access launch on Product Hunt", url: "https://community.n8n.io/t/3322"}
  - {date: "2020-12-30", stage: milestone, channels: [github, npm], media: release, title: "100th release (0.100.0)", url: "https://blog.n8n.io/celebrating-n8n-second-anniversary/"}
  - {date: "2021-01-04", stage: community, channels: [hackernews], media: post, title: "Fair-Code Automation with n8n.io (132 pts)", url: "https://news.ycombinator.com/item?id=25632892"}
  - {date: "2021-02-01", stage: event, channels: [forum], media: post, title: "Let's catch-up in an n8n meet-up!", url: "https://community.n8n.io/t/4121"}
  - {date: "2021-04-26", stage: funding, channels: [blog, press, forum, hackernews], media: article, title: "Announcing our $12m Series A funding", url: "https://blog.n8n.io/series-a-announcement/"}
  - {date: "2021-04-27", stage: community, channels: [discord, forum], media: post, title: "The n8n community is now on Discord!", url: "https://community.n8n.io/t/5473"}
  - {date: "2021-05-03", stage: event, channels: [forum, youtube], media: livestream, title: "Monthly community meetups begin", url: "https://community.n8n.io/t/5579"}
  - {date: "2021-05-21", stage: launch, channels: [producthunt], media: post, title: "Notion n8n Integration is on Product Hunt", url: "https://community.n8n.io/t/5890"}
  - {date: "2021-06-23", stage: milestone, channels: [blog], media: article, title: "Celebrating n8n's second anniversary", url: "https://blog.n8n.io/celebrating-n8n-second-anniversary/"}
  - {date: "2021-11-04", stage: launch, channels: [producthunt], media: post, title: "n8n desktop app is live on Product Hunt", url: "https://community.n8n.io/t/8883"}
  - {date: "2022-03-17", stage: pivot, channels: [forum, blog], media: article, title: "Announcing the new Sustainable Use License (heads-up 2022-03-03)", url: "https://blog.n8n.io/announcing-new-sustainable-use-license/"}
  - {date: "2022-03-15", stage: release, channels: [blog, forum], media: article, title: "User Management MVP", url: "https://blog.n8n.io/announcing-user-management/"}
  - {date: "2022-06-12", stage: rebrand, channels: [website], media: page, title: "New website + pink logo (#FF6D5A -> #EA4B71); 'Automate without limits' (Wayback window 06-10..15)", url: "https://web.archive.org/web/20220615051024/https://n8n.io/"}
  - {date: "2022-08-11", stage: launch, channels: [producthunt], media: post, title: "Community node repository launch on Product Hunt", url: "https://community.n8n.io/t/16587"}
  - {date: "2022-12-12", stage: release, channels: [forum], media: post, title: "Paid self-hosted features coming soon", url: "https://community.n8n.io/t/20716"}
  - {date: "2022-12-31", stage: milestone, channels: [forum], media: post, title: "2022 in Review", url: "https://community.n8n.io/t/21320"}
  - {date: "2023-05-17", stage: release, channels: [forum], media: post, title: "Python Support and Release Versions", url: "https://community.n8n.io/t/26291"}
  - {date: "2023-07-19", stage: pre-launch, channels: [forum], media: post, title: "n8n version 1 ready to be tested", url: "https://community.n8n.io/t/28328"}
  - {date: "2023-07-24", stage: launch, channels: [blog, forum, producthunt], media: article, title: "n8n Version 1.0 - A new milestone in our journey", url: "https://blog.n8n.io/n8n-version-1/"}
  - {date: "2023-08-04", stage: rebrand, channels: [website], media: page, title: "H1 'Build complex automations 10x faster, without fighting APIs'", url: "https://web.archive.org/web/20230804082546/https://n8n.io/"}
  - {date: "2023-10-04", stage: launch, channels: [docs, hackernews, forum, youtube], media: post, title: "LangChain in n8n (beta) + community workshop", url: "https://news.ycombinator.com/item?id=37765778"}
  - {date: "2023-10-13", stage: community, channels: [forum], media: post, title: "AI LangChain Contest (winners 2023-11-15)", url: "https://community.n8n.io/t/31557"}
  - {date: "2023-11-22", stage: community, channels: [forum], media: post, title: "The Creator Hub is here!", url: "https://community.n8n.io/t/33281"}
  - {date: "2023-11-28", stage: community, channels: [forum], media: post, title: "Are you an Affiliate yet?", url: "https://community.n8n.io/t/33519"}
  - {date: "2023-11-29", stage: release, channels: [docs], media: release, title: "LangChain general availability (1.19.0)", url: "https://docs.n8n.io/changelog/release-notes-1.x.md"}
  - {date: "2024-04-04", stage: milestone, channels: [forum], media: post, title: "We just reached 40k stars on Github!", url: "https://community.n8n.io/t/43753"}
  - {date: "2024-04-15", stage: rebrand, channels: [website], media: page, title: "H1 'Secure, AI-native workflow automation'", url: "https://web.archive.org/web/20240415000000*/n8n.io"}
  - {date: "2024-06-06", stage: community, channels: [forum], media: post, title: "Announcing the n8n Ambassador Program!", url: "https://community.n8n.io/t/47996"}
  - {date: "2024-08-21", stage: launch, channels: [blog, forum, github], media: article, title: "Self-hosted AI Starter Kit", url: "https://blog.n8n.io/self-hosted-ai/"}
  - {date: "2024-09-02", stage: community, channels: [bluesky, forum], media: post, title: "New social media account: Bluesky", url: "https://community.n8n.io/t/53126"}
  - {date: "2024-10-08", stage: milestone, channels: [forum, x, linkedin], media: post, title: "We're celebrating - n8n turns five! (#n8nTurns5)", url: "https://community.n8n.io/t/57000"}
  - {date: "2024-10-29", stage: pre-launch, channels: [forum], media: post, title: "Help Us Test the New n8n Canvas (Beta)", url: "https://community.n8n.io/t/60070"}
  - {date: "2025-01-21", stage: milestone, channels: [blog], media: article, title: "n8n's 2024 in Review", url: "https://blog.n8n.io/2024-in-review/"}
  - {date: "2025-03-25", stage: funding, channels: [blog, forum, press], media: article, title: "n8n closes EUR 55M Series B round led by Highland Europe", url: "https://blog.n8n.io/series-b/"}
  - {date: "2025-03-26", stage: rebrand, channels: [website, forum], media: post, title: "New fonts. New vibes. Same automation magic", url: "https://community.n8n.io/t/92983"}
  - {date: "2025-03-27", stage: reveal, channels: [youtube, website], media: video, title: "n8n: Flexible AI Workflow Automation for Technical Teams [2025] (174 s)", url: "https://www.youtube.com/watch?v=ZCuL2e4zC_4"}
  - {date: "2025-04-10", stage: release, channels: [forum], media: post, title: "MCP Client tool & MCP Trigger nodes", url: "https://community.n8n.io/t/99338"}
  - {date: "2025-05-28", stage: milestone, channels: [forum], media: image, title: "100k stars on GitHub!", url: "https://community.n8n.io/t/122554"}
  - {date: "2025-06-06", stage: release, channels: [blog], media: article, title: "Introducing Evaluations for AI workflows", url: "https://blog.n8n.io/introducing-evaluations-for-ai-workflows/"}
  - {date: "2025-07-09", stage: event, channels: [forum], media: event, title: "First n8n Fest, Berlin (invite-only)", url: "https://community.n8n.io/t/137261"}
  - {date: "2025-08-07", stage: release, channels: [blog, forum, youtube], media: article, title: "New plan, no active workflow limits (pricing)", url: "https://blog.n8n.io/build-without-limits-everything-you-need-to-know-about-n8ns-new-pricing/"}
  - {date: "2025-09-22", stage: release, channels: [forum], media: post, title: "Data Tables Are Here!", url: "https://community.n8n.io/t/192256"}
  - {date: "2025-09-29", stage: pre-launch, channels: [forum], media: post, title: "AI-powered workflow-building coming soon", url: "https://community.n8n.io/t/196499"}
  - {date: "2025-10-09", stage: funding, channels: [blog, forum, hackernews, press], media: article, title: "n8n raises $180m (Series C, $2.5B, Accel)", url: "https://blog.n8n.io/series-c/"}
  - {date: "2025-10-13", stage: launch, channels: [forum, producthunt], media: post, title: "Introducing AI Workflow Builder (Beta)", url: "https://community.n8n.io/t/204919"}
  - {date: "2025-10-20", stage: milestone, channels: [forum], media: post, title: "150,000 stars on GitHub", url: "https://community.n8n.io/t/208779"}
  - {date: "2025-11-25", stage: pre-launch, channels: [forum], media: post, title: "Announcing n8n version 2.0 - coming soon!", url: "https://community.n8n.io/t/226475"}
  - {date: "2025-12-08", stage: launch, channels: [blog, npm], media: article, title: "Introducing n8n 2.0", url: "https://blog.n8n.io/introducing-n8n-2-0/"}
  - {date: "2025-12-15", stage: launch, channels: [forum, blog], media: post, title: "Chat Hub beta (blog 'Introducing Chat Hub' 2026-01-28)", url: "https://blog.n8n.io/introducing-chat-hub/"}
  - {date: "2026-05-12", stage: funding, channels: [blog], media: article, title: "Announcing SAP's strategic investment in n8n + SAP partnership", url: "https://blog.n8n.io/n8n-sap/"}
  - {date: "2026-07-09", stage: launch, channels: [forum, blog], media: post, title: "Introducing the AI Assistant (blog 'Introducing n8n Assistant' 2026-09-09)", url: "https://community.n8n.io/t/302667"}
  - {date: "2026-07-16", stage: event, channels: [forum, youtube], media: event, title: "n8n Fest 2026 (aftermovie 2026-07-23)", url: "https://community.n8n.io/t/304483"}
  - {date: "2026-08-05", stage: launch, channels: [forum, blog], media: post, title: "Introducing n8n Agents (blog 2026-09-25)", url: "https://blog.n8n.io/introducing-n8n-agents/"}
  - {date: "2026-08-19", stage: event, channels: [forum, website], media: post, title: "In The Loop: early-bird tickets", url: "https://community.n8n.io/t/308390"}
  - {date: "2026-09-07", stage: community, channels: [forum], media: post, title: "Community Weekly Challenge starts", url: "https://community.n8n.io/t/311603"}
  - {date: "2026-09-15", stage: pre-launch, channels: [youtube], media: video, title: "Node Runner Reveal (n8n In the Loop 2026), 24 s teaser", url: "https://www.youtube.com/watch?v=sevVXhV0kec"}
  - {date: "2026-09-29", stage: rebrand, channels: [website], media: page, title: "n8n Brand System sneak peek (first observed)", url: "https://guidelines.n8n.design/"}
  - {date: "2026-10-13", stage: event, channels: [website, linkedin], media: event, title: "In The Loop 2026 conference, Berlin (13-14 Oct)", url: "https://n8n.io/intheloop/"}
units:
  - id: U01
    name: weekly-release-train
    trigger: "weekly minor release (beta -> stable a week later); daily patches"
    channels: [github, npm, docker, docs, rss]
    assets:
      - {kind: changelog, spec: "auto-generated conventional-commit GitHub release", count: 1}
      - {kind: docs-entry, spec: "'n8n X.Y <top feature>, plus N other features' + one bullet per PR", count: 1}
    copy: "headline feature + count -> per bullet '<Node>: <imperative>' -> what changed -> defaults/compat"
    cadence: "~4 minors/month; 24-49 npm versions/month (2026)"
  - id: U02
    name: feature-story
    trigger: "notable feature reaches users"
    channels: [docs, forum, blog, youtube, linkedin, x]
    assets:
      - {kind: screenshot-or-gif, spec: "product UI, forum inline", count: 1}
      - {kind: changelog-story, spec: "3-5 paragraphs", count: 1}
      - {kind: video, spec: "16:9 demo 2-10 min (est.)", count: 1}
      - {kind: social-card, spec: "brand card (size unknown)", count: 1}
    copy: "benefit headline -> problem before -> what it does -> how to enable -> availability by plan/version -> docs link -> feedback ask"
    cadence: "changelog ~6/month; blog 'Introducing' ~1-2/month"
  - id: U03
    name: beta-call
    trigger: "feature ready for community testing"
    channels: [forum]
    assets:
      - {kind: forum-post, spec: "screenshot + enable steps + feedback questions", count: 1}
    copy: "'Help us test X (Beta)' -> what -> how to enable -> feedback wanted -> known limits"
    cadence: "~1/month"
  - id: U04
    name: major-version-launch
    trigger: "semver major (1.0, 2.0, 3.0 pending)"
    channels: [forum, docs, blog, producthunt, youtube]
    assets:
      - {kind: breaking-changes-doc, spec: "docs page + migration guide/tool", count: 1}
      - {kind: blog-post, spec: "hero image + sections", count: 1}
      - {kind: producthunt-listing, spec: "launch post", count: 1}
    copy: "'ready to be tested'/'coming soon' -> 'a new milestone in our journey' -> what's new -> what breaks -> how to migrate -> thanks"
    cadence: "~every 2.5 years; 5-13 days from announcement to GA"
  - id: U05
    name: funding-announcement
    trigger: "round closes"
    channels: [blog, press, forum, linkedin, x, hackernews]
    assets:
      - {kind: banner, spec: "1920x1080 (Series B) / 1920x1092 (Series C)", count: 1}
      - {kind: founder-letter, spec: "blog post signed by the CEO", count: 1}
      - {kind: team-photo, spec: "group photo", count: 1}
    copy: "'We raised $X led by Y' -> investor list -> why now (thesis) -> growth metrics -> use of funds -> community promise + hiring"
    cadence: "2020-03, 2021-04, 2025-03, 2025-10, 2026-05"
  - id: U06
    name: star-milestone
    trigger: "GitHub stars cross a round number"
    channels: [forum, linkedin, x, website]
    assets:
      - {kind: graphic, spec: "1920x1080 celebration card", count: 1}
    copy: "number + pun + thanks"
    cadence: "every 1-6 months in 2025"
  - id: U07
    name: anniversary-year-in-review
    trigger: "June 23 / October 8 anniversary; year end"
    channels: [blog, forum, x, linkedin, youtube]
    assets:
      - {kind: banner, spec: "1920x1080", count: 1}
      - {kind: retrospective-images, spec: "1395x805 old UI screenshots, team photos, chart", count: 6}
    copy: "thanks -> dated short history -> numbers -> team -> what's next -> share your story (hashtag)"
    cadence: yearly
  - id: U08
    name: meetup-report
    trigger: "ambassador/local meetup happens"
    channels: [luma, forum, youtube, linkedin]
    assets:
      - {kind: event-page, spec: "Luma listing", count: 1}
      - {kind: photos, spec: "event photos (est. 5-15)", count: 10}
      - {kind: talk-recordings, spec: "16:9 talks", count: 2}
    copy: "'<City> <Month> <Year> Meetup - Report' -> speakers -> photos -> recordings -> next date"
    cadence: "2-8/month globally"
  - id: U09
    name: community-livestream
    trigger: "monthly slot"
    channels: [forum, youtube]
    assets:
      - {kind: livestream, spec: "YouTube Live ~60 min (est.) + thumbnail", count: 1}
    copy: "'Community Hangout, <date>: <topic>' -> guests -> agenda -> link -> '[recording available]'"
    cadence: monthly
  - id: U10
    name: contest-challenge
    trigger: "new capability to seed, or engagement series"
    channels: [forum, youtube]
    assets:
      - {kind: rules-post, spec: "forum post", count: 1}
      - {kind: workshop-video, spec: "16:9 recording", count: 1}
      - {kind: winners-post, spec: "forum post", count: 1}
    copy: "announce -> prizes -> rules -> deadline -> winners"
    cadence: "several/year; weekly since 2026-09"
  - id: U11
    name: workflow-template
    trigger: "creator submits a workflow, passes review"
    channels: [website, in-app]
    assets:
      - {kind: workflow-json, spec: "nodes + connections", count: 1}
      - {kind: description, spec: "markdown: How it works -> Setup -> Requirements", count: 1}
    copy: "'How it works' -> setup steps -> requirements -> customization"
    cadence: "~600/month (est.)"
  - id: U12
    name: integration-page
    trigger: "node ships or updates"
    channels: [website, docs]
    assets:
      - {kind: page, spec: "templated page (see app_store_listing)", count: 1}
      - {kind: pair-pages, spec: "/integrations/<a>/and/<b>/", count: 500}
    copy: "'Integrate <App> with 1000+ apps and services' -> actions -> templates -> FAQ"
    cadence: continuous
  - id: U13
    name: tutorial-video
    trigger: "feature, theme or partner"
    channels: [youtube, docs, blog]
    assets:
      - {kind: video, spec: "16:9, 5-30 min + thumbnail", count: 1}
    copy: "'How to build X in n8n' / 'Building With <Partner>: <use case>'"
    cadence: "~9/month"
  - id: U14
    name: seo-guide
    trigger: "keyword plan / series"
    channels: [blog]
    assets:
      - {kind: article, spec: "1,500-3,000 words (est.) + diagrams + template embeds", count: 1}
    copy: "definition -> patterns -> how in n8n -> template CTA"
    cadence: "~12-15/month"
  - id: U15
    name: comparison-report-benchmark
    trigger: "competitor/category keyword; annual research"
    channels: [website, blog]
    assets:
      - {kind: page, spec: "/vs/<x>, /reports/<year>-..., /ai-benchmark/<model>", count: 1}
    copy: "claim -> side-by-side -> proof -> CTA"
    cadence: "report yearly; others ad hoc"
  - id: U16
    name: case-study
    trigger: "customer outcome"
    channels: [website, youtube, blog]
    assets:
      - {kind: page, spec: "/case-studies/<slug> with quote + metric", count: 1}
    copy: "'How <Company> <did X> and saved <number>' + named quote"
    cadence: "ad hoc (34 live)"
  - id: U17
    name: flagship-event-cycle
    trigger: "owned event (n8n Fest, Builders Berlin, In The Loop)"
    channels: [forum, website, luma, youtube, linkedin]
    assets:
      - {kind: micro-site, spec: "home/agenda/speakers/FAQ/tickets", count: 1}
      - {kind: teaser-video, spec: "~24 s", count: 1}
      - {kind: aftermovie-and-recordings, spec: "16:9", count: 3}
    copy: "announce -> early-bird -> teaser -> speakers -> community discount -> event -> photos/aftermovie -> recordings"
    cadence: "1 flagship/year (+ Fest)"
  - id: U18
    name: program-launch
    trigger: "new community program (creators, affiliates, ambassadors, experts)"
    channels: [forum, website, linkedin]
    assets:
      - {kind: forum-post, spec: "announcement + landing page link", count: 1}
    copy: "'Announcing the X Program!' -> who it's for -> benefits -> how to apply"
    cadence: "~1/year"
  - id: U19
    name: security-advisory
    trigger: "vulnerability fixed"
    channels: [forum, blog, github]
    assets:
      - {kind: advisory, spec: "forum post + GitHub advisory", count: 1}
    copy: "'Action required' -> affected versions -> fixed version -> upgrade steps"
    cadence: "ad hoc"
reveal_sequence:
  - {step: 0, what: "Founder launches small tools on HN (link.fish 2017, Sheets add-on 2018): audience habit before product", channels: [hackernews], gap_days_from_previous: null}
  - {step: 1, what: "Build privately (from ~2018-04); reserve X @n8n_io (2018-11) and GitHub org (2018-11-30)", channels: [x, github], gap_days_from_previous: 210}
  - {step: 2, what: "Reserve npm package name n8n@0.0.1 (2019-04-24)", channels: [npm], gap_days_from_previous: 145}
  - {step: 3, what: "Anonymous 'Ask HN' on license strategy (2019-04-25)", channels: [hackernews], gap_days_from_previous: 1}
  - {step: 4, what: "Soft open-source reveal: npm 0.1.0 (06-21), GitHub repo (06-22), YouTube channel (06-27)", channels: [npm, github, youtube], gap_days_from_previous: 57}
  - {step: 5, what: "Ship in public: 18 minor releases in 10 weeks; docs early; first outside PR", channels: [github, npm, docs], gap_days_from_previous: 14}
  - {step: 6, what: "Demo video (<3 min, 2019-09-05) + community forum (2019-09-07)", channels: [youtube, forum], gap_days_from_previous: 70}
  - {step: 7, what: "Launch day 2019-10-08: Product Hunt #1 + HN front page + landing page w/ demo + newsletter", channels: [producthunt, hackernews, website, newsletter], gap_days_from_previous: 31}
  - {step: 8, what: "Post-launch proof: 10k stars, GmbH (11-27), YC Startup School grant (12-27), first job post (2020-02-17)", channels: [github, forum], gap_days_from_previous: 50}
  - {step: 9, what: "Seed reveal via TechCrunch (2020-03-13), 'fair code' framing", channels: [press, blog], gap_days_from_previous: 25}
  - {step: 10, what: "Content engine + ecosystem: dev.to tutorials/interviews, new docs (2020-06-29), Nodemaker", channels: [devto, docs, forum], gap_days_from_previous: 108}
  - {step: 11, what: "Monetization launch: n8n.cloud Early Access on Product Hunt (2020-12-09); 100th release (12-30)", channels: [producthunt, forum], gap_days_from_previous: 163}
  - {step: 12, what: "Scale-up reveal: Series A (2021-04-26) + Discord (04-27) + monthly meetups (05-03) + anniversary recap (06-23)", channels: [blog, press, discord, forum], gap_days_from_previous: 138}
  - {step: 13, what: "Repeat shape for every later launch: forum teaser/beta call -> weekly-train release -> 'Introducing X' (forum+blog+changelog) -> video -> Product Hunt (big ones) -> contest/livestream -> proof post; gaps 5-14 days teaser->reveal, 44-62 days forum->blog", channels: [forum, docs, blog, youtube, producthunt], gap_days_from_previous: null}
```
