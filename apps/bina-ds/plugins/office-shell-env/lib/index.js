/**
 * office-shell-env — the office's deliberately given service tokens, in the agent's shell, by name.
 *
 * The problem this closes (DGO-1812): the office hands the agent's container two scoped service tokens —
 * COMPUTERS_EXEC_TOKEN (its proof to computers when it runs a command on a machine, apps/computers/AGENT.md)
 * and CHAT_READ_TOKEN (chat's READ-only token: GET /api/accounts and GET /api/readyz,
 * apps/chat/operatives/chat.accounts.md). But the harness spawns every model shell call from
 * `scrubbedParentEnv()` (@deepseek-ai/dsh-subprocess), which drops every name matching
 * /KEY|PASSWORD|SECRET|TOKEN/i — on purpose: no credential reaches a child implicitly. So `$COMPUTERS_EXEC_TOKEN`
 * was always empty in the agent's curl (measured in bina-ds-staging, 2026-11-11).
 *
 * The harness's own way through is explicit: a plugin registers a `dsh-shell-env` contributor that declares
 * every DSH_* key it returns, and those merge AFTER the scrub. This is that contributor, and it is the one
 * place the office decides which credential the model's shell holds. Two properties are deliberate:
 *
 *   * ONLY the names listed in FORWARDED cross, each from the one container variable it names; a value that
 *     is unset or blank contributes nothing (the key is absent, so a brief's curl sends no header and chat or
 *     computers says why) — never an empty string that looks like a value;
 *   * only an AGENT's shell call receives them (the same rule the registry applies to DSH_SESSION_ID): a
 *     shell the harness runs for itself gets nothing.
 *
 * Neither token is the office's full credential: the chat one opens two reads, the computers one is the
 * agent's own caller identity there. The office agent also holds the checkout and the engine's socket by the
 * owner's decision (2026-09-17), so this is scope for its routine calls, not containment.
 */

export const name = '@bina/dsh-office-shell-env'
export const inject = ['shellEnv']

/** The DSH_* name the model's shell sees → the container variable it is read from, and what it is for. */
export const FORWARDED = Object.freeze({
  DSH_COMPUTERS_EXEC_TOKEN: Object.freeze({
    from: 'COMPUTERS_EXEC_TOKEN',
    description: "the office agent's proof to computers when it runs a command on a machine (apps/computers/AGENT.md)",
  }),
  DSH_CHAT_READ_TOKEN: Object.freeze({
    from: 'CHAT_READ_TOKEN',
    description: "chat's READ-only office token: GET /api/accounts and GET /api/readyz, nothing else (chat.accounts)",
  }),
})

/** The values to hand on, from `env`: only the declared names, only a non-blank value. */
export function values(env = process.env) {
  const out = {}
  for (const [key, { from }] of Object.entries(FORWARDED)) {
    const v = env[from]
    if (typeof v === 'string' && v.trim() !== '') out[key] = v   // handed on as it is: a value is never rewritten
  }
  return out
}

export function apply(ctx) {
  ctx.shellEnv.register({
    name: 'bina:office-service-tokens',
    variables: Object.fromEntries(Object.entries(FORWARDED).map(([key, v]) => [key, { description: v.description }])),
    resolve: (execution) => (execution && execution.agent !== undefined ? values() : {}),
  })
}
