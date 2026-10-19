// Telegram API helpers — send, edit, photo, file download, webhook
import { readFileSync, mkdirSync, writeFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

// Public base of THIS dispatcher, from the deployment (apps/openhands/docker-compose.yml sets
// DISPATCH_PUBLIC_URL from ${DISPATCH_BASE_URL}, which derives from DEPLOYMENT_DOMAIN). It was a
// literal at every call site, so every link the bot handed out named the FIRST deployment's
// domain no matter which deployment sent it.
const DISPATCH_PUBLIC_URL = (process.env.DISPATCH_PUBLIC_URL || 'http://localhost:8800').replace(/\/+$/, '');

const TOKEN = process.env.TELEGRAM_BOT_TOKEN || '';
const API = `https://api.telegram.org/bot${TOKEN}`;
const DOWNLOADS_DIR = '/root/deployment-hacohen/development/openhands/downloads';
try { mkdirSync(DOWNLOADS_DIR, { recursive: true }); } catch(e) {}

// In-memory image cache for URL proxy
const imageCache = new Map();

// Send a chat action (typing, upload_photo, etc.)
export async function sendChatAction(chatId, action) {
  if (!TOKEN) return;
  action = action || 'typing';
  try {
    await fetch(`${API}/sendChatAction`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ chat_id: chatId, action: action }),
      signal: AbortSignal.timeout(10000)
    });
  } catch(e) { /* silent — non-critical */ }
}

// Send or edit a Telegram message (HTML parse mode)
export async function sendMessage(chatId, text, opts) {
  if (!TOKEN) return;
  opts = opts || {};
  var body = { chat_id: chatId, text: String(text||'').slice(0, 4096), parse_mode: 'HTML' };
  if (opts.replyToMsgId) body.reply_to_message_id = opts.replyToMsgId;
  try {
    var method = opts.editMsgId ? 'editMessageText' : 'sendMessage';
    if (opts.editMsgId) body.message_id = opts.editMsgId;
    await fetch(`${API}/${method}`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body), signal: AbortSignal.timeout(30000)
    });
  } catch(e) { console.error('[telegram] send error:', e.message); }
}

// Send a photo from local file or URL
export async function sendPhoto(chatId, photoPathOrUrl, opts) {
  if (!TOKEN) return null;
  opts = opts || {};
  try {
    var fd = new FormData();
    fd.append('chat_id', String(chatId));
    if (opts.replyToMsgId) fd.append('reply_to_message_id', String(opts.replyToMsgId));
    if (opts.caption) fd.append('caption', opts.caption.slice(0, 1024));
    if (photoPathOrUrl.startsWith('http://') || photoPathOrUrl.startsWith('https://')) {
      fd.append('photo', photoPathOrUrl);
    } else {
      var buf = readFileSync(photoPathOrUrl);
      fd.append('photo', new Blob([buf]), photoPathOrUrl.split('/').pop());
    }
    var res = await fetch(`${API}/sendPhoto`, { method: 'POST', body: fd, signal: AbortSignal.timeout(30000) });
    var d = await res.json();
    return d.ok ? d.result : null;
  } catch(e) { console.error('[telegram] sendPhoto error:', e.message); return null; }
}

// Forward session images created in the last 5 minutes
export async function forwardSessionImages(chatId, convId, replyToMsgId) {
  if (!TOKEN || !chatId) return [];
  var sent = [];
  try {
    var cutoff = Date.now() - 300000;
    var files = readdirSync(DOWNLOADS_DIR);
    for (var i = 0; i < files.length; i++) {
      var f = files[i], fp = join(DOWNLOADS_DIR, f);
      if (statSync(fp).mtimeMs < cutoff) continue;
      var ext = f.split('.').pop().toLowerCase();
      if (!['png','jpg','jpeg','gif','webp'].includes(ext)) continue;
      if (f.startsWith('tg_')) continue;
      var r = await sendPhoto(chatId, fp, { replyToMsgId, caption: '[img] ' + f });
      if (r) sent.push(fp);
    }
  } catch(e) { console.error('[telegram] scan images error:', e.message); }
  if (sent.length) console.log('[telegram] forwarded ' + sent.length + ' session images');
  return sent;
}

// Get Telegram file download URL
async function getFileUrl(fileId) {
  if (!TOKEN) return null;
  try {
    var r = await fetch(`${API}/getFile?file_id=${fileId}`, { signal: AbortSignal.timeout(10000) });
    if (!r.ok) return null;
    var d = await r.json();
    return (d.ok && d.result && d.result.file_path)
      ? `https://api.telegram.org/file/bot${TOKEN}/${d.result.file_path}` : null;
  } catch(e) { return null; }
}

// Download ANY Telegram file → save to shared downloads + register in image cache
export async function cacheFileForOpenHands(fileId, fileType) {
  if (!TOKEN) return null;
  try {
    var fileUrl = await getFileUrl(fileId);
    if (!fileUrl) return null;
    var r = await fetch(fileUrl, { signal: AbortSignal.timeout(30000) });
    if (!r.ok) return null;
    var buffer = Buffer.from(await r.arrayBuffer());
    var ct = r.headers.get('content-type') || 'application/octet-stream';
    var ext = 'bin';
    if (ct.includes('png')) ext = 'png';
    else if (ct.includes('gif')) ext = 'gif';
    else if (ct.includes('webp')) ext = 'webp';
    else if (ct.includes('jpeg') || ct.includes('jpg')) ext = 'jpg';
    else if (ct.includes('mp4')) ext = 'mp4';
    else if (ct.includes('pdf')) ext = 'pdf';
    else if (ct.includes('zip')) ext = 'zip';
    else if (ct.includes('mpeg') || ct.includes('mp3')) ext = 'mp3';
    else if (ct.includes('ogg')) ext = 'ogg';
    var safeName = 'tg_' + (fileType||'file') + '_' + fileId.slice(0,16).replace(/[^a-zA-Z0-9_-]/g,'') + '_' + Date.now() + '.' + ext;
    writeFileSync(join(DOWNLOADS_DIR, safeName), buffer);
    var cacheId = 'img_' + fileId.slice(0,12).replace(/[^a-zA-Z0-9]/g,'');
    imageCache.set(cacheId, { data: buffer, contentType: ct });
    var url = `${DISPATCH_PUBLIC_URL}/image/${cacheId}.${ext}`;
    var sandboxPath = `/workspace/project/development/openhands/downloads/${safeName}`;
    console.log('[telegram] ' + (fileType||'file') + ' saved: ' + join(DOWNLOADS_DIR, safeName) + ' (' + buffer.length + ' bytes)');
    return { url, path: sandboxPath, hostPath: join(DOWNLOADS_DIR, safeName), fileName: safeName, mimeType: ct, size: buffer.length };
  } catch(e) { console.error('[telegram] file cache error:', e.message); return null; }
}

// Set Telegram webhook
export async function setWebhook(webhookUrl) {
  if (!TOKEN || !webhookUrl) return;
  try {
    var r = await fetch(`${API}/setWebhook?url=${encodeURIComponent(webhookUrl)}&allowed_updates=["message"]`, { signal: AbortSignal.timeout(10000) });
    var d = await r.json();
    console.log('[telegram] webhook ' + (d.ok ? 'set → ' + webhookUrl : 'FAILED: ' + JSON.stringify(d)));
  } catch(e) { console.warn('[telegram] webhook setup error:', e.message); }
}

// Export for URL proxy server
export function getImageCache() { return imageCache; }
export function getDownloadsDir() { return DOWNLOADS_DIR; }
export function getToken() { return TOKEN; }
export { API as TELEGRAM_API };
