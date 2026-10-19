const axios = require('axios');
const { CONFIG } = require('../config');
const { normalizePhone } = require('../utils/phone');

// In-memory settings cache — loaded once at startup and on explicit reload
let settingsCache = { whatsapp_admins: [] };
let settingsLoaded = false;

const loadSettings = async () => {
  console.log('[integration] Fetching settings...');
  if (!CONFIG.N8N_SETTINGS_WEBHOOK) {
    throw new Error('Missing CONFIG.N8N_SETTINGS_WEBHOOK');
  }
  // Legacy source, tenant-scoped since the 2026-08-28 cutover: without ?__instance= the
  // settings chain THROWS server-side, so a tenantless call is not a soft miss here — it is
  // an error execution in n8n on every startup and reload. No tenant configured -> skip; the
  // chat-owned botAdmins + CONFIG.ADMINS remain the working sources (see getAdmins).
  if (!CONFIG.INDOX_INSTANCE) {
    console.log('[integration] legacy settings source skipped (INDOX_INSTANCE not set)');
    return settingsCache;
  }
  try {
    const res = await axios.get(CONFIG.N8N_SETTINGS_WEBHOOK, {
      timeout: 60000,
      params: { key: 'whatsapp_admins', TRIGGERED_FROM: 'WHATSAPP_BOT',
                __instance: CONFIG.INDOX_INSTANCE },
      auth: { username: CONFIG.N8N_SETTINGS_USER, password: CONFIG.N8N_SETTINGS_PASS }
    });

    const admins = res.data?.val;
    if (!Array.isArray(admins)) {
      throw new Error('Unable to get admins list from settings');
    }
    settingsCache = { whatsapp_admins: admins.map(a => normalizePhone(String(a))) };
    settingsLoaded = true;
    console.log(`[integration] Loaded settings. Admins: ${settingsCache.whatsapp_admins.length}`, settingsCache.whatsapp_admins);
  } catch (e) {
    console.error('[integration] Failed to fetch settings', e.message);
  }
  return settingsCache;
};

const getSettings = () => settingsCache;

/**
 * Admins declared by the BOT ITSELF, per connection, from the chat app's own settings store.
 *
 * This is the chat-owned source and it wins. The list used to live only in an n8n KV
 * (`key_val_settings`, reached over the `setting` webhook) — which is neither chat's store nor
 * indox's, so who owned the bot's own admin list was answered by a third service. A bot's
 * configuration belongs to the bot.
 *
 * Set per dispatch from `ctx.settings`, so two connections can genuinely have different admins —
 * which is the point of per-connection settings and is impossible with one global KV key.
 * An EMPTY list is not "no admins": it means this bot declares none here, and the legacy source
 * still speaks. Clearing the list must not silently lock every admin out of a live deployment.
 */
let botAdmins = [];

/**
 * Canonical form of ONE admin entry — a phone number where it is one, the id itself where it is not.
 *
 * normalizePhone() strips every non-digit, so it returns '' for anything that is not a phone. That
 * was fine while the only transport was WhatsApp and every sender WAS a phone number. It is wrong
 * for the private engine, whose identities are user ids like `me` or `bot-user`: every one of them
 * normalised to '' and was dropped, so no local identity could ever be an admin and the bot's
 * admin-only menu could never appear on local chat — while the setting's own label promises
 * "מספרים או מזהי משתמש".
 *
 * Falling back to the raw id keeps WhatsApp behaviour byte-identical (a phone still normalises) and
 * makes a private-engine id work as itself.
 */
const canonAdmin = (value) => {
  const raw = String(value || '').trim();
  if (!raw) return '';
  return normalizePhone(raw) || raw;
};

const setBotAdmins = (list) => {
  botAdmins = (Array.isArray(list) ? list : String(list || '').split(/[\s,;]+/))
    .map(canonAdmin)
    .filter(Boolean);
  return botAdmins;
};

const getAdmins = async () => {
    const configAdmins = (CONFIG.ADMINS || []).map(canonAdmin);
    const settingsAdmins = (getSettings().whatsapp_admins || []).map(canonAdmin);
    const allAdmins = Array.from(new Set([...botAdmins, ...configAdmins, ...settingsAdmins]));
    return allAdmins;
};

/**
 * `sender` is a phone number on WhatsApp/Telegram and a user id on the private engine. Canonicalise
 * it the same way the list was canonicalised, so both kinds compare like with like — matching only
 * on the normalised phone silently excluded every non-phone identity.
 */
const isAdmin = async (sender) => {
  const p = canonAdmin(sender);
  return !!p && (await getAdmins()).includes(p);
}

module.exports = { loadSettings, getSettings, getAdmins, isAdmin, setBotAdmins, canonAdmin };
