/**
 * office-context — the installed apps' own briefs, straight from the platform compiler.
 *
 * The problem this closes: the agent's persona used to name apps by hand — a paragraph about
 * `computers`, and nothing about whatever was installed last week. A list living in a prompt is a
 * list that can only be as current as the last person who remembered to edit it.
 *
 * Instead, every app declares `agent.context` in its app.json (a Markdown file it owns), and
 * `platform/manager/reconcile.py` compiles the ENABLED apps' briefs into one file,
 * `.generated/registry/agent-context.md`. This row registers that file as a system-prompt section
 * whose text is READ ON EVERY PROMPT ASSEMBLY — so `./bbox apps enable <id>` (which re-renders it)
 * changes the agent's prompt on the next turn: no restart, no rebuild, no hand-maintained list.
 * Disable an app and its brief leaves with it.
 *
 * Two properties are deliberate and load-bearing:
 *
 *   * a missing or unreadable file contributes NOTHING and never throws (empty section text is
 *     dropped by the prompt renderer). An agent whose brief cannot be read loses the brief, not
 *     its session — and the log line below is the only place that failure is visible, because an
 *     absent section is otherwise completely silent;
 *   * `interpolate: false`. A brief is DATA written by app authors, and the harness's variable
 *     interpolation is strict: one stray `{{…}}` in a brief (an n8n expression is the obvious way
 *     in) would throw on every turn and kill the session.
 */
import { readFileSync } from 'node:fs'

export const name = '@bina/dsh-office-context'
export const inject = ['systemPrompt']

/** Namespaced, so it can never shadow a harness-owned section (deployment:persona-*, harness:identity). */
const SECTION_NAME = 'bina:office-context'
/** After the identity (0), before every tool's instructions (1000). */
const SECTION_ORDER = 400
/** The compiler's output, relative to the office checkout. */
const RELATIVE_PATH = '.generated/registry/agent-context.md'

/**
 * The brief to read: an explicit `config.path`, else `$DSH_OFFICE_ROOT/.generated/registry/…`.
 * Trailing slashes are stripped but whitespace is NOT: this deployment's directory name ends in a
 * space, and `DSH_OFFICE_ROOT` carries it.
 */
function resolvePath(config) {
  if (typeof config.path === 'string' && config.path.length > 0) return config.path
  const root = process.env.DSH_OFFICE_ROOT
  return root ? `${root.replace(/\/+$/, '')}/${RELATIVE_PATH}` : undefined
}

export function apply(ctx, config = {}) {
  const file = resolvePath(config)
  let reported = ''

  // Log only when the READING CHANGES — every turn would flood the container log, and a silent
  // path failure is exactly the state this line exists to make visible.
  const report = (line) => {
    if (line === reported) return
    reported = line
    process.stderr.write(`office-context: ${line}\n`)
  }

  ctx.effect(() => ctx.systemPrompt.section({
    name: SECTION_NAME,
    order: SECTION_ORDER,
    interpolate: false,
    text: () => {
      if (file === undefined) {
        report('no path: DSH_OFFICE_ROOT is unset and no config.path was given — section stays empty')
        return ''
      }
      try {
        const body = readFileSync(file, 'utf8')
        report(`${SECTION_NAME}: ${body.length} bytes from ${file}`)
        return body
      } catch (error) {
        report(`${SECTION_NAME}: cannot read ${file} (${error?.code ?? error?.message}) — section stays empty`)
        return ''
      }
    },
  }), 'office-context.section()')
}
