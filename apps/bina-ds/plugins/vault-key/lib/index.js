/**
 * vault-key — the office's vault as a LIVE credential source for the agent harness.
 *
 * WHAT IT CHANGES, AND WHERE. The harness mounts one credential service (`credentials`, shipped as
 * `@deepseek-ai/dsh-credentials-local`): settings name a REFERENCE (`DEEPSEEK_API_KEY`), and every
 * provider adapter resolves that reference PER REQUEST — the seam's own contract, so a changed value
 * reaches the next request with no restart (see `@deepseek-ai/dsh-llm-deepseek`'s `resolveApiKey`).
 * This plugin IS that service: it keeps everything the file-backed one does, and adds one value
 * shape. A reference whose stored value is `vault:<connection-id>` is a POINTER at a connection in
 * the office's credential plane, and the value behind it is fetched from `connections` at the moment
 * it is used, in this container's own name, through the broker — never copied into
 * `$DSH_HOME/.credentials.yaml` and never written to this volume.
 *
 * WHY NOT JUST THE BOOT ENVIRONMENT. `inject.sh` already hands every app its declared connections as
 * environment variables, and those still work — they are the read-only layer this service keeps. But
 * they are a SNAPSHOT taken when the container started: rotating a key in the vault, or pointing the
 * agent at a different connection, needs a restart, and the Models page cannot show or choose any of
 * it. This adds the missing half (owner, 2026-11-03: «שאפלקציית בינה יכולה לבחור מתוך אפלקציית
 * סודות … ולהזרים את המפתח מהסודות»).
 *
 * PRECEDENCE, DELIBERATELY NARROW. A LITERAL stored value keeps the shipped layering exactly
 * (launch environment, then the file, then `.env`). Only a `vault:` value changes it, and only for
 * itself: an operator who bound a reference to a vault connection meant the vault, so the vault wins
 * over a launch-time environment value for that one reference. That is what makes the feature work
 * at all on an office whose `.env` still carries an older copy of the same key.
 *
 * WHAT THE MODELS PAGE SEES. `describe()` reports `source: "office-vault:<connection>"` for a bound
 * reference — the one field the harness's own credential API passes through unchanged — so the
 * provider card can show WHICH connection is behind the key without any new API. When the vault holds
 * nothing (a placeholder, or a connection nobody filled in) the credential reads as UNCONFIGURED
 * rather than as a key that will fail on first use.
 */

import z from 'zod'
import { LocalCredentialProvider } from '@deepseek-ai/dsh-credentials-local'
import { VaultSource, vaultConnectionOf } from './vault.mjs'

/** The plugin's cordis id. */
export const name = '@bina/dsh-vault-key'

/** How the shipped service is configured, plus where the vault is. */
export const Config = z.object({
  path: z.string().optional(),
  dshHome: z.string().optional(),
  watch: z.boolean().default(true),
  debounceMs: z.number().min(0).default(100),
  /** The connections app on the office network. */
  vaultUrl: z.string().default('http://connections:8990'),
  /** This app's compose service — the broker grants only what it declares, and refuses a mismatch. */
  service: z.string().default('bina-ds'),
  /** How long one connection's lease is reused. Short: a rotation should reach the next few requests. */
  cacheSeconds: z.number().min(0).default(30),
  /** One lease's whole timeout. */
  timeoutMs: z.number().min(100).default(4000),
})

/**
 * The credential service, with `vault:<connection-id>` values resolved against the office vault.
 */
export default class VaultCredentialProvider extends LocalCredentialProvider {
  static Config = Config

  /**
   * @param ctx - host cordis context.
   * @param config - this row's composition config.
   */
  constructor(ctx, config) {
    super(ctx, config)
    this.vault = new VaultSource({
      url: config.vaultUrl,
      service: config.service,
      cacheSeconds: config.cacheSeconds,
      timeoutMs: config.timeoutMs,
      log: (message) => ctx.logger.warn(message),
    })
  }

  /**
   * The connection a reference is bound to, read straight out of the stored document.
   * @param ref - the credential reference.
   * @returns the connection id, or `undefined` when this reference holds a literal value.
   */
  boundConnection(ref) {
    return vaultConnectionOf(this.values.get(ref))
  }

  /**
   * Resolve one reference for one operation.
   *
   * A bound reference is answered by the vault, and a vault failure is thrown rather than reported as
   * "no key": an adapter that cannot reach the vault must fail with the vault's reason in the
   * message, not with a generic missing-credential.
   * @param ref - the credential reference.
   * @returns the value and the layer that supplied it, or `undefined` while unconfigured.
   */
  async resolve(ref) {
    const connection = this.boundConnection(ref)
    if (connection === undefined) return super.resolve(ref)
    const value = await this.vault.secret(ref, connection)
    return value === undefined ? undefined : { value, source: `office-vault:${connection}` }
  }

  /**
   * Describe one reference without revealing it — the shape the Models page and the settings API read.
   * @param ref - the credential reference.
   * @returns configured state, the supplying layer, and writability.
   */
  async describe(ref) {
    const connection = this.boundConnection(ref)
    if (connection === undefined) return super.describe(ref)
    const state = await this.vault.state(connection)
    if (!state.configured) {
      this.ctx.logger.warn(
        'vault-key: "%s" is bound to the vault connection "%s", which holds no value (%s)',
        ref,
        connection,
        state.reason ?? 'not configured',
      )
    }
    return { configured: state.configured, source: `office-vault:${connection}`, writable: true }
  }
}
