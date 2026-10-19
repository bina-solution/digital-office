# cost-meter — the price of a conversation, where its token count used to be

The harness's composer footer counts **tokens** ("1.9 מיליון"). Tokens are the vendor's unit, not the
owner's. This plugin replaces that figure with **the money it bought**, in the currency the office
sets in Settings.

Owner's request, 2026-10-12: *"במקום 1.9 מיליון טוקנים אני רוצה את העלות בשקל או מה שמוגדר בהגדרות
… תוודה שזה מאוד יעיל נקי וספק הוכחות"*.

## What it is made of

| file | what it owns |
|---|---|
| `lib/pricing.js` | the price book (DeepSeek's published rates), the peak-window rule, the usage-sample reader, money and token formatting. Pure — no imports, no state. |
| `lib/cost.js` | the fold over durable events and the published value. Pure — the tests and the display mock import THIS, so a screenshot and the footer cannot disagree. |
| `lib/index.js` | the host wiring: the `costMeter` session projection and the `cost-meter` settings namespace. |
| `lib/client.js` | the composer pill, its breakdown panel, the settings card, and the one CSS rule that hides the token pill. |
| `test/pricing.test.mjs` | 13 tests over hand-built durable events (`node --test test/pricing.test.mjs`). |

Mounted by two declarations in `apps/bina-ds/harness/profile/`: a `file:` dependency in
`package.json`, and one row in `cordis.patch.yml` whose `config` is the **composition layer** of the
settings section. Nothing else in the office had to change, and nothing outside `apps/bina-ds/` did.

## The numbers, and where they come from

DeepSeek's published price list (<https://api-docs.deepseek.com/quick_start/pricing>, read 2026-10-12),
USD per 1M tokens, **peak** rate:

| row | cache hit | cache miss (input) | output |
|---|---|---|---|
| Flash (`deepseek-flash`, and the retired `deepseek-v4-flash*`) | $0.006 | $0.30 | $1.20 |
| Pro (`deepseek-v4-pro`) | $0.044 | $1.32 | $3.96 |

Three facts drive the whole implementation, and each of them is a factor the naive meter loses:

1. **Off-peak is half price.** Peak is 01:00–04:00 and 06:00–10:00 UTC, Monday–Friday; everything
   else is off-peak. So every sample is priced at the moment it was *reported*, and a session that
   crosses 10:00 UTC is priced in two parts. (Chinese public holidays are off-peak and are not
   modelled — on those days this meter is up to 2x high; the peak split is visible in the panel and
   the whole rule can be switched off in Settings.)
2. **Cache hits are 50x cheaper than misses.** An agent conversation is mostly cache reads: ignoring
   the bucket over-states a real session by roughly an order of magnitude.
3. **A cache write has no published price** — it bills as prompt input, so it is priced as a miss.

An id with no published price is priced at the Flash row **and named as unpriced** in the value the
browser shows; an unknown model never silently becomes a confident number.

## The fold, and why it mirrors `tokenUsage`

The harness bills one usage sample per request, and writes it twice: an `assistant/attempt` carries
it inside the stream, the settlement (`assistant/message`) carries it as `data.usage` with the route.
The harness's own `tokenUsage` unit **replaces** the earlier sample of the same step, and an
`llm/retry-started` closes the slot so a retried attempt adds on top.

This plugin reproduces that rule exactly (`lib/cost.js`), so the price is the price of
**the tokens the pill used to show** — not of a different set of samples. The one thing it adds is
that the replacement is undone **in the window and price row it was added to**: a step that straddles
a peak boundary must not move tokens between windows.

Money is *not* folded. The state keeps tokens per (price row, peak|off-peak); the currency and the
rate are read when the value is published. A changed rate therefore re-prices every session, and
changing it never requires replaying a log.

## What the office sees

* **The pill**: `₪4.21` where `1.9 מיליון` was, in the harness's own row (portalled into
  `[data-composer-stats]`), with the harness's own icon size, hover and theme. Hover shows both
  figures; the accessible name is the price.
* **The panel** (click): the total, then the four buckets — cached input, uncached input, cache
  write, output — each with its tokens and its money, then the rate, the cache-hit share, the
  peak/off-peak split, the models used, and a warning when a model had no published price.
* **Settings → תוספים → מדד עלות**: the currency, the exchange rate, and whether peak hours are
  billed. Saved per office on the volume, applied live (`settings.register(..., {applies: 'live'})`).
* **No host, no pill**: if the projection is absent the plugin renders nothing and the token pill
  stays exactly as it was. The hiding rule is scoped to `html[data-bina-cost="ready"]`, so a failure
  can never leave an empty space where a number used to be.

## Traps

* **The token pill is matched by the icon the harness draws in it** (the database cylinder — an
  `ellipse`; the turns pill's gauge has none), not by position. A positional rule would hide whatever
  the harness renders last after a rebuild, which is the wrong pill on the worst day. This couples
  the plugin to one icon inside a harness version that `package.json` pins; the failure mode is both
  pills showing.
* **The pill is portalled into a React-managed row** (`plugins/voice` does the same for the
  microphone). The holder is appended LAST so it never becomes the `nextSibling` React inserts its
  own children against.
* **`stateVersion` is a contract with the persisted projection cache.** Changing the fold's semantics
  or its state shape means bumping it, or old rows are forward-applied into garbage.
* **The projection is per session and from the log**, so a session that ran before this plugin
  existed is priced the moment it is opened — and a forked session inherits its parent's prefix (the
  registry folds the inherited events too, which is why the child's figure includes what it inherited).
* **Prices change.** They are in `lib/pricing.js`, dated and cited; a DeepSeek price change is a
  one-line edit and an image rebuild, not a settings write.
