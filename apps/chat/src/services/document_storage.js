// Centralized document storage helpers: upload file to n8n (Drive) and hash utilities
const fs = require('fs');
const path = require('path');
const axios = require('axios');
const mime = require('mime-types');
const { CONFIG } = require('../config');

/**
 * Upload a file to the configured n8n webhook and return a public/drive link (if any)
 * Returns null on failure or if webhook not configured.
 * @param {string} filePath absolute/relative path to file
 * @param {string|null} overrideName optional filename to use in Drive instead of the file's basename
 * @returns {Promise<string|null>} web content link
 */
const uploadFileAndGetLink = async (filePath, overrideName = null) => {
  const fileName = overrideName || path.basename(filePath);
  const mimeType = mime.lookup(filePath) || 'application/octet-stream';
  const content = fs.readFileSync(filePath).toString('base64');

  // Primary path: INDOX API upload endpoint
  if (CONFIG.INDOX_API_BASE) {
    const indoxUrl = `${CONFIG.INDOX_API_BASE}${CONFIG.INDOX_API_PREFIX}/documents/upload`;
    try {
      const resp = await axios.post(indoxUrl, { fileName, mimeType, content }, { timeout: 30000 });
      const link = resp.data?.link || resp.data?.webViewLink;
      if (link) return link;
    } catch (e) {
      console.warn('[document-storage] INDOX API upload failed, trying fallback webhook if configured:', e.message);
    }
  }

  // Fallback path: n8n webhook (if configured)
  if (CONFIG.N8N_UPLOAD_DOC_WEBHOOK && CONFIG.N8N_UPLOAD_DOC_USER && CONFIG.N8N_UPLOAD_DOC_PASS) {
    try {
      const axiosOptions = { 
        timeout: 30000,
        auth: { username: CONFIG.N8N_UPLOAD_DOC_USER, password: CONFIG.N8N_UPLOAD_DOC_PASS }
      };
      const resp = await axios.post(
        CONFIG.N8N_UPLOAD_DOC_WEBHOOK,
        { fileName, mimeType, content },
        axiosOptions
      );
      if (resp.data?.webViewLink || resp.data?.link) return resp.data.webViewLink || resp.data.link;
    } catch (e) {
      throw new Error('File upload fallback error: ' + e.message);
    }
  }

  throw new Error('File upload failed: INDOX API and fallback webhook failed or not configured');
};

module.exports = { uploadFileAndGetLink };



// Local testing, execute by runing script directly 
function test_UploadFileAndGetLink() {
    const testFilePath = __dirname + '/tests/files/test.pdf'; // Path to a test file
    uploadFileAndGetLink(testFilePath)
        .then(link => {
            console.log('Test file upload link:', link);
        })
        .catch(err => {
            console.error('Error uploading test file:', err);
        });
}

if (require.main === module) {
    // This code runs only when the file is executed directly
    console.log("Running as main script");
    test_UploadFileAndGetLink();
}
