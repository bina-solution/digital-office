"""main.py — NewsFlow: the office's own news, collected through the OFFICE BROWSER, organised by category.

WHY THIS SHAPE (DGO-1348). The owner's own prototype (github.com/solomonBoltin/NewsFlow) was a standalone
Apify scraper: its own playwright, its own selectors, its own LLM context, and its output went to a Telegram
channel — nothing an office could use. Here the collection is the office's browser (browser42): one signed-in
Chromium the owner already watches, with the sites' real pages instead of a bot-shaped request, and no second
browser to keep alive. Everything else is the office's shape: a store on its own volume, four channels
(view, CLI, HTTP API, the event stream), and every source's failure reported instead of hidden.

FOUR CHANNELS, one contract:
  view  — /a/newsflow/ in the console (static/index.html, Hebrew, RTL)
  CLI   — ./bbox newsflow collect|list|categories|status (apps/newsflow/hooks/*)
  API   — http://newsflow:8991/api/{news,categories,collect,status,review/queue,review,site,competitors}   (newsflow.v1)
  flow  — dgo:flow:newsflow, one `article.new` per new article (flow.v1)

Storage is one sqlite file on the app's volume: a re-read of a page is not a second article (dedupe by URL).

THE REVIEW STEP (DGO-1383). The owner asked for news on the company site, in his eight sections (2026-11-04:
ai, llm, hardware, business, funding, regulation, global, israel). A headline the browser read is not yet
something the site may say: a reviewer — an office agent, then a second reader — opens the story, writes a
summary IN ITS OWN WORDS, says why it matters, places it in a section, and approves or rejects it. Reviews
live in their own table, so collection never waits for them and a review never edits what was collected.
Only `approved` leaves the office: `GET /api/site` is the site's feed, and nothing else is.

COMPETITORS (DGO-1384). The owner asked for «איסוף מלא של כל מה שקשור לכל אחד מהמתחרים שלנו». The watchlist
(watchlist.json beside this file: names in Hebrew and English, domains, product keywords) marks every new article
whose title or address names a competitor as a MENTION of it; `GET /api/competitors` answers per competitor how
many mentions and the latest ones. The competitors' own news pages are listed there but are NOT sources of the
routine pass: 27 more tabs every pass would push the regular sources out of its budget. Office-internal: mentions
never reach the site.
"""
from __future__ import annotations

import json
import os
import re
import socket
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("NEWSFLOW_PORT", "8991"))
DB = os.environ.get("NEWSFLOW_DB", "/data/newsflow.db")
BROWSER = (os.environ.get("BROWSER42_URL") or "http://browser42:8766").rstrip("/")
# the runner's token, read from the office's vault (DGO-1152): browser42 names this app a reader of its task
# runner's token (its app.json, `token_readers`), and the vault hands it over to this container alone
VAULT = (os.environ.get("CONNECTIONS_URL") or "http://connections:8990").rstrip("/")
RUNNER_SERVICE = "browser42-task-runner"
FLOW_APP = "newsflow"
REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_PW = os.environ.get("REDIS_PASSWORD", "")
VERSION = "0.2.0"
#: One browser verb's own clock. A site that hangs (a paywall interstitial, a bot wall) must cost one
#: source's slot, not the whole pass: measured 2026-11-04 — a 20-source pass with a 90 s clock sat for
#: half an hour on the sites that never answered.
B42_TIMEOUT = float(os.environ.get("NEWSFLOW_B42_TIMEOUT", "60"))
#: Opening a page is the slow half (an ad-heavy homepage paints for a minute), and the answer that
#: arrives at 50 s is not a failure — it is the same page. One retry, then it is a real failure.
OPEN_TIMEOUT = float(os.environ.get("NEWSFLOW_OPEN_TIMEOUT", "90"))
#: A screenshot is the slowest evidence verb (a full-page capture on a heavy page): its own clock.
SHOT_TIMEOUT = float(os.environ.get("NEWSFLOW_SHOT_TIMEOUT", "90"))
#: A whole pass has its own budget: past it the sources that are left are reported «skipped», not
#: quietly waited for. Measured 2026-11-04: one pass over twenty sources, three of them hanging on a
#: paywall or a bot wall, held the lock for half an hour and the screen said nothing.
PASS_BUDGET_S = float(os.environ.get("NEWSFLOW_PASS_BUDGET_S", "1800"))

#: The taxonomy is the owner's own list (his words, 2026-11-04), each with the sources that feed it.
#: A source that changes shape is a row «failed: why» in the run, never a silent empty category.
CATEGORIES = [
    ("tech", "טכנולוגיה"),
    ("ai", "בינה מלאכותית"),
    ("models", "מודלים חדשים"),
    ("benchmarks", "בנצ'מארקים"),
    ("oss", "כלים בקוד פתוח"),
    ("cloud", "ענן"),
    ("business", "עסקים"),
    ("marketing", "שיווק"),
    ("israel", "ישראל"),
    ("startups", "כחול-לבן וסטארטאפים"),
    ("initiatives", "יוזמות"),
    ("bureaucracy", "בירוקרטיה ישראלית"),
    ("law", "חוק ומשפט"),
    ("vc", "קרנות הון"),
    # The owner's own model of what matters to BINA Solutions (2026-11-04): every step that makes AI better
    # and cheaper to run on PRIVATE compute is a step for this product; every stock and every cyber item is
    # for our clients; every new AI working standard is how we work.
    ("private-ai", "AI על מחשוב פרטי"),
    ("local-models", "מודלים מקומיים"),
    ("speech", "דיבור וקול"),
    ("vision", "ראייה ותמונה"),
    ("hardware", "חומרה ומאיצים"),
    ("cyber", "סייבר"),
    ("standards", "תקנים ושיטות עבודה"),
    ("market-il", "בורסת ת\"א"),
    ("market-global", "שווקים עולמיים"),
    ("ai-economy", "כלכלת ה-AI"),
    # Not a section of the web — a KIND of item (the owner, 2026-11-04): a law, a fund, a raise, a new
    # venture, an Innovation Authority track. Served as its own tab, computed from the headline.
    ("opportunities", "הזדמנויות עסקיות"),
    # The owner's own priority (2026-11-04 18:29): how good content is MADE — the craft, the tools that
    # changed this month, and what the people who do it for a living are learning. A feed about news is not
    # enough; the office has to know HOW, not only WHAT happened.
    ("content", "יצירת תוכן"),
    ("video-ai", "וידאו ורילס"),
    ("prompting", "פרומפטינג ושיטות"),
    # …and the discipline that decides whether anyone ever SEES it (the owner, 2026-11-04 18:31): being
    # the answer an AI gives, not only a page a person finds.
    ("growth", "צמיחה, SEO ו-AEO"),
    ("brand", "מיתוג, שפה ושמות"),
    ("creative", "קריאייטיב ופרסום"),
    ("competitors", "מתחרים"),
]

#: What makes a headline an OPPORTUNITY for us or for a client — money, a call, a rule that changed.
OPPORTUNITY_CUES = ("מכרז", "מענק", "מענקים", "קול קורא", "מסלול", "קרן", "קרנות", "מימון", "גיוס",
                    "השקעה", "הנפקה", "רשות החדשנות", "תוכנית", "תכנית", "פטור", "הטבה", "חוק",
                    "תקנות", "רגולציה", "ממשלה", "grant", "funding", "tender", "call for", "raise")
CAT_NAME = dict(CATEGORIES)

#: The site's sections (the owner's list for bina-solutions.co.il/news/, 2026-11-04) and the section a category
#: suggests to the reviewer. A suggestion only: the reviewer places each story where it belongs.
SECTIONS = ["ai", "llm", "hardware", "business", "funding", "regulation", "global", "israel"]
SECTION_OF = {"tech": "global", "ai": "ai", "models": "llm", "benchmarks": "llm", "oss": "ai", "cloud": "business",
              "business": "business", "marketing": "business", "israel": "israel", "startups": "funding",
              "initiatives": "regulation", "bureaucracy": "regulation", "law": "regulation", "vc": "funding",
              "private-ai": "ai", "local-models": "llm", "speech": "ai", "vision": "ai", "hardware": "hardware",
              "cyber": "global", "standards": "regulation", "market-il": "israel", "market-global": "global",
              "ai-economy": "business", "opportunities": "funding", "content": "business", "video-ai": "ai",
              "prompting": "ai", "growth": "business", "brand": "business", "creative": "business",
              "competitors": "business"}
#: A summary is ours, short, and not the source's prose: past this many words it is not a summary.
SUMMARY_MAX_WORDS = 45

SOURCES = [
    ("techcrunch", "https://techcrunch.com/", "tech"),
    ("themarker", "https://www.themarker.com/", "business"),
    ("calcalist", "https://www.calcalist.co.il/", "israel"),
    ("globes", "https://en.globes.co.il/", "israel"),
    ("timesofisrael", "https://www.timesofisrael.com/", "israel"),
    ("geektime", "https://www.geektime.co.il/", "startups"),
    ("techinasia", "https://www.techinasia.com/", "israel"),
    ("hackernews", "https://news.ycombinator.com/", "oss"),
    ("github-trending", "https://github.com/trending", "oss"),
    ("openai", "https://openai.com/news/", "models"),
    ("huggingface", "https://huggingface.co/blog", "models"),
    ("arxiv-cs-ai", "https://arxiv.org/list/cs.AI/recent", "benchmarks"),
    ("aws", "https://aws.amazon.com/blogs/aws/", "cloud"),
    ("google-cloud", "https://cloudblog.withgoogle.com/", "cloud"),
    ("ft", "https://www.ft.com/", "business"),
    ("marketingweek", "https://www.marketingweek.com/", "marketing"),
    ("calcalist-legal", "https://www.calcalist.co.il/law", "law"),
    ("globes-vc", "https://en.globes.co.il/en/section/technology", "vc"),
    ("gov-il", "https://www.gov.il/he/departments/news", "bureaucracy"),
    ("innovation-israel", "https://innovationisrael.org.il/", "initiatives"),
    # The owner's own ask (2026-11-04): the Telegram technology channels, read through their public
    # preview pages — the same browser, the same pass. @TechIL is the channel he named.
    ("techil-tg", "https://t.me/s/TechIL", "tech"),
    ("geektime-tg", "https://t.me/s/geektimecoil", "startups"),
    # …and the sources an Israeli business actually needs to see: the money, the regulation, the winners.
    ("vccafe", "https://www.vccafe.com/", "vc"),
    ("nocamels", "https://nocamels.com/", "startups"),
    ("calcalist-tech", "https://www.calcalist.co.il/tech", "tech"),
    ("ivc", "https://www.ivc-online.com/", "vc"),
    ("startupnationcentral", "https://www.startupnationcentral.org/", "startups"),
    # What the owner's own source actually links to: 200 posts of «עדכוני טכנולוגיה» (@TechIL) carry 155
    # links and only SIX domains, ranked here by use — the Israeli tech press he reads through Telegram,
    # read directly instead (2026-11-04, DGO-1350).
    ("gadgety", "https://www.gadgety.co.il/", "tech"),          # 66 links in 200 posts
    ("hwzone", "https://hwzone.co.il/", "tech"),                # 37
    ("walla-tech", "https://tech.walla.co.il/", "tech"),        # 13
    ("mako", "https://www.mako.co.il/", "israel"),              # 14
    ("maariv", "https://www.maariv.co.il/", "israel"),          # 13
    ("ynet", "https://www.ynet.co.il/", "israel"),              # 12
    # ── AI on private compute: the family of sources that decides how good and how cheap it gets ──
    ("hf-models-trending", "https://huggingface.co/models?sort=trending", "local-models"),
    ("ollama-blog", "https://ollama.com/blog", "private-ai"),
    ("llamacpp-releases", "https://github.com/ggml-org/llama.cpp/releases", "local-models"),
    ("simonwillison", "https://simonwillison.net/", "standards"),
    ("reddit-localllama", "https://www.reddit.com/r/LocalLLaMA/top/?t=week", "local-models"),
    ("whisper-releases", "https://github.com/openai/whisper/releases", "speech"),
    ("anthropic-news", "https://www.anthropic.com/news", "models"),
    ("deepmind-blog", "https://deepmind.google/discover/blog/", "models"),
    ("nvidia-news", "https://nvidianews.nvidia.com/news/latest", "hardware"),
    # ── the two stacks the owner named: Israeli capital markets, and the giants ──
    ("globes-markets", "https://en.globes.co.il/en/section/markets", "market-il"),
    ("bizportal", "https://www.bizportal.co.il/", "market-il"),
    ("tase", "https://www.tase.co.il/", "market-il"),
    ("cnbc-tech", "https://www.cnbc.com/technology/", "market-global"),
    ("yahoo-finance-tech", "https://finance.yahoo.com/technology/", "market-global"),
    # ── cyber, the thing every client asks about ──
    ("cyberscoop", "https://cyberscoop.com/", "cyber"),
    ("securityweek", "https://www.securityweek.com/", "cyber"),
    # ── the opportunity surfaces (the owner, 2026-11-04): tenders, grants, funds, the Innovation Authority ──
    ("mr-tenders", "https://mr.gov.il/ilgstorefront/he/search?q=%D7%9E%D7%9B%D7%A8%D7%96", "opportunities"),
    ("innovation-programs", "https://innovationisrael.org.il/programs/", "opportunities"),
    ("bird-fund", "https://www.birdf.org/", "opportunities"),
    ("globes-law", "https://en.globes.co.il/en/section/law", "law"),
    # ── the craft of content: the tools that changed this week, and the people who teach the work ──
    ("runway", "https://runwayml.com/blog", "video-ai"),
    ("elevenlabs", "https://elevenlabs.io/blog", "video-ai"),
    ("heygen", "https://www.heygen.com/blog", "video-ai"),
    ("descript", "https://www.descript.com/blog", "video-ai"),
    ("hf-text-to-video", "https://huggingface.co/models?pipeline_tag=text-to-video&sort=trending", "video-ai"),
    ("anthropic-engineering", "https://www.anthropic.com/engineering", "prompting"),
    ("prompting-guide", "https://www.promptingguide.ai/", "prompting"),
    ("google-ai-blog", "https://blog.google/technology/ai/", "content"),
    ("buffer-resources", "https://buffer.com/resources/", "content"),
    ("social-media-today", "https://www.socialmediatoday.com/", "content"),
    ("exploding-topics", "https://explodingtopics.com/blog", "content"),
    # ── being found, and being the one an AI cites: search, answer engines, brand and naming ──
    ("searchengineland", "https://searchengineland.com/", "growth"),
    ("searchenginejournal", "https://www.searchenginejournal.com/", "growth"),
    ("ahrefs", "https://ahrefs.com/blog/", "growth"),
    ("semrush", "https://www.semrush.com/blog/", "growth"),
    ("backlinko", "https://backlinko.com/blog", "growth"),
    ("moz", "https://moz.com/blog", "growth"),
    ("later-blog", "https://later.com/blog/", "creative"),
    ("adweek", "https://www.adweek.com/", "creative"),
    ("adage", "https://adage.com/", "creative"),
    ("brandnew", "https://www.underconsideration.com/brandnew/", "brand"),
    # ── the three categories that were EMPTY on the owner's own screen (2026-11-05, his photo of the tile):
    # «בינה מלאכותית», «ראייה ותמונה», «כלכלת ה-AI» had no source at all, so a taxonomy that leads with AI
    # could never fill its first row. A category with no source is not an empty category — it is a missing one.
    ("techcrunch-ai", "https://techcrunch.com/category/artificial-intelligence/", "ai"),
    ("venturebeat-ai", "https://venturebeat.com/category/ai/", "ai"),
    ("theverge-ai", "https://www.theverge.com/ai-artificial-intelligence", "ai"),
    ("arstechnica-ai", "https://arstechnica.com/ai/", "ai"),
    ("wired-ai", "https://www.wired.com/tag/artificial-intelligence/", "ai"),
    ("mit-tr-ai", "https://www.technologyreview.com/topic/artificial-intelligence/", "ai"),
    ("roboflow-blog", "https://blog.roboflow.com/", "vision"),
    ("vision-systems", "https://www.vision-systems.com/", "vision"),
    ("aibusiness", "https://aibusiness.com/", "ai-economy"),
    ("ai-news", "https://www.artificialintelligence-news.com/", "ai-economy"),
    ("stanford-hai", "https://hai.stanford.edu/news", "ai-economy"),
    # ── the sections a business owner actually reads (measured 2026-11-05, DGO-1350): the app was reading
    # homepages, so the Hebrew business press reached it as general news and the sections that carry the
    # decisions a client makes — taxes, wages, litigation, advertising budgets, the bond market — were missed.
    ("globes-he", "https://www.globes.co.il/", "business"),
    ("globes-he-markets", "https://www.globes.co.il/news/home.aspx?fid=585", "market-il"),
    ("globes-he-law", "https://www.globes.co.il/news/home.aspx?fid=829", "law"),
    ("globes-he-careers", "https://www.globes.co.il/news/home.aspx?fid=3266", "business"),
    ("globes-he-marketing", "https://www.globes.co.il/news/home.aspx?fid=821", "marketing"),
    ("globes-he-tech", "https://www.globes.co.il/news/home.aspx?fid=594", "tech"),
    ("ynet-economy", "https://www.ynet.co.il/economy", "business"),
    ("ynet-law", "https://www.ynet.co.il/economy/category/10610", "law"),
    ("ynet-markets", "https://www.ynet.co.il/economy/category/11652", "market-il"),
    ("ynet-tech", "https://www.ynet.co.il/economy/category/65252", "tech"),
    ("ice", "https://www.ice.co.il/", "business"),
    ("ice-marketing", "https://www.ice.co.il/advertising-marketing", "marketing"),
    ("ice-law", "https://www.ice.co.il/law", "law"),
    ("ice-finance", "https://www.ice.co.il/finance", "market-il"),
    # «what was breached this week, and what needs a patch» — the cyber that lands on a small business
    ("bleepingcomputer", "https://www.bleepingcomputer.com/", "cyber"),
    # depth: one aggregator that covers twenty feeds, AI with a business angle, and the private-compute stack
    ("techmeme", "https://www.techmeme.com/", "tech"),
    ("the-decoder", "https://the-decoder.com/", "ai-economy"),
    ("hf-papers", "https://huggingface.co/papers", "benchmarks"),
    ("vllm-blog", "https://vllm.ai/blog", "private-ai"),
    ("google-research", "https://research.google/blog/", "models"),
    ("mistral-news", "https://mistral.ai/news/", "local-models"),
    ("crunchbase-news", "https://news.crunchbase.com/", "vc"),
    # ── Telegram, read through the public preview pages: the Hebrew channels that carry the business day.
    # The research named the ones it verified; the ones it could NOT verify are deliberately absent.
    ("calcalist-tg", "https://t.me/s/calcalist", "business"),
    ("globes-tg", "https://t.me/s/globesnews", "market-il"),
    ("ai-hebrew-tg", "https://t.me/s/ai_hebrew", "ai"),
    ("technews-heb-tg", "https://t.me/s/technewsheb", "tech"),
    ("techisrael-tg", "https://t.me/s/TechIsrael", "startups"),
    ("cyber-ai-il-tg", "https://t.me/s/tech_cyber_ai_israel", "cyber"),
    # ── The recognition research (DGO-1712, 2026-11-09): every site the web research of the partnerships /
    # investment / TASE plan drew on, at its news page. The research's 12 searches returned 235 links on 133
    # domains: 9 domains were already followed above (bleepingcomputer, venturebeat, the-decoder, calcalist,
    # globes, timesofisrael, innovationisrael, vccafe, github), 15 are left out because they hold no news (a
    # shop, a copied README, a forum thread, a defunct company, a personal feed link — each named with why in
    # research_notes/Bina recognition partnerships and investment 2026-11-09/README.md), and the other 124
    # domains became these 108 sources at their news page — a few merged (the MCP docs and its blog,
    # fosdem.org and its list archive). Measured from the MacBook with curl, a plain client: 77 answer 200,
    # 17 answer 403 (bot protection — this app reads through browser42, a real browser), 11 addresses were
    # wrong, corrected and re-checked.
    ("agskills", "https://agskills.dev/", "standards"),
    ("aicatchup", "https://aicatchup.com/news/", "ai"),
    ("aicodex", "https://www.aicodex.to/articles", "ai"),
    ("aiengineerguide", "https://aiengineerguide.com/til/", "prompting"),
    ("aiweekly", "https://aiweekly.co/", "ai"),
    ("algemeiner", "https://www.algemeiner.com/", "israel"),
    ("alpic-blog", "https://alpic.ai/blog", "standards"),
    ("arynews-tech", "https://arynews.tv/", "tech"),
    ("ats-news", "https://ats.org/ats-news/", "israel"),
    ("australianjewishnews", "https://www.australianjewishnews.com/", "israel"),
    ("claude-blog", "https://claude.com/blog", "models"),
    ("claudemarketplaces", "https://claudemarketplaces.com/", "standards"),
    ("cryptobriefing", "https://cryptobriefing.com/", "ai-economy"),
    ("ctech", "https://www.calcalistech.com/ctechnews", "startups"),
    ("cxodigitalpulse", "https://www.cxodigitalpulse.com/", "ai-economy"),
    ("devco-blog", "https://dev.co/blog", "ai"),
    ("developersdigest", "https://www.developersdigest.tech/blog", "ai"),
    ("devto-selfhosted", "https://dev.to/t/selfhosted", "oss"),
    ("dice-insights", "https://www.dice.com/career-advice", "tech"),
    ("digitalocean-blog", "https://www.digitalocean.com/blog", "cloud"),
    ("digitalocean-notes", "https://docs.digitalocean.com/release-notes/", "cloud"),
    ("do-marketplace-notes", "https://docs.digitalocean.com/release-notes/marketplace/", "cloud"),
    ("dsebastien", "https://www.dsebastien.net/", "standards"),
    ("ecosystems-blog", "https://blog.ecosyste.ms/", "oss"),
    ("enterpriseaiworld", "https://www.enterpriseaiworld.com/Articles/News/", "ai-economy"),
    ("entrepreneurloop", "https://entrepreneurloop.com/", "startups"),
    ("eseospace-blog", "https://eseospace.com/blog/", "growth"),
    ("eweek-news", "https://www.eweek.com/news/", "tech"),
    ("fdd-analysis", "https://www.fdd.org/analysis/", "israel"),
    ("fosdem-news", "https://fosdem.org/2027/news/", "oss"),
    ("fourweekmba", "https://fourweekmba.com/", "ai-economy"),
    ("fundsforcompanies", "https://fundsforcompanies.fundsforngos.org/", "initiatives"),
    ("gend-blog", "https://www.gend.co/blog", "ai"),
    ("getdrio-blog", "https://www.getdrio.com/blog", "ai"),
    ("glama-blog", "https://glama.ai/blog", "standards"),
    ("guptadeepak", "https://guptadeepak.com/", "startups"),
    ("hackernoon", "https://hackernoon.com/", "tech"),
    ("hackingpc", "https://hackingpc.pages.dev/", "hardware"),
    ("home-assistant-blog", "https://www.home-assistant.io/blog/", "oss"),
    ("i24-economy", "https://www.i24news.tv/en/news/israel/economy", "israel"),
    ("ice-world", "https://www.ice.it/it/news", "market-global"),
    ("incorpx-grants", "https://www.incorpx.io/grants", "initiatives"),
    ("infoq-news", "https://www.infoq.com/news/", "oss"),
    ("innmind-deals", "https://innmind.com/startup-deals/", "startups"),
    ("inss-he", "https://www.inss.org.il/he/publication/", "israel"),
    ("intellinews", "https://www.intellinews.com/", "market-global"),
    ("israeldesks", "https://israeldesks.com/", "vc"),
    ("israelhayom", "https://www.israelhayom.com/", "israel"),
    ("jefferies-insights", "https://www.jefferies.com/insights/", "market-global"),
    ("jewishnews-uk", "https://www.jewishnews.co.uk/", "israel"),
    ("jewishpress-israel", "https://www.jewishpress.com/news/israel/", "israel"),
    ("jns-israel", "https://www.jns.org/israel-news/", "israel"),
    ("jpost-business", "https://www.jpost.com/business-and-innovation", "business"),
    ("juedische-allgemeine", "https://www.juedische-allgemeine.de/israel/", "israel"),
    ("letsdatascience-news", "https://letsdatascience.com/news", "ai"),
    ("levelup-latest", "https://levelup.gitconnected.com/latest", "prompting"),
    ("linuxfr-news", "https://linuxfr.org/news", "oss"),
    ("luminik-cfp", "https://www.luminik.io/call-for-speakers", "initiatives"),
    ("madhyamam-tech", "https://www.madhyamamonline.com/technology", "tech"),
    ("malaymail-tech", "https://www.malaymail.com/news/tech-gadgets", "tech"),
    ("matrix-blog", "https://matrix.org/blog/", "oss"),
    ("mcp-blog", "https://blog.modelcontextprotocol.io/", "standards"),
    ("mcpbundles", "https://www.mcpbundles.com/guides", "standards"),
    ("milken-israel", "https://milkeninnovationcenter.org/publications/", "market-il"),
    ("minipclab", "https://minipclab.com/blog", "hardware"),
    ("mixed-news", "https://mixed-news.com/en/", "ai"),
    ("moburst-blog", "https://www.moburst.com/blog/", "growth"),
    ("mondovisione", "https://mondovisione.com/media-and-resources/news/", "market-global"),
    ("openhab-blog", "https://www.openhab.org/blog/", "oss"),
    ("opportunitiesforyouth", "https://opportunitiesforyouth.org/", "initiatives"),
    ("pcbuildadvisor", "https://www.pcbuildadvisor.com/", "hardware"),
    ("pertama-funding", "https://www.pertamapartners.com/funding", "initiatives"),
    ("pillitteri", "https://pasqualepillitteri.it/en/", "ai"),
    ("prnewswire-il", "https://www.prnewswire.com/il/news-releases/", "israel"),
    ("pulsebot-ai", "https://pulse.bot/", "ai"),
    ("qveris", "https://qveris.ai/", "standards"),
    ("refreshmiami", "https://refreshmiami.com/news/", "startups"),
    ("remio-blog", "https://www.remio.ai/blog", "ai"),
    ("roxyapi-blogs", "https://roxyapi.com/blogs", "standards"),
    ("selfhosting-sh", "https://selfhosting.sh/", "oss"),
    ("semafor-business", "https://www.semafor.com/vertical/business", "market-global"),
    ("simplywallst-il", "https://simplywall.st/markets/il", "market-il"),
    ("solosatoshi-blog", "https://www.solosatoshi.com/blog/", "hardware"),
    ("speakeasy-blog", "https://www.speakeasy.com/blog", "standards"),
    ("stackone-blog", "https://www.stackone.com/blog", "standards"),
    ("starryhope", "https://www.starryhope.com/", "hardware"),
    # The one competitor whose own news page the research named. It is a MENTION source like the rest of
    # its category: its articles are counted against the watchlist and never reach the site.
    ("start9-blog", "https://start9.com/", "competitors"),
    ("startupim", "https://startupim.com/", "vc"),
    ("stocktitan-news", "https://www.stocktitan.net/news/", "market-global"),
    ("sunpeak-blogs", "https://sunpeak.ai/blog/", "standards"),
    ("techbytes", "https://techbytes.app/posts/", "tech"),
    ("techrepublic-ai", "https://www.techrepublic.com/topic/artificial-intelligence/", "ai"),
    ("tedium", "https://tedium.co/", "tech"),
    ("theinformation-briefings", "https://www.theinformation.com/briefings", "ai-economy"),
    ("theprint-tech", "https://theprint.in/tech/", "tech"),
    ("toi-blogs", "https://blogs.timesofisrael.com/", "israel"),
    ("toolnavs", "https://toolnavs.com/", "ai"),
    ("unite-ai", "https://www.unite.ai/", "ai"),
    ("unraid-blog", "https://unraid.net/blog", "oss"),
    ("vibeindex", "https://vibeindex.ai/", "standards"),
    ("virtualizationhowto", "https://www.virtualizationhowto.com/", "oss"),
    ("voidly-agentic", "https://voidly.ai/", "ai-economy"),
    ("webpronews", "https://www.webpronews.com/", "tech"),
    ("webull-news", "https://www.webull.com/", "market-global"),
    ("xwiki-blog", "https://www.xwiki.org/xwiki/bin/view/Blog/", "oss"),
    ("ynetnews-business", "https://www.ynetnews.com/business", "israel"),
    ("yourstory-ai", "https://yourstory.com/ai-story", "ai"),
    ("zima-blog", "https://shop.zimaspace.com/blogs/zima-campaign-hub", "hardware"),
]

#: What «ראשי» puts first. The taxonomy the owner wrote leads with AI and technology, and an item that is
#: merely the newest must not lead a business news app: on 2026-11-05 thirteen restaurants held the top of
#: the feed while the market and the regulation of the same hour sat below them. Recency still orders
#: everything INSIDE a group (the sort is stable), so the lead is the newest of the front group.
FRONT = ("ai", "tech", "business", "israel", "startups", "market-il", "market-global", "vc", "law",
         "cyber", "ai-economy", "models", "cloud", "oss", "benchmarks", "hardware", "standards",
         "initiatives", "bureaucracy", "opportunities", "private-ai", "local-models")

def _watchlist() -> list[dict]:
    """The competitors to follow — watchlist.json beside this file; none when it is missing or unreadable."""
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchlist.json"), encoding="utf-8") as f:
            rows = json.load(f)
        return [w for w in (rows.get("watchlist") if isinstance(rows, dict) else rows) or [] if w.get("id")]
    except (OSError, ValueError):
        return []


WATCHLIST = _watchlist()


def mentions_of(url: str, title: str) -> list[str]:
    """The competitors an article names: by a domain in its address, or a name or product keyword in its title
    (a whole word — «Wix» in a title, not «wix» inside another word; a Hebrew name takes up to two prefix letters,
    «בוויקס», «שמאנדיי»)."""
    host = urllib.parse.urlsplit(url).netloc.lower()
    low = (title or "").lower()
    found = []
    for w in WATCHLIST:
        if any(host == d or host.endswith("." + d) for d in (x.lower() for x in w.get("domains") or [])):
            found.append(w["id"]); continue
        terms = [t.lower() for t in (w.get("names") or []) + (w.get("keywords") or []) if len(t) >= 3]
        pre = lambda t: "[והבכלמש]{0,2}" if re.match(r"[\u0590-\u05FF]", t) else ""
        if any(re.search(r"(?<![\w])" + pre(t) + re.escape(t) + r"(?![\w])", low) for t in terms):
            found.append(w["id"])
    return found


_LOCK = threading.Lock()


# ── the store ────────────────────────────────────────────────────────────────────────────────────────
def db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB) or ".", exist_ok=True)
    c = sqlite3.connect(DB, timeout=20)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    with db() as c:
        c.executescript("""
        create table if not exists articles (
          id integer primary key,
          url_key text unique,          -- the URL without its query: the same page twice is one article
          url text not null, title text not null, source text not null, category text not null,
          snippet text default '', found_at text not null, first_seen_at text not null);
        create table if not exists runs (
          id integer primary key, started_at text not null, ended_at text, added integer default 0,
          sources_ok integer default 0, report text default '{}');
        create index if not exists articles_found on articles(found_at desc);
        create index if not exists articles_cat on articles(category, found_at desc);
        create table if not exists reviews (
          url_key text primary key,      -- the article it reviews
          section text not null, lang text default 'he', summary_he text not null, why_he text default '',
          status text not null check (status in ('approved','rejected')), reason text default '',
          reviewer text not null, reviewed_at text not null, published_at text default '');
        create index if not exists reviews_site on reviews(status, section, reviewed_at desc);
        create table if not exists mentions (
          url_key text not null, competitor text not null, found_at text not null,
          primary key (url_key, competitor));
        create index if not exists mentions_by on mentions(competitor, found_at desc);
        """)
        # The card's picture, beside the sentence. Kan-11's own homepage carries 315 images (measured
        # 2026-11-05) and its cards are image-first; a text-only list of the same stories reads as a worse
        # product (the owner, msg 179). Added in place, so the articles already in the store are untacked.
        cols = {r["name"] for r in c.execute("pragma table_info(articles)")}
        if "image" not in cols:
            c.execute("alter table articles add column image text default ''")
        c.commit()


#: Every browser task this app opens, on the volume. A task is a TAB in the shared browser, a browser42 slug
#: is immutable and lives forever, and a task that stalls stays stalled — so a pass that dies mid-way leaves
#: tabs behind and the next pass meets `browser_tab_pressure` on its first source (measured 2026-11-04: the
#: office browser was left with 8 tabs and NOTHING could open a page until it was restarted). This file is
#: what lets the next pass close exactly what this app opened, and nothing else.
TASKS = os.environ.get("NEWSFLOW_TASKS", "/data/tasks.json")


#: When each source was last tried, so a pass that cannot reach the end of the list still rotates through it.
SEEN = os.environ.get("NEWSFLOW_SEEN", "/data/source-seen.json")


def source_seen(slug: str = "", at: float = 0.0) -> dict:
    """Read the per-source clock, or stamp one source and write it back."""
    try:
        with open(SEEN, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    if not slug:
        return {k: float(v) for k, v in data.items() if isinstance(v, (int, float))}
    data[slug] = at
    try:
        tmp = SEEN + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, SEEN)
    except OSError:
        pass
    return data


def tasks_read() -> list[str]:
    try:
        with open(TASKS, "r", encoding="utf-8") as fh:
            v = json.load(fh)
        return [str(x) for x in v] if isinstance(v, list) else []
    except (OSError, ValueError):
        return []


def tasks_write(slugs: list[str]) -> None:
    try:
        with open(TASKS + ".tmp", "w", encoding="utf-8") as fh:
            json.dump(sorted(set(slugs))[-40:], fh)
        os.replace(TASKS + ".tmp", TASKS)
    except OSError:
        pass


def tasks_close(slugs: list[str]) -> list[str]:
    """Close what this app left open; return the ones that would not close (named, never silent)."""
    left = []
    for slug in slugs:
        for verb in ("close", "finish"):             # close drops the group's tabs; finish ends the task
            try:
                b42(verb, slug, timeout=20)
                break
            except Exception:
                continue
        else:
            left.append(slug)
    return left


#: A call-to-action or a menu entry is not a headline. «VIEW OUR MEDIA LIBRARY» became the lead story of the
#: first Kan-11-shaped screen (2026-11-04), so the same test runs twice: when a page is read, and when the feed
#: is served — the junk already in the store is history, not something to delete, but it is not news either.
NAV_CUES = ("view our", "read more", "learn more", "sign in", "log in", "subscribe", "contact us",
            "book a", "book an", "cookie", "privacy policy", "glossary", "opportunities", "conferences",
            "all rights", "follow us", "terms of", "menu",
            # the owner's own screenshot (#180): a paywall's own pitch is not a headline
            "members only", "remove all ads", "support toi", "support us", "sign up", "donate",
            "ad-free", "newsletter", "community (", "tradingview", "עקוב אחר", "הירשמו", "הצטרפו",
            "לחצו כאן", "כל הזכויות", "מדיניות פרטיות", "צור קשר", "תנאי שימוש", "מנויי", "למנויים",
            "בשיתוף",   # «…בשיתוף GWS» — a paid placement, not the site's journalism
            # A page's own link interstitial is a sentence with no story in it, and it led the front page
            # on 2026-11-05 («whatsapp מעבר לאתר חיצוני»): the same words every browser overlay uses.
            "מעבר לאתר חיצוני", "אתר חיצוני", "external site", "opens in a new", "נפתח בחלון",
            "whatsapp מעבר", "קישור חיצוני"
            # a job board is not news (measured 2026-11-05: eleven «Developer Wanted» cards led the Israel feed)
            "(onsite)", "(remote)", "onsite)", "we are hiring", " משרה ", "דרוש/ה")

#: A page's own furniture lives at a predictable address, whatever its headline says: a job card, a tag page, a
#: sign-in wall. The URL is the honest signal, because the title can be anything (measured 2026-11-05).
PROMO_PATHS = ("/jobs/", "/job/", "/careers", "/advertise", "/subscribe", "/newsletter", "/tag/",
               "/author/", "/login", "/signin", "/sign-in", "/pricing", "/shop/", "/wiki/")

#: Cards glue their clock and their section label to the headline: «09:26 …», «לפני 54 דקות …», «1h ago …»,
#: «FEATURED PREMIUM …», «בלעדי | …». The label is furniture; the sentence after it is the story (#180).
PREFIX_RE = re.compile(
    r"""^(?:
        \d{1,2}:\d{2}
      | לפני\s*\d+\s*(?:דקות|שעות|ימים|שבועות|חודשים)
      | \d+\s*(?:h|m|d|hr|hrs|min|mins)\s*ago
      | featured(?:\s+premium)? | premium | sponsored | exclusive
      | בלעדי | פרשנות | וידאו | צפייה | גלריה | עדכון | חי
    )\s*(?:[|·:\-–—]\s*)?\s*""", re.I | re.X)


def clean_title(title: str) -> str:
    """The headline without the card's own clock or section label."""
    t = " ".join((title or "").split())
    for _ in range(3):
        n = PREFIX_RE.sub("", t, count=1)
        if n == t:
            break
        t = " ".join(n.split())
    # A clock glued to the sentence with no space («7h agoOman fintech…»).
    t = re.sub(r"^\d+\s*(?:h|m|d|hr|min)\s*ago(?=[A-Z\u0590-\u05FF])", "", t, flags=re.I)
    # …and the same clock at the END, with the reporter's name after it («… 09:26 מיכל דאב»).
    t = re.sub(r"\s+\d{1,2}:\d{2}\s+[^\d]{2,40}$", "", t)
    # The reading-time and byline a blog card glues to its headline («… By Drew Bradstock · 11-minute read»).
    t = re.sub(r"\s+By\s+[^•·]{2,40}?\s*[•·]?\s*\d+[- ]minute read$", "", t, flags=re.I)
    t = re.sub(r"\s*[•·]?\s*\d+[- ]minute read$", "", t, flags=re.I)
    return t.strip(" -–—|·:")


def is_headline(title: str, url: str = "") -> bool:
    t = clean_title(title)
    if len(t) < 22 or " " not in t:
        return False
    if url:
        path = urllib.parse.urlsplit(url).path.lower()
        if any(p in path for p in PROMO_PATHS):
            return False
    if t.startswith(("{", "}", "[", "]")) or (t.count("{") + t.count("}")) > 0:
        return False
    letters = [c for c in t if c.isalpha()]
    if letters and all(c.isupper() for c in letters):
        return False
    low = t.lower()
    if any(cue in low for cue in NAV_CUES):
        return False
    # A pay grade is not a story: «Product Owner Daya Wira Performa IDR 6M – 11M».
    if re.search(r"\bIDR\s*\d|\bRp\s*\d|\bsalary\b", t, re.I):
        return False
    return True


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def url_key(url: str) -> str:
    u = urllib.parse.urlsplit(url)
    return f"{u.scheme}://{u.netloc}{u.path}".rstrip("/").lower()


# ── the event stream (flow.v1) — a failed publish never fails a collection ───────────────────────────
def _resp(rf):
    head = rf.readline()
    if not head:
        raise ConnectionError("redis closed")
    h = head.rstrip(b"\r\n")
    k, rest = h[:1], h[1:]
    if k == b"+":
        return rest.decode()
    if k == b"-":
        raise ConnectionError(rest.decode()[:200])
    if k == b":":
        return int(rest)
    if k == b"$":
        n = int(rest)
        return None if n < 0 else rf.read(n + 2)[:-2].decode("utf-8", "replace")
    if k == b"*":
        n = int(rest)
        return None if n < 0 else [_resp(rf) for _ in range(n)]
    raise ConnectionError("unexpected reply")


def publish(events: list[dict]) -> str:
    """XADD each event to dgo:flow:newsflow. Returns "" when it landed, else why it did not."""
    if not events:
        return ""
    try:
        s = socket.create_connection((REDIS_HOST, REDIS_PORT), timeout=10)
        rf = s.makefile("rb")

        def cmd(*args):
            out = [b"*%d\r\n" % len(args)]
            for a in args:
                b = a if isinstance(a, bytes) else str(a).encode()
                out.append(b"$%d\r\n%s\r\n" % (len(b), b))
            s.sendall(b"".join(out))
            return _resp(rf)

        if REDIS_PW:
            cmd("AUTH", REDIS_PW)
        for ev in events:
            cmd("XADD", "dgo:flow:" + FLOW_APP, "MAXLEN", "~", "1000", "*",
                "type", ev["type"], "title", ev["title"][:300], "at", ev.get("at") or now(),
                "app", FLOW_APP, "link", ev.get("link", ""), "data", json.dumps(ev.get("data") or {}, ensure_ascii=False))
        s.close()
        return ""
    except (OSError, ConnectionError) as e:
        return f"the stream was not written ({e})"


# ── collection, through the office browser ───────────────────────────────────────────────────────────
def own_container_id() -> str:
    """This container's id — the second factor the vault asks of a reader (platform-base/connections/identity.py).
    Docker mounts /var/lib/docker/containers/<id>/… into every container, so mountinfo names it. The same
    reading as apps/dgo-extend/converge.py own_container_id (an app imports no other app's code)."""
    for path, marker in (("/proc/self/mountinfo", "/containers/"), ("/proc/self/cgroup", "/docker/")):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    i = line.find(marker)
                    while i != -1:
                        cand = line[i + len(marker):i + len(marker) + 64]
                        if len(cand) == 64 and all(c in "0123456789abcdef" for c in cand):
                            return cand
                        i = line.find(marker, i + 1)
        except OSError:
            continue
    return ""


_RUNNER_TOKEN = {"value": "", "missed_at": 0.0}
#: after the vault handed nothing over, the next ask waits this long: a pass makes many calls, and an unreachable
#: vault must not add its timeout to each of them (the second reader)
TOKEN_MISS_S = 60


def runner_token(fresh: bool = False) -> str:
    """The task runner's token from the vault, kept in memory and asked again when `fresh`. "" when the vault does
    not hand it over (not named, not reachable): the runner then answers as its BROWSER42_TASK_AUTH says — served
    while it warns, a 401 once it refuses, and the vault's own sentence is in its grant log."""
    if not fresh and (_RUNNER_TOKEN["value"] or time.time() - _RUNNER_TOKEN["missed_at"] < TOKEN_MISS_S):
        return _RUNNER_TOKEN["value"]
    req = urllib.request.Request(f"{VAULT}/api/agent-token/{RUNNER_SERVICE}",
                                 headers={"X-Conn-Container": own_container_id()})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            _RUNNER_TOKEN["value"] = str(json.loads(r.read() or b"{}").get("token") or "").strip()
    except (urllib.error.URLError, OSError, ValueError, AttributeError):
        _RUNNER_TOKEN["value"] = ""
    if not _RUNNER_TOKEN["value"]:
        _RUNNER_TOKEN["missed_at"] = time.time()
    return _RUNNER_TOKEN["value"]


def b42(*argv: str, timeout: float = 90):
    """One browser42 task verb (`./bbox b42 task …`) over its agent door, with the runner's token (DGO-1152), and
    its JSON answer. A 401 asks the vault once more (a token the runner rotated), then stands."""
    body = json.dumps({"argv": list(argv)}, ensure_ascii=False).encode()
    for attempt in (1, 2):
        headers = {"content-type": "application/json; charset=utf-8"}
        token = runner_token(fresh=attempt == 2)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(BROWSER + "/v1/task", data=body, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code != 401 or attempt == 2:
                raise


IMAGES_JS = (
    "JSON.stringify(Object.fromEntries(Array.from(document.querySelectorAll('a')).map(function (a) {"
    "  var i = a.querySelector('img');"
    "  var im = i ? (i.currentSrc || i.src || (i.dataset && (i.dataset.src || i.dataset.original"
    "                || i.dataset.lazy || i.dataset.srcset)) || '') : '';"
    "  if (im && im.slice(0, 2) === '//') { im = 'https:' + im; }"
    "  return [a.href, im || ''];"
    "}).filter(function (kv) { return kv[1] && /^https?:/.test(kv[1]); })))")


def image_map(task: str) -> dict:
    """href → the picture the card itself shows, from ONE evaluate on the page we already have open.

    `inspect` gives the links (and it is the protocol's evidence); it does not give pictures, and a feed
    without them is the difference the owner named between our app and Kan-11 (msg 179). The page is
    already loaded, so this is one call, not one visit per article.
    """
    try:
        answer = b42("js", task, IMAGES_JS, timeout=B42_TIMEOUT)
        raw = (answer or {}).get("result")
        data = json.loads(raw) if isinstance(raw, str) else (raw or {})
        if not isinstance(data, dict):
            return {}
        return {k: v for k, v in data.items() if isinstance(v, str) and v.startswith(("http://", "https://"))}
    except Exception:
        return {}


def text_of(answer) -> str:
    """The page's text out of a task answer, whatever depth the door nests it at."""
    stack = [answer]
    while stack:
        cur = stack.pop()
        if isinstance(cur, str) and len(cur) > 40:
            return cur
        if isinstance(cur, dict):
            for k in ("text", "content", "read", "page", "data", "output", "result"):
                if k in cur:
                    stack.append(cur[k])
            stack.extend(v for k, v in cur.items() if k not in ("text", "content", "read", "page", "data", "output", "result"))
        elif isinstance(cur, list):
            stack.extend(cur)
    return ""


LINK = re.compile(r"\[([^\]\n]{18,180})\]\(([^)\s]{12,400})\)")
BARE = re.compile(r"<a[^>]+href=\"(https?://[^\"]{12,400})\"[^>]*>([^<]{10,180})</a>", re.I)
#: The page's own anchors, asked of the browser instead of guessed from its text: `read` gives a clean text
#: with NO links in it (measured on Hacker News, 2026-11-04 — the text was perfect and every headline's URL
#: was gone), so the links come from the DOM, which every site has.
JS_LINKS = ("JSON.stringify([...document.querySelectorAll('a[href]')]"
            ".map(a=>({t:(a.textContent||'').replace(/\\s+/g,' ').trim(),u:a.href}))"
            ".filter(x=>x.t&&x.u&&x.u.startsWith('http')).slice(0,400))")


def links_from_js(answer, base: str) -> list[tuple[str, str]]:
    """(url, title) pairs out of the `js` verb's answer — the DOM's anchors, absolute and deduped."""
    raw = answer.get("result") if isinstance(answer, dict) else None
    if not isinstance(raw, str):
        return []
    try:
        rows = json.loads(raw)
    except ValueError:
        return []
    return _clean([(r.get("u") or "", r.get("t") or "") for r in rows if isinstance(r, dict)], base)


def links_from(text: str, base: str) -> list[tuple[str, str]]:
    """(url, title) pairs a person would click, out of a page's TEXT (the fallback when `js` is refused)."""
    out = []
    for m in LINK.finditer(text):
        out.append((urllib.parse.urljoin(base, m.group(2).strip()), m.group(1).strip()))
    for m in BARE.finditer(text):
        out.append((urllib.parse.urljoin(base, m.group(1)), re.sub(r"<[^>]+>", "", m.group(2)).strip()))
    return _clean(out, base)


def _clean(pairs: list[tuple[str, str]], base: str) -> list[tuple[str, str]]:
    """What a person would click: a real headline, on its own URL — never the site's own chrome."""
    host = urllib.parse.urlsplit(base).netloc
    clean, seen = [], set()
    for url, title in pairs:
        title = " ".join((title or "").split())
        u = urllib.parse.urlsplit(url or "")
        if not u.netloc or not title:
            continue
        if not is_headline(title, url):
            continue
        if u.netloc == host and u.path in ("", "/"):    # the site linking to itself
            continue
        k = url_key(url)
        if k in seen:
            continue
        seen.add(k)
        clean.append((url, clean_title(title)[:300]))
    return clean[:25]


def collect(categories: list[str] | None) -> dict:
    with _LOCK:
        started = now()
        with db() as c:
            run = c.execute("insert into runs(started_at) values (?)", (started,)).lastrowid
            c.commit()
        report, added, events, ok = {}, 0, [], 0
        want = [s for s in SOURCES if not categories or s[2] in categories]
        # The list does not fit one pass (a source costs ~40–90 s and the budget is 30 min), and taking it in
        # order starved the tail FOREVER: the sources added last never ran at all (measured 2026-11-05). Each
        # pass starts with the sources that were collected longest ago, so every source gets its turn — and a
        # source added today is unseen (timestamp 0), so the pass after the change reads the NEW ones first
        # (DGO-1712, measured 2026-11-09: 221 sources, ~60 s a source, so one pass reaches ~25 of them and a
        # full cycle is four to five passes; the budget stays 30 min because that browser is the owner's too).
        seen = source_seen()
        want.sort(key=lambda s: seen.get(s[0], 0))
        leftover = tasks_read()
        if leftover:
            left = tasks_close(leftover)
            tasks_write(left)
            print(f"[newsflow] closed {len(leftover) - len(left)} leftover browser task(s)"
                  + (f"; {len(left)} would not close: {', '.join(left)}" if left else ""), flush=True)
        open_tasks = tasks_read()
        deadline = time.time() + PASS_BUDGET_S
        for slug, url, cat in want:
            t0 = time.time()
            if t0 > deadline:
                report[slug] = "skipped: the pass ran out of its %ds budget" % PASS_BUDGET_S
                continue
            # A browser42 slug is immutable and lives forever, and a task that stalls stays stalled: a fixed
            # `nf-<source>` made the SECOND pass answer `duplicate_slug` for every source and leave six tabs
            # behind (measured 2026-11-04). So each pass gets its own task, and the task is always closed.
            task = f"nf{run}-{slug}"
            handles: list = []                       # per source: a stale one from the last page is not evidence
            source_seen(slug, time.time())
            open_tasks = tasks_read() + [task]
            tasks_write(open_tasks)                  # written BEFORE the tab exists: a crash leaves a record
            try:
                opened = False
                for attempt in (0, 1):
                    try:
                        b42("start", task, url, timeout=OPEN_TIMEOUT)
                        opened = True
                        break
                    except Exception as e:
                        if attempt:
                            raise
                        # a fresh task slug is the one thing that differs on the second try: a task whose
                        # tab stalled keeps its state, while a new one opens a new tab (measured 2026-11-05:
                        # the retry that opened calcalist answered where the first attempt timed out).
                        task = f"{task}-r"
                        tasks_write(tasks_read() + [task])
                        time.sleep(3)
                # The links come from `inspect`, which is the protocol's own way to ask a page what it holds:
                # every control with its handle, name and href. (`read` returns the page's TEXT with the links
                # stripped; `js` works but is no evidence, which is what left tabs open.)
                controls = b42("inspect", task, timeout=B42_TIMEOUT).get("controls") or []
                links = [(c.get("href") or "", c.get("name") or "") for c in controls
                         if isinstance(c, dict) and c.get("href") and c.get("role") == "link"]
                found = _clean(links, url)
                handles = [c.get("handle") for c in controls if isinstance(c, dict) and c.get("handle")]
                if not found:
                    report[slug] = "no links read (the page may need the owner's eyes) · %.0fs" % (time.time() - t0)
                    continue
                ok += 1
                ts = now()
                imgs = image_map(task)               # the cards' own pictures, one evaluate on the open page
                with db() as c:
                    for link, title in found:
                        k = url_key(link)
                        img = imgs.get(link, "")
                        if c.execute("select 1 from articles where url_key=?", (k,)).fetchone():
                            # An article already in the store gets its picture the first time a source shows
                            # one: the pass heals the rows that were read before pictures were kept, instead
                            # of leaving an old feed that is text and a new feed that is not.
                            if img:
                                c.execute("update articles set image=? where url_key=? and coalesce(image,'')=''",
                                          (img, k))
                            continue
                        c.execute("""insert into articles(url_key,url,title,source,category,image,found_at,first_seen_at)
                                     values (?,?,?,?,?,?,?,?)""",
                                  (k, link, title[:300], slug, cat, img, ts, ts))
                        for comp in mentions_of(link, title):
                            c.execute("insert or ignore into mentions(url_key,competitor,found_at) values (?,?,?)", (k, comp, ts))
                        added += 1
                        events.append({"type": "article.new", "at": ts, "link": link,
                                       "title": f"{CAT_NAME.get(cat, cat)} · {title[:120]}",
                                       "data": {"url": link, "title": title[:300], "source": slug,
                                                "category": cat, "category_he": CAT_NAME.get(cat, cat)}})
                    c.commit()
            except Exception as e:                       # one source never stops the pass
                report[slug] = f"failed: {str(e)[:160]}"
            finally:
                # Always close the task — a stalled or timed-out one holds a tab, and the browser's tab cap
                # (6) is what turns one slow source into a pass where everything after it reads nothing.
                # `close` is the verb that drops the group's TAB; `finish` only ends the task, and it refuses
                # without the task's evidence checks (measured 2026-11-04: `result_not_accepted … run task
                # verify`, so a pass that called finish alone leaked one tab per source until the browser hit
                # its cap and nothing could open a page). close first, then finish for the bookkeeping.
                # browser42 ends a task only when its evidence checks pass, and the tab is freed by that
                # same `finish` — there is no `close` on the door. So the evidence is produced on purpose:
                # one `extract` (a record), one `screenshot`, then verify and finish.
                #
                # …but only when there is a page to give evidence about. A source whose `start` never opened
                # (`opened` false: a timeout on a loaded machine) has no tab and nothing to photograph, and the
                # four-verb dance still spent a screenshot's 90 s and two 60 s verbs on it, TWICE with the
                # retry — measured 2026-11-09 (DGO-1712): one timed-out source cost ~370 s of a 1800 s pass,
                # so nine sources were all a pass could reach, and the 108 sources the item added could never
                # be covered. Such a task is dropped the cheap way (`tasks_close`: close, then finish, 20 s
                # each) and named in the report if it will not drop.
                if not opened:
                    left = tasks_close([task])
                    if left:
                        report[slug] = (report.get(slug, "") + " · its tab would not close").strip(" ·")
                    else:
                        tasks_write([t for t in tasks_read() if t != task])
                else:
                    closed = False
                    for attempt in (0, 1):
                        try:
                            if attempt == 0 and handles:
                                b42("extract", task, handles[min(1, len(handles) - 1)], timeout=B42_TIMEOUT)
                            b42("screenshot", task, timeout=SHOT_TIMEOUT)
                            b42("verify", task, timeout=B42_TIMEOUT)
                            b42("finish", task, timeout=B42_TIMEOUT)
                            closed = True
                            break
                        except Exception as e:
                            if attempt:
                                report[slug] = (report.get(slug, "")
                                                + f" · its tab is still open ({str(e)[:60]})").strip(" ·")
                            else:
                                time.sleep(3)
                    if closed:
                        tasks_write([t for t in tasks_read() if t != task])
        flow_err = publish(events)
        ended = now()
        with db() as c:
            c.execute("update runs set ended_at=?, added=?, sources_ok=?, report=? where id=?",
                      (ended, added, ok, json.dumps(report, ensure_ascii=False), run))
            c.commit()
        return {"run": run, "started_at": started, "ended_at": ended, "added": added,
                "sources_ok": ok, "sources_tried": len(want), "report": report, "flow": flow_err or "ok"}


# ── the API ──────────────────────────────────────────────────────────────────────────────────────────
def order_front(rows: list) -> list:
    """«ראשי»: the front group first, newest first inside each group.

    The list arrives newest-first from SQL and `sort` is stable, so this only moves the groups — the order a
    reader already trusts inside a category is never rewritten.
    """
    # The lead a reader's eye lands on must be a card with a picture: an item read before pictures were kept
    # would otherwise hold the top of the page as a blank tile (measured 2026-11-05, the same hour the images
    # arrived). Group first, then the picture, then the recency SQL already gave us.
    # …and this is a Hebrew product read by Israeli business people: an English item waits behind a Hebrew one
    # of the same group, never disappears (the global sources stay, just not as the lead).
    hebrew = lambda t: 1 if any("\u0590" <= ch <= "\u05FF" for ch in (t or "")) else 0
    return sorted(rows, key=lambda r: (0 if r.get("category") in FRONT else 1,
                                       0 if r.get("image") else 1,
                                       0 if hebrew(r.get("title")) else 1))


def news(category: str = "", limit: int = 60, source: str = "") -> dict:
    q = "select url,title,source,category,image,found_at from articles"
    args: list = []
    # `source=<slug>`: one source's own items. It is how a pass's coverage is judged — «did the source I added
    # really give a headline?» — without reading the app's database from the outside (DGO-1712).
    where: list = []
    if source:
        where.append("source=?")
        args.append(source)
    if category == "opportunities":
        where.append("(" + " or ".join("title like ?" for _ in OPPORTUNITY_CUES) + ")")
        args.extend(["%" + c + "%" for c in OPPORTUNITY_CUES])
    elif category:
        where.append("category=?")
        args.append(category)
    if where:
        q += " where " + " and ".join(where)
    q += " order by found_at desc, id desc limit ?"
    # Read WIDER than asked: the served list is filtered, and a page of results that the filter empties
    # read as "no news" while the store was full (measured 2026-11-04 — sixty menu entries from one source).
    args.append(max(1, min(1000, max(limit, 1) * 8)))
    with db() as c:
        rows = []
        for r in c.execute(q, args):
            if not is_headline(r["title"], r["url"]):
                continue
            r = dict(r)
            r["title"] = clean_title(r["title"])
            rows.append(r)
        if not category and not source:
            rows = order_front(rows)
        rows = rows[:max(1, min(500, limit))]
    for r in rows:
        r["category_he"] = CAT_NAME.get(r["category"], r["category"])
    return {"items": rows, "count": len(rows), "category": category, "source": source}


def review_queue(limit: int = 30, category: str = "") -> dict:
    """The newest collected articles that nobody has reviewed yet, each with the section its category suggests."""
    q = ("select a.url_key,a.url,a.title,a.source,a.category,a.found_at from articles a "
         "left join reviews r on r.url_key=a.url_key where r.url_key is null")
    args: list = []
    if category:
        q += " and a.category=?"
        args.append(category)
    q += " order by a.found_at desc, a.id desc limit ?"
    args.append(max(1, min(200, limit)))
    with db() as c:
        rows = [dict(r) for r in c.execute(q, args)]
        waiting = c.execute("select count(*) from articles a left join reviews r on r.url_key=a.url_key "
                            "where r.url_key is null").fetchone()[0]
    for r in rows:
        r["section_hint"] = SECTION_OF.get(r["category"], "global")
    return {"items": rows, "count": len(rows), "waiting": waiting, "sections": SECTIONS}


def review(body: dict) -> tuple[int, dict]:
    """One review, by URL. Refused (400) when it is not a review the site could publish as it is:
    an unknown section, no summary, a summary longer than SUMMARY_MAX_WORDS, an approval with no reviewer."""
    url, section = (body.get("url") or "").strip(), (body.get("section") or "").strip()
    status_, summary = (body.get("status") or "").strip(), (body.get("summary_he") or "").strip()
    reviewer = (body.get("reviewer") or "").strip()
    with db() as c:
        row = c.execute("select url_key from articles where url_key=? or url=?", (url_key(url), url)).fetchone()
    if not row:
        return 404, {"error": "no collected article has this url", "url": url}
    if status_ not in ("approved", "rejected"):
        return 400, {"error": "status must be approved or rejected"}
    if status_ == "approved":
        if section not in SECTIONS:
            return 400, {"error": f"section must be one of {SECTIONS}", "section": section}
        if not summary or len(summary.split()) > SUMMARY_MAX_WORDS:
            return 400, {"error": f"an approved story needs a summary of 1–{SUMMARY_MAX_WORDS} words, in our own words"}
    if not reviewer:
        return 400, {"error": "who reviewed it? (reviewer)"}
    with db() as c:
        c.execute("""insert into reviews(url_key,section,lang,summary_he,why_he,status,reason,reviewer,reviewed_at,published_at)
                     values (?,?,?,?,?,?,?,?,?,?)
                     on conflict(url_key) do update set section=excluded.section, lang=excluded.lang,
                       summary_he=excluded.summary_he, why_he=excluded.why_he, status=excluded.status,
                       reason=excluded.reason, reviewer=excluded.reviewer, reviewed_at=excluded.reviewed_at,
                       published_at=excluded.published_at""",
                  (row["url_key"], section or "global", (body.get("lang") or "he")[:5], summary,
                   (body.get("why_he") or "").strip(), status_, (body.get("reason") or "").strip()[:300],
                   reviewer[:80], now(), (body.get("published_at") or "")[:10]))
        c.commit()
    return 200, {"ok": True, "url_key": row["url_key"], "status": status_, "section": section}


def site(section: str = "", limit: int = 200) -> dict:
    """The site's feed: approved stories only, newest first — the one thing that leaves the office."""
    q = ("select a.url,a.title,a.source,a.found_at,r.section,r.lang,r.summary_he,r.why_he,r.reviewer,r.reviewed_at,"
         "r.published_at from reviews r join articles a on a.url_key=r.url_key where r.status='approved'")
    args: list = []
    if section:
        q += " and r.section=?"
        args.append(section)
    q += " order by coalesce(nullif(r.published_at,''), a.found_at) desc limit ?"
    args.append(max(1, min(1000, limit)))
    with db() as c:
        rows = [dict(r) for r in c.execute(q, args)]
        counts = dict(c.execute("select section, count(*) from reviews where status='approved' group by section").fetchall())
    return {"items": rows, "count": len(rows), "per_section": {s_: counts.get(s_, 0) for s_ in SECTIONS}}


def competitors(only: str = "", limit: int = 10) -> dict:
    """Per competitor on the watchlist: how many articles named it, and the latest ones."""
    out = []
    with db() as c:
        for w in WATCHLIST:
            if only and w["id"] != only:
                continue
            n = c.execute("select count(*) from mentions where competitor=?", (w["id"],)).fetchone()[0]
            latest = [dict(r) for r in c.execute(
                """select a.title,a.url,a.source,m.found_at from mentions m join articles a on a.url_key=m.url_key
                   where m.competitor=? order by m.found_at desc limit ?""", (w["id"], max(1, min(100, limit))))]
            out.append({"id": w["id"], "names": w.get("names") or [], "mentions": n, "latest": latest})
    return {"competitors": out, "count": len(out)}


def status() -> dict:
    with db() as c:
        last = c.execute("select * from runs order by id desc limit 1").fetchone()
        total = c.execute("select count(*) from articles").fetchone()[0]
    # `sources` is the COUNT and `source_ids` the list it counts: a source is declared in this file, so a
    # question like «is the source I just added really in the pass?» is answered by reading the answer, not by
    # guessing from a number (DGO-1712: 108 new sources, and the item's own acceptance is that they are listed).
    out = {"version": VERSION, "articles": total, "sources": len(SOURCES), "categories": len(CATEGORIES),
           "source_ids": [s[0] for s in SOURCES],
           "last_run": dict(last) if last else None}
    if last:
        out["last_run"]["report"] = json.loads(out["last_run"].get("report") or "{}")
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "newsflow/" + VERSION

    def log_message(self, fmt, *a):                       # one line, no address noise
        print("[newsflow] " + (fmt % a), flush=True)

    def _send(self, code: int, payload, ctype="application/json; charset=utf-8"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(u.query)
        try:
            if u.path in ("/healthz", "/health"):
                st = status()
                return self._send(200, {"ok": True, "articles": st["articles"], "sources": st["sources"]})
            if u.path == "/manifest":
                return self._send(200, {
                    "id": FLOW_APP, "version": VERSION, "interface": "newsflow.v1",
                    "ops": ["list", "categories", "collect", "status", "review-queue", "review", "site", "competitors"],
                    "endpoint": f"http://newsflow:{PORT}",
                    "flow": "dgo:flow:" + FLOW_APP,
                    "capabilities": [{"name": "news-feed", "type": "service", "interface": "newsflow.v1"}],
                    "state": {"articles": status()["articles"]}})
            if u.path == "/api/categories":
                with db() as c:
                    counts = dict(c.execute("select category, count(*) from articles group by category").fetchall())
                    opp = c.execute("select count(*) from articles where " + " or ".join(
                        "title like ?" for _ in OPPORTUNITY_CUES),
                        ["%" + cue + "%" for cue in OPPORTUNITY_CUES]).fetchone()[0]
                return self._send(200, {"categories": [{"id": i, "he": h,
                                                        "articles": opp if i == "opportunities" else counts.get(i, 0)}
                                                       for i, h in CATEGORIES]})
            if u.path == "/api/news":
                return self._send(200, news((q.get("category") or [""])[0],
                                            int((q.get("limit") or ["60"])[0] or 60),
                                            (q.get("source") or [""])[0]))
            if u.path == "/api/status":
                return self._send(200, status())
            if u.path == "/api/review/queue":
                return self._send(200, review_queue(int((q.get("limit") or ["30"])[0] or 30), (q.get("category") or [""])[0]))
            if u.path == "/api/site":
                return self._send(200, site((q.get("section") or [""])[0], int((q.get("limit") or ["200"])[0] or 200)))
            if u.path == "/api/competitors":
                return self._send(200, competitors((q.get("id") or [""])[0], int((q.get("limit") or ["10"])[0] or 10)))
            if u.path in ("/", "/index.html"):
                with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "index.html"), "rb") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")
            return self._send(404, {"error": "no such path", "path": u.path})
        except Exception as e:
            return self._send(500, {"error": str(e)[:300]})

    def do_POST(self):
        u = urllib.parse.urlsplit(self.path)
        n = int(self.headers.get("content-length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        except ValueError:
            body = {}
        try:
            if u.path == "/api/collect":
                cats = [c for c in (body.get("categories") or []) if c in CAT_NAME]
                return self._send(200, collect(cats))
            if u.path == "/api/review":
                code, out = review(body)
                return self._send(code, out)
            return self._send(404, {"error": "no such path", "path": u.path})
        except Exception as e:
            return self._send(500, {"error": str(e)[:300]})


def schedule() -> None:
    """Routine collection: one pass every NEWSFLOW_EVERY_MIN minutes (0 = only when asked).

    The owner's word was «בשגרה» — a feed that fills only when somebody presses a button is not a routine.
    A pass that dies is logged and the clock keeps going; nothing here can stop the service.
    """
    every = int(os.environ.get("NEWSFLOW_EVERY_MIN", "0") or 0)
    if every <= 0:
        print("[newsflow] no schedule (NEWSFLOW_EVERY_MIN=0) — collection is on demand", flush=True)
        return
    # …and NOT on every restart: a rebuild restarted this service four times in one hour and each boot ran a
    # pass (measured 2026-11-04 — passes 20, 22, 24 back to back, the shared browser busy the whole time). The
    # clock resumes where the last pass left it.
    last = (status().get("last_run") or {}).get("ended_at") or ""
    if last:
        try:
            done = time.mktime(time.strptime(last, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
            wait = every * 60 - (time.time() - done)
            if wait > 0:
                print(f"[newsflow] next scheduled pass in {int(wait / 60)} min", flush=True)
                time.sleep(wait)
        except ValueError:
            pass
    time.sleep(45)                      # let the edge and the office browser settle after a restart
    while True:
        try:
            out = collect(None)
            print(f"[newsflow] scheduled pass {out['run']}: +{out['added']} · "
                  f"{out['sources_ok']}/{out['sources_tried']} sources · flow {out['flow']}", flush=True)
        except Exception as e:           # a failed pass must not end the clock
            print(f"[newsflow] scheduled pass failed: {e}", flush=True)
        time.sleep(max(600, every * 60))


def main() -> None:
    init()
    threading.Thread(target=schedule, daemon=True).start()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[newsflow] {VERSION} on :{PORT} — {len(SOURCES)} sources, {len(CATEGORIES)} categories, "
          f"browser={BROWSER}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
