// Central Incoming Documents API helper
// Responsible solely for posting prepared document records to the remote API.
// Keep this file focused on transport / retries / logging so business logic stays
// inside the document processing module.

const axios = require('axios');
const { CONFIG } = require('../config');

/**
 * Post a document record to the central incoming documents webhook.
 * @param {Object} record - Prepared payload with required fields
 * @returns {Promise<{posted: boolean, error?: string}>}
 */
const postIncomingDocumentRecord = async (record) => {
  const payload = Array.isArray(record) ? record : [record];

  // Primary path: INDOX API documents endpoint
  if (CONFIG.INDOX_API_BASE) {
    const indoxUrl = `${CONFIG.INDOX_API_BASE}${CONFIG.INDOX_API_PREFIX}/documents`;
    try {
      await axios.post(indoxUrl, payload, { timeout: 30000 });
      return { posted: true };
    } catch (e) {
      console.warn('[incoming-documents-api] INDOX API post failed, trying fallback webhook if configured:', e.message);
    }
  }

  // Fallback path: n8n webhook (if configured)
  if (CONFIG.INCOMING_DOCS_WEBHOOK) {
    try {
      await axios.post(CONFIG.INCOMING_DOCS_WEBHOOK, record, {
        timeout: 360000,
        auth: { username: CONFIG.N8N_INCOMING_DOCS_USER, password: CONFIG.N8N_INCOMING_DOCS_PASS }
      });
      return { posted: true };
    } catch (e) {
      throw new Error('Post to INCOMING_DOCS_WEBHOOK failed: ' + e.message);
    }
  }

  return { posted: false, error: 'No reachable INDOX API or fallback webhook' };
};

module.exports = { postIncomingDocumentRecord };
