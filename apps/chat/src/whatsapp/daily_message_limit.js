/**
 * Kept as a re-export so nothing that still requires this path breaks.
 *
 * The implementation moved to `bots/hacohen-bot/daily_limit.js` — the cap is that bot's policy, and
 * the version here could not come with it because it imported `./send` (Baileys) to deliver the
 * warning. There is ONE counter: this wrapper adapts the old `(sock, senderId, replyJid)` signature
 * onto the new `(senderId, notify)` one, so a caller on either path shares the same state and a
 * sender cannot get two separate daily allowances by talking on two paths.
 */
const { sendTextMessage } = require('./send');
const { manageDailyMessageLimit: coreLimit } = require('../../bots/hacohen-bot/daily_limit');

const manageDailyMessageLimit = (sock, senderId, replyJid) =>
    coreLimit(senderId, (text) => sendTextMessage(sock, replyJid || senderId, text));

module.exports = { manageDailyMessageLimit };
