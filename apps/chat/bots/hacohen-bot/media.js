/**
 * Saving an inbound attachment to disk, transport-free.
 *
 * This is the file that used to be welded hardest. The old code called Baileys' own
 * `downloadContentFromMessage(msg.documentMessage, 'document')` and had to know about
 * `documentWithCaptionMessage` wrappers — WhatsApp wire format, in the middle of the bot.
 *
 * The seam is `attachment.download()`: the TRANSPORT closes over whatever it takes to produce the
 * bytes (Baileys stream, Telegram getFile + HTTP GET, a local disk read) and the bot just asks for
 * them. Everything left in this file — deciding a safe filename, guessing an extension, writing to
 * the uploads dir — is genuinely the bot's business and is identical on every backend.
 */
const fs = require('fs');
const path = require('path');
const { CONFIG } = require('../../src/config');

/**
 * Pick a filename that is safe on disk and still recognisable to a human reading the uploads dir.
 * Extension precedence: the sender's own filename, then the MIME type, then `.bin` — because a
 * document with no extension breaks the OCR step downstream, and guessing wrong is recoverable while
 * guessing nothing is not.
 */
function safeFileName(att = {}) {
    const originalName = att.fileName
        || (att.caption ? String(att.caption).replace(/\s+/g, '_') : 'file');
    let ext = path.extname(originalName);
    if (!ext && att.mimeType) {
        const mt = String(att.mimeType).split(';')[0]; // remove charset
        const guess = mt.split('/')[1];
        if (guess) ext = '.' + guess.replace(/[^a-z0-9+.-]/gi, '');
    }
    if (!ext) ext = '.bin';
    // Normalise excel mime derived extensions like vnd.openxmlformats-officedocument.spreadsheetml.sheet
    if (ext.includes('spreadsheetml')) ext = '.xlsx';
    if (ext === '.vnd.ms-excel') ext = '.xls';
    const safeBase = path.basename(originalName, path.extname(originalName))
        .replace(/[\n\r]/g, ' ')
        .replace(/[^\p{L}0-9-_ ]/gu, '')
        .replace(/\s+/g, '_')
        .slice(0, 80) || 'file';
    return safeBase + ext;
}

/**
 * Materialise an attachment into CONFIG.UPLOADS_DIR.
 * @param {{fileName?:string, mimeType?:string, caption?:string, download:()=>Promise<Buffer>}} att
 * @returns {Promise<{filePath:string, fileName:string, caption:string}>}
 */
async function saveAttachment(att) {
    if (!att || typeof att.download !== 'function') throw new Error('Unsupported media type');
    const fileName = safeFileName(att);
    const buffer = await att.download();
    const uploadsDir = CONFIG.UPLOADS_DIR;
    if (!fs.existsSync(uploadsDir)) fs.mkdirSync(uploadsDir, { recursive: true });
    const filePath = path.join(uploadsDir, Date.now() + '_' + fileName);
    fs.writeFileSync(filePath, buffer);
    console.log('Saved incoming media:', filePath);
    return { filePath, fileName, caption: att.caption || '' };
}

module.exports = { saveAttachment, safeFileName };
