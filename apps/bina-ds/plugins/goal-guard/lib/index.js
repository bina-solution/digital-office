/**
 * goal-guard — the office's fence around the harness's automatic goal round loop.
 *
 * WHY THIS EXISTS (measured, 2026-11-01/02, session-f7a05d7b):
 *   The harness's `goal-round-driver` gives an active goal one more round every time its agent goes
 *   idle. Nothing in that loop asks whether the round it just paid for *did* anything. On 2026-11-01
 *   21:00 the loop ran 786 rounds in 60 minutes, of which **783 had one step, zero tool calls and
 *   lasted ~2.2 s** — text in, text out, next round, text in, text out. The whole session came to
 *   961 rounds / 2,593 steps / 1.245 **billion** input tokens and ₪19.10, 82% of the office's entire
 *   LLM spend for the week. The goal's own report each time it was stopped was, in the model's
 *   words, "everything that is mine on DGO-553 is implemented, deployed and proven; what is left
 *   needs your decision" — so an honest "I am done, the rest is the owner's" was being answered with
 *   another round, 783 times.
 *
 *   Second hole, same incident: `create_goal` takes an explicit `max_goal_rounds`, and the goal
 *   service's own default is 256. The run's goals were created with **400** — three times, after
 *   clearing the goal that had just reached its cap. A ceiling a run can raise by re-creating the
 *   goal is not a ceiling.
 *
 * WHAT IT DOES — two rules, both on facts the harness already publishes, both fail-safe (a listener
 * that throws here can disturb the agent loop, so nothing below throws or awaits):
 *
 *   1. NO PROGRESS, NO NEXT ROUND. A turn that IS an automatic goal round (`user/message` whose
 *      source is `{kind:'goal'}`) and that ended without a single `tool/call` does not get a next
 *      round: the goal is blocked with `code: 'no-progress'`, and the driver stops (it only drives
 *      an `active`+`armed` goal). The owner sees a blocked goal with the reason instead of a
 *      silent meter.
 *      A round that means to end the autonomous run has a tool for it — `update_goal complete` or
 *      `update_goal blocked` — and both are tool calls, so they are untouched by this rule.
 *
 *   2. THE OFFICE'S ROUND CEILING. Every goal (created or edited) is clamped to `maxGoalRounds`
 *      (default 12; BINA_GOAL_MAX_ROUNDS overrides). The model can still *ask* for 400; it gets the
 *      office's number. This does not shorten work — it makes the run come back to the owner, who
 *      resumes it with one click when there is more to do.
 *
 * WHAT IT DELIBERATELY DOES NOT DO: it never resumes, never completes and never clears a goal, and
 * it never touches a goal that is already terminal. Stopping automation is a safety act; starting it
 * again is the owner's.
 *
 * Disable with `BINA_GOAL_GUARD_DISABLED=1`. The row's config in the profile may also set
 * `{maxGoalRounds, noProgress: false}`.
 */

export const name = '@bina/dsh-goal-guard'
/** The three services this needs: live agents (to act as one), the goals registry, nothing else. */
export const inject = ['agents', 'goals']

const OFF = new Set(['0', 'false', 'False', 'no', 'off'])

/** A positive safe integer from config/env, or the fallback. */
function positive(raw, fallback) {
  const n = Number(raw)
  return Number.isSafeInteger(n) && n > 0 ? n : fallback
}

/**
 * Install the two fences.
 * @param ctx - the harness context: `agents` and `goals` are injected.
 * @param config - `{maxGoalRounds, noProgress}` from the profile row.
 */
export function apply(ctx, config = {}) {
  if (OFF.has(String(process.env.BINA_GOAL_GUARD_DISABLED ?? '').trim())) {
    warn(ctx, 'disabled by BINA_GOAL_GUARD_DISABLED — the round loop is unfenced')
    return
  }

  const maxGoalRounds = positive(
    config.maxGoalRounds ?? process.env.BINA_GOAL_MAX_ROUNDS,
    12,
  )
  const noProgress = config.noProgress !== false

  /** The round (if any) this turn is serving, and whether it produced a single tool call. */
  const turns = new Map()

  /** One warning line, never a throw: this runs inside the agent's own event path. */
  function warn(of, message) {
    try {
      of.logger?.warn?.(`goal-guard: ${message}`)
    } catch {
      /* a logger that throws is not a reason to break a turn */
    }
  }

  /**
   * The live goal for this session's agent, if there is one.
   * @param session - the session the event belongs to.
   * @returns `{agent, goal}` or undefined.
   */
  function liveGoal(session) {
    const agent = ctx.agents.get(session.id)
    if (agent === undefined) return undefined
    const goal = ctx.goals.get(agent)
    return goal === undefined ? undefined : { agent, goal }
  }

  /** Rule 1: end the automatic run when the round it just paid for did nothing. */
  function endEmptyRound(session, turn) {
    if (!noProgress) return
    const live = liveGoal(session)
    if (live === undefined || live.goal.phase !== 'active') return
    // Only the exact round this goal is running: a stale queued round must not block a live goal.
    if (live.goal.id !== turn.goalId || live.goal.revision !== turn.revision) return
    try {
      ctx.goals.block(
        live.agent,
        { id: live.goal.id, revision: live.goal.revision },
        {
          code: 'no-progress',
          message:
            `סבב ${turn.round} הסתיים בלי אף קריאת כלי אחד — כלומר בלי שום שינוי במצב הלשכה. ` +
            'הלופ האוטומטי נעצר כאן ולא יזמן סבב נוסף. אדם מחליט אם להמשיך (resume) או לסגור.',
        },
      )
      warn(ctx, `blocked goal ${live.goal.id} after empty round ${turn.round}`)
    } catch (error) {
      warn(ctx, `could not block goal ${live.goal.id}: ${String(error?.message ?? error)}`)
    }
  }

  /** Rule 2: no goal runs on more rounds than the office allows, whoever asked for what. */
  function clampCeiling(agent) {
    let goal
    try {
      goal = ctx.goals.get(agent)
    } catch {
      return
    }
    if (goal === undefined || goal.phase === 'complete') return
    if (!(goal.maxGoalRounds > maxGoalRounds)) return
    try {
      ctx.goals.edit(agent, { id: goal.id, revision: goal.revision }, { maxGoalRounds })
      warn(ctx, `goal ${goal.id} asked ${goal.maxGoalRounds} rounds; clamped to ${maxGoalRounds}`)
    } catch (error) {
      warn(ctx, `could not clamp goal ${goal.id}: ${String(error?.message ?? error)}`)
    }
  }

  ctx.effect(function* () {
    ctx.on('session/event', (session, event) => {
      const type = event?.type
      if (type === 'turn/start') {
        turns.set(session.id, { goalId: undefined, revision: undefined, round: 0, toolCalls: 0 })
        return
      }
      const turn = turns.get(session.id)
      if (turn === undefined) return
      if (type === 'user/message') {
        const source = event.data?.source
        if (source?.kind === 'goal' && positive(source.round, 0) > 0) {
          turn.goalId = source.goalId
          turn.revision = source.revision
          turn.round = source.round
        }
        return
      }
      if (type === 'tool/call') {
        turn.toolCalls += 1
        return
      }
      if (type === 'turn/end') {
        turns.delete(session.id)
        if (turn.goalId !== undefined && turn.toolCalls === 0) {
          try {
            endEmptyRound(session, turn)
          } catch (error) {
            warn(ctx, `empty-round check failed: ${String(error?.message ?? error)}`)
          }
        }
      }
    })

    ctx.on('agent/disposed', ({ agent }) => {
      try {
        turns.delete(agent?.session?.id)
      } catch {
        /* a disposed agent that cannot name its session leaves one map entry behind, nothing more */
      }
    })

    ctx.on('goal/changed', ({ agent }) => {
      try {
        clampCeiling(agent)
      } catch (error) {
        warn(ctx, `ceiling check failed: ${String(error?.message ?? error)}`)
      }
    })
  })

  warn(ctx, `armed: ceiling ${maxGoalRounds} rounds, empty-round stop ${noProgress ? 'on' : 'off'}`)
}
