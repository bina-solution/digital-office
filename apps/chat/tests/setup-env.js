/**
 * Point every state-writing default at a per-run temp directory.
 *
 * The chat service persists two things to disk — the active connection pointer and the bot
 * attachments — and both default to `/data`, which is the container's volume. Running the suite on a
 * developer machine would otherwise create a real `/data` (on Windows, `C:\data`) and, worse, carry
 * one test file's attachments into the next run, so a test could pass only because of what an earlier
 * run left behind.
 */
const fs = require('fs');
const os = require('os');
const path = require('path');

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'chat-state-'));
process.env.CHAT_STATE_DIR = dir;
