/**
 * hacohen-bot — the live bookkeeping assistant, ported off WhatsApp.
 *
 * This is the same bot that has been running on a real phone number: document intake (invoices,
 * delivery notes, aging reports), company lookup, URL intake, per-user daily limits, subscriber state,
 * and a set of admin surfaces that dispatch agent-runner jobs. Nothing was dropped to make the port
 * tidy; the diff against the old `src/whatsapp/chat_bot.js` is almost entirely mechanical:
 *
 *   sock + senderId        ->  ctx                (the destination is where the message came from)
 *   Baileys message shapes ->  msg.text / msg.attachments
 *   downloadContentFrom…   ->  attachment.download()
 *   reactions / presence   ->  ctx.react / ctx.typing (best-effort)
 *   onPrivateMessage +
 *   onGroupMessage         ->  ONE onMessage; `groupReply` existed only because the private helper
 *                              hard-coded "answer the sender's DM", which ctx makes impossible to
 *                              get wrong.
 *
 * What did NOT become transport-neutral, and why:
 *   · The JID routing (`@g.us` vs `@s.whatsapp.net` vs `@lid`, and the LID→phone fallback) stayed in
 *     `src/whatsapp/chat_bot.js`. It is not bot logic — it is how WhatsApp addresses a conversation.
 *     The bot now receives `isGroup` and `conversationId` already decided.
 *   · Admin-only document intake is still refused inside groups (menu 10/11/12 answer "DM me"). That
 *     is a deliberate product rule about where a private financial document may be posted, not a
 *     transport limitation, so it ports as-is to Telegram and local chat.
 *
 * Services it still imports directly (document_processing, companies_api, agent_runner, subscribers):
 * those are APP services, not transports. A bot is allowed to have a backend; it is not allowed to
 * have a socket.
 */
const { TEXTS } = require('../../src/config');
const { isAdmin, loadSettings, setBotAdmins } = require('../../src/services/settings_api');
const { getOrCreateSubscriber, setSubscriberState, updateSubscriber } = require('../../src/data/subscribers');
const { processGeneralDocument, processBalanceSheet, processLinkDocument } = require('../../src/services/document_processing');
const { findCompanyByInput, fetchCompanies } = require('../../src/services/companies_api');
const { getAgentStatus, cancelAgentJob } = require('../../src/services/agent_runner');
const { UnableToGuessCompany } = require('../../src/errors');
const { Sentry } = require('../../src/services/sentry');

const {
    STATES, STATE_TIMEOUT_MS, AWAITING_STATES, MENU_CHOICES, CANCEL_REGEX, extractUrl,
} = require('./states');
const { reply, menuText } = require('./reply');
const { saveAttachment } = require('./media');
const { manageDailyMessageLimit } = require('./daily_limit');
const {
    AGENT_JOBS, runAgentJobForAdmin,
    startAgentChat, handleAgentChatTurn,
    startDispatcher, handleDispatcherTurn,
} = require('./agent_sessions');

/** The first document/image on the message, or null. The bot only ever processes one per message —
 *  same as before, when Baileys could only carry one. */
const firstAttachment = (msg) => {
    const list = (msg && msg.attachments) || [];
    return list.find((a) => a.kind === 'document' || a.kind === 'image') || null;
};

/** How long a half-finished exchange ("send me the file") stays open on THIS connection, before it
 *  resets to the menu. Falls back to the module constant so a bot invoked without settings — every
 *  existing test, and the WhatsApp shim — behaves exactly as it did. */
const stateTimeoutMs = (ctx) => {
    const h = ctx && ctx.settings && Number(ctx.settings.stateTimeoutHours);
    return Number.isFinite(h) && h > 0 ? h * 60 * 60 * 1000 : STATE_TIMEOUT_MS;
};

/** The four "we took your document" lines, identical across the six places that used to build them. */
const processedSummary = (prefix, processed) => prefix + '\n'
    + (processed.companyGuess?.companyName ? TEXTS.LABEL_COMPANY + processed.companyGuess.companyName + '\n' : '')
    + (processed.ids?.document_id ? TEXTS.LABEL_DOCUMENT + processed.ids.document_id + ' (' + processed.ids.document_type + ')\n' : '')
    + (processed.driveLink ? TEXTS.LABEL_LINK + processed.driveLink + '\n' : '');

// ── menu ──────────────────────────────────────────────────────────────────────
const handleHelloBack = async (ctx, user) =>
    reply(ctx, TEXTS.HELLO_BACK.replace('{name}', user.fullName), true);

const onMenuResponse = async (msg, ctx, user) => {
    const senderId = ctx.sender.id;
    const choice = (msg.text || '').trim();
    const messageDate = msg.timestamp instanceof Date ? msg.timestamp : new Date();
    const attachment = firstAttachment(msg);
    const url = extractUrl(msg.text);

    switch (choice) {
    case MENU_CHOICES.HELLO_BACK:
        return handleHelloBack(ctx, user);
    case MENU_CHOICES.ABOUT:
        return reply(ctx, TEXTS.ABOUT_BOT, true);
    case MENU_CHOICES.BALANCE_SHEET:
        if (await isAdmin(senderId)) {
            await updateSubscriber(senderId, { state: STATES.AWAIT_BALANCE_SHEET_FILE, stateChangedAt: Date.now() });
            return reply(ctx, TEXTS.PROMPT_BALANCE_SHEET_FILE);
        }
        break;
    case MENU_CHOICES.GENERIC_DOCUMENT:
        if (await isAdmin(senderId)) {
            await updateSubscriber(senderId, { state: STATES.AWAIT_GENERIC_DOCUMENT_FILE, stateChangedAt: Date.now() });
            return reply(ctx, TEXTS.PROMPT_GENERIC_DOCUMENT_FILE);
        }
        break;
    case MENU_CHOICES.LINK_DOCUMENT:
        if (await isAdmin(senderId)) {
            await updateSubscriber(senderId, { state: STATES.AWAIT_LINK_DOCUMENT, stateChangedAt: Date.now() });
            return reply(ctx, TEXTS.PROMPT_LINK_DOCUMENT);
        }
        break;
    case MENU_CHOICES.RELOAD_SETTINGS:
        if (await isAdmin(senderId)) {
            await loadSettings();
            await fetchCompanies(true);
            return reply(ctx, TEXTS.SETTINGS_RELOADED, true);
        }
        break;
    case MENU_CHOICES.SUNDAY_REPORT:
    case MENU_CHOICES.QUICK_HEALTH:
    case MENU_CHOICES.DEPLOYMENT_REVIEW:
    case MENU_CHOICES.SECURITY_REVIEW:
    case MENU_CHOICES.STORAGE_REPORT:
        if (await isAdmin(senderId)) {
            return runAgentJobForAdmin(ctx, AGENT_JOBS[choice]);
        }
        break;
    case MENU_CHOICES.AGENT_STATUS:
        if (await isAdmin(senderId)) {
            try {
                const s = await getAgentStatus();
                const line = s.current
                    ? `${TEXTS.AGENT_STATUS_RUNNING_PREFIX}${s.current.job} — ${Math.max(1, Math.round(s.current.elapsedMs / 60000))}m (inFlight ${s.inFlight}/${s.maxConcurrency}, model ${s.model})${TEXTS.AGENT_STATUS_RUNNING_HINT}`
                    : `${TEXTS.AGENT_STATUS_IDLE} (model ${s.model})`;
                return reply(ctx, line);
            } catch (e) {
                return reply(ctx, TEXTS.AGENT_STATUS_FAILED_PREFIX + e.message);
            }
        }
        break;
    case MENU_CHOICES.AGENT_CANCEL:
        if (await isAdmin(senderId)) {
            try {
                const r = await cancelAgentJob();
                if (r.idle) return reply(ctx, TEXTS.AGENT_CANCEL_NONE);
                const m = Math.max(1, Math.round((r.cancelled?.elapsedMs || 0) / 60000));
                return reply(ctx, `${TEXTS.AGENT_CANCEL_OK_PREFIX}${r.cancelled?.job || '?'} (${m}m)`);
            } catch (e) {
                return reply(ctx, TEXTS.AGENT_CANCEL_FAILED_PREFIX + e.message);
            }
        }
        break;
    case MENU_CHOICES.AGENT_CHAT:
        if (await isAdmin(senderId)) return startAgentChat(ctx);
        break;
    case MENU_CHOICES.DISPATCHER:
        if (await isAdmin(senderId)) return startDispatcher(ctx);
        break;
    default:
        break;
    }

    // Auto-intake: if user sends a document or link outside of a menu selection, process it automatically
    if (attachment && await isAdmin(senderId)) {
        try {
            await reply(ctx, TEXTS.AUTO_INTAKE_DOC);
            const { filePath, caption } = await saveAttachment(attachment);
            const processed = await processGeneralDocument({ textContext: caption || '', filePath, messageDate, senderId });
            return reply(ctx, processedSummary(TEXTS.GENERIC_DOC_RECEIVED_PREFIX, processed), true);
        } catch (e) {
            console.error('[auto-intake-doc]', e);
            Sentry.captureException(e);
            return reply(ctx, TEXTS.ERROR_GENERIC_DOC_PREFIX + e.message, true);
        }
    }

    if (url && await isAdmin(senderId)) {
        try {
            await reply(ctx, TEXTS.AUTO_INTAKE_LINK);
            const processed = await processLinkDocument({ url, textContext: msg.text || '', messageDate, senderId });
            return reply(ctx, processedSummary(TEXTS.LINK_DOC_RECEIVED_PREFIX, processed), true);
        } catch (e) {
            console.error('[auto-intake-link]', e);
            Sentry.captureException(e);
            return reply(ctx, TEXTS.ERROR_LINK_DOC_PREFIX + e.message, true);
        }
    }

    return reply(ctx, TEXTS.INVALID_OPTION, true);
};

const onNewUser = async (ctx) => {
    await setSubscriberState(ctx.sender.id, null); // ensure cleared first
    await reply(ctx, TEXTS.WELCOME_MESSAGE, true);
};

// ── the state machine (1:1 conversations) ─────────────────────────────────────
const onUserMessage = async (msg, ctx, user) => {
    const senderId = ctx.sender.id;
    const messageDate = msg.timestamp instanceof Date ? msg.timestamp : new Date();
    const text = msg.text;
    const attachment = firstAttachment(msg);

    // Auto-reset stale awaiting states (older than 24h) back to menu
    if (AWAITING_STATES.includes(user.state) && user.stateChangedAt && (Date.now() - user.stateChangedAt > stateTimeoutMs(ctx))) {
        console.log(`[state-timeout] Resetting stale state "${user.state}" for ${senderId} (set ${Math.round((Date.now() - user.stateChangedAt) / 3600000)}h ago)`);
        await setSubscriberState(senderId, null);
        user.state = null;
    }

    const handleGenericDocUpload = async () => {
        if (text && CANCEL_REGEX.test(text) && !attachment) {
            await setSubscriberState(senderId, null);
            return reply(ctx, TEXTS.CANCELLED, true);
        }
        if (!attachment) return reply(ctx, TEXTS.PROMPT_GENERIC_DOCUMENT_ONLY);
        try {
            const { filePath, caption } = await saveAttachment(attachment);
            // Immediate acknowledgement so user knows we're working
            await reply(ctx, TEXTS.PROCESSING_GENERIC_DOCUMENT);
            const processed = await processGeneralDocument({ textContext: caption || '', filePath, messageDate, senderId });
            await setSubscriberState(senderId, null);
            await reply(ctx, processedSummary(TEXTS.GENERIC_DOC_RECEIVED_PREFIX, processed), true);
        } catch (e) {
            console.error('[generic-doc-upload]', e);
            await reply(ctx, TEXTS.ERROR_GENERIC_DOC_PREFIX + e.message, true);
        }
    };

    const handleBalanceSheetFile = async () => {
        if (text && CANCEL_REGEX.test(text) && !attachment) {
            await setSubscriberState(senderId, null);
            return reply(ctx, TEXTS.CANCELLED, true);
        }
        if (!attachment) return reply(ctx, TEXTS.PROMPT_BALANCE_SHEET_FILE_OR_CANCEL);

        // Save file first
        let filePath, caption;
        try {
            ({ filePath, caption } = await saveAttachment(attachment));
        } catch (e) {
            console.error('[balance-sheet-upload-save]', e);
            return reply(ctx, TEXTS.ERROR_SAVE_FILE_PREFIX + e.message);
        }

        // Process balance sheet
        try {
            // Immediate acknowledgement so user knows we're working
            await reply(ctx, TEXTS.PROCESSING_BALANCE_SHEET);
            const processed_bs = await processBalanceSheet({ textContext: caption || '', filePath, messageDate, senderId });
            await setSubscriberState(senderId, null);
            const out = TEXTS.BALANCE_SHEET_RECEIVED_PREFIX + '\n'
                + TEXTS.LABEL_COMPANY + processed_bs.companyGuess.companyName + '\n'
                + TEXTS.LABEL_LINK + (processed_bs.driveLink || TEXTS.NOT_APPLICABLE);
            return reply(ctx, out, true);
        } catch (e) {
            // if unable to guess company, ask user for it
            if (e instanceof UnableToGuessCompany) {
                await updateSubscriber(senderId, { pending_balance_file: filePath, state: STATES.AWAIT_BALANCE_SHEET_COMPANY, stateChangedAt: Date.now() });
                return reply(ctx, TEXTS.UNABLE_TO_GUESS_COMPANY);
            }
            // other errors
            console.error('[balance-sheet-upload]', e);
            return reply(ctx, TEXTS.ERROR_BALANCE_SHEET_PREFIX + e.message);
        }
    };

    const handleBalanceSheetCompany = async () => {
        if (text && CANCEL_REGEX.test(text)) {
            await setSubscriberState(senderId, null);
            return reply(ctx, TEXTS.CANCELLED, true);
        }
        const comp = findCompanyByInput(text);
        if (!comp) return reply(ctx, TEXTS.PROMPT_COMPANY_NOT_FOUND);
        const pendingFile = user.pending_balance_file;
        if (!pendingFile) {
            await setSubscriberState(senderId, null);
            return reply(ctx, TEXTS.NO_PENDING_FILE_PREFIX + MENU_CHOICES.BALANCE_SHEET + '.', true);
        }
        try {
            const processed_bs = await processBalanceSheet({ textContext: text, filePath: pendingFile, explicitCompany: comp, messageDate, senderId });
            await setSubscriberState(senderId, null);
            const out = TEXTS.BALANCE_SHEET_RECEIVED_PREFIX + '\n'
                + TEXTS.LABEL_COMPANY + processed_bs.companyGuess.companyName + '\n'
                + TEXTS.LABEL_LINK + (processed_bs.driveLink || TEXTS.NOT_APPLICABLE);
            await reply(ctx, out, true);
        } catch (e) {
            console.error('[balance-sheet-company]', e);
            await reply(ctx, TEXTS.ERROR_BALANCE_SHEET_PREFIX + e.message, true);
        }
    };

    const handleLinkDocument = async () => {
        if (text && CANCEL_REGEX.test(text)) {
            await setSubscriberState(senderId, null);
            return reply(ctx, TEXTS.CANCELLED, true);
        }
        const url = extractUrl(text);
        if (!url) return reply(ctx, TEXTS.PROMPT_LINK_ONLY);
        try {
            await reply(ctx, TEXTS.PROCESSING_LINK_DOCUMENT);
            const processed = await processLinkDocument({ url, textContext: text || '', messageDate, senderId });
            await setSubscriberState(senderId, null);
            return reply(ctx, processedSummary(TEXTS.LINK_DOC_RECEIVED_PREFIX, processed), true);
        } catch (e) {
            console.error('[link-doc-upload]', e);
            await reply(ctx, TEXTS.ERROR_LINK_DOC_PREFIX + e.message, true);
        }
    };

    switch (user.state) {
    case STATES.NEW:
        return onNewUser(ctx);
    case STATES.AWAIT_GENERIC_DOCUMENT_FILE:
        return handleGenericDocUpload();
    case STATES.AWAIT_BALANCE_SHEET_FILE:
        return handleBalanceSheetFile();
    case STATES.AWAIT_BALANCE_SHEET_COMPANY:
        return handleBalanceSheetCompany();
    case STATES.AWAIT_LINK_DOCUMENT:
        return handleLinkDocument();
    case STATES.AGENT_CHAT:
        return handleAgentChatTurn(ctx, text);
    case STATES.DISPATCHER:
        return handleDispatcherTurn(ctx, text);
    default:
        return onMenuResponse(msg, ctx, user);
    }
};

// ── groups ────────────────────────────────────────────────────────────────────
/**
 * Groups deliberately do NOT run the state machine.
 *
 * The bot answers exactly three things in a group: a brand-new participant (welcome), an admin's
 * document or link (intake), and a handful of known menu numbers. Everything else is ignored — the
 * same rule the sim encodes as "never auto-reply in a group", arrived at for the same reason: a bot
 * that answers every line in a six-person group is indistinguishable from a fault.
 *
 * That is also why this bot sets `accepts.groups = true` while still being quiet: the RUNTIME gate is
 * off for it because it genuinely has group work to do, and the silence is enforced here, precisely.
 */
const onGroupMessage = async (msg, ctx, user) => {
    const senderId = ctx.sender.id;
    const text = msg.text;
    const attachment = firstAttachment(msg);
    const messageDate = msg.timestamp instanceof Date ? msg.timestamp : new Date();
    const url = extractUrl(text);

    // group replies never carried the version suffix — preserved
    const groupReply = (t, showMenu = false) => reply(ctx, t, showMenu, { withVersion: false });

    // Auto-reset stale states
    if (AWAITING_STATES.includes(user.state) && user.stateChangedAt && (Date.now() - user.stateChangedAt > stateTimeoutMs(ctx))) {
        await setSubscriberState(senderId, null);
        user.state = null;
    }

    // New user in group → just register, show welcome in group
    if (user.state === STATES.NEW) {
        await setSubscriberState(senderId, null);
        await groupReply(TEXTS.WELCOME_MESSAGE, true);
        return;
    }

    // Auto-intake: documents and links sent in group by admins
    if (await isAdmin(senderId)) {
        if (attachment) {
            try {
                await groupReply(TEXTS.AUTO_INTAKE_DOC);
                const { filePath, caption } = await saveAttachment(attachment);
                const processed = await processGeneralDocument({ textContext: caption || '', filePath, messageDate, senderId });
                return groupReply(processedSummary(TEXTS.GENERIC_DOC_RECEIVED_PREFIX, processed), false);
            } catch (e) {
                console.error('[group-auto-intake-doc]', e);
                return groupReply(TEXTS.ERROR_GENERIC_DOC_PREFIX + e.message, false);
            }
        }
        if (url) {
            try {
                await groupReply(TEXTS.AUTO_INTAKE_LINK);
                const processed = await processLinkDocument({ url, textContext: text || '', messageDate, senderId });
                return groupReply(processedSummary(TEXTS.LINK_DOC_RECEIVED_PREFIX, processed), false);
            } catch (e) {
                console.error('[group-auto-intake-link]', e);
                return groupReply(TEXTS.ERROR_LINK_DOC_PREFIX + e.message, false);
            }
        }
    }

    // For text menu commands in group — only respond to known commands, don't spam on every message
    const choice = (text || '').trim();
    if (['1', '2', '10', '11', '12'].includes(choice)) {
        switch (choice) {
        case '1':
            return groupReply(TEXTS.HELLO_BACK.replace('{name}', user.fullName), true);
        case '2':
            return groupReply(TEXTS.ABOUT_BOT, true);
        case '10':
        case '11':
        case '12':
            if (await isAdmin(senderId)) {
                return groupReply('פעולות מנהל (קליטת מסמכים) זמינות רק בצ\'אט פרטי עם הבוט.', false);
            }
            break;
        }
    }
    // Don't reply to random group messages — only react to known commands, docs, and links
};

// ── the bot ───────────────────────────────────────────────────────────────────
/**
 * @param {object} msg normalised inbound message
 * @param {object} ctx runtime-built context (see bots/README.md)
 */
const onMessage = async (msg, ctx) => {
    try {
        const senderId = ctx.sender && ctx.sender.id;
        if (!senderId) { console.warn('[hacohen-bot] message without a sender id, skipping'); return; }

        // Seed the admin list from THIS CONNECTION's settings before anything asks isAdmin().
        // Done per dispatch rather than at boot because the answer is per connection: the same bot
        // on the public WhatsApp number and on internal chat may have different admins, and a value
        // read once at startup could only ever hold one of them.
        if (ctx.settings && String(ctx.settings.admins || '').trim()) setBotAdmins(ctx.settings.admins);

        // The daily cap is checked BEFORE the subscriber is touched, exactly as before, so a sender
        // who is over the limit cannot keep mutating their own state by spamming.
        if (!manageDailyMessageLimit(senderId, (t) => ctx.send(t), ctx.settings && ctx.settings.dailyMessageLimit)) return;

        const user = await getOrCreateSubscriber(senderId, ctx.sender.name);
        if (ctx.isGroup) return await onGroupMessage(msg, ctx, user);
        return await onUserMessage(msg, ctx, user);
    } catch (e) {
        console.error('[hacohen-bot] error', e);
        Sentry.captureException(e);
    }
};

module.exports = {
    id: 'hacohen-bot',
    name: 'בוט הכהנים',
    desc: 'קליטת מסמכים (חשבוניות, ת. משלוח, דוחות גיול), זיהוי חברה, קליטה מקישור ותפריט מנהל.',
    /**
     * `groups: true`  — it does real work in groups (admin document intake), so the runtime's
     *                   never-in-a-group gate must not fire for it; the precise silence is enforced
     *                   in onGroupMessage above.
     * `chatter: true` — in a DM with this bot a two-character message ("1") IS the payload, so the
     *                   runtime's short-chatter gate would eat the entire menu.
     */
    accepts: { groups: true, chatter: true },
    /**
     * The knobs an operator may turn, per connection, from the chat UI.
     *
     * Only things this bot ACTUALLY reads are here. A setting that renders a control and changes
     * nothing is worse than no setting at all: the operator believes they have adjusted the bot.
     *
     * `accepts.*` is the runtime's convention for overriding an auto-reply gate on one connection —
     * which is how the same bot can be silenced in groups on a public WhatsApp number while it keeps
     * doing group document intake internally, with no redeploy.
     */
    settings: [
        {
            key: 'accepts.groups',
            label: 'לענות בקבוצות',
            hint: 'קליטת מסמכים וקישורים ממנהלים בקבוצות. גם כשפעיל, הבוט מתעלם משיחה רגילה בקבוצה.',
            type: 'boolean',
            default: true,
        },
        {
            key: 'accepts.chatter',
            label: 'לענות להודעות קצרות',
            hint: 'בשיחה פרטית הודעה בת תו אחד ("1") היא בחירה בתפריט — כיבוי כאן ישתיק את התפריט.',
            type: 'boolean',
            default: true,
        },
        {
            // The bot's OWN admin list, in the chat app's own store. It used to live only in an n8n
            // KV reached over a webhook — neither chat's store nor indox's — so who owned the bot's
            // admin list was answered by a third service. Per connection, so the WhatsApp number and
            // internal chat can genuinely have different admins, which one global KV key cannot do.
            // Left empty, the legacy source still speaks: clearing this must not lock a live
            // deployment's admins out.
            key: 'admins',
            label: 'מנהלים (מספרים או מזהי משתמש)',
            hint: 'מופרדים בפסיק. מי שרשום כאן רשאי לקלוט מסמכים ולהריץ פעולות מנהל בחיבור הזה. ריק — נלקח מההגדרות הישנות.',
            type: 'text',
            default: '',
            maxLength: 2000,
        },
        {
            key: 'dailyMessageLimit',
            label: 'מגבלת הודעות יומית לכל משתמש',
            hint: 'מעבר למספר זה נשלחת אזהרה אחת ביום והבוט מפסיק לענות לאותו משתמש.',
            type: 'number',
            default: 100,
            min: 1,
            max: 10000,
        },
        {
            key: 'stateTimeoutHours',
            label: 'איפוס שיחה תלויה (שעות)',
            hint: 'משתמש שהתבקש לשלוח קובץ ולא שלח יחזור לתפריט אחרי הזמן הזה.',
            type: 'number',
            default: 24,
            min: 1,
            max: 720,
        },
    ],
    onMessage,
    // exported for the WhatsApp shim's back-compat surface and for tests
    STATES,
    _internals: { onUserMessage, onGroupMessage, onMenuResponse },
};
