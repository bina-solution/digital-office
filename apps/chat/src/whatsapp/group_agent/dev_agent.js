/**
 * Dev Agent: handles @mention in the "dev agent" WhatsApp group.
 *
 * Similar to group_agent.js but with:
 *  - Full read-write access to the production server
 *  - Multi-session dispatcher for long-running dev processes
 *  - Issue tracking & management
 *  - Longer session TTL (24h)
 *  - Uses /dev-turn endpoint on agent-runner
 *
 * Flow:
 *  1. extractMention() checks if this message is a bot @mention.
 *  2. Resolve or create per-user session (24h TTL).
 *  3. React 👀 + send status message immediately.
 *  4. Stream dev-agent chat turn, emit throttled progress edits.
 *  5. Send final reply and react ✅.
 */

const { extractMention } = require('./mention_detector');
const { ProgressReporter } = require('./progress_reporter');
const { appProperties } = require('../../globals');
const { devTurn } = require('../../services/dev_agent_client');
const { searchMessages } = require('../../data/wa_archive');
const fs = require('fs');
const path = require('path');

// Cancel keywords
const CANCEL_PATTERNS = [/^!cancel$/i, /^בטל$/i, /^עצור$/i, /^stop$/i];

// ─── Dev Session Store ─────────────────────────────────────────────────────

const DEV_SESSION_TTL_MS = 24 * 60 * 60 * 1000; // 24 hours idle
const DEV_BOT_MSG_TRACKER_SIZE = 1000;

/** @type {Map<string, DevSession>} */
const devSessions = new Map();
const devBotMsgs = new Map(); // botMsgId -> sessionKey

const devSessionKey = (groupJid, userJid) => `${groupJid}:${userJid}`;

const pruneDevSessions = () => {
    const cutoff = Date.now() - DEV_SESSION_TTL_MS;
    for (const [key, s] of devSessions) {
        if (s.lastActivity < cutoff && !s.activeRequest) {
            devSessions.delete(key);
        }
    }
};
setInterval(pruneDevSessions, 15 * 60 * 1000);

const getDevSession = (groupJid, userJid, { quotedMsgId } = {}) => {
    if (quotedMsgId) {
        const ownerKey = devBotMsgs.get(quotedMsgId);
        if (ownerKey) {
            const ownerSession = devSessions.get(ownerKey);
            if (ownerSession && ownerKey === devSessionKey(groupJid, userJid)) {
                ownerSession.lastActivity = Date.now();
                return ownerSession;
            }
        }
    }
    const key = devSessionKey(groupJid, userJid);
    if (!devSessions.has(key)) {
        devSessions.set(key, {
            key, groupJid, userJid,
            agentSessionId: null,
            activeRequest: null,
            lastActivity: Date.now(),
            issues: [],       // tracked issues for this dev
            model: 'deepseek-chat',  // default (dual-backend: deepseek-* → DS, claude-* → Anthropic)
            totalCost: 0,
            turnCount: 0,
        });
    }
    const s = devSessions.get(key);
    s.lastActivity = Date.now();
    return s;
};

const trackDevBotMessage = (msgId, groupJid, userJid) => {
    const key = devSessionKey(groupJid, userJid);
    if (devBotMsgs.size >= DEV_BOT_MSG_TRACKER_SIZE) {
        const oldest = devBotMsgs.keys().next().value;
        devBotMsgs.delete(oldest);
    }
    devBotMsgs.set(msgId, key);
};

const clearDevActiveRequest = (session) => {
    session.activeRequest = null;
};

const isDevBotMessage = (msgId) => devBotMsgs.has(msgId);

// ─── Issue tracking helpers ───────────────────────────────────────────────

let nextIssueId = 1;
const addIssue = (session, title, description, reporter) => {
    const issue = {
        id: nextIssueId++,
        title,
        description: description || '',
        reporter: reporter || session.userJid.split('@')[0],
        status: 'open',
        createdAt: new Date().toISOString(),
        completedAt: null,
    };
    session.issues.push(issue);
    return issue;
};

const formatIssues = (issues) => {
    if (!issues.length) return 'no open issues';
    return issues.map(i => {
        const status = i.status === 'done' ? 'done' : i.status === 'in-progress' ? 'active' : 'open';
        return `#${i.id} | ${status} | ${i.title} | ${i.reporter}`;
    }).join('\n');
};

// ─── Special command handlers ─────────────────────────────────────────────

const specialCommands = {
    '!status': async (sock, session, msg, senderName) => {
        const active = session.activeRequest ? 'active' : 'idle';
        const cost = session.totalCost > 0 ? ` | $${session.totalCost.toFixed(4)} (${session.turnCount}t)` : '';
        const lines = [
            `*${senderName}* — ${active} | model: ${session.model}${cost}`,
            formatIssues(session.issues)
        ];
        await sock.sendMessage(
            session.groupJid,
            { text: lines.filter(Boolean).join('\n') },
            { quoted: { key: msg.key, message: {} } }
        );
        return true;
    },

    '!issues': async (sock, session, msg, senderName) => {
        await sock.sendMessage(
            session.groupJid,
            { text: `*${senderName}*\n${formatIssues(session.issues)}` },
            { quoted: { key: msg.key, message: {} } }
        );
        return true;
    },

    '!health': async (sock, session, msg, senderName) => {
        session._pendingHealth = true;
        return false;
    },

    '!model': async (sock, session, msg, senderName) => {
        await sock.sendMessage(
            session.groupJid,
            { text: `*${senderName}* — model: *${session.model}* | available: deepseek-chat | switch: !model <name>` },
            { quoted: { key: msg.key, message: {} } }
        );
        return true;
    },
};

// ─── Main handler ──────────────────────────────────────────────────────────

/**
 * @param {object} sock - Baileys socket
 * @param {object} msg - WhatsApp message object
 * @returns {Promise<boolean>} true if handled
 */
const handleDevMention = async (sock, msg) => {
    if (msg.key?.fromMe) return false;

    const botPhone = appProperties.botNumber;
    if (!botPhone) return false;

    const botIds = {
        phone: `${botPhone}@s.whatsapp.net`,
        pushName: sock?.user?.name || sock?.authState?.creds?.me?.name || '',
        lid: (() => {
            const rawLid = sock?.user?.lid || sock?.authState?.creds?.me?.lid;
            if (rawLid) return rawLid.split(':')[0] + '@lid';
            return null;
        })(),
    };

    // Get the configured dev group JID
    const devGroupJid = process.env.DEV_GROUP_JID || '';
    if (!devGroupJid) {
        console.log('[dev-agent] DEV_GROUP_JID not configured, skipping');
        return false;
    }

    // Only handle messages from the dev group
    if (msg.key?.remoteJid !== devGroupJid) return false;

    let mention = extractMention(msg, botIds);

    // Also handle replies to bot messages and continuation
    if (!mention) {
        const ext = msg.message?.extendedTextMessage || {};
        const quotedId = ext?.contextInfo?.stanzaId;
        const senderJid = msg.key?.participant || '';

        if (senderJid && !msg.key?.fromMe) {
            const rawText = ext?.text || msg.message?.conversation || '';

            // Check 1: reply to bot message
            if (quotedId && isDevBotMessage(quotedId) && rawText.trim()) {
                mention = {
                    text: rawText, senderJid, groupJid: msg.key.remoteJid,
                    senderName: msg.pushName || senderJid.split('@')[0],
                    quotedMsgId: quotedId,
                    quotedParticipant: ext?.contextInfo?.participant || null,
                    isGroup: true, mediaType: null, mediaMime: null,
                };
            }
            // Check 2: time-based continuation (10 min window for dev)
            else if (rawText && !rawText.includes('@') && rawText.trim()) {
                const session = getDevSession(msg.key.remoteJid, senderJid, {});
                if (session && session.agentSessionId) {
                    const elapsed = Date.now() - session.lastActivity;
                    if (elapsed < 10 * 60 * 1000) {
                        mention = {
                            text: rawText, senderJid, groupJid: msg.key.remoteJid,
                            senderName: msg.pushName || senderJid.split('@')[0],
                            quotedMsgId: null, quotedParticipant: null,
                            isGroup: true, mediaType: null, mediaMime: null,
                        };
                    }
                }
            }
        }
        if (!mention) return false;
    }

    const { text: rawText, senderJid, senderName, groupJid, quotedMsgId } = mention;
    const mentionMedia = { type: mention.mediaType, mime: mention.mediaMime };

    const session = getDevSession(groupJid, senderJid, { quotedMsgId });
    const text = rawText || '';

    // ── Check special commands ──────────────────────────────────────────

    // !model switch
    const modelMatch = text.match(/^!model\s+([a-z0-9][a-z0-9-]{1,80})$/i);
    if (modelMatch) {
        const allowed = ['deepseek-chat', 'deepseek-reasoner', 'deepseek-v4-flash', 'deepseek-v4-pro', 'haiku', 'sonnet', 'opus', 'claude-haiku-4-6', 'claude-sonnet-4-6', 'claude-opus-4-6'];
        const req = modelMatch[1].toLowerCase();
        const found = allowed.find(a => a === req || a.includes(req));
        if (found) {
            session.model = found;
            await sock.sendMessage(groupJid, { text: `*${senderName}* — model switched to *${found}*` }, { quoted: { key: msg.key, message: {} } });
        } else {
            await sock.sendMessage(groupJid, { text: `*${senderName}* — unknown model. Available: ${allowed.slice(0,3).join(' ')}` }, { quoted: { key: msg.key, message: {} } });
        }
        return true;
    }

    // Other special commands
    for (const [cmd, handler] of Object.entries(specialCommands)) {
        if (text === cmd || text.startsWith(cmd + ' ')) {
            const handled = await handler(sock, session, msg, senderName);
            if (handled) return true;
        }
    }

    // ── Cancel check ────────────────────────────────────────────────────
    if (CANCEL_PATTERNS.some(p => p.test(text))) {
        if (session.activeRequest) {
            session.activeRequest.ac.abort();
            await sock.sendMessage(groupJid, { text: `*${senderName}* — cancelled` }, { quoted: { key: msg.key, message: {} } });
        } else {
            await sock.sendMessage(groupJid, { text: `*${senderName}* — nothing to cancel` }, { quoted: { key: msg.key, message: {} } });
        }
        return true;
    }

    // ── Busy check ─────────────────────────────────────────────────────
    if (session.activeRequest) {
        const elapsedSec = Math.round((Date.now() - session.activeRequest.startTs) / 1000);
        await sock.sendMessage(
            groupJid,
            { text: `*${senderName}* — busy (${elapsedSec}s). Send !cancel to abort.` },
            { quoted: { key: msg.key, message: {} } }
        );
        return true;
    }

    if (!text) {
        await sock.sendMessage(
            groupJid,
            { text: `*${senderName}* — dev agent ready.\nCommands: !status !issues !health !deploy !logs !pr !push !model !cancel` },
            { quoted: { key: msg.key, message: {} } }
        );
        return true;
    }

    // ── Build agent message ─────────────────────────────────────────────
    let agentMessage = text;

    // Non-image media: can't download, inform agent via text
    if (mentionMedia.type && mentionMedia.type !== 'image') {
        agentMessage = `[User sent ${mentionMedia.type} attachment. User says: ${text}]`;
    }

    // Add issue context if !issue command
    const issueMatch = text.match(/^!issue\s+#?(\d+)/i);
    if (issueMatch) {
        const id = parseInt(issueMatch[1]);
        const issue = session.issues.find(i => i.id === id);
        if (issue) {
            agentMessage = `[Looking at issue #${id}: "${issue.title}" — status: ${issue.status}]\n\nUser says: ${text}`;
        }
    }

    // Add !done command handling
    const doneMatch = text.match(/^!done\s+#?(\d+)/i);
    if (doneMatch) {
        const id = parseInt(doneMatch[1]);
        const issue = session.issues.find(i => i.id === id);
        if (issue) {
            issue.status = 'done';
            issue.completedAt = new Date().toISOString();
            agentMessage = `[Issue #${id} marked as done by user: "${issue.title}"]\n\nUser says: ${text}`;
        }
    }

    // Handle !deploy command
    const deployMatch = text.match(/^!deploy\s+([a-z0-9-]+)/i);
    if (deployMatch) {
        const service = deployMatch[1];
        agentMessage = `[DEPLOY COMMAND] User wants to deploy/restart service: ${service}. Run: docker compose -f /workspace/compose.yml -f /workspace/compose.override.yaml up -d ${service} 2>&1. Check status after. If the service name is wrong, suggest correct names from docker ps. Respond in English.]`;
    }

    // Handle !logs command
    const logsMatch = text.match(/^!logs\s+([a-z0-9-]+)/i);
    if (logsMatch) {
        const service = logsMatch[1];
        agentMessage = `[LOGS COMMAND] User wants logs for: ${service}. Run: docker logs --tail 50 ${service}-bina-deployment 2>&1. Respond in English.`;
    }

    // Handle !pr command
    const prMatch = text.match(/^!pr\s+(.+)/i);
    if (prMatch) {
        const prTitle = prMatch[1];
        agentMessage = `[PR COMMAND] User wants to create a PR titled: "${prTitle}". First run: git status && git diff --stat && git branch --show-current. Then summarize changes and ask if ready to push. Respond in English.`;
    }

    // Handle !push command
    if (text.trim() === '!push') {
        agentMessage = `[PUSH COMMAND] User wants to push current branch. Run: git branch --show-current && git status && git log --oneline -5. Show what would be pushed and ask confirmation. Respond in English.`;
    }

    // ── Look up quoted message context ──────────────────────────────────
    if (quotedMsgId && !mentionMedia.type) {
        try {
            const quotedMsgs = await searchMessages({ chatJid: groupJid, limit: 50 });
            const quoted = quotedMsgs.find(m => m.message_id === quotedMsgId);
            if (quoted && quoted.text) {
                agentMessage = text + `\n\n[User replying to: "${quoted.text.slice(0, 300)}"]`;
            }
        } catch (e) { /* non-fatal */ }
    }

    // ── Download image attachment if present ──────────────────────────────
    let imageData = null;
    if (mentionMedia.type === 'image' && msg.message?.imageMessage) {
        try {
            const { downloadContentFromMessage } = require('baileys');
            const imgMsg = msg.message.imageMessage;
            const stream = await downloadContentFromMessage(imgMsg, 'image');
            let buffer = Buffer.from([]);
            for await (const chunk of stream) buffer = Buffer.concat([buffer, chunk]);
            const MAX_BYTES = 10 * 1024 * 1024;
            if (buffer && buffer.length <= MAX_BYTES) {
                imageData = {
                    data: buffer.toString('base64'),
                    media_type: mentionMedia.mime || 'image/jpeg',
                };
                console.log(`[dev-agent] downloaded image: ${(buffer.length / 1024).toFixed(1)}KB ${mentionMedia.mime || ''}`);
            } else if (buffer) {
                console.log(`[dev-agent] image too large: ${(buffer.length / 1024).toFixed(1)}KB (max 10MB), skipping`);
            }
        } catch (e) {
            console.warn('[dev-agent] image download failed:', e.message);
        }
    }
    // Fallback: inform agent if image was present but couldn't be analyzed
    if (mentionMedia.type === 'image' && !imageData) {
        agentMessage = `[User sent an image but analysis failed. If they need vision analysis, suggest switching to a Claude model (sonnet/opus). User says: ${text}]`;
    }

    // ── Handle URLs ─────────────────────────────────────────────────────
    const urlRegex = /https?:\/\/[^\s]+/g;
    const urls = text.match(urlRegex) || [];
    if (urls.length > 0 && !mentionMedia.type) {
        agentMessage = `[Links: ${urls.join(', ')}]\n\nUser says: ${text}\n\nFetch and analyze these links if relevant. Respond in English.`;
    }

    // ── Start agent request ─────────────────────────────────────────────
    const ac = new AbortController();
    const reporter = new ProgressReporter(sock, groupJid, msg.key, senderJid, senderName);

    session.activeRequest = { ac, startTs: Date.now() };

    try {
    // Inject recent conversation context
    try {
        const recent = await searchMessages({ chatJid: groupJid, limit: 8 });
        const ctxLines = [];
        for (const m of recent) {
            if (m.message_type === 'protocolMessage' || m.message_type === 'reactionMessage') continue;
            const who = m.from_me ? 'Bot' : (m.sender_jid || '').split('@')[0];
            const txt = (m.text || '').slice(0, 200);
            if (txt) ctxLines.push(`${who}: ${txt}`);
        }
        if (ctxLines.length > 0) {
            const prefix = quotedMsgId ? 'Group conversation context' : 'Recent messages';
            agentMessage = `[${prefix}:\n${ctxLines.join('\n')}\n]\n\nCurrent user (${senderName}) says: ${agentMessage}`;
        }
    } catch (e) { /* non-fatal */ }

    // Ack + status
    await reporter.ack();
    await reporter.sendStatus(text || `📎 ${mentionMedia.type} attachment`);

    try {
        const result = await devTurn({
            sessionId: session.agentSessionId,
            message: agentMessage,
            images: imageData ? [imageData] : undefined,
            model: session.model,
            onProgress: (evt) => {
                if (ac.signal.aborted) return;
                if (evt.kind === 'session') {
                    session.agentSessionId = evt.sessionId;
                } else if (evt.kind === 'tool_use') {
                    reporter.onToolStart(evt.name, evt.input);
                } else if (evt.kind === 'tool_result') {
                    reporter.onToolResult(evt.preview, evt.isError);
                }
            },
        });

        if (ac.signal.aborted) {
            await reporter.sendError('cancelled');
            return true;
        }

        if (result.sessionId) {
            session.agentSessionId = result.sessionId;
        }

        // Track cost
        session.turnCount += 1;
        if (result.stats && typeof result.stats.total_cost_usd === 'number') {
            session.totalCost += result.stats.total_cost_usd;
        }

        const replyText = result.text || (result.error ? `[${result.errorKind || 'err'}] ${result.error}` : 'no response');
        const finalMsgKey = await reporter.sendFinalAnswer(replyText);
        if (finalMsgKey) {
            trackDevBotMessage(finalMsgKey.id, groupJid, senderJid);
        }

    } catch (err) {
        if (!ac.signal.aborted) {
            console.error('[dev-agent] error:', err.message);
            await reporter.sendError(err.message?.slice(0, 80) || 'agent error');
        }
    }
    } finally {
        clearDevActiveRequest(session);
    }

    return true;
};

module.exports = { handleDevMention, getDevSession, addIssue };
