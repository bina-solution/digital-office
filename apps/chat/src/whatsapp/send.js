const { CONFIG, TEXTS } = require('../config');
const { isAdmin } = require('../services/settings_api');
const { readSubscribers } = require('../data/subscribers');
const { appProperties } = require('../globals');
const { toWhatsAppJid } = require('../utils/phone');


const sendTextMessage = async (sock, senderId, text) => {    
    await sock.sendMessage(toWhatsAppJid(senderId), { text });
};

// Send long text in WhatsApp-safe chunks (~4000 chars, splitting on newlines
// when possible). Used for large admin reports that exceed the per-message
// limit (~4096 chars).
const sendLongTextMessage = async (sock, senderId, text, { chunkSize = 3800, delayMs = 400 } = {}) => {
    if (!text) return 0;
    const chunks = [];
    let remaining = String(text);
    while (remaining.length > chunkSize) {
        let cut = remaining.lastIndexOf('\n', chunkSize);
        if (cut < chunkSize * 0.5) cut = chunkSize; // no nearby newline — hard cut
        chunks.push(remaining.slice(0, cut));
        remaining = remaining.slice(cut).replace(/^\n+/, '');
    }
    if (remaining.length > 0) chunks.push(remaining);
    for (let i = 0; i < chunks.length; i++) {
        const header = chunks.length > 1 ? `(${i + 1}/${chunks.length})\n` : '';
        await sendTextMessage(sock, senderId, header + chunks[i]);
        if (i < chunks.length - 1) await new Promise(r => setTimeout(r, delayMs));
    }
    return chunks.length;
};

const sendContactMessage = async (sock, senderId, display_name, vcf_text) => {
    await sock.sendMessage(toWhatsAppJid(senderId), {
        contacts: {
            displayName: display_name,
            contacts: [{ vcard: vcf_text }]
        }
    });
};

const sendVideoMessage = async (sock, senderId, video_url, caption) => {
    await sock.sendMessage(toWhatsAppJid(senderId), {
        video: { url: video_url },
        caption
    });
};

const sendImageMessage = async (sock, jid, imagePath, caption) => {
    const fs = require('fs');
    await sock.sendMessage(jid, {
        image: fs.readFileSync(imagePath),
        caption: caption || ''
    });
    return { success: true, message: 'Image sent successfully', jid };
};

const sendDocumentMessage = async (sock, senderId, document_path, filename, mimetype, caption, jpegThumbnail) => {
    try {
        const message = {
            document: { url: document_path },
            mimetype,
            fileName: filename,
            caption
        };

        if (jpegThumbnail) {
            message.jpegThumbnail = jpegThumbnail; // Baileys will attach as preview
        }

        await sock.sendMessage(toWhatsAppJid(senderId), message);
        return { success: true, message: 'Document sent successfully', jid: toWhatsAppJid(senderId), preview: Boolean(jpegThumbnail) };
    } catch (error) {
        console.error('Error sending document:', error);
        return { success: false, message: error.message };
    }
};

const sendMenu = async (sock, senderId) => {
    let menu = TEXTS.MENU_TEXT;
    if (await isAdmin(senderId)) {
    menu += TEXTS.ADMIN_MENU_TEXT;
    }
    menu += `\n\nv${CONFIG.APP_VERSION}`;
    await sendTextMessage(sock, senderId, menu);
};

const sendBroadcastMessage = async (message) => {
    if (!appProperties.sock || !appProperties.is_connected) {
      throw new Error('Bot is not connected');
    }
  
    const subscribers = await readSubscribers();
    const results = { sent: 0, failed: 0, errors: [] };
    for (const subscriber of subscribers) {
      try {
        await sendTextMessage(appProperties.sock, subscriber.phoneNumber, message);
        results.sent++;
      } catch (e) {
        results.failed++;
        results.errors.push({ phone: subscriber.phoneNumber, error: e.message });
        console.error(`[broadcast] Failed to send to ${subscriber.phoneNumber}:`, e.message);
      }
      // Add delay to avoid flooding
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    console.log(`[broadcast] Completed: ${results.sent} sent, ${results.failed} failed`);
    return results;
  };





module.exports = {
    sendTextMessage,
    sendLongTextMessage,
    sendContactMessage,
    sendVideoMessage,
    sendDocumentMessage,
    sendImageMessage,
    sendBroadcastMessage,
    sendMenu
};
