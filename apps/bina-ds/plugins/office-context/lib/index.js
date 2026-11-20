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
 *
 * An INDEX, not the briefs (EXU-64, the decision of ai/context/azaria-context-architecture.md §5,
 * DGO-647: "App briefs become an index plus on-demand reading"). The whole briefs grew to 99,903
 * characters — 22 apps, every «Traps» section of every one — and with them the system message to
 * 109,036. On the office's local model (a 32k window) the harness then had room for ONE answer
 * token: Azaria answered «ה» and stopped at max-tokens, after reading for 17 minutes; on a cloud
 * model it is the same prompt paid on every turn. So the section is now one line per app — what it
 * is for, where it answers, and where its brief is — and the agent READS the brief of the app a task
 * touches. The index is built from the compiler's structured twin (`agent-context.json`); when that
 * cannot be read the whole briefs are given, as before, so nothing is ever lost. `mode: 'full'`
 * keeps the old behaviour on purpose.
 */
import { readFileSync, existsSync } from 'node:fs'

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

/** The checkout the brief paths are relative to: the file's own `.generated/registry/` parent. */
const rootOf = (file) => file.replace(/\/?\.generated\/registry\/[^/]*$/, '') || '.'

/** What an app is FOR, in one line: the first sentence of the brief's first paragraph of prose (the
 *  briefs wrap at ~100 columns, so a line is not a sentence), without emphasis, cut at a word. */
export function purposeOf(brief, max = 180) {
  const para = []
  for (const raw of String(brief || '').split('\n')) {
    const line = raw.trim()
    if (!line) { if (para.length) break; continue }
    if (/^(#|<!--|\||```|>|-{3,}|[-*] )/.test(line)) { if (para.length) break; continue }
    para.push(line)
  }
  // a brief that opens with its own label («What it is FOR:») says what it is for right after it
  const plain = para.join(' ').replace(/\*\*/g, '').replace(/\s+/g, ' ').trim().replace(/^What it is for[.:]\s*/i, '')
  const end = plain.search(/[.!?](\s|$)/)
  const first = end > 0 ? plain.slice(0, end + 1) : plain
  if (first.length <= max) return first
  const cut = first.slice(0, max)
  return `${cut.slice(0, Math.max(cut.lastIndexOf(' '), max - 30))}…`
}

/** Where an app's brief lives, relative to the checkout (apps/ or platform-base/). */
function briefPath(root, app) {
  const file = app.file || 'AGENT.md'
  for (const base of ['apps', 'platform-base']) {
    if (existsSync(`${root}/${base}/${app.id}/${file}`)) return `${base}/${app.id}/${file}`
  }
  return `apps/${app.id}/${file}`
}

/** The index: the rules every app shares once, then one line per installed app. Deterministic, so the
 *  prompt prefix stays byte-identical between turns (the cache, principle 7). */
export function renderIndex(doc, root) {
  const apps = Array.isArray(doc && doc.apps) ? doc.apps : []
  const lines = [
    '# אפליקציות הלשכה — מה מותקן (אינדקס)',
    '',
    'The apps installed in this office, compiled from app.json + platform.state.yaml: an app that is not',
    'listed here is NOT installed — do not invent it. Each line says what the app is for and where it',
    'answers. Its brief (vocabulary, ops, traps) is a file: READ IT with the `read` tool before you',
    'operate that app, and only for the apps the task touches.',
    '',
    'How every app is used: call its ops over HTTP at its endpoint on `traefik-network`;',
    '`GET <endpoint>/manifest` is the live contract (when a brief and `/manifest` disagree, `/manifest`',
    'is right); accounts live in `connections` (`http://connections:8990`); never reach into another',
    "app's volume, database or files; a machine outside the platform goes through `computers`; a",
    'secret through the account the app already holds — never ask the owner to paste a key.',
    '',
    `${apps.length} app(s):`,
  ]
  for (const app of apps) {
    const ifaces = [...new Set((app.capabilities || []).map((c) => c && c.interface).filter(Boolean))]
    const where = app.endpoint ? ` · \`${app.endpoint}\`${ifaces.length ? ` (${ifaces.join(', ')})` : ''}` : ''
    const what = purposeOf(app.brief)
    lines.push(`- **${app.title || app.id}** \`${app.id}\`${where}${what ? ` — ${what}` : ''} · brief: \`${briefPath(root, app)}\``)
  }
  return `${lines.join('\n')}\n`
}

export function apply(ctx, config = {}) {
  const file = resolvePath(config)
  const full = config.mode === 'full'
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
      if (!full) {
        const twin = file.replace(/\.md$/, '.json')
        try {
          const body = renderIndex(JSON.parse(readFileSync(twin, 'utf8')), rootOf(file))
          report(`${SECTION_NAME}: an index of ${body.split('\n- ').length - 1} app(s), ${body.length} characters, from ${twin}`)
          return body
        } catch (error) {
          report(`${SECTION_NAME}: no index (${twin}: ${error?.code ?? error?.message}) — the whole briefs instead`)
        }
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
