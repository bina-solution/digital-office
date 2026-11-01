const { CONFIG } = require('../config');

/**
 * Normalize a phone input to WhatsApp JID-ready local part (E.164 without '+').
 * Rules:
 * - Trim spaces
 * - Remove all non-digits except leading '+'
 * - If starts with '+', drop '+' and return digits
 * - If starts with '00', convert to international by dropping leading '00'
 * - If starts with a single '0' and doesn't start with country code, replace leading '0' with DEFAULT_COUNTRY_CODE
 * - If starts with digits but not with DEFAULT_COUNTRY_CODE, and input length looks like local number, prepend DEFAULT_COUNTRY_CODE
 * - Ensure only digits at the end
 */
const normalizePhone = (input, opts = {}) => {
  const cc = String(opts.countryCode || CONFIG.DEFAULT_COUNTRY_CODE || '').replace(/[^0-9]/g, '');
  if (!input) return '';
  let s = String(input).trim();
  // Keep leading + for now to detect
  s = s.replace(/(?!^)\D/g, '');

  if (s.startsWith('+')) {
    return s.slice(1);
  }
  // convert 00xx.. to international
  if (s.startsWith('00')) {
    return s.slice(2);
  }
  // all digits from here
  s = s.replace(/\D/g, '');
  if (!s) return '';

  // If starts with single 0 (local style): replace leading 0 with country code
  if (s.startsWith('0')) {
    return (cc || '') + s.slice(1);
  }

  // If already starts with country code, keep as-is
  if (cc && s.startsWith(cc)) return s;

  // Heuristic: if looks like local number length (7-10 digits), prepend cc
  if (cc && s.length >= 7 && s.length <= 10) {
    return cc + s;
  }

  // Otherwise return as-is (assumed already international)
  return s;
};

/**
 * Convert a phone number to WhatsApp JID (appending domain).
 * If input already contains '@' (is already a JID), return as-is.
 */
const toWhatsAppJid = (phone) => {
  if (!phone) return '';
  if (String(phone).includes('@')) return String(phone); // already a JID
  const local = normalizePhone(phone);
  if (!local) return '';
  return local + '@s.whatsapp.net';
};

module.exports = { normalizePhone, toWhatsAppJid };
