/**
 * The bot's reply helpers.
 *
 * `reply(ctx, text, showMenu)` is a straight port of the old `reply(sock, senderId, text, showMenu)`
 * — the only change is that the destination is no longer an argument. It is `ctx`, and `ctx` already
 * knows which conversation it came from. That one substitution is what collapsed the old
 * private-vs-group duplication: `groupReply` existed purely because the private helper hard-coded
 * "reply to the sender's DM", and a group message must be answered in the group.
 *
 * The MENU TEXT lives here, in the bot, and not in the runtime: it is this customer's menu. The bot
 * renders it and hands it to `ctx.sendMenu({ text })`, which lets a transport with native quick
 * replies upgrade the rendering later without the bot changing.
 */
const { CONFIG, TEXTS } = require('../../src/config');
const { isAdmin } = require('../../src/services/settings_api');

/**
 * @param {string} senderId
 * @param {{withVersion?:boolean}} opts  the group menu never carried the version suffix and the DM one
 *   always did; preserved rather than unified, because this is a live bot and "tidier" is not a reason
 *   to change what a user sees.
 */
async function menuText(senderId, { withVersion = true } = {}) {
    let menu = TEXTS.MENU_TEXT;
    if (await isAdmin(senderId)) menu += TEXTS.ADMIN_MENU_TEXT;
    if (withVersion) menu += `\n\nv${CONFIG.APP_VERSION}`;
    return menu;
}

/** Reply with text, then optionally the menu — the shape every handler in this bot uses. */
async function reply(ctx, text, showMenu = false, menuOpts = {}) {
    if (text) await ctx.send(text);
    if (showMenu) {
        const senderId = ctx.sender && ctx.sender.id;
        await ctx.sendMenu({ text: await menuText(senderId, menuOpts) });
    }
}

module.exports = { reply, menuText };
