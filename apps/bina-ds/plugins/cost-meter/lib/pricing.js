/**
 * cost-meter/pricing — the whole arithmetic of "what did this conversation cost", as pure
 * functions with no imports and no state.
 *
 * WHY A SEPARATE MODULE. Three callers price the same tokens and must never disagree: the Host
 * half (the session projection the composer pill reads), the unit tests, and the display mock
 * (digital-office/sim/cost-pill-mock). The mock is where a proposal is measured; if it carried its
 * own copy of the formula, its numbers would prove nothing.
 *
 * THE PRICES ARE DEEPSEEK'S, PUBLISHED, AND CITED. Source: https://api-docs.deepseek.com/quick_start/pricing
 * (read 2026-10-12). The table below is the PEAK rate in USD per 1M tokens; DeepSeek's off-peak
 * rate is exactly half of it, so one number per row is the whole table. Peak hours are 01:00-04:00
 * and 06:00-10:00 UTC, Monday to Friday; everything else (weekends, and Chinese public holidays,
 * which are NOT modelled here) is off-peak. A session that crosses 10:00 UTC is therefore priced
 * in two parts, per request, by that request's own timestamp.
 *
 * Two consequences worth saying out loud, because they are the difference between a number the
 * owner can trust and one he cannot:
 *   * PEAK/OFF-PEAK DOUBLES THE ANSWER. Pricing everything at peak over-states an evening session
 *     by 2x; pricing everything off-peak under-states a morning one by 2x. Neither is acceptable,
 *     and both are what a "one price per model" meter silently does.
 *   * CACHE HITS ARE 50x CHEAPER THAN MISSES on Flash (0.006 against 0.30 per 1M). An agent
 *     conversation is mostly cache reads, so a meter that ignores the bucket would over-state a
 *     real session by an order of magnitude.
 *
 * Cache WRITES have no published price of their own; DeepSeek bills prompt input, and a write is
 * input, so a cache-write token is priced at the cache-miss rate.
 */

/** Price book: USD per 1M tokens at DeepSeek's PEAK rate. */
export const PRICES = {
  flash: { cacheHit: 0.006, cacheMiss: 0.3, output: 1.2 },
  pro: { cacheHit: 0.044, cacheMiss: 1.32, output: 3.96 },
}

/**
 * Model id → price row. DeepSeek retired the `deepseek-v4-flash*` names and serves them with the
 * V4.1-Flash model at the Flash price (said in the pricing page's own footnote), so an older
 * session — written before the rename — is priced by what it actually ran as, not as unknown.
 */
const MODEL_ALIASES = {
  'deepseek-flash': 'flash',
  'deepseek-v4-flash': 'flash',
  'deepseek-v4-flash-vision-exp': 'flash',
  'deepseek-v4-pro': 'pro',
  'deepseek-v4-pro-0813': 'pro',
}

/** The row an unpriced/unknown model is priced at, and why: the office's default model. */
export const FALLBACK_MODEL = 'flash'

/** Settings defaults — also the composition `base` of the row that mounts this plugin. */
export const DEFAULTS = {
  /** Currency the cost is shown in. Any symbol/word; `ספרה` only ever appears next to it. */
  currency: '₪',
  /** Units of that currency per 1 USD. Edited in Settings; the prices are DeepSeek's USD book. */
  usdRate: 3.7,
  /** Whether peak/off-peak hours are applied. Off = everything at the peak (highest) rate. */
  peakPricing: true,
}

/** Peak windows in UTC hours, half-open [from, to). DeepSeek: 01:00-04:00 and 06:00-10:00. */
const PEAK_HOURS_UTC = [[1, 4], [6, 10]]

/**
 * Whether one request's timestamp falls in a peak window.
 * @param timeMs - the request's own time, epoch milliseconds.
 * @returns true at peak (the full rate), false off-peak (half).
 */
export function isPeak(timeMs) {
  const at = new Date(timeMs)
  const day = at.getUTCDay()
  if (day === 0 || day === 6) return false // weekends are off-peak in full
  const hour = at.getUTCHours() + at.getUTCMinutes() / 60
  return PEAK_HOURS_UTC.some(([from, to]) => hour >= from && hour < to)
}

/**
 * Resolve a model id to its price row and the row's own name.
 * @param modelId - provider model id as the session recorded it.
 * @returns the row key and whether the id was recognised (a guess is reported, not hidden).
 */
export function priceRow(modelId) {
  const id = String(modelId ?? '').trim()
  const key = MODEL_ALIASES[id]
  return key === undefined ? { key: FALLBACK_MODEL, known: false } : { key, known: true }
}

/**
 * Price one usage sample.
 * @param usage - `{inputTokens, outputTokens, cacheReadTokens, cacheWriteTokens}` as the provider reported it.
 * @param options - `{modelId, timeMs, peakPricing}`.
 * @returns USD for this sample, at this model, at this timestamp.
 */
export function costOfSample(usage, options) {
  const { key } = priceRow(options.modelId)
  const row = PRICES[key]
  const factor = options.peakPricing === false || isPeak(options.timeMs) ? 1 : 0.5
  const cacheHit = num(usage.cacheReadTokens)
  const cacheMiss = num(usage.inputTokens) + num(usage.cacheWriteTokens)
  const output = num(usage.outputTokens)
  return ((cacheHit * row.cacheHit + cacheMiss * row.cacheMiss + output * row.output) / 1e6) * factor
}

/** A finite, non-negative token count; anything else is 0 rather than NaN in a total. */
function num(value) {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : 0
}

/** The four buckets this meter keeps, in the order the panel shows them. */
export const BUCKETS = ['cacheHit', 'cacheMiss', 'cacheWrite', 'output']

/**
 * The usage sample carried by one durable event, or undefined.
 *
 * Mirrors the token-meter's own reader (`@deepseek-ai/dsh-token-meter`): an Assistant settlement
 * reports its usage either as `data.usage` or as the last `usage` chunk embedded in its stream.
 * Inlined rather than imported because a profile plugin lives outside the harness's node_modules —
 * the same reason `command-next` resolves its helpers at mount time.
 * @param event - one committed session event.
 * @returns the provider's usage object, or undefined when this event reports none.
 */
export function usageOf(event) {
  const data = event?.data
  if (data === undefined) return undefined
  if (event.type === 'assistant/message' && data.usage !== undefined) return data.usage
  if (event.type !== 'assistant/message' && event.type !== 'assistant/attempt') return undefined
  const stream = data.stream
  if (!Array.isArray(stream)) return undefined
  for (let index = stream.length - 1; index >= 0; index -= 1) {
    const record = stream[index]
    if (record?.type === 'chunk' && record.chunk?.type === 'usage') return record.chunk.usage
  }
  return undefined
}

/**
 * The provider/model an Assistant settlement was served by, or undefined.
 * @param event - one committed session event.
 * @returns `{provider, model}` when the event names both, otherwise undefined.
 */
export function routeOf(event) {
  const source = event?.type === 'assistant/message' ? event.data?.message?.source : undefined
  const provider = String(source?.provider ?? '')
  const model = String(source?.model ?? '')
  return provider.length > 0 && model.length > 0 ? { provider, model } : undefined
}

/**
 * A USD amount in the office's currency, rounded for display.
 * @param usd - amount in USD.
 * @param settings - resolved settings (`currency`, `usdRate`).
 * @param decimals - display decimals; two by default because API bills are small.
 * @returns `{amount, currency, text}` where `text` is what a screen shows.
 */
export function money(usd, settings, decimals = 2) {
  const currency = typeof settings?.currency === 'string' && settings.currency.length > 0 ? settings.currency : DEFAULTS.currency
  const rate = Number.isFinite(settings?.usdRate) ? settings.usdRate : DEFAULTS.usdRate
  const amount = usd * rate
  const rounded = Math.round(amount * 10 ** decimals) / 10 ** decimals
  // Hebrew reads a currency symbol before the number ("₪4.21"); a word or code reads after it.
  const symbol = /^[^\p{L}\p{N}]+$/u.test(currency)
  return {
    amount: rounded,
    currency,
    rate,
    text: symbol ? `${currency}${rounded.toFixed(decimals)}` : `${rounded.toFixed(decimals)} ${currency}`,
  }
}

/**
 * A token count as the panel shows it: exact below 1000, compact above.
 * @param value - token count.
 * @returns display string.
 */
export function tokens(value) {
  const count = num(value)
  if (count < 1000) return String(count)
  if (count < 1e6) return `${Math.round(count / 100) / 10}K`
  return `${Math.round(count / 1e5) / 10}M`
}
