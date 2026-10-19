# Startup-tail — how product startups reveal themselves and then keep publishing updates (cross-company patterns)

Research for the `startup-tail` blueprint of `apps/digital-assets` (נכסים דיגיטליים). Compiled **2026-09-29**.
Question: *which series of videos, images and texts do successful product startups publish, first to reveal
themselves and then to announce updates, and which parts repeat often enough to become ready-made slots?*

**Method and confidence.**
- **Dates** come from primary sources wherever possible: company blogs and changelogs, and the Hacker News Algolia API
  (story `created_at`, points). The **current cadence** comes from each company's YouTube RSS feed (the latest 15
  videos, read on 2026-09-29). One Wayback CDX query answered; the others timed out.
- Items marked *(secondary)* come from third-party write-ups. A gap such as **+78 d** is the number of days since the
  previous beat. "unknown" means not verified. No number here is estimated.
- HN points are a snapshot taken on 2026-09-29.

**Five findings that shape the blueprint.**
1. The tail has two layers: a **one-off reveal arc** (holding page → teaser → waitlist → launch day → postmortem →
   first named update) and a **recurring engine** (changelog → digest email → monthly narrative with a livestream →
   quarterly launch week → annual conference, "State of" address and year-in-review).
2. The **atomic unit is the changelog entry**. Every bigger unit bundles entries: a monthly post, a launch week, a
   keynote. Linear, PostHog and Raycast all publish entries weekly or per release.
3. The **launch week** (Supabase, since 2021-03) is the most copied repeatable format. It runs 5 days with one
   headline per day, a personalized ticket, a hackathon, meetups and a Top-10 recap. Tailscale and Vercel wrapped
   the same format around a conference.
4. **Video has moved from launch-only to ritual.** Home Assistant streams every monthly release. Supabase has run a
   weekly changelog stream since 2026. Linear and Raycast publish an "Introducing X" film for each feature.
5. Every tail observed for long enough eventually needed a **transition unit**: a pivot letter, a licence change, an
   end-of-life notice, an incident report or an acquisition video. Reserve that slot from the start.

---

## 1. Per company

### 1.1 Supabase — the launch-week archetype
| Date | Beat | Gap | Source |
|---|---|---|---|
| 2020-01 | Building starts | — | [How we launch](https://supabase.com/blog/supabase-how-we-launch) |
| 2020-03-10 | First archived supabase.io page (holding page) | — | [Wayback](https://web.archive.org/web/20200310080644/https://supabase.io/) |
| 2020-05-27 | HN front page "Supabase (YC S20) – An open source Firebase alternative", 1,120 pts | +78 d | [HN](https://news.ycombinator.com/item?id=23319901) |
| 2020-07-10 | "Alpha Launch Postmortem": 30,000 visitors, 1,400+ sign-ups in 7 days, repo 300→1,300 stars overnight, infrastructure caps hit | +44 d | [blog](https://supabase.com/blog/alpha-launch-postmortem) |
| 2020 → 2020-12 | Monthly build updates ("Eight/Nine months of building") → "Supabase Beta December 2020" | ~+6 mo | [blog](https://supabase.com/blog/supabase-beta-december-2020) |
| 2021-03-25 | "Launch week — Five days of Supabase" announced; LW1 runs the week of 2021-03-29 | +306 d after HN; announced 4 days before | [blog](https://supabase.com/blog/launch-week) |
| 2021-11-26 | "How we launch at Supabase" published alongside the LW III announcement | | [blog](https://supabase.com/blog/supabase-how-we-launch) |
| 2025-04-22 | $200M Series D at a $2B valuation (earlier rounds not verified here) | | [HN](https://news.ycombinator.com/item?id=43763225) |
| 2026-09 | "Weekly Changelog Live Stream" (Ep 14 on 2026-09-28); "Supabase Select 26" teaser (2026-09-01) | | [YouTube](https://youtu.be/QmJY5foN2gs) |

**Launch-week rhythm (dated by blog posts):** LW1 2021-03-29 week · LW2 "The SQL" 2021-07 (days not verified) ·
LW3 week of 2021-11-29 · LW4 2022-03-28..04-01 · LW5 2022-08-15..19 · LW6 2022-12-12..16 · LW7 2023-04-10..14 ·
LW8 2023-08-07..11 · LW X 2023-12-11..15 · GA Week 2024-04 (week of 04-15) · LW12 2024-08-12..16 · LW13 2024-12-02..06 ·
LW14 2025-03-31..04-04 · LW15 2025-07-14..18 · further launch-week posts dated 2025-12-01..05. That is about one
launch week every 4–5 months.

**Signature units.**
- **Launch Week.** Five "main stage" launches, one per day at 08:00 PT (LW15 added six "build stage" extras).
- **Personalized ticket.** LW7 gave each user AI-generated ticket art. Sharing on X *and* LinkedIn turned it into a
  "golden" ticket that entered a swag draw
  ([source](https://supabase.com/blog/designing-with-ai-midjourney)).
- **Around the week.** A 10-day hackathon starting Friday, 40+ city meetups (LW15), a community-highlights post, and
  a "Top 10 launches" recap.
- **Internal playbook.** Press is briefed 3 weeks ahead and integrations are finished 1 week ahead. On launch day, a
  reminder tweet for the Twitter Space goes out at 07:30 and the blog post at 08:00.
- **Other recurring units.** Monthly "Supabase Beta <Month>" posts (Dec 2020, and Apr/May/Oct 2023 among others),
  the weekly changelog livestream (2026), and short educational clips.

**Channels:** blog, launch-week hub page, X (including Twitter Spaces), YouTube, HN, Product Hunt, LinkedIn,
GitHub, Luma (meetups), email.

### 1.2 Linear — invite-only craft reveal, then a weekly changelog
| Date | Beat | Gap | Source |
|---|---|---|---|
| 2019-03 | Founders quit their jobs; working prototype in ~1 month | — | [First Round](https://review.firstround.com/linears-path-to-product-market-fit/) |
| 2019-04 (reported 04-18, secondary) | "Announcing Linear" Medium post + tweet + waitlist with a survey; ~10,000 emails; ~10 hand-picked invites/week | — | [First Round](https://review.firstround.com/linears-path-to-product-market-fit/) |
| 2019-11-21 | $4.2M seed led by Sequoia | +217 d | [TechCrunch](https://techcrunch.com/2019/11/21/linear-lines-up-4-2m-led-by-sequoia-to-build-a-better-platform-for-software-developer-collaboration/) |
| 2020-06-30 | Public launch; HN "Linear – A fast issue tracker", 491 pts | +439 d after beta | [HN](https://news.ycombinator.com/item?id=23693029) |
| 2020-09-16 | "Linear Method" (practices for building) on HN | +78 d | [linear.app/method](https://linear.app/method) |
| 2020-12-08 | $13M Series A (Sequoia), announced on Medium | +161 d after launch | [Medium](https://medium.com/linear-app/linear-raises-13m-in-series-a-funding-from-sequoia-capital-daa0f0c43758) |
| 2022-12-01 | "Polishing Season 2022" (a December quality month) | | [changelog](https://linear.app/changelog/polishing/2022) |
| 2023-09-14 | $35M Series B led by Accel | | [blog](https://linear.app/blog/series-b) |
| 2025-06-10 | Series C, "Building our way" ($82M at $1.25B per secondary sources) | | [now](https://linear.app/now/building-our-way) |

**Signature units.**
- **Changelog, about weekly.** The latest entries are dated 2026-07-20, 07-23, 07-30, 08-13, 08-20, 09-03, 09-14 and
  09-24. Each has a headline feature with a hero image or video, then "Improvements" and "Fixes" lists. Big
  launches get their own entry, for example "Introducing Loops" (2026-07-20).
- **"Introducing X" videos** on YouTube, one per launch ([Linear Diffs](https://youtu.be/7gZBxBTapDQ), 2026-05-28).
- **Short brand films in 2026:** "FASTER THAN SOUND" (2026-07-21), "After the IDE" (2026-08-11), "INSPECT" (2026-08-31).
- **Evergreen:** the Method page, and a December polish season.
- **Early vs. now:** the 2019 beta and 2020 Series A were announced on Medium; the 2023 Series B and 2025 Series C
  on linear.app.

**Channels:** changelog, linear.app/now, X, YouTube, email.

### 1.3 Raycast — free for three years, then paid tiers, new platforms and hardware
| Date | Beat | Gap | Source |
|---|---|---|---|
| 2020-03-02 | "Launch HN: Raycast (YC W20) – CLI-inspired desktop app for non-coding tasks", 160 pts (first trace found) | — | [HN](https://news.ycombinator.com/item?id=22466994) |
| 2020-10 | Public beta with 130 daily users; $2.7M seed (Accel, YC) *(secondary)* | ~+7 mo | [secondary](https://startupfounderstories.com/stories/thomas-paul-mann-raycast-launcher) |
| 2021-12-01 | Series A announced **together with** the Raycast Store and API | +639 d | [blog](https://www.raycast.com/blog/series-a/) |
| 2022-12-19 | "Raycast Wrapped": a personalized year-in-review | | [X](https://twitter.com/raycastapp/status/1604868675277725697) |
| 2023-02-22 | Raycast AI page / waitlist | | [raycast.com/ai](https://www.raycast.com/ai) |
| 2023-05-10 | Raycast Pro, the first paid tier | +77 d after the AI waitlist; +1,164 d after Launch HN | [blog](https://www.raycast.com/blog/introducing-raycast-pro) |
| 2024-09-25 | $30M Series B **with** a Windows public beta and an iOS waitlist; "bi-weekly releases" | | [blog](https://www.raycast.com/blog/series-b) |
| 2026-03-04 | "Glaze by Raycast", a second product (HN, 234 pts) | | [HN](https://news.ycombinator.com/item?id=47247033) |
| 2026-08-27 → 09-10 | NuPhy × Raycast keyboard film (2026-08-27) → "102 Things You Can Do With Raycast 2.0" (2026-09-04) → "Update on Raycast Paid Plans" (2026-09-10) | | [YouTube](https://youtu.be/73pdeHCGerA) |

**Signature units.**
- A versioned changelog page per release ([1.56.0](https://www.raycast.com/changelog/1-56-0)).
- "Introducing X" films.
- A feature-explainer series (Window Management, Quicklinks, Snippets, Settings; June–July 2026).
- "Watercooler" community episodes (#6 on 2026-07-17), a CEO reaction video (to WWDC, 2026-06-12), and Wrapped.
- **Pattern:** every funding round is bundled with a product beat.

**Channels:** changelog, blog, X, YouTube, extension Store, Product Hunt (unverified).

### 1.4 The Browser Company (Arc → Dia) — video-led, founder-to-camera
| Date | Beat | Gap | Source |
|---|---|---|---|
| by 2022-04 (date unknown) | ~100 NDA beta testers | — | [Wikipedia](https://en.wikipedia.org/wiki/The_Browser_Company) |
| 2022-04-19 | Arc announced on Twitter; invite-only waitlist | — | [Wikipedia](https://en.wikipedia.org/wiki/The_Browser_Company) |
| 2022-05-27 | Bloomberg feature, a press moment during the waitlist | +38 d | [Bloomberg](https://www.bloomberg.com/news/features/2022-05-27/google-chrome-and-apple-safari-challenged-by-browser-upstart) |
| 2023-07-25 | Arc 1.0; waitlist dropped | +462 d after the announcement | [9to5Mac](https://9to5mac.com/2023/07/25/arc-browser-no-waitlist/) |
| 2023-10-03 | Arc Max (AI features): a film + the arc.net/max page | +70 d | [video](https://www.youtube.com/watch?v=y7koAGLf0EE) |
| 2023-12-11 → 2024-04-30 | Arc for Windows beta → GA | +141 d | [TechCrunch](https://techcrunch.com/2024/04/30/the-browser-company-releases-arc-for-windows) |
| 2024-02-01 | "Act II of Arc Browser" video (Arc Search for iOS launched 2024-01) | | [video](https://www.youtube.com/watch?v=WIeJF3kL5ng) |
| 2024-12-02 | "An early peek at Dia, our second product — A recruiting video" | | [video](https://youtu.be/C25g53PC5QQ) |
| 2025-05-27 | "Letter to Arc members 2025": active Arc feature development stops; focus moves to Dia | | [Substack](https://browsercompany.substack.com/p/letter-to-arc-members-2025) |
| 2025-06-11 | Dia beta: launch film "Never Explain Yourself Again", a "6.11.25" date video, and a CEO update the next day | +191 d after the teaser | [film](https://youtu.be/YVOw0TAO9ok) |
| 2025-09-04 | Atlassian acquisition ($610M), announced by video + Substack | | [video](https://youtu.be/u0GljxGVBE4) |
| 2025-10-09 | Dia public on Mac | +120 d after the beta | [MacRumors](https://www.macrumors.com/2025/10/09/ai-browser-dia-launches-publicly-on-mac/) |

**Signature units.**
- Team-to-camera YouTube updates, from the CEO or from designers ("Three designers break down swipeable Profiles",
  2026-08-05).
- Cinematic product films.
- Long Substack letters to "members".
- Short use-case series ("Charlie uses Dia for…", 4 videos on consecutive days, 2026-03-23..26).

Funding rounds: not verified here.

**Channels:** YouTube, X, Substack, product domains (arc.net, diabrowser.com), press.

### 1.5 PostHog — transparent, content-heavy, rolling launches
| Date | Beat | Gap | Source |
|---|---|---|---|
| 2020-02-20 | "Launch HN: PostHog (YC W20) – open-source product analytics", 282 pts | — | [HN](https://news.ycombinator.com/item?id=22376732) |
| 2020-06-04 | "How we raised $3M for an open source project" (the funding news *as* a founder story) | +105 d | [blog](https://posthog.com/blog/raising-3m-for-os) |
| 2021-06-10 / 06-17 | $15M Series B + "Why we raised a $15m Series B ahead of schedule" | +476 d | [blog](https://posthog.com/blog/15-million-series-b) |
| 2022-03-23..25 | "Launch Week I": one launch per day for 3 days, each crediting the engineers | | [blog](https://posthog.com/blog/launch-week-universe-of-new-features) |
| 2023-10-03 | Public company handbook on HN | | [handbook](https://posthog.com/handbook) |
| 2024-01-14 | Slack community closed in favour of an owned forum (HN, 396 pts) | | [blog](https://posthog.com/blog/slack-closure) |
| 2025-06-09 | $70M Series D | | [blog](https://posthog.com/blog/series-d) |

**Signature units.**
- **Changelog:** a weekly changelog, plus a bi-weekly changelog email sent through Customer.io
  ([handbook](https://posthog.com/handbook/brand/email-comms)).
- **Newsletter:** "Product for Engineers" on Substack ([newsletter.posthog.com](https://newsletter.posthog.com/);
  subscriber count not verified).
- **Launch tiers:** a four-tier announcement framework
  ([handbook](https://posthog.com/handbook/marketing/product-announcements)).
  - Tier 1, a new product: a product page, blog post, demo video, email campaign and custom art.
  - Tier 2, a major change: email, artwork, blog post and an in-app modal.
  - Tiers 3 and 4: the changelog and social posts.
- **Opinion videos and brand ads** on YouTube ("Tag @PostHog in Slack", 2026-07-06, about 1.3M views on 2026-09-29).
- The handbook now prefers **"rolling" launches over coordinated big-bang events**.

**Channels:** blog, changelog, email, Substack, YouTube, X, LinkedIn, HN, in-app.

### 1.6 Cal.com — open-source launch, version-numbered relaunches
| Date | Beat | Gap | Source |
|---|---|---|---|
| 2021-04-15 | "Calendso: An open source Calendly alternative" on HN (311 pts) + Product Hunt (2,100+ upvotes per Cal.com) | — | [HN](https://news.ycombinator.com/item?id=26817795) |
| 2021-09 | Rebrand to Cal.com + v1.0 release candidate (HN 2021-09-17) | +155 d | [blog](https://cal.com/blog/calendso-rebrands-to-cal-com) |
| 2021 (day unknown) | $7.4M seed led by OSS Capital | | [blog](https://cal.com/blog/seed) |
| 2022-04-18 | $25M Series A (Seven Seven Six) | +368 d after launch | [VentureBeat](https://venturebeat.com/2022/04/18/open-source-calendly-rival-cal-com-raises-25m/) |
| 2022-08-28 | "Open Startup" metrics page on HN | | [cal.com/open](https://cal.com/open) |
| 2022-09-16 | v2, "Scheduling Infrastructure" | | [HN](https://news.ycombinator.com/item?id=32866261) |
| 2023-01-24 | HN "Cal.com: Open Scheduling Infrastructure", 576 pts | | [HN](https://news.ycombinator.com/item?id=34507672) |
| 2023-06-15 | v3.0 launch *(secondary)* | | — |
| 2026-04-15 / 04-21 | "Cal.com is going closed source" (HN, 391 pts) → community edition "Cal.diy" | +1,826 d | [blog](https://cal.com/blog/cal-com-goes-closed-source-why) |

**Signature units:** each version is a relaunch (v1, v2, v3), with Product Hunt and HN every time; a public metrics
page; the founders' posts on X.

**Channels:** Product Hunt, HN, GitHub, X, blog. The YouTube RSS feed returned no recent videos.

### 1.7 Home Assistant — the monthly release ritual plus annual set pieces
- **Birthday 09-17.** Home Assistant used its 10th birthday livestream (HA10, 2023-09-17) to launch the
  **Home Assistant Green** hub; the anniversary batch of 1,000 sold out
  ([blog](https://www.home-assistant.io/blog/2023/09/17/home-assistant-green-your-entry-to-home-assistant/)). A
  birthday video followed on 2026-09-17 ([video](https://youtu.be/YakjQj2bH6I)).
- **Monthly release, YYYY.M**, in four parts:
  - The **pre-release stream**, in beta week: "Pre-Release Not a Release Party"
    ([2026-06-25](https://youtu.be/n3HghFZQCiA)).
  - The **release-notes post** on release day, with a theme title
    ([2025.5 "Two Million Strong"](https://www.home-assistant.io/blog/2025/05/07/release-20255/)).
  - The **Release Party** livestream, 20:00 GMT that evening ([2026.9, 2026-09-02](https://youtu.be/TgGiUchnmDw);
    2026.8 on 2026-08-05).
  - The **"What's New in Home Assistant YYYY.M"** recap video the next day ([2026-08-06](https://youtu.be/2NadKNdVHNs)),
    plus "Did you know… in 2026.5" clips.
- **Annual "State of the Open Home" livestream:**
  - A 2021 edition page exists ([link](https://www.home-assistant.io/state-of-the-open-home/)).
  - 2022 edition, followed by "2023: Home Assistant's year of Voice" on 2022-12-20
    ([blog](https://www.home-assistant.io/blog/2022/12/20/year-of-voice/)).
  - 2024-04-20 ([recap](https://www.home-assistant.io/blog/2024/04/24/state-of-the-open-home-2024/)).
  - 2025-04-12, announced 17 days ahead
    ([blog](https://www.home-assistant.io/blog/2025/03/26/state-of-the-open-home-2025-announcement/)).
- **Themed year with chapters:** the Year of the Voice, e.g. Chapter 2 on 2023-04-27 and a Chapter 6 livestream on
  2024-02-16.
- **Hardware line:**
  - Blue (2020-12, *secondary*).
  - Yellow: crowdfunded in 2021; production ended 2025-10-15
    ([blog](https://www.home-assistant.io/blog/2025/10/15/yellow-end-of-life/)).
  - SkyConnect (2022).
  - Green (2023-09-17).
  - Voice Preview Edition (2024-12-19, [blog](https://www.home-assistant.io/blog/2024/12/19/voice-preview-edition-the-era-of-open-voice/)).
  - ESPHome Starter Kit "Product Launch Pre Stream" (2026-08-12).

**Channels:** blog, YouTube (live + clips), X, community forum.

### 1.8 Tailscale — engineering-voice feature posts, community conference, DevRel video
| Date | Beat | Gap | Source |
|---|---|---|---|
| unknown | First public trace (not verified; Wayback timed out) | | — |
| 2020-11-11 | $12M Series A ("The next milestone") | | [blog](https://tailscale.com/blog/the-next-milestone/) |
| 2022-05-04 | $100M Series B (HN, 854 pts) | +539 d | [blog](https://tailscale.com/blog/series-b/) |
| 2022-06-22 / 11-18 | Tailscale SSH (759 pts) / Tailscale Funnel (666 pts) | | [SSH](https://tailscale.com/blog/tailscale-ssh/) |
| 2023-02-22 → 05-31 | "Tailscale Up" announced → single-track community conference in SF (CFP via Sessionize; $75 early bird) | 98 d runway | [blog](https://tailscale.com/blog/tailscale-up-2023) |
| 2025-04-08 | $160M Series C | | [blog](https://tailscale.com/blog/series-c) |
| 2026-07-31 | Incident post "Tailscale didn't stop the Hugging Face intrusion" (HN, 627 pts) | | [blog](https://tailscale.com/blog/hugging-face-intrusion) |
| 2026-08/09 | TailscaleUp 2026 + a "TailscaleUp-date" launch week: one launch per day, Aperture GA video (2026-08-26), keynote replay (2026-09-03), recap webinar | | [page](https://tailscale.com/tailscaleup-date-week-26) |

**Signature units:**
- Feature launch posts written in an engineering voice.
- A monthly newsletter published as a blog post ([Dec 2024](https://tailscale.com/blog/2024-12-newsletter)).
- A conference with a launch week around it.
- DevRel homelab tutorials, e.g. "Free and Easy Home Assistant Remote Access with Tailscale!" (2026-07-10, about
  52k views on 2026-09-29).
- "Ask a Tailscale Expert" and "DevRel Hot Takes" episodes.

**Channels:** blog, YouTube, X, HN, Reddit (unverified), email.

### 1.9 Plausible — bootstrapped building in public (no funding beat)
Timeline from the founders' own ledger ([2022-06-22 post](https://plausible.io/blog/open-source-saas)):
- 2018-12 first code → 2019-01 public beta → 2019-05 paid plans ($64 MRR) → 2019-07 first HN traffic spike → 2019-09
  open source (MIT).
- 2020-02 marketing co-founder joins → 2020-04 viral "stop using Google Analytics" post → 2020-05 opensource.com
  feature (94 trial sign-ups in one day) → 2020-08 Product Hunt → 2020-10-06 Show HN of the self-hosted edition
  (351 pts, [HN](https://news.ycombinator.com/item?id=24696145)) → 2020-10 licence change to AGPL.
- 2021-01 $10k MRR → 2021-08 adblocker study → 2021-10 $500k ARR ([post](https://plausible.io/blog/bootstrapping-saas))
  → **2022-06-02 $1M ARR ($83,637 MRR), published 20 days later**.
- 2024-07-10 Community Edition ([blog](https://plausible.io/blog/community-edition)).

**Signature units:**
- Milestone revenue posts with a month-by-month ledger.
- A public stats dashboard of its own site ([plausible.io/plausible.io](https://plausible.io/plausible.io)).
- Newsjacking posts: Google FLoC, AMP, the Universal Analytics shutdown, the Austrian GDPR ruling.
- One original study: the adblocker study "+100% trial sign-ups within five days".
- No ads, no paid influencers.

**Channels:** blog, HN, X, Indie Hackers, opensource.com (guest).

### 1.10 Vercel — the conference as the reveal engine
| Date | Beat | Gap | Source |
|---|---|---|---|
| 2020-04-21 | ZEIT renamed Vercel + $21M Series A | — | [blog](https://vercel.com/blog/zeit-is-now-vercel) |
| 2020-10-27 | First Next.js Conf, online ("70k registered" per the HN title) | +189 d | [HN](https://news.ycombinator.com/item?id=24908604) |
| 2020-12-16 | $40M Series B | +50 d after the conference | [blog](https://vercel.com/blog/series-b-40m-to-build-the-next-web) |
| 2021 | Next.js Conf with "claim your ticket" and a multiplayer conference site (HN 2021-05-18/19); October edition for "5 years of Next.js" | | [HN](https://news.ycombinator.com/item?id=27201209) |
| 2022-10 | Next.js Conf in San Francisco + an "Everything launched" thread (2022-10-30) | | [X](https://twitter.com/leeerob/status/1585349567410626560) |
| week of 2023-05-01 | "Vercel Ship" **launch week**: KV, Postgres, Blob storage, Secure Compute, Firewall | | [TechCrunch](https://techcrunch.com/2023/05/01/vercel-adds-new-backend-tools-to-its-frontend-cloud/) |
| 2024-05-23 | Vercel Ship 2024 (NYC), keynote livestream | | [keynote](https://www.youtube.com/watch?v=roRx0b_VXsU) |
| 2025-06-25 / 10-23 | Ship 2025 (NYC + online) / Ship AI (SF) | | [ship/2025](https://vercel.com/ship/2025) |
| 2026 | Ship 26 NYC (talks uploaded 2026-07-20) and Ship 26 SF (2026-10-15..16) | | [ship](https://vercel.com/ship) |

**Signature units:**
- Annual conferences with personalized tickets and a keynote livestream. Ship itself started as a launch week
  (2023) and became a conference with several cities per year.
- Batch uploads of talk recordings.
- Customer-story videos ("How Rogo ships…", 2026-09-23).
- A changelog.

**Channels:** conference sites, YouTube (live), X, blog, changelog, press.

---

## 2. The general startup-tail skeleton

D0 = public launch day. Windows before D0 are offsets. After launch the tail becomes recurring. Gaps are taken from
the companies above, for example Supabase D-78 → D0 → D+44 postmortem → D+306 first launch week.

**Mapping to digital-assets slot types.**
- *Identification* slots are created once and refreshed on rebrands: holding page, og/link card, X header, GitHub
  social preview, product-hunt thumbnail.
- *Content* slots are texts: posts, changelog entries, letters, newsletters, threads.
- *Media* slots are films, clips, loops, livestreams, thumbnails, tickets and carousels.
- A recurring unit means one slot **per occurrence**, e.g. `changelog-entry` × every release.

**Platform-standard specs used below**

| Use | Size / aspect | Notes |
|---|---|---|
| Link / og card (website, Facebook, LinkedIn link, X card, WhatsApp preview) | 1200×630 (1.91:1) | One per post/page |
| X in-stream image · X header | 1600×900 (16:9) · 1500×500 (3:1) | |
| LinkedIn feed image · document carousel | 1200×627 or 1080×1080 · PDF pages 1080×1350 | |
| Instagram feed · Stories/Reels/YouTube Shorts/WhatsApp Status | 1080×1350 (4:5) · 1080×1920 (9:16) | Shorts: ≤60 s typical; YouTube accepts up to 3 min since 2024-10 |
| YouTube video · thumbnail | 1920×1080 (16:9) · 1280×720 | Livestream at 1920×1080 |
| GitHub social preview | 1280×640 (2:1) | |
| Product Hunt thumbnail · gallery | 240×240 (GIF allowed) · 1270×760 | |
| Email | 600 px wide; header 1200×600 (@2x) | |
| Blog / changelog hero | 1600×900 (16:9) or MP4 loop 5–15 s | |
| Discord | embed image 16:9; server banner 960×540 | |

### Phase 1 — Pre-launch / stealth (`stealth`, window `D-180..D-60`)

Claim the name and write down the worldview before anything is shown. Supabase's domain was already live 78 days before its HN launch; Linear published its thesis with the waitlist.

**`holding-page` — Holding page with email capture**  
*Purpose:* Claim the name/domain, collect early interest, create the first public trace every later asset links back to. *Trigger:* Name and domain decided. *Timing:* D-180..D-60 (Supabase: first archived capture D-78).  
*Channels:* website, github, x.  
*Assets:* page single section: logo, one-line promise, email field ×1; image og/link card 1200x630 (1.91:1) ×1; image X header 1500x500 (3:1) ×1; image GitHub social preview 1280x640 (2:1) ×1.  
*Copy:* one-line promise → who it is for → 'get early access' email field → (optional) who is building it.  
*Examples:* [supabase.io, first archived 2020-03-10, 78 days before the HN launch](https://web.archive.org/web/20200310080644/https://supabase.io/); [diabrowser.com holding page at the Dia teaser, 2024-12-02](https://news.ycombinator.com/item?id=42298063); [Raycast AI waitlist page, 2023-02-22](https://www.raycast.com/ai).

**`founder-thesis-post` — Founder thesis / manifesto post**  
*Purpose:* Frame the problem and the worldview so the later reveal has a story and a vocabulary. *Trigger:* Before or together with the first public announcement. *Timing:* D-120..D0.  
*Channels:* blog, x, linkedin, hackernews, email.  
*Assets:* text article 800-1500 words ×1; image hero 16:9 1600x900 ×1; thread 5-8 posts (X) / 1 long post (LinkedIn) ×1.  
*Copy:* the broken status quo → why now → our principles → what we are building (no full screenshots) → join the waitlist.  
*Examples:* [Linear: 'Announcing Linear' Medium post + tweet + waitlist, 2019-04](https://review.firstround.com/linears-path-to-product-market-fit/); [Linear Method (practices for building), on HN 2020-09-16](https://linear.app/method); [Plausible: viral 'why you should stop using Google Analytics' post, 2020-04 (listed in)](https://plausible.io/blog/open-source-saas).

### Phase 2 — Teaser (`teaser`, window `D-200..D-3`)

Show a glimpse, not the product, and fix a date. The Browser Company teased Dia 191 days before its beta and framed the teaser as a recruiting video.

**`teaser-video` — Teaser / early-peek video**  
*Purpose:* Create curiosity (and recruit talent) without full disclosure. *Trigger:* Product direction fixed; beta date within ~6 months. *Timing:* D-190..D-30 (Dia: D-191).  
*Channels:* youtube, x, linkedin, instagram, website.  
*Assets:* video 16:9 1920x1080, 60-180 s ×1; video 9:16 1080x1920 cut, <=60 s ×1; image YouTube thumbnail 1280x720 ×1; page teaser landing with waitlist field ×1.  
*Copy:* tension (what is wrong today) → glimpse (fragments of UI, people, process) → name + 'coming <season>' → CTA: waitlist / we are hiring.  
*Examples:* [Dia: 'An early peek at Dia, our second product | A recruiting video', 2024-12-02](https://youtu.be/C25g53PC5QQ); [TechCrunch coverage of the Dia teaser, 2024-12-02](https://techcrunch.com/2024/12/02/the-browser-company-teases-dia-its-new-ai-browser/); [Raycast AI waitlist page 77 days before Raycast Pro, 2023-02-22](https://www.raycast.com/ai).

**`save-the-date` — Save-the-date / countdown**  
*Purpose:* Lock a date in people's calendars and turn followers into reminders. *Trigger:* Date of the launch, launch week or livestream fixed. *Timing:* D-30..D-3 (Supabase LW1 announced D-4; HA State of the Open Home 2025 announced D-17).  
*Channels:* blog, x, linkedin, youtube, email, discord, whatsapp.  
*Assets:* image 16:9 1600x900 ×1; image 1:1 1080x1080 ×1; image story 9:16 1080x1920 ×1; livestream scheduled YouTube premiere/live page ('Notify me') ×1; email 600 px wide, one CTA ×1.  
*Copy:* what (event name) → when (date + time in 3 time zones) → what you will get → reminder CTA ('Notify me' / add to calendar).  
*Examples:* [Supabase 'Launch week - Five days of Supabase', posted 2021-03-25](https://supabase.com/blog/launch-week); [Home Assistant 'Announcing State of the Open Home 2025', 2025-03-26 for 2025-04-12](https://www.home-assistant.io/blog/2025/03/26/state-of-the-open-home-2025-announcement/); [Home Assistant save-the-date post on X for State of the Open Home 2024](https://x.com/home_assistant/status/1772744406615175341).

### Phase 3 — Waitlist / invite-only beta (`waitlist`, window `D-460..D-1`)

Linear (439 days) and Arc (462 days) both stayed invite-only for more than a year. Linear used the waitlist as research: a survey, and about 10 hand-picked invites a week.

**`waitlist-survey` — Waitlist with qualifying survey**  
*Purpose:* Measure demand, pick fitting early users, learn their problems in their words. *Trigger:* Teaser or thesis published. *Timing:* opens D-460..D-90, stays open until public launch.  
*Channels:* website, email.  
*Assets:* page form: email + 2-3 questions (use case, current tool, team size) ×1; email confirmation, 600 px, plain ×1; image og/link card 1200x630 ×1.  
*Copy:* promise → 'why do you want it / what is your current problem?' → honest expectation (small weekly batches) → share link.  
*Examples:* [Linear private beta: ~10,000 emails, ~10 hand-picked invites per week](https://review.firstround.com/linears-path-to-product-market-fit/); [Karri Saarinen on hand-picking waitlist invites](https://x.com/karrisaarinen/status/1785391264730669351); [Arc drops its waitlist at 1.0, 2023-07-25](https://9to5mac.com/2023/07/25/arc-browser-no-waitlist/).

**`cohort-invite-email` — Cohort invite + beta build note**  
*Purpose:* Onboard a small batch, open a feedback loop, ship a new build per cohort. *Trigger:* New cohort selected. *Timing:* recurring:weekly during the beta.  
*Channels:* email, discord.  
*Assets:* email personal plain-text invite from a founder ×1; text beta release note (what changed since last cohort) ×1.  
*Copy:* personal note → what is new since the last cohort → what we want feedback on → how to reach us.  
*Examples:* [Linear: a new version for every weekly cohort of ~10 users](https://review.firstround.com/linears-path-to-product-market-fit/); [Arc: ~100 NDA testers before the public invite-only period](https://en.wikipedia.org/wiki/The_Browser_Company).

### Phase 4 — Reveal / launch day (`launch-day`, window `D0`)

One canonical post that every channel links to, one film, and native posts per network, all published within a two-hour window. YC companies use Launch HN; Product Hunt adds a badge but does not keep traffic coming.

**`launch-post` — Launch post (canonical)**  
*Purpose:* The one page every other channel links to. *Trigger:* Product (or public beta) available to anyone. *Timing:* D0, fixed hour (Supabase publishes at 08:00 PT).  
*Channels:* blog, website, email, x, linkedin, facebook, hackernews, producthunt.  
*Assets:* text 600-1200 words ×1; image hero 16:9 1600x900 ×1; image og/link card 1200x630 ×1; animation MP4/GIF product loop 5-15 s, 16:9 ×3; email announcement 600 px ×1.  
*Copy:* hook (one-line promise) → the problem → what it is + 3 capabilities (one loop each) → proof (users, numbers, quotes) → availability & price → CTA → what is next.  
*Examples:* [Arc 1.0 available to everyone, 2023-07-25](https://techcrunch.com/2023/07/25/arc-browser-is-now-available-to-download-for-everyone); [Calendso rebrands to Cal.com and launches v1.0](https://cal.com/blog/calendso-rebrands-to-cal-com); [Linear public launch on HN, 2020-06-30](https://news.ycombinator.com/item?id=23693029).

**`launch-film` — Launch film**  
*Purpose:* The shareable 'what it feels like' asset. *Trigger:* Launch day. *Timing:* D0 (premiere at post time).  
*Channels:* youtube, x, linkedin, instagram, facebook, website, producthunt.  
*Assets:* video 16:9 1920x1080, 60-120 s master ×1; video 9:16 1080x1920 cut, <=60 s ×1; video 1:1 1080x1080 cut, <=60 s ×1; image thumbnail 1280x720 ×1; text subtitles he/en (SRT) ×2.  
*Copy:* cold open on a real pain → name + promise → 3 moments of use → availability → CTA.  
*Examples:* [Dia 'Never Explain Yourself Again', 2025-06-11](https://youtu.be/YVOw0TAO9ok); [Arc Max film, 2023-10-03](https://www.youtube.com/watch?v=y7koAGLf0EE); [NuPhy x Raycast keyboard film, 2026-08-27](https://youtu.be/73pdeHCGerA).

**`hn-launch` — Launch HN / Show HN post**  
*Purpose:* Reach developers and early adopters in an honest founder voice. *Trigger:* Launch day (YC companies: 'Launch HN'). *Timing:* D0, US morning.  
*Channels:* hackernews.  
*Assets:* text title <=80 chars ×1; text founder first comment 300-600 words ×1.  
*Copy:* who we are → the problem we hit ourselves → what we built and how it differs → open source / pricing → ask for feedback.  
*Examples:* [Supabase (YC S20), 2020-05-27, 1,120 points](https://news.ycombinator.com/item?id=23319901); [Launch HN: PostHog (YC W20), 2020-02-20](https://news.ycombinator.com/item?id=22376732); [Calendso: an open source Calendly alternative, 2021-04-15](https://news.ycombinator.com/item?id=26817795).

**`product-hunt-launch` — Product Hunt launch**  
*Purpose:* Badge and one-day spike of social proof; not a lasting channel. *Trigger:* Launch or a major version. *Timing:* D0 at 00:01 PT.  
*Channels:* producthunt, x, linkedin, email.  
*Assets:* image thumbnail 240x240 (GIF allowed) ×1; image gallery 1270x760 ×5; video YouTube link of the launch film ×1; text tagline <=60 chars + maker comment ×1.  
*Copy:* tagline → maker comment (story + launch offer) → gallery, one image per capability.  
*Examples:* [Calendso on Product Hunt: 2,100+ upvotes (per Cal.com)](https://cal.com/blog/calendso-rebrands-to-cal-com); [Plausible on Product Hunt 2020-08: 'spike of hope followed by flat line'](https://plausible.io/blog/open-source-saas); [Supabase includes Product Hunt in its launch playbook](https://supabase.com/blog/supabase-how-we-launch).

**`social-launch-thread` — Native launch thread / carousel**  
*Purpose:* Tell the story in each network's native format instead of a bare link. *Trigger:* Launch post live. *Timing:* D0, +0..2 h after the post.  
*Channels:* x, linkedin, instagram, facebook, discord, whatsapp.  
*Assets:* thread X thread 5-10 posts ×1; image 16:9 1600x900 per capability ×4; image carousel 4:5 1080x1350 (Instagram) / PDF 1080x1350 (LinkedIn) ×8; text Discord announcement + WhatsApp channel update ×2.  
*Copy:* post 1 = hook + film → one capability per post with a visual → proof → link → credits/thanks.  
*Examples:* ['Everything launched at Next.js Conf' thread, 2022-10](https://twitter.com/leeerob/status/1585349567410626560); [Supabase daily rhythm: 07:30 reminder tweet, 08:00 blog post](https://supabase.com/blog/supabase-how-we-launch).

### Phase 5 — Post-launch: postmortem and first big update (`post-launch`, window `D+1..D+180`)

Turn the spike into trust (numbers, what broke) and then into a second story. Supabase's postmortem came 44 days after its HN launch, Arc Max came 70 days after Arc 1.0, and Cal.com's rebrand to v1.0 came 155 days after Calendso.

**`launch-postmortem` — Launch postmortem / numbers post**  
*Purpose:* Convert the launch into trust: the numbers, what broke, what changed. *Trigger:* Launch spike settled. *Timing:* D+30..D+60 (Supabase: D+44).  
*Channels:* blog, hackernews, x, linkedin.  
*Assets:* text 1000-2000 words ×1; image charts 16:9 1600x900 ×3; image og/link card 1200x630 ×1.  
*Copy:* what happened (numbers) → what broke and why → what we changed → thanks → what is next.  
*Examples:* [Supabase 'Alpha Launch Postmortem', 2020-07-10](https://supabase.com/blog/alpha-launch-postmortem); [PostHog 'How we raised $3M for an open source project', D+105](https://posthog.com/blog/raising-3m-for-os).

**`first-big-update` — First named update / version reveal**  
*Purpose:* Prove momentum and re-open the story to press and communities. *Trigger:* A feature set big enough to get its own name (1.0, v2, 'Max'). *Timing:* D+60..D+180 (Arc Max D+70; Cal.com v1.0 D+155).  
*Channels:* blog, youtube, x, linkedin, producthunt, hackernews, email.  
*Assets:* video 16:9 1920x1080, 60-120 s ×1; page named landing (e.g. /max) ×1; image og/link card 1200x630 ×1; text post 600-1000 words ×1; email 600 px ×1.  
*Copy:* name the update → the one big idea → 3 capabilities → who it is for / price → CTA update or try.  
*Examples:* [Arc Max page, 2023-10-03](https://arc.net/max); [Cal.com (formerly Calendso) on HN, 2021-09-17](https://news.ycombinator.com/item?id=28568789); [Cal.com v2, 2022-09-16](https://news.ycombinator.com/item?id=32866261).

### Phase 6 — Release train (recurring) (`release-train`, window `recurring:weekly..monthly from D+1`)

This is the backbone of the tail. A weekly or per-release changelog entry, a digest email every two weeks or every month, and a monthly narrative with a human face (a livestream) plus a short recap video.

**`changelog-entry` — Changelog entry**  
*Purpose:* Steady proof of shipping; one linkable unit per feature. *Trigger:* Every release. *Timing:* recurring:weekly (Linear, PostHog) or every release (Raycast, bi-weekly).  
*Channels:* website, x, linkedin, discord, rss.  
*Assets:* page entry with anchor/permalink ×1; image hero 16:9 1600x900 or MP4 loop 5-15 s ×1; text lists: Improvements, Fixes ×1.  
*Copy:* headline feature (benefit in <=8 words) → visual → how to use (2-3 sentences + docs link) → Improvements → Fixes.  
*Examples:* [Linear changelog](https://linear.app/changelog); [Raycast changelog 1.56.0, 2023-07-27](https://www.raycast.com/changelog/1-56-0); [PostHog changelog](https://posthog.com/changelog).

**`changelog-digest-email` — Changelog digest email**  
*Purpose:* Bring existing users back to new features. *Trigger:* Recurring. *Timing:* recurring:biweekly (PostHog) or monthly (Tailscale).  
*Channels:* email, blog.  
*Assets:* email 600 px, 3-6 items, hero 1200x600 ×1; page web version of the email ×1.  
*Copy:* top feature → 3-5 shorter items → one community story → CTA 'see the full changelog'.  
*Examples:* [PostHog bi-weekly changelog email (handbook)](https://posthog.com/handbook/brand/email-comms); [Tailscale monthly newsletter, December 2024](https://tailscale.com/blog/2024-12-newsletter).

**`monthly-update-post` — Monthly release notes / update post**  
*Purpose:* One narrative per month that ties the releases together. *Trigger:* Monthly release or month end. *Timing:* recurring:monthly (HA on release day; Supabase 'Beta <Month>' 2020-2023).  
*Channels:* blog, email, x, linkedin, discord.  
*Assets:* text long post with a theme title ×1; image hero 16:9 1600x900 ×1; image og/link card 1200x630 ×1; animation feature loops 5-15 s ×5.  
*Copy:* theme headline ('YYYY.M: <theme>') → highlights → full list → breaking changes → thanks to contributors → CTA upgrade.  
*Examples:* [Home Assistant '2025.5: Two Million Strong and Getting Better'](https://www.home-assistant.io/blog/2025/05/07/release-20255/); [Supabase Beta December 2020](https://supabase.com/blog/supabase-beta-december-2020); [Supabase Beta October 2023](https://supabase.com/blog/beta-update-october-2023).

**`release-livestream` — Release party / changelog livestream**  
*Purpose:* A human face and live Q&A for each release; a community ritual. *Trigger:* Release day. *Timing:* recurring:monthly on release day, 20:00 GMT (HA); recurring:weekly (Supabase, 2026); beta-week pre-stream (HA).  
*Channels:* youtube-live, x, discord.  
*Assets:* livestream 16:9 1920x1080, 45-90 min ×1; image thumbnail 1280x720 ×1; video highlight clips 9:16 1080x1920 <=60 s ×3.  
*Copy:* welcome → highlights demo → contributor shout-outs → Q&A → CTA update now.  
*Examples:* [Home Assistant 2026.9 Release Party, 2026-09-02](https://youtu.be/TgGiUchnmDw); [Supabase Weekly Changelog Live Stream Ep 14, 2026-09-28](https://youtu.be/QmJY5foN2gs); [Home Assistant 'Pre-Release Not a Release Party', 2026-06-25](https://youtu.be/n3HghFZQCiA).

**`whats-new-video` — What's-new recap / 'Introducing X' video**  
*Purpose:* Short evergreen explainer per release or per feature. *Trigger:* Release or feature shipped. *Timing:* D+1 after each release (HA); with each feature (Linear, Raycast).  
*Channels:* youtube, x, linkedin, instagram.  
*Assets:* video 16:9 1920x1080, 1-6 min ×1; video 9:16 1080x1920, <=60 s ×2; image thumbnail 1280x720 ×1.  
*Copy:* what is new in <version> → 3-5 features demoed → 'update now'.  
*Examples:* ['What's New in Home Assistant 2026.8', 2026-08-06](https://youtu.be/2NadKNdVHNs); [Linear 'Introducing Linear Diffs', 2026-05-28](https://youtu.be/7gZBxBTapDQ); [Raycast 'Introducing Raycast Dictation', 2026-06-18](https://youtu.be/RUh1KDgSOsc).

### Phase 7 — Launch week (recurring) (`launch-week`, window `recurring:quarterly..3x-per-year (each week spans D-21..D+45)`)

Supabase's invention, copied widely (PostHog, Vercel Ship, Tailscale's 'TailscaleUp-date'). You batch a quarter of shipping into 5 days. Each day gets one headline, and around the week sit a ticket, a hackathon, meetups and a Top-10 recap.

**`launch-week-hub` — Launch-week hub page + announcement**  
*Purpose:* One place for the week; date lock; partner/press coordination. *Trigger:* 3-5 launches ready for the same week. *Timing:* press briefed D-21; integrations frozen D-7; public announcement D-14..D-4.  
*Channels:* website, blog, x, linkedin, email, discord, youtube.  
*Assets:* page hub with 5 day-slots + countdown + ticket CTA ×1; image og/link card 1200x630 ×1; video trailer 16:9, 30-60 s ×1; email announcement 600 px ×1.  
*Copy:* N days, N launches → dates & hour → claim your ticket / get reminders → hackathon & meetups.  
*Examples:* [Supabase Launch Week 15 hub (2025-07-14..18)](https://supabase.com/launch-week); [Supabase Launch Week X (2023-12-11..15)](https://supabase.com/launch-week/x); [Tailscale 'TailscaleUp-date' week, 2026](https://tailscale.com/tailscaleup-date-week-26).

**`personal-ticket` — Personalized ticket / badge**  
*Purpose:* Make every sign-up a distributor of the launch. *Trigger:* Hub page live. *Timing:* D-14..D+4.  
*Channels:* website, x, linkedin.  
*Assets:* image generated per person, 1200x630 (og) × per sign-up; image 'golden' variant unlocked by sharing × per sharer; page ticket wall ×1.  
*Copy:* 'I'm in' + name/avatar + dates → share to unlock (golden ticket / swag).  
*Examples:* [Supabase LW7: AI-art ticket per user, golden ticket for sharing on X and LinkedIn](https://supabase.com/blog/designing-with-ai-midjourney); [Next.js Conf 2021 'claim your ticket'](https://news.ycombinator.com/item?id=27201209).

**`daily-drop` — Daily launch (day N of 5)**  
*Purpose:* One headline per day holds attention for a whole week. *Trigger:* Each day of the week. *Timing:* D0..D+4 at a fixed hour (Supabase 08:00 PT).  
*Channels:* blog, youtube, x, linkedin, hackernews, producthunt, discord.  
*Assets:* text launch post × 1 per day; video demo 16:9, 2-5 min × 1 per day; image og/link card 1200x630 × 1 per day; thread X/LinkedIn post × 1 per day; image story 9:16 1080x1920 × 1 per day.  
*Copy:* Day N of 5 → feature name → why it matters → demo → docs link → tomorrow's teaser.  
*Examples:* [Supabase LW15: one main-stage launch per day + 6 'build stage' extras](https://supabase.com/launch-week); [PostHog Launch Week I, 2022-03-23..25](https://posthog.com/blog/launch-week-universe-of-new-features); [Vercel Ship launch week: storage, 2023-05-01](https://vercel.com/blog/vercel-storage).

**`community-hackathon` — Hackathon + meetups**  
*Purpose:* Turn the launches into things others build; local presence. *Trigger:* Launch-week Friday. *Timing:* D+4..D+14 (Supabase: 10 days); winners post D+30..D+45.  
*Channels:* website, blog, x, discord, luma, youtube.  
*Assets:* page rules, prizes, dates ×1; image og/link card 1200x630 ×1; page meetup listings (Luma) × per city; text winners post with demos ×1.  
*Copy:* theme & prizes → rules & dates → submit → winners with links/demos.  
*Examples:* [Supabase LW15 hackathon](https://supabase.com/blog/lw15-hackathon); [Supabase LW12 hackathon winners, 2024-09-30](https://supabase.com/blog/lw12-hackathon-winners); [Supabase LW X community meetups](https://supabase.com/blog/community-meetups-lwx).

**`launch-week-recap` — Wrap-up / Top-10 recap**  
*Purpose:* One shareable summary for everyone who missed the week. *Trigger:* Last day of the week. *Timing:* D+4 (same Friday).  
*Channels:* blog, email, x, linkedin, youtube.  
*Assets:* text ranked list post ×1; image collage 16:9 1600x900 ×1; video recap 9:16 <=60 s ×1; email 600 px digest ×1.  
*Copy:* the week in one line → ranked list, one sentence + link each → hackathon CTA → next launch week tease.  
*Examples:* [Supabase 'Top 10 Launches of Launch Week 15', 2025-07-18](https://supabase.com/blog/launch-week-15-top-10); [Supabase 'Launch Week 6: Wrap Up', 2022-12-16](https://supabase.com/blog/launch-week-6-wrap-up); [Supabase GA Week summary](https://supabase.com/blog/ga-week-summary).

### Phase 8 — Milestones & building in public (`proof`, window `trigger-based, from D+30`)

Between releases, the numbers and the opinions are the story. Plausible grew to $1M ARR without ads, largely on milestone posts, newsjacking and one original study.

**`milestone-post` — Metric milestone post**  
*Purpose:* Social proof plus founder story; attracts press, users and hires. *Trigger:* A round-number metric (MRR/ARR, users, installs, stars). *Timing:* on trigger (Plausible: $1M ARR on 2022-06-02, post on 2022-06-22).  
*Channels:* blog, hackernews, x, linkedin, email.  
*Assets:* text 1500-3000 words with a month-by-month ledger ×1; image charts 16:9 1600x900 ×2; image og/link card 1200x630 ×1; thread X/LinkedIn summary ×1.  
*Copy:* the number → the timeline → what worked → what did not → what is next.  
*Examples:* [Plausible 'How we built a $1M ARR open source SaaS'](https://plausible.io/blog/open-source-saas); [Plausible 'bootstrapped ... to $500k ARR'](https://plausible.io/blog/bootstrapping-saas); [Home Assistant release titled 'Two Million Strong'](https://www.home-assistant.io/blog/2025/05/07/release-20255/).

**`open-metrics-page` — Open-startup metrics page**  
*Purpose:* Permanent transparency that earns trust and links. *Trigger:* Decision to build in public. *Timing:* evergreen; live or monthly refresh.  
*Channels:* website.  
*Assets:* page live dashboard: revenue, customers, traffic, team ×1; image og/link card 1200x630 ×1.  
*Copy:* why we are open → live numbers → how they are measured → link to source.  
*Examples:* [Cal.com open startup page (HN 2022-08-28)](https://cal.com/open); [Plausible's public dashboard of its own site](https://plausible.io/plausible.io).

**`research-or-opinion-post` — Original research / newsjacking / opinion piece**  
*Purpose:* Earn attention between releases with the company's viewpoint or data. *Trigger:* Industry news, or an owned data study. *Timing:* on trigger (news: within 24-72 h).  
*Channels:* blog, youtube, hackernews, x, linkedin, reddit.  
*Assets:* text 800-2000 words ×1; image charts 16:9 1600x900 ×2; video opinion video 16:9 5-15 min (optional) ×1.  
*Copy:* the news or finding → our take / our data → what it means for you → soft product mention.  
*Examples:* [Plausible adblocker study (+100% trial signups in five days) and FLoC/AMP posts](https://plausible.io/blog/open-source-saas); [PostHog 'We were wrong about product managers', 2026-06-18](https://youtu.be/pW3wlkPoFZs); [PostHog 'Your Idea Sucks. Ship It Anyway.', 2026-09-21](https://youtu.be/-8RTBTBHmEg).

### Phase 9 — Funding announcements (`funding`, window `trigger-based (first round often D+100..D+220)`)

Funding posts are written for users and future hires, not only for investors. The best ones bundle a product beat: Raycast announced its Series A together with the Store and API, and its Series B together with Windows and iOS.

**`funding-announcement` — Funding announcement**  
*Purpose:* Signal durability to users, recruit, start a press cycle. *Trigger:* Round closed. *Timing:* on trigger (PostHog D+105; Linear Series A D+161 after public launch).  
*Channels:* blog, press, x, linkedin, hackernews, youtube, email.  
*Assets:* text letter 600-1200 words ×1; image hero 16:9 1600x900 ×1; image og/link card 1200x630 ×1; video founder video 1-3 min (optional) ×1; text press exclusive brief (embargoed) ×1.  
*Copy:* thank users → progress numbers → who backed us → what the money is for (roadmap) → we are hiring.  
*Examples:* [Linear raises $13M Series A, 2020-12-08](https://medium.com/linear-app/linear-raises-13m-in-series-a-funding-from-sequoia-capital-daa0f0c43758); [Raycast Series A + Store + API, 2021-12-01](https://www.raycast.com/blog/series-a/); [Tailscale raises $100M, 2022-05-04](https://tailscale.com/blog/series-b/).

**`why-we-raised-post` — Why/how we raised (founder transparency)**  
*Purpose:* Turn a financing event into useful content for other founders. *Trigger:* After the announcement. *Timing:* funding D+0..D+7.  
*Channels:* blog, hackernews, x, linkedin.  
*Assets:* text 1000-2000 words ×1; image og/link card 1200x630 ×1.  
*Copy:* context → options considered → what we optimized for → lessons.  
*Examples:* [PostHog 'How we raised $3M for an open source project', 2020-06-04](https://posthog.com/blog/raising-3m-for-os); [PostHog 'Why we raised a $15m Series B ahead of schedule', 2021-06-17](https://posthog.com/blog/why-we-raised-a-15m-series-b-ahead-of-schedule); [Linear 'Building our way' (Series C), 2025-06-10](https://linear.app/now/building-our-way).

### Phase 10 — Community & education (recurring) (`community`, window `recurring:weekly..monthly from D+30`)

This builds an owned audience that outlives any single launch. That means a newsletter, a public method or handbook, tutorial series, and posts that spotlight community work.

**`newsletter-issue` — Newsletter issue**  
*Purpose:* Owned audience beyond users; teach, do not only announce. *Trigger:* Recurring. *Timing:* recurring:weekly..monthly.  
*Channels:* email, website, linkedin.  
*Assets:* email 600 px, header 1200x600 ×1; text 800-1500 words ×1.  
*Copy:* one lesson or opinion → 3 links → one product mention → CTA subscribe/share.  
*Examples:* [PostHog 'Product for Engineers' on Substack](https://newsletter.posthog.com/); [Tailscale monthly newsletter](https://tailscale.com/blog/2024-12-newsletter).

**`method-handbook` — Public method / handbook**  
*Purpose:* Evergreen explanation of how the company works; recruits and differentiates. *Trigger:* Once, then maintained. *Timing:* D+60..D+365, then evergreen (Linear Method D+78).  
*Channels:* website, hackernews, x.  
*Assets:* page multi-section site ×1; image og/link card 1200x630 ×1.  
*Copy:* principles → practices → examples → how to apply it yourself.  
*Examples:* [Linear Method](https://linear.app/method); [PostHog handbook (on HN 2023-10-03)](https://posthog.com/handbook).

**`tutorial-video` — Tutorial / use-case video series**  
*Purpose:* Search traffic on YouTube; real use-cases; developer relations. *Trigger:* Recurring. *Timing:* recurring:weekly.  
*Channels:* youtube, x, linkedin, instagram.  
*Assets:* video 16:9 1920x1080, 5-15 min ×1; video 9:16 1080x1920, <=60 s ×2; image thumbnail 1280x720 ×1.  
*Copy:* problem in the title → result first → steps → CTA.  
*Examples:* [Tailscale 'Free and Easy Home Assistant Remote Access with Tailscale!', 2026-07-10](https://youtu.be/fMR8uvNIilI); [Supabase 'RLS explained in less than 40s', 2026-08-30](https://youtu.be/9jbOTZqcGsI); [Raycast 'Window Management in Raycast', 2026-06-05](https://youtu.be/Ei1RIZCrZN8).

**`community-spotlight` — Community highlights / episode**  
*Purpose:* Reward contributors; social proof from real users. *Trigger:* After a launch week, or monthly. *Timing:* recurring:monthly or after each launch week.  
*Channels:* blog, youtube, x, discord.  
*Assets:* text post with featured projects ×1; video episode 20-40 min (optional) ×1; image 16:9 1600x900 ×1.  
*Copy:* what the community built → featured projects with links → how to get featured.  
*Examples:* [Supabase 'Launch Week 8 Community Highlights'](https://supabase.com/blog/launch-week-8-community-highlights); [Raycast 'Watercooler #6', 2026-07-17](https://youtu.be/mFCb5xVY5Ps).

### Phase 11 — Pricing, platform, hardware & second-product launches (`expansion`, window `trigger-based (seen D+300..D+2000)`)

Each expansion reuses the launch-day kit. Platforms get two beats: beta, then general availability about 140 days later. Hardware gets a live pre-stream. A second product re-runs the teaser, beta and launch sequence.

**`pricing-launch` — Paid tier / pricing launch**  
*Purpose:* Introduce monetization with a clear value story. *Trigger:* Paid tier ready. *Timing:* on trigger (Raycast Pro: 1,164 days after Launch HN, 77 days after its AI waitlist).  
*Channels:* blog, website, email, youtube, x.  
*Assets:* page pricing page ×1; text post ×1; video 16:9 1-2 min ×1; email 600 px ×1; image og/link card 1200x630 ×1.  
*Copy:* what stays free → what the paid tier adds → price → founding-member offer → FAQ.  
*Examples:* [Introducing Raycast Pro, 2023-05-10](https://www.raycast.com/blog/introducing-raycast-pro); [Raycast 'Update on Raycast Paid Plans', 2026-09-10](https://youtu.be/FEgUktmN3gs).

**`platform-launch` — New platform launch (beta -> GA)**  
*Purpose:* Expand reach in two beats. *Trigger:* Port ready for testers, then for everyone. *Timing:* beta, then GA ~140 days later (Arc Windows 2023-12-11 -> 2024-04-30).  
*Channels:* blog, website, x, youtube, press, email.  
*Assets:* page download / waitlist page ×1; video 16:9 60-90 s ×1; image og/link card 1200x630 ×1; email to the platform waitlist ×1.  
*Copy:* now on <platform> → what is the same / different → download or join the waitlist.  
*Examples:* [Arc for Windows GA, 2024-04-30](https://techcrunch.com/2024/04/30/the-browser-company-releases-arc-for-windows); [Raycast Series B: Windows beta + iOS waitlist, 2024-09-25](https://www.raycast.com/blog/series-b); [Dia public on Mac, 2025-10-09](https://www.macrumors.com/2025/10/09/ai-browser-dia-launches-publicly-on-mac/).

**`hardware-launch` — Hardware / physical product launch**  
*Purpose:* A physical anchor for the brand; revenue; ecosystem. *Trigger:* Product ready for pre-order or crowdfunding. *Timing:* pre-stream D-1..D0; often on the anniversary or at year end; plan an end-of-life notice years later.  
*Channels:* blog, youtube-live, x, website, press, email.  
*Assets:* livestream 16:9 30-60 min ×1; video product film 16:9 60-120 s ×1; image product shots 1:1 2000x2000 (white background) ×6; page product page with buy links ×1; text launch post ×1.  
*Copy:* who it is for → what is in the box → price & availability → where to buy.  
*Examples:* [Home Assistant Green at the HA10 livestream, 2023-09-17](https://www.home-assistant.io/blog/2023/09/17/home-assistant-green-your-entry-to-home-assistant/); [Home Assistant Voice Preview Edition, 2024-12-19](https://www.home-assistant.io/blog/2024/12/19/voice-preview-edition-the-era-of-open-voice/); [ESPHome Starter Kit 'Product Launch Pre Stream', 2026-08-12](https://youtu.be/GnXucSzzCqg).

**`second-product-reveal` — Second product reveal**  
*Purpose:* Show the company is more than one product; reuse the teaser->beta->public arc. *Trigger:* New product. *Timing:* repeats phases 2-4 (Dia: teaser D-191, public D+120 after beta).  
*Channels:* youtube, x, website, hackernews, press.  
*Assets:* video teaser + launch film (see teaser-video, launch-film) ×2; page own domain / landing ×1; text launch post ×1.  
*Copy:* same arc as the first product; say plainly what happens to the first one.  
*Examples:* [Dia teaser, 2024-12-02](https://youtu.be/C25g53PC5QQ); [Glaze by Raycast on HN, 2026-03-04](https://news.ycombinator.com/item?id=47247033).

### Phase 12 — Conference / keynote (annual) (`conference`, window `recurring:annual (announce ~D-100)`)

Once the audience is big enough, one annual stage concentrates the year's biggest launches. A launch week is often built around it (Vercel Ship 2023, TailscaleUp-date 2026), and the talk recordings keep feeding YouTube for weeks.

**`conference-announce-cfp` — Conference announcement + CFP + tickets**  
*Purpose:* Gather the community; a ~100-day runway. *Trigger:* Date and venue fixed. *Timing:* announce ~D-100 (Tailscale Up 2023: D-98), CFP closes ~D-70, early-bird tickets.  
*Channels:* blog, website, x, linkedin, email, youtube.  
*Assets:* page event site with agenda/CFP/tickets ×1; image 16:9 1600x900 + 1:1 1080x1080 ×2; email series: announce, CFP reminder, speakers, last call ×4.  
*Copy:* what / when / where → who should come → CFP formats → tickets.  
*Examples:* [Announcing 'Tailscale Up' community conference, 2023-02-22](https://tailscale.com/blog/tailscale-up-2023); [Vercel Ship 2025, NYC + online, 2025-06-25](https://vercel.com/ship/2025); [Vercel Ship 2024 call for proposals](https://ship-cfp-2024.vercel.app/).

**`keynote-livestream` — Keynote livestream + bundled launches**  
*Purpose:* The year's biggest launch moment. *Trigger:* Conference day. *Timing:* conference D0; replay the same week.  
*Channels:* youtube-live, website, x, linkedin.  
*Assets:* livestream 16:9 1920x1080, 45-90 min ×1; video per-launch clip 16:9 1-3 min ×4; text 'everything we launched' post ×1.  
*Copy:* vision → launches (each: problem, demo, availability) → customer on stage → CTA.  
*Examples:* [Vercel Ship 2024 keynote (live), 2024-05-23](https://www.youtube.com/watch?v=roRx0b_VXsU); [Tailscale Up 2026 keynote replay, 2026-09-03](https://youtu.be/j3CNNXUc4KE); [Tailscale 'Three new features launching at Tailscale Up'](https://tailscale.com/blog/three-new-features-launching-at-tailscale-up).

**`talk-recordings` — Talk recordings & workshops**  
*Purpose:* The conference's long tail on YouTube. *Trigger:* After the event. *Timing:* D+7..D+30, batch upload.  
*Channels:* youtube, website.  
*Assets:* video 16:9 per talk, 10-40 min × per talk; image thumbnail 1280x720 × per talk.  
*Copy:* talk title + speaker + event name in the title.  
*Examples:* [Vercel 'Ship 26 NYC' talks, uploaded 2026-07-20](https://youtu.be/eD8pV7nSIxY); [TailscaleUp on-demand](https://tailscale.com/tailscaleup/on-demand).

### Phase 13 — Anniversary & year-in-review (`annual`, window `recurring:annual`)

Fixed dates in the calendar: the founding day (Home Assistant launched a hardware product on its 10th birthday), an annual 'State of' address that sets the next year's theme, and a year-end recap or polish season.

**`anniversary-moment` — Birthday / anniversary moment**  
*Purpose:* Annual ritual and a natural launch slot. *Trigger:* Founding date. *Timing:* recurring:annual on the founding date.  
*Channels:* youtube-live, blog, x, instagram.  
*Assets:* livestream optional, 30-60 min ×1; video 9:16 <=60 s ×1; image 1:1 1080x1080 ×1; text post ×1.  
*Copy:* years + numbers → thank you → surprise (launch / offer).  
*Examples:* [HA10 livestream launches Home Assistant Green, 2023-09-17](https://www.home-assistant.io/blog/2023/09/17/home-assistant-green-your-entry-to-home-assistant/); [Home Assistant 'another year older' video, 2026-09-17](https://youtu.be/YakjQj2bH6I).

**`state-of-address` — Annual 'State of' address**  
*Purpose:* Vision, roadmap and survey results; sets the theme of the coming year. *Trigger:* Annual. *Timing:* recurring:annual (HA: 2024-04-20, 2025-04-12; announced 17-25 days ahead).  
*Channels:* youtube-live, blog, x, email.  
*Assets:* livestream 16:9 60-120 min ×1; text recap post ×1; image 16:9 1600x900 ×1.  
*Copy:* year in numbers → community highlights → roadmap / theme of the year → how to help.  
*Examples:* [Home Assistant 'Thinking Bigger: State of the Open Home 2024'](https://www.home-assistant.io/blog/2024/04/24/state-of-the-open-home-2024/); [Home Assistant '2023: Home Assistant's year of Voice', 2022-12-20](https://www.home-assistant.io/blog/2022/12/20/year-of-voice/).

**`year-in-review` — Year-in-review / 'Wrapped' / polish season**  
*Purpose:* End-of-year shareable; personalized recaps spread themselves. *Trigger:* December. *Timing:* recurring:annual (December).  
*Channels:* website, x, linkedin, instagram, email.  
*Assets:* image per-user card 9:16 1080x1920 + 1200x630 × per user; page recap page ×1; text post ×1.  
*Copy:* your / our year in numbers → highlights → thanks → what is next.  
*Examples:* [Raycast Wrapped, 2022-12-19](https://twitter.com/raycastapp/status/1604868675277725697); [Linear 'Polishing Season 2022'](https://linear.app/changelog/polishing/2022).

### Phase 14 — Transitions: pivots, licence changes, incidents, end-of-life, exits (`transition`, window `trigger-based`)

Every tail that was followed long enough contains one of these. Companies that wrote them as open letters kept goodwill. The slot should exist before it is needed.

**`open-letter` — Open letter (pivot / licence / sunset)**  
*Purpose:* Explain a hard change honestly to existing users. *Trigger:* Strategic change that affects users. *Timing:* on trigger; before the change takes effect.  
*Channels:* blog, email, x, youtube.  
*Assets:* text 1000-2500 words ×1; video CEO 3-10 min (optional) ×1; email to all users ×1; page FAQ ×1.  
*Copy:* what is changing → why (honestly) → what it means for you (support, data, price) → what is next → thank you.  
*Examples:* ['Letter to Arc members 2025', 2025-05-27](https://browsercompany.substack.com/p/letter-to-arc-members-2025); ['Cal.com is going closed source', 2026-04-15](https://cal.com/blog/cal-com-goes-closed-source-why); ['Ending production of Home Assistant Yellow', 2025-10-15](https://www.home-assistant.io/blog/2025/10/15/yellow-end-of-life/).

**`incident-report` — Incident / security report**  
*Purpose:* Protect trust when something breaks. *Trigger:* Incident or disclosure. *Timing:* first note within 24 h; full report within ~1-2 weeks.  
*Channels:* blog, website, email, x.  
*Assets:* text report ×1; page status page entry ×1; email to affected users ×1.  
*Copy:* what happened → impact → what we did → what we will change.  
*Examples:* [Tailscale 'Tailscale didn't stop the Hugging Face intrusion', 2026-07-31](https://tailscale.com/blog/hugging-face-intrusion); [Supabase 'Alpha Launch Postmortem'](https://supabase.com/blog/alpha-launch-postmortem).

**`acquisition-announcement` — Acquisition / new-chapter announcement**  
*Purpose:* Reassure users and tell the next chapter of the story. *Trigger:* Deal signed. *Timing:* on signing.  
*Channels:* youtube, blog, x, press.  
*Assets:* video 16:9 2-5 min ×1; text letter ×1.  
*Copy:* the news → why this partner → what does not change for users → what gets better.  
*Examples:* [The Browser Company 'We have entered an agreement to be acquired by Atlassian', 2025-09-04](https://youtu.be/u0GljxGVBE4); ['Your Tuesday in 2030' (Substack), 2025-09-04](https://browsercompany.substack.com/p/your-tuesday-in-2030).

---

## 3. Cadence table — what repeats, how often, and who does it

| Repeating unit (skeleton id) | Cadence | Companies (evidence) |
|---|---|---|
| Changelog entry (`changelog-entry`) | weekly or every release | Linear (8 entries 2026-07-20..09-24), PostHog (weekly), Raycast (per version; "bi-weekly releases"), Supabase and Vercel (continuous changelogs; cadence not measured) |
| Changelog digest email (`changelog-digest-email`) | every 2 weeks · monthly | PostHog (bi-weekly, Customer.io) · Tailscale (monthly newsletter as a blog post) |
| Newsletter (`newsletter-issue`) | regular (cadence not verified) | PostHog "Product for Engineers" (Substack) |
| Monthly release notes post (`monthly-update-post`) | monthly | Home Assistant (YYYY.M, themed titles); Supabase "Beta <Month>" (found 2020-12 … 2023-10) |
| Release livestream (`release-livestream`) | monthly (release day) · weekly | Home Assistant Release Party, 20:00 GMT; Supabase Weekly Changelog Live Stream (Ep 14 on 2026-09-28) |
| Pre-release / beta stream | monthly | Home Assistant "Pre-Release Not a Release Party" |
| What's-new / "Introducing X" video (`whats-new-video`) | per release (the next day) · per feature | Home Assistant, Linear, Raycast |
| Tutorial / explainer videos (`tutorial-video`) | weekly | Tailscale DevRel, Supabase shorts, Raycast feature series |
| Launch week (`launch-week-hub` … `launch-week-recap`) | every ~4–5 months (~3×/year) | Supabase (LW1 2021-03 → LW15 2025-07, plus GA Week 2024-04); PostHog once (2022-03); Vercel Ship (2023-05, then conferences); Tailscale "TailscaleUp-date" (2026) |
| Hackathon + meetups (`community-hackathon`) | per launch week (10 days) | Supabase (40+ meetups in LW15) |
| Community highlights (`community-spotlight`) | per launch week · monthly | Supabase; Raycast "Watercooler" episodes |
| Conference + keynote (`conference-announce-cfp`, `keynote-livestream`, `talk-recordings`) | annual (Vercel now several cities a year) | Vercel Next.js Conf (since 2020-10-27) and Ship (2024-05-23, 2025-06-25, Ship AI 2025-10-23, Ship 26 NYC + SF 2026-10-15..16); Tailscale Up (2023-05-31; 2026) |
| "State of" address (`state-of-address`) | annual | Home Assistant State of the Open Home (2021 page, 2022, 2024-04-20, 2025-04-12) |
| Birthday (`anniversary-moment`) | annual (09-17) | Home Assistant (HA10 launched Green in 2023; video in 2026) |
| Themed year with chapters | annual theme; a chapter every few months | Home Assistant "Year of the Voice" (2023) |
| Year-in-review / Wrapped / polish season (`year-in-review`) | annual (December) | Raycast Wrapped (2022-12-19); Linear Polishing Season (2022-12) |
| Milestone post (`milestone-post`) | when a threshold is reached (months apart) | Plausible ($500k ARR 2021-10 → $1M ARR 2022-06); Home Assistant "Two Million Strong" (2025-05) |
| Funding announcement (`funding-announcement`) | per round, every ~1–3 years | Linear 2019-11 / 2020-12 / 2023-09 / 2025-06; Tailscale 2020-11 / 2022-05 / 2025-04; PostHog 2020-06 / 2021-06 / 2025-06 |
| Named / versioned relaunch (`first-big-update`) | about yearly | Cal.com v1 (2021) / v2 (2022) / v3 (2023); Arc 1.0 → Max; Raycast 2.0 (2026-09) |
| Brand / opinion films | 1–3 per quarter | Linear (2026: three short films), PostHog (opinion videos, ads) |

**Composite default cadence for a small startup**, with the Linear/PostHog/HA/Supabase habits scaled down:
- a changelog entry per release (weekly);
- a digest email every 2 weeks or monthly;
- one monthly post plus one release livestream or recap video;
- a launch week about every 4 months;
- one annual set piece: birthday or "State of", plus a year-in-review in December.

---

## 4. Anti-patterns — what visibly failed, or what these companies stopped doing

1. **Launching without capacity.** Supabase's alpha launch hit DigitalOcean's 400-server cap and then its 1,000-server
   cap. It also hit Cloudflare's 1,000-subdomain limit at 4 am, which caused a 3-hour outage. The company moved 1,800
   servers to AWS over 3 weeks
   ([postmortem](https://supabase.com/blog/alpha-launch-postmortem)).
   *Lesson:* the launch-day checklist must include provider quotas and a status page. The honest postmortem then
   became trusted content in its own right.
2. **Treating Product Hunt as a growth channel.** Plausible got "only 20 visitors a few days later", a "spike of hope
   followed by flat line". Its growth came from word of mouth, HN posts and content
   ([source](https://plausible.io/blog/open-source-saas)).
   *Lesson:* treat Product Hunt as a badge, never the main plan.
3. **Asking for donations instead of charging.** Plausible received about 6 donations of $5 in six months. Over the
   same period its paid product was earning more than $8,500 MRR (same source).
4. **Teasing far ahead of the product and leaving the old product's fate open.** The Dia teaser (2024-12-02) targeted
   "early 2025" ([Wikipedia](https://en.wikipedia.org/wiki/The_Browser_Company)); the beta opened 2025-06-11, 191
   days later. In between, Arc users learned from a letter (2025-05-27)
   that Arc feature development had stopped. Earlier, the "Act II" video (2024-02-01) had promised a new direction
   for Arc itself.
   *Lesson:* keep the gap from teaser to beta under ~90 days. When a second product arrives, say in the same message
   what happens to the first.
5. **Changing the openness contract late.** Cal.com built its identity on being the open-source Calendly (2021) and
   an "Open Startup" (2022). It announced closed source on 2026-04-15 (HN, 391 pts), and a community edition,
   Cal.diy, followed 6 days later. Plausible, by contrast, changed its licence to AGPL in 2020-10, before most of its
   users arrived.
   *Lesson:* licence and pricing contract changes cost less the earlier they come. They need the `open-letter` unit,
   an FAQ and a path forward for existing users.
6. **Community on rented, unsearchable ground.** PostHog closed its Slack community on 2024-01-14 and moved to an owned
   forum ([blog](https://posthog.com/blog/slack-closure)). Linear moved its announcements from Medium (2019–2020) to
   linear.app (2023+).
   *Lesson:* the canonical URL of every unit should live on the company's own domain.
7. **Big-bang only.** PostHog ran one Launch Week (2022-03), and its handbook now prescribes "rolling" launches that
   teams ship independently rather than coordinated big-bang events
   ([handbook](https://posthog.com/handbook/marketing/product-announcements)).
   Supabase's weeks grew to 5 main-stage and 6 "build stage" launches (LW15), so every week now ends with a "Top 10"
   recap.
   *Lesson:* a launch week needs a steady release train underneath it, and features should never be held back only
   to fill the week.
8. **Hardware and integration tails you did not plan for.** Home Assistant ended production of the Yellow on
   2025-10-15, about four years after crowdfunding it. It also had to remove its myQ integration after the vendor
   blocked access ([2023-11-06](https://www.home-assistant.io/blog/2023/11/06/removal-of-myq-integration/),
   HN 1,181 pts).
   *Lesson:* each hardware or partner launch implies a future end-of-life or removal post.
9. **Letting third parties tell the incident story first.** Two of the most-voted HN stories about these companies
   were third-party researcher write-ups: the top Arc story (2024-09-19, 1,469 pts) and Supabase MCP (2025-07-08,
   848 pts, second only to Supabase's own launch). Tailscale, by contrast, published its own
   plain account of the Hugging Face intrusion (2026-07-31, 627 pts).
   *Lesson:* keep the `incident-report` slot pre-built, with a template, an owner and the status page.
10. **(Caution, not a proven failure) A waitlist used only as scarcity.** Arc stayed invite-only for 462 days, and
    dropping the waitlist was itself the 1.0 news. Linear stayed invite-only for 439 days but used the waitlist as
    research: a survey, about 10 hand-picked invites a week, and a new build for every cohort.
    *Lesson:* a waitlist should ask something and teach something.

---

## Appendix — machine-readable skeleton

The block below and Section 2 are generated from the same data, so they list the same 14 phases and 45 units. It
parses as YAML (checked with Ruby's YAML loader), and every scalar is double-quoted.

```yaml
# startup-tail-skeleton
# Generated from research/startup-patterns.md (2026-09-29). D0 = public launch day.
# Channel ids: website, blog, email, x, linkedin, facebook, instagram, youtube, youtube-live,
# github, discord, whatsapp, hackernews, producthunt, reddit, press, luma, rss.
phases:
  - id: "stealth"
    name: "Pre-launch / stealth"
    order: 1
    window: "D-180..D-60"
    units:
      - id: "holding-page"
        name: "Holding page with email capture"
        purpose: "Claim the name/domain, collect early interest, create the first public trace every later asset links back to."
        trigger: "Name and domain decided."
        timing: "D-180..D-60 (Supabase: first archived capture D-78)"
        channels: ["website", "github", "x"]
        assets:
          - {kind: "page", spec: "single section: logo, one-line promise, email field", count: 1}
          - {kind: "image", spec: "og/link card 1200x630 (1.91:1)", count: 1}
          - {kind: "image", spec: "X header 1500x500 (3:1)", count: 1}
          - {kind: "image", spec: "GitHub social preview 1280x640 (2:1)", count: 1}
        copy: "one-line promise -> who it is for -> 'get early access' email field -> (optional) who is building it"
        examples:
          - "supabase.io, first archived 2020-03-10, 78 days before the HN launch - https://web.archive.org/web/20200310080644/https://supabase.io/"
          - "diabrowser.com holding page at the Dia teaser, 2024-12-02 - https://news.ycombinator.com/item?id=42298063"
          - "Raycast AI waitlist page, 2023-02-22 - https://www.raycast.com/ai"
      - id: "founder-thesis-post"
        name: "Founder thesis / manifesto post"
        purpose: "Frame the problem and the worldview so the later reveal has a story and a vocabulary."
        trigger: "Before or together with the first public announcement."
        timing: "D-120..D0"
        channels: ["blog", "x", "linkedin", "hackernews", "email"]
        assets:
          - {kind: "text", spec: "article 800-1500 words", count: 1}
          - {kind: "image", spec: "hero 16:9 1600x900", count: 1}
          - {kind: "thread", spec: "5-8 posts (X) / 1 long post (LinkedIn)", count: 1}
        copy: "the broken status quo -> why now -> our principles -> what we are building (no full screenshots) -> join the waitlist"
        examples:
          - "Linear: 'Announcing Linear' Medium post + tweet + waitlist, 2019-04 - https://review.firstround.com/linears-path-to-product-market-fit/"
          - "Linear Method (practices for building), on HN 2020-09-16 - https://linear.app/method"
          - "Plausible: viral 'why you should stop using Google Analytics' post, 2020-04 (listed in) - https://plausible.io/blog/open-source-saas"
  - id: "teaser"
    name: "Teaser"
    order: 2
    window: "D-200..D-3"
    units:
      - id: "teaser-video"
        name: "Teaser / early-peek video"
        purpose: "Create curiosity (and recruit talent) without full disclosure."
        trigger: "Product direction fixed; beta date within ~6 months."
        timing: "D-190..D-30 (Dia: D-191)"
        channels: ["youtube", "x", "linkedin", "instagram", "website"]
        assets:
          - {kind: "video", spec: "16:9 1920x1080, 60-180 s", count: 1}
          - {kind: "video", spec: "9:16 1080x1920 cut, <=60 s", count: 1}
          - {kind: "image", spec: "YouTube thumbnail 1280x720", count: 1}
          - {kind: "page", spec: "teaser landing with waitlist field", count: 1}
        copy: "tension (what is wrong today) -> glimpse (fragments of UI, people, process) -> name + 'coming <season>' -> CTA: waitlist / we are hiring"
        examples:
          - "Dia: 'An early peek at Dia, our second product | A recruiting video', 2024-12-02 - https://youtu.be/C25g53PC5QQ"
          - "TechCrunch coverage of the Dia teaser, 2024-12-02 - https://techcrunch.com/2024/12/02/the-browser-company-teases-dia-its-new-ai-browser/"
          - "Raycast AI waitlist page 77 days before Raycast Pro, 2023-02-22 - https://www.raycast.com/ai"
      - id: "save-the-date"
        name: "Save-the-date / countdown"
        purpose: "Lock a date in people's calendars and turn followers into reminders."
        trigger: "Date of the launch, launch week or livestream fixed."
        timing: "D-30..D-3 (Supabase LW1 announced D-4; HA State of the Open Home 2025 announced D-17)"
        channels: ["blog", "x", "linkedin", "youtube", "email", "discord", "whatsapp"]
        assets:
          - {kind: "image", spec: "16:9 1600x900", count: 1}
          - {kind: "image", spec: "1:1 1080x1080", count: 1}
          - {kind: "image", spec: "story 9:16 1080x1920", count: 1}
          - {kind: "livestream", spec: "scheduled YouTube premiere/live page ('Notify me')", count: 1}
          - {kind: "email", spec: "600 px wide, one CTA", count: 1}
        copy: "what (event name) -> when (date + time in 3 time zones) -> what you will get -> reminder CTA ('Notify me' / add to calendar)"
        examples:
          - "Supabase 'Launch week - Five days of Supabase', posted 2021-03-25 - https://supabase.com/blog/launch-week"
          - "Home Assistant 'Announcing State of the Open Home 2025', 2025-03-26 for 2025-04-12 - https://www.home-assistant.io/blog/2025/03/26/state-of-the-open-home-2025-announcement/"
          - "Home Assistant save-the-date post on X for State of the Open Home 2024 - https://x.com/home_assistant/status/1772744406615175341"
  - id: "waitlist"
    name: "Waitlist / invite-only beta"
    order: 3
    window: "D-460..D-1"
    units:
      - id: "waitlist-survey"
        name: "Waitlist with qualifying survey"
        purpose: "Measure demand, pick fitting early users, learn their problems in their words."
        trigger: "Teaser or thesis published."
        timing: "opens D-460..D-90, stays open until public launch"
        channels: ["website", "email"]
        assets:
          - {kind: "page", spec: "form: email + 2-3 questions (use case, current tool, team size)", count: 1}
          - {kind: "email", spec: "confirmation, 600 px, plain", count: 1}
          - {kind: "image", spec: "og/link card 1200x630", count: 1}
        copy: "promise -> 'why do you want it / what is your current problem?' -> honest expectation (small weekly batches) -> share link"
        examples:
          - "Linear private beta: ~10,000 emails, ~10 hand-picked invites per week - https://review.firstround.com/linears-path-to-product-market-fit/"
          - "Karri Saarinen on hand-picking waitlist invites - https://x.com/karrisaarinen/status/1785391264730669351"
          - "Arc drops its waitlist at 1.0, 2023-07-25 - https://9to5mac.com/2023/07/25/arc-browser-no-waitlist/"
      - id: "cohort-invite-email"
        name: "Cohort invite + beta build note"
        purpose: "Onboard a small batch, open a feedback loop, ship a new build per cohort."
        trigger: "New cohort selected."
        timing: "recurring:weekly during the beta"
        channels: ["email", "discord"]
        assets:
          - {kind: "email", spec: "personal plain-text invite from a founder", count: 1}
          - {kind: "text", spec: "beta release note (what changed since last cohort)", count: 1}
        copy: "personal note -> what is new since the last cohort -> what we want feedback on -> how to reach us"
        examples:
          - "Linear: a new version for every weekly cohort of ~10 users - https://review.firstround.com/linears-path-to-product-market-fit/"
          - "Arc: ~100 NDA testers before the public invite-only period - https://en.wikipedia.org/wiki/The_Browser_Company"
  - id: "launch-day"
    name: "Reveal / launch day"
    order: 4
    window: "D0"
    units:
      - id: "launch-post"
        name: "Launch post (canonical)"
        purpose: "The one page every other channel links to."
        trigger: "Product (or public beta) available to anyone."
        timing: "D0, fixed hour (Supabase publishes at 08:00 PT)"
        channels: ["blog", "website", "email", "x", "linkedin", "facebook", "hackernews", "producthunt"]
        assets:
          - {kind: "text", spec: "600-1200 words", count: 1}
          - {kind: "image", spec: "hero 16:9 1600x900", count: 1}
          - {kind: "image", spec: "og/link card 1200x630", count: 1}
          - {kind: "animation", spec: "MP4/GIF product loop 5-15 s, 16:9", count: 3}
          - {kind: "email", spec: "announcement 600 px", count: 1}
        copy: "hook (one-line promise) -> the problem -> what it is + 3 capabilities (one loop each) -> proof (users, numbers, quotes) -> availability & price -> CTA -> what is next"
        examples:
          - "Arc 1.0 available to everyone, 2023-07-25 - https://techcrunch.com/2023/07/25/arc-browser-is-now-available-to-download-for-everyone"
          - "Calendso rebrands to Cal.com and launches v1.0 - https://cal.com/blog/calendso-rebrands-to-cal-com"
          - "Linear public launch on HN, 2020-06-30 - https://news.ycombinator.com/item?id=23693029"
      - id: "launch-film"
        name: "Launch film"
        purpose: "The shareable 'what it feels like' asset."
        trigger: "Launch day."
        timing: "D0 (premiere at post time)"
        channels: ["youtube", "x", "linkedin", "instagram", "facebook", "website", "producthunt"]
        assets:
          - {kind: "video", spec: "16:9 1920x1080, 60-120 s master", count: 1}
          - {kind: "video", spec: "9:16 1080x1920 cut, <=60 s", count: 1}
          - {kind: "video", spec: "1:1 1080x1080 cut, <=60 s", count: 1}
          - {kind: "image", spec: "thumbnail 1280x720", count: 1}
          - {kind: "text", spec: "subtitles he/en (SRT)", count: 2}
        copy: "cold open on a real pain -> name + promise -> 3 moments of use -> availability -> CTA"
        examples:
          - "Dia 'Never Explain Yourself Again', 2025-06-11 - https://youtu.be/YVOw0TAO9ok"
          - "Arc Max film, 2023-10-03 - https://www.youtube.com/watch?v=y7koAGLf0EE"
          - "NuPhy x Raycast keyboard film, 2026-08-27 - https://youtu.be/73pdeHCGerA"
      - id: "hn-launch"
        name: "Launch HN / Show HN post"
        purpose: "Reach developers and early adopters in an honest founder voice."
        trigger: "Launch day (YC companies: 'Launch HN')."
        timing: "D0, US morning"
        channels: ["hackernews"]
        assets:
          - {kind: "text", spec: "title <=80 chars", count: 1}
          - {kind: "text", spec: "founder first comment 300-600 words", count: 1}
        copy: "who we are -> the problem we hit ourselves -> what we built and how it differs -> open source / pricing -> ask for feedback"
        examples:
          - "Supabase (YC S20), 2020-05-27, 1,120 points - https://news.ycombinator.com/item?id=23319901"
          - "Launch HN: PostHog (YC W20), 2020-02-20 - https://news.ycombinator.com/item?id=22376732"
          - "Calendso: an open source Calendly alternative, 2021-04-15 - https://news.ycombinator.com/item?id=26817795"
      - id: "product-hunt-launch"
        name: "Product Hunt launch"
        purpose: "Badge and one-day spike of social proof; not a lasting channel."
        trigger: "Launch or a major version."
        timing: "D0 at 00:01 PT"
        channels: ["producthunt", "x", "linkedin", "email"]
        assets:
          - {kind: "image", spec: "thumbnail 240x240 (GIF allowed)", count: 1}
          - {kind: "image", spec: "gallery 1270x760", count: 5}
          - {kind: "video", spec: "YouTube link of the launch film", count: 1}
          - {kind: "text", spec: "tagline <=60 chars + maker comment", count: 1}
        copy: "tagline -> maker comment (story + launch offer) -> gallery, one image per capability"
        examples:
          - "Calendso on Product Hunt: 2,100+ upvotes (per Cal.com) - https://cal.com/blog/calendso-rebrands-to-cal-com"
          - "Plausible on Product Hunt 2020-08: 'spike of hope followed by flat line' - https://plausible.io/blog/open-source-saas"
          - "Supabase includes Product Hunt in its launch playbook - https://supabase.com/blog/supabase-how-we-launch"
      - id: "social-launch-thread"
        name: "Native launch thread / carousel"
        purpose: "Tell the story in each network's native format instead of a bare link."
        trigger: "Launch post live."
        timing: "D0, +0..2 h after the post"
        channels: ["x", "linkedin", "instagram", "facebook", "discord", "whatsapp"]
        assets:
          - {kind: "thread", spec: "X thread 5-10 posts", count: 1}
          - {kind: "image", spec: "16:9 1600x900 per capability", count: 4}
          - {kind: "image", spec: "carousel 4:5 1080x1350 (Instagram) / PDF 1080x1350 (LinkedIn)", count: 8}
          - {kind: "text", spec: "Discord announcement + WhatsApp channel update", count: 2}
        copy: "post 1 = hook + film -> one capability per post with a visual -> proof -> link -> credits/thanks"
        examples:
          - "'Everything launched at Next.js Conf' thread, 2022-10 - https://twitter.com/leeerob/status/1585349567410626560"
          - "Supabase daily rhythm: 07:30 reminder tweet, 08:00 blog post - https://supabase.com/blog/supabase-how-we-launch"
  - id: "post-launch"
    name: "Post-launch: postmortem and first big update"
    order: 5
    window: "D+1..D+180"
    units:
      - id: "launch-postmortem"
        name: "Launch postmortem / numbers post"
        purpose: "Convert the launch into trust: the numbers, what broke, what changed."
        trigger: "Launch spike settled."
        timing: "D+30..D+60 (Supabase: D+44)"
        channels: ["blog", "hackernews", "x", "linkedin"]
        assets:
          - {kind: "text", spec: "1000-2000 words", count: 1}
          - {kind: "image", spec: "charts 16:9 1600x900", count: 3}
          - {kind: "image", spec: "og/link card 1200x630", count: 1}
        copy: "what happened (numbers) -> what broke and why -> what we changed -> thanks -> what is next"
        examples:
          - "Supabase 'Alpha Launch Postmortem', 2020-07-10 - https://supabase.com/blog/alpha-launch-postmortem"
          - "PostHog 'How we raised $3M for an open source project', D+105 - https://posthog.com/blog/raising-3m-for-os"
      - id: "first-big-update"
        name: "First named update / version reveal"
        purpose: "Prove momentum and re-open the story to press and communities."
        trigger: "A feature set big enough to get its own name (1.0, v2, 'Max')."
        timing: "D+60..D+180 (Arc Max D+70; Cal.com v1.0 D+155)"
        channels: ["blog", "youtube", "x", "linkedin", "producthunt", "hackernews", "email"]
        assets:
          - {kind: "video", spec: "16:9 1920x1080, 60-120 s", count: 1}
          - {kind: "page", spec: "named landing (e.g. /max)", count: 1}
          - {kind: "image", spec: "og/link card 1200x630", count: 1}
          - {kind: "text", spec: "post 600-1000 words", count: 1}
          - {kind: "email", spec: "600 px", count: 1}
        copy: "name the update -> the one big idea -> 3 capabilities -> who it is for / price -> CTA update or try"
        examples:
          - "Arc Max page, 2023-10-03 - https://arc.net/max"
          - "Cal.com (formerly Calendso) on HN, 2021-09-17 - https://news.ycombinator.com/item?id=28568789"
          - "Cal.com v2, 2022-09-16 - https://news.ycombinator.com/item?id=32866261"
  - id: "release-train"
    name: "Release train (recurring)"
    order: 6
    window: "recurring:weekly..monthly from D+1"
    units:
      - id: "changelog-entry"
        name: "Changelog entry"
        purpose: "Steady proof of shipping; one linkable unit per feature."
        trigger: "Every release."
        timing: "recurring:weekly (Linear, PostHog) or every release (Raycast, bi-weekly)"
        channels: ["website", "x", "linkedin", "discord", "rss"]
        assets:
          - {kind: "page", spec: "entry with anchor/permalink", count: 1}
          - {kind: "image", spec: "hero 16:9 1600x900 or MP4 loop 5-15 s", count: 1}
          - {kind: "text", spec: "lists: Improvements, Fixes", count: 1}
        copy: "headline feature (benefit in <=8 words) -> visual -> how to use (2-3 sentences + docs link) -> Improvements -> Fixes"
        examples:
          - "Linear changelog - https://linear.app/changelog"
          - "Raycast changelog 1.56.0, 2023-07-27 - https://www.raycast.com/changelog/1-56-0"
          - "PostHog changelog - https://posthog.com/changelog"
      - id: "changelog-digest-email"
        name: "Changelog digest email"
        purpose: "Bring existing users back to new features."
        trigger: "Recurring."
        timing: "recurring:biweekly (PostHog) or monthly (Tailscale)"
        channels: ["email", "blog"]
        assets:
          - {kind: "email", spec: "600 px, 3-6 items, hero 1200x600", count: 1}
          - {kind: "page", spec: "web version of the email", count: 1}
        copy: "top feature -> 3-5 shorter items -> one community story -> CTA 'see the full changelog'"
        examples:
          - "PostHog bi-weekly changelog email (handbook) - https://posthog.com/handbook/brand/email-comms"
          - "Tailscale monthly newsletter, December 2024 - https://tailscale.com/blog/2024-12-newsletter"
      - id: "monthly-update-post"
        name: "Monthly release notes / update post"
        purpose: "One narrative per month that ties the releases together."
        trigger: "Monthly release or month end."
        timing: "recurring:monthly (HA on release day; Supabase 'Beta <Month>' 2020-2023)"
        channels: ["blog", "email", "x", "linkedin", "discord"]
        assets:
          - {kind: "text", spec: "long post with a theme title", count: 1}
          - {kind: "image", spec: "hero 16:9 1600x900", count: 1}
          - {kind: "image", spec: "og/link card 1200x630", count: 1}
          - {kind: "animation", spec: "feature loops 5-15 s", count: 5}
        copy: "theme headline ('YYYY.M: <theme>') -> highlights -> full list -> breaking changes -> thanks to contributors -> CTA upgrade"
        examples:
          - "Home Assistant '2025.5: Two Million Strong and Getting Better' - https://www.home-assistant.io/blog/2025/05/07/release-20255/"
          - "Supabase Beta December 2020 - https://supabase.com/blog/supabase-beta-december-2020"
          - "Supabase Beta October 2023 - https://supabase.com/blog/beta-update-october-2023"
      - id: "release-livestream"
        name: "Release party / changelog livestream"
        purpose: "A human face and live Q&A for each release; a community ritual."
        trigger: "Release day."
        timing: "recurring:monthly on release day, 20:00 GMT (HA); recurring:weekly (Supabase, 2026); beta-week pre-stream (HA)"
        channels: ["youtube-live", "x", "discord"]
        assets:
          - {kind: "livestream", spec: "16:9 1920x1080, 45-90 min", count: 1}
          - {kind: "image", spec: "thumbnail 1280x720", count: 1}
          - {kind: "video", spec: "highlight clips 9:16 1080x1920 <=60 s", count: 3}
        copy: "welcome -> highlights demo -> contributor shout-outs -> Q&A -> CTA update now"
        examples:
          - "Home Assistant 2026.9 Release Party, 2026-09-02 - https://youtu.be/TgGiUchnmDw"
          - "Supabase Weekly Changelog Live Stream Ep 14, 2026-09-28 - https://youtu.be/QmJY5foN2gs"
          - "Home Assistant 'Pre-Release Not a Release Party', 2026-06-25 - https://youtu.be/n3HghFZQCiA"
      - id: "whats-new-video"
        name: "What's-new recap / 'Introducing X' video"
        purpose: "Short evergreen explainer per release or per feature."
        trigger: "Release or feature shipped."
        timing: "D+1 after each release (HA); with each feature (Linear, Raycast)"
        channels: ["youtube", "x", "linkedin", "instagram"]
        assets:
          - {kind: "video", spec: "16:9 1920x1080, 1-6 min", count: 1}
          - {kind: "video", spec: "9:16 1080x1920, <=60 s", count: 2}
          - {kind: "image", spec: "thumbnail 1280x720", count: 1}
        copy: "what is new in <version> -> 3-5 features demoed -> 'update now'"
        examples:
          - "'What's New in Home Assistant 2026.8', 2026-08-06 - https://youtu.be/2NadKNdVHNs"
          - "Linear 'Introducing Linear Diffs', 2026-05-28 - https://youtu.be/7gZBxBTapDQ"
          - "Raycast 'Introducing Raycast Dictation', 2026-06-18 - https://youtu.be/RUh1KDgSOsc"
  - id: "launch-week"
    name: "Launch week (recurring)"
    order: 7
    window: "recurring:quarterly..3x-per-year (each week spans D-21..D+45)"
    units:
      - id: "launch-week-hub"
        name: "Launch-week hub page + announcement"
        purpose: "One place for the week; date lock; partner/press coordination."
        trigger: "3-5 launches ready for the same week."
        timing: "press briefed D-21; integrations frozen D-7; public announcement D-14..D-4"
        channels: ["website", "blog", "x", "linkedin", "email", "discord", "youtube"]
        assets:
          - {kind: "page", spec: "hub with 5 day-slots + countdown + ticket CTA", count: 1}
          - {kind: "image", spec: "og/link card 1200x630", count: 1}
          - {kind: "video", spec: "trailer 16:9, 30-60 s", count: 1}
          - {kind: "email", spec: "announcement 600 px", count: 1}
        copy: "N days, N launches -> dates & hour -> claim your ticket / get reminders -> hackathon & meetups"
        examples:
          - "Supabase Launch Week 15 hub (2025-07-14..18) - https://supabase.com/launch-week"
          - "Supabase Launch Week X (2023-12-11..15) - https://supabase.com/launch-week/x"
          - "Tailscale 'TailscaleUp-date' week, 2026 - https://tailscale.com/tailscaleup-date-week-26"
      - id: "personal-ticket"
        name: "Personalized ticket / badge"
        purpose: "Make every sign-up a distributor of the launch."
        trigger: "Hub page live."
        timing: "D-14..D+4"
        channels: ["website", "x", "linkedin"]
        assets:
          - {kind: "image", spec: "generated per person, 1200x630 (og)", count: "per sign-up"}
          - {kind: "image", spec: "'golden' variant unlocked by sharing", count: "per sharer"}
          - {kind: "page", spec: "ticket wall", count: 1}
        copy: "'I'm in' + name/avatar + dates -> share to unlock (golden ticket / swag)"
        examples:
          - "Supabase LW7: AI-art ticket per user, golden ticket for sharing on X and LinkedIn - https://supabase.com/blog/designing-with-ai-midjourney"
          - "Next.js Conf 2021 'claim your ticket' - https://news.ycombinator.com/item?id=27201209"
      - id: "daily-drop"
        name: "Daily launch (day N of 5)"
        purpose: "One headline per day holds attention for a whole week."
        trigger: "Each day of the week."
        timing: "D0..D+4 at a fixed hour (Supabase 08:00 PT)"
        channels: ["blog", "youtube", "x", "linkedin", "hackernews", "producthunt", "discord"]
        assets:
          - {kind: "text", spec: "launch post", count: "1 per day"}
          - {kind: "video", spec: "demo 16:9, 2-5 min", count: "1 per day"}
          - {kind: "image", spec: "og/link card 1200x630", count: "1 per day"}
          - {kind: "thread", spec: "X/LinkedIn post", count: "1 per day"}
          - {kind: "image", spec: "story 9:16 1080x1920", count: "1 per day"}
        copy: "Day N of 5 -> feature name -> why it matters -> demo -> docs link -> tomorrow's teaser"
        examples:
          - "Supabase LW15: one main-stage launch per day + 6 'build stage' extras - https://supabase.com/launch-week"
          - "PostHog Launch Week I, 2022-03-23..25 - https://posthog.com/blog/launch-week-universe-of-new-features"
          - "Vercel Ship launch week: storage, 2023-05-01 - https://vercel.com/blog/vercel-storage"
      - id: "community-hackathon"
        name: "Hackathon + meetups"
        purpose: "Turn the launches into things others build; local presence."
        trigger: "Launch-week Friday."
        timing: "D+4..D+14 (Supabase: 10 days); winners post D+30..D+45"
        channels: ["website", "blog", "x", "discord", "luma", "youtube"]
        assets:
          - {kind: "page", spec: "rules, prizes, dates", count: 1}
          - {kind: "image", spec: "og/link card 1200x630", count: 1}
          - {kind: "page", spec: "meetup listings (Luma)", count: "per city"}
          - {kind: "text", spec: "winners post with demos", count: 1}
        copy: "theme & prizes -> rules & dates -> submit -> winners with links/demos"
        examples:
          - "Supabase LW15 hackathon - https://supabase.com/blog/lw15-hackathon"
          - "Supabase LW12 hackathon winners, 2024-09-30 - https://supabase.com/blog/lw12-hackathon-winners"
          - "Supabase LW X community meetups - https://supabase.com/blog/community-meetups-lwx"
      - id: "launch-week-recap"
        name: "Wrap-up / Top-10 recap"
        purpose: "One shareable summary for everyone who missed the week."
        trigger: "Last day of the week."
        timing: "D+4 (same Friday)"
        channels: ["blog", "email", "x", "linkedin", "youtube"]
        assets:
          - {kind: "text", spec: "ranked list post", count: 1}
          - {kind: "image", spec: "collage 16:9 1600x900", count: 1}
          - {kind: "video", spec: "recap 9:16 <=60 s", count: 1}
          - {kind: "email", spec: "600 px digest", count: 1}
        copy: "the week in one line -> ranked list, one sentence + link each -> hackathon CTA -> next launch week tease"
        examples:
          - "Supabase 'Top 10 Launches of Launch Week 15', 2025-07-18 - https://supabase.com/blog/launch-week-15-top-10"
          - "Supabase 'Launch Week 6: Wrap Up', 2022-12-16 - https://supabase.com/blog/launch-week-6-wrap-up"
          - "Supabase GA Week summary - https://supabase.com/blog/ga-week-summary"
  - id: "proof"
    name: "Milestones & building in public"
    order: 8
    window: "trigger-based, from D+30"
    units:
      - id: "milestone-post"
        name: "Metric milestone post"
        purpose: "Social proof plus founder story; attracts press, users and hires."
        trigger: "A round-number metric (MRR/ARR, users, installs, stars)."
        timing: "on trigger (Plausible: $1M ARR on 2022-06-02, post on 2022-06-22)"
        channels: ["blog", "hackernews", "x", "linkedin", "email"]
        assets:
          - {kind: "text", spec: "1500-3000 words with a month-by-month ledger", count: 1}
          - {kind: "image", spec: "charts 16:9 1600x900", count: 2}
          - {kind: "image", spec: "og/link card 1200x630", count: 1}
          - {kind: "thread", spec: "X/LinkedIn summary", count: 1}
        copy: "the number -> the timeline -> what worked -> what did not -> what is next"
        examples:
          - "Plausible 'How we built a $1M ARR open source SaaS' - https://plausible.io/blog/open-source-saas"
          - "Plausible 'bootstrapped ... to $500k ARR' - https://plausible.io/blog/bootstrapping-saas"
          - "Home Assistant release titled 'Two Million Strong' - https://www.home-assistant.io/blog/2025/05/07/release-20255/"
      - id: "open-metrics-page"
        name: "Open-startup metrics page"
        purpose: "Permanent transparency that earns trust and links."
        trigger: "Decision to build in public."
        timing: "evergreen; live or monthly refresh"
        channels: ["website"]
        assets:
          - {kind: "page", spec: "live dashboard: revenue, customers, traffic, team", count: 1}
          - {kind: "image", spec: "og/link card 1200x630", count: 1}
        copy: "why we are open -> live numbers -> how they are measured -> link to source"
        examples:
          - "Cal.com open startup page (HN 2022-08-28) - https://cal.com/open"
          - "Plausible's public dashboard of its own site - https://plausible.io/plausible.io"
      - id: "research-or-opinion-post"
        name: "Original research / newsjacking / opinion piece"
        purpose: "Earn attention between releases with the company's viewpoint or data."
        trigger: "Industry news, or an owned data study."
        timing: "on trigger (news: within 24-72 h)"
        channels: ["blog", "youtube", "hackernews", "x", "linkedin", "reddit"]
        assets:
          - {kind: "text", spec: "800-2000 words", count: 1}
          - {kind: "image", spec: "charts 16:9 1600x900", count: 2}
          - {kind: "video", spec: "opinion video 16:9 5-15 min (optional)", count: 1}
        copy: "the news or finding -> our take / our data -> what it means for you -> soft product mention"
        examples:
          - "Plausible adblocker study (+100% trial signups in five days) and FLoC/AMP posts - https://plausible.io/blog/open-source-saas"
          - "PostHog 'We were wrong about product managers', 2026-06-18 - https://youtu.be/pW3wlkPoFZs"
          - "PostHog 'Your Idea Sucks. Ship It Anyway.', 2026-09-21 - https://youtu.be/-8RTBTBHmEg"
  - id: "funding"
    name: "Funding announcements"
    order: 9
    window: "trigger-based (first round often D+100..D+220)"
    units:
      - id: "funding-announcement"
        name: "Funding announcement"
        purpose: "Signal durability to users, recruit, start a press cycle."
        trigger: "Round closed."
        timing: "on trigger (PostHog D+105; Linear Series A D+161 after public launch)"
        channels: ["blog", "press", "x", "linkedin", "hackernews", "youtube", "email"]
        assets:
          - {kind: "text", spec: "letter 600-1200 words", count: 1}
          - {kind: "image", spec: "hero 16:9 1600x900", count: 1}
          - {kind: "image", spec: "og/link card 1200x630", count: 1}
          - {kind: "video", spec: "founder video 1-3 min (optional)", count: 1}
          - {kind: "text", spec: "press exclusive brief (embargoed)", count: 1}
        copy: "thank users -> progress numbers -> who backed us -> what the money is for (roadmap) -> we are hiring"
        examples:
          - "Linear raises $13M Series A, 2020-12-08 - https://medium.com/linear-app/linear-raises-13m-in-series-a-funding-from-sequoia-capital-daa0f0c43758"
          - "Raycast Series A + Store + API, 2021-12-01 - https://www.raycast.com/blog/series-a/"
          - "Tailscale raises $100M, 2022-05-04 - https://tailscale.com/blog/series-b/"
      - id: "why-we-raised-post"
        name: "Why/how we raised (founder transparency)"
        purpose: "Turn a financing event into useful content for other founders."
        trigger: "After the announcement."
        timing: "funding D+0..D+7"
        channels: ["blog", "hackernews", "x", "linkedin"]
        assets:
          - {kind: "text", spec: "1000-2000 words", count: 1}
          - {kind: "image", spec: "og/link card 1200x630", count: 1}
        copy: "context -> options considered -> what we optimized for -> lessons"
        examples:
          - "PostHog 'How we raised $3M for an open source project', 2020-06-04 - https://posthog.com/blog/raising-3m-for-os"
          - "PostHog 'Why we raised a $15m Series B ahead of schedule', 2021-06-17 - https://posthog.com/blog/why-we-raised-a-15m-series-b-ahead-of-schedule"
          - "Linear 'Building our way' (Series C), 2025-06-10 - https://linear.app/now/building-our-way"
  - id: "community"
    name: "Community & education (recurring)"
    order: 10
    window: "recurring:weekly..monthly from D+30"
    units:
      - id: "newsletter-issue"
        name: "Newsletter issue"
        purpose: "Owned audience beyond users; teach, do not only announce."
        trigger: "Recurring."
        timing: "recurring:weekly..monthly"
        channels: ["email", "website", "linkedin"]
        assets:
          - {kind: "email", spec: "600 px, header 1200x600", count: 1}
          - {kind: "text", spec: "800-1500 words", count: 1}
        copy: "one lesson or opinion -> 3 links -> one product mention -> CTA subscribe/share"
        examples:
          - "PostHog 'Product for Engineers' on Substack - https://newsletter.posthog.com/"
          - "Tailscale monthly newsletter - https://tailscale.com/blog/2024-12-newsletter"
      - id: "method-handbook"
        name: "Public method / handbook"
        purpose: "Evergreen explanation of how the company works; recruits and differentiates."
        trigger: "Once, then maintained."
        timing: "D+60..D+365, then evergreen (Linear Method D+78)"
        channels: ["website", "hackernews", "x"]
        assets:
          - {kind: "page", spec: "multi-section site", count: 1}
          - {kind: "image", spec: "og/link card 1200x630", count: 1}
        copy: "principles -> practices -> examples -> how to apply it yourself"
        examples:
          - "Linear Method - https://linear.app/method"
          - "PostHog handbook (on HN 2023-10-03) - https://posthog.com/handbook"
      - id: "tutorial-video"
        name: "Tutorial / use-case video series"
        purpose: "Search traffic on YouTube; real use-cases; developer relations."
        trigger: "Recurring."
        timing: "recurring:weekly"
        channels: ["youtube", "x", "linkedin", "instagram"]
        assets:
          - {kind: "video", spec: "16:9 1920x1080, 5-15 min", count: 1}
          - {kind: "video", spec: "9:16 1080x1920, <=60 s", count: 2}
          - {kind: "image", spec: "thumbnail 1280x720", count: 1}
        copy: "problem in the title -> result first -> steps -> CTA"
        examples:
          - "Tailscale 'Free and Easy Home Assistant Remote Access with Tailscale!', 2026-07-10 - https://youtu.be/fMR8uvNIilI"
          - "Supabase 'RLS explained in less than 40s', 2026-08-30 - https://youtu.be/9jbOTZqcGsI"
          - "Raycast 'Window Management in Raycast', 2026-06-05 - https://youtu.be/Ei1RIZCrZN8"
      - id: "community-spotlight"
        name: "Community highlights / episode"
        purpose: "Reward contributors; social proof from real users."
        trigger: "After a launch week, or monthly."
        timing: "recurring:monthly or after each launch week"
        channels: ["blog", "youtube", "x", "discord"]
        assets:
          - {kind: "text", spec: "post with featured projects", count: 1}
          - {kind: "video", spec: "episode 20-40 min (optional)", count: 1}
          - {kind: "image", spec: "16:9 1600x900", count: 1}
        copy: "what the community built -> featured projects with links -> how to get featured"
        examples:
          - "Supabase 'Launch Week 8 Community Highlights' - https://supabase.com/blog/launch-week-8-community-highlights"
          - "Raycast 'Watercooler #6', 2026-07-17 - https://youtu.be/mFCb5xVY5Ps"
  - id: "expansion"
    name: "Pricing, platform, hardware & second-product launches"
    order: 11
    window: "trigger-based (seen D+300..D+2000)"
    units:
      - id: "pricing-launch"
        name: "Paid tier / pricing launch"
        purpose: "Introduce monetization with a clear value story."
        trigger: "Paid tier ready."
        timing: "on trigger (Raycast Pro: 1,164 days after Launch HN, 77 days after its AI waitlist)"
        channels: ["blog", "website", "email", "youtube", "x"]
        assets:
          - {kind: "page", spec: "pricing page", count: 1}
          - {kind: "text", spec: "post", count: 1}
          - {kind: "video", spec: "16:9 1-2 min", count: 1}
          - {kind: "email", spec: "600 px", count: 1}
          - {kind: "image", spec: "og/link card 1200x630", count: 1}
        copy: "what stays free -> what the paid tier adds -> price -> founding-member offer -> FAQ"
        examples:
          - "Introducing Raycast Pro, 2023-05-10 - https://www.raycast.com/blog/introducing-raycast-pro"
          - "Raycast 'Update on Raycast Paid Plans', 2026-09-10 - https://youtu.be/FEgUktmN3gs"
      - id: "platform-launch"
        name: "New platform launch (beta -> GA)"
        purpose: "Expand reach in two beats."
        trigger: "Port ready for testers, then for everyone."
        timing: "beta, then GA ~140 days later (Arc Windows 2023-12-11 -> 2024-04-30)"
        channels: ["blog", "website", "x", "youtube", "press", "email"]
        assets:
          - {kind: "page", spec: "download / waitlist page", count: 1}
          - {kind: "video", spec: "16:9 60-90 s", count: 1}
          - {kind: "image", spec: "og/link card 1200x630", count: 1}
          - {kind: "email", spec: "to the platform waitlist", count: 1}
        copy: "now on <platform> -> what is the same / different -> download or join the waitlist"
        examples:
          - "Arc for Windows GA, 2024-04-30 - https://techcrunch.com/2024/04/30/the-browser-company-releases-arc-for-windows"
          - "Raycast Series B: Windows beta + iOS waitlist, 2024-09-25 - https://www.raycast.com/blog/series-b"
          - "Dia public on Mac, 2025-10-09 - https://www.macrumors.com/2025/10/09/ai-browser-dia-launches-publicly-on-mac/"
      - id: "hardware-launch"
        name: "Hardware / physical product launch"
        purpose: "A physical anchor for the brand; revenue; ecosystem."
        trigger: "Product ready for pre-order or crowdfunding."
        timing: "pre-stream D-1..D0; often on the anniversary or at year end; plan an end-of-life notice years later"
        channels: ["blog", "youtube-live", "x", "website", "press", "email"]
        assets:
          - {kind: "livestream", spec: "16:9 30-60 min", count: 1}
          - {kind: "video", spec: "product film 16:9 60-120 s", count: 1}
          - {kind: "image", spec: "product shots 1:1 2000x2000 (white background)", count: 6}
          - {kind: "page", spec: "product page with buy links", count: 1}
          - {kind: "text", spec: "launch post", count: 1}
        copy: "who it is for -> what is in the box -> price & availability -> where to buy"
        examples:
          - "Home Assistant Green at the HA10 livestream, 2023-09-17 - https://www.home-assistant.io/blog/2023/09/17/home-assistant-green-your-entry-to-home-assistant/"
          - "Home Assistant Voice Preview Edition, 2024-12-19 - https://www.home-assistant.io/blog/2024/12/19/voice-preview-edition-the-era-of-open-voice/"
          - "ESPHome Starter Kit 'Product Launch Pre Stream', 2026-08-12 - https://youtu.be/GnXucSzzCqg"
      - id: "second-product-reveal"
        name: "Second product reveal"
        purpose: "Show the company is more than one product; reuse the teaser->beta->public arc."
        trigger: "New product."
        timing: "repeats phases 2-4 (Dia: teaser D-191, public D+120 after beta)"
        channels: ["youtube", "x", "website", "hackernews", "press"]
        assets:
          - {kind: "video", spec: "teaser + launch film (see teaser-video, launch-film)", count: 2}
          - {kind: "page", spec: "own domain / landing", count: 1}
          - {kind: "text", spec: "launch post", count: 1}
        copy: "same arc as the first product; say plainly what happens to the first one"
        examples:
          - "Dia teaser, 2024-12-02 - https://youtu.be/C25g53PC5QQ"
          - "Glaze by Raycast on HN, 2026-03-04 - https://news.ycombinator.com/item?id=47247033"
  - id: "conference"
    name: "Conference / keynote (annual)"
    order: 12
    window: "recurring:annual (announce ~D-100)"
    units:
      - id: "conference-announce-cfp"
        name: "Conference announcement + CFP + tickets"
        purpose: "Gather the community; a ~100-day runway."
        trigger: "Date and venue fixed."
        timing: "announce ~D-100 (Tailscale Up 2023: D-98), CFP closes ~D-70, early-bird tickets"
        channels: ["blog", "website", "x", "linkedin", "email", "youtube"]
        assets:
          - {kind: "page", spec: "event site with agenda/CFP/tickets", count: 1}
          - {kind: "image", spec: "16:9 1600x900 + 1:1 1080x1080", count: 2}
          - {kind: "email", spec: "series: announce, CFP reminder, speakers, last call", count: 4}
        copy: "what / when / where -> who should come -> CFP formats -> tickets"
        examples:
          - "Announcing 'Tailscale Up' community conference, 2023-02-22 - https://tailscale.com/blog/tailscale-up-2023"
          - "Vercel Ship 2025, NYC + online, 2025-06-25 - https://vercel.com/ship/2025"
          - "Vercel Ship 2024 call for proposals - https://ship-cfp-2024.vercel.app/"
      - id: "keynote-livestream"
        name: "Keynote livestream + bundled launches"
        purpose: "The year's biggest launch moment."
        trigger: "Conference day."
        timing: "conference D0; replay the same week"
        channels: ["youtube-live", "website", "x", "linkedin"]
        assets:
          - {kind: "livestream", spec: "16:9 1920x1080, 45-90 min", count: 1}
          - {kind: "video", spec: "per-launch clip 16:9 1-3 min", count: 4}
          - {kind: "text", spec: "'everything we launched' post", count: 1}
        copy: "vision -> launches (each: problem, demo, availability) -> customer on stage -> CTA"
        examples:
          - "Vercel Ship 2024 keynote (live), 2024-05-23 - https://www.youtube.com/watch?v=roRx0b_VXsU"
          - "Tailscale Up 2026 keynote replay, 2026-09-03 - https://youtu.be/j3CNNXUc4KE"
          - "Tailscale 'Three new features launching at Tailscale Up' - https://tailscale.com/blog/three-new-features-launching-at-tailscale-up"
      - id: "talk-recordings"
        name: "Talk recordings & workshops"
        purpose: "The conference's long tail on YouTube."
        trigger: "After the event."
        timing: "D+7..D+30, batch upload"
        channels: ["youtube", "website"]
        assets:
          - {kind: "video", spec: "16:9 per talk, 10-40 min", count: "per talk"}
          - {kind: "image", spec: "thumbnail 1280x720", count: "per talk"}
        copy: "talk title + speaker + event name in the title"
        examples:
          - "Vercel 'Ship 26 NYC' talks, uploaded 2026-07-20 - https://youtu.be/eD8pV7nSIxY"
          - "TailscaleUp on-demand - https://tailscale.com/tailscaleup/on-demand"
  - id: "annual"
    name: "Anniversary & year-in-review"
    order: 13
    window: "recurring:annual"
    units:
      - id: "anniversary-moment"
        name: "Birthday / anniversary moment"
        purpose: "Annual ritual and a natural launch slot."
        trigger: "Founding date."
        timing: "recurring:annual on the founding date"
        channels: ["youtube-live", "blog", "x", "instagram"]
        assets:
          - {kind: "livestream", spec: "optional, 30-60 min", count: 1}
          - {kind: "video", spec: "9:16 <=60 s", count: 1}
          - {kind: "image", spec: "1:1 1080x1080", count: 1}
          - {kind: "text", spec: "post", count: 1}
        copy: "years + numbers -> thank you -> surprise (launch / offer)"
        examples:
          - "HA10 livestream launches Home Assistant Green, 2023-09-17 - https://www.home-assistant.io/blog/2023/09/17/home-assistant-green-your-entry-to-home-assistant/"
          - "Home Assistant 'another year older' video, 2026-09-17 - https://youtu.be/YakjQj2bH6I"
      - id: "state-of-address"
        name: "Annual 'State of' address"
        purpose: "Vision, roadmap and survey results; sets the theme of the coming year."
        trigger: "Annual."
        timing: "recurring:annual (HA: 2024-04-20, 2025-04-12; announced 17-25 days ahead)"
        channels: ["youtube-live", "blog", "x", "email"]
        assets:
          - {kind: "livestream", spec: "16:9 60-120 min", count: 1}
          - {kind: "text", spec: "recap post", count: 1}
          - {kind: "image", spec: "16:9 1600x900", count: 1}
        copy: "year in numbers -> community highlights -> roadmap / theme of the year -> how to help"
        examples:
          - "Home Assistant 'Thinking Bigger: State of the Open Home 2024' - https://www.home-assistant.io/blog/2024/04/24/state-of-the-open-home-2024/"
          - "Home Assistant '2023: Home Assistant's year of Voice', 2022-12-20 - https://www.home-assistant.io/blog/2022/12/20/year-of-voice/"
      - id: "year-in-review"
        name: "Year-in-review / 'Wrapped' / polish season"
        purpose: "End-of-year shareable; personalized recaps spread themselves."
        trigger: "December."
        timing: "recurring:annual (December)"
        channels: ["website", "x", "linkedin", "instagram", "email"]
        assets:
          - {kind: "image", spec: "per-user card 9:16 1080x1920 + 1200x630", count: "per user"}
          - {kind: "page", spec: "recap page", count: 1}
          - {kind: "text", spec: "post", count: 1}
        copy: "your / our year in numbers -> highlights -> thanks -> what is next"
        examples:
          - "Raycast Wrapped, 2022-12-19 - https://twitter.com/raycastapp/status/1604868675277725697"
          - "Linear 'Polishing Season 2022' - https://linear.app/changelog/polishing/2022"
  - id: "transition"
    name: "Transitions: pivots, licence changes, incidents, end-of-life, exits"
    order: 14
    window: "trigger-based"
    units:
      - id: "open-letter"
        name: "Open letter (pivot / licence / sunset)"
        purpose: "Explain a hard change honestly to existing users."
        trigger: "Strategic change that affects users."
        timing: "on trigger; before the change takes effect"
        channels: ["blog", "email", "x", "youtube"]
        assets:
          - {kind: "text", spec: "1000-2500 words", count: 1}
          - {kind: "video", spec: "CEO 3-10 min (optional)", count: 1}
          - {kind: "email", spec: "to all users", count: 1}
          - {kind: "page", spec: "FAQ", count: 1}
        copy: "what is changing -> why (honestly) -> what it means for you (support, data, price) -> what is next -> thank you"
        examples:
          - "'Letter to Arc members 2025', 2025-05-27 - https://browsercompany.substack.com/p/letter-to-arc-members-2025"
          - "'Cal.com is going closed source', 2026-04-15 - https://cal.com/blog/cal-com-goes-closed-source-why"
          - "'Ending production of Home Assistant Yellow', 2025-10-15 - https://www.home-assistant.io/blog/2025/10/15/yellow-end-of-life/"
      - id: "incident-report"
        name: "Incident / security report"
        purpose: "Protect trust when something breaks."
        trigger: "Incident or disclosure."
        timing: "first note within 24 h; full report within ~1-2 weeks"
        channels: ["blog", "website", "email", "x"]
        assets:
          - {kind: "text", spec: "report", count: 1}
          - {kind: "page", spec: "status page entry", count: 1}
          - {kind: "email", spec: "to affected users", count: 1}
        copy: "what happened -> impact -> what we did -> what we will change"
        examples:
          - "Tailscale 'Tailscale didn't stop the Hugging Face intrusion', 2026-07-31 - https://tailscale.com/blog/hugging-face-intrusion"
          - "Supabase 'Alpha Launch Postmortem' - https://supabase.com/blog/alpha-launch-postmortem"
      - id: "acquisition-announcement"
        name: "Acquisition / new-chapter announcement"
        purpose: "Reassure users and tell the next chapter of the story."
        trigger: "Deal signed."
        timing: "on signing"
        channels: ["youtube", "blog", "x", "press"]
        assets:
          - {kind: "video", spec: "16:9 2-5 min", count: 1}
          - {kind: "text", spec: "letter", count: 1}
        copy: "the news -> why this partner -> what does not change for users -> what gets better"
        examples:
          - "The Browser Company 'We have entered an agreement to be acquired by Atlassian', 2025-09-04 - https://youtu.be/u0GljxGVBE4"
          - "'Your Tuesday in 2030' (Substack), 2025-09-04 - https://browsercompany.substack.com/p/your-tuesday-in-2030"
```
