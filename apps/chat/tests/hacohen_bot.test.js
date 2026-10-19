/**
 * The ported hacohen-bot, driven END TO END through the real runtime with a fake ctx.
 *
 * "End to end" here means: a normalised inbound message goes into `runtime.dispatch`, the runtime
 * discovers the bot from the real `bots/` directory, builds a ctx from a fake backend whose only
 * method is `sendMessage(conversationId, {text})`, and the bot runs its actual state machine — daily
 * limit, subscriber lookup, state routing, attachment download, document processing, reply + menu.
 * NOTHING about WhatsApp is present. If this passes, the same bot runs on local chat and Telegram.
 *
 * The mocked modules are the ones that reach the network or the disk-backed subscriber store. They are
 * the bot's *services*, not its transport — which is exactly the distinction this stage draws.
 */
const fs = require('fs');
const os = require('os');
const path = require('path');

jest.mock('../src/services/settings_api', () => ({
  isAdmin: jest.fn(async () => true),
  loadSettings: jest.fn(async () => ({})),
  getSettings: jest.fn(() => ({})),
  getAdmins: jest.fn(() => []),
}));
jest.mock('../src/data/subscribers', () => ({
  getOrCreateSubscriber: jest.fn(),
  setSubscriberState: jest.fn(async () => {}),
  updateSubscriber: jest.fn(async () => {}),
  readSubscribers: jest.fn(async () => []),
  getSubscriber: jest.fn(async () => null),
}));
jest.mock('../src/services/document_processing', () => ({
  processGeneralDocument: jest.fn(),
  processBalanceSheet: jest.fn(),
  processLinkDocument: jest.fn(),
}));
jest.mock('../src/services/companies_api', () => ({
  findCompanyByInput: jest.fn(() => null),
  fetchCompanies: jest.fn(async () => []),
}));
jest.mock('../src/services/agent_runner', () => ({
  runAgentJob: jest.fn(),
  getAgentStatus: jest.fn(async () => ({ current: null, model: 'test-model' })),
  cancelAgentJob: jest.fn(async () => ({ idle: true })),
  AgentRunnerBusyError: class AgentRunnerBusyError extends Error {},
}));
jest.mock('../src/services/agent_chat', () => ({
  chatTurn: jest.fn(),
  AgentRunnerBusyError: class AgentChatBusyError extends Error {},
}));
jest.mock('../src/services/automations_chat', () => ({ automationsTurn: jest.fn() }));
jest.mock('../src/services/dispatcher_client', () => ({
  dispatch: jest.fn(),
  DispatcherBusyError: class DispatcherBusyError extends Error {},
}));
jest.mock('../src/services/currency', () => ({
  convertUsdToIls: jest.fn(async (usd) => ({ formatted: `₪${(usd * 3.7).toFixed(2)}` })),
}));
jest.mock('../src/services/sentry', () => ({ Sentry: { captureException: jest.fn() }, initSentry: jest.fn() }));

const runtime = require('../bots/chat_bot');
const { TEXTS, CONFIG } = require('../src/config');
const { isAdmin } = require('../src/services/settings_api');
const subs = require('../src/data/subscribers');
const docs = require('../src/services/document_processing');
const companies = require('../src/services/companies_api');
const agentRunner = require('../src/services/agent_runner');
const { UnableToGuessCompany } = require('../src/errors');
const { _resetDailyCounts } = require('../bots/hacohen-bot/daily_limit');

// The id the connections service ACTUALLY issues (connections_client.LOCAL_ID) — deliberately NOT
// WhatsApp. This file previously used 'local-chat', a name nothing in the system ever mints; the
// default-wiring test below therefore passed against a default that could never fire in production.
const CONN = 'chat_local-local';
const DM = 'conv-dm-1';                        // an opaque conversation id; no JID anywhere in this file
const GROUP = 'conv-group-1';
const SENDER = { id: 'u-4711', name: 'משה כהן' };

let UPLOADS;

/** The abstract backend: one canonical op. */
function fakeBackend() {
  const sent = [];
  return { sent, texts: () => sent.map((s) => s.text), async sendMessage(conversationId, p) { sent.push({ conversationId, ...p }); return { id: 's' }; } };
}

function inbound(over = {}) {
  return {
    id: 'msg-1', conversationId: DM, isGroup: false, fromMe: false,
    sender: { ...SENDER }, text: null, timestamp: new Date('2026-07-29T09:00:00Z'),
    attachments: [], raw: {}, ...over,
  };
}

/** A normalised attachment — `download()` is the seam the transport fills in. */
function attachment(over = {}) {
  return {
    kind: 'document', fileName: 'חשבונית 20458.pdf', mimeType: 'application/pdf',
    caption: 'חשבונית ספק', size: 12,
    download: jest.fn(async () => Buffer.from('%PDF-1.4 fake')),
    ...over,
  };
}

const send = (msg, opts = {}) => runtime.dispatch(msg, { connectionId: CONN, backend: opts.backend, transport: opts.transport || {} });

beforeAll(() => {
  UPLOADS = fs.mkdtempSync(path.join(os.tmpdir(), 'hacohen-uploads-'));
  CONFIG.UPLOADS_DIR = UPLOADS;
  runtime.loadBots();                       // the REAL bots/ directory
});
afterAll(() => { try { fs.rmSync(UPLOADS, { recursive: true, force: true }); } catch { /* best effort */ } });

beforeEach(() => {
  jest.clearAllMocks();
  _resetDailyCounts();
  isAdmin.mockResolvedValue(true);
  subs.getOrCreateSubscriber.mockResolvedValue({ phoneNumber: SENDER.id, fullName: SENDER.name, state: null });
  runtime.reset();
  runtime.loadBots();
});

// ── wiring ────────────────────────────────────────────────────────────────────
describe('default wiring', () => {
  test('hacohen-bot is discovered from the real bots directory', () => {
    expect(runtime.loadBots().has('hacohen-bot')).toBe(true);
    const entry = runtime.listBots().find((b) => b.id === 'hacohen-bot');
    expect(entry.name).toBe('בוט הכהנים');
    // it opts into both gates and says why in its manifest
    expect(entry.accepts).toEqual({ groups: true, chatter: true });
  });

  test('it is attached to local chat by default — and to the live WhatsApp connection too', () => {
    expect(runtime.attachedTo('chat_local-local')).toBe('hacohen-bot');
    // A WhatsApp instance id carries a hash minted when the operator adds the account, so the default
    // has to hold for ANY id of that protocol. This is the assertion that protects the live number.
    expect(runtime.attachedTo('chat_wa_baileys-20150caa')).toBe('hacohen-bot');
    expect(runtime.attachedTo('chat_wa_baileys-ffffffff')).toBe('hacohen-bot');
  });

  test('a protocol with no default answers with no bot rather than guessing one', () => {
    expect(runtime.attachedTo('chat_tg_bot-abcd1234')).toBe('none');
  });

  test('turning the bot off sticks — an explicit none outranks the protocol default', () => {
    // The failure this guards against is silent: if `none` were stored by deleting the key, the next
    // read would fall through to the default and the bot would start answering again on its own.
    runtime.detach('chat_wa_baileys-20150caa');
    expect(runtime.attachedTo('chat_wa_baileys-20150caa')).toBe('none');
    expect(runtime.attachedTo('chat_wa_baileys-ffffffff')).toBe('hacohen-bot');  // untouched
    runtime.attach('chat_wa_baileys-20150caa', 'hacohen-bot');
  });
});

// ── THE END-TO-END PROOF ──────────────────────────────────────────────────────
describe('E2E: an admin drops an invoice into the chat (auto-intake)', () => {
  test('the document is downloaded, saved, processed and acknowledged — with no transport in sight', async () => {
    docs.processGeneralDocument.mockResolvedValue({
      companyGuess: { companyName: 'ישראל קרטון בע״מ' },
      ids: { document_id: 'INV-20458', document_type: 'invoice' },
      driveLink: 'https://drive.example/d/20458',
    });

    const backend = fakeBackend();
    const att = attachment();
    const r = await send(inbound({ attachments: [att] }), { backend });

    expect(r).toMatchObject({ handled: true, botId: 'hacohen-bot' });

    // 1. the transport-supplied download() closure was the ONLY way bytes entered the bot
    expect(att.download).toHaveBeenCalledTimes(1);

    // 2. the bytes landed on disk under a normalised, filesystem-safe name
    const written = fs.readdirSync(UPLOADS);
    expect(written).toHaveLength(1);
    expect(written[0]).toMatch(/^\d+_.+\.pdf$/);
    expect(fs.readFileSync(path.join(UPLOADS, written[0])).toString()).toBe('%PDF-1.4 fake');

    // 3. the real service was called with the caption as context and the message's own date
    expect(docs.processGeneralDocument).toHaveBeenCalledWith(expect.objectContaining({
      textContext: 'חשבונית ספק',
      filePath: path.join(UPLOADS, written[0]),
      senderId: SENDER.id,
      messageDate: new Date('2026-07-29T09:00:00Z'),
    }));

    // 4. the user got the ack, the summary and the menu — all in THIS conversation
    const texts = backend.texts();
    expect(texts[0]).toBe(TEXTS.AUTO_INTAKE_DOC);
    expect(texts[1]).toContain(TEXTS.GENERIC_DOC_RECEIVED_PREFIX);
    expect(texts[1]).toContain('ישראל קרטון בע״מ');
    expect(texts[1]).toContain('INV-20458');
    expect(texts[1]).toContain('https://drive.example/d/20458');
    expect(texts[2]).toContain(TEXTS.MENU_TEXT.slice(0, 20));
    expect(backend.sent.every((s) => s.conversationId === DM)).toBe(true);
  });

  test('a non-admin dropping a document is not served — they get the menu', async () => {
    isAdmin.mockResolvedValue(false);
    const backend = fakeBackend();
    const att = attachment();
    await send(inbound({ attachments: [att] }), { backend });
    expect(att.download).not.toHaveBeenCalled();
    expect(docs.processGeneralDocument).not.toHaveBeenCalled();
    expect(backend.texts()[0]).toBe(TEXTS.INVALID_OPTION);
  });

  test('a failing document processor apologises instead of going silent', async () => {
    docs.processGeneralDocument.mockRejectedValue(new Error('OCR endpoint down'));
    const backend = fakeBackend();
    await send(inbound({ attachments: [attachment()] }), { backend });
    expect(backend.texts()[1]).toBe(TEXTS.ERROR_GENERIC_DOC_PREFIX + 'OCR endpoint down');
  });
});

// ── the multi-turn flow that has real state in it ─────────────────────────────
describe('E2E: the balance-sheet flow across three turns', () => {
  test('menu 10 → file → company, with the company asked for only when it cannot be guessed', async () => {
    const backend = fakeBackend();

    // turn 1: the admin picks menu 10
    await send(inbound({ text: '10' }), { backend });
    expect(subs.updateSubscriber).toHaveBeenCalledWith(SENDER.id, expect.objectContaining({ state: 'await_balance_sheet_file' }));
    expect(backend.texts()).toContain(TEXTS.PROMPT_BALANCE_SHEET_FILE);

    // turn 2: they send the file, and the company cannot be guessed
    subs.getOrCreateSubscriber.mockResolvedValue({ phoneNumber: SENDER.id, fullName: SENDER.name, state: 'await_balance_sheet_file' });
    docs.processBalanceSheet.mockRejectedValueOnce(new UnableToGuessCompany('no match'));
    const b2 = fakeBackend();
    await send(inbound({ attachments: [attachment({ fileName: 'aging.xlsx', mimeType: 'application/vnd.ms-excel', caption: '' })] }), { backend: b2 });
    expect(b2.texts()).toContain(TEXTS.PROCESSING_BALANCE_SHEET);
    expect(b2.texts()).toContain(TEXTS.UNABLE_TO_GUESS_COMPANY);
    const stashed = subs.updateSubscriber.mock.calls.at(-1)[1];
    expect(stashed.state).toBe('await_balance_sheet_company');
    expect(stashed.pending_balance_file).toMatch(/aging\.xlsx$/);

    // turn 3: they name the company, and the stashed file is processed
    subs.getOrCreateSubscriber.mockResolvedValue({
      phoneNumber: SENDER.id, fullName: SENDER.name,
      state: 'await_balance_sheet_company', pending_balance_file: stashed.pending_balance_file,
    });
    companies.findCompanyByInput.mockReturnValue({ companyName: 'ישראל קרטון בע״מ', companyId: '514' });
    docs.processBalanceSheet.mockResolvedValueOnce({ companyGuess: { companyName: 'ישראל קרטון בע״מ' }, driveLink: 'https://drive.example/bs' });
    const b3 = fakeBackend();
    await send(inbound({ text: 'ישראל קרטון' }), { backend: b3 });
    expect(docs.processBalanceSheet).toHaveBeenLastCalledWith(expect.objectContaining({
      filePath: stashed.pending_balance_file,
      explicitCompany: { companyName: 'ישראל קרטון בע״מ', companyId: '514' },
    }));
    expect(b3.texts()[0]).toContain(TEXTS.BALANCE_SHEET_RECEIVED_PREFIX);
    expect(b3.texts()[0]).toContain('https://drive.example/bs');
  });

  test('"ביטול" mid-flow clears the state and returns the menu', async () => {
    subs.getOrCreateSubscriber.mockResolvedValue({ phoneNumber: SENDER.id, fullName: SENDER.name, state: 'await_balance_sheet_file' });
    const backend = fakeBackend();
    await send(inbound({ text: 'ביטול' }), { backend });
    expect(subs.setSubscriberState).toHaveBeenCalledWith(SENDER.id, null);
    expect(backend.texts()[0]).toBe(TEXTS.CANCELLED);
  });

  test('a stale awaiting state older than 24h falls back to the menu instead of eating the message', async () => {
    subs.getOrCreateSubscriber.mockResolvedValue({
      phoneNumber: SENDER.id, fullName: SENDER.name,
      state: 'await_generic_document_file', stateChangedAt: Date.now() - 25 * 3600 * 1000,
    });
    const backend = fakeBackend();
    await send(inbound({ text: '2' }), { backend });
    expect(backend.texts()[0]).toBe(TEXTS.ABOUT_BOT);
  });
});

// ── menu + admin surfaces ─────────────────────────────────────────────────────
describe('menu', () => {
  test('a brand-new subscriber is welcomed and shown the menu', async () => {
    subs.getOrCreateSubscriber.mockResolvedValue({ phoneNumber: SENDER.id, fullName: SENDER.name, state: 'new' });
    const backend = fakeBackend();
    await send(inbound({ text: 'שלום' }), { backend });
    expect(backend.texts()[0]).toBe(TEXTS.WELCOME_MESSAGE);
  });

  test('menu 1 greets by name; the menu carries the version in a DM', async () => {
    const backend = fakeBackend();
    await send(inbound({ text: '1' }), { backend });
    expect(backend.texts()[0]).toBe(TEXTS.HELLO_BACK.replace('{name}', SENDER.name));
    expect(backend.texts()[1]).toContain(`v${CONFIG.APP_VERSION}`);
  });

  test('the admin block only appears for an admin', async () => {
    isAdmin.mockResolvedValue(false);
    const backend = fakeBackend();
    await send(inbound({ text: '2' }), { backend });
    expect(backend.texts()[1]).not.toContain(TEXTS.ADMIN_MENU_TEXT.slice(0, 20));
  });

  test('menu 17 reports agent-runner status (an admin surface that survived the port)', async () => {
    agentRunner.getAgentStatus.mockResolvedValue({ current: null, model: 'deepseek-chat' });
    const backend = fakeBackend();
    await send(inbound({ text: '17' }), { backend });
    expect(backend.texts()[0]).toContain(TEXTS.AGENT_STATUS_IDLE);
    expect(backend.texts()[0]).toContain('deepseek-chat');
  });

  test('a non-admin pressing an admin number gets the invalid-option menu, not the action', async () => {
    isAdmin.mockResolvedValue(false);
    const backend = fakeBackend();
    await send(inbound({ text: '17' }), { backend });
    expect(agentRunner.getAgentStatus).not.toHaveBeenCalled();
    expect(backend.texts()[0]).toBe(TEXTS.INVALID_OPTION);
  });

  test('a bare URL from an admin is intaken automatically', async () => {
    docs.processLinkDocument.mockResolvedValue({ companyGuess: { companyName: 'ספק' }, ids: null, driveLink: 'https://drive.example/l' });
    const backend = fakeBackend();
    await send(inbound({ text: 'https://supplier.example/invoice/998' }), { backend });
    expect(docs.processLinkDocument).toHaveBeenCalledWith(expect.objectContaining({ url: 'https://supplier.example/invoice/998' }));
    expect(backend.texts()[0]).toBe(TEXTS.AUTO_INTAKE_LINK);
    expect(backend.texts()[1]).toContain(TEXTS.LINK_DOC_RECEIVED_PREFIX);
  });
});

// ── groups ────────────────────────────────────────────────────────────────────
describe('groups', () => {
  const groupMsg = (over) => inbound({ isGroup: true, conversationId: GROUP, ...over });

  test('random group chatter gets NO reply — even from an admin', async () => {
    const backend = fakeBackend();
    for (const text of ['מישהו זמין לסגור את דוח המע״מ להיום?', 'תודה רחל', 'מעולה 🙌', 'בסדר גמור, נדבר מחר בבוקר']) {
      await send(groupMsg({ text }), { backend });
    }
    expect(backend.sent).toHaveLength(0);
  });

  test('a known menu number IS answered, in the group and without the version suffix', async () => {
    const backend = fakeBackend();
    await send(groupMsg({ text: '2' }), { backend });
    expect(backend.texts()[0]).toBe(TEXTS.ABOUT_BOT);
    expect(backend.texts()[1]).not.toContain(`v${CONFIG.APP_VERSION}`);
    expect(backend.sent.every((s) => s.conversationId === GROUP)).toBe(true);
  });

  test('an admin document in a group IS intaken, and answered in the group', async () => {
    docs.processGeneralDocument.mockResolvedValue({ companyGuess: { companyName: 'ספק' }, ids: null, driveLink: null });
    const backend = fakeBackend();
    const att = attachment();
    await send(groupMsg({ attachments: [att] }), { backend });
    expect(att.download).toHaveBeenCalled();
    expect(backend.texts()[0]).toBe(TEXTS.AUTO_INTAKE_DOC);
    expect(backend.sent.every((s) => s.conversationId === GROUP)).toBe(true);
  });

  test('admin document menus are refused in a group and pushed to the DM', async () => {
    const backend = fakeBackend();
    await send(groupMsg({ text: '11' }), { backend });
    expect(backend.texts()[0]).toContain('רק בצ\'אט פרטי');
    expect(subs.updateSubscriber).not.toHaveBeenCalled();
  });

  test('the group never runs the DM state machine — an in-flight upload state is not resumed there', async () => {
    subs.getOrCreateSubscriber.mockResolvedValue({ phoneNumber: SENDER.id, fullName: SENDER.name, state: 'await_link_document' });
    const backend = fakeBackend();
    await send(groupMsg({ text: 'סתם משפט ארוך בקבוצה שלא אמור לעניין את הבוט' }), { backend });
    expect(backend.sent).toHaveLength(0);
    expect(docs.processLinkDocument).not.toHaveBeenCalled();
  });
});

// ── the daily cap and the reaction/presence capabilities ──────────────────────
describe('cross-cutting behaviour that had to survive the port', () => {
  test('over the daily cap the sender is warned once and then served nothing', async () => {
    const backend = fakeBackend();
    const limit = CONFIG.DAILY_MESSAGE_LIMIT;
    for (let i = 0; i < limit + 3; i++) await send(inbound({ text: '2' }), { backend });
    const warnings = backend.texts().filter((t) => t === TEXTS.DAILY_MESSAGE_LIMIT_REACHED);
    expect(warnings).toHaveLength(1);              // warned once, not on every further message
    const abouts = backend.texts().filter((t) => t === TEXTS.ABOUT_BOT);
    expect(abouts).toHaveLength(limit - 1);        // served up to the cap, then stopped
  });

  test('the agent chat acks with a reaction where the transport has one, and works where it does not', async () => {
    const { chatTurn } = require('../src/services/agent_chat');
    chatTurn.mockResolvedValue({ text: 'the stack is healthy', sessionId: 's1', toolUseCount: 3, stats: { total_cost_usd: 0.01, duration_ms: 4000 } });
    subs.getOrCreateSubscriber.mockResolvedValue({ phoneNumber: SENDER.id, fullName: SENDER.name, state: 'agent_chat' });
    // seed the in-memory session the state refers to
    require('../bots/hacohen-bot/agent_sessions')._agentChatSessions.set(SENDER.id, {
      sessionId: null, lastActiveAt: Date.now(), totalCost: 0, turnCount: 0, turnInFlight: false, model: 'deepseek-chat',
    });

    const reacted = [];
    const backend = fakeBackend();
    await send(inbound({ text: 'is the stack healthy?' }), {
      backend, transport: { react: (m, e) => reacted.push(e), typing: () => {} },
    });
    expect(reacted).toEqual(['👀']);
    expect(backend.texts()[0]).toBe('the stack is healthy');
    expect(backend.texts()[1]).toContain('[deepseek-chat]');

    // and again with a backend that has NO reactions at all — same answer, no crash
    require('../bots/hacohen-bot/agent_sessions')._agentChatSessions.set(SENDER.id, {
      sessionId: null, lastActiveAt: Date.now(), totalCost: 0, turnCount: 0, turnInFlight: false, model: 'deepseek-chat',
    });
    const b2 = fakeBackend();
    await send(inbound({ text: 'is the stack still healthy?' }), { backend: b2 });
    expect(b2.texts()[0]).toBe('the stack is healthy');
  });
});
