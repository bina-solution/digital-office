/**
 * The admin-facing agent surfaces: one-shot agent-runner jobs, the live agent chat (menu 21) and the
 * OpenHands dispatcher (menu 22).
 *
 * Ported verbatim in behaviour. Three transport calls existed here and each had a transport-free
 * replacement waiting in ctx:
 *   sock.sendMessage(jid, {react:{...}})      -> ctx.react('👀')      best-effort, no-op where unsupported
 *   sock.sendPresenceUpdate('composing', jid) -> ctx.typing(true)     ditto
 *   sendLongTextMessage(sock, senderId, t)    -> ctx.sendLong(t)      chunking moved to the runtime
 *
 * Everything else — budgets, model switching, in-flight locks, the idle sweepers, the cost footers —
 * never referred to a socket in the first place and is unchanged.
 */
const { TEXTS } = require('../../src/config');
const { setSubscriberState, updateSubscriber } = require('../../src/data/subscribers');
const { runAgentJob, getAgentStatus, cancelAgentJob, AgentRunnerBusyError } = require('../../src/services/agent_runner');
const { chatTurn: agentChatTurn, AgentRunnerBusyError: AgentChatBusyError } = require('../../src/services/agent_chat');
const { automationsTurn } = require('../../src/services/automations_chat');
const { dispatch: dispatcherDispatch, DispatcherBusyError } = require('../../src/services/dispatcher_client');
const { convertUsdToIls } = require('../../src/services/currency');
const { Sentry } = require('../../src/services/sentry');
const { STATES, MENU_CHOICES } = require('./states');
const { reply } = require('./reply');

// ── Automations agent routing ───────────────────────────────────────
const AUTOMATION_KEYWORDS = [
    'מסמך', 'מסמכים', 'חשבונית', 'חשבוניות', 'ספק', 'דרייב', 'גוגל',
    'גימייל', 'מייל', 'אימייל', 'תייג', 'תיוג', 'לייבל',
    'פריוריטי', 'נקלט', 'שורה', 'גיליון', 'אוטומציה', 'אוטומציות',
    'incoming document', 'invoice', 'supplier', 'gmail', 'email label',
    'google sheet', 'automation', 'priority', 'drive',
    'document id', 'document name',
];
const isAutomationQuery = (text) => {
    const lower = (text || '').toLowerCase();
    return AUTOMATION_KEYWORDS.some(kw => lower.includes(kw.toLowerCase()));
};

// Registry of agent-runner-backed admin jobs. Adding a new one is a single
// entry here + a context file at `context/{job}-context.txt`.
const AGENT_JOBS = {
    [MENU_CHOICES.SUNDAY_REPORT]: {
        job: 'deployment-report',
        startingText: () => TEXTS.SUNDAY_REPORT_STARTING,
        donePrefix: () => TEXTS.SUNDAY_REPORT_DONE_PREFIX,
        failedPrefix: () => TEXTS.SUNDAY_REPORT_FAILED_PREFIX
    },
    [MENU_CHOICES.QUICK_HEALTH]: {
        job: 'quick-health',
        startingText: () => TEXTS.QUICK_HEALTH_STARTING,
        donePrefix: () => TEXTS.QUICK_HEALTH_DONE_PREFIX,
        failedPrefix: () => TEXTS.QUICK_HEALTH_FAILED_PREFIX
    },
    [MENU_CHOICES.DEPLOYMENT_REVIEW]: {
        job: 'deployment-review',
        startingText: () => TEXTS.DEPLOYMENT_REVIEW_STARTING,
        donePrefix: () => TEXTS.DEPLOYMENT_REVIEW_DONE_PREFIX,
        failedPrefix: () => TEXTS.DEPLOYMENT_REVIEW_FAILED_PREFIX
    },
    [MENU_CHOICES.SECURITY_REVIEW]: {
        job: 'security-review',
        startingText: () => TEXTS.SECURITY_REVIEW_STARTING,
        donePrefix: () => TEXTS.SECURITY_REVIEW_DONE_PREFIX,
        failedPrefix: () => TEXTS.SECURITY_REVIEW_FAILED_PREFIX
    },
    [MENU_CHOICES.STORAGE_REPORT]: {
        job: 'storage-report',
        startingText: () => TEXTS.STORAGE_REPORT_STARTING,
        donePrefix: () => TEXTS.STORAGE_REPORT_DONE_PREFIX,
        failedPrefix: () => TEXTS.STORAGE_REPORT_FAILED_PREFIX
    }
};

// Track in-flight agent jobs per (sender, job) so a double-press gets a
// friendly "already running" reply instead of a 429 or duplicate $$ run.
const agentJobsInFlight = new Set();
const inFlightKey = (senderId, job) => `${senderId}:${job}`;

const runAgentJobForAdmin = async (ctx, cfg) => {
    const senderId = ctx.sender.id;
    const key = inFlightKey(senderId, cfg.job);
    if (agentJobsInFlight.has(key)) {
        return reply(ctx, TEXTS.AGENT_JOB_ALREADY_RUNNING);
    }
    agentJobsInFlight.add(key);
    await reply(ctx, cfg.startingText());
    // Fire-and-forget: agent jobs can take minutes; ack immediately,
    // then stream the result back in chunks when done. `ctx` closes over the conversation, so the
    // late reply lands in the right place even though the message handler returned long ago.
    (async () => {
        try {
            const started = Date.now();
            const { text, toolUseCount, stats } = await runAgentJob(cfg.job);
            const elapsedMin = Math.max(1, Math.round((Date.now() - started) / 60000));
            const chunks = await ctx.sendLong(text);
            const parts = [
                `${text.length} chars`,
                `${chunks} parts`,
                `${toolUseCount} tool calls`,
                `${elapsedMin}m`
            ];
            if (stats && typeof stats.total_cost_usd === 'number') {
                const usd = stats.total_cost_usd;
                const { formatted: ilsStr } = await convertUsdToIls(usd);
                parts.push(`$${usd.toFixed(4)} / ${ilsStr}`);
            }
            if (stats && (stats.input_tokens != null || stats.output_tokens != null)) {
                const i = stats.input_tokens ?? 0;
                const o = stats.output_tokens ?? 0;
                const cr = stats.cache_read_input_tokens ?? 0;
                const cw = stats.cache_creation_input_tokens ?? 0;
                parts.push(`in=${i} out=${o} cache_r=${cr} cache_w=${cw}`);
            }
            await ctx.send(`${cfg.donePrefix()}${parts.join(' / ')}`);
        } catch (e) {
            console.error(`[agent-job:${cfg.job}]`, e);
            if (e instanceof AgentRunnerBusyError) {
                // Translate the sidecar's raw 429 into a friendly message that
                // tells the admin exactly what is blocking and for how long.
                const b = e.body || {};
                const running = (b.current && b.current.job)
                    ? `${b.current.job} (${Math.max(1, Math.round(b.current.elapsedMs / 60000))}m)`
                    : 'another job';
                try {
                    await ctx.send(`${TEXTS.AGENT_RUNNER_BUSY_PREFIX}${running}. ${TEXTS.AGENT_RUNNER_BUSY_HINT}`);
                } catch { /* ignore */ }
                return;
            }
            Sentry.captureException(e);
            try {
                await ctx.send(cfg.failedPrefix() + e.message);
            } catch { /* ignore */ }
        } finally {
            agentJobsInFlight.delete(key);
        }
    })();
};

// =====================================================================
// Live agent chat (menu choice 21)
// =====================================================================
// Per-admin in-memory session registry. Each entry tracks the SDK session id
// the sidecar handed back, running cost / turn counters for budget control,
// and a `turnInFlight` lock so a double-press doesn't fire two parallel turns
// for the same admin.
const agentChatSessions = new Map(); // senderId -> { sessionId, lastActiveAt, totalCost, turnCount, turnInFlight, model }
const AGENT_CHAT_IDLE_MS = 15 * 60 * 1000; // 15 min idle → drop session
const AGENT_CHAT_BUDGET_USD = parseFloat(process.env.AGENT_CHAT_BUDGET_USD || '5');
const AGENT_CHAT_MAX_TURNS = parseInt(process.env.AGENT_CHAT_MAX_TURNS || '40', 10);
const AGENT_CHAT_DEFAULT_MODEL = process.env.AGENT_CHAT_DEFAULT_MODEL || 'deepseek-chat';
const AGENT_CHAT_MODELS = (process.env.AGENT_CHAT_MODELS || 'deepseek-chat,deepseek-reasoner,deepseek-v4-flash,deepseek-v4-pro,haiku,sonnet,opus,claude-haiku-4-6,claude-sonnet-4-6,claude-opus-4-6')
    .split(',').map((s) => s.trim()).filter(Boolean);

const formatChatCostWithIls = async (totalCost, turnCount) => {
  const usd = (totalCost || 0);
  const { formatted: ilsStr } = await convertUsdToIls(usd);
  return `$${usd.toFixed(4)} / ${ilsStr} (${turnCount} תורים)`;
};

const endAgentChatSession = async (senderId, reason) => {
    const sess = agentChatSessions.get(senderId);
    agentChatSessions.delete(senderId);
    await setSubscriberState(senderId, null);
    return sess
        ? { reason, sessionId: sess.sessionId, totalCost: sess.totalCost, turnCount: sess.turnCount }
        : { reason };
};

// Sweep idle chat sessions once a minute. Cheap: in-memory map, small N.
const _agentChatSweeper = setInterval(() => {
    const now = Date.now();
    for (const [senderId, sess] of agentChatSessions.entries()) {
        if (sess.turnInFlight) continue;
        if (now - sess.lastActiveAt > AGENT_CHAT_IDLE_MS) {
            agentChatSessions.delete(senderId);
            // Fire-and-forget — the sweeper has no ctx (nobody is talking to us), so persist the state
            // reset only. The next inbound message routes back to the menu.
            setSubscriberState(senderId, null).catch(() => { /* ignore */ });
        }
    }
}, 60 * 1000);
_agentChatSweeper.unref?.();

const startAgentChat = async (ctx) => {
    const senderId = ctx.sender.id;
    agentChatSessions.set(senderId, {
        sessionId: null,
        lastActiveAt: Date.now(),
        totalCost: 0,
        turnCount: 0,
        turnInFlight: false,
        model: AGENT_CHAT_DEFAULT_MODEL
    });
    await updateSubscriber(senderId, { state: STATES.AGENT_CHAT, stateChangedAt: Date.now() });
    return reply(ctx, TEXTS.AGENT_CHAT_STARTED);
};

const handleAgentChatTurn = async (ctx, text) => {
    const senderId = ctx.sender.id;
    const trimmed = (text || '').trim();

    // No text (e.g. an image) — politely ignore, keep the session.
    if (!trimmed) {
        return reply(ctx, '(שלח טקסט בלבד בצ׳אט הזה — שלח /end לסיום)');
    }

    const sess = agentChatSessions.get(senderId);
    if (!sess) {
        // Stale state with no in-memory entry — recover by routing back to the menu.
        await setSubscriberState(senderId, null);
        return reply(ctx, TEXTS.AGENT_CHAT_IDLE_TIMEOUT, true);
    }

    // Slash commands.
    if (trimmed === '/end' || trimmed === '/exit' || /^ביטול$/i.test(trimmed)) {
        const ended = await endAgentChatSession(senderId, 'user_end');
        return reply(ctx, TEXTS.AGENT_CHAT_ENDED_PREFIX + await formatChatCostWithIls(ended.totalCost, ended.turnCount), true);
    }
    if (trimmed === '/cost') {
        return reply(ctx, TEXTS.AGENT_CHAT_COST_PREFIX + await formatChatCostWithIls(sess.totalCost, sess.turnCount));
    }
    if (trimmed === '/model' || /^\/model\s*$/.test(trimmed)) {
        return reply(ctx, `📊 Current model: *${sess.model}*\nAvailable: ${AGENT_CHAT_MODELS.join(' / ')}\nSwitch: /model <name>\n\ne.g. /model deepseek-chat`);
    }
    const modelMatch = trimmed.match(/^\/model\s+([a-z0-9][a-z0-9-]{1,80})$/i);
    if (modelMatch) {
        const requested = modelMatch[1];
        if (!AGENT_CHAT_MODELS.includes(requested)) {
            return reply(ctx, `❌ Unknown model. Available: ${AGENT_CHAT_MODELS.join(' / ')}`);
        }
        sess.model = requested;
        sess.lastActiveAt = Date.now();
        return reply(ctx, `✅ Model switched to *${requested}* (effective next turn).`);
    }
    if (trimmed === '/status') {
        try {
            const s = await getAgentStatus();
            const line = s.current
                ? `${TEXTS.AGENT_STATUS_RUNNING_PREFIX}${s.current.job} — ${Math.max(1, Math.round(s.current.elapsedMs / 60000))}m`
                : TEXTS.AGENT_STATUS_IDLE;
            return reply(ctx, line);
        } catch (e) {
            return reply(ctx, TEXTS.AGENT_STATUS_FAILED_PREFIX + e.message);
        }
    }
    if (trimmed === '/stop') {
        if (!sess.turnInFlight) return reply(ctx, TEXTS.AGENT_CHAT_NO_TURN_RUNNING);
        try {
            await cancelAgentJob();
            return reply(ctx, TEXTS.AGENT_CHAT_TURN_CANCELLED);
        } catch (e) {
            return reply(ctx, TEXTS.AGENT_CANCEL_FAILED_PREFIX + e.message);
        }
    }

    // Budget check (turn count + cost).
    if (sess.turnCount >= AGENT_CHAT_MAX_TURNS || sess.totalCost >= AGENT_CHAT_BUDGET_USD) {
        const ended = await endAgentChatSession(senderId, 'budget');
        return reply(ctx,
            TEXTS.AGENT_CHAT_BUDGET_EXHAUSTED_PREFIX + await formatChatCostWithIls(ended.totalCost, ended.turnCount) + TEXTS.AGENT_CHAT_BUDGET_EXHAUSTED_SUFFIX,
            true);
    }

    if (sess.turnInFlight) {
        return reply(ctx, TEXTS.AGENT_JOB_ALREADY_RUNNING);
    }
    sess.turnInFlight = true;
    sess.lastActiveAt = Date.now();

    // Ack with a reaction so the admin knows we received the turn. Both of these are best-effort by
    // contract — a backend without reactions or presence silently does nothing.
    await ctx.react('👀');
    await ctx.typing(true);

    let result;
    try {
        const useAuto = isAutomationQuery(trimmed);
        const turnFn = useAuto ? automationsTurn : agentChatTurn;
        if (useAuto) console.log('[hacohen-bot] routing to automations:', trimmed.slice(0, 80));
        result = await turnFn({ sessionId: sess.sessionId, message: trimmed, model: sess.model });
    } catch (e) {
        sess.turnInFlight = false;
        await ctx.typing(false);
        if (e instanceof AgentChatBusyError) {
            const b = e.body || {};
            const running = (b.current && b.current.job)
                ? `${b.current.job} (${Math.max(1, Math.round((b.current.elapsedMs || 0) / 60000))}m)`
                : 'משהו אחר';
            return reply(ctx, `${TEXTS.AGENT_CHAT_BUSY_PREFIX}${running}. ${TEXTS.AGENT_RUNNER_BUSY_HINT}`);
        }
        console.error('[agent-chat-turn]', e);
        Sentry.captureException(e);
        return reply(ctx, TEXTS.AGENT_CHAT_TURN_FAILED_PREFIX + e.message);
    }

    await ctx.typing(false);

    // Persist learned sessionId + accumulate stats.
    if (result.sessionId) sess.sessionId = result.sessionId;
    sess.turnCount += 1;
    sess.lastActiveAt = Date.now();
    const turnCost = (result.stats && typeof result.stats.total_cost_usd === 'number') ? result.stats.total_cost_usd : 0;
    sess.totalCost += turnCost;
    sess.turnInFlight = false;

    const baseText = result.text && result.text.trim() ? result.text : '';
    const suffix = result.error ? `\n\n⚠️ ${result.error}` : '';
    const replyText = (baseText + suffix).trim() || TEXTS.AGENT_CHAT_EMPTY_REPLY;
    await ctx.sendLong(replyText);

    // Compact footer: cost + turn # + tools used. Keeps the bot honest about cost.
    const turnIls = await convertUsdToIls(turnCost);
    const totalIls = await convertUsdToIls(sess.totalCost);
    const footerBits = [
        `#${sess.turnCount}`,
        `${result.toolUseCount} tools`,
        `$${turnCost.toFixed(4)} / ${turnIls.formatted} (∑ $${sess.totalCost.toFixed(4)} / ${totalIls.formatted})`
    ];
    if (result.stats && result.stats.duration_ms) {
        footerBits.push(`${Math.max(1, Math.round(result.stats.duration_ms / 1000))}s`);
    }
    footerBits.push(`[${sess.model}]`);
    await ctx.send('— ' + footerBits.join(' / '));

    // Auto-close on budget after this turn so the admin sees the answer first.
    if (sess.totalCost >= AGENT_CHAT_BUDGET_USD || sess.turnCount >= AGENT_CHAT_MAX_TURNS) {
        const ended = await endAgentChatSession(senderId, 'budget');
        await reply(ctx,
            TEXTS.AGENT_CHAT_BUDGET_EXHAUSTED_PREFIX + await formatChatCostWithIls(ended.totalCost, ended.turnCount) + TEXTS.AGENT_CHAT_BUDGET_EXHAUSTED_SUFFIX,
            true);
    }
};

// ── Dispatcher Session Management (OpenHands autonomous coding) ────────
const dispatcherSessions = new Map(); // senderId -> { conversationId, lastActiveAt, turnCount, turnInFlight, model }
const DISPATCHER_IDLE_MS = 30 * 60 * 1000; // 30 min idle → drop session
const DISPATCHER_MAX_TURNS = parseInt(process.env.DISPATCHER_MAX_TURNS || '50', 10);
const DISPATCHER_DEFAULT_MODEL = process.env.DISPATCHER_DEFAULT_MODEL || 'deepseek-v4-pro';
const DISPATCHER_MODELS = (process.env.DISPATCHER_MODELS || 'deepseek-chat,deepseek-reasoner,deepseek-v4-flash,deepseek-v4-pro,haiku,sonnet,opus,claude-haiku-4-6,claude-sonnet-4-6,claude-opus-4-6')
    .split(',').map((s) => s.trim()).filter(Boolean);

const endDispatcherSession = async (senderId, reason) => {
    const sess = dispatcherSessions.get(senderId);
    dispatcherSessions.delete(senderId);
    await setSubscriberState(senderId, null);
    return sess
        ? { reason, conversationId: sess.conversationId, turnCount: sess.turnCount }
        : { reason };
};

// Sweep idle dispatcher sessions
const _dispatcherSweeper = setInterval(() => {
    const now = Date.now();
    for (const [senderId, sess] of dispatcherSessions.entries()) {
        if (sess.turnInFlight) continue;
        if (now - sess.lastActiveAt > DISPATCHER_IDLE_MS) {
            dispatcherSessions.delete(senderId);
            setSubscriberState(senderId, null).catch(() => { /* ignore */ });
        }
    }
}, 60 * 1000);
_dispatcherSweeper.unref?.();

const startDispatcher = async (ctx) => {
    const senderId = ctx.sender.id;
    dispatcherSessions.set(senderId, {
        conversationId: null,
        lastActiveAt: Date.now(),
        turnCount: 0,
        turnInFlight: false,
        model: DISPATCHER_DEFAULT_MODEL
    });
    await updateSubscriber(senderId, { state: STATES.DISPATCHER, stateChangedAt: Date.now() });
    const modelList = DISPATCHER_MODELS.join(' / ');
    return reply(ctx, TEXTS.DISPATCHER_STARTED + '\n\n📊 Models: ' + modelList + '\nDefault: *' + DISPATCHER_DEFAULT_MODEL + '*');
};

const handleDispatcherTurn = async (ctx, text) => {
    const senderId = ctx.sender.id;
    const trimmed = (text || '').trim();

    if (!trimmed) {
        return reply(ctx, '(שלח טקסט בלבד — שלח /end לסיום)');
    }

    const sess = dispatcherSessions.get(senderId);
    if (!sess) {
        await setSubscriberState(senderId, null);
        return reply(ctx, TEXTS.DISPATCHER_ENDED_PREFIX + '(session expired)', true);
    }

    // Slash commands
    if (trimmed === '/end' || trimmed === '/exit' || /^ביטול$/i.test(trimmed)) {
        const ended = await endDispatcherSession(senderId, 'user_end');
        return reply(ctx, TEXTS.DISPATCHER_ENDED_PREFIX + `${ended.turnCount} turns`, true);
    }
    if (trimmed === '/status') {
        const line = sess.turnInFlight
            ? `🟡 Dispatcher busy — turn #${sess.turnCount} in flight, model: ${sess.model}`
            : `🟢 Dispatcher idle — ${sess.turnCount} turns used, model: ${sess.model}`;
        return reply(ctx, line);
    }
    if (trimmed === '/model' || /^\/model\s*$/.test(trimmed)) {
        return reply(ctx, `📊 Current model: *${sess.model}*\nAvailable: ${DISPATCHER_MODELS.join(' / ')}\nSwitch: /model <name>`);
    }
    const modelMatch = trimmed.match(/^\/model\s+([a-z0-9][a-z0-9/_-]{1,80})$/i);
    if (modelMatch) {
        const requested = modelMatch[1];
        if (!DISPATCHER_MODELS.includes(requested)) {
            return reply(ctx, `❌ Unknown model. Available: ${DISPATCHER_MODELS.join(' / ')}`);
        }
        sess.model = requested;
        sess.lastActiveAt = Date.now();
        return reply(ctx, `✅ Model switched to *${requested}* (effective next turn).`);
    }
    if (trimmed === '/stop') {
        if (!sess.turnInFlight) return reply(ctx, TEXTS.DISPATCHER_NO_ACTIVE);
        try {
            await fetch(`http://dispatcher:8800/cancel/${encodeURIComponent(senderId)}`, {
                method: 'POST',
                headers: { authorization: `Bearer ${process.env.DISPATCHER_TOKEN}` },
            });
            sess.turnInFlight = false;
            return reply(ctx, TEXTS.DISPATCHER_CANCELLED);
        } catch (e) {
            return reply(ctx, `❌ Cancel error: ${e.message}`);
        }
    }

    // Turn limit
    if (sess.turnCount >= DISPATCHER_MAX_TURNS) {
        const ended = await endDispatcherSession(senderId, 'limit');
        return reply(ctx, `🛑 Turn limit reached (${ended.turnCount}). Session closed.`, true);
    }

    if (sess.turnInFlight) {
        return reply(ctx, TEXTS.AGENT_JOB_ALREADY_RUNNING);
    }
    sess.turnInFlight = true;
    sess.lastActiveAt = Date.now();

    // Ack
    await ctx.react('🚀');
    await ctx.typing(true);

    let result;
    try {
        result = await dispatcherDispatch({
            userId: senderId,
            message: trimmed,
            sessionId: sess.conversationId,
            model: sess.model,
        });
    } catch (e) {
        sess.turnInFlight = false;
        await ctx.typing(false);
        if (e instanceof DispatcherBusyError) {
            return reply(ctx, `${TEXTS.DISPATCHER_BUSY_PREFIX}Try again later.`);
        }
        console.error('[dispatcher-turn]', e);
        Sentry.captureException(e);
        return reply(ctx, TEXTS.DISPATCHER_TURN_FAILED_PREFIX + e.message);
    }

    await ctx.typing(false);

    if (result.sessionId) sess.conversationId = result.sessionId;
    sess.turnCount += 1;
    sess.lastActiveAt = Date.now();
    sess.turnInFlight = false;

    const baseText = result.text && result.text.trim() ? result.text : '';
    const suffix = result.error ? `\n\n⚠️ ${result.error}` : '';
    const replyText = (baseText + suffix).trim() || TEXTS.DISPATCHER_EMPTY_REPLY;
    await ctx.sendLong(replyText);

    // Footer
    const footerBits = [
        `#${sess.turnCount}`,
        `${result.toolUseCount} tools`,
    ];
    if (result.stats && result.stats.durationMs) {
        footerBits.push(`${Math.max(1, Math.round(result.stats.durationMs / 1000))}s`);
    }
    footerBits.push(`[${sess.model}]`);
    await ctx.send('— ' + footerBits.join(' / '));

    if (sess.turnCount >= DISPATCHER_MAX_TURNS) {
        const ended = await endDispatcherSession(senderId, 'limit');
        await reply(ctx, `🛑 Turn limit reached (${ended.turnCount}).`, true);
    }
};

module.exports = {
    AGENT_JOBS,
    runAgentJobForAdmin,
    startAgentChat, handleAgentChatTurn,
    startDispatcher, handleDispatcherTurn,
    isAutomationQuery,
    // test seams
    _agentChatSessions: agentChatSessions,
    _dispatcherSessions: dispatcherSessions,
};
