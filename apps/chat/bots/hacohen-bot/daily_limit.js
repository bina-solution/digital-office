/**
 * Per-sender daily message cap.
 *
 * This is BOT policy, not runtime policy: the cap is a number in this app's CONFIG and the warning is
 * a Hebrew sentence in this app's TEXTS. A generic runtime enforcing it would be imposing one
 * customer's fair-use rule on every bot on the platform.
 *
 * The only thing that had to change in the port is how the warning goes out: the old version imported
 * `./send` (Baileys) and took a `sock`. It now takes a `notify(text)` callback, which the caller
 * fills in from `ctx.send`. Same counter, same behaviour, no transport.
 */
const { CONFIG, TEXTS } = require('../../src/config');

const dailyMessageCount = {};

const newDailyMessageCount = () => ({ count: 0, date: new Date().toISOString().split('T')[0] });

// Clear daily message count every 24 hours
const _sweeper = setInterval(() => {
    console.log('Clearing daily message count');
    for (const senderId in dailyMessageCount) delete dailyMessageCount[senderId];
}, 1000 * 60 * 60 * 24);
_sweeper.unref?.();

/**
 * Count this message and say whether the sender may be served.
 *
 * `notify` is fired at most once per sender per day — the warning itself must not be what pushes a
 * chatty sender further over the limit, and repeating it every message is how a rate limit turns into
 * the spam it was meant to prevent.
 *
 * @param {string} senderId
 * @param {(text:string)=>Promise<any>} [notify]
 * @param {number} [limit] the cap for THIS connection (ctx.settings.dailyMessageLimit). Falls back to
 *   the env-configured default, so every existing caller — and every test — keeps its old behaviour.
 * @returns {boolean} true if the message may be processed
 */
const manageDailyMessageLimit = (senderId, notify, limit) => {
    const cap = Number.isFinite(limit) && limit > 0 ? limit : CONFIG.DAILY_MESSAGE_LIMIT;
    const dailyCount = dailyMessageCount[senderId] || newDailyMessageCount();
    console.log('Daily message count for', senderId, dailyCount);
    dailyCount.count++;
    dailyCount.date = new Date().toISOString().split('T')[0];

    dailyMessageCount[senderId] = dailyCount;
    if (dailyCount.count >= cap) {
        console.log('Daily message limit reached for', senderId);
        if (!dailyCount.warned) {
            if (typeof notify === 'function') {
                Promise.resolve(notify(TEXTS.DAILY_MESSAGE_LIMIT_REACHED))
                    .catch((e) => console.error('[daily-limit] Failed to send limit warning:', e.message));
            }
            dailyCount.warned = true;
        }
        return false;
    }
    return true;
};

/** Test seam — the counter is process-global by design (it survives reconnects). */
const _resetDailyCounts = () => { for (const k in dailyMessageCount) delete dailyMessageCount[k]; };

module.exports = { manageDailyMessageLimit, _resetDailyCounts };
