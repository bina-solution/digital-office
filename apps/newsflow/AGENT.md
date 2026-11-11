# Operating «זרימת חדשות» (the `newsflow` app, DGO-1348)

The office's news, collected through the office's own browser and sorted into the owner's categories —
technology, AI, new models, benchmarks, open-source tools, cloud, business, marketing, Israel, blue-and-white
startups, initiatives, Israeli bureaucracy, law, venture funds. The source of this app is the owner's own
prototype (github.com/solomonBoltin/NewsFlow); what changed is the shape: no second scraper, no Telegram
channel — the office's browser reads, the office's stream carries, four channels serve.

## From the server's shell

```bash
./bbox newsflow collect [category …]   # one collection pass; prints what was added and every source that failed
./bbox newsflow list [category] [N]    # the newest items (default 60)
./bbox newsflow categories             # the taxonomy with a count per category
./bbox newsflow status                 # last run: when, what it added, which sources answered
```

## From inside the office network (`http://newsflow:8991`)

```bash
curl -s http://newsflow:8991/manifest                  # the live contract (newsflow.v1)
curl -s 'http://newsflow:8991/api/news?category=ai&limit=30'
curl -s http://newsflow:8991/api/categories
curl -s http://newsflow:8991/api/status
curl -s -X POST http://newsflow:8991/api/collect -H 'content-type: application/json' -d '{"categories":["ai","cloud"]}'
```

The stream is `dgo:flow:newsflow` (flow.v1): one `article.new` per article that was not there before, with
`data: {url, title, source, category, category_he}`.

## Rules

- **A collection pass is real browser work.** It drives browser42 (a task per source, closed after the read),
  so it costs the shared browser a few minutes and must not be run in a loop; one pass at a time (the app
  takes a lock).
- **A source that does not answer is a row in the run, never a silent empty category.** Read `report` in
  `./bbox newsflow status` (or the pass's answer) and fix the source, not the category.
- Nothing here deletes: an article that is gone from the web stays in the store as history.

## Traps

- browser42 is REQUIRED. With it down every source answers `failed: …` and the pass adds nothing — that is
  reported, not hidden. `curl -s http://newsflow:8991/healthz` stays green: it reports the store, not the
  browser.
- A site that blocks even the office browser (a paywall, a bot wall) will read no links: the report says
  «no links read (the page may need the owner's eyes)».
- The source list and the category ids live in `main.py` (`SOURCES`, `CATEGORIES`) — add a source there, in
  one place, and it is picked up by the next pass.
