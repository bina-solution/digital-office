/**
 * Group agent: handles @mention of the bot in a WhatsApp group.
 *
 * Flow:
 *  1. extractMention() checks if this message is a bot @mention.
 *  2. Resolve or create per-user session (reply-chain threading).
 *  3. React 👀 + send status message immediately.
 *  4. Stream agent-runner chat turn, emit throttled progress edits.
 *  5. Send final reply and react ✅.
 *
 * Concurrency: each user in the group runs their own independent agent.
 * Same user sending a second request while one is active gets a "still working"
 * message. They can cancel with "!cancel".
 */

const { extractMention } = require('./mention_detector');
const { getSession, trackBotMessage, clearActiveRequest, isBotMessage } = require('./session_manager');
const { ProgressReporter } = require('./progress_reporter');
const { appProperties } = require('../../globals');
const { chatTurn } = require('../../services/agent_chat');
const { automationsTurn } = require('../../services/automations_chat');
const { searchMessages } = require('../../data/wa_archive');
const fs = require('fs');
const path = require('path');

// Cancel keywords (any language)
const CANCEL_PATTERNS = [/^!cancel$/i, /^בטל$/i, /^עצור$/i, /^stop$/i];

// ── Automations agent routing ───────────────────────────────────────
// Keywords that indicate an automation / Google Workspace / document query.
// These get routed to the n8n-powered automations-turn endpoint instead of
// the general chat-turn (Claude Agent SDK).
const AUTOMATION_KEYWORDS = [
    // Hebrew keywords
    'מסמך', 'מסמכים', 'חשבונית', 'חשבוניות', 'ספק', 'דריב', 'דרייב', 'גוגל',
    'גימייל', 'מייל', 'אימייל', 'תייג', 'תיוג', 'תייגים', 'לייבל',
    'פריוריטי', 'נקלט', 'נקלטה', 'שורה', 'גיליון', 'אוטומציה', 'אוטומציות',
    // English keywords  
    'incoming document', 'invoice', 'supplier', 'gmail', 'email label',
    'google sheet', 'automation', 'priority', 'drive', 'spreadsheet',
    'document id', 'document name',
];

const isAutomationQuery = (text) => {
    const lower = (text || '').toLowerCase();
    return AUTOMATION_KEYWORDS.some(kw => lower.includes(kw.toLowerCase()));
};

/**
 * Main entry point. Called from messages.upsert handler.
 * Returns true if the message was handled as a group-agent interaction.
 */
const handleGroupMention = async (sock, msg) => {
    // NEVER respond to our own messages — prevents infinite self-reply loops
    if (msg.key?.fromMe) return false;

    const botPhone = appProperties.botNumber;
    if (!botPhone) return false;

    // Build bot IDs — handle both phone JID and LID (groups can use either)
    const botIds = {
        phone: `${botPhone}@s.whatsapp.net`,
        pushName: sock?.user?.name || sock?.authState?.creds?.me?.name || '',
        lid: (() => {
            const rawLid = sock?.user?.lid || sock?.authState?.creds?.me?.lid;
            if (rawLid) return rawLid.split(':')[0] + '@lid';
            return null;
        })(),
    };

    let mention = extractMention(msg, botIds);

    // If not an @mention, check if this is a reply to a bot message
    // (allows continuing conversation without re-@mentioning)
    if (!mention) {
        const ext = msg.message?.extendedTextMessage || {};
        const quotedId = ext?.contextInfo?.stanzaId;
        const isGroup = msg.key?.remoteJid?.endsWith('@g.us');
        const senderJid = msg.key?.participant || '';

        if (isGroup && senderJid && !msg.key?.fromMe) {
            const rawText = ext?.text || msg.message?.conversation || '';
            // Check 1: proper reply with stanzaId
            if (quotedId && isBotMessage(quotedId) && rawText.trim()) {
                mention = {
                    text: rawText, senderJid, groupJid: msg.key.remoteJid,
                    senderName: msg.pushName || senderJid.split('@')[0],
                    quotedMsgId: quotedId,
                    quotedParticipant: ext?.contextInfo?.participant || null,
                    isGroup: true, mediaType: null, mediaMime: null,
                };
            }
            // Check 2: time-based — user with recent session, no @ in text
            else if (rawText && !rawText.includes('@') && rawText.trim()) {
                const session = getSession(msg.key.remoteJid, senderJid, {});
                if (session && session.agentSessionId) {
                    const elapsed = Date.now() - session.lastActivity;
                    if (elapsed < 5 * 60 * 1000) { // 5 minute window
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

    const { text, senderJid, senderName, groupJid, quotedMsgId } = mention;
    const mentionMedia = { type: mention.mediaType, mime: mention.mediaMime };

    // Resolve session (reply-chain aware)
    const session = getSession(groupJid, senderJid, { quotedMsgId });

    // Check for cancel intent
    if (CANCEL_PATTERNS.some(p => p.test(text))) {
        if (session.activeRequest) {
            session.activeRequest.ac.abort();
            await sock.sendMessage(
                groupJid,
                { text: `✋ *${senderName}*, ביטול הבקשה...` },
                { quoted: { key: msg.key, message: {} } }
            );
        } else {
            await sock.sendMessage(
                groupJid,
                { text: `ℹ️ אין בקשה פעילה לביטול.` },
                { quoted: { key: msg.key, message: {} } }
            );
        }
        return true;
    }

    // Already running for this user?
    if (session.activeRequest) {
        const elapsedSec = Math.round((Date.now() - session.activeRequest.startTs) / 1000);
        await sock.sendMessage(
            groupJid,
            { text: `⏳ *${senderName}*, עדיין עובד על הבקשה הקודמת שלך (${elapsedSec}s).\nשלח !cancel לביטול.` },
            { quoted: { key: msg.key, message: {} } }
        );
        return true;
    }

    if (!text) {
        await sock.sendMessage(
            groupJid,
            { text: `היי *${senderName}*! 👋 כתוב לי שאלה או בקשה לאחר ה-@.` },
            { quoted: { key: msg.key, message: {} } }
        );
        return true;
    }

    // ── Start the agent request ──────────────────────────────────────────────
    const ac = new AbortController();
    const reporter = new ProgressReporter(sock, groupJid, msg.key, senderJid, senderName);

    session.activeRequest = { ac, startTs: Date.now() };

    try {
    // ── Determine base agent message early ────────────────────────────────────
    let agentMessage = text;

    // ── Look up quoted message for context (reply to any message) ──────────────
    if (quotedMsgId && !mentionMedia.type) {
        try {
            const quotedMsgs = await searchMessages({ chatJid: groupJid, limit: 50 });
            const quoted = quotedMsgs.find(m => m.message_id === quotedMsgId);
            if (quoted) {
                const raw = JSON.parse(quoted.raw_json || '{}');
                const msgTypes = Object.keys(raw.message || {}).filter(k => k.endsWith('Message'));
                const mediaType = msgTypes.find(k => ['imageMessage','videoMessage','documentMessage','audioMessage'].includes(k));
                if (mediaType) {
                    const typeName = mediaType.replace('Message', '');
                    const typeLabel = typeName === 'image' ? 'תמונה' : typeName === 'audio' ? 'הקלטה' : typeName;
                    // Note: can't re-download old media, but tell agent what was in the quoted msg
                    agentMessage = text
                        + `\n\n[User is replying to a ${typeLabel} attachment`;
                    if (quoted.text) agentMessage += ` with caption: "${quoted.text.slice(0, 200)}"`;
                    agentMessage += `. Look in /wa_media/ for files matching this timestamp (${quoted.message_ts}). If found, use the Read tool. Otherwise, explain that the media may have expired.]`;
                    console.log(`[group-agent] reply to ${typeName} detected`);
                } else if (quoted.text) {
                    agentMessage = text + `\n\n[User is replying to message: "${quoted.text.slice(0, 300)}"]`;
                }
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
            const MAX_BYTES = 10 * 1024 * 1024; // 10 MB cap
            if (buffer && buffer.length <= MAX_BYTES) {
                imageData = {
                    data: buffer.toString('base64'),
                    media_type: mentionMedia.mime || 'image/jpeg',
                };
                console.log(`[group-agent] downloaded image: ${(buffer.length / 1024).toFixed(1)}KB ${mentionMedia.mime || ''}`);
            } else if (buffer) {
                console.log(`[group-agent] image too large: ${(buffer.length / 1024).toFixed(1)}KB (max 10MB), skipping`);
            }
        } catch (e) {
            console.warn('[group-agent] image download failed:', e.message);
        }
    }
    if (mentionMedia.type === 'image' && !imageData) {
        agentMessage = `[User sent an image that could not be processed. Ask them to describe it. User says: ${text}]`;
    }

    // ── Handle links/URLs in the message ──────────────────────────────────────
    const urlRegex = /https?:\/\/[^\s]+/g;
    const urls = text.match(urlRegex) || [];
    if (urls.length > 0 && !mentionMedia.type) {
        agentMessage = `[Links in message: ${urls.join(', ')}]\n\nUser says: ${text}\n\nUse curl or fetch to get the content of these links and summarize. Respond in English.`;
        console.log('[group-agent] detected ' + urls.length + ' URLs:', urls.join(', '));
    }

    // Phase 1 & 2: ack + status
    await reporter.ack();
    await reporter.sendStatus(text || `📎 ${mentionMedia.type} attachment`);

    // ── Inject conversation context for replies and media context ──────────────
    // Always look at recent messages to provide context about nearby media
    try {
        const recent = await searchMessages({ chatJid: groupJid, limit: 6 });
        // Check if any recent message has media that the user might be asking about
        const mediaContext = [];
        const lines = [];
        for (const m of recent) {
            if (m.message_type === 'protocolMessage' || m.message_type === 'reactionMessage') continue;
            const who = m.from_me ? 'Bot' : (m.sender_jid || '').split('@')[0];
            if (m.message_type === 'imageMessage' || m.message_type === 'audioMessage' ||
                m.message_type === 'videoMessage' || m.message_type === 'documentMessage') {
                const mediaLabel = m.message_type === 'audioMessage' ? 'Voice Note' :
                    m.message_type === 'imageMessage' ? 'Photo' : m.message_type.replace('Message', '');
                mediaContext.push(`${who} sent a ${mediaLabel} (mime: ${m.media_mime || 'unknown'})`);
            } else {
                const txt = (m.text || '').slice(0, 200);
                if (txt) lines.push(`${who}: ${txt}`);
            }
        }
        if (lines.length > 0 || mediaContext.length > 0) {
            const ctx = [...mediaContext, ...lines].join('\n');
            const prefix = quotedMsgId ? 'Group conversation context' : 'Recent messages in this chat';
            agentMessage = `[${prefix}:\n${ctx}\n]\n\nCurrent user says: ${agentMessage}`;
        }
    } catch (e) { /* non-fatal */ }

    // ── Route to automations agent for workspace/document queries ──────
    const useAutomationAgent = isAutomationQuery(agentMessage);
    if (useAutomationAgent) {
        console.log('[group-agent] routing to automations agent:', agentMessage.slice(0, 100));
    }

    try {
        const turnFn = useAutomationAgent ? automationsTurn : chatTurn;
        const result = await turnFn({
            sessionId: session.agentSessionId,
            message: agentMessage,
            images: imageData ? [imageData] : undefined,
            context: useAutomationAgent ? {
                senderName: senderName || undefined,
                groupName: groupJid || undefined,
            } : undefined,
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
            await reporter.sendError('בוטל');
            return true;
        }

        // Save session ID for next turn
        if (result.sessionId) {
            session.agentSessionId = result.sessionId;
        }

        // Phase 4: final answer — prefer error info over generic fallback
        const replyText = result.text
            || (result.error ? `[${result.errorKind || 'err'}] ${result.error}` : '')
            || (mentionMedia.type === 'audio' ? 'Received voice note — cannot transcribe audio. Please send text.'
                : mentionMedia.type === 'image' ? 'Received image — this model cannot analyze images directly. Try describing it or use /model sonnet.'
                : mentionMedia.type === 'video' ? 'Received video — cannot analyze video content.'
                : mentionMedia.type ? `Received ${mentionMedia.type} — cannot process this attachment type.`
                : 'No response — try again or use !cancel');
        const finalMsgKey = await reporter.sendFinalAnswer(replyText);
        if (finalMsgKey) {
            trackBotMessage(finalMsgKey.id, groupJid, senderJid);
        }

    } catch (err) {
        if (!ac.signal.aborted) {
            console.error('[group-agent] error:', err.message);
            await reporter.sendError(err.message?.slice(0, 80) || 'agent error');
        }
    }
    } finally {
        clearActiveRequest(session);
    }

    return true;
};

module.exports = { handleGroupMention };
