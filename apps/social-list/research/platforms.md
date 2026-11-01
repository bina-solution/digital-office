# social-list: platform research (profile, posts, API, browser)

Snapshot date: **2026-09-29**. Platforms covered: YouTube, GitHub, Facebook Page, Instagram (Business/Creator),
X, Discord, WhatsApp (Business app profile, Channels, Cloud API) and a generic website. LinkedIn Company Page,
TikTok, Telegram and Threads are covered briefly.

## How to read this document

Every spec carries an evidence tag:

| Tag | Meaning |
|---|---|
| **[V]** | Read on the official page during this pass (2026-09-29). |
| **[S]** | Official page, but the value came from a search-result snippet of that page. The page itself could not be fetched (JS-rendered or HTTP 403). |
| **[2]** | Secondary source (third-party blog or forum). Treat it as a lead, not a fact. |
| **[?]** | Not verified in this pass (general knowledge or an older/legacy doc). It may be stale, so confirm it before you build on it. |
| **stale?** | The official doc is legacy or older than 2025. |
| unknown | No trustworthy number was found. This document does not invent numbers. |

Terms-of-service positions are **paraphrased** with a link, and verbatim third-party text is kept to one
short fragment (X, section 5).

**Abstract ops:** `profile.get`, `profile.update.{name,bio,avatar,banner}`, `post.create.{text,image,video}`,
`post.update`, `post.delete`, `feed.list`, `comment.{list,create,delete}`, `reaction.create`, `insights.get`.

**Terms risk for the `browser` kind** (used in every section and in the matrix):

- **explicit-ban**: The rules specifically forbid scripting the website or a user account to post or interact:
  X, LinkedIn, Discord, TikTok and WhatsApp. Keep the browser kind **off** here and use `api` or *handoff*.
- **broad-clause**: The terms forbid access by "automated means" without permission, but they do not single out
  posting from your own account: YouTube, Facebook, Instagram and Threads. The browser kind is technically
  possible for a few owner-initiated actions, but it is a ToS risk that the owner must opt into explicitly.
- **low**: GitHub (its AUP targets excessive bulk activity and inauthentic activity), Telegram (bots are the
  sanctioned path; user-API clients fall under Telegram's API terms [?]) and the office's own website.

**Proposed third kind, `handoff`:** social-list prepares everything (text on the clipboard, media downloaded,
deep link opened), and the owner performs the final click. Nothing is automated, so there is no ToS
exposure. This document recommends it wherever `api` is impossible and `browser` is explicit-ban.

---

## 1. YouTube (channel)

### Profile surface
| Field | Rules / limits | Src |
|---|---|---|
| Channel name | Can be changed twice in 14 days. Max length unknown. | [V] 2972003 |
| Handle (`@`) | 3–30 characters (Han/Hangul 1–10; Ethiopic/Hiragana/Katakana 2–20). Letters and digits from 75 supported languages, plus `_ - . ·` but not at the start or end. Must be unique. Can be changed twice in 14 days. | [V] 11585688, [V] 2972003 |
| Description | Max length unknown (1,000 is often cited [2]). Writable via the API (`brandingSettings.channel.description`). | [V] channels.update |
| Links | Up to 14 links on the channel. | [V] 2972003 |
| Contact email (business inquiries) | Set in YouTube Studio only. | [?] |
| Keywords, country, default language, unsubscribed trailer | Writable via the API (`brandingSettings`). | [V] |

- **Avatar:** JPG/GIF/BMP/PNG (no animated GIF), 15 MB max, rendered at 98x98 and shown as a circle; use a
  square or round source [S 10456525]. A recommended upload size is not stated officially (800x800 is common
  advice [2]).
- **Banner:** Minimum upload 2048x1152 (16:9). At that size, the **safe area for text and logos is 1235x338**.
  Max 6 MB [S 10456525]. 2560x1440 is recommended for the best display on all devices, including TV
  [V 12950272]. Phones show roughly only the safe strip, desktop shows a wider strip, and TV shows the full
  image.

### Post surface
| Type | Limits | Src |
|---|---|---|
| Video | 256 GB or 12 h max, whichever is less. Videos over 15 min need a verified account. Title 100 characters; description 5,000 characters. | [S] 71673, [S] 57404 |
| Short | Up to 3 min, square or vertical. | [S] 15424877 |
| Post (the "Community"/Posts tab) | Text, image(s), poll, quiz, video link. Limits unknown. **No API.** | [V] API resource list |

- **Scheduling:** Yes in Studio. Via the API, upload as private and set `status.publishAt` [?].
- **Edit after publish:** Title, description, thumbnail and visibility can be edited. The media file cannot be
  replaced.
- **Delete:** Yes.
- **Link previews:** None. Links in descriptions stay plain.

### Official API: YouTube Data API v3 and YouTube Analytics API
- **Auth:** Google OAuth 2.0. `channels.update` accepts the `youtube`, `youtube.force-ssl` and
  `youtubepartner` scopes [V]. Uploads use `youtube.upload`, and Analytics uses `yt-analytics.readonly` [?].
- **Review and audit:**
  - Google OAuth app verification applies to sensitive scopes [?].
  - **Unverified API projects created after 2020-07-28 upload videos locked to private** until the project
    passes the YouTube API compliance audit [S videos.insert, S 7300965].
  - Each self-hosted office has its own Google Cloud project, so public uploads stay private until that office
    is audited.
- **Cost and quota:**
  - Free, with 10,000 units/day plus **separate daily buckets of 100 `videos.insert` and 100 `search.list`
    calls** [V].
  - Unit costs: list calls 1; `channels.update`, `channelBanners.insert`, `videos.update`/`delete`/`rate`,
    `comments.insert`/`delete`, `commentThreads.insert` and `thumbnails.set` 50 each [V].
- **What each op maps to:**
  - `profile.get`: `channels.list`.
  - Description, keywords, country, language and trailer: `channels.update`.
  - **Name:** not writable. The title must be omitted or equal to the current title [V].
  - **Avatar:** not writable; it is not an updatable property [V].
  - **Banner:** `channelBanners.insert`, then set `brandingSettings.image.bannerExternalUrl` via
    `channels.update` [? verify at implementation].
  - Posts: `videos.insert`, `videos.update`, `videos.delete`, `thumbnails.set`.
  - `feed.list`: `playlistItems.list` on the uploads playlist.
  - Comments: `commentThreads.list`/`insert`, `comments.insert` (reply), `comments.delete` and
    `setModerationStatus`.
  - Reactions: `videos.rate` (like/dislike videos only; there is no comment-like endpoint).
  - Insights: YouTube Analytics API.
  - There is no community-post resource [V].
- **Gaps (browser only):** channel name, handle, avatar, the links section [?], and Posts-tab posts.

### Browser surface
- **URLs:**
  - Profile: `https://studio.youtube.com/channel/<CHANNEL_ID>/editing/profile` [? pattern]
  - Upload: `https://www.youtube.com/upload` (opens the Studio uploader) [?]
  - Posts tab: `https://www.youtube.com/@<handle>/posts` [?]
- **Login:** Google Account with 2-Step Verification or a passkey, plus "verify it's you" prompts. Google
  refuses sign-in from browsers it considers automated or embedded ("This browser or app may not be secure")
  [? support.google.com/accounts/answer/7675428]. The owner should sign in by hand in a normal persistent
  profile.
- **Terms (paraphrase):** YouTube's Terms forbid accessing the service by automated means such as robots,
  botnets or scrapers. The exceptions are public search engines (per robots.txt) and prior written permission.
  Source: https://www.youtube.com/static?template=terms [S]. Risk: **broad-clause**.

**Sources:**
- https://support.google.com/youtube/answer/2972003
- https://support.google.com/youtube/answer/11585688
- https://support.google.com/youtube/answer/10456525
- https://support.google.com/youtube/answer/12950272
- https://support.google.com/youtube/answer/15424877
- https://support.google.com/youtube/answer/71673
- https://support.google.com/youtube/answer/57404
- https://developers.google.com/youtube/v3/docs/channels/update
- https://developers.google.com/youtube/v3/determine_quota_cost
- https://developers.google.com/youtube/v3/docs/videos/insert
- https://support.google.com/youtube/answer/7300965
- https://developers.google.com/youtube/v3/docs

---

## 2. GitHub (user or organization)

### Profile surface
- **User fields:**
  - Name, bio (**160 characters max**), pronouns, website URL.
  - **Up to 4 social account links.**
  - Company, location, local time zone, display email, status, ORCID iD.
  - Profile README (a repository named after the user).
  - Source: [V] personalizing-your-profile.
- **Username:** Can be changed in Settings, then Account. GitHub redirects the old repository URLs, and the old
  name becomes claimable by others [?].
- **Organization fields:** display name, description, URL, email, location, avatar, and an org README at
  `.github/profile/README.md` [?].
- **Avatar:** PNG/JPG/GIF, **under 1 MB, under 3000x3000**, about **500x500 recommended**. Users get a circle
  crop and orgs a rounded square [S profile-reference].
- **Banner:** None. The closest equivalent is the **repository social preview**: PNG/JPG/GIF under 1 MB, at
  least 640x320, and **1280x640 for the best display** [V].

### Post surface
GitHub has no feed posts. The equivalents:
- **Release** (Markdown notes plus assets): a project's announcement.
- **Discussion** (for example in an Announcements category).
- **Profile README edit**: a "pinned bio post".
- **Gist** and **issue**.

Text limits for releases and discussions are unknown. Issue bodies are commonly limited to 65,536 characters
[2]. There is no scheduling. Posts can be edited and deleted.

### Official API: REST and GraphQL (free)
- **Auth:**
  - Fine-grained PAT with Contents, Discussions and Metadata permissions, or a classic PAT with the `user`
    scope (profile), `repo`/`public_repo` (releases) and `write:discussion` [? verify].
  - A GitHub App or OAuth App also works.
  - No review.
- **Rate limits** [V]:
  - Primary: 5,000 requests/h with a PAT, 15,000/h for a GitHub App installed on Enterprise Cloud.
  - Secondary: 100 concurrent requests max, 900 points/min (REST), 2,000 points/min (GraphQL), and
    **80 content-creating requests/min and 500/h**.
- **What each op maps to:**
  - `profile.get`: `GET /user`.
  - Profile update: `PATCH /user` with `name`, `email`, `blog`, `twitter_username`, `company`, `location`,
    `hireable` and `bio` [V]. Social accounts use `/user/social_accounts` [?].
  - **Avatar:** no API [V: none documented]. The repo social preview has no API either [?].
  - Posts: the Releases REST API (create, update, delete, upload assets) and the GraphQL
    `createDiscussion`/`updateDiscussion`/`deleteDiscussion` mutations [?]. README edits go through the
    Contents API.
  - `feed.list`: the Events API or the releases list.
  - Comments: issue and discussion comments.
  - Reactions: the REST Reactions API and GraphQL `addReaction`.
  - Insights: repository traffic (views and clones for the last 14 days), plus star and fork counts. There is
    no profile analytics [?].

### Browser surface
- **URLs:**
  - Profile: `https://github.com/settings/profile`
  - Username: `https://github.com/settings/admin`
  - Organization profile: `https://github.com/organizations/<org>/settings/profile`
  - New release: `https://github.com/<o>/<r>/releases/new`
  - New discussion: `https://github.com/<o>/<r>/discussions/new`
  - Social preview: `https://github.com/<o>/<r>/settings`
- **Login:** Password or passkey plus 2FA (mandatory for most accounts since 2023 [?]). Sensitive settings
  require re-authentication ("sudo mode").
- **Terms (paraphrase):** The Acceptable Use Policies forbid automated excessive bulk activity, coordinated
  inauthentic activity, and rank abuse such as automated starring or following. Source:
  https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies [V].
  A few owner-initiated profile edits are not bulk. Risk: **low**.

**Sources:**
- https://docs.github.com/en/account-and-profile/setting-up-and-managing-your-github-profile/customizing-your-profile/personalizing-your-profile
- https://docs.github.com/en/account-and-profile/reference/profile-reference
- https://docs.github.com/en/rest/users/users#update-the-authenticated-user
- https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api
- https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/customizing-your-repositorys-social-media-preview

---

## 3. Facebook Page

### Profile surface
- **Page name:** You request a change from Page settings; it can be reviewed or rejected, and guidelines apply.
  Max length unknown [S 271607792873806, 519912414718764].
- **Username** (`facebook.com/<username>`): **at least 5 characters**, A–Z, 0–9 and `.` only. No generic terms
  or extensions. Periods and letter case do not make a username distinct [S 105399436216001].
- **Bio/intro:** Length unknown. A secondary post says the limit rose to 255 [2].
- **Other fields:** category, phone, email(s), website(s), address/location, hours, and the about/description
  text. The API can write all of these except the name and username [V Page reference].
- **Avatar:** Displays at **176x176 on desktop, 196x196 on smartphones** and 36x36 on feature phones. Upload
  **320x320** for best quality. It is cropped to a circle [S 125379114252045, stale?].
- **Cover:** Displays at **820x312 on desktop and 640x360 on smartphones**. Minimum 400x150. It loads fastest
  as an sRGB JPG at 851x315 and under 100 KB [S 125379114252045, stale?]. For a **safe area**, keep the
  essentials in the region both crops share: roughly the central 640x312. This is derived, not official.

### Post surface
- **Types:**
  - Text.
  - Link: the preview is built from the target's Open Graph tags.
  - Photo or album.
  - **Video:** since June 2025, every video is published as a reel of any length or orientation
    [S 1197310377458196]. Uploads must be **10 GB or less and under 240 min** [S 1692533511105458].
  - Story; event [?].
- **Text limit:** Unknown (63,206 is widely cited [2]).
- **Scheduling:** Yes. The API accepts a `scheduled_publish_time` **10 min to 30 days** ahead [V].
- **Edit:** Yes, but **an app can only update posts that were made by the same app** [V].
- **Delete:** Yes [V].

### Official API: Graph API (reference pages show v26.0 [S])
- **Auth:** Facebook Login, then a Page access token. Page tasks CREATE_CONTENT, MANAGE and MODERATE [V].
  - Permissions [V]: `pages_manage_posts`, `pages_manage_engagement`, `pages_read_engagement`, `publish_video`.
  - Permissions [?]: `pages_show_list`, `pages_manage_metadata`, `pages_read_user_content`, `read_insights`.
- **Review:**
  - App Review (Advanced Access) and Business Verification are required when serving other people's Pages.
  - An app in development mode has **Standard Access for users who hold a role on the app** [? access-levels].
  - So "one Meta app per office, with the owner as app admin" likely avoids App Review. Verify this.
- **Cost:** Free. Rate limits are Business Use Case limits that scale with the Page's engaged users
  [? rate-limiting].
- **What each op maps to:**
  - `profile.get`: yes.
  - `POST /{page-id}` writes about, description, phone, website, emails, hours, location, **cover** and more [V].
  - **Name:** not listed as writable [V].
  - **Avatar:** `POST /{page-id}/picture` (URL or photo id; needs the MANAGE task plus
    `pages_read_engagement` and `pages_show_list`) [V].
  - Posts: the `/feed`, `/photos`, `/videos` and `/video_reels` edges [? reels edge]; stories edges [?];
    update and delete [V].
  - `feed.list`: `/feed` and `/published_posts`.
  - Comments: list, create as the Page, delete and hide [?].
  - Reactions: reading works. Liking as the Page is **unverified**.
  - Insights: `/{page-id}/insights` and post insights, but the metrics keep changing:
    - `impressions` was replaced by `views` from 2025-11-15.
    - More metrics were deprecated for all versions by 2026-06-15 [S blog 2025-08-15].

### Browser surface
- **URLs:**
  - Page profile (after switching into the Page): `https://www.facebook.com/profile.php?id=<PAGE_ID>&sk=about`
    [? pattern]
  - Meta Business Suite: `https://business.facebook.com/latest/home` [?]
  - Composer: `https://business.facebook.com/latest/composer` [?], or the Page's own composer.
- **Login:** Meta account with 2FA (often required for Page admins [?]). Checkpoints on new devices, action
  blocks on rapid actions, and a DOM with hashed class names, so locators must use accessible names [?].
- **Terms (paraphrase):** Meta's Terms forbid accessing or collecting data from Meta products by automated
  means without prior permission, whether or not the user is logged in. Sources: https://www.facebook.com/terms
  [S] and https://www.facebook.com/legal/automated_data_collection_terms [S]. Risk: **broad-clause**.

**Sources:**
- https://www.facebook.com/help/125379114252045
- https://www.facebook.com/help/105399436216001
- https://www.facebook.com/help/271607792873806
- https://www.facebook.com/business/help/1197310377458196
- https://www.facebook.com/business/help/1692533511105458
- https://developers.facebook.com/docs/graph-api/reference/page/
- https://developers.facebook.com/docs/graph-api/reference/page/picture/
- https://developers.facebook.com/docs/pages-api/posts
- https://developers.facebook.com/blog/post/2025/08/15/page-insights-api-updates/

---

## 4. Instagram (Business or Creator account)

### Profile surface
- **Name:** Length unknown. "Twice in 14 days" is the commonly reported change limit [2].
- **Username:** Letters, numbers, periods and underscores [S]; 30 characters max [2]. Username changes can be
  reverted within 14 days [? 876876079327341].
- **Bio:** **150 characters max** [S 728994388226960].
- **Other fields:** up to 5 links [2]; category and contact buttons (professional accounts); pronouns.
- **Avatar:** Circle crop. Official pixel size unknown (320x320 is commonly cited [2]).
- **Banner:** None.

### Post surface
- **Types:** feed photo; carousel (**up to 20 items in the app** [S 269314186824048], **10 via the API** [V]);
  reel; story (9:16); live.
- **Reels:** Up to 3 min. Reels longer than 3 min are not recommended to new audiences [S about.instagram.com].
  Size 1080x1920, 9:16 [V 1038071743007909].
- **Caption:** 2,200 characters and 30 hashtags [2].
- **API media rules:** JPEG only. Carousel items are cropped to the first item's ratio, which defaults to 1:1
  [V]. The historical feed aspect bounds were 4:5 to 1.91:1 [?].
- **Scheduling:** In the app and Business Suite. The API has no schedule parameter [?], so social-list must
  schedule.
- **Edit after publish:** Captions can be edited in the app. **The API cannot edit the caption**; it can only
  toggle `comment_enabled` [V].
- **Delete:** `DELETE` via the API works for non-ad posts, stories, reels and whole carousels, on the Facebook
  Login path with `instagram_manage_contents` [V].

### Official API (Instagram API with Instagram Login, or with Facebook Login)
- **Scopes:**
  - Instagram Login: `instagram_business_basic` and `instagram_business_content_publish` [V];
    `instagram_business_manage_comments` and `instagram_business_manage_insights` [?].
  - Facebook Login: `instagram_basic`, `instagram_content_publish`, `pages_read_engagement` (plus
    `ads_management`/`ads_read` when the user's Page role requires it) and `instagram_manage_comments` [V];
    `instagram_manage_insights` [?].
- **Review:** App Review for Advanced Access (the same dev-mode caveat as Facebook).
- **Cost:** Free.
- **Rate limit:** **100 API-published posts per rolling 24 h** per account; a carousel counts as one [V].
  Shopping tags and filters are not supported [V].
- **What each op maps to:**
  - `profile.get`: username, name, biography, website, profile picture URL, follower and media counts [?].
  - **Profile update:** no endpoint for the name, bio, avatar or links.
  - Posts: create images, video/reels, carousels (up to 10) and stories [?]. Caption update is not possible.
    Delete works [V].
  - `feed.list`: `/{ig-user-id}/media`.
  - Comments:
    - List: yes.
    - Create: yes, but not on live video [V].
    - Reply: via `/replies` [?].
    - Hide: yes.
    - **Delete: only by the owner of the media** [V].
  - Reactions: **no like endpoint** [?].
  - Insights: yes [?].

### Browser surface
- **URLs:**
  - Profile: `https://www.instagram.com/accounts/edit/`
  - Composer: `https://www.instagram.com/` then Create (no stable deep link), or the Business Suite composer.
- **Login:** Password or Facebook login plus 2FA. Expect "suspicious login" challenges, and temporary action
  blocks on unusual patterns [?].
- **Terms (paraphrase):** The Instagram Terms of Use forbid accessing or collecting information in unauthorized
  ways, including automated ways, without express permission. Source: https://help.instagram.com/581066165581870
  [S]. Risk: **broad-clause**.

**Sources:**
- https://developers.facebook.com/docs/instagram-platform/content-publishing
- https://developers.facebook.com/docs/instagram-platform/reference/instagram-media
- https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-media/comments
- https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-comment
- https://help.instagram.com/728994388226960
- https://help.instagram.com/269314186824048
- https://help.instagram.com/1038071743007909
- https://about.instagram.com/features/reels

---

## 5. X (formerly Twitter)

### Profile surface
- **Name:** 50 characters max.
- **Username:** **more than 4 and at most 15 characters**; A–Z, 0–9 and underscore only
  [S x-username-rules].
- **Bio:** 160 characters max [S].
- **Location and website:** Official limits unknown. The legacy v1.1 docs list 30 and 100 [?, stale?].
- **Avatar:** **400x400** recommended.
- **Header:** **1500x500** (3:1). JPG/GIF/PNG, no animated GIFs [S common-issues-when-uploading-profile-photo].
  Max file sizes unknown. The avatar overlaps the lower left of the header, and the mobile crop differs; no
  official safe area is published.

### Post surface
- **Text:** A post is 280 characters, weighted [S how-to-post]. **X Premium allows up to 25,000 characters**
  [S x-premium].
- **Media:** Up to 4 media items in the app [S]. The API allows **4 photos, or 1 GIF, or 1 video** [V].
- **Video length** (the two sources conflict):
  - The help center says **140 s** for non-Premium users in the app [S].
  - The API docs (2026-09-01) say **20 min / 8 GB by default and 125 min / 16 GB for Premium or verified
    accounts**. The limit follows the posting user, not the API plan [V changelog].
- **Other types:**
  - Thread (a reply chain).
  - Poll: 2–4 options, 5 min to 7 days [V].
  - Quote: Enterprise-only via the API [V].
  - Article: API endpoints since 2026-06-11 [V].
  - Community post.
- **Scheduling:** Available in the web composer [?]. The API has none, so social-list must schedule.
- **Edit:** Premium only, within 1 hour, up to 5 edits [S edit-post]. Via the API, `POST /2/tweets` with
  `edit_options.previous_post_id` works for Premium users on their own posts within 1 hour
  [V changelog 2025-10-03].
- **Delete:** Yes.
- **Link previews:** Built from the target page's `twitter:*` and Open Graph tags.

### Official API: X API v2 (paid)
- **Auth:**
  - OAuth 2.0 PKCE in user context (`tweet.read`, `tweet.write`, `users.read`, `media.write`,
    `offline.access` [? exact list]), or OAuth 1.0a in user context.
  - OAuth 1.0a tokens can be exchanged for OAuth 2.0 without re-consent (2026-09-21) [V].
- **Pricing (pay-per-use, launched 2026-02-06):** Credits are bought in console.x.com, with no subscription or
  minimum [V pricing]. Rates:

  | Operation | Price |
  |---|---|
  | Create a post | **$0.015** |
  | **Create a post that contains a URL** | **$0.20** |
  | Summoned reply | $0.010 |
  | Interaction delete | $0.010 |
  | Content manage | $0.005 |
  | Media metadata | $0.005 |
  | Read a post | $0.005 per resource |
  | Read a user | $0.010 per resource |
  | Read a like | $0.001 per resource |
  | **Owned reads** (your own timeline, mentions, followers…, since 2026-04-20) | **$0.001 per resource** |

  - Monthly cap: **3 M post reads**. Above that you need **Enterprise**, which is custom-priced (about $42k+/mo
    per [2]).
  - **Legacy tiers:** Basic ($200/mo) and Pro ($5,000/mo). The official changelog (2026-02) says they "remain
    available" to existing subscribers. Third-party blogs report forced migration after 2026-06-01 (Basic)
    and 2026-09-01 (Pro) [2].
  - New developers get pay-per-use or Enterprise only. The old Free tier is gone; recently active Legacy Free
    users got a one-time $10 voucher [V].
  - Example: 20 posts/month costs $0.30 without links and **$4.00 with links**, plus reads.
- **Self-serve restrictions** [V]:
  - **Likes, follows and quote-posts were removed from self-serve (2026-04-20)**, so `reaction.create` = **no**.
  - **Programmatic replies are allowed only when the original author "summoned" you** (2026-02-23), so
    `comment.create` = limited.
  - At most 1 cashtag per post.
- **Rate limits** [V]:
  - `POST /2/tweets`: 100 per 15 min per user; 10,000 per 24 h per app.
  - `DELETE`: 50 per 15 min per user.
  - Media upload: 500 per 15 min per user.
  - `GET /2/users/me`: 75 per 15 min.
- **What each op maps to:**
  - `profile.get`: `users/me`. v2 can read the avatar and banner URLs [V].
  - **Profile update: no v2 endpoint.** The legacy v1.1 `account/update_profile`, `update_profile_image` and
    `update_profile_banner` are still documented on developer.x.com, but not in the v2 docs, so their
    availability and pricing on pay-per-use are **unknown** [?, stale?]. The X Activity API can *notify* you of
    profile changes (`profile.update.*` events, $0.005 each) [V].
  - Posts: create, edit and delete.
  - `feed.list`: owned reads.
  - `comment.list`: recent search with `conversation_id:` (7-day window) [?], or mentions.
  - `comment.delete`: your own replies. Hiding other people's replies [?].
  - `insights.get`: public, non-public and organic metrics for your own recent posts [?].

### Browser surface
- **URLs:**
  - Profile: `https://x.com/settings/profile`
  - Composer: `https://x.com/compose/post`
- **Login:** Password plus 2FA (TOTP or passkey; SMS 2FA is Premium-only [?]). Expect Arkose/FunCaptcha
  challenges. X locks accounts it flags for automation [2].
- **Rules:**
  - X's automation rules warn that "non-API-based forms of automation, such as scripting the X website" can
    lead to permanent suspension. Source: https://help.x.com/en/rules-and-policies/x-automation [S].
  - The ToS (paraphrase) limits access to X's published interfaces and forbids scraping without consent.
    Source: https://x.com/en/tos [S].
  - Risk: **explicit-ban**.

**Sources:**
- https://docs.x.com/x-api/getting-started/pricing
- https://docs.x.com/changelog
- https://docs.x.com/x-api/posts/create-post
- https://docs.x.com/x-api/fundamentals/rate-limits
- https://devcommunity.x.com/t/x-api-pricing-update-owned-reads-now-0-001-other-changes-effective-april-20-2026/263025
- https://help.x.com/en/managing-your-account/x-username-rules
- https://help.x.com/en/using-x/edit-post
- https://developer.x.com/en/docs/x-api/v1/accounts-and-users/manage-account-settings/api-reference/post-account-update_profile (legacy)
- Secondary: https://www.blotato.com/blog/twitter-api-pricing, https://postproxy.dev/blog/x-api-pricing-2026/

---

## 6. Discord (server or community)

### Profile surface (server)
- **Name:** **2–100 characters**, trimmed [V guild].
- **Icon:** The API expects **1024x1024** PNG/JPEG/GIF; an animated icon needs the `ANIMATED_ICON` feature [V].
- **Banner:** **16:9**; needs the `BANNER` feature, or `ANIMATED_BANNER` if animated [V]. The support article
  says it must be **at least 960x540** and unlocks at **Boost Level 2** [S 360028716472, stale?].
- **Invite splash:** 16:9, `INVITE_SPLASH` feature [V].
- **Discovery splash:** `DISCOVERABLE` feature [V].
- **Description:** Length unknown.
- **Vanity URL:** Boost Level 3 [?].
- **Server tag:** 4 characters; costs 3 Boosts [S].
- **Bot identity** (how posts appear):
  - Username 2–32 characters. It cannot contain `@`, `#`, `:`, a triple backtick, or the word "discord", and cannot be "everyone" or "here".
  - Display name 1–32 characters.
  - Avatar and banner via `PATCH /users/@me` [V].

### Post surface
- **Message:** **2,000 characters**. Up to **10 embeds** with **6,000 characters in total** (title 256,
  description 4,096, up to 25 fields). The request can be up to **25 MiB** [V message].
- **Upload size limits:**
  - Free accounts: 10 MB since late 2024 [2], with reports of 20 MB during a 2026 rollout [2].
  - Nitro Basic 50 MB, Nitro 500 MB [2].
  - The official FAQ could not be fetched: https://support.discord.com/hc/en-us/articles/25444343291031.
- **Other types:** announcement channel with **crosspost** to following servers [V]; forum/media-channel posts
  (a thread plus its first message); polls; scheduled events.
- **Scheduling:** No native message scheduling (events only), so social-list must schedule.
- **Edit:** Only by the author [V].
- **Delete:** By the author, or by others with `MANAGE_MESSAGES`. Bulk delete works on 2–100 messages younger
  than 14 days [V].

### Official API (free)
- **Auth:** A bot token plus an OAuth2 install with the `bot` and `applications.commands` scopes.
  - Permissions: `MANAGE_GUILD` (server profile), `SEND_MESSAGES`, `MANAGE_MESSAGES`, `ADD_REACTIONS`,
    `READ_MESSAGE_HISTORY`.
  - Channel **webhooks** are a lighter, token-only way to post.
- **Review:** Privileged intents (message content, members, presence) can be toggled freely **until the app
  reaches 10,000 users**. After that you must apply, and **re-apply every year**. Before the 2026 change the
  threshold was 100 servers [S support-dev 40281523410967].
- **Rate limits** [V]:
  - 50 requests/s per bot, globally.
  - 10,000 invalid requests (401/403/429) in 10 min leads to a temporary block.
  - Routes are rate-limited in per-route buckets.
- **What each op maps to:**
  - Profile: `GET`/`PATCH /guilds/{id}` for the name, icon, banner, splash and description [V].
  - Posts, channel history, thread replies and reactions all work [V].
  - **No insights API.** Server Insights exists only in the client [?].

### Browser surface
- **URLs:**
  - Server settings: `https://discord.com/channels/<GUILD_ID>`, then Server Settings, then Overview (no deep
    link [?]).
  - Composer: `https://discord.com/channels/<GUILD_ID>/<CHANNEL_ID>`
- **Login:** Email or phone plus password and 2FA. hCaptcha appears on suspicious logins [?].
- **Terms (paraphrase):** Automating a normal user account ("self-bot") outside the OAuth2/bot API is forbidden
  and can get the account terminated. Source: https://support.discord.com/hc/en-us/articles/115002192352 [S].
  Risk: **explicit-ban**.

**Sources:**
- https://docs.discord.com/developers/resources/guild
- https://docs.discord.com/developers/resources/user
- https://docs.discord.com/developers/resources/message
- https://docs.discord.com/developers/topics/rate-limits
- https://support.discord.com/hc/en-us/articles/360028716472-Server-Banners
- https://support-dev.discord.com/hc/en-us/articles/40281523410967

---

## 7. WhatsApp

These are three separate surfaces, and they do not share an implementation.

### 7a. WhatsApp Business **app** profile (the phone app, with WhatsApp Web as a linked device)
- **Fields:** business name, profile photo, category, description, address, business hours, email, website(s),
  catalog, and links to a Facebook Page or Instagram account. Meta AI can draft the description
  [S 577829787429875, 665179381840568].
- **Limits in the app:** Unknown. The Cloud API limits in 7c are the best proxy [?].
- **API:** None for the app itself. If the number is onboarded to the Cloud API (optionally in "coexistence"
  with the app [?]), profile edits go through 7c.
- **Browser:** `https://web.whatsapp.com`, logged in by scanning a QR code from the phone. Whether WhatsApp Web
  can edit the business profile is unknown; the mobile app is the canonical editor.

### 7b. WhatsApp Channels
- **Channel fields:** name, optional description, optional icon [S 265055289421317]. Followers do not see the
  admins' phone numbers [S].
- **Updates:** Admins can **edit updates for up to 30 days**, and the server keeps **up to 30 days** of history
  [S]. Types are text, photos, videos, stickers and polls [? WhatsApp blog]. Followers react with emoji or
  vote; there are no comments [?].
- **API: none.** Meta's official APIs do not expose Channels. This is based on secondary sources [2] and on
  Channels being absent from Meta's docs. Third-party "channel APIs" use the unofficial WhatsApp Web protocol
  and carry ban risk.
- **Browser:** On web.whatsapp.com, open Channels. Creating a channel on the web is documented
  [S 794229125227200]. Automating it is **explicit-ban**.

### 7c. WhatsApp Business Platform: Cloud API
- **Business profile API** (`GET`/`POST /{phone-number-id}/whatsapp_business_profile`) [V]:

  | Field | Limit |
  |---|---|
  | about | 139 characters |
  | address | 256 characters |
  | description | 512 characters |
  | email | 128 characters, valid format |
  | vertical | enum |
  | websites | up to 2, 256 characters each, with `http(s)://` |
  | profile photo | `profile_picture_handle` from the Resumable Upload API; official px and MB limits unknown |

- **Display name:**
  - Set or changed in WhatsApp Manager or via the API.
  - **After business verification, every display-name change is reviewed.** Statuses are PENDING_REVIEW and
    DECLINED, and the `phone_number_name_update` webhook reports the outcome
    [S facebook.com/business/help 338047025165344, 757569725593362].
- **Posts:** None. There is no feed and no Status posting via the API [?]. The platform only sends messages
  (templates outside the 24-hour customer-service window).
- **Auth:** A Meta Business Portfolio plus a system-user token, with `whatsapp_business_management` and
  `whatsapp_business_messaging` (and `business_management`) [?].
- **Messaging limits:** Unique users per 24 h go **250, then 2,000, 10,000, 100,000, then unlimited**. You reach
  2,000 through business verification, or by delivering 2,000 high-quality template messages in 30 days
  [V messaging-limits].
- **Pricing:**
  - **Per message since 2025-07-01**: charged per delivered template message. Utility templates inside an open
    service window are free [S pricing].
  - More pricing changes land on **2026-08-01 and 2026-10-01**, including **a free monthly tier of 1,000
    service messages per number** [S]. Verify the details before you rely on them.
  - The On-Premises API was sunset on 2025-10-23 [2].
- **Insights:** Messaging, pricing and template analytics endpoints [S].

**Terms (paraphrase):** WhatsApp's Terms forbid bulk or automated messaging and using the service through
automated or unauthorized means. Sources: https://www.whatsapp.com/legal/terms-of-service [S] and
https://faq.whatsapp.com/5957850900902049. Risk: **explicit-ban** for automating the app or WhatsApp Web.

**Sources:**
- https://developers.facebook.com/docs/whatsapp/cloud-api/reference/business-profiles
- https://developers.facebook.com/docs/whatsapp/messaging-limits
- https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing
- https://www.facebook.com/business/help/338047025165344
- https://faq.whatsapp.com/265055289421317
- https://faq.whatsapp.com/577829787429875
- Secondary: https://whapi.cloud/blog/whatsapp-channel-api-automation

---

## 8. Website (generic: the office's own site)

Everything here is under the office's control. The `api` kind means writing files and deploying.

**Icons**

| Asset | Spec | Src |
|---|---|---|
| `favicon.ico` | Multi-size 16/32/48. | [?] |
| SVG favicon | `<link rel="icon" type="image/svg+xml">` | [?] |
| `apple-touch-icon` | 180x180 PNG. | [?] |
| Manifest icons | **At least 192x192 and 512x512** (Chromium). 1024x1024 is the largest display size. | [S] web.dev, [V] MDN |
| Maskable variant | `"purpose": "maskable"`. Keep the logo inside the **safe zone: a circle with a radius of 40% of the width**, which is an 80% diameter. | [V] MDN, [S] web.dev |
| Manifest fields | `name`, `short_name`, `description`, `theme_color`, `background_color`, `icons`. | [?] |

**Share images (this is the website's "banner")**

| Tag | Spec | Src |
|---|---|---|
| Open Graph image (`og:image`) | **1200x630 or larger** recommended. Min 200x200, ratio about **1.91:1**, **8 MB max**. Add `og:image:width` and `og:image:height` so the first share renders, and when replacing an image, **change its URL** and re-scrape. | [V] |
| Open Graph text | `og:title`, `og:description`, `og:url`, `og:site_name`. | |
| X card `summary_large_image` | **2:1**, min 300x157, max 4096x4096, under 5 MB; JPG/PNG/WEBP/GIF. | [2]; the official developer.x.com cards page could not be fetched |
| X card `summary` | 1:1, min 144x144. | [2] |
| LinkedIn link preview | 1.91:1 (1200x627). | [V] a563309 |

**Posts:** Blog or news entries, if the site has a CMS or static generator. Also expose an RSS/Atom feed so
other channels can syndicate from it.

**Browser:** Not needed. **Terms:** Not applicable. Facebook, LinkedIn and X all cache link previews; use the
Facebook Sharing Debugger or LinkedIn Post Inspector to refresh them [?].

**Sources:**
- https://developers.facebook.com/docs/sharing/webmasters/images
- https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/How_to/Define_app_icons
- https://web.dev/articles/maskable-icon
- https://developer.x.com/en/docs/x-for-websites/cards/overview/summary-card-with-large-image

---

## 9. LinkedIn Company Page (brief)

- **Profile:**
  - Fields: Page name (limit unknown; 100 per [2]), tagline and description (limits unknown; secondary
    sources conflict), website, industry, company size, type, locations, phone, custom button, hashtags.
  - **Logo:** minimum 268x268, recommended **400x400**, 3 MB max, PNG/JPEG. It is shown on both light and dark
    backgrounds.
  - **Cover:** **1512x256** (minimum and recommended), 3 MB max. This replaces the older 1128x191 spec.
  - Life-tab main image: 1128x376.
  - Image specs source: [V a563309].
- **Posts:**
  - Text up to **3,000 characters** [S a528176].
  - **Up to 20 images** [S a527229].
  - **Video up to 15 min from desktop and 10 min from mobile** [S a527229].
  - Also: document (PDF carousel), poll, article, newsletter, event.
  - Link previews are 1.91:1 (1200x627) [V].
  - Scheduling [?]; edit and delete work.
- **API: Community Management API** (vetted) [V]:
  - It covers organization posts, comments and reactions; follower, page and share statistics; and "create,
    update, and delete organization information".
  - **Access runs in two tiers.** The Development tier (500 requests per app and 100 per member [? per day])
    comes first. You reach the Standard tier after a **screencast review**.
  - Scopes: `w_organization_social`, `r_organization_social`, `rw_organization_admin` [?]. `r_member_social`
    is closed.
  - The API is versioned: version 202510 sunsets on 2026-10-15.
  - It is free but gated, and approval for a small self-hosted install is uncertain.
- **Browser:**
  - Admin view: `https://www.linkedin.com/company/<ID>/admin/` [?].
  - **Terms (paraphrase):** User Agreement §8.2 forbids using bots or unauthorized automated methods to create,
    comment on, like or share posts. Source: https://www.linkedin.com/legal/user-agreement [S]. Also see
    https://www.linkedin.com/help/linkedin/answer/a1341387. Risk: **explicit-ban**.

**Sources:**
- https://www.linkedin.com/help/linkedin/answer/a563309
- https://www.linkedin.com/help/linkedin/answer/a527229
- https://learn.microsoft.com/en-us/linkedin/marketing/community-management/community-management-overview

## 10. TikTok (brief)

- **Profile:**
  - **Username:** 2–24 characters (letters, digits, `_` and `.`, not ending in `.`). Can be changed **once every
    30 days**.
  - **Nickname:** 30 characters max. Can be changed once every 7 days.
  - Source for both: [S support.tiktok.com].
  - **Bio:** 80 characters historically; 160 is reported [2].
  - Photo or video avatar; website link (eligibility unknown).
- **Posts:**
  - Types: video, photo post, story, LIVE.
  - Caption up to 4,000 characters [2]. The maximum uploaded video length is unknown (60 min is reported [2]).
- **API** [V unless noted]:
  - Login Kit plus the Content Posting API. Choose `video.publish` (Direct Post) or `video.upload` (sends the
    video to the creator's drafts).
  - Photos go through `/v2/post/publish/content/init/` with `media_type=PHOTO`, from a verified domain.
  - **Unaudited clients:** posts are private only, and at most 5 users can post per 24 h.
  - **Creator cap:** about 15 posts per day per creator, across all API clients.
  - **Required UX:** a preview; an explicit privacy choice with no default; interaction toggles off by
    default; a commercial-content disclosure; and explicit consent.
  - The Display API (`user.info.*`, `video.list`) covers profile reads, feed and basic stats [?].
  - There is no profile update, and no comments or likes, in the general API [?].
  - Free, but the audit is required for public posting.
- **Browser:**
  - Upload: `https://www.tiktok.com/tiktokstudio/upload` [?].
  - **Terms (paraphrase):** They forbid using automated scripts or bots to extract data or interact. Source:
    https://www.tiktok.com/legal/page/us/terms-of-service/en [S]. Risk: **explicit-ban**.

**Sources:**
- https://developers.tiktok.com/doc/content-posting-api-get-started
- https://developers.tiktok.com/doc/content-sharing-guidelines
- https://www.tiktok.com/support/faq_detail?id=7581821550156962315

## 11. Telegram (channel and bot) (brief)

Profile, post and limit facts below come from the Bot API docs (Bot API 10.3) [V] unless noted.

- **Channel profile:**
  - Title: **1–128 characters** (`setChatTitle`).
  - Description: **0–255 characters** (`setChatDescription`).
  - Photo: `setChatPhoto`; the bot must be an admin with the right permissions.
  - Public `@username`: 5–32 characters [? Telegram FAQ].
- **Posts:**
  - Text: **1–4,096 characters**.
  - Caption: **0–1,024 characters**.
  - Photo: **10 MB max**, width plus height at most 10,000, and an aspect ratio of at most 20.
  - Files: **50 MB max** through the cloud Bot API, or up to **2,000 MB** with a self-hosted Local Bot API
    server.
  - Media group: **2–10 items**.
  - Polls.
- **What each op maps to:**
  - Edit: `editMessageText`, `editMessageCaption` and `editMessageMedia`.
  - **Delete:** Normally only messages younger than 48 h. A bot with `can_post_messages` can delete its own
    channel posts, and a bot with `can_delete_messages` can delete any channel message.
  - Reactions: `setMessageReaction` (bots cannot send paid reactions).
  - Comments: through the channel's linked discussion group [?].
  - `feed.list`: Bots cannot read channel history retroactively; they only get updates while subscribed [?].
  - Scheduling: The apps can schedule; the Bot API cannot, so social-list must schedule.
- **Auth:** A bot token from @BotFather. Free, with no review.
- **Rate:** About 30 messages/s overall and about 20 per minute per group [? Bots FAQ].
- **Insights:** None in the Bot API [?].
- **Browser:** `https://web.telegram.org/a/` (phone or QR login, plus an optional cloud password). It is not
  needed.

**Source:** https://core.telegram.org/bots/api

## 12. Threads (brief)

- **Profile:** Shares the Instagram identity (username; the picture can be imported). Name, bio and link(s) are
  edited in the app; limits unknown [?]. The API can read the profile [?] but **cannot update it**.
- **Posts** [V threads/posts]:
  - Text: **500 characters**, with emoji counted by UTF-8 bytes. At most 5 unique links in a text-only post.
  - Images: JPEG/PNG, **8 MB max**, width 320–1,440 px, aspect ratio up to 10:1, sRGB.
  - Video: MOV/MP4, **5 min max**, 1 GB max, 23–60 fps; 9:16 recommended.
  - Carousel: **2–20 items**.
  - Text attachments of up to 10,000 characters [? 2025].
  - Edit: in the app only [?]; the API has none. Delete: via the API [V].
- **API:**
  - Scopes: `threads_basic`, `threads_content_publish`, `threads_manage_replies`, `threads_manage_insights`,
    `threads_delete`, `threads_keyword_search`, `threads_location_tagging` [V]; `threads_read_replies` [?].
  - **Limits per 24 h:** 250 posts, 1,000 replies, 100 deletions, 500 location searches and 2,200 keyword
    searches [V].
  - **Insights** [V]:
    - Per post: views, likes, replies, reposts, quotes, shares.
    - Per user: views, likes, replies, reposts, quotes, clicks, follower count, and follower demographics
      (100+ followers).
    - No user insights before 2024-04-13.
  - App Review for Advanced Access [?]. Free.
- **Browser:**
  - Composer: `https://www.threads.com/`. Profile: open it and choose Edit profile [?].
  - Meta and Instagram terms apply, so the risk is **broad-clause**.

**Sources:**
- https://developers.facebook.com/docs/threads/posts
- https://developers.facebook.com/docs/threads/overview
- https://developers.facebook.com/docs/threads/insights/

---

## Coverage matrix

Each cell reads `api`, `browser`, `api+browser` or `no`, with a one-word caveat. A cell says `browser` only
where that platform's browser risk is broad-clause or low. On explicit-ban platforms, an op with no API is
`no (ToS)`, `no (handoff)` or `no (none)`. `(n/a)` means the platform has no such thing.

| op | YouTube | GitHub | FB Page | Instagram | X | Discord | WA Business (Cloud API) | WA Channel | Website | LinkedIn | TikTok | Telegram | Threads |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| profile.get | api | api | api | api | api (paid) | api | api | no (handoff) | api | api (gated) | api | api | api |
| profile.update.name | browser (ToS-risk) | api | browser (reviewed) | browser (ToS-risk) | api (legacy?) | api | api (reviewed) | no (handoff) | api | api (gated?) | no (ToS) | api | browser (ToS-risk) |
| profile.update.bio | api | api | api | browser (ToS-risk) | api (legacy?) | api | api | no (handoff) | api | api (gated?) | no (ToS) | api | browser (ToS-risk) |
| profile.update.avatar | browser (ToS-risk) | browser (low-risk) | api | browser (ToS-risk) | api (legacy?) | api | api | no (handoff) | api | api (gated?) | no (ToS) | api | browser (ToS-risk) |
| profile.update.banner | api (verify) | browser (repo-preview) | api | no (n/a) | api (legacy?) | api (Boost-L2) | no (n/a) | no (n/a) | api (og:image) | api (gated?) | no (n/a) | no (n/a) | no (n/a) |
| post.create.text | browser (ToS-risk) | api (release) | api | no (media-only) | api (paid) | api | no (n/a) | no (handoff) | api | api (gated) | no (n/a) | api | api |
| post.create.image | browser (ToS-risk) | api (asset) | api | api | api (paid) | api | no (n/a) | no (handoff) | api | api (gated) | api (audit) | api | api |
| post.create.video | api (audit) | no (n/a) | api | api | api (paid) | api (size) | no (n/a) | no (handoff) | api | api (gated) | api (audit) | api (50MB) | api |
| post.update | api (metadata) | api | api (same-app) | browser (ToS-risk) | api (Premium) | api | no (n/a) | no (handoff) | api | api (gated) | no (none) | api | browser (ToS-risk) |
| post.delete | api | api | api | api | api | api | no (n/a) | no (handoff) | api | api (gated) | no (ToS) | api | api |
| feed.list | api | api | api | api | api (owned) | api | no (n/a) | no (handoff) | api | api (gated) | api | api (live-only) | api |
| comment.list | api | api | api | api | api (search) | api | no (n/a) | no (n/a) | no (n/a) | api (gated) | no (none) | api (group) | api |
| comment.create | api | api | api | api | api (summoned-only) | api | no (n/a) | no (n/a) | no (n/a) | api (gated) | no (none) | api (group) | api |
| comment.delete | api | api | api | api (own-media) | api (own) | api | no (n/a) | no (n/a) | no (n/a) | api (gated) | no (none) | api (admin) | api (hide) |
| reaction.create | api (videos) | api | api? (unverified) | browser (ToS-risk) | no (removed) | api | no (n/a) | no (handoff) | no (n/a) | api (gated) | no (none) | api | browser (ToS-risk) |
| insights.get | api (Analytics) | api (14-day) | api (churning) | api | api (own) | no (client-only) | api (messaging) | no (client-only) | api (own) | api (gated) | api (basic) | no (none) | api |

Notes:
- **YouTube banner:** The two-step `channelBanners.insert` → `bannerExternalUrl` flow must be verified in code.
- **YouTube video:** Uploads stay private until the office's Google project passes the audit.
- **FB name:** It is a reviewed request, so `browser` just files the request.
- **FB reaction:** Liking as the Page via `/{object-id}/likes` was not verified.
- **X legacy:** The v1.1 `account/update_profile*` endpoints are documented only on the legacy site, and their
  availability on pay-per-use is unverified.
- **WA Business:** Assumes the number is on the Cloud API. If the office uses only the WhatsApp Business
  app, every profile op becomes `no (handoff)`.
- **Threads** `post.update`: in-app edit only [?].

### Logo and identity push (for `digital-assets`)
When a new logo becomes active:
- **Fully automatable** (api): Facebook Page (avatar and cover), Discord (icon and banner), WhatsApp Cloud API
  profile photo, Telegram channel photo, the website (favicon set, manifest icons, og/twitter images), and the
  YouTube banner (verify).
- **Legacy/unverified:** X avatar and header.
- **Browser, opt-in:**
  - Low risk: GitHub avatar and repo social preview.
  - ToS-risk: YouTube avatar, Instagram avatar, Threads avatar.
- **Handoff:** LinkedIn logo and cover (unless the Community Management API is approved), TikTok avatar,
  WhatsApp Business app photo, WhatsApp Channel icon.

---

## Recommendation per platform (default implementation and why)

| Platform | Default | Why |
|---|---|---|
| **YouTube** | **api** | Covers bio, banner, uploads, metadata edits, comments, likes and analytics. The remaining ops (name, avatar, Posts tab) are opt-in browser (ToS-risk) or handoff. Until the office's Google project passes the compliance audit, upload **private** and let the owner publish (handoff), since unaudited uploads are locked private anyway. Budget 100 uploads/day. |
| **GitHub** | **api** (PAT or GitHub App) | Everything except the avatar and the repo social preview. Those two are rare, owner-initiated and low-risk, so `browser` is an acceptable default for them. |
| **Facebook Page** | **api** | The fullest official coverage of any platform, avatar and cover included. The Page name is a reviewed request, so use handoff. Self-hosted pattern: one Meta app per office in dev mode, with the owner as app admin, relying on Standard Access (verify). Expect insights metric churn. |
| **Instagram** | **api** | Posts, delete, comments and insights work via the API, but there are **no profile writes**, so name, bio, avatar and links default to handoff (browser as a ToS-risk opt-in). The API allows at most 10 carousel items, no caption edits, and 100 posts per 24 h. |
| **X** | **api** (pay-per-use) | Posting, editing (Premium) and deleting are cheap, but **a post containing a URL costs $0.20, which is 13x more**; social-list should warn about this. Browser is ruled out: scripting the site risks permanent suspension. Try the legacy v1.1 profile endpoints for profile writes, and fall back to handoff. There are no likes, and replies only work when summoned. |
| **Discord** | **api** (bot, or a channel webhook for announcements) | Full coverage, free. Never use the browser: self-bots are banned. |
| **WhatsApp** | Profile: **api** (Cloud API) if the number is on the Cloud API, otherwise **handoff**. Channels: **handoff**. | The Channels API does not exist, and automating the app or Web is an explicit ToS risk. Broadcasting via templates is a separate, per-message-paid messaging product, out of scope for social-list. |
| **Website** | **api** (files plus deploy) | Generate the favicon set, 192/512 manifest icons (plus maskable), a 1200x630 OG image and a 2:1 X card from the logo. Give each new image a new URL so platform caches refresh. |
| **LinkedIn** | **handoff**, and **api** once the office holds Community Management API (Standard tier) approval | The API is gated behind vetting, and the User Agreement explicitly bans automated posting, commenting and liking. |
| **TikTok** | **api** (`video.upload` to drafts) plus **handoff** to publish | This respects the audit rules: unaudited Direct Post is private-only and limited to 5 users per day. Profile edits: handoff. Never use the browser. |
| **Telegram** | **api** (bot) | The Bot API covers the channel profile, posts, edits, deletes and reactions for free. The browser is not needed. |
| **Threads** | **api** | Publishing, replies, delete and insights are well covered. Profile edits default to handoff (browser as a ToS-risk opt-in). |

Cross-cutting recommendations:
- **Add `handoff` as a first-class implementation kind next to `api` and `browser`.**
- **Pre-validate every post against the limits in the appendix before calling any API**: text length, media
  count, aspect ratio, duration and file size.
- **social-list owns scheduling.** The APIs with native scheduling (Facebook, YouTube) are the exception, not
  the rule.
- **Keep browser actions few, deliberate and owner-initiated, and stop at every challenge.** Enable the
  browser kind per platform only after an explicit owner opt-in that shows the ToS risk class from this
  document.

---

## Appendix: platform-specs

`null` means unknown. `browser: yes` means the op is technically possible and allowed to be enabled; check the
note for any ToS-risk.

```yaml
# platform-specs
# Research snapshot 2026-09-29. Evidence tags: see "How to read this document" above.
# ops values are quoted strings: api "yes" | "no" | "limited"; browser "yes" | "no" (quoted so YAML 1.1 parsers do not turn them into booleans)
platforms:
  - id: youtube
    name: "YouTube (channel)"
    kinds_supported: [api, browser]
    default_kind: api
    auth:
      kind: oauth2
      scopes: ["https://www.googleapis.com/auth/youtube", "https://www.googleapis.com/auth/youtube.force-ssl", "https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/yt-analytics.readonly"]
      review_required: "Google OAuth verification (sensitive scopes); YouTube API compliance audit for public uploads and quota increases"
      cost: "free; 10,000 units/day + 100 videos.insert/day + 100 search.list/day"
    profile:
      fields:
        - {id: name, max_len: null, rules: "change twice per 14 days; not writable via API"}
        - {id: handle, max_len: 30, rules: "3-30 chars (Han/Hangul 1-10; Ethiopic/Hiragana/Katakana 2-20); letters/digits of 75 languages + _ - . middle-dot, not at start/end; unique; change twice per 14 days"}
        - {id: description, max_len: null, rules: "API brandingSettings.channel.description; 1000 often cited (unverified)"}
        - {id: links, max_len: null, rules: "up to 14 links"}
        - {id: contact_email, max_len: null, rules: "Studio only"}
        - {id: keywords, max_len: null, rules: "API brandingSettings.channel.keywords"}
      avatar: {w: null, h: null, aspect: "1:1", max_mb: 15, shape: circle, note: "renders at 98x98; JPG/GIF/BMP/PNG; no animated GIF; 800x800 is common advice (unverified)"}
      banner: {w: 2560, h: 1440, aspect: "16:9", min: "2048x1152", max_mb: 6, safe_area: {w: 1235, h: 338, note: "text/logo safe area at the 2048x1152 minimum; TV shows full image"}}
    post_types:
      - {id: video, text_max: 5000, title_max: 100, media: {images_max: 0, aspects: ["16:9"], video_max_s: 43200}, note: "<=256 GB; >15 min needs verified account; unaudited API uploads locked private"}
      - {id: short, text_max: 5000, title_max: 100, media: {images_max: 0, aspects: ["9:16", "1:1"], video_max_s: 180}}
      - {id: channel_post, text_max: null, media: {images_max: null, aspects: [], video_max_s: null}, note: "Posts/Community tab; no API"}
    ops:
      profile.get: {api: "yes", browser: "yes", note: "channels.list"}
      profile.update.name: {api: "no", browser: "yes", note: "title not writable via API; browser = broad-clause ToS risk"}
      profile.update.bio: {api: "yes", browser: "yes", note: "channels.update brandingSettings (50 units)"}
      profile.update.avatar: {api: "no", browser: "yes", note: "no API; ToS risk"}
      profile.update.banner: {api: "limited", browser: "yes", note: "channelBanners.insert + bannerExternalUrl; verify"}
      post.create.text: {api: "no", browser: "yes", note: "Posts tab has no API"}
      post.create.image: {api: "no", browser: "yes", note: "Posts tab has no API"}
      post.create.video: {api: "limited", browser: "yes", note: "videos.insert; private until project audited; 100/day"}
      post.update: {api: "yes", browser: "yes", note: "metadata only (title, description, thumbnail, privacy)"}
      post.delete: {api: "yes", browser: "yes", note: "videos.delete"}
      feed.list: {api: "yes", browser: "yes", note: "uploads playlist via playlistItems.list"}
      comment.list: {api: "yes", browser: "yes", note: "commentThreads.list"}
      comment.create: {api: "yes", browser: "yes", note: "commentThreads.insert / comments.insert (reply)"}
      comment.delete: {api: "yes", browser: "yes", note: "comments.delete / setModerationStatus"}
      reaction.create: {api: "limited", browser: "yes", note: "videos.rate only; no comment likes"}
      insights.get: {api: "yes", browser: "yes", note: "YouTube Analytics API"}
    urls:
      profile_edit: "https://studio.youtube.com/channel/<CHANNEL_ID>/editing/profile"
      compose: "https://www.youtube.com/upload"

  - id: github
    name: "GitHub (user / organization)"
    kinds_supported: [api, browser]
    default_kind: api
    auth:
      kind: pat
      scopes: ["classic: user, repo|public_repo, write:discussion", "fine-grained: Contents, Discussions, Metadata (verify)"]
      review_required: false
      cost: "free; 5,000 req/h; 80 content-creating req/min, 500/h"
    profile:
      fields:
        - {id: name, max_len: null, rules: "PATCH /user name"}
        - {id: bio, max_len: 160, rules: "PATCH /user bio"}
        - {id: blog, max_len: null, rules: "website URL"}
        - {id: social_accounts, max_len: null, rules: "up to 4 links"}
        - {id: company, max_len: null, rules: ""}
        - {id: location, max_len: null, rules: ""}
        - {id: pronouns, max_len: null, rules: "web only"}
        - {id: username, max_len: null, rules: "changeable in settings; old name becomes claimable (unverified)"}
      avatar: {w: 500, h: 500, aspect: "1:1", max_mb: 1, shape: circle, note: "PNG/JPG/GIF; must be < 3000x3000; org avatars are rounded squares; no API"}
      banner: {w: 1280, h: 640, aspect: "2:1", safe_area: null, note: "no profile banner; this is the repository social preview (>=640x320, <1 MB); no API"}
    post_types:
      - {id: release, text_max: null, media: {images_max: null, aspects: [], video_max_s: null}, note: "Markdown notes + binary assets"}
      - {id: discussion, text_max: null, media: {images_max: null, aspects: [], video_max_s: null}, note: "GraphQL; issue bodies capped at 65,536 (secondary)"}
      - {id: profile_readme, text_max: null, media: {images_max: null, aspects: [], video_max_s: null}, note: "Contents API on <user>/<user>/README.md"}
    ops:
      profile.get: {api: "yes", browser: "yes", note: "GET /user"}
      profile.update.name: {api: "yes", browser: "yes", note: "PATCH /user"}
      profile.update.bio: {api: "yes", browser: "yes", note: "PATCH /user (160 chars)"}
      profile.update.avatar: {api: "no", browser: "yes", note: "no API; low ToS risk"}
      profile.update.banner: {api: "no", browser: "yes", note: "repo social preview only"}
      post.create.text: {api: "yes", browser: "yes", note: "release / discussion"}
      post.create.image: {api: "limited", browser: "yes", note: "release asset; inline image upload is web-only"}
      post.create.video: {api: "no", browser: "no", note: "n/a"}
      post.update: {api: "yes", browser: "yes", note: ""}
      post.delete: {api: "yes", browser: "yes", note: ""}
      feed.list: {api: "yes", browser: "yes", note: "events / releases"}
      comment.list: {api: "yes", browser: "yes", note: "issue/discussion comments"}
      comment.create: {api: "yes", browser: "yes", note: ""}
      comment.delete: {api: "yes", browser: "yes", note: ""}
      reaction.create: {api: "yes", browser: "yes", note: "Reactions API / addReaction"}
      insights.get: {api: "limited", browser: "yes", note: "repo traffic, last 14 days; no profile analytics"}
    urls:
      profile_edit: "https://github.com/settings/profile"
      compose: "https://github.com/<owner>/<repo>/releases/new"

  - id: facebook_page
    name: "Facebook Page"
    kinds_supported: [api, browser]
    default_kind: api
    auth:
      kind: oauth2_page_token
      scopes: [pages_manage_posts, pages_manage_engagement, pages_read_engagement, pages_read_user_content, pages_show_list, pages_manage_metadata, read_insights, publish_video]
      review_required: "App Review (Advanced Access) + Business Verification for third-party Pages; dev-mode app with owner as admin likely suffices (verify)"
      cost: "free; Business Use Case rate limits"
    profile:
      fields:
        - {id: name, max_len: null, rules: "change is a reviewed request; not writable via API"}
        - {id: username, max_len: null, rules: ">=5 chars; A-Z 0-9 and '.'; no generic terms/extensions"}
        - {id: about, max_len: null, rules: "POST /{page-id} about"}
        - {id: description, max_len: null, rules: "POST /{page-id} description"}
        - {id: phone, max_len: null, rules: ""}
        - {id: emails, max_len: null, rules: ""}
        - {id: website, max_len: null, rules: ""}
        - {id: hours, max_len: null, rules: ""}
        - {id: location, max_len: null, rules: ""}
        - {id: category, max_len: null, rules: "web"}
      avatar: {w: 320, h: 320, aspect: "1:1", max_mb: null, shape: circle, note: "displays 176x176 desktop, 196x196 smartphone; API POST /{page-id}/picture"}
      banner: {w: 851, h: 315, aspect: "820:312 desktop / 640:360 mobile", min: "400x150", max_mb: 0.1, safe_area: {w: 640, h: 312, note: "derived overlap of desktop and mobile crops; not official"}, note: "the 100 KB figure is for fastest load, not a hard cap"}
    post_types:
      - {id: text, text_max: null, media: {images_max: 0, aspects: [], video_max_s: null}}
      - {id: link, text_max: null, media: {images_max: 0, aspects: ["1.91:1"], video_max_s: null}, note: "preview from target OG tags"}
      - {id: photo, text_max: null, media: {images_max: null, aspects: [], video_max_s: null}}
      - {id: video_reel, text_max: null, media: {images_max: 0, aspects: ["9:16", "any"], video_max_s: 14400}, note: "since 2025-06 all videos are reels; <=10 GB; must be < 240 min"}
      - {id: story, text_max: null, media: {images_max: 1, aspects: ["9:16"], video_max_s: null}}
    ops:
      profile.get: {api: "yes", browser: "yes", note: ""}
      profile.update.name: {api: "no", browser: "yes", note: "reviewed request; broad-clause ToS risk"}
      profile.update.bio: {api: "yes", browser: "yes", note: "about/description"}
      profile.update.avatar: {api: "yes", browser: "yes", note: "POST /{page-id}/picture"}
      profile.update.banner: {api: "yes", browser: "yes", note: "cover via POST /{page-id}"}
      post.create.text: {api: "yes", browser: "yes", note: "/feed; scheduled_publish_time 10 min-30 days"}
      post.create.image: {api: "yes", browser: "yes", note: "/photos"}
      post.create.video: {api: "yes", browser: "yes", note: "/videos or /video_reels"}
      post.update: {api: "limited", browser: "yes", note: "only posts created by the same app"}
      post.delete: {api: "yes", browser: "yes", note: ""}
      feed.list: {api: "yes", browser: "yes", note: "/feed, /published_posts"}
      comment.list: {api: "yes", browser: "yes", note: ""}
      comment.create: {api: "yes", browser: "yes", note: "as the Page"}
      comment.delete: {api: "yes", browser: "yes", note: "delete or hide"}
      reaction.create: {api: "limited", browser: "yes", note: "like-as-Page unverified"}
      insights.get: {api: "yes", browser: "yes", note: "impressions->views (2025-11-15); more deprecations by 2026-06-15"}
    urls:
      profile_edit: "https://www.facebook.com/profile.php?id=<PAGE_ID>&sk=about"
      compose: "https://business.facebook.com/latest/composer"

  - id: instagram
    name: "Instagram (Business / Creator)"
    kinds_supported: [api, browser]
    default_kind: api
    auth:
      kind: oauth2
      scopes: [instagram_business_basic, instagram_business_content_publish, instagram_business_manage_comments, instagram_business_manage_insights]
      review_required: "App Review for Advanced Access (dev-mode role caveat as Facebook)"
      cost: "free; 100 API-published posts per 24h"
    profile:
      fields:
        - {id: name, max_len: null, rules: "change limit reportedly twice per 14 days (secondary); no API"}
        - {id: username, max_len: 30, rules: "letters, numbers, periods, underscores; 30 is secondary; no API"}
        - {id: bio, max_len: 150, rules: "no API"}
        - {id: links, max_len: null, rules: "up to 5 (secondary); no API"}
        - {id: category, max_len: null, rules: "professional accounts"}
      avatar: {w: null, h: null, aspect: "1:1", max_mb: null, shape: circle, note: "320x320 commonly cited (secondary); no API"}
      banner: null
    post_types:
      - {id: image, text_max: 2200, media: {images_max: 1, aspects: ["1:1", "4:5", "1.91:1"], video_max_s: null}, note: "API JPEG only; caption limit secondary; aspect bounds unverified"}
      - {id: carousel, text_max: 2200, media: {images_max: 10, aspects: ["1:1", "4:5", "1.91:1"], video_max_s: null}, note: "20 in-app, 10 via API; cropped to first item"}
      - {id: reel, text_max: 2200, media: {images_max: 0, aspects: ["9:16"], video_max_s: 180}, note: "1080x1920; >3 min not recommended to new audiences"}
      - {id: story, text_max: null, media: {images_max: 1, aspects: ["9:16"], video_max_s: null}}
    ops:
      profile.get: {api: "yes", browser: "yes", note: ""}
      profile.update.name: {api: "no", browser: "yes", note: "no endpoint; broad-clause ToS risk"}
      profile.update.bio: {api: "no", browser: "yes", note: "no endpoint"}
      profile.update.avatar: {api: "no", browser: "yes", note: "no endpoint"}
      profile.update.banner: {api: "no", browser: "no", note: "n/a"}
      post.create.text: {api: "no", browser: "no", note: "media required"}
      post.create.image: {api: "yes", browser: "yes", note: ""}
      post.create.video: {api: "yes", browser: "yes", note: "reels"}
      post.update: {api: "no", browser: "yes", note: "API cannot edit caption (comment_enabled only)"}
      post.delete: {api: "yes", browser: "yes", note: "Facebook-Login path, instagram_manage_contents"}
      feed.list: {api: "yes", browser: "yes", note: ""}
      comment.list: {api: "yes", browser: "yes", note: ""}
      comment.create: {api: "yes", browser: "yes", note: "not on live video"}
      comment.delete: {api: "limited", browser: "yes", note: "only by owner of the media; hide also available"}
      reaction.create: {api: "no", browser: "yes", note: "no like endpoint"}
      insights.get: {api: "yes", browser: "yes", note: ""}
    urls:
      profile_edit: "https://www.instagram.com/accounts/edit/"
      compose: "https://www.instagram.com/"

  - id: x
    name: "X (Twitter)"
    kinds_supported: [api]
    default_kind: api
    auth:
      kind: oauth2_pkce
      scopes: [tweet.read, tweet.write, users.read, media.write, offline.access]
      review_required: false
      cost: "pay-per-use: $0.015/post, $0.20/post with URL, $0.010 summoned reply, $0.005/post read, $0.001 owned read; 3M reads/month cap; Enterprise custom"
    profile:
      fields:
        - {id: name, max_len: 50, rules: ""}
        - {id: username, max_len: 15, rules: "more than 4 chars; A-Z 0-9 underscore"}
        - {id: bio, max_len: 160, rules: ""}
        - {id: location, max_len: null, rules: "30 per legacy v1.1 docs (unverified)"}
        - {id: website, max_len: null, rules: "100 per legacy v1.1 docs (unverified)"}
      avatar: {w: 400, h: 400, aspect: "1:1", max_mb: null, shape: circle, note: "JPG/GIF/PNG; no animated GIF"}
      banner: {w: 1500, h: 500, aspect: "3:1", safe_area: null, note: "avatar overlaps lower-left; mobile crop differs"}
    post_types:
      - {id: post, text_max: 280, media: {images_max: 4, aspects: [], video_max_s: 1200}, note: "Premium text 25,000; video 20 min/8 GB default, 125 min/16 GB Premium (API docs 2026-09); help center says 140 s non-Premium in-app"}
      - {id: poll, text_max: 280, media: {images_max: 0, aspects: [], video_max_s: null}, note: "2-4 options, 5-10,080 min"}
      - {id: thread, text_max: 280, media: {images_max: 4, aspects: [], video_max_s: 1200}, note: "reply chain; self-reply rules under summoned-only policy unverified"}
      - {id: article, text_max: null, media: {images_max: null, aspects: [], video_max_s: null}, note: "API endpoints since 2026-06-11"}
    ops:
      profile.get: {api: "yes", browser: "no", note: "users/me"}
      profile.update.name: {api: "limited", browser: "no", note: "legacy v1.1 update_profile only; availability unverified; scripting site = suspension risk"}
      profile.update.bio: {api: "limited", browser: "no", note: "legacy v1.1"}
      profile.update.avatar: {api: "limited", browser: "no", note: "legacy v1.1 update_profile_image"}
      profile.update.banner: {api: "limited", browser: "no", note: "legacy v1.1 update_profile_banner"}
      post.create.text: {api: "yes", browser: "no", note: "$0.015; $0.20 with URL"}
      post.create.image: {api: "yes", browser: "no", note: "<=4 photos"}
      post.create.video: {api: "yes", browser: "no", note: "1 video"}
      post.update: {api: "limited", browser: "no", note: "Premium, own post, < 1h, edit_options"}
      post.delete: {api: "yes", browser: "no", note: "50/15min per user"}
      feed.list: {api: "yes", browser: "no", note: "owned reads $0.001"}
      comment.list: {api: "limited", browser: "no", note: "recent search conversation_id (7-day) / mentions"}
      comment.create: {api: "limited", browser: "no", note: "only when summoned (2026-02-23)"}
      comment.delete: {api: "limited", browser: "no", note: "own replies"}
      reaction.create: {api: "no", browser: "no", note: "likes removed from self-serve 2026-04-20"}
      insights.get: {api: "yes", browser: "no", note: "own post metrics"}
    urls:
      profile_edit: "https://x.com/settings/profile"
      compose: "https://x.com/compose/post"

  - id: discord
    name: "Discord (server / community)"
    kinds_supported: [api]
    default_kind: api
    auth:
      kind: bot_token
      scopes: [bot, applications.commands]
      review_required: "privileged intents need application once the app reaches 10,000 users; yearly re-application"
      cost: "free; 50 req/s global"
    profile:
      fields:
        - {id: name, max_len: 100, rules: "2-100 chars, trimmed; PATCH /guilds/{id}"}
        - {id: description, max_len: null, rules: "PATCH /guilds/{id}"}
        - {id: vanity_url, max_len: null, rules: "Boost Level 3 (unverified)"}
        - {id: bot_username, max_len: 32, rules: "2-32; no @ # : triple-backtick or 'discord'; not everyone/here"}
      avatar: {w: 1024, h: 1024, aspect: "1:1", max_mb: null, shape: rounded, note: "PNG/JPEG/GIF; animated needs ANIMATED_ICON"}
      banner: {w: 960, h: 540, aspect: "16:9", safe_area: null, note: "minimum 960x540; needs BANNER feature (Boost Level 2)"}
    post_types:
      - {id: message, text_max: 2000, media: {images_max: 10, aspects: [], video_max_s: null}, note: "10 attachments per message (unverified); request <= 25 MiB"}
      - {id: embed, text_max: 4096, media: {images_max: 1, aspects: [], video_max_s: null}, note: "<=10 embeds, 6000 chars total"}
      - {id: announcement, text_max: 2000, media: {images_max: 10, aspects: [], video_max_s: null}, note: "crosspost to following servers"}
      - {id: forum_post, text_max: 2000, media: {images_max: 10, aspects: [], video_max_s: null}, note: "thread + first message"}
    ops:
      profile.get: {api: "yes", browser: "no", note: "GET /guilds/{id}"}
      profile.update.name: {api: "yes", browser: "no", note: "MANAGE_GUILD; self-bots banned"}
      profile.update.bio: {api: "yes", browser: "no", note: "description"}
      profile.update.avatar: {api: "yes", browser: "no", note: "icon"}
      profile.update.banner: {api: "yes", browser: "no", note: "BANNER feature"}
      post.create.text: {api: "yes", browser: "no", note: ""}
      post.create.image: {api: "yes", browser: "no", note: ""}
      post.create.video: {api: "yes", browser: "no", note: "size-limited attachment"}
      post.update: {api: "yes", browser: "no", note: "author only"}
      post.delete: {api: "yes", browser: "no", note: ""}
      feed.list: {api: "yes", browser: "no", note: "channel messages"}
      comment.list: {api: "yes", browser: "no", note: "thread messages / replies"}
      comment.create: {api: "yes", browser: "no", note: ""}
      comment.delete: {api: "yes", browser: "no", note: "MANAGE_MESSAGES for others"}
      reaction.create: {api: "yes", browser: "no", note: ""}
      insights.get: {api: "no", browser: "no", note: "Server Insights is client-only"}
    urls:
      profile_edit: "https://discord.com/channels/<GUILD_ID>"
      compose: "https://discord.com/channels/<GUILD_ID>/<CHANNEL_ID>"

  - id: whatsapp_business
    name: "WhatsApp Business (Cloud API profile; Business app via handoff)"
    kinds_supported: [api]
    default_kind: api
    auth:
      kind: system_user_token
      scopes: [whatsapp_business_management, whatsapp_business_messaging, business_management]
      review_required: "business verification (to pass 250 limit); display-name review"
      cost: "profile edits free; messaging per delivered template message (since 2025-07-01)"
    profile:
      fields:
        - {id: display_name, max_len: null, rules: "changes reviewed after business verification"}
        - {id: about, max_len: 139, rules: ""}
        - {id: address, max_len: 256, rules: ""}
        - {id: description, max_len: 512, rules: ""}
        - {id: email, max_len: 128, rules: "valid email"}
        - {id: vertical, max_len: null, rules: "enum"}
        - {id: websites, max_len: 256, rules: "max 2; must include http(s)://"}
      avatar: {w: null, h: null, aspect: "1:1", max_mb: null, shape: circle, note: "profile_picture_handle via Resumable Upload API"}
      banner: null
    post_types: []
    ops:
      profile.get: {api: "yes", browser: "no", note: "GET whatsapp_business_profile"}
      profile.update.name: {api: "limited", browser: "no", note: "reviewed"}
      profile.update.bio: {api: "yes", browser: "no", note: "about/description"}
      profile.update.avatar: {api: "yes", browser: "no", note: "profile_picture_handle"}
      profile.update.banner: {api: "no", browser: "no", note: "n/a"}
      post.create.text: {api: "no", browser: "no", note: "n/a (messaging only)"}
      post.create.image: {api: "no", browser: "no", note: "n/a"}
      post.create.video: {api: "no", browser: "no", note: "n/a"}
      post.update: {api: "no", browser: "no", note: "n/a"}
      post.delete: {api: "no", browser: "no", note: "n/a"}
      feed.list: {api: "no", browser: "no", note: "n/a"}
      comment.list: {api: "no", browser: "no", note: "n/a"}
      comment.create: {api: "no", browser: "no", note: "n/a"}
      comment.delete: {api: "no", browser: "no", note: "n/a"}
      reaction.create: {api: "no", browser: "no", note: "message reactions exist but are not post reactions"}
      insights.get: {api: "limited", browser: "no", note: "messaging/template analytics"}
    urls:
      profile_edit: "https://business.facebook.com/wa/manage/phone-numbers/"
      compose: null

  - id: whatsapp_channel
    name: "WhatsApp Channel"
    kinds_supported: []
    default_kind: handoff
    auth: {kind: none, scopes: [], review_required: false, cost: "n/a"}
    profile:
      fields:
        - {id: name, max_len: null, rules: "required"}
        - {id: description, max_len: null, rules: "optional"}
      avatar: {w: null, h: null, aspect: "1:1", max_mb: null, shape: circle, note: "channel icon"}
      banner: null
    post_types:
      - {id: update, text_max: null, media: {images_max: null, aspects: [], video_max_s: null}, note: "text/photo/video/sticker/poll (unverified); editable 30 days; kept 30 days"}
    ops:
      profile.get: {api: "no", browser: "no", note: "no official API; automation is explicit-ban -> handoff"}
      profile.update.name: {api: "no", browser: "no", note: "handoff"}
      profile.update.bio: {api: "no", browser: "no", note: "handoff"}
      profile.update.avatar: {api: "no", browser: "no", note: "handoff"}
      profile.update.banner: {api: "no", browser: "no", note: "n/a"}
      post.create.text: {api: "no", browser: "no", note: "handoff via web.whatsapp.com Channels"}
      post.create.image: {api: "no", browser: "no", note: "handoff"}
      post.create.video: {api: "no", browser: "no", note: "handoff"}
      post.update: {api: "no", browser: "no", note: "handoff (<=30 days)"}
      post.delete: {api: "no", browser: "no", note: "handoff"}
      feed.list: {api: "no", browser: "no", note: "handoff"}
      comment.list: {api: "no", browser: "no", note: "n/a (reactions/votes only)"}
      comment.create: {api: "no", browser: "no", note: "n/a"}
      comment.delete: {api: "no", browser: "no", note: "n/a"}
      reaction.create: {api: "no", browser: "no", note: "handoff"}
      insights.get: {api: "no", browser: "no", note: "client-only"}
    urls:
      profile_edit: "https://web.whatsapp.com"
      compose: "https://web.whatsapp.com"

  - id: website
    name: "Website (own)"
    kinds_supported: [api]
    default_kind: api
    auth: {kind: local, scopes: [], review_required: false, cost: "free"}
    profile:
      fields:
        - {id: site_name, max_len: null, rules: "<title>, og:site_name, manifest name"}
        - {id: short_name, max_len: null, rules: "manifest short_name"}
        - {id: description, max_len: null, rules: "meta description, og:description, manifest description"}
        - {id: theme_color, max_len: null, rules: "manifest"}
      avatar: {w: 512, h: 512, aspect: "1:1", max_mb: null, shape: "maskable-circle", note: "also 192x192; maskable safe zone = circle radius 40% of width; favicon.ico 16/32/48, SVG icon, apple-touch-icon 180x180 (unverified)"}
      banner: {w: 1200, h: 630, aspect: "1.91:1", max_mb: 8, safe_area: null, note: "og:image min 200x200; twitter:image summary_large_image 2:1, min 300x157, max 4096x4096, <5 MB (secondary); new URL on change"}
    post_types:
      - {id: blog_post, text_max: null, media: {images_max: null, aspects: [], video_max_s: null}, note: "CMS/static generator; expose RSS/Atom"}
    ops:
      profile.get: {api: "yes", browser: "no", note: "read own files"}
      profile.update.name: {api: "yes", browser: "no", note: ""}
      profile.update.bio: {api: "yes", browser: "no", note: ""}
      profile.update.avatar: {api: "yes", browser: "no", note: "favicon set + manifest icons"}
      profile.update.banner: {api: "yes", browser: "no", note: "og/twitter images"}
      post.create.text: {api: "yes", browser: "no", note: ""}
      post.create.image: {api: "yes", browser: "no", note: ""}
      post.create.video: {api: "yes", browser: "no", note: ""}
      post.update: {api: "yes", browser: "no", note: ""}
      post.delete: {api: "yes", browser: "no", note: ""}
      feed.list: {api: "yes", browser: "no", note: ""}
      comment.list: {api: "no", browser: "no", note: "n/a"}
      comment.create: {api: "no", browser: "no", note: "n/a"}
      comment.delete: {api: "no", browser: "no", note: "n/a"}
      reaction.create: {api: "no", browser: "no", note: "n/a"}
      insights.get: {api: "yes", browser: "no", note: "own analytics/logs"}
    urls:
      profile_edit: null
      compose: null

  - id: linkedin_page
    name: "LinkedIn Company Page"
    kinds_supported: [api]
    default_kind: handoff
    auth:
      kind: oauth2
      scopes: [w_organization_social, r_organization_social, rw_organization_admin]
      review_required: "Community Management API vetting: Development tier then Standard tier (screencast)"
      cost: "free (gated)"
    profile:
      fields:
        - {id: name, max_len: null, rules: "100 per secondary source"}
        - {id: tagline, max_len: null, rules: "unknown"}
        - {id: description, max_len: null, rules: "unknown"}
        - {id: website, max_len: null, rules: ""}
        - {id: industry, max_len: null, rules: ""}
      avatar: {w: 400, h: 400, aspect: "1:1", min: "268x268", max_mb: 3, shape: square, note: "PNG/JPEG; shown on light and dark backgrounds"}
      banner: {w: 1512, h: 256, aspect: "5.9:1", max_mb: 3, safe_area: null, note: "min = recommended = 1512x256"}
    post_types:
      - {id: post, text_max: 3000, media: {images_max: 20, aspects: ["1.91:1"], video_max_s: 900}, note: "video 15 min desktop / 10 min mobile"}
      - {id: document, text_max: 3000, media: {images_max: 0, aspects: [], video_max_s: null}, note: "PDF carousel"}
    ops:
      profile.get: {api: "limited", browser: "no", note: "gated"}
      profile.update.name: {api: "limited", browser: "no", note: "field coverage unverified; bots banned by User Agreement"}
      profile.update.bio: {api: "limited", browser: "no", note: "unverified"}
      profile.update.avatar: {api: "limited", browser: "no", note: "unverified"}
      profile.update.banner: {api: "limited", browser: "no", note: "unverified"}
      post.create.text: {api: "limited", browser: "no", note: "Posts API (gated)"}
      post.create.image: {api: "limited", browser: "no", note: "gated"}
      post.create.video: {api: "limited", browser: "no", note: "gated"}
      post.update: {api: "limited", browser: "no", note: "gated"}
      post.delete: {api: "limited", browser: "no", note: "gated"}
      feed.list: {api: "limited", browser: "no", note: "gated"}
      comment.list: {api: "limited", browser: "no", note: "gated"}
      comment.create: {api: "limited", browser: "no", note: "gated"}
      comment.delete: {api: "limited", browser: "no", note: "gated"}
      reaction.create: {api: "limited", browser: "no", note: "gated"}
      insights.get: {api: "limited", browser: "no", note: "follower/page/share statistics (gated)"}
    urls:
      profile_edit: "https://www.linkedin.com/company/<ID>/admin/"
      compose: "https://www.linkedin.com/company/<ID>/admin/"

  - id: tiktok
    name: "TikTok"
    kinds_supported: [api]
    default_kind: api
    auth:
      kind: oauth2
      scopes: [user.info.basic, video.upload, video.publish, video.list]
      review_required: "audit required for public Direct Post; unaudited = private-only, 5 users/24h"
      cost: "free"
    profile:
      fields:
        - {id: username, max_len: 24, rules: "2-24; letters digits _ .; not ending in '.'; change once per 30 days; no API"}
        - {id: nickname, max_len: 30, rules: "change once per 7 days; no API"}
        - {id: bio, max_len: 80, rules: "historic 80; 160 reported (secondary); no API"}
      avatar: {w: null, h: null, aspect: "1:1", max_mb: null, shape: circle, note: "photo or video; no API"}
      banner: null
    post_types:
      - {id: video, text_max: 4000, media: {images_max: 0, aspects: ["9:16"], video_max_s: null}, note: "caption limit secondary; max length unknown (60 min reported)"}
      - {id: photo, text_max: 4000, media: {images_max: null, aspects: [], video_max_s: null}, note: "API: /v2/post/publish/content/init/ PHOTO"}
    ops:
      profile.get: {api: "yes", browser: "no", note: "Display API"}
      profile.update.name: {api: "no", browser: "no", note: "explicit-ban ToS -> handoff"}
      profile.update.bio: {api: "no", browser: "no", note: "handoff"}
      profile.update.avatar: {api: "no", browser: "no", note: "handoff"}
      profile.update.banner: {api: "no", browser: "no", note: "n/a"}
      post.create.text: {api: "no", browser: "no", note: "n/a"}
      post.create.image: {api: "limited", browser: "no", note: "audit; ~15 posts/day/creator"}
      post.create.video: {api: "limited", browser: "no", note: "video.upload to drafts (then handoff) or Direct Post after audit"}
      post.update: {api: "no", browser: "no", note: ""}
      post.delete: {api: "no", browser: "no", note: "handoff"}
      feed.list: {api: "yes", browser: "no", note: "video.list"}
      comment.list: {api: "no", browser: "no", note: ""}
      comment.create: {api: "no", browser: "no", note: ""}
      comment.delete: {api: "no", browser: "no", note: ""}
      reaction.create: {api: "no", browser: "no", note: ""}
      insights.get: {api: "limited", browser: "no", note: "basic user/video stats"}
    urls:
      profile_edit: "https://www.tiktok.com/@<USERNAME>"
      compose: "https://www.tiktok.com/tiktokstudio/upload"

  - id: telegram
    name: "Telegram (channel via bot)"
    kinds_supported: [api]
    default_kind: api
    auth: {kind: bot_token, scopes: [], review_required: false, cost: "free"}
    profile:
      fields:
        - {id: title, max_len: 128, rules: "1-128; setChatTitle"}
        - {id: description, max_len: 255, rules: "0-255; setChatDescription"}
        - {id: username, max_len: 32, rules: "5-32 (unverified)"}
      avatar: {w: null, h: null, aspect: "1:1", max_mb: null, shape: circle, note: "setChatPhoto; bot must be admin"}
      banner: null
    post_types:
      - {id: text, text_max: 4096, media: {images_max: 0, aspects: [], video_max_s: null}}
      - {id: photo, text_max: 1024, media: {images_max: 1, aspects: [], video_max_s: null}, note: "<=10 MB; w+h <= 10000; ratio <= 20"}
      - {id: media_group, text_max: 1024, media: {images_max: 10, aspects: [], video_max_s: null}, note: "2-10 items"}
      - {id: video, text_max: 1024, media: {images_max: 0, aspects: [], video_max_s: null}, note: "<=50 MB via cloud Bot API; <=2000 MB via local Bot API server"}
    ops:
      profile.get: {api: "yes", browser: "no", note: "getChat"}
      profile.update.name: {api: "yes", browser: "no", note: "setChatTitle"}
      profile.update.bio: {api: "yes", browser: "no", note: "setChatDescription"}
      profile.update.avatar: {api: "yes", browser: "no", note: "setChatPhoto"}
      profile.update.banner: {api: "no", browser: "no", note: "n/a"}
      post.create.text: {api: "yes", browser: "no", note: ""}
      post.create.image: {api: "yes", browser: "no", note: ""}
      post.create.video: {api: "yes", browser: "no", note: "50 MB cap"}
      post.update: {api: "yes", browser: "no", note: "editMessage*"}
      post.delete: {api: "yes", browser: "no", note: "needs can_post_messages / can_delete_messages"}
      feed.list: {api: "limited", browser: "no", note: "only updates received while running"}
      comment.list: {api: "limited", browser: "no", note: "linked discussion group"}
      comment.create: {api: "limited", browser: "no", note: "linked discussion group"}
      comment.delete: {api: "limited", browser: "no", note: "admin rights in discussion group"}
      reaction.create: {api: "yes", browser: "no", note: "setMessageReaction; no paid reactions"}
      insights.get: {api: "no", browser: "no", note: "none in Bot API"}
    urls:
      profile_edit: "https://web.telegram.org/a/"
      compose: "https://web.telegram.org/a/"

  - id: threads
    name: "Threads"
    kinds_supported: [api, browser]
    default_kind: api
    auth:
      kind: oauth2
      scopes: [threads_basic, threads_content_publish, threads_manage_replies, threads_read_replies, threads_manage_insights, threads_delete]
      review_required: "App Review for Advanced Access (unverified)"
      cost: "free; 250 posts, 1000 replies, 100 deletions per 24h"
    profile:
      fields:
        - {id: name, max_len: null, rules: "in-app only"}
        - {id: bio, max_len: null, rules: "in-app only"}
        - {id: link, max_len: null, rules: "in-app only"}
      avatar: {w: null, h: null, aspect: "1:1", max_mb: null, shape: circle, note: "can import from Instagram; no API"}
      banner: null
    post_types:
      - {id: text, text_max: 500, media: {images_max: 0, aspects: [], video_max_s: null}, note: "<=5 unique links; emoji counted in UTF-8 bytes"}
      - {id: image, text_max: 500, media: {images_max: 1, aspects: ["<=10:1"], video_max_s: null}, note: "JPEG/PNG <=8 MB, width 320-1440"}
      - {id: video, text_max: 500, media: {images_max: 0, aspects: ["9:16"], video_max_s: 300}, note: "MOV/MP4 <=1 GB"}
      - {id: carousel, text_max: 500, media: {images_max: 20, aspects: [], video_max_s: 300}, note: "2-20 items"}
    ops:
      profile.get: {api: "yes", browser: "yes", note: "threads_basic"}
      profile.update.name: {api: "no", browser: "yes", note: "broad-clause ToS risk"}
      profile.update.bio: {api: "no", browser: "yes", note: ""}
      profile.update.avatar: {api: "no", browser: "yes", note: ""}
      profile.update.banner: {api: "no", browser: "no", note: "n/a"}
      post.create.text: {api: "yes", browser: "yes", note: ""}
      post.create.image: {api: "yes", browser: "yes", note: ""}
      post.create.video: {api: "yes", browser: "yes", note: ""}
      post.update: {api: "no", browser: "yes", note: "in-app edit only (unverified)"}
      post.delete: {api: "yes", browser: "yes", note: "threads_delete; 100/24h"}
      feed.list: {api: "yes", browser: "yes", note: ""}
      comment.list: {api: "yes", browser: "yes", note: "threads_read_replies"}
      comment.create: {api: "yes", browser: "yes", note: "1000 replies/24h"}
      comment.delete: {api: "limited", browser: "yes", note: "hide replies; delete own"}
      reaction.create: {api: "no", browser: "yes", note: "no like endpoint (unverified)"}
      insights.get: {api: "yes", browser: "yes", note: "no user insights before 2024-04-13"}
    urls:
      profile_edit: "https://www.threads.com/"
      compose: "https://www.threads.com/"
```
