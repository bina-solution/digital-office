/**
 * INTENT — "does this message actually want an answer?"
 *
 * The sim (digital-office/sim/mocks/wadmin.js) settled this question before we did, and its answer is
 * the one we port: a bot replies to a QUESTION, a MENU CHOICE or a KEYWORD — never to every line, and
 * never in a group. Its mock replies are demo data and are deliberately NOT copied; the *rule* is.
 *
 * The rule lives here, in the runtime, rather than in each bot, for one reason: "don't spam the chat"
 * is a property of the SERVICE, not of any one bot. A bot that forgot to implement it would be
 * indistinguishable from a broken connection — it would answer its own group's small talk forever.
 * Putting the gate in one place means a new bot is quiet by default and has to ASK to be noisy
 * (`accepts.groups` / `accepts.chatter`), which is the safe direction for the failure to point.
 *
 * Everything here is pure and transport-free: it reads the NORMALISED message only (see README.md).
 */

/** A trailing question mark in either the ASCII or the full-width form (pasted from mobile IMEs). */
const QUESTION_RE = /[?？]\s*$/;
/** A bare number is how every menu bot in the world spells "option N". */
const MENU_CHOICE_RE = /^\d{1,2}$/;
/** Slash/bang commands — `/end`, `/model sonnet`, `!status`. */
const COMMAND_RE = /^[/!][a-z]/i;
/** "get me a human" — the one intent that must always win, in Hebrew and English. */
const HUMAN_RE = /(נציג|אנושי|בן ?אדם|לדבר עם|human|agent|representative)/i;
const URL_RE = /https?:\/\/[^\s<>"']+/i;

/**
 * Below this length a plain statement is "chatter" — "ok", "תודה", "👍". The sim used 24 characters
 * and it is a good line: long enough that a real request clears it, short enough that acknowledgements
 * do not. It is a heuristic and is named as one; `accepts.chatter` is the escape hatch for bots (like
 * hacohen-bot) where a two-character message IS the payload.
 */
const CHATTER_MAX_CHARS = 24;

/** Precedence order, most specific first. The first hit wins. */
function kindOf(msg, text) {
  if (msg.attachments && msg.attachments.length) return 'attachment';
  if (!text) return 'empty';
  if (COMMAND_RE.test(text)) return 'command';
  if (MENU_CHOICE_RE.test(text)) return 'menuChoice';
  if (URL_RE.test(text)) return 'link';
  if (HUMAN_RE.test(text)) return 'handoff';
  if (QUESTION_RE.test(text)) return 'question';
  if (text.length > CHATTER_MAX_CHARS) return 'statement';
  return 'chatter';
}

/**
 * Classify a normalised inbound message.
 * Returns a flat record (not just a string) because bots want the booleans directly — `intent.isQuestion`
 * reads better at a call site than `intent.kind === 'question'`, and a bot that cares about both a
 * question AND a keyword would otherwise have to re-derive one of them.
 */
function classify(msg = {}) {
  const text = (msg.text || '').trim();
  const kind = kindOf(msg, text);
  return {
    kind,
    text,
    length: text.length,
    isGroup: Boolean(msg.isGroup),
    hasAttachment: kind === 'attachment',
    hasLink: Boolean(text && URL_RE.test(text)),
    isCommand: kind === 'command',
    isMenuChoice: kind === 'menuChoice',
    isQuestion: kind === 'question',
    isHandoff: kind === 'handoff',
    /** short plain text that asked for nothing — the thing a bot must NOT answer by default */
    isChatter: kind === 'chatter',
    isEmpty: kind === 'empty',
  };
}

/** What a bot gets if its manifest says nothing: quiet in groups, quiet on small talk. */
const DEFAULT_ACCEPTS = Object.freeze({ groups: false, chatter: false });

/**
 * The gate the runtime applies before it will even wake a bot.
 *
 * `accepts` is the bot's manifest opt-in. Returning a REASON rather than a bare false is deliberate:
 * "the bot said nothing" and "the runtime never asked the bot" look identical in a chat window and
 * completely different in a bug report.
 *
 * @returns {{ ok: boolean, reason: string }}
 */
function shouldAutoReply(msg = {}, accepts = DEFAULT_ACCEPTS) {
  const a = { ...DEFAULT_ACCEPTS, ...(accepts || {}) };
  const intent = classify(msg);

  if (msg.isGroup && !a.groups) return { ok: false, reason: 'group_not_accepted', intent };
  if (intent.isEmpty) return { ok: false, reason: 'empty', intent };
  if (intent.isChatter && !a.chatter) return { ok: false, reason: 'chatter', intent };
  return { ok: true, reason: 'ok', intent };
}

module.exports = {
  classify, shouldAutoReply,
  DEFAULT_ACCEPTS, CHATTER_MAX_CHARS,
};
