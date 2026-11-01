// Currency conversion service: USD → ILS with 1-day in-memory cache.
// Fetches exchange rate from a free API (no key required).

const API_URL = process.env.CURRENCY_API_URL || 'https://api.exchangerate-api.com/v4/latest/USD';
const FALLBACK_RATE = parseFloat(process.env.CURRENCY_FALLBACK_RATE || '3.7');

let cachedRate = null;   // { ilsPerUsd: number, fetchedAt: number }
const CACHE_TTL_MS = 24 * 60 * 60 * 1000; // 1 day

/**
 * Fetch the current USD/ILS exchange rate.
 * Cached in-memory for 24 hours to avoid hammering the API.
 * @returns {Promise<number>} ILS per 1 USD
 */
const fetchUsdToIlsRate = async () => {
  const now = Date.now();
  if (cachedRate && (now - cachedRate.fetchedAt < CACHE_TTL_MS)) {
    return cachedRate.ilsPerUsd;
  }

  try {
    const res = await fetch(API_URL, { signal: AbortSignal.timeout(10_000) });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const ilsPerUsd = data?.rates?.ILS;
    if (typeof ilsPerUsd !== 'number' || ilsPerUsd <= 0) {
      throw new Error(`Unexpected ILS rate: ${ilsPerUsd}`);
    }
    cachedRate = { ilsPerUsd, fetchedAt: now };
    console.log(`[currency] USD/ILS rate updated: ${ilsPerUsd} (cached 24h)`);
    return ilsPerUsd;
  } catch (e) {
    // If we have a stale cache, serve it rather than failing entirely.
    if (cachedRate) {
      console.warn(`[currency] Failed to refresh rate, using stale cache (${Math.round((now - cachedRate.fetchedAt) / 3600000)}h old):`, e.message);
      return cachedRate.ilsPerUsd;
    }
    // Last resort: a reasonable fallback.
    console.warn('[currency] No cache available, using fallback rate:', e.message);
    return FALLBACK_RATE;
  }
};

/**
 * Convert a USD amount to ILS and return a formatted string.
 * @param {number} usdAmount - Amount in US Dollars
 * @returns {Promise<string>} e.g. "₪6.85"
 */
const formatUsdAsIls = async (usdAmount) => {
  if (typeof usdAmount !== 'number' || usdAmount < 0) return '₪0.00';
  const rate = await fetchUsdToIlsRate();
  const ils = usdAmount * rate;
  return `₪${ils.toFixed(2)}`;
};

/**
 * Convert a USD amount to ILS and return the raw number + formatted string.
 * Useful when both representations are needed (e.g. "USD + ILS" footers).
 * @param {number} usdAmount
 * @returns {Promise<{ils: number, formatted: string, rate: number}>}
 */
const convertUsdToIls = async (usdAmount) => {
  const rate = await fetchUsdToIlsRate();
  const ils = (typeof usdAmount === 'number' ? usdAmount : 0) * rate;
  return { ils, formatted: `₪${ils.toFixed(2)}`, rate };
};

module.exports = { fetchUsdToIlsRate, formatUsdAsIls, convertUsdToIls };
