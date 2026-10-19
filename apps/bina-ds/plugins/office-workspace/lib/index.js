/**
 * office-workspace — registers one directory in the harness's workspace registry at boot.
 *
 * The registry (ctx.workspaceRegistry, package @deepseek-ai/dsh-workspace) is the list the hero's
 * workspace chip offers; normally a person adds a directory through the picker. This row adds the
 * configured directory once, titled "הלשכה הדיגיטלית". `create()` returns the existing record for
 * a directory that already has one, so later boots are no-ops.
 */
import { stat } from 'node:fs/promises'

export const name = '@bina/dsh-office-workspace'
export const inject = ['workspaceRegistry']

export async function apply(ctx, config = {}) {
  const path = config.path ?? process.env.DSH_OFFICE_ROOT
  const title = config.title ?? 'הלשכה הדיגיטלית'
  if (!path) return
  // `inject` above guarantees the registry is up before apply runs; register right away.
  try {
    const s = await stat(path)
    if (!s.isDirectory()) return
    const record = await ctx.workspaceRegistry.create(path, title)
    process.stderr.write(`office-workspace: ${title} → ${path} (${record?.id ?? 'registered'})\n`)
  } catch (error) {
    process.stderr.write(`office-workspace: could not register ${path}: ${String(error)}\n`)
  }
}
