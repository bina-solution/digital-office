// INDOX shared normalizer registry — Step 1 (design §E.1).
// VERBATIM copy from indoxV2ActionsGDoc01 'Selection & Scoring Logic1' — the SINGLE source of truth
// for extraction/selection normalizers. Engines (kwExtract01, select01, ...) embed this so
// normalization stays universal + byte-identical. DO NOT diverge a copy; edit here + re-embed.
// A named registry lets fixtures reference a normalizer by name (e.g. "docid_last5").

function makeNormalizers() {
  const has = (v) => v != null && v !== "" && String(v).toLowerCase() !== "unknown";

  function normalizeCompanyID(val) {
      if (!has(val)) return null;
      let digitsOnly = String(val).replace(/\D/g, '');
      return digitsOnly.slice(-6).padStart(6, '0');
    }

  function normalizeDocID(val) {
      if (!has(val)) return null;
      let digitsOnly = String(val).replace(/\D/g, '');
      return digitsOnly.slice(-5).padStart(5, '0');
    }

  function normalizeAmount(val) {
      if (!has(val)) return null;
      let num = parseFloat(String(val).replace(/[^\d.-]/g, ''));
      return isNaN(num) ? null : num.toFixed(2);
    }

  function normalizeDate(val) {
      if (!has(val)) return null;
      let s = String(val).trim().replace(/\s+/g, '');
      let day, month, year, match;
      if (/^\d{5}(\.\d+)?$/.test(s)) {
        const dateObj = new Date(Math.round((parseFloat(s) - 25569) * 86400 * 1000));
        day = String(dateObj.getDate()).padStart(2, '0');
        month = String(dateObj.getMonth() + 1).padStart(2, '0');
        year = dateObj.getFullYear();
      } else if (match = s.match(/^(\d{1,2})[\/\.\-](\d{1,2})[\/\.\-](\d{2,4})$/)) {
        day = match[1].padStart(2, '0');
        month = match[2].padStart(2, '0');
        year = match[3].length === 2 ? '20' + match[3] : match[3];
      } else if (match = s.match(/^(\d{4})[\/\.\-](\d{1,2})[\/\.\-](\d{1,2})$/)) {
        year = match[1]; month = match[2].padStart(2, '0'); day = match[3].padStart(2, '0');
      } else {
        const parsed = new Date(s);
        if (isNaN(parsed.getTime())) return s;
        day = String(parsed.getDate()).padStart(2, '0');
        month = String(parsed.getMonth() + 1).padStart(2, '0');
        year = parsed.getFullYear();
      }
      return `${day}/${month}/${year}`;
    }

  function normalizeDocType(val) {
      if (!has(val)) return null;
      return String(val).trim().toUpperCase();
    }

  function isEmptyOrEmptyArray(val) {
      if (!has(val)) return true;
      const s = String(val).trim();
      return s === '[]' || s === '';
    }

  function extractFirstShipmentID(val) {
      if (!has(val)) return null;
      const s = String(val).trim();
      try {
        const arr = JSON.parse(s);
        if (Array.isArray(arr) && arr.length > 0) return String(arr[0]).trim();
      } catch (e) {}
      if (s.includes(',')) {
        return s.split(',')[0].trim();
      }
      return s.replace(/^\[|\]$/g, '').replace(/"/g, '').trim() || null;
    }

  function resolveDate(dateAI, dateBS, dateKW) {
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      const SIX_MONTHS_MS = 180 * 24 * 60 * 60 * 1000;
  
      function parseDD_MM_YYYY(str) {
        if (!str) return null;
        const parts = str.split('/');
        if (parts.length !== 3) return null;
        const dt = new Date(Number(parts[2]), Number(parts[1]) - 1, Number(parts[0]));
        return isNaN(dt.getTime()) ? null : dt;
      }
  
      const candidates = [
        { label: 'AI', val: dateAI },
        { label: 'BS', val: dateBS },
        { label: 'KW', val: dateKW }
      ]
        .filter(c => has(c.val))
        .map(c => ({ ...c, dt: parseDD_MM_YYYY(c.val) }))
        .filter(c => c.dt !== null);
  
      if (candidates.length === 0) return null;
      if (candidates.length === 1) return candidates[0].val;
  
      const uniqueVals = [...new Set(candidates.map(c => c.val))];
      if (uniqueVals.length === 1) return uniqueVals[0];
  
      candidates.sort((a, b) => b.dt - a.dt);
      const newest = candidates[0];
      const oldest = candidates[candidates.length - 1];
      const gap = newest.dt - oldest.dt;
  
      if (gap > SIX_MONTHS_MS) {
        const nonFuture = candidates.filter(c => c.dt <= today);
        if (nonFuture.length > 0) return nonFuture[0].val;
        return oldest.val;
      }
  
      return dateAI || dateBS || dateKW;
    }

  // name -> fn registry (fixtures reference these names)
  const registry = {
    docid_last5:     normalizeDocID,
    companyid_last6: normalizeCompanyID,
    amount_2dp:      normalizeAmount,
    date_ddmmyyyy:   normalizeDate,
    uppercase:       normalizeDocType,
    trim:            (v) => has(v) ? String(v).trim() : null,
    id_clean:        (v) => has(v) ? (String(v).replace(/[^A-Za-z0-9]/g,"").toUpperCase() || null) : null,
  };
  return { has, registry, normalizeDocID, normalizeCompanyID, normalizeAmount, normalizeDate,
           normalizeDocType, isEmptyOrEmptyArray, extractFirstShipmentID, resolveDate };
}

// n8n usage: const N = makeNormalizers(); N.registry['docid_last5'](val)
if (typeof module !== 'undefined') module.exports = { makeNormalizers };