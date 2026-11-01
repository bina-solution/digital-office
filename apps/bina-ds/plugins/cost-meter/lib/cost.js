/**
 * cost-meter/cost — the fold and the published value, as pure functions over durable events.
 *
 * Kept apart from lib/index.js on purpose: index.js needs the harness's own packages (zod for the
 * projection schemas, schemastery for the settings section) and therefore cannot be imported
 * outside the harness process, while THIS file must be — the tests and the display mock import it
 * so the number in a screenshot and the number in the footer are computed by one implementation.
 *
 * See lib/index.js for why the fold mirrors the harness's own `tokenUsage` unit.
 */
import { BUCKETS, FALLBACK_MODEL, PRICES, isPeak, money, priceRow, routeOf, usageOf } from './pricing.js'

/** Empty bucket set. */
export const zero = () => ({ cacheHit: 0, cacheMiss: 0, cacheWrite: 0, output: 0 })

/** The state of a session that has billed nothing yet. */
export const initial = () => ({ windows: {}, models: [], unpriced: [], last: null })

/** Total tokens of one bucket set. */
export const sumOf = (buckets) => buckets.cacheHit + buckets.cacheMiss + buckets.cacheWrite + buckets.output

/**
 * The buckets of one provider sample. Cache traffic is kept apart because it is priced 50x
 * differently; a bucket the provider did not send is a zero, never a hole.
 * @param usage - provider usage object.
 * @returns the four non-negative counts.
 */
export function bucketsOf(usage) {
  const count = (value) => (typeof value === 'number' && Number.isFinite(value) && value > 0 ? Math.round(value) : 0)
  return {
    cacheHit: count(usage.cacheReadTokens),
    cacheMiss: count(usage.inputTokens),
    cacheWrite: count(usage.cacheWriteTokens),
    output: count(usage.outputTokens),
  }
}

/** `buckets` with `minus` subtracted and `plus` added, per bucket. */
function replace(buckets, minus, plus) {
  return {
    cacheHit: buckets.cacheHit - minus.cacheHit + plus.cacheHit,
    cacheMiss: buckets.cacheMiss - minus.cacheMiss + plus.cacheMiss,
    cacheWrite: buckets.cacheWrite - minus.cacheWrite + plus.cacheWrite,
    output: buckets.output - minus.output + plus.output,
  }
}

/**
 * The fold. Every branch that is not this unit's own returns the SAME state reference — an unchanged
 * reference is what tells the projection registry there is nothing to publish.
 * @param state - state covering every prior event.
 * @param event - the next committed session event.
 * @returns the next state.
 */
export function fold(state, event) {
  if (event.type === 'llm/retry-started') {
    return state.last !== null && state.last.turn === event.data.turn && state.last.step === event.data.step
      ? { ...state, last: null }
      : state
  }
  if (event.type !== 'assistant/message' && event.type !== 'assistant/attempt') return state
  const usage = usageOf(event)
  if (usage === undefined) return state
  const { turn, step } = event.data
  const buckets = bucketsOf(usage)
  const previous = state.last !== null && state.last.turn === turn && state.last.step === step ? state.last : undefined
  // An attempt is logged before the settlement that names its route, so a session's first attempt is
  // priced at the last model it ran — or at the office's default for the very first one.
  const model = routeOf(event)?.model ?? state.models[state.models.length - 1] ?? FALLBACK_MODEL
  const { key: rowKey, known } = priceRow(model)
  const key = `${rowKey}|${isPeak(event.time) ? 'peak' : 'off'}`
  if (previous !== undefined && previous.key === key && BUCKETS.every((bucket) => previous.buckets[bucket] === buckets[bucket])) {
    return state
  }
  const windows = { ...state.windows }
  // Undo the sample this one supersedes in ITS OWN window and row, then add this one: a step that
  // crosses a peak boundary must not move tokens between windows.
  if (previous !== undefined) windows[previous.key] = replace(windows[previous.key] ?? zero(), previous.buckets, zero())
  windows[key] = replace(windows[key] ?? zero(), zero(), buckets)
  return {
    windows,
    models: state.models.includes(model) ? state.models : [...state.models, model],
    unpriced: known || state.unpriced.includes(model) ? state.unpriced : [...state.unpriced, model],
    last: { turn, step, key, buckets },
  }
}

/** USD of one window entry at the settings in force when it is read. */
function usdOf(rowKey, window, buckets, peakPricing) {
  const row = PRICES[rowKey] ?? PRICES[FALLBACK_MODEL]
  const factor = peakPricing && window === 'off' ? 0.5 : 1
  const prompt = buckets.cacheMiss + buckets.cacheWrite
  return ((buckets.cacheHit * row.cacheHit + prompt * row.cacheMiss + buckets.output * row.output) / 1e6) * factor
}

/** USD of one bucket inside one window entry, for the panel's per-row figures. */
function usdBucket(rowKey, window, bucket, count, peakPricing) {
  if (count === 0) return 0
  const row = PRICES[rowKey] ?? PRICES[FALLBACK_MODEL]
  const price = bucket === 'output' ? row.output : bucket === 'cacheHit' ? row.cacheHit : row.cacheMiss
  return (count * price) / 1e6 * (peakPricing && window === 'off' ? 0.5 : 1)
}

/**
 * Publish the value the browser reads: money in the configured currency, plus the breakdown that
 * lets the owner check it. Money is derived HERE rather than folded, so a changed rate or currency
 * re-prices every session on its next published value instead of being frozen into its state.
 * @param state - folded token state.
 * @param settings - resolved `cost-meter` settings.
 * @returns the client-visible payload.
 */
export function view(state, settings) {
  const peakPricing = settings?.peakPricing !== false
  const entries = Object.entries(state.windows).map(([key, buckets]) => {
    const [rowKey, window] = key.split('|')
    return { rowKey, window, buckets, usd: usdOf(rowKey, window, buckets, peakPricing) }
  })
  const usd = entries.reduce((total, entry) => total + entry.usd, 0)
  const buckets = zero()
  for (const entry of entries) for (const bucket of BUCKETS) buckets[bucket] += entry.buckets[bucket]
  const shown = money(usd, settings)
  const rows = BUCKETS.map((bucket) => {
    const bucketUsd = entries.reduce(
      (total, entry) => total + usdBucket(entry.rowKey, entry.window, bucket, entry.buckets[bucket], peakPricing),
      0,
    )
    return { bucket, tokens: buckets[bucket], usd: bucketUsd, amount: bucketUsd * shown.rate }
  })
  const peak = { tokens: 0, usd: 0 }
  const offPeak = { tokens: 0, usd: 0 }
  for (const entry of entries) {
    const side = entry.window === 'peak' ? peak : offPeak
    side.tokens += sumOf(entry.buckets)
    side.usd += entry.usd
  }
  return {
    usd,
    amount: shown.amount,
    currency: shown.currency,
    rate: shown.rate,
    text: shown.text,
    totalTokens: sumOf(buckets),
    buckets,
    rows,
    models: state.models,
    unpriced: state.unpriced,
    peak,
    offPeak,
    peakPricing,
  }
}
