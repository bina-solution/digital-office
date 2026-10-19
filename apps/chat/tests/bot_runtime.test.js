/**
 * The bot runtime, tested without a transport.
 *
 * Everything here runs against a fake backend whose only method is the canonical
 * `sendMessage(conversationId, {text})`. That is the point: if these pass, a bot needs nothing from
 * WhatsApp, Telegram or the local tables, and the seam is where we claim it is.
 *
 * Bots are discovered from a REAL temporary directory rather than from a stubbed `fs`, because the
 * thing most likely to break discovery is the filesystem convention itself (a folder without an
 * index.js, an id that disagrees with its folder, a module that throws on require) and a stub would
 * cheerfully agree with whatever we assumed.
 */
const fs = require('fs');
const os = require('os');
const path = require('path');

const runtime = require('../bots/chat_bot');
const intent = require('../bots/intent');

let TMP;

/** A backend with exactly the canonical op and nothing else. */
function fakeBackend() {
  const sent = [];
  return {
    sent,
    async sendMessage(conversationId, payload) { sent.push({ conversationId, ...payload }); return { id: `m${sent.length}` }; },
  };
}

/** A normalised inbound message — the shape documented in bots/README.md. */
function inbound(over = {}) {
  return {
    id: 'wamid.1',
    conversationId: 'person32@example.com',
    isGroup: false,
    fromMe: false,
    sender: { id: '050-000-0006', name: 'משה' },
    text: 'hello',
    timestamp: new Date(),
    attachments: [],
    raw: {},
    ...over,
  };
}

function writeBot(folder, source) {
  const dir = path.join(TMP, folder);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, 'index.js'), source, 'utf8');
  return dir;
}

beforeAll(() => {
  TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'chat-bots-'));

  // default policy: quiet in groups, quiet on chatter
  writeBot('quiet-bot', `
    module.exports = {
      id: 'quiet-bot', name: 'Quiet', desc: 'default policy',
      async onMessage(msg, ctx) {
        global.__CALLS.push({ bot: 'quiet-bot', text: msg.text, intent: ctx.intent.kind, conn: ctx.connectionId });
        await ctx.send('answered: ' + msg.text);
      },
    };
  `);

  // opts in to everything — the hacohen-bot posture
  writeBot('loud-bot', `
    module.exports = {
      id: 'loud-bot', name: 'Loud', desc: 'accepts groups and chatter',
      accepts: { groups: true, chatter: true },
      async onMessage(msg, ctx) {
        global.__CALLS.push({ bot: 'loud-bot', text: msg.text, group: ctx.isGroup });
        await ctx.send('loud: ' + msg.text);
      },
    };
  `);

  // declares knobs, including the accepts.* gate override
  writeBot('tunable-bot', `
    module.exports = {
      id: 'tunable-bot', name: 'Tunable', desc: 'declares settings',
      accepts: { groups: true, chatter: true },
      settings: [
        { key: 'accepts.groups', label: 'groups', type: 'boolean', default: true },
        { key: 'greeting', label: 'greeting', type: 'text', default: 'shalom', maxLength: 20 },
        { key: 'cap', label: 'cap', type: 'number', default: 10, min: 1, max: 100 },
        { key: 'tone', label: 'tone', type: 'select', default: 'warm', options: ['warm', 'terse'] },
      ],
      async onMessage(msg, ctx) {
        global.__CALLS.push({ bot: 'tunable-bot', settings: ctx.settings, group: ctx.isGroup });
        await ctx.send(ctx.settings.greeting);
      },
    };
  `);

  // a settings schema that cannot be rendered — must be rejected at LOAD, like any other broken bot
  writeBot('badschema-bot', `
    module.exports = {
      id: 'badschema-bot', async onMessage() {},
      settings: [{ key: 'x', type: 'colour', default: 'red' }],
    };
  `);

  // throws at require — must not take the others down with it
  writeBot('broken-bot', 'throw new Error("boom at require time");');

  // id disagrees with its folder — the silent-misattachment bug
  writeBot('mismatch-bot', 'module.exports = { id: "something-else", async onMessage() {} };');

  // a folder that is not a bot at all
  fs.mkdirSync(path.join(TMP, 'notes'), { recursive: true });
  fs.writeFileSync(path.join(TMP, 'notes', 'README.md'), '# not a bot', 'utf8');

  // a loose file next to the bots — must never be loaded as one
  fs.writeFileSync(path.join(TMP, 'helper.js'), 'module.exports = { id: "helper", onMessage(){} };', 'utf8');
});

afterAll(() => { try { fs.rmSync(TMP, { recursive: true, force: true }); } catch { /* best effort */ } });

/**
 * A clean slate now means clearing the DISK too.
 *
 * `reset()` deliberately only drops in-process state — it is the test seam for "the container
 * restarted", and a restart is precisely the case where the persisted attachments and settings must
 * come back. So reset() alone no longer isolates one test from the next; without this, a test would
 * pass or fail depending on what the test above it happened to save.
 */
beforeEach(() => {
  global.__CALLS = [];
  runtime.reset();
  for (const f of ['bot-attachments.json', 'bot-settings.json']) {
    try { fs.rmSync(path.join(process.env.CHAT_STATE_DIR, f), { force: true }); } catch { /* nothing saved yet */ }
  }
});

// ── discovery ─────────────────────────────────────────────────────────────────
describe('discovery', () => {
  test('a bot is a folder with an index.js — nothing else is loadable', () => {
    const ids = [...runtime.loadBots(TMP).keys()].sort();
    expect(ids).toEqual(['loud-bot', 'quiet-bot', 'tunable-bot']);
  });

  test('one bot throwing at require does not stop the others loading', () => {
    // broken-bot is in the same directory and blows up on require; the two healthy bots still appear
    expect(runtime.loadBots(TMP).has('quiet-bot')).toBe(true);
    expect(runtime.loadBots(TMP).has('broken-bot')).toBe(false);
  });

  test('an id that disagrees with its folder is rejected, not silently accepted', () => {
    // otherwise an attachment record points at a bot id no folder answers to, and the connection just
    // goes quiet with nothing in the logs
    expect(runtime.loadBots(TMP).has('something-else')).toBe(false);
    expect(runtime.validate({ id: 'something-else', onMessage() {} }, 'mismatch-bot'))
      .toMatch(/does not match folder/);
  });

  test('validate names the specific defect', () => {
    expect(runtime.validate(null, 'x')).toMatch(/not an object/);
    expect(runtime.validate({ onMessage() {} }, 'x')).toMatch(/`id`/);
    expect(runtime.validate({ id: 'x' }, 'x')).toMatch(/onMessage/);
    expect(runtime.validate({ id: 'x', onMessage() {} }, 'x')).toBeNull();
  });

  test('listBots offers "none" first, so turning automation off is a normal choice', () => {
    const list = runtime.listBots(TMP);
    expect(list[0].id).toBe('none');
    expect(list.map((b) => b.id).sort()).toEqual(['loud-bot', 'none', 'quiet-bot', 'tunable-bot']);
    // the roster advertises the policy, so the UI can explain why a bot is quiet in a group
    expect(list.find((b) => b.id === 'quiet-bot').accepts).toEqual({ groups: false, chatter: false });
    expect(list.find((b) => b.id === 'loud-bot').accepts).toEqual({ groups: true, chatter: true });
  });
});

// ── attachment ────────────────────────────────────────────────────────────────
describe('attach / detach per connection', () => {
  test('an unwired connection has no bot — it does not inherit one', async () => {
    runtime.loadBots(TMP);
    expect(runtime.attachedTo('brand-new-connection')).toBe('none');
    const backend = fakeBackend();
    const r = await runtime.dispatch(inbound({ text: 'is anyone there?' }), {
      connectionId: 'brand-new-connection', backend, botsDir: TMP,
    });
    expect(r).toMatchObject({ handled: false, reason: 'no_bot' });
    expect(backend.sent).toHaveLength(0);
  });

  test('attaching is per connection: two connections, two different bots', async () => {
    runtime.loadBots(TMP);
    runtime.attach('conn-a', 'quiet-bot', TMP);
    runtime.attach('conn-b', 'loud-bot', TMP);
    expect(runtime.attachedTo('conn-a')).toBe('quiet-bot');
    expect(runtime.attachedTo('conn-b')).toBe('loud-bot');

    await runtime.dispatch(inbound({ text: 'who is answering me?' }), { connectionId: 'conn-a', backend: fakeBackend(), botsDir: TMP });
    await runtime.dispatch(inbound({ text: 'who is answering me?' }), { connectionId: 'conn-b', backend: fakeBackend(), botsDir: TMP });
    expect(global.__CALLS.map((c) => c.bot)).toEqual(['quiet-bot', 'loud-bot']);
  });

  test('the ctx tells the bot which connection it is on', async () => {
    runtime.attach('conn-a', 'quiet-bot', TMP);
    await runtime.dispatch(inbound({ text: 'which connection is this?' }), { connectionId: 'conn-a', backend: fakeBackend(), botsDir: TMP });
    expect(global.__CALLS[0].conn).toBe('conn-a');
  });

  test('detach silences the connection without deleting it', async () => {
    runtime.attach('conn-a', 'quiet-bot', TMP);
    expect(runtime.detach('conn-a')).toBe('none');
    const backend = fakeBackend();
    const r = await runtime.dispatch(inbound({ text: 'anyone home?' }), { connectionId: 'conn-a', backend, botsDir: TMP });
    expect(r.reason).toBe('no_bot');
    expect(backend.sent).toHaveLength(0);
  });

  test('attaching an unknown bot fails loudly instead of half-wiring the connection', () => {
    runtime.loadBots(TMP);
    expect(() => runtime.attach('conn-a', 'no-such-bot', TMP)).toThrow(/unknown bot/);
    expect(runtime.attachedTo('conn-a')).toBe('none');
  });

  test('setBot is the same verb under the canonical op name', () => {
    runtime.loadBots(TMP);
    runtime.setBot('conn-c', 'loud-bot', TMP);
    expect(runtime.attachedTo('conn-c')).toBe('loud-bot');
  });

  test('an attachment survives a restart', () => {
    // The regression this guards against was observed on every redeploy: attachments lived only in a
    // Map, so a container recreate reverted the operator's choice to `none` with nothing in the logs.
    // reset() drops all in-process state, which is exactly what a restart does.
    runtime.loadBots(TMP);
    runtime.attach('conn-persist', 'loud-bot', TMP);
    runtime.reset();
    expect(runtime.attachedTo('conn-persist', TMP)).toBe('loud-bot');
  });

  test('a bot whose settings schema cannot be rendered is rejected at load', () => {
    // Not at first-open of the panel: a schema the UI cannot draw is a broken bot, and discovering
    // that mid-conversation is far worse than never loading it.
    expect(runtime.loadBots(TMP).has('badschema-bot')).toBe(false);
    expect(runtime.validate({ id: 'x', onMessage() {}, settings: [{ key: 'k', type: 'colour' }] }, 'x'))
      .toMatch(/unknown type "colour"/);
    expect(runtime.validate({ id: 'x', onMessage() {}, settings: [{ key: 'k', type: 'select' }] }, 'x'))
      .toMatch(/no options/);
    expect(runtime.validate({ id: 'x', onMessage() {}, settings: [{ key: 'k', type: 'text' }, { key: 'k', type: 'text' }] }, 'x'))
      .toMatch(/duplicate setting key/);
  });

  test('an explicit silence survives a restart too', () => {
    // Strictly stronger than the test above: `none` must be stored, not represented by absence.
    // Absence means "never chosen", which is what lets a protocol default fire.
    runtime.loadBots(TMP);
    runtime.attach('conn-hushed', 'loud-bot', TMP);
    runtime.detach('conn-hushed');
    runtime.reset();
    expect(runtime.attachedTo('conn-hushed', TMP)).toBe('none');
  });
});

// ── settings ──────────────────────────────────────────────────────────────────
describe('per-connection bot settings', () => {
  const A = 'conn-a', B = 'conn-b', BOT = 'tunable-bot';

  test('an untouched bot reports its declared defaults', () => {
    runtime.loadBots(TMP);
    expect(runtime.getSettings(A, BOT, TMP))
      .toEqual({ 'accepts.groups': true, greeting: 'shalom', cap: 10, tone: 'warm' });
  });

  test('settings are per connection, not per bot', () => {
    // The same bot on a public number and on internal chat is doing two different jobs; one shared
    // value is wrong in whichever direction it is set.
    runtime.loadBots(TMP);
    runtime.setSettings(A, BOT, { greeting: 'boker tov' }, TMP);
    expect(runtime.getSettings(A, BOT, TMP).greeting).toBe('boker tov');
    expect(runtime.getSettings(B, BOT, TMP).greeting).toBe('shalom');
  });

  test('a partial save leaves the other keys alone', () => {
    runtime.loadBots(TMP);
    runtime.setSettings(A, BOT, { cap: 5 }, TMP);
    runtime.setSettings(A, BOT, { tone: 'terse' }, TMP);
    expect(runtime.getSettings(A, BOT, TMP)).toMatchObject({ cap: 5, tone: 'terse', greeting: 'shalom' });
  });

  test('values arriving as strings are coerced to the declared type', () => {
    // They always do: an HTTP body has no types. A bot reads ctx.settings.cap and must get a number.
    runtime.loadBots(TMP);
    runtime.setSettings(A, BOT, { cap: '42', 'accepts.groups': 'false' }, TMP);
    const s = runtime.getSettings(A, BOT, TMP);
    expect(s.cap).toBe(42);
    expect(s['accepts.groups']).toBe(false);
  });

  test('a bad value is refused with the field named, not silently dropped', () => {
    runtime.loadBots(TMP);
    expect(runtime.setSettings(A, BOT, { cap: 'lots' }, TMP)).toMatchObject({ ok: false, error: /"cap" must be a number/ });
    expect(runtime.setSettings(A, BOT, { cap: 9999 }, TMP)).toMatchObject({ ok: false, error: /at most 100/ });
    expect(runtime.setSettings(A, BOT, { tone: 'shouty' }, TMP)).toMatchObject({ ok: false, error: /must be one of warm, terse/ });
    expect(runtime.setSettings(A, BOT, { greeting: 'x'.repeat(21) }, TMP)).toMatchObject({ ok: false, error: /longer than 20/ });
    // and nothing was written
    expect(runtime.getSettings(A, BOT, TMP).cap).toBe(10);
  });

  test('an unknown key is refused rather than ignored', () => {
    // A typo that is silently accepted is a setting the operator believes they changed and did not.
    runtime.loadBots(TMP);
    expect(runtime.setSettings(A, BOT, { greting: 'hi' }, TMP)).toMatchObject({ ok: false, error: /unknown setting "greting"/ });
  });

  test('settings survive a restart', () => {
    runtime.loadBots(TMP);
    runtime.setSettings(A, BOT, { greeting: 'erev tov' }, TMP);
    runtime.reset();
    expect(runtime.getSettings(A, BOT, TMP).greeting).toBe('erev tov');
  });

  test('the bot reads its settings off ctx', async () => {
    runtime.loadBots(TMP);
    runtime.attach(A, BOT, TMP);
    runtime.setSettings(A, BOT, { greeting: 'ahlan' }, TMP);
    const backend = fakeBackend();
    await runtime.dispatch(inbound({ text: 'a real question?' }), { connectionId: A, backend, botsDir: TMP });
    expect(global.__CALLS[0].settings.greeting).toBe('ahlan');
    expect(backend.sent[0].text).toBe('ahlan');
  });

  test('an accepts.* setting overrides the gate on that connection only', async () => {
    // This is the whole point of per-connection settings: silence the bot in groups on the public
    // number while it keeps doing group document intake internally, with no redeploy.
    runtime.loadBots(TMP);
    runtime.attach(A, BOT, TMP);
    runtime.attach(B, BOT, TMP);
    runtime.setSettings(A, BOT, { 'accepts.groups': false }, TMP);

    const inGroup = inbound({ isGroup: true, text: 'a real question in a group?' });
    const quiet = fakeBackend();
    const loud = fakeBackend();
    const rA = await runtime.dispatch(inGroup, { connectionId: A, backend: quiet, botsDir: TMP });
    const rB = await runtime.dispatch(inGroup, { connectionId: B, backend: loud, botsDir: TMP });

    expect(rA.handled).toBe(false);
    expect(quiet.sent).toHaveLength(0);
    expect(rB.handled).toBe(true);
    expect(loud.sent).toHaveLength(1);
  });

  test('a key dropped from the schema does not come back', () => {
    // Overrides are stored, resolved values are not — so a setting the bot no longer declares simply
    // stops being served instead of haunting the panel.
    runtime.loadBots(TMP);
    runtime.setSettings(A, BOT, { greeting: 'hi' }, TMP);
    expect(runtime.getSettings(A, 'quiet-bot', TMP)).toEqual({});
  });

  test('saving against a bot with no settings is refused, not a silent no-op', () => {
    runtime.loadBots(TMP);
    expect(runtime.setSettings(A, 'quiet-bot', { x: 1 }, TMP)).toMatchObject({ ok: false, error: /declares no settings/ });
    expect(runtime.setSettings(A, 'no-such-bot', { x: 1 }, TMP)).toMatchObject({ ok: false, error: /unknown bot/ });
  });

  // ── reset to the declared defaults ──────────────────────────────────────────
  // PUT cannot express "unset": the store holds OVERRIDES, and writing the current default back
  // would PIN it, so a bot that later changes its own default would keep running the old one on
  // every connection anyone had ever "reset". Only deleting the key means "follow the bot".
  test('clearing one key drops back to the DECLARED default, not the value at reset time', () => {
    runtime.loadBots(TMP);
    runtime.setSettings(A, BOT, { greeting: 'boker tov', cap: 5 }, TMP);
    const r = runtime.clearSettings(A, BOT, ['greeting'], TMP);
    expect(r).toMatchObject({ ok: true, cleared: ['greeting'] });
    expect(runtime.getSettings(A, BOT, TMP)).toMatchObject({ greeting: 'shalom', cap: 5 });
  });

  test('clearing with no key list resets the whole (connection, bot) pair', () => {
    runtime.loadBots(TMP);
    runtime.setSettings(A, BOT, { greeting: 'boker tov', cap: 5, tone: 'terse' }, TMP);
    expect(runtime.clearSettings(A, BOT, null, TMP).cleared.sort()).toEqual(['cap', 'greeting', 'tone']);
    expect(runtime.getSettings(A, BOT, TMP))
      .toEqual({ 'accepts.groups': true, greeting: 'shalom', cap: 10, tone: 'warm' });
  });

  test('clearing one connection leaves the other connection alone', () => {
    runtime.loadBots(TMP);
    runtime.setSettings(A, BOT, { greeting: 'boker tov' }, TMP);
    runtime.setSettings(B, BOT, { greeting: 'erev tov' }, TMP);
    runtime.clearSettings(A, BOT, null, TMP);
    expect(runtime.getSettings(A, BOT, TMP).greeting).toBe('shalom');
    expect(runtime.getSettings(B, BOT, TMP).greeting).toBe('erev tov');
  });

  test('a reset survives a restart — it deleted the override, it did not mask it', () => {
    runtime.loadBots(TMP);
    runtime.setSettings(A, BOT, { greeting: 'boker tov' }, TMP);
    runtime.clearSettings(A, BOT, null, TMP);
    runtime.reset();                       // what a container restart does
    runtime.loadBots(TMP);
    expect(runtime.getSettings(A, BOT, TMP).greeting).toBe('shalom');
  });

  test('an unknown key is refused, exactly as saving one is', () => {
    // "I reset that" and "I typoed that" must not look identical to the operator.
    runtime.loadBots(TMP);
    expect(runtime.clearSettings(A, BOT, ['gretting'], TMP)).toMatchObject({ ok: false, error: /unknown setting "gretting"/ });
    expect(runtime.clearSettings(A, 'no-such-bot', null, TMP)).toMatchObject({ ok: false, error: /unknown bot/ });
    expect(runtime.clearSettings(A, 'quiet-bot', null, TMP)).toMatchObject({ ok: false, error: /declares no settings/ });
    expect(runtime.clearSettings(null, BOT, null, TMP)).toMatchObject({ ok: false, error: /connectionId required/ });
  });

  test('clearing what was never set is ok with cleared:[] — not a failure', () => {
    runtime.loadBots(TMP);
    expect(runtime.clearSettings(A, BOT, null, TMP)).toMatchObject({ ok: true, cleared: [] });
  });
});

// ── the auto-reply gate ───────────────────────────────────────────────────────
describe('the auto-reply gate', () => {
  beforeEach(() => { runtime.loadBots(TMP); runtime.attach('c', 'quiet-bot', TMP); });

  test('a GROUP message gets no auto-reply', async () => {
    const backend = fakeBackend();
    const r = await runtime.dispatch(
      inbound({ isGroup: true, conversationId: '12345@g.us', text: 'מישהו זמין לסגור את דוח המע״מ להיום?' }),
      { connectionId: 'c', backend, botsDir: TMP });
    expect(r).toMatchObject({ handled: false, reason: 'group_not_accepted' });
    expect(backend.sent).toHaveLength(0);
    expect(global.__CALLS).toHaveLength(0); // the bot was never even woken
  });

  test('a QUESTION does get an auto-reply', async () => {
    const backend = fakeBackend();
    const r = await runtime.dispatch(inbound({ text: 'מתי צפוי התשלום להיכנס?' }), { connectionId: 'c', backend, botsDir: TMP });
    expect(r).toMatchObject({ handled: true, reason: 'ok', botId: 'quiet-bot' });
    expect(backend.sent).toHaveLength(1);
    expect(backend.sent[0].conversationId).toBe('person32@example.com');
  });

  test('short chatter does NOT get an auto-reply', async () => {
    const backend = fakeBackend();
    for (const text of ['תודה', 'ok', '👍', 'נתראה']) {
      const r = await runtime.dispatch(inbound({ text }), { connectionId: 'c', backend, botsDir: TMP });
      expect(r).toMatchObject({ handled: false, reason: 'chatter' });
    }
    expect(backend.sent).toHaveLength(0);
  });

  test('a bot that opts in DOES get the group message and the chatter', async () => {
    runtime.attach('c', 'loud-bot', TMP);
    const backend = fakeBackend();
    await runtime.dispatch(inbound({ isGroup: true, conversationId: '12345@g.us', text: 'small talk' }), { connectionId: 'c', backend, botsDir: TMP });
    await runtime.dispatch(inbound({ text: 'ok' }), { connectionId: 'c', backend, botsDir: TMP });
    expect(global.__CALLS).toHaveLength(2);
    // and its reply goes to the GROUP, not to the sender's DM — the bug ctx exists to make impossible
    expect(backend.sent[0].conversationId).toBe('12345@g.us');
  });

  test('our own echoed message is dropped before any bot sees it', async () => {
    const backend = fakeBackend();
    const r = await runtime.dispatch(inbound({ fromMe: true, text: 'this is my own reply, is it not?' }), { connectionId: 'c', backend, botsDir: TMP });
    expect(r).toMatchObject({ handled: false, reason: 'from_me' });
    expect(backend.sent).toHaveLength(0);
  });

  test('an empty message is not an event', async () => {
    const r = await runtime.dispatch(inbound({ text: null }), { connectionId: 'c', backend: fakeBackend(), botsDir: TMP });
    expect(r.reason).toBe('empty');
  });

  test('an attachment is never chatter, however short its caption', async () => {
    const backend = fakeBackend();
    const r = await runtime.dispatch(
      inbound({ text: '', attachments: [{ kind: 'document', fileName: 'inv.pdf', download: async () => Buffer.from('x') }] }),
      { connectionId: 'c', backend, botsDir: TMP });
    expect(r.handled).toBe(true);
  });

  test('dispatch reports a bot that threw rather than pretending it answered', async () => {
    writeBot('angry-bot', 'module.exports = { id: "angry-bot", async onMessage() { throw new Error("nope"); } };');
    runtime.reset();
    runtime.attach('c', 'angry-bot', TMP);
    const r = await runtime.dispatch(inbound({ text: 'does this explode?' }), { connectionId: 'c', backend: fakeBackend(), botsDir: TMP });
    expect(r).toMatchObject({ handled: false, reason: 'bot_error', botId: 'angry-bot' });
    fs.rmSync(path.join(TMP, 'angry-bot'), { recursive: true, force: true });
    runtime.reset();
  });

  test('a backend without the canonical op is refused instead of crashing mid-reply', async () => {
    runtime.attach('c', 'quiet-bot', TMP);
    const r = await runtime.dispatch(inbound({ text: 'will this work?' }), { connectionId: 'c', backend: {}, botsDir: TMP });
    expect(r.reason).toBe('no_backend');
  });
});

// ── intent, on its own ────────────────────────────────────────────────────────
describe('intent classification', () => {
  const c = (text, over) => intent.classify({ text, attachments: [], ...over });

  test('a trailing question mark is a question, in either width', () => {
    expect(c('מתי התשלום?').kind).toBe('question');
    expect(c('when？').kind).toBe('question');
  });

  test('a bare number is a menu choice — the payload of every menu bot', () => {
    expect(c('1').kind).toBe('menuChoice');
    expect(c('22').kind).toBe('menuChoice');
    expect(c('12345').kind).not.toBe('menuChoice');
  });

  test('slash commands outrank everything textual', () => {
    expect(c('/model sonnet').kind).toBe('command');
    expect(c('/end').kind).toBe('command');
  });

  test('"get me a human" wins over being short', () => {
    expect(c('נציג').kind).toBe('handoff');
    expect(c('human').kind).toBe('handoff');
  });

  test('a link is a link even inside small talk', () => {
    expect(c('see https://x.example/a.pdf').kind).toBe('link');
    expect(c('see https://x.example/a.pdf').hasLink).toBe(true);
  });

  test('long plain text is a statement, short plain text is chatter', () => {
    expect(c('תודה רבה').kind).toBe('chatter');
    expect(c('x'.repeat(intent.CHATTER_MAX_CHARS + 1)).kind).toBe('statement');
  });

  test('an attachment outranks the text entirely', () => {
    expect(c('ok', { attachments: [{ kind: 'document' }] }).kind).toBe('attachment');
  });

  test('shouldAutoReply returns a reason, not a bare false', () => {
    expect(intent.shouldAutoReply({ text: 'is anyone there?', isGroup: true })).toMatchObject({ ok: false, reason: 'group_not_accepted' });
    expect(intent.shouldAutoReply({ text: 'is anyone there?', isGroup: true }, { groups: true })).toMatchObject({ ok: true });
    // the two gates are independent: opting into groups does not opt you into small talk
    expect(intent.shouldAutoReply({ text: 'hi', isGroup: true }, { groups: true })).toMatchObject({ ok: false, reason: 'chatter' });
    expect(intent.shouldAutoReply({ text: 'ok' })).toMatchObject({ ok: false, reason: 'chatter' });
    expect(intent.shouldAutoReply({ text: 'ok' }, { chatter: true })).toMatchObject({ ok: true });
  });
});

// ── ctx construction ──────────────────────────────────────────────────────────
describe('ctx', () => {
  const bot = { id: 'x', name: 'X' };

  test('send goes to the conversation the message came from, never to the sender', async () => {
    const backend = fakeBackend();
    const ctx = runtime.buildCtx(inbound({ isGroup: true, conversationId: 'g@g.us' }), { bot, connectionId: 'c', backend });
    await ctx.send('hi');
    expect(backend.sent[0].conversationId).toBe('g@g.us');
  });

  test('react and typing are no-ops, not crashes, on a backend without them', async () => {
    const ctx = runtime.buildCtx(inbound(), { bot, connectionId: 'c', backend: fakeBackend() });
    await expect(ctx.react('👀')).resolves.toBeNull();
    await expect(ctx.typing(true)).resolves.toBeNull();
    expect(ctx.can('react')).toBe(false);
    expect(ctx.can('send')).toBe(true);
  });

  test('react and typing reach the transport when it has them', async () => {
    const seen = [];
    const ctx = runtime.buildCtx(inbound(), {
      bot, connectionId: 'c', backend: fakeBackend(),
      transport: { react: (m, e) => seen.push(['react', e]), typing: (m, on) => seen.push(['typing', on]) },
    });
    await ctx.react('🚀'); await ctx.typing(true);
    expect(seen).toEqual([['react', '🚀'], ['typing', true]]);
    expect(ctx.can('react')).toBe(true);
  });

  test('a transport whose react throws does not fail the bot turn', async () => {
    const ctx = runtime.buildCtx(inbound(), {
      bot, connectionId: 'c', backend: fakeBackend(),
      transport: { react: () => { throw new Error('no reactions here'); } },
    });
    await expect(ctx.react('👀')).resolves.toBeNull();
  });

  test('sendMenu falls back to plain text where there is no native menu', async () => {
    const backend = fakeBackend();
    const ctx = runtime.buildCtx(inbound(), { bot, connectionId: 'c', backend });
    await ctx.sendMenu({ text: '1) a\n2) b', options: [{ id: '1' }] });
    expect(backend.sent[0].text).toBe('1) a\n2) b');
  });

  test('sendTo addresses a different conversation', async () => {
    const backend = fakeBackend();
    const ctx = runtime.buildCtx(inbound(), { bot, connectionId: 'c', backend });
    await ctx.sendTo('person37@example.com', 'come to the DM');
    expect(backend.sent[0].conversationId).toBe('person37@example.com');
  });

  test('sendLong chunks and numbers the parts', async () => {
    const backend = fakeBackend();
    const ctx = runtime.buildCtx(inbound(), { bot, connectionId: 'c', backend });
    const parts = await ctx.sendLong(('line\n').repeat(2000), { chunkSize: 500, delayMs: 0 });
    expect(parts).toBeGreaterThan(1);
    expect(backend.sent).toHaveLength(parts);
    expect(backend.sent[0].text.startsWith(`(1/${parts})\n`)).toBe(true);
  });

  test('a short reply is sent whole, with no part header', async () => {
    const backend = fakeBackend();
    const ctx = runtime.buildCtx(inbound(), { bot, connectionId: 'c', backend });
    expect(await ctx.sendLong('short', { delayMs: 0 })).toBe(1);
    expect(backend.sent[0].text).toBe('short');
  });
});
