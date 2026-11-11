# CRAFT.md — how we make content worth a person's time, and the platform rules with their sources

Read this with [BRIEF.md](BRIEF.md) (the voice and the article rules) and [FACTS.md](FACTS.md) (the only things
we say about DGO). The skills `content-angles`, `video-studio` and `written-content` read it, and their checks
read its dates (`python3 apps/digital-assets/content/craft_age.py` lists every rule not re-checked in 6 months).

**Why this file exists.** The owner, 2026-11-04 (the group, messages 199–201): «אתה חייב למצוא סקילים הרבה
הרבה יותר טובים … וקונטקסט איך לייצר תוכן איכותי … וכל הטרנדים ומדריכים והיוכולות והכלים החדשים» and «אנחנו
באמת רוצים תמיד להביא ערך ולא רק להדהד דברים קיימים». A platform rule we follow without its source is a rumour;
a rule we never re-check is last year's rumour. So every rule below carries the primary source, the source's
own date, and the date someone opened it and checked (DGO-1395).

**How a rule changes.** newsflow's craft categories (`content`, `video-ai`, `growth`, `creative`, `brand`,
DGO-1400) bring the news. When a platform says something new, the row changes here first — with the new source
and today's date — and then the skills follow. `checked` is the date the source was opened, not the date the
row was typed.

## 1. What we tell the world

- **The one sentence** (the office's brief «מה אנחנו מספרים לעולם», 2026-11-04): *עסק שלם על מחשב אחד — עם AI
  שמשרת אותך, לא מנוי שמשרת את עצמו.* Every piece proves it with a number, a screen or a verdict, never a
  slogan.
- **Prove it by showing the office at work.** A real screen of a real office beats any render. Generated
  footage is B-roll at most, and is labelled as AI where the platform asks (§2, rules V11–V13).
- **Israeli reality first**: Hebrew, מע״מ 18%, חשבוניות ישראל, WhatsApp, a shekel price with its date.
- **«We are the only ones…» is a search result, not a feeling.** Write it only after `top_results` (the
  content-angles gate) shows nobody else does it, and then say what was searched.

### What counts as OURS (an idea without one never reaches the owner)

| kind | what it is | example from 2026-11-05 |
|---|---|---|
| measurement | a number we measured, with the method and the date | the office agent filed invoice 4117 in 7½ min for $0.016 of API tokens |
| screen | the office doing the thing, filmed from the real screen | the email arriving in «מייל», the row appearing in «קבצים» |
| israeli | the local reality the English internet does not cover | which tools the AI engines recommend when asked in Hebrew, from Israel |
| verdict | a judgement backed by evidence a reader can open | «run speech locally, rent the big language model» — with our numbers |

## 2. Short video — Reels, Shorts, TikTok

| # | rule | primary source | source date | checked |
|---|---|---|---|---|
| V1 | Judge a Reel by watch time, likes per reach and sends per reach; sends weigh a little more for reaching non-followers. | Adam Mosseri, https://www.instagram.com/p/DFFyRp-pINJ/ (login-walled; quoted in https://www.socialmediatoday.com/news/instagram-shares-algorithm-insights-2025/738034/) | 2025-01-21 | 2026-11-05 |
| V2 | Do not cut a Reel short only to raise completion: Instagram counts both the share watched and the seconds watched. | Mosseri on Threads, via https://www.socialmediatoday.com/news/instagram-longer-video-watch-time-versus-completion-rate/740916/ | 2025-02-25 | 2026-11-05 |
| V3 | Expect every Reel to be tried first on a small group of non-followers; their response decides the reach. | https://creators.instagram.com/blog/recommendations-and-originality | 2024-04-30 | 2026-11-05 |
| V4 | Post only footage we made, or third-party material we changed materially; borders, watermarks, subtitles and a caption credit are not a change. | https://creators.instagram.com/blog/rewarding-original-creators-on-instagram | 2026-04-30 | 2026-11-05 |
| V5 | Keep a significant share of each rolling 30 days original, or the whole account loses recommendations (Reels since 2024; photos and carousels since April 2026). | same as V4 | 2026-04-30 | 2026-11-05 |
| V6 | Never upload with another app's visible watermark. | https://creators.instagram.com/blog/recommendations-and-originality | 2024-04-30 | 2026-11-05 |
| V7 | Reels and Shorts: 3 minutes at most. Our reels are 30–45 s. | Reels: Mosseri, https://www.threads.net/@mosseri/post/DE-efFqyStv · Shorts: https://support.google.com/youtube/answer/12779649 | 2025-01-18 · 2024-10-15 | 2026-11-05 |
| V8 | Export 1080×1920 (9:16), H.264, 30 fps, AAC. | the platforms' spec pages (Meta's Ads Guide URL answered 404 on 2026-11-05: re-find it) | — | 2026-11-05 (secondary) |
| V9 | Keep text and faces out of the top 14%, the bottom 35% and 6% at each side (≈269 / 672 / 65 px at 1080×1920) — the conservative union of the three apps. | no primary source found; figures from ad-tool vendors | — | 2026-11-05 (unverified) |
| V10 | Mix dialogue to about −14 LUFS integrated, true peak ≤ −1 dBTP; YouTube turns louder audio down. | https://meterplugs.com/blog/2019/09/18/youtube-changes-loudness-reference-to-14-lufs.html (measured, not published by YouTube) | 2019-09-18 | 2026-11-05 (secondary) |
| V11 | Label realistic AI-made video or voice on Instagram with the AI disclosure; C2PA/IPTC metadata is detected. | https://about.fb.com/news/2024/02/labeling-ai-generated-images-on-facebook-instagram-and-threads/ | 2024-02-06 (upd. 2025-04-01) | 2026-11-05 |
| V12 | On TikTok, label realistic AI-generated content; TikTok labels C2PA content by itself. | https://newsroom.tiktok.com/more-ways-to-spot-shape-and-understand-ai-content | 2025-11-19 | 2026-11-05 |
| V13 | On YouTube, disclose realistic synthetic content; a voice-over in a cloned voice of your own is exempt — a stock synthetic narrator over real screens needs no label, a fake person does. | https://support.google.com/youtube/answer/14328491 | read 2026-11-05 | 2026-11-05 |
| V14 | On TikTok design for watching to the end; a finished longer video is a strong signal, follower count is not. | https://newsroom.tiktok.com/en-us/how-tiktok-recommends-videos-for-you | 2020-06-18 | 2026-11-05 |
| V15 | Put the message in the first 3 seconds; text on screen helps (TikTok's ad data: 63% of the highest-CTR videos did). | https://ads.tiktok.com/business/en-US/blog/9-creative-tips-to-drive-auction-ad-performance | 2020-10-21 | 2026-11-05 |
| V16 | Make every frame readable without sound: burned-in captions and on-screen text, because many watch muted. | Facebook IQ (2016, secondary): captions raised view time 12% | 2016-02 | 2026-11-05 (secondary) |
| V17 | Judge Shorts by engaged views: since 2025-03-31 every start or replay counts as a view. | https://support.google.com/youtube/answer/10059070 | 2025-03-31 | 2026-11-05 |

**Our practice on top of the rules** (not platform rules — what we decided, and why):
- The hook is on screen AND spoken in the first 2 seconds, readable at 0.5 s (V15, V16).
- One idea per reel; the picture changes every 2–4 s; it ends on a loop back to the hook or one call to act.
- Captions are Hebrew, right to left, in logical order, the spoken word highlighted, inside the V9 band.
- The numbers spoken are the numbers measured on that take; a demo document says it is one.

## 3. Long video — YouTube

| # | rule | primary source | source date | checked |
|---|---|---|---|---|
| Y1 | The first 30 seconds deliver what the title and thumbnail promised; the strongest moment comes early. | https://support.google.com/youtube/answer/9314415 | read 2026-11-05 | 2026-11-05 |
| Y2 | Chapters: the first at 00:00, at least 3, ascending, each ≥ 10 s. | https://support.google.com/youtube/answer/9884579 | read 2026-11-05 | 2026-11-05 |
| Y3 | Test 3 titles and 3 thumbnails with Test & Compare (the winner by watch time; up to 2 weeks; not for Shorts). | https://support.google.com/youtube/answer/13861714 | read 2026-11-05 | 2026-11-05 |
| Y4 | Upload Hebrew captions as a UTF-8 .srt with no styling. | https://support.google.com/youtube/answer/2734698 | read 2026-11-05 | 2026-11-05 |
| Y5 | Aim at satisfaction, not clicks: recommendations weigh viewing, likes, dislikes and surveys. | https://www.youtube.com/howyoutubeworks/product-features/recommendations/ | read 2026-11-05 | 2026-11-05 |
| Y6 | Never mass-produce templated or AI-repeated videos («inauthentic content» is not monetised). | YouTube Partner Program update, in effect 2025-07-15 (press; the Help page not opened yet) | 2025-07-15 | 2026-11-05 (secondary) |

## 4. Written — articles, LinkedIn, X, carousels

| # | rule | primary source | source date | checked |
|---|---|---|---|---|
| W1 | Publish original information, reporting, research or analysis — not rewrites. | https://developers.google.com/search/docs/fundamentals/creating-helpful-content | 2026-10-05 | 2026-11-05 |
| W2 | Make it obvious who wrote it, how it was made and why it exists. | same | 2026-10-05 | 2026-11-05 |
| W3 | Never publish AI text in bulk without human editing; never write to a word count. | same | 2026-10-05 | 2026-11-05 |
| W4 | Write unique, non-commodity content. | https://developers.google.com/search/blog/2025/05/succeeding-in-ai-search | 2025-05-21 | 2026-11-05 |
| W5 | Structured data says only what the visible page says. | https://developers.google.com/search/docs/appearance/structured-data/sd-policies | 2026-07-10 | 2026-11-05 |
| W6 | Add quotations, statistics and cited sources; they raised visibility in generative answers by 30–40% in the GEO study; keyword stuffing did not. | https://arxiv.org/abs/2311.09735 (KDD 2024) | 2024-06-28 (v3) | 2026-11-05 |
| W7 | Short, self-contained answers; never hide a key fact in a tab, an image or a PDF. | https://about.ads.microsoft.com/en/blog/post/october-2025/optimizing-your-content-for-inclusion-in-ai-search-answers | 2025-10-08 | 2026-11-05 |
| W8 | LinkedIn: write for relevance and real insight; no engagement bait, pods or automated comments. | https://news.linkedin.com/2026/ImprovingTheFeed | 2026-03-12 | 2026-11-05 |
| W9 | LinkedIn: hold attention — a post people skip is scored down. | https://www.linkedin.com/blog/engineering/feed/understanding-feed-dwell-time | 2020-05-12 | 2026-11-05 |
| W10 | X: write for replies, quotes and shares by DM or link (weights 5, 5, 5, 20 against a like's 0.7); anything that draws «not interested», mute or report costs far more (−53 to −234). Cite the file by commit: it changes weekly. | https://github.com/xai-org/x-algorithm/blob/main/home-mixer/params/param.rs | file committed 2026-11-05 | 2026-11-05 |

## 5. AEO — being named in the answers of ChatGPT, Gemini, Perplexity, Claude and Google

| # | rule | primary source | source date | checked |
|---|---|---|---|---|
| A1 | Google AI Overviews / AI Mode need no special markup, file or «AI text»: do good SEO, keep key content in crawlable text. | https://developers.google.com/search/docs/appearance/ai-features | 2025-12-10 | 2026-11-05 |
| A2 | Measure AI-feature traffic in Search Console's Performance report (Web). | same | 2025-12-10 | 2026-11-05 |
| A3 | Verify the site in Bing Webmaster Tools and read its AI Performance report (citations in Copilot and Bing's AI answers). | https://blogs.bing.com/webmaster/February-2026/Introducing-AI-Performance-in-Bing-Webmaster-Tools-Public-Preview | 2026-02-10 | 2026-11-05 |
| A4 | Report AI visibility as the share of answers that name us over many prompts × runs — never as an «AI rank»: the same list came back twice in < 1 in 100 runs. | https://sparktoro.com/blog/new-research-ais-are-highly-inconsistent-when-recommending-brands-or-products-marketers-should-take-care-when-tracking-ai-visibility/ | 2026-01-27 | 2026-11-05 |
| A5 | Earn branded mentions on the sites the answers cite: across ~75K brands, mentions correlated with AI Overview visibility at 0.664, backlinks at 0.218 (Spearman, Google AIO only). | https://ahrefs.com/blog/ai-overview-brand-correlation/ | 2025-05-26 | 2026-11-05 |
| A6 | Be on YouTube, Reddit and Wikipedia where honest: they lead the citations (Perplexity, 3.1M US queries: Reddit 24.6%, YouTube 14.2%, Wikipedia 7.2% of the top-50 share). Quote a share with its metric and date — they move. | https://ahrefs.com/blog/most-cited-domains-perplexity/ | 2026-11-03 | 2026-11-05 |
| A7 | llms.txt is optional, for agents and coding tools; never count it as an AEO lever (97% of 137K sites with one got no request for it). | https://ahrefs.com/blog/llmstxt-study/ | 2026-06-15 | 2026-11-05 |
| A8 | A Wikidata item only with serious public references; never edit a Wikipedia article about us — propose on its talk page with a disclosed conflict of interest. | https://www.wikidata.org/wiki/Wikidata:Notability · https://en.wikipedia.org/wiki/Wikipedia:Conflict_of_interest | 2026-11-01 | 2026-11-05 |

**Our panel** (aeo-watch, DGO-1399): 40 fixed prompts in Hebrew and English (category, problem, comparison,
brand, Israeli-local) — `apps/digital-assets/aeo/prompts.json` — on every engine we can reach, three runs, every
week, read from Israel. What it records per answer: named or not, our URLs cited, the alternatives named, every
cited source, and for brand prompts what it says about DGO against FACTS.md.

## 6. Hebrew voice and captions

| # | rule | primary source | source date | checked |
|---|---|---|---|---|
| H1 | The Hebrew TTS that wins blind votes today: Gemini 3.1 Flash TTS (Elo 1586), Deepdub, ElevenLabs v3, Soniox; Blue V2 (MIT, CPU) is the best free local one. Audition before choosing; the owner picks by ear. | https://ivrit-ai-tts-arena-hebrew.hf.space/leaderboard | Nov 2026 (live) | 2026-11-05 |
| H2 | ElevenLabs' multilingual v2 and flash v2.5 do not speak Hebrew; eleven_v3 does, with `language_code: "he"`. | https://elevenlabs.io/docs/overview/models | read 2026-11-05 | 2026-11-05 |
| H3 | Azure's Hebrew voices are he-IL-HilaNeural and he-IL-AvriNeural (standard neural; word-boundary events for captions). The free `edge-tts` reaches the same voices with no terms allowing commercial use — auditions only. | https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support?tabs=tts | read 2026-11-05 | 2026-11-05 |
| H4 | Non-commercial voices are out: Phonikud-TTS checkpoints, the Piper Hebrew voice and Meta MMS-TTS (CC-BY-NC). | https://huggingface.co/Phonikud/phonikud-tts-checkpoints · https://huggingface.co/facebook/mms-tts-heb | read 2026-11-05 | 2026-11-05 |
| H5 | OpenAI's TTS models shut down on 2027-01-06 — do not build on them. | https://developers.openai.com/api/docs/guides/text-to-speech | read 2026-11-05 | 2026-11-05 |
| H6 | Write numbers as words in the voice script, and say brand names the way people do (DGO → «די־ג׳י־או»); the captions keep the digits and the brand. | our auditions, 2026-11-05 (DGO-1401) | 2026-11-05 | 2026-11-05 |

Word timings for captions come from the office's own speech model on the rendered voice (apitools, ivrit.ai;
`verbose_json` gives each word's start and end), so every voice gets exact captions without a vendor's
timestamps.

## 7. Tools — never hard-code a model

- Generation is by API, and the best model changes monthly: read a public leaderboard (Artificial Analysis'
  text-to-video and text-to-speech arenas, ivrit.ai's Hebrew arena) on the day, and write the model and the
  date into the piece's scorecard.
- What the herd has, measured: no GPU on the HP (`nvidia-smi` absent, 2026-11-05) — so local generation means
  CPU models only (BlueTTS, ivrit.ai Whisper, Tesseract), and video generation is API-only.

## 8. After posting — what is measured

| when | what | where it goes |
|---|---|---|
| 48 h | Reels: average watch time, reach, likes/reach, sends/reach · Shorts: engaged views, viewed vs swiped · TikTok: average watch time, finished % | the piece's `scorecard.json` (video-studio) |
| 7 days | LinkedIn: impressions, dwell signals the page shows · X: replies, quotes, shares | the same scorecard |
| weekly | the AEO panel (A4): share of answers naming us, cited domains | the AEO page (DGO-1404) |

## 9. Re-check log

| date | rows | by | what changed |
|---|---|---|---|
| 2026-11-05 | all | DGO-1395 (first version) | Written from three read-only research passes (video, written + AEO, Hebrew TTS), each source opened. Corrected on the way: the «16% of Perplexity's citations» is Ahrefs' June-2025 figure (14.2% on the live page); SparkToro tested ChatGPT, Claude and Google, not Gemini or Perplexity; Ahrefs' 75K-brand study is May 2025 and Google AIO only; Instagram's April-2026 originality change extended the Reels rule to photos and carousels. |
