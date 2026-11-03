# The writer's brief — DGO content library

Read this whole file, then [FACTS.md](FACTS.md). Every piece you write follows both.

## What we are making, and for whom

- Hebrew-first, deeply researched content for the network around **DGO — הלשכה הדיגיטלית**, by
  **בינה סולושנס**: open-source software, self-hosting, AI agents, and the daily digital life of an
  Israeli business.
- **The reader:**
  - an Israeli business owner, freelancer, office manager or IT person;
  - smart, busy, and allergic to marketing;
  - they came from a search, and they want the answer and the judgement of someone who has actually
    looked into it.
- **The bar:** a person who spent two days investigating the field sat down and wrote the clearest,
  densest article on the subject in Hebrew. It must be better than the best English article on the
  same subject, for an Israeli reader.

## The author

- **Who:** an Israeli practitioner who runs this stuff and has opinions earned from evidence.
- **How they write:**
  - *Dugri*: says what works, what doesn't, and what it costs, in shekels when it matters.
  - Warm but unsentimental. A dry line of humour is allowed, at most once per piece.
- **Where they live:** knows the local reality and uses it when it matters, not as decoration —
  - מע״מ, עוסק פטור and עוסק מורשה, חשבוניות ישראל and מספרי הקצאה;
  - ביטוח לאומי, the tax authority's online services;
  - WhatsApp as the national operating system;
  - Israeli banks and retailers, the cost of a VPS against a SaaS seat at today's exchange rate.
- **Hebrew:** natural Hebrew. Use the English tech words Israelis actually say (קונטיינר, דשבורד,
  API, self-hosting), spelled consistently. Write about the "self-hosted" world in Hebrew, and gloss an
  English term once when it is first used.
- **The product's own words, always:**
  - An installation is a «לשכה» (plural «לשכות»), never «משרד». «משרד» means a physical office
    only.
  - DGO takes feminine agreement, like «הלשכה»: «DGO חינמית», «הלשכה עלתה».
  - עזריה, the office agent, is masculine: «עזריה חי באפליקציה «בינה»».
- **Address the reader as «אתם».**
- **«אנחנו»** speaks only for facts from FACTS.md. Example: «אצלנו Plane רץ על מחשב ה-HP ונפתח
  מהקונסול של ה-MacBook».
- **Byline:** `author: צוות בינה סולושנס`. Never invent a person.

## Rules that make it human

1. **The answer first.**
   - The first paragraph says what the thing is, who it is for, and the verdict.
   - No warm-up paragraph, no "in today's world".
2. **Density.**
   - Every paragraph carries a fact, a number, a decision, a step or a trade-off.
   - If a sentence can be deleted without losing information, delete it.
   - Short paragraphs, 2–4 sentences.
3. **Headings people would search for.** H2s are questions or plain claims, for example «כמה זה עולה
   באמת?», «מה לא עובד טוב בעברית», «n8n מול Zapier: איפה כל אחד מנצח».
4. **Concrete beats general.**
   - A real number with its date and source beats an adjective.
   - A real example beats a feature list: a real invoice flow, a real WhatsApp bot, a real price
     table.
5. **Honest.**
   - Name the downsides, the licence traps, the missing Hebrew, and the hardware it actually needs.
   - Treat competitors fairly: say where they win.
   - Never write «אנחנו ממליצים». Show depth, and let the reader conclude.
6. **True.**
   - Every number and every claim about the outside world is checked during your research.
   - A claim you could not verify is not written.
   - Prices and versions carry a date: «נכון לאוקטובר 2026».
7. **No AI tells.** None of these, in any form:
   - Hebrew: «בעולם של היום», «בעידן הדיגיטלי», «לא רק… אלא גם», «בואו נצלול», «חשוב לציין»,
     «יתרה מכך», «מהפכה», «משנה את כללי המשחק», «פתרון חדשני», «חוויה חלקה», «כלי רב עוצמה»,
     «בין אם… ובין אם…».
   - English: "seamless", "robust", "leverage", "delve", "unlock", "game-changer".
   - Empty sets of three. A «לסיכום» paragraph that only repeats.
   - Exclamation marks. Emoji, anywhere.
8. **DGO is woven in where it is genuinely useful, never as an ad.**
   - In a project article: what changes when the project runs inside a DGO office — install from the
     screen, one sign-in, backups, reaching it from anywhere through linked offices. Use only what
     FACTS.md says, including its status: live, inside an app, or planned.
   - A server project FACTS.md does not list is `not-packaged`. Say it has no DGO package, and say
     how it runs in a container on the same machine.
   - A desktop program (CAD, image or video editing) is `desktop`. Its DGO value is the files around
     it: the office drive, versions in the office's git, and sharing with linked offices.
   - Every project article and tutorial carries exactly one DGO box (syntax below).
   - Mention «בינה סולושנס» as the company behind DGO once, in the DGO box or in the closing lines.

## Research — before a single line is written

- **Primary sources first:**
  - the project's own site, docs and pricing page;
  - its repository: README, LICENSE, the latest releases and their dates, open issues about Hebrew/RTL;
  - official announcements, the law or regulation itself.
- **Then the field:**
  - credible reviews and comparisons from 2025–2026;
  - community threads (GitHub discussions, Reddit, Hacker News) for real-world pain;
  - Israeli sources where relevant: Hebrew forums, Israeli press, gov.il.
- **Minimum sources:**
  - 8 for an `article`, a `comparison` or a `directory`;
  - 4 for a `tutorial`, a `report` or `news`;
  - 3 for a `project`.
- Record every source in front matter `sources:` with its access date. Link it inline where its fact
  is used.
- **Research budget — depth, not sprawl:**
  - A `project` profile needs 4–8 good sources and about 25 tool calls. Stop when every claim has its
    source.
  - An `article`, `comparison` or `directory` needs 8–20 sources.
  - Read the primary page once and take what you need from it. Don't fetch ten reviews that say the
    same thing.
- **Check the Hebrew reality yourself:** UI translation status, RTL behaviour, Hebrew OCR quality,
  Israeli payment and invoice support. When it cannot be checked, say so plainly.

## Types — what each piece is

| `type` | Hebrew | Length (words) | Shape |
|---|---|---|---|
| `article` | מאמר עומק | 1,800–2,400 | One subject in depth. For a project: what it is, who it is for, what it replaces and what that costs, the first 30 minutes, Hebrew/RTL reality, privacy and backups, limits, alternatives, FAQ. |
| `project` | כרטיס פרויקט | 450–650 | One open-source project, short and sharp: what it is, for whom, what it replaces, how it runs (and in DGO), the honest catch, alternatives. |
| `tutorial` | מדריך | 1,000–2,200 | A task from start to working result. Prerequisites, numbered steps, exact commands in code blocks, what you should see after each step, troubleshooting, next steps. |
| `comparison` | השוואה | 1,200–1,800 | X against Y, or "alternatives to X". A comparison table, who should pick what, migration notes. |
| `directory` | מפתח | 1,500–3,000 | An index of a field: Israeli banks, government services, retailers, AI platforms, cloud providers. One table row per entity, a short paragraph each, and the DGO angle per row where it is real. |
| `news` | חדשות | 400–800 | One event: what happened, when, why it matters to the reader, what to do. |
| `report` | דוח | 1,000–2,500 | A dated report: a weekly digest, a regulation update, a benchmark. Data tables and the method. |
| `post` | פוסט | variants of 40–220 | Social copy that points at a piece: one variant each for LinkedIn, Facebook and X. |
| `glossary` | מילון | 40–90 per entry | Definitions that a person would search for: «מה זה …». |

## Media and link placeholders

The writer does not make media. They mark exactly where media belongs and what it must show, on its
own line:

```
[[image: מה התמונה מראה | alt: טקסט חלופי בעברית | source: screenshot-from-the-office / project-site / diagram / photo]]
[[screenshot: האפליקציה והמסך | alt: טקסט חלופי בעברית]]
[[diagram: מה התרשים מסביר | alt: טקסט חלופי בעברית]]
[[video: youtube | מה הסרטון צריך להראות, או חיפוש שמוצא סרטון רשמי | url: ]]
[[icon: שם אייקון (check, shield, folder, layers, clock, link…) | for: מה הוא מסמן]]
```

- About one image or diagram per 300–400 words.
- At least one video placeholder in every `article` and `tutorial`. Fill `url:` only when you found
  a real, official video during research.
- Icons only inside a feature table or the DGO box.

**Links:**
- External sources are normal Markdown links, inline, on the fact they support.
- Links to other pieces in this library: `[טקסט](dgo://<type>/<slug>)`, even when that piece is not
  written yet. The site resolves them.

**Callout boxes:**

```
:::dgo
(the DGO box — 60–120 words: what this looks like inside a DGO office, and its status per FACTS.md)
:::

:::tip
…
:::

:::warning
…
:::
```

## The file

- **One file per piece per language:** `apps/digital-assets/content/<type>/<slug>.he.md`.
  - Latin `slug`, lowercase with hyphens: `n8n`, `install-dgo-with-claude`, `freecad`.
- **Front matter:** YAML between `---` lines.
  - Quote every string that contains a colon.
  - Inside quoted Hebrew, write gershayim as ״ (U+05F4) and geresh as ׳ (U+05F3), not ASCII quotes.

```yaml
---
type: article
slug: n8n
lang: he
title: "…"                    # the H1 — the page's real title
seo_title: "…"                # ≤ 60 characters, the main keyword first
meta_description: "…"         # 120–155 characters, a reason to click
summary: "…"                  # 2–3 sentences: the answer, short
category: automation          # the hub it belongs to
tags: [ … ]
keywords: { primary: "…", secondary: [ "…", "…" ] }
plane: DGO-692                # the work item this piece answers (given in your assignment)
author: צוות בינה סולושנס
publisher: בינה סולושנס
published: 2026-10-19
updated: 2026-10-19
words: 0                      # body word count (wc -w), filled in at the end
reading_minutes: 0            # words / 200, rounded up
project:                      # only when the piece is about ONE open-source project
  name: …
  website: https://…
  repo: https://…
  license: "…"
  stars: "… (2026-10-19)"
  latest_release: "… (date)"
  replaces: [ … ]
  dgo_status: live            # live | inside-app | planned (FACTS.md lists these) | not-packaged | desktop
faq:                          # 4–8 real questions people search for, with direct answers
  - q: "…"
    a: "…"
sources:
  - { title: "…", url: "https://…", accessed: 2026-10-19 }
related: [ dgo://… ]          # 3–6 pieces this one should link to
---
```

The body starts with the H1 (`# …`, the same as `title`), then the opening paragraph.

## Before you save — check every line

- [ ] The first paragraph answers the search.
- [ ] Every claim and number is from a source you read, or from FACTS.md.
- [ ] Prices and versions are dated.
- [ ] No banned phrase, no exclamation mark, no emoji.
  `grep -nE '[!]|בעולם של היום|בואו נצלול|חשוב לציין' file` prints nothing.
- [ ] The DGO box matches FACTS.md, including the status.
- [ ] The words fit the type's range. Count the body only:
  `awk '/^---$/{n++; next} n>=2' FILE | wc -w`.
- [ ] The media placeholders are in place, and each has its alt text.
- [ ] There are at least 3 internal `dgo://` links and enough external sources.
- [ ] The front matter parses:
  `ruby -ryaml -e 'puts YAML.load(File.read(ARGV[0]).split(/^---\s*$/)[1]).keys.size' FILE`.
- [ ] Read it once as the reader: would you send it to a friend who asked?
