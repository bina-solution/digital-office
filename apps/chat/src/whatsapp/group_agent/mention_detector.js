/**
 * Detects @mentions of the bot in group messages including media attachments.
 *
 * Supports: extendedText, conversation, imageMessage, videoMessage, documentMessage
 */

const extractMention = (msg, botIds) => {
    if (!msg?.message) return null;

    const groupJid = msg.key?.remoteJid;
    if (!groupJid?.endsWith('@g.us')) return null;

    const senderJid = msg.key?.participant || msg.participant || '';
    const senderName = msg.pushName || senderJid.split('@')[0];

    const botPhone = botIds.phone.split('@')[0];
    const botLid   = botIds.lid ? botIds.lid.split('@')[0] : null;

    // ── Collect text and context info from any message type ──────────────
    let rawText = '', ctxInfo = {}, mediaType = null, mediaMime = null;

    const ext = msg.message.extendedTextMessage;
    const conv = msg.message.conversation;
    if (ext) { rawText = ext.text || ''; ctxInfo = ext.contextInfo || {}; }
    else if (conv) { rawText = conv; }

    const mediaTypes = ['imageMessage', 'videoMessage', 'documentMessage', 'audioMessage'];
    for (const mt of mediaTypes) {
        const m = msg.message[mt];
        if (m) {
            mediaType = mt.replace('Message', '');
            mediaMime = m.mimetype || null;
            rawText = m.caption || rawText;
            ctxInfo = m.contextInfo || ctxInfo;
            break;
        }
    }

    if (!rawText) return null;

    // ── Strategy 1: contextInfo.mentionedJid ─────────────────────────────
    const mentionedJids = ctxInfo?.mentionedJid || [];
    const hasStructuredMention = mentionedJids.some(j => {
        const user = j.split('@')[0];
        return user === botPhone || (botLid && user === botLid);
    });

    // ── Strategy 2: Text fallback (@phone or @lid or @botName) ─────────
    const patterns = [new RegExp(`@${botPhone}\\b`, 'i')];
    if (botLid) patterns.push(new RegExp(`@${botLid}\\b`, 'i'));
    // Also match Hebrew/display name mentions (e.g. @בוט הכהנים)
    if (botIds.pushName) patterns.push(new RegExp(`@${botIds.pushName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'i'));
    const hasTextMention = patterns.some(p => p.test(rawText));

    if (!hasStructuredMention && !hasTextMention) return null;

    // ── Clean the text ──────────────────────────────────────────────────
    let text = rawText;
    text = text.replace(new RegExp(`@${botPhone}\\s*`, 'g'), '');
    if (botLid) text = text.replace(new RegExp(`@${botLid}\\s*`, 'g'), '');
    text = text.trim() || '(media attachment)';

    const quotedMsgId = ctxInfo?.stanzaId || null;
    const quotedParticipant = ctxInfo?.participant || null;

    return {
        text,
        senderJid,
        senderName,
        groupJid,
        quotedMsgId,
        quotedParticipant,
        isGroup: true,
        mediaType: mediaType || null,
        mediaMime: mediaMime || null,
    };
};

module.exports = { extractMention };
