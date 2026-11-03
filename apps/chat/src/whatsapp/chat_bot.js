/**
 * WhatsApp → bot-runtime adapter.
 *
 * This file used to BE the bot: 1068 lines of document intake, agent jobs and subscriber state, with
 * `require('./send')` at the top and Baileys message shapes read inline. The bot moved to
 * `apps/chat/bots/hacohen-bot/`; what is left here is the only part that was ever really about
 * WhatsApp, and it is the part that must stay:
 *
 *   · JID routing — `@g.us` is a group, `@s.whatsapp.net` is a DM, `@lid` is neither until you resolve
 *     it through `remoteJidAlt`/`participantAlt`. No other transport has this problem and no bot
 *     should ever have had to know about it.
 *   · Message shape — `conversation` vs `extendedTextMessage.text` vs a caption on a document nested
 *     inside `documentWithCaptionMessage`. Flattened here into `msg.text` + `msg.attachments`.
 *   · Media bytes — `downloadContentFromMessage` is a Baileys API. It is closed over inside
 *     `attachment.download()` so the bot can ask for bytes without importing a driver.
 *   · Reactions and presence — `{react:{...}}` and `sendPresenceUpdate` are Baileys calls, offered to
 *     the runtime as OPTIONAL capabilities that degrade to no-ops elsewhere.
 *
 * `onMessage(sock, message)` keeps its old signature, so `baileyes_app.js` is unchanged and the live
 * bot keeps working. Under it, the message is normalised and handed to the runtime, which decides
 * which bot (if any) is attached to this connection.
 */
const { toWhatsAppJid } = require('../utils/phone');
const { sendTextMessage, sendLongTextMessage } = require('./send');
const runtime = require('../../bots/chat_bot');
const hacohenBot = require('../../bots/hacohen-bot');
const { Sentry } = require('../services/sentry');

/**
 * The connection id this transport reports to the runtime.
 *
 * A constant for now because there is exactly one Baileys pairing; when the connections service owns
 * WhatsApp instances this becomes the real connection id and nothing else here changes. It matches
 * the key in the runtime's DEFAULT_ATTACHMENTS, which is what keeps the live number answered.
 */
const WA_CONNECTION_ID = process.env.CHAT_WA_CONNECTION_ID || 'wa-baileys';

// Baileys v7 is ESM-only, use dynamic import with cache
let baileysModule = null;
const loadBaileys = async () => {
    if (!baileysModule) baileysModule = await import('baileys');
    return baileysModule;
};

// Recursively unwrap nested future-proof / withCaption message containers to locate a document/image payload
const unwrapMediaContainer = (messageNode) => {
    if (!messageNode) return null;
    if (messageNode.documentMessage || messageNode.imageMessage) return messageNode;
    if (messageNode.documentWithCaptionMessage) return unwrapMediaContainer(messageNode.documentWithCaptionMessage.message);
    if (messageNode.imageWithCaptionMessage) return unwrapMediaContainer(messageNode.imageWithCaptionMessage.message);
    return null;
};

/** Textual content of a Baileys message, in the two forms WhatsApp actually sends. */
const extractMessageText = (message) =>
    message?.message?.conversation || message?.message?.extendedTextMessage?.text || null;

/**
 * Normalised attachments for a Baileys message (0 or 1 — WhatsApp carries one per message).
 * `download()` closes over the Baileys stream API; that closure IS the seam.
 */
const attachmentsOf = (message) => {
    const container = unwrapMediaContainer(message?.message);
    if (!container) return [];
    const node = container.documentMessage || container.imageMessage;
    const kind = container.documentMessage ? 'document' : 'image';
    return [{
        kind,
        fileName: node.fileName || null,
        mimeType: node.mimetype || null,
        caption: node.caption || '',
        size: Number(node.fileLength || 0) || null,
        download: async () => {
            const { downloadContentFromMessage } = await loadBaileys();
            const stream = await downloadContentFromMessage(node, kind);
            let buffer = Buffer.from([]);
            for await (const chunk of stream) buffer = Buffer.concat([buffer, chunk]);
            return buffer;
        },
    }];
};

/**
 * Resolve the addressing of an inbound Baileys message.
 * @returns {{conversationId:string, isGroup:boolean, senderId:string}|null} null == not ours to handle
 *          (broadcast, unresolvable LID, missing participant) — exactly the cases the old router
 *          logged and skipped.
 */
const routeOf = (message) => {
    const jid = message?.key?.remoteJid || '';
    const altJid = message?.key?.remoteJidAlt || '';

    // LID-addressed messages: resolve via remoteJidAlt to get the real phone/group JID first.
    let convJid = jid;
    if (jid.endsWith('@lid')) {
        if (altJid.endsWith('@s.whatsapp.net') || altJid.endsWith('@g.us')) {
            convJid = altJid;
        } else {
            console.log(`[wa-adapter] LID message without usable alt JID, skipping: ${jid}`);
            return null;
        }
    }

    if (convJid.endsWith('@g.us')) {
        let participantJid = message?.key?.participant || '';
        if (participantJid.endsWith('@lid')) {
            const altPart = message?.key?.participantAlt || '';
            if (altPart.endsWith('@s.whatsapp.net')) {
                participantJid = altPart;
            } else {
                console.warn(`[wa-adapter] LID participant without usable alt, skipping: ${participantJid}`);
                return null;
            }
        }
        const senderId = participantJid ? participantJid.split('@')[0] : null;
        if (!senderId) { console.warn('[wa-adapter] group message without participant, skipping'); return null; }
        return { conversationId: convJid, isGroup: true, senderId };
    }

    if (convJid.endsWith('@s.whatsapp.net')) {
        return { conversationId: convJid, isGroup: false, senderId: convJid.split('@')[0] };
    }

    // Broadcasts (@broadcast) and unknown JID types are not ours.
    return null;
};

/** Baileys message -> the normalised shape documented in bots/README.md. */
const normalise = (message) => {
    const route = routeOf(message);
    if (!route) return null;
    return {
        id: message?.key?.id || null,
        conversationId: route.conversationId,
        isGroup: route.isGroup,
        fromMe: Boolean(message?.key?.fromMe),
        sender: { id: route.senderId, name: message?.pushName || null },
        text: extractMessageText(message),
        timestamp: message?.messageTimestamp ? new Date(Number(message.messageTimestamp) * 1000) : new Date(),
        attachments: attachmentsOf(message),
        raw: message,
    };
};

/**
 * The abstract backend this transport presents to the runtime.
 *
 * Deliberately the CANONICAL op and nothing more: `sendMessage(conversationId, {text})`. When
 * `chatapi/adapters/baileys.js` lands it replaces this object wholesale and the runtime does not
 * notice — which is the test of whether the seam is in the right place.
 */
const backendFor = (sock) => ({
    async sendMessage(conversationId, { text }) {
        // toWhatsAppJid is a no-op for a full JID and normalises a bare phone number, so both the
        // conversation id and a legacy phone-number caller land in the same place.
        return sendTextMessage(sock, toWhatsAppJid(conversationId), text);
    },
});

/** Optional transport niceties. Each one is allowed to fail silently — none is load-bearing. */
const transportFor = (sock) => ({
    sendLong: (conversationId, text, opts) => sendLongTextMessage(sock, toWhatsAppJid(conversationId), text, opts),
    /** The bot renders its own menu text; WhatsApp has no native menu, so it goes out as plain text.
     *  (`send.js`'s own `sendMenu` still exists and is still used by the admin HTTP API — it renders
     *  the SAME text; it is not called from here because the menu content is now the bot's to own.) */
    sendMenu: (conversationId, { text }) => sendTextMessage(sock, toWhatsAppJid(conversationId), text),
    react: (msg, emoji) => sock.sendMessage(msg.conversationId, { react: { text: emoji, key: msg.raw.key } }),
    typing: (msg, on) => sock.sendPresenceUpdate(on ? 'composing' : 'paused', msg.conversationId),
});

/**
 * Main dispatched entrypoint for any inbound WhatsApp message. Same signature as before.
 */
const onMessage = async (sock, message) => {
    try {
        if (!message?.message) return; // empty/protocol frames
        const msg = normalise(message);
        if (!msg) return;
        await runtime.dispatch(msg, {
            connectionId: WA_CONNECTION_ID,
            backend: backendFor(sock),
            transport: transportFor(sock),
        });
    } catch (e) {
        console.error('[wa-adapter] unexpected error', e);
        Sentry.captureException(e);
    }
};

module.exports = {
    onMessage,
    /** Back-compat: the states used to live here. They are the bot's, and this re-export means any
     *  caller that still reaches for `require('./chat_bot').STATES` keeps working. */
    STATES: hacohenBot.STATES,
    // exported for the adapter's own tests
    normalise, routeOf, extractMessageText, attachmentsOf, backendFor, transportFor,
    WA_CONNECTION_ID,
};
