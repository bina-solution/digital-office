# oss-seo-patterns — how products like us became findable, and the ten patterns we adopt (DGO-671)

The owner (DGO-671): «try to relate ourselves to products like us, okay, that were successful and the SEO they did».
`n8n.md`, `umbrel.md`, `notion.md` and `startup-patterns.md` already hold how those companies LAUNCHED; this file is
the SEO side, for the products the item names that were missing: Coolify, CasaOS, YunoHost, Cloudron, Nextcloud, Odoo
and Plane — and Supabase, Cal.com and Home Assistant again, for their SEO only.

Measured 2026-11-10 by a read-only research agent, from each company's own sitemap, the GitHub API, the Hacker News
search API (hn.algolia.com) and their own pages. A count is what that source said that day; a claim with no source
that could be opened says «unverified». The full record (every query and URL) is at the end, and the agent's whole
transcript is in `research_notes/DGO-671 OSS SEO patterns 2026-11-10/`.

## 1. Per company

### Coolify (coolify.io)
- GitHub: 65,878 stars, repository created 2021-01-25 (`gh api repos/coollabsio/coolify`).
- Launches: Product Hunt 2022-03-30, «An open-source & self-hostable Heroku, Netlify alternative», 428 upvotes, #4 of
  the day (https://www.producthunt.com/products/coolify/launches); «Show HN: Coolify v2 – Open-source and
  self-hostable Heroku/Netlify alternative», 158 points the same day (https://news.ycombinator.com/item?id=30854912);
  a second HN post 2025-04-02, 382 points (https://news.ycombinator.com/item?id=43555996). Other people write the
  tutorials, e.g. «Beginner Guide to VPS Hetzner and Coolify», 306 points (https://news.ycombinator.com/item?id=45480506).
- Main site: 19 URLs (https://coolify.io/sitemap-0.xml), every one aimed at a search — five `/compare/` pages
  (coolify-vs-dokploy, coolify-vs-dokploy-vs-caprover-vs-dokku-vs-kamal, heroku-alternative, netlify-alternative,
  vercel-alternative) and root keyword pages (`/free-heroku-alternative`, `/deploy-apps-on-your-own-vps`,
  `/self-host-postgres-with-backups`).
- Docs are the bulk: 1,299 URLs (https://coolify.io/docs/sitemap.xml) — 356 `/docs/services/<app>` pages, one per
  one-click app, titled for search («Self-host N8N with Coolify (One-click Docker)»), 330 API endpoint pages, 299 CLI
  command pages, 14 MCP pages. 388 compose templates in the repository (`templates/compose`).
- awesome-selfhosted: not listed (master, 2026-11-10).

### CasaOS (now under ZimaSpace / IceWhale)
- GitHub: 37,617 stars, created 2021-09-26; the repository's homepage is casaos.zimaspace.com (casaos.io redirects).
- Hacker News: at most 29 points (2023-04-16, https://news.ycombinator.com/item?id=35587451) — HN was not the channel;
  that GitHub and the homelab YouTube channels drove it is unverified.
- The app store at scale: https://www.zimaspace.com/app-store-sitemap.xml has 2,184 URLs = 182 apps × 12 languages
  (`/zimaos/app-store/app/<id>`, titles like «BentoPDF - App Store - ZimaOS»). Docs sitemap 992 URLs, community forum
  2,921. The CasaOS-AppStore repository holds 182 apps (375 stars).
- awesome-selfhosted: not listed.

### YunoHost
- GitHub: 2,991 stars, created 2014. HN: 86 points in 2014 (https://news.ycombinator.com/item?id=7894838), 255 in 2023
  (https://news.ycombinator.com/item?id=35300482).
- Catalog: 702 apps, 701 «working», 15 categories (https://app.yunohost.org/default/v3/apps.json).
- Weak SEO: apps.yunohost.org has no sitemap (404) and an app page's title is only «YunoHost app store | Nextcloud»;
  the docs sitemap has 123 URLs. The forum: about 19,470 URLs (https://forum.yunohost.org/sitemap.xml).
- Badges in other projects' READMEs: GitHub code search finds «install-with-yunohost» in 133 README files (approximate),
  beyond YunoHost's own package repositories FreshRSS, 24eme/signaturepdf, terraforming-mars.
- awesome-selfhosted: listed under «Self-hosting Solutions» — the section DGO would belong in.

### Cloudron
- HN: «Show HN: Cloudron – Get Your Own Cloud», 64 points, 2015-07-30 (https://news.ycombinator.com/item?id=9976992);
  «Cloudron is now open source», 50 points, 2016.
- App store: 198 apps (https://api.cloudron.io/api/v1/apps). Weak SEO: the www site has no sitemap (404), and an app
  page's raw HTML has no title (59 bytes, https://www.cloudron.io/store/io.n8n.cloudronapp.html) — the store is barely
  indexable.
- Docs: 820 URLs (https://docs.cloudron.io/sitemap.xml): 266 `/apps`, 210 `/packages`, 275 `/api`. Forum: about 14,730
  topic URLs in three sitemaps plus 233 categories (https://forum.cloudron.io/sitemap.xml).
- Badges: «cloudron.io/button» in 44 READMEs (wekan, FreshRSS, Mailtrain…).
- awesome-selfhosted: in the NON-FREE list; its code is not at github.com/cloudron-io/box (404).

### Nextcloud
- HN: the fork, «Owncloud has been forked into Nextcloud», 182 points, 2016-06-02
  (https://news.ycombinator.com/item?id=11821117); later news ranks higher, e.g. «Austrian ministry kicks out
  Microsoft…», 479 points (https://news.ycombinator.com/item?id=45732485). GitHub: 37,460 stars.
- Sitemap (https://nextcloud.com/sitemap_index.xml): 1,295 blog posts, 226 press releases, 30 case studies, 16
  whitepapers. Localized pages with localized slugs: de 73, fr 61, es 56, it 53 (e.g. `/de/microsoft-integrationen/`);
  the home page's hreflang lists de, en, es, fr, it — no Hebrew (`/he/` 404).
- Comparisons: `/compare/`, `/es/nextcloud-vs-office365/`, and many posts framed against Microsoft.
- App store: 946 apps (https://apps.nextcloud.com/api/v1/apps.json).

### Odoo
- GitHub: 55,690 stars, 34,266 forks. HN «Odoo: The new OpenERP», 44 points, 2014
  (https://news.ycombinator.com/item?id=7750020).
- The sitemap is mostly forum: 126,626 URLs in three files, 109,294 of them (86%) `/forum`; then 12,684 `/event`, 1,801
  blog, 1,372 slides, 124 `/industries/` (a page and a «-features» page per industry), 115 `/app/`, and directories —
  257 accounting firms, 241 customers, 175 partners.
- Directories by country, Israel included: https://www.odoo.com/partners/country/israel-100,
  `/customers/country/israel-100`, `/accounting-firms/country/israel-100`.
- Languages: the home page's hreflang names 31, Arabic among them — no Hebrew (`/he_IL` 404). The Apps Store states no
  total (the usually quoted figure is unverified); app URLs are `/apps/modules/<version>/<name>`, versions 5.0–20.0.

### Plane (plane.so)
- GitHub: 62,243 stars, created 2022-11-19; «jira-alternative» is one of its repository topics.
- HN: «Plane – Open-source Jira alternative», 437 points, 2023-07-22 (https://news.ycombinator.com/item?id=36824450).
  Their own account (https://plane.so/blog/how-we-got-to-20k-github-stars): it was the FIFTH HN submission; that post
  brought about 7,000 stars, about three times all earlier Reddit and X efforts together; credited: the Jira-alternative
  framing and the README (Product Hunt is not mentioned).
- Sitemap (https://plane.so/sitemap.xml): 9 `plane-vs-*` pages (jira, linear, asana, clickup, monday, notion,
  shortcut…), `/compare`, `/switch-from-jira-data-center`; 8 industry and 10 solution pages; 500 blog posts (the
  sitemap may stop at 500), 79 of them «best X alternatives» or vs posts; 208 changelog, 22 template, 25 marketplace
  and 11 customer pages. Docs: 156 URLs, AI agents and MCP among them.
- Product Hunt «Launch of the Day» 2025-10-13: from a search snippet only, the page not opened.

### Supabase (SEO only; the launches are in `startup-patterns.md`)
- Docs: 2,548 URLs (https://supabase.com/docs/sitemap.xml). www: 851 URLs — 447 blog, 169 changelog, 90 `/features/`, 48
  customers, 18 solutions, 3 `/alternatives/` (supabase-vs-firebase, -auth0, -heroku-postgres). A catalog of 119
  partners at `/partners/catalog/<x>` (https://supabase.com/partners/integrations); a knowledge base and a 74-URL
  `/library`. GitHub: 114,740 stars.

### Cal.com (SEO only)
- Sitemap: 10,690 URLs (https://cal.com/sitemap.xml) in 8 locales of about 1,164 each (de, fr, es, it, nl, pl, pt,
  pt-BR) plus English. In English, by profession and by tool: 172 `/workflows/workflows-for-<industry>`, 150
  `/routing/routing-for-<industry>`, 53 `/scheduling/<industry>`, 160 world-clock tool pages, 744 blog posts.
- Comparisons: 36 vs or alternative URLs in English (`/calcom-vs-calendly`, `/blog/calendly-alternatives`…), 324 with
  the locales. Local pages: `/discover` has 1,627 city and category pages (generated by the app, says robots.txt).
- The repository calcom/cal.com now resolves to calcom/cal.diy (49,883 stars), «the open source community edition».

### Home Assistant (SEO only)
- Sitemap: 4,428 URLs (https://www.home-assistant.io/sitemap.xml): 1,701 `/integrations/`, 1,096 `/actions/`, 216
  triggers, 207 template functions, 173 conditions, 645 blog posts, 58 changelogs, FAQ pages
  (`faq/works-with-apple-google-alexa`). The home page: «2.7 million households». GitHub: 92,119 stars.
- HN: 2 points in 2015 (https://news.ycombinator.com/item?id=10183085), 561 in 2021
  (https://news.ycombinator.com/item?id=28544835). works-with.home-assistant.io answers 200 (the programme not read).

### awesome-selfhosted (the list itself)
- 335,675 stars, 1,275 entries. Its rule: the first release must be more than four months old
  (https://raw.githubusercontent.com/awesome-selfhosted/awesome-selfhosted-data/master/CONTRIBUTING.md).

### Where DGO starts (2026-11-10)
- https://digital-office.co.il/sitemap.xml: 44 URLs — 26 `/apps/`, 2 `/docs/`, 0 `/en/`.
- The public repository bina-solution/digital-office: 2 stars and one PRERELEASE (`machine-arm64-ab1cfb970284`,
  2026-11-03): awesome-selfhosted's four-month clock has not started.
- Search, the same day (DGO-1765): Bing holds no page of digital-office.co.il; Google signed-out, on a phone, does not
  show it in the top 30 for «הלשכה הדיגיטלית», and shows it first for «הלשכה הדיגיטלית לעסקים».

## 2. The ten patterns we adopt

| # | Pattern | Evidence | What it means for digital-office.co.il | Plan item |
|---|---|---|---|---|
| 1 | One indexable page per installable app, titled «self-host X with us» | Coolify 356 `/docs/services/` («Self-host N8N with Coolify»); Home Assistant 1,701 `/integrations/`; ZimaOS 182 apps × 12 languages = 2,184. YunoHost (702 apps, no sitemap, generic titles) and Cloudron (no title in the HTML) show the cost of skipping it | each of the 26 `/apps/` pages, then each of the 35 + 200 projects, a Hebrew page «להריץ את X בלשכה» with a real screenshot, the install step, its own title and description, in the sitemap | seo-514 (DGO-762), seo-301 (DGO-691), seo-400 (DGO-727) |
| 2 | «X vs Y» and «alternative to X» pages as their own family of addresses | Plane 9 `plane-vs-*` + `/compare` + 79 alternatives posts; Coolify 5 `/compare/`; Supabase 3 `/alternatives/`; Cal.com 36 in English ×9 languages; Nextcloud `/compare/` | a `/compare/` family: DGO against Monday, Priority, morning, Google Workspace, Umbrel, Coolify, and «חלופה ל-X» for each famous SaaS | seo-708 (DGO-789), seo-710 (DGO-791), seo-709 (DGO-790), seo-707 (DGO-788) |
| 3 | A launch titled «open-source alternative to <famous SaaS>», submitted again until it lands | HN: Supabase 1,120 (Firebase), Plane 437 (Jira, the 5th try, about 7,000 stars), Calendso 311 (Calendly), Coolify 158 + 428 on Product Hunt (Heroku/Netlify); CasaOS, without that frame, 29 | in English «an open-source alternative to Monday + Google Workspace that runs on your own computer», the same line in Hebrew on the site; several HN submissions planned, not one | DGO-1694 (launch week), seo-804 (DGO-795) |
| 4 | The GitHub README and the awesome lists as the funnel | Coolify 65.9k stars, Plane 62.2k, CasaOS 37.6k; awesome-selfhosted (335k stars) lists YunoHost, Nextcloud, Odoo, Plane, Home Assistant, Cal.diy, and wants a first release older than four months | a real tagged release on the public repository NOW (today only an arm64 prerelease), so the four months start; an English README with a demo and a one-line install | seo-803 (DGO-794), DGO-1693 |
| 5 | Landing pages by profession and industry | Cal.com 172 workflows-for-X, 150 routing-for-X, 53 scheduling/X; Odoo 124 `/industries/`; Plane 8 industries + 10 solutions | «הלשכה לרואי חשבון / עורכי דין / קליניקות / קבלנים / נדל"ן / עמותות», each with its real workflow (INDOX, invoices, WhatsApp) | seo-611 (DGO-776), DGO-1689 |
| 6 | Localized pages with hreflang and translated slugs — and the language nobody serves | Cal.com 9 languages; Odoo 31 (`/he_IL` 404); Nextcloud de/fr/es/it (`/he/` 404); ZimaOS 12. None has Hebrew | Hebrew is the source, and these companies do not compete in it; English under `/en/` with hreflang (0 `/en/` today) | seo-205 (DGO-686), DGO-1699, seo-113 (DGO-679) |
| 7 | Generated reference documentation — a page per API call, CLI command and MCP tool — and a changelog page per release | Supabase N docs + 169 changelog; Coolify 330 API + 299 CLI + 14 MCP; Home Assistant 1,096 actions; Plane 208 changelog | a page per `bbox` command, per app channel (ui, cli, api, flow) and per tool of the office's MCP server (DGO-1687), and a Hebrew `/changelog/<version>`; `/docs/` has 2 URLs today | new item: «תיעוד מחולל: עמוד לכל פקודת bbox, לכל ערוץ ולכל כלי MCP, ויומן שינויים לכל גרסה» (nearest: seo-505 / DGO-753, DGO-1425) |
| 8 | An «Install with <platform>» badge in other projects' READMEs | YunoHost 133 README hits (FreshRSS, signaturepdf, terraforming-mars); Cloudron 44 (wekan, FreshRSS, Mailtrain); Coolify 288, mostly users' own | a «Run in Digital Office» badge, offered as a pull request to the 35 flagship projects together with their install page: links back from the upstream repositories | seo-805 (DGO-796) |
| 9 | A public, indexable community forum for the long tail of questions | Odoo 109,294 forum URLs (86% of its sitemap); YunoHost forum about 19,470; Cloudron about 14,730; Zima 2,921 | a Hebrew questions-and-answers space (מספר הקצאה, חשבונית, וואטסאפ לעסק…), fed by the real questions of the group desk, each answer its own address | new item: «פורום שאלות ותשובות ציבורי בעברית, נסרק» (nearest: seo-806 / DGO-797) |
| 10 | Directories by country: partners, customers, templates, marketplace | Odoo `/partners/`, `/customers/`, `/accounting-firms/country/israel-100`; Supabase 119 partners; Plane 22 templates, 25 marketplace, 11 customers; Cal.com 1,627 `/discover` city pages | an Israeli integrators' directory, installable business-case templates, and case studies (Bina's own office first; clients only with their consent) | DGO-1706, DGO-1689, seo-615 (DGO-780); new item: «ספריית שותפים ולקוחות בישראל באתר» |

## 3. The research record

Repository files read: `apps/digital-assets/research/` (README, and the headings of startup-patterns.md, n8n.md,
umbrel.md), `apps/project-pln/plans/seo.yaml`, `ci-artifacts/king-2026-11-10/fronts/seo-content.md`,
`apps/digital-assets/content/topics.yaml`, `ci-artifacts/triage/results/seo-1.result.jsonl`.

Web searches: «Plane open source project management Product Hunt launch upvotes»; «Coolify Product Hunt launch
self-hostable Heroku alternative».

Hacker News search API (`hn.algolia.com/api/v1/search`, stories): coolify; casaos; yunohost; cloudron; nextcloud;
odoo; plane jira alternative; supabase; calendso; home assistant; umbrel; show hn coolify; odoo openerp; nextcloud
before 2017; supabase before 2020-09; home assistant before 2016.

GitHub API — repositories: coollabsio/coolify, IceWhaleTech/CasaOS, YunoHost/yunohost, YunoHost/apps,
nextcloud/server, odoo/odoo, makeplane/plane, supabase/supabase, calcom/cal.com (→ cal.diy), home-assistant/core,
getumbrel/umbrel, n8n-io/n8n, cloudron-io/box (404), IceWhaleTech/CasaOS-AppStore, awesome-selfhosted/awesome-selfhosted,
bina-solution/digital-office (and its releases and tags), orgs/OCA; coolify `contents/templates` and
`templates/compose`; code search for «install_with_yunohost.svg», «install-with-yunohost», «Deploy on Coolify»,
«cloudron.io/button», «casaos».

Pages and sitemaps opened:
- Coolify: coolify.io/sitemap.xml (404), /robots.txt, /sitemap-index.xml, /sitemap-0.xml, /docs/sitemap.xml,
  /docs/services/n8n
- CasaOS: casaos.zimaspace.com/sitemap.xml and casaos.io/sitemap.xml (both 404), casaos.io, zimaspace.com/robots.txt,
  /sitemap_index.xml, /en-US-sitemap.xml, /docs-sitemap.xml, /app-store-sitemap.xml,
  /zimaos/app-store/app/com.icewhale.bentopdf, community.zimaspace.com/sitemap.xml and /sitemap_1.xml
- YunoHost: yunohost.org/sitemap.xml (404), app.yunohost.org/default/v3/apps.json, apps.yunohost.org/app/nextcloud,
  /catalog, /sitemap.xml (404), doc.yunohost.org/sitemap.xml, /en/, /fr/, forum.yunohost.org/sitemap.xml,
  /sitemap_1.xml, /sitemap_2.xml
- Cloudron: www.cloudron.io/sitemap.xml and /sitemap-index.xml (both 404), /, /store/index.html,
  /store/io.n8n.cloudronapp.html, api.cloudron.io/api/v1/apps, docs.cloudron.io/sitemap.xml,
  forum.cloudron.io/sitemap.xml, /sitemap/topics.1–3.xml, /sitemap/categories.xml
- Nextcloud: nextcloud.com/sitemap.xml, /sitemap_index.xml, post-sitemap.xml, post-sitemap2.xml, page-sitemap.xml,
  case_studies-, whitepapers- and press_releases-sitemap.xml, /, /he/ (404), apps.nextcloud.com/api/v1/apps.json
- Odoo: www.odoo.com/sitemap.xml, sitemap-1-349452c1-1/2/3.xml, /, /he_IL (404), /he (404), apps.odoo.com/sitemap.xml,
  apps.odoo.com/apps/modules
- Plane: plane.so/sitemap.xml and its pages-, blog-, changelog-, templates-, marketplace- and customers-sitemap.xml,
  plane.so/blog/how-we-got-to-20k-github-stars, docs.plane.so/sitemap.xml
- Supabase: supabase.com/sitemap.xml, sitemap_www.xml, docs/sitemap.xml, kb/sitemap-index.xml, library/sitemap.xml,
  partners/integrations
- Cal.com: cal.com/sitemap.xml, /robots.txt, /discover/sitemap.xml, /help/sitemap.xml, /apps; github.com/calcom/cal.com
- Home Assistant: www.home-assistant.io/sitemap.xml, /, /integrations/, works-with.home-assistant.io,
  community.home-assistant.io/sitemap.xml (403)
- Product Hunt: www.producthunt.com/products/coolify/launches
- awesome-selfhosted: the raw README.md and non-free.md, and CONTRIBUTING.md of awesome-selfhosted-data
- DGO: digital-office.co.il/robots.txt and /sitemap.xml
