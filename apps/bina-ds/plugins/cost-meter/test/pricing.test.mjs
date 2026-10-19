/**
 * cost-meter tests — the arithmetic, and the fold, against hand-built durable events.
 *
 * The events here are the shapes the harness actually logs (see `@deepseek-ai/dsh-token-meter`'s
 * own `usageOf`/`deriveTurnTokenUsage`): an `assistant/attempt` carries a stream whose last `usage`
 * chunk is the provider's report; an `assistant/message` carries `data.usage` and the route it was
 * served by. They are fixtures, not a live session — the live proof is the deployment's own
 * projection, read back over the API after the image that carries this plugin is up.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'

import { costOfSample, isPeak, money, priceRow, tokens, usageOf } from '../lib/pricing.js'
import { fold, initial, view } from '../lib/cost.js'

const FLASH = 'deepseek-flash'
const PRO = 'deepseek-v4-pro'
/** 2026-10-12 is a Monday; 12:00 UTC is outside every peak window, 02:00 UTC is inside one. */
const OFF_PEAK = Date.UTC(2026, 9, 12, 12, 0, 0)
const PEAK = Date.UTC(2026, 9, 12, 2, 0, 0)

/** One durable attempt event, with its usage embedded in the stream, exactly as the harness writes it. */
const attempt = (turn, step, usage, time = OFF_PEAK) => ({
  type: 'assistant/attempt',
  time,
  data: { turn, step, stream: [{ type: 'chunk', chunk: { type: 'text-delta', text: 'x' } }, { type: 'chunk', chunk: { type: 'usage', usage } }] },
})

/** One durable Assistant settlement carrying usage and its route. */
const message = (turn, step, usage, model, time = OFF_PEAK) => ({
  type: 'assistant/message',
  time,
  data: { turn, step, usage, message: { source: { provider: 'deepseek', model } } },
})

const usage = (input, output, cacheRead = 0, cacheWrite = 0) => ({
  inputTokens: input,
  outputTokens: output,
  cacheReadTokens: cacheRead,
  cacheWriteTokens: cacheWrite,
})

const foldAll = (events) => events.reduce(fold, initial())
const settings = { currency: '₪', usdRate: 3.7, peakPricing: true }

test('peak hours are DeepSeek’s own windows, in UTC, on weekdays only', () => {
  assert.equal(isPeak(PEAK), true, '02:00 UTC on a Monday is peak')
  assert.equal(isPeak(OFF_PEAK), false, '12:00 UTC is off-peak')
  assert.equal(isPeak(Date.UTC(2026, 9, 11, 2, 0, 0)), false, 'Sunday 02:00 UTC is off-peak')
  assert.equal(isPeak(Date.UTC(2026, 9, 12, 5, 0, 0)), false, 'the 04:00-06:00 gap is off-peak')
  assert.equal(isPeak(Date.UTC(2026, 9, 12, 9, 59, 0)), true, '09:59 UTC is still peak')
  assert.equal(isPeak(Date.UTC(2026, 9, 12, 10, 0, 0)), false, '10:00 UTC is not')
})

test('legacy and current model names price at the row they actually run as', () => {
  assert.deepEqual(priceRow('deepseek-flash'), { key: 'flash', known: true })
  assert.deepEqual(priceRow('deepseek-v4-flash-vision-exp'), { key: 'flash', known: true })
  assert.deepEqual(priceRow('deepseek-v4-pro'), { key: 'pro', known: true })
  assert.deepEqual(priceRow('gpt-4o'), { key: 'flash', known: false }, 'an unknown model is priced at the fallback row and REPORTED as unknown')
})

test('one million uncached Flash tokens at peak cost $0.30, and half that off-peak', () => {
  const at = costOfSample(usage(1e6, 0), { modelId: FLASH, timeMs: PEAK, peakPricing: true })
  assert.equal(Number(at.toFixed(6)), 0.3)
  const off = costOfSample(usage(1e6, 0), { modelId: FLASH, timeMs: OFF_PEAK, peakPricing: true })
  assert.equal(Number(off.toFixed(6)), 0.15)
  assert.equal(costOfSample(usage(1e6, 0), { modelId: FLASH, timeMs: OFF_PEAK, peakPricing: false }), 0.3, 'peakPricing off bills everything at the peak rate')
})

test('cache reads are priced 50x below misses, and cache writes are priced as input', () => {
  const hit = costOfSample(usage(0, 0, 1e6), { modelId: FLASH, timeMs: PEAK, peakPricing: true })
  const miss = costOfSample(usage(1e6, 0), { modelId: FLASH, timeMs: PEAK, peakPricing: true })
  assert.equal(Number((miss / hit).toFixed(3)), 50)
  assert.equal(
    costOfSample(usage(0, 0, 0, 1e6), { modelId: FLASH, timeMs: PEAK, peakPricing: true }),
    miss,
    'a cache write has no published price; it is prompt input',
  )
})

test('a usage sample is read from the stream exactly as the harness writes it', () => {
  const event = attempt(1, 1, usage(10, 5))
  assert.deepEqual(usageOf(event), usage(10, 5))
  assert.equal(usageOf({ type: 'assistant/attempt', data: { stream: [{ type: 'chunk', chunk: { type: 'text-delta', text: 'x' } }] } }), undefined)
  assert.equal(usageOf({ type: 'step/start', data: { turn: 1, step: 1 } }), undefined)
})

test('the settlement replaces its own step’s attempt sample — the same tokens the token pill counts', () => {
  const state = foldAll([attempt(1, 1, usage(1000, 100)), message(1, 1, usage(1000, 100), FLASH)])
  assert.equal(state.windows['flash|off'].cacheMiss, 1000, 'not 2000: the settlement supersedes the attempt')
  assert.equal(state.windows['flash|off'].output, 100)
})

test('a retried attempt adds on top instead of replacing', () => {
  const state = foldAll([
    attempt(1, 1, usage(1000, 0)),
    { type: 'llm/retry-started', time: OFF_PEAK, data: { turn: 1, step: 1 } },
    message(1, 1, usage(1200, 50), FLASH),
  ])
  assert.equal(state.windows['flash|off'].cacheMiss, 2200, 'the failed attempt is billed and kept')
})

test('every event of another type returns the same state reference', () => {
  const state = foldAll([message(1, 1, usage(10, 1), FLASH)])
  assert.equal(fold(state, { type: 'tool/result', time: OFF_PEAK, data: {} }), state)
  assert.equal(fold(state, { type: 'step/start', time: OFF_PEAK, data: { turn: 1, step: 2 } }), state)
})

test('a step that crosses the peak boundary keeps its tokens in the window that billed them', () => {
  const state = foldAll([attempt(1, 1, usage(1000, 0), PEAK), message(1, 1, usage(1000, 0), FLASH, OFF_PEAK)])
  assert.equal(state.windows['flash|peak'].cacheMiss, 0, 'the peak sample was undone in its own window')
  assert.equal(state.windows['flash|off'].cacheMiss, 1000)
})

test('the published value is money in the configured currency, and the rate re-prices it', () => {
  const state = foldAll([message(1, 1, usage(1e6, 0), FLASH, PEAK)])
  const shekels = view(state, settings)
  assert.equal(Number(shekels.usd.toFixed(6)), 0.3)
  assert.equal(shekels.amount, 1.11, '0.30 * 3.7')
  assert.equal(shekels.text, '₪1.11')
  assert.equal(shekels.totalTokens, 1e6)
  assert.deepEqual(shekels.models, [FLASH])
  assert.deepEqual(shekels.unpriced, [])

  const dollars = view(state, { currency: 'USD', usdRate: 1, peakPricing: true })
  assert.equal(dollars.text, '0.30 USD')
  assert.equal(dollars.amount, 0.3)
})

test('an unpriced model is priced at the fallback row AND named in the value', () => {
  const state = foldAll([message(1, 1, usage(1000, 100), 'some-new-model')])
  const published = view(state, settings)
  assert.deepEqual(published.unpriced, ['some-new-model'])
  assert.equal(Number(published.usd.toFixed(9)), Number((((1000 * 0.3 + 100 * 1.2) / 1e6) * 0.5).toFixed(9)))
})

test('the peak/off-peak split is published, and turning it off bills at the peak rate', () => {
  const state = foldAll([message(1, 1, usage(1e6, 0), FLASH, PEAK), message(2, 1, usage(1e6, 0), FLASH, OFF_PEAK)])
  const split = view(state, settings)
  assert.equal(split.peak.tokens + split.offPeak.tokens, 2e6)
  assert.equal(Number(split.peak.usd.toFixed(6)), 0.3)
  assert.equal(Number(split.offPeak.usd.toFixed(6)), 0.15)
  assert.equal(Number(split.usd.toFixed(6)), 0.45)
  assert.equal(Number(view(state, { ...settings, peakPricing: false }).usd.toFixed(6)), 0.6)
})

test('money and token formatting keep a small bill readable', () => {
  assert.equal(money(0.00423, { currency: '₪', usdRate: 3.7 }).text, '₪0.02')
  assert.equal(money(1, { currency: '$', usdRate: 0.5 }).text, '$0.50')
  assert.equal(tokens(950), '950')
  assert.equal(tokens(12000), '12K')
  assert.equal(tokens(1900000), '1.9M')
})
