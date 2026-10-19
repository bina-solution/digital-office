const fs = require('fs');
const path = require('path');
const { CONFIG } = require('../config');
const { fetchCompanies, getCompanies } = require('./companies_api');
const { uploadFileAndGetLink } = require('./document_storage');
const { hashFile } = require('../utils/hash');
const { postIncomingDocumentRecord } = require('./incoming_documents_api');
const { runQueries, performDocumentOcr } = require('./document_query_api');
const { UnableToGuessCompany } = require('./../errors');
const XLSX = require('xlsx');

// Helpers
const tryStatSize = (p) => { try { return fs.statSync(p).size; } catch { return null; } };
const sanitizeCompany = (n) => n.replace(/[^\p{L}0-9-_ ]/gu,'').replace(/\s+/g,'_');

// Fetch full OCR text for a file (best-effort; returns empty string on failure)
const fetchOcrText = async (filePath) => {
  const o = (await performDocumentOcr(filePath))?.ocr_json?.fullTextAnnotation?.text;
  if (!o) throw new Error('No valid OCR text found');
  return String(o);
};

// Extract textual content from non-PDF sources (best-effort, truncated)
const extractStructuredText = async (filePath) => {
  try {
    const ext = path.extname(filePath).toLowerCase();
    if (['.txt', '.log', '.csv'].includes(ext)) return fs.readFileSync(filePath, 'utf8').slice(0, 200000);
    if (ext === '.xls' || ext === '.xlsx') {
      const wb = XLSX.readFile(filePath, { cellDates: false });
      const parts = [];
      for (const s of wb.SheetNames) {
        const ws = wb.Sheets[s]; if (!ws) continue;
        for (const row of XLSX.utils.sheet_to_json(ws, { header: 1, raw: false }) || []) {
          if (!Array.isArray(row)) continue;
          const t = row.filter(v => v!=null && String(v).trim() !== '').join(' ').trim();
          if (t) parts.push(t);
        }
      }
      return parts.join('\n').slice(0, 200000);
    }
    return '';
  } catch (e) { console.warn('[document-processing] extractStructuredText failed', e.message); return ''; }
};

// Guess company by scanning message & OCR text for identifiers / name
const guessDocumentCompany = async (message_text, doc_ocr_text) => {
  await fetchCompanies(false);
  const companies = getCompanies();
  if (!companies || !Object.keys(companies).length) return null;
  const msg = (message_text||'').toLowerCase();
  const ocr = (doc_ocr_text||'').toLowerCase();
  let fallback = null;
  for (const [name, data] of Object.entries(companies)) {
    const identifiers = (data.identifiers||[]).filter(Boolean);
    for (const ident of identifiers) {
      const l = ident.toLowerCase();
      if (msg.includes(l) || ocr.includes(l)) return { companyName: name, identifier: ident };
    }
    const nL = name.toLowerCase();
    if (!fallback && (msg.includes(nL) || ocr.includes(nL))) fallback = { companyName: name, identifier: identifiers[0]||null };
  }
  return fallback;
};

const extractDocumentIds = async (filePath) => {
  try {
    const qMap = {};
    const qCfg = CONFIG.DOCUMENT_JSON_QUERIES || {};
    if (qCfg.INVOICE_ID) qMap.invoice_id = qCfg.INVOICE_ID;
    if (qCfg.SHIPMENT_ID) qMap.shipment_id = qCfg.SHIPMENT_ID;
    const qRes = await runQueries(filePath, qMap);
    const pick = (v) => {
      if (!v) return null;
      if (Array.isArray(v)) v = v[0];
      if (typeof v === 'object') v = v.value || v.text || Object.values(v)[0];
      if (typeof v === 'string') return (v.match(/[0-9]{3,20}/)||[])[0] || null;
      return null;
    };
    const invoice_id = pick(qRes.results?.invoice_id);
    const shipment_id = pick(qRes.results?.shipment_id);
    const document_id = invoice_id || shipment_id || null;
    return { invoice_id, shipment_id, document_id, document_type: invoice_id ? 'invoice' : shipment_id ? 'shipment' : 'unknown', _ocr_file_hash: qRes.file_hash };
  } catch (e) {
    console.warn('[document-processing] extractDocumentIds failed', e?.message || e, 'file:', filePath);
    throw new UnableToGuessCompany('Unable to extract document IDs. Please check the document or provide the IDs explicitly. error: ' + (e?.message || e));
  }
};


// Previous month date string MM.YY (falls back to current)
const computeBalanceSheetDate = (messageDate) => {
  let d = messageDate ? new Date(messageDate) : new Date();
  if (isNaN(d)) { console.warn('[document-processing] Invalid messageDate:', messageDate); d = new Date(); }
  d.setMonth(d.getMonth() - 1);
  return `${String(d.getMonth()+1).padStart(2,'0')}.${String(d.getFullYear()).slice(-2)}`;
};

// Process a balance sheet document (explicit company optional)
const processBalanceSheet = async ({ textContext, filePath, explicitCompany, messageDate, senderId }) => {
  let companyGuess = explicitCompany;
  if (!companyGuess) {
    const ext = path.extname(filePath).toLowerCase();
    let ocrText = ['.txt','.log','.csv','.xls','.xlsx'].includes(ext) ? await extractStructuredText(filePath) : '';
    if (!ocrText) {
      try { ocrText = await fetchOcrText(filePath); }
      catch (e) { console.warn('[document-processing] fetchOcrText failed', e?.message || e, 'file:', filePath); }
    }
    companyGuess = await guessDocumentCompany(textContext||'', ocrText||'');
    if (!companyGuess) throw new UnableToGuessCompany('Unable to guess company by document content. Please provide the explicitCompany parameter.');
  }
  const bsDate = computeBalanceSheetDate(messageDate);
  let renamedPath = filePath;
  if (companyGuess?.companyName) {
    const target = path.join(path.dirname(filePath), `${sanitizeCompany(companyGuess.companyName)}-${bsDate}${path.extname(filePath)||'.pdf'}`);
    try { fs.copyFileSync(filePath, target); renamedPath = target; } catch { /* silent */ }
  }
  const docNameBase = `${companyGuess?.companyName || 'unknown'}-${bsDate}`;
  const docName = `${docNameBase}${path.extname(renamedPath)||''}`;
  // For Drive (gdoc) naming we want <company_name>-<doc_id>. For balance sheet, doc_id equivalent is the bsDate
  const driveLink = await uploadFileAndGetLink(renamedPath, docNameBase);
  const fileSize = tryStatSize(renamedPath);
  const fileHash = hashFile(renamedPath);
  const incoming_doc = {
    NAME: docName,
    LINK: driveLink,
    TYPE: 'BALANCE_SHEET',
    SOURCE_TYPE: 'WHATSAPP',
    SOURCE_ID: senderId || null,
    SOURCE_LINK: senderId ? `https://wa.me/${encodeURIComponent(String(senderId).replace(/[^0-9+]/g,''))}` : null,
    SIZE: fileSize,
    HASH: fileHash,
    STATUS: companyGuess?.companyName ? 'COMPLETED' : 'ACTION_REQUIRED',
    REQUIRED_ACTION: companyGuess?.companyName ? null : 'Missing company name'
  };
  if (companyGuess?.identifier) incoming_doc.COMPANY_ID = companyGuess.identifier;
  await postIncomingDocumentRecord(incoming_doc);
  return { incoming_doc, companyGuess, docName, driveLink, fileHash, fileSize };
};

// Process a generic (invoice / shipment / unknown) document
const processGeneralDocument = async ({ textContext, filePath, explicitCompany, messageDate, senderId }) => {
  console.log('Processing generic document:', { textContext, filePath, explicitCompany, messageDate, senderId });
  
  let companyGuess = explicitCompany;
  if (!companyGuess) {
    try { companyGuess = await guessDocumentCompany(textContext||'', await fetchOcrText(filePath)); }
    catch (e) { console.warn('[document-processing] fetchOcrText (generic) failed', e?.message || e, 'file:', filePath); }
  }
  const ids = await extractDocumentIds(filePath);
  console.log('Generic document processed:', ids);
  const fileSize = tryStatSize(filePath);
  const fileHash = hashFile(filePath);

  // document id in should be unknown or 5 digit (startpadding with 0s)
  const paddedDocId = String(ids.document_id || 'unknown').padStart(5, '0');
  const docName = `${companyGuess?.companyName || 'unknown'}-${paddedDocId}${path.extname(filePath)||''}`;
  const driveLink = await uploadFileAndGetLink(filePath, docName);
  const incoming_doc = {
    NAME: `${companyGuess?.companyName || 'unknown'}-${ids.document_id || 'unknown'}${path.extname(filePath)||'.pdf'}`,
    LINK: driveLink,
    TYPE: ids.document_type === 'invoice' ? 'INVOICE' : ids.document_type === 'shipment' ? 'SHIPMENT' : 'UNKNOWN',
    SOURCE_TYPE: 'WHATSAPP',
    SOURCE_ID: senderId || null,
    SOURCE_LINK: senderId ? `https://wa.me/${encodeURIComponent(String(senderId).replace(/[^0-9+]/g,''))}` : null,
    SIZE: fileSize,
    HASH: fileHash,
    STATUS: (companyGuess?.companyName && ids.document_id) ? 'COMPLETED' : 'ACTION_REQUIRED'
  };
  if (companyGuess?.identifier) incoming_doc.COMPANY_ID = companyGuess.identifier;
  await postIncomingDocumentRecord(incoming_doc);
  return { incoming_doc, companyGuess, ids, driveLink, fileHash, fileSize };
};

// Download a file from URL and process it as a generic document
const processLinkDocument = async ({ url, textContext, messageDate, senderId }) => {
  console.log('[link-doc] Downloading from URL:', url);
  const axios = require('axios');
  
  // Follow redirects and download the file
  const response = await axios.get(url, { 
    responseType: 'arraybuffer', 
    timeout: 60000,
    maxRedirects: 10,
    headers: { 'User-Agent': 'Mozilla/5.0 (compatible; HacohenBot/1.0)' }
  });
  
  const buffer = Buffer.from(response.data);
  if (buffer.length < 100) throw new Error('Downloaded file is too small or empty');
  
  // Determine filename from Content-Disposition header or URL
  let fileName = 'downloaded_file';
  const disposition = response.headers['content-disposition'];
  if (disposition) {
    const match = disposition.match(/filename[*]?=(?:UTF-8''|"?)([^";\n]+)/i);
    if (match) fileName = decodeURIComponent(match[1].trim());
  }
  if (fileName === 'downloaded_file') {
    // Try to extract from URL path
    try {
      const urlPath = new URL(url).pathname;
      const urlFile = path.basename(urlPath);
      if (urlFile && urlFile.includes('.')) fileName = urlFile;
    } catch { /* ignore */ }
  }
  
  // Determine extension from content-type if not in filename
  let ext = path.extname(fileName);
  if (!ext) {
    const contentType = (response.headers['content-type'] || '').split(';')[0].trim();
    const extMap = { 'application/pdf': '.pdf', 'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp',
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx', 'application/vnd.ms-excel': '.xls',
      'text/csv': '.csv', 'text/plain': '.txt' };
    ext = extMap[contentType] || '.bin';
    fileName += ext;
  }
  
  // Save to uploads dir
  const uploadsDir = CONFIG.UPLOADS_DIR;
  if (!fs.existsSync(uploadsDir)) fs.mkdirSync(uploadsDir, { recursive: true });
  const safeBase = path.basename(fileName, path.extname(fileName)).replace(/[^\p{L}0-9-_ ]/gu, '').replace(/\s+/g, '_').slice(0, 80) || 'downloaded';
  const filePath = path.join(uploadsDir, Date.now() + '_' + safeBase + (path.extname(fileName) || '.bin'));
  fs.writeFileSync(filePath, buffer);
  console.log('[link-doc] Saved downloaded file:', filePath, 'size:', buffer.length);
  
  // Process as generic document
  return processGeneralDocument({ textContext: (textContext || '') + ' ' + url, filePath, messageDate, senderId });
};

module.exports = { processBalanceSheet, processGeneralDocument, processLinkDocument, guessDocumentCompany };



// Live Tests the functions like with taking args
function test_process_balance_sheet(filepath) {
  console.log('Testing processBalanceSheet...');
  (async () => {
  const result = await processBalanceSheet({ filePath: filepath, textContext: '', explicitCompany: null, messageDate: "2025-01-15", senderId: 'TEST_SENDER' });
    console.log('Processing result:', result);
  })();
}

if (require.main === module) {
	console.log('Document Processing Tests');
	const testFile = process.argv[2];
	if (!testFile) {
		console.log('Usage: node document_processing.js <file>');
		process.exit(0);
	}
  
	test_process_balance_sheet(testFile);
}