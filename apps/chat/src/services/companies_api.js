const axios = require('axios');
const { CONFIG } = require('../config');

// In-memory cache of companies { name: { identifiers: string[], mails: string[] } }
let companiesCache = {};
let lastFetchTs = 0;
const CACHE_TTL_MS = 1000 * 60 * 15; // 15m

/**
 * Companies belong to INDOX, and chat reads them through indox's own API.
 *
 * They used to arrive over an n8n webhook that cached them in an n8n KV and, on a miss, ran a
 * sub-workflow against indox's table. That is three owners for one value and no API boundary
 * anywhere: chat could not tell where the data came from, indox could not change its schema without
 * breaking a workflow it does not own, and the value was stale by however long the KV held it.
 *
 * `GET /incomingDocuments/config/companies` is indox's published surface and returns its ROWS, so
 * the projection into the shape this bot wants happens here — in the consumer, where it belongs.
 * The Hebrew column names are indox's own; they are read defensively (a missing column yields an
 * empty list, never a crash) because indox owns that schema and may add to it.
 */
function projectIndoxRows(rows) {
  const out = {};
  for (const r of rows || []) {
    const name = String(r['שם חברה'] || r.company_name || '').trim();
    if (!name) continue;
    const pick = (...keys) => keys.map((k) => r[k]).filter((v) => v !== null && v !== undefined && String(v).trim() !== '').map(String);
    out[name] = {
      identifiers: pick('מזהה 1', 'מזהה 2', 'identifier_1', 'identifier_2'),
      mails: pick('מייל 1', 'מייל 2', 'mail_1', 'mail_2'),
    };
  }
  return out;
}

const fetchCompanies = async (force = false) => {
  if (!force && Date.now() - lastFetchTs < CACHE_TTL_MS && Object.keys(companiesCache).length) {
    return companiesCache;
  }

  // 1. indox's API — the supported path.
  if (CONFIG.INDOX_API_BASE) {
    const url = `${CONFIG.INDOX_API_BASE}${CONFIG.INDOX_API_PREFIX}/config/companies`;
    try {
      const res = await axios.get(url, { timeout: 20000 });
      const projected = projectIndoxRows(res.data && res.data.companies);
      if (Object.keys(projected).length) {
        companiesCache = projected;
        lastFetchTs = Date.now();
        console.log(`[integration] Loaded ${Object.keys(companiesCache).length} companies from the indox API`);
        return companiesCache;
      }
      // An EMPTY answer is not a failure — a deployment may genuinely have no companies yet — but it
      // is not worth caching either, so fall through and let the legacy path have a say.
      console.log('[integration] indox API returned no companies; trying the legacy webhook');
    } catch (e) {
      console.warn(`[integration] indox API unavailable (${e.message}); trying the legacy webhook`);
    }
  }

  // 2. The n8n webhook — kept only as a MIGRATION fallback, for a deployment whose indox predates
  //    the /config/companies endpoint. It is the coupling this change exists to remove; delete it
  //    once no live deployment needs it.
  if (!CONFIG.N8N_COMPANY_WEBHOOK) {
    throw new Error('[integration] no company source: neither INDOX_API_BASE nor N8N_COMPANY_WEBHOOK');
  }
  try {
    const res = await axios.get(CONFIG.N8N_COMPANY_WEBHOOK, {
      timeout: 60000,
      auth: { username: CONFIG.N8N_SETTINGS_USER, password: CONFIG.N8N_SETTINGS_PASS }
    });
    companiesCache = res.data?.companies || {};
    lastFetchTs = Date.now();
    console.log(`[integration] Loaded ${Object.keys(companiesCache).length} companies (legacy webhook)`);
  } catch (e) {
    throw new Error('[integration] Failed to fetch companies: ' + e.message);
  }
  return companiesCache;
};

// Find company by free input (identifier or partial name)
const findCompanyByInput = (input) => {
  if (!input) return null;
  const text = input.trim().toLowerCase();
  // identifier direct match
  for (const [name, data] of Object.entries(companiesCache)) {
    if ((data.identifiers||[]).some(id => id && id.toLowerCase() === text)) {
      return { companyName: name, identifier: text };
    }
  }
  // partial name includes
  let candidates = Object.keys(companiesCache).filter(n => n.toLowerCase().includes(text));
  if (candidates.length === 1) {
    const name = candidates[0];
    return { companyName: name, identifier: (companiesCache[name].identifiers||[])[0] || null };
  }
  return null;
};


module.exports = { fetchCompanies, getCompanies: () => companiesCache, findCompanyByInput };
