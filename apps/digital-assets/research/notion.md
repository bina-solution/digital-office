# Notion (Notion Labs, Inc.) — net-front scan

- **Blueprint target:** `startup-tail` (the repeatable series of media a young product publishes to reveal itself, then its updates)
- **Company scanned:** Notion. The owner wrote "notation"; this scan treats that as Notion.
- **Observed:** 2026-09-29
- **Method:** Most facts come from primary sources: notion.com pages and sitemaps; the `__NEXT_DATA__` JSON of a Marketplace listing; notion.com CSS tokens; public Notion pages (read through Notion's public page API); the Wayback CDX API and raw captures; the YouTube RSS feed, watch pages and channel data; the Product Hunt product pages, awards page and archived posts; the HN Algolia API; the GitHub API; and the Apple Podcasts lookup with the podcast's RSS feed. X, Instagram, TikTok, Facebook, Threads and Reddit block direct reads. Their numbers come from search-result snippets and are marked `~`. Partway through, the session hit its WebSearch cap (200 of 200, shared across the session), so later gaps could only be checked with direct fetches.
- **Confidence marks:**
  - ✓ = read on the primary source
  - ~ = secondary source or search snippet
  - ? = uncertain or inferred

---

## 1. Snapshot

Notion Labs, Inc. was **founded in 2013 in San Francisco** by **Ivan Zhao (CEO) and Simon Last**. Wikipedia also lists Akshay Kothari, Chris Prucha, Jessica Lam and Toby Schachman as founders ~. The first dated public trace is the GitHub org `makenotion`, created **2013-06-23** ✓.

The first product was a no-code / developer-oriented tool. In **2015** the company nearly failed: Zhao laid off the team, moved to **Kyoto** with Last, and rewrote the product around the "block" model ~ ([Figma blog](https://www.figma.com/blog/design-on-a-deadline-how-notion-pulled-itself-back-from-the-brink-of-failure/)). **Notion 1.0 (web + Mac)** launched on Product Hunt on **2016-08-09** ✓. **Notion 2.0** added databases and the "all-in-one workspace" line on **2018-03-20** ✓. The founders call 2.0 "the real 1.0".

**HQ:** downtown San Francisco (about page) ✓. The careers page lists seven hubs: SF, New York, Dublin, Seoul, Hyderabad, Tokyo and Sydney ✓.

**Funding:**

| Date | Round | Amount | Valuation | Lead / investors | Conf. |
|---|---|---|---|---|---|
| 2013 (month unknown; one source says March) | Seed | about $2M | – | First Round wrote the largest check | ~ |
| 2019 (Apr–Jul; exact date unknown) | "Angel round" (called Series A in some sources) | $10M | $800M | Daniel Gross, Elad Gil, Josh Kopelman, First Round, Sherpalo, Draft | ~ ([The Information](https://www.theinformation.com/articles/collaboration-app-notion-labs-hits-800-million-valuation-in-new-funding)) |
| 2020-04-01 | Series B | $50M | $2B | Index Ventures | ~ ([TechCrunch](https://techcrunch.com/2020/04/01/notion-hits-2-billion-valuation-in-new-raise)) |
| 2021-10-08 | Series C | $275M | $10B | Coatue, Sequoia | ~ ([SiliconANGLE](https://siliconangle.com/2021/10/08/productivity-startup-notion-valued-10b-latest-275m-funding-round/)) |
| 2022-07-29 | Secondary purchase of employee shares | not stated | $10B | Sequoia, Index | ✓ ([blog](https://www.notion.com/blog/sequoia-index-purchase-shares-from-notion-employees)) |
| Kicked off 2025-12-15, announced 2026-01-26 | Employee tender | about $270M | $11B | GIC joins Sequoia and Index | ~ ([Forbes](https://www.forbes.com/sites/annatong/2025/12/15/notion-kicks-off-employee-share-sale-at-11-billion-valuation-as-ai-accelerates-its-growth/)) |

Total primary funding is about $343M ~.

**Users:**
- **1M:** Sep 2019 per Wikipedia ~; Ivan Zhao says "2020, pre-Covid" ✓. The two sources conflict.
- **20M:** Oct 2021 ~.
- **100M:** announced on X on 2024-07-22 ✓, then in the blog post "100 million people now use Notion" on 2024-09-03 ✓.

**Revenue:** more than $500M annualized by Sep 2025, and $865M ARR by Jul 2026 per Sacra ~.

**Scale indicators (observed 2026-09-29 unless noted):**
- The home page claims "Trusted by 98% of the Forbes Cloud 100" ✓.
- Marketplace: 30,000+ templates and 22,288 creators ✓.
- Releases: 152 entries on `/releases` since 2020, plus 131 on the legacy changelog ✓.
- YouTube: **349K** subscribers, 737 videos, 153.8M views ✓.
- LinkedIn: **1,122,450** followers; 7,137 members list Notion as employer ✓.
- X @NotionHQ: **~513.7K** followers ~.
- Instagram @notionhq: **~481K** followers, 337 posts ~.
- TikTok @notionhq: **~143.4K** followers, 734.2K likes ~.
- Facebook /NotionHQ: **~62K** ~.
- r/Notion (community-run): **~472K** members ~.
- Community Discord: **~11.4K** members ~.
- GitHub makenotion: **3,059** followers, 61 repos ✓.
- Product Hunt: **19K** followers, 25 launches ✓.

---

## 2. Net-front inventory

*Cadence is a per-month estimate. "Since" is the earliest dated trace found. All URLs are public.*

### 2a. Website sections (notion.com; `notion.so` redirects)

| Channel | URL / handle | Exists since | Followers (date) | Profile bio (verbatim) | Avatar / banner (described) | What is posted there | Cadence | Notes |
|---|---|---|---|---|---|---|---|---|
| Home | https://www.notion.com/ | notion.so first captured 2015-07-13, redirecting to `early-access.notion.so` ✓ | – | `<title>`: "The AI workspace that works for you. \| Notion". Hero: "Where teams and agents Think together." (the capital T may be a styling artifact). Sub: "Capture context, find answers, and automate tasks with AI built for your team." | Product video hero. No illustration in the current hero; Muradov-style illustrations appear on the about page and in campaigns | Positioning, logo wall, 3 value columns, use-case cards, testimonials, McLuhan quote | Hero re-cut at each major launch (2–4 per year) | Footer carries 22 languages, including he and ar. The title has changed at each era (see §3) |
| Product pages | nav: Notion AI, Agents, AI Meeting Notes, Enterprise Search, Knowledge Base, Docs, Projects, Connections, Security, Notion Calendar, What's new, Download | /mobile 2017-09-28 and /desktop 2017-11-02 ✓; /ai 2022-11-16 ✓ | – | Nav captions: "AI tools for work", "Automate busywork", "Perfectly written by AI", "Find answers instantly", "Centralize knowledge", "Simple and powerful", "Manage any project", "Connect your apps", "Safe and scalable", "It's time" | Product UI screenshots and GIFs | One landing page per product surface | A new page per launch | Each page follows the same template: hero, feature blocks, testimonials, CTA |
| Pricing | https://www.notion.com/pricing | 2017-10-29 ✓ | – | Free "Essentials for staying organized"; Plus $10 "For small teams and professionals to work together"; Business $20 "For growing businesses to streamline teamwork"; Enterprise custom | – | Plan cards, comparison table, add-ons (Custom Agents at $10 per 1,000 credits; Workers beta), testimonial, 11 FAQs | Changes 1–2 times a year | Pricing changes are also published as release entries (2020-05-19, 2022-12-07, 2024-06-26) |
| Help Center | https://www.notion.com/help | unknown (/guides 2020-10-11 ✓) | – | "Hi, how can we help you?" | – | 14 categories of articles; guides by team; "What's New" rail | Continuous | See §4 |
| Notion Academy | https://academy.notion.com/ (redirected from /help/notion-academy) | unknown | – | – | – | Learning paths → badges (Essentials, Workflows, Advanced) → proctored Certified Admin exam | Content in 6 new languages on 2026-03-19 ✓ | The site returned 403 to the fetcher, so its structure comes from a help page and snippets ~ |
| Blog "Tools & Craft" | https://www.notion.com/blog | /blog first captured 2021-03-02 ✓ (earlier home unknown) | – | "Tools & Craft – Notion Blog: Thoughts on the future of work, from the people and teams creating it." | Illustrated or photographic cover per post | Categories: Notion HQ, For Teams, Inspiration, Pioneers, Tech, First Block | ~6–10 posts per month (estimate) | Tech posts regularly reach HN (Postgres sharding 471 pts; data model 338; WASM SQLite 253) |
| Releases / What's New | https://www.notion.com/releases (legacy page: https://www.notion.so/What-s-New-157765353f2c4705bd45474e5ba8b46c) | Legacy changelog from 2016-03-19 ✓; `/releases` from 2020-01-09 ✓ | – | Meta: "Product improvements, updates, and fixes." | Cover image per entry | Dated, versioned release notes | 2016: 38 · 2017: 20 · 2018: 15 · 2019: 13 · 2020: 25 · 2021: 18 · 2022: 22 · 2023: 11 · 2024: 13 · 2025: 13 · 2026 to 09-15: 50 | Also sent as email. See §4 and unit U1 |
| Community hub | https://www.notion.com/community → app.notion.com/community | /community 2019-09-08 ✓ | – | not readable (app-rendered) | – | Links to programs and events | – | Programs are hosted as public Notion pages (below) |
| Ambassadors | https://www.notion.so/Notion-Ambassador-Program-45448f9b8e704c7bab254bd505c4717c | unknown | – | "The Notion Ambassador Program brings together our most passionate and creative builders from all over the world." | Photo collages of meetups | Volunteers host events, lead local or virtual communities, create content | Cohorts. Global applications paused in 2026; Korea and Japan still open ✓ | Benefits: Slack + workspace, early access, priority support, event grants, speaking invites, free team workspace, swag. Commitment: 1–2 h per month |
| Champions | https://www.notion.com/champions → public Notion page | unknown | – | "Champions are the biggest Notion fans inside of companies." | 4 photo tiles | In-company admins; Slack, office hours, AMAs with executives | Page says the program is "not fully active" as of 2026 ✓ | Requires a Plus, Business or Enterprise plan; weekly Slack participation plus one event a month; applications reviewed every two weeks |
| Templates / Marketplace | https://www.notion.com/templates (creators at `/@handle`) | Template gallery refresh 2019-07-03; "brand new template gallery" 2021-11-16; creator profiles about May 2023 (@notion created 2023-05-11) ✓ | – | "Choose from 30,000+ Notion templates \| Notion Marketplace" | Template cover (1920×1200) plus mobile image (1125×2436) | Free and paid templates, AI Skills, Agents; 348 categories; collections | New listings daily from the community; Notion-made listings with each launch | Paid templates settle through Stripe Connect. Full listing field model in §4 |
| Integrations / Connections | https://www.notion.com/integrations (items at /connections/&lt;slug&gt;) | 2022-03-02 ✓, the day before the API went GA | – | "Extend Notion with connections that sync your data, automate workflows, and connect your favorite tools." | Partner logos | Filters: category (15), connection type (Public API, AI connector, Embed, SCIM/SSO), developer (Made by Notion, Technology partners); sort | New entries weekly | The card shows logo, name, type, developer badge, adoption count and price |
| Developers | https://developers.notion.com | API public beta 2021-05-13 ✓ | – | – | – | API docs, SDKs, MCP, Workers, Developer Platform (3.5, 2026-05-13) | – | Tied to GitHub (below) |
| Customers | https://www.notion.com/customers | 2020-04-15 ✓ | – | – | Customer photography and logos | Customer stories, most paired with a YouTube film | ~2–4 per month | – |
| Careers | https://www.notion.com/careers | unknown | – | "Notion is for people who care about craft and making work better for others, so they can do their life's work." | Office photos | Values: "Customer in every room", "Own the outcome", "Why not today", "Direct and kind"; benefits; 100+ roles in 15 departments | Continuous | In-office Mon, Tue and Thu |
| About / manifesto | https://www.notion.com/about | 2017-04-15 ✓ | – | Heading: "Why we built Notion" | Muradov-style black-and-white illustrations: office workers, factory workers, mid-century computer operators, a person arranging floating documents | Essay on tool history, from typewriters and filing cabinets to Engelbart, Kay and Nelson; Notion as building blocks; logos of press coverage | Rarely changes | This is the vision anchor (§4) |
| Press / brand kit | https://www.notion.so/Media-Kit-205535b1d9c4440497a3d7a2ac096286 | unknown | – | "Thanks for your interest in Notion! Here are links to our logo, product screenshots, San Francisco Headquarters office photos, and illustrations." | – | Four zip files: NotionLogoFiles, Notion-illustrations, Notion_product_screenshots_Apr2026, NotionHQ-Office-Photos; person42@example.com | Screenshots refreshed (latest set dated Apr 2026) | No `/press` newsroom was found. Company news goes out through the blog's "Notion HQ" category and wire releases (e.g. BusinessWire for Cron, 2022-06-09) |
| Partners / consultants | https://www.notion.com/partners (directory: https://www.notion.so/consulting-partners) | unknown | – | "Become a Notion partner and grow with us." | – | Technology, Solutions, Security & Compliance, Startup and Builders programs; "1,000+ partners" | – | The Startup program offers 6 months of free Business with AI |
| Newsletter / email | release emails ("What's New") | unknown | – | – | – | Each numbered release goes out as an email. The 2026-03-26 note says 3.4 "has too much to cover in a single email" ✓ | ~1 per month | No standalone signup page was found ? |

### 2b. Off-site channels

| Channel | URL / handle | Exists since | Followers (date) | Profile bio (verbatim) | Avatar / banner (described) | What is posted there | Cadence | Notes |
|---|---|---|---|---|---|---|---|---|
| GitHub | https://github.com/makenotion | 2013-06-23 ✓ | 3,059 (2026-09-29) ✓ | "We shape our tools, thereafter our tools shape us" | Notion N-cube | SDKs (notion-sdk-js, 5.7K★), notion-mcp-server (4.7K★), Claude Code / Cursor plugins, workers-template, skills, lore | New repos roughly monthly in 2025–26 | Earliest dated trace of the company |
| YouTube | https://www.youtube.com/@Notion (UCoSvlWS5XcwaSzIcbuJ-Ysg) | Joined 2018-06-02; first upload 2018-06-11 ✓ | 349K subs, 737 videos, 153.8M views (2026-09-29) ✓ | "Notion is the AI workspace where teams and AI agents get more done together. Assign the task, and your Agents will get to work alongside your team in one connected workspace." (opening) | Black-and-white N-cube avatar | Quick Tips and tutorials, customer films, keynotes (Make with Notion), brand films, webinars, podcast videos | ~5 per month (15 uploads from 2026-06-24 to 2026-09-23) ✓ | One brand film ("AI Can't Replace Teamwork", 2026-08-04) has 19.3M views, which points to paid distribution ? |
| X / Twitter | https://x.com/NotionHQ | ≤ 2017-06 (`twitter:site @NotionHQ` in the site meta) ✓; join date unknown | ~513.7K (2026) ~ | not readable (walled) | N-cube ? | Launch posts on release day (e.g. 2026-02-24 Custom Agents), milestones ("first 1,000 users → 100 million", 2024-07-22), community shout-outs | ~30–60 posts per month (estimate) ? | Founder account @ivanhzhao amplifies launches (3.0 post, 2025-09-18) |
| LinkedIn | https://www.linkedin.com/company/notionhq | unknown (lists "Founded 2016") | 1,122,450 (2026-09-29) ✓ | "Notion blends your everyday work tools into one. Product roadmap? Company wiki? Meeting notes? With Notion, they're all in one place, and totally customizable to meet the needs of any workflow." | – | Launches, customer stories, hiring, exec posts | ~20–40 per month ? | Search snippets gave about 548K. The direct fetch (1.12M) is preferred |
| Facebook | https://www.facebook.com/NotionHQ/ | unknown (a Facebook pixel was on the site from 2016-06) | ~62K ~ | "The connected workspace for your docs, projects, and knowledge." ~ | – | Reposts of launches and videos | low ? | Secondary channel |
| Instagram | https://www.instagram.com/notionhq/ | unknown | ~481K, 337 posts ~ | "The AI workspace that works while you sleep." ~ | – | Reels (tips, humor), launch visuals | ~6–10 per month ? | Regional: @notionhq_kr (~5.5K) ~ |
| TikTok | https://www.tiktok.com/@notionhq | ≤ 2023-01-13 (video 7188288460413816110, "#notionnewyear") ~ | ~143.4K followers, 734.2K likes ~ | "The connected workspace for your docs, projects, and knowledge." ~ | – | Short humor and tip videos (student / "notiontok" culture) | ~4–8 per month ? | Walled |
| Threads | https://www.threads.com/@notionhq | unknown | unknown | – | – | Mirror of X ? | ? | Walled |
| Discord (community) | https://discord.com/invite/notion-community-967943233105702922 | Server created 2022-04-25 (snowflake-decoded) ✓ | ~11,435 ~ | "public, community discord server … led by Notion Ambassadors" ~ | – | Help, template sharing, events | Continuous | Community-run, not official |
| Reddit r/Notion | https://www.reddit.com/r/Notion/ | unknown | ~472K ~ | – | – | User questions, templates, self-promotion | Continuous | Community-run. @NotionHQ celebrated 100K members on 2021-03-19 ✓ |
| Product Hunt | https://www.producthunt.com/products/notion | Product page says "Launched in 2015". First Notion Labs post 2015-03-26 ✓ | 19K (2026-09-29) ✓ | – | – | Launch posts for every new surface (§5) | 1–4 per year | Golden Kitty: AI (Alpha) Product of the Year 2022; Notion AI Product of the Year 2023; Calendar and Sites won categories in 2024 ✓ |
| Hacker News | no official account; organic | First story 2017-06-16 ✓ | – | – | – | Organic launch threads and engineering posts | Few big threads per year | Peaks: 2019-01-14 (970 pts), 2020-05-19 (1,044 pts), 2021-05-13 API (536), 2022-11-16 AI waitlist (361) ✓ |
| Podcast | "Notion Podcast": https://podcasts.apple.com/us/podcast/notion-podcast/id1422389039 (RSS https://anchor.fm/s/586e6d8/podcast/rss) | 2018-08-03 ✓ | – | "Candid conversations with the people shaping the world of technology — from pioneers of computer history to founders at the world's leading startups." | – | Series *Pioneers* (2018–21; Andy Hertzfeld, Stu Card, Ted Nelson, Louis Pouzin); *First Block* (founder interviews hosted by co-founder Akshay Kothari) | ~1 per month (34 episodes) | Early YouTube uploads were branded "Tools & Craft Podcast" (2018-06-11) ✓ |
| Events | Make with Notion | 2024-10-24 (SF, "first-ever" / "first global conference") ✓/~; 2025-09-18 (Fort Mason, SF) ~ | – | – | – | Keynote livestream, workshops, launch batch | Yearly | Keynote on YouTube 5 days later (2025-09-23, 359K views) ✓. Ambassadors also run local meetups |
| Merch | none found | – | – | – | – | Swag appears only as a program perk ("Notion Ambassador swag", "Exclusive goodies") ✓ | – | No public store was found ? |

---

## 3. Identification

### Name and handles
- **Name:** Notion. Legal entity: Notion Labs, Inc. (footer: "© 2026 Notion Labs, Inc.").
- **Email domain:** makenotion.com (press@, community@, templates@).
- **Handle system, two stems:**
  - **`NotionHQ` / `notionhq`:** X, Facebook, LinkedIn, Instagram, TikTok, Threads.
  - **`Notion` / `makenotion`:** YouTube `@Notion`, GitHub `makenotion`, Marketplace `@notion`.
- **Domains:**
  - `notion.so` (2015→, the historic primary)
  - `notion.com` (current canonical; switch date unknown)
  - `*.notion.site` (published pages and template previews)
  - `app.notion.com`
  - short links `ntn.so`
- **Consistency:** high. Every official profile uses the same black N-cube avatar and the name "Notion".

### Taglines over time

| Date | Where | Tagline (verbatim) |
|---|---|---|
| 2015-03-26 | Product Hunt (hunter's) | "Capture and organize knowledge collaboratively" |
| 2015-09-14 | Product Hunt, Notion Beta 0.5 | "An expressive and collaborative document editor" |
| 2015-11-25 | Product Hunt | "Documents reimagined" |
| 2016-03 | site `<title>` | "Notion Next" |
| 2016-06-16 | site `<title>` | "Notion – A tool for notes, documents, and knowledge bases – made for modern thinkers." |
| 2016-08-09 | Product Hunt, 1.0 | "Docs, wikis, tasks – a minimal & unified workspace for teams" |
| 2016-10-15 | site `<title>` | "Notion – Docs, wikis, tasks, seamlessly in one. A unified workspace for modern teams." |
| 2017-06 → 2018-03 | site title and meta | "Docs, Wikis, Tasks. Seamlessly in one." / "A new tool that blends your everyday work apps into one. It's a unified and collaborative workspace for you and your team" |
| 2018-03-20 → ~2022 | site title (2.0) | "The all-in-one workspace for your notes, tasks, wikis, and databases." |
| ~2022–2024 (exact dates unknown) | still in social bios | "The connected workspace for your docs, projects, and knowledge." |
| 2024-07-10 | OOH brand campaign | "Think it. Make it." |
| 2026 | site title / hero / Instagram | "The AI workspace that works for you." / "Where teams and agents Think together." / "The AI workspace that works while you sleep." |

### Descriptions
- **Short description in use (79 chars, home subhead):** "Capture context, find answers, and automate tasks with AI built for your team."
- **Long description in use:** the YouTube channel "About". It opens: "Notion is the AI workspace where teams and AI agents get more done together." It continues with "Assign the task, and your Agents will get to work…" and closes on "…spend less time on busywork and more time on your life's work." It then names OpenAI, Figma, Ramp and Toyota as customers.
- **Older long description (LinkedIn):** "Notion blends your everyday work tools into one. Product roadmap? Company wiki? Meeting notes? With Notion, they're all in one place…"

### Terminology glossary (Notion's own nouns)

| Term | Meaning |
|---|---|
| Block | The atomic unit. Every paragraph, image, to-do or embed is a block, and any block can contain blocks. This model came out of the Kyoto rewrite. |
| Page | A block that holds other blocks. Pages nest without limit. |
| Database | A collection of pages with typed properties. It arrived in 2.0; in 2025 the release line was "Everything is database". |
| View | A lens on a database: table, board, timeline, calendar, gallery, list, chart, dashboard, map, form. |
| Property | A typed field on a database page (select, date, person, relation, formula…). |
| Relation / Rollup | A link between databases, and an aggregation across that link. |
| Linked database | A view of one database embedded elsewhere. |
| Synced block | Content mirrored across pages (2.11, 2021). |
| Template | A reusable page or database starting point. Also database templates and template buttons. |
| Workspace | The tenant: a team's or person's whole Notion. |
| Teamspace | A department-level area inside a workspace (2.18, 2022). |
| Sidebar / Home / Library | Navigation surfaces. Library arrived 2026-02-18. |
| Wiki / page verification | A knowledge base with "verified" pages. |
| Connections | Integrations and link previews. Also the gallery name. |
| Notion AI | The AI layer (alpha 2022-11-16, GA 2023-02-22). |
| Agent | The personal AI agent that acts inside Notion (3.0). |
| Custom Agent | A team-built agent with triggers and schedules (3.3, 2026-02-24). |
| Skills | Reusable AI instructions ("AI Skills" category; 3.7). |
| Workers | Code running on Notion's infrastructure (Developer Platform, 3.5). |
| AI Meeting Notes | Transcription and summaries (2.51). |
| Enterprise Search | Cross-app answers (2.51). |
| Notion Calendar | The calendar app (formerly Cron). |
| Notion Mail | The email client (formerly Skiff; launched 2025-04-15). |
| Notion Sites | Web publishing (2024-06-25). |
| Forms | A form view on databases (2024-10-24). |
| Marketplace | The template store with creator profiles (`/@handle`). |
| Notion credits | The usage currency for agents and Workers. |
| Notion Faces | The official hand-drawn avatar creator (2025-01-10). |
| Ambassadors / Champions | Community programs: external teachers, and in-company admins. |
| Made by Notion | The label for first-party templates and connections. |
| Pioneers / First Block / Tools & Craft | Editorial franchises: computing history, founder interviews, the blog name. |

### Colors (from the notion.com "Tatami" design-system tokens) ✓
- **Base:** white `#ffffff`; black `#000000`. The warm gray ramp runs gray-100 `#f9f9f8`, 200 `#f6f5f4`, 300 `#dfdcd9`, 400 `#a39e98`, 500 `#78736f`, 600 `#615d59`, 700 `#494744`, 800 `#31302e`, 900 `#191918`.
- **Action blue:** blue-600 `#0075de` (primary buttons); blue-500 `#097fe8`.
- **Accent 500s:**

  | Color | Hex |
  |---|---|
  | red | `#f64932` |
  | orange | `#ff6d00` |
  | yellow | `#ffb110` |
  | green | `#1aae39` |
  | teal | `#2a9d99` (surface-accent uses the teal ramp) |
  | purple | `#9849e8` |
  | pink | `#ff64c8` |
  | brown | `#9c7054` |

- **Text:** normal text is black at 90% alpha (`#000000e5`); muted is `#0000008a`.
- **Campaign palettes:** the agents-launch campaign uses blues `#455dd3` / `#213183` / `#02093a` with cream `#fefcd5`. The dev-platform "DOS" campaign uses `#1313ba` / `#0a0a5d`.
- **Brand rule:** the product stays near-monochrome. Bold primary colors first appeared in ads with the 2024 campaign ✓ (blog).

### Typography ✓
- **NotionInter:** a custom Inter cut, the primary sans.
- **Lyon Text:** a serif for editorial and quote moments.
- **iA Writer Mono:** code and monospace.
- **Permanent Marker:** a handwritten face loaded as an @font-face. Its use is assumed to be campaign or annotation accents ?
- **RTL:** Noto Sans Hebrew and Noto Sans Arabic cover the he and ar locales.

### Theme
- The marketing site is light-first (white canvas, warm grays). Dark palettes exist in the CSS (`.dark` modules, `prefers-color-scheme: dark`).
- The product has full light and dark modes (dark-mode settings 2021-01-27) and a high-contrast mode (2026-07-30) ✓.

### Logo and usage
- **Mark:** an isometric, hand-drawn-looking **cube with a bold serif "N" on its face**, black outline on white. It works as an app icon on its own or beside the "Notion" wordmark.
- **Stability:** it has been unchanged in substance since about 2016 per secondary sources ~. No official redesign was found for 2023–2026 ?
- **Where the new marks are:** since 2024 the brand has added animated secondary marks rather than changing the logo:
  - the **Notion AI face**: a Muradov-drawn face with eyes, eyebrows and nose, animated by BUCK in cel animation and implemented in Rive with states for thinking and error
  - **Notion Faces** avatars (2025-01-10)
- **Assets:** logo files ship in the Media Kit (`NotionLogoFiles.zip`, not opened).

### Illustration style
- **Artist:** long-time illustrator and later **art director Roman Muradov**.
- **Style:** minimalist, gestural **black-and-white pencil-and-ink characters** with light "diaphanous" strokes and muted tones. Influences named: Cubism, Saul Steinberg, Rube Goldberg.
- **Where it appears:** empty states, about page, templates, onboarding and the 2024 OOH campaign.
- **2024 "Think it. Make it." principles:**
  - "stay true" to the original heritage
  - "show, don't tell" abstract thinking
  - "move in closer" to characters' inner worlds
  - the first use of bold primary colors, for billboards in SF, London and Seoul ✓
- **Motion:** hand-made cel animation (AI face). Release notes use short product GIFs.

### Voice and tone
- Plain, warm and slightly playful.
- **Release titles:** end with emoji (e.g. "Notion 2.8, now free for personal use 🤘") and follow the formula "Notion X.Y: &lt;benefit&gt;".
- **Candor:** "the 2.0 is the real 1.0 for us"; 3.4 has "a champagne problem".
- **Craft vocabulary:** tools, craft, building blocks, "life's work".
- **Reverence for computing history:** Engelbart, Kay, Nelson, McLuhan's line "We shape our tools, and thereafter our tools shape us".
- **Headlines:** short declaratives with light humor ("Make it cute (no, really)").

---

## 4. Content structure

### About / who we are (`/about`, "Why we built Notion")
Sections in order:
1. Today's tab-cluttered work
2. The history of tools, from the Industrial Revolution to 1970s computing pioneers
3. The "vision gap": today's tools are still paper metaphors
4. Notion's answer: customizable building blocks, "solve your problems your way"
5. Company: SF office, team interests, careers
6. Press logos: Forbes, Fast Company, TechCrunch, NYT, WSJ, The Verge

Black-and-white character illustrations run throughout.

### Help Center (`/help`) and Academy
- **Top level:** search ("Hi, how can we help you?") and **14 categories**:
  1. Get started
  2. Workspace basics
  3. Create & format pages
  4. Build databases
  5. Share & collaborate
  6. Automation & connections
  7. Work with Notion AI
  8. Agents in Notion
  9. Admin & security
  10. Calendar & Apps
  11. Get started on marketplace
  12. Manage your plan
  13. Fix a problem
  14. Developer Platform
- **Other rails:** "Browse by team" guides (project management, engineering, design, marketing, startup, enterprise); a "What's New" rail; support links (chat, community, consultants).
- **URL patterns:** `/help/<slug>`, `/help/category/<name>`, `/help/guides/category/<team>`.
- **Article anatomy** (e.g. *Intro to databases*):
  - breadcrumb → title → embedded video (with a YouTube link) → intro plus a 4-bullet overview → table of contents
  - 6 H2 sections, each with screenshots and "Note"/"Tip" callouts
  - an "Up next" card, then a thumbs up/down feedback widget
- **Academy** (academy.notion.com):
  - learning paths → **badges** (Essentials, Workflows, Advanced; free; knowledge check)
  - → **Notion Certified Admin** (paid, proctored; needs all 3 badges)
  - credentials are valid 2 years
  - videos and certifications exist in 6 more languages since 2026-03-19 ✓ / ~

### Template gallery listing — every field of ONE listing
The listing is *Habit tracker* (made by Notion): https://www.notion.com/templates/notion-habit-tracker (read from the page's `__NEXT_DATA__` and JSON-LD on 2026-09-29) ✓

| Field | Type | Value |
|---|---|---|
| `<title>` / OG title | string (name + year + "Template \| Notion Marketplace") | "Habit tracker 2026 Template \| Notion Marketplace" |
| name | string | "Habit tracker" |
| slug | string | `notion-habit-tracker` (URL `/templates/<slug>`) |
| emoji icon | emoji | 📝 |
| short description (meta and card) | string ≤ 160 | "Build and maintain healthy habits with this automated habit tracker template." |
| long description (body) | rich text | Opens "Keep yourself accountable by tracking your habits everyday." Mentions the button block and one-click check-off |
| cover image | image | 1920×1200 (desktop) |
| mobile image | image | 1125×2436 |
| screenshots | image[] | 2048×1280 |
| mobile screenshots | image[] | 750×2668 |
| preview URL | url | `https://notion.notion.site/Habit-tracker-…` (a live Notion page behind "View template") |
| block_id | uuid | the source page that gets duplicated |
| made_by | enum | `notion` \| `community` |
| creator | object | name "Notion", handle `@notion`, avatar 200×200, badge "Recommended creator" (`is_featured_creator`), bio "Welcome to Notion's creator profile! Here you'll find countless templates to inspire your next project.", 571 templates, links (notion.so, X, TikTok, LinkedIn), contact email, consultant_status |
| price | money | Free (USD 0). Paid listings carry a price and settle through Stripe Connect |
| primary category | ref | "Habit Tracking" (3,386 templates, 1,920 free; icon `checkmark-line`, purple) |
| tags | ref[] | 2 direct and 6 total |
| rating | number + histogram | 4.59 / 5 from 1,823 ratings (5★ 1,400 · 4★ 253 · 3★ 82 · 2★ 24 · 1★ 64). The UI rounds to "4.65 / 1K+" |
| installation_count | int | 218,666 |
| reviews | object[] | title, body, rating, author name, created and updated time, optional creator response, status |
| created / last updated | date | 2023-03-23 / 2025-07-23 (published_version 33) |
| locales | enum[] | en-US default; the UI offers 19 more |
| related templates | ref[] | "More by Notion" (3) and "Similar templates" (3 from other creators) |
| collections | ref[] | "Your productivity hub", "Top 10 most popular", "Healthy habits made easy" |
| CTAs | actions | "View template" (preview → duplicate); share to X, LinkedIn, Facebook, email; "Report template"; Terms; "Become a creator → Get started" |
| related content | ref[] | Help and blog posts linked from the category |
| social card | image | Auto-generated `/front-api/og-image/templates/<slug>` |
| structured data | JSON-LD | schema.org `Product` with `offers` (price, USD) and `aggregateRating` |

### Home page sections in order (2026-09-29) ✓
1. Nav (Product mega-menu, Resources, Pricing, Request a demo, Log in, Get Notion free)
2. Hero: headline, subhead, 2 CTAs, product video
3. Logo wall: "Trusted by 98% of the Forbes Cloud 100" (OpenAI, Figma, Ramp, Cursor, Vercel, Nvidia, Volvo, L'Oréal, Discord…)
4. Three pillars with UI shots: Capture knowledge / Find answers / Automate busywork
5. Use-case cards (triage product feedback, resolve support tickets in Slack, security alerts, weekly reporting, developer tools)
6. Testimonials: "Trusted by teams that ship." (Cursor, Faire, Ramp)
7. McLuhan quote
8. Footer: Product, Resources, Company, "Notion for", 22 languages, cookie settings

### Blog post types
| Category | Content |
|---|---|
| Notion HQ | Company news, acquisitions ("ZeroEntropy is joining Notion"), security updates, new executives, board |
| For Teams | How-to and use-case articles, launch explainers |
| Inspiration | Profiles of users and creators |
| Pioneers | Computing-history essays and interviews |
| Tech | Engineering deep dives: Postgres sharding, CRDTs, search reindexing, WASM SQLite |
| First Block | Founder interviews, cross-posted as podcast and video |

Post card fields: cover image, category, title, author, excerpt.

### Newsletter
The "What's New" release email mirrors `/releases`: the same cover, sections and GIFs. The asset names say so, e.g. `September2025_WhatsNew_BugTracker.gif`. Program newsletters also exist: Ambassador-application alerts through a form. No standalone public newsletter archive was found ?

### News / press
- Media Kit public page (logo, illustrations, screenshots, office photos, person42@example.com).
- Company announcements appear as "Notion HQ" blog posts, sometimes with a wire release (BusinessWire, GlobeNewswire).

### Release entry format (ONE entry: 2025-09-18 "Notion 3.0: Agents") ✓
1. `<time>` "September 18, 2025"
2. H1 "Notion 3.0: Agents" (the pattern is `Notion <major.minor>: <headline>`; micro-releases drop the version)
3. Two or three intro paragraphs. The hook is "Notion 3.0 is here!", followed by the one-line promise and the lineage ("With Notion 1.0 and 2.0 … With 3.0 …")
4. Six to ten feature sections. Each is an H3 benefit headline (e.g. "Make it cute (no, really)"), then a GIF or 3840-wide JPG, then one to three paragraphs, sometimes a link to help or templates
5. A "Recent releases" grid: cover image, date, title

Meta description: the first sentence. The URL is `/releases/<YYYY-MM-DD>`.

### Vision / manifesto
- The About essay places Notion in the Engelbart–Kay–Nelson line of "tools that augment intellect".
- Supporting pieces: the *Pioneers* series; the GitHub bio and home-page McLuhan quote; Ivan Zhao's line that the world needs "building blocks for software" (100M blog).
- The 3.0 framing: 1.0 and 2.0 gave tools; 3.0 gives agents that do the work.

---

## 5. Media timeline (first public trace → today)

| Date | Stage | Channel(s) | Media | Title | URL | Note |
|---|---|---|---|---|---|---|
| 2013 (month ?) | funding | press | article (retro) | Seed about $2M, First Round's largest check | https://en.wikipedia.org/wiki/Notion_(productivity_software) | ~ month unknown |
| 2013-06-23 | pre-launch | GitHub | org | `makenotion` organization created | https://github.com/makenotion | ✓ earliest dated trace |
| 2015 (early) | pivot | – | (retro article) | Team laid off; founders move to Kyoto and rewrite the product | https://www.figma.com/blog/design-on-a-deadline-how-notion-pulled-itself-back-from-the-brink-of-failure/ | ~ |
| 2015-03-26 | pre-launch (unplanned) | Product Hunt | post | "Notion: Capture and organize knowledge collaboratively" (hunted by Chris Messina, 10 upvotes) | https://web.archive.org/web/20160319120303/http://www.producthunt.com/posts/notion-2 | ? date read from page metadata |
| 2015-04-22 | pre-launch | YouTube | channel | A channel named "Notion" (UC7VipXG_qo4gWVkYLxBbMjA) created; one "Test." video on 2015-12-27 | https://www.youtube.com/feeds/videos.xml?channel_id=UC7VipXG_qo4gWVkYLxBbMjA | ? ownership unconfirmed |
| 2015-07-13 | teaser | website | landing (gate) | notion.so redirects to early-access.notion.so | https://web.archive.org/web/20150713213038/https://www.notion.so/ | ✓ invite-only phase |
| 2015-09-14 | reveal (accidental) | Product Hunt | post | "Notion Beta — An expressive and collaborative document editor" (Notion 0.5, 554 upvotes). Ivan: "trying to keep it low until the 1.0" | https://web.archive.org/web/20170511144729/https://www.producthunt.com/posts/notion-4 | ✓ |
| 2015-11-25 | community | Product Hunt | post | "Notion — Documents reimagined" (5 upvotes) | https://web.archive.org/web/20170513151000/https://www.producthunt.com/posts/notion-6 | ✓ |
| 2016-01-23 | pre-launch | website | app gate | "Notion – Login"; the page says browser support is coming soon | https://web.archive.org/web/20160123121507/https://www.notion.so/ | ✓ |
| 2016-03-15 | teaser | website | title | "Notion Next" | https://web.archive.org/web/20160315103449/https://www.notion.so/ | ✓ |
| 2016-03-19 | release | What's New (public Notion page) | changelog | First dated changelog entry. Building in public begins | https://www.notion.so/What-s-New-157765353f2c4705bd45474e5ba8b46c | ✓ 38 entries in 2016 |
| 2016-06-16 | reveal | website | title | "A tool for notes, documents, and knowledge bases – made for modern thinkers." | https://web.archive.org/web/20160616122804/https://www.notion.so/ | ✓ |
| 2016-08-09 | launch | Product Hunt, web, Mac app | post | "Notion 1.0 Web + Mac App — Docs, wikis, tasks – a minimal & unified workspace for teams" (hunter Naval Ravikant, 2,945 upvotes) | https://web.archive.org/web/20170415062308/https://www.producthunt.com/posts/notion-1-0-web-mac-app | ✓ Ivan: "accidentally hunted 10 months ago… rebuilding from scratch" |
| 2016-10-15 | positioning | website | title | "Docs, wikis, tasks, seamlessly in one. A unified workspace for modern teams." | https://web.archive.org/web/20161015190946/https://www.notion.so/ | ✓ |
| 2016-12-02 | milestone | Product Hunt | award nomination | Golden Kitty nominee, "Desktop Product of the Year" | https://web.archive.org/web/20170511225411/https://www.producthunt.com/posts/notion-1-0-web-mac-app-2 | ✓ |
| 2016-12-20 | release | What's New | changelog | Notion 1.5 | https://www.notion.so/What-s-New-157765353f2c4705bd45474e5ba8b46c | ✓ |
| 2017-04-15 | release | What's New, website | changelog + page | Notion 1.7. The `/about` page is first captured the same day | https://web.archive.org/web/20170415074332/https://www.notion.so/about | ✓ |
| 2017-06-16 | community | Hacker News | story | "Notion.so – A unified and collaborative workspace" | https://news.ycombinator.com/item?id=14571454 | ✓ first HN story |
| 2017-09-25 → 2017-12-12 | release | What's New | changelog | Notion 1.8 → 1.9. /mobile (2017-09-28) and /desktop (2017-11-02) pages appear | https://www.notion.so/What-s-New-157765353f2c4705bd45474e5ba8b46c | ✓ |
| 2018-03-20 | launch (relaunch) | Product Hunt, website, What's New | post + page | "Notion 2.0 — The all-in-one workspace - notes, tasks, wikis, & databases" (2,049 upvotes, #1 of the day). Adds tables, kanban, calendars. The site title changes the same day | https://hunted.space/dashboard/122747 | ✓ "the 2.0 is the real 1.0 for us" |
| 2018-06-02 | community | YouTube | channel | @Notion joined | https://www.youtube.com/@Notion | ✓ |
| 2018-06-07 | release | What's New | changelog | Notion 2.1 | https://www.notion.so/What-s-New-157765353f2c4705bd45474e5ba8b46c | ✓ |
| 2018-06-11 | media | YouTube | video (109 s) | "Tools & Craft Podcast: Backstage with Andy Hertzfeld" (first upload) | https://www.youtube.com/watch?v=4QDQeykT4dY | ✓ |
| 2018-08-03 | media | Podcast | audio | "Pioneers: Andy Hertzfeld on building the Macintosh" (first episode) | https://anchor.fm/s/586e6d8/podcast/rss | ✓ |
| 2018-10-24 | release | What's New | changelog | Notion 2.2 | https://www.notion.so/What-s-New-157765353f2c4705bd45474e5ba8b46c | ✓ |
| 2019-01-14 | milestone (organic) | Hacker News | story | "Notion – All-in-one workspace for notes, tasks, wikis, and databases" (970 pts, 479 comments) | https://news.ycombinator.com/item?id=18904648 | ✓ |
| 2019-01-28 → 2019-06-17 | release | What's New | changelog | Notion 2.3, 2.4 (04-03), 2.5 (04-29), 2.6 (06-17) | https://www.notion.so/What-s-New-157765353f2c4705bd45474e5ba8b46c | ✓ |
| 2019 (Apr–Jul) | funding | press | article | $10M "angel round" at $800M | https://www.theinformation.com/articles/collaboration-app-notion-labs-hits-800-million-valuation-in-new-funding | ~ exact date unknown |
| 2019-07-03 | community | What's New | changelog | "New Templates" (template gallery expansion) | https://www.notion.so/What-s-New-157765353f2c4705bd45474e5ba8b46c | ✓ |
| 2019-09 | milestone | – | – | 1M users per Wikipedia (Ivan Zhao says 2020) | https://www.notion.com/blog/100-million-of-you | ? conflicting sources |
| 2019-12-06 | media | YouTube | video (151 s) | "Using database views" (first how-to tutorial) | https://www.youtube.com/watch?v=-vLeXjO3aKU | ✓ |
| 2020-01-09 | release | website | release page | `/releases` begins ("stability & infrastructure upgrades") | https://www.notion.com/releases/2020-01-09 | ✓ |
| 2020-01-21 | media | YouTube | video (114 s) | "Figma x Notion: One knowledge base keeps everyone informed & aligned" (first customer film) | https://www.youtube.com/watch?v=RJvD_VBz8s4 | ✓ |
| 2020-04-01 | funding | press | article | $50M at $2B, led by Index | https://techcrunch.com/2020/04/01/notion-hits-2-billion-valuation-in-new-raise | ~ |
| 2020-05-19 | launch (pricing) | releases, HN | release + story | "Notion 2.8, now free for personal use 🤘" (HN 1,044 pts) | https://www.notion.com/releases/2020-05-19 | ✓ |
| 2020-08-10 | release (localization) | releases | release | "Notion in Korean 🇰🇷" | https://www.notion.com/releases/2020-08-10 | ✓ first localization |
| 2020-11-11 | release | releases, HN | release | "Notion 2.10, now with Timeline" (HN 311 pts) | https://www.notion.com/releases/2020-11-11 | ✓ |
| 2020-12-08 | release | releases | release | "API private beta" | https://www.notion.com/releases/2020-12-08 | ✓ |
| 2021-03-19 | community | X | post | @NotionHQ celebrates r/Notion reaching 100K members | https://x.com/NotionHQ/status/1372987922400473090 | ✓ date decoded from the tweet ID |
| 2021-05-13 | launch | releases, developers site, HN | release | "Start building with the API" (HN 536 pts) | https://www.notion.com/releases/2021-05-13 | ✓ |
| 2021-09-08 | acquisition | releases | release | "Acquiring Automate.io" | https://www.notion.com/releases/2021-09-08 | ✓ |
| 2021-10-08 | funding | press | article | $275M at $10B (Coatue, Sequoia); 20M users | https://siliconangle.com/2021/10/08/productivity-startup-notion-valued-10b-latest-275m-funding-round/ | ~ |
| 2021-10-12 | release (localization) | releases, wire | release + press release | "Notion in Japanese 🇯🇵" | https://www.notion.com/releases/2021-10-12 | ✓ |
| 2021-11-16 | release | releases | release | "Notion 2.14, now with simple tables" plus a brand-new template gallery | https://www.notion.com/releases/2021-11-16 | ✓ |
| 2022-03-03 | launch | releases, integrations gallery | release | "Connect your tools with the API" (API out of beta; `/integrations` gallery goes live 2022-03-02) | https://www.notion.com/releases/2022-03-03 | ✓ |
| 2022-04-25 | community | Discord | server | Community Discord server created | https://discord.com/invite/notion-community-967943233105702922 | ✓ date decoded from the server ID; community-run |
| 2022-06-09 | acquisition | blog, BusinessWire | article + press release | "Notion acquires Cron, the next-generation calendar" | https://www.notion.com/blog/notion-acquires-cron | ✓ |
| 2022-07-29 | funding (secondary) | blog | article | Sequoia and Index buy employee shares at $10B | https://www.notion.com/blog/sequoia-index-purchase-shares-from-notion-employees | ✓ |
| 2022-08-29 | release | releases | release | "Notion 2.18, now with teamspaces" | https://www.notion.com/releases/2022-08-29 | ✓ |
| 2022-11-16 | teaser (waitlist) | website /ai, Product Hunt, HN | waitlist page + launch | "Notion AI – waiting list signup" (HN 361). PH Notion AI (Alpha): Launch of the Day, Week and Month; later Golden Kitty Product of the Year 2022 | https://news.ycombinator.com/item?id=33623201 | ✓ |
| 2022-12-07 | pricing | releases | release | "Expanded Free Plan & new Business Plan" | https://www.notion.com/releases/2022-12-07 | ✓ |
| 2023-02-22 | launch (GA) | releases | release | "Notion 2.21: Notion AI, for everyone" | https://www.notion.com/releases/2023-02-22 | ✓ 98 days after the waitlist |
| 2023-05-11 | community (marketplace) | Marketplace | creator profile | `@notion` creator profile created; the creator-profile Marketplace era begins | https://www.notion.com/@notion | ? inferred from `profile.created_at` |
| 2023-05-31 | launch | releases | release | "Notion 2.30: Project Management" (Notion Projects) | https://www.notion.com/releases/2023-05-31 | ✓ |
| 2023-11-14 | launch (beta) | releases | release | "Notion 2.35: Introducing Q&A by Notion AI" | https://www.notion.com/releases/2023-11-14 | ✓ |
| 2024-01-17 | launch | releases, Product Hunt (2024-01-18) | release + post | "Notion 2.37: Notion Calendar" (PH 1,198 upvotes, #2 of the day; Golden Kitty, Personal Productivity) | https://www.notion.com/releases/2024-01-17 | ✓ rebrand of Cron |
| 2024-02-09 | acquisition | – | – | Skiff acquired (later becomes Notion Mail) | https://en.wikipedia.org/wiki/Notion_(productivity_software) | ~ |
| 2024-06-25 | launch | releases, Product Hunt | release + post | "Notion 2.42: Introducing Notion Sites" (PH 634 upvotes; Golden Kitty, No-Code) | https://www.notion.com/releases/2024-06-25 | ✓ |
| 2024-07-10 | rebrand (campaign) | OOH (SF, London, Seoul), blog | billboards + article | "Think it. Make it." campaign (Muradov illustrations; first bold colors) | https://www.notion.com/blog/the-thinking-behind-our-latest-brand-campaign | ✓ |
| 2024-07-22 | milestone | X | post (image) | "From our first 1,000 users → to 100 million!" | https://x.com/NotionHQ/status/1815513728315699586 | ✓ |
| 2024-08-13 | teaser | releases | release | "Notion 2.44: Introducing charts + a sneak peek at forms" | https://www.notion.com/releases/2024-08-13 | ✓ |
| 2024-09-03 | milestone | blog | founder letter | "100 million people now use Notion" (Ivan Zhao) | https://www.notion.com/blog/100-million-of-you | ✓ |
| 2024-09-25 | launch | releases | release | "Notion 2.45: Meet the new Notion AI" | https://www.notion.com/releases/2024-09-25 | ✓ |
| 2024-10-24 | event | Make with Notion (SF), blog, releases, livestream | keynote + recap | First global conference. "Notion 2.46: Forms, Mail, layouts, new automations"; Mail waitlist; Marketplace redesign | https://www.notion.com/blog/conference-product-releases | ✓ |
| 2025-01-10 | launch | Product Hunt | post | "Notion Faces — Bring your custom self-portrait in Notion, officially" (#4 of the day) | https://www.producthunt.com/products/notion/launches | ✓ |
| 2025-04-15 | launch | releases, Product Hunt | release + post | "Notion 2.50: Meet Notion Mail" (PH "The first inbox that thinks like you", 451 upvotes) | https://www.notion.com/releases/2025-04-15 | ✓ 173 days after the waitlist |
| 2025-05-13 | launch | releases, Product Hunt | release + post | "Notion 2.51: AI Meeting Notes, Enterprise Search & more" (PH #1 of the day and week, #5 of the month) | https://www.notion.com/releases/2025-05-13 | ✓ |
| 2025-07-10 | release | releases | release | "Notion 2.52: Everything is database" | https://www.notion.com/releases/2025-07-10 | ✓ |
| 2025-08-19 | release | releases | release | "Notion 2.53: Offline mode" | https://www.notion.com/releases/2025-08-19 | ✓ |
| 2025-09-18 | launch + event | Make with Notion 2025 (Fort Mason SF), releases, X (founder), TechCrunch | keynote, release, post, article | "Notion 3.0: Agents" | https://www.notion.com/releases/2025-09-18 | ✓ Ivan Zhao's X post: https://x.com/ivanhzhao/status/1968761820241609063 |
| 2025-09-23 | media | YouTube | keynote video | "Make with Notion 2025: Product Launch Keynote (Ivan Zhao)" (359K views) | https://www.youtube.com/watch?v=KZ3hAy_XZwI | ✓ 5 days after the event |
| 2025-11-17 | release | releases | release | "Notion 3.1" (agent updates, Meetings tab, map view) | https://www.notion.com/releases/2025-11-17 | ✓ micro-releases start 2025-11-10 |
| 2025-12-15 | funding (secondary) | press | article | Employee share sale at $11B | https://www.forbes.com/sites/annatong/2025/12/15/notion-kicks-off-employee-share-sale-at-11-billion-valuation-as-ai-accelerates-its-growth/ | ~ (tender reported 2026-01-26, about $270M, GIC) |
| 2026-01-29 | rebrand (identity) | press (design media) | case study | BUCK × Muradov: the hand-drawn Notion AI character | https://the-brandidentity.com/project/how-buck-gave-notions-ai-assistant-a-hand-drawn-personality | ~ |
| 2026-02-24 | launch | releases, X, Product Hunt (02-25) | release + post | "Notion 3.3: Custom Agents" (PH 409, #2 of the day) | https://www.notion.com/releases/2026-02-24 | ✓ 159 days after the 3.0 tease |
| 2026-03-19 | community (education) | releases, Academy | release | "Notion Academy & certifications, in 6 new languages" | https://www.notion.com/releases/2026-03-19 | ✓ |
| 2026-03-26 / 2026-04-14 | release | releases, email | release (two parts) | "Notion 3.4, part 1" / "part 2" ("too much to cover in a single email") | https://www.notion.com/releases/2026-03-26 | ✓ |
| 2026-05-13 | launch | releases, Product Hunt (05-14) | release + post | "3.5: Notion Developer Platform" (PH "Build on Notion, not just inside it") | https://www.notion.com/releases/2026-05-13 | ✓ |
| 2026-07-01 | release | releases | release | "Notion 3.6: External Agents, HTML blocks, and more" | https://www.notion.com/releases/2026-07-01 | ✓ |
| 2026-07-08 | launch | releases, App Store | release | "Meet the Notion Agents iOS app" | https://www.notion.com/releases/2026-07-08 | ✓ |
| 2026-07-10 | launch | Product Hunt | post | "Ship OS by Notion — The agent-native way to ship software" (174 upvotes) | https://www.producthunt.com/products/notion/launches | ✓ |
| 2026-08-04 | brand film | YouTube (paid ?) | video | "AI Can't Replace Teamwork" (19.3M views) | https://www.youtube.com/watch?v=vG_LQo0wOGg | ✓ views / ? paid |
| 2026-09-15 | release | releases, email | release | "Notion 3.7: Agent skills for your whole team" | https://www.notion.com/releases/2026-09-15 | ✓ latest |
| 2026-09-22 | media | YouTube | Quick Tip | "What are database views in Notion? \| Quick Tip" | https://www.youtube.com/watch?v=3TO_yjh4L_I | ✓ the recurring tutorial format |

**The recurring rhythm since 2020:**
- a dated release note about every 2–4 weeks, with a numbered "Notion X.Y" every 1–2 months (2.7 → 2.53 over 2020–25; 3.0 → 3.7 over Sep 2025–Sep 2026)
- since late 2025, several single-feature micro-releases a week (50 entries in 2026 so far)
- one flagship launch per quarter, each with a Product Hunt post
- one conference a year (Make with Notion)
- YouTube at about 5 per month: Quick Tips, customer films, keynotes
- a podcast episode about once a month (First Block)
- a localization launch every 6–12 months

---

## 6. Repeatable media units

| id | Name | Trigger | Channels | Assets | Copy structure | Cadence | Examples |
|---|---|---|---|---|---|---|---|
| U1 | Numbered release note ("Notion X.Y: &lt;benefit&gt;") | A feature batch is ready | /releases, email, X, LinkedIn, in-app "What's new" | 1 cover (16:9), 4–10 sections each with a GIF or 3840w JPG plus 1–3 paragraphs, "Recent releases" grid, social cut of the cover | date → "Notion X.Y: benefit" → hook ("X is here!" / "Big news today") → lineage or promise line → H3 benefit headline + visual + paragraph + help link (repeat) → recent releases | Every 4–8 weeks (major.minor) | https://www.notion.com/releases/2025-09-18 · https://www.notion.com/releases/2020-05-19 · https://www.notion.com/releases/2026-09-15 |
| U2 | Micro-release | One shippable feature or new model | /releases, X | 1 cover plus 1–2 paragraphs, optional GIF | "&lt;Thing&gt;, now in Notion" / "&lt;Verb&gt; with Notion AI" → what it does → why it matters | 2–5 per week in 2026 | https://www.notion.com/releases/2026-02-09 · https://www.notion.com/releases/2026-07-30 · https://www.notion.com/releases/2026-03-02 |
| U3 | Product Hunt launch | A new product or surface (1.0, 2.0, AI, Calendar, Sites, Faces, Mail, Meeting Notes, Custom Agents, Dev Platform) | Product Hunt, X, LinkedIn | Tagline ≤ 60 chars, gallery images and video, maker's first comment (founder story), a same-day release note | "&lt;Product&gt;: &lt;one-line promise&gt;" → maker comment (why, what's new, ask) | 1–4 per year | https://hunted.space/dashboard/122747 · https://www.producthunt.com/products/notion/launches · https://web.archive.org/web/20170415062308/https://www.producthunt.com/posts/notion-1-0-web-mac-app |
| U4 | Annual keynote event ("Make with Notion") | Yearly launch batch | In-person event (SF), livestream, YouTube, blog, releases, Product Hunt | Keynote video (about 30–60 min, 16:9), session playlist, recap blog "Everything we launched at…", same-day release note, waitlists | "The problem (tool sprawl)" → "the mission" → new ways to build / work / share → CTA (waitlist, demo) | Yearly (2024-10-24, 2025-09-18) | https://www.notion.com/blog/conference-product-releases · https://www.youtube.com/watch?v=KZ3hAy_XZwI · https://www.notion.com/releases/2024-10-24 |
| U5 | Waitlist / sneak-peek teaser | A product not yet ready (AI, Forms, Mail, Custom Agents) | Landing page (/ai, /product/mail), release note ("sneak peek"), keynote, HN (organic) | Landing page with signup form, 1 demo GIF or video, teaser section inside a release | "Coming soon" → a single promise → "Sign up now to join the waitlist" | 1–2 per year; GA follows in 72–173 days | https://news.ycombinator.com/item?id=33623201 · https://www.notion.com/releases/2024-08-13 · https://www.notion.com/releases/2024-10-24 |
| U6 | Milestone post | A user, community or funding milestone | X (image post), blog (founder letter), LinkedIn | 1 image card, a founder essay of about 800–1,500 words, a photo of early days | "From &lt;first&gt; → to &lt;now&gt;!" → thanks → how we got here → what's next | 1–2 per year | https://x.com/NotionHQ/status/1815513728315699586 · https://www.notion.com/blog/100-million-of-you · https://x.com/NotionHQ/status/1372987922400473090 |
| U7 | Acquisition announcement | A deal closes | Blog (Notion HQ), wire release, release note, the acquired product's own blog | Blog post with both logos, press release, FAQ | "Notion acquires &lt;X&gt;, the &lt;category&gt;" → why → what happens to users → future vision | About 1 per year | https://www.notion.com/blog/notion-acquires-cron · https://www.notion.com/releases/2021-09-08 · https://www.cron.com/blog/2022-06-09-cron+notion |
| U8 | Quick Tip / how-to video | A feature needing education | YouTube, TikTok, Instagram, help-article embed | 1–3 min 16:9 screen recording with voice-over (vertical cut for social), thumbnail | "What is / How to &lt;feature&gt;" → a 3-step demo → where to learn more (Help or Academy) | ~2–4 per month | https://www.youtube.com/watch?v=3TO_yjh4L_I · https://www.youtube.com/watch?v=-vLeXjO3aKU · https://www.youtube.com/watch?v=_1ZIgz9FOno |
| U9 | Customer story film | A marquee customer | YouTube, /customers, LinkedIn, sales decks | 2–5 min documentary film (often a 2-part pair), customer page with quote and logo | "&lt;Metaphor title&gt;: How &lt;Company&gt; &lt;does X&gt; with Notion" → people and craft → workflow in Notion → outcome | ~2–4 per month in 2026 | https://www.youtube.com/watch?v=RJvD_VBz8s4 · https://www.youtube.com/watch?v=1vaK57L5IMM · https://www.youtube.com/watch?v=KFa-X6RuEA4 |
| U10 | Interview series (Pioneers → First Block) | Editorial calendar | Podcast (Apple, Spotify), YouTube, blog | Audio episode (30–60 min), video version, blog summary, pull-quote cards | "First Block: Interview with &lt;Name&gt;, &lt;Role&gt; of &lt;Company&gt;" → firsts of the journey | ~1 per month | https://anchor.fm/s/586e6d8/podcast/rss · https://www.notion.com/blog/first-block-with-ivan-zhao-simon-last · https://www.youtube.com/watch?v=ZMrjvxCIPpY |
| U11 | Engineering deep dive | An infrastructure achievement | Blog (Tech), HN, X | Long-form post (2–4K words) with diagrams | Problem at our scale → approach → results → "we're hiring" | ~1–2 per month | https://www.notion.so/blog/sharding-postgres-at-notion · https://www.notion.so/blog/data-model-behind-notion · https://www.notion.so/blog/how-we-sped-up-notion-in-the-browser-with-wasm-sqlite |
| U12 | Brand campaign | A positioning shift (all-in-one → connected → AI workspace → agents) | OOH billboards, YouTube film, social, blog "thinking behind" | Illustrated billboards (Muradov), 30–90 s film, a behind-the-scenes blog post | Imperative headline ("Think it. Make it.") + illustration + logo | About 1 per year | https://www.notion.com/blog/the-thinking-behind-our-latest-brand-campaign · https://www.youtube.com/watch?v=vG_LQo0wOGg · https://the-brandidentity.com/project/how-buck-gave-notions-ai-assistant-a-hand-drawn-personality |
| U13 | Localization launch | A new language ships | Release note, regional social account (e.g. @notionhq_kr), wire release | Release entry with a flag emoji, localized site and templates | "Notion in &lt;Language&gt; 🇯🇵🎊" → community thanks → what's localized | Every 6–12 months | https://www.notion.com/releases/2020-08-10 · https://www.notion.com/releases/2021-10-12 · https://www.notion.com/releases/2025-07-22 |
| U14 | First-party template or skill listing | Each feature or launch (e.g. the AI Skills category created 2026-03-08) | Marketplace, release note links, help | Listing (§4 fields): cover 1920×1200, mobile 1125×2436, screenshots, preview page | Name → one-sentence benefit → body → "View template" | Continuous (571 listings by @notion) | https://www.notion.com/templates/notion-habit-tracker · https://www.notion.com/@notion · https://www.notion.com/templates |
| U15 | Community program page | Launch or refresh of a program | Public Notion page, community hub, newsletter form | About, benefits (bullets), requirements (numbered), how to join, FAQ toggles, photos | Welcome quote → what members do → benefits vs. responsibilities → apply CTA | Updated yearly | https://www.notion.so/Notion-Ambassador-Program-45448f9b8e704c7bab254bd505c4717c · https://www.notion.com/champions · https://www.notion.com/partners |

---

## 7. The reveal sequence

**From nothing to launched (2013 → 2018):**

| # | Step | What | Channels | Gap from previous (days) |
|---|---|---|---|---|
| 1 | Quiet founding | Company plus GitHub org (2013-06-23); seed round; builds in private | GitHub | – |
| 2 | Accidental first listing | A hunter posts the early editor on Product Hunt (2015-03-26, 10 upvotes) | Product Hunt | 641 |
| 3 | Gate | notion.so becomes an early-access gate (2015-07-13) | website | 109 |
| 4 | Accidental beta reveal | "Notion Beta" (0.5) hunted, 554 upvotes. The founder replies in the thread and promises 1.0 (2015-09-14) | Product Hunt | 63 |
| 5 | Login-gated app | Working app behind login (2016-01-23) | website | 131 |
| 6 | Build in public | Public dated changelog starts (2016-03-19), then about 1 entry a week | What's New page | 56 |
| 7 | Positioning | Public homepage title aimed at "modern thinkers" (2016-06-16) | website | 89 |
| 8 | Launch 1.0 | Web plus Mac app on Product Hunt, hunted by a well-known investor (Naval Ravikant); maker story in the comments (2016-08-09) | Product Hunt, website, changelog | 54 |
| 9 | Social proof | Golden Kitty nomination (2016-12-02) | Product Hunt | 115 |
| 10 | Relaunch 2.0 | Databases plus the "all-in-one workspace" tagline; #1 on Product Hunt; site title changes the same day (2018-03-20) | Product Hunt, website, changelog | 473 |
| 11 | Content engine | YouTube channel (2018-06-02) and podcast (2018-08-03) | YouTube, podcast | 74 (then 62 to the podcast) |
| 12 | Organic peak | HN front page, 970 pts (2019-01-14) | Hacker News | 164 |

**How later launches reuse the shape.** Every major launch runs a compressed version of the same arc. An asset arrives first (an acquisition or an alpha), then a public teaser (a waitlist or a "sneak peek"), then launch day, then follow-up micro-releases:
1. Acquire or build in private, or run a public alpha.
2. Tease: a waitlist page or a "sneak peek" section in the monthly release.
3. Launch day, all at once:
   - a numbered release note ("Notion X.Y: …") plus email
   - a Product Hunt post (the same day or +1)
   - an X post from @NotionHQ plus the founder's post
   - a blog explainer and a YouTube demo (keynote uploaded about 5 days after an event)
   - a first-party template or skill listing
4. Follow-ups: micro-releases (platform ports, admin controls, new models), localization, customer films.

| Launch | Asset / teaser | Launch | Follow-ups | Gaps (days) |
|---|---|---|---|---|
| Notion AI | Waitlist plus PH alpha, 2022-11-16 | GA "Notion 2.21: Notion AI, for everyone", 2023-02-22 | Q&A 2023-11-14 → new Notion AI 2024-09-25 → AI Meeting Notes / Enterprise Search 2025-05-13 → 3.0 Agents 2025-09-18 → Custom Agents 2026-02-24 | 98 → 265 → 316 → 230 → 128 → 159 |
| Calendar | Cron acquired 2022-06-09 | Notion Calendar 2024-01-17 (PH +1 day) | Android 2024-07-17; agent calendar tools 2026-07-16 | 587 → 182 |
| Mail | Skiff acquired 2024-02-09; waitlist at Make with Notion 2024-10-24 | Notion Mail 2025-04-15 (release plus PH the same day) | Mail & Calendar settings tab 2026-04-17 | 258 → 173 |
| Forms | "Sneak peek at forms" 2024-08-13 | Forms at Make with Notion 2024-10-24 | Conditional logic 2025-03-26; "Agent can build forms" 2025-12-03 | 72 → 153 |
| Sites | – | Notion Sites 2024-06-25 (release plus PH the same day) | – | 0 |
| Agents (3.0) | "Soon: Custom Agents" inside the 3.0 note | 3.0 at Make with Notion 2025-09-18 (release, founder X post, TechCrunch) | Keynote video 2025-09-23; 3.1 2025-11-17; Custom Agents 2026-02-24 (PH +1 day) | 5 → 60 → 159 |

**Takeaways for the blueprint:**
- The first reveal was unplanned: two premature Product Hunt listings came before the product was ready. Notion turned them into a promise ("coming in 1.0") and a public changelog.
- The relaunch framed as "the real 1.0" drove the traction.
- From then on, every launch is **release note + Product Hunt + social on the same day**, preceded by a **waitlist or sneak peek 2–6 months earlier** and followed by weekly micro-updates.

---

## 8. Gaps (not verified)

- **Walled social platforms:**
  - X: bio, join date, exact follower count, posting cadence.
  - Instagram, TikTok, Facebook, Threads: bios and counts come from search snippets (`~`); creation dates are unknown; cadences are estimates.
  - Reddit and Discord are community-run; their counts are snippets.
- **academy.notion.com** returned HTTP 403. The Academy structure comes from the help page and search snippets.
- **Media Kit contents** (zip files) were not opened, per the no-download rule. The logo variants and illustration set are unverified.
- **Funding dates:** the seed month (2013) and the exact 2019 round date are unknown. The 2026 tender figures ($270M, GIC, 2026-01-26) come from secondary sources.
- **1M-user date:** Wikipedia says Sep 2019; Ivan Zhao says 2020.
- **Pre-2015 product:** the original 2013–2014 tool is invisible in Wayback; notion.so is first captured 2015-07-13.
- **The 2015 YouTube channel "Notion"** (UC7VipXG_qo4gWVkYLxBbMjA) is not confirmed as Notion Labs'.
- **2015-03-26 PH post:** "Capture and organize knowledge collaboratively" is attributed to Notion Labs from context (a text editor) and its date comes from page metadata. The attribution is plausible, but the "accidentally hunted" post Ivan refers to is the 2015-09-14 one.
- **Domain switch:** the date notion.so became notion.com canonical is unknown.
- **Newsletter:** no standalone signup page or archive was found. The release email is inferred from the release copy and asset names.
- **Merch:** no public store was found. Swag exists only as a program perk.
- **Make with Notion 2025 date:** 2025-09-18 at Fort Mason comes from event-listing snippets `~`. The keynote upload date (2025-09-23) is verified.
- **2023+ logo evolution:** no official logo change was found. The AI face and Notion Faces are additions; a secondary source says the core logo is unchanged since 2016.
- **Blog history before 2021:** its earliest Wayback capture is 2021-03-02; the earlier blog location is unknown. Engineering posts from 2021 at /blog are linked from HN.
- **Search cap:** partway through, the session hit its WebSearch cap (200 of 200), so the remaining gaps were not searched further.

---

## Appendix

```yaml
# blueprint-input
company: Notion
observed_at: "2026-09-29"
channels:
  - {platform: website, handle: notion.com, url: "https://www.notion.com/", since: "2015-07-13", followers: null, bio: "The AI workspace that works for you.", cadence: "hero re-cut per major launch (2-4/yr)"}
  - {platform: releases, handle: /releases, url: "https://www.notion.com/releases", since: "2016-03-19", followers: null, bio: "Product improvements, updates, and fixes.", cadence: "2020-2025 ~1-2/mo; 2026 ~5-6/mo (50 by 2026-09-15)"}
  - {platform: blog, handle: "Tools & Craft", url: "https://www.notion.com/blog", since: "2021-03-02 (earliest capture)", followers: null, bio: "Thoughts on the future of work, from the people and teams creating it.", cadence: "~6-10/mo (estimate)"}
  - {platform: help, handle: /help, url: "https://www.notion.com/help", since: unknown, followers: null, bio: "Hi, how can we help you?", cadence: continuous}
  - {platform: academy, handle: academy.notion.com, url: "https://academy.notion.com/", since: unknown, followers: null, bio: null, cadence: "paths + badges; 6 new languages 2026-03-19"}
  - {platform: marketplace, handle: /templates, url: "https://www.notion.com/templates", since: "2019-07-03 (gallery); ~2023-05 (creator profiles)", followers: null, bio: "Choose from 30,000+ Notion templates", cadence: "daily (community); per-launch (Notion)"}
  - {platform: integrations, handle: /integrations, url: "https://www.notion.com/integrations", since: "2022-03-02", followers: null, bio: "Extend Notion with connections that sync your data, automate workflows, and connect your favorite tools.", cadence: weekly}
  - {platform: press_kit, handle: Media Kit, url: "https://www.notion.so/Media-Kit-205535b1d9c4440497a3d7a2ac096286", since: unknown, followers: null, bio: "Here are links to our logo, product screenshots, San Francisco Headquarters office photos, and illustrations.", cadence: "screenshots refreshed (Apr 2026 set)"}
  - {platform: github, handle: makenotion, url: "https://github.com/makenotion", since: "2013-06-23", followers: 3059, bio: "We shape our tools, thereafter our tools shape us", cadence: "~1 new repo/mo (2025-26)"}
  - {platform: youtube, handle: "@Notion", url: "https://www.youtube.com/@Notion", since: "2018-06-02", followers: 349000, bio: "Notion is the AI workspace where teams and AI agents get more done together.", cadence: "~5/mo"}
  - {platform: x, handle: "@NotionHQ", url: "https://x.com/NotionHQ", since: "<=2017-06", followers: "~513700 (snippet)", bio: unknown, cadence: "~30-60/mo (estimate)"}
  - {platform: linkedin, handle: notionhq, url: "https://www.linkedin.com/company/notionhq", since: unknown, followers: 1122450, bio: "Notion blends your everyday work tools into one.", cadence: "~20-40/mo (estimate)"}
  - {platform: facebook, handle: NotionHQ, url: "https://www.facebook.com/NotionHQ/", since: unknown, followers: "~62000 (snippet)", bio: "The connected workspace for your docs, projects, and knowledge.", cadence: low}
  - {platform: instagram, handle: notionhq, url: "https://www.instagram.com/notionhq/", since: unknown, followers: "~481000 (snippet)", bio: "The AI workspace that works while you sleep.", cadence: "~6-10/mo (estimate)"}
  - {platform: tiktok, handle: notionhq, url: "https://www.tiktok.com/@notionhq", since: "<=2023-01-13", followers: "~143400 (snippet)", bio: "The connected workspace for your docs, projects, and knowledge.", cadence: "~4-8/mo (estimate)"}
  - {platform: threads, handle: notionhq, url: "https://www.threads.com/@notionhq", since: unknown, followers: unknown, bio: unknown, cadence: unknown}
  - {platform: discord, handle: "Notion Community (community-run)", url: "https://discord.com/invite/notion-community-967943233105702922", since: "2022-04-25", followers: "~11435 (snippet)", bio: "public, community discord server led by Notion Ambassadors", cadence: continuous}
  - {platform: reddit, handle: r/Notion (community-run), url: "https://www.reddit.com/r/Notion/", since: unknown, followers: "~472000 (snippet)", bio: null, cadence: continuous}
  - {platform: producthunt, handle: notion, url: "https://www.producthunt.com/products/notion", since: "2015-03-26", followers: 19000, bio: null, cadence: "1-4 launches/yr"}
  - {platform: hackernews, handle: null, url: "https://hn.algolia.com/?query=notion.so", since: "2017-06-16", followers: null, bio: null, cadence: "organic; few big threads/yr"}
  - {platform: podcast, handle: "Notion Podcast", url: "https://podcasts.apple.com/us/podcast/notion-podcast/id1422389039", since: "2018-08-03", followers: null, bio: "Candid conversations with the people shaping the world of technology", cadence: "~1/mo (34 episodes)"}
  - {platform: events, handle: "Make with Notion", url: "https://www.notion.com/blog/conference-product-releases", since: "2024-10-24", followers: null, bio: null, cadence: yearly}
  - {platform: community_programs, handle: "Ambassadors / Champions / Partners", url: "https://www.notion.so/Notion-Ambassador-Program-45448f9b8e704c7bab254bd505c4717c", since: unknown, followers: null, bio: "The Notion Ambassador Program brings together our most passionate and creative builders from all over the world.", cadence: "cohorts (paused globally 2026)"}
  - {platform: email, handle: "What's New email", url: "https://www.notion.com/releases", since: unknown, followers: null, bio: null, cadence: "~1/mo"}
identity:
  name: Notion
  legal_name: "Notion Labs, Inc."
  handles: {x: NotionHQ, instagram: notionhq, tiktok: notionhq, threads: notionhq, linkedin: notionhq, facebook: NotionHQ, youtube: "@Notion", github: makenotion, marketplace: "@notion", email_domain: makenotion.com, domains: [notion.so, notion.com, notion.site, ntn.so]}
  taglines:
    - {date: "2015-09-14", text: "An expressive and collaborative document editor"}
    - {date: "2016-06-16", text: "A tool for notes, documents, and knowledge bases – made for modern thinkers."}
    - {date: "2016-08-09", text: "Docs, wikis, tasks – a minimal & unified workspace for teams"}
    - {date: "2016-10-15", text: "Docs, wikis, tasks, seamlessly in one. A unified workspace for modern teams."}
    - {date: "2017-06-16", text: "Docs, Wikis, Tasks. Seamlessly in one."}
    - {date: "2018-03-20", text: "The all-in-one workspace for your notes, tasks, wikis, and databases."}
    - {date: "~2022", text: "The connected workspace for your docs, projects, and knowledge."}
    - {date: "2024-07-10", text: "Think it. Make it."}
    - {date: "2026", text: "The AI workspace that works for you."}
    - {date: "2026", text: "Where teams and agents Think together."}
  short_description: "Capture context, find answers, and automate tasks with AI built for your team."
  long_description: "Notion is the AI workspace where teams and AI agents get more done together. Assign the task, and your Agents will get to work alongside your team in one connected workspace."
  terminology:
    - {term: block, meaning: "atomic content unit; any block can contain blocks"}
    - {term: page, meaning: "a block that holds blocks; nests infinitely"}
    - {term: database, meaning: "collection of pages with typed properties"}
    - {term: view, meaning: "table/board/timeline/calendar/gallery/list/chart/dashboard/map/form lens on a database"}
    - {term: property, meaning: "typed field on a database page"}
    - {term: relation, meaning: "link between databases"}
    - {term: rollup, meaning: "aggregation across a relation"}
    - {term: linked database, meaning: "a view of a database embedded elsewhere"}
    - {term: synced block, meaning: "content mirrored across pages"}
    - {term: template, meaning: "reusable page/database starting point"}
    - {term: workspace, meaning: "the tenant: a team's or person's whole Notion"}
    - {term: teamspace, meaning: "department area inside a workspace"}
    - {term: Home / Library, meaning: "personal start surface / home for everything not pinned"}
    - {term: connections, meaning: "integrations and link previews"}
    - {term: Notion AI, meaning: "AI layer across the workspace"}
    - {term: Agent, meaning: "personal AI agent acting inside Notion (3.0)"}
    - {term: Custom Agent, meaning: "team agent with triggers and schedules (3.3)"}
    - {term: skills, meaning: "reusable AI instructions (3.7)"}
    - {term: Workers, meaning: "code running on Notion infra (Developer Platform)"}
    - {term: AI Meeting Notes, meaning: "transcription and summaries"}
    - {term: Enterprise Search, meaning: "answers across connected apps"}
    - {term: Notion Calendar, meaning: "calendar app (ex-Cron)"}
    - {term: Notion Mail, meaning: "email client (ex-Skiff)"}
    - {term: Notion Sites, meaning: "publish pages as websites"}
    - {term: Forms, meaning: "form view feeding a database"}
    - {term: Marketplace, meaning: "template store with creator profiles"}
    - {term: Notion credits, meaning: "usage currency for agents/Workers"}
    - {term: Notion Faces, meaning: "hand-drawn avatar creator"}
    - {term: Ambassadors / Champions, meaning: "external teachers / in-company admins community programs"}
  colors:
    - {name: white (background-base), hex: "#ffffff"}
    - {name: black, hex: "#000000"}
    - {name: gray-100, hex: "#f9f9f8"}
    - {name: gray-200, hex: "#f6f5f4"}
    - {name: gray-500, hex: "#78736f"}
    - {name: gray-900, hex: "#191918"}
    - {name: blue-600 (primary action), hex: "#0075de"}
    - {name: blue-500, hex: "#097fe8"}
    - {name: red-500, hex: "#f64932"}
    - {name: orange-500, hex: "#ff6d00"}
    - {name: yellow-500, hex: "#ffb110"}
    - {name: green-500, hex: "#1aae39"}
    - {name: teal-400 (surface accent), hex: "#2a9d99"}
    - {name: purple-500, hex: "#9849e8"}
    - {name: pink-500, hex: "#ff64c8"}
    - {name: brown-500, hex: "#9c7054"}
    - {name: campaign agents-launch blue, hex: "#455dd3"}
    - {name: campaign agents-launch cream, hex: "#fefcd5"}
  typography: "NotionInter (custom Inter cut) primary; Lyon Text serif for editorial/quotes; iA Writer Mono for code; Permanent Marker accent (campaign, unverified use); Noto Sans Hebrew/Arabic for RTL locales"
  theme: "light-first marketing site on white + warm grays; product has light/dark and high-contrast (2026-07-30) modes"
  logo: "black-outlined isometric cube with a bold serif N on its face + 'Notion' wordmark; black on white; core mark stable since ~2016; secondary animated marks since 2024: hand-drawn AI face (BUCK x Muradov, Rive) and Notion Faces avatars"
  illustration: "Roman Muradov (art director): minimalist gestural black-and-white pencil/ink characters, light strokes, Steinberg/Cubism/Rube-Goldberg influences; 2024 campaign adds bold primaries for OOH; motion = hand-made cel animation; product GIFs in releases"
  voice: "plain, warm, candid, lightly playful; emoji-tagged release titles; 'Notion X.Y: <benefit>' formula; craft/tools vocabulary; reverence for computing pioneers (McLuhan, Engelbart, Kay, Nelson)"
content:
  sections:
    - {id: about, title: "Why we built Notion", structure: "clutter today -> history of tools -> vision gap -> building blocks -> company/careers -> press logos; B&W illustrations"}
    - {id: home, title: "Home", structure: "nav -> hero (headline, subhead, 2 CTAs, video) -> logo wall -> 3 pillars -> use-case cards -> testimonials -> quote -> footer (22 languages)"}
    - {id: help, title: "Help Center", structure: "search -> 14 categories -> guides by team -> What's New rail -> support; article = breadcrumb, title, video, intro, TOC, H2 sections with images+callouts, Up next, feedback"}
    - {id: academy, title: "Notion Academy", structure: "learning paths -> badges (Essentials, Workflows, Advanced) -> Certified Admin proctored exam; valid 2 years; multilingual"}
    - {id: templates, title: "Marketplace", structure: "categories (348), collections, creators (/@handle), listing pages (see app_store_listing)"}
    - {id: integrations, title: "Connections gallery", structure: "filters: category, connection type, developer; sort; card = logo, name, type, developer badge, adoption, price"}
    - {id: blog, title: "Tools & Craft", structure: "categories Notion HQ / For Teams / Inspiration / Pioneers / Tech / First Block; card = cover, category, title, author, excerpt"}
    - {id: releases, title: "What's New", structure: "date -> 'Notion X.Y: headline' -> hook intro -> H3 feature + GIF/JPG + paragraph (x4-10) -> recent releases grid; mirrored as email"}
    - {id: press, title: "Media Kit", structure: "public Notion page: intro line, 4 zip files (logo, illustrations, screenshots, office photos), press email callout"}
    - {id: community, title: "Community programs", structure: "public Notion pages: about, what members do, benefits, requirements, how to join, FAQ toggles, photos"}
    - {id: vision, title: "Manifesto", structure: "tools-shape-us thesis; Pioneers series; building blocks for software; 1.0/2.0 tools -> 3.0 agents"}
app_store_listing:
  fields:
    - {name: title_tag, type: string, example: "Habit tracker 2026 Template | Notion Marketplace"}
    - {name: name, type: string, example: "Habit tracker"}
    - {name: slug, type: string, example: "notion-habit-tracker"}
    - {name: emoji, type: emoji, example: "📝"}
    - {name: description, type: "string<=160", example: "Build and maintain healthy habits with this automated habit tracker template."}
    - {name: body, type: rich_text, example: "Keep yourself accountable by tracking your habits everyday. ..."}
    - {name: cover_image, type: "image 1920x1200", example: "desktop.jpg"}
    - {name: mobile_image, type: "image 1125x2436", example: "mobile.jpg"}
    - {name: screenshots, type: "image[] 2048x1280", example: "1 desktop screenshot"}
    - {name: mobile_screenshots, type: "image[] 750x2668", example: "1 mobile screenshot"}
    - {name: preview_url, type: url, example: "https://notion.notion.site/Habit-tracker-c6ab9f9dcde5407bbc63f46a9e621832"}
    - {name: source_block_id, type: uuid, example: "c6ab9f9d-cde5-407b-bc63-f46a9e621832"}
    - {name: made_by, type: "enum(notion|community)", example: notion}
    - {name: creator, type: "ref(profile: name, handle, avatar, bio, badges, template_count, links, contact_email)", example: "Notion @notion, Recommended creator, 571 templates"}
    - {name: price, type: "money (USD; Stripe Connect for paid)", example: 0}
    - {name: category, type: ref, example: "Habit Tracking"}
    - {name: tags, type: "ref[]", example: "2 direct / 6 total"}
    - {name: rating, type: "float + star histogram", example: "4.59 (1823 ratings: 1400/253/82/24/64)"}
    - {name: installation_count, type: int, example: 218666}
    - {name: reviews, type: "object[] (title, body, rating, author, created, creator_response)", example: "rating 4, 'very good'"}
    - {name: created_at, type: date, example: "2023-03-23"}
    - {name: last_updated_at, type: date, example: "2025-07-23"}
    - {name: published_version, type: int, example: 33}
    - {name: locales, type: "enum[]", example: "en-US + 19"}
    - {name: related_templates, type: "ref[]", example: "More by Notion (3), Similar (3)"}
    - {name: collections, type: "ref[]", example: "Your productivity hub; Top 10 most popular; Healthy habits made easy"}
    - {name: ctas, type: "action[]", example: "View template; Share (X, LinkedIn, Facebook, Email); Report template; Become a creator"}
    - {name: og_image, type: "generated image", example: "/front-api/og-image/templates/notion-habit-tracker"}
    - {name: structured_data, type: "JSON-LD Product", example: "offers + aggregateRating"}
timeline:
  - {date: "2013-06-23", stage: pre-launch, channels: [github], media: org, title: "makenotion org created", url: "https://github.com/makenotion"}
  - {date: "2015-03-26", stage: pre-launch, channels: [producthunt], media: post, title: "Notion: Capture and organize knowledge collaboratively", url: "https://web.archive.org/web/20160319120303/http://www.producthunt.com/posts/notion-2"}
  - {date: "2015-07-13", stage: teaser, channels: [website], media: landing, title: "early-access.notion.so gate", url: "https://web.archive.org/web/20150713213038/https://www.notion.so/"}
  - {date: "2015-09-14", stage: reveal, channels: [producthunt], media: post, title: "Notion Beta (0.5) - An expressive and collaborative document editor", url: "https://web.archive.org/web/20170511144729/https://www.producthunt.com/posts/notion-4"}
  - {date: "2016-03-19", stage: release, channels: [changelog], media: page, title: "What's New changelog begins", url: "https://www.notion.so/What-s-New-157765353f2c4705bd45474e5ba8b46c"}
  - {date: "2016-06-16", stage: reveal, channels: [website], media: page, title: "A tool for notes, documents, and knowledge bases – made for modern thinkers.", url: "https://web.archive.org/web/20160616122804/https://www.notion.so/"}
  - {date: "2016-08-09", stage: launch, channels: [producthunt, website], media: post, title: "Notion 1.0 Web + Mac App", url: "https://web.archive.org/web/20170415062308/https://www.producthunt.com/posts/notion-1-0-web-mac-app"}
  - {date: "2016-12-02", stage: milestone, channels: [producthunt], media: nomination, title: "Golden Kitty nominee - Desktop Product of the Year", url: "https://web.archive.org/web/20170511225411/https://www.producthunt.com/posts/notion-1-0-web-mac-app-2"}
  - {date: "2017-06-16", stage: community, channels: [hackernews], media: post, title: "Notion.so – A unified and collaborative workspace", url: "https://news.ycombinator.com/item?id=14571454"}
  - {date: "2018-03-20", stage: launch, channels: [producthunt, website, changelog], media: post, title: "Notion 2.0 - The all-in-one workspace", url: "https://hunted.space/dashboard/122747"}
  - {date: "2018-06-11", stage: community, channels: [youtube], media: video, title: "Tools & Craft Podcast: Backstage with Andy Hertzfeld", url: "https://www.youtube.com/watch?v=4QDQeykT4dY"}
  - {date: "2018-08-03", stage: community, channels: [podcast], media: audio, title: "Pioneers: Andy Hertzfeld on building the Macintosh", url: "https://anchor.fm/s/586e6d8/podcast/rss"}
  - {date: "2019-01-14", stage: milestone, channels: [hackernews], media: post, title: "Notion – All-in-one workspace (970 pts)", url: "https://news.ycombinator.com/item?id=18904648"}
  - {date: "2019-12-06", stage: release, channels: [youtube], media: video, title: "Using database views", url: "https://www.youtube.com/watch?v=-vLeXjO3aKU"}
  - {date: "2020-04-01", stage: funding, channels: [press], media: article, title: "$50M at $2B (Index)", url: "https://techcrunch.com/2020/04/01/notion-hits-2-billion-valuation-in-new-raise"}
  - {date: "2020-05-19", stage: launch, channels: [releases, hackernews], media: article, title: "Notion 2.8, now free for personal use", url: "https://www.notion.com/releases/2020-05-19"}
  - {date: "2021-05-13", stage: launch, channels: [releases, hackernews], media: article, title: "Start building with the API", url: "https://www.notion.com/releases/2021-05-13"}
  - {date: "2021-09-08", stage: acquisition, channels: [releases], media: article, title: "Acquiring Automate.io", url: "https://www.notion.com/releases/2021-09-08"}
  - {date: "2021-10-08", stage: funding, channels: [press], media: article, title: "$275M at $10B (Coatue, Sequoia)", url: "https://siliconangle.com/2021/10/08/productivity-startup-notion-valued-10b-latest-275m-funding-round/"}
  - {date: "2022-06-09", stage: acquisition, channels: [blog, press], media: article, title: "Notion acquires Cron", url: "https://www.notion.com/blog/notion-acquires-cron"}
  - {date: "2022-11-16", stage: pre-launch, channels: [website, producthunt, hackernews], media: post, title: "Notion AI waitlist / alpha", url: "https://news.ycombinator.com/item?id=33623201"}
  - {date: "2023-02-22", stage: launch, channels: [releases], media: article, title: "Notion 2.21: Notion AI, for everyone", url: "https://www.notion.com/releases/2023-02-22"}
  - {date: "2024-01-17", stage: launch, channels: [releases, producthunt], media: article, title: "Notion 2.37: Notion Calendar", url: "https://www.notion.com/releases/2024-01-17"}
  - {date: "2024-06-25", stage: launch, channels: [releases, producthunt], media: article, title: "Notion 2.42: Introducing Notion Sites", url: "https://www.notion.com/releases/2024-06-25"}
  - {date: "2024-07-10", stage: rebrand, channels: [ooh, blog], media: image, title: "Think it. Make it.", url: "https://www.notion.com/blog/the-thinking-behind-our-latest-brand-campaign"}
  - {date: "2024-07-22", stage: milestone, channels: [x], media: post, title: "From our first 1,000 users → to 100 million!", url: "https://x.com/NotionHQ/status/1815513728315699586"}
  - {date: "2024-10-24", stage: event, channels: [event, livestream, blog, releases], media: livestream, title: "Make with Notion 2024 (Forms, Mail waitlist, layouts)", url: "https://www.notion.com/blog/conference-product-releases"}
  - {date: "2025-04-15", stage: launch, channels: [releases, producthunt], media: article, title: "Notion 2.50: Meet Notion Mail", url: "https://www.notion.com/releases/2025-04-15"}
  - {date: "2025-05-13", stage: launch, channels: [releases, producthunt], media: article, title: "Notion 2.51: AI Meeting Notes, Enterprise Search", url: "https://www.notion.com/releases/2025-05-13"}
  - {date: "2025-09-18", stage: launch, channels: [event, releases, x, press], media: livestream, title: "Notion 3.0: Agents (Make with Notion 2025)", url: "https://www.notion.com/releases/2025-09-18"}
  - {date: "2025-09-23", stage: event, channels: [youtube], media: video, title: "Make with Notion 2025: Product Launch Keynote", url: "https://www.youtube.com/watch?v=KZ3hAy_XZwI"}
  - {date: "2026-02-24", stage: launch, channels: [releases, x, producthunt], media: article, title: "Notion 3.3: Custom Agents", url: "https://www.notion.com/releases/2026-02-24"}
  - {date: "2026-05-13", stage: launch, channels: [releases, producthunt], media: article, title: "3.5: Notion Developer Platform", url: "https://www.notion.com/releases/2026-05-13"}
  - {date: "2026-08-04", stage: rebrand, channels: [youtube], media: video, title: "AI Can't Replace Teamwork", url: "https://www.youtube.com/watch?v=vG_LQo0wOGg"}
  - {date: "2026-09-15", stage: release, channels: [releases, email], media: article, title: "Notion 3.7: Agent skills for your whole team", url: "https://www.notion.com/releases/2026-09-15"}
units:
  - {id: U1, name: numbered_release_note, trigger: "feature batch ready", channels: [releases, email, x, linkedin, in_app], assets: [{kind: cover_image, spec: "16:9", count: 1}, {kind: gif_or_jpg, spec: "3840w", count: "4-10"}, {kind: section, spec: "H3 + 1-3 paragraphs", count: "4-10"}], copy: "date -> 'Notion X.Y: benefit' -> hook -> lineage/promise -> H3 feature + visual + paragraph + help link (xN) -> recent releases", cadence: "every 4-8 weeks"}
  - {id: U2, name: micro_release, trigger: "single feature or new AI model", channels: [releases, x], assets: [{kind: cover_image, spec: "16:9", count: 1}, {kind: paragraph, spec: "1-2", count: 1}], copy: "'<Thing>, now in Notion' -> what -> why", cadence: "2-5/week (2026)"}
  - {id: U3, name: producthunt_launch, trigger: "new product surface", channels: [producthunt, x, linkedin], assets: [{kind: tagline, spec: "<=60 chars", count: 1}, {kind: gallery, spec: "images+video", count: "4-8"}, {kind: maker_comment, spec: "founder story", count: 1}], copy: "'<Product>: <promise>' -> maker comment (why, what, ask)", cadence: "1-4/yr"}
  - {id: U4, name: annual_keynote_event, trigger: "yearly launch batch", channels: [event, livestream, youtube, blog, releases, producthunt], assets: [{kind: keynote_video, spec: "30-60 min 16:9", count: 1}, {kind: recap_blog, spec: "'Everything we launched at...'", count: 1}, {kind: release_note, spec: "same day", count: 1}, {kind: session_videos, spec: playlist, count: "5-20"}], copy: "problem -> mission -> new ways to build/work/share -> CTA (waitlist/demo)", cadence: yearly}
  - {id: U5, name: waitlist_teaser, trigger: "product not yet GA", channels: [landing_page, releases, event], assets: [{kind: landing_page, spec: "signup form", count: 1}, {kind: demo_gif, spec: "short", count: 1}], copy: "coming soon -> single promise -> 'Sign up now to join the waitlist'", cadence: "1-2/yr; GA after 72-173 days"}
  - {id: U6, name: milestone_post, trigger: "user/community/funding milestone", channels: [x, blog, linkedin], assets: [{kind: image_card, spec: "1200x675", count: 1}, {kind: founder_letter, spec: "800-1500 words", count: 1}], copy: "'From <first> -> to <now>!' -> thanks -> story -> next", cadence: "1-2/yr"}
  - {id: U7, name: acquisition_announcement, trigger: "deal closes", channels: [blog, wire, releases], assets: [{kind: blog_post, spec: "both logos", count: 1}, {kind: press_release, spec: wire, count: 1}], copy: "'Notion acquires <X>, the <category>' -> why -> what happens to users -> vision", cadence: "~1/yr"}
  - {id: U8, name: quick_tip_video, trigger: "feature needs education", channels: [youtube, tiktok, instagram, help], assets: [{kind: video, spec: "1-3 min 16:9 + 9:16 cut", count: 1}, {kind: thumbnail, spec: "16:9", count: 1}], copy: "'What is / How to <feature>' -> 3-step demo -> learn more", cadence: "2-4/mo"}
  - {id: U9, name: customer_story_film, trigger: "marquee customer", channels: [youtube, customers_page, linkedin], assets: [{kind: film, spec: "2-5 min 16:9, often 2 parts", count: "1-2"}, {kind: customer_page, spec: "quote + logo", count: 1}], copy: "'<Metaphor>: How <Company> <does X> with Notion' -> people/craft -> workflow -> outcome", cadence: "2-4/mo"}
  - {id: U10, name: interview_series, trigger: "editorial calendar", channels: [podcast, youtube, blog], assets: [{kind: audio, spec: "30-60 min", count: 1}, {kind: video, spec: "16:9", count: 1}, {kind: blog_summary, spec: "article", count: 1}], copy: "'First Block: Interview with <Name>, <Role> of <Company>'", cadence: "~1/mo"}
  - {id: U11, name: engineering_deep_dive, trigger: "infra achievement", channels: [blog, hackernews, x], assets: [{kind: article, spec: "2-4K words + diagrams", count: 1}], copy: "problem at scale -> approach -> results -> hiring", cadence: "1-2/mo"}
  - {id: U12, name: brand_campaign, trigger: "positioning shift", channels: [ooh, youtube, social, blog], assets: [{kind: billboard, spec: "illustrated (Muradov)", count: "several"}, {kind: film, spec: "30-90 s", count: 1}, {kind: bts_blog, spec: article, count: 1}], copy: "imperative headline + illustration + logo", cadence: "~1/yr"}
  - {id: U13, name: localization_launch, trigger: "new language ships", channels: [releases, regional_social, wire], assets: [{kind: release_note, spec: "flag emoji title", count: 1}], copy: "'Notion in <Language> <flag>' -> community thanks -> scope", cadence: "every 6-12 months"}
  - {id: U14, name: first_party_listing, trigger: "each feature/launch", channels: [marketplace, releases, help], assets: [{kind: cover, spec: "1920x1200", count: 1}, {kind: mobile_cover, spec: "1125x2436", count: 1}, {kind: screenshots, spec: "2048x1280 + 750x2668", count: "1-4"}, {kind: preview_page, spec: "notion.site", count: 1}], copy: "name -> one-sentence benefit -> body -> 'View template'", cadence: continuous}
  - {id: U15, name: community_program_page, trigger: "program launch/refresh", channels: [public_notion_page, community_hub], assets: [{kind: page, spec: "about/benefits/requirements/how-to-join/FAQ", count: 1}, {kind: photos, spec: "meetup collage", count: "3-6"}], copy: "welcome quote -> what members do -> benefits vs responsibilities -> apply", cadence: yearly}
reveal_sequence:
  - {step: 1, what: "quiet founding; GitHub org; seed", channels: [github], gap_days_from_previous: null}
  - {step: 2, what: "accidental first Product Hunt listing", channels: [producthunt], gap_days_from_previous: 641}
  - {step: 3, what: "early-access gate on the domain", channels: [website], gap_days_from_previous: 109}
  - {step: 4, what: "accidental beta (0.5) reveal; founder promises 1.0 in the thread", channels: [producthunt], gap_days_from_previous: 63}
  - {step: 5, what: "login-gated working app", channels: [website], gap_days_from_previous: 131}
  - {step: 6, what: "public dated changelog (build in public)", channels: [changelog], gap_days_from_previous: 56}
  - {step: 7, what: "public positioning title", channels: [website], gap_days_from_previous: 89}
  - {step: 8, what: "1.0 launch on Product Hunt, hunted by a known investor; web + Mac", channels: [producthunt, website, changelog], gap_days_from_previous: 54}
  - {step: 9, what: "award nomination (social proof)", channels: [producthunt], gap_days_from_previous: 115}
  - {step: 10, what: "2.0 relaunch = 'the real 1.0' (databases, new tagline, #1 PH)", channels: [producthunt, website, changelog], gap_days_from_previous: 473}
  - {step: 11, what: "content engine: YouTube + podcast", channels: [youtube, podcast], gap_days_from_previous: 74}
  - {step: 12, what: "organic HN front page", channels: [hackernews], gap_days_from_previous: 164}
  - {step: 13, what: "repeat per launch: waitlist/sneak-peek -> same-day release note + PH + X + founder post + blog -> keynote video +5d -> micro-releases", channels: [releases, producthunt, x, blog, youtube], gap_days_from_previous: null}
```
