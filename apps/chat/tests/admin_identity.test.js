/**
 * Who counts as an admin, across two kinds of identity.
 *
 * The admin gate was written when the only transport was WhatsApp and every sender WAS a phone
 * number, so it pushed each value through normalizePhone(). That strips non-digits and returns ''
 * for anything else — which means every private-engine identity (`me`, `bot-user`, `u_dvir`) was
 * silently dropped from the list AND from the comparison. The effect was not an error: the bot's
 * admin-only menu simply never appeared on local chat, while the setting's own label promised
 * "מספרים או מזהי משתמש".
 *
 * These tests pin BOTH shapes, because fixing one and breaking the other is the easy mistake: a
 * phone must still normalise (050-000-0007 and 050-000-0007 are the same admin) and an engine id
 * must survive as itself.
 */
const settings = require('../src/services/settings_api');

beforeEach(() => settings.setBotAdmins([]));

describe('canonAdmin', () => {
  test('a phone number normalises, in any of the shapes people type', () => {
    expect(settings.canonAdmin('050-000-0007')).toBe('050-000-0007');
    expect(settings.canonAdmin('050-000-0007')).toBe('050-000-0007');
    expect(settings.canonAdmin(' 050-000-0007 ')).toBe('050-000-0007');
  });

  test('a private-engine user id survives as ITSELF instead of becoming empty', () => {
    expect(settings.canonAdmin('me')).toBe('me');
    expect(settings.canonAdmin('bot-user')).toBe('bot-user');
    expect(settings.canonAdmin('u_dvir')).toBe('u_dvir');
  });

  test('nothing in, nothing out', () => {
    expect(settings.canonAdmin('')).toBe('');
    expect(settings.canonAdmin(null)).toBe('');
    expect(settings.canonAdmin(undefined)).toBe('');
  });
});

describe('setBotAdmins / isAdmin', () => {
  test('a list may mix engine ids and phone numbers', () => {
    expect(settings.setBotAdmins('me, bot-user, 050-000-0007'))
      .toEqual(['me', 'bot-user', '050-000-0007']);
  });

  test('an engine identity is recognised — the case that could not work before', async () => {
    settings.setBotAdmins(['bot-user']);
    expect(await settings.isAdmin('bot-user')).toBe(true);
  });

  test('a phone still matches however the sender spells it', async () => {
    settings.setBotAdmins(['050-000-0007']);
    expect(await settings.isAdmin('050-000-0007')).toBe(true);
    expect(await settings.isAdmin('050-000-0007')).toBe(true);
  });

  test('someone not on the list is not an admin', async () => {
    settings.setBotAdmins(['bot-user']);
    expect(await settings.isAdmin('stranger')).toBe(false);
    expect(await settings.isAdmin('')).toBe(false);
  });

  test('an empty list does not by itself make anyone an admin', async () => {
    settings.setBotAdmins([]);
    expect(await settings.isAdmin('nobody-in-any-source')).toBe(false);
  });

  test('separators people actually use all work', () => {
    expect(settings.setBotAdmins('me;bot-user  u_dvir,rachel'))
      .toEqual(['me', 'bot-user', 'u_dvir', 'rachel']);
  });
});
