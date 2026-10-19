/**
 * In-memory session store for per-user group agent conversations.
 *
 * Session key: `<groupJid>:<userJid>`
 * Each session tracks:
 *  - agentSessionId: the agent-runner Claude session ID (persists conversation)
 *  - activeRequest:  currently running agent, or null
 *  - lastActivity:   for TTL expiry
 *
 * BotMessageTracker maps botMsgId → sessionKey, so reply-chains
 * are routed to the right user's session automatically.
 */

const SESSION_TTL_MS = 30 * 60 * 1000; // 30 minutes idle
const BOT_MSG_TRACKER_SIZE = 500;       // max tracked bot messages

// sessionKey → Session
const sessions = new Map();

// botMsgId → sessionKey  (LRU by insertion order, capped at BOT_MSG_TRACKER_SIZE)
const botMsgToSession = new Map();

const sessionKey = (groupJid, userJid) => `${groupJid}:${userJid}`;

const pruneExpired = () => {
    const cutoff = Date.now() - SESSION_TTL_MS;
    for (const [key, s] of sessions) {
        if (s.lastActivity < cutoff && !s.activeRequest) {
            sessions.delete(key);
        }
    }
};

// Periodic cleanup every 5 minutes
setInterval(pruneExpired, 5 * 60 * 1000);

/**
 * Get or create a session for this user in this group.
 */
const getSession = (groupJid, userJid, { quotedMsgId } = {}) => {
    // If the user replied to a bot message, find whose session it belongs to
    if (quotedMsgId) {
        const ownerKey = botMsgToSession.get(quotedMsgId);
        if (ownerKey) {
            const ownerSession = sessions.get(ownerKey);
            if (ownerSession && ownerKey === sessionKey(groupJid, userJid)) {
                // Same user replying to their own bot message → continue session
                ownerSession.lastActivity = Date.now();
                return ownerSession;
            }
            // Different user or stale session → fall through
        }
    }

    const key = sessionKey(groupJid, userJid);
    if (!sessions.has(key)) {
        sessions.set(key, {
            key,
            groupJid,
            userJid,
            agentSessionId: null,   // populated by agent-runner on first turn
            activeRequest: null,    // { ac: AbortController, statusMsgKey, startTs }
            lastActivity: Date.now(),
        });
    }
    const s = sessions.get(key);
    s.lastActivity = Date.now();
    return s;
};

/**
 * Record that the bot sent a message, so future replies can route back here.
 */
const trackBotMessage = (msgId, groupJid, userJid) => {
    const key = sessionKey(groupJid, userJid);
    // Keep map bounded by FIFO eviction
    if (botMsgToSession.size >= BOT_MSG_TRACKER_SIZE) {
        const oldest = botMsgToSession.keys().next().value;
        botMsgToSession.delete(oldest);
    }
    botMsgToSession.set(msgId, key);
};

const clearActiveRequest = (session) => {
    session.activeRequest = null;
};

/**
 * Check if a message ID was sent by the bot (tracked for reply routing).
 */
const isBotMessage = (msgId) => botMsgToSession.has(msgId);

module.exports = { getSession, trackBotMessage, clearActiveRequest, isBotMessage };
