// Document Query / OCR API helper
// Provides thin wrappers around OCR + JSON query endpoints so higher level
// logic (document_processing etc.) can evolve without coupling to transport.

const fs = require('fs');
const path = require('path');
const axios = require('axios');
const FormData = require('form-data');
const { CONFIG } = require('../config');

/**
 * Upload a file to OCR endpoint to obtain file hash / base OCR data.
 * Mirrors n8n demo: multipart with field name 'file'.
 * @param {string} filePath
 * @param {Object} opts optional flags { dontReturnOcr: boolean }
 * @returns {Promise<{file_hash:string, ocr?:object}|null>}
 */
const performDocumentOcr = async (filePath, opts = {}) => {
	if (!CONFIG.DOCUMENT_OCR_ENDPOINT) {
		throw new Error('DOCUMENT_OCR_ENDPOINT not configured');
	}
	try {
		const abs = path.resolve(filePath);
		const form = new FormData();
		form.append('file', fs.createReadStream(abs));
		if (opts.dontReturnOcr) form.append('dont_return_ocr', 'true');
		const resp = await axios.post(CONFIG.DOCUMENT_OCR_ENDPOINT, form, {
			headers: form.getHeaders(),
			timeout: 60000
		});
		if (!resp.data) throw new Error('No response from OCR API');
		if (resp.data.error) throw new Error('OCR API error: ' + resp.data.error);
		return resp.data;
	} catch (e) {
		// Enrich error message with HTTP status and response details if available
		const status = e?.response?.status;
		const statusText = e?.response?.statusText;
		const respErr = (e?.response?.data && (e.response.data.error || e.response.data.message)) || '';
		const url = CONFIG.DOCUMENT_OCR_ENDPOINT;
		const extra = [
			status ? `status=${status}${statusText ? ' ' + statusText : ''}` : null,
			url ? `url=${url}` : null,
			respErr ? `response_error=${respErr}` : null
		].filter(Boolean).join(' ');
		throw new Error(`performDocumentOcr error: ${e.message}${extra ? ' | ' + extra : ''}`);
	}
};

/**
 * Execute a JSON query against previously OCR-ed file (by file_id / hash)
 * @param {string} fileId file hash/id from OCR step
 * @param {Object} ocrJsonQuery query spec (action, action_value, value_validations, is_rtl, etc.)
 * @returns {Promise<any|null>} raw API response
 */
const performJsonQuery = async (fileId, ocrJsonQuery) => {
	if (!CONFIG.DOCUMENT_JSON_QUERY_ENDPOINT) {
		throw new Error('DOCUMENT_JSON_QUERY_ENDPOINT not configured');
	}
	try {
		const payload = { file_id: fileId, ocr_json_query: ocrJsonQuery };
		const resp = await axios.post(CONFIG.DOCUMENT_JSON_QUERY_ENDPOINT, payload, { timeout: 45000 });
		if (!resp.data) throw new Error('No response from JSON Query API');
		return resp.data;
	} catch (e) {
		throw new Error('performJsonQuery error: ' + e.message);
	}
};

/**
 * Convenience helper to run a set of queries sequentially on same file.
 * queries: { key: ocrJsonQuerySpec }
 * Returns { file_hash, results: { key: response?.result?.result || null } }
 */
const runQueries = async (filePath, queriesMap) => {
	const ocr = await performDocumentOcr(filePath, { dontReturnOcr: true });
	if (!ocr?.file_hash) return { file_hash: null, results: {}, error: 'ocr_failed' };
	const results = {};
	for (const [key, spec] of Object.entries(queriesMap || {})) {
		const qResp = await performJsonQuery(ocr.file_hash, spec);
		results[key] = qResp?.result?.result || null;
	}
	return { file_hash: ocr.file_hash, results };
};

module.exports = { performDocumentOcr, performJsonQuery, runQueries };

// Local ad-hoc test (node document_query_api.js path/to/file.pdf)
if (require.main === module) {
	console.log('Document Query API test');
	const testFile = process.argv[2];
	if (!testFile) {
		console.log('Usage: node document_query_api.js <file>');
		process.exit(0);
	}
	(async () => {
		const ocr = await performDocumentOcr(testFile, { dontReturnOcr: true });
		if (ocr?.file_hash) {
			const demoQuery = { action: 'find after', action_value: ['חשבונית מס', 'invoice'], value_validations: [{ validation_type: 'has_number' }], is_rtl: true };
			const q = await performJsonQuery(ocr.file_hash, demoQuery);
		}
	})();
}

