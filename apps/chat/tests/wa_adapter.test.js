/**
 * The WhatsApp side of the seam: `src/whatsapp/chat_bot.js`.
 *
 * After the port this file is an ADAPTER, not a bot. Its whole job is to turn a Baileys frame into the
 * normalised message the runtime expects, and it is the only place left in the app that knows a `@g.us`
 * from a `@lid`. Those rules are exactly the kind that rot silently — a LID message that fails to
 * resolve is not an error, it is a customer whose messages stop being answered — so they are pinned
 * here rather than trusted to review.
 */
jest.mock('../src/data/subscribers', () => ({
  getOrCreateSubscriber: jest.fn(async () => ({ phoneNumber: 'x', fullName: 'x', state: null })),
  setSubscriberState: jest.fn(async () => {}), updateSubscriber: jest.fn(async () => {}),
  readSubscribers: jest.fn(async () => []), getSubscriber: jest.fn(async () => null),
}));
jest.mock('../src/services/settings_api', () => ({
  isAdmin: jest.fn(async () => false), loadSettings: jest.fn(async () => ({})),
  getSettings: jest.fn(() => ({})), getAdmins: jest.fn(() => []),
}));
jest.mock('../src/services/document_processing', () => ({ processGeneralDocument: jest.fn(), processBalanceSheet: jest.fn(), processLinkDocument: jest.fn() }));
jest.mock('../src/services/companies_api', () => ({ findCompanyByInput: jest.fn(), fetchCompanies: jest.fn(async () => []) }));
jest.mock('../src/services/agent_runner', () => ({ runAgentJob: jest.fn(), getAgentStatus: jest.fn(), cancelAgentJob: jest.fn(), AgentRunnerBusyError: class extends Error {} }));
jest.mock('../src/services/agent_chat', () => ({ chatTurn: jest.fn(), AgentRunnerBusyError: class extends Error {} }));
jest.mock('../src/services/automations_chat', () => ({ automationsTurn: jest.fn() }));
jest.mock('../src/services/dispatcher_client', () => ({ dispatch: jest.fn(), DispatcherBusyError: class extends Error {} }));
jest.mock('../src/services/currency', () => ({ convertUsdToIls: jest.fn(async () => ({ formatted: '₪0' })) }));
jest.mock('../src/services/sentry', () => ({ Sentry: { captureException: jest.fn() }, initSentry: jest.fn() }));

const wa = require('../src/whatsapp/chat_bot');

const frame = (over = {}) => ({
  key: { id: 'wamid.X', remoteJid: 'person32@example.com', fromMe: false, ...(over.key || {}) },
  message: over.message !== undefined ? over.message : { conversation: 'שלום' },
  pushName: over.pushName !== undefined ? over.pushName : 'משה',
  messageTimestamp: over.messageTimestamp !== undefined ? over.messageTimestamp : 1785000000,
});

describe('routing', () => {
  test('a DM becomes a 1:1 conversation keyed by the phone number', () => {
    const m = wa.normalise(frame());
    expect(m).toMatchObject({ conversationId: 'person32@example.com', isGroup: false, fromMe: false });
    expect(m.sender).toEqual({ id: '050-000-0006', name: 'משה' });
    expect(m.text).toBe('שלום');
    expect(m.timestamp).toBeInstanceOf(Date);
  });

  test('a group keeps the GROUP as the conversation and the PARTICIPANT as the sender', () => {
    // this is the split that used to force two near-identical handlers; the normalised shape carries
    // both, so one handler can reply to the group while tracking state per person
    const m = wa.normalise(frame({ key: { remoteJid: '12345@g.us', participant: 'person41@example.com' } }));
    expect(m.conversationId).toBe('12345@g.us');
    expect(m.isGroup).toBe(true);
    expect(m.sender.id).toBe('050-000-0012');
  });

  test('a LID-addressed DM is resolved through remoteJidAlt', () => {
    const m = wa.normalise(frame({ key: { remoteJid: '999@lid', remoteJidAlt: 'person32@example.com' } }));
    expect(m.conversationId).toBe('person32@example.com');
    expect(m.isGroup).toBe(false);
  });

  test('a LID with no usable alt is skipped rather than answered at a wrong address', () => {
    expect(wa.normalise(frame({ key: { remoteJid: '999@lid' } }))).toBeNull();
  });

  test('a LID participant in a group falls back to participantAlt, and is skipped without one', () => {
    const ok = wa.normalise(frame({ key: { remoteJid: '12345@g.us', participant: '888@lid', participantAlt: 'person41@example.com' } }));
    expect(ok.sender.id).toBe('050-000-0012');
    expect(wa.normalise(frame({ key: { remoteJid: '12345@g.us', participant: '888@lid' } }))).toBeNull();
  });

  test('broadcasts and unknown jid types are not ours', () => {
    expect(wa.normalise(frame({ key: { remoteJid: 'status@broadcast' } }))).toBeNull();
  });

  test('our own echo is normalised with fromMe set — the runtime is what drops it', () => {
    expect(wa.normalise(frame({ key: { fromMe: true } })).fromMe).toBe(true);
  });
});

describe('message shape flattening', () => {
  test('both text carriers collapse into msg.text', () => {
    expect(wa.extractMessageText({ message: { conversation: 'a' } })).toBe('a');
    expect(wa.extractMessageText({ message: { extendedTextMessage: { text: 'b' } } })).toBe('b');
    expect(wa.extractMessageText({ message: { imageMessage: {} } })).toBeNull();
  });

  test('a plain document becomes one normalised attachment', () => {
    const [att] = wa.attachmentsOf({ message: { documentMessage: { fileName: 'inv.pdf', mimetype: 'application/pdf', caption: 'חשבונית', fileLength: 12 } } });
    expect(att).toMatchObject({ kind: 'document', fileName: 'inv.pdf', mimeType: 'application/pdf', caption: 'חשבונית', size: 12 });
    expect(typeof att.download).toBe('function');
  });

  test('a document wrapped in a withCaption container is unwrapped, not lost', () => {
    // the wrapper WhatsApp introduced for captioned documents; missing it meant "unsupported media type"
    const [att] = wa.attachmentsOf({ message: { documentWithCaptionMessage: { message: { documentMessage: { fileName: 'a.pdf', mimetype: 'application/pdf' } } } } });
    expect(att.kind).toBe('document');
    expect(att.fileName).toBe('a.pdf');
  });

  test('an image is an attachment too', () => {
    const [att] = wa.attachmentsOf({ message: { imageMessage: { mimetype: 'image/jpeg', caption: 'קבלה' } } });
    expect(att.kind).toBe('image');
  });

  test('a text-only message has no attachments', () => {
    expect(wa.attachmentsOf({ message: { conversation: 'hi' } })).toEqual([]);
  });
});

describe('the backend and transport it presents to the runtime', () => {
  test('the backend exposes the canonical op and sends to the conversation id', async () => {
    const sock = { sendMessage: jest.fn(async () => ({})) };
    await wa.backendFor(sock).sendMessage('12345@g.us', { text: 'hi' });
    expect(sock.sendMessage).toHaveBeenCalledWith('12345@g.us', { text: 'hi' });
  });

  test('a bare phone number still resolves to a JID, so legacy callers keep working', async () => {
    const sock = { sendMessage: jest.fn(async () => ({})) };
    await wa.backendFor(sock).sendMessage('050-000-0006', { text: 'hi' });
    expect(sock.sendMessage).toHaveBeenCalledWith('person32@example.com', { text: 'hi' });
  });

  test('react and typing map onto the Baileys calls they replaced', async () => {
    const sock = { sendMessage: jest.fn(async () => ({})), sendPresenceUpdate: jest.fn(async () => ({})) };
    const t = wa.transportFor(sock);
    const msg = wa.normalise(frame());
    await t.react(msg, '👀');
    expect(sock.sendMessage).toHaveBeenCalledWith(msg.conversationId, { react: { text: '👀', key: msg.raw.key } });
    await t.typing(msg, true);
    expect(sock.sendPresenceUpdate).toHaveBeenCalledWith('composing', msg.conversationId);
    await t.typing(msg, false);
    expect(sock.sendPresenceUpdate).toHaveBeenLastCalledWith('paused', msg.conversationId);
  });
});

describe('back-compat', () => {
  test('onMessage keeps its (sock, message) signature so baileyes_app.js is untouched', () => {
    expect(typeof wa.onMessage).toBe('function');
    expect(wa.onMessage.length).toBe(2);
  });

  test('STATES is still re-exported from this path', () => {
    expect(wa.STATES.AWAIT_BALANCE_SHEET_FILE).toBe('await_balance_sheet_file');
  });

  test('it dispatches to the bot attached to the WhatsApp connection', async () => {
    const runtime = require('../bots/chat_bot');
    const spy = jest.spyOn(runtime, 'dispatch').mockResolvedValue({ handled: true });
    const sock = { sendMessage: jest.fn(), sendPresenceUpdate: jest.fn() };
    await wa.onMessage(sock, frame());
    expect(spy).toHaveBeenCalledWith(
      expect.objectContaining({ conversationId: 'person32@example.com' }),
      expect.objectContaining({ connectionId: wa.WA_CONNECTION_ID }));
    spy.mockRestore();
  });

  test('an empty frame is ignored without reaching the runtime', async () => {
    const runtime = require('../bots/chat_bot');
    const spy = jest.spyOn(runtime, 'dispatch');
    await wa.onMessage({}, frame({ message: null }));
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });
});
