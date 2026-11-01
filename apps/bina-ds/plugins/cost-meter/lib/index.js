/**
 * cost-meter — what this conversation cost, in the office's own currency.
 *
 * WHAT IT IS. The harness counts tokens: the composer's footer carries a "1.9 מיליון" pill fed by
 * the `tokenUsage` projection. Tokens are the vendor's unit, not the owner's; he asked (2026-10-12)
 * for the price instead — "במקום 1.9 מיליון טוקנים אני רוצה את העלות בשקל או מה שמוגדר בהגדרות".
 * This plugin replaces that figure with the money it bought.
 *
 * WHERE IT SITS, AND WHY THERE. `ctx.sessionProjections` is the harness's own extension point for
 * exactly this shape of fact: a pure fold over committed session events, published to the browser as
 * a whole value and checkpointed per session. `tokenUsage` is one registered unit; this is another,
 * so the client reads it with the same `useProjection` the token pill uses, gets the same replay
 * semantics, and every session — including one that ran before this plugin existed — is priced from
 * its own durable log rather than from a counter that starts at zero.
 *
 * THE FOLD MIRRORS `tokenUsage` ON PURPOSE. A step's usage arrives as an attempt sample and then as
 * the settlement's sample; the later one REPLACES the earlier, and an `llm/retry-started` closes the
 * slot so the retried attempt adds on top. Pricing a different set of samples than the pill counts
 * would show two numbers about one session that cannot both be right, so the replacement rule is
 * reproduced exactly in lib/cost.js — the money is the price OF THE TOKENS ON SCREEN.
 *
 * WHAT IS ACTUALLY NEW. Tokens are split by (price row, peak vs off-peak) at the moment each sample
 * was reported, because both change the answer by 2x-50x and both are properties of the sample
 * rather than of the total (see lib/pricing.js). Currency and exchange rate are NOT folded: they are
 * settings, read when the value is published, so changing them never needs a replay.
 *
 * This file is the wiring only — schemas and registration; the arithmetic lives in lib/cost.js so
 * the tests and the display mock can import it without the harness's own packages.
 */
import z from 'zod'
import s from '@deepseek-ai/schemastery'
import { DEFAULTS } from './pricing.js'
import { fold, initial, view } from './cost.js'

/** The plugin's cordis id, spelled once. */
export const name = '@bina/dsh-cost-meter'

/** The projection key the browser reads; the same string lib/client.js asks for. */
export const PROJECTION_KEY = 'costMeter'

/** The four token buckets as a schema; also the shape of every bucket value in this plugin. */
const bucketsSchema = z
  .object({
    cacheHit: z.number().int().nonnegative(),
    cacheMiss: z.number().int().nonnegative(),
    cacheWrite: z.number().int().nonnegative(),
    output: z.number().int().nonnegative(),
  })
  .strict()

/** Persisted fold state. Declared with zod because `stateSchema` IS a ZodType by the contract. */
const stateSchema = z
  .object({
    /** `"<flash|pro>|<peak|off>"` → tokens billed there. The one place money is derived from. */
    windows: z.record(z.string(), bucketsSchema),
    /** Model ids the session actually ran on, in the order they first appeared. */
    models: z.array(z.string()),
    /** Model ids with no published price, priced at the fallback row and reported as such. */
    unpriced: z.array(z.string()),
    /** The sample a same-step replacement would undo: its window and its exact buckets. */
    last: z
      .object({
        turn: z.number().int().nonnegative(),
        step: z.number().int().nonnegative(),
        key: z.string(),
        buckets: bucketsSchema,
      })
      .strict()
      .nullable(),
  })
  .strict()

/** The client-visible payload — everything a screen may show, and nothing it must compute. */
const viewSchema = z.object({
  usd: z.number().nonnegative(),
  amount: z.number().nonnegative(),
  currency: z.string(),
  rate: z.number().positive(),
  text: z.string(),
  totalTokens: z.number().int().nonnegative(),
  buckets: bucketsSchema,
  rows: z.array(
    z.object({
      bucket: z.string(),
      tokens: z.number().int().nonnegative(),
      usd: z.number().nonnegative(),
      amount: z.number().nonnegative(),
    }),
  ),
  models: z.array(z.string()),
  unpriced: z.array(z.string()),
  peak: z.object({ tokens: z.number().int().nonnegative(), usd: z.number().nonnegative() }),
  offPeak: z.object({ tokens: z.number().int().nonnegative(), usd: z.number().nonnegative() }),
  peakPricing: z.boolean(),
})

/** Settings namespace owned by this plugin (lowercase and hyphenated — the settings law). */
export const SETTINGS_NAMESPACE = 'cost-meter'

/** Durable schema of the section; also the wire envelope the browser scope validates against. */
export const SettingsSchema = s.object({
  currency: s.string().default(DEFAULTS.currency),
  usdRate: s.number().min(0).default(DEFAULTS.usdRate),
  peakPricing: s.boolean().default(DEFAULTS.peakPricing),
})

/** Composition row config — the same three keys, and the settings `base` layer. */
export const Config = SettingsSchema

/** Required service. The registry drives the fold; this plugin subscribes to nothing. */
export const inject = ['sessionProjections']

/**
 * Mount: register the settings namespace (an optional service) and the projection unit.
 * @param ctx - host cordis context.
 * @param config - this row's composition config, used as the settings base layer.
 */
export function apply(ctx, config = {}) {
  let settings
  ctx.inject(['settings'], (settingsCtx) => {
    settings = settingsCtx.settings.register(SETTINGS_NAMESPACE, SettingsSchema, { base: config, applies: 'live' })
  })
  ctx.sessionProjections.register({
    key: PROJECTION_KEY,
    stateVersion: 1,
    stateSchema,
    init: initial,
    apply: fold,
    wire: {
      viewSchema,
      // Read at publish time, not folded: a changed rate or currency re-prices the next value the
      // browser receives, and a session opened afterwards is priced in the new currency at once.
      view: (state) => view(state, settings === undefined ? config : settings.get()),
    },
  })
}
