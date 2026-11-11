# DGO net: the public front of DGO (DGO-1757)

The owner, 2026-11-10, in his own words:

> final goal for us in general is to have full dgo net app on our server that provides fully public services for our
> clients among them is
> * accounts (dgo accounts, login with google and private erea)
> * apps (public app sotore containing all dgo applications ready to be installed from anywhere)
> * news like google news we put out all new we collect in newsflow on hp
> * operative collective (full operation scripture social network for anything from how to implment dgo in a company to
>   creating apps to do annual business tax for small israeli business (step by step of what to prepare and where to go
>   and what to do), to making an omlet (more for the robotics era so pepole will use ready operatives for dayly tasks so
>   they know exactly what to expect)
> * domains (we want to resell domains like internic and other so pepole can buy directly from us)
> * compute (we want to resell comupte via providores like hostinger and other so we can sell vps, gpu, etc)
> * public-route (we baissacly want to allow pepol to run a mini dgo on our servers for free that will just extend there
>   local dgo so they can have public access basically for us it should be very cheap and we serve baiscally as a secured
>   router to there applications that are running locally (so they can access them from any where on
>   console.<dgo-account>.digital-office.co.il and thy see al of there local dgos and apps showing up there, while taking
>   minimal compute from us)
> * llm (like open router) where we provide models from diffrent providors
> * dgo cloud (basically gives a vps and deployes a new dgo on it, fully secured manged dgo cloud solution)
> * payments (single payment gate service for everything we offer behind payment)
>
> it can be sperated into genric dgo apllications olving that business domains for any company (like accounts and
> payments) but all served and orgenised inside the dgo net application, we should do deepinvestigation how current mega
> online service providors are managing (like alphabet, meta, hostinger, hugging face etc) providors and make sure we
> have the world leading mangment for our dgo product company
> currently only do the basic research and remeber everything will get to this dgo net front later and we will achive
> world leadinng mangment and find the best way to offer all of thees

## What it is

DGO net is the product's public face. It is one application on Bina's own server, and through it clients reach ten
services. Every service is first a **generic DGO app**: an app any company can run for its own business, with its
providers as provider apps (the rule in [provider-apps.md](provider-apps.md), DGO-1473). DGO net is the application that
**serves and organises** them for Bina's clients: one account, one bill, one front.

**Status, 2026-11-10: research only.** Nothing is built. The owner's order is basic research now, and the build
later, through this front. The research, with its seven findings and the open questions for the deep investigation, is
[reports/DGO net research 2026.md](../../reports/DGO%20net%20research%202026.md). Every query and source is in
`research_notes/DGO net research 2026/`.

**Name.** The id `dgo-net` is TAKEN: it is the container that holds each office's WireGuard interfaces (`apps/dgo-extend`,
`dgo-net` + `dgo-link`). The app gets another id when it is built. «DGO net» is the product's name, not an id.

## The ten services: what each asks for, and what the office already has

| service | what he asks | what exists today | what is missing |
|---|---|---|---|
| **accounts** | DGO accounts, sign in with Google, a private area | authentik on every office (`platform-base/authentik`); vps1 is the herd's public sign-in ([dgo-herd.md](dgo-herd.md)) | an account that spans a client's offices and the paid services; Google sign-in is down: the herd's OAuth client answers `invalid_client`, and a new one is an owner step (DGO-1392) |
| **apps** | a public store of every DGO app, installable from anywhere | `platform-base/app-management`: the catalog, the store tab, `POST /api/catalog/install`; the signed app index and `bbox app install <id\|URL\|path>` (`platform/manager/catalog.py`, F-Droid's model, Ed25519); the public AGPL release (`bina-solution/digital-office`) | a public page of the catalog, with its signed index published on digital-office.co.il; an install the client starts there and their own office pulls (never a push into it) |
| **news** | Google-News-like, everything newsflow gathers on the HP | `newsflow` (221 sources, 108 of them added by DGO-1712; the review step for the sites' news sections, DGO-1383; the competitors it follows, DGO-1384). It is only on the HP's branch `hp-dgo` (written by Azaria), not in `dgo-stable`; `sites` serves public sites | newsflow in `dgo-stable`; a public news front, with what the law requires of an aggregator in Israel |
| **operative collective** | a social network of step-by-step operations, from installing DGO to a small business's annual tax to an omelet; ready for robots | `apps/operatives`: «the Operative Collective», one proven recipe per action at `apps/<app>/operatives/<id>.md`, matched by `bbox ops find` | the public, social side: people's operatives, quality, reputation, moderation, a licence |
| **domains** | resell InterNIC and others, bought directly from Bina | `domains` (generic) + `domain-internic` (provider, browser rung) | a reseller account and its API at a registrar, prices, billing |
| **compute** | resell VPS and GPU from Hostinger and others | `computers` (servers over SSH, the herd); the Hostinger panel driven in the HP's browser | a provider API and resale terms, provisioning, billing |
| **public-route** | a free mini DGO on Bina's server that extends a local DGO to the public, at `console.<account>.digital-office.co.il`, showing all of the account's offices and apps, at minimal cost | `dgo-extend`: WireGuard links, apps given across a link; vps1's console already serves linked offices' apps (`#/m/<app>.<office>/…`); the herd design ([dgo-herd-design.md](dgo-herd-design.md), guest herds) | names per account (free accounts on a separate domain, not digital-office.co.il: research report, § public-route), outsiders' offices joining, isolation between accounts, abuse handling, the security posture for strangers ([dgo-security.md](dgo-security.md)) |
| **llm** | like OpenRouter: models of many providers | DGO-1752: the `ai` router and `ai-<provider>` apps, designed. A paused draft is in `ci-artifacts/ai-router/draft/`; the notes are in `ci-artifacts/ai-router/notes.md` | the build. BYOK first: OpenAI, Google and Anthropic restrict reselling raw model access, so Bina's own keys power only Bina's own services, unless a provider expressly approves resale or an aggregator's terms allow it (research report, § llm) |
| **dgo cloud** | a VPS with a new DGO deployed on it, fully secured and managed | `dgo-extend` «office» kind: installs a DGO on a machine over SSH from a declaration; `scripts/ops/host-baseline.sh` (Exampleu's host); [fresh-office-cloud-sandbox-2026-10-15.md](fresh-office-cloud-sandbox-2026-10-15.md) | ordering, provisioning the VPS by API, the managed service's terms (updates, backups, SLA), billing |
| **payments** | one payment gate for everything sold | `my-docs` over apitools' ledger: tax invoices to the Tax Authority's rules, with allocation numbers (`apps/apitools/src/doc_data/allocation.py`: a stub by default, `live` to the Tax Authority) and the PCN874 VAT report (`pcn874.py`); on `dgo-stable`, disabled on the Mac. No payment gate (a client's app, `chimney-services`, has its own Stripe) | the gate and its two rails (Grow for shekels, a merchant of record abroad), the wallet and usage credits, an invoice issued on every sale |

## Rules already in force for it

- A generic app per domain of work, and a provider app per outside service, found by name
  ([provider-apps.md](provider-apps.md)). Accounts and payments are generic apps any company can run; DGO net uses them
  for Bina's own business.
- The herd: vps1 is «the storefront and the door» ([dgo-herd.md](dgo-herd.md)). Heavy work stays off it.
- Research comes before building, and every query, source and transcript is saved in the office
  (`research_notes/`, the office drive, the item).
- No outside AI service without the owner's word (memory `feedback-no-external-ai-without-his-word`); each new LLM
  provider of `llm` needs it.
