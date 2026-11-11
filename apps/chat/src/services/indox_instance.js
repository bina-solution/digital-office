// Which INDOX instance chat's calls to INDOX act on (DGO-1815, issues/an-indox-call-without-an-instance-…).
//
// chat posted WhatsApp documents to INDOX's POST /documents and read GET /config/companies with no instance, and
// INDOX answers such a call on the first client's books. A call now names its instance:
//   1. INDOX_INSTANCE, when the office declares it (the same id chat's legacy settings source sends as __instance);
//   2. else the ONE enabled instance INDOX lists (GET /instances) whose purpose is not 'test' — the office's own
//      default, the rule apps/indox/hooks/_schema-lib.sh applies: every office carries the standing `test` tenant, so
//      «the only enabled instance» never resolves. Cached for five minutes;
//   3. else none — two production instances and no declaration cannot be guessed. The call goes on as before
//      (INDOX's own log names it, stage one) and this says why, once per ten minutes. Refusing such a call is
//      INDOX's step (stage three: 400 once its log is empty), not a caller's.
// An unresolved or failed answer is kept for one minute, so a burst of posts does not ask once per post; a failed
// refresh keeps the last good id (INDOX not answering does not change its registry).

const ID = /^[a-z][a-z0-9_]*$/;
const TTL_MS = 5 * 60 * 1000;
const MISS_MS = 60 * 1000;
const SAY_MS = 10 * 60 * 1000;

function instanceResolver({ declared = '', get, base, prefix, now = Date.now, warn = console.warn }) {
  let cached = '';
  let at = null;                              // null = never asked (a clock can read 0)
  let ttl = TTL_MS;                           // how long the answer at `at` holds
  let said = null;                            // null = never said (a clock can read 0)
  const say = (msg) => {
    if (said === null || now() - said >= SAY_MS) { said = now(); warn(`[indox-instance] ${msg}`); }
  };
  return async function indoxInstance() {
    const named = String(declared || '').trim();
    if (named) {
      if (ID.test(named)) return named;
      say(`INDOX_INSTANCE=${JSON.stringify(named)} is not an instance id — chat names none`);
      return '';
    }
    if (at !== null && now() - at < ttl) return cached;
    try {
      const r = await get(`${base}${prefix}/instances`, { timeout: 10000 });
      const rows = ((r && r.data && r.data.instances) || [])
        .filter((x) => x && x.enabled !== false && ID.test(String(x.id || '')) && String(x.purpose || '') !== 'test');
      if (rows.length === 1) {
        cached = String(rows[0].id);
        ttl = TTL_MS;
      } else {
        cached = '';                          // the registry ANSWERED and names no single tenant: drop the old one
        ttl = MISS_MS;
        say(rows.length
          ? `INDOX lists ${rows.length} enabled production instances and INDOX_INSTANCE is not set — chat names none`
          : 'INDOX lists no enabled production instance (or an INDOX that does not say purpose) — chat names none');
      }
    } catch (e) {
      // INDOX not answering does not change its registry: a good id is kept, and asked again in a minute
      ttl = MISS_MS;
      say(`GET /instances failed (${e && e.message}) — ${cached ? `keeping ${cached}` : 'chat names none'} for a minute`);
    }
    at = now();
    return cached;
  };
}

/** `params` for an axios call to INDOX: `{ instance }` when there is one, else nothing extra. */
async function instanceParams(resolve) {
  const instance = await resolve();
  return instance ? { instance } : {};
}

let shared = null;
/** The resolver chat's services use: CONFIG's INDOX address and declaration, axios to ask. */
function defaultResolver() {
  if (!shared) {
    const axios = require('axios');
    const { CONFIG } = require('../config');
    shared = instanceResolver({ declared: CONFIG.INDOX_INSTANCE, get: axios.get, base: CONFIG.INDOX_API_BASE,
      prefix: CONFIG.INDOX_API_PREFIX });
  }
  return shared;
}

module.exports = { defaultResolver, instanceParams, instanceResolver };
