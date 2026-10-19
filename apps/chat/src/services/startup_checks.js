const axios = require('axios');
const { CONFIG } = require('../config');

/**
 * Run all external integration checks and print a startup report.
 * Each check is independent — failures are logged but don't block startup.
 */
const runStartupChecks = async () => {
  console.log('[startup-checks] ═══════════════════════════════════════');
  console.log('[startup-checks]  External Integration Health Report');
  console.log('[startup-checks] ═══════════════════════════════════════');

  const checks = [
    {
      name: 'N8N Settings Webhook',
      fn: () => checkN8nSettings(),
    },
    {
      name: 'N8N Company Webhook',
      fn: () => checkN8nCompany(),
    },
    {
      name: 'INDOX API Document Storage',
      fn: () => checkIndoxApiStorage(),
    },
    {
      name: 'Apitools Document OCR',
      fn: () => checkEndpointReachable(CONFIG.DOCUMENT_OCR_ENDPOINT, 'DOCUMENT_OCR_ENDPOINT'),
    },
    {
      name: 'Apitools JSON Query',
      fn: () => checkEndpointReachable(CONFIG.DOCUMENT_JSON_QUERY_ENDPOINT, 'DOCUMENT_JSON_QUERY_ENDPOINT'),
    },
    {
      name: 'GlitchTip / Sentry DSN',
      fn: () => checkGlitchTip(),
    },
  ];

  const results = [];
  for (const check of checks) {
    try {
      const result = await check.fn();
      results.push({ name: check.name, ...result });
    } catch (e) {
      results.push({ name: check.name, status: 'FAIL', detail: e.message });
    }
  }

  // Print report
  let failCount = 0;
  let warnCount = 0;
  for (const r of results) {
    const icon = r.status === 'OK' ? '✅' : r.status === 'WARN' ? '⚠️' : '❌';
    if (r.status === 'FAIL') failCount++;
    if (r.status === 'WARN') warnCount++;
    const detail = r.detail ? ` — ${r.detail}` : '';
    console.log(`[startup-checks]  ${icon} ${r.name}${detail}`);
  }

  console.log('[startup-checks] ───────────────────────────────────────');
  const total = results.length;
  const ok = total - failCount - warnCount;
  console.log(`[startup-checks]  ${ok}/${total} OK, ${warnCount} warnings, ${failCount} failures`);
  console.log('[startup-checks] ═══════════════════════════════════════');

  return results;
};

// ── Individual checks ────────────────────────────────────────────────

async function checkN8nSettings() {
  // ADVISORY: the n8n `setting` webhook is the LEGACY source for whatsapp_admins.
  // Admins are now owned by the chat app itself (per-connection botAdmins) and by
  // the INDOX API (/config/settings), so a failing/missing legacy webhook must not
  // read as a hard integration failure. This check reports WARN, never FAIL.
  if (!CONFIG.N8N_SETTINGS_WEBHOOK) return { status: 'WARN', detail: 'URL not configured' };
  // Tenant-scoped since the 2026-08-28 cutover: a tenantless probe is an ERROR EXECUTION in
  // n8n (the settings chain throws server-side), so probing without a tenant does not measure
  // health — it manufactures noise. No tenant -> don't call.
  if (!CONFIG.INDOX_INSTANCE) return { status: 'WARN', detail: 'legacy source disabled (INDOX_INSTANCE not set)' };
  try {
    const res = await axios.get(CONFIG.N8N_SETTINGS_WEBHOOK, {
      timeout: 10000,
      params: { key: 'whatsapp_admins', TRIGGERED_FROM: 'HEALTH_CHECK',
                __instance: CONFIG.INDOX_INSTANCE },
      auth: { username: CONFIG.N8N_SETTINGS_USER, password: CONFIG.N8N_SETTINGS_PASS },
      validateStatus: () => true,
    });
    if (res.status === 200 && Array.isArray(res.data?.val)) {
      return { status: 'OK', detail: `${res.data.val.length} admins` };
    }
    return { status: 'WARN', detail: `HTTP ${res.status} (legacy source; admins owned by chat/INDOX)` };
  } catch (e) {
    return { status: 'WARN', detail: `unreachable (${e.message}); legacy source` };
  }
}

async function checkN8nCompany() {
  if (!CONFIG.N8N_COMPANY_WEBHOOK) return { status: 'WARN', detail: 'URL not configured' };
  // Same tenant scoping as checkN8nSettings — tenantless probes manufacture n8n error
  // executions since the cutover instead of measuring anything.
  if (!CONFIG.INDOX_INSTANCE) return { status: 'WARN', detail: 'legacy source disabled (INDOX_INSTANCE not set)' };
  const res = await axios.get(CONFIG.N8N_COMPANY_WEBHOOK, {
    timeout: 10000,
    params: { __instance: CONFIG.INDOX_INSTANCE },
    auth: { username: CONFIG.N8N_SETTINGS_USER, password: CONFIG.N8N_SETTINGS_PASS },
    validateStatus: () => true,
  });
  if (res.status === 200 && res.data?.companies) {
    const count = Object.keys(res.data.companies).length;
    return { status: 'OK', detail: `${count} companies` };
  }
  if (res.status === 401 || res.status === 403) {
    return { status: 'FAIL', detail: `Auth rejected (${res.status})` };
  }
  return { status: 'WARN', detail: `HTTP ${res.status}` };
}

async function checkIndoxApiStorage() {
  if (!CONFIG.INDOX_API_BASE) return { status: 'WARN', detail: 'INDOX_API_BASE not configured' };
  try {
    const res = await axios.get(`${CONFIG.INDOX_API_BASE}${CONFIG.INDOX_API_PREFIX}/health`, {
      timeout: 10000,
      validateStatus: () => true,
    });
    if (res.status === 200) {
      return { status: 'OK', detail: `reachable (${CONFIG.INDOX_API_BASE})` };
    }
    return { status: 'WARN', detail: `HTTP ${res.status}` };
  } catch (e) {
    return { status: 'FAIL', detail: e.message };
  }
}

async function checkEndpointReachable(url, configKey) {
  if (!url) return { status: 'WARN', detail: `${configKey} not configured` };
  try {
    // Use GET — API will likely return 405 or 200, both mean it's reachable
    const res = await axios.get(url, { timeout: 10000, validateStatus: () => true });
    if (res.status < 500) {
      return { status: 'OK', detail: `reachable (HTTP ${res.status})` };
    }
    return { status: 'FAIL', detail: `HTTP ${res.status}` };
  } catch (e) {
    return { status: 'FAIL', detail: e.message };
  }
}

async function checkGlitchTip() {
  const dsn = process.env.SENTRY_DSN || '';
  if (!dsn) return { status: 'WARN', detail: 'SENTRY_DSN not set' };
  // Parse DSN to extract host and verify it's reachable
  try {
    const url = new URL(dsn);
    const healthUrl = `${url.protocol}//${url.host}/_health/`;
    const res = await axios.get(healthUrl, { timeout: 10000, validateStatus: () => true });
    if (res.status === 200) {
      return { status: 'OK', detail: `DSN configured, server healthy` };
    }
    return { status: 'WARN', detail: `DSN set but health check returned HTTP ${res.status}` };
  } catch (e) {
    return { status: 'WARN', detail: `DSN set but server unreachable: ${e.message}` };
  }
}

module.exports = { runStartupChecks };
